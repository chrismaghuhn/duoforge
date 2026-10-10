/*
 * duoforge.state.pool_g88 (white-box): step G88 of the content expansion (decision 0046), Lash Out and Assurance, with the
 * turn-history position flags of tail rev 5 (LOWERED_THIS_TURN bit 5, HURT_THIS_TURN bit 6) and the PIVOT refusal of the
 * public record with DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY (64).
 *
 * The recorded battles are replayed the way duoforge.reference.conformance_pool_data replays them: every step with its kept
 * draws (the test-only tape) and its recorded commands, so the path is the trace's. This file checks the flags and the boundary
 * after the steps that matter, the row and the marks, and the refusal of the public record at the PIVOT. Flat positions: side
 * 0 slots 0 and 1 (flat 0, 1), side 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static uint32_t flags_of(const duoforge_battle *b, uint32_t flat)
{
    return (uint32_t)b->tail.sides[flat / 2u].positions[flat % 2u].position_flags;
}

/* The recorded battle `name` (conformance_pool.h). */
static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The setup of a recorded battle, as the conformance test builds it. */
static void setup_from(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0u; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* Creates the recorded battle `name` (no step yet). Returns false when it cannot. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, const df_conf_battle **cbo)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    *cbo = find_conf(name);
    DF_CHECK(t, *cbo != NULL);
    if (*ctx == NULL || *cbo == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(*cbo, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    return *b != NULL;
}

/* Steps `from` up to `to` (exclusive) of the recorded battle with its kept draws and its recorded commands, as the conformance
 * replay does. Returns the first failing status, or OK when every step consumed its whole tape. */
static duoforge_status replay_steps(duoforge_context *ctx, duoforge_battle *b, const df_conf_battle *cb, uint32_t from, uint32_t to)
{
    static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
    for (uint32_t si = from; si < to && si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = b->request_epoch;
        bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
        for (uint32_t s = 0u; s < 2u; ++s) {
            if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
                continue;
            }
            duoforge_side_choice *r = &bd.responses[s];
            r->epoch = b->request_epoch;
            r->side = (uint8_t)s;
            if (st->team) {
                r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                r->pick_count = 4u;
                for (uint32_t i = 0u; i < 4u; ++i) {
                    r->picks[i] = st->picks[s][i];
                }
            } else {
                r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                for (uint32_t k = 0u; k < 2u; ++k) {
                    const df_conf_cmd *c = &st->cmds[s][k];
                    r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
                }
            }
        }
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
        const duoforge_status status =
            dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
        if (status != DUOFORGE_OK) {
            return status;
        }
        if (used != st->tape_len) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    return DUOFORGE_OK;
}

/* The row and the marks: the handler ids, the support marks, the flag bits and the cause value (the manifest, the flags and the
 * view agree). */
static void test_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_LASHOUT].special, DFI_SPECIAL_LASH_OUT);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ASSURANCE].special, DFI_SPECIAL_ASSURANCE);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_LASHOUT], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ASSURANCE], 1u);
    DF_CHECK_EQ_U64(t, DFI_POSFLAG_LOWERED, 0x20u);
    DF_CHECK_EQ_U64(t, DFI_POSFLAG_HURT, 0x40u);
    DF_CHECK_EQ_U64(t, DFI_POSFLAG_VALID_MASK, 0x6Fu); /* bit 4 (Destiny Bond, G76) is not on this branch */
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, 64u);
}

/* g88_lo_intimidate: Intimidate lowers Umbreon (flat 0) and Milotic (flat 1) at the start, so LOWERED_THIS_TURN is set before
 * turn 1 (sim/battle.ts:2086); the turn-1 boundary clears it (sim/battle.ts:1679). Step 0 is the team selection, step 1 turn 1. */
