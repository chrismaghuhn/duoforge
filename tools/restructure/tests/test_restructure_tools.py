"""tools/restructure: fn_diff's normalisation and clone groups, callgrind_gate's parser and clone sums, and the rules of
test_audit's rename table, offline."""
import contextlib
import io
import json
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

    def test_merge_keeps_each_section_and_renames_what_collides(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tests/moves').mkdir(parents=True)
        a = SOURCE.replace('pool_g999', 'pool_g998')
        b = SOURCE.replace('pool_g999', 'pool_g997').replace('return 2u * x;', 'return x + x;').replace(
            '/* the second subject */\nstatic void check_two(df_test *t)\n{\n    DF_CHECK(t, twice(2u) == 4u);\n}\n\n', '').replace(
            '    check_two(&t);\n', '')
        (root / 'tests/moves/test_pool_g998.c').write_text(a, encoding='utf-8')
        (root / 'tests/moves/test_pool_g997.c').write_text(b, encoding='utf-8')
        one = {'source': 'moves/test_pool_g998.c', 'parts': [{'file': 'moves/test_both.c', 'calls': ['check_one', 'check_two'], 'header': 's'}]}
        two = {'source': 'moves/test_pool_g997.c', 'parts': [{'file': 'moves/test_both.c', 'calls': ['check_one'], 'header': 's'}]}
        ctest, text = split_test.merge(root, {'file': 'moves/test_both.c', 'header': 'both',
                                              'sections': [{'spec': one, 'prefix': 'first_'}, {'spec': two, 'prefix': 'second_'}]})
        self.assertEqual(ctest, 'duoforge.moves.both')
        for name in ('first_twice', 'second_twice', 'first_check_one', 'second_check_one'):
            self.assertRegex(text, r'\b%s\(' % name)
        self.assertIn('static void check_two(df_test *t)', text)  # only the first section has it: no prefix
        self.assertIn('    { /* first */\n        first_check_one(&t);\n        check_two(&t);\n    }\n    { /* second */\n        second_check_one(&t);\n    }\n',
                      text)
        self.assertEqual(text.count('df_test_begin(&t, "duoforge.moves.both");'), 1)
        same = {'source': 'moves/test_pool_g998.c', 'parts': [{'file': 'moves/test_both.c', 'calls': ['check_one', 'check_two'], 'header': 's'}]}
        three = dict(two, source='moves/test_pool_g996.c')
        (root / 'tests/moves/test_pool_g996.c').write_text(a.replace('pool_g998', 'pool_g996').replace(
            '/* the second subject */\nstatic void check_two(df_test *t)\n{\n    DF_CHECK(t, twice(2u) == 4u);\n}\n\n', '').replace(
            '    check_two(&t);\n', ''), encoding='utf-8')
        _, text = split_test.merge(root, {'file': 'moves/test_both.c', 'header': 'both',
                                          'sections': [{'spec': same, 'prefix': 'first_'}, {'spec': three, 'prefix': 'third_'}]})
        self.assertEqual(text.count('static unsigned twice(unsigned x)'), 1)  # the same helper in both: kept once, not renamed

    def merge_tree(self, sources):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tests/moves').mkdir(parents=True)
        for name, text in sources.items():
            (root / 'tests/moves' / name).write_text(text, encoding='utf-8')
        return root

    def test_merge_tells_sections_apart_by_their_macros(self):
        """Two identical functions that name a macro of two values stay two (the review's case): each section keeps its value."""
        def source(n, value):
            return SOURCE.replace('pool_g999', n).replace('#include "support/check.h"\n', '#include "support/check.h"\n\n#define BASE %su\n#define LIMIT (BASE + 1u)\n' % value).replace(
                'DF_CHECK(t, twice(1u) == 2u);', 'DF_CHECK(t, twice(1u) <= LIMIT);')
        root = self.merge_tree({'test_pool_g998.c': source('pool_g998', 1), 'test_pool_g997.c': source('pool_g997', 7)})
        spec = lambda n: {'source': 'moves/test_%s.c' % n, 'parts': [{'file': 'moves/test_both.c', 'calls': ['check_one', 'check_two'], 'header': 's'}]}
        _, text = split_test.merge(root, {'file': 'moves/test_both.c', 'header': 'both', 'sections': [
            {'spec': spec('pool_g998'), 'prefix': 'a_'}, {'spec': spec('pool_g997'), 'prefix': 'b_'}]})
        self.assertIn('#define a_BASE 1u', text)
        self.assertIn('#define b_BASE 7u', text)
        self.assertIn('#define a_LIMIT (a_BASE + 1u)', text)  # a macro that only another macro names is kept, renamed
        self.assertIn('#define b_LIMIT (b_BASE + 1u)', text)
        self.assertIn('DF_CHECK(t, twice(1u) <= a_LIMIT);', text)  # twice is the same in both: shared
        self.assertIn('DF_CHECK(t, twice(1u) <= b_LIMIT);', text)
        self.assertIn('    { /* b */\n        b_check_one(&t);', text)
        same = self.merge_tree({'test_pool_g998.c': source('pool_g998', 1), 'test_pool_g997.c': source('pool_g997', 1)})
        _, text = split_test.merge(same, {'file': 'moves/test_both.c', 'header': 'both', 'sections': [
            {'spec': spec('pool_g998'), 'prefix': 'a_'}, {'spec': spec('pool_g997'), 'prefix': 'b_'}]})
        self.assertEqual(text.count('#define BASE 1u'), 1)  # the same macro of the same value: once, as it was
        self.assertEqual(text.count('static void check_one('), 1)

    def test_a_part_keeps_only_the_macros_it_needs(self):
        src = SOURCE.replace('#include "support/check.h"\n', '#include "support/check.h"\n\n/* only check_two\'s */\n#define TWO 2u\n').replace(
            'DF_CHECK(t, twice(2u) == 4u);', 'DF_CHECK(t, twice(TWO) == 4u);')
        out = self.run_split({'parts': self.TWO}, source=src)
        self.assertNotIn('TWO', out['moves/test_one.c'])
        self.assertNotIn("only check_two's", out['moves/test_one.c'])
        self.assertIn('#define TWO 2u', out['moves/test_two.c'])

    def test_names_of_anonymous_enums_and_tagged_structs(self):
        self.assertEqual(split_test.item_name('enum { LO, HI, KINDS };\n'), 'LO')
        self.assertEqual(split_test.item_name('struct pair {\n    unsigned base;\n};\n'), 'pair')
        self.assertEqual(split_test.item_name('static const struct pair pairs[] = {{1u}};\n'), 'pairs')
        self.assertEqual(split_test.enumerators([('LO', 'enum { LO, HI = 3, KINDS };\n')]), {'LO': 'LO', 'HI': 'LO', 'KINDS': 'LO'})

    def test_except_and_keep_header(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tests/moves').mkdir(parents=True)
        (root / 'tests/moves/test_pool_g999.c').write_text(SOURCE, encoding='utf-8')
        spec = Path(tmp.name) / 'spec.json'
        spec.write_text(json.dumps({'source': 'moves/test_pool_g999.c', 'parts': [
            {'file': 'moves/test_pool_g999.c', 'calls': ['check_one'], 'keep_header': True},
            {'file': 'moves/test_two.c', 'calls': ['check_two'], 'header': 'two'}]}), encoding='utf-8')
        with open(os.devnull, 'w') as sink:
            stdout, sys.stdout = sys.stdout, sink
            try:
                self.assertEqual(split_test.main([str(spec), '--root', str(root), '--except', 'moves/test_two.c']), 0)
            finally:
                sys.stdout = stdout
        kept = (root / 'tests/moves/test_pool_g999.c').read_text(encoding='utf-8')
        self.assertTrue(kept.startswith('/*\n * duoforge.state.pool_g999 (white-box): two subjects.\n */\n'))
        self.assertNotIn('check_two', kept)
        self.assertFalse((root / 'tests/moves/test_two.c').exists())

    def test_defines_dropped_line_by_line_and_never_where_the_preprocessor_reads_them(self):
        pre = ('#include <stdio.h>\n\n#include "support/check.h"\n\n/* the cap */\n#define CAP 3u\n#define FLOOR 1u\n\n'
               '/* only for the other part */\n#define OTHER 9u\n\n')
        self.assertEqual(split_test.drop_unused_defines(pre, {'CAP', 'FLOOR'}),
                         '#include <stdio.h>\n\n#include "support/check.h"\n\n/* the cap */\n#define CAP 3u\n#define FLOOR 1u\n')
        # the comment over a group stays with the define that is kept, and goes when the first define of its group goes alone
        self.assertEqual(split_test.drop_unused_defines(pre, {'FLOOR'}),
                         '#include <stdio.h>\n\n#include "support/check.h"\n\n/* the cap */\n#define FLOOR 1u\n')
        self.assertEqual(split_test.drop_unused_defines(pre, set()), '#include <stdio.h>\n\n#include "support/check.h"\n')
        guarded = '#include <stdio.h>\n\n#define WITH 1\n#if WITH\n#define LIM 3u\n#else\n#define LIM 5u\n#endif\n'
        self.assertEqual(split_test.drop_unused_defines(guarded, {'LIM'}), guarded)  # a conditional: nothing is dropped
        two = '#include <stdio.h>\n\n\n#define X 1u\n#define Y 2u\n'
        self.assertEqual(split_test.drop_unused_defines(two, {'Y'}), '#include <stdio.h>\n\n\n#define Y 2u\n')  # the source's two
        config = '#define DF_CHECK_VERBOSE 1\n#include <stdio.h>\n\n#define X 1u\n'
        self.assertEqual(split_test.drop_unused_defines(config, set()), config)  # a define before an include: kept
        # a kept define of several lines directly above a dropped one keeps its body (its continuation is no comment)
        cont = '#include <x.h>\n\n#define A(x) \\\n    ((x) + 1)\n#define B 2\n'
        self.assertEqual(split_test.drop_unused_defines(cont, {'A'}), '#include <x.h>\n\n#define A(x) \\\n    ((x) + 1)\n')
        # a block comment goes whole or not at all (a middle line without a star), a // run goes whole
        half = '#include <x.h>\n\n/* a comment\n   over two lines\n * and more */\n#define B 2\n#define C 3\n'
        self.assertEqual(split_test.drop_unused_defines(half, set()), '#include <x.h>\n')
        tail = '#include <x.h>\n\n/* one */ int x;\n * not a comment */\n#define B 2\n#define K 1\n'
        self.assertEqual(split_test.drop_unused_defines(tail, {'K'}), '#include <x.h>\n\n/* one */ int x;\n * not a comment */\n#define K 1\n')
        slashes = '#include <x.h>\n\n// two\n// lines\n#define B 2\n#define K 1\n'
        self.assertEqual(split_test.drop_unused_defines(slashes, {'K'}), '#include <x.h>\n\n// two\n// lines\n#define K 1\n')
        self.assertEqual(split_test.drop_unused_defines(slashes, set()), '#include <x.h>\n')
        # a comment that runs on past a define, a define in a comment, a nested /*, a // line continued: kept whole
        for whole in ('#include <x.h>\n\n#define B 2 /* the value\n   of B */\n#define C 3\n',
                      '#include <x.h>\n\n/* disabled:\n#define B 2 */\n#define C 3\n',
                      '#include <x.h>\n\n/* outer\n/* inner */\n#define B 2\n#define C 3\n',
                      '#include <x.h>\n\n// a line \\\n#define B 2\n#define C 3\n',
                      '#include <x.h>\n\n#define C 3\n/* open\n'):
            self.assertEqual(split_test.drop_unused_defines(whole, {'C'}), whole)
        # a comment that closes on the define's own line goes with it
        self.assertEqual(split_test.drop_unused_defines('#include <x.h>\n\n#define B 2 /* B */\n#define C 3\n', {'C'}),
                         '#include <x.h>\n\n#define C 3\n')
        # a define at the end of the preamble goes with its blank line above, so the blank before the first item is single
        end = '#include <x.h>\n\n#define B 2\n'
        self.assertEqual(split_test.drop_unused_defines(end, set()), '#include <x.h>\n')

    def test_a_part_keeps_its_sources_blank_lines_between_items(self):
        src = SOURCE.replace('/* the first subject */\nstatic void check_one', 'static unsigned zero = 0u;\n/* the first subject */\nstatic void check_one').replace(
            'DF_CHECK(t, twice(1u) == 2u);', 'DF_CHECK(t, twice(1u) == 2u + zero);')
        out = self.run_split({'parts': self.TWO}, source=src)
        self.assertIn('}\n\nstatic unsigned zero = 0u;\n/* the first subject */\nstatic void check_one', out['moves/test_one.c'])

    def test_header_replace_and_its_refusal(self):
        keep = {'file': 'moves/test_pool_g999.c', 'calls': ['check_one', 'check_two'], 'keep_header': True,
                'header_replace': [[' two subjects.', ' two subjects, the second elsewhere.']]}
        out = self.run_split({'parts': [keep]})
        self.assertTrue(out['moves/test_pool_g999.c'].startswith('/*\n * duoforge.state.pool_g999 (white-box): two subjects, the second elsewhere.\n */\n'))
        self.assertIn('header_replace', self.run_split({'parts': [dict(keep, header_replace=[['no such text', 'x']])]}))

    def test_merge_specs_come_from_the_repository_of_the_merge_spec(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tests/moves').mkdir(parents=True)
        (root / 'tests/moves/test_pool_g999.c').write_text(SOURCE, encoding='utf-8')
        mspec = {'file': 'moves/test_both.c', 'header': 'both', 'sections': [{'spec': 'specs/one.json', 'prefix': 'a_'}]}
        with self.assertRaises(split_test.Refused) as cm:
            split_test.merge(root, mspec, spec_base=root)
        self.assertIn('specs/one.json is not in', str(cm.exception))
        (root / 'specs').mkdir()
        (root / 'specs/one.json').write_text(json.dumps({'source': 'moves/test_pool_g999.c', 'parts': [
            {'file': 'moves/test_both.c', 'calls': ['check_one', 'check_two'], 'header': 's'}]}), encoding='utf-8')
        self.assertEqual(split_test.merge(root, mspec, spec_base=root)[0], 'duoforge.moves.both')
        # a merge spec in no repository (no tools/restructure above it) is refused, not read against --root
        (root / 'both.merge.json').write_text(json.dumps(mspec), encoding='utf-8')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(split_test.main([str(root / 'both.merge.json'), '--merge', '--root', str(root)]), 2)
        self.assertIn('in no repository', err.getvalue())

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
            merge = 'moves/test_pool_g998.c\tduoforge.state.pool_g998\tmerge\tmoves/test_one.c\tduoforge.moves.one\tdone\tG998'
            self.assertIn('moves/test_pool_g999.c: two part rows of one source name moves/test_one.c',
                          table(split, merge, part % ('one', 'one', 'one'), part % ('one', 'one', 'one')))
            self.assertIn('moves/test_pool_g999.c: a part row is written when its file is (state done)',
                          table(split, part % ('one', 'one', 'one'), (part % ('two', 'two', 'two')).replace('\tdone\t', '\tplanned\t')))
            (root / 'tests/items').mkdir()
            (root / 'tests/items/tests.cmake').write_text(cmake, encoding='utf-8')
            (root / 'tests/moves/tests.cmake').write_text('', encoding='utf-8')
            self.assertIn('moves/test_pool_g999.c: part moves/test_one.c is registered outside tests/moves/tests.cmake',
                          table(split, part % ('one', 'one', 'one'), part % ('two', 'two', 'two')))


if __name__ == '__main__':
    unittest.main()
