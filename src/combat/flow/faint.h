#ifndef DUOFORGE_COMBAT_FLOW_FAINT_H
#define DUOFORGE_COMBAT_FLOW_FAINT_H

/* Private flow implementation (restructure step 4, flow): win check and faint handling. Split from
 * src/combat/turn.c@c02189e7; included by turn.c where the code stood, so its dependencies and the turn order are
 * unchanged. */
#include "combat/run_internal.h"

/* checkWin (sim/battle.ts:404-415): a side with no Pokemon left loses; when
 * every side is out, the side whose Pokemon fainted last wins (generation 5
 * and later). */
static uint32_t dfi_win_result(const struct duoforge_battle *b, uint32_t last_fainted)
{
    const uint32_t left0 = dfi_left(b, 0u);
    const uint32_t left1 = dfi_left(b, 1u);
    if (left0 == 0u && left1 == 0u) {
        return last_fainted / 2u == 0u ? DFI_RESULT_SIDE0 : DFI_RESULT_SIDE1;
    }
    if (left1 == 0u) {
        return DFI_RESULT_SIDE0;
    }
    return left0 == 0u ? DFI_RESULT_SIDE1 : DFI_RESULT_NONE;
}

/* The AfterFaint event of faintMessages (sim/battle.ts:2600-2602, runEvent('AfterFaint', faintData.target, faintData.source,
 * faintData.effect, length)): length is the number of faints that this call shows (the queue's length when it began, faints
 * from `from` on), and the handler that runs is the source's onSourceAfterFaint, Moxie's (data/abilities.ts:2749-2759), when
 * the last faint's effect is a Move: this.boost({atk: length}, source), the source being the holder itself, so a fainted
 * holder gets nothing (Battle.boost, :2029). The caller has checked the win (no AfterFaint after a finished battle). */
static void dfi_after_faint(dfi_run *r, uint32_t length, bool by_move, uint32_t src)
{
    if (length == 0u || !by_move || src >= DFI_POSITIONS) {
        return;
    }
    const dfi_member *holder = dfi_at(r->b, src);
    if (!dfi_ability(r->b, holder, DFI_ABILITY_MOXIE) || holder->hp == 0u) {
        return;
    }
    uint8_t atk_up[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 6u, 6u}; /* biased by 6 */
    atk_up[DFI_STAGE_ATK] = (uint8_t)(6u + length); /* wide-operands-reviewed: length <= DFI_POSITIONS */
    (void)dfi_boost(r, src, atk_up, src, dfi_effect(DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_MOXIE, DFI_BOOST_PRIMARY));
}

/* Destiny Bond's onFaint (step G76; data/moves.ts:3505-3520), run for the holder's faint before its volatiles are cleared
 * (sim/battle.ts:2555-2570): a holder with the flag that faints from a Move of a foe (not an ally, not Future Sight: the pool
 * has none) shows -activate|holder|move: Destiny Bond (ACTIVATE, cause MOVE, id2 the move) and queues the attacker's faint,
 * which the faint loop then processes after it. The attacker is not faint()ed again when it is fainted or queued already
 * (sim/pokemon.ts:1581-1584), but the -activate line shows regardless. The attacker's faint has no effect: the Moxie read
 * after the queue sees by_move false. */
static void dfi_destiny_bond_ko(dfi_run *r, uint32_t flat)
{
    dfi_tail_pos *tail = &r->b->tail.sides[flat / 2u].positions[flat % 2u];
    if ((tail->position_flags & DFI_POSFLAG_DESTINY_BOND) == 0u || !r->last_faint_move) {
        return;
    }
    const uint32_t src = r->last_faint_by;
    if (src >= DFI_POSITIONS || src / 2u == flat / 2u) {
        return; /* no source, or the holder's own side (Battle.isAlly) */
    }
    /* The holder's onFaint runs once, in faintMessages (sim/battle.ts:2555-2570), and clearVolatile ends the flag there: the
     * flag is cleared here, so that the processing of the faint does not run the KO a second time. */
    tail->position_flags = (uint8_t)((uint32_t)tail->position_flags & ~(uint32_t)DFI_POSFLAG_DESTINY_BOND); /* wide-operands-reviewed */
    const duoforge_event act = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_MOVE, DFI_MOVE_DESTINYBOND, DUOFORGE_NO_POSITION);
    dfi_emit(r, &act); /* [-activate] holder|move: Destiny Bond */
    dfi_member *am = dfi_at(r->b, src);
    if (am == NULL || am->hp == 0u || r->faint_count >= DFI_POSITIONS) {
        return;
    }
    am->hp = 0u; /* faint() sets the HP to 0 when it queues (sim/pokemon.ts:1586) */
    r->faint_queue[r->faint_count] = src;
    r->faint_count += 1u;
    r->last_faint_by = DFI_POSITIONS;
    r->last_faint_move = false;
}

