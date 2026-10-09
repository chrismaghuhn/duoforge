/*
 * duoforge.state.pool_g49 (white-box): step G49 of the content expansion, the item rows Muscle Band, Wise Glasses and
 * Bright Powder (decision 0015, item 5am). The duration rows (Damp Rock, Heat Rock, Smooth Rock, Icy Rock and Terrain
 * Extender) are not part of this step: the Python live tracker keeps weather and terrain turns at 5 (python/duoforge_live).
 *
 *   - Muscle Band (data/items.ts:4239-4251) and Wise Glasses (data/items.ts:7754-7766): base power x4505/4096 for a Physical
 *     and a Special move of the holder, onBasePowerPriority 16, so after Sharpness (19) and before the type boosters (15).
 *   - Bright Powder (data/items.ts:659-670): the accuracy of a move against the holder x3686/4096, onModifyAccuracyPriority -2,
 *     the same priority as Wide Lens (data/items.ts:7719-7726, the attacker's side). The two of priority -2 have no order in
 *     the pin (the holders' Speed, an exact tie draws), so the engine computes both orders and refuses a move for which they
 *     give different accuracies (E_UNSUPPORTED). The multi-hit path refuses a target with Bright Powder (the loop applies
 *     ModifyAccuracy after the stages, as it does for Wide Lens).
 *
 * The recorded battles (g49_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares
 * everything the reference shows. Here are the facts that it does not show:
 *   - the marks and the handler columns of the three rows (ENGINE_ROWS: no handler, not UNMODELED, no family);
 *   - the chain arithmetic: the modifiers, and for which base accuracies the two orders of Wide Lens and Bright Powder give
 *     different accuracies, for each prefix that Compound Eyes and Snow Cloak or Sand Veil make before them;
 *   - the two refusals, each with a control that the same battle with the powder removed (or a Sitrus Berry) is accepted:
 *       (a) Compound Eyes and Wide Lens on the attacker, Bright Powder on the target, a move of accuracy 75 (Sleep Powder,
 *           Vivillon): the two orders give 97 and 96, so the step is E_UNSUPPORTED (a battle built here, step API);
 *       (b) a multi-hit multiaccuracy move (Triple Axel, the recorded g33_triple_axel battle) into a Bright Powder holder:
 *           its first hit hits (the recorded draw is below 81), its second hit's check is refused (E_UNSUPPORTED).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/modifier.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The modified accuracy of a move with base accuracy `base` under the chain `chain` (dfi_modify, as the engine computes it). */
static uint32_t modified(uint32_t base, uint32_t chain)
{
    return dfi_modify(base, chain);
}

/* The two orders of Wide Lens (4505) and Bright Powder (3686) after a prefix chain (as the engine chains them): the chain
 * value of each order, and how many base accuracies (1 to 100) give a different modified accuracy in the two orders. */
static uint32_t order_chains(uint32_t prefix, uint32_t *wide_first, uint32_t *powder_first, uint32_t *differing)
{
    uint32_t a = prefix;
    uint32_t b = prefix;
    const bool ok = dfi_chain_modify(prefix, 4505u, &a) && dfi_chain_modify(a, 3686u, &a) &&
                    dfi_chain_modify(prefix, 3686u, &b) && dfi_chain_modify(b, 4505u, &b);
    *wide_first = a;
    *powder_first = b;
    *differing = 0u;
    for (uint32_t acc = 1u; acc <= 100u; ++acc) {
        *differing += modified(acc, a) != modified(acc, b) ? 1u : 0u;
    }
    return ok ? 1u : 0u;
}

/* ---- the recorded battles, as the conformance tests build them (the G34 pattern) ---- */

/* One member's item replaced: side, member and the item code (1 + id). side -1: none. */
typedef struct {
    int side;
    uint32_t member;
    uint32_t item;
} df_patch;

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s, const df_patch *p)
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
            if (p != NULL && p->side == (int)side && p->member == m) {
                dst->item = p->item;
            }
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

