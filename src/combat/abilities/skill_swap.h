#ifndef DUOFORGE_COMBAT_ABILITIES_SKILL_SWAP_H
#define DUOFORGE_COMBAT_ABILITIES_SKILL_SWAP_H

/* Private abilities implementation (restructure step 4, abilities): Skill Swap: failskillswap, the swap of the current
 * abilities, its Ends and Starts. Split from src/combat/turn.c@98915957; included by turn.c where the code stood, so
 * its dependencies and the turn order are unchanged. */
#include "combat/run_internal.h"

/* Skill Swap (step G70, decision 0041; sim/battle.ts:1311-1345, data/moves.ts:16590-16606). The failures are the pin's: a
 * fainted holder or failskillswap on either ability (dfi_fails_skillswap), and they print -fail|user [still]. Before anything
 * changes, the refusals: the Update handlers of the abilities that come in act on a state the holder has (Limber on a paralysed
 * holder, Thermal Exchange on a burned one, Oblivious on a taunted one). Then the line, as two ABILITY events in the line's order with cause MOVE: id = the holder's new ability + 1, id2 = the
 * move; the Ends of the old abilities (Flash Fire's and Unburden's volatiles go with no line); the swap of the tail's
 * ability_now, stored as 0 while it equals the sheet's; the Starts, the target's new ability first, then the user's. The
 * ally pair is the same (the line names no ability; the converter follows the pair). */
/* failskillswap (sim/battle.ts:1316, the pin's ability flag), read from the holder's current ability: exactly the pool's abilities
 * that have the flag, Disguise, Hunger Switch, Illusion (data/abilities.ts:2091; issue #620, decision 0015 entry 5dx), Stance
 * Change and Zero to Hero. tools/datagen/gen_closure.py (FAILSKILLSWAP_ABILITIES, check_failskillswap) fails when the pin's set
 * over the pool rows is another one. The disguise does not matter: the pin reads the holder's own ability. */
static bool dfi_fails_skillswap(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_ability(b, m, DFI_ABILITY_DISGUISE) || dfi_ability(b, m, DFI_ABILITY_HUNGERSWITCH) ||
           dfi_ability(b, m, DFI_ABILITY_ILLUSION) || dfi_ability(b, m, DFI_ABILITY_STANCECHANGE) ||
           dfi_ability(b, m, DFI_ABILITY_ZEROTOHERO);
}

static bool dfi_skill_swap_update_due(struct duoforge_battle *b, uint32_t flat, uint32_t code)
{
    const dfi_member *m = dfi_at(b, flat);
    if (m == NULL || m->hp == 0u) {
        return false;
    }
    if (code == 1u + DFI_ABILITY_LIMBER) {
        return m->status == DFI_STATUS_PAR; /* Limber's onUpdate cures the paralysis (data/abilities.ts:2368-2374) */
    }
    if (code == 1u + DFI_ABILITY_THERMALEXCHANGE) {
        return m->status == DFI_STATUS_BRN; /* Thermal Exchange's onUpdate cures a burn */
    }
    if (code == 1u + DFI_ABILITY_OBLIVIOUS) {
        return b->tail.sides[flat / 2u].positions[flat % 2u].taunt_turns != 0u; /* onUpdate removes Taunt (:3008-3040) */
    }
    if (code == 1u + DFI_ABILITY_MAGMAARMOR) {
        return m->status == DFI_STATUS_FRZ; /* Magma Armor's onUpdate cures the freeze (data/abilities.ts:2502-2507, step G77) */
    }
    return false;
}

/* The tail's copy of the holder's ability: kept only while it differs from the sheet's (the view's ability_changed bit). */
static void dfi_skill_swap_set(struct duoforge_battle *b, uint32_t flat, uint32_t code)
{
    const dfi_member *m = dfi_at(b, flat);
    const uint32_t stored = code == m->ability ? 0u : code;
    b->tail.sides[flat / 2u].ability_now[dfi_pos(b, flat)->occupant] = (uint16_t)stored;
}

/* setAbility's End of the old ability (sim/battle.ts:1325-1326): Flash Fire removes its volatile (silent), Unburden its
 * volatile (no line); Unnerve's flag is derived from the holder's ability (dfi_unnerved), so it needs nothing. */
