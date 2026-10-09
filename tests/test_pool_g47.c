/*
 * duoforge.state.pool_g47 (white-box): step G47 of the content expansion, the status and volatile cures: Synchronize and Oblivious
 * (abilities) and Lum Berry and Mental Herb (items). No public value, no new state, no new draw site.
 *
 *   - Synchronize (data/abilities.ts:4857-4871): a psn, tox, brn or par that another Pokemon gave the holder is passed back to that
 *     Pokemon by its trySetStatus (src/combat/turn.c dfi_synchronize, through dfi_try_status with the SYNC origin). The recorded
 *     battles g47_synchronize_* show the pass-back in each source: a Pokemon of the same status (-fail), a poison-immune Arbok, an
 *     Electric Raichu and a Fire Volcarona (-immune), a Gardevoir that answers (-fail), the Lum Berry after it (priority -1), a
 *     contact Flame Body and a contact Poison Touch.
 *   - Oblivious (data/abilities.ts:3008-3040): Taunt is -immune to its holder, and Intimidate's Attack drop fails (g47_oblivious).
 *   - Lum Berry (data/items.ts:3537-3560): the berry is eaten at a status (onAfterSetStatus) and cures it at once (g47_lum_berry);
 *     a foe's Unnerve refuses the eating (g47_lum_unnerve).
 *   - Mental Herb (data/items.ts:3889-3926): its holder's taunt, encore, disable or heal block is cured in the Update that follows
 *     (g47_herb_taunt, g47_herb_encore, g47_herb_disable, g47_herb_heal_block); a holder keeps its queued move under an Encore
 *     (g47_herb_encore).
 *
 * The recorded battles replay step by step through the conformance runner (tests/test_conformance.c) against the protocol; this test
 * checks the state that each rule leaves (the statuses, the herb or berry consumed, the volatile removed) and the marks: the four
 * rows are marked and handled by id, and what would make a rule reach another path is not marked (Mold Breaker, the other breakers;
 * Harvest, Cheek Pouch, Gluttony and Ripen, which eat or restore berries; Attract and Torment, whose volatiles the engine does not
 * have, so Mental Herb's and Oblivious's halves for them are not modelled). Trace copies of Oblivious onto a taunted Pokemon are
 * refused by dfi_trace (E_UNSUPPORTED): the entry copy never meets a taunt, so no battle reaches it.
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
#include "state/closure_member.h"
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

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step and the leads' entries). */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
    if (created != DUOFORGE_OK) {
        fprintf(stderr, "  %s create: %s\n", name, duoforge_status_name(created));
    }
    if (!DF_CHECK(t, created == DUOFORGE_OK && b != NULL)) {
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

/* The member standing at flat position `flat` (side = flat / 2, slot = flat % 2). */
static const dfi_member *standing(const duoforge_battle *b, uint32_t flat)
{
    const dfi_side *s = &b->sides[flat / 2u];
    return &s->members[s->positions[flat % 2u].occupant];
}

static const dfi_tail_pos *tail_of(const duoforge_battle *b, uint32_t flat)
{
    return &b->tail.sides[flat / 2u].positions[flat % 2u];
}

/* The state after `steps` steps: the Pokemon at `flat` has `status`, and its item is (or is not) consumed. */
static void expect_status(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, uint32_t flat, uint32_t status)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    if (standing(b, flat)->status != status) {
        fprintf(stderr, "  %s after %u steps, position %u: status %u, expected %u\n", name, steps, flat,
                (unsigned)standing(b, flat)->status, (unsigned)status);
    }
    DF_CHECK_EQ_U64(t, standing(b, flat)->status, status);
    duoforge_battle_destroy(b);
}

static void expect_item(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, uint32_t flat, bool consumed)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, standing(b, flat)->item_consumed, consumed ? 1u : 0u);
    duoforge_battle_destroy(b);
}

/* The state after `steps` steps: the volatile of Taunt, Encore, Disable or Heal Block is gone at `flat` (zero counters). */
static void expect_volatiles_gone(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, uint32_t flat)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return;
    }
    const dfi_tail_pos *p = tail_of(b, flat);
    DF_CHECK_EQ_U64(t, p->taunt_turns, 0u);
    DF_CHECK_EQ_U64(t, p->encore_slot, 0u);
    DF_CHECK_EQ_U64(t, p->disable_slot, 0u);
    DF_CHECK_EQ_U64(t, p->heal_block_turns, 0u);
    duoforge_battle_destroy(b);
}

