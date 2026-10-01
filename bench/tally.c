#include "tally.h"

#include <string.h>

void dfb_tally_reset(dfb_tally *tally)
{
    memset(tally, 0, sizeof *tally);
}

void dfb_tally_add(dfb_tally *into, const dfb_tally *from)
{
    into->choices += from->choices;
    into->team_selections += from->team_selections;
    into->slot_commands += from->slot_commands;
    into->moves += from->moves;
    into->struggles += from->struggles;
    into->megas += from->megas;
    into->switches += from->switches;
    into->replacements += from->replacements;
    into->passes += from->passes;
    into->target_foe += from->target_foe;
    into->target_ally += from->target_ally;
    into->target_none += from->target_none;
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        into->leads[i] += from->leads[i];
    }
    for (uint32_t i = 0u; i < DFB_TALLY_MOVE_IDS; ++i) {
        into->move_uses[i] += from->move_uses[i];
    }
}

/* One slot command of `player` at the boundary `obs` shows. */
static duoforge_status dfb_tally_command(const duoforge_observation *obs, uint32_t player, uint32_t slot,
                                         const duoforge_slot_command *c, dfb_tally *add)
{
    if (c->kind == DUOFORGE_SLOT_NONE) {
        return DUOFORGE_OK;
    }
    add->slot_commands += 1u;
    if (c->kind == DUOFORGE_SLOT_PASS) {
        add->passes += 1u;
        return DUOFORGE_OK;
    }
    if (c->kind == DUOFORGE_SLOT_SWITCH) {
        if (obs->boundary_kind == DUOFORGE_BOUNDARY_TURN) {
            add->switches += 1u;
        } else {
            add->replacements += 1u;
        }
        return DUOFORGE_OK;
    }
    if (c->kind != DUOFORGE_SLOT_MOVE) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    add->moves += 1u;
    add->megas += c->mega != 0u ? 1u : 0u;
    if (c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE) {
        add->struggles += 1u;
    } else {
        const duoforge_side_view *own = &obs->sides[player];
        const uint32_t occupant = own->occupant[slot];
        if (occupant >= DUOFORGE_MAX_ROSTER || c->move_slot >= DUOFORGE_MAX_MOVE_SLOTS) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        const uint32_t id = own->members[occupant].move_ids[c->move_slot];
        if (id < DFB_TALLY_MOVE_IDS) {
            add->move_uses[id] += 1u;
        }
    }
    if (c->target == DUOFORGE_TARGET_NONE) {
        add->target_none += 1u;
    } else if ((uint32_t)c->target / 2u == player) {
        add->target_ally += 1u;
    } else {
        add->target_foe += 1u;
    }
    return DUOFORGE_OK;
}

duoforge_status dfb_tally_choice(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                 const duoforge_side_choice *choice, dfb_tally *tally)
{
    if (ctx == NULL || battle == NULL || choice == NULL || tally == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    duoforge_observation obs;
    const duoforge_status st = duoforge_battle_observe(ctx, battle, player, &obs);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfb_tally add;
    memset(&add, 0, sizeof add);
    add.choices = 1u;
    if (choice->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        if (obs.boundary_kind != DUOFORGE_BOUNDARY_TEAM_SELECTION) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        add.team_selections = 1u;
        for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE && k < choice->pick_count; ++k) {
            if (choice->picks[k] >= DUOFORGE_MAX_ROSTER) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
            add.leads[choice->picks[k]] += 1u;
        }
    } else if (choice->kind == DUOFORGE_CHOICE_SLOTS) {
        for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE; ++k) {
            const duoforge_status cs = dfb_tally_command(&obs, player, k, &choice->slots[k], &add);
            if (cs != DUOFORGE_OK) {
                return cs;
            }
        }
    } else {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    dfb_tally_add(tally, &add);
    return DUOFORGE_OK;
}
