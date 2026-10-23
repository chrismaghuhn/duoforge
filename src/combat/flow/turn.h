#ifndef DUOFORGE_COMBAT_FLOW_TURN_H
#define DUOFORGE_COMBAT_FLOW_TURN_H

/* Private flow implementation (restructure step 4, flow): the turn: requests, faint checks, pivots, forced switches,
 * end of turn, turn start and the turn loop. Split from src/combat/turn.c@c02189e7; included by turn.c where the code
 * stood, so its dependencies and the turn order are unchanged. */
#include "combat/run_internal.h"

static void dfi_clear_requests(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &b->sides[s];
        side->requested_slots = 0u;
        side->sealed = 0u;
        side->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        side->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
    }
    b->queue_len = 0u;
    for (uint32_t i = 0u; i < DFI_QUEUE_CAPACITY; ++i) {
        b->queue[i] = (dfi_queue_record){0u, 0u, 0u, 0u, 0u, 0u, 0u};
    }
}

static duoforge_status dfi_next_epoch(struct duoforge_battle *b)
{
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->request_epoch, 1u, &epoch) || epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->request_epoch = epoch;
    return DUOFORGE_OK;
}

/* checkFainted (sim/battle.ts:2524-2530): a fainted Pokemon keeps its
 * status until the turn's actions are done (its burn handler still takes
 * part in the residual order); then the status is gone. */
static void dfi_check_fainted(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            if (sd->members[m].hp == 0u) {
                sd->members[m].status = (uint8_t)DFI_STATUS_NONE;
                sd->members[m].status_counter = 0u;
                b->tail.sides[s].sleep_cant[m] = 0u; /* decision 0066 */
            }
        }
    }
}

static bool dfi_has_reserve(const struct duoforge_battle *b, uint32_t side);

/* A switch request while actions are still queued (sim/battle.ts:
 * 2876-2915): a side with flagged positions but no reserve loses its flags;
 * the other sides with flagged positions answer for exactly those positions,
 * and the rest of the queue waits. A flagged position holds a standing
 * Pokemon (Parting Shot, Emergency Exit) or, after a pass at a REPLACEMENT,
 * a fainted one (checkFainted): then the side is asked again right after the
 * switch, before the newcomer's entry. */
/* A side with a pending pivot can answer it: a flagged slot needs a living reserve, a Revival Blessing slot a brought
 * fainted member (the request is made even with no living reserve, sim/battle.ts 2882-2891). */
static bool dfi_side_can_answer(struct duoforge_battle *b, uint32_t s)
{
    const dfi_side *sd = &b->sides[s];
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (sd->positions[p].switch_flag == DFI_SWITCH_REVIVE_BLESSING) {
            for (uint32_t x = 0u; x < DUOFORGE_MAX_ROSTER && x < sd->member_count; ++x) {
                if (((uint32_t)sd->brought_mask >> x & 1u) != 0u && sd->members[x].hp == 0u) {
                    return true;
                }
            }
        } else if (sd->positions[p].switch_flag != 0u && dfi_has_reserve(b, s)) {
            return true;
        }
    }
    return false;
}

static bool dfi_pivot_pending(struct duoforge_battle *b)
{
    bool pending = false;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        if (sd->positions[0].switch_flag == 0u && sd->positions[1].switch_flag == 0u) {
            continue;
        }
        if (dfi_side_can_answer(b, s)) {
            pending = true;
        } else {
            sd->positions[0].switch_flag = 0u;
            sd->positions[1].switch_flag = 0u;
        }
    }
    return pending;
}

static duoforge_status dfi_pivot(struct duoforge_battle *b)
{
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->request_epoch, 1u, &epoch) || epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    b->request_epoch = epoch;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    uint32_t mask = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *sd = &b->sides[s];
        uint32_t slots = 0u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_member *m = dfi_at(b, s * 2u + p);
            if (sd->positions[p].switch_flag != 0u && m != NULL) {
                slots |= 1u << p;
            } else {
                sd->positions[p].switch_flag = 0u;
            }
        }
        sd->requested_slots = (uint8_t)slots; /* <= 3 */
        sd->sealed = 0u;
        sd->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        sd->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        mask |= slots != 0u ? 1u << s : 0u;
    }
    b->request_mask = (uint8_t)mask; /* <= 3 */
    return DUOFORGE_OK;
}

/* The answer to a PIVOT (commitChoices): speeds are taken again, the new
 * switches (instaswitch) go in front of the stored rest of the turn. */
