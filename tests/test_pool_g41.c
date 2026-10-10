/*
 * duoforge.state.pool_g41 (white-box): step G41 of the content expansion, Shadow Tag (and Gengarite, the stone of the only forme
 * that has it).
 *
 * Shadow Tag (data/abilities.ts:4156-4173) traps every adjacent foe that is not a holder itself and not a Ghost type: at the TURN
 * boundary the foe's request refuses every switch (src/combat/turn.c dfi_switch_trapped, read by src/state/request.c). It shows
 * no line and keeps no state, so the recorded battles replay it without showing it (a planned switch of a trapped Pokemon is
 * turned into a move by the recorder, as the request says it is trapped): this test replays them to the interesting turns and
 * asks the real request builder for the complete joint domain of each player.
 *
 *   - g41_shadow_tag: nobody is trapped before the Gengar has Mega Evolved; at turn 2 both Pokemon of side 1 are, side 0 is not;
 *     the pivot of a U-turn at the boundary in between is free;
 *   - g41_shadow_tag_ghost: the Ghost and Steel type is free, its partner is not, and the partner's U-turn pivots;
 *   - g41_shadow_tag_soak: Soak makes the Dragon and Ghost type a Water type, trapped from the next turn;
 *   - g41_shadow_tag_second: the Gengar stands in the second position of its side (a probe that asks only the foe's first position
 *     finds nobody trapped);
 *   - g41_shadow_tag_fainted: the foes take down the Gengar's ally and both reserves, then the Gengar itself: with no reserve left the
 *     fainted Gengar stays in its position, and from the next TURN boundary it traps nobody (the foes' side is free);
 *   - g41_shadow_tag_trace: a Trace copy of Shadow Tag traps the Kingambit beside the Gengar (the Gengar is a holder and exempt),
 *     and the Staraptor beside the Gardevoir (a holder through the copy) is trapped by the Gengar.
 *
 * Why the exclusion leaks nothing (decision 0007: the open team sheets and the lines are public): the trap is a function of the
 * foes' current abilities and the types of the Pokemon, all of them public. The Mega forme and its single ability are known from
 * the Mega Stone on the sheet and the `-mega` line, a Trace copy is a `-ability` line, a type change is a `-start|typechange`
 * line. The pin tells the last active Pokemon only `maybeTrapped` and refuses the switch ([Unavailable choice], sim/side.ts:
 * 527-534, 984-1000); the engine's domain simply has no switch, and the differential harness (tools/reference/ps_play.js) treats
 * that refusal as consistent.
 *
 * The rows that would free the holder, or move or suppress the ability, are unmarked, so no battle has them: the guard below names
 * each of them, and marking any of them fails here until dfi_switch_trapped reads it.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step). */
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

/* Whether any candidate of `player`'s joint domain has a switch in `slot` (and that there are candidates at all). */
static bool offers_switch(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player, uint32_t slot)
{
    static duoforge_side_choice buf[4096];
    uint32_t n = 0u;
    DF_CHECK(t, duoforge_battle_candidates(ctx, b, player, buf, 4096u, &n) == DUOFORGE_OK);
    DF_CHECK(t, n != 0u);
    for (uint32_t i = 0u; i < n && i < 4096u; ++i) {
        if (buf[i].slots[slot].kind == DUOFORGE_SLOT_SWITCH) {
            return true;
        }
    }
    return false;
}

/* The state after `steps` steps is a TURN boundary where flat position `p` is trapped (or not): the predicate and the domain
 * agree, both for the position and for the moves, which stay offered. */
static void expect_turn(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, const bool trapped[4])
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    for (uint32_t flat = 0u; flat < 4u; ++flat) {
        DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, flat) ? 1u : 0u, trapped[flat] ? 1u : 0u);
        DF_CHECK_EQ_U64(t, offers_switch(t, ctx, b, flat / 2u, flat % 2u) ? 1u : 0u, trapped[flat] ? 0u : 1u);
    }
    duoforge_battle_destroy(b);
}

/* The state after `steps` steps is a TURN boundary where positions 2 and 3 (side 1) are trapped or not: the predicate and the
 * domain of side 1 agree, and nobody on side 0 is trapped (side 1 has no holder). Side 0 may have no reserve left, so its domain is
 * not asked. */
static void expect_side1(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, bool trapped2, bool trapped3)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, 0u) ? 1u : 0u, 0u);
    DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, 1u) ? 1u : 0u, 0u);
    DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, 2u) ? 1u : 0u, trapped2 ? 1u : 0u);
    DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, 3u) ? 1u : 0u, trapped3 ? 1u : 0u);
    DF_CHECK_EQ_U64(t, offers_switch(t, ctx, b, 1u, 0u) ? 1u : 0u, trapped2 ? 0u : 1u);
    DF_CHECK_EQ_U64(t, offers_switch(t, ctx, b, 1u, 1u) ? 1u : 0u, trapped3 ? 0u : 1u);
    duoforge_battle_destroy(b);
}

