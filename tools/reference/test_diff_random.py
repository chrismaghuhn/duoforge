#!/usr/bin/env python3
"""The random mode of the driver (tools/reference/diff_random.py) without Node
and without a Showdown checkout.

usage: python3 tools/reference/test_diff_random.py

CTest runs it as duoforge.reference.diff_random, with DUOFORGE_DIFF_RUNNER set
to the runner it has built. A committed battle stands in for what the reference
plays and records (play answers the choices of its trace, record the trace cut
to the choices it is given), with faults made by index; the converter is real,
the runner is a fake or, with DUOFORGE_DIFF_RUNNER, the real one. Children that
die or hang are stand-in processes. The seed derivation, the bucket of each
step of the pipeline and what wins when two apply, the signatures, the cases,
the cut of a run into chunks (it must not change the result) and the machine
lock are tested.
"""
import contextlib
import copy
import gzip
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_driver as driver  # noqa: E402
import diff_random as rnd  # noqa: E402
import team_registry  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RUNNER = os.environ.get('DUOFORGE_DIFF_RUNNER')
VERSION = {'node': 'v0.0.0', 'pin': '0' * 40, 'harness': 14}
KINDS = conformance_records.data_kinds(ROOT)
PARAMS = rnd.Params(1, 24, rnd.DEFAULT_PAIRINGS, 300, 0.1, 0.5)
REAL = 'm5_real_aa_1'  # real teams of team A, ends: a PASS under CLOSURE
REAL_TEAM_C = 'c01_team_c_profile'  # six real members, ends: a PASS under TEAM_C
REAL_POOL = 'g5_uturn_e'  # a pool battle that ends (a Rocky Helmet faints the U-turn user): a PASS under POOL
DEV = 's3_struggle_end'  # sets without an ability, ends: needs CLOSURE_DEV

_tables = {}
_pause = {}


def setUpModule():
    """The tests never look at the real pause file of this machine (a measurement may have made it): the path that they
    run with is one that does not exist, and the tests that need the file make it there."""
    _pause['saved'] = os.environ.get('DUOFORGE_FUZZ_PAUSE')
    _pause['dir'] = tempfile.TemporaryDirectory()
    os.environ['DUOFORGE_FUZZ_PAUSE'] = os.path.join(_pause['dir'].name, 'duoforge-fuzz.pause')


def tearDownModule():
    if _pause['saved'] is None:
        os.environ.pop('DUOFORGE_FUZZ_PAUSE', None)
    else:
        os.environ['DUOFORGE_FUZZ_PAUSE'] = _pause['saved']
    _pause['dir'].cleanup()


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


# ------------------------------------------------------------ a committed battle as the reference

class World:
    """What the reference does, as one committed battle: play answers the choices of its trace, record answers its
    trace cut to the choices it is given. scenario(index) says what goes wrong for battle `index`: a dict with
    'steps' (a play that stops there, the battle not over), 'play_error', 'record_error' (exceptions),
    'mutate' (changes the trace: mutate(trace, is_prefix)), 'runner' (a function of (steps, is_prefix) that
    answers instead of the runner saying PASS), 'samples' (the domain samples of the play, see sample_of) and
    'request_changed' (how many samples the play dropped)."""

    def __init__(self, battle=REAL, scenario=None, seed=1):
        spec, text = driver.load_committed(ROOT, battle)
        self.spec = spec
        self.trace = json.loads(text)
        self.seed = seed
        self.scenario = scenario or (lambda index: {})

    def sample_of(self, step, side, extra=(), played=True):
        """A domain sample of the play: the text that was played at that step by that side (unless `played` is false)
        and the texts of `extra`, as accepted."""
        text = self.trace['steps'][step]['input'][('p1', 'p2')[side]]
        return {'step': step, 'side': side, 'accepted': ([text] if played else []) + list(extra)}

    def spec_for(self, index):
        spec = copy.deepcopy(self.spec)
        spec.pop('plan', None)
        spec.pop('choices', None)
        spec['name'] = 'fz_%d_%d' % (self.seed, index)
        return spec, 1000 + index, 'AA'


def index_of(name):
    m = re.match(r'fz_\d+_(\d+)(_prefix)?(\.json)?$', name)
    return int(m.group(1)), bool(m.group(2))


class WorldWorker:
    def __init__(self, world, version=VERSION):
        self.world = world
        self.reported = version
        self.closed = self.killed = 0
        self.failed = False
        self.plays = []
        self.lock = threading.Lock()

    def version(self):
        return dict(self.reported)

    def play(self, battle, policy):
        index = policy['seed'] - 1000
        with self.lock:
            self.plays.append((index, battle, policy))
        what = self.world.scenario(index)
        if 'play_error' in what:
            raise what['play_error']
        trace = self.world.trace
        steps = what.get('steps', len(trace['steps']))
        return {'choices': [s['input'] for s in trace['steps'][:steps]], 'ended': trace['steps'][steps - 1]['state']['ended'],
                'steps': steps,
                'domain': {'samples': copy.deepcopy(what.get('samples', [])), 'request_changed': what.get('request_changed', 0)}}

    def record(self, spec, spec_file):
        index, prefix = index_of(spec_file)
        what = self.world.scenario(index)
        if 'record_error' in what and not prefix:
            raise what['record_error']
        trace = copy.deepcopy(self.world.trace)
        trace['steps'] = trace['steps'][:len(spec['choices'])]
        if 'mutate' in what:
            what['mutate'](trace, prefix)
        return json.dumps(trace, indent=1) + '\n'

    def close(self):
        self.closed += 1
        return []

    def kill(self):
        self.killed += 1


class WorldRunner:
    role = 'runner'

    def __init__(self, world):
        self.world = world
        self.requests = []
        self.closed = self.killed = 0
        self.failed = False
        self.lock = threading.Lock()

    def run(self, name, records):
        with self.lock:
            self.requests.append((name, records))
        index, prefix = index_of(name)
        steps = int(records.split('\n', 1)[0].split(' ')[5])
        answer = self.world.scenario(index).get('runner')
        if answer is not None:
            return answer(steps, prefix)
        return driver.RunnerResult('PASS', 'CLOSURE', None, steps, '-', [])

    def close(self):
        self.closed += 1
        return []

    def kill(self):
        self.killed += 1


DIFFERENCE = 'side 0 member 0 hp 5, reference 6'
DIFFERENCE_LINE = '  fz_1_0 step %d: ' + DIFFERENCE


def diverges(step, text=DIFFERENCE, detail='differences: state 1, observation 0, events 0, battle_check DUOFORGE_OK'):
    """A runner answer: a DIVERGENCE at `step` whatever it is asked (a runner that is deterministic), with the one
    line of the comparator ("  <name> step <n>: <text>") that the runner prints for it."""
    def answer(steps, prefix):
        return driver.RunnerResult('DIVERGENCE', 'CLOSURE', step, steps, detail, ['  fz_1_0 step %d: %s' % (step, text)])
    return answer


def process(world, index=0, params=PARAMS, kinds=KINDS):
    """Battle `index` of the world through the pipeline: the Outcome and the fake worker and runner."""
    worker, runner = WorldWorker(world), WorldRunner(world)
    seconds = rnd.collections.defaultdict(float)
    outcome = rnd.process_random(index, params, worker, runner, tables, kinds, world.spec_for, seconds)
    return outcome, worker, runner


# ------------------------------------------------------------ what battle i is

class Derivation(unittest.TestCase):
    TEAMS = None

    @classmethod
    def setUpClass(cls):
        cls.TEAMS = rnd.read_teams(ROOT)

    def test_the_seed_of_a_battle_is_a_function_of_the_run_and_the_index(self):
        # Pinned: a change of the derivation changes every run that was made before.
        self.assertEqual((rnd.battle_seed(1, 0), rnd.battle_seed(1, 1), rnd.battle_seed(2, 0)),
                         (0x5e41ab087439611e, 0x29e49b199086d8d3, 0x64684c4f0fd784b4))
        seeds = {rnd.battle_seed(s, i) for s in range(20) for i in range(20)}
        self.assertEqual(len(seeds), 400)  # no two (run, index) share one

    def test_battle_zero_of_run_one(self):
        spec, policy_seed, pairing = rnd.derive(PARAMS, 0, self.TEAMS)
        self.assertEqual((spec['name'], pairing, policy_seed), ('fz_1_0', 'AB', 4051625597))
        self.assertEqual(spec['seed'], 'sodium,62066530bfa1767c54e98cc1abab9d7c81bac56616f990ec607d39f783ffaf1f')
        heads = [[s.split('\n')[0] for s in team.split('\n\n')] for team in spec['teams']]
        self.assertEqual(heads[0][:2], ['Rillaboom (M) @ Miracle Seed', 'Raichu (F) @ Raichunite Y'])
        self.assertEqual(heads[1][:2], ['Farigiraf (F) @ Sitrus Berry', 'Charizard (M) @ Charizardite Y'])

    def test_a_battle_does_not_depend_on_the_others_or_on_how_many_there_are(self):
        a = rnd.derive(PARAMS, 3, self.TEAMS)
        b = rnd.derive(PARAMS._replace(battles=5000), 3, self.TEAMS)
        self.assertEqual(a, b)
        # Nor does the reference seed or the policy seed depend on the pairing: only the teams do.
        other = rnd.derive(PARAMS._replace(pairings=('CA', 'BC', 'CC', 'AC')), 0, self.TEAMS)
        mine = rnd.derive(PARAMS, 0, self.TEAMS)
        self.assertEqual((other[0]['seed'], other[1]), (mine[0]['seed'], mine[1]))
        self.assertEqual(rnd.derive(PARAMS, 0, self.TEAMS), rnd.derive(PARAMS, 0, self.TEAMS))
        self.assertNotEqual(rnd.derive(PARAMS, 1, self.TEAMS)[0]['seed'], mine[0]['seed'])

    def test_the_spec(self):
        pairings = rnd.PAIRINGS
        params = PARAMS._replace(pairings=pairings)
        for index in range(2 * len(pairings)):
            spec, policy_seed, pairing = rnd.derive(params, index, self.TEAMS)
            with self.subTest(index=index):
                self.assertEqual(pairing, pairings[index % len(pairings)])
                want = ['name', 'purpose'] + (['data'] if 'C' in pairing else []) + ['format', 'seed', 'teams']
                self.assertEqual(list(spec), want)
                self.assertEqual(spec['name'], 'fz_1_%d' % index)
                self.assertEqual(spec.get('data'), 'team_c' if 'C' in pairing else None)
                self.assertRegex(spec['seed'], r'^sodium,[0-9a-f]{64}$')
                self.assertTrue(0 <= policy_seed < 2 ** 32)
                self.assertEqual(spec['format'], 'gen9championsvgc2026regmc')
                for side, letter in enumerate(pairing):  # the six sets of the team, in some order
                    self.assertEqual(sorted(spec['teams'][side].split('\n\n')), sorted(self.TEAMS[letter]))
                self.assertIn('random differential battle %d of run 1' % index, spec['purpose'].lower())
                self.assertIn('policy seed %d' % policy_seed, spec['purpose'])

    def test_the_teams_are_the_committed_ones(self):
        self.assertEqual({k: len(v) for k, v in self.TEAMS.items()}, {'A': 6, 'B': 6, 'C': 6})
        self.assertTrue(self.TEAMS['C'][0].startswith('Sneasler (M) @ White Herb'))
        with io.open(os.path.join(ROOT, 'tests', 'reference', 'teams', 'team_a.txt'), encoding='utf-8') as f:
            self.assertEqual('\n\n'.join(self.TEAMS['A']), f.read().strip())

    def test_the_prefix_of_a_spec(self):
        spec = World().spec_for(0)[0]
        spec['choices'] = [{'p1': 'a'}, {'p1': 'b'}, {'p1': 'c'}, {'p1': 'd'}]
        cut = rnd.prefix_spec(spec, 1)
        self.assertEqual((cut['name'], cut['choices']), ('fz_1_0_prefix', [{'p1': 'a'}, {'p1': 'b'}]))
        self.assertEqual({k: v for k, v in cut.items() if k not in ('name', 'choices')},
                         {k: v for k, v in spec.items() if k not in ('name', 'choices')})
        self.assertEqual(len(spec['choices']), 4)  # the original is as it was
        cut['choices'][0]['p1'] = 'changed'
        self.assertEqual(spec['choices'][0], {'p1': 'a'})  # and shares nothing with the copy
        self.assertEqual(rnd.prefix_spec(spec)['choices'], spec['choices'])  # no step: all of them
        self.assertEqual(rnd.prefix_spec(spec, 0)['choices'], [{'p1': 'a'}])


# ------------------------------------------------------------ the bucket of a battle

