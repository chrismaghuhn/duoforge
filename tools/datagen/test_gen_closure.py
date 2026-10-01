#!/usr/bin/env python3
"""Refusal checks for gen_closure.py's move parser: a secondary effect the
tables do not model must fail instead of being encoded as something else.
The move texts copy the pinned data/moves.ts layout, so no checkout is needed.

usage: python3 tools/datagen/test_gen_closure.py
"""
import unittest

import gen_closure

# Flame Charge at the pin (data/moves.ts) with its secondary as a slot.
MOVE = '''\tflamecharge: {
\t\tnum: 488,
\t\taccuracy: 100,
\t\tbasePower: 50,
\t\tcategory: "Physical",
\t\tname: "Flame Charge",
\t\tpp: 20,
\t\tpriority: 0,
\t\tflags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },
%s
\t\ttarget: "normal",
\t\ttype: "Fire",
\t\tcontestType: "Cool",
\t},'''
# The pinned secondary: a Speed boost for the user, not the target.
SELF_BOOST = '''\t\tsecondary: {
\t\t\tchance: 100,
\t\t\tself: {
\t\t\t\tboosts: {
\t\t\t\t\tspe: 1,
\t\t\t\t},
\t\t\t},
\t\t},'''
TARGET_BOOST = '''\t\tsecondary: {
\t\t\tchance: 100,
\t\t\tboosts: {
\t\t\t\tspe: -1,
\t\t\t},
\t\t},'''
TWO_EFFECTS = '''\t\tsecondary: {
\t\t\tchance: 10,
\t\t\tstatus: 'brn',
\t\t\tvolatileStatus: 'flinch',
\t\t},'''
EMPTY = '\t\tsecondary: {}, // Sheer Force-boosted'


class TextSource(gen_closure.Source):
    """A Source over the test's own text, without the pin check."""

    def __init__(self, rel, text):
        self.rel, self.lines = rel, text.split('\n')


def parse(secondary, ext):
    base = TextSource('data/moves.ts', MOVE % secondary)
    champ = TextSource('data/mods/champions/moves.ts', '')
    return gen_closure.parse_move('flamecharge', base, champ, ext)


class Secondary(unittest.TestCase):
    def assert_refused(self, secondary, message):
        for ext in (False, True):
            with self.subTest(ext=ext):
                with self.assertRaises(SystemExit) as cm:
                    parse(secondary, ext)
                self.assertEqual(cm.exception.code, 'gen_closure: move flamecharge: ' + message)

    def test_self_boost_is_refused(self):
        self.assert_refused(SELF_BOOST, 'secondary self effects are not supported')

    def test_two_effects_are_refused(self):
        self.assert_refused(TWO_EFFECTS, 'unknown secondary')

    def test_empty_secondary_is_refused(self):
        self.assert_refused(EMPTY, 'unknown secondary')

    def test_target_boost_is_encoded(self):
        # Control: the same move text with a modelled secondary parses.
        want = [0] * len(gen_closure.BOOSTS)
        want[gen_closure.BOOSTS.index('spe')] = -1
        for ext in (False, True):
            with self.subTest(ext=ext):
                rec = parse(TARGET_BOOST, ext)
                self.assertEqual((rec['sec_chance'], rec['sec_kind'], rec['boost_role'], rec['boosts']),
                                 (100, 1, gen_closure.BOOST_ROLE['SECONDARY_TARGET'], want))


if __name__ == '__main__':
    unittest.main()
