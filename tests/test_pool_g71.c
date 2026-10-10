/*
 * duoforge.state.pool_g71 (white-box): step G71 of the content expansion (decision 0034, decision 0015 5bn), the state and the
 * public side of Attract. The volatile's draws (Cute Charm's 3/10 and Attract's 1/2) wait for their draw sites (G73 owns site 23),
 * so this file tests the parts that need no draw: the constants, the Attract source bytes of the rev 5 reserve (1341 + flat), the
 * state check that refuses every invalid source, the public bit (POSITION_EXT_ATTRACT, for both players, no source), the refusal of
 * a from-view world with an infatuated occupant (E_UNSUPPORTED, lead's option B) and the clear of the holder's byte.
 *
 * The battle is the recorded g65_water_bubble (Araquanid M on side 0 flat 0, Milotic F on flat 1; Incineroar M on side 1 flat 2,
 * Skeledirge F on flat 3; the benched Sneasler M is side 1 member 3). A source byte is 1 + side * 6 + roster index.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/identity.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define G71_ARA 0u /* flat 0: side 0, Araquanid (M) */
#define G71_MIL 1u /* flat 1: side 0, Milotic (F) */
#define G71_INC 2u /* flat 2: side 1, Incineroar (M) */
#define G71_SKE 3u /* flat 3: side 1, Skeledirge (F) */

/* The source code of side s, roster index m: 1 + side * 6 + m (the byte of battle_internal.h). */
static uint8_t code_of(uint32_t side, uint32_t m)
{
    return (uint8_t)(1u + side * DUOFORGE_MAX_ROSTER + m);
}

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

/* A fresh battle of the same setup (an empty destination for decode and for a from-view world). */
static duoforge_battle *make_battle(const duoforge_context *ctx)
{
    const df_conf_battle *cb = find_conf("g65_water_bubble");
    duoforge_battle_setup s;
    setup_from(cb, &s);
    return df_make_battle(ctx, &s);
}

/* The recorded battle `name` after its team preview: the context, the battle, and the first move request. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b)
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
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    team_bundle(&bd, *b);
    return duoforge_battle_step(*ctx, *b, &bd, &res) == DUOFORGE_OK;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* The row's constants and the byte layout: 4 bytes of the rev 5 reserve, at the absolute offset 1341 (the state is 1357 bytes). */
static void test_constants(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_ATTRACT, 0x08000000u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VOLATILE_ATTRACT, 11u);
    DF_CHECK_EQ_U64(t, DUOFORGE_CAUSE_ATTRACT, 36u);
    DF_CHECK_EQ_U64(t, DFI_ATTRACT_SLOTS, 4u);
    DF_CHECK_EQ_U64(t, DFI_ATTRACT_MEMBER_MAX, 12u);
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE + DFI_ENC_TAIL5_ATTRACT_OFF, 1341u);
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL5_ATTRACT_SIZE, 4u);
    DF_CHECK_EQ_U64(t, DFI_STATE_POOL_ENCODED_SIZE, 1357u);
    /* the two draw sites of Cute Charm and Attract (lead's Q5; G73 owns 23) */
    DF_CHECK_EQ_U64(t, DFI_SITE_MOODY, 23u);
    DF_CHECK_EQ_U64(t, DFI_SITE_CUTE_CHARM, 24u);
    DF_CHECK_EQ_U64(t, DFI_SITE_ATTRACT, 25u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 26u);
}

/* The source bytes are written to the reserve and read back, and the bytes after them stay zero. */
static void test_encode_roundtrip(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u); /* Araquanid (M) infatuated by Skeledirge (F) */
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    uint8_t buf[DFI_STATE_POOL_ENCODED_SIZE];
    size_t written = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_encode(ctx, b, buf, sizeof buf, &written), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, written, (size_t)DFI_STATE_POOL_ENCODED_SIZE);
    DF_CHECK_EQ_U64(t, buf[1341u], code_of(1u, 1u));
    DF_CHECK_EQ_U64(t, buf[1342u], 0u);
    DF_CHECK_EQ_U64(t, buf[1343u], 0u);
    DF_CHECK_EQ_U64(t, buf[1344u], 0u);
    for (uint32_t i = 1345u; i < 1357u; ++i) {
        DF_CHECK_EQ_U64(t, buf[i], 0u);
    }
    duoforge_battle *dst = make_battle(ctx);
    if (dst != NULL) {
        DF_CHECK_EQ_U64(t, duoforge_battle_decode(ctx, dst, buf, sizeof buf), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, dst->tail.attract_source[G71_ARA], code_of(1u, 1u));
        DF_CHECK_EQ_U64(t, dst->tail.attract_source[G71_MIL], 0u);
        duoforge_battle_destroy(dst);
    }
    b->tail.attract_source[G71_ARA] = 0u;
    finish(ctx, b);
}

