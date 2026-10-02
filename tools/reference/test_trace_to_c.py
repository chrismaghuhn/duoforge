#!/usr/bin/env python3
"""trace_to_c.py as a library: refusals, data and the generated headers. It
needs Python only, no Node and no Showdown checkout.

usage: python3 tools/reference/test_trace_to_c.py

CTest runs it as duoforge.reference.converter_api. The negative controls
change in-memory copies of committed battles; each asserts the rule, the
detail and the exact message, which is what the converter said before it had
ConversionError.
"""
import ast
import copy
import functools
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SCRIPT = os.path.join(HERE, 'trace_to_c.py')
HEADERS = ('conformance.h', 'conformance_team_c.h', 'conformance_types.h')

_tables = {}


def tables(team_c=False):
    if team_c not in _tables:
        _tables[team_c] = trace_to_c.load_tables(ROOT, team_c)
    return _tables[team_c]


def battle(name):
    """A fresh copy of the committed spec and trace of `name`."""
    return trace_to_c.load_battle(ROOT, name)


def convert(name, spec, trace):
    """convert_battle with the tables the spec asks for, as the command line does."""
    return trace_to_c.convert_battle(name, spec, trace, tables(trace_to_c.spec_is_team_c(name, spec)))


def committed(fname):
    with io.open(os.path.join(ROOT, 'tests', 'reference', fname), encoding='ascii') as f:
        return f.read().replace('\r\n', '\n')


def leaves(x):
    if isinstance(x, (tuple, list)):
        for v in x:
            yield from leaves(v)
    else:
        yield x


RECORDS = ('df_conf_member', 'df_conf_cmd', 'df_conf_mon', 'df_conf_step')


@functools.lru_cache(maxsize=None)
def declared_records():
    """The record types of conformance_types.h read from trace_to_c.TYPES, the
    text they are generated from: {struct: ((type, field, dims), ...)} in
    declaration order. df_conf_battle holds pointers and is no record of ints."""
    text = re.sub(r'/\*.*?\*/', '', '\n'.join(trace_to_c.TYPES), flags=re.S)
    out = {}
    for m in re.finditer(r'typedef struct (\w+) \{([^}]*)\} \w+;', text):
        if m.group(1) not in RECORDS:
            continue
        fields = []
        for decl in m.group(2).split(';'):
            if not decl.strip():
                continue
            ctype, names = decl.split(None, 1)
            for name in names.split(','):
                f = re.fullmatch(r'\s*(\w+)((?:\[\d+\])*)\s*', name)
                if f is None:
                    raise AssertionError('cannot read the declaration %r' % decl)
                fields.append((ctype, f.group(1), tuple(int(d) for d in re.findall(r'\[(\d+)\]', f.group(2)))))
        out[m.group(1)] = tuple(fields)
    if sorted(out) != sorted(RECORDS):
        raise AssertionError('records read: %s' % sorted(out))
    return out


