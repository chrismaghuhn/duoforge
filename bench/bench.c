/*
 * The benchmark families of bench.h. Only the public API is measured; the
 * reference teams come from the test support (df_setup_teams).
 */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L /* clock_gettime */
#endif

#include "bench.h"

#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <time.h>
#endif

#include "support/fixtures.h"

typedef struct dfb_battle_tape {
    uint32_t start;  /* index of its start state (TEAM_SELECTION) in states */
    uint32_t first;  /* index of its first bundle in bundles */
    uint32_t steps;  /* its bundles */
    uint8_t digest[DUOFORGE_DIGEST_SIZE]; /* the state it ends in */
} dfb_battle_tape;

struct dfb_tapes {
    dfb_battle_tape *battle;
    uint32_t battles;
    duoforge_decision_bundle *bundle;
    uint32_t bundles;
    uint32_t bundle_cap;
    duoforge_battle **state; /* every boundary before a step */
    uint32_t states;
    uint32_t state_cap;
    uint64_t turns;
    uint64_t side_decisions;
    uint64_t truncations;
    size_t encoded_max;
};

/* ---------------------------------------------------------------- clocks */

uint64_t dfb_wall_ns(void)
{
#if defined(_WIN32)
    LARGE_INTEGER freq;
    LARGE_INTEGER count;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&count);
    const uint64_t hz = (uint64_t)freq.QuadPart;
    const uint64_t ticks = (uint64_t)count.QuadPart;
    return ticks / hz * 1000000000u + ticks % hz * 1000000000u / hz;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
#endif
}

uint64_t dfb_cpu_ns(void)
{
#if defined(_WIN32)
    FILETIME created;
    FILETIME exited;
    FILETIME kernel;
    FILETIME user;
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) {
        return 0u;
    }
    const uint64_t k = ((uint64_t)kernel.dwHighDateTime << 32) | kernel.dwLowDateTime;
    const uint64_t u = ((uint64_t)user.dwHighDateTime << 32) | user.dwLowDateTime;
    return (k + u) * 100u; /* 100 ns units */
#else
    struct timespec ts;
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
#endif
}

bool dfb_rep_disturbed(const dfb_rep *rep)
{
    return rep->wall_ns >= 100000000u && rep->cpu_ns * 10u < rep->wall_ns * 9u;
}

/* ---------------------------------------------------------------- workload */

/* splitmix64: the policy's own generator, independent of the engine. */
static uint64_t dfb_next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

#define DFB_PAIRINGS 4u

static void dfb_setup(const duoforge_battle_setup *teams, uint32_t pairing, uint64_t seed,
                      duoforge_battle_setup *out)
{
    static const uint32_t pick[DFB_PAIRINGS][2] = {{0u, 1u}, {1u, 0u}, {0u, 0u}, {1u, 1u}};
    *out = *teams;
    out->sides[0] = teams->sides[pick[pairing][0]];
    out->sides[1] = teams->sides[pick[pairing][1]];
    out->rng_initstate = seed;
    out->rng_initseq = 1001u;
}

/* The boundary of `b`: DUOFORGE_BOUNDARY_* from player 0's request. */
static duoforge_status dfb_boundary(const duoforge_context *ctx, const duoforge_battle *b, uint32_t *out)
{
    duoforge_request rq;
    const duoforge_status st = duoforge_battle_request(ctx, b, 0u, &rq);
    *out = rq.boundary_kind;
    return st;
}

/* The uniform random policy: one candidate of every requested player. */
static duoforge_status dfb_choose(const duoforge_context *ctx, const duoforge_battle *b, uint64_t *rng,
                                  duoforge_side_choice *cands, duoforge_decision_bundle *bd, uint64_t *decisions)
{
    memset(bd, 0, sizeof *bd);
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        duoforge_request rq;
        duoforge_status st = duoforge_battle_request(ctx, b, p, &rq);
        if (st != DUOFORGE_OK) {
            return st;
        }
        bd->epoch = rq.epoch;
        if (rq.requested == 0u) {
            continue;
        }
        uint32_t n = 0u;
        st = duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (n == 0u) {
            return DUOFORGE_E_INVARIANT;
        }
        bd->responses[p] = cands[(size_t)(dfb_next(rng) % n)];
        bd->response_mask = (uint8_t)(bd->response_mask | (1u << p));
        *decisions += 1u;
    }
    return DUOFORGE_OK;
}

