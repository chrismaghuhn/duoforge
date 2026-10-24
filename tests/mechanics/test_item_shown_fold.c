/*
 * duoforge.mechanics.item_shown_fold (white-box): step G67 of the content expansion, the event ITEM_SHOWN (decision 0033) in
 * the fold: the open team sheets already show the item, so a fold of this event leaves the viewer's knowledge (the whole battle
 * record, as the fold writes it) exactly as it was: g67_balloon_ground replayed to its end and folded once.
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

/* The fold ignores ITEM_SHOWN (decision 0033): the open team sheets already show the item, so a fold of this event leaves the
 * viewer's knowledge (the whole battle record, as the fold writes it) exactly as it was. */
static void check_fold_ignores_item_shown(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_all(t, ctx, "g67_balloon_ground");
    if (b == NULL) {
        return;
    }
    duoforge_battle *copy = malloc(sizeof *copy);
    if (!DF_CHECK(t, copy != NULL)) {
        duoforge_battle_destroy(b);
        return;
    }
    memcpy(copy, b, sizeof *copy);
    dfi_events ev;
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_ITEM_SHOWN, 2u);
    ev.rec[0].id2 = (uint16_t)(1u + DFI_ITEM_AIRBALLOON);
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, copy, &ev, 0u));
    DF_CHECK(t, memcmp(b, copy, sizeof *copy) == 0);
    free(copy);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.mechanics.item_shown_fold");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_fold_ignores_item_shown(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
