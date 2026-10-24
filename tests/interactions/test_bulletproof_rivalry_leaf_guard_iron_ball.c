/*
 * duoforge.interactions.bulletproof_rivalry_leaf_guard_iron_ball (white-box): step G83 of the content expansion, Bulletproof,
 * Rivalry, Leaf Guard and Iron Ball (decision 0015 entry 5bt), all four engine rows read by id (Bulletproof in
 * dfi_try_hit_abilities; Rivalry in the base power chain; Leaf Guard in dfi_try_status and dfi_yawn; Iron Ball in dfi_grounded
 * and the item chain of dfi_speed_key): the marks and the bullet bit of the flags3 column, and each of the eight battles of its
 * list replays to its end; test_conformance compares the lines and HP of every step.
 *
 * Split by subject from the test of step G83 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The recorded battle `name` replayed to its end (every step is checked against the tape of the reference). */
static duoforge_battle *replay_all(df_test *t, const duoforge_context *ctx, const char *name)
{
    const df_conf_battle *cb = df_conf_find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        df_conf_bundle_of(st, b, &bd);
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

/* The marks: the four rows are engine rows (handler NONE, read by id). */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_BULLETPROOF] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_BULLETPROOF], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RIVALRY] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_RIVALRY], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_LEAFGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_LEAFGUARD], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_IRONBALL] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_IRONBALL], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG3_BULLET, 0x10u); /* the bullet bit of the flags3 column the Bulletproof reader tests (approved) */
}

/* Each G83 battle replays to its end with the lines and HP of the reference (test_conformance compares them step by step). */
static void check_battles(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g83_bulletproof_bullets", "g83_ironball_ground", "g83_ironball_spikes",
                                        "g83_ironball_speed", "g83_rivalry_gender", "g83_rivalry_genderless",
                                        "g83_leafguard_sun", "g83_leafguard_yawn_residual"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        duoforge_battle *b = replay_all(t, ctx, names[i]);
        if (b != NULL) {
            duoforge_battle_destroy(b);
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.bulletproof_rivalry_leaf_guard_iron_ball");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_battles(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
