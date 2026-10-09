/*
 * duoforge.state.pool_g52 (white-box): Revival Blessing's REVIVE event and the information boundary (decision 0025 items 6
 * to 10; decision 0007). The owner's copy of a REVIVE keeps the member's exact HP; the foe's copy is a percentage with
 * hp_max 100 and hp_flag, like the HEAL and SWITCH lines, and never carries the exact value.
 */
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "state/knowledge.h"
#include "support/check.h"

/* The owner (side 0) revives a member of its own side: the position is the user's, the id the roster index. */
static void test_projection(df_test *t)
{
    duoforge_event in;
    memset(&in, 0, sizeof in);
    in.kind = DUOFORGE_EVENT_REVIVE;
    in.position = 0u;
    in.id = 2u;
    in.hp = 85u;
    in.hp_max = 170u;
    in.hp_kind = DUOFORGE_HP_EXACT;
    in.cause = DUOFORGE_CAUSE_MOVE;
    in.id2 = 374u; /* Revival Blessing */

    /* the owner's copy: unchanged, exact */
    duoforge_event own;
    dfi_event_project(&in, 0u, &own);
    DF_CHECK(t, memcmp(&own, &in, sizeof own) == 0);
    DF_CHECK_EQ_U64(t, own.hp_kind, DUOFORGE_HP_EXACT);
    DF_CHECK_EQ_U64(t, own.hp, 85u);

    /* the foe's copy: a percentage, the same display as every heal of the foe shows (decision 0007) */
    uint8_t percent = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(85u, 170u, &percent, &flag);
    duoforge_event foe;
    dfi_event_project(&in, 1u, &foe);
    DF_CHECK_EQ_U64(t, foe.hp_kind, DUOFORGE_HP_PERCENT);
    DF_CHECK_EQ_U64(t, foe.hp_max, 100u);
    DF_CHECK_EQ_U64(t, foe.hp, percent);
    DF_CHECK_EQ_U64(t, foe.hp_flag, flag);
    DF_CHECK(t, foe.hp != in.hp); /* the exact HP (85 of 170) is not in the foe's copy */
    DF_CHECK_EQ_U64(t, foe.position, 0u);
    DF_CHECK_EQ_U64(t, foe.id, 2u);
    DF_CHECK_EQ_U64(t, foe.cause, DUOFORGE_CAUSE_MOVE);
    DF_CHECK_EQ_U64(t, foe.id2, 374u);

    /* a revive on the foe's side is the mirror image: the foe owns it, the viewer 0 sees a percentage */
    duoforge_event mirror = in;
    mirror.position = 3u;
    duoforge_event seen_by_0;
    dfi_event_project(&mirror, 0u, &seen_by_0);
    DF_CHECK_EQ_U64(t, seen_by_0.hp_kind, DUOFORGE_HP_PERCENT);
    DF_CHECK_EQ_U64(t, seen_by_0.hp_max, 100u);
    duoforge_event seen_by_1;
    dfi_event_project(&mirror, 1u, &seen_by_1);
    DF_CHECK_EQ_U64(t, seen_by_1.hp_kind, DUOFORGE_HP_EXACT);
    DF_CHECK_EQ_U64(t, seen_by_1.hp, 85u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g52");
    test_projection(&t);
    return df_test_end(&t);
}
