#!/usr/bin/env python3
"""The team registry (data/teams, tools/reference/team_registry.py): the committed registry as it must be, and the checks
that say so on made-up ones. Python only, no Node and no Showdown checkout.

usage: python3 tools/reference/test_team_registry.py

CTest runs it as duoforge.reference.team_registry. What is held: every team of the index has its file and every file its
entry; the files are in the registry's form (the importer's), each with the SHA-256 that the index says (a team never
changes under its id: the learner refuses a changed file, and a correction is a new id); the entries have the keys, ids,
sources and supersessions that README.md of this directory documents; the gender of each Pokemon is as the converter
reads it; and the three teams that the registry starts with are copies of the files that other tests use.
"""
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import team_registry as reg  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
BASE = [e['id'] for e in reg.entries(ROOT)]  # the teams of the committed registry (a test that adds one expects them first)
OLD_FILES = {'A': os.path.join('tests', 'reference', 'teams', 'team_a.txt'),
             'B': os.path.join('tests', 'reference', 'teams', 'team_b.txt'),
             'C': os.path.join('docs', 'research', 'third-team', 'team-c.txt')}

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def read(path):
    with io.open(path, 'rb') as f:
        return f.read()


class Committed(unittest.TestCase):
    def test_the_registry_is_as_it_must_be(self):
        found = reg.problems(ROOT, tables)
        self.assertEqual(found, [], '\n'.join('%s: %s' % x for x in found))

    def test_it_starts_with_the_three_reference_teams_which_are_copies_of_the_files_other_tests_use(self):
        self.assertEqual([e['id'] for e in reg.entries(ROOT)][:3], ['A', 'B', 'C'])
        for team_id, old in OLD_FILES.items():
            with self.subTest(team_id):
                self.assertEqual(read(reg.team_path(ROOT, team_id)), read(os.path.join(ROOT, old)),
                                 '%s is a copy of %s, which stays (gen_real_specs and the tests read it)' % (team_id, old))

    def test_the_entries_of_the_three_teams(self):
        entries = {e['id']: e for e in reg.entries(ROOT)}
        self.assertEqual(entries['A']['source']['url'], 'https://pokepast.es/470a6ec2468af8a4')
        self.assertEqual(entries['B']['source']['url'], 'https://pokepast.es/7c9c0663ef60180e')
        self.assertEqual((entries['A']['name'], entries['B']['name']), ('Balt Top 8', 'Baltimore Regional Finalist'))
        self.assertEqual((entries['C']['source']['event'], entries['C']['source']['placing']), (None, None))
        for entry in entries.values():
            self.assertEqual(sorted(entry['source']), ['event', 'placing', 'url'])
            self.assertTrue(entry['notes'])  # each says where its genders are from

    def test_every_gender_is_stated_and_every_set_has_level_50(self):
        for entry in reg.entries(ROOT):
            sets = reg.read_team(ROOT, entry['id'])[0]
            self.assertEqual(len(sets), 6)
            for block in sets:
                lines = block.split('\n')
                head = reg.HEAD.match(lines[0])
                self.assertIsNotNone(head, lines[0])
                self.assertIn('Level: 50', lines)
                if head.group('species') not in ('Gholdengo',):  # the genderless one of these teams
                    self.assertIn(head.group('gender'), ('M', 'F'), lines[0])
                else:
                    self.assertIsNone(head.group('gender'))

    def test_the_index_is_written_as_the_registry_writes_it(self):
        self.assertEqual(read(reg.index_path(ROOT)), reg.dumps_index(reg.read_index(ROOT)))

    def test_the_hash_is_that_of_the_file(self):
        for entry in reg.entries(ROOT):
            self.assertEqual(entry['sha256'], reg.sha256_of(read(reg.team_path(ROOT, entry['id']))))
        # Pinned: the files of the three teams do not change under their ids (a correction is a new id).
        self.assertEqual({e['id']: e['sha256'] for e in reg.entries(ROOT)[:3]}, {
            'A': '4955f90d9f8650ef5e526fec4a2d5853fa1c98910c0a77c85084d9935977852f',
            'B': 'd936ae39ba48a382395e79b795ed8fe024370dcf5d72c4a736127219f0ec5300',
            'C': '4c625aff89a656e1e52ffe75e98d429d5f9f915aa17ba05dde6941a38004fd3b'})


