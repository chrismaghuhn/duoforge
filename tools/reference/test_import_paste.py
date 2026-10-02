#!/usr/bin/env python3
"""The paste importer (tools/reference/import_paste.py) without Node: what it normalises, what it refuses, what it writes.

usage: python3 tools/reference/test_import_paste.py

CTest runs it as duoforge.reference.import_paste. The pokedex is a stand-in with the facts of the species the tests ask
about, in the shape tools/reference/ps_species.js writes them (a stand-in for the Node run, so the importer's own reading of
the answers and of a failing script is tested as well), and the registry is a copy in a temporary directory. The pinned
Showdown answers in test_import_paste_pin.py.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import import_paste as imp  # noqa: E402
import team_registry as reg  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SpeciesInfo = imp.SpeciesInfo  # the real class: main() is run with one that asks the stand-in

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def species(name, gender='', ratio=(0.5, 0.5), base=None, mega_of=None, stone=None):
    """The facts of one species as ps_species.js writes them."""
    return {'exists': True, 'name': name, 'baseSpecies': base or name, 'forme': '', 'gender': gender,
            'genderRatio': {'M': ratio[0], 'F': ratio[1]}, 'isMega': mega_of is not None, 'requiredItem': stone,
            'battleOnly': mega_of}


DEX = {s['name']: s for s in (
    species('Rillaboom', ratio=(0.875, 0.125)), species('Staraptor'), species('Milotic'), species('Ceruledge'),
    species('Raichu'), species('Gholdengo', gender='N', ratio=(0, 0)), species('Vulpix', ratio=(0.25, 0.75)),
    species('Charizard', ratio=(0.875, 0.125)),
    species('Charizard-Mega-Y', ratio=(0.875, 0.125), base='Charizard', mega_of='Charizard', stone='Charizardite Y'),
    species('Salamence'), species('Salamence-Mega', base='Salamence', mega_of='Salamence', stone='Salamencite'),
    species('Orphaned-Mega', base='Orphan', mega_of='Orphan', stone='Orphanite'),
    species('Indeedee', gender='M', ratio=(1, 0)),
    species('Indeedee-F', gender='F', ratio=(0, 1), base='Indeedee'), species('Blissey', gender='F', ratio=(0, 1)))}
BY_ID = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in DEX.items()}


def info_of(name):
    """The stand-in pokedex: case does not matter, as in the real one; None for a species it does not have."""
    return BY_ID.get(re.sub(r'[^a-z0-9]', '', name.lower()))


def fake_script(calls=None):
    """A stand-in for `node ps_species.js <checkout> <format>`: reads the names on stdin, writes the facts of the stand-in
    pokedex for them as the script does (a species it does not have as `exists: false`)."""
    def run(command, input=None, stdout=None, stderr=None):
        names = json.loads(input.decode('utf-8'))
        if calls is not None:
            calls.append((command, names))
        out = {name: info_of(name) or dict(species(name.lower()), exists=False) for name in names}
        return subprocess.CompletedProcess(command, 0, json.dumps(out).encode('utf-8'), b'')
    return run


def set_text(head='Rillaboom (M) @ Miracle Seed', ability='Grassy Surge', level='Level: 50', evs='EVs: 18 HP / 32 Atk',
             nature='Adamant Nature', moves=('Wood Hammer', 'Fake Out'), extra=()):
    """The text of one set in the registry's form; a part that is None (or empty, for the level and the EVs) is left out."""
    lines = [head]
    if ability is not None:
        lines.append('Ability: %s' % ability)
    if level:
        lines.append(level)
    if evs:
        lines.append(evs)
    if nature is not None:
        lines.append(nature)
    lines += list(extra)
    lines += ['- %s' % m for m in moves]
    return '\n'.join(lines)


def paste(*blocks):
    """A paste of six sets: the given ones, then Gholdengo (genderless, so nothing to report) to fill the team."""
    sets = list(blocks) + [set_text('Gholdengo @ Life Orb', ability='Good as Gold')] * (6 - len(blocks))
    return '\n\n'.join(sets) + '\n'


def read_bytes(path):
    with io.open(path, 'rb') as f:
        return f.read()


