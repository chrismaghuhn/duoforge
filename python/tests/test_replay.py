"""duoforge.python.replay: the M11 replay pipeline against the pinned Showdown
and DuoForge (spec docs/superpowers/specs/2026-10-02-m11-replay-data-design.md
section 14).

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR)
and the runner (DUOFORGE_DIFF_RUNNER); CTest registers it only with all of
them and reports it skipped otherwise. Every input is our own: the committed
reference battles, replayed by the pinned Showdown as spectator logs.
"""
import json
import os
import subprocess
import unittest

from duoforge import _layout
from duoforge_live import data, lines

from python.tests._replay_reference import Reference, true_stats_of

C = _layout.CONSTANTS
TEAM_SELECTION = C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]
# Fields of the own members that the spectator shows the public way (spec section 6), compared with their source.
PUBLIC_OWN = ("hp", "hp_max", "hp_kind", "hp_flag", "pp", "pp_kind")
FROM_PRIOR = ("stats", "stat_points")
HP_UNKNOWN = 3  # DUOFORGE_HP_UNKNOWN (include/duoforge/duoforge.h)
NEWLINE = chr(10)


def node_stats(*args, stdin=None):
    script = data.ROOT / "tools" / "reference" / "ps_stats.js"
    out = subprocess.run([os.environ["DUOFORGE_NODE"], str(script), os.environ["DUOFORGE_PS_REFERENCE_DIR"]] +
                         list(args), input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=300)
    if out.returncode != 0:
        raise AssertionError(f"ps_stats.js {' '.join(args)}: {out.stderr}")
    return json.loads(out.stdout)


class ShowdownFactsTest(unittest.TestCase):
    """Facts of the pinned Showdown the pipeline relies on (Task 4)."""

    def test_choice_items_equal_showdown(self):
        self.assertEqual(list(lines.CHOICE_ITEMS), node_stats("--choice-items"))

    def test_stat_source_serves_showdown_stats(self):
        from duoforge_replay.stats import StatSource
        query = {"species": "Rillaboom", "nature": "Adamant", "sp": [32, 32, 0, 0, 0, 2]}
        want = node_stats(stdin=json.dumps([query]))[0]
        source = StatSource(os.environ["DUOFORGE_NODE"], os.environ["DUOFORGE_PS_REFERENCE_DIR"])
        try:
            self.assertEqual(source.stats("Rillaboom", "Adamant", [32, 32, 0, 0, 0, 2]), want)
            self.assertEqual(source.stats("rillaboom", "adamant", [32, 32, 0, 0, 0, 2]), want)  # ids too
            with self.assertRaisesRegex(ValueError, "unknown species"):
                source.stats("Nope", "Adamant", [0] * 6)
        finally:
            source.close()


def differences(a, b, path=""):
    """The field paths where two records of one structured dtype differ, with both values."""
    out = []
    if a.dtype.names:
        for name in a.dtype.names:
            out += differences(a[name], b[name], f"{path}.{name}" if path else name)
    elif a.shape:
        for i in range(a.shape[0]):
            out += differences(a[i], b[i], f"{path}[{i}]")
    elif a != b:
        out.append(f"{path}: {a} != {b}")
    return out


def spectate(battle, side, source):
    """[(point, observation)] at every point where `side` is asked, from the battle's spectator log."""
    from duoforge_replay import points, spectator
    log = battle.lines
    pts = points.find(log)
    picks = true_picks(battle, side)
    seen = spectator.hindsight_picks(log, side, Reference.get().data, battle_sheets(battle))
    if seen is not None and seen != picks:
        raise AssertionError(f"{battle.name} side {side}: hindsight picks {seen}, true {picks}")
    tracker = spectator.SpectatorTracker(Reference.get().data, battle_sheets(battle), side, picks,
                                         true_stats_of(battle, side, source), log)
    leads, back = spectator.hindsight(log, side, Reference.get().data, battle_sheets(battle))
    out = []
    reached = 0  # points walked: the first point a stop loses is this index
    try:
        for point in spectator.walk(tracker, log, pts):
            reached += 1
            if spectator.own_requested(tracker):
                domain, lists = superset_of(tracker)
                out.append((point, tracker.observation().copy(), (domain, lists), label_of(tracker, log, point, lists,
                                                                                           leads, back)))
    except lines.Stop as stop:
        if not allowed_stop(stop.reason):
            raise
        STOPS[(battle.name, side)] = (stop.reason, reached)
    return out


