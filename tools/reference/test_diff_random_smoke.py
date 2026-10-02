#!/usr/bin/env python3
"""The random mode of the driver end to end, with Node and the pinned Showdown: 16 battles that the reference
plays itself (AB, BA, AA, BB, seed 2, two workers, no machine lock) through worker, converter and runner, twice.

usage: python3 tools/reference/test_diff_random_smoke.py <node> <checkout> <runner> <work dir> [--update-golden]

CTest runs it as duoforge.reference.diff_random_smoke. It requires

 - that both runs end with status 0 and that battles.jsonl, summary.json, run.json and cases/ of the two are
   byte-identical (determinism: the same arguments make the same files; timing.json is the one that differs);
 - that the buckets, the (bucket, rule, detail) signatures with their counts and, for every battle, its pairing,
   bucket and number of steps are those of tests/reference/random_smoke_golden.json. The number of steps ties the
   derivation of battle i and the policy of ps_play.js to the golden: a change of either is seen here.

With --update-golden the golden is written from the first run (after a change that is meant to change these
battles: a new pin, a new policy, a fix of a finding that the golden names). The golden holds no versions.
"""
import difflib
import io
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DRIVER = os.path.join(HERE, 'diff_driver.py')
GOLDEN = os.path.join(ROOT, 'tests', 'reference', 'random_smoke_golden.json')
SEED = 2
BATTLES = 16
PAIRINGS = 'AB,BA,AA,BB'
WORKERS = 2
IDENTICAL = ('battles.jsonl', 'summary.json', 'run.json')  # and cases/; the rest holds timings


def run_driver(node, checkout, runner, outdir):
    command = [sys.executable, DRIVER, 'random', '--checkout', checkout, '--node', node, '--runner', runner,
               '--battles', str(BATTLES), '--seed', str(SEED), '--pairings', PAIRINGS, '--workers', str(WORKERS),
               '--no-lock', '--out', outdir]
    done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = done.stdout.decode('utf-8', 'replace')
    if done.returncode != 0:
        sys.exit('the driver exited with status %d:\n%s' % (done.returncode, text))
    return text


def read(path):
    with io.open(path, 'rb') as f:
        return f.read()


def tree(root):
    """{relative path: bytes} of the files that must be identical between two runs."""
    out = {}
    for name in IDENTICAL:
        out[name] = read(os.path.join(root, name))
    cases = os.path.join(root, 'cases')
    for base, _, files in os.walk(cases):
        for fname in files:
            full = os.path.join(base, fname)
            out[os.path.relpath(full, root).replace(os.sep, '/')] = read(full)
    return out


def observed(outdir):
    """What the golden holds of a run: its parameters, the buckets, the signatures and one line per battle."""
    with io.open(os.path.join(outdir, 'summary.json'), encoding='ascii') as f:
        summary = json.load(f)
    with io.open(os.path.join(outdir, 'battles.jsonl'), encoding='ascii') as f:
        battles = [json.loads(line) for line in f]
    return {
        'seed': summary['seed'], 'battles': summary['battles'], 'pairings': summary['pairings'], 'policy': summary['policy'],
        'buckets': summary['buckets'],
        'signatures': [{'bucket': s['bucket'], 'rule': s['rule'], 'detail': s['detail'], 'count': s['count']}
                       for s in summary['signatures']],
        'battle_lines': ['%s %s %s' % (b['pairing'], b['bucket'], '-' if b['steps'] is None else b['steps']) for b in battles],
    }


def dump(value):
    """The golden as text: the parameters, buckets and signatures indented, then one line per battle."""
    head = json.dumps({k: v for k, v in value.items() if k != 'battle_lines'}, indent=1, sort_keys=True)
    assert head.endswith('\n}')
    battles = ',\n'.join('  %s' % json.dumps(line) for line in value['battle_lines'])
    return head[:-2] + ',\n "battle_lines": [\n' + battles + '\n ]\n}\n'


def main(argv):
    update = '--update-golden' in argv
    args = [a for a in argv if a != '--update-golden']
    if len(args) != 4:
        sys.exit(__doc__.strip().split('\n\n')[1])
    node, checkout, runner, work = args
    shutil.rmtree(work, ignore_errors=True)
    outs = [os.path.join(work, name) for name in ('first', 'second')]
    for outdir in outs:
        run_driver(node, checkout, runner, outdir)
    first, second = tree(outs[0]), tree(outs[1])
    if sorted(first) != sorted(second):
        sys.exit('the two runs made different files: %s' % sorted(set(first) ^ set(second)))
    differ = [name for name in sorted(first) if first[name] != second[name]]
    if differ:
        sys.exit('the two runs made different bytes in %s' % ', '.join(differ))
    have = observed(outs[0])
    if update:
        with io.open(GOLDEN, 'w', encoding='utf-8', newline='\n') as f:
            f.write(dump(have))
        print('wrote %s' % GOLDEN)
        return 0
    with io.open(GOLDEN, encoding='utf-8') as f:
        want_text = f.read()
    want = json.loads(want_text)
    if have != want:
        diff = difflib.unified_diff(want_text.split('\n'), dump(have).split('\n'), 'golden', 'this run', lineterm='')
        sys.exit('this run is not the golden (tests/reference/random_smoke_golden.json; --update-golden writes it):\n%s'
                 % '\n'.join(diff))
    print('diff_random_smoke: %d battles, twice, byte-identical; buckets %s as in the golden' % (
        have['battles'], ', '.join('%s %d' % (k, v) for k, v in have['buckets'].items() if v)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
