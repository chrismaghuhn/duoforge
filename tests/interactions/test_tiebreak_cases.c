/*
 * duoforge.state.tiebreak (white-box): duoforge_battle_tiebreak on states made
 * by hand, so that the stage that decides is known from the numbers: the
 * count of the Pokemon not fainted, an equal count with different HP
 * percentages, an equal percentage with different total HP, an exact tie, the
 * rounding of the reference's binary64 sums, the order of a bench that the
 * engine does not keep, the whole roster before the picks, the four brought
 * of six, a terminal battle, a pure query, and the negative cases. The
 * battles of the pinned reference are in duoforge.reference.tiebreak (test_tiebreak.c).
 *
 * The expected values are worked out here from the numbers; the 64-bit
 * patterns of the HP percentages are what JavaScript's Number gives for the
 * pin's expression (sum of hp / maxhp from the left, * 100 / 6).
 */
#include <stdio.h>
#include <string.h>

#include "state/battle_internal.h"
#include "state/tiebreak.h"
#include "state/transition.h"
#include "support/check.h"
#include "support/fixtures.h"

#define SIDE0 DUOFORGE_RESULT_SIDE_0
#define SIDE1 DUOFORGE_RESULT_SIDE_1
#define TIE DUOFORGE_RESULT_TIE
#define BIT(r) (1u << (r))

/* One side of a hand-made state: the HP maximum and the HP of the roster. */
typedef struct side_spec {
    uint32_t hp_max[6];
    uint32_t hp[6];
} side_spec;

static void fill(side_spec *s, uint32_t hp_max, uint32_t hp)
{
    for (uint32_t i = 0; i < 6u; ++i) {
        s->hp_max[i] = hp_max;
        s->hp[i] = hp;
    }
}

/* C1 (SYNTHETIC, 6 members, 4 brought): both sides with the six members of
 * G1's side 0, the HP maxima of the specs, at TEAM_SELECTION. */
static duoforge_battle *make_selection(const duoforge_context *c1, const side_spec spec[2])
{
    duoforge_battle_setup setup;
    df_setup_g1(&setup);
    setup.sides[1].member_count = 6u;
    for (uint32_t i = 4u; i < 6u; ++i) {
        setup.sides[1].members[i] = setup.sides[0].members[i];
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t i = 0; i < 6u; ++i) {
            setup.sides[s].members[i].hp_max = spec[s].hp_max[i];
        }
    }
    return df_make_battle(c1, &setup);
}

/* The picks (both sides the ordered roster indices of picks[s]) and then the
 * HP of the specs for the whole roster, brought or not. */
static duoforge_battle *make_turn(const duoforge_context *ctx, duoforge_battle *b, const side_spec spec[2],
                                  const uint8_t picks[2][4], uint32_t brought)
{
    dfi_team_picks tp;
    memset(&tp, 0xFF, sizeof tp);
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t i = 0; i < brought; ++i) {
            tp.picks[s][i] = picks[s][i];
        }
    }
    if (dfi_apply_team_selection(ctx, b, &tp) != DUOFORGE_OK) {
        fprintf(stderr, "make_turn: team selection failed\n");
        return NULL;
    }
    df_see_active(b);
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t i = 0; i < b->sides[s].member_count; ++i) {
            b->sides[s].members[i].hp = (uint16_t)spec[s].hp[i];
        }
    }
    df_knowledge_refresh_active(b);
    if (duoforge_battle_check(ctx, b) != DUOFORGE_OK) {
        fprintf(stderr, "make_turn: the state is not valid\n");
        return NULL;
    }
    return b;
}

static const uint8_t k_picks_id[2][4] = {{0u, 1u, 2u, 3u}, {0u, 1u, 2u, 3u}};

