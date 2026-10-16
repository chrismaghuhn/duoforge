"""Switch rights, own displays, Ally Switch, Baton Pass, the residual, damage and Pressure.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import lines
from ..data import trace_to_c
from .constants import (ALLY_SWITCH_LEVEL_MAX, ALLY_SWITCH_TURNS, FLAG, FLAG_FOLLOW_ME, FLAG_HELPING_HAND,
                        MOVE_SLOT_NONE, _MUST_PRESSURE, NOPOS, ROSTER_NONE, SWITCH_FAINTED, TARGET_NONE)
from .state import _SWAP_MOVES


class _ActionFolds:
    def _can_switch(self, side):
        """A member of `side` can come in (src/combat/turn.c dfi_can_switch): one brought, not fainted and not active, as
        far as the lines showed (a member seen at 0 percent is gone; one never seen stands)."""
        members = self._member(side)
        brought = len(self._picks) if side == self.side and self._picks is not None else self._teamsize[side]
        if brought is None:
            raise ValueError(f"no brought count for side {side}")
        gone = sum(1 for m in members if m.seen and m.hp_percent == 0)
        standing = sum(1 for p in self._positions[side] if p.occupant != ROSTER_NONE and not p.fainted)
        return brought - gone - standing > 0

    @staticmethod
    def _move_action(p):
        """One move action of the occupant of `p` (the record's move_actions: every MOVE action the queue runs for a
        standing occupant, src/combat/turn.c dfi_run_move_body): its first line, a [move], a [cant] or the confusion's
        -activate; the line after that confusion line belongs to the same action."""
        if p.confused_action:
            p.confused_action = False
            return
        p.move_actions = min(p.move_actions + 1, 255)

    @staticmethod
    def _own_display(member, hp, hp_max):
        """An own member's HP as its opponent is shown it (the public record's knowledge): the display of the exact HP of
        an own line (hp of hp_max), from the library."""
        from duoforge import view
        member.hp_percent, member.hp_flag = view.hp_display(hp, hp_max)

    def _own_target(self, slot):
        """The target position the own accepted choice gave the move of `slot`."""
        if self._accepted is None:
            raise ValueError("an own two-turn move without an accepted choice")
        words = self._accepted.split(", ")[slot].split(" ")
        if words[0] != "move" or len(words) < 3:
            raise ValueError(f"an own two-turn move without a target: {self._accepted!r}")
        return trace_to_c.abs_target(self.side, int(words[2]))

    def _swap_positions(self, user, partner):
        """Ally Switch's exchange of the flat positions `user` and `partner` (dfi_swap_position_state, decision 0044 section 10):
        the fields of _SWAP_MOVES go with the Pokemon, those of _SWAP_SLOT stay, and what names a swapped position follows it:
        the trap source of every position (a trapper's flat position + 1) and the Attract source position of every infatuated
        one (the engine derives it from the member code, which does not change). A pending Healing Wish on either slot is the
        engine's E_UNSUPPORTED (its onSwap heal is not modelled): an explicit stop, before anything changes."""
        a, c = self._at(user), self._at(partner)
        if a.wish or c.wish:
            raise lines.Stop("ally-switch-healing-wish")
        self._as_pending = None
        self._ally_pass(a)  # a passed consecutive roll (or the first use): the counter goes up (before the swap, as the engine)
        for name in _SWAP_MOVES:
            va, vc = getattr(a, name), getattr(c, name)
            setattr(a, name, vc)
            setattr(c, name, va)
        for p in (p for side in self._positions for p in side):
            if p.trap_source == user + 1:
                p.trap_source = partner + 1
            elif p.trap_source == partner + 1:
                p.trap_source = user + 1
            if p.attract:
                if p.attract_from == user:
                    p.attract_from = partner
                elif p.attract_from == partner:
                    p.attract_from = user

    def _ally_pass(self, p):
        """Ally Switch's counter after a passed roll: the first use starts at level 1 (no roll), a later one goes up to 6;
        either way the duration is 2 turns (dfi_ally_switch_prepare)."""
        p.ally_level = 1 if p.ally_level == 0 else min(ALLY_SWITCH_LEVEL_MAX, p.ally_level + 1)
        p.ally_turns = ALLY_SWITCH_TURNS

    def _upkeep(self):
        def down(n):
            return n - 1 if n > 0 else 0
        for side in (0, 1):
            for p in self._positions[side]:
                if p.ally_level:
                    if p.ally_turns <= 1:
                        p.ally_level = p.ally_turns = 0  # the residual's end: turns 1 -> 0 (the volatile is deleted)
                    else:
                        p.ally_turns -= 1
        self._weather_turns = down(self._weather_turns)
        self._terrain_turns = down(self._terrain_turns)
        self._trick_room = down(self._trick_room)
        self._gravity = down(self._gravity)  # K4: the residual order 27.2, after Trick Room
        self._conditions = [[down(n) for n in c] for c in self._conditions]
        for side in self._positions:
            for p in side:
                p.flag = SWITCH_FAINTED if p.fainted else 0  # checkFainted at the end of the turn; no other flag carries over
                p.protecting = 0
                p.flags &= ~(FLAG_FOLLOW_ME | FLAG_HELPING_HAND)  # single-turn
                p.rage_powder = 0
                if p.stall:
                    p.stall -= 1
                    if not p.stall:
                        p.chain = 0
                if p.charge:
                    p.charge -= 1
                    if not p.charge:
                        p.locked_slot, p.locked_target = MOVE_SLOT_NONE, TARGET_NONE
                p.throat_chop = down(p.throat_chop)  # its residual end is silent
                p.encore_turns = down(p.encore_turns)
                # the residual counts (orders 15, 17, 20, 23); each end at 0 shows its line, which the fold read already
                p.taunt, p.heal_block, p.yawn = down(p.taunt), down(p.heal_block), down(p.yawn)
                p.disable_turns = down(p.disable_turns)

    def _hurt(self, pos, cause):
        """hurtThisTurn (G88, dfi_deal_ex): a spread damage that leaves its target standing. Every damage line is spread
        damage except the directDamage of a user's own cost: Struggle's recoil ([from] Recoil after a Struggle line of
        the same position) and the plain -damage of DIRECT_COST_MOVES on their user. A plain -damage on the
        user of another move is no line the engine makes: it stops the tracker rather than guess."""
        last = self._last_move
        own = last is not None and last[0] == pos
        if own and cause == trace_to_c.CAUSE["RECOIL"] and last[1] == self._struggle:
            return
        if own and cause == trace_to_c.CAUSE["NONE"]:
            if last[1] in self._direct_costs:
                return
            raise lines.Stop("line:-damage of the move's own user")
        self._at(pos).hurt = 1

    def _pressure_extra(self, pos, move, target, flags):
        """The extra PP a move use costs for the user's standing foes with Pressure (decision 0030, step G53), counted
        only where the line shows the targets: the named target of a single-target move, every standing foe for the
        spread classes, for "all" and for a MUSTPRESSURE move; none for a foeSide move or a blanked ([still])
        target, which nobody can know. A [spread] line of a single-target move (Expanding Force on Psychic Terrain:
        onModifyMove runs before getMoveTargets, sim/battle-actions.ts useMoveInner) counts every standing foe as
        well: its pressureTargets are all adjacent foes, a foe its Protect leaves out of the [spread] list included."""
        if self._pressure is None or flags & FLAG["STILL"]:
            return 0
        foe = 1 - pos // 2
        members = self._member(foe)
        holders = [k for k, p in enumerate(self._positions[foe]) if p.occupant != ROSTER_NONE and not p.fainted
                   and p.occupant < len(members) and (p.ability_now or members[p.occupant].ability) == self._pressure]
        if not holders:
            return 0
        kind = self.data.target_type(move)
        if self.data.move_flags(move) & _MUST_PRESSURE or kind in ("all", "allAdjacentFoes", "allAdjacent"):
            return len(holders)
        if flags & FLAG["SPREAD"]:
            # a single-target class turned spread (onModifyMove: allAdjacentFoes) hits every adjacent foe; an "allies"
            # move's [spread] list is the user's side (alliesAndSelf), no foe
            return len(holders) if kind in ("normal", "any", "adjacentFoe") else 0
        if kind == "foeSide" or target == NOPOS or target // 2 != foe:
            return 0
        return int(target % 2 in holders)
