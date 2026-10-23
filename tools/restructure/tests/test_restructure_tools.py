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
import split_test  # noqa: E402
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
ROW = 'moves/test_pool_g62.c\tduoforge.state.pool_g62\trename\tmoves/test_haze.c\tduoforge.moves.haze\t%s\tG62: Haze'


class RenameTable(unittest.TestCase):
    """test_audit --check on a small git tree: one historical test (G62) planned, then done."""

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

    PLANNED = 'duoforge_add_test(NAME duoforge.state.pool_g62 SOURCES moves/test_pool_g62.c TIER quick AREA moves)\n'
    DONE = 'duoforge_add_test(NAME duoforge.moves.haze SOURCES moves/test_haze.c TIER quick AREA moves)\n'

    def test_planned_row_matches_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g62.c': '/* G62 */\n'}, cmake=self.PLANNED)
            self.assertEqual(test_audit.check(root), [])

    def test_a_historical_file_without_a_row_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmake = self.PLANNED + 'duoforge_add_test(NAME duoforge.state.pool_k9 SOURCES moves/test_pool_k9.c)\n'
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g62.c': '', 'tests/moves/test_pool_k9.c': ''}, cmake=cmake)
            self.assertEqual(test_audit.check(root), ['moves/test_pool_k9.c: a historical name without a row in tests/renames.tsv'])

    def test_done_row_needs_the_new_registration_and_no_old_name_in_living_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {'tests/moves/test_haze.c': '/* duoforge.moves.haze, was G62 */\n',
                     'tools/x.py': 'NAME = "duoforge.state.pool_g62"\n',
                     'docs/history/old.md': 'duoforge.state.pool_g62 in tests/moves/test_pool_g62.c\n',
                     'docs/benchmarks/b/README.md': 'test_pool_g62.c\n'}
            root = self.tree(tmp, 'done', files, cmake=self.DONE)
            self.assertEqual(test_audit.check(root), ['tools/x.py: still names duoforge.state.pool_g62 (renamed, see tests/renames.tsv)'])
            (root / 'tools' / 'x.py').write_text('NAME = "duoforge.moves.haze"  # pool_g620 is another name\n', encoding='utf-8')
            self.assertEqual(test_audit.check(root), [])

    def test_done_row_with_the_old_file_left_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'done', {'tests/moves/test_haze.c': '', 'tests/moves/test_pool_g62.c': ''}, cmake=self.DONE)
            self.assertIn('moves/test_pool_g62.c: done, but the old file still exists', test_audit.check(root))

    def test_new_names_must_be_behaviour_names_of_the_area(self):
        bad = [ROW.replace('moves/test_haze.c\tduoforge.moves.haze', 'moves/test_haze_g62.c\tduoforge.moves.haze_g62') % 'planned',
               ROW.replace('duoforge.moves.haze', 'duoforge.state.haze') % 'planned']
        for row in bad:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g62.c': ''}, table_rows=[row], cmake=self.PLANNED)
                problems = test_audit.check(root)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn('is not tests/<area>/test_<behaviour>.c', problems[0])

    def test_a_split_names_no_new_file_and_rows_are_unique(self):
        split = 'moves/test_pool_g62.c\tduoforge.state.pool_g62\tsplit\tmoves/test_haze.c\tduoforge.moves.haze\tplanned\tG62'
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(tmp, 'planned', {'tests/moves/test_pool_g62.c': ''}, table_rows=[split, ROW % 'planned'],
                             cmake=self.PLANNED)
            problems = test_audit.check(root)
            self.assertIn('moves/test_pool_g62.c: a split names its new files in rows of their own (step 6e), not here', problems)
            self.assertIn('moves/test_pool_g62.c: old_file moves/test_pool_g62.c is in two rows', problems)

    def test_the_committed_table_holds(self):
        self.assertEqual(test_audit.check(Path(__file__).resolve().parents[3]), [])


