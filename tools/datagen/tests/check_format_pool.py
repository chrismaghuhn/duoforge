#!/usr/bin/env python3
"""Makes the pool source of a format definition again with the pinned TeamValidator and compares it with the
committed file (step O1 of docs/superpowers/specs/2026-10-15-gen9-ou-design.md).

It runs docs/research/expansion/tools/build_legal_pool.js for the definition's Showdown format id into a temporary
directory and compares every block except the run facts of meta (checkout path, Node version, elapsed time).

usage: python3 tools/datagen/tests/check_format_pool.py <node> <pinned checkout> <format id>
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gen_format  # noqa: E402

RUN_FACTS = ('showdown_checkout', 'node', 'cross_product_ms')


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    node, checkout, format_id = sys.argv[1:]
    fmt = gen_format.load_format(format_id=format_id)
    tool = os.path.join(gen_format.REPO, 'docs', 'research', 'expansion', 'tools', 'build_legal_pool.js')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'pool.json')
        subprocess.run([node, tool, '--format', fmt['showdown_format_id'], '--checkout', checkout,
                        '--duoforge', gen_format.REPO, '--out', out], check=True, stdout=subprocess.DEVNULL)
        with open(out, encoding='utf-8') as fh:
            made = json.load(fh)
    with open(os.path.join(gen_format.REPO, fmt['pool']['source']), encoding='utf-8') as fh:
        committed = json.load(fh)
    for blob in (made, committed):
        for key in RUN_FACTS:
            blob['meta'].pop(key)
    differ = sorted(k for k in set(made) | set(committed) if made.get(k) != committed.get(k))
    if differ:
        sys.exit('check_format_pool: %s differs from the pinned validator in %s' % (fmt['pool']['source'], differ))
    print('%s: the pinned validator makes the committed pool (%d formes, %d moves, %d items, %d abilities)' % (
        fmt['pool']['source'], len(made['species']), len(made['moves']), len(made['items']), len(made['abilities'])))


if __name__ == '__main__':
    main()
