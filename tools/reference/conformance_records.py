#!/usr/bin/env python3
"""Records of converted conformance battles: the input of the C runner
(tools/difftest, duoforge_diff_runner) and of the test that checks the records
against the compiled tables (duoforge.reference.runner_records).

usage: python tools/reference/conformance_records.py --all <repo root> --out <dir>

Converts every committed battle (tests/reference/specs and traces) with
trace_to_c and writes <dir>/closure.records, <dir>/team_c.records and
<dir>/pool.records: the battles of conformance.h, of conformance_team_c.h and
of conformance_pool.h, in the same order. The pool battles (decision 0015)
carry team_c 1 (the pool tables keep the extended ids) and the data kind POOL:
they run under it alone, as they use ids the Team C tables do not have.

As a library, write_battle(data, team_c, out, kind=0, domain=()) writes one
battle of convert_battle's data to the text stream `out`, all or nothing.

The format is ASCII, LF line ends, one record per line, tokens separated by
one space. Every number is an unsigned decimal integer below 2**32; every
value is written, there are no defaults. A battle is

    B <name> <team_c> <kind> <member_count> <step_count> <dropped_total> <domain_count>
    M <side> <index> <member row>          member_count lines per side, side 0 first
    D <step> <side> <count>                a domain sample, before the S record of its step
    C <choice>                             its count choices
    S <step record>                        step_count times, each followed by
    T <site> <lo> <hi> <value>             the step's kept draws (tape_len lines) and
    E <event>                              its events, player 0's then player 1's
                                           (ev_len[0] + ev_len[1] lines)
    END

<name> is [A-Za-z0-9_]{1,63}, <team_c> is 0 (closure) or 1 (Team C). <kind>
is the data kind the runner must create the battle under, with no fallback (a
DUOFORGE_DATA_KIND_* value of duoforge.h: CLOSURE or CLOSURE_DEV for a closure
battle, TEAM_C, TEAM_C_DEV, POOL or POOL_DEV for the extended ids), or 0 for the conformance fallback of
the replay: CLOSURE, then CLOSURE_DEV when that cannot create it, and the Team
C pair likewise.

A domain sample (random play) is the set of choices that the reference accepted
from one side before one step: the runner compares it with the engine's
candidates for that side (duoforge_battle_candidates) before it applies the
step. <domain_count> says how many there are (0 for the conformance battles).
A sample of step <step> comes right before that step's S record, side 0 before
side 1, and only for a side that answers the step; its <count> (1 to 784) C
records follow, strictly ascending (as the 18 numbers read, so a set has no
duplicate). A choice is the engine's side choice without its epoch and side:

    C <kind> <pick_count> <6 picks> <2 slot commands of 5 numbers each>

<kind> is DUOFORGE_CHOICE_TEAM_SELECTION (1) or DUOFORGE_CHOICE_SLOTS (2); a
team choice has its <pick_count> picks (roster indices, leads first, the rest 0)
and zero commands, a slots choice zero picks and the commands in the order of
duoforge_slot_command (kind, move_slot, target, mega, reserve), all-zero for a
slot that is not requested. A choice is what trace_to_c.convert_choice makes of a
Showdown choice text ('team' or 'slots', see flat_choice).

The member row, the step record and the event are the nested int tuples of
convert_battle's data and of step_record() below, flattened in order: the
leaves of a df_conf_member, of a df_conf_step and of a duoforge_event, in the
order they are declared in tests/reference/conformance_types.h. Nothing here
lists those fields: the order is the converter's. The offsets of a step record
(tape_off, ev_off) are into the tape and the events of its own battle, from
0; tape_off and ev_off count the T and E lines before the step.
"""
import argparse
import io
import os
import re
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import trace_to_c  # noqa: E402

NAME = re.compile(r'[A-Za-z0-9_]{1,63}')
MAX_MEMBERS = 6
MAX_VALUE = 0xFFFFFFFF


