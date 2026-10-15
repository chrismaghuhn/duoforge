#!/usr/bin/env python3
"""The reference sets: every battle file checked, every sum derived from them, each set against its lower bound.

Restructure step 2 (docs/superpowers/plans/2026-10-11-repo-restructure.md): global sums are derived, not maintained.
tests/reference/pins/<format>.json holds only the hand-maintained lower bound of each set's battle count; the sums
(battles, names, certified, fixture matches, tiebreak stops, live outcomes and stops, own-PP stops) are derived here
from the battle files, as tests/reference/data.cmake derives the native runners' counts at configure time. A battle's
own pins stay checked per battle (capture_battle_pins.py --check)."""
import collections
import hashlib
import json
from pathlib import Path
import sys


def summaries(root, format_name='reg-mc'):
    directory = root / 'tests/reference/battles' / format_name
    result, all_names, all_files = {}, set(), set()
    # Each spec's data set, parsed once for the three sets (was once per set: 3 x 1,142 files, 2026-10-14).
    spec_sets = {p.stem: json.loads(p.read_text(encoding='utf-8')).get('data') or 'closure'
                 for p in (root / 'tests/reference/specs').glob('*.json')}
    for dataset in ('closure', 'team_c', 'pool'):
        names, certified, fixture_matches, stops, own_pp = [], 0, 0, 0, 0
        outcomes, live_stops = collections.Counter(), collections.Counter()
        for file in sorted((directory / dataset).glob('*.json')):
            value = json.loads(file.read_text(encoding='ascii'))
            if (value['format'], value['set'], value['name']) != (format_name, dataset, file.stem):
                raise ValueError(f'{file}: wrong battle identity')
            if file.stem in all_names:
                raise ValueError(f'{file}: duplicate battle name')
            all_names.add(file.stem)
            all_files.add(file)
            names.append(file.stem)
            pins = value['pins']
            if type(pins['certified']) is not int or pins['certified'] not in (0, 1):
                raise ValueError(f'{file}: invalid certified pin')
            if type(pins['fixture_matches']) is not int or pins['fixture_matches'] < 0:
                raise ValueError(f'{file}: invalid fixture pin')
            certified += pins['certified']
            fixture_matches += pins['fixture_matches']
            conf, tb = value['conformance'], value['tiebreak']
            if not conf['definitions'].strip() or not conf['entry'].strip() or conf['step_count'] <= 0:
                raise ValueError(f'{file}: empty conformance payload')
            for rows, count in [(conf['tape'], conf['tape_count']), (conf['events'], conf['event_count']),
                                (tb['rows'], tb['stop_count'])]:
                if type(count) is not int or count < 0 or len(rows.splitlines()) != count:
                    raise ValueError(f'{file}: row count differs from payload')
            if tb['stop_count'] == 0:
                raise ValueError(f'{file}: empty tiebreak payload')
            stops += tb['stop_count']
            if dataset != 'team_c':
                live = pins['live']
                for field, total in [('outcomes', outcomes), ('stops', live_stops)]:
                    if any(type(n) is not int or n < 0 for n in live[field].values()):
                        raise ValueError(f'{file}: invalid live {field}')
                    total.update(live[field])
                players = live['own_pp_stops']
                if any(type(p) is not int or p not in (0, 1) for p in players) or len(set(players)) != len(players):
                    raise ValueError(f'{file}: invalid own-PP stops')
                own_pp += len(players)
        specs = {name for name, data in spec_sets.items() if data == dataset}
        if set(names) != specs:
            raise ValueError(f'{dataset}: battle files and specs differ')
        result[dataset] = dict(battles=len(names),
                              names_sha256=hashlib.sha256(''.join(n + '\n' for n in names).encode('ascii')).hexdigest(),
                              certified=certified, fixture_matches=fixture_matches, tiebreak_stops=stops,
                              outcomes=dict(outcomes), live_stops=dict(live_stops),
                              live_stop_total=sum(live_stops.values()), own_pp_stops=own_pp)
    if all_names != {p.stem for p in (root / 'tests/reference/traces').glob('*.json')}:
        raise ValueError('battle files and traces differ')
    if all_files != set(directory.rglob('*.json')):
        raise ValueError('unexpected battle directory/file')
    return result


SETS = ('closure', 'team_c', 'pool')


def check(root, format_name='reg-mc'):
    """The derived sums of each set; fails for an invalid battle file or a set below its lower bound."""
    pin_file = root / 'tests/reference/pins' / (format_name + '.json')
    bounds = json.loads(pin_file.read_text(encoding='ascii'))
    if bounds.get('format') != format_name:
        raise ValueError(f'{pin_file}: wrong format')
    if set(bounds) != {'maintenance', 'format', 'minimum_battles'} or set(bounds['minimum_battles']) != set(SETS):
        raise ValueError(f'{pin_file}: expected maintenance, format and minimum_battles of {", ".join(SETS)}')
    actual = summaries(root, format_name)
    for dataset in SETS:
        minimum = bounds['minimum_battles'][dataset]
        if type(minimum) is not int or minimum < 0:
            raise ValueError(f'{pin_file}: invalid minimum for {dataset}')
        if actual[dataset]['battles'] < minimum:
            raise ValueError(f'{pin_file}: {dataset} has {actual[dataset]["battles"]} battles, below the minimum {minimum}')
    return actual


def main():
    try:
        result = check(Path(sys.argv[1]).resolve())
    except (ValueError, KeyError, OSError) as error:
        print(f'reference format pins: {error}', file=sys.stderr)
        return 1
    print('reference format pins: ' + '/'.join(str(result[k]['battles']) for k in SETS)
          + ' battles, every battle file valid and every set at or above its minimum; derived sums:')
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
