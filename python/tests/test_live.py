"""duoforge.python.live: the Showdown live adapter against the pinned Showdown.

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR)
and the runner (DUOFORGE_DIFF_RUNNER); CTest registers it only with all of
them and reports it skipped otherwise. Spec section 8, tests 1, 2 and 5.

The reference (built once): every committed closure battle replayed in the
pinned Showdown by tools/reference/ps_client.js (each player's client stream)
and by duoforge_diff_runner --dump-views (what DuoForge shows each player at
every step). Decision point k of a player is its k-th request; DuoForge's
view k is the state after k steps.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from duoforge import _layout
from duoforge_live import data, options, teams
from duoforge_live.data import trace_to_c

C = _layout.CONSTANTS
SLOTS, TEAM = C["DUOFORGE_CHOICE_SLOTS"], C["DUOFORGE_CHOICE_TEAM_SELECTION"]
COMMAND = ("kind", "move_slot", "target", "mega", "reserve")


def node_tool(*args):
    """stdout of tools/reference/ps_client.js with the pinned checkout."""
    script = data.ROOT / "tools" / "reference" / "ps_client.js"
    out = subprocess.run([os.environ["DUOFORGE_NODE"], str(script), os.environ["DUOFORGE_PS_REFERENCE_DIR"]] +
                         list(args), capture_output=True, text=True, encoding="utf-8", timeout=600)
    if out.returncode != 0:
        raise AssertionError(f"ps_client.js {' '.join(args)}: {out.stderr}")
    return out.stdout


class Point:
    """Decision point k of one player: its request, the trace state before step k, DuoForge's views."""

    def __init__(self, battle, player, k, request, messages):
        self.battle, self.player, self.k, self.request, self.messages = battle, player, k, request, messages
        trace = battle.trace
        self.state = trace["start"]["state"] if k == 0 else trace["steps"][k - 1]["state"]
        self.observation, self.domain = battle.views[(k, player)]

    def locked(self):
        """The locked slots of the player and their targets, from Showdown's state (not DuoForge's)."""
        side = self.state["sides"][self.player]
        out = {}
        for slot, index in enumerate(side["active"]):
            lock = side["pokemon"][index].get("locked") if index >= 0 else None
            if lock:
                out[slot] = trace_to_c.abs_target(self.player, lock[1])
        return out


class Battle:
    def __init__(self, name, views, streams, exts):
        self.name = name
        self.spec, self.trace = trace_to_c.load_battle(str(data.ROOT), name)
        self.views = views
        self.exts = exts  # (k, player) -> DuoForge's view extension bytes (all zero: closure battles)
        self.streams = streams  # player -> list of messages (lists of lines)
        state = self.trace["start"]["state"]
        self.roster_names = []  # as convert_battle names a Pokemon in a choice
        for s in range(2):
            names = {trace_to_c.name_of(p): i for i, p in enumerate(state["sides"][s]["pokemon"])}
            for species, protocol in trace_to_c.BASE_SPECIES_NAME.items():
                if species in names:
                    names[protocol] = names[species]
            self.roster_names.append(names)

    def points(self, player):
        """The decision points of `player`: one per request (a new rqid), with the messages up to it."""
        seen, k = set(), 0
        for i, lines in enumerate(self.streams[player]):
            for line in lines:
                if line.startswith("|request|"):
                    request = json.loads(line[len("|request|"):])
                    if request["rqid"] in seen:
                        continue
                    seen.add(request["rqid"])
                    yield Point(self, player, k, request, self.streams[player][:i + 1])
                    k += 1


def runner_dump(tmp, records):
    """duoforge_diff_runner --dump-views --dump-public over tmp/records: (views, exts, publics, causes) by battle name and
    (k, viewer), every battle a PASS."""
    views_path = os.path.join(tmp, records + ".views")
    public_path = os.path.join(tmp, records + ".public")
    out = subprocess.run([os.environ["DUOFORGE_DIFF_RUNNER"], "--dump-views", views_path, "--dump-public", public_path,
                          os.path.join(tmp, records)], capture_output=True, text=True, timeout=600)
    results = [line.split(" ") for line in out.stdout.splitlines() if line.startswith("R ")]
    if out.returncode != 0 or not results or any(r[2] != "PASS" for r in results):
        raise AssertionError(f"the runner: {out.returncode} {out.stderr} {out.stdout[-2000:]}")
    views, exts = {}, {}
    with open(views_path, encoding="ascii") as f:
        for line in f:
            _, name, k, viewer, obs, dom, ext = line.split()
            views.setdefault(name, {})[(int(k), int(viewer))] = (
                np.frombuffer(bytes.fromhex(obs), dtype=_layout.OBSERVATION)[0],
                np.frombuffer(bytes.fromhex(dom), dtype=_layout.FACTORED_DOMAIN)[0])
            exts.setdefault(name, {})[(int(k), int(viewer))] = bytes.fromhex(ext)
    # The engine's public record of each player at each state (the live search's record assembler, Task 1) and the
    # causes of its refusal (duoforge_battle_public_causes).
    publics, causes = {}, {}
    with open(public_path, encoding="ascii") as f:
        for line in f:
            _, name, k, viewer, status, cause, record = line.split()
            publics.setdefault(name, {})[(int(k), int(viewer))] = (
                int(status), None if record == "-" else
                np.frombuffer(bytes.fromhex(record), dtype=_layout.PUBLIC_STATE)[0])
            causes.setdefault(name, {})[(int(k), int(viewer))] = int(cause)
    if sorted(publics) != sorted(views):
        raise AssertionError("the public records and the views name other battles")
    return views, exts, publics, causes


class PoolReference:
    """The committed pool battles (pool.records): the engine's views and public records, and each player's client
    stream, for the record assembler's POOL test. Built on first use (Reference.pool())."""

    def __init__(self, tmp):
        views, exts, self.publics, self.causes = runner_dump(tmp, "pool.records")
        streams = {}
        for line in node_tool(str(data.ROOT), *sorted(views)).splitlines():
            m = json.loads(line)
            streams.setdefault(m["battle"], ([], []))[int(m["to"][1]) - 1].append(m["lines"])
        if sorted(streams) != sorted(views):
            raise AssertionError("the pool client streams and the views name other battles")
        self.battles = [Battle(name, views[name], streams[name], exts[name]) for name in sorted(views)]
        self.battles_by_name = {b.name: b for b in self.battles}
        self.data = data.load(kind="pool")


class Reference:
    """Built once for the module: records, views and client streams of every committed closure battle."""
    _built = None
    _pool = None

    @classmethod
    def get(cls):
        if cls._built is None:
            cls._built = cls()
        return cls._built

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="duoforge_live_")
        atexit.register(shutil.rmtree, self.tmp, True)
        root = str(data.ROOT)
        subprocess.run([sys.executable, str(data.ROOT / "tools" / "reference" / "conformance_records.py"), "--all",
                        root, "--out", self.tmp], check=True, timeout=600)
        views, exts, self.publics, self.causes = runner_dump(self.tmp, "closure.records")
        streams = {}
        for line in node_tool(root, "--all").splitlines():
            m = json.loads(line)
            streams.setdefault(m["battle"], ([], []))[int(m["to"][1]) - 1].append(m["lines"])
        if sorted(streams) != sorted(views):
            raise AssertionError("the client streams and the views name other battles")
        self.battles = [Battle(name, views[name], streams[name], exts[name]) for name in sorted(views)]
        self.battles_by_name = {b.name: b for b in self.battles}
        self.data = data.load()

    def pool(self):
        """The PoolReference of the same records, built once."""
        if Reference._pool is None:
            Reference._pool = PoolReference(self.tmp)
        return Reference._pool


