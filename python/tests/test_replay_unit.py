"""duoforge.python.replay_unit: the M11 replay pipeline without Node (spec
docs/superpowers/specs/2026-10-02-m11-replay-data-design.md section 14).

Everything here runs on our own data: the generated tables, the reference
teams and a committed spectator log of one reference battle
(python/tests/data/replay/). No replay of the unlicensed dataset is a test
input.
"""
import collections
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

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

    def item_now(self, ident):
        return self.sheet_of(ident)["item"]

    def side_sheets(self, ident):
        return [m for k, m in self._members.items() if k[:2] == ident[:2]]


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
        self.assertEqual(self.stop("|-fieldstart|move: Gravity"), "feature:GRAVITY")
        self.assertEqual(lines.check("|-fieldstart|move: Electric Terrain|[from] ability: Electric Surge|[of] p2a: Gholdengo",
                                     self.view), "fold")  # a base-value feature: the observation's terrain
        # Trace's copy folds (ABILITY_CHANGE); an ability source the engine does not model stops on its line
        self.assertEqual(lines.check("|-ability|p2a: Gholdengo|Intimidate|[from] ability: Trace|[of] p1a: Staraptor",
                                     self.view), "fold")
        self.assertEqual(self.stop("|-ability|p2a: Gholdengo|Pressure|Good as Gold|[from] move: Role Play|"
                                   "[of] p1a: Staraptor"), "line:-ability [from] move: Role Play")

    def test_frisk_of_the_held_item_is_kept(self):
        # Frisk names the holder's item: the one the open sheet (or item_now) shows changes no field; another stops
        self.assertEqual(lines.check("|-item|p1a: Staraptor|Sitrus Berry|[from] ability: Frisk|[of] p2a: Gholdengo",
                                     self.view), "keep")
        self.assertEqual(lines.check("|-item|p1a: Staraptor|Sitrus Berry|[from] ability: Frisk|[of] p2a: Gholdengo|"
                                     "[identify]", self.view), "keep")
        self.assertEqual(self.stop("|-item|p1a: Staraptor|Leftovers|[from] ability: Frisk|[of] p2a: Gholdengo"),
                         "line:-item Leftovers")

    def test_type_change_lines(self):
        # Soak (no attribute) and Double Shock (???/its other type) are the type changes the engine models (steps G11,
        # G50); every other typechange line stops on its own line
        self.assertEqual(lines.check("|-start|p1a: Staraptor|typechange|Water", self.view), "fold")
        self.assertEqual(lines.check("|-start|p1a: Staraptor|typechange|???/Fighting|[from] move: Double Shock",
                                     self.view), "fold")
        self.assertEqual(self.stop("|-start|p1a: Staraptor|typechange|Fire|[from] ability: Protean"),
                         "line:-start typechange [from] ability: Protean")
        self.assertEqual(self.stop("|-start|p1a: Staraptor|typechange|[from] move: Reflect Type|[of] p2a: Gholdengo"),
                         "line:-start typechange [from] move: Reflect Type")

    def test_hazard_lines(self):
        # Step G37: a -sidestart lays a layer (folded); of the removals only Toxic Spikes absorbed by a grounded Poison
        # type (no [from]) is modelled, Defog, Rapid Spin, Mortal Spin and Tidy Up stop on their line
        self.assertEqual(lines.check("|-sidestart|p1: Staraptor|move: Toxic Spikes", self.view), "fold")
        self.assertEqual(lines.check("|-sideend|p1: Staraptor|move: Toxic Spikes|[of] p1a: Staraptor", self.view),
                         "fold")
        self.assertEqual(self.stop("|-sideend|p1: Staraptor|move: Toxic Spikes|[from] move: Rapid Spin|"
                                   "[of] p1a: Staraptor"), "line:-sideend move: Toxic Spikes [from] move: Rapid Spin")
        self.assertEqual(self.stop("|-sideend|p1: Staraptor|Spikes|[from] move: Defog|[of] p2a: Gholdengo"),
                         "line:-sideend Spikes [from] move: Defog")

    def test_unmodelled_ability_changes_stop_on_their_line(self):
        # Mummy and Lingering Aroma print -activate|holder|ability: X|attacker|[ability] Old (sim/pokemon.ts setAbility,
        # :1928-1930), Wandering Spirit the Skill Swap line of battle.skillSwap; the engine models none of them
        # (DFI_HANDLER_UNMODELED), so each stops with its own reason, never through a converter refusal
        view = _View({"p1: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE"),
                      "p2: Cofagrigus": ("COFAGRIGUS", "LEFTOVERS", "MUMMY"),
                      "p2: Runerigus": ("RUNERIGUS", "LEFTOVERS", "WANDERINGSPIRIT"),
                      "p2: Gholdengo": ("GHOLDENGO", "LIFEORB", "GOODASGOLD")})

        def stop(line):
            with self.assertRaises(lines.Stop) as caught:
                lines.check(line, view)
            return caught.exception.reason
        self.assertEqual(stop("|-activate|p2a: Cofagrigus|ability: Mummy|p1a: Staraptor|[ability] Intimidate"),
                         "line:-activate ability: Mummy")
        self.assertEqual(stop("|-activate|p2a: Cofagrigus|ability: Lingering Aroma|p1a: Staraptor|[ability] Intimidate"),
                         "line:-activate ability: Lingering Aroma")
        self.assertEqual(stop("|-activate|p1a: Staraptor|Skill Swap|Wandering Spirit|Intimidate|[of] p2b: Runerigus"),
                         "line:-activate Skill Swap Wandering Spirit")
        self.assertEqual(stop("|-activate|p2a: Cofagrigus|Skill Swap|||[of] p2b: Runerigus"),
                         "line:-activate Skill Swap Wandering Spirit")  # an ally swap: the holder's current ability
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|Skill Swap|Good as Gold|Intimidate|[of] p2a: Gholdengo",
                                     view), "fold")  # Skill Swap of two modelled abilities folds
        # Knock Off folds (ITEM_CHANGE); an item source the engine does not model stops on its line
        self.assertEqual(lines.check("|-enditem|p1a: Staraptor|Sitrus Berry|[from] move: Knock Off|[of] p2a: Gholdengo",
                                     self.view), "fold")
        self.assertEqual(self.stop("|-enditem|p1a: Staraptor|Sitrus Berry|[from] move: Incinerate"),
                         "line:-enditem [from] move: Incinerate")
        self.assertEqual(self.stop("|-item|p1a: Staraptor|Sitrus Berry|[from] move: Recycle"),
                         "line:-item [from] move: Recycle")
        self.assertEqual(self.stop("|-start|p1a: Staraptor|move: Leech Seed"), "feature:LEECH_SEED")
        self.assertEqual(lines.check("|-start|p1a: Staraptor|Encore", self.view), "fold")  # the tracker folds Encore
        self.assertEqual(lines.check("|-status|p1a: Staraptor|tox", self.view), "fold")  # Tox folds (BC spec 5)
        self.assertEqual(self.stop("|replace|p1a: Zoroark|Zoroark-Hisui, L50, M"), "feature:ILLUSION")

    def test_g64_lines(self):
        # Step G64: Sheer Cold's bare -ohko after the target's faint changes no field (kept, no event); Poltergeist's
        # -activate names the item its target holds, the open sheet's (another stops); Bug Bite's stealeat takes the
        # target's berry like Knock Off, decision 0018's ITEM_CHANGE (folded)
        self.assertEqual(lines.check("|-ohko", self.view), "keep")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: Poltergeist|Life Orb", self.view), "fold")
        self.assertEqual(self.stop("|-activate|p2a: Gholdengo|move: Poltergeist|Leftovers"),
                         "line:-activate move: Poltergeist")
        bug_bite = "|-enditem|p1a: Staraptor|Sitrus Berry|[from] stealeat|[move] Bug Bite|[of] p2a: Gholdengo"
        self.assertEqual(lines.check(bug_bite, self.view), "fold")
    def test_phantom_force_breaking_a_protection_folds(self):
        # Step G58: Phantom Force breaks a Protect like Feint (hitStepBreakProtect), printed with [broken]
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: Phantom Force|[broken]", self.view), "fold")

    def test_item_transfer_lines_are_item_change(self):
        # G29 (#171): every line of a Trick, Switcheroo, Thief or Covet is decision 0018's ITEM_CHANGE, the
        # -activate of Trick too (it names the target; Switcheroo prints none); the tracker folds them
        for line in ("|-activate|p1a: Staraptor|move: Trick|[of] p2a: Gholdengo",
                     "|-item|p1a: Staraptor|Choice Scarf|[from] move: Trick",
                     "|-enditem|p1a: Staraptor|Sitrus Berry|[silent]|[from] move: Switcheroo",
                     "|-item|p1a: Staraptor|Life Orb|[from] move: Thief|[of] p2a: Gholdengo",
                     "|-enditem|p2a: Gholdengo|Life Orb|[silent]|[from] move: Thief|[of] p1a: Staraptor",
                     "|-item|p1a: Staraptor|Life Orb|[from] move: Covet|[of] p2a: Gholdengo"):
            self.assertEqual(lines.check(line, self.view), "fold", line)

    def test_haze_folds(self):
        # Step G62 (decision 0031): Haze's -clearallboost is the CLEAR_ALL_BOOSTS event; the tracker folds it
        self.assertEqual(lines.check("|-clearallboost", self.view), "fold")

    def test_after_you_and_quash_fold(self):
        # Step G62: After You and Quash move their target in the action queue (data/moves.ts afteryou, quash: -activate
        # of the target); the queue is no field of the view, the move lines that follow show the order
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: After You", self.view), "fold")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: Quash", self.view), "fold")
    def test_substitute_lines_stop_on_its_feature(self):
        # Decision 0032 (step G60): every line that shows a Substitute stops on its feature until the tracker folds it,
        # the absorbed hit's -activate included (it is no unknown line); its -fail lines are FAIL events (fold)
        for line in ("|-start|p1a: Staraptor|Substitute", "|-end|p1a: Staraptor|Substitute",
                     "|-activate|p1a: Staraptor|move: Substitute|[damage]"):
            self.assertEqual(self.stop(line), "feature:SUBSTITUTE", line)
        for line in ("|-fail|p1a: Staraptor|move: Substitute", "|-fail|p1a: Staraptor|move: Substitute|[weak]"):
            self.assertEqual(lines.check(line, self.view), "fold", line)

    def test_a_terrain_blocking_yawn_is_its_terrain_feature(self):
        # The Yawn fix: Electric Terrain blocks the Yawn volatile and its sleep, Misty Terrain the sleep
        # (data/moves.ts electricterrain/mistyterrain onTryAddVolatile/onSetStatus): the terrain's own feature, as
        # its -fieldstart line, not an unknown line
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: Electric Terrain", self.view), "fold")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|move: Misty Terrain", self.view), "fold")

    def test_a_line_that_does_not_fit_its_name_under_a_possible_illusion_is_the_illusion_feature(self):
        # Step I2 (decision 0026): under a disguise the lines name the disguise, so an item or ability that is not the
        # named member's can be the Illusion holder's (a Focus Sash used up under the disguise); with an Illusion holder
        # on that side's sheet the line stops on feature:ILLUSION, without one it stays an unknown line
        view = _View({"p1: Staraptor": ("STARAPTOR", "SITRUSBERRY", "INTIMIDATE"),
                      "p2: Gholdengo": ("GHOLDENGO", "LIFEORB", "GOODASGOLD"),
                      "p2: Zoroark": ("ZOROARKHISUI", "FOCUSSASH", "ILLUSION")})
        with self.assertRaises(lines.Stop) as caught:
            lines.check("|-enditem|p2a: Gholdengo|Focus Sash", view)
        self.assertEqual(caught.exception.reason, "feature:ILLUSION")
        self.assertEqual(self.stop("|-enditem|p1a: Staraptor|Focus Sash"), "line:-enditem Focus Sash")

    def test_symbiosis_passing_its_item_is_item_change(self):
        # Step G69: Symbiosis hands the holder's item to its partner (`-activate|X|ability: Symbiosis|Item|[of] Y`): the
        # partner then holds another item than its sheet's, decision 0018's ITEM_CHANGE, as Trick, Knock Off, Bug Bite
        view = _View({"p1: Staraptor": ("STARAPTOR", "LEFTOVERS", "SYMBIOSIS"),
                      "p1: Gholdengo": ("GHOLDENGO", "FOCUSSASH", "GOODASGOLD")})
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|ability: Symbiosis|Leftovers|[of] p1b: Gholdengo", view),
                         "fold")  # the tracker folds ITEM_CHANGE

    def test_skill_swap_lines_are_ability_change(self):
        # Step G70 (decision 0041): the pin prints "Skill Swap" without "move: " for a foe swap (both abilities named)
        # and an ally swap (none named); both are decision 0018's ABILITY_CHANGE, which the tracker folds
        for line in ("|-activate|p1a: Staraptor|Skill Swap|Good as Gold|Intimidate|[of] p2a: Gholdengo",
                     "|-activate|p1a: Staraptor|Skill Swap|||[of] p1b: Staraptor",
                     "|-activate|p1a: Staraptor|move: Skill Swap|Good as Gold|Intimidate|[of] p2a: Gholdengo"):
            self.assertEqual(lines.check(line, self.view), "fold", line)

    def test_destiny_bond_lines_are_its_feature(self):
        # Step G76: Destiny Bond's start (-singlemove) and its KO (-activate|TARGET|move: Destiny Bond) are decision
        # 0018's DESTINY_BOND (feature 35, marked supported by G76) until the tracker folds it
        for line in ("|-singlemove|p1a: Staraptor|Destiny Bond", "|-activate|p2a: Gholdengo|move: Destiny Bond"):
            self.assertEqual(self.stop(line), "feature:DESTINY_BOND", line)

    def test_partial_trap_lines_fold_in_the_engines_forms_only(self):
        # Step G90 (decision 0060): the start (-activate|T|move: M|[of] S), the residual damage (-damage|T|hp|[from] move: M|
        # [partiallytrapped]) and the end (-end|T|M|[partiallytrapped], with [silent] for the silent ends) of the six moves
        # of the engine; the tracker folds them (PARTIAL_TRAP and TRAP_ELAPSED). Every other form stops on its line.
        f = lines.FEATURES
        self.assertTrue(lines.SUPPORTED >> f["PARTIAL_TRAP"] & 1 and lines.SUPPORTED >> f["TRAP_ELAPSED"] & 1)  # 18 and 45
        for move in ("Bind", "Wrap", "Fire Spin", "Sand Tomb", "Infestation"):
            for line in (f"|-activate|p2a: Gholdengo|move: {move}|[of] p1a: Staraptor",
                         f"|-damage|p2a: Gholdengo|83/100|[from] move: {move}|[partiallytrapped]",
                         f"|-damage|p2a: Gholdengo|83/182|[from] move: {move}|[partiallytrapped]",
                         f"|-end|p2a: Gholdengo|move: {move}|[partiallytrapped]",
                         f"|-end|p2a: Gholdengo|{move}|[partiallytrapped]|[silent]",
                         f"|-end|p2a: Gholdengo|move: {move}|[partiallytrapped]|[silent]"):
                self.assertEqual(lines.check(line, self.view), "fold", line)
        # the moves the engine does not model keep their stop (Snap Trap stays unmarked, decision 0060 section 8), and so does
        # every other shape
        for line, reason in (
                ("|-activate|p2a: Gholdengo|move: Whirlpool|[of] p1a: Staraptor", "line:-activate move: Whirlpool"),
                ("|-activate|p2a: Gholdengo|move: Snap Trap|[of] p1a: Staraptor", "line:-activate move: Snap Trap"),
                ("|-damage|p2a: Gholdengo|83/100|[from] move: Snap Trap|[partiallytrapped]",
                 "line:-damage partiallytrapped"),
                ("|-activate|p2a: Gholdengo|move: Magma Storm|[of] p1a: Staraptor", "line:-activate move: Magma Storm"),
                ("|-activate|p2a: Gholdengo|move: Bind", "line:-activate move: Bind"),  # no source
                ("|-activate|p2a: Gholdengo|move: Bind|[of] p1a: Staraptor|[silent]", "line:-activate move: Bind"),
                ("|-activate|p2a: Gholdengo|Bind|[of] p1a: Staraptor", "line:-activate Bind"),  # no "move: "
                ("|-activate|p2a: Gholdengo|move: Bind|x|[of] p1a: Staraptor", "line:-activate move: Bind"),
                ("|-damage|p2a: Gholdengo|83/100|[partiallytrapped]", "line:-damage partiallytrapped"),
                ("|-damage|p2a: Gholdengo|83/100|[from] move: Bind", None),  # a plain damage line is the converter's
                ("|-damage|p2a: Gholdengo|83/100|[from] move: Bind|[of] p1a: Staraptor|[partiallytrapped]",
                 "line:-damage partiallytrapped"),
                ("|-damage|p2a: Gholdengo|83/100|[from] move: Whirlpool|[partiallytrapped]",
                 "line:-damage partiallytrapped"),
                ("|-damage|p2a: Gholdengo|83/100|[from] item: Leftovers|[partiallytrapped]",
                 "line:-damage partiallytrapped"),
                ("|-end|p2a: Gholdengo|move: Whirlpool|[partiallytrapped]", "line:-end move: Whirlpool"),
                ("|-end|p2a: Gholdengo|move: Bind|[partiallytrapped]|[silent]|[of] p1a: Staraptor",
                 "line:-end move: Bind"),
                ("|-end|p2a: Gholdengo|move: Bind|[partiallytrapped]|[from] x", "line:-end move: Bind"),
                ("|-end|p2a: Gholdengo|move: Bind|[silent]", "line:-end move: Bind"),  # no marker
                ("|-end|p2a: Gholdengo|move: Bind|[partiallytrapped]|[partiallytrapped]", "line:-end move: Bind")):
            if reason is None:
                self.assertEqual(lines.check(line, self.view), "fold", line)
            else:
                self.assertEqual(self.stop(line), reason, line)

    def test_drag_folds(self):
        # Step G46: a forced switch brings a member in as a switch does (the tracker folds it as one, or stops)
        self.assertEqual(lines.check("|drag|p2a: Gholdengo|Gholdengo, L50|100/100", self.view), "fold")
        self.assertEqual(lines.check("|drag|p1a: Staraptor|Staraptor, L50, F|100/100", self.view), "fold")

    def test_unknown_lines_stop(self):
        self.assertEqual(self.stop("|-sethp|p1a: Staraptor|50/100"), "line:-sethp")
        self.assertEqual(self.stop("|move|p1a: Staraptor|Shed Tail|p1a: Staraptor"), "line:move Shed Tail")
        # Step G74 (decision 0042): Baton Pass is folded, its copy rides on the SWITCH event of the receiver
        self.assertEqual(lines.check("|move|p1a: Staraptor|Baton Pass|p1a: Staraptor", self.view), "fold")
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
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|move: Rage Powder", self.view), "fold")  # folded
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Quick Guard", self.view), "turn:QUICK_GUARD")
        self.assertEqual(lines.check("|-singleturn|p1a: Staraptor|Wide Guard", self.view), "fold")  # folded

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
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Wide Guard", self.view), "fold")  # folded
        self.assertEqual(lines.check("|-activate|p1a: Staraptor|move: Quick Guard", self.view), "turn:QUICK_GUARD")
        self.assertEqual(lines.check("|-activate|p2a: Gholdengo|ability: Storm Drain", self.view), "fold")

    def test_features_from_the_header(self):
        self.assertEqual(lines.FEATURES["WEATHER_SAND"], 0)
        self.assertEqual(lines.FEATURES["RAGE_POWDER"], 39)
        self.assertEqual(lines.FEATURES["MOVE_FAILED"], 41)
        self.assertEqual(lines.FEATURES["TRANSFORM"], 42)
        # tail revision 4: ROOST 40, MOVE_FAILED 41; 0028: TRANSFORM 42; 0050: the five reserve families 59 to 63
        # and 45 TRAP_ELAPSED (lane A, G90, decision 0060): one feature of its own inside the lane range
        self.assertEqual(len(lines.FEATURES), 43 + 1 + 5)
        self.assertEqual([lines.FEATURES[n] for n in ("RESERVE_VOLATILES", "VOLATILES2", "RESERVE_GUARDS",
                                                      "SIDE_CONDITIONS", "FIELD_FLAGS")], [59, 60, 61, 62, 63])

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
        # C comments between the terms (G76 writes one per feature) are no part of the expression
        source = ("static const dfi_support dfi_support = {\n"
                  "    .view_ext_features = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) | /* G8, a, b */\n"
                  "                         /* Step G76: Destiny Bond (bit 35, public: * its line). */\n"
                  "                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND), // last\n};\n")
        self.assertEqual(lines.extract_supported(source), 1 << f["THROAT_CHOP"] | 1 << f["DESTINY_BOND"])

    def test_a_feature_the_tracker_does_not_fold_stops(self):
        # the library may support a feature (G60: Substitute), but its view-extension field stays empty until the
        # tracker folds it: the line still stops the perspective
        self.assertEqual(lines.SUPPORTED & ~lines.TRACKER_FOLDS, 0)
        self.assertTrue(lines.LIBRARY_SUPPORTED >> lines.FEATURES["SUBSTITUTE"] & 1)
        self.assertEqual(self.stop("|-start|p1a: Staraptor|Substitute"), "feature:SUBSTITUTE")
        # a folded one: Throat Chop's [silent] lines (the tracker sets and clears the presence bit)
        self.assertEqual(lines.check("|-start|p1a: Staraptor|Throat Chop|[silent]", self.view), "fold")
        self.assertEqual(lines.check("|-end|p1a: Staraptor|Throat Chop|[silent]", self.view), "fold")
        # the base-value features fold (BC spec section 5): Sand and Snow, which the library supports (#124), and Tox
        f = lines.FEATURES
        self.assertTrue(lines.LIBRARY_SUPPORTED >> f["WEATHER_SAND"] & 1 and lines.LIBRARY_SUPPORTED >> f["WEATHER_SNOW"] & 1)
        self.assertEqual(lines.check("|-weather|Sandstorm|[from] ability: Sand Stream|[of] p2a: Gholdengo", self.view), "fold")
        self.assertEqual(lines.check("|-weather|Snowscape|[from] ability: Snow Warning|[of] p2a: Gholdengo", self.view),
                         "fold")

    def test_every_fold_names_its_view_extension_fields(self):
        # the base-value folds have no record field, every view-extension fold has some (tracker.EXT_FIELDS: what the
        # tracker writes and what test_replay compares); restrict_ext keeps only those fields and the header
        import numpy as np
        from duoforge import _layout
        from duoforge_live import tracker
        for name, bit in lines.FEATURES.items():
            if lines.TRACKER_FOLDS >> bit & 1:
                self.assertEqual(bool(tracker.EXT_FIELDS[name]), bool(lines.EXT_FOLDS >> bit & 1), name)
        self.assertEqual(lines.BASE_FOLDS & lines.EXT_FOLDS, 0)
        full = np.frombuffer(bytes(range(192)), dtype=_layout.OBSERVATION_EXT)[0]
        cut = tracker.restrict_ext(full, 0)
        self.assertEqual((int(cut["revision"]), int(cut["epoch"])), (int(full["revision"]), int(full["epoch"])))
        self.assertEqual(cut["sides"].tobytes(), bytes(_layout.SIDE_EXT.itemsize * 2))
        chop = tracker.restrict_ext(full, 1 << lines.FEATURES["THROAT_CHOP"])
        self.assertEqual(chop["sides"]["positions"]["volatiles"].tolist(),
                         (full["sides"]["positions"]["volatiles"] & tracker.EXT_THROAT_CHOP).tolist())

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

    def test_an_emergency_exit_in_the_switch_phase_is_a_pivot(self):
        # g37_exit: a member switched in at the TURN point takes the hazards to half and leaves by Emergency Exit before
        # any action of the turn; the switch into its position answers a PIVOT, it is no TURN action
        from duoforge_replay import points
        log = self._HEAD + ["|switch|p2a: Golisopod|Golisopod, L50|100/100",
                            "|-damage|p2a: Golisopod|40/100|[from] Stealth Rock",
                            "|-activate|p2a: Golisopod|ability: Emergency Exit",
                            "|switch|p2a: Milotic|Milotic, L50|100/100",
                            "|move|p1a: Dragalge|Protect|p1a: Dragalge", "|upkeep", "|turn|2"]
        found = [(pt.boundary, pt.run) for pt in points.find(log)]
        self.assertEqual(found[2:], [(points.PIVOT, (2,)), (points.TURN, ())])


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

    def test_dragon_darts_line_may_name_the_other_foe(self):
        # data/moves.ts dragondarts smartTarget (step G78): when the chosen foe cannot be hit (here it protects), both
        # darts go to its ally and the move line names the ally, so the line does not name the chosen target
        mv = self.tables["MOVE"]
        moves = ([mv["BRAVEBIRD"], mv["DRAGONDARTS"], mv["TAILWIND"], mv["PROTECT"]], self.moves[1])
        log = ["|move|p2a: Foe|Protect|p2a: Foe", "|-singleturn|p2a: Foe|Protect",
               "|move|p1a: Staraptor|Dragon Darts|p2b: Foe2"]
        point = self.P.Point(1, 0, self.P.TURN, (), len(log))
        got = self.L.turn_label(log, point, 0, self.lists, moves, lambda details: self.species[details.split(",")[0]],
                                self.tables, len(log))
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)
        self.assertTrue({2, 3} <= {o.target for o in self.options_of(got, 0)})  # the chosen p2a is in the label
        self.assertEqual({(o.move_slot, o.mega) for o in self.options_of(got, 0)}, {(1, 0)})

    def test_faint_earlier_makes_the_target_unknown(self):
        got = self.label(["|move|p1b: Gholdengo|Make It Rain|p2a: Foe|[spread] p2a,p2b", "|faint|p2a: Foe",
                          "|move|p1a: Staraptor|Brave Bird|p2b: Foe2"])
        self.assertEqual(got.reasons[0], self.L.TARGET_UNKNOWN)

    def _struggle_lists(self):
        """Slot 0 with Struggle only (every move barred) and the reserves; slot 1 as in setUpClass."""
        request = {"side": {"id": "p1", "pokemon": [
            {"ident": "p1: a", "active": True, "condition": "100/100", "moves": ["bravebird", "closecombat", "tailwind", "protect"]},
            {"ident": "p1: b", "active": True, "condition": "100/100", "moves": ["makeitrain"]},
            {"ident": "p1: c", "active": False, "condition": "100/100", "moves": []},
            {"ident": "p1: d", "active": False, "condition": "100/100", "moves": []}]},
            "active": [{"moves": [{"id": "struggle"}]},
                       {"moves": [{"id": "makeitrain", "pp": 8, "target": "allAdjacentFoes", "disabled": False}]}]}
        return self.O.slot_options(request, 0, {"p1: a": 1, "p1: b": 0, "p1: c": 2, "p1: d": 3}, {})

    def _cant_label(self, line, barred):
        log = [line]
        point = self.P.Point(1, 0, self.P.TURN, (), len(log))
        return self.L.turn_label(log, point, 0, self._struggle_lists(), self.moves,
                                 lambda details: self.species[details.split(",")[0]], self.tables, len(log),
                                 barred=barred)

    def test_a_disabled_move_named_by_cant_is_every_move_option_only_when_the_view_bars_it(self):
        # g27_disable_lock: the slot's request was Struggle (its move Disabled), and cant|X|Disable|Move names the barred
        # move, which is no option: every move option (here Struggle), MOVE_HIDDEN, but only when the tracker's view bars
        # that slot (disable_slot or the Choice lock); otherwise the named move is no option for a reason the view does
        # not know, and the label stays the empty set (bc_data refuses it as a labeler bug), never a silent fallback
        lists = self._struggle_lists()
        got = self._cant_label("|cant|p1a: Staraptor|Disable|Brave Bird", ({0}, set()))
        self.assertEqual(got.reasons[0], self.L.MOVE_HIDDEN)
        self.assertEqual([(lists[0][i].kind, lists[0][i].move_slot) for i in range(len(lists[0]))
                          if got.slots[0] >> i & 1], [(self.O.MOVE, self.O.STRUGGLE)])
        for line, barred in (("|cant|p1a: Staraptor|Disable|Brave Bird", (set(), set())),  # the view bars nothing
                             ("|cant|p1a: Staraptor|Disable|Brave Bird", ({1}, set())),  # it bars another slot
                             ("|cant|p1a: Staraptor|move: Taunt|Brave Bird", ({0}, set()))):  # another reason
            got = self._cant_label(line, barred)
            self.assertEqual(got.slots[0], 0, (line, barred))

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

    def test_encore_before_the_own_move_hides_the_choice(self):
        # an Encore that starts on the position before its move line replaced the chosen move: every move option
        # (the Encored one too, which a player who chose it sees unchanged), no switch
        got = self.label(["|move|p2a: Foe|Encore|p1a: Staraptor", "|-start|p1a: Staraptor|Encore",
                          "|move|p1a: Staraptor|Close Combat|p2a: Foe"])
        self.assertEqual(got.reasons[0], self.L.MOVE_HIDDEN)
        opts = self.options_of(got, 0)
        self.assertEqual({o.kind for o in opts}, {self.O.MOVE})
        self.assertEqual({o.move_slot for o in opts}, {0, 1, 2, 3})

    def test_encore_after_the_own_move_changes_nothing(self):
        # only the lines before the position's own move line can replace its choice
        got = self.label(["|move|p1a: Staraptor|Close Combat|p2a: Foe", "|move|p2a: Foe|Encore|p1a: Staraptor",
                          "|-start|p1a: Staraptor|Encore"])
        self.assertEqual(got.reasons[0], self.L.EXACT)

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


