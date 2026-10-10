/*
 * duoforge.state.pool_g82 (white-box): Healing Wish (decision 0045, step G82). Position bit 0 is the slot's wish: the occupant's
 * clear (a switch-out, a replacement's entry) keeps it and ends the other bits with the occupant; the heal of the entrant is a HEAL
 * event with cause MOVE and the move id, which the foe sees as a percentage like every heal (decision 0007); the view bit and its
 * feature are the manifest's and the public values of the header (0x00400000, feature 43, count 44).
 */
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/identity.h"
#include "state/knowledge.h"
#include "support/check.h"

/* The heal of an entrant (side 0, position 2, full HP): the owner's copy is exact and unchanged, the foe's is a percentage. */
static void test_heal_projection(df_test *t)
{
    duoforge_event in;
    memset(&in, 0, sizeof in);
    in.kind = DUOFORGE_EVENT_HEAL;
    in.position = 2u;
    in.id = 0u;
    in.hp = 170u;
    in.hp_max = 170u;
    in.hp_kind = DUOFORGE_HP_EXACT;
    in.cause = DUOFORGE_CAUSE_MOVE;
    in.id2 = DFI_MOVE_HEALINGWISH;

    duoforge_event own;
    dfi_event_project(&in, 0u, &own);
    DF_CHECK(t, memcmp(&own, &in, sizeof own) == 0);

    uint8_t percent = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(170u, 170u, &percent, &flag);
    duoforge_event foe;
    dfi_event_project(&in, 1u, &foe);
    DF_CHECK_EQ_U64(t, foe.hp_kind, DUOFORGE_HP_PERCENT);
    DF_CHECK_EQ_U64(t, foe.hp_max, 100u);
    DF_CHECK_EQ_U64(t, foe.hp, percent);
    DF_CHECK_EQ_U64(t, foe.cause, DUOFORGE_CAUSE_MOVE);
    DF_CHECK_EQ_U64(t, foe.id2, DFI_MOVE_HEALINGWISH);
}

/* Bit 0 is the slot's: the occupant's clear keeps it (a switch-out or the replacement's entry, identity.c), and the other bits
 * (the raised flag, bit 1) end with the occupant as before. */
static void test_wish_kept_by_occupant_clear(df_test *t)
{
    static duoforge_battle b;
    memset(&b, 0, sizeof b);
    dfi_tail_pos *p = &b.tail.sides[0].positions[1];
    p->position_flags = (uint8_t)(DFI_POSFLAG_HEALING_WISH | DFI_POSFLAG_STATS_RAISED);
    b.sides[0].positions[1].occupant = 0u;
    dfi_tail_clear_occupant(&b, 1u);
    DF_CHECK_EQ_U64(t, p->position_flags, DFI_POSFLAG_HEALING_WISH);
    /* the replacement's entry clears the position again: the wish still waits */
    dfi_tail_clear_occupant(&b, 1u);
    DF_CHECK_EQ_U64(t, p->position_flags, DFI_POSFLAG_HEALING_WISH);
    /* a position without the wish ends with its occupant as before */
    b.tail.sides[0].positions[0].position_flags = DFI_POSFLAG_STATS_RAISED;
    dfi_tail_clear_occupant(&b, 0u);
    DF_CHECK_EQ_U64(t, b.tail.sides[0].positions[0].position_flags, 0u);
}

/* The public values: the view bit 0x00400000 (decision 0045), the feature 43 in the manifest, and the feature count 44. */
static void test_public_values(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_POSITION_EXT_HEALING_WISH, 0x00400000u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH, 43u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_COUNT, 44u);
    DF_CHECK(t, ((dfi_support.view_ext_features >> DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH) & 1u) == 1u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g82");
    test_heal_projection(&t);
    test_wish_kept_by_occupant_clear(&t);
    test_public_values(&t);
    return df_test_end(&t);
}
