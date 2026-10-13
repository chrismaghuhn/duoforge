#!/usr/bin/env python3
"""Independent inventory/aggregate pins and safeguards for deliberate pin updates."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/reference' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


format_pins = module('format_pins')
capture = module('capture_battle_pins')


class FrozenPins(unittest.TestCase):
    def test_committed_format_has_independent_names_counts_and_sums(self):
        format_pins.check(ROOT)

    def test_coordinated_deletion_and_rename_fail_even_with_regenerated_data(self):
        for mutate in ('delete', 'rename'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for dataset in ('closure', 'team_c', 'pool'):
                    sample = next(iter(sorted((ROOT / 'tests/reference/battles/reg-mc' / dataset).glob('*.json'))))
                    target = root / 'tests/reference/battles/reg-mc' / dataset / sample.name
                    target.parent.mkdir(parents=True)
                    shutil.copyfile(sample, target)
                    spec = root / 'tests/reference/specs' / sample.name
                    spec.parent.mkdir(exist_ok=True)
                    spec.write_text(json.dumps({} if dataset == 'closure' else {'data': dataset}))
                    trace = root / 'tests/reference/traces' / sample.name
                    trace.parent.mkdir(exist_ok=True)
                    trace.write_text('{}')
                expected = format_pins.summaries(root)
                pin = root / 'tests/reference/pins/reg-mc.json'
                pin.parent.mkdir(parents=True)
                pin.write_text(json.dumps({'format': 'reg-mc', 'sets': expected}))
                format_pins.check(root)
                paths = [target, spec, trace]  # coordinated change of all three pool files
                if mutate == 'delete':
                    for file in paths:
                        file.unlink()
                else:
                    value = json.loads(target.read_text())
                    value['name'] = 'renamed_battle'
                    target.write_text(json.dumps(value))
                    for file in paths:
                        file.rename(file.with_name('renamed_battle.json'))
                # Discovered files/specs/traces still agree (as after regeneration).
                actual = format_pins.summaries(root)
                self.assertNotEqual(actual, expected)
                with self.assertRaisesRegex(ValueError, 'independent reference-set pins differ'):
                    format_pins.check(root)

    def test_each_aggregate_change_fails_the_independent_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dataset in ('closure', 'team_c', 'pool'):
                sample = next(iter(sorted((ROOT / 'tests/reference/battles/reg-mc' / dataset).glob('*.json'))))
                file = root / 'tests/reference/battles/reg-mc' / dataset / sample.name
                file.parent.mkdir(parents=True)
                shutil.copyfile(sample, file)
                spec = root / 'tests/reference/specs' / sample.name
                spec.parent.mkdir(exist_ok=True)
                spec.write_text(json.dumps({} if dataset == 'closure' else {'data': dataset}))
                trace = root / 'tests/reference/traces' / sample.name
                trace.parent.mkdir(exist_ok=True)
                trace.write_text('{}')
            expected = format_pins.summaries(root)
            pin = root / 'tests/reference/pins/reg-mc.json'
            pin.parent.mkdir(parents=True)
            pin.write_text(json.dumps({'format': 'reg-mc', 'sets': expected}))
            good = json.loads(file.read_text())  # pool battle
            for field in ('certified', 'fixture_matches', 'tiebreak_stops', 'outcomes', 'live_stops', 'own_pp_stops'):
                with self.subTest(field):
                    value = copy.deepcopy(good)
                    if field == 'certified':
                        value['pins'][field] ^= 1
                    elif field == 'fixture_matches':
                        value['pins'][field] += 1
                    elif field == 'tiebreak_stops':
                        value['tiebreak']['stop_count'] += 1
                        value['tiebreak']['rows'] += value['tiebreak']['rows'].splitlines()[0] + '\n'
                    elif field == 'own_pp_stops':
                        value['pins']['live'][field].append(next(p for p in (0, 1) if p not in value['pins']['live'][field]))
                    else:
                        key = 'stops' if field == 'live_stops' else field
                        value['pins']['live'][key]['unexpected'] = 1
                    file.write_text(json.dumps(value))
                    # Payload/metadata are valid; only the independent aggregate rejects the change.
                    format_pins.summaries(root)
                    with self.assertRaisesRegex(ValueError, 'independent reference-set pins differ'):
                        format_pins.check(root)
            file.write_text(json.dumps(good))

    def test_existing_pins_are_never_written_without_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'battle.json'
            good = {'pins': {'certified': 1, 'live': {'outcomes': {'equal': 3}, 'stops': {}}}, 'payload': 'retained'}
            target.write_text(json.dumps(good))
            original = target.read_bytes()
            regressed = {'certified': 0, 'live': {'outcomes': {'refused': 3}, 'stops': {'new-stop': 1}}}
            capture.write_pins(target, {}, regressed)
            self.assertEqual(target.read_bytes(), original)
            with contextlib.redirect_stderr(io.StringIO()) as diagnostics:
                self.assertEqual(capture.write_pins(target, {}, regressed, check=True), 1)
            self.assertEqual(target.read_bytes(), original)
            self.assertIn('pins.certified', diagnostics.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as changes:
                capture.write_pins(target, {}, regressed, update_existing=True)
            self.assertEqual(json.loads(target.read_text())['payload'], 'retained')
            self.assertEqual(json.loads(target.read_text())['pins'], regressed)
            for field in ('pins.certified', 'pins.live.outcomes.equal', 'pins.live.outcomes.refused', 'pins.live.stops.new-stop'):
                self.assertIn(field, changes.getvalue())
                self.assertIn(str(target), changes.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as unchanged:
                capture.write_pins(target, {}, regressed, update_existing=True)
            self.assertEqual(unchanged.getvalue(), '')
            # Identical values must not silently rewrite a differently formatted file.
            target.write_text(json.dumps(json.loads(target.read_text())))
            original = target.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as unchanged:
                capture.write_pins(target, {}, regressed, update_existing=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(unchanged.getvalue(), '')

    def test_only_new_file_is_seeded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sub/new.json'
            with contextlib.redirect_stdout(io.StringIO()):
                capture.write_pins(path, {'name': 'new'}, {'certified': 1})
            self.assertEqual(json.loads(path.read_text()), {'name': 'new', 'pins': {'certified': 1}})

    def test_default_cli_observes_no_existing_battle(self):
        from unittest.mock import patch
        with patch.object(capture, 'certificates', side_effect=AssertionError('existing battle observed')), \
             patch.object(capture, 'live_observations', side_effect=AssertionError('existing live battle observed')), \
             patch('sys.argv', ['capture_battle_pins.py', str(ROOT)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(capture.main(), 0)


class ConfigureGuards(unittest.TestCase):
    def test_stale_declarations_and_truncated_payloads_fail_at_configure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / 'reference'
            reference.mkdir()
            sets = {}
            files = {}
            for dataset, header in [('closure', 'conformance.h'), ('team_c', 'conformance_team_c.h'), ('pool', 'conformance_pool.h')]:
                sample = next(p for p in sorted((ROOT / 'tests/reference/battles/reg-mc' / dataset).glob('*.json'))
                              if json.loads(p.read_text())['conformance']['tape_count'] > 0)
                value = json.loads(sample.read_text())
                file = reference / 'battles/reg-mc' / dataset / sample.name
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps(value))
                files[dataset] = file
                sets[dataset] = {'battles': 1, 'certified': value['pins']['certified'],
                                 'fixture_matches': value['pins']['fixture_matches'], 'tiebreak_stops': value['tiebreak']['stop_count']}
                (reference / header).write_text(f'#define DF_REFERENCE_BATTLE_COUNT 1u\n'
                    f'#define DF_REFERENCE_TAPE_COUNT {value["conformance"]["tape_count"]}u\n'
                    f'#define DF_REFERENCE_EVENT_COUNT {value["conformance"]["event_count"]}u\n')
            pins = reference / 'pins/reg-mc.json'
            pins.parent.mkdir()
            pins.write_text(json.dumps({'sets': sets}))
            tb_header = reference / 'tiebreak_ref.h'
            tb_header.write_text('#define DF_REFERENCE_TIEBREAK_COUNT 3u\n')
            shutil.copyfile(ROOT / 'tests/reference/data.cmake', reference / 'data.cmake')
            (root / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.23)\nproject(pin_guard C)\n'
                'function(duoforge_configure_target target)\nendfunction()\ninclude(reference/data.cmake)\n')
            command = [os.environ.get('DUOFORGE_CMAKE', 'cmake'), '-S', str(root), '-B', str(root / 'build')]
            def run():
                return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(run().returncode, 0)
            for file, macro in [(tb_header, 'DF_REFERENCE_TIEBREAK_COUNT'),
                                (reference / 'conformance.h', 'DF_REFERENCE_TAPE_COUNT'),
                                (reference / 'conformance.h', 'DF_REFERENCE_EVENT_COUNT')]:
                good = file.read_text()
                lines = [line if not line.startswith('#define '+macro+' ') else '#define '+macro+' 999999u'
                         for line in good.splitlines()]
                file.write_text('\n'.join(lines)+'\n')
                result = run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('stale '+macro, ' '.join(result.stdout.split()))
                file.write_text(good)
            file = files['closure']
            good = file.read_text()
            for section, field in [('conformance', 'tape_count'), ('conformance', 'event_count'), ('tiebreak', 'stop_count')]:
                value = json.loads(good)
                value[section][field] += 1
                file.write_text(json.dumps(value))
                result = run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('row count', ' '.join(result.stdout.split()))
            file.write_text(good)
            file.unlink()
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('independent pin', ' '.join(result.stdout.split()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
