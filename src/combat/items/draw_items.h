#ifndef DUOFORGE_COMBAT_ITEMS_DRAW_ITEMS_H
#define DUOFORGE_COMBAT_ITEMS_DRAW_ITEMS_H
/*
 * The two held items with a roll of their own (decision 0015 entry 5eh): Quick Claw and Focus Band. Neither has a Champions
 * override (data/mods/champions/items.ts has no entry for them), so the rules are the base game's and hold in every format
 * that uses the rows. Each roll is drawn only for a holder: a battle without the item draws exactly what it drew before.
 */
#include <stdbool.h>
#include <stdint.h>

#include "combat/items/held.h"
#include "combat/run_internal.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "rng/draw.h"

/* Quick Claw (data/items.ts:4989-5005): onFractionalPriority, priority -2. resolveAction runs the FractionalPriority event once for
 * every move action it resolves without midTurn (sim/battle-queue.ts:249: at the commit of the choices, and for the action that
 * Champions' Encore puts in place of a queued one, data/mods/champions/moves.ts:334), with the relay value 0, which the handler
 * reads as `priority`. So for a holder, at every such action:
 *   - the Mycelium Might exemption (a Status move of a Mycelium Might holder) cannot apply: no pool forme has the ability;
 *   - `priority <= 0` is the relay value, 0, whatever the move's own priority (a priority move rolls too): only an earlier
 *     handler of the event could raise it, and the only ones of the pin are Quick Draw (unmarked: a battle with it is refused at
 *     create), Mycelium Might, Custap Berry, Stall, Full Incense and Lagging Tail (none in the pool);
 *   - randomChance(1, 5) (QUICK_CLAW); on success `-activate|holder|item: Quick Claw` at once and the fraction 0.1.
 * The action keeps the fraction for the rest of the turn (DFI_QRES_QUICK_CLAW in its record), and comparePriority puts it after the
 * higher integer priorities and before every action of its own priority (dfi_compare). The item is not used up.
 * `m` is the actor (standing: it is choosing or being given a move action); `reserve` the record's byte. */
static inline duoforge_status dfi_quick_claw_roll(dfi_run *r, uint32_t flat, const dfi_member *m, uint8_t *reserve)
{
    if (!dfi_holds(r->b, m, DFI_ITEM_QUICKCLAW)) {
        return DUOFORGE_OK;
    }
    bool fast = false;
    const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_QUICK_CLAW, 1u, 5u, &fast);
    if (st != DUOFORGE_OK || !fast) {
        return st;
    }
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_QUICKCLAW, DUOFORGE_NO_POSITION);
    dfi_emit(r, &e); /* [-activate] holder|item: Quick Claw */
    *reserve = (uint8_t)((uint32_t)*reserve | DFI_QRES_QUICK_CLAW); /* wide-operands-reviewed: a byte mask */
    return DUOFORGE_OK;
}

/* Focus Band (data/items.ts:2253-2268): onDamage, priority -40. Battle.spreadDamage runs the Damage event for every damage of a
 * standing, active target except Struggle's recoil (sim/battle.ts:2105-2127; directDamage, sim/pokemon.ts, runs none), and the
 * handler draws randomChance(1, 10) FIRST: so the roll (FOCUS_BAND) is drawn at every such damage of the holder, a hit that is
 * not lethal, recoil, Life Orb, a Rocky Helmet, a hazard, the weather and the residuals included. Only when it succeeds, the
 * damage is at least the holder's HP and the effect is a Move (a move's hit or the confusion self-hit, dfi_dmg_class MOVE) does
 * it print `-activate|holder|item: Focus Band` and leave 1 HP (return target.hp - 1). The item is not used up.
 * The handlers of the event that run before it, and what the engine makes of them (the callers come here after them):
 *   - Magic Guard (priority 0) returns false for every effect that is not a Move: the event stops, no roll (dfi_deal's early
 *     return comes first);
 *   - Rock Head (priority 0) returns null for a recoil move's recoil: the event stops, no roll (the callers deal no recoil then);
 *   - Sturdy (priority -30) leaves hp - 1 of a full-HP holder's lethal Move damage, with its line before the roll (the callers
 *     apply it first), so the roll that follows cannot save;
 *   - Disguise, Ice Face and Poison Heal (priority 1), Heatproof, Endure (-10), False Swipe and Hold Back (-20) are unmarked
 *     rows: no battle with them is created.
 * A damage of 0 (the event runs with a relay value of 0, then a -damage line) is refused by name: no caller of the engine is
 * known to pass one for a holder, and the line would not be shown. `amount` is the damage after the earlier handlers. */
static inline duoforge_status dfi_focus_band_roll(dfi_run *r, uint32_t flat, const dfi_member *m, bool move_effect,
                                                  uint32_t *amount)
{
    if (!dfi_holds(r->b, m, DFI_ITEM_FOCUSBAND)) {
        return DUOFORGE_OK;
    }
    if (*amount == 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* a Damage event of 0 for a Focus Band holder: not modelled (see above) */
    }
    bool band = false;
    const duoforge_status st = dfi_draw_chance(r->draws, DFI_SITE_FOCUS_BAND, 1u, 10u, &band);
    if (st != DUOFORGE_OK || !band || !move_effect || *amount < m->hp) {
        return st;
    }
    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ITEM, 1u + DFI_ITEM_FOCUSBAND, DUOFORGE_NO_POSITION);
    dfi_emit(r, &e); /* [-activate] holder|item: Focus Band, before the -damage line */
    *amount = (uint32_t)m->hp - 1u;
    return DUOFORGE_OK;
}

#endif
