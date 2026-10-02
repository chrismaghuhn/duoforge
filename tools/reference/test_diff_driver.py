#!/usr/bin/env python3
"""The replay driver (tools/reference/diff_driver.py) and the records writer
(tools/reference/conformance_records.py) without Node and without a Showdown
checkout.

usage: python3 tools/reference/test_diff_driver.py

CTest runs it as duoforge.reference.diff_driver, with DUOFORGE_DIFF_RUNNER set
to the runner it has built. The bucket logic runs with a fake worker and a fake
runner, and with the real converter on committed battles: the refusals come
from edited copies of them, nothing of the converter is mocked. The clients of
the child processes run against stand-in processes. With the real runner, every
committed battle goes through the driver, a stand-in for the reference
answering its committed trace.
"""
import contextlib
import copy
import inspect
import io
import itertools
import json
import linecache
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_driver as driver  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RUNNER = os.environ.get('DUOFORGE_DIFF_RUNNER')
CLOSURE, TEAM_C = 's2_turn_core_1', 'c05_helmet_order'  # a small battle of each kind
VERSION = {'node': 'v0.0.0', 'pin': '0' * 40, 'harness': 14}
SCHEMA = ['name', 'bucket', 'rule', 'detail', 'step', 'steps', 'context', 'messages']

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def committed(name):
    """A fresh copy of the spec and the trace text of a committed battle."""
    return driver.load_committed(ROOT, name)


def edited(name, edit):
    """The spec of battle `name` and a trace text after edit(spec, trace): the text is its own committed trace."""
    spec, text = committed(name)
    trace = json.loads(text)
    edit(spec, trace)
    return spec, json.dumps(trace, indent=1) + '\n'


class FakeWorker:
    """record() answers what answer(spec, spec_file) says, or raises."""

    def __init__(self, answer=None, version=VERSION):
        self.answer = answer
        self.reported = version
        self.requests = []
        self.closed = self.killed = 0
        self.failed = False  # set by a test that plays a worker that died: it is replaced

    def version(self):
        return dict(self.reported)

    def record(self, spec, spec_file):
        self.requests.append(spec_file)
        return self.answer(spec, spec_file)

    def close(self):
        self.closed += 1
        return []

    def kill(self):
        self.killed += 1


class FakeRunner:
    """run() answers `result`; a runner that must not be asked has none."""

    def __init__(self, result=None, leaves_with=(), raises=None):
        self.result = result
        self.leaves_with = list(leaves_with)
        self.raises = raises
        self.requests = []
        self.closed = self.killed = 0
        self.failed = False

    def run(self, name, records):
        self.requests.append((name, records))
        if self.raises is not None:
            raise self.raises
        if self.result is None:
            raise AssertionError('the runner must not be asked for %s' % name)
        return self.result

    def close(self):
        self.closed += 1
        return self.leaves_with

    def kill(self):
        self.killed += 1


def runner_result(verdict, context='CLOSURE_DEV', step=None, steps=4, detail='-', messages=()):
    return driver.RunnerResult(verdict, context, step, steps, detail, list(messages))


class Buckets(unittest.TestCase):
    """One battle through the three steps, by the bucket it ends in."""

    def process(self, name, spec, text, answer=None, result=None, runner_raises=None):
        worker = FakeWorker(answer or (lambda s, f: text))
        runner = FakeRunner(result, raises=runner_raises)
        record = driver.process_battle(name, spec, text, worker, runner, tables)
        return record, worker, runner

    def test_a_worker_error_is_a_ref_error(self):
        spec, text = committed(CLOSURE)

        def refuse(s, f):
            raise driver.WorkerError('choice rejected: "move 9"', 'Error: choice rejected\n    at run (ps_trace.js:1)')

        record, worker, runner = self.process(CLOSURE, spec, text, refuse)
        self.assertEqual(record, {'name': CLOSURE, 'bucket': 'REF_ERROR', 'rule': None, 'detail': 'choice rejected: "move 9"',
                                  'step': None, 'steps': None, 'context': None,
                                  'messages': ['Error: choice rejected', '    at run (ps_trace.js:1)']})
        self.assertEqual(worker.requests, [CLOSURE + '.json'])  # the file name of the spec
        self.assertEqual(runner.requests, [])

    def test_a_trace_that_differs_from_the_committed_one_is_a_ref_error(self):
        spec, text = committed(CLOSURE)
        changed = text.replace('"harness": 14', '"harness": 15', 1)
        self.assertNotEqual(changed, text)
        record, _, runner = self.process(CLOSURE, spec, text, lambda s, f: changed)
        self.assertEqual((record['bucket'], record['rule'], record['detail']),
                         ('REF_ERROR', None, 'trace differs from the committed trace'))
        self.assertEqual(len(record['messages']), 1)
        self.assertRegex(record['messages'][0], r'^line 2: .*"harness": 15.* against .*"harness": 14')
        self.assertEqual(runner.requests, [])

    def test_a_refusal_of_the_converter_is_an_oracle_gap_with_its_rule_and_detail(self):
        spec, text = edited(CLOSURE, lambda spec, trace: trace['steps'][1]['log'].append('|foo|bar'))
        record, _, runner = self.process(CLOSURE, spec, text)
        self.assertEqual(record, {'name': CLOSURE, 'bucket': 'ORACLE_GAP', 'rule': 'protocol-line', 'detail': 'foo',
                                  'step': None, 'steps': None, 'context': None,
                                  'messages': ["trace_to_c: unknown protocol line '|foo|bar'"]})
        self.assertEqual(runner.requests, [])

    def test_a_refusal_of_the_spec_before_the_tables_are_chosen_is_an_oracle_gap_too(self):
        spec, text = edited(TEAM_C, lambda spec, trace: spec.update(data='team_d'))
        record, _, runner = self.process(TEAM_C, spec, text)
        self.assertEqual((record['bucket'], record['rule'], record['detail']), ('ORACLE_GAP', 'spec-data', None))
        self.assertEqual(record['messages'], ["trace_to_c: %s: unknown data 'team_d'" % TEAM_C])
        self.assertEqual(runner.requests, [])

    def test_untyped_errors_of_the_converter_are_oracle_gaps(self):
        """KeyError, IndexError, ValueError and TypeError out of convert_battle: the rule is
        untyped:<type>, the detail the message and the function and line that raised it."""
        def unknown_species(spec, trace):
            self.assertIn('Golisopod', spec['teams'][0])
            spec['teams'][0] = spec['teams'][0].replace('Golisopod', 'Zzzmon', 1)

        cases = (
            ('KeyError', unknown_species, "'ZZZMON'"),
            ('IndexError', lambda spec, trace: trace['steps'][0]['log'].append('|-damage|p1a: Golisopod'),
             'list index out of range'),
            ('ValueError', lambda spec, trace: trace['steps'][0]['log'].append('|turn|abc'),
             "invalid literal for int() with base 10: 'abc'"),
            ('TypeError', lambda spec, trace: trace['steps'][0].update(log=None), "'NoneType' object is not iterable"),
        )
        for kind, edit, message in cases:
            with self.subTest(kind):
                spec, text = edited(CLOSURE, edit)
                record, _, runner = self.process(CLOSURE, spec, text)
                self.assertEqual((record['bucket'], record['rule']), ('ORACLE_GAP', 'untyped:' + kind))
                m = re.fullmatch(r'(.*) \((\w+):(\d+)\)', record['detail'])
                self.assertIsNotNone(m, record['detail'])
                self.assertEqual(m.group(1), message)
                # The function is one of the converter's, and the line is inside it.
                lines, first = inspect.getsourcelines(getattr(trace_to_c, m.group(2)))
                self.assertTrue(first <= int(m.group(3)) < first + len(lines), record['detail'])
                self.assertEqual(record['messages'], ['%s: %s' % (kind, message)])
                self.assertEqual((record['step'], record['context']), (None, None))
                self.assertEqual(runner.requests, [])

    def test_nothing_else_is_caught(self):
        """An error that is neither a refusal nor one of the four untyped ones is a bug: it
        propagates, and the runner is not asked."""
        spec, text = edited(CLOSURE, lambda spec, trace: trace['steps'][1]['input'].update(p1=5))
        worker, runner = FakeWorker(lambda s, f: text), FakeRunner()
        with self.assertRaises(AttributeError):
            driver.process_battle(CLOSURE, spec, text, worker, runner, tables)
        self.assertEqual(runner.requests, [])

    def test_the_verdicts_of_the_runner_are_the_buckets(self):
        for name, team_c in ((CLOSURE, 0), (TEAM_C, 1)):
            spec, text = committed(name)
            for result, want in (
                    (runner_result('PASS', 'CLOSURE'), {'bucket': 'PASS', 'detail': None, 'step': None,
                                                        'context': 'CLOSURE', 'messages': []}),
                    (runner_result('DIVERGENCE', 'TEAM_C', 2, 7, 'differences: state 1, observation 0, events 0',
                                   ['  m step 2: side 0 member 0 hp 5, reference 6']),
                     {'bucket': 'DIVERGENCE', 'detail': 'differences: state 1, observation 0, events 0', 'step': 2,
                      'context': 'TEAM_C', 'messages': ['  m step 2: side 0 member 0 hp 5, reference 6']}),
                    (runner_result('UNSUPPORTED', 'CLOSURE_DEV', None, 4, 'create: DUOFORGE_E_UNSUPPORTED'),
                     {'bucket': 'UNSUPPORTED', 'detail': 'create: DUOFORGE_E_UNSUPPORTED', 'step': None,
                      'context': 'CLOSURE_DEV', 'messages': []})):
                with self.subTest(name=name, verdict=result.verdict):
                    record, worker, runner = self.process(name, spec, text, result=result)
                    self.assertEqual(list(record), SCHEMA)
                    self.assertEqual((record['name'], record['rule'], record['steps']), (name, None, result.steps))
                    for key, value in want.items():
                        self.assertEqual(record[key], value, key)
                    # The runner got this battle's records: one battle, closure or Team C by the spec.
                    (asked, records), = runner.requests
                    self.assertEqual(asked, name)
                    self.assertTrue(records.startswith('B %s %d ' % (name, team_c)), records[:60])
                    self.assertTrue(records.endswith('\nEND\n'))
                    self.assertEqual(records.count('\nB '), 0)

    def test_a_runner_that_died_or_hung_on_the_battle_is_a_divergence(self):
        spec, text = committed(CLOSURE)
        for failure, detail in (
                (driver.ChildFailure('the runner gave no answer: exited with status 3', 'runner', 'died', 3,
                                     'assertion failed\nat turn.c:12'), 'runner died (exit 3)'),
                (driver.ChildFailure('the runner gave no answer: exited with status 3221225477', 'runner', 'died',
                                     3221225477, ''), 'runner died (exit 0xc0000005)'),
                (driver.ChildFailure('the runner gave no answer: no answer in 60 s, killed', 'runner', 'timed out', 1,
                                     ''), 'runner timed out')):
            with self.subTest(detail):
                record, worker, runner = self.process(CLOSURE, spec, text, runner_raises=failure)
                self.assertEqual(list(record), SCHEMA)
                self.assertEqual((record['bucket'], record['rule'], record['detail'], record['step'], record['context']),
                                 ('DIVERGENCE', None, detail, None, None))
                self.assertEqual(record['messages'], [line for line in failure.stderr.split('\n') if line])

    def test_a_worker_that_died_or_hung_on_the_battle_is_a_ref_error(self):
        spec, text = committed(CLOSURE)
        for failure, detail in (
                (driver.ChildFailure('the reference worker gave no answer', 'worker', 'died', 134, 'Error: heap'),
                 'worker died (exit 134)'),
                (driver.ChildFailure('the reference worker gave no answer', 'worker', 'timed out', 1, ''),
                 'worker timed out')):
            with self.subTest(detail):
                def die(s, f):
                    raise failure
                record, worker, runner = self.process(CLOSURE, spec, text, die)
                self.assertEqual((record['bucket'], record['rule'], record['detail']), ('REF_ERROR', None, detail))
                self.assertEqual(runner.requests, [])

    def test_a_tool_error_that_is_not_a_child_failure_still_stops_the_replay(self):
        spec, text = committed(CLOSURE)
        with self.assertRaises(driver.ToolError) as cm:
            self.process(CLOSURE, spec, text, runner_raises=driver.ToolError('the runner: not a result line'))
        self.assertNotIsInstance(cm.exception, driver.ChildFailure)

    def test_every_result_has_one_bucket_and_one_schema(self):
        spec, text = committed(CLOSURE)
        records = [self.process(CLOSURE, spec, text, result=runner_result(v))[0] for v in driver.VERDICTS]
        records.append(self.process(CLOSURE, spec, text, lambda s, f: 'other')[0])
        for record in records:
            self.assertEqual(list(record), SCHEMA)
            self.assertIn(record['bucket'], driver.BUCKETS)
            json.dumps(record)
        self.assertEqual([r['bucket'] for r in records], ['PASS', 'DIVERGENCE', 'UNSUPPORTED', 'REF_ERROR'])
        with self.assertRaises(AssertionError):
            driver.new_result('x', 'MAYBE')