static duoforge_status dfi_resume_pivot(dfi_run *r, const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT])
{
    struct duoforge_battle *b = r->b;
    duoforge_status st = dfi_update_speeds(r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_queue_record fresh[DFI_POSITIONS];
    uint32_t k = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        if (((uint32_t)b->request_mask >> s & 1u) == 0u) {
            continue;
        }
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const duoforge_slot_command *sc = &responses[s].slots[slot];
            if (sc->kind == DUOFORGE_SLOT_REVIVE) {
                /* the answer ends the request: the flag goes (choice of a revive, sim/side.ts:960-977) */
                fresh[k] = (dfi_queue_record){0u, (uint8_t)DFI_Q_REVIVE, (uint8_t)s, (uint8_t)slot, 0u, 0u, sc->reserve};
                k += 1u;
                b->sides[s].positions[slot].switch_flag = 0u;
            } else if (sc->kind == DUOFORGE_SLOT_SWITCH) {
                fresh[k] = (dfi_queue_record){0u, (uint8_t)DFI_Q_SWITCH_IN, (uint8_t)s, (uint8_t)slot, 0u, 0u,
                                              sc->reserve};
                k += 1u;
            } else if (((uint32_t)b->sides[s].requested_slots >> slot & 1u) == 0u) {
                b->sides[s].positions[slot].switch_flag = 0u;
            }
            /* A requested slot that passes keeps its flag (choosePass,
             * sim/side.ts:1330-1357): with two flagged slots and one reserve
             * (Flip Turn and Emergency Exit on one side, Team C), the side is
             * asked again after the switch, the Pokemon that left now being
             * a reserve (dfi_pivot_pending). */
        }
    }
    if ((uint32_t)b->queue_len + k > DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_INVARIANT;
    }
    for (uint32_t i = b->queue_len; i > 0u; --i) {
        b->queue[i + k - 1u] = b->queue[i - 1u];
    }
    for (uint32_t i = 0u; i < k; ++i) {
        b->queue[i] = fresh[i];
    }
    b->queue_len = (uint8_t)((uint32_t)b->queue_len + k); /* wide-operands-reviewed: <= 12 */
    /* Two Emergency Exits in one action (one on each side) switch in Speed
     * order. */
    return k > 1u ? dfi_sort_front(r, k) : DUOFORGE_OK;
}

/* The battle is over: TERMINAL with its result, nobody requested. */
static duoforge_status dfi_terminal(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    if (r->early_result == DFI_RESULT_NONE) {
        duoforge_event e = dfi_event_make(DUOFORGE_EVENT_RESULT, DUOFORGE_NO_POSITION);
        e.detail = b->result; /* [win] or [tie]: DFI_RESULT_* are the public values */
        dfi_emit(r, &e);
    } else if (r->early_result != b->result) {
        return DUOFORGE_E_INVARIANT; /* nothing revives, so the hit loop's result stands */
    }
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_pos(b, flat)->switch_flag = 0u; /* no pivot after the end */
    }
    dfi_check_fainted(b);
    const duoforge_status st = dfi_next_epoch(b);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_clear_requests(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL;
    b->request_mask = 0u;
    return DUOFORGE_OK;
}

/* The turn limit: the battle ties when endTurn makes the turn counter pass it (sim/battle.ts:1839). */
#define DFI_TURN_LIMIT 1000u

