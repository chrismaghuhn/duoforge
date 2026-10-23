"""Step K3 (#473, decision 0015 5de): the live record of a Speed Swap.

The tracker folds the swap's -activate line into the presence bit of both positions, and the public record it assembles
(Tracker.public_parts, record.assemble) refuses with DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP (128) exactly while a swapped Speed is
live on an active position, and accepts again once both swapped occupants have left. The pool records of these battles are
also compared with the engine's records in duoforge.python.live (test_pool_records_equal_engine); this test checks the cause.

It uses the same feed as the pool record test (test_live.py TestPool...): the battle's streams per player, the record kind of
the battle, the team of the spec; no spectator walk.
"""
import unittest
from unittest import mock

from duoforge import view
from duoforge_live import record
from python.tests.live.test_live import Reference, record_kind

# k3_aegislash_swap_end is not here: its Stance Change is a FORME_CHANGE line, which the tracker stops at (a named stop, as
# for the Aegislash battles of the pool); its refusal and its end are checked by the engine in duoforge.moves.speed_swap.
SPEED_SWAP_BATTLES = ("k3_speed_swap_basic", "k3_speed_swap_switch", "k3_speed_swap_mega", "k3_speed_swap_mega_end")


def _swapped(tracker):
    return any(p.speed_swapped for side in tracker._positions for p in side)


class SpeedSwapLiveRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from duoforge_live.tracker import Tracker
        cls.pool = Reference.get().pool()
        cls.points = {}  # (battle, player) -> [(k, swapped, parts, engine verdicts of the point)]
        cls.engine_calls = []  # every status the engine's record check gave while the points are assembled
        real_check = view.public_record_check

        def spy(ctx, rec):
            status = real_check(ctx, rec)
            cls.engine_calls.append(status)
            return status

        patcher = mock.patch.object(view, "public_record_check", spy)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        for battle in cls.pool.battles:
            if battle.name not in SPEED_SWAP_BATTLES:
                continue
            kind = record_kind(battle.name)
            for player in (0, 1):
                tracker, done, pid = Tracker(cls.pool.data, battle.spec["teams"][player]), 0, f"p{player + 1}"
                tracker.record_kind = kind
                out = cls.points[(battle.name, player)] = []
                for lines in battle.streams[player]:
                    tracker.feed(lines)
                    if not (tracker.ready and tracker.epoch > done):
                        continue
                    done = tracker.epoch
                    k = done - 1
                    before = len(cls.engine_calls)
                    parts = tracker.public_parts()
                    out.append((k, _swapped(tracker), parts, cls.engine_calls[before:]))
                    step = battle.trace["steps"][k] if k < len(battle.trace["steps"]) else None
                    if step is not None and pid in step["input"]:
                        tracker.accepted(step["input"][pid])

    def test_refused_with_cause_128_exactly_while_a_swap_is_live(self):
        for name in SPEED_SWAP_BATTLES:
            for player in (0, 1):
                with self.subTest(battle=name, side=player):
                    points = self.points[(name, player)]
                    self.assertTrue(points, (name, player))
                    live = [p for p in points if p[1]]
                    self.assertTrue(live, (name, player))  # the swap is on the record at some point
                    for k, swapped, parts, _ in points:
                        causes = int(parts["causes"])
                        if swapped:
                            self.assertEqual(parts["status"], record.E_UNSUPPORTED, (name, player, k))
                            self.assertEqual(causes & record.CAUSE_SPEED_SWAP, record.CAUSE_SPEED_SWAP, (name, player, k, parts["reason"]))
                        else:
                            self.assertEqual(causes & record.CAUSE_SPEED_SWAP, 0, (name, player, k))
                    print(f"\n{name} side {player}: {len(points)} points, {len(live)} with the swap live")

    def test_the_engine_refuses_every_swapped_point(self):
        # the engine's record check (duoforge.view.public_record_check) decides the refusal: at every point with a live swap
        # the assembled record is put to the engine, and the engine answers E_UNSUPPORTED
        for name in SPEED_SWAP_BATTLES:
            for player in (0, 1):
                with self.subTest(battle=name, side=player):
                    for k, swapped, parts, verdicts in self.points[(name, player)]:
                        if swapped:
                            self.assertIn(record.E_UNSUPPORTED, verdicts, (name, player, k))
                            self.assertEqual(parts["reason"], "speed-swap", (name, player, k))

    def test_accepted_again_after_the_last_swap_ends(self):
        # k3_speed_swap_mega_end: Alakazam's own swap ends at its Mega and Milotic's at its switch-out (turn 3); the record
        # is refused before the last of them and accepted after it.
        for name in ("k3_speed_swap_mega_end",):
            for player in (0, 1):
                with self.subTest(battle=name, side=player):
                    points = self.points[(name, player)]
                    last_live = max(k for k, swapped, _, _v in points if swapped)
                    after = [(k, parts) for k, swapped, parts, _v in points if not swapped and k > last_live]
                    self.assertTrue(after, (name, player))
                    for k, parts in after:
                        self.assertEqual(int(parts["causes"]) & record.CAUSE_SPEED_SWAP, 0, (name, player, k))
                    self.assertTrue(any(parts["status"] == 0 for _, parts in after), (name, player))

    def test_accepted_again_once_both_swapped_occupants_left(self):
        # k3_speed_swap_switch: Milotic (the target) switches out on turn 2 and Alakazam on turn 3, so the last live point
        # is followed by points without the swap, and those are accepted (status 0) unless another reason refuses them.
        name = "k3_speed_swap_switch"
        for player in (0, 1):
            with self.subTest(battle=name, side=player):
                points = self.points[(name, player)]
                last_live = max(k for k, swapped, _, _v in points if swapped)
                after = [(k, parts) for k, swapped, parts, _v in points if not swapped and k > last_live]
                self.assertTrue(after, (name, player))
                for k, parts in after:
                    self.assertEqual(int(parts["causes"]) & record.CAUSE_SPEED_SWAP, 0, (name, player, k))
                self.assertTrue(any(parts["status"] == 0 for _, parts in after), (name, player))


if __name__ == "__main__":
    unittest.main()
