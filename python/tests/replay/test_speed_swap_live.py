"""Step K3 (#473, decision 0015 5de): the live record of a Speed Swap.

The tracker folds the swap's -activate line into the presence bit of both positions, and the record it assembles carries
the bit (single_turn, DFI_SINGLE_TURN_SPEED_SWAP). The engine's public-record check (duoforge_public_record_check) then
refuses the record with DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP exactly while a swapped Speed is live, and takes it back once
both swapped occupants have left (a switch-out rebuilds the leaver's Speed). The check runs on a record built WITHOUT the
assembler's own shortcut (record._record), so the engine's verdict is what is tested.

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR), like test_replay.py.
"""
import os
import unittest

from duoforge import view as _view
from duoforge_live import record
from python.tests.replay.test_replay import Reference, battle_sheets, true_picks, true_stats_of

SPEED_SWAP_BATTLES = ("k3_speed_swap_basic", "k3_speed_swap_switch", "k3_speed_swap_mega")


def _swapped(tracker):
    return any(p.speed_swapped for side in tracker._positions for p in side)


class SpeedSwapLiveRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from duoforge_replay.stats import StatSource
        cls.ref = Reference.get()
        cls.source = StatSource(os.environ["DUOFORGE_NODE"], os.environ["DUOFORGE_PS_REFERENCE_DIR"])

    @classmethod
    def tearDownClass(cls):
        cls.source.close()

    def check_battle(self, name, side):
        from duoforge_replay import points, spectator
        battle = next(b for b in self.ref.battles if b.name == name)
        log = battle.lines
        tracker = spectator.SpectatorTracker(self.ref.data, battle_sheets(battle), side, true_picks(battle, side),
                                             true_stats_of(battle, side, self.source), log)
        checked = refused = 0
        for point in spectator.walk(tracker, log, points.find(log)):
            if not spectator.own_requested(tracker):
                continue
            observation = tracker.observation().copy()
            ctx = tracker.data.context_of(tracker.record_kind)
            want_refused = _swapped(tracker)
            try:
                assembled = record._record(tracker, observation)
            except record.Refusal:
                continue  # a field the library cannot reproduce here refuses on its own (not this step's business)
            status = _view.public_record_check(ctx, assembled)
            self.assertEqual(status == record.E_UNSUPPORTED, want_refused, (name, side, point))
            checked += 1
            refused += want_refused
        self.assertGreater(checked, 0, name)
        return checked, refused

    def test_engine_refuses_exactly_while_the_swap_is_live(self):
        for name in SPEED_SWAP_BATTLES:
            for side in (0, 1):
                with self.subTest(battle=name, side=side):
                    checked, refused = self.check_battle(name, side)
                    print(f"\n{name} side {side}: {checked} points checked, {refused} refused with the swap live")
                    if name == "k3_speed_swap_basic":
                        self.assertGreater(refused, 0)  # the swap stands from turn 1 to the end of the record
