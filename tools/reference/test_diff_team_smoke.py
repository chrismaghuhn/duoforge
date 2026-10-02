#!/usr/bin/env python3
"""A team file of the random mode end to end, with Node and the pinned Showdown: a team file that equals team A gives the
same battles as team A.

usage: python3 tools/reference/test_diff_team_smoke.py <node> <checkout> <runner> <work dir>

CTest runs it as duoforge.reference.diff_team_smoke. Six battles of `--pairings AB,BA` and the same six of
`--team D=<a copy of team A> --pairings DB,BD` (seed 5, two workers, no machine lock, the copy written with Windows line
ends): every record of the second run (battles.jsonl) must be that of the first, but for the letter D where the first
has an A; so must the buckets of the summary, and with --keep-traces the kept battles (their specs but for the purpose,
and their traces byte for byte). The identity of the second run (run.json) names the team file by its hash and data kind.
"""
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
TEAM_A = os.path.join(ROOT, 'tests', 'reference', 'teams', 'team_a.txt')
SEED, BATTLES, WORKERS = 5, 6, 2


def run_driver(node, checkout, runner, outdir, pairings, *extra):
    command = [sys.executable, DRIVER, 'random', '--checkout', checkout, '--node', node, '--runner', runner,
               '--battles', str(BATTLES), '--seed', str(SEED), '--pairings', pairings, '--workers', str(WORKERS),
               '--no-lock', '--keep-traces', '--out', outdir] + list(extra)
    done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = done.stdout.decode('utf-8', 'replace')
    if done.returncode != 0:
        sys.exit('the driver exited with status %d:\n%s' % (done.returncode, text))
    return text


def read(path):
    with io.open(path, 'rb') as f:
        return f.read()


def records(outdir):
    with io.open(os.path.join(outdir, 'battles.jsonl'), encoding='ascii') as f:
        return [json.loads(line) for line in f]


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__.strip().split('\n\n')[1])
    node, checkout, runner, work = argv
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    team = os.path.join(work, 'd.txt')
    with io.open(team, 'w', encoding='utf-8', newline='') as f:  # Windows line ends: no difference to the sets
        f.write(read(TEAM_A).decode('utf-8').replace('\r\n', '\n').replace('\n', '\r\n'))
    first, second = os.path.join(work, 'a'), os.path.join(work, 'd')
    run_driver(node, checkout, runner, first, 'AB,BA')
    run_driver(node, checkout, runner, second, 'DB,BD', '--team', 'D=' + team)
    a, d = records(first), records(second)
    if len(a) != BATTLES or len(d) != BATTLES:
        sys.exit('%d and %d battles, not %d' % (len(a), len(d), BATTLES))
    for x, y in zip(a, d):
        if y['pairing'].replace('D', 'A') != x['pairing']:
            sys.exit('battle %d: pairing %s for %s' % (x['index'], y['pairing'], x['pairing']))
        differ = [k for k in x if k != 'pairing' and x[k] != y[k]]
        if differ:
            sys.exit('battle %d of the team file differs from team A in %s:\n  %s\n  %s' % (
                x['index'], ', '.join(differ), {k: x[k] for k in differ}, {k: y[k] for k in differ}))
    with io.open(os.path.join(first, 'summary.json'), encoding='ascii') as f:
        sa = json.load(f)
    with io.open(os.path.join(second, 'summary.json'), encoding='ascii') as f:
        sd = json.load(f)
    if (sa['buckets'], sa['signatures'], sa['domain']) != (sd['buckets'], sd['signatures'], sd['domain']):
        sys.exit('the summaries differ: %s against %s' % (sa['buckets'], sd['buckets']))
    # The kept battles: the same specs but for the purpose (it says team D), and the same traces.
    kept_a = sorted(os.listdir(os.path.join(first, 'kept'))) if os.path.isdir(os.path.join(first, 'kept')) else []
    kept_d = sorted(os.listdir(os.path.join(second, 'kept'))) if os.path.isdir(os.path.join(second, 'kept')) else []
    if kept_a != kept_d or not kept_a:
        sys.exit('kept battles %s and %s (some PASS battle is expected)' % (kept_a, kept_d))
    for name in kept_a:
        spec_a = json.loads(read(os.path.join(first, 'kept', name, 'spec.json')).decode('utf-8'))
        spec_d = json.loads(read(os.path.join(second, 'kept', name, 'spec.json')).decode('utf-8'))
        if 'team D' not in spec_d['purpose'] or 'team D' in spec_a['purpose']:
            sys.exit('%s: the purpose does not name team D: %r' % (name, spec_d['purpose']))
        spec_a.pop('purpose'), spec_d.pop('purpose')
        if spec_a != spec_d:
            sys.exit('%s: the spec of the team file is not the spec of team A' % name)
        if read(os.path.join(first, 'kept', name, 'trace.json.gz')) != read(os.path.join(second, 'kept', name, 'trace.json.gz')):
            sys.exit('%s: the trace of the team file is not the trace of team A' % name)
    with io.open(os.path.join(second, 'run.json'), encoding='utf-8') as f:
        identity = json.load(f)
    if sorted(identity.get('teams', {})) != ['D'] or identity['teams']['D']['data'] != 'closure' \
            or len(identity['teams']['D']['sha256']) != 64 or 'teams' in json.load(
                io.open(os.path.join(first, 'run.json'), encoding='utf-8')):
        sys.exit('run.json does not hold the team file as it should: %s' % identity.get('teams'))
    print('diff_team_smoke: %d battles of a team file that equals team A are those of team A (%s)' % (
        BATTLES, ', '.join('%s %d' % (k, v) for k, v in sa['buckets'].items() if v)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
