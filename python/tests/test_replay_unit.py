"""duoforge.python.replay_unit: the M11 replay pipeline without Node (spec
docs/superpowers/specs/2026-10-02-m11-replay-data-design.md section 14).

Everything here runs on our own data: the generated tables, the reference
teams and a committed spectator log of one reference battle
(python/tests/data/replay/). No replay of the unlicensed dataset is a test
input.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from duoforge_live import data, lines
from duoforge_live.data import trace_to_c

_PAUSE = {}


def setUpModule():
    # The builds here honour the fuzz pause file. The machine's own one ($TEMP/duoforge-fuzz.pause) exists while a
    # measurement runs, and would hold every build of this module until it ends (a ctest timeout): the module gets a
    # pause file of its own, absent, as tools/reference/test_diff_random.py does.
    import os
    _PAUSE["dir"] = tempfile.TemporaryDirectory()
    _PAUSE["saved"] = os.environ.get("DUOFORGE_FUZZ_PAUSE")
    os.environ["DUOFORGE_FUZZ_PAUSE"] = os.path.join(_PAUSE["dir"].name, "duoforge-fuzz.pause")


def tearDownModule():
    import os
    if _PAUSE["saved"] is None:
        os.environ.pop("DUOFORGE_FUZZ_PAUSE", None)
    else:
        os.environ["DUOFORGE_FUZZ_PAUSE"] = _PAUSE["saved"]
    _PAUSE["dir"].cleanup()


def _define(header, name):
    return int(re.search(rf"#define {name} (\d+)u", header).group(1))


# The generated rows as duoforge_live.data read them before decision 0020 (src/data/*_tables.c): the reference of
# GeneratedRowsTest, which shows the library's data API answering the same for every row of both kinds.
_ROW_KINDS = {"closure": ("closure_tables.h", "closure_tables.c", "DFI_", "dfi_closure_formes[DFI_FORME_COUNT] = {",
                          "dfi_closure_moves[DFI_MOVE_COUNT] = {", "dfi_closure_items[DFI_ITEM_COUNT] = {"),
              "pool": ("pool_tables.h", "pool_tables.c", "DFI_POOL_", "dfi_pool_formes[DFI_POOL_FORME_COUNT] = {",
                       "dfi_pool_moves[DFI_POOL_MOVE_COUNT] = {", "dfi_pool_items[DFI_POOL_ITEM_COUNT] = {")}
# dfi_forme_data: dex_num, weight_hg, types[2], base[6], ability, gender_rule, is_mega, base_forme, mega_forme, ...
_FORME_ROW = re.compile(r"\{\d+u, \d+u, \{\w+, \w+\}, \{[^}]*\}, (\w+), \w+, \w+, (\w+), (\w+), \w+,")
# dfi_move_data: type, category, base_power, accuracy, pp_base, pp_max, priority, target_class, ...
_MOVE_ROW = re.compile(r"^    \{\d+u, \d+u, \d+u, \d+u, \d+u, (\d+)u, \d+u, (\d+)u,", re.M)
# dfi_item_data: the forme that holds it as a Mega Stone, the Mega forme it reaches
_ITEM_ROW = re.compile(r"^    \{(\w+), (\w+)\},", re.M)


def _generated_rows(kind):
    """(formes [(ability, base, mega)], moves [(pp_max, target class)], items [(holder, mega)]) of a kind's generated
    rows; None for a NONE symbol or the closure's 0xFF."""
    header_file, file, prefix, *starts = _ROW_KINDS[kind]
    header = (data.ROOT / "src" / "data" / header_file).read_text(encoding="ascii")
    source = (data.ROOT / "src" / "data" / file).read_text(encoding="ascii")

    def value(token):
        if token in ("DFI_CLOSURE_NONE", "DFI_FORME_NONE") or (kind == "closure" and token == "255u"):
            return None
        return int(token[:-1])

    out = []
    for table, start, row in zip(("FORME", "MOVE", "ITEM"), starts, (_FORME_ROW, _MOVE_ROW, _ITEM_ROW)):
        a = source.index(start)
        rows = row.findall(source[a:source.index("};", a)])
        assert len(rows) == _define(header, f"{prefix}{table}_COUNT"), (kind, table)
        out.append([tuple(value(x) if not x.isdigit() else int(x) for x in r) for r in rows])
    return out


class GeneratedRowsTest(unittest.TestCase):
    """The data the fold reads (decision 0020): what the generated rows hold, row by row, for both kinds."""

    def test_the_data_equals_the_generated_rows(self):
        for kind in ("closure", "pool"):
            d = data.load(kind=kind)
            formes, moves, items = _generated_rows(kind)
            self.assertEqual((d.counts["FORME"], d.counts["MOVE"], d.counts["ITEM"]), (len(formes), len(moves), len(items)))
            for forme, (ability, base, mega) in enumerate(formes):
                where = (kind, "forme", forme)
                self.assertEqual(d.ability_of(forme), ability + 1, where)
                self.assertEqual(d.base_forme(forme), base, where)
                self.assertEqual(d.mega_forme(forme), mega, where)
            for move, (pp_max, target_class) in enumerate(moves):
                self.assertEqual(d.pp_max(move), pp_max, (kind, "move", move))
                self.assertEqual(d.target_type(move), data.TARGET_TYPES[target_class], (kind, "move", move))
            for item, (holder, mega) in enumerate(items):
                where = (kind, "item", item)
                if holder is not None and mega is not None:  # the item row names the stone's first pair
                    self.assertEqual(d.mega_of(holder, item + 1), mega, where)
                for forme in range(len(formes)):
                    got = d.mega_of(forme, item + 1)
                    if mega is None:
                        self.assertIsNone(got, where + (forme,))  # no stone, no Mega
                    elif got is not None:  # another holder of the same stone (Meowsticite): its own Mega
                        self.assertEqual(formes[got][1], forme, where + (forme,))
                self.assertIsNone(d.mega_of(0, 0))


    def test_a_checkout_the_library_does_not_match_is_refused(self):
        # the ids are the converter's (the checkout's headers), the rows the library's: a DLL of other tables is an
        # explicit error, never rows of the wrong ids
        from unittest import mock
        real = trace_to_c.load_tables

        def swapped(root, pool):
            tables = real(root, pool)
            tables["MOVE"]["PROTECT"], tables["MOVE"]["TAILWIND"] = tables["MOVE"]["TAILWIND"], tables["MOVE"]["PROTECT"]
            return tables

        with mock.patch.object(trace_to_c, "load_tables", swapped):
            with self.assertRaisesRegex(ValueError, "the library's MOVE names differ from the converter's tables"):
                data.load(kind="pool")


class DataTest(unittest.TestCase):
    """The POOL tables of the fold (Task 2)."""

    @classmethod
    def setUpClass(cls):
        cls.pool = data.load(kind="pool")
        cls.closure = data.load()
        cls.header = (data.ROOT / "src" / "data" / "pool_tables.h").read_text(encoding="ascii")

    def test_pool_counts(self):
        self.assertEqual(self.pool.counts["FORME"], _define(self.header, "DFI_POOL_FORME_COUNT"))
        self.assertEqual(self.pool.counts["ITEM"], _define(self.header, "DFI_POOL_ITEM_COUNT"))
        self.assertEqual(len(self.pool._pp_max), _define(self.header, "DFI_POOL_MOVE_COUNT"))
        self.assertEqual(len(self.pool._target_class), _define(self.header, "DFI_POOL_MOVE_COUNT"))

    def test_target_types(self):
        moves = self.pool.tables["MOVE"]
        self.assertEqual(self.pool.target_type(moves["TAILWIND"]), "allySide")
        self.assertEqual(self.pool.target_type(moves["PROTECT"]), "self")
        self.assertEqual(self.closure.target_type(moves["PROTECT"]), "self")

    def test_each_stone_reaches_its_own_mega(self):
        # G23 (#162): Charizardite X and Y take Charizard to two formes, Garchompite and Garchompite Z Garchomp
        f, i, a = self.pool.tables["FORME"], self.pool.tables["ITEM"], self.pool.tables["ABILITY"]
        for base, stone, mega in (("CHARIZARD", "CHARIZARDITEX", "CHARIZARDMEGAX"),
                                  ("CHARIZARD", "CHARIZARDITEY", "CHARIZARDMEGAY"),
                                  ("GARCHOMP", "GARCHOMPITE", "GARCHOMPMEGA"),
                                  ("GARCHOMP", "GARCHOMPITEZ", "GARCHOMPMEGAZ"),
                                  # one stone, two holders: Meowsticite takes each Meowstic to its own Mega
                                  ("MEOWSTIC", "MEOWSTICITE", "MEOWSTICMMEGA"),
                                  ("MEOWSTICF", "MEOWSTICITE", "MEOWSTICFMEGA")):
            self.assertEqual(self.pool.mega_of(f[base], i[stone] + 1), f[mega], stone)
            self.assertEqual(self.pool.base_forme(f[mega]), f[base], mega)
            self.assertIsNone(self.pool.mega_of(f["SALAMENCE"], i[stone] + 1), stone)  # another forme's stone
        self.assertEqual(self.pool.ability_of(f["CHARIZARDMEGAX"]), a["TOUGHCLAWS"] + 1)
        self.assertEqual(self.pool.ability_of(f["CHARIZARDMEGAY"]), a["DROUGHT"] + 1)
        self.assertEqual(self.pool.forme("Charizard-Mega-X"), f["CHARIZARDMEGAX"])
        self.assertEqual(self.pool.forme("Garchomp-Mega-Z"), f["GARCHOMPMEGAZ"])

    def test_protect_pp(self):
        self.assertEqual(self.pool.pp_max(self.pool.tables["MOVE"]["PROTECT"]), 8)

    def test_closure_prefix_kept(self):
        for forme in range(self.closure.counts["FORME"]):
            self.assertEqual(self.pool.base_forme(forme), self.closure.base_forme(forme))
            self.assertEqual(self.pool.mega_forme(forme), self.closure.mega_forme(forme))
            self.assertEqual(self.pool.ability_of(forme), self.closure.ability_of(forme))
        for move in range(self.closure.counts["MOVE"]):
            self.assertEqual(self.pool.pp_max(move), self.closure.pp_max(move))
            self.assertEqual(self.pool.target_type(move), self.closure.target_type(move))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            data.load(kind="x")

    def test_unknown_target_class(self):
        pool = data.load(kind="pool")
        pool._target_class = [99]
        with self.assertRaisesRegex(ValueError, "target class 99 has no Showdown target type"):
            pool.target_type(0)