class Normalising(unittest.TestCase):
    def normalize(self, text):
        return imp.normalize(text, info_of)

    def refused(self, text):
        with self.assertRaises(imp.PasteError) as cm:
            self.normalize(text)
        return cm.exception.problems

    def test_a_paste_in_the_registry_form_is_unchanged_and_says_nothing(self):
        sets, notes = self.normalize(paste(set_text(), set_text('Staraptor (F) @ Staraptite', ability='Intimidate')))
        self.assertEqual(notes, [])
        self.assertEqual(sets[0], set_text())
        self.assertEqual(sets[1], set_text('Staraptor (F) @ Staraptite', ability='Intimidate'))
        self.assertEqual(reg.team_problems(reg.file_text(sets).decode('utf-8'), tables), [])

    def test_a_gender_that_is_not_stated_is_added_by_the_owners_standard_and_reported(self):
        text = paste(set_text('Rillaboom @ Miracle Seed'), set_text('Staraptor @ Staraptite', ability='Intimidate'),
                     set_text('Blissey @ Leftovers', ability='Natural Cure'),
                     set_text('Vulpix', ability='Flash Fire', moves=('Ember',)),
                     set_text('Gholdengo @ Life Orb', ability='Good as Gold'),
                     set_text('Indeedee-F @ Rocky Helmet', ability='Psychic Surge'))
        sets, notes = self.normalize(text)
        self.assertEqual([s.split('\n')[0] for s in sets],
                         ['Rillaboom (M) @ Miracle Seed', 'Staraptor (M) @ Staraptite', 'Blissey (F) @ Leftovers', 'Vulpix (M)',
                          'Gholdengo @ Life Orb', 'Indeedee-F (F) @ Rocky Helmet'])
        self.assertEqual(notes, [  # male for Vulpix whatever its ratio; none for Gholdengo, which has no gender
            "set 1: gender (M) added to Rillaboom: the species can be either (M 87.5%, F 12.5%), the owner's standard is male",
            "set 2: gender (M) added to Staraptor: the species can be either (M 50%, F 50%), the owner's standard is male",
            'set 3: gender (F) added to Blissey: the species is always F',
            "set 4: gender (M) added to Vulpix: the species can be either (M 25%, F 75%), the owner's standard is male",
            'set 6: gender (F) added to Indeedee-F: the species is always F'])

    def test_a_gender_that_is_stated_is_kept_and_one_that_cannot_be_is_an_error(self):
        sets, notes = self.normalize(paste(set_text('Rillaboom (F) @ Miracle Seed')))
        self.assertEqual((sets[0].split('\n')[0], notes), ('Rillaboom (F) @ Miracle Seed', []))  # the paste decides
        for head, part in (('Blissey (M) @ Leftovers', 'Blissey is always F, the paste states (M)'),
                           ('Gholdengo (M) @ Life Orb', 'Gholdengo has no gender, the paste states (M)'),
                           ('Indeedee (F)', 'Indeedee is always M, the paste states (F)')):
            with self.subTest(head):
                self.assertTrue(any(part in p for p in self.refused(paste(set_text(head)))), part)

    def test_a_mega_forme_with_its_stone_is_the_base_forme_with_the_stone(self):
        sets, notes = self.normalize(paste(set_text('Charizard-Mega-Y @ Charizardite Y'),
                                           set_text('Salamence-Mega (F) @ Salamencite', ability='Intimidate')))
        self.assertEqual([s.split('\n')[0] for s in sets[:2]], ['Charizard (M) @ Charizardite Y', 'Salamence (F) @ Salamencite'])
        self.assertEqual(len(notes), 3)  # two mappings, and the gender of Charizard (Salamence states its own)
        self.assertTrue(notes[0].startswith('set 1: Charizard-Mega-Y @ Charizardite Y is written as Charizard @ Charizardite Y'))
        self.assertIn('gender (M) added to Charizard: the species can be either', notes[1])  # the gender is the base forme's
        self.assertTrue(notes[2].startswith('set 2: Salamence-Mega @ Salamencite is written as Salamence @ Salamencite'))
        # Without its stone, or with another item, it is an error: nothing is made up.
        for head in ('Charizard-Mega-Y', 'Charizard-Mega-Y @ Leftovers', 'Charizard-Mega-Y @ Charizardite X'):
            with self.subTest(head):
                self.assertTrue(any('needs its stone Charizardite Y' in p for p in self.refused(paste(set_text(head)))))
        # A base forme with its stone is written as it is; a Mega forme whose base forme the pokedex does not have is an error.
        self.assertEqual(self.normalize(paste(set_text('Charizard (M) @ Charizardite Y')))[1], [])
        self.assertTrue(any('the base forme' in p and 'not in the pokedex' in p
                            for p in self.refused(paste(set_text('Orphaned-Mega @ Orphanite')))))

    def test_a_nickname_and_the_spelling_of_the_species(self):
        sets, notes = self.normalize(paste(set_text('Sunny (Rillaboom) (M) @ Miracle Seed'), set_text('rillaboom (M)')))
        self.assertEqual([s.split('\n')[0] for s in sets[:2]], ['Rillaboom (M) @ Miracle Seed', 'Rillaboom (M)'])
        self.assertEqual(notes, ["set 1 (Rillaboom): the nickname 'Sunny' is dropped",
                                 "set 2: 'rillaboom' is written as the pokedex spells it, Rillaboom"])
        sets, notes = self.normalize(paste(set_text('Sunny (Rillaboom)')))  # no gender stated: the nickname must not hide it
        self.assertEqual(sets[0].split('\n')[0], 'Rillaboom (M)')
        self.assertEqual(len(notes), 2)  # the nickname and the gender

    def test_the_names_to_ask_the_pokedex_for_are_the_species_as_written(self):
        text = paste(set_text('Sunny (Rillaboom) (M) @ Miracle Seed'), set_text('Charizard-Mega-Y @ Charizardite Y'),
                     set_text('rillaboom'))
        self.assertEqual(imp.species_of_paste(text), ['Rillaboom', 'Charizard-Mega-Y', 'rillaboom'] + ['Gholdengo'] * 3)

    def test_level_50_is_added_and_no_other_level_is_accepted(self):
        sets, notes = self.normalize(paste(set_text(level=None)))
        self.assertIn('Level: 50', sets[0].split('\n'))
        self.assertEqual(notes, ['set 1 (Rillaboom): "Level: 50" added'])
        self.assertEqual(self.normalize(paste(set_text(level='Level: 50')))[1], [])
        self.assertTrue(any('Level 100: the registry is Level 50' in p
                            for p in self.refused(paste(set_text(level='Level: 100')))))

    def test_the_cosmetic_lines_are_dropped_and_reported_and_nothing_else_is(self):
        sets, notes = self.normalize(paste(set_text(extra=('Shiny: Yes', 'Happiness: 0', 'Tera Type: Fire'))))
        self.assertEqual(notes, ["set 1 (Rillaboom): dropped the cosmetic line 'Shiny: Yes'",
                                 "set 1 (Rillaboom): dropped the cosmetic line 'Happiness: 0'",
                                 "set 1 (Rillaboom): dropped the cosmetic line 'Tera Type: Fire'"])
        self.assertEqual(sets[0], set_text())
        for line in ('IVs: 0 Atk', 'Gigantamax: Yes', 'Dynamax Level: 5', 'Pokeball: Great Ball', 'Hidden Power: Fire',
                     'Shiny', 'Hapiness: 0'):
            with self.subTest(line):
                problems = self.refused(paste(set_text(extra=(line,))))
                self.assertTrue(any('unknown line %r' % line in p and 'nothing is dropped silently' in p for p in problems),
                                problems)

    def test_a_line_that_a_set_has_once_is_not_accepted_twice(self):
        for extra, field in ((('Ability: Grassy Surge',), 'ability'), (('Level: 50',), 'level'), (('EVs: 2 HP',), 'evs'),
                             (('Jolly Nature',), 'nature')):
            with self.subTest(field):
                problems = self.refused(paste(set_text(extra=extra)))
                self.assertTrue(any('a second %s line' % field in p and 'nothing is dropped silently' in p for p in problems),
                                problems)

    def test_the_lines_are_put_in_the_registry_order(self):
        scrambled = '\n'.join(['Rillaboom @ Miracle Seed', '- Wood Hammer', 'Adamant Nature', 'EVs: 18 HP / 32 Atk',
                               'Level: 50', 'Ability: Grassy Surge', '- Fake Out'])
        sets, notes = self.normalize(paste(scrambled))
        self.assertEqual(sets[0], set_text('Rillaboom (M) @ Miracle Seed'))
        self.assertEqual(len(notes), 1)  # only the gender: the order is no content

    def test_everything_that_is_wrong_is_listed_together(self):
        text = paste(set_text('Fakemon (M)'), set_text(ability=None), set_text(nature='Adamant'), set_text(moves=()),
                     set_text(moves=('A', 'B', 'C', 'D', 'E')), set_text(evs='EVs: lots'))
        problems = self.refused(text)
        wants = ("set 1: unknown species 'Fakemon'", 'set 2 (Rillaboom): no "Ability: Name" line',
                 "set 3 (Rillaboom): unknown line 'Adamant'", 'set 3 (Rillaboom): no nature line',
                 'set 4 (Rillaboom): 0 moves, one to four are needed', 'set 5 (Rillaboom): 5 moves, one to four are needed',
                 'set 6 (Rillaboom): not an EVs line')
        for want in wants:
            self.assertTrue(any(want in p for p in problems), (want, problems))
        self.assertEqual(self.refused('\n\n'.join([set_text()] * 5)), ['a team has six sets, the paste has 5'])
        self.assertEqual(self.refused('\n\n'.join([set_text()] * 7)), ['a team has six sets, the paste has 7'])

    def test_windows_line_ends_and_extra_blank_lines_are_no_difference(self):
        text = paste(set_text(), set_text('Staraptor (F) @ Staraptite', ability='Intimidate'))
        crlf = text.replace('\n', '\r\n').replace('\r\n\r\n', '\r\n  \r\n\r\n\r\n')
        self.assertEqual(self.normalize(crlf), self.normalize(text))


