"""The reference of the replay tests, built once per process: every committed battle
(closure, Team C, pool) as the pinned Showdown's spectator log (ps_client.js
--every --spectator), DuoForge's views of both players after every step
(duoforge_diff_runner --dump-views over the three record files), and the
committed traces and specs.

Decision point k of the battle is the state after k steps; its views are
views[(k, viewer)] = (OBSERVATION, FACTORED_DOMAIN).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

from duoforge import _layout
from duoforge_live import data, teams
from duoforge_live.data import trace_to_c

STATS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")


class Battle:
    def __init__(self, name, lines, views):
        self.name = name
        self.lines = lines  # the spectator log, one protocol line per entry
        self.views = views
        self.spec, self.trace = trace_to_c.load_battle(str(data.ROOT), name)
        self.sets = [teams._paste(self.spec["teams"][s]) for s in (0, 1)]  # the true sets: stat points, nature


class Reference:
    _built = None

    @classmethod
    def get(cls):
        if cls._built is None:
            cls._built = cls()
        return cls._built

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="duoforge_replay_")
        atexit.register(shutil.rmtree, self.tmp, True)
        root = str(data.ROOT)
        subprocess.run([sys.executable, str(data.ROOT / "tools" / "reference" / "conformance_records.py"), "--all",
                        root, "--out", self.tmp], check=True, timeout=600)
        views = {}
        for records in ("closure", "team_c", "pool"):
            path = os.path.join(self.tmp, f"{records}.records")
            views_path = os.path.join(self.tmp, f"{records}.views")
            out = subprocess.run([os.environ["DUOFORGE_DIFF_RUNNER"], "--dump-views", views_path, path],
                                 capture_output=True, text=True, timeout=600)
            results = [line.split(" ") for line in out.stdout.splitlines() if line.startswith("R ")]
            if out.returncode != 0 or not results or any(r[2] != "PASS" for r in results):
                raise AssertionError(f"the runner on {records}: {out.returncode} {out.stderr} {out.stdout[-2000:]}")
            with open(views_path, encoding="ascii") as f:
                for line in f:
                    _, name, k, viewer, obs, dom = line.split()
                    views.setdefault(name, {})[(int(k), int(viewer))] = (
                        np.frombuffer(bytes.fromhex(obs), dtype=_layout.OBSERVATION)[0],
                        np.frombuffer(bytes.fromhex(dom), dtype=_layout.FACTORED_DOMAIN)[0])
        script = data.ROOT / "tools" / "reference" / "ps_client.js"
        out = subprocess.run([os.environ["DUOFORGE_NODE"], str(script), os.environ["DUOFORGE_PS_REFERENCE_DIR"], root,
                              "--every", "--spectator"], capture_output=True, text=True, encoding="utf-8",
                             timeout=600)
        if out.returncode != 0:
            raise AssertionError(f"ps_client.js --every --spectator: {out.stderr}")
        logs = {}
        for line in out.stdout.splitlines():
            m = json.loads(line)
            logs.setdefault(m["battle"], []).extend(m["lines"])
        if sorted(logs) != sorted(views):
            raise AssertionError(f"logs and views name other battles: {sorted(set(logs) ^ set(views))}")
        self.data = data.load(kind="pool")
        self.battles = [Battle(name, logs[name], views[name]) for name in sorted(views)]


def true_stats_of(battle, side, source):
    """stats_of for the spectator tracker with the battle's true team as the prior: (stats, stat points) of member m
    in forme `forme` (a forme id of the pool tables)."""
    names = {v: k for k, v in Reference.get().data.tables["FORME"].items() if k != "COUNT"}

    def stats_of(m, forme):
        s = battle.sets[side][m]
        sp = list(s["evs"])
        return source.stats(names[forme].lower(), s["nature"], sp), sp
    return stats_of