static duoforge_status dfi_end_turn(dfi_run *r)
{
    struct duoforge_battle *b = r->b;
    uint32_t turn = 0u;
    uint32_t epoch = 0u;
    if (!dfi_add_u32(b->turn, 1u, &turn) || turn > UINT16_MAX || !dfi_add_u32(b->request_epoch, 1u, &epoch) ||
        epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    /* The Endless Battle Clause of the singles reference format ([Gen 9 Champions] OU, Standard AG,
     * data/mods/champions/rulesets.ts:2-8) is checked in nextTurn from turn 101 on (sim/battle.ts:1836, 1854-1903: the
     * staleness of every Pokemon, then a tie or a loss). The engine does not model it, so a singles battle that reaches
     * turn 101 is refused here, by name of the rule, before any change (decision 0083 section 6). The turn limit of every
     * format (below) is checked before the clause in the pin, but a singles battle never gets past turn 100 to reach it. */
    if (dfi_context_singles(r->ctx) && turn > 100u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    b->turn = (uint16_t)turn;
    /* endTurn: newlySwitched ends (sim/battle.ts:1673; Team C), and DisableMove runs for every active Pokemon
     * (sim/battle.ts:1691), where choicelock ends for a holder without its Choice item. */
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_choice_lock_ends(b, flat);
        dfi_active_slot *pos = dfi_pos(b, flat);
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~DFI_VOL_NEWLY_SWITCHED); /* wide-operands-reviewed */
        /* statsRaisedThisTurn is cleared at the turn's end (sim/battle.ts:1678, endTurn): the raised bit is per turn */
        dfi_tail_pos *rt = &b->tail.sides[flat / 2u].positions[flat % 2u];
        rt->position_flags = (uint8_t)((uint32_t)rt->position_flags & ~(uint32_t)(DFI_POSFLAG_STATS_RAISED | DFI_POSFLAG_LOWERED | DFI_POSFLAG_HURT)); /* wide-operands-reviewed */
        /* statsLoweredThisTurn (sim/battle.ts:1679) and hurtThisTurn (sim/battle.ts:1682) are cleared here too (G88) */
        /* moveLastTurnResult = moveThisTurnResult, then this turn's is undefined (sim/battle.ts:1674-1675). The unclassified
         * bit moves with the result (step G42). */
        dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
        const uint32_t mr = tp->move_result;
        tp->move_result = (uint8_t)(((mr & DFI_MOVE_RESULT_VALUE_MASK) << DFI_MOVE_RESULT_LAST_SHIFT) | /* wide-operands-reviewed: <= 0x3F */
                                    ((mr & DFI_MOVE_RESULT_UNCLASSIFIED_NOW) != 0u ? DFI_MOVE_RESULT_UNCLASSIFIED_LAST : 0u));
    }
    /* The turn limit of every format (decision 0015 entry 5dt): endTurn raises the counter (sim/battle.ts:1624), runs the
     * per-active updates above (:1665-1771), then maybeTriggerEndlessBattleClause (:1773) ties once the counter passes
     * 1000 (:1839-1843: the |message| line and tie(); "not a part of Endless Battle Clause" :1838, so it comes before the
     * clause's rule test :1854 and holds for Reg M-C too) and endTurn returns: no |turn| line, no request. The RESULT
     * event is the |tie| line; the epoch advances once in dfi_terminal, as at every other end of a battle. The |message|
     * line and the |bigerror| warnings of turns 500-1000 (:1844-1852) carry no state and are not events. */
    if (turn > DFI_TURN_LIMIT) {
        b->result = (uint8_t)DFI_RESULT_TIE;
        return dfi_terminal(r);
    }
    b->request_epoch = epoch;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TURN;
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_TURN, DUOFORGE_NO_POSITION);
    e.id = b->turn; /* [turn] */
    dfi_emit(r, &e);
    b->request_mask = 3u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &b->sides[s];
        uint32_t occupied = 0u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            if (side->positions[p].occupant != DFI_OCCUPANT_NONE) {
                occupied |= 1u << p;
            }
        }
        side->requested_slots = (uint8_t)occupied; /* <= 3 */
        side->sealed = 0u;
        side->sealed_cmds[0] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
        side->sealed_cmds[1] = (dfi_slot_cmd){0u, 0u, 0u, 0u, 0u};
    }
    return DUOFORGE_OK;
}

/* A standing brought member that is not on the field. */
static bool dfi_has_reserve(const struct duoforge_battle *b, uint32_t side)
{
    const dfi_side *sd = &b->sides[side];
    for (uint32_t m = 0u; m < sd->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        if (((uint32_t)sd->brought_mask >> m & 1u) != 0u && sd->members[m].hp != 0u &&
            sd->positions[0].occupant != m && sd->positions[1].occupant != m) {
            return true;
        }
    }
    return false;
}

/* The queue is empty after the residual action or after the switches of
 * a REPLACEMENT: checkFainted and the switch request (sim/battle.ts:
 * 2524-2530, 2876-2915). A side with a fainted Pokemon on the field and a
 * reserve, or with an Emergency Exit after the residual action (`exits`,
 * by flat position), answers for those positions; otherwise the next turn
 * starts. A REPLACEMENT can follow a REPLACEMENT: when a side passed for a
 * fainted position and the Emergency Exit holder went to the bench. */
/* The drag in (step G46, sim/battle-actions.ts:162-174, dragIn). The reserve is drawn first, from the bench in side.pokemon
 * order (party_order past the active positions, one of them in singles; the non-fainted reserves; no draw when there is none:
 * sim/battle.ts:1570-1588), and only then the outgoing holder's DragOut runs: a block after the draw still consumed it (the
 * pin's order, mirrored on purpose). The
 * switch-in is switchIn with isDrag (no BeforeSwitchOut, no Update, the [drag] line), and its entry runs at once (gen 5+,
 * battle-actions.ts:153-155), together with the entries queued right behind it. */
