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
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"

/* The POOL player-view extension (decision 0018): size and every offset, so that no edit moves a field unseen. */
_Static_assert(sizeof(duoforge_field_ext) == 16u, "field ext is 16 bytes");
_Static_assert(sizeof(duoforge_position_ext) == 16u, "position ext is 16 bytes");
_Static_assert(offsetof(duoforge_position_ext, ability_now) == 4u, "position ext layout: ability_now");
_Static_assert(offsetof(duoforge_position_ext, type_now) == 6u, "position ext layout: type_now");
_Static_assert(offsetof(duoforge_position_ext, encore_slot) == 8u, "position ext layout: encore_slot");
_Static_assert(offsetof(duoforge_position_ext, perish) == 11u, "position ext layout: perish");
_Static_assert(offsetof(duoforge_position_ext, reserved) == 12u, "position ext layout: reserved");
_Static_assert(sizeof(duoforge_member_ext) == 4u, "member ext is 4 bytes");
_Static_assert(offsetof(duoforge_member_ext, item_now) == 2u, "member ext layout: item_now");
_Static_assert(sizeof(duoforge_side_ext) == 64u, "side ext is 64 bytes");
_Static_assert(offsetof(duoforge_side_ext, members) == 32u, "side ext layout: members");
_Static_assert(offsetof(duoforge_side_ext, aurora_veil_turns) == 56u, "side ext layout: aurora_veil_turns");
_Static_assert(offsetof(duoforge_side_ext, guard_flags) == 61u, "side ext layout: guard_flags");
_Static_assert(offsetof(duoforge_side_ext, reserved) == 62u, "side ext layout: reserved");
_Static_assert(sizeof(duoforge_observation_ext) == DUOFORGE_OBSERVATION_EXT_SIZE, "observation ext is 192 bytes");
_Static_assert(offsetof(duoforge_observation_ext, epoch) == 4u, "observation ext layout: epoch");
_Static_assert(offsetof(duoforge_observation_ext, supported) == 8u, "observation ext layout: supported");
_Static_assert(offsetof(duoforge_observation_ext, field) == 16u, "observation ext layout: field");
_Static_assert(offsetof(duoforge_observation_ext, sides) == 32u, "observation ext layout: sides");
_Static_assert(offsetof(duoforge_observation_ext, reserved1) == 160u, "observation ext layout: reserved1");

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
                   DUOFORGE_WEATHER_SAND == DFI_WEATHER_SAND && DUOFORGE_WEATHER_SNOW == DFI_WEATHER_SNOW &&
                   DUOFORGE_TERRAIN_GRASSY == DFI_TERRAIN_GRASSY && DUOFORGE_TERRAIN_PSYCHIC == DFI_TERRAIN_PSYCHIC,
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
        /* The item of the sheet is gone: used up or taken, and not replaced by one that a move gave (step G29: then the
         * consumed flag is clear and item_now holds it; a member without a sheet item has none to lose). */
        v->item_used = (mem->item != 0u && (mem->item_consumed != 0u || b->tail.sides[s].item_now[m] == DFI_TAIL_ITEM_NONE))
                           ? 1u
                           : 0u;
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
    v->item_used = (mem->item != 0u && ((uint32_t)know->revealed & DFI_REVEALED_ITEM_CONSUMED) != 0u) ? 1u : 0u;
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
    /* Unburden is public by inference: the ability and the item's use are
     * shown (Team C). */
    const uint32_t follow = ((uint32_t)slot->flags & DFI_VOL_FOLLOW_ME) != 0u ? DUOFORGE_POSITION_FLAG_FOLLOW_ME : 0u;
    const uint32_t helping = ((uint32_t)slot->flags & DFI_VOL_HELPING_HAND) != 0u ? DUOFORGE_POSITION_FLAG_HELPING_HAND : 0u;
    /* The flag says that Unburden doubles the Speed, which asks for no item (data/abilities.ts:5247-5251): the volatile of a
     * holder of its own Mega Stone, set by a Knock Off that the stone refused, shows nothing (no line says it). */
    const dfi_member *holder = slot->occupant < b->sides[s].member_count ? &b->sides[s].members[slot->occupant] : NULL;
    const bool item_gone = holder != NULL && (holder->item_consumed != 0u ||
                                              b->tail.sides[s].item_now[slot->occupant] == DFI_TAIL_ITEM_NONE);
    const uint32_t unburden =
        ((uint32_t)slot->flags & DFI_VOL_UNBURDEN) != 0u && item_gone ? DUOFORGE_POSITION_FLAG_UNBURDEN : 0u;
    out->reserved = (uint8_t)(follow | helping | unburden); /* wide-operands-reviewed: < 8 */
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

