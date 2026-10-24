/*
 * duoforge.abilities.swift_swim_fainted_holder (white-box): step G22 of the content expansion (decision 0015 entry 5o), the
 * queued action of a fainted Swift Swim holder, under both POOL kinds. In g22_swift_swim Kingambit knocks Basculegion out with
 * Sucker Punch in the rain; its Liquidation stays in the queue and, with a standing holder's x2, would not tie Politoed's
 * Weather Ball (196 against 98). The pin prices a fainted Pokemon's action again without its ability (an inactive Pokemon's
 * ability handler is ignored, sim/battle.ts:874-883, sim/pokemon.ts:858-859), at the raw 98 that Politoed has with its 8 Speed
 * points, so the two tie and the reference draws a shuffle. The tape without that entry fails exactly there (E_INVARIANT, every
 * earlier entry consumed): the engine draws the tie. The recorded battles g22_* are replayed by
 * duoforge.reference.conformance_pool_data.
 *
 * Split by subject from the test of step G22 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

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
#define TAPE_MAX 64u

/* 1. The tie of a fainted Swift Swim holder's queued action. */
static void check_fainted_holder(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g22_swift_swim");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 4u)) {
        return;
    }
    const uint32_t decisive = 4u; /* turn 3: Sucker Punch, then the tie of Basculegion's and Politoed's actions */
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, decisive);
    if (b == NULL) {
        return;
    }
    const df_conf_step *st = &cb->steps[decisive];
    const dfi_tape_entry *tape = &conf_tape[st->tape_off];
    uint32_t at = st->tape_len;
    for (uint32_t i = 1u; i < st->tape_len; ++i) {
        if (tape[i].site == DFI_SITE_SPEED_TIE && tape[i - 1u].site == DFI_SITE_DAMAGE_ROLL) {
            at = i;
            break;
        }
    }
    if (!DF_CHECK(t, at < st->tape_len) || !DF_CHECK(t, st->tape_len < TAPE_MAX)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    df_conf_bundle_of(st, b, &bd);
    static dfi_tape_entry variant[TAPE_MAX];
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < st->tape_len; ++i) {
        if (i != at) {
            variant[n++] = tape[i];
        }
    }
    duoforge_battle *c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, tape, st->tape_len, &used, &res) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, used, st->tape_len);
        duoforge_battle_destroy(c);
    }
    c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, variant, n, &used, &res) == DUOFORGE_E_INVARIANT);
        if (!DF_CHECK_EQ_U64(t, used, at)) {
            fprintf(stderr, "  the engine asked for the tie of the fainted Swift Swim holder's action after %u entries, not %u\n",
                    used, at);
        }
        duoforge_battle_destroy(c);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.swift_swim_fainted_holder");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    for (uint32_t k = 0u; k < 2u; ++k) {
        const duoforge_context *ctx = k == 0u ? kp : kd;
        check_fainted_holder(&t, ctx);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
