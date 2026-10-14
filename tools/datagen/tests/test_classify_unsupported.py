#!/usr/bin/env python3
"""Checks for classify_unsupported.py: the class of a pool entry follows its pinned object. A callback (or a
condition) makes it hand-work and names it; without one it is data-only, with the modelled and marked witness
that expresses all its data fields, or family "none" naming the fields that no witness has. The texts copy the
pinned data layout, so no checkout is needed. The last test reads the pinned checkout and is skipped without
DUOFORGE_PS_REFERENCE_DIR.

usage: python3 tools/datagen/tests/test_classify_unsupported.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classify_unsupported as cu


def body(name, *lines):
    """An entry as Source.entry returns it: its first line, its fields one tab deeper, its closing line."""
    return ['\t%s: {' % name] + ['\t\t' + line for line in lines] + ['\t},']


def witness(eid, handler, *lines):
    return {'id': eid, 'handler': handler, 'fields': cu.parts('move', [body(eid, *lines)])[1]}


PLAIN = witness('plainmove', 'NONE', 'target: "adjacentAllyOrSelf",', 'accuracy: 100,', 'basePower: 40,')
MULTI = witness('multiwitness', 'MULTI_HIT_2_5', 'multihit: [2, 5],', 'basePower: 25,')


def classify_move(name, *lines, modelled=False, witnesses=(), recorded=None):
    cbs, fields, _columns = cu.parts('move', [body(name, *lines)])
    return cu.classify_entry('move', name, name.title(), modelled, cbs, fields, list(witnesses), 'data/moves.ts:1-2',
                             recorded)


class MoveClasses(unittest.TestCase):
    def test_on_hit_is_hand_work_naming_it(self):
        rec = classify_move('acupressure', 'accuracy: true,', 'onHit(target) {', '    return 1;', '},',
                            witnesses=[PLAIN])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['callback onHit'])
        self.assertIsNone(rec['family'])

    def test_condition_is_hand_work(self):
        rec = classify_move('aquaring', 'condition: {', '\tduration: 1,', '},', witnesses=[PLAIN])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['condition'])

    def test_callback_named_property_counts_even_with_a_value(self):
        rec = classify_move('odd', 'onTryHitPriority: -1,', 'basePower: 40,', witnesses=[PLAIN])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['callback onTryHitPriority'])

    def test_only_field_with_a_modelled_witness_is_data_only_with_that_witness(self):
        rec = classify_move('plainish', 'target: "adjacentAllyOrSelf",', 'basePower: 60,', witnesses=[PLAIN])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {'id': 'plainmove', 'handler': 'NONE'})
        self.assertEqual(rec['reasons'][0], 'no callback')

    def test_field_shape_no_witness_has_is_family_none_naming_the_field(self):
        rec = classify_move('bonerush', 'multihit: [3, 3],', 'basePower: 25,', witnesses=[PLAIN])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: multihit', rec['reasons'])

    def test_multihit_range_witness_matches_by_shape(self):
        rec = classify_move('pinmissile', 'multihit: [2, 5],', 'basePower: 25,', witnesses=[PLAIN, MULTI])
        self.assertEqual(rec['family'], {'id': 'multiwitness', 'handler': 'MULTI_HIT_2_5'})

    def test_modelled_entry_is_modelled_unmarked_with_the_recorded_reason(self):
        rec = classify_move('jetpunch', 'basePower: 60,', modelled=True,
                            recorded='Not marked: Jet Punch (its only learner has no marked ability)')
        self.assertEqual(rec['class'], 'modelled-unmarked')
        self.assertEqual(rec['reasons'], ['unmarked: Not marked: Jet Punch (its only learner has no marked ability)'])
        self.assertIsNone(rec['family'])

    def test_modelled_entry_without_a_recorded_reason(self):
        rec = classify_move('bite', 'basePower: 60,', modelled=True)
        self.assertEqual(rec['reasons'], ['unmarked: no recorded reason'])

    def test_champions_override_wins_per_field_and_callbacks_union(self):
        base = body('fakeout', 'priority: 3,', 'onTry() { return 1; },')
        champ = body('fakeout', 'priority: 2,')
        cbs, fields, columns = cu.parts('move', [base, champ])
        self.assertEqual(cbs, ['onTry'])
        self.assertIn('priority', columns)
        self.assertEqual(fields, {})

    def test_flags_are_one_field_each(self):
        flag_witness = witness('flagged', 'NONE', 'flags: {contact: 1, protect: 1},', 'basePower: 10,')
        rec = classify_move('punchy', 'flags: {contact: 1, bullet: 1},', 'basePower: 10,', witnesses=[flag_witness])
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: flags.bullet', rec['reasons'])


class ItemAndAbilityClasses(unittest.TestCase):
    def test_item_with_on_eat_is_hand_work(self):
        cbs, fields, _ = cu.parts('item', [body('aspearberry', 'name: "Aspear Berry",', 'onEat(pokemon) {', '},')])
        self.assertEqual(cbs, ['onEat'])
        rec = cu.classify_entry('item', 'aspearberry', 'Aspear Berry', False, cbs, fields, [], 'data/items.ts:1-2')
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['callback onEat'])

    def test_item_without_callback_and_fields_is_data_only_with_a_witness(self):
        item_w = {'id': 'sitrusberry', 'handler': 'NONE', 'fields': {}}
        cbs, fields, _ = cu.parts('item', [body('starapitite', 'name: "Starapitite",', 'fling: {basePower: 80},')])
        rec = cu.classify_entry('item', 'starapitite', 'Starapitite', False, cbs, fields, [item_w], 'data/items.ts:1-2')
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {'id': 'sitrusberry', 'handler': 'NONE'})

    def test_ability_with_on_start_is_hand_work(self):
        cbs, _f, _ = cu.parts('ability', [body('anticipation', 'name: "Anticipation",', 'onStart(pokemon) {', '},')])
        self.assertEqual(cbs, ['onStart'])

    def test_ability_with_callback_named_value_is_hand_work(self):
        cbs, _f, _ = cu.parts('ability', [body('stall', 'name: "Stall",', 'onFractionalPriority: -0.1,')])
        self.assertEqual(cbs, ['onFractionalPriority'])

    def test_ability_without_callback_and_with_no_fields_matches_a_plain_witness(self):
        abil_w = {'id': 'adaptability', 'handler': 'NONE', 'fields': {}}
        cbs, fields, _ = cu.parts('ability', [body('corrosion', 'name: "Corrosion",', 'rating: 2,', 'num: 212,')])
        rec = cu.classify_entry('ability', 'corrosion', 'Corrosion', False, cbs, fields, [abil_w], 'data/abilities.ts:1-2')
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {'id': 'adaptability', 'handler': 'NONE'})


class Normalisation(unittest.TestCase):
    def test_numbers_arrays_and_quotes(self):
        self.assertEqual(cu.normalize(' [2, 5], '), '[N,N]')
        self.assertEqual(cu.normalize(' "always" '), "'always'")
        self.assertEqual(cu.normalize(' {atk: -1, def: 2} '), '{atk:N,def:N}')


@unittest.skipUnless(os.environ.get('DUOFORGE_PS_REFERENCE_DIR'), 'needs the pinned Showdown checkout')
class CheckoutCounts(unittest.TestCase):
    def test_input_sets_and_one_class_each(self):
        records = cu.build(os.environ['DUOFORGE_PS_REFERENCE_DIR'])
        keys = [(r['kind'], r['id']) for r in records]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(r['class'] in cu.CLASSES for r in records))
        by = lambda kind, cls=None: sum(1 for r in records if r['kind'] == kind and (cls is None or r['class'] == cls))
        self.assertEqual(by('move'), 145 + 25)
        self.assertEqual(by('move', 'modelled-unmarked'), 25)
        self.assertEqual(by('item'), 33)
        self.assertEqual(by('ability'), 89)


if __name__ == '__main__':
    unittest.main()
