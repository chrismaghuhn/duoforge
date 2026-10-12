"""duoforge.python.state_layout: the canonical state encoding's fields by name (generated from the C macros)."""
import os
from pathlib import Path
import re
import unittest

import numpy as np

import duoforge
from duoforge import _layout, _state_layout, state_layout
from tools.layout.gen_state_layout import generate

ROOT = Path(__file__).resolve().parents[2]
POOL_SIZE = 1357  # DUOFORGE_VIEW_STATE_MAX: the POOL encoding (tail rev 5)
CLOSURE_SIZE = 1009  # the v3 body without the POOL tail


class StateLayout(unittest.TestCase):
    def test_generated_layout_is_current(self):
        source = Path(_state_layout.__file__).read_text(encoding="utf-8")
        self.assertEqual(source, generate(os.environ["DUOFORGE_STATE_LAYOUT_DUMP"]))

    def test_dump_lists_every_macro_of_the_header(self):
        header = (ROOT / "src/codec/state_codec.h").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"#define (DFI_ENC_[A-Z0-9_]+) ", header)), set(_state_layout.OFFSETS))

    def test_fields_cover_every_byte_once(self):
        for pool, size in ((True, POOL_SIZE), (False, CLOSURE_SIZE)):
            with self.subTest(pool=pool):
                spans = state_layout.fields(pool)
                self.assertEqual(len({name for name, _, _ in spans}), len(spans))  # unique names
                end = 0
                for name, start, length in sorted(spans, key=lambda f: f[1]):
                    self.assertEqual(start, end, name)  # no gap, no overlap
                    self.assertGreater(length, 0, name)
                    end = start + length
                self.assertEqual(end, size)
        self.assertEqual(_layout.CONSTANTS.get("DUOFORGE_VIEW_STATE_MAX", POOL_SIZE), POOL_SIZE)

    def test_diff_names_the_field(self):
        C = _layout.CONSTANTS
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            b.query_factored()
            choice = np.zeros((1, 2), dtype=_layout.FACTORED_CHOICE)
            for side in (0, 1):
                choice["picks"][0, side, :4] = (0, 1, 2, 3)
            b.step_factored(choice)
            records, statuses = b.public(np.zeros(1, np.uint32))
            self.assertEqual(int(statuses[0]), 0)
            size = int(records["state_size"][0])
            state = bytes(records["state"][0][:size])
        self.assertEqual(size, POOL_SIZE)
        self.assertEqual(state_layout.diff(state, state), [])
        named = {name: (start, length) for name, start, length in state_layout.fields()}
        for name in ("turn", "side1.member0.hp", "side0.position1.activation", "tail.side1.position0.taunt_turns",
                     "tail5.position3.position_flags"):
            start, _ = named[name]
            changed = bytearray(state)
            changed[start] ^= 0x01
            self.assertEqual(state_layout.diff(state, changed), [name])
        with self.assertRaises(ValueError):
            state_layout.diff(state, state[:-1])


if __name__ == "__main__":
    unittest.main()
