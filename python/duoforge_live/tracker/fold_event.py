"""One event into the tracker's fields.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import lines
from ..data import trace_to_c
from .constants import (C, CHARGE_TURNS, DISABLE_TURNS, ENCORE_TURNS, EV, FIELD_TURNS, FLAG, FLAG_FOLLOW_ME,
                        FLAG_HELPING_HAND, FLAG_UNBURDEN, FREEZE_TURNS, _HAZARD, HEAL_BLOCK_TURNS, HITS_TAKEN_MAX,
                        ITEM_NOW_NONE, MOVE_SLOT_NONE, NOPOS, _PASSED, REVEALED_ITEM_CONSUMED, REVEALED_MEGA,
                        ROSTER_NONE, SCREEN_EXTENDER, SCREEN_TURNS, SCREEN_TURNS_CLAY, _SIDE_CONDITION, STAGE_NEUTRAL,
                        STALL_DURATION, STALL_LEVEL_MAX, STATUS, SWITCH_EMERGENCY_EXIT, SWITCH_FAINTED, SWITCH_MOVE,
                        TAILWIND_TURNS, TARGET_NONE, TAUNT_TURNS, _TERRAIN, TOXIC_STAGE_MAX, YAWN_TURNS)
from .state import SheetContradiction


class _EventFold:
    def _fold_event(self, e, herb=None):
        kind, pos, ident, ident2 = e[0], e[1], e[4], e[5]
        hp, hp_kind, hp_flag, status, detail, amount, flags = e[6], e[8], e[9], e[10], e[11], e[12], e[13]
        foe = pos != NOPOS and pos // 2 != self.side
        public = foe or (self._spectator and pos != NOPOS)  # folded from the public lines
        if kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"] and pos != NOPOS and self._as_pending == pos:
            # Ally Switch's consecutive roll failed (onPrepareHit false, -fail|X with [still]): the volatile is deleted, the
            # next use starts at level 1 (data/moves.ts:326-357; the engine: dfi_ally_switch_prepare)
            self._at(pos).ally_level = self._at(pos).ally_turns = 0
            self._as_pending = None
        if kind == EV["TURN"]:
            self._turn = ident
            self._after_upkeep = False
            self._turn_scoped.clear()
            self._guards.clear()
            for side in (0, 1):
                for p in self._positions[side]:
                    # endTurn: newlySwitched ends, and the raised flag (statsRaisedThisTurn: not before turn 1, the
                    # battle's start keeps its entry boosts' flag); every standing occupant has its move ahead
                    p.newly_switched = 0
                    if ident > 1:
                        p.raised = p.lowered = p.hurt = 0  # statsLoweredThisTurn and hurtThisTurn as well (G88)
                    p.move_queued = p.occupant != ROSTER_NONE and not p.fainted
                    p.turn_done = p.occupant == ROSTER_NONE or p.fainted
                    # endTurn's DisableMove: choicelock ends for a holder without its Choice item (dfi_end_turn)
                    if p.choice_slot != MOVE_SLOT_NONE and p.occupant != ROSTER_NONE:
                        m = self._member(side)[p.occupant]
                        if m.item_used or self._item_of(m) not in self._choice_items:
                            p.choice_slot = MOVE_SLOT_NONE
        elif kind in (EV["SWITCH"], EV["DRAG"]):
            # A drag (Step G46) is a switch of the dragged-in member: the occupant is replaced and reset, the HP of the line.
            p = self._at(pos)
            self._trap_source_left(pos)
            if p.occupant != ROSTER_NONE:
                self._member(pos // 2)[p.occupant].toxic_stage = 0  # the leaving member's toxic counter ends with it
            passed = None
            if kind == EV["SWITCH"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._baton_pass:
                # Baton Pass (step G74, decision 0042; sim/pokemon.ts copyVolatileFrom): no line shows the copy; of
                # the base view's fields the receiver keeps the leaver's stages and confusion, of the folded view
                # extension what dfi_pass_give copies (_PASSED). The other copied volatiles are decision 0018 features,
                # which stopped the tracker at their start lines.
                passed = (list(p.stages), p.confused, {name: getattr(p, name) for name in _PASSED})
            p.occupant, p.flag, p.fainted = ident, 0, False
            p.reset()
            if passed is not None:
                p.stages, p.confused = passed[0], passed[1]
                for name, value in passed[2].items():
                    setattr(p, name, value)
            p.activation, p.move_actions = self._next_activation, 0  # entries are numbered in the order of their lines
            p.confused_action = False
            p.newly_switched, p.turn_done, p.move_queued = 1, True, False
            self._member(pos // 2)[ident].toxic_stage = 0  # tox's onSwitchIn
            self._next_activation += 1
            if pos // 2 != self.side and self._foe_leads[pos % 2] == ROSTER_NONE:
                self._foe_leads[pos % 2] = ident  # the foe's pick order starts with its leads
            if pos // 2 == self.side and self._party is not None and ident in self._party:
                i = self._party.index(ident)
                self._party[i], self._party[pos % 2] = self._party[pos % 2], self._party[i]
            m = self._member(pos // 2)[ident]
            if public:
                m.seen, m.hp_percent, m.hp_flag, m.status = True, hp, hp_flag, status
            else:
                m.seen = True
                self._own_display(m, hp, e[7])
        elif kind == EV["MOVE"]:
            p = self._at(pos)
            if ident == self._healing_wish and e[3] == trace_to_c.CAUSE["NONE"] and not flags & FLAG["STILL"]:
                # dfi_run_healing_wish: it runs (a reserve stands; a [still] -fail is the refusal for none) and sets the
                # slot's wish; a second one finds it set and changes nothing
                p.wish = 1
            self._as_pending = pos if ident == self._ally_move else None
            if e[3] == trace_to_c.CAUSE["NONE"]:
                # an action of the user (runMove's activeMoveActions++, dfi_run_move); a move line with cause ABILITY is
                # Magic Bounce's reflection (useMove), no action of the holder
                p.acted = 1
                self._move_action(p)
                p.turn_done, p.move_queued = True, False
                if ident in self._move_pivots:
                    p.flag = self._move_pivots[ident]  # a -fail line that follows takes it back
            self._last_move = (pos, ident, e[2])
            if e[3] != trace_to_c.CAUSE["ABILITY"]:
                # the next action ends Glaive Rush's drawback (glaiverush onBeforeMove, step G19). A move line with cause
                # ABILITY is Magic Bounce's reflection, no action of its own; Dancer, whose copy would be one, is not
                # modelled by the engine
                p.glaive_rush = 0
            if e[3] == trace_to_c.CAUSE["NONE"]:
                p.last_move = ident  # runMove's moveUsed, a locked turn too; not a move another effect makes it use
            m = self._occupant(pos)
            if e[3] != trace_to_c.CAUSE["ABILITY"]:
                # the move Encore takes (pokemon.moveUsed after runMove's PP, a locked turn included); a move that Magic
                # Bounce reflects (cause ABILITY, step G57) is not its user's own move
                if ident in m.sheet["moves"]:
                    p.last_slot = m.sheet["moves"].index(ident) + 1
                else:
                    p.last_slot = 5 if ident == self._struggle else None
            if not flags & FLAG["LOCKED"] and e[3] != trace_to_c.CAUSE["ABILITY"] and ident in m.sheet["moves"]:
                # a move Magic Bounce reflects (cause ABILITY, step G57) costs its holder no PP: the pin's useMove
                # deducts none, as DuoForge's knowledge fold
                m.uses[m.sheet["moves"].index(ident)] += 1 + self._pressure_extra(pos, ident, e[2], flags)
            if ident in self._guard_moves and not flags & FLAG["LOCKED"]:
                # Wide Guard and Quick Guard add the stall volatile when they run (data/moves.ts onHitSide
                # addVolatile('stall')), also when the side has the guard already (no -singleturn line then), the
                # counter a Protect reads: protect_chain counts them (g7_wide_guard_ally). A -fail undoes it.
                p.guard_undo = (p.chain, p.stall)
                p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
                p.stall = STALL_DURATION
            holds_choice = not m.item_used and self._item_of(m) in self._choice_items
            if p.choice_slot != MOVE_SLOT_NONE and not holds_choice and e[3] != trace_to_c.CAUSE["ABILITY"]:
                p.choice_slot = MOVE_SLOT_NONE  # choicelock's onBeforeMove: its Choice item is gone (a Trick, Knock Off)
            if self.check_foe_sheet and pos // 2 != self.side and e[3] == trace_to_c.CAUSE["NONE"] and ident != self._struggle:
                # A drawn foe sheet (decision 0081, cts.ParticleTracker) the line contradicts, where the open-sheet fold
                # would go on in silence: an own move off the sheet, or another move than the one a Choice item locked
                if ident not in m.sheet["moves"]:
                    raise SheetContradiction("move-not-on-set")
                if p.choice_slot != MOVE_SLOT_NONE and holds_choice and m.sheet["moves"][p.choice_slot] != ident:
                    raise SheetContradiction("choice-lock", member=p.occupant)
            if (p.choice_slot == MOVE_SLOT_NONE and holds_choice and ident in m.sheet["moves"]
                    and e[3] != trace_to_c.CAUSE["ABILITY"]):
                # A Choice item locks its holder into the move of its |move| line (data/items.ts onModifyMove,
                # set right before the line) until it leaves (c07 battles, Choice Scarf).
                p.choice_slot = m.sheet["moves"].index(ident)
        elif kind == EV["ACTIVATE"]:
            if e[3] == trace_to_c.CAUSE["ABILITY"] and ident2 == self.data.tables["ABILITY"]["EMERGENCYEXIT"] + 1:
                # it leaves: asked to switch (id2 names an ability only with cause ABILITY)
                self._at(pos).flag = SWITCH_EMERGENCY_EXIT
            elif e[3] == trace_to_c.CAUSE["ABILITY"] and ident2 == self._symbiosis:
                # Symbiosis (step G69): the holder passes its item (id: the item + 1) to its ally ([of], `other`), which
                # has used its own up; the holder then holds nothing
                holder = self._occupant(pos)
                holder.item_now = ITEM_NOW_NONE
                holder.revealed |= REVEALED_ITEM_CONSUMED
                if public:
                    holder.item_used = 1
                self._item_received(e[2], ident, public)
            elif e[3] == trace_to_c.CAUSE["MOVE"] and ident2 in self._trap_moves:
                self._trap_start(pos, e[2], ident2)  # the partial trap's start (step G90)
            elif e[3] == trace_to_c.CAUSE["MOVE"] and ident2 in (self._feint, self._phantom_force):
                # Feint broke something (step G28, sim/battle-actions.ts hitStepBreakProtect, printed only then; Phantom
                # Force's `[broken]` line the same, step G58): the target's own Protect (its flag) and its stall
                # volatile (chain and stall, a guard_undo that is no longer open), and the Wide Guard and Quick Guard of
                # the target's whole side, a partner's included. Only the target's stall goes: a partner that set the
                # guard keeps its own chain.
                p = self._at(pos)
                p.protecting = p.chain = p.stall = 0
                p.guard_undo = None
                for guard in ("WIDE_GUARD", "QUICK_GUARD"):
                    self._guards.discard((guard, pos // 2))
                    if not any(g[0] == guard for g in self._guards):
                        self._turn_scoped.discard(guard)
        elif kind == EV["FAINT"]:
            p = self._at(pos)
            self._trap_source_left(pos)
            p.reset()  # a faint clears the position's conditions; the occupant stays until replaced
            p.fainted = True
            # a faint takes a pivot flag (faint(): switchFlag = false); after the residual (Perish Song's) checkFainted asks
            # for the position at once
            p.flag = SWITCH_FAINTED if self._after_upkeep else 0
            p.move_actions = 0
            # a faint that no damage line announced (Perish Song's perish0, step G26): the display shows 0
            m = self._occupant(pos)
            m.hp_percent, m.hp_flag = 0, 0
            m.status, m.freeze_turns = 0, 0  # a fainted member has no status (the views show none; the record holds none)
            m.toxic = m.toxic_stage = 0
            m.sleep_cant = 0  # decision 0066: the sleep's count ends with it
        elif kind == EV["CANT"]:
            # An ability's block (Armor Tail) names its holder; the move's user, [of], took the action.
            blocked = e[3] == trace_to_c.CAUSE["ABILITY"]
            actor = self._at(e[2] if blocked else pos)
            if e[3] == trace_to_c.CAUSE["SLEEP"] and actor.occupant != ROSTER_NONE:
                self._member(pos // 2)[actor.occupant].sleep_cant += 1  # decision 0066: one more cant line of this sleep
            actor.acted = 1
            if not blocked:
                self._move_action(actor)  # a block follows the user's own [move] line: the same action
            actor.turn_done, actor.move_queued = True, False
            actor.glaive_rush = 0  # its action began: glaiverush's onBeforeMove ran first (step G19)
            if e[3] == trace_to_c.CAUSE["RECHARGE"]:
                self._at(pos).must_recharge = 0  # cant|X|recharge: mustrecharge's onBeforeMove ends it (step G17)
            if e[3] == trace_to_c.CAUSE["FREEZE"]:
                m = self._occupant(pos)
                m.freeze_turns = max(m.freeze_turns - 1, 0)
        elif kind == EV["TYPE_CHANGE"]:
            # Soak's single type (detail: its id) or Double Shock's ??? (detail DUOFORGE_TYPE_NONE, amount: the other
            # type + 1), step G11 and decision 0025, until the occupant leaves or Mega Evolves (the tail's soak_type).
            # A plain typechange line is Soak's only after a Soak move line (Magic Powder prints the same form).
            if e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._soak and (
                    self._last_move is None or self._last_move[1] != self._soak):
                raise lines.Stop("line:-start typechange (no Soak)")
            p = self._at(pos)
            p.type_now = (0, amount) if detail == trace_to_c.TYPE_NONE else (detail + 1, 0)
            p.type2 = amount if detail == trace_to_c.TYPE_NONE else 0  # setType replaces both types (Soak)
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_ATTRACT:
            # Attract (step G71, decision 0034): -start|X|Attract|[from] ability: Cute Charm|[of] Y (e[2] = Y's position) keeps Y's
            # member code on X; the visible ends (Mental Herb's and Oblivious's rows) clear it. The silent end (the source left) comes
            # as its own line (_silent_attract_end), and a switch or a faint of X clears it in _Position.reset.
            p = self._at(pos)
            if kind == EV["VOLATILE_START"]:
                holder = self._at(e[2])
                if holder.occupant == ROSTER_NONE:
                    raise lines.Stop("attract-source-unknown")  # the holder of [of] is not on the field
                p.attract = 1 + (e[2] // 2) * C["DUOFORGE_MAX_ROSTER"] + holder.occupant
                p.attract_from = e[2]  # the view's source position (step G87, decision 0080)
            else:
                p.attract, p.attract_from = 0, 0
        elif kind == EV["VOLATILE_END"] and detail == trace_to_c.VOLATILE_PARTIAL_TRAP:
            self._trap_end(pos, ident)  # the duration's end (step G90): the line names the move in `ident`
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_HEAL_BLOCK:
            # Heal Block (step G8, Psychic Noise): -start|X|move: Heal Block and -end|X|move: Heal Block (the duration,
            # Mental Herb); the occupant's leaving ends it with no line; its count is never shown
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, self._at(pos).heal_block, "heal_block")
            self._at(pos).heal_block = HEAL_BLOCK_TURNS if kind == EV["VOLATILE_START"] else 0
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_TAUNT:
            # Taunt (step G31): -start|X|move: Taunt and -end|X|move: Taunt (the duration, Mental Herb, Oblivious); the
            # occupant's leaving ends it with no line; the view shows its presence, the record its count: one more
            # when the target has been out for a turn and has no move left this turn (dfi_taunt)
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, p.taunt, "taunt")
            p.taunt = 0
            if kind == EV["VOLATILE_START"]:
                p.taunt = TAUNT_TURNS + (1 if not p.newly_switched and not p.move_queued else 0)
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_DISABLE:
            # Disable (step G27): -start|X|Disable|MOVE (also [from] ability: Cursed Body) bars MOVE's slot of the open
            # sheet; -end|X|Disable (the duration, Mental Herb) and the occupant's leaving end it; its count is never
            # shown. A barred move that is not on the sheet stops.
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, p.disable_turns, "disable")
                p.disable_slot = p.disable_turns = 0
            else:
                moves = self._occupant(pos).sheet["moves"]
                if ident not in moves:
                    raise lines.Stop("disable-move-unknown")
                p.disable_slot = moves.index(ident) + 1
                # its count (the record): one less when the target has its move ahead or Cursed Body sets it
                # (dfi_disable_start: the effect comes from the holder's own action in progress)
                by_ability = e[3] == trace_to_c.CAUSE["ABILITY"]
                p.disable_turns = DISABLE_TURNS - (1 if by_ability or p.move_queued else 0)
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_IMPRISON:
            self._at(pos).imprison = 1  # -start|X|move: Imprison (step G38): no end line, it ends with the occupant
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_LEECH_SEED:
            # -start|X|move: Leech Seed (step G84, decision 0047, no [of], no end line): the source is the user of the move
            # line before (the holder of a Magic Bounce reflection); a start after any other line is no case of the engine
            last = self._last_move
            if last is None or last[1] != self._leech_seed or last[0] == pos:
                raise lines.Stop("leech-seed-source-unknown")
            self._at(pos).leech_source = last[0] + 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_YAWN:
            self._at(pos).yawn = YAWN_TURNS  # -start|X|move: Yawn|[of] source (step G31); its end line is [silent], above
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_MUST_RECHARGE:
            self._at(pos).must_recharge = 1  # -mustrecharge|X: a recharge move hit (step G17)
        elif kind == EV["CONFUSED"]:
            p = self._at(pos)
            p.acted = 1
            p.glaive_rush = 0  # the action began (a confused self-hit shows no move line)
            self._move_action(p)
            p.confused_action = True  # the action's own move or [cant] line follows, or its self-hit
            p.turn_done, p.move_queued = True, False
        elif kind in (EV["DAMAGE"], EV["HEAL"]):
            m = self._occupant(pos)
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["CONFUSION"]:
                self._at(pos).confused_action = False  # the self-hit ends the action the confusion line began
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["NONE"] and self._last_move is not None \
                    and self._last_move[0] != pos:
                # timesAttacked: a damaging hit of another Pokemon's move (a -damage line without a source)
                user = self._at(self._last_move[0])
                if self._last_move[1] in self._hit_pivots and user.occupant != ROSTER_NONE and not user.fainted \
                        and self._can_switch(self._last_move[0] // 2):
                    user.flag = self._hit_pivots[self._last_move[1]]
                p = self._at(pos)
                p.hits_taken = min(p.hits_taken + 1, HITS_TAKEN_MAX)
                if (self._last_move[1] == self._knock_off and self._unburden is not None
                        and self._ability_at(pos) == self._unburden and not p.flags & FLAG_UNBURDEN
                        and self._item_of(m) and not m.item_used):  # takeItem of a holder without an item: no event
                    # Unburden's onTakeItem answers Knock Off before the item may refuse (a Mega Stone): the volatile can
                    # be set with no line; an -enditem that follows shows the usual case (_unburden_unseen, record.py)
                    p.unburden_unseen = True
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["LEECH_SEED"]:
                # the drain (dfi_leech_drain): `[of]` names the seed's source slot, or no `[of]` when an Ally Switch put the
                # holder on that slot (it drains into itself, issue 541); any other holder or source is no case of the engine
                # (a seed whose start the tracker did not see)
                source = self._at(pos).leech_source - 1
                if source < 0 or e[2] != (trace_to_c.NOPOS if source == pos else source):
                    raise lines.Stop("leech-seed-drain-source")
            if kind == EV["DAMAGE"] and hp != 0:
                self._hurt(pos, e[3])
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["POISON"] and m.toxic:
                m.toxic_stage = min(m.toxic_stage + 1, TOXIC_STAGE_MAX)  # tox's residual: the stage first, then the damage
            if public:
                m.hp_percent, m.hp_flag = hp, hp_flag
            else:
                self._own_display(m, hp, e[7])
            if kind == EV["HEAL"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._healing_wish:
                # dfi_wish_heal: the entrant's full heal ends the wish and its status (clearStatus, silent: no cure line)
                self._at(pos).wish = 0
                m.status, m.freeze_turns = 0, 0
                m.toxic = m.toxic_stage = 0
                m.sleep_cant = 0  # decision 0066
        elif kind == EV["REVIVE"]:
            # Step G52 (decision 0025): Revival Blessing brings a fainted member of the user's side back at half HP,
            # its status cured; ident is its roster index (the line names it without a position)
            m = self._member(pos // 2)[ident]
            if public:
                m.hp_percent, m.hp_flag = hp, hp_flag
            else:
                self._own_display(m, hp, e[7])
            m.status = 0
            m.sleep_cant = 0  # decision 0066: the revival cures the sleep and its count
            user = self._rb_pending.pop(pos // 2, None)
            if user is not None:
                self._at(user).flag = 0  # the revive answers the request: the flag goes
        elif kind == EV["STATUS"]:
            m = self._occupant(pos)
            if public:
                m.status = detail
            m.freeze_turns = FREEZE_TURNS if detail == STATUS["frz"] else 0
            m.toxic = 1 if detail == STATUS["tox"] else 0
            m.toxic_stage = 0  # tox's onStart
            m.sleep_cant = 0  # decision 0066: a new sleep counts from 0 (the status line of a sleep is public for both)
        elif kind == EV["CURE_STATUS"]:
            m = self._occupant(pos)
            if public:
                m.status = 0
            m.freeze_turns = 0
            m.toxic = m.toxic_stage = 0
            m.sleep_cant = 0  # decision 0066: the cure ends the sleep and its count
        elif kind in (EV["BOOST"], EV["UNBOOST"]):
            p = self._at(pos)
            sign = 1 if kind == EV["BOOST"] else -1
            last = self._last_move
            if amount > 0 and last is not None and last[1] == self._parting_shot and last[2] == pos:
                self._at(last[0]).flag = SWITCH_MOVE  # Parting Shot switches its user once it changes a stat (Contrary too)
            p.stages[detail] = min(12, max(0, p.stages[detail] + sign * amount))
            if kind == EV["BOOST"] and amount > 0:
                p.raised = 1  # statsRaisedThisTurn: a stage really rose
            if kind == EV["UNBOOST"] and amount > 0:
                p.lowered = 1  # statsLoweredThisTurn (G88, dfi_boost): a stage really fell
        elif kind == EV["SWAP"]:
            # Ally Switch (step G80, decision 0044; sim/battle.ts swapPosition): the user and its partner change
            # positions with everything that rides on the Pokemon (_swap_positions: an explicit field list, not an object swap)
            self._swap_positions(pos, e[2])
            if pos // 2 == self.side and self._party is not None:
                # side.pokemon: the two actives exchange their entries (sim/battle.ts:1598-1599)
                self._party[pos % 2], self._party[e[2] % 2] = self._party[e[2] % 2], self._party[pos % 2]
        elif kind == EV["COPY_BOOST"]:
            # Psych Up (step G80): the user takes the target's seven stages (-copyboost; the copied crit volatiles
            # are silent decision 0018 features)
            self._at(pos).stages = list(self._at(e[2]).stages)
        elif kind == EV["CLEAR_ALL_BOOSTS"]:
            # Haze (step G62, decision 0031; data/moves.ts haze onHitField: clearBoosts on getAllActive): every standing
            # active Pokemon's stages return to neutral
            for p in (p for side in self._positions for p in side):
                if p.occupant != ROSTER_NONE and not p.fainted:
                    p.stages = [STAGE_NEUTRAL] * 7
        elif kind == EV["CONFUSION_START"]:
            self._at(pos).confused = 1
        elif kind == EV["CONFUSION_END"]:
            self._at(pos).confused = 0
        elif kind == EV["FLASH_FIRE"]:
            self._at(pos).flash_fire = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_CURSE:
            # The Ghost Curse (step G84b, decision 0063): the holder's CURSED bit, shown to both viewers; the holder's
            # leaving or faint clears it (reset), the source's does not (the residual goes on)
            self._at(pos).cursed = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_PERISH:
            # Perish Song's count (step G26): the residual's -start|X|perishN, N = 3, 2, 1, then perish0 before the
            # holder faints; the cast's own perish3 line is [silent] (no event), so nothing shows until the first count
            self._at(pos).perish = amount
        elif kind == EV["ABILITY"] and e[3] in (trace_to_c.CAUSE["ABILITY"], trace_to_c.CAUSE["MOVE"]):
            # An ability that changed until the occupant leaves or Mega Evolves (the tail's ability_now): Trace's copy
            # (step AC1, -ability|X|NEW|...|[from] ability: Trace: cause ABILITY, the new ability in id2) or a Skill Swap
            # (step G70, decision 0041: cause MOVE, the holder's new ability in id). A swap ends the old abilities:
            # Flash Fire's and Unburden's volatiles go with no line (sim/battle.ts:1325-1326).
            p = self._at(pos)
            new = ident2 if e[3] == trace_to_c.CAUSE["ABILITY"] else ident
            if e[3] == trace_to_c.CAUSE["MOVE"]:
                p.flash_fire = 0
                p.flags &= ~FLAG_UNBURDEN
            p.ability_now = new if new != self._member(pos // 2)[p.occupant].ability else 0
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_ENCORE:
            # Encore (step G9): -start|X|Encore forces the slot of the target's last move line (the move must be on
            # its sheet, or the pin's onStart fails without the line); -end|X|Encore (the duration, a used-up move,
            # Mental Herb) and the occupant's leaving end it. A last move the lines do not tie to a slot stops.
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                p.encore_slot = p.encore_turns = 0
            elif p.last_slot in (1, 2, 3, 4):
                p.encore_slot = p.last_slot
                p.encore_turns = ENCORE_TURNS + (1 if p.turn_done else 0)  # one more when it has no move left this turn
            else:
                raise lines.Stop("encore-slot-unknown")
        elif kind == EV["PROTECT"]:
            p = self._at(pos)
            p.protecting = 1
            p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
            p.stall = STALL_DURATION
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._ally_move and self._ally_move is not None:
            self._as_pending = None
            self._ally_pass(self._at(pos))  # the roll passed; the onHit found no partner (NOT_FAIL, null)
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"] and self._last_move is not None \
                and self._last_move[0] == pos and self._last_move[1] in self._move_pivots:
            self._at(pos).flag = 0  # Baton Pass or Revival Blessing failed: no switch
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"]:
            # Only the move's own failure is a failed Protect or guard. A FAIL with a cause is another effect of the
            # same position: an Intimidate that the holder's Inner Focus stopped (cause ABILITY, duoforge.h
            # DUOFORGE_EVENT_FAIL) leaves the stall chain as it is.
            if self._last_move is not None and self._last_move[0] == pos and self._last_move[1] in self._stall_moves:
                p = self._at(pos)
                p.chain = p.stall = 0
            elif (self._last_move is not None and self._last_move[0] == pos and self._last_move[1] in self._guard_moves
                  and self._at(pos).guard_undo is not None):
                p = self._at(pos)
                p.chain, p.stall = p.guard_undo  # the guard failed (nobody acts after it): no stall added
                p.guard_undo = None
        elif kind == EV["WEATHER"]:
            if not flags & FLAG["UPKEEP"]:
                self._weather = detail
                self._weather_turns = self._field_turns_next if detail else 0
        elif kind == EV["FIELD_START"]:
            if detail == 2:
                self._trick_room = FIELD_TURNS
            elif detail == C["DUOFORGE_FIELD_GRAVITY"]:
                # K4 (#475, decision 0015 5dl): Gravity counts five turns; no extender is modelled for it
                self._gravity = FIELD_TURNS
            else:
                # DUOFORGE_FIELD_* -> the observation's DUOFORGE_TERRAIN_*: Grassy, Psychic (Team C), Electric and Misty
                # (POOL, step G25)
                self._terrain, self._terrain_turns = _TERRAIN[detail], self._field_turns_next
        elif kind == EV["FIELD_END"]:
            if detail == 2:
                self._trick_room = 0
            elif detail == C["DUOFORGE_FIELD_GRAVITY"]:
                self._gravity = 0
            else:
                self._terrain = self._terrain_turns = 0
        elif kind in (EV["SIDE_START"], EV["SIDE_END"]) and amount in _HAZARD:
            # an entry hazard (step G37): every -sidestart line lays one layer, up to the move's maximum; its -sideend
            # (Toxic Spikes that a grounded Poison type absorbed, the one removal the engine models) clears it
            field, top = _HAZARD[amount]
            # The Counter keeps the kinds that are up in the order they were created (the record's hazard_order): a
            # further layer keeps its place, an ended kind leaves, one put up again goes last.
            layers = self._hazards[detail]
            if kind == EV["SIDE_START"]:
                layers[field] = min(layers[field] + 1, top)
            else:
                layers.pop(field, None)
        elif kind == EV["SIDE_START"]:
            index = _SIDE_CONDITION[amount]
            turns = TAILWIND_TURNS
            if amount != 1:
                # a screen (Reflect, Light Screen, Aurora Veil, step G20): 5 turns, 8 when the user holds Light Clay
                # (durationCallback); the user is the last move line's
                user = self._occupant(self._last_move[0])
                turns = SCREEN_TURNS_CLAY if self._holds_id(user, SCREEN_EXTENDER) else SCREEN_TURNS
            self._conditions[detail][index] = turns
        elif kind == EV["SIDE_END"]:
            self._conditions[detail][_SIDE_CONDITION[amount]] = 0
        elif kind == EV["ITEM_END"] and detail == 1:
            # a resist berry's [weaken] line: its [eat] line already took the berry, and an ally's Symbiosis may have
            # given the eater a new item since (issue 553)
            pass
        elif kind == EV["ITEM_END"]:
            m = self._occupant(pos)
            m.revealed |= REVEALED_ITEM_CONSUMED
            self._at(pos).unburden_unseen = False
            if self._mental_herb is not None and ident2 == self._mental_herb + 1:
                self._herb_end = pos  # its -end lines follow (dfi_mental_herb)
            if e[3] == trace_to_c.CAUSE["NONE"] and self._eject_button is not None and ident2 == self._eject_button + 1:
                self._at(pos).flag = SWITCH_EMERGENCY_EXIT  # Eject Button sets its holder's switchFlag, then the -enditem
            if e[3] != trace_to_c.CAUSE["ITEM_TAKEN"]:
                m.item_consumed = 1  # used up (useItem, eatItem); a taken item is not
            if public:
                m.item_used = 1
            if e[3] == trace_to_c.CAUSE["ITEM_TAKEN"]:
                # a move took the item (Knock Off, Thief, Trick, Switcheroo, Bug Bite; steps G16, G29, G64): the member
                # holds nothing, also after a switch or a faint (the tail's item_now)
                m.item_now = ITEM_NOW_NONE
            if self._unburden is not None and self._ability_at(pos) == self._unburden:
                self._at(pos).flags |= FLAG_UNBURDEN  # Unburden doubles Speed once the item is gone (c08 battles)
        elif kind == EV["ITEM_START"]:
            # a move gave the member an item (Trick, Switcheroo, Thief, Covet; step G29): it holds it now, its old item is
            # no longer "gone"; the one it came from ([of], Thief and Covet) holds nothing. A Choice item that comes
            # ends the receiver's lock (the item's onStart).
            self._item_received(pos, ident2, public)
            if e[2] != NOPOS:
                giver = self._occupant(e[2])
                giver.item_now = ITEM_NOW_NONE
                giver.revealed |= REVEALED_ITEM_CONSUMED
                if e[2] // 2 != self.side or self._spectator:
                    giver.item_used = 1
                if self._unburden is not None and self._ability_at(e[2]) == self._unburden and not self._at(e[2]).fainted:
                    self._at(e[2]).flags |= FLAG_UNBURDEN  # takeItem's TakeItem event (Covet prints no -enditem)
        elif kind == EV["SINGLE_TURN"]:
            if ident == self._follow_me:
                self._at(pos).flags |= FLAG_FOLLOW_ME  # this turn (c11 battles)
            elif ident == self._helping_hand:
                self._at(pos).flags |= FLAG_HELPING_HAND  # on the boosted ally, this turn (c09 battles)
            elif ident == self._wide_guard:
                # Wide Guard (step G7): the side's guard for this turn (the residual ends it, a Feint breaks it), which
                # only a PIVOT inside the turn shows
                self._guards.add(("WIDE_GUARD", pos // 2))
            elif ident == self._rage_powder:
                # Rage Powder (step G30): the extension's RAGE_POWDER bit for this turn, which only a PIVOT inside the
                # turn shows (the residual ends it); the base view's Follow Me flag stays off for it
                self._at(pos).rage_powder = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_SPEED_SWAP:
            # Speed Swap (step K3): both positions carry the presence bit; the swapped values are not public
            self._at(pos).speed_swapped = 1
            self._at(e[2]).speed_swapped = 1
        elif kind == EV["FORME"]:
            # the view keeps the set's species; MEGA sets is_mega and the ability. A forme change rebuilds the stored stats
            # (setSpecies), so a live Speed Swap of the position ends (step K3)
            self._at(pos).speed_swapped = 0
        elif kind == EV["MEGA"]:
            self._mega_used[pos // 2] = 1
            self._at(pos).speed_swapped = 0  # formeChange -> setSpecies rebuilds the stored stats (step K3)
            self._at(pos).ability_now = 0  # the Mega forme's ability replaces a copied one (formeChange -> setAbility)
            self._at(pos).type_now = (0, 0)  # and setType(species.types) ends a type that Soak set
            self._occupant(pos).revealed |= REVEALED_MEGA
            self._at(pos).unburden_unseen = False  # the Mega forme's ability ends Unburden's volatile
            # the Mega forme and its ability, at once for both sides: an own member's request shows them only at the next
            # decision point, and the Pressure of the lines between reads the ability (_pressure_extra)
            m = self._occupant(pos)
            m.is_mega = 1
            m.ability = self.data.ability_of(self.data.mega_of(m.sheet["species"], m.sheet["item"]))
        elif kind == EV["PREPARE"]:
            p = self._at(pos)
            m = self._occupant(pos)
            p.charge = CHARGE_TURNS
            p.locked_slot = m.sheet["moves"].index(ident)
            if not foe:
                p.locked_target = self._own_target(pos % 2)
        elif kind == EV["ANIMATION"]:
            p = self._at(pos)
            if p.charge == CHARGE_TURNS and self._last_move is not None and self._last_move[0] == pos:
                # The charge turn's move fired at once (Electro Shot in rain): nothing stays charged.
                p.charge, p.locked_slot, p.locked_target = 0, MOVE_SLOT_NONE, TARGET_NONE
        elif kind == EV["UPKEEP"]:
            self._upkeep()
            self._after_upkeep = True
            self._turn_scoped.clear()
            self._guards.clear()
        elif kind == EV["RESULT"]:
            self.ended = True