class Buckets(unittest.TestCase):
    def test_the_bucket_after_the_runner_says_its_verdict(self):
        for verdict, ended, want in (('PASS', True, 'PASS'), ('PASS', False, 'CAP'), ('DIVERGENCE', True, 'DIVERGENCE'),
                                     ('DIVERGENCE', False, 'DIVERGENCE'), ('UNSUPPORTED', False, 'UNSUPPORTED'),
                                     ('UNSUPPORTED', True, 'UNSUPPORTED')):
            self.assertEqual(rnd.runner_bucket(verdict, ended), want, (verdict, ended))

    def test_a_pass_of_a_battle_that_ended(self):
        outcome, worker, runner = process(World())
        r = outcome.record
        self.assertEqual(list(r), rnd.RECORD_KEYS)
        self.assertEqual((r['index'], r['name'], r['pairing'], r['bucket'], r['rule'], r['detail'], r['step'], r['context'],
                          r['ended'], r['reproduces'], r['messages']),
                         (0, 'fz_1_0', 'AA', 'PASS', None, None, None, 'CLOSURE', True, None, []))
        self.assertEqual(r['steps'], len(World().trace['steps']))
        self.assertEqual(len(outcome.spec['choices']), r['steps'])
        self.assertIsNotNone(outcome.trace_text)
        self.assertEqual(len(runner.requests), 1)  # no prefix for a PASS

    def test_what_the_play_is_asked(self):
        world = World()
        outcome, worker, runner = process(world, 5)
        (index, battle, policy), = worker.plays
        spec = world.spec_for(5)[0]
        self.assertEqual((index, battle), (5, {'format': spec['format'], 'seed': spec['seed'], 'teams': spec['teams']}))
        self.assertEqual(policy, {'seed': 1005, 'max_steps': 300, 'switch_weight': 0.1, 'mega_weight': 0.5, 'domain_rate': 0.0})
        # The rate of the run goes to the worker as it is.
        outcome, worker, runner = process(world, 6, params=PARAMS._replace(domain_rate=0.25))
        self.assertEqual(worker.plays[0][2]['domain_rate'], 0.25)

    def test_a_battle_that_did_not_end_is_a_cap(self):
        outcome, worker, runner = process(World(scenario=lambda i: {'steps': 6}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['steps'], r['ended'], r['step']), ('CAP', 6, False, None))
        self.assertIn('did not end within 6 steps', r['detail'])
        self.assertEqual(r['reproduces'], True)  # the prefix of a CAP is all of it: the same pipeline, the same CAP
        self.assertEqual([name for name, _ in runner.requests], ['fz_1_0', 'fz_1_0_prefix'])
        self.assertEqual(len(runner.requests[1][1].split('\nS ')) - 1, 6)

    def test_a_battle_that_did_not_end_is_a_cap_only_if_the_runner_passes_it(self):
        # CAP is what a PASS becomes when the battle did not end; a finding of the runner is never hidden by it.
        outcome, worker, runner = process(World(scenario=lambda i: {'steps': 6, 'runner': diverges(3)}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['steps'], r['ended'], r['reproduces']), ('DIVERGENCE', 3, 6, False, True))

        def unsupported(steps, prefix):
            return driver.RunnerResult('UNSUPPORTED', 'CLOSURE', 4, steps, 'step: DUOFORGE_E_UNSUPPORTED, tape 3 of 8', [])
        outcome, worker, runner = process(World(scenario=lambda i: {'steps': 6, 'runner': unsupported}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['ended'], r['reproduces']), ('UNSUPPORTED', 4, False, None))
        self.assertEqual(len(runner.requests), 1)  # an UNSUPPORTED has no prefix, at a step or not

    def test_a_divergence_is_reproduced_by_its_prefix(self):
        outcome, worker, runner = process(World(scenario=lambda i: {'runner': diverges(3)}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['ended'], r['reproduces']), ('DIVERGENCE', 3, True, True))
        self.assertEqual(r['messages'], [DIFFERENCE_LINE % 3])
        (_, _), (prefix_name, prefix_records) = runner.requests
        self.assertEqual(prefix_name, 'fz_1_0_prefix')
        self.assertEqual(len(prefix_records.split('\nS ')) - 1, 4)  # the choices up to and including step 3
        self.assertEqual(len(worker.plays), 1)  # the prefix is recorded again, not played again

    def test_a_divergence_that_its_prefix_does_not_show_is_not_reproduced(self):
        def flaky(steps, prefix):
            return driver.RunnerResult('PASS', 'CLOSURE', None, steps, '-', []) if prefix else diverges(3)(steps, prefix)
        outcome, worker, runner = process(World(scenario=lambda i: {'runner': flaky}))
        self.assertEqual((outcome.record['bucket'], outcome.record['reproduces']), ('DIVERGENCE', False))

    def test_a_divergence_at_another_step_of_the_prefix_is_not_reproduced_either(self):
        def moved(steps, prefix):
            return diverges(2 if prefix else 3)(steps, prefix)
        outcome, worker, runner = process(World(scenario=lambda i: {'runner': moved}))
        self.assertEqual((outcome.record['step'], outcome.record['reproduces']), (3, False))

    def test_an_unsupported_has_no_prefix(self):
        def unsupported(steps, prefix):
            return driver.RunnerResult('UNSUPPORTED', 'CLOSURE', None, steps, 'create: DUOFORGE_E_UNSUPPORTED (CLOSURE)', [])
        outcome, worker, runner = process(World(scenario=lambda i: {'runner': unsupported}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['detail'], r['reproduces']), ('UNSUPPORTED', 'create: DUOFORGE_E_UNSUPPORTED (CLOSURE)', None))
        self.assertEqual(len(runner.requests), 1)

    def test_the_converter_comes_before_the_runner(self):
        def inject(trace, prefix):
            trace['steps'][1]['log'].append('|foo|bar')
        outcome, worker, runner = process(World(scenario=lambda i: {'mutate': inject, 'runner': diverges(3)}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['rule'], r['detail'], r['step'], r['ended'], r['reproduces']),
                         ('ORACLE_GAP', 'protocol-line', 'foo', None, True, None))
        self.assertEqual(runner.requests, [])  # not asked: the runner's DIVERGENCE does not come into it

    def test_every_rule_of_the_converter_is_an_oracle_gap_with_its_rule_and_detail(self):
        """A rule that the converter gets later ('unknown-volatile' is coming) needs no change in the buckets."""
        for rule, detail in (('unknown-volatile', 'twoturnmove'), ('a-rule-that-does-not-exist-yet', None)):
            def refuse(name, spec, trace, tables, rule=rule, detail=detail):
                raise trace_to_c.ConversionError(rule, 'trace_to_c: refused', detail)
            with mock.patch.object(trace_to_c, 'convert_battle', refuse):
                outcome, _, runner = process(World())
            r = outcome.record
            self.assertEqual((r['bucket'], r['rule'], r['detail'], r['messages']),
                             ('ORACLE_GAP', rule, detail, ['trace_to_c: refused']), rule)
            self.assertEqual(runner.requests, [])
            self.assertEqual(rnd.signature(r), (rule, detail or ''))

    def test_untyped_errors_of_the_converter_are_oracle_gaps_here_too(self):
        def break_it(trace, prefix):
            trace['steps'][0]['log'] = None
        outcome, _, runner = process(World(scenario=lambda i: {'mutate': break_it}))
        self.assertEqual((outcome.record['bucket'], outcome.record['rule']), ('ORACLE_GAP', 'untyped:TypeError'))

    def test_a_play_that_fails_is_a_ref_error_before_anything_else(self):
        failure = driver.WorkerError('no accepted choice', 'Error: no accepted choice\n    at chooseFor (ps_play.js:1)')
        outcome, worker, runner = process(World(scenario=lambda i: {'play_error': failure, 'runner': diverges(3)}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['detail'], r['step'], r['steps'], r['ended'], r['reproduces']),
                         ('REF_ERROR', 'no accepted choice', None, None, None, None))
        self.assertEqual(r['messages'], ['Error: no accepted choice', '    at chooseFor (ps_play.js:1)'])
        self.assertEqual(runner.requests, [])
        self.assertIsNone(outcome.trace_text)
        self.assertEqual(sorted(outcome.play_request), ['battle', 'policy'])  # what is needed to play it again
        self.assertNotIn('choices', outcome.spec)

    def test_a_worker_that_dies_in_the_play_is_a_ref_error(self):
        died = driver.ChildFailure('the reference worker gave no answer', 'worker', 'died', 134, 'Error: heap')
        outcome, _, _ = process(World(scenario=lambda i: {'play_error': died}))
        self.assertEqual((outcome.record['bucket'], outcome.record['detail'], outcome.record['messages']),
                         ('REF_ERROR', 'worker died (exit 134)', ['Error: heap']))

    def test_choices_that_do_not_replay_are_a_ref_error(self):
        failure = driver.WorkerError('p1 choice rejected: "move 9": Can\'t move', 'Error: p1 choice rejected\n    at choose')
        outcome, _, runner = process(World(scenario=lambda i: {'record_error': failure}))
        r = outcome.record
        self.assertEqual((r['bucket'], r['detail']), ('REF_ERROR', 'the choices spec does not replay'))
        self.assertEqual(r['messages'][0], 'p1 choice rejected: "move 9": Can\'t move')  # what the worker said
        self.assertEqual(runner.requests, [])
        self.assertIn('choices', outcome.spec)  # the spec that did not replay is the case
        self.assertIsNone(outcome.trace_text)

    def test_a_replay_that_ends_otherwise_than_the_play_said_is_a_ref_error(self):
        world = World()
        worker, runner = WorldWorker(world), WorldRunner(world)
        real_play = worker.play
        worker.play = lambda battle, policy: dict(real_play(battle, policy), ended=False)  # the play says: not over
        outcome = rnd.process_random(0, PARAMS, worker, runner, tables, KINDS, world.spec_for, rnd.collections.defaultdict(float))
        r = outcome.record
        self.assertEqual((r['bucket'], r['detail'], r['ended']), ('REF_ERROR', 'the choices spec does not replay', True))
        self.assertIn('the play said ended False, the recording of its choices ended True', r['messages'][0])
        self.assertEqual(runner.requests, [])

    def test_a_worker_that_dies_recording_is_a_ref_error(self):
        timed_out = driver.ChildFailure('the reference worker gave no answer', 'worker', 'timed out', 1, '')
        outcome, _, _ = process(World(scenario=lambda i: {'record_error': timed_out}))
        self.assertEqual((outcome.record['bucket'], outcome.record['detail']), ('REF_ERROR', 'worker timed out'))

    def test_a_runner_that_dies_or_hangs_is_a_divergence_without_a_step(self):
        for failure, detail in ((driver.ChildFailure('the runner gave no answer', 'runner', 'died', 3, 'assertion failed'),
                                 'runner died (exit 3)'),
                                (driver.ChildFailure('the runner gave no answer', 'runner', 'timed out', 1, ''),
                                 'runner timed out')):
            def crash(steps, prefix, failure=failure):
                raise failure
            outcome, _, runner = process(World(scenario=lambda i: {'runner': crash}))
            r = outcome.record
            self.assertEqual((r['bucket'], r['detail'], r['step'], r['steps'], r['ended'], r['reproduces']),
                             ('DIVERGENCE', detail, None, None, True, None), detail)
            self.assertEqual(len(runner.requests), 1)  # no step to cut at: no prefix

    def test_the_runner_is_told_the_data_kind_and_has_no_fallback_to_take(self):
        outcome, _, runner = process(World())
        self.assertTrue(runner.requests[0][1].startswith('B fz_1_0 0 %d ' % KINDS['CLOSURE']), runner.requests[0][1][:40])
        outcome, _, runner = process(World(REAL_TEAM_C))
        self.assertTrue(runner.requests[0][1].startswith('B fz_1_0 1 %d ' % KINDS['TEAM_C']), runner.requests[0][1][:40])
        self.assertEqual(outcome.record['bucket'], 'PASS')

    def test_every_record_has_one_schema_and_one_bucket(self):
        worlds = [World(), World(scenario=lambda i: {'steps': 6}), World(scenario=lambda i: {'runner': diverges(2)})]
        for world in worlds:
            r = process(world)[0].record
            self.assertEqual(list(r), rnd.RECORD_KEYS)
            self.assertIn(r['bucket'], driver.RANDOM_BUCKETS)
            json.dumps(r)


# ------------------------------------------------------------ the signature

class Signatures(unittest.TestCase):
    def test_what_is_the_same_about_two_differences(self):
        self.assertEqual(rnd.numbers_away('side 0 member 3 hp 181, reference 182'), 'side # member # hp #, reference #')
        self.assertEqual(rnd.numbers_away('side 1 slot 0 offers 0x1f, reference 0xf'), 'side # slot # offers 0x#, reference 0x#')
        cases = (
            ('create: DUOFORGE_E_INVALID_ARGUMENT (CLOSURE)', [], ('create', 'DUOFORGE_E_INVALID_ARGUMENT (CLOSURE)')),
            ('create: DUOFORGE_E_UNSUPPORTED (CLOSURE), DUOFORGE_E_UNSUPPORTED (CLOSURE_DEV)', [],
             ('create', 'DUOFORGE_E_UNSUPPORTED (CLOSURE), DUOFORGE_E_UNSUPPORTED (CLOSURE_DEV)')),
            ('step: DUOFORGE_E_INVARIANT, tape 7 of 7', [], ('step', 'DUOFORGE_E_INVARIANT')),
            ('step: DUOFORGE_E_UNSUPPORTED, tape n/a of 3', [], ('step', 'DUOFORGE_E_UNSUPPORTED')),
            ('step: the tape is not consumed exactly, tape 3 of 5', [], ('tape', 'not consumed exactly')),
            ('differences: state 1, observation 0, events 0, battle_check DUOFORGE_OK',
             ['  fz_1_9 step 4: side 0 member 2 hp 181, reference 182'], ('state', 'side # member # hp #, reference #')),
            ('differences: state 0, observation 2, events 0, battle_check DUOFORGE_OK',
             ['  fz_1_9 step 4: player 0 sees side 0 position 1 differently', '  fz_1_9 step 4: player 1 sees side 0 position 1 differently'],
             ('observation', 'player # sees side # position # differently')),
            ('differences: state 0, observation 0, events 0, battle_check DUOFORGE_E_INVARIANT',
             ['  fz_1_9 step 4: duoforge_battle_check: DUOFORGE_E_INVARIANT'], ('battle_check', 'DUOFORGE_E_INVARIANT')),
            ('something else 12', [], ('runner', 'something else #')),
        )
        for detail, messages, want in cases:
            self.assertEqual(rnd.runner_signature(detail, messages), want, detail)

    def test_the_events_signature_names_the_fields_that_differ(self):
        ref = '    reference kind 2 pos 0 other 255 cause 0 id 0 id2 0 hp 182/181 kind 1 flag 0 status 0 detail 0 amount 0 flags 0'
        eng = '    engine    kind 2 pos 0 other 255 cause 0 id 0 id2 0 hp 181/181 kind 1 flag 0 status 0 detail 0 amount 0 flags 0'
        self.assertEqual(rnd.event_signature([ref, eng]), 'reference kind 2 differs in hp')
        other = eng.replace('hp 181/181', 'hp 182/181').replace('kind 2 pos 0', 'kind 5 pos 1').replace('id 0 id2', 'id 7 id2')
        self.assertEqual(rnd.event_signature([ref, other]), 'reference kind 2 differs in kind, pos, id')
        self.assertEqual(rnd.event_signature([ref.replace('kind 1 flag', 'kind 2 flag'), eng.replace('hp 181/181', 'hp 182/181')]),
                         'reference kind 2 differs in kind2')  # the second "kind" is the HP kind
        self.assertEqual(rnd.event_signature([ref]), 'reference kind 2, engine has no event')
        self.assertEqual(rnd.event_signature([eng]), 'engine kind 2, reference has no event')
        self.assertIsNone(rnd.event_signature(['    something']))
        messages = ['  fz_1_9 step 4: player 0 event 3 differs', ref, eng]
        self.assertEqual(rnd.runner_signature('differences: state 0, observation 0, events 1, battle_check DUOFORGE_OK', messages),
                         ('events', 'reference kind 2 differs in hp'))
        # Lines that are not what the comparator prints: the first message, without its numbers.
        self.assertEqual(rnd.runner_signature('differences: state 0, observation 0, events 1, battle_check DUOFORGE_OK',
                                              ['  fz_1_9 step 4: player 0 event 3 differs', '    odd']),
                         ('events', 'player # event # differs'))

    def test_the_signature_of_a_record(self):
        def record(bucket, rule=None, detail=None, messages=()):
            return {'bucket': bucket, 'rule': rule, 'detail': detail, 'messages': list(messages)}
        self.assertEqual(rnd.signature(record('ORACLE_GAP', 'tie-context', 'event:Accuracy')), ('tie-context', 'event:Accuracy'))
        self.assertEqual(rnd.signature(record('ORACLE_GAP', 'protocol-line')), ('protocol-line', ''))
        self.assertEqual(rnd.signature(record('REF_ERROR', None, 'no accepted choice')), ('', 'no accepted choice'))
        self.assertEqual(rnd.signature(record('CAP', None, 'the battle did not end within 6 steps')),
                         ('', 'the battle did not end within 6 steps'))
        self.assertEqual(rnd.signature(record('DIVERGENCE', None, 'runner died (exit 3)')), ('runner-failed', 'died (exit 3)'))
        self.assertEqual(rnd.signature(record('DIVERGENCE', None, 'runner timed out')), ('runner-failed', 'timed out'))
        self.assertEqual(rnd.signature(record('UNSUPPORTED', None, 'step: DUOFORGE_E_UNSUPPORTED, tape 1 of 4')),
                         ('step', 'DUOFORGE_E_UNSUPPORTED'))
        self.assertEqual(rnd.signature(record('DIVERGENCE', None, 'differences: state 1, observation 0, events 0, battle_check DUOFORGE_OK',
                                              ['  fz_1_9 step 4: turn 5, reference 6'])), ('state', 'turn #, reference #'))


# ------------------------------------------------------------ what is kept of a battle that is not a PASS

class Cases(unittest.TestCase):
    def outcome_with_divergence(self):
        outcome, _, _ = process(World(scenario=lambda i: {'runner': diverges(1)}))
        return outcome

    def test_the_files_of_a_divergence(self):
        outcome = self.outcome_with_divergence()
        files = rnd.case_files(outcome)
        self.assertEqual(sorted(files), ['messages.txt', 'prefix_result.json', 'prefix_spec.json', 'spec.json', 'step.json',
                                         'trace.json.gz'])
        spec = json.loads(files['spec.json'].decode('utf-8'))
        self.assertEqual((spec['name'], len(spec['choices'])), ('fz_1_0', len(World().trace['steps'])))
        self.assertEqual(list(spec)[:2], ['name', 'purpose'])  # a spec as a committed one: promote it by copying
        self.assertEqual(gzip.decompress(files['trace.json.gz']).decode('utf-8'), outcome.trace_text)
        lines = files['messages.txt'].decode('utf-8').split('\n')
        self.assertEqual(lines[0], 'DIVERGENCE | - | differences: state 1, observation 0, events 0, battle_check DUOFORGE_OK')
        self.assertEqual(lines[1], DIFFERENCE_LINE % 1)
        self.assertEqual(json.loads(files['prefix_result.json'].decode('utf-8')),
                         {'bucket': 'DIVERGENCE', 'step': 1, 'choices': 2, 'reproduces': True})
        cut = json.loads(files['prefix_spec.json'].decode('utf-8'))
        self.assertEqual((cut['name'], cut['choices']), ('fz_1_0_prefix', spec['choices'][:2]))

    def test_the_step_of_a_divergence_with_a_verdict_for_every_draw(self):
        trace = World().trace
        k = next(i for i, s in enumerate(trace['steps']) if any(d['site'] == 'SPEED_TIE' for d in s['draws']) and i > 0)
        report = rnd.step_report(trace, k)
        self.assertEqual((report['step'], report['input'], report['log']), (k, trace['steps'][k]['input'], trace['steps'][k]['log']))
        self.assertEqual([d['draw'] for d in report['draws']], trace['steps'][k]['draws'])
        verdicts = [d['verdict'] for d in report['draws']]
        self.assertTrue(all(v == 'kept' or v.startswith(('dropped: ', 'kept: ')) for v in verdicts), verdicts)
        # Every draw has the verdict the converter gives it: kept ones are the tape of its data.
        spec, text = driver.load_committed(ROOT, REAL)
        data = trace_to_c.convert_battle(REAL, spec, trace, tables(False))
        self.assertEqual(sum(v == 'kept' or v.startswith('kept: ') for v in verdicts), len(data['steps'][k]['tape']))
        self.assertEqual(sum(v.startswith('dropped: ') for v in verdicts), data['steps'][k]['dropped'])
        self.assertEqual(rnd.step_report(trace, 0)['step'], 0)  # step 0 reads the start state

    def test_a_draw_that_the_converter_refuses_has_the_error_for_its_verdict(self):
        trace = copy.deepcopy(World().trace)
        trace['steps'][1]['draws'][0] = {'site': 'UNKNOWN', 'context': 'x', 'lo': 0, 'hi': 2, 'value': 1}
        report = rnd.step_report(trace, 1)
        self.assertEqual(report['draws'][0]['verdict'], 'error: unclassified-draw: trace_to_c: unclassified draw')

    def test_the_files_are_the_same_every_time(self):
        a = rnd.case_files(self.outcome_with_divergence())
        b = rnd.case_files(self.outcome_with_divergence())
        self.assertEqual(a, b)  # also the gzip: no name, no time

    def test_the_files_of_other_buckets(self):
        outcome, _, _ = process(World(scenario=lambda i: {'steps': 6}))  # a CAP: all of it is the prefix
        files = rnd.case_files(outcome)
        self.assertEqual(sorted(files), ['messages.txt', 'prefix_result.json', 'prefix_spec.json', 'spec.json', 'trace.json.gz'])
        self.assertEqual(json.loads(files['prefix_result.json'].decode('utf-8')),
                         {'bucket': 'CAP', 'step': None, 'choices': 6, 'reproduces': True})
        failure = driver.WorkerError('no accepted choice', 'Error: no accepted choice')
        outcome, _, _ = process(World(scenario=lambda i: {'play_error': failure}))
        files = rnd.case_files(outcome)
        self.assertEqual(sorted(files), ['messages.txt', 'play_request.json', 'spec.json'])
        self.assertEqual(sorted(json.loads(files['play_request.json'].decode('utf-8'))), ['battle', 'policy'])
        self.assertNotIn('choices', json.loads(files['spec.json'].decode('utf-8')))
        def inject(trace, prefix):
            trace['steps'][1]['log'].append('|foo|bar')
        outcome, _, _ = process(World(scenario=lambda i: {'mutate': inject}))
        files = rnd.case_files(outcome)
        # The trace the converter refused, and the shortest prefix of the battle that it refuses (the step with the
        # line it does not know and none after it): the cut that a fix of the converter is promoted from.
        self.assertEqual(sorted(files), ['messages.txt', 'prefix_result.json', 'prefix_spec.json', 'spec.json',
                                         'trace.json.gz'])
        self.assertEqual(files['messages.txt'].decode('utf-8').split('\n')[:2],
                         ['ORACLE_GAP | protocol-line | foo', "trace_to_c: unknown protocol line '|foo|bar'"])
        self.assertEqual(json.loads(files['prefix_result.json'].decode('utf-8')),
                         {'bucket': 'ORACLE_GAP', 'step': 1, 'choices': 2, 'reproduces': True})
        cut = json.loads(files['prefix_spec.json'].decode('utf-8'))
        self.assertEqual((cut['name'], cut['choices']), ('fz_1_0_prefix', json.loads(files['spec.json'].decode('utf-8'))['choices'][:2]))

    def test_a_case_is_written_to_a_directory_of_its_name(self):
        outcome = self.outcome_with_divergence()
        with tempfile.TemporaryDirectory() as tmp:
            rnd.write_case(tmp, 'fz_1_0', rnd.case_files(outcome))
            self.assertEqual(sorted(os.listdir(os.path.join(tmp, 'cases', 'fz_1_0'))), sorted(rnd.case_files(outcome)))
            self.assertEqual([f for f in os.listdir(os.path.join(tmp, 'cases', 'fz_1_0')) if f.endswith('.tmp')], [])