static duoforge_status dfi_drag_in(dfi_run *r, uint32_t side, uint32_t slot)
{
    struct duoforge_battle *b = r->b;
    const dfi_side *sd = &b->sides[side];
    uint32_t brought = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        brought += (uint32_t)sd->brought_mask >> m & 1u;
    }
    uint32_t cand[DUOFORGE_MAX_ROSTER];
    uint32_t n = 0u;
    for (uint32_t k = dfi_context_active(r->ctx); k < brought && k < DUOFORGE_MAX_ROSTER; ++k) {
        const uint32_t e = dfi_party_entry(&b->tail, side, k);
        if (e != 0u && e <= DUOFORGE_MAX_ROSTER && sd->members[e - 1u].hp != 0u) {
            cand[n] = e - 1u;
            n += 1u;
        }
    }
    if (n == 0u) {
        return DUOFORGE_OK; /* getRandomSwitchable returns null: no draw, no switch */
    }
    uint32_t pick = 0u;
    duoforge_status st = dfi_draw(r->draws, DFI_SITE_DRAG, 0u, n, &pick);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t flat = side * 2u + slot;
    const dfi_member *old = dfi_at(b, flat);
    if (old == NULL || old->hp == 0u) {
        return DUOFORGE_OK; /* sim/battle-actions.ts:166-167 (the holder fainted: no drag) */
    }
    if (dfi_drag_blocked(r, flat)) {
        return DUOFORGE_OK; /* DragOut (Suction Cups, Guard Dog) returns null: the drag is not made */
    }
    uint32_t activation = 0u;
    st = dfi_switch_in(r, side, slot, cand[pick], true, false, &activation);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const dfi_member *entrant = dfi_at(b, flat);
    if (entrant == NULL) {
        return DUOFORGE_E_INVARIANT; /* dfi_switch_in placed the reserve in this slot */
    }
    r->speed_seen[flat] = dfi_entrant_speed_key(b, entrant); /* the entrant's cached speed (dfi_entrant_speed_key) */
    uint32_t entering = 1u << flat;
    while (b->queue_len > 0u && b->queue[0].kind == DFI_Q_RUN_SWITCH) {
        dfi_queue_record q;
        dfi_queue_pop(b, &q);
        entering |= 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
    }
    return dfi_run_entries(r, entering);
}

/* The phazing loop after an action (sim/battle.ts:2822-2827): each position in order, sides first, whose forceSwitchFlag is set
 * is dragged in if its Pokemon still stands; the flag is cleared either way. */
static duoforge_status dfi_phaze(dfi_run *r)
{
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            const uint32_t flat = side * 2u + slot;
            if (((r->drag_pending >> flat) & 1u) == 0u) {
                continue;
            }
            r->drag_pending &= ~(1u << flat);
            const dfi_member *m = dfi_at(r->b, flat);
            if (m != NULL && m->hp != 0u) {
                const duoforge_status st = dfi_drag_in(r, side, slot);
                if (st != DUOFORGE_OK) {
                    return st;
                }
            }
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_finish_turn(dfi_run *r, uint32_t exits)
{
    struct duoforge_battle *b = r->b;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        dfi_pos(b, flat)->switch_flag = 0u; /* the REPLACEMENT carries no flags */
    }
    dfi_check_fainted(b);
    uint32_t mask = 0u;
    uint32_t fainted[DUOFORGE_SIDE_COUNT] = {0u, 0u};
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER && b->sides[s].members[occupant].hp == 0u) {
                fainted[s] |= 1u << p;
            }
        }
        const uint32_t leaving = exits >> (s * 2u) & 3u;
        if ((fainted[s] != 0u && dfi_has_reserve(b, s)) || leaving != 0u) {
            fainted[s] |= leaving;
            mask |= 1u << s;
        }
    }
    if (mask == 0u) {
        return dfi_end_turn(r);
    }
    const duoforge_status st = dfi_next_epoch(b);
    if (st != DUOFORGE_OK) {
        return st;
    }
    dfi_clear_requests(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    b->request_mask = (uint8_t)mask; /* <= 3 */
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        if ((mask >> s & 1u) != 0u) {
            b->sides[s].requested_slots = (uint8_t)fainted[s]; /* <= 3 */
        }
    }
    return DUOFORGE_OK;
}

