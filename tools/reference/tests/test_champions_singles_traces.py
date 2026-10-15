#!/usr/bin/env python3
"""The traces of the conformance set champions-singles (decision 0083) are what the pinned Showdown records from their
specs: `ps_trace.js <checkout> <spec> --check <trace>` for every battle of tests/reference/singles/champions-singles.

usage: python3 tools/reference/tests/test_champions_singles_traces.py <node> <checkout>

CTest runs it as duoforge.reference.champions_singles_traces (label reference: Node and the pinned checkout).
"""
import io
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SET = os.path.join(ROOT, 'tests', 'reference', 'singles', 'champions-singles')


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    node, checkout = argv[1], argv[2]
    with io.open(os.path.join(SET, 'set.json'), encoding='utf-8') as f:
        names = json.load(f)['battles']
    bad = []
    for name in names:
        p = subprocess.run([node, os.path.join(HERE, 'ps_trace.js'), checkout, os.path.join(SET, name + '.spec.json'),
                            '--check', os.path.join(SET, name + '.trace.json')], capture_output=True, text=True)
        if p.returncode != 0:
            bad.append(name)
            sys.stderr.write('%s: %s%s\n' % (name, p.stdout[-1500:], p.stderr[-1500:]))
    print('champions-singles traces: %d specs, %d re-recorded equal' % (len(names), len(names) - len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
