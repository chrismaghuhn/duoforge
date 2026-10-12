/*
 * duoforge.view.sleep_count (white-box): decision 0066 (visible sleep, #442). A sleeping POOL member publishes its cant count c
 * (the member byte +9 of the tail: the cant lines printed since the sleep started); the start S is 2 or 3 (sample([2, 3, 3]),
 * data/mods/champions/conditions.ts:23), the counter is S - c, and a rebuild draws S from the hypothesis word with the exact law.
 *
 * Checked here: the counter and the count of the engine over the attempts (S = 2: one cant, then the wake at the second attempt;
 * S = 3: two cants, then the wake at the third); the public view (the count shows, the counter stays hidden); the rebuild law over
 * a sweep of words (c = 2 leaves S = 3; c in {0, 1} takes S = 2 for the bucket of the word 0, the share 1/3); and the refusals
 * (a count above 2, a count without a sleep, revision 3, Early Bird, Sleep Talk among the moves).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define SLEEP_WORDS 3000u

/* The team selection of the four leads' picks 0 to 3: the battle at its first TURN boundary. */
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

/* One turn: the move of each side's two slots (move slot, target flat position). */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const uint8_t move[2][2], const uint8_t target[2][2])
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
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = move[side][slot];
            c->slots[slot].target = target[side][slot];
            c->slots[slot].reserve = 0u;
        }
    }
}

static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle_setup setup;
    df_setup_teams(&setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    DF_CHECK(t, b != NULL);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, b->boundary_kind == DUOFORGE_BOUNDARY_TURN);
    return b;
}

/* The byte offsets of a member's counter, its cant count, its ability and its move slots, in the encoded state. */
static size_t counter_at(uint32_t side, uint32_t m)
{
    return DFI_ENC_SIDE_OFF + side * DFI_ENC_SIDE_SIZE + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE +
           DFI_ENC_MEMBER_STATUS_COUNTER_OFF;
}

static size_t member_at_off(uint32_t side, uint32_t m)
{
    return DFI_ENC_SIDE_OFF + side * DFI_ENC_SIDE_SIZE + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
}

static size_t cant_at(uint32_t side, uint32_t m)
{
    return DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_SIDES_OFF + side * DFI_ENC_TAIL_SIDE_SIZE + DFI_ENC_TAIL_MEMBER_OFF +
           m * DFI_ENC_TAIL_MEMBER_SIZE + DFI_ENC_TAIL_MEMBER_SLEEP_CANT_OFF;
}

/* A sleeping member of `side` at roster index m with the start S and the count c (the counter S - c). */
static void put_sleep(duoforge_battle *b, uint32_t side, uint32_t m, uint32_t start, uint32_t cant)
{
    b->sides[side].members[m].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[side].members[m].status_counter = (uint8_t)(start - cant);
    b->tail.sides[side].sleep_cant[m] = (uint8_t)cant;
}

/* The rebuilt counter of the foe's lead for the word `word`, with its view v and hypothesis h (both of the same battle). */
static uint32_t rebuilt_counter(df_test *t, const duoforge_context *ctx, const duoforge_public_state *v,
                                duoforge_hypothesis *h, uint32_t side, uint32_t m, uint64_t word, duoforge_battle *w)
{
    h->sleep[side][m] = word;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, v, h, w), DUOFORGE_OK);
    return w->sides[side].members[m].status_counter;
}

/* The law of the rebuild (decision 0066, section 4): c = 2 gives S = 3; c in {0, 1} gives S = 2 for the bucket 0 of 3 (the word
 * below 2^64 / 3, probability 1/3) and S = 3 otherwise; the counter is S - c. */
static uint32_t expected_counter(uint32_t cant, uint64_t word)
{
    /* the bucket 0 of 3 is the words up to 2^64 / 3 (0x5555555555555555 is the last one): word * 3 < 2^64 */
    const bool bucket0 = word <= 0x5555555555555555ull;
    const uint32_t start = cant == 2u ? 3u : bucket0 ? 2u : 3u;
    return start - cant;
}

