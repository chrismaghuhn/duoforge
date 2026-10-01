#!/usr/bin/env python3
"""Turns reference traces (tools/reference/ps_trace.js) into C fixture
tables for the conformance test (decision 0006 sections 5.1 and 7).

usage: python tools/reference/trace_to_c.py <repo root> [--check]

Reads tests/reference/specs/*.json and tests/reference/traces/*.json and
writes tests/reference/conformance.h (or, with --check, compares).

Draws: every draw of the reference becomes a tape entry, except the
families decision 0006 section 5.1 (proposal B) drops. Each drop rule
checks its precondition and fails loudly otherwise:

  TEAM_ORDER        always: the team-preview actions are independent per side
  SPEED_TIE each:*  only if no tied Pokemon has a handler for that event
  SPEED_TIE switch-order
                    only if no tied Pokemon has a SwitchIn handler
  SPEED_TIE field:Residual
                    only if every tied handler only counts down a duration
  INSERT_TIE        only if the queue holds nothing but runSwitch actions of
                    Pokemon without SwitchIn handlers
  RANDOM_TARGET action-speed, resolve
                    always: the target computed for ModifyPriority or a
                    queued choice is read by no closure handler
  RANDOM_TARGET execute:allAdjacentFoes
                    always: the main target of a spread move only labels
                    the protocol line; the move hits every adjacent foe

Shuffle draws (SPEED_TIE queue) are made relative to the shuffled group:
random(i, n) with i and n counted from the group's first index.

Stdlib only; CTest runs it with --check when Python is available.
"""
import io
import json
import os
import re
import sys

SITES = {'SPEED_TIE': 1, 'ACCURACY': 2, 'CRIT': 3, 'DAMAGE_ROLL': 4, 'SECONDARY': 5, 'STALL': 6,
         'SLEEP_TURNS': 7, 'FREEZE_THAW': 8, 'FULL_PARALYSIS': 9, 'CONFUSION_TURNS': 10,
         'CONFUSION_HIT': 11, 'RANDOM_TARGET': 12}
STATS = ['HP', 'Atk', 'Def', 'SpA', 'SpD', 'Spe']
GENDER = {'M': 1, 'F': 2}
GENDERLESS = 3


def ids(header, prefix):
    out = {}
    for m in re.finditer(r'#define DFI_%s_([A-Z0-9]+) (\d+)u' % prefix, header):
        out[m.group(1)] = int(m.group(2))
    return out


def key(name):
    return re.sub(r'[^A-Za-z0-9]', '', name).upper()


def parse_team(text, tables):
    """A Showdown paste as written by the specs: name, gender, item, ability,
    EVs (Stat Points), nature, moves."""
    team = []
    for block in text.strip().split('\n\n'):
        lines = [l.strip() for l in block.strip().split('\n')]
        head = lines[0]
        item = 0
        if ' @ ' in head:
            head, item_name = head.split(' @ ')
            item = tables['ITEM'][key(item_name)] + 1
        m = re.match(r'^(.+?)(?: \(([MF])\))?$', head)
        species_name, gender_tag = m.group(1), m.group(2)
        forme = tables['FORME'][key(species_name)]
        mon = {'species': forme, 'item': item, 'ability': None, 'nature': None, 'sp': [0] * 6, 'moves': []}
        rule = tables['GENDER_RULE'][forme]
        if gender_tag:
            mon['gender'] = GENDER[gender_tag]
        elif rule == 3:
            mon['gender'] = GENDERLESS
        else:
            raise SystemExit('trace_to_c: %s has no gender; specs always state it' % species_name)
        for line in lines[1:]:
            if line.startswith('Ability: '):
                name = line[len('Ability: '):]
                mon['ability'] = 0 if name == 'No Ability' else tables['ABILITY'][key(name)] + 1
            elif line.startswith('EVs: '):
                for part in line[len('EVs: '):].split(' / '):
                    value, stat = part.split(' ')
                    mon['sp'][STATS.index(stat)] = int(value)
            elif line.endswith(' Nature'):
                mon['nature'] = tables['NATURE'][key(line[:-len(' Nature')])]
            elif line.startswith('- '):
                mon['moves'].append(tables['MOVE'][key(line[2:])])
            elif line.startswith('Level: '):
                if line != 'Level: 50':
                    raise SystemExit('trace_to_c: level 50 only')
            else:
                raise SystemExit('trace_to_c: unknown line %r' % line)
        if mon['ability'] is None or mon['nature'] is None:
            raise SystemExit('trace_to_c: %s needs an ability and a nature' % species_name)
        team.append(mon)
    return team


