/*
 * duoforge.reference.conformance (white-box): battles recorded from the
 * pinned Showdown (tests/reference/traces, converted by
 * tools/reference/trace_to_c.py into tests/reference/conformance.h) replayed
 * in DuoForge. The teams are created through the public API (CLOSURE_DEV,
 * the support gate must let them pass); every turn runs through the step
 * with the reference's kept draws as a test-only tape, which must be
 * consumed exactly; afterwards HP, PP, stat stages and the stall counter of
 * every member equal the reference, and so does the turn number. The
 * comparators (state, observation, events) are in support/conformance_compare.c.
 *
 * Built with DF_CONFORMANCE_TEAM_C it is duoforge.reference.conformance_team_c:
 * the same driver over the Team C battles (tests/reference/conformance_team_c.h,
 * decision 0009 section 6.1) with TEAM_C and TEAM_C_DEV contexts.
 *
 * Built with DF_CONFORMANCE_POOL (on its own, or with DF_CONFORMANCE_TEAM_C) it
 * is duoforge.reference.conformance_pool (or _team_c_pool): the same battles
 * under the POOL and POOL_DEV contexts (decision 0015 section 5). The pool
 * tables have the closure and the extended tables as their prefix and the
 * POOL profile is the certified one, so every battle must pass as before and
 * the same battles run under POOL itself, not under POOL_DEV.
 *
 * Built with DF_CONFORMANCE_POOL_DATA it is duoforge.reference.conformance_pool_data:
 * the battles recorded for the pool items (tests/reference/conformance_pool.h,
 * "data": "pool" in their specs), which use ids that only the pool tables
 * have. Every one must run under POOL itself, with no fallback to POOL_DEV.
 */
#include <stdio.h>
#include <string.h>

#if defined(DF_CONFORMANCE_POOL_DATA)
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "support/pool.h"
#define DF_CONF_FORMES dfi_pool_formes
#define DF_POOL_DATA_BATTLES 405u /* the recorded pool battles (G46, G48, G43, G44, G49, G50: six Double Shock; G52: five Revival Blessing battles) */
#elif defined(DF_CONFORMANCE_TEAM_C)
#include "data/extended_tables.h"
#include "reference/conformance_team_c.h"
#include "support/team_c.h"
#define DF_CONF_FORMES dfi_ext_formes
#define DF_TEAM_C_BATTLES 73u /* the recorded Team C battles */
#define DF_TEAM_C_REAL 23u   /* of them under TEAM_C itself (six registered members) */
#else
#include "data/closure_tables.h"
#include "reference/conformance.h"
#define DF_CONF_FORMES dfi_closure_formes
#endif
#ifdef DF_CONFORMANCE_POOL
#include "data/pool_tables.h"
#include "support/pool.h"
#undef DF_CONF_FORMES
#define DF_CONF_FORMES dfi_pool_formes
#endif
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_compare.h"
#include "support/fixtures.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

