#!/usr/bin/env python3
"""Random play under the POOL data kind end to end, with Node and the pinned Showdown: a team that carries Wide Guard
(step G7) plays battles that all PASS under POOL (the engine's candidates are what Showdown accepts at every request,
and every event, draw and state of the battle equals the reference's), and some of them guard with Wide Guard and stop
a spread move at a guarded target.

usage: python3 tools/reference/test_diff_wide_guard_smoke.py <node> <checkout> <runner> <work dir>

CTest runs it as duoforge.reference.diff_wide_guard_smoke. Ten battles of `--team D=tests/reference/teams/team_pivot.txt
--pairings DA,AD,DC,DD,DB` (seed 5, two workers, no machine lock, --keep-traces): the team has U-turn (an id of the pool
tables that Team C does not have), so run.json holds it as pool data and every battle of its pairings is created under POOL
and PASSes; the kept traces hold at least one switch with [from] U-turn, so the pivot path ran; and a battle of the same
seed between A and B (closure data) is not changed by the others being there.
"""
import gzip
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
TEAM = os.path.join(ROOT, 'tests', 'reference', 'teams', 'team_wide_guard.txt')
SEED, BATTLES, WORKERS = 7, 20, 2


def run_driver(node, checkout, runner, outdir, pairings, *extra):
    command = [sys.executable, DRIVER, 'random', '--checkout', checkout, '--node', node, '--runner', runner,
               '--battles', str(BATTLES), '--seed', str(SEED), '--pairings', pairings, '--workers', str(WORKERS),
               '--domain-rate', '1.0', '--no-lock', '--keep-traces', '--out', outdir] + list(extra)
    done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = done.stdout.decode('utf-8', 'replace')
    if done.returncode != 0:
        sys.exit('the driver exited with status %d:\n%s' % (done.returncode, text))
    return text


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__.strip().split('\n\n')[1])
    node, checkout, runner, work = argv
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    out = os.path.join(work, 'pool')
    run_driver(node, checkout, runner, out, 'DA,AD,DC,DD,DB', '--team', 'D=' + TEAM)
    with io.open(os.path.join(out, 'battles.jsonl'), encoding='ascii') as f:
        records = [json.loads(line) for line in f]
    if len(records) != BATTLES:
        sys.exit('%d battles, not %d' % (len(records), BATTLES))
    bad = [(r['name'], r['pairing'], r['bucket'], r['detail']) for r in records if r['bucket'] != 'PASS']
    if bad:
        sys.exit('battles of the Wide Guard team that do not PASS: %s' % bad)
    wrong = [(r['name'], r['context']) for r in records if r['context'] != 'POOL']
    if wrong:
        sys.exit('battles that did not run under POOL: %s' % wrong)
    with io.open(os.path.join(out, 'run.json'), encoding='utf-8') as f:
        identity = json.load(f)
    team = identity.get('teams', {}).get('D')
    if team is None or team['data'] != 'pool' or len(team['sha256']) != 64:
        sys.exit('run.json does not hold the Wide Guard team as pool data: %s' % identity.get('teams'))
    guards = stops = 0
    for name in sorted(os.listdir(os.path.join(out, 'kept'))):
        with gzip.open(os.path.join(out, 'kept', name, 'trace.json.gz')) as f:
            trace = json.loads(f.read().decode('utf-8'))
        with io.open(os.path.join(out, 'kept', name, 'spec.json'), encoding='utf-8') as f:
            spec = json.load(f)
        if spec.get('data') != 'pool':
            sys.exit('%s: the spec is not pool data: %r' % (name, spec.get('data')))
        for step in trace['steps']:
            for line in step['log']:
                guards += line.endswith('|Wide Guard') and line.startswith('|-singleturn|')
                stops += line.endswith('|move: Wide Guard') and line.startswith('|-activate|')
    if guards == 0 or stops == 0:
        sys.exit('%d Wide Guard lines and %d stopped targets in the %d battles: the guard path did not run'
                 % (guards, stops, BATTLES))
    # Closure data is what it was: a run of A against B alone.
    other = os.path.join(work, 'ab')
    run_driver(node, checkout, runner, other, 'AB,BA')
    with io.open(os.path.join(other, 'battles.jsonl'), encoding='ascii') as f:
        ab = [json.loads(line) for line in f]
    if any(r['bucket'] != 'PASS' or r['context'] != 'CLOSURE' for r in ab):
        sys.exit('A against B does not PASS under CLOSURE: %s' % [(r['name'], r['bucket'], r['context']) for r in ab])
    print('diff_wide_guard_smoke: %d battles of the Wide Guard team PASS under POOL, %d guards, %d stopped targets'
          % (BATTLES, guards, stops))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
