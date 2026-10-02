#!/usr/bin/env python3
"""Turns reference traces (tools/reference/ps_trace.js) into C fixture
tables for the conformance test (decision 0006 sections 5.1 and 7).

usage: python tools/reference/trace_to_c.py <repo root> [--check]

Reads tests/reference/specs/*.json and tests/reference/traces/*.json and
writes tests/reference/conformance.h, conformance_team_c.h (the Team C
battles) and conformance_types.h (the record types both include), or, with
--check, compares all three.

As a library: load_battle(root, name) reads a spec and a trace (the only file
IO of a conversion), convert_battle(name, spec, trace, tables) turns them into
plain data and format_battle(data, out, all_tape, all_events) writes that
data as C tables; step_record(st, tape_off, ev_off, ev_len) is one step as the
nested tuple of its df_conf_step, in declaration order. A spec or trace the
converter does not model raises ConversionError, a SystemExit with a stable
`rule` and an optional `detail`: a script that does not catch it still prints
the message and exits with 1. The rule is the first argument of each raise
below.

Draws: every draw of the reference becomes a tape entry, except the
families decision 0006 section 5.1 (proposal B) drops. Each drop rule
checks its precondition and fails loudly otherwise:

  TEAM_ORDER        always: the team-preview actions are independent per side
  SPEED_TIE each:*  only if at most one tied Pokemon has a handler for
                    that event (Sitrus Berry, Grassy Seed): with two, the
                    tie orders their lines and the engine draws
  SPEED_TIE switch-order
                    only if at most one tied entering Pokemon has a SwitchIn
                    handler with an effect and at most one tied standing
                    Pokemon holds a White Herb (its onAnySwitchIn runs in this
                    order); Choice Scarf's onStart, a SwitchIn handler through
                    Battle.getCallback, only removes a choicelock, which an
                    entering Pokemon never has, so it does not count
  SPEED_TIE field:Residual
                    only if every tied handler only counts down a duration;
                    both sides' same side condition running out in this
                    residual is kept instead: the tie orders their two end
                    lines, and the entry states which side's line comes
                    first (the engine's draw; see side_end_tie)
  SPEED_TIE event:Accuracy
                    only between No Guard handlers (data/abilities.ts noguard):
                    onAnyAccuracy returns true when its holder is the source
                    or the target of the move and passes the accuracy on
                    otherwise, so every order of them gives the same value; a
                    tie with any other handler is refused (tie-context)
  SPEED_TIE event:AfterMove, event:AfterMega
                    never: White Herb's are the only handlers of these events
                    in the data, and the engine draws every tie among them
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

Dire Claw's status pick (Team C) is recorded as SECONDARY[0,3) in context
Hit; it becomes STATUS_PICK, and every one is kept: the engine draws it
after each successful secondary roll, as the reference does (decision 0009
section 10.6).

A two-turn move's lock (Electro Shot, Team B's Archaludon) is the state's
`locked`, which ps_trace.js records only while twoturnmove and the move's own
volatile both stand (tools/reference/ps_trace.js:280-282). Electro Shot's
onTryMove removes that volatile on the locked turn (data/moves.ts:4639-4642),
but twoturnmove stays: duration 2 (data/conditions.ts:290), onLockMove returns
the stored move (data/conditions.ts:317-319), and the duration counts down to
the end in the residual (sim/battle.ts:515-523). The Pokemon is locked until
then, as DuoForge models it (charge_turns and the lock end in the residual).
Between the locked move and the residual, at a mid-turn boundary (a pivot:
Parting Shot, Emergency Exit) or at the end of the battle, a state has
twoturnmove without the move's volatile and the recorder shows no lock. For
such a Pokemon the converter takes the lock last recorded for it
(two_turn_lock); if none was recorded earlier in the battle the state is
refused (twoturnmove-lock), never read as "no lock". The remembered lock goes
with twoturnmove: the first state without it for the Pokemon (the residual, or
a switch-out or a faint, which clear every volatile: sim/battle-actions.ts:117,
sim/battle.ts:2563) forgets it.

Stdlib only; CTest runs it with --check when Python is available.
"""
import io
import json
import os
import re
import sys

SITES = {'SPEED_TIE': 1, 'ACCURACY': 2, 'CRIT': 3, 'DAMAGE_ROLL': 4, 'SECONDARY': 5, 'STALL': 6,
         'SLEEP_TURNS': 7, 'FREEZE_THAW': 8, 'FULL_PARALYSIS': 9, 'CONFUSION_TURNS': 10,
         'CONFUSION_HIT': 11, 'RANDOM_TARGET': 12, 'STATUS_PICK': 13}
STATS = ['HP', 'Atk', 'Def', 'SpA', 'SpD', 'Spe']
GENDER = {'M': 1, 'F': 2}
GENDERLESS = 3


