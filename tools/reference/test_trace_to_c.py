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
HEADERS = ('conformance.h', 'conformance_team_c.h', 'conformance_pool.h', 'conformance_types.h')

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


def mon_of(state, side, species):
    """The Pokemon `species` of `side` in a recorded state."""
    found = [p for p in state['sides'][side]['pokemon'] if trace_to_c.name_of(p) == species]
    assert len(found) == 1, (side, species, found)
    return found[0]


RECORDS = ('df_conf_member', 'df_conf_cmd', 'df_conf_mon', 'df_conf_step')


def mon_row(trace, data, step, side, species):
    """The df_conf_mon of `species` on `side` after step `step` of converted data, by field name."""
    roster = [trace_to_c.name_of(p) for p in trace['start']['state']['sides'][side]['pokemon']].index(species)
    names = [name for _, name, _ in declared_records()['df_conf_mon']]
    return dict(zip(names, data['steps'][step]['mons'][side][roster]))


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

    def test_hail_is_refused_never_mapped(self):
        """Hail is isNonstandard "Past" at the pin and not in the format (Snow Warning sets Snowscape, which does no
        damage): a -weather line that names it, and damage [from] Hail, are ConversionErrors, not silently another weather."""
        def hail_weather(spec, trace):
            for step in trace['steps']:
                for i, line in enumerate(step['log']):
                    if line == '|-weather|Sandstorm|[upkeep]':
                        step['log'][i] = '|-weather|Hail|[upkeep]'
                        return
            self.fail('no upkeep line')

        def hail_damage(spec, trace):
            for step in trace['steps']:
                for i, line in enumerate(step['log']):
                    if line.endswith('|[from] Sandstorm'):
                        step['log'][i] = line[:-len('Sandstorm')] + 'Hail'
                        return
            self.fail('no sandstorm damage')

        self.control('w1_sand_stream', hail_weather, 'weather-line',
                     "trace_to_c: unknown weather 'Hail' in '|-weather|Hail|[upkeep]'", 'Hail')
        self.control('w1_sand_stream', hail_damage, 'from-attribute', 'trace_to_c: [from] Hail: no Hail in the format',
                     'Hail')

    def test_the_bare_ohko_of_a_sheer_cold_sub_break_is_dropped_only_before_that_break(self):
        """Sheer Cold into a Substitute (step G64 with decision 0032): the sub's break prints `-ohko` right after the move line
        and right before `-end|X|Substitute` (data/moves.ts:18357-18374). The line is dropped only with that exact pair in
        place: without the -end, or with the -end of another Pokemon, it is refused like any other -ohko."""
        def drop_the_break(spec, trace):
            for step in trace['steps']:
                log = step['log']
                for i, line in enumerate(log):
                    if line == '|-ohko' and log[i + 1] == '|-end|p2a: Gengar|Substitute':
                        del log[i + 1]
                        return
            self.fail('no sub break by an OHKO in xr3_sheercold_sub')

        def other_target(spec, trace):
            for step in trace['steps']:
                log = step['log']
                for i, line in enumerate(log):
                    if line == '|-ohko' and log[i + 1] == '|-end|p2a: Gengar|Substitute':
                        log[i + 1] = '|-end|p1a: Glalie|Substitute'
                        return
            self.fail('no sub break by an OHKO in xr3_sheercold_sub')

        self.control('xr3_sheercold_sub', drop_the_break, 'ohko-line', "trace_to_c: unknown -ohko '|-ohko'", '|-ohko')
        self.control('xr3_sheercold_sub', other_target, 'ohko-line', "trace_to_c: unknown -ohko '|-ohko'", '|-ohko')

    def test_unknown_protocol_line(self):
        self.control('s2_turn_core_1', lambda spec, trace: trace['steps'][1]['log'].append('|foo|bar'),
                     'protocol-line', "trace_to_c: unknown protocol line '|foo|bar'", 'foo')

    def test_a_hitcount_line_is_asserted_against_the_damage_lines_and_dropped(self):
        """`|-hitcount|P|N` (multi-hit moves, data/mods/champions/scripts.ts:427-549) is no event: N must be the number of
        -damage lines the move showed on that Pokemon. A wrong N is refused; a missing line is not an error (the Champions loop
        prints none for Parental Bond with only its first hit); and the line of a Pokemon that has fainted, shown without its
        slot, still matches."""
        name = 'g33_dual_wingbeat'
        spec, trace = battle(name)
        base = convert(name, spec, trace)
        lines = [(k, i, l) for k, st in enumerate(trace['steps']) for i, l in enumerate(st['log']) if l.startswith('|-hitcount|')]
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(any(re.match(r'\|-hitcount\|p[12]: ', l) for _, _, l in lines), 'a slotless line (a fainted target)')
        self.assertTrue(any(re.match(r'\|-hitcount\|p[12][ab]: ', l) for _, _, l in lines), 'a line with a slot')
        self.assertTrue(any(l.endswith('|2') for _, _, l in lines))

        def wrong(spec, trace):
            k, i, l = lines[0]
            n = int(l.split('|')[-1])
            trace['steps'][k]['log'][i] = l[:-len(str(n))] + str(n + 1)
        n0 = int(lines[0][2].split('|')[-1])
        self.control(name, wrong, 'hitcount-mismatch',
                     "trace_to_c: %r but the move showed %d -damage lines on that Pokemon" % (lines[0][2][:-1] + str(n0 + 1), n0),
                     str(n0 + 1))

        def zero(spec, trace):
            k, i, l = lines[0]
            trace['steps'][k]['log'][i] = l[:-len(str(n0))] + '0'
        self.control(name, zero, 'hitcount-mismatch',
                     "trace_to_c: %r but the move showed %d -damage lines on that Pokemon" % (lines[0][2][:-1] + '0', n0), '0')

        def not_a_number(spec, trace):
            k, i, l = lines[0]
            trace['steps'][k]['log'][i] = l[:-len(str(n0))] + 'x'
        self.control(name, not_a_number, 'hitcount-mismatch',
                     "trace_to_c: %r but the move showed %d -damage lines on that Pokemon" % (lines[0][2][:-1] + 'x', n0), 'x')

        def other_pokemon(spec, trace):
            k, i, l = lines[0]
            m = re.match(r'\|-hitcount\|p([12])(?:[ab])?: ', l)
            other = '2' if m.group(1) == '1' else '1'
            trace['steps'][k]['log'][i] = '|-hitcount|p' + other + l[len('|-hitcount|p1'):]
        spec, trace = battle(name)
        other_pokemon(spec, trace)
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            convert(name, spec, trace)
        self.assertEqual(cm.exception.rule, 'hitcount-mismatch')

        # a -damage line with an attribute ([from] ...) is not a hit: it must not be counted for the Pokemon it shows
        spec, trace = battle(name)
        k, i, l = lines[0]
        log = trace['steps'][k]['log']
        j = max(x for x in range(i) if log[x].startswith('|-damage|') and '[' not in log[x])
        log.insert(i, log[j] + '|[from] item: Rocky Helmet')
        convert(name, spec, trace)

        spec, trace = battle(name)
        for st in trace['steps']:
            st['log'] = [l for l in st['log'] if not l.startswith('|-hitcount|')]
        self.assertEqual(convert(name, spec, trace), base)  # absent lines: no error, the events are the same

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

    def test_an_update_tie_of_a_trace_holder_is_not_a_holder(self):
        """Step AC1: a Trace holder at an Update (its onUpdate returns unless it is still seeking, which the engine
        refuses) is not a holder of the tie: a tie with at most one other holder is dropped, one with two others is
        the engine's own (its Sitrus holders' draw), and a handler that is not known is refused."""
        def tie(group):
            return trace_to_c.drop_reason({'site': 'SPEED_TIE', 'context': 'each:Update', 'group': group}, {})
        self.assertIsNotNone(tie(['P:p1b:1:trace', 'P:p2a:0:']))
        self.assertIsNotNone(tie(['P:p1b:1:trace', 'P:p2a:1:sitrusberry']))
        self.assertIsNotNone(tie(['P:p1b:1:trace', 'P:p2a:1:trace']))
        self.assertIsNone(tie(['P:p1b:1:trace', 'P:p2a:1:sitrusberry', 'P:p2b:1:sitrusberry']))
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            tie(['P:p1b:1:trace', 'P:p2a:1:whiteherb'])
        self.assertEqual(cm.exception.rule, 'each-tie-handlers')

    def test_a_before_move_tie_of_heal_block_and_throat_chop_of_one_pokemon_is_dropped(self):
        """Step AC1 follow-up (the AWS triage of 2026-10-03): the two BeforeMove handlers of a Pokemon that holds Heal
        Block and Throat Chop, in either order, are dropped (no pool move has both flags); any other BeforeMove tie, and
        the pair on two Pokemon, are refused."""
        def tie(group, context='event:BeforeMove'):
            return trace_to_c.drop_reason({'site': 'SPEED_TIE', 'context': context, 'group': group}, {})
        self.assertIn('Heal Block', tie(['H:healblock:p1b:cb', 'H:throatchop:p1b:cb']))
        self.assertIn('Heal Block', tie(['H:throatchop:p2a:cb', 'H:healblock:p2a:cb']))
        # the ModifyMove handlers of the same two conditions (data/moves.ts:8314, :19417) are the same case
        self.assertIn('ModifyMove', tie(['H:healblock:p1b:cb', 'H:throatchop:p1b:cb'], 'event:ModifyMove'))
        self.assertIn('Heal Block', tie(['H:throatchop:p2a:cb', 'H:healblock:p2a:cb'], 'event:ModifyMove'))
        with self.assertRaises(trace_to_c.ConversionError):
            tie(['H:healblock:p1b:cb', 'H:throatchop:p1b:cb'], 'event:TryHit')
        for bad in (['H:healblock:p1b:cb', 'H:throatchop:p2a:cb'], ['H:healblock:p1b:cb', 'H:flinch:p1b:cb'],
                    ['H:healblock:p1b:cb', 'H:throatchop:p1b:cb', 'H:slp:p1b:cb'], ['H:healblock:p1b:cb', 'H:healblock:p1b:cb']):
            with self.assertRaises(trace_to_c.ConversionError) as cm:
                tie(bad)
            self.assertEqual(cm.exception.rule, 'tie-context')

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

    def test_singleturn_line_that_is_not_protect_helping_hand_or_follow_me(self):
        def mutate(spec, trace):
            log = trace['steps'][1]['log']
            self.assertEqual(log[1], '|-singleturn|p1b: Kingambit|Helping Hand|[of] p1a: Indeedee')
            log[1] = '|-singleturn|p1b: Kingambit|move: Quick Guard'
        self.control('c09_helping_hand', mutate, 'singleturn-line',
                     "trace_to_c: unknown -singleturn '|-singleturn|p1b: Kingambit|move: Quick Guard'",
                     'move: Quick Guard')

    def test_choice_scarf_holder_without_its_switch_in_handler(self):
        def mutate(spec, trace):
            d = trace['steps'][0]['draws'][1]
            self.assertEqual((d['site'], d['context'], d['group']),
                             ('SPEED_TIE', 'switch-order', ['P:p1a:1:S', 'P:p2b:1:S']))
            d['group'][0] = 'P:p1a:0:S'
        self.control('c12_scarf_tie', mutate, 'switch-order-handlers',
                     "trace_to_c: a Choice Scarf holder without its SwitchIn handler in ['P:p1a:0:S', 'P:p2b:1:S']",
                     'choicescarf')

    def test_switch_order_scarf_is_the_item_the_pokemon_enters_with(self):
        """The ORACLE_GAP of the first G29 campaign (fz_9900000_938, step 10): an Arcanine-Hisui enters at p1b with no item
        (its tie entry is 'P:p1b:0:S': no SwitchIn handler), and a Trick later in the same step gives it a Choice Scarf.
        The state after the step shows the Scarf, so reading the holders there counted a Scarf handler that was not
        there (a refusal, 'a Choice Scarf holder without its SwitchIn handler'). The holders are read as of the entry:
        the item that the same species holds in the state before the step. States cut down from that case."""
        def mon(species, item):
            return {'species': species, 'item': item}
        before = {'sides': [
            {'active': [0, 1], 'pokemon': [mon('Gholdengo', 'choicescarf'), mon('Swalot', 'focussash'),
                                           mon('Farigiraf', ''), mon('Arcanine-Hisui', '')]},
            {'active': [0, 1], 'pokemon': [mon('Arcanine-Hisui', ''), mon('Farigiraf', 'leftovers')]}]}
        after = {'sides': [
            {'active': [0, 3], 'pokemon': [mon('Gholdengo', ''), mon('Swalot', 'focussash'), mon('Farigiraf', ''),
                                           mon('Arcanine-Hisui', 'choicescarf')]},
            {'active': [0, 1], 'pokemon': [mon('Arcanine-Hisui', ''), mon('Farigiraf', 'leftovers')]}]}
        self.assertEqual(trace_to_c.choice_scarf_slots(after), {'p1b'})  # the end state alone (the old reading)
        # The standing Gholdengo held the Scarf at the start of the step (p1a); the entering Arcanine-Hisui did not (p1b).
        self.assertEqual(trace_to_c.choice_scarf_slots(after, before), {'p1a'})
        group = ['P:p1b:0:S', 'P:p2a:0:-']
        d = {'site': 'SPEED_TIE', 'context': 'switch-order', 'group': group}
        self.assertEqual(trace_to_c.drop_reason(d, before, after), 'switch-in order with at most one entry effect')
        # A Pokemon that comes in with the Scarf has its handler, and the same state before and after reads the same.
        before['sides'][0]['pokemon'][3]['item'] = 'choicescarf'
        self.assertEqual(trace_to_c.choice_scarf_slots(after, before), {'p1a', 'p1b'})
        d = {'site': 'SPEED_TIE', 'context': 'switch-order', 'group': ['P:p1b:1:S', 'P:p2a:0:-']}
        self.assertEqual(trace_to_c.drop_reason(d, before, after), 'switch-in order with at most one entry effect')
        # Still refused: a Scarf holder at the entry whose tie entry has no handler.
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            trace_to_c.drop_reason(dict(d, group=group), before, after)
        self.assertEqual((cm.exception.rule, cm.exception.detail), ('switch-order-handlers', 'choicescarf'))

    @staticmethod
    def accuracy_tie(trace):
        """The one draw in context event:Accuracy of d01_noguard_accuracy_tie."""
        found = [d for step in trace['steps'] for d in step['draws'] if d.get('context') == 'event:Accuracy']
        assert len(found) == 1, found
        return found[0]

    def test_accuracy_tie_with_a_handler_that_is_not_no_guard(self):
        def mutate(spec, trace):
            d = self.accuracy_tie(trace)
            self.assertEqual((d['site'], d['group']), ('SPEED_TIE', ['H:noguard:p1b:cb', 'H:noguard:p2b:cb']))  # dropped
            d['group'][1] = 'H:victorystar:p2b:cb'  # onAnyModifyAccuracy: not the handler whose order is known to decide nothing
        self.control('d01_noguard_accuracy_tie', mutate, 'tie-context', 'trace_to_c: unhandled tie context event:Accuracy',
                     'event:Accuracy')

    def test_accuracy_tie_of_no_guard_with_an_entry_that_is_not_a_callback(self):
        def mutate(spec, trace):
            self.accuracy_tie(trace)['group'][0] = 'H:noguard:p1b:end'
        self.control('d01_noguard_accuracy_tie', mutate, 'tie-context', 'trace_to_c: unhandled tie context event:Accuracy',
                     'event:Accuracy')

    def test_the_no_guard_rule_is_for_the_accuracy_event_only(self):
        def mutate(spec, trace):
            self.accuracy_tie(trace)['context'] = 'event:AfterMove'  # the same two handlers in an event they are not in
        self.control('d01_noguard_accuracy_tie', mutate, 'after-event-tie',
                     "trace_to_c: event:AfterMove tie with ['H:noguard:p1b:cb', 'H:noguard:p2b:cb']",
                     'event:AfterMove:noguard')

    @staticmethod
    def priority_tie(trace):
        """The draws in context event:ModifyAccuracy of g49_bright_powder_tie (Wide Lens and Bright Powder at one Speed)."""
        found = [d for step in trace['steps'] for d in step['draws'] if d.get('context') == 'event:ModifyAccuracy']
        assert len(found) == 2, found
        return found

    def test_wide_lens_and_bright_powder_tie_is_a_dropped_draw(self):
        """g49_bright_powder_tie: the two priority -2 accuracy items of equal-Speed holders tie in ModifyAccuracy. The draws are
        dropped with their reason (the engine refuses the orders that differ), and the battle converts."""
        name = 'g49_bright_powder_tie'
        spec, trace = battle(name)
        convert(name, spec, trace)
        for d in self.priority_tie(trace):
            self.assertEqual((d['site'], d['group']), ('SPEED_TIE', ['H:brightpowder:p2a:cb', 'H:widelens:p1a:cb']))
        k = next(k for k, step in enumerate(trace['steps']) for d in step['draws'] if d.get('context') == 'event:ModifyAccuracy')
        d = self.priority_tie(trace)[0]
        before, after = trace['steps'][k - 1]['state'], trace['steps'][k]['state']
        flipped = dict(d, group=list(reversed(d['group'])))
        self.assertEqual(trace_to_c.drop_reason(d, before, after), trace_to_c.drop_reason(flipped, before, after))
        self.assertIn('Wide Lens and Bright Powder', trace_to_c.drop_reason(d, before, after))

    def test_accuracy_tie_of_wide_lens_and_bright_powder_with_another_handler(self):
        """A tie in ModifyAccuracy with any third handler, or with a handler that is not a callback, is still refused."""
        def other(spec, trace):
            self.priority_tie(trace)[0]['group'][1] = 'H:noguard:p2b:cb'
        self.control('g49_bright_powder_tie', other, 'tie-context', 'trace_to_c: unhandled tie context event:ModifyAccuracy',
                     'event:ModifyAccuracy')

        def third(spec, trace):
            self.priority_tie(trace)[0]['group'].append('H:widelens:p2b:cb')
        self.control('g49_bright_powder_tie', third, 'tie-context', 'trace_to_c: unhandled tie context event:ModifyAccuracy',
                     'event:ModifyAccuracy')

        def not_a_callback(spec, trace):
            self.priority_tie(trace)[0]['group'][0] = 'H:brightpowder:p2a:end'
        self.control('g49_bright_powder_tie', not_a_callback, 'tie-context', 'trace_to_c: unhandled tie context event:ModifyAccuracy',
                     'event:ModifyAccuracy')

    def test_unknown_volatile(self):
        def mutate(spec, trace):
            mon = trace['steps'][1]['state']['sides'][0]['pokemon'][0]
            self.assertNotIn('zzunknown', mon['volatiles'])
            mon['volatiles'] = sorted(mon['volatiles'] + ['zzunknown'])
        self.control('c11_follow_me', mutate, 'unknown-volatile',
                     "trace_to_c: unknown volatile 'zzunknown' of Indeedee-F", 'zzunknown')

    def test_two_turn_move_volatile_without_twoturnmove(self):
        def mutate(spec, trace):
            mon = trace['steps'][0]['state']['sides'][1]['pokemon'][1]
            self.assertNotIn('twoturnmove', mon['volatiles'])
            mon['volatiles'] = sorted(mon['volatiles'] + ['electroshot'])
        self.control('c11_follow_me_rod', mutate, 'unknown-volatile',
                     'trace_to_c: electroshot without twoturnmove on Archaludon', 'electroshot')

    def test_twoturnmove_without_a_lock_recorded_earlier(self):
        def mutate(spec, trace):
            charging = mon_of(trace['steps'][2]['state'], 0, 'Archaludon')  # the charge turn of d02
            self.assertEqual((charging['volatiles'], charging['locked']), (['electroshot', 'twoturnmove'], [1, -1]))
            charging['volatiles'] = ['twoturnmove']  # no lock is recorded for it, and none was before
            charging['locked'] = None
        self.control('d02_electro_shot_lock_emergency_exit', mutate, 'twoturnmove-lock',
                     'trace_to_c: twoturnmove without a lock recorded earlier on Archaludon', 'twoturnmove')

    def test_the_remembered_lock_is_of_one_pokemon_on_one_side(self):
        """d02 is team B against team B: the other side's Archaludon has no lock recorded, so the lock of ours is not
        taken for it."""
        def mutate(spec, trace):
            other = mon_of(trace['steps'][3]['state'], 1, 'Archaludon')
            self.assertEqual((other['volatiles'], other['locked']), (['stall'], None))
            other['volatiles'] = ['stall', 'twoturnmove']
        self.control('d02_electro_shot_lock_emergency_exit', mutate, 'twoturnmove-lock',
                     'trace_to_c: twoturnmove without a lock recorded earlier on Archaludon', 'twoturnmove')

    def test_a_lock_does_not_outlive_twoturnmove(self):
        """The residual ends twoturnmove, and a switch-out or a faint clears every volatile of the Pokemon
        (sim/battle-actions.ts:117, sim/battle.ts:2563): the first state without twoturnmove forgets the lock, which a
        later twoturnmove without its move's volatile must not take again. Not a committed battle: d02's last state
        is made the state after the residual, and a copy of it the window of another charge."""
        name = 'd02_electro_shot_lock_emergency_exit'
        spec, trace = battle(name)
        last = trace['steps'][3]
        window = mon_of(last['state'], 0, 'Archaludon')
        self.assertEqual((window['volatiles'], window['locked']), (['twoturnmove'], None))
        window['volatiles'] = []  # twoturnmove is gone
        data = convert(name, spec, trace)
        row = mon_row(trace, data, 3, 0, 'Archaludon')
        self.assertEqual((row['locked_slot'], row['locked_target'], row['vols']), (0xFF, 0, 0))
        again = copy.deepcopy(last)
        again['input'] = {}
        mon_of(again['state'], 0, 'Archaludon')['volatiles'] = ['twoturnmove']
        trace['steps'].append(again)
        self.assert_refused(lambda: convert(name, spec, trace), 'twoturnmove-lock',
                            'trace_to_c: twoturnmove without a lock recorded earlier on Archaludon', 'twoturnmove')

    def test_follow_me_line_with_an_attribute(self):
        def mutate(spec, trace):
            log = trace['steps'][1]['log']
            self.assertIn('|-singleturn|p1a: Indeedee|move: Follow Me', log)
            i = log.index('|-singleturn|p1a: Indeedee|move: Follow Me')
            log[i] = '|-singleturn|p1a: Indeedee|move: Follow Me|[zeffect]'
        self.control('c11_follow_me', mutate, 'singleturn-line',
                     "trace_to_c: unknown -singleturn '|-singleturn|p1a: Indeedee|move: Follow Me|[zeffect]'",
                     'move: Follow Me')

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
        """convert_battle and format_battle reproduce the four committed headers: the code --check runs."""
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'traces'))
                       if f.endswith('.json'))
        pool_names = [n for n in names if trace_to_c.is_pool(ROOT, n)]
        self.assertGreater(len(pool_names), 0)
        for team_c, pool, fname in ((False, False, 'conformance.h'), (True, False, 'conformance_team_c.h'),
                                    (True, True, 'conformance_pool.h')):
            with self.subTest(fname):
                chosen = [n for n in names if trace_to_c.is_pool(ROOT, n) == pool and
                          (pool or trace_to_c.is_team_c(ROOT, n) == team_c)]
                text, _, _ = trace_to_c.build_header(ROOT, chosen, tables(team_c), team_c, pool)
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

    def test_the_tie_of_two_fairy_aura_handlers_is_a_dropped_draw(self):
        """g12_fairy_aura_both: both Floettes are Mega with the same Speed, so their Fairy Aura handlers tie in the
        BasePower event of every damaging move. Exactly one of them applies (move.auraBooster) whichever runs first, so
        each draw is dropped, with its reason, and the battle converts; any other handler in the group is refused."""
        name = 'g12_fairy_aura_both'
        spec, trace = battle(name)
        data = convert(name, spec, trace)
        found = [(k, d) for k, step in enumerate(trace['steps']) for d in step['draws'] if d.get('context') == 'event:BasePower']
        self.assertGreater(len(found), 4)
        for k, d in found:
            self.assertEqual(d['site'], 'SPEED_TIE')
            self.assertEqual(sorted(d['group']), ['H:fairyaura:p1a:cb', 'H:fairyaura:p2a:cb'])
            before = trace['steps'][k - 1]['state'] if k else trace['start']['state']
            self.assertEqual(trace_to_c.drop_reason(d, before, trace['steps'][k]['state']),
                             'Fairy Aura handlers whose order changes nothing')
        k, d = found[0]
        before = trace['steps'][k - 1]['state'] if k else trace['start']['state']
        after = trace['steps'][k]['state']
        for group, context in ((['H:fairyaura:p1a:cb', 'H:lifeorb:p2a:cb'], 'event:BasePower'),
                               (['H:fairyaura:p1a:cb', 'H:fairyaura:p2a:end'], 'event:BasePower'),
                               (['H:fairyaura:p1a:cb', 'H:fairyaura:p2a:cb'], 'event:ModifyDamage')):
            with self.subTest(group=group, context=context), self.assertRaises(trace_to_c.ConversionError) as cm:
                trace_to_c.drop_reason(dict(d, group=group, context=context), before, after)
            self.assertEqual(cm.exception.rule, 'modifydamage-tie' if context == 'event:ModifyDamage' else 'tie-context')
        self.assertTrue(all(len(step['tape']) + step['dropped'] == len(trace['steps'][k]['draws'])
                            for k, step in enumerate(data['steps'])))

    def test_life_orb_ties_with_any_resist_berry_of_the_family_and_nothing_else(self):
        """The AWS finding fz_9810000_780 (2026-10-03): a ModifyDamage tie of the attacker's Life Orb and the target's Occa
        Berry. Every resist berry of the RESIST_BERRY family of the pool tables has the one modifier that Chople Berry
        has, so the pair commutes; the family is read from the generated tables, not listed here."""
        def tie(group):
            return trace_to_c.drop_reason({'site': 'SPEED_TIE', 'context': 'event:ModifyDamage', 'group': group}, {})
        family = trace_to_c.resist_berries()
        self.assertGreaterEqual(len(family), 18)  # Chople Berry and the seventeen others (decision 0015)
        for name in ('chopleberry', 'occaberry', 'chilanberry', 'yacheberry'):
            self.assertIn(name, family)
        for name in family:
            for group in (['H:lifeorb:p1a:cb', 'H:%s:p2a:cb' % name], ['H:%s:p2b:cb' % name, 'H:lifeorb:p1b:cb']):
                self.assertEqual(tie(group), 'Life Orb and a resist berry, whose modifiers commute')
        for bad in (['H:lifeorb:p1a:cb', 'H:sitrusberry:p2a:cb'], ['H:lifeorb:p1a:cb', 'H:leftovers:p2a:cb'],
                    ['H:occaberry:p1a:cb', 'H:chopleberry:p2a:cb'], ['H:lifeorb:p1a:cb', 'H:lifeorb:p2a:cb'],
                    ['H:lifeorb:p1a:cb', 'H:occaberry:p2a:cb', 'H:chopleberry:p2b:cb']):
            with self.subTest(group=bad), self.assertRaises(trace_to_c.ConversionError) as cm:
                tie(bad)
            self.assertEqual(cm.exception.rule, 'modifydamage-tie')

    def test_friend_guard_ties_step_g35(self):
        """Friend Guard (step G35, 0.75) joins the ModifyDamage handlers; the campaign's seed 3501 had its two holders (one on
        each side) tie in one hit. At most one of the handlers applies to a hit (its holder's allies other than itself), so a
        group with the handler twice is still one value in every order; a second handler of another kind twice stays refused."""
        def tie(group):
            return trace_to_c.drop_reason({'site': 'SPEED_TIE', 'context': 'event:ModifyDamage', 'group': group}, {})
        self.assertEqual(trace_to_c.modify_damage_values()['friendguard'], 3072)
        for group in (['H:friendguard:p1a:cb', 'H:friendguard:p2b:cb'], ['H:friendguard:p1a:cb', 'H:lifeorb:p2a:cb'],
                      ['H:friendguard:p1a:cb', 'H:friendguard:p1b:cb', 'H:lifeorb:p2a:cb'],
                      ['H:friendguard:p1a:cb', 'H:multiscale:p2a:cb', 'H:lifeorb:p2b:cb']):
            with self.subTest(group=group):
                self.assertEqual(tie(group), 'ModifyDamage modifiers whose every order chains to the same value')
        for bad in (['H:lifeorb:p1a:cb', 'H:lifeorb:p2a:cb', 'H:friendguard:p1b:cb'],  # two Life Orbs are no state of one hit
                    ['H:expertbelt:p1a:cb', 'H:multiscale:p2a:cb', 'H:friendguard:p2b:cb'],  # does not commute: refused by the engine
                    ['H:friendguard:p1a:cb', 'H:friendguard:p1b:cb', 'H:lifeorb:p2a:cb', 'H:lifeorb:p2b:cb']):
            with self.subTest(group=bad), self.assertRaises(trace_to_c.ConversionError) as cm:
                tie(bad)
            self.assertEqual(cm.exception.rule, 'modifydamage-tie')

    def test_aura_guard_ties_mega_batch_2(self):
        """Aura Guard (Mega batch 2, 0.5) joins the ModifyDamage handlers as the target's one ability, with Solid Rock and
        Multiscale: a tie with a Life Orb attacker and a screen (three modifiers that commute) is one value in every order;
        two ability handlers on one target are no state of one hit, and an Expert Belt with Glaive Rush and Aura Guard does
        not commute (refused by the engine, so refused here)."""
        def tie(group):
            return trace_to_c.drop_reason({'site': 'SPEED_TIE', 'context': 'event:ModifyDamage', 'group': group}, {})
        self.assertEqual(trace_to_c.modify_damage_values()['auraguard'], 2048)
        same = 'ModifyDamage modifiers whose every order chains to the same value'
        for group in (['H:auraguard:p1a:cb', 'H:lifeorb:p2a:cb'], ['H:auraguard:p1a:cb', 'H:lifeorb:p2a:cb', 'H:reflect:p1:cb'],
                      ['H:auraguard:p1a:cb', 'H:friendguard:p1b:cb', 'H:lifeorb:p2a:cb']):
            with self.subTest(group=group):
                self.assertEqual(tie(group), same)
        for bad in (['H:expertbelt:p2a:cb', 'H:glaiverush:p1a:cb', 'H:auraguard:p1a:cb'],  # does not commute
                    ['H:expertbelt:p2a:cb', 'H:auraguard:p1a:cb', 'H:friendguard:p1b:cb']):  # does not commute
            with self.subTest(group=bad), self.assertRaises(trace_to_c.ConversionError) as cm:
                tie(bad)
            self.assertEqual(cm.exception.rule, 'modifydamage-tie')
        # the subsets one hit can have: Aura Guard is exclusive with Solid Rock and Multiscale (the target's one ability)
        values = trace_to_c.modify_damage_values()
        subsets = trace_to_c.modifier_subsets(['auraguard', 'multiscale', 'solidrock'], values)
        self.assertEqual(sorted(subsets), [[2048], [2048], [3072]])

    def test_a_flower_veil_block_is_the_activate_event_of_the_ability_with_the_holder_in_other(self):
        """-block|protected|ability: Flower Veil|[of] holder (step G12): ACTIVATE at the protected Pokemon, cause ABILITY,
        the ability's id + 1, the holder in `other` (the ability's own activation has none); another -block is refused."""
        pool = tables(True)
        line = '|-block|p1b: Rillaboom|ability: Flower Veil|[of] p1a: Floette'
        events = trace_to_c.step_events([line], 0, {}, {}, pool)
        self.assertEqual(events, [trace_to_c.ev_tuple(trace_to_c.EV['ACTIVATE'], 1, 0, trace_to_c.CAUSE['ABILITY'], 0,
                                                      pool['ABILITY']['FLOWERVEIL'] + 1)])
        for bad in ('|-block|p1b: Rillaboom|ability: Flower Veil',  # no [of]
                    '|-block|p1b: Rillaboom|move: Protect|[of] p1a: Floette',
                    '|-block|p1b: Rillaboom|ability: Flower Veil|extra|[of] p1a: Floette'):
            with self.subTest(bad), self.assertRaises(trace_to_c.ConversionError) as cm:
                trace_to_c.step_events([bad], 0, {}, {}, pool)
            self.assertEqual(cm.exception.rule, 'block-line')
        # The converted battles have the event: the opening Intimidate and the Hypnosis of g12_flower_veil_a/_b.
        for name in ('g12_flower_veil_a', 'g12_flower_veil_b'):
            spec, trace = battle(name)
            logs = [l for step in trace['steps'] for l in step['log'] if l.startswith('|-block|')]
            self.assertTrue(logs, name)
            convert(name, spec, trace)

    def test_the_tie_of_two_no_guard_handlers_is_a_dropped_draw(self):
        """d01_noguard_accuracy_tie (a cut of fz_1_118 of the differential loop's seed 1): both Raichu are Mega Raichu Y,
        whose No Guard handlers tie in the Accuracy event of the first attack. The draw is dropped, with its reason,
        and is no tape entry; the battle converts."""
        name = 'd01_noguard_accuracy_tie'
        spec, trace = battle(name)
        data = convert(name, spec, trace)
        found = [(k, d) for k, step in enumerate(trace['steps']) for d in step['draws'] if d.get('context') == 'event:Accuracy']
        self.assertEqual(len(found), 1)
        k, d = found[0]
        self.assertEqual((d['site'], d['group']), ('SPEED_TIE', ['H:noguard:p1b:cb', 'H:noguard:p2b:cb']))
        before, after = trace['steps'][k - 1]['state'], trace['steps'][k]['state']
        self.assertEqual(trace_to_c.drop_reason(d, before, after), 'No Guard handlers whose order changes nothing')
        # The order of the two does not matter to the rule: a tie of the same two the other way round is dropped as well.
        flipped = dict(d, group=list(reversed(d['group'])))
        self.assertEqual(trace_to_c.drop_reason(flipped, before, after), 'No Guard handlers whose order changes nothing')
        step = data['steps'][k]
        dropped = [x for x in trace['steps'][k]['draws'] if trace_to_c.side_end_tie(x, before) is None
                   and trace_to_c.drop_reason(x, before, after) is not None]
        self.assertIn(d, dropped)
        self.assertEqual((step['dropped'], len(step['tape']) + step['dropped']), (len(dropped), len(trace['steps'][k]['draws'])))

    def test_heal_block_end_ties_are_kept_when_two_end_lines_show_their_order(self):
        """Two Heal Blocks of holders of equal Speed that end in the same residual (g8_heal_block_tie_a and _b, the two
        orders): the tie is a tape entry that states which line comes first (the lower position's: 0), the same
        for the draw and for the lines. A tie of which fewer than two end (turn 1 of the same battles) is dropped, with the
        step's log as the precondition; reaching the drop with two end lines, or without a log, is an error; a group of
        three is refused, and a draw that contradicts the lines is an error and never an entry."""
        for name in ('g8_heal_block_tie_a', 'g8_heal_block_tie_b'):
            trace = json.load(open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json')))
            kept, dropped = [], []
            for k, step in enumerate(trace['steps']):
                before = trace['start']['state'] if k == 0 else trace['steps'][k - 1]['state']
                for d in step['draws']:
                    if d['site'] != 'SPEED_TIE' or not all(g.startswith('H:healblock:') for g in d.get('group', ['x'])):
                        continue
                    entry = trace_to_c.heal_block_end_tie(d, step['log'])
                    if entry is not None:
                        kept.append((k, entry, d))
                        with self.assertRaises(trace_to_c.ConversionError) as ctx:
                            trace_to_c.drop_reason(d, before, step['state'], step['log'])
                        self.assertEqual(ctx.exception.rule, 'heal-block-end-tie')
                    else:
                        dropped.append(k)
                        self.assertEqual(trace_to_c.drop_reason(d, before, step['state'], step['log']),
                                         'residual tie of Heal Block ends of which fewer than two end now')
                        with self.assertRaises(trace_to_c.ConversionError) as ctx:
                            trace_to_c.drop_reason(d, before, step['state'])
                        self.assertEqual(ctx.exception.rule, 'heal-block-tie-log')
            self.assertEqual(len(kept), 1, name)
            self.assertEqual(len(dropped), 1, name)
            k, entry, d = kept[0]
            lines = [l for l in trace['steps'][k]['log'] if l.startswith('|-end|') and l.endswith('|move: Heal Block')]
            self.assertEqual(len(lines), 2)
            lower_first = lines[0].startswith('|-end|p1a')
            self.assertEqual(entry, (trace_to_c.SITES['SPEED_TIE'], 0, 2, d['value'] - d['start']), name)  # the draw as it is
            # name a: the line of p1a is first, name b: the line of p2a
            self.assertEqual(lower_first, name.endswith('_a'))
            # The same draw with the lines in the other order contradicts the draw: an error, no entry.
            flipped = [lines[1], lines[0]]
            with self.assertRaises(trace_to_c.ConversionError) as ctx:
                trace_to_c.heal_block_end_tie(d, flipped)
            self.assertEqual(ctx.exception.rule, 'heal-block-end-order')
            # Fewer than two end lines: no order shows, no entry.
            self.assertIsNone(trace_to_c.heal_block_end_tie(d, lines[:1]))
            self.assertIsNone(trace_to_c.heal_block_end_tie(d, []))
            # Three holders in the group with two ending: refused.
            three = dict(d, group=d['group'] + ['H:healblock:p1b:end'])
            with self.assertRaises(trace_to_c.ConversionError) as ctx:
                trace_to_c.heal_block_end_tie(three, trace['steps'][k]['log'])
            self.assertEqual(ctx.exception.rule, 'heal-block-tie-size')
            # A tie that is not of Heal Block ends is not this rule's.
            self.assertIsNone(trace_to_c.heal_block_end_tie(dict(d, group=['H:protect:p1a:end', 'H:stall:p1a:end']),
                                                            trace['steps'][k]['log']))

    def test_a_protect_and_stall_tie_is_kept_only_when_the_battle_ends_and_the_holder_stands(self):
        """The residual tie of one Pokemon's Protect volatile and its stall counter (every Protect turn has one) is kept
        as an entry that states the outcome (0: the stall counter ran first, 1: Protect's volatile did, whatever the
        group's pre-shuffle order) when the battle ended in the step and the holder has not fainted; any other time it
        is no entry here (the drop rule takes it), and a kept one never reaches the drop rule."""
        def draw(group, value, start=3):
            return {'site': 'SPEED_TIE', 'context': 'field:Residual', 'lo': start, 'hi': start + 2, 'value': value,
                    'group': group, 'start': start}

        def after(ended, p1a_fainted=False):
            side = lambda fainted: {'active': [0, 1], 'pokemon': [{'fainted': fainted}, {'fainted': False}]}
            return {'ended': ended, 'sides': [side(p1a_fainted), side(False)]}

        stall_first = ['H:stall:p1a:end', 'H:protect:p1a:end']
        protect_first = ['H:protect:p1a:end', 'H:stall:p1a:end']
        spec = trace_to_c.SITES['SPEED_TIE']
        # the draw keeps the order (value = start) or swaps it, from either pre-shuffle order
        self.assertEqual(trace_to_c.no_order_end_tie(draw(stall_first, 3), after(True)), (spec, 0, 2, 0))
        self.assertEqual(trace_to_c.no_order_end_tie(draw(stall_first, 4), after(True)), (spec, 0, 2, 1))
        self.assertEqual(trace_to_c.no_order_end_tie(draw(protect_first, 3), after(True)), (spec, 0, 2, 1))
        self.assertEqual(trace_to_c.no_order_end_tie(draw(protect_first, 4), after(True)), (spec, 0, 2, 0))
        # Spiky Shield's volatile is the same handler
        self.assertEqual(trace_to_c.no_order_end_tie(draw(['H:stall:p2b:end', 'H:spikyshield:p2b:end'], 4), after(True)),
                         (spec, 0, 2, 1))
        # no end, or a holder that fainted: no entry
        self.assertIsNone(trace_to_c.no_order_end_tie(draw(stall_first, 4), after(False)))
        self.assertIsNone(trace_to_c.no_order_end_tie(draw(stall_first, 4), after(True, p1a_fainted=True)))
        self.assertIsNone(trace_to_c.no_order_end_tie(draw(stall_first, 4), None))
        # a bigger group, two holders, other handlers, other contexts and sites are not this rule's
        for group in (stall_first + ['H:helpinghand:p1a:end'], ['H:stall:p1a:end', 'H:protect:p1b:end'],
                      ['H:stall:p1a:end', 'H:leftovers:p1a:cb'], ['H:stall:p1a:end', 'H:stall:p1b:end']):
            self.assertIsNone(trace_to_c.no_order_end_tie(draw(group, 4), after(True)), group)
        self.assertIsNone(trace_to_c.no_order_end_tie(dict(draw(stall_first, 4), context='event:Accuracy'), after(True)))
        # a shuffle that is not random(start, start + 2) is an error and never an entry
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.no_order_end_tie(dict(draw(stall_first, 4), hi=6), after(True))
        self.assertEqual(ctx.exception.rule, 'no-order-end-shuffle')
        # the drop rule drops the tie the rule does not keep, and refuses one that it keeps
        before = after(False)
        self.assertEqual(trace_to_c.drop_reason(draw(stall_first, 4), before, after(False)), 'residual tie of duration counters')
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.drop_reason(draw(stall_first, 4), before, after(True))
        self.assertEqual(ctx.exception.rule, 'no-order-end-tie')
        # G56: one lockedmove (a callback) and the silent ends of stall and Protect: the tie is dropped; the other shapes stay refused
        lock_group = ['H:lockedmove:p2b:cb', 'H:stall:p2b:end']
        self.assertTrue(trace_to_c.lock_counter_tie(lock_group))
        self.assertTrue(trace_to_c.lock_counter_tie(['H:protect:p1a:end', 'H:lockedmove:p2b:cb', 'H:stall:p2b:end']))
        self.assertIn('lockedmove', trace_to_c.drop_reason(draw(lock_group, 4), before, after(False)))
        for group in (['H:lockedmove:p2b:cb', 'H:lockedmove:p1b:cb', 'H:stall:p2b:end'], ['H:lockedmove:p2b:cb', 'H:disable:p2b:end']):
            self.assertFalse(trace_to_c.lock_counter_tie(group), group)
            with self.assertRaises(trace_to_c.ConversionError) as ctx:
                trace_to_c.drop_reason(draw(group, 4), before, after(False))
            self.assertEqual(ctx.exception.rule, 'residual-tie-callbacks', group)

    # ---- the weather step (Sandstorm, Snowscape; decision 0018, view bits 0 and 1) ----
    WEATHER_BATTLES = ('w1_sand_stream', 'w2_sandstorm_move', 'w3_snow_warning', 'w4_snowscape_move',
                       'w5_sand_tie_four', 'w5_sand_tie_pairs', 'w5_sand_tie_mixed', 'w6_sand_residual_order',
                       'w7_sand_ko_sitrus', 'w8_sand_soak')

    def weather_ties(self, name):
        """(step, draw, drop reason) of the each:Weather draws of a committed battle, with the step's log."""
        spec, trace = battle(name)
        found = []
        for k, step in enumerate(trace['steps']):
            before = trace['steps'][k - 1]['state'] if k else None
            for d in step['draws']:
                if d['site'] == 'SPEED_TIE' and d.get('context') == 'each:Weather':
                    found.append((k, d, trace_to_c.drop_reason(d, before, step['state'], step['log']), step['log']))
        return found

    def test_the_weather_rows_of_the_view_are_what_the_weather_lines_say(self):
        """Decision 0018 section 6.1, weather values Sand and Snow: a -weather line that names a weather sets it for 5
        turns, each [upkeep] line is a turn gone, -weather|none ends it. The rows of the C test (weather_rows in
        tests/test_pool_weather.c: the weather and the turns left after each step of the nine weather battles, for
        both players) must be exactly what these lines give for the committed traces, so that the engine's view is
        checked against the protocol and not against itself."""
        source = open(os.path.join(ROOT, 'tests', 'test_pool_weather.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(w\d_\w+)", (\d+)u, (\d)u, (\d)u\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3)), int(m.group(4)))
        code = {'Sandstorm': 3, 'Snowscape': 4, 'RainDance': 1, 'SunnyDay': 2}
        derived = {}
        for name in self.WEATHER_BATTLES:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            weather, turns = 0, 0
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3 or part[1] != '-weather':
                        continue
                    if part[2] == 'none':
                        weather, turns = 0, 0
                    elif '[upkeep]' in part:
                        turns -= 1
                    else:
                        weather, turns = code[part[2]], 5
                derived[(name, k)] = (weather, turns)
        self.assertEqual(rows, derived)
        values = {v[0] for v in derived.values()}
        self.assertTrue({0, 3, 4} <= values)  # both new weathers are shown, and they end

    TERRAIN_BATTLES = ['g25_electric_surge_voltage', 'g25_electric_seed', 'g25_misty_terrain', 'g25_terrain_pulse_psychic_misty',
                       'g25_terrain_pulse_electric', 'g25_weather_ball_refrigerate', 'g25_misty_hurricane']

    def test_the_terrain_rows_of_the_view_are_what_the_field_lines_say(self):
        """Decision 0018 section 6.1, terrain values Electric and Misty (step G25): a -fieldstart line that names a terrain sets
        it for 5 turns (the replaced terrain ends without a line), each |upkeep line with a terrain up is one turn gone, a
        -fieldend line ends it (Misty Terrain's has no "move: " in it). The rows of the C test (terrain_rows in
        tests/test_pool_terrain.c: the terrain and the turns left after each step of the seven battles, for both players)
        must be exactly what these lines give for the committed traces, so that the engine's view is checked against the
        protocol and not against itself."""
        with open(os.path.join(ROOT, 'tests', 'test_pool_terrain.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g25_\w+)", (\d+)u, (\d)u, (\d)u\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3)), int(m.group(4)))
        code = {'move: Grassy Terrain': 1, 'move: Psychic Terrain': 2, 'move: Electric Terrain': 3, 'move: Misty Terrain': 4}
        derived = {}
        for name in self.TERRAIN_BATTLES:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            terrain, turns = 0, 0
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 2:
                        continue
                    if part[1] == '-fieldstart' and part[2] in code:
                        terrain, turns = code[part[2]], 5
                    elif part[1] == '-fieldend':
                        self.assertIn(part[2], tuple(code) + ('Misty Terrain',))
                        terrain, turns = 0, 0
                    elif part[1] == 'upkeep' and terrain:
                        turns -= 1
                derived[(name, k)] = (terrain, turns)
        self.assertEqual(rows, derived)
        values = {v[0] for v in derived.values()}
        self.assertTrue({0, 2, 3, 4} <= values)  # both new terrains are shown, and they end

    def test_every_terrain_line_the_battles_show_is_a_known_start_end_or_block(self):
        """The field lines of the terrain battles: starts from an ability ([from] ability: Electric Surge or Psychic Surge with
        [of]) or a move (no attribute), the ends (with the one that has no "move: "), and the -activate lines of the status
        refusals; the converter maps each to its event."""
        starts, ends, blocks = set(), set(), set()
        for name in self.TERRAIN_BATTLES:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            for step in trace['steps']:
                for line in step['log']:
                    part = line.split('|')
                    if len(part) > 2 and part[1] == '-fieldstart':
                        starts.add((part[2], part[3] if len(part) > 3 else ''))
                    if len(part) > 2 and part[1] == '-fieldend':
                        ends.add(part[2])
                    if len(part) > 3 and part[1] == '-activate' and 'Terrain' in part[3]:
                        blocks.add(part[3])
        self.assertEqual({s[0] for s in starts}, {'move: Electric Terrain', 'move: Misty Terrain', 'move: Psychic Terrain'})
        self.assertIn(('move: Electric Terrain', '[from] ability: Electric Surge'), starts)
        self.assertIn(('move: Psychic Terrain', '[from] ability: Psychic Surge'), starts)
        self.assertEqual(ends, {'move: Electric Terrain', 'Misty Terrain'})
        self.assertEqual(blocks, {'move: Electric Terrain', 'move: Misty Terrain'})
        self.assertEqual((trace_to_c.FIELD_ELECTRIC_TERRAIN, trace_to_c.FIELD_MISTY_TERRAIN), (4, 5))
        self.assertEqual((trace_to_c.TERRAIN['electricterrain'], trace_to_c.TERRAIN['mistyterrain']), (3, 4))

    def test_every_weather_line_the_battles_show_is_a_known_start_end_or_upkeep(self):
        """The -weather lines of the weather battles: starts from an ability ([from] ability: Sand Stream or Snow Warning
        with [of]) or a move (no attribute), the upkeep, and none; and the damage lines [from] Sandstorm, the
        Sandstorm of the move whose line names it, nothing else."""
        starts, causes = set(), set()
        for name in self.WEATHER_BATTLES:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            for step in trace['steps']:
                for line in step['log']:
                    part = line.split('|')
                    if len(part) > 2 and part[1] == '-weather' and part[2] != 'none' and '[upkeep]' not in part:
                        starts.add((part[2], part[3] if len(part) > 3 else ''))
                    if len(part) > 3 and part[1] == '-damage' and part[-1].startswith('[from] ') and 'item' not in part[-1]:
                        causes.add(part[-1])
        self.assertEqual(starts, {('Sandstorm', ''), ('Sandstorm', '[from] ability: Sand Stream'), ('Snowscape', ''),
                                  ('Snowscape', '[from] ability: Snow Warning'), ('RainDance', '[from] ability: Drizzle')})
        self.assertEqual(causes, {'[from] Sandstorm', '[from] psn', '[from] brn'})
        pool = trace_to_c.load_tables(ROOT, True)
        self.assertEqual(trace_to_c.ev_cause(['[from] Sandstorm'], pool)[:2], (trace_to_c.CAUSE['WEATHER'], 3))
        self.assertEqual(trace_to_c.WEATHER_LINE['Snowscape'], 4)
        self.assertEqual(trace_to_c.WEATHER['snowscape'], 4)

    def test_sandstorm_damage_ties_are_kept_when_two_tied_pokemon_take_damage(self):
        """Under Sandstorm every active Pokemon has the weather's onWeather, so eachEvent('Weather') shuffles every tie of
        Speed (the group is all the tied actives); the order shows only between two that take the damage. w5_sand_tie_four
        (four of Speed 101: two Milotic, two immune Tyranitar) keeps its draws; in w5_sand_tie_pairs the pair of Milotic
        keeps them and the pair of Tyranitar (immune) is dropped; in w5_sand_tie_mixed a Milotic and a Tyranitar tie and
        the draw is dropped (one damage line shows no order). The other weather battles have no such tie."""
        for name, expect in (('w5_sand_tie_four', {True}), ('w5_sand_tie_pairs', {True, False}),
                             ('w5_sand_tie_mixed', {False})):
            with self.subTest(name):
                found = self.weather_ties(name)
                self.assertTrue(found)
                kept = {reason is None for _k, _d, reason, _log in found}
                self.assertEqual(kept, expect)
                for _k, d, reason, log in found:
                    self.assertTrue(reason is None or 'Sandstorm' in reason)
                    damaged = {l.split('|')[2].split(':')[0] for l in log
                               if l.startswith('|-damage|') and l.endswith('|[from] Sandstorm')}
                    slots = [g.split(':')[1] for g in d['group']]
                    self.assertEqual(reason is None, sum(1 for x in slots if x in damaged) >= 2)
        for name in ('w1_sand_stream', 'w2_sandstorm_move', 'w3_snow_warning', 'w4_snowscape_move',
                     'w6_sand_residual_order', 'w7_sand_ko_sitrus'):
            with self.subTest(name):
                self.assertEqual([k for k in self.weather_ties(name) if k[2] is None], [])

    def test_a_weather_tie_with_a_handler_the_converter_does_not_know_is_refused(self):
        found = self.weather_ties('w5_sand_tie_four')
        _k, d, _reason, log = found[0]
        other = dict(d, group=[d['group'][0].replace('sandstorm', 'sandstorm+dryskin')] + d['group'][1:])
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            trace_to_c.drop_reason(other, None, None, log)
        self.assertEqual((cm.exception.rule, cm.exception.detail), ('weather-tie-handlers', 'dryskin+sandstorm'))
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            trace_to_c.drop_reason(d, None, None, None)
        self.assertEqual(cm.exception.rule, 'weather-tie-log')
        # Without Sandstorm the event has no handler at all, and the tie is dropped as every each: tie of no holder.
        rain = dict(d, group=['P:%s:0:' % g.split(':')[1] for g in d['group']])
        self.assertEqual(trace_to_c.drop_reason(rain, None, None, log), 'each-event tie with at most one holder')

    def test_rain_dish_weather_ties_step_g35(self):
        """Rain Dish's onWeather (step G35) is a handler of its holder alone, and only in rain: two holders tied in rain keep the
        draw (the engine draws among the tied holders, dfi_rain_dish), one holder or two holders in another weather drop it, and
        under Sandstorm the holder's handler is not one that the converter does not know."""
        def tie(*handlers):
            return {'site': 'SPEED_TIE', 'context': 'each:Weather',
                    'group': ['P:p%d%s:%d:%s' % (1 + i // 2, 'ab'[i % 2], len(h.split('+')) if h else 0, h)
                              for i, h in enumerate(handlers)]}
        two = tie('raindish', '', 'raindish')
        two['group'][1] = 'P:p1b:0:'
        rain, sun = {'weather': 'raindance'}, {'weather': 'sunnyday'}
        self.assertIsNone(trace_to_c.drop_reason(two, rain, rain, []))
        self.assertEqual(trace_to_c.drop_reason(two, sun, sun, []), 'each-event tie with at most one holder')
        # the weather of the step's end counts when there is one (rain that came in this step)
        self.assertIsNone(trace_to_c.drop_reason(two, sun, rain, []))
        one = tie('raindish', '', '')
        self.assertEqual(trace_to_c.drop_reason(one, rain, rain, []), 'each-event tie with at most one holder')
        # Sandstorm: every Pokemon has the weather's handler, a Rain Dish holder one more that does nothing
        sand = {'weather': 'sandstorm'}
        group = ['P:p1a:2:sandstorm+raindish', 'P:p1b:1:sandstorm', 'P:p2a:1:sandstorm']
        log = ['|-damage|p1a: X|90/100|[from] Sandstorm', '|-damage|p1b: Y|90/100|[from] Sandstorm']
        self.assertIsNone(trace_to_c.drop_reason(dict(two, group=group), sand, sand, log))

    def test_view_extension_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Throat Chop and Heal Block: a position has the bit from the -start line
        (`|-start|X|Throat Chop|[silent]`, `|-start|X|move: Heal Block`) until the matching -end line, or until the
        occupant leaves (`|switch|`, `|drag|`, `|replace|`, `|faint|`). The rows of the C test (view_ext_rows in
        tests/test_pool_g8.c: the expected view extension after each step of the G8 battles, for both viewers, as
        masks over side * 2 + slot) must be exactly what these lines give for the committed traces, so the engine's
        extension is checked against the protocol and not against itself."""
        names = ('g8_throat_chop', 'g8_heal_block', 'g8_heal_block_pair', 'g8_heal_block_tie_a', 'g8_heal_block_tie_b')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g8.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g8_\w+)", (\d+)u, 0x([0-9a-f])u, 0x([0-9a-f])u\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3), 16), int(m.group(4), 16))
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            throat, block = set(), set()
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    if part[1] in ('switch', 'drag', 'faint', 'replace'):
                        throat.discard(part[2][:3])
                        block.discard(part[2][:3])
                    elif part[1] == '-start' and len(part) > 3 and part[3] == 'Throat Chop':
                        self.assertEqual(part[-1], '[silent]')
                        throat.add(part[2][:3])
                    elif part[1] == '-end' and len(part) > 3 and part[3] == 'Throat Chop':
                        throat.discard(part[2][:3])
                    elif part[1] == '-start' and len(part) > 3 and part[3] == 'move: Heal Block':
                        block.add(part[2][:3])
                    elif part[1] == '-end' and len(part) > 3 and part[3] == 'move: Heal Block':
                        block.discard(part[2][:3])

                def mask(s):
                    return sum(1 << ((int(x[1]) - 1) * 2 + 'ab'.index(x[2])) for x in s)

                derived[(name, k)] = (mask(throat), mask(block))
        self.assertEqual(rows, derived)
        # The battles do set and clear both: something is shown in each, and every row of the last step is empty.
        self.assertTrue(any(v[0] for v in derived.values()) and any(v[1] for v in derived.values()))

    def test_wide_guard_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Wide Guard: the side of the user has the guard from the
        `|-singleturn|X|Wide Guard` line until the next `|upkeep|` (a second Wide Guard of the same side prints no
        line and changes nothing). The rows of the C test (guard_rows in tests/test_pool_g7.c: the guard flag of each
        side after each step of the G7 battles, as a mask over the sides) must be exactly what these lines give for the
        committed traces, so a guard is live at a mid-turn (pivot) boundary and never at a turn boundary, and the
        engine's flag and view extension are checked against the protocol and not against themselves. Every
        `-activate|X|move: Wide Guard` is at a side whose guard is up, and every `-singleturn` Wide Guard comes
        from a move line of Wide Guard."""
        names = ('g7_wide_guard_a', 'g7_wide_guard_b', 'g7_wide_guard_ally', 'g7_wide_guard_pivot')
        with open(os.path.join(ROOT, 'tests', 'test_pool_g7.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g7_\w+)", (\d+)u, 0x([0-9a-f])u\}', source):
            rows[(m.group(1), int(m.group(2)))] = int(m.group(3), 16)
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            up = set()
            last_move = None
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 2:
                        continue
                    if part[1] == 'move':
                        last_move = part[3]
                    elif part[1] == '-singleturn' and len(part) > 3 and part[3] == 'Wide Guard':
                        self.assertEqual(last_move, 'Wide Guard')
                        up.add(int(part[2][1]) - 1)
                    elif part[1] == '-activate' and len(part) > 3 and part[3] == 'move: Wide Guard':
                        self.assertIn(int(part[2][1]) - 1, up, '%s step %d: %s' % (name, k, line))
                    elif part[1] == 'upkeep':
                        up.clear()
                derived[(name, k)] = sum(1 << s for s in up)
        self.assertEqual(rows, derived)
        # The guard is live at a boundary inside a turn in the pivot battle, and only there.
        self.assertEqual({k: v for k, v in derived.items() if v}, {('g7_wide_guard_pivot', 1): 1})

    def test_spiky_shield_rows_are_what_the_protocol_lines_say(self):
        """Decision 0015 section 7 for the Protect variant of tail rev 3: a position has protect_kind 1 from the
        `|-singleturn|X|move: Protect` line that follows its `|move|X|Spiky Shield|` line until the next `|upkeep|` or until
        its occupant leaves or faints (Protect and Detect print `-singleturn|X|Protect`: the variant 0). The rows of the C
        test (kind_rows in tests/test_pool_g20_protect.c: protect_kind of the four positions, side * 2 + slot, after each
        step of the G20 Spiky Shield battles) must be exactly what these lines give for the committed traces, so the
        variant is live at a boundary inside a turn (a pivot) and never at a turn boundary. Every contact move that a
        Spiky Shield stops is followed by `-damage|attacker|hp|[from] Spiky Shield|[of] holder`, a move without contact by
        nothing of the kind."""
        with open(os.path.join(ROOT, 'tests', 'test_pool_g20_protect.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g20_spiky\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = tuple(int(m.group(i)) for i in range(3, 7))
        names = sorted({n for n, _ in rows})
        self.assertTrue(names)
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g20_spiky\w+)"', listed)), names)
        contact = {'Iron Head', 'Sucker Punch', 'Double-Edge', 'U-turn', 'Wood Hammer', 'Brave Bird'}

        def flat(label):  # `p1a: Name` -> side * 2 + slot
            return (int(label[1]) - 1) * 2 + 'ab'.index(label[2])
        derived = {}
        punished = stopped_without = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            kind = [0, 0, 0, 0]
            last = None
            for k, step in enumerate(trace['steps']):
                lines = [l for l in step['log'] if not l.startswith('|split')]
                for i, line in enumerate(lines):
                    part = line.split('|')
                    if len(part) < 2:
                        continue
                    if part[1] == 'move':
                        last = (part[2], part[3])
                    elif part[1] == '-singleturn' and part[3] == 'move: Protect':
                        self.assertEqual(last[1], 'Spiky Shield', line)
                        kind[flat(part[2])] = 1
                    elif part[1] == '-activate' and part[3] == 'move: Protect' and kind[flat(part[2])] == 1:
                        nxt = lines[i + 1].split('|') if i + 1 < len(lines) else []
                        if last[1] in contact:
                            self.assertEqual(nxt[1:2], ['-damage'], '%s step %d: %s' % (name, k, line))
                            self.assertEqual(nxt[4:], ['[from] Spiky Shield', '[of] ' + part[2]])
                            punished += 1
                        else:
                            self.assertNotEqual(nxt[1:2], ['-damage'], '%s step %d: %s' % (name, k, line))
                            stopped_without += 1
                    elif part[1] == 'upkeep':
                        kind = [0, 0, 0, 0]
                    elif part[1] in ('switch', 'faint', 'drag'):
                        kind[flat(part[2])] = 0
                derived[(name, k)] = tuple(kind)
        self.assertEqual(rows, derived)
        self.assertTrue(any(any(v) for v in derived.values()) and punished > 0 and stopped_without > 0)

    def test_disable_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Disable: a position has the slot of the move named by `|-start|X|Disable|MOVE` (the
        slot of MOVE in the member's set, the spec's team text: the order of its `- Move` lines, from 1) until the
        `|-end|X|Disable` line or until its occupant leaves (`|switch|` at the position) or faints. The rows of the C test
        (slot_rows in tests/test_pool_g27.c: the barred slot of the four positions, side * 2 + slot, after each step of the G27
        battles) must be exactly what these lines give for the committed traces. Every `cant|X|Disable|MOVE` is of the barred
        move, a `-start` with [from] ability: Cursed Body comes after a hit at a holder of that ability, and the next move
        line of a barred position is never of its barred move."""
        with open(os.path.join(ROOT, 'tests', 'test_pool_g27.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g27_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = tuple(int(m.group(i)) for i in range(3, 7))
        names = sorted({n for n, _ in rows})
        self.assertTrue(names)
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g27_\w+)"', listed)), names)

        def flat(label):  # `p1a: Name` -> side * 2 + slot
            return (int(label[1]) - 1) * 2 + 'ab'.index(label[2])
        derived = {}
        cursed = moves = cants = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            sets = [[t for t in team.split('\n\n')] for team in spec['teams']]

            def moves_of(side, species):
                found = [t for t in sets[side] if t.startswith(species + ' ') or t.startswith(species + '\n')]
                self.assertEqual(len(found), 1, (name, species))
                return [l[2:] for l in found[0].split('\n') if l.startswith('- ')]
            slot = [0, 0, 0, 0]
            for k, step in enumerate(trace['steps']):
                lines = [l for l in step['log'] if not l.startswith('|split')]
                for i, line in enumerate(lines):
                    part = line.split('|')
                    if len(part) < 2:
                        continue
                    if part[1] == 'move':
                        who = flat(part[2])
                        if slot[who]:
                            moves += 1
                            species = part[2].split(': ')[1]
                            self.assertNotEqual(moves_of(who // 2, species)[slot[who] - 1], part[3], line)
                    elif part[1] == '-start' and part[3] == 'Disable':
                        who = flat(part[2])
                        species = part[2].split(': ')[1]
                        slot[who] = moves_of(who // 2, species).index(part[4]) + 1
                        if any(a.startswith('[from] ability: Cursed Body') for a in part[5:]):
                            cursed += 1
                    elif part[1] == '-end' and part[3] == 'Disable':
                        slot[flat(part[2])] = 0
                    elif part[1] == 'cant' and part[3] == 'Disable':
                        who = flat(part[2])
                        species = part[2].split(': ')[1]
                        self.assertEqual(moves_of(who // 2, species)[slot[who] - 1], part[4], line)
                        cants += 1
                    elif part[1] in ('switch', 'faint', 'drag'):
                        slot[flat(part[2])] = 0
                derived[(name, k)] = tuple(slot)
        self.assertEqual(rows, derived)
        self.assertTrue(any(any(v) for v in derived.values()) and cursed > 0 and cants > 0)

    def test_cursed_body_is_a_draw_site_of_its_own(self):
        """Cursed Body's randomChance(3, 10) (step G27) is a draw of the site CURSED_BODY, random(10), that ps_trace.js names
        by the effect and the event it runs in; the new public values are the numbers of the header."""
        self.assertEqual(trace_to_c.SITES['CURSED_BODY'], 17)
        self.assertEqual(trace_to_c.CAUSE['DISABLE'], 19)
        self.assertEqual(trace_to_c.VOLATILE_DISABLE, 4)
        with open(os.path.join(ROOT, 'tools', 'reference', 'ps_trace.js'), encoding='utf-8') as f:
            self.assertIn("'cursedbody:DamagingHit': 'CURSED_BODY'", f.read())

    def test_toxic_rows_are_what_the_protocol_lines_say(self):
        """Decision 0015 section 7 for the toxic stage (step G36): the occupant of a position is badly poisoned from the
        `|-status|X|tox` line until it faints (the status stays through a switch-out), and its stage (the tail's toxic_stage)
        is the number of `|-damage|X|HP tox|[from] psn` events since that line or since it last switched in (the stage
        starts again: tox's onSwitchIn), at most 15. The rows of the C test (rows in tests/test_pool_g36.c: bit 8 the status,
        the low byte the stage, of the four positions after each step) must be exactly that for the committed traces. The
        residual damage of tox names psn as its source, so no new cause exists, and the HP field carries the status tox."""
        self.assertEqual(trace_to_c.STATUS['tox'], 6)
        self.assertEqual(trace_to_c.AILMENT['tox'], 6)
        with open(os.path.join(ROOT, 'tests', 'test_pool_g36.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g36_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = tuple(int(m.group(i)) for i in range(3, 7))
        names = sorted({n for n, _ in rows})
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g36_\w+)"', listed)), names)
        self.assertEqual(names, sorted(n[:-5] for n in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs'))
                                       if n.startswith('g36_')))

        def flat(label):
            return (int(label[1]) - 1) * 2 + 'ab'.index(label[2])
        derived = {}
        damages = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            occupant, tox, stage = {}, set(), {}
            for k, step in enumerate(trace['steps']):
                prev = None
                for line in [l for l in step['log'] if not l.startswith('|split')]:
                    part = line.split('|')
                    dup = prev is not None and prev[1:3] == part[1:3] and len(part) > 1 and part[1] == '-damage'
                    prev = part
                    if dup or len(part) < 3:
                        continue  # the percentage line of the same event
                    key = None
                    if part[1] in ('switch', 'drag'):
                        occupant[flat(part[2])] = part[2].split(': ')[1]
                        stage[(flat(part[2]) // 2, occupant[flat(part[2])])] = 0
                    elif part[1] == '-status' and part[3] == 'tox':
                        key = (flat(part[2]) // 2, part[2].split(': ')[1])
                        tox.add(key)
                        stage[key] = 0
                    elif part[1] == '-damage' and len(part) > 4 and part[4] == '[from] psn' and ' tox' in part[3]:
                        key = (flat(part[2]) // 2, part[2].split(': ')[1])
                        stage[key] = min(stage.get(key, 0) + 1, 15)
                        damages += 1
                    elif part[1] == 'faint':
                        key = (flat(part[2]) // 2, part[2].split(': ')[1])
                        tox.discard(key)
                        stage[key] = 0
                row = []
                for f in range(4):
                    key = (f // 2, occupant.get(f))
                    row.append(((1 if key in tox else 0) << 8) | stage.get(key, 0))
                derived[(name, k)] = tuple(row)
        self.assertEqual(rows, derived)
        self.assertTrue(damages > 0 and any(v & 255 >= 3 for r in derived.values() for v in r))

    def test_taunt_and_yawn_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Taunt and Yawn (step G31): a position has Taunt (bit 0) from `|-start|X|move: Taunt`
        until `|-end|X|move: Taunt`, and Yawn (bit 1) from `|-start|X|move: Yawn|[of] SRC` until its `|-end|X|move: Yawn|[silent]`:
        the pin's onEnd of Yawn (data/moves.ts:21153-21156) prints that line and then tries the sleep, which is the
        `|-status|X|slp` line when it lands, or the terrain's `|-activate|X|move: Electric Terrain` (or Misty) line when the terrain
        refuses it (data/moves.ts:4518 and 12172); the volatile ends either way, so a refused sleep clears the bit as well.
        Both end when the occupant leaves (`|switch|` at the position) or faints. The rows of the C test (rows in
        tests/test_pool_g31.c) must be exactly what these lines give for the committed traces; the sleep that Yawn brings
        has no [from], there are `cant|X|move: Taunt|MOVE` lines, and the new public numbers are the header's."""
        self.assertEqual(trace_to_c.CAUSE['TAUNT'], 20)
        self.assertEqual(trace_to_c.VOLATILE_TAUNT, 6)
        self.assertEqual(trace_to_c.VOLATILE_YAWN, 7)
        with open(os.path.join(ROOT, 'tests', 'test_pool_g31.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g31_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = tuple(int(m.group(i)) for i in range(3, 7))
        names = sorted({n for n, _ in rows})
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g31_\w+)"', listed)), names)
        self.assertEqual(names, sorted(n[:-5] for n in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs'))
                                       if n.startswith('g31_')))

        def flat(label):
            return (int(label[1]) - 1) * 2 + 'ab'.index(label[2])
        derived = {}
        cants = sleeps = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            bits = [0, 0, 0, 0]
            for k, step in enumerate(trace['steps']):
                for line in [l for l in step['log'] if not l.startswith('|split')]:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    if part[1] == '-start' and part[3] == 'move: Taunt':
                        bits[flat(part[2])] |= 1
                    elif part[1] == '-end' and part[3] == 'move: Taunt':
                        bits[flat(part[2])] &= ~1
                    elif part[1] == '-start' and part[3] == 'move: Yawn':
                        bits[flat(part[2])] |= 2
                    elif part[1] == '-end' and part[3] == 'move: Yawn':
                        bits[flat(part[2])] &= ~2  # onEnd: the volatile ends (silently), whether the sleep lands or is refused
                    elif part[1] == '-status' and part[3] == 'slp':
                        self.assertEqual(len(part), 4, line)  # no [from]
                        bits[flat(part[2])] &= ~2
                        sleeps += 1
                    elif part[1] == 'cant' and part[3] == 'move: Taunt':
                        cants += 1
                    elif part[1] in ('switch', 'faint', 'drag'):
                        bits[flat(part[2])] = 0
                derived[(name, k)] = tuple(bits)
        self.assertEqual(rows, derived)
        self.assertTrue(cants > 0 and sleeps > 0 and any(any(v) for v in derived.values()))

    def test_hazard_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for the four entry hazards (step G37): a side has Stealth Rock or Sticky Web from its
        `|-sidestart|pN: X|move: ...` line, a layer of Spikes (`|-sidestart|pN: X|Spikes`, no `move: ` in its name) or of
        Toxic Spikes with each such line, and Toxic Spikes no more from the `|-sideend|pN: X|move: Toxic Spikes|[of] Y` line
        of a grounded Poison type that absorbed them. The rows of the C test (hazard_rows in tests/test_pool_g37.c: stealth
        rock, spikes, toxic spikes and sticky web of side 0, then of side 1, after each step of the G37 battles) must be
        exactly what these lines give for the committed traces, and what the reference's own state (the key `hazards` of the
        harness, in creation order) holds: the engine's tail and view are checked against the game and not against
        themselves. The last two numbers of a row are the creation order of each side (tail rev 4, hazard_order: two bits per
        slot, a new kind appended, an absorbed one removed, so one put up again goes last), the order of the first
        `-sidestart` lines that the protocol shows. The damage
        names the hazard as its source (`[from] Stealth Rock`, `[from] Spikes`): the cause is the move's, with its id."""
        names_ = ('stealthrock', 'spikes', 'toxicspikes', 'stickyweb')
        lines_of = {'move: Stealth Rock': 0, 'Spikes': 1, 'move: Spikes': 1, 'move: Toxic Spikes': 2, 'move: Sticky Web': 3}
        most = (1, 3, 2, 1)
        with open(os.path.join(ROOT, 'tests', 'test_pool_g37.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g37_\w+)", (\d+)u, \{((?:\d+u(?:, )?){10})\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = tuple(int(x[:-1]) for x in m.group(3).split(', '))
        names = sorted({n for n, _ in rows})
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g37_\w+)"', listed)), names)
        self.assertEqual(names, sorted(n[:-5] for n in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs'))
                                       if n.startswith('g37_')))
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            layers = [[0] * 4, [0] * 4]
            created = [[], []]
            for k, step in enumerate(trace['steps']):
                for line in [l for l in step['log'] if not l.startswith('|split')]:
                    part = line.split('|')
                    if len(part) > 3 and part[1] == '-sidestart' and part[3] in lines_of:
                        side, kind = int(part[2][1]) - 1, lines_of[part[3]]
                        self.assertLess(layers[side][kind], most[kind], '%s step %d: a hazard above its last layer' % (name, k))
                        if layers[side][kind] == 0:
                            created[side].append(kind)
                        layers[side][kind] += 1
                    elif len(part) > 3 and part[1] == '-sideend' and part[3] == 'move: Toxic Spikes':
                        self.assertEqual(len(part), 5)  # [of] the Pokemon that absorbed them
                        layers[int(part[2][1]) - 1][2] = 0
                        created[int(part[2][1]) - 1].remove(2)
                orders = tuple(sum(kind << (2 * slot) for slot, kind in enumerate(c)) for c in created)
                derived[(name, k)] = tuple(layers[0] + layers[1]) + orders
                # the reference's own state, in creation order
                state = [dict(side.get('hazards', [])) for side in step['state']['sides']]
                ref_orders = tuple(sum(names_.index(h[0]) << (2 * slot) for slot, h in enumerate(side.get('hazards', [])))
                                   for side in step['state']['sides'])
                self.assertEqual(tuple(state[0].get(n, 0) for n in names_) + tuple(state[1].get(n, 0) for n in names_) + ref_orders,
                                 derived[(name, k)], '%s step %d: the lines and the state of the reference differ' % (name, k))
        self.assertEqual(rows, derived)
        for kind in range(4):
            self.assertTrue(any(v[kind] or v[4 + kind] for v in derived.values()), names_[kind])
        self.assertTrue(any(3 in (v[1], v[5]) for v in derived.values()) and any(2 in (v[2], v[6]) for v in derived.values()))

    def test_aurora_veil_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Aurora Veil: a side has the screen from the `|-sidestart|pN: X|move: Aurora Veil`
        line (5 turns, 8 when the user of the move holds Light Clay: the sheet, which is the spec's team text) and its turns
        left count down at every `|upkeep|` line until the `-sideend` line of the screen ends it (at the residual where
        one turn is left). The rows of the C test (veil_rows in tests/test_pool_g20.c: the turns left of each side after
        each step of the G20 battles) must be exactly what these lines give for the committed traces, so the engine's
        tail and view extension are checked against the protocol and not against themselves. Every `-sidestart` comes from
        a move line of Aurora Veil of that side, and a `-sideend` comes with one turn left; a failed Aurora Veil (`-fail`
        after the move line) leaves the rows alone."""
        with open(os.path.join(ROOT, 'tests', 'test_pool_g20.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g20_\w+)", (\d+)u, \{(\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3)), int(m.group(4)))
        names = sorted({n for n, _ in rows})
        self.assertTrue(names)
        listed = re.search(r'names\[\] = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"(g20_\w+)"', listed)), names)
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            turns = [0, 0]
            last = None  # (user, move) of the last move line
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 2:
                        continue
                    if part[1] == 'move':
                        last = (part[2], part[3])
                    elif part[1] == '-sidestart' and part[3] == 'move: Aurora Veil':
                        side = int(part[2][1]) - 1
                        self.assertEqual(last[1], 'Aurora Veil')
                        self.assertEqual(int(last[0][1]) - 1, side)
                        self.assertEqual(turns[side], 0, '%s step %d: a second -sidestart' % (name, k))
                        species = last[0].split(': ')[1]
                        sets = [t for t in spec['teams'][side].split('\n\n') if t.startswith(species)]
                        self.assertEqual(len(sets), 1, species)
                        turns[side] = 8 if '@ Light Clay' in sets[0].split('\n')[0] else 5
                    elif part[1] == '-sideend' and part[3] == 'move: Aurora Veil':
                        side = int(part[2][1]) - 1
                        self.assertEqual(turns[side], 1, '%s step %d: %s' % (name, k, line))
                        turns[side] = 0
                    elif part[1] == 'upkeep':
                        turns = [t - 1 if t else 0 for t in turns]
                derived[(name, k)] = tuple(turns)
        self.assertEqual(rows, derived)
        # The battles have a screen of five turns and one of eight, one that ends, and both sides' at once.
        values = list(derived.values())
        self.assertTrue(any(max(v) > 5 for v in values) and any(all(v) for v in values) and any(sum(v) for v in values))

    def test_item_transfer_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Trick, Switcheroo, Thief and Covet (step G29): the item_now of every roster member
        after each step, and the numbers of `-item` and silent `-enditem ... [from] move:` lines, are what the committed
        traces' protocol lines say alone; the rows of tests/test_pool_g29.c must be exactly that. `|-item|X|Item|[from] move:
        M` gives X the item (item id + 1; a Thief's or Covet's `[of] Y` takes Y's away, 255), `|-enditem|X|Item|[silent]|[from]
        move: M` takes X's away; a used-up item and a switch change nothing. Also the converter: the lines are ITEM_START (cause
        MOVE) and ITEM_END (cause ITEM_TAKEN), and any other shape is refused."""
        names = ('g29_trick_scarf', 'g29_empty_hands', 'g29_thief_covet', 'g29_trick_fails', 'g29_edge_cases', 'g29_trick_lock_before_move', 'g29_thief_fainted')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g29.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g29_\w+)", (\d+)u, \{([^}]*)\}, (\d+)u, (\d+)u\}', source):
            codes = tuple(int(x.strip().rstrip('u')) for x in m.group(3).split(','))
            rows[(m.group(1), int(m.group(2)))] = (codes, int(m.group(4)), int(m.group(5)))
        tables = trace_to_c.load_tables(ROOT, True)
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            rosters = [re.findall(r'^([A-Za-z-]+)(?: \([MF]\))?(?: @|$)', text, re.M) for text in spec['teams']]
            held = [0] * 12

            def member(side, shown):
                # the name that the protocol shows: the species, or its first word (Arcanine-Hisui is shown as Arcanine)
                if shown in rosters[side]:
                    return rosters[side].index(shown)
                return [r.split('-')[0] for r in rosters[side]].index(shown)
            for k, step in enumerate(trace['steps']):
                received = left = 0
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 5 or part[1] not in ('-item', '-enditem'):
                        continue
                    from_move = [a for a in part[4:] if a.startswith('[from] move: ')]
                    if not from_move:
                        continue
                    side = int(part[2][1]) - 1
                    index = side * 6 + member(side, part[2][5:])
                    if part[1] == '-item':
                        held[index] = tables['ITEM'][trace_to_c.key(part[3])] + 1
                        received += 1
                        for a in part[4:]:
                            if a.startswith('[of] '):
                                of_side = int(a[6]) - 1
                                held[of_side * 6 + member(of_side, a[10:])] = 255
                    else:
                        held[index] = 255
                        left += 1
                derived[(name, k)] = (tuple(held), received, left)
        self.assertEqual(rows, derived)
        self.assertTrue(any(r > 0 for (_, r, _) in derived.values()) and any(l > 0 for (_, _, l) in derived.values()))
        # The converter.
        roster = [{'Sneasler': 0}, {'Staraptor': 0}]
        maxhp = [{'Sneasler': 100}, {'Staraptor': 100}]
        cases = (
            ('|-item|p2a: Staraptor|Sitrus Berry|[from] move: Trick', 'ITEM_START', 2, trace_to_c.NOPOS, 'Trick', 'Sitrus Berry'),
            ('|-item|p1a: Sneasler|Sitrus Berry|[from] move: Thief|[of] p2a: Staraptor', 'ITEM_START', 0, 2, 'Thief', 'Sitrus Berry'),
            ('|-item|p1a: Sneasler|Sitrus Berry|[from] move: Covet|[of] p2a: Staraptor', 'ITEM_START', 0, 2, 'Covet', 'Sitrus Berry'),
        )
        for line, kind, pos, other, move, item in cases:
            with self.subTest(line=line):
                (e,) = trace_to_c.step_events([line], 0, roster, maxhp, tables)
                self.assertEqual(e, (trace_to_c.EV[kind], pos, other, trace_to_c.CAUSE['MOVE'],
                                     tables['MOVE'][trace_to_c.key(move)], tables['ITEM'][trace_to_c.key(item)] + 1,
                                     0, 0, 0, 0, 0, 0, 0, 0))
        for line, move, other in (('|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Trick', 'Trick', trace_to_c.NOPOS),
                                  ('|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Switcheroo', 'Switcheroo',
                                   trace_to_c.NOPOS),
                                  ('|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Thief|[of] p1a: Sneasler', 'Thief', 0)):
            with self.subTest(line=line):
                (e,) = trace_to_c.step_events([line], 0, roster, maxhp, tables)
                self.assertEqual(e[:6], (trace_to_c.EV['ITEM_END'], 2, other, trace_to_c.CAUSE['ITEM_TAKEN'],
                                         tables['MOVE'][trace_to_c.key(move)], tables['ITEM'][trace_to_c.key('Sitrus Berry')] + 1))
        # A silent -enditem that no move caused is still no event; every other shape of these lines is refused.
        self.assertEqual(trace_to_c.step_events(['|-enditem|p2a: Staraptor|Sitrus Berry|[silent]'], 0, roster, maxhp, tables), [])
        for bad in ('|-item|p2a: Staraptor|Sitrus Berry|[from] move: Trick|[of] p1a: Sneasler',
                    '|-item|p2a: Staraptor|Sitrus Berry|[from] move: Thief',
                    '|-item|p2a: Staraptor|Sitrus Berry|[from] ability: Frisk',
                    '|-item|p2a: Staraptor|Sitrus Berry',
                    '|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Trick|[of] p1a: Sneasler',
                    '|-enditem|p2a: Staraptor|Sitrus Berry|[from] move: Trick',
                    '|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Thief',
                    '|-enditem|p2a: Staraptor|Sitrus Berry|[silent]|[from] move: Knock Off|[of] p1a: Sneasler'):
            with self.subTest(line=bad), self.assertRaises(trace_to_c.ConversionError):
                trace_to_c.step_events([bad], 0, roster, maxhp, tables)

    def test_item_taken_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Knock Off: a member holds nothing from the `|-enditem|X|Item|[from] move: Knock Off|
        [of] Y` line on, and nothing clears it (the item stays gone across a switch-out and a faint: sim/pokemon.ts:1851-1866
        takeItem sets pokemon.item to the empty item for good). The rows of the C test (rows in tests/test_pool_g16.c: per
        step the members that hold nothing as a mask over side * 6 + roster index, the number of such lines, the number of
        `|-activate|X|ability: Sticky Hold` lines) must be exactly what these lines give for the committed traces, so the
        engine's tail, events and extension are checked against the protocol and not against itself. Also: the converter
        reads the line as ITEM_END with the cause ITEM_TAKEN (the move in id, the user in other, the item in id2), and
        refuses any other shape of a `[from] move:` item line."""
        names = ('g16_removal', 'g16_unburden', 'g16_stones', 'g16_sticky_hold', 'g16_scarf_helmet', 'g16_helmet_faint',
                 'g16_scarf_lock_stays')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g16.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g16_\w+)", (\d+)u, 0x([0-9a-f]+)u, (\d+)u, (\d+)u\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3), 16), int(m.group(4)), int(m.group(5)))
        derived = {}
        taken_total = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            rosters = [re.findall(r'^([A-Za-z-]+)(?: \([MF]\))? @', text, re.M) for text in spec['teams']]
            gone = 0
            for k, step in enumerate(trace['steps']):
                taken = blocked = 0
                for line in step['log']:
                    part = line.split('|')
                    if len(part) > 4 and part[1] == '-enditem' and '[from] move: Knock Off' in part[4:]:
                        side = int(part[2][1]) - 1
                        gone |= 1 << (side * 6 + rosters[side].index(part[2][5:]))
                        taken += 1
                    elif len(part) > 3 and part[1] == '-activate' and part[3] == 'ability: Sticky Hold':
                        blocked += 1
                derived[(name, k)] = (gone, taken, blocked)
                taken_total += taken
        self.assertEqual(rows, derived)
        self.assertTrue(taken_total >= 8 and any(b for (_, _, b) in derived.values()))
        # The converter.
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Meowscarada': 0}, {'Pelipper': 0}]
        line = '|-enditem|p2a: Pelipper|Sitrus Berry|[from] move: Knock Off|[of] p1a: Meowscarada'
        (e,) = trace_to_c.step_events([line], 0, roster, [{'Meowscarada': 100}, {'Pelipper': 100}], tables)
        self.assertEqual((e[0], e[1], e[2], e[3], e[4], e[5], e[11], e[13]),
                         (trace_to_c.EV['ITEM_END'], 2, 0, trace_to_c.CAUSE['ITEM_TAKEN'],
                          tables['MOVE'][trace_to_c.key('Knock Off')], tables['ITEM'][trace_to_c.key('Sitrus Berry')] + 1,
                          0, 0))
        self.assertEqual(trace_to_c.CAUSE['ITEM_TAKEN'], 17)
        for bad in ('|-enditem|p2a: Pelipper|Sitrus Berry|[from] move: Knock Off',
                    '|-enditem|p2a: Pelipper|Sitrus Berry|[from] move: Knock Off|[of] p1a: Meowscarada|[eat]'):
            with self.assertRaises(trace_to_c.ConversionError):
                trace_to_c.step_events([bad], 0, roster, [{'Meowscarada': 100}, {'Pelipper': 100}], tables)
        # An item used up is the old line, unchanged: no cause, no move.
        (e,) = trace_to_c.step_events(['|-enditem|p2a: Pelipper|Sitrus Berry|[eat]'], 0, roster,
                                      [{'Meowscarada': 100}, {'Pelipper': 100}], tables)
        self.assertEqual((e[0], e[1], e[3], e[4], e[13]),
                         (trace_to_c.EV['ITEM_END'], 2, 0, 0, trace_to_c.FLAG['EATEN']))

    def test_imprison_rows_are_what_the_protocol_lines_say(self):
        """Decision 0015 step G38: a position stands with Imprison from the `|-start|X|move: Imprison` line (data/moves.ts:
        9501, onStart) until its occupant leaves (a switch, a drag, a replace or a faint: sim/pokemon.ts:1508 clearVolatile;
        the volatile has no end line). The rows of the C test (rows in tests/test_pool_g38.c: per step the positions that
        stand with it as a mask over side * 2 + slot, the number of start lines, the number of `cant|X|move: Imprison|Move`
        lines) must be exactly what these lines give for the committed traces, so the engine's tail, events and extension
        are checked against the protocol and not against itself. Also: the converter reads the start line as VOLATILE_START
        with the detail 8 and the cant line as CANT with the cause 21 and the stopped move in id (and refuses an end line,
        which the pin never prints), and the harness's `hidden` rows take the imprisoned moves out of the move masks of the
        requests (the request shows them as enabled for the last active Pokemon, the choice of them is rejected) and make
        Struggle of a request with none left."""
        names = ('g38_imprison_mask', 'g38_imprison_struggle', 'g38_imprison_cant', 'g38_imprison_encore', 'g38_imprison_choice',
                 'g38_imprison_end', 'g38_imprison_pair', 'g38_imprison_struggle_b')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g38.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g38_\w+)", (\d+)u, 0x([0-9a-f]+)u, (\d+)u, (\d+)u\}', source):
            rows[(m.group(1), int(m.group(2)))] = (int(m.group(3), 16), int(m.group(4)), int(m.group(5)))
        derived = {}
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            mask = 0
            for k, step in enumerate(trace['steps']):
                started = cant = 0
                for line in step['log']:
                    part = line.split('|')
                    if len(part) > 2 and part[1] in ('switch', 'drag', 'replace', 'faint', '-start') and part[2][:1] == 'p':
                        bit = (int(part[2][1]) - 1) * 2 + 'ab'.index(part[2][2])
                        if part[1] == '-start':
                            if part[3:4] == ['move: Imprison']:
                                mask |= 1 << bit
                                started += 1
                        else:
                            mask &= ~(1 << bit)
                    elif len(part) > 3 and part[1] == 'cant' and part[3] == 'move: Imprison':
                        cant += 1
                derived[(name, k)] = (mask, started, cant)
        self.assertEqual(rows, derived)
        values = list(derived.values())
        self.assertTrue(sum(v[1] for v in values) >= 8 and sum(v[2] for v in values) >= 4)
        # The converter.
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Milotic': 0}, {'Gholdengo': 0}]
        hp = [{'Milotic': 100}, {'Gholdengo': 100}]
        (e,) = trace_to_c.step_events(['|-start|p1a: Milotic|move: Imprison'], 0, roster, hp, tables)
        self.assertEqual((e[0], e[1], e[11]), (trace_to_c.EV['VOLATILE_START'], 0, 8))
        (e,) = trace_to_c.step_events(['|cant|p2a: Gholdengo|move: Imprison|Shadow Ball'], 0, roster, hp, tables)
        self.assertEqual((e[0], e[1], e[3]), (trace_to_c.EV['CANT'], 2, trace_to_c.CAUSE['IMPRISON']))
        self.assertEqual(trace_to_c.CAUSE['IMPRISON'], 21)
        self.assertEqual(e[4], tables['MOVE'][trace_to_c.key('Shadow Ball')])
        with self.assertRaises(trace_to_c.ConversionError):
            trace_to_c.step_events(['|-end|p1a: Milotic|move: Imprison'], 0, roster, hp, tables)
        # The hidden rows: the move masks of the requests (bit k for move k, 0x10 Struggle).
        for name, step, want in (('g38_imprison_mask', 1, (0x3, 0x1)), ('g38_imprison_struggle', 1, (0x10, 0x1)),
                                 ('g38_imprison_cant', 1, (0xa, 0xb)), ('g38_imprison_struggle_b', 1, (0x1, 0x10))):
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            data = convert(name, spec, trace)
            self.assertEqual(tuple(data['steps'][step]['enabled'][1]), want, name)

    def test_soak_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Soak: a position is Soaked from the `|-start|X|typechange|Water` line until the
        occupant leaves (`|switch|`, `|drag|`, `|replace|`, `|faint|`) or Mega Evolves (`|-mega|`: setSpecies resets the
        types, sim/pokemon.ts:1392; the research table had OUT only). The rows of the C test (rows in
        tests/test_pool_g11.c: the Soaked positions after each step of the G11 battles, as masks over side * 2 + slot)
        must be exactly what these lines give for the committed traces, so the engine's tail and extension are checked
        against the protocol and not against itself. Also: the converter reads the line as TYPE_CHANGE (the type in the
        detail, cause MOVE with Soak), and refuses one that is not a single type of the table."""
        names = ('g11_soak', 'g11_soak_mega', 'g11_soak_stab', 'g11_soak_electro')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g11.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g11_\w+)", (\d+)u, 0x([0-9a-f])u\}', source):
            rows[(m.group(1), int(m.group(2)))] = int(m.group(3), 16)
        derived = {}
        lines_seen = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            soaked = set()
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    if part[1] in ('switch', 'drag', 'faint', 'replace', '-mega'):
                        soaked.discard(part[2][:3])
                    elif part[1] == '-start' and len(part) > 4 and part[3] == 'typechange':
                        self.assertEqual(part[4], 'Water')
                        self.assertEqual(len(part), 5)  # no [from]: the move is Soak, the converter's rule
                        soaked.add(part[2][:3])
                        lines_seen += 1
                derived[(name, k)] = sum(1 << ((int(x[1]) - 1) * 2 + 'ab'.index(x[2])) for x in soaked)
        self.assertEqual(rows, derived)
        self.assertTrue(any(derived.values()) and lines_seen >= 6)
        tables = trace_to_c.load_tables(ROOT, True)
        names_of = {'p1a': 0, 'p1b': 1, 'p2a': 2, 'p2b': 3}
        roster = [{'Pelipper': 0}, {'Pelipper': 0}]
        events = trace_to_c.step_events(['|-start|p2a: Pelipper|typechange|Water'], 0, roster, [{'Pelipper': 100}] * 2, tables)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e[0], e[1], e[3], e[5], e[11]),
                         (trace_to_c.EV['TYPE_CHANGE'], names_of['p2a'], trace_to_c.CAUSE['MOVE'],
                          tables['MOVE'][trace_to_c.key('Soak')], trace_to_c.TYPE_IDS['Water']))
        self.assertEqual(trace_to_c.EV['TYPE_CHANGE'], 41)
        for bad in ('|-start|p2a: Pelipper|typechange|Water/Flying', '|-start|p2a: Pelipper|typechange|Stellar'):
            with self.assertRaises(trace_to_c.ConversionError):
                trace_to_c.step_events([bad], 0, roster, [{'Pelipper': 100}] * 2, tables)

    def test_encore_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Encore: a position is Encored from the `|-start|X|Encore` line, to the slot of the
        occupant's last `|move|` line on its open sheet (its set's move order), until the matching `|-end|X|Encore` or
        until the occupant leaves (`|switch|`, `|drag|`, `|replace|`, `|faint|`). The rows of the C test (rows in
        tests/test_pool_g9.c: the slot + 1 of each position after each step of the g09 battles) must be exactly what
        these lines give for the committed traces and specs, so the engine's tail and extension are checked against the
        protocol and not against itself. Also: the converter reads both lines as VOLATILE_START and VOLATILE_END with
        the Encore detail."""
        names = ('g09_encore_lock', 'g09_encore_fail', 'g09_encore_late', 'g09_encore_switch', 'g09_encore_struggle',
                 'g09_encore_tie_a', 'g09_encore_tie_b', 'g09_encore_encore')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g9.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g09_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = [int(m.group(i)) for i in (3, 4, 5, 6)]
        derived = {}
        starts = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            sheets = []
            for text in spec['teams']:
                sheet = {}
                for block in text.strip().split('\n\n'):
                    lines = block.split('\n')
                    sheet[re.split(r' \(| @', lines[0])[0]] = [l[2:] for l in lines if l.startswith('- ')]
                sheets.append(sheet)
            last, encore = {}, {}
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    pos = part[2][:3]
                    if part[1] in ('switch', 'drag', 'faint', 'replace'):
                        last.pop(pos, None)
                        encore.pop(pos, None)
                    elif part[1] == 'move':
                        moves = sheets[int(pos[1]) - 1][part[2].split(': ', 1)[1]]
                        last[pos] = moves.index(part[3]) + 1 if part[3] in moves else 5
                    elif part[1] == '-start' and len(part) > 3 and part[3] == 'Encore':
                        encore[pos] = last[pos]
                        starts += 1
                    elif part[1] == '-end' and len(part) > 3 and part[3] == 'Encore':
                        encore.pop(pos, None)
                slots = [0, 0, 0, 0]
                for p, v in encore.items():
                    slots[(int(p[1]) - 1) * 2 + 'ab'.index(p[2])] = v
                derived[(name, k)] = slots
        self.assertEqual(rows, derived)
        self.assertTrue(starts >= 5 and any(any(v) for v in derived.values()))
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Milotic': 0}, {'Milotic': 0}]
        maxhp = [{'Milotic': 100}] * 2
        for line, kind in (('|-start|p2a: Milotic|Encore', 'VOLATILE_START'), ('|-end|p2a: Milotic|Encore', 'VOLATILE_END')):
            events = trace_to_c.step_events([line], 0, roster, maxhp, tables)
            self.assertEqual(len(events), 1)
            e = events[0]
            self.assertEqual((e[0], e[1], e[11]), (trace_to_c.EV[kind], 2, trace_to_c.VOLATILE_ENCORE))
        self.assertEqual((trace_to_c.EV['VOLATILE_START'], trace_to_c.EV['VOLATILE_END']), (39, 40))
        self.assertEqual(trace_to_c.VOLATILE_ENCORE, 2)

    def test_the_draws_of_an_encore_replacement_are_tape_entries(self):
        """Encore's replaced action (Champions' onStart, queue.changeAction -> insertChoice -> resolveAction) draws the
        target that decides who it hits (the harness labels it RANDOM_TARGET resolve:insert, not INSERT_TIE) and, when it
        ties queued actions, its place among them (INSERT_TIE with moves in the tied range). The converter keeps both as
        tape entries; the old rules stay: a RANDOM_TARGET resolve of an ordinary queue and an insert tie among runSwitch
        entries are dropped, an insert tie among anything else is an error."""
        before = {'sides': []}
        target = {'site': 'RANDOM_TARGET', 'context': 'resolve:insert', 'lo': 0, 'hi': 2, 'value': 1}
        self.assertIsNone(trace_to_c.drop_reason(target, before))
        self.assertEqual(trace_to_c.tape_entry(target), (trace_to_c.SITES['RANDOM_TARGET'], 0, 2, 1))
        plain = dict(target, context='resolve')
        self.assertEqual(trace_to_c.drop_reason(plain, before), 'target computed for priority')
        group = ['A:move:p1a:thunderbolt', 'A:move:p2b:shadowball', 'A:residual:-:']
        tie = {'site': 'INSERT_TIE', 'context': 'queue', 'lo': 0, 'hi': 3, 'value': 1, 'group': group}
        self.assertIsNone(trace_to_c.drop_reason(tie, before))
        self.assertEqual(trace_to_c.tape_entry(tie), (trace_to_c.SITES['INSERT_TIE'], 0, 3, 1))
        self.assertEqual(trace_to_c.SITES['INSERT_TIE'], 14)
        runs = dict(tie, group=['A:runSwitch:p1a::1', 'A:runSwitch:p2a::1'], hi=2)
        self.assertEqual(trace_to_c.drop_reason(runs, before), 'queue order of entries that run together')
        other = dict(tie, group=['A:switch:p1a::', 'A:switch:p2a::', 'A:residual:-:'])
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.drop_reason(other, before)
        self.assertEqual(ctx.exception.rule, 'insert-tie')

    def test_poison_touch_rolls_are_kept_as_their_own_site(self):
        """Poison Touch's randomChance(3, 10) (step G14) is a draw of the site POISON_TOUCH, random(10), that the harness
        names by the effect and the event it runs in (ps_trace.js CONDITION_SITES) and the converter keeps as a tape entry
        of site 16: after every contact hit of a holder, also at a target that is down or immune. The recorded battle has
        draws below and above 3 and none outside [0, 10)."""
        with open(os.path.join(ROOT, 'tests', 'reference', 'traces', 'g14_poison_touch.json'), encoding='utf-8') as f:
            trace = json.load(f)
        draws = [d for step in trace['steps'] for d in step['draws'] if d['site'] == 'POISON_TOUCH']
        self.assertTrue(draws)
        self.assertTrue(all((d['lo'], d['hi']) == (0, 10) and 0 <= d['value'] < 10 for d in draws))
        self.assertTrue(any(d['value'] < 3 for d in draws) and any(d['value'] >= 3 for d in draws))
        self.assertEqual(trace_to_c.SITES['POISON_TOUCH'], 16)
        for d in draws:
            self.assertEqual(trace_to_c.tape_entry(d), (16, 0, 10, d['value']))
        # No draw of the battle is unclassified.
        self.assertFalse([d for step in trace['steps'] for d in step['draws'] if d['site'] == 'UNKNOWN'])

    def test_thermal_exchange_is_no_holder_of_an_update_tie(self):
        """Thermal Exchange's onUpdate (step G14) cures a burn that its holder cannot have, so an each:Update tie with it
        is dropped as one without a holder; a Sitrus Berry beside it is a holder like any other, and a burned holder
        (the precondition) is an error."""
        def state(status):
            side = {'active': [0, None], 'pokemon': [{'status': status}]}
            return {'sides': [side, {'active': [None, None], 'pokemon': []}]}

        d = {'site': 'SPEED_TIE', 'context': 'each:Update', 'lo': 0, 'hi': 2, 'value': 0, 'start': 0,
             'group': ['P:p1a:1:thermalexchange', 'P:p2a:1:sitrusberry']}
        self.assertEqual(trace_to_c.drop_reason(d, state('')), 'each-event tie with at most one holder')
        both = dict(d, group=['P:p1a:1:sitrusberry', 'P:p2a:1:sitrusberry', 'P:p1b:1:thermalexchange'])
        self.assertIsNone(trace_to_c.drop_reason(both, state('')))  # two Sitrus holders: the engine draws
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.drop_reason(d, state('brn'))
        self.assertEqual(ctx.exception.rule, 'thermal-exchange-burn')
        # The holder that stands in the slot when the tie is drawn counts: one that switched in this step over a burned
        # Pokemon (the state before the step still shows the burned one) is no burned holder (step G21, fz_2101_3); a
        # burned occupant in the state after the step is.
        self.assertEqual(trace_to_c.drop_reason(d, state('brn'), state('')), 'each-event tie with at most one holder')
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.drop_reason(d, state(''), state('brn'))
        self.assertEqual(ctx.exception.rule, 'thermal-exchange-burn')

    def test_recharge_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for the recharge (step G17): a position must recharge from the `|-mustrecharge|X`
        line until the `|cant|X|recharge` line or until the occupant leaves (`|switch|`, `|drag|`, `|replace|`,
        `|faint|`); Encore as for step G9. The rows of the C test (rows in tests/test_pool_g17.c: per position after each
        step, the recharge flag and the Encored slot + 1) must be exactly what these lines give for the committed traces
        and specs, so the engine's tail, requests and extension are checked against the protocol and not against
        themselves. Every `cant|X|recharge` has the `-mustrecharge` before it, and the line comes only after a move
        line of a recharge move that is not a miss or a block."""
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs')) if f.startswith('g17_'))
        self.assertGreaterEqual(len(names), 9)
        source = open(os.path.join(ROOT, 'tests', 'test_pool_g17.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(g17_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}',
                             source):
            rows[(m.group(1), int(m.group(2)))] = ([int(m.group(i)) for i in (3, 4, 5, 6)],
                                                   [int(m.group(i)) for i in (7, 8, 9, 10)])
        derived = {}
        recharges = cants = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8') as f:
                spec = json.load(f)
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            sheets = []
            for text in spec['teams']:
                sheet = {}
                for block in text.strip().split('\n\n'):
                    lines = block.split('\n')
                    sheet[re.sub(r'[^a-z0-9]', '', re.split(r' \(| @', lines[0])[0].lower())] = [l[2:] for l in lines if l.startswith('- ')]
                sheets.append(sheet)
            last, encore, recharge = {}, {}, set()
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    kind, pos = part[1], part[2][:3]
                    if kind in ('switch', 'drag', 'faint', 'replace'):
                        last.pop(pos, None)
                        encore.pop(pos, None)
                        recharge.discard(pos)
                    elif kind == 'move':
                        moves = sheets[int(pos[1]) - 1][re.sub(r'[^a-z0-9]', '', part[2].split(': ', 1)[1].lower())]
                        last[pos] = moves.index(part[3]) + 1 if part[3] in moves else 5
                    elif kind == '-start' and len(part) > 3 and part[3] == 'Encore':
                        encore[pos] = last[pos]
                    elif kind == '-end' and len(part) > 3 and part[3] == 'Encore':
                        encore.pop(pos, None)
                    elif kind == '-mustrecharge':
                        recharge.add(pos)
                        recharges += 1
                    elif kind == 'cant' and len(part) > 3 and part[3] == 'recharge':
                        self.assertIn(pos, recharge)
                        recharge.discard(pos)
                        cants += 1
                enc, rec = [0, 0, 0, 0], [0, 0, 0, 0]
                for x, v in encore.items():
                    enc[(int(x[1]) - 1) * 2 + 'ab'.index(x[2])] = v
                for x in recharge:
                    rec[(int(x[1]) - 1) * 2 + 'ab'.index(x[2])] = 1
                derived[(name, k)] = (rec, enc)
        self.assertEqual(rows, derived)
        self.assertTrue(recharges >= 8 and cants >= 6)

    def test_the_recharge_lines_and_choice_are_converted(self):
        """`|-mustrecharge|X` is VOLATILE_START with the detail 3 (DUOFORGE_VOLATILE_MUST_RECHARGE), `|cant|X|recharge` is
        CANT with the cause 18 (DUOFORGE_CAUSE_RECHARGE), and the choice on a recharge turn (Showdown's "move 1": the
        request offers the move Recharge) is MOVE with the move slot 5 (DUOFORGE_MOVE_SLOT_RECHARGE), no target, no
        Mega, whatever was typed."""
        self.assertEqual((trace_to_c.CAUSE['RECHARGE'], trace_to_c.VOLATILE_MUST_RECHARGE, trace_to_c.MOVE_SLOT_RECHARGE),
                         (18, 3, 5))
        spec, trace = battle('g17_hyper_beam')
        data = convert('g17_hyper_beam', spec, trace)
        starts = cants = recharge_cmds = 0
        for st in data['steps']:
            for evs in st['events']:
                for e in evs:
                    starts += 1 if e[0] == trace_to_c.EV['VOLATILE_START'] and e[11] == 3 else 0
                    cants += 1 if e[0] == trace_to_c.EV['CANT'] and e[3] == 18 else 0
            for side_cmds in st['cmds']:
                recharge_cmds += sum(1 for c in side_cmds if tuple(c)[:3] == (1, 5, 0xFF))
        self.assertEqual((starts, cants, recharge_cmds), (2, 2, 1))  # both viewers see both lines; one choice

    def test_trace_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for an ability changed by Trace: a position has the copied ability from the
        `|-ability|X|NEW|OLD|[from] ability: Trace|[of] foe` line until its occupant leaves (`|switch|`, `|drag|`,
        `|replace|`, `|faint|`) or Mega Evolves (`|-mega|`: formeChange sets the Mega forme's ability). The rows of the
        C test (tests/test_pool_ac1.c: the copied ability of the four positions after each step of the ac1 battles)
        must be exactly what these lines give for the committed traces. Also: the converter reads the line as an
        ABILITY event (the new ability in id2, cause ABILITY, the foe in `other`), and refuses a [from] ability line
        that is not Trace's, an [of] that is missing and a plain line with a [from]."""
        names = ('ac1_trace_intimidate', 'ac1_trace_defiant', 'ac1_trace_drizzle', 'ac1_trace_single',
                 'ac1_trace_switch')
        source = open(os.path.join(ROOT, 'tests', 'test_pool_ac1.c'), encoding='utf-8').read()
        rows = {}
        for m in re.finditer(r'\{"(ac1_\w+)", (\d+)u, \{([^}]*)\}\}', source):
            cells = [c.strip() for c in m.group(3).split(',')]
            rows[(m.group(1), int(m.group(2)))] = [0 if c == '0u' else re.fullmatch(r'AB\((\w+)\)', c).group(1) for c in cells]
        derived = {}
        lines_seen = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            copied = {}
            for k, step in enumerate(trace['steps']):
                for line in step['log']:
                    part = line.split('|')
                    if len(part) < 3:
                        continue
                    if part[1] in ('switch', 'drag', 'faint', 'replace', '-mega'):
                        copied.pop(part[2][:3], None)
                    elif part[1] == '-ability' and len(part) > 5 and part[5] == '[from] ability: Trace':
                        self.assertEqual(len(part), 7)  # -ability|X|NEW|OLD|[from] ability: Trace|[of] foe
                        copied[part[2][:3]] = trace_to_c.key(part[3])
                        lines_seen += 1
                derived[(name, k)] = [copied.get(x, 0) for x in ('p1a', 'p1b', 'p2a', 'p2b')]
        self.assertEqual(rows, derived)
        self.assertTrue(any(any(v) for v in derived.values()) and lines_seen >= 6)
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Gardevoir': 0}, {'Incineroar': 0}]
        line = '|-ability|p1a: Gardevoir|Intimidate|Trace|[from] ability: Trace|[of] p2a: Incineroar'
        events = trace_to_c.step_events([line], 0, roster, [{'Gardevoir': 100}] * 2, tables)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e[0], e[1], e[2], e[3], e[5]),
                         (trace_to_c.EV['ABILITY'], 0, 2, trace_to_c.CAUSE['ABILITY'],
                          tables['ABILITY'][trace_to_c.key('Intimidate')] + 1))
        self.assertEqual(trace_to_c.SITES['TRACE'], 15)
        for bad in ('|-ability|p1a: Gardevoir|Intimidate|Trace|[from] ability: Pressure|[of] p2a: Incineroar',
                    '|-ability|p1a: Gardevoir|Intimidate|Trace|[from] ability: Trace',
                    '|-ability|p1a: Gardevoir|Intimidate|boost|[from] ability: Trace|[of] p2a: Incineroar',
                    '|-ability|p1a: Gardevoir|Intimidate|boost|[from] move: Skill Swap'):
            with self.assertRaises(trace_to_c.ConversionError):
                trace_to_c.step_events([bad], 0, roster, [{'Gardevoir': 100}] * 2, tables)

    def test_skill_swap_foe_and_ally_lines_are_two_ability_events(self):
        """Step G70 (decision 0041): the foe's line names both abilities (the source now has the first); the ally's line
        names none, and its pair is the one swap_partners follows from the sheets and the earlier lines of the battle."""
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Gardevoir': 0, 'Incineroar': 1}, {'Milotic': 0, 'Pelipper': 1}]
        maxhp = [{'Gardevoir': 100, 'Incineroar': 100}, {'Milotic': 100, 'Pelipper': 100}]
        ab = tables['ABILITY']
        move = tables['MOVE'][trace_to_c.key('Skill Swap')]
        # foe line: p2a Milotic (the source) swaps with p1a Gardevoir; Milotic now has Intimidate, Gardevoir Multiscale
        foe = '|-activate|p2a: Milotic|Skill Swap|Intimidate|Multiscale|[of] p1a: Gardevoir'
        events = trace_to_c.step_events([foe], 0, roster, maxhp, tables)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][:6], (trace_to_c.EV['ABILITY'], 2, 0, trace_to_c.CAUSE['MOVE'], ab[trace_to_c.key('Intimidate')] + 1, move))
        self.assertEqual(events[1][:6], (trace_to_c.EV['ABILITY'], 0, 2, trace_to_c.CAUSE['MOVE'], ab[trace_to_c.key('Multiscale')] + 1, move))
        # ally line: p1a Gardevoir (Trace) swaps with p1b Incineroar (Intimidate); no names in the line
        teams = [[{'ability': ab[trace_to_c.key('Trace')] + 1}, {'ability': ab[trace_to_c.key('Intimidate')] + 1}],
                 [{'ability': ab[trace_to_c.key('Multiscale')] + 1}, {'ability': ab[trace_to_c.key('Pressure')] + 1}]]
        ally = '|-activate|p1a: Gardevoir|Skill Swap|||[of] p1b: Incineroar'
        enter = ['|switch|p1a: Gardevoir|Gardevoir, L50|100/100', '|switch|p1b: Incineroar|Incineroar, L50|100/100']
        log = enter + [ally]
        swaps = trace_to_c.swap_partners({'steps': [{'log': log}]}, teams, roster, tables)
        self.assertEqual(swaps, [{2: (ab[trace_to_c.key('Intimidate')], ab[trace_to_c.key('Trace')])}])
        events = trace_to_c.step_events(log, 1, roster, maxhp, tables, None, swap_ids=swaps[0])
        self.assertEqual(events[-2][:6], (trace_to_c.EV['ABILITY'], 0, 1, trace_to_c.CAUSE['MOVE'], ab[trace_to_c.key('Intimidate')] + 1, move))
        self.assertEqual(events[-1][:6], (trace_to_c.EV['ABILITY'], 1, 0, trace_to_c.CAUSE['MOVE'], ab[trace_to_c.key('Trace')] + 1, move))
        # the Trace copy before the ally swap is followed: Incineroar copies Multiscale from p2a, then swaps with Gardevoir
        log2 = enter + ['|-ability|p1b: Incineroar|Multiscale|Intimidate|[from] ability: Trace|[of] p2a: Milotic', ally]
        swaps2 = trace_to_c.swap_partners({'steps': [{'log': log2}]}, teams, roster, tables)
        self.assertEqual(swaps2, [{3: (ab[trace_to_c.key('Multiscale')], ab[trace_to_c.key('Trace')])}])
        # refusals: an ally line without its pair, and an ally swap of a Mega Evolved holder (its ability is not known)
        with self.assertRaises(trace_to_c.ConversionError):
            trace_to_c.step_events([ally], 1, roster, maxhp, tables)
        mega_log = enter + ['|-mega|p1a: Gardevoir|Gardevoir-Mega|Gardevoirite', ally]
        with self.assertRaises(trace_to_c.ConversionError):
            trace_to_c.swap_partners({'steps': [{'log': mega_log}]}, teams, roster, tables)
        for bad in ('|-activate|p2a: Milotic|Skill Swap|Intimidate|[of] p1a: Gardevoir',
                    '|-activate|p2a: Milotic|Skill Swap|Intimidate|Multiscale|[of] p1a: Gardevoir|[from] move: X'):
            with self.assertRaises(trace_to_c.ConversionError):
                trace_to_c.step_events([bad], 0, roster, maxhp, tables)

    def test_perish_song_lines_are_events_and_rows_are_what_the_protocol_lines_say(self):
        """Perish Song (step G26): `-start|X|perishN` is a VOLATILE_START of the volatile PERISH (5) with the count N in
        `amount` (3, 2, 1, and 0 from onEnd, which a `faint` line follows); `-fieldactivate|move: Perish Song` is an ACTIVATE
        of the move with no position; the cast's own `-start|X|perish3|[silent]` is not shown and never converts. Anything
        else is refused. Decision 0018 section 6.1: the view's `perish` is the last count a position was told, cleared by a
        faint, a switch or a drag: the rows of the C test (rows in tests/test_pool_g26.c: the count of each position after
        each step) must be exactly what the committed traces say, so the engine's tail and extension are checked against the
        protocol and not against themselves. After a `perish0` line every position that showed it has a `faint` line in the
        same step, and the win of g26_perish_end goes to the side of the last `faint`."""
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Politoed': 0}, {'Politoed': 0}]
        maxhp = [{'Politoed': 100}] * 2
        for n in (3, 2, 1, 0):
            events = trace_to_c.step_events(['|-start|p1a: Politoed|perish%d' % n], 0, roster, maxhp, tables)
            self.assertEqual(len(events), 1)
            e = events[0]
            self.assertEqual((e[0], e[1], e[11], e[12]), (trace_to_c.EV['VOLATILE_START'], 0, trace_to_c.VOLATILE_PERISH, n))
        self.assertEqual(trace_to_c.VOLATILE_PERISH, 5)
        self.assertEqual(trace_to_c.step_events(['|-start|p1a: Politoed|perish3|[silent]'], 0, roster, maxhp, tables), [])
        field = trace_to_c.step_events(['|-fieldactivate|move: Perish Song'], 0, roster, maxhp, tables)
        self.assertEqual(len(field), 1)
        self.assertEqual((field[0][0], field[0][1], field[0][2], field[0][3], field[0][5]),
                         (trace_to_c.EV['ACTIVATE'], 0xFF, 0xFF, trace_to_c.CAUSE['MOVE'], tables['MOVE'][trace_to_c.key('Perish Song')]))
        with self.assertRaises(trace_to_c.ConversionError) as ctx:
            trace_to_c.step_events(['|-fieldactivate|move: Trick Room'], 0, roster, maxhp, tables)
        self.assertEqual(ctx.exception.rule, 'fieldactivate-line')
        names = ('g26_perish_song', 'g26_perish_recast', 'g26_perish_end', 'g26_perish_survivor_a',
                 'g26_perish_survivor_b', 'g26_perish_soundproof')
        with open(os.path.join(ROOT, 'tests', 'test_pool_g26.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g26_\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = [int(m.group(i)) for i in (3, 4, 5, 6)]
        derived = {}
        zero_lines = faints = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            perish = {}
            for k, step in enumerate(trace['steps']):
                log = [l.split('|') for l in step['log']]
                zeros = set()
                fainted = set()
                for part in log:
                    if len(part) < 3:
                        continue
                    kind, pos = part[1], part[2][:3]
                    if kind in ('switch', 'drag', 'faint', 'replace'):
                        perish.pop(pos, None)
                        if kind == 'faint':
                            fainted.add(pos)
                    elif kind == '-start' and len(part) == 4 and re.fullmatch(r'perish[0-3]', part[3]):
                        n = int(part[3][6])
                        if n == 0:
                            perish.pop(pos, None)
                            zeros.add(pos)
                            zero_lines += 1
                        else:
                            perish[pos] = n
                self.assertEqual(zeros, fainted & zeros)  # every perish0 is followed by the holder's faint in the step
                faints += len(zeros)
                row = [0, 0, 0, 0]
                for x, n in perish.items():
                    row[(int(x[1]) - 1) * 2 + 'ab'.index(x[2])] = n
                derived[(name, k)] = row
        self.assertEqual(rows, derived)
        self.assertTrue(zero_lines >= 10 and faints == zero_lines)
        # g26_perish_end: the last line of the log is the win, and it is the side of the last `faint` line.
        with open(os.path.join(ROOT, 'tests', 'reference', 'traces', 'g26_perish_end.json'), encoding='utf-8') as f:
            last = json.load(f)['steps'][-1]['log']
        faint_lines = [l for l in last if l.startswith('|faint|')]
        self.assertEqual(len(faint_lines), 4)
        self.assertEqual([l for l in last if l.startswith('|win|')], ['|win|p%s' % faint_lines[-1][8]])

    def test_glaive_rush_rows_are_what_the_protocol_lines_say(self):
        """Decision 0018 section 6.1 for Glaive Rush (step G19): its user is hit as vulnerable from a `|move|X|Glaive Rush|`
        line that is followed by damage to a foe (a miss, a block or an immunity gives nothing; the `-singlemove|X|Glaive
        Rush|[silent]` line is not shown) until the user's next `|move|` or `|cant|` line (BeforeMove, priority 100) or
        until it leaves (`|switch|`, `|drag|`, `|replace|`, `|faint|`). The rows of the C test (rows in
        tests/test_pool_g19.c: the flag of each position after each step) must be exactly what these lines give for the
        committed traces, so the engine's tail and extension are checked against the protocol and not against
        themselves. Every silent line follows such a hit, and no battle shows it for a miss, a block or an immunity."""
        names = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs')) if f.startswith('g19_glaive'))
        self.assertEqual(len(names), 5)
        with open(os.path.join(ROOT, 'tests', 'test_pool_g19.c'), encoding='utf-8') as f:
            source = f.read()
        rows = {}
        for m in re.finditer(r'\{"(g19_glaive\w+)", (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\}', source):
            rows[(m.group(1), int(m.group(2)))] = [int(m.group(i)) for i in (3, 4, 5, 6)]
        derived = {}
        silent = hits = 0
        for name in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            glaive = set()
            for k, step in enumerate(trace['steps']):
                log = [l.split('|') for l in step['log']]
                for i, part in enumerate(log):
                    if len(part) < 3:
                        continue
                    kind, pos = part[1], part[2][:3]
                    if kind in ('switch', 'drag', 'faint', 'replace'):
                        glaive.discard(pos)
                    elif kind in ('move', 'cant'):
                        glaive.discard(pos)
                        if kind == 'move' and len(part) > 3 and part[3] == 'Glaive Rush':
                            hit = False
                            for later in log[i + 1:]:
                                if len(later) > 2 and later[1] in ('move', 'turn', 'upkeep', 'cant'):
                                    break
                                if len(later) > 2 and later[1] == '-damage' and later[2][:2] != pos[:2]:
                                    hit = True
                            hits += 1 if hit else 0
                            if hit:
                                glaive.add(pos)
                    elif kind == '-singlemove' and len(part) > 4 and part[3] == 'Glaive Rush' and part[4] == '[silent]':
                        silent += 1
                        self.assertIn(pos, glaive)
                row = [0, 0, 0, 0]
                for x in glaive:
                    row[(int(x[1]) - 1) * 2 + 'ab'.index(x[2])] = 1
                derived[(name, k)] = row
        self.assertEqual(rows, derived)
        self.assertTrue(hits >= 2 and silent == hits)

    def test_a_two_turn_lock_lasts_while_twoturnmove_stands(self):
        """Electro Shot's onTryMove removes the move's volatile on the locked turn and the recorder's `locked` is made of
        it, but twoturnmove stays until the residual. In the last step of d02 (Emergency Exit) and d03 (Parting Shot,
        Team C), cuts of battles found by the differential loop, a mid-turn boundary comes between the two, and in the
        last step of s14_electro_shot_rain_miss the battle ends there: the converted lock is the one recorded before."""
        for name, side, boundary in (('d02_electro_shot_lock_emergency_exit', 0, 4),
                                     ('d03_electro_shot_lock_parting_shot', 1, 4),
                                     ('s14_electro_shot_rain_miss', 0, 5)):
            with self.subTest(name):
                spec, trace = battle(name)
                data = convert(name, spec, trace)
                states = [step['state'] for step in trace['steps']]
                bare = [k for k, st in enumerate(states) if mon_of(st, side, 'Archaludon')['volatiles'] == ['twoturnmove']]
                self.assertEqual(bare, [len(states) - 1])
                self.assertIsNone(mon_of(states[-1], side, 'Archaludon')['locked'])  # what the recorder says
                self.assertEqual(data['steps'][-1]['boundary'], boundary)  # 4 PIVOT, 5 TERMINAL
                recorded = [k for k, st in enumerate(states) if mon_of(st, side, 'Archaludon')['locked']]
                self.assertTrue(recorded)
                lock = mon_row(trace, data, recorded[-1], side, 'Archaludon')
                row = mon_row(trace, data, len(states) - 1, side, 'Archaludon')
                self.assertNotEqual(lock['locked_slot'], 0xFF)
                self.assertEqual((row['locked_slot'], row['locked_target']), (lock['locked_slot'], lock['locked_target']))
                self.assertEqual((lock['vols'] & 4, row['vols'] & 4), (4, 4))  # still charging, as the engine's observation says

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
        self.assertEqual(sorted(data), ['dropped_total', 'illusion_duplicate_step', 'member_count', 'members', 'name', 'purpose', 'steps'])
        self.assertIsNone(data['illusion_duplicate_step'])  # no disguise shown beside its real member in this battle
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

    def test_pool_is_the_decision_of_the_spec(self):
        """"data": "pool" (decision 0015) is read with the extended ids, so spec_is_team_c holds for it too, and
        spec_is_pool tells the pool battles apart; the pool tables name the new items and every old id is kept."""
        self.assertEqual(trace_to_c.spec_data('x', {'data': 'pool'}), 'pool')
        self.assertEqual(trace_to_c.spec_data('x', {'data': 'team_c'}), 'team_c')
        self.assertEqual(trace_to_c.spec_data('x', {}), 'closure')
        self.assertTrue(trace_to_c.spec_is_pool('x', {'data': 'pool'}))
        self.assertFalse(trace_to_c.spec_is_pool('x', {'data': 'team_c'}))
        self.assertFalse(trace_to_c.spec_is_pool('x', {}))
        self.assertTrue(trace_to_c.spec_is_team_c('x', {'data': 'pool'}))
        self.assertTrue(trace_to_c.is_pool(ROOT, 'p2_chilan_berry'))
        self.assertFalse(trace_to_c.is_pool(ROOT, 'c05_chople_berry'))
        extended = tables(True)
        self.assertEqual(extended['ITEM']['CHILANBERRY'], 34)
        self.assertEqual(extended['ITEM']['CHOPLEBERRY'], 14)
        self.assertEqual(extended['ITEM']['MYSTICWATER'], 6)
        self.assertNotIn('CHILANBERRY', tables(False)['ITEM'])
        self.assertEqual(len(extended['GENDER_RULE']), 347)  # the pool's formes: the whole legal pool plus the Blade row (decision 0015 4.2, step G66)

    def test_the_protocol_names_of_the_formes_with_a_base_species(self):
        """An unnamed Pokemon is called by its base species in the protocol (sim/pokemon.ts:339-341): Indeedee-F,
        Arcanine-Hisui and Floette-Eternal. The pool battles g2_data_moves_b names Arcanine-Hisui in the switch line."""
        self.assertEqual(trace_to_c.BASE_SPECIES_NAME,
                         {'Indeedee-F': 'Indeedee', 'Arcanine-Hisui': 'Arcanine', 'Floette-Eternal': 'Floette',
                          'Ninetales-Alola': 'Ninetales', 'Meowstic-F': 'Meowstic', 'Lycanroc-Dusk': 'Lycanroc',
                          'Samurott-Hisui': 'Samurott'})  # G21; Samurott-Hisui of step G48
        spec = json.load(open(os.path.join(ROOT, 'tests', 'reference', 'traces', 'g2_data_moves_b.json')))
        # Meowstic-F (step G15, g15_ef_retarget_*) is called Meowstic.
        for name in ('g15_ef_retarget_terrain', 'g15_ef_retarget_plain'):
            log = [l for step in json.load(open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json')))['steps']
                   for l in step['log']]
            self.assertTrue(any('|Meowstic-F, L50, F|' in l and l.startswith('|switch|p2') and ': Meowstic|' in l
                                for l in log), name)
        lines = [l for step in spec['steps'] for l in step['log']]
        self.assertTrue(any(l.startswith('|switch|p1a: Arcanine|Arcanine-Hisui, L50, M|') for l in lines))

    def test_every_move_marked_beyond_the_extended_ids_is_used_in_a_pool_battle(self):
        """A move that the pool manifest marks beyond the extended ids (twelve of step G2, U-turn of step G5, Throat Chop
        and Psychic Noise of step G8, Soak of step G11, Moonblast and Calm Mind of step G12, Sandstorm and Snowscape
        of the weather step, the fourteen of step G13) was used in a committed pool battle: a move line of it that did
        something (damage, a boost, a heal, a -start line for a status move, a -weather line for a weather move; for
        Detect, the protection of its user: -singleturn) before the next move line."""
        def read(*p):
            return open(os.path.join(ROOT, *p), encoding='utf-8').read()
        header, source = read('src', 'data', 'pool_tables.h'), read('src', 'data', 'pool_tables.c')
        ext_moves = int(re.search(r'#define DFI_EXT_MOVE_COUNT (\d+)u', read('src', 'data', 'extended_tables.h')).group(1))
        array = source[source.index('dfi_pool_moves[DFI_POOL_MOVE_COUNT] = {'):source.index('dfi_pool_items[')]
        names = re.findall(r'^    /\* (.+?) -- data/', array, re.M)
        ids = {m.group(1): int(m.group(2)) for m in re.finditer(r'#define DFI_MOVE_(?!FLAG)(\w+) (\d+)u', header)}
        marked = [n for n in re.findall(r'\[DFI_MOVE_(\w+)\] = 1u', read('src', 'data', 'support_manifest.c'))
                  if n in ids and ids[n] >= ext_moves]
        self.assertEqual(len(names), ext_moves + len(ids))
        self.assertEqual(len(marked), 198)  # G78: Dragon Darts makes 198 (decision 0043); G72b: Alluring Voice and Dragon Cheer make 197 (195 before); the King's Shield of G66 (decision 0015 5cb) makes 195; the Skill Swap of G70 makes 194 (decision 0041) makes 194 from 193; 189 before step G68 (decision 0015 item 5cc: Steel Beam, Thunder Wave, Fire Punch, Ice Hammer); 180 of main, the four of G64 and the three of G62 (Haze, After You, Quash)  # the four of step G64 (Poltergeist, Beat Up, Bug Bite, Sheer Cold; decision 0015 item 5ca), the seven of step G54 (Icicle Spear, Scale Shot, Quick Guard, Upper Hand, Heal Pulse, Strength Sap, Sing), and the 171 of main (Roost and Stomping Tantrum of G42, Double Shock of G50 among them)  # Roost and Stomping Tantrum (G42), Double Shock (G50), the eleven of step G44, the four of step G46, the four of step G48, Taunt and Yawn (G31) and the rows of the earlier steps as before
        pool = [n for n in os.listdir(os.path.join(ROOT, 'tests', 'reference', 'specs'))
                if trace_to_c.is_pool(ROOT, n[:-5])]
        logs = []
        for n in pool:
            trace = json.load(open(os.path.join(ROOT, 'tests', 'reference', 'traces', n)))
            logs.append([l for step in trace['steps'] for l in step['log'] if not l.startswith('|split')])
        for move in marked:
            name = names[ids[move]]
            done = False
            for lines in logs:
                for i, line in enumerate(lines):
                    if line.startswith('|move|') and ('|%s|' % name) in line:
                        for after in lines[i + 1:]:
                            if after.startswith('|move|') or after.startswith('|turn|'):
                                break
                            done = done or after.startswith(('|-damage|', '|-boost|', '|-heal|', '|-start|', '|-weather|') + (('|-status|',) if name in ('Will-O-Wisp', 'Stun Spore', 'Sleep Powder', 'Poison Powder', 'Sing') else ()))
                            # A status move of one target with a primary drop (Charm, Fake Tears, step G39): its -unboost line.
                            done = done or (name in ('Charm', 'Fake Tears') and after.startswith('|-unboost|'))
                            # A forced switch (step G46: Whirlwind; Dragon Tail is damaging, so its damage line counts): the drag line.
                            done = done or (name in ('Whirlwind', 'Roar', 'Circle Throw') and after.startswith('|drag|'))
                            # A side condition that a status move sets (Aurora Veil, step G20): its -sidestart line.
                            done = done or (after.startswith('|-sidestart|') and after.endswith(('|move: ' + name, '|' + name)))  # Spikes' own line has no move: prefix (step G37)
                            # A terrain that a status move sets (Electric Terrain, Misty Terrain, step G25): its -fieldstart line.
                            done = done or (after.startswith('|-fieldstart|') and after.endswith('|move: ' + name))
                            # A side move (Wide Guard, step G7) shows its effect as its own -singleturn line; Detect's is
                            # Protect's (step G13: its handler, and the line of the Protect condition).
                            done = done or (after.startswith('|-singleturn|') and after.endswith('|' + name))
                            done = done or (name == 'Detect' and after.startswith('|-singleturn|'))
                            # Spiky Shield (step G20) prints Protect's line, `move: Protect`, for its own volatile.
                            done = done or (name == 'Spiky Shield' and after.startswith('|-singleturn|'))
                            # King's Shield (step G66) prints the same `-singleturn|X|Protect` line as Protect (data/moves.ts:9929).
                            done = done or (name == "King's Shield" and after.startswith('|-singleturn|'))
                            # Haze (step G62, decision 0031): its own line, the public -clearallboost.
                            done = done or (name == 'Haze' and after == '|-clearallboost')
                            # Thunder Wave (step G68): its paralysis (-status) or the Ground or Electric immunity (-immune).
                            done = done or (name == 'Thunder Wave' and after.startswith(('|-status|', '|-immune|')))
                            # After You and Quash (step G62): the -activate line of the move on the target.
                            done = done or (name in ('After You', 'Quash') and after.startswith('|-activate|') and after.endswith('|move: ' + name))
                            # Rage Powder (step G30): the single-turn line of its condition.
                            done = done or (name == 'Rage Powder' and after.startswith('|-singleturn|') and after.endswith('|move: Rage Powder'))
                            # An item that a move gave (Trick, Switcheroo, Thief, Covet; step G29): its -item line.
                            done = done or (after.startswith('|-item|') and ('[from] move: ' + name) in after)
            with self.subTest(move=name):
                self.assertTrue(done, '%s is marked but no committed pool battle uses it' % name)

    def test_inner_focus_fail_line_is_a_fail_event_of_the_ability(self):
        """Inner Focus (step G22, data/abilities.ts:2157-2162): `-fail|X|unboost|atk|[from] ability: Inner Focus|[of] X`
        is a FAIL whose cause is the ability (id2 = ability + 1) and whose `other` is the holder; any other stat, a
        missing [of] or another cause is refused, not mapped, and a `-fail` of a heal move or an ailment stays what it
        was."""
        tables = trace_to_c.load_tables(ROOT, True)
        roster = [{'Dragonite': 0}, {'Dragonite': 0}]
        maxhp = [{'Dragonite': 100}] * 2
        line = '|-fail|p2a: Dragonite|unboost|atk|[from] ability: Inner Focus|[of] p2a: Dragonite'
        events = trace_to_c.step_events([line], 0, roster, maxhp, tables)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e[0], e[1], e[2], e[3], e[5]),
                         (trace_to_c.EV['FAIL'], 2, 2, trace_to_c.CAUSE['ABILITY'],
                          tables['ABILITY'][trace_to_c.key('Inner Focus')] + 1))
        for bad in ('|-fail|p2a: Dragonite|unboost|def|[from] ability: Inner Focus|[of] p2a: Dragonite',
                    '|-fail|p2a: Dragonite|unboost|atk|[from] ability: Inner Focus',
                    '|-fail|p2a: Dragonite|unboost|atk|[from] move: Protect|[of] p2a: Dragonite'):
            with self.assertRaises(trace_to_c.ConversionError) as ctx:
                trace_to_c.step_events([bad], 0, roster, maxhp, tables)
            self.assertEqual(ctx.exception.rule, 'fail-line')
        plain = trace_to_c.step_events(['|-fail|p2a: Dragonite|heal'], 0, roster, maxhp, tables)[0]
        self.assertEqual((plain[0], plain[3], plain[11]), (trace_to_c.EV['FAIL'], 0, 0))

    def test_every_ability_marked_by_g22_shows_its_effect_in_a_pool_battle(self):
        """The six abilities of step G22 are used in committed pool battles that show what the engine reads, from the
        protocol lines alone: the Speed abilities as an order of the move lines that the weather turns around (the same
        two Pokemon, the slower first without the weather and the faster first with it), Sand Rush's holder with no
        Sandstorm line while foes have them, Inner Focus as its -fail lines and no flinch of its holders, Liquid Voice as
        a hit that the sound move's own type forbids."""
        def trace(name):
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8') as f:
                return json.load(f)

        def moves(step):
            return [l.split('|')[2] for l in step['log'] if l.startswith('|move|')]

        def first_before(step, a, b):
            order = moves(step)
            return a in order and b in order and order.index(a) < order.index(b)

        def weather_of(steps):
            """The weather after each step, from the -weather lines (upkeep lines keep it)."""
            now, out = '', []
            for step in steps:
                for l in step['log']:
                    if l.startswith('|-weather|'):
                        now = '' if l.split('|')[2] == 'none' else l.split('|')[2]
                out.append(now)
            return out

        # Swift Swim: Raichu first without rain, Basculegion first (twice its Speed) in the same turn that the rain starts.
        swim = trace('g22_swift_swim')['steps']
        self.assertTrue(first_before(swim[1], 'p2a: Raichu', 'p1a: Basculegion'))
        self.assertTrue(first_before(swim[2], 'p1a: Basculegion', 'p2a: Raichu') or 'p2a: Raichu' not in moves(swim[2]))
        self.assertTrue(any(l.startswith('|-weather|RainDance|[from] ability: Drizzle') for l in swim[2]['log']))
        # ... and the queued action of the knocked-out holder ties Politoed's: the draw of the queue site.
        self.assertTrue(any(d['site'] == 'SPEED_TIE' and d['context'] == 'queue' and
                            sorted(d['group']) == ['A:move:p1a:liquidation', 'A:move:p1b:weatherball']
                            for step in swim for d in step['draws']))
        # Sand Rush: sand damage on Raichu and Milotic and none on the holders (Houndstone is a Ghost); Houndstone
        # (88 raw Speed, 176 in the sand) before Raichu (130) in the turn after the sandstorm began.
        sand = trace('g22_sand_rush')['steps']
        hits = [l for step in sand for l in step['log'] if l.endswith('[from] Sandstorm')]
        self.assertTrue(any('p2a: Raichu' in l for l in hits) and any('p2b: Milotic' in l for l in hits))
        self.assertFalse([l for l in hits if 'Houndstone' in l or 'Lycanroc' in l])
        self.assertTrue(first_before(sand[2], 'p1a: Houndstone', 'p2a: Raichu'))
        self.assertTrue(any(l.startswith('|move|p1a: Houndstone|Sandstorm') for l in sand[1]['log']))
        # Slush Rush: Milotic before Beartic on the turn of Snowscape, Beartic before Milotic on the next.
        slush = trace('g22_slush_rush')['steps']
        self.assertTrue(first_before(slush[1], 'p2a: Milotic', 'p1a: Beartic'))
        self.assertTrue(first_before(slush[2], 'p1a: Beartic', 'p2a: Milotic'))
        # Chlorophyll: Raichu before Venusaur without the sun, Venusaur before Raichu in the turn that Drought starts it.
        sun = trace('g22_chlorophyll')['steps']
        self.assertTrue(first_before(sun[1], 'p2a: Raichu', 'p1b: Venusaur'))
        self.assertTrue(first_before(sun[2], 'p1b: Venusaur', 'p2a: Raichu') or
                        ('p2a: Raichu' not in moves(sun[2]) and '|faint|p2a: Raichu' in sun[2]['log']))
        self.assertTrue(any(l.startswith('|-weather|SunnyDay|[from] ability: Drought') for l in sun[2]['log']))
        # In a weather that is not theirs the abilities change nothing: the foes at 101 to 120 Speed move before the 98
        # (Basculegion), 88 (Houndstone) and 100 (Venusaur) holders in the sun and the snow, and Beartic (70) is last in the sun.
        foreign = trace('g22_foreign_weather')['steps']
        self.assertEqual(moves(foreign[2]), ['p2a: Milotic', 'p1a: Basculegion', 'p1b: Beartic'])
        self.assertTrue(any(l.startswith('|-weather|SunnyDay|[from] ability: Drought') for l in foreign[2]['log']))
        self.assertEqual(moves(foreign[3]), ['p1b: Beartic', 'p2b: Ninetales', 'p1a: Basculegion'])
        self.assertTrue(any(l.startswith('|-weather|Snowscape|[from] ability: Snow Warning') for l in foreign[3]['log']))
        self.assertEqual(moves(foreign[5])[:4], ['p2b: Ninetales', 'p2a: Abomasnow', 'p1b: Venusaur', 'p1a: Houndstone'])
        # Slush Rush against a tie: Beartic (70 raw, 140 in snow) and Sneasler (raw 140) tie in the queue and, both with
        # Leftovers, in the residual; Sneasler is first on the turn of the Snowscape (Beartic has its raw Speed until
        # the snow is up).
        tie = trace('g22_speed_tie_snow')['steps']
        self.assertEqual(moves(tie[1])[-2:], ['p2a: Sneasler', 'p1a: Beartic'])
        draws = [d for step in tie for d in step['draws'] if d['site'] == 'SPEED_TIE']
        self.assertTrue(any(d['context'] == 'queue' and
                            sorted(d['group']) == ['A:move:p1a:superpower', 'A:move:p2a:shadowclaw'] for d in draws))
        self.assertTrue(any(d['context'] == 'field:Residual' and
                            sorted(d['group']) == ['H:leftovers:p1a:cb', 'H:leftovers:p2a:cb'] for d in draws))
        # Inner Focus: its Intimidate lines say -fail (three times: the entry, and Staraptor's switch-in), the other foe
        # is lowered, Fake Out and the 30 percent Rock Slide flinch Raichu and never Dragonite.
        focus = trace('g22_inner_focus')['steps']
        lines = [l for step in focus for l in step['log']]
        fails = [l for l in lines if l.startswith('|-fail|') and 'unboost|atk' in l]
        self.assertEqual(len(fails), 2)
        self.assertTrue(all(l.endswith('[from] ability: Inner Focus|[of] p2a: Dragonite') for l in fails))
        self.assertTrue(any(l == '|-unboost|p2b: Raichu|atk|1' for l in lines))
        flinches = [l for l in lines if l.startswith('|cant|') and l.endswith('|flinch')]
        self.assertEqual(sorted(set(flinches)), ['|cant|p2b: Raichu|flinch'])
        self.assertGreaterEqual(len(flinches), 2)
        self.assertTrue(any(l.startswith('|move|p1a: Incineroar|Fake Out|p2a: Dragonite') for l in lines))
        # Parting Shot (an effect that is not Intimidate) lowers its Attack all the same.
        self.assertTrue(any(l == '|-unboost|p2a: Dragonite|atk|1' for l in lines))
        # Liquid Voice: Psychic Noise (Psychic) hits Incineroar (a Dark type: immune to Psychic) as a super effective
        # Water move, and Hyper Voice (Normal) hits a Ghost.
        voice = trace('g22_liquid_voice')['steps']
        step = [s for s in voice if any(l.startswith('|move|p1a: Primarina|Psychic Noise|p2b: Incineroar') for l in s['log'])][0]
        after = step['log'][[i for i, l in enumerate(step['log']) if l.startswith('|move|p1a: Primarina|Psychic Noise')][0]:]
        self.assertTrue(after[1].startswith('|-supereffective|p2b: Incineroar'), after[:3])
        self.assertTrue(any(l.startswith('|-damage|p2b: Incineroar|') for l in after[:4]))
        hv = [(s, i) for s in voice for i, l in enumerate(s['log']) if l.startswith('|move|p1a: Primarina|Hyper Voice')]
        self.assertTrue(hv)
        s, i = hv[0]
        self.assertTrue(any(l.startswith('|-damage|p2a: Gholdengo|') for l in s['log'][i:i + 6]))
        self.assertFalse(any(l.startswith('|-immune|') for l in s['log'][i:i + 6]))
        # Every one of the six is marked and has a battle: the manifest lists exactly these.
        with open(os.path.join(ROOT, 'src', 'data', 'support_manifest.c'), encoding='utf-8') as f:
            marked = f.read()
        for name in ('SANDRUSH', 'SWIFTSWIM', 'SLUSHRUSH', 'CHLOROPHYLL', 'INNERFOCUS', 'LIQUIDVOICE'):
            self.assertIn('[DFI_ABILITY_%s] = 1u' % name, marked)
        # (Cursed Body, which G22 left unmarked for want of the Disable volatile, is marked by step G27.)

    def test_the_switch_of_a_damaging_pivot_names_its_move(self):
        """[from] U-turn (step G5) is [from] of the move, as Flip Turn and Parting Shot: the cause MOVE and the move's
        id (the pool tables have U-turn, the extended tables do not: a bare KeyError there, the converter's way to say
        that a name is not in the tables); and every pool battle with a [from] U-turn switch line converts."""
        pool, ext = trace_to_c.load_tables(ROOT, True), trace_to_c.load_tables(ROOT, False)
        move = pool['MOVE']
        self.assertEqual(trace_to_c.ev_cause(['[from] U-turn'], pool)[:2], (trace_to_c.CAUSE['MOVE'], move['UTURN']))
        self.assertEqual(trace_to_c.ev_cause(['[from] Flip Turn'], pool)[:2], (trace_to_c.CAUSE['MOVE'], move['FLIPTURN']))
        self.assertEqual(trace_to_c.ev_cause(['[from] Parting Shot'], pool)[:2], (trace_to_c.CAUSE['MOVE'], move['PARTINGSHOT']))
        self.assertNotEqual(move['UTURN'], move['FLIPTURN'])
        with self.assertRaises(KeyError):
            trace_to_c.ev_cause(['[from] U-turn'], ext)
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            trace_to_c.ev_cause(['[from] Baton Pass'], pool)  # not a move that the converter knows as a cause
        self.assertEqual(cm.exception.rule, 'from-attribute')
        names = ('g5_uturn_a', 'g5_uturn_b', 'g5_uturn_c', 'g5_uturn_d', 'g5_uturn_e')
        seen = {}
        for n in names:
            with open(os.path.join(ROOT, 'tests', 'reference', 'traces', n + '.json'), encoding='utf-8') as f:
                trace = json.load(f)
            seen[n] = sum(1 for step in trace['steps'] for l in step['log'] if '[from] U-turn' in l)
        self.assertEqual(seen['g5_uturn_b'], 0)  # Protect: no pivot
        self.assertTrue(all(seen[n] > 0 for n in names if n not in ('g5_uturn_b',)), seen)

    def test_magic_bounce_move_line_is_accepted_and_another_ability_is_refused(self):
        """Step G57: `[from] ability: Magic Bounce` on a move line is the bounced move (cause ABILITY, id2 the ability + 1, and
        other the source, also for a foeSide hazard, whose label is real then); every other `[from] ability:` on a move line
        still raises move-attribute (a negative control: the acceptance is for Magic Bounce alone)."""
        tables = trace_to_c.load_tables(ROOT, True)
        cause, mb = trace_to_c.CAUSE['ABILITY'], tables['ABILITY'][trace_to_c.key('Magic Bounce')] + 1
        for name in ('g57_mb_whirlwind', 'g57_mb_stealth_rock'):
            spec, trace = trace_to_c.load_battle(ROOT, name)
            data = trace_to_c.convert_battle(name, spec, trace, tables)
            bounced = [e for st in data['steps'] for evs in st['events'] for e in evs
                       if e[0] == trace_to_c.EV['MOVE'] and e[3] == cause]
            self.assertTrue(bounced, name)
            self.assertTrue(all(e[5] == mb for e in bounced), name)
            self.assertTrue(all(e[2] != trace_to_c.NOPOS for e in bounced), name)
        spec, trace = trace_to_c.load_battle(ROOT, 'g57_mb_whirlwind')
        for step in trace['steps']:
            step['log'] = [line.replace('[from] ability: Magic Bounce', '[from] ability: Soundproof') for line in step['log']]
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            trace_to_c.convert_battle('g57_mb_whirlwind', spec, trace, tables)
        self.assertEqual(cm.exception.rule, 'move-attribute')

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
        for fname in ('closure_tables.h', 'closure_tables.c', 'extended_tables.h', 'extended_tables.c',
                      'pool_tables.h', 'pool_tables.c'):
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

    BATTLES = ('c01_team_c_profile', 'c04_flip_turn_ko', 'p2_chilan_berry', 's2_ally_target', 's2_turn_core_1')

    def test_check_of_the_committed_tables_passes(self):
        p = self.run_cli(ROOT, '--check')
        self.assertEqual((p.returncode, p.stderr), (0, ''), p.stdout)
        want = ['trace_to_c: %s matches %s' % (os.path.join(ROOT, 'tests', 'reference', fname), what)
                for fname, what in (('conformance.h', 'the traces'), ('conformance_team_c.h', 'the traces'),
                                    ('conformance_pool.h', 'the traces'),
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

    def test_write_and_check_cover_all_four_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.tree(tmp, self.BATTLES)
            reference = os.path.join(tmp, 'tests', 'reference')
            p = self.run_cli(tmp)
            self.assertEqual((p.returncode, p.stderr), (0, ''))
            self.assertEqual(sorted(f for f in os.listdir(reference) if f.endswith('.h')), sorted(HEADERS))
            self.assertEqual(self.run_cli(tmp, '--check').returncode, 0)
            for fname, what in (('conformance_types.h', 'the template in trace_to_c.py'),
                                ('conformance_pool.h', 'the traces'),
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

class IllusionPP(unittest.TestCase):
    """The foe's knowledge of PP under an Illusion (decision 0026 section 4; trace_to_c.ill_pp_fold, step I2). Hand-made
    states: side 1 has the holder Zoroark (roster 0; Shadow Ball, Sludge Bomb, Protect) shown as the disguise Milotic (roster 1;
    Protect, Scald). Without the fold the foe's PP is the true PP, and the checks on a disguised row fail."""

    def state(self, zoroark_pp, milotic_pp, active=(0, -1)):
        def mon(species, pp):
            return {'species': species, 'set_species': species, 'pp': list(pp)}
        return {'sides': [{'pokemon': [mon('Ceruledge', [8])], 'active': [0, -1]},
                          {'pokemon': [mon('Zoroark', zoroark_pp), mon('Milotic', milotic_pp)], 'active': list(active)}]}

    def plain_uses(self, log, tables):
        """The charge of every move line at 1 (no Pressure in these states), as the event pass of the converter gives them."""
        uses = [[], []]
        for line in log:
            parts = line.split('|')
            if len(parts) >= 4 and parts[1] == 'move' and '[from] lockedmove' not in parts[5:]:
                uses[int(parts[2][1]) - 1].append((tables['MOVE'][trace_to_c.key(parts[3])], 1))
        return uses

    def tables_and_teams(self):
        tables = {'MOVE': {trace_to_c.key(n): i + 1 for i, n in enumerate(
            ['Shadow Ball', 'Sludge Bomb', 'Protect', 'Scald'])}, 'ABILITY': {trace_to_c.key('Illusion'): 4}}
        teams = [[{'ability': 0, 'moves': [1]}],
                 [{'ability': 5, 'moves': [1, 2, 3]}, {'ability': 0, 'moves': [3, 4]}]]
        return tables, teams

    def run_fold(self, steps):
        """The foe's PP of every row after each step: the start PP less the counts the fold attributes (pp_foe)."""
        tables, teams = self.tables_and_teams()
        roster_of = [{'Ceruledge': 0}, {'Zoroark': 0, 'Milotic': 1}]
        win, spent, out = [None, None], {}, []
        start = self.state([16, 12, 8], [8, 16])
        start_pp = {}
        for s in range(2):
            for p in start['sides'][s]['pokemon']:
                start_pp[(s, roster_of[s][p['species']])] = list(p['pp']) + [0] * (4 - len(p['pp']))
        prev = start
        for log, new in steps:
            trace_to_c.ill_pp_fold(log, prev, new, roster_of, teams, tables, 4, win, spent, {}, self.plain_uses(log, tables))
            out.append({key: tuple(max(0, start_pp[key][k] - spent.get(key, [0, 0, 0, 0])[k]) for k in range(4))
                        for key in start_pp})
            prev = new
        return out

    ENTER = ['|switch|p2a: Milotic|Milotic, L50, F|167/167']

    def test_a_move_not_on_the_disguise_sheet_is_pending_until_the_break(self):
        # Zoroark, disguised as Milotic, uses Sludge Bomb under the name Milotic: the foe still counts 12 on Zoroark.
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16])),
                 (['|move|p2a: Milotic|Sludge Bomb|p1a: Ceruledge'], self.state([16, 11, 8], [8, 16]))]
        known = self.run_fold(steps)
        self.assertEqual(known[1][(1, 0)], (16, 12, 8, 0))  # the holder's row, frozen (true 11)
        self.assertEqual(known[1][(1, 1)], (8, 16, 0, 0))   # the disguise's row is not touched by Sludge Bomb

    def test_a_move_on_the_disguise_sheet_counts_on_the_disguise_row(self):
        # Zoroark uses Protect (on both sheets) under the name Milotic: the foe counts it on Milotic, not on Zoroark.
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16])),
                 (['|move|p2a: Milotic|Protect|p2a: Milotic'], self.state([16, 12, 7], [8, 16]))]
        known = self.run_fold(steps)
        self.assertEqual(known[1][(1, 0)], (16, 12, 8, 0))  # Zoroark's Protect stays 8 for the foe
        self.assertEqual(known[1][(1, 1)], (7, 16, 0, 0))   # Milotic's Protect shows the use

    def test_the_break_brings_the_holder_to_the_truth(self):
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16])),
                 (['|move|p2a: Milotic|Sludge Bomb|p1a: Ceruledge'], self.state([16, 11, 8], [8, 16])),
                 (['|replace|p2a: Zoroark|Zoroark, L50, F|167/167', '|-end|p2a: Zoroark|Illusion'], self.state([16, 11, 8], [8, 16]))]
        known = self.run_fold(steps)
        self.assertEqual(known[2][(1, 0)], (16, 11, 8, 0))  # the pending use is attributed at the break
        self.assertEqual(known[2][(1, 1)], (8, 16, 0, 0))   # the disguise's row restored to its value before the disguise

    def test_negative_control_the_foe_knows_pp_foe_and_the_owner_the_true_pp(self):
        """Negative control: where the true PP and the foe's PP differ (Sludge Bomb used under the disguise's name), the row
        the converter emits carries both: the true PP for the owner (conformance_compare.c uses pp for the owner's viewer)
        and pp_foe for the foe. A converter that put the true PP into pp_foe fails the foe assertion below."""
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16])),
                 (['|move|p2a: Milotic|Sludge Bomb|p1a: Ceruledge'], self.state([16, 11, 8], [8, 16]))]
        out = self.run_fold(steps)
        true_row = steps[1][1]['sides'][1]['pokemon'][0]['pp'] + [0]
        shown_row = out[1][(1, 0)]
        self.assertEqual(true_row, [16, 11, 8, 0])            # the owner's row: the true PP
        self.assertEqual(shown_row, (16, 12, 8, 0))           # the foe's row: what it was shown
        self.assertNotEqual(tuple(true_row), shown_row)       # the two differ, so the negative control has teeth

    def status_state(self, zoro, milo):
        """A state with the statuses of the two Pokemon of side 1: zoro = (pp, status), milo = (pp, status)."""
        def mon(species, pp, status):
            return {'species': species, 'set_species': species, 'pp': list(pp), 'status': status}
        return {'sides': [{'pokemon': [mon('Ceruledge', [8], '')], 'active': [0, -1]},
                          {'pokemon': [mon('Zoroark', zoro[0], zoro[1]), mon('Milotic', milo[0], milo[1])], 'active': [0, -1]}]}

    def run_status_fold(self, steps):
        tables, teams = self.tables_and_teams()
        roster_of = [{'Ceruledge': 0}, {'Zoroark': 0, 'Milotic': 1}]
        win, spent, sst = [None, None], {}, {}
        prev = self.status_state(([16, 12, 8], ''), ([8, 16], ''))
        for log, new in steps:
            trace_to_c.ill_pp_fold(log, prev, new, roster_of, teams, tables, 4, win, spent, sst, self.plain_uses(log, tables))
            prev = new
        return win, sst

    def test_negative_control_the_foe_shows_the_status_of_the_name(self):
        """Negative control (decision 0026 section 4, shown_status): the holder is burned under the disguise's name. The foe's
        holder row keeps the status it knew before (none), the disguise's row shows the burn, and the owner's row is the truth
        (the converter emits shown_status for the foe and the true status is compared for the owner). A converter that put the
        true status into shown_status fails the foe assertions."""
        steps = [(self.ENTER, self.status_state(([16, 12, 8], ''), ([8, 16], ''))),
                 (['|-status|p2a: Milotic|brn'], self.status_state(([16, 12, 8], 'brn'), ([8, 16], '')))]
        win, sst = self.run_status_fold(steps)
        true_holder = steps[1][1]['sides'][1]['pokemon'][0]['status']
        self.assertEqual(true_holder, 'brn')                              # the owner's row: the true status
        self.assertEqual(trace_to_c.status_map(steps[1][1], [{'Ceruledge': 0}, {'Zoroark': 0, 'Milotic': 1}])[(1, 0)], 'brn')
        self.assertEqual(sst.get((1, 0)), '')                             # the foe's holder row: frozen, none
        self.assertEqual(sst.get((1, 1)), 'brn')                          # the foe's disguise row: the burn of the name
        self.assertNotEqual(sst.get((1, 0)), true_holder)                 # the two differ, so the control has teeth

    def test_the_break_gives_the_holder_the_last_status_shown(self):
        steps = [(self.ENTER, self.status_state(([16, 12, 8], ''), ([8, 16], ''))),
                 (['|-status|p2a: Milotic|brn'], self.status_state(([16, 12, 8], 'brn'), ([8, 16], ''))),
                 (['|replace|p2a: Zoroark|Zoroark, L50, M', '|-end|p2a: Zoroark|Illusion'],
                  self.status_state(([16, 12, 8], 'brn'), ([8, 16], '')))]
        win, sst = self.run_status_fold(steps)
        self.assertEqual(sst.get((1, 0)), 'brn')   # the holder takes the status the name showed last
        self.assertIn(sst.get((1, 1)), (None, ''))  # the disguise's row goes back to its status before the disguise (None: the true one)

    def test_a_disguise_without_a_use_is_the_truth(self):
        known = self.run_fold([(self.ENTER, self.state([16, 12, 8], [8, 16]))])
        self.assertEqual(known[0][(1, 0)], (16, 12, 8, 0))
        self.assertEqual(known[0][(1, 1)], (8, 16, 0, 0))



