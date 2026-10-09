/*
 * duoforge.state.pool_g70 (white-box): step G70 of the content expansion, Skill Swap (decision 0041).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the row: Skill Swap is marked (its handler is SKILL_SWAP, id 91, and UNMODELED follows it at 92); the other handler
 *     rows of the batch are not touched;
 *   - flags3 bit 2 (DFI_MOVE_FLAG3_BYPASSSUB): Skill Swap has flags.bypasssub in the pin (data/moves.ts:16598), so it is set;
 *   - the abilities that the swap moves are marked (no new ability row of this step): Trace, Synchronize, Intimidate, Pressure,
 *     Drizzle, Flash Fire, Cursed Body, Contrary, Levitate and Hospitality are supported, and Stance Change (its failskillswap,
 *     decision 0041) is the one that the swap fails on, marked only by step G66.
 * The engine's behaviour (the two ability events, the Start and End of the abilities that move, the ability copies, the Trace
 * draw, Hospitality, the Update refusals) is pinned by the recorded battles tests/reference/traces/g70_skillswap_*.json,
 * replayed by duoforge.reference.conformance_pool_data.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The setup of a recorded battle (as tests/test_pool_g47.c builds it), the step of a recorded battle and the battle after its
 * first `steps` steps (step 0 is the team step, which places the leads). */
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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static duoforge_battle *replay_to_leads(df_test *t, const duoforge_context *ctx, const char *name)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 1u)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    const df_conf_step *st = &cb->steps[0];
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
        r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        r->pick_count = 4u;
        for (uint32_t i = 0; i < 4u; ++i) {
            r->picks[i] = st->picks[s][i];
        }
    }
    duoforge_step_result res;
    uint32_t used = 0xFFFFFFFFu;
    const duoforge_status status =
        dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
    if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
        duoforge_battle_destroy(b);
        return NULL;
    }
    return b;
}

/* Skill Swap's decision (dfi_skill_swap_decision, decision 0041) on the battle with the leads placed: the user is flat 0 (p1a,
 * Gardevoir) and the target flat 1 (p1b, Espeon) of g70_skillswap_ally_trace. The rules are set on the state directly, and the
 * battle must not change: the decision reads the state only, and a refusal changes nothing before it. */