def command(c):
    return tuple(int(c[f]) for f in COMMAND)


class PackTest(unittest.TestCase):
    def test_pack_equals_showdown(self):
        for name, file in teams.FILES.items():
            path = data.ROOT / "tests" / "reference" / "teams" / file
            self.assertEqual(teams.pack(teams.text(name)), node_tool("--pack", str(path)).rstrip("\n"), name)


class PressureExtraTest(unittest.TestCase):
    """Decision 0030 (step G53): the extra PP of the foe's derived PP is Showdown's pressureTargets
    (sim/pokemon.ts getMoveTargets), counted only where the line shows the targets."""

    @classmethod
    def setUpClass(cls):
        from types import SimpleNamespace
        from duoforge_live import tracker
        cls.D = data.load(kind="pool")
        t = tracker.Tracker.__new__(tracker.Tracker)
        t._action = None  # no move action open (Tracker._segment)
        t._herb_end = None
        t.data = cls.D
        t._pressure = cls.D.tables["ABILITY"]["PRESSURE"] + 1
        members = [SimpleNamespace(ability=t._pressure), SimpleNamespace(ability=t._pressure)]
        t._member = lambda side: members
        t._positions = [[SimpleNamespace(occupant=k, fainted=False, ability_now=0) for k in (0, 1)] for _ in (0, 1)]
        cls.t = t
        cls.FLAG = trace_to_c.FLAG

    def extra(self, move, target, flags=0):
        return self.t._pressure_extra(0, self.D.tables["MOVE"][move], target, flags)

    def test_a_spread_line_of_a_normal_move_counts_every_standing_pressure_foe(self):
        # Expanding Force on Psychic Terrain: onModifyMove makes it allAdjacentFoes before getMoveTargets, so
        # pressureTargets are both foes, also one that Protect leaves out of the [spread] list
        self.assertEqual(self.extra("EXPANDINGFORCE", trace_to_c.NOPOS, self.FLAG["SPREAD"]), 2)

    def test_a_spread_line_of_an_allies_move_counts_no_foe(self):
        # target "allies" (Howl, Life Dew): getMoveTargets takes alliesAndSelf, so no foe is a pressureTarget
        move = next(m for m in ("HOWL", "LIFEDEW", "JUNGLEHEALING", "LUNARBLESSING") if m in self.D.tables["MOVE"])
        self.assertEqual(self.extra(move, trace_to_c.NOPOS, self.FLAG["SPREAD"]), 0)

    def test_a_single_target_line_counts_its_target(self):
        self.assertEqual(self.extra("EXPANDINGFORCE", 2), 1)

    def test_a_blanked_target_counts_nothing(self):
        self.assertEqual(self.extra("EXPANDINGFORCE", trace_to_c.NOPOS, self.FLAG["STILL"] | self.FLAG["SPREAD"]), 0)
class BatonPassTest(unittest.TestCase):
    """Step G74 (decision 0042): the receiver of a Baton Pass (`|switch|...|[from] move: Baton Pass`, no volatile
    lines) takes the leaver's stages and confusion, the base view's fields; a plain switch resets them. The other
    copied volatiles are decision 0018 features, which stopped the tracker at their start lines."""

    def _tracker(self):
        from duoforge_live import tracker
        from types import SimpleNamespace
        D = data.load(kind="pool")
        t = tracker.Tracker.__new__(tracker.Tracker)
        t._action = None  # no move action open (Tracker._segment)
        t._herb_end = None
        t.data, t.side, t._spectator = D, 0, False
        t._baton_pass = D.tables["MOVE"]["BATONPASS"]
        t._next_activation, t._foe_leads, t._party = 1, [tracker.ROSTER_NONE] * 2, None  # the public record's entry folds
        members = [SimpleNamespace(seen=False, hp_percent=100, hp_flag=0, status=0) for _ in range(6)]
        t._member = lambda side: members
        t._positions = [[tracker._Position(), tracker._Position()], [tracker._Position(), tracker._Position()]]
        leaver = t._positions[0][0]
        leaver.occupant, leaver.stages, leaver.confused = 0, [8, 6, 6, 4, 6, 6, 6], 1
        return t, D, tracker

    def test_the_receiver_takes_stages_and_confusion(self):
        t, D, tracker = self._tracker()
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 3,
                                     D.tables["MOVE"]["BATONPASS"], 100, 100, 1))
        p = t._positions[0][0]
        self.assertEqual((p.occupant, p.stages, p.confused), (3, [8, 6, 6, 4, 6, 6, 6], 1))

    def test_a_plain_switch_resets_them(self):
        t, D, tracker = self._tracker()
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["SWITCH"], 0, trace_to_c.NOPOS, 0, 3, 0, 100, 100, 1))
        p = t._positions[0][0]
        self.assertEqual((p.occupant, p.stages, p.confused), (3, [tracker.STAGE_NEUTRAL] * 7, 0))


class SetBoostTest(unittest.TestCase):
    """Steps G86 and G77: Belly Drum's and Anger Point's -setboost show the Attack stage they leave
    (sim/battle.ts:2051-2052); the tracker sets the position's stage to it, as the engine's BOOST event of the change does
    (src/combat/turn.c dfi_boost: cause MOVE for Belly Drum, cause ABILITY for Anger Point)."""
    LINES = ("|-setboost|p1a: Snorlax|atk|6|[from] move: Belly Drum", "|-setboost|p1a: Primeape|atk|6|[from] ability: Anger Point")

    def tracker(self, stage):
        from types import SimpleNamespace
        from duoforge_live import tracker
        t = tracker.Tracker.__new__(tracker.Tracker)
        t._action = None  # no move action open (Tracker._segment)
        t._herb_end = None
        t.side, t._spectator, t.data = 0, False, data.load(kind="pool")
        t._last_move, t._parting_shot = None, -1
        p = SimpleNamespace(occupant=0, fainted=False, stages=[tracker.STAGE_NEUTRAL] * 7)
        p.stages[0] = stage
        t._positions = [[p, SimpleNamespace(occupant=1, fainted=False, stages=[6] * 7)],
                        [SimpleNamespace(), SimpleNamespace()]]
        return t, p

    def test_the_stage_becomes_the_printed_one(self):
        from duoforge_live import tracker
        for start in (tracker.STAGE_NEUTRAL - 2, tracker.STAGE_NEUTRAL, tracker.STAGE_NEUTRAL + 3):
            for line in self.LINES:
                t, p = self.tracker(start)
                t._set_boost(line.split("|"))
                self.assertEqual(p.stages[0], tracker.STAGE_NEUTRAL + 6, (start, line))
                self.assertEqual(p.stages[1:], [tracker.STAGE_NEUTRAL] * 6)

    def test_no_positive_change_stops(self):
        from duoforge_live import lines, tracker
        for line in self.LINES:
            t, p = self.tracker(tracker.STAGE_NEUTRAL + 6)
            with self.assertRaises(lines.Stop) as caught:
                t._set_boost(line.split("|"))
            self.assertEqual(caught.exception.reason, "converter:setboost-change", line)