class ConversionError(SystemExit):
    """The converter refuses a spec or a trace: something it does not model,
    never a silent fallback. A SystemExit, so an uncaught one prints the
    message and exits with status 1. `rule` is a short stable id of the check
    that refused; `detail` an optional grouping key (a protocol line kind, an
    attribute, an effect)."""

    def __init__(self, rule, message, detail=None):
        super().__init__(message)
        self.rule = rule
        self.detail = detail

    def __reduce__(self):  # copy and pickle by the constructor's arguments (the default passes only the message)
        return (type(self), (self.rule, self.args[0], self.detail))


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
                raise ConversionError('gender-illegal', 'trace_to_c: %s cannot be (%s)' % (species_name, gender_tag),
                                      detail=species_name)
        elif rule == 3:
            mon['gender'] = GENDERLESS
        else:
            raise ConversionError('gender-missing',
                                  'trace_to_c: %s has no gender; specs always state it' % species_name,
                                  detail=species_name)
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
                    raise ConversionError('team-level', 'trace_to_c: level 50 only')
            else:
                raise ConversionError('team-line', 'trace_to_c: unknown line %r' % line, detail=line.split(':')[0])
        if mon['ability'] is None or mon['nature'] is None:
            raise ConversionError('team-incomplete', 'trace_to_c: %s needs an ability and a nature' % species_name,
                                  detail=species_name)
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
        raise ConversionError('side-end-shuffle', 'trace_to_c: unexpected side-end shuffle %s' % d)
    first = parts[0] if d['value'] == d['start'] else parts[1]  # random(start, start + 2): start keeps the order
    return (SITES['SPEED_TIE'], 0, 2, int(first[2][1]) - 1)


def tie_effects(group):
    """The effect ids of the handler entries ('H:<effect>:<holder>:<cb|end>')
    of a tie group, sorted: the detail of the errors about such a tie."""
    return '+'.join(sorted(set(g.split(':')[1] for g in group if isinstance(g, str) and g.startswith('H:'))))


def choice_scarf_slots(state):
    """The active slots ('p1a', ...) whose Pokemon holds a Choice Scarf in `state`."""
    slots = set()
    for s, side in enumerate(state['sides']):
        for pos, i in enumerate(side['active']):
            if i is not None and 0 <= i < len(side['pokemon']) and side['pokemon'][i]['item'] == 'choicescarf':
                slots.add('p%d%s' % (s + 1, 'ab'[pos]))
    return slots


def drop_reason(d, state, after=None):
    """Why draw `d` is not a tape entry, or None; `state` is the state before the step, `after` the one after
    it (an entering Pokemon stands in its slot there)."""
    site, ctx, group = d['site'], d.get('context', ''), d.get('group')
    if site == 'TEAM_ORDER':
        return 'team-preview order'
    if site == 'SPEED_TIE' and ctx.startswith('each:'):
        # P:<slot>:<handlers>:<effect ids>. Sitrus Berry (Update) and Grassy
        # Seed (TerrainChange) act only on their holder, so the order of the
        # Pokemon changes nothing.
        ids = [x for g in group for x in g.split(':', 3)[3].split('+') if x]
        if not all(x in ('sitrusberry', 'grassyseed') for x in ids):
            raise ConversionError('each-tie-handlers',
                                  'trace_to_c: %s tie between Pokemon with handlers: %s' % (ctx, group),
                                  detail=ctx + ':' + '+'.join(sorted(set(ids) - {'sitrusberry', 'grassyseed'})))
        if sum(1 for g in group if g.split(':', 3)[3]) <= 1:
            return 'each-event tie with at most one holder'
        return None  # the engine draws: the order of the holders' lines
    if site == 'SPEED_TIE' and ctx == 'switch-order':
        # P:<slot>:<SwitchIn handlers>:<S entering | - not>[:<onAnySwitchIn
        # effects of a standing Pokemon>]; the order decides something only
        # between two entering Pokemon with handlers, or between two standing
        # White Herb holders (Team C).
        parts = [g.split(':') for g in group]
        anys = [x for p in parts if len(p) > 4 for x in p[4].split('+')]
        if any(x != 'whiteherb' for x in anys):
            raise ConversionError('switch-order-handlers',
                                  'trace_to_c: switch-order tie with onAnySwitchIn handlers %s' % group,
                                  detail='+'.join(sorted(set(anys) - {'whiteherb'})))
        # An entering Choice Scarf holder counts one SwitchIn handler without
        # an effect (data/items.ts choicescarf onStart).
        scarves = choice_scarf_slots(after) if after is not None else set()
        effective = []
        for p in parts:
            n = int(p[2]) - (1 if p[3] == 'S' and p[1] in scarves else 0)
            if n < 0:
                raise ConversionError('switch-order-handlers',
                                      'trace_to_c: a Choice Scarf holder without its SwitchIn handler in %s' % group,
                                      detail='choicescarf')
            effective.append(n)
        bearers = sum(1 for p, n in zip(parts, effective) if n != 0 and p[3] == 'S')
        herbs = sum(1 for p in parts if len(p) > 4)
        if bearers <= 1 and herbs <= 1:
            return 'switch-in order with at most one entry effect'
        return None  # the engine draws
    if site == 'SPEED_TIE' and ctx == 'field:Residual':
        if all(g.startswith('H:') and g.endswith(':end') for g in group):
            if side_end_tie(d, state) is not None:
                raise ConversionError('side-end-tie',
                                      'trace_to_c: ending side conditions reach drop_reason: %s' % group)
            return 'residual tie of duration counters'
        if all(g.startswith('H:') and g.endswith(':cb') for g in group):
            return None  # callbacks (burn, Grassy Terrain): the engine draws
        raise ConversionError('residual-tie-callbacks', 'trace_to_c: residual tie with callbacks: %s' % group,
                              detail=tie_effects(group))
    if site == 'SPEED_TIE' and ctx in ('event:AfterMove', 'event:AfterMega'):
        if all(g.startswith('H:whiteherb:') and g.endswith(':cb') for g in group):
            return None  # the engine draws: the order of the holders' checks
        raise ConversionError('after-event-tie', 'trace_to_c: %s tie with %s' % (ctx, group),
                              detail=ctx + ':' + tie_effects(group))
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
        raise ConversionError('modifydamage-tie', 'trace_to_c: ModifyDamage tie with %s' % group,
                              detail=tie_effects(group))
    if site == 'SPEED_TIE' and ctx == 'event:Accuracy' and all(
            g.startswith('H:noguard:') and g.endswith(':cb') for g in group):
        # data/abilities.ts noguard: onAnyAccuracy(accuracy, target, source, move) returns true when its holder is
        # the source or the target of the move and the accuracy it was given otherwise. Whichever of the tied
        # handlers runs first, a true passes on as true and the accuracy stays what it was: one order, one value.
        return 'No Guard handlers whose order changes nothing'
    if site == 'SPEED_TIE' and ctx != 'queue':
        raise ConversionError('tie-context', 'trace_to_c: unhandled tie context %s' % ctx, detail=ctx)
    if site == 'INSERT_TIE':
        # Ties are among entry actions of one speed; runSwitch takes every
        # entry queued right behind it, so their queue order changes nothing
        # as long as the entries stand together.
        runs = [i for i, g in enumerate(group) if g.startswith('A:runSwitch:')]
        if runs and runs == list(range(runs[0], runs[0] + len(runs))):
            return 'queue order of entries that run together'
        raise ConversionError('insert-tie', 'trace_to_c: insert tie in %s' % group)
    if site == 'RANDOM_TARGET' and ctx in ('action-speed', 'resolve'):
        return 'target computed for priority'
    if site == 'RANDOM_TARGET' and ctx == 'execute:allAdjacentFoes':
        return 'main target of a spread move'
    if site == 'UNKNOWN':
        raise ConversionError('unclassified-draw', 'trace_to_c: unclassified draw', detail=ctx)
    return None