class SpeciesQueries(unittest.TestCase):
    """SpeciesInfo: what it asks the script and what it makes of the answer."""

    def test_each_name_is_asked_once_and_a_batch_is_one_run(self):
        calls = []
        infos = SpeciesInfo('checkout', 'node-x', run=fake_script(calls))
        infos.prefetch(['Rillaboom', 'Staraptor', 'Rillaboom'])
        infos.prefetch(['Rillaboom'])  # nothing new: no run
        self.assertEqual(infos.get('Staraptor')['name'], 'Staraptor')  # remembered: no run
        self.assertEqual(len(calls), 1)
        command, names = calls[0]
        self.assertEqual((command[0], command[2], command[3], names), ('node-x', 'checkout', imp.FORMAT, ['Rillaboom', 'Staraptor']))
        self.assertEqual(os.path.basename(command[1]), 'ps_species.js')
        self.assertEqual(infos.get('Vulpix')['name'], 'Vulpix')  # a name that was not asked for: one more run, for it alone
        self.assertEqual([names for _, names in calls], [['Rillaboom', 'Staraptor'], ['Vulpix']])

    def test_a_species_the_pokedex_does_not_have_is_there_and_does_not_exist(self):
        self.assertFalse(SpeciesInfo('checkout', run=fake_script()).get('Fakemon')['exists'])

    def test_a_script_that_fails_or_a_node_that_is_missing_is_an_error_with_the_reason(self):
        def failing(command, input=None, stdout=None, stderr=None):
            return subprocess.CompletedProcess(command, 2, b'', 'ps_species: dist/sim/dex.js not found\n'.encode('utf-8'))

        def missing(command, input=None, stdout=None, stderr=None):
            raise FileNotFoundError(2, 'No such file or directory')
        with self.assertRaises(imp.PasteError) as cm:
            SpeciesInfo('checkout', run=failing).get('Rillaboom')
        self.assertEqual(cm.exception.problems, ['ps_species.js failed (status 2): ps_species: dist/sim/dex.js not found'])
        with self.assertRaises(imp.PasteError) as cm:
            SpeciesInfo('checkout', 'no-node', run=missing).get('Rillaboom')
        self.assertTrue(cm.exception.problems[0].startswith('cannot run node (no-node): '))


