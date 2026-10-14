#!/usr/bin/env python3
"""Seed/check frozen reference pins per battle (no weights or private data).

Needs the same library, runner, Node and pinned Showdown as python.live.
Usage: python tools/reference/capture_battle_pins.py <repo> [--check | --update-existing]
Only test observations and public API calls are used. The unchanged functional
record comparisons must pass before a pin is written. Ordinary tests always
compare to the frozen pins. Existing expectations are changed only with
--update-existing, which reports every changed file and field.
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


def live_observations(names):
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
            if b.name in names:
                result[b.name] = {'outcomes': dict(by_battle[b.name]), 'stops': {}, 'own_pp_stops': []}
    for name, stops in live.RecordAssemblerPoolTest.stops_by_battle.items():
        if name in result:
            result[name]['stops'] = dict(stops)
    for name, player in live.RecordAssemblerPoolTest.raised:
        if name in result:
            result[name]['own_pp_stops'].append(player)
    for row in result.values():
        row['own_pp_stops'].sort()
    return result


def differences(old, new, field='pins'):
    """Every changed leaf, including removed keys and whole list changes."""
    if isinstance(old, dict) or isinstance(new, dict):
        before = old if isinstance(old, dict) else {}
        after = new if isinstance(new, dict) else {}
        for key in sorted(set(before) | set(after)):
            child = f'{field}.{key}' if field else key
            yield from differences(before.get(key), after.get(key), child)
    elif old != new or type(old) is not type(new):
        yield field, old, new


def write_pins(target, identity, pins, check=False, update_existing=False):
    """Protect frozen expectations even when called separately from the CLI."""
    have = json.loads(target.read_text(encoding='ascii')) if target.exists() else {}
    if check:
        changes = list(differences(have.get('pins'), pins))
        for field, old, new in changes:
            print(f'reference pins: {target}: {field}: frozen={old!r}, observed={new!r}', file=sys.stderr)
        return int(bool(changes))
    if target.exists() and not update_existing:
        return 0
    if target.exists():
        proposed = dict(have, **identity, pins=pins)
        changes = list(differences(have, proposed, field=''))
        if not changes:
            return 0
        for field, old, new in changes:
            print(f'reference pins UPDATE: {target}: {field}: {old!r} -> {new!r}')
    else:
        print(f'reference pins NEW: {target}')
    have.update(identity, pins=pins)
    content = json.dumps(have, indent=2, sort_keys=True) + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_text(encoding='ascii') != content:
        target.write_text(content, encoding='ascii')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--update-existing', action='store_true')
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'python'))
    from tools.reference import trace_to_c
    names = sorted(p.stem for p in (root / 'tests/reference/traces').glob('*.json'))
    targets = {}
    for name in names:
        # The kind is the spec's: the trace (71 MB in all, 2026-10-14) is read only where a battle is observed.
        kind = trace_to_c.spec_data(name, trace_to_c.load_json(str(root), 'specs', name))
        targets[name] = (kind, root / 'tests/reference/battles/reg-mc' / kind / (name + '.json'))
    if not args.check and not args.update_existing:
        names = [name for name in names if not targets[name][1].exists()]
    if not names:
        print('reference pins: no new battles; existing pins preserved')
        return 0
    real, matches = certificates(root, names)
    live_names = {name for name in names if targets[name][0] != 'team_c'}
    live = live_observations(live_names) if live_names else {}
    rc = 0
    for name in names:
        kind, target = targets[name]
        pins = {'certified': real[name], 'fixture_matches': matches[name]}
        if name in live:
            pins['live'] = live[name]
        identity = {'generated_by': 'tools/reference/trace_to_c.py, tiebreak_ref.js, capture_battle_pins.py',
                    'format': 'reg-mc', 'set': kind, 'name': name}
        rc |= write_pins(target, identity, pins, args.check, args.update_existing)
    print(f'reference pins: {len(names)} battles, {len(live)} live battles; {"checked" if args.check else "written"}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
