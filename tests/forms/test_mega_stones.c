/*
 * duoforge.forms.mega_stones (white-box): the Mega Stones and the Megas they lead to. Step G63 of the content expansion
 * (decision 0015 entry 5bj): Garchompite, Steelixite, Slowbronite, Scolipite, Aggronite and Skarmorite are marked and take
 * their base forme to its Mega (the manifest and the tables); Heracronite (Skill Link) is not, because Skill Link is dropped
 * (no modelled multi-hit move is in Heracross's learnset). The stones of the other Mega batches join this file in restructure
 * step 6e.
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

/* The six stones are marked, Heracronite is not, and each stone takes its base forme to its Mega (the manifest and the tables). */
static void test_mega_stones_g63(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_GARCHOMPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STEELIXITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SLOWBRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SCOLIPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_AGGRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SKARMORITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_HERACRONITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u), DFI_FORME_GARCHOMPMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_STEELIX, DFI_ITEM_STEELIXITE + 1u), DFI_FORME_STEELIXMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SLOWBRO, DFI_ITEM_SLOWBRONITE + 1u), DFI_FORME_SLOWBROMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SCOLIPEDE, DFI_ITEM_SCOLIPITE + 1u), DFI_FORME_SCOLIPEDEMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_AGGRON, DFI_ITEM_AGGRONITE + 1u), DFI_FORME_AGGRONMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u), DFI_FORME_SKARMORYMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.forms.mega_stones");
    test_mega_stones_g63(&t);
    return df_test_end(&t);
}