/* The state check: the valid source is accepted, and each invalid one is refused (E_INVARIANT, the battle is not changed). */
static void test_check_refusals(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    /* Control: Araquanid (M, side 0 member 0) is infatuated by Skeledirge (F, side 1 member 1, active on flat 3). */
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    b->tail.attract_source[G71_ARA] = 0u;

    /* A bad member index: 13 names no member (the codes are 1..12). */
    b->tail.attract_source[G71_ARA] = 13u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    /* The source is the holder itself: side 0 member 0 is Araquanid. */
    b->tail.attract_source[G71_ARA] = code_of(0u, 0u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    /* A source not active: Sneasler (M, side 1 member 3) is on the bench; Milotic (F) is on flat 1. */
    b->tail.attract_source[G71_MIL] = code_of(1u, 3u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.attract_source[G71_MIL] = 0u;
    /* A source that fainted: Skeledirge's HP is zero (it is still on flat 3). */
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    b->sides[1].members[1].hp = 0u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->sides[1].members[1].hp = b->sides[1].members[1].hp_max;
    /* The same gender: Incineroar (M, side 1 member 0) is not the opposite of Araquanid (M). */
    b->tail.attract_source[G71_ARA] = code_of(1u, 0u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    /* A nonzero byte on an empty position: flat 0 has no occupant. */
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    const uint8_t occ = b->sides[0].positions[0].occupant;
    b->sides[0].positions[0].occupant = DFI_OCCUPANT_NONE;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->sides[0].positions[0].occupant = occ;
    /* A fainted infatuated holder: Araquanid's HP is zero. */
    b->sides[0].members[0].hp = 0u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->sides[0].members[0].hp = b->sides[0].members[0].hp_max;

    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    b->tail.attract_source[G71_ARA] = 0u;
    finish(ctx, b);
}

/* The public bit: set on the infatuated occupant for both players (the foe too), with no source; no other bit or position. */
static void test_view_bit(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        duoforge_observation_ext ob;
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, &ob), DUOFORGE_OK);
        DF_CHECK(t, (ob.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ATTRACT) != 0u);
        DF_CHECK(t, (ob.sides[0].positions[1].volatiles & DUOFORGE_POSITION_EXT_ATTRACT) == 0u);
        DF_CHECK(t, (ob.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_ATTRACT) == 0u);
        DF_CHECK(t, (ob.sides[1].positions[1].volatiles & DUOFORGE_POSITION_EXT_ATTRACT) == 0u);
    }
    b->tail.attract_source[G71_ARA] = 0u;
    finish(ctx, b);
}

/* A world from a public state with an infatuated occupant is refused (E_UNSUPPORTED): the source is in the reserve and no
 * hypothesis carries it (lead's option B). Its control, the same state without the byte, is accepted. */
static void test_from_view_refused(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    duoforge_public_state view;
    duoforge_hypothesis hyp;
    duoforge_battle *world = make_battle(ctx);
    DF_CHECK(t, world != NULL);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &view), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_hypothesis(ctx, b, 0u, &hyp), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &view, &hyp, world), DUOFORGE_OK);

    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &view), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &view, &hyp, world), DUOFORGE_E_UNSUPPORTED);
    b->tail.attract_source[G71_ARA] = 0u;
    if (world != NULL) {
        duoforge_battle_destroy(world);
    }
    finish(ctx, b);
}

/* The holder's byte ends with the holder: dfi_tail_clear_occupant (a switch-out or a faint) clears it. */
static void test_clear_on_leave(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->tail.attract_source[G71_ARA] = code_of(1u, 1u);
    b->tail.attract_source[G71_INC] = code_of(0u, 1u);
    dfi_tail_clear_occupant(b, G71_ARA);
    DF_CHECK_EQ_U64(t, b->tail.attract_source[G71_ARA], 0u);
    DF_CHECK_EQ_U64(t, b->tail.attract_source[G71_INC], code_of(0u, 1u)); /* the other holder keeps its byte */
    b->tail.attract_source[G71_INC] = 0u;
    finish(ctx, b);
}

/* One byte set and checked: the state must be refused (refused_at) or accepted (accepted_at); the byte is restored. */
static void refused_at(df_test *t, const duoforge_context *ctx, duoforge_battle *b, uint32_t flat, uint8_t code)
{
    const uint8_t saved = b->tail.attract_source[flat];
    b->tail.attract_source[flat] = code;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.attract_source[flat] = saved;
}

static void accepted_at(df_test *t, const duoforge_context *ctx, duoforge_battle *b, uint32_t flat, uint8_t code)
{
    const uint8_t saved = b->tail.attract_source[flat];
    b->tail.attract_source[flat] = code;
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    b->tail.attract_source[flat] = saved;
}

/* One named test per rule of dfi_attract_byte_ok (src/state/invariants.c), on the recorded g65_water_bubble battle: Araquanid (M,
 * side 0 member 0, flat 0) and Milotic (F, side 0 member 1, flat 1) on side 0; Incineroar (M, side 1 member 0, flat 2) and
 * Skeledirge (F, side 1 member 1, flat 3) on side 1; Gholdengo (genderless) and Sneasler (M) are on the bench (members 2, 3 of
 * side 0 and of side 1: Sneasler is side 1 member 3). A code is 1 + side * 6 + roster index. */
