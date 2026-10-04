"""Protocol-only opening extraction tests using short synthetic replay logs."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from duoforge_live.data import trace_to_c
from duoforge_replay import openings


_POKEMON = (
    "Pikachu", "Vivillon-Pokeball", "Charizard", "Indeedee-F", "Torkoal", "Sinistcha-Masterpiece",
    "Incineroar", "Gholdengo", "Pelipper", "Flutter Mane", "Kingambit", "Archaludon",
)
_MOVES = ("Thunderbolt", "Fake Out", "Make It Rain", "Heat Wave", "Snarl", "Psychic", "Protect", "U-turn",
          "Volt Switch", "Flip Turn", "Parting Shot")
_ITEMS = ("Choice Band", "Sitrus Berry", "Leftovers", "Booster Energy")


class FakeData:
    def __init__(self):
        self.aliases = {
            "vivillonpokeball": "Vivillon", "sinistchamasterpiece": "Sinistcha",
        }
        names = {self.aliases.get(trace_to_c.key(name).lower(), name) for name in _POKEMON} | {"Vivillon-Mega"}
        self.species = {trace_to_c.key(name): index for index, name in enumerate(sorted(names))}
        for alias, canonical in self.aliases.items():
            self.species[alias.upper()] = self.species[trace_to_c.key(canonical)]
        self.tables = {
            "FORME": dict(self.species),
            "MOVE": {trace_to_c.key(name): index for index, name in enumerate(_MOVES)},
            "ITEM": {trace_to_c.key(name): index for index, name in enumerate(_ITEMS)},
        }

    def forme(self, name):
        key = trace_to_c.key(name)
        if key not in self.species:
            raise ValueError(name)
        return self.species[key]

    def canonical(self, name):
        key = trace_to_c.key(name).lower()
        if key in self.aliases:
            return self.aliases[key]
        self.forme(name)
        return name

    def base_forme(self, forme):
        return forme


def _packed(species, item, moves):
    fields = [species, "", trace_to_c.key(item).lower(), "overgrow", ",".join(trace_to_c.key(m).lower() for m in moves),
              "Hardy", "", "", "", "", "50", ""]
    return "|".join(fields)


def _team(species, items):
    return "]".join(_packed(name, item, _MOVES[:4]) for name, item in zip(species, items))


P1 = _POKEMON[:6]
P2 = _POKEMON[6:]
LOG = "\n".join([
    "|player|p1|Alice|1|1500",
    "|player|p2|Bob|2|1420",
    "|uhtml|bestof|<h2><strong>Game 2</strong> of a best-of-3</h2>",
    *(f"|poke|p1|{name}, L50|" for name in P1),
    *(f"|poke|p2|{name}, L50|" for name in P2),
    f"|showteam|p1|{_team(P1, ('Choice Band', 'Sitrus Berry', 'Leftovers', '', '', ''))}",
    f"|showteam|p2|{_team(P2, ('Sitrus Berry', 'Leftovers', 'Booster Energy', '', '', ''))}",
    "|start|",
    "|switch|p1a: Pikachu|Pikachu, L50|100/100",
    "|switch|p1b: Vivillon-Pokeball|Vivillon-Pokeball, L50|100/100",
    "|switch|p2a: Incineroar|Incineroar, L50|100/100",
    "|switch|p2b: Gholdengo|Gholdengo, L50|100/100",
    "|turn|1",
    "|move|p1a: Pikachu|U-turn|p2a: Incineroar|",
    "|switch|p1a: Pikachu|Charizard, L50|100/100",
    "|move|p1a: Charizard|Thunderbolt|p2a: Incineroar|",
    "|-mega|p1b: Vivillon-Pokeball|Vivillon-Mega|",
    "|-terastallize|p1a: Charizard|Electric|",
    "|-item|p2a: Incineroar|Sitrus Berry|",
    "|move|p2b: Gholdengo|Make It Rain|p1a: Pikachu|",
    "|move|p1a: Pikachu|",
    "|future-opening-event|ignored|",
    "|faint|p2a: Incineroar",
    "|upkeep|",
    "|switch|p2a: Incineroar|Pelipper, L50|100/100",
    "|turn|2",
    "|switch|p1a: Charizard|Indeedee-F, L50|100/100",
    "|move|p1a: Indeedee-F|Psychic|p2a: Pelipper|",
    "|move|p2a: Pelipper|Fake Out|p1a: Indeedee-F|",
    "|turn|3",
    "|switch|p1b: Vivillon-Pokeball|Charizard, L50|100/100",
    "|switch|p2b: Gholdengo|Flutter Mane, L50|100/100",
    "|move|p1a: Indeedee-F|U-turn|p2a: Pelipper|",
    "|switch|p1a: Indeedee-F|Pikachu, L50|100/100",
    "|-terastallize|p2a: Pelipper|Fire|",
    "|move|p2a: Pelipper|Snarl|p1a: Pikachu|",
    "|drag|p1a: Pikachu|Charizard, L50|100/100",
    "|win|Alice",
])


class OpeningsTest(unittest.TestCase):
    def setUp(self):
        self.data = FakeData()

    def extract(self, log=LOG, format_id="gen9championsvgc2026regmc"):
        return openings.extract_game("fixture", format_id, log, self.data)

    def test_extracts_sheets_leads_actions_winner_and_diagnostics(self):
        game = self.extract()
        self.assertEqual((game.source, game.format_id, tuple(side.rating for side in game.sides), game.winner,
                          game.bo3_game),
                         ("champions", "gen9championsvgc2026regmc", (1500, 1420), 0, 2))
        self.assertEqual(len(game.sides[0].team), 6)
        self.assertEqual([(member.species, member.item) for member in game.sides[0].team], [
            ("Pikachu", "choiceband"), ("Vivillon", "sitrusberry"), ("Charizard", "leftovers"),
            ("Indeedee-F", ""), ("Torkoal", ""), ("Sinistcha", ""),
        ])
        self.assertEqual(game.sides[0].team[1], openings.SpeciesItem("Vivillon", "sitrusberry"))
        self.assertEqual(game.sides[0].leads, ("Pikachu", "Vivillon"))
        self.assertEqual(game.sides[0].brought, ("Pikachu", "Vivillon", "Charizard", "Indeedee-F"))
        self.assertEqual(game.sides[1].leads, ("Incineroar", "Gholdengo"))
        self.assertEqual(game.sides[1].brought, ("Incineroar", "Gholdengo", "Pelipper", "Flutter Mane"))
        self.assertEqual([(action.turn, action.kind, action.name, action.target) for action in game.actions], [
            (1, "move", "U-turn", "p2a: Incineroar"),
            (1, "switch", "Charizard", None),
            (1, "move", "Thunderbolt", "p2a: Incineroar"),
            (1, "mega", "Vivillon-Mega", None),
            (1, "move", "Make It Rain", "p1a: Charizard"),
            (1, "switch", "Pelipper", None),
            (2, "switch", "Indeedee-F", None),
            (2, "move", "Psychic", "p2a: Pelipper"),
            (2, "move", "Fake Out", "p1a: Indeedee-F"),
            (3, "switch", "Charizard", None),
            (3, "switch", "Flutter Mane", None),
            (3, "move", "U-turn", "p2a: Pelipper"),
            (3, "switch", "Pikachu", None),
            (3, "move", "Snarl", "p1a: Pikachu"),
            (3, "switch", "Charizard", None),
        ])
        self.assertEqual([(action.turn, action.switch_context) for action in game.actions if action.kind == "switch"], [
            (1, "pivot"), (1, "replacement"), (2, "choice"), (3, "choice"), (3, "choice"), (3, "pivot"),
            (3, "drag"),
        ])
        self.assertEqual(game.tera_sides, (True, True))
        self.assertTrue(game.terastallized)
        self.assertTrue(game.pool_compatible)
        self.assertIn(("lines.garbled.move", 1), game.diagnostics)
        self.assertIn(("lines.unknown.future-opening-event", 1), game.diagnostics)
        self.assertEqual(openings.source_for_format("gen9championsvgc2026regmbbo3"), "champions")
        self.assertEqual(openings.source_for_format("gen9vgc2026regi"), "sv_vgc")

    def test_switches_after_pivot_moves_without_from_are_midturn(self):
        for move in ("U-turn", "Volt Switch", "Flip Turn", "Parting Shot"):
            with self.subTest(move=move):
                game = self.extract(log=LOG.replace("U-turn", move))
                switch = next(action for action in game.actions if action.turn == 1 and action.kind == "switch"
                              and action.name == "Charizard")
                self.assertEqual(switch.switch_context, "pivot")

    def test_leads_and_brought_tables_have_counts_and_win_rates(self):
        game = self.extract(format_id="gen9vgc2026regi")
        result = openings.aggregate([game])
        self.assertEqual(len(result["tables"]["leads_per_team"]), 2)
        p1_team = next(row for row in result["tables"]["leads_per_team"] if "Pikachu" in row["team_species"])
        self.assertEqual(dict(zip(p1_team["team_species"], p1_team["team_items"])),
                         {member.species: member.item for member in game.sides[0].team})
        self.assertEqual(p1_team["opposing_team_species"], tuple(sorted(P2)))
        self.assertEqual(p1_team["opposing_leads"], ("Gholdengo", "Incineroar"))
        self.assertEqual(p1_team["backs"], ("Charizard", "Indeedee-F"))
        self.assertEqual((p1_team["rating"], p1_team["opposing_rating"]), (1500, 1420))
        self.assertEqual((p1_team["source"], p1_team["format"], p1_team["count"], p1_team["wins"], p1_team["win_rate"]),
                         ("sv_vgc", "gen9vgc2026regi", 1, 1, 1.0))
        thunderbolt = next(row for row in result["tables"]["turn_1_actions"] if row["action"] == "Thunderbolt")
        self.assertEqual((thunderbolt["rating"], thunderbolt["opposing_rating"], thunderbolt["side"]),
                         (1500, 1420, 0))
        self.assertEqual((thunderbolt["leads"], thunderbolt["opposing_leads"], thunderbolt["target"],
                          thunderbolt["count"], thunderbolt["win_rate"]),
                         (("Pikachu", "Vivillon"), ("Gholdengo", "Incineroar"), "p2a: Incineroar", 1, 1.0))
        p1_switches = [row for row in result["tables"]["turn_1_actions"]
                       if row["action_kind"] == "switch" and row["leads"] == ("Pikachu", "Vivillon")]
        self.assertEqual([(row["action"], row["switch_context"]) for row in p1_switches], [("Charizard", "pivot")])
        p2_switches = [row for row in result["tables"]["turn_1_actions"]
                       if row["action_kind"] == "switch" and row["leads"] == ("Gholdengo", "Incineroar")]
        self.assertEqual([(row["action"], row["switch_context"]) for row in p2_switches], [("Pelipper", "replacement")])
        self.assertEqual(len(result["tables"]["species_brought"]), 8)
        pikachu = next(row for row in result["tables"]["species_brought"] if row["species"] == "Pikachu")
        self.assertEqual((pikachu["count"], pikachu["wins"], pikachu["win_rate"]), (1, 1, 1.0))

    def test_turn_one_actions_sort_targets_with_and_without_a_target(self):
        log = LOG.replace(
            "|move|p1a: Charizard|Thunderbolt|p2a: Incineroar|",
            "|move|p1a: Charizard|Thunderbolt|p2a: Incineroar|\n|move|p1a: Charizard|Thunderbolt|",
        )
        result = openings.aggregate([self.extract(log=log)])
        thunderbolts = [row for row in result["tables"]["turn_1_actions"] if row["action"] == "Thunderbolt"]
        self.assertEqual({row["target"] for row in thunderbolts}, {None, "p2a: Incineroar"})

    def test_excluding_terastallized_games_preserves_pool_compatibility_counts(self):
        game = self.extract(format_id="gen9vgc2026regi")
        result = openings.aggregate([game], exclude_terastallized=True)
        self.assertEqual(result["tables"]["leads_per_team"], [])
        self.assertEqual(result["tables"]["turn_1_actions"], [])
        self.assertEqual(result["tables"]["species_brought"], [])
        summary = result["tables"]["pool_compatibility"][0]
        self.assertEqual((summary["source"], summary["format"], summary["games"], summary["pool_compatible"],
                          summary["terastallized"]), ("sv_vgc", "gen9vgc2026regi", 1, 1, 1))
        self.assertEqual(result["counters"]["games.excluded.terastallized"], 1)

    def test_incompatible_species_move_and_item_are_reported_by_reason(self):
        game = self.extract(format_id="gen9vgc2026regi")
        self.assertEqual(game.pool_incompatible_reasons, ())
        unknown_move = LOG.replace("Thunderbolt", "Unknown Move")
        unknown_item = LOG.replace("Sitrus Berry", "Unknown Berry")
        unknown_species = LOG.replace("Pikachu", "Unknownmon")
        games = [self.extract(unknown_move, "gen9vgc2026regi"),
                 self.extract(unknown_item, "gen9vgc2026regi"),
                 self.extract(unknown_species, "gen9vgc2026regi")]
        self.assertEqual([game.pool_incompatible_reasons for game in games], [("move",), ("item",), ("species",)])
        summary = openings.aggregate(games)["tables"]["pool_compatibility"][0]
        self.assertEqual((summary["games"], summary["pool_incompatible"],
                          summary["pool_incompatible_species"], summary["pool_incompatible_move"],
                          summary["pool_incompatible_item"]), (3, 3, 1, 1, 1))

    def test_skip_names_match_the_replay_pipeline(self):
        with self.assertRaisesRegex(openings.OpeningSkip, "skip:session"):
            self.extract(LOG + "\n|deinit|")
        with self.assertRaisesRegex(openings.OpeningSkip, "skip:two-games"):
            self.extract(LOG + "\n|start|")
        with self.assertRaisesRegex(openings.OpeningSkip, "skip:sheets"):
            self.extract(LOG.replace("|showteam|p2|", "|missing|p2|"))

    def test_build_uses_shared_source_reader_and_writes_only_to_the_passed_directory(self):
        with tempfile.TemporaryDirectory(prefix="duoforge_openings_") as temp:
            root = Path(temp)
            source_file = root / "sample.jsonl"
            source_file.write_text("\n".join([
                json.dumps({"id": "included", "formatid": "gen9vgc2026regi", "log": LOG}),
                json.dumps({"id": "included-2", "formatid": "gen9vgc2026regi",
                            "log": LOG.replace("|win|Alice", "|win|Bob")}),
                json.dumps({"id": "not-vgc", "formatid": "gen9ou", "log": LOG}),
                json.dumps({"id": "bad-sheets", "formatid": "gen9vgc2026regi",
                            "log": LOG.replace("|showteam|p2|", "|future-line|malformed|")}),
            ]) + "\n", encoding="utf-8")
            guard_calls = []
            from duoforge_replay import dataset

            original_guard = dataset.refuse_repository

            def guard(path):
                original_guard(path)
                guard_calls.append(Path(path).resolve())
            stderr = io.StringIO()
            with mock.patch.object(dataset, "refuse_repository", side_effect=guard):
                with redirect_stderr(stderr):
                    serial = openings.build([source_file], root / "out-serial", self.data,
                                            unit_lines=1, workers=1, progress_interval=0.01)
                with redirect_stderr(stderr):
                    parallel = openings.build([source_file], root / "out-parallel", self.data,
                                              unit_lines=1, workers=2, progress_interval=0.01)
            self.assertEqual(guard_calls, [(root / "out-serial").resolve(), (root / "out-parallel").resolve()])
            serial_path = root / "out-serial" / "openings.json"
            parallel_path = root / "out-parallel" / "openings.json"
            self.assertTrue(serial_path.is_file())
            self.assertTrue(parallel_path.is_file())
            self.assertEqual(serial, parallel)
            self.assertEqual(serial["schema_version"], 2)
            self.assertEqual(serial_path.read_bytes(), parallel_path.read_bytes())
            self.assertEqual(serial["counters"]["games.processed"], 2)
            self.assertEqual(serial["counters"]["games.skipped.skip:format"], 1)
            self.assertEqual(serial["counters"]["games.skipped.skip:sheets"], 1)
            self.assertIn({"source": "sv_vgc", "format": "gen9vgc2026regi", "reason": "lines.unknown.future-line",
                           "count": 1}, serial["diagnostics"])
            self.assertEqual(json.loads(serial_path.read_text(encoding="utf-8")), serial)
            self.assertIn("4/4 units; 4 games read", stderr.getvalue())
            self.assertIn("2 worker(s)", stderr.getvalue())
            self.assertIn("elapsed", stderr.getvalue())

    def test_schema_two_keys_keep_items_matchups_backs_and_ratings_separate(self):
        from dataclasses import replace

        game = self.extract()
        own = game.sides[0]
        variants = [game,
                    replace(game, sides=(replace(own, rating=1600), game.sides[1])),
                    replace(game, sides=(replace(own, brought=None), game.sides[1])),
                    replace(game, sides=(replace(own, team=(openings.SpeciesItem(own.team[0].species, "other"),)
                                                         + own.team[1:]), game.sides[1])),
                    replace(game, sides=(own, replace(game.sides[1], leads=None)))]
        rows = [row for row in openings.aggregate(variants)["tables"]["leads_per_team"]
                if "Pikachu" in row["team_species"]]
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(row["count"] for row in rows), 5)
        self.assertTrue(any(row["backs"] is None for row in rows))
        self.assertTrue(any(row["opposing_leads"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
