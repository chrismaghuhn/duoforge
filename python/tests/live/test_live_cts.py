"""duoforge.python.live_cts: the particle tracker of closed team sheets (decision 0081).

The stream is the live client's fixture (python/tests/support/data/live_stream_ab.json: what the pinned Showdown sends p1,
Team A against Team B, with open team sheets) without its |showteam| lines: what a closed-sheet battle sends. The foe is
Team B. Turn 1: Farigiraf uses Protect, its Armor Tail stops Ceruledge's Shadow Sneak, Grimmsnarl uses Spirit Break.
Turn 2: Grimmsnarl uses Spirit Break, Farigiraf uses Trick Room.
"""
import hashlib
import json
import unittest

import numpy as np

from duoforge import features
from duoforge_live import cts, data, game, lines, options, search as live_search, teams, tracker
from python.tests.live.test_live_client import FakePolicy

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
        """Two streams with the same first turn and different second turns (Trick Room, or Helping Hand) give the same
        particles up to turn 2's decision point, and different ones after."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        other = closed(FIXTURE["messages"])
        other[8] = [line.replace("|move|p2b: Farigiraf|Trick Room|p2b: Farigiraf", "|move|p2b: Farigiraf|Helping Hand|p2a: Grimmsnarl")
                    for line in other[8] if not line.startswith("|-fieldstart|move: Trick Room")]
        self.assertNotEqual(other[8], closed(FIXTURE["messages"])[8])
        a = self.run_closed(sets, n=16)
        b = Run(self.particles(sets, n=16), other)
        self.assertEqual([p["sets"] for p in a.points[:3]], [p["sets"] for p in b.points[:3]])
        self.assertNotEqual(a.points[3]["sets"], b.points[3]["sets"])

    def test_a_redrawn_particle_passes_the_engine_check_of_every_earlier_decision_point(self):
        """Review of 2026-10-12: a particle drawn anew mid-game is folded from the start, and its record must pass the
        engine's check at every decision point it folds, as a kept particle's did. Here the check refuses Farigiraf's
        Mental Herb set at turn 1's decision point (a stand-in for a refusal such as Damp Rock's); turn 2's Trick Room
        then redraws the particles without it, and none of them may come back with the Mental Herb set."""
        from unittest import mock
        real = tracker.Tracker.public_parts

        def checked(t):
            if t.epoch == 2 and any(s["species"] == "Farigiraf" and s["item"] == "MentalHerb" for s in t.foe_sets):
                raise ValueError("the engine does not take the assembled record back: DUOFORGE_E_MALFORMED (stand-in)")
            return real(t)
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Mental Herb"),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        with mock.patch.object(tracker.Tracker, "public_parts", checked):
            run = self.run_closed(sets, n=16)
        self.assertGreater(run.t.counters["redraw.facts"], 0)
        self.assertGreater(run.t.counters["redraw.error:ValueError"], 0)
        for point in (2, 3):
            self.assertFalse(any(s[1] == "Mental Herb" for s in self.held(run, point, "Farigiraf")), point)

    def test_a_battle_line_before_the_team_preview_fails_as_it_fails_an_open_tracker(self):
        """Review of 2026-10-12: before the preview request the particle tracker folds the lines as an open tracker
        does: a battle line before the sheets raises, and a battle over before them has ended."""
        messages = closed(FIXTURE["messages"])
        switch = "|switch|p2a: Grimmsnarl|Grimmsnarl, L50, M|100/100"
        t = self.particles(foe_sets())
        t.feed(messages[0])
        with self.assertRaisesRegex(ValueError, "before both open team sheets"):
            t.feed([switch])
        t = self.particles(foe_sets())
        t.feed(messages[0] + messages[1] + ["|win|p1"])
        self.assertTrue(t.ended)
        self.assertFalse(t.ready)
        with self.assertRaisesRegex(ValueError, "no team preview"):
            self.particles(foe_sets()).accepted("team 1234")

    def test_every_stop_is_counted(self):
        messages = closed(FIXTURE["messages"])
        messages[6] = [line.replace("ability: Armor Tail", "ability: Drizzle") for line in messages[6]]
        t = self.particles(foe_sets())
        with self.assertRaises(lines.Stop):
            Run(t, messages)
        self.assertEqual(t.counters["stop.cts:no-consistent-set"], 1)

    # ---------------------------------------------------------------- contradictions
    def test_a_choice_lock_against_a_later_different_move_is_never_kept(self):
        """#423: Farigiraf uses Protect, then Trick Room in the next turn without leaving. A Choice Scarf set would have
        been locked into Protect: the particles that drew it are redrawn."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Choice Scarf"))
        run = self.run_closed(sets, n=16)
        self.assertTrue(any(s[1] == "Choice Scarf" for s in self.held(run, 2, "Farigiraf")))
        self.assertFalse(any(s[1] == "Choice Scarf" for s in self.held(run, 3, "Farigiraf")))
        self.assertGreater(run.t.counters["redraw.choice-lock"], 0)

    def test_a_choice_lock_rules_out_choice_sets_of_that_member_for_every_draw(self):
        """A prior that gives Farigiraf a Choice Scarf in 1000 of 1001 sets: once its lock is contradicted (Protect,
        then Trick Room), rejection alone would rarely find the Sitrus set. The contradiction names the member, and a
        set holding a Choice item contradicts the log for every particle (Showdown enforces the lock; a lock the tracker
        assumed means no line changed the item), so that member's draws leave Choice sets out, counted."""
        scarf = teams._paste(farigiraf(item="Choice Scarf"))[0]
        sitrus = teams._paste(farigiraf())[0]
        sets = [(s, 1) for s in foe_sets() if s["species"] != "Farigiraf"] + [(scarf, 1000), (sitrus, 1)]
        t = cts.ParticleTracker(self.data, FIXTURE["team"], cts.SetPrior(self.data, sets), seed=SEED, key=KEY, n=16)
        run = Run(t, closed(FIXTURE["messages"]))
        self.assertEqual({s[1] for s in self.held(run, 3, "Farigiraf")}, {"Sitrus Berry"})
        self.assertEqual(t.counters["choice-excluded"], 1)

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

    def test_a_used_move_off_every_set_draws_a_level_one_set(self):
        """Level 1 (the replay's set belief, #385 step 3): no set of the prior has Trick Room, which Farigiraf uses on
        turn 2. A set that agrees on the item and ability is the base: its moves become the used ones (Protect, Trick
        Room) and then its own others, and the engine's setup accepts it. Counted, never silent."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        run = self.run_closed(sets, n=4)
        after = self.held(run, 3, "Farigiraf")
        self.assertEqual(len(after), 4)
        for s in after:
            self.assertEqual(set(s[3]), {"Protect", "Trick Room", "Psychic", "Grass Knot"}, s)
        self.assertGreater(run.t.counters["level1"], 0)

    def test_a_revealed_ability_no_set_has_draws_a_level_two_set(self):
        """Level 2: Armor Tail, shown on turn 1, against a prior whose Farigiraf has only Cud Chew. Level 1 keeps the
        item and ability, so it has no base; level 2 takes every set of the species as a base and puts the log's item,
        ability and moves on it, as long as the engine's setup accepts the result. Counted."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(ability="Cud Chew"))
        run = self.run_closed(sets, n=4)
        self.assertEqual({s[2] for s in self.held(run, 3, "Farigiraf")}, {"Armor Tail"})
        self.assertGreater(run.t.counters["level2"], 0)

    def test_level_two_keeps_no_protect_with_a_choice_item(self):
        """Level 2's fill follows the table's rule: a Choice item's holder carries no Protect or Detect (the used moves
        stay as the log shows them)."""
        from duoforge_replay.facts import MemberFacts
        member = MemberFacts("Farigiraf", "F", frozenset({"Psychic"}), "Choice Scarf", None)
        base = teams._paste(farigiraf(moves=("Psychic", "Protect", "Trick Room", "Helping Hand")))[0]
        found, refused = cts.level2(self.data, [(base, 3)], member)
        self.assertEqual(refused, 0)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0]["item"], "Choice Scarf")
        self.assertNotIn("Protect", found[0][0]["moves"])
        self.assertEqual(found[0][1], 3)
        unknown = MemberFacts("Farigiraf", "F", frozenset({"Psychic"}), "Notanitem", None)
        self.assertEqual(cts.level2(self.data, [(base, 3)], unknown), ([], 1))  # a name the tables lack: refused, counted

    def test_a_set_the_engine_refuses_at_every_level_stops_by_name(self):
        """No level gives a set the engine accepts: Farigiraf with an ability it cannot have stops the tracker by name."""
        messages = closed(FIXTURE["messages"])
        messages[6] = [line.replace("ability: Armor Tail", "ability: Drizzle") for line in messages[6]]
        t = self.particles(foe_sets())
        with self.assertRaises(lines.Stop) as caught:
            Run(t, messages)
        self.assertEqual(caught.exception.reason, "cts:no-consistent-set Farigiraf")
        # every rebuilt set the engine refused is counted, never dropped in silence (review of 2026-10-12)
        self.assertGreater(t.counters["levels.refused"], 0)

    def test_the_level_counters_count_facts_not_draws(self):
        """level1 counts the distinct facts of a member that needed level 1, once, not once per particle and redraw."""
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        run = self.run_closed(sets, n=16)
        self.assertEqual(run.t.counters["level1"], 1)  # Farigiraf after Trick Room: one set of facts

    def test_a_setup_check_that_fails_for_another_reason_raises(self):
        """setup_issue names an unknown name ("name"); any other failure of the check is a bug and raises."""
        from unittest import mock
        s = teams._paste(farigiraf())[0]
        self.assertIsNone(cts.setup_issue(self.data, s))
        self.assertEqual(cts.setup_issue(self.data, dict(s, item="Notanitem")), ("name", None))
        for call in ("team", "setup_issue"):
            with mock.patch.object(type(self.data), call, side_effect=KeyError("a bug")):
                with self.assertRaises(KeyError):
                    cts.setup_issue(self.data, s)

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
        """The parts are taken when a decision point's request is folded: none before the first. A particle drawn anew
        later in the turn folds the stream from the start and takes them at the same points, so every particle shows
        the last decision point's."""
        t = self.particles(foe_sets())
        with self.assertRaises(ValueError):
            t.public_parts()
        sets = with_species(foe_sets(), "Farigiraf", farigiraf(),
                            farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")))
        t = self.particles(sets, n=16)
        messages = closed(FIXTURE["messages"])
        Run(t, messages, upto=8)  # turn 2's request
        before = [p["record"].tobytes() for p in t.public_parts()]
        t.feed(messages[8])  # turn 2's lines: Trick Room redraws the particles without it, mid-turn
        self.assertGreater(t.counters["redraw.facts"], 0)
        after = t.public_parts()
        self.assertEqual(len(after), 16)
        self.assertEqual({int(p["record"]["turn"]) for p in after}, {2})
        kept = [i for i, p in enumerate(after) if p["record"].tobytes() == before[i]]
        self.assertTrue(kept and len(kept) < 16, kept)  # the kept particles' parts did not move
        t.feed(messages[9])  # turn 3's request
        self.assertEqual({int(p["record"]["turn"]) for p in t.public_parts()}, {3})

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

    def test_the_committed_set_table_is_a_prior(self):
        """SetPrior.from_table: the pinned table of duoforge_search.smogon_sets, every set checked by the engine."""
        from duoforge_search import smogon_sets
        prior = cts.SetPrior.from_table(self.data)
        found = prior.candidates("Farigiraf")
        self.assertGreater(len(found), 10)
        self.assertEqual(sum(w for _, w in found), smogon_sets.RESOLUTION)
        self.assertTrue(any(s["item"] == "sitrusberry" and "trickroom" in s["moves"] for s, _ in found))
        with self.assertRaises(ValueError):
            cts.SetPrior.from_table(self.data, sha256="0" * 64)

    def test_the_committed_table_plays_the_fixture(self):
        t = cts.ParticleTracker(self.data, FIXTURE["team"], cts.SetPrior.from_table(self.data), seed=SEED, key=KEY, n=16)
        run = Run(t, closed(FIXTURE["messages"]))
        self.assertEqual(len(run.points), 4)
        for s in self.held(run, 3, "Farigiraf"):
            self.assertTrue({"protect", "trickroom"} <= {m.lower().replace(" ", "") for m in s[3]}, s)

    def test_the_prior_refuses_a_set_the_engine_refuses(self):
        # Grimmsnarl does not learn Snarl in the pool tables (data.setup_issue)
        bad = teams._paste(FIXTURE["foe_team"].split("\n\n")[0].replace("- Spirit Break", "- Snarl"))
        with self.assertRaises(ValueError):
            cts.SetPrior(self.data, bad)


class SpyPolicy:
    """Ranks every allowed choice with probabilities that depend on the observation it is shown, and keeps what it was
    shown: the mean over the particles is under test, not the network."""
    encoder = 2

    def __init__(self):
        self.seen = []

    @staticmethod
    def weights(observation, count):
        h = hashlib.sha256(np.asarray(observation).tobytes()).digest()
        w = [h[k % len(h)] % 7 + 1 for k in range(count)]
        return [x / sum(w) for x in w]

    def rank_pairs(self, observation, obs_part, slot_part, pair_mask):
        self.seen.append(np.asarray(observation).tobytes())
        n = pair_mask.shape[1]
        allowed = np.flatnonzero(pair_mask.reshape(-1))
        ranked = [(int(i) // n, int(i) % n, p) for i, p in zip(allowed, self.weights(observation, allowed.size))]
        return sorted(ranked, key=lambda r: -r[2])

    def rank_teams(self, observation, obs_part):
        self.seen.append(np.asarray(observation).tobytes())
        return sorted(enumerate(self.weights(observation, 360)), key=lambda r: -r[1])


class RawSearch:
    """A LiveSearch in shape: keeps every call and plays raw."""

    def __init__(self):
        self.calls = []

    def decide(self, parts, obs_part, slot_part, pair_mask, *, key, episode, budget, worlds=None):
        self.calls.append({"parts": parts, "obs_part": obs_part, "slot_part": slot_part, "pair_mask": pair_mask,
                           "worlds": worlds})
        return live_search.Outcome(None, "raw", None, None, 0.0)


class ClosedGameTest(unittest.TestCase):
    """game.Game.closed_sheets: a closed-sheet battle played over the particles."""
    N = 4

    @classmethod
    def setUpClass(cls):
        cls.data = data.load(kind="pool")

    def game(self, policy, search=None):
        prior = cts.SetPrior(self.data, with_species(foe_sets(), "Farigiraf", farigiraf(), farigiraf(item="Leftovers"),
                                                     farigiraf(item="Mental Herb")))
        return game.Game.closed_sheets(self.data, policy, FIXTURE["team"], prior, search=search, room=KEY, seed=SEED,
                                       n=self.N)

    @staticmethod
    def mean(values):
        """The mean as game.mean_ranking takes it: summed in particle order, without compensation (sum() of Python 3.12
        compensates)."""
        total, n = 0.0, 0
        for v in values:
            total, n = total + v, n + 1
        return total / n

    @staticmethod
    def points(g):
        """The game at each decision point of the closed stream (before the fixture's choice is accepted)."""
        done = 0
        for m in closed(FIXTURE["messages"]):
            g.feed(m)
            if g.ready and g.epoch > done:
                done = g.epoch
                yield g
                g.accepted(FIXTURE["inputs"][done - 1])

    def test_the_raw_ranking_is_the_mean_over_the_particles(self):
        spy = SpyPolicy()
        checked = 0
        for g in self.points(self.game(spy)):
            spy.seen.clear()
            got = g.candidates()
            observations = g.tracker.observations()
            self.assertEqual(spy.seen, [o.tobytes() for o in observations])  # each particle once, in order
            self.assertGreater(len(set(spy.seen)), 1)  # the particles' observations differ: a mean to take
            if g.request.get("teamPreview"):
                ws = [spy.weights(o, 360) for o in observations]
                mean = [self.mean(w[k] for w in ws) for k in range(360)]
                want = [(options.team_text(game.TEAM_TABLE[k]), mean[k])
                        for k in sorted(range(360), key=lambda k: (-mean[k], k))]
            else:
                domain, lists = g.tracker.domain()
                _, _, mask = features.encode(observations[0], domain, g.tracker.observation_exts()[0], 0)
                n, allowed = mask.shape[1], np.flatnonzero(mask.reshape(-1))
                ws = [spy.weights(o, allowed.size) for o in observations]
                mean = [self.mean(w[k] for w in ws) for k in range(allowed.size)]
                want = [(options.pair_text(lists[0][allowed[k] // n], lists[1][allowed[k] % n]), mean[k])
                        for k in sorted(range(allowed.size), key=lambda k: (-mean[k], allowed[k]))]
            self.assertEqual([(c.text, c.probability) for c in got], want)
            checked += 1
        self.assertEqual(checked, 4)

    def test_the_search_gets_one_world_per_particle(self):
        search = RawSearch()
        for g in self.points(self.game(FakePolicy(), search)):
            g.candidates()
            call = search.calls[-1]
            parts = g.tracker.public_parts()
            self.assertEqual(len(call["worlds"]), self.N)
            for (world, obs_part, slot_part, history), want in zip(call["worlds"], parts):
                self.assertIs(world, want)
                self.assertEqual(len(history), g.epoch)  # its (record, status) at every decision point so far
                self.assertEqual(history[-1][0].tobytes(), want["record"].tobytes())
                self.assertEqual(obs_part.shape, call["obs_part"].shape)
                self.assertEqual(slot_part is None, bool(g.request.get("teamPreview")))
            self.assertIs(call["parts"], parts[0])  # the root's request and own pairs: every particle's
            self.assertIs(call["obs_part"], call["worlds"][0][1])
        self.assertEqual(len(search.calls), 4)

    def preview_record(self, sets):
        """The team-preview record an open-sheet tracker shows with `sets` as the foe's sheet."""
        t = tracker.Tracker(self.data, FIXTURE["team"])
        own, foe = teams.pack(FIXTURE["team"]), teams.pack(teams.to_text(sets))
        for m in closed(FIXTURE["messages"]):
            for i, line in enumerate(m):
                side = cts._preview_side(line)
                if side is not None:
                    t.feed(m[:i + 1])
                    t.feed([f"|showteam|p{s + 1}|" + (own if s == side else foe) for s in (0, 1)])
                    return t.public_parts()["record"]
            t.feed(m)
        raise AssertionError("no team preview")

    def test_a_particle_drawn_anew_brings_the_preview_record_of_its_own_sets(self):
        # Review of #385 step 4: the search builds world w's team preview from particle w's history, so a particle drawn
        # after the preview must carry the preview record of its own sets, not of the particle it replaced.
        prior = cts.SetPrior(self.data, with_species(foe_sets(), "Farigiraf", farigiraf(),
                                                     farigiraf(moves=("Psychic", "Grass Knot", "Helping Hand", "Protect")),
                                                     farigiraf(item="Leftovers")))
        g = game.Game.closed_sheets(self.data, FakePolicy(), FIXTURE["team"], prior, room=KEY, seed=SEED, n=8)
        at_preview, changed = None, 0
        for g in self.points(g):
            histories = g.tracker.histories()
            if at_preview is None:
                at_preview = [h[0][0].tobytes() for h in histories]
            for p, h in zip(g.tracker.particles, histories):
                self.assertEqual(h[0][0].tobytes(), self.preview_record(p.sets).tobytes())
            changed = sum(a != h[0][0].tobytes() for a, h in zip(at_preview, histories))
        self.assertGreater(g.tracker.counters["redraw.facts"], 0)
        self.assertGreater(changed, 0)  # a particle redrawn after the preview: another preview record

    def test_the_summary_names_the_reasons_of_the_raw_decisions(self):
        # #385 step 5 counts the #464 refusals (engine-refuses-record) from each game's summary.
        reason = "DUOFORGE_E_UNSUPPORTED: public record (public_record_unsupported); tracker: engine-refuses-record"

        class Refusing(RawSearch):
            def decide(self, *args, **kwargs):
                super().decide(*args, **kwargs)
                return live_search.Outcome(None, "unreconstructible", "a", reason, 0.0)
        for g in self.points(self.game(FakePolicy(), Refusing())):
            g.candidates()
        summary = g.summary()
        self.assertEqual(summary["fallback"], {"a": 4})
        self.assertEqual(summary["reasons"], {reason: 4})

    def test_each_particle_shows_its_own_extension_record(self):
        for g in self.points(self.game(FakePolicy())):
            self.assertEqual([e.tobytes() for e in g.tracker.observation_exts()],
                             [p.tracker.observation_ext().tobytes() for p in g.tracker.particles])

    def test_the_live_search_sets_the_particles_as_its_worlds(self):
        from duoforge_search.record_roots import RecordRoots

        class Searcher:
            encoder, s = 4, ClosedGameTest.N

            def __init__(self):
                self.worlds = []

            def decide(self, roots, envs, seats, keys, last_step):
                self.worlds.append(roots.worlds(int(envs[0]), int(seats[0])))
                return np.zeros(1, np.int64), [{"kind": "raw"}]

        searcher = Searcher()
        live = live_search.LiveSearch(searcher, roots=RecordRoots(1))
        self.addCleanup(live.close)
        g = self.game(FakePolicy(), live)
        for g in self.points(g):
            g.candidates()
            got = searcher.worlds[-1]
            parts = g.tracker.public_parts()
            self.assertEqual([r.tobytes() for r in got["records"]], [p["record"].tobytes() for p in parts])
            self.assertEqual(got["statuses"].tolist(), [p["status"] for p in parts])
            self.assertEqual(got["causes"].tolist(), [p["causes"] for p in parts])
            self.assertEqual([o.tobytes() for o in got["observations"]], [p["observation"].tobytes() for p in parts])
            self.assertEqual(len(got["obs"]), self.N)
            self.assertEqual(len(got["slots"]), self.N)
            self.assertEqual([[r.tobytes() for r, _ in h] for h in got["histories"]],
                             [[r.tobytes() for r, _ in h] for h in g.tracker.histories()])
        self.assertEqual([o.cause for o in g.outcomes], ["raw"] * 4)

    def test_a_refused_decision_names_every_particles_reason(self):
        # Review of #385 step 5: the #464 count reads the outcome's reason, so every particle's named reason is in it,
        # not only the first one's.
        from duoforge_search.record_roots import RecordRoots

        class Refusing:
            encoder, s = 4, ClosedGameTest.N

            def decide(self, roots, envs, seats, keys, last_step):
                return np.zeros(1, np.int64), [{"kind": "unreconstructible", "reason": "DUOFORGE_E_UNSUPPORTED: x"}]

        live = live_search.LiveSearch(Refusing(), roots=RecordRoots(1))
        self.addCleanup(live.close)
        for g in self.points(self.game(FakePolicy(), live)):
            parts = g.tracker.public_parts()
            for i, reason in enumerate((None, "visible-confusion", "engine-refuses-record", "visible-confusion")):
                parts[i]["reason"] = reason
            g.candidates()
            if not g.request.get("teamPreview"):
                break
        self.assertEqual(g.outcomes[-1].reason,
                         "DUOFORGE_E_UNSUPPORTED: x; tracker: engine-refuses-record,visible-confusion")


class LogReplayTest(unittest.TestCase):
    def test_a_stop_ends_the_replay_under_its_name(self):
        tables = data.load(kind="pool")
        prior = cts.SetPrior(tables, [s for s in foe_sets() if s["species"] != "Farigiraf"])
        records = [{"feed": m} for m in closed(FIXTURE["messages"])]
        replay = cts.LogReplay(records, tables, None, FIXTURE["team"], prior, KEY)
        self.assertEqual(list(replay), [])
        self.assertEqual(replay.stopped, "stop:cts:no-consistent-set")

    def test_a_fallback_of_the_bot_is_named_and_a_divergence_found(self):
        # Review of the replay core: the bot's own fallback ends its feeds; the replay names it, and a log whose bot
        # stopped the tracker where the replay does not (or the reverse) is a divergence, never silent.
        tables = data.load(kind="pool")
        prior = cts.SetPrior(tables, foe_sets())
        feeds = [{"feed": m} for m in closed(FIXTURE["messages"])[:4]]
        replay = cts.LogReplay(feeds + [{"fallback": "deadline", "detail": "no decision within 20 s"}], tables, None,
                               FIXTURE["team"], prior, KEY)
        self.assertEqual(len(list(replay)), 1)  # the team preview
        self.assertEqual((replay.stopped, replay.diverged, replay.complete), ("fallback:deadline", None, True))
        replay = cts.LogReplay(feeds + [{"fallback": "stop:cts:redraw-cap", "detail": "stop:cts:redraw-cap x"}], tables,
                               None, FIXTURE["team"], prior, KEY)
        list(replay)
        self.assertEqual(replay.stopped, "fallback:stop:cts:redraw-cap")
        self.assertIn("the bot stopped", replay.diverged)
        partial = cts.LogReplay(feeds, tables, None, FIXTURE["team"], prior, KEY)
        next(iter(partial))
        self.assertFalse(partial.complete)  # a consumer that stops early: no verdict

    # The two log formats (client.LOG_FORMAT): the fixtures are the arena bot's own log of a battle the foe forfeits
    # with its turn-1 choice sent (test_pkmn_arena: test_the_format_2_fixture_is_the_bots_own_log), format 1 without
    # its {"log_format"} and {"pending_at_end"} records.
    FORFEIT_KEY = "battle-gen9championsvgc2026regmc-11"
    FORFEIT_CHOICE = "move 1 -2, move 1"

    def replay_fixture(self, n, cut=None):
        path = data.ROOT / "python" / "tests" / "support" / "data" / f"cts_log_format{n}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()][:cut]
        tables = data.load(kind="pool")
        replay = cts.LogReplay(records, tables, None, FIXTURE["team"], cts.SetPrior.from_table(tables),
                               self.FORFEIT_KEY)
        return replay, [record for _, record in replay]

    def test_a_format_2_log_names_the_choice_the_battle_ended_on(self):
        replay, records = self.replay_fixture(2)
        self.assertEqual((replay.log_format, replay.stopped, replay.diverged), (2, None, None))
        self.assertEqual(len(records), 2)  # the team preview and turn 1
        self.assertNotIn("pending_at_end", records[0])
        self.assertEqual((records[-1]["sent"], records[-1]["accepted"], records[-1]["pending_at_end"]),
                         (self.FORFEIT_CHOICE, None, self.FORFEIT_CHOICE))

    def test_a_format_1_log_replays_as_before_without_pending_at_end(self):
        old, old_records = self.replay_fixture(1)
        new, new_records = self.replay_fixture(2)
        self.assertEqual((old.log_format, old.stopped, old.diverged), (1, None, None))
        self.assertFalse([r for r in old_records if "pending_at_end" in r])
        self.assertEqual(old_records, [{k: v for k, v in r.items() if k != "pending_at_end"} for r in new_records])

    def test_a_log_without_its_end_gives_no_pending_at_end(self):
        # a log still being written, or cut at a reconnect: no end, no claim about the end
        _, records = self.replay_fixture(2, cut=-2)
        self.assertFalse([r for r in records if "pending_at_end" in r])

    def test_a_later_log_format_is_refused_by_name(self):
        tables = data.load(kind="pool")
        for bad in (3, 0, True, "2", 2.0, None):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "log format"):
                cts.LogReplay([{"log_format": bad}], tables, None, FIXTURE["team"], None, KEY)
        with self.assertRaisesRegex(ValueError, "record 1 names a log format"):
            cts.LogReplay([{"feed": []}, {"log_format": 2}], tables, None, FIXTURE["team"], None, KEY)

    def test_a_format_1_log_never_gives_pending_at_end(self):
        # a format-1 log is read as format 1 whatever records it holds (review of the format 2)
        path = data.ROOT / "python" / "tests" / "support" / "data" / "cts_log_format2.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()][1:]
        tables = data.load(kind="pool")
        replay = cts.LogReplay(records, tables, None, FIXTURE["team"], cts.SetPrior.from_table(tables),
                               self.FORFEIT_KEY)
        self.assertEqual(replay.log_format, 1)
        self.assertFalse([r for _, r in replay if "pending_at_end" in (r or {})])

    def test_a_record_that_is_no_object_is_refused(self):
        with self.assertRaisesRegex(ValueError, "record 1"):
            cts.LogReplay([{"feed": []}, "x"], data.load(kind="pool"), None, FIXTURE["team"], None, KEY)

    def test_the_key_is_the_room_the_log_is_named_by(self):
        from pathlib import Path
        self.assertEqual(cts.room_of_log(Path("x/battle-gen9championsvgc2026regmc-75-lingce.jsonl"), "Ling-Ce"),
                         "battle-gen9championsvgc2026regmc-75")
        with self.assertRaises(ValueError):
            cts.room_of_log(Path("battle-x-1-other.jsonl"), "Ling-Ce")


class TrueSheetTest(unittest.TestCase):
    def test_the_true_sheet_is_what_the_pinned_server_shows(self):
        # Review of #385 step 5: the oracle arm's foe sheet must be the open sheet Showdown sends (no stat points,
        # sim/battle.ts showOpenTeamSheets), never the paste with its EVs; the particles fold the same form.
        real = next(line for m in FIXTURE["messages"] for line in m if line.startswith("|showteam|p2|"))
        self.assertEqual("|showteam|p2|" + cts.true_sheet(FIXTURE["foe_team"]), real)
        self.assertNotEqual(cts.true_sheet(FIXTURE["foe_team"]), teams.pack(FIXTURE["foe_team"]))  # the EVs differ


class CounterKindTest(unittest.TestCase):
    def test_a_redraw_by_a_stop_keeps_the_stops_kind_only(self):
        self.assertEqual(cts.counter_kind("redraw.stop:structure:p2a: Nickname names no member seen yet"),
                         "redraw.stop:structure")
        self.assertEqual(cts.counter_kind("redraw.stop:cts:redraw-cap error:ValueError"), "redraw.stop:cts:redraw-cap")
        for key in ("redraw.facts", "redraw.error:ValueError", "stop.cts:facts", "level1", "choice-excluded"):
            self.assertEqual(cts.counter_kind(key), key)


class WordTest(unittest.TestCase):
    def test_the_word_is_the_replays(self):
        from duoforge_replay import setbelief
        self.assertEqual(cts.word(SEED, KEY, 1, 2, 3, 4), setbelief.word(SEED, KEY, 1, 2, 3, 4))
        self.assertIsInstance(np.uint64(cts.word(1, "k", 0, 0, 0, 0)), np.uint64)


if __name__ == "__main__":
    unittest.main()