def drop_reason(d):
    site, ctx, group = d['site'], d.get('context', ''), d.get('group')
    if site == 'TEAM_ORDER':
        return 'team-preview order'
    if site == 'SPEED_TIE' and ctx.startswith('each:'):
        if all(g.startswith('P:') and g.endswith(':0') for g in group):
            return 'each-event tie without handlers'
        raise SystemExit('trace_to_c: %s tie between Pokemon with handlers: %s' % (ctx, group))
    if site == 'SPEED_TIE' and ctx == 'switch-order':
        # P:<slot>:<SwitchIn handlers>:<S entering | - not>; the order decides
        # something only between two entering Pokemon with handlers.
        bearers = sum(1 for g in group if g.split(':')[2] != '0' and g.split(':')[3] == 'S')
        if bearers <= 1:
            return 'switch-in order with at most one entry effect'
        return None  # the engine draws
    if site == 'SPEED_TIE' and ctx == 'field:Residual':
        if all(g.startswith('H:') and g.endswith(':end') for g in group):
            return 'residual tie of duration counters'
        if all(g.startswith('H:') and g.endswith(':cb') for g in group):
            return None  # callbacks (burn, Grassy Terrain): the engine draws
        raise SystemExit('trace_to_c: residual tie with callbacks: %s' % group)
    if site == 'SPEED_TIE' and ctx != 'queue':
        raise SystemExit('trace_to_c: unhandled tie context %s' % ctx)
    if site == 'INSERT_TIE':
        # Ties are among entry actions of one speed; runSwitch takes every
        # entry queued right behind it, so their queue order changes nothing
        # as long as the entries stand together.
        runs = [i for i, g in enumerate(group) if g.startswith('A:runSwitch:')]
        if runs and runs == list(range(runs[0], runs[0] + len(runs))):
            return 'queue order of entries that run together'
        raise SystemExit('trace_to_c: insert tie in %s' % group)
    if site == 'RANDOM_TARGET' and ctx in ('action-speed', 'resolve'):
        return 'target computed for priority'
    if site == 'RANDOM_TARGET' and ctx == 'execute:allAdjacentFoes':
        return 'main target of a spread move'
    if site == 'UNKNOWN':
        raise SystemExit('trace_to_c: unclassified draw')
    return None


def tape_entry(d):
    site = SITES[d['site']]
    lo, hi, value = d['lo'], d['hi'], d['value']
    if d['site'] == 'SPEED_TIE':
        start = d['start']
        lo, hi, value = lo - start, hi - start, value - start
    return (site, lo, hi, value)


def convert_choice(text, side, state, roster_of):
    """A Showdown choice string -> ('team', picks) or ('slots', [cmd, cmd])."""
    if text.startswith('team '):
        return ('team', [int(c) - 1 for c in text[len('team '):]])
    cmds = []
    actives = state['sides'][side]['active']
    for slot, part in enumerate(text.split(', ')):
        words = part.split(' ')
        if words[0] == 'move':
            mon = state['sides'][side]['pokemon'][actives[slot]]
            n = int(words[1]) - 1
            mega = 1 if words[-1] == 'mega' else 0
            if mega:
                words = words[:-1]
            if all(pp == 0 for pp in mon['pp']):
                cmds.append((1, 4, 0xFF, mega, 0))  # Struggle
                continue
            target = 0xFF
            if len(words) > 2:
                loc = int(words[2])
                target = (1 - side) * 2 + loc - 1 if loc > 0 else side * 2 + (-loc) - 1
            cmds.append((1, n, target, mega, 0))
        elif words[0] == 'switch':
            # "switch N" names position N of side.pokemon, which the
            # reference reorders on every switch.
            mon = state['sides'][side]['pokemon'][int(words[1]) - 1]
            cmds.append((2, 0, 0, 0, roster_of[side][mon['species']]))
        elif words[0] == 'pass':
            # In a replacement request the reference wants "pass" for a slot
            # that is not asked to switch; DuoForge does not request that slot.
            mon = state['sides'][side]['pokemon'][actives[slot]]
            asked = state['sides'][side]['request'] != 'switch' or mon['fainted']
            cmds.append((3, 0, 0, 0, 0) if asked else (0, 0, 0, 0, 0))
        else:
            raise SystemExit('trace_to_c: choice %r is not supported' % part)
    return ('slots', cmds)


