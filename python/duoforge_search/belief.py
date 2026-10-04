"""The belief of the visible-information search (decision 0023, spec section 5):
the spread table of the foe's stat points and the deterministic words of a
world. Numbers only: the engine maps every uniform (HP inside a display,
counters, charging targets) by its own rules; Python never knows those
distributions.

The spread table holds the stated spreads of a team pool (the curated pastes,
whose stat points are real; a set without any stat point is skipped), keyed by
the engine's ids. A draw takes one whole spread of the first key level with
enough sets:
  1. (species, nature, item) with at least min_sets sets;
  2. (species, nature);
  3. species;
  4. nature (any species);
  5. every set.
Leave one team out: the sets of the foe's own team (its pool index) are not
drawn from, so a measurement never draws the true spread from the team it
faces.

The words of world w of a decision (key) under the search seed:
    g      = splitmix64(splitmix64(seed + WORLD_TAG) + key)
    z_w    = splitmix64(g + w)
    x_w,k  = splitmix64(z_w + k)
with a fixed range of k per kind of draw (WORDS), so one draw never shifts
another. A spread is the floor(x * N / 2^64)-th of the N sets of its key in
the table's order: a spread seen c times weighs c.
"""
import hashlib

import numpy as np

from duoforge_learn.pairing import splitmix64

WORLD_TAG = 0x574F524C44000001  # "WORLD"
MIN_SETS = 5
STAT_POINTS = 6
ROSTER = 6
# k ranges of the words of one world.
WORDS = {
    "spread": 1,          # 1..6: foe member m's spread
    "hp": 7,              # 7..12
    "bench": 13,
    "sleep": 14,          # 14..25: side * 6 + member
    "confusion": 26,      # 26..29: side * 2 + position
    "charge_target": 30,  # 30..31
    "queue": 32,
    "respread": 64,       # 64 + 8 * attempt + m: a spread drawn again (a flagged HP display refused the first)
}
_MASK = (1 << 64) - 1
_U64 = np.uint64


def world_words(seed, key, w, ks):
    """The uint64 words x_w,k of world w for the k in ks."""
    with np.errstate(over="ignore"):
        g = splitmix64(splitmix64(_U64(int(seed) & _MASK) + _U64(WORLD_TAG)) + _U64(int(key) & _MASK))
        z = splitmix64(g + _U64(int(w) & _MASK))
        return splitmix64(z + np.asarray(ks, dtype=_U64))


def pick(word, n):
    """floor(word * n / 2^64): the index a 64-bit word picks of n values."""
    if n < 1:
        raise ValueError("pick needs at least one value")
    return (int(word) * int(n)) >> 64


class SpreadTable:
    """The stated spreads of a pool, in a fixed order (by team index, then
    member), with the engine ids of each set."""

    def __init__(self, team, species, nature, item, spreads, min_sets=MIN_SETS):
        self.team = np.asarray(team, dtype=np.int64)
        self.species = np.asarray(species, dtype=np.int64)
        self.nature = np.asarray(nature, dtype=np.int64)
        self.item = np.asarray(item, dtype=np.int64)
        self.spreads = np.asarray(spreads, dtype=np.uint8).reshape(-1, STAT_POINTS)
        n = self.spreads.shape[0]
        if not (self.team.shape == self.species.shape == self.nature.shape == self.item.shape == (n,)):
            raise ValueError("a spread table needs one team, species, nature and item per spread")
        if n == 0:
            raise ValueError("a spread table needs at least one stated spread")
        if (self.spreads > 32).any() or (self.spreads.astype(np.int64).sum(axis=1) > 66).any():
            raise ValueError("a spread is past 32 per stat or 66 in all")
        self.min_sets = int(min_sets)

    @staticmethod
    def from_sides(sides, min_sets=MIN_SETS):
        """The table of SIDE_SETUP records (a TeamPool's sides): team index t
        is the record's position."""
        rows = ([], [], [], [], [])
        for t, side in enumerate(np.asarray(sides).reshape(-1)):
            for k in range(int(side["member_count"])):
                m = side["members"][k]
                sp = np.asarray(m["stat_points"], dtype=np.int64)
                if not sp.any():
                    continue  # no stated spread (an importer's list)
                for col, v in zip(rows, (t, int(m["species_id"]), int(m["nature"]), int(m["item"]), sp)):
                    col.append(v)
        return SpreadTable(*rows, min_sets=min_sets)

    def sha256(self):
        """The hex SHA-256 of the table's content and min_sets (a run's condition)."""
        h = hashlib.sha256()
        for arr in (self.team, self.species, self.nature, self.item):
            h.update(arr.astype("<i8").tobytes())
        h.update(self.spreads.tobytes())
        h.update(int(self.min_sets).to_bytes(4, "little"))
        return h.hexdigest()

    def candidates(self, species, nature, item, exclude_team=None):
        """(level, indices): the key level used (1..5) and the table rows it draws from."""
        keep = np.ones(self.team.shape, dtype=bool) if exclude_team is None else self.team != int(exclude_team)
        levels = (
            keep & (self.species == species) & (self.nature == nature) & (self.item == item),
            keep & (self.species == species) & (self.nature == nature),
            keep & (self.species == species),
            keep & (self.nature == nature),
            keep,
        )
        for level, mask in enumerate(levels, start=1):
            rows = np.flatnonzero(mask)
            if rows.size >= (self.min_sets if level == 1 else 1):
                return level, rows
        raise ValueError("the spread table has no set left once the foe's team is left out")

    def draw(self, word, species, nature, item, exclude_team=None):
        """(spread, level): the whole spread a word picks for a member."""
        level, rows = self.candidates(species, nature, item, exclude_team)
        return self.spreads[rows[pick(word, rows.size)]].copy(), level


