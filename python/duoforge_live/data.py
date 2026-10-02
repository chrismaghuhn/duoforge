"""The data the live adapter needs, from the converter's own tables.

Ids come from tools/reference/trace_to_c.py (load_tables, parse_team, key):
there is no second id table. The maximum PP of a move and a forme's Mega
data (its Mega forme and stone, its base forme, its ability) come from the
rows of src/data/closure_tables.c, read the way load_tables reads the
gender rules; the test duoforge.python.live_unit checks them against the
library's own view of Teams A and B.
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

# dfi_forme_data: dex_num, weight_hg, types[2], base[6], ability, gender_rule, is_mega, base_forme, mega_forme,
# mega_item, ...
_FORME_ROW = re.compile(r"\{\d+u, \d+u, \{\d+u, \d+u\}, \{[^}]*\}, (\d+)u, \d+u, \d+u, (\d+)u, (\d+)u, (\d+)u,")
# dfi_move_data: type, category, base_power, accuracy, pp_base, pp_max, ...
_MOVE_ROW = re.compile(r"^    \{\d+u, \d+u, \d+u, \d+u, \d+u, (\d+)u,", re.M)


def _rows(source, start, row, count):
    """The `count` rows of the table that begins with `start`, in id order."""
    a = source.index(start)
    found = row.findall(source[a:source.index("};", a)])
    if len(found) != count:
        raise ValueError(f"closure_tables.c: {start!r} has {len(found)} rows, not {count}")
    return found


class Data:
    """Tables of the closure (CLOSURE data)."""

    def __init__(self, root=ROOT):
        root = Path(root)
        self.tables = trace_to_c.load_tables(str(root), False)
        source = (root / "src" / "data" / "closure_tables.c").read_text(encoding="ascii")
        formes = _rows(source, "dfi_closure_formes[DFI_FORME_COUNT] = {", _FORME_ROW, self.tables["FORME"]["COUNT"])
        self._formes = [tuple(int(x) for x in f) for f in formes]  # (ability, base_forme, mega_forme, mega_item)
        moves = _rows(source, "dfi_closure_moves[DFI_MOVE_COUNT] = {", _MOVE_ROW, self.tables["MOVE"]["COUNT"])
        self._pp_max = [int(x) for x in moves]

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

    def ability_of(self, forme):
        """The forme's ability as a member holds it (the set's; a Mega forme's own), 1-based like parse_team."""
        return self._formes[forme][0] + 1

    def base_forme(self, forme):
        return self._formes[forme][1]

    def mega_forme(self, forme):
        """The forme's Mega forme, or None."""
        mega = self._formes[forme][2]
        return None if mega == NONE else mega

    def mega_capable(self, forme, item):
        """Whether `item` (1-based, 0 for none) is the stone of the forme's Mega."""
        stone = self._formes[forme][3]
        return item != 0 and stone != NONE and item - 1 == stone


def load(root=ROOT):
    return Data(root)