def child_code(body):
    return 'import sys\n' + body


class StandInRunner(driver.DiffRunner):
    """The client of the runner over a Python process that plays the runner."""

    def __init__(self, code, timeout=30):
        driver.Child.__init__(self, [sys.executable, '-c', child_code(code)], 'the runner', timeout)


class StandInWorker(driver.NodeWorker):
    def __init__(self, code, timeout=30):
        driver.Child.__init__(self, [sys.executable, '-c', child_code(code)], 'the reference worker', timeout)
        self.next_id = 1


# A runner that answers every battle with a failing step; it ends a line with CR LF as a Windows runner may.
RUNNER_ANSWERS = r'''
name = None
for line in sys.stdin:
    if line.startswith('B '):
        name = line.split()[1]
    elif line.strip() == 'END':
        sys.stdout.write('  %s step 2: side 0 member 0 hp 5, reference 6\r\n' % name)
        sys.stdout.write('R %s DIVERGENCE CLOSURE 2 9 differences: state 1\r\n' % name)
        sys.stdout.flush()
'''
RECORDS = 'B x 0 0 1 1 0\nEND\n'  # what the stand-ins read: the name is all they look at
# A child that says its own priority and waits for EOF.
PRIORITY = r'''
import os
if os.name == 'nt':
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    print(hex(k.GetPriorityClass(k.GetCurrentProcess())))
else:
    print(os.nice(0))
sys.stdout.flush()
sys.stdin.read()
'''