class AliasTest(unittest.TestCase):
    """The cosmetic aliases of the POOL tables (#118) through the library's find (BC spec section 5)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import prior
        cls.pool = data.load(kind="pool")
        cls.prior = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})
        cls.log = FIXTURE.read_text(encoding="utf-8").splitlines()

    def run_game(self, lines_):
        from duoforge_replay import game
        return game.process("fixture-alias", "gen9championsvgc2026regmcbo3", chr(10).join(lines_), self.pool,
                            self.prior, _Stats())

    def with_species(self, species):
        """The committed log with p2's Politoed (nickname kept) shown as `species`, genderless (Sinistcha), on its
        sheet and in its details."""
        out = []
        for line in self.log:
            if line.startswith("|showteam|p2|"):
                line = line.replace("|showteam|p2|Politoed||", f"|showteam|p2|Politoed|{species}|")
                line = line.replace("Protect|Modest||M|||50|]Farigiraf", "Protect|Modest|||||50|]Farigiraf")
            elif line.startswith(("|poke|p2|Politoed,", "|switch|p2a: Politoed|", "|switch|p2b: Politoed|")):
                line = line.replace("|Politoed, L50, M", f"|{species}, L50")
            out.append(line)
        return out

    def test_alias_resolves_to_its_base(self):
        self.assertEqual(self.pool.forme("Vivillon-Pokeball"), self.pool.forme("Vivillon"))
        self.assertEqual(self.pool.forme("Sinistcha-Masterpiece"), self.pool.forme("Sinistcha"))
        self.assertEqual(self.pool.forme(self.pool.canonical("Vivillon-Pokeball")), self.pool.forme("Vivillon"))
        with self.assertRaises(ValueError):
            self.pool.forme("Vivillon-Nonsense")

    def test_unknown_alias_stays_a_name_skip(self):
        from duoforge_replay import game
        with self.assertRaises(game.Skip) as caught:
            self.run_game(self.with_species("Vivillon-Nonsense"))
        self.assertEqual(caught.exception.reason, "name:FORME Vivillon-Nonsense")

    def test_alias_game_runs(self):
        # the fixture keeps Politoed's set (Drizzle, its moves) under Sinistcha's name, which POOL setup would refuse;
        # legality is not this test's subject (test_pool_illegal_skip is), so the check passes here
        from unittest import mock
        with mock.patch.object(type(self.pool), "setup_issue", return_value=None):
            result = self.run_game(self.with_species("Sinistcha-Masterpiece"))
        self.assertFalse([k for k in result.counters if "name:" in k or k.startswith("internal:")], result.counters)
        self.assertGreater(result.counters["points.written"], 4)
        # the alias in the |switch| details folds as its base forme: no stop the plain log does not have
        stops = lambda c: {k: v for k, v in c.items() if k.startswith("perspectives.stopped.")}
        with mock.patch.object(type(self.pool), "setup_issue", return_value=None):
            plain = self.run_game(self.log)
        self.assertEqual(stops(result.counters), stops(plain.counters))
        sinistcha = self.pool.forme("Sinistcha")
        species = {int(m["species_id"]) for r in result.rows for m in r.observation["sides"][1]["members"]}
        self.assertIn(sinistcha, species)


class _View:
    """What lines.check reads of a tracker: the data and, per protocol ident, the sheet and current ability."""

    def __init__(self, members):
        self.data = data.load(kind="pool")
        t = self.data.tables
        self._members = {}
        for ident, (species, item, ability) in members.items():
            self._members[ident] = {"species": t["FORME"][species], "item": t["ITEM"][item] + 1 if item else 0,
                                    "ability": t["ABILITY"][ability] + 1}

    def sheet_of(self, ident):
        return self._members[ident.split(": ")[0][:2] + ": " + ident.split(": ")[1]]

    def known_sheet(self, ident):
        return self._members.get(ident.split(": ")[0][:2] + ": " + ident.split(": ")[1])

    def ability_now(self, ident):
        return self.sheet_of(ident)["ability"]


class LinesTest(unittest.TestCase):
    """The line classes of the shared fold (Task 3, spec section 5)."""

    @classmethod
    def setUpClass(cls):
        cls.view = _View({"p1: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE"),
                          "p2: Gholdengo": ("GHOLDENGO", "LIFEORB", "GOODASGOLD")})

    def stop(self, line):
        with self.assertRaises(lines.Stop) as caught:
            lines.check(line, self.view)
        return caught.exception.reason

    def test_feature_lines_stop(self):
        self.assertEqual(self.stop("|-fieldstart|move: Electric Terrain|[from] ability: Electric Surge|[of] p2a: Gholdengo"),
                         "feature:TERRAIN_ELECTRIC")
        self.assertEqual(self.stop("|-ability|p2a: Gholdengo|Intimidate|[from] ability: Trace|[of] p1a: Staraptor"),
                         "feature:ABILITY_CHANGE")
        self.assertEqual(self.stop("|-enditem|p1a: Staraptor|Sitrus Berry|[from] move: Knock Off|[of] p2a: Gholdengo"),
                         "feature:ITEM_CHANGE")
        self.assertEqual(self.stop("|-start|p1a: Staraptor|Encore"), "feature:ENCORE")
        self.assertEqual(lines.check("|-status|p1a: Staraptor|tox", self.view), "fold")  # Tox folds (BC spec 5)
        self.assertEqual(self.stop("|replace|p1a: Zoroark|Zoroark-Hisui, L50, M"), "feature:ILLUSION")

    def test_item_transfer_lines_are_item_change(self):
        # G29 (#171): every line of a Trick, Switcheroo, Thief or Covet is decision 0018's ITEM_CHANGE, the
        # -activate of Trick too (it names the target; Switcheroo prints none)
        for line in ("|-activate|p1a: Staraptor|move: Trick|[of] p2a: Gholdengo",
                     "|-item|p1a: Staraptor|Choice Scarf|[from] move: Trick",
                     "|-enditem|p1a: Staraptor|Sitrus Berry|[silent]|[from] move: Switcheroo",
                     "|-item|p1a: Staraptor|Life Orb|[from] move: Thief|[of] p2a: Gholdengo",
                     "|-enditem|p2a: Gholdengo|Life Orb|[silent]|[from] move: Thief|[of] p1a: Staraptor",
                     "|-item|p1a: Staraptor|Life Orb|[from] move: Covet|[of] p2a: Gholdengo"):
            self.assertEqual(self.stop(line), "feature:ITEM_CHANGE", line)

    def test_drag_folds(self):
        # Step G46: a forced switch brings a member in as a switch does (the tracker folds it as one, or stops)
        self.assertEqual(lines.check("|drag|p2a: Gholdengo|Gholdengo, L50|100/100", self.view), "fold")
        self.assertEqual(lines.check("|drag|p1a: Staraptor|Staraptor, L50, F|100/100", self.view), "fold")

    def test_unknown_lines_stop(self):
        self.assertEqual(self.stop("|-sethp|p1a: Staraptor|50/100"), "line:-sethp")
        self.assertEqual(self.stop("|move|p1a: Staraptor|Baton Pass|p1a: Staraptor"), "line:move Baton Pass")
        self.assertEqual(self.stop("|-activate|p1a: Staraptor|move: Court Change"), "line:-activate move: Court Change")
        self.assertEqual(self.stop("|-ability|p1a: Staraptor|Pressure"), "line:-ability Pressure")

    def test_a_drop_kept_by_the_holders_ability_is_kept(self):
        # the seven forms of Reg M-C replays: an Intimidate (or another drop) that the holder's own ability stops
        view = _View({"p1: Dragonite": ("DRAGONITE", None, "INNERFOCUS"), "p1: Metagross": ("METAGROSS", None, "CLEARBODY"),
                      "p2: Kangaskhan": ("KANGASKHAN", None, "SCRAPPY"), "p2: Mamoswine": ("MAMOSWINE", None, "OBLIVIOUS"),
                      "p2: Gliscor": ("GLISCOR", None, "HYPERCUTTER"), "p2: Slowbro": ("SLOWBRO", None, "OWNTEMPO"),
                      "p2: Torkoal": ("TORKOAL", None, "WHITESMOKE")})
        for ident, ability, stat in (("p1a: Dragonite", "Inner Focus", "atk|"), ("p1b: Metagross", "Clear Body", ""),
                                     ("p2a: Kangaskhan", "Scrappy", "atk|"), ("p2b: Mamoswine", "Oblivious", "atk|"),
                                     ("p2a: Gliscor", "Hyper Cutter", "atk|"), ("p2b: Slowbro", "Own Tempo", "atk|"),
                                     ("p2a: Torkoal", "White Smoke", "")):
            line = f"|-fail|{ident}|unboost|{stat}[from] ability: {ability}|[of] {ident}"
            self.assertEqual(lines.check(line, view), "keep", line)
        for line in ("|-fail|p1a: Dragonite|unboost|atk|[from] ability: Clear Body|[of] p1a: Dragonite",  # not its own
                     "|-fail|p1a: Dragonite|unboost|atk|[from] ability: Inner Focus|[of] p1b: Metagross",  # another holder
                     "|-fail|p1a: Dragonite|unboost|atk|[from] ability: Inner Focus",  # no holder
                     "|-fail|p1a: Dragonite|unboost|power|[from] ability: Inner Focus|[of] p1a: Dragonite",  # no stat
                     "|-fail|p1a: Dragonite|unboost|atk|[from] item: Clear Amulet|[of] p1a: Dragonite"):  # an item
            with self.assertRaises(lines.Stop, msg=line) as caught:
                lines.check(line, view)
            self.assertEqual(caught.exception.reason, "line:-fail unboost")

    def test_a_mega_folds_only_for_its_own_stone(self):
        # G23: Garchompite Z reaches Garchomp-Mega-Z, Garchompite Garchomp-Mega
        line_z = "|detailschange|p1a: Garchomp|Garchomp-Mega-Z, L50, M"
        z = _View({"p1: Garchomp": ("GARCHOMP", "GARCHOMPITEZ", "ROUGHSKIN")})
        plain = _View({"p1: Garchomp": ("GARCHOMP", "GARCHOMPITE", "ROUGHSKIN")})
        self.assertEqual(lines.check(line_z, z), "fold")
        self.assertEqual(lines.check("|detailschange|p1a: Garchomp|Garchomp-Mega, L50, M", plain), "fold")
        with self.assertRaises(lines.Stop) as caught:
            lines.check(line_z, plain)
        self.assertEqual(caught.exception.reason, "feature:FORME_CHANGE")

    def test_full_stat_name_is_kept(self):
        # Reg M-B replays come from an older server that writes the stat's full name ("Attack", not "atk")
        view = _View({"p1: Dragonite": ("DRAGONITE", None, "INNERFOCUS")})
        self.assertEqual(lines.check("|-fail|p1a: Dragonite|unboost|Attack|[from] ability: Inner Focus|[of] p1a: Dragonite",
                                     view), "keep")
        with self.assertRaises(lines.Stop):
            lines.check("|-fail|p1a: Dragonite|unboost|Power|[from] ability: Inner Focus|[of] p1a: Dragonite", view)

    def test_roost_single_turn_is_its_feature(self):
        # G42: -singleturn|X|move: Roost is the ROOST feature: folded once the library supports it, else a Stop
        line = "|-singleturn|p1a: Staraptor|move: Roost"
        if lines.SUPPORTED >> lines.FEATURES["ROOST"] & 1:
            self.assertEqual(lines.check(line, self.view), "fold")
        else:
            self.assertEqual(self.stop(line), "feature:ROOST")

    def test_activate_of_own_ability_folds(self):
        # G45/G47: Synchronize, Telepathy and the like announce the holder's own ability; their effects come in
        # their own lines (-status, the skipped hit), so the -activate line itself changes no field
        view = _View({"p1: Umbreon": ("UMBREON", "LEFTOVERS", "SYNCHRONIZE"),
                      "p2: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE")})
        self.assertEqual(lines.check("|-activate|p1a: Umbreon|ability: Synchronize", view), "fold")
        with self.assertRaises(lines.Stop):  # not the holder's current ability: unknown, as before
            lines.check("|-activate|p2a: Staraptor|ability: Synchronize", view)
        with self.assertRaises(lines.Stop):  # an ability the tables lack
            lines.check("|-activate|p1a: Umbreon|ability: No Such Ability", view)

    def test_fold_and_room_lines(self):
        self.assertEqual(lines.check("|-enditem|p1a: Staraptor|Sitrus Berry|[eat]", self.view), "fold")
        self.assertEqual(lines.check("|-ability|p1a: Staraptor|Intimidate|boost", self.view), "fold")
        self.assertEqual(lines.check("|-damage|p2a: Gholdengo|50/100|[from] item: Life Orb", self.view), "fold")
        self.assertEqual(lines.check("|-item|p1a: Staraptor|Sitrus Berry", self.view), "fold")  # own item announced
        self.assertEqual(self.stop("|-item|p1a: Staraptor|Life Orb"), "line:-item Life Orb")
        self.assertIsNone(lines.check("|j|☆x", self.view))
        self.assertIsNone(lines.check("|c|☆x|hi|there", self.view))

    def test_turn_scoped(self):
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|move: Rage Powder", self.view), "turn:RAGE_POWDER")
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Wide Guard", self.view), "turn:WIDE_GUARD")

    def test_the_protect_variants_single_turn_line_folds(self):
        # Spiky Shield, Baneful Bunker and Burning Bulwark print `move: Protect` (Protect and Detect print `Protect`).
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|move: Protect", self.view), "fold")
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Protect", self.view), "fold")
        self.assertEqual(self.stop("|-singleturn|p1a: Staraptor|move: Court Change"), "line:-singleturn move: Court Change")

    def test_spiky_shield_damage_folds_with_a_known_source(self):
        # `-damage|attacker|hp|[from] Spiky Shield|[of] holder`: the generic damage fold applies the HP; the converter's
        # ev_cause knows the source (the cause MOVE with the move in id2 and the holder in other).
        line = "|-damage|p2a: Gholdengo|87/100|[from] Spiky Shield|[of] p1a: Staraptor"
        self.assertEqual(lines.check(line, self.view), "fold")
        tables = self.view.data.tables
        cause, id2, other = lines.trace_to_c.ev_cause(["[from] Spiky Shield", "[of] p1a: Staraptor"], tables)
        self.assertEqual((cause, id2), (lines.trace_to_c.CAUSE["MOVE"], tables["MOVE"]["SPIKYSHIELD"]))
        self.assertNotEqual(other, lines.trace_to_c.NOPOS)

    def test_guard_blocks_are_turn_scoped(self):
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Wide Guard", self.view), "turn:WIDE_GUARD")
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Quick Guard", self.view), "turn:QUICK_GUARD")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|ability: Storm Drain", self.view), "fold")

    def test_features_from_the_header(self):
        self.assertEqual(lines.FEATURES["WEATHER_SAND"], 0)
        self.assertEqual(lines.FEATURES["RAGE_POWDER"], 39)
        self.assertEqual(lines.FEATURES["MOVE_FAILED"], 41)
        self.assertEqual(lines.FEATURES["TRANSFORM"], 42)
        self.assertEqual(len(lines.FEATURES), 43)  # tail revision 4: ROOST 40, MOVE_FAILED 41; 0028: TRANSFORM 42

    def test_supported_mask_forms(self):
        f = lines.FEATURES
        self.assertEqual(lines.parse_supported("0u"), 0)
        self.assertEqual(lines.parse_supported("(1ull << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW)"), 1 << f["WEATHER_SNOW"])
        self.assertEqual(lines.parse_supported("((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) | "
                                               "((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK)"),
                         1 << f["THROAT_CHOP"] | 1 << f["HEAL_BLOCK"])
        with self.assertRaisesRegex(ValueError, "not understood"):
            lines.parse_supported("SOMETHING_ELSE")
        self.assertEqual(lines.LIBRARY_SUPPORTED, lines.supported())
        # the manifest writes a long mask over several lines
        source = ("static const dfi_support dfi_support = {\n    .turn_core = 1u,\n"
                  "    .view_ext_features = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |\n"
                  "                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD),\n};\n")
        self.assertEqual(lines.extract_supported(source), 1 << f["THROAT_CHOP"] | 1 << f["WIDE_GUARD"])

    def test_a_feature_the_tracker_does_not_fold_stops(self):
        # the library may support a feature (G8: Throat Chop), but rows carry no view extension until the tracker
        # folds it: the line still stops the perspective
        self.assertEqual(lines.SUPPORTED & ~lines.TRACKER_FOLDS, 0)
        self.assertEqual(self.stop("|-start|p1a: Staraptor|Throat Chop|[silent]"), "feature:THROAT_CHOP")
        # the base-value features fold (BC spec section 5): Sand and Snow, which the library supports (#124), and Tox
        f = lines.FEATURES
        self.assertTrue(lines.LIBRARY_SUPPORTED >> f["WEATHER_SAND"] & 1 and lines.LIBRARY_SUPPORTED >> f["WEATHER_SNOW"] & 1)
        self.assertEqual(lines.check("|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Gholdengo", self.view), "fold")
        self.assertEqual(lines.check("|-weather|Snowscape|[from] ability: Snow Warning|[of] p2a: Gholdengo", self.view),
                         "fold")

    def test_choice_items(self):
        self.assertEqual(lines.CHOICE_ITEMS, ("choiceband", "choicescarf", "choicespecs"))


TEAMS = data.ROOT / "tests" / "reference" / "teams"


class PointsTest(unittest.TestCase):
    """The decision points of a log (points.find)."""

    _HEAD = ["|showteam|p1|x", "|showteam|p2|y", "|start", "|switch|p1a: Dragalge|Dragalge, L50|100/100",
             "|switch|p2a: Gholdengo|Gholdengo, L50|100/100", "|turn|1"]

    def test_a_switch_out_effect_of_the_answer_is_not_in_the_point(self):
        # G51 (#281): Regenerator heals at the switch-out, a line of the PIVOT's answer printed before its |switch|;
        # the player was asked before it (the engine shows the HP before the heal at the request)
        from duoforge_replay import points
        log = self._HEAD + ["|move|p1a: Dragalge|Flip Turn|p2a: Gholdengo", "|-damage|p2a: Gholdengo|80/100",
                            "|-heal|p1a: Dragalge|53/100|[from] ability: Regenerator|[silent]",
                            "|switch|p1a: Staraptor|Staraptor, L50|100/100|[from] Flip Turn", "|upkeep"]
        pivot = [pt for pt in points.find(log) if pt.boundary == points.PIVOT]
        self.assertEqual(len(pivot), 1)
        self.assertEqual(log[pivot[0].line], "|-heal|p1a: Dragalge|53/100|[from] ability: Regenerator|[silent]")
        # Natural Cure cures at the switch-out the same way
        cure = self._HEAD + ["|move|p1a: Dragalge|U-turn|p2a: Gholdengo", "|-damage|p2a: Gholdengo|80/100",
                             "|-curestatus|p1a: Dragalge|slp|[from] ability: Natural Cure",
                             "|switch|p1a: Staraptor|Staraptor, L50|100/100|[from] U-turn", "|upkeep"]
        pivot = [pt for pt in points.find(cure) if pt.boundary == points.PIVOT]
        self.assertEqual(cure[pivot[0].line], "|-curestatus|p1a: Dragalge|slp|[from] ability: Natural Cure")
        # a heal of another position, or one without a switch-out ability, stays in the point
        other = self._HEAD + ["|move|p1a: Dragalge|Flip Turn|p2a: Gholdengo",
                              "|-heal|p2a: Gholdengo|90/100|[from] item: Leftovers",
                              "|switch|p1a: Staraptor|Staraptor, L50|100/100|[from] Flip Turn", "|upkeep"]
        pivot = [pt for pt in points.find(other) if pt.boundary == points.PIVOT]
        self.assertTrue(other[pivot[0].line].startswith("|switch|"))


class PriorTest(unittest.TestCase):
    """The stat point prior (Task 4, spec section 10), on pastes of our reference teams."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import prior
        cls.prior_module = prior
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_prior_"))
        team_a = (TEAMS / "team_a.txt").read_text(encoding="utf-8")
        shutil.copy(TEAMS / "team_a.txt", cls.tmp / "a.txt")
        shutil.copy(TEAMS / "team_b.txt", cls.tmp / "b.txt")
        # Team A again, its Rillaboom with another spread: a tie of two spreads, the smaller tuple wins
        other = team_a.replace("EVs: 18 HP / 32 Atk / 2 Def / 6 SpD / 8 Spe", "EVs: 32 HP / 32 Atk / 2 Spe", 1)
        assert other != team_a
        head = "Nick (Rillaboom) (M) @ Miracle Seed  " + chr(10) + "Shiny: Yes" + chr(10)
        (cls.tmp / "c.txt").write_text(head + other.split(chr(10), 1)[1], encoding="utf-8")
        cls.prior = prior.Prior(prior.build(cls.tmp))
        cls.rillaboom = {"species": "Rillaboom", "item": "MiracleSeed", "ability": "GrassySurge", "nature": "Adamant",
                         "moves": ["WoodHammer", "GrassyGlide", "FakeOut", "HighHorsepower"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def lookup(self, **change):
        return self.prior.lookup({**self.rillaboom, **change})

    def test_levels(self):
        self.assertEqual(self.lookup(), ([18, 32, 2, 0, 6, 8], 0))  # tie of two: (18, ...) < (32, ...)
        self.assertEqual(self.lookup(moves=["WoodHammer", "Protect"])[1], 1)
        self.assertEqual(self.lookup(moves=["Protect"], item="Leftovers")[1], 2)
        self.assertEqual(self.lookup(moves=["Protect"], item="Leftovers", nature="Jolly")[1], 3)
        self.assertEqual(self.lookup(species="Pikachu"), ([0] * 6, 4))

    def test_move_order_does_not_matter(self):
        self.assertEqual(self.lookup(moves=list(reversed(self.rillaboom["moves"])))[1], 0)

    def test_pastes_counted(self):
        self.assertEqual(self.prior.data["pastes"], 3)

    def test_evs_are_refused(self):
        with self.assertRaisesRegex(ValueError, "EVs, not stat points"):
            self.prior_module.parse_paste("Rillaboom @ Miracle Seed\nAbility: Grassy Surge\nEVs: 252 Atk\n"
                                          "Adamant Nature\n- Fake Out")

    def test_unknown_line_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown paste line"):
            self.prior_module.parse_paste("Rillaboom @ Miracle Seed\nWeird: line\n- Fake Out")



class LabelsTest(unittest.TestCase):
    """Label sets (Task 7, spec section 9) on hand-made turn segments of side 0 (p1)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import options
        from duoforge_replay import labels, points
        cls.L, cls.P, cls.O = labels, points, options
        cls.tables = data.load(kind="pool").tables
        mv = cls.tables["MOVE"]
        # slot 0: Staraptor with Brave Bird (normal), Close Combat (normal), Tailwind (allySide), Protect (self);
        # Mega possible; reserves 2 and 3. Slot 1: Gholdengo with one move (Make It Rain, allAdjacentFoes).
        cls.moves = ([mv["BRAVEBIRD"], mv["CLOSECOMBAT"], mv["TAILWIND"], mv["PROTECT"]], [mv["MAKEITRAIN"]])
        request = {"side": {"id": "p1", "pokemon": [
            {"ident": "p1: a", "active": True, "condition": "100/100", "moves": ["bravebird", "closecombat", "tailwind", "protect"]},
            {"ident": "p1: b", "active": True, "condition": "100/100", "moves": ["makeitrain"]},
            {"ident": "p1: c", "active": False, "condition": "100/100", "moves": []},
            {"ident": "p1: d", "active": False, "condition": "100/100", "moves": []}]},
            "active": [{"moves": [{"id": "bravebird", "pp": 8, "target": "any", "disabled": False},
                                  {"id": "closecombat", "pp": 8, "target": "normal", "disabled": False},
                                  {"id": "tailwind", "pp": 8, "target": "allySide", "disabled": False},
                                  {"id": "protect", "pp": 8, "target": "self", "disabled": False}], "canMegaEvo": True},
                       {"moves": [{"id": "makeitrain", "pp": 8, "target": "allAdjacentFoes", "disabled": False}]}]}
        cls.lists = options.slot_options(request, 0, {"p1: a": 1, "p1: b": 0, "p1: c": 2, "p1: d": 3}, {})
        cls.point = points.Point(1, 0, points.TURN, (), 0)
        cls.species = {"Staraptor": 1, "Gholdengo": 0, "Rillaboom": 2, "Milotic": 3}

    def label(self, log, stop_line=None):
        point = self.P.Point(1, 0, self.P.TURN, (), len(log))
        return self.L.turn_label(log, point, 0, self.lists, self.moves,
                                 lambda details: self.species[details.split(",")[0]], self.tables,
                                 len(log) if stop_line is None else stop_line)

    def options_of(self, label, slot):
        return [self.lists[slot][i] for i in range(len(self.lists[slot])) if label.slots[slot] >> i & 1]

    def test_plain_move_exact(self):
        got = self.label(["|move|p1a: Staraptor|Close Combat|p2a: Foe", "|move|p1b: Gholdengo|Make It Rain|p2a: Foe|[spread] p2a,p2b"])
        self.assertEqual(got.reasons, (self.L.EXACT, self.L.EXACT))
        [o] = self.options_of(got, 0)
        self.assertEqual((o.kind, o.move_slot, o.target, o.mega), (self.O.MOVE, 1, 2, 0))

    def test_mega_shown(self):
        got = self.label(["|detailschange|p1a: Staraptor|Staraptor-Mega, L50, F", "|-mega|p1a: Staraptor|Staraptor|Staraptite",
                          "|move|p1a: Staraptor|Protect|p1a: Staraptor"])
        [o] = self.options_of(got, 0)
        self.assertEqual((o.move_slot, o.mega), (3, 1))

    def test_follow_me_makes_the_target_unknown(self):
        got = self.label(["|move|p2b: Foe2|Follow Me|p2b: Foe2", "|-singleturn|p2b: Foe2|move: Follow Me",
                          "|move|p1a: Staraptor|Close Combat|p2b: Foe2"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)
        self.assertEqual({o.target for o in self.options_of(got, 0)}, {1, 2, 3})
        self.assertEqual({(o.move_slot, o.mega) for o in self.options_of(got, 0)}, {(1, 0)})

    def test_faint_earlier_makes_the_target_unknown(self):
        got = self.label(["|move|p1b: Gholdengo|Make It Rain|p2a: Foe|[spread] p2a,p2b", "|faint|p2a: Foe",
                          "|move|p1a: Staraptor|Brave Bird|p2b: Foe2"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)

    def test_paralysis_hides_the_move(self):
        got = self.label(["|cant|p1a: Staraptor|par"])
        self.assertEqual(got.reasons[0], self.L.MOVE_HIDDEN)
        self.assertEqual({o.kind for o in self.options_of(got, 0)}, {self.O.MOVE})
        self.assertEqual({o.mega for o in self.options_of(got, 0)}, {0})
        self.assertEqual(len(self.options_of(got, 0)), 3 + 3 + 1 + 1)  # every move option without Mega

    def test_cant_naming_the_move(self):
        got = self.label(["|cant|p1a: Staraptor|move: Taunt|Tailwind"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)
        self.assertEqual([o.move_slot for o in self.options_of(got, 0)], [2])

    def test_locked_move_is_forced(self):
        got = self.label(["|move|p1a: Staraptor|Brave Bird|p2a: Foe|[from]lockedmove"])
        self.assertEqual(got.reasons[0], self.L.FORCED)
        self.assertEqual(got.slots[0], (1 << len(self.lists[0])) - 1)

    def test_switch_action_exact(self):
        got = self.label(["|switch|p1a: Rillaboom|Rillaboom, L50, M|100/100", "|move|p1b: Gholdengo|Make It Rain|p2a: Foe"])
        [o] = self.options_of(got, 0)
        self.assertEqual((o.kind, o.reserve), (self.O.SWITCH, 2))

    def test_stop_before_the_move_is_unknown(self):
        log = ["|move|p1b: Gholdengo|Make It Rain|p2a: Foe", "|-sethp|p2a: Foe|50/100", "|move|p1a: Staraptor|Protect|p1a: Staraptor"]
        got = self.label(log, stop_line=1)
        self.assertEqual(got.reasons, (self.L.UNKNOWN, self.L.EXACT))
        self.assertEqual(got.slots[0], (1 << len(self.lists[0])) - 1)

    def test_team_label(self):
        from duoforge_live.game import TEAM_TABLE
        one = self.L.team_label((1, 0), {3})
        none = self.L.team_label((1, 0), set())
        bits = lambda label: [i for i in range(len(TEAM_TABLE)) if label.team[i // 8] >> (i % 8) & 1]  # noqa: E731
        self.assertEqual(len(bits(one)), 6)
        self.assertEqual(len(bits(none)), 12)
        self.assertTrue(all(TEAM_TABLE[i][:2] == (1, 0) and 3 in TEAM_TABLE[i][2:] for i in bits(one)))
        self.assertEqual(len(one.team), 45)



FIXTURE = Path(__file__).resolve().parent / "data" / "replay" / "c12_real_cb_4.log"


class _Stats:
    """A stand-in for the Showdown stat source (the unit tests run without Node): fixed stats per forme."""

    def stats(self, species, nature, stat_points):
        return [100 + len(species), 90, 80, 70, 60, 50]


class GameTest(unittest.TestCase):
    """One game end to end (Task 8) on the committed spectator log of c12_real_cb_4 (a reference battle)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import game, prior
        cls.game = game
        cls.data = data.load(kind="pool")
        cls.prior = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})
        cls.log = FIXTURE.read_text(encoding="utf-8").splitlines()

    def run_game(self, lines):
        return self.game.process("fixture-1", "gen9championsvgc2026regmcbo3", "\n".join(lines), self.data,
                                 self.prior, _Stats())

    def skip_reason(self, lines):
        with self.assertRaises(self.game.Skip) as caught:
            self.run_game(lines)
        return caught.exception.reason

    def insert_after(self, prefix, new):
        i = next(i for i, line in enumerate(self.log) if line.startswith(prefix))
        return self.log[:i + 1] + [new] + self.log[i + 1:]

    def test_clean_game(self):
        result = self.run_game(self.log)
        self.assertEqual(result.counters["perspectives.kept"], 2)
        self.assertEqual(result.counters["points.written"], len(result.rows))
        for side in (0, 1):
            rows = [r for r in result.rows if r.side == side]
            self.assertGreater(len(rows), 10)
            epochs = [int(r.observation["epoch"]) for r in rows]
            self.assertEqual(epochs, sorted(set(epochs)))
            self.assertTrue(all(int(r.observation["player"]) == side for r in rows))
            self.assertTrue(all(r.prior_level == (4,) * 6 for r in rows))
        self.assertEqual(result.record.winner, 1)
        self.assertEqual(result.record.turns, 10)

    def test_a_feature_stops_after_turn_two(self):
        # a feature the tracker does not fold (Throat Chop; Sand folds since the BC PR) ends both perspectives there:
        # the points before it are written, the later ones dropped
        clean = self.run_game(self.log)
        result = self.run_game(self.insert_after("|turn|2", "|-start|p2a: Politoed|Throat Chop|[silent]"))
        self.assertEqual(result.counters["perspectives.stopped.feature:THROAT_CHOP"], 2)
        self.assertGreater(result.counters["points.dropped.feature:THROAT_CHOP"], 0)
        turn2 = [int(r.observation["epoch"]) for r in clean.rows if int(r.observation["turn"]) == 2
                 and r.observation["boundary_kind"] == 2]
        self.assertTrue(all(int(r.observation["epoch"]) <= max(turn2) for r in result.rows))
        self.assertLess(len(result.rows), len(clean.rows))

    def test_illusion_sheet_skips(self):
        lines = [line.replace("|Defiant|", "|Illusion|", 1) if line.startswith("|showteam|p1|") else line
                 for line in self.log]
        self.assertEqual(self.skip_reason(lines), "skip:illusion")

    def test_session_line_skips_game(self):
        self.assertEqual(self.skip_reason(self.insert_after("|turn|3", "|init|battle")), "skip:session")

    def test_unknown_name_skips_with_reason(self):
        lines = [line.replace("ChopleBerry", "BogusBerry", 1) if line.startswith("|showteam|p1|") else line
                 for line in self.log]
        self.assertEqual(self.skip_reason(lines), "name:ITEM BogusBerry")

    def test_no_win_line(self):
        result = self.run_game([line for line in self.log if not line.startswith("|win|")])
        self.assertEqual(result.record.winner, -1)
        self.assertGreater(len(result.rows), 20)

    def test_player_ratings(self):
        lines = [line.replace("|player|p1|p1||", "|player|p1|Alice|1|1350").replace("|player|p2|p2||",
                                                                                      "|player|p2|Bob|2|abc")
                 for line in self.log]
        lines = [line.replace("|win|p2", "|win|Bob") for line in lines]
        record = self.run_game(lines).record
        self.assertEqual(record.ratings, (1350, -1))
        self.assertEqual(record.winner, 1)
        self.assertNotEqual(record.players[0], record.players[1])

    def test_rage_powder_without_pivot_passes(self):
        result = self.run_game(self.insert_after("|turn|3", "|-singleturn|p2a: Politoed|move: Rage Powder"))
        self.assertEqual(result.counters["turn-scoped.RAGE_POWDER"], 2)
        self.assertEqual(result.counters["perspectives.kept"], 2)

    def test_rage_powder_before_an_own_pivot_stops(self):
        # turn 2: p1's Parting Shot switch is a PIVOT point of side 0
        result = self.run_game(self.insert_after("|turn|2", "|-singleturn|p2a: Politoed|move: Rage Powder"))
        self.assertEqual(result.counters["perspectives.stopped.feature:RAGE_POWDER"], 1)
        self.assertEqual(result.counters["perspectives.kept"], 1)

    def test_picks_incomplete(self):
        # cut before p1's fourth member (Salamence) ever enters
        cut = next(i for i, line in enumerate(self.log) if line.startswith("|switch|p1a: Salamence"))
        result = self.run_game(self.log[:cut] + ["|win|p2"])
        side0 = [r for r in result.rows if r.side == 0]
        self.assertEqual(len(side0), 1)
        self.assertEqual(int(side0[0].observation["boundary_kind"]), 1)
        self.assertEqual(result.counters["perspectives.stopped.picks-incomplete"], 1)

    def test_forfeit_hides_nothing_it_cannot_know(self):
        # review C1: the game ends while players choose: no action ran, a switch was as possible as a move
        cut = next(i for i, line in enumerate(self.log) if line.startswith("|turn|5")) + 1
        result = self.run_game(self.log[:cut] + ["|-message|p1 forfeited.", "|win|p2"])
        last = [r for r in result.rows if int(r.observation["turn"]) == 5]
        self.assertTrue(last)
        from duoforge_replay import labels
        for row in last:
            self.assertNotIn(labels.MOVE_HIDDEN, row.label.reasons, row.side)

    def test_weather_extended_by_an_item_lasts_eight_turns(self):
        # review C2: Politoed's Drizzle with Damp Rock lasts 8 turns, and no line says so: the setter's open sheet
        # holds the rock (data/conditions.ts durationCallback: source.hasItem), so the fold counts 8, not 5
        lines = [line.replace("|MysticWater|", "|DampRock|", 1) if line.startswith("|showteam|p2|") else line
                 for line in self.log]
        result = self.run_game(lines)
        stopped = [k for k in result.counters if k.startswith("perspectives.stopped.line:-weather")]
        self.assertEqual(stopped, [])
        plain = self.run_game(self.log)
        def turns(res):
            return [int(r.observation["weather_turns"]) for r in res.rows if int(r.observation["weather"]) != 0]
        self.assertTrue(turns(plain) and max(turns(plain)) <= 5)
        self.assertTrue(turns(result) and max(turns(result)) > 5, turns(result))
        self.assertLessEqual(max(turns(result)), 8)

    def test_sheet_the_converter_refuses_skips(self):
        # review I2: a refusal of the converter is a counted skip, not an escaping SystemExit
        lines = [line.replace("|Modest|", "||", 1) if line.startswith("|showteam|p2|") else line for line in self.log]
        reason = self.skip_reason(lines)
        self.assertTrue(reason.startswith("sheet:"), reason)

    def test_wide_guard_raises_the_stall_counter(self):
        # review I4: Wide Guard adds the stall volatile (data/moves.ts wideguard onHitSide): the chain shows 1
        lines = self.insert_after("|turn|5", "|-singleturn|p2a: Farigiraf|Wide Guard")
        lines = self.insert_after_in(lines, "|turn|5", "|move|p2a: Farigiraf|Wide Guard|p2a: Farigiraf")
        turn6 = [r for r in self.run_game(lines).rows if r.side == 0 and int(r.observation["turn"]) == 6
                 and int(r.observation["boundary_kind"]) == 2]
        self.assertEqual(int(turn6[0].observation["sides"][1]["positions"][0]["protect_chain"]), 1)

    def test_failed_detect_resets_the_stall_counter(self):
        # review I4: Detect shows "-singleturn|Protect"; its failure resets the counter like Protect's. The reset is
        # visible inside the turn (at a PIVOT); by the next TURN the stall duration ends the chain anyway.
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        lines = self.insert_after("|turn|1", "|-singleturn|p2a: Politoed|Protect")
        lines = self.insert_after_in(lines, "|turn|1", "|move|p2a: Politoed|Detect|p2a: Politoed")
        lines = self.insert_after_in(lines, "|turn|2", "|-fail|p2a: Politoed")
        lines = self.insert_after_in(lines, "|turn|2", "|move|p2a: Politoed|Detect||[still]")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in lines if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), lines)
        fail = lines.index("|-fail|p2a: Politoed")
        tracker.feed(lines[:fail])
        self.assertEqual(tracker._positions[1][0].chain, 1)  # Detect succeeded in turn 1
        tracker.feed([lines[fail]])
        self.assertEqual(tracker._positions[1][0].chain, 0)

    def protected_farigiraf(self, ability=None):
        """A tracker of p1 fed up to Farigiraf's Protect in turn 2 (p2b, chain 1); `ability` replaces Armor Tail on
        its open sheet."""
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        log = [line.replace("]Farigiraf||SitrusBerry|ArmorTail|", f"]Farigiraf||SitrusBerry|{ability}|")
               if ability is not None and line.startswith("|showteam|p2|") else line for line in self.log]
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), log)
        tracker.feed(log[:log.index("|-singleturn|p2b: Farigiraf|Protect") + 1])
        self.assertEqual(tracker._positions[1][1].chain, 1)
        return tracker

    def test_an_ability_failure_keeps_the_stall_counter(self):
        # G22 (#160): an Intimidate that Inner Focus stops is a FAIL of its holder with cause ABILITY (duoforge.h
        # DUOFORGE_EVENT_FAIL); after the holder's Protect it is not the Protect failing: the chain stays
        tracker = self.protected_farigiraf()
        tracker._event(trace_to_c.ev_tuple(trace_to_c.EV["FAIL"], 3, 3, trace_to_c.CAUSE["ABILITY"], 0,
                                           self.data.tables["ABILITY"]["INNERFOCUS"] + 1))
        self.assertEqual(tracker._positions[1][1].chain, 1)

    def test_a_drop_kept_by_the_holders_ability_is_kept(self):
        # an Intimidate after a Protect, stopped by the holder's own ability: the line changes no field; the
        # perspective goes on and the stall chain stays
        tracker = self.protected_farigiraf("InnerFocus")
        line = "|-fail|p2b: Farigiraf|unboost|atk|[from] ability: Inner Focus|[of] p2b: Farigiraf"
        tracker.feed([line])
        self.assertEqual(tracker._positions[1][1].chain, 1)
        self.assertEqual(tracker._positions[1][1].stages, self.protected_farigiraf()._positions[1][1].stages)

    def at_turn_3(self):
        """A tracker of p1 fed up to |turn|3: Farigiraf (p2b) protected in turn 2, its chain is 1."""
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in self.log if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), self.log)
        tracker.feed(self.log[:self.log.index("|turn|3") + 1])
        self.assertEqual(tracker._positions[1][1].chain, 1)
        return tracker

    def test_feint_breaking_the_partners_guard_ends_only_the_targets_chain(self):
        # G28 (sim/battle-actions.ts hitStepBreakProtect): Feint at Farigiraf, which protected the turn before and not
        # now, breaks Politoed's Wide Guard. Farigiraf's stall volatile goes (chain 0, seen at a PIVOT of the turn);
        # Politoed keeps the chain its Wide Guard added, and the side's guard is gone
        tracker = self.at_turn_3()
        tracker.feed(["|move|p2a: Politoed|Wide Guard|p2a: Politoed", "|-singleturn|p2a: Politoed|Wide Guard"])
        self.assertEqual(tracker._positions[1][0].chain, 1)
        self.assertIn("WIDE_GUARD", tracker._turn_scoped)
        tracker.feed(["|move|p1a: Indeedee|Feint|p2b: Farigiraf", "|-activate|p2b: Farigiraf|move: Feint"])
        self.assertEqual((tracker._positions[1][1].chain, tracker._positions[1][1].stall), (0, 0))
        self.assertEqual(tracker._positions[1][0].chain, 1)
        self.assertNotIn("WIDE_GUARD", tracker._turn_scoped)

    def test_a_move_activation_is_no_emergency_exit(self):
        # an ACTIVATE of a move whose id equals Emergency Exit's ability id + 1 (move 8, Muddy Water) asks no switch:
        # only cause ABILITY names an ability
        tracker = self.at_turn_3()
        exit_id = self.data.tables["ABILITY"]["EMERGENCYEXIT"] + 1
        self.assertEqual(self.data.tables["MOVE"]["MUDDYWATER"], exit_id)
        tracker._event(trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], 2, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 0,
                                           exit_id))
        self.assertEqual(tracker._positions[1][0].flag, 0)
        tracker._event(trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], 2, trace_to_c.NOPOS, trace_to_c.CAUSE["ABILITY"], 0,
                                           exit_id))
        self.assertEqual(tracker._positions[1][0].flag, 1)

    def charizard_mega(self, stone, forme):
        """The committed log with Charizard (p2) holding `stone` and evolving into `forme`."""
        out = []
        for line in self.log:
            if line.startswith("|showteam|p2|"):
                line = line.replace("]Charizard||CharizarditeY|", f"]Charizard||{stone.replace(' ', '')}|")
            elif line == "|detailschange|p2b: Charizard|Charizard-Mega-Y, L50, M":
                line = f"|detailschange|p2b: Charizard|{forme}, L50, M"
            elif line == "|-mega|p2b: Charizard|Charizard|Charizardite Y":
                line = f"|-mega|p2b: Charizard|Charizard|{stone}"
            out.append(line)
        return out

    def test_mega_x_folds_with_its_own_ability(self):
        # G23: Charizardite X takes Charizard to Charizard-Mega-X (Tough Claws), not to the first Mega of the forme
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        lines = self.charizard_mega("Charizardite X", "Charizard-Mega-X")
        result = self.run_game(lines)
        self.assertFalse([k for k in result.counters if k.startswith("perspectives.stopped.")], result.counters)
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in lines if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), lines)
        tracker.feed(lines[:lines.index("|-mega|p2b: Charizard|Charizard|Charizardite X") + 1])
        charizard = tracker._member_of("p2b: Charizard")
        self.assertEqual((charizard.is_mega, charizard.ability), (1, self.data.tables["ABILITY"]["TOUGHCLAWS"] + 1))

    def test_a_mega_its_stone_does_not_reach_stops(self):
        # Charizardite Y shown on the sheet, Charizard-Mega-X in the log: no Mega Evolution the stone makes
        result = self.run_game(self.charizard_mega("Charizardite Y", "Charizard-Mega-X"))
        self.assertEqual(result.counters["perspectives.stopped.feature:FORME_CHANGE"], 2, result.counters)

    def turn_rows(self, result, turn, side=0):
        return [r for r in result.rows if r.side == side and int(r.observation["turn"]) == turn
                and int(r.observation["boundary_kind"]) == 2]

    def test_sandstorm_folds(self):
        # spec 5: the base-value features fold (TRACKER_FOLDS); Sand and Snow were the largest curable stops
        from duoforge._layout import CONSTANTS as C
        lines_ = self.insert_after("|turn|2", "|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Politoed")
        result = self.run_game(lines_)
        self.assertFalse([k for k in result.counters if "WEATHER_SAND" in k], result.counters)
        o = self.turn_rows(result, 3)[0].observation
        self.assertEqual((int(o["weather"]), int(o["weather_turns"])), (C["DUOFORGE_WEATHER_SAND"], 4))

    def test_snowscape_folds(self):
        from duoforge._layout import CONSTANTS as C
        result = self.run_game(self.insert_after("|turn|2", "|-weather|Snowscape"))
        self.assertFalse([k for k in result.counters if "WEATHER_SNOW" in k], result.counters)
        self.assertEqual(int(self.turn_rows(result, 3)[0].observation["weather"]), C["DUOFORGE_WEATHER_SNOW"])

    def test_tox_folds(self):
        from duoforge_live import teams
        from duoforge_replay.spectator import SpectatorTracker
        lines_ = self.insert_after("|turn|2", "|-status|p2a: Politoed|tox")
        self.assertFalse([k for k in self.run_game(lines_).counters if "AILMENT_TOX" in k])
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in lines_ if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), lines_)
        tracker.feed(lines_[:lines_.index("|-status|p2a: Politoed|tox") + 1])
        self.assertEqual(tracker._member_of("p2a: Politoed").status, trace_to_c.STATUS["tox"])

    def test_unknown_weather_form_still_stops(self):
        # "-weather|Snow" (an older server's name) is no form the converter reads: a named stop, never a fold
        result = self.run_game(self.insert_after("|turn|2", "|-weather|Snow"))
        stops = [k for k in result.counters if k.startswith("perspectives.stopped.")]
        self.assertTrue(stops and all(k.startswith("perspectives.stopped.converter:") for k in stops), result.counters)

    def test_unsupported_base_bit_still_stops(self):
        from unittest import mock
        without_sand = lines.SUPPORTED & ~(1 << lines.FEATURES["WEATHER_SAND"])
        with mock.patch.object(lines, "SUPPORTED", without_sand):
            result = self.run_game(self.insert_after("|turn|2", "|-weather|Sandstorm"))
        self.assertEqual(result.counters["perspectives.stopped.feature:WEATHER_SAND"], 2, result.counters)

    def insert_after_in(self, lines, prefix, new):
        i = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        return lines[:i + 1] + [new] + lines[i + 1:]

    def test_forme_changed_on_the_bench_stops(self):
        # full run: Zero to Hero turns Palafin into Palafin-Hero on its way out, silently; its next switch line
        # shows the new forme (decision 0018 FORME_CHANGE), never an internal error
        i = max(i for i, line in enumerate(self.log) if line.startswith("|switch|p2a: Politoed|"))
        lines = list(self.log)
        lines[i] = lines[i].replace("Politoed, L50, M", "Politoed-Hero, L50, M")
        result = self.run_game(lines)
        self.assertEqual(result.counters["perspectives.stopped.feature:FORME_CHANGE"], 2)
        self.assertGreater(len(result.rows), 4)

    def test_charge_target_hidden_when_its_side_has_a_vacancy(self):
        from duoforge_live import teams
        from duoforge_replay.spectator import HIDDEN_TARGET, SpectatorTracker
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in self.log if line.startswith("|showteam|"))
        tracker = SpectatorTracker(self.data, sheets, 0, None, lambda m, f: ([100] * 6, [0] * 6), self.log)
        faint = self.log.index("|faint|p2b: Charizard")
        tracker.feed(self.log[:faint + 1])  # p2b fainted, not replaced yet
        tracker._log = self.log[:tracker._fed + 1] + ["|move|p1a: Salamence|Draco Meteor|p2a: Politoed|[from]lockedmove"]
        self.assertEqual(tracker._own_target(0), HIDDEN_TARGET)

    def with_moves(self, old, new):
        """The committed log with a sheet's move list `old` replaced by `new`."""
        return [line.replace(old, new) if line.startswith("|showteam|") else line for line in self.log]

    def test_regmb_pp_skip(self):
        # BC spec 11: Strength Sap and Wish have other PP in Reg M-B (10) than in the engine's M-C data (5)
        from duoforge_replay import game
        lines_ = self.with_moves("KowtowCleave,SuckerPunch,IronHead,Protect", "KowtowCleave,SuckerPunch,IronHead,Wish")
        with self.assertRaises(game.Skip) as caught:
            game.process("fixture-mb", "gen9championsvgc2026regmbbo3", chr(10).join(lines_), self.data, self.prior, _Stats())
        self.assertEqual(caught.exception.reason, "skip:regmb-pp")
        with self.assertRaises(game.Skip) as caught:
            self.run_game(lines_)  # Reg M-C: no PP difference; Kingambit cannot learn Wish under POOL
        self.assertEqual(caught.exception.reason, "skip:pool-illegal Kingambit move Wish")

    def test_pool_illegal_skip(self):
        lines_ = self.with_moves("DragonPulse,ElectroShot,Snarl,Protect", "DragonPulse,ElectroShot,MirrorCoat,Protect")
        self.assertEqual(self.skip_reason(lines_), "skip:pool-illegal Archaludon move MirrorCoat")

    def test_two_games_in_one_log_skip(self):
        # a Bo3 log with a second game's lines: one game per row, so the log is skipped and counted
        start = self.log.index("|start")
        self.assertEqual(self.skip_reason(self.log + self.log[start:]), "skip:two-games")

    def test_a_failure_the_converter_does_not_parse_stops(self):
        # the converter decides which -fail forms it reads (main reads "heal" since G8); the one it cannot read is a
        # named stop, never an internal error
        lines = self.insert_after("|turn|3", "|-fail|p2a: Politoed|move: Substitute")
        result = self.run_game(lines)
        stops = [k for k in result.counters if k.startswith("perspectives.stopped.converter:untyped -fail")]
        self.assertEqual(sum(result.counters[k] for k in stops), 2, result.counters)

    def test_a_drop_kept_by_another_ability_stops(self):
        # -fail|X|unboost from an ability the holder does not have (Politoed: Drizzle) is no form the fold knows
        lines = self.insert_after("|turn|3", "|-fail|p2a: Politoed|unboost|[from] ability: Clear Body|[of] p2a: Politoed")
        result = self.run_game(lines)
        self.assertEqual(result.counters["perspectives.stopped.line:-fail unboost"], 2, result.counters)

    def test_bo3_game_number(self):
        lines = ['|uhtml|bestof|<h2><strong>Game 2</strong> of <a href="/game-bestof3-x">a best-of-3</a></h2>'] + self.log
        self.assertEqual(self.run_game(lines).record.bo3_game, 2)