def site_of(d):
    """The tape site of draw `d`: the only draw in context Hit is Dire Claw's
    status pick, recorded as SECONDARY[0,3); any other fails loudly."""
    if d.get('context') == 'Hit':
        if d['site'] != 'SECONDARY' or (d['lo'], d['hi']) != (0, 3):
            raise ConversionError('hit-draw', 'trace_to_c: unexpected Hit draw %s' % d,
                                  detail='%s[%s,%s)' % (d['site'], d.get('lo'), d.get('hi')))
        return 'STATUS_PICK'
    return d['site']


def tape_entry(d):
    site = SITES[site_of(d)]
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


def two_turn_lock(p, key, remembered):
    """The two-turn lock of Pokemon `p` in a state, [slot, target location] or None. `remembered` maps
    (side, name) to the lock last recorded for a Pokemon while twoturnmove stands; see the module docstring."""
    lock = p.get('locked')
    if lock:
        remembered[key] = lock
        return lock
    if 'twoturnmove' not in p['volatiles']:
        remembered.pop(key, None)  # the residual ended it, or a switch-out or a faint cleared it: nothing stays locked
        return None
    # twoturnmove without the move's volatile: Electro Shot's onTryMove removed it on the locked turn, twoturnmove
    # (onLockMove) locks until the residual
    if key not in remembered:
        raise ConversionError('twoturnmove-lock', 'trace_to_c: twoturnmove without a lock recorded earlier on %s' %
                              key[1], detail='twoturnmove')
    return remembered[key]


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
            # Struggle is what the reference's request offers: [2] for the
            # slot, with no PP left or with every move with PP disabled
            # (Champions' Fake Out, a choice lock; Team C).
            rows = state['sides'][side].get('enabled') or []
            struggle = slot < len(rows) and rows[slot] == [2]
            if all(pp == 0 for pp in mon['pp']) and not struggle:
                raise ConversionError('struggle-request',
                                      'trace_to_c: no PP left and no Struggle in the request: %r' % text)
            if struggle:
                # Such a request has no canMegaEvo; the reference pushes
                # Struggle and drops a typed "mega" (sim/side.ts chooseMove).
                cmds.append((1, 4, 0xFF, 0, 0))
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
            asked = state['sides'][side]['request'] != 'switch' or bool(mon.get('switch_flag'))
            cmds.append((3, 0, 0, 0, 0) if asked else (0, 0, 0, 0, 0))
        else:
            raise ConversionError('choice-kind', 'trace_to_c: choice %r is not supported' % part, detail=words[0])
    return ('slots', cmds)


