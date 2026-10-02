"""Superset options of an own decision point (M11 spec section 8).

A replay has no request. superset.domain() builds the request the player
would have received as far as the view knows it, and gives it to the live
adapter's options.slot_options, which lists DuoForge's slot options in its
documented order:

- every sheet move whose PP left (maximum minus the uses seen) is above 0,
  with the target type of the move's target class in the tables;
- Mega Evolution when the member holds its stone and its side has not used
  Mega Evolution; never trapped;
- the reserves: the alive brought members on the bench (hindsight picks);
- a charging position only its locked move with its stored target, a
  choice-locked one only its locked move, Struggle when no usable move has
  PP left;
- at a REPLACEMENT or PIVOT, forceSwitch for the asked positions.

The pair mask is the provisional full one, as live. The set contains every
option of the real request (duoforge.python.replay checks it) and may
contain more: moves an effect outside the view disables (Fake Out after the
first turn, Taunt, Imprison, Assault Vest), switches of a trapped position.
"""
from duoforge_live import options
from duoforge_live.tracker import MOVE_SLOT_NONE

from .points import TEAM_SELECTION, TURN

BROUGHT = 4


def _move_name(tracker, move_id):
    names = tracker.__dict__.setdefault("_move_names", {v: k for k, v in tracker.data.tables["MOVE"].items()
                                                        if k != "COUNT"})
    return names[move_id].lower()


def domain(tracker):
    """(FACTORED_DOMAIN record, slot lists) at the tracker's point; at team selection (team domain, None)."""
    side = tracker.side
    epoch = tracker.epoch
    if tracker.boundary() == TEAM_SELECTION:
        return options.team_domain(epoch, len(tracker.own_sheets), BROUGHT), None
    members = tracker._own_members
    positions = tracker._positions[side]
    actives = [p.occupant for p in positions]
    order = list(actives) + [m for m in tracker._picks if m not in actives]
    roster_of, pokemon = {}, []
    for k, m in enumerate(order):
        ident = f"p{side + 1}: member{k}"
        member = members[m] if m < len(members) else None  # an empty position holds DUOFORGE_ROSTER_NONE
        alive = member is not None and not (member.seen and member.hp_percent == 0)
        if k < 2 and positions[k].fainted:
            alive = False
        roster_of[ident] = m
        pokemon.append({"ident": ident, "active": k < 2, "condition": "100/100" if alive else "0 fnt",
                        "moves": [_move_name(tracker, mv) for mv in member.sheet["moves"]] if member else []})
    request = {"side": {"id": f"p{side + 1}", "pokemon": pokemon}}
    locked = {}
    struggle_too = [False, False]
    if tracker.boundary() == TURN:
        request["active"] = []
        for k, p in enumerate(positions):
            member = members[p.occupant] if p.occupant < len(members) else None
            if member is None:
                request["active"].append(None)
                continue
            sheet_moves = member.sheet["moves"]
            pp = [max(mx - u, 0) for mx, u in zip(member.pp_max, member.uses)]
            if p.charge:
                request["active"].append({"moves": [{"id": _move_name(tracker, sheet_moves[p.locked_slot])}]})
                locked[k] = p.locked_target
                continue
            usable = [pp[i] > 0 and (p.choice_slot == MOVE_SLOT_NONE or i == p.choice_slot)
                      for i in range(len(sheet_moves))]
            if not any(usable):  # no PP left, or none for the choice-locked move: Struggle
                request["active"].append({"moves": [{"id": "struggle"}]})
                continue
            struggle_too[k] = sum(usable) == 1
            moves = []
            for i, move_id in enumerate(sheet_moves):
                disabled = not usable[i]
                moves.append({"id": _move_name(tracker, move_id), "pp": pp[i],
                              "target": tracker.data.target_type(move_id), "disabled": disabled})
            mega = member.mega_capable and not member.is_mega and not tracker._mega_used[side]
            request["active"].append({"moves": moves, "canMegaEvo": bool(mega)})
    else:
        asked = tracker._asked[side][1]
        request["forceSwitch"] = [bool(asked >> k & 1) for k in (0, 1)]
    lists = options.slot_options(request, side, roster_of, locked)
    for k, needs in enumerate(struggle_too):
        has = any(o.kind == options.MOVE and o.move_slot == options.STRUGGLE for o in lists[k])
        if needs and not has and any(o.kind == options.MOVE for o in lists[k]):
            # One usable move only (a choice lock, or PP left in one move): an effect outside the view can disable it
            # (Fake Out after the first turn, c07_choice_lock), and then the request offers Struggle.
            lists[k] = lists[k] + [options.Option(options.MOVE, options.STRUGGLE, options.TARGET_NONE, 0, 0, "move 1")]
    return options.domain(lists, epoch), lists

