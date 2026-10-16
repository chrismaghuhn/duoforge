"""Gate (b) of a phase cut: executed instructions of one bench run, before against after (restructure proofs).

Usage:
  python3 tools/restructure/callgrind_gate.py --out DIR [--limit 1.010] [--function NAME ...]
      --pair ipo BEFORE_BENCH AFTER_BENCH [--pair noipo BEFORE_BENCH AFTER_BENCH ...]
  python3 tools/restructure/callgrind_gate.py --analyse BEFORE.callgrind AFTER.callgrind [--function NAME ...]

Runs each bench executable under `valgrind --tool=callgrind` on the same workload (the step/events bench of the
restructure proofs) and checks the total Ir ratio after/before <= --limit per profile. The callgrind output is parsed
here, not through callgrind_annotate, so that every clone of a function counts:

- a group is a source function with all its clones (`dfi_get_damage`, `dfi_get_damage.lto_priv.0`, `.constprop.N`,
  `.isra.N`, `.part.N`, `.cold`, callgrind's recursion copies `'N`; tools/restructure/fn_diff.py `base`);
- the group's exclusive Ir is the sum over its clones; its inclusive Ir adds every call from a clone to a function
  outside the group (a call between two clones of the group is not counted twice);
- the report lists the groups whose exclusive Ir changed most, so a change of inlining elsewhere (a callee no longer
  inlined into its callers) shows up even when the named function's own delta is smaller than the total's.

The gate also runs fn_diff on the measured executables themselves and records the groups whose code differs.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fn_diff  # noqa: E402

BENCH_ARGS = ['--battles', '128', '--repetitions', '1', '--warmup', '0', '--max-steps', '128', '--policy-seed',
              '20261001', '--battle-seed', '7001', '--families', 'step,events', '--workers', '1']
NAMED = re.compile(r'^(c?fn)=\((\d+)\)(?: (.*))?$')


def parse(path):
    """Self Ir per function name and inclusive Ir per (caller, callee) pair of one callgrind output file."""
    names, self_ir, calls = {}, {}, {}
    fn = cfn = None
    pending_call = False
    total = None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('summary:') or line.startswith('totals:'):
                total = int(line.split()[1])
                continue
            m = NAMED.match(line)
            if m:
                kind, ident, name = m.groups()
                if name is not None:
                    names[ident] = name
                if kind == 'fn':
                    fn = names[ident]
                else:
                    cfn = names[ident]
                continue
            if line.startswith('calls='):
                pending_call = True
                continue
            if not line or not (line[0].isdigit() or line[0] in '+-*'):
                continue  # ob=, fl=, fi=, fe=, cob=, cfi=, headers
            parts = line.split()
            ir = int(parts[1]) if len(parts) > 1 else 0
            if pending_call:
                calls[(fn, cfn)] = calls.get((fn, cfn), 0) + ir
                pending_call = False
            else:
                self_ir[fn] = self_ir.get(fn, 0) + ir
    assert total is not None and total == sum(self_ir.values()), (path, total, sum(self_ir.values()))
    return total, self_ir, calls


def groups(self_ir, calls):
    excl, incl = {}, {}
    for name, ir in self_ir.items():
        g = fn_diff.base(name)
        excl[g] = excl.get(g, 0) + ir
    incl.update(excl)
    for (caller, callee), ir in calls.items():
        g = fn_diff.base(caller)
        if fn_diff.base(callee) != g:
            incl[g] = incl.get(g, 0) + ir
    return excl, incl


def analyse(before, after, functions, top=10):
    (tb, sb, cb), (ta, sa, ca) = parse(before), parse(after)
    (eb, ib), (ea, ia) = groups(sb, cb), groups(sa, ca)
    row = {'ir_total': [tb, ta], 'ir_total_ratio': ta / tb, 'functions': {}}
    for f in functions:
        row['functions'][f] = {'exclusive': [eb.get(f, 0), ea.get(f, 0)], 'inclusive': [ib.get(f, 0), ia.get(f, 0)],
                               'clones': [sorted(n for n in sb if fn_diff.base(n) == f),
                                          sorted(n for n in sa if fn_diff.base(n) == f)]}
    deltas = sorted(((ea.get(g, 0) - eb.get(g, 0), g) for g in set(eb) | set(ea)), key=lambda x: (-abs(x[0]), x[1]))
    row['exclusive_delta_top'] = [[g, d] for d, g in deltas[:top] if d]
    return row


def run(exe, out, tag):
    cg = out / f'{tag}.callgrind'
    with (out / f'{tag}.log').open('w') as log:
        subprocess.run(['valgrind', '--tool=callgrind', f'--callgrind-out-file={cg}', str(exe), *BENCH_ARGS,
                        '--out', str(out / f'{tag}.json')], check=True, stdout=subprocess.DEVNULL, stderr=log)
    return cg, json.loads((out / f'{tag}.json').read_text())['record']


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pair', nargs=3, action='append', metavar=('PROFILE', 'BEFORE', 'AFTER'))
    p.add_argument('--analyse', nargs=2, metavar=('BEFORE', 'AFTER'))
    p.add_argument('--out')
    p.add_argument('--limit', type=float, default=1.010)
    p.add_argument('--function', action='append', default=[])
    a = p.parse_args()
    if a.analyse:
        print(json.dumps(analyse(*a.analyse, a.function), indent=1))
        return
    if not a.pair or not a.out:
        p.error('--pair and --out are required (or --analyse)')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {'workload': BENCH_ARGS, 'limit': a.limit, 'profiles': {}}
    for profile, before, after in a.pair:
        for exe in (before, after):
            assert os.access(exe, os.X_OK), f'{exe} is not executable'
        cb, rb = run(before, out, f'{profile}-before')
        ca, ra = run(after, out, f'{profile}-after')
        assert rb == ra, f'{profile}: the bench record differs'
        row = analyse(cb, ca, a.function)
        row['code_diff'] = fn_diff.compare(before, after)
        row['pass'] = row['ir_total_ratio'] <= a.limit
        result['profiles'][profile] = row
        print(profile, f"ir_total {row['ir_total'][0]} -> {row['ir_total'][1]} ratio {row['ir_total_ratio']:.6f}",
              'pass' if row['pass'] else 'FAIL', 'code differs in', row['code_diff']['differing_groups'], flush=True)
    (out / 'callgrind-gate.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    if not all(r['pass'] for r in result['profiles'].values()):
        sys.exit('callgrind gate failed')
    print('callgrind gate pass')


if __name__ == '__main__':
    main()