class Refusals(unittest.TestCase):
    """Negative controls: a battle the converter does not model is refused with
    its rule, never converted differently."""

    def assert_refused(self, call, rule, message, detail=None):
        with self.assertRaises(SystemExit) as cm:
            call()
        e = cm.exception
        self.assertIsInstance(e, trace_to_c.ConversionError)
        self.assertIsInstance(e, SystemExit)
        self.assertEqual(e.rule, rule)
        self.assertEqual(e.code, message)
        self.assertEqual(e.detail, detail)

    def control(self, name, mutate, rule, message, detail=None):
        """The battle converts; with `mutate` applied it is refused."""
        spec, trace = battle(name)
        convert(name, spec, trace)
        mutate(spec, trace)
        self.assert_refused(lambda: convert(name, spec, trace), rule, message, detail)

    def test_unknown_protocol_line(self):
        self.control('s2_turn_core_1', lambda spec, trace: trace['steps'][1]['log'].append('|foo|bar'),
                     'protocol-line', "trace_to_c: unknown protocol line '|foo|bar'", 'foo')

    def test_unclassified_draw(self):
        def mutate(spec, trace):
            d = trace['steps'][3]['draws'][0]
            self.assertEqual((d['site'], d['context']), ('STALL', 'StallMove'))
            d['site'] = 'UNKNOWN'
        self.control('s2_turn_core_1', mutate, 'unclassified-draw', 'trace_to_c: unclassified draw', 'StallMove')

    def test_residual_tie_with_a_callback_handler(self):
        def mutate(spec, trace):
            d = trace['steps'][1]['draws'][0]
            self.assertEqual((d['site'], d['context']), ('SPEED_TIE', 'field:Residual'))
            self.assertEqual(d['group'], ['H:protect:p2a:end', 'H:stall:p2a:end'])  # duration counters
            d['group'][1] = 'H:stall:p2a:cb'
        self.control('s2_turn_core_1', mutate, 'residual-tie-callbacks',
                     "trace_to_c: residual tie with callbacks: ['H:protect:p2a:end', 'H:stall:p2a:cb']",
                     'protect+stall')

    def test_each_tie_between_holders_it_does_not_know(self):
        def mutate(spec, trace):
            d = trace['steps'][0]['draws'][4]
            self.assertEqual((d['site'], d['context']), ('SPEED_TIE', 'each:Update'))
            self.assertEqual(d['group'], ['P:p1b:0:', 'P:p2a:0:'])
            d['group'][0] = 'P:p1b:1:whiteherb'
        self.control('s2_struggle', mutate, 'each-tie-handlers',
                     "trace_to_c: each:Update tie between Pokemon with handlers: ['P:p1b:1:whiteherb', 'P:p2a:0:']",
                     'each:Update:whiteherb')

    def test_switch_order_tie_with_an_entry_effect_that_is_not_white_herb(self):
        def mutate(spec, trace):
            d = trace['steps'][0]['draws'][2]
            self.assertEqual((d['site'], d['context']), ('SPEED_TIE', 'switch-order'))
            self.assertEqual(d['group'], ['P:p1a:0:S:whiteherb', 'P:p2a:0:S:whiteherb'])  # two herbs: the engine draws
            d['group'][0] = 'P:p1a:0:S:whiteherb+foo'
        self.control('c08_herb_ties', mutate, 'switch-order-handlers',
                     "trace_to_c: switch-order tie with onAnySwitchIn handlers "
                     "['P:p1a:0:S:whiteherb+foo', 'P:p2a:0:S:whiteherb']", 'foo')

    def test_after_event_tie_between_holders_that_are_not_white_herb(self):
        for index, context in ((3, 'event:AfterMega'), (8, 'event:AfterMove')):  # draws of step 1 of c08_herb_ties
            with self.subTest(context=context):
                def mutate(spec, trace):
                    d = trace['steps'][1]['draws'][index]
                    self.assertEqual((d['site'], d['context']), ('SPEED_TIE', context))
                    self.assertEqual(d['group'], ['H:whiteherb:p1a:cb', 'H:whiteherb:p2a:cb'])  # kept: the engine draws
                    d['group'][1] = 'H:lifeorb:p2a:cb'
                self.control('c08_herb_ties', mutate, 'after-event-tie',
                             "trace_to_c: %s tie with ['H:whiteherb:p1a:cb', 'H:lifeorb:p2a:cb']" % context,
                             context + ':lifeorb+whiteherb')

    def test_singleturn_line_that_is_not_protect_or_helping_hand(self):
        def mutate(spec, trace):
            log = trace['steps'][1]['log']
            self.assertEqual(log[1], '|-singleturn|p1b: Kingambit|Helping Hand|[of] p1a: Indeedee')
            log[1] = '|-singleturn|p1b: Kingambit|move: Follow Me'
        self.control('c09_helping_hand', mutate, 'singleturn-line',
                     "trace_to_c: unknown -singleturn '|-singleturn|p1b: Kingambit|move: Follow Me'", 'move: Follow Me')

    def test_hit_draw_that_is_not_the_status_pick(self):
        for draw, text, detail in (
                ({'site': 'ACCURACY', 'context': 'Hit', 'lo': 0, 'hi': 100, 'value': 7},
                 "{'site': 'ACCURACY', 'context': 'Hit', 'lo': 0, 'hi': 100, 'value': 7}", 'ACCURACY[0,100)'),
                ({'site': 'SECONDARY', 'context': 'Hit', 'lo': 0, 'hi': 2, 'value': 1},
                 "{'site': 'SECONDARY', 'context': 'Hit', 'lo': 0, 'hi': 2, 'value': 1}", 'SECONDARY[0,2)')):
            with self.subTest(detail=detail):
                def mutate(spec, trace):
                    trace['steps'][3]['draws'][1] = copy.deepcopy(draw)
                self.control('s2_turn_core_1', mutate, 'hit-draw', 'trace_to_c: unexpected Hit draw ' + text, detail)

    def test_the_status_pick_is_a_tape_entry(self):
        """The one Hit draw that is accepted: SECONDARY[0,3) becomes STATUS_PICK (site 13)."""
        spec, trace = battle('s2_turn_core_1')
        before = len(convert('s2_turn_core_1', spec, trace)['steps'][3]['tape'])
        trace['steps'][3]['draws'].append({'site': 'SECONDARY', 'context': 'Hit', 'lo': 0, 'hi': 3, 'value': 1})
        tape = convert('s2_turn_core_1', spec, trace)['steps'][3]['tape']
        self.assertEqual((len(tape), tape[-1]), (before + 1, (13, 0, 3, 1)))

    def test_struggle_that_the_request_does_not_offer(self):
        def mutate(spec, trace):
            sides = trace['steps'][8]['state']['sides']
            self.assertEqual(sides[0]['enabled'], [[2], [1]])  # Struggle for slot 0, with no PP left
            sides[0]['enabled'] = [[1], [1]]
        self.control('s2_struggle', mutate, 'struggle-request',
                     "trace_to_c: no PP left and no Struggle in the request: 'move 1, move 1'")

    def test_choice_that_is_not_supported(self):
        def mutate(spec, trace):
            trace['steps'][1]['input']['p1'] = 'move 1 1, shift'
        self.control('s2_turn_core_1', mutate, 'choice-kind', "trace_to_c: choice 'shift' is not supported", 'shift')

    def test_public_hp_that_is_not_a_percent_display(self):
        def mutate(spec, trace):
            log = trace['steps'][3]['log']
            self.assertEqual(log[5], '|-damage|p2a: Archaludon|75/100')  # the public copy of a split line
            log[5] = '|-damage|p2a: Archaludon|75/182'
        self.control('s2_turn_core_1', mutate, 'public-hp-display',
                     "trace_to_c: not a public HP display in '|-damage|p2a: Archaludon|75/182'")

    def test_public_hp_of_a_pokemon_that_is_not_on_the_roster(self):
        def mutate(spec, trace):
            trace['steps'][3]['log'][5] = '|-damage|p2a: Nobody|75/100'
        self.control('s2_turn_core_1', mutate, 'unknown-pokemon',
                     "trace_to_c: unknown Pokemon in '|-damage|p2a: Nobody|75/100'", 'Nobody')

    def test_gender_the_species_cannot_have(self):
        def mutate(spec, trace):
            self.assertIn('Gholdengo\nAbility', spec['teams'][1])  # genderless
            spec['teams'][1] = spec['teams'][1].replace('Gholdengo\nAbility', 'Gholdengo (M)\nAbility')
        self.control('s2_turn_core_1', mutate, 'gender-illegal', 'trace_to_c: Gholdengo cannot be (M)', 'Gholdengo')

    def test_spec_data_that_is_not_known(self):
        spec, trace = battle('s2_turn_core_1')
        spec['data'] = 'team_d'
        self.assert_refused(lambda: trace_to_c.spec_is_team_c('s2_turn_core_1', spec), 'spec-data',
                            "trace_to_c: s2_turn_core_1: unknown data 'team_d'")


