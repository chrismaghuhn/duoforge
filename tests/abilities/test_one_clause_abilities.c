/*
 * duoforge.abilities.one_clause_abilities (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), fourteen
 * abilities with one clause each at an existing hook, as one batch. The recorded POOL battles a2a_cover_a to a2a_cover_i
 * (campaigns 52002 and 52003) are replayed against the pool rows by duoforge.reference.conformance_pool_data; this test checks
 * what the replays alone do not:
 *
 *   1. The marks and the handler column: the fourteen rows are marked engine rows (handler NONE); Insomnia, Vital Spirit and
 *      Immunity stay unmarked UNMODELED rows (HS decision: stragglers after the abilities move, their Trace refusal belongs in
 *      dfi_trace). Poison Point's draw site is 26 (HS grant) with its own name.
 *   2. The hook fires and the neighbours do not: at the step of a recorded battle where the clause decides something, the step
 *      replays with the reference's tape; with the holder's ability changed to a marked neighbour of the same hook (Volt Absorb
 *      for Water Absorb and Earth Eater, Lightning Rod for Motor Drive, Rain Dish for Ice Body, Static for Poison Point, ...)
 *      the same step no longer reproduces the reference (another status, another tape use or other events).
 *
 * Split by subject from the test of step A2a (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/abilities/current.h"
#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/observation_digest.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define AB(x) (1u + DFI_ABILITY_##x)

/* One clause at its decisive step: the battle, the step, the holder (side and forme), the clause's ability the holder has at the
 * step (its sheet's or, for the Trace holder, the copied one), and the marked neighbour of the same hook. */
typedef struct a2a_case {
    const char *battle;
    uint32_t step;
    uint32_t side;
    uint32_t forme;
    uint32_t ability;
    uint32_t neighbour;
    const char *what;
} a2a_case;