def trace_ev(kind, pos, other, cause, ident, ident2, hp, hpmax, hp_kind, flags=0):
    """An event tuple as convert_battle reads it: the kind, position, other, cause, id, id2, hp, hp max, hp kind, flags at 13."""
    return (trace_to_c.EV[kind], pos, other, cause, ident, ident2, hp, hpmax, hp_kind, 0, 0, 0, 0, flags)


class IllusionPressure(unittest.TestCase):
    """A disguised holder's move that hits a Pressure target (decision 0026 section 4 with decision 0030 section 1): the move is
    charged 1 plus the Pressure extra of the owner's standing Pressure Pokemon that it targets. On the disguise's sheet the charge
    goes to the disguise's row; off it, the charge is pending and reaches the holder only at the break. The owner (side 0, Ceruledge
    with Pressure) is the viewer; side 1 is the holder Zoroark (roster 0, sheet Shadow Ball, Sludge Bomb, Protect) disguised as
    Milotic (roster 1, sheet Protect, Scald)."""

    def tables_teams(self):
        tables = {'MOVE': {trace_to_c.key(n): i + 1 for i, n in enumerate(
                      ['Shadow Ball', 'Sludge Bomb', 'Protect', 'Scald'])},
                  'ABILITY': {trace_to_c.key('Illusion'): 4, trace_to_c.key('Pressure'): 2},
                  'MOVE_CLASS': {1: 0, 2: 0, 3: 0, 4: 0}, 'MOVE_MUST': {1: 0, 2: 0, 3: 0, 4: 0}}
        teams = [[{'ability': 3, 'moves': [1]}],  # the owner's Pressure Pokemon (the sheet's ability is id + 1)
                 [{'ability': 5, 'moves': [1, 2, 3]}, {'ability': 0, 'moves': [3, 4]}]]
        return tables, teams

    def state(self, zoro_pp, milo_pp):
        def mon(species, pp):
            return {'species': species, 'set_species': species, 'pp': list(pp)}
        return {'sides': [{'pokemon': [mon('Ceruledge', [8])], 'active': [0, -1]},
                          {'pokemon': [mon('Zoroark', zoro_pp), mon('Milotic', milo_pp)], 'active': [0, -1]}]}

    def fold(self, steps):
        """steps: (log, new state, the owner's events of the step). Returns (spent, the window after each step, the charges)."""
        tables, teams = self.tables_teams()
        roster_of = [{'Ceruledge': 0}, {'Zoroark': 0, 'Milotic': 1}]
        pressure = trace_to_c.FoePressure(tables, teams)
        win, spent, sst = [None, None], {}, {}
        prev = self.state([16, 12, 8], [8, 16])
        windows, charges = [], []
        for log, new, owner_events in steps:
            uses = pressure.step([owner_events, []])
            charges.append(uses)
            trace_to_c.ill_pp_fold(log, prev, new, roster_of, teams, tables, 4, win, spent, sst, uses)
            windows.append(win[1])
            prev = new
        return spent, windows, charges

    def own_switch(self):
        # the owner's Ceruledge enters at position 0, healthy (EV SWITCH, id = roster 0, hp 100)
        return (trace_ev('SWITCH', 0, 0xFF, 0, 0, 0, 100, 100, 1),)

    ENTER = ['|switch|p2a: Milotic|Milotic, L50, F|167/167']

    def test_a_move_on_the_disguise_sheet_is_charged_to_the_disguise_with_the_pressure_extra(self):
        # Milotic (the disguise) uses Scald at the owner's Ceruledge: Scald is on the disguise's sheet, one extra PP: 2 counts.
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16]), self.own_switch()),
                 (['|move|p2a: Milotic|Scald|p1a: Ceruledge'], self.state([16, 12, 8], [8, 16]),
                  (trace_ev('MOVE', 2, 0, 0, 4, 0, 0, 0, 0),))]
        spent, windows, charges = self.fold(steps)
        self.assertEqual(charges[1], [[], [(4, 2)]])                 # Scald, 1 plus the extra of the standing Pressure target
        self.assertEqual(spent[(1, 1)], [0, 2, 0, 0])                # the disguise's row: Scald is slot 1 of its sheet
        self.assertEqual(spent.get((1, 0), [0, 0, 0, 0]), [0, 0, 0, 0])  # the holder's row stays what the foe knew
        self.assertEqual(windows[1]['pending'], [0, 0, 0, 0])

    def test_a_move_off_the_disguise_sheet_is_pending_and_reaches_the_holder_at_the_break(self):
        # The disguise (Milotic) is shown using Shadow Ball, which is not on its sheet: the 2 counts stay pending, out of every row.
        steps = [(self.ENTER, self.state([16, 12, 8], [8, 16]), self.own_switch()),
                 (['|move|p2a: Milotic|Shadow Ball|p1a: Ceruledge'], self.state([16, 12, 8], [8, 16]),
                  (trace_ev('MOVE', 2, 0, 0, 1, 0, 0, 0, 0),)),
                 (['|replace|p2a: Zoroark|Zoroark, L50, F|167/167', '|-end|p2a: Zoroark|Illusion'],
                  self.state([14, 12, 8], [8, 16]), ())]
        spent, windows, charges = self.fold(steps)
        self.assertEqual(charges[1], [[], [(1, 2)]])
        self.assertEqual(windows[1]['pending'], [2, 0, 0, 0])        # Shadow Ball is slot 0 of the holder's sheet
        self.assertEqual(spent.get((1, 1), [0, 0, 0, 0]), [0, 0, 0, 0])   # nothing on the disguise's row
        self.assertIsNone(windows[2])                                 # the break ends the disguise
        self.assertEqual(spent[(1, 0)], [2, 0, 0, 0])                 # the holder takes the pending 2 at the break
        self.assertEqual(spent[(1, 1)], [0, 0, 0, 0])                 # the disguise's row restored to its snapshot


