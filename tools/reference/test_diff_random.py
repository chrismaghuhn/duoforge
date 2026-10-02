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
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_driver as driver  # noqa: E402
import diff_random as rnd  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RUNNER = os.environ.get('DUOFORGE_DIFF_RUNNER')
VERSION = {'node': 'v0.0.0', 'pin': '0' * 40, 'harness': 14}
KINDS = conformance_records.data_kinds(ROOT)
PARAMS = rnd.Params(1, 24, rnd.DEFAULT_PAIRINGS, 300, 0.1, 0.5)
REAL = 'm5_real_aa_1'  # real teams of team A, ends: a PASS under CLOSURE
REAL_TEAM_C = 'c01_team_c_profile'  # six real members, ends: a PASS under TEAM_C
DEV = 's3_struggle_end'  # sets without an ability, ends: needs CLOSURE_DEV

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


# ------------------------------------------------------------ a committed battle as the reference

class World:
    """What the reference does, as one committed battle: play answers the choices of its trace, record answers its
    trace cut to the choices it is given. scenario(index) says what goes wrong for battle `index`: a dict with
    'steps' (a play that stops there, the battle not over), 'play_error', 'record_error' (exceptions),
    'mutate' (changes the trace: mutate(trace, is_prefix)) and 'runner' (a function of (steps, is_prefix) that
    answers instead of the runner saying PASS)."""

    def __init__(self, battle=REAL, scenario=None, seed=1):
        spec, text = driver.load_committed(ROOT, battle)
        self.spec = spec
        self.trace = json.loads(text)
        self.seed = seed
        self.scenario = scenario or (lambda index: {})

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
                'steps': steps}

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
        self.assertEqual(policy, {'seed': 1005, 'max_steps': 300, 'switch_weight': 0.1, 'mega_weight': 0.5})

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
        self.assertEqual(sorted(files), ['messages.txt', 'spec.json', 'trace.json.gz'])  # the trace the converter refused
        self.assertEqual(files['messages.txt'].decode('utf-8').split('\n')[:2],
                         ['ORACLE_GAP | protocol-line | foo', "trace_to_c: unknown protocol line '|foo|bar'"])

    def test_a_case_is_written_to_a_directory_of_its_name(self):
        outcome = self.outcome_with_divergence()
        with tempfile.TemporaryDirectory() as tmp:
            rnd.write_case(tmp, 'fz_1_0', rnd.case_files(outcome))
            self.assertEqual(sorted(os.listdir(os.path.join(tmp, 'cases', 'fz_1_0'))), sorted(rnd.case_files(outcome)))
            self.assertEqual([f for f in os.listdir(os.path.join(tmp, 'cases', 'fz_1_0')) if f.endswith('.tmp')], [])


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
                                (PARAMS._replace(switch_weight=0.2), 'policy')):
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
        reply.update(choices=choices, ended=True, steps=len(choices))
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
                                (['--start', '10'], 'is not before --battles')):
                with self.subTest(extra):
                    # The option is given twice, and the later one wins (argparse).
                    self.assertIn(part, self.refused(*(base_args + extra)))
            self.assertIn('is not a file', self.refused(*(base_args + ['--runner', exe + '.none'])))
            self.assertIn('has no dist/sim', self.refused(*(base_args + ['--checkout', ROOT])))
            parser, args = self.parse(*base_args)
            params = rnd.validate(parser, args)
            self.assertEqual(params, rnd.Params(1, 10, rnd.DEFAULT_PAIRINGS, 300, 0.1, 0.5))
            parser, args = self.parse(*(base_args + ['--pairings', 'ab,cc', '--max-steps', '50', '--switch-weight', '0.3',
                                                     '--mega-weight', '1']))
            self.assertEqual(rnd.validate(parser, args), rnd.Params(1, 10, ('AB', 'CC'), 50, 0.3, 1.0))
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
                '--out', '/out/dir', '--max-steps', '300', '--switch-weight', '0.25', '--mega-weight', '0.5', '--node', 'node'])
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


# ------------------------------------------------------------ the real runner

@unittest.skipUnless(RUNNER, 'DUOFORGE_DIFF_RUNNER is not set (CTest sets it to the runner it builds)')
class RealRunner(unittest.TestCase):
    """The pipeline with the real runner and converter; only the reference is a committed battle."""

    def process(self, battle, scenario=None):
        world = World(battle, scenario)
        runner = driver.DiffRunner(RUNNER)
        self.addCleanup(runner.kill)
        worker = WorldWorker(world)
        outcome = rnd.process_random(0, PARAMS, worker, runner, tables, KINDS, world.spec_for, rnd.collections.defaultdict(float))
        return outcome.record

    def test_real_teams_pass_under_the_strict_kinds(self):
        r = self.process(REAL)
        self.assertEqual((r['bucket'], r['context'], r['ended'], r['reproduces']), ('PASS', 'CLOSURE', True, None))
        r = self.process(REAL_TEAM_C)
        self.assertEqual((r['bucket'], r['context'], r['ended']), ('PASS', 'TEAM_C', True))

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
