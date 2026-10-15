#!/usr/bin/env python3
"""The conformance set champions-singles (decision 0083): every committed singles battle, recorded against the pinned
Showdown in [Gen 9 Champions] OU, through the converter and the differential runner of this build under
DUOFORGE_DATA_KIND_POOL_SINGLES_DEV. Every battle must PASS: the states, requests, events, views and draws of every step
equal the reference's (tests/support/conformance_compare.c, the comparator of the doubles sets).

usage: python3 tools/reference/tests/test_champions_singles.py <duoforge_diff_runner>

CTest runs it as duoforge.reference.champions_singles (Python only, no Node). The battles are
tests/reference/singles/champions-singles/<name>.spec.json with the trace <name>.trace.json beside it, and set.json
lists their names: a missing or an extra file fails, as a battle that does not pass does. The re-recording of the specs
by the pinned Showdown is duoforge.reference.champions_singles_traces (Node and the checkout).
"""
import io
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SET = os.path.join(ROOT, 'tests', 'reference', 'singles', 'champions-singles')
sys.path.insert(0, HERE)

import conformance_records  # noqa: E402
import trace_to_c  # noqa: E402


def battles():
    """The (name, spec, trace) of the set, in the order of set.json; a missing or an unlisted file is an error."""
    with io.open(os.path.join(SET, 'set.json'), encoding='utf-8') as f:
        names = json.load(f)['battles']
    files = sorted(os.listdir(SET))
    expected = sorted(['set.json'] + ['%s.spec.json' % n for n in names] + ['%s.trace.json' % n for n in names])
    if files != expected:
        raise SystemExit('champions-singles: the files differ from set.json: extra %s, missing %s' %
                         (sorted(set(files) - set(expected)), sorted(set(expected) - set(files))))
    out = []
    for name in names:
        with io.open(os.path.join(SET, name + '.spec.json'), encoding='utf-8') as f:
            spec = json.load(f)
        with io.open(os.path.join(SET, name + '.trace.json'), encoding='utf-8') as f:
            trace = json.load(f)
        if spec.get('name') != name or not trace_to_c.spec_singles(spec):
            raise SystemExit('champions-singles: %s is not a singles battle of that name' % name)
        out.append((name, spec, trace))
    return out


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    tables = trace_to_c.load_tables(ROOT, True)
    kind = conformance_records.data_kinds(ROOT)['POOL_SINGLES_DEV']
    records = io.StringIO()
    listed = battles()
    for name, spec, trace in listed:
        conformance_records.write_battle(trace_to_c.convert_battle(name, spec, trace, tables), True, records, kind=kind)
    # bytes, not text: a text pipe on Windows writes CR LF, and the runner refuses the CR
    p = subprocess.run([argv[1]], input=records.getvalue().encode('ascii'), capture_output=True)
    stdout = p.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
    stderr = p.stderr.decode('utf-8', 'replace').replace('\r\n', '\n')
    verdicts = {}
    for line in stdout.splitlines():
        if line.startswith('R '):
            words = line.split(' ')
            verdicts[words[1]] = words[2]
    failed = [n for n, _, _ in listed if verdicts.get(n) != 'PASS']
    steps = sum(len(t['steps']) for _, _, t in listed)
    print('champions-singles: %d battles, %d steps, %d pass' % (len(listed), steps, len(listed) - len(failed)))
    if failed or p.returncode not in (0, 1):
        sys.stdout.write(stdout[-6000:])
        sys.stderr.write(stderr[-2000:])
        print('champions-singles: not passing: %s' % ', '.join(failed))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
