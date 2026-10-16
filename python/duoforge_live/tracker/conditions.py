"""Boosts, Attract, Throat Chop, the partial trap and the extended field turns that lines set.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import lines
from ..data import trace_to_c
from .constants import (EV, FIELD_TURNS, FIELD_TURNS_EXTENDED, ROSTER_NONE, STAGE_NEUTRAL, TERRAIN_EXTENDER,
                        THROAT_CHOP_TURNS, TRAP_ELAPSED_MAX, _WEATHER_ROCK)


class _ConditionFolds:
    def _set_boost(self, parts):
        """Belly Drum's (step G86) and Anger Point's (step G77) -setboost: the line shows the Attack stage it leaves; the
        engine's event is the BOOST of the change (dfi_boost: Belly Drum with cause MOVE and the move's id, Anger Point
        with cause ABILITY and the ability's id + 1), which the tracker folds as any boost. The converter computes the
        change from the trace state (trace_to_c); the tracker has the stage itself. A change that is not positive is the
        converter's refusal setboost-change (at +6 before, Anger Point's pin prints no line at all)."""
        flat = trace_to_c.ev_pos(parts[2])
        stat = trace_to_c.EV_STATS.index(parts[3])
        change = STAGE_NEUTRAL + int(parts[4]) - self._at(flat).stages[stat]
        if change <= 0:
            raise lines.Stop("converter:setboost-change")
        if parts[5:] == ["[from] ability: Anger Point"]:
            cause, id2 = trace_to_c.CAUSE["ABILITY"], self.data.tables["ABILITY"]["ANGERPOINT"] + 1
        else:
            cause, id2 = trace_to_c.CAUSE["MOVE"], self.data.tables["MOVE"]["BELLYDRUM"]
        self._event(trace_to_c.ev_tuple(EV["BOOST"], flat, trace_to_c.NOPOS, cause, 0, id2, detail=stat, amount=change))

    def _silent_attract_end(self, parts):
        """-end|X|Attract|[silent] (data/moves.ts attract onEnd): the infatuation of X ends with no visible line, when its source
        has left the field (onUpdate's removeVolatile, the engine's silent clearing of its byte). The converter skips [silent]
        lines, so the tracker clears the position here, as the Yawn's end does; any other form stops."""
        pos = lines.flat_position(parts[2])
        if pos is None or parts[4:] != ["[silent]"]:
            raise lines.Stop("line:-end Attract")
        self._at(pos).attract = 0

    def _throat_chop(self, parts):
        """Throat Chop's volatile (decision 0018 THROAT_CHOP, step G8; public by the owner's change): the move's
        `-start|X|Throat Chop|[silent]` (data/moves.ts throatchop, onStart) sets the presence bit, its residual
        `-end|X|Throat Chop|[silent]` (onEnd) clears it, and so does the occupant's leaving (the position's reset). The
        converter skips [silent] lines, so the line is folded here; its count is never shown. Any other form stops."""
        pos = lines.flat_position(parts[2])
        if pos is None or parts[4:] != ["[silent]"]:
            raise lines.Stop(f"line:{parts[1]} Throat Chop")
        self._at(pos).throat_chop = THROAT_CHOP_TURNS if parts[1] == "-start" else 0

    def _trap_move_id(self, name):
        """The move id of a partial-trap line's move name, None when the tables have none."""
        return self.data.tables["MOVE"].get(trace_to_c.key(name))

    @staticmethod
    def _trap_clear(p):
        p.trap = p.trap_source = p.trap_move = p.trap_band = p.trap_elapsed = 0

    def _trap_start(self, pos, source, move):
        """The partial trap's start (step G90, decision 0060; `-activate|T|move: M|[of] S`, an ACTIVATE of cause MOVE): the
        engine sets the volatile on a standing target that has none, with the source, the move, the source's Binding Band
        at that moment and a zero elapsed count. A target that has one is refused by the engine with no line, so the
        line cannot come then; the drawn turns are never shown."""
        p = self._at(pos)
        if p.trap:
            raise lines.Stop("trap-start-on-trapped")
        if (p.occupant == ROSTER_NONE or not 0 <= source < len(self._positions) * 2 or source == pos
                or self._at(source).occupant == ROSTER_NONE):
            raise lines.Stop("trap-start-source")
        p.trap, p.trap_source, p.trap_move = 1, source + 1, move + 1
        p.trap_band = 1 if self._holds(self._occupant(source), "BINDINGBAND") else 0
        p.trap_elapsed = 0

    def _trap_end(self, pos, move):
        """The duration's end (`-end|T|move: M|[partiallytrapped]`, VOLATILE_END): the engine clears the trap and its count."""
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-end-untrapped")
        if p.trap_move != move + 1:
            raise lines.Stop("trap-end-move")
        self._trap_clear(p)

    def _trap_silent_end(self, parts):
        """A partial trap's silent end, `-end|T|M|[partiallytrapped]|[silent]` (the pin prints the move bare; the converter's
        other spelling, "move: M", is taken too): the engine cleared the trap with no event. Any other form stops."""
        pos = lines.flat_position(parts[2]) if len(parts) > 2 else None
        if len(parts) != 6 or parts[1] != "-end" or parts[4] != "[partiallytrapped]" or parts[5] != "[silent]" or pos is None:
            raise lines.Stop("trap-end-line")
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-end-untrapped")
        name = parts[3][len("move: "):] if parts[3].startswith("move: ") else parts[3]
        if self._trap_move_id(name) != p.trap_move - 1:
            raise lines.Stop("trap-end-move")
        self._trap_clear(p)

    def _trap_residual(self, parts):
        """One residual phase of a partial trap that stays up: `-damage|T|hp|[from] move: M|[partiallytrapped]`. The engine
        counts the phase (TRAP_ELAPSED, +1) before the damage; the phase that ends the trap shows an end line, not this one,
        and the count stays below the duration of at most 6. Any other form stops."""
        pos = lines.flat_position(parts[2]) if len(parts) > 2 else None
        if (len(parts) != 6 or parts[1] != "-damage" or not parts[3] or parts[3].startswith("[") or pos is None
                or parts[5] != "[partiallytrapped]" or not parts[4].startswith("[from] move: ")):
            raise lines.Stop("trap-residual-line")
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-residual-untrapped")
        if self._trap_move_id(parts[4][len("[from] move: "):]) != p.trap_move - 1:
            raise lines.Stop("trap-residual-move")
        if p.trap_elapsed >= TRAP_ELAPSED_MAX:
            raise lines.Stop("trap-residual-count")
        p.trap_elapsed += 1

    def _trap_source_left(self, pos):
        """The occupant of `pos` leaves (a switch, a drag or a faint): every trap it was the source of keeps its turns, move,
        band and count but has no source any more (dfi_tail_clear_occupant), and the residual ends it silently."""
        for side in self._positions:
            for q in side:
                if q.trap and q.trap_source == pos + 1:
                    q.trap_source = 0

    def _extended_field(self, line):
        """A weather or terrain set by a member that holds the item lengthening it (Damp Rock, Heat Rock, Smooth
        Rock, Icy Rock, Terrain Extender; data/conditions.ts durationCallback: source.hasItem) lasts 8 turns, and no
        line shows it: the setter is the [of] member (an ability) or the last move's user, its item the open
        sheet's unless it was seen used or lost. The next WEATHER or FIELD_START event of this line takes the 8."""
        self._field_turns_next = FIELD_TURNS
        parts = line.split("|")
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "-weather" and len(parts) > 2 and parts[2] in _WEATHER_ROCK and "[upkeep]" not in parts:
            item = _WEATHER_ROCK[parts[2]]
        elif kind == "-fieldstart" and len(parts) > 2 and parts[2].endswith(" Terrain"):
            item = TERRAIN_EXTENDER
        else:
            return
        of = [p[len("[of] "):] for p in parts if p.startswith("[of] ")]
        holder = None
        if of:
            holder = self._member_of(of[0])
        elif self._last_move is not None:
            holder = self._occupant(self._last_move[0])
        if holder is not None and self._holds_id(holder, item):
            self._field_turns_next = FIELD_TURNS_EXTENDED
