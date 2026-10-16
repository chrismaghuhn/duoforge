"""tools/restructure: fn_diff's normalisation and clone groups, callgrind_gate's parser and clone sums, offline."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import callgrind_gate  # noqa: E402
import fn_diff  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