class RevivalLabelTest(unittest.TestCase):
    """The revived member of a Revival Blessing label (step G52). Its -heal line names it by its nickname only
    ("|-heal|p1: <nickname>|..."): the member is the one that switched in under that name before. Made-up logs after
    the eight patterns of the 2026-10-10 replay run, which stopped with a ValueError (the nickname read as a forme)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import options
        from duoforge_replay import labels, points
        cls.L, cls.P, cls.O = labels, points, options
        revive = [options.Option(options.REVIVE, 0, 0, 0, r, f"revive {r}") for r in (2, 3)]
        # slot 0 is not asked; slot 1 (p1b) used Revival Blessing and chooses among the fainted reserves 2 and 3
        cls.lists = ([options.Option(options.NONE, 0, 0, 0, 0, "pass")],
                     revive + [options.Option(options.PASS, 0, 0, 0, 0, "pass")])
        # the stand-in of Context.member_of: species -> roster index; a nickname or a base forme the roster lacks fails
        cls.roster = {"Milotic": 3, "Floette-Eternal": 2, "Rillaboom": 2}

    def member_of(self, details):
        return self.roster[details.split(",")[0]]

    def label(self, before, name):
        log = before + ["|move|p1b: Pawmot|Revival Blessing|p1b: Pawmot", f"|-heal|p1: {name}|50/100|[from] move: Revival Blessing"]
        point = self.P.Point(1, len(before) + 1, self.P.PIVOT, (1,), len(log), True)
        return self.L.switch_label(log, point, 0, self.lists, self.member_of, len(log))

    def revived(self, label):
        [i] = [i for i in range(len(self.lists[1])) if label.slots[1] >> i & 1]
        return self.lists[1][i]

    def assert_revives(self, before, name, reserve):
        got = self.label(before, name)
        self.assertEqual(got.reasons[1], self.L.EXACT)
        option = self.revived(got)
        self.assertEqual((option.kind, option.reserve), (self.O.REVIVE, reserve))

    def test_a_plain_nickname(self):  # "Alex", "Darlen", "Dallas", "Babahagen", "Unbehagen"
        self.assert_revives(["|switch|p1a: Nick|Milotic, L50, F|100/100", "|faint|p1a: Nick"], "Nick", 3)

    def test_a_nickname_with_spaces(self):  # "sorry for doubting"
        self.assert_revives(["|switch|p1a: three short words|Milotic, L50, F|100/100", "|faint|p1a: three short words"],
                            "three short words", 3)

    def test_a_nickname_that_is_a_base_forme_the_tables_lack(self):  # "Floette" for Floette-Eternal
        self.assert_revives(["|switch|p1a: Floette|Floette-Eternal, L50, F|100/100", "|faint|p1a: Floette"], "Floette", 2)

    def test_no_nickname(self):
        self.assert_revives(["|switch|p1a: Milotic|Milotic, L50, F|100/100", "|faint|p1a: Milotic"], "Milotic", 3)

    def test_the_foe_side_does_not_count(self):
        self.assert_revives(["|switch|p2a: Nick|Rillaboom, L50, M|100/100", "|switch|p1a: Nick|Milotic, L50, F|100/100",
                             "|faint|p1a: Nick"], "Nick", 3)

    def test_a_name_that_never_switched_in_is_a_counted_skip(self):
        with self.assertRaises(self.P.Skip) as cm:
            self.label(["|switch|p1a: Other|Milotic, L50, F|100/100"], "Nick")
        self.assertEqual(cm.exception.reason, "skip:revive-unseen")

    def test_a_name_two_members_had_is_a_counted_skip(self):
        with self.assertRaises(self.P.Skip) as cm:
            self.label(["|switch|p1a: Nick|Milotic, L50, F|100/100", "|switch|p1a: Nick|Rillaboom, L50, M|100/100",
                        "|faint|p1a: Nick"], "Nick")
        self.assertEqual(cm.exception.reason, "skip:revive-ambiguous")



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

    def test_turn_coverage_of_a_clean_game_is_every_turn(self):
        # turns.total: the game's turns per perspective; turns.kept: the turns complete before the perspective's stop
        result = self.run_game(self.log)
        self.assertEqual((result.counters["turns.total"], result.counters["turns.kept"]),
                         (2 * result.record.turns, 2 * result.record.turns))

    def test_turn_coverage_ends_at_the_stop(self):
        result = self.run_game(self.insert_after("|turn|2", "|-start|p2a: Politoed|Substitute"))
        self.assertEqual(result.counters["turns.total"], 2 * result.record.turns)
        self.assertEqual(result.counters["turns.kept"], 2 * 1)  # turn 1 complete, turn 2 stopped
        self.assertEqual(result.counters["games.both_kept"], 0)

    def test_a_match_counts_when_both_perspectives_run_to_the_end(self):
        self.assertEqual(self.run_game(self.log).counters["games.both_kept"], 1)
        # a stop in one perspective is enough: the Rage Powder before p1's own pivot stops p1 only
        one = self.run_game(self.insert_after("|turn|3", "|-start|p2a: Politoed|Rage Powder"))
        self.assertEqual(one.counters["games.both_kept"], 1 if one.counters["perspectives.kept"] == 2 else 0)

    def test_a_feature_stops_after_turn_two(self):
        # a feature the tracker does not fold (Substitute; Sand folds since the BC PR) ends both perspectives there:
        # the points before it are written, the later ones dropped
        clean = self.run_game(self.log)
        result = self.run_game(self.insert_after("|turn|2", "|-start|p2a: Politoed|Substitute"))
        self.assertEqual(result.counters["perspectives.stopped.feature:SUBSTITUTE"], 2)
        self.assertGreater(result.counters["points.dropped.feature:SUBSTITUTE"], 0)
        turn2 = [int(r.observation["epoch"]) for r in clean.rows if int(r.observation["turn"]) == 2
                 and r.observation["boundary_kind"] == 2]
        self.assertTrue(all(int(r.observation["epoch"]) <= max(turn2) for r in result.rows))
        self.assertLess(len(result.rows), len(clean.rows))

    def test_illusion_sheet_skips(self):
        lines = [line.replace("|Defiant|", "|Illusion|", 1) if line.startswith("|showteam|p1|") else line
                 for line in self.log]
        self.assertEqual(self.skip_reason(lines), "skip:illusion")

    def test_two_sheets_of_one_side_are_a_refusal_of_their_own(self):
        # review of #331: two |showteam| lines of the same side pass source.select (two lines) but are no pair of
        # sheets; the game is refused under its own reason, not counted as a game without sheets
        lines = [line.replace("|showteam|p2|", "|showteam|p1|", 1) for line in self.log]
        self.assertEqual(self.skip_reason(lines), "skip:sheets-one-side")

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

    def test_turn_scoped_feature_without_pivot_passes(self):
        # a single-turn feature the tracker does not fold (Quick Guard; Rage Powder folds since its view-extension fold)
        result = self.run_game(self.insert_after("|turn|3", "|-singleturn|p2a: Politoed|Quick Guard"))
        self.assertEqual(result.counters["turn-scoped.QUICK_GUARD"], 2)
        self.assertEqual(result.counters["perspectives.kept"], 2)

    def test_turn_scoped_feature_before_an_own_pivot_stops(self):
        # turn 2: p1's Parting Shot switch is a PIVOT point of side 0
        result = self.run_game(self.insert_after("|turn|2", "|-singleturn|p2a: Politoed|Quick Guard"))
        self.assertEqual(result.counters["perspectives.stopped.feature:QUICK_GUARD"], 1)
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
        self.assertIn(("WIDE_GUARD", 1), tracker._guards)  # the side's guard (the view extension's guard_flags)
        tracker.feed(["|move|p1a: Indeedee|Feint|p2b: Farigiraf", "|-activate|p2b: Farigiraf|move: Feint"])
        self.assertEqual((tracker._positions[1][1].chain, tracker._positions[1][1].stall), (0, 0))
        self.assertEqual(tracker._positions[1][0].chain, 1)
        self.assertNotIn(("WIDE_GUARD", 1), tracker._guards)

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
        from duoforge_live.tracker import SWITCH_EMERGENCY_EXIT
        self.assertEqual(tracker._positions[1][0].flag, SWITCH_EMERGENCY_EXIT)  # the reason (the record's flag)

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
        # the converter decides which -fail forms it reads (main reads "heal" since G8, Substitute's since G60); one it
        # cannot read (Shed Tail's, data/moves.ts:16181) is a named stop, never an internal error
        lines = self.insert_after("|turn|3", "|-fail|p2a: Politoed|move: Shed Tail|[weak]")
        result = self.run_game(lines)
        stops = [k for k in result.counters if k.startswith("perspectives.stopped.converter:untyped -fail")]
        self.assertEqual(sum(result.counters[k] for k in stops), 2, result.counters)

    def test_a_drop_kept_by_another_ability_stops(self):
        # -fail|X|unboost from an ability the holder does not have (Politoed: Drizzle) is no form the fold knows
        lines = self.insert_after("|turn|3", "|-fail|p2a: Politoed|unboost|[from] ability: Clear Body|[of] p2a: Politoed")
        result = self.run_game(lines)
        self.assertEqual(result.counters["perspectives.stopped.line:-fail unboost"], 2, result.counters)

    def test_an_encored_position_offers_only_its_encored_move(self):
        # Incineroar used Fake Out on turn 1; an Encore before the turn's upkeep holds it to Fake Out on turn 2
        lines = self.insert_after("|move|p2b: Farigiraf|Psychic|p1a: Indeedee", "|-start|p1b: Incineroar|Encore")
        result = self.run_game(lines)
        rows = [r for r in result.rows if r.side == 0 and int(r.observation["turn"]) == 2]
        self.assertTrue(rows, result.counters)
        domain = rows[0].domain
        slots = [domain["slots"][1][i] for i in range(int(domain["slot_count"][1]))]
        from duoforge_live import options
        moves = {int(o["move_slot"]) for o in slots if int(o["kind"]) == 1} - {options.STRUGGLE}
        self.assertEqual(len(moves), 1, moves)  # Fake Out only (with its targets); Struggle stays, as everywhere
        self.assertTrue(any(int(o["kind"]) == 2 for o in slots))  # it can still switch
        self.assertGreater(int(rows[0].ext["sides"][0]["positions"][1]["encore_slot"]), 0)

    def test_every_row_carries_its_extension_record(self):
        from duoforge import _layout
        result = self.run_game(self.log)
        self.assertTrue(result.rows)
        for row in result.rows:
            self.assertEqual(row.ext.dtype, _layout.OBSERVATION_EXT)
            self.assertEqual(int(row.ext["epoch"]), int(row.observation["epoch"]))
            self.assertEqual(int(row.ext["player"]), row.side)

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

    def test_the_funnel_per_format_adds_up_to_the_totals(self):
        from duoforge_replay import funnel
        c = self.build("funnel")
        report = funnel.report(c)
        self.assertEqual(sorted(report), ["gen9championsvgc2026regmcbo3", "gen9ou"])
        for format_id, f in report.items():
            self.assertEqual(f["read"], sum(f["skipped"].values()) + f["internal"] + f["processed"], format_id)
            self.assertEqual(f["perspectives"]["kept"] + sum(f["perspectives"]["stopped"].values()),
                             2 * f["processed"], format_id)
            self.assertEqual(f["with_sheets"], f["read"] - f["skipped"].get("skip:format", 0)
                             - f["skipped"].get("skip:sheets", 0), format_id)
        self.assertEqual(report["gen9ou"]["skipped"], {"skip:format": 1})
        self.assertEqual(report["gen9championsvgc2026regmcbo3"]["processed"], 3)
        total = lambda key: sum(f[key] for f in report.values())  # noqa: E731
        self.assertEqual(total("read"), c["games.read"])
        self.assertEqual(total("processed"), c["games.processed"])
        self.assertEqual(total("rows"), c["points.written"])
        self.assertEqual(sum(f["perspectives"]["kept"] for f in report.values()), c["perspectives.kept"])
        for key, n in c.items():
            if key.startswith("games.skipped."):
                reason = key[len("games.skipped."):]
                self.assertEqual(sum(f["skipped"].get(reason, 0) for f in report.values()), n, reason)
        text = funnel.text(report)
        for format_id in report:
            self.assertIn(format_id, text)

    def test_the_funnel_counts_turns(self):
        from duoforge_replay import funnel
        c = self.build("turns")
        f = funnel.report(c)["gen9championsvgc2026regmcbo3"]
        self.assertEqual(f["turns"], {"total": c["turns.total"], "kept": c["turns.kept"], "refused": 0})
        self.assertGreater(f["turns"]["total"], 0)
        text = funnel.text(funnel.report(c))
        self.assertIn("turns without a stop, of all its games taken", text)
        self.assertIn("turns without a stop, of the games set up", text)
        self.assertEqual(f["both_kept"], c["games.both_kept"])
        self.assertIn("matches with both perspectives to the end", text)

    def test_the_funnel_command_reads_a_dataset(self):
        import contextlib
        import io
        from duoforge_replay import __main__ as cli
        self.build("cli")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["funnel", str(self.tmp / "cli")]), 0)
        self.assertIn("gen9championsvgc2026regmcbo3", out.getvalue())
        self.assertIn("rows", out.getvalue())

    def test_the_funnel_counts_refused_games_and_internal_errors(self):
        # review of #331: the funnel stages of game.Skip and of an internal error, each in a build of its own
        import json
        from duoforge_replay import funnel
        lines = self.log.split(chr(10))
        i = next(i for i, line in enumerate(lines) if line.startswith("|showteam|p1|"))
        head, packed = lines[i].split("|", 3)[:3], lines[i].split("|", 3)[3]
        first = packed.split("]")[0].split("|")
        first[1] = "Fakemon"  # a species the tables lack: name:FORME Fakemon
        lines[i] = "|".join(head + ["]".join(["|".join(first)] + packed.split("]")[1:])])
        mixed = self.tmp / "mixed.jsonl"
        with open(mixed, "w", encoding="utf-8", newline=chr(10)) as f:
            fake = chr(10).join(lines)
            f.write(json.dumps({"id": "fake", "formatid": "gen9championsvgc2026regmc", "log": fake}) + chr(10))
            f.write(json.dumps({"id": "ok", "formatid": "gen9championsvgc2026regmc", "log": self.log}) + chr(10))
        from duoforge_replay import build
        c = build.build([mixed], self.prior_path, self.tmp / "refused", unit_lines=2, stats_factory=stats_factory,
                        log=lambda _: None)
        f = funnel.report(c)["gen9championsvgc2026regmc"]
        self.assertEqual((f["read"], f["skipped"], f["internal"], f["processed"]),
                         (2, {"name:FORME Fakemon": 1}, 0, 1))
        # a refused game's turns stay in the denominator of the turn coverage, both perspectives, none kept
        turns = max(int(line.split("|")[2]) for line in lines if line.startswith("|turn|"))
        self.assertEqual(f["turns"]["refused"], 2 * turns)
        c = build.build([self.source], self.prior_path, self.tmp / "internal", unit_lines=2,
                        stats_factory=broken_stats_factory, log=lambda _: None)
        f = funnel.report(c)["gen9championsvgc2026regmcbo3"]
        self.assertEqual((f["read"], f["internal"], f["processed"], f["rows"]), (3, 3, 0, 0))
        self.assertGreater(f["turns"]["refused"], 0)  # an internal error's turns too
        self.assertEqual(f["internal"], c["internal:RuntimeError"])

    def test_the_funnel_command_refuses_a_dataset_without_funnel(self):
        # review of #331: a dataset built before the funnel has none; an empty report would read as "no games"
        import contextlib
        import io
        import json
        from duoforge_replay import __main__ as cli
        old = self.tmp / "old"
        old.mkdir()
        (old / "counters.json").write_text(json.dumps({"games.read": 3, "games.processed": 3}), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["funnel", str(old)]), 2)
        self.assertIn("no funnel", err.getvalue())

    def test_reg_ma_is_excluded(self):
        # owner, 2026-10-10: Reg M-A ran under another mechanics era (Showdown before Champions 1.1.0); no prefix that
        # takes its games is a build
        from duoforge_replay import build
        for prefix in ("gen9championsvgc2026regma", "gen9championsvgc2026regmabo3", "gen9championsvgc2026", "gen9"):
            with self.subTest(prefix), self.assertRaisesRegex(ValueError, "Reg M-A"):
                build.build([self.source], self.prior_path, self.tmp / "ma", unit_lines=2, stats_factory=stats_factory,
                            log=lambda _: None, format_prefix=[prefix])
        self.assertFalse((self.tmp / "ma").exists())

    def test_the_funnel_names_the_excluded_regulation(self):
        from duoforge_replay import funnel
        report = funnel.report({"funnel.gen9championsvgc2026regma.read": 5,
                                "funnel.gen9championsvgc2026regma.skipped.skip:format": 5})
        self.assertIn("excluded: other mechanics era (owner, 2026-10-10)", funnel.text(report))

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
        from duoforge_replay import funnel
        report = funnel.report(counters)  # the unread row group counts per format too
        self.assertEqual({k: (f["read"], f["skipped"]) for k, f in report.items()},
                         {"gen9ou": (2, {"skip:format": 2}), "gen9championsvgc2026regmc": (1, {"skip:sheets": 1})})

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
        self.assertEqual(counters["funnel.gen9championsvgc2026regmcbo3.read"], 2)
        self.assertEqual(counters["funnel.gen9championsvgc2026regmcbo3.skipped.skip:sheets"], 1)
        self.assertEqual(counters["funnel.gen9ou.skipped.skip:format"], 1)


class PickHypothesesTest(unittest.TestCase):
    """Pick hypotheses (M11 pick hypotheses spec): a perspective whose back picks the log does not show is folded once
    per pick tuple the log allows, marked, and stopped at the earliest stop of any of them."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import teams
        from duoforge_replay import game, hindsight, prior
        cls.G, cls.H = game, hindsight
        cls.data = data.load(kind="pool")
        log = FIXTURE.read_text(encoding="utf-8").split(chr(10))
        cut = next(i for i, line in enumerate(log) if line.startswith("|switch|p1a: Salamence|"))
        cls.short = log[:cut] + ["|win|p2"]  # p1's Salamence never enters: three of p1's four brought are seen
        cls.full = log
        cls.sheets = tuple(teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|"))
        for s in cls.sheets[0] + cls.sheets[1]:
            s["species"] = cls.data.canonical(s["species"])
        cls.names = [s["species"] for s in cls.sheets[0]]
        cls.prior = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})

    def index(self, species):
        return self.names.index(species)

    def fold(self, log, **kw):
        return self.G.process("fixture-hyp", "gen9championsvgc2026regmcbo3", chr(10).join(log), self.data, self.prior,
                              _Stats(), **kw)

    def test_the_hypotheses_are_the_pick_tuples_the_log_allows(self):
        hyps = self.H.pick_hypotheses(self.short, 0, self.data, self.sheets)
        leads = (self.index("Kingambit"), self.index("Incineroar"))
        seen = self.index("Indeedee-F")
        unseen = {self.index(n) for n in ("Salamence", "Basculegion", "Sneasler")}
        self.assertEqual(len(hyps), 3)
        for h in hyps:
            self.assertEqual(h[:2], leads)
            self.assertIn(seen, h[2:])
            self.assertEqual(len(set(h[2:]) - {seen}), 1)
        self.assertEqual({next(iter(set(h[2:]) - {seen})) for h in hyps}, unseen)
        cut = next(i for i, line in enumerate(self.short) if line.startswith("|switch|p1a: Indeedee"))
        two = self.H.pick_hypotheses(self.short[:cut] + ["|win|p2"], 0, self.data, self.sheets)
        self.assertEqual(len(two), 6)  # only the leads seen: two of the four other members
        self.assertEqual({h[:2] for h in two}, {leads})
        self.assertEqual(len({frozenset(h[2:]) for h in two}), 6)
        # with the four brought known there is one hypothesis: the picks themselves
        self.assertEqual(self.H.pick_hypotheses(self.full, 0, self.data, self.sheets),
                         [self.H.hindsight_picks(self.full, 0, self.data, self.sheets)])

    def test_each_hypothesis_gives_its_marked_rows_and_the_team_row_once(self):
        from duoforge_replay import points
        result = self.fold(self.short, pick_hypotheses=True)
        own = [r for r in result.rows if r.side == 0]
        team = [r for r in own if int(r.observation["boundary_kind"]) == points.TEAM_SELECTION]
        self.assertEqual([(r.picks_hypotheses, r.hypothesis) for r in team], [(1, 0)])
        turns = [r for r in own if int(r.observation["boundary_kind"]) != points.TEAM_SELECTION]
        self.assertEqual({r.picks_hypotheses for r in turns}, {3})
        self.assertEqual({r.hypothesis for r in turns}, {0, 1, 2})
        by_hyp = collections.Counter(r.hypothesis for r in turns)
        self.assertEqual(len(set(by_hyp.values())), 1)  # a common stop: every hypothesis has the same points
        hyps = self.H.pick_hypotheses(self.short, 0, self.data, self.sheets)
        for r in turns:  # the own bench follows its hypothesis
            order = [int(x) for x in r.observation["sides"][0]["brought_order"][:4]]
            self.assertEqual(sorted(order), sorted(hyps[r.hypothesis]))

    def test_the_headline_counters_do_not_change(self):
        plain, hyp = self.fold(self.short), self.fold(self.short, pick_hypotheses=True)
        for key in ("perspectives.kept", "perspectives.stopped.picks-incomplete", "turns.kept", "turns.total"):
            self.assertEqual(hyp.counters[key], plain.counters[key], key)
        self.assertGreater(hyp.counters["turns.hypotheses"], 0)
        self.assertEqual(hyp.counters["perspectives.hypotheses_kept"]
                         + sum(v for k, v in hyp.counters.items() if k.startswith("perspectives.hypotheses_stopped.")),
                         plain.counters["perspectives.stopped.picks-incomplete"])
        self.assertEqual(hyp.counters["points.hypotheses"], sum(1 for r in hyp.rows if r.picks_hypotheses > 1))

    def test_a_single_pick_tuple_makes_no_hypothesis_rows(self):
        # review: a sheet of four members leaves one pick tuple; its rows would pass for rows with known picks
        def without(line, names):
            packed = line.split("|", 3)[3]
            kept = [m for m in packed.split("]") if not set(m.split("|")[:2]) & set(names)]
            return "|".join(line.split("|", 3)[:3]) + "|" + "]".join(kept)
        log = [without(line, ("Basculegion", "Sneasler")) if line.startswith("|showteam|p1|") else line
               for line in self.short]
        plain, hyp = self.fold(log), self.fold(log, pick_hypotheses=True)
        self.assertEqual(plain.counters["perspectives.stopped.picks-incomplete"], 1)
        self.assertEqual(len(hyp.rows), len(plain.rows))
        self.assertEqual(hyp.counters["points.written"], plain.counters["points.written"])
        self.assertEqual(hyp.counters["perspectives.hypotheses_stopped.single-hypothesis"], 1)
        self.assertEqual(hyp.counters["points.hypotheses"], 0)

    def test_a_stop_in_one_hypothesis_ends_all_at_the_earliest_line(self):
        from duoforge_replay import points

        class Stop(Exception):
            def __init__(self, line, reason):
                self.line, self.reason = line, reason
        p = [points.Point(i, line, points.TURN, (), line + 1) for i, line in enumerate((10, 20, 30, 40))]
        runs = [([(q, "row") for q in p], None), ([(q, "row") for q in p[:2]], Stop(25, "feature:X")),
                ([(q, "row") for q in p[:3]], Stop(35, "feature:Y"))]
        kept, stop = self.G._common_stop(runs)
        self.assertEqual((stop.line, stop.reason), (25, "feature:X"))
        self.assertEqual([[q.line for q, _ in taken] for taken in kept], [[10, 20], [10, 20], [10, 20]])
        kept, stop = self.G._common_stop([([(q, "row") for q in p], None)] * 2)
        self.assertIsNone(stop)
        self.assertEqual([len(t) for t in kept], [4, 4])


