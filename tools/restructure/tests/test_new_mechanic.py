"""tools/new_mechanic.py (restructure step 12): what a scaffold writes and what it refuses, on a copy of the files it touches."""
import ast
import io
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'tools'))
import new_mechanic  # noqa: E402

FILES = ['tests/moves/tests.cmake', 'tests/abilities/tests.cmake', 'tests/interactions/tests.cmake',
         'docs/mechanics/TEMPLATE.md', 'src/rng/draw.h', 'src/rng/draw_sites.def', 'src/combat/residual_order.h',
         'src/combat/residual_kinds.def', 'tools/reference/trace_to_c.py']
# A fixed block row, so that the cases do not follow the HS's current blocks.
NUMBERS = '| Family | Owner |\n|---|---|\n| Decision 0015 entry ids | Content: 5ea-5ez; Fuzz: 5fa-5fm; HS: the rest | notes |\n'


class NewMechanic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in FILES:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, self.root / rel)
        (self.root / 'docs/process').mkdir(parents=True)
        (self.root / 'docs/process/NUMBERS.md').write_text(NUMBERS, encoding='utf-8')
        # The first free draw site below the count and the first free residual kind of the copied files: the cases take
        # those, whatever the lanes have taken by then.
        sites = (self.root / 'src/rng/draw_sites.def').read_text(encoding='utf-8')
        used = {int(v) for v in re.findall(r'^DFI_DRAW_SITE\([A-Z0-9_]+, (\d+)u,', sites, re.M)}
        self.count = int(re.search(r'^#define DFI_SITE_COUNT (\d+)u', (self.root / 'src/rng/draw.h').read_text(encoding='utf-8'),
                                   re.M).group(1))
        self.site = min(v for v in range(1, self.count) if v not in used)
        kinds = (self.root / 'src/combat/residual_kinds.def').read_text(encoding='utf-8')
        self.kind = max(int(v) for v in re.findall(r'^DFI_RES_KIND\([A-Z0-9_]+, (\d+)u,', kinds, re.M)) + 1

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        if '--lane' not in args:
            args = (*args, '--lane', 'HS')
        with redirect_stdout(out), redirect_stderr(err):
            code = new_mechanic.main([*args, '--root', str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob('*')) if p.is_file()}

    def test_a_scaffold_writes_the_test_its_registration_the_doc_and_the_numbers(self):
        code, out, err = self.run_tool('moves', 'unit_scaffold_case', '--id', '5zz', '--title', 'Unit scaffold case',
                                       '--step', 'X1', '--draw-site', 'UNIT_SCAFFOLD_ROLL=%d' % self.site,
                                       '--residual-kind', 'UNIT_SCAFFOLD=%d' % self.kind)
        self.assertEqual((code, err), (0, ''))
        test = (self.root / 'tests/moves/test_unit_scaffold_case.c').read_text(encoding='utf-8')
        self.assertIn('df_test_begin(&t, "duoforge.moves.unit_scaffold_case");', test)
        self.assertIn('const bool mechanic_checks_written = false;', test)  # it fails until it is filled in
        self.assertIn('mechanic_checks_written && "scaffold of 5zz: write the mechanic\'s checks"', test)
        cmake = (self.root / 'tests/moves/tests.cmake').read_text(encoding='utf-8')
        self.assertTrue(cmake.endswith('duoforge_add_test(NAME duoforge.moves.unit_scaffold_case SOURCES moves/test_unit_scaffold_case.c '
                                       'WHITEBOX TIMEOUT 60 TIER quick AREA moves)\n'))
        doc = (self.root / 'docs/mechanics/moves/5zz-unit-scaffold-case.md').read_text(encoding='utf-8').split('\n')
        self.assertEqual(doc[0], '<a id="5zz"></a>')
        self.assertEqual(doc[2], '# 5zz. X1, Unit scaffold case')
        self.assertEqual([l for l in doc if l.startswith('- ')][:3],
                         ['- Area: moves', '- Step: X1', '- Tests: duoforge.moves.unit_scaffold_case'])
        self.assertEqual(sum(1 for l in doc if l.startswith('5zz. **')), 1)
        self.assertNotIn('## Support', doc)  # optional, added with its support line by hand
        sites = (self.root / 'src/rng/draw_sites.def').read_text(encoding='utf-8')
        values = [int(v) for v in re.findall(r'^DFI_DRAW_SITE\([A-Z0-9_]+, (\d+)u,', sites, re.M)]
        self.assertEqual(values, sorted(values))  # the new line in id order
        self.assertIn('DFI_DRAW_SITE(UNIT_SCAFFOLD_ROLL, %du, "unit-scaffold-roll")' % self.site, sites)
        self.assertRegex((self.root / 'src/rng/draw.h').read_text(encoding='utf-8'),
                         r'#define DFI_SITE_UNIT_SCAFFOLD_ROLL %du /\*[^\n]*\*/\n#define DFI_SITE_COUNT ' % self.site)
        kinds = (self.root / 'src/combat/residual_kinds.def').read_text(encoding='utf-8')
        self.assertTrue(kinds.endswith('DFI_RES_KIND(UNIT_SCAFFOLD, %du, "unit-scaffold")\n' % self.kind))
        self.assertIn('#define DFI_RES_UNIT_SCAFFOLD %du' % self.kind, (self.root / 'src/combat/residual_order.h').read_text(encoding='utf-8'))
        trace = (self.root / 'tools/reference/trace_to_c.py').read_text(encoding='utf-8')
        sites_src = trace[trace.index('\nSITES = {'):]
        sites_src = sites_src[:sites_src.index('}') + 1]
        table = ast.literal_eval(sites_src.strip().split('=', 1)[1].strip())  # the dict literal (comments are tokens, not values)
        self.assertEqual(table['UNIT_SCAFFOLD_ROLL'], self.site)
        self.assertEqual(table, {n: int(v) for n, v in re.findall(r'^DFI_DRAW_SITE\(([A-Z0-9_]+), (\d+)u,', sites, re.M)})
        self.assertEqual(sorted(out.split('\n')[:-1]), sorted('writes ' + p for p in [
            'docs/mechanics/moves/5zz-unit-scaffold-case.md', 'src/combat/residual_kinds.def',
            'src/combat/residual_order.h', 'src/rng/draw.h', 'src/rng/draw_sites.def', 'tests/moves/test_unit_scaffold_case.c',
            'tests/moves/tests.cmake', 'tools/reference/trace_to_c.py']))

    def test_dry_run_writes_nothing(self):
        before = self.snapshot()
        code, out, _ = self.run_tool('abilities', 'dummy', '--id', '5zz', '--title', 'Dummy', '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('would write tests/abilities/test_dummy.c', out)
        self.assertEqual(self.snapshot(), before)

    def test_refusals_write_nothing(self):
        (self.root / 'docs/mechanics/moves').mkdir(parents=True)
        (self.root / 'docs/mechanics/moves/5zy-taken.md').write_text('x', encoding='utf-8')
        (self.root / 'docs/mechanics/moves/renamed.md').write_text('<a id="5zw"></a>\n', encoding='utf-8')
        cases = [
            (('flow2', 'probe'), 'area'),
            (('moves', 'haze_g62'), 'no step number'),
            (('moves', 'Haze'), 'lowercase'),
            (('interactions', 'probe'), '--doc-area'),
            (('moves', 'probe', '--id', '9'), 'entry id'),
            (('moves', 'probe', '--id', '5zy'), 'has its file or anchor already'),
            (('moves', 'probe', '--id', '5zw'), 'has its file or anchor already'),
            (('moves', 'probe', '--id', '5zz', '--lane', 'Content'), 'outside the Content block'),
            (('moves', 'probe', '--id', '5ea', '--lane', 'Fuzz'), 'outside the Fuzz block'),
            (('moves', 'probe', '--id', '5eb', '--lane', 'HS'), "another lane's block"),
            (('moves', 'probe', '--id', '5eb', '--lane', 'Nobody'), 'has no block'),
            (('moves', 'probe', '--draw-site', 'DRAG=%d' % self.site), 'taken'),
            (('moves', 'probe', '--draw-site', 'NEW_ROLL=20'), 'taken'),
            (('moves', 'probe', '--draw-site', 'NEW_ROLL=%d' % self.count), 'outside 1..%d' % (self.count - 1)),
            (('moves', 'probe', '--draw-site', 'new=%d' % self.site), 'NAME=NUMBER'),
            (('moves', 'probe', '--residual-kind', 'CURSE=%d' % self.kind), 'taken'),
            (('moves', 'probe', '--residual-kind', 'NEW=19'), 'taken'),
        ]
        for args, reason in cases:
            with self.subTest(args=args):
                full = list(args)
                if '--id' not in full:
                    full += ['--id', '5zz']
                before = self.snapshot()
                code, _, err = self.run_tool(*full, '--title', 'X')
                self.assertEqual(code, 2)
                self.assertIn(reason, err)
                self.assertIn('nothing written', err)
                self.assertEqual(self.snapshot(), before)

    def test_a_lane_id_inside_its_block_is_taken(self):
        code, _, err = self.run_tool('moves', 'probe', '--id', '5ec', '--lane', 'Content', '--title', 'X', '--dry-run')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(new_mechanic.lane_blocks('| Decision 0015 entry ids | Content: 5ea-5ez; Fuzz: 5fa-5fm; HS: the rest |'),
                         {'Content': [('5ea', '5ez')], 'Fuzz': [('5fa', '5fm')]})
        self.assertLess(new_mechanic.id_key('5z'), new_mechanic.id_key('5aa'))

    def test_a_taken_test_name_or_file_is_refused(self):
        self.assertEqual(self.run_tool('moves', 'probe', '--id', '5zz', '--title', 'X')[0], 0)
        code, _, err = self.run_tool('moves', 'probe', '--id', '5zx', '--title', 'Y')
        self.assertEqual(code, 2)
        self.assertIn('tests/moves/test_probe.c exists', err)
        (self.root / 'tests/moves/test_probe.c').unlink()
        code, _, err = self.run_tool('moves', 'probe', '--id', '5zx', '--title', 'Y')
        self.assertIn('the CTest name duoforge.moves.probe is taken', err)


if __name__ == '__main__':
    unittest.main()
