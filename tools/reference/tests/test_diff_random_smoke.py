#!/usr/bin/env python3
"""The random mode of the driver end to end, with Node and the pinned Showdown: 16 battles that the reference
plays itself (AB, BA, AA, BB, seed 2, two workers, no machine lock) through worker, converter and runner.

usage: python3 tools/reference/test_diff_random_smoke.py <node> <checkout> <runner> <work dir> [--update-golden]

CTest runs it as duoforge.reference.diff_random_smoke. The battles are run three times: twice as one run, and a
third time in pieces (the second half of the battles as one chunk, then what is left as another, then a run that
writes the files). It requires

 - that every run ends with status 0 and that battles.jsonl, summary.json, run.json and cases/ of the three are
   byte-identical (determinism, and a result that does not depend on the order or the cut in which the battles
   ran; timing.json is the one that differs);
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


def run_driver(node, checkout, runner, outdir, *extra):
    command = [sys.executable, DRIVER, 'random', '--checkout', checkout, '--node', node, '--runner', runner,
               '--battles', str(BATTLES), '--seed', str(SEED), '--pairings', PAIRINGS, '--workers', str(WORKERS),
               '--no-lock', '--out', outdir] + list(extra)
    done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = done.stdout.decode('utf-8', 'replace')
    if done.returncode != 0:
        sys.exit('the driver exited with status %d (%s):\n%s' % (done.returncode, ' '.join(extra) or 'one run', text))
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
    first, second, pieces = (os.path.join(work, name) for name in ('first', 'second', 'pieces'))
    run_driver(node, checkout, runner, first)
    run_driver(node, checkout, runner, second)
    # In pieces: the second half first, then the rest, each as one chunk (it writes the results of its battles and
    # no summary), then a run that has nothing left to run and writes the files.
    half = str(BATTLES // 2)
    run_driver(node, checkout, runner, pieces, '--start', half, '--chunk-minutes', '1')
    run_driver(node, checkout, runner, pieces, '--chunk-minutes', '1')
    if os.path.exists(os.path.join(pieces, 'summary.json')):
        sys.exit('a chunk wrote the summary: only the process that owns the run does')
    run_driver(node, checkout, runner, pieces)
    expected = tree(first)
    for name, outdir in (('the second run', second), ('the run in pieces', pieces)):
        have = tree(outdir)
        if sorted(have) != sorted(expected):
            sys.exit('%s made other files than the first: %s' % (name, sorted(set(have) ^ set(expected))))
        differ = [f for f in sorted(have) if have[f] != expected[f]]
        if differ:
            sys.exit('%s made other bytes than the first in %s' % (name, ', '.join(differ)))
    have = observed(first)
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
    print('diff_random_smoke: %d battles, run twice and in pieces, byte-identical; buckets %s as in the golden' % (
        have['battles'], ', '.join('%s %d' % (k, v) for k, v in have['buckets'].items() if v)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
