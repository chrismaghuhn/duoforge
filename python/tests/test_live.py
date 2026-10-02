"""duoforge.python.live: the Showdown live adapter against the pinned Showdown.

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR)
and the runner (DUOFORGE_DIFF_RUNNER); CTest registers it only with all of
them and reports it skipped otherwise. Spec section 8, tests 1 (the options), 2 and 5.

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


if __name__ == "__main__":
    unittest.main()
