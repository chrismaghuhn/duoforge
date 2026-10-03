/*
 * duoforge.state.pool_g33 (white-box): step G33 of the content expansion, the multi-hit moves Dual Wingbeat, Twin Beam and
 * Triple Axel and the ability Mirror Armor.
 *
 * The recorded battles (g33_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the
 * reference's draws, which compares everything that the reference shows. Here are the facts and the refusal that it does not
 * show:
 *
 *   - the marks and the handler numbers: the hit counts are in the handler ids (the static hit columns have no reader in the
 *     engine, duoforge.data.static_unread checks that), Population Bomb stays unmarked and keeps its data;
 *   - the later hits of a multiaccuracy move are checked with the loop's own arithmetic (scripts.ts:481-510), which the
 *     engine plays only without a ModifyAccuracy handler on the user: a Triple Axel user with Wide Lens (or Compound Eyes)
 *     is refused at its second hit, E_UNSUPPORTED, never played with the first hit's arithmetic.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/multiaccuracy.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_facts(df_test *t)
{
    static const uint32_t moves[] = {DFI_MOVE_DUALWINGBEAT, DFI_MOVE_TRIPLEAXEL, DFI_MOVE_TWINBEAM};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MIRRORARMOR] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MIRRORARMOR], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DUALWINGBEAT].special, DFI_SPECIAL_MULTI_HIT_2);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TWINBEAM].special, DFI_SPECIAL_MULTI_HIT_2);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].special, DFI_SPECIAL_TRIPLE_AXEL);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_TRIPLE_AXEL, DFI_SPECIAL_MULTI_HIT_2 + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_TRIPLE_AXEL + 1u);
    /* Population Bomb: no marked user, so no mark and no handler; its data stays */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_POPULATIONBOMB] == 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].special, DFI_SPECIAL_UNMODELED);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].accuracy, 90u);
}

/* The later-hit arithmetic is proved for the accuracy 90 only: every multiaccuracy move of the pool has it, and another
 * accuracy is refused (dfi_accuracy_check). The pool's multiaccuracy rows are checked against the helper here. */
static void check_proven_accuracy(df_test *t)
{
    DF_CHECK(t, dfi_multiaccuracy_proven(90u));
    static const uint32_t other[] = {0u, 1u, 50u, 85u, 89u, 91u, 95u, 100u, 117u};
    for (size_t i = 0u; i < sizeof other / sizeof other[0]; ++i) {
        DF_CHECK(t, !dfi_multiaccuracy_proven(other[i]));
    }
    DF_CHECK(t, dfi_multiaccuracy_proven(dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].accuracy));
    DF_CHECK(t, dfi_multiaccuracy_proven(dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].accuracy));
}

/* ---- the refusal: the recorded g33_triple_axel_stages with a Wide Lens in the hands of the first Pokemon of side 0 */
static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s, uint32_t lens_item)
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
            if (side == 0u && m == 0u && lens_item != 0u) {
                dst->item = lens_item;
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
static uint32_t play(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t lens_item, duoforge_status *status)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup, lens_item);
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

static void check_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g33_triple_axel_stages");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    /* as recorded: every step is played */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, 0u, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* Milotic (side 0, the Triple Axel user) with a Wide Lens: step 1 is Coil, step 2 the first Triple Axel that lands, refused
     * at its second hit */
    const uint32_t refused = play(t, ctx, cb, 1u + DFI_ITEM_WIDELENS, &st);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, refused, 2u);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g33");
    check_facts(&t);
    check_proven_accuracy(&t);
    check_refusal(&t);
    return df_test_end(&t);
}