# Stops for information only the player had (spec section 6), allowed in reference logs; every other stop fails.
HIDDEN = {"charge-target-hidden"}
STOPS = {}


# Features the library models but its view does not show yet: its honest search refuses them with a named, counted
# public cause, and a spectator rightly stops there (decision 0040: Aegislash-Blade, member_ext.forme not filled).
VIEW_REFUSED = {"FORME_CHANGE": "DUOFORGE_PUBLIC_CAUSE_TEMP_FORME"}


def allowed_stop(reason):
    """A stop a committed battle may show: information only its player had, a feature of decision 0018 that the
    library supports and this tracker does not fold yet (its rows would lack the view extension), a feature the
    library's view refuses with a public cause (VIEW_REFUSED), or a view bit encoder 5 cannot show (awaiting-encoder)."""
    if reason in HIDDEN:
        return True
    if reason.startswith("awaiting-encoder:"):
        from duoforge import features
        return reason[len("awaiting-encoder:"):] in features._AWAITING_ENCODER  # a view bit encoder 5 cannot show
    name = reason[len("feature:"):] if reason.startswith("feature:") else None
    if name in VIEW_REFUSED and VIEW_REFUSED[name] in C:
        return True
    pending = lines.LIBRARY_SUPPORTED & ~lines.TRACKER_FOLDS
    return name in lines.FEATURES and bool(pending >> lines.FEATURES[name] & 1)


def label_of(tracker, log, point, lists, leads, back):
    """The label at the tracker's point."""
    from duoforge_replay import labels
    return labels.for_point(tracker, log, point, lists, len(log), leads, back)


def superset_of(tracker):
    """The superset domain and slot lists at the tracker's point."""
    from duoforge_replay import superset
    domain, lists = superset.domain(tracker)
    return domain.copy(), lists


COMMAND = ("kind", "move_slot", "target", "mega", "reserve")


def commands(domain, s):
    return {tuple(int(domain["slots"][s][i][f]) for f in COMMAND) for i in range(int(domain["slot_count"][s]))}


def true_picks(battle, side):
    """The side's team choice from the trace, in the spectator's convention: leads, then the back ascending."""
    text = battle.trace["steps"][0]["input"][f"p{side + 1}"]
    assert text.startswith("team "), text
    picks = [int(c) - 1 for c in text[len("team "):]]
    return tuple(picks[:2]) + tuple(sorted(picks[2:4]))


def battle_sheets(battle):
    from duoforge_live import teams
    packed = {}
    for line in battle.lines:
        if line.startswith("|showteam|"):
            _, _, who, payload = line.split("|", 3)
            packed[int(who[1]) - 1] = teams.unpack(payload)
    return packed[0], packed[1]


