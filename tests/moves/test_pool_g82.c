/*
 * duoforge.state.pool_g82 (white-box): Healing Wish (decision 0045, step G82). Position bit 0 is the slot's wish: the occupant's
 * clear (a switch-out, a replacement's entry) keeps it and ends the other bits with the occupant; the heal of the entrant is a HEAL
 * event with cause MOVE and the move id, which the foe sees as a percentage like every heal (decision 0007); the view bit and its
 * feature are the manifest's and the public values of the header (0x00400000, feature 43, a lane's feature above the tiers: the
 * tier count stays 43, as the batch 8 integration kept it, 4884b077).
 *
 * The recorded battles g82_r1_normal_heal and g82_r2_full_hp_kept (conformance_pool.h) are replayed here step by step, each step
 * with its recorded commands and the reference's draws as the tape: after the Healing Wish user faints, the view of both viewers
 * shows DUOFORGE_POSITION_EXT_HEALING_WISH at that slot (public); after a heal on entry it is gone (R1); with a full-HP entrant it
 * stays set (R2); and battle_from_view rebuilds the tail bit 0 from the view (the round trip). Flat positions: side 0 slots 0 and 1
 * (flat 0, 1), side 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/events.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "state/knowledge.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The heal of an entrant (side 0, full HP): the owner's copy is exact and unchanged, the foe's is a percentage. */
static void test_heal_projection(df_test *t)
{
    duoforge_event in;
    memset(&in, 0, sizeof in);
    in.kind = DUOFORGE_EVENT_HEAL;
    in.position = 0u; /* side 0: viewer 0 owns it, viewer 1 (the foe) sees the percentage */
    in.id = 0u;
    in.hp = 170u;
    in.hp_max = 170u;
    in.hp_kind = DUOFORGE_HP_EXACT;
    in.cause = DUOFORGE_CAUSE_MOVE;
    in.id2 = DFI_MOVE_HEALINGWISH;

    duoforge_event own;
    dfi_event_project(&in, 0u, &own);
    DF_CHECK(t, memcmp(&own, &in, sizeof own) == 0);

    uint8_t percent = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(170u, 170u, &percent, &flag);
    duoforge_event foe;
    dfi_event_project(&in, 1u, &foe);
    DF_CHECK_EQ_U64(t, foe.hp_kind, DUOFORGE_HP_PERCENT);
    DF_CHECK_EQ_U64(t, foe.hp_max, 100u);
    DF_CHECK_EQ_U64(t, foe.hp, percent);
    DF_CHECK_EQ_U64(t, foe.cause, DUOFORGE_CAUSE_MOVE);
    DF_CHECK_EQ_U64(t, foe.id2, DFI_MOVE_HEALINGWISH);
}

/* Bit 0 is the slot's: the occupant's clear keeps it (a switch-out or the replacement's entry, identity.c), and the other bits
 * (the raised flag, bit 1) end with the occupant as before. */
static void test_wish_kept_by_occupant_clear(df_test *t)
{
    static duoforge_battle b;
    memset(&b, 0, sizeof b);
    dfi_tail_pos *p = &b.tail.sides[0].positions[1];
    p->position_flags = (uint8_t)(DFI_POSFLAG_HEALING_WISH | DFI_POSFLAG_STATS_RAISED);
    b.sides[0].positions[1].occupant = 0u;
    dfi_tail_clear_occupant(&b, 1u);
    DF_CHECK_EQ_U64(t, p->position_flags, DFI_POSFLAG_HEALING_WISH);
    /* the replacement's entry clears the position again: the wish still waits */
    dfi_tail_clear_occupant(&b, 1u);
    DF_CHECK_EQ_U64(t, p->position_flags, DFI_POSFLAG_HEALING_WISH);
    /* a position without the wish ends with its occupant as before */
    b.tail.sides[0].positions[0].position_flags = DFI_POSFLAG_STATS_RAISED;
    dfi_tail_clear_occupant(&b, 0u);
    DF_CHECK_EQ_U64(t, b.tail.sides[0].positions[0].position_flags, 0u);
}

/* The public values: the view bit 0x00400000 (decision 0045), the feature 43 in the manifest. Feature 43 is the first of the
 * content expansion's lane features (43 to 58, decision 0050), above the tiers 0 to COUNT - 1 (COUNT 43, encoder 5's TRANSFORM
 * is the last tier) and below the reserve families (59 to 63): encoder 6 shows it through RESERVE_OWN, encoder 5 has no column
 * for it. */
static void test_public_values(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_HEALING_WISH, 0x00400000u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH, 43u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_COUNT, 43u);
    DF_CHECK(t, DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH >= DUOFORGE_VIEWEXT_FEATURE_COUNT &&
                    DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH < DUOFORGE_VIEWEXT_FEATURE_RESERVE_VOLATILES);
    DF_CHECK(t, ((dfi_support.view_ext_features >> DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH) & 1u) == 1u);
}

/* ---- the recorded battles: their steps replayed with the reference's draws as the tape ---- */

/* The recorded steps of R1 and R2 (conformance_pool.h): 0 the team preview, 1 turn 1, 2 side 1's replacement (its KO in turn 1),
 * 3 turn 2 (Lopunny's Healing Wish at side 0 slot 1, the user faints), 4 side 0's replacement into that slot. */