class ClearAllBoostsTest(unittest.TestCase):
    """Step G62 (decision 0031): Haze's CLEAR_ALL_BOOSTS returns the stages of every standing active Pokemon to
    neutral (data/moves.ts haze onHitField: getAllActive, sim/pokemon.ts clearBoosts); an empty or fainted position
    keeps what it holds."""

    def test_every_standing_active_position_returns_to_neutral(self):
        from types import SimpleNamespace
        from duoforge_live import tracker
        t = tracker.Tracker.__new__(tracker.Tracker)
        t._action = None  # no move action open (Tracker._segment)
        t._herb_end = None
        t.side, t._spectator = 0, False
        raised = [8, 4, 6, 6, 6, 9, 6]

        def position(occupant, fainted=False):
            return SimpleNamespace(occupant=occupant, fainted=fainted, stages=list(raised))

        t._positions = [[position(0), position(1)], [position(2, fainted=True), position(tracker.ROSTER_NONE)]]
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["CLEAR_ALL_BOOSTS"]))
        self.assertEqual([p.stages for p in t._positions[0]], [[tracker.STAGE_NEUTRAL] * 7] * 2)
        self.assertEqual([p.stages for p in t._positions[1]], [raised, raised])


class BreakProtectTest(unittest.TestCase):
    """Steps G28 and G58: a breaksProtect move's -activate (Feint, Phantom Force [broken]) removes the target's Protect
    and stall and its side's Wide and Quick Guard (sim/battle-actions.ts hitStepBreakProtect, the same for both)."""

    def test_phantom_force_breaks_like_feint(self):
        from types import SimpleNamespace
        from duoforge_live import tracker
        D = data.load(kind="pool")
        for move in ("FEINT", "PHANTOMFORCE"):
            t = tracker.Tracker.__new__(tracker.Tracker)
            t._action = None  # no move action open (Tracker._segment)
            t._herb_end = None
            t.data, t.side, t._spectator = D, 0, False
            t._feint = D.tables["MOVE"]["FEINT"]
            t._phantom_force = D.tables["MOVE"]["PHANTOMFORCE"]
            target = SimpleNamespace(protecting=1, chain=2, stall=1, guard_undo=(1, 0))
            t._positions = [[SimpleNamespace(), SimpleNamespace()], [target, SimpleNamespace()]]
            t._guards = {("WIDE_GUARD", 1)}
            t._turn_scoped = {"WIDE_GUARD"}
            t._event(trace_to_c.ev_tuple(trace_to_c.EV["ACTIVATE"], 2, trace_to_c.NOPOS, trace_to_c.CAUSE["MOVE"], 0,
                                         D.tables["MOVE"][move]))
            self.assertEqual((target.protecting, target.chain, target.stall, target.guard_undo), (0, 0, 0, None), move)
            self.assertEqual((t._guards, t._turn_scoped), (set(), set()), move)