class Runner(unittest.TestCase):
    def stand_in(self, code, timeout=30):
        runner = StandInRunner(code, timeout)
        self.addCleanup(runner.kill)
        return runner

    def test_the_messages_come_before_the_result_line_and_the_next_battle_follows(self):
        runner = self.stand_in(RUNNER_ANSWERS)
        for name in ('x', 'y'):
            got = runner.run(name, RECORDS.replace(' x ', ' %s ' % name))
            self.assertEqual(got, driver.RunnerResult('DIVERGENCE', 'CLOSURE', 2, 9, 'differences: state 1',
                                                      ['  %s step 2: side 0 member 0 hp 5, reference 6' % name]))
        self.assertEqual(runner.close(), [])  # EOF on stdin, status 0

    def test_a_runner_that_refuses_its_input_is_a_bug_of_the_tool_with_its_stderr(self):
        """Status 2 and "malformed input" is the reader refusing what the driver wrote: not a finding about a battle."""
        runner = self.stand_in("sys.stdin.readline()\nsys.stderr.write('duoforge_diff_runner: malformed input: line 3: boom\\n')\nsys.exit(2)")
        with self.assertRaises(driver.ToolError) as cm:
            runner.run('x', RECORDS)
        self.assertNotIsInstance(cm.exception, driver.ChildFailure)
        self.assertRegex(str(cm.exception), r'^the runner .*exited with status 2: duoforge_diff_runner: malformed input: line 3: boom$')

    def test_a_runner_that_dies_on_a_battle_is_a_child_failure(self):
        """Any other death (a crash, an abort, a sanitizer's exit) is a finding: the exit code and the stderr are kept."""
        runner = self.stand_in("sys.stdin.readline()\nsys.stderr.write('assertion failed\\nat turn.c:12\\n')\nsys.exit(3)")
        with self.assertRaises(driver.ChildFailure) as cm:
            runner.run('x', RECORDS)
        e = cm.exception
        self.assertEqual((e.role, e.kind, e.exit_code, e.detail()), ('runner', 'died', 3, 'runner died (exit 3)'))
        self.assertEqual(e.stderr, 'assertion failed\nat turn.c:12')
        self.assertIsInstance(e, driver.ToolError)  # code that does not know better stops
        self.assertTrue(runner.failed)

    def test_a_runner_that_does_not_answer_is_killed_after_the_timeout(self):
        runner = self.stand_in('sys.stdin.readline()\nimport time\ntime.sleep(60)', timeout=1)
        with self.assertRaises(driver.ChildFailure) as cm:
            runner.run('x', RECORDS)
        self.assertIn('no answer in 1 s, killed', str(cm.exception))
        self.assertEqual((cm.exception.role, cm.exception.kind, cm.exception.detail()), ('runner', 'timed out', 'runner timed out'))
        self.assertIsNotNone(runner.proc.poll())
        self.assertTrue(runner.failed)

    def test_exit_codes_as_a_person_reads_them(self):
        self.assertEqual([driver.format_exit(c) for c in (0, 3, 134, -11, 3221225477, 0xC0000409)],
                         ['0', '3', '134', '-11', '0xc0000005', '0xc0000409'])

    def test_a_child_runs_below_normal_priority(self):
        """BELOW_NORMAL_PRIORITY_CLASS on Windows, nice 10 elsewhere: the child reports it itself."""
        runner = self.stand_in(PRIORITY)
        reported = runner.readline().decode('ascii').strip()
        if os.name == 'nt':
            self.assertEqual(reported, '0x4000')
        else:
            self.assertGreaterEqual(int(reported), 10)
        self.assertEqual(runner.close(), [])

    def test_how_a_child_is_started_below_normal_priority(self):
        which = {'nice': '/usr/bin/nice', 'prog': '/opt/prog'}.get
        self.assertEqual(driver.low_priority(['prog', 'a', 'b'], windows=False, which=which),
                         (['/usr/bin/nice', '-n', '10', 'prog', 'a', 'b'], {}))
        self.assertEqual(driver.low_priority(['prog', 'a'], windows=True, which=lambda name: None),
                         (['prog', 'a'], {'creationflags': 0x4000}))  # BELOW_NORMAL_PRIORITY_CLASS of the Windows API
        # A program that is not there is refused as Popen refuses it. Left to nice(1) it would be started all the
        # same, and the driver would see a child that died (exit 127) on its first battle.
        with self.assertRaises(FileNotFoundError) as cm:
            driver.low_priority(['/no/such/prog'], windows=False, which=which)
        self.assertEqual(cm.exception.filename, '/no/such/prog')
        with self.assertRaises(driver.ToolError) as cm:  # no nice: a failure of the tool, said so
            driver.low_priority(['prog'], windows=False, which=lambda name: None)
        self.assertIn('nice is not on the PATH', str(cm.exception))

    def test_result_lines_that_are_not_the_format_are_failures_of_the_tool(self):
        for line, part in (('R other PASS CLOSURE - 1 -', 'not a result line'),  # another battle's
                           ('R x PASS CLOSURE - 1', 'not a result line'),  # no detail
                           ('R x MAYBE CLOSURE - 1 -', 'not a result line'),
                           ('R x PASS CLOSURE two 1 -', 'no step numbers'),
                           ('R x PASS CLOSURE - 1.5 -', 'no step numbers')):
            with self.subTest(line=line):
                runner = self.stand_in("for l in sys.stdin:\n if l.strip() == 'END':\n  print(%r)\n  sys.stdout.flush()" % line)
                with self.assertRaises(driver.ToolError) as cm:
                    runner.run('x', RECORDS)
                self.assertIn(part, str(cm.exception))

    def test_a_result_line_without_a_step_and_a_detail_with_spaces(self):
        runner = self.stand_in("for l in sys.stdin:\n if l.strip() == 'END':\n  print('R x UNSUPPORTED TEAM_C_DEV - 12 create: DUOFORGE_E_UNSUPPORTED')\n  sys.stdout.flush()")
        self.assertEqual(runner.run('x', RECORDS), driver.RunnerResult(
            'UNSUPPORTED', 'TEAM_C_DEV', None, 12, 'create: DUOFORGE_E_UNSUPPORTED', []))

    def test_a_runner_that_leaves_with_a_status_at_eof_is_reported(self):
        runner = self.stand_in("sys.stdin.read()\nsys.stderr.write('leak\\n')\nsys.exit(5)")
        problems = runner.close()
        self.assertEqual(len(problems), 1)
        self.assertRegex(problems[0], r'^the runner left with status 5: leak$')

    def test_a_program_that_is_not_there(self):
        with self.assertRaises(driver.ToolError) as cm:
            driver.DiffRunner(os.path.join(ROOT, 'no', 'such', 'runner'))
        self.assertIn('cannot start the runner', str(cm.exception))


# A worker that answers as ps_worker.js does, and misbehaves for some spec file names.
WORKER_ANSWERS = r'''
import json
for line in sys.stdin:
    req = json.loads(line)
    reply = None
    if not line.isascii():
        reply = {'id': req['id'], 'ok': False, 'error': 'the request is not ASCII'}
    elif req['cmd'] == 'version':
        reply = {'id': req['id'], 'ok': True, 'node': 'v0', 'pin': 'p', 'harness': 3}
    elif req['cmd'] == 'play':
        kind = req['battle'].get('kind')
        ok = {'ok': True, 'choices': [{'p1': 'team 1234', 'p2': 'team 4321'}, {'p1': 'move 1'}], 'ended': True, 'steps': 2}
        if kind == 'bad':
            reply = {'id': req['id'], 'ok': False, 'error': 'no accepted choice', 'stack': 'Error: no accepted choice'}
        elif kind == 'choices':
            reply = dict(ok, id=req['id'], choices='x')
        elif kind == 'steps':
            reply = dict(ok, id=req['id'], steps=3)
        elif kind == 'ended':
            reply = dict(ok, id=req['id'], ended='yes')
        else:
            reply = dict(ok, id=req['id'])
    elif req['spec_file'] == 'bad.json':
        reply = {'id': req['id'], 'ok': False, 'error': 'it broke', 'stack': 'Error: it broke\n    at here'}
    elif req['spec_file'] == 'skew.json':
        reply = {'id': req['id'] + 1, 'ok': True, 'trace': 't'}
    elif req['spec_file'] == 'junk.json':
        sys.stdout.write('not json\n')
    elif req['spec_file'] == 'notrace.json':
        reply = {'id': req['id'], 'ok': True}
    elif req['spec_file'] == 'utf8.json':
        sys.stdout.buffer.write((json.dumps({'id': req['id'], 'ok': True, 'trace': 'Pokémon'}, ensure_ascii=False) + '\n').encode('utf-8'))
    else:
        reply = {'id': req['id'], 'ok': True, 'trace': 'trace of ' + req['spec_file'] + ' ' + json.dumps(req['spec'])}
    if reply is not None:
        sys.stdout.write(json.dumps(reply) + '\n')
    sys.stdout.flush()
'''