/* The report and the public answer of a battle. want == 0: E_UNSUPPORTED. */
static void expect(df_test *t, const char *what, const duoforge_context *ctx, const duoforge_battle *b,
                   uint32_t want, uint32_t want_mask, const uint32_t nf[2], const uint32_t total[2])
{
    dfi_tiebreak_report r;
    memset(&r, 0xA5, sizeof r);
    const duoforge_status rs = dfi_battle_tiebreak_report(ctx, b, &r);
    uint32_t out = 0xDEADBEEFu;
    const duoforge_status st = duoforge_battle_tiebreak(ctx, b, &out);
    if (!DF_CHECK(t, rs == DUOFORGE_OK)) {
        fprintf(stderr, "  %s: report %s\n", what, duoforge_status_name(rs));
        return;
    }
    if (want != 0u) {
        DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, out, want);
    } else {
        DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
        DF_CHECK_EQ_U64(t, out, 0xDEADBEEFu); /* untouched on failure */
    }
    DF_CHECK_EQ_U64(t, r.result, want);
    DF_CHECK_EQ_U64(t, r.result_mask, want_mask);
    if (nf != NULL) {
        for (uint32_t s = 0; s < 2u; ++s) {
            if (!DF_CHECK_EQ_U64(t, r.not_fainted[s], nf[s]) || !DF_CHECK_EQ_U64(t, r.hp_total[s], total[s])) {
                fprintf(stderr, "  %s: side %u\n", what, s);
            }
        }
    }
}

static bool has_bits(const dfi_tiebreak_report *r, uint32_t side, uint64_t bits)
{
    for (uint32_t i = 0; i < r->pct_count[side]; ++i) {
        if (r->pct_bits[side][i] == bits) {
            return true;
        }
    }
    return false;
}

static void test_stages(df_test *t, const duoforge_context *c1)
{
    side_spec spec[2];
    const uint32_t four_total[2] = {400u, 400u};

    /* 1. The count decides, whatever the HP: three at full HP lose to four
     * at 1 HP (the percentage and the total favour the side with three). */
    fill(&spec[0], 100u, 100u);
    spec[0].hp[3] = 0u;
    fill(&spec[1], 100u, 1u);
    duoforge_battle *b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t nf[2] = {3u, 4u};
        const uint32_t total[2] = {300u, 4u};
        expect(t, "count", c1, b, SIDE1, BIT(SIDE1), nf, total);
        duoforge_battle_destroy(b);
    }

    /* 2. The same count, different HP percentages (all four alive). */
    fill(&spec[0], 100u, 100u);
    spec[0].hp[3] = 50u;
    fill(&spec[1], 100u, 100u);
    spec[1].hp[2] = 50u;
    spec[1].hp[3] = 50u;
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t nf[2] = {4u, 4u};
        const uint32_t total[2] = {350u, 300u};
        expect(t, "percentage", c1, b, SIDE0, BIT(SIDE0), nf, total);
        duoforge_battle_destroy(b);
    }

    /* 3. The percentage beats the total: 80 of 100 four times (53.3 percent,
     * 320 HP) against 150 of 450 four times (33.3 percent, 600 HP). */
    fill(&spec[0], 100u, 80u);
    fill(&spec[1], 450u, 150u);
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t nf[2] = {4u, 4u};
        const uint32_t total[2] = {320u, 600u};
        expect(t, "percentage over total", c1, b, SIDE0, BIT(SIDE0), nf, total);
        duoforge_battle_destroy(b);
    }

    /* 4. The same percentage, different total HP: half of 100 against half
     * of 200 (0.5 is exact in binary, so the percentages are equal). */
    fill(&spec[0], 100u, 50u);
    fill(&spec[1], 200u, 100u);
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t nf[2] = {4u, 4u};
        const uint32_t total[2] = {200u, 400u};
        expect(t, "total", c1, b, SIDE1, BIT(SIDE1), nf, total);
        dfi_tiebreak_report r;
        DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], r.pct_bits[1][0]);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], UINT64_C(0x4040aaaaaaaaaaab)); /* 33.333333333333336 */
        duoforge_battle_destroy(b);
    }

    /* 5. An exact tie: the same numbers on both sides. */
    fill(&spec[0], 100u, 100u);
    fill(&spec[1], 100u, 100u);
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        expect(t, "tie", c1, b, TIE, BIT(TIE), (const uint32_t[2]){4u, 4u}, four_total);
        dfi_tiebreak_report r;
        DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], UINT64_C(0x4050aaaaaaaaaaab)); /* 66.66666666666667: four of six */
        duoforge_battle_destroy(b);
    }

    /* 6. Equal everything but the order of the picks: still a tie, and the
     * leads and the bench in other slots change nothing. */
    {
        static const uint8_t other[2][4] = {{3u, 1u, 0u, 2u}, {2u, 0u, 3u, 1u}};
        b = make_turn(c1, make_selection(c1, spec), spec, other, 4u);
        if (DF_CHECK(t, b != NULL)) {
            expect(t, "tie, other picks", c1, b, TIE, BIT(TIE), (const uint32_t[2]){4u, 4u}, four_total);
            duoforge_battle_destroy(b);
        }
    }
}