class LockedMoveSlotTest(unittest.TestCase):
    """View audit of 2026-10-10 (#323): a foe whose last used move is a lockedmove (Outrage, Thrash, Petal Dance:
    DUOFORGE_MOVE_STATIC_FLAG_LOCKED_MOVE) shows no locked slot, a Choice lock included, as the C observation hides it
    (src/state/observation.c dfi_maybe_lockedmove). The last move is pokemon.moveUsed's: set by the position's own
    move lines (a locked turn included), not by a move another effect makes it use, cleared when it leaves."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live import tracker
        cls.tracker = tracker
        cls.D = data.load(kind="pool")
        cls.M = cls.D.tables["MOVE"]

    def setUp(self):
        from types import SimpleNamespace
        t = self.tracker.Tracker.__new__(self.tracker.Tracker)
        t._action = None  # no move action open (Tracker._segment)
        t._herb_end = None
        t.data, t.side, t._spectator = self.D, 0, False
        from duoforge_live import lines
        items = self.D.tables["ITEM"]
        band = next(items[k.upper()] for k in lines.CHOICE_ITEMS if k.upper() in items) + 1  # a Choice holder (#334)
        t._guard_moves, t._choice_items = set(), {band}
        t._turn, t._move_pivots = 1, {}  # the public record's folds of a move line
        t._positions = [[self.tracker._Position(), self.tracker._Position()],
                        [self.tracker._Position(), self.tracker._Position()]]
        for side in t._positions:
            for k, p in enumerate(side):
                p.occupant = k
        sheet = {"item": band, "moves": [self.M["OUTRAGE"], self.M["DRAGONCLAW"], self.M["PROTECT"]]}
        t._occupant = lambda pos: SimpleNamespace(sheet=sheet, uses=[0, 0, 0], item_used=0, item_now=0)
        t._pressure_extra = lambda *a: 0
        self.t = t

    def move(self, pos, name, cause=0, flags=0):
        self.t._event(trace_to_c.ev_tuple(trace_to_c.EV["MOVE"], pos, 0, cause, self.M[name], flags=flags))

    def test_a_foe_after_a_lockedmove_shows_no_locked_slot(self):
        p = self.t._positions[1][0]
        p.choice_slot = 0
        self.move(2, "OUTRAGE")
        self.assertEqual(self.t._shown_locked_slot(p, own=False), self.tracker.MOVE_SLOT_NONE)
        self.move(2, "OUTRAGE", flags=trace_to_c.FLAG["LOCKED"])  # a locked turn is a move use too
        self.assertEqual(self.t._shown_locked_slot(p, own=False), self.tracker.MOVE_SLOT_NONE)

    def test_a_foe_after_another_move_shows_its_choice_slot(self):
        p = self.t._positions[1][0]
        p.choice_slot = 1
        self.move(2, "DRAGONCLAW")
        self.assertEqual(self.t._shown_locked_slot(p, own=False), 1)

    def test_a_move_used_through_another_effect_is_not_the_last_move(self):
        p = self.t._positions[1][0]
        p.choice_slot = 1
        self.move(2, "DRAGONCLAW")
        self.move(2, "OUTRAGE", cause=trace_to_c.CAUSE["ABILITY"])  # e.g. reflected by Magic Bounce: no moveUsed
        self.assertEqual(self.t._shown_locked_slot(p, own=False), 1)

    def test_leaving_clears_the_last_move(self):
        p = self.t._positions[1][0]
        self.move(2, "OUTRAGE")
        p.reset()
        p.choice_slot = 1
        self.assertEqual(self.t._shown_locked_slot(p, own=False), 1)

    def test_the_own_side_is_unchanged(self):
        p = self.t._positions[0][0]
        p.choice_slot = 0
        self.move(0, "OUTRAGE")
        self.assertEqual(self.t._shown_locked_slot(p, own=True), 0)


class OptionsTest(unittest.TestCase):
    """Test 1 (the options) and test 2 (the choice text) of the spec."""

    @classmethod
    def setUpClass(cls):
        cls.ref = Reference.get()

    def lists(self, point):
        own = self.ref.data.team(point.battle.spec["teams"][point.player])
        roster_of = options.own_roster(point.request, own, self.ref.data)
        return options.slot_options(point.request, point.player, roster_of, point.locked())

    def test_options_equal_duoforge(self):
        points = 0
        for battle in self.ref.battles:
            for player in (0, 1):
                # One point per step, and one more when the battle did not end (its last view asks again).
                count = sum(1 for _ in battle.points(player))
                steps = len(battle.trace["steps"])
                self.assertIn(count, (steps, steps + 1), (battle.name, player))
                for point in battle.points(player):
                    where = (battle.name, point.k, player)
                    dom = point.domain
                    r = point.request
                    points += 1
                    if r.get("wait"):
                        self.assertEqual(int(dom["kind"]), 0, where)
                        continue
                    if r.get("teamPreview"):
                        own = options.team_domain(point.k + 1, len(battle.spec["teams"][player].strip().split("\n\n")),
                                                  r["maxChosenTeamSize"])
                        self.assertEqual(own.tobytes(), dom.tobytes(), where)
                        continue
                    self.assertEqual(int(dom["kind"]), SLOTS, where)
                    lists = self.lists(point)
                    mine = options.domain(lists, point.k + 1)
                    # The documented order too, not only the sets (options.py promises it).
                    self.assertEqual(mine["slot_count"].tobytes(), dom["slot_count"].tobytes(), where)
                    self.assertEqual(mine["slots"].tobytes(), dom["slots"].tobytes(), where)
                    for s in (0, 1):
                        theirs = {command(dom["slots"][s][i]) for i in range(int(dom["slot_count"][s]))}
                        ours = [(o.kind, o.move_slot, o.target, o.mega, o.reserve) for o in lists[s]]
                        self.assertEqual(len(ours), len(set(ours)), where)
                        self.assertEqual(set(ours), theirs, (where, s))
                    index = [{(o.kind, o.move_slot, o.target, o.mega, o.reserve): i for i, o in enumerate(lists[s])}
                             for s in (0, 1)]
                    for i in range(int(dom["slot_count"][0])):
                        for j in range(int(dom["slot_count"][1])):
                            if (int(dom["allowed"][i]) >> j) & 1:
                                a, b = index[0][command(dom["slots"][0][i])], index[1][command(dom["slots"][1][j])]
                                self.assertTrue((int(mine["allowed"][a]) >> b) & 1, (where, i, j))
        self.assertGreater(points, 2000)

    def test_choice_text_round_trip(self):
        from duoforge_learn.selfplay import TEAM_TABLE
        pairs = 0
        for battle in self.ref.battles:
            for player in (0, 1):
                for point in battle.points(player):
                    r, dom, where = point.request, point.domain, (battle.name, point.k, player)
                    if r.get("wait"):
                        continue
                    if r.get("teamPreview"):
                        for picks in TEAM_TABLE[:: 7]:
                            text = options.team_text(tuple(int(p) for p in picks))
                            got = trace_to_c.convert_choice(text, player, point.state, battle.roster_names)
                            self.assertEqual(got, ("team", [int(p) for p in picks]), (where, text))
                        continue
                    lists = self.lists(point)
                    index = [{(o.kind, o.move_slot, o.target, o.mega, o.reserve): o for o in lists[s]} for s in (0, 1)]
                    for i in range(int(dom["slot_count"][0])):
                        for j in range(int(dom["slot_count"][1])):
                            if not (int(dom["allowed"][i]) >> j) & 1:
                                continue
                            want = [command(dom["slots"][0][i]), command(dom["slots"][1][j])]
                            text = options.pair_text(index[0][want[0]], index[1][want[1]])
                            got = trace_to_c.convert_choice(text, player, point.state, battle.roster_names)
                            self.assertEqual((got[0], [tuple(c) for c in got[1]]), ("slots", want), (where, text))
                            pairs += 1
        self.assertGreater(pairs, 10000)


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


def run_tracker(battle, player, stream=None, sheet_text=None):
    """[(k, tracker observation, tracker domain, lists, tracker view extension)] at every decision point of `player`,
    feeding the stream message by message and the recorded own choices as accepted."""
    from duoforge_live.tracker import Tracker
    tracker = Tracker(Reference.get().data, sheet_text or battle.spec["teams"][player])
    pid = f"p{player + 1}"
    out, done = [], 0
    for lines in stream if stream is not None else battle.streams[player]:
        tracker.feed(lines)
        if tracker.ready and tracker.epoch > done:
            done = tracker.epoch
            k = done - 1
            dom, lists = tracker.domain()
            out.append((k, tracker.observation(), dom, lists, tracker.observation_ext()))
            step = battle.trace["steps"][k] if k < len(battle.trace["steps"]) else None
            if step is not None and pid in step["input"]:
                tracker.accepted(step["input"][pid])
    return out


def record_diff(battle_name, k, viewer, record):
    """The tracker's record assembler against the engine (live honest search, plan 2026-10-10 Task 1): the engine's
    public record of `viewer` at decision point k of a committed battle beside an assembled `record`
    (PUBLIC_STATE). Returns {"boundary", "player", "engine_status", "engine_causes", "fields"}: the boundary and player of
    the engine's view, its status (0, or the refusal), the cause mask of duoforge_battle_public_causes, and the differing
    header fields and state fields (duoforge.state_layout names); fields == [] means byte-identical. A refused engine
    record compares nothing (fields None)."""
    from duoforge import state_layout
    ref = Reference.get() if battle_name in Reference.get().publics else Reference.get().pool()
    status, want = ref.publics[battle_name][(int(k), int(viewer))]
    obs, _ = ref.battles_by_name[battle_name].views[(int(k), int(viewer))]
    out = {"boundary": int(obs["boundary_kind"]), "player": int(viewer), "engine_status": status, "fields": None,
           "engine_causes": ref.causes[battle_name][(int(k), int(viewer))]}
    if status != 0:
        return out
    got = np.asarray(record)
    header = [n for n in want.dtype.names if n not in ("state", "pad") and not np.array_equal(want[n], got[n])]
    size = int(want["state_size"])
    out["fields"] = header + state_layout.diff(np.asarray(want["state"])[:size].tobytes(),
                                              np.asarray(got["state"])[:size].tobytes(),
                                              pool=size > state_layout.V3_SIZE)
    return out


# The outcome of every decision point of the committed corpus (deterministic): byte-identical records, refusals equal to the
# engine's (status, causes, an all-zero record), and the tracker's own named refusals; the pool streams the tracker stops
# (lines.Stop: an unfolded feature's line), by reason.
CLOSURE_OUTCOME = {"equal": 2594, "refused": 310}
# Batch 7 pins (deliberate, measured on hs/batch7-python; main had equal 9898 / refused 487 and the stops {SUBSTITUTE 78,
# FORME_CHANGE 10, DESTINY_BOND 10, DRAGON_CHEER 8, ROOST 8, line:-end 2, ILLUSION 2}): the 865 pool battles now hold the
# conformance battles of G84 to G92 (Leech Seed, Curse, Belly Drum, Confuse Ray, Swagger, Flatter, Teeter Dance, Memento and
# the sub-fixes), so more decision points are compared; no "move-result-not-determined" refusal is left (the classifier maps
# those handlers, src/state/view.c mr_family_of). The tracker folds Leech Seed (EXT_FOLDS, step G84): the 12 streams that
# stopped on feature:LEECH_SEED run on (equal 10470 -> 10558, +88 decision points; 2 of them stop on a later Substitute,
# 96 -> 98), and the feature has no stop of its own any more.
# lane B batch 5c (G71 Cute Charm, G75 cheap set): +144 equal and +2 refused records; 12 streams stop on the Attract lines
# (unfolded:DUOFORGE_POSITION_EXT_ATTRACT, the tracker fold of the ATTRACT bit comes after G71), 4 more on Dragon Cheer (the
# G75 crit battles). Lane B batch 5d (G79 Cloud Nine, G81 Frisk): +170 equal and +18 refused records, no new stop.
# PR #393 (the Attract fold, G71 on the tracker): the 12 unfolded:DUOFORGE_POSITION_EXT_ATTRACT streams are gone (the fold
# reaches their later points): +30 equal, +4 refused, and 42 infatuated points whose tracker refusal is the engine check's
# verdict (duoforge_public_record_check refuses a world with an infatuated occupant, lead's option B), counted apart. Measured
# on the merged tree (CI, Linux and Windows Python jobs, identical): 10242 equal, 511 refused, 42 engine-check refusals.
# lane B G83 (Iron Ball, Bulletproof, Rivalry, Leaf Guard): +64 equal; +4 refused, all g83_ironball_ground under the
# visible-confusion cause (mask 2); no new stop. Measured on the merged tree (main 6c16c960 + G83): 10306 equal, 515 refused.
# Batch 7 (base: main before batch 7, equal 9898 / refused 487): G84 Leech Seed fold, the G86, G92 and C4 moves and the
# sub-fixes-2 moves add +660 equal and +122 refused; the SUBSTITUTE stops go 78 -> 98 (the Leech Seed streams run on to a
# later Substitute). Main (+408 equal, +28 refused): Attract #393, lane B G79/G81/G83 and the infatuated engine check.
# Measured on the merged tree (CI 38140646950, Windows Python job): 10966 equal, 637 refused.
# lane B G87 (the Attract source public; HS fold hs/g87-python): the 42 infatuated points build now: +42 equal, the engine-check
# refusal is gone. Lane B G77 (crit package): +74 equal (its eight battles), no new refused record or stop. Measured on the
# merged tree (main 0bc8d8d9 + G77 + G87): 11082 equal, 637 refused.
POOL_OUTCOME = {"equal": 11082, "refused": 637, "tracker refuses: unburden-without-item-line": 4}
POOL_STOPS = {"feature:SUBSTITUTE": 98, "feature:DRAGON_CHEER": 12, "feature:FORME_CHANGE": 10, "feature:DESTINY_BOND": 10,
              "feature:ROOST": 8, "line:-end": 2, "feature:ILLUSION": 2}


INFATUATED_REFUSAL = "engine check refuses: infatuated occupant (from_view, option B)"


def infatuated_in_engine(battle_name, k, viewer):
    """Whether the engine's public record of `viewer` at decision point k has an Attract source (the tail5 reserve bytes)."""
    from duoforge import state_layout
    ref = Reference.get() if battle_name in Reference.get().publics else Reference.get().pool()
    status, record = ref.publics[battle_name][(int(k), int(viewer))]
    if status != 0:
        return False
    start, size = next((s, n) for name, s, n in state_layout.fields(pool=True) if name == "tail5.attract_source")
    return bool(np.asarray(record["state"])[start:start + size].any())