class Writing(unittest.TestCase):
    """The command line, with the stand-in pokedex and a registry in a temporary directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        shutil.copytree(reg.registry_dir(ROOT), reg.registry_dir(self.root))
        os.makedirs(os.path.join(self.root, 'dist', 'sim'))  # what --checkout must have
        self.paste = os.path.join(self.root, 'paste.txt')
        self.write_paste(paste(set_text('Rillaboom @ Miracle Seed'), set_text('Charizard-Mega-Y @ Charizardite Y'),
                               set_text('Sunny (Staraptor) @ Staraptite', ability='Intimidate', level=None,
                                        extra=('Shiny: Yes',))))
        patch = unittest.mock.patch.object(
            imp, 'SpeciesInfo', lambda checkout, node='node': SpeciesInfo(checkout, node, run=fake_script()))
        patch.start()
        self.addCleanup(patch.stop)

    def write_paste(self, text):
        with io.open(self.paste, 'w', encoding='utf-8', newline='') as f:
            f.write(text)

    def run_main(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if stdin is None:
                status = imp.main(['--checkout', self.root, '--root', self.root, '--paste', self.paste] + list(argv))
            else:
                reader = io.TextIOWrapper(io.BytesIO(stdin.encode('utf-8')), encoding='utf-8')
                with unittest.mock.patch.object(sys, 'stdin', reader):
                    status = imp.main(['--checkout', self.root, '--root', self.root, '--paste', '-'] + list(argv))
        return status, out.getvalue(), err.getvalue()

    def team_files(self):
        return {f: read_bytes(reg.team_path(self.root, f)) for f in 'ABC'}

    def test_a_team_is_imported_with_its_entry_and_every_change_is_reported(self):
        before = self.team_files()
        status, out, err = self.run_main('--id', 'MC405', '--name', 'A real team', '--url', 'https://pokepast.es/x',
                                         '--event', 'Regional', '--placing', '2nd', '--notes', 'imported')
        self.assertEqual((status, err), (0, ''))
        lines = out.strip().split('\n')
        self.assertTrue(all(line.startswith('import_paste: ') for line in lines), lines)
        wanted = ('gender (M) added to Rillaboom', 'Charizard-Mega-Y @ Charizardite Y is written as Charizard @ Charizardite Y',
                  'gender (M) added to Charizard', "the nickname 'Sunny' is dropped", 'gender (M) added to Staraptor',
                  '"Level: 50" added', "dropped the cosmetic line 'Shiny: Yes'")
        for part in wanted:
            self.assertEqual(sum(part in line for line in lines), 1, (part, lines))  # one line for each change
        self.assertEqual(len(lines), len(wanted) + 1)  # and the last says what was written
        self.assertIn('wrote data', lines[-1].replace('\\', '/'))
        self.assertIn('%d changes' % len(wanted), lines[-1])
        entry = reg.get_entry(self.root, 'MC405')
        self.assertEqual((entry['name'], entry['source'], entry['notes']),
                         ('A real team', {'url': 'https://pokepast.es/x', 'event': 'Regional', 'placing': '2nd'}, 'imported'))
        data = read_bytes(reg.team_path(self.root, 'MC405'))
        self.assertEqual(entry['sha256'], reg.sha256_of(data))
        self.assertEqual(reg.problems(self.root, tables), [])  # a registry as the registry must be
        self.assertEqual(self.team_files(), before)  # the others untouched
        sets = reg.read_team(self.root, 'MC405')[0]
        self.assertEqual(sets[1].split('\n')[0], 'Charizard (M) @ Charizardite Y')
        self.assertEqual(data, reg.file_text(sets))  # the form the registry has
        self.assertEqual([e['id'] for e in reg.entries(self.root)], ['A', 'B', 'C', 'MC405'])

    def test_a_paste_from_stdin_and_the_defaults_of_the_entry(self):
        status, out, err = self.run_main('--id', 'S1', '--name', 'From stdin', stdin=read_bytes(self.paste).decode('utf-8'))
        self.assertEqual((status, err), (0, ''))
        entry = reg.get_entry(self.root, 'S1')
        self.assertEqual((entry['source'], entry['notes']), ({'url': None, 'event': None, 'placing': None}, ''))
        self.assertEqual(reg.problems(self.root, tables), [])

    def test_a_dry_run_reports_and_writes_nothing_and_print_shows_the_file(self):
        before = read_bytes(reg.index_path(self.root))
        status, out, _ = self.run_main('--id', 'MC405', '--name', 'x', '--dry-run', '--print')
        self.assertEqual(status, 0)
        self.assertIn('Charizard (M) @ Charizardite Y\nAbility: ', out)
        self.assertIn('import_paste: dry run: would write data/teams/MC405.txt', out)
        self.assertFalse(os.path.exists(reg.team_path(self.root, 'MC405')))
        self.assertEqual(read_bytes(reg.index_path(self.root)), before)

    def test_an_id_that_is_used_is_refused_with_nothing_written(self):
        before = read_bytes(reg.index_path(self.root))
        status, out, err = self.run_main('--id', 'B', '--name', 'x')
        self.assertEqual((status, out), (1, ''))
        self.assertIn('team B is in the registry already: ids are never reused', err)
        self.assertIn('nothing written', err)
        self.assertEqual(read_bytes(reg.index_path(self.root)), before)
        status, _, err = self.run_main('--id', 'mc 405', '--name', 'x')
        self.assertEqual(status, 1)
        self.assertIn('is no team id', err)
        with io.open(reg.team_path(self.root, 'ZZ'), 'wb') as f:  # a file without an entry is not a free id
            f.write(b'x')
        self.assertEqual(self.run_main('--id', 'ZZ', '--name', 'x')[0], 1)
        os.remove(reg.team_path(self.root, 'C'))  # nor is an entry without its file
        self.assertEqual(self.run_main('--id', 'C', '--name', 'x')[0], 1)
        self.assertEqual(read_bytes(reg.index_path(self.root)), before)

    def test_a_correction_is_a_new_id_that_supersedes_the_old(self):
        status, _, _ = self.run_main('--id', 'B2', '--name', 'B, corrected', '--supersedes', 'B')
        self.assertEqual(status, 0)
        self.assertEqual(reg.get_entry(self.root, 'B')['superseded_by'], 'B2')
        self.assertNotIn('superseded_by', reg.get_entry(self.root, 'B2'))
        self.assertEqual(read_bytes(reg.team_path(self.root, 'B')), read_bytes(reg.team_path(ROOT, 'B')))  # B itself unchanged
        self.assertEqual(reg.problems(self.root, tables), [])
        status, _, err = self.run_main('--id', 'B3', '--name', 'x', '--supersedes', 'NOPE')
        self.assertEqual(status, 1)
        self.assertIn('--supersedes NOPE: no such team', err)
        status, _, err = self.run_main('--id', 'B4', '--name', 'x', '--supersedes', 'B')
        self.assertEqual(status, 1)
        self.assertIn('team B is superseded by B2 already', err)

    def test_a_paste_that_cannot_be_imported_lists_its_problems_and_writes_nothing(self):
        self.write_paste(paste(set_text('Fakemon (M)'), set_text(extra=('IVs: 0 Atk',))))
        before = read_bytes(reg.index_path(self.root))
        status, out, err = self.run_main('--id', 'BAD', '--name', 'x')
        self.assertEqual((status, out), (1, ''))
        self.assertIn("unknown species 'Fakemon'", err)
        self.assertIn("unknown line 'IVs: 0 Atk'", err)
        self.assertFalse(os.path.exists(reg.team_path(self.root, 'BAD')))
        self.assertEqual(read_bytes(reg.index_path(self.root)), before)

    def test_a_checkout_that_is_not_built_is_a_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            imp.main(['--checkout', os.path.join(self.root, 'nowhere'), '--root', self.root, '--paste', self.paste, '--id', 'X',
                      '--name', 'x'])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('has no dist/sim', err.getvalue())


if __name__ == '__main__':
    unittest.main()