BOUNDARY = {'teampreview': 1, 'move': 2, 'switch': 3}
STATUS = {'': 0, 'brn': 1, 'frz': 2, 'par': 3, 'slp': 4, 'psn': 5, 'fnt': 0}
WEATHER = {'': 0, 'raindance': 1, 'sunnyday': 2}
TERRAIN = {'': 0, 'grassyterrain': 1, 'psychicterrain': 2}
FIELD_PSYCHIC_TERRAIN = 3  # DUOFORGE_FIELD_PSYCHIC_TERRAIN (Team C)
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
            raise ConversionError('unknown-pokemon', 'trace_to_c: unknown Pokemon in %r' % line,
                                  detail=who.split(': ', 1)[1])
        token = hp.split(' ')[0]
        if token == '0':
            shown[side][roster] = (0, 0)
            continue
        m = re.match(r'^(\d+)/100([gry]?)$', token)
        if not m:
            raise ConversionError('public-hp-display', 'trace_to_c: not a public HP display in %r' % line)
        shown[side][roster] = (int(m.group(1)), HP_FLAGS[m.group(2)])



# ---------------------------------------------------------------- events
# Decision 0007 section 6: one event per protocol line the game shows a
# player, with the HP that player's screen shows. Values of
# include/duoforge/duoforge.h.
EV = {name: i + 1 for i, name in enumerate(
    ['TURN', 'SWITCH', 'MOVE', 'DAMAGE', 'HEAL', 'FAINT', 'CANT', 'MISS', 'CRIT', 'SUPER_EFFECTIVE', 'RESISTED',
     'IMMUNE', 'FAIL', 'PROTECT', 'BLOCKED', 'BOOST', 'UNBOOST', 'STATUS', 'CURE_STATUS', 'CONFUSION_START',
     'CONFUSION_END', 'CONFUSED', 'FLASH_FIRE', 'WEATHER', 'FIELD_START', 'FIELD_END', 'SIDE_START', 'SIDE_END',
     'ITEM_END', 'FORME', 'MEGA', 'PREPARE', 'ANIMATION', 'ABILITY', 'ACTIVATE', 'UPKEEP', 'RESULT',
     'SINGLE_TURN'])}
CAUSE = {'NONE': 0, 'MOVE': 1, 'ITEM': 2, 'ABILITY': 3, 'RECOIL': 4, 'DRAIN': 5, 'BURN': 6, 'CONFUSION': 7,
         'TERRAIN': 8, 'PARALYSIS': 9, 'SLEEP': 10, 'FREEZE': 11, 'FLINCH': 12, 'NO_PP': 13, 'POISON': 14}
FLAG = {'STILL': 1, 'LOCKED': 2, 'SPREAD': 4, 'UPKEEP': 8, 'EATEN': 16, 'MESSAGE': 32, 'MISS': 64, 'NOTARGET': 128}
AILMENT = {'brn': 1, 'frz': 2, 'par': 3, 'slp': 4, 'psn': 5}
EV_STATS = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion']
NOPOS = 0xFF

# The reference's volatiles (Pokemon.volatiles, as ps_trace.js records them)
# and how the state comparison covers them. COMPARED_VOLATILES are bits of
# df_conf_mon.vols; IGNORED_VOLATILES are compared through another field.
# Any other volatile is refused: a new mechanic's volatile must be placed in
# one of the two tables before its traces convert.
COMPARED_VOLATILES = (('protect', 1), ('flashfire', 2), ('twoturnmove', 4), ('choicelock', 8), ('unburden', 16),
                      ('helpinghand', 32), ('followme', 64), ('flinch', 128))
IGNORED_VOLATILES = {
    # data/conditions.ts stall: compared as df_conf_mon.stall (its presence).
    'stall': 'the stall field',
    # data/conditions.ts confusion: compared as df_conf_mon.confusion (its turns).
    'confusion': 'the confusion field',
    # twoturnmove's onStart adds the move's own volatile with the target
    # (data/conditions.ts twoturnmove); compared as locked_slot and
    # locked_target. twoturnmove's onEnd and Electro Shot's onTryMove remove
    # it, so it never stands without twoturnmove (checked below); twoturnmove
    # can stand without it, from the locked turn to the residual, and the lock
    # is then the one remembered (two_turn_lock).
    'electroshot': 'the locked slot and target',
}
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
            elif what == 'psn':
                cause = CAUSE['POISON']
            elif what == 'confusion':
                cause = CAUSE['CONFUSION']
            elif what == 'Grassy Terrain':
                cause = CAUSE['TERRAIN']
            elif what in ('Parting Shot', 'Flip Turn'):
                cause, id2 = CAUSE['MOVE'], tables['MOVE'][key(what)]
            elif what == 'lockedmove':
                pass  # a MOVE flag
            else:
                raise ConversionError('from-attribute', 'trace_to_c: unknown [from] %r' % a, detail=what)
        elif a.startswith('[of] '):
            other = ev_pos(a[5:])
    return cause, id2, other