class SplitTest(unittest.TestCase):
    """The player split of the Bo1 belief validation (M11 Bo1 spec section 6): no player in training and test."""

    def test_a_test_player_makes_a_test_game(self):
        from duoforge_replay import split
        self.assertTrue(split.is_test_player(40))
        self.assertFalse(split.is_test_player(41))
        self.assertEqual(split.of_game((40, 41)), "test")
        self.assertEqual(split.of_game((41, 40)), "test")
        self.assertEqual(split.of_game((41, 43)), "train")

    def test_players_of_hashes_the_two_player_lines(self):
        from duoforge_replay import game, split
        lines = ["|player|p1|Alice|1|1500", "|player|p2|Bob B|2|", "|player|p1|Alice|1|1500"]
        self.assertEqual(split.players_of(lines), (game._hash8("alice"), game._hash8("bobb")))
        with self.assertRaisesRegex(ValueError, "player"):
            split.players_of(["|player|p1|Alice|1|"])


P1_PREVIEW = ["Kingambit, L50, M", "Incineroar, L50, M", "Charizard, L50, M", "Rillaboom, L50, M",
              "Garchomp, L50, F", "Gholdengo, L50"]
P2_PREVIEW = ["Politoed, L50, M", "Farigiraf, L50, F", "Sneasler, L50, F", "Tyranitar, L50, M",
              "Sinistcha, L50", "Dragonite, L50, M"]


