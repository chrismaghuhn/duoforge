/*
 * duoforge.request.observation_ext (white-box): the POOL player-view
 * extension at tier 0 (decision 0018): the types, the query and its
 * conventions and the supported mask. Every field is zero and every bit clear until a step implements its
 * feature (step G8: Throat Chop and Heal Block; their fields are checked in test_pool_g8.c).
 *
 *   - the struct sizes and every offset of decision 0018 section 3 (literal
 *     numbers, not read back from the header's own macros);
 *   - the constants: the 40 feature bits are 0..39 once each, the 20 position
 *     bits are 20 different single bits, the type ids are alphabetical;
 *   - under every kind except POOL and POOL_DEV (CLOSURE, CLOSURE_DEV, TEAM_C,
 *     TEAM_C_DEV, SYNTHETIC) the result is all zero, at every boundary and for
 *     both viewers; under the POOL kinds it is zero except revision, player and
 *     epoch, and the paired observation has the same player and epoch;
 *   - the conventions of duoforge_battle_observe: NULL, then context mismatch,
 *     then the viewer, then the state invariant, and *out untouched on every
 *     failure;
 *   - purity: a query changes neither the battle nor the observation, and two
 *     calls give the same bytes.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

#define KIND_COUNT 6u

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];

/* Every requested player's first candidate. */
static bool first_bundle(const duoforge_context *ctx, const duoforge_battle *b, duoforge_decision_bundle *out)
{
    memset(out, 0, sizeof *out);
    for (uint32_t p = 0u; p < 2u; ++p) {
        duoforge_request rq;
        uint32_t n = 0u;
        if (duoforge_battle_request(ctx, b, p, &rq) != DUOFORGE_OK) {
            return false;
        }
        out->epoch = rq.epoch;
        if (rq.requested != 0u) {
            if (duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK || n == 0u) {
                return false;
            }
            out->response_mask = (uint8_t)(out->response_mask | (1u << p));
            out->responses[p] = cands[0];
        }
    }
    return true;
}

static void test_layout(df_test *t)
{
    DF_CHECK(t, sizeof(duoforge_field_ext) == 16u);
    DF_CHECK(t, sizeof(duoforge_position_ext) == 16u);
    DF_CHECK(t, sizeof(duoforge_member_ext) == 4u);
    DF_CHECK(t, sizeof(duoforge_side_ext) == 64u);
    DF_CHECK(t, sizeof(duoforge_observation_ext) == 192u);
    DF_CHECK(t, DUOFORGE_OBSERVATION_EXT_SIZE == 192u && DUOFORGE_OBSERVATION_EXT_REVISION == 1u);

    DF_CHECK(t, offsetof(duoforge_field_ext, gravity_turns) == 0u && offsetof(duoforge_field_ext, reserved) == 1u);

    DF_CHECK(t, offsetof(duoforge_position_ext, volatiles) == 0u);
    DF_CHECK(t, offsetof(duoforge_position_ext, ability_now) == 4u);
    DF_CHECK(t, offsetof(duoforge_position_ext, type_now) == 6u);
    DF_CHECK(t, offsetof(duoforge_position_ext, encore_slot) == 8u);
    DF_CHECK(t, offsetof(duoforge_position_ext, disable_slot) == 9u);
    DF_CHECK(t, offsetof(duoforge_position_ext, stockpile) == 10u);
    DF_CHECK(t, offsetof(duoforge_position_ext, perish) == 11u);
    DF_CHECK(t, offsetof(duoforge_position_ext, reserved) == 12u);

    DF_CHECK(t, offsetof(duoforge_member_ext, forme) == 0u);
    DF_CHECK(t, offsetof(duoforge_member_ext, item_now) == 2u);
    DF_CHECK(t, offsetof(duoforge_member_ext, reserved) == 3u);

    DF_CHECK(t, offsetof(duoforge_side_ext, positions) == 0u);
    DF_CHECK(t, offsetof(duoforge_side_ext, members) == 32u);
    DF_CHECK(t, offsetof(duoforge_side_ext, aurora_veil_turns) == 56u);
    DF_CHECK(t, offsetof(duoforge_side_ext, stealth_rock) == 57u);
    DF_CHECK(t, offsetof(duoforge_side_ext, spikes) == 58u);
    DF_CHECK(t, offsetof(duoforge_side_ext, toxic_spikes) == 59u);
    DF_CHECK(t, offsetof(duoforge_side_ext, sticky_web) == 60u);
    DF_CHECK(t, offsetof(duoforge_side_ext, guard_flags) == 61u);
    DF_CHECK(t, offsetof(duoforge_side_ext, reserved) == 62u);

    DF_CHECK(t, offsetof(duoforge_observation_ext, revision) == 0u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, player) == 1u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, reserved0) == 2u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, epoch) == 4u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, supported) == 8u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, field) == 16u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, sides) == 32u);
    DF_CHECK(t, offsetof(duoforge_observation_ext, reserved1) == 160u);
    /* The sections end exactly where the next begins and the struct is full: no padding. */
    DF_CHECK(t, 160u + 32u == sizeof(duoforge_observation_ext));
}