int main(void)
{
    df_test t;
#if defined(DF_CONFORMANCE_POOL_DATA)
    df_test_begin(&t, "duoforge.reference.conformance_pool_data");
#elif defined(DF_CONFORMANCE_POOL) && defined(DF_CONFORMANCE_TEAM_C)
    df_test_begin(&t, "duoforge.reference.conformance_team_c_pool");
#elif defined(DF_CONFORMANCE_POOL)
    df_test_begin(&t, "duoforge.reference.conformance_pool");
#elif defined(DF_CONFORMANCE_TEAM_C)
    df_test_begin(&t, "duoforge.reference.conformance_team_c");
#else
    df_test_begin(&t, "duoforge.reference.conformance");
#endif
#if defined(DF_CONFORMANCE_POOL) || defined(DF_CONFORMANCE_POOL_DATA)
    duoforge_context *k1 = df_make_context(&df_config_pool);
    duoforge_context *k2 = df_make_context(&df_config_pool_dev);
#elif defined(DF_CONFORMANCE_TEAM_C)
    duoforge_context *k1 = df_make_context(&df_config_team_c);
    duoforge_context *k2 = df_make_context(&df_config_team_c_dev);
#else
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
#endif
    unsigned real = 0; /* battles under CLOSURE data: every set has a real ability */
    /* Event differences written so far; the comparator stops at its cap per run. */
    unsigned event_reports = 0;
    for (size_t bi = 0; bi < sizeof conf_battles / sizeof conf_battles[0]; ++bi) {
        const df_conf_battle *cb = &conf_battles[bi];
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        /* CLOSURE data where the sets are real, CLOSURE_DEV (No Ability
         * allowed) for the development teams. */
        const duoforge_context *ctx = k1;
        duoforge_status created = duoforge_battle_create(k1, &setup, &b);
        if (created != DUOFORGE_OK) {
            ctx = k2;
            created = duoforge_battle_create(k2, &setup, &b);
        } else {
            real += 1u;
        }
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", cb->name, duoforge_status_name(created));
            continue;
        }
        unsigned bad = 0;
        for (uint32_t si = 0; si < cb->step_count && bad == 0u; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
            for (uint32_t s = 0; s < 2u; ++s) {
                if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
                    continue;
                }
                duoforge_side_choice *r = &bd.responses[s];
                r->epoch = b->request_epoch;
                r->side = (uint8_t)s;
                if (st->team) {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                    r->pick_count = 4u;
                    for (uint32_t i = 0; i < 4u; ++i) {
                        r->picks[i] = st->picks[s][i];
                    }
                } else {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                    for (uint32_t k = 0; k < 2u; ++k) {
                        const df_conf_cmd *c = &st->cmds[s][k];
                        r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve,
                                                              {0u, 0u, 0u}};
                    }
                }
            }
            duoforge_step_result res;
            uint32_t used = 0xFFFFFFFFu;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u},
                                                {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            const duoforge_status status = dfi_battle_step_events_tape(
                ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
            const bool consumed = used == st->tape_len;
            if (!DF_CHECK(&t, status == DUOFORGE_OK && consumed)) {
                fprintf(stderr, "  %s step %u: %s, tape %u of %u\n", cb->name, si, duoforge_status_name(status),
                        used, st->tape_len);
                ++bad;
                break;
            }
            bad += df_conf_compare_state(stderr, ctx, b, st, cb->name, si);
            bad += df_conf_compare_observation(stderr, ctx, b, st, cb, si);
            bad += df_conf_compare_events(stderr, st, cb->name, si, buffers, conf_events, &event_reports);
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        duoforge_battle_destroy(b);
    }
#if defined(DF_CONFORMANCE_POOL_DATA)
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], DF_POOL_DATA_BATTLES);
    /* All of them under POOL itself: the sets are the real members', with
     * a real ability each, the new items are marked (decision 0015 step P2). */
    DF_CHECK_EQ_U64(&t, real, DF_POOL_DATA_BATTLES);
#elif defined(DF_CONFORMANCE_TEAM_C)
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], DF_TEAM_C_BATTLES);
    DF_CHECK_EQ_U64(&t, real, DF_TEAM_C_REAL);
    /* The real Team C of the recorded gate battles (team-c.txt through the
     * specs) is the gate's fixture (df_put_team_c, duoforge.combat.
     * team_c_gate): each Team C member of a c12_real battle equals the
     * fixture's member of its species, which no team A or B member shares. */
    {
        duoforge_side_setup fixture;
        df_put_team_c(&fixture);
        uint32_t matched = 0u;
        for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
            const df_conf_battle *cb = &conf_battles[i];
            if (strncmp(cb->name, "c12_real_", 9u) != 0) {
                continue;
            }
            for (uint32_t side = 0; side < 2u; ++side) {
                for (uint32_t m = 0; m < cb->member_count; ++m) {
                    const df_conf_member *src = &cb->members[side][m];
                    for (uint32_t f = 0; f < fixture.member_count; ++f) {
                        const duoforge_member_setup *d = &fixture.members[f];
                        if (d->species_id != src->species) {
                            continue;
                        }
                        bool same = d->gender == src->gender && d->nature == src->nature &&
                                    d->ability == src->ability && d->item == src->item &&
                                    d->move_count == src->move_count;
                        for (uint32_t k = 0; k < 6u; ++k) {
                            same = same && d->stat_points[k] == src->sp[k];
                        }
                        for (uint32_t k = 0; k < d->move_count && k < 4u; ++k) {
                            same = same && d->moves[k].move_id == src->moves[k];
                        }
                        if (!DF_CHECK(&t, same)) {
                            fprintf(stderr, "  %s: member %u of side %u differs from df_put_team_c\n", cb->name, m,
                                    side);
                        }
                        matched += 1u;
                    }
                }
            }
        }
        DF_CHECK_EQ_U64(&t, matched, 24u * 6u); /* Team C on 4 x 4 + 4 x 2 sides */
    }
#else
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], 90u);
    /* Exactly the battles of the real teams run under CLOSURE, the certified
     * profile (decision 0010): the closure gate's 8, the 16 of M5 step 3 and
     * d01_noguard_accuracy_tie and d02_electro_shot_lock_emergency_exit, cuts
     * of battles found by the differential loop. */
    DF_CHECK_EQ_U64(&t, real, 26u);
#endif
#if defined(DF_CONFORMANCE_POOL) || defined(DF_CONFORMANCE_POOL_DATA)
    fprintf(stderr, "  %u of the battles run under POOL data\n", real);
#elif defined(DF_CONFORMANCE_TEAM_C)
    fprintf(stderr, "  %u of the battles run under TEAM_C data\n", real);
#else
    fprintf(stderr, "  %u of the battles run under CLOSURE data\n", real);
#endif
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    return df_test_end(&t);
}