static void dfi_skill_swap_end(struct duoforge_battle *b, uint32_t flat)
{
    dfi_active_slot *pos = dfi_pos(b, flat);
    pos->flags = (uint8_t)((uint32_t)pos->flags & ~((uint32_t)DFI_VOL_UNBURDEN | (uint32_t)DFI_VOL_FLASH_FIRE)); /* wide-operands-reviewed */
}

/* The Start of the ability the holder now has: the entry abilities (dfi_entry_ability: weather, terrain, Intimidate, Trace's
 * copy, Fairy Aura, Unnerve, Pressure) and Hospitality's heal of the ally, which is not an entry (dfi_has_entry). */
static duoforge_status dfi_skill_swap_start(dfi_run *r, uint32_t flat)
{
    const dfi_member *m = dfi_at(r->b, flat);
    if (m == NULL || m->hp == 0u) {
        return DUOFORGE_OK;
    }
    if (dfi_has_entry(r->b, m)) {
        return dfi_entry_ability(r, flat);
    }
    if (dfi_ability_code(r->b, m) == 1u + DFI_ABILITY_HOSPITALITY) {
        dfi_hospitality(r, flat);
    }
    return DUOFORGE_OK;
}

uint32_t dfi_skill_swap_decision(struct duoforge_battle *b, uint32_t user, uint32_t target)
{
    const dfi_member *um = dfi_at(b, user);
    const dfi_member *tm = dfi_at(b, target);
    if (um == NULL || tm == NULL) {
        return DFI_SKILL_SWAP_INVALID;
    }
    if (um->hp == 0u || tm->hp == 0u || dfi_fails_skillswap(b, um) || dfi_fails_skillswap(b, tm)) {
        return DFI_SKILL_SWAP_FAILS;
    }
    if (dfi_skill_swap_update_due(b, user, dfi_ability_code(b, tm)) ||
        dfi_skill_swap_update_due(b, target, dfi_ability_code(b, um))) {
        return DFI_SKILL_SWAP_REFUSED;
    }
    return DFI_SKILL_SWAP_PROCEED;
}

static duoforge_status dfi_skill_swap(dfi_run *r, uint32_t user, uint32_t target, uint32_t move_id, bool *did)
{
    struct duoforge_battle *b = r->b;
    *did = false;
    /* The decision reads the state only: a refusal (an Update handler on a state the holder has) comes before anything changes. */
    const uint32_t decision = dfi_skill_swap_decision(b, user, target);
    if (decision == DFI_SKILL_SWAP_INVALID) {
        return DUOFORGE_E_INVARIANT;
    }
    if (decision == DFI_SKILL_SWAP_FAILS) {
        dfi_fail_still(r, user); /* skillSwap returns false: the move's -fail and [still] */
        return DUOFORGE_OK;
    }
    if (decision == DFI_SKILL_SWAP_REFUSED) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const uint32_t user_now = dfi_ability_code(b, dfi_at(b, user));   /* 1 + id */
    const uint32_t target_now = dfi_ability_code(b, dfi_at(b, target));
    /* -activate|user|Skill Swap|A|B|[of] target: the user now has the target's ability (A), the target the user's (B). */
    duoforge_event first = dfi_ev(DUOFORGE_EVENT_ABILITY, user, DUOFORGE_CAUSE_MOVE, move_id, target);
    first.id = (uint16_t)target_now;
    dfi_emit(r, &first);
    duoforge_event second = dfi_ev(DUOFORGE_EVENT_ABILITY, target, DUOFORGE_CAUSE_MOVE, move_id, user);
    second.id = (uint16_t)user_now;
    dfi_emit(r, &second);
    dfi_skill_swap_end(b, user);
    dfi_skill_swap_end(b, target);
    dfi_skill_swap_set(b, user, target_now);
    dfi_skill_swap_set(b, target, user_now);
    duoforge_status st = dfi_skill_swap_start(r, target); /* the target's new ability starts first (battle.ts:1344) */
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_skill_swap_start(r, user);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *did = true;
    return DUOFORGE_OK;
}

#endif