def facts_log(*body, p1=P1_PREVIEW, p2=P2_PREVIEW):
    """A made-up Bo1 log without sheets: preview, leads Kingambit "Gambit" and Incineroar "Roar" against Politoed
    "Frog" and Farigiraf "Giraffe", then the body."""
    return (["|player|p1|Alice|1|", "|player|p2|Bob|2|", "|gametype|doubles"]
            + [f"|poke|p1|{s}|" for s in p1] + [f"|poke|p2|{s}|" for s in p2]
            + ["|teampreview|4", "|start", "|switch|p1a: Gambit|Kingambit, L50, M|100/100",
               "|switch|p1b: Roar|Incineroar, L50, M|100/100", "|switch|p2a: Frog|Politoed, L50, M|100/100",
               "|switch|p2b: Giraffe|Farigiraf, L50, F|100/100", "|turn|1"] + list(body))


class FactsTest(unittest.TestCase):
    """What a log without sheets reveals of each member (M11 Bo1 spec section 3), on made-up logs."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import facts, points
        cls.F, cls.Skip = facts, points.Skip
        cls.data = data.load(kind="pool")

    def facts(self, *body, side=0, **kw):
        return self.F.side_facts(facts_log(*body, **kw), side, self.data)

    def skip(self, *body, **kw):
        with self.assertRaises(self.Skip) as cm:
            self.facts(*body, **kw)
        return cm.exception.reason

    def test_preview_species_and_gender(self):
        f = self.facts()
        self.assertEqual([m.species for m in f], ["Kingambit", "Incineroar", "Charizard", "Rillaboom", "Garchomp",
                                                  "Gholdengo"])
        self.assertEqual([m.gender for m in f], ["M", "M", "M", "M", "F", ""])
        self.assertEqual({m.moves for m in f}, {frozenset()})
        self.assertEqual({(m.item, m.ability) for m in f}, {(None, None)})

    def test_moves_by_nickname_and_no_called_moves(self):
        body = ["|move|p1a: Gambit|Kowtow Cleave|p2a: Frog", "|move|p1b: Roar|Fake Out|p2b: Giraffe",
                "|move|p1a: Gambit|Sucker Punch|p2a: Frog|[from]lockedmove",
                "|move|p1b: Roar|Protect|p1b: Roar|[from]move: Copycat",
                "|move|p1b: Roar|Taunt|p2a: Frog|[from] ability: Dancer",
                "|switch|p1a: Zard|Charizard, L50, M|100/100", "|move|p1a: Zard|Heat Wave|p2a: Frog|[spread] p2a,p2b",
                "|move|p2a: Frog|Weather Ball|p1a: Zard|[from]move: Instruct"]
        f = self.facts(*body)
        self.assertEqual(f[0].moves, frozenset({"Kowtow Cleave", "Sucker Punch"}))
        self.assertEqual(f[1].moves, frozenset({"Fake Out"}))
        self.assertEqual(f[2].moves, frozenset({"Heat Wave"}))
        self.assertEqual(self.facts(*body, side=1)[0].moves, frozenset({"Weather Ball"}))  # Instruct: its own move

    def test_ally_switch_swaps_the_occupants(self):
        # review C1: after |swap| both positions name the other member
        f = self.facts("|move|p1b: Roar|Ally Switch|p1b: Roar", "|swap|p1b: Roar|0|[from] move: Ally Switch",
                       "|move|p1a: Roar|Fake Out|p2a: Frog", "|move|p1b: Gambit|Kowtow Cleave|p2a: Frog",
                       "|-enditem|p1a: Roar|Sitrus Berry|[eat]")
        self.assertEqual(f[0].moves, frozenset({"Kowtow Cleave"}))
        self.assertEqual(f[1].moves, frozenset({"Ally Switch", "Fake Out"}))
        self.assertEqual((f[0].item, f[1].item), (None, "Sitrus Berry"))

    def test_an_absorbing_heal_names_no_attacker_and_bug_bite_no_biter(self):
        # review I1: a -heal [from] ability names the attacker as [of] (Volt Absorb); a Bug Bite's heal names the
        # victim's berry on the biter
        f = self.facts("|move|p1a: Gambit|Kowtow Cleave|p2a: Frog",
                       "|-heal|p2a: Frog|100/100|[from] ability: Volt Absorb|[of] p1a: Gambit")
        self.assertEqual(f[0].ability, None)
        bite = ["|-enditem|p2a: Frog|Sitrus Berry|[from] stealeat|[move] Bug Bite|[of] p1a: Gambit",
                "|-heal|p1a: Gambit|100/100|[from] item: Sitrus Berry"]
        self.assertIsNone(self.facts(*bite)[0].item)
        self.assertEqual(self.facts(*bite, side=1)[0].item, "Sitrus Berry")

    def test_struggle_and_a_mimicked_move_are_no_moves(self):
        f = self.facts("|move|p1a: Gambit|Struggle|p2a: Frog", "|move|p1b: Roar|Fake Out|p2a: Frog",
                       "|-start|p1b: Roar|Mimic|Weather Ball", "|move|p1b: Roar|Weather Ball|p2a: Frog")
        self.assertEqual(f[0].moves, frozenset())
        self.assertEqual(f[1].moves, frozenset({"Fake Out"}))

    def test_item_from_enditem_mega_and_from_item(self):
        f = self.facts("|-enditem|p1b: Roar|Sitrus Berry|[eat]",
                       "|-damage|p2b: Giraffe|90/100|[from] item: Rocky Helmet|[of] p1a: Gambit",
                       "|-heal|p2a: Frog|80/100|[from] item: Leftovers",
                       "|switch|p1a: Zard|Charizard, L50, M|100/100",
                       "|detailschange|p1a: Zard|Charizard-Mega-Y, L50, M", "|-mega|p1a: Zard|Charizard|Charizardite Y")
        self.assertEqual([m.item for m in f[:3]], ["Rocky Helmet", "Sitrus Berry", "Charizardite Y"])
        self.assertEqual(self.facts("|-heal|p2a: Frog|80/100|[from] item: Leftovers", side=1)[0].item, "Leftovers")

    def test_an_of_on_the_other_side_names_no_own_member(self):
        # the effect's holder is the [of] member; when it is the foe, the subject learns nothing
        body = ["|-damage|p1a: Gambit|80/100|[from] ability: Rough Skin|[of] p2a: Frog",
                "|-damage|p1a: Gambit|70/100|[from] item: Rocky Helmet|[of] p2b: Giraffe"]
        self.assertEqual((self.facts(*body)[0].ability, self.facts(*body)[0].item), (None, None))
        self.assertEqual(self.facts(*body, side=1)[0].ability, "Rough Skin")
        self.assertEqual(self.facts(*body, side=1)[1].item, "Rocky Helmet")

    def test_frisk_names_the_foe_item(self):
        body = ["|-item|p2a: Frog|Leftovers|[from] ability: Frisk|[of] p1b: Roar"]
        self.assertEqual(self.facts(*body, side=1)[0].item, "Leftovers")
        self.assertEqual(self.facts(*body)[1].ability, "Frisk")

    def test_no_item_after_trick(self):
        f = self.facts("|-damage|p1a: Gambit|90/100|[from] item: Life Orb",
                       "|-activate|p1a: Gambit|move: Trick|[of] p2a: Frog",
                       "|-item|p2a: Frog|Life Orb|[from] move: Trick", "|-item|p1a: Gambit|Leftovers|[from] move: Trick",
                       "|-heal|p1a: Gambit|100/100|[from] item: Leftovers",
                       "|-heal|p2a: Frog|100/100|[from] item: Mystic Water")
        self.assertEqual(f[0].item, "Life Orb")  # seen before the trick: its own
        self.assertIsNone(self.facts("|-activate|p1a: Gambit|move: Trick|[of] p2a: Frog",
                                     "|-item|p2a: Frog|Life Orb|[from] move: Trick", side=1)[0].item)

    def test_trace_is_the_original_ability(self):
        body = ["|-ability|p2b: Giraffe|Intimidate|[from] ability: Trace|[of] p1b: Roar"]
        self.assertEqual(self.facts(*body, side=1)[1].ability, "Trace")
        self.assertEqual(self.facts(*body)[1].ability, "Intimidate")
        self.assertEqual(self.facts("|-ability|p1b: Roar|Intimidate|boost")[1].ability, "Intimidate")

    def test_no_ability_after_skill_swap_or_mega(self):
        f = self.facts("|-activate|p1a: Gambit|move: Skill Swap|Defiant|Drizzle|[of] p2a: Frog",
                       "|-ability|p1a: Gambit|Drizzle", "|switch|p1a: Zard|Charizard, L50, M|100/100",
                       "|detailschange|p1a: Zard|Charizard-Mega-Y, L50, M", "|-ability|p1a: Zard|Drought")
        self.assertEqual((f[0].ability, f[2].ability), (None, None))

    def test_a_mega_forme_is_its_preview_member(self):
        f = self.facts("|switch|p1a: Zard|Charizard, L50, M|100/100",
                       "|detailschange|p1a: Zard|Charizard-Mega-Y, L50, M", "|move|p1a: Zard|Solar Beam|p2a: Frog")
        self.assertEqual((f[2].species, f[2].moves), ("Charizard", frozenset({"Solar Beam"})))

    def test_a_wildcard_preview_is_resolved_by_its_switch_or_skipped(self):
        p1 = P1_PREVIEW[:4] + ["Rotom-*, L50"] + P1_PREVIEW[5:]
        f = self.facts("|switch|p1a: Fridge|Rotom-Wash, L50|100/100", p1=p1)
        self.assertEqual(f[4].species, "Rotom-Wash")
        f = self.facts("|switch|p1a: Fridge|Rotom, L50|100/100", p1=p1)  # the base forme itself (review minor)
        self.assertEqual(f[4].species, "Rotom")
        self.assertEqual(self.skip(p1=p1), "skip:belief-preview")

    def test_skips(self):
        self.assertEqual(self.skip(p1=P1_PREVIEW[:5] + ["Zoroark-Hisui, L50, M"]), "skip:illusion")
        self.assertEqual(self.skip("|-transform|p1a: Gambit|p2a: Frog"), "skip:belief-transform")
        five = [f"|move|p1a: Gambit|{m}|p2a: Frog" for m in ("Kowtow Cleave", "Sucker Punch", "Iron Head", "Protect",
                                                            "Swords Dance")]
        self.assertEqual(self.skip(*five), "skip:belief-moves")
        self.assertEqual(self.skip(p1=P1_PREVIEW[:5]), "skip:belief-preview")
        self.assertEqual(self.skip("|switch|p1a: Stranger|Dragonite, L50, M|100/100"), "skip:belief-preview")


def packed_set(species, item, ability, moves, nature, gender="M"):
    return "|".join([species, "", item, ability, ",".join(moves), nature, "", gender, "", "", "50", ""])


def player_names():
    """A test player's name and two training players' names (bucket 0 of 20 or not)."""
    from duoforge_replay import game, split
    names = [f"player{i}" for i in range(200)]
    test = next(n for n in names if split.is_test_player(game._hash8(n)))
    train = [n for n in names if not split.is_test_player(game._hash8(n))][:2]
    return test, train


class CorpusTest(unittest.TestCase):
    """The set corpus of the Bo1 belief (M11 Bo1 spec section 3): training-split sheets, one count per team."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.data = data.load(kind="pool")
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_corpus_"))
        test, (a, b) = player_names()
        team1 = "]".join([packed_set("Kingambit", "ChopleBerry", "Defiant", ["KowtowCleave", "SuckerPunch"], "Adamant"),
                          packed_set("Incineroar", "SitrusBerry", "Intimidate", ["FakeOut", "PartingShot"], "Careful")])
        team2 = packed_set("Politoed", "MysticWater", "Drizzle", ["WeatherBall", "Protect"], "Modest")
        team3 = packed_set("Dragonite", "ChoiceBand", "Multiscale", ["ExtremeSpeed"], "Adamant")
        team4 = packed_set("Garchomp", "FakeItem", "RoughSkin", ["Earthquake"], "Jolly")  # an item outside the tables
        cls.teams = (team1, team2, team3, team4)

        def game(p1, p2, s1, s2):
            return "\n".join([f"|player|p1|{p1}|1|", f"|player|p2|{p2}|2|", f"|showteam|p1|{s1}", f"|showteam|p2|{s2}"])
        cls.source = cls.tmp / "games.jsonl"
        with open(cls.source, "w", encoding="utf-8", newline="\n") as f:
            for gid, log in (("g1", game(a, b, team1, team2)), ("g2", game(a, b, team1, team2)),  # one Bo3, twice
                             ("g3", game(test, a, team3, team1)),  # a test player: team3, and team1 is in a test game
                             ("g4", game(a, b, team4, team2))):
                f.write(json.dumps({"id": gid, "formatid": "gen9championsvgc2026regmcbo3", "log": log}) + "\n")
        cls.registry = cls.tmp / "registry"
        (cls.registry / "data" / "teams").mkdir(parents=True)
        (cls.registry / "data" / "teams" / "index.json").write_text(json.dumps(
            {"registry": 1, "teams": [{"id": "PP_X", "name": "x", "source": {}, "notes": "", "sha256": ""}]}))
        (cls.registry / "data" / "teams" / "PP_X.txt").write_text(
            "Garchomp (F) @ Life Orb\nAbility: Rough Skin\nLevel: 50\nJolly Nature\n- Earthquake\n- Protect\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, name):
        from duoforge_replay import corpus
        out = self.tmp / name
        corpus.build([self.source], ("gen9championsvgc2026regmc",), self.registry, out, self.data)
        return corpus.load(out)

    def test_corpus_takes_the_training_split_once_per_team(self):
        from duoforge_replay import game
        c = self.build("c1.json")
        self.assertEqual([s[4] for s in c.sets("POLITOED")], [1])  # one team, however often its player played it
        self.assertEqual(c.sets("DRAGONITE"), [])
        # team1 was played in a test game too (by the training opponent): out, so no test game draws from itself
        self.assertEqual(c.sets("KINGAMBIT"), [])
        self.assertEqual(c.sets("GARCHOMP"), [("Life Orb", "Rough Skin", "Jolly", ("Earthquake", "Protect"), 1)])
        self.assertEqual(c.sheet_hashes, frozenset({game._hash8(self.teams[1]), game._hash8(self.teams[3])}))

    def test_corpus_adds_the_registry_and_refuses_the_repository(self):
        from duoforge_replay import corpus
        c = self.build("c2.json")
        # the registry's Garchomp; the sheet Garchomp with an item outside the tables is not taken
        self.assertEqual(c.sets("GARCHOMP"), [("Life Orb", "Rough Skin", "Jolly", ("Earthquake", "Protect"), 1)])
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            corpus.build([self.source], ("gen9championsvgc2026regmc",), self.registry, data.ROOT / "corpus.json",
                         self.data)


class SetBeliefTest(unittest.TestCase):
    """Whole sets drawn from the corpus, agreeing with every fact (L0) or completed from frequencies (L1)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay import corpus, facts, points, setbelief
        cls.C, cls.F, cls.B, cls.Skip = corpus, facts, setbelief, points.Skip
        cls.data = data.load(kind="pool")
        cls.corpus = corpus.Corpus({"KINGAMBIT": [
            ("ChopleBerry", "Defiant", "Adamant", ("KowtowCleave", "SuckerPunch", "IronHead", "Protect"), 3),
            ("BlackGlasses", "Defiant", "Adamant", ("SuckerPunch", "IronHead", "LowKick", "Protect"), 5)]},
            frozenset(), "test")

    def member(self, moves=(), item=None, ability=None):
        return self.F.MemberFacts("Kingambit", "M", frozenset(moves), item, ability)

    def test_l0_draw_agrees_with_every_fact(self):
        belief = self.B.SetBelief(self.corpus, self.data)
        for w in range(0, 2 ** 64, 2 ** 60):
            s, level = belief.draw(self.member(moves={"Kowtow Cleave"}), w)
            self.assertEqual((level, s["item"]), (0, "ChopleBerry"))
            self.assertEqual((s["species"], s["gender"], s["level"], s["evs"]), ("Kingambit", "M", 50, [0] * 6))
        s, level = belief.draw(self.member(item="Black Glasses"), 0)  # a revealed item keeps the log's spelling
        self.assertEqual((level, s["item"], s["moves"][0]), (0, "Black Glasses", "SuckerPunch"))

    def test_l1_keeps_used_moves_and_fills_from_frequencies(self):
        belief = self.B.SetBelief(self.corpus, self.data)
        s, level = belief.draw(self.member(moves={"Swords Dance"}), 12345)
        self.assertEqual(level, 1)
        self.assertIn("Swords Dance", s["moves"])
        self.assertEqual(len(s["moves"]), 4)
        self.assertEqual(len({trace_to_c.key(m) for m in s["moves"]}), 4)
        self.assertTrue(set(s["moves"]) - {"Swords Dance"} <= {"KowtowCleave", "SuckerPunch", "IronHead", "Protect",
                                                               "LowKick"})

    def test_l1_fill_has_no_move_twice_under_two_spellings(self):
        # review I2: sheets spell "FakeOut", pastes "Fake Out"; the fill keys moves by trace_to_c.key
        mixed = self.C.Corpus({"KINGAMBIT": [
            ("ChopleBerry", "Defiant", "Adamant", ("FakeOut", "KnockOff", "SuckerPunch", "IronHead"), 3),
            ("Black Glasses", "Defiant", "Adamant", ("Fake Out", "Knock Off", "Sucker Punch", "Iron Head"), 3)]},
            frozenset(), "test")
        belief = self.B.SetBelief(mixed, self.data)
        for w in range(0, 2 ** 64, 2 ** 57):
            s, level = belief.draw(self.member(moves={"Throat Chop"}), w)
            self.assertEqual(level, 1)
            self.assertEqual(len({trace_to_c.key(m) for m in s["moves"]}), len(s["moves"]), s["moves"])

    def test_unsupported_species_is_a_counted_skip(self):
        belief = self.B.SetBelief(self.corpus, self.data, min_sets=9)
        with self.assertRaises(self.Skip) as cm:
            belief.draw(self.member(), 0)
        self.assertEqual(cm.exception.reason, "skip:belief-unsupported Kingambit")
        with self.assertRaises(self.Skip) as cm:
            self.B.SetBelief(self.corpus, self.data).draw(self.member(item="Leftovers"), 0)
        self.assertEqual(cm.exception.reason, "skip:belief-unsupported Kingambit")

    def test_words_do_not_depend_on_order(self):
        w = self.B.word(1, "r", 0, 2, 0, 0)
        self.assertEqual(w, self.B.word(1, "r", 0, 2, 0, 0))
        others = [self.B.word(2, "r", 0, 2, 0, 0), self.B.word(1, "s", 0, 2, 0, 0), self.B.word(1, "r", 1, 2, 0, 0),
                  self.B.word(1, "r", 0, 3, 0, 0), self.B.word(1, "r", 0, 2, 1, 0), self.B.word(1, "r", 0, 2, 0, 1)]
        self.assertEqual(len(set(others + [w])), 7)
        self.assertTrue(0 <= w < 2 ** 64)

    def test_same_word_same_set(self):
        belief = self.B.SetBelief(self.corpus, self.data)
        self.assertEqual(belief.draw(self.member(), 99), belief.draw(self.member(), 99))


class BeliefGameTest(unittest.TestCase):
    """A game without sheets on sampled sheets of both sides (option B), on the fixture with its sheets removed."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import teams
        from duoforge_replay import corpus, game, prior, setbelief
        cls.G, cls.SB = game, setbelief
        cls.data = data.load(kind="pool")
        log = FIXTURE.read_text(encoding="utf-8").split("\n")
        cls.sheets = [teams.unpack(line.split("|", 3)[3]) for line in log if line.startswith("|showteam|")]
        cls.log = [line for line in log if not line.startswith("|showteam|")]
        cls.with_sheets = log
        cls.prior = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})
        sets = collections.defaultdict(list)
        for s in cls.sheets[0] + cls.sheets[1]:
            key = trace_to_c.key(cls.data.canonical(s["species"]))
            sets[key].append((s["item"], s["ability"], s["nature"], tuple(sorted(s["moves"])), 3))
            sets[key].append((s["item"], s["ability"], "Hardy" if s["nature"] != "Hardy" else "Bold",
                              tuple(sorted(s["moves"])), 1))  # a second set: draws can differ
        cls.corpus = corpus.Corpus(dict(sets), frozenset(), "test")
        cls.belief = setbelief.SetBelief(cls.corpus, cls.data, min_sets=1)

    def process(self, log=None, belief=None, **kw):
        return self.G.process("fixture-belief", "gen9championsvgc2026regmc", "\n".join(log or self.log), self.data,
                              self.prior, _Stats(), belief=belief or self.belief, **kw)

    def test_a_belief_game_gives_rows_with_levels(self):
        result = self.process(seed=1)
        self.assertGreater(len(result.rows), 10)
        for row in result.rows:
            self.assertEqual(len(row.belief_level), 12)
            self.assertTrue(set(row.belief_level) <= {0, 1})
            self.assertEqual(len(row.revealed), 6)
            for slot, reason in zip(row.label.slots, row.label.reasons):
                self.assertTrue(slot or reason == 0)  # every asked slot has a label set (its option is in the domain)
        self.assertEqual(result.record.draw, 0)

    def test_the_played_move_is_always_in_the_drawn_set(self):
        from duoforge_replay import facts
        for draw in range(4):
            sheets, levels, revealed = self.G.draw_sheets(self.log, "gen9championsvgc2026regmc", self.data, self.belief,
                                                          7, "fixture-belief", draw)
            for side in (0, 1):
                for member, s, bits in zip(facts.side_facts(self.log, side, self.data), sheets[side], revealed[side]):
                    drawn = [trace_to_c.key(m) for m in s["moves"]]
                    self.assertTrue({trace_to_c.key(m) for m in member.moves} <= set(drawn), (member, s))
                    self.assertEqual(bin(bits).count("1"), len(member.moves))

    def test_a_revealed_name_outside_the_tables_is_a_name_skip(self):
        # the 2026-10-10 run: an item a log reveals (Assault Vest) that the tables lack was a KeyError
        at = next(i for i, line in enumerate(self.log) if line.startswith("|switch|p1a: Kingambit|")) + 1
        log = self.log[:at] + ["|-enditem|p1a: Kingambit|Assault Vest|[from] move: Knock Off|[of] p2a: Politoed"] \
            + self.log[at:]
        with self.assertRaises(self.G.Skip) as cm:
            self.process(log=log)
        self.assertEqual(cm.exception.reason, "name:ITEM Assault Vest")

    def test_a_game_with_sheets_is_refused(self):
        with self.assertRaisesRegex(ValueError, "has sheets"):
            self.process(log=self.with_sheets)

    def test_the_own_sheet_in_the_corpus_is_refused(self):
        # review question: a training player can share a test player's team (a rental): the game is a counted
        # skip, never drawn from its own sheet
        from duoforge_replay import corpus, setbelief
        own = corpus.Corpus(self.corpus._sets, frozenset({12345}), "test")
        with self.assertRaises(self.G.Skip) as cm:
            self.process(belief=setbelief.SetBelief(own, self.data, min_sets=1), known_sheets=(12345, 6789))
        self.assertEqual(cm.exception.reason, "skip:sheet-in-corpus")

    def test_an_illegal_draw_is_redrawn_then_skipped(self):
        from duoforge_replay import corpus, setbelief
        sets = dict(self.corpus._sets)
        sets["KINGAMBIT"] = [("ChopleBerry", "Drizzle", "Adamant", ("KowtowCleave", "Protect", "IronHead", "SuckerPunch"),
                              1)]
        bad = setbelief.SetBelief(corpus.Corpus(sets, frozenset(), "test"), self.data, min_sets=1)
        with self.assertRaises(self.G.Skip) as cm:
            self.process(belief=bad)
        self.assertEqual(cm.exception.reason, "skip:belief-illegal")

    def test_a_refusal_a_redraw_cannot_fix_keeps_its_reason(self):
        # review minor: only a legality refusal is redrawn; a sheet rule refusal (a gender, say) keeps its reason
        from unittest import mock
        for reason, want in (("sheet:gender-none", "sheet:gender-none"),
                             ("skip:pool-illegal Kingambit move Protect", "skip:belief-illegal")):
            with self.subTest(reason), mock.patch.object(self.G, "_check_sheets", side_effect=self.G.Skip(reason)):
                with self.assertRaises(self.G.Skip) as cm:
                    self.process()
                self.assertEqual(cm.exception.reason, want)

    def test_draws_are_deterministic(self):
        a, b = self.process(seed=3), self.process(seed=3)
        self.assertEqual([r.observation.tobytes() for r in a.rows], [r.observation.tobytes() for r in b.rows])
        drawn = {repr(self.G.draw_sheets(self.log, "gen9championsvgc2026regmc", self.data, self.belief, 3,
                                         "fixture-belief", d)[0]) for d in range(8)}
        self.assertGreater(len(drawn), 1)
        self.assertEqual(self.process(seed=3, draw=2).record.draw, 2)


