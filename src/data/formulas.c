#include "data/formulas.h"

#include "core/arith.h"
#include "data/closure_tables.h"

bool dfi_champions_stat(uint32_t stat, uint32_t base, uint32_t stat_points, uint32_t nature, uint16_t *out)
{
    if (stat >= DFI_STAT_COUNT || base < 1u || base > 255u || stat_points > DFI_STAT_POINTS_MAX ||
        nature >= DFI_NATURE_COUNT) {
        return false;
    }
    uint32_t value = 0u;
    if (stat == DFI_STAT_HP) {
        value = base + stat_points + 75u;
    } else {
        value = base + stat_points + 20u;
        /* The reference truncates stat * 110 (or * 90) to 16 bits before the
         * division. With base <= 255 the product is at most 33,770, so that
         * truncation can never change the value; reject instead of wrapping
         * if the bounds above are ever widened. */
        const dfi_nature_data *n = &dfi_closure_natures[nature];
        if (n->plus == stat) {
            if (value * 110u > UINT16_MAX) {
                return false;
            }
            value = (value * 110u) / 100u;
        } else if (n->minus == stat) {
            value = (value * 90u) / 100u;
        }
    }
    return dfi_u32_to_u16(value, out);
}

bool dfi_champions_pp_max(uint32_t pp_base, bool no_pp_boosts, uint8_t *out)
{
    if (pp_base < 1u || pp_base > 255u) {
        return false;
    }
    const uint32_t capped = pp_base > DFI_PP_CAP ? DFI_PP_CAP : pp_base;
    if (no_pp_boosts) {
        return dfi_u32_to_u8(capped, out);
    }
    if (capped % 5u != 0u) {
        return false;
    }
    return dfi_u32_to_u8((capped / 5u + 1u) * 4u, out);
}
