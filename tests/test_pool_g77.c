/*
 * duoforge.state.pool_g77 (white-box): step G77 of the content expansion (decision 0015, item 5bq, the crit package), POOL build.
 *
 * Four rows, read by id in combat/turn.c:
 *   Magma Armor   onImmunity 'frz' refuses every freeze of its holder (Immunity, after the natural immunities and before
 *                 SetStatus); its onUpdate cure is not modelled: a frozen holder that gains the ability (Trace, Skill Swap) is refused
 *   Anger Point   onHit: a critical hit that the holder takes from a primary move raises its Attack by 12 (capped at +6), the line
 *                 -setboost with [from] ability: Anger Point (sim/battle.ts:2050-2053)
 *   Sniper        onModifyDamage of the attacker: x1.5 (6144/4096) on a critical hit, in the ModifyDamage chain
 *   Leek          onModifyCritRatio of the holder: +2 when its base species is Farfetch'd or Sirfetch'd
 *
 * The recorded battles (g77_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares every
 * event, HP and draw with the reference. Here are the facts that they do not show by themselves:
 *   - the marks and the handler columns: the four rows are marked engine rows (family NONE, handler NONE); Mold Breaker, which
 *     would ignore the breakable flag of Magma Armor, is not marked and stays UNMODELLED;
 *   - the ModifyDamage chain holds at most DFI_MODIFY_DAMAGE_MAX modifiers, and dfi_mods_push refuses the ninth (E_UNSUPPORTED)
 *     without writing past the list. The maximum for one hit is six (turn.c, the comment of combat/damage_chain.h): Sniper is
 *     a crit-only modifier and a screen is not applied to a crit, so the two never meet;
 *   - the chain of a critical hit with Life Orb, a resist berry, Solid Rock and Sniper does not commute: the engine refuses that
 *     hit (E_UNSUPPORTED), and the reference orders those four by speed (a tie); the converter drops nothing of it;
 *   - Skill Swap that would hand a frozen Pokemon Magma Armor, or hand Magma Armor away from a frozen Pokemon, is refused, and the
 *     refusal changes nothing (dfi_skill_swap_decision); the same swap with the status absent proceeds;
 *   - Trace copying Magma Armor onto a frozen holder is refused (E_UNSUPPORTED) and the battle is unchanged: the battle is the
 *     recorded ac1_trace_switch with both foes given Magma Armor now and Gardevoir frozen when it comes back in.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/damage_chain.h"
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define AB(name) (1u + DFI_ABILITY_##name)

/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_MAGMAARMOR, DFI_ABILITY_ANGERPOINT, DFI_ABILITY_SNIPER};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LEEK] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LEEK], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_family[DFI_ITEM_LEEK].family, DFI_ITEM_FAMILY_NONE);
    /* Mold Breaker would ignore the breakable flag of Magma Armor: it is not marked, and its row is UNMODELLED */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

/* ---- the ModifyDamage list: the bound, and the refusal of a write past it */
static void check_chain_bound(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_MODIFY_DAMAGE_MAX, 8u);
    uint32_t list[DFI_MODIFY_DAMAGE_MAX] = {0u};
    uint32_t mods = 0u;
    for (uint32_t i = 0u; i < DFI_MODIFY_DAMAGE_MAX; ++i) {
        DF_CHECK(t, dfi_mods_push(list, &mods, 2048u + i));
    }
    DF_CHECK_EQ_U64(t, mods, DFI_MODIFY_DAMAGE_MAX);
    /* the ninth is refused: the count and the list are unchanged, nothing is written past the end */
    DF_CHECK(t, !dfi_mods_push(list, &mods, 4096u));
    DF_CHECK_EQ_U64(t, mods, DFI_MODIFY_DAMAGE_MAX);
    DF_CHECK_EQ_U64(t, list[DFI_MODIFY_DAMAGE_MAX - 1u], 2048u + DFI_MODIFY_DAMAGE_MAX - 1u);
}

