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
           FIELD(duoforge_position_ext, reserved));
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
    STRUCT(duoforge_batch_config, false, FIELD(duoforge_batch_config, env_count),
           FIELD(duoforge_batch_config, worker_count), FIELD(duoforge_batch_config, seed),
           FIELD(duoforge_batch_config, setups));
    STRUCT(duoforge_batch_episode, true, FIELD(duoforge_batch_episode, env), FIELD(duoforge_batch_episode, episode),
           FIELD(duoforge_batch_episode, steps), FIELD(duoforge_batch_episode, decisions),
           FIELD(duoforge_batch_episode, turns), FIELD(duoforge_batch_episode, result),
           FIELD(duoforge_batch_episode, digest));
    printf("  },\n  \"constants\": {\n");
    CONSTANT(DUOFORGE_MAX_CANDIDATES, false);
    CONSTANT(DUOFORGE_MAX_SLOT_OPTIONS, false);
    CONSTANT(DUOFORGE_DIGEST_SIZE, false);
    CONSTANT(DUOFORGE_MAX_ROSTER, false);
    CONSTANT(DUOFORGE_SIDE_COUNT, false);
    CONSTANT(DUOFORGE_ACTIVE_PER_SIDE, false);
    CONSTANT(DUOFORGE_BATCH_NO_CHOICE, false);
    CONSTANT(DUOFORGE_DATA_KIND_CLOSURE, false);
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
    CONSTANT(DUOFORGE_E_INVALID_ARGUMENT, false);
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
    CONSTANT(DUOFORGE_WEATHER_NONE, false);
    CONSTANT(DUOFORGE_WEATHER_RAIN, false);
    CONSTANT(DUOFORGE_WEATHER_SUN, false);
    CONSTANT(DUOFORGE_WEATHER_SAND, false);
    CONSTANT(DUOFORGE_WEATHER_SNOW, false);
    CONSTANT(DUOFORGE_TERRAIN_NONE, false);
    CONSTANT(DUOFORGE_TERRAIN_GRASSY, false);
    CONSTANT(DUOFORGE_TERRAIN_PSYCHIC, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_FOLLOW_ME, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_HELPING_HAND, false);
    CONSTANT(DUOFORGE_POSITION_FLAG_UNBURDEN, false);
    CONSTANT(DUOFORGE_LOCATION_UNDETERMINED, false);
    CONSTANT(DUOFORGE_LOCATION_BENCH, false);
    CONSTANT(DUOFORGE_LOCATION_ACTIVE, false);
    CONSTANT(DUOFORGE_LOCATION_NOT_BROUGHT, false);
    CONSTANT(DUOFORGE_OBSERVATION_EXT_SIZE, false);
    CONSTANT(DUOFORGE_OBSERVATION_EXT_REVISION, true);
    printf("  }\n}\n");
    return 0;
}
