#!/usr/bin/env python3
"""A/B comparison of two builds of duoforge_bench on one machine (tools/cloud/gcp_watch/README.md, "A bench round").

Runs `duoforge_bench` of build A and of build B alternately (A B, B A, A B, ...: the order flips every round, so a drift
of the machine does not favour one side), `--rounds` times, with the same families, workload and worker counts, and
writes bench.json: per family and per side the median, the minimum, the maximum and the spread of the benchmark's own
median wall time over the rounds, the cost per call where the family counts calls (copy and codec: one call is one
restored state), the paired ratio B/A of every round, and what each build said about itself (revision, workload
fingerprint). Nothing here measures anything itself: the numbers are those of duoforge_bench.

usage: bench_ab.py --a-bin CMD --b-bin CMD --a-sha SHA --b-sha SHA --out bench.json [--families copy,codec,batch]
                   [--workers 1] [--rounds 5] [--battles 400] [--repetitions 7] [--warmup 1] [--run ID]
       bench_ab.py --validate-only --a-sha SHA --b-sha SHA [--families ...] [--workers ...] --out FILE
                   (checks the values and exits, nothing is run: round.sh does it before the first build)

A family that is not one of duoforge_bench's (bench/main.c) is refused before anything runs, and a requested family that
a build did not report is an error: duoforge_bench itself ignores a name it does not know. A failure is written to
bench.json ("error") and the exit status is 1. The one-thread families (step, events, request, copy, codec, episode)
run on one thread; batch runs on the worker counts of --workers (default 1)."""
import argparse
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import tempfile

# The families of duoforge_bench in the order of bench/main.c (a test compares this list with that file).
FAMILIES = ('step', 'events', 'request', 'copy', 'codec', 'episode', 'batch')
DEFAULT_FAMILIES = 'copy,codec,batch'
# (family, variant) of a result entry -> the name of the family on the command line. batch: one entry per worker count.
ENTRY_FAMILY = {('STEP_CORE', 'plain'): 'step', ('STEP_CORE', 'events'): 'events', ('REQUEST', None): 'request',
                ('SNAPSHOT', 'copy'): 'copy', ('SNAPSHOT', 'codec'): 'codec', ('EPISODE_NATIVE', None): 'episode'}
SHA_RE = re.compile(r'^[0-9a-f]{40}$')


class BenchError(Exception):
    pass


def parse_families(text):
    """The list of families, in the order given, or BenchError for an empty list, a repeat or an unknown name."""
    names = text.split(',') if text else []
    if not names or '' in names:
        raise BenchError('the family list "%s" is empty or has an empty name' % text)
    unknown = [n for n in names if n not in FAMILIES]
    if unknown:
        raise BenchError('unknown benchmark famil%s %s (duoforge_bench has: %s)' % (
            'y' if len(unknown) == 1 else 'ies', ', '.join(unknown), ','.join(FAMILIES)))
    if len(set(names)) != len(names):
        raise BenchError('the family list "%s" names a family twice' % text)
    return names


def parse_workers(text):
    try:
        workers = [int(w) for w in text.split(',')]
    except ValueError:
        raise BenchError('--workers "%s" is not a list of whole numbers' % text) from None
    if not workers or any(w < 1 or w > 256 for w in workers) or len(set(workers)) != len(workers):
        raise BenchError('--workers "%s": distinct counts between 1 and 256' % text)
    return workers


def entry_key(entry):
    """The key of one result entry of duoforge_bench in bench.json ('copy', 'batch/workers=1', ...), or None for an
    entry that no family of the command line produces."""
    family, variant = entry.get('family'), entry.get('variant')
    if family == 'BATCH_NATIVE':
        return 'batch/' + variant
    return ENTRY_FAMILY.get((family, variant)) or ENTRY_FAMILY.get((family, None))


def expected_keys(families, workers):
    keys = []
    for f in families:
        if f == 'batch':
            keys.extend('batch/workers=%d' % w for w in workers)
        else:
            keys.append(f)
    return keys