static void test_constants(df_test *t)
{
    static const uint32_t features[] = {
        DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND,     DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW,
        DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE,   DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL,
        DUOFORGE_VIEWEXT_FEATURE_PERISH,           DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC,
        DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP,      DUOFORGE_VIEWEXT_FEATURE_ENCORE,
        DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES,     DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE,
        DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX,      DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE,
        DUOFORGE_VIEWEXT_FEATURE_IMPRISON,         DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK,
        DUOFORGE_VIEWEXT_FEATURE_TAUNT,            DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE,
        DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK,       DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD,
        DUOFORGE_VIEWEXT_FEATURE_PARTIAL_TRAP,     DUOFORGE_VIEWEXT_FEATURE_FORME_CHANGE,
        DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH,      DUOFORGE_VIEWEXT_FEATURE_DISABLE,
        DUOFORGE_VIEWEXT_FEATURE_STOCKPILE,        DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE,
        DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER,     DUOFORGE_VIEWEXT_FEATURE_YAWN,
        DUOFORGE_VIEWEXT_FEATURE_ILLUSION,         DUOFORGE_VIEWEXT_FEATURE_GRAVITY,
        DUOFORGE_VIEWEXT_FEATURE_LEECH_SEED,       DUOFORGE_VIEWEXT_FEATURE_FOCUS_ENERGY,
        DUOFORGE_VIEWEXT_FEATURE_SPIKES,           DUOFORGE_VIEWEXT_FEATURE_CHARGE,
        DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY,    DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB,
        DUOFORGE_VIEWEXT_FEATURE_SALT_CURE,        DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND,
        DUOFORGE_VIEWEXT_FEATURE_CURSE,            DUOFORGE_VIEWEXT_FEATURE_NO_RETREAT,
        DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD,      DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER,
    };
    /* Bit numbers 0 to 39, each once, in the order of the note (the tiers). */
    DF_CHECK(t, sizeof features / sizeof features[0] == DUOFORGE_VIEWEXT_FEATURE_COUNT);
    DF_CHECK(t, DUOFORGE_VIEWEXT_FEATURE_COUNT == 40u);
    uint64_t seen = 0u;
    for (uint32_t i = 0u; i < DUOFORGE_VIEWEXT_FEATURE_COUNT; ++i) {
        DF_CHECK(t, features[i] == i);
        seen |= (uint64_t)1u << features[i];
    }
    DF_CHECK(t, seen == (((uint64_t)1u << 40u) - 1u));

    static const uint32_t vol[] = {
        DUOFORGE_POSITION_EXT_SUBSTITUTE,    DUOFORGE_POSITION_EXT_TAUNT,         DUOFORGE_POSITION_EXT_IMPRISON,
        DUOFORGE_POSITION_EXT_LEECH_SEED,    DUOFORGE_POSITION_EXT_YAWN,          DUOFORGE_POSITION_EXT_FOCUS_ENERGY,
        DUOFORGE_POSITION_EXT_DRAGON_CHEER,  DUOFORGE_POSITION_EXT_MUST_RECHARGE, DUOFORGE_POSITION_EXT_PARTIAL_TRAP,
        DUOFORGE_POSITION_EXT_GLAIVE_RUSH,   DUOFORGE_POSITION_EXT_DESTINY_BOND,  DUOFORGE_POSITION_EXT_CURSE,
        DUOFORGE_POSITION_EXT_NO_RETREAT,    DUOFORGE_POSITION_EXT_SALT_CURE,     DUOFORGE_POSITION_EXT_CHARGE,
        DUOFORGE_POSITION_EXT_HEAL_BLOCK,    DUOFORGE_POSITION_EXT_THROAT_CHOP,   DUOFORGE_POSITION_EXT_RAGE_POWDER,
        DUOFORGE_POSITION_EXT_TYPE_CHANGED,  DUOFORGE_POSITION_EXT_ILLUSION_UP,
    };
    uint32_t all = 0u;
    for (uint32_t i = 0u; i < sizeof vol / sizeof vol[0]; ++i) {
        DF_CHECK(t, vol[i] == (1u << i)); /* bit i, in the order of the note */
        all |= vol[i];
    }
    DF_CHECK(t, sizeof vol / sizeof vol[0] == 20u && all == 0xFFFFFu);
    DF_CHECK(t, DUOFORGE_SIDE_GUARD_WIDE_GUARD == 1u && DUOFORGE_SIDE_GUARD_QUICK_GUARD == 2u);
    DF_CHECK(t, DUOFORGE_ITEM_NOW_NONE == 255u);

    /* Type ids: the alphabetical order of the tables (type_now holds id + 1). */
    DF_CHECK(t, DUOFORGE_TYPE_BUG == DFI_TYPE_BUG && DUOFORGE_TYPE_DARK == DFI_TYPE_DARK &&
                    DUOFORGE_TYPE_DRAGON == DFI_TYPE_DRAGON && DUOFORGE_TYPE_ELECTRIC == DFI_TYPE_ELECTRIC &&
                    DUOFORGE_TYPE_FAIRY == DFI_TYPE_FAIRY && DUOFORGE_TYPE_FIGHTING == DFI_TYPE_FIGHTING &&
                    DUOFORGE_TYPE_FIRE == DFI_TYPE_FIRE && DUOFORGE_TYPE_FLYING == DFI_TYPE_FLYING &&
                    DUOFORGE_TYPE_GHOST == DFI_TYPE_GHOST && DUOFORGE_TYPE_GRASS == DFI_TYPE_GRASS &&
                    DUOFORGE_TYPE_GROUND == DFI_TYPE_GROUND && DUOFORGE_TYPE_ICE == DFI_TYPE_ICE &&
                    DUOFORGE_TYPE_NORMAL == DFI_TYPE_NORMAL && DUOFORGE_TYPE_POISON == DFI_TYPE_POISON &&
                    DUOFORGE_TYPE_PSYCHIC == DFI_TYPE_PSYCHIC && DUOFORGE_TYPE_ROCK == DFI_TYPE_ROCK &&
                    DUOFORGE_TYPE_STEEL == DFI_TYPE_STEEL && DUOFORGE_TYPE_WATER == DFI_TYPE_WATER);
    /* The new enum values extend the old fields without touching the old ones. */
    DF_CHECK(t, DUOFORGE_WEATHER_SUN == 2u && DUOFORGE_WEATHER_SAND == 3u && DUOFORGE_WEATHER_SNOW == 4u);
    DF_CHECK(t, DUOFORGE_TERRAIN_PSYCHIC == 2u && DUOFORGE_TERRAIN_ELECTRIC == 3u && DUOFORGE_TERRAIN_MISTY == 4u);
    DF_CHECK(t, DUOFORGE_AILMENT_POISON == 5u && DUOFORGE_AILMENT_TOX == 6u);
    /* The bits that the build's steps have set (decision 0018 section 7): step G8, Throat Chop (bit 6) and Heal Block
     * (bit 16); step G11, the type change of Soak (bit 9); step G7, Wide Guard (bit 17); step G9, Encore (bit 7); step G17, the recharge
     * (bit 15); the step of Sandstorm and Snowscape, the weather values Sand (bit 0) and Snow (bit 1); step G16, the item that a move
     * took (bit 11, Knock Off); step AC1, the ability change of Trace (bit 2); step G19, Glaive Rush (bit 20); step G20, Aurora Veil (bit 3); step G27, Disable (bit 21). A step that sets a bit changes this expectation
     * together with its recorded battles. */
    DF_CHECK(t, dfi_support.view_ext_features ==
                    (((uint64_t)1u << 6u) | ((uint64_t)1u << 7u) | ((uint64_t)1u << 9u) | ((uint64_t)1u << 15u) |
                     ((uint64_t)1u << 16u) | ((uint64_t)1u << 17u) | ((uint64_t)1u << 0u) | ((uint64_t)1u << 1u) |
                     ((uint64_t)1u << 11u) | ((uint64_t)1u << 2u) | ((uint64_t)1u << 20u) | ((uint64_t)1u << 3u) |
                     ((uint64_t)1u << 21u)));
}