def record_kind(battle_name):
    """The library data kind the runner played a battle under, as the tracker's record_kind (None: the tables' kind,
    CLOSURE; CLOSURE_DEV for a battle the runner created under the DEV fallback): read from the fingerprint of the
    engine's records, a constant of the context."""
    from duoforge import state_layout
    start, size = next((s, n) for name, s, n in state_layout.fields(pool=False) if name == "fingerprint")
    ref = Reference.get() if battle_name in Reference.get().publics else Reference.get().pool()
    head = ref.data.record_head()[0]
    dev = C["DUOFORGE_DATA_KIND_CLOSURE_DEV"] if ref.data.kind == "closure" else C["DUOFORGE_DATA_KIND_POOL_DEV"]
    for status, record in ref.publics[battle_name].values():
        if status == 0:
            if bytes(record["state"][start:start + size]) == head[start:start + size]:
                return None
            if bytes(record["state"][start:start + size]) == ref.data.record_head(dev)[0][start:start + size]:
                return dev
            raise AssertionError(f"{battle_name}: a record of an unknown context")
    return None


class RecordHarnessTest(unittest.TestCase):
    """The engine records the tracker's assembler is compared with: one per player and state, refused or self-consistent."""

    def test_engine_records_cover_every_state(self):
        ref = Reference.get()
        supported = 0
        for battle in ref.battles:
            for (k, viewer), (obs, _) in battle.views.items():
                status, record = ref.publics[battle.name][(k, viewer)]
                self.assertIn(status, (0, C["DUOFORGE_E_UNSUPPORTED"]), (battle.name, k, viewer))
                result = record_diff(battle.name, k, viewer, record if record is not None else np.zeros((), _layout.PUBLIC_STATE))
                self.assertEqual((result["boundary"], result["player"]), (int(obs["boundary_kind"]), viewer))
                if status == 0:
                    supported += 1
                    self.assertEqual(result["fields"], [], (battle.name, k, viewer))
                    self.assertEqual(int(record["boundary"]), int(obs["boundary_kind"]))
                    changed = record.copy()
                    changed["turn"] += 1
                    self.assertEqual(record_diff(battle.name, k, viewer, changed)["fields"], ["turn"])
                else:
                    self.assertIsNone(result["fields"])
        self.assertGreater(supported, 100)


class RecordAssemblerTest(unittest.TestCase):
    """The tracker's public record (Tracker.public_parts, duoforge_live.record; M12 option A) is the engine's, byte for
    byte, at every decision point of both players of every committed closure battle; where the engine refuses the
    record, the tracker refuses with the same status and the cause mask that duoforge_battle_public_causes gives. The
    engine's own check (from_view, then public) gives every assembled record back and refuses one that fills a masked
    field; the request is the engine's."""

    @classmethod
    def setUpClass(cls):
        from duoforge_live.tracker import Tracker
        cls.ref = Reference.get()
        cls.points = {}  # (battle, player) -> [(k, parts)]
        for battle in cls.ref.battles:
            for player in (0, 1):
                tracker, done, pid = Tracker(cls.ref.data, battle.spec["teams"][player]), 0, f"p{player + 1}"
                tracker.record_kind = record_kind(battle.name)
                out = cls.points[(battle.name, player)] = []
                for lines in battle.streams[player]:
                    tracker.feed(lines)
                    if not (tracker.ready and tracker.epoch > done):
                        continue
                    done = tracker.epoch
                    k = done - 1
                    out.append((k, tracker.public_parts()))
                    step = battle.trace["steps"][k] if k < len(battle.trace["steps"]) else None
                    if step is not None and pid in step["input"]:
                        tracker.accepted(step["input"][pid])

    def test_record_equals_engine(self):
        import collections
        import re
        outcome, fields, where = collections.Counter(), collections.Counter(), {}
        for (name, player), points in self.points.items():
            for k, parts in points:
                result = record_diff(name, k, player, parts["record"])
                if result["engine_status"] != 0:
                    same = (parts["status"], parts["causes"], parts["record"].tobytes()) == (
                        result["engine_status"], result["engine_causes"], bytes(_layout.PUBLIC_STATE.itemsize))
                    key = "refused" if same else f"engine refuses ({result['engine_causes']}): {parts['reason']}"
                elif parts["status"] != 0:
                    key = f"tracker refuses: {parts['reason']}"
                else:
                    key = "mismatch" if result["fields"] else "equal"
                    for field in result["fields"]:
                        fields[re.sub(r"\d+", "#", field)] += 1
                        where.setdefault(re.sub(r"\d+", "#", field), (name, k, player, field))
                outcome[key] += 1
                where.setdefault(key, (name, k, player))
        print(f"\nrecord assembler: {dict(sorted(outcome.items()))}")
        self.assertFalse(fields, {field: (n, where[field]) for field, n in fields.most_common()})
        self.assertEqual(dict(outcome), CLOSURE_OUTCOME, {key: where[key] for key in outcome})

    def test_request_equals_engine(self):
        for (name, player), points in self.points.items():
            for k, parts in points:
                obs, dom = self.ref.battles_by_name[name].views[(k, player)]
                r, where = parts["request"], (name, k, player)
                self.assertEqual([int(r[f]) for f in ("epoch", "boundary_kind", "player", "requested", "slot_mask")],
                                 [int(obs[f]) for f in ("epoch", "boundary_kind", "player", "requested", "slot_mask")],
                                 where)
                self.assertEqual(int(r["candidate_count"]), 0, where)  # not assembled (Tracker.request_record)

    def test_engine_gives_every_assembled_record_back(self):
        import duoforge
        from duoforge_live import record
        contexts = {kind: duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_CLOSURE"] if kind is None else kind)
                    for kind in (None, C["DUOFORGE_DATA_KIND_CLOSURE_DEV"])}
        try:
            checked = refused = 0
            for (name, player), points in self.points.items():
                ctx = contexts[record_kind(name)]
                for k, parts in points:
                    if parts["status"] != 0:
                        continue
                    rec = parts["record"]
                    self.assertEqual(record.check(ctx, rec), 0, (name, k, player))
                    checked += 1
                    if int(rec["boundary"]) == C["DUOFORGE_BOUNDARY_TURN"] and refused < 50:
                        # a field the engine masks (the foe's exact HP of its first member) filled: refused
                        bad = rec.copy()
                        start = next(s for f, s, _ in state_layout_fields() if f == f"side{1 - player}.member0.hp")
                        bad["state"][start] ^= 1
                        self.assertEqual(duoforge.status_name(record.check(ctx, bad)), "DUOFORGE_E_MALFORMED",
                                         (name, k, player))
                        refused += 1
            self.assertEqual((checked, refused), (CLOSURE_OUTCOME["equal"], 50))
        finally:
            for ctx in contexts.values():
                ctx.close()