static void test_rule_zero_is_none(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    for (uint32_t f = 0u; f < DFI_ATTRACT_SLOTS; ++f) {
        DF_CHECK_EQ_U64(t, b->tail.attract_source[f], 0u);
    }
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    finish(ctx, b);
}

static void test_rule_bad_index(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    refused_at(t, ctx, b, G71_ARA, 13u);  /* 13 > 12: no member */
    refused_at(t, ctx, b, G71_ARA, 255u);
    accepted_at(t, ctx, b, G71_ARA, code_of(1u, 1u)); /* control */
    finish(ctx, b);
}

static void test_rule_holder_standing(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->sides[0].members[0].hp = 0u; /* the holder fainted: no infatuation on a fainted occupant */
    refused_at(t, ctx, b, G71_ARA, code_of(1u, 1u));
    b->sides[0].members[0].hp = b->sides[0].members[0].hp_max;
    finish(ctx, b);
}

static void test_rule_empty_position(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    const uint8_t occ = b->sides[0].positions[0].occupant;
    b->sides[0].positions[0].occupant = DFI_OCCUPANT_NONE; /* a byte on an empty position */
    refused_at(t, ctx, b, G71_ARA, code_of(1u, 1u));
    b->sides[0].positions[0].occupant = occ;
    finish(ctx, b);
}

static void test_rule_roster_bound(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    /* Side 1 has 3 members only: roster index 3 (Sneasler) is not one of them. The other invariants may refuse too; the
     * refusal is asserted, and the check of the byte alone is in the sweep of test_pool_tail. */
    const uint8_t count = b->sides[1].member_count;
    b->sides[1].member_count = 3u;
    refused_at(t, ctx, b, G71_MIL, code_of(1u, 3u));
    b->sides[1].member_count = count;
    finish(ctx, b);
}

static void test_rule_not_holder(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    refused_at(t, ctx, b, G71_ARA, code_of(0u, 0u)); /* Araquanid infatuated by Araquanid */
    finish(ctx, b);
}

static void test_rule_source_active(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    refused_at(t, ctx, b, G71_MIL, code_of(1u, 3u)); /* Sneasler (M) is on the bench: not active */
    accepted_at(t, ctx, b, G71_MIL, code_of(1u, 0u)); /* control: Incineroar (M) is active on flat 2 */
    finish(ctx, b);
}

static void test_rule_source_alive(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    const uint16_t hp = b->sides[1].members[1].hp;
    b->sides[1].members[1].hp = 0u; /* Skeledirge fainted while still on flat 3 */
    refused_at(t, ctx, b, G71_ARA, code_of(1u, 1u));
    b->sides[1].members[1].hp = hp;
    finish(ctx, b);
}

static void test_rule_gender_pair(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    refused_at(t, ctx, b, G71_ARA, code_of(1u, 0u)); /* male with male: Incineroar (M) on Araquanid (M) */
    const uint8_t g = b->sides[1].members[1].gender;
    b->sides[1].members[1].gender = DFI_GENDER_NONE; /* genderless: no pair with a male */
    refused_at(t, ctx, b, G71_ARA, code_of(1u, 1u));
    b->sides[1].members[1].gender = g;
    accepted_at(t, ctx, b, G71_ARA, code_of(1u, 1u)); /* control: female with male */
    finish(ctx, b);
}

static void test_rule_ally_source(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    /* The rules name no side for the source: an ally (Milotic, F, side 0 member 1, active) infatuates Araquanid (M). */
    accepted_at(t, ctx, b, G71_ARA, code_of(0u, 1u));
    finish(ctx, b);
}

/* The codes the state accepts on flat 0 (Araquanid, M): exactly Milotic (ally, code 2) and Skeledirge (foe, code 8). */
static void test_accepted_codes_flat0(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    uint32_t ok_codes = 0u;
    for (uint32_t code = 1u; code <= DFI_ATTRACT_MEMBER_MAX; ++code) {
        b->tail.attract_source[G71_ARA] = (uint8_t)code;
        if (duoforge_battle_check(ctx, b) == DUOFORGE_OK) {
            ok_codes |= 1u << code;
        }
    }
    b->tail.attract_source[G71_ARA] = 0u;
    DF_CHECK_EQ_U64(t, ok_codes, (1u << 2u) | (1u << 8u));
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g71");
    test_rule_zero_is_none(&t);
    test_rule_bad_index(&t);
    test_rule_holder_standing(&t);
    test_rule_empty_position(&t);
    test_rule_roster_bound(&t);
    test_rule_not_holder(&t);
    test_rule_source_active(&t);
    test_rule_source_alive(&t);
    test_rule_gender_pair(&t);
    test_rule_ally_source(&t);
    test_accepted_codes_flat0(&t);
    test_constants(&t);
    test_encode_roundtrip(&t);
    test_check_refusals(&t);
    test_view_bit(&t);
    test_from_view_refused(&t);
    test_clear_on_leave(&t);
    return df_test_end(&t);
}
