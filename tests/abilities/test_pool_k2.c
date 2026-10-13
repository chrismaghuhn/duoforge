/*
 * duoforge.state.pool_k2 (white-box): step K2 of the content expansion (decision 0015, entry 5dd, issue #474), Piercing Drill.
 *
 * Piercing Drill (data/abilities.ts:3282-3294; the Champions mod inherits it, data/mods/champions/abilities.ts:59-62) marks the
 * holder's contact move through onHitProtect; checkMoveBypassesProtect (sim/battle.ts:1300-1309) then lets it through the
 * protections whose check calls it. The Champions modifyDamage (data/mods/champions/scripts.ts) multiplies that hit by 0.25 after
 * its ModifyDamage chain, and prints -ability and -zbroken. The engine row is in the generated handler column (DFI_HANDLER_NONE),
 * the bypass is src/combat/abilities/protect_bypass.h, and Excadrite is the stone that takes Excadrill to Excadrill-Mega.
 *
 * This file checks the marks, the stone link, the event kind of -zbroken (provisional number 51 until HS confirms it), and the
 * 0.25 modifier arithmetic (dfi_modify with 1024/4096). The battle behaviour is covered by the recorded battles of entry 5dd.
 */
#include <stddef.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "core/modifier.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "support/check.h"

/* Piercing Drill is an engine row (the handler NONE: the bypass is read by id in src/combat/turn.c), and the row is marked. */
static void test_piercing_drill_is_an_engine_row(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_PIERCINGDRILL] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_PIERCINGDRILL], DFI_HANDLER_NONE);
}

/* Excadrite is marked, and it takes the base Excadrill to Excadrill-Mega (the Mega carries Piercing Drill). */
static void test_excadrite_takes_excadrill_to_its_mega(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_EXCADRITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_EXCADRILL, DFI_ITEM_EXCADRITE + 1u), DFI_FORME_EXCADRILLMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_EXCADRILL, DFI_ITEM_EXCADRITE + 1u));
}

/* The -zbroken line's event kind: DUOFORGE_EVENT_PROTECT_BROKEN, the next free value after COPY_BOOST (provisional, decision 0015 5dd). */
static void test_protect_broken_event_kind(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_PROTECT_BROKEN, 51u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_PROTECT_BROKEN, DUOFORGE_EVENT_COPY_BOOST + 1u);
}

/* The bypassed hit's damage is modify(damage, 0.25) = tr((tr(value * 1024) + 2047) / 4096), so a .5 rounds down (102 -> 25) and
 * .25 and .75 round to the nearest (101 -> 25, 103 -> 26). Hand values: 100/4 = 25; 101/4 = 25.25; 102/4 = 25.5; 103/4 = 25.75;
 * 1000/4 = 250; 1/4 = 0.25. */
static void test_quarter_modifier_rounding(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_modify(100u, 1024u), 25u);
    DF_CHECK_EQ_U64(t, dfi_modify(101u, 1024u), 25u);
    DF_CHECK_EQ_U64(t, dfi_modify(102u, 1024u), 25u);
    DF_CHECK_EQ_U64(t, dfi_modify(103u, 1024u), 26u);
    DF_CHECK_EQ_U64(t, dfi_modify(1000u, 1024u), 250u);
    DF_CHECK_EQ_U64(t, dfi_modify(1u, 1024u), 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_k2");
    test_piercing_drill_is_an_engine_row(&t);
    test_excadrite_takes_excadrill_to_its_mega(&t);
    test_protect_broken_event_kind(&t);
    test_quarter_modifier_rounding(&t);
    return df_test_end(&t);
}
