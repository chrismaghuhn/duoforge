"""duoforge.python.step_events: a step's events on a copy of a batch environment (privileged.step_events, M12 bundle 7).

The test positions (data/positions) prove their claims over reseeded copies of a battle and count what happened
(faints, critical hits, a move that still ran): duoforge_battle_step_events on a clone of the environment's battle,
with the bundle the batch builds from a factored choice. The environment itself is never changed.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout, privileged

C = _layout.CONSTANTS


def _start(test, seed=42):
    """A batch at its first TURN; the test closes its context and batch."""
    ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
    test.addCleanup(ctx.close)
    b = duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, seed)
    test.addCleanup(b.close)
    b.query_factored()
    choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
    choices["picks"][0, :, :4] = (0, 1, 2, 3)
    b.step_factored(choices)
    b.query_factored()
    return b


def _attack(b):
    """Both sides' first allowed pair whose two slots use a move (the leads attack)."""
    choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
    for side in (0, 1):
        d = b.domains[0, side]
        moves = [[i for i in range(int(d["slot_count"][s])) if int(d["slots"][s, i]["kind"]) == C["DUOFORGE_SLOT_MOVE"]
                  and int(d["slots"][s, i]["move_slot"]) == 0] for s in (0, 1)]
        i, k = next((i, k) for i in moves[0] for k in moves[1] if (int(d["allowed"][i]) >> k) & 1)
        choices["slot"][0, side] = (i, k)
    return choices


class StepEvents(unittest.TestCase):
    def test_a_copy_steps_as_the_batch_does_and_the_batch_is_unchanged(self):
        a, b = _start(self), _start(self)
        choices = _attack(a)
        before = bytes(b.digest(0))
        out = privileged.step_events(b, 0, choices[0], rng=None)  # the batch's own stream
        self.assertEqual(out["status"], 0)
        self.assertEqual(bytes(b.digest(0)), before)  # the environment is untouched
        a.step_factored(choices)
        self.assertEqual(bytes(out["digest"]), bytes(a.digest(0)))  # the copy stepped as the batch steps
        self.assertEqual(int(out["result"]["boundary_kind"]), int(a.results[0]["boundary_kind"]))
        self.assertEqual(out["battle_result"], a.result(0))
        for p in (0, 1):
            events = out["events"][p]
            self.assertEqual(events.dtype, _layout.EVENT)
            moved = {int(e["position"]) for e in events if int(e["kind"]) == C["DUOFORGE_EVENT_MOVE"]}
            self.assertTrue(moved, f"player {p} sees no move")

    def test_reseeded_copies_roll_apart_and_show_critical_hits(self):
        b = _start(self)
        choices = _attack(b)
        digests, crits = set(), 0
        for k in range(64):
            out = privileged.step_events(b, 0, choices[0], rng=(0x2026101100000800 + k, 0x2026101100000900 + k))
            self.assertEqual(out["status"], 0)
            digests.add(bytes(out["digest"]))
            crits += sum(int(e["kind"]) == C["DUOFORGE_EVENT_CRIT"] for e in out["events"][0])
        self.assertGreater(len(digests), 1)  # the damage rolls differ
        self.assertGreater(crits, 0)  # 64 turns of four attacks: about ten critical hits are expected

    def test_the_random_stream_is_always_named(self):
        b = _start(self)
        with self.assertRaises(TypeError):
            privileged.step_events(b, 0, _attack(b)[0])  # neither a reseed nor the batch's own stream asked for

    def test_a_choice_outside_the_domain_is_refused(self):
        b = _start(self)
        choices = _attack(b)[0].copy()
        choices["slot"][0][0] = 31
        with self.assertRaisesRegex(ValueError, "not in the domain"):
            privileged.step_events(b, 0, choices, rng=(1, 2))


if __name__ == "__main__":
    unittest.main()