class RecordAssemblerPoolTest(unittest.TestCase):
    """The record assembler under the POOL kind (the tracker with the pool tables), over every committed pool battle,
    both players, every decision point until the tracker stops at a line it does not fold (lines.Stop, counted by
    reason): each record is the engine's byte for byte, or refused with the engine's status and cause mask, or refused
    by the tracker with a named reason of TRACKER_REFUSALS where the engine has a record the lines do not determine. The
    tail's move_result comes from the library's classification of each move action (duoforge_move_result)."""

    # unburden-without-item-line: Unburden answering a Knock Off that removes nothing (a Mega Stone) shows no line;
    # move-result-not-determined: the library cannot tell an action's result from its events (duoforge_move_result
    # refuses); last-move-not-on-sheet: the move of a position's last line is on no slot of its sheet
    TRACKER_REFUSALS = {"unburden-without-item-line", "move-result-not-determined", "last-move-not-on-sheet",
                        "own-command-unknown", "pivot-switch-reason-unknown"}
    # The tracker's own-PP check (Tracker._on_request) refuses these player streams before a record: Pressure the lines
    # cannot attribute (a [still] target, a clamped extra), Dragon Darts' split, the Pressure of a disguised Illusion.
    OWN_PP_STOPS = {("g53_field_trick_room", 0), ("g53_still_pressure", 1), ("g78_ee_t", 0), ("g78_fainted_ally", 0),
                    ("g78_fainted_target", 0), ("g78_ko_t_hit1", 0), ("g78_partner_absent", 0), ("g78_pressure2", 0),
                    ("g78_split", 0), ("i2_bench_swap", 0), ("i2_illusion_break", 0), ("i2_unbroken_switchout", 0)}

    @classmethod
    def setUpClass(cls):
        import collections
        from duoforge_live import lines as live_lines
        from duoforge_live.tracker import Tracker
        cls.pool = Reference.get().pool()
        cls.points, cls.stops, cls.raised = {}, collections.Counter(), set()  # (battle, player) -> [(k, parts)]
        for battle in cls.pool.battles:
            kind = record_kind(battle.name)
            for player in (0, 1):
                tracker, done, pid = Tracker(cls.pool.data, battle.spec["teams"][player]), 0, f"p{player + 1}"
                tracker.record_kind = kind
                out = cls.points[(battle.name, player)] = []
                try:
                    for lines in battle.streams[player]:
                        tracker.feed(lines)
                        if not (tracker.ready and tracker.epoch > done):
                            continue
                        done = tracker.epoch
                        k = done - 1
                        out.append((k, tracker.public_parts()))
                        step = battle.trace["steps"][k] if k < len(battle.trace["steps"]) else None
                        if step is not None and pid in step["input"]:
                            tracker.accepted(step["input"][pid])
                except live_lines.Stop as stop:
                    cls.stops[str(stop).split(" ")[0]] += 1
                except ValueError as err:
                    if not str(err).startswith("own PP of "):
                        raise
                    cls.raised.add((battle.name, player))

    def test_pool_records_equal_engine(self):
        import collections
        import re
        outcome, fields, where = collections.Counter(), collections.Counter(), {}
        for (name, player), points in self.points.items():
            for k, parts in points:
                result = record_diff(name, k, player, parts["record"])
                if result["engine_status"] != 0:
                    same = (parts["status"], parts["causes"], parts["record"].tobytes()) == (
                        result["engine_status"], result["engine_causes"], bytes(_layout.PUBLIC_STATE.itemsize))
                    key = "refused" if same else f"engine refuses ({result['engine_causes']}): {parts['reason']}"
                elif parts["status"] != 0 and parts["reason"] == "engine-refuses-record":
                    # the engine's public record of this point is status 0, but its check refuses a world with an infatuated occupant
                    # (duoforge_battle_from_view, lead's option B, tests/test_pool_g71.c): the tracker refuses with that verdict. Only
                    # records with an Attract source in the engine's record may take this key (infatuated_in_engine).
                    self.assertTrue(infatuated_in_engine(name, k, player), (name, k, player))
                    key = INFATUATED_REFUSAL
                elif parts["status"] != 0:
                    key = f"tracker refuses: {parts['reason']}"
                else:
                    key = "mismatch" if result["fields"] else "equal"
                    for field in result["fields"]:
                        fields[re.sub(r"\d+", "#", field)] += 1
                        where.setdefault(re.sub(r"\d+", "#", field), (name, k, player, field))
                outcome[key] += 1
                where.setdefault(key, (name, k, player))
        print(f"\npool record assembler: {dict(sorted(outcome.items()))}")
        print(f"pool tracker stops: {sum(self.stops.values())} streams, {dict(self.stops.most_common())}")
        self.assertFalse(fields, {field: (n, where[field]) for field, n in fields.most_common()})
        allowed = {"equal", "refused", INFATUATED_REFUSAL} | {f"tracker refuses: {reason}" for reason in self.TRACKER_REFUSALS}
        self.assertEqual(set(outcome) - allowed, set(), {key: where[key] for key in outcome})
        self.assertEqual(self.raised, self.OWN_PP_STOPS)
        self.assertEqual(dict(outcome), POOL_OUTCOME)
        self.assertEqual(dict(self.stops), POOL_STOPS)

    def test_tracker_of_a_pool_checkpoint_assembles_pool_records(self):
        # the live path's tables (data.for_config of a POOL checkpoint): the tracker's records are of the POOL context,
        # its size and fingerprint, and byte-identical to the engine's
        from duoforge import state_layout
        from duoforge_live.tracker import Tracker
        tables = data.for_config({"format": 2, "data": {"kind": "pool",
                                                        "fingerprint": self.pool.data.context().fingerprint().hex()}})
        battle = next(b for b in self.pool.battles if record_kind(b.name) is None)
        tracker = Tracker(tables, battle.spec["teams"][0])
        start, length = next((s, n) for name, s, n in state_layout.fields(pool=False) if name == "fingerprint")
        for lines in battle.streams[0]:
            tracker.feed(lines)
            if tracker.ready:
                break
        parts = tracker.public_parts()
        self.assertEqual((parts["status"], int(parts["record"]["state_size"])), (0, 1357))
        self.assertEqual(bytes(parts["record"]["state"][start:start + length]), tables.context().fingerprint())
        self.assertEqual(record_diff(battle.name, 0, 0, parts["record"])["fields"], [])

    def tracker_at(self, name, boundary):
        """A tracker of the pool battle `name` at its first decision point of `boundary` (either player's stream)."""
        from duoforge_live.tracker import Tracker
        battle = next(b for b in self.pool.battles if b.name == name)
        for player in (0, 1):
            tracker, done = Tracker(self.pool.data, battle.spec["teams"][player]), 0
            tracker.record_kind = record_kind(name)
            for lines in battle.streams[player]:
                tracker.feed(lines)
                if not (tracker.ready and tracker.epoch > done):
                    continue
                done = tracker.epoch
                if tracker.boundary() == boundary and tracker._turn > 1:
                    return tracker
                step = battle.trace["steps"][done - 1] if done - 1 < len(battle.trace["steps"]) else None
                if step is not None and f"p{player + 1}" in step["input"]:
                    tracker.accepted(step["input"][f"p{player + 1}"])
        raise AssertionError(f"{name}: no decision point of boundary {boundary}")

    def assert_refusal(self, tracker, reason):
        from duoforge_live import record
        with self.assertRaises(record.Refusal) as caught:
            record._record(tracker, tracker.observation())
        self.assertEqual(caught.exception.reason, reason)

    def test_the_named_refusals_the_corpus_never_reaches(self):
        # the tracker's own refusals of TRACKER_REFUSALS that no committed battle reaches, each from a real decision
        # point whose fold is broken in exactly that one way
        from duoforge_live import record
        PIVOT, TURN = C["DUOFORGE_BOUNDARY_PIVOT"], C["DUOFORGE_BOUNDARY_TURN"]
        name = "g5_uturn_a"
        t = self.tracker_at(name, PIVOT)
        record._record(t, t.observation())  # the point itself assembles
        t._requested = lambda side, boundary: (False, 0)  # a PIVOT whose asked side the lines did not show
        self.assert_refusal(t, "pivot-switch-reason-unknown")
        t = self.tracker_at(name, PIVOT)
        side = next(side for side in (0, 1) if t._requested(side, PIVOT)[0])
        k = next(k for k in (0, 1) if t._requested(side, PIVOT)[1] >> k & 1)
        t._positions[side][k].flag = 0  # asked to switch for a reason no line showed
        self.assert_refusal(t, "pivot-switch-reason-unknown")
        t = self.tracker_at(name, PIVOT)
        own = next(p for p in t._positions[t.side] if p.occupant != record.OCCUPANT_NONE and not p.fainted)
        own.move_queued, t._accepted_commands = True, None  # an own move left whose command the accepted choice lacks
        self.assert_refusal(t, "own-command-unknown")
        t = self.tracker_at(name, TURN)
        record._record(t, t.observation())
        p = next(p for p in t._positions[t.side] if p.occupant != record.OCCUPANT_NONE)
        p.result_now = None  # the library could not classify the action's events
        self.assert_refusal(t, "move-result-not-determined")
        t = self.tracker_at(name, TURN)
        p = next(p for p in t._positions[t.side] if p.occupant != record.OCCUPANT_NONE)
        p.last_slot = None  # the move of its last line is on no slot of its sheet
        self.assert_refusal(t, "last-move-not-on-sheet")

    def test_move_result_maps_the_librarys_refusal_to_none(self):
        # view.move_result: E_UNSUPPORTED (a handler the classifier does not map: Substitute) is None, a class is its value
        from duoforge import view
        from duoforge._state_layout import VALUES
        from duoforge_live.data import trace_to_c
        EV, moves = trace_to_c.EV, self.pool.data.tables["MOVE"]
        ctx = self.pool.data.context()
        self.assertIsNone(view.move_result(ctx, 0, [trace_to_c.ev_tuple(EV["MOVE"], 0, 0, 0, moves["SUBSTITUTE"])]))
        cant = trace_to_c.ev_tuple(EV["CANT"], 1, cause=trace_to_c.CAUSE["PARALYSIS"])
        self.assertEqual(view.move_result(ctx, 1, [cant]), VALUES["DFI_MOVE_RESULT_FALSE"])

    def test_engine_gives_every_pool_record_back(self):
        import duoforge
        from duoforge import state_layout
        from duoforge_live import record
        contexts = {kind: duoforge.Context(data_kind=C["DUOFORGE_DATA_KIND_POOL"] if kind is None else kind)
                    for kind in (None, C["DUOFORGE_DATA_KIND_POOL_DEV"])}
        party = next(s for f, s, _ in state_layout.fields(pool=True) if f == "tail.field.party_order")
        try:
            checked = refused = 0
            for (name, player), points in self.points.items():
                ctx = contexts[record_kind(name)]
                for k, parts in points:
                    if parts["status"] != 0:
                        continue
                    rec = parts["record"]
                    self.assertEqual(record.check(ctx, rec), 0, (name, k, player))
                    checked += 1
                    if int(rec["boundary"]) == C["DUOFORGE_BOUNDARY_TURN"] and refused < 50:
                        # a POOL tail mask filled: the foe's first bench entry of party_order (hidden) named
                        bad = rec.copy()
                        start = party + 3 * (1 - player)
                        value = int.from_bytes(bytes(bad["state"][start:start + 3]), "little")
                        value = (value & ~(7 << 6)) | (1 << 6)  # entry 2: roster index 0 + 1 instead of hidden
                        bad["state"][start:start + 3] = list(value.to_bytes(3, "little"))
                        self.assertEqual(duoforge.status_name(record.check(ctx, bad)), "DUOFORGE_E_MALFORMED",
                                         (name, k, player))
                        refused += 1
            self.assertEqual((checked, refused), (POOL_OUTCOME["equal"], 50))
        finally:
            for ctx in contexts.values():
                ctx.close()