class RenameRun(unittest.TestCase):
    """rename_tests mv and names on a small git tree: one planned rename (G62 to Haze) of the moves area."""

    def test_mv_then_names_leaves_no_old_name_and_marks_the_row_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'tests/moves/test_pool_g62.c': '/* duoforge.state.pool_g62 (white-box): step G62, Haze. */\n'
                                               'df_test_begin(&t, "duoforge.state.pool_g62");\n',
                'tests/moves/tests.cmake': 'duoforge_add_test(NAME duoforge.state.pool_g62 SOURCES moves/test_pool_g62.c TIER quick AREA moves)\n',
                'tools/x.py': 'OLD = ("tests/test_pool_g62.c", "tests/moves/test_pool_g62.c", "duoforge.state.pool_g62")\n'
                              'OTHER = "duoforge.state.pool_g620"\n',
                'docs/mechanics/moves/5az-haze.md': '- Tests: duoforge.state.pool_g62\n',
                'docs/history/old.md': 'duoforge.state.pool_g62 in tests/test_pool_g62.c\n',
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
                    self.assertTrue((root / 'tests/moves/test_haze.c').exists())
                    self.assertFalse((root / 'tests/moves/test_pool_g62.c').exists())
                    self.assertEqual(rename_tests.main(['names', '--areas', 'moves', '--root', str(root)]), 0)
                finally:
                    sys.stdout = stdout
            self.assertEqual((root / 'tools/x.py').read_text(encoding='utf-8'),
                             'OLD = ("tests/moves/test_haze.c", "tests/moves/test_haze.c", "duoforge.moves.haze")\n'
                             'OTHER = "duoforge.state.pool_g620"\n')
            self.assertIn('df_test_begin(&t, "duoforge.moves.haze");', (root / 'tests/moves/test_haze.c').read_text(encoding='utf-8'))
            self.assertIn('NAME duoforge.moves.haze SOURCES moves/test_haze.c', (root / 'tests/moves/tests.cmake').read_text(encoding='utf-8'))
            self.assertEqual((root / 'docs/mechanics/moves/5az-haze.md').read_text(encoding='utf-8'), '- Tests: duoforge.moves.haze\n')
            self.assertEqual((root / 'docs/history/old.md').read_text(encoding='utf-8'), files['docs/history/old.md'])  # frozen
            self.assertEqual(test_audit.read_table(root)[0]['state'], 'done')
            self.assertEqual(test_audit.check(root), [])


SOURCE = """/*
 * duoforge.state.pool_g999 (white-box): two subjects.
 */
#include <stdio.h>

#include "support/check.h"

/* shared by both checks */
static unsigned twice(unsigned x)
{
    return 2u * x;
}

/* the first subject */
static void check_one(df_test *t)
{
    DF_CHECK(t, twice(1u) == 2u);
}

/* the second subject */
static void check_two(df_test *t)
{
    DF_CHECK(t, twice(2u) == 4u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g999");
    check_one(&t);
    check_two(&t);
    return df_test_end(&t);
}
"""