static bool dfb_grow(void **items, uint32_t *cap, uint32_t need, size_t size)
{
    if (need <= *cap) {
        return true;
    }
    uint32_t next = *cap == 0u ? 256u : *cap * 2u;
    while (next < need) {
        next *= 2u;
    }
    void *grown = realloc(*items, (size_t)next * size);
    if (grown == NULL) {
        return false;
    }
    *items = grown;
    *cap = next;
    return true;
}

static void dfb_result_init(dfb_result *out, const char *family, const char *variant)
{
    memset(out, 0, sizeof *out);
    out->family = family;
    out->variant = variant;
}

static uint32_t dfb_reps(uint32_t repetitions)
{
    return repetitions > DFB_MAX_REPETITIONS ? DFB_MAX_REPETITIONS : repetitions;
}

/* ---------------------------------------------------------------- record */

duoforge_status dfb_tapes_record(const duoforge_context *ctx, const dfb_workload *workload, dfb_tapes **out_tapes,
                                 dfb_result *out_totals, dfb_tally tallies[DUOFORGE_SIDE_COUNT])
{
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    dfb_result_init(out_totals, "RECORD", "");
    *out_tapes = NULL;
    dfb_tapes *t = calloc(1u, sizeof *t);
    if (t == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    t->battle = calloc((size_t)workload->battles * DFB_PAIRINGS, sizeof *t->battle);
    if (t->battle == NULL) {
        dfb_tapes_destroy(t);
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    uint64_t rng = workload->policy_seed;
    uint64_t seed = workload->battle_seed;
    for (uint32_t pairing = 0u; pairing < DFB_PAIRINGS; ++pairing) {
        for (uint32_t i = 0u; i < workload->battles; ++i, ++seed) {
            duoforge_battle_setup setup;
            dfb_setup(&teams, pairing, seed, &setup);
            duoforge_battle *b = NULL;
            duoforge_status st = duoforge_battle_create(ctx, &setup, &b);
            if (st != DUOFORGE_OK) {
                out_totals->errors += 1u;
                continue;
            }
            dfb_battle_tape *tape = &t->battle[t->battles];
            tape->start = t->states;
            tape->first = t->bundles;
            for (;;) {
                uint32_t boundary = 0u;
                st = dfb_boundary(ctx, b, &boundary);
                if (st != DUOFORGE_OK || boundary == DUOFORGE_BOUNDARY_TERMINAL) {
                    break;
                }
                if (tape->steps >= workload->max_steps) {
                    t->truncations += 1u;
                    break;
                }
                if (!dfb_grow((void **)&t->state, &t->state_cap, t->states + 1u, sizeof *t->state) ||
                    !dfb_grow((void **)&t->bundle, &t->bundle_cap, t->bundles + 1u, sizeof *t->bundle)) {
                    st = DUOFORGE_E_OUT_OF_MEMORY;
                    break;
                }
                st = duoforge_battle_clone(ctx, b, &t->state[t->states]);
                if (st != DUOFORGE_OK) {
                    break;
                }
                t->states += 1u;
                size_t size = 0u;
                if (duoforge_battle_encoded_size(ctx, b, &size) == DUOFORGE_OK && size > t->encoded_max) {
                    t->encoded_max = size;
                }
                duoforge_decision_bundle *bd = &t->bundle[t->bundles];
                st = dfb_choose(ctx, b, &rng, cands, bd, &t->side_decisions);
                for (uint32_t p = 0u; st == DUOFORGE_OK && p < DUOFORGE_SIDE_COUNT; ++p) {
                    if ((((uint32_t)bd->response_mask >> p) & 1u) != 0u) {
                        st = dfb_tally_choice(ctx, b, p, &bd->responses[p], &tallies[p]);
                    }
                }
                if (st != DUOFORGE_OK) {
                    break;
                }
                duoforge_step_result res;
                st = duoforge_battle_step(ctx, b, bd, &res);
                if (st != DUOFORGE_OK) {
                    break;
                }
                t->bundles += 1u;
                tape->steps += 1u;
                t->turns += res.boundary_kind == DUOFORGE_BOUNDARY_TURN ? 1u : 0u;
            }
            if (st != DUOFORGE_OK || duoforge_battle_digest(ctx, b, tape->digest) != DUOFORGE_OK) {
                out_totals->errors += 1u;
            }
            duoforge_battle_destroy(b);
            t->battles += 1u;
        }
    }
    out_totals->battles = t->battles;
    out_totals->turns = t->turns;
    out_totals->steps = t->bundles;
    out_totals->side_decisions = t->side_decisions;
    out_totals->truncations = t->truncations;
    *out_tapes = t;
    return out_totals->errors == 0u ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

void dfb_tapes_destroy(dfb_tapes *tapes)
{
    if (tapes == NULL) {
        return;
    }
    for (uint32_t i = 0u; i < tapes->states; ++i) {
        duoforge_battle_destroy(tapes->state[i]);
    }
    free(tapes->state);
    free(tapes->bundle);
    free(tapes->battle);
    free(tapes);
}

/* ---------------------------------------------------------------- families */

static void dfb_rep_begin(dfb_rep *rep)
{
    memset(rep, 0, sizeof *rep);
    rep->cpu_ns = dfb_cpu_ns();
    rep->wall_ns = dfb_wall_ns();
}

static void dfb_rep_end(dfb_rep *rep)
{
    const uint64_t wall = dfb_wall_ns();
    const uint64_t cpu = dfb_cpu_ns();
    rep->wall_ns = wall - rep->wall_ns;
    rep->cpu_ns = cpu - rep->cpu_ns;
}

/* One replay of every battle; `check` compares the final states. */
static void dfb_replay(const duoforge_context *ctx, const dfb_tapes *t, duoforge_battle *work, bool events,
                       bool check, uint64_t *errors)
{
    static duoforge_event ev[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_EVENTS];
    for (uint32_t i = 0u; i < t->battles; ++i) {
        const dfb_battle_tape *tape = &t->battle[i];
        if (duoforge_battle_copy(ctx, work, t->state[tape->start]) != DUOFORGE_OK) {
            *errors += 1u;
            continue;
        }
        for (uint32_t k = 0u; k < tape->steps; ++k) {
            duoforge_step_result res;
            duoforge_status st;
            if (events) {
                duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{ev[0], DUOFORGE_MAX_EVENTS, 0u},
                                                                      {ev[1], DUOFORGE_MAX_EVENTS, 0u}};
                st = duoforge_battle_step_events(ctx, work, &t->bundle[tape->first + k], &res, buffers);
            } else {
                st = duoforge_battle_step(ctx, work, &t->bundle[tape->first + k], &res);
            }
            if (st != DUOFORGE_OK) {
                *errors += 1u;
                break;
            }
        }
        if (check) {
            uint8_t digest[DUOFORGE_DIGEST_SIZE];
            if (duoforge_battle_digest(ctx, work, digest) != DUOFORGE_OK ||
                memcmp(digest, tape->digest, sizeof digest) != 0) {
                *errors += 1u; /* the replay left the recorded trajectory */
            }
        }
    }
}

duoforge_status dfb_step_core(const duoforge_context *ctx, const dfb_tapes *tapes, bool events, uint32_t warmup,
                              uint32_t repetitions, dfb_result *out)
{
    dfb_result_init(out, "STEP_CORE", events ? "events" : "plain");
    if (tapes->states == 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    duoforge_battle *work = NULL;
    const duoforge_status cs = duoforge_battle_clone(ctx, tapes->state[0], &work);
    if (cs != DUOFORGE_OK) {
        return cs;
    }
    uint64_t errors = 0u;
    dfb_replay(ctx, tapes, work, events, true, &errors); /* checked, not timed */
    for (uint32_t w = 0u; w < warmup; ++w) {
        dfb_replay(ctx, tapes, work, events, false, &errors);
    }
    out->repetitions = dfb_reps(repetitions);
    for (uint32_t r = 0u; r < out->repetitions; ++r) {
        dfb_rep_begin(&out->rep[r]);
        dfb_replay(ctx, tapes, work, events, false, &errors);
        dfb_rep_end(&out->rep[r]);
    }
    duoforge_battle_destroy(work);
    out->battles = tapes->battles;
    out->turns = tapes->turns;
    out->steps = tapes->bundles;
    out->side_decisions = tapes->side_decisions;
    out->truncations = tapes->truncations;
    out->errors = errors;
    return errors == 0u ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

static void dfb_request_pass(const duoforge_context *ctx, const dfb_tapes *t, uint64_t *calls, uint64_t *errors)
{
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    duoforge_observation obs;
    for (uint32_t i = 0u; i < t->states; ++i) {
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
            duoforge_request rq;
            uint32_t n = 0u;
            if (duoforge_battle_request(ctx, t->state[i], p, &rq) != DUOFORGE_OK ||
                (rq.requested != 0u &&
                 duoforge_battle_candidates(ctx, t->state[i], p, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK) ||
                duoforge_battle_observe(ctx, t->state[i], p, &obs) != DUOFORGE_OK) {
                *errors += 1u;
            }
            *calls += 1u;
        }
    }
}

duoforge_status dfb_request(const duoforge_context *ctx, const dfb_tapes *tapes, uint32_t warmup,
                            uint32_t repetitions, dfb_result *out)
{
    dfb_result_init(out, "REQUEST", "request+candidates+observe");
    uint64_t errors = 0u;
    uint64_t calls = 0u;
    for (uint32_t w = 0u; w < warmup; ++w) {
        dfb_request_pass(ctx, tapes, &calls, &errors);
    }
    out->repetitions = dfb_reps(repetitions);
    for (uint32_t r = 0u; r < out->repetitions; ++r) {
        calls = 0u;
        dfb_rep_begin(&out->rep[r]);
        dfb_request_pass(ctx, tapes, &calls, &errors);
        dfb_rep_end(&out->rep[r]);
    }
    out->calls = calls;
    out->errors = errors;
    return errors == 0u ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

static void dfb_snapshot_pass(const duoforge_context *ctx, const dfb_tapes *t, duoforge_battle *work, bool codec,
                              uint8_t *buffer, size_t capacity, uint64_t *errors)
{
    for (uint32_t i = 0u; i < t->states; ++i) {
        if (codec) {
            size_t written = 0u;
            if (duoforge_battle_encode(ctx, t->state[i], buffer, capacity, &written) != DUOFORGE_OK ||
                duoforge_battle_decode(ctx, work, buffer, written) != DUOFORGE_OK) {
                *errors += 1u;
            }
        } else if (duoforge_battle_copy(ctx, work, t->state[i]) != DUOFORGE_OK) {
            *errors += 1u;
        }
    }
}

duoforge_status dfb_snapshot(const duoforge_context *ctx, const dfb_tapes *tapes, bool codec, uint32_t warmup,
                             uint32_t repetitions, dfb_result *out)
{
    dfb_result_init(out, "SNAPSHOT", codec ? "codec" : "copy");
    if (tapes->states == 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    duoforge_battle *work = NULL;
    duoforge_status st = duoforge_battle_clone(ctx, tapes->state[0], &work);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint8_t *buffer = malloc(tapes->encoded_max);
    if (buffer == NULL) {
        duoforge_battle_destroy(work);
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    uint64_t errors = 0u;
    for (uint32_t w = 0u; w < warmup; ++w) {
        dfb_snapshot_pass(ctx, tapes, work, codec, buffer, tapes->encoded_max, &errors);
    }
    out->repetitions = dfb_reps(repetitions);
    for (uint32_t r = 0u; r < out->repetitions; ++r) {
        dfb_rep_begin(&out->rep[r]);
        dfb_snapshot_pass(ctx, tapes, work, codec, buffer, tapes->encoded_max, &errors);
        dfb_rep_end(&out->rep[r]);
    }
    free(buffer);
    duoforge_battle_destroy(work);
    out->calls = tapes->states;
    out->bytes = tapes->encoded_max;
    out->errors = errors;
    return errors == 0u ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}

/* One live pass over the workload; part_ns: reset, policy, step. */
static void dfb_episode_pass(const duoforge_context *ctx, const dfb_workload *w, dfb_rep *rep, dfb_result *out)
{
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    uint64_t rng = w->policy_seed;
    uint64_t seed = w->battle_seed;
    out->battles = 0u;
    out->turns = 0u;
    out->steps = 0u;
    out->side_decisions = 0u;
    out->truncations = 0u;
    for (uint32_t pairing = 0u; pairing < DFB_PAIRINGS; ++pairing) {
        for (uint32_t i = 0u; i < w->battles; ++i, ++seed) {
            duoforge_battle_setup setup;
            dfb_setup(&teams, pairing, seed, &setup);
            uint64_t t0 = dfb_wall_ns();
            duoforge_battle *b = NULL;
            duoforge_status st = duoforge_battle_create(ctx, &setup, &b);
            rep->part_ns[0] += dfb_wall_ns() - t0;
            if (st != DUOFORGE_OK) {
                out->errors += 1u;
                continue;
            }
            uint32_t steps = 0u;
            for (;;) {
                uint32_t boundary = 0u;
                st = dfb_boundary(ctx, b, &boundary);
                if (st != DUOFORGE_OK || boundary == DUOFORGE_BOUNDARY_TERMINAL) {
                    break;
                }
                if (steps >= w->max_steps) {
                    out->truncations += 1u;
                    break;
                }
                duoforge_decision_bundle bd;
                const uint64_t p0 = dfb_wall_ns();
                st = dfb_choose(ctx, b, &rng, cands, &bd, &out->side_decisions);
                const uint64_t p1 = dfb_wall_ns();
                rep->part_ns[1] += p1 - p0;
                if (st != DUOFORGE_OK) {
                    break;
                }
                duoforge_step_result res;
                st = duoforge_battle_step(ctx, b, &bd, &res);
                rep->part_ns[2] += dfb_wall_ns() - p1;
                if (st != DUOFORGE_OK) {
                    break;
                }
                steps += 1u;
                out->turns += res.boundary_kind == DUOFORGE_BOUNDARY_TURN ? 1u : 0u;
            }
            out->errors += st != DUOFORGE_OK ? 1u : 0u;
            out->steps += steps;
            t0 = dfb_wall_ns();
            duoforge_battle_destroy(b);
            rep->part_ns[0] += dfb_wall_ns() - t0;
            out->battles += 1u;
        }
    }
}

duoforge_status dfb_episode_native(const duoforge_context *ctx, const dfb_workload *workload, uint32_t warmup,
                                   uint32_t repetitions, dfb_result *out)
{
    dfb_result_init(out, "EPISODE_NATIVE", "uniform-random");
    out->parts[0] = "reset";
    out->parts[1] = "policy";
    out->parts[2] = "step";
    dfb_rep scratch;
    for (uint32_t w = 0u; w < warmup; ++w) {
        memset(&scratch, 0, sizeof scratch);
        dfb_episode_pass(ctx, workload, &scratch, out);
    }
    out->repetitions = dfb_reps(repetitions);
    for (uint32_t r = 0u; r < out->repetitions; ++r) {
        dfb_rep_begin(&out->rep[r]);
        const uint64_t wall0 = out->rep[r].wall_ns;
        const uint64_t cpu0 = out->rep[r].cpu_ns;
        out->rep[r].wall_ns = 0u;
        out->rep[r].cpu_ns = 0u;
        dfb_episode_pass(ctx, workload, &out->rep[r], out);
        out->rep[r].wall_ns = dfb_wall_ns() - wall0;
        out->rep[r].cpu_ns = dfb_cpu_ns() - cpu0;
    }
    return out->errors == 0u ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}
