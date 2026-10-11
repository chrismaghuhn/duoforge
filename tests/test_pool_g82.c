/*
 * duoforge.state.pool_g82 (white-box): Healing Wish (decision 0045, step G82). Position bit 0 is the slot's wish: the occupant's
 * clear (a switch-out, a replacement's entry) keeps it and ends the other bits with the occupant; the heal of the entrant is a HEAL
 * event with cause MOVE and the move id, which the foe sees as a percentage like every heal (decision 0007); the view bit and its
 * feature are the manifest's and the public values of the header (0x00400000, feature 43, count 44).
 *
 * The recorded battles g82_r1_normal_heal and g82_r2_full_hp_kept (conformance_pool.h, the tapes of their specs) are replayed here
 * command by command: after the Healing Wish user faints, the view of both viewers shows DUOFORGE_POSITION_EXT_HEALING_WISH at that
 * slot (public); after a heal on entry it is gone (R1); with a full-HP entrant it stays set (R2); and battle_from_view rebuilds the
 * tail bit 0 from the view bit (the round trip). Flat positions: side 0 slots 0 and 1 (flat 0, 1), side 1 (flat 2, 3).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/events.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "state/knowledge.h"
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

/* The public values: the view bit 0x00400000 (decision 0045), the feature 43 in the manifest, and the feature count 44. */
static void test_public_values(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_HEALING_WISH, 0x00400000u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH, 43u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_COUNT, 44u);
    DF_CHECK(t, ((dfi_support.view_ext_features >> DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH) & 1u) == 1u);
}

/* ---- the recorded tapes: the battle of a spec, replayed command by command ---- */

typedef struct g82_cmd {
    uint8_t kind;      /* DUOFORGE_SLOT_MOVE, DUOFORGE_SLOT_SWITCH or DUOFORGE_SLOT_PASS */
    uint8_t move_slot; /* 0-based */
    uint8_t target;    /* flat position, DUOFORGE_TARGET_NONE for none */
    uint8_t reserve;   /* roster index, for a switch */
} g82_cmd;

#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define SW(reserve) {DUOFORGE_SLOT_SWITCH, 0u, DUOFORGE_TARGET_NONE, (reserve)}
#define PASS {DUOFORGE_SLOT_PASS, 0u, DUOFORGE_TARGET_NONE, 0u}
#define NO DUOFORGE_TARGET_NONE

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

/* The team preview: the first four of each paste (the leads are the first two), as the recorded battles pick them. */
static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* One turn: cmd[side][slot], both sides. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g82_cmd cmd[2][2])
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = cmd[side][slot].kind;
            c->slots[slot].move_slot = cmd[side][slot].move_slot;
            c->slots[slot].target = cmd[side][slot].target;
            c->slots[slot].reserve = cmd[side][slot].reserve;
        }
    }
}

/* A replacement answer of side 0 alone (the other side is not asked at this boundary). */
static void replacement_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g82_cmd side0[2])
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 1u;
    duoforge_side_choice *c = &bd->responses[0];
    c->epoch = b->request_epoch;
    c->side = 0u;
    c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    for (uint32_t slot = 0u; slot < 2u; ++slot) {
        c->slots[slot].kind = side0[slot].kind;
        c->slots[slot].move_slot = side0[slot].move_slot;
        c->slots[slot].target = side0[slot].target;
        c->slots[slot].reserve = side0[slot].reserve;
    }
}

/* Starts the recorded battle `name` (the team preview is answered). */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, duoforge_decision_bundle *bd,
                  duoforge_step_result *res)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (*ctx == NULL || cb == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    team_bundle(bd, *b);
    return duoforge_battle_step(*ctx, *b, bd, res) == DUOFORGE_OK;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
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
    (void)b;
}

/* The round trip (battle_from_view): the public state of viewer 0 at the faint rebuilds the tail bit 0 of the wish slot. The
 * hypothesis is the zero one: the hidden parts are not the point of this check, the wish bit is. */
static void check_round_trip(df_test *t, duoforge_context *ctx, const duoforge_battle *b, const char *name)
{
    duoforge_public_state pub;
    memset(&pub, 0, sizeof pub);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &pub), DUOFORGE_OK);
    duoforge_battle_setup s;
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (cb == NULL) {
        return;
    }
    setup_from(cb, &s);
    duoforge_battle *world = df_make_battle(ctx, &s);
    DF_CHECK(t, world != NULL);
    if (world == NULL) {
        return;
    }
    duoforge_hypothesis hyp;
    memset(&hyp, 0, sizeof hyp);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &pub, &hyp, world), DUOFORGE_OK);
    DF_CHECK(t, (world->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    duoforge_battle_destroy(world);
}

/* R1: the entrant is hurt and paralysed: the heal on entry clears the bit (the wish is consumed), for both viewers. */
static void test_r1_view(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g82_r1_normal_heal", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g82_cmd turn1[2][2] = {{MV(0, 3u), MV(1, NO)}, {MV(0, NO), MV(0, 0u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    static const g82_cmd turn2[2][2] = {{SW(2), MV(0, NO)}, {MV(0, NO), MV(0, 0u)}};
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the Healing Wish user has fainted: the slot holds the wish, public to both viewers */
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
    check_view_bit(t, ctx, b, 0u, 1u, true);
    check_round_trip(t, ctx, b, "g82_r1_normal_heal");
    static const g82_cmd repl[2] = {PASS, SW(0)};
    replacement_bundle(&bd, b, repl);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
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
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g82_r2_full_hp_kept", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const g82_cmd turn1[2][2] = {{MV(0, 3u), MV(1, NO)}, {MV(0, NO), MV(0, 1u)}};
    turn_bundle(&bd, b, turn1);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    static const g82_cmd turn2[2][2] = {{SW(2), MV(0, NO)}, {MV(0, NO), MV(0, 1u)}};
    turn_bundle(&bd, b, turn2);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    check_view_bit(t, ctx, b, 0u, 1u, true);
    static const g82_cmd repl[2] = {PASS, SW(0)};
    replacement_bundle(&bd, b, repl);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    /* the full-HP entrant does not consume the wish: the bit stays set for both viewers */
    check_view_bit(t, ctx, b, 0u, 1u, true);
    DF_CHECK(t, (b->tail.sides[0].positions[1].position_flags & DFI_POSFLAG_HEALING_WISH) != 0u);
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