def flatten(value, where):
    """The ints of a nested tuple in order. Anything but an int from 0 to
    2**32 - 1 (a bool, a float, a negative) is a bug of the converter or of
    this module: ValueError, never written."""
    if isinstance(value, (tuple, list)):
        for i, item in enumerate(value):
            yield from flatten(item, '%s[%d]' % (where, i))
    elif type(value) is int and 0 <= value <= MAX_VALUE:
        yield value
    else:
        raise ValueError('%s: %r is not an unsigned 32-bit integer' % (where, value))


def record(tag, value, where):
    return ' '.join([tag] + [str(v) for v in flatten(value, where)])


def data_kinds(root):
    """{name: value} of the DUOFORGE_DATA_KIND_* constants of include/duoforge/duoforge.h."""
    with io.open(os.path.join(root, 'include', 'duoforge', 'duoforge.h'), encoding='utf-8') as f:
        text = f.read()
    return {m.group(1): int(m.group(2)) for m in re.finditer(r'^#define DUOFORGE_DATA_KIND_(\w+)\s+(\d+)u', text, re.M)}


CHOICE_TEAM = 1   # DUOFORGE_CHOICE_TEAM_SELECTION
CHOICE_SLOTS = 2  # DUOFORGE_CHOICE_SLOTS
MAX_PICKS = 6     # DUOFORGE_MAX_ROSTER
MAX_CANDIDATES = 784  # DUOFORGE_MAX_CANDIDATES: the most choices of a sample
FLAT_CHOICE_LEN = 18  # kind, pick_count, 6 picks, 2 commands of 5


def flat_choice(choice):
    """The 18 ints of a C record for a choice as trace_to_c.convert_choice returns it: ('team', picks) or ('slots',
    [command, command]) with a command (kind, move_slot, target, mega, reserve). ValueError for anything else."""
    try:
        kind, value = choice
    except (TypeError, ValueError):
        raise ValueError('a choice is (kind, value), not %r' % (choice,)) from None
    if kind == 'team':
        picks = list(value)
        if not 1 <= len(picks) <= MAX_PICKS:
            raise ValueError('a team choice has 1 to %d picks, not %r' % (MAX_PICKS, picks))
        return (CHOICE_TEAM, len(picks), *picks, *([0] * (MAX_PICKS - len(picks))), *([0] * 10))
    if kind == 'slots':
        commands = [tuple(c) for c in value]
        if len(commands) != 2 or any(len(c) != 5 for c in commands):
            raise ValueError('a slots choice has 2 commands of 5 numbers, not %r' % (value,))
        return (CHOICE_SLOTS, 0, *([0] * MAX_PICKS), *commands[0], *commands[1])
    raise ValueError('a choice is a team or slots choice, not %r' % (kind,))


def domain_lines(name, steps, domain):
    """{step: [D and C lines]} of the domain samples `domain` (dicts with 'step', 'side' and 'choices', the choices of
    a sample in ascending order of their flat form) of a battle of `steps`; ValueError for what the format cannot
    hold: a sample outside the battle, for a side that does not answer its step, twice, empty, too large, with
    choices that are not strictly ascending."""
    by_step = {}
    seen = set()
    for sample in domain:
        step, side, choices = sample['step'], sample['side'], sample['choices']
        where = '%s domain sample of step %r side %r' % (name, step, side)
        if type(step) is not int or not 0 <= step < len(steps) or type(side) is not int or side not in (0, 1):
            raise ValueError('%s: not a step of the battle (%d steps) and a side' % (where, len(steps)))
        if (step, side) in seen:
            raise ValueError('%s: given twice' % where)
        seen.add((step, side))
        if not steps[step]['answered%d' % side]:
            raise ValueError('%s: the side does not answer the step' % where)
        flats = [flat_choice(c) for c in choices]
        if not 1 <= len(flats) <= MAX_CANDIDATES:
            raise ValueError('%s: %d choices, not 1 to %d' % (where, len(flats), MAX_CANDIDATES))
        if any(a >= b for a, b in zip(flats, flats[1:])):
            raise ValueError('%s: the choices are not strictly ascending' % where)
        lines = [record('D', (step, side, len(flats)), where)]
        lines += [record('C', flat, where + ' choice') for flat in flats]
        by_step.setdefault(step, []).append((side, lines))
    return {step: [line for _, lines in sorted(groups) for line in lines] for step, groups in by_step.items()}