def run_invocation(command, argv, out_path, timeout):
    """One run of duoforge_bench: its JSON report (the file of --out); the text on its stderr goes to ours."""
    full = list(command) + argv + ['--out', out_path]
    try:
        subprocess.run(full, check=True, stdout=subprocess.DEVNULL, timeout=timeout)
    except subprocess.CalledProcessError as e:
        raise BenchError('duoforge_bench exited with status %d (%s)' % (e.returncode, ' '.join(full))) from None
    except subprocess.TimeoutExpired:
        raise BenchError('duoforge_bench did not finish in %s seconds (%s)' % (timeout, ' '.join(full))) from None
    except OSError as e:
        raise BenchError('duoforge_bench could not be started: %s' % e) from None
    with open(out_path, encoding='utf-8') as f:
        return json.load(f)


def collect(data, keys, side, sha):
    """The entries of one report by key; checks the errors of the report and its revision. Returns (entries, manifest)."""
    if data.get('errors'):
        raise BenchError('build %s: duoforge_bench reported %s error(s)' % (side, data['errors']))
    manifest = data.get('manifest') or {}
    revision = manifest.get('revision')
    if revision is not None and revision != sha:
        raise BenchError('build %s reports revision %s, not %s: the binary is not the commit it is labelled with' % (
            side, revision, sha))
    entries = {}
    for entry in data.get('results', []):
        key = entry_key(entry)
        if key in keys:
            if key in entries:
                raise BenchError('build %s: the result "%s" is reported twice' % (side, key))
            if entry.get('errors'):
                raise BenchError('build %s: the result "%s" reports %s error(s)' % (side, key, entry['errors']))
            entries[key] = entry
    missing = [k for k in keys if k not in entries]
    if missing:
        raise BenchError('build %s did not report: %s (families in the file: %s)' % (
            side, ', '.join(missing), sorted({r.get('family') for r in data.get('results', [])})))
    return entries, manifest


def stats(samples):
    med = statistics.median(samples)
    return {'samples': samples, 'median': med, 'min': min(samples), 'max': max(samples),
            'spread_percent': round(100.0 * (max(samples) - min(samples)) / med, 2) if med else None}


def summarize(key, per_side, order):
    """per_side: {'a': [entry per round], 'b': [...]}; order: the rounds' order, for the record."""
    out = {}
    for side in ('a', 'b'):
        entries = per_side[side]
        wall = stats([e['median_wall_ns'] for e in entries])
        item = {'median_wall_ns': wall, 'disturbed_repetitions': sum(e['disturbed_repetitions'] for e in entries),
                'per_second_battles': int(statistics.median(e['per_second']['battles'] for e in entries))}
        calls = entries[0].get('calls', 0)
        if calls:  # copy and codec: one call is one restored state
            item['calls_per_repetition'] = calls
            item['ns_per_call'] = {k: round(wall[k] / calls, 2) for k in ('median', 'min', 'max')}
            item['calls_per_second'] = int(statistics.median(e['per_second']['calls'] for e in entries))
        if entries[0].get('bytes'):
            item['bytes_per_state'] = entries[0]['bytes']
        out[side] = item
    paired = [b['median_wall_ns'] / a['median_wall_ns'] for a, b in zip(per_side['a'], per_side['b'])]
    out['ratio_b_over_a'] = {'of_medians': round(out['b']['median_wall_ns']['median'] / out['a']['median_wall_ns']['median'], 4),
                             'paired_median': round(statistics.median(paired), 4), 'paired_min': round(min(paired), 4),
                             'paired_max': round(max(paired), 4)}
    return out