class Worker(unittest.TestCase):
    def stand_in(self, code=WORKER_ANSWERS):
        worker = StandInWorker(code)
        self.addCleanup(worker.kill)
        return worker

    def test_version_and_record(self):
        worker = self.stand_in()
        self.assertEqual(worker.version(), {'node': 'v0', 'pin': 'p', 'harness': 3})
        # The request is one ASCII line whatever the spec holds; the answer may be UTF-8.
        self.assertEqual(worker.record({'teams': ['é']}, 'a.json'), 'trace of a.json {"teams": ["\\u00e9"]}')
        self.assertEqual(worker.record({}, 'utf8.json'), 'Pokémon')
        self.assertEqual(worker.close(), [])

    def test_an_ok_false_answer_is_a_worker_error(self):
        worker = self.stand_in()
        with self.assertRaises(driver.WorkerError) as cm:
            worker.record({}, 'bad.json')
        self.assertEqual((cm.exception.error, cm.exception.stack), ('it broke', 'Error: it broke\n    at here'))
        self.assertEqual(worker.record({}, 'again.json'), 'trace of again.json {}')  # it keeps serving

    def test_answers_out_of_protocol_are_failures_of_the_tool(self):
        for spec_file, part in (('skew.json', 'out of protocol'), ('junk.json', 'not JSON'),
                                ('notrace.json', 'without a trace')):
            with self.subTest(spec_file):
                worker = self.stand_in()
                with self.assertRaises(driver.ToolError) as cm:
                    worker.record({}, spec_file)
                self.assertIn(part, str(cm.exception))

    def test_a_worker_that_dies(self):
        worker = self.stand_in("sys.stdin.readline()\nsys.stderr.write('Error: out of memory\\n')\nsys.exit(134)")
        with self.assertRaises(driver.ChildFailure) as cm:
            worker.record({}, 'a.json')
        self.assertRegex(str(cm.exception), r'exited with status 134: Error: out of memory$')
        e = cm.exception
        self.assertEqual((e.role, e.kind, e.exit_code, e.detail(), e.stderr),
                         ('worker', 'died', 134, 'worker died (exit 134)', 'Error: out of memory'))
        self.assertTrue(worker.failed)

    def test_a_worker_that_does_not_answer(self):
        worker = StandInWorker('sys.stdin.readline()\nimport time\ntime.sleep(60)', timeout=1)
        self.addCleanup(worker.kill)
        with self.assertRaises(driver.ChildFailure) as cm:
            worker.play({}, {})
        self.assertEqual((cm.exception.role, cm.exception.detail()), ('worker', 'worker timed out'))

    def test_play(self):
        worker = self.stand_in()
        self.assertEqual(worker.play({'kind': 'ok'}, {'seed': 1}),
                         {'choices': [{'p1': 'team 1234', 'p2': 'team 4321'}, {'p1': 'move 1'}], 'ended': True, 'steps': 2})
        with self.assertRaises(driver.WorkerError) as cm:
            worker.play({'kind': 'bad'}, {'seed': 1})
        self.assertEqual((cm.exception.error, cm.exception.stack), ('no accepted choice', 'Error: no accepted choice'))
        self.assertTrue(worker.play({'kind': 'ok'}, {'seed': 1})['ended'])  # it keeps serving
        for kind in ('choices', 'steps', 'ended'):  # answers that are not a play
            with self.subTest(kind):
                with self.assertRaises(driver.ToolError) as cm:
                    worker.play({'kind': kind}, {'seed': 1})
                self.assertIn('answered a play without choices, ended and steps', str(cm.exception))


class Lanes(unittest.TestCase):
    """The threads: every battle once, the children closed or killed, the order of the output."""

    def lanes(self, names, workers, handle, make_worker=None, make_runner=None, **kwargs):
        made = {'workers': [], 'runners': []}
        lock = threading.Lock()

        def make(kind, fake):
            def factory():
                child = fake()
                with lock:
                    made[kind].append(child)
                return child
            return factory

        outcome = None
        try:
            outcome = driver.run_lanes(names, workers, make('workers', make_worker or (lambda: FakeWorker())),
                                       make('runners', make_runner or (lambda: FakeRunner())), handle, **kwargs)
            error = None
        except BaseException as e:
            error = e
        return outcome, error, made

    @staticmethod
    def passes(name, worker, runner):
        return driver.new_result(name, 'PASS')

    def test_every_battle_is_served_once_and_every_child_is_closed(self):
        names = ['b%02d' % i for i in range(10)]
        seen = []

        def handle(name, worker, runner):
            seen.append(name)
            return driver.new_result(name, 'PASS')

        outcome, error, made = self.lanes(names, 3, handle)
        self.assertIsNone(error)
        results, version = outcome
        self.assertEqual((sorted(results), sorted(seen), version), (names, names, VERSION))
        self.assertEqual((len(made['workers']), len(made['runners'])), (3, 3))
        for child in made['workers'] + made['runners']:
            self.assertEqual((child.closed, child.killed), (1, 0))

    def test_a_child_that_failed_is_replaced_before_the_next_battle(self):
        served = {}

        def handle(name, worker, runner):
            served[name] = (id(worker), id(runner))
            if name == 'b01':
                runner.failed = True  # the runner died on this battle; the handler made a bucket of it
            if name == 'b03':
                worker.failed = True
            return driver.new_result(name, 'PASS')

        outcome, error, made = self.lanes(['b00', 'b01', 'b02', 'b03', 'b04'], 1, handle)
        self.assertIsNone(error)
        self.assertEqual(sorted(outcome[0]), ['b00', 'b01', 'b02', 'b03', 'b04'])
        (w0, w1), (r0, r1) = made['workers'], made['runners']
        self.assertEqual((len(made['workers']), len(made['runners'])), (2, 2))
        # The runner is new from b02 on, the worker from b04 on.
        self.assertEqual([served[n] for n in ('b00', 'b01', 'b02', 'b03', 'b04')],
                         [(id(w0), id(r0)), (id(w0), id(r0)), (id(w0), id(r1)), (id(w0), id(r1)), (id(w1), id(r1))])
        self.assertEqual([(c.killed, c.closed) for c in (r0, r1, w0, w1)], [(1, 0), (0, 1), (1, 0), (0, 1)])

    def test_a_worker_that_comes_back_with_another_version_stops_the_run(self):
        versions = iter([VERSION, dict(VERSION, node='v9.9.9')])

        def handle(name, worker, runner):
            worker.failed = True
            return driver.new_result(name, 'PASS')

        outcome, error, made = self.lanes(['a', 'b'], 1, handle, make_worker=lambda: FakeWorker(version=next(versions)))
        self.assertIsInstance(error, driver.ToolError)
        self.assertIn('another version', str(error))
        for child in made['workers'] + made['runners']:
            self.assertEqual(child.closed + child.killed, 1)

    def test_a_replacement_that_cannot_be_started_stops_the_run(self):
        count = [0]

        def make_runner():
            count[0] += 1
            if count[0] > 1:
                raise driver.ToolError('cannot start the runner')
            return FakeRunner()

        def handle(name, worker, runner):
            runner.failed = True
            return driver.new_result(name, 'PASS')

        outcome, error, made = self.lanes(['a', 'b', 'c'], 1, handle, make_runner=make_runner)
        self.assertEqual(str(error), 'cannot start the runner')
        for child in made['workers'] + made['runners']:
            self.assertEqual(child.closed + child.killed, 1)

    def test_a_stop_request_ends_the_lanes_between_battles(self):
        done = []

        def handle(name, worker, runner):
            done.append(name)
            return driver.new_result(name, 'PASS')

        names = ['b%02d' % i for i in range(10)]
        seen = []
        outcome, error, made = self.lanes(names, 1, handle, should_stop=lambda: len(done) >= 3,
                                          on_result=lambda name, record: seen.append((name, record['bucket'])))
        self.assertIsNone(error)
        self.assertEqual((sorted(outcome[0]), done), (names[:3], names[:3]))  # no battle is left half done
        self.assertEqual(seen, [(n, 'PASS') for n in names[:3]])  # and every result was handed on, in order
        for child in made['workers'] + made['runners']:
            self.assertEqual((child.closed, child.killed), (1, 0))

    def test_a_failure_in_the_result_callback_stops_the_run(self):
        def on_result(name, record):
            raise OSError('disk full')

        outcome, error, made = self.lanes(['a', 'b'], 1, self.passes, on_result=on_result)
        self.assertIsInstance(error, OSError)

    def test_nothing_to_replay_is_a_failure(self):
        outcome, error, made = self.lanes([], 4, self.passes)
        self.assertIsInstance(error, driver.ToolError)
        self.assertEqual(made['workers'], [])

    def test_there_are_no_more_lanes_than_battles(self):
        outcome, error, made = self.lanes(['a', 'b'], 8, self.passes)
        self.assertIsNone(error)
        self.assertEqual(len(made['workers']), 2)

    def test_a_failure_stops_the_replay_and_no_child_is_left(self):
        names = ['b%02d' % i for i in range(30)]

        def handle(name, worker, runner):
            if name == 'b02':
                raise driver.ToolError('the runner went away')
            return driver.new_result(name, 'PASS')

        outcome, error, made = self.lanes(names, 4, handle)
        self.assertIsInstance(error, driver.ToolError)
        self.assertEqual(str(error), 'the runner went away')
        self.assertEqual(sum(c.killed for c in made['workers'] + made['runners']), 2)  # the failing lane's
        for child in made['workers'] + made['runners']:
            self.assertEqual(child.closed + child.killed, 1)  # gone, one way or the other

    def test_an_unexpected_error_propagates_as_it_is(self):
        boom = AttributeError('a bug')

        def handle(name, worker, runner):
            raise boom

        outcome, error, made = self.lanes(['a', 'b', 'c'], 2, handle)
        self.assertIs(error, boom)
        for child in made['workers'] + made['runners']:
            self.assertEqual(child.closed + child.killed, 1)

    def test_a_child_that_does_not_leave_cleanly_is_a_failure(self):
        outcome, error, made = self.lanes(['a'], 1, self.passes,
                                          make_runner=lambda: FakeRunner(leaves_with=['the runner left with status 5']))
        self.assertIsInstance(error, driver.ToolError)
        self.assertEqual(str(error), 'the runner left with status 5')

    def test_a_child_that_cannot_be_started(self):
        def cannot():
            raise driver.ToolError('cannot start the reference worker')

        outcome, error, made = self.lanes(['a'], 1, self.passes, make_worker=cannot)
        self.assertEqual(str(error), 'cannot start the reference worker')
        self.assertEqual(made['runners'], [])  # not started without its worker

    def test_workers_that_disagree_about_their_versions(self):
        versions = iter([VERSION, dict(VERSION, node='v1.1.1')])
        lock = threading.Lock()

        def make():
            with lock:
                return FakeWorker(version=next(versions))

        outcome, error, made = self.lanes(['a', 'b', 'c', 'd'], 2, self.passes, make_worker=make)
        self.assertIsInstance(error, driver.ToolError)
        self.assertIn('disagree about their versions', str(error))

    def test_the_output_does_not_depend_on_timing_or_on_the_number_of_lanes(self):
        names = ['n%02d' % i for i in range(12)]
        outputs = []
        for workers in (1, 4, 8):
            last_done = threading.Event()

            def handle(name, worker, runner):
                # With several lanes the first battle finishes last, after the last one.
                if workers > 1 and name == names[0]:
                    self.assertTrue(last_done.wait(30))
                    time.sleep(0.2)  # the lane of the last battle stores its result first
                i = names.index(name)
                record = driver.new_result(name, ('PASS', 'DIVERGENCE', 'ORACLE_GAP')[i % 3],
                                           rule='r%d' % (i % 2) if i % 3 == 2 else None, step=i if i % 3 == 1 else None)
                if name == names[-1]:
                    last_done.set()
                return record

            outcome, error, made = self.lanes(names, workers, handle)
            self.assertIsNone(error)
            results, version = outcome
            if workers > 1:
                self.assertEqual(list(results)[-1], names[0])  # it arrived last
            with tempfile.TemporaryDirectory() as tmp:
                driver.write_outputs(tmp, results, driver.summarize(results, version, 'replay', 'head', '1.2.3'))
                with io.open(os.path.join(tmp, 'battles.jsonl'), 'rb') as a, io.open(os.path.join(tmp, 'summary.json'), 'rb') as b:
                    outputs.append((a.read(), b.read()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])
        self.assertEqual([json.loads(line)['name'] for line in outputs[0][0].decode('ascii').splitlines()], names)


