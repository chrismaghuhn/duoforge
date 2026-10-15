#!/usr/bin/env python3
"""The reference sets (sums derived from the battle files, lower bounds per set) and safeguards for deliberate pin updates."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]


def configure_command(source, build, **extra):
    """cmake configuring `source` into `build`, with the generator, the C compiler and the make program of the build
    that runs this test where CTest gives them (DUOFORGE_CMAKE_GENERATOR, _C_COMPILER, _MAKE_PROGRAM). Without them
    CMake picked its own default: on Windows the Visual Studio generator and MSVC, found through MSBuild on every first
    configure, the slowest and most variable part of this test on the Windows jobs (#501, #505, #511). Only the
    compiler choice is shared; every configure still runs on its own with its own inputs. extra: -D values."""
    command = [os.environ.get('DUOFORGE_CMAKE', 'cmake'), '-S', str(source), '-B', str(build)]
    if os.environ.get('DUOFORGE_CMAKE_GENERATOR'):
        command += ['-G', os.environ['DUOFORGE_CMAKE_GENERATOR']]
    values = {'CMAKE_C_COMPILER': os.environ.get('DUOFORGE_C_COMPILER'),
              'CMAKE_MAKE_PROGRAM': os.environ.get('DUOFORGE_MAKE_PROGRAM'), **extra}
    return command + [f'-D{name}={value}' for name, value in values.items() if value]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/reference' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


format_pins = module('format_pins')
capture = module('capture_battle_pins')


def mini_root(root, minimum=1):
    """One battle per set (with its spec and trace) and lower bounds of `minimum`; returns the pool battle file."""
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
    pin = root / 'tests/reference/pins/reg-mc.json'
    pin.parent.mkdir(parents=True)
    pin.write_text(json.dumps({'maintenance': '', 'format': 'reg-mc',
                               'minimum_battles': {'closure': minimum, 'team_c': minimum, 'pool': minimum}}))
    return target, spec, trace


class DerivedSums(unittest.TestCase):
    def test_committed_sets_are_valid_and_at_their_minimum(self):
        result = format_pins.check(ROOT)
        self.assertEqual(result, format_pins.summaries(ROOT))  # derived the same way twice

    def test_a_deletion_below_the_minimum_fails(self):
        # Was: a coordinated deletion failed the hand-maintained aggregate. Now the lower bound catches it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = mini_root(root)
            format_pins.check(root)
            for file in paths:  # coordinated: battle, spec and trace together
                file.unlink()
            format_pins.summaries(root)  # the files still agree with each other
            with self.assertRaisesRegex(ValueError, 'below the minimum 1'):
                format_pins.check(root)

    def test_an_uncoordinated_rename_or_a_missing_spec_fails(self):
        # A coordinated rename is a deliberate change visible in the diff; an inconsistent one still fails.
        for mutate in ('name', 'spec', 'trace'):
            with self.subTest(mutate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target, spec, trace = mini_root(root)
                if mutate == 'name':
                    target.rename(target.with_name('renamed_battle.json'))
                    pattern = 'wrong battle identity'
                elif mutate == 'spec':
                    spec.unlink()
                    pattern = 'battle files and specs differ'
                else:
                    trace.unlink()
                    pattern = 'battle files and traces differ'
                with self.assertRaisesRegex(ValueError, pattern):
                    format_pins.check(root)

    def test_the_derived_sums_follow_every_pin_and_refuse_invalid_ones(self):
        # Was: each aggregate change failed the hand-maintained pin. Now each change moves exactly its derived sum.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = mini_root(root)[0]
            base = format_pins.check(root)['pool']
            good = json.loads(file.read_text())
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
                    changed = format_pins.check(root)['pool']
                    moved = {k for k in base if base[k] != changed[k]}
                    self.assertTrue(moved, field)
                    self.assertLessEqual(moved, {field, 'live_stop_total'}, field)
            for field, bad in (('certified', 2), ('fixture_matches', -1)):
                with self.subTest('invalid ' + field):
                    value = copy.deepcopy(good)
                    value['pins'][field] = bad
                    file.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ValueError, 'invalid'):
                        format_pins.check(root)
            file.write_text(json.dumps(good))


class CapturePins(unittest.TestCase):
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
    def test_derived_counts_and_truncated_payloads_fail_at_configure(self):
        # Was: a stale committed declaration failed the configure. Now the configure writes the counts itself (it is
        # checked that they are the battle files' sums) and fails, named, for a truncated payload, an invalid pin or a
        # set below its minimum.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / 'reference'
            reference.mkdir()
            files, expected = {}, {}
            for dataset in ('closure', 'team_c', 'pool'):
                sample = next(p for p in sorted((ROOT / 'tests/reference/battles/reg-mc' / dataset).glob('*.json'))
                              if json.loads(p.read_text())['conformance']['tape_count'] > 0)
                value = json.loads(sample.read_text())
                file = reference / 'battles/reg-mc' / dataset / sample.name
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps(value))
                files[dataset] = file
                expected[dataset] = value
            pins = reference / 'pins/reg-mc.json'
            pins.parent.mkdir()
            pins.write_text(json.dumps({'minimum_battles': {'closure': 1, 'team_c': 1, 'pool': 1}}))
            shutil.copyfile(ROOT / 'tests/reference/data.cmake', reference / 'data.cmake')
            (root / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.23)\nproject(pin_guard C)\n'
                'function(duoforge_configure_target target)\nendfunction()\ninclude(reference/data.cmake)\n')
            command = configure_command(root, root / 'build')
            def run(variant):
                # Each configure's wall time on stderr: the Windows/MSYS2 job's time is spent here and there (#505).
                start = time.perf_counter()
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                print(f'configure {variant}: {time.perf_counter() - start:.2f} s', file=sys.stderr, flush=True)
                return result
            self.assertEqual(run('baseline').returncode, 0)
            counts = root / 'build/reference_counts'
            for dataset, value in expected.items():
                conf = value['conformance']
                self.assertEqual((counts / f'reference_counts_{dataset}.h').read_text().splitlines()[1:], [
                    '#define DF_REFERENCE_BATTLE_COUNT 1u',
                    f'#define DF_REFERENCE_REAL_BATTLES {value["pins"]["certified"]}u',
                    f'#define DF_REFERENCE_FIXTURE_MATCHES {value["pins"]["fixture_matches"]}u',
                    f'#define DF_REFERENCE_TAPE_COUNT {max(1, conf["tape_count"])}u',
                    f'#define DF_REFERENCE_EVENT_COUNT {max(1, conf["event_count"])}u'])
            self.assertEqual((counts / 'reference_counts_tiebreak.h').read_text().splitlines()[1:], [
                '#define DF_REFERENCE_TIEBREAK_COUNT 3u'] + [
                f'#define DF_REFERENCE_{d.upper()}_STOPS {expected[d]["tiebreak"]["stop_count"]}u'
                for d in ('closure', 'team_c', 'pool')])
            pins_h = (root / 'build/reference_pins.h').read_text()
            self.assertIn(f'#define DF_REFERENCE_PIN_POOL_CERTIFIED {expected["pool"]["pins"]["certified"]}u', pins_h)
            self.assertIn(f'#define DF_REFERENCE_PIN_TEAM_C_TIEBREAK_STOPS {expected["team_c"]["tiebreak"]["stop_count"]}u',
                          pins_h)
            file = files['closure']
            good = file.read_text()
            for section, field in [('conformance', 'tape_count'), ('conformance', 'event_count'), ('tiebreak', 'stop_count')]:
                value = json.loads(good)
                value[section][field] += 1
                file.write_text(json.dumps(value))
                result = run(f'{section}.{field} + 1')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('row count', ' '.join(result.stdout.split()))
            value = json.loads(good)
            value['pins']['certified'] = 2
            file.write_text(json.dumps(value))
            result = run('invalid certified pin')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('invalid certified or fixture_matches pin', ' '.join(result.stdout.split()))
            file.write_text(good)
            file.unlink()
            result = run('deleted battle')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('below the minimum 1', ' '.join(result.stdout.split()))

    def test_a_configure_with_a_wrong_option_still_fails(self):
        # What the configures share (the generator and the compiler of this test's build) are inputs of each run,
        # never a cached result: a fresh configure given a wrong one fails. A wrong generator fails everywhere; a wrong
        # compiler fails where the generator takes the compiler from CMAKE_C_COMPILER (Ninja, Makefiles; the Visual
        # Studio generators pick MSVC themselves and ignore it).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.23)\nproject(pin_guard C)\n')
            command = configure_command(root, root / 'wrong-generator')
            command = [a for i, a in enumerate(command) if a != '-G' and (i == 0 or command[i - 1] != '-G')]
            result = subprocess.run(command + ['-G', 'No Such Generator'], text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('No Such Generator', result.stdout)
            generator = os.environ.get('DUOFORGE_CMAKE_GENERATOR', '')
            if generator and not generator.startswith('Visual Studio'):
                missing = str(root / 'no-such-compiler' / 'cc')
                command = configure_command(root, root / 'wrong-compiler', CMAKE_C_COMPILER=missing)
                self.assertIn(f'-DCMAKE_C_COMPILER={missing}', command)
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    # The slowest tests by name in the CI log (Python 3.12's durations), as format_pins hit its timeout on the MSYS2 job.
    unittest.main(verbosity=2, **({'durations': 0} if sys.version_info >= (3, 12) else {}))