class _BeliefFixture:
    """The fixture log as games of chosen player splits, with and without sheets, a corpus of its own sets."""

    @classmethod
    def setUpClass(cls):
        import json
        from duoforge_live import teams
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_belief_build_"))
        cls.data = data.load(kind="pool")
        log = FIXTURE.read_text(encoding="utf-8")
        cls.prior_path = cls.tmp / "prior.json"
        cls.prior_path.write_text(json.dumps({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                                  encoding="utf-8")
        sheets = [teams.unpack(line.split("|", 3)[3]) for line in log.split(chr(10)) if line.startswith("|showteam|")]
        sets = collections.defaultdict(list)
        for s in sheets[0] + sheets[1]:
            sets[trace_to_c.key(cls.data.canonical(s["species"]))].append(
                [s["item"], s["ability"], s["nature"], sorted(s["moves"]), 5])
        cls.corpus = cls.tmp / "corpus.json"
        cls.corpus.write_text(json.dumps({"version": 1, "sheet_hashes": [], "sets": sets}), encoding="utf-8")
        test, (a, b) = player_names()

        def named(text, p1, p2):
            return text.replace("|player|p1|p1||", f"|player|p1|{p1}||").replace("|player|p2|p2||", f"|player|p2|{p2}||")
        bo1 = chr(10).join(line for line in log.split(chr(10)) if not line.startswith("|showteam|"))
        cls.games = {"open-train": named(log, a, b), "open-test": named(log, test, b), "bo1-train": named(bo1, a, b),
                     "bo1-test": named(bo1, test, a)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def source(self, name, ids):
        import json
        path = self.tmp / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8", newline=chr(10)) as f:
            for gid in ids:
                f.write(json.dumps({"id": gid, "formatid": "gen9championsvgc2026regmc", "log": self.games[gid]}) + chr(10))
        return path

    def build(self, name, ids, **kw):
        from duoforge_replay import build
        return build.build([self.source(name, ids)], self.prior_path, self.tmp / name, unit_lines=8,
                           stats_factory=stats_factory, log=lambda _: None, **kw)

    def manifest(self, name):
        import json
        return json.loads((self.tmp / name / "manifest.json").read_text(encoding="utf-8"))



class BeliefBuildTest(_BeliefFixture, unittest.TestCase):
    """The bo1_belief and drop_sheets modes of a build and their marked datasets (M11 Bo1 plan Task 5)."""

    def test_bo1_mode_takes_only_games_without_sheets(self):
        from duoforge_replay import dataset, funnel
        c = self.build("bo1", ["open-train", "bo1-train"], mode="bo1_belief", corpus=self.corpus, seed=1)
        self.assertEqual((c["games.processed"], c["games.skipped.skip:has-sheets"]), (1, 1))
        f = funnel.report(c)["gen9championsvgc2026regmc"]
        self.assertEqual(f["taken"], 1)
        self.assertIn("taken by this build 1", funnel.text(funnel.report(c)))
        shards = list(dataset.read(self.tmp / "bo1"))
        self.assertTrue(shards)
        for shard in shards:
            self.assertEqual(shard["belief_level"].shape[1:], (12,))
            self.assertEqual(shard["revealed"].shape[1:], (6,))
        self.assertEqual(self.manifest("bo1")["source"], "bo1_belief")

    def test_drop_mode_takes_test_split_sheet_games_without_their_sheets(self):
        c = self.build("drop", ["open-test", "open-train", "bo1-test"], mode="drop_sheets", corpus=self.corpus)
        self.assertEqual(c["games.processed"], 1)
        self.assertEqual(c["games.skipped.skip:split-train"], 1)
        self.assertEqual(c["games.skipped.skip:sheets"], 1)
        from duoforge_replay import funnel
        f = funnel.report(c)["gen9championsvgc2026regmc"]
        self.assertEqual(f["skipped"].get("skip:split-train"), 1)
        self.assertEqual(f["read"], sum(f["skipped"].values()) + f["internal"] + f["processed"])
        self.assertEqual(self.manifest("drop")["source"], "drop_sheets")

    def test_k_draws_are_k_games_with_their_draw(self):
        from duoforge_replay import dataset
        c = self.build("k3", ["bo1-train"], mode="bo1_belief", corpus=self.corpus, k=3)
        self.assertEqual((c["games.read"], c["games.processed"]), (3, 3))
        games = dataset.read_games(next(iter(dataset.parts(self.tmp / "k3"))))
        self.assertEqual(sorted(games["draw"].tolist()), [0, 1, 2])

    def test_a_build_keeps_the_extension_records_and_its_folds(self):
        from duoforge import _layout
        from duoforge_live import lines as line_classes
        from duoforge_replay import dataset
        self.build("ext", ["open-train"])
        m = self.manifest("ext")
        self.assertEqual((m["format_version"], m["tracker_folds"]), (4, line_classes.TRACKER_FOLDS))
        self.assertEqual(m["ext_revision"], _layout.CONSTANTS["DUOFORGE_OBSERVATION_EXT_REVISION"])
        for shard in dataset.read(self.tmp / "ext"):
            self.assertEqual(shard["ext"].dtype, _layout.OBSERVATION_EXT)
            self.assertEqual(len(shard["ext"]), len(shard["side"]))
            self.assertTrue((shard["ext"]["epoch"] == shard["observation"]["epoch"]).all())

    def test_a_sheet_build_names_its_source_and_has_no_belief_fields(self):
        from duoforge_replay import dataset
        self.build("sheet", ["open-train", "bo1-train"])
        m = self.manifest("sheet")
        self.assertEqual((m["source"], m["format_version"]), ("sheet", dataset.FORMAT_VERSION))
        self.assertEqual(dataset.FORMAT_VERSION, 4)
        for shard in dataset.read(self.tmp / "sheet"):
            self.assertNotIn("belief_level", shard)
        part = next(iter(dataset.parts(self.tmp / "sheet")))
        self.assertNotIn("draw", dataset.read_games(part))

    def test_the_options_must_fit_the_mode(self):
        for kw, part in (({"mode": "sheet", "corpus": self.corpus}, "corpus"), ({"mode": "bo1_belief"}, "corpus"),
                         ({"mode": "sheet", "k": 2}, "k"), ({"mode": "nonsense"}, "mode"),
                         ({"mode": "drop_sheets", "corpus": self.corpus, "split_of": "train"}, "test split"),
                         ({"mode": "bo1_belief", "corpus": self.corpus, "k": 256}, "k")):
            with self.subTest(kw), self.assertRaisesRegex(ValueError, part):
                self.build("bad", ["bo1-train"], **kw)

    def test_a_writer_refuses_rows_of_the_other_source(self):
        from duoforge_replay import dataset, game, prior, setbelief, corpus
        belief = setbelief.SetBelief(corpus.load(self.corpus), self.data)
        result = game.process("x", "gen9championsvgc2026regmc", self.games["bo1-train"], self.data,
                              prior.Prior.load(self.prior_path), _Stats(), belief=belief)
        writer = dataset.Writer(self.tmp / "mixed", {}, source="sheet")
        with self.assertRaisesRegex(ValueError, "belief rows"):
            writer.add(result)


def short_log(log):
    """The fixture log cut before p1's Salamence enters: three of p1's four brought members are seen."""
    lines = log.split(chr(10))
    cut = next(i for i, line in enumerate(lines) if line.startswith("|switch|p1a: Salamence|"))
    return chr(10).join(lines[:cut] + ["|win|p2"])


class _ShortFixture(_BeliefFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.games["short-train"] = short_log(cls.games["open-train"])


class PickHypothesesBuildTest(_ShortFixture, unittest.TestCase):
    """A sheet build with --pick-hypotheses: its marked rows, manifest, inputs and funnel (M11 pick hypotheses spec,
    sections 4, 6 and 7)."""

    def test_the_hypothesis_rows_are_marked_and_counted_apart(self):
        from duoforge_replay import dataset, funnel
        plain = self.build("plain", ["short-train", "open-train"])
        hyp = self.build("hyp", ["short-train", "open-train"], pick_hypotheses=True)
        self.assertEqual((self.manifest("hyp")["pick_hypotheses"], self.manifest("plain")["pick_hypotheses"]),
                         (True, False))
        shards = list(dataset.read(self.tmp / "hyp"))
        h = np.concatenate([s["picks_hypotheses"] for s in shards])
        k = np.concatenate([s["hypothesis"] for s in shards])
        self.assertEqual(set(h.tolist()), {1, 3})
        self.assertEqual(set(k[h == 3].tolist()), {0, 1, 2})
        self.assertTrue((k[h == 1] == 0).all())
        for s in dataset.read(self.tmp / "plain"):
            self.assertTrue((s["picks_hypotheses"] == 1).all())
        self.assertEqual(int((h == 1).sum()), sum(len(s["side"]) for s in dataset.read(self.tmp / "plain")))
        fp, fh = (funnel.report(c)["gen9championsvgc2026regmc"] for c in (plain, hyp))
        self.assertEqual(fh["rows"], fp["rows"])  # the rows column holds the rows without hypotheses
        self.assertEqual(fh["turns"], fp["turns"])  # the headline turn coverage does not change
        self.assertEqual(fh["perspectives"], fp["perspectives"])
        self.assertEqual(fh["hypotheses"]["rows"], int((h == 3).sum()))
        self.assertGreater(fh["hypotheses"]["turns"], 0)
        self.assertEqual(fh["hypotheses"]["kept"] + sum(fh["hypotheses"]["stopped"].values()),
                         fp["perspectives"]["stopped"]["picks-incomplete"])
        self.assertEqual(fp["hypotheses"], {"kept": 0, "stopped": {}, "turns": 0, "rows": 0})
        text = funnel.text(funnel.report(hyp))
        self.assertIn("turns with pick hypotheses", text)
        self.assertNotIn("turns with pick hypotheses", funnel.text(funnel.report(plain)))

    def test_a_resume_refuses_the_other_setting(self):
        self.build("resume", ["short-train"])
        with self.assertRaisesRegex(ValueError, "other inputs"):
            self.build("resume", ["short-train"], pick_hypotheses=True)

    def test_only_a_sheet_build_makes_hypotheses(self):
        with self.assertRaisesRegex(ValueError, "pick hypotheses"):
            self.build("bad-hyp", ["bo1-train"], mode="bo1_belief", corpus=self.corpus, pick_hypotheses=True)

    def test_a_writer_without_the_option_refuses_hypothesis_rows(self):
        from duoforge_replay import dataset, game, prior
        result = game.process("x", "gen9championsvgc2026regmc", self.games["short-train"], self.data,
                              prior.Prior.load(self.prior_path), _Stats(), pick_hypotheses=True)
        self.assertTrue(any(r.picks_hypotheses > 1 for r in result.rows))
        writer = dataset.Writer(self.tmp / "no-hyp", {})
        with self.assertRaisesRegex(ValueError, "pick hypotheses"):
            writer.add(result)
        with self.assertRaisesRegex(ValueError, "sheet"):
            dataset.Writer(self.tmp / "belief-hyp", {}, source="bo1_belief", pick_hypotheses=True)


class ValidateHypothesesTest(_ShortFixture, unittest.TestCase):
    """The validation of the pick hypotheses (M11 pick hypotheses spec, Validation): a seen back pick hidden from the
    hypothesis builder; the true hypothesis must give the real rows byte for byte."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from duoforge_replay import prior
        cls.prior = prior.Prior.load(cls.prior_path)

    def counters(self, log):
        from duoforge_replay import validate
        return validate.hypotheses_game("fixture-v", "gen9championsvgc2026regmcbo3", log, self.data, self.prior,
                                        _Stats())

    def test_the_true_hypothesis_of_a_hidden_pick_is_byte_identical(self):
        c = self.counters(FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(c["perspectives.seen4"], 1)
        self.assertEqual(c["cases"], 2 * c["perspectives.seen4"])  # each of the two seen back picks hidden once
        self.assertGreater(c["true.rows"], 0)
        self.assertEqual((c["true.identical"], c["true.missing"]), (c["true.rows"], 0))
        self.assertEqual(c["other.rows"] + c["other.missing"], 2 * (c["true.rows"] + c["true.missing"]))
        self.assertGreater(c["other.differs.own_members"], 0)  # the swapped bench member's location
        self.assertGreater(c["points"], 0)
        self.assertEqual(c["all_equal.rows"], 0)  # the own bench of every hypothesis is its own
        self.assertLessEqual(c["all_equal.beyond_picks"], c["points"])

    def test_a_row_difference_of_the_true_hypothesis_is_counted(self):
        from unittest import mock
        from duoforge_replay import game
        real = game.hypothesis_rows

        def shifted(*args, **kw):
            rows, stop = real(*args, **kw)
            for per in rows:
                for r in per:
                    r.observation = r.observation.copy()
                    r.observation["turn"] += 1
            return rows, stop
        with mock.patch.object(game, "hypothesis_rows", shifted):
            c = self.counters(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual((c["true.identical"], c["true.differs"]), (0, c["true.rows"]))

    def test_the_real_hypotheses_count_their_equal_points(self):
        c = self.counters(self.games["short-train"])
        self.assertEqual(c["real.perspectives"], 1)
        self.assertGreater(c["real.points"], 0)
        self.assertEqual(c["real.all_equal.rows"], 0)

    def test_the_report_is_aggregates_of_test_games_only(self):
        import json
        from duoforge_replay import validate
        path = self.source("vh", ["open-train", "open-test"])
        report = validate.hypotheses([path], "gen9championsvgc2026regmc", self.tmp / "vh.json",
                                     self.prior_path, stats_factory=stats_factory)
        f = report["formats"]["gen9championsvgc2026regmc"]
        self.assertEqual((f["games"], report["skipped"].get("skip:split-train")), (1, 1))
        self.assertEqual(f["true"]["identical_share"], 1.0)
        self.assertNotIn("open-test", json.dumps(report))
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            validate.hypotheses([path], "gen9championsvgc2026regmc", Path(__file__).resolve().parent / "x.json",
                                self.prior_path, stats_factory=stats_factory)


class ValidateTest(_BeliefFixture, unittest.TestCase):
    """Validation (a) set recovery and (b) row difference (M11 Bo1 spec section 6), aggregates only."""

    def test_set_recovery_counts(self):
        from duoforge_replay import facts, prior, validate
        true = {"species": "Kingambit", "item": "ChopleBerry", "ability": "Defiant", "nature": "Adamant",
                "moves": ["KowtowCleave", "SuckerPunch", "IronHead", "Protect"]}
        drawn = {"species": "Kingambit", "item": "ChopleBerry", "ability": "Defiant", "nature": "Jolly",
                 "moves": ["KowtowCleave", "SuckerPunch", "IronHead", "LowKick"]}
        fact = facts.MemberFacts("Kingambit", "M", frozenset({"Kowtow Cleave"}), None, "Defiant")
        c = validate.set_recovery([true], [drawn], [fact], [1], prior.Prior.load(self.prior_path))
        self.assertEqual(dict(c), {"members": 1, "members.level1": 1, "moves.exact": 0, "moves.unseen": 3,
                                   "moves.unseen_hit": 2, "item.unrevealed": 1, "item.hit": 1, "ability.unrevealed": 0,
                                   "ability.hit": 0, "nature.hit": 0, "prior_level.same": 1, "prior_points.same": 1})

    def test_validate_sets_on_the_fixture(self):
        import json
        from duoforge_replay import validate
        out = self.tmp / "sets.json"
        report = validate.sets([self.source("v", ["open-test", "open-train"])], ("gen9championsvgc2026regmc",),
                               self.corpus, 1, out, self.data, self.prior_path)
        self.assertEqual(report["games"], 1)
        self.assertEqual(report["counters"]["members"], 12)
        self.assertEqual(report["skipped"], {"skip:split-train": 1})
        text = out.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), report)
        self.assertNotIn("open-test", text)

    def test_compare_rows_on_the_fixture(self):
        import json
        from duoforge_replay import validate
        self.build("cmp-sheet", ["open-test"], split_of="test")
        self.build("cmp-drop", ["open-test"], mode="drop_sheets", corpus=self.corpus, seed=1)
        report = validate.compare_rows(self.tmp / "cmp-sheet", self.tmp / "cmp-drop")
        self.assertGreater(report["both"], 10)
        self.assertEqual(report["both"] + report["only_sheet"], report["rows_sheet"])
        self.assertTrue(0 <= report["mask_jaccard_mean"] <= 1)
        for group in ("own_members", "foe_members", "positions", "header"):
            self.assertTrue(0 <= report["observation_differs"][group] <= 1)
        self.assertEqual(report["label"]["same"] + report["label"]["differs"], report["both"])
        self.assertNotIn("open-test", json.dumps(report))
        # review I3: this corpus holds exactly the true sets, so by move identity every row agrees
        self.assertEqual(report["mask_jaccard_mean"], 1.0)
        self.assertEqual(report["label"]["differs"], 0)
        self.assertEqual(report["observation_differs"]["own_members"], 0.0)
        self.assertEqual(report["observation_differs"]["foe_members"], 0.0)

    def test_compare_rows_refuses_two_draws_of_a_row(self):
        from duoforge_replay import validate
        self.build("cmp-k2", ["open-test"], mode="drop_sheets", corpus=self.corpus, k=2)
        with self.assertRaisesRegex(ValueError, "draw"):
            validate.compare_rows(self.tmp / "cmp-k2", self.tmp / "cmp-k2")

    def test_reports_are_refused_in_the_repository(self):
        from duoforge_replay import validate
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            validate.sets([self.source("r", ["open-test"])], ("gen9championsvgc2026regmc",), self.corpus, 1,
                          data.ROOT / "sets.json", self.data, self.prior_path)


if __name__ == "__main__":
    unittest.main()
