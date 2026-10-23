/*
 * duoforge.abilities.natural_cure (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), Natural Cure's
 * CURE_STATUS has cause ABILITY and id2 Natural Cure + 1 (a2a_cover_b step 2), and the observation digest's line schema accepts
 * it.
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

/* 6. Natural Cure's event (a2a_cover_b step 2: Pawmot, badly poisoned, switches out) and the digest's line schema. */
static void check_natural_cure_event(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("a2a_cover_b");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 2u)) {
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, 2u);
    if (b == NULL) {
        return;
    }
    static df_conf_run run;
    df_conf_run_step(ctx, b, &cb->steps[2], &run);
    DF_CHECK(t, run.status == DUOFORGE_OK);
    uint32_t found = 0u;
    for (uint32_t i = 0u; i < run.count; ++i) {
        const duoforge_event *e = &run.events[i];
        if (e->kind == DUOFORGE_EVENT_CURE_STATUS && e->cause == DUOFORGE_CAUSE_ABILITY) {
            found += 1u;
            DF_CHECK_EQ_U64(t, e->id2, AB(NATURALCURE));
            DF_CHECK_EQ_U64(t, e->detail, DUOFORGE_AILMENT_TOX);
            DF_CHECK_EQ_U64(t, e->flags, 0u); /* [silent]: no [msg] */
            uint8_t line[64];
            uint32_t size = 0u;
            DF_CHECK(t, dfi_observation_line_encode(e, NULL, line, (uint32_t)sizeof line, &size) == DUOFORGE_OK);
        }
    }
    DF_CHECK_EQ_U64(t, found, 1u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.natural_cure");
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_natural_cure_event(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