class Library(unittest.TestCase):
    def test_the_committed_headers_are_what_the_library_makes(self):
        """convert_battle and format_battle reproduce the three committed headers: the code --check runs."""
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'traces'))
                       if f.endswith('.json'))
        for team_c, fname in ((False, 'conformance.h'), (True, 'conformance_team_c.h')):
            with self.subTest(fname):
                chosen = [n for n in names if trace_to_c.is_team_c(ROOT, n) == team_c]
                text, _, _ = trace_to_c.build_header(ROOT, chosen, tables(team_c), team_c)
                self.assertEqual(text, committed(fname))
                self.assertIn('#include "reference/conformance_types.h"\n', text)
                self.assertNotIn('typedef struct df_conf_', text)  # the types live in their own header
        self.assertEqual(trace_to_c.types_header(), committed('conformance_types.h'))

    def test_every_draw_is_a_tape_entry_or_dropped(self):
        """In every committed battle the steps' tape entries and drop counts add up to the draws of the trace."""
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'traces'))
                       if f.endswith('.json'))
        self.assertGreater(len(names), 100)
        for name in names:
            spec, trace = battle(name)
            data = convert(name, spec, trace)
            self.assertEqual(len(data['steps']), len(trace['steps']), name)
            for i, (st, raw) in enumerate(zip(data['steps'], trace['steps'])):
                self.assertEqual(len(st['tape']) + st['dropped'], len(raw['draws']), '%s step %d' % (name, i))
            self.assertEqual(data['dropped_total'], sum(st['dropped'] for st in data['steps']), name)

    def assert_shape(self, value, ctype, dims, where):
        """`value` is a `ctype` with array dimensions `dims` as the data holds it: nested tuples that follow the
        declaration in conformance_types.h, plain ints at the leaves."""
        records = declared_records()
        if dims:
            self.assertIsInstance(value, (tuple, list), where)
            self.assertEqual(len(value), dims[0], where)
            for i, item in enumerate(value):
                self.assert_shape(item, ctype, dims[1:], '%s[%d]' % (where, i))
        elif ctype in records:
            self.assertIsInstance(value, (tuple, list), where)
            self.assertEqual(len(value), len(records[ctype]), where)
            for item, (t, name, d) in zip(value, records[ctype]):
                self.assert_shape(item, t, d, '%s.%s' % (where, name))
        else:
            self.assertIs(type(value), int, where)

    def test_the_data_has_the_df_conf_shape(self):
        spec, trace = battle('s2_turn_core_1')
        data = convert('s2_turn_core_1', spec, trace)
        self.assertEqual(sorted(data), ['dropped_total', 'member_count', 'members', 'name', 'purpose', 'steps'])
        self.assertEqual((data['name'], data['purpose']), ('s2_turn_core_1', spec['purpose']))
        self.assertEqual(data['member_count'], 4)
        self.assertEqual([len(rows) for rows in data['members']], [4, 4])
        for s, rows in enumerate(data['members']):
            for m, member in enumerate(rows):
                self.assert_shape(member, 'df_conf_member', (), 'member %d of side %d' % (m, s))
        step_fields = ['answered0', 'answered1', 'boundary', 'cmds', 'dropped', 'enabled', 'entries', 'events',
                       'field', 'mons', 'occupants', 'picks', 'result', 'tape', 'team', 'turn']
        for i, st in enumerate(data['steps']):
            self.assertEqual(sorted(st), step_fields)
            self.assert_shape(trace_to_c.step_record(st, 0, (0, 0), (0, 0)), 'df_conf_step', (), 'step %d' % i)
            self.assertTrue(all(len(entry) == 4 for entry in st['tape']))  # site, lo, hi, value
            self.assertEqual(len(st['events']), 2)  # one list per player
            self.assertTrue(all(len(e) == 14 for evs in st['events'] for e in evs))  # the duoforge_event fields
            self.assertTrue(all(type(v) is int for key in ('tape', 'events') for v in leaves(st[key])))

    def test_step_record_is_the_declaration_order(self):
        """step_record lists the fields of df_conf_step in the order it is
        declared in: by name, what the data holds, and the offsets where the
        declaration has them. A runner that flattens the record relies on it."""
        spec, trace = battle('s2_turn_core_1')
        names = [name for _, name, _ in declared_records()['df_conf_step']]
        for st in convert('s2_turn_core_1', spec, trace)['steps']:
            derived = {'tape_off': 7, 'tape_len': len(st['tape']), 'ev_off': (11, 13), 'ev_len': (2, 3)}
            record = trace_to_c.step_record(st, 7, (11, 13), (2, 3))
            self.assertEqual(len(record), len(names))
            for value, name in zip(record, names):
                self.assertEqual(value, derived[name] if name in derived else st[name], name)

    def test_convert_battle_is_pure(self):
        """No file IO, and the spec and the trace are as they were."""
        for name in ('s2_struggle', 'c05_helmet_order'):  # a closure and a Team C battle, both with ties
            spec, trace = battle(name)
            before = copy.deepcopy((spec, trace))
            battle_tables = tables(trace_to_c.spec_is_team_c(name, spec))
            refuse = AssertionError('convert_battle did file IO')
            with mock.patch('io.open', side_effect=refuse), mock.patch('builtins.open', side_effect=refuse):
                data = trace_to_c.convert_battle(name, spec, trace, battle_tables)
            self.assertEqual((spec, trace), before, name)
            self.assertEqual(data['name'], name)

    def test_team_c_is_the_decision_of_the_spec(self):
        self.assertTrue(trace_to_c.spec_is_team_c('x', {'data': 'team_c'}))
        self.assertFalse(trace_to_c.spec_is_team_c('x', {}))
        self.assertTrue(trace_to_c.is_team_c(ROOT, 'c01_team_c_profile'))
        self.assertFalse(trace_to_c.is_team_c(ROOT, 's2_turn_core_1'))

    def test_pass_for_both_slots_converts_per_slot(self):
        """A choice that passes both slots of a switch request: each slot is
        asked when its Pokemon holds the switch flag (a fainted one, or a
        standing one that keeps it), as for a single pass. The second pass once
        raised UnboundLocalError. The state is made up: no committed battle
        answers both slots with pass."""
        asked, unasked = (3, 0, 0, 0, 0), (0, 0, 0, 0, 0)

        def state(request, flags):
            return {'sides': [{'request': request, 'active': [0, 1], 'pokemon': [{'switch_flag': f} for f in flags]}]}

        for mid_turn in (False, True):  # the rule reads the flag; mid_turn is only kept for the callers
            for request, flags, want in (('switch', (1, 0), [asked, unasked]), ('switch', (0, 1), [unasked, asked]),
                                         ('switch', (1, 1), [asked, asked]), ('switch', (0, 0), [unasked, unasked]),
                                         ('move', (0, 0), [asked, asked])):
                with self.subTest(request=request, flags=flags, mid_turn=mid_turn):
                    got = trace_to_c.convert_choice('pass, pass', 0, state(request, flags), [{}], mid_turn)
                    self.assertEqual(got, ('slots', want))

    def test_conversion_error_is_a_system_exit_that_pickles(self):
        e = trace_to_c.ConversionError('some-rule', 'trace_to_c: some message', detail='some detail')
        self.assertIsInstance(e, SystemExit)
        self.assertEqual((e.code, str(e)), ('trace_to_c: some message', 'trace_to_c: some message'))
        self.assertEqual((e.rule, e.detail), ('some-rule', 'some detail'))
        self.assertIsNone(trace_to_c.ConversionError('r', 'm').detail)
        back = pickle.loads(pickle.dumps(e))
        self.assertIsInstance(back, trace_to_c.ConversionError)
        self.assertEqual((back.code, back.rule, back.detail), (e.code, e.rule, e.detail))

    def test_no_refusal_is_a_bare_system_exit(self):
        """Every refusal of the converter carries a rule: a driver buckets by it."""
        with io.open(SCRIPT, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        bare = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
                and isinstance(n.exc.func, ast.Name) and n.exc.func.id == 'SystemExit']
        self.assertEqual(bare, [], 'raise ConversionError(rule, message) instead, at these lines')


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, env=env)

    def tree(self, tmp, names, mutate=None):
        """A small tree in `tmp`: the tables of src/data and some committed battles, one of them changed by
        `mutate(name, spec, trace)`."""
        os.makedirs(os.path.join(tmp, 'src', 'data'))
        for fname in ('closure_tables.h', 'closure_tables.c', 'extended_tables.h', 'extended_tables.c'):
            shutil.copy(os.path.join(ROOT, 'src', 'data', fname), os.path.join(tmp, 'src', 'data', fname))
        for kind in ('specs', 'traces'):
            os.makedirs(os.path.join(tmp, 'tests', 'reference', kind))
        for name in names:
            spec, trace = battle(name)
            if mutate:
                mutate(name, spec, trace)
            for kind, obj in (('specs', spec), ('traces', trace)):
                with io.open(os.path.join(tmp, 'tests', 'reference', kind, name + '.json'), 'w',
                             encoding='utf-8') as f:
                    json.dump(obj, f)

    BATTLES = ('c01_team_c_profile', 'c04_flip_turn_ko', 's2_ally_target', 's2_turn_core_1')

    def test_check_of_the_committed_tables_passes(self):
        p = self.run_cli(ROOT, '--check')
        self.assertEqual((p.returncode, p.stderr), (0, ''), p.stdout)
        want = ['trace_to_c: %s matches %s' % (os.path.join(ROOT, 'tests', 'reference', fname), what)
                for fname, what in (('conformance.h', 'the traces'), ('conformance_team_c.h', 'the traces'),
                                    ('conformance_types.h', 'the template in trace_to_c.py'))]
        self.assertEqual(p.stdout.splitlines(), want)

    def test_usage(self):
        p = self.run_cli()
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, '', 'usage: trace_to_c.py <repo root> [--check]\n'))

    def test_a_refused_trace_exits_with_status_1_and_its_message(self):
        def corrupt(name, spec, trace):
            if name == 's2_turn_core_1':
                trace['steps'][1]['log'].append('|foo|bar')
        with tempfile.TemporaryDirectory() as tmp:
            self.tree(tmp, self.BATTLES, corrupt)
            p = self.run_cli(tmp, '--check')
        self.assertEqual((p.returncode, p.stdout, p.stderr),
                         (1, '', "trace_to_c: unknown protocol line '|foo|bar'\n"))

    def test_write_and_check_cover_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.tree(tmp, self.BATTLES)
            reference = os.path.join(tmp, 'tests', 'reference')
            p = self.run_cli(tmp)
            self.assertEqual((p.returncode, p.stderr), (0, ''))
            self.assertEqual(sorted(f for f in os.listdir(reference) if f.endswith('.h')), sorted(HEADERS))
            self.assertEqual(self.run_cli(tmp, '--check').returncode, 0)
            for fname, what in (('conformance_types.h', 'the template in trace_to_c.py'),
                                ('conformance_team_c.h', 'the traces'), ('conformance.h', 'the traces')):
                path = os.path.join(reference, fname)
                with io.open(path, encoding='ascii') as f:
                    good = f.read()
                with io.open(path, 'w', encoding='ascii', newline='\n') as f:
                    f.write(good + '/* edited by hand */\n')
                p = self.run_cli(tmp, '--check')
                self.assertEqual((p.returncode, p.stderr),
                                 (1, 'trace_to_c: %s differs from %s\n' % (path, what)), fname)
                with io.open(path, 'w', encoding='ascii', newline='\n') as f:
                    f.write(good)
            self.assertEqual(self.run_cli(tmp, '--check').returncode, 0)


if __name__ == '__main__':
    unittest.main()
