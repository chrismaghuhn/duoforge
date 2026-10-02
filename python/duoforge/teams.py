"""Teams for training (decision 0017): the team pool, and (Task 17) the
registry loader.

A TeamPool holds the teams a run plays: their registry ids, the sha256 of
their files ("" for teams made from setups), sampling weights and side
setups (SIDE_SETUP). It builds the battle setups of pairs of team indices;
the library checks them when a battle starts, so nothing here decides
legality.
"""
import dataclasses
import hashlib
import math
import re

import numpy as np

from . import _layout


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
