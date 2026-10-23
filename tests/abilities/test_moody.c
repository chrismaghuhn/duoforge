/*
 * duoforge.state.pool_g73 (white-box): step G73 of the content expansion (decision 0015, item 5bo), Moody, POOL build.
 *
 * Moody (data/abilities.ts:2701-2734) is an engine row read by id in combat/turn.c (dfi_moody):
 *   - the residual entry of order 28, sub-order 2, the key of Speed Boost (DFI_RES_MOODY, a callback);
 *   - two samples on DFI_SITE_MOODY (23): the stats below +6 (accuracy and evasion left out), then the stats above -6 and not
 *     the raised one; an empty list draws nothing, a list of one draws (random(1));
 *   - one boost {raised +2, lowered -1}, the raised key first (positives_first in dfi_boost_effect).
 *
 * The behaviour is checked by the recorded battles (g73_* under "data": "pool") that duoforge.reference.conformance_pool_data
 * replays against the reference, including the fainted holder's residual (g73_moody_faint_turn: no draw, no line) and the
 * residual faint by poison (g73_moody_residual_faint). A start state with the holder's stages set directly is not built here:
 * the turn step refuses such a state (see the 5bo entry), so the four-stats-at-+6 draw count is a known gap.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/residual_order.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MOODY] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOODY], DFI_HANDLER_NONE); /* an engine row: read by id */
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_MOODY].family, DFI_ABILITY_FAMILY_NONE);
    /* Opportunist copies a foe's rise (onFoeAfterBoost, data/abilities.ts:3042): not marked, UNMODELLED, so it is refused */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_OPPORTUNIST], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_OPPORTUNIST], DFI_HANDLER_UNMODELED);
    /* the draw site of Moody's samples, and the count of the sites after it */
    DF_CHECK_EQ_U64(t, DFI_SITE_MOODY, 23u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 34u); /* G73 Moody (site 23), G80 Ally Switch (site 33) */
    /* the residual kind of the entry (after the kinds of residual_order.h before it) */
    DF_CHECK_EQ_U64(t, DFI_RES_MOODY, 18u);
}

/* ---- the recorded battles of this step are in the conformance table (their names are the spec names) */
static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void check_battles_present(df_test *t)
{
    static const char *const names[] = {"g73_moody_turns", "g73_moody_white_herb", "g73_moody_speed_tie", "g73_moody_faint_turn",
                                        "g73_moody_residual_faint"};
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        DF_CHECK(t, find(names[i]) != NULL);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g73");
    check_facts(&t);
    check_battles_present(&t);
    return df_test_end(&t);
}
