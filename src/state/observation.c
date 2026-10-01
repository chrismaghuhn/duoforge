/*
 * Observation v2: what a player sees (docs/decisions/0007). The record for
 * player p is built from
 *  - p's own side, exactly, except what the game never shows (sleep,
 *    freeze and confusion turns);
 *  - the open team sheets of both sides (species, gender, nature, ability,
 *    item, moves and their maximum PP, the stone);
 *  - public facts of the battle: occupancy, statuses, stat stages,
 *    volatile conditions that the game announces, field and side
 *    conditions with their remaining turns, Mega Evolution, who must answer;
 *  - p's knowledge of the opponent: the seen mask, the HP display p saw
 *    last, the items p saw used up, the Mega Evolutions p saw, and the move
 *    uses p saw (the foe's PP is derived from them).
 * The opponent's exact HP and PP, its bench order and pick order, its
 * sealed commitments, the target of its charged move and the RNG are never
 * read here.
 */
#include <stddef.h>
#include <string.h>

#include "core/arith.h"
#include "data/closure_tables.h"
#include "data/extended_tables.h"
#include "state/battle_internal.h"
#include "state/context_internal.h"
#include "state/invariants.h"

_Static_assert(sizeof(duoforge_member_view) == 52u, "member view is 52 bytes");
_Static_assert(offsetof(duoforge_member_view, move_ids) == 6u, "member view layout: move ids");
_Static_assert(offsetof(duoforge_member_view, stats) == 14u, "member view layout: stats");
_Static_assert(offsetof(duoforge_member_view, pp) == 24u, "member view layout: pp");
_Static_assert(offsetof(duoforge_member_view, pp_max) == 28u, "member view layout: pp max");
_Static_assert(offsetof(duoforge_member_view, stat_points) == 32u, "member view layout: stat points");
_Static_assert(offsetof(duoforge_member_view, mega_capable) == 43u, "member view layout: mega");
_Static_assert(offsetof(duoforge_member_view, status) == 50u, "member view layout: status");
_Static_assert(sizeof(duoforge_position_view) == 16u, "position view is 16 bytes");
_Static_assert(offsetof(duoforge_position_view, protecting) == 14u, "position view layout: protecting");
_Static_assert(sizeof(duoforge_side_view) == 360u, "side view is 360 bytes");
_Static_assert(offsetof(duoforge_side_view, positions) == 312u, "side view layout: positions");
_Static_assert(offsetof(duoforge_side_view, member_count) == 344u, "side view layout: count");
_Static_assert(offsetof(duoforge_side_view, brought_order) == 348u, "side view layout: order");
_Static_assert(offsetof(duoforge_side_view, requested) == 354u, "side view layout: requested");
_Static_assert(sizeof(duoforge_observation) == 736u, "observation is 736 bytes");
_Static_assert(DFI_MEMBER_STAT_COUNT == 5u && DFI_STAT_POINT_COUNT == 6u, "view stat arrays");
_Static_assert(offsetof(duoforge_observation, turn) == 8u, "observation layout: turn");
_Static_assert(offsetof(duoforge_observation, sides) == 16u, "observation layout: sides");
_Static_assert(DUOFORGE_AILMENT_BURN == DFI_STATUS_BRN && DUOFORGE_AILMENT_FREEZE == DFI_STATUS_FRZ &&
                   DUOFORGE_AILMENT_PARALYSIS == DFI_STATUS_PAR && DUOFORGE_AILMENT_SLEEP == DFI_STATUS_SLP &&
                   DUOFORGE_AILMENT_POISON == DFI_STATUS_PSN,
               "public ailments are the internal statuses");
_Static_assert(DUOFORGE_WEATHER_RAIN == DFI_WEATHER_RAIN && DUOFORGE_WEATHER_SUN == DFI_WEATHER_SUN &&
                   DUOFORGE_TERRAIN_GRASSY == DFI_TERRAIN_GRASSY,
               "public field values are the internal ones");

static bool dfi_is_occupant(const dfi_side *side, uint32_t m)
{
    return side->positions[0].occupant == m || side->positions[1].occupant == m;
}