#define G82_STEPS_TO_FAINT 4u
#define G82_STEP_ENTRY 4u

static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

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

/* The bundle of recorded step `st`: the sides it answered, with their picks or slot commands. */
static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0u; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
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
}

/* Steps [from, to) of the recorded battle on b, each with its recorded draws (every one consumed) and its recorded boundary. */
static bool replay(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const df_conf_battle *cb, uint32_t from,
                   uint32_t to)
{
    if (!DF_CHECK(t, to <= cb->step_count)) {
        return false;
    }
    for (uint32_t si = from; si < to; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len) || !DF_CHECK_EQ_U64(t, b->boundary_kind, st->boundary)) {
            fprintf(stderr, "  %s step %u\n", cb->name, si);
            return false;
        }
    }
    return true;
}

/* Starts the recorded battle `name` and replays it up to the faint of the Healing Wish user: a REPLACEMENT boundary that asks
 * side 0 alone (the recorded step G82_STEP_ENTRY answers side 0 only). */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, const df_conf_battle **cb)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    *cb = find_conf(name);
    DF_CHECK(t, *cb != NULL);
    if (*ctx == NULL || *cb == NULL || !DF_CHECK(t, (*cb)->step_count > G82_STEP_ENTRY)) {
        return false;
    }
    const df_conf_step *entry = &(*cb)->steps[G82_STEP_ENTRY];
    DF_CHECK(t, entry->answered0 == 1u && entry->answered1 == 0u && entry->team == 0u);
    duoforge_battle_setup s;
    setup_from(*cb, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL || !replay(t, *ctx, *b, *cb, 0u, G82_STEPS_TO_FAINT)) {
        return false;
    }
    return DF_CHECK_EQ_U64(t, (*b)->boundary_kind, DUOFORGE_BOUNDARY_REPLACEMENT);
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    if (b != NULL) {
        duoforge_battle_destroy(b);
    }
    if (ctx != NULL) {
        duoforge_context_destroy(ctx);
    }
}

/* The view bit of a side-0 position as both viewers see it (the bit is public: the wish is no hidden state). */
static void check_view_bit(df_test *t, duoforge_context *ctx, const duoforge_battle *b, uint32_t side, uint32_t slot, bool want)
{
    for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
        duoforge_observation_ext ob;
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, &ob), DUOFORGE_OK);
        const bool got = (ob.sides[side].positions[slot].volatiles & DUOFORGE_POSITION_EXT_HEALING_WISH) != 0u;
        DF_CHECK(t, got == want);
    }
}

/* The round trip (battle_from_view): the public state of viewer 0 at the faint, with viewer 0's true hypothesis
 * (duoforge_battle_hypothesis, the current revision), rebuilds the tail bit 0 of the wish slot in a fresh world of the same
 * setup, which starts without it. */
static void check_round_trip(df_test *t, duoforge_context *ctx, const duoforge_battle *b, const df_conf_battle *cb)
{
    duoforge_public_state pub;
    memset(&pub, 0, sizeof pub);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &pub), DUOFORGE_OK);
    duoforge_hypothesis hyp;
    memset(&hyp, 0, sizeof hyp);
    DF_CHECK_EQ_U64(t, duoforge_battle_hypothesis(ctx, b, 0u, &hyp), DUOFORGE_OK);
    duoforge_battle_setup s;
    setup_from(cb, &s);
    duoforge_battle *world = df_make_battle(ctx, &s);
    DF_CHECK(t, world != NULL);
    if (world == NULL) {
        return;
    }
    DF_CHECK(t, (world->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) == 0u);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &pub, &hyp, world), DUOFORGE_OK);
    DF_CHECK(t, (world->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    duoforge_battle_destroy(world);
}

/* R1: the entrant is hurt and paralysed: the heal on entry clears the bit (the wish is consumed), for both viewers. */
static void test_r1_view(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g82_r1_normal_heal", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    /* the Healing Wish user has fainted: the slot holds the wish, public to both viewers */
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    check_view_bit(t, ctx, b, 0u, 1u, true);
    check_round_trip(t, ctx, b, cb);
    DF_CHECK(t, replay(t, ctx, b, cb, G82_STEP_ENTRY, G82_STEP_ENTRY + 1u));
    /* the heal on entry: the bit is gone for both viewers */
    check_view_bit(t, ctx, b, 0u, 1u, false);
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) == 0u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

/* R2: the entrant is at full HP without a status: the wish waits, the bit stays set after the entry, for both viewers. */
static void test_r2_view(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    const df_conf_battle *cb = NULL;
    if (!start(t, "g82_r2_full_hp_kept", &ctx, &b, &cb)) {
        finish(ctx, b);
        return;
    }
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    check_view_bit(t, ctx, b, 0u, 1u, true);
    DF_CHECK(t, replay(t, ctx, b, cb, G82_STEP_ENTRY, G82_STEP_ENTRY + 1u));
    /* the full-HP entrant does not consume the wish: the bit stays set for both viewers */
    check_view_bit(t, ctx, b, 0u, 1u, true);
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    DF_CHECK(t, dfi_state_check(ctx, b, NULL) == DUOFORGE_OK);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g82");
    test_heal_projection(&t);
    test_wish_kept_by_occupant_clear(&t);
    test_public_values(&t);
    test_r1_view(&t);
    test_r2_view(&t);
    return df_test_end(&t);
}