# ------------------------------------------------------------ the domain of a request

ALL_TEAM_TEXTS = ['team ' + ''.join(str(i + 1) for i in picks) for picks in itertools.permutations(range(6), 4)]


class Domain(unittest.TestCase):
    """What Showdown accepts for a request, as the driver makes it a set for the records."""

    def test_what_was_played_is_the_choice_that_the_converter_made_of_it(self):
        """The driver makes its own state, roster and mid-turn flag for trace_to_c.convert_choice (the converter builds
        them inline in convert_battle): for what was played they must give what convert_battle put in its data."""
        names = driver.spec_names(ROOT)
        names = sorted(set(names[::4]) | {n for n in (DEV, 's12_parting_shot', 's13_replacement_before_entry', 'c11_follow_me',
                                                      REAL, REAL_TEAM_C) if n in names})
        self.assertGreater(len(names), 30)
        compared = {'team': 0, 'slots': 0, 'mid_turn': 0}
        for name in names:
            spec, trace = trace_to_c.load_battle(ROOT, name)
            team_c = trace_to_c.spec_is_team_c(name, spec)
            data = trace_to_c.convert_battle(name, spec, trace, tables(team_c))
            roster_of = rnd.roster_tables(trace)
            for k, step in enumerate(trace['steps']):
                for side, sid in enumerate(('p1', 'p2')):
                    if sid not in step['input']:
                        continue
                    mid_turn = rnd.mid_turn_before(trace, k)
                    got = rnd.canonical_choice(step['input'][sid], side, rnd.state_before(trace, k), roster_of, mid_turn)
                    if data['steps'][k]['team']:
                        picks = tuple(data['steps'][k]['picks'][side])
                        want = ('team', picks[:len(got[1])])
                        self.assertEqual(picks[len(got[1]):], (0,) * (6 - len(got[1])), (name, k))
                    else:
                        want = ('slots', tuple(tuple(c) for c in data['steps'][k]['cmds'][side]))
                    self.assertEqual(got, want, (name, k, side, step['input'][sid]))
                    compared[got[0]] += 1
                    compared['mid_turn'] += 1 if mid_turn else 0
        self.assertTrue(all(compared.values()), compared)  # team preview, turns and mid-turn requests were all seen

    def test_the_state_before_a_step_and_the_mid_turn_flag(self):
        trace = World().trace
        self.assertIs(rnd.state_before(trace, 0), trace['start']['state'])
        self.assertIs(rnd.state_before(trace, 3), trace['steps'][2]['state'])
        self.assertFalse(rnd.mid_turn_before(trace, 0))
        has_upkeep = lambda k: any(line.startswith('|upkeep') for line in trace['steps'][k]['log'])
        self.assertEqual(rnd.mid_turn_before(trace, 1), not has_upkeep(0))
        fake = {'steps': [{'log': ['|move|x', '|upkeep']}, {'log': ['|move|x']}, {'log': []}]}
        self.assertEqual([rnd.mid_turn_before(fake, k) for k in range(3)], [False, False, True])

    def test_the_roster_has_the_aliases_of_the_converter(self):
        state = {'sides': [{'pokemon': [{'species': 'Indeedee-F', 'set_species': 'Indeedee-F'}, {'species': 'Milotic'}]},
                           {'pokemon': [{'species': 'Milotic'}]}]}
        roster_of = rnd.roster_tables({'start': {'state': state}})
        self.assertEqual(roster_of, [{'Indeedee-F': 0, 'Indeedee': 0, 'Milotic': 1}, {'Milotic': 0}])

    def test_a_sample_becomes_a_set_in_the_order_of_the_records(self):
        world = World()
        trace = world.trace
        played = trace['steps'][0]['input']['p1']
        others = [t for t in ('team 6543', 'team 1234', 'team 2143') if t != played]
        sets = rnd.domain_choices(trace, [world.sample_of(1, 1), {'step': 0, 'side': 0, 'accepted': [others[1], played, others[0]]}])
        self.assertEqual([(s['step'], s['side']) for s in sets], [(0, 0), (1, 1)])  # by step and side
        team = sets[0]
        flats = [conformance_records.flat_choice(c) for c in team['choices']]
        self.assertEqual(flats, sorted(flats))
        self.assertEqual(len(team['choices']), 3)
        self.assertEqual(sorted(team['rendered']), sorted([others[1], played, others[0]]))
        for text, rendered in team['rendered'].items():
            self.assertEqual(rendered, 'team ' + ' '.join(str(int(c) - 1) for c in text[len('team '):]))
        self.assertEqual(team['accepted'], [others[1], played, others[0]])  # the texts as Showdown listed them
        self.assertEqual(rnd.domain_choices(trace, []), [])

    def test_what_was_played_must_be_among_what_showdown_accepted(self):
        world = World()
        played = world.trace['steps'][0]['input']['p1']
        other = 'team 6543' if played != 'team 6543' else 'team 1234'
        with self.assertRaises(rnd.DomainError) as cm:
            rnd.domain_choices(world.trace, [{'step': 0, 'side': 0, 'accepted': [other]}])
        self.assertIn('step 0 side 0: what was played (%r) is not among the 1 choices' % played, str(cm.exception))

    def test_a_sample_must_be_of_a_side_and_a_step_of_the_recording(self):
        world = World('s13_replacement_before_entry')
        one = next(k for k, step in enumerate(world.trace['steps']) if len(step['input']) == 1)  # only one side answers
        missing = 1 if 'p1' in world.trace['steps'][one]['input'] else 0
        with self.assertRaises(rnd.DomainError) as cm:
            rnd.domain_choices(world.trace, [{'step': one, 'side': missing, 'accepted': ['pass']}])
        self.assertIn('the side did not answer a step of the recording', str(cm.exception))
        with self.assertRaises(rnd.DomainError):
            rnd.domain_choices(world.trace, [{'step': len(world.trace['steps']), 'side': 0, 'accepted': ['pass']}])

    def test_the_refusals_of_the_converter_pass_through(self):
        world = World()
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            rnd.domain_choices(world.trace, [{'step': 1, 'side': 0, 'accepted': ['dance 1, dance 1']}])
        self.assertEqual((cm.exception.rule, cm.exception.detail), ('choice-kind', 'dance'))

    def test_a_choice_as_the_runner_prints_it(self):
        # The same strings as the unit test of the runner (tests/test_runner_domain.c): the two sides agree on the text.
        self.assertEqual(rnd.format_choice(('team', (2, 4, 0, 1))), 'team 2 4 0 1')
        self.assertEqual(rnd.format_choice(('slots', ((1, 1, 2, 1, 0), (2, 0, 0, 0, 3)))), 'slots move 1 -> 2 mega, switch 3')
        self.assertEqual(rnd.format_choice(('slots', ((1, 4, 255, 0, 0), (3, 0, 0, 0, 0)))), 'slots move 4 -> none, pass')
        self.assertEqual(rnd.format_choice(('slots', ((0, 0, 0, 0, 0), (1, 0, 0, 0, 0)))), 'slots none, move 0 -> 0')

    def test_the_shape_of_a_printed_choice(self):
        shapes = {'team 2 4 0 1': 'team', 'slots move 1 -> 2 mega, switch 3': 'move+mega+target/switch',
                  'slots move 4 -> none, pass': 'move/pass', 'slots none, move 0 -> 0': 'none/move+target',
                  'slots move 0 -> none mega, move 3 -> 1': 'move+mega/move+target'}
        for text, shape in shapes.items():
            self.assertEqual(rnd.choice_shape(text), shape, text)

    # ---- through the pipeline, with a fake reference and a fake runner

    def test_the_samples_are_written_before_their_steps_and_counted(self):
        world = World()
        samples = [world.sample_of(0, 0, ['team 6543', 'team 1234']), world.sample_of(0, 1), world.sample_of(1, 0),
                   world.sample_of(1, 1)]
        world.scenario = lambda i: {'samples': samples, 'request_changed': 2}
        outcome, worker, runner = process(world)
        r = outcome.record
        self.assertEqual((r['bucket'], r['domain']), ('PASS', {'samples': 4, 'request_changed': 2}))
        (_, records), = runner.requests
        lines = records.split('\n')
        n0 = len(set(samples[0]['accepted']))
        self.assertEqual([l for l in lines if l.startswith('D ')], ['D 0 0 %d' % n0, 'D 0 1 1', 'D 1 0 1', 'D 1 1 1'])
        self.assertEqual(lines[0].split(' ')[-1], '4')  # the B line says how many
        s_at = [i for i, l in enumerate(lines) if l.startswith('S ')]
        d_at = [i for i, l in enumerate(lines) if l.startswith('D ')]
        self.assertTrue(d_at[1] < s_at[0] < d_at[2] < d_at[3] < s_at[1])
        self.assertEqual(len(outcome.domain), 4)

    def test_no_samples_is_a_battle_of_the_same_records_as_before(self):
        outcome, _, runner = process(World())
        self.assertEqual(outcome.record['domain'], {'samples': 0, 'request_changed': 0})
        (_, records), = runner.requests
        self.assertEqual(records.split('\n')[0].split(' ')[-1], '0')
        self.assertNotIn('\nD ', records)

    def test_a_play_that_failed_has_no_domain_counts(self):
        failure = driver.WorkerError('no accepted choice', 'Error: no accepted choice')
        outcome, _, _ = process(World(scenario=lambda i: {'play_error': failure}))
        self.assertIsNone(outcome.record['domain'])

    def test_a_prefix_gets_the_samples_of_its_steps_only(self):
        world = World()
        samples = [world.sample_of(k, s) for k in range(5) for s in (0, 1)]
        world.scenario = lambda i: {'samples': samples, 'runner': diverges(2)}
        outcome, worker, runner = process(world)
        (_, first), (prefix_name, prefix) = runner.requests
        self.assertEqual((prefix_name, first.count('\nD '), prefix.count('\nD ')), ('fz_1_0_prefix', 10, 6))  # steps 0, 1 and 2
        self.assertEqual((first.split('\n')[0].split(' ')[-1], prefix.split('\n')[0].split(' ')[-1]), ('10', '6'))
        self.assertEqual(outcome.record['reproduces'], True)

    def test_a_sample_that_disagrees_with_the_recording_is_a_ref_error(self):
        world = World()
        played = world.trace['steps'][0]['input']['p1']
        other = 'team 6543' if played != 'team 6543' else 'team 1234'
        world.scenario = lambda i: {'samples': [{'step': 0, 'side': 0, 'accepted': [other]}]}
        outcome, _, runner = process(world)
        r = outcome.record
        self.assertEqual((r['bucket'], r['detail'], r['domain']), ('REF_ERROR', 'a domain sample disagrees with the recording',
                                                                   {'samples': 1, 'request_changed': 0}))
        self.assertIn('what was played', r['messages'][0])
        self.assertEqual(runner.requests, [])
        self.assertIsNotNone(outcome.trace_text)  # the recording is in the case

    def test_a_text_the_converter_refuses_is_an_oracle_gap(self):
        world = World()
        world.scenario = lambda i: {'samples': [{'step': 1, 'side': 0, 'accepted': ['dance 1, dance 1']}]}
        outcome, _, runner = process(world)
        r = outcome.record
        self.assertEqual((r['bucket'], r['rule'], r['detail']), ('ORACLE_GAP', 'choice-kind', 'dance'))
        self.assertEqual(runner.requests, [])

    def difference(self, engine_only, reference_only, step=1, side=0):
        lines = ['  fz_1_0 step %d: domain side %d engine-only: %s' % (step, side, t) for t in engine_only]
        lines += ['  fz_1_0 step %d: domain side %d reference-only: %s' % (step, side, t) for t in reference_only]
        detail = 'domain: engine-only %d, reference-only %d (step %d side %d)' % (len(engine_only) + 4, len(reference_only), step, side)
        return lambda steps, prefix: driver.RunnerResult('DIVERGENCE', 'CLOSURE', step, steps, detail, lines)

    def test_a_difference_of_the_domain_is_a_divergence_with_a_signature_and_a_case(self):
        world = World()
        world.scenario = lambda i: {'samples': [world.sample_of(1, 0, ['move 1 1, move 1 2']), world.sample_of(1, 1)],
                                    'runner': self.difference(['slots move 0 -> 2, pass', 'slots move 1 -> none mega, switch 3'],
                                                              ['team 2 4 0 1'])}
        outcome, _, runner = process(world)
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['reproduces'], r['domain']),
                         ('DIVERGENCE', 1, True, {'samples': 2, 'request_changed': 0}))
        self.assertEqual(rnd.signature(r), ('domain', 'engine-only move+mega/switch, move+target/pass, reference-only team'))
        files = rnd.case_files(outcome)
        self.assertIn('domain.json', files)
        self.assertIn('step.json', files)
        domain = json.loads(files['domain.json'].decode('utf-8'))
        self.assertEqual((domain['step'], domain['side']), (1, 0))
        self.assertEqual([a['text'] for a in domain['accepted']], outcome.domain[0]['accepted'])
        for a in domain['accepted']:
            self.assertTrue(a['choice'].startswith('slots '), a)  # each text with its choice as the runner prints it
        self.assertEqual(domain['accepted'][0]['choice'],
                         rnd.format_choice(rnd.canonical_choice(domain['accepted'][0]['text'], 0, rnd.state_before(world.trace, 1),
                                                                rnd.roster_tables(world.trace), rnd.mid_turn_before(world.trace, 1))))

    def test_the_failure_of_a_candidates_call_is_a_signature_too(self):
        detail = 'domain: candidates: DUOFORGE_E_UNSUPPORTED (step 3 side 1)'
        self.assertEqual(rnd.runner_signature(detail, ['  x step 3: domain side 1: the engine\'s candidates: DUOFORGE_E_UNSUPPORTED']),
                         ('domain', 'candidates: DUOFORGE_E_UNSUPPORTED'))
        self.assertEqual(rnd.runner_signature('domain: engine-only 2, reference-only 0 (step 3 side 1)', []),
                         ('domain', 'engine-only -, reference-only -'))  # no example in the messages: nothing to say of them

    def test_a_case_of_another_difference_has_no_domain_file(self):
        outcome, _, _ = process(World(scenario=lambda i: {'runner': diverges(2)}))
        self.assertNotIn('domain.json', rnd.case_files(outcome))

    def test_the_summary_counts_the_samples_and_the_rate_is_part_of_the_identity_of_a_run(self):
        identity = rnd.identity_of(PARAMS._replace(domain_rate=0.2), VERSION, 'h', '1', 'f' * 64)
        self.assertEqual((identity['domain_rate'], identity['policy']), (0.2, {'max_steps': 300, 'switch_weight': 0.1, 'mega_weight': 0.5}))
        records = []
        kinds = (('PASS', {'samples': 5, 'request_changed': 1}), ('PASS', None), ('CAP', {'samples': 2, 'request_changed': 0}),
                 ('DIVERGENCE', {'samples': 4, 'request_changed': 2}), ('ORACLE_GAP', {'samples': 3, 'request_changed': 0}))
        for i, (bucket, domain) in enumerate(kinds):
            records.append({'index': i, 'name': 'fz_1_%d' % i, 'pairing': 'AA', 'bucket': bucket, 'rule': None, 'detail': None,
                            'step': None, 'steps': 4, 'context': 'CLOSURE', 'ended': True, 'reproduces': None,
                            'domain': domain, 'messages': []})
        summary = rnd.summarize(records, identity)
        # Sampled: all of them; agreed: those of the battles that ran to the end (PASS, CAP); dropped: all of those.
        self.assertEqual(summary['domain'], {'rate': 0.2, 'samples': 14, 'agreed': 7, 'request_changed': 3})


# ------------------------------------------------------------ a run, the summary, and its cut into chunks

def scenario_of(index):
    """Every kind of bucket by index: a world for the chunk tests."""
    def inject(trace, prefix):
        trace['steps'][1]['log'].append('|foo|bar')
    kind = index % 6
    if kind == 1:
        return {'runner': diverges(2)}
    if kind == 2:
        return {'mutate': inject}
    if kind == 3:
        return {'steps': 5}
    if kind == 4:
        return {'play_error': driver.WorkerError('no accepted choice', 'Error: no accepted choice')}
    if kind == 5:
        return {'runner': lambda steps, prefix: driver.RunnerResult(
            'UNSUPPORTED', 'CLOSURE', 4, steps, 'step: DUOFORGE_E_UNSUPPORTED, tape 3 of 8', [])}
    return {}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now

    def advance(self, seconds):
        with self.lock:
            self.now += seconds


def run_chunk_of(world, outdir, start, minutes, workers, clock, seconds_per_battle=10):
    """run_chunk over the world; each battle that is played makes the clock go on."""
    make_worker = lambda: ClockWorker(WorldWorker(world), clock, seconds_per_battle)
    return rnd.run_chunk(PARAMS, outdir, start, minutes, make_worker, lambda: WorldRunner(world), tables, KINDS,
                         world.spec_for, workers, clock=clock, out=io.StringIO())


class ClockWorker:
    """A worker whose play takes `seconds` on the clock."""

    def __init__(self, inner, clock, seconds):
        self.inner, self.clock, self.seconds = inner, clock, seconds
        self.failed = False

    def play(self, battle, policy):
        self.clock.advance(self.seconds)
        return self.inner.play(battle, policy)

    def __getattr__(self, name):
        return getattr(self.inner, name)


IDENTITY = rnd.identity_of(PARAMS, VERSION, 'abc123', '1.2.3', 'f' * 64)


def read_tree(path, skip=()):
    """{relative path: bytes} of every file under `path`, but the names in `skip`."""
    out = {}
    for base_dir, _, files in os.walk(path):
        for fname in files:
            full = os.path.join(base_dir, fname)
            rel = os.path.relpath(full, path).replace(os.sep, '/')
            if rel.split('/')[0] in skip or fname in skip:
                continue
            with io.open(full, 'rb') as f:
                out[rel] = f.read()
    return out