BOUNDARY = {'teampreview': 1, 'move': 2, 'switch': 3}
STATUS = {'': 0, 'brn': 1, 'frz': 2, 'par': 3, 'slp': 4, 'fnt': 0}
WEATHER = {'': 0, 'raindance': 1, 'sunnyday': 2}
TERRAIN = {'': 0, 'grassyterrain': 1}
RESULT = {'p1': 1, 'p2': 2, '': 3}


def boundary_of(state):
    """The DuoForge boundary after a step: TERMINAL, else the request kind."""
    if state['ended']:
        return 5
    kinds = set(s['request'] for s in state['sides']) - {''}
    if len(kinds) != 1:
        raise SystemExit('trace_to_c: mixed requests %s' % sorted(kinds))
    return BOUNDARY[kinds.pop()]


def convert(root, name, tables, out, all_tape):
    spec = json.load(io.open(os.path.join(root, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8'))
    trace = json.load(io.open(os.path.join(root, 'tests', 'reference', 'traces', name + '.json'), encoding='utf-8'))
    teams = [parse_team(spec['teams'][s], tables) for s in range(2)]
    w = out.append
    w('/* %s: %s */' % (name, spec['purpose']))
    w('static const df_conf_member conf_%s_members[2][6] = {' % name)
    for s in range(2):
        rows = []
        for mon in teams[s]:
            mv = mon['moves'] + [0] * (4 - len(mon['moves']))
            rows.append('{%du, %du, %du, {%s}, %du, %du, %du, {%s}}' % (
                mon['species'], mon['gender'], mon['nature'], ', '.join('%du' % x for x in mon['sp']),
                mon['ability'], mon['item'], len(mon['moves']), ', '.join('%du' % x for x in mv)))
        w('    {%s},' % ', '.join(rows))
    w('};')
    picks = [None, None]
    state = trace['start']['state']
    # Species are unique per team (species clause): the start state lists the
    # whole roster in order, so a species names its roster index.
    roster_of = []
    for s in range(2):
        names = [p['species'] for p in state['sides'][s]['pokemon']]
        if len(names) != len(teams[s]) or len(set(names)) != len(names):
            raise SystemExit('trace_to_c: %s side %d roster is not unique' % (name, s))
        roster_of.append({n: i for i, n in enumerate(names)})
    steps = []
    dropped_total = 0
    for step in trace['steps']:
        kinds = {}
        for side, sid in enumerate(('p1', 'p2')):
            if sid in step['input']:
                kinds[side] = convert_choice(step['input'][sid], side, state, roster_of)
        tape_off = len(all_tape)
        dropped = 0
        for d in step['draws']:
            if drop_reason(d) is None:
                all_tape.append(tape_entry(d))
            else:
                dropped += 1
        dropped_total += dropped
        team = all(k[0] == 'team' for k in kinds.values()) and len(kinds) == 2
        if team:
            picks = [kinds[0][1], kinds[1][1]]
        new_state = step['state']
        mons = []
        for s in range(2):
            row = []
            by_roster = {}
            for p in new_state['sides'][s]['pokemon']:
                by_roster[roster_of[s][p['species']]] = p
            for roster in range(6):
                p = by_roster.get(roster)
                if p is None:
                    row.append('{0u, 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u, 0u, 0u, 0u}')
                    continue
                pp = p['pp'] + [0] * (4 - len(p['pp']))
                stall = 1 if 'stall' in p['volatiles'] else 0
                # A fainted Pokemon's status is not compared (DuoForge drops it).
                status, counter = (0, 0) if p['fainted'] else (STATUS[p['status']], p['status_time'])
                if status not in (2, 4):
                    counter = 0
                row.append('{1u, %du, {%s}, {%s}, %du, %du, %du, %du, %du}' % (
                    p['hp'], ', '.join('%du' % x for x in pp), ', '.join('%du' % (x + 6) for x in p['boosts']),
                    stall, 1 if p['fainted'] else 0, status, counter, p['confusion']))
            mons.append(row)
        cmds = []
        for s in range(2):
            if s in kinds and kinds[s][0] == 'slots':
                c = kinds[s][1] + [(0, 0, 0, 0, 0)] * (2 - len(kinds[s][1]))
            else:
                c = [(0, 0, 0, 0, 0)] * 2
            cmds.append('{%s}' % ', '.join('{%du, %du, %du, %du, %du}' % x for x in c))
        pk = []
        for s in range(2):
            row = (kinds[s][1] if team else []) + [0] * (6 - (len(kinds[s][1]) if team else 0))
            pk.append('{%s}' % ', '.join('%du' % x for x in row))
        occ = []
        for s in range(2):
            sd = new_state['sides'][s]
            row = [roster_of[s][sd['pokemon'][i]['species']] if i >= 0 else 0xFF for i in sd['active']]
            occ.append('{%s}' % ', '.join('%du' % x for x in row))
        # The positions that received a Pokemon, in the reference's order
        # (each switch is logged twice, for the two audiences).
        entries = []
        for line in step['log']:
            if line.startswith('|switch|'):
                who = line.split('|')[2].split(':')[0]
                flat = (int(who[1]) - 1) * 2 + (ord(who[2]) - ord('a'))
                if flat not in entries:
                    entries.append(flat)
        ent = entries + [0xFF] * (4 - len(entries))
        weather = WEATHER[new_state['weather']]
        terrain = TERRAIN[new_state['terrain']]
        field = (weather, new_state['weather_turns'] if weather else 0, terrain,
                 new_state['terrain_turns'] if terrain else 0)
        boundary = boundary_of(new_state)
        result = RESULT[new_state['winner']] if boundary == 5 else 0
        steps.append('    {%du, %du, %du, %du, %du, %du, %du, %du, {%s}, {%s}, {%s}, {%s}, {%s}, {{%s}, {%s}}},'
                     '  /* %d draws dropped */' % (
                         1 if team else 0, 1 if 0 in kinds else 0, 1 if 1 in kinds else 0, tape_off,
                         len(all_tape) - tape_off, new_state['turn'], boundary, result, ', '.join(pk),
                         ', '.join(cmds), ', '.join(occ), ', '.join('%du' % x for x in ent),
                         ', '.join('%du' % x for x in field), ', '.join(mons[0]), ', '.join(mons[1]), dropped))
        state = new_state
    w('static const df_conf_step conf_%s_steps[] = {' % name)
    out.extend(steps)
    w('};')
    return '    {"%s", %du, conf_%s_members, conf_%s_steps, sizeof conf_%s_steps / sizeof conf_%s_steps[0], %du},' % (
        name, len(teams[0]), name, name, name, name, dropped_total)


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--check'):
        sys.stderr.write('usage: trace_to_c.py <repo root> [--check]\n')
        return 2
    root = sys.argv[1]
    header = io.open(os.path.join(root, 'src', 'data', 'closure_tables.h'), encoding='ascii').read()
    tables = {k: ids(header, k) for k in ('FORME', 'MOVE', 'ITEM', 'ABILITY', 'NATURE')}
    source = io.open(os.path.join(root, 'src', 'data', 'closure_tables.c'), encoding='ascii').read()
    a = source.index('dfi_closure_formes[DFI_FORME_COUNT] = {')
    rules = re.findall(r'\{\d+u, \d+u, \{\d+u, \d+u\}, \{[^}]*\}, \d+u, (\d+)u,', source[a:])
    tables['GENDER_RULE'] = [int(x) for x in rules]
    names = sorted(f[:-5] for f in os.listdir(os.path.join(root, 'tests', 'reference', 'traces')) if f.endswith('.json'))
    out = ['/*', ' * GENERATED by tools/reference/trace_to_c.py from tests/reference/specs and',
           ' * tests/reference/traces (pinned Showdown b2cb775b0616115b775534eaeff50300e1fc81fc).',
           ' * Do not edit by hand. Draw drop rules: tools/reference/trace_to_c.py.', ' */',
           '#ifndef DUOFORGE_TESTS_REFERENCE_CONFORMANCE_H', '#define DUOFORGE_TESTS_REFERENCE_CONFORMANCE_H',
           '#include <stdint.h>', '', '#include "rng/draw.h"', '',
           '/* species, gender, nature, Stat Points, ability + 1 (0 none), item + 1 (0 none), moves */',
           'typedef struct df_conf_member {', '    uint32_t species, gender, nature, sp[6], ability, item, move_count, moves[4];',
           '} df_conf_member;', '/* kind, move_slot, target, mega, reserve */',
           'typedef struct df_conf_cmd {', '    uint8_t kind, move_slot, target, mega, reserve;', '} df_conf_cmd;',
           '/* present, hp, pp, stages (biased by 6), stall counter present, fainted,',
           ' * status (DFI_STATUS_*), its counter (sleep, freeze), confusion turns */',
           'typedef struct df_conf_mon {', '    uint32_t present, hp;', '    uint8_t pp[4];', '    uint8_t stages[7];',
           '    uint8_t stall, fainted, status, status_counter, confusion;', '} df_conf_mon;',
           '/* team step, side 0 / side 1 answered, tape slice, the turn, boundary and',
           ' * result afterwards, the picks of a team step, slot commands, the occupants',
           ' * of the positions afterwards (roster index, 0xFF empty), the positions',
           ' * (side * 2 + slot) that received a Pokemon in the reference\'s order (0xFF',
           ' * pads), weather, its turns, terrain, its turns, the expected members by',
           ' * roster index */',
           'typedef struct df_conf_step {',
           '    uint32_t team, answered0, answered1, tape_off, tape_len, turn, boundary, result;',
           '    uint8_t picks[2][6];', '    df_conf_cmd cmds[2][2];', '    uint8_t occupants[2][2];', '    uint8_t entries[4];', '    uint8_t field[4];',
           '    df_conf_mon mons[2][6];', '} df_conf_step;',
           'typedef struct df_conf_battle {', '    const char *name;', '    uint32_t member_count;',
           '    const df_conf_member (*members)[6];', '    const df_conf_step *steps;', '    uint32_t step_count;',
           '    uint32_t dropped;', '} df_conf_battle;', '']
    all_tape = []
    entries = []
    body = []
    for n in names:
        entries.append(convert(root, n, tables, body, all_tape))
    out.extend(body)
    out.append('')
    out.append('/* Every kept draw of every battle: site, lo, hi, value. */')
    out.append('static const dfi_tape_entry conf_tape[] = {')
    for e in all_tape:
        out.append('    {%du, %du, %du, %du},' % e)
    if not all_tape:
        out.append('    {0u, 0u, 0u, 0u},')
    out.append('};')
    out.append('')
    out.append('static const df_conf_battle conf_battles[] = {')
    out.extend(entries)
    out.append('};')
    out.append('')
    out.append('#endif')
    text = '\n'.join(out) + '\n'
    target = os.path.join(root, 'tests', 'reference', 'conformance.h')
    if len(sys.argv) == 3:
        have = io.open(target, encoding='ascii').read().replace('\r\n', '\n') if os.path.exists(target) else ''
        if have != text:
            sys.stderr.write('trace_to_c: %s differs from the traces\n' % target)
            return 1
        print('trace_to_c: %s matches the traces' % target)
        return 0
    io.open(target, 'w', encoding='ascii', newline='\n').write(text)
    print('trace_to_c: wrote %s (%d battles, %d tape entries)' % (target, len(names), len(all_tape)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
