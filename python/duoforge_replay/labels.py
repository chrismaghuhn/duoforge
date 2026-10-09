"""Labels of an own decision point: the options that agree with the log (M11 spec section 9).

A label is a set, never a guess: per slot list a 32-bit mask over its
options (bit i = option i), at team selection a 360-bit mask over
TEAM_TABLE (45 bytes, bit i in byte i // 8 at i % 8). A reason per slot
says why the set has its size:

- EXACT: one option;
- TARGET_UNKNOWN: the move (slot and Mega choice) with every target, when
  redirection or retargeting was possible, or a cant line names the move;
- MOVE_HIDDEN: every move option with the shown Mega choice, when the move
  never showed (it fainted or left first, or a cant line names no move);
- FORCED, UNKNOWN: every option, no information;
- NOT_REQUESTED: a slot that was not asked.

Labels read only the lines before the perspective's stop line: a slot whose
action comes later gets UNKNOWN. The BC loss is -log P(label set).
"""
from dataclasses import dataclass

from duoforge_live import options
from duoforge_live.lines import flat_position, line_kind
from duoforge_live.data import trace_to_c
from duoforge_live.game import TEAM_TABLE

from .points import TEAM_SELECTION, TURN

NOT_REQUESTED, EXACT, TARGET_UNKNOWN, MOVE_HIDDEN, FORCED, UNKNOWN = range(6)
TEAM_BYTES = (len(TEAM_TABLE) + 7) // 8
# The other side's single-turn lines that draw single-target moves (Follow Me, Rage Powder, Spotlight).
REDIRECT_TURN = {"move: Follow Me", "move: Rage Powder", "Rage Powder", "move: Spotlight", "Spotlight"}
# Abilities whose -activate right before a move line draws it (sim: onAnyRedirectTarget).
_REDIRECT_ABILITY = {"ability: Lightning Rod", "ability: Storm Drain"}


@dataclass(frozen=True)
class Label:
    slots: tuple  # (u32 mask, u32 mask)
    team: bytes  # TEAM_BYTES bytes
    reasons: tuple  # (reason, reason)


def _mask(indices):
    out = 0
    for i in indices:
        out |= 1 << i
    return out


def _all(options_list):
    return (1 << len(options_list)) - 1




