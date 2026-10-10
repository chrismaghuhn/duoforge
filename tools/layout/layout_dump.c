/*
 * duoforge_layout_dump: the public struct layouts as JSON (M7, decision
 * 0013). Under "structs", for every struct the Python package mirrors as a
 * NumPy dtype, {"size": sizeof, "fields": {"name": [offsetof, sizeof]}};
 * under "constants", the values the package uses. The test
 * duoforge.python.layout requires both to match.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_batch.h>
#include <duoforge/duoforge_view.h>

typedef struct layout_field {
    const char *name;
    size_t offset;
    size_t size;
} layout_field;

#define FIELD(type, name) {#name, offsetof(type, name), sizeof(((type *)NULL)->name)}

static void dump(const char *name, size_t size, const layout_field *fields, size_t n, bool last)
{
    printf("    \"%s\": {\"size\": %llu, \"fields\": {", name, (unsigned long long)size);
    for (size_t i = 0u; i < n; ++i) {
        printf("%s\"%s\": [%llu, %llu]", i == 0u ? "" : ", ", fields[i].name, (unsigned long long)fields[i].offset,
               (unsigned long long)fields[i].size);
    }
    printf("}}%s\n", last ? "" : ",");
}

/* A block, not do-while (MSVC C4127 at /W4); used as a statement. */
#define STRUCT(type, last, ...)                                                    \
    {                                                                              \
        static const layout_field f_[] = {__VA_ARGS__};                            \
        dump(#type, sizeof(type), f_, sizeof f_ / sizeof f_[0], last);             \
    }

#define CONSTANT(name, last) printf("    \"%s\": %llu%s\n", #name, (unsigned long long)(name), (last) ? "" : ",")

int main(void)
{
    printf("{\n  \"structs\": {\n");
    STRUCT(duoforge_context_config, false, FIELD(duoforge_context_config, data_kind),
           FIELD(duoforge_context_config, max_roster), FIELD(duoforge_context_config, brought_count),
           FIELD(duoforge_context_config, species_count), FIELD(duoforge_context_config, move_count),
           FIELD(duoforge_context_config, move_target_classes));
    STRUCT(duoforge_move_setup, false, FIELD(duoforge_move_setup, move_id), FIELD(duoforge_move_setup, pp_max));
    STRUCT(duoforge_member_setup, false, FIELD(duoforge_member_setup, species_id),
           FIELD(duoforge_member_setup, hp_max), FIELD(duoforge_member_setup, move_count),
           FIELD(duoforge_member_setup, mega_capable), FIELD(duoforge_member_setup, moves),
           FIELD(duoforge_member_setup, gender), FIELD(duoforge_member_setup, nature),
           FIELD(duoforge_member_setup, stat_points), FIELD(duoforge_member_setup, ability),
           FIELD(duoforge_member_setup, item));
    STRUCT(duoforge_side_setup, false, FIELD(duoforge_side_setup, member_count), FIELD(duoforge_side_setup, members));
    STRUCT(duoforge_battle_setup, false, FIELD(duoforge_battle_setup, rng_initstate),
           FIELD(duoforge_battle_setup, rng_initseq), FIELD(duoforge_battle_setup, sides));
    STRUCT(duoforge_slot_command, false, FIELD(duoforge_slot_command, kind), FIELD(duoforge_slot_command, move_slot),
           FIELD(duoforge_slot_command, target), FIELD(duoforge_slot_command, mega),
           FIELD(duoforge_slot_command, reserve), FIELD(duoforge_slot_command, reserved));
    STRUCT(duoforge_side_choice, false, FIELD(duoforge_side_choice, epoch), FIELD(duoforge_side_choice, side),
           FIELD(duoforge_side_choice, kind), FIELD(duoforge_side_choice, pick_count),
           FIELD(duoforge_side_choice, picks), FIELD(duoforge_side_choice, reserved),
           FIELD(duoforge_side_choice, slots));
    STRUCT(duoforge_factored_domain, false, FIELD(duoforge_factored_domain, epoch),
           FIELD(duoforge_factored_domain, kind), FIELD(duoforge_factored_domain, slot_count),
           FIELD(duoforge_factored_domain, member_count), FIELD(duoforge_factored_domain, pick_count),
           FIELD(duoforge_factored_domain, reserved), FIELD(duoforge_factored_domain, slots),
           FIELD(duoforge_factored_domain, allowed));
    STRUCT(duoforge_factored_choice, false, FIELD(duoforge_factored_choice, slot),
           FIELD(duoforge_factored_choice, picks));
    STRUCT(duoforge_request, false, FIELD(duoforge_request, epoch), FIELD(duoforge_request, candidate_count),
           FIELD(duoforge_request, boundary_kind), FIELD(duoforge_request, player),
           FIELD(duoforge_request, requested), FIELD(duoforge_request, slot_mask));
    STRUCT(duoforge_step_result, false, FIELD(duoforge_step_result, epoch), FIELD(duoforge_step_result, kind),
           FIELD(duoforge_step_result, boundary_kind), FIELD(duoforge_step_result, request_mask),
           FIELD(duoforge_step_result, reserved));
    STRUCT(duoforge_member_view, false, FIELD(duoforge_member_view, species_id), FIELD(duoforge_member_view, hp),
           FIELD(duoforge_member_view, hp_max), FIELD(duoforge_member_view, move_ids),
           FIELD(duoforge_member_view, stats), FIELD(duoforge_member_view, pp), FIELD(duoforge_member_view, pp_max),
           FIELD(duoforge_member_view, stat_points), FIELD(duoforge_member_view, move_count),
           FIELD(duoforge_member_view, hp_kind), FIELD(duoforge_member_view, hp_flag),
           FIELD(duoforge_member_view, pp_kind), FIELD(duoforge_member_view, location),
           FIELD(duoforge_member_view, mega_capable), FIELD(duoforge_member_view, is_mega),
           FIELD(duoforge_member_view, gender), FIELD(duoforge_member_view, nature),
           FIELD(duoforge_member_view, ability), FIELD(duoforge_member_view, item),
           FIELD(duoforge_member_view, item_used), FIELD(duoforge_member_view, status),
           FIELD(duoforge_member_view, reserved));
    STRUCT(duoforge_position_view, false, FIELD(duoforge_position_view, stages),
           FIELD(duoforge_position_view, confused), FIELD(duoforge_position_view, charging),
           FIELD(duoforge_position_view, locked_slot), FIELD(duoforge_position_view, locked_target),
           FIELD(duoforge_position_view, acted), FIELD(duoforge_position_view, protect_chain),
           FIELD(duoforge_position_view, flash_fire), FIELD(duoforge_position_view, protecting),
           FIELD(duoforge_position_view, reserved));
    STRUCT(duoforge_side_view, false, FIELD(duoforge_side_view, members), FIELD(duoforge_side_view, positions),
           FIELD(duoforge_side_view, member_count), FIELD(duoforge_side_view, occupant),
           FIELD(duoforge_side_view, mega_used), FIELD(duoforge_side_view, brought_order),
           FIELD(duoforge_side_view, requested), FIELD(duoforge_side_view, requested_slots),
           FIELD(duoforge_side_view, reflect_turns), FIELD(duoforge_side_view, light_screen_turns),
           FIELD(duoforge_side_view, tailwind_turns), FIELD(duoforge_side_view, reserved));
    STRUCT(duoforge_observation, false, FIELD(duoforge_observation, epoch),
           FIELD(duoforge_observation, boundary_kind), FIELD(duoforge_observation, player),
           FIELD(duoforge_observation, requested), FIELD(duoforge_observation, slot_mask),
           FIELD(duoforge_observation, turn), FIELD(duoforge_observation, weather),
           FIELD(duoforge_observation, weather_turns), FIELD(duoforge_observation, terrain),
           FIELD(duoforge_observation, terrain_turns), FIELD(duoforge_observation, trick_room_turns),
           FIELD(duoforge_observation, reserved), FIELD(duoforge_observation, sides));
    STRUCT(duoforge_field_ext, false, FIELD(duoforge_field_ext, gravity_turns), FIELD(duoforge_field_ext, reserved));
    STRUCT(duoforge_position_ext, false, FIELD(duoforge_position_ext, volatiles),
           FIELD(duoforge_position_ext, ability_now), FIELD(duoforge_position_ext, type_now),
           FIELD(duoforge_position_ext, encore_slot), FIELD(duoforge_position_ext, disable_slot),
           FIELD(duoforge_position_ext, stockpile), FIELD(duoforge_position_ext, perish),
           FIELD(duoforge_position_ext, move_failed), FIELD(duoforge_position_ext, transform_source),
           FIELD(duoforge_position_ext, reserved));
    STRUCT(duoforge_mega_info, false, FIELD(duoforge_mega_info, base_species), FIELD(duoforge_mega_info, stone),
           FIELD(duoforge_mega_info, mega_species), FIELD(duoforge_mega_info, mega_ability),
           FIELD(duoforge_mega_info, supported));
    STRUCT(duoforge_member_ext, false, FIELD(duoforge_member_ext, forme), FIELD(duoforge_member_ext, item_now),
           FIELD(duoforge_member_ext, reserved));
    STRUCT(duoforge_side_ext, false, FIELD(duoforge_side_ext, positions), FIELD(duoforge_side_ext, members),
           FIELD(duoforge_side_ext, aurora_veil_turns), FIELD(duoforge_side_ext, stealth_rock),
           FIELD(duoforge_side_ext, spikes), FIELD(duoforge_side_ext, toxic_spikes),
           FIELD(duoforge_side_ext, sticky_web), FIELD(duoforge_side_ext, guard_flags),
           FIELD(duoforge_side_ext, reserved));
    STRUCT(duoforge_observation_ext, false, FIELD(duoforge_observation_ext, revision),
           FIELD(duoforge_observation_ext, player), FIELD(duoforge_observation_ext, reserved0),
           FIELD(duoforge_observation_ext, epoch), FIELD(duoforge_observation_ext, supported),
           FIELD(duoforge_observation_ext, field), FIELD(duoforge_observation_ext, sides),
           FIELD(duoforge_observation_ext, reserved1));
    STRUCT(duoforge_forme_info, false, FIELD(duoforge_forme_info, dex_num), FIELD(duoforge_forme_info, is_mega), FIELD(duoforge_forme_info, setup_legal), FIELD(duoforge_forme_info, base_species), FIELD(duoforge_forme_info, mega_species), FIELD(duoforge_forme_info, mega_stone), FIELD(duoforge_forme_info, mega_ability), FIELD(duoforge_forme_info, mega_supported), FIELD(duoforge_forme_info, gender_mask), FIELD(duoforge_forme_info, no_ability), FIELD(duoforge_forme_info, ability_count), FIELD(duoforge_forme_info, abilities), FIELD(duoforge_forme_info, move_count));
    STRUCT(duoforge_forme_static, false, FIELD(duoforge_forme_static, types), FIELD(duoforge_forme_static, base_stats), FIELD(duoforge_forme_static, weight_hg), FIELD(duoforge_forme_static, default_ability), FIELD(duoforge_forme_static, is_mega));
    STRUCT(duoforge_move_static, false, FIELD(duoforge_move_static, type), FIELD(duoforge_move_static, category), FIELD(duoforge_move_static, base_power), FIELD(duoforge_move_static, accuracy), FIELD(duoforge_move_static, pp), FIELD(duoforge_move_static, priority), FIELD(duoforge_move_static, target_class), FIELD(duoforge_move_static, flags), FIELD(duoforge_move_static, crit_stage), FIELD(duoforge_move_static, drain), FIELD(duoforge_move_static, recoil), FIELD(duoforge_move_static, secondary_chance), FIELD(duoforge_move_static, hits_min), FIELD(duoforge_move_static, hits_max));
    STRUCT(duoforge_item_static, false, FIELD(duoforge_item_static, family), FIELD(duoforge_item_static, family_type), FIELD(duoforge_item_static, is_mega_stone), FIELD(duoforge_item_static, mega_species));
    STRUCT(duoforge_ability_static, false, FIELD(duoforge_ability_static, family), FIELD(duoforge_ability_static, family_param));
    STRUCT(duoforge_nature_static, false, FIELD(duoforge_nature_static, raised_stat), FIELD(duoforge_nature_static, lowered_stat));
    STRUCT(duoforge_batch_config, false, FIELD(duoforge_batch_config, env_count),
           FIELD(duoforge_batch_config, worker_count), FIELD(duoforge_batch_config, seed),
           FIELD(duoforge_batch_config, setups));
    STRUCT(duoforge_batch_episode, false, FIELD(duoforge_batch_episode, env), FIELD(duoforge_batch_episode, episode),
           FIELD(duoforge_batch_episode, steps), FIELD(duoforge_batch_episode, decisions),
           FIELD(duoforge_batch_episode, turns), FIELD(duoforge_batch_episode, result),
           FIELD(duoforge_batch_episode, digest));
    STRUCT(duoforge_public_state, false, FIELD(duoforge_public_state, revision), FIELD(duoforge_public_state, player),
           FIELD(duoforge_public_state, state_size), FIELD(duoforge_public_state, boundary), FIELD(duoforge_public_state, turn),
           FIELD(duoforge_public_state, request_mask), FIELD(duoforge_public_state, epoch), FIELD(duoforge_public_state, foe_seen_mask),
           FIELD(duoforge_public_state, foe_leads), FIELD(duoforge_public_state, foe_pending_mask), FIELD(duoforge_public_state, queue_count),
           FIELD(duoforge_public_state, reserved), FIELD(duoforge_public_state, state), FIELD(duoforge_public_state, pad));
    STRUCT(duoforge_hypothesis, true, FIELD(duoforge_hypothesis, revision), FIELD(duoforge_hypothesis, reserved0),
           FIELD(duoforge_hypothesis, stat_points), FIELD(duoforge_hypothesis, pick_order), FIELD(duoforge_hypothesis, reserved1),
           FIELD(duoforge_hypothesis, hp), FIELD(duoforge_hypothesis, sleep), FIELD(duoforge_hypothesis, confusion),
           FIELD(duoforge_hypothesis, charge_target), FIELD(duoforge_hypothesis, queued), FIELD(duoforge_hypothesis, queue_order),
           FIELD(duoforge_hypothesis, reserved2));
    printf("  },\n  \"constants\": {\n");
    CONSTANT(DUOFORGE_VIEW_REVISION, false);
    CONSTANT(DUOFORGE_HYPOTHESIS_REVISION, false);
    CONSTANT(DUOFORGE_VIEW_STATE_MAX, false);
    CONSTANT(DUOFORGE_VIEW_HIDDEN, false);
    CONSTANT(DUOFORGE_VIEW_HIDDEN_TARGET, false);
    CONSTANT(DUOFORGE_VIEW_PICK_NONE, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_TEMP_FORME, false);
    CONSTANT(DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN, false);
    CONSTANT(DUOFORGE_MAX_CANDIDATES, false);
    CONSTANT(DUOFORGE_MAX_SLOT_OPTIONS, false);
    CONSTANT(DUOFORGE_DIGEST_SIZE, false);
    CONSTANT(DUOFORGE_MAX_ROSTER, false);
    CONSTANT(DUOFORGE_SIDE_COUNT, false);
    CONSTANT(DUOFORGE_ACTIVE_PER_SIDE, false);
    CONSTANT(DUOFORGE_BATCH_NO_CHOICE, false);
    CONSTANT(DUOFORGE_DATA_KIND_CLOSURE, false);
    CONSTANT(DUOFORGE_GENDER_MALE, false);
    CONSTANT(DUOFORGE_GENDER_FEMALE, false);
    CONSTANT(DUOFORGE_GENDER_NONE, false);
    CONSTANT(DUOFORGE_CHOICE_TEAM_SELECTION, false);
    CONSTANT(DUOFORGE_CHOICE_SLOTS, false);
    CONSTANT(DUOFORGE_BOUNDARY_TEAM_SELECTION, false);
    CONSTANT(DUOFORGE_BOUNDARY_TURN, false);
    CONSTANT(DUOFORGE_BOUNDARY_REPLACEMENT, false);
    CONSTANT(DUOFORGE_BOUNDARY_PIVOT, false);
    CONSTANT(DUOFORGE_BOUNDARY_TERMINAL, false);
    CONSTANT(DUOFORGE_RESULT_SIDE_0, false);
    CONSTANT(DUOFORGE_RESULT_SIDE_1, false);
    CONSTANT(DUOFORGE_RESULT_TIE, false);
    CONSTANT(DUOFORGE_SLOT_NONE, false);
    CONSTANT(DUOFORGE_SLOT_MOVE, false);
    CONSTANT(DUOFORGE_SLOT_SWITCH, false);
    CONSTANT(DUOFORGE_SLOT_PASS, false);
    CONSTANT(DUOFORGE_SLOT_REVIVE, false);
    CONSTANT(DUOFORGE_EVENT_REVIVE, false);
    CONSTANT(DUOFORGE_E_INVALID_ARGUMENT, false);
    CONSTANT(DUOFORGE_E_UNSUPPORTED, false);
    CONSTANT(DUOFORGE_BATCH_MAX_ENVS, false);
    CONSTANT(DUOFORGE_BATCH_AUTORESET, false);
    CONSTANT(DUOFORGE_ROSTER_NONE, false);
    CONSTANT(DUOFORGE_TARGET_NONE, false);
    CONSTANT(DUOFORGE_MOVE_SLOT_NONE, false);
    CONSTANT(DUOFORGE_MOVE_SLOT_STRUGGLE, false);
    CONSTANT(DUOFORGE_MOVE_SLOT_RECHARGE, false);
    CONSTANT(DUOFORGE_HP_EXACT, false);
    CONSTANT(DUOFORGE_HP_PERCENT, false);
    CONSTANT(DUOFORGE_AILMENT_NONE, false);
    CONSTANT(DUOFORGE_AILMENT_BURN, false);
    CONSTANT(DUOFORGE_AILMENT_FREEZE, false);
    CONSTANT(DUOFORGE_AILMENT_PARALYSIS, false);
    CONSTANT(DUOFORGE_AILMENT_SLEEP, false);
    CONSTANT(DUOFORGE_AILMENT_POISON, false);
    CONSTANT(DUOFORGE_AILMENT_TOX, false);
    CONSTANT(DUOFORGE_WEATHER_NONE, false);
    CONSTANT(DUOFORGE_WEATHER_RAIN, false);
    CONSTANT(DUOFORGE_WEATHER_SUN, false);
    CONSTANT(DUOFORGE_WEATHER_SAND, false);
    CONSTANT(DUOFORGE_WEATHER_SNOW, false);
    CONSTANT(DUOFORGE_TERRAIN_NONE, false);
    CONSTANT(DUOFORGE_TERRAIN_GRASSY, false);
    CONSTANT(DUOFORGE_TERRAIN_PSYCHIC, false);
    CONSTANT(DUOFORGE_TERRAIN_ELECTRIC, false);
    CONSTANT(DUOFORGE_TERRAIN_MISTY, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_FOLLOW_ME, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_HELPING_HAND, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_UNBURDEN, false);
    CONSTANT(DUOFORGE_LOCATION_UNDETERMINED, false);
    CONSTANT(DUOFORGE_LOCATION_BENCH, false);
    CONSTANT(DUOFORGE_LOCATION_ACTIVE, false);
    CONSTANT(DUOFORGE_LOCATION_NOT_BROUGHT, false);
    CONSTANT(DUOFORGE_EVENT_DRAG, false);
    CONSTANT(DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, false);
    CONSTANT(DUOFORGE_EVENT_SWAP, false);
    CONSTANT(DUOFORGE_EVENT_COPY_BOOST, false);
    CONSTANT(DUOFORGE_VOLATILE_SUBSTITUTE, false);
    CONSTANT(DUOFORGE_VOLATILE_DRAGONCHEER, false);
    CONSTANT(DUOFORGE_FAIL_SUBSTITUTE_EXISTS, false);
    CONSTANT(DUOFORGE_FAIL_SUBSTITUTE_WEAK, false);
    CONSTANT(DUOFORGE_OBSERVATION_EXT_SIZE, false);
    CONSTANT(DUOFORGE_OBSERVATION_EXT_REVISION, false);
    CONSTANT(DUOFORGE_POSITION_EXT_SUBSTITUTE, false);
    CONSTANT(DUOFORGE_POSITION_EXT_TAUNT, false);
    CONSTANT(DUOFORGE_POSITION_EXT_IMPRISON, false);
    CONSTANT(DUOFORGE_POSITION_EXT_LEECH_SEED, false);
    CONSTANT(DUOFORGE_POSITION_EXT_YAWN, false);
    CONSTANT(DUOFORGE_POSITION_EXT_FOCUS_ENERGY, false);
    CONSTANT(DUOFORGE_POSITION_EXT_DRAGON_CHEER, false);
    CONSTANT(DUOFORGE_POSITION_EXT_MUST_RECHARGE, false);
    CONSTANT(DUOFORGE_POSITION_EXT_PARTIAL_TRAP, false);
    CONSTANT(DUOFORGE_POSITION_EXT_GLAIVE_RUSH, false);
    CONSTANT(DUOFORGE_POSITION_EXT_DESTINY_BOND, false);
    CONSTANT(DUOFORGE_POSITION_EXT_CURSE, false);
    CONSTANT(DUOFORGE_POSITION_EXT_NO_RETREAT, false);
    CONSTANT(DUOFORGE_POSITION_EXT_SALT_CURE, false);
    CONSTANT(DUOFORGE_POSITION_EXT_CHARGE, false);
    CONSTANT(DUOFORGE_POSITION_EXT_HEAL_BLOCK, false);
    CONSTANT(DUOFORGE_POSITION_EXT_THROAT_CHOP, false);
    CONSTANT(DUOFORGE_POSITION_EXT_RAGE_POWDER, false);
    CONSTANT(DUOFORGE_POSITION_EXT_TYPE_CHANGED, false);
    CONSTANT(DUOFORGE_POSITION_EXT_ILLUSION_UP, false);
    CONSTANT(DUOFORGE_POSITION_EXT_ROOST, false);
    CONSTANT(DUOFORGE_POSITION_EXT_TRANSFORMED, false);
    CONSTANT(DUOFORGE_SIDE_GUARD_WIDE_GUARD, false);
    CONSTANT(DUOFORGE_SIDE_GUARD_QUICK_GUARD, false);
    CONSTANT(DUOFORGE_ITEM_NOW_NONE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_PERISH, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_ENCORE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_IMPRISON, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TAUNT, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_PARTIAL_TRAP, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_FORME_CHANGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_DISABLE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_STOCKPILE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_YAWN, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_ILLUSION, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_GRAVITY, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_LEECH_SEED, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_FOCUS_ENERGY, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_SPIKES, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_CHARGE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_SALT_CURE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_CURSE, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_NO_RETREAT, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_ROOST, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_MOVE_FAILED, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_TRANSFORM, false);
    CONSTANT(DUOFORGE_VIEWEXT_FEATURE_COUNT, false);
    CONSTANT(DUOFORGE_DATA_KIND_SYNTHETIC, false);
    CONSTANT(DUOFORGE_DATA_KIND_TEAM_C, false);
    CONSTANT(DUOFORGE_DATA_KIND_POOL, false);
    CONSTANT(DUOFORGE_DATA_TABLE_SPECIES, false);
    CONSTANT(DUOFORGE_DATA_TABLE_MOVE, false);
    CONSTANT(DUOFORGE_DATA_TABLE_ITEM, false);
    CONSTANT(DUOFORGE_DATA_TABLE_ABILITY, false);
    CONSTANT(DUOFORGE_DATA_TABLE_NATURE, false);
    CONSTANT(DUOFORGE_DATA_TABLE_COUNT, false);
    CONSTANT(DUOFORGE_DATA_NONE, false);
    CONSTANT(DUOFORGE_DATA_MAX_FORME_ABILITIES, false);
    CONSTANT(DUOFORGE_DATA_MAX_FORME_MOVES, false);
    CONSTANT(DUOFORGE_GENDER_BIT_MALE, false);
    CONSTANT(DUOFORGE_GENDER_BIT_FEMALE, false);
    CONSTANT(DUOFORGE_GENDER_BIT_NONE, false);
    CONSTANT(DUOFORGE_MOVE_CATEGORY_PHYSICAL, false);
    CONSTANT(DUOFORGE_MOVE_CATEGORY_SPECIAL, false);
    CONSTANT(DUOFORGE_MOVE_CATEGORY_STATUS, false);
    CONSTANT(DUOFORGE_TARGET_CLASS_STATIC_COUNT, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_CONTACT, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_SOUND, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_PUNCH, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_BITE, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_BULLET, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_PULSE, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_SLICING, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_WIND, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_DANCE, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_POWDER, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE, false);
    CONSTANT(DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE, false);
    CONSTANT(DUOFORGE_ITEM_FAMILY_NONE, false);
    CONSTANT(DUOFORGE_ITEM_FAMILY_TYPE_BOOSTER, false);
    CONSTANT(DUOFORGE_ITEM_FAMILY_RESIST_BERRY, false);
    CONSTANT(DUOFORGE_ABILITY_FAMILY_NONE, false);
    CONSTANT(DUOFORGE_ABILITY_FAMILY_ATE, false);
    CONSTANT(DUOFORGE_ABILITY_FAMILY_PINCH, false);
    CONSTANT(DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER, false);
    CONSTANT(DUOFORGE_ABILITY_FAMILY_TERRAIN_SETTER, false);
    CONSTANT(DUOFORGE_TYPE_BUG, false);
    CONSTANT(DUOFORGE_TYPE_DARK, false);
    CONSTANT(DUOFORGE_TYPE_DRAGON, false);
    CONSTANT(DUOFORGE_TYPE_ELECTRIC, false);
    CONSTANT(DUOFORGE_TYPE_FAIRY, false);
    CONSTANT(DUOFORGE_TYPE_FIGHTING, false);
    CONSTANT(DUOFORGE_TYPE_FIRE, false);
    CONSTANT(DUOFORGE_TYPE_FLYING, false);
    CONSTANT(DUOFORGE_TYPE_GHOST, false);
    CONSTANT(DUOFORGE_TYPE_GRASS, false);
    CONSTANT(DUOFORGE_TYPE_GROUND, false);
    CONSTANT(DUOFORGE_TYPE_ICE, false);
    CONSTANT(DUOFORGE_TYPE_NORMAL, false);
    CONSTANT(DUOFORGE_TYPE_POISON, false);
    CONSTANT(DUOFORGE_TYPE_PSYCHIC, false);
    CONSTANT(DUOFORGE_TYPE_ROCK, false);
    CONSTANT(DUOFORGE_TYPE_STEEL, false);
    CONSTANT(DUOFORGE_TYPE_WATER, false);
    CONSTANT(DUOFORGE_TYPE_NONE, true);
    printf("  }\n}\n");
    return 0;
}