/* A foe's PP as the viewer can count it: the maximum (open) minus the uses
 * the viewer saw (decision 0007 point A). */
static uint8_t dfi_derived_pp(uint32_t pp_max, uint32_t used)
{
    const uint32_t left = used < pp_max ? pp_max - used : 0u;
    return (uint8_t)left; /* <= pp_max < 256 */
}

static void dfi_view_member(const struct duoforge_battle *b, uint32_t viewer, uint32_t s, uint32_t m,
                            duoforge_member_view *v)
{
    const dfi_side *side = &b->sides[s];
    const dfi_member *mem = &side->members[m];
    const bool own = s == viewer;
    /* The open team sheet. */
    v->species_id = mem->species_id;
    v->move_count = mem->move_count;
    v->mega_capable = mem->mega_capable;
    v->gender = mem->gender;
    v->nature = mem->nature;
    v->ability = mem->ability; /* the current one: a Mega Evolution is public */
    v->item = mem->item;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        v->move_ids[k] = mem->moves[k].move_id;
        v->pp_max[k] = mem->moves[k].pp_max;
    }
    if (own) {
        v->hp = mem->hp;
        v->hp_max = mem->hp_max;
        v->hp_kind = (uint8_t)DUOFORGE_HP_EXACT;
        v->pp_kind = (uint8_t)DUOFORGE_PP_EXACT;
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            v->pp[k] = mem->moves[k].pp;
        }
        for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
            v->stats[i] = mem->stats[i]; /* the player's own sheet and stats */
        }
        for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
            v->stat_points[i] = mem->stat_points[i];
        }
        v->is_mega = mem->is_mega;
        v->item_used = mem->item_consumed;
        v->status = mem->hp != 0u ? mem->status : (uint8_t)DUOFORGE_AILMENT_NONE;
        if (b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
            v->location = (uint8_t)DUOFORGE_LOCATION_UNDETERMINED;
        } else if (dfi_is_occupant(side, m)) {
            v->location = (uint8_t)DUOFORGE_LOCATION_ACTIVE;
        } else if ((((uint32_t)side->brought_mask >> m) & 1u) != 0u) {
            v->location = (uint8_t)DUOFORGE_LOCATION_BENCH;
        } else {
            v->location = (uint8_t)DUOFORGE_LOCATION_NOT_BROUGHT;
        }
        return;
    }
    const dfi_knowledge *know = &b->sides[viewer].knowledge[m];
    v->pp_kind = (uint8_t)DUOFORGE_PP_DERIVED;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        v->pp[k] = dfi_derived_pp(mem->moves[k].pp_max, know->moves_used[k]);
    }
    v->is_mega = ((uint32_t)know->revealed & DFI_REVEALED_MEGA) != 0u ? 1u : 0u;
    v->item_used = ((uint32_t)know->revealed & DFI_REVEALED_ITEM_CONSUMED) != 0u ? 1u : 0u;
    if ((((uint32_t)b->sides[viewer].seen_mask >> m) & 1u) != 0u) {
        v->hp = know->hp_percent;
        v->hp_flag = know->hp_flag;
        v->hp_max = 100u;
        v->hp_kind = (uint8_t)DUOFORGE_HP_PERCENT;
        v->location = dfi_is_occupant(side, m) ? (uint8_t)DUOFORGE_LOCATION_ACTIVE : (uint8_t)DUOFORGE_LOCATION_BENCH;
        /* A status is announced when it starts and when it ends, so the
         * current one is the one shown (read from the state like the
         * ability, which changes only by a Mega Evolution, always shown:
         * an invariant ties is_mega to the revealed fact); a fainted member
         * shows none. */
        v->status = know->hp_percent != 0u ? mem->status : (uint8_t)DUOFORGE_AILMENT_NONE;
    } else {
        v->hp_kind = (uint8_t)DUOFORGE_HP_UNKNOWN;
        v->location = (uint8_t)DUOFORGE_LOCATION_UNDETERMINED;
    }
}

/* An active position: stat stages and the volatile conditions the game
 * announces. Hidden: confusion turns (both sides) and the foe's locked
 * target. */
