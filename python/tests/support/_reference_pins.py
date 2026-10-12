"""Frozen observations owned by each public reference battle, not global sums."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(dataset):
    directory = ROOT / 'tests/reference/battles/reg-mc' / dataset
    expected = {p.stem for p in (ROOT / 'tests/reference/specs').glob('*.json')
                if (json.loads(p.read_text()).get('data') or 'closure') == dataset}
    files = sorted(directory.glob('*.json'))
    if {p.stem for p in files} != expected or not files:
        raise AssertionError(f'{dataset}: per-battle pins do not cover the committed specs')
    result = {}
    for file in files:
        value = json.loads(file.read_text(encoding='ascii'))
        if (value['format'], value['set'], value['name']) != ('reg-mc', dataset, file.stem):
            raise AssertionError(f'{file}: wrong battle identity')
        pins = value['pins']['live']
        if set(pins) != {'outcomes', 'stops', 'own_pp_stops'}:
            raise AssertionError(f'{file}: invalid live-pin fields')
        for key in ('outcomes', 'stops'):
            if not isinstance(pins[key], dict) or any(not isinstance(name, str) or type(count) is not int or count < 0
                                                     for name, count in pins[key].items()):
                raise AssertionError(f'{file}: invalid {key} pins')
        players = pins['own_pp_stops']
        if (not isinstance(players, list) or
                any(type(p) is not int or p not in (0, 1) for p in players) or
                players != sorted(set(players))):
            raise AssertionError(f'{file}: invalid own-PP stops')
        result[file.stem] = pins
    return result


def totals(pins, key):
    result = collections.Counter()
    for row in pins.values():
        result.update(row[key])
    return dict(result)
