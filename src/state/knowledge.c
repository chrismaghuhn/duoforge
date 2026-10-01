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

void dfi_knowledge_see_hp(struct duoforge_battle *b, uint32_t side, uint32_t roster)
{
    const dfi_member *mem = &b->sides[side].members[roster];
    dfi_knowledge *k = &b->sides[1u - side].knowledge[roster];
    dfi_hp_display(mem->hp, mem->hp_max, &k->hp_percent, &k->hp_flag);
}

void dfi_knowledge_refresh_active(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER) {
                dfi_knowledge_see_hp(b, s, occupant);
            }
        }
    }
}
