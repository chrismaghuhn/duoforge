/*
 * duoforge.state.pool_g60 (white-box): step G60 of the content expansion, Substitute (decision 0032).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the approved public values (VOLATILE_SUBSTITUTE 9, FAIL_SUBSTITUTE_EXISTS 1, FAIL_SUBSTITUTE_WEAK 2, the public cause
 *     SUBSTITUTE 8), with the view bit that the position's presence uses;
 *   - the marks: the Substitute is supported; Baton Pass, Shed Tail, Tidy Up and Defog are not (decision 0032 section 7);
 *   - the bypasssub column (dfi_pool_move_bypasssub, generated, appended last to the canonical pool bytes): the moves that carry
 *     flags.bypasssub in the pin have 1, the Substitute and the moves that do not carry it have 0;
 *   - the public record of a battle with a Substitute on either side refuses (E_UNSUPPORTED) with the cause bit set, and a battle
 *     without one is not refused by the cause (the causes mask is the one predicate of both).
 * The engine's behaviour (the hit gate, the cost, the break, the events, Intimidate, the resist berries) is pinned by the seven
 * recorded battles tests/reference/traces/g60_sub_*.json, replayed by duoforge.reference.conformance_pool_data.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/turn.h"
#include "state/request.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

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

/* The approved values, and the supported and unsupported rows of decision 0032 section 7. */
static void check_values_and_marks(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_SUBSTITUTE, 9u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FAIL_SUBSTITUTE_EXISTS, 1u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FAIL_SUBSTITUTE_WEAK, 2u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE, 8u);
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_SUBSTITUTE, 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SUBSTITUTE, 82u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SUBSTITUTE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INFILTRATOR] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INTIMIDATE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BATONPASS] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SHEDTAIL] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_TIDYUP] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_DEFOG] == 0u);
}

/* The generated column: 1 for each marked move with flags.bypasssub in the pin (data/moves.ts), 0 for the others. */
static void check_bypass_column(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_ENCORE], 1u);     /* data/moves.ts:4732 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_COACHING], 1u);   /* data/moves.ts:2598 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_DISABLE], 1u);    /* data/moves.ts:3656 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_TAUNT], 1u);      /* data/moves.ts:18982 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_IMPRISON], 1u);   /* data/moves.ts:9497 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_PERISHSONG], 1u); /* data/moves.ts:13241 */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_SUBSTITUTE], 0u); /* data/moves.ts:18312: snatch, nonsky, metronome */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_YAWN], 0u);       /* data/moves.ts:21139: no bypasssub */
    DF_CHECK_EQ_U64(t, dfi_pool_move_bypasssub[DFI_MOVE_PROTECT], 0u);
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
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
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step): the battle is the engine's own, not a
 * hand-made state. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* A battle with a Substitute on a side is refused by the public record with the SUBSTITUTE cause, on either side; the same battle
 * without one is not (decision 0032 section 4: the owner's request shows no Substitute HP either, so no honest world can rebuild
 * one). The battles are the recorded g60_sub_chople, after its first turn (Kingambit's Substitute is up at its first position) and
 * before it (the team step only). */
static void check_public_refusal(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *none = replay(t, ctx, "g60_sub_chople", 1u);
    DF_CHECK(t, none != NULL);
    if (none != NULL) {
        uint32_t mask = 0u;
        duoforge_public_state out;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, none, 0u, &mask), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, mask & DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE, 0u);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, none, 0u, &out), DUOFORGE_OK);
        duoforge_battle_destroy(none);
    }

    duoforge_battle *b = replay(t, ctx, "g60_sub_chople", 2u);
    DF_CHECK(t, b != NULL);
    if (b == NULL) {
        return;
    }
    DF_CHECK(t, b->tail.sides[0].positions[0].substitute_hp != 0u); /* Kingambit's Substitute is up */
    uint32_t mask = 0u;
    duoforge_public_state out;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 0u, &mask), DUOFORGE_OK);
    DF_CHECK(t, (mask & DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE) != 0u);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &out), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 1u, &out), DUOFORGE_E_UNSUPPORTED); /* the foe sees the same presence */

    /* a foe's Substitute refuses too: the cause is either side (the foe's first position stands, its HP is below a quarter) */
    b->tail.sides[0].positions[0].substitute_hp = 0u;
    b->tail.sides[1].positions[0].substitute_hp = 20u;
    mask = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 0u, &mask), DUOFORGE_OK);
    DF_CHECK(t, (mask & DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE) != 0u);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &out), DUOFORGE_E_UNSUPPORTED);

    b->tail.sides[1].positions[0].substitute_hp = 0u;
    mask = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 0u, &mask), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mask & DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE, 0u);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &out), DUOFORGE_OK);
    duoforge_battle_destroy(b);
}