def write_battle(data, team_c, out, kind=0, domain=()):
    """One battle of convert_battle's data as records, to the text stream
    `out`. `team_c` says which tables the battle was converted with (the
    runner picks its contexts by it); `kind` the data kind it must run under
    with no fallback, or 0; `domain` its domain samples (see domain_lines).
    ValueError for data the format cannot hold; then nothing has been written."""
    name = data['name']
    if NAME.fullmatch(name) is None:
        raise ValueError('battle name %r is not [A-Za-z0-9_]{1,63}' % name)
    if not isinstance(team_c, bool):
        raise ValueError('%s: team_c must be a bool, not %r' % (name, team_c))
    count = data['member_count']
    if not 1 <= count <= MAX_MEMBERS or len(data['members']) != 2 or any(len(rows) != count for rows in data['members']):
        raise ValueError('%s: both sides need member_count (%r, 1 to %d) members' % (name, count, MAX_MEMBERS))
    steps = data['steps']
    if not steps:
        raise ValueError('%s: a battle has at least one step' % name)
    domain = list(domain)
    sampled = domain_lines(name, steps, domain)
    lines = ['B ' + name + ' ' + ' '.join(str(v) for v in flatten(
        (int(team_c), kind, count, len(steps), data['dropped_total'], len(domain)), 'B ' + name))]
    for side, rows in enumerate(data['members']):
        for index, row in enumerate(rows):
            lines.append(record('M', (side, index, row), '%s member %d of side %d' % (name, index, side)))
    tape_off = 0
    ev_off = 0
    for i, st in enumerate(steps):
        where = '%s step %d' % (name, i)
        if len(st['events']) != 2:
            raise ValueError('%s: events of %d players, not 2' % (where, len(st['events'])))
        ev_len = tuple(len(evs) for evs in st['events'])
        offsets = (ev_off, ev_off + ev_len[0])
        lines.extend(sampled.get(i, ()))
        lines.append(record('S', trace_to_c.step_record(st, tape_off, offsets, ev_len), where))
        for entry in st['tape']:
            lines.append(record('T', entry, where + ' tape'))
        for evs in st['events']:
            for event in evs:
                lines.append(record('E', event, where + ' event'))
        tape_off += len(st['tape'])
        ev_off += ev_len[0] + ev_len[1]
    lines.append('END')
    out.write('\n'.join(lines) + '\n')


def committed_battles(root):
    """The names of the committed battles, sorted: the order of the generated headers."""
    return sorted(f[:-5] for f in os.listdir(os.path.join(root, 'tests', 'reference', 'traces')) if f.endswith('.json'))


def write_all(root, outdir):
    """closure.records, team_c.records and pool.records of every committed
    battle into `outdir`; returns the three paths with their battle counts."""
    tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
    pool_kind = data_kinds(root)['POOL']
    files = ('closure', 'team_c', 'pool')
    streams = {data: io.StringIO() for data in files}
    counts = {data: 0 for data in files}
    for name in committed_battles(root):
        spec, trace = trace_to_c.load_battle(root, name)
        data = trace_to_c.spec_data(name, spec)
        team_c = data != 'closure'
        write_battle(trace_to_c.convert_battle(name, spec, trace, tables[team_c]), team_c, streams[data],
                     kind=pool_kind if data == 'pool' else 0)
        counts[data] += 1
    os.makedirs(outdir, exist_ok=True)
    written = []
    for data in files:
        path = os.path.join(outdir, data + '.records')
        with io.open(path, 'w', encoding='ascii', newline='\n') as f:
            f.write(streams[data].getvalue())
        written.append((path, counts[data]))
    return written


def main(argv):
    parser = argparse.ArgumentParser(prog='conformance_records.py', description=__doc__.split('\n')[0])
    parser.add_argument('--all', metavar='ROOT', required=True, help='the repository root: every committed battle')
    parser.add_argument('--out', metavar='DIR', required=True, help='where closure.records, team_c.records and pool.records go')
    args = parser.parse_args(argv)
    for path, n in write_all(args.all, args.out):
        print('conformance_records: wrote %s (%d battles)' % (path, n))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