duoforge_status dfi_turn_start(const duoforge_context *ctx, struct duoforge_battle *b, dfi_draws *draws,
                               dfi_events *events)
{
    if (!dfi_context_is_closure(ctx)) {
        return DUOFORGE_OK;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE, 1u, 0u, 0u, 0u, DFI_POSITIONS, false, {0u, 0u, 0u, 0u, 0u, 0u}, false, false, DUOFORGE_OK, 0u, 0u};
    dfi_init_speeds(&r);
    /* The leads entered one by one (insertChoice updated each speed); their
     * entries run together. */
    duoforge_status st = dfi_update_speeds(&r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t entering = 0u;
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        entering |= dfi_at(b, flat) != NULL ? 1u << flat : 0u; /* their [switch] lines came first */
    }
    st = dfi_run_entries(&r, entering);
    if (st != DUOFORGE_OK) {
        return st;
    }
    /* The runSwitch action's epilogue runs its Update (sim/battle.ts:2860-2861). */
    st = r.ended ? DUOFORGE_OK : dfi_update(&r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (r.deferred != DUOFORGE_OK) {
        return r.deferred; /* step G69: a Symbiosis pass refused inside an Update (a berry of the residual) */
    }
    return r.ended ? DUOFORGE_E_INVARIANT : DUOFORGE_OK; /* nothing at the start can end the battle */
}

/* A TURN or REPLACEMENT bundle as queued actions, sorted like
 * commitChoices and the beforeTurn epilogue. */
/* Stalwart's tracksTarget (issue 541): a Pokemon on the field that has Stalwart, or holds the stone of a Mega forme with it, can
 * aim a move of this turn at its original target. Skill Swap can hand the ability on only among these. */
static bool dfi_tracking_possible(struct duoforge_battle *b)
{
    for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
        const dfi_member *m = dfi_at(b, flat);
        if (m == NULL || m->hp == 0u) {
            continue;
        }
        const uint32_t mega = m->is_mega != 0u ? DFI_FORME_NONE : dfi_mega_of(m->species_id, m->item);
        if (dfi_ability(b, m, DFI_ABILITY_STALWART) ||
            (mega != DFI_FORME_NONE && dfi_pool_formes[mega].ability == DFI_ABILITY_STALWART)) {
            return true;
        }
    }
    return false;
}

/* resolveAction's originalTarget (sim/battle-queue.ts:273, getAtLoc of the chosen location) as bits 2-4 of a MOVE record's
 * reserve (DFI_QRES_ORIGINAL_*): the occupant's roster index + 1, or none. */
static uint8_t dfi_original_target_code(const struct duoforge_battle *b, uint32_t target)
{
    uint32_t code = DFI_QRES_ORIGINAL_NONE;
    if (target < DFI_POSITIONS) {
        const uint32_t occ = b->sides[target / 2u].positions[target % 2u].occupant;
        code = occ < DUOFORGE_MAX_ROSTER ? occ + 1u : DFI_QRES_ORIGINAL_NONE;
    }
    return (uint8_t)(code << DFI_QRES_ORIGINAL_SHIFT); /* wide-operands-reviewed: <= 28 */
}