/* The engine: a sleeper's attempts print one cant each and wake at its start (S = 2: one cant; S = 3: two cants). The whole
 * battle is stepped; the sleeper is the foe's lead, which the own side does not touch (its moves target nobody). */
static void check_attempts(df_test *t, const duoforge_context *ctx, uint32_t start)
{
    duoforge_battle *b = turn_battle(t, ctx);
    const uint32_t lead = b->sides[1].positions[0].occupant;
    put_sleep(b, 1u, lead, start, 0u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    /* move slot 0 of each lead: the own leads (flat 0, 1) hit the foe's (flat 2, 3); the sleeper (flat 2) hits the own lead */
    static const uint8_t move[2][2] = {{0u, 0u}, {0u, 0u}};
    static const uint8_t target[2][2] = {{2u, 3u}, {0u, 1u}};
    uint32_t counter = start;
    uint32_t cant = 0u;
    for (uint32_t attempt = 1u; attempt <= start; ++attempt) {
        duoforge_decision_bundle bd;
        turn_bundle(&bd, b, move, target);
        duoforge_step_result res;
        DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
        if (attempt < start) {
            /* a cant: the counter goes down, the count goes up, the sleep goes on */
            ++cant;
            counter = start - cant;
            DF_CHECK(t, b->sides[1].members[lead].status == DUOFORGE_AILMENT_SLEEP);
            DF_CHECK_EQ_U64(t, b->sides[1].members[lead].status_counter, counter);
            DF_CHECK_EQ_U64(t, b->tail.sides[1].sleep_cant[lead], cant);
        } else {
            /* the wake at the start: the status and the count end */
            DF_CHECK(t, b->sides[1].members[lead].status == DUOFORGE_AILMENT_NONE);
            DF_CHECK_EQ_U64(t, b->tail.sides[1].sleep_cant[lead], 0u);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    }
    duoforge_battle_destroy(b);
}

/* The public view shows the count and hides the counter; the rebuild reproduces the engine's counter for the true word. */
static void check_law(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    duoforge_battle *w = turn_battle(t, ctx);
    const uint32_t lead = b->sides[1].positions[0].occupant;
    static const uint32_t cases[5][2] = {{2u, 0u}, {3u, 0u}, {2u, 1u}, {3u, 1u}, {3u, 2u}};
    for (uint32_t i = 0u; i < 5u; ++i) {
        const uint32_t start = cases[i][0], cant = cases[i][1];
        put_sleep(b, 1u, lead, start, cant);
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        duoforge_public_state v;
        memset(&v, 0, sizeof v);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &v), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, v.state[counter_at(1u, lead)], DUOFORGE_VIEW_HIDDEN);
        DF_CHECK_EQ_U64(t, v.state[cant_at(1u, lead)], cant);
        duoforge_hypothesis h;
        memset(&h, 0, sizeof h);
        DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, h.revision, DUOFORGE_HYPOTHESIS_REVISION);
        /* the true word, rebuilt, gives the true counter */
        const uint64_t truth = start == 2u ? ((uint64_t)1 << 62) : ((uint64_t)1 << 63);
        DF_CHECK_EQ_U64(t, rebuilt_counter(t, ctx, &v, &h, 1u, lead, truth, w), start - cant);
        /* the sweep: every word gives the law's counter */
        static const uint64_t words[] = {0u, 0x5555555555555555ull, 0x5555555555555556ull, 0xAAAAAAAAAAAAAAAAull,
                                         0xFFFFFFFFFFFFFFFFull};
        for (uint32_t k = 0u; k < sizeof words / sizeof words[0]; ++k) {
            DF_CHECK_EQ_U64(t, rebuilt_counter(t, ctx, &v, &h, 1u, lead, words[k], w), expected_counter(cant, words[k]));
        }
    }
    /* the share of the start 2 among the words of a sleep with no count yet: the bucket 0 of 3, 1/3 */
    duoforge_battle *s = turn_battle(t, ctx);
    put_sleep(s, 1u, lead, 3u, 0u);
    duoforge_public_state v;
    memset(&v, 0, sizeof v);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, s, 0u, &v), DUOFORGE_OK);
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, s, 0u, &h) == DUOFORGE_OK);
    uint32_t twos = 0u;
    for (uint32_t i = 0u; i < SLEEP_WORDS; ++i) {
        const uint64_t word = (uint64_t)i * (UINT64_MAX / (SLEEP_WORDS - 1u));
        if (rebuilt_counter(t, ctx, &v, &h, 1u, lead, word, w) == 2u) {
            ++twos;
        }
    }
    /* 1000 of 3000 words fall in the bucket 0 (the start 2 with no count): 1/3 */
    DF_CHECK(t, twos >= 990u && twos <= 1010u);
    duoforge_battle_destroy(s);
    duoforge_battle_destroy(w);
    duoforge_battle_destroy(b);
}