class Run(unittest.TestCase):
    def finished(self, tmp, name, world=None, **kwargs):
        """A complete run in tmp/name in one chunk."""
        outdir = os.path.join(tmp, name)
        world = world or World(scenario=scenario_of)
        rnd.check_identity(outdir, IDENTITY)
        run_chunk_of(world, outdir, 0, None, kwargs.get('workers', 1), FakeClock())
        rnd.finalize(outdir, PARAMS.battles)
        return outdir

    def test_every_bucket_and_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = self.finished(tmp, 'a')
            with io.open(os.path.join(outdir, 'battles.jsonl'), encoding='ascii') as f:
                records = [json.loads(line) for line in f]
            with io.open(os.path.join(outdir, 'summary.json'), encoding='ascii') as f:
                summary = json.load(f)
            self.assertEqual([r['index'] for r in records], list(range(24)))  # in index order
            self.assertEqual([r['bucket'] for r in records[:6]], ['PASS', 'DIVERGENCE', 'ORACLE_GAP', 'CAP', 'REF_ERROR', 'UNSUPPORTED'])
            self.assertEqual(summary['buckets'], {'PASS': 4, 'DIVERGENCE': 4, 'UNSUPPORTED': 4, 'ORACLE_GAP': 4, 'REF_ERROR': 4, 'CAP': 4})
            self.assertEqual([(s['bucket'], s['rule'], s['detail'], s['count'], s['first'], s['case']) for s in summary['signatures']], [
                ('DIVERGENCE', 'state', 'side # member # hp #, reference #', 4, 1, 'fz_1_1'),
                ('UNSUPPORTED', 'step', 'DUOFORGE_E_UNSUPPORTED', 4, 5, 'fz_1_5'),
                ('ORACLE_GAP', 'protocol-line', 'foo', 4, 2, 'fz_1_2'),
                ('REF_ERROR', None, 'no accepted choice', 4, 4, 'fz_1_4'),
                ('CAP', None, 'the battle did not end within 5 steps', 4, 3, 'fz_1_3')])  # in the order of the buckets
            self.assertEqual(summary['reproduction'], {'reproduced': 8, 'not reproduced': 0})  # the 4 divergences and 4 caps
            self.assertEqual({k: summary[k] for k in ('mode', 'battles', 'seed', 'pairings', 'policy', 'node', 'pin', 'harness',
                                                      'git_head', 'library_version')},
                             {'mode': 'random', 'battles': 24, 'seed': 1, 'pairings': ['AB', 'BA', 'AA', 'BB'],
                              'policy': {'max_steps': 300, 'switch_weight': 0.1, 'mega_weight': 0.5}, 'node': 'v0.0.0',
                              'pin': '0' * 40, 'harness': 14, 'git_head': 'abc123', 'library_version': '1.2.3'})
            self.assertNotIn('runner_sha256', summary)
            # No timing in the two files that are compared: it is in timing.json.
            for name in ('battles.jsonl', 'summary.json'):
                with io.open(os.path.join(outdir, name), encoding='ascii') as f:
                    self.assertNotIn('seconds', f.read())
            with io.open(os.path.join(outdir, 'timing.json'), encoding='ascii') as f:
                timing = json.load(f)
            self.assertEqual((timing['battles'], sorted(timing['seconds']), len(timing['slowest'])),
                             (24, sorted(rnd.PHASES), 10))
            # A case for every battle that is not a PASS, and for no other.
            self.assertEqual(sorted(os.listdir(os.path.join(outdir, 'cases'))), sorted('fz_1_%d' % r['index'] for r in records
                                                                                    if r['bucket'] != 'PASS'))

    def test_a_run_in_chunks_is_the_same_as_a_run_in_one(self):
        """The files that are compared (battles.jsonl, summary.json) and the cases do not depend on how the run was cut."""
        with tempfile.TemporaryDirectory() as tmp:
            whole = self.finished(tmp, 'whole')
            expected = read_tree(whole, skip=('partial', 'chunks', 'timing.json'))
            for workers in (1, 3):
                with self.subTest(workers=workers):
                    outdir = os.path.join(tmp, 'chunked%d' % workers)
                    world = World(scenario=scenario_of)
                    clock = FakeClock()
                    sleeps = []
                    ran = []

                    def run_inprocess(command):
                        """What a chunk subprocess does, here: its --start and --chunk-minutes, the lock left out."""
                        start = int(command[command.index('--start') + 1])
                        minutes = int(command[command.index('--chunk-minutes') + 1])
                        self.assertEqual(command[-1], '--no-lock')
                        ran.append(start)
                        run_chunk_of(world, outdir, start, minutes, workers, clock)
                        return 0

                    rnd.check_identity(outdir, IDENTITY)
                    rnd.orchestrate(PARAMS, outdir, ['--battles', '24'], 1, run=run_inprocess, sleep=sleeps.append, bash='bash',
                                    lock_script='lock.sh', python='py', driver_script='d.py', out=io.StringIO())
                    rnd.finalize(outdir, PARAMS.battles)
                    self.assertGreater(len(ran), 1)  # a minute is six battles: it took several chunks
                    self.assertEqual(ran[0], 0)
                    self.assertEqual(ran, sorted(set(ran)))  # each chunk goes on where the last stopped
                    self.assertEqual(sleeps, [rnd.CHUNK_PAUSE] * (len(ran) - 1))  # a pause between chunks, none after the last
                    self.assertEqual(read_tree(outdir, skip=('partial', 'chunks', 'timing.json')), expected)
                    with io.open(os.path.join(outdir, 'timing.json'), encoding='ascii') as f:
                        self.assertEqual(len(json.load(f)['chunks']), len(ran))

    def test_a_chunk_that_is_cut_leaves_a_prefix_and_goes_on_from_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, 'x')
            world = World(scenario=scenario_of)
            clock = FakeClock()
            ran = run_chunk_of(world, outdir, 0, 1, 1, clock)  # 10 s per battle, a minute: the 7th is not started
            self.assertEqual((ran, rnd.first_missing(outdir, 24)), (6, 6))
            self.assertEqual(sorted(os.listdir(os.path.join(outdir, 'partial'))), sorted('%d.json' % i for i in range(6)))
            self.assertEqual(rnd.first_missing(outdir, 24, 10), 10)  # --start: from there on
            ran = run_chunk_of(world, outdir, 6, 1, 1, clock)
            self.assertEqual((ran, rnd.first_missing(outdir, 24)), (6, 12))
            # Battles that have a result are not run again, whatever --start says.
            self.assertEqual(run_chunk_of(world, outdir, 0, None, 2, clock), 12)
            self.assertEqual(rnd.first_missing(outdir, 24), 24)

    def test_a_temporary_file_that_a_killed_chunk_left_is_not_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = self.finished(tmp, 'x')
            with io.open(os.path.join(outdir, 'timing.json'), encoding='ascii') as f:
                before = f.read()
            rnd.write_atomically(os.path.join(outdir, 'chunks', '0.json.4242.7.tmp'), b'{"half')
            rnd.write_atomically(os.path.join(outdir, 'partial', '3.json.4242.7.tmp'), b'{"half')
            rnd.finalize(outdir, PARAMS.battles)
            with io.open(os.path.join(outdir, 'timing.json'), encoding='ascii') as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(rnd.first_missing(outdir, PARAMS.battles), PARAMS.battles)

    def test_finalize_needs_every_battle(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, 'x')
            rnd.check_identity(outdir, IDENTITY)
            run_chunk_of(World(scenario=scenario_of), outdir, 0, 1, 1, FakeClock())
            with self.assertRaises(driver.ToolError) as cm:
                rnd.finalize(outdir, 24)
            self.assertIn('battle 6 and 17 more have no result yet', str(cm.exception))

    def test_a_directory_that_belongs_to_another_run_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            rnd.check_identity(tmp, IDENTITY)
            rnd.check_identity(tmp, IDENTITY)  # the same run again: a resume
            for change, part in (({'seed': 2}, 'seed'), ({'battles': 25}, 'battles'),
                                 ({'pairings': ['AB']}, 'pairings'), ({'node': 'v1.0.0'}, 'node'),
                                 ({'runner_sha256': '0' * 64}, 'runner_sha256'), ({'git_head': 'def456'}, 'git_head'),
                                 ({'domain_rate': 0.5}, 'domain_rate'),
                                 ({'policy': dict(IDENTITY['policy'], mega_weight=0.9)}, 'policy')):
                with self.subTest(part):
                    with self.assertRaises(driver.ToolError) as cm:
                        rnd.check_identity(tmp, dict(IDENTITY, **change))
                    self.assertIn('belongs to another run', str(cm.exception))
                    self.assertIn(part, str(cm.exception))

    def test_the_loop_refuses_a_directory_of_another_run_before_it_starts_a_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            rnd.check_parameters(tmp, PARAMS)  # no run.json yet: nothing to refuse
            rnd.check_identity(tmp, IDENTITY)
            rnd.check_parameters(tmp, PARAMS)  # the same run
            for other, part in ((PARAMS._replace(seed=2), 'seed'), (PARAMS._replace(battles=25), 'battles'),
                                (PARAMS._replace(pairings=('AB',)), 'pairings'), (PARAMS._replace(max_steps=50), 'policy'),
                                (PARAMS._replace(switch_weight=0.2), 'policy'),
                                (PARAMS._replace(domain_rate=0.5), 'domain_rate')):
                with self.subTest(part):
                    with self.assertRaises(driver.ToolError) as cm:
                        rnd.check_parameters(tmp, other)
                    self.assertIn('belongs to another run (it differs in %s)' % part, str(cm.exception))

    def test_a_result_is_written_whole_or_not_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'a', 'b', 'c.json')
            rnd.write_atomically(path, b'one')
            rnd.write_atomically(path, b'two')
            with io.open(path, 'rb') as f:
                self.assertEqual(f.read(), b'two')
            self.assertEqual(os.listdir(os.path.dirname(path)), ['c.json'])


# ------------------------------------------------------------ children that die or hang, as processes

TRACE_PATH = None

RUNNER_CODE = r'''
import re, sys, time
for line in sys.stdin:
    if line.startswith('B '):
        name = line.split()[1]
    elif line.strip() == 'END':
        n = int(re.match(r'fz_\d+_(\d+)', name).group(1))
        if n == 3:
            sys.stderr.write('assertion failed: turn.c:12\n')
            sys.stderr.flush()
            sys.exit(3)
        if n == 5 and not name.endswith('_prefix'):
            time.sleep(60)
        print('R %s PASS CLOSURE - 4 -' % name)
        sys.stdout.flush()
'''
WORKER_CODE = r'''
import json, sys, time
trace_text = open(sys.argv[1], encoding='utf-8', newline='').read()
choices = [s['input'] for s in json.loads(trace_text)['steps']]
for line in sys.stdin:
    req = json.loads(line)
    reply = {'id': req['id'], 'ok': True}
    if req['cmd'] == 'version':
        reply.update(node='v0', pin='p', harness=1)
    elif req['cmd'] == 'play':
        n = req['policy']['seed'] - 1000
        if n == 7:
            sys.stderr.write('Error: heap out of memory\n')
            sys.stderr.flush()
            sys.exit(134)
        if n == 9:
            time.sleep(60)
        reply.update(choices=choices, ended=True, steps=len(choices), domain={'samples': [], 'request_changed': 0})
    else:
        reply.update(trace=trace_text)
    sys.stdout.write(json.dumps(reply) + '\n')
    sys.stdout.flush()
'''


PATIENT = 60  # seconds a stand-in is given to answer: it has to start, perhaps on a machine that is busy with a CI
HANG = 1  # seconds it is given on the battle that it hangs on: no reason to wait long for what must not answer


class StandInRunner(driver.DiffRunner):
    def __init__(self):
        driver.Child.__init__(self, [sys.executable, '-c', 'import sys\n' + RUNNER_CODE], 'the runner', PATIENT)

    def run(self, name, records):
        self.timeout = HANG if name == 'fz_1_5' else PATIENT  # RUNNER_CODE hangs on battle 5
        return super().run(name, records)


class StandInWorker(driver.NodeWorker):
    def __init__(self):
        driver.Child.__init__(self, [sys.executable, '-c', 'import sys\n' + WORKER_CODE, TRACE_PATH], 'the reference worker',
                              PATIENT)
        self.next_id = 1

    def play(self, battle, policy):
        self.timeout = HANG if policy['seed'] == 1009 else PATIENT  # WORKER_CODE hangs on the play of battle 9
        return super().play(battle, policy)


class Crashes(unittest.TestCase):
    """Children that die or hang on a battle are buckets; the lane restarts them and goes on."""

    @classmethod
    def setUpClass(cls):
        global TRACE_PATH
        cls.tmp = tempfile.TemporaryDirectory()
        TRACE_PATH = os.path.join(cls.tmp.name, 'trace.json')
        with io.open(TRACE_PATH, 'w', encoding='utf-8', newline='') as f:
            f.write(driver.load_committed(ROOT, REAL)[1])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_runner_or_a_worker_that_dies_or_hangs_is_a_bucket_and_the_run_goes_on(self):
        params = PARAMS._replace(battles=12)
        world = World()
        made = {'runner': 0, 'worker': 0}
        lock = threading.Lock()

        def make_runner():
            with lock:
                made['runner'] += 1
            return StandInRunner()

        def make_worker():
            with lock:
                made['worker'] += 1
            return StandInWorker()

        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, 'x')
            rnd.check_identity(outdir, rnd.identity_of(params, VERSION, 'h', '1', 'f' * 64))
            rnd.run_chunk(params, outdir, 0, None, make_worker, make_runner, tables, KINDS, world.spec_for, 2, out=io.StringIO())
            rnd.finalize(outdir, 12)
            with io.open(os.path.join(outdir, 'battles.jsonl'), encoding='ascii') as f:
                records = [json.loads(line) for line in f]
            got = {r['index']: (r['bucket'], r['detail']) for r in records}
            self.assertEqual({i: b for i, b in got.items() if b[0] != 'PASS'}, {
                3: ('DIVERGENCE', 'runner died (exit 3)'),
                5: ('DIVERGENCE', 'runner timed out'),
                7: ('REF_ERROR', 'worker died (exit 134)'),
                9: ('REF_ERROR', 'worker timed out')})
            self.assertEqual(sum(1 for r in records if r['bucket'] == 'PASS'), 8)  # the others, after the restarts
            self.assertEqual(records[3]['messages'], ['assertion failed: turn.c:12'])
            self.assertEqual(records[7]['messages'], ['Error: heap out of memory'])
            self.assertEqual((records[3]['step'], records[3]['reproduces'], records[3]['ended']), (None, None, True))
            # Two lanes, and one replacement for each child that failed.
            self.assertEqual(made, {'runner': 2 + 2, 'worker': 2 + 2})
            # The cases are saved: the spec, the trace if there is one, and what the child said.
            self.assertEqual(sorted(os.listdir(os.path.join(outdir, 'cases'))), ['fz_1_3', 'fz_1_5', 'fz_1_7', 'fz_1_9'])
            self.assertIn('trace.json.gz', os.listdir(os.path.join(outdir, 'cases', 'fz_1_3')))
            self.assertIn('play_request.json', os.listdir(os.path.join(outdir, 'cases', 'fz_1_7')))
            self.assertNotIn('trace.json.gz', os.listdir(os.path.join(outdir, 'cases', 'fz_1_7')))
            with io.open(os.path.join(outdir, 'cases', 'fz_1_3', 'messages.txt'), encoding='utf-8') as f:
                self.assertEqual(f.read().split('\n')[:2], ['DIVERGENCE | - | runner died (exit 3)', 'assertion failed: turn.c:12'])
            with io.open(os.path.join(outdir, 'summary.json'), encoding='ascii') as f:
                signatures = [(s['bucket'], s['rule'], s['detail']) for s in json.load(f)['signatures']]
            self.assertEqual(signatures, [('DIVERGENCE', 'runner-failed', 'died (exit 3)'),
                                          ('DIVERGENCE', 'runner-failed', 'timed out'),
                                          ('REF_ERROR', None, 'worker died (exit 134)'),
                                          ('REF_ERROR', None, 'worker timed out')])


# ------------------------------------------------------------ the machine lock

STAND_IN_DRIVER = r'''
import json, os, sys
args = sys.argv[1:]
def option(name):
    return args[args.index(name) + 1]
start, out, battles = int(option('--start')), option('--out'), int(option('--battles'))
lock = os.environ['DUOFORGE_MACHINE_LOCK']
held = os.path.isdir(lock)
owner = open(os.path.join(lock, 'owner')).read().split() if held else []
os.makedirs(os.path.join(out, 'partial'), exist_ok=True)
with open(os.path.join(out, 'chunks.log'), 'a') as f:
    f.write(json.dumps({'args': args, 'lock_held': held, 'label': owner[1] if len(owner) > 1 else None}) + '\n')
for i in range(start, min(start + 3, battles)):
    with open(os.path.join(out, 'partial', '%d.json' % i), 'w') as f:
        f.write('{}')
'''


class FindBash(unittest.TestCase):
    def test_the_bash_that_runs_the_lock_script(self):
        self.assertEqual(rnd.find_bash(False, lambda name: '/usr/bin/bash'), '/usr/bin/bash')
        self.assertIsNone(rnd.find_bash(False, lambda name: None))
        git_on_the_path = 'C:\\Program Files\\Git\\usr\\bin\\bash.exe'
        self.assertEqual(rnd.find_bash(True, lambda name: git_on_the_path, {}), git_on_the_path)
        launcher = lambda name: 'C:\\Windows\\System32\\bash.exe'  # the launcher of WSL runs the script in another system
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rnd.find_bash(True, launcher, {'ProgramFiles': tmp, 'LocalAppData': tmp}))
            self.assertIsNone(rnd.find_bash(True, lambda name: None, {}))
            os.makedirs(os.path.join(tmp, 'Programs', 'Git', 'bin'))
            with io.open(os.path.join(tmp, 'Programs', 'Git', 'bin', 'bash.exe'), 'w') as f:
                f.write('')
            self.assertEqual(rnd.find_bash(True, launcher, {'ProgramFiles': tmp, 'LocalAppData': tmp}),
                             os.path.join(tmp, 'Programs', 'Git', 'bin', 'bash.exe'))


