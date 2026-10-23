"""tools/restructure: fn_diff's normalisation and clone groups, callgrind_gate's parser and clone sums, and the rules of
test_audit's rename table, offline."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import callgrind_gate  # noqa: E402
import fn_diff  # noqa: E402
import rename_tests  # noqa: E402
import test_audit  # noqa: E402

# A callgrind file in the tool's own format (positions: line, events: Ir, name compression): main calls the two clones
# of f, the .part clone of f is called from f itself, and f.lto_priv.0 calls g. Self Ir: main 5, f 20 + 30 + 7, g 40.
CALLGRIND = """# callgrind format
version: 1
positions: line
events: Ir
summary: 102

ob=(1) /bin/bench
fl=(1) ???
fn=(1) main
0 5
cfn=(2) f.lto_priv.0
calls=2 0
0 90
cfn=(4) f.cold
calls=1 0
0 7

fn=(2)
0 20
cfn=(3) f.part.0
calls=1 0
0 30
cfn=(5) g
calls=3 0
0 40

fn=(3)
+1 30

fn=(4)
* 7

fn=(5)
0 40
"""


class Tools(unittest.TestCase):
    def test_base(self):
        self.assertEqual(fn_diff.base('dfi_get_damage.lto_priv.0'), 'dfi_get_damage')
        self.assertEqual(fn_diff.base("dfi_boost.isra.0'2"), 'dfi_boost')
        self.assertEqual(fn_diff.base('dfi_lum_cure.lto_priv.0.cold'), 'dfi_lum_cure')
        self.assertEqual(fn_diff.base('memcpy@plt'), 'memcpy@plt')

    def test_normalise(self):
        self.assertEqual(fn_diff.normalise('call   4d5d5 <dfi_event_make>'), 'call   <dfi_event_make>')
        self.assertEqual(fn_diff.normalise('lea    0x763e9(%rip),%rax        # 90af4 <_fini+0x6158>'), 'lea    RIP,%rax')
        self.assertEqual(fn_diff.normalise('lea    0x10(%rip),%rdx        # 1a0 <CSWTCH.1025>'), 'lea    RIP,%rdx')
        self.assertEqual(fn_diff.CLONE.sub('', 'call   <dfi_lum_cure.lto_priv.0>'), 'call   <dfi_lum_cure>')
        self.assertEqual(fn_diff.CLONE.sub('', 'dfi_lum_cure.lto_priv.0.cold'), 'dfi_lum_cure.cold')

    def test_parse_and_groups(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.callgrind')
            with open(path, 'w') as f:
                f.write(CALLGRIND)
            total, self_ir, calls = callgrind_gate.parse(path)
        self.assertEqual(total, 102)
        self.assertEqual(self_ir, {'main': 5, 'f.lto_priv.0': 20, 'f.part.0': 30, 'f.cold': 7, 'g': 40})
        excl, incl = callgrind_gate.groups(self_ir, calls)
        self.assertEqual(excl['f'], 57)  # every clone's own Ir
        self.assertEqual(incl['f'], 97)  # plus its call of g; the call of f.part.0 from f is not counted twice
        self.assertEqual(incl['main'], 102)

    def test_analyse_names_the_moved_cost(self):
        moved = CALLGRIND.replace('summary: 102', 'summary: 112').replace('fn=(5)\n0 40', 'fn=(5)\n0 50') \
            .replace('calls=3 0\n0 40', 'calls=3 0\n0 50').replace('0 90', '0 100')
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, 'a'), os.path.join(d, 'b')
            for p, text in ((a, CALLGRIND), (b, moved)):
                with open(p, 'w') as f:
                    f.write(text)
            row = callgrind_gate.analyse(a, b, ['f'])
        self.assertEqual(row['ir_total'], [102, 112])
        self.assertEqual(row['functions']['f']['exclusive'], [57, 57])
        self.assertEqual(row['functions']['f']['inclusive'], [97, 107])
        self.assertEqual(row['exclusive_delta_top'], [['g', 10]])

    def test_summary_must_match(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'x.callgrind')
            with open(path, 'w') as f:
                f.write(CALLGRIND.replace('summary: 102', 'summary: 103'))
            with self.assertRaises(AssertionError):
                callgrind_gate.parse(path)


HEADER = test_audit.COLUMNS
ROW = 'moves/test_pool_g999.c\tduoforge.state.pool_g999\trename\tmoves/test_probe.c\tduoforge.moves.probe\t%s\tG999: Probe'


class RenameTable(unittest.TestCase):
    """test_audit --check on a small git tree: one historical test (G999) planned, then done."""

    def tree(self, tmp, state, files, table_rows=None, cmake=None):
        root = Path(tmp)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding='utf-8', newline='\n')
        rows = table_rows if table_rows is not None else [ROW % state]
        (root / 'tests').mkdir(exist_ok=True)
        (root / 'tests' / 'renames.tsv').write_text('# comment\n' + '\t'.join(HEADER) + '\n' + ''.join(r + '\n' for r in rows),
                                                   encoding='utf-8', newline='\n')
        (root / 'tests' / 'moves').mkdir(exist_ok=True)
        (root / 'tests' / 'moves' / 'tests.cmake').write_text(cmake, encoding='utf-8', newline='\n')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        return root

    PLANNED = 'duoforge_add_test(NAME duoforge.state.pool_g999 SOURCES moves/test_pool_g999.c TIER quick AREA moves)\n'
    DONE = 'duoforge_add_test(NAME duoforge.moves.probe SOURCES moves/test_probe.c TIER quick AREA moves)\n'

    def test_planned_row_matches_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g999.c': '/* G999 */\n'}, cmake=self.PLANNED)
            self.assertEqual(test_audit.check(root), [])

    def test_a_historical_file_without_a_row_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmake = self.PLANNED + 'duoforge_add_test(NAME duoforge.state.pool_k9 SOURCES moves/test_pool_k9.c)\n'
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g999.c': '', 'tests/moves/test_pool_k9.c': ''}, cmake=cmake)
            self.assertEqual(test_audit.check(root), ['moves/test_pool_k9.c: a historical name without a row in tests/renames.tsv'])

    def test_done_row_needs_the_new_registration_and_no_old_name_in_living_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {'tests/moves/test_probe.c': '/* duoforge.moves.probe, was G999 */\n',
                     'tools/x.py': 'NAME = "duoforge.state.pool_g999"\n',
                     'docs/history/old.md': 'duoforge.state.pool_g999 in tests/moves/test_pool_g999.c\n',
                     'docs/benchmarks/b/README.md': 'test_pool_g999.c\n'}
            root = self.tree(tmp, 'done', files, cmake=self.DONE)
            self.assertEqual(test_audit.check(root), ['tools/x.py: still names duoforge.state.pool_g999 (renamed, see tests/renames.tsv)'])
            (root / 'tools' / 'x.py').write_text('NAME = "duoforge.moves.probe"  # pool_g9990 is another name\n', encoding='utf-8')
            self.assertEqual(test_audit.check(root), [])

    def test_done_row_with_the_old_file_left_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'done', {'tests/moves/test_probe.c': '', 'tests/moves/test_pool_g999.c': ''}, cmake=self.DONE)
            self.assertIn('moves/test_pool_g999.c: done, but the old file still exists', test_audit.check(root))

    def test_new_names_must_be_behaviour_names_of_the_area(self):
        bad = [ROW.replace('moves/test_probe.c\tduoforge.moves.probe', 'moves/test_probe_g62.c\tduoforge.moves.probe_g62') % 'planned',
               ROW.replace('duoforge.moves.probe', 'duoforge.state.haze') % 'planned']
        for row in bad:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g999.c': ''}, table_rows=[row], cmake=self.PLANNED)
                problems = test_audit.check(root)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn('is not tests/<area>/test_<behaviour>.c', problems[0])

    def test_a_split_names_no_new_file_and_rows_are_unique(self):
        split = 'moves/test_pool_g999.c\tduoforge.state.pool_g999\tsplit\tmoves/test_probe.c\tduoforge.moves.probe\tplanned\tG999'
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g999.c': ''}, table_rows=[split, ROW % 'planned'],
                             cmake=self.PLANNED)
            problems = test_audit.check(root)
            self.assertIn('moves/test_pool_g999.c: a split names its new files in rows of their own (step 6e), not here', problems)
            self.assertIn('moves/test_pool_g999.c: old_file moves/test_pool_g999.c is in two rows', problems)

    def test_the_committed_table_holds(self):
        self.assertEqual(test_audit.check(Path(__file__).resolve().parents[3]), [])


class RenameRun(unittest.TestCase):
    """rename_tests mv and names on a small git tree: one planned rename (G999 to Probe) of the moves area."""

    def test_mv_then_names_leaves_no_old_name_and_marks_the_row_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'tests/moves/test_pool_g999.c': '/* duoforge.state.pool_g999 (white-box): step G999, Probe. */\n'
                                               'df_test_begin(&t, "duoforge.state.pool_g999");\n',
                'tests/moves/tests.cmake': 'duoforge_add_test(NAME duoforge.state.pool_g999 SOURCES moves/test_pool_g999.c TIER quick AREA moves)\n',
                'tools/x.py': 'OLD = ("tests/test_pool_g999.c", "tests/moves/test_pool_g999.c", "duoforge.state.pool_g999")\n'
                              'OTHER = "duoforge.state.pool_g9990"\n',
                'docs/mechanics/moves/5zz-probe.md': '- Tests: duoforge.state.pool_g999\n',
                'docs/history/old.md': 'duoforge.state.pool_g999 in tests/test_pool_g999.c\n',
                'tests/renames.tsv': '\t'.join(test_audit.COLUMNS) + '\n' + ROW % 'planned' + '\n',
            }
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text, encoding='utf-8', newline='\n')
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            with open(os.devnull, 'w') as sink:
                stdout, sys.stdout = sys.stdout, sink
                try:
                    self.assertEqual(rename_tests.main(['mv', '--areas', 'moves', '--root', str(root)]), 0)
                    self.assertTrue((root / 'tests/moves/test_probe.c').exists())
                    self.assertFalse((root / 'tests/moves/test_pool_g999.c').exists())
                    self.assertEqual(rename_tests.main(['names', '--areas', 'moves', '--root', str(root)]), 0)
                finally:
                    sys.stdout = stdout
            self.assertEqual((root / 'tools/x.py').read_text(encoding='utf-8'),
                             'OLD = ("tests/moves/test_probe.c", "tests/moves/test_probe.c", "duoforge.moves.probe")\n'
                             'OTHER = "duoforge.state.pool_g9990"\n')
            self.assertIn('df_test_begin(&t, "duoforge.moves.probe");', (root / 'tests/moves/test_probe.c').read_text(encoding='utf-8'))
            self.assertIn('NAME duoforge.moves.probe SOURCES moves/test_probe.c', (root / 'tests/moves/tests.cmake').read_text(encoding='utf-8'))
            self.assertEqual((root / 'docs/mechanics/moves/5zz-probe.md').read_text(encoding='utf-8'), '- Tests: duoforge.moves.probe\n')
            self.assertEqual((root / 'docs/history/old.md').read_text(encoding='utf-8'), files['docs/history/old.md'])  # frozen
            self.assertEqual(test_audit.read_table(root)[0]['state'], 'done')
            self.assertEqual(test_audit.check(root), [])


if __name__ == '__main__':
    unittest.main()
