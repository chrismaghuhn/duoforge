/*
 * duoforge.interactions.magic_guard_air_balloon (white-box): step G67 of the content expansion, Magic Guard and Air Balloon
 * (decision 0015 entry 5bl). Magic Guard (data/abilities.ts:2465-2476) blocks every damage whose Showdown effect is not a Move;
 * the turn code classes every indirect damage with dfi_deal's required dfi_dmg_class (SIDE, WEATHER, STATUS, CONDITION, RECOIL
 * and ITEM skipped silently by a holder, ABILITY skipped with -activate, DIRECT and MOVE taken, UNCLASSIFIED refused). The
 * marks (both rows are engine rows, the switch-in line is the event kind 48), and each of the twelve battles of its list
 * replays to its end with no refusal; test_conformance compares the HP and the lines of every step.
 *
 * Split by subject from the test of step G67 (restructure step 6e; tests/renames.tsv maps the old name).
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

/* The marks: both rows are engine rows (handler NONE, read by id), and the switch-in line is the event kind 48. */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MAGICGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MAGICGUARD], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_AIRBALLOON] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_AIRBALLOON], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_ITEM_SHOWN, 48u); /* decision 0033 */
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_ITEM_SHOWN, DUOFORGE_EVENT_CLEAR_ALL_BOOSTS + 1u);
}

/* Each G67 battle replays to its end: the classes of the table above are what the recorded lines show, and the turn code
 * takes or skips the damage accordingly (test_conformance compares the HP and the lines of every step). */
static void check_battles(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g67_magic_guard_sandstorm", "g67_magic_guard_hazards", "g67_magic_guard_recoil",
                                        "g67_balloon_ground", "g67_balloon_stealth_rock", "g67_mg_sand_tie",
                                        "g67_struggle_sub_balloon", "g67_residual_leftovers_tie", "g67_update_sitrus_tie",
                                        "g67_af_sub_pop_normal", "g67_mg_recoil_contact", "g67_mg_struggle"};
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
    df_test_begin(&t, "duoforge.interactions.magic_guard_air_balloon");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_battles(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
