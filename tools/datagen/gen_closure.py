#!/usr/bin/env python3
"""Generates src/data/formats/reg-mc/closure_tables.{h,c}: the immutable data of the two
reference teams (decision 0004) read from the pinned Pokemon Showdown
checkout (decision 0006 section 2).

usage: python3 tools/datagen/gen_closure.py <pinned checkout> [--team-c | --pool] [--check]

  --team-c  write src/data/formats/reg-mc/extended_tables.{h,c} instead: the closure tables
            followed by Team C (docs/decisions/0009). The closure ids stay an
            exact prefix; the generator checks that before it writes.
  --pool    write src/data/formats/reg-mc/pool_tables.{h,c} instead: the extended tables as
            the prefix, then the rows of the content expansion, with the
            family columns of every item and ability and the moves and
            abilities that each forme may have (docs/decisions/0015). Both
            prefixes are checked row by row before it writes.
  --check   do not write; exit 1 if the committed files differ.

Offline tooling. It extracts static data only; every effect still needs a
typed handler in C (decision 0006). It fails, instead of guessing, when an
input hash differs from the pin, when a move has a field it does not know,
or when a callback is not mapped to a named handler id. The family columns
come from one strict pattern per family; a handler that deviates from the
pattern of its family fails the generator. CTest never needs Python: the
generated files are committed.
"""
import hashlib
import io
import json
import os
import sys

from tablegen import abilities, families, items, moves, output, rules, source, species, tables

# Every name of the area modules stays readable as gen_closure.<name> (the tests, classify_unsupported.py and
# tools/reference/team_registry.py read the parsers, the pin and the fact tables from here); main() below uses
# build, build_pool, check_prefix, check_pool_prefix, render, render_ext, render_pool and feature_summary.
for _area in (source, species, moves, families, items, abilities, rules, tables, output):
    globals().update({k: v for k, v in vars(_area).items() if not k.startswith('__')})
del _area


def main():
    team_c = '--team-c' in sys.argv[1:]
    pool = '--pool' in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a not in ('--check', '--team-c', '--pool')]
    check = '--check' in sys.argv[1:]
    if len(args) != 1 or (team_c and pool):
        sys.exit(__doc__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = build(args[0])
    if pool:
        dc = d
        dx = build(args[0], ext=True)
        check_prefix(dx, dc)
        d = build_pool(args[0], repo, dx)
        check_pool_prefix(d, dx, dc)
        h, c, digest, size = render_pool(d, dx)
        stem = 'pool_tables'
        summary = feature_summary(d)
    elif team_c:
        dc = d
        d = build(args[0], ext=True)
        check_prefix(d, dc)
        h, c, digest, size = render_ext(d, dc)
        stem = 'extended_tables'
    else:
        h, c, digest, size = render(d)
        stem = 'closure_tables'
    outs = ((os.path.join(repo, 'src', 'data', 'formats', 'reg-mc', stem + '.h'), h),
            (os.path.join(repo, 'src', 'data', 'formats', 'reg-mc', stem + '.c'), c))
    for path, text in outs:
        if check:
            have = io.open(path, 'rb').read().replace(b'\r\n', b'\n')
            if have != text.encode('ascii'):
                fail('%s differs from the generator output' % path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, 'w', encoding='ascii', newline='\n') as fh:
                fh.write(text)
    if pool:
        print(json.dumps(dict(summary, aliases=len(d['aliases']), flags_that_matter=d['flags_that_matter']), indent=1,
                         sort_keys=True))
    print('%s: %d formes, %d moves, %d items, %d abilities; canonical %d bytes, sha256 %s%s' % (
        stem, len(d['formes']), len(d['moves']), len(d['items']), len(d['abilities']), size, digest,
        ' (check ok)' if check else ''))
    for path, text in outs:
        print('  %s sha256 %s' % (os.path.basename(path), hashlib.sha256(text.encode('ascii')).hexdigest()))


if __name__ == '__main__':
    main()
