"""duoforge.python.cts_live_eval: the evaluation of Ling-Ce's live closed-sheet games (#385, after step 5).

tools/research/cts_live_eval.py reads the private arena logs (outside the repository) and prints aggregates only. Under
test, on synthetic logs: a battle's classification (played over the particles, or an old /choose default one), the
counts of its decisions and their reasons (#464 among them), the run logs summed from a start time, and that a stop's
named reason never carries the free text after it (a nickname).
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from duoforge_live import data

_SPEC = importlib.util.spec_from_file_location("cts_live_eval", data.ROOT / "tools" / "research" / "cts_live_eval.py")
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)

REFUSED = "DUOFORGE_E_UNSUPPORTED: public record (public_record_unsupported); tracker: engine-refuses-record"


def _search(cause, seconds=0.1, fallback=None, reason=None):
    return {"action": None, "cause": cause, "fallback": fallback, "reason": reason, "seconds": seconds,
            "spread_fallback": None, "spread_redrawn": None}


def played():
    return [{"in": "|init|battle"}, {"in": "|t:|1791900000"}, {"feed": ["|request|{}"]},
            {"decision": 1, "top": [], "sent": "team 1234", "search": _search("team", 0.01)},
            {"accepted": "team 1234"}, {"feed": ["|turn|1"]},
            {"decision": 3, "top": [], "sent": "move 1, move 1", "search": _search("searched", 0.2)},
            {"decision": 5, "top": [], "sent": "move 1, move 2", "search": _search("searched", 0.4)},
            {"decision": 7, "top": [], "sent": "move 2, move 1",
             "search": _search("unreconstructible", 0.05, "a", REFUSED)},
            {"decision": 9, "top": [], "sent": "move 1, move 1", "search": _search("deadline", 2.0, "deadline")},
            {"timer": "missing", "decision": 9},
            {"in": "|win|Ling-Ce"}, {"end": "|win|Ling-Ce"}]


def stopped():
    return [{"in": "|init|battle"}, {"feed": ["|request|{}"]},
            {"decision": 1, "top": [], "sent": "team 1234", "search": _search("team", 0.01)},
            {"fallback": "stop:cts:redraw-cap",
             "detail": "stop:cts:redraw-cap stop:structure:p2a: Bobby names no member seen yet"},
            {"sent": "default", "decision": 3, "fallback": "stop:cts:redraw-cap"},
            {"sent": "default", "decision": 5, "fallback": "stop:cts:redraw-cap"},
            {"in": "|win|Opponent"}, {"end": "|win|Opponent"}]


def old():
    return [{"fallback": "closed_team_sheets", "detail": "the tracker needs both open team sheets (decision 0016)"},
            {"in": "|init|battle"}, {"sent": "default", "decision": 1, "fallback": "closed_team_sheets"},
            {"in": "|win|Ling-Ce"}, {"end": "|win|Ling-Ce"}]


class LiveEvalTest(unittest.TestCase):
    def test_a_battle_over_the_particles_is_counted_by_its_decisions_and_reasons(self):
        b = ev.battle(played(), "lingce")
        self.assertEqual((b["kind"], b["result"]), ("particles", "win"))
        self.assertEqual(b["causes"], {"team": 1, "searched": 2, "unreconstructible": 1, "deadline": 1})
        self.assertEqual((b["engine_refuses_record"], b["defaults"], b["timer_missing"]), (1, 0, 1))
        self.assertEqual(b["seconds"], [0.2, 0.4, 0.05, 2.0])  # every decision but the team preview's
        self.assertEqual(b["start"], 1791900000)  # the first timestamp: --since keeps battles by it

    def test_every_decision_counts_one_without_a_search_too_and_a_dirty_one_has_no_seconds(self):
        # Review of the evaluation tool: after a class (b) error later games play raw, their decisions carry no search
        # outcome; they still count, or the searched share would be inflated
        records = played() + [{"decision": 11, "top": [], "sent": "move 1, move 1"},
                              {"decision": 13, "top": [], "sent": "move 1, move 1", "search": _search("dirty", 0.0)}]
        b = ev.battle(records, "lingce")
        self.assertEqual((b["causes"]["no_search"], b["causes"]["dirty"]), (1, 1))
        self.assertEqual(b["seconds"], [0.2, 0.4, 0.05, 2.0])
        s = ev.summarize([b])
        self.assertEqual(s["decisions"], 6)
        self.assertAlmostEqual(s["searched_share"], 2 / 6)
        # a fallback "a" whose reasons name no refused particle is no #464 case
        other = played()[:5] + [{"decision": 3, "top": [], "sent": "move 1, move 1",
                                 "search": _search("unreconstructible", 0.1, "a", "missing team-preview record")}]
        self.assertEqual(ev.battle(other, "lingce")["engine_refuses_record"], 0)

    def test_a_named_stop_never_carries_the_text_after_it(self):
        b = ev.battle(stopped(), "lingce")
        self.assertEqual((b["kind"], b["result"], b["defaults"]), ("particles", "loss", 2))
        self.assertEqual(b["stop"], "stop:cts:redraw-cap stop:structure:p2a")
        self.assertNotIn("Bobby", json.dumps(b))
        for detail, named in (("stop:cts:no-consistent-set Farigiraf", "stop:cts:no-consistent-set"),
                              ("ValueError: a long message", "ValueError"),
                              ("stop:cts:redraw-cap stop:feature:SUBSTITUTE", "stop:cts:redraw-cap stop:feature:SUBSTITUTE")):
            self.assertEqual(ev.named(detail), named)

    def test_an_old_default_battle_is_apart_and_the_sums_are_aggregates(self):
        self.assertEqual(ev.battle(old(), "lingce")["kind"], "before_particles")
        battles = [ev.battle(x, "lingce") for x in (played(), stopped(), old())]
        s = ev.summarize(battles)
        self.assertEqual(s["battles"], {"particles": 2, "before_particles": 1})
        self.assertEqual(s["results"], {"win": 1, "loss": 1})
        self.assertEqual(s["decisions"], 4)  # the particle battles' decisions but the team previews and the defaults
        self.assertAlmostEqual(s["searched_share"], 2 / 4)
        self.assertEqual((s["engine_refuses_record"], s["deadline"], s["defaulted_decisions"]), (1, 1, 2))
        self.assertEqual(s["stops"], {"stop:cts:redraw-cap stop:structure:p2a": 1})
        self.assertEqual(s["seconds"]["n"], 4)

    def test_run_logs_are_summed_from_a_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, started, wins in (("a", "2026-10-12T10:00:00Z", 5), ("b", "2026-10-13T21:00:00Z", 7),
                                        ("c", "2026-10-13T22:00:00Z", 2)):
                Path(tmp, f"arena-run-{name}.json").write_text(json.dumps({
                    "started": started, "counts": {"battles": wins + 1, "wins": wins, "reconnects": 1},
                    "fallback_battles": {"stop:cts:redraw-cap": 1}, "closes": {"1006": 1},
                    "search_causes": {"searched": 10}, "cts": {"redraw.facts": 3}}), encoding="utf-8")
            runs = ev.run_logs(tmp, since="2026-10-13T00:00:00Z")
        self.assertEqual(runs["files"], 2)
        self.assertEqual(runs["counts"], {"battles": 11, "wins": 9, "reconnects": 2})
        self.assertEqual((runs["fallback_battles"], runs["cts"]), ({"stop:cts:redraw-cap": 2}, {"redraw.facts": 6}))


class OpponentTest(unittest.TestCase):
    """Per opponent (HauptSession, 2026-10-13): a private label file keeps each opponent's letter across series, so a
    fix's before and after compare the same opponents; no name is ever printed."""

    def test_the_opponent_is_the_player_that_is_not_the_bot(self):
        records = [{"in": "|player|p1|Ling-Ce||"}, {"in": "|player|p2|Some Foe|2|"}]
        self.assertEqual(ev.opponent(records, "lingce"), "somefoe")
        self.assertEqual(ev.opponent([{"in": "|player|p1|Ling-Ce||"}], "lingce"), None)

    def test_labels_are_kept_and_new_opponents_continue_by_battles_then_first_seen(self):
        labels = ev.assign_labels(["x", "y", "y", "z", "y", "z"], {})
        self.assertEqual(labels, {"y": "A", "z": "B", "x": "C"})  # most battles first, ties by first appearance
        later = ev.assign_labels(["w", "x", "w", "v"], labels)
        self.assertEqual(later, {"y": "A", "z": "B", "x": "C", "w": "D", "v": "E"})  # kept, then continued

    def test_an_opponents_team_is_its_preview_species(self):
        records = [{"in": "|player|p1|Ling-Ce||"}, {"in": "|player|p2|Some Foe|2|"},
                   {"in": "|poke|p1|Froslass, L50, F|"}, {"in": "|poke|p2|Garchomp, L50, M|"},
                   {"in": "|poke|p2|Charizard, L50, M|"}]
        self.assertEqual(ev.foe_team(records, "lingce"), ev.foe_team(list(reversed(records)), "lingce"))
        other = records[:-1] + [{"in": "|poke|p2|Venusaur, L50, F|"}]
        self.assertNotEqual(ev.foe_team(records, "lingce"), ev.foe_team(other, "lingce"))

    def test_each_opponents_teams_are_numbered_by_first_appearance_and_kept(self):
        # An opponent may change its team between series (HauptSession, 2026-10-14): each team of an opponent is a
        # label of its own, letter and number, kept in the same private file.
        labels = ev.assign_labels(["x", "y"], {})
        labels = ev.assign_teams([("x", "t1"), ("y", "s1"), ("x", "t2"), ("x", "t1")], labels)
        self.assertEqual([ev.team_label(labels, o, t) for o, t in (("x", "t1"), ("x", "t2"), ("y", "s1"))],
                         ["A1", "A2", "B1"])
        later = ev.assign_teams([("x", "t3"), ("x", "t2")], labels)
        self.assertEqual([ev.team_label(later, "x", t) for t in ("t1", "t2", "t3")], ["A1", "A2", "A3"])

    def test_the_label_file_never_lies_in_the_repository(self):
        with self.assertRaises(ValueError):
            ev.load_labels(data.ROOT / "python" / "tests" / "labels.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "labels.json")
            self.assertEqual(ev.load_labels(path), {})
            ev.save_labels(path, {"y": "A"})
            self.assertEqual(ev.load_labels(path), {"y": "A"})


class MainTest(unittest.TestCase):
    def test_the_output_holds_letters_and_counts_but_no_name_or_room(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as logs, tempfile.TemporaryDirectory() as private:
            names = {"battle-gen9x-501": ("Some Foe", played()), "battle-gen9x-502": ("Other Foe", stopped())}
            for room_id, (foe, records) in names.items():
                head = [{"in": "|player|p1|Ling-Ce||"}, {"in": f"|player|p2|{foe}|2|"},
                        {"in": "|poke|p2|Garchomp, L50, M|"}]  # its team: the preview (none: "?")
                Path(logs, f"{room_id}-lingce.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in head + records) + "\n", encoding="utf-8")
            out = io.StringIO()
            labels = Path(private, "labels.json")
            with contextlib.redirect_stdout(out):
                ev.main(["--logs", logs, "--labels", str(labels), "--since", "2026-10-13T00:00:00Z"])
            text = out.getvalue()
        result = json.loads(text)
        # the tool's own commit hash is no log text: a room number's digits may occur in it by chance (Content lane,
        # 2026-10-14: "14502344" in a commit failed this test), so the check reads the output without it
        checked = text.replace(result["code"]["commit"], "<tool commit>")
        for private_text in ("Some Foe", "somefoe", "Other Foe", "otherfoe", "501", "502", "Bobby"):
            self.assertNotIn(private_text, checked)
        self.assertEqual(sorted(result["by_opponent"]), ["A"])  # the stopped battle has no timestamp: before --since
        self.assertEqual(sorted(result["by_team"]), ["A1"])
        self.assertEqual((result["logs"], result["kept"]), (2, 1))


class CodeTest(unittest.TestCase):
    """A measurement series per bot commit (HauptSession, 2026-10-14: from a7dd956b on, Ling-Ce plays the 2e rule): the
    battles and run logs of one commit, never mixed with another's."""

    def test_a_battle_names_its_bots_code_from_its_summary(self):
        code = {"commit": "a7dd956b" + "0" * 32, "dirty": False}
        b = ev.battle(played() + [{"summary": {"causes": {}, "code": code}}], "lingce")
        self.assertEqual(b["code"], code)
        self.assertIsNone(ev.battle(played(), "lingce")["code"])

    def test_main_keeps_the_battles_and_run_logs_of_one_commit(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as logs:
            for n, commit in ((1, "1ffa6a03"), (2, "a7dd956b"), (3, None)):
                summary = [] if commit is None else [{"summary": {"code": {"commit": commit + "0" * 32, "dirty": False}}}]
                Path(logs, f"battle-gen9x-{n}-lingce.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in played() + summary) + "\n", encoding="utf-8")
                Path(logs, f"arena-run-{n}.json").write_text(json.dumps({
                    "started": "2026-10-14T00:00:00Z", "counts": {"battles": 1},
                    **({} if commit is None else {"code": {"commit": commit + "0" * 32, "dirty": False}})}),
                    encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ev.main(["--logs", logs, "--code", "a7dd956b"])
        result = json.loads(out.getvalue())
        self.assertEqual((result["logs"], result["kept"], result["code_filter"]), (3, 1, "a7dd956b"))
        self.assertEqual(result["by_code"], {"1ffa6a03": 1, "a7dd956b": 1, "none": 1})
        self.assertEqual(result["runs"]["files"], 1)


class CodeReviewTest(unittest.TestCase):
    """The review of the format 2: every battle names its code in its first record, so a series keeps its failure
    battles too (a raw game after a class (b) error writes no summary); a dirty run is another series."""

    def test_a_battle_names_its_code_in_its_first_record(self):
        code = {"commit": "a7dd956b" + "0" * 32, "dirty": False}
        self.assertEqual(ev.battle([{"log_format": 2, "code": code}] + played(), "lingce")["code"], code)

    def test_a_dirty_run_is_not_in_its_commits_series(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as logs:
            for n, dirty in ((1, False), (2, True)):
                head = {"log_format": 2, "code": {"commit": "a7dd956b" + "0" * 32, "dirty": dirty}}
                Path(logs, f"battle-gen9x-{n}-lingce.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in [head] + played()) + "\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ev.main(["--logs", logs, "--code", "a7dd956b"])
        result = json.loads(out.getvalue())
        self.assertEqual(result["by_code"], {"a7dd956b": 1, "a7dd956b+dirty": 1})
        self.assertEqual(result["kept"], 1)

    def test_an_opponents_team_without_a_preview_is_unknown_and_a_resync_changes_nothing(self):
        records = [{"in": "|player|p1|Ling-Ce||"}, {"in": "|player|p2|Some Foe|2|"},
                   {"in": "|poke|p2|Garchomp, L50, M|"}, {"in": "|poke|p2|Charizard, L50, M|"}]
        again = records + [{"in": "|poke|p2|Garchomp, L50, M|"}]  # a resync logs the preview again
        self.assertEqual(ev.foe_team(records, "lingce"), ev.foe_team(again, "lingce"))
        self.assertIsNone(ev.foe_team(records[:2], "lingce"))
        labels = ev.assign_teams([("x", None)], ev.assign_labels(["x"], {}))
        self.assertEqual(ev.team_label(labels, "x", None), "?")

    def test_details_need_the_replay(self):
        with tempfile.TemporaryDirectory() as logs, self.assertRaisesRegex(SystemExit, "--replay"):
            ev.main(["--logs", logs, "--details", str(Path(logs, "details.json"))])


class ReplayTest(unittest.TestCase):
    """--replay (#473-#477): a battle log replayed through the particles counts its decision points and those where the
    engine refuses a particle's record, with the unmodelled content each refused particle holds."""

    def test_the_fixture_replays_with_its_decision_points_and_no_refusal(self):
        from duoforge_live import cts, tracker
        fixture = json.loads((data.ROOT / "python" / "tests" / "support" / "data" / "live_stream_ab.json")
                             .read_text(encoding="utf-8"))
        tables = data.load(kind="pool")
        records, t, done = [], tracker.Tracker(tables, fixture["team"]), 0
        for m in fixture["messages"]:  # the batches as fed and the choices accepted, as the bot's log keeps them
            records.append({"feed": [line for line in m if not line.startswith("|showteam|")]})
            t.feed(m)
            if t.ready and t.epoch > done:
                done = t.epoch
                records.append({"accepted": fixture["inputs"][done - 1]})
                t.accepted(fixture["inputs"][done - 1])
        names = ev.unmodelled((data.ROOT / "src" / "data" / "pool_tables.c").read_text(encoding="utf-8"))
        out = ev.replay(records, tables, cts.SetPrior.from_table(tables), fixture["team"], "battle-test-1", names)
        self.assertEqual(out["points"], 3)  # turns 1 to 3 (the team preview is not a searched decision)
        self.assertEqual(out["refused"], [])
        # a prior whose Farigiraf holds Gravity (unmodelled): every particle's record is refused, and named by it
        from duoforge_live import teams
        foe = teams._paste(fixture["foe_team"])
        gravity = [dict(s, moves=["Psychic", "Gravity", "Trick Room", "Protect"]) for s in foe if s["species"] == "Farigiraf"]
        prior = cts.SetPrior(tables, [s for s in foe if s["species"] != "Farigiraf"] + gravity)
        out = ev.replay(records, tables, prior, fixture["team"], "battle-test-1", names)
        self.assertEqual(out["points"], 3)
        self.assertEqual(out["refused"], [[["move:gravity"]] * cts.PARTICLES] * 3)

    def test_a_stopped_replay_is_counted_under_its_named_reason(self):
        # A content fix may stop the tracker at a line (Speed Swap option B: a real swap stops it, by name): under
        # closed sheets every particle's fold stops there, the battle falls back. The replay counts it, never crashes.
        from duoforge_live import cts, teams
        fixture = json.loads((data.ROOT / "python" / "tests" / "support" / "data" / "live_stream_ab.json")
                             .read_text(encoding="utf-8"))
        tables = data.load(kind="pool")
        prior = cts.SetPrior(tables, [s for s in teams._paste(fixture["foe_team"]) if s["species"] != "Farigiraf"])
        records = [{"feed": [line for line in m if not line.startswith("|showteam|")]} for m in fixture["messages"]]
        out = ev.replay(records, tables, prior, fixture["team"], "battle-test-1", set())
        self.assertEqual((out["points"], out["stopped"]), (0, "stop:cts:no-consistent-set"))

    def test_unmodelled_content_is_read_from_the_tables_and_named_per_set(self):
        text = ("    /* Speed Swap -- data/moves.ts:1-2  [unmodelled: callback onHit] */\n"
                " *   piercingdrill -- data/abilities.ts:3-4  [unmodelled: callback onHitProtect]\n"
                " *   toughclaws -- data/abilities.ts:7-8  [unmodelled: test]\n"
                "    /* Flare Blitz -- data/moves.ts:5-6 */\n")
        names = ev.unmodelled(text)
        self.assertEqual(names, {"speedswap", "piercingdrill", "toughclaws"})
        tables = data.load(kind="pool")
        self.assertEqual(ev.held({"species": "Alakazam", "item": "Focus Sash", "ability": "Magic Guard",
                                  "moves": ["Speed Swap", "Psychic"]}, names, tables), {"move:speedswap"})
        self.assertEqual(ev.held({"species": "Excadrill", "item": "Excadrite", "ability": "Sand Rush",
                                  "moves": ["Iron Head"]}, names, tables), {"mega:excadrillmega(piercingdrill)"})
        # the library's own holder and stone pairs: Charizardite X takes Charizard to Mega X (Tough Claws), Y to Mega Y
        self.assertEqual(ev.held({"species": "Charizard", "item": "Charizardite X", "ability": "Blaze",
                                  "moves": ["Flare Blitz"]}, names, tables), {"mega:charizardmegax(toughclaws)"})
        self.assertEqual(ev.held({"species": "Charizard", "item": "Charizardite Y", "ability": "Blaze",
                                  "moves": ["Flare Blitz"]}, names, tables), set())
        self.assertEqual(ev.held({"species": "Charizard", "item": "Charcoal", "ability": "Blaze",
                                  "moves": ["Flare Blitz"]}, names, tables), set())

    def test_the_real_tables_name_the_known_unmodelled_content(self):
        names = ev.unmodelled((data.ROOT / "src" / "data" / "pool_tables.c").read_text(encoding="utf-8"))
        self.assertTrue({"speedswap", "piercingdrill", "gravity", "temperflare"} <= names, sorted(names)[:10])


if __name__ == "__main__":
    unittest.main()