def ev_hp(text, side, viewer, maxhp):
    """An HP field as `viewer` sees it -> (hp, hp_max, kind, flag, status)."""
    tokens = text.split(' ')
    status = 0
    if len(tokens) > 1 and tokens[1] != 'fnt':
        if tokens[1] not in AILMENT:
            raise ConversionError('hp-status', 'trace_to_c: unknown status in HP %r' % text, detail=tokens[1])
        status = AILMENT[tokens[1]]
    if tokens[0] == '0':
        return (0, maxhp if side == viewer else 100, HP_EXACT if side == viewer else HP_PERCENT, 0, 0)
    m = re.match(r'^(\d+)/(\d+)([gry]?)$', tokens[0])
    if not m:
        raise ConversionError('hp-format', 'trace_to_c: bad HP %r' % text)
    if side == viewer:
        return (int(m.group(1)), int(m.group(2)), HP_EXACT, 0, status)
    if m.group(2) != '100':
        raise ConversionError('hp-opponent-exact', 'trace_to_c: the opponent sees exact HP in %r' % text)
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
                    raise ConversionError('move-attribute', 'trace_to_c: unknown move attribute %r' % a, detail=a)
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
            if args[1] == 'Protect':
                e = ev_tuple(EV['PROTECT'], ev_pos(args[0]))
            elif args[1] == 'Helping Hand':  # Team C: [of] the user
                _, _, of = ev_cause(attrs, tables)
                e = ev_tuple(EV['SINGLE_TURN'], ev_pos(args[0]), of, 0, tables['MOVE'][key(args[1])])
            elif args[1] == 'move: Follow Me' and not attrs:  # Team C: no [of]; [zeffect] is not in the format
                e = ev_tuple(EV['SINGLE_TURN'], ev_pos(args[0]), NOPOS, 0, tables['MOVE'][key(args[1][6:])])
            else:
                raise ConversionError('singleturn-line', 'trace_to_c: unknown -singleturn %r' % line, detail=args[1])
        elif kind == '-activate':
            pos = ev_pos(args[0])
            what = args[1]
            if what == 'move: Protect':
                e = ev_tuple(EV['BLOCKED'], pos)
            elif what == 'move: Psychic Terrain':  # Team C: a priority move stopped at a grounded target
                e = ev_tuple(EV['BLOCKED'], pos, detail=FIELD_PSYCHIC_TERRAIN)
            elif what == 'confusion':
                e = ev_tuple(EV['CONFUSED'], pos)
            elif what.startswith('ability: '):
                e = ev_tuple(EV['ACTIVATE'], pos, NOPOS, CAUSE['ABILITY'], 0, tables['ABILITY'][key(what[9:])] + 1)
            elif what.startswith('move: '):
                e = ev_tuple(EV['ACTIVATE'], pos, NOPOS, CAUSE['MOVE'], 0, tables['MOVE'][key(what[6:])])
            else:
                raise ConversionError('activate-line', 'trace_to_c: unknown -activate %r' % line, detail=what)
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
                raise ConversionError('start-end-line', 'trace_to_c: unknown %s %r' % (kind, line),
                                      detail='%s %s' % (kind, what))
        elif kind == '-weather':
            cause, id2, other = ev_cause(attrs, tables)
            weather = {'RainDance': 1, 'SunnyDay': 2, 'none': 0}[args[0]]
            e = ev_tuple(EV['WEATHER'], NOPOS, other, cause, 0, id2, detail=weather,
                         flags=FLAG['UPKEEP'] if '[upkeep]' in attrs else 0)
        elif kind in ('-fieldstart', '-fieldend'):
            cause, id2, other = ev_cause(attrs, tables)
            field = {'move: Grassy Terrain': 1, 'move: Trick Room': 2, 'move: Psychic Terrain': FIELD_PSYCHIC_TERRAIN}[args[0]]
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
                    raise ConversionError('anim-attribute', 'trace_to_c: unknown -anim attribute %r' % a, detail=a)
            shown = ev_pos(args[2])  # a fainted Pokemon has no slot ("p1: Name")
            e = ev_tuple(EV['ANIMATION'], ev_pos(args[0]), NOPOS if shown is None else shown, 0,
                         tables['MOVE'][key(args[1])], flags=flags)
        elif kind == '-ability':
            e = ev_tuple(EV['ABILITY'], ev_pos(args[0]), NOPOS, 0, 0, tables['ABILITY'][key(args[1])] + 1)
        else:
            raise ConversionError('protocol-line', 'trace_to_c: unknown protocol line %r' % line, detail=kind)
        out.append(e)
    return out


def boundary_of(state, log):
    """The DuoForge boundary after a step: TERMINAL, else the request kind."""
    if state['ended']:
        return 5
    kinds = set(s['request'] for s in state['sides']) - {''}
    if len(kinds) != 1:
        raise ConversionError('mixed-requests', 'trace_to_c: mixed requests %s' % sorted(kinds))
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


def read_ascii(path):
    with io.open(path, encoding='ascii') as f:
        return f.read()