class Made(unittest.TestCase):
    """Made-up registries: a copy of the committed one in a temporary directory, changed one way at a time."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        shutil.copytree(reg.registry_dir(ROOT), reg.registry_dir(self.root))

    def problems(self):
        return reg.problems(self.root, tables)

    def index(self):
        return reg.read_index(self.root)

    def write_index(self, index):
        with io.open(reg.index_path(self.root), 'wb') as f:
            f.write(reg.dumps_index(index))

    def write_team(self, team_id, data, rehash=True):
        with io.open(reg.team_path(self.root, team_id), 'wb') as f:
            f.write(data)
        if rehash:
            index = self.index()
            next(e for e in index['teams'] if e['id'] == team_id)['sha256'] = reg.sha256_of(data)
            self.write_index(index)

    def has(self, category, part):
        found = self.problems()
        self.assertTrue(any(c == category and part in m for c, m in found), found)
        return found

    def team_text(self, team_id='A'):
        return read(reg.team_path(self.root, team_id)).decode('utf-8')

    def test_a_copy_is_as_it_must_be(self):
        self.assertEqual(self.problems(), [])

    def test_what_is_wrong_with_the_index(self):
        index = self.index()
        for change, part in (
                (lambda i: i.update(registry=2), 'the keys of index.json'),
                (lambda i: i.update(extra=1), 'the keys of index.json'),
                (lambda i: i['teams'][0].update(extra='x'), 'has the keys'),
                (lambda i: i['teams'][0].pop('notes'), 'has the keys'),
                (lambda i: i['teams'].__setitem__(0, dict(reversed(list(i['teams'][0].items())))), 'in that order'),
                (lambda i: i['teams'][0].update(id='a'), 'upper case letter'),
                (lambda i: i['teams'][0].update(id='A-B'), 'upper case letter'),
                (lambda i: i['teams'][1].update(id='A'), 'in the index twice'),
                (lambda i: i['teams'][0].update(name=' '), 'the name'),
                (lambda i: i['teams'][0].update(notes=3), 'the notes'),
                (lambda i: i['teams'][0]['source'].update(extra='x'), 'the source'),
                (lambda i: i['teams'][0]['source'].update(url=4), 'the source'),
                (lambda i: i['teams'][0].update(sha256='abc'), 'the sha256'),
                (lambda i: i['teams'][0].update(superseded_by='NOPE'), 'superseded by')):
            with self.subTest(part):
                changed = copy.deepcopy(index)
                change(changed)
                self.write_index(changed)
                self.has('index', part) if part != 'in the index twice' else self.has('index', part)
        self.write_index(index)
        with io.open(reg.index_path(self.root), 'w') as f:
            f.write('[1, 2')
        self.assertEqual([c for c, _ in self.problems()], ['index'])
        os.remove(reg.index_path(self.root))
        self.assertEqual([c for c, _ in self.problems()], ['index'])

    def test_a_team_and_its_file_stand_together(self):
        os.remove(reg.team_path(self.root, 'B'))
        self.has('files', 'team B has no file B.txt')
        shutil.copy(reg.team_path(ROOT, 'B'), reg.team_path(self.root, 'B'))
        shutil.copy(reg.team_path(ROOT, 'B'), reg.team_path(self.root, 'ZZ'))
        self.has('files', 'ZZ.txt is in no entry')
        os.remove(reg.team_path(self.root, 'ZZ'))
        with io.open(os.path.join(reg.registry_dir(self.root), 'notes.md'), 'w') as f:
            f.write('x')
        self.has('files', 'notes.md')
        os.remove(os.path.join(reg.registry_dir(self.root), 'notes.md'))
        with io.open(os.path.join(reg.registry_dir(self.root), 'README.md'), 'w') as f:
            f.write('the one other file that is allowed')
        self.assertEqual(self.problems(), [])

    def test_a_crlf_copy_of_a_file_has_the_hash_of_the_lf_file(self):
        """The sha256 is that of the text with CRLF turned into LF: a checkout with Windows line ends is the same team."""
        for entry in reg.entries(self.root):
            data = read(reg.team_path(self.root, entry['id']))
            self.assertNotIn(b'\r', data)
            crlf = data.replace(b'\n', b'\r\n')
            self.assertEqual(reg.sha256_of(crlf), reg.sha256_of(data))
            self.assertEqual(reg.sha256_of(crlf), entry['sha256'])
            self.assertNotEqual(hashlib.sha256(crlf).hexdigest(), entry['sha256'])  # a hash of the bytes would differ
        self.write_team('A', read(reg.team_path(self.root, 'A')).replace(b'\n', b'\r\n'), rehash=False)
        found = self.problems()
        self.assertEqual([c for c, _ in found], ['form'])  # the hash holds; only the line ends are named
        self.assertIn('carriage returns', found[0][1])

    def test_a_file_that_changed_is_not_the_team_of_its_id(self):
        data = read(reg.team_path(self.root, 'A')).replace(b'Jolly', b'Timid')
        self.write_team('A', data, rehash=False)
        self.has('sha256', 'a team never changes under its id')
        self.write_team('A', data, rehash=True)  # the index brought into line: the form is still checked, not the history
        self.assertEqual(self.problems(), [])

    def test_the_form_of_a_paste(self):
        text = self.team_text('A')
        sets = text.rstrip('\n').split('\n\n')
        for label, changed, part in (
                ('carriage returns', text.replace('\n', '\r\n'), 'carriage returns'),
                ('no newline at the end', text.rstrip('\n'), 'exactly one newline'),
                ('a blank line at the end', text + '\n', 'exactly one newline'),
                ('five sets', '\n\n'.join(sets[:5]) + '\n', 'six sets'),
                ('no level', text.replace('Level: 50\n', '', 1), 'Level: 50'),
                ('level 100', text.replace('Level: 50', 'Level: 100', 1), 'Level: 50'),
                ('a line that is none of them', text.replace('Adamant Nature', 'Adamant Nature\nShiny: Yes', 1), 'then one to four'),
                ('IVs', text.replace('Adamant Nature', 'IVs: 0 Atk\nAdamant Nature', 1), 'nature line'),
                ('no ability', text.replace('Ability: Grassy Surge\n', '', 1), 'Ability'),
                ('five moves', text.replace('- Protect\n', '- Protect\n- Roar\n', 1), 'then one to four'),
                ('no moves', text.replace('- Wood Hammer\n- Grassy Glide\n- Fake Out\n- High Horsepower\n', '', 1), 'then one to four'),
                ('EVs of another kind', text.replace('EVs: 18 HP', 'EVs: eighteen HP', 1), 'EVs'),
                ('a first line that is none', text.replace('Rillaboom (M) @ Miracle Seed', '@ Miracle Seed', 1), 'first line'),
                ('a space at the end of a line', text.replace('Level: 50', 'Level: 50 ', 1), 'blank space')):
            with self.subTest(label):
                self.write_team('A', changed.encode('utf-8'))
                found = self.has('form', part)
                self.assertFalse(any(c == 'sha256' for c, _ in found))

    def test_the_gender_as_the_converter_reads_it(self):
        text = self.team_text('A')
        self.write_team('A', text.replace('Rillaboom (M)', 'Rillaboom', 1).encode('utf-8'))
        self.has('gender', 'Rillaboom has no gender')  # a species that has one: it is stated
        self.write_team('A', text.replace('Gholdengo @', 'Gholdengo (M) @', 1).encode('utf-8'))
        self.has('gender', 'Gholdengo cannot be (M)')  # one that has none: nothing is stated
    def test_a_name_that_the_tables_do_not_have_is_a_problem(self):
        """A team the converter cannot read is no registry team: the differential tools read every one. It is named, not
        skipped (before, such a team was checked for its form only, and a cosmetic forme slipped through)."""
        text = self.team_text('A')
        for label, changed, part in (
                ('species', text.replace('Rillaboom (M) @ Miracle Seed', 'Fakemon (M) @ Miracle Seed', 1), 'FAKEMON'),
                ('item', text.replace('Rillaboom (M) @ Miracle Seed', 'Rillaboom (M) @ Fake Item', 1), 'FAKEITEM'),
                ('move', text.replace('- Wood Hammer', '- Fake Move', 1), 'FAKEMOVE')):
            with self.subTest(label):
                self.write_team('A', changed.encode('utf-8'))
                found = self.has('names', part)
                self.assertEqual([c for c, _ in found], ['names'])
                self.assertIn("the converter's tables have no", found[0][1])


class Adding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        shutil.copytree(reg.registry_dir(ROOT), reg.registry_dir(self.root))
        self.sets = reg.read_team_file(reg.team_path(ROOT, 'A'))

    def entry(self, team_id, **kw):
        return reg.new_entry(team_id, kw.pop('name', 'A new team'), self.sets, **kw)

    def test_a_team_is_added_at_the_end_with_its_file(self):
        path = reg.add_team(self.root, self.entry('MC405', url='https://pokepast.es/x', event='E', placing='1st', notes='n'),
                            self.sets)
        self.assertEqual(path, reg.team_path(self.root, 'MC405'))
        self.assertEqual([e['id'] for e in reg.entries(self.root)], BASE + ['MC405'])
        new = reg.entries(self.root)[-1]
        self.assertEqual(list(new), ['id', 'name', 'source', 'notes', 'sha256'])
        self.assertEqual(new['sha256'], reg.sha256_of(read(path)))
        self.assertEqual(read(path), read(reg.team_path(ROOT, 'A')))  # the same sets: the same bytes
        self.assertEqual(reg.problems(self.root, tables), [])
        self.assertEqual(read(reg.index_path(self.root)), reg.dumps_index(reg.read_index(self.root)))
        # The first three are what they were, byte for byte.
        for team_id in 'ABC':
            self.assertEqual(read(reg.team_path(self.root, team_id)), read(reg.team_path(ROOT, team_id)))

    def test_an_id_is_never_used_again(self):
        for team_id in ('A', 'C'):
            with self.assertRaises(reg.RegistryError) as cm:
                reg.add_team(self.root, self.entry(team_id), self.sets)
            self.assertIn('ids are never reused', str(cm.exception))
        # Not even one whose entry was lost but whose file is there.
        shutil.copy(reg.team_path(ROOT, 'A'), reg.team_path(self.root, 'LOST'))
        with self.assertRaises(reg.RegistryError):
            reg.add_team(self.root, self.entry('LOST'), self.sets)

    def test_what_an_id_is(self):
        for bad in ('a', 'mc405', '1A', 'A-B', 'A B', '', 'A' * 33, '_A'):
            with self.subTest(bad), self.assertRaises(reg.RegistryError):
                reg.add_team(self.root, self.entry(bad), self.sets)
        for good in ('Z', 'MC405', 'A_1', 'A' * 32):
            reg.add_team(self.root, self.entry(good), self.sets)
        self.assertEqual(reg.problems(self.root, tables), [])

    def test_a_correction_is_a_new_team_that_supersedes_the_old(self):
        before = read(reg.team_path(self.root, 'B'))
        reg.add_team(self.root, self.entry('B2', name='B, corrected'), self.sets, supersedes='B')
        entries = {e['id']: e for e in reg.entries(self.root)}
        self.assertEqual(entries['B']['superseded_by'], 'B2')
        self.assertEqual(list(entries['B']), ['id', 'name', 'source', 'notes', 'sha256', 'superseded_by'])
        self.assertNotIn('superseded_by', entries['B2'])
        self.assertEqual(read(reg.team_path(self.root, 'B')), before)  # the old file stays, as it was
        self.assertEqual(reg.problems(self.root, tables), [])
        with self.assertRaises(reg.RegistryError) as cm:
            reg.add_team(self.root, self.entry('B3'), self.sets, supersedes='B')
        self.assertIn('superseded by B2 already', str(cm.exception))
        with self.assertRaises(reg.RegistryError):
            reg.add_team(self.root, self.entry('B4'), self.sets, supersedes='NOPE')
        self.assertEqual([e['id'] for e in reg.entries(self.root)], BASE + ['B2'])  # nothing changed by the failures

    def test_a_team_has_six_sets(self):
        with self.assertRaises(reg.RegistryError):
            reg.add_team(self.root, self.entry('FIVE'), self.sets[:5])
        self.assertFalse(os.path.exists(reg.team_path(self.root, 'FIVE')))

    def test_a_failure_while_the_index_is_written_leaves_the_registry_as_it_was(self):
        before = {f: read(os.path.join(reg.registry_dir(self.root), f)) for f in os.listdir(reg.registry_dir(self.root))}
        with unittest.mock.patch.object(reg, 'replace_file', side_effect=OSError('disk full')), \
                self.assertRaises(OSError):
            reg.add_team(self.root, self.entry('MC405'), self.sets, supersedes='B')
        after = {f: read(os.path.join(reg.registry_dir(self.root), f)) for f in os.listdir(reg.registry_dir(self.root))}
        self.assertEqual(after, before)  # no file without its entry, no lock left, no index changed
        self.assertEqual(reg.problems(self.root, tables), [])
        reg.add_team(self.root, self.entry('MC405'), self.sets)  # and the id is free

    def test_the_index_is_replaced_whole(self):
        reg.add_team(self.root, self.entry('MC405'), self.sets)
        self.assertEqual(sorted(os.listdir(reg.registry_dir(self.root))),
                         sorted([i + '.txt' for i in BASE] + ['MC405.txt', 'README.md', 'index.json']))  # no .tmp, no .lock left

    def test_one_writer_at_a_time(self):
        lock = os.path.join(reg.registry_dir(self.root), '.lock')
        os.mkdir(lock)  # another import is writing
        before = read(reg.index_path(self.root))
        slept = []
        with unittest.mock.patch.object(reg.time, 'sleep', slept.append), self.assertRaises(reg.RegistryError) as cm:
            reg.add_team(self.root, self.entry('MC405'), self.sets)
        self.assertIn('is held', str(cm.exception))
        self.assertGreater(len(slept), 10)  # it waited, then gave up
        self.assertEqual(read(reg.index_path(self.root)), before)
        self.assertTrue(os.path.isdir(lock))  # the lock of the other writer is not ours to remove
        os.rmdir(lock)
        reg.add_team(self.root, self.entry('MC405'), self.sets)

    def test_a_file_that_appeared_meanwhile_is_not_written_over(self):
        original = reg.check_new

        def check_then_appear(root, team_id, supersedes=None):
            index = original(root, team_id, supersedes)
            with io.open(reg.team_path(root, team_id), 'wb') as f:  # the race: the file is made after the check
                f.write(b'someone else')
            return index
        with unittest.mock.patch.object(reg, 'check_new', check_then_appear), self.assertRaises(reg.RegistryError):
            reg.add_team(self.root, self.entry('MC405'), self.sets)
        self.assertEqual(read(reg.team_path(self.root, 'MC405')), b'someone else')
        self.assertEqual([e['id'] for e in reg.entries(self.root)], BASE)

    def test_a_registry_is_made_where_there_is_none(self):
        with tempfile.TemporaryDirectory() as empty:
            reg.add_team(empty, self.entry('FIRST'), self.sets)
            self.assertEqual([e['id'] for e in reg.entries(empty)], ['FIRST'])
            self.assertEqual(reg.problems(empty, tables), [])

    def test_the_entry_and_the_sets(self):
        self.assertEqual(reg.get_entry(ROOT, 'B')['name'], 'Baltimore Regional Finalist')
        with self.assertRaises(reg.RegistryError) as cm:
            reg.get_entry(ROOT, 'NOPE')
        self.assertIn('ids are A, B, C', str(cm.exception))
        sets, path = reg.read_team(ROOT, 'C')
        self.assertEqual((len(sets), path), (6, reg.team_path(ROOT, 'C')))
        self.assertEqual(reg.file_text(sets), read(reg.team_path(ROOT, 'C')))
        self.assertEqual(reg.team_sha256(sets), reg.team_sha256(reg.split_sets(read(reg.team_path(ROOT, 'C')).decode('utf-8')
                                                                                .replace('\n', '\r\n') + '\r\n\r\n')))


if __name__ == '__main__':
    unittest.main()
