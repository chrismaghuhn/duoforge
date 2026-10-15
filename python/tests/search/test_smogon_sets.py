"""duoforge.python.smogon_sets: the closed-sheet set prior from the registry's whole sets and Smogon's usage statistics
(duoforge_search.smogon_sets, decision 0081, #385 step 3). Made-up stats and a made-up registry; the committed table is
checked against its pin and the engine."""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from duoforge_live import data
from duoforge_search import smogon_sets as S
from duoforge_search import smogon_spreads as ss

FARIGIRAF = """Farigiraf (F) @ Sitrus Berry
Ability: Armor Tail
Level: 50
EVs: 32 HP / 20 Def / 14 SpD
Bold Nature
- Psychic
- Trick Room
- Helping Hand
- Protect
"""


def paste(species, item, ability, nature, moves, gender="F"):
    return (f"{species} ({gender}) @ {item}\nAbility: {ability}\nLevel: 50\n{nature} Nature\n"
            + "".join(f"- {m}\n" for m in moves))


def entry(items, abilities, spreads, moves):
    return {"Items": items, "Abilities": abilities, "Spreads": spreads, "Moves": moves}


def sources(data_by_name, cutoff=1760):
    return {(fmt, c): {"info": {"number of battles": 1000}, "data": data_by_name if (fmt, c) == (ss.FORMATS[0], cutoff)
                       else {}} for fmt in ss.FORMATS for c in ss.CUTOFFS}