def load_json(root, kind, name):
    """tests/reference/<kind>/<name>.json, parsed."""
    with io.open(os.path.join(root, 'tests', 'reference', kind, name + '.json'), encoding='utf-8') as f:
        return json.load(f)


def load_battle(root, name):
    """The spec and the trace of the committed battle `name`: the file IO of a conversion."""
    return load_json(root, 'specs', name), load_json(root, 'traces', name)


def convert_battle(name, spec, trace, tables):
    """One battle as plain data, in the field order of the df_conf_* types
    (conformance_types.h): {'name', 'purpose', 'member_count', 'members',
    'steps', 'dropped_total'}. 'members' holds per side its members as int
    tuples (df_conf_member; the C array zero-fills the rest of the six). A step
    is a dict with the df_conf_step fields, except that its own tape entries
    (site, lo, hi, value) are 'tape' and each player's events (the fields of
    duoforge_event as int tuples) are 'events', instead of offsets into the
    shared arrays; 'dropped' is the number of draws the step dropped.
    Pure: no file IO, and spec and trace are not changed. What the converter
    does not model raises ConversionError."""
    teams = [parse_team(spec['teams'][s], tables) for s in range(2)]
    members = []
    for s in range(2):
        rows = []
        for mon in teams[s]:
            mv = mon['moves'] + [0] * (4 - len(mon['moves']))
            rows.append((mon['species'], mon['gender'], mon['nature'], tuple(mon['sp']), mon['ability'], mon['item'],
                         len(mon['moves']), tuple(mv)))
        members.append(rows)
    picks = [None, None]
    state = trace['start']['state']
    # Species are unique per team (species clause): the start state lists the
    # whole roster in order, so a species names its roster index.
    roster_of = []
    for s in range(2):
        names = [name_of(p) for p in state['sides'][s]['pokemon']]
        if len(names) != len(teams[s]) or len(set(names)) != len(names):
            raise ConversionError('roster-unique', 'trace_to_c: %s side %d roster is not unique' % (name, s))
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
    # The two-turn lock last recorded per (side, name) while twoturnmove stands (two_turn_lock).
    remembered_locks = {}
    # A switch request made during the turn: the step that led to it has not
    # reached the end of the turn (no upkeep line).
    mid_turn = False
    for step in trace['steps']:
        public_lines(step['log'], roster_of, shown)
        kinds = {}
        for side, sid in enumerate(('p1', 'p2')):
            if sid in step['input']:
                kinds[side] = convert_choice(step['input'][sid], side, state, roster_of, mid_turn)
        tape = []
        dropped = 0
        for d in step['draws']:
            ends = side_end_tie(d, state)
            if ends is not None:
                tape.append(ends)
            elif drop_reason(d, state, step['state']) is None:
                tape.append(tape_entry(d))
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
                    row.append((0, 0, (0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0), 0, 0, 0, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0))
                    continue
                pp = p['pp'] + [0] * (4 - len(p['pp']))
                stall = 1 if 'stall' in p['volatiles'] else 0
                # A fainted Pokemon's status is not compared (DuoForge drops it).
                status, counter = (0, 0) if p['fainted'] else (STATUS[p['status']], p['status_time'])
                if status not in (2, 4):
                    counter = 0
                lock = two_turn_lock(p, (s, name_of(p)), remembered_locks)
                lslot, ltarget = (lock[0], abs_target(s, lock[1])) if lock else (0xFF, 0)
                # A Choice item's lock (Team C) names its slot without a
                # target; with a two-turn lock both are on the same move.
                choice = p.get('choice')
                if choice is not None:
                    if choice < 0 or (lock and lock[0] != choice):
                        raise ConversionError(
                            'choice-lock', 'trace_to_c: unexpected choice lock %r (two-turn lock %r)' % (choice, lock))
                    if not lock:
                        lslot, ltarget = choice, 0
                seen = shown[s].get(roster)
                compared = dict(COMPARED_VOLATILES)
                for v in p['volatiles']:
                    if v not in compared and v not in IGNORED_VOLATILES:
                        raise ConversionError('unknown-volatile', 'trace_to_c: unknown volatile %r of %s' %
                                              (v, name_of(p)), detail=v)
                if 'electroshot' in p['volatiles'] and 'twoturnmove' not in p['volatiles']:
                    raise ConversionError('unknown-volatile', 'trace_to_c: electroshot without twoturnmove on %s' %
                                          name_of(p), detail='electroshot')
                vols = sum(bit for name, bit in COMPARED_VOLATILES if name in p['volatiles'])
                row.append((1, p['hp'], tuple(pp), tuple(x + 6 for x in p['boosts']),
                            stall, 1 if p['fainted'] else 0, status, counter, p['confusion'], lslot, ltarget,
                            p.get('mega', 0), 1 if p['item'] else 0, 1 if seen else 0, seen[0] if seen else 0,
                            seen[1] if seen else 0, vols))
            mons.append(tuple(row))
        cmds = []
        for s in range(2):
            if s in kinds and kinds[s][0] == 'slots':
                c = kinds[s][1] + [(0, 0, 0, 0, 0)] * (2 - len(kinds[s][1]))
            else:
                c = [(0, 0, 0, 0, 0)] * 2
            cmds.append(tuple(c))
        pk = []
        for s in range(2):
            row = (kinds[s][1] if team else []) + [0] * (6 - (len(kinds[s][1]) if team else 0))
            pk.append(tuple(row))
        occ = []
        for s in range(2):
            sd = new_state['sides'][s]
            row = [roster_of[s][name_of(sd['pokemon'][i])] if i >= 0 else 0xFF for i in sd['active']]
            occ.append(tuple(row))
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
            enabled.append(tuple(row))
        weather = WEATHER[new_state['weather']]
        terrain = TERRAIN[new_state['terrain']]
        field = (weather, new_state['weather_turns'] if weather else 0, terrain,
                 new_state['terrain_turns'] if terrain else 0, new_state['trick_room']) + tuple(
                     c for sd in new_state['sides'] for c in sd['conditions'])
        boundary = boundary_of(new_state, step['log'])
        result = RESULT[new_state['winner']] if boundary == 5 else 0
        events = [step_events(step['log'], viewer, roster_of, maxhp, tables) for viewer in range(2)]
        steps.append({'team': 1 if team else 0, 'answered0': 1 if 0 in kinds else 0, 'answered1': 1 if 1 in kinds else 0,
                      'turn': new_state['turn'], 'boundary': boundary, 'result': result, 'picks': tuple(pk),
                      'cmds': tuple(cmds), 'occupants': tuple(occ), 'entries': tuple(ent), 'field': field,
                      'enabled': tuple(enabled), 'mons': tuple(mons), 'tape': tape, 'events': events,
                      'dropped': dropped})
        state = new_state
        mid_turn = not any(line.startswith('|upkeep') for line in step['log'])
    return {'name': name, 'purpose': spec['purpose'], 'member_count': len(teams[0]), 'members': members,
            'steps': steps, 'dropped_total': dropped_total}