static void expect_decision(df_test *t, duoforge_battle *b, uint32_t user, uint32_t target, uint32_t want, const char *what)
{
    duoforge_battle snapshot;
    memcpy(&snapshot, b, sizeof snapshot);
    const uint32_t got = dfi_skill_swap_decision(b, user, target);
    DF_CHECK_EQ_U64(t, got, want);
    if (memcmp(&snapshot, b, sizeof snapshot) != 0) {
        fprintf(stderr, "  %s: the decision changed the battle\n", what);
        DF_CHECK(t, 0);
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

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step, which places the leads). */
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
        const duoforge_status status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The state that the swaps of the recorded battles leave, checked on the replayed battles (the protocol shows no end of a volatile
 * and no copy that is cleared, so the conformance runner cannot see these):
 *   - flash fire: Gardevoir (the user, flat 0) holds the flashfire volatile after Bitter Blade's hit, and the swap ends it;
 *   - swap back: Liepard (flat 1) holds Pressure (Gardevoir's entry copy) after the first swap and its own Unburden after the second, so its copy
 *     (ability_now) is cleared, as the sheet is the ability it has again. */
static void check_swap_state(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *before = replay(t, ctx, "g70_skillswap_flashfire_end", 2u);
    if (DF_CHECK(t, before != NULL)) {
        DF_CHECK(t, (before->sides[0].positions[0].flags & DFI_VOL_FLASH_FIRE) != 0u);
        duoforge_battle_destroy(before);
    }
    duoforge_battle *after = replay(t, ctx, "g70_skillswap_flashfire_end", 3u);
    if (DF_CHECK(t, after != NULL)) {
        DF_CHECK(t, (after->sides[0].positions[0].flags & DFI_VOL_FLASH_FIRE) == 0u);
        duoforge_battle_destroy(after);
    }
    duoforge_battle *once = replay(t, ctx, "g70_skillswap_swap_back", 3u);
    if (DF_CHECK(t, once != NULL)) {
        const uint32_t occ = once->sides[0].positions[1].occupant;
        DF_CHECK_EQ_U64(t, once->tail.sides[0].ability_now[occ], (uint64_t)DFI_ABILITY_PRESSURE + 1u);
        duoforge_battle_destroy(once);
    }
    duoforge_battle *back = replay(t, ctx, "g70_skillswap_swap_back", 4u);
    if (DF_CHECK(t, back != NULL)) {
        const uint32_t occ = back->sides[0].positions[1].occupant;
        DF_CHECK_EQ_U64(t, back->tail.sides[0].ability_now[occ], 0u);
        duoforge_battle_destroy(back);
    }
}

static void set_ability_now(duoforge_battle *b, uint32_t flat, uint32_t ability_id)
{
    b->tail.sides[flat / 2u].ability_now[b->sides[flat / 2u].positions[flat % 2u].occupant] = (uint16_t)(ability_id + 1u);
}

static void set_status(duoforge_battle *b, uint32_t flat, uint8_t status)
{
    b->sides[flat / 2u].members[b->sides[flat / 2u].positions[flat % 2u].occupant].status = status;
}

/* The refusals and the failure of the swap, each with the state that the pin's rule needs: an Update handler on a state its
 * holder has (E_UNSUPPORTED), failskillswap (the move's -fail) and the baseline (the swap proceeds). */
static void check_decisions(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_to_leads(t, ctx, "g70_skillswap_ally_trace");
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_PROCEED, "baseline");
    /* Limber: the user's ability is Limber and the target (the one that gets it) is paralysed */
    set_ability_now(b, 0u, DFI_ABILITY_LIMBER);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_PROCEED, "Limber on a healthy target");
    set_status(b, 1u, DFI_STATUS_PAR);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_REFUSED, "Limber on a paralysed target");
    /* Thermal Exchange: the target would hold it while burned */
    set_ability_now(b, 0u, DFI_ABILITY_THERMALEXCHANGE);
    set_status(b, 1u, DFI_STATUS_BRN);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_REFUSED, "Thermal Exchange on a burned target");
    set_status(b, 1u, 0u);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_PROCEED, "Thermal Exchange on a healthy target");
    /* Oblivious: the target would hold it while taunted (its taunt is a tail count, not a status) */
    set_ability_now(b, 0u, DFI_ABILITY_OBLIVIOUS);
    b->tail.sides[0].positions[1].taunt_turns = 2u;
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_REFUSED, "Oblivious on a taunted target");
    b->tail.sides[0].positions[1].taunt_turns = 0u;
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_PROCEED, "Oblivious on an untaunted target");
    /* Stance Change: failskillswap on either side makes the move fail (-fail and [still]) */
    set_ability_now(b, 0u, DFI_ABILITY_STANCECHANGE);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_FAILS, "Stance Change on the user");
    set_ability_now(b, 0u, DFI_ABILITY_TRACE);
    set_ability_now(b, 1u, DFI_ABILITY_STANCECHANGE);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_FAILS, "Stance Change on the target");
    /* a fainted target fails the move too */
    set_ability_now(b, 1u, DFI_ABILITY_SYNCHRONIZE);
    b->sides[0].members[b->sides[0].positions[1].occupant].hp = 0u;
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_FAILS, "a fainted target");
    duoforge_battle_destroy(b);
}

/* The row and its handler. */
static void check_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_SKILL_SWAP, DFI_SPECIAL_PHANTOM_FORCE + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_SKILL_SWAP + 1u);
    DF_CHECK_EQ_U64(t, DFI_MOVE_SKILLSWAP, 405u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SKILLSWAP] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SKILLSWAP].special, DFI_SPECIAL_SKILL_SWAP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SKILLSWAP].special == DFI_SPECIAL_UNMODELED ? 1u : 0u, 0u);
}

/* flags.bypasssub of the pin: the swap passes a Substitute (flags3 bit 2), and so do the moves that the pin marks with it. */
static void check_bypass(df_test *t)
{
    DF_CHECK(t, (dfi_pool_move_flags3[DFI_MOVE_SKILLSWAP] & DFI_MOVE_FLAG3_BYPASSSUB) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags3[DFI_MOVE_SUBSTITUTE] & DFI_MOVE_FLAG3_BYPASSSUB) == 0u);
}

/* The abilities the swap and its Start and End lines name are rows that the support manifest marks (decision 0041, table). */
static void check_abilities(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_TRACE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SYNCHRONIZE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INTIMIDATE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_PRESSURE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_DRIZZLE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_FLASHFIRE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CURSEDBODY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_HOSPITALITY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_LIMBER] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_THERMALEXCHANGE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_OBLIVIOUS] != 0u);
    /* Stance Change has failskillswap (data/abilities.ts:4531): its row is the one the swap refuses, and only step G66 marks it */
    DF_CHECK_EQ_U64(t, DFI_ABILITY_STANCECHANGE, 180u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g70");
    check_row(&t);
    check_bypass(&t);
    check_abilities(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(&t, ctx != NULL);
    if (ctx != NULL) {
        check_decisions(&t, ctx);
        check_swap_state(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
