#ifndef DUOFORGE_COMBAT_FIELD_TERRAIN_H
#define DUOFORGE_COMBAT_FIELD_TERRAIN_H

/* Private field-family implementation. Included by turn.c at the
 * existing helper dependency boundary; turn flow owns evaluation order. */
#include "combat/run_internal.h"

/* isGrounded with the data (sim/pokemon.ts:2148-2160): an Iron Ball holder is grounded first (step G83: `if (item === 'ironball')
 * return true`, before the Flying and Levitate tests, so it is grounded whatever its types and ability); otherwise not a Flying
 * type, not a Levitate holder and not an Air Balloon holder (step G67: `return item !== 'airballoon'`, read live, so Knock Off
 * and Trick move it at once). Gravity, Ingrain, Smack Down, Magnet Rise and Telekinesis are unmarked rows, so no battle has
 * them; Eelevate is an unmarked ability. The ability is the current one (a Mega's, or one that Trace copied). Stealth Rock does
 * not read it (moves.ts:17814-17838). */
static bool dfi_grounded_test(const struct duoforge_battle *b, const dfi_member *m)
{
    if (dfi_holds(b, m, DFI_ITEM_IRONBALL)) {
        return true;
    }
    return !dfi_has_type(b, m, DFI_TYPE_FLYING) && !dfi_ability(b, m, DFI_ABILITY_LEVITATE) &&
           !dfi_holds(b, m, DFI_ITEM_AIRBALLOON);
}

/* Keep the hot entry point inline without duplicating the type/ability
 * accessor work inside every caller. The predicate above retains its body. */
static inline bool dfi_grounded(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_grounded_test(b, m);
}

/* The FIELD_START / FIELD_END detail of a terrain (DUOFORGE_FIELD_*). */
static inline uint32_t dfi_terrain_field_detail(uint32_t terrain)
{
    return terrain == DFI_TERRAIN_GRASSY     ? DUOFORGE_FIELD_GRASSY_TERRAIN
           : terrain == DFI_TERRAIN_PSYCHIC  ? DUOFORGE_FIELD_PSYCHIC_TERRAIN
           : terrain == DFI_TERRAIN_ELECTRIC ? DUOFORGE_FIELD_ELECTRIC_TERRAIN
                                             : DUOFORGE_FIELD_MISTY_TERRAIN;
}

#endif