/* The first step that does not return OK (or step_count when none), and its status. */
static uint32_t play(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, const df_patch *p, duoforge_status *status)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup, p);
    duoforge_battle *b = NULL;
    *status = DUOFORGE_OK;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return 0u;
    }
    uint32_t si = 0u;
    for (; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        *status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (*status != DUOFORGE_OK) {
            break;
        }
    }
    duoforge_battle_destroy(b);
    return si;
}

/* ---- (a) Vivillon: Compound Eyes and Wide Lens against Bright Powder, Sleep Powder (accuracy 75) ---- */

/* The battle of g49_bright_powder's team, with the attacker at side 0 member 0 replaced by Vivillon (Compound Eyes, Wide
 * Lens, Sleep Powder and Protect), and the target (side 1 member 0, Milotic) holding `target_item`. Two steps: the team, then
 * Vivillon's Sleep Powder at Milotic (slot 0 of side 1) and Coil and Protect for the others. Returns the status of the turn. */
static duoforge_status vivillon_turn(df_test *t, duoforge_context *ctx, uint32_t target_item)
{
    const df_conf_battle *cb = find("g49_bright_powder");
    if (!DF_CHECK(t, cb != NULL)) {
        return DUOFORGE_E_INVARIANT;
    }
    const df_patch target = {1, 0u, target_item};
    duoforge_battle_setup setup;
    build_setup(cb, &setup, &target);
    duoforge_member_setup *v = &setup.sides[0].members[0];
    v->species_id = DFI_FORME_VIVILLON;
    v->gender = DUOFORGE_GENDER_FEMALE;
    v->ability = 1u + DFI_ABILITY_COMPOUNDEYES;
    v->item = 1u + DFI_ITEM_WIDELENS;
    v->move_count = 2u;
    v->moves[0].move_id = DFI_MOVE_SLEEPPOWDER;
    v->moves[1].move_id = DFI_MOVE_PROTECT;
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    bundle_of(&cb->steps[0], b, &bd); /* the team selection, as recorded */
    DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_OK);
    /* The turn: Vivillon's Sleep Powder (slot 0) at the foe in position 2 (side 1, slot 0); Gholdengo's Protect; the foe's
     * Coil (slot 2, self) and Incineroar's Protect (slot 2). */
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    const duoforge_slot_command mine[2] = {{DUOFORGE_SLOT_MOVE, 0u, 2u, 0u, 0u, {0u, 0u, 0u}},
                                           {DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}}};
    const duoforge_slot_command theirs[2] = {{DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}},
                                             {DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}}};
    for (uint32_t s = 0; s < 2u; ++s) {
        duoforge_side_choice *r = &bd.responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        r->slots[0] = s == 0u ? mine[0] : theirs[0];
        r->slots[1] = s == 0u ? mine[1] : theirs[1];
    }
    const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
    duoforge_battle_destroy(b);
    return st;
}

static void check_vivillon_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    /* the control: the powder is a Sitrus Berry, the same turn is accepted */
    DF_CHECK_EQ_U64(t, vivillon_turn(t, ctx, 1u + DFI_ITEM_SITRUSBERRY), DUOFORGE_OK);
    /* Bright Powder: the orders give 97 and 96 for accuracy 75 (Compound Eyes, Wide Lens, Bright Powder), so refused */
    DF_CHECK_EQ_U64(t, vivillon_turn(t, ctx, 1u + DFI_ITEM_BRIGHTPOWDER), DUOFORGE_E_UNSUPPORTED);
    duoforge_context_destroy(ctx);
}

/* ---- (b) Triple Axel into a Bright Powder holder (the recorded g33_triple_axel battle) ---- */

static void check_triple_axel_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g33_triple_axel");
    if (!DF_CHECK(t, cb != NULL)) {
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    /* as recorded: every step is played */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, NULL, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* The foe Primarina (side 1) holds Bright Powder: step 2 (index 1), Milotic's Triple Axel, hits once (its first draw, 44,
     * is below 81, the powder's accuracy for 90) and the second hit is refused before its draw. */
    uint32_t prim = 0u;
    for (uint32_t m = 0; m < cb->member_count; ++m) {
        if (cb->members[1][m].species == DFI_FORME_PRIMARINA) {
            prim = m;
        }
    }
    const df_patch powder = {1, prim, 1u + DFI_ITEM_BRIGHTPOWDER};
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, &powder, &st), 1u);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    duoforge_context_destroy(ctx);
}

