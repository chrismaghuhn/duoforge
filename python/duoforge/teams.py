"""Teams for training (decision 0017): the registry loader and the team pool.

load reads teams from the registry (data/teams: index.json and <id>.txt,
Showdown pastes with every gender stated), checks each file against the
index hash, maps names to ids with the library's data query API and lets
the library judge each team by creating a battle of the team against
itself; a team it refuses raises TeamError naming the team and the status.

A TeamPool holds the teams a run plays: their registry ids, the sha256 of
their files ("" for teams made from setups), sampling weights and side
setups (SIDE_SETUP). It builds the battle setups of pairs of team indices;
the library checks them when a battle starts, so nothing here decides
legality.
"""
import ctypes
import dataclasses
import hashlib
import json
import math
import os
import re

import numpy as np

from . import _layout, data
from ._lib import load_library, ptr, status_name
from .errors import DuoforgeError


class TeamError(ValueError):
    """A team cannot be read or the library refuses it; the message names it."""


_STATS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
_HEAD = re.compile(r"^(?P<species>[^()@]+?)(?: \((?P<gender>[MF])\))?(?: @ (?P<item>.+))?$")
_NATURE = re.compile(r"^(?P<nature>[A-Z][a-z]+) Nature$")


def text_sha256(data):
    """The sha256 (hex) of a team file's bytes after CRLF -> LF: the hash the
    registry's index.json gives, equal on every checkout."""
    return hashlib.sha256(bytes(data).replace(b"\r\n", b"\n")).hexdigest()


def parse(text, name="<text>"):
    """The members of a registry paste: per member a dict with species,
    gender ("M", "F" or None), item (or None), ability, stat_points (HP to
    Spe), nature and moves (1 to 4). Text only: legality is the library's.
    Any line this format does not have raises TeamError naming the file,
    the line and the reason."""
    members, block = [], []
    lines = text.replace("\r\n", "\n").split("\n")
    for number, raw in enumerate(lines + [""], start=1):
        line = raw.rstrip()
        if line.strip():
            block.append((number, line))
        elif block:
            members.append(_member(block, name))
            block = []
    if not members:
        raise TeamError(f"{name}: no members")
    return members


def _member(block, name):
    def fail(number, reason):
        raise TeamError(f"{name}:{number}: {reason}")

    number, head = block[0]
    m = _HEAD.match(head)
    if m is None:
        fail(number, "a nickname (Name (Species)) is not supported" if "(" in head.split(" @ ")[0]
             else f"first line {head!r} is not 'Species (M|F) @ Item'")
    member = {"species": m.group("species").strip(), "gender": m.group("gender"), "item": m.group("item"),
              "ability": None, "stat_points": [0] * 6, "nature": None, "moves": []}
    seen = set()
    for number, line in block[1:]:
        key = line.split(":", 1)[0] if ":" in line else None
        if key in seen:
            fail(number, f"{key} is given twice")
        if line.startswith("Ability: "):
            member["ability"] = line[len("Ability: "):].strip()
        elif line.startswith("Level: "):
            if line[len("Level: "):].strip() != "50":
                fail(number, f"level {line[len('Level: '):].strip()}: battles are at level 50")
        elif line.startswith("EVs: "):
            for part in line[len("EVs: "):].split(" / "):
                bits = part.split()
                if len(bits) != 2 or not bits[0].isdigit() or bits[1] not in _STATS:
                    fail(number, f"EVs part {part!r} is not '<Stat Points> <{'|'.join(_STATS)}>'")
                member["stat_points"][_STATS.index(bits[1])] = int(bits[0])
        elif _NATURE.match(line):
            if member["nature"] is not None:
                fail(number, "the nature is given twice")
            member["nature"] = _NATURE.match(line).group("nature")
            continue
        elif line.startswith("- "):
            if len(member["moves"]) == 4:
                fail(number, "more than 4 moves")
            member["moves"].append(line[2:].strip())
            continue
        else:
            fail(number, f"unknown line {line!r}")
        seen.add(key)
    first = block[0][0]
    if member["ability"] is None:
        fail(first, "no Ability line")
    if member["nature"] is None:
        fail(first, "no Nature line")
    if not member["moves"]:
        fail(first, "no moves")
    return member


def _weights(weights, n):
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)
    if w.shape != (n,):
        raise ValueError(f"{w.size} weights for {n} teams")
    for i, x in enumerate(w.tolist()):
        if not math.isfinite(x) or x < 0:
            raise ValueError(f"team weight {i} is {x}: weights must be finite and at least 0")
    if w.sum() <= 0:
        raise ValueError("the team weights sum to 0: no team could be drawn")
    if not math.isfinite(w.sum()):
        raise ValueError("the team weights sum to infinity: scale them down")
    return w


