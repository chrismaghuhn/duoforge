"""The stat point prior of the own side (M11 spec section 10).

A replay never shows Stat Points. The own members' stat points come from
public pastes (VGCPastes, kept outside the repository): for each key, the
most frequent spread among the pastes, a tie going to the smallest spread
tuple. An own member takes the first level whose key matches its open sheet:

    0  species, item, ability, nature and the move set
    1  species, nature, item
    2  species, nature
    3  species
    4  no paste: every stat point 0

Every row stores the level of each own member (prior_level), so a trainer
can filter. Keys are Showdown ids (to_id). Stats are never computed here
(stats.py asks the pinned Showdown).
"""
import collections
import json
import re
from pathlib import Path

LEVELS = 4  # keyed levels 0..3; level 4 is "no paste"
STATS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
_IGNORED = ("Shiny:", "IVs:", "Tera Type:", "Happiness:", "Level:", "Gigantamax:", "Pokeball:", "Dynamax Level:")
STAT_POINTS_MAX = 32  # DUOFORGE_STAT_POINTS_MAX (include/duoforge/duoforge.h)


def to_id(name):
    """Showdown's toID: lower-case letters and digits."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def keys(species, item, ability, nature, moves):
    """The keys of levels 0..3 of a set (names in any spelling)."""
    s, i, a, n = to_id(species), to_id(item), to_id(ability), to_id(nature)
    move_set = ",".join(sorted(to_id(m) for m in moves))
    return (f"{s}|{i}|{a}|{n}|{move_set}", f"{s}|{n}|{i}", f"{s}|{n}", s)


def parse_paste(text):
    """The sets of one paste: [(species, item, ability, nature, moves, stat points)]. ValueError names a line that is
    neither a set line nor a cosmetic one, or stat points above the maximum (EVs, not a Champions paste)."""
    sets = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [r.strip() for r in block.strip().splitlines() if r.strip()]
        if not rows:
            continue
        head, item = (rows[0].split(" @ ", 1) + [""])[:2]
        head = re.sub(r"\s*\((M|F)\)$", "", head.strip())
        nick = re.fullmatch(r".+\((.+)\)", head)
        species = nick.group(1) if nick else head
        ability, nature, moves, sp = "", "", [], [0] * 6
        for row in rows[1:]:
            if row.startswith("Ability:"):
                ability = row[len("Ability:"):].strip()
            elif row.startswith("EVs:"):
                for part in row[len("EVs:"):].split("/"):
                    value, stat = part.split()
                    sp[STATS.index(stat)] = int(value)
            elif row.endswith(" Nature"):
                nature = row[:-len(" Nature")].strip()
            elif row.startswith("- "):
                moves.append(row[2:].strip())
            elif not row.startswith(_IGNORED):
                raise ValueError(f"unknown paste line {row!r}")
        if max(sp) > STAT_POINTS_MAX:
            raise ValueError(f"{species}: {sp} are EVs, not stat points")
        sets.append((species, item.strip(), ability, nature, moves, sp))
    return sets


def build(paste_dir):
    """The prior of every *.txt paste in paste_dir, as the JSON-ready dict the file holds."""
    counts = [collections.defaultdict(collections.Counter) for _ in range(LEVELS)]
    pastes, skipped = 0, collections.Counter()
    for path in sorted(Path(paste_dir).glob("*.txt")):
        try:
            sets = parse_paste(path.read_text(encoding="utf-8"))
        except ValueError as e:
            skipped[str(e).split(":")[0] if "unknown paste line" in str(e) else "not stat points"] += 1
            continue
        pastes += 1
        for species, item, ability, nature, moves, sp in sets:
            for level, key in enumerate(keys(species, item, ability, nature, moves)):
                counts[level][key][tuple(sp)] += 1
    levels = []
    for level in counts:
        out = {}
        for key, spreads in sorted(level.items()):
            spread, n = min(spreads.items(), key=lambda kv: (-kv[1], kv[0]))  # most frequent, then smallest
            out[key] = [list(spread), n]
        levels.append(out)
    return {"version": 1, "pastes": pastes, "skipped": dict(sorted(skipped.items())), "levels": levels}


class Prior:
    """A built prior: lookup(set) -> (stat points, level)."""

    def __init__(self, data):
        if data.get("version") != 1 or len(data.get("levels", ())) != LEVELS:
            raise ValueError("not a version 1 prior")
        self.data = data

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def lookup(self, sheet):
        """The stat points and level of an open sheet (a teams.unpack set: species, item, ability, nature, moves)."""
        for level, key in enumerate(keys(sheet["species"], sheet["item"], sheet["ability"], sheet["nature"],
                                         sheet["moves"])):
            hit = self.data["levels"][level].get(key)
            if hit is not None:
                return list(hit[0]), level
        return [0] * 6, LEVELS
