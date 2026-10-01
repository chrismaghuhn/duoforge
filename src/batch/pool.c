#include "batch/pool.h"

#include "core/alloc.h"

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
typedef HANDLE dfi_thread;
typedef SRWLOCK dfi_mutex;
typedef CONDITION_VARIABLE dfi_cond;
#else
#include <pthread.h>
typedef pthread_t dfi_thread;
typedef pthread_mutex_t dfi_mutex;
typedef pthread_cond_t dfi_cond;
#endif

typedef struct dfi_worker {
    struct dfi_pool *pool;
    uint32_t index;
    dfi_thread thread;
    bool started;
} dfi_worker;

struct dfi_pool {
    uint32_t workers;
    dfi_mutex lock;
    dfi_cond start; /* a new job or the shutdown */
    dfi_cond done;  /* the last slice of a job finished */
    uint64_t generation;
    uint32_t pending; /* slices of the current job still running on workers */
    bool shutdown;
    dfi_pool_fn fn;
    void *job;
    uint32_t items;
    dfi_worker *worker; /* workers - 1 threads; slice 0 is the caller's */
};

#if defined(_WIN32)
static void dfi_lock(dfi_mutex *m)
{
    AcquireSRWLockExclusive(m);
}
static void dfi_unlock(dfi_mutex *m)
{
    ReleaseSRWLockExclusive(m);
}
static void dfi_wait(dfi_cond *c, dfi_mutex *m)
{
    (void)SleepConditionVariableSRW(c, m, INFINITE, 0);
}
static void dfi_wake_all(dfi_cond *c)
{
    WakeAllConditionVariable(c);
}
#else
static void dfi_lock(dfi_mutex *m)
{
    (void)pthread_mutex_lock(m);
}
static void dfi_unlock(dfi_mutex *m)
{
    (void)pthread_mutex_unlock(m);
}
static void dfi_wait(dfi_cond *c, dfi_mutex *m)
{
    (void)pthread_cond_wait(c, m);
}
static void dfi_wake_all(dfi_cond *c)
{
    (void)pthread_cond_broadcast(c);
}
#endif

static void dfi_slice(const struct dfi_pool *p, uint32_t w, uint32_t *begin, uint32_t *end)
{
    *begin = (uint32_t)(((uint64_t)p->items * w) / p->workers);        /* wide-operands-reviewed */
    *end = (uint32_t)(((uint64_t)p->items * (w + 1u)) / p->workers); /* wide-operands-reviewed */
}

static void dfi_worker_loop(dfi_worker *self)
{
    struct dfi_pool *p = self->pool;
    uint64_t seen = 0u;
    for (;;) {
        dfi_lock(&p->lock);
        while (p->generation == seen && !p->shutdown) {
            dfi_wait(&p->start, &p->lock);
        }
        if (p->shutdown) {
            dfi_unlock(&p->lock);
            return;
        }
        seen = p->generation;
        const dfi_pool_fn fn = p->fn;
        void *job = p->job;
        uint32_t begin = 0u;
        uint32_t end = 0u;
        dfi_slice(p, self->index, &begin, &end);
        dfi_unlock(&p->lock);
        if (begin < end) {
            fn(job, self->index, begin, end);
        }
        dfi_lock(&p->lock);
        p->pending -= 1u;
        if (p->pending == 0u) {
            dfi_wake_all(&p->done);
        }
        dfi_unlock(&p->lock);
    }
}

#if defined(_WIN32)
static DWORD WINAPI dfi_thread_main(LPVOID arg)
{
    dfi_worker_loop((dfi_worker *)arg);
    return 0u;
}
#else
static void *dfi_thread_main(void *arg)
{
    dfi_worker_loop((dfi_worker *)arg);
    return NULL;
}
#endif

static bool dfi_thread_start(dfi_worker *w)
{
#if defined(_WIN32)
    w->thread = CreateThread(NULL, 0u, dfi_thread_main, w, 0u, NULL);
    return w->thread != NULL;
#else
    return pthread_create(&w->thread, NULL, dfi_thread_main, w) == 0;
#endif
}

static void dfi_thread_join(dfi_worker *w)
{
#if defined(_WIN32)
    (void)WaitForSingleObject(w->thread, INFINITE);
    (void)CloseHandle(w->thread);
#else
    (void)pthread_join(w->thread, NULL);
#endif
}

dfi_pool *dfi_pool_create(uint32_t workers)
{
    if (workers < 1u) {
        return NULL;
    }
    struct dfi_pool *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return NULL;
    }
    p->workers = workers;
#if defined(_WIN32)
    InitializeSRWLock(&p->lock);
    InitializeConditionVariable(&p->start);
    InitializeConditionVariable(&p->done);
#else
    if (pthread_mutex_init(&p->lock, NULL) != 0 || pthread_cond_init(&p->start, NULL) != 0 ||
        pthread_cond_init(&p->done, NULL) != 0) {
        dfi_free(p);
        return NULL;
    }
#endif
    if (workers > 1u) {
        p->worker = dfi_alloc_zeroed(sizeof *p->worker * (workers - 1u));
        if (p->worker == NULL) {
            dfi_pool_destroy(p);
            return NULL;
        }
        for (uint32_t i = 0u; i + 1u < workers; ++i) {
            p->worker[i].pool = p;
            p->worker[i].index = i + 1u;
            p->worker[i].started = dfi_thread_start(&p->worker[i]);
            if (!p->worker[i].started) {
                dfi_pool_destroy(p);
                return NULL;
            }
        }
    }
    return p;
}

void dfi_pool_destroy(dfi_pool *pool)
{
    if (pool == NULL) {
        return;
    }
    dfi_lock(&pool->lock);
    pool->shutdown = true;
    dfi_wake_all(&pool->start);
    dfi_unlock(&pool->lock);
    if (pool->worker != NULL) {
        for (uint32_t i = 0u; i + 1u < pool->workers; ++i) {
            if (pool->worker[i].started) {
                dfi_thread_join(&pool->worker[i]);
            }
        }
        dfi_free(pool->worker);
    }
#if !defined(_WIN32)
    (void)pthread_cond_destroy(&pool->done);
    (void)pthread_cond_destroy(&pool->start);
    (void)pthread_mutex_destroy(&pool->lock);
#endif
    dfi_free(pool);
}

void dfi_pool_run(dfi_pool *pool, dfi_pool_fn fn, void *job, uint32_t items)
{
    dfi_lock(&pool->lock);
    pool->fn = fn;
    pool->job = job;
    pool->items = items;
    pool->pending = pool->workers - 1u;
    pool->generation += 1u;
    dfi_wake_all(&pool->start);
    uint32_t begin = 0u;
    uint32_t end = 0u;
    dfi_slice(pool, 0u, &begin, &end);
    dfi_unlock(&pool->lock);
    if (begin < end) {
        fn(job, 0u, begin, end);
    }
    dfi_lock(&pool->lock);
    while (pool->pending != 0u) {
        dfi_wait(&pool->done, &pool->lock);
    }
    dfi_unlock(&pool->lock);
}

uint32_t dfi_pool_workers(const dfi_pool *pool)
{
    return pool->workers;
}