class SpectatorTest(unittest.TestCase):
    """Tests 1, 2, 5 and 6 of spec section 14 over every committed battle and both sides (Task 5)."""

    @classmethod
    def setUpClass(cls):
        from duoforge_replay.stats import StatSource
        cls.ref = Reference.get()
        cls.source = StatSource(os.environ["DUOFORGE_NODE"], os.environ["DUOFORGE_PS_REFERENCE_DIR"])
        cls.runs = {}
        for battle in cls.ref.battles:
            for side in (0, 1):
                cls.runs[(battle.name, side)] = spectate(battle, side, cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.source.close()

    def test_reference_logs_never_stop(self):
        # spectate() raised in setUpClass for any stop but a documented hidden-information one
        print(f"\nhidden-information stops: {sorted(STOPS.items())}")
        self.assertTrue(all(allowed_stop(reason) for reason, _ in STOPS.values()), STOPS)

    def test_points_equal_duoforge(self):
        for battle in self.ref.battles:
            for side in (0, 1):
                want = sorted(k for (k, viewer), (obs, _) in battle.views.items()
                              if viewer == side and obs["requested"] == 1)
                last = max(k for k, _ in battle.views)
                if int(battle.views[(last, side)][0]["boundary_kind"]) in (C["DUOFORGE_BOUNDARY_REPLACEMENT"],
                                                                           C["DUOFORGE_BOUNDARY_PIVOT"]):
                    # the trace ends at an unanswered switch request: no switch line shows it, so no point
                    want = [k for k in want if k != last]
                if (battle.name, side) in STOPS:  # the perspective stopped: points up to the stop's epoch
                    want = [k for k in want if k < STOPS[(battle.name, side)][1]]
                got = [int(obs["epoch"]) - 1 for _, obs, *_ in self.runs[(battle.name, side)]]
                self.assertEqual(got, want, (battle.name, side))

    def test_view_equals_duoforge(self):
        for battle in self.ref.battles:
            for side in (0, 1):
                for point, obs, *_ in self.runs[(battle.name, side)]:
                    k = int(obs["epoch"]) - 1
                    theirs = battle.views[(k, side)][0].copy()
                    foe_view = battle.views[(k, 1 - side)][0]
                    where = f"{battle.name} k={k} side={side}"
                    ours = obs.copy()
                    own, their_own = ours["sides"][side], theirs["sides"][side]
                    for m in range(int(own["member_count"])):
                        mine, real, public = own["members"][m], their_own["members"][m], foe_view["sides"][side]["members"][m]
                        if public["hp_kind"] == HP_UNKNOWN:  # never entered: full, shown as 100/100
                            self.assertEqual((int(mine["hp"]), int(mine["hp_max"])), (100, 100), (where, m))
                            self.assertEqual(int(real["hp"]), int(real["hp_max"]), (where, m))
                            self.assertEqual(int(mine["hp_kind"]), C["DUOFORGE_HP_PERCENT"], (where, m))
                            for f in ("pp", "pp_kind"):
                                self.assertEqual(mine[f].tolist(), public[f].tolist(), (where, m, f))
                        else:
                            for f in PUBLIC_OWN:
                                self.assertEqual(mine[f].tolist(), public[f].tolist(), (where, m, f))
                        for f in PUBLIC_OWN:
                            mine[f] = real[f]
                    order, real_order = own["brought_order"], their_own["brought_order"]
                    self.assertEqual(order[:2].tolist(), real_order[:2].tolist(), where)
                    self.assertEqual(sorted(order[2:4].tolist()), sorted(real_order[2:4].tolist()), where)
                    own["brought_order"] = their_own["brought_order"]
                    diff = differences(ours, theirs)
                    self.assertFalse(diff, f"{where}: " + "; ".join(diff[:12]))

    def test_stats_equal_duoforge(self):
        # test_view_equals_duoforge compares stats and stat points with the true team as the prior; this names a
        # member whose Showdown stats differ from DuoForge's own on its own.
        for battle in self.ref.battles:
            for side in (0, 1):
                for _, obs, *_ in self.runs[(battle.name, side)][:1]:
                    theirs = battle.views[(int(obs["epoch"]) - 1, side)][0]["sides"][side]["members"]
                    for m in range(int(obs["sides"][side]["member_count"])):
                        self.assertEqual(obs["sides"][side]["members"][m]["stats"].tolist(),
                                         theirs[m]["stats"].tolist(), (battle.name, side, m))

    def test_superset_contains_duoforge(self):
        from duoforge_replay import superset  # noqa: F401  (the module under test)
        team = C["DUOFORGE_CHOICE_TEAM_SELECTION"]
        for battle in self.ref.battles:
            for side in (0, 1):
                for _, obs, (domain, _), _ in self.runs[(battle.name, side)]:
                    k = int(obs["epoch"]) - 1
                    theirs = battle.views[(k, side)][1]
                    where = (battle.name, k, side)
                    self.assertEqual((int(domain["epoch"]), int(domain["kind"])),
                                     (int(theirs["epoch"]), int(theirs["kind"])), where)
                    if int(theirs["kind"]) == team:
                        self.assertEqual(domain.tobytes(), theirs.tobytes(), where)
                        continue
                    for s in (0, 1):
                        missing = commands(theirs, s) - commands(domain, s)
                        self.assertFalse(missing, (where, s, sorted(missing)))

    def test_production_path_keeps_known_charge_targets(self):
        # review I1: game.process (the production path) must know the own charging targets spectate() knows
        from duoforge_replay import game, prior
        empty = prior.Prior({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]})
        checked = 0
        for battle in self.ref.battles:
            if not any("[still]" in line for line in battle.lines):
                continue
            try:
                result = game.process(battle.name, "gen9championsvgc2026regmc", NEWLINE.join(battle.lines),
                                      self.ref.data, empty, self.source)
            except game.Skip:
                continue  # a development team (No Ability): never in a replay
            checked += 1
            hidden = result.counters["perspectives.stopped.charge-target-hidden"]
            self.assertLessEqual(hidden, sum(1 for name, _ in STOPS if name == battle.name), battle.name)
        self.assertGreater(checked, 20)

    def test_fixture_is_showdowns_output(self):
        # the unit tests' committed spectator log is the pinned Showdown's, never stale
        fixture = data.ROOT / "python" / "tests" / "data" / "replay" / "c12_real_cb_4.log"
        battle = next(b for b in self.ref.battles if b.name == "c12_real_cb_4")
        self.assertEqual(fixture.read_text(encoding="utf-8").splitlines(), battle.lines)

    def test_true_choice_in_label(self):
        from duoforge_live.data import trace_to_c
        from duoforge_live.game import TEAM_TABLE
        from duoforge_replay import labels
        exact = slots = 0
        for battle in self.ref.battles:
            trace = battle.trace
            state0 = trace["start"]["state"]
            roster_names = []
            for s in range(2):
                names = {trace_to_c.name_of(p): i for i, p in enumerate(state0["sides"][s]["pokemon"])}
                for species, protocol in trace_to_c.BASE_SPECIES_NAME.items():
                    if species in names:
                        names[protocol] = names[species]
                roster_names.append(names)
            for side in (0, 1):
                for point, obs, (domain, lists), label in self.runs[(battle.name, side)]:
                    k = int(obs["epoch"]) - 1
                    where = (battle.name, k, side)
                    if k >= len(trace["steps"]):
                        continue  # the trace ends at this point: no choice was made
                    text = trace["steps"][k]["input"][f"p{side + 1}"]
                    state = state0 if k == 0 else trace["steps"][k - 1]["state"]
                    kind, choice = trace_to_c.convert_choice(text, side, state, roster_names)
                    if kind == "team":
                        index = TEAM_TABLE.index(tuple(choice[:4]))
                        self.assertTrue(label.team[index // 8] >> (index % 8) & 1, (where, text))
                        continue
                    for s in (0, 1):
                        want = tuple(choice[s])
                        found = [i for i, o in enumerate(lists[s])
                                 if (o.kind, o.move_slot, o.target, o.mega, o.reserve) == want]
                        self.assertEqual(len(found), 1, (where, s, text, want))
                        self.assertTrue(label.slots[s] >> found[0] & 1, (where, s, text, label.reasons[s]))
                        if label.reasons[s] != labels.NOT_REQUESTED:
                            slots += 1
                            exact += label.reasons[s] == labels.EXACT
        print(f"\nlabels: {exact} of {slots} requested slots EXACT ({100.0 * exact / max(slots, 1):.1f} %)")


if __name__ == "__main__":
    unittest.main()