@dataclasses.dataclass(frozen=True)
class TeamPool:
    ids: tuple
    sha256: tuple
    weights: np.ndarray
    sides: np.ndarray

    def __post_init__(self):
        n = len(self.ids)
        if len(set(self.ids)) != n:
            raise ValueError(f"team ids are not unique: {self.ids}")
        if len(self.sha256) != n or self.sides.dtype != _layout.SIDE_SETUP or self.sides.shape != (n,):
            raise ValueError(f"a pool of {n} teams needs {n} hashes and {n} SIDE_SETUP records")
        object.__setattr__(self, "weights", _weights(self.weights, n))

    @staticmethod
    def from_setups(ids, sides, weights=None):
        """A pool of side setups (SIDE_SETUP, (N,)) with ids and no files."""
        sides = np.array(sides, dtype=_layout.SIDE_SETUP).reshape(-1)
        return TeamPool(tuple(ids), ("",) * len(tuple(ids)), weights, sides)

    def with_weights(self, weights):
        return dataclasses.replace(self, weights=weights)

    def setups(self, side0, side1):
        """Battle setups (SETUP, (K,)) of team indices side0 and side1; the
        rng fields are 0 (a batch derives them)."""
        side0, side1 = np.asarray(side0), np.asarray(side1)
        out = np.zeros(side0.shape[0], dtype=_layout.SETUP)
        out["sides"][:, 0] = self.sides[side0]
        out["sides"][:, 1] = self.sides[side1]
        return out


_GENDERS = {"M": _layout.CONSTANTS["DUOFORGE_GENDER_MALE"], "F": _layout.CONSTANTS["DUOFORGE_GENDER_FEMALE"],
            None: _layout.CONSTANTS["DUOFORGE_GENDER_NONE"]}


def side_setup(context, members, team):
    """The SIDE_SETUP record of parsed members (parse); TeamError for a name
    the context's data kind does not have."""
    side = np.zeros((), dtype=_layout.SIDE_SETUP)
    if len(members) > _layout.MAX_ROSTER:
        raise TeamError(f"team {team}: {len(members)} members, at most {_layout.MAX_ROSTER}")
    side["member_count"] = len(members)

    tables = {"species": data.TABLE_SPECIES, "move": data.TABLE_MOVE, "item": data.TABLE_ITEM,
              "ability": data.TABLE_ABILITY, "nature": data.TABLE_NATURE}

    def find(table, name, k):
        try:
            return data.find(context, tables[table], data.to_id(name))
        except DuoforgeError:
            raise TeamError(f"team {team}: member {k + 1}: {table} {data.to_id(name)!r} is not in the tables of "
                            f"this context's data kind") from None

    for k, m in enumerate(members):
        out = side["members"][k]
        out["species_id"] = find("species", m["species"], k)
        out["gender"] = _GENDERS[m["gender"]]
        out["nature"] = find("nature", m["nature"], k)
        out["stat_points"] = m["stat_points"]
        out["ability"] = 1 + find("ability", m["ability"], k)
        out["item"] = 0 if m["item"] is None else 1 + find("item", m["item"], k)
        out["move_count"] = len(m["moves"])
        for j, move in enumerate(m["moves"]):
            out["moves"][j]["move_id"] = find("move", move, k)
    return side


def check(context, side):
    """The status of duoforge_battle_create for the team against itself (0: accepted)."""
    lib = load_library()
    setup = np.zeros(1, dtype=_layout.SETUP)
    setup["sides"][0, 0] = side
    setup["sides"][0, 1] = side
    battle = ctypes.c_void_p()
    st = lib.duoforge_battle_create(context.handle, ptr(setup), ctypes.byref(battle))
    if st == 0:
        lib.duoforge_battle_destroy(battle)
    return int(st)


def load(context, ids, root="data/teams", weights=None):
    """The TeamPool of registry teams ids under the context: each file must
    match its index hash, parse, map to ids and be accepted by the library."""
    index_path = os.path.join(root, "index.json")
    with open(index_path, encoding="utf-8") as f:
        index = {t["id"]: t for t in json.load(f)["teams"]}
    shas, sides = [], []
    for team in ids:
        if team not in index:
            raise TeamError(f"team {team} is not in {index_path}")
        path = os.path.join(root, f"{team}.txt")
        with open(path, "rb") as f:
            raw = f.read()
        sha = text_sha256(raw)
        if sha != index[team]["sha256"]:
            raise TeamError(f"team {team}: {path} has sha256 {sha}, the index says {index[team]['sha256']}")
        side = side_setup(context, parse(raw.decode("utf-8"), path), team)
        st = check(context, side)
        if st != 0:
            raise TeamError(f"team {team} is refused under this context's data kind: {status_name(st)}")
        shas.append(sha)
        sides.append(side)
    return TeamPool(tuple(ids), tuple(shas), weights, np.array(sides, dtype=_layout.SIDE_SETUP))
