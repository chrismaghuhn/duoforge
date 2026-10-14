#!/usr/bin/env python3
"""Checks for classify_unsupported.py. The class of a pool entry follows its pinned object:

- a callback or a condition makes it hand-work and names it;
- a reference to its id in the pinned code (hasAbility('x'), case 'x':, an includes list ...) makes it hand-work and
  names every site;
- without either it is data-only: its family is a modelled and marked witness that expresses all its effect fields
  (a generic witness, special NONE, by shape; a dedicated witness, a named special, by exact text), "none" with the
  fields that no witness has and a nearest dedicated witness when one differs, or "no effect fields" when it has no
  effect field at all.

The texts copy the pinned layout, so no checkout is needed. The last test reads the pinned checkout and is skipped
without DUOFORGE_PS_REFERENCE_DIR.

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
    return cu.make_witness(eid, handler, [body(eid, *lines)])


GENERIC = witness('plainmove', 'NONE', 'target: "adjacentAllyOrSelf",', 'accuracy: 100,', 'basePower: 40,')
MULTI = witness('multiwitness', 'MULTI_HIT_2_5', 'multihit: [2, 5],', 'basePower: 25,')
ICE_FANG = witness('icefang', 'ICE_FANG',
                   'secondaries: [ { chance: 10, status: "frz", }, { chance: 10, volatileStatus: "flinch", }, ],')
GENERIC_SECONDARY = witness('generic2', 'NONE', 'secondary: { chance: 10, status: "frz", },')
BULLET = witness('bulletwitness', 'NONE', 'flags: {bullet: 1},', 'basePower: 10,')


def analyse_move(name, *lines):
    return cu.analyse('move', [body(name, *lines)])


SCAREY = witness('scaryface', 'NONE', 'boosts: {spe: -1},')
BREAKING = witness('breakingswipe', 'NONE', 'target: "normal",')


def classify_move(name, *lines, modelled=False, witnesses=(), recorded=None, references=(), reason=None):
    return cu.classify_entry('move', name, name.title(), modelled, analyse_move(name, *lines), list(witnesses),
                             'data/moves.ts:1-2', recorded, list(references), generator_reason=reason)


class MoveClasses(unittest.TestCase):
    def test_on_hit_is_hand_work_naming_it(self):
        rec = classify_move('acupressure', 'accuracy: true,', 'onHit(target) {', '    return 1;', '},',
                            witnesses=[GENERIC])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['callback onHit'])
        self.assertIsNone(rec['family'])

    def test_condition_is_hand_work(self):
        rec = classify_move('aquaring', 'condition: {', '\tduration: 1,', '},', witnesses=[GENERIC])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['condition'])

    def test_callback_named_property_counts_even_with_a_value(self):
        rec = classify_move('odd', 'onTryHitPriority: -1,', 'basePower: 40,', witnesses=[GENERIC])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['callback onTryHitPriority'])

    def test_generic_witness_matches_by_shape(self):
        rec = classify_move('plainish', 'target: "adjacentAllyOrSelf",', 'basePower: 60,', witnesses=[GENERIC])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {'target': {'id': 'plainmove', 'column': 'target'}})

    def test_field_shape_no_witness_has_is_family_none_naming_the_field(self):
        rec = classify_move('bonerush', 'multihit: [3, 3],', 'basePower: 25,', witnesses=[GENERIC])
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: multihit', rec['reasons'])
        self.assertIsNone(rec['nearest'])

    def test_multihit_range_witness_matches_exactly(self):
        rec = classify_move('pinmissile', 'multihit: [2, 5],', 'basePower: 25,', witnesses=[GENERIC, MULTI])
        self.assertEqual(rec['family'], {'multihit': {'id': 'multiwitness', 'special': 'MULTI_HIT_2_5'}})

    def test_dedicated_special_mismatch_is_none_with_nearest(self):
        rec = classify_move('firefang', 'secondaries: [ { chance: 10, status: "brn", }, '
                                        '{ chance: 10, volatileStatus: "flinch", }, ],', witnesses=[ICE_FANG])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], 'none')
        self.assertEqual(rec['nearest']['id'], 'icefang')
        self.assertEqual(rec['nearest']['special'], 'ICE_FANG')
        self.assertIn("'brn' vs 'frz'", rec['nearest']['differs'])

    def test_dedicated_special_exact_text_matches(self):
        rec = classify_move('thunderfist', 'secondaries: [ { chance: 10, status: "frz", }, '
                                           '{ chance: 10, volatileStatus: "flinch", }, ],', witnesses=[ICE_FANG])
        self.assertEqual(rec['family'], {'secondaries': {'id': 'icefang', 'special': 'ICE_FANG'}})

    def test_generic_column_needs_the_same_value(self):
        rec = classify_move('firefang', 'secondary: { chance: 10, status: "brn", },', witnesses=[GENERIC_SECONDARY])
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: secondary', rec['reasons'])

    def test_generic_column_with_the_same_value_is_covered(self):
        rec = classify_move('firefang', 'secondary: { chance: 10, status: "frz", },', witnesses=[GENERIC_SECONDARY])
        self.assertEqual(rec['family'], {'secondary': {'id': 'generic2', 'column': 'secondary'}})

    def test_each_field_may_have_its_own_witness(self):
        rec = classify_move('bulletseed', 'multihit: [2, 5],', 'flags: {bullet: 1},', 'basePower: 25,',
                            witnesses=[MULTI, BULLET])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {
            'multihit': {'id': 'multiwitness', 'special': 'MULTI_HIT_2_5'},
            'flags.bullet': {'id': 'bulletwitness', 'column': 'flags'}})

    def test_combination_reason_with_only_generic_witnesses_is_none(self):
        rec = classify_move('cottonspore', 'boosts: {spe: -1},', 'target: "normal",', witnesses=[SCAREY, BREAKING],
                            reason='primary boosts on a non-self target')
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: primary boosts on a non-self target', rec['reasons'])
        self.assertEqual(rec['generator_reason'], 'primary boosts on a non-self target')

    def test_reason_covered_by_a_dedicated_witness(self):
        rec = classify_move('reasonmulti', 'multihit: [2, 5],', 'basePower: 25,', witnesses=[MULTI],
                            reason='field multihit')
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {
            'multihit': {'id': 'multiwitness', 'special': 'MULTI_HIT_2_5'},
            'reason field multihit': {'id': 'multiwitness', 'special': 'MULTI_HIT_2_5'}})

    def test_reason_with_a_dedicated_witness_of_other_text_is_none(self):
        rec = classify_move('reasonother', 'multihit: [3, 3],', 'basePower: 25,', witnesses=[MULTI],
                            reason='field multihit')
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: field multihit, multihit', rec['reasons'])

    def test_generator_reason_is_none_for_a_modelled_entry(self):
        rec = classify_move('jetpunch', 'basePower: 60,', modelled=True)
        self.assertIsNone(rec['generator_reason'])

    def test_dedicated_witness_whose_owned_fields_fit_is_preferred(self):
        # Dragon Darts owns smartTarget, which Double Hit lacks; Dual Wing Beat owns only multihit: it fits.
        dragon = witness('dragondarts', 'DRAGON_DARTS', 'multihit: 2,', 'smartTarget: true,')
        dual = witness('dualwingbeat', 'MULTI_HIT_2', 'multihit: 2,')
        rec = classify_move('doublehit', 'multihit: 2,', 'basePower: 25,', witnesses=[dragon, dual],
                            reason='field multihit')
        self.assertEqual(rec['family']['multihit']['id'], 'dualwingbeat')
        self.assertNotIn('partial', rec['family']['multihit'])
        self.assertEqual(rec['family']['reason field multihit']['id'], 'dualwingbeat')
        self.assertEqual(sorted(a['id'] for a in rec['family']['multihit']['alternatives']),
                         ['dragondarts', 'dualwingbeat'])

    def test_no_fitting_witness_takes_the_best_and_names_the_partial_fields(self):
        dragon = witness('dragondarts', 'DRAGON_DARTS', 'multihit: 2,', 'smartTarget: true,')
        rec = classify_move('doublehit', 'multihit: 2,', 'basePower: 25,', witnesses=[dragon])
        self.assertEqual(rec['family']['multihit']['id'], 'dragondarts')
        self.assertEqual(rec['family']['multihit']['partial'], ['smartTarget'])

    def test_a_field_value_no_entry_has_is_none(self):
        rec = classify_move('odd', 'multihit: [2, 5],', 'target: "foo",', witnesses=[MULTI, BULLET])
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: target', rec['reasons'])

    def test_id_reference_is_hand_work_naming_every_site(self):
        rec = classify_move('bite', 'basePower: 60,', witnesses=[GENERIC],
                            references=['sim/pokemon.ts:1710', 'data/conditions.ts:68'])
        self.assertEqual(rec['class'], 'hand-work')
        self.assertEqual(rec['reasons'], ['referenced by id at sim/pokemon.ts:1710',
                                          'referenced by id at data/conditions.ts:68'])
        self.assertIsNone(rec['family'])

    def test_no_effect_fields_is_not_a_witness(self):
        rec = classify_move('plainnothing', 'accuracy: true,', 'basePower: 0,', witnesses=[GENERIC])
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], 'no effect fields')

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
        a = cu.analyse('move', [base, champ])
        self.assertEqual(a['callbacks'], ['onTry'])
        self.assertIn('priority', a['columns'])
        self.assertEqual(a['fields'], {})

    def test_flags_are_one_field_each(self):
        flag_witness = witness('flagged', 'NONE', 'flags: {contact: 1, protect: 1},', 'basePower: 10,')
        rec = classify_move('punchy', 'flags: {contact: 1, bullet: 1},', 'basePower: 10,', witnesses=[flag_witness])
        self.assertEqual(rec['family'], 'none')
        self.assertIn('uncovered: flags.bullet', rec['reasons'])


class FindReferences(unittest.TestCase):
    def test_patterns_in_code_and_not_in_comments(self):
        lines = [
            "const x = source?.hasAbility('corrosion');",
            "    case 'corrosion':",
            "if (ids.includes('corrosion')) {",
            "const list = ['x', 'corrosion', 'y'];",
            "// hasAbility('corrosion') in a comment",
            "this.add('-activate', 'corrosion');",
        ]
        hits = cu.find_references('corrosion', [('sim/pokemon.ts', lines)])
        self.assertEqual(hits, ['sim/pokemon.ts:1', 'sim/pokemon.ts:2', 'sim/pokemon.ts:3', 'sim/pokemon.ts:4'])

    def test_other_ids_are_not_hits(self):
        hits = cu.find_references('earlybird', [('data/conditions.ts', ["hasAbility('corrosion')"])])
        self.assertEqual(hits, [])


class ItemAndAbilityClasses(unittest.TestCase):
    def test_item_with_on_eat_is_hand_work(self):
        a = cu.analyse('item', [body('aspearberry', 'name: "Aspear Berry",', 'onEat(pokemon) {', '},')])
        self.assertEqual(a['callbacks'], ['onEat'])
        rec = cu.classify_entry('item', 'aspearberry', 'Aspear Berry', False, a, [], 'data/items.ts:1-2')
        self.assertEqual(rec['reasons'], ['callback onEat'])

    def test_item_with_an_effect_field_and_a_witness(self):
        item_w = cu.make_witness('sitrusberry', 'NONE', [body('sitrusberry', 'boosts: {atk: 1},')])
        a = cu.analyse('item', [body('starapitite', 'boosts: {atk: 1},')])
        rec = cu.classify_entry('item', 'starapitite', 'Starapitite', False, a, [item_w], 'data/items.ts:1-2')
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], {'boosts': {'id': 'sitrusberry', 'family': 'NONE'}})

    def test_ability_with_on_start_is_hand_work(self):
        a = cu.analyse('ability', [body('anticipation', 'name: "Anticipation",', 'onStart(pokemon) {', '},')])
        self.assertEqual(a['callbacks'], ['onStart'])

    def test_ability_with_callback_named_value_is_hand_work(self):
        a = cu.analyse('ability', [body('stall', 'name: "Stall",', 'onFractionalPriority: -0.1,')])
        self.assertEqual(a['callbacks'], ['onFractionalPriority'])

    def test_ability_with_only_inert_fields_has_no_effect_fields(self):
        a = cu.analyse('ability', [body('corrosion', 'name: "Corrosion",', 'rating: 2.5,', 'num: 212,', 'flags: {},')])
        rec = cu.classify_entry('ability', 'corrosion', 'Corrosion', False, a, [], 'data/abilities.ts:1-2')
        self.assertEqual(rec['class'], 'data-only')
        self.assertEqual(rec['family'], 'no effect fields')


class Normalisation(unittest.TestCase):
    def test_shape_numbers_arrays_and_quotes(self):
        self.assertEqual(cu.normalize(' [2, 5], '), '[N,N]')
        self.assertEqual(cu.normalize(' "always" '), "'always'")
        self.assertEqual(cu.normalize(' {atk: -1, def: 2} '), '{atk:N,def:N}')

    def test_exact_keeps_numbers(self):
        self.assertEqual(cu.exact_text(' [2, 5], '), '[2,5]')
        self.assertEqual(cu.exact_text(' { status: "frz", } '), "{status:'frz'}")


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
