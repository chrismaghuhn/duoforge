"""A Showdown request as DuoForge's slot options, and choices as Showdown text.

slot_options(request, side, roster_of, locked) lists, per slot of the side,
the commands DuoForge offers at that boundary (src/state/request.c,
dfi_slot_candidates), in its documented order, each with the text that
chooses it in Showdown. The request is the authority live; the test
duoforge.python.live checks the lists against DuoForge's own factored domain
at every request of every committed closure battle, and every text back
through the converter (trace_to_c.convert_choice).

The pair mask is provisional (spec section 5): every pair of two options is
allowed, and Showdown judges a pair (two switches to one Pokemon, two Mega
Evolutions) when it is chosen.
"""
from dataclasses import dataclass

import numpy as np

from duoforge import _layout

C = _layout.CONSTANTS
NONE, MOVE, SWITCH, PASS = (C[f"DUOFORGE_SLOT_{n}"] for n in ("NONE", "MOVE", "SWITCH", "PASS"))
TARGET_NONE = C["DUOFORGE_TARGET_NONE"]
STRUGGLE = 4  # DUOFORGE_MOVE_SLOT_STRUGGLE (include/duoforge/duoforge.h)
TEAM, SLOTS = C["DUOFORGE_CHOICE_TEAM_SELECTION"], C["DUOFORGE_CHOICE_SLOTS"]

# Showdown's target types: those that take a chosen target, and those that do not.
_AIMED = {"normal", "any", "adjacentAlly", "adjacentAllyOrSelf", "adjacentFoe"}
_UNAIMED = {"self", "allAdjacentFoes", "allAdjacent", "allySide", "foeSide", "all", "allies", "allyTeam",
            "randomNormal", "scripted"}


@dataclass(frozen=True)
class Option:
    """One command of a slot list (the SLOT_COMMAND fields) and its Showdown text."""
    kind: int
    move_slot: int
    target: int
    mega: int
    reserve: int
    text: str


def _targets(target_type, side, slot):
    """The positions a move of this target type can aim at, ascending (dfi_targets)."""
    me, ally = side * 2 + slot, side * 2 + 1 - slot
    foes = [(1 - side) * 2, (1 - side) * 2 + 1]
    if target_type in ("normal", "any"):
        return [p for p in range(4) if p != me]
    if target_type == "adjacentAlly":
        return [ally]
    if target_type == "adjacentAllyOrSelf":
        return sorted((me, ally))
    if target_type == "adjacentFoe":
        return foes
    if target_type in _UNAIMED:
        return [TARGET_NONE]
    raise ValueError(f"unknown target type {target_type!r}")


def _location(side, target):
    """Showdown's target location of a position: foes 1 and 2, the own side -1 and -2."""
    return str(target % 2 + 1) if target // 2 != side else str(-(target % 2 + 1))


def _alive(mon):
    return mon is not None and not mon["condition"].endswith(" fnt")


def _reserves(request, roster_of):
    """(roster index, text) of every Pokemon that can come in, ascending by roster index."""
    out = []
    for pos, mon in enumerate(request["side"]["pokemon"]):
        if not mon["active"] and _alive(mon):
            out.append((roster_of[mon["ident"]], f"switch {pos + 1}"))
    return sorted(out)


def own_roster(request, own_members, data):
    """{ident: roster index} of the request's Pokemon: the member whose species is the base forme of the
    species in its details (species are unique in a team)."""
    out = {}
    for mon in request["side"]["pokemon"]:
        base = data.base_forme(data.forme(mon["details"].split(",")[0]))
        index = [m for m, member in enumerate(own_members) if member["species"] == base]
        if len(index) != 1:
            raise ValueError(f"{mon['ident']} ({mon['details']}) is not one member of the own team")
        out[mon["ident"]] = index[0]
    return out


def slot_options(request, side, roster_of, locked):
    """The two slot lists of a move or switch request (not a wait or team preview request)."""
    pokemon = request["side"]["pokemon"]
    lists = []
    for slot in range(2):
        mon = pokemon[slot] if slot < len(pokemon) and pokemon[slot]["active"] else None
        out = []
        if "active" in request:
            entry = request["active"][slot] if slot < len(request["active"]) else None
            if entry is None or not _alive(mon):
                lists.append([Option(PASS, 0, 0, 0, 0, "pass")])
                continue
            moves = entry["moves"]
            if len(moves) == 1 and moves[0]["id"] == "struggle":
                out.append(Option(MOVE, STRUGGLE, TARGET_NONE, 0, 0, "move 1"))
            elif len(moves) == 1 and "pp" not in moves[0]:
                if slot not in locked:
                    raise ValueError(f"slot {slot} is locked into {moves[0]['id']} without a known target")
                own = [m.lower() for m in mon["moves"]]
                out.append(Option(MOVE, own.index(moves[0]["id"]), locked[slot], 0, 0, "move 1"))
            else:
                megas = (0, 1) if entry.get("canMegaEvo") else (0,)
                for i, move in enumerate(moves):
                    if move.get("disabled") or move["pp"] <= 0:
                        continue
                    for target in _targets(move["target"], side, slot):
                        aim = "" if target == TARGET_NONE else " " + _location(side, target)
                        for mega in megas:
                            out.append(Option(MOVE, i, target, mega, 0, f"move {i + 1}{aim}" + (" mega" if mega else "")))
            if not entry.get("trapped"):
                out += [Option(SWITCH, 0, 0, 0, r, text) for r, text in _reserves(request, roster_of)]
        elif "forceSwitch" in request:
            if not request["forceSwitch"][slot]:
                lists.append([Option(NONE, 0, 0, 0, 0, "pass")])
                continue
            out = [Option(SWITCH, 0, 0, 0, r, text) for r, text in _reserves(request, roster_of)]
            out.append(Option(PASS, 0, 0, 0, 0, "pass"))
        else:
            raise ValueError("not a move or switch request")
        lists.append(out)
    return lists


def domain(lists, epoch):
    """The FACTORED_DOMAIN record of two slot lists, with the provisional pair mask."""
    d = np.zeros((), dtype=_layout.FACTORED_DOMAIN)
    d["epoch"], d["kind"] = epoch, SLOTS
    for s in (0, 1):
        if not 0 < len(lists[s]) <= _layout.MAX_SLOT_OPTIONS:
            raise ValueError(f"slot list {s} has {len(lists[s])} options")
        d["slot_count"][s] = len(lists[s])
        for i, o in enumerate(lists[s]):
            d["slots"][s][i] = (o.kind, o.move_slot, o.target, o.mega, o.reserve, (0, 0, 0))
    d["allowed"][:len(lists[0])] = (1 << len(lists[1])) - 1
    return d


def team_domain(epoch, member_count, pick_count):
    d = np.zeros((), dtype=_layout.FACTORED_DOMAIN)
    d["epoch"], d["kind"], d["member_count"], d["pick_count"] = epoch, TEAM, member_count, pick_count
    return d


def none_domain(epoch):
    """The domain of a player who is not asked (kind 0)."""
    d = np.zeros((), dtype=_layout.FACTORED_DOMAIN)
    d["epoch"] = epoch
    return d


def pair_text(a, b):
    return f"{a.text}, {b.text}"


def team_text(picks):
    """Showdown's team choice of roster indices, leads first."""
    return "team " + "".join(str(p + 1) for p in picks)