/* The Pokemon not brought are not in side.pokemon: neither the count nor
 * the sums see them (the pin: side.pokemon is the four picked after the
 * team action, sim/battle.ts:2750-2757). */
static void test_not_brought(df_test *t, const duoforge_context *c1)
{
    side_spec spec[2];
    fill(&spec[0], 100u, 100u);
    fill(&spec[1], 100u, 100u);
    const uint32_t nf[2] = {4u, 4u};
    const uint32_t total[2] = {400u, 400u};
    /* Side 0's two others at full HP, side 1's two others fainted: a tie. */
    spec[1].hp[4] = 0u;
    spec[1].hp[5] = 0u;
    duoforge_battle *b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        expect(t, "not brought, fainted", c1, b, TIE, BIT(TIE), nf, total);
        duoforge_battle_destroy(b);
    }
    /* Brought by other picks: now those are the ones that count. */
    static const uint8_t picks[2][4] = {{0u, 1u, 2u, 3u}, {0u, 1u, 4u, 5u}};
    b = make_turn(c1, make_selection(c1, spec), spec, picks, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t nf2[2] = {4u, 2u};
        const uint32_t total2[2] = {400u, 200u};
        expect(t, "brought fainted", c1, b, SIDE0, BIT(SIDE0), nf2, total2);
        duoforge_battle_destroy(b);
    }
    /* Unequal HP maxima of the unpicked ones do not enter the percentage. */
    fill(&spec[0], 100u, 100u);
    fill(&spec[1], 100u, 100u);
    spec[0].hp_max[4] = 7u;
    spec[0].hp[4] = 1u;
    spec[0].hp_max[5] = 999u;
    spec[0].hp[5] = 3u;
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        expect(t, "not brought, odd HP", c1, b, TIE, BIT(TIE), nf, total);
        duoforge_battle_destroy(b);
    }
}

/* Before the picks: side.pokemon is the whole roster (sim/side.ts:241-245). */
static void test_selection(df_test *t, const duoforge_context *c1)
{
    side_spec spec[2];
    fill(&spec[0], 100u, 100u);
    fill(&spec[1], 200u, 200u);
    duoforge_battle *b = make_selection(c1, spec);
    if (DF_CHECK(t, b != NULL)) {
        /* Six against six at full HP: the percentage is 100 for both (the
         * divisor is 6 and so is the roster), the total HP decides. */
        dfi_tiebreak_report r;
        DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], UINT64_C(0x4059000000000000));
        DF_CHECK_EQ_U64(t, r.pct_bits[1][0], UINT64_C(0x4059000000000000));
        DF_CHECK_EQ_U64(t, r.pct_count[0], 1u); /* the order of a roster is known */
        expect(t, "selection, total", c1, b, SIDE1, BIT(SIDE1), (const uint32_t[2]){6u, 6u},
               (const uint32_t[2]){600u, 1200u});
        duoforge_battle_destroy(b);
    }
    /* G1: six members against four: the count decides. */
    b = df_make_g1(c1);
    expect(t, "selection G1", c1, b, SIDE0, BIT(SIDE0), (const uint32_t[2]){6u, 4u},
           (const uint32_t[2]){100u + 110u + 120u + 130u + 140u + 150u, 200u + 201u + 202u + 203u});
    duoforge_battle_destroy(b);
}

