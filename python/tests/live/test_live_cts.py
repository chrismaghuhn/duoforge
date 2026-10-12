"""duoforge.python.live_cts: the particle tracker of closed team sheets (decision 0081).

The stream is the live client's fixture (python/tests/support/data/live_stream_ab.json: what the pinned Showdown sends p1,
Team A against Team B, with open team sheets) without its |showteam| lines: what a closed-sheet battle sends. The foe is
Team B. Turn 1: Farigiraf uses Protect, its Armor Tail stops Ceruledge's Shadow Sneak, Grimmsnarl uses Spirit Break.
Turn 2: Grimmsnarl uses Spirit Break, Farigiraf uses Trick Room.
"""
import json
import unittest

import numpy as np

from duoforge_live import cts, data, lines, teams, tracker

FIXTURE = json.loads((data.ROOT / "python" / "tests" / "support" / "data" / "live_stream_ab.json").read_text(encoding="utf-8"))
SEED, KEY = 7, "battle-gen9championsvgc2026regmc-1"


def closed(messages):
    """The messages without their |showteam| lines (a closed-sheet stream)."""
    return [[line for line in m if not line.startswith("|showteam|")] for m in messages]


def foe_sets():
    return teams._paste(FIXTURE["foe_team"])


def with_species(sets, species, *alternatives):
    """A prior of the true foe sets, where `species` has `alternatives` (paste blocks) besides or instead of its own."""
    return [s for s in sets if s["species"] != species] + [a for block in alternatives for a in teams._paste(block)]


def farigiraf(item="Sitrus Berry", ability="Armor Tail", moves=("Psychic", "Grass Knot", "Trick Room", "Protect")):
    return (f"Farigiraf (F) @ {item}\nAbility: {ability}\nLevel: 50\nBold Nature\n"
            + "".join(f"- {m}\n" for m in moves))


class Run:
    """Feeds a tracker (open or particle) message by message and keeps what it shows at each decision point."""

    def __init__(self, t, messages, upto=None):
        self.t, self.points = t, []
        done = 0
        for m in messages[:upto]:
            t.feed(m)
            if t.ready and t.epoch > done:
                done = t.epoch
                self.points.append(self.snapshot())
                t.accepted(FIXTURE["inputs"][done - 1])

    def snapshot(self):
        t = self.t
        if isinstance(t, cts.ParticleTracker):
            return {"epoch": t.epoch, "request": t.request,
                    "sets": [tuple(_set_key(s) for s in p.sets) for p in t.particles],
                    "parts": t.public_parts(), "observations": t.observations(), "domain": t.domain()[0].tobytes()}
        return {"epoch": t.epoch, "request": t.request, "parts": t.public_parts(),
                "observation": t.observation().tobytes(), "domain": t.domain()[0].tobytes()}


def _set_key(s):
    return (s["species"], s["item"], s["ability"], tuple(sorted(s["moves"])), s["nature"])


class CtsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = data.load(kind="pool")

    def particles(self, sets, n=8, seed=SEED, key=KEY):
        return cts.ParticleTracker(self.data, FIXTURE["team"], cts.SetPrior(self.data, sets), seed=seed, key=key, n=n)

    def run_closed(self, sets, upto=None, **kw):
        return Run(self.particles(sets, **kw), closed(FIXTURE["messages"]), upto)

    def held(self, run, point, species):
        """The sets of `species` the particles hold at decision point `point`."""
        return [s for p in run.points[point]["sets"] for s in p if s[0] == species]

    # ---------------------------------------------------------------- the open-sheet tracker is unchanged
    def test_the_sheet_hook_is_off_for_a_plain_tracker(self):
        self.assertFalse(tracker.Tracker.check_foe_sheet)
        self.assertFalse(tracker.Tracker(self.data, FIXTURE["team"]).check_foe_sheet)

    def test_a_particle_with_the_true_team_shows_what_the_open_sheets_show(self):
        """The pin of decision 0081: at every decision point, every particle's observation, domain and public parts
        (record, status, causes, reason) are those of the open-sheet tracker, byte for byte."""
        open_run = Run(tracker.Tracker(self.data, FIXTURE["team"]), FIXTURE["messages"])
        run = self.run_closed(foe_sets(), n=3)
        self.assertEqual(len(run.points), len(open_run.points))
        self.assertEqual(len(run.points), 4)  # team preview and turns 1 to 3
        for point, want in zip(run.points, open_run.points):
            self.assertEqual((point["epoch"], point["request"], point["domain"]),
                             (want["epoch"], want["request"], want["domain"]))
            self.assertEqual(len(point["parts"]), 3)
            for parts, observation in zip(point["parts"], point["observations"]):
                self.assertEqual(observation.tobytes(), want["observation"])
                self.assertEqual((parts["status"], parts["causes"], parts["reason"]),
                                 (want["parts"]["status"], want["parts"]["causes"], want["parts"]["reason"]))
                self.assertEqual(parts["record"].tobytes(), want["parts"]["record"].tobytes())
                self.assertEqual(parts["observation"].tobytes(), want["parts"]["observation"].tobytes())
        self.assertEqual(sum(v for k, v in run.t.counters.items() if k.startswith("redraw.")), 0)

    def test_nothing_is_ready_before_the_team_preview_request(self):
        t = self.particles(foe_sets())
        for m in closed(FIXTURE["messages"])[:2]:
            t.feed(m)
        self.assertFalse(t.ready)
        self.assertIsNone(t.particles)

    # ---------------------------------------------------------------- conditioning on the prefix only
    def test_a_move_counts_from_its_first_line_on_never_before(self):
        """No hindsight (HauptSession, 2026-10-12): Trick Room is first used on turn 2. Before its line, the particles
        still hold Farigiraf's set without it; from its line on, none does."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        run = self.run_closed(sets, n=16)
        before = self.held(run, 2, "Farigiraf")  # turn 2's decision: Protect seen, Trick Room not yet
        after = self.held(run, 3, "Farigiraf")
        self.assertTrue(any("Helping Hand" in s[3] for s in before), before)
        self.assertTrue(all("Trick Room" in s[3] for s in after), after)
        self.assertGreater(run.t.counters["redraw.facts"], 0)

    def test_the_particles_of_a_prefix_do_not_depend_on_the_rest_of_the_stream(self):
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        full = self.run_closed(sets, n=16)
        for upto in (4, 6, 8):
            prefix = self.run_closed(sets, upto=upto, n=16)
            self.assertEqual([p["sets"] for p in prefix.points], [p["sets"] for p in full.points[:len(prefix.points)]])

    # ---------------------------------------------------------------- contradictions
    def test_a_choice_lock_against_a_later_different_move_is_never_kept(self):
        """#423: Farigiraf uses Protect, then Trick Room in the next turn without leaving. A Choice Scarf set would have
        been locked into Protect: the particles that drew it are redrawn."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Choice Scarf"))
        run = self.run_closed(sets, n=16)
        self.assertTrue(any(s[1] == "Choice Scarf" for s in self.held(run, 2, "Farigiraf")))
        self.assertFalse(any(s[1] == "Choice Scarf" for s in self.held(run, 3, "Farigiraf")))
        self.assertGreater(run.t.counters["redraw.choice-lock"], 0)

    def test_the_hook_finds_a_choice_lock_and_a_move_off_the_set(self):
        def fold(sheet):
            t = tracker.Tracker(self.data, FIXTURE["team"])
            t.check_foe_sheet = True
            packed = teams.pack(sheet)
            for m in FIXTURE["messages"][:9]:
                t.feed([line if not line.startswith("|showteam|p2|") else "|showteam|p2|" + packed for line in m])
                if t.ready and t.request.get("teamPreview"):
                    t.accepted(FIXTURE["inputs"][0])

        true = FIXTURE["foe_team"]
        fold(true)  # the true sheet: no contradiction
        for block, reason in ((farigiraf(item="Choice Scarf"), "choice-lock"),
                              (farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")), "move-not-on-set")):
            sheet = teams.to_text([s if s["species"] != "Farigiraf" else teams._paste(block)[0]
                                   for s in teams._paste(true)])
            with self.assertRaises(tracker.SheetContradiction) as caught:
                fold(sheet)
            self.assertEqual(caught.exception.reason, reason)

    def test_a_revealed_ability_is_never_contradicted(self):
        """Turn 1: `cant|p2b: Farigiraf|ability: Armor Tail|...` shows Farigiraf's ability."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(ability="Cud Chew"))
        run = self.run_closed(sets, n=16)
        self.assertTrue(any(s[2] == "Cud Chew" for s in self.held(run, 1, "Farigiraf")))  # before turn 1's lines
        for point in (2, 3):
            self.assertFalse(any(s[2] == "Cud Chew" for s in self.held(run, point, "Farigiraf")), point)

    def test_a_used_move_off_every_set_stops_by_name(self):
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        with self.assertRaises(lines.Stop) as caught:
            self.run_closed(sets)
        self.assertEqual(caught.exception.reason, "cts:no-consistent-set Farigiraf")

    def test_a_species_without_a_set_stops_at_team_preview(self):
        sets = [s for s in foe_sets() if s["species"] != "Politoed"]
        t = self.particles(sets)
        with self.assertRaises(lines.Stop) as caught:
            for m in closed(FIXTURE["messages"])[:3]:
                t.feed(m)
        self.assertEqual(caught.exception.reason, "cts:no-consistent-set Politoed")

    def test_the_item_clause_holds_in_every_particle(self):
        # Grimmsnarl and Farigiraf may both hold a Sitrus Berry: no particle has both
        grimm = FIXTURE["foe_team"].split("\n\n")[0].replace("@ Light Clay", "@ Sitrus Berry")
        sets = with_species(with_species(foe_sets(), "Grimmsnarl", FIXTURE["foe_team"].split("\n\n")[0], grimm),
                            "Farigiraf", farigiraf(), farigiraf(item="Mental Herb"))
        run = self.run_closed(sets, n=16)
        for point in run.points:
            for team in point["sets"]:
                items = [s[1] for s in team if s[1]]
                self.assertEqual(len(items), len(set(items)), team)
        self.assertGreater(run.t.counters["redraw.item-clause"], 0)

    def test_a_team_the_item_clause_forbids_stops_after_the_redraw_cap(self):
        grimm = FIXTURE["foe_team"].split("\n\n")[0].replace("@ Light Clay", "@ Sitrus Berry")
        sets = with_species(foe_sets(), "Grimmsnarl", grimm)  # Farigiraf holds the Sitrus Berry as well
        with self.assertRaises(lines.Stop) as caught:
            self.run_closed(sets, upto=3)
        self.assertEqual(caught.exception.reason, "cts:redraw-cap item-clause")

    def test_a_line_every_draw_stops_at_stops_the_tracker_by_name(self):
        """A Substitute stops the open-sheet tracker whatever the sheets: every draw stops at it (in the same batch,
        Farigiraf's Protect contradicts half of the particles), and after MAX_ATTEMPTS the tracker stops by name, with the
        open tracker's Stop as the cause."""
        messages = closed(FIXTURE["messages"])
        messages[6] = messages[6][:2] + ["|-start|p2a: Grimmsnarl|Substitute"] + messages[6][2:]
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Trick Room", "Helping Hand")))
        for n in (1, 16):
            with self.assertRaises(lines.Stop) as caught:
                Run(self.particles(sets, n=n), messages)
            self.assertEqual(caught.exception.reason, "cts:redraw-cap stop:feature:SUBSTITUTE", n)
            self.assertEqual(caught.exception.__cause__.reason, "feature:SUBSTITUTE", n)

    def test_an_item_clause_that_few_draws_keep_costs_no_fold(self):
        """Grimmsnarl and Farigiraf hold a Sitrus Berry in 400 of 401 sets each: about 1 draw in 200 keeps the Item
        Clause. Draws are cheap (no fold), so every particle finds one."""
        grimm = FIXTURE["foe_team"].split("\n\n")[0]
        sitrus = teams._paste(grimm.replace("@ Light Clay", "@ Sitrus Berry"))[0]
        sets = [(s, 1) for s in foe_sets() if s["species"] not in ("Grimmsnarl", "Farigiraf")]
        sets += [(sitrus, 400), (teams._paste(grimm)[0], 1),
                 (teams._paste(farigiraf())[0], 400), (teams._paste(farigiraf(item="Mental Herb"))[0], 1)]
        t = cts.ParticleTracker(self.data, FIXTURE["team"], cts.SetPrior(self.data, sets), seed=SEED, key=KEY, n=16)
        Run(t, closed(FIXTURE["messages"]), upto=3)
        self.assertEqual(len(t.particles), 16)
        self.assertGreater(t.counters["redraw.item-clause"], 16 * 64)

    def test_the_parts_are_those_of_the_decision_point(self):
        """The parts are taken when a decision point's request is folded: none before the first, and a particle redrawn
        later in the turn has the next decision point's only."""
        t = self.particles(foe_sets())
        with self.assertRaises(ValueError):
            t.public_parts()
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        t = self.particles(sets, n=16)
        messages = closed(FIXTURE["messages"])
        Run(t, messages, upto=8)  # turn 2's request
        t.feed(messages[8])  # turn 2's lines: Trick Room redraws the particles without it, mid-turn
        self.assertGreater(t.counters["redraw.facts"], 0)
        with self.assertRaises(ValueError):
            t.public_parts()
        t.feed(messages[9])  # turn 3's request
        self.assertEqual(len(t.public_parts()), 16)

    def test_facts_the_log_cannot_give_stop_by_name(self):
        messages = closed(FIXTURE["messages"])
        messages[6] = messages[6][:2] + ["|-transform|p2a: Grimmsnarl|p1a: Ceruledge"] + messages[6][2:]
        with self.assertRaises(lines.Stop) as caught:
            Run(self.particles(foe_sets()), messages)
        self.assertEqual(caught.exception.reason, "cts:facts skip:belief-transform")

    # ---------------------------------------------------------------- determinism
    def test_the_draw_is_deterministic_under_seed_and_key(self):
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Choice Scarf"),
                            farigiraf(item="Mental Herb"))
        a = self.run_closed(sets, n=16)
        b = self.run_closed(sets, n=16)
        self.assertEqual([p["sets"] for p in a.points], [p["sets"] for p in b.points])
        self.assertEqual(a.t.counters, b.t.counters)
        other = self.run_closed(sets, n=16, seed=SEED + 1)
        self.assertNotEqual([p["sets"] for p in a.points], [p["sets"] for p in other.points])

    def test_the_draw_follows_the_weights(self):
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Mental Herb"))
        prior = cts.SetPrior(self.data, [(s, 1 if s["item"] != "Mental Herb" else 0) for s in sets])
        t = cts.ParticleTracker(self.data, FIXTURE["team"], prior, seed=SEED, key=KEY, n=16)
        Run(t, closed(FIXTURE["messages"]), upto=3)
        self.assertFalse(any(s["item"] == "Mental Herb" for p in t.particles for s in p.sets))

    def test_the_prior_refuses_a_set_the_engine_refuses(self):
        # Grimmsnarl does not learn Snarl in the pool tables (data.setup_issue)
        bad = teams._paste(FIXTURE["foe_team"].split("\n\n")[0].replace("- Spirit Break", "- Snarl"))
        with self.assertRaises(ValueError):
            cts.SetPrior(self.data, bad)


class WordTest(unittest.TestCase):
    def test_the_word_is_the_replays(self):
        from duoforge_replay import setbelief
        self.assertEqual(cts.word(SEED, KEY, 1, 2, 3, 4), setbelief.word(SEED, KEY, 1, 2, 3, 4))
        self.assertIsInstance(np.uint64(cts.word(1, "k", 0, 0, 0, 0)), np.uint64)


if __name__ == "__main__":
    unittest.main()
