#!/usr/bin/env python3
"""duoforge.reference.dump_views: the runner's --dump-views (tools/difftest).

usage: python tools/reference/test_dump_views.py <duoforge_diff_runner> <closure.records>

Runs with DUOFORGE_PYTHON and DUOFORGE_LIBRARY (the first view is compared
with the Python package). Checks, over every committed closure battle:
- every battle passes and has 2 * (steps + 1) view lines, decision index k
  ascending and viewer 0 before 1, each with the observation's epoch k + 1
  and player equal to the viewer, and sizes of 736 and 652 bytes;
- the first views of m5_real_ab_1 (Team A against Team B) equal what the
  public API gives for the battle's setup, built from its record's member
  lines (a Batch's query_factored());
- the flag changes nothing on stdout or in the exit status;
- a file that cannot be written is an explicit failure.
"""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

RUNNER = RECORDS = None


def run(args):
    return subprocess.run([RUNNER] + args, capture_output=True, timeout=600)


def read_views(path):
    """{(battle, k, viewer): (observation bytes, domain bytes)} and the order of the keys."""
    views, order = {}, []
    with open(path, encoding="ascii") as f:
        for line in f:
            tag, name, k, viewer, obs, dom = line.rstrip("\n").split(" ")
            if tag != "V":
                raise AssertionError("not a view line: %r" % line[:40])
            key = (name, int(k), int(viewer))
            views[key] = (bytes.fromhex(obs), bytes.fromhex(dom))
            order.append(key)
    return views, order


def record_members(path, name):
    """The member rows (M lines) of battle `name` in a records file, per side."""
    sides = [[], []]
    inside = False
    with open(path, encoding="ascii") as f:
        for line in f:
            parts = line.split()
            if parts[0] == "B":
                inside = parts[1] == name
            elif inside and parts[0] == "M":
                sides[int(parts[1])].append([int(x) for x in parts[3:]])
    if not sides[0]:
        raise AssertionError("no battle %s in %s" % (name, path))
    return sides


class DumpViewsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.views_path = os.path.join(cls.tmp.name, "views.txt")
        cls.with_flag = run(["--dump-views", cls.views_path, RECORDS])
        cls.without_flag = run([RECORDS])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def results(self, out):
        """(name, verdict, steps) of every R line."""
        rows = []
        for line in out.decode("ascii").splitlines():
            if line.startswith("R "):
                parts = line.split(" ")
                rows.append((parts[1], parts[2], int(parts[5])))
        return rows

    def test_views_of_every_battle(self):
        from duoforge import _layout
        self.assertEqual(self.with_flag.returncode, 0, self.with_flag.stderr.decode())
        rows = self.results(self.with_flag.stdout)
        self.assertGreater(len(rows), 80)
        views, order = read_views(self.views_path)
        expected = []
        for name, verdict, steps in rows:
            self.assertEqual(verdict, "PASS", name)
            expected += [(name, k, v) for k in range(steps + 1) for v in (0, 1)]
        self.assertEqual(order, expected)
        steps = {name: s for name, _, s in rows}
        slots = _layout.CONSTANTS["DUOFORGE_CHOICE_SLOTS"]
        terminal = _layout.CONSTANTS["DUOFORGE_BOUNDARY_TERMINAL"]
        for (name, k, viewer), (obs, dom) in views.items():
            self.assertEqual((len(obs), len(dom)), (736, 652), name)
            o = np.frombuffer(obs, dtype=_layout.OBSERVATION)[0]
            d = np.frombuffer(dom, dtype=_layout.FACTORED_DOMAIN)[0]
            where = (name, k, viewer)
            self.assertEqual((int(o["epoch"]), int(o["player"]), int(d["epoch"])), (k + 1, viewer, k + 1), where)
            # The domain is the viewer's own: a domain exactly when the viewer is asked, and at a SLOTS
            # boundary one non-empty slot list per requested slot (a single NONE entry otherwise).
            self.assertEqual(int(d["kind"]) != 0, int(o["requested"]) != 0, where)
            if int(d["kind"]) == slots:
                for s in (0, 1):
                    asked = (int(o["slot_mask"]) >> s) & 1
                    self.assertTrue(asked or (int(d["slot_count"][s]) == 1 and int(d["slots"][s][0]["kind"]) == 0),
                                    where)
            # Only the last view of a battle may be TERMINAL.
            if int(o["boundary_kind"]) == terminal:
                self.assertEqual(k, steps[name], where)

    def test_first_view_is_the_public_api(self):
        import duoforge
        from duoforge import _layout
        views, _ = read_views(self.views_path)
        setups = np.zeros(1, dtype=_layout.SETUP)
        for side, members in enumerate(record_members(RECORDS, "m5_real_ab_1")):
            setups[0]["sides"][side]["member_count"] = len(members)
            for m, row in enumerate(members):  # df_conf_member: species gender nature sp[6] ability item count moves[4]
                dst = setups[0]["sides"][side]["members"][m]
                dst["species_id"], dst["gender"], dst["nature"] = row[0], row[1], row[2]
                dst["stat_points"] = row[3:9]
                dst["ability"], dst["item"], dst["move_count"] = row[9], row[10], row[11]
                dst["moves"]["move_id"][:row[11]] = row[12:12 + row[11]]
        context = duoforge.Context()
        batch = duoforge.Batch(context, setups, 1, 1)
        try:
            batch.query_factored()
            for viewer in (0, 1):
                obs, dom = views[("m5_real_ab_1", 0, viewer)]
                self.assertEqual(obs, batch.observations[0, viewer].tobytes(), viewer)
                self.assertEqual(dom, batch.domains[0, viewer].tobytes(), viewer)
        finally:
            batch.close()
            context.close()

    def test_flag_changes_nothing_else(self):
        self.assertEqual(self.with_flag.returncode, self.without_flag.returncode)
        self.assertEqual(self.with_flag.stdout, self.without_flag.stdout)

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs /dev/full (Linux)")
    def test_full_disk_fails(self):
        out = run(["--dump-views", "/dev/full", RECORDS])
        self.assertEqual(out.returncode, 1)
        self.assertIn(b"cannot write /dev/full", out.stderr)

    def test_unwritable_file_fails(self):
        out = run(["--dump-views", self.tmp.name, RECORDS])  # a directory
        self.assertEqual(out.returncode, 1)
        self.assertIn(self.tmp.name.encode(), out.stderr)
        self.assertNotIn(b"R ", out.stdout)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__.split("\n\n")[1] + "\n")
        sys.exit(2)
    RUNNER, RECORDS = sys.argv[1], sys.argv[2]
    unittest.main(argv=sys.argv[:1], verbosity=2)