def state_layout_fields():
    from duoforge import state_layout
    return state_layout.fields(pool=False)


class TrackerTest(unittest.TestCase):
    """Test 1 of the spec: the tracker's observation is DuoForge's, byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.ref = Reference.get()

    def _updated_request_pair(self):
        from duoforge_live.tracker import Tracker

        tracker = Tracker(self.ref.data, self.ref.battles[0].spec["teams"][0])
        tracker.request = {"rqid": 1, "side": {"id": "p1", "pokemon": []}, "active": [{}, {}]}
        request = json.loads(json.dumps(tracker.request))
        request.update(update=True, rqid=2)
        return tracker, request

    def test_update_requires_a_current_request(self):
        tracker, request = self._updated_request_pair()
        tracker.request = None
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def test_update_requires_active_on_current_request(self):
        tracker, request = self._updated_request_pair()
        tracker.request.pop("active")
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def test_update_requires_active_on_new_request(self):
        tracker, request = self._updated_request_pair()
        request.pop("active")
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def test_update_requires_no_intervening_battle_lines(self):
        tracker, request = self._updated_request_pair()
        tracker._lines.append("|player|p2|Opponent|0|1500")
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def test_update_requires_the_same_active_count(self):
        tracker, request = self._updated_request_pair()
        request["active"].pop()
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def test_update_requires_the_same_side(self):
        tracker, request = self._updated_request_pair()
        request["side"]["id"] = "p2"
        with self.assertRaisesRegex(ValueError, "updated request"):
            tracker._on_updated_request(request)

    def assertSameView(self, battle, player, points):
        expected = sum(1 for _ in battle.points(player))
        self.assertEqual([p[0] for p in points], list(range(expected)), (battle.name, player))
        for k, obs, dom, _, ext in points:
            theirs, their_dom = battle.views[(k, player)]
            where = f"{battle.name} k={k} viewer={player}"
            diff = differences(obs, theirs)
            self.assertFalse(diff, f"{where}: " + "; ".join(diff[:12]))
            self.assertEqual(ext.tobytes(), battle.exts[(k, player)], where)  # closure kinds: both all zero
            self.assertEqual((int(dom["epoch"]), int(dom["kind"])), (int(their_dom["epoch"]), int(their_dom["kind"])),
                             where)
            if int(dom["kind"]) == TEAM:
                self.assertEqual(dom.tobytes(), their_dom.tobytes(), where)
            for s in (0, 1) if int(dom["kind"]) == SLOTS else ():
                ours = {command(dom["slots"][s][i]) for i in range(int(dom["slot_count"][s]))}
                theirs = {command(their_dom["slots"][s][i]) for i in range(int(their_dom["slot_count"][s]))}
                self.assertEqual(ours, theirs, (where, s))

    def test_tracker_equals_duoforge(self):
        for battle in self.ref.battles:
            for player in (0, 1):
                self.assertSameView(battle, player, run_tracker(battle, player))

    def test_foe_nicknames_change_nothing(self):
        for battle in self.ref.battles:
            for player in (0, 1):
                foe = 2 - player  # the foe's protocol side number
                names = sorted(battle.roster_names[1 - player], key=len, reverse=True)
                nick = {name: f"Nick{i}" for i, name in enumerate(names)}

                def rename(line):
                    for name in names:
                        for who in (f"p{foe}a: ", f"p{foe}b: ", f"p{foe}: "):
                            line = line.replace(who + name + "|", who + nick[name] + "|")
                            if line.endswith(who + name):
                                line = line[:-len(name)] + nick[name]
                    return line
                stream = [[rename(line) for line in lines] for lines in battle.streams[player]]
                self.assertNotEqual(stream, battle.streams[player], battle.name)
                self.assertSameView(battle, player, run_tracker(battle, player, stream))

    def test_room_lines_do_not_complete_a_decision(self):
        room = ["|c|☆someone|hello", "|j|☆watcher", "||watcher is ready for game 2.", "|inactive|Time left",
                "|player|p2|watcher||"]
        for battle in self.ref.battles:
            for player in (0, 1):
                stream = []
                for lines in battle.streams[player]:
                    stream.append(lines)
                    if any(line.startswith("|request|") for line in lines):
                        stream.append(room)
                self.assertSameView(battle, player, run_tracker(battle, player, [room] + stream))

    def test_repeated_request_is_one_decision(self):
        for battle in self.ref.battles:
            for player in (0, 1):
                stream = []
                for lines in battle.streams[player]:
                    stream.append(lines)
                    if any(line.startswith("|request|") for line in lines):
                        stream.append(lines)  # a reconnect sends the request again, same rqid
                self.assertSameView(battle, player, run_tracker(battle, player, stream))

    def test_unknown_line_raises(self):
        battle = self.ref.battles[0]
        stream = [list(lines) for lines in battle.streams[0]]
        last = max(i for i, lines in enumerate(stream) if any(line.startswith("|turn|") for line in lines))
        stream[last].insert(0, "|-futureline|p1a: Someone")
        with self.assertRaisesRegex(ValueError, "futureline"):  # the parser's ConversionError, as a ValueError
            run_tracker(battle, 0, stream)

    def test_forfeit_message_is_room_text(self):
        # A forfeit or a timer loss: the server adds "|-message|<name> forfeited." before |win| (room-battle.ts).
        for battle in self.ref.battles[:10]:
            for player in (0, 1):
                stream = [list(lines) for lines in battle.streams[player]]
                for lines in stream:
                    for i, line in enumerate(lines):
                        if line.startswith("|turn|"):
                            lines.insert(i, "|-message|Somebody has 30 seconds left.")
                            break
                self.assertSameView(battle, player, run_tracker(battle, player, stream))
        from duoforge_live.tracker import Tracker
        tracker = Tracker(self.ref.data, self.ref.battles[0].spec["teams"][0])
        tracker.feed(["|-message|chris forfeited.", "|win|p1"])  # before any sheet: no error
        self.assertTrue(tracker.ended)

    def test_session_lines_raise(self):
        # A reconnect replays the whole log after |init|, a choice already sent shows |sentchoice|, an updated
        # request (update: true) after battle lines (it updates no current request) or a request without rqid
        # cannot be placed, and the end of the session ends the battle: each raises instead of folding something
        # wrong.
        battle = self.ref.battles[0]
        stream = [list(lines) for lines in battle.streams[0]]
        last = max(i for i, lines in enumerate(stream) if any(line.startswith("|turn|") for line in lines))
        for bad in (["|init|battle"], ["|sentchoice|move 1"], ["|bigerror|The simulator process crashed."],
                    ["|deinit"], ["|noinit|nonexistent|x"], ["|expire|x"]):
            with self.assertRaises(ValueError, msg=bad):
                run_tracker(battle, 0, stream[:last] + [bad] + stream[last:])
        request = next(i for i in range(last, len(stream)) if any(l.startswith("|request|") for l in stream[i]))
        for change in ({"update": True}, {"rqid": None}):
            lines = []
            for line in stream[request]:
                if line.startswith("|request|"):
                    r = json.loads(line[len("|request|"):])
                    r.update(change)
                    if r["rqid"] is None:
                        del r["rqid"]
                    line = "|request|" + json.dumps(r)
                lines.append(line)
            with self.assertRaises(ValueError, msg=change):
                run_tracker(battle, 0, stream[:request] + [lines] + stream[request + 1:])

    def test_updated_request_is_a_new_epoch_of_the_same_decision_point(self):
        # Showdown refuses a switch of a hidden-trapped last active with "[Unavailable choice]" and sends the move
        # request again under a new rqid, the slot now trapped (sim/side.ts:527-534, 984-1000). The tracker takes it
        # as a new request epoch of the same decision point: the observation stays but for its epoch, and the
        # options follow the update.
        from duoforge_live.tracker import Tracker
        battle = self.ref.battles[0]
        tracker, done = Tracker(self.ref.data, battle.spec["teams"][0]), 0
        for lines in battle.streams[0]:
            tracker.feed(lines)
            if tracker.ready and tracker.epoch > done:
                done = tracker.epoch
                if "active" in tracker.request:
                    break
                step = battle.trace["steps"][done - 1]
                if "p1" in step["input"]:
                    tracker.accepted(step["input"]["p1"])
        self.assertIn("active", tracker.request)
        before, (_, lists_before) = tracker.observation().copy(), tracker.domain()
        self.assertIn(options.SWITCH, [o.kind for o in lists_before[1]])
        update = json.loads(json.dumps(tracker.request))
        update["active"][1]["trapped"] = True
        update.update(update=True, rqid=update["rqid"] + 100)
        tracker.feed(["|request|" + json.dumps(update)])
        self.assertTrue(tracker.ready)
        dom, lists = tracker.domain()
        after = tracker.observation()
        self.assertEqual((int(after["epoch"]), int(dom["epoch"])), (int(before["epoch"]) + 1,) * 2)
        before["epoch"] = after["epoch"]
        self.assertFalse(differences(after, before))
        self.assertEqual(lists[0], lists_before[0])
        self.assertEqual(lists[1], [o for o in lists_before[1] if o.kind != options.SWITCH])


if __name__ == "__main__":
    unittest.main()