static void check_synchronize(df_test *t, const duoforge_context *ctx)
{
    /* p1a is the Umbreon (Synchronize) and p2a the source in all of these; flat 0 is p1a, flat 2 is p2a. */
    expect_status(t, ctx, "g47_synchronize_tox", 2u, 0u, DFI_STATUS_TOX);
    expect_status(t, ctx, "g47_synchronize_tox", 2u, 2u, DFI_STATUS_TOX);          /* the Houndoom, passed back */
    expect_status(t, ctx, "g47_synchronize_immune_poison", 2u, 2u, DFI_STATUS_NONE); /* the Poison type Arbok is immune */
    expect_status(t, ctx, "g47_synchronize_immune_poison", 2u, 0u, DFI_STATUS_TOX);
    expect_status(t, ctx, "g47_synchronize_immune_electric", 2u, 2u, DFI_STATUS_NONE); /* the Electric type Raichu is immune */
    expect_status(t, ctx, "g47_synchronize_immune_electric", 2u, 0u, DFI_STATUS_PAR);
    expect_status(t, ctx, "g47_synchronize_par_stun", 2u, 2u, DFI_STATUS_PAR);     /* the Whimsicott is paralysed, passed back */
    expect_status(t, ctx, "g47_synchronize_both", 2u, 0u, DFI_STATUS_TOX);
    expect_status(t, ctx, "g47_synchronize_both", 2u, 2u, DFI_STATUS_TOX);         /* the Gardevoir, which answers with -fail */
    expect_status(t, ctx, "g47_synchronize_fail_status", 3u, 2u, DFI_STATUS_TOX);  /* the Houndoom stays poisoned */
    expect_status(t, ctx, "g47_synchronize_flame_body", 2u, 0u, DFI_STATUS_BRN);   /* Flame Body burns the Umbreon */
    expect_status(t, ctx, "g47_synchronize_flame_body", 2u, 2u, DFI_STATUS_NONE);  /* the Fire type Volcarona is immune */
    /* the Lum Berry of the holder cures it after the pass-back (the source keeps the poison) */
    expect_status(t, ctx, "g47_synchronize_lum", 2u, 0u, DFI_STATUS_NONE);
    expect_item(t, ctx, "g47_synchronize_lum", 2u, 0u, true);
    expect_status(t, ctx, "g47_synchronize_lum", 2u, 2u, DFI_STATUS_TOX);
}

static void check_oblivious_and_lum(df_test *t, const duoforge_context *ctx)
{
    /* the Oblivious Slowbro is never taunted: its counters stay zero */
    expect_volatiles_gone(t, ctx, "g47_oblivious", 2u, 2u);
    /* the berry of Umbreon cures its burn at once (turn 1); with no berry left, its poison (turn 2) stays */
    expect_status(t, ctx, "g47_lum_berry", 2u, 0u, DFI_STATUS_NONE);
    expect_item(t, ctx, "g47_lum_berry", 2u, 0u, true);
    expect_status(t, ctx, "g47_lum_berry", 3u, 0u, DFI_STATUS_TOX);
    expect_item(t, ctx, "g47_lum_berry", 3u, 0u, true);
    /* under a foe's Unnerve the berry is not eaten and the burn stays */
    /* the confusion of Hurricane (a marked move's 30 percent secondary): the berry is eaten at the Update and the confusion ends
     * with it (onEat removes it); the eaten berry is consumed and the confusion counter is zero */
    {
        duoforge_battle *b = replay(t, ctx, "g47_lum_confusion", 3u);
        if (b != NULL) {
            DF_CHECK_EQ_U64(t, standing(b, 2u)->item_consumed, 1u);
            DF_CHECK_EQ_U64(t, b->sides[1].positions[0].confusion_turns, 0u);
            duoforge_battle_destroy(b);
        }
    }
    expect_status(t, ctx, "g47_lum_unnerve", 3u, 2u, DFI_STATUS_BRN);
    expect_item(t, ctx, "g47_lum_unnerve", 3u, 2u, false);
}

static void check_herb(df_test *t, const duoforge_context *ctx)
{
    /* the Taunt of Gyarados is cured by the herb of Umbreon in the Update after it */
    expect_volatiles_gone(t, ctx, "g47_herb_taunt", 2u, 2u);
    expect_item(t, ctx, "g47_herb_taunt", 2u, 2u, true);
    /* the Encore with the herb: the lock is cured, the herb is used */
    expect_volatiles_gone(t, ctx, "g47_herb_encore", 3u, 2u);
    expect_item(t, ctx, "g47_herb_encore", 3u, 2u, true);
    /* the Disable with the herb */
    expect_volatiles_gone(t, ctx, "g47_herb_disable", 3u, 2u);
    expect_item(t, ctx, "g47_herb_disable", 3u, 2u, true);
    /* the Heal Block of Psychic Noise with the herb of Politoed */
    expect_volatiles_gone(t, ctx, "g47_herb_heal_block", 2u, 2u);
    expect_item(t, ctx, "g47_herb_heal_block", 2u, 2u, true);
}

/* What is marked is what the rules read: the four rows by id, with no handler of their own (the turn code has them), and nothing
 * that reaches another path (the breakers, the berry-eating and berry-restoring abilities, Attract and Torment). */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SYNCHRONIZE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_SYNCHRONIZE], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_OBLIVIOUS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_OBLIVIOUS], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LUMBERRY] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LUMBERRY], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_MENTALHERB] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_MENTALHERB], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_HARVEST] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CHEEKPOUCH] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_GLUTTONY] == 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RIPEN] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_ATTRACT] == 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_TORMENT] == 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g47");
    check_marks(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_synchronize(&t, ctx);
    check_oblivious_and_lum(&t, ctx);
    check_herb(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
