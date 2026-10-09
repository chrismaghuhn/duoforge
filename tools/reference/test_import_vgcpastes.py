"""duoforge.reference.import_vgcpastes: the bulk import of the VGCPastes Repository sheet, without Node or the library.

A made-up sheet (the HTML export's table form), made-up pastes, the stand-in pokedex of test_import_paste and a stand-in
for the engine's setup check: the rows, what each paste becomes (pool, pending, illegal), duplicates, the entries, and a
write into a copy of the registry.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

import import_vgcpastes as ivp  # noqa: E402
import team_registry as reg  # noqa: E402
import test_import_paste as tip  # noqa: E402  (its stand-in pokedex)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))


def cells(*values):
    return '<tr>' + ''.join('<td>%s</td>' % v for v in values) + '</tr>'


def sheet(rows):
    """The table of a tab as the export writes it: column letters, two banner rows, the header, then the teams."""
    header = ['3', 'Team ID', 'Team Description', '', 'Full Name', '', '1', '', '', '2', '', '', '3', '', '', '4', '', '',
              '5', '', '', '6', '', '', '', 'Pokepaste', 'EVs', 'Extracted paste?', 'Replica Status', 'Replica Code',
              'Date Shared', 'Tournament / Event', 'Rank']
    out = [cells('', 'A', 'B'), cells('1', '', 'VGCPastes Repository'), cells('2', 'Click here'), cells(*header)]
    for n, (tid, desc, creator, paste, evs, event, rank) in enumerate(rows, 4):
        link = '<a href="https://pokepast.es/%s">https://pokepast.es/%s</a>' % (paste, paste) if paste else ''
        values = [str(n), tid, desc, '', creator] + [''] * 20 + [link, evs, 'Extracted', 'X', 'None', '4 Oct 2026',
                                                                 event, rank]
        out.append(cells(*values))
    return '<table>' + ''.join(out) + '</table>'


def paste(names, evs=True):
    sets = []
    for name in names:
        lines = ['%s @ Sitrus Berry' % name, 'Ability: Pressure']
        if evs:
            lines.append('EVs: 32 HP / 2 Def / 32 SpD')
        lines += ['Calm Nature', '- Protect', '- Tackle']
        sets.append('\n'.join(lines))
    return '\n\n'.join(sets) + '\n'


TEAM1 = ['Rillaboom', 'Staraptor', 'Milotic', 'Ceruledge', 'Raichu', 'Gholdengo']
TEAM2 = ['Charizard', 'Salamence', 'Blissey', 'Vulpix', 'Staraptor', 'Milotic']
TEAM3 = ['Rillaboom', 'Raichu', 'Blissey', 'Vulpix', 'Gholdengo', 'Salamence']


def check_by_first(text):
    """The stand-in setup check: the first species of the team decides (Rillaboom pool, Charizard pending, else illegal)."""
    first = text.split(' ', 1)[0]
    if first == 'Rillaboom':
        return ('pool', None)
    if first == 'Charizard':
        return ('pending', ['move tackle (unsupported)'])
    return ('illegal', 'DUOFORGE_E_INVALID_ARGUMENT')


class SheetTest(unittest.TestCase):
    def test_rows_of_a_tab(self):
        text = sheet([('MC12', 'A team', 'Alice', 'aaaaaaaaaaaaaaaa', 'Yes', 'Recife Regional', 'Champion'),
                      ('MC11', 'No paste', 'Bob', None, 'Yes', '-', '-'),
                      ('', 'not a team row', '', None, '', '', '')])
        rows = ivp.sheet_rows(text, 'Champions M-C')
        self.assertEqual([r['team_id'] for r in rows], ['MC12', 'MC11'])
        r = rows[0]
        self.assertEqual((r['description'], r['creator'], r['paste_id'], r['evs'], r['event'], r['rank'], r['tab']),
                         ('A team', 'Alice', 'aaaaaaaaaaaaaaaa', 'Yes', 'Recife Regional', 'Champion', 'Champions M-C'))
        self.assertIsNone(rows[1]['paste_id'])


class DecideTest(unittest.TestCase):
    def rows(self, *specs):
        return [{'team_id': tid, 'description': 'd ' + tid, 'creator': 'c', 'paste_id': pid, 'evs': evs, 'event': '-',
                 'rank': '-', 'date': '4 Oct 2026', 'tab': tab} for tid, pid, evs, tab in specs]

    def test_pool_pending_illegal_and_no_evs(self):
        rows = self.rows(('MC3', 'a' * 16, 'Yes', 'Champions M-C'), ('MC2', 'b' * 16, 'Yes', 'Champions M-C'),
                         ('MC1', 'c' * 16, 'Yes', 'Champions M-C'), ('MC0', 'd' * 16, 'No', 'Champions M-C'),
                         ('MB9', 'e' * 16, 'Yes', 'Champions M-B'))
        pastes = {'a' * 16: paste(TEAM1), 'b' * 16: paste(TEAM2), 'c' * 16: paste(['Staraptor'] + TEAM1[1:]),
                  'd' * 16: paste(TEAM1), 'e' * 16: paste(TEAM3, evs=False)}
        out = {d['row']['team_id']: d for d in ivp.decide(rows, pastes, {}, tip.info_of, check_by_first)}
        self.assertEqual(out['MC3']['status'], 'pool')
        self.assertEqual(out['MC3']['id'], 'PP_' + 'A' * 16)
        self.assertEqual(out['MC2']['status'], 'pending')
        self.assertEqual(out['MC2']['blockers'], ['move tackle (unsupported)'])
        self.assertEqual(out['MC1']['status'], 'illegal')
        self.assertNotIn('MC0', out)  # the sheet says the paste has no EVs: not imported
        self.assertEqual(out['MB9']['status'], 'evs-missing')  # the sheet says Yes, a set has no EVs line

    def test_duplicates_keep_the_first(self):
        rows = self.rows(('MC5', 'a' * 16, 'Yes', 'Champions M-C'), ('MB5', 'f' * 16, 'Yes', 'Champions M-B'),
                         ('MB4', 'a' * 16, 'Yes', 'Champions M-B Featured Teams'))
        pastes = {'a' * 16: paste(TEAM1), 'f' * 16: paste(TEAM1)}  # the same team in two pastes
        out = ivp.decide(rows, pastes, {}, tip.info_of, check_by_first)
        by = {d['row']['team_id']: d for d in out}
        self.assertEqual(by['MC5']['status'], 'pool')
        self.assertEqual((by['MB5']['status'], by['MB5']['duplicate_of']), ('duplicate', 'PP_' + 'A' * 16))
        self.assertEqual(by['MB4']['status'], 'duplicate')  # the same paste again (a featured row)
        self.assertEqual(sum(d['status'] == 'pool' for d in out), 1)

    def test_a_team_the_registry_has_is_a_duplicate(self):
        sets, _ = ivp.normalized(paste(TEAM1), tip.info_of)
        known = {ivp.content_key(sets): 'LL_X_1'}
        out = ivp.decide(self.rows(('MC5', 'a' * 16, 'Yes', 'Champions M-C')), {'a' * 16: paste(TEAM1)}, known,
                         tip.info_of, check_by_first)
        self.assertEqual((out[0]['status'], out[0]['duplicate_of']), ('duplicate', 'LL_X_1'))

    def test_a_paste_id_the_registry_has_is_skipped(self):
        out = ivp.decide(self.rows(('MC5', 'a' * 16, 'Yes', 'Champions M-C')), {'a' * 16: paste(TEAM1)}, {},
                         tip.info_of, check_by_first, registry_ids={'PP_' + 'A' * 16})
        self.assertEqual(out[0]['status'], 'in-registry')

    def test_a_missing_paste_is_counted(self):
        out = ivp.decide(self.rows(('MC5', 'a' * 16, 'Yes', 'Champions M-C')), {}, {}, tip.info_of, check_by_first)
        self.assertEqual(out[0]['status'], 'not-fetched')

    def test_entry_names_the_source(self):
        rows = self.rows(('MC3', 'a' * 16, 'Yes', 'Champions M-C'))
        rows[0].update(event='Recife Regional 2027', rank='Champion', creator='Juan Salerno')
        d = ivp.decide(rows, {'a' * 16: paste(TEAM1)}, {}, tip.info_of, check_by_first)[0]
        e = ivp.entry_for(d, '2026-10-09')
        self.assertEqual(e['id'], 'PP_' + 'A' * 16)
        self.assertEqual(e['source'], {'url': 'https://pokepast.es/' + 'a' * 16, 'event': 'Recife Regional 2027',
                                       'placing': 'Champion'})
        self.assertIn('MC3', e['name'])
        for text in ('VGCPastes Repository', 'MC3', 'Juan Salerno', 'Champions M-C', '2026-10-09', 'gender'):
            self.assertIn(text, e['notes'])


class PendingTest(unittest.TestCase):
    def test_pending_list_has_no_paste_text(self):
        rows = DecideTest.rows(DecideTest(), ('MC2', 'b' * 16, 'Yes', 'Champions M-C'),
                               ('MC3', 'a' * 16, 'Yes', 'Champions M-C'))
        rows[0]['creator'] = 'Bob'
        decisions = ivp.decide(rows, {'a' * 16: paste(TEAM1), 'b' * 16: paste(TEAM2)}, {}, tip.info_of,
                               check_by_first)
        out = ivp.pending_list(decisions, '2026-10-09')
        self.assertEqual(out['date'], '2026-10-09')
        self.assertEqual([t['id'] for t in out['teams']], ['PP_' + 'B' * 16])
        t = out['teams'][0]
        self.assertEqual((t['url'], t['tab'], t['team_id'], t['creator'], t['blockers']),
                         ('https://pokepast.es/' + 'b' * 16, 'Champions M-C', 'MC2', 'Bob',
                          ['move tackle (unsupported)']))
        self.assertNotIn('Charizard', repr(out))  # no paste text, no species
        self.assertEqual(out['blocker_counts'], {'move tackle (unsupported)': 1})


class WriteTest(unittest.TestCase):
    def test_write_into_a_copy_of_the_registry(self):
        tmp = tempfile.mkdtemp(prefix='duoforge_ivp_')
        try:
            shutil.copytree(os.path.join(ROOT, 'data', 'teams'), os.path.join(tmp, 'data', 'teams'))
            rows = [{'team_id': 'MC3', 'description': 'd', 'creator': 'c', 'paste_id': 'a' * 16, 'evs': 'Yes',
                     'event': '-', 'rank': '-', 'date': '4 Oct 2026', 'tab': 'Champions M-C'}]
            decisions = ivp.decide(rows, {'a' * 16: paste(TEAM1)}, {}, tip.info_of, check_by_first)
            written = ivp.write(tmp, decisions, '2026-10-09')
            self.assertEqual(written, ['PP_' + 'A' * 16])
            self.assertIn('PP_' + 'A' * 16, [e['id'] for e in reg.entries(tmp)])
            self.assertEqual(reg.problems(tmp, lambda team_c: tip.tables(team_c)), [])
            with self.assertRaises(reg.RegistryError):  # ids are never reused: a second write refuses
                ivp.write(tmp, decisions, '2026-10-09')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