class SplitTest(unittest.TestCase):
    """split_test on a small C test of two subjects: what each part gets, and what is refused."""

    def run_split(self, spec, source=SOURCE, header=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tests/moves').mkdir(parents=True)
        (root / 'tests/moves/test_pool_g999.c').write_text(source, encoding='utf-8')
        if header is not None:
            (root / 'tests/support').mkdir()
            (root / 'tests/support/h.h').write_text(header, encoding='utf-8')
        spec = dict({'source': 'moves/test_pool_g999.c'}, **spec)
        try:
            _, parts = split_test.split(root, spec)
        except split_test.Refused as e:
            return str(e)
        return {f: text for f, _, text in parts}

    TWO = [{'file': 'moves/test_one.c', 'calls': ['check_one'], 'header': 'one'},
           {'file': 'moves/test_two.c', 'calls': ['check_two'], 'header': 'two'}]

    def test_each_part_gets_its_check_the_shared_helper_and_its_name(self):
        out = self.run_split({'parts': self.TWO})
        one, two = out['moves/test_one.c'], out['moves/test_two.c']
        self.assertIn('df_test_begin(&t, "duoforge.moves.one");', one)
        self.assertIn('static unsigned twice(unsigned x)', one)
        self.assertIn('static unsigned twice(unsigned x)', two)
        self.assertIn('check_one(&t);', one)
        self.assertNotIn('check_two', one)
        self.assertNotIn('check_one', two)
        self.assertTrue(one.startswith('/*\n * duoforge.moves.one (white-box): one\n */\n#include <stdio.h>\n'))

    def test_every_check_lands_exactly_once(self):
        self.assertIn('not placed: calls [\'check_two\']', self.run_split({'parts': self.TWO[:1]}))
        twice = [self.TWO[0], dict(self.TWO[1], calls=['check_one'])]
        self.assertIn('the call of check_one is in moves/test_one.c already', self.run_split({'parts': twice}))
        self.assertIn('no call of check_three', self.run_split({'parts': [self.TWO[0], dict(self.TWO[1], calls=['check_three'])]}))

    def test_a_support_helper_must_be_the_sources_copy(self):
        same = '/* h */\nstatic inline unsigned df_twice(unsigned x)\n{\n    return 2u * x; /* a comment is no difference */\n}\n'
        out = self.run_split({'parts': self.TWO, 'support': {'header': 'support/h.h', 'items': {'twice': 'df_twice'}}},
                             header=same)
        self.assertNotIn('static unsigned twice', out['moves/test_one.c'])
        self.assertIn('DF_CHECK(t, df_twice(1u) == 2u);', out['moves/test_one.c'])
        self.assertIn('#include "support/h.h"', out['moves/test_one.c'])
        other = same.replace('2u * x', 'x + x')
        self.assertIn('is not the source\'s twice',
                      self.run_split({'parts': self.TWO, 'support': {'header': 'support/h.h', 'items': {'twice': 'df_twice'}}},
                                     header=other))

    LOOP = SOURCE.replace("""    check_one(&t);
    check_two(&t);
""", """    unsigned k0 = 0u; /* a context */
    for (unsigned k = 0u; k < 2u; ++k) {
        check_one(&t);
        check_two(&t);
    }
    (void)k0;
""")

    def test_main_blocks_and_shared_blocks(self):
        src = SOURCE.replace('    check_one(&t);\n', '    unsigned c = 1u; /* shared */\n    check_one(&t);\n    (void)c;\n')
        out = self.run_split({'shared_blocks': [0], 'parts': [
            {'file': 'moves/test_one.c', 'calls': ['check_one'], 'main_blocks': [0, 2], 'header': 'one'},
            {'file': 'moves/test_two.c', 'calls': ['check_two'], 'main_blocks': [0], 'header': 'two'}]}, source=src)
        self.assertIn('unsigned c = 1u; /* shared */', out['moves/test_one.c'])
        self.assertIn('unsigned c = 1u; /* shared */', out['moves/test_two.c'])
        self.assertIn('(void)c;', out['moves/test_one.c'])
        self.assertIn('main blocks [2]', self.run_split({'shared_blocks': [0], 'parts': [
            {'file': 'moves/test_one.c', 'calls': ['check_one'], 'main_blocks': [0], 'header': 'one'},
            {'file': 'moves/test_two.c', 'calls': ['check_two'], 'main_blocks': [0], 'header': 'two'}]}, source=src))

    def test_a_main_written_out_keeps_every_call_and_every_line(self):
        def body(call):
            return ['    unsigned k0 = 0u;', '    for (unsigned k = 0u; k < 2u; ++k) {', '        %s(&t);' % call, '    }',
                    '    (void)k0;']
        good = [{'file': 'moves/test_one.c', 'main_body': body('check_one'), 'header': 'one'},
                {'file': 'moves/test_two.c', 'main_body': body('check_two'), 'header': 'two'}]
        out = self.run_split({'parts': good}, source=self.LOOP)
        self.assertIn('    for (unsigned k = 0u; k < 2u; ++k) {\n        check_one(&t);\n    }', out['moves/test_one.c'])
        no_loop = [dict(good[0], main_body=['    check_one(&t);']), dict(good[1], main_body=['    check_two(&t);'])]
        self.assertIn('lines of the source main in no part', self.run_split({'parts': no_loop}, source=self.LOOP))
        twice = [dict(good[0], main_body=body('check_one') + ['    check_one(&t);']), good[1]]
        self.assertIn('the parts make the calls', self.run_split({'parts': twice}, source=self.LOOP))

    def test_line_comments_stay_and_conditionals_are_refused(self):
        src = SOURCE.replace('/* the first subject */', '// the first subject')
        self.assertIn('// the first subject\nstatic void check_one', self.run_split({'parts': self.TWO}, source=src)['moves/test_one.c'])
        guarded = SOURCE.replace('/* the second subject */\n', '#if 1\n/* the second subject */\n').replace(
            'DF_CHECK(t, twice(2u) == 4u);\n}\n', 'DF_CHECK(t, twice(2u) == 4u);\n}\n#endif\n')
        self.assertIn('a preprocessor conditional', self.run_split({'parts': self.TWO}, source=guarded))

    def test_a_support_type_is_renamed_in_code_not_in_comments(self):
        src = SOURCE.replace('/* shared by both checks */\nstatic unsigned twice(unsigned x)\n{\n    return 2u * x;\n}\n',
                             '/* shared by both checks; a pair is a word here */\ntypedef struct pair {\n    unsigned x;\n} pair;\n\n'
                             'static unsigned twice(unsigned x)\n{\n    pair p = {x};\n    return 2u * p.x;\n}\n')
        header = '/* h */\ntypedef struct df_pair {\n    unsigned x;\n} df_pair;\n'
        out = self.run_split({'parts': self.TWO, 'support': {'header': 'support/h.h', 'items': {'pair': 'df_pair'}}},
                             source=src, header=header)
        self.assertIn('    df_pair p = {x};', out['moves/test_one.c'])
        self.assertNotIn('typedef struct pair', out['moves/test_one.c'])

    def test_parts_of_a_split_in_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmake = ''.join('duoforge_add_test(NAME duoforge.moves.%s SOURCES moves/test_%s.c)\n' % (n, n) for n in ('one', 'two'))
            split = 'moves/test_pool_g999.c\tduoforge.state.pool_g999\tsplit\t-\t-\tdone\tG999'
            part = 'moves/test_pool_g999.c\tduoforge.state.pool_g999\tpart\tmoves/test_%s.c\tduoforge.moves.%s\tdone\tG999: %s'
            files = {'tests/moves/test_one.c': '', 'tests/moves/test_two.c': '', 'tests/moves/tests.cmake': cmake}
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text, encoding='utf-8')
            def table(*rows):
                (root / 'tests/renames.tsv').write_text('\t'.join(test_audit.COLUMNS) + '\n' + ''.join(r + '\n' for r in rows),
                                                       encoding='utf-8')
                subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
                subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
                return test_audit.check(root)
            self.assertEqual(table(split, part % ('one', 'one', 'one'), part % ('two', 'two', 'two')), [])
            self.assertEqual(table(split, part % ('one', 'one', 'one')),
                             ['moves/test_pool_g999.c: a split is done with 1 part row(s); a single subject is a rename'])
            self.assertIn('moves/test_pool_g999.c: a part row whose source has no split row of the same CTest name',
                          table(part % ('one', 'one', 'one')))
            planned = split.replace('\tdone\t', '\tplanned\t')
            self.assertIn('moves/test_pool_g999.c: a part row while its split is planned (the old test would still run beside it)',
                          table(planned, part % ('one', 'one', 'one'), part % ('two', 'two', 'two')))
            self.assertIn('moves/test_pool_g999.c: the new file moves/test_one.c is in two rows',
                          table(split, part % ('one', 'one', 'one'), part % ('one', 'one', 'one')))
            self.assertIn('moves/test_pool_g999.c: a part row is written when its file is (state done)',
                          table(split, part % ('one', 'one', 'one'), (part % ('two', 'two', 'two')).replace('\tdone\t', '\tplanned\t')))
            (root / 'tests/items').mkdir()
            (root / 'tests/items/tests.cmake').write_text(cmake, encoding='utf-8')
            (root / 'tests/moves/tests.cmake').write_text('', encoding='utf-8')
            self.assertIn('moves/test_pool_g999.c: part moves/test_one.c is registered outside tests/moves/tests.cmake',
                          table(split, part % ('one', 'one', 'one'), part % ('two', 'two', 'two')))


if __name__ == '__main__':
    unittest.main()
