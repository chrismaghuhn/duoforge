#!/usr/bin/env python3
"""The corpus tooling (tools/reference/diff_corpus.py) without Node and without a Showdown checkout.

usage: python3 tools/reference/test_diff_corpus.py

CTest runs it as duoforge.reference.diff_corpus, with DUOFORGE_DIFF_RUNNER set to the runner it has built. Committed
battles stand in for what the fuzz plays and what the reference records again; the converter is real, and the runner is
a fake or, with DUOFORGE_DIFF_RUNNER, the real one. What is tested: the signatures (the coverage of gen_real_specs step by
step, and the request situations), the greedy choice and the cut, the layout checks of the corpus directory, the replay
of a corpus through the converter and the runner (and what it says of a battle that fails), and promote (coverage and
defects, with what it refuses). The real corpus is held by test_corpus_layout.py and the corpus mode itself.
"""
import collections
import contextlib
import copy
import io
import json
import os
import random
import re
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_corpus as corpus_tools  # noqa: E402
import diff_driver as driver  # noqa: E402
import diff_random as rnd  # noqa: E402
import gen_real_specs  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RUNNER = os.environ.get('DUOFORGE_DIFF_RUNNER')
KINDS = conformance_records.data_kinds(ROOT)
PURPOSE = 'Corpus (coverage): a battle of the tests of the corpus tooling, kept for what it adds to the signatures.'

_tables = {}


def tables(team_c):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def committed(name):
    """(spec, trace) of a committed battle."""
    spec, text = driver.load_committed(ROOT, name)
    return spec, json.loads(text)


def entry_of(name, purpose=PURPOSE, as_name=None):
    """(spec, trace text) of a corpus entry made from committed battle `name`: its choices spec and its trace, with what a
    recording of that spec says (its own name as the spec file)."""
    as_name = as_name or name
    spec, trace = committed(name)
    trace['spec'] = as_name + '.json'
    out = {'name': as_name, 'purpose': purpose}
    if 'data' in spec:
        out['data'] = spec['data']
    out.update({'format': spec['format'], 'seed': spec['seed'], 'teams': spec['teams'],
                'choices': [step['input'] for step in trace['steps']]})
    return out, json.dumps(trace, indent=1) + '\n'


def write_entry(corpus, name, spec, text):
    os.makedirs(corpus, exist_ok=True)
    with io.open(corpus_tools.spec_path(corpus, name), 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(spec, indent=2) + '\n')
    with io.open(corpus_tools.trace_path(corpus, name), 'wb') as f:
        f.write(rnd.gzipped(text))


def made(corpus, *names, **kw):
    """A corpus directory of committed battles `names`."""
    for name in names:
        spec, text = entry_of(name, **kw)
        write_entry(corpus, name, spec, text)
    return corpus


# ------------------------------------------------------------ signatures

def side(request, enabled=(), active=(0, 1), **mon):
    """One side of a made-up state: what the request situations read of it."""
    return {'request': request, 'enabled': [list(row) for row in enabled], 'active': list(active),
            'pokemon': [dict({'locked': None, 'choice': None}, **mon) for _ in range(2)]}


def request_made_in(before, inputs, previous_log=()):
    """The trace of two steps whose second answers, with `inputs`, a request made in the state `before` (a pair of sides)
    after a step that wrote `previous_log`; the situations of that second step."""
    first = {'input': {}, 'draws': [], 'log': list(previous_log), 'state': {'sides': list(before)}}
    second = {'input': inputs, 'draws': [], 'log': [], 'state': {'sides': list(before)}}
    return corpus_tools.situations({'start': {'state': {'sides': list(before)}}, 'steps': [first, second]}, 1)