def measure(args, families, workers, workdir):
    keys = expected_keys(families, workers)
    commands = {'a': shlex.split(args.a_bin), 'b': shlex.split(args.b_bin)}
    shas = {'a': args.a_sha, 'b': args.b_sha}
    argv = ['--families', ','.join(families)]
    if workers:  # only the batch family has worker counts
        argv += ['--workers', ','.join(str(w) for w in workers)]
    argv += ['--battles', str(args.battles), '--repetitions', str(args.repetitions), '--warmup', str(args.warmup)]
    per_side = {k: {'a': [], 'b': []} for k in keys}
    manifests = {}
    order = []
    for rnd in range(args.rounds):
        sides = ('a', 'b') if rnd % 2 == 0 else ('b', 'a')  # the order flips every round
        order.append(''.join(sides))
        for side in sides:
            print('bench_ab: round %d/%d, build %s (%s)' % (rnd + 1, args.rounds, side.upper(), shas[side][:12]), flush=True)
            data = run_invocation(commands[side], argv, os.path.join(workdir, 'run-%d-%s.json' % (rnd, side)), args.timeout)
            entries, manifest = collect(data, keys, side.upper(), shas[side])
            manifests[side] = manifest
            for key in keys:
                per_side[key][side].append(entries[key])
    return keys, per_side, manifests, order


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--validate-only', action='store_true', help='check the shas, families and workers, then exit')
    ap.add_argument('--a-bin', help='the duoforge_bench command of build A (split like a shell would)')
    ap.add_argument('--b-bin', help='the duoforge_bench command of build B')
    ap.add_argument('--a-sha', required=True, help='the commit build A was made from (40 digits)')
    ap.add_argument('--b-sha', required=True, help='the commit build B was made from (40 digits)')
    ap.add_argument('--families', default=DEFAULT_FAMILIES)
    ap.add_argument('--workers', default='1', help='worker counts of the batch family (default 1)')
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--battles', type=int, default=400, help='battles per pairing of the workload')
    ap.add_argument('--repetitions', type=int, default=7)
    ap.add_argument('--warmup', type=int, default=1)
    ap.add_argument('--timeout', type=float, default=1200.0, help='seconds for one invocation of duoforge_bench')
    ap.add_argument('--run', default='')
    ap.add_argument('--instance-type', default='unknown')
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    result = {'schema': 1, 'run': args.run, 'a': {'sha': args.a_sha}, 'b': {'sha': args.b_sha},
              'instance_type': args.instance_type, 'vcpus': os.cpu_count()}
    try:
        for side, sha in (('a', args.a_sha), ('b', args.b_sha)):
            if not SHA_RE.match(sha):
                raise BenchError('--%s-sha "%s" is not a 40-digit commit' % (side, sha))
        if args.rounds < 1 or args.battles < 1 or args.repetitions < 1 or args.warmup < 0:
            raise BenchError('--rounds, --battles and --repetitions must be at least 1')
        families = parse_families(args.families)
        workers = parse_workers(args.workers) if 'batch' in families else []
        result.update({'families': families, 'workers': workers, 'rounds': args.rounds, 'battles_per_pairing': args.battles,
                       'repetitions': args.repetitions, 'warmup': args.warmup,
                       'order': 'alternating, the first listed build first in round 1'})
        if args.validate_only:
            result['validated'] = True
        else:
            if not (args.a_bin and args.b_bin):
                raise BenchError('--a-bin and --b-bin are required')
            with tempfile.TemporaryDirectory(prefix='bench_ab_') as workdir:
                keys, per_side, manifests, order = measure(args, families, workers, workdir)
            result['rounds_order'] = order
            for side in ('a', 'b'):
                m = manifests[side]
                result[side].update({k: m.get(k) for k in ('engine', 'revision', 'dirty', 'compiler', 'build_type', 'ipo',
                                                           'cpu', 'context_fingerprint', 'workload')})
            result['same_workload_fingerprint'] = result['a'].get('context_fingerprint') == result['b'].get('context_fingerprint')
            result['results'] = {k: summarize(k, per_side[k], order) for k in keys}
        status = 0
    except BenchError as e:
        result['error'] = str(e)
        status = 1
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, indent=1)
        f.write('\n')
    if status:
        print('bench_ab: FAILED: %s' % result['error'], file=sys.stderr)
    elif args.validate_only:
        print('bench_ab: the values are valid')
    else:
        for key, r in result['results'].items():
            print('bench_ab: %-18s B/A %.4f (paired %.4f..%.4f), spread A %s%% B %s%%' % (
                key, r['ratio_b_over_a']['of_medians'], r['ratio_b_over_a']['paired_min'], r['ratio_b_over_a']['paired_max'],
                r['a']['median_wall_ns']['spread_percent'], r['b']['median_wall_ns']['spread_percent']))
    return status


if __name__ == '__main__':
    sys.exit(main())