class Outputs(unittest.TestCase):
    def results(self):
        return {name: driver.new_result(name, bucket, rule=rule, detail=detail, step=step, steps=3 if step is not None else None,
                                        context='CLOSURE' if step is not None else None, messages=['m é'] if rule else [])
                for name, bucket, rule, detail, step in (
                    ('b', 'DIVERGENCE', None, 'differences: state 1', 2),
                    ('a', 'PASS', None, None, None),
                    ('d', 'ORACLE_GAP', 'protocol-line', 'foo', None),
                    ('c', 'ORACLE_GAP', 'protocol-line', 'bar', None),
                    ('e', 'ORACLE_GAP', 'untyped:KeyError', "'X' (parse_team:1)", None),
                    ('f', 'REF_ERROR', None, 'trace differs from the committed trace', None))}

    def test_the_summary_counts_buckets_and_rules(self):
        summary = driver.summarize(self.results(), VERSION, 'replay', 'abc123', '9.8.7')
        self.assertEqual(summary, {
            'mode': 'replay', 'battles': 6,
            'buckets': {'PASS': 1, 'DIVERGENCE': 1, 'UNSUPPORTED': 0, 'ORACLE_GAP': 3, 'REF_ERROR': 1},
            'rules': {'protocol-line': 2, 'untyped:KeyError': 1},
            'node': 'v0.0.0', 'pin': '0' * 40, 'harness': 14, 'git_head': 'abc123', 'library_version': '9.8.7'})
        self.assertEqual(sorted(summary['buckets']), sorted(driver.BUCKETS))  # every bucket, also with 0

    def test_the_files(self):
        results = self.results()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'nested', 'run')  # made on demand
            summary = driver.summarize(results, VERSION, 'replay', 'abc123', '9.8.7')
            driver.write_outputs(out, results, summary)
            self.assertEqual(sorted(os.listdir(out)), ['battles.jsonl', 'summary.json'])
            with io.open(os.path.join(out, 'battles.jsonl'), 'rb') as f:
                raw = f.read()
            with io.open(os.path.join(out, 'summary.json'), 'rb') as f:
                raw_summary = f.read()
        raw.decode('ascii')  # ASCII: the messages are escaped
        self.assertNotIn(b'\r', raw + raw_summary)
        lines = raw.decode('ascii').split('\n')
        self.assertEqual(lines[-1], '')
        self.assertEqual([json.loads(line)['name'] for line in lines[:-1]], ['a', 'b', 'c', 'd', 'e', 'f'])  # by name
        for line in lines[:-1]:
            record = json.loads(line)
            self.assertEqual(list(record), SCHEMA)
            self.assertEqual(record, results[record['name']])
        self.assertEqual(json.loads(raw_summary.decode('ascii')), summary)
        self.assertEqual(raw_summary.decode('ascii'), json.dumps(summary, indent=1, sort_keys=True) + '\n')

    def test_the_library_version_is_the_one_of_the_header(self):
        with io.open(os.path.join(ROOT, 'include', 'duoforge', 'duoforge.h'), encoding='utf-8') as f:
            text = f.read()
        self.assertEqual(driver.library_version(ROOT), re.search(r'#define DUOFORGE_VERSION_STRING "([^"]+)"', text).group(1))

    def test_load_committed_reads_line_ends_as_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ('specs', 'traces'):
                os.makedirs(os.path.join(tmp, 'tests', 'reference', kind))
            with io.open(os.path.join(tmp, 'tests', 'reference', 'specs', 'x.json'), 'w', encoding='utf-8') as f:
                f.write('{"a": 1}')
            with io.open(os.path.join(tmp, 'tests', 'reference', 'traces', 'x.json'), 'wb') as f:
                f.write('{\r\n "p": "Pokémon"\r\n}\r\n'.encode('utf-8'))
            self.assertEqual(driver.load_committed(tmp, 'x'), ({'a': 1}, '{\n "p": "Pokémon"\n}\n'))
            self.assertEqual(driver.spec_names(tmp), ['x'])

    def test_the_specs_are_selected_by_a_glob(self):
        names = driver.spec_names(ROOT)
        self.assertGreater(len(names), 100)
        self.assertEqual(names, sorted(names))
        self.assertEqual(driver.select_names(names, None), names)
        self.assertEqual(driver.select_names(names, 's2_*'), [n for n in names if n.startswith('s2_')])
        self.assertEqual(driver.select_names(names, CLOSURE), [CLOSURE])
        with self.assertRaises(ValueError):
            driver.select_names(names, 'no_such_*')

    def test_first_difference_and_the_place_of_a_raise(self):
        self.assertEqual(driver.first_difference('a\nb\nc', 'a\nb\nd'), 'line 3: c against d')
        self.assertEqual(driver.first_difference('a\nb', 'a'), 'line 2: b against <end>')
        self.assertEqual(driver.clip('x' * 300), 'x' * 200 + '...')
        self.assertEqual(driver.printable('Pokémon ☃'), 'Pok\\xe9mon \\u2603')  # the console may be cp1252
        self.assertEqual(driver.printable('x' * 300), 'x' * 160 + '...')
        try:
            raise KeyError('k')
        except KeyError as e:
            function, line = driver.raised_at(e)
        self.assertEqual(function, 'test_first_difference_and_the_place_of_a_raise')
        self.assertEqual(linecache.getline(__file__, line).strip(), "raise KeyError('k')")


