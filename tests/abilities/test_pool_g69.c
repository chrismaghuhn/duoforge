/*
 * duoforge.state.pool_g69 (white-box): step G69 of the content expansion, Symbiosis (decision 0015 5bm).
 *
 * Symbiosis (data/abilities.ts:4837-4856, onAllyAfterUseItem): when its ally uses up its item (a berry eaten, a Focus Sash or an
 * Eject Button, a Red Card used), the holder passes the item it holds to that ally, which has none. The pass changes item_now of
 * both members (the POOL tail, DFI_TAIL_ITEM_NONE for "holds nothing") and shows one line, `-activate|holder|ability: Symbiosis|
 * Item|[of] user`, an ACTIVATE event (src/combat/turn.c dfi_symbiosis). Its refusals change nothing:
 *
 *   - g69_symbiosis_sitrus: Milotic eats its Sitrus Berry at half HP and Floette-Eternal (Leftovers) passes it the Leftovers, after
 *     the heal of the berry (eatItem: Eat, then AfterUseItem). The pass happens once, in one step: before it the holder keeps its
 *     Leftovers (item_now 0, as the sheet says) and the user its Sitrus Berry; after it the holder holds nothing and the user the
 *     Leftovers (item_now 9 = item 8 + 1). Nothing is passed back.
 *   - g69_symbiosis_eject: Milotic is hit and uses its Eject Button. Eject Button sets the user's switchFlag before its useItem
 *     (items.ts:1692-1694), so the pin returns at once: the Leftovers stay with the holder in every step (item_now 0).
 *   - g69_symbiosis_stone: Lucario eats its Sitrus Berry, and the holder Floette-Eternal holds the Lucarionite, the stone of
 *     Lucario's own species: the item's TakeItem refuses it for the user (a stone of the recipient's species, the same check as
 *     Trick's, dfi_stone_refused_for). The holder keeps the stone in every step (item_now 0), with no line.
 *
 * Not replayed here: a Sticky Hold holder (none can exist: a Symbiosis holder has Symbiosis as its only ability, so the holder's
 * own TakeItem meets no Sticky Hold), and a White Herb or a terrain seed that starts on receipt (refused, E_UNSUPPORTED: the
 * reference would pass, so no conformance battle can show it; the code is in dfi_symbiosis). Bug Bite never runs AfterUseItem
 * (data/moves.ts:1920-1930), so a stolen berry eaten by the Bug Bite user passes nothing.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The item_now of a roster member: 0 as its sheet says, DFI_TAIL_ITEM_NONE for nothing, else the item id + 1. */
#define G69_LEFTOVERS_NOW ((uint32_t)DFI_ITEM_LEFTOVERS + 1u)

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
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed: 2 bits */
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

/* The steps [from, to) of the recorded battle `cb` on `b`, each one as recorded (the tape consumed exactly). */
static bool advance(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, duoforge_battle *b, uint32_t from, uint32_t to)
{
    for (uint32_t si = from; si < to; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", cb->name, si, duoforge_status_name(status));
            return false;
        }
    }
    return true;
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
    if (!advance(t, ctx, cb, b, 0u, steps)) {
        duoforge_battle_destroy(b);
        return NULL;
    }
    return b;
}

/* Symbiosis's pass, step by step: side 0 roster 0 is the holder (Floette-Eternal, Leftovers), roster 1 the user (Milotic, Sitrus
 * Berry). The holder's item_now is 0 until the step of the pass, then DFI_TAIL_ITEM_NONE for every later step; the user's is 0 (its
 * sheet's Sitrus Berry, used up) and becomes the Leftovers exactly at the same step. The pass happens once. */
static void check_sitrus(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g69_symbiosis_sitrus");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    uint32_t pass_step = 0u;
    uint32_t passes = 0u;
    for (uint32_t k = 1u; k <= cb->step_count; ++k) {
        duoforge_battle *b = replay(t, ctx, "g69_symbiosis_sitrus", k);
        if (b == NULL) {
            return;
        }
        const uint8_t holder = b->tail.sides[0].item_now[0];
        const uint8_t user = b->tail.sides[0].item_now[1];
        if (holder == DFI_TAIL_ITEM_NONE) {
            if (passes == 0u) {
                pass_step = k;
            }
            passes += 1u;
            DF_CHECK_EQ_U64(t, user, G69_LEFTOVERS_NOW);
        } else {
            DF_CHECK_EQ_U64(t, holder, 0u); /* the sheet's Leftovers */
            DF_CHECK(t, passes == 0u);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(t, passes == 1u ? 1u : 0u, 1u);
    DF_CHECK(t, pass_step > 0u);
}

/* No pass in the other two battles: the holder keeps its item in every step, and the user's item_now never reaches a stone or the
 * Leftovers through the holder. */
static void check_no_pass(df_test *t, const duoforge_context *ctx, const char *name)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    for (uint32_t k = 1u; k <= cb->step_count; ++k) {
        duoforge_battle *b = replay(t, ctx, name, k);
        if (b == NULL) {
            return;
        }
        DF_CHECK_EQ_U64(t, b->tail.sides[0].item_now[0], 0u);
        duoforge_battle_destroy(b);
    }
}

/* The refusal of a terrain seed that starts on its user (dfi_symbiosis, decision 0015 5bm): the Sitrus battle with the holder
 * Floette-Eternal holding a Psychic Seed, and Psychic Terrain up at the step of the pass (set at the boundary before it: nothing
 * before the pass uses the terrain). The step returns E_UNSUPPORTED, and the battle the caller holds is byte-for-byte the battle
 * before the step: the step ran on a working copy (src/state/request.c), so no state change is visible. */
static void check_seed_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g69_symbiosis_sitrus");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    uint32_t pass_k = 0u;
    for (uint32_t k = 1u; k <= cb->step_count && pass_k == 0u; ++k) {
        duoforge_battle *b = replay(t, ctx, "g69_symbiosis_sitrus", k);
        if (b == NULL) {
            return;
        }
        if (b->tail.sides[0].item_now[0] == DFI_TAIL_ITEM_NONE) {
            pass_k = k;
        }
        duoforge_battle_destroy(b);
    }
    if (!DF_CHECK(t, pass_k > 0u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    setup.sides[0].members[0].item = (uint8_t)(DFI_ITEM_PSYCHICSEED + 1u); /* the holder's sheet item, id + 1 as the conformance tables */
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    if (advance(t, ctx, cb, b, 0u, pass_k - 1u)) {
        b->terrain = DFI_TERRAIN_PSYCHIC;
        b->terrain_turns = DFI_FIELD_TURNS_MAX;
        duoforge_battle snapshot = *b;
        const df_conf_step *st = &cb->steps[pass_k - 1u];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        DF_CHECK_EQ_U64(t, (uint64_t)status, (uint64_t)DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, memcmp(&snapshot, b, sizeof snapshot) == 0);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g69");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_sitrus(&t, ctx);
        check_no_pass(&t, ctx, "g69_symbiosis_eject");
        check_no_pass(&t, ctx, "g69_symbiosis_stone");
        check_seed_refusal(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
