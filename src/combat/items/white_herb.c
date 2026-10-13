#include "combat/items/items.h"

/* White Herb's check (onStart, data/items.ts): its standing holder has a
 * lowered stat. */
bool dfi_herb_due(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u || !dfi_holds(b, m, DFI_ITEM_WHITEHERB)) {
        return false;
    }
    const dfi_active_slot *pos = dfi_pos(b, flat);
    bool lowered = false;
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        lowered = lowered || pos->stages[i] < DFI_STAGE_NEUTRAL;
    }
    return lowered;
}

/* White Herb (Team C, data/items.ts): when it is due, its holder uses it:
 * [-enditem], then the lowered stages go back to 0 ([-clearnegativeboost]
 * is [silent]), then AfterUseItem (Unburden). */
void dfi_white_herb(dfi_run *r, uint32_t flat, dfi_item_use_fn use_item)
{
    if (!dfi_herb_due(r->b, flat)) {
        return;
    }
    use_item(r, flat);
    dfi_active_slot *pos = dfi_pos(r->b, flat);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        if (pos->stages[i] < DFI_STAGE_NEUTRAL) {
            pos->stages[i] = (uint8_t)DFI_STAGE_NEUTRAL;
        }
    }
}

/* A standing Pokemon whose White Herb is unused: it has the herb's
 * handlers (side.allies() keeps only Pokemon with HP). */
bool dfi_herb_holder(struct duoforge_battle *b, uint32_t flat)
{
    const dfi_member *m = dfi_at(b, flat);
    return m != NULL && m->hp != 0u && dfi_holds(b, m, DFI_ITEM_WHITEHERB);
}
