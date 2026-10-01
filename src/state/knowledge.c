#include "state/knowledge.h"

void dfi_hp_display(uint32_t hp, uint32_t hp_max, uint8_t *out_percent, uint8_t *out_flag)
{
    *out_flag = (uint8_t)DUOFORGE_HP_FLAG_NONE;
    *out_percent = 0u;
    if (hp == 0u || hp_max == 0u) {
        return;
    }
    uint32_t pct = (100u * hp) / hp_max; /* hp <= 65535: no overflow */
    if (pct == 0u) {
        pct = 1u;
    }
    if (pct > 100u) {
        pct = 100u; /* corrupt state only (hp > hp_max) */
    }
    uint32_t flag = DUOFORGE_HP_FLAG_NONE;
    if (pct == 20u) {
        flag = hp * 5u > hp_max ? DUOFORGE_HP_FLAG_YELLOW : DUOFORGE_HP_FLAG_RED;
    } else if (pct == 50u) {
        flag = hp * 2u > hp_max ? DUOFORGE_HP_FLAG_GREEN : DUOFORGE_HP_FLAG_YELLOW;
    }
    *out_flag = (uint8_t)flag;
    *out_percent = (uint8_t)pct; /* <= 100 */
}

bool dfi_hp_display_valid(uint32_t percent, uint32_t flag)
{
    if (percent > 100u) {
        return false;
    }
    if (percent == 20u) {
        return flag == DUOFORGE_HP_FLAG_RED || flag == DUOFORGE_HP_FLAG_YELLOW;
    }
    if (percent == 50u) {
        return flag == DUOFORGE_HP_FLAG_YELLOW || flag == DUOFORGE_HP_FLAG_GREEN;
    }
    return flag == DUOFORGE_HP_FLAG_NONE;
}