class Cli(unittest.TestCase):
    def refused(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            driver.main(list(args))
        self.assertEqual(cm.exception.code, 2)
        return err.getvalue()

    def test_bad_command_lines(self):
        exe = os.path.abspath(__file__)  # any file will do as a runner here
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        checkout = tmp.name
        os.makedirs(os.path.join(checkout, 'dist', 'sim'))
        self.assertIn('the following arguments are required', self.refused('replay', '--runner', exe))
        self.assertIn('--workers must be at least 1', self.refused('replay', '--checkout', checkout, '--runner', exe, '--workers', '0'))
        self.assertIn('is not a file', self.refused('replay', '--checkout', checkout, '--runner', exe + '.none'))
        self.assertIn('has no dist/sim', self.refused('replay', '--checkout', ROOT, '--runner', exe))
        self.assertIn("no committed spec matches 'nothing*'", self.refused(
            'replay', '--checkout', checkout, '--runner', exe, '--node', exe, '--only', 'nothing*'))
        self.assertIn('required', self.refused())  # a mode is required


@unittest.skipUnless(RUNNER, 'DUOFORGE_DIFF_RUNNER is not set (CTest sets it to the runner it builds)')
class RealRunner(unittest.TestCase):
    """The real runner and the real converter on the committed battles; only the reference is
    a stand-in, which answers the committed trace."""

    class CommittedWorker(FakeWorker):
        def __init__(self):
            super().__init__(lambda spec, spec_file: committed(spec_file[:-len('.json')])[1])

    def replay(self, names, workers):
        handle = driver.battle_handler(ROOT, {False: tables(False), True: tables(True)})
        return driver.run_lanes(names, workers, self.CommittedWorker, lambda: driver.DiffRunner(RUNNER), handle)

    def test_every_committed_battle_is_a_pass(self):
        names = driver.spec_names(ROOT)
        results, version = self.replay(names, 4)
        self.assertEqual(sorted(results), names)
        self.assertEqual({n: r['bucket'] for n, r in results.items() if r['bucket'] != 'PASS'}, {})
        for record in results.values():
            self.assertEqual(list(record), SCHEMA)
            self.assertEqual((record['rule'], record['detail'], record['step'], record['messages']), (None, None, None, []))
            self.assertGreaterEqual(record['steps'], 1)
        self.assertEqual({r['context'] for r in results.values()}, {'CLOSURE', 'CLOSURE_DEV', 'TEAM_C', 'TEAM_C_DEV'})

    def test_the_lanes_do_not_change_what_a_battle_comes_to(self):
        names = sorted(set(driver.spec_names(ROOT)[:10] + [TEAM_C, 's3_struggle_end']))
        one, _ = self.replay(names, 1)
        three, _ = self.replay(names, 3)
        self.assertEqual(one, three)

    def result_of(self, name, kind=0, mutate=None, domain=()):
        """The runner's result for the committed battle `name` written with data kind `kind`, its data changed by
        `mutate` and with the domain samples `domain`."""
        spec, text = committed(name)
        team_c = trace_to_c.spec_is_team_c(name, spec)
        data = trace_to_c.convert_battle(name, spec, json.loads(text), tables(team_c))
        if mutate:
            mutate(data)
        records = io.StringIO()
        conformance_records.write_battle(data, team_c, records, kind=kind, domain=domain)
        runner = driver.DiffRunner(RUNNER)
        self.addCleanup(runner.kill)
        return runner.run(name, records.getvalue())

    # The domain check: before a step the engine's candidates for a side are compared with the set of choices that
    # the reference accepted. At team selection of a battle of six members the set is the 360 ordered picks of four.
    ALL_PICKS = [('team', list(p)) for p in itertools.permutations(range(6), 4)]
    REAL = 'm5_real_aa_1'

    def domain_result(self, samples):
        return self.result_of(self.REAL, conformance_records.data_kinds(ROOT)['CLOSURE'], domain=samples)

    def test_the_domain_of_the_engine_is_the_domain_of_the_reference_when_they_are_the_same_set(self):
        result = self.domain_result([{'step': 0, 'side': 0, 'choices': self.ALL_PICKS},
                                     {'step': 0, 'side': 1, 'choices': self.ALL_PICKS}])
        self.assertEqual((result.verdict, result.step, result.detail, result.messages), ('PASS', None, '-', []))
        # What the reference played at the turn that follows is among the engine's candidates (nothing reference-only).
        spec, text = committed(self.REAL)
        data = trace_to_c.convert_battle(self.REAL, spec, json.loads(text), tables(False))
        played = ('slots', [tuple(c) for c in data['steps'][1]['cmds'][0]])
        result = self.domain_result([{'step': 1, 'side': 0, 'choices': [played]}])
        self.assertEqual((result.verdict, result.step), ('DIVERGENCE', 1))
        self.assertRegex(result.detail, r'^domain: engine-only [1-9]\d*, reference-only 0 \(step 1 side 0\)$')

    def test_a_choice_that_the_reference_does_not_accept_is_engine_only(self):
        missing = self.ALL_PICKS[137]
        result = self.domain_result([{'step': 0, 'side': 1, 'choices': self.ALL_PICKS[:137] + self.ALL_PICKS[138:]}])
        self.assertEqual((result.verdict, result.context, result.step), ('DIVERGENCE', 'CLOSURE', 0))
        self.assertEqual(result.detail, 'domain: engine-only 1, reference-only 0 (step 0 side 1)')
        self.assertEqual(result.messages, ['  %s step 0: domain side 1 engine-only: team %s' % (self.REAL, ' '.join(map(str, missing[1])))])

    def test_a_choice_that_the_engine_does_not_offer_is_reference_only(self):
        # Showdown does not accept a slots choice at team preview, so one in the set is a lie about the reference: the
        # engine does not offer it.
        slots = ('slots', [(1, 0, 255, 0, 0), (3, 0, 0, 0, 0)])
        result = self.domain_result([{'step': 0, 'side': 0, 'choices': self.ALL_PICKS + [slots]}])
        self.assertEqual((result.verdict, result.step), ('DIVERGENCE', 0))
        self.assertEqual(result.detail, 'domain: engine-only 0, reference-only 1 (step 0 side 0)')
        self.assertEqual(result.messages, ['  %s step 0: domain side 0 reference-only: slots move 0 -> none, pass' % self.REAL])

    def test_both_kinds_of_difference_at_once_are_counted_and_at_most_three_examples_of_each_are_given(self):
        slots = [('slots', [(1, s, 255, 0, 0), (3, 0, 0, 0, 0)]) for s in range(4)]
        result = self.domain_result([{'step': 0, 'side': 0, 'choices': self.ALL_PICKS[5:] + slots}])
        self.assertEqual(result.detail, 'domain: engine-only 5, reference-only 4 (step 0 side 0)')
        engine_only = [m for m in result.messages if 'engine-only: ' in m]
        reference_only = [m for m in result.messages if 'reference-only: ' in m]
        self.assertEqual([m.split('engine-only: ')[1] for m in engine_only],
                         ['team 0 1 2 3', 'team 0 1 2 4', 'team 0 1 2 5'])  # the first three in the order of the sets
        self.assertEqual(len(reference_only), 3)
        self.assertEqual(len(result.messages), 6)

    def test_the_first_sample_with_a_difference_ends_the_battle_and_a_later_one_is_not_looked_at(self):
        wrong = self.ALL_PICKS[1:]
        result = self.domain_result([{'step': 0, 'side': 0, 'choices': self.ALL_PICKS}, {'step': 0, 'side': 1, 'choices': wrong},
                                     {'step': 1, 'side': 0, 'choices': self.ALL_PICKS[:1]}])
        self.assertEqual((result.step, result.detail), (0, 'domain: engine-only 1, reference-only 0 (step 0 side 1)'))
        # The same wrong sample of step 1 alone: found there, before step 1 is applied.
        result = self.domain_result([{'step': 1, 'side': 1, 'choices': [('slots', [(1, 0, 255, 0, 0), (3, 0, 0, 0, 0)])]}])
        self.assertEqual(result.step, 1)

    def test_a_domain_sample_does_not_change_what_the_rest_of_the_battle_comes_to(self):
        plain = self.result_of(self.REAL, conformance_records.data_kinds(ROOT)['CLOSURE'])
        sampled = self.domain_result([{'step': 0, 'side': 0, 'choices': self.ALL_PICKS}])
        self.assertEqual((sampled.verdict, sampled.steps, sampled.context), (plain.verdict, plain.steps, plain.context))

    def test_a_strict_kind_is_the_context_and_there_is_no_fallback(self):
        kinds = conformance_records.data_kinds(ROOT)
        # Sets without an ability need CLOSURE_DEV: the conformance fallback finds it, a strict CLOSURE does not.
        fallback = self.result_of(CLOSURE)
        self.assertEqual((fallback.verdict, fallback.context, fallback.step), ('PASS', 'CLOSURE_DEV', None))
        strict = self.result_of(CLOSURE, kinds['CLOSURE'])
        self.assertEqual((strict.verdict, strict.context, strict.step, strict.messages), ('DIVERGENCE', 'CLOSURE', None, []))
        self.assertRegex(strict.detail, r'^create: DUOFORGE_E_\w+ \(CLOSURE\)$')  # one attempt, one status
        dev = self.result_of(CLOSURE, kinds['CLOSURE_DEV'])
        self.assertEqual((dev.verdict, dev.context), ('PASS', 'CLOSURE_DEV'))
        # Real teams run under CLOSURE, and Team C under TEAM_C (the profile battle has six real members).
        real = self.result_of('m5_real_aa_1', kinds['CLOSURE'])
        self.assertEqual((real.verdict, real.context), ('PASS', 'CLOSURE'))
        team_c = self.result_of('c01_team_c_profile', kinds['TEAM_C'])
        self.assertEqual((team_c.verdict, team_c.context), ('PASS', 'TEAM_C'))

    def test_a_create_that_fails_in_both_contexts_names_both_statuses(self):
        def unknown_species(data):
            row = list(data['members'][0][0])
            row[0] = 99  # the species id: no forme of the tables
            data['members'][0][0] = tuple(row)
        result = self.result_of(CLOSURE, mutate=unknown_species)
        self.assertEqual((result.verdict, result.context, result.step), ('DIVERGENCE', 'CLOSURE_DEV', None))
        self.assertRegex(result.detail, r'^create: DUOFORGE_E_\w+ \(CLOSURE\), DUOFORGE_E_\w+ \(CLOSURE_DEV\)$')
        strict = self.result_of(CLOSURE, conformance_records.data_kinds(ROOT)['CLOSURE_DEV'], unknown_species)
        self.assertRegex(strict.detail, r'^create: DUOFORGE_E_\w+ \(CLOSURE_DEV\)$')


class Records(unittest.TestCase):
    """conformance_records.write_battle: what it writes, what it refuses, where the order of the fields comes from."""

    def data(self, name):
        spec, trace = trace_to_c.load_battle(ROOT, name)
        team_c = trace_to_c.spec_is_team_c(name, spec)
        return trace_to_c.convert_battle(name, spec, trace, tables(team_c)), team_c

    def write(self, data, team_c):
        out = io.StringIO()
        conformance_records.write_battle(data, team_c, out)
        return out.getvalue()

    @staticmethod
    def flat(value):
        """The leaves of nested tuples, as text, in order."""
        if isinstance(value, (tuple, list)):
            return [x for v in value for x in Records.flat(v)]
        return [str(value)]

    def test_the_records_of_a_battle(self):
        for name in (CLOSURE, TEAM_C):
            with self.subTest(name):
                data, team_c = self.data(name)
                text = self.write(data, team_c)
                self.assertTrue(text.endswith('END\n'))
                self.assertNotIn('\r', text)
                text.encode('ascii')
                # What the format says, rebuilt from the data.
                want = ['B %s %d 0 %d %d %d 0' % (name, team_c, data['member_count'], len(data['steps']), data['dropped_total'])]
                for side, rows in enumerate(data['members']):
                    for index, row in enumerate(rows):
                        want.append(' '.join(['M', str(side), str(index)] + self.flat(row)))
                tape_off = ev_off = 0
                for st in data['steps']:
                    lens = [len(evs) for evs in st['events']]
                    want.append(' '.join(['S'] + self.flat(trace_to_c.step_record(st, tape_off, (ev_off, ev_off + lens[0]), lens))))
                    want += [' '.join(['T'] + self.flat(e)) for e in st['tape']]
                    want += [' '.join(['E'] + self.flat(e)) for evs in st['events'] for e in evs]
                    tape_off += len(st['tape'])
                    ev_off += sum(lens)
                want.append('END')
                self.assertEqual(text.split('\n')[:-1], want)

    def test_the_order_of_the_fields_is_the_converters(self):
        """The writer has no list of fields: it takes what step_record, the member rows and the event tuples give."""
        data, team_c = self.data(CLOSURE)
        real = trace_to_c.step_record
        with mock.patch.object(trace_to_c, 'step_record', lambda *args: tuple(reversed(real(*args)))):
            reversed_text = self.write(data, team_c)
        text = self.write(data, team_c)
        self.assertNotEqual(reversed_text, text)
        s_lines = [line for line in text.split('\n') if line.startswith('S ')]
        r_lines = [line for line in reversed_text.split('\n') if line.startswith('S ')]
        self.assertEqual(len(s_lines), len(r_lines))
        # The first value of the real record is the last of the nested tuple reversed, and so on: the
        # reversed record lists the fields of `ev_len` first.
        st = data['steps'][0]
        want = ' '.join(['S'] + self.flat(tuple(reversed(real(st, 0, (0, len(st['events'][0])), [len(e) for e in st['events']])))))
        self.assertEqual(r_lines[0], want)

    def test_data_the_format_cannot_hold_is_refused_and_nothing_is_written(self):
        data, team_c = self.data(CLOSURE)

        def with_change(change):
            copied = copy.deepcopy(data)
            change(copied)
            return copied

        def set_hp(d, value):
            """The hp of the first mon of side 0 in the first step (the rows are tuples)."""
            st = d['steps'][0]
            row = st['mons'][0][0]
            st['mons'] = (((row[0], value) + row[2:],) + st['mons'][0][1:],) + st['mons'][1:]

        cases = {
            'a name with a space': (with_change(lambda d: d.update(name='a b')), team_c),
            'a name that is too long': (with_change(lambda d: d.update(name='x' * 64)), team_c),
            'a bool for a number': (with_change(lambda d: set_hp(d, True)), team_c),
            'a float': (with_change(lambda d: set_hp(d, 1.0)), team_c),
            'a negative number': (with_change(lambda d: set_hp(d, -1)), team_c),
            'a number above 2**32 - 1': (with_change(lambda d: set_hp(d, 2 ** 32)), team_c),
            'team_c that is an int': (data, 1),
            'sides of different sizes': (with_change(lambda d: d['members'][1].pop()), team_c),
            'a member count of 7': (with_change(lambda d: d.update(member_count=7)), team_c),
            'no steps': (with_change(lambda d: d.update(steps=[])), team_c),
            'events of three players': (with_change(lambda d: d['steps'][0]['events'].append([])), team_c),
        }
        for what, (bad, flag) in cases.items():
            with self.subTest(what):
                out = io.StringIO()
                with self.assertRaises(ValueError):
                    conformance_records.write_battle(bad, flag, out)
                self.assertEqual(out.getvalue(), '')

    def test_the_two_files_of_every_committed_battle(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = conformance_records.write_all(ROOT, tmp)
            self.assertEqual([os.path.basename(p) for p, _ in written], ['closure.records', 'team_c.records'])
            names = conformance_records.committed_battles(ROOT)
            team_c = [n for n in names if trace_to_c.is_team_c(ROOT, n)]
            for (path, count), want in zip(written, ([n for n in names if n not in team_c], team_c)):
                with io.open(path, encoding='ascii', newline='') as f:
                    text = f.read()
                heads = [line.split(' ') for line in text.split('\n') if line.startswith('B ')]
                self.assertEqual([h[1] for h in heads], want)
                self.assertEqual(count, len(want))
                self.assertEqual({h[2] for h in heads}, {'1' if want is team_c else '0'})
                self.assertEqual({h[3] for h in heads}, {'0'})  # the conformance fallback: no strict kind
                self.assertEqual(text.count('\nEND\n'), len(want))

    def test_a_choice_as_the_c_record_has_it(self):
        flat = conformance_records.flat_choice
        self.assertEqual(flat(('team', [2, 4, 0, 1])), (1, 4, 2, 4, 0, 1, 0, 0) + (0,) * 10)
        self.assertEqual(flat(('team', (5, 4, 3, 2, 1, 0))), (1, 6, 5, 4, 3, 2, 1, 0) + (0,) * 10)
        self.assertEqual(flat(('slots', [(1, 0, 255, 0, 0), (3, 0, 0, 0, 0)])),
                         (2, 0, 0, 0, 0, 0, 0, 0, 1, 0, 255, 0, 0, 3, 0, 0, 0, 0))
        self.assertEqual(len(flat(('team', [0]))), conformance_records.FLAT_CHOICE_LEN)
        self.assertEqual(len(flat(('slots', [(0,) * 5, (0,) * 5]))), conformance_records.FLAT_CHOICE_LEN)
        for bad in (('team', []), ('team', list(range(7))), ('slots', [(1, 0, 255, 0, 0)]),
                    ('slots', [(1, 0, 255, 0)] * 2), ('slots', [(1, 0, 255, 0, 0)] * 3), ('pass', []), 'team', None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    flat(bad)

    def test_domain_samples_come_before_their_step_in_the_order_of_step_and_side(self):
        data, team_c = self.data(CLOSURE)
        team = [('team', [0, 1, 2, 3]), ('team', [0, 1, 2, 4])]
        slots = [('slots', [(1, 0, 255, 0, 0), (3, 0, 0, 0, 0)])]
        samples = [{'step': 1, 'side': 1, 'choices': slots}, {'step': 0, 'side': 1, 'choices': team[:1]},
                   {'step': 0, 'side': 0, 'choices': team}]  # not in order: the writer puts them in
        out = io.StringIO()
        conformance_records.write_battle(data, team_c, out, domain=samples)
        lines = out.getvalue().split('\n')
        self.assertEqual(lines[0].split(' ')[-1], '3')  # the B line says how many
        s_at = [i for i, line in enumerate(lines) if line.startswith('S ')]
        flat = conformance_records.flat_choice
        want_before_step0 = (['D 0 0 2', 'C ' + ' '.join(map(str, flat(team[0]))), 'C ' + ' '.join(map(str, flat(team[1]))),
                              'D 0 1 1', 'C ' + ' '.join(map(str, flat(team[0])))])
        self.assertEqual(lines[s_at[0] - len(want_before_step0):s_at[0]], want_before_step0)
        self.assertEqual(lines[s_at[1] - 2:s_at[1]], ['D 1 1 1', 'C ' + ' '.join(map(str, flat(slots[0])))])
        # Nothing else changed: without the samples the battle is the same text but for the B line.
        plain = self.write(data, team_c).split('\n')
        self.assertEqual([l for l in lines if l[:2] not in ('D ', 'C ')][1:], plain[1:])
        self.assertEqual(lines[0].split(' ')[:-1], plain[0].split(' ')[:-1])

    def test_domain_samples_the_format_cannot_hold_are_refused_and_nothing_is_written(self):
        data, team_c = self.data(CLOSURE)
        team = [('team', [0, 1, 2, 3]), ('team', [0, 1, 2, 4])]
        one_side = copy.deepcopy(data)
        one_side['steps'][0]['answered1'] = 0  # a battle in which side 1 does not answer step 0
        many = [('team', [a, b, c, d]) for a in range(6) for b in range(6) for c in range(6) for d in range(6)
                if len({a, b, c, d}) == 4]
        cases = {
            'a step beyond the battle': (data, [{'step': len(data['steps']), 'side': 0, 'choices': team}]),
            'a negative step': (data, [{'step': -1, 'side': 0, 'choices': team}]),
            'a side that is not 0 or 1': (data, [{'step': 0, 'side': 2, 'choices': team}]),
            'a side that is a bool': (data, [{'step': 0, 'side': True, 'choices': team}]),
            'two samples of one side and step': (data, [{'step': 0, 'side': 0, 'choices': team}] * 2),
            'a side that does not answer the step': (one_side, [{'step': 0, 'side': 1, 'choices': team}]),
            'a sample without choices': (data, [{'step': 0, 'side': 0, 'choices': []}]),
            'more choices than a domain holds': (data, [{'step': 0, 'side': 0, 'choices': many * 3}]),
            'choices in descending order': (data, [{'step': 0, 'side': 0, 'choices': team[::-1]}]),
            'the same choice twice': (data, [{'step': 0, 'side': 0, 'choices': team[:1] * 2}]),
            'a choice that is not one': (data, [{'step': 0, 'side': 0, 'choices': [('dance', [])]}]),
            'a command of four numbers': (data, [{'step': 1, 'side': 0, 'choices': [('slots', [(1, 0, 255, 0)] * 2)]}]),
            'a pick above 2**32 - 1': (data, [{'step': 0, 'side': 0, 'choices': [('team', [2 ** 32, 1, 2, 3])]}]),
        }
        self.assertGreater(len(many), 300)
        for what, (battle, samples) in cases.items():
            with self.subTest(what):
                out = io.StringIO()
                with self.assertRaises(ValueError):
                    conformance_records.write_battle(battle, team_c, out, domain=samples)
                self.assertEqual(out.getvalue(), '')
        # The control of the one that depends on the battle: the same sample is right for the side that answers.
        out = io.StringIO()
        conformance_records.write_battle(one_side, team_c, out, domain=[{'step': 0, 'side': 0, 'choices': team}])
        self.assertIn('\nD 0 0 2\n', out.getvalue())

    def test_the_data_kind_of_a_battle(self):
        """A strict kind is written after team_c; 0 is the conformance fallback; the kinds are those of duoforge.h."""
        kinds = conformance_records.data_kinds(ROOT)
        self.assertEqual({k: kinds[k] for k in ('CLOSURE', 'CLOSURE_DEV', 'TEAM_C', 'TEAM_C_DEV')},
                         {'CLOSURE': 2, 'CLOSURE_DEV': 3, 'TEAM_C': 4, 'TEAM_C_DEV': 5})
        for name, kind in ((CLOSURE, kinds['CLOSURE_DEV']), (TEAM_C, kinds['TEAM_C'])):
            data, team_c = self.data(name)
            out = io.StringIO()
            conformance_records.write_battle(data, team_c, out, kind=kind)
            self.assertEqual(out.getvalue().split('\n')[0].split(' ')[1:4], [name, '1' if team_c else '0', str(kind)])
            self.assertEqual(out.getvalue().split('\n', 1)[1], self.write(data, team_c).split('\n', 1)[1])  # nothing else changes
        data, team_c = self.data(CLOSURE)
        for bad in (-1, True, 2.0, 2 ** 32, '2', None):
            with self.subTest(kind=bad):
                out = io.StringIO()
                with self.assertRaises(ValueError):
                    conformance_records.write_battle(data, team_c, out, kind=bad)
                self.assertEqual(out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