static const a2a_case cases[] = {
    {"a2a_cover_a", 10u, 0u, DFI_FORME_WATCHOG, AB(ILLUMINATE), AB(BIGPECKS), "Illuminate deletes Mud-Slap's accuracy drop"},
    {"a2a_cover_c", 3u, 0u, DFI_FORME_STARMIE, AB(ILLUMINATE), AB(BIGPECKS), "Illuminate ignores Gardevoir's evasion"},
    {"a2a_cover_a", 5u, 1u, DFI_FORME_TORKOAL, AB(WHITESMOKE), AB(HYPERCUTTER), "White Smoke deletes Muddy Water's drop (roll 21)"},
    {"a2a_cover_b", 2u, 0u, DFI_FORME_VAPOREON, AB(WATERABSORB), AB(VOLTABSORB), "Water Absorb takes Surf at full HP (-immune)"},
    {"a2a_cover_g", 1u, 1u, DFI_FORME_ORTHWORM, AB(EARTHEATER), AB(VOLTABSORB), "Earth Eater takes Earthquake at full HP"},
    {"a2a_cover_b", 13u, 0u, DFI_FORME_EMOLGA, AB(MOTORDRIVE), AB(LIGHTNINGROD), "Motor Drive: Wild Charge raises Speed"},
    {"a2a_cover_b", 14u, 1u, DFI_FORME_AVALUGG, AB(ICEBODY), AB(RAINDISH), "Ice Body heals in snow"},
    {"a2a_cover_d", 10u, 1u, DFI_FORME_RAICHUALOLA, AB(SURGESURFER), AB(SWIFTSWIM), "Surge Surfer doubles Speed in Electric Terrain"},
    {"a2a_cover_c", 3u, 1u, DFI_FORME_GARDEVOIR, AB(QUICKFEET), AB(CHLOROPHYLL), "Quick Feet (traced) of a paralysed Gardevoir"},
    {"a2a_cover_e", 1u, 1u, DFI_FORME_SALAZZLE, AB(CORROSION), AB(OBLIVIOUS), "Corrosion: Toxic poisons a Poison type"},
    {"a2a_cover_a", 9u, 1u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt refuses Hypnosis"},
    {"a2a_cover_a", 6u, 1u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt refuses Yawn"},
    {"a2a_cover_d", 10u, 0u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt halves Shadow Ball"},
    {"a2a_cover_f", 1u, 0u, DFI_FORME_GOODRA, AB(GOOEY), AB(WEAKARMOR), "Gooey lowers Corviknight's Speed (Mirror Armor)"},
    {"a2a_cover_a", 1u, 0u, DFI_FORME_DRAGALGE, AB(POISONPOINT), AB(STATIC), "Poison Point rolls on site 26"},
    {"a2a_cover_c", 15u, 0u, DFI_FORME_PIDGEOT, AB(TANGLEDFEET), AB(SANDVEIL), "Tangled Feet halves Snarl's accuracy"},
    {"a2a_cover_b", 2u, 1u, DFI_FORME_PAWMOT, AB(NATURALCURE), AB(REGENERATOR), "Natural Cure cures tox at the switch-out"},
};

static void check_case(df_test *t, const duoforge_context *ctx, const a2a_case *c)
{
    const df_conf_battle *cb = df_conf_find(c->battle);
    if (!DF_CHECK(t, cb != NULL && c->step < cb->step_count)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, c->step);
    if (b == NULL) {
        return;
    }
    const uint32_t m = df_conf_member_of(b, c->side, c->forme);
    if (!DF_CHECK(t, m < DUOFORGE_MAX_ROSTER) ||
        !DF_CHECK_EQ_U64(t, dfi_ability_code(b, &b->sides[c->side].members[m]), c->ability)) {
        fprintf(stderr, "  %s: the holder is not found with its ability\n", c->what);
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[c->step];
    static df_conf_run base;
    static df_conf_run moved;
    duoforge_battle *x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        df_conf_run_step(ctx, x, st, &base);
        if (!DF_CHECK(t, base.status == DUOFORGE_OK) || !DF_CHECK_EQ_U64(t, base.used, st->tape_len)) {
            fprintf(stderr, "  %s: the recorded step does not replay\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        const uint32_t sheet = x->sides[c->side].members[m].ability;
        x->tail.sides[c->side].ability_now[m] = (uint16_t)(c->neighbour == sheet ? 0u : c->neighbour);
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        df_conf_run_step(ctx, x, st, &moved);
        const bool same = moved.status == DUOFORGE_OK && moved.used == st->tape_len && moved.count == base.count &&
                          memcmp(moved.events, base.events, (size_t)base.count * sizeof base.events[0]) == 0;
        if (!DF_CHECK(t, !same)) {
            fprintf(stderr, "  %s: the neighbour ability plays the same step\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

static void check_marks(df_test *t)
{
    static const uint32_t rows[] = {DFI_ABILITY_ILLUMINATE, DFI_ABILITY_WHITESMOKE, DFI_ABILITY_WATERABSORB, DFI_ABILITY_EARTHEATER,
                                    DFI_ABILITY_MOTORDRIVE, DFI_ABILITY_ICEBODY, DFI_ABILITY_SURGESURFER, DFI_ABILITY_QUICKFEET,
                                    DFI_ABILITY_CORROSION, DFI_ABILITY_PURIFYINGSALT, DFI_ABILITY_GOOEY, DFI_ABILITY_POISONPOINT,
                                    DFI_ABILITY_TANGLEDFEET, DFI_ABILITY_NATURALCURE};
    for (size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[rows[i]], DFI_HANDLER_NONE);
    }
    static const uint32_t stragglers[] = {DFI_ABILITY_INSOMNIA, DFI_ABILITY_VITALSPIRIT, DFI_ABILITY_IMMUNITY};
    for (size_t i = 0; i < sizeof stragglers / sizeof stragglers[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[stragglers[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[stragglers[i]], DFI_HANDLER_UNMODELED);
    }
    DF_CHECK_EQ_U64(t, DFI_SITE_POISON_POINT, 26u);
    const char *name = dfi_site_name(DFI_SITE_POISON_POINT);
    DF_CHECK(t, name != NULL && strcmp(name, "poison-point") == 0);
    DF_CHECK(t, DFI_SITE_POISON_POINT != DFI_SITE_STATIC && DFI_SITE_POISON_POINT != DFI_SITE_FLAME_BODY);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.one_clause_abilities");
    check_marks(&t);
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            check_case(&t, kp, &cases[i]);
        }
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