class Registry:
    """A made-up registry: index.json and one paste per team."""

    def __init__(self, teams, test=None):
        self.tmp = tempfile.TemporaryDirectory()
        if test is not None:
            test.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        index = {"registry": {}, "teams": [{"id": f"T{i}"} for i in range(len(teams))]}
        (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
        for i, text in enumerate(teams):
            (root / f"T{i}.txt").write_text(text, encoding="utf-8")
        self.root = root


class SmogonSetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = data.load(kind="pool")
        cls.names = S.Names(cls.data.context())

    def test_a_registry_set_counts_once_per_team_and_a_mega_stone_names_its_bucket(self):
        lucario = paste("Lucario", "Lucarionite", "Inner Focus", "Jolly", ["Close Combat", "Meteor Mash", "Protect",
                                                                          "Extreme Speed"], gender="M")
        reg = Registry([FARIGIRAF + "\n" + lucario, FARIGIRAF, FARIGIRAF.replace("Bold", "Calm")], self)
        sets, counts = S.registry_sets(reg.root, self.names, self.data)
        bold = ("sitrusberry", "armortail", "bold", ("helpinghand", "protect", "psychic", "trickroom"))
        self.assertEqual(sets["farigiraf"]["farigiraf"][bold], 2)  # two teams, once each
        self.assertEqual(sum(sets["farigiraf"]["farigiraf"].values()), 3)
        self.assertEqual(list(sets["lucario"]), ["lucariomega"])  # the stone: the Mega forme's bucket
        self.assertEqual(counts["registry.teams"], 3)

    def test_a_set_the_engine_refuses_is_counted_by_name_never_kept(self):
        bad = paste("Grimmsnarl", "Light Clay", "Prankster", "Sassy", ["Snarl", "Reflect", "Light Screen", "Parting Shot"],
                    gender="M")
        unknown = paste("Farigiraf", "Sitrus Berry", "Armor Tail", "Bold", ["Psychic", "Notamove", "Protect", "Trick Room"])
        reg = Registry([bad, unknown, FARIGIRAF], self)
        sets, counts = S.registry_sets(reg.root, self.names, self.data)
        self.assertEqual(counts["registry.refused.setup"], 1)  # Grimmsnarl does not learn Snarl in the pool tables
        self.assertEqual(counts["registry.refused.name"], 1)
        self.assertNotIn("grimmsnarl", sets)
        self.assertEqual(sum(sets["farigiraf"]["farigiraf"].values()), 1)

    def test_a_team_the_registry_marks_pending_is_skipped_and_counted_by_its_reason(self):
        """#406: a team marked "status": "pending" stays in the registry but gives no set; it is counted by its reason."""
        reg = Registry([FARIGIRAF, FARIGIRAF.replace("Bold", "Calm")], self)
        index = json.loads((reg.root / "index.json").read_text(encoding="utf-8"))
        index["teams"][1].update(status="pending", status_reason="#406: 0 SP with Serious")
        (reg.root / "index.json").write_text(json.dumps(index), encoding="utf-8")
        sets, counts = S.registry_sets(reg.root, self.names, self.data)
        self.assertEqual(sum(sets["farigiraf"]["farigiraf"].values()), 1)  # the Bold team only
        self.assertEqual(counts["registry.teams"], 1)
        self.assertEqual(counts["registry.pending.#406: 0 SP with Serious"], 1)

    def test_marginals_take_the_highest_cutoff_with_enough_weight_and_engine_names(self):
        heavy = ss.MIN_WEIGHT
        src = sources({"Farigiraf": entry({"sitrusberry": heavy, "nothing": heavy}, {"armortail": 2 * heavy},
                                          {"Bold:32/0/20/0/14/0": 2 * heavy}, {"trickroom": 2 * heavy, "": heavy}),
                       "Notamon": entry({}, {"x": 1.0}, {}, {})})
        chosen, counts = S.marginals(src, self.names)
        m = chosen["farigiraf"]
        self.assertEqual((m["cutoff"], m["species"]), (1760, "farigiraf"))
        self.assertEqual(dict(m["item"]), {"sitrusberry": heavy, "": heavy})  # "nothing" is no item
        self.assertEqual(dict(m["move"]), {"trickroom": 2 * heavy})  # an empty slot is no move
        self.assertEqual(counts["smogon.outside_context"], 1)

    def test_a_species_takes_one_cutoff_for_all_its_buckets(self):
        """Review of 2026-10-12: a base species and its Mega forme at different cutoffs mixed weights of different scales
        (Aggron's stone at 9 % instead of 97 %). The species takes the highest cutoff where all its buckets together
        weigh enough, and every bucket is read there."""
        light, heavy = 2.0, 30.0
        base = {"Lucario": entry({"lifeorb": light}, {"innerfocus": light}, {"Jolly:0/32/0/0/2/32": light},
                                 {"closecombat": 4 * light})}
        mega = {"Lucario-Mega": entry({"lucarionite": heavy}, {"adaptability": heavy}, {"Jolly:0/32/0/0/2/32": heavy},
                                      {"closecombat": 4 * heavy})}
        src = sources({**base, **mega})
        for name, e in (("Lucario", base["Lucario"]), ("Lucario-Mega", mega["Lucario-Mega"])):
            big = entry({k: 50 * v for k, v in e["Items"].items()}, {k: 50 * v for k, v in e["Abilities"].items()},
                        {k: 50 * v for k, v in e["Spreads"].items()}, {k: 50 * v for k, v in e["Moves"].items()})
            src[(ss.FORMATS[0], 1500)]["data"][name] = big
        src[(ss.FORMATS[0], 1500)]["data"]["Lucario"]["Items"] = {"lifeorb": 50 * 50 * light}  # base heavy at 1500
        chosen, _ = S.marginals(src, self.names)
        self.assertEqual((chosen["lucario"]["cutoff"], chosen["lucariomega"]["cutoff"]), (1760, 1760))
        self.assertEqual((chosen["lucario"]["weight"], chosen["lucariomega"]["weight"]), (light, heavy))

    def test_move_shares_count_the_sets_with_empty_slots(self):
        """Review of 2026-10-12: Smogon's Moves sum to four slots per set, empty ones ("") included. A move's share of
        sets is its weight over the species' weight, not over the filled slots."""
        src = sources({"Farigiraf": entry({"sitrusberry": 100.0}, {"armortail": 100.0}, {"Bold:32/0/20/0/14/0": 100.0},
                                          {"protect": 100.0, "trickroom": 50.0, "": 250.0})})
        chosen, _ = S.marginals(src, self.names)
        support = [("sitrusberry", "armortail", "bold", ("protect", "trickroom")), ("sitrusberry", "armortail", "bold",
                                                                                  ("protect",))]
        goal, uncovered = S.targets(chosen["farigiraf"], support, [1, 1], mega=False)
        self.assertAlmostEqual(goal["move"]["protect"], 1.0)
        self.assertAlmostEqual(goal["move"]["trickroom"], 0.5)
        self.assertAlmostEqual(uncovered["move"], 0.0)

    def test_targets_of_a_support_smogon_does_not_cover_are_the_supports_own(self):
        support = [("mentalherb", "armortail", "bold", ("protect",))]
        marginal = {"weight": 100.0, "item": Counter({"sitrusberry": 100.0}), "ability": Counter({"armortail": 100.0}),
                    "nature": Counter({"bold": 100.0}), "move": Counter({"protect": 100.0})}
        goal, uncovered = S.targets(marginal, support, [1], mega=False)
        self.assertEqual(goal["item"], {"mentalherb": 1.0})
        self.assertAlmostEqual(uncovered["item"], 1.0)

    def test_raking_meets_feasible_marginals(self):
        support = [("a", "x", "bold", ("m1", "m2")), ("b", "x", "bold", ("m1", "m3")), ("a", "x", "calm", ("m2", "m3")),
                   ("b", "x", "calm", ("m1", "m2"))]
        # the shares of the weights 0.3, 0.1, 0.4, 0.2: a goal some weights meet
        goal = {"item": {"a": 0.7, "b": 0.3}, "ability": {"x": 1.0}, "nature": {"bold": 0.4, "calm": 0.6},
                "move": {"m1": 0.6, "m2": 0.9, "m3": 0.5}}
        weights = S.rake(support, [1, 1, 1, 1], goal)
        self.assertAlmostEqual(sum(weights), 1.0)
        self.assertLess(S.residual(support, weights, goal), 1e-3)

    def test_a_part_smogon_never_saw_keeps_a_small_weight(self):
        support = [("sitrusberry", "armortail", "bold", ("protect",)), ("mentalherb", "armortail", "bold", ("protect",))]
        marginal = {"weight": 1000.0, "item": Counter({"sitrusberry": 1000.0}), "ability": Counter({"armortail": 1000.0}),
                    "nature": Counter({"bold": 1000.0}), "move": Counter({"protect": 1000.0})}
        goal, uncovered = S.targets(marginal, support, [1, 1], mega=False)
        self.assertGreater(goal["item"]["mentalherb"], 0.0)
        self.assertLess(goal["item"]["mentalherb"], 0.02)
        self.assertEqual(uncovered["item"], 0.0)
        weights = S.rake(support, [1, 1], goal)
        self.assertGreater(weights[1], 0.0)

    def test_a_mega_bucket_has_no_ability_marginal(self):
        support = [("lucarionite", "innerfocus", "jolly", ("closecombat",))]
        marginal = {"weight": 100.0, "item": Counter({"lucarionite": 100.0}), "ability": Counter({"adaptability": 100.0}),
                    "nature": Counter({"jolly": 100.0}), "move": Counter({"closecombat": 100.0})}
        goal, uncovered = S.targets(marginal, support, [1], mega=True)
        self.assertNotIn("ability", goal)
        self.assertNotIn("ability", uncovered)

    def test_smogon_mass_outside_the_support_is_counted(self):
        support = [("sitrusberry", "armortail", "bold", ("protect", "trickroom"))]
        marginal = {"weight": 100.0, "item": Counter({"sitrusberry": 60.0, "colburberry": 40.0}),
                    "ability": Counter({"armortail": 100.0}), "nature": Counter({"bold": 100.0}),
                    "move": Counter({"protect": 100.0, "trickroom": 100.0, "psychic": 200.0})}
        _, uncovered = S.targets(marginal, support, [1], mega=False)
        self.assertAlmostEqual(uncovered["item"], 0.4)
        self.assertAlmostEqual(uncovered["move"], 0.5)

    def test_synthesized_sets_follow_the_rules_and_are_deterministic(self):
        marginal = {"weight": 500.0, "item": Counter({"choicescarf": 400.0, "sitrusberry": 100.0}),
                    "ability": Counter({"armortail": 500.0}), "nature": Counter({"bold": 300.0, "calm": 200.0}),
                    "move": Counter({"protect": 500.0, "trickroom": 450.0, "psychic": 400.0, "helpinghand": 300.0,
                                     "hypervoice": 200.0, "thunderbolt": 150.0})}
        a, counts = S.synthesize("farigiraf", marginal, None, self.names, self.data, "farigiraf", None)
        b, _ = S.synthesize("farigiraf", marginal, None, self.names, self.data, "farigiraf", None)
        self.assertEqual(a, b)
        self.assertEqual(len(a), S.SYNTH_SETS)
        for item, ability, nature, moves in a:
            self.assertEqual(len(set(moves)), 4)
            if item == "choicescarf":
                self.assertFalse(set(moves) & set(S.CHOICE_EXCLUDED), moves)
            self.assertTrue(S.legal(self.data, "farigiraf", (item, ability, nature, moves)))
        self.assertTrue(any(s[0] == "choicescarf" for s in a))

    def test_a_mega_buckets_synthesized_sets_hold_the_stone_and_a_base_ability(self):
        marginal = {"weight": 500.0, "item": Counter({"lucarionite": 500.0}), "ability": Counter({"adaptability": 500.0}),
                    "nature": Counter({"jolly": 500.0}),
                    "move": Counter({"closecombat": 500.0, "meteormash": 500.0, "extremespeed": 500.0, "protect": 500.0})}
        base = {"ability": Counter({"innerfocus": 10.0})}
        drawn, counts = S.synthesize("lucariomega", marginal, base, self.names, self.data, "lucario", "lucarionite")
        self.assertTrue(drawn)
        self.assertEqual({(s[0], s[1]) for s in drawn}, {("lucarionite", "innerfocus")})
        self.assertEqual(counts["synth.ability_from_base"], 1)

    def test_a_forme_smogon_lumps_with_its_dex_sibling_takes_the_siblings_legal_sets(self):
        """Smogon counts Toxtricity-Low-Key under "Toxtricity"; the engine has two species (Plus or Minus) with one dex
        number. The forme the table lacks takes the sets of its dex sibling that its own setup accepts, counted."""
        toxtricity = paste("Toxtricity", "Life Orb", "Punk Rock", "Modest", ["Overdrive", "Sludge Bomb", "Boomburst",
                                                                                "Protect"], gender="M")
        plus = toxtricity.replace("Punk Rock", "Plus")
        reg = Registry([toxtricity, plus, toxtricity.replace("Modest", "Timid"), plus.replace("Modest", "Timid")], self)
        src = sources({"Toxtricity": entry({"lifeorb": 100.0}, {"punkrock": 80.0, "plus": 20.0},
                                           {"Modest:0/0/0/32/2/32": 60.0, "Timid:0/0/0/32/2/32": 40.0},
                                           {"overdrive": 100.0, "sludgebomb": 100.0, "boomburst": 100.0, "protect": 100.0})})
        table = S.build(src, self.data, self.names, registry_root=reg.root)
        self.assertIn("toxtricity", table["species"])
        low_key = table["species"]["toxtricitylowkey"]["sets"]
        self.assertTrue(low_key)
        self.assertEqual({s[1] for s in low_key}, {"punkrock"})  # Plus is not a Low-Key ability
        self.assertEqual(sum(s[4] for s in low_key), S.RESOLUTION)
        self.assertEqual(table["derivation"]["species.from_dex_sibling"], 1)

    def test_a_forme_with_other_types_or_several_siblings_takes_no_siblings_sets(self):
        """Review of 2026-10-12: Tauros-Paldea-Combat (Fighting) is no forme Smogon counts under "Tauros" (Normal); a
        missing forme of another type, or with more than one sibling in the table, gets no sets (no data, not lumped)."""
        tauros = paste("Tauros", "Expert Belt", "Intimidate", "Jolly", ["Body Slam", "Iron Head", "Close Combat",
                                                                       "Protect"], gender="M")
        reg = Registry([tauros, tauros.replace("Jolly", "Adamant"), tauros.replace("Iron Head", "Rock Slide"),
                        tauros.replace("Body Slam", "Double-Edge")], self)
        src = sources({"Tauros": entry({"expertbelt": 100.0}, {"intimidate": 100.0}, {"Jolly:0/32/0/0/2/32": 100.0},
                                       {"bodyslam": 100.0, "ironhead": 100.0, "closecombat": 100.0, "protect": 100.0})})
        table = S.build(src, self.data, self.names, registry_root=reg.root)
        self.assertIn("tauros", table["species"])
        self.assertNotIn("taurospaldeacombat", table["species"])

    def test_marginals_the_engine_cannot_draw_from_are_refused_by_name(self):
        """A bucket whose Smogon items are all unknown to the tables (or that has fewer than four moves: Ditto) gives no
        synthesized set, counted, never a crash."""
        marginal = {"weight": 100.0, "item": Counter(), "ability": Counter({"armortail": 100.0}),
                    "nature": Counter({"bold": 100.0}),
                    "move": Counter({"protect": 100.0, "trickroom": 100.0, "psychic": 100.0, "helpinghand": 100.0})}
        drawn, counts = S.synthesize("farigiraf", marginal, None, self.names, self.data, "farigiraf", None)
        self.assertEqual((drawn, counts["synth.refused.marginals"]), ([], 1))

    def test_whole_draws_by_largest_remainders(self):
        probs = Counter({("a", "x", "bold", ("m",)): 0.5, ("b", "x", "bold", ("m",)): 0.3333,
                         ("c", "x", "bold", ("m",)): 0.1667})
        out = S._quantize(probs, Counter())
        self.assertEqual([(s[0], s[4]) for s in out["sets"]], [("a", 5000), ("b", 3333), ("c", 1667)])

    def test_the_stats_are_refused_inside_the_repository(self):
        with self.assertRaises(SystemExit) as caught:
            S.main(["--stats", str(Path(S.__file__).resolve().parents[2] / "data"), "--check"])
        self.assertIn("inside the repository", str(caught.exception))


class CommittedTableTest(unittest.TestCase):
    """The committed table: its pin, its credit and its sources, and every set one the engine accepts."""

    def test_the_committed_table_is_pinned_credited_and_legal(self):
        table = S.load_table(S.TABLE_PATH, S.TABLE_SHA256)
        self.assertEqual(table["source"]["credit"], ss.CREDIT)
        self.assertEqual(table["source"]["files"], ss.SOURCES)
        d = data.load(kind="pool")
        sets = 0
        for species, e in table["species"].items():
            self.assertEqual(sum(s[4] for s in e["sets"]), S.RESOLUTION, species)
            for item, ability, nature, moves, n in e["sets"]:
                self.assertTrue(S.legal(d, species, (item, ability, nature, tuple(moves))), (species, item, moves))
                sets += 1
        self.assertGreater(sets, 5000)
        with self.assertRaises(ValueError):
            S.load_table(S.TABLE_PATH, "0" * 64)


if __name__ == "__main__":
    unittest.main()
