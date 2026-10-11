/* Baseline-only observation, compiled into temporary copies of the original
 * test drivers. No engine/test source is changed. stdout is hashed by the
 * collector; integers are decimal, fields are explicit (never struct padding).
 */
#include <inttypes.h>
#include <stdlib.h>
#include "state/tiebreak.h"

static void baseline_u64(uint64_t value)
{
    printf("%" PRIu64 " ", value);
}

static void baseline_state(const duoforge_context *ctx, const duoforge_battle *b)
{
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
    if (duoforge_battle_digest(ctx, b, digest) != DUOFORGE_OK) {
        exit(2);
    }
    printf("state ");
    for (unsigned i = 0; i < sizeof digest; ++i) {
        printf("%02x", digest[i]);
    }
    putchar('\n');
    for (uint32_t side = 0; side < DUOFORGE_SIDE_COUNT; ++side) {
        duoforge_request r = {0};
        const duoforge_status status = duoforge_battle_request(ctx, b, side, &r);
        printf("request ");
        baseline_u64(side);
        baseline_u64(status);
        if (status == DUOFORGE_OK) {
            baseline_u64(r.epoch);
            baseline_u64(r.candidate_count);
            baseline_u64(r.boundary_kind);
            baseline_u64(r.player);
            baseline_u64(r.requested);
            baseline_u64(r.slot_mask);
        }
        putchar('\n');
    }
}

static void baseline_step(const duoforge_context *ctx, const duoforge_battle *b,
                          uint32_t used, const duoforge_step_result *r)
{
    printf("step ");
    baseline_u64(used);
    baseline_u64(r->epoch);
    baseline_u64(r->kind);
    baseline_u64(r->boundary_kind);
    baseline_u64(r->request_mask);
    baseline_u64(r->reserved);
    putchar('\n');
    baseline_state(ctx, b);
}

#ifdef BASELINE_CONFORMANCE
static void baseline_events(const duoforge_event_buffer *buffers)
{
    for (uint32_t side = 0; side < DUOFORGE_SIDE_COUNT; ++side) {
        printf("events ");
        baseline_u64(side);
        baseline_u64(buffers[side].count);
        putchar('\n');
        for (uint32_t i = 0; i < buffers[side].count; ++i) {
            const duoforge_event *e = &buffers[side].events[i];
            baseline_u64(e->kind);
            baseline_u64(e->position);
            baseline_u64(e->other);
            baseline_u64(e->cause);
            baseline_u64(e->id);
            baseline_u64(e->id2);
            baseline_u64(e->hp);
            baseline_u64(e->hp_max);
            baseline_u64(e->hp_kind);
            baseline_u64(e->hp_flag);
            baseline_u64(e->status);
            baseline_u64(e->detail);
            baseline_u64(e->amount);
            baseline_u64(e->flags);
            baseline_u64(e->reserved[0]);
            baseline_u64(e->reserved[1]);
            putchar('\n');
        }
    }
}
#else
static void baseline_tiebreak(const df_tb_stop *stop, const dfi_tiebreak_report *r,
                             duoforge_status rs, duoforge_status ps, uint32_t out)
{
    printf("tiebreak ");
    baseline_u64(stop->prefix);
    baseline_u64(rs);
    baseline_u64(ps);
    baseline_u64(out);
    if (rs == DUOFORGE_OK) {
        baseline_u64(r->result);
        baseline_u64(r->result_mask);
        /* The report's side fields are unset at TERMINAL. */
        if (!stop->ended) {
            for (uint32_t side = 0; side < DUOFORGE_SIDE_COUNT; ++side) {
                baseline_u64(r->not_fainted[side]);
                baseline_u64(r->hp_total[side]);
                baseline_u64(r->pct_count[side]);
                for (uint32_t i = 0; i < r->pct_count[side]; ++i) {
                    baseline_u64(r->pct_bits[side][i]);
                }
            }
        }
    }
    putchar('\n');
}
#endif