class SupersetTest(unittest.TestCase):
    """Superset lists on the fixture (Task 6); duoforge.python.replay checks them against DuoForge."""

    def test_replacement_list(self):
        from duoforge_live import options, teams
        from duoforge_replay import points, spectator, superset
        log = FIXTURE.read_text(encoding="utf-8").splitlines()
        pool = data.load(kind="pool")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        picks = spectator.hindsight_picks(log, 0, pool, sheets)
        tracker = spectator.SpectatorTracker(pool, sheets, 0, picks, lambda m, f: ([100] * 6, [0] * 6), log)
        seen = []
        for point in spectator.walk(tracker, log, points.find(log)):
            if point.boundary == points.REPLACEMENT and spectator.own_requested(tracker):
                _, lists = superset.domain(tracker)
                seen.append([o.kind for o in lists[0]])
        # after turn 5 p1a fainted: the alive bench members, then pass
        self.assertTrue(seen)
        self.assertTrue(all(kinds[-1] == options.PASS and set(kinds[:-1]) <= {options.SWITCH} for kinds in seen), seen)

    def test_struggle_beside_every_move_list(self):
        # an effect outside the view can disable every move (two or more too), and then the request is Struggle
        from duoforge_live import options, teams
        from duoforge_replay import points, spectator, superset
        log = FIXTURE.read_text(encoding="utf-8").splitlines()
        pool = data.load(kind="pool")
        sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        picks = spectator.hindsight_picks(log, 0, pool, sheets)
        tracker = spectator.SpectatorTracker(pool, sheets, 0, picks, lambda m, f: ([100] * 6, [0] * 6), log)
        moving = 0
        for point in spectator.walk(tracker, log, points.find(log)):
            if point.boundary == points.TURN and spectator.own_requested(tracker):
                _, lists = superset.domain(tracker)
                for slot in lists:
                    if any(o.kind == options.MOVE for o in slot):
                        moving += 1
                        self.assertTrue(any(o.move_slot == options.STRUGGLE for o in slot), slot)
        self.assertGreater(moving, 10)


