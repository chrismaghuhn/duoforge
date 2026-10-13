#include "combat/items/items.h"
#include "combat/damage_chain.h"

bool dfi_type_booster_base_power(const struct duoforge_battle *b, const dfi_member *a,
                                uint32_t move_type, bool ok, uint32_t *bp_chain)
{
    /* A type booster (the TYPE_BOOSTER family: Mystic Water, Miracle Seed
     * and the sixteen others, decision 0015): 4915/4096 for a move of its
     * type (onBasePowerPriority 15). */
    if (dfi_type_booster_applies(dfi_item_code(b, a), move_type)) {
        ok = ok && dfi_chain_modify(*bp_chain, DFI_TYPE_BOOSTER_MODIFIER, bp_chain);
    }
    return ok;
}

/* The turn has already decided whether this hit may eat the berry, including
 * Unnerve and Substitute. Its existing useItem path keeps all AfterUseItem
 * behavior, including Symbiosis, in the same order and on the same scratch. */
duoforge_status dfi_resist_berry_hit(dfi_run *r, uint32_t target, uint32_t berry_item,
                                   bool *ok, uint32_t *chain, uint32_t *mlist, uint32_t *mods,
                                   dfi_item_use_fn use_item)
{
    use_item(r, target); /* [-enditem] [eat] */
    duoforge_event weaken =
        dfi_ev(DUOFORGE_EVENT_ITEM_END, target, DUOFORGE_CAUSE_NONE, berry_item, DUOFORGE_NO_POSITION);
    weaken.detail = 1u;
    dfi_emit(r, &weaken); /* [-enditem] [weaken] */
    *ok = *ok && dfi_chain_modify(*chain, DFI_RESIST_BERRY_MODIFIER, chain);
    if (!dfi_mods_push(mlist, mods, DFI_RESIST_BERRY_MODIFIER)) {
        return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
    }
    return DUOFORGE_OK;
}
