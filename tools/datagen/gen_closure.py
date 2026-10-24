#!/usr/bin/env python3
"""Generates src/data/formats/reg-mc/closure_tables.{h,c}: the immutable data of the two
reference teams (decision 0004) read from the pinned Pokemon Showdown
checkout (decision 0006 section 2).

usage: python3 tools/datagen/gen_closure.py <pinned checkout> [--team-c | --pool [--format <id>]] [--check]

  --team-c  write src/data/formats/reg-mc/extended_tables.{h,c} instead: the closure tables
            followed by Team C (docs/decisions/0009). The closure ids stay an
            exact prefix; the generator checks that before it writes.
  --pool    write src/data/formats/reg-mc/pool_tables.{h,c} instead: the extended tables as
            the prefix, then the rows of the content expansion, with the
            family columns of every item and ability and the moves and
            abilities that each forme may have (docs/decisions/0015). Both
            prefixes are checked row by row before it writes.
  --format  with --pool: the format whose tables are built (default reg-mc, the
            engine's format): its definition data/formats/<id>.json names the
            pool, the rule set, the writer's names, the learnset bytes, the id
            bounds and the excluded formes (its tables section; restructure
            step 5). The closure and Team C tables are Reg M-C's.
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

import gen_format
from tablegen import abilities, families, formats, items, moves, output, rules, source, species, tables

# Every name of the area modules stays readable as gen_closure.<name> (the tests, classify_unsupported.py and
# tools/reference/team_registry.py read the parsers, the pin and the fact tables from here); main() below uses
# load_table_set, build, build_pool, check_prefix, check_pool_prefix, render, render_ext, render_pool and
# feature_summary.
for _area in (source, formats, species, moves, families, items, abilities, rules, tables, output):
    globals().update({k: v for k, v in vars(_area).items() if not k.startswith('__')})
del _area


def main():
    argv = sys.argv[1:]
    format_id = gen_format.ENGINE_FORMAT
    if '--format' in argv:
        k = argv.index('--format')
        if k + 1 >= len(argv):
            sys.exit(__doc__)
        format_id = argv[k + 1]
        del argv[k:k + 2]
    team_c = '--team-c' in argv
    pool = '--pool' in argv
    args = [a for a in argv if a not in ('--check', '--team-c', '--pool')]
    check = '--check' in argv
    if len(args) != 1 or (team_c and pool) or (format_id != gen_format.ENGINE_FORMAT and not pool):
        sys.exit(__doc__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ts = load_table_set(repo, format_id)
    d = build(args[0], ts)
    if pool:
        dc = d
        dx = build(args[0], ts, ext=True)
        check_prefix(dx, dc)
        d = build_pool(args[0], repo, dx, ts)
        check_pool_prefix(d, dx, dc)
        h, c, digest, size = render_pool(d, dx, ts)
        stem = ts.stem
        summary = feature_summary(d)
    elif team_c:
        dc = d
        d = build(args[0], ts, ext=True)
        check_prefix(d, dc)
        h, c, digest, size = render_ext(d, dc)
        stem = 'extended_tables'
    else:
        h, c, digest, size = render(d)
        stem = 'closure_tables'
    # src/data/formats/<id>/ holds the tables of a format (restructure step 5); the closure and Team C tables are reg-mc's.
    outs = ((os.path.join(repo, 'src', 'data', 'formats', ts.format_id, stem + '.h'), h),
            (os.path.join(repo, 'src', 'data', 'formats', ts.format_id, stem + '.c'), c))
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
