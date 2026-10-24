/*
 * duoforge.abilities.stalwart (white-box): step G63 of the content expansion (decision 0015 entry 5bj), the one fact that
 * Stalwart's redirection rule depends on: no marked move has the scripted target class. Stalwart does not change a scripted
 * move's target at the pin, and the engine's redirection only runs for the single-target classes; a marked scripted move would
 * need its own case (E_UNSUPPORTED for a Stalwart holder), so this check fails first if one is marked.
 *
 * Split by subject from the test of step G63 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "support/check.h"

/* Stalwart (the redirection of the holder's moves is skipped for the single-target classes only): no marked move has the scripted
 * target class, so a scripted move never meets the rule. A marked scripted move would need its own case (E_UNSUPPORTED for a
 * Stalwart holder), so this check fails first if one is marked. */
static void test_no_marked_scripted_move(df_test *t)
{
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        if (dfi_support.moves[id] == 0u) {
            continue;
        }
        DF_CHECK(t, dfi_pool_moves[id].target_class != DFI_TARGET_CLASS_SCRIPTED);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.stalwart");
    test_no_marked_scripted_move(&t);
    return df_test_end(&t);
}
