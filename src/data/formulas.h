#ifndef DUOFORGE_DATA_FORMULAS_H
#define DUOFORGE_DATA_FORMULAS_H
/*
 * Champions stat and PP formulas (docs/decisions/0006 section 2), read at the
 * pinned reference: data/mods/champions/scripts.ts:3-9 (PP cap), :10-40
 * (statModify, the branch without Level Clause Mod) and :41-43
 * (calculatePP). Level and IVs do not enter the stat formula.
 *
 * Fallible helpers return true on success; on failure *out is untouched.
 */
#include <stdbool.h>
#include <stdint.h>

#define DFI_STAT_POINTS_MAX 32u       /* per stat */
#define DFI_STAT_POINTS_TOTAL_MAX 66u /* per set (validator, EV Limit Auto) */
#define DFI_PP_CAP 20u

/* stat: DFI_STAT_*; base: 1..255; stat_points: 0..32; nature: < DFI_NATURE_COUNT.
 *   HP    = base + stat_points + 75
 *   other = base + stat_points + 20, then x110/100 or x90/100 (truncated)
 *           when the nature raises or lowers that stat. */
bool dfi_champions_stat(uint32_t stat, uint32_t base, uint32_t stat_points, uint32_t nature, uint16_t *out);

/* Maximum PP: the base value is capped at 20; then (pp / 5 + 1) * 4, or the
 * capped value itself for a move without PP boosts (Struggle). A capped
 * value that is not a multiple of 5 is rejected. */
bool dfi_champions_pp_max(uint32_t pp_base, bool no_pp_boosts, uint8_t *out);

#endif