def c_init(value):
    """A C initializer of nested int tuples: (1, (2, 3)) is {1u, {2u, 3u}}."""
    if isinstance(value, (tuple, list)):
        return '{%s}' % ', '.join(c_init(v) for v in value)
    return '%du' % value


def step_record(st, tape_off, ev_off, ev_len):
    """A step of convert_battle's data as the nested int tuple of a
    df_conf_step, in the order of its declaration (conformance_types.h): the
    one place in Python that order is written down. `tape_off` is where the
    step's tape entries start in the tape that holds them, `ev_off` and
    `ev_len` per player where its events start in the event array and how many
    there are."""
    return (st['team'], st['answered0'], st['answered1'], tape_off, len(st['tape']), st['turn'], st['boundary'],
            st['result'], st['picks'], st['cmds'], st['occupants'], st['entries'], st['field'], st['enabled'],
            st['mons'], tuple(ev_off), tuple(ev_len))


def format_battle(data, out, all_tape, all_events):
    """The C tables of a battle from convert_battle's data. The lines go to
    `out`; the tape entries and events of each step are appended to the shared
    arrays all_tape and all_events, where the step records its offsets.
    Returns the battle's row of conf_battles."""
    name = data['name']
    w = out.append
    w('/* %s: %s */' % (name, data['purpose']))
    w('static const df_conf_member conf_%s_members[2][6] = {' % name)
    for rows in data['members']:
        w('    {%s},' % ', '.join(c_init(row) for row in rows))
    w('};')
    steps = []
    for st in data['steps']:
        tape_off = len(all_tape)
        all_tape.extend(st['tape'])
        ev_off, ev_len = [], []
        for evs in st['events']:
            ev_off.append(len(all_events))
            ev_len.append(len(evs))
            all_events.extend(evs)
        steps.append('    %s,  /* %d draws dropped */' % (c_init(step_record(st, tape_off, ev_off, ev_len)),
                                                           st['dropped']))
    w('static const df_conf_step conf_%s_steps[] = {' % name)
    out.extend(steps)
    w('};')
    return '    {"%s", %du, conf_%s_members, conf_%s_steps, sizeof conf_%s_steps / sizeof conf_%s_steps[0], %du},' % (
        name, data['member_count'], name, name, name, name, data['dropped_total'])


def spec_is_team_c(name, spec):
    """A spec with "data": "team_c" records a Team C battle (decision 0009 section 6.1)."""
    data = spec.get('data')
    if data not in (None, 'team_c'):
        raise ConversionError('spec-data', 'trace_to_c: %s: unknown data %r' % (name, data))
    return data == 'team_c'


def is_team_c(root, name):
    """spec_is_team_c of the committed spec `name`."""
    return spec_is_team_c(name, load_json(root, 'specs', name))