static void check_facts(df_test *t)
{
    static const uint32_t items[] = {DFI_ITEM_MUSCLEBAND, DFI_ITEM_WISEGLASSES, DFI_ITEM_BRIGHTPOWDER};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[items[i]].family, DFI_ITEM_FAMILY_NONE);
    }
    /* The duration rows stay unmarked: their step is not this one. */
    static const uint32_t unmarked[] = {DFI_ITEM_DAMPROCK, DFI_ITEM_HEATROCK, DFI_ITEM_SMOOTHROCK, DFI_ITEM_ICYROCK,
                                        DFI_ITEM_TERRAINEXTENDER};
    for (size_t i = 0u; i < sizeof unmarked / sizeof unmarked[0]; ++i) {
        DF_CHECK(t, dfi_support.items[unmarked[i]] == 0u);
    }
    /* The modifiers as the pin writes them: 4505/4096 is 1.1 and 3686/4096 is 0.9 of the base accuracy or power. */
    DF_CHECK_EQ_U64(t, modified(100u, 4505u), 110u);
    DF_CHECK_EQ_U64(t, modified(100u, 3686u), 90u);
    DF_CHECK_EQ_U64(t, modified(85u, 3686u), 76u);
    DF_CHECK_EQ_U64(t, modified(100u, 4096u), 100u);
}

static void check_orders(df_test *t)
{
    uint32_t wide = 0u;
    uint32_t powder = 0u;
    uint32_t differing = 0u;
    /* No prefix, or Snow Cloak's 3277 before them: a chain of two is the same in either order. */
    DF_CHECK(t, order_chains(4096u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 4054u);
    DF_CHECK_EQ_U64(t, powder, 4054u);
    DF_CHECK_EQ_U64(t, differing, 0u);
    DF_CHECK(t, order_chains(3277u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, powder);
    DF_CHECK_EQ_U64(t, differing, 0u);
    /* Compound Eyes (5325) before them: the chains are 5271 and 5270; the orders differ for the base accuracies 68 and 75. */
    DF_CHECK(t, order_chains(5325u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 5271u);
    DF_CHECK_EQ_U64(t, powder, 5270u);
    DF_CHECK_EQ_U64(t, differing, 2u);
    DF_CHECK(t, modified(68u, wide) != modified(68u, powder));
    DF_CHECK(t, modified(75u, wide) != modified(75u, powder));
    DF_CHECK(t, modified(100u, wide) == modified(100u, powder));
    DF_CHECK(t, modified(90u, wide) == modified(90u, powder));
    /* Compound Eyes and Snow Cloak together (4260 before the two): they differ for the base accuracies 17, 51 and 85. */
    DF_CHECK(t, order_chains(4260u, &wide, &powder, &differing) == 1u);
    DF_CHECK_EQ_U64(t, wide, 4216u);
    DF_CHECK_EQ_U64(t, powder, 4217u);
    DF_CHECK_EQ_U64(t, differing, 3u);
    DF_CHECK(t, modified(85u, wide) != modified(85u, powder));
    DF_CHECK(t, modified(100u, wide) == modified(100u, powder));
    /* The refusal of (a) is at 75 with Compound Eyes: 97 against 96 (the numbers the test above relies on). */
    DF_CHECK_EQ_U64(t, modified(75u, 5271u), 97u);
    DF_CHECK_EQ_U64(t, modified(75u, 5270u), 96u);
}

static void check_recorded(df_test *t)
{
    static const char *names[] = {"g49_wise_glasses", "g49_wise_glasses_base", "g49_muscle_band", "g49_muscle_band_base",
                                  "g49_bright_powder", "g49_bright_powder_base", "g49_category_cross",
                                  "g49_bright_powder_tie"};
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        DF_CHECK(t, find(names[i]) != NULL);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g49");
    check_facts(&t);
    check_orders(&t);
    check_recorded(&t);
    check_vivillon_refusal(&t);
    check_triple_axel_refusal(&t);
    return df_test_end(&t);
}
