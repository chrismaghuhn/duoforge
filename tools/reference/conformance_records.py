#!/usr/bin/env python3
"""Records of converted conformance battles: the input of the C runner
(tools/difftest, duoforge_diff_runner) and of the test that checks the records
against the compiled tables (duoforge.reference.runner_records).

usage: python tools/reference/conformance_records.py --all <repo root> --out <dir>

Converts every committed battle (tests/reference/specs and traces) with
trace_to_c and writes <dir>/closure.records and <dir>/team_c.records: the
battles of conformance.h and of conformance_team_c.h, in the same order.

As a library, write_battle(data, team_c, out) writes one battle of
convert_battle's data to the text stream `out`, all or nothing.

The format is ASCII, LF line ends, one record per line, tokens separated by
one space. Every number is an unsigned decimal integer below 2**32; every
value is written, there are no defaults. A battle is

    B <name> <team_c> <member_count> <step_count> <dropped_total>
    M <side> <index> <member row>          member_count lines per side, side 0 first
    S <step record>                        step_count times, each followed by
    T <site> <lo> <hi> <value>             the step's kept draws (tape_len lines) and
    E <event>                              its events, player 0's then player 1's
                                           (ev_len[0] + ev_len[1] lines)
    END

<name> is [A-Za-z0-9_]{1,63}, <team_c> is 0 (closure) or 1 (Team C). The
member row, the step record and the event are the nested int tuples of
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


def write_battle(data, team_c, out):
    """One battle of convert_battle's data as records, to the text stream
    `out`. `team_c` says which tables the battle was converted with (the
    runner picks its contexts by it). ValueError for data the format cannot
    hold; then nothing has been written."""
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
    lines = ['B ' + name + ' ' + ' '.join(str(v) for v in flatten(
        (int(team_c), count, len(steps), data['dropped_total']), 'B ' + name))]
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
    """closure.records and team_c.records of every committed battle into
    `outdir`; returns the two paths with their battle counts."""
    tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
    streams = {False: io.StringIO(), True: io.StringIO()}
    counts = {False: 0, True: 0}
    for name in committed_battles(root):
        spec, trace = trace_to_c.load_battle(root, name)
        team_c = trace_to_c.spec_is_team_c(name, spec)
        write_battle(trace_to_c.convert_battle(name, spec, trace, tables[team_c]), team_c, streams[team_c])
        counts[team_c] += 1
    os.makedirs(outdir, exist_ok=True)
    written = []
    for team_c, fname in ((False, 'closure.records'), (True, 'team_c.records')):
        path = os.path.join(outdir, fname)
        with io.open(path, 'w', encoding='ascii', newline='\n') as f:
            f.write(streams[team_c].getvalue())
        written.append((path, counts[team_c]))
    return written


def main(argv):
    parser = argparse.ArgumentParser(prog='conformance_records.py', description=__doc__.split('\n')[0])
    parser.add_argument('--all', metavar='ROOT', required=True, help='the repository root: every committed battle')
    parser.add_argument('--out', metavar='DIR', required=True, help='where closure.records and team_c.records go')
    args = parser.parse_args(argv)
    for path, n in write_all(args.all, args.out):
        print('conformance_records: wrote %s (%d battles)' % (path, n))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
