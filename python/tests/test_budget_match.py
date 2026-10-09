"""The continuation control's budget matching (stage 3 P1, train --update-gpu-share match): before every update a
device is chosen from the ledger so that both of the pilot's totals are matched within 5 %, never pushing an axis
above 1.05 with the expected cost of the next step (JIT included), and stopping as incomplete when no device fits.

The costs are the per-step ledger deltas measured on the AWS L4 machine (g6.4xlarge) in the P1 control run of
2026-10-09 (control/match.json and the run's log.jsonl): the first update of a process includes its JIT."""
import json
import math
import unittest

from duoforge_learn import budget_match as bm

PILOT = (5202.449553, 59.90232400300056)
# (cpu core-seconds, gpu-seconds) from one decision point to the next: the next collection plus the update.
L4 = {"cpu": {"first": (153.7, 0.0), "warm": (133.4, 0.0)},
      "default": {"first": (108.2, 13.2), "warm": (28.1, 3.65)}}
STARTUP = (25.0, 0.0)  # a resumed process's start-up before its first update


def simulate(targets=PILOT, restarts=(), costs=L4, start=(0.0, 0.0), limit=500):
    """The controller against a cost table: (fractions, stop reason, devices). restarts: the step indices after which
    the process restarts (a Spot interruption), paying start-up and a first update per device again."""
    c, g = start
    book, devices = bm.Costs(), []
    while len(devices) < limit:
        device, reason = bm.choose((c, g), targets, book)
        if device is None:
            return (c / targets[0], g / targets[1]), reason, devices
        kind = "warm" if device in book.used else "first"
        dc, dg = costs[device][kind]
        book.observe(device, dc, dg)
        c, g = c + dc, g + dg
        devices.append(device)
        if len(devices) in restarts:
            book.new_process()
            c, g = c + STARTUP[0], g + STARTUP[1]
    raise AssertionError("no stop")


class ChooseTest(unittest.TestCase):
    def assert_matched(self, fractions):
        for f in fractions:
            self.assertGreaterEqual(f, bm.FLOOR)
            self.assertLessEqual(f, bm.CEILING)

    def test_fresh_run_on_the_l4_costs_matches_both_axes(self):
        fractions, reason, devices = simulate()
        self.assertEqual(reason, "matched")
        self.assert_matched(fractions)
        self.assertIn("default", devices)
        self.assertGreater(devices.count("cpu"), devices.count("default"))

    def test_restarts_pay_their_jit_and_still_match(self):
        for restarts in ((5,), (20,), (10, 25), (30,)):
            fractions, reason, _ = simulate(restarts=restarts)
            self.assertEqual(reason, "matched", restarts)
            self.assert_matched(fractions)

    def test_never_above_the_ceiling_after_any_step(self):
        c, g, book = 0.0, 0.0, bm.Costs()
        while True:
            device, _ = bm.choose((c, g), PILOT, book)
            if device is None:
                break
            kind = "warm" if device in book.used else "first"
            dc, dg = L4[device][kind]
            book.observe(device, dc, dg)
            c, g = c + dc, g + dg
            self.assertLessEqual(c / PILOT[0], bm.CEILING)
            self.assertLessEqual(g / PILOT[1], bm.CEILING)

    def test_no_device_fits_is_incomplete(self):
        book = bm.Costs()
        book.observe("cpu", 200.0, 0.0)
        book.observe("cpu", 200.0, 0.0)
        book.observe("default", 30.0, 1.5)
        book.observe("default", 30.0, 1.5)
        # cpu 0.90, gpu 0.94: a CPU step reaches 1.10 of the CPU axis, a GPU step 1.09 of the GPU axis.
        device, reason = bm.choose((900.0, 9.4), (1000.0, 10.0), book)
        self.assertEqual((device, reason), (None, "incomplete"))

    def test_an_unmeasured_jit_is_not_risked_near_the_end(self):
        book = bm.Costs()
        book.observe("cpu", 100.0, 0.0)
        book.observe("cpu", 100.0, 0.0)
        # GPU axis lagging at 0.85, but no GPU update measured yet: its cost is assumed to be a quarter of the axis.
        device, _ = bm.choose((900.0, 8.5), (1000.0, 10.0), book)
        self.assertEqual(device, "cpu")

    def test_matched_at_the_floor(self):
        self.assertEqual(bm.choose((950.0, 9.5), (1000.0, 10.0), bm.Costs()), (None, "matched"))

    def test_lagging_axis_first(self):
        book = bm.Costs()
        for device, cost in (("cpu", (10.0, 0.0)), ("cpu", (10.0, 0.0)), ("default", (2.0, 0.1)),
                             ("default", (2.0, 0.1))):
            book.observe(device, *cost)
        self.assertEqual(bm.choose((300.0, 2.0), (1000.0, 10.0), book)[0], "default")
        self.assertEqual(bm.choose((200.0, 3.0), (1000.0, 10.0), book)[0], "cpu")

    def test_costs_from_the_run_log(self):
        lines = [{"init": "params-49333.npz"},
                 {"update": 1, "update_device": "cpu", "ledger": {"cpu_core_seconds": 150.0, "gpu_seconds": 0.0}},
                 {"update": 2, "update_device": "cpu", "ledger": {"cpu_core_seconds": 280.0, "gpu_seconds": 0.0}},
                 {"update": 3, "update_device": "default",
                  "ledger": {"cpu_core_seconds": 390.0, "gpu_seconds": 13.0}},
                 {"resume": {}, "at_update": 3},
                 {"update": 4, "update_device": "default",
                  "ledger": {"cpu_core_seconds": 520.0, "gpu_seconds": 27.0}},
                 {"update": 5, "update_device": "default",
                  "ledger": {"cpu_core_seconds": 548.0, "gpu_seconds": 30.5}}]
        book = bm.Costs.from_log(json.dumps(r) for r in lines)
        self.assertEqual(book.used, set())  # a new process: every device's next update is a first one again
        self.assertEqual(book.estimate("cpu"), (150.0, 0.0))
        self.assertEqual(book.estimate("default"), (130.0, 14.0))
        book.observe("default", 120.0, 13.5)
        self.assertEqual(book.estimate("default"), (28.0, 3.5))


class FixedShareTest(unittest.TestCase):
    def test_the_old_fixed_share_misses_the_cpu_axis_on_the_l4_costs(self):
        """The 2026-10-09 run: calibration to update 12, then p1_match's q = 0.210187 in a resumed process whose first
        GPU update paid its JIT: the GPU stop came at 80 % of the CPU axis (control 4142 / 62.9)."""
        from duoforge_learn.train import _on_default
        q = 0.21018705958739733
        c, g, update, used = 1074.1127350000002, 31.44006399999944, 12, set()
        while c < PILOT[0] and g < PILOT[1]:
            device = "default" if _on_default(update, q) else "cpu"
            dc, dg = L4[device]["warm" if device in used else "first"]
            used.add(device)
            c, g, update = c + dc, g + dg, update + 1
        self.assertGreater(abs(c / PILOT[0] - 1), 0.05)
        self.assertTrue(math.isclose(c / PILOT[0], 0.8, abs_tol=0.03), c / PILOT[0])


if __name__ == "__main__":
    unittest.main()