@unittest.skipUnless(rnd.find_bash(), 'no bash that can run tools/ci/machine_lock.sh')
class Lock(unittest.TestCase):
    """The chunks as processes under tools/ci/machine_lock.sh, with DUOFORGE_MACHINE_LOCK in a temporary directory:
    never the real lock."""

    def test_a_live_holder_is_alive_whatever_the_callers_path_conversion(self):
        # machine_lock_alive decides whether a lock is stale. A caller that exported MSYS_NO_PATHCONV=1 (for a wsl.exe
        # command) made Git Bash pass tasklist's `//FI` unconverted: every live holder looked dead and its lock was
        # taken over (2026-10-09). This test process is a live holder; a pid far above any real one is not.
        script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
        for conv in ('', '1'):
            env = dict(os.environ)
            env.pop('MSYS_NO_PATHCONV', None)
            if conv:
                env['MSYS_NO_PATHCONV'] = conv
            for pid, alive in ((os.getpid(), True), (987654321, False)):
                done = subprocess.run([rnd.find_bash(), '-c', 'source "%s"; machine_lock_alive %d' % (script, pid)],
                                      capture_output=True, text=True, timeout=60, env=env)
                self.assertEqual(done.returncode == 0, alive, (conv, pid, done.stderr))

    def test_each_chunk_holds_the_lock_and_the_lock_is_free_between_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, 'lock')
            outdir = os.path.join(tmp, 'out')
            script = os.path.join(tmp, 'stand_in_driver.py')
            with io.open(script, 'w', encoding='utf-8') as f:
                f.write(STAND_IN_DRIVER)
            params = PARAMS._replace(battles=8)
            free_between = []

            def sleep(seconds):
                free_between.append((seconds, os.path.exists(lock)))

            with mock.patch.dict(os.environ, {'DUOFORGE_MACHINE_LOCK': lock}):
                rnd.orchestrate(params, outdir, ['--battles', '8', '--out', outdir], 7, sleep=sleep, driver_script=script,
                                out=io.StringIO())
            with io.open(os.path.join(outdir, 'chunks.log'), encoding='utf-8') as f:
                chunks = [json.loads(line) for line in f]
            self.assertEqual([c['lock_held'] for c in chunks], [True, True, True])  # inside each chunk
            self.assertEqual([c['label'] for c in chunks], ['fuzz'] * 3)  # the label the owner asked for
            for c, start in zip(chunks, (0, 3, 6)):
                self.assertEqual(c['args'][0], 'random')
                self.assertEqual(c['args'][-5:], ['--start', str(start), '--chunk-minutes', '7', '--no-lock'])
                self.assertEqual(c['args'][c['args'].index('--battles') + 1], '8')
            self.assertEqual(free_between, [(30, False), (30, False)])  # released, 30 s between, none after the last
            self.assertFalse(os.path.exists(lock))  # and nothing is left held at the end

    def test_a_chunk_that_fails_or_does_not_move_stops_the_loop(self):
        params = PARAMS._replace(battles=8)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(driver.ToolError) as cm:
                rnd.orchestrate(params, tmp, [], 5, run=lambda command: 4, sleep=lambda s: None, bash='bash',
                                lock_script='l', python='p', driver_script='d', out=io.StringIO())
            self.assertIn('exited with status 4', str(cm.exception))
            with self.assertRaises(driver.ToolError) as cm:
                rnd.orchestrate(params, tmp, [], 5, run=lambda command: 0, sleep=lambda s: None, bash='bash',
                                lock_script='l', python='p', driver_script='d', out=io.StringIO())
            self.assertIn('made no progress', str(cm.exception))

    def test_the_command_of_a_chunk(self):
        command = rnd.chunk_command(['--seed', '1'], 40, 10, python='C:\\Py\\python.exe', driver_script='C:\\r\\diff_driver.py',
                                    bash='bash', lock_script='C:\\r\\tools\\ci\\machine_lock.sh')
        self.assertEqual(command, ['bash', 'C:/r/tools/ci/machine_lock.sh', 'fuzz', 'C:/Py/python.exe', 'C:/r/diff_driver.py',
                                   'random', '--seed', '1', '--start', '40', '--chunk-minutes', '10', '--no-lock'])

    def test_the_status_of_a_chunk_that_found_the_pause_file_passes_the_wrapper_and_the_lock_is_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, 'lock')
            script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
            command = [rnd.find_bash(), script, 'fuzz', sys.executable.replace('\\', '/'), '-c',
                       'import os, sys; sys.exit(%d if os.path.isdir(sys.argv[1]) else 1)' % rnd.PAUSED_STATUS,
                       lock.replace('\\', '/')]  # the child exits with 75 only while the lock is held
            with mock.patch.dict(os.environ, {'DUOFORGE_MACHINE_LOCK': lock}):
                self.assertEqual(rnd.run_process(command), rnd.PAUSED_STATUS)
            self.assertFalse(os.path.exists(lock))

    def test_a_free_lock_goes_to_the_oldest_live_waiter(self):
        # First come, first served: a waiter takes a ticket; the lock goes to the oldest ticket whose process lives,
        # not to whoever polls first (2026-10-09: short jobs queued for an hour behind later arrivals). The stand-in
        # sleep counts the rounds; an older live waiter (pid 4242) leaves the queue in round 3, and a dead waiter's
        # ticket (pid 987654321) is no obstacle. One slot: with two, the free second slot admits this waiter at once
        # (test_with_two_slots_the_second_waiter_is_admitted_while_two_slots_are_free).
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, 'lock')
            queue = lock + '.queue'
            os.mkdir(queue)
            for name in ('0000000000000000001-987654321', '0000000000000000002-4242'):
                with io.open(os.path.join(queue, name), 'w', encoding='ascii', newline='\n') as f:
                    f.write('%s other since 2026-10-09 12:00:00\n' % name.split('-')[1])
            script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
            shell = ('source "%s"; machine_lock_alive() { [ "$1" = 4242 ] || [ "$1" = "$(machine_lock_pid)" ]; }; n=0; '
                     'sleep() { n=$((n + 1)); if [ $n -eq 3 ]; then rm -f "$MACHINE_LOCK.queue/"*-4242; fi; }; '
                     'machine_lock_acquire fuzz && echo "rounds $n" && ls "$MACHINE_LOCK.queue" | wc -l && '
                     'machine_lock_release' % script)
            done = subprocess.run([rnd.find_bash(), '-c', shell], capture_output=True, text=True, timeout=60,
                                  env=dict(os.environ, DUOFORGE_MACHINE_LOCK=lock.replace('\\', '/'),
                                           DUOFORGE_MACHINE_LOCK_SLOTS='1'))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.split(), ['rounds', '3', '0'])  # waited for 4242, its ticket gone, no ticket left
            self.assertFalse(os.path.exists(lock))

    def test_a_chunk_that_waits_names_the_holder_and_the_minutes_waited_every_five_minutes(self):
        # The script is sourced with two stand-ins: sleep counts the rounds (15 s each) and the holder releases the lock
        # in the 21st, and the holder's pid is alive without asking tasklist (one call is about a second on Windows).
        # One slot, so that one holder fills the machine (two: test_with_two_slots_a_third_job_waits_for_a_free_slot).
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, 'lock')
            os.mkdir(lock)
            with io.open(os.path.join(lock, 'owner'), 'w', encoding='ascii', newline='\n') as f:
                f.write('4242 local_ci other-checkout since 2026-10-09 12:00:00\n')
            script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
            shell = ('source "%s"; machine_lock_alive() { [ "$1" = 4242 ]; }; n=0; '
                     'sleep() { n=$((n + 1)); if [ $n -eq 21 ]; then rm -rf "$MACHINE_LOCK"; fi; }; '
                     'machine_lock_acquire fuzz && head -n 1 "$MACHINE_LOCK/owner" && machine_lock_release' % script)
            done = subprocess.run([rnd.find_bash(), '-c', shell], capture_output=True, text=True, timeout=60,
                                  env=dict(os.environ, DUOFORGE_MACHINE_LOCK=lock.replace('\\', '/'),
                                           DUOFORGE_MACHINE_LOCK_SLOTS='1'))
            self.assertEqual(done.returncode, 0, done.stderr)
            holder = '4242 local_ci other-checkout since 2026-10-09 12:00:00'
            self.assertEqual(done.stderr.splitlines(), [
                'machine lock: waiting for %s (0 min so far)' % holder,  # at once: who holds it and since when
                'machine lock: waiting for %s (5 min so far)' % holder,  # then every 300 s: how long this one waited
            ])
            self.assertRegex(done.stdout, r'^\d+ fuzz since \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\n$')  # then it is ours
            self.assertFalse(os.path.exists(lock))

    # Slots (2026-10-10): DUOFORGE_MACHINE_LOCK_SLOTS jobs at once, 2 by default. Slot 0 is the lock directory of the
    # one-slot script ($MACHINE_LOCK), slot k is $MACHINE_LOCK.slot<k>: a holder or waiter of the old script still
    # counts. The waits below use the stand-ins of the tests above: sleep counts the rounds and changes the scene.

    def lock_shell(self, tmp, body, alive=(), slots=None, cpus='16', holders=(), tickets=(), record=None, before=''):
        """Runs `body` in a bash that sourced the lock script, with DUOFORGE_MACHINE_LOCK=<tmp>/lock, the pids `alive`
        (and its own) alive, NUMBER_OF_PROCESSORS=`cpus`, DUOFORGE_MACHINE_LOCK_SLOTS=`slots` (None: unset, the
        default), the slot holders `holders` [(slot, owner line[, marked])], marked as this script marks them unless
        the third item is False (a holder of the old script), the queue tickets `tickets` [(name, text)] and the
        recorded slot count `record` (queue/.slots). `before` runs first in the alive stand-in (with the pid in $1)."""
        lock = os.path.join(tmp, 'lock')
        for holder in holders:
            slot, owner = holder[:2]
            marked = holder[2] if len(holder) > 2 else True
            path = lock if slot == 0 else '%s.slot%d' % (lock, slot)
            os.mkdir(path)
            with io.open(os.path.join(path, 'owner'), 'w', encoding='ascii', newline='\n') as f:
                f.write(owner + ('\nslots\n' if marked else '\n'))
        if tickets or record is not None:
            os.mkdir(lock + '.queue')
        for name, text in tickets:
            with io.open(os.path.join(lock + '.queue', name), 'w', encoding='ascii', newline='\n') as f:
                f.write(text)
        if record is not None:
            with io.open(os.path.join(lock + '.queue', '.slots'), 'w', encoding='ascii', newline='\n') as f:
                f.write(record + '\n')
        script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
        live = ' || '.join(['[ "$1" = "$(machine_lock_pid)" ]'] + ['[ "$1" = %d ]' % pid for pid in alive])
        shell = 'source "%s"; machine_lock_alive() { %s %s; }; n=0; %s' % (script, before, live, body)
        env = dict(os.environ, DUOFORGE_MACHINE_LOCK=lock.replace('\\', '/'), NUMBER_OF_PROCESSORS=cpus)
        env.pop('DUOFORGE_MACHINE_LOCK_SLOTS', None)
        env.pop('DUOFORGE_JOBS', None)
        if slots is not None:
            env['DUOFORGE_MACHINE_LOCK_SLOTS'] = slots
        return lock, subprocess.run([rnd.find_bash(), '-c', shell], capture_output=True, text=True, timeout=60, env=env)

    def test_with_two_slots_a_job_alone_holds_the_old_lock_directory_and_is_told_half_the_processors(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz && echo "rounds $n" '
                                              '&& echo "jobs $DUOFORGE_JOBS" && ls -d "$MACHINE_LOCK"* && '
                                              'cat "$MACHINE_LOCK/owner" && machine_lock_release')
            self.assertEqual(done.returncode, 0, done.stderr)
            lines = done.stdout.splitlines()
            self.assertEqual(lines[:2], ['rounds 0', 'jobs 8'])  # at once; 16 processors over 2 slots
            self.assertEqual(sorted(os.path.basename(p) for p in lines[2:-2]), ['lock', 'lock.queue'])  # slot 0 only
            self.assertRegex(lines[-2], r'^\d+ fuzz since ')
            self.assertEqual(lines[-1], 'slots')  # the mark of this script: no holder of the old one
            self.assertFalse(os.path.exists(lock))
            self.assertEqual(os.listdir(lock + '.queue'), [])  # the machine is idle: no record of the slot count

    def test_with_two_slots_a_job_beside_a_holder_of_this_script_takes_the_second_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz && echo "rounds $n" '
                                              '&& cat "$MACHINE_LOCK.slot1/owner" && machine_lock_release',
                                         alive=(4242,), holders=[(0, '4242 local_ci one since 2026-10-09 12:00:00')])
            self.assertEqual(done.returncode, 0, done.stderr)
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 0')
            self.assertRegex(lines[1], r'^\d+ fuzz since ')
            self.assertFalse(os.path.exists(lock + '.slot1'))  # released
            with io.open(os.path.join(lock, 'owner'), encoding='ascii') as f:  # and the other holder's slot untouched
                self.assertEqual(f.read(), '4242 local_ci one since 2026-10-09 12:00:00\nslots\n')

    def test_a_holder_of_the_old_script_keeps_the_machine_to_itself(self):
        # The one-slot script writes its owner file without the mark: its job was promised the whole machine, so a job
        # of this script waits although slot 1 is free.
        with tempfile.TemporaryDirectory() as tmp:
            old = '4242 local_ci old-script since 2026-10-09 12:00:00'
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); if [ $n -eq 2 ]; then rm -rf "$MACHINE_LOCK"; fi; }; '
                                              'machine_lock_acquire fuzz && echo "rounds $n" && '
                                              'head -n 1 "$MACHINE_LOCK/owner" && machine_lock_release',
                                         alive=(4242,), holders=[(0, old, False)])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s (0 min so far)' % old])
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 2')  # only once the old holder is gone
            self.assertRegex(lines[1], r'^\d+ fuzz since ')  # and then in slot 0

    def test_while_a_waiter_of_the_old_script_queues_a_job_takes_only_slot_0(self):
        # The old script waits for slot 0 only and then runs as if alone: a job of this script must not hold slot 1
        # when that happens, wherever the old waiter's ticket stands (here: after this job's).
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); if [ $n -eq 2 ]; then rm -rf "$MACHINE_LOCK"; fi; }; '
                                              'machine_lock_acquire fuzz && echo "rounds $n" && '
                                              'head -n 1 "$MACHINE_LOCK/owner" && machine_lock_release',
                                         alive=(4242, 4243), holders=[(0, '4242 local_ci one since 2026-10-09 12:00:00')],
                                         tickets=[('9999999999999999999-4243', '4243 old-script since 2026-10-09 12:00:00\n')])
            self.assertEqual(done.returncode, 0, done.stderr)
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 2')  # slot 1 was free all along
            self.assertRegex(lines[1], r'^\d+ fuzz since ')

    def test_with_two_slots_an_older_waiter_of_the_old_script_lets_nobody_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            older = '4243 old-script since 2026-10-09 12:00:00'
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); rm -f "$MACHINE_LOCK.queue/"*-4243; }; '
                                              'machine_lock_acquire fuzz && echo "rounds $n" && machine_lock_release',
                                         alive=(4243,), tickets=[('0000000000000000001-4243', older + '\n')])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s (0 min so far)' % older])
            self.assertEqual(done.stdout.splitlines(), ['rounds 1'])

    def test_with_two_slots_a_third_job_waits_for_a_free_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = '4242 local_ci one since 2026-10-09 12:00:00'
            b = '4243 bench two since 2026-10-09 12:01:00'
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); if [ $n -eq 2 ]; then rm -rf "$MACHINE_LOCK.slot1"; '
                                              'fi; }; machine_lock_acquire fuzz && echo "rounds $n" && '
                                              'cat "$MACHINE_LOCK.slot1/owner" && machine_lock_release',
                                         alive=(4242, 4243), holders=[(0, a), (1, b)])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s; %s (0 min so far)' % (a, b)])
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 2')  # the second holder left in round 2
            self.assertRegex(lines[1], r'^\d+ fuzz since ')
            self.assertTrue(os.path.isdir(lock))  # the first holder's slot stays

    def test_with_two_slots_the_second_waiter_is_admitted_while_two_slots_are_free(self):
        # One older live waiter and two free slots: both can run. The later waiter takes the highest free slot and leaves
        # slot 0 to the head of the queue, which may run the one-slot script (it knows only slot 0).
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz && echo "rounds $n" '
                                              '&& ls -d "$MACHINE_LOCK"* && machine_lock_release',
                                         alive=(4242,), tickets=[('0000000000000000001-987654321', '987654321 dead\n'),
                                                                 ('0000000000000000002-4242', '4242 other\nslots\n')])
            self.assertEqual(done.returncode, 0, done.stderr)
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 0')
            self.assertEqual(sorted(os.path.basename(p) for p in lines[1:]), ['lock.queue', 'lock.slot1'])
            self.assertEqual(sorted(os.listdir(lock + '.queue')), ['.slots', '0000000000000000002-4242'])  # dead one gone

    def test_with_two_slots_a_waiter_waits_while_older_waiters_take_the_free_slots(self):
        # First come, first served with slots: one slot free and one older live waiter, so the slot is the older one's.
        with tempfile.TemporaryDirectory() as tmp:
            older = '4243 other since 2026-10-09 12:00:00'
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); if [ $n -eq 2 ]; then rm -f "$MACHINE_LOCK.queue/"*-4243; '
                                              'fi; }; machine_lock_acquire fuzz && echo "rounds $n" && '
                                              'cat "$MACHINE_LOCK.slot1/owner" && machine_lock_release',
                                         alive=(4242, 4243), holders=[(0, '4242 local_ci one since 2026-10-09 11:00:00')],
                                         tickets=[('0000000000000000001-4243', older + '\nslots\n')])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s (0 min so far)' % older])
            lines = done.stdout.splitlines()
            self.assertEqual(lines[0], 'rounds 2')
            self.assertRegex(lines[1], r'^\d+ fuzz since ')

    def test_a_stale_slot_is_taken_over_whichever_slot_it_is(self):
        live = '4242 local_ci one since 2026-10-09 12:00:00'
        dead = '987654321 bench gone since 2026-10-09 11:00:00'
        for stale_slot in (0, 1):
            with self.subTest(stale_slot=stale_slot), tempfile.TemporaryDirectory() as tmp:
                path = '"$MACHINE_LOCK"' if stale_slot == 0 else '"$MACHINE_LOCK.slot1"'
                lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz && '
                                                  'echo "rounds $n" && cat %s/owner && machine_lock_release' % path,
                                             alive=(4242,), holders=[(stale_slot, dead), (1 - stale_slot, live)])
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stderr.splitlines(), ['machine lock: removing a stale lock (%s)' % dead])
                lines = done.stdout.splitlines()
                self.assertEqual(lines[0], 'rounds 0')
                self.assertRegex(lines[1], r'^\d+ fuzz since ')  # the stale slot is now this job's

    def test_a_stale_slot_that_changed_hands_meanwhile_is_not_removed(self):
        # Between reading a dead holder's owner and removing the slot, another waiter may have taken the slot over: the
        # owner is read again right before the removal. The stand-in of machine_lock_alive plays that waiter.
        with tempfile.TemporaryDirectory() as tmp:
            live = '4242 local_ci one since 2026-10-09 12:00:00'
            thief = '4243 fuzz since 2026-10-09 12:05:00'
            take = ('if [ "$1" = 987654321 ]; then printf "%s\\nslots\\n" > "$MACHINE_LOCK.slot1/owner"; return 1; fi; '
                    % thief)
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); rm -rf "$MACHINE_LOCK.slot1"; }; '
                                              'machine_lock_acquire fuzz && echo "rounds $n" && machine_lock_release',
                                         alive=(4242, 4243), before=take,
                                         holders=[(0, live), (1, '987654321 bench gone since 2026-10-09 11:00:00')])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s; %s (0 min so far)' % (live, thief)])
            self.assertEqual(done.stdout.splitlines(), ['rounds 1'])  # it waited for the new holder

    def test_a_slot_without_owner_is_starting_and_after_five_minutes_stale(self):
        # A job killed between mkdir and writing its owner file leaves an empty slot directory: young, it is a job that
        # is starting; five minutes old, it is stale.
        live = '4242 local_ci one since 2026-10-09 12:00:00'
        for age, rounds, stderr in ((0, 'rounds 1', ['machine lock: waiting for %s; a job that is starting (0 min so far)'
                                                       % live]),
                                    (600, 'rounds 0', None)):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as tmp:
                lock = os.path.join(tmp, 'lock')
                os.mkdir(lock + '.slot1')
                stamp = time.time() - age
                os.utime(lock + '.slot1', (stamp, stamp))
                lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); rm -rf "$MACHINE_LOCK.slot1"; }; '
                                                  'machine_lock_acquire fuzz && echo "rounds $n" && machine_lock_release',
                                             alive=(4242,), holders=[(0, live)])
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.splitlines(), [rounds])
                if stderr is None:
                    self.assertEqual(len(done.stderr.splitlines()), 1)
                    self.assertRegex(done.stderr, r'^machine lock: removing an ownerless lock \(.*lock\.slot1, 10 min old\)\n$')
                else:
                    self.assertEqual(done.stderr.splitlines(), stderr)

    def test_a_slot_count_unlike_the_recorded_one_is_refused_while_jobs_hold_or_wait(self):
        # Every session must count the same slots. The first job records its count in the queue directory; another
        # count is refused while the machine is in use, and replaces the record of an idle machine.
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz; echo "status $?"',
                                         alive=(4242,), holders=[(0, '4242 local_ci one since 2026-10-09 12:00:00')],
                                         record='3')
            self.assertEqual(done.stdout.splitlines(), ['status 2'])
            self.assertIn("DUOFORGE_MACHINE_LOCK_SLOTS is 2 here, but the jobs that hold or wait run with '3'", done.stderr)
            self.assertEqual(os.listdir(lock + '.queue'), ['.slots'])  # no ticket left behind
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz && '
                                              'cat "$MACHINE_LOCK.queue/.slots" && machine_lock_release', record='3')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.splitlines(), ['2'])  # an idle machine: the record is replaced
            self.assertEqual(os.listdir(lock + '.queue'), [])  # and goes when the machine is idle again

    def test_an_exclusive_job_waits_for_every_slot_and_holds_them_all(self):
        # Measurements take the whole machine: --exclusive waits until no slot is held, holds every slot and is told
        # every processor.
        with tempfile.TemporaryDirectory() as tmp:
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); if [ $n -eq 2 ]; then rm -rf "$MACHINE_LOCK.slot1"; '
                                              'fi; }; machine_lock_acquire --exclusive bench && echo "rounds $n" && '
                                              'echo "jobs $DUOFORGE_JOBS" && head -q -n 1 "$MACHINE_LOCK/owner" '
                                              '"$MACHINE_LOCK.slot1/owner" && machine_lock_release && ls -d "$MACHINE_LOCK"*',
                                         alive=(4243,), holders=[(1, '4243 fuzz since 2026-10-09 12:00:00')])
            self.assertEqual(done.returncode, 0, done.stderr)
            lines = done.stdout.splitlines()
            self.assertEqual(lines[:2], ['rounds 2', 'jobs 16'])
            self.assertRegex(lines[2], r'^\d+ bench since ')
            self.assertEqual(lines[2], lines[3])
            self.assertEqual([os.path.basename(p) for p in lines[4:]], ['lock.queue'])  # both slots released

    def test_a_waiter_behind_an_exclusive_waiter_waits_although_slots_are_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            older = '4243 bench since 2026-10-09 12:00:00'
            lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); rm -f "$MACHINE_LOCK.queue/"*-4243; }; '
                                              'machine_lock_acquire fuzz && echo "rounds $n" && machine_lock_release',
                                         alive=(4243,), tickets=[('0000000000000000001-4243', older + '\nslots exclusive\n')])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr.splitlines(), ['machine lock: waiting for %s (0 min so far)' % older])
            self.assertEqual(done.stdout.splitlines(), ['rounds 1'])

    def test_a_slot_count_that_is_not_a_positive_number_is_refused(self):
        for slots in ('0', 'two', '', '-1'):
            with self.subTest(slots=slots), tempfile.TemporaryDirectory() as tmp:
                lock, done = self.lock_shell(tmp, 'sleep() { n=$((n + 1)); }; machine_lock_acquire fuzz; echo "status $?"',
                                             slots=slots)
                self.assertEqual(done.stdout.splitlines(), ['status 2'])
                self.assertIn('DUOFORGE_MACHINE_LOCK_SLOTS', done.stderr)
                self.assertFalse(os.path.exists(lock))

    def test_two_wrapped_jobs_run_at_the_same_time_and_an_exclusive_one_runs_alone(self):
        # Real processes, the wrapper form, the default of two slots. Each wrapped command marks that it started and
        # waits (at most 30 s) until both have: it exits 0 only if the other one ran at the same time.
        meet = ('import os, sys, time\n'
                'open(os.path.join(sys.argv[1], sys.argv[2]), "w").write(os.environ["DUOFORGE_JOBS"])\n'
                'end = time.time() + 30\n'
                'while len(os.listdir(sys.argv[1])) < 2 and time.time() < end:\n'
                '    time.sleep(0.1)\n'
                'sys.exit(0 if len(os.listdir(sys.argv[1])) == 2 else 3)\n')
        script = os.path.join(ROOT, 'tools', 'ci', 'machine_lock.sh').replace('\\', '/')
        with tempfile.TemporaryDirectory() as tmp:
            lock = os.path.join(tmp, 'lock')
            marks = os.path.join(tmp, 'marks')
            os.mkdir(marks)
            env = dict(os.environ, DUOFORGE_MACHINE_LOCK=lock.replace('\\', '/'), NUMBER_OF_PROCESSORS='16')
            env.pop('DUOFORGE_MACHINE_LOCK_SLOTS', None)
            jobs = [subprocess.Popen([rnd.find_bash(), script, name, sys.executable.replace('\\', '/'), '-c', meet,
                                      marks.replace('\\', '/'), name], env=env) for name in ('a', 'b')]
            self.assertEqual([job.wait(timeout=60) for job in jobs], [0, 0])
            for name in ('a', 'b'):
                with io.open(os.path.join(marks, name), encoding='ascii') as f:
                    self.assertEqual(f.read(), '8')
            self.assertEqual(sorted(os.listdir(tmp)), ['lock.queue', 'marks'])  # both released
            held = ('import os, sys; d = sys.argv[1]; '
                    'print(os.environ["DUOFORGE_JOBS"], os.path.isdir(d), os.path.isdir(d + ".slot1"))')
            done = subprocess.run([rnd.find_bash(), script, '--exclusive', 'bench', sys.executable.replace('\\', '/'), '-c',
                                   held, lock.replace('\\', '/')], capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.split(), ['16', 'True', 'True'])
            self.assertEqual(sorted(os.listdir(tmp)), ['lock.queue', 'marks'])