class FormeStance(unittest.TestCase):
    """NAMED RULE FORME-STANCE (step G66, decision 0040): a `-formechange` line with no attribute is accepted only for
    Aegislash or Aegislash-Blade, only right before the move line of the same position, and the Shield's forme only before
    King's Shield. Each negative control changes an in-memory copy of a committed battle and asserts the rule."""

    NAME = 'g66_blade_shield_cycle'
    CASE = '|-formechange|p1a: Aegislash|Aegislash-Blade|'

    def mutated(self, fn):
        spec, trace = battle(self.NAME)
        changed = 0
        for st in trace['steps']:
            new = []
            for line in st['log']:
                if line.startswith('|-formechange|'):
                    line = fn(line)
                    changed += 1
                new.append(line)
            st['log'] = new
        self.assertGreater(changed, 0, 'the committed battle has the -formechange lines')
        return spec, trace

    def test_committed_lines_convert(self):
        spec, trace = battle(self.NAME)
        convert(self.NAME, spec, trace)  # no ConversionError: the rule accepts the recorded shapes

    def test_species_other_than_aegislash_refused(self):
        spec, trace = self.mutated(lambda l: l.replace('|Aegislash-Blade|', '|Garchomp|', 1))
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            convert(self.NAME, spec, trace)
        self.assertEqual(cm.exception.rule, 'formechange-line')

    def test_shield_forme_before_another_move_refused(self):
        # The Blade move (Iron Head) with the Shield's species: the Shield changes only before King's Shield.
        spec, trace = self.mutated(lambda l: l.replace('|Aegislash-Blade|', '|Aegislash|', 1))
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            convert(self.NAME, spec, trace)
        self.assertEqual(cm.exception.rule, 'formechange-line')

    def test_blade_forme_before_king_s_shield_refused(self):
        # Turn 2: the Shield forme before King's Shield. Making it the Blade is refused (King's Shield never gives the Blade).
        spec, trace = self.mutated(lambda l: l.replace('|p1a: Aegislash|Aegislash|', '|p1a: Aegislash|Aegislash-Blade|'))
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            convert(self.NAME, spec, trace)
        self.assertEqual(cm.exception.rule, 'formechange-line')

    def test_attribute_from_another_ability_refused(self):
        spec, trace = self.mutated(lambda l: l + '[from] ability: Trace' if l.endswith('|') else l)
        with self.assertRaises(trace_to_c.ConversionError) as cm:
            convert(self.NAME, spec, trace)
        self.assertEqual(cm.exception.rule, 'formechange-line')


if __name__ == '__main__':
    unittest.main()
