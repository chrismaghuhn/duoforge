/*
 * duoforge.items.quick_claw_focus_band (white-box): scaffolded by tools/new_mechanic.py (items, quick_claw_focus_band).
 *
 * The mechanic's documentation is docs/mechanics/items/5eh-quick-claw-and-focus-band-draws.md; its Tests line names this test. Replace the placeholder below with the checks
 * that the recorded reference battles cannot show by themselves (marks, pinned rows, public values, refusals).
 */
#include <stdbool.h>
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "support/check.h"

/* The scaffold's placeholder: it fails until the mechanic's own checks replace it (tools/new_mechanic.py), so that an unfilled
 * scaffold never passes. */
static void check_placeholder(df_test *t)
{
    const bool mechanic_checks_written = false;
    if (!mechanic_checks_written) {
        fputs("scaffold of 5eh: write the mechanic's checks\n", stderr);
    }
    DF_CHECK(t, mechanic_checks_written);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.quick_claw_focus_band");
    check_placeholder(&t);
    return df_test_end(&t);
}