# ------------------------------------------------------------ the command line

class CommandLine(unittest.TestCase):
    def parse(self, *argv):
        parser = driver_parser()
        return parser, parser.parse_args(['random', *argv])

    def refused(self, *argv):
        parser, args = self.parse(*argv)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            rnd.validate(parser, args)
        self.assertEqual(cm.exception.code, 2)
        return err.getvalue()

    def test_pairings(self):
        self.assertEqual(rnd.parse_pairings('AB,BA,AA,BB'), ('AB', 'BA', 'AA', 'BB'))
        self.assertEqual(rnd.parse_pairings(' ab , cc '), ('AB', 'CC'))
        self.assertEqual(rnd.parse_pairings(','.join(rnd.PAIRINGS)), rnd.PAIRINGS)
        for bad in ('', 'AD', 'A', 'AB,XY', 'ABC'):
            with self.assertRaises(ValueError):
                rnd.parse_pairings(bad)
        self.assertEqual(rnd.DEFAULT_PAIRINGS, ('AB', 'BA', 'AA', 'BB'))  # Team C is opt-in

    def test_the_arguments_that_are_refused(self):
        exe = os.path.abspath(__file__)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            base_args = ['--checkout', tmp, '--runner', exe, '--battles', '10', '--seed', '1', '--node', exe]
            for extra, part in ((['--pairings', 'AX'], 'pairings are some of'), (['--battles', '0'], 'at least 1'),
                                (['--seed', '-1'], 'at least 0'), (['--workers', '0'], 'at least 1'),
                                (['--max-steps', '0'], 'at least 1'), (['--chunk-minutes', '0'], '--chunk-minutes is at least 1'),
                                (['--switch-weight', '1.5'], 'from 0 to 1'), (['--mega-weight', '-0.1'], 'from 0 to 1'),
                                (['--domain-rate', '1.5'], 'from 0 to 1'), (['--domain-rate', '-0.5'], 'from 0 to 1'),
                                (['--domain-rate', 'nan'], 'from 0 to 1'),
                                (['--start', '10'], 'is not before --battles')):
                with self.subTest(extra):
                    # The option is given twice, and the later one wins (argparse).
                    self.assertIn(part, self.refused(*(base_args + extra)))
            self.assertIn('is not a file', self.refused(*(base_args + ['--runner', exe + '.none'])))
            self.assertIn('has no dist/sim', self.refused(*(base_args + ['--checkout', ROOT])))
            parser, args = self.parse(*base_args)
            params = rnd.validate(parser, args)
            self.assertEqual(params, rnd.Params(1, 10, rnd.DEFAULT_PAIRINGS, 300, 0.1, 0.5, 0.1))  # 10% of the requests
            parser, args = self.parse(*(base_args + ['--pairings', 'ab,cc', '--max-steps', '50', '--switch-weight', '0.3',
                                                     '--mega-weight', '1', '--domain-rate', '0']))
            self.assertEqual(rnd.validate(parser, args), rnd.Params(1, 10, ('AB', 'CC'), 50, 0.3, 1.0, 0.0))
            self.assertFalse(args.no_lock)
            self.assertEqual((args.chunk_minutes, args.start), (None, 0))

    def test_what_a_chunk_is_told(self):
        exe = os.path.abspath(__file__)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            parser, args = self.parse('--checkout', tmp, '--runner', exe, '--battles', '10', '--seed', '3', '--workers', '5',
                                      '--pairings', 'AB,CC', '--switch-weight', '0.25', '--node', 'node')
            self.assertEqual(rnd.forwarded(args, '/out/dir'), [
                '--checkout', tmp, '--runner', exe, '--battles', '10', '--seed', '3', '--pairings', 'AB,CC', '--workers', '5',
                '--out', '/out/dir', '--max-steps', '300', '--switch-weight', '0.25', '--mega-weight', '0.5',
                '--domain-rate', '0.1', '--node', 'node'])
            # The chunk parses that again into the same run.
            chunk_args = parser.parse_args(['random'] + rnd.forwarded(args, '/out/dir') + ['--start', '4', '--chunk-minutes', '9', '--no-lock'])
            self.assertEqual(rnd.validate(parser, chunk_args), rnd.validate(parser, args))
            self.assertEqual((chunk_args.start, chunk_args.chunk_minutes, chunk_args.no_lock, chunk_args.out), (4, 9, True, '/out/dir'))


def driver_parser():
    import argparse
    parser = argparse.ArgumentParser(prog='diff_driver.py')
    modes = parser.add_subparsers(dest='mode', required=True)
    rnd.add_arguments(modes)
    return parser


# ------------------------------------------------------------ the pause file

