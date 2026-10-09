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
    def __init__(self, name, views, streams):
        self.name = name
        self.spec, self.trace = trace_to_c.load_battle(str(data.ROOT), name)
        self.views = views
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


class Reference:
    """Built once for the module: records, views and client streams of every committed closure battle."""
    _built = None

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
        views_path = os.path.join(self.tmp, "views.txt")
        out = subprocess.run([os.environ["DUOFORGE_DIFF_RUNNER"], "--dump-views", views_path,
                              os.path.join(self.tmp, "closure.records")], capture_output=True, text=True, timeout=600)
        results = [line.split(" ") for line in out.stdout.splitlines() if line.startswith("R ")]
        if out.returncode != 0 or not results or any(r[2] != "PASS" for r in results):
            raise AssertionError(f"the runner: {out.returncode} {out.stderr} {out.stdout[-2000:]}")
        views = {}
        with open(views_path, encoding="ascii") as f:
            for line in f:
                _, name, k, viewer, obs, dom = line.split()
                views.setdefault(name, {})[(int(k), int(viewer))] = (
                    np.frombuffer(bytes.fromhex(obs), dtype=_layout.OBSERVATION)[0],
                    np.frombuffer(bytes.fromhex(dom), dtype=_layout.FACTORED_DOMAIN)[0])
        streams = {}
        for line in node_tool(root, "--all").splitlines():
            m = json.loads(line)
            streams.setdefault(m["battle"], ([], []))[int(m["to"][1]) - 1].append(m["lines"])
        if sorted(streams) != sorted(views):
            raise AssertionError("the client streams and the views name other battles")
        self.battles = [Battle(name, views[name], streams[name]) for name in sorted(views)]
        self.data = data.load()


def command(c):
    return tuple(int(c[f]) for f in COMMAND)


class PackTest(unittest.TestCase):
    def test_pack_equals_showdown(self):
        for name, file in teams.FILES.items():
            path = data.ROOT / "tests" / "reference" / "teams" / file
            self.assertEqual(teams.pack(teams.text(name)), node_tool("--pack", str(path)).rstrip("\n"), name)


class ClearAllBoostsTest(unittest.TestCase):
    """Step G62 (decision 0031): Haze's CLEAR_ALL_BOOSTS returns the stages of every standing active Pokemon to
    neutral (data/moves.ts haze onHitField: getAllActive, sim/pokemon.ts clearBoosts); an empty or fainted position
    keeps what it holds."""

    def test_every_standing_active_position_returns_to_neutral(self):
        from types import SimpleNamespace
        from duoforge_live import tracker
        t = tracker.Tracker.__new__(tracker.Tracker)
        t.side, t._spectator = 0, False
        raised = [8, 4, 6, 6, 6, 9, 6]

        def position(occupant, fainted=False):
            return SimpleNamespace(occupant=occupant, fainted=fainted, stages=list(raised))

        t._positions = [[position(0), position(1)], [position(2, fainted=True), position(tracker.ROSTER_NONE)]]
        t._event(trace_to_c.ev_tuple(trace_to_c.EV["CLEAR_ALL_BOOSTS"]))
        self.assertEqual([p.stages for p in t._positions[0]], [[tracker.STAGE_NEUTRAL] * 7] * 2)
        self.assertEqual([p.stages for p in t._positions[1]], [raised, raised])


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
    """[(k, tracker observation, tracker domain, lists)] at every decision point of `player`, feeding the
    stream message by message and the recorded own choices as accepted."""
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
            out.append((k, tracker.observation(), dom, lists))
            step = battle.trace["steps"][k] if k < len(battle.trace["steps"]) else None
            if step is not None and pid in step["input"]:
                tracker.accepted(step["input"][pid])
    return out


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
        for k, obs, dom, _ in points:
            theirs, their_dom = battle.views[(k, player)]
            where = f"{battle.name} k={k} viewer={player}"
            diff = differences(obs, theirs)
            self.assertFalse(diff, f"{where}: " + "; ".join(diff[:12]))
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
