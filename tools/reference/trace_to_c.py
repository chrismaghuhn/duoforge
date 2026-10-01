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
  SPEED_TIE each:*  only if at most one tied Pokemon has a handler for
                    that event (Sitrus Berry, Grassy Seed): with two, the
                    tie orders their lines and the engine draws
  SPEED_TIE switch-order
                    only if no tied Pokemon has a SwitchIn handler
  SPEED_TIE field:Residual
                    only if every tied handler only counts down a duration;
                    both sides' same side condition running out in this
                    residual is kept instead: the tie orders their two end
                    lines, and the entry states which side's line comes
                    first (the engine's draw; see side_end_tie)
  SPEED_TIE event:ModifyDamage
                    only between screens, of which at most one applies, or
                    between the attacker's Life Orb and the target's Chople
                    Berry, whose modifiers commute
  INSERT_TIE        only if the runSwitch actions in the tied group stand
                    together in the queue: runSwitch takes every entry
                    queued right behind it, so their queue order changes
                    nothing (the entries then run in Speed order, with the
                    engine's own draws for entry ties)
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
            # The reference fixes an illegal gender silently; DuoForge rejects it.
            if rule == 3 or (rule in (1, 2) and mon['gender'] != rule):
                raise SystemExit('trace_to_c: %s cannot be (%s)' % (species_name, gender_tag))
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


COND_INDEX = {'tailwind': 0, 'reflect': 1, 'lightscreen': 2}  # the order of a side's 'conditions'


def side_end_tie(d, state):
    """A residual tie of both sides' same side condition, both at 1 turn in
    `state` (the state before the step): both end now, and the shuffle of
    the two orders their end lines. The engine draws which side's line
    comes first (decision 0007 section 11); the reference's pre-shuffle
    order of the pair depends on its handler list (the insertion order of
    each side's conditions), which the state does not hold, so the entry
    states the outcome: (SPEED_TIE, 0, 2, the side whose line comes first).
    None for any other draw."""
    if d['site'] != 'SPEED_TIE' or d.get('context') != 'field:Residual':
        return None
    group = d['group']
    parts = [g.split(':') for g in group]
    if len(group) != 2 or any(len(x) != 4 or x[0] != 'H' or x[3] != 'end' for x in parts):
        return None
    if parts[0][1] != parts[1][1] or parts[0][1] not in COND_INDEX or {parts[0][2], parts[1][2]} != {'p1', 'p2'}:
        return None
    if any(state['sides'][int(x[2][1]) - 1]['conditions'][COND_INDEX[x[1]]] != 1 for x in parts):
        return None
    if d['hi'] - d['lo'] != 2 or d['lo'] != d['start']:
        raise SystemExit('trace_to_c: unexpected side-end shuffle %s' % d)
    first = parts[0] if d['value'] == d['start'] else parts[1]  # random(start, start + 2): start keeps the order
    return (SITES['SPEED_TIE'], 0, 2, int(first[2][1]) - 1)


def drop_reason(d, state):
    """Why draw `d` is not a tape entry, or None; `state` is the state before the step."""
    site, ctx, group = d['site'], d.get('context', ''), d.get('group')
    if site == 'TEAM_ORDER':
        return 'team-preview order'
    if site == 'SPEED_TIE' and ctx.startswith('each:'):
        # P:<slot>:<handlers>:<effect ids>. Sitrus Berry (Update) and Grassy
        # Seed (TerrainChange) act only on their holder, so the order of the
        # Pokemon changes nothing.
        ids = [x for g in group for x in g.split(':', 3)[3].split('+') if x]
        if not all(x in ('sitrusberry', 'grassyseed') for x in ids):
            raise SystemExit('trace_to_c: %s tie between Pokemon with handlers: %s' % (ctx, group))
        if sum(1 for g in group if g.split(':', 3)[3]) <= 1:
            return 'each-event tie with at most one holder'
        return None  # the engine draws: the order of the holders' lines
    if site == 'SPEED_TIE' and ctx == 'switch-order':
        # P:<slot>:<SwitchIn handlers>:<S entering | - not>; the order decides
        # something only between two entering Pokemon with handlers.
        bearers = sum(1 for g in group if g.split(':')[2] != '0' and g.split(':')[3] == 'S')
        if bearers <= 1:
            return 'switch-in order with at most one entry effect'
        return None  # the engine draws
    if site == 'SPEED_TIE' and ctx == 'field:Residual':
        if all(g.startswith('H:') and g.endswith(':end') for g in group):
            if side_end_tie(d, state) is not None:
                raise SystemExit('trace_to_c: ending side conditions reach drop_reason: %s' % group)
            return 'residual tie of duration counters'
        if all(g.startswith('H:') and g.endswith(':cb') for g in group):
            return None  # callbacks (burn, Grassy Terrain): the engine draws
        raise SystemExit('trace_to_c: residual tie with callbacks: %s' % group)
    if site == 'SPEED_TIE' and ctx == 'event:ModifyDamage':
        # Reflect and Light Screen of both sides: each checks the target's
        # side and the move's category, so at most one applies to a hit.
        if all(g.startswith(('H:reflect:', 'H:lightscreen:')) for g in group):
            return 'screen handlers of which at most one applies'
        # The attacker's Life Orb and the target's Chople Berry (Team C) at
        # one speed: every order of the ModifyDamage modifiers chains to the
        # same value (the engine checks it at compile time, turn.c).
        if sorted(g.split(':')[1] for g in group) == ['chopleberry', 'lifeorb']:
            return 'Life Orb and Chople Berry, whose modifiers commute'
        raise SystemExit('trace_to_c: ModifyDamage tie with %s' % group)
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


def name_of(p):
    """The roster name of a Pokemon: its set's species (a Mega changes the species)."""
    return p.get('set_species', p['species'])


# Set species whose protocol name is another (the base species), decision 0009.
BASE_SPECIES_NAME = {'Indeedee-F': 'Indeedee'}


def abs_target(side, loc):
    """A Showdown target location (foes positive, own side negative) as a
    DuoForge position (side * 2 + slot)."""
    return (1 - side) * 2 + loc - 1 if loc > 0 else side * 2 + (-loc) - 1


def convert_choice(text, side, state, roster_of, mid_turn=False):
    """A Showdown choice string -> ('team', picks) or ('slots', [cmd, cmd]).
    mid_turn: the request was made during the turn (a pivot), not at its end."""
    if text.startswith('team '):
        return ('team', [int(c) - 1 for c in text[len('team '):]])
    cmds = []
    actives = state['sides'][side]['active']
    for slot, part in enumerate(text.split(', ')):
        words = part.split(' ')
        if words[0] == 'move':
            mon = state['sides'][side]['pokemon'][actives[slot]]
            if mon.get('locked'):
                # A locked move: its slot and the stored target, whatever was typed.
                cmds.append((1, mon['locked'][0], abs_target(side, mon['locked'][1]), 0, 0))
                continue
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
            cmds.append((2, 0, 0, 0, roster_of[side][name_of(mon)]))
        elif words[0] == 'pass':
            # In a switch request the reference wants "pass" for a slot that
            # is not asked to switch; DuoForge does not request that slot. A
            # slot is asked exactly when its switch flag is set: a fainted
            # Pokemon only at the end of the turn (checkFainted sets the flag,
            # so a pivot during the turn does not ask it), and a standing one
            # that keeps its flag while it passes (Flip Turn and Emergency
            # Exit on one side with one reserve, Team C). mid_turn agrees with
            # the flag for fainted Pokemon and is kept for the callers.
            mon = state['sides'][side]['pokemon'][actives[slot]]
            del mid_turn
            asked = state['sides'][side]['request'] != 'switch' or bool(mon.get('switch_flag'))
            cmds.append((3, 0, 0, 0, 0) if asked else (0, 0, 0, 0, 0))
        else:
            raise SystemExit('trace_to_c: choice %r is not supported' % part)
    return ('slots', cmds)


BOUNDARY = {'teampreview': 1, 'move': 2, 'switch': 3}
STATUS = {'': 0, 'brn': 1, 'frz': 2, 'par': 3, 'slp': 4, 'fnt': 0}
WEATHER = {'': 0, 'raindance': 1, 'sunnyday': 2}
TERRAIN = {'': 0, 'grassyterrain': 1}
RESULT = {'p1': 1, 'p2': 2, '': 3}


HP_FLAGS = {'': 0, 'r': 1, 'y': 2, 'g': 3}  # DUOFORGE_HP_FLAG_*


def public_lines(log, roster_of, shown):
    """Updates shown[side][roster] = (percent, flag) from the protocol lines
    that show HP to everyone. A split line comes as '|split|pN', the copy for
    pN (exact HP) and then the public copy: only the public copy counts. A
    public HP that is not a Champions percent display stops the conversion."""
    skip = False
    for line in log:
        if skip:
            skip = False
            continue
        if line.startswith('|split|'):
            skip = True
            continue
        parts = line.split('|')
        if len(parts) >= 5 and parts[1] in ('switch', 'drag'):
            who, hp = parts[2], parts[4]
        elif len(parts) >= 4 and parts[1] in ('-damage', '-heal', '-sethp'):
            who, hp = parts[2], parts[3]
        else:
            continue
        side = int(who[1]) - 1
        roster = roster_of[side].get(who.split(': ', 1)[1])
        if roster is None:
            raise SystemExit('trace_to_c: unknown Pokemon in %r' % line)
        token = hp.split(' ')[0]
        if token == '0':
            shown[side][roster] = (0, 0)
            continue
        m = re.match(r'^(\d+)/100([gry]?)$', token)
        if not m:
            raise SystemExit('trace_to_c: not a public HP display in %r' % line)
        shown[side][roster] = (int(m.group(1)), HP_FLAGS[m.group(2)])



# ---------------------------------------------------------------- events
# Decision 0007 section 6: one event per protocol line the game shows a
# player, with the HP that player's screen shows. Values of
# include/duoforge/duoforge.h.
EV = {name: i + 1 for i, name in enumerate(
    ['TURN', 'SWITCH', 'MOVE', 'DAMAGE', 'HEAL', 'FAINT', 'CANT', 'MISS', 'CRIT', 'SUPER_EFFECTIVE', 'RESISTED',
     'IMMUNE', 'FAIL', 'PROTECT', 'BLOCKED', 'BOOST', 'UNBOOST', 'STATUS', 'CURE_STATUS', 'CONFUSION_START',
     'CONFUSION_END', 'CONFUSED', 'FLASH_FIRE', 'WEATHER', 'FIELD_START', 'FIELD_END', 'SIDE_START', 'SIDE_END',
     'ITEM_END', 'FORME', 'MEGA', 'PREPARE', 'ANIMATION', 'ABILITY', 'ACTIVATE', 'UPKEEP', 'RESULT'])}
CAUSE = {'NONE': 0, 'MOVE': 1, 'ITEM': 2, 'ABILITY': 3, 'RECOIL': 4, 'DRAIN': 5, 'BURN': 6, 'CONFUSION': 7,
         'TERRAIN': 8, 'PARALYSIS': 9, 'SLEEP': 10, 'FREEZE': 11, 'FLINCH': 12, 'NO_PP': 13}
FLAG = {'STILL': 1, 'LOCKED': 2, 'SPREAD': 4, 'UPKEEP': 8, 'EATEN': 16, 'MESSAGE': 32, 'MISS': 64, 'NOTARGET': 128}
AILMENT = {'brn': 1, 'frz': 2, 'par': 3, 'slp': 4}
EV_STATS = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion']
NOPOS = 0xFF
HP_EXACT, HP_PERCENT = 1, 2
HP_FLAGS_EV = {'': 0, 'r': 1, 'y': 2, 'g': 3}
# Lines that are not events: setup, layout, hints, and what the game does
# not show ([silent]).
NOT_EVENTS = {'', 'split', 't:', 'gametype', 'player', 'teamsize', 'gen', 'tier', 'rule', 'clearpoke', 'poke',
              'teampreview', 'start', 'uhtml', 'uhtmlchange', '-hint', 'j', 'l', 'c', 'raw', 'inactive'}


def ev_pos(text):
    """'p2a: Raichu' -> 2; 'p1: Charizard' (a side) -> None."""
    if len(text) >= 3 and text[0] == 'p' and text[1] in '12' and text[2] in 'ab':
        return (int(text[1]) - 1) * 2 + (ord(text[2]) - ord('a'))
    return None


def ev_tuple(kind, position=NOPOS, other=NOPOS, cause=0, ident=0, ident2=0, hp=0, hp_max=0, hp_kind=0,
             hp_flag=0, status=0, detail=0, amount=0, flags=0):
    return (kind, position, other, cause, ident, ident2, hp, hp_max, hp_kind, hp_flag, status, detail, amount, flags)


def ev_cause(attrs, tables):
    """[from] and [of] attributes -> (cause, id2, other)."""
    cause, id2, other = 0, 0, NOPOS
    for a in attrs:
        if a.startswith('[from] '):
            what = a[len('[from] '):]
            if what.startswith('item: '):
                cause, id2 = CAUSE['ITEM'], tables['ITEM'][key(what[6:])] + 1
            elif what.startswith('ability: '):
                cause, id2 = CAUSE['ABILITY'], tables['ABILITY'][key(what[9:])] + 1
            elif what.startswith('move: '):
                cause, id2 = CAUSE['MOVE'], tables['MOVE'][key(what[6:])]
            elif what.lower() == 'recoil':
                cause = CAUSE['RECOIL']
            elif what == 'drain':
                cause = CAUSE['DRAIN']
            elif what == 'brn':
                cause = CAUSE['BURN']
            elif what == 'confusion':
                cause = CAUSE['CONFUSION']
            elif what == 'Grassy Terrain':
                cause = CAUSE['TERRAIN']
            elif what in ('Parting Shot', 'Flip Turn'):
                cause, id2 = CAUSE['MOVE'], tables['MOVE'][key(what)]
            elif what == 'lockedmove':
                pass  # a MOVE flag
            else:
                raise SystemExit('trace_to_c: unknown [from] %r' % a)
        elif a.startswith('[of] '):
            other = ev_pos(a[5:])
    return cause, id2, other


def ev_hp(text, side, viewer, maxhp):
    """An HP field as `viewer` sees it -> (hp, hp_max, kind, flag, status)."""
    tokens = text.split(' ')
    status = AILMENT.get(tokens[1], 0) if len(tokens) > 1 else 0
    if tokens[0] == '0':
        return (0, maxhp if side == viewer else 100, HP_EXACT if side == viewer else HP_PERCENT, 0, 0)
    m = re.match(r'^(\d+)/(\d+)([gry]?)$', tokens[0])
    if not m:
        raise SystemExit('trace_to_c: bad HP %r' % text)
    if side == viewer:
        return (int(m.group(1)), int(m.group(2)), HP_EXACT, 0, status)
    if m.group(2) != '100':
        raise SystemExit('trace_to_c: the opponent sees exact HP in %r' % text)
    return (int(m.group(1)), 100, HP_PERCENT, HP_FLAGS_EV[m.group(3)], status)


def step_events(log, viewer, roster_of, maxhp, tables):
    """The events `viewer` sees in one step, in protocol order."""
    out = []
    skip = set()
    for i, line in enumerate(log):
        if i in skip:
            continue
        if line.startswith('|split|'):
            owner = int(line[len('|split|p'):]) - 1
            skip.add(i + 2 if owner == viewer else i + 1)  # the owner keeps its exact copy, others the public one
            continue
        out_line = line
        parts = out_line.split('|')
        kind = parts[1] if len(parts) > 1 else ''
        if kind in NOT_EVENTS or kind.startswith('t:'):
            continue
        attrs = [x for x in parts[2:] if x.startswith('[')]
        if '[silent]' in attrs:
            continue
        args = [x for x in parts[2:] if not x.startswith('[')]
        e = None
        if kind == 'turn':
            e = ev_tuple(EV['TURN'], ident=int(args[0]))
        elif kind == 'upkeep':
            e = ev_tuple(EV['UPKEEP'])
        elif kind in ('win', 'tie'):
            e = ev_tuple(EV['RESULT'], detail=3 if kind == 'tie' else int(args[0][1:]))
        elif kind == 'switch':
            pos = ev_pos(args[0])
            side = pos // 2
            name = args[0].split(': ', 1)[1]
            cause, id2, _ = ev_cause(attrs, tables)
            hp = ev_hp(args[2], side, viewer, maxhp[side][name])
            e = ev_tuple(EV['SWITCH'], pos, NOPOS, cause, roster_of[side][name], id2, *hp)
        elif kind == 'move':
            pos = ev_pos(args[0])
            target = ev_pos(parts[4]) if len(parts) > 4 else None
            flags = 0
            amount = 0
            for a in parts[5:]:
                if a == '[still]':
                    flags |= FLAG['STILL']
                elif a == '[from] lockedmove':
                    flags |= FLAG['LOCKED']
                elif a == '[miss]':
                    flags |= FLAG['MISS']
                elif a == '[notarget]':
                    flags |= FLAG['NOTARGET']
                elif a.startswith('[spread]'):
                    flags |= FLAG['SPREAD']
                    for slot in a[len('[spread]'):].strip().split(','):
                        if slot:
                            amount |= 1 << ev_pos(slot)
                elif a:
                    raise SystemExit('trace_to_c: unknown move attribute %r' % a)
            if flags & (FLAG['SPREAD'] | FLAG['NOTARGET'] | FLAG['STILL']) or target is None:
                target = NOPOS
            e = ev_tuple(EV['MOVE'], pos, target, 0, tables['MOVE'][key(args[1])], amount=amount, flags=flags)
        elif kind in ('-damage', '-heal'):
            pos = ev_pos(args[0])
            side = pos // 2
            cause, id2, other = ev_cause(attrs, tables)
            hp = ev_hp(args[1], side, viewer, maxhp[side][args[0].split(': ', 1)[1]])
            e = ev_tuple(EV['DAMAGE' if kind == '-damage' else 'HEAL'], pos, other, cause, 0, id2, *hp)
        elif kind == 'faint':
            e = ev_tuple(EV['FAINT'], ev_pos(args[0]))
        elif kind == 'cant':
            pos = ev_pos(args[0])
            reason = args[1]
            if reason.startswith('ability: '):
                _, _, other = ev_cause(attrs, tables)
                e = ev_tuple(EV['CANT'], pos, other, CAUSE['ABILITY'], tables['MOVE'][key(args[2])],
                             tables['ABILITY'][key(reason[9:])] + 1)
            else:
                cause = {'par': 'PARALYSIS', 'slp': 'SLEEP', 'frz': 'FREEZE', 'flinch': 'FLINCH', 'nopp': 'NO_PP'}
                e = ev_tuple(EV['CANT'], pos, NOPOS, CAUSE[cause[reason]])
        elif kind == '-miss':
            e = ev_tuple(EV['MISS'], ev_pos(args[0]), ev_pos(args[1]))
        elif kind in ('-crit', '-supereffective', '-resisted'):
            # The Champions -supereffective and -resisted carry min(|typeMod|, 2).
            e = ev_tuple(EV[{'-crit': 'CRIT', '-supereffective': 'SUPER_EFFECTIVE', '-resisted': 'RESISTED'}[kind]],
                         ev_pos(args[0]), amount=int(args[1]) if len(args) > 1 else 0)
        elif kind == '-immune':
            cause, id2, _ = ev_cause(attrs, tables)
            e = ev_tuple(EV['IMMUNE'], ev_pos(args[0]), NOPOS, cause, 0, id2)
        elif kind == '-fail':
            e = ev_tuple(EV['FAIL'], ev_pos(args[0]), detail=AILMENT[args[1]] if len(args) > 1 else 0)
        elif kind == '-singleturn':
            e = ev_tuple(EV['PROTECT'], ev_pos(args[0]))
        elif kind == '-activate':
            pos = ev_pos(args[0])
            what = args[1]
            if what == 'move: Protect':
                e = ev_tuple(EV['BLOCKED'], pos)
            elif what == 'confusion':
                e = ev_tuple(EV['CONFUSED'], pos)
            elif what.startswith('ability: '):
                e = ev_tuple(EV['ACTIVATE'], pos, NOPOS, CAUSE['ABILITY'], 0, tables['ABILITY'][key(what[9:])] + 1)
            elif what.startswith('move: '):
                e = ev_tuple(EV['ACTIVATE'], pos, NOPOS, CAUSE['MOVE'], 0, tables['MOVE'][key(what[6:])])
            else:
                raise SystemExit('trace_to_c: unknown -activate %r' % line)
        elif kind in ('-boost', '-unboost'):
            cause, id2, other = ev_cause(attrs, tables)
            e = ev_tuple(EV['BOOST' if kind == '-boost' else 'UNBOOST'], ev_pos(args[0]), other, cause, 0, id2,
                         detail=EV_STATS.index(args[1]), amount=int(args[2]))
        elif kind == '-status':
            cause, id2, other = ev_cause(attrs, tables)
            e = ev_tuple(EV['STATUS'], ev_pos(args[0]), other, cause, 0, id2, detail=AILMENT[args[1]])
        elif kind == '-curestatus':
            # [from] move: a defrost move thaws its frozen user (Team C, Flare Blitz).
            cause, id2, other = ev_cause(attrs, tables)
            e = ev_tuple(EV['CURE_STATUS'], ev_pos(args[0]), other, cause, 0, id2, detail=AILMENT[args[1]],
                         flags=FLAG['MESSAGE'] if '[msg]' in attrs else 0)
        elif kind in ('-start', '-end'):
            what = args[1]
            if what == 'confusion':
                e = ev_tuple(EV['CONFUSION_START' if kind == '-start' else 'CONFUSION_END'], ev_pos(args[0]))
            elif what == 'ability: Flash Fire' and kind == '-start':
                e = ev_tuple(EV['FLASH_FIRE'], ev_pos(args[0]))
            else:
                raise SystemExit('trace_to_c: unknown %s %r' % (kind, line))
        elif kind == '-weather':
            cause, id2, other = ev_cause(attrs, tables)
            weather = {'RainDance': 1, 'SunnyDay': 2, 'none': 0}[args[0]]
            e = ev_tuple(EV['WEATHER'], NOPOS, other, cause, 0, id2, detail=weather,
                         flags=FLAG['UPKEEP'] if '[upkeep]' in attrs else 0)
        elif kind in ('-fieldstart', '-fieldend'):
            cause, id2, other = ev_cause(attrs, tables)
            field = {'move: Grassy Terrain': 1, 'move: Trick Room': 2}[args[0]]
            e = ev_tuple(EV['FIELD_START' if kind == '-fieldstart' else 'FIELD_END'], NOPOS, other, cause, 0, id2,
                         detail=field)
        elif kind in ('-sidestart', '-sideend'):
            side = int(args[0][1]) - 1
            cond = {'move: Tailwind': 1, 'Reflect': 2, 'move: Reflect': 2, 'move: Light Screen': 3}[args[1]]
            e = ev_tuple(EV['SIDE_START' if kind == '-sidestart' else 'SIDE_END'], detail=side, amount=cond)
        elif kind == '-enditem':
            # [weaken]: the second line of a resist berry (Team C, Chople Berry), detail 1.
            e = ev_tuple(EV['ITEM_END'], ev_pos(args[0]), NOPOS, 0, 0, tables['ITEM'][key(args[1])] + 1,
                         detail=1 if '[weaken]' in attrs else 0, flags=FLAG['EATEN'] if '[eat]' in attrs else 0)
        elif kind == 'detailschange':
            e = ev_tuple(EV['FORME'], ev_pos(args[0]), ident=tables['FORME'][key(args[1].split(',')[0])])
        elif kind == '-mega':
            e = ev_tuple(EV['MEGA'], ev_pos(args[0]), NOPOS, 0, 0, tables['ITEM'][key(args[2])] + 1)
        elif kind == '-prepare':
            e = ev_tuple(EV['PREPARE'], ev_pos(args[0]), ident=tables['MOVE'][key(args[1])])
        elif kind == '-anim':
            # addMove('-anim') makes it the last move line: later attributes
            # ([miss], [notarget]) amend it.
            flags = 0
            for a in attrs:
                if a == '[miss]':
                    flags |= FLAG['MISS']
                elif a == '[notarget]':
                    flags |= FLAG['NOTARGET']
                else:
                    raise SystemExit('trace_to_c: unknown -anim attribute %r' % a)
            shown = ev_pos(args[2])  # a fainted Pokemon has no slot ("p1: Name")
            e = ev_tuple(EV['ANIMATION'], ev_pos(args[0]), NOPOS if shown is None else shown, 0,
                         tables['MOVE'][key(args[1])], flags=flags)
        elif kind == '-ability':
            e = ev_tuple(EV['ABILITY'], ev_pos(args[0]), NOPOS, 0, 0, tables['ABILITY'][key(args[1])] + 1)
        else:
            raise SystemExit('trace_to_c: unknown protocol line %r' % line)
        out.append(e)
    return out


def boundary_of(state, log):
    """The DuoForge boundary after a step: TERMINAL, else the request kind."""
    if state['ended']:
        return 5
    kinds = set(s['request'] for s in state['sides']) - {''}
    if len(kinds) != 1:
        raise SystemExit('trace_to_c: mixed requests %s' % sorted(kinds))
    kind = kinds.pop()
    if kind == 'switch' and '|upkeep' not in log:
        # Without the residual action ('|upkeep') in this step the queue still
        # holds actions: a PIVOT. That is a mid-turn switch (Parting Shot,
        # Emergency Exit) or, during a REPLACEMENT, a fainted position that
        # passed and is asked again right after the switch, before the
        # newcomer's entry. After the residual action the queue is empty:
        # the request (fainted positions, an Emergency Exit) is a REPLACEMENT.
        return 4
    return BOUNDARY[kind]


def convert(root, name, tables, out, all_tape, all_events):
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
        names = [name_of(p) for p in state['sides'][s]['pokemon']]
        if len(names) != len(teams[s]) or len(set(names)) != len(names):
            raise SystemExit('trace_to_c: %s side %d roster is not unique' % (name, s))
        roster_of.append({n: i for i, n in enumerate(names)})
    maxhp = [{name_of(p): p['maxhp'] for p in state['sides'][s]['pokemon']} for s in range(2)]
    # The protocol calls an unnamed Pokemon by its base species
    # (sim/pokemon.ts:329-330), which differs from the set's species only
    # for these formes; the species clause keeps the alias unique.
    for s in range(2):
        for species, protocol in BASE_SPECIES_NAME.items():
            if species in roster_of[s]:
                roster_of[s][protocol] = roster_of[s][species]
                maxhp[s][protocol] = maxhp[s][species]
    steps = []
    dropped_total = 0
    # What each player has seen of the other side: the last public HP display
    # per roster index (the opponent's knowledge in DuoForge), taken from the
    # public copy of every protocol line that shows HP.
    shown = [{}, {}]
    # A switch request made during the turn: the step that led to it has not
    # reached the end of the turn (no upkeep line).
    mid_turn = False
    for step in trace['steps']:
        public_lines(step['log'], roster_of, shown)
        kinds = {}
        for side, sid in enumerate(('p1', 'p2')):
            if sid in step['input']:
                kinds[side] = convert_choice(step['input'][sid], side, state, roster_of, mid_turn)
        tape_off = len(all_tape)
        dropped = 0
        for d in step['draws']:
            ends = side_end_tie(d, state)
            if ends is not None:
                all_tape.append(ends)
            elif drop_reason(d, state) is None:
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
                by_roster[roster_of[s][name_of(p)]] = p
            for roster in range(6):
                p = by_roster.get(roster)
                if p is None:
                    row.append('{0u, 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, '
                               '0u, 0u, 0u, 0u, 0u}')
                    continue
                pp = p['pp'] + [0] * (4 - len(p['pp']))
                stall = 1 if 'stall' in p['volatiles'] else 0
                # A fainted Pokemon's status is not compared (DuoForge drops it).
                status, counter = (0, 0) if p['fainted'] else (STATUS[p['status']], p['status_time'])
                if status not in (2, 4):
                    counter = 0
                lock = p.get('locked')
                lslot, ltarget = (lock[0], abs_target(s, lock[1])) if lock else (0xFF, 0)
                seen = shown[s].get(roster)
                vols = sum(bit for name, bit in (('protect', 1), ('flashfire', 2), ('twoturnmove', 4))
                           if name in p['volatiles'])
                row.append('{1u, %du, {%s}, {%s}, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du}' % (
                    p['hp'], ', '.join('%du' % x for x in pp), ', '.join('%du' % (x + 6) for x in p['boosts']),
                    stall, 1 if p['fainted'] else 0, status, counter, p['confusion'], lslot, ltarget,
                    p.get('mega', 0), 1 if p['item'] else 0, 1 if seen else 0, seen[0] if seen else 0,
                    seen[1] if seen else 0, vols))
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
            row = [roster_of[s][name_of(sd['pokemon'][i])] if i >= 0 else 0xFF for i in sd['active']]
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
        # The moves the reference's request offers per slot: bit k for move k,
        # 0x10 for Struggle, 0xFF where there is nothing to compare.
        enabled = []
        for s in range(2):
            rows = new_state['sides'][s]['enabled']
            row = []
            for k in range(2):
                sd = new_state['sides'][s]
                ai = sd['active'][k] if k < len(sd['active']) else -1
                lock = sd['pokemon'][ai].get('locked') if ai >= 0 else None
                if lock and k < len(rows) and rows[k]:
                    row.append(1 << lock[0])
                elif k >= len(rows) or not rows[k]:
                    row.append(0xFF)
                elif rows[k] == [2]:
                    row.append(0x10)
                else:
                    row.append(sum(1 << i for i, e in enumerate(rows[k]) if e == 1))
            enabled.append('{%s}' % ', '.join('%du' % x for x in row))
        weather = WEATHER[new_state['weather']]
        terrain = TERRAIN[new_state['terrain']]
        field = (weather, new_state['weather_turns'] if weather else 0, terrain,
                 new_state['terrain_turns'] if terrain else 0, new_state['trick_room']) + tuple(
                     c for sd in new_state['sides'] for c in sd['conditions'])
        boundary = boundary_of(new_state, step['log'])
        result = RESULT[new_state['winner']] if boundary == 5 else 0
        ev_off, ev_len = [], []
        for viewer in range(2):
            evs = step_events(step['log'], viewer, roster_of, maxhp, tables)
            ev_off.append(len(all_events))
            ev_len.append(len(evs))
            all_events.extend(evs)
        steps.append('    {%du, %du, %du, %du, %du, %du, %du, %du, {%s}, {%s}, {%s}, {%s}, {%s}, {%s}, {{%s}, {%s}}, '
                     '{%du, %du}, {%du, %du}},  /* %d draws dropped */' % (
                         1 if team else 0, 1 if 0 in kinds else 0, 1 if 1 in kinds else 0, tape_off,
                         len(all_tape) - tape_off, new_state['turn'], boundary, result, ', '.join(pk),
                         ', '.join(cmds), ', '.join(occ), ', '.join('%du' % x for x in ent),
                         ', '.join('%du' % x for x in field), ', '.join(enabled), ', '.join(mons[0]),
                         ', '.join(mons[1]), ev_off[0], ev_off[1], ev_len[0], ev_len[1], dropped))
        state = new_state
        mid_turn = not any(line.startswith('|upkeep') for line in step['log'])
    w('static const df_conf_step conf_%s_steps[] = {' % name)
    out.extend(steps)
    w('};')
    return '    {"%s", %du, conf_%s_members, conf_%s_steps, sizeof conf_%s_steps / sizeof conf_%s_steps[0], %du},' % (
        name, len(teams[0]), name, name, name, name, dropped_total)


def is_team_c(root, name):
    """A spec with "data": "team_c" records a Team C battle (decision 0009 section 6.1)."""
    spec = json.load(io.open(os.path.join(root, 'tests', 'reference', 'specs', name + '.json'), encoding='utf-8'))
    data = spec.get('data')
    if data not in (None, 'team_c'):
        raise SystemExit('trace_to_c: %s: unknown data %r' % (name, data))
    return data == 'team_c'


def load_tables(root, team_c):
    """Name -> id tables: the closure's, or for Team C the extended tables
    (the closure ids plus Team C's, decision 0009 section 3.2)."""
    header = io.open(os.path.join(root, 'src', 'data', 'closure_tables.h'), encoding='ascii').read()
    source = io.open(os.path.join(root, 'src', 'data', 'closure_tables.c'), encoding='ascii').read()
    start = 'dfi_closure_formes[DFI_FORME_COUNT] = {'
    if team_c:
        header += io.open(os.path.join(root, 'src', 'data', 'extended_tables.h'), encoding='ascii').read()
        source = io.open(os.path.join(root, 'src', 'data', 'extended_tables.c'), encoding='ascii').read()
        start = 'dfi_ext_formes[DFI_EXT_FORME_COUNT] = {'
    tables = {k: ids(header, k) for k in ('FORME', 'MOVE', 'ITEM', 'ABILITY', 'NATURE')}
    a = source.index(start)
    rules = re.findall(r'\{\d+u, \d+u, \{\d+u, \d+u\}, \{[^}]*\}, \d+u, (\d+)u,', source[a:])
    tables['GENDER_RULE'] = [int(x) for x in rules]
    return tables


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--check'):
        sys.stderr.write('usage: trace_to_c.py <repo root> [--check]\n')
        return 2
    root = sys.argv[1]
    check = len(sys.argv) == 3
    names = sorted(f[:-5] for f in os.listdir(os.path.join(root, 'tests', 'reference', 'traces')) if f.endswith('.json'))
    team_c = [n for n in names if is_team_c(root, n)]
    closure = [n for n in names if n not in team_c]
    rc = write_header(root, closure, load_tables(root, False), False, check)
    if team_c:
        rc |= write_header(root, team_c, load_tables(root, True), True, check)
    return rc


def write_header(root, names, tables, team_c, check):
    guard = 'DUOFORGE_TESTS_REFERENCE_CONFORMANCE_TEAM_C_H' if team_c else 'DUOFORGE_TESTS_REFERENCE_CONFORMANCE_H'
    source_line = (' * tests/reference/traces, the Team C battles (decision 0009; pinned Showdown' if team_c else
                   ' * tests/reference/traces (pinned Showdown b2cb775b0616115b775534eaeff50300e1fc81fc).')
    out = ['/*', ' * GENERATED by tools/reference/trace_to_c.py from tests/reference/specs and', source_line]
    if team_c:
        out.append(' * b2cb775b0616115b775534eaeff50300e1fc81fc), read with the extended tables.')
    out += [' * Do not edit by hand. Draw drop rules: tools/reference/trace_to_c.py.', ' */',
            '#ifndef %s' % guard, '#define %s' % guard,
           '#include <stdint.h>', '', '#include <duoforge/duoforge.h>', '', '#include "rng/draw.h"', '',
           '/* species, gender, nature, Stat Points, ability + 1 (0 none), item + 1 (0 none), moves */',
           'typedef struct df_conf_member {', '    uint32_t species, gender, nature, sp[6], ability, item, move_count, moves[4];',
           '} df_conf_member;', '/* kind, move_slot, target, mega, reserve */',
           'typedef struct df_conf_cmd {', '    uint8_t kind, move_slot, target, mega, reserve;', '} df_conf_cmd;',
           '/* present, hp, pp, stages (biased by 6), stall counter present, fainted,',
           ' * status (DFI_STATUS_*), its counter (sleep, freeze), confusion turns, the',
           ' * locked move slot (0xFF none) and its target, Mega forme, the item still',
           ' * held, and what the opponent has seen: seen, HP percent and colour flag',
           ' * of the last public display (DUOFORGE_HP_FLAG_*) */',
           'typedef struct df_conf_mon {', '    uint32_t present, hp;', '    uint8_t pp[4];', '    uint8_t stages[7];',
           '    uint8_t stall, fainted, status, status_counter, confusion, locked_slot, locked_target, mega;',
           '    uint8_t held, seen, seen_percent, seen_flag;',
           '    uint8_t vols; /* volatiles: 1 protect, 2 flashfire, 4 twoturnmove */',
           '} df_conf_mon;',
           '/* team step, side 0 / side 1 answered, tape slice, the turn, boundary and',
           ' * result afterwards, the picks of a team step, slot commands, the occupants',
           ' * of the positions afterwards (roster index, 0xFF empty), the positions',
           ' * (side * 2 + slot) that received a Pokemon in the reference\'s order (0xFF',
           ' * pads), weather, its turns, terrain, its turns, Trick Room turns, per',
           ' * side Tailwind, Reflect and Light Screen turns, the moves the request',
           ' * offers per slot (bit k move k, 0x10 Struggle, 0xFF none), the expected',
           ' * members by roster index */',
           'typedef struct df_conf_step {',
           '    uint32_t team, answered0, answered1, tape_off, tape_len, turn, boundary, result;',
           '    uint8_t picks[2][6];', '    df_conf_cmd cmds[2][2];', '    uint8_t occupants[2][2];', '    uint8_t entries[4];', '    uint8_t field[11];',
           '    uint8_t enabled[2][2];',
           '    df_conf_mon mons[2][6];',
           '    uint32_t ev_off[2], ev_len[2]; /* each player\'s events of the step in conf_events */',
           '} df_conf_step;',
           'typedef struct df_conf_battle {', '    const char *name;', '    uint32_t member_count;',
           '    const df_conf_member (*members)[6];', '    const df_conf_step *steps;', '    uint32_t step_count;',
           '    uint32_t dropped;', '} df_conf_battle;', '']
    all_tape = []
    all_events = []
    entries = []
    body = []
    for n in names:
        entries.append(convert(root, n, tables, body, all_tape, all_events))
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
    out.append('/* Every step\'s events per player (decision 0007 section 6), from the')
    out.append(' * protocol lines the game shows that player. */')
    out.append('static const duoforge_event conf_events[] = {')
    for e in all_events:
        out.append('    {%du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %du, {0u, 0u}},' % e)
    if not all_events:
        out.append('    {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, {0u, 0u}},')
    out.append('};')
    out.append('')
    out.append('static const df_conf_battle conf_battles[] = {')
    out.extend(entries)
    out.append('};')
    out.append('')
    out.append('#endif')
    text = '\n'.join(out) + '\n'
    target = os.path.join(root, 'tests', 'reference', 'conformance_team_c.h' if team_c else 'conformance.h')
    if check:
        have = io.open(target, encoding='ascii').read().replace('\r\n', '\n') if os.path.exists(target) else ''
        if have != text:
            sys.stderr.write('trace_to_c: %s differs from the traces\n' % target)
            return 1
        print('trace_to_c: %s matches the traces' % target)
        return 0
    io.open(target, 'w', encoding='ascii', newline='\n').write(text)
    print('trace_to_c: wrote %s (%d battles, %d tape entries, %d events)' % (target, len(names), len(all_tape),
                                                                            len(all_events)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
