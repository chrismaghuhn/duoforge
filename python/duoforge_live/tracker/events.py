"""Lines into events, and the move action an event belongs to.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import lines
from ..data import trace_to_c
from .constants import EV, FLAG, _kind, NOPOS, ROSTER_NONE, SPECTATOR


class _EventFolds:
    # ------------------------------------------------------------------ fold
    def _register(self, line):
        """Learns the roster index of a Pokemon named in a switch line, from the species of its details."""
        parts = line.split("|")
        if parts[1] not in ("switch", "drag"):
            return
        side = int(parts[2][1]) - 1
        name = parts[2].split(": ", 1)[1]
        if name in self._names[side]:
            return
        base = self.data.base_forme(self.data.forme(parts[3].split(",")[0]))
        index = [m for m, member in enumerate(self._member(side)) if member.sheet["species"] == base]
        if len(index) != 1:
            if parts[1] == "drag":
                # Step G46: a drag into a member that is not one member of the side's sheet cannot be represented.
                raise lines.Stop(f"drag:{parts[2]} names no member of the side's sheet")
            raise ValueError(f"{parts[2]} ({parts[3]}) is not one member of its side's sheet")
        self._names[side][name] = index[0]

    def _fold(self, line, fold=True):
        """The line's events into the tracker's fields; fold=False only collects them for the move action's result."""
        if _kind(line) in trace_to_c.NOT_EVENTS:
            return  # setup and layout lines: no event (step_events skips them too)
        if _kind(line) in ("win", "tie") and self._foe_members is None:
            self.ended = True  # over before the sheets (a forfeit during the wait): nothing to fold
            return
        if self._foe_members is None:
            raise ValueError(f"a battle line before both open team sheets: {line!r}")
        self._register(line)
        maxhp = [{n: 100 for n in self._names[s]} for s in (0, 1)]
        own = self._member(self.side)
        if not self._spectator:
            for name, index in self._names[self.side].items():
                maxhp[self.side][name] = own[index].hp_max
        viewer = SPECTATOR if self._spectator else self.side
        parts = line.split("|")
        if _kind(line) == "move" and parts[3:4] == ["Revival Blessing"]:
            user = lines.flat_position(parts[2])
            if user is not None:
                self._rb_pending[user // 2] = user  # its revive comes in the step that answers the request
        swap_ids = None
        if parts[1] == "-activate" and parts[3:6] == ["Skill Swap", "", ""] and len(parts) == 7:
            # an ally Skill Swap names no ability (decision 0041): the two holders' current abilities, known from the
            # open sheets and the lines folded so far, change places
            src, tgt = lines.flat_position(parts[2]), lines.flat_position(parts[6][len("[of] "):])
            if src is not None and tgt is not None and self._at(src).occupant != ROSTER_NONE \
                    and self._at(tgt).occupant != ROSTER_NONE and self._ability_at(src) and self._ability_at(tgt):
                swap_ids = {0: (self._ability_at(tgt) - 1, self._ability_at(src) - 1)}
        try:
            events = trace_to_c.step_events([line], viewer, self._names, maxhp, self.data.tables, self._rb_pending,
                                            swap_ids=swap_ids, lead=self._lines[-4:-1])  # the Leech Seed heal reads back
        except trace_to_c.ConversionError as e:  # a SystemExit: callers catch one kind of error
            detail = getattr(e, "detail", None)
            raise lines.Stop(f"converter:{e.rule}" + (f" {detail}" if detail else "")) from e
        except (KeyError, IndexError) as e:  # a form of a known line the parser does not know (untyped, as diff_driver)
            raise lines.Stop(f"converter:untyped {_kind(line)} {type(e).__name__} {e}") from e
        for e in events:
            if fold:
                self._event(e)
            else:
                self._segment(e)

    def _at(self, pos):
        return self._positions[pos // 2][pos % 2]

    def current_types(self, member, position=None):
        """The types of a member now, as the lines the tracker folds show them: a type a move set while it stands at
        `position` (the position's type_now, #342: Soak's single type, or Double Shock's remaining type; a Mega Evolution
        ends it), else those of its set's forme, or of its Mega forme once it Mega Evolved (the stone of its sheet names
        it). A forme change stops on its own line (FORME_CHANGE is no fold of this tracker; the day it is folded this
        has to know it, so it refuses while it is supported). Without the position a folded type change cannot be
        seen, so it refuses then too. Trick-or-Treat and Forest's Curse stop on their lines (the converter). Lines the
        tracker does not read cannot change them (Roost only hides Flying for a turn, which never decides a Ghost).
        ValueError for a Mega member whose sheet has no stone of its forme."""
        if lines.SUPPORTED >> lines.FEATURES["FORME_CHANGE"] & 1:
            raise lines.Stop("types:FORME_CHANGE")
        if position is not None and position.type_now != (0, 0):
            soak, other = position.type_now  # (id + 1, 0): Soak's type; (0, id + 1): Double Shock's ??? and that type
            return (soak - 1,) if soak else (other - 1,)
        if position is None and lines.SUPPORTED >> lines.FEATURES["TYPE_CHANGE"] & 1:
            raise lines.Stop("types:TYPE_CHANGE")
        forme = member.sheet["species"]
        if member.is_mega:
            forme = self.data.mega_of(forme, member.sheet["item"])
            if forme is None:
                raise ValueError("a Mega member whose sheet has no Mega Stone of its forme")
        return self.data.forme_types(forme)

    def _occupant(self, pos):
        p = self._at(pos)
        return None if p.occupant == ROSTER_NONE else self._member(pos // 2)[p.occupant]

    def _event(self, e):
        self._segment(e)
        herb, self._herb_end = self._herb_end, None
        if herb is not None and e[0] == EV["VOLATILE_END"] and e[1] == herb:
            self._herb_end = herb  # the herb's row of -end lines goes on
        self._fold_event(e, herb)

    def _residual_end(self, e, herb, count, name):
        """A natural end of a counted volatile (no [from], not Mental Herb's row) comes in the residual where its count
        runs out: the tracker's count must be 1 there. Any other count is a counting error (the start's duration rule,
        a wrong move_queued), which stops the tracker instead of writing a wrong count into the record."""
        if e[3] == trace_to_c.CAUSE["NONE"] and e[1] != herb and count != 1:
            raise lines.Stop(f"count:{name} ends at {count}")

    def _segment(self, e):
        """The events of each move action, for its result (the POOL record's move_result): an action begins with its
        user's own [move] line, a [cant] (not an ability's block, which follows the user's [move]) or a confusion line
        (the [move] or [cant] after it belongs to it), and ends where the next one begins, at the residual (|upkeep|),
        at the next turn or at a decision point (_end_action)."""
        kind, pos, cause = e[0], e[1], e[3]
        if kind in (EV["UPKEEP"], EV["TURN"]):
            self._end_action()
            if kind == EV["TURN"]:
                for side in self._positions:
                    for p in side:
                        # endTurn: moveLastTurnResult = moveThisTurnResult, this turn's undefined (src/combat/turn.c)
                        p.result_last, p.result_now = p.result_now, 0
            return
        action = self._action
        # A Magic Bounce holder's [cant] Throat Chop right after the move line that targets it is the bounced run, inside the
        # action (issue 570), not an action of its own
        bounce_cant = action is not None and action["events"] and self._bounce_cant(action["events"][-1], e, action["pos"])
        starts = not bounce_cant and (
            (kind == EV["MOVE"] and cause == trace_to_c.CAUSE["NONE"]) or kind == EV["CONFUSED"] or
            (kind == EV["CANT"] and cause != trace_to_c.CAUSE["ABILITY"]))
        if starts and action is not None and action["pos"] == pos and action["confused"] and kind != EV["CONFUSED"]:
            action["confused"] = False  # the move the confusion line let through, or its [cant]
            action["events"].append(e)
        elif starts:
            # the lines of this action that come before its first one end the previous action's list: a wake-up or thaw
            # ([-curestatus] [msg]), the end of a confusion, Struggle's -activate
            lead = []
            while action is not None and action["events"] and self._pre_action(action["events"], pos):
                lead.insert(0, action["events"].pop())
            self._end_action()
            p = self._at(pos)
            self._action = {"pos": pos, "events": lead + [e], "confused": kind == EV["CONFUSED"],
                            "activation": p.activation}
        elif action is not None:
            action["events"].append(e)

    def _bounce_cant(self, prev, e, user):
        """`e` is the [cant] Throat Chop of the target of `user`'s move line `prev`, a foe: Magic Bounce took the move and
        Throat Chop stopped the bounced run before its line (issue 570, src/combat/turn.c dfi_bounce)."""
        return e[0] == EV["CANT"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._throat_chop_id and \
            prev[0] == EV["MOVE"] and prev[3] == trace_to_c.CAUSE["NONE"] and prev[1] == user and prev[2] == e[1] and \
            e[1] != NOPOS and e[1] // 2 != user // 2

    def _pre_action(self, events, pos):
        """The last of `events` is a line of `pos` that comes before its action's first line: a wake-up or a thaw
        ([-curestatus] [msg], not a berry's cure after its -enditem), the end of its confusion, Struggle's -activate."""
        e = events[-1]
        if e[1] != pos:
            return False
        if len(events) > 1 and events[-2][0] == EV["ITEM_END"] and events[-2][1] == pos:
            return False
        return (e[0] == EV["CURE_STATUS"] and e[13] & FLAG["MESSAGE"] and e[3] == trace_to_c.CAUSE["NONE"]) or \
            e[0] == EV["CONFUSION_END"] or \
            (e[0] == EV["ACTIVATE"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._struggle) or \
            (e[0] == EV["ACTIVATE"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._attract)

    def _end_action(self):
        """The result of the move action that ends here, into its user's position (this turn's): the library's
        classification of its events (record.move_result_of), None where they do not determine it."""
        action, self._action = self._action, None
        if action is None or self.data.kind != "pool":
            return
        from .. import record
        events = action["events"]
        # The user may have moved during its own action (Ally Switch): the activation id belongs to the Pokemon, so the slot that
        # now holds it gets the result (src/combat/turn.c dfi_run_move). Another occupant at every slot, or the user fainted:
        # the faint's clearing comes after the result
        side = action["pos"] // 2
        for p in self._positions[side]:
            if p.occupant != ROSTER_NONE and p.activation == action["activation"] and not p.fainted:
                p.result_now = record.move_result_of(self.data, action["pos"], events)
                break
        for i, e in enumerate(events):
            if (e[0] == EV["MOVE"] and e[3] == trace_to_c.CAUSE["ABILITY"] or
                    i > 0 and self._bounce_cant(events[i - 1], e, action["pos"])) and e[1] != NOPOS:
                # Magic Bounce: the holder's result is that of the reflected run (src/combat/turn.c, the bounced move)
                holder = self._at(e[1])
                if holder.occupant != ROSTER_NONE and not holder.fainted:
                    holder.result_now = record.move_result_of(self.data, e[1], events[i:])