/* The view's presence bit (DUOFORGE_POSITION_EXT_SUBSTITUTE) of a position, read by both players: a standing Substitute is public
 * presence on both sides (decision 0032 section 4), the break and a switch-out clear it. `expect` is the bit of side 0's first
 * position for both viewers; every other position must be clear. */
static void expect_presence(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const char *what, bool expect)
{
    for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
        duoforge_observation_ext ob;
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, &ob), DUOFORGE_OK);
        for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const bool bit = (ob.sides[side].positions[p].volatiles & DUOFORGE_POSITION_EXT_SUBSTITUTE) != 0u;
                const bool want = expect && side == 0u && p == 0u;
                if (bit != want) {
                    fprintf(stderr, "  %s: viewer %u side %u position %u presence %d, expected %d\n", what, (unsigned)viewer,
                            (unsigned)side, (unsigned)p, (int)bit, (int)want);
                }
                DF_CHECK_EQ_U64(t, (uint64_t)bit, (uint64_t)want);
            }
        }
    }
}

static void check_observation_bit(df_test *t, const duoforge_context *ctx)
{
    /* a standing Substitute: Kingambit's, after its first turn (g60_sub_absorb, the Substitute is up at the end of step 1) */
    duoforge_battle *up = replay(t, ctx, "g60_sub_absorb", 2u);
    DF_CHECK(t, up != NULL);
    if (up != NULL) {
        DF_CHECK(t, up->tail.sides[0].positions[0].substitute_hp != 0u);
        expect_presence(t, ctx, up, "absorb, the Substitute stands", true);
        duoforge_battle_destroy(up);
    }
    /* after the break: g60_sub_basic's Dragon Claw breaks Gengar's Substitute in step 1, and nothing raises one after it */
    duoforge_battle *broken = replay(t, ctx, "g60_sub_basic", 2u);
    DF_CHECK(t, broken != NULL);
    if (broken != NULL) {
        DF_CHECK_EQ_U64(t, (uint64_t)broken->tail.sides[0].positions[0].substitute_hp, 0u);
        expect_presence(t, ctx, broken, "basic, after the break", false);
        duoforge_battle_destroy(broken);
    }
    /* a switch-out: g60_sub_switchout raises it in step 1 (the presence stands), and in step 2 Rillaboom replaces Kingambit in
     * the position with no line for it (the presence goes with the occupant) */
    duoforge_battle *before = replay(t, ctx, "g60_sub_switchout", 2u);
    DF_CHECK(t, before != NULL);
    if (before != NULL) {
        expect_presence(t, ctx, before, "switch-out, before the switch", true);
        duoforge_battle_destroy(before);
    }
    duoforge_battle *after = replay(t, ctx, "g60_sub_switchout", 3u);
    DF_CHECK(t, after != NULL);
    if (after != NULL) {
        DF_CHECK_EQ_U64(t, (uint64_t)after->tail.sides[0].positions[0].substitute_hp, 0u);
        expect_presence(t, ctx, after, "switch-out, after the switch", false);
        duoforge_battle_destroy(after);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g60");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(&t, ctx != NULL);
    check_values_and_marks(&t);
    check_bypass_column(&t);
    if (ctx != NULL) {
        check_public_refusal(&t, ctx);
        check_observation_bit(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