class Belief:
    """Version 1 (spec section 5.6): every world weighs 1/W. A later belief
    (M13 lever 3) reweights or redraws the worlds through the same call."""

    def __init__(self, table):
        self.table = table

    def sample(self, members, n, seed, key, exclude_team=None, attempts=None):
        """W = n hypotheses of the foe as arrays, and their weights.

        members: the foe's (species, nature, item) ids, one triple per roster
        member. attempts (optional, (n, ROSTER) ints): how often member m's
        spread of world w was refused already (a flagged HP display); attempt
        a > 0 draws from the word "respread" + 8 * (a - 1) + m.
        Returns a dict of stat_points (n, 6, 6) uint8, hp (n, 6), sleep (n, 2,
        6), confusion (n, 2, 2), charge_target (n, 2) uint64 words, bench and
        queue (n,) uint64 words, levels (n, 6), and weights (n,) float64."""
        members = list(members)
        if len(members) > ROSTER:
            raise ValueError(f"at most {ROSTER} foe members")
        attempts = np.zeros((n, ROSTER), dtype=np.int64) if attempts is None else np.asarray(attempts)
        out = {
            "stat_points": np.zeros((n, ROSTER, STAT_POINTS), dtype=np.uint8),
            "levels": np.zeros((n, ROSTER), dtype=np.int64),
            "hp": np.zeros((n, ROSTER), dtype=np.uint64),
            "sleep": np.zeros((n, 2, ROSTER), dtype=np.uint64),
            "confusion": np.zeros((n, 2, 2), dtype=np.uint64),
            "charge_target": np.zeros((n, 2), dtype=np.uint64),
            "bench": np.zeros(n, dtype=np.uint64),
            "queue": np.zeros(n, dtype=np.uint64),
            "weights": np.full(n, 1.0 / n, dtype=np.float64),
        }
        for w in range(n):
            words = world_words(seed, key, w, np.arange(128))
            for m, (species, nature, item) in enumerate(members):
                a = int(attempts[w, m])
                k = WORDS["spread"] + m if a == 0 else WORDS["respread"] + 8 * (a - 1) + m
                if k >= words.size:
                    raise ValueError(f"member {m} of world {w}: too many spreads refused")
                spread, level = self.table.draw(words[k], species, nature, item, exclude_team)
                out["stat_points"][w, m] = spread
                out["levels"][w, m] = level
            out["hp"][w] = words[WORDS["hp"]:WORDS["hp"] + ROSTER]
            out["sleep"][w] = words[WORDS["sleep"]:WORDS["sleep"] + 2 * ROSTER].reshape(2, ROSTER)
            out["confusion"][w] = words[WORDS["confusion"]:WORDS["confusion"] + 4].reshape(2, 2)
            out["charge_target"][w] = words[WORDS["charge_target"]:WORDS["charge_target"] + 2]
            out["bench"][w] = words[WORDS["bench"]]
            out["queue"][w] = words[WORDS["queue"]]
        return out


def draw_index(probabilities, word):
    """The index a word plays of nonnegative probabilities (bench tuples,
    queue pairs): u = (word >> 11) * 2^-53 against the cumulative sum, as the
    play draw does; the last index with mass if rounding leaves u past it."""
    p = np.asarray(probabilities, dtype=np.float64)
    if p.ndim != 1 or not np.isfinite(p).all() or (p < 0).any() or not p.sum() > 0.0:
        raise ValueError("draw_index needs nonnegative probabilities with a positive sum")
    u = float(int(word) >> 11) * 2.0 ** -53
    c = np.cumsum(p / p.sum())
    hit = np.flatnonzero(c > u)
    return int(hit[0]) if hit.size else int(np.flatnonzero(p > 0)[-1])