def load_tables(root, team_c):
    """Name -> id tables: the closure's, or for Team C the extended tables
    (the closure ids plus Team C's, decision 0009 section 3.2)."""
    header = read_ascii(os.path.join(root, 'src', 'data', 'closure_tables.h'))
    source = read_ascii(os.path.join(root, 'src', 'data', 'closure_tables.c'))
    start = 'dfi_closure_formes[DFI_FORME_COUNT] = {'
    if team_c:
        header += read_ascii(os.path.join(root, 'src', 'data', 'extended_tables.h'))
        source = read_ascii(os.path.join(root, 'src', 'data', 'extended_tables.c'))
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
    rc |= write_types(root, check)
    return rc


# The record types of the conformance tables, shared by conformance.h,
# conformance_team_c.h and the comparators; they are written to
# conformance_types.h, which the other two include.
TYPES = [
    '/* species, gender, nature, Stat Points, ability + 1 (0 none), item + 1 (0 none), moves */',
    'typedef struct df_conf_member {',
    '    uint32_t species, gender, nature, sp[6], ability, item, move_count, moves[4];',
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
    '    uint8_t vols; /* volatiles: 1 protect, 2 flashfire, 4 twoturnmove, 8 choicelock, 16 unburden, 32 helpinghand,',
    '                     64 followme, 128 flinch */',
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
    '    uint8_t picks[2][6];', '    df_conf_cmd cmds[2][2];', '    uint8_t occupants[2][2];',
    '    uint8_t entries[4];', '    uint8_t field[11];',
    '    uint8_t enabled[2][2];',
    '    df_conf_mon mons[2][6];',
    '    uint32_t ev_off[2], ev_len[2]; /* each player\'s events of the step in conf_events */',
    '} df_conf_step;',
    'typedef struct df_conf_battle {', '    const char *name;', '    uint32_t member_count;',
    '    const df_conf_member (*members)[6];', '    const df_conf_step *steps;', '    uint32_t step_count;',
    '    uint32_t dropped;', '} df_conf_battle;']


def types_header():
    """The text of conformance_types.h: TYPES with its own include guard."""
    guard = 'DUOFORGE_TESTS_REFERENCE_CONFORMANCE_TYPES_H'
    out = ['/*', ' * GENERATED by tools/reference/trace_to_c.py. Do not edit by hand.',
           ' * The record types of the conformance tables (conformance.h and',
           ' * conformance_team_c.h) and of the comparators that read them.', ' */',
           '#ifndef %s' % guard, '#define %s' % guard, '#include <stdint.h>', ''] + TYPES + ['', '#endif']
    return '\n'.join(out) + '\n'


def emit(target, text, check, subject, summary=''):
    """Writes `text` to `target`, or with `check` compares it with the file
    (read with LF line ends); `subject` is what it must equal. Returns the exit status."""
    if check:
        have = read_ascii(target).replace('\r\n', '\n') if os.path.exists(target) else ''
        if have != text:
            sys.stderr.write('trace_to_c: %s differs from %s\n' % (target, subject))
            return 1
        print('trace_to_c: %s matches %s' % (target, subject))
        return 0
    with io.open(target, 'w', encoding='ascii', newline='\n') as f:
        f.write(text)
    print('trace_to_c: wrote %s%s' % (target, summary))
    return 0


def write_types(root, check):
    return emit(os.path.join(root, 'tests', 'reference', 'conformance_types.h'), types_header(), check,
                'the template in trace_to_c.py')


def write_header(root, names, tables, team_c, check):
    text, n_tape, n_events = build_header(root, names, tables, team_c)
    target = os.path.join(root, 'tests', 'reference', 'conformance_team_c.h' if team_c else 'conformance.h')
    return emit(target, text, check, 'the traces',
                ' (%d battles, %d tape entries, %d events)' % (len(names), n_tape, n_events))


def build_header(root, names, tables, team_c):
    """The text of conformance.h (conformance_team_c.h for Team C) over the
    committed battles `names`, and the sizes of its tape and event arrays."""
    guard = 'DUOFORGE_TESTS_REFERENCE_CONFORMANCE_TEAM_C_H' if team_c else 'DUOFORGE_TESTS_REFERENCE_CONFORMANCE_H'
    source_line = (' * tests/reference/traces, the Team C battles (decision 0009; pinned Showdown' if team_c else
                   ' * tests/reference/traces (pinned Showdown b2cb775b0616115b775534eaeff50300e1fc81fc).')
    out = ['/*', ' * GENERATED by tools/reference/trace_to_c.py from tests/reference/specs and', source_line]
    if team_c:
        out.append(' * b2cb775b0616115b775534eaeff50300e1fc81fc), read with the extended tables.')
    out += [' * Do not edit by hand. Draw drop rules: tools/reference/trace_to_c.py.', ' */',
            '#ifndef %s' % guard, '#define %s' % guard,
           '#include <stdint.h>', '', '#include <duoforge/duoforge.h>', '', '#include "rng/draw.h"', '',
           '#include "reference/conformance_types.h"', '']
    all_tape = []
    all_events = []
    entries = []
    body = []
    for n in names:
        spec, trace = load_battle(root, n)
        entries.append(format_battle(convert_battle(n, spec, trace, tables), body, all_tape, all_events))
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
    return '\n'.join(out) + '\n', len(all_tape), len(all_events)


if __name__ == '__main__':
    sys.exit(main())
