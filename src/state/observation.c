/*
 * Perspective-safe observation prototype (docs/decisions/0005 section 6).
 * The record for player p is built from p's side (exact), public facts
 * (occupancy, Mega use, registered counts, open team-sheet fields) and p's
 * knowledge of the opponent (seen_mask) at the profile's HP precision.
 * Nothing else of the opponent's side is read: not its bench order, PP,
 * exact HP of unseen members, sealed commitments or the RNG.
 */
#include <stddef.h>
#include <string.h>

#include "core/arith.h"
#include "state/battle_internal.h"
#include "state/context_internal.h"
#include "state/invariants.h"

_Static_assert(sizeof(duoforge_member_view) == 24u, "member view is 24 bytes");
_Static_assert(offsetof(duoforge_member_view, move_ids) == 6u, "member view layout: move ids");
_Static_assert(offsetof(duoforge_member_view, pp) == 14u, "member view layout: pp");
_Static_assert(offsetof(duoforge_member_view, mega_capable) == 23u, "member view layout: mega");
_Static_assert(sizeof(duoforge_side_view) == 156u, "side view is 156 bytes");
_Static_assert(offsetof(duoforge_side_view, member_count) == 144u, "side view layout: count");
_Static_assert(offsetof(duoforge_side_view, brought_order) == 148u, "side view layout: order");
_Static_assert(sizeof(duoforge_observation) == 320u, "observation is 320 bytes");
_Static_assert(offsetof(duoforge_observation, sides) == 8u, "observation layout: sides");

/* Champions HP display (sim/pokemon.ts:2060-2073 at the pin): floor percent,
 * minimum 1 while alive, colour flag at exactly 20 and 50. hp <= hp_max and
 * hp_max > 0 hold after the invariant check. */
static void dfi_hp_percent(uint32_t hp, uint32_t hp_max, uint16_t *out_pct, uint8_t *out_flag)
{
    *out_flag = (uint8_t)DUOFORGE_HP_FLAG_NONE;
    if (hp == 0u) {
        *out_pct = 0u;
        return;
    }
    uint32_t pct = (100u * hp) / hp_max; /* hp <= 65535: no overflow */
    if (pct == 0u) {
        pct = 1u;
    }
    uint32_t flag = DUOFORGE_HP_FLAG_NONE;
    if (pct == 20u) {
        flag = hp * 5u > hp_max ? DUOFORGE_HP_FLAG_YELLOW : DUOFORGE_HP_FLAG_RED;
    } else if (pct == 50u) {
        flag = hp * 2u > hp_max ? DUOFORGE_HP_FLAG_GREEN : DUOFORGE_HP_FLAG_YELLOW;
    }
    *out_flag = (uint8_t)flag;
    *out_pct = (uint16_t)pct; /* <= 100 */
}

static bool dfi_is_occupant(const dfi_side *side, uint32_t m)
{
    return side->positions[0].occupant == m || side->positions[1].occupant == m;
}

static void dfi_view_side(const struct duoforge_battle *b, uint32_t viewer, uint32_t s, duoforge_side_view *out)
{
    const dfi_side *side = &b->sides[s];
    const bool own = s == viewer;
    const uint32_t seen = b->sides[viewer].seen_mask;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        duoforge_member_view *v = &out->members[m];
        if (m >= side->member_count) {
            continue; /* unregistered: all-zero */
        }
        const dfi_member *mem = &side->members[m];
        v->species_id = mem->species_id;
        v->move_count = mem->move_count;
        v->mega_capable = mem->mega_capable;
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            v->move_ids[k] = mem->moves[k].move_id;
        }
        if (own) {
            v->hp = mem->hp;
            v->hp_max = mem->hp_max;
            v->hp_kind = (uint8_t)DUOFORGE_HP_EXACT;
            v->pp_kind = (uint8_t)DUOFORGE_PP_EXACT;
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                v->pp[k] = mem->moves[k].pp;
            }
            if (b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
                v->location = (uint8_t)DUOFORGE_LOCATION_UNDETERMINED;
            } else if (dfi_is_occupant(side, m)) {
                v->location = (uint8_t)DUOFORGE_LOCATION_ACTIVE;
            } else if ((((uint32_t)side->brought_mask >> m) & 1u) != 0u) {
                v->location = (uint8_t)DUOFORGE_LOCATION_BENCH;
            } else {
                v->location = (uint8_t)DUOFORGE_LOCATION_NOT_BROUGHT;
            }
        } else {
            v->pp_kind = (uint8_t)DUOFORGE_PP_UNKNOWN;
            if (((seen >> m) & 1u) != 0u) {
                dfi_hp_percent(mem->hp, mem->hp_max, &v->hp, &v->hp_flag);
                v->hp_max = 100u;
                v->hp_kind = (uint8_t)DUOFORGE_HP_PERCENT;
                const uint32_t loc = dfi_is_occupant(side, m) ? DUOFORGE_LOCATION_ACTIVE : DUOFORGE_LOCATION_BENCH;
                v->location = (uint8_t)loc;
            } else {
                v->hp_kind = (uint8_t)DUOFORGE_HP_UNKNOWN;
                v->location = (uint8_t)DUOFORGE_LOCATION_UNDETERMINED;
            }
        }
    }
    out->member_count = side->member_count;
    out->occupant[0] = side->positions[0].occupant;
    out->occupant[1] = side->positions[1].occupant;
    out->mega_used = side->mega_used;
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        out->brought_order[i] = own ? side->brought_order[i] : (uint8_t)DUOFORGE_ROSTER_NONE;
    }
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
    if (dfi_state_check(ctx, battle, NULL) != DUOFORGE_OK) {
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
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_view_side(battle, player, s, &o.sides[s]);
    }
    *out_observation = o;
    return DUOFORGE_OK;
}
