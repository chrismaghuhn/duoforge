#!/usr/bin/env python3
"""Regenerate/check frozen reference pins per battle (no weights or private data).

Needs the same library, runner, Node and pinned Showdown as python.live.
Usage: python tools/reference/capture_battle_pins.py <repo> [--check]
Only test observations and public API calls are used. The unchanged functional
record comparisons must pass before a pin is written. Ordinary tests always
compare to the frozen pins; this explicit generator is how a deliberate pin
update is reproduced.
"""
import argparse
import collections
import ctypes
import json
import re
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True


def certificates(root, names):
    import numpy as np
    import duoforge
    from duoforge import _layout
    from duoforge._lib import load_library, ptr
    from tools.reference import trace_to_c
    from tools.reference.conformance_records import data_kinds
    kind_values = data_kinds(str(root))
    lib = load_library()
    create = lib.duoforge_battle_create
    create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_int
    destroy = lib.duoforge_battle_destroy
    destroy.argtypes = [ctypes.c_void_p]
    destroy.restype = None
    contexts = {}
    tables = {kind: trace_to_c.load_tables(str(root), kind != 'closure') for kind in ('closure', 'team_c', 'pool')}
    fixture_names = re.findall(r'\{DFI_FORME_(\w+),', (root / 'tests/support/team_c.c').read_text())
    fixture_ids = {tables['team_c']['FORME'][name] for name in fixture_names}
    if not fixture_ids:
        raise ValueError('Team C fixture has no species')
    matches = {}
    kinds = {'closure': 'CLOSURE', 'team_c': 'TEAM_C', 'pool': 'POOL'}
    try:
        for key in kinds.values():
            for suffix in ('', '_DEV'):
                contexts[key + suffix] = duoforge.Context(data_kind=kind_values[key + suffix])
        result = {}
        for name in names:
            spec, trace = trace_to_c.load_battle(str(root), name)
            kind = trace_to_c.spec_data(name, spec)
            data = trace_to_c.convert_battle(name, spec, trace, tables[kind])
            setup = np.zeros((), dtype=_layout.SETUP)
            setup['rng_initstate'] = 1
            setup['rng_initseq'] = 2
            for side, members in enumerate(data['members']):
                setup['sides'][side]['member_count'] = data['member_count']
                for index, row in enumerate(members[:data['member_count']]):
                    species, gender, nature, sp, ability, item, move_count, moves = row
                    dst = setup['sides'][side]['members'][index]
                    for field, value in [('species_id', species), ('gender', gender), ('nature', nature),
                                         ('stat_points', sp), ('ability', ability), ('item', item), ('move_count', move_count)]:
                        dst[field] = value
                    for slot, move in enumerate(moves[:move_count]):
                        dst['moves'][slot]['move_id'] = move
            battle = ctypes.c_void_p()
            status = create(contexts[kinds[kind]].handle, ptr(setup), ctypes.byref(battle))
            real = status == 0
            if not real:
                status = create(contexts[kinds[kind] + '_DEV'].handle, ptr(setup), ctypes.byref(battle))
            if status != 0 or not battle.value:
                raise ValueError(f'{name}: both conformance contexts refuse its setup ({status})')
            destroy(battle)
            result[name] = int(real)
            matches[name] = (sum(row[0] in fixture_ids for side in data['members']
                                 for row in side[:data['member_count']])
                             if name.startswith('c12_real_') else 0)
        return result, matches
    finally:
        for ctx in contexts.values():
            ctx.close()


def live_observations():
    from python.tests.live import test_live as live
    checker = unittest.TestCase()
    live.RecordAssemblerTest.setUpClass()
    live.RecordAssemblerPoolTest.setUpClass()
    result = {}
    for cls, collect in [(live.RecordAssemblerTest, live._closure_assembler_observations),
                         (live.RecordAssemblerPoolTest, live._pool_assembler_observations)]:
        values = collect(cls.points, checker) if cls is live.RecordAssemblerPoolTest else collect(cls.points)
        outcome, fields, where, by_battle = values
        checker.assertFalse(fields, {key: (count, where[key]) for key, count in fields.items()})
        allowed = {'equal', 'refused'}
        if cls is live.RecordAssemblerPoolTest:
            allowed |= {live.INFATUATED_REFUSAL} | {f'tracker refuses: {reason}' for reason in cls.TRACKER_REFUSALS}
        checker.assertEqual(set(outcome) - allowed, set(), where)
        ref = cls.pool if cls is live.RecordAssemblerPoolTest else cls.ref
        for b in ref.battles:
            result[b.name] = {'outcomes': dict(by_battle[b.name]), 'stops': {}, 'own_pp_stops': []}
    for name, stops in live.RecordAssemblerPoolTest.stops_by_battle.items():
        result[name]['stops'] = dict(stops)
    for name, player in live.RecordAssemblerPoolTest.raised:
        result[name]['own_pp_stops'].append(player)
    for row in result.values():
        row['own_pp_stops'].sort()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'python'))
    from tools.reference import trace_to_c
    names = sorted(p.stem for p in (root / 'tests/reference/traces').glob('*.json'))
    real, matches = certificates(root, names)
    live = live_observations()
    rc = 0
    for name in names:
        spec, _ = trace_to_c.load_battle(str(root), name)
        kind = trace_to_c.spec_data(name, spec)
        target = root / 'tests/reference/battles/reg-mc' / kind / (name + '.json')
        have = json.loads(target.read_text()) if target.exists() else {}
        pins = {'certified': real[name], 'fixture_matches': matches[name]}
        if name in live:
            pins['live'] = live[name]
        if args.check:
            if have.get('pins') != pins:
                print(f'reference pins: {target} differs from the observations', file=sys.stderr)
                rc = 1
        else:
            have.update({'generated_by': 'tools/reference/trace_to_c.py, tiebreak_ref.js, capture_battle_pins.py',
                         'format': 'reg-mc', 'set': kind, 'name': name, 'pins': pins})
            target.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(have, indent=2, sort_keys=True) + '\n'
            if not target.exists() or target.read_text(encoding='ascii') != content:
                target.write_text(content, encoding='ascii')
    print(f'reference pins: {len(names)} battles, {len(live)} live battles; {"checked" if args.check else "written"}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