class Signatures(unittest.TestCase):
    def test_a_battle_has_the_features_of_gen_real_specs_step_by_step(self):
        """The union of the features of the steps is gen_real_specs.features of the battle, in every committed battle
        that ended (features() takes only those)."""
        compared = 0
        for name in driver.spec_names(ROOT):
            trace = committed(name)[1]
            whole = gen_real_specs.features(trace)
            if whole is None:
                continue
            union = set()
            for entry in trace['steps']:
                union |= corpus_tools.step_features(entry)
            self.assertEqual(union, whole, name)
            compared += 1
        self.assertGreater(compared, 100)

    def test_a_battle_that_does_not_end_has_features_too(self):
        trace = committed('d01_noguard_accuracy_tie')[1]
        self.assertIsNone(gen_real_specs.features(trace))  # features() wants a battle that ended
        first = corpus_tools.trace_signatures(trace)
        self.assertTrue(first)
        self.assertNotIn('win', first)
        self.assertNotIn('tie', first)  # what the step that ends the battle adds is taken away again

    def test_a_tie_of_the_battle_itself_stays(self):
        self.assertEqual(corpus_tools.step_features({'draws': [], 'log': ['|tie|']}), frozenset({'tie'}))
        self.assertEqual(corpus_tools.step_features({'draws': [], 'log': ['|move|p1a: A|Tackle|p2a: B']}),
                         frozenset({'move:Tackle'}))

    def test_a_draw_without_a_site_is_not_a_trace_to_keep(self):
        unknown = {'site': 'UNKNOWN', 'context': 'x', 'lo': 0, 'hi': 2, 'value': 1}
        entry = {'draws': [unknown, {'site': 'CRIT', 'context': '', 'lo': 0, 'hi': 24, 'value': 3}], 'log': []}
        self.assertIsNone(corpus_tools.step_features(entry))
        self.assertEqual(corpus_tools.step_features(entry, lenient=True), frozenset({'draw:CRIT:'}))
        trace = copy.deepcopy(committed('m5_real_aa_1')[1])
        trace['steps'][1]['draws'].append(unknown)
        self.assertIsNone(corpus_tools.trace_signatures(trace))
        self.assertTrue(corpus_tools.trace_signatures(trace, lenient=True))  # the committed ones are counted as they are

    def test_the_first_step_of_each_signature(self):
        trace = committed('d02_electro_shot_lock_emergency_exit')[1]
        first = corpus_tools.trace_signatures(trace)
        self.assertEqual((first['request:teampreview'], first['request:turn:mega'], first['request:turn:switch']), (0, 1, 1))
        self.assertEqual(first['request:turn'], 2)
        # The charge of Electro Shot on step 2 and its locked turn on step 3, in which Emergency Exit switches a Pokemon out.
        self.assertEqual((first['move:Electro Shot[still]'], first['move:Electro Shot[from] lockedmove']), (2, 3))
        self.assertEqual((first['-activate:ability: Emergency Exit'], first['request:turn:locked-twoturn']), (3, 3))
        self.assertEqual(max(first.values()), 3)  # four steps, the last of them the first of some

    def test_the_request_situations_of_a_battle(self):
        trace = committed('s12_parting_shot')[1]
        self.assertEqual([sorted(corpus_tools.situations(trace, k)) for k in range(5)], [
            ['request:teampreview'], ['request:turn'], ['request:pivot:pass'], ['request:replacement:pass'],
            ['request:turn', 'request:turn:switch']])  # a Parting Shot, its pivot, the replacement and a switch
        trace = committed('d02_electro_shot_lock_emergency_exit')[1]
        self.assertEqual([sorted(corpus_tools.situations(trace, k)) for k in range(4)], [
            ['request:teampreview'], ['request:turn:mega', 'request:turn:switch'], ['request:turn'],
            ['request:turn', 'request:turn:locked-twoturn']])

    def test_each_flag_of_a_request(self):
        both = (side('move'), side('move'))
        cases = (
            ('team preview', (side('teampreview'), side('teampreview')), {'p1': 'team 1234', 'p2': 'team 1234'},
             ['request:teampreview']),
            ('a plain turn', both, {'p1': 'move 1, move 1', 'p2': 'move 2 1, move 3'}, ['request:turn']),
            ('mega and a switch', both, {'p1': 'move 1, move 1 mega', 'p2': 'move 2 1, switch 3'},
             ['request:turn:mega', 'request:turn:switch']),
            ('struggle', (side('move', enabled=[[2], [1]]), side('move')), {'p1': 'move 1, move 1', 'p2': 'move 1, move 1'},
             ['request:turn', 'request:turn:struggle']),
            ('a disabled move', (side('move', enabled=[[1, 0], [1, 1]]), side('move')),
             {'p1': 'move 1, move 1', 'p2': 'move 1, move 1'}, ['request:turn', 'request:turn:disabled-move']),
            ('both kinds of lock', (side('move', locked=[1, 2]), side('move', choice=0)),
             {'p1': 'move 1, move 1', 'p2': 'move 1, move 1'},
             ['request:turn:locked-twoturn', 'request:turn:locked-choice']),
            ('a slot that passes', (side('move'), side('move', active=(0, -1))), {'p1': 'move 1, move 1', 'p2': 'move 1, pass'},
             ['request:turn', 'request:turn:pass']),
            ('a replacement', (side('switch'), side('wait')), {'p1': 'switch 3'}, ['request:replacement']),
            ('a replacement that passes', (side('switch'), side('wait')), {'p1': 'switch 3, pass'},
             ['request:replacement:pass']))
        for label, before, inputs, want in cases:
            with self.subTest(label):
                # After the residual: the end of the turn, so a switch request is a replacement.
                self.assertEqual(request_made_in(before, inputs, ('|upkeep',)), set(want))
        # The flags of a request are one signature, sorted: the same situation is the same string.
        found = request_made_in((side('move', enabled=[[0]], locked=[0, 1]), side('move')),
                                {'p1': 'move 1, move 1 mega', 'p2': 'move 1, move 1'})
        self.assertEqual(found, {'request:turn:disabled-move+locked-twoturn+mega', 'request:turn'})

    def test_a_pivot_is_a_switch_request_in_the_middle_of_the_turn(self):
        before = (side('switch'), side('wait'))
        self.assertEqual(request_made_in(before, {'p1': 'switch 3, pass'}), {'request:pivot:pass'})  # no upkeep before it
        self.assertEqual(request_made_in(before, {'p1': 'switch 3, pass'}, ('|upkeep',)), {'request:replacement:pass'})
        self.assertEqual(request_made_in(before, {'p1': 'switch 3'}), {'request:pivot'})

    def test_every_committed_battle_has_signatures_and_the_union_is_what_is_covered(self):
        covered = corpus_tools.committed_signatures(ROOT)
        self.assertGreater(len(covered), 300)
        categories = collections.Counter(corpus_tools.category(s) for s in covered)
        self.assertTrue(all(categories[c] for c in ('draw', 'request', 'line')), categories)
        self.assertLessEqual(set(corpus_tools.trace_signatures(committed('c11_follow_me')[1])), covered)


# ------------------------------------------------------------ the greedy choice

