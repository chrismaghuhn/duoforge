"""The data the live adapter needs: ids from the converter's tables, row data from the library.

Ids come from tools/reference/trace_to_c.py (load_tables, parse_team, key):
there is no second id table. What a row holds comes from the loaded
library's data API (decision 0020, python/duoforge/data.py), read once at
load under a context of the kind: the maximum PP and the target class of a
move (move_static), a forme's base forme and Mega forme (forme_info) and the
ability a member of it holds (forme_static: a Mega forme's own; under the
closure the set's), and the Mega forme a stone reaches (item_static). The
library is the one source: the checkout's generated rows and the DLL cannot
disagree (python/tests/test_replay_unit.py GeneratedRowsTest compares them
row by row).

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

# DUOFORGE_TARGET_CLASS_* (include/duoforge/duoforge.h) and the static classes 10 to 15 of duoforge_move_static
# (DUOFORGE_TARGET_CLASS_STATIC_COUNT) -> Showdown's target type
TARGET_TYPES = {1: "normal", 2: "any", 3: "adjacentAlly", 4: "adjacentAllyOrSelf", 5: "adjacentFoe", 6: "self",
                7: "allAdjacentFoes", 8: "allySide", 9: "all", 10: "randomNormal", 11: "allAdjacent", 12: "scripted",
                13: "allyTeam", 14: "allies", 15: "foeSide"}
# The library's data kind of each table kind
_KINDS = {"closure": "DUOFORGE_DATA_KIND_CLOSURE", "pool": "DUOFORGE_DATA_KIND_POOL"}


class Data:
    """Tables of the closure (CLOSURE data), or of the pool (kind "pool": the POOL kinds' tables)."""

    def __init__(self, root=ROOT, kind="closure"):
        if kind not in _KINDS:
            raise ValueError(f"unknown table kind {kind!r}: one of {sorted(_KINDS)}")
        import duoforge
        from duoforge import _layout, data as api
        self.kind = kind
        self._ctx = None  # the context of the alias lookups (_context)
        self.tables = trace_to_c.load_tables(str(Path(root)), kind == "pool")
        with duoforge.Context(data_kind=_layout.CONSTANTS[_KINDS[kind]]) as context:
            self.counts = {"FORME": api.count(context, api.TABLE_SPECIES), "MOVE": api.count(context, api.TABLE_MOVE),
                           "ITEM": api.count(context, api.TABLE_ITEM)}
            for name, table in (("FORME", api.TABLE_SPECIES), ("MOVE", api.TABLE_MOVE), ("ITEM", api.TABLE_ITEM),
                                ("ABILITY", api.TABLE_ABILITY)):
                # The ids are the converter's (the checkout's headers), the rows the library's: each id must name the
                # same row in both, or the rows below would belong to other ids
                count = api.count(context, table)
                names = {k.lower(): v for k, v in self.tables[name].items() if k != "COUNT"}
                if names != {api.name(context, table, i): i for i in range(count)}:
                    raise ValueError(f"the library's {name} names differ from the converter's tables (kind {kind}): "
                                     "the library was built from other tables than this checkout")
            infos = [api.forme_info(context, f) for f in range(self.counts["FORME"])]
            self._ability = [api.forme_static(context, f)["default_ability"] for f in range(self.counts["FORME"])]
            moves = [api.move_static(context, m) for m in range(self.counts["MOVE"])]
            items = [api.item_static(context, i) for i in range(self.counts["ITEM"])]

        def link(value):
            return None if value == api.NONE else value

        self._base = [info["base_species"] for info in infos]
        self._mega = [link(info["mega_species"]) for info in infos]
        self._pp_max = [m["pp"] for m in moves]
        self._target_class = [m["target_class"] for m in moves]
        self._stone = [link(i["mega_species"]) if i["is_mega_stone"] else None for i in items]  # the Mega it reaches

    def team(self, text):
        """A paste as trace_to_c.parse_team reads it: member dicts with species, gender, nature, sp, ability
        (0 for none), item (0 for none), moves (ids)."""
        return trace_to_c.parse_team(text, self.tables)

    def forme(self, name):
        """The forme id of a species name ("Charizard-Mega-Y" as well). A name the converter's tables lack is looked up
        with the library's duoforge_data_find, which maps the POOL tables' cosmetic aliases (#118: "Vivillon-Pokeball",
        "Sinistcha-Masterpiece") to their base row. ValueError for a name neither knows."""
        key = trace_to_c.key(name)
        forme = self.tables["FORME"].get(key) if key != "COUNT" else None  # DFI_FORME_COUNT is no forme
        if forme is None:
            forme = self._find(name)
        if forme is None:
            raise ValueError(f"{name!r} is not a forme of the {self.kind} tables")
        return forme

    def canonical(self, name):
        """The tables' name of the row a species name or alias finds (its Showdown id, "vivillon"): what parse_team and
        the converter read. ValueError for a name neither knows."""
        import duoforge
        from duoforge import data as api
        forme = self.forme(name)
        if self.tables["FORME"].get(trace_to_c.key(name)) == forme:
            return name
        return api.name(self._context(), api.TABLE_SPECIES, forme)

    def _context(self):
        """A context of this kind, opened on the first alias lookup and kept for the next ones."""
        if self._ctx is None:
            import duoforge
            from duoforge import _layout
            self._ctx = duoforge.Context(data_kind=_layout.CONSTANTS[_KINDS[self.kind]])
        return self._ctx

    def _find(self, name):
        """The library's row of a name (duoforge_data_find over its Showdown id), or None."""
        from duoforge import data as api
        from duoforge.errors import DuoforgeError
        ident = re.sub(r"[^a-z0-9]", "", name.lower())
        if not ident:
            return None
        try:
            return api.find(self._context(), api.TABLE_SPECIES, ident)
        except DuoforgeError:
            return None

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
        return self._ability[forme] + 1

    def base_forme(self, forme):
        return self._base[forme]

    def mega_forme(self, forme):
        """The forme's Mega forme (its first, when stones take it to several), or None."""
        return self._mega[forme]

    def mega_of(self, forme, item):
        """The Mega forme that `item` (1-based, 0 for none) takes the forme to, or None: the stone names its Mega,
        whose base forme is its holder (Charizardite X and Y take Charizard to two formes)."""
        if item == 0:
            return None
        mega = self._stone[item - 1]
        return mega if mega is not None and self._base[mega] == forme else None

    def mega_capable(self, forme, item):
        """Whether `item` (1-based, 0 for none) is a Mega Stone of the forme."""
        return self.mega_of(forme, item) is not None


def load(root=ROOT, kind="closure"):
    return Data(root, kind)
