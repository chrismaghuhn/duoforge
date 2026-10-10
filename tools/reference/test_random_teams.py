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

    def test_an_id_names_the_content(self):
        a, b = rt.to_paste([gset('Incineroar')]), rt.to_paste([gset('Torkoal')])
        self.assertRegex(rt.team_id(a), r'^RT_[0-9A-F]{16}$')
        self.assertEqual(rt.team_id(a), rt.team_id(a))
        self.assertNotEqual(rt.team_id(a), rt.team_id(b))


def registry_sets(team_id):
    """The sets of a registry team as the generator would give them (a stand-in for ps_random_teams.js)."""
    with open(os.path.join(rt.ROOT, 'data', 'teams', team_id + '.txt'), encoding='utf-8') as f:
        members = teams.parse(f.read(), team_id)
    keys = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
    return [{'species': m['species'], 'gender': m['gender'] or '', 'shiny': False, 'level': 50, 'item': m['item'] or '',
             'ability': m['ability'], 'nature': m['nature'], 'evs': dict(zip(keys, m['stat_points'])),
             'ivs': dict.fromkeys(keys, 31), 'moves': list(m['moves'])} for m in members]


class Main(unittest.TestCase):
    """main() end to end with the library (DUOFORGE_LIBRARY) and stand-ins for the generator and the composition:
    only teams the engine accepts are written, a refusal is counted, and a second run writes the same bytes."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='random_teams_')
        self.checkout = os.path.join(self.tmp, 'ps')
        os.makedirs(os.path.join(self.checkout, 'dist', 'sim'))
        with open(os.path.join(rt.ROOT, 'data', 'teams', 'index.json'), encoding='utf-8') as f:
            ids = [t['id'] for t in json.load(f)['teams'] if t['id'].startswith('PP_')]
        self.good = registry_sets(ids[0])
        bad = registry_sets(ids[1])
        bad[0]['evs'].update(hp=32, atk=32, spe=32)  # 96 or more stat points: the pre-filter passes it,
        # the engine refuses the team (DUOFORGE_STAT_POINTS_TOTAL_MAX)
        self.bad = bad
        self.saved = rt.generate, rt.compose
        rt.generate = lambda node, checkout, seed, first, count: [
            {'index': first + i, 'seed': 's', 'team': t} for i, t in enumerate([self.good, self.bad][first:first + count])]
        rt.compose = lambda sets, rng, dex_of, size=6: [self.good, self.bad]

    def tearDown(self):
        import shutil
        rt.generate, rt.compose = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_main(self, name):
        out = os.path.join(self.tmp, name)
        code = rt.main(['--checkout', self.checkout, '--seed', '00000000000000aa', '--count', '2',
                        '--generator-teams', '2', '--out', out])
        return code, out

    def test_only_accepted_teams_are_written_and_a_rerun_is_byte_identical(self):
        code, out = self.run_main('a')
        self.assertEqual(code, 1)  # 1 of 2 teams: the refused one is not replaced
        with open(os.path.join(out, 'manifest.json'), encoding='utf-8') as f:
            manifest = json.load(f)
        self.assertEqual(manifest['kept'], 1)
        self.assertEqual(manifest['teams'], {'pool': 1, 'illegal': 1})
        with open(os.path.join(out, 'teams.txt'), encoding='utf-8') as f:
            [tid] = f.read().split()
        good_text = rt.to_paste(self.good)
        self.assertEqual(tid, rt.team_id(good_text))
        with open(os.path.join(out, tid + '.txt'), encoding='utf-8') as f:
            self.assertEqual(f.read(), good_text)
        self.assertEqual(sorted(os.listdir(out)), sorted([tid + '.txt', 'index.json', 'manifest.json', 'teams.txt']))
        _, again = self.run_main('b')
        for name in ('index.json', 'manifest.json', 'teams.txt', tid + '.txt'):
            with open(os.path.join(out, name), 'rb') as f1, open(os.path.join(again, name), 'rb') as f2:
                self.assertEqual(f1.read(), f2.read(), name)


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

    def test_the_pin_gives_the_recorded_first_team(self):
        # pinned Showdown b2cb775b0616115b775534eaeff50300e1fc81fc; a new pin that changes the generator changes this
        [cand] = self.run_js('00000000000000aa', 0, 1)
        self.assertEqual([s['species'] for s in cand['team']],
                         ['Tauros-Paldea-Combat', 'Greninja', 'Chimecho', 'Skarmory', 'Salamence', 'Alakazam'])
        self.assertEqual([s['item'] for s in cand['team']],
                         ['Life Orb', 'Life Orb', 'Sitrus Berry', 'Leftovers', 'Life Orb', 'Alakazite'])

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