static duoforge_status dfi_queue_choices(dfi_run *r, const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT],
                                         bool replacement)
{
    struct duoforge_battle *b = r->b;
    const bool tracking = dfi_tracking_possible(b);
    /* The actions in the reference's order of addition: side 0 slot a, b,
     * then side 1 (sim/battle.ts:2998-3022); a pass adds none. */
    b->queue_len = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const bool requested = ((uint32_t)b->request_mask >> s & 1u) != 0u;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            dfi_slot_cmd c = {0u, 0u, 0u, 0u, 0u};
            if (requested) {
                const duoforge_slot_command *sc = &responses[s].slots[slot];
                c = (dfi_slot_cmd){sc->kind, sc->move_slot, sc->target, sc->mega, sc->reserve};
            } else if (b->sides[s].sealed != 0u) {
                c = b->sides[s].sealed_cmds[slot];
            }
            if (c.kind == DFI_SLOT_PASS && replacement && requested &&
                ((uint32_t)b->sides[s].requested_slots >> slot & 1u) != 0u) {
                /* A pass adds no action (resolveAction), so a fainted
                 * position keeps checkFainted's switch flag. */
                const dfi_member *m = dfi_at(b, s * 2u + slot);
                if (m != NULL && m->hp == 0u) {
                    b->sides[s].positions[slot].switch_flag = (uint8_t)DFI_SWITCH_FAINTED;
                }
            }
            if (c.kind == DFI_SLOT_NONE || c.kind == DFI_SLOT_PASS) {
                continue;
            }
            uint32_t kind = DFI_Q_MOVE;
            if (c.kind == DFI_SLOT_SWITCH) {
                if (dfi_support.switching == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                kind = replacement ? DFI_Q_SWITCH_IN : DFI_Q_SWITCH;
            } else if (c.kind != DFI_SLOT_MOVE || replacement) {
                return DUOFORGE_E_UNSUPPORTED;
            }
            const bool move = kind == DFI_Q_MOVE;
            if (move && c.mega != 0u) {
                /* resolveAction unshifts the megaEvo action before the move. */
                if (dfi_support.mega_evolution == 0u) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                b->queue[b->queue_len] = (dfi_queue_record){b->sides[s].positions[slot].activation_id,
                                                            (uint8_t)DFI_Q_MEGA, (uint8_t)s, (uint8_t)slot, 0u, 0u,
                                                            0u};
                b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 6 */
            }
            b->queue[b->queue_len] = (dfi_queue_record){
                kind == DFI_Q_SWITCH_IN ? 0u : b->sides[s].positions[slot].activation_id, (uint8_t)kind, (uint8_t)s,
                (uint8_t)slot, move ? c.move_slot : 0u, move ? c.target : 0u,
                move ? (tracking ? dfi_original_target_code(b, c.target) : 0u) : c.reserve};
            b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 6 */
        }
    }
    duoforge_status st = DUOFORGE_OK;
    if (!replacement) {
        b->queue[b->queue_len] = (dfi_queue_record){0u, (uint8_t)DFI_Q_RESIDUAL, 0u, 0u, 0u, 0u, 0u};
        b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 5 */
    }
    /* Sorted when the choices are committed; in a turn again after the
     * beforeTurn action, whose epilogue sorts before a first move
     * (sim/battle.ts:2940-2947, 2917-2926). A replacement has no beforeTurn. */
    if (b->queue_len > 0u) {
        st = dfi_sort_queue(r);
    }
    /* The beforeTurn action's epilogue runs its Update first
     * (sim/battle.ts:2860-2861). */
    if (st == DUOFORGE_OK && !replacement) {
        st = dfi_update(r);
    }
    if (st == DUOFORGE_OK && !replacement && b->queue[0].kind == DFI_Q_MOVE) {
        st = dfi_sort_queue(r);
    }
    return st;
}