static void dfi_view_position(const struct duoforge_battle *b, uint32_t viewer, uint32_t s, uint32_t p,
                              duoforge_position_view *out)
{
    const dfi_active_slot *slot = &b->sides[s].positions[p];
    out->locked_slot = (uint8_t)DUOFORGE_MOVE_SLOT_NONE;
    out->locked_target = (uint8_t)DUOFORGE_TARGET_NONE;
    if (slot->occupant == DFI_OCCUPANT_NONE) {
        for (uint32_t i = 0u; i < 7u; ++i) {
            out->stages[i] = (uint8_t)DFI_STAGE_NEUTRAL; /* empty: nothing raised or lowered */
        }
        return;
    }
    for (uint32_t i = 0u; i < 7u; ++i) {
        out->stages[i] = slot->stages[i];
    }
    out->confused = slot->confusion_turns != 0u ? 1u : 0u;
    out->charging = slot->charge_turns != 0u ? 1u : 0u;
    const uint32_t locked_index = slot->locked_move != 0u ? (uint32_t)slot->locked_move - 1u : DUOFORGE_MOVE_SLOT_NONE;
    out->locked_slot = (uint8_t)locked_index; /* <= 0xFF */
    if (slot->charge_turns != 0u && s == viewer) {
        out->locked_target = slot->locked_target; /* a choice lock has no target (Team C) */
    }
    out->protecting = (((uint32_t)slot->flags & DFI_VOL_PROTECT) != 0u) ? 1u : 0u;
    out->acted = slot->move_actions != 0u ? 1u : 0u;
    out->protect_chain = slot->stall_level;
    out->flash_fire = ((uint32_t)slot->flags & DFI_VOL_FLASH_FIRE) != 0u ? 1u : 0u;
}

static void dfi_view_side(const struct duoforge_battle *b, uint32_t viewer, uint32_t s, duoforge_side_view *out)
{
    const dfi_side *side = &b->sides[s];
    const bool own = s == viewer;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER && m < side->member_count; ++m) {
        dfi_view_member(b, viewer, s, m, &out->members[m]); /* unregistered slots stay all-zero */
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        dfi_view_position(b, viewer, s, p, &out->positions[p]);
    }
    out->member_count = side->member_count;
    out->occupant[0] = side->positions[0].occupant;
    out->occupant[1] = side->positions[1].occupant;
    out->mega_used = side->mega_used;
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        out->brought_order[i] = own ? side->brought_order[i] : (uint8_t)DUOFORGE_ROSTER_NONE;
    }
    /* Who must answer is public: a human sees the opponent being asked. */
    if ((((uint32_t)b->request_mask >> s) & 1u) != 0u) {
        out->requested = 1u;
        out->requested_slots = side->requested_slots;
    }
    out->reflect_turns = side->reflect_turns;
    out->light_screen_turns = side->light_screen_turns;
    out->tailwind_turns = side->tailwind_turns;
}

duoforge_status duoforge_battle_observe(const duoforge_context *ctx, const duoforge_battle *battle,
                                        uint32_t player, duoforge_observation *out_observation)
{
    if (ctx == NULL || battle == NULL || out_observation == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (player >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (dfi_state_check_query(ctx, battle, NULL) != DUOFORGE_OK) { /* decision 0011 */
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_observation o;
    memset(&o, 0, sizeof o);
    o.epoch = battle->request_epoch;
    o.boundary_kind = battle->boundary_kind;
    o.player = (uint8_t)player;
    if ((((uint32_t)battle->request_mask >> player) & 1u) != 0u) {
        o.requested = 1u;
        o.slot_mask = battle->sides[player].requested_slots;
    }
    o.turn = battle->turn;
    o.weather = battle->weather;
    o.weather_turns = battle->weather_turns;
    o.terrain = battle->terrain;
    o.terrain_turns = battle->terrain_turns;
    o.trick_room_turns = battle->trick_room_turns;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_view_side(battle, player, s, &o.sides[s]);
    }
    *out_observation = o;
    return DUOFORGE_OK;
}