class PauseFile(unittest.TestCase):
    """Measurements pause the fuzzing by making a file (docs/TESTING_AND_BENCHMARKS.md section 7): the loop looks at it
    before each chunk, and a chunk that holds the lock looks again."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'pause')
        self.addCleanup(self.tmp.cleanup)

    def make(self):
        with io.open(self.path, 'w') as f:
            f.write('a measurement\n')

    def test_the_path_is_the_variable_or_a_file_in_the_temporary_folder(self):
        self.assertEqual(rnd.pause_path({'DUOFORGE_FUZZ_PAUSE': 'x/pause', 'TEMP': 'T'}), 'x/pause')
        self.assertEqual(rnd.pause_path({'TEMP': 'T'}), os.path.join('T', 'duoforge-fuzz.pause'))
        self.assertEqual(rnd.pause_path({'DUOFORGE_FUZZ_PAUSE': '', 'TEMP': 'T'}), os.path.join('T', 'duoforge-fuzz.pause'))
        self.assertEqual(rnd.pause_path({}), os.path.join(tempfile.gettempdir(), 'duoforge-fuzz.pause'))
        self.assertEqual(rnd.pause_path(), os.environ['DUOFORGE_FUZZ_PAUSE'])  # what these tests run with

    def test_without_the_file_there_is_nothing_to_wait_for(self):
        out = io.StringIO()
        self.assertFalse(rnd.wait_while_paused(self.path, sleep=self.fail, out=out))
        self.assertEqual(out.getvalue(), '')

    def test_it_says_so_once_and_looks_every_fifteen_seconds_until_the_file_is_gone(self):
        self.make()
        out, sleeps = io.StringIO(), []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                os.remove(self.path)

        self.assertTrue(rnd.wait_while_paused(self.path, sleep=sleep, out=out))
        self.assertEqual(sleeps, [15, 15, 15])
        self.assertEqual(rnd.PAUSE_POLL, 15)
        self.assertEqual(out.getvalue(), 'fuzz paused by %s\n' % self.path)  # one line, however long it takes

    def orchestrate(self, run, sleep, battles=6, **kw):
        outdir = os.path.join(self.tmp.name, 'out')
        out = io.StringIO()
        rnd.orchestrate(PARAMS._replace(battles=battles), outdir, [], 5, run=run, sleep=sleep, bash='bash', lock_script='l',
                        python='p', driver_script='d', out=out, pause=self.path, **kw)
        return out.getvalue()

    def ran(self, outdir_battles=6):
        """A chunk that runs every battle that is left: the results are what first_missing looks at."""
        def run(command):
            outdir = os.path.join(self.tmp.name, 'out')
            for index in range(rnd.first_missing(outdir, outdir_battles), outdir_battles):
                rnd.write_atomically(rnd.partial_path(outdir, index), b'{}')
            return 0
        return run

    def test_the_loop_waits_before_it_starts_a_chunk(self):
        self.make()
        starts, sleeps = [], []

        def run(command):
            self.assertFalse(os.path.exists(self.path))  # not a chunk while the file is there
            starts.append(command)
            return self.ran()(command)

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                os.remove(self.path)

        text = self.orchestrate(run, sleep)
        self.assertEqual((len(starts), sleeps), (1, [15, 15]))
        self.assertEqual(text.count('fuzz paused by'), 1)
        self.assertIn('fuzz paused by %s\n' % self.path, text)
        self.assertLess(text.index('fuzz paused by'), text.index('chunk from battle 0'))

    def test_a_chunk_that_found_the_file_after_it_got_the_lock_is_a_wait_not_a_failure(self):
        """It leaves with PAUSED_STATUS and the lock goes with it: the loop makes no progress, and no error of it, waits
        for the file to go (one line) and starts the chunk again."""
        statuses, sleeps = [], []

        def run(command):
            if not statuses:
                statuses.append(rnd.PAUSED_STATUS)
                self.make()  # the measurement started while the chunk waited for the lock
                return rnd.PAUSED_STATUS
            statuses.append(0)
            return self.ran()(command)

        def sleep(seconds):
            sleeps.append(seconds)
            if os.path.exists(self.path):
                os.remove(self.path)

        text = self.orchestrate(run, sleep)
        self.assertEqual(statuses, [rnd.PAUSED_STATUS, 0])
        self.assertEqual(sleeps, [15])
        self.assertEqual(text.count('fuzz paused by'), 1)
        self.assertEqual(text.count('chunk from battle 0'), 2)  # the same chunk, again

    def test_no_file_changes_nothing(self):
        sleeps = []
        text = self.orchestrate(self.ran(), sleeps.append, battles=6)
        self.assertEqual((sleeps, 'paused' in text), ([], False))

    def args_of(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            exe = os.path.abspath(__file__)
            parser = driver_parser()
            args = parser.parse_args(['random', '--checkout', tmp, '--runner', exe, '--battles', '4', '--seed', '1',
                                      '--node', exe, '--no-lock', '--chunk-minutes', '5', '--out', self.tmp.name] + list(extra))
            return args, rnd.validate(parser, args)

    def test_a_chunk_that_holds_the_lock_leaves_without_starting_a_battle(self):
        self.make()

        class Started(Exception):
            pass

        args, params = self.args_of()
        with mock.patch.dict(os.environ, {rnd.LOCK_HELD_ENV: '1', 'DUOFORGE_FUZZ_PAUSE': self.path}), \
                mock.patch.object(driver, 'NodeWorker', side_effect=Started):
            self.assertEqual(rnd.run(args, params), rnd.PAUSED_STATUS)  # no worker was made
            os.remove(self.path)
            with self.assertRaises(Started):  # without the file the chunk goes on to its first worker
                rnd.run(args, params)

    def test_a_run_without_the_lock_never_looks_at_the_file(self):
        """CTest runs with --no-lock inside local_ci.sh, which holds the lock: a pause that the measurement makes while it
        waits for that lock must not stop them, or the two would wait for each other."""
        self.make()

        class Started(Exception):
            pass

        args, params = self.args_of()
        environ = {k: v for k, v in os.environ.items() if k != rnd.LOCK_HELD_ENV}
        environ['DUOFORGE_FUZZ_PAUSE'] = self.path
        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(driver, 'NodeWorker', side_effect=Started):
            with self.assertRaises(Started):
                rnd.run(args, params)

    def test_the_chunks_of_the_loop_are_told_that_they_hold_the_lock(self):
        seen = []

        def fake_run(argv, **kwargs):
            seen.append((argv, kwargs))
            return mock.Mock(returncode=0)

        with mock.patch.object(rnd.subprocess, 'run', fake_run), \
                mock.patch.object(driver, 'low_priority', lambda command: (list(command), {'creationflags': 7})):
            self.assertEqual(rnd.run_process(['prog', 'a']), 0)
        argv, kwargs = seen[0]
        self.assertEqual((argv, kwargs['creationflags'], kwargs['env'][rnd.LOCK_HELD_ENV]), (['prog', 'a'], 7, '1'))
        self.assertEqual(kwargs['env']['PATH'], os.environ['PATH'])  # the rest of the environment is the loop's


# ------------------------------------------------------------ team files

TEAM_A = os.path.join(ROOT, 'tests', 'reference', 'teams', 'team_a.txt')
TEAM_B = os.path.join(ROOT, 'tests', 'reference', 'teams', 'team_b.txt')
TEAM_C = os.path.join(ROOT, 'docs', 'research', 'third-team', 'team-c.txt')


def read_text(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


class TeamFiles(unittest.TestCase):
    """--team NAME=path: a paste of six sets as one more letter of the pairings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text, newline=None):
        path = os.path.join(self.tmp.name, name)
        with io.open(path, 'w', encoding='utf-8', newline=newline) as f:
            f.write(text)
        return path

    def test_the_options(self):
        self.assertEqual(rnd.parse_team_options(['d=a.txt', ' E = b=c ']), [('D', 'a.txt'), ('E', 'b=c')])
        # An id of the registry is given by itself (no file, any case); a file of your own as NAME=path.
        self.assertEqual(rnd.parse_team_options(['mc405', 'D=x', 'A', 'Team_7']), [('MC405', None), ('D', 'x'), ('A', None),
                                                                                  ('TEAM_7', None)])
        for bad, part in (('d=', 'an id of the registry or NAME=path'), ('dd=x', 'one letter'), ('1=x', 'one letter'),
                          ('=x', 'one letter'), ('a=x', 'committed teams'), ('C=x', 'committed teams'),
                          ('', 'by its id'), ('1d', 'by its id'), ('mc-405', 'by its id'), ('m c', 'by its id'),
                          ('x' * 33, 'by its id')):
            with self.subTest(bad), self.assertRaises(ValueError) as cm:
                rnd.parse_team_options([bad])
            self.assertIn(part, str(cm.exception))
        for twice in (['d=x', 'D=y'], ['mc405', 'MC405'], ['a', 'A'], ['d', 'd=x']):
            with self.subTest(twice), self.assertRaises(ValueError) as cm:
                rnd.parse_team_options(twice)
            self.assertIn('given twice', str(cm.exception))

    def test_pairings_may_use_the_letters_of_the_team_files(self):
        self.assertEqual(rnd.parse_pairings('ad, DA,dd', 'ABCD'), ('AD', 'DA', 'DD'))
        self.assertEqual(rnd.parse_pairings('AB,CD', tuple('ABCDE')), ('AB', 'CD'))
        for bad in ('AE', 'DD', 'D'):
            with self.subTest(bad), self.assertRaises(ValueError) as cm:
                rnd.parse_pairings(bad, tuple('ABC'))
            self.assertIn('pairings are some of', str(cm.exception))
        self.assertEqual(rnd.parse_pairings('AB,CC'), ('AB', 'CC'))  # the committed teams as ever

    def test_pairings_of_ids_of_more_than_one_character_are_joined_by_a_dash(self):
        ids = ('A', 'B', 'C', 'MC405', 'D')
        # The dash is how two ids are joined; a pair of one-character ids is the same pairing either way, written without it.
        self.assertEqual(rnd.parse_pairings('A-MC405, mc405-a, MC405-MC405, AD, D-A, A-B', ids),
                         ('A-MC405', 'MC405-A', 'MC405-MC405', 'AD', 'DA', 'AB'))
        for bad in ('MC405', 'A-X', 'A-MC405-D', 'AMC405', 'MC405A', '-A', 'A-', 'A--B', 'MC-405'):
            with self.subTest(bad), self.assertRaises(ValueError) as cm:
                rnd.parse_pairings(bad, ids)
            self.assertIn('pairings are some of', str(cm.exception))
        self.assertEqual(rnd.pairing_ids('AB'), ('A', 'B'))
        self.assertEqual(rnd.pairing_ids('A-MC405'), ('A', 'MC405'))
        self.assertEqual(rnd.pairing_ids('MC405-MC408'), ('MC405', 'MC408'))

    def test_the_data_kind_follows_the_members(self):
        sets_a, sets_c = rnd.read_team_file(TEAM_A), rnd.read_team_file(TEAM_C)
        self.assertEqual((rnd.team_data_kind('t', sets_a), rnd.team_data_kind('t', sets_c)), ('closure', 'team_c'))
        # One member that is not in the closure tables makes the team Team C data; with the rest of team A's sets too.
        self.assertEqual(rnd.team_data_kind('t', sets_a[:5] + sets_c[:1]), 'team_c')

    def test_the_closure_and_team_c_kinds_hold_a_member_to_its_set_moves_and_ability(self):
        """The AWS finding of 2026-10-03: PP_62AA4EF34EE42F01 has only extended ids, but its Golisopod runs Sucker Punch, which
        is not in the Team C set of Golisopod (Leech Life, Iron Head, Drill Run, Protect), so TEAM_C refused the team at
        create (12 battles of registry-mix size). The kind is Team C only when every move is a set move and the ability is
        the set ability; the pool takes the rest."""
        path = os.path.join(ROOT, 'data', 'teams', 'PP_62AA4EF34EE42F01.txt')
        sets = rnd.read_team_file(path)
        golisopod = [i for i, s in enumerate(sets) if s.startswith('Golisopod')][0]
        self.assertIn('- Sucker Punch', sets[golisopod])
        self.assertEqual(rnd.team_data_kind('PP_62AA', sets), 'pool')
        fixed = list(sets)
        fixed[golisopod] = sets[golisopod].replace('- Sucker Punch', '- Leech Life')
        # the set move: the team is all closure names again, so closure data
        self.assertEqual(rnd.team_data_kind('PP_62AA', fixed), 'closure')
        # a team of the registry that is all set moves and set abilities keeps its kind, and so do teams A and C
        self.assertEqual(rnd.team_data_kind('PP_470A', rnd.read_team_file(
            os.path.join(ROOT, 'data', 'teams', 'PP_470A6EC2468AF8A4.txt'))), 'closure')
        self.assertEqual(rnd.team_data_kind('t', rnd.read_team_file(TEAM_A)), 'closure')
        self.assertEqual(rnd.team_data_kind('t', rnd.read_team_file(TEAM_C)), 'team_c')

    def test_a_team_file_that_equals_team_a_derives_the_same_battles_as_team_a(self):
        path = self.write('d.txt', read_text(TEAM_A))
        teams = rnd.check_teams([('D', path)])
        self.assertEqual([(t.id, t.data) for t in teams], [('D', 'closure')])
        params_d = rnd.Params(5, 40, ('DB', 'BD', 'DD', 'DA'), 300, 0.1, 0.5, 0.1, teams)
        params_a = params_d._replace(pairings=('AB', 'BA', 'AA', 'AA'), teams=None)
        by_d, by_a = rnd.read_teams(ROOT, teams), rnd.read_teams(ROOT)
        self.assertEqual(by_d['D'], by_a['A'])
        for index in range(40):
            with self.subTest(index=index):
                d, policy_d, pairing_d = rnd.derive(params_d, index, by_d)
                a, policy_a, pairing_a = rnd.derive(params_a, index, by_a)
                self.assertEqual(pairing_d.replace('D', 'A'), pairing_a)
                self.assertEqual(policy_d, policy_a)
                for key in ('name', 'format', 'seed', 'teams'):
                    self.assertEqual(d[key], a[key])
                self.assertEqual(d.get('data'), a.get('data'))
                self.assertEqual(list(d), list(a))
                self.assertIn('team D', d['purpose'])  # every pairing of this run has the letter D
                self.assertNotIn('team D', a['purpose'])

    def test_a_team_with_an_id_of_the_pool_tables_is_pool_data(self):
        """Team C and the pool read the same tables (the pool keeps every extended id): a team is Team C data while all
        its ids are extended ones, pool data from the first one beyond them (here U-turn, step G5), and a battle with
        such a team is a "data": "pool" battle whichever other team it meets."""
        sets_a, sets_c = rnd.read_team_file(TEAM_A), rnd.read_team_file(TEAM_C)
        self.assertIn('- High Horsepower', sets_a[0])
        pool_a = [sets_a[0].replace('- High Horsepower', '- U-turn')] + sets_a[1:]
        self.assertEqual(rnd.team_data_kind('t', pool_a), 'pool')
        self.assertIn('- Protect', sets_c[0])
        pool_c = [sets_c[0].replace('- Protect', '- U-turn')] + sets_c[1:]
        self.assertEqual(rnd.team_data_kind('t', pool_c), 'pool')
        self.assertEqual((rnd.team_data_kind('t', sets_a), rnd.team_data_kind('t', sets_c)), ('closure', 'team_c'))
        # A forme, an item and an ability of the pool tables alone count as well as a move.
        item = [sets_a[0].replace('Miracle Seed', 'Focus Sash')] + sets_a[1:]
        self.assertEqual(rnd.team_data_kind('t', item), 'pool')
        # What no kind has is still a refusal that names the thing and the three kinds.
        with self.assertRaises(ValueError) as cm:
            rnd.team_data_kind('team D', [sets_a[0].replace('- High Horsepower', '- Fake Move')] + sets_a[1:])
        self.assertIn("move 'Fake Move' (set 1)", str(cm.exception))
        self.assertIn('(CLOSURE, TEAM_C, POOL)', str(cm.exception))
        path = self.write('d.txt', '\n\n'.join(pool_a) + '\n')
        teams = rnd.check_teams([('D', path)])
        self.assertEqual([(t.id, t.data) for t in teams], [('D', 'pool')])
        params = rnd.Params(1, 8, ('DA', 'DC', 'AB', 'CA'), 300, 0.1, 0.5, 0.1, teams)
        by = rnd.read_teams(ROOT, teams)
        self.assertEqual(rnd.derive(params, 0, by)[0]['data'], 'pool')  # D against A
        self.assertEqual(rnd.derive(params, 1, by)[0]['data'], 'pool')  # D against Team C: pool wins over team_c
        self.assertNotIn('data', rnd.derive(params, 2, by)[0])  # A against B
        self.assertEqual(rnd.derive(params, 3, by)[0]['data'], 'team_c')  # Team C against A
        self.assertEqual(rnd.run_parameters(params)['teams'], {'D': {'sha256': teams[0].sha256, 'data': 'pool'}})
        self.assertEqual(rnd.STRICT_KIND, {'closure': 'CLOSURE', 'team_c': 'TEAM_C', 'pool': 'POOL'})

    def test_a_team_file_of_team_c_data_makes_the_battles_team_c_data(self):
        teams = rnd.check_teams([('D', self.write('d.txt', read_text(TEAM_C)))])
        self.assertEqual(teams[0].data, 'team_c')
        params = rnd.Params(1, 8, ('DA', 'AB'), 300, 0.1, 0.5, 0.1, teams)
        by = rnd.read_teams(ROOT, teams)
        self.assertEqual(rnd.derive(params, 0, by)[0]['data'], 'team_c')  # D against A
        self.assertNotIn('data', rnd.derive(params, 1, by)[0])  # A against B
        self.assertEqual(rnd.derive(params, 0, by)[0]['teams'][0].count('Basculegion'), 1)

    def test_the_crlf_of_a_file_made_on_windows_is_no_difference(self):
        crlf = self.write('d.txt', read_text(TEAM_A).replace('\n', '\r\n'), newline='')
        with io.open(crlf, 'rb') as f:
            self.assertIn(b'\r\n', f.read())
        self.assertEqual(rnd.read_team_file(crlf), rnd.read_team_file(TEAM_A))
        self.assertEqual(rnd.team_sha256(rnd.read_team_file(crlf)), rnd.team_sha256(rnd.read_team_file(TEAM_A)))

    def refusal(self, text, name='d.txt'):
        path = self.write(name, text)
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('D', path)])
        return str(cm.exception)

    def test_what_the_driver_refuses_before_it_plays(self):
        sets = rnd.read_team_file(TEAM_A)
        text = '\n\n'.join(sets)
        # A name that no data kind has: the thing, the set and where the POOL data kind will go.
        for old, new, what in (('Rillaboom (M) @ Miracle Seed', 'Fakemon (M) @ Miracle Seed', "species 'Fakemon'"),
                               ('@ Miracle Seed', '@ Fake Item', "item 'Fake Item'"),
                               ('Ability: Grassy Surge', 'Ability: Fake Ability', "ability 'Fake Ability'"),
                               ('- Protect', '- Fake Move', "move 'Fake Move'"),
                               ('Adamant Nature', 'Fake Nature', "nature 'Fake'")):
            with self.subTest(what):
                self.assertIn(old, text)
                message = self.refusal(text.replace(old, new, 1))
                self.assertIn(what, message)
                self.assertIn('(set ', message)
                self.assertIn('POOL', message)  # the hook: the next data kind
                self.assertIn('team D', message)
        # A paste of five or seven sets, a gender that is not stated, a level other than 50, a line that no set has, and
        # a file that is not there.
        self.assertIn('has 5 sets, not 6', self.refusal('\n\n'.join(sets[:5])))
        self.assertIn('has 7 sets, not 6', self.refusal('\n\n'.join(sets + sets[:1])))
        self.assertIn('Rillaboom has no gender', self.refusal(text.replace('Rillaboom (M)', 'Rillaboom', 1)))
        self.assertIn('level 50 only', self.refusal(text.replace('Level: 50', 'Level: 100', 1)))
        self.assertIn('not a Showdown paste that the converter reads', self.refusal(text.replace('EVs: ', 'EVs: x / ', 1)))
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('D', os.path.join(self.tmp.name, 'none.txt'))])
        self.assertIn('cannot read the team file', str(cm.exception))

    def test_a_refused_team_is_a_refusal_of_the_command_line(self):
        """Status 2 with the message, before anything is played: not a REF_ERROR of a battle."""
        sets = rnd.read_team_file(TEAM_A)
        bad = self.write('bad.txt', '\n\n'.join(sets).replace('Miracle Seed', 'Fake Item', 1))
        parser = driver_parser()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            exe = os.path.abspath(__file__)
            args = parser.parse_args(['random', '--checkout', tmp, '--runner', exe, '--battles', '4', '--seed', '1',
                                      '--node', exe, '--team', 'D=' + bad, '--pairings', 'AD'])
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                rnd.validate(parser, args)
            self.assertEqual(cm.exception.code, 2)
            self.assertIn("item 'Fake Item'", err.getvalue())
            # A pairing with a letter that is no team is refused as the others are.
            good = self.write('good.txt', read_text(TEAM_A))
            args = parser.parse_args(['random', '--checkout', tmp, '--runner', exe, '--battles', '4', '--seed', '1',
                                      '--node', exe, '--team', 'D=' + good, '--pairings', 'AE'])
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                rnd.validate(parser, args)
            self.assertIn('pairings are some of', err.getvalue())

    def test_the_run_knows_its_team_files(self):
        path = self.write('d.txt', read_text(TEAM_A))
        parser = driver_parser()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            exe = os.path.abspath(__file__)
            base_args = ['random', '--checkout', tmp, '--runner', exe, '--battles', '4', '--seed', '1', '--node', exe]
            args = parser.parse_args(base_args + ['--team', 'd=' + path, '--pairings', 'AD,DB', '--keep-traces'])
            params = rnd.validate(parser, args)
            self.assertEqual(params.pairings, ('AD', 'DB'))
            team = params.teams[0]
            self.assertEqual((team.id, team.path, team.data), ('D', os.path.abspath(path), 'closure'))
            # The identity of the run holds the letter, the hash and the data kind; a run without a team file has none.
            self.assertEqual(rnd.run_parameters(params)['teams'], {'D': {'sha256': team.sha256, 'data': 'closure'}})
            self.assertNotIn('teams', rnd.run_parameters(params._replace(teams=None)))
            # A chunk is told the file, by its absolute path, and keeps what the run keeps.
            forwarded = rnd.forwarded(args, '/out')
            self.assertEqual(forwarded[forwarded.index('--team') + 1], 'D=' + os.path.abspath(path))
            self.assertIn('--keep-traces', forwarded)
            chunk = parser.parse_args(['random'] + forwarded + ['--start', '2', '--chunk-minutes', '3', '--no-lock'])
            self.assertEqual(rnd.validate(parser, chunk), params)
            # Another file under the same letter is another run; so is a file that changes while the run is on.
            other = self.write('e.txt', read_text(TEAM_A).replace('Adamant Nature', 'Jolly Nature', 1))
            changed = rnd.validate(parser, parser.parse_args(base_args + ['--team', 'D=' + other, '--pairings', 'AD']))
            self.assertNotEqual(rnd.run_parameters(changed)['teams'], rnd.run_parameters(params)['teams'])
            rnd.read_teams(ROOT, params.teams)
            with io.open(path, 'a', encoding='utf-8') as f:
                f.write('\n')  # a blank line more does not change the sets
            rnd.read_teams(ROOT, params.teams)
            self.write('d.txt', read_text(TEAM_A).replace('Adamant Nature', 'Jolly Nature', 1))
            with self.assertRaises(driver.ToolError) as cm:
                rnd.read_teams(ROOT, params.teams)
            self.assertIn('changed since the run was set up', str(cm.exception))


