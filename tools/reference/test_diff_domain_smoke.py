#!/usr/bin/env python3
"""The domain check of the differential loop end to end, with Node and the pinned Showdown: 8 battles that the
reference plays itself (AB, BA, AA, BB, seed 6, two workers, no machine lock) with every request sampled
(--domain-rate 1.0): the set of choices that Showdown accepts, judged option by option, against the engine's
candidates for the side, before every step.

usage: python3 tools/reference/test_diff_domain_smoke.py <node> <checkout> <runner> <work dir>

CTest runs it as duoforge.reference.diff_domain_smoke. The same 8 battles are run once more without the check
(--domain-rate 0). It requires

 - that both runs end with status 0 and that every battle of both is PASS: the engine's candidates are what Showdown
   accepts, at team preview, at every turn and at every replacement of these battles;
 - that nothing else about a battle depends on the check: its pairing, bucket, number of steps and end are the same in
   the two runs (sampling is decided by a hash of the policy seed, the step and the side, never by the generator that
   draws the choices, and what judging does to a request is put back);
 - that the check was made: with the rate 1.0 every request is compared (or counted as changed), that is at least one
   per step of every battle, and none without.
"""
import io
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'diff_driver.py')
SEED = 6
BATTLES = 8
PAIRINGS = 'AB,BA,AA,BB'
WORKERS = 2


def run_driver(node, checkout, runner, outdir, rate):
    command = [sys.executable, DRIVER, 'random', '--checkout', checkout, '--node', node, '--runner', runner,
               '--battles', str(BATTLES), '--seed', str(SEED), '--pairings', PAIRINGS, '--workers', str(WORKERS),
               '--domain-rate', rate, '--no-lock', '--out', outdir]
    done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = done.stdout.decode('utf-8', 'replace')
    if done.returncode != 0:
        sys.exit('the driver exited with status %d (--domain-rate %s):\n%s' % (done.returncode, rate, text))
    with io.open(os.path.join(outdir, 'battles.jsonl'), encoding='ascii') as f:
        battles = [json.loads(line) for line in f]
    with io.open(os.path.join(outdir, 'summary.json'), encoding='ascii') as f:
        summary = json.load(f)
    return battles, summary, text


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__.strip().split('\n\n')[1])
    node, checkout, runner, work = argv
    shutil.rmtree(work, ignore_errors=True)
    sampled, summary, text = run_driver(node, checkout, runner, os.path.join(work, 'sampled'), '1.0')
    plain, plain_summary, _ = run_driver(node, checkout, runner, os.path.join(work, 'plain'), '0')
    for name, battles in (('with the domain check', sampled), ('without it', plain)):
        bad = [(b['name'], b['bucket'], b['detail']) for b in battles if b['bucket'] != 'PASS']
        if bad:
            sys.exit('not every battle %s is PASS: %s\n%s' % (name, bad, text))
    without = lambda b: {k: v for k, v in b.items() if k != 'domain'}
    if [without(b) for b in sampled] != [without(b) for b in plain]:
        diff = [(a['name'], a['steps'], b['steps']) for a, b in zip(sampled, plain) if without(a) != without(b)]
        sys.exit('the check changed what a battle comes to: %s' % diff)
    if len(sampled) != BATTLES or not all(b['steps'] >= 2 for b in sampled):
        sys.exit('the battles are not the 8 of the test: %s' % [(b['name'], b['steps']) for b in sampled])
    for b in sampled:
        d = b['domain']
        # One request per step at least (a step with both sides asked has two), every one compared or counted.
        if not b['steps'] <= d['samples'] + d['request_changed'] <= 2 * b['steps']:
            sys.exit('%s: %d steps and %d requests compared or changed' % (b['name'], b['steps'], d['samples'] + d['request_changed']))
    if any(b['domain'] != {'samples': 0, 'request_changed': 0} for b in plain):
        sys.exit('requests were compared without --domain-rate: %s' % [b['domain'] for b in plain])
    if summary['domain']['rate'] != 1.0 or plain_summary['domain']['rate'] != 0.0:
        sys.exit('the rates of the runs are %s and %s' % (summary['domain']['rate'], plain_summary['domain']['rate']))
    total = summary['domain']['samples'] + summary['domain']['request_changed']
    print('diff_domain_smoke: %d battles, %d requests compared with what Showdown accepts (%d dropped as changed), all PASS, '
          'and the same battles without the check' % (BATTLES, summary['domain']['samples'], summary['domain']['request_changed']))
    return 0 if total > 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
