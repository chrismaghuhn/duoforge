#!/usr/bin/env python3
"""Paired public-fixture benchmark; writes aggregate counters/timings only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import tempfile
import time


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def median_ci(values):
    rng = random.Random(20261012)
    draws = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(20000))
    return [draws[499], draws[19499]]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', required=True)
    p.add_argument('--after', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--rounds', type=int, default=30)
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--warmup', type=int, default=2)
    p.add_argument('--battles', type=int, default=512)
    p.add_argument('--cpu', type=int, default=max(os.sched_getaffinity(0)))
    p.add_argument('--ipo', choices=['on', 'off'], default='on')
    args = p.parse_args()
    assert args.rounds >= 15
    assert args.cpu in os.sched_getaffinity(0)
    binaries = dict(before=str(Path(args.before).resolve()), after=str(Path(args.after).resolve()))
    started = time.time()
    rounds = []
    manifests = {}
    record = None
    choices = None
    results = dict(protocol=dict(rounds=args.rounds, repetitions=args.repetitions,
        warmup=args.warmup, battles_per_pairing=args.battles, cpu_affinity=[args.cpu],
        order='AB on odd rounds, BA on even rounds; all samples retained',
        bootstrap='20000 paired-resample medians, seed 20261012, percentile 95% CI',
        gate='median after/before time <= 1.02, within baseline min/max relative spread',
        ipo=args.ipo, cgroup_cpu_max=Path('/sys/fs/cgroup/cpu.max').read_text().strip()),
        binaries={key: dict(path=path, sha256=sha256(path)) for key, path in binaries.items()},
        rounds=rounds)
    with tempfile.TemporaryDirectory(prefix='duoforge-paired-') as temporary:
        for number in range(1, args.rounds + 1):
            order = ['before', 'after'] if number % 2 else ['after', 'before']
            row = dict(round=number, order=order, profiles={})
            for profile in order:
                output = Path(temporary) / f'{number}-{profile}.json'
                command = [binaries[profile], '--battles', str(args.battles), '--repetitions',
                    str(args.repetitions), '--warmup', str(args.warmup), '--max-steps', '128',
                    '--policy-seed', '20261001', '--battle-seed', '7001',
                    '--families', 'step,events', '--out', str(output)]
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    preexec_fn=lambda: os.sched_setaffinity(0, {args.cpu}))
                data = json.loads(output.read_text())
                assert data['errors'] == 0 and data['skipped_by_time_limit'] == 0
                assert data['record']['errors'] == 0 and data['record']['truncations'] == 0
                if record is None:
                    record, choices = data['record'], data['choices']
                assert data['record'] == record and data['choices'] == choices
                manifests.setdefault(profile, data['manifest'])
                assert data['manifest']['ipo'] == (args.ipo == 'on')
                if len(manifests) == 2:
                    for field in ('compiler', 'build_type', 'c_flags', 'ipo', 'workload',
                                  'context_fingerprint', 'policy_seed', 'battle_seed',
                                  'max_steps', 'battles_per_pairing', 'pairings', 'workers'):
                        assert manifests['before'][field] == manifests['after'][field], field
                row['profiles'][profile] = {r['variant']: dict(wall_ns=r['wall_ns'],
                    cpu_ns=r['cpu_ns'], disturbed=r['disturbed_repetitions'],
                    median_wall_ns=statistics.median(r['wall_ns']), errors=r['errors'])
                    for r in data['results']}
            row['time_ratios'] = {key: row['profiles']['after'][key]['median_wall_ns'] /
                row['profiles']['before'][key]['median_wall_ns'] for key in ['plain', 'events']}
            rounds.append(row)
            print(f"Round {number:02}/{args.rounds}: " + ' '.join(f'{k}={v:.5f}' for k,v in row['time_ratios'].items()), flush=True)
            Path(args.out).write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')
    summaries = {}
    for variant in ['plain', 'events']:
        ratios = [row['time_ratios'][variant] for row in rounds]
        baseline = [row['profiles']['before'][variant]['median_wall_ns'] for row in rounds]
        after = [row['profiles']['after'][variant]['median_wall_ns'] for row in rounds]
        centre = statistics.median(baseline)
        spread = [min(baseline)/centre, max(baseline)/centre]
        ratio = statistics.median(ratios)
        summaries[variant] = dict(median_time_ratio=ratio, median_throughput_ratio=1/ratio,
            change_percent=100*(ratio-1), ratio_range=[min(ratios), max(ratios)],
            paired_bootstrap_95ci=median_ci(ratios),
            baseline_median_ms=centre/1e6, after_median_ms=statistics.median(after)/1e6,
            baseline_relative_spread=spread,
            baseline_sample_ms=[v/1e6 for v in baseline], after_sample_ms=[v/1e6 for v in after],
            within_baseline_spread=spread[0] <= ratio <= spread[1],
            median_loss_at_most_2_percent=ratio <= 1.02,
            disturbed_repetitions={profile:sum(row['profiles'][profile][variant]['disturbed'] for row in rounds)
                for profile in ['before', 'after']})
    results.update(manifests=manifests, record=record, choices=choices,
        summaries=summaries, elapsed_seconds=time.time()-started)
    Path(args.out).write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summaries, indent=2), flush=True)


if __name__ == '__main__':
    main()