/* The sums are the reference's binary64 sums. A and B are equal as
 * fractions (7/6 of the roster's six, 19.4444...) but not as doubles: the
 * percentage of B is one unit in the last place larger, and with equal total
 * HP (3 each) exact arithmetic would give a tie. The reference has side 1 win.
 * C4: 4 members, 2 brought, no bench. */
static void test_rounding(df_test *t)
{
    duoforge_context *c4 = df_make_context(&df_config_c4);
    duoforge_battle_setup setup;
    df_setup_g7(&setup);
    setup.sides[0].members[0].hp_max = 2u;
    setup.sides[0].members[1].hp_max = 3u;
    setup.sides[1].members[0].hp_max = 2u;
    setup.sides[1].members[1].hp_max = 6u;
    setup.sides[0].members[2].hp_max = 50u; /* not brought */
    setup.sides[1].members[2].hp_max = 50u;
    duoforge_battle *b = df_make_battle(c4, &setup);
    dfi_team_picks tp;
    memset(&tp, 0xFF, sizeof tp);
    tp.picks[0][0] = 0u;
    tp.picks[0][1] = 1u;
    tp.picks[1][0] = 0u;
    tp.picks[1][1] = 1u;
    if (DF_CHECK(t, dfi_apply_team_selection(c4, b, &tp) == DUOFORGE_OK)) {
        df_see_active(b);
        b->sides[0].members[0].hp = 1u; /* 1/2 + 2/3 */
        b->sides[0].members[1].hp = 2u;
        b->sides[1].members[0].hp = 2u; /* 2/2 + 1/6 */
        b->sides[1].members[1].hp = 1u;
        b->sides[0].members[2].hp = 50u;
        b->sides[1].members[2].hp = 50u;
        df_knowledge_refresh_active(b);
        DF_CHECK(t, duoforge_battle_check(c4, b) == DUOFORGE_OK);
        dfi_tiebreak_report r;
        DF_CHECK(t, dfi_battle_tiebreak_report(c4, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_count[0], 1u);
        DF_CHECK_EQ_U64(t, r.pct_count[1], 1u);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], UINT64_C(0x403371c71c71c71c)); /* 19.444444444444443 */
        DF_CHECK_EQ_U64(t, r.pct_bits[1][0], UINT64_C(0x403371c71c71c71d)); /* 19.444444444444446 */
        expect(t, "rounding", c4, b, SIDE1, BIT(SIDE1), (const uint32_t[2]){2u, 2u}, (const uint32_t[2]){3u, 3u});
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(c4);
}

/* A side of four whose HP percentage depends in the last bit on the order of
 * its two bench Pokemon: with hp / maxhp 41/232, 217/244, 45/110, 203/246 the
 * bench order (2, 3) gives 38.33937602249244 and (3, 2) 38.33937602249243. */
static void four_fractions(side_spec *s)
{
    static const uint32_t hp[4] = {41u, 217u, 45u, 203u};
    static const uint32_t mx[4] = {232u, 244u, 110u, 246u};
    fill(s, 100u, 100u);
    for (uint32_t i = 0; i < 4u; ++i) {
        s->hp[i] = hp[i];
        s->hp_max[i] = mx[i];
    }
}

