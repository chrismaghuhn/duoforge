"""The data the live adapter needs: ids from the converter's tables, row data from the library.

Ids come from tools/reference/trace_to_c.py (load_tables, parse_team, key):
there is no second id table. What a row holds comes from the loaded
library's data API (decision 0020, python/duoforge/data.py), read once at
load under a context of the kind: the maximum PP and the target class of a
move (move_static), a forme's base forme and Mega forme (forme_info) and the
ability a member of it holds (forme_static: a Mega forme's own; under the
closure the set's), and the Mega forme a stone takes each holder to (duoforge_data_mega_at). The
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
        self.checkpoint_check = None  # for_config: how a format-2 checkpoint reads these tables (checkpoint.check_data)
        self._ctx = None  # the context of the alias lookups and the legality (_context)
        self._legal = {}  # forme -> (setup_legal, abilities, no_ability, moves): setup_issue
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
            # Every (holder, stone) pair the library knows (duoforge_data_mega_at): one stone may take two holders
            # to two Megas (Meowsticite: Meowstic-M and Meowstic-F), so the stone alone does not name its Mega.
            self._mega_pairs = {}
            for forme in range(self.counts["FORME"]):
                for k in range(api.mega_count(context, forme)):
                    entry = api.mega_at(context, forme, k)
                    self._mega_pairs[(forme, int(entry["stone"]))] = int(entry["mega_species"])

        def link(value):
            return None if value == api.NONE else value

        self._base = [info["base_species"] for info in infos]
        self._mega = [link(info["mega_species"]) for info in infos]
        self._pp_max = [m["pp"] for m in moves]
        self._target_class = [m["target_class"] for m in moves]
        self._move_flags = [m["flags"] for m in moves]  # DUOFORGE_MOVE_STATIC_FLAG_*

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

    def setup_issue(self, member):
        """None when the library's setup would accept a parsed member (parse_team: species, ability 1-based, moves) on
        its legality under this kind; else ("species", None), ("ability", None) or ("move", index of the move): the
        first of duoforge_data_forme_info's and duoforge_data_forme_moves' rules it breaks (the setup validates the
        same). The support gate is not part of it."""
        from duoforge import data as api
        forme = member["species"]
        if forme not in self._legal:
            info = api.forme_info(self._context(), forme)
            abilities = set(info["abilities"][:info["ability_count"]])
            self._legal[forme] = (bool(info["setup_legal"]), abilities, bool(info["no_ability"]),
                                  set(api.forme_moves(self._context(), forme)))
        legal, abilities, no_ability, moves = self._legal[forme]
        if not legal:
            return ("species", None)
        if (member["ability"] == 0 and not no_ability) or (member["ability"] != 0 and member["ability"] - 1 not in abilities):
            return ("ability", None)
        for index, move in enumerate(member["moves"]):
            if move not in moves:
                return ("move", index)
        return None

    def _context(self):
        """A context of this kind, opened on the first alias lookup and kept for the next ones."""
        if self._ctx is None:
            import duoforge
            from duoforge import _layout
            self._ctx = duoforge.Context(data_kind=_layout.CONSTANTS[_KINDS[self.kind]])
        return self._ctx

    def context(self):
        """The context of this kind (opened on first use and kept): the library calls of the record assembler."""
        return self._context()

    def context_of(self, data_kind=None):
        """The context of the library data kind `data_kind` (None: this kind; a DEV kind of the same tables), kept open:
        the record assembler's engine calls of a record of that context."""
        from duoforge import _layout
        import duoforge
        if data_kind is None or data_kind == _layout.CONSTANTS[_KINDS[self.kind]]:
            return self._context()
        contexts = self.__dict__.setdefault("_contexts", {})
        if data_kind not in contexts:
            contexts[data_kind] = duoforge.Context(data_kind=data_kind)
        return contexts[data_kind]

    def record_head(self, data_kind=None):
        """(head, state_size) of a public record under this kind (or the library data kind `data_kind`, a DEV kind of the
        same tables): the bytes of the canonical encoding before its RNG (the envelope and the context fingerprint,
        constants of the context) and the encoding's size, read from the engine's own record of a reference battle at team
        preview (duoforge_batch_public), kept after the first call. The live record assembler (record.py) copies them."""
        import duoforge
        import numpy as np
        from duoforge import _layout, state_layout
        if data_kind is None:
            data_kind = _layout.CONSTANTS[_KINDS[self.kind]]
        heads = self.__dict__.setdefault("_record_heads", {})
        if data_kind not in heads:
            context = self._context() if data_kind == _layout.CONSTANTS[_KINDS[self.kind]] else \
                duoforge.Context(data_kind=data_kind)
            try:
                with duoforge.Batch(context, duoforge.reference_setups([0]), 1, 0) as batch:
                    records, statuses = batch.public(np.zeros(1, np.uint32))
                    if int(statuses[0]) != 0:
                        raise ValueError(f"no public record of the reference battle: status {int(statuses[0])}")
                    start = dict((n, s) for n, s, _ in state_layout.fields(pool=False))["rng.state"]
                    heads[data_kind] = (bytes(records["state"][0][:start]), int(records["state_size"][0]))
            finally:
                if context is not self._ctx:
                    context.close()
        return heads[data_kind]

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

    def move_flags(self, move_id):
        """The DUOFORGE_MOVE_STATIC_FLAG_* bits of a move (duoforge_move_static)."""
        return self._move_flags[move_id]

    def target_type(self, move_id):
        """Showdown's target type of a move (the options of a synthetic request); ValueError for a target class
        that has none."""
        target_class = self._target_class[move_id]
        if target_class not in TARGET_TYPES:
            raise ValueError(f"move {move_id}: target class {target_class} has no Showdown target type")
        return TARGET_TYPES[target_class]

    def request_target(self, move_id, types):
        """Showdown's target type of a move in the request of a user of the given current types (DUOFORGE_TYPE_* values,
        one or two): the library's rule (duoforge_data_request_target_class), which differs from target_type for a Curse
        of a user without the Ghost type ("self"). ValueError for a user without a type or with more than two, and for
        a target class that has no Showdown target type."""
        from duoforge import data as api
        types = tuple(types)
        if not 1 <= len(types) <= 2:
            raise ValueError(f"a user has one or two types, not {len(types)}")
        target_class = api.request_target_class(self._context(), move_id, types + (api.NONE,) * (2 - len(types)))
        if target_class not in TARGET_TYPES:
            raise ValueError(f"move {move_id}: target class {target_class} has no Showdown target type")
        return TARGET_TYPES[target_class]

    def forme_types(self, forme):
        """The types of a forme row (a Mega forme's own), one or two DUOFORGE_TYPE_* values."""
        from duoforge import data as api
        types = api.forme_static(self._context(), forme)["types"]
        return tuple(t for t in types if t != api.NONE)

    def ability_of(self, forme):
        """The forme's ability as a member holds it (the set's; a Mega forme's own), 1-based like parse_team."""
        return self._ability[forme] + 1

    def base_forme(self, forme):
        return self._base[forme]

    def mega_forme(self, forme):
        """The forme's Mega forme (its first, when stones take it to several), or None."""
        return self._mega[forme]

    def mega_of(self, forme, item):
        """The Mega forme that `item` (1-based, 0 for none) takes the forme to, or None, from the library's
        (holder, stone) pairs: Charizardite X and Y take Charizard to two formes, and Meowsticite takes Meowstic-M
        and Meowstic-F to two."""
        if item == 0:
            return None
        return self._mega_pairs.get((forme, item - 1))

    def mega_capable(self, forme, item):
        """Whether `item` (1-based, 0 for none) is a Mega Stone of the forme."""
        return self.mega_of(forme, item) is not None