/* The expected extension: all zero, and under POOL the header of the paired observation. */
static void expect_ext(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer, bool pool,
                       const char *what)
{
    duoforge_observation_ext got;
    memset(&got, 0xA5, sizeof got);
    duoforge_observation ob;
    const duoforge_status ss = duoforge_battle_observe_ext(ctx, b, viewer, &got);
    const duoforge_status os = duoforge_battle_observe(ctx, b, viewer, &ob);
    duoforge_observation_ext want;
    memset(&want, 0, sizeof want);
    if (pool && os == DUOFORGE_OK) {
        want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
        want.player = (uint8_t)viewer;
        want.epoch = ob.epoch;
        want.supported = dfi_support.view_ext_features;
    }
    if (!DF_CHECK(t, ss == DUOFORGE_OK && os == DUOFORGE_OK && memcmp(&got, &want, sizeof got) == 0)) {
        fprintf(stderr, "  %s viewer %u: status %u, the extension is not the expected one\n", what, viewer, ss);
    }
    if (pool) {
        DF_CHECK(t, got.player == ob.player && got.epoch == ob.epoch && got.supported == dfi_support.view_ext_features);
    }
    /* Purity: the battle and the answer do not change by asking, twice. */
    uint8_t d0[DUOFORGE_DIGEST_SIZE], d1[DUOFORGE_DIGEST_SIZE];
    duoforge_observation_ext again;
    DF_CHECK(t, duoforge_battle_digest(ctx, b, d0) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &again) == DUOFORGE_OK &&
                    memcmp(&again, &got, sizeof again) == 0);
    DF_CHECK(t, duoforge_battle_digest(ctx, b, d1) == DUOFORGE_OK && memcmp(d0, d1, sizeof d0) == 0);
    duoforge_observation ob2;
    DF_CHECK(t, duoforge_battle_observe(ctx, b, viewer, &ob2) == DUOFORGE_OK && memcmp(&ob, &ob2, sizeof ob) == 0);
}