duoforge_status dfi_turn_run(const duoforge_context *ctx, struct duoforge_battle *b,
                             const duoforge_side_choice responses[DUOFORGE_SIDE_COUNT], dfi_draws *draws,
                             dfi_events *events)
{
    const bool replacement = b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT;
    const bool pivot = b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT;
    if (!dfi_context_is_closure(ctx) || (b->boundary_kind != DUOFORGE_BOUNDARY_TURN && !replacement && !pivot)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (!dfi_closure_battle_supported(&dfi_support, b) || ((replacement || pivot) && dfi_support.switching == 0u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    dfi_run r = {ctx, b, draws, {0u, 0u, 0u, 0u}, 0u, 0u, 0u, false, DFI_RESULT_NONE, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}, events, UINT32_MAX, false, DFI_MOVE_TARGET_NONE, 1u, 0u, 0u, 0u, DFI_POSITIONS, false, {0u, 0u, 0u, 0u, 0u, 0u}, false, false, DUOFORGE_OK, 0u, 0u};
    dfi_init_speeds(&r);
    duoforge_status st = DUOFORGE_OK;
    uint32_t exits = 0u; /* Emergency Exit after the residual action */
    uint32_t switch_flat = DFI_POSITIONS; /* the Pokemon of the runSwitch action that ran (Emergency Exit after it) */
    uint32_t switch_hp = 0u;              /* its HP before the action (sim/battle.ts:2666) */
    if (pivot) {
        st = dfi_resume_pivot(&r, responses);
    } else {
        st = dfi_queue_choices(&r, responses, replacement);
    }
    if (st != DUOFORGE_OK) {
        return st;
    }
    while (b->queue_len > 0u) {
        dfi_queue_record q;
        dfi_queue_pop(b, &q);
        if (q.kind == DFI_Q_MOVE) {
            bool ran = false;
            /* lockedmove (step G56): a locked user whose move is stopped before its use keeps the lock, not restarted, into the
             * residual, whose countdown ends it there with onEnd (sim/battle.ts:515-522; issue 606, decision 0015 5dv). A
             * sleeping holder goes on and its lock gets the unused-lock bit (DFI_SINGLE_TURN_LOCK_UNUSED, in the state, so a
             * PIVOT pause before the residual keeps it); the other stops (a flinch, a freeze, a full paralysis, a confusion
             * self-hit) stay refused: lifting them is its own change. */
            uint32_t mover = (uint32_t)q.side * 2u + (uint32_t)q.slot;
            const bool lock_before = b->tail.sides[mover / 2u].positions[mover % 2u].lock_turns != 0u;
            st = dfi_run_move(&r, &q, &ran);
            if (st != DUOFORGE_OK) {
                return st;
            }
            /* An Ally Switch (step G80) moved the mover to the other slot of its side, with its queued action (issue 541): the
             * epilogue below (AfterMove, the lock's countdown) is the mover's, at its new slot, not the partner's. */
            const uint32_t moved_to = (uint32_t)q.side * 2u + (1u - (uint32_t)q.slot);
            if (dfi_pos(b, mover)->activation_id != q.activation_id && dfi_pos(b, moved_to)->activation_id == q.activation_id) {
                q.slot = (uint8_t)(1u - (uint32_t)q.slot); /* wide-operands-reviewed: 0 or 1 */
                mover = moved_to;
            }
            if (lock_before && !r.move_used) {
                const dfi_member *mm = dfi_at(b, mover);
                if (mm != NULL && mm->hp != 0u && mm->status != DFI_STATUS_SLP) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                dfi_tail_pos *mt = &b->tail.sides[mover / 2u].positions[mover % 2u];
                if (mm != NULL && mm->hp != 0u && mt->lock_turns != 0u) {
                    mt->single_turn = (uint8_t)((uint32_t)mt->single_turn | DFI_SINGLE_TURN_LOCK_UNUSED); /* wide-operands-reviewed: a byte mask */
                }
            }
            if (!ran) {
                continue; /* runAction returned before its epilogue */
            }
            /* AfterMove after a used move: White Herb's onAnyAfterMove (Team
             * C; sim/battle-actions.ts:311-312). runEvent collects the Any
             * handlers only while the user or runMove's target is active
             * (sim/battle.ts:1053), and a Pokemon whose faint the hit loop
             * showed is not (:2566). With a spread move's undrawn target that
             * is unknown: E_UNSUPPORTED when the handlers would do anything
             * (with the data only a Rocky Helmet makes the user faint there,
             * against a single-target contact move). */
            if (r.move_used) {
                const uint32_t user = (uint32_t)q.side * 2u + (uint32_t)q.slot;
                bool collected = true;
                if (dfi_faint_shown(&r, user)) {
                    if (r.move_target == DFI_MOVE_TARGET_SPREAD && dfi_herbs_matter(&r)) {
                        return DUOFORGE_E_UNSUPPORTED;
                    }
                    collected = r.move_target < DFI_POSITIONS && !dfi_faint_shown(&r, r.move_target);
                }
                /* lockedmove's confusion (step G56) at the end of this use, after the White Herb's AnyAfterMove: when both would
                 * print (a holder whose stat is down, and a lock that ends with a count of 1 or less), their order is not modelled. */
                const bool lock_ends_here = b->tail.sides[user / 2u].positions[user % 2u].lock_turns != 0u &&
                                            ((r.lock_restarted >> user) & 1u) == 0u && b->tail.sides[user / 2u].positions[user % 2u].lock_turns <= 1u &&
                                            dfi_at(b, user) != NULL && dfi_at(b, user)->hp != 0u;
                if (lock_ends_here && dfi_herbs_matter(&r)) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                if (collected) {
                    st = dfi_herb_event(&r, user);
                    if (st != DUOFORGE_OK) {
                        return st;
                    }
                }
                /* lockedmove (step G56, data/conditions.ts:253-285). A use that restarted the lock (lock_restarted: a hit with a
                 * count of 2 or more, or the start) keeps it: its count goes down by the residual of this turn, which is done
                 * here, at the use, so that no residual of a later call (a replacement's pause) has to remember the restart.
                 * A use that did not restart it: onAfterMove removes it at duration 1 (after any result), and onEnd confuses
                 * when the count is 1 or less. A fainted user has no handler (its volatiles were cleared). */
                const dfi_member *um = dfi_at(b, user);
                const bool restarted_use = ((r.lock_restarted >> user) & 1u) != 0u;
                r.lock_restarted &= ~(1u << user); /* wide-operands-reviewed: user < 4 */
                if (b->tail.sides[user / 2u].positions[user % 2u].lock_turns != 0u && um != NULL && um->hp != 0u) {
                    if (restarted_use) {
                        dfi_tail_pos *ut = &b->tail.sides[user / 2u].positions[user % 2u];
                        ut->lock_turns = (uint8_t)((uint32_t)ut->lock_turns - 1u); /* wide-operands-reviewed: >= 1 */
                    } else {
                        if (b->tail.sides[user / 2u].positions[user % 2u].lock_turns <= 1u && dfi_herbs_matter(&r)) {
                            /* the White Herb's AnyAfterMove and this confusion would both print: the order is not modelled */
                            return DUOFORGE_E_UNSUPPORTED;
                        }
                        st = dfi_lock_end(&r, user);
                        if (st != DUOFORGE_OK) {
                            return st;
                        }
                    }
                }
            }
        } else if (q.kind == DFI_Q_REVIVE) {
            st = dfi_run_revive(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_SWITCH || q.kind == DFI_Q_SWITCH_IN || q.kind == DFI_Q_INSTASWITCH) {
            st = dfi_run_switch(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_RUN_SWITCH) {
            /* runSwitch takes every entry queued right behind it. */
            uint32_t entering = 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
            switch_flat = (uint32_t)q.side * 2u + (uint32_t)q.slot;
            switch_hp = dfi_at(b, switch_flat) != NULL ? dfi_at(b, switch_flat)->hp : 0u;
            while (b->queue_len > 0u && b->queue[0].kind == DFI_Q_RUN_SWITCH) {
                dfi_queue_pop(b, &q);
                entering |= 1u << ((uint32_t)q.side * 2u + (uint32_t)q.slot);
            }
            st = dfi_run_entries(&r, entering);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_MEGA) {
            st = dfi_run_mega(&r, &q);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else if (q.kind == DFI_Q_RESIDUAL) {
            st = dfi_residual(&r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        } else {
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The epilogue: faints and the win rule; before a further
         * replacement nothing else; before a move action, speeds and
         * priorities are recomputed and the rest of the queue is sorted. */
        /* A move's own faintMessages (sim/battle-actions.ts:347, at the end of useMove, with its checkWin) comes before the
         * phazing loop of runAction (sim/battle.ts:2822-2827), so the faints of the move (an item's recoil included) and a
         * win they cause are shown first; the phazing still runs after a win (the reference drags after its [win]). The
         * other actions have no such step; the rest of the faints follow the phazing (dfi_process_faints). */
        if (q.kind == DFI_Q_MOVE) {
            const bool fresh = r.faint_announced < r.faint_count && r.early_result == DFI_RESULT_NONE;
            dfi_announce_faints(&r, fresh);
        }
        st = dfi_phaze(&r); /* the phazing loop of runAction, before the faints (sim/battle.ts:2822-2827; step G46) */
        if (st != DUOFORGE_OK) {
            return st;
        }
        dfi_process_faints(&r);
        if (r.ended) {
            return r.deferred != DUOFORGE_OK ? r.deferred : dfi_terminal(&r);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_SWITCH_IN) {
            continue;
        }
        st = dfi_update(&r); /* sim/battle.ts:2860-2861 */
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (q.kind == DFI_Q_RESIDUAL) {
            /* sim/battle.ts:2862-2867: after the Update, so a Sitrus Berry
             * eaten there keeps its holder in. */
            for (uint32_t flat = 0u; flat < DFI_POSITIONS; ++flat) {
                if (dfi_exits(b, flat, r.residual_hp[flat], r.drag_pending)) {
                    exits |= 1u << flat;
                    const duoforge_event e = dfi_ev(DUOFORGE_EVENT_ACTIVATE, flat, DUOFORGE_CAUSE_ABILITY,
                                                    1u + DFI_ABILITY_EMERGENCYEXIT, DUOFORGE_NO_POSITION);
                    dfi_emit(&r, &e); /* [-activate] ability: Emergency Exit */
                }
            }
        }
        if (q.kind == DFI_Q_RUN_SWITCH && switch_flat < DFI_POSITIONS) {
            /* sim/battle.ts:2871-2874: after the Update, the Pokemon of a runSwitch action that a hazard took from above half
             * its HP to half or less runs its EmergencyExit event (only the first Pokemon of the batch: the action's own). */
            dfi_emergency_exit(&r, switch_flat, switch_hp);
            if (b->queue_len == 0u && dfi_pos(b, switch_flat)->switch_flag == DFI_SWITCH_EMERGENCY_EXIT) {
                exits |= 1u << switch_flat; /* nothing is queued: the turn ends with a request for its replacement */
            }
            switch_flat = DFI_POSITIONS;
        }
        if (b->queue_len > 0u && dfi_pivot_pending(b)) {
            return r.deferred != DUOFORGE_OK ? r.deferred : dfi_pivot(b);
        }
        if (b->queue_len > 0u && b->queue[0].kind == DFI_Q_MOVE) {
            st = dfi_sort_queue(&r);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    if (r.deferred != DUOFORGE_OK) {
        return r.deferred; /* step G69: a Symbiosis refusal, see dfi_run.deferred */
    }
    return dfi_finish_turn(&r, exits);
}

#endif