def load(root=ROOT, kind="closure"):
    return Data(root, kind)


def for_config(config, root=ROOT):
    """The tables of a checkpoint's config: its data kind (policy.table_kind: "closure" for a format-1 file, which names
    none), always the current library's context of that kind. The live tracker reads the battle with them, and its
    public record is of that context. A format-2 file must read these rows as it was trained (checkpoint.check_data):
    the same fingerprint, or another one whose embedded ids carry over (checkpoint.check_ids; the tables only grew at
    the end); the result is the tables' checkpoint_check. A format-2 config without its data, a kind without live
    tables (team_c) or another fingerprint whose ids do not carry over raises ValueError before a game starts, never
    another kind."""
    from .policy import table_kind
    if not isinstance(config, dict):
        raise ValueError("the checkpoint names no data kind and fingerprint (no config)")
    form = config.get("format", 1)  # a format-1 config is free and names no format (decision 0014, train.save)
    if form == 1:
        return Data(root, table_kind(config))  # a format-1 network: the closure tables, no fingerprint to check
    if form != 2:
        raise ValueError(f"the checkpoint's config format {form!r} is not 1 or 2: its tables are unknown")
    entry = config.get("data")
    if not isinstance(entry, dict) or "kind" not in entry or "fingerprint" not in entry:
        raise ValueError("the checkpoint names no data kind and fingerprint (config['data']): its tables are unknown")
    try:
        kind = table_kind(config)
    except ValueError as err:
        raise ValueError(f"the checkpoint's data kind {entry['kind']!r} has no live tables ({err})") from None
    from duoforge_learn import checkpoint
    tables = Data(root, kind)  # the current library's tables: the game is played with today's engine
    try:
        tables.checkpoint_check = checkpoint.check_data(config, tables.context())
    except ValueError as err:
        raise ValueError(f"the {kind} tables: {err}") from None
    return tables


def for_checkpoint(path, root=ROOT):
    """for_config of the checkpoint file at `path`."""
    from duoforge_learn import checkpoint
    return for_config(checkpoint.load(path)[1], root)