duoforge_status duoforge_battle_observe_ext(const duoforge_context *ctx, const duoforge_battle *battle,
                                            uint32_t viewer, duoforge_observation_ext *out)
{
    if (ctx == NULL || battle == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (viewer >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (dfi_state_check_query(ctx, battle, NULL) != DUOFORGE_OK) { /* decision 0011 */
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_observation_ext o;
    memset(&o, 0, sizeof o);
    /* Only the POOL kinds have an extension; every other kind gets the all-zero struct. */
    if (dfi_context_is_closure(ctx) && dfi_kind_limits_of(ctx->data_kind).pool_rules) {
        o.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
        o.player = (uint8_t)viewer;
        o.epoch = battle->request_epoch;
        o.supported = dfi_support.view_ext_features;
        /* A feature's step fills its fields here and sets its bit in the manifest (decision 0018 section 13).
         * Step G8: Heal Block and Throat Chop, both public (section 5, the owner's change for Throat Chop): the
         * presence of the occupant's tail counters, never the counters. They are set by the -start lines and cleared
         * by the -end lines or when the occupant leaves (the tail is cleared then), as section 6.1 says; an empty
         * position has no tail. */
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            /* Step G7: Wide Guard of the side (public: [-singleturn] Wide Guard). It lasts the turn and ends in the
             * residual, so it is set only at a boundary inside a turn (a PIVOT), as decision 0018 section 3.3 says. */
            o.sides[s].guard_flags = battle->tail.sides[s].wide_guard != 0u ? (uint8_t)DUOFORGE_SIDE_GUARD_WIDE_GUARD : 0u;
            /* Step G20: Aurora Veil's turns left (public: -sidestart ... move: Aurora Veil, 5 turns or 8 with Light Clay on
             * the setter, then counted down in the residual until the -sideend line; the sheet has the item). The state
             * keeps the same count, so the view is the tail's field. */
            o.sides[s].aurora_veil_turns = battle->tail.sides[s].aurora_veil_turns;
            /* Step G16: the held item that a move took (Knock Off), public (-enditem|X|Item|[from] move: Knock Off): the
             * member holds nothing, DUOFORGE_ITEM_NOW_NONE, and it stays across a switch-out and a faint. The tail's
             * item_now is the overlay of decision 0018 as it is: the item id + 1 that a Trick, Thief or Covet put there (step
             * G29), or none. A member that does not exist has none (the invariants). */
            for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                o.sides[s].members[m].item_now = battle->tail.sides[s].item_now[m];
            }
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const dfi_tail_pos *tail = &battle->tail.sides[s].positions[p];
                uint32_t vol = 0u;
                vol |= tail->heal_block_turns != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_HEAL_BLOCK : 0u;
                vol |= tail->throat_chop_turns != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_THROAT_CHOP : 0u;
                vol |= tail->must_recharge != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_MUST_RECHARGE : 0u; /* step G17 */
                vol |= tail->glaive_rush != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_GLAIVE_RUSH : 0u; /* step G19 */
                o.sides[s].positions[p].volatiles = vol;
                /* Step G9, Encore: the one move slot (slot + 1) that the occupant may use, public (-start|X|Encore: the
                 * slot is the one of its last move line); the turns are never shown. */
                o.sides[s].positions[p].encore_slot = tail->encore_slot;
                /* Step G11, Soak: the type that it set, public (-start|X|typechange|Water): the occupant is pure
                 * Water until it leaves, faints or Mega Evolves (the tail's soak type is cleared there). */
                const uint32_t occupant = battle->sides[s].positions[p].occupant;
                /* Step AC1, Trace: the ability that the occupant copied, public (-ability|X|NEW|OLD|[from] ability:
                 * Trace); ability id + 1 when it is not the sheet's ability, else 0. Gone when the occupant leaves or
                 * Mega Evolves (the tail's ability_now is cleared there). */
                const uint32_t changed = occupant < DUOFORGE_MAX_ROSTER ? battle->tail.sides[s].ability_now[occupant] : 0u;
                if (changed != 0u && changed != battle->sides[s].members[occupant].ability) {
                    o.sides[s].positions[p].ability_now = (uint16_t)changed;
                }
                const uint32_t soak = occupant < DUOFORGE_MAX_ROSTER ? battle->tail.sides[s].soak_type[occupant] : 0u;
                if (soak != 0u) {
                    o.sides[s].positions[p].volatiles = vol | (uint32_t)DUOFORGE_POSITION_EXT_TYPE_CHANGED;
                    o.sides[s].positions[p].type_now[0] = (uint8_t)soak; /* type id + 1: one type, the second slot stays 0 */
                }
            }
        }
    }
    *out = o;
    return DUOFORGE_OK;
}
