/* Independent witness from turn.c@657dae45, before generated dispatch tables.
 * Retained in test support only; never regenerate it from the new source rows. */
#ifndef DUOFORGE_TEST_SPECIAL_PREDICATES_H
#define DUOFORGE_TEST_SPECIAL_PREDICATES_H
#include <stdbool.h>
#include <stdint.h>
#include "data/pool_tables.h"
static inline bool df_test_old_special_guard(uint32_t special)
{
    return !(special > DFI_SPECIAL_STRUGGLE && special != DFI_SPECIAL_DARKEST_LARIAT &&
        special != DFI_SPECIAL_WILL_CRIT && special != DFI_SPECIAL_LAST_RESPECTS && special != DFI_SPECIAL_SUCKER_PUNCH &&
        special != DFI_SPECIAL_FIRST_IMPRESSION && special != DFI_SPECIAL_LOW_KICK &&
        special != DFI_SPECIAL_SOAK && special != DFI_SPECIAL_ENCORE && special != DFI_SPECIAL_DISABLE &&
        special != DFI_SPECIAL_KNOCK_OFF && special != DFI_SPECIAL_EXPANDING_FORCE &&
        special != DFI_SPECIAL_GLAIVE_RUSH && special != DFI_SPECIAL_ACROBATICS &&
        special != DFI_SPECIAL_BLIZZARD && special != DFI_SPECIAL_FEINT &&
        special != DFI_SPECIAL_STEEL_ROLLER && special != DFI_SPECIAL_BRICK_BREAK &&
        special != DFI_SPECIAL_PSYCHIC_FANGS && special != DFI_SPECIAL_SOLAR_BEAM &&
        special != DFI_SPECIAL_HP_POWER && special != DFI_SPECIAL_BODY_PRESS &&
        special != DFI_SPECIAL_FOUL_PLAY && special != DFI_SPECIAL_PSYSHOCK &&
        special != DFI_SPECIAL_FREEZE_DRY && special != DFI_SPECIAL_CLANGING_SCALES &&
        special != DFI_SPECIAL_RISING_VOLTAGE && special != DFI_SPECIAL_TERRAIN_PULSE &&
        special != DFI_SPECIAL_MULTI_HIT_2 && special != DFI_SPECIAL_TRIPLE_AXEL &&
        special != DFI_SPECIAL_DOUBLE_SHOCK &&
        special != DFI_SPECIAL_RAGE_FIST && special != DFI_SPECIAL_STONE_AXE &&
        special != DFI_SPECIAL_CEASELESS_EDGE && special != DFI_SPECIAL_MULTI_HIT_10 &&
        special != DFI_SPECIAL_IMPRISON && special != DFI_SPECIAL_TRICK && special != DFI_SPECIAL_SWITCHEROO &&
        special != DFI_SPECIAL_THIEF && special != DFI_SPECIAL_COVET && special != DFI_SPECIAL_SUPER_FANG &&
        special != DFI_SPECIAL_TAUNT && special != DFI_SPECIAL_YAWN &&
        special != DFI_SPECIAL_ROOST && special != DFI_SPECIAL_STOMPING_TANTRUM &&
        special != DFI_SPECIAL_POWER_TRIP && special != DFI_SPECIAL_THUNDER && special != DFI_SPECIAL_ICE_FANG &&
        special != DFI_SPECIAL_TRI_ATTACK && special != DFI_SPECIAL_LOCKED_MOVE &&
        special != DFI_SPECIAL_MULTI_HIT_2_5 &&
        special != DFI_SPECIAL_SCALE_SHOT && special != DFI_SPECIAL_QUICK_GUARD &&
        special != DFI_SPECIAL_UPPER_HAND && special != DFI_SPECIAL_HEAL_PULSE &&
        special != DFI_SPECIAL_STRENGTH_SAP && special != DFI_SPECIAL_POLTERGEIST &&
        special != DFI_SPECIAL_BEAT_UP && special != DFI_SPECIAL_SHEER_COLD &&
        special != DFI_SPECIAL_BUG_BITE && special != DFI_SPECIAL_AFTER_YOU &&
        special != DFI_SPECIAL_QUASH && special != DFI_SPECIAL_SUBSTITUTE && special != DFI_SPECIAL_PHANTOM_FORCE &&
        special != DFI_SPECIAL_STEEL_BEAM && special != DFI_SPECIAL_THUNDER_WAVE &&
        special != DFI_SPECIAL_SKILL_SWAP &&
        special != DFI_SPECIAL_ALLURING_VOICE && special != DFI_SPECIAL_DRAGON_CHEER &&
        special != DFI_SPECIAL_FINAL_GAMBIT && special != DFI_SPECIAL_ENDEAVOR &&
        special != DFI_SPECIAL_DRAGON_DARTS &&
        special != DFI_SPECIAL_LASH_OUT && special != DFI_SPECIAL_ASSURANCE &&
        special != DFI_SPECIAL_HEAVY_SLAM && special != DFI_SPECIAL_HARD_PRESS &&
        special != DFI_SPECIAL_ICE_SPINNER && special != DFI_SPECIAL_BELLY_DRUM &&
        special != DFI_SPECIAL_LEECH_SEED &&
        special != DFI_SPECIAL_CONFUSE && special != DFI_SPECIAL_OHKO &&
        special != DFI_SPECIAL_MEMENTO && special != DFI_SPECIAL_LEVEL_DAMAGE &&
        special != DFI_SPECIAL_PARTIAL_TRAP &&
        special != DFI_SPECIAL_PSYCH_UP && special != DFI_SPECIAL_ALLY_SWITCH &&
        special != DFI_SPECIAL_PSYCHIC_TERRAIN && special != DFI_SPECIAL_SPEED_SWAP); /* K3 (decision 0015 5de) */
}
static inline bool df_test_old_status_hit(uint32_t special)
{
    return special == DFI_SPECIAL_PARTING_SHOT || special == DFI_SPECIAL_SPEED_SWAP || /* K3 (decision 0015 5de): a status move */
           special == DFI_SPECIAL_STRENGTH_SAP ||
           special == DFI_SPECIAL_HEAL_PULSE ||
           special == DFI_SPECIAL_SOAK ||
           special == DFI_SPECIAL_ENCORE ||
           special == DFI_SPECIAL_DISABLE ||
           special == DFI_SPECIAL_AFTER_YOU ||
           special == DFI_SPECIAL_QUASH ||
           special == DFI_SPECIAL_TRICK ||
           special == DFI_SPECIAL_SWITCHEROO ||
           special == DFI_SPECIAL_SKILL_SWAP ||
           special == DFI_SPECIAL_TAUNT ||
           special == DFI_SPECIAL_YAWN ||
           special == DFI_SPECIAL_DRAGON_CHEER ||
           special == DFI_SPECIAL_PSYCH_UP ||
           special == DFI_SPECIAL_ALLY_SWITCH ||
           special == DFI_SPECIAL_LEECH_SEED ||
           special == DFI_SPECIAL_CONFUSE;
}
#endif