def naive_greedy(candidates, covered, limit=None):
    """The same choice without the heap: measure every battle against what is covered, take the best, again."""
    covered, chosen, left = set(covered), [], dict(candidates)
    while left and (limit is None or len(chosen) < limit):
        gains = {key: [s for s in first if s not in covered] for key, first in left.items()}
        best = min(left, key=lambda key: (-len(gains[key]), key))
        if not gains[best]:
            break
        step = max(left[best][s] for s in gains[best])
        chosen.append((best, sorted(gains[best]), step))
        covered.update(s for s, k in left[best].items() if k <= step)
        del left[best]
    return chosen


class Greedy(unittest.TestCase):
    def test_the_battle_that_adds_most_goes_first_and_is_cut_where_it_stops_adding(self):
        candidates = {1: {'a': 0, 'b': 4}, 2: {'b': 1, 'c': 2, 'd': 9}, 3: {'a': 0}, 4: {'e': 3}}
        # 2 adds three (b, c, d), cut after its last new one (step 9); then 1 adds a only (b is covered by 2), cut at 0;
        # then 4 adds e; 3 adds nothing after 1.
        self.assertEqual(corpus_tools.greedy(candidates, set()), [(2, ['b', 'c', 'd'], 9), (1, ['a'], 0), (4, ['e'], 3)])

    def test_what_is_covered_already_is_not_added_and_does_not_move_the_cut(self):
        # y is covered: 1 adds only x (step 0) and is cut there, though its y is at step 7; 2 adds nothing.
        self.assertEqual(corpus_tools.greedy({1: {'x': 0, 'y': 7}, 2: {'y': 3}}, {'y'}), [(1, ['x'], 0)])

    def test_a_tie_goes_to_the_lower_key(self):
        self.assertEqual(corpus_tools.greedy({7: {'a': 0}, 3: {'b': 0}, 5: {'c': 0}}, set())[0][0], 3)
        self.assertEqual([c[0] for c in corpus_tools.greedy({7: {'a': 0}, 3: {'a': 0}}, set())], [3])
        self.assertEqual([c[0] for c in corpus_tools.greedy({1: {'x': 0, 'q': 5, 'y': 7}, 2: {'q': 1, 'y': 3, 'r': 4}}, set())],
                         [1, 2])  # both add three: 1 first, then 2 adds only r

    def test_it_stops_when_nothing_is_added_or_at_the_limit(self):
        candidates = {1: {'a': 0}, 2: {'b': 0}, 3: {'c': 0}}
        self.assertEqual(len(corpus_tools.greedy(candidates, set())), 3)
        self.assertEqual(len(corpus_tools.greedy(candidates, set(), limit=2)), 2)
        self.assertEqual(corpus_tools.greedy(candidates, {'a', 'b', 'c'}), [])
        self.assertEqual(corpus_tools.greedy({}, set()), [])
        self.assertEqual(corpus_tools.greedy({1: {}}, set()), [])  # a battle with no signature adds none

    def test_it_is_the_choice_of_the_plain_greedy_algorithm_and_covers_everything_it_can(self):
        rng = random.Random(7)
        for trial in range(300):
            universe = ['s%d' % i for i in range(rng.randint(1, 30))]
            candidates = {k: {s: rng.randint(0, 12) for s in rng.sample(universe, rng.randint(0, len(universe)))}
                          for k in rng.sample(range(100), rng.randint(0, 25))}
            covered = set(rng.sample(universe, rng.randint(0, len(universe))))
            limit = rng.choice([None, 1, 3, 10])
            with self.subTest(trial=trial):
                chosen = corpus_tools.greedy(candidates, covered, limit)
                self.assertEqual(chosen, naive_greedy(candidates, covered, limit))
                if limit is None:  # without a limit, what the candidates can give is covered: nothing is left out
                    union = set().union(*[set(first) for first in candidates.values()]) if candidates else set()
                    self.assertEqual(covered | {s for _, new, _ in chosen for s in new}, covered | union)

    def test_the_cut_is_the_latest_first_step_of_what_it_adds(self):
        self.assertEqual(corpus_tools.cut_step({'a': 2, 'b': 9, 'c': 5}, ['a', 'c']), 5)
        self.assertEqual(corpus_tools.cut_step({'a': 0}, ['a']), 0)


# ------------------------------------------------------------ the layout of the directory