static void test_lo_intimidate(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g88_lo_intimidate", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 1u), DUOFORGE_OK);
    DF_CHECK(t, (flags_of(b, 0u) & DFI_POSFLAG_LOWERED) != 0u);
    DF_CHECK(t, (flags_of(b, 1u) & DFI_POSFLAG_LOWERED) != 0u);
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 1u, 2u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    DF_CHECK(t, (flags_of(b, 0u) & DFI_POSFLAG_LOWERED) == 0u); /* the turn boundary cleared it (endTurn) */
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* The Assurance battles of turn 1. The HURT bit of the Assurance target is set by the spread damage of its hit, and endTurn
 * (which clears it) runs after the turn's end replacements. The boundary of turn 1 is the recorded one (conf_* in
 * conformance_pool.h, which the trace gives): TURN for g88_av_hurt, REPLACEMENT for g88_av_control. */
static void test_av_turn(df_test *t, const char *name, uint32_t hurt_flat, uint32_t expected_boundary, bool hurt_after_turn)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, name, &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 1u), DUOFORGE_OK);
    DF_CHECK(t, (flags_of(b, hurt_flat) & DFI_POSFLAG_HURT) == 0u); /* nobody was hurt before turn 1 */
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 1u, 2u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, expected_boundary);
    DF_CHECK_EQ_U64(t, (flags_of(b, hurt_flat) & DFI_POSFLAG_HURT) != 0u, hurt_after_turn);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

static void test_av_hurt(df_test *t)
{
    /* Raichu's Thunderbolt on Milotic (flat 3) and Umbreon's Assurance on Milotic: Milotic is hurt in turn 1, and the turn ends
     * at a TURN boundary (Raichu survives at 19/164, as in the trace: no faint, no switch request), where endTurn cleared HURT. */
    test_av_turn(t, "g88_av_hurt", 3u, DUOFORGE_BOUNDARY_TURN, false);
}

static void test_av_control(df_test *t)
{
    /* Umbreon's Assurance on Salamence (flat 2), which nobody hit before it: unhurt, so 60 base power. Raichu faints in turn 1
     * (trace: Salamence's Dragon Claw, then Milotic's Alluring Voice |faint|p1a: Raichu|), so the end-of-turn replacement makes the
     * boundary REPLACEMENT. That boundary comes before endTurn, so Salamence's HURT from Assurance is still set there. */
    test_av_turn(t, "g88_av_control", 2u, DUOFORGE_BOUNDARY_REPLACEMENT, true);
}

/* g88_pivot_turn_history: Raichu's Volt Switch makes the PIVOT boundary of turn 1 while Umbreon (flat 1) knows Lash Out and
 * Assurance; the public record and the causes call of that state name DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, and the record refuses. */
static void test_pivot_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g88_pivot_turn_history", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 2u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY);
        duoforge_public_state pub;
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, player, &pub), DUOFORGE_E_UNSUPPORTED);
    }
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* g88_lo_intimidate at the first decision (turn 1, after team selection, before any move): Intimidate has lowered Umbreon, and
 * LOWERED_THIS_TURN survives into turn 1 (sim/battle.ts:1677-1683 keeps it), but the view does not carry the bit. Umbreon knows
 * Lash Out, so the public record and the causes call of that decision name DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY (decision 0046,
 * section 3). A counted refusal: both players refuse. */
static void test_lo_turn1_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g88_lo_intimidate", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK_EQ_U64(t, replay_steps(ctx, b, cb, 0u, 1u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->turn, 1u);
    DF_CHECK(t, (flags_of(b, 0u) & DFI_POSFLAG_LOWERED) != 0u);
    uint32_t refused = 0u;
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, player, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY, DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY);
        duoforge_public_state pub;
        if (duoforge_battle_public(ctx, b, player, &pub) == DUOFORGE_E_UNSUPPORTED) {
            refused += 1u;
        }
    }
    DF_CHECK_EQ_U64(t, refused, 2u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g88");
    test_row(&t);
    test_lo_turn1_refusal(&t);
    test_lo_intimidate(&t);
    test_av_hurt(&t);
    test_av_control(&t);
    test_pivot_refusal(&t);
    return df_test_end(&t);
}
