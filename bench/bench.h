#ifndef DUOFORGE_BENCH_H
#define DUOFORGE_BENCH_H
/*
 * DuoForge benchmark API (docs/decisions/0008): the benchmark families of
 * docs/TESTING_AND_BENCHMARKS.md section 4 (STEP_CORE, REQUEST, SNAPSHOT,
 * EPISODE_NATIVE), measured through the public API on one fixed workload.
 *
 * Workload "closure-pairings-v1": the two reference teams of the closure in
 * the four pairings A-B, B-A, A-A, B-B, a uniform random policy over each
 * requested player's candidates with its own seed (splitmix64), and a guard
 * of max_steps per battle (a battle that reaches it is a truncation, never
 * a result). The battles are recorded once as a fixed command source (the
 * bundles of every battle and every boundary state); STEP_CORE, REQUEST and
 * SNAPSHOT replay that source, EPISODE_NATIVE plays the same battles live.
 *
 * Every repetition reports wall time and the process's CPU time: a
 * single-threaded run whose CPU time is well below its wall time shared the
 * machine and is flagged as disturbed (decision 0008).
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "tally.h"

#define DFB_MAX_REPETITIONS 32u
#define DFB_PARTS 3u

typedef struct dfb_workload {
    uint32_t battles;     /* per pairing */
    uint32_t max_steps;   /* per battle */
    uint64_t policy_seed; /* the random policy's seed */
    uint64_t battle_seed; /* rng_initstate of the first battle; +1 per battle */
} dfb_workload;

typedef struct dfb_rep {
    uint64_t wall_ns;
    uint64_t cpu_ns;               /* this process's CPU time (user + kernel) */
    uint64_t part_ns[DFB_PARTS];   /* named parts, where the family has them */
} dfb_rep;

typedef struct dfb_result {
    const char *family;            /* "STEP_CORE", "REQUEST", "SNAPSHOT", "EPISODE_NATIVE" */
    const char *variant;           /* e.g. "plain", "events", "copy", "codec" */
    const char *parts[DFB_PARTS];  /* names of part_ns, NULL when unused */
    uint32_t repetitions;          /* measured repetitions (after warmup) */
    dfb_rep rep[DFB_MAX_REPETITIONS];
    /* The work of ONE repetition (the same in every repetition). */
    uint64_t battles;
    uint64_t turns;          /* step results that start a turn */
    uint64_t steps;          /* step calls (decision boundaries passed) */
    uint64_t side_decisions; /* responses submitted (requested players) */
    uint64_t calls;          /* REQUEST: per-player request groups; SNAPSHOT: restores */
    uint64_t bytes;          /* SNAPSHOT codec: encoded bytes per state */
    uint64_t truncations;    /* battles stopped by max_steps */
    uint64_t errors;         /* non-OK statuses, replay mismatches: must be 0 */
    uint32_t workers;        /* BATCH_NATIVE: worker threads; 0 for the one-thread families */
} dfb_result;

/* The recorded command source of a workload. */
typedef struct dfb_tapes dfb_tapes;

/* Monotonic wall time and process CPU time in nanoseconds. */
uint64_t dfb_wall_ns(void);
uint64_t dfb_cpu_ns(void);

/* True when the repetition is long enough to judge (>= 100 ms) and its CPU
 * time is below 90 percent of its wall time. */
bool dfb_rep_disturbed(const dfb_rep *rep);
/* The same for a repetition of `workers` threads (0 counts as 1): its
 * process CPU time is below 90 percent of workers x wall. */
bool dfb_rep_disturbed_workers(const dfb_rep *rep, uint32_t workers);

/* Plays and records the workload under `ctx` (CLOSURE data). The totals of
 * the recording (battles, turns, steps, side decisions, truncations,
 * errors) go to *out_totals (family "RECORD"); what each side's policy
 * chose goes to tallies[side] (dfb_tally, outside any timing). */
duoforge_status dfb_tapes_record(const duoforge_context *ctx, const dfb_workload *workload, dfb_tapes **out_tapes,
                                 dfb_result *out_totals, dfb_tally tallies[DUOFORGE_SIDE_COUNT]);
void dfb_tapes_destroy(dfb_tapes *tapes); /* NULL is a no-op */

/* BATCH_NATIVE (decisions 0008 and 0012): the batch runtime's native mode
 * with `workers` threads over DFB_BATCH_ENVS environments (the four pairings
 * in turn), ceil(4 x battles / DFB_BATCH_ENVS) random-policy episodes each,
 * batch seed = the policy seed; a fresh batch per repetition, its creation
 * untimed. *io_hash is the hash of every episode record: 0 on entry sets it,
 * a different hash is an error (every worker count plays the same battles). */
#define DFB_BATCH_ENVS 256u
duoforge_status dfb_batch_native(const duoforge_context *ctx, const dfb_workload *workload, uint32_t workers,
                                 uint32_t warmup, uint32_t repetitions, uint64_t *io_hash, dfb_result *out);

/* STEP_CORE: replays every battle from its start state (one restore per
 * battle inside the timing); with `events` through duoforge_battle_step_events
 * with full buffers. The warmup run also checks that every replay ends in
 * the recorded state (errors otherwise). */
duoforge_status dfb_step_core(const duoforge_context *ctx, const dfb_tapes *tapes, bool events, uint32_t warmup,
                              uint32_t repetitions, dfb_result *out);

/* REQUEST: at every recorded boundary, for both players: the request, the
 * candidates of a requested player, the observation. */
duoforge_status dfb_request(const duoforge_context *ctx, const dfb_tapes *tapes, uint32_t warmup,
                            uint32_t repetitions, dfb_result *out);

/* SNAPSHOT: every recorded boundary state restored into one battle:
 * variant "copy" (duoforge_battle_copy) or "codec" (encode, then decode). */
duoforge_status dfb_snapshot(const duoforge_context *ctx, const dfb_tapes *tapes, bool codec, uint32_t warmup,
                             uint32_t repetitions, dfb_result *out);

/* EPISODE_NATIVE: the workload's battles played live from setup to the end:
 * parts "reset" (create and destroy), "policy" (request, candidates, the
 * choice) and "step". */
duoforge_status dfb_episode_native(const duoforge_context *ctx, const dfb_workload *workload, uint32_t warmup,
                                   uint32_t repetitions, dfb_result *out);

#endif