/* faintMessages and checkWin (sim/battle.ts:2535-2590, 404-415): the faints
 * of the action in order, then the win rule. */
static void dfi_process_faints(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    const uint32_t length = r->faint_count - r->faint_announced; /* the faints this call shows (sim/battle.ts faintQueue.length) */
    for (uint32_t i = 0u; i < r->faint_count; ++i) {
        const uint32_t flat = r->faint_queue[i];
        if (i >= r->faint_announced) {
            dfi_emit_plain(r, DUOFORGE_EVENT_FAINT, flat); /* [faint] */
        }
        dfi_destiny_bond_ko(r, flat); /* step G76: before the tail is cleared, which ends the flag */
        dfi_tail_clear_occupant(b, flat); /* the POOL tail ends with the volatiles (decision 0015 section 7) */
        dfi_clear_volatile(dfi_pos(b, flat));
        /* clearVolatile ends with setSpecies, which sets pokemon.speed to the
         * raw Speed stat (sim/pokemon.ts:1418); a fainted Pokemon is not
         * updated again. */
        r->speed_seen[flat] = dfi_raw_speed_key(dfi_at(b, flat));
        r->last_fainted = flat;
    }
    const bool any = r->faint_count != 0u;
    const bool by_move = r->last_faint_move;
    const uint32_t src = r->last_faint_by;
    r->faint_count = 0u;
    r->faint_announced = 0u;
    if (!any) {
        return;
    }
    const uint32_t result = dfi_win_result(b, r->last_fainted);
    if (result != DFI_RESULT_NONE) {
        b->result = (uint8_t)result;
        r->ended = true;
        return; /* checkWin returns before AfterFaint (sim/battle.ts:2598) */
    }
    dfi_after_faint(r, length, by_move, src); /* after the queue is processed: the faints of this call are no longer queued */
}

/* The faintMessages after the hit loop (data/mods/champions/scripts.ts:546)
 * shows the faints so far; their processing stays at the end of the action
 * (dfi_process_faints), where the engine runs it for the whole action. With
 * the attacker at 0 HP (a Rocky Helmet) that faintMessages also checks the
 * win (sim/battle.ts:2593-2598): the result is shown here, before the rest
 * of the action, which the reference still runs and shows (a target's
 * Emergency Exit, :578-590). */
static void dfi_announce_faints(dfi_run *r, bool check_win)
{
    const uint32_t length = r->faint_count - r->faint_announced; /* the faints this call shows */
    for (uint32_t i = r->faint_announced; i < r->faint_count; ++i) {
        dfi_emit_plain(r, DUOFORGE_EVENT_FAINT, r->faint_queue[i]); /* [faint] */
        /* Destiny Bond's KO belongs to faintMessages too: the attacker's faint is queued here and shown in this loop, before any
         * recoil of the attacker's move (sim/battle-actions.ts:976-982, the faintMessages before applyRecoilDamage). */
        dfi_destiny_bond_ko(r, r->faint_queue[i]);
    }
    r->faint_announced = r->faint_count;
    if (check_win && r->faint_count != 0u) {
        const uint32_t result = dfi_win_result(r->b, r->faint_queue[r->faint_count - 1u]);
        if (result != DFI_RESULT_NONE) {
            duoforge_event e = dfi_event_make(DUOFORGE_EVENT_RESULT, DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)result; /* wide-operands-reviewed: <= 3 */
            dfi_emit(r, &e); /* [win] */
            r->early_result = result;
            return; /* faintMessages returns after checkWin: no AfterFaint (sim/battle.ts:2598) */
        }
    }
    dfi_after_faint(r, length, r->last_faint_move, r->last_faint_by);
}

/* Whether a faintMessages inside the current action already showed the
 * faint at `flat`; the reference processed it there, so from then on that
 * Pokemon is not active (sim/battle.ts:2566). */
static bool dfi_faint_shown(const dfi_run *r, uint32_t flat)
{
    for (uint32_t i = 0u; i < r->faint_announced; ++i) {
        if (r->faint_queue[i] == flat) {
            return true;
        }
    }
    return false;
}

#endif
