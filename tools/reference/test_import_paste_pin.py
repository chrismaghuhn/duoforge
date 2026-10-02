#!/usr/bin/env python3
"""The paste importer with the pinned Showdown for the pokedex (Node): the facts, the owner's raw pastes, the registry.

usage: python3 tools/reference/test_import_paste_pin.py <node> <checkout>

CTest runs it as duoforge.reference.import_paste_pin (label reference). It checks what the stand-in pokedex of
test_import_paste.py cannot: that tools/reference/ps_species.js reads the facts of the pinned pokedex as the importer needs
them (the fixed gender, "N" for none, the Mega stone and the base forme), the raw pastes of decision 0004 (Team A and Team B
as retrieved from pokepast.es, which state few genders) imported into the registry's teams but for the genders, the three
teams of the registry imported as a fixed point (the importer changes nothing of what it wrote itself), the Mega mapping
and the cosmetic lines with real data, and the command line end to end.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import import_paste as imp  # noqa: E402
import team_registry as reg  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
NODE = CHECKOUT = None  # the arguments (set by main)
DECISION = os.path.join(ROOT, 'docs', 'decisions', '0004-owner-selections-champions-reference-teams.md')

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def without_genders(text):
    return re.sub(r' \((?:M|F)\)', '', text)


class WithThePin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CHECKOUT is None:
            raise unittest.SkipTest('usage: test_import_paste_pin.py <node> <checkout>')
        cls.infos = imp.SpeciesInfo(CHECKOUT, NODE)
        with io.open(DECISION, encoding='utf-8') as f:
            cls.raw = re.findall(r'```text\n(.*?)```', f.read(), re.S)
        assert len(cls.raw) == 2, 'decision 0004 has the two raw pastes in text blocks'

    def normalize(self, text):
        """What import_paste.main does with the pokedex: the names as written, then the base formes of the Megas."""
        self.infos.prefetch(imp.species_of_paste(text))
        self.infos.prefetch([i.get('battleOnly') or i.get('baseSpecies') for i in self.infos.cache.values() if i.get('isMega')])
        return imp.normalize(text, self.infos.get)

    def test_the_facts_of_the_pokedex(self):
        self.infos.prefetch(['Rillaboom', 'Gholdengo', 'Raichu-Mega-Y', 'Indeedee-F', 'Basculegion', 'rillaboom', 'Fakemon'])
        get = self.infos.get
        self.assertEqual((get('Rillaboom')['gender'], get('Rillaboom')['genderRatio']), ('', {'M': 0.875, 'F': 0.125}))
        self.assertEqual(get('Gholdengo')['gender'], 'N')
        self.assertEqual((get('Indeedee-F')['gender'], get('Basculegion')['gender']), ('F', 'M'))
        mega = get('Raichu-Mega-Y')
        self.assertEqual((mega['isMega'], mega['requiredItem'], mega['battleOnly'], mega['baseSpecies']),
                         (True, 'Raichunite Y', 'Raichu', 'Raichu'))
        self.assertEqual(get('rillaboom')['name'], 'Rillaboom')  # the pokedex spells it, and case does not matter
        self.assertFalse(get('Fakemon')['exists'])
        self.assertFalse(get('Rillaboom')['isMega'])

    def test_the_raw_pastes_of_the_owners_teams(self):
        """Team A and Team B as retrieved from pokepast.es (decision 0004): the importer adds the genders they lack and
        nothing else, so what it makes is the registry's team but for the genders, which the registry has by the project's
        own choice (the files the reference battles were made with) and the importer's standard does not change."""
        for team_id, raw, genders in (('A', self.raw[0], 5), ('B', self.raw[1], 6)):
            with self.subTest(team_id):
                sets, notes = self.normalize(raw)
                registry = reg.read_team(ROOT, team_id)[0]
                self.assertEqual([without_genders(s) for s in sets], [without_genders(s) for s in registry])
                # A gender is added to each Pokemon that has one and the paste does not state; Team B states Grimmsnarl's.
                self.assertEqual(len(notes), 5)
                self.assertTrue(all('gender (M) added to' in n and 'the species can be either' in n for n in notes), notes)
                self.assertEqual(sum(' (M)' in s.split('\n')[0] for s in sets), genders)
                self.assertEqual(reg.team_problems(reg.file_text(sets).decode('utf-8'), tables), [])

    def test_the_registry_is_a_fixed_point_of_the_importer(self):
        for team_id in ('A', 'B', 'C'):
            with self.subTest(team_id):
                registry = reg.read_team(ROOT, team_id)[0]
                self.assertEqual(self.normalize('\n\n'.join(registry)), (registry, []))  # it writes what it reads, silently

    def test_mega_formes_nicknames_and_cosmetic_lines_with_the_real_dex(self):
        text = '\n\n'.join([
            'Charizard-Mega-Y @ Charizardite Y\nAbility: Blaze\nShiny: Yes\nEVs: 2 HP\nTimid Nature\n- Protect',
            'Sunny (Rillaboom) @ Miracle Seed\nAbility: Grassy Surge\nHappiness: 0\nLevel: 50\nAdamant Nature\n- Fake Out',
            'Raichu-Mega-Y (F) @ Raichunite Y\nAbility: Lightning Rod\nTera Type: Electric\nTimid Nature\n- Protect',
            'Salamence-Mega @ Salamencite\nAbility: Intimidate\nJolly Nature\n- Protect',
            'Blissey @ Leftovers\nAbility: Natural Cure\nBold Nature\n- Protect',
            'Gholdengo @ Life Orb\nAbility: Good as Gold\nModest Nature\n- Make It Rain'])
        sets, notes = self.normalize(text)
        self.assertEqual([s.split('\n')[0] for s in sets], [
            'Charizard (M) @ Charizardite Y', 'Rillaboom (M) @ Miracle Seed', 'Raichu (F) @ Raichunite Y',
            'Salamence (M) @ Salamencite', 'Blissey (F) @ Leftovers', 'Gholdengo @ Life Orb'])
        self.assertEqual(sum('is written as' in n and 'the Mega forme is what the battle makes' in n for n in notes), 3)
        self.assertEqual(sum('dropped the cosmetic line' in n for n in notes), 3)  # Shiny, Happiness, Tera Type
        self.assertEqual(sum('"Level: 50" added' in n for n in notes), 5)  # all but the second had no level line
        self.assertEqual(sum('the nickname' in n for n in notes), 1)
        # Charizard, Rillaboom, Salamence and Blissey: Raichu states its own gender and Gholdengo has none.
        self.assertEqual(sorted(re.search(r'added to (\S+):', n).group(1) for n in notes if 'gender (' in n),
                         ['Blissey', 'Charizard', 'Rillaboom', 'Salamence'])
        self.assertEqual(len(notes), 3 + 3 + 5 + 1 + 4)
        self.assertEqual(reg.team_problems(reg.file_text(sets).decode('utf-8'), tables), [])

    def test_the_command_line_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(reg.registry_dir(ROOT), reg.registry_dir(tmp))
            paste_file = os.path.join(tmp, 'raw.txt')
            with io.open(paste_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(self.raw[0])
            command = [sys.executable, os.path.join(HERE, 'import_paste.py'), '--checkout', CHECKOUT, '--node', NODE, '--root',
                       tmp, '--paste', paste_file, '--id', 'MC405', '--name', 'Balt Top 8 (raw)', '--url',
                       'https://pokepast.es/470a6ec2468af8a4']
            done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out = done.stdout.decode('utf-8')
            self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8'))
            self.assertEqual(out.count('gender (M) added'), 5)
            self.assertIn('wrote ', out)
            self.assertEqual(reg.problems(tmp, tables), [])
            sets = reg.read_team(tmp, 'MC405')[0]
            self.assertEqual(sets[1].split('\n')[0], 'Staraptor (M) @ Staraptite')  # Team A has (F): the standard is male
            self.assertEqual(sets[5].split('\n')[0], 'Gholdengo @ Life Orb')  # and nothing for a genderless one
            again = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(again.returncode, 1)  # ids are never reused
            self.assertIn('ids are never reused', again.stderr.decode('utf-8'))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().split('\n\n')[1])
    NODE, CHECKOUT = sys.argv[1], sys.argv[2]
    unittest.main(argv=[sys.argv[0]])