static void test_bench_order(df_test *t, const duoforge_context *c1)
{
    const uint64_t ab = UINT64_C(0x40432b70ac6ad367); /* 38.33937602249244 */
    const uint64_t ba = UINT64_C(0x40432b70ac6ad366); /* 38.33937602249243 */
    side_spec spec[2];
    dfi_tiebreak_report r;

    /* The engine keeps no bench order, so it evaluates every one: two
     * candidate values, the first that of the order of the picks. */
    four_fractions(&spec[0]);
    fill(&spec[1], 100u, 100u); /* a clear winner: full HP */
    duoforge_battle *b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_count[0], 2u);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][0], ab);
        DF_CHECK_EQ_U64(t, r.pct_bits[0][1], ba);
        DF_CHECK_EQ_U64(t, r.pct_count[1], 2u); /* equal fractions: the same value twice */
        DF_CHECK_EQ_U64(t, r.pct_bits[1][0], r.pct_bits[1][1]);
        /* The percentage differs in the last bit, the winner does not: answered. */
        expect(t, "bench order, clear", c1, b, SIDE1, BIT(SIDE1), (const uint32_t[2]){4u, 4u},
               (const uint32_t[2]){41u + 217u + 45u + 203u, 400u});
        duoforge_battle_destroy(b);
    }

    /* The picks' lead order is no bench order: the leads' sum is commutative. */
    {
        static const uint8_t swapped[2][4] = {{1u, 0u, 2u, 3u}, {0u, 1u, 2u, 3u}};
        b = make_turn(c1, make_selection(c1, spec), spec, swapped, 4u);
        if (DF_CHECK(t, b != NULL)) {
            DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, r.pct_count[0], 2u);
            DF_CHECK(t, has_bits(&r, 0u, ab) && has_bits(&r, 0u, ba));
            duoforge_battle_destroy(b);
        }
    }
    {
        /* Another bench order of the picks (3 before 2): the same two values. */
        static const uint8_t other[2][4] = {{0u, 1u, 3u, 2u}, {0u, 1u, 2u, 3u}};
        b = make_turn(c1, make_selection(c1, spec), spec, other, 4u);
        if (DF_CHECK(t, b != NULL)) {
            DF_CHECK(t, dfi_battle_tiebreak_report(c1, b, &r) == DUOFORGE_OK);
            DF_CHECK(t, has_bits(&r, 0u, ab) && has_bits(&r, 0u, ba));
            duoforge_battle_destroy(b);
        }
    }

    /* The mirror: both sides with those fractions. Equal for every pair of
     * orders that agree, one side ahead in the last bit for the others, so
     * the order the reference happens to hold would decide: not guessed. */
    four_fractions(&spec[1]);
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        const uint32_t total = 41u + 217u + 45u + 203u;
        expect(t, "bench order, mirror", c1, b, 0u, BIT(SIDE0) | BIT(SIDE1) | BIT(TIE), (const uint32_t[2]){4u, 4u},
               (const uint32_t[2]){total, total});
        duoforge_battle_destroy(b);
    }

    /* A side that is ahead by more than a rounding error: answered, whatever
     * the benches' orders (one more HP on the third Pokemon of 110). */
    four_fractions(&spec[1]);
    spec[1].hp[2] = 46u;
    b = make_turn(c1, make_selection(c1, spec), spec, k_picks_id, 4u);
    if (DF_CHECK(t, b != NULL)) {
        expect(t, "bench order, other side clearly ahead", c1, b, SIDE1, BIT(SIDE1), NULL, NULL);
        duoforge_battle_destroy(b);
    }
}

/* F4: REPLACEMENT with both leaders fainted: the roster members not brought
 * (side 0's 4 and 5) have HP and do not count. */