/* The state after `steps` steps is a PIVOT boundary of side `side` at `slot`: the switch is offered although the Pokemon is trapped. */
static void expect_pivot_free(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, uint32_t side,
                              uint32_t slot, bool trapped_at_turn)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
    DF_CHECK_EQ_U64(t, dfi_switch_trapped(b, side * 2u + slot) ? 1u : 0u, trapped_at_turn ? 1u : 0u);
    DF_CHECK(t, offers_switch(t, ctx, b, side, slot));
    duoforge_battle_destroy(b);
}

static void check_domain(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    /* flat 0, 1: side 0 slots 0, 1; flat 2, 3: side 1 */
    static const bool none[4] = {false, false, false, false};
    static const bool side1_both[4] = {false, false, true, true};
    static const bool ghost_free[4] = {false, false, false, true};
    static const bool trace[4] = {false, true, false, true};
    static const bool soak[4] = {false, false, true, true};
    /* before the Mega Evolution nobody is trapped (the traps are computed at the start of a turn) */
    expect_turn(t, ctx, "g41_shadow_tag", 1u, none);
    /* turn 1's U-turn: the pivot boundary of side 1's slot 1 is free; turn 2: both are trapped, side 0 is not */
    expect_pivot_free(t, ctx, "g41_shadow_tag", 2u, 1u, 1u, true);
    expect_turn(t, ctx, "g41_shadow_tag", 3u, side1_both);
    /* the Ghost and Steel Gholdengo is free at turn 2, the Staraptor beside it is not, and its U-turn pivots */
    expect_turn(t, ctx, "g41_shadow_tag_ghost", 2u, ghost_free);
    expect_pivot_free(t, ctx, "g41_shadow_tag_ghost", 4u, 1u, 1u, true);
    /* Soak: the Dragon and Ghost type is free at turn 1 and a Water type from turn 2 */
    expect_turn(t, ctx, "g41_shadow_tag_soak", 1u, none);
    expect_turn(t, ctx, "g41_shadow_tag_soak", 2u, soak);
    /* a Trace copy of Shadow Tag: the holder (own or copied) is exempt, the Pokemon beside a holder is trapped by the other */
    expect_turn(t, ctx, "g41_shadow_tag_trace", 6u, trace);
    /* the Gardevoir has fainted and a Milotic has come in: nothing is copied any more, the Kingambit's side is free and the foes are
     * trapped by the Gengar alone (the trap is recomputed at every TURN boundary) */
    expect_turn(t, ctx, "g41_shadow_tag_trace", 9u, soak);
    /* the Gengar in the second position: both foes are trapped (a probe of the foe's first position only would miss it) */
    expect_turn(t, ctx, "g41_shadow_tag_second", 1u, none);
    expect_turn(t, ctx, "g41_shadow_tag_second", 2u, side1_both);
    /* the Gengar and its ally have both reserves taken (the Sneasler and the Milotic fell, the Ceruledge stands): the Gengar still
     * traps at turn 7, and after it fainted with no reserve left (it stays in its position, hp 0) it traps nobody at turn 9 */
    expect_side1(t, ctx, "g41_shadow_tag_fainted", 7u, true, true);
    expect_side1(t, ctx, "g41_shadow_tag_fainted", 9u, false, false);
    duoforge_context_destroy(ctx);
}

/* What would free the holder, or move, copy, take away or hide the ability, or trap in another way, is not marked: no battle has
 * it, and the trap rule reads none of it. Each is named, so that marking any of them fails here until dfi_switch_trapped reads it
 * (Shed Shell and Run Away free their holder, onTrapPokemon at priority -10 after Shadow Tag's; Skill Swap, Role Play, Entrainment,
 * Simple Beam, Worry Seed, Wandering Spirit and Mummy move or replace an ability; Gastro Acid suppresses it; Neutralizing Gas is not
 * in the pool; Illusion hides the Pokemon whose types and ability count; Mean Look and Block trap in their own way). Trace is
 * marked and is public (the `-ability` line); a type change is Soak's (marked, public). */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SHADOWTAG] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_SHADOWTAG], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_GENGARITE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CURSEDBODY] != 0u); /* Gengar's own ability: the base of the Mega */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_TRACE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SOAK] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SHEDSHELL] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RUNAWAY] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_ILLUSION] != 0u); /* marked by step I2 (decision 0026): this step left it unmarked */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_WANDERINGSPIRIT] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MUMMY] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SKILLSWAP] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ROLEPLAY] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ENTRAINMENT] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_GASTROACID] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SIMPLEBEAM] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_WORRYSEED] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_MEANLOOK] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BLOCK] == 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g41");
    check_marks(&t);
    check_domain(&t);
    return df_test_end(&t);
}
