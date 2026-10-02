#!/usr/bin/env python3
"""The raw speed of the engine on the fuzz box (tools/cloud/aws_fuzz/README.md, `bench=1` in a campaign.conf).

Runs the native batch benchmark of the repository (`duoforge_bench --families batch`, decision 0012: the loop over
the games runs in C on a pool of worker threads, no Python and no Showdown) on every vCPU of the machine for about
`--seconds` seconds, and on 16 threads for about a third of that (the owner's PC plays 16 threads, so the two
numbers compare). One run is one invocation of duoforge_bench: it records the workload once (the closure pairings,
5000 battles per pairing) and plays it 32 times; invocations repeat until the time is used. The result is the
median over the runs of the benchmark's own per-second figures.

usage: bench_run.py --bench "<duoforge_bench command>" --vcpus N --out bench.json [--seconds 30]
                    [--instance-type T] [--campaign ID] [--commit SHA]

bench.json: games_per_second, decisions_per_second (the two sides' decisions), steps_per_second, threads (all
vCPUs), instance_type, the same figures for 16 threads under "threads_16", and every run. Exit status 0 when every
run succeeded and reported no error."""
import argparse
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time

BATTLES_PER_PAIRING = 5000
REPETITIONS = 32
WARMUP = 1
COMPARE_THREADS = 16


def one_invocation(command, threads, out_path):
    """One run of duoforge_bench's batch family with `threads` workers; (the result entry, wall seconds)."""
    argv = list(command) + ['--families', 'batch', '--workers', str(threads), '--battles', str(BATTLES_PER_PAIRING),
                            '--repetitions', str(REPETITIONS), '--warmup', str(WARMUP), '--out', out_path]
    t0 = time.monotonic()
    subprocess.run(argv, check=True, stdout=subprocess.DEVNULL)
    wall = time.monotonic() - t0
    with open(out_path, encoding='utf-8') as f:
        data = json.load(f)
    if data.get('errors'):
        raise RuntimeError('duoforge_bench reported %s error(s)' % data['errors'])
    entries = [r for r in data['results'] if r['family'] == 'batch']
    if len(entries) != 1:
        raise RuntimeError('expected one batch result, got %d' % len(entries))
    entry = entries[0]
    if entry.get('errors'):
        raise RuntimeError('the batch family reported %s error(s)' % entry['errors'])
    return entry, wall


def measure(command, threads, seconds, workdir):
    """Invocations until `seconds` have passed (at least one); the figures are the medians of the runs."""
    runs = []
    t_end = time.monotonic() + seconds
    k = 0
    while True:
        entry, wall = one_invocation(command, threads, os.path.join(workdir, 'run-%d-%d.json' % (threads, k)))
        k += 1
        runs.append({'wall_seconds': round(wall, 3), 'median_wall_ns': entry['median_wall_ns'],
                     'disturbed_repetitions': entry['disturbed_repetitions'], 'per_second': entry['per_second'],
                     'games_per_repetition': entry['battles']})
        if time.monotonic() >= t_end:
            break

    def med(key):
        return int(statistics.median(r['per_second'][key] for r in runs))
    return {'threads': threads, 'games_per_second': med('battles'), 'decisions_per_second': med('side_decisions'),
            'steps_per_second': med('steps'), 'runs': runs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--bench', required=True, help='the duoforge_bench command (a path; split like a shell would)')
    ap.add_argument('--vcpus', type=int, required=True, help='threads for the main measurement: every vCPU')
    ap.add_argument('--seconds', type=float, default=30.0, help='time for the all-vCPU measurement (default 30)')
    ap.add_argument('--instance-type', default='unknown')
    ap.add_argument('--campaign', default='')
    ap.add_argument('--commit', default='')
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    if args.vcpus < 1 or args.seconds <= 0:
        ap.error('--vcpus must be at least 1 and --seconds positive')
    command = shlex.split(args.bench)
    with tempfile.TemporaryDirectory(prefix='bench_run_') as workdir:
        main_result = measure(command, args.vcpus, args.seconds, workdir)
        compare = measure(command, COMPARE_THREADS, args.seconds / 3, workdir) if args.vcpus > COMPARE_THREADS else None
    result = {'campaign': args.campaign, 'commit': args.commit, 'instance_type': args.instance_type,
              'vcpus': args.vcpus, 'threads': main_result['threads'],
              'games_per_second': main_result['games_per_second'],
              'decisions_per_second': main_result['decisions_per_second'],
              'steps_per_second': main_result['steps_per_second'],
              'workload': 'closure-pairings-v1, %d battles per pairing, %d repetitions' % (BATTLES_PER_PAIRING, REPETITIONS),
              'runs': main_result['runs'], 'threads_16': compare}
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, indent=1)
        f.write('\n')
    print('bench: %d games/s, %d decisions/s on %d threads (%s)' % (
        result['games_per_second'], result['decisions_per_second'], result['threads'], args.instance_type))
    if compare is not None:
        print('bench: %d games/s on %d threads' % (compare['games_per_second'], compare['threads']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