static void test_kind(df_test *t, const duoforge_context_config *cfg, const char *name, bool pool)
{
    duoforge_context *ctx = df_make_context(cfg);
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_battle *b = df_make_battle(ctx, &s);
    /* TEAM_SELECTION, then the first TURN. */
    for (uint32_t stage = 0u; stage < 2u; ++stage) {
        for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
            expect_ext(t, ctx, b, viewer, pool, name);
        }
        duoforge_decision_bundle bundle;
        duoforge_step_result res;
        if (!DF_CHECK(t, first_bundle(ctx, b, &bundle) && duoforge_battle_step(ctx, b, &bundle, &res) == DUOFORGE_OK)) {
            break;
        }
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

static void test_synthetic(df_test *t)
{
    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_battle *b = df_make_f1(c1); /* a SYNTHETIC battle at a TURN boundary */
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        expect_ext(t, c1, b, viewer, false, "SYNTHETIC");
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(c1);
}

static bool untouched(const duoforge_observation_ext *x)
{
    duoforge_observation_ext pattern;
    memset(&pattern, 0xA5, sizeof pattern);
    return memcmp(x, &pattern, sizeof pattern) == 0;
}

static void test_conventions(df_test *t)
{
    duoforge_context *pool = df_make_context(&df_config_pool);
    duoforge_context *closure = df_make_context(&df_config_k1);
    duoforge_context *team_c = df_make_context(&df_config_team_c);
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_battle *b = df_make_battle(pool, &s);
    duoforge_battle *bk = df_make_battle(closure, &s);
    duoforge_observation_ext out;

#define FRESH() memset(&out, 0xA5, sizeof out)
    /* NULL: every pointer, ahead of every other check (also a bad viewer). */
    FRESH();
    DF_CHECK(t, duoforge_battle_observe_ext(NULL, b, 0u, &out) == DUOFORGE_E_NULL_ARGUMENT && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(pool, NULL, 0u, &out) == DUOFORGE_E_NULL_ARGUMENT && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(pool, b, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_observe_ext(NULL, NULL, 7u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_observe_ext(NULL, b, 7u, &out) == DUOFORGE_E_NULL_ARGUMENT && untouched(&out));
    /* A battle of another context: CONTEXT_MISMATCH, ahead of the viewer check. */
    DF_CHECK(t, duoforge_battle_observe_ext(pool, bk, 0u, &out) == DUOFORGE_E_CONTEXT_MISMATCH && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(closure, b, 0u, &out) == DUOFORGE_E_CONTEXT_MISMATCH && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(team_c, b, 0u, &out) == DUOFORGE_E_CONTEXT_MISMATCH && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(team_c, bk, 7u, &out) == DUOFORGE_E_CONTEXT_MISMATCH && untouched(&out));
    /* The viewer: 0 and 1 only, ahead of the state check, under every kind. */
    DF_CHECK(t, duoforge_battle_observe_ext(pool, b, 2u, &out) == DUOFORGE_E_INVALID_ARGUMENT && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(pool, b, 0xFFFFFFFFu, &out) == DUOFORGE_E_INVALID_ARGUMENT && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(closure, bk, 2u, &out) == DUOFORGE_E_INVALID_ARGUMENT && untouched(&out));
    /* The state invariant, as duoforge_battle_observe reports it: an index out of range. */
    duoforge_battle *x = NULL;
    DF_CHECK(t, duoforge_battle_clone(pool, b, &x) == DUOFORGE_OK);
    x->sides[1].members[0].nature = (uint8_t)DFI_NATURE_COUNT;
    duoforge_observation ob;
    FRESH();
    DF_CHECK(t, duoforge_battle_observe(pool, x, 0u, &ob) == DUOFORGE_E_INVARIANT);
    DF_CHECK(t, duoforge_battle_observe_ext(pool, x, 0u, &out) == DUOFORGE_E_INVARIANT && untouched(&out));
    DF_CHECK(t, duoforge_battle_observe_ext(pool, x, 5u, &out) == DUOFORGE_E_INVALID_ARGUMENT && untouched(&out));
    duoforge_battle_destroy(x);
    DF_CHECK(t, duoforge_battle_clone(closure, bk, &x) == DUOFORGE_OK);
    x->sides[1].members[0].nature = (uint8_t)DFI_NATURE_COUNT;
    FRESH();
    DF_CHECK(t, duoforge_battle_observe_ext(closure, x, 1u, &out) == DUOFORGE_E_INVARIANT && untouched(&out));
    duoforge_battle_destroy(x);
#undef FRESH

    duoforge_battle_destroy(bk);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(team_c);
    duoforge_context_destroy(closure);
    duoforge_context_destroy(pool);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.observation_ext");
    test_layout(&t);
    test_constants(&t);
    test_kind(&t, &df_config_k1, "CLOSURE", false);
    test_kind(&t, &df_config_k2, "CLOSURE_DEV", false);
    test_kind(&t, &df_config_team_c, "TEAM_C", false);
    test_kind(&t, &df_config_team_c_dev, "TEAM_C_DEV", false);
    test_kind(&t, &df_config_pool, "POOL", true);
    test_kind(&t, &df_config_pool_dev, "POOL_DEV", true);
    test_synthetic(&t);
    test_conventions(&t);
    return df_test_end(&t);
}