def stats_factory():
    """The stat source of the build tests' workers (a module-level function, so spawned workers import it)."""
    return _Stats()


def _sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasetTest(unittest.TestCase):
    """Shards, games table, manifest, counters, determinism (Task 9, spec section 11)."""

    @classmethod
    def setUpClass(cls):
        import json
        from duoforge_replay import game, prior
        cls.data = data.load(kind="pool")
        cls.log = FIXTURE.read_text(encoding="utf-8")
        cls.empty_prior = {"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}
        cls.results = [game.process(f"fixture-{i}", "gen9championsvgc2026regmc", cls.log, cls.data,
                                    prior.Prior(cls.empty_prior), _Stats()) for i in range(2)]
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_dataset_"))
        cls.prior_path = cls.tmp / "prior.json"
        cls.prior_path.write_text(json.dumps(cls.empty_prior), encoding="utf-8")
        source = cls.tmp / "source.jsonl"
        with open(source, "w", encoding="utf-8", newline="\n") as f:
            for i in range(3):
                f.write(json.dumps({"id": f"fixture-{i}", "formatid": "gen9championsvgc2026regmcbo3",
                                    "log": cls.log}) + "\n")
            f.write(json.dumps({"id": "other", "formatid": "gen9ou", "log": cls.log}) + "\n")
        cls.source = source

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def write(self, name, shard_rows=40):
        from duoforge_replay import dataset
        writer = dataset.Writer(self.tmp / name, {"test": True}, shard_rows=shard_rows)
        for result in self.results:
            writer.add(result)
        return writer.close()

    def test_round_trip(self):
        from duoforge_replay import dataset
        counters = self.write("round")
        shards = list(dataset.read(self.tmp / "round"))
        self.assertGreater(len(shards), 1)  # 40 rows per shard
        rows = sum(len(s["side"]) for s in shards)
        self.assertEqual(rows, sum(len(r.rows) for r in self.results))
        self.assertEqual(counters["points.written"], rows)
        first = shards[0]
        want = self.results[0].rows[0]
        self.assertEqual(first["observation"][0].tobytes(), want.observation.tobytes())
        self.assertEqual(first["domain"][0].tobytes(), want.domain.tobytes())
        self.assertEqual(tuple(first["label_slots"][0]), want.label.slots)
        self.assertEqual(bytes(first["label_team"][0]), want.label.team)
        games = dataset.read_games(self.tmp / "round")
        self.assertEqual(list(games["replay_id"]), ["fixture-0", "fixture-1"])
        self.assertEqual(games["winner"].tolist(), [1, 1])

    def test_same_bytes_twice(self):
        self.write("a")
        self.write("b")
        for path in sorted((self.tmp / "a").iterdir()):
            self.assertEqual(_sha(path), _sha(self.tmp / "b" / path.name), path.name)

    def test_refuses_the_repository(self):
        import subprocess
        from duoforge_replay import dataset
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.Writer(data.ROOT / "build" / "replay-out", {})
        # review I3: any work tree of this repository (the main checkout of a worktree too), and the prior file
        common = subprocess.run(["git", "-C", str(data.ROOT), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.Writer(Path(common).parent / "replay-out", {})
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            dataset.refuse_repository(Path(common).parent / "prior.json")

    def test_refuses_a_used_directory(self):
        from duoforge_replay import dataset
        self.write("used")
        with self.assertRaisesRegex(ValueError, "not empty"):
            dataset.Writer(self.tmp / "used", {})

    def build(self, name, workers=1, **kw):
        from duoforge_replay import build
        kw.setdefault("stats_factory", stats_factory)
        return build.build([self.source], self.prior_path, self.tmp / name, workers=workers, unit_lines=2,
                           log=lambda _: None, **kw)

    def test_counters_add_up(self):
        c = self.build("counted")
        skipped = sum(v for k, v in c.items() if k.startswith("games.skipped."))
        internal = sum(v for k, v in c.items() if k.startswith("internal:"))
        self.assertEqual(c["games.read"], c["games.processed"] + skipped + internal)
        stopped = sum(v for k, v in c.items() if k.startswith("perspectives.stopped."))
        self.assertEqual(c["perspectives.kept"] + stopped, 2 * c["games.processed"])
        self.assertEqual(c["games.processed"], 3)
        self.assertEqual(c["games.skipped.skip:format"], 1)

    def test_parts_are_source_units(self):
        # two source lines per unit: four games give two parts, each its own directory
        from duoforge_replay import dataset
        self.build("units")
        parts = sorted(p.name for p in (self.tmp / "units").iterdir() if p.is_dir())
        self.assertEqual(parts, ["part-source-00000", "part-source-00001"])
        rows = sum(len(shard["side"]) for shard in dataset.read(self.tmp / "units"))
        self.assertEqual(rows, sum(len(r.rows) for r in self.results) * 3 // 2)

    def test_workers_same_bytes(self):
        for workers in (1, 2):
            self.build(f"w{workers}", workers=workers)
        files = sorted(p.relative_to(self.tmp / "w1") for p in (self.tmp / "w1").rglob("*") if p.is_file())
        self.assertTrue(any(f.parts[0].startswith("part-") for f in files))
        for f in files:
            if f.name != "manifest.json" or len(f.parts) > 1:  # a part's manifest names no worker count
                self.assertEqual(_sha(self.tmp / "w1" / f), _sha(self.tmp / "w2" / f), f)

    def test_resume_writes_only_missing_parts(self):
        whole = self.tmp / "whole"
        self.build("whole")
        resumed = self.tmp / "resumed"
        self.build("resumed")
        shutil.rmtree(resumed / "part-source-00001")  # a run stopped before this part
        (resumed / "part-source-00000.tmp").mkdir()  # a half-written part of a killed run
        (resumed / "part-source-00000.tmp" / "junk").write_text("x")
        c = self.build("resumed")
        self.assertEqual(c["parts.written"], 1)
        self.assertEqual(c["parts.skipped.done"], 1)
        self.assertFalse((resumed / "part-source-00000.tmp").exists())
        files = sorted(p.relative_to(whole) for p in whole.rglob("*") if p.is_file())
        self.assertIn(Path("counters.json"), files)
        for f in files:
            if f != Path("manifest.json"):  # the output's manifest records the last run (parts written, seconds)
                self.assertEqual(_sha(whole / f), _sha(resumed / f), f)

    def test_the_output_must_be_a_dataset_or_empty(self):
        from duoforge_replay import build
        stranger = self.tmp / "stranger"
        stranger.mkdir()
        (stranger / "notes.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "not a replay dataset"):
            build.build([self.source], self.prior_path, stranger, unit_lines=2, stats_factory=stats_factory,
                        log=lambda _: None)


def broken_stats_factory():
    """A stat source that fails like a dead Node process: every game is an internal error."""
    class Broken:
        def stats(self, species, nature, stat_points):
            raise RuntimeError("ps_stats.js ended")
    return Broken()


class PartsReviewTest(unittest.TestCase):
    """Review of #127: resume keeps bugs visible, refuses changed inputs and broken parts, pauses, validates."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_parts_"))
        cls.log = FIXTURE.read_text(encoding="utf-8")
        cls.prior_path = cls.tmp / "prior.json"
        cls.prior_path.write_text(json.dumps({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                                  encoding="utf-8")
        cls.source = cls.tmp / "source.jsonl"
        with open(cls.source, "w", encoding="utf-8", newline=chr(10)) as f:
            for i in range(4):
                f.write(json.dumps({"id": f"fixture-{i}", "formatid": "gen9championsvgc2026regmc", "log": cls.log})
                        + chr(10))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, name, **kw):
        from duoforge_replay import build
        kw.setdefault("stats_factory", stats_factory)
        kw.setdefault("unit_lines", 2)
        return build.build([self.source], self.prior_path, self.tmp / name, log=lambda _: None, **kw)

    def test_internal_errors_survive_a_resume(self):
        # I1: a part written with internal errors keeps its replay ids; a resume still reports them
        first = self.build("broken", stats_factory=broken_stats_factory, limit_parts=1)
        self.assertTrue(first["internal.examples"])
        again = self.build("broken")  # the clean remaining part
        self.assertEqual(again["parts.written"], 1)
        self.assertTrue(any("fixture-0" in e for e in again["internal.examples"]), again["internal.examples"])
        self.assertGreater(again["internal:RuntimeError"], 0)

    def test_changed_inputs_are_refused(self):
        # I2/I5: another unit size, prior or Showdown pin is another dataset
        pin = str(data.ROOT)  # any git checkout stands in for the Showdown pin here; the tmp directory has none
        self.build("inputs", limit_parts=1, ps_dir=pin)
        with self.assertRaisesRegex(ValueError, "other inputs"):
            self.build("inputs", unit_lines=3, ps_dir=pin)
        with self.assertRaisesRegex(ValueError, "other inputs"):
            self.build("inputs", ps_dir=str(self.tmp))
        self.assertEqual(self.build("inputs", ps_dir=pin)["parts.written"], 1)  # the same inputs resume

    def test_a_broken_part_is_redone(self):
        # I4: a part whose files a host crash left empty is not finished
        self.build("crash")
        part = self.tmp / "crash" / "part-source-00001"
        (part / "manifest.json").write_text("", encoding="utf-8")
        c = self.build("crash")
        self.assertEqual(c["parts.written"], 1)
        self.assertEqual(c["parts.redone.broken"], 1)

    def test_pause_holds_every_worker(self):
        # I3: with two workers the build submits nothing while the pause file exists
        import os
        import threading
        import time
        pause = self.tmp / "pause"
        pause.write_text("x")
        saved = os.environ.get("DUOFORGE_FUZZ_PAUSE")
        os.environ["DUOFORGE_FUZZ_PAUSE"] = str(pause)
        threading.Timer(2.0, pause.unlink).start()
        start = time.monotonic()
        try:
            c = self.build("paused", workers=2)
        finally:
            if saved is None:
                os.environ.pop("DUOFORGE_FUZZ_PAUSE", None)
            else:
                os.environ["DUOFORGE_FUZZ_PAUSE"] = saved
        self.assertGreaterEqual(time.monotonic() - start, 2.0)
        self.assertEqual(c["parts.written"], 2)

    def test_a_second_run_on_the_same_output_is_refused(self):
        # M4: the lock of a running build
        out = self.tmp / "locked"
        self.build("locked", limit_parts=0)
        (out / "build.lock").write_text("12345")
        with self.assertRaisesRegex(ValueError, "another build"):
            self.build("locked")

    def test_bad_arguments(self):
        # M3
        from duoforge_replay import __main__ as cli
        for args in (["--limit-parts", "-1"], ["--unit-lines", "0"]):
            with self.assertRaises(SystemExit):
                cli.main(["build", "--source", str(self.source), "--prior", str(self.prior_path),
                          "--out", str(self.tmp / "never"), *args])

    def test_an_unfinished_parts_output_reads_empty(self):
        # M1: a parts dataset with no finished part is empty, not the single-directory layout
        from duoforge_replay import dataset
        self.build("empty", limit_parts=0)
        self.assertEqual(list(dataset.read(self.tmp / "empty")), [])


class _FakeParquet:
    """pyarrow.parquet for one fake file: two row groups, the first of another format."""

    class _Column:
        def __init__(self, values):
            self.values = values

        def to_pylist(self):
            return list(self.values)

    class _Table:
        def __init__(self, rows, columns):
            self.cols = {c: [r[c] for r in rows] for c in columns}

        def column(self, c):
            return _FakeParquet._Column(self.cols[c] if isinstance(c, str) else list(self.cols.values())[c])

    class ParquetFile:
        groups = [[{"id": "a", "formatid": "gen9ou", "log": ""}, {"id": "b", "formatid": "gen9ou", "log": ""}],
                  [{"id": "c", "formatid": "gen9championsvgc2026regmc", "log": "x"}]]

        def __init__(self, path):
            self.metadata = type("M", (), {"num_row_groups": 2})()

        def read_row_group(self, group, columns):
            return _FakeParquet._Table(self.groups[group], columns)


class SourceTest(unittest.TestCase):
    def test_skipped_row_groups_are_counted(self):
        import collections
        import types
        from duoforge_replay import source
        fake = types.ModuleType("pyarrow.parquet")
        fake.ParquetFile = _FakeParquet.ParquetFile
        package = types.ModuleType("pyarrow")
        package.parquet = fake
        saved = {k: sys.modules.get(k) for k in ("pyarrow", "pyarrow.parquet")}
        sys.modules.update({"pyarrow": package, "pyarrow.parquet": fake})
        try:
            tmp = Path(tempfile.mkdtemp(prefix="duoforge_source_"))
            (tmp / "x.parquet").write_bytes(b"")
            counters = collections.Counter()
            units = source.units([tmp])
            self.assertEqual([u.id for u in units], ["x-00000", "x-00001"])
            rows = []
            for unit in units:
                rows += list(source.select(source.read_unit(unit, "gen9championsvgc2026regmc", counters),
                                           "gen9championsvgc2026regmc", counters))
            shutil.rmtree(tmp, ignore_errors=True)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertEqual(counters["games.read"], 3)
        self.assertEqual(counters["games.skipped.skip:format"], 2)
        self.assertEqual(counters["games.skipped.skip:sheets"], 1)
        self.assertEqual(rows, [])

    def test_select(self):
        import collections
        from duoforge_replay import source
        log2 = "|showteam|p1|x\n|showteam|p2|y"
        rows = [("a", "gen9championsvgc2026regmc", log2), ("b", "gen9ou", log2),
                ("c", "gen9championsvgc2026regmcbo3", "|showteam|p1|x"), ("d", "gen9championsvgc2026regmcbo3", log2)]
        counters = collections.Counter()
        kept = list(source.select(rows, "gen9championsvgc2026regmc", counters))
        self.assertEqual([r[0] for r in kept], ["a", "d"])
        self.assertEqual(counters["games.skipped.skip:format"], 1)
        self.assertEqual(counters["games.skipped.skip:sheets"], 1)


if __name__ == "__main__":
    unittest.main()