/* The refusals: a count above 2, a count without a sleep, revision 3, Early Bird and Sleep Talk among the moves. */
static void check_refusals(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    duoforge_battle *w = turn_battle(t, ctx);
    const uint32_t lead = b->sides[1].positions[0].occupant;
    put_sleep(b, 1u, lead, 3u, 1u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_public_state v;
    memset(&v, 0, sizeof v);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &v), DUOFORGE_OK);
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
    /* a count of 3 fits no start */
    v.state[cant_at(1u, lead)] = 3u;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &v, &h, w), DUOFORGE_E_MALFORMED);
    v.state[cant_at(1u, lead)] = 1u;
    /* a count on a member that is not asleep: the foe's second member */
    const uint32_t other = (lead + 1u) % 6u;
    v.state[cant_at(1u, other)] = 1u;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &v, &h, w), DUOFORGE_E_INVALID_ARGUMENT);
    v.state[cant_at(1u, other)] = 0u;
    /* revision 3 has no exact law: a hidden POOL sleeper is refused */
    h.revision = 3u;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &v, &h, w), DUOFORGE_E_UNSUPPORTED);
    h.revision = DUOFORGE_HYPOTHESIS_REVISION;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &v, &h, w), DUOFORGE_OK);
    duoforge_battle_destroy(w);
    duoforge_battle_destroy(b);
}

/* Early Bird and Sleep Talk: the own lead asleep with the ability (as the view shows it) or the move in its slot. */
static void check_unsupported_sources(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    duoforge_battle *w = turn_battle(t, ctx);
    const uint32_t lead = b->sides[0].positions[0].occupant;
    put_sleep(b, 0u, lead, 2u, 0u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_public_state v;
    memset(&v, 0, sizeof v);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &v), DUOFORGE_OK);
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &v, &h, w), DUOFORGE_OK);
    /* Early Bird on the sleeper: its own ability byte */
    duoforge_public_state e = v;
    e.state[member_at_off(0u, lead) + DFI_ENC_MEMBER_ABILITY_OFF] = (uint8_t)(DFI_ABILITY_EARLYBIRD + 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &e, &h, w), DUOFORGE_E_UNSUPPORTED);
    /* Sleep Talk in the sleeper's first move slot */
    duoforge_public_state m = v;
    m.state[member_at_off(0u, lead) + DFI_ENC_MOVE_OFF] = (uint8_t)(DFI_MOVE_SLEEPTALK & 0xFFu);
    m.state[member_at_off(0u, lead) + DFI_ENC_MOVE_OFF + 1u] = (uint8_t)(DFI_MOVE_SLEEPTALK >> 8);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &m, &h, w), DUOFORGE_E_UNSUPPORTED);
    duoforge_battle_destroy(w);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.view.sleep_count");
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_attempts(&t, kp, 2u);
    check_attempts(&t, kp, 3u);
    check_law(&t, kp);
    check_refusals(&t, kp);
    check_unsupported_sources(&t, kp);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