def team_label(leads, seen_back, member_count=6):
    """Every team tuple with these leads (slot order) whose back pair contains the back members seen."""
    bits = bytearray(TEAM_BYTES)
    for i, picks in enumerate(TEAM_TABLE):
        if picks[:2] == tuple(leads) and set(seen_back) <= set(picks[2:]) and max(picks) < member_count:
            bits[i // 8] |= 1 << (i % 8)
    return Label((0, 0), bytes(bits), (NOT_REQUESTED, NOT_REQUESTED))


def turn_label(log, point, side, lists, moves, member_of, tables, stop_line, vacant=frozenset()):
    """The label of a TURN point: per own slot, from the lines log[point.line:min(point.end, stop_line)].
    moves[k] are the move ids of the occupant of slot k at the point (None for none); member_of(details) is the own
    roster index of a switch line's details; vacant holds the flat positions empty or fainted at the point."""
    end = min(point.end, stop_line)
    segment = log[point.line:end]
    # A slot whose action never showed chose a move only if the switch phase of the turn is over (Showdown runs
    # switches first): some move, cant, Mega Evolution or confusion line came. A game that ends while the players
    # choose (a forfeit, the timer) shows none, and then a switch is as possible as a move.
    acted = any(line_kind(line) in ("move", "cant", "-mega") or
                (line_kind(line) == "-activate" and line.split("|")[3:4] == ["confusion"]) for line in segment)
    slots, reasons = [], []
    for k in (0, 1):
        mask, reason = _slot_label(segment, side, k, lists[k], moves[k], member_of, tables, vacant)
        if reason is None:
            reason, mask = UNKNOWN if end < point.end or not acted else MOVE_HIDDEN, None
            if reason == MOVE_HIDDEN:
                mask = _move_options(lists[k], _mega_shown(segment, side * 2 + k))
                if not mask:
                    reason, mask = UNKNOWN, _all(lists[k])
            else:
                mask = _all(lists[k])
        slots.append(mask)
        reasons.append(reason)
    return Label(tuple(slots), bytes(TEAM_BYTES), tuple(reasons))


def _mega_shown(segment, position):
    return 1 if any(line_kind(line) == "-mega" and flat_position(line.split("|")[2]) == position for line in segment) else 0


def _move_options(options_list, mega, move_slot=None):
    return _mask(i for i, o in enumerate(options_list)
                 if o.kind == options.MOVE and o.mega == mega and (move_slot is None or o.move_slot == move_slot))


def _slot_label(segment, side, k, options_list, moves, member_of, tables, vacant):
    """(mask, reason) of slot k, or (None, None) when its action never showed in the segment."""
    kinds = {o.kind for o in options_list}
    if kinds == {options.NONE}:
        return _all(options_list), NOT_REQUESTED
    if kinds == {options.PASS} or len(options_list) == 1:
        return _all(options_list), FORCED
    position = side * 2 + k
    mega = _mega_shown(segment, position)
    acted = False  # a move-phase line of anyone came before
    encored = False  # an Encore started on this position since the choice
    for index, line in enumerate(segment):
        kind = line_kind(line)
        parts = line.split("|")
        if kind == "switch" and flat_position(parts[2]) == position:
            if acted:
                return None, None  # it left (a pivot) before acting
            member = member_of(parts[3])
            found = [i for i, o in enumerate(options_list) if o.kind == options.SWITCH and o.reserve == member]
            return (_mask(found), EXACT) if len(found) == 1 else (_all(options_list), UNKNOWN)
        if kind in ("move", "cant", "-mega"):
            acted = True
        if kind == "faint" and flat_position(parts[2]) == position:
            return None, None
        if kind == "cant" and flat_position(parts[2]) == position:
            if parts[3] == "recharge":
                return _all(options_list), FORCED
            if len(parts) > 4 and parts[4]:
                move = tables["MOVE"].get(trace_to_c.key(parts[4]))
                if move is not None and moves is not None and move in moves:
                    return _move_options(options_list, mega, moves.index(move)), TARGET_UNKNOWN
            return None, None
        if kind == "-start" and len(parts) > 3 and parts[3] == "Encore" and flat_position(parts[2]) == position:
            encored = True
        if kind == "move" and flat_position(parts[2]) == position:
            if encored:
                # Encore started on this position before it moved: a queued move of another slot is replaced by the
                # Encored one (Champions), so the move line is not what was chosen
                return _all(options_list), UNKNOWN
            return _move_label(segment, index, parts, side, options_list, moves, mega, tables, vacant)
    return None, None


def _move_label(segment, index, parts, side, options_list, moves, mega, tables, vacant):
    attrs = [p for p in parts[3:] if p.startswith("[")]
    if "[from]lockedmove" in attrs or "[from] lockedmove" in attrs:
        return _all(options_list), FORCED
    name = parts[3]
    if name == "Struggle":
        found = [i for i, o in enumerate(options_list) if o.kind == options.MOVE and o.move_slot == options.STRUGGLE]
        return (_mask(found), EXACT) if found else (_all(options_list), UNKNOWN)
    move = tables["MOVE"].get(trace_to_c.key(name))
    if move is None or moves is None or move not in moves:
        return _all(options_list), UNKNOWN
    move_slot = moves.index(move)
    candidates = [i for i, o in enumerate(options_list)
                  if o.kind == options.MOVE and o.move_slot == move_slot and o.mega == mega]
    if not candidates:
        return _all(options_list), UNKNOWN
    targets = {options_list[i].target for i in candidates}
    if targets == {options.TARGET_NONE}:
        return _mask(candidates), EXACT
    shown = flat_position(parts[4]) if len(parts) > 4 else None
    uncertain = shown is None or "[notarget]" in attrs or any(a.startswith("[spread]") for a in attrs)
    if not uncertain and any(position // 2 == shown // 2 for position in vacant):
        uncertain = True  # a position of the target's side was empty at the point: Showdown retargets
    if not uncertain:
        target_side = shown // 2
        before = segment[:index]
        for line in before:
            kind, p = line_kind(line), line.split("|")
            if kind == "-singleturn" and len(p) > 3 and p[3] in REDIRECT_TURN and flat_position(p[2]) is not None \
                    and flat_position(p[2]) // 2 == target_side:
                uncertain = True  # a redirector of the target's side was up
            if kind == "faint" and flat_position(p[2]) is not None and flat_position(p[2]) // 2 == target_side:
                uncertain = True  # the chosen target may have fainted: Showdown retargets
        previous = [line for line in before if line_kind(line) is not None][-1:]
        following = [line for line in segment[index + 1:] if line_kind(line) is not None][:1]
        if any(line_kind(line) == "-activate" and line.split("|")[3:4] and line.split("|")[3] in _REDIRECT_ABILITY
               for line in previous + following):
            uncertain = True  # Lightning Rod or Storm Drain drew it (its line comes right after the move line)
    if not uncertain:
        exact = [i for i in candidates if options_list[i].target == shown]
        if len(exact) == 1:
            return _mask(exact), EXACT
    return _mask(candidates), TARGET_UNKNOWN


def switch_label(log, point, side, lists, member_of, stop_line):
    """The label of a REPLACEMENT or PIVOT point: per asked own slot, the switch of its run, or a pass."""
    end = min(point.end, stop_line)
    segment = log[point.line:end]
    slots, reasons = [], []
    for k in (0, 1):
        options_list = lists[k]
        kinds = {o.kind for o in options_list}
        if kinds == {options.NONE}:
            slots.append(_all(options_list))
            reasons.append(NOT_REQUESTED)
            continue
        position = side * 2 + k
        lines_k = [line for line in segment if line_kind(line) == "switch" and flat_position(line.split("|")[2]) == position]
        revives = [line for line in segment if line_kind(line) == "-heal" and "[from] move: Revival Blessing" in line
                   and line.split("|")[2].startswith(f"p{side + 1}: ")]
        if getattr(point, "revive", False) and position in point.run:
            # Revival Blessing's choice (step G52): the member its -heal line names
            if revives:
                member = member_of(revives[0].split("|")[2].split(": ", 1)[1])
                found = [i for i, o in enumerate(options_list) if o.kind == options.REVIVE and o.reserve == member]
            elif end < point.end:
                found = []
            else:  # no revive before the next action: the request was passed (it comes again)
                found = [i for i, o in enumerate(options_list) if o.kind == options.PASS]
        elif lines_k and position in point.run:
            member = member_of(lines_k[0].split("|")[3])
            found = [i for i, o in enumerate(options_list) if o.kind == options.SWITCH and o.reserve == member]
        elif end < point.end:
            found = []
        else:
            found = [i for i, o in enumerate(options_list) if o.kind == options.PASS]
        if len(found) == 1:
            slots.append(_mask(found))
            reasons.append(EXACT)
        else:
            slots.append(_all(options_list))
            reasons.append(UNKNOWN)
    return Label(tuple(slots), bytes(TEAM_BYTES), tuple(reasons))


@dataclass(frozen=True)
class Context:
    """What a label needs of the tracker at its point: the side, the occupants' moves, the own roster's base formes,
    the tables (labels are read later, once the perspective's stop line is known)."""
    side: int
    moves: tuple  # per slot: the occupant's move ids, or None
    roster: tuple  # the own members' base forme ids
    data: object
    vacant: frozenset = frozenset()  # flat positions empty or fainted at the point

    def member_of(self, details):
        base = self.data.base_forme(self.data.forme(details.split(",")[0]))
        return self.roster.index(base) if self.roster.count(base) == 1 else -1


def context(tracker):
    """The label context of the tracker's current point."""
    own = tracker._own_members
    moves = tuple(list(own[p.occupant].sheet["moves"]) if p.occupant < len(own) else None
                  for p in tracker._positions[tracker.side])
    roster = tuple(tracker.data.base_forme(member.sheet["species"]) for member in own)
    vacant = frozenset(s * 2 + k for s in (0, 1) for k, p in enumerate(tracker._positions[s])
                       if p.occupant >= len(tracker._member(s) or ()) or p.fainted)
    return Context(tracker.side, moves, roster, tracker.data, vacant)


def compute(ctx, log, point, lists, stop_line, leads, seen_back):
    """The label of a point from its context and the whole log."""
    if point.boundary == TEAM_SELECTION:
        return team_label(leads, seen_back, len(ctx.roster))
    if point.boundary == TURN:
        return turn_label(log, point, ctx.side, lists, ctx.moves, ctx.member_of, ctx.data.tables, stop_line,
                          ctx.vacant)
    return switch_label(log, point, ctx.side, lists, ctx.member_of, stop_line)


def for_point(tracker, log, point, lists, stop_line, leads, seen_back):
    """The label of the tracker's current point (spectator.walk)."""
    return compute(context(tracker), log, point, lists, stop_line, leads, seen_back)