class Layout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.corpus = os.path.join(self.tmp.name, 'corpus')

    def problems(self, **kw):
        return corpus_tools.layout_problems(ROOT, self.corpus, **kw)

    def test_a_corpus_as_it_must_be(self):
        made(self.corpus, 'm5_real_aa_1', 'c01_team_c_profile')
        self.assertEqual(self.problems(), [])
        self.assertEqual(corpus_tools.listing(self.corpus), (['c01_team_c_profile', 'm5_real_aa_1'],
                                                             ['c01_team_c_profile', 'm5_real_aa_1'], []))
        self.assertGreater(corpus_tools.corpus_bytes(self.corpus), 1000)

    def test_a_directory_with_nothing_in_it_is_no_corpus(self):
        self.assertEqual([c for c, _ in self.problems()], ['empty'])
        os.makedirs(self.corpus)
        self.assertEqual([c for c, _ in self.problems()], ['empty'])

    def test_a_spec_and_its_trace_stand_together(self):
        made(self.corpus, 'm5_real_aa_1', 'c01_team_c_profile')
        os.remove(corpus_tools.trace_path(self.corpus, 'm5_real_aa_1'))
        os.remove(corpus_tools.spec_path(self.corpus, 'c01_team_c_profile'))
        found = self.problems()
        self.assertEqual(sorted(found), [('orphan', 'c01_team_c_profile has a trace and no spec'),
                                         ('orphan', 'm5_real_aa_1 has a spec and no trace')])

    def test_nothing_else_is_there(self):
        made(self.corpus, 'm5_real_aa_1')
        for fname in ('README.md', 'm5_real_aa_1.json.bak', 'x.gz'):
            with io.open(os.path.join(self.corpus, fname), 'w') as f:
                f.write('x')
        found = self.problems()
        self.assertEqual([c for c, _ in found], ['files', 'files', 'files'])
        self.assertTrue(all('neither a <name>.json spec' in m for _, m in found))

    def test_the_name_is_one_the_records_hold(self):
        spec, text = entry_of('m5_real_aa_1')
        write_entry(self.corpus, 'bad-name', dict(spec, name='bad-name'), text)
        write_entry(self.corpus, 'x' * 64, dict(spec, name='x' * 64), text)
        self.assertEqual([c for c, m in self.problems() if 'letters, digits' in m], ['files', 'files'])

    def test_the_purpose_says_why(self):
        for purpose in (None, '', 'a battle', 'Corpus (coverage): short', 'Coverage corpus battle with a long purpose that '
                        'does not start the way the purposes do, so it says nothing the tests can read', 7):
            with self.subTest(purpose=purpose):
                spec, text = entry_of('m5_real_aa_1')
                if purpose is None:
                    del spec['purpose']
                else:
                    spec['purpose'] = purpose
                write_entry(self.corpus, 'm5_real_aa_1', spec, text)
                self.assertEqual([c for c, _ in self.problems()], ['purpose'])
        for purpose in ('Corpus (defect): ' + 'found as a DIVERGENCE and fixed, the shortest prefix of it. ' * 2, PURPOSE):
            spec, text = entry_of('m5_real_aa_1', purpose=purpose)
            write_entry(self.corpus, 'm5_real_aa_1', spec, text)
            self.assertEqual(self.problems(), [])

    def test_the_spec_is_a_choices_spec_of_its_name(self):
        spec, text = entry_of('m5_real_aa_1')
        for change, part in ((lambda s: s.update(name='other'), "its name is 'other'"), (lambda s: s.pop('seed'), 'no seed'),
                             (lambda s: s.pop('choices'), 'no choices'), (lambda s: s.update(plan={}), 'has its choices, not a plan'),
                             (lambda s: s.update(data='pool'), "data 'pool'")):
            with self.subTest(part):
                changed = copy.deepcopy(spec)
                change(changed)
                write_entry(self.corpus, 'm5_real_aa_1', changed, text)
                found = self.problems()
                self.assertTrue(any(c == 'spec' and part in m for c, m in found), found)

    def test_the_trace_is_the_recording_of_the_spec_at_this_pin(self):
        spec, text = entry_of('m5_real_aa_1')
        trace = json.loads(text)
        pin, harness = corpus_tools.harness_constants(ROOT)
        self.assertEqual((trace['pin'], trace['harness']), (pin, harness))
        for change, part in ((lambda t: t.update(pin='0' * 40), 'recorded at pin'), (lambda t: t.update(harness=harness + 1), 'harness'),
                             (lambda t: t.update(spec='other.json'), "its trace is of the spec 'other.json'"),
                             (lambda t: t['steps'].pop(), 'choices and'), (lambda t: t.update(seed='x'), 'its seed'),
                             (lambda t: t['steps'][1]['input'].update(p1='move 4'), 'not what the trace answers')):
            with self.subTest(part):
                changed = copy.deepcopy(trace)
                change(changed)
                write_entry(self.corpus, 'm5_real_aa_1', spec, json.dumps(changed))
                found = self.problems()
                self.assertTrue(any(c == 'trace' and part in m for c, m in found), found)

    def test_a_file_that_cannot_be_read(self):
        spec, text = entry_of('m5_real_aa_1')
        write_entry(self.corpus, 'm5_real_aa_1', spec, text)
        with io.open(corpus_tools.trace_path(self.corpus, 'm5_real_aa_1'), 'wb') as f:
            f.write(b'this is not gzip')
        self.assertEqual([c for c, _ in self.problems()], ['trace'])
        with io.open(corpus_tools.trace_path(self.corpus, 'm5_real_aa_1'), 'wb') as f:
            f.write(rnd.gzipped(text)[:40])  # cut: the end of the stream is missing
        self.assertEqual([c for c, _ in self.problems()], ['trace'])
        write_entry(self.corpus, 'm5_real_aa_1', spec, text)
        with io.open(corpus_tools.spec_path(self.corpus, 'm5_real_aa_1'), 'w') as f:
            f.write('{"name"')
        self.assertEqual([c for c, _ in self.problems()], ['spec'])

    def test_the_cap(self):
        made(self.corpus, 'm5_real_aa_1', 'c01_team_c_profile')
        size = corpus_tools.corpus_bytes(self.corpus)
        self.assertEqual(self.problems(cap=size), [])
        found = self.problems(cap=size - 1)
        self.assertEqual([c for c, _ in found], ['size'])
        self.assertIn('over the cap of', found[0][1])
        self.assertEqual(corpus_tools.CAP_BYTES, 20 * 1024 * 1024)  # decision 0015: about 20 MB


# ------------------------------------------------------------ replay: the corpus through the converter and the runner