/* ---- the commutation of the chain with Sniper: the sets the engine refuses, and the ones it chains */
static void check_commute(df_test *t)
{
    /* Life Orb 5324, a resist berry 2048, Solid Rock 3072 and Sniper 6144 on one critical super-effective hit: the chain takes
     * 2995 or 2996 by the order of its four factors, so the engine refuses the hit */
    const uint32_t refused[4] = {5324u, 2048u, 3072u, 6144u};
    DF_CHECK(t, !dfi_mods_commute(refused, 4u));
    /* Life Orb with Sniper and a resist berry (no Solid Rock, Friend Guard or Glaive Rush): every order gives 3993 */
    const uint32_t chains[3] = {5324u, 6144u, 2048u};
    DF_CHECK(t, dfi_mods_commute(chains, 3u));
    /* a resist berry, Glaive Rush and Sniper: every order gives 6144 */
    const uint32_t berry_glaive[3] = {6144u, 2048u, 8192u};
    DF_CHECK(t, dfi_mods_commute(berry_glaive, 3u));
}

/* ---- a recorded battle replayed to its leads (step 0: the team selection), the setters and the decisions */
static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

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

static void set_ability_now(duoforge_battle *b, uint32_t flat, uint32_t ability_id)
{
    b->tail.sides[flat / 2u].ability_now[b->sides[flat / 2u].positions[flat % 2u].occupant] = (uint16_t)(ability_id + 1u);
}

static void set_status(duoforge_battle *b, uint32_t flat, uint8_t status)
{
    b->sides[flat / 2u].members[b->sides[flat / 2u].positions[flat % 2u].occupant].status = status;
}

/* dfi_skill_swap_decision reads the state only: a refusal changes nothing before it, so the battle is compared before and after */
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

/* Skill Swap (decision 0041): the user (flat 0) and the target (flat 1) of the leads; the swap hands each one the other's ability,
 * so a frozen holder that receives Magma Armor is refused, and a Magma Armor holder whose partner is frozen is refused too */
static void check_skill_swap(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_to_leads(t, ctx, "g77_leek_anger_point");
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    set_ability_now(b, 1u, DFI_ABILITY_MAGMAARMOR); /* the target would hand its Magma Armor to the user */
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_PROCEED, "Magma Armor on a healthy receiver");
    set_status(b, 0u, DFI_STATUS_FRZ); /* the user, frozen, would receive it */
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_REFUSED, "Magma Armor to a frozen user");
    set_status(b, 0u, DFI_STATUS_NONE);
    set_ability_now(b, 1u, DFI_ABILITY_LIMBER);
    set_ability_now(b, 0u, DFI_ABILITY_MAGMAARMOR); /* the user holds Magma Armor; the target, frozen, would receive it */
    set_status(b, 1u, DFI_STATUS_FRZ);
    expect_decision(t, b, 0u, 1u, DFI_SKILL_SWAP_REFUSED, "Magma Armor to a frozen target");
    duoforge_battle_destroy(b);
}

/* Trace copying Magma Armor onto a frozen holder: refused (E_UNSUPPORTED) and the battle is unchanged (as Limber's refusal) */
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

static void check_trace_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("ac1_trace_switch");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 3u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < 3u; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK)) {
            duoforge_battle_destroy(b);
            return;
        }
    }
    /* Both foes hold Magma Armor now (so the draw of Trace keeps its two candidates), and the Trace holder that comes back in is
     * frozen. */
    for (uint32_t p = 0u; p < 2u; ++p) {
        const uint32_t occupant = b->sides[1].positions[p].occupant;
        if (DF_CHECK(t, occupant < DUOFORGE_MAX_ROSTER && b->sides[1].members[occupant].hp != 0u)) {
            b->tail.sides[1].ability_now[occupant] = (uint16_t)AB(MAGMAARMOR);
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if (b->sides[0].members[m].species_id == DFI_FORME_GARDEVOIR) {
            b->sides[0].members[m].status = DFI_STATUS_FRZ;
        }
    }
    duoforge_battle *before = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &before) == DUOFORGE_OK && before != NULL)) {
        const df_conf_step *st = &cb->steps[3];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                        DUOFORGE_E_UNSUPPORTED);
        bool equal = false;
        DF_CHECK(t, duoforge_battle_equal(ctx, b, before, &equal) == DUOFORGE_OK && equal);
    }
    duoforge_battle_destroy(before);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g77");
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_facts(&t);
    check_chain_bound(&t);
    check_commute(&t);
    if (kp != NULL) {
        check_skill_swap(&t, kp);
        check_trace_refusal(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
