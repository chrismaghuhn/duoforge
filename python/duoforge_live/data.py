"""The data the live adapter needs, from the converter's own tables.

Ids come from tools/reference/trace_to_c.py (load_tables, parse_team, key):
there is no second id table. The maximum PP and the target class of a move
and a forme's Mega data (its Mega forme and stone, its base forme, its
ability) come from the rows of src/data/closure_tables.c, read the way
load_tables reads the gender rules; the test duoforge.python.live_unit
checks them against the library's own view of Teams A and B.

kind "pool" reads the pool tables instead (decision 0015: the closure and
Team C ids as their prefix, then the rows the expansion adds), for the M11
replay pipeline (python/duoforge_replay), whose games use every name of
the tables.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.dont_write_bytecode = True  # importing the converter must not leave __pycache__ in tools/reference
if str(ROOT / "tools" / "reference") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "reference"))
import trace_to_c  # noqa: E402

NONE = 0xFF  # DFI_CLOSURE_NONE
# "No such row" in the generated rows: a number (DFI_CLOSURE_NONE is 0xFF in the closure's 8-bit fields) or a symbol
# (the pool's 16-bit forme links use DFI_FORME_NONE).
_NONE_SYMBOLS = {"DFI_CLOSURE_NONE", "DFI_FORME_NONE"}

# dfi_forme_data: dex_num, weight_hg, types[2], base[6], ability, gender_rule, is_mega, base_forme, mega_forme,
# mega_item, ...
_FORME_ROW = re.compile(r"\{\d+u, \d+u, \{\w+, \w+\}, \{[^}]*\}, (\w+), \w+, \w+, (\w+), (\w+), (\w+),")
# dfi_move_data: type, category, base_power, accuracy, pp_base, pp_max, priority, target_class, ...
_MOVE_ROW = re.compile(r"^    \{\d+u, \d+u, \d+u, \d+u, \d+u, (\d+)u, \d+u, (\d+)u,", re.M)
# DUOFORGE_TARGET_CLASS_* (include/duoforge/duoforge.h), DFI_TARGET_CLASS_RANDOM_NORMAL (10, Struggle only,
# src/data/closure_tables.h) and the pool's classes 11 to 15 (src/data/pool_tables.h) -> Showdown's target type
TARGET_TYPES = {1: "normal", 2: "any", 3: "adjacentAlly", 4: "adjacentAllyOrSelf", 5: "adjacentFoe", 6: "self",
                7: "allAdjacentFoes", 8: "allySide", 9: "all", 10: "randomNormal", 11: "allAdjacent", 12: "scripted",
                13: "allyTeam", 14: "allies", 15: "foeSide"}
# The forme and move rows of each kind: (header, source, count prefix, forme array, move array)
_KINDS = {
    "closure": ("closure_tables.h", "closure_tables.c", "DFI_",
                "dfi_closure_formes[DFI_FORME_COUNT] = {", "dfi_closure_moves[DFI_MOVE_COUNT] = {",
                "dfi_closure_items[DFI_ITEM_COUNT] = {"),
    "pool": ("pool_tables.h", "pool_tables.c", "DFI_POOL_",
             "dfi_pool_formes[DFI_POOL_FORME_COUNT] = {", "dfi_pool_moves[DFI_POOL_MOVE_COUNT] = {",
             "dfi_pool_items[DFI_POOL_ITEM_COUNT] = {"),
}
# dfi_item_data / dfi_pool_item_data: the forme that holds it as a Mega Stone, the Mega forme it reaches
_ITEM_ROW = re.compile(r"^    \{(\w+), (\w+)\},", re.M)


def _value(token):
    """A field of a generated row: 12u -> 12, a NONE symbol -> None."""
    if token in _NONE_SYMBOLS:
        return None
    if not token.endswith("u") or not token[:-1].isdigit():
        raise ValueError(f"a row field {token!r} is neither a number nor a NONE symbol")
    return int(token[:-1])


def _rows(source, start, row, count):
    """The `count` rows of the table that begins with `start`, in id order."""
    a = source.index(start)
    found = row.findall(source[a:source.index("};", a)])
    if len(found) != count:
        raise ValueError(f"{start!r} has {len(found)} rows, not {count}")
    return found


class Data:
    """Tables of the closure (CLOSURE data), or of the pool (kind "pool": the POOL kinds' tables)."""

    def __init__(self, root=ROOT, kind="closure"):
        if kind not in _KINDS:
            raise ValueError(f"unknown table kind {kind!r}: one of {sorted(_KINDS)}")
        root = Path(root)
        header_file, file, prefix, forme_start, move_start, item_start = _KINDS[kind]
        self.kind = kind
        self.tables = trace_to_c.load_tables(str(root), kind == "pool")
        header = (root / "src" / "data" / header_file).read_text(encoding="ascii")
        source = (root / "src" / "data" / file).read_text(encoding="ascii")
        self.counts = {t: int(re.search(rf"#define {prefix}{t}_COUNT (\d+)u", header).group(1))
                       for t in ("FORME", "MOVE", "ITEM")}
        formes = _rows(source, forme_start, _FORME_ROW, self.counts["FORME"])
        self._formes = [tuple(_value(x) for x in f) for f in formes]  # (ability, base_forme, mega_forme, mega_item)
        moves = _rows(source, move_start, _MOVE_ROW, self.counts["MOVE"])
        self._pp_max = [int(pp) for pp, _ in moves]
        self._target_class = [int(target) for _, target in moves]
        items = _rows(source, item_start, _ITEM_ROW, self.counts["ITEM"])
        self._stones = [tuple(_value(x) for x in row) for row in items]  # (mega base forme, Mega forme) per item

    def team(self, text):
        """A paste as trace_to_c.parse_team reads it: member dicts with species, gender, nature, sp, ability
        (0 for none), item (0 for none), moves (ids)."""
        return trace_to_c.parse_team(text, self.tables)

    def forme(self, name):
        """The forme id of a species name ("Charizard-Mega-Y" as well); ValueError outside the closure."""
        key = trace_to_c.key(name)
        forme = self.tables["FORME"].get(key) if key != "COUNT" else None  # DFI_FORME_COUNT is no forme
        if forme is None:
            raise ValueError(f"{name!r} is not a forme of the closure")
        return forme

    def pp_max(self, move_id):
        return self._pp_max[move_id]

    def target_type(self, move_id):
        """Showdown's target type of a move (the options of a synthetic request); ValueError for a target class
        that has none."""
        target_class = self._target_class[move_id]
        if target_class not in TARGET_TYPES:
            raise ValueError(f"move {move_id}: target class {target_class} has no Showdown target type")
        return TARGET_TYPES[target_class]

    def ability_of(self, forme):
        """The forme's ability as a member holds it (the set's; a Mega forme's own), 1-based like parse_team."""
        return self._formes[forme][0] + 1

    def base_forme(self, forme):
        return self._formes[forme][1]

    def mega_forme(self, forme):
        """The forme's Mega forme, or None."""
        mega = self._formes[forme][2]
        return None if mega is None or (self.kind == "closure" and mega == NONE) else mega

    def mega_of(self, forme, item):
        """The Mega forme that `item` (1-based, 0 for none) takes the forme to, or None: the stone's row names its
        holder and its Mega (Charizardite X and Y take Charizard to two formes)."""
        if item == 0:
            return None
        base, mega = self._stones[item - 1]
        if base is None or mega is None or (self.kind == "closure" and NONE in (base, mega)) or base != forme:
            return None
        return mega

    def mega_capable(self, forme, item):
        """Whether `item` (1-based, 0 for none) is a Mega Stone of the forme."""
        return self.mega_of(forme, item) is not None


def load(root=ROOT, kind="closure"):
    return Data(root, kind)