@unittest.skipUnless(RUNNER, 'DUOFORGE_DIFF_RUNNER is not set (CTest sets it to the runner it builds)')
class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.corpus = os.path.join(self.tmp.name, 'corpus')

    def replay(self, **kw):
        return corpus_tools.replay(ROOT, RUNNER, 2, corpus=self.corpus, **kw)

    def test_committed_battles_as_corpus_entries_all_pass_also_a_cut_that_does_not_end(self):
        # A closure battle, a Team C battle, and a cut of one: it never says CAP here.
        made(self.corpus, 'm5_real_aa_1', 'c01_team_c_profile', 'd02_electro_shot_lock_emergency_exit')
        results, summary = self.replay()
        self.assertEqual({n: r['bucket'] for n, r in results.items()},
                         {'m5_real_aa_1': 'PASS', 'c01_team_c_profile': 'PASS', 'd02_electro_shot_lock_emergency_exit': 'PASS'})
        self.assertFalse(committed('d02_electro_shot_lock_emergency_exit')[1]['steps'][-1]['state']['ended'])
        self.assertEqual((summary['mode'], summary['battles'], summary['buckets']['PASS'], summary['node']),
                         ('corpus', 3, 3, None))
        self.assertEqual(summary['pin'], corpus_tools.harness_constants(ROOT)[0])
        self.assertEqual(self.replay(names=['m5_real_aa_1'])[1]['battles'], 1)

    def test_a_battle_that_the_engine_does_not_agree_with_is_a_divergence(self):
        spec, text = entry_of('m5_real_aa_1')
        trace = json.loads(text)
        trace['steps'][3]['state']['sides'][0]['pokemon'][0]['hp'] += 1
        write_entry(self.corpus, 'm5_real_aa_1', spec, json.dumps(trace))
        made(self.corpus, 'c01_team_c_profile')
        results, summary = self.replay()
        self.assertEqual((results['m5_real_aa_1']['bucket'], results['m5_real_aa_1']['step']), ('DIVERGENCE', 3))
        self.assertEqual(results['c01_team_c_profile']['bucket'], 'PASS')
        self.assertEqual((summary['buckets']['DIVERGENCE'], summary['buckets']['PASS']), (1, 1))

    def test_a_trace_that_the_converter_refuses_is_an_oracle_gap_and_one_that_cannot_be_read_a_ref_error(self):
        spec, text = entry_of('m5_real_aa_1')
        trace = json.loads(text)
        trace['steps'][1]['log'].append('|foo|bar')
        write_entry(self.corpus, 'm5_real_aa_1', spec, json.dumps(trace))
        made(self.corpus, 'c01_team_c_profile')
        with io.open(corpus_tools.trace_path(self.corpus, 'c01_team_c_profile'), 'wb') as f:
            f.write(b'not gzip')
        results, _ = self.replay()
        self.assertEqual((results['m5_real_aa_1']['bucket'], results['m5_real_aa_1']['rule']), ('ORACLE_GAP', 'protocol-line'))
        self.assertEqual((results['c01_team_c_profile']['bucket'], results['c01_team_c_profile']['detail']),
                         ('REF_ERROR', 'cannot read the battle'))

    def test_an_empty_corpus_is_a_failure_of_the_tool_not_a_pass(self):
        os.makedirs(self.corpus)
        with self.assertRaises(corpus_tools.CorpusError):
            self.replay()

    def run_mode(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = driver.main(['corpus', '--runner', RUNNER, '--corpus', self.corpus,
                                  '--out', os.path.join(self.tmp.name, 'out'), '--workers', '2'] + list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_the_mode_says_so_and_its_status_is_that_of_the_replay(self):
        made(self.corpus, 'm5_real_aa_1', 'c01_team_c_profile')
        status, out, _ = self.run_mode()
        self.assertEqual(status, 0)
        self.assertIn('diff_driver: corpus of 2 battles: PASS 2', out)
        with io.open(os.path.join(self.tmp.name, 'out', 'summary.json'), encoding='ascii') as f:
            self.assertEqual(json.load(f)['mode'], 'corpus')
        spec, text = entry_of('m5_real_aa_1')
        trace = json.loads(text)
        trace['steps'][3]['state']['sides'][0]['pokemon'][0]['hp'] += 1
        write_entry(self.corpus, 'm5_real_aa_1', spec, json.dumps(trace))
        status, out, _ = self.run_mode()
        self.assertEqual(status, driver.EXIT_NOT_ALL_PASS)
        self.assertIn('DIVERGENCE 1', out)
        self.assertIn('m5_real_aa_1 DIVERGENCE', out)
        status, out, _ = self.run_mode('--only', 'c01_*')
        self.assertEqual((status, 'corpus of 1 battles: PASS 1' in out), (0, True))
        status, out, err = self.run_mode('--only', 'nothing_*')
        self.assertEqual(status, driver.EXIT_TOOL)
        self.assertIn('no corpus battle matches', err)


# ------------------------------------------------------------ promote

class FakeReference:
    """The reference and the engine of a promotion: a recording of a committed battle cut to the choices it is given,
    under the name it is given, and a runner that says PASS (or what `fails` says for a name)."""

    role = 'runner'

    def __init__(self, battles, fails=None):
        self.battles = battles  # {name of a battle of the run: the committed battle that stands for it}
        self.fails = fails or {}
        self.recorded = []
        self.ran = []

    def record(self, spec, spec_file):  # the worker
        self.recorded.append(spec_file)
        trace = committed(self.battles[re.sub(r'(_prefix|_cut\d+)$', '', spec['name'])])[1]
        trace['spec'] = spec_file
        trace['steps'] = trace['steps'][:len(spec['choices'])]
        return json.dumps(trace, indent=1) + '\n'

    def run(self, name, records):  # the runner
        self.ran.append(name)
        steps = int(records.split('\n', 1)[0].split(' ')[5])
        answer = self.fails.get(name, self.fails.get('*'))  # '*': whatever the name
        if answer is not None:
            return answer
        return driver.RunnerResult('PASS', 'CLOSURE', None, steps, '-', [])


def make_run(path, battles, seed=9, defects=None):
    """A run directory of the random mode: battle fz_<seed>_<i> is the committed battle battles[i], kept when it PASSes,
    with a case when `defects` ({index: (bucket, failing step or None)}) says it did not. Returns the records."""
    defects = defects or {}
    records = []
    for index, committed_name in enumerate(battles):
        name = 'fz_%d_%d' % (seed, index)
        spec, text = entry_of(committed_name, as_name=name)
        trace = json.loads(text)
        bucket, step = defects.get(index, ('PASS', None))
        record = {'index': index, 'name': name, 'pairing': 'CC' if 'data' in spec else 'AB', 'bucket': bucket, 'rule': None,
                  'detail': None, 'step': None, 'steps': len(trace['steps']), 'context': None, 'ended': True,
                  'reproduces': None, 'domain': None, 'messages': []}
        if bucket == 'DIVERGENCE':
            record.update(rule='state', detail='differences: state 1, observation 0, events 0, battle_check DUOFORGE_OK',
                          step=step, reproduces=True, messages=['  %s step %d: side 0 member 0 hp 5, reference 6' % (name, step)])
        elif bucket == 'ORACLE_GAP':
            record.update(rule='protocol-line', detail='foo', messages=["trace_to_c: unknown protocol line '|foo|bar'"])
        records.append(record)
        rnd.write_partial(path, index, record, collections.defaultdict(float))
        if bucket == 'PASS':
            rnd.write_kept(path, name, {'spec.json': rnd.dumps(spec).encode('utf-8'),
                                        'trace.json.gz': rnd.gzipped(text)})
            continue
        files = {'spec.json': rnd.dumps(spec).encode('utf-8'), 'trace.json.gz': rnd.gzipped(text), 'messages.txt': b'x\n'}
        cut_at = 1 if step is None else step  # an ORACLE_GAP: the step that the converter refuses
        cut = rnd.prefix_spec(spec, cut_at)
        files['prefix_spec.json'] = rnd.dumps(cut).encode('utf-8')
        files['prefix_result.json'] = rnd.dumps({'bucket': bucket, 'step': cut_at, 'choices': cut_at + 1,
                                                 'reproduces': True}).encode('utf-8')
        rnd.write_case(path, name, files)
    rnd.write_atomically(os.path.join(path, 'run.json'), rnd.dumps({'seed': seed}).encode('utf-8'))
    return records


class Promote(unittest.TestCase):
    BATTLES = ['m5_real_aa_1', 'm5_real_ab_1', 's2_struggle', 'c11_follow_me', 'd02_electro_shot_lock_emergency_exit']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = os.path.join(self.tmp.name, 'run')
        self.corpus = os.path.join(self.tmp.name, 'corpus')

    def reference(self, battles, fails=None):
        return FakeReference({'fz_9_%d' % i: n for i, n in enumerate(battles)}, fails)

    def promote(self, battles=None, defects=None, reference=None, fresh=True, **kw):
        """A run directory of `battles` with `defects`, promoted into the corpus: (promoted, refused, what it said,
        the reference). `fresh`: the run directory is made again (a corpus that is there stays)."""
        battles = battles or self.BATTLES
        if fresh:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            make_run(self.run_dir, battles, defects=defects)
        reference = reference or self.reference(battles)
        kw.setdefault('base_signatures', set())  # what the committed battles cover: nothing, to see what each adds
        out = io.StringIO()
        promoted, refused = corpus_tools.promote(ROOT, self.run_dir, reference, reference, tables, KINDS, corpus=self.corpus,
                                                 out=out, **kw)
        return promoted, refused, out.getvalue(), reference

    def test_coverage_battles_go_in_greedily_and_what_they_add_is_what_nobody_had(self):
        promoted, refused, out, _ = self.promote()
        self.assertEqual(refused, [])
        names = [e.name for e in promoted]
        self.assertTrue(names)
        seen = set()
        for entry in promoted:  # each adds some that no earlier one has
            self.assertEqual(entry.kind, 'coverage')
            self.assertTrue(entry.new)
            self.assertTrue(seen.isdisjoint(entry.new))
            seen.update(entry.new)
        self.assertEqual(seen, corpus_tools.corpus_signatures(self.corpus))  # what the directory covers is what they added
        self.assertEqual(corpus_tools.layout_problems(ROOT, self.corpus), [])  # a corpus as the layout test wants
        self.assertEqual(sorted(corpus_tools.listing(self.corpus)[0]), sorted(names))
        for entry in promoted:
            spec, trace = corpus_tools.read_entry(self.corpus, entry.name)
            self.assertTrue(spec['purpose'].startswith('Corpus (coverage): random differential battle '))
            self.assertIn('%d signatures' % len(entry.new), spec['purpose'])
            self.assertEqual((len(spec['choices']), len(trace['steps'])), (entry.steps, entry.steps))
            self.assertEqual(spec['choices'], [s['input'] for s in trace['steps']])
        self.assertIn('promoted %s' % names[0], out)
        # The same run again: everything that it has is covered now.
        promoted, refused, _, _ = self.promote(fresh=False)
        self.assertEqual((promoted, refused), ([], []))

    def test_a_battle_is_cut_where_it_stops_adding_and_named_for_it(self):
        battle = ['d02_electro_shot_lock_emergency_exit']  # four steps
        first = corpus_tools.trace_signatures(committed(battle[0])[1])
        by_step = lambda k: {s for s, at in first.items() if at == k}
        for covered_steps, steps in (((), 4), ((3,), 3), ((2, 3), 2), ((1, 2, 3), 1)):
            with self.subTest(new_up_to_step=steps - 1):
                shutil.rmtree(self.corpus, ignore_errors=True)
                covered = set().union(*[by_step(k) for k in covered_steps])
                promoted, _, _, reference = self.promote(battle, base_signatures=covered)
                (entry,) = promoted
                self.assertEqual((entry.steps, entry.total), (steps, 4))
                spec, trace = corpus_tools.read_entry(self.corpus, entry.name)
                self.assertEqual(len(spec['choices']), steps)
                if steps < 4:
                    self.assertEqual(entry.name, 'fz_9_0_cut%d' % steps)
                    self.assertIn('cut after step %d of 4' % steps, spec['purpose'])
                else:
                    self.assertEqual(entry.name, 'fz_9_0')
                    self.assertIn('the whole battle', spec['purpose'])
                self.assertEqual(reference.recorded, [entry.name + '.json'])  # recorded again, under the name it has now
        shutil.rmtree(self.corpus)
        promoted, refused, _, _ = self.promote(battle, base_signatures=set(first))  # nothing new: nothing goes in
        self.assertEqual((promoted, refused), ([], []))

    def test_whole_keeps_the_battles_and_chooses_the_same_ones(self):
        cut, _, _, _ = self.promote()
        shutil.rmtree(self.corpus)
        whole, _, _, _ = self.promote(whole=True)
        strip = lambda name: re.sub(r'_cut\d+$', '', name)
        self.assertEqual([strip(e.name) for e in cut], [e.name for e in whole])  # the same battles, in the same order
        self.assertEqual([e.new for e in cut], [e.new for e in whole])  # that add the same
        self.assertTrue(all(e.steps == e.total for e in whole))
        self.assertTrue(any(e.steps < e.total for e in cut))  # and the cut ones are shorter
        spec, _ = corpus_tools.read_entry(self.corpus, whole[0].name)
        self.assertIn('the whole battle', spec['purpose'])
        self.assertEqual(corpus_tools.layout_problems(ROOT, self.corpus), [])

    def test_nothing_goes_in_that_the_engine_does_not_pass(self):
        reference = self.reference(self.BATTLES, {'*': driver.RunnerResult('DIVERGENCE', 'CLOSURE', 3, 9, 'differences: x', [])})
        promoted, refused, _, _ = self.promote(reference=reference)
        self.assertEqual(promoted, [])
        self.assertTrue(refused and all('does not PASS when it is recorded again: DIVERGENCE differences: x' in r.why for r in refused))
        self.assertFalse(os.path.exists(self.corpus) and corpus_tools.listing(self.corpus)[0])

    def test_a_run_without_kept_battles_has_no_coverage_to_promote(self):
        make_run(self.run_dir, self.BATTLES)
        shutil.rmtree(os.path.join(self.run_dir, 'kept'))
        promoted, refused, out, _ = self.promote(fresh=False)
        self.assertEqual((promoted, refused), ([], []))
        self.assertFalse(os.path.exists(self.corpus))

    def test_the_budget_the_limit_and_the_dry_run(self):
        promoted, refused, _, _ = self.promote(budget_bytes=1)
        self.assertEqual(promoted, [])
        self.assertTrue(refused and 'budget' in refused[0].why)
        self.assertFalse(os.path.exists(self.corpus) and corpus_tools.listing(self.corpus)[0])
        promoted, refused, out, _ = self.promote(dry_run=True)
        self.assertTrue(promoted and refused == [])
        self.assertIn('would promote', out)
        self.assertFalse(os.path.exists(self.corpus))  # nothing was written
        promoted, _, _, _ = self.promote(max_entries=1)
        self.assertEqual(len(promoted), 1)
        # A budget is for the corpus as it is, and never above the cap.
        size = corpus_tools.corpus_bytes(self.corpus)
        promoted, refused, _, _ = self.promote(budget_bytes=size + 1)
        self.assertEqual(promoted, [])

    # --- defects

    DEFECTS = ['m5_real_aa_1', 'd02_electro_shot_lock_emergency_exit', 'c11_follow_me', 's2_struggle']

    def test_a_defect_goes_in_as_its_shortest_prefix_once_it_is_fixed(self):
        # 1: a DIVERGENCE at step 2, 3: an ORACLE_GAP that the converter refused at step 1 (their cases have the prefix)
        defects = {1: ('DIVERGENCE', 2), 3: ('ORACLE_GAP', None)}
        promoted, refused, _, reference = self.promote(self.DEFECTS, defects, coverage=False, note='A6 (#85)')
        self.assertEqual(refused, [])
        self.assertEqual([(e.name, e.kind, e.steps, e.total) for e in promoted],
                         [('fz_9_1_prefix', 'defect', 3, 4), ('fz_9_3_prefix', 'defect', 2, 11)])
        spec, trace = corpus_tools.read_entry(self.corpus, 'fz_9_1_prefix')
        self.assertTrue(spec['purpose'].startswith('Corpus (defect): case fz_9_1 of run 9'))
        self.assertIn('found as DIVERGENCE', spec['purpose'])
        self.assertIn('3 of 4 choices', spec['purpose'])
        self.assertTrue(spec['purpose'].rstrip('.').endswith('fixed by A6 (#85)'))
        self.assertEqual((len(spec['choices']), len(trace['steps'])), (3, 3))
        self.assertEqual(reference.recorded, ['fz_9_1_prefix.json', 'fz_9_3_prefix.json'])
        self.assertEqual(corpus_tools.layout_problems(ROOT, self.corpus), [])

    def test_a_defect_that_is_not_fixed_is_not_promoted_and_the_message_says_what_to_do(self):
        defects = {1: ('DIVERGENCE', 2), 3: ('ORACLE_GAP', None)}
        reference = self.reference(self.DEFECTS, {'fz_9_1_prefix': driver.RunnerResult(
            'DIVERGENCE', 'CLOSURE', 2, 3, 'differences: state 1', [])})
        promoted, refused, _, _ = self.promote(self.DEFECTS, defects, reference, coverage=False)
        self.assertEqual([e.name for e in promoted], ['fz_9_3_prefix'])
        self.assertEqual([r.name for r in refused], ['fz_9_1_prefix'])
        self.assertIn('not fixed yet (DIVERGENCE differences: state 1)', refused[0].why)
        self.assertIn('regular fixture with its fix', refused[0].why)
        self.assertIn('d01 to d03', refused[0].why)
        self.assertEqual(corpus_tools.listing(self.corpus)[0], ['fz_9_3_prefix'])

    def test_one_defect_for_each_signature_unless_the_cases_are_named(self):
        defects = {1: ('DIVERGENCE', 2), 2: ('DIVERGENCE', 3), 3: ('ORACLE_GAP', None)}  # 1 and 2: the same signature
        promoted, _, _, _ = self.promote(self.DEFECTS, defects, coverage=False)
        self.assertEqual(sorted(e.name for e in promoted), ['fz_9_1_prefix', 'fz_9_3_prefix'])
        shutil.rmtree(self.corpus)
        promoted, _, _, _ = self.promote(self.DEFECTS, defects, coverage=False, cases=['fz_9_2'])
        self.assertEqual([e.name for e in promoted], ['fz_9_2_prefix'])

    def test_a_case_without_a_prefix_or_whose_prefix_did_not_reproduce_is_refused(self):
        battles = ['m5_real_aa_1', 'd02_electro_shot_lock_emergency_exit']
        make_run(self.run_dir, battles, defects={1: ('DIVERGENCE', 2)})
        case = os.path.join(self.run_dir, 'cases', 'fz_9_1')
        with io.open(os.path.join(case, 'prefix_result.json'), 'w') as f:
            f.write(json.dumps({'bucket': 'DIVERGENCE', 'step': 2, 'choices': 3, 'reproduces': False}))
        promoted, refused, _, _ = self.promote(battles, fresh=False, coverage=False)
        self.assertEqual(promoted, [])
        self.assertIn('not the shortest prefix', refused[0].why)
        os.remove(os.path.join(case, 'prefix_spec.json'))
        promoted, refused, _, _ = self.promote(battles, fresh=False, coverage=False, cases=['fz_9_1'])
        self.assertEqual(promoted, [])
        self.assertIn('no shortest prefix', refused[0].why)

    def test_a_name_that_is_there_is_not_written_over(self):
        defects = {1: ('DIVERGENCE', 2)}
        self.promote(self.DEFECTS, defects, coverage=False)
        path = corpus_tools.spec_path(self.corpus, 'fz_9_1_prefix')
        with io.open(path, 'rb') as f:
            before = f.read()
        promoted, refused, _, _ = self.promote(self.DEFECTS, defects, coverage=False)
        self.assertEqual(promoted, [])
        self.assertIn('a corpus battle of that name already', refused[0].why)
        with io.open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_a_directory_that_is_no_run(self):
        with self.assertRaises(corpus_tools.CorpusError):
            corpus_tools.read_records(self.tmp.name)
        os.makedirs(os.path.join(self.tmp.name, 'partial'))
        with self.assertRaises(corpus_tools.CorpusError):
            corpus_tools.run_seed(self.tmp.name)

    def test_the_report(self):
        promoted, _, _, _ = self.promote()
        out = io.StringIO()
        corpus_tools.report(promoted, [corpus_tools.Refused('x', 'because')], self.corpus, out)
        text = out.getvalue()
        self.assertIn('promote: %d battles (%d coverage, 0 defect)' % (len(promoted), len(promoted)), text)
        self.assertIn('not promoted: x: because', text)
        self.assertIn('promote: the corpus is ', text)


class Purposes(unittest.TestCase):
    def test_what_a_purpose_names(self):
        record = {'index': 12, 'name': 'fz_5_12', 'pairing': 'AD'}
        new = ['request:turn:mega', 'draw:CRIT:', '-boost:spa', 'request:replacement', 'move:Foo', 'move:Bar', 'move:Baz',
               'move:Qux']
        text = corpus_tools.coverage_purpose(record, 5, 7, 20, new)
        self.assertTrue(text.startswith('Corpus (coverage): random differential battle 12 of run 5'))
        self.assertIn('team A against team D', text)
        self.assertIn('cut after step 7 of 20', text)
        self.assertIn('adds 8 signatures', text)
        self.assertIn('and 2 more', text)  # six are named: the request situations first, then draws, then lines
        self.assertLess(text.index('request:replacement'), text.index('draw:CRIT:'))
        self.assertLess(text.index('draw:CRIT:'), text.index('-boost:spa'))
        self.assertIn('the whole battle', corpus_tools.coverage_purpose(record, 5, 20, 20, new))
        self.assertGreaterEqual(len(text), corpus_tools.MIN_PURPOSE)


if __name__ == '__main__':
    unittest.main()
