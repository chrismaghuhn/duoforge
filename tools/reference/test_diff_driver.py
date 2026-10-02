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

    def __init__(self, result=None, leaves_with=()):
        self.result = result
        self.leaves_with = list(leaves_with)
        self.requests = []
        self.closed = self.killed = 0

    def run(self, name, records):
        self.requests.append((name, records))
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

    def process(self, name, spec, text, answer=None, result=None):
        worker = FakeWorker(answer or (lambda s, f: text))
        runner = FakeRunner(result)
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
RECORDS = 'B x 0 1 1 0\nEND\n'


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

    def test_a_runner_that_dies_is_a_failure_of_the_tool_with_its_stderr(self):
        runner = self.stand_in("sys.stdin.readline()\nsys.stderr.write('duoforge_diff_runner: malformed input: line 3: boom\\n')\nsys.exit(2)")
        with self.assertRaises(driver.ToolError) as cm:
            runner.run('x', RECORDS)
        self.assertRegex(str(cm.exception), r'^the runner .*exited with status 2: duoforge_diff_runner: malformed input: line 3: boom$')

    def test_a_runner_that_does_not_answer_is_killed_after_the_timeout(self):
        runner = self.stand_in('sys.stdin.readline()\nimport time\ntime.sleep(60)', timeout=1)
        with self.assertRaises(driver.ToolError) as cm:
            runner.run('x', RECORDS)
        self.assertIn('no answer in 1 s, killed', str(cm.exception))
        self.assertIsNotNone(runner.proc.poll())

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
        with self.assertRaises(driver.ToolError) as cm:
            worker.record({}, 'a.json')
        self.assertRegex(str(cm.exception), r'exited with status 134: Error: out of memory$')


class Lanes(unittest.TestCase):
    """The threads: every battle once, the children closed or killed, the order of the output."""

    def lanes(self, names, workers, handle, make_worker=None, make_runner=None):
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
                                       make('runners', make_runner or (lambda: FakeRunner())), handle)
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
                want = ['B %s %d %d %d %d' % (name, team_c, data['member_count'], len(data['steps']), data['dropped_total'])]
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
                self.assertEqual(text.count('\nEND\n'), len(want))


if __name__ == '__main__':
    unittest.main()