class TeamRegistryIds(unittest.TestCase):
    """--team ID: a team of the registry (data/teams, tools/reference/team_registry.py) by its id. The registry here is a
    copy in a temporary directory, with the teams a test adds (the committed one has A, B and C and nothing else yet)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        shutil.copytree(team_registry.registry_dir(ROOT), team_registry.registry_dir(self.root))

    def add(self, team_id, text):
        sets = team_registry.split_sets(text)
        team_registry.add_team(self.root, team_registry.new_entry(team_id, 'a team of the test', sets), sets)

    def test_the_committed_teams_are_read_from_the_registry(self):
        sets = rnd.read_teams(self.root)
        self.assertEqual(sorted(sets), ['A', 'B', 'C'])
        for letter, old in (('A', TEAM_A), ('B', TEAM_B), ('C', TEAM_C)):
            self.assertEqual(sets[letter], rnd.read_team_file(old))  # the files they were read from before the registry
        # The registry is where they come from, and a file is held to the SHA-256 of its entry: a team never changes under
        # its id, so another file under the id A is refused, by the run and by the command line.
        with io.open(team_registry.team_path(self.root, 'A'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(read_text(TEAM_C))
        with self.assertRaises(driver.ToolError) as cm:
            rnd.read_teams(self.root)
        self.assertIn('a team never changes under its id', str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('A', None)], root=self.root)
        self.assertIn('--team A: team A', str(cm.exception))
        os.remove(team_registry.index_path(self.root))
        with self.assertRaises(driver.ToolError) as cm:
            rnd.read_teams(self.root)
        self.assertIn('cannot read the team index', str(cm.exception))

    def test_a_team_of_the_registry_is_taken_by_its_id_and_a_committed_one_needs_no_option(self):
        self.add('MC405', read_text(TEAM_A))
        self.add('TC1', read_text(TEAM_C))
        teams = rnd.check_teams(rnd.parse_team_options(['mc405', 'TC1', 'a', 'C']), root=self.root)
        self.assertEqual([(t.id, t.data) for t in teams], [('MC405', 'closure'), ('TC1', 'team_c')])  # A and C are no Team
        self.assertEqual(teams[0].path, os.path.abspath(team_registry.team_path(self.root, 'MC405')))
        self.assertEqual(teams[0].sha256, rnd.team_sha256(rnd.read_team_file(TEAM_A)))
        self.assertEqual(rnd.check_teams([('A', None), ('B', None), ('C', None)], root=self.root), ())

    def test_an_id_that_the_registry_does_not_have_is_refused_with_the_ids_it_has(self):
        self.add('MC405', read_text(TEAM_A))
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('MC406', None)], root=self.root)
        self.assertIn('--team MC406: no team MC406 in the registry', str(cm.exception))
        self.assertIn('ids are ' + ', '.join([e['id'] for e in team_registry.entries(ROOT)] + ['MC405']), str(cm.exception))

    def test_a_file_of_your_own_must_not_take_the_name_of_a_team_of_the_registry(self):
        self.add('D', read_text(TEAM_A))
        mine = os.path.join(self.root, 'mine.txt')
        with io.open(mine, 'w', encoding='utf-8', newline='\n') as f:
            f.write(read_text(TEAM_A))
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('D', mine)], root=self.root)
        self.assertIn('D is a team of the registry', str(cm.exception))
        self.assertIn('--team D is that team', str(cm.exception))
        self.assertEqual([t.id for t in rnd.check_teams([('E', mine)], root=self.root)], ['E'])  # another letter is free

    def test_a_registry_team_that_the_driver_cannot_play_is_refused_before_it_plays(self):
        """The registry holds what a team is made of, not what the engine plays: a name that no data kind has (the POOL
        data kind comes with P1) is the driver's to refuse, as for a file of your own, never a REF_ERROR of a battle."""
        self.add('FAKE1', read_text(TEAM_A).replace('Miracle Seed', 'Fake Item', 1))
        with self.assertRaises(ValueError) as cm:
            rnd.check_teams([('FAKE1', None)], root=self.root)
        self.assertIn("item 'Fake Item'", str(cm.exception))
        self.assertIn('team FAKE1', str(cm.exception))
        self.assertIn('POOL', str(cm.exception))

    def test_a_registry_team_that_equals_team_a_gives_the_same_battles_as_team_a(self):
        self.add('MC405', read_text(TEAM_A))
        teams = rnd.check_teams([('MC405', None)], root=self.root)
        pairings = rnd.parse_pairings('MC405-B,B-MC405,MC405-MC405,MC405-A', ('A', 'B', 'C', 'MC405'))
        self.assertEqual(pairings, ('MC405-B', 'B-MC405', 'MC405-MC405', 'MC405-A'))
        params_m = rnd.Params(5, 40, pairings, 300, 0.1, 0.5, 0.1, teams)
        params_a = params_m._replace(pairings=('AB', 'BA', 'AA', 'AA'), teams=None)
        by_m, by_a = rnd.read_teams(self.root, teams), rnd.read_teams(self.root)
        self.assertEqual(by_m['MC405'], by_a['A'])
        for index in range(40):
            with self.subTest(index=index):
                m, policy_m, pairing_m = rnd.derive(params_m, index, by_m)
                a, policy_a, pairing_a = rnd.derive(params_a, index, by_a)
                self.assertEqual(tuple('A' if t == 'MC405' else t for t in rnd.pairing_ids(pairing_m)),
                                 rnd.pairing_ids(pairing_a))
                self.assertEqual(policy_m, policy_a)
                for key in ('name', 'format', 'seed', 'teams'):
                    self.assertEqual(m[key], a[key])
                self.assertEqual(m.get('data'), a.get('data'))
                self.assertEqual(list(m), list(a))
                self.assertIn('team MC405', m['purpose'])  # every pairing of this run has the id MC405
                self.assertNotIn('team MC405', a['purpose'])

    def test_a_registry_team_of_team_c_data_makes_the_battles_team_c_data(self):
        self.add('TC1', read_text(TEAM_C))
        teams = rnd.check_teams([('TC1', None)], root=self.root)
        params = rnd.Params(1, 4, ('A-TC1', 'AB'), 300, 0.1, 0.5, 0.1, teams)
        by = rnd.read_teams(self.root, teams)
        self.assertEqual(rnd.derive(params, 0, by)[0]['data'], 'team_c')  # A against TC1
        self.assertNotIn('data', rnd.derive(params, 1, by)[0])  # A against B

    def test_a_registry_file_with_windows_line_ends_is_the_team_the_index_says(self):
        for team_id in ('A', 'B', 'C'):
            path = team_registry.team_path(self.root, team_id)
            with io.open(path, 'rb') as f:
                data = f.read()
            with io.open(path, 'wb') as f:
                f.write(data.replace(b'\n', b'\r\n'))
        self.assertEqual(rnd.read_teams(self.root)['A'], rnd.read_team_file(TEAM_A))  # the sha256 is of the text, CRLF as LF
        self.assertEqual(rnd.check_teams([('B', None), ('C', None)], root=self.root), ())

    def test_a_registry_file_that_changed_since_the_run_was_set_up_is_refused(self):
        self.add('MC405', read_text(TEAM_A))
        teams = rnd.check_teams([('MC405', None)], root=self.root)
        rnd.read_teams(self.root, teams)
        with io.open(team_registry.team_path(self.root, 'MC405'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(read_text(TEAM_A).replace('Adamant Nature', 'Jolly Nature', 1))
        with self.assertRaises(driver.ToolError) as cm:
            rnd.read_teams(self.root, teams)
        self.assertIn('a team never changes under its id', str(cm.exception))  # the index says what the file must be
        with self.assertRaises(ValueError):
            rnd.check_teams([('MC405', None)], root=self.root)  # and the command line refuses it as well

    def test_the_command_line_with_ids(self):
        parser = driver_parser()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'dist', 'sim'))
            exe = os.path.abspath(__file__)
            base_args = ['random', '--checkout', tmp, '--runner', exe, '--battles', '4', '--seed', '1', '--node', exe]

            def refused(*extra):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                    rnd.validate(parser, parser.parse_args(base_args + list(extra)))
                self.assertEqual(cm.exception.code, 2)
                return err.getvalue()

            # A, B and C are always there: the option adds no team, and a chunk is told it as it is.
            args = parser.parse_args(base_args + ['--team', 'a', '--team', 'C', '--pairings', 'AC,CA'])
            params = rnd.validate(parser, args)
            self.assertEqual((params.pairings, params.teams), (('AC', 'CA'), None))
            forwarded = rnd.forwarded(args, '/out')
            self.assertEqual([forwarded[i + 1] for i, v in enumerate(forwarded) if v == '--team'], ['A', 'C'])
            # An id that the registry does not have is refused, with the ids it has, before anything is played.
            message = refused('--team', 'MC999')
            self.assertIn('no team MC999 in the registry', message)
            self.assertIn('ids are A, B, C', message)
            self.assertIn('by its id', refused('--team', 'mc-999'))
            # A pairing with an id that is no team of the run is refused as every other pairing that is none.
            self.assertIn('pairings are some of', refused('--pairings', 'A-MC405'))
            # A team of the registry that is not A, B or C: by its id in the chunk, not by a path.
            team = rnd.Team('MC405', '/registry/MC405.txt', 'closure', 'f' * 64)
            with mock.patch.object(rnd, 'check_teams', lambda options, *rest, **kwargs: (team,)):
                args = parser.parse_args(base_args + ['--team', 'mc405', '--pairings', 'a-mc405,MC405-A'])
                params = rnd.validate(parser, args)
            self.assertEqual((params.pairings, params.teams), (('A-MC405', 'MC405-A'), (team,)))
            self.assertEqual(rnd.run_parameters(params)['teams'], {'MC405': {'sha256': 'f' * 64, 'data': 'closure'}})
            forwarded = rnd.forwarded(args, '/out')
            self.assertEqual(forwarded[forwarded.index('--team') + 1], 'MC405')
            self.assertEqual(forwarded[forwarded.index('--pairings') + 1], 'a-mc405,MC405-A')


# ------------------------------------------------------------ the pieces a corpus is made from

class Kept(unittest.TestCase):
    """--keep-traces: the spec and the trace of every PASS battle, for `promote` to choose coverage from."""

    def test_pass_battles_are_kept_and_the_others_have_their_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            for keep in (False, True):
                outdir = os.path.join(tmp, 'keep' if keep else 'no')
                world = World(scenario=scenario_of)
                make_worker = lambda: WorldWorker(world)
                rnd.run_chunk(PARAMS, outdir, 0, None, make_worker, lambda: WorldRunner(world), tables, KINDS,
                              world.spec_for, 2, out=io.StringIO(), keep_traces=keep)
                records = [rnd.read_partial(outdir, i)['record'] for i in range(PARAMS.battles)]
                passed = sorted(r['name'] for r in records if r['bucket'] == 'PASS')
                self.assertEqual(passed, sorted('fz_1_%d' % i for i in range(0, 24, 6)))
                if not keep:
                    self.assertFalse(os.path.exists(os.path.join(outdir, 'kept')))
                    continue
                self.assertEqual(sorted(os.listdir(os.path.join(outdir, 'kept'))), passed)
                for name in passed:
                    files = sorted(os.listdir(os.path.join(outdir, 'kept', name)))
                    self.assertEqual(files, ['spec.json', 'trace.json.gz'])  # no case for a PASS, no temporary file
                    with io.open(os.path.join(outdir, 'kept', name, 'spec.json'), encoding='utf-8') as f:
                        spec = json.load(f)
                    with gzip.open(os.path.join(outdir, 'kept', name, 'trace.json.gz')) as f:
                        trace = json.loads(f.read().decode('utf-8'))
                    self.assertEqual((spec['name'], len(spec['choices'])), (name, len(trace['steps'])))
                    self.assertEqual(spec['choices'], [step['input'] for step in trace['steps']])
                self.assertTrue(set(os.listdir(os.path.join(outdir, 'cases'))).isdisjoint(passed))  # a PASS has no case

    def test_the_step_at_which_the_converter_refuses_a_trace(self):
        world = World()
        spec = copy.deepcopy(world.spec_for(0)[0])
        trace = copy.deepcopy(world.trace)
        trace['steps'][2]['log'].append('|foo|bar')
        result = driver.oracle_gap('x', self.refusal_of(spec, trace))
        self.assertEqual(rnd.refusing_step('x', spec, trace, tables, result), 2)  # the first step that is refused, not the last
        trace['steps'][4]['log'].append('|baz|qux')  # a later refusal of its own does not move it
        self.assertEqual(rnd.refusing_step('x', spec, trace, tables, result), 2)
        # An error of the converter that is not a refusal of a rule (a KeyError of a lookup) has its step too.
        trace = copy.deepcopy(world.trace)
        del trace['steps'][3]['state']['sides'][0]['pokemon'][0]['hp']
        error = self.refusal_of(spec, trace)
        self.assertIsInstance(error, KeyError)
        self.assertEqual(rnd.refusing_step('x', spec, trace, tables, driver.oracle_gap('x', error)), 3)
        # A result that the cuts do not make again (another rule) has no step.
        other = driver.new_result('x', 'ORACLE_GAP', rule='something-else', detail='x')
        self.assertIsNone(rnd.refusing_step('x', spec, trace, tables, other))

    def refusal_of(self, spec, trace):
        try:
            trace_to_c.convert_battle('x', spec, trace, tables(False))
        except (trace_to_c.ConversionError, KeyError, IndexError, ValueError, TypeError) as e:
            return e
        raise AssertionError('the converter did not refuse the trace')


# ------------------------------------------------------------ the real runner

@unittest.skipUnless(RUNNER, 'DUOFORGE_DIFF_RUNNER is not set (CTest sets it to the runner it builds)')
class RealRunner(unittest.TestCase):
    """The pipeline with the real runner and converter; only the reference is a committed battle."""

    def process_outcome(self, battle, scenario=None):
        world = World(battle, scenario)
        runner = driver.DiffRunner(RUNNER)
        self.addCleanup(runner.kill)
        worker = WorldWorker(world)
        return rnd.process_random(0, PARAMS, worker, runner, tables, KINDS, world.spec_for, rnd.collections.defaultdict(float))

    def process(self, battle, scenario=None):
        return self.process_outcome(battle, scenario).record

    # The domain: at team preview Showdown accepts the 360 ordered picks of four of six, and so does the engine.
    def team_samples(self, battle, leave_out=()):
        accepted = [t for t in ALL_TEAM_TEXTS if t not in leave_out]
        return lambda i: {'samples': [{'step': 0, 'side': side, 'accepted': accepted} for side in (0, 1)]}

    def test_the_domain_at_team_preview_is_the_same_set_for_the_engine_and_the_reference(self):
        outcome = self.process_outcome(REAL, self.team_samples(REAL))
        r = outcome.record
        self.assertEqual((r['bucket'], r['domain'], r['messages']), ('PASS', {'samples': 2, 'request_changed': 0}, []))
        self.assertEqual(len(outcome.domain[0]['choices']), 360)

    def test_a_pick_that_showdown_does_not_accept_is_engine_only_end_to_end(self):
        played = World(REAL).trace['steps'][0]['input']['p1']
        left_out = next(t for t in ALL_TEAM_TEXTS if t != played)
        outcome = self.process_outcome(REAL, self.team_samples(REAL, [left_out]))
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['reproduces']), ('DIVERGENCE', 0, True))
        self.assertEqual(r['detail'], 'domain: engine-only 1, reference-only 0 (step 0 side 0)')
        self.assertEqual(len(r['messages']), 1)
        self.assertEqual(r['messages'][0], '  fz_1_0 step 0: domain side 0 engine-only: ' + rnd.format_choice(
            ('team', tuple(int(c) - 1 for c in left_out[len('team '):]))))
        self.assertEqual(rnd.signature(r), ('domain', 'engine-only team, reference-only -'))
        domain = json.loads(rnd.case_files(outcome)['domain.json'].decode('utf-8'))
        self.assertEqual((domain['step'], domain['side'], len(domain['accepted'])), (0, 0, 359))
        self.assertNotIn(left_out, [a['text'] for a in domain['accepted']])

    def test_a_choice_that_the_engine_does_not_offer_is_reference_only_end_to_end(self):
        world = World(REAL)
        # Switching to the two Pokemon in the field: Showdown would not accept it, and the engine does not offer it.
        scenario = lambda i: {'samples': [world.sample_of(1, 0, ['switch 1, switch 2'])]}
        outcome = self.process_outcome(REAL, scenario)
        r = outcome.record
        self.assertEqual((r['bucket'], r['step'], r['reproduces']), ('DIVERGENCE', 1, True))
        self.assertRegex(r['detail'], r'^domain: engine-only [1-9]\d*, reference-only 1 \(step 1 side 0\)$')
        self.assertTrue(any(re.match(r'^  fz_1_0 step 1: domain side 0 reference-only: slots switch \d, switch \d$', m)
                            for m in r['messages']), r['messages'])
        # The set has the played choice and the lie: the engine offers many more, of which three are shown.
        self.assertEqual(len([m for m in r['messages'] if 'engine-only' in m]), 3)
        self.assertEqual(rnd.signature(r)[0], 'domain')

    def test_real_teams_pass_under_the_strict_kinds(self):
        r = self.process(REAL)
        self.assertEqual((r['bucket'], r['context'], r['ended'], r['reproduces']), ('PASS', 'CLOSURE', True, None))
        r = self.process(REAL_TEAM_C)
        self.assertEqual((r['bucket'], r['context'], r['ended']), ('PASS', 'TEAM_C', True))
        r = self.process(REAL_POOL)  # a pool battle runs under POOL alone: U-turn is not in the TEAM_C tables
        self.assertEqual((r['bucket'], r['context'], r['ended']), ('PASS', 'POOL', True))

    def test_sets_that_need_the_dev_context_are_a_finding_not_a_fallback(self):
        r = self.process(DEV)
        self.assertEqual((r['bucket'], r['step'], r['context'], r['reproduces']), ('DIVERGENCE', None, 'CLOSURE', None))
        self.assertRegex(r['detail'], r'^create: DUOFORGE_E_\w+ \(CLOSURE\)$')
        self.assertEqual(rnd.signature(r)[0], 'create')

    def test_a_battle_cut_short_is_a_cap_that_reproduces(self):
        r = self.process(REAL, lambda i: {'steps': 6})
        self.assertEqual((r['bucket'], r['steps'], r['ended'], r['step'], r['reproduces']), ('CAP', 6, False, None, True))

    def test_a_difference_at_a_step_is_a_divergence_with_its_prefix(self):
        def corrupt(trace, prefix):
            mon = trace['steps'][3]['state']['sides'][0]['pokemon'][0]
            mon['hp'] += 1
        r = self.process(REAL, lambda i: {'mutate': corrupt})
        self.assertEqual((r['bucket'], r['step'], r['ended'], r['reproduces']), ('DIVERGENCE', 3, True, True))
        self.assertIn(' hp ', ' '.join(r['messages']))
        self.assertEqual(rnd.signature(r)[0], 'state')

    def test_a_difference_that_the_prefix_does_not_show_is_not_reproduced(self):
        def corrupt(trace, prefix):
            if not prefix:
                trace['steps'][3]['state']['sides'][0]['pokemon'][0]['hp'] += 1
        r = self.process(REAL, lambda i: {'mutate': corrupt})
        self.assertEqual((r['bucket'], r['step'], r['reproduces']), ('DIVERGENCE', 3, False))


if __name__ == '__main__':
    unittest.main()
