#!/usr/bin/env python3
"""The random training teams (tools/reference/random_teams.py): the paste translation, the team composition and the
output guard without Node or the library; with <node> <checkout>, also the pinned generator's determinism.

usage: python3 tools/reference/test_random_teams.py [<node> <checkout>]

CTest runs it as duoforge.reference.random_teams (no arguments) and, with the pinned Showdown, as
duoforge.reference.random_teams_pin (label reference).
"""
import json
import os
import random
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'python'))
import random_teams as rt  # noqa: E402
from duoforge import teams  # noqa: E402

NODE = CHECKOUT = None  # the arguments (set by main)


def gset(species, item='Life Orb', **over):
    s = {'species': species, 'gender': 'F', 'shiny': False, 'level': 54, 'item': item, 'ability': 'Intimidate',
         'nature': '', 'evs': {'hp': 11, 'atk': 0, 'def': 11, 'spa': 11, 'spd': 11, 'spe': 11},
         'ivs': dict.fromkeys(('hp', 'atk', 'def', 'spa', 'spd', 'spe'), 31), 'moves': ['Protect', 'Fake Out']}
    s.update(over)
    return s


class Paste(unittest.TestCase):
    def test_the_level_is_50_and_a_missing_nature_is_serious(self):
        text = rt.to_paste([gset('Incineroar')])
        self.assertIn('Level: 50\n', text)
        self.assertNotIn('Level: 54', text)
        self.assertIn('Serious Nature\n', text)
        [m] = teams.parse(text, 't')  # the registry format reads it
        self.assertEqual((m['species'], m['gender'], m['item'], m['nature']), ('Incineroar', 'F', 'Life Orb', 'Serious'))
        self.assertEqual(m['stat_points'], [11, 0, 11, 11, 11, 11])  # the generator's stat points, a zero left out
        self.assertEqual(m['moves'], ['Protect', 'Fake Out'])

    def test_a_given_nature_and_no_item_and_no_gender_are_kept(self):
        [m] = teams.parse(rt.to_paste([gset('Porygon2', item='', gender='N', nature='Quiet')]), 't')
        self.assertEqual((m['item'], m['gender'], m['nature']), (None, None, 'Quiet'))

    def test_a_shiny_set_and_an_iv_below_31_are_refused_not_changed(self):
        with self.assertRaisesRegex(rt.RandomTeamError, 'set 2: shiny'):
            rt.to_paste([gset('Incineroar'), gset('Sinistcha', shiny=True)])
        low = gset('Torkoal')
        low['ivs']['spe'] = 0
        with self.assertRaisesRegex(rt.RandomTeamError, 'IVs other than 31'):
            rt.to_paste([low])


class Compose(unittest.TestCase):
    def sets(self):
        names = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'A', 'B']
        items = ['Life Orb', 'Sitrus Berry', 'Leftovers', 'Focus Sash', 'Choice Scarf', 'Mystic Water',
                 'Life Orb', 'Sitrus Berry', '', '', 'Charcoal', 'Miracle Seed', 'Wiki Berry', 'Shell Bell']
        return [gset(n, item=i) for n, i in zip(names, items)]

    def test_teams_keep_the_species_and_item_clause_and_use_each_set_once(self):
        built = rt.compose(self.sets(), random.Random(7), dex_of=lambda s: s)
        self.assertTrue(built)
        used = []
        for team in built:
            self.assertEqual(len(team), 6)
            self.assertEqual(len({s['species'] for s in team}), 6)
            items = [s['item'] for s in team if s['item']]
            self.assertEqual(len(items), len(set(items)))
            used += [id(s) for s in team]
        self.assertEqual(len(used), len(set(used)))

    def test_the_same_seed_gives_the_same_teams(self):
        sets = self.sets()
        a = rt.compose(sets, random.Random(11), dex_of=lambda s: s)
        b = rt.compose(sets, random.Random(11), dex_of=lambda s: s)
        self.assertEqual(a, b)

    def test_a_shared_dex_number_counts_as_one_species(self):
        sets = [gset('Rotom-Wash', item='Sitrus Berry'), gset('Rotom-Heat', item='Leftovers')] + \
            [gset(n, item='') for n in 'BCDEF']
        built = rt.compose(sets, random.Random(3), dex_of=lambda s: s.split('-')[0])
        self.assertEqual(len(built), 1)
        self.assertEqual(sum(s['species'].startswith('Rotom') for s in built[0]), 1)


class Guards(unittest.TestCase):
    def test_the_output_must_be_outside_the_repository(self):
        with self.assertRaisesRegex(rt.RandomTeamError, 'inside the repository'):
            rt.refuse_repository(os.path.join(rt.ROOT, 'data', 'random'))
        rt.refuse_repository(os.path.join(os.path.dirname(rt.ROOT), 'elsewhere'))  # no error

    def test_ids_name_the_seed_and_the_index(self):
        self.assertEqual(rt.team_id('2026101000000001', 7), 'RT_2026101000000001_000007')


class Pin(unittest.TestCase):
    """The pinned generator (Node): a team depends only on the seed and its index."""

    def run_js(self, seed, first, count):
        return rt.generate(NODE, CHECKOUT, seed, first, count)

    def setUp(self):
        if NODE is None:
            self.skipTest('needs <node> <checkout>')

    def test_the_same_seed_and_index_give_the_same_team(self):
        a = self.run_js('00000000000000aa', 0, 3)
        b = self.run_js('00000000000000aa', 1, 2)
        self.assertEqual(json.dumps(a[1:]), json.dumps(b))
        self.assertNotEqual(json.dumps(a[0]['team']), json.dumps(a[1]['team']))
        for cand in a:
            self.assertEqual(len(cand['team']), 6)
            for s in cand['team']:
                self.assertEqual(sum(s['evs'].values()) <= 66, True)
                teams.parse(rt.to_paste([s]) if not s['shiny'] else rt.to_paste([dict(s, shiny=False)]), 'pin')

    def test_a_bad_seed_is_refused(self):
        out = subprocess.run([NODE, os.path.join(HERE, 'ps_random_teams.js'), CHECKOUT, 'xyz', '0', '1'],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


def main():
    global NODE, CHECKOUT
    if len(sys.argv) >= 3:
        NODE, CHECKOUT = sys.argv[1], sys.argv[2]
        del sys.argv[1:3]
    unittest.main()


if __name__ == '__main__':
    main()