static void test_boundaries(df_test *t, const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f4(c1);
    /* Side 0 brought 2, 0, 1, 3 with member 2 fainted: three of hp_max 100,
     * 110, 130 at full HP, 340 in all; side 1 brought 1, 3, 0, 2 with member 3
     * fainted: three of 201, 200, 202, 603 in all. Equal count, equal
     * percentage (three of the four at full HP: 50 of the six... the same
     * sum of 1.0), the total decides. */
    expect(t, "F4", c1, b, SIDE1, BIT(SIDE1), (const uint32_t[2]){3u, 3u}, (const uint32_t[2]){340u, 603u});
    duoforge_battle_destroy(b);

    /* A TERMINAL battle gives its own result. */
    duoforge_context *c4 = df_make_context(&df_config_c4);
    b = df_make_f13(c4);
    {
        dfi_tiebreak_report r;
        uint32_t out = 0xDEADBEEFu;
        DF_CHECK(t, duoforge_battle_tiebreak(c4, b, &out) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, out, SIDE0);
        DF_CHECK(t, dfi_battle_tiebreak_report(c4, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.result_mask, BIT(SIDE0));
        /* A result the counts would not give: it is returned all the same. */
        b->result = (uint8_t)DFI_RESULT_TIE;
        if (duoforge_battle_check(c4, b) == DUOFORGE_OK) {
            DF_CHECK(t, duoforge_battle_tiebreak(c4, b, &out) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, out, TIE);
        }
        b->result = (uint8_t)DFI_RESULT_SIDE1;
        if (duoforge_battle_check(c4, b) == DUOFORGE_OK) {
            DF_CHECK(t, duoforge_battle_tiebreak(c4, b, &out) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, out, SIDE1);
        }
    }
    duoforge_battle_destroy(b);

    /* The small context (2 brought): no bench, one value for each side. */
    b = df_make_f9(c4);
    {
        dfi_tiebreak_report r;
        DF_CHECK(t, dfi_battle_tiebreak_report(c4, b, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, r.pct_count[0], 1u);
        DF_CHECK_EQ_U64(t, r.pct_count[1], 1u);
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(c4);
}

static void test_pure_and_negative(df_test *t, const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f2(c1);
    uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
    struct duoforge_battle copy;
    df_encode(c1, b, before);
    memcpy(&copy, b, sizeof copy);
    uint32_t first = 0u;
    uint32_t again = 0u;
    DF_CHECK(t, duoforge_battle_tiebreak(c1, b, &first) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_tiebreak(c1, b, &again) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, first, again);
    DF_CHECK(t, first >= SIDE0 && first <= TIE);
    df_encode(c1, b, after);
    DF_CHECK_BYTES(t, after, before, sizeof before, "encoding after a tiebreak");
    DF_CHECK_BYTES(t, (const uint8_t *)b, (const uint8_t *)&copy, sizeof copy, "the battle's bytes after a tiebreak");

    /* NULL arguments: E_NULL_ARGUMENT, nothing written. */
    uint32_t out = 0xDEADBEEFu;
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(NULL, b, &out), DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(c1, NULL, &out), DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(c1, b, NULL), DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(NULL, NULL, NULL), DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK_EQ_U64(t, out, 0xDEADBEEFu);

    /* A context that is not the battle's. */
    duoforge_context *c2 = df_make_context(&df_config_c2);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(c2, b, &out), DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK_EQ_U64(t, out, 0xDEADBEEFu);
    duoforge_context *k1 = df_make_context(&df_config_k1);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(k1, b, &out), DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK_EQ_U64(t, out, 0xDEADBEEFu);
    duoforge_context_destroy(k1);
    duoforge_context_destroy(c2);

    /* A corrupted state is an engine failure, as for the other queries. */
    b->sides[0].members[0].hp = (uint16_t)(b->sides[0].members[0].hp_max + 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_tiebreak(c1, b, &out), DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, out, 0xDEADBEEFu);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.tiebreak");
    duoforge_context *c1 = df_make_context(&df_config_c1);
    test_stages(&t, c1);
    test_not_brought(&t, c1);
    test_selection(&t, c1);
    test_rounding(&t);
    test_bench_order(&t, c1);
    test_boundaries(&t, c1);
    test_pure_and_negative(&t, c1);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
