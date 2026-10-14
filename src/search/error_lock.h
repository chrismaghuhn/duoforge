#ifndef DFI_SEARCH_ERROR_LOCK_H
#define DFI_SEARCH_ERROR_LOCK_H
/* Only the fixed diagnostic record contends, never successful leaf work.
 * Literal initialization needs no allocation or cold runtime setup. */
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
typedef SRWLOCK dfi_error_lock;
#define DFI_ERROR_LOCK_INIT SRWLOCK_INIT
static inline void dfi_error_lock_enter(dfi_error_lock *lock) { AcquireSRWLockExclusive(lock); }
static inline void dfi_error_lock_leave(dfi_error_lock *lock) { ReleaseSRWLockExclusive(lock); }
static inline void dfi_error_lock_destroy(dfi_error_lock *lock) { (void)lock; }
#else
#include <pthread.h>
typedef pthread_mutex_t dfi_error_lock;
#define DFI_ERROR_LOCK_INIT PTHREAD_MUTEX_INITIALIZER
static inline void dfi_error_lock_enter(dfi_error_lock *lock) { (void)pthread_mutex_lock(lock); }
static inline void dfi_error_lock_leave(dfi_error_lock *lock) { (void)pthread_mutex_unlock(lock); }
static inline void dfi_error_lock_destroy(dfi_error_lock *lock) { (void)pthread_mutex_destroy(lock); }
#endif
#endif
