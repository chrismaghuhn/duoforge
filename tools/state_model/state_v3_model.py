#!/usr/bin/env python3
"""Structural model of DuoForge context v3, state v3, invariants v3, codec v3
and the decision domains (decisions 0005 and 0006). Written from the decision
notes, not from the C sources. Stdlib only. CTest never runs it.

Prints every value the C tests assert: context bytes and fingerprints,
fixture encodings and digests, per-region mutation counts, targeted invariant
edits, setup-sweep counts, and for every fixture and player the request, the
candidate count and the SHA-256 of the concatenated canonical candidates.

With --goldens it prints tests/support/goldens.c instead.
"""
import hashlib
import itertools
import struct
import sys

MAGIC = bytes([0x89, 0x44, 0x55, 0x4F, 0x0D, 0x0A, 0x1A, 0x0A])
KIND_CONTEXT = 1
KIND_BATTLE_STATE = 2
SCHEMA = 3
SEMANTICS = 3
CONTEXT_BYTES_SIZE = 63
HEADER_SIZE = 215
QUEUE_OFF = 95
QUEUE_CAP = 12
QUEUE_REC_SIZE = 10
SIDE_SIZE = 397
POS_SIZE = 21
KNOW_SIZE = 7
MEMBER_SIZE = 48
STATE_SIZE = HEADER_SIZE + 2 * SIDE_SIZE
assert STATE_SIZE == 1009 and QUEUE_OFF + QUEUE_CAP * QUEUE_REC_SIZE == HEADER_SIZE
MAX_ROSTER = 6
MOVE_SLOTS = 4
NONE = 0xFF

TEAM_SELECTION, TURN, REPLACEMENT, PIVOT, TERMINAL = 1, 2, 3, 4, 5
BOUNDARY_NAMES = {1: 'TEAM_SELECTION', 2: 'TURN', 3: 'REPLACEMENT', 4: 'PIVOT', 5: 'TERMINAL'}
SLOT_NONE, SLOT_MOVE, SLOT_SWITCH, SLOT_PASS = 0, 1, 2, 3
CHOICE_TEAM_SELECTION, CHOICE_SLOTS = 1, 2
TARGET_NONE = 0xFF
# target classes
NORMAL, ANY, ADJ_ALLY, ADJ_ALLY_OR_SELF, ADJ_FOE, SELF, ALL_ADJ_FOES, ALLY_SIDE, ALL = range(1, 10)
CLASS_COUNT = 9

# state v3 value ranges (decision 0006 section 3)
RESULT_NONE, RESULT_SIDE0, RESULT_SIDE1, RESULT_TIE = 0, 1, 2, 3
WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN = 0, 1, 2
TERRAIN_NONE, TERRAIN_GRASSY = 0, 1
FIELD_TURNS_MAX = 5
SCREEN_TURNS_MAX = 8
TAILWIND_TURNS_MAX = 4
STAGE_COUNT = 7
STAGE_NEUTRAL = 6
STAGE_MAX = 12
VOL_FLINCH, VOL_PROTECT, VOL_FLASH_FIRE = 1, 2, 4
VOL_FLAGS_MAX = 7
STALL_LEVEL_MAX = 6
STALL_TURNS_MAX = 2
CONFUSION_TURNS_MAX = 5
CHARGE_TURNS_MAX = 2
MOVE_SLOT_STRUGGLE = 4
SWITCH_NONE, SWITCH_MOVE, SWITCH_EMERGENCY_EXIT = 0, 1, 2
REVEALED_ITEM_CONSUMED, REVEALED_MEGA = 1, 2
# side-relative offsets of the v3 side block
SIDE_POS_OFF, SIDE_SEALED_OFF, SIDE_KNOW_OFF, SIDE_MEMBERS_OFF = 15, 57, 67, 109
assert SIDE_POS_OFF + 2 * POS_SIZE == SIDE_SEALED_OFF and SIDE_SEALED_OFF + 10 == SIDE_KNOW_OFF
assert SIDE_KNOW_OFF + MAX_ROSTER * KNOW_SIZE == SIDE_MEMBERS_OFF
assert SIDE_MEMBERS_OFF + MAX_ROSTER * MEMBER_SIZE == SIDE_SIZE
Q_NONE, Q_SWITCH_IN, Q_RUN_SWITCH, Q_SWITCH, Q_MEGA, Q_MOVE, Q_RESIDUAL = range(7)


# ---------------------------------------------------------------- PCG32
def pcg_step(state, inc):
    return (state * 6364136223846793005 + inc) & 0xFFFFFFFFFFFFFFFF


def pcg_seed(initstate, initseq):
    inc = ((initseq << 1) | 1) & 0xFFFFFFFFFFFFFFFF
    state = pcg_step(0, inc)
    state = (state + initstate) & 0xFFFFFFFFFFFFFFFF
    state = pcg_step(state, inc)
    return state, inc


def pcg_next(st):
    old = st['rng_state']
    st['rng_state'] = pcg_step(old, st['rng_inc'])
    st['draws'] += 1
    xorshifted = (((old >> 18) ^ old) >> 27) & 0xFFFFFFFF
    rot = old >> 59
    return ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & 0xFFFFFFFF


# ---------------------------------------------------------------- context
class Context:
    def __init__(self, data_kind, max_roster, brought_count, species_count, move_count, table):
        self.data_kind = data_kind
        self.max_roster = max_roster
        self.brought_count = brought_count
        self.species_count = species_count
        self.move_count = move_count
        self.table = bytes(table)

    def valid(self):
        return (self.data_kind == 1 and 1 <= self.max_roster <= MAX_ROSTER
                and 1 <= self.brought_count <= self.max_roster
                and 1 <= self.species_count <= 65535 and 1 <= self.move_count <= 65535
                and len(self.table) == self.move_count and all(1 <= c <= CLASS_COUNT for c in self.table))

    def canonical_bytes(self):
        b = MAGIC + struct.pack('<HHII', KIND_CONTEXT, SCHEMA, SEMANTICS, CONTEXT_BYTES_SIZE)
        b += bytes([2, 2, MAX_ROSTER, MOVE_SLOTS, self.data_kind, self.max_roster, self.brought_count])
        b += struct.pack('<HH', self.species_count, self.move_count)
        b += hashlib.sha256(self.table).digest()
        assert len(b) == CONTEXT_BYTES_SIZE
        return b

    def fingerprint(self):
        return hashlib.sha256(self.canonical_bytes()).digest()


# T1 mirrors the 36 distinct moves of the two teams of decision 0004, in that
# order, with the target classes of data/moves.ts at the pin.
T1 = [NORMAL, NORMAL, NORMAL, NORMAL, ANY, NORMAL, ALLY_SIDE, SELF, ALL_ADJ_FOES, SELF,
      NORMAL, NORMAL, NORMAL, NORMAL, SELF, NORMAL, NORMAL, ALL_ADJ_FOES, NORMAL, SELF,
      NORMAL, NORMAL, NORMAL, NORMAL, ANY, NORMAL, ALL_ADJ_FOES, NORMAL, NORMAL, ALL,
      ALL_ADJ_FOES, ANY, NORMAL, ALLY_SIDE, ALLY_SIDE, NORMAL]
assert len(T1) == 36
T2 = list(T1)
T2[35] = SELF
T4 = list(range(1, 10))

C1 = Context(1, 6, 4, 16, 36, T1)
C2 = Context(1, 6, 4, 16, 36, T2)
C3 = Context(1, 6, 1, 16, 36, T1)
C4 = Context(1, 4, 2, 8, 9, T4)

# CLOSURE contexts (decision 0006 section 2): the generated tables are built
# in. The canonical bytes carry their counts (16 formes, 37 moves) and, in
# place of the target-class table hash, the closure table hash, which
# tests/test_closure_tables.c recomputes from the canonical table bytes.
CLOSURE_TABLE_HASH = bytes.fromhex('86ca9d9f548042473c0980c496e9bd6bebbde4b3df0ed10a9ba25aa62316ef5c')
KIND_CLOSURE, KIND_CLOSURE_DEV = 2, 3


class ClosureContext(Context):
    def __init__(self, data_kind, max_roster, brought_count):
        Context.__init__(self, data_kind, max_roster, brought_count, 16, 37, b'')

    def valid(self):
        return (self.data_kind in (KIND_CLOSURE, KIND_CLOSURE_DEV) and 1 <= self.max_roster <= MAX_ROSTER
                and 1 <= self.brought_count <= self.max_roster)

    def canonical_bytes(self):
        b = MAGIC + struct.pack('<HHII', KIND_CONTEXT, SCHEMA, SEMANTICS, CONTEXT_BYTES_SIZE)
        b += bytes([2, 2, MAX_ROSTER, MOVE_SLOTS, self.data_kind, self.max_roster, self.brought_count])
        b += struct.pack('<HH', self.species_count, self.move_count)
        b += CLOSURE_TABLE_HASH
        assert len(b) == CONTEXT_BYTES_SIZE
        return b


K1 = ClosureContext(KIND_CLOSURE, 6, 4)
K2 = ClosureContext(KIND_CLOSURE_DEV, 6, 4)


# ---------------------------------------------------------------- state
def empty_member():
    return {'species': 0, 'hp': 0, 'hp_max': 0, 'stats': [0] * 5, 'move_count': 0, 'mega_capable': 0,
            'is_mega': 0, 'gender': 0, 'nature': 0, 'sp': [0] * 6, 'status': 0, 'status_counter': 0,
            'item': 0, 'item_consumed': 0, 'ability': 0,
            'moves': [{'id': 0, 'pp': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]}


def zero_cmd():
    return {'kind': 0, 'move_slot': 0, 'target': 0, 'mega': 0, 'reserve': 0}


def empty_pos():
    """The cleared position: no occupant, neutral stages, no volatile."""
    return {'occ': NONE, 'act': 0, 'stages': [STAGE_NEUTRAL] * STAGE_COUNT, 'flags': 0, 'stall_level': 0,
            'stall_turns': 0, 'confusion_turns': 0, 'charge_turns': 0, 'locked_move': 0, 'locked_target': 0,
            'move_actions': 0, 'switch_flag': 0}


def empty_know():
    return {'hp_pct': 0, 'hp_flag': 0, 'revealed': 0, 'used': [0] * MOVE_SLOTS}


def empty_side():
    return {'member_count': 0, 'brought': 0, 'requested_slots': 0, 'mega_used': 0, 'sealed': 0,
            'seen': 0, 'order': [NONE] * MAX_ROSTER, 'reflect': 0, 'light_screen': 0, 'tailwind': 0,
            'pos': [empty_pos(), empty_pos()],
            'sealed_cmds': [zero_cmd(), zero_cmd()],
            'know': [empty_know() for _ in range(MAX_ROSTER)],
            'members': [empty_member() for _ in range(MAX_ROSTER)]}


def empty_state(ctx):
    return {'fp': ctx.fingerprint(), 'rng_state': 0, 'rng_inc': 0, 'draws': 0, 'next': 1,
            'boundary': TEAM_SELECTION, 'request_mask': 3, 'epoch': 1, 'turn': 0, 'result': RESULT_NONE,
            'weather': 0, 'weather_turns': 0, 'terrain': 0, 'terrain_turns': 0, 'trick_room_turns': 0,
            'queue_len': 0, 'queue': [qrec(Q_NONE) for _ in range(QUEUE_CAP)],
            'sides': [empty_side(), empty_side()]}


def qrec(kind, side=0, slot=0, move_slot=0, target=0, reserve=0, act=0):
    return {'kind': kind, 'side': side, 'slot': slot, 'move_slot': move_slot, 'target': target,
            'reserve': reserve, 'act': act}


def see(st, side, roster):
    """The opponent of `side` records the HP display of member `roster`."""
    mem = st['sides'][side]['members'][roster]
    k = st['sides'][1 - side]['know'][roster]
    k['hp_pct'], k['hp_flag'] = hp_percent(mem['hp'], mem['hp_max'])


def place(st, side, slot, roster):
    sd = st['sides'][side]
    assert sd['pos'][slot]['occ'] == NONE
    assert roster < sd['member_count'] and (sd['brought'] >> roster) & 1
    assert sd['pos'][1 - slot]['occ'] != roster
    assert st['next'] != 0xFFFFFFFF
    sd['pos'][slot] = empty_pos()
    sd['pos'][slot]['occ'] = roster
    sd['pos'][slot]['act'] = st['next']
    st['next'] += 1
    st['sides'][1 - side]['seen'] |= 1 << roster
    see(st, side, roster)


def vacate(st, side, slot):
    """Leaving clears the position; the opponent keeps the last seen HP."""
    assert st['sides'][side]['pos'][slot]['occ'] != NONE
    st['sides'][side]['pos'][slot] = empty_pos()


def refresh_knowledge(st):
    """After a direct HP edit of an active member: what the opponent sees."""
    for side in range(2):
        for p in st['sides'][side]['pos']:
            if p['occ'] != NONE:
                see(st, side, p['occ'])


def occupied_mask(sd):
    return sum(1 << k for k in range(2) if sd['pos'][k]['occ'] != NONE)


def popcount(v):
    return bin(v).count('1')


# ---------------------------------------------------------------- setup
SETUP_FIELDS = []


def build_field_list():
    SETUP_FIELDS.append((None, None, None, 'rng_initstate'))
    SETUP_FIELDS.append((None, None, None, 'rng_initseq'))
    for s in range(2):
        SETUP_FIELDS.append((s, None, None, 'member_count'))
        for m in range(MAX_ROSTER):
            for name in ('species_id', 'hp_max', 'move_count', 'mega_capable'):
                SETUP_FIELDS.append((s, m, None, name))
            for k in range(MOVE_SLOTS):
                for name in ('move_id', 'pp_max'):
                    SETUP_FIELDS.append((s, m, k, name))


build_field_list()
assert len(SETUP_FIELDS) == 148


def setup_member(species, hp_max, moves, mega=0):
    mv = [{'move_id': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]
    for k, (mid, ppm) in enumerate(moves):
        mv[k] = {'move_id': mid, 'pp_max': ppm}
    return {'species_id': species, 'hp_max': hp_max, 'move_count': len(moves), 'mega_capable': mega, 'moves': mv}


def zero_setup_member():
    return setup_member(0, 0, [])


def setup_g1():
    """Rosters of M1's F1 plus synthetic Mega stones: side 0 members 1 and 3,
    side 1 member 0."""
    s0 = [setup_member(i + 1, 100 + 10 * i, [(4 * i + k, 5 + 5 * k) for k in range((i % 4) + 1)],
                       1 if i in (1, 3) else 0) for i in range(6)]
    s1 = [setup_member(10 + i, 200 + i, [(31 - (4 * i + k), 8 * (k + 1)) for k in range(4)],
                       1 if i == 0 else 0) for i in range(4)] + [zero_setup_member(), zero_setup_member()]
    return {'rng_initstate': 42, 'rng_initseq': 54,
            'sides': [{'member_count': 6, 'members': s0}, {'member_count': 4, 'members': s1}]}


def setup_g3():
    """Rosters of M1's F3 (C3, brought 1)."""
    s0 = [setup_member(i, 50 + i, [(i, 1)]) for i in range(3)] + [zero_setup_member()] * 3
    s1 = [setup_member(15 - i, 65535 - i, [(31, 255), (30, 1)]) for i in range(2)] + [zero_setup_member()] * 4
    return {'rng_initstate': 42, 'rng_initseq': 54,
            'sides': [{'member_count': 3, 'members': s0}, {'member_count': 2, 'members': s1}]}


def setup_g7():
    """Small exhaustive fixture on C4 (max_roster 4, brought 2, 8 species,
    9 moves = one of each target class). Side 0: 4 members, side 1: 3."""
    s0 = [setup_member(0, 30, [(NORMAL - 1, 2), (SELF - 1, 1)], 1),
          setup_member(1, 31, [(ANY - 1, 1)]),
          setup_member(2, 32, [(ADJ_ALLY - 1, 3), (ADJ_ALLY_OR_SELF - 1, 3), (ADJ_FOE - 1, 3), (ALL - 1, 3)], 1),
          setup_member(3, 33, [(ALL_ADJ_FOES - 1, 5), (ALLY_SIDE - 1, 5)])]
    s1 = [setup_member(4, 40, [(NORMAL - 1, 1), (ANY - 1, 1), (SELF - 1, 1)]),
          setup_member(5, 41, [(ADJ_FOE - 1, 2)], 1),
          setup_member(6, 42, [(ALL - 1, 1), (NORMAL - 1, 1)]),
          zero_setup_member()]
    return {'rng_initstate': 7, 'rng_initseq': 9,
            'sides': [{'member_count': 4, 'members': s0 + [zero_setup_member()] * 2},
                      {'member_count': 3, 'members': s1 + [zero_setup_member()] * 2}]}


def copy_setup(su):
    return {'rng_initstate': su['rng_initstate'], 'rng_initseq': su['rng_initseq'],
            'sides': [{'member_count': sd['member_count'],
                       'members': [dict(m, moves=[dict(mv) for mv in m['moves']]) for m in sd['members']]}
                      for sd in su['sides']]}


def set_field(su, field, value):
    side, m, k, name = field
    if side is None:
        su[name] = value
    elif m is None:
        su['sides'][side][name] = value
    elif k is None:
        su['sides'][side]['members'][m][name] = value
    else:
        su['sides'][side]['members'][m]['moves'][k][name] = value


def validate_setup(ctx, su):
    """Setup validation order (decision 0005 section 9).
    Returns True for OK, False for INVALID_ARGUMENT."""
    if su['rng_initseq'] >= (1 << 63):
        return False
    for sd in su['sides']:
        mc = sd['member_count']
        if not (ctx.brought_count <= mc <= ctx.max_roster):
            return False
        for m in range(MAX_ROSTER):
            mem = sd['members'][m]
            if m < mc:
                if mem['species_id'] >= ctx.species_count:
                    return False
                if not (1 <= mem['hp_max'] <= 65535):
                    return False
                if not (1 <= mem['move_count'] <= MOVE_SLOTS):
                    return False
                for k in range(MOVE_SLOTS):
                    mv = mem['moves'][k]
                    if k < mem['move_count']:
                        if mv['move_id'] >= ctx.move_count or not (1 <= mv['pp_max'] <= 255):
                            return False
                    elif mv['move_id'] != 0 or mv['pp_max'] != 0:
                        return False
                if mem['mega_capable'] > 1:
                    return False
            else:
                if (mem['species_id'] or mem['hp_max'] or mem['move_count'] or mem['mega_capable']
                        or any(x['move_id'] or x['pp_max'] for x in mem['moves'])):
                    return False
    return True


def init_state(ctx, su):
    assert validate_setup(ctx, su)
    st = empty_state(ctx)
    st['rng_state'], st['rng_inc'] = pcg_seed(su['rng_initstate'], su['rng_initseq'])
    for s, sd in enumerate(su['sides']):
        out = st['sides'][s]
        out['member_count'] = sd['member_count']
        for m in range(sd['member_count']):
            src = sd['members'][m]
            dst = out['members'][m]
            dst['species'] = src['species_id']
            dst['hp'] = dst['hp_max'] = src['hp_max']
            dst['move_count'] = src['move_count']
            dst['mega_capable'] = src['mega_capable']
            for k in range(src['move_count']):
                dst['moves'][k] = {'id': src['moves'][k]['move_id'], 'pp': src['moves'][k]['pp_max'],
                                   'pp_max': src['moves'][k]['pp_max']}
    assert check_state(ctx, st) == 'OK'
    return st


# ---------------------------------------------------------------- invariants
INVARIANTS = ['NONE', 'CONTEXT_FINGERPRINT', 'RNG_INC_EVEN', 'NEXT_ACTIVATION_ZERO', 'BOUNDARY_KIND',
              'EPOCH_ZERO', 'REQUEST_MASK', 'TURN_COUNTER', 'RESULT', 'FIELD', 'MEMBER_COUNT', 'SPECIES_RANGE',
              'HP_MAX_ZERO', 'HP_ABOVE_MAX', 'MOVE_COUNT', 'MOVE_ID_RANGE', 'PP_MAX_ZERO', 'PP_ABOVE_MAX',
              'UNUSED_MOVE_NONZERO', 'MEGA_CAPABLE_RANGE', 'MEMBER_EXTRA', 'UNUSED_MEMBER_NONZERO',
              'BROUGHT_OUT_OF_RANGE', 'BROUGHT_COUNT', 'BROUGHT_ORDER', 'MEGA_USED_RANGE', 'SIDE_CONDITION',
              'EMPTY_WITH_ACTIVATION', 'OCCUPIED_WITHOUT_ACTIVATION', 'OCCUPANT_RANGE', 'OCCUPANT_NOT_BROUGHT',
              'ACTIVATION_NOT_ISSUED', 'OCCUPANT_DUPLICATE', 'VOLATILE', 'REQUESTED_SLOTS', 'SWITCH_FLAG',
              'SEALED_RANGE',
              'SEALED_RULE', 'SEALED_COMMAND', 'ACTIVATION_DUPLICATE', 'SEEN_MASK', 'KNOWLEDGE', 'QUEUE']
assert len(INVARIANTS) == 43


def cmd_is_zero(c):
    return not (c['kind'] or c['move_slot'] or c['target'] or c['mega'] or c['reserve'])


def sealed_cmd_valid(c, mc):
    if c['kind'] == SLOT_MOVE:
        if c['move_slot'] == MOVE_SLOT_STRUGGLE:
            target_ok = c['target'] == TARGET_NONE
        else:
            target_ok = c['move_slot'] < MOVE_SLOTS and (c['target'] < 4 or c['target'] == TARGET_NONE)
        return target_ok and c['mega'] <= 1 and c['reserve'] == 0
    if c['kind'] == SLOT_SWITCH:
        return c['reserve'] < mc and not (c['move_slot'] or c['target'] or c['mega'])
    if c['kind'] in (SLOT_NONE, SLOT_PASS):
        return not (c['move_slot'] or c['target'] or c['mega'] or c['reserve'])
    return False


def member_extra_is_zero(mem):
    return not (any(mem['stats']) or mem['is_mega'] or mem['gender'] or mem['nature'] or any(mem['sp'])
                or mem['status'] or mem['status_counter'] or mem['item'] or mem['item_consumed']
                or mem['ability'])


def volatile_valid(p, move_count):
    """Value ranges of an occupied position's volatile block."""
    if p['switch_flag'] > SWITCH_EMERGENCY_EXIT:
        return False
    if any(s > STAGE_MAX for s in p['stages']) or p['flags'] > VOL_FLAGS_MAX:
        return False
    if p['stall_level'] > STALL_LEVEL_MAX or p['stall_turns'] > STALL_TURNS_MAX:
        return False
    if (p['stall_level'] == 0) != (p['stall_turns'] == 0):
        return False
    if p['confusion_turns'] > CONFUSION_TURNS_MAX or p['charge_turns'] > CHARGE_TURNS_MAX:
        return False
    if p['locked_move'] > move_count or (p['charge_turns'] == 0) != (p['locked_move'] == 0):
        return False
    if p['locked_move'] == 0:
        return p['locked_target'] == 0
    return p['locked_target'] < 4 or p['locked_target'] == TARGET_NONE


def check_side(ctx, st, s):
    sd = st['sides'][s]
    kind = st['boundary']
    requested = (st['request_mask'] >> s) & 1
    mc = sd['member_count']
    if not (ctx.brought_count <= mc <= ctx.max_roster):
        return 'MEMBER_COUNT'
    for m in range(MAX_ROSTER):
        mem = sd['members'][m]
        if m < mc:
            if mem['species'] >= ctx.species_count:
                return 'SPECIES_RANGE'
            if mem['hp_max'] == 0:
                return 'HP_MAX_ZERO'
            if mem['hp'] > mem['hp_max']:
                return 'HP_ABOVE_MAX'
            if not (1 <= mem['move_count'] <= MOVE_SLOTS):
                return 'MOVE_COUNT'
            for k in range(MOVE_SLOTS):
                mv = mem['moves'][k]
                if k < mem['move_count']:
                    if mv['id'] >= ctx.move_count:
                        return 'MOVE_ID_RANGE'
                    if mv['pp_max'] == 0:
                        return 'PP_MAX_ZERO'
                    if mv['pp'] > mv['pp_max']:
                        return 'PP_ABOVE_MAX'
                elif mv['id'] or mv['pp'] or mv['pp_max']:
                    return 'UNUSED_MOVE_NONZERO'
            if mem['mega_capable'] > 1:
                return 'MEGA_CAPABLE_RANGE'
            # SYNTHETIC data has no stats, natures, statuses, items or abilities.
            if not member_extra_is_zero(mem):
                return 'MEMBER_EXTRA'
        else:
            if (mem['species'] or mem['hp'] or mem['hp_max'] or mem['move_count'] or mem['mega_capable']
                    or any(x['id'] or x['pp'] or x['pp_max'] for x in mem['moves'])
                    or not member_extra_is_zero(mem)):
                return 'UNUSED_MEMBER_NONZERO'
    mask = sd['brought']
    if (mask >> mc) != 0:
        return 'BROUGHT_OUT_OF_RANGE'
    n = popcount(mask)
    if n != (0 if kind == TEAM_SELECTION else ctx.brought_count):
        return 'BROUGHT_COUNT'
    for i in range(MAX_ROSTER):
        o = sd['order'][i]
        if i < n:
            if o >= mc or not (mask >> o) & 1 or o in sd['order'][:i]:
                return 'BROUGHT_ORDER'
        elif o != NONE:
            return 'BROUGHT_ORDER'
    if sd['mega_used'] > 1:
        return 'MEGA_USED_RANGE'
    if (sd['reflect'] > SCREEN_TURNS_MAX or sd['light_screen'] > SCREEN_TURNS_MAX
            or sd['tailwind'] > TAILWIND_TURNS_MAX):
        return 'SIDE_CONDITION'
    for p in sd['pos']:
        if p['occ'] == NONE:
            if p['act'] != 0:
                return 'EMPTY_WITH_ACTIVATION'
            continue
        if p['act'] == 0:
            return 'OCCUPIED_WITHOUT_ACTIVATION'
        if p['occ'] >= mc:
            return 'OCCUPANT_RANGE'
        if not (mask >> p['occ']) & 1:
            return 'OCCUPANT_NOT_BROUGHT'
        if p['act'] >= st['next']:
            return 'ACTIVATION_NOT_ISSUED'
    if sd['pos'][0]['occ'] != NONE and sd['pos'][0]['occ'] == sd['pos'][1]['occ']:
        return 'OCCUPANT_DUPLICATE'
    for p in sd['pos']:
        if p['occ'] == NONE:
            if p != empty_pos():
                return 'VOLATILE'
        elif not volatile_valid(p, sd['members'][p['occ']]['move_count']):
            return 'VOLATILE'
    occ = occupied_mask(sd)
    rs = sd['requested_slots']
    if rs > 3:
        return 'REQUESTED_SLOTS'
    if not requested or kind == TEAM_SELECTION:
        if rs != 0:
            return 'REQUESTED_SLOTS'
    elif kind == TURN:
        if rs != occ:
            return 'REQUESTED_SLOTS'
    else:
        if rs == 0 or (rs & ~occ) != 0:
            return 'REQUESTED_SLOTS'
    # A switch flag marks exactly the requested slots of a PIVOT (the cause:
    # a self-switch move or Emergency Exit); it exists nowhere else.
    flagged = sum(1 << k for k in range(2) if sd['pos'][k]['switch_flag'] != 0)
    if flagged != (rs if kind == PIVOT and requested else 0):
        return 'SWITCH_FLAG'
    if sd['sealed'] > 1:
        return 'SEALED_RANGE'
    # A sealed choice exists only while the other side is re-prompted at TURN.
    if sd['sealed'] != (1 if kind == TURN and not requested else 0):
        return 'SEALED_RULE'
    for c in sd['sealed_cmds']:
        if sd['sealed'] == 0:
            if not cmd_is_zero(c):
                return 'SEALED_COMMAND'
        elif not sealed_cmd_valid(c, mc):
            return 'SEALED_COMMAND'
    return 'OK'


def hp_display_valid(pct, flag):
    if pct > 100:
        return False
    if pct == 20:
        return flag in (FLAG_RED, FLAG_YELLOW)
    if pct == 50:
        return flag in (FLAG_YELLOW, FLAG_GREEN)
    return flag == FLAG_NONE


def check_knowledge(st, p):
    """What player p remembers about the opposing members."""
    seen = st['sides'][p]['seen']
    opp = st['sides'][1 - p]
    active = [pos['occ'] for pos in opp['pos'] if pos['occ'] != NONE]
    for m in range(MAX_ROSTER):
        k = st['sides'][p]['know'][m]
        if not (seen >> m) & 1:
            if k != empty_know():
                return False
            continue
        mem = opp['members'][m]
        if not hp_display_valid(k['hp_pct'], k['hp_flag']):
            return False
        # Revealed facts are facts: a consumed item, a Mega forme.
        if k['revealed'] > REVEALED_ITEM_CONSUMED | REVEALED_MEGA:
            return False
        if k['revealed'] & REVEALED_ITEM_CONSUMED and mem['item_consumed'] != 1:
            return False
        if k['revealed'] & REVEALED_MEGA and mem['is_mega'] != 1:
            return False
        if any(k['used'][j] for j in range(mem['move_count'], MOVE_SLOTS)):
            return False
        if m in active and (k['hp_pct'], k['hp_flag']) != hp_percent(mem['hp'], mem['hp_max']):
            return False
    return True


def queue_record_valid(st, r):
    if r['kind'] < Q_SWITCH_IN or r['kind'] > Q_RESIDUAL or r['side'] > 1 or r['slot'] > 1:
        return False
    mc = st['sides'][r['side']]['member_count']
    bound = 1 <= r['act'] < st['next']
    plain = r['move_slot'] == 0 and r['target'] == 0
    if r['kind'] == Q_SWITCH_IN:
        return plain and r['act'] == 0 and r['reserve'] < mc
    if r['kind'] == Q_SWITCH:
        return plain and bound and r['reserve'] < mc
    if r['kind'] in (Q_RUN_SWITCH, Q_MEGA):
        return plain and bound and r['reserve'] == 0
    if r['kind'] == Q_MOVE:
        return (bound and r['reserve'] == 0 and r['move_slot'] <= MOVE_SLOT_STRUGGLE
                and (r['target'] < 4 or r['target'] == TARGET_NONE))
    return r == qrec(Q_RESIDUAL)


def check_queue(st):
    n = st['queue_len']
    if n > QUEUE_CAP or (st['boundary'] == PIVOT) != (n >= 1):
        return False
    for i in range(QUEUE_CAP):
        r = st['queue'][i]
        if i >= n:
            if r != qrec(Q_NONE):
                return False
        elif not queue_record_valid(st, r):
            return False
    return True


def check_state(ctx, st):
    """Invariant order (decisions 0005 section 9 and 0006 section 3); returns
    'OK' or the first violated invariant name."""
    if st['fp'] != ctx.fingerprint():
        return 'CONTEXT_FINGERPRINT'
    if st['rng_inc'] & 1 == 0:
        return 'RNG_INC_EVEN'
    if st['next'] == 0:
        return 'NEXT_ACTIVATION_ZERO'
    if not (1 <= st['boundary'] <= 5):
        return 'BOUNDARY_KIND'
    if st['epoch'] == 0:
        return 'EPOCH_ZERO'
    if st['boundary'] == TERMINAL:
        if st['request_mask'] != 0:
            return 'REQUEST_MASK'
    elif not (1 <= st['request_mask'] <= 3):
        return 'REQUEST_MASK'
    if (st['boundary'] == TEAM_SELECTION) != (st['turn'] == 0):
        return 'TURN_COUNTER'
    if st['result'] > RESULT_TIE or (st['boundary'] == TERMINAL) != (st['result'] != RESULT_NONE):
        return 'RESULT'
    if (st['weather'] > WEATHER_SUN or st['weather_turns'] > FIELD_TURNS_MAX
            or (st['weather'] == 0) != (st['weather_turns'] == 0)
            or st['terrain'] > TERRAIN_GRASSY or st['terrain_turns'] > FIELD_TURNS_MAX
            or (st['terrain'] == 0) != (st['terrain_turns'] == 0)
            or st['trick_room_turns'] > FIELD_TURNS_MAX):
        return 'FIELD'
    for s in range(2):
        r = check_side(ctx, st, s)
        if r != 'OK':
            return r
    acts = [p['act'] for sd in st['sides'] for p in sd['pos'] if p['occ'] != NONE]
    if len(acts) != len(set(acts)):
        return 'ACTIVATION_DUPLICATE'
    for p in range(2):
        seen = st['sides'][p]['seen']
        opp = st['sides'][1 - p]
        if (seen >> opp['member_count']) != 0 or (seen & ~opp['brought']) != 0:
            return 'SEEN_MASK'
        for pos in opp['pos']:
            if pos['occ'] != NONE and not (seen >> pos['occ']) & 1:
                return 'SEEN_MASK'
    for p in range(2):
        if not check_knowledge(st, p):
            return 'KNOWLEDGE'
    if not check_queue(st):
        return 'QUEUE'
    return 'OK'


# ---------------------------------------------------------------- codec
POS_BYTE_FIELDS = ['flags', 'stall_level', 'stall_turns', 'confusion_turns', 'charge_turns', 'locked_move',
                   'locked_target', 'move_actions', 'switch_flag']
MEMBER_HEAD_FIELDS = ['move_count', 'mega_capable', 'is_mega', 'gender', 'nature']
MEMBER_TAIL_FIELDS = ['status', 'status_counter', 'item', 'item_consumed', 'ability']
QUEUE_BYTE_FIELDS = ['kind', 'side', 'slot', 'move_slot', 'target', 'reserve']


def encode(st):
    b = bytearray(MAGIC + struct.pack('<HHII', KIND_BATTLE_STATE, SCHEMA, SEMANTICS, STATE_SIZE))
    b += st['fp']
    b += struct.pack('<QQQI', st['rng_state'], st['rng_inc'], st['draws'], st['next'])
    b += struct.pack('<BBIHB', st['boundary'], st['request_mask'], st['epoch'], st['turn'], st['result'])
    b += bytes([st['weather'], st['weather_turns'], st['terrain'], st['terrain_turns'], st['trick_room_turns'],
                st['queue_len']])
    assert len(b) == QUEUE_OFF
    for r in st['queue']:
        b += bytes([r[f] for f in QUEUE_BYTE_FIELDS]) + struct.pack('<I', r['act'])
    assert len(b) == HEADER_SIZE
    for sd in st['sides']:
        b += bytes([sd['member_count'], sd['brought'], sd['requested_slots'], sd['mega_used'], sd['sealed'],
                    sd['seen']])
        b += bytes(sd['order'])
        b += bytes([sd['reflect'], sd['light_screen'], sd['tailwind']])
        for p in sd['pos']:
            b += bytes([p['occ']]) + struct.pack('<I', p['act']) + bytes(p['stages'])
            b += bytes([p[f] for f in POS_BYTE_FIELDS])
        for c in sd['sealed_cmds']:
            b += bytes([c['kind'], c['move_slot'], c['target'], c['mega'], c['reserve']])
        for k in sd['know']:
            b += bytes([k['hp_pct'], k['hp_flag'], k['revealed']] + k['used'])
        for mem in sd['members']:
            b += struct.pack('<HHH5H', mem['species'], mem['hp'], mem['hp_max'], *mem['stats'])
            b += bytes([mem[f] for f in MEMBER_HEAD_FIELDS] + mem['sp'] + [mem[f] for f in MEMBER_TAIL_FIELDS])
            for mv in mem['moves']:
                b += struct.pack('<HBB', mv['id'], mv['pp'], mv['pp_max'])
    assert len(b) == STATE_SIZE
    return bytes(b)


def parse(b):
    st = {'fp': bytes(b[20:52])}
    st['rng_state'], st['rng_inc'], st['draws'], st['next'] = struct.unpack_from('<QQQI', b, 52)
    st['boundary'], st['request_mask'], st['epoch'], st['turn'], st['result'] = struct.unpack_from('<BBIHB', b, 80)
    (st['weather'], st['weather_turns'], st['terrain'], st['terrain_turns'], st['trick_room_turns'],
     st['queue_len']) = b[89:95]
    st['queue'] = []
    for i in range(QUEUE_CAP):
        o = QUEUE_OFF + QUEUE_REC_SIZE * i
        r = {f: b[o + j] for j, f in enumerate(QUEUE_BYTE_FIELDS)}
        r['act'] = struct.unpack_from('<I', b, o + 6)[0]
        st['queue'].append(r)
    st['sides'] = []
    for s in range(2):
        o = HEADER_SIZE + SIDE_SIZE * s
        sd = {'member_count': b[o], 'brought': b[o + 1], 'requested_slots': b[o + 2], 'mega_used': b[o + 3],
              'sealed': b[o + 4], 'seen': b[o + 5], 'order': list(b[o + 6:o + 12]), 'reflect': b[o + 12],
              'light_screen': b[o + 13], 'tailwind': b[o + 14], 'pos': [], 'sealed_cmds': [], 'know': [],
              'members': []}
        for k in range(2):
            po = o + SIDE_POS_OFF + POS_SIZE * k
            p = {'occ': b[po], 'act': struct.unpack_from('<I', b, po + 1)[0], 'stages': list(b[po + 5:po + 12])}
            for j, f in enumerate(POS_BYTE_FIELDS):
                p[f] = b[po + 12 + j]
            sd['pos'].append(p)
        for c in range(2):
            co = o + SIDE_SEALED_OFF + 5 * c
            sd['sealed_cmds'].append({'kind': b[co], 'move_slot': b[co + 1], 'target': b[co + 2],
                                      'mega': b[co + 3], 'reserve': b[co + 4]})
        for m in range(MAX_ROSTER):
            ko = o + SIDE_KNOW_OFF + KNOW_SIZE * m
            sd['know'].append({'hp_pct': b[ko], 'hp_flag': b[ko + 1], 'revealed': b[ko + 2],
                               'used': list(b[ko + 3:ko + 7])})
        for m in range(MAX_ROSTER):
            mo = o + SIDE_MEMBERS_OFF + MEMBER_SIZE * m
            vals = struct.unpack_from('<HHH5H', b, mo)
            mem = {'species': vals[0], 'hp': vals[1], 'hp_max': vals[2], 'stats': list(vals[3:8]),
                   'sp': list(b[mo + 21:mo + 27]), 'moves': []}
            for j, f in enumerate(MEMBER_HEAD_FIELDS):
                mem[f] = b[mo + 16 + j]
            for j, f in enumerate(MEMBER_TAIL_FIELDS):
                mem[f] = b[mo + 27 + j]
            for k in range(MOVE_SLOTS):
                mid, pp, ppm = struct.unpack_from('<HBB', b, mo + 32 + 4 * k)
                mem['moves'].append({'id': mid, 'pp': pp, 'pp_max': ppm})
            sd['members'].append(mem)
        st['sides'].append(sd)
    return st


def decode(ctx, b):
    """Strict decode order (decision 0002 section 6, sizes of v3); returns
    (status, invariant-or-None)."""
    size = len(b)
    if size < 20:
        return 'MALFORMED', None
    if bytes(b[0:8]) != MAGIC:
        return 'MALFORMED', None
    kind, schema, semantics, total = struct.unpack_from('<HHII', b, 8)
    if kind != KIND_BATTLE_STATE or schema != SCHEMA:
        return 'SCHEMA_MISMATCH', None
    if semantics != SEMANTICS:
        return 'SEMANTICS_MISMATCH', None
    if total != size:
        return 'MALFORMED', None
    if size != STATE_SIZE:
        return 'MALFORMED', None
    if bytes(b[20:52]) != ctx.fingerprint():
        return 'CONTEXT_MISMATCH', None
    st = parse(b)
    inv = check_state(ctx, st)
    if inv != 'OK':
        return 'MALFORMED', inv
    assert encode(st) == bytes(b)
    return 'OK', None


# ---------------------------------------------------------------- transitions
def team_domain(mc, bc):
    return list(itertools.permutations(range(mc), bc))


def apply_team_selection(ctx, st, picks):
    """The mechanics-free TEAM_SELECTION -> TURN transition."""
    assert st['boundary'] == TEAM_SELECTION and st['epoch'] < 0xFFFFFFFF
    for s in range(2):
        sd = st['sides'][s]
        assert picks[s] in team_domain(sd['member_count'], ctx.brought_count)
        sd['brought'] = sum(1 << r for r in picks[s])
        sd['order'] = list(picks[s]) + [NONE] * (MAX_ROSTER - len(picks[s]))
    for s in range(2):
        for slot in range(min(2, ctx.brought_count)):
            place(st, s, slot, picks[s][slot])
    for s in range(2):
        st['sides'][s]['requested_slots'] = occupied_mask(st['sides'][s])
    st['boundary'] = TURN
    st['request_mask'] = 3
    st['epoch'] += 1
    st['turn'] = 1
    assert check_state(ctx, st) == 'OK'


# ---------------------------------------------------------------- domains
def selectable_targets(cls, side, slot):
    me = 2 * side + slot
    ally = 2 * side + (1 - slot)
    foes = [2 * (1 - side), 2 * (1 - side) + 1]
    if cls in (NORMAL, ANY):
        return sorted([ally] + foes)
    if cls == ADJ_ALLY:
        return [ally]
    if cls == ADJ_ALLY_OR_SELF:
        return sorted([me, ally])
    if cls == ADJ_FOE:
        return foes
    return [TARGET_NONE]


def cmd(kind, move_slot=0, target=0, mega=0, reserve=0):
    return {'kind': kind, 'move_slot': move_slot, 'target': target, 'mega': mega, 'reserve': reserve}


def reserves(sd):
    active = {p['occ'] for p in sd['pos'] if p['occ'] != NONE}
    return [r for r in range(sd['member_count'])
            if (sd['brought'] >> r) & 1 and r not in active and sd['members'][r]['hp'] > 0]


def slot_domain(ctx, st, side, slot):
    """Per-slot candidates in documented order; Struggle (move slot 4, no
    target) when the occupant has no move with PP left."""
    sd = st['sides'][side]
    pos = sd['pos'][slot]
    out = []
    if st['boundary'] == TURN:
        if pos['occ'] == NONE or sd['members'][pos['occ']]['hp'] == 0:
            return [cmd(SLOT_PASS)]
        mem = sd['members'][pos['occ']]
        megas = [0, 1] if mem['mega_capable'] and not sd['mega_used'] else [0]
        for k in range(mem['move_count']):
            mv = mem['moves'][k]
            if mv['pp'] == 0:
                continue
            # Champions disables Fake Out (closure move 2) after a move action.
            if ctx.data_kind in (KIND_CLOSURE, KIND_CLOSURE_DEV) and mv['id'] == 2 and pos['move_actions'] != 0:
                continue
            for tgt in selectable_targets(ctx.table[mv['id']], side, slot):
                for mg in megas:
                    out.append(cmd(SLOT_MOVE, k, tgt, mg))
        if not out:
            for mg in megas:
                out.append(cmd(SLOT_MOVE, MOVE_SLOT_STRUGGLE, TARGET_NONE, mg))
        for r in reserves(sd):
            out.append(cmd(SLOT_SWITCH, reserve=r))
        return out
    for r in reserves(sd):
        out.append(cmd(SLOT_SWITCH, reserve=r))
    return out


def side_domain(ctx, st, side):
    """Complete joint side choices in documented order: slot a outer, slot b
    inner; drops same-reserve pairs and double Mega; at REPLACEMENT/PIVOT
    exactly min(requested, reserves) slots switch and the rest PASS."""
    sd = st['sides'][side]
    rs = sd['requested_slots']
    slots = [k for k in range(2) if (rs >> k) & 1]
    doms = []
    for k in range(2):
        if k in slots:
            d = slot_domain(ctx, st, side, k)
            if d == 'UNSUPPORTED':
                return 'UNSUPPORTED'
            if st['boundary'] != TURN:
                d = d + [cmd(SLOT_PASS)]
            doms.append(d)
        else:
            doms.append([cmd(SLOT_NONE)])
    need = None
    if st['boundary'] != TURN:
        need = min(len(slots), len(reserves(sd)))
    out = []
    for a in doms[0]:
        for b in doms[1]:
            if a['kind'] == SLOT_SWITCH and b['kind'] == SLOT_SWITCH and a['reserve'] == b['reserve']:
                continue
            if a['kind'] == SLOT_MOVE and b['kind'] == SLOT_MOVE and a['mega'] and b['mega']:
                continue
            if need is not None and sum(1 for c in (a, b) if c['kind'] == SLOT_SWITCH) != need:
                continue
            out.append((a, b))
    return out


def side_choice_bytes(epoch, side, kind, picks=(), slots=None):
    p = list(picks) + [0] * (MAX_ROSTER - len(picks))
    b = struct.pack('<IBBB', epoch, side, kind, len(picks)) + bytes(p) + bytes(3)
    for c in (slots or (zero_cmd(), zero_cmd())):
        b += bytes([c['kind'], c['move_slot'], c['target'], c['mega'], c['reserve'], 0, 0, 0])
    assert len(b) == 32
    return b


def candidates(ctx, st, player):
    """Returns (request tuple, [candidate bytes]) or ('UNSUPPORTED', None).
    request = (epoch, boundary, requested, slot_mask, count)."""
    sd = st['sides'][player]
    requested = (st['request_mask'] >> player) & 1
    if not requested:
        return (st['epoch'], st['boundary'], 0, 0, 0), []
    if st['boundary'] == TEAM_SELECTION:
        cands = [side_choice_bytes(st['epoch'], player, CHOICE_TEAM_SELECTION, picks=t)
                 for t in team_domain(sd['member_count'], ctx.brought_count)]
    else:
        dom = side_domain(ctx, st, player)
        if dom == 'UNSUPPORTED':
            return 'UNSUPPORTED', None
        cands = [side_choice_bytes(st['epoch'], player, CHOICE_SLOTS, slots=pair) for pair in dom]
    return (st['epoch'], st['boundary'], 1, sd['requested_slots'], len(cands)), cands



# ---------------------------------------------------------------- observation
HP_EXACT, HP_PERCENT, HP_UNKNOWN = 1, 2, 3
PP_EXACT, PP_UNKNOWN = 1, 3
FLAG_NONE, FLAG_RED, FLAG_YELLOW, FLAG_GREEN = 0, 1, 2, 3
LOC_UNDETERMINED, LOC_BENCH, LOC_ACTIVE, LOC_NOT_BROUGHT = 0, 1, 2, 3
OBSERVATION_SIZE = 320


def hp_percent(hp, hp_max):
    """Champions HP display: floor percent, minimum 1 while alive, colour
    flag at exactly 20 and 50 (sim/pokemon.ts:2060-2073 at the pin)."""
    if hp == 0:
        return 0, FLAG_NONE
    pct = (100 * hp) // hp_max
    if pct == 0:
        pct = 1
    flag = FLAG_NONE
    if pct == 20:
        flag = FLAG_YELLOW if hp * 5 > hp_max else FLAG_RED
    elif pct == 50:
        flag = FLAG_GREEN if hp * 2 > hp_max else FLAG_YELLOW
    return pct, flag


def observe(ctx, st, player):
    """Perspective-safe observation of `player` (decision 0005 section 6):
    320 bytes, absolute side order. The HP of an opposing member comes from
    the player's knowledge (decision 0006 section 6), never from the member."""
    requested = (st['request_mask'] >> player) & 1
    b = bytearray(struct.pack('<IBBBB', st['epoch'], st['boundary'], player, requested,
                              st['sides'][player]['requested_slots'] if requested else 0))
    for s in range(2):
        sd = st['sides'][s]
        own = s == player
        seen = st['sides'][player]['seen']
        occupants = [p['occ'] for p in sd['pos']]
        for m in range(MAX_ROSTER):
            mem = sd['members'][m]
            registered = m < sd['member_count']
            if not registered:
                b += bytes(24)
                continue
            if own:
                hp, hp_max, hp_kind, flag = mem['hp'], mem['hp_max'], HP_EXACT, FLAG_NONE
                pp = [mv['pp'] for mv in mem['moves']]
                pp_kind = PP_EXACT
                if st['boundary'] == TEAM_SELECTION:
                    loc = LOC_UNDETERMINED
                elif m in occupants:
                    loc = LOC_ACTIVE
                elif (sd['brought'] >> m) & 1:
                    loc = LOC_BENCH
                else:
                    loc = LOC_NOT_BROUGHT
            else:
                pp = [0, 0, 0, 0]
                pp_kind = PP_UNKNOWN
                if (seen >> m) & 1:
                    know = st['sides'][player]['know'][m]
                    hp, hp_max, hp_kind, flag = know['hp_pct'], 100, HP_PERCENT, know['hp_flag']
                    loc = LOC_ACTIVE if m in occupants else LOC_BENCH
                else:
                    hp, hp_max, hp_kind, flag = 0, 0, HP_UNKNOWN, FLAG_NONE
                    loc = LOC_UNDETERMINED
            b += struct.pack('<HHH', mem['species'], hp, hp_max)
            b += struct.pack('<HHHH', *[mv['id'] for mv in mem['moves']])
            b += bytes(pp)
            b += bytes([mem['move_count'], hp_kind, flag, pp_kind, loc, mem['mega_capable']])
        b += bytes([sd['member_count'], occupants[0], occupants[1], sd['mega_used']])
        b += bytes(sd['order'] if own else [NONE] * MAX_ROSTER)
        b += bytes(2)
    assert len(b) == OBSERVATION_SIZE
    return bytes(b)


# ---------------------------------------------------------------- fixtures
def fixture_g1():
    return init_state(C1, setup_g1())


def fixture_f1():
    st = fixture_g1()
    apply_team_selection(C1, st, [(2, 0, 1, 3), (1, 3, 0, 2)])
    return st


def fixture_f2():
    """F1 after 16 draws; s0a (roster 2) left at 24 of 120 HP and roster 3
    entered; s1b left. Roster 2 then changes on the bench, which the opponent
    does not see: its knowledge stays at 20 percent, red."""
    st = fixture_f1()
    for _ in range(16):
        pcg_next(st)
    s0, s1 = st['sides']
    s0['members'][2]['hp'] = 24
    refresh_knowledge(st)
    vacate(st, 0, 0)
    place(st, 0, 0, 3)
    vacate(st, 1, 1)
    s1['requested_slots'] = 1
    s0['members'][2]['hp'] = 40
    s0['members'][0]['hp'] = 0
    s0['members'][1]['hp'] = 57
    s0['members'][1]['moves'][0]['pp'] = 0
    s1['members'][2]['hp'] = 0
    s1['members'][0]['moves'][3]['pp'] = 7
    s0['mega_used'] = 1
    refresh_knowledge(st)
    assert check_state(C1, st) == 'OK'
    return st


def fixture_g3():
    return init_state(C3, setup_g3())


def fixture_f3():
    st = fixture_g3()
    apply_team_selection(C3, st, [(2,), (0,)])
    return st


def fixture_f4():
    """Two-side REPLACEMENT: s0a (roster 2) and s1b (roster 3) fainted."""
    st = fixture_f1()
    st['sides'][0]['members'][2]['hp'] = 0
    st['sides'][1]['members'][3]['hp'] = 0
    refresh_knowledge(st)
    st['boundary'] = REPLACEMENT
    st['epoch'] = 3
    st['request_mask'] = 3
    st['sides'][0]['requested_slots'] = 1
    st['sides'][1]['requested_slots'] = 2
    assert check_state(C1, st) == 'OK'
    return st


def set_queue(st, records):
    st['queue_len'] = len(records)
    st['queue'] = list(records) + [qrec(Q_NONE) for _ in range(QUEUE_CAP - len(records))]


def fixture_f5():
    """One-side PIVOT (side 0, slot a) in turn 7 with every v3 group in use:
    field and side conditions, volatile blocks, knowledge and a queue."""
    st = fixture_f1()
    st['boundary'] = PIVOT
    st['epoch'] = 3
    st['request_mask'] = 1
    st['turn'] = 7
    s0, s1 = st['sides']
    s0['requested_slots'] = 1
    s1['requested_slots'] = 0
    st['weather'], st['weather_turns'] = WEATHER_RAIN, 3
    st['terrain'], st['terrain_turns'] = TERRAIN_GRASSY, 5
    st['trick_room_turns'] = 2
    s0['reflect'], s0['tailwind'] = 8, 1
    s1['light_screen'], s1['tailwind'] = 4, 3
    s0['pos'][0].update(stages=[0, 6, 12, 6, 7, 6, 5], move_actions=3)
    s0['pos'][1].update(flags=VOL_PROTECT | VOL_FLASH_FIRE, stall_level=2, stall_turns=1, move_actions=1)
    s1['pos'][0].update(confusion_turns=4, charge_turns=1, locked_move=3, locked_target=0, move_actions=255)
    s1['pos'][1].update(stages=[6, 6, 6, 6, 6, 5, 8], flags=VOL_FLINCH, charge_turns=2, locked_move=1,
                        locked_target=TARGET_NONE)
    s0['pos'][0]['switch_flag'] = SWITCH_MOVE  # Parting Shot
    s1['members'][1]['hp'] = 101
    refresh_knowledge(st)
    s0['know'][1]['used'] = [2, 0, 1, 0]
    s0['know'][3]['used'] = [0, 0, 0, 255]
    s1['know'][2]['used'] = [1, 1, 0, 0]
    s1['know'][0]['used'] = [9, 0, 0, 0]
    set_queue(st, [qrec(Q_MOVE, 1, 0, move_slot=2, target=0, act=3),
                   qrec(Q_MOVE, 1, 1, move_slot=MOVE_SLOT_STRUGGLE, target=TARGET_NONE, act=4),
                   qrec(Q_RESIDUAL)])
    assert check_state(C1, st) == 'OK'
    return st


def fixture_f6():
    """Two-side PIVOT (s0a and s1b) with one queue record of every kind."""
    st = fixture_f5()
    st['request_mask'] = 3
    st['sides'][1]['requested_slots'] = 2
    st['sides'][1]['pos'][1]['switch_flag'] = SWITCH_EMERGENCY_EXIT
    set_queue(st, [qrec(Q_SWITCH_IN, 0, 0, reserve=5), qrec(Q_RUN_SWITCH, 0, 1, act=2),
                   qrec(Q_SWITCH, 1, 0, reserve=0, act=3), qrec(Q_MEGA, 0, 1, act=2),
                   qrec(Q_MOVE, 1, 1, move_slot=0, target=1, act=4), qrec(Q_RESIDUAL)])
    assert check_state(C1, st) == 'OK'
    return st


def fixture_g7():
    return init_state(C4, setup_g7())


def fixture_f8():
    st = fixture_g7()
    apply_team_selection(C4, st, [(1, 3), (2, 0)])
    return st


def fixture_f9():
    """F8 variants: side 0 leads 0 and 2 (Mega holders), side 1 leads 1 and 2."""
    st = fixture_g7()
    apply_team_selection(C4, st, [(0, 2), (1, 2)])
    return st


def fixture_f10():
    """F9 with side 1 slot b fainted (forced PASS) and side 0 Mega used."""
    st = fixture_f9()
    st['sides'][1]['members'][2]['hp'] = 0
    st['sides'][0]['mega_used'] = 1
    refresh_knowledge(st)
    assert check_state(C4, st) == 'OK'
    return st


def fixture_f11():
    """F9 at REPLACEMENT with both side 0 slots requested but only one reserve."""
    st = fixture_f9()
    st['boundary'] = REPLACEMENT
    st['epoch'] = 3
    st['request_mask'] = 1
    st['sides'][0]['members'][0]['hp'] = 0
    st['sides'][0]['members'][2]['hp'] = 0
    st['sides'][0]['requested_slots'] = 3
    st['sides'][1]['requested_slots'] = 0
    refresh_knowledge(st)
    assert check_state(C4, st) == 'OK'
    return st


def fixture_f12():
    """F9 with side 0 slot a alive but every move at pp 0 (Struggle offered)."""
    st = fixture_f9()
    for mv in st['sides'][0]['members'][0]['moves'][:2]:
        mv['pp'] = 0
    assert check_state(C4, st) == 'OK'
    return st


def fixture_f13():
    """F9 at TERMINAL in turn 12: both brought members of side 1 fainted,
    side 0 has won. Nobody is requested."""
    st = fixture_f9()
    st['sides'][1]['members'][1]['hp'] = 0
    st['sides'][1]['members'][2]['hp'] = 0
    refresh_knowledge(st)
    st['boundary'] = TERMINAL
    st['epoch'] = 3
    st['request_mask'] = 0
    st['turn'] = 12
    st['result'] = RESULT_SIDE0
    st['sides'][0]['requested_slots'] = 0
    st['sides'][1]['requested_slots'] = 0
    assert check_state(C4, st) == 'OK'
    return st


FIXTURES = [('G1', C1, fixture_g1), ('F1', C1, fixture_f1), ('F2', C1, fixture_f2), ('G3', C3, fixture_g3),
            ('F3', C3, fixture_f3), ('F4', C1, fixture_f4), ('F5', C1, fixture_f5), ('F6', C1, fixture_f6),
            ('G7', C4, fixture_g7), ('F8', C4, fixture_f8), ('F9', C4, fixture_f9), ('F10', C4, fixture_f10),
            ('F11', C4, fixture_f11), ('F12', C4, fixture_f12), ('F13', C4, fixture_f13)]

S0, S1 = HEADER_SIZE, HEADER_SIZE + SIDE_SIZE
REGIONS = [('magic', 0, 8), ('kind', 8, 10), ('schema', 10, 12), ('semantics', 12, 16), ('total_length', 16, 20),
           ('fingerprint', 20, 52), ('rng.state', 52, 60), ('rng.inc', 60, 68), ('rng.draws', 68, 76),
           ('next_activation', 76, 80), ('boundary', 80, 86), ('turn_result', 86, 89), ('field', 89, 94),
           ('queue', 94, 215)]
for _name, _base in (('side0', S0), ('side1', S1)):
    REGIONS += [(_name + '.header', _base, _base + SIDE_POS_OFF),
                (_name + '.positions', _base + SIDE_POS_OFF, _base + SIDE_SEALED_OFF),
                (_name + '.sealed', _base + SIDE_SEALED_OFF, _base + SIDE_KNOW_OFF),
                (_name + '.knowledge', _base + SIDE_KNOW_OFF, _base + SIDE_MEMBERS_OFF),
                (_name + '.members', _base + SIDE_MEMBERS_OFF, _base + SIDE_SIZE)]
assert REGIONS[-1][2] == STATE_SIZE and len(REGIONS) == 24
STATUS_COLUMNS = ['OK', 'MALFORMED', 'CONTEXT_MISMATCH', 'SCHEMA_MISMATCH', 'SEMANTICS_MISMATCH']


def mutation_counts(ctx, golden):
    counts = {}
    for name, lo, hi in REGIONS:
        c = {}
        for off in range(lo, hi):
            for v in range(256):
                if v == golden[off]:
                    continue
                b = bytearray(golden)
                b[off] = v
                status, _ = decode(ctx, b)
                c[status] = c.get(status, 0) + 1
        counts[name] = c
    return counts


V32 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 31, 32, 33, 63, 255, 256, 257, 258, 261, 262, 511, 65535, 65536,
       65552, 65636, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
V64 = V32 + [0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF]


def setup_sweep(ctx, base):
    classes = {}
    for field in SETUP_FIELDS:
        side, m, k, name = field
        values = V64 if side is None else V32
        cls = ('battle', name) if side is None else (side, name)
        ok = bad = 0
        for v in values:
            su = copy_setup(base)
            set_field(su, field, v)
            if validate_setup(ctx, su):
                ok += 1
            else:
                bad += 1
        prev = classes.get(cls, (0, 0))
        classes[cls] = (prev[0] + ok, prev[1] + bad)
    return classes


# Targeted single-byte edits per invariant id that one byte can trigger
# (offsets from the v3 layout; S0 = 215 and S1 = 612 are the side blocks;
# P, K and M give side-relative offsets of positions, knowledge and members).
# Each row: fixture, offset, value, expected first invariant.
def P(k, f):
    return SIDE_POS_OFF + POS_SIZE * k + f


def K(m, f):
    return SIDE_KNOW_OFF + KNOW_SIZE * m + f


def M(m, f):
    return SIDE_MEMBERS_OFF + MEMBER_SIZE * m + f


TARGETED = [
    ('F1', 60, 0x6C, 'RNG_INC_EVEN'), ('F1', 76, 0, 'NEXT_ACTIVATION_ZERO'), ('F1', 80, 0, 'BOUNDARY_KIND'),
    ('F1', 80, 6, 'BOUNDARY_KIND'), ('F1', 82, 0, 'EPOCH_ZERO'), ('F1', 81, 0, 'REQUEST_MASK'),
    ('F1', 81, 4, 'REQUEST_MASK'), ('F1', 80, 5, 'REQUEST_MASK'), ('F13', 81, 1, 'REQUEST_MASK'),
    ('F1', 86, 0, 'TURN_COUNTER'), ('G1', 86, 1, 'TURN_COUNTER'), ('F1', 88, 1, 'RESULT'),
    ('F1', 88, 4, 'RESULT'), ('F13', 88, 0, 'RESULT'), ('F13', 88, 4, 'RESULT'),
    ('F1', 89, 1, 'FIELD'), ('F1', 89, 3, 'FIELD'), ('F1', 90, 1, 'FIELD'), ('F5', 90, 6, 'FIELD'),
    ('F1', 91, 1, 'FIELD'), ('F1', 92, 1, 'FIELD'), ('F5', 91, 2, 'FIELD'), ('F5', 92, 0, 'FIELD'),
    ('F1', 93, 6, 'FIELD'),
    ('F1', S0 + 0, 3, 'MEMBER_COUNT'), ('F1', S0 + 0, 7, 'MEMBER_COUNT'),
    ('F1', S0 + M(0, 0), 16, 'SPECIES_RANGE'), ('F1', S0 + M(0, 4), 0, 'HP_MAX_ZERO'),
    ('F1', S0 + M(0, 2), 101, 'HP_ABOVE_MAX'), ('F1', S0 + M(0, 16), 0, 'MOVE_COUNT'),
    ('F1', S0 + M(0, 16), 5, 'MOVE_COUNT'), ('F1', S0 + M(0, 32), 36, 'MOVE_ID_RANGE'),
    ('F1', S0 + M(0, 35), 0, 'PP_MAX_ZERO'), ('F1', S0 + M(0, 34), 6, 'PP_ABOVE_MAX'),
    ('F1', S0 + M(0, 36), 1, 'UNUSED_MOVE_NONZERO'), ('F1', S0 + M(0, 17), 2, 'MEGA_CAPABLE_RANGE'),
    ('F1', S0 + M(0, 6), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 15), 1, 'MEMBER_EXTRA'),
    ('F1', S0 + M(0, 18), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 19), 1, 'MEMBER_EXTRA'),
    ('F1', S0 + M(0, 20), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 21), 1, 'MEMBER_EXTRA'),
    ('F1', S0 + M(0, 26), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 27), 1, 'MEMBER_EXTRA'),
    ('F1', S0 + M(0, 28), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 29), 1, 'MEMBER_EXTRA'),
    ('F1', S0 + M(0, 30), 1, 'MEMBER_EXTRA'), ('F1', S0 + M(0, 31), 1, 'MEMBER_EXTRA'),
    ('F1', S1 + M(4, 0), 1, 'UNUSED_MEMBER_NONZERO'), ('F1', S1 + M(5, 29), 1, 'UNUSED_MEMBER_NONZERO'),
    ('F1', S1 + 1, 0x17, 'BROUGHT_OUT_OF_RANGE'), ('F1', S0 + 1, 0x07, 'BROUGHT_COUNT'),
    ('F1', S0 + 6, 5, 'BROUGHT_ORDER'), ('F1', S0 + 9, 0xFF, 'BROUGHT_ORDER'), ('F1', S0 + 10, 0, 'BROUGHT_ORDER'),
    ('F1', S0 + 3, 2, 'MEGA_USED_RANGE'),
    ('F1', S0 + 12, 9, 'SIDE_CONDITION'), ('F1', S0 + 13, 9, 'SIDE_CONDITION'), ('F1', S0 + 14, 5, 'SIDE_CONDITION'),
    ('F1', S0 + P(0, 0), 0xFF, 'EMPTY_WITH_ACTIVATION'), ('F1', S1 + P(1, 1), 0, 'OCCUPIED_WITHOUT_ACTIVATION'),
    ('F1', S1 + P(0, 0), 4, 'OCCUPANT_RANGE'), ('F1', S0 + P(0, 0), 4, 'OCCUPANT_NOT_BROUGHT'),
    ('F1', S0 + P(0, 1), 5, 'ACTIVATION_NOT_ISSUED'), ('F1', S0 + P(1, 0), 2, 'OCCUPANT_DUPLICATE'),
    ('F1', S0 + P(0, 5), 13, 'VOLATILE'), ('F1', S0 + P(0, 12), 8, 'VOLATILE'), ('F1', S0 + P(0, 13), 1, 'VOLATILE'),
    ('F1', S0 + P(0, 13), 7, 'VOLATILE'), ('F1', S0 + P(0, 14), 1, 'VOLATILE'), ('F5', S0 + P(1, 14), 3, 'VOLATILE'),
    ('F1', S0 + P(0, 15), 6, 'VOLATILE'), ('F1', S0 + P(0, 16), 1, 'VOLATILE'), ('F5', S1 + P(0, 16), 3, 'VOLATILE'),
    ('F1', S0 + P(0, 17), 1, 'VOLATILE'), ('F5', S1 + P(0, 17), 5, 'VOLATILE'), ('F1', S0 + P(0, 18), 1, 'VOLATILE'),
    ('F5', S1 + P(0, 18), 4, 'VOLATILE'), ('F5', S0 + P(1, 17), 2, 'VOLATILE'), ('F1', S0 + P(0, 20), 3, 'VOLATILE'),
    ('F2', S1 + P(1, 5), 5, 'VOLATILE'), ('F2', S1 + P(1, 12), 1, 'VOLATILE'), ('F2', S1 + P(1, 19), 1, 'VOLATILE'),
    ('F2', S1 + P(1, 20), 1, 'VOLATILE'),
    ('F1', S0 + 2, 1, 'REQUESTED_SLOTS'), ('F1', S0 + 2, 4, 'REQUESTED_SLOTS'), ('F13', S0 + 2, 1, 'REQUESTED_SLOTS'),
    ('F1', S0 + P(0, 20), 1, 'SWITCH_FLAG'), ('F5', S0 + P(0, 20), 0, 'SWITCH_FLAG'),
    ('F5', S0 + P(1, 20), 1, 'SWITCH_FLAG'), ('F5', S1 + P(0, 20), 2, 'SWITCH_FLAG'),
    ('F6', S1 + P(1, 20), 0, 'SWITCH_FLAG'), ('F4', S0 + P(0, 20), 1, 'SWITCH_FLAG'),
    ('F1', S0 + 4, 2, 'SEALED_RANGE'), ('F1', S0 + 4, 1, 'SEALED_RULE'), ('F5', S1 + 4, 1, 'SEALED_RULE'),
    ('F1', S0 + SIDE_SEALED_OFF, 1, 'SEALED_COMMAND'), ('F1', S1 + P(0, 1), 1, 'ACTIVATION_DUPLICATE'),
    ('F1', S0 + 5, 0x1A, 'SEEN_MASK'), ('F1', S0 + 5, 0x08, 'SEEN_MASK'), ('F1', S1 + 5, 0x10, 'SEEN_MASK'),
    ('F1', S0 + K(0, 0), 1, 'KNOWLEDGE'), ('F1', S0 + K(0, 3), 1, 'KNOWLEDGE'), ('F1', S0 + K(1, 0), 99, 'KNOWLEDGE'),
    ('F1', S0 + K(1, 1), 1, 'KNOWLEDGE'), ('F1', S1 + K(0, 4), 1, 'KNOWLEDGE'), ('F2', S1 + K(2, 0), 101, 'KNOWLEDGE'),
    ('F2', S1 + K(2, 1), 3, 'KNOWLEDGE'), ('F2', S1 + K(2, 1), 0, 'KNOWLEDGE'), ('F1', S0 + K(1, 2), 1, 'KNOWLEDGE'),
    ('F1', S0 + K(1, 2), 2, 'KNOWLEDGE'), ('F1', S0 + K(1, 2), 4, 'KNOWLEDGE'), ('F1', S0 + K(0, 2), 1, 'KNOWLEDGE'),
    ('F1', 94, 1, 'QUEUE'), ('F1', 95, 1, 'QUEUE'), ('F1', 104, 1, 'QUEUE'), ('F5', 94, 0, 'QUEUE'),
    ('F5', 94, 13, 'QUEUE'), ('F5', 94, 2, 'QUEUE'), ('F5', 94, 4, 'QUEUE'), ('F5', 95, 0, 'QUEUE'),
    ('F5', 95, 7, 'QUEUE'), ('F5', 96, 2, 'QUEUE'), ('F5', 97, 2, 'QUEUE'), ('F5', 98, 5, 'QUEUE'),
    ('F5', 99, 4, 'QUEUE'), ('F5', 100, 1, 'QUEUE'), ('F5', 101, 5, 'QUEUE'), ('F5', 101, 0, 'QUEUE'),
    ('F5', 116, 1, 'QUEUE'), ('F5', 121, 1, 'QUEUE'), ('F6', 100, 6, 'QUEUE'), ('F6', 101, 1, 'QUEUE'),
    ('F6', 98, 1, 'QUEUE'), ('F6', 110, 1, 'QUEUE'), ('F6', 111, 0, 'QUEUE'), ('F6', 120, 4, 'QUEUE'),
    ('F6', 121, 0, 'QUEUE'), ('F6', 130, 1, 'QUEUE'),
]
# Single-byte edits that stay valid (the structural checker is not a
# reachability checker).
ACCEPTED = [('F1', S0 + P(0, 19), 200), ('F1', S0 + P(0, 5), 0), ('F1', S0 + P(0, 5), 12), ('F1', S0 + 12, 8),
            ('F1', S0 + 14, 4), ('F1', 93, 5), ('F5', 99, 0xFF), ('F5', S0 + P(0, 20), 2)]


def c_array(name, data):
    lines = ['const uint8_t %s[%d] = {' % (name, len(data))]
    for off in range(0, len(data), 20):
        row = ', '.join('0x%02x' % v for v in data[off:off + 20])
        lines.append('    %s, /* %3d */' % (row, off))
    lines.append('};')
    return '\n'.join(lines)


def emit_goldens(encoded):
    print('/*')
    print(' * GENERATED by tools/state_model/state_v3_model.py --goldens from the')
    print(' * independent structural model; never copied from the C encoder. Offsets')
    print(' * are annotated per 20-byte row. Do not edit by hand.')
    print(' */')
    print('#include "support/fixtures.h"')
    print('')
    print(c_array('df_context_c1_bytes', C1.canonical_bytes()))
    for name in ('F1', 'F2', 'F3', 'F5'):
        print('')
        print(c_array('df_golden_%s' % name.lower(), encoded[name]))


def main():
    sys.stdout.reconfigure(newline=chr(10))  # LF on every platform
    encoded = {}
    contexts = {}
    for name, ctx, build in FIXTURES:
        st = build()
        b = encode(st)
        encoded[name] = b
        contexts[name] = ctx
        assert decode(ctx, b) == ('OK', None)
    if '--goldens' in sys.argv[1:]:
        emit_goldens(encoded)
        return

    for name, ctx in (('C1', C1), ('C2', C2), ('C3', C3), ('C4', C4)):
        assert ctx.valid()
        print('context %s bytes %s' % (name, ctx.canonical_bytes().hex()))
        print('context %s table_sha256 %s' % (name, hashlib.sha256(ctx.table).hexdigest()))
        print('context %s fingerprint %s' % (name, ctx.fingerprint().hex()))
    for name, ctx in (('K1', K1), ('K2', K2)):
        assert ctx.valid()
        print('context %s bytes %s' % (name, ctx.canonical_bytes().hex()))
        print('context %s fingerprint %s' % (name, ctx.fingerprint().hex()))

    for name, ctx, build in FIXTURES:
        b = encoded[name]
        print('fixture %s sha256 %s' % (name, hashlib.sha256(b).hexdigest()))
        for off in range(0, STATE_SIZE, 20):
            print('fixture %s %03d: %s' % (name, off, b[off:off + 20].hex()))

    for name, ctx, build in FIXTURES:
        st = build()
        for player in range(2):
            req, cands = candidates(ctx, st, player)
            if req == 'UNSUPPORTED':
                print('domain %s p%d UNSUPPORTED' % (name, player))
                continue
            blob = b''.join(cands)
            print('domain %s p%d request epoch=%d kind=%s requested=%d slots=%d count=%d sha256=%s' % (
                name, player, req[0], BOUNDARY_NAMES[req[1]], req[2], req[3], req[4],
                hashlib.sha256(blob).hexdigest()))
            if 0 < len(cands) <= 40:
                for i, c in enumerate(cands):
                    print('domain %s p%d %02d %s' % (name, player, i, c.hex()))

    for name, ctx, build in FIXTURES:
        st = build()
        for player in range(2):
            ob = observe(ctx, st, player)
            print('observation %s p%d sha256=%s' % (name, player, hashlib.sha256(ob).hexdigest()))
            if name in ('F3', 'F2'):
                for off in range(0, OBSERVATION_SIZE, 32):
                    print('observation %s p%d %03d: %s' % (name, player, off, ob[off:off + 32].hex()))

    for rname, lo, hi in REGIONS:
        print('region_c     {%d, %d, "%s"},' % (lo, hi, rname))
    for name in ('F1', 'F2', 'F5'):
        counts = mutation_counts(C1, encoded[name])
        total = {}
        for rname, _, _ in REGIONS:
            c = counts[rname]
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
            print('mutation %s %s %s' % (name, rname, ' '.join('%s=%d' % kv for kv in sorted(c.items()))))
        print('mutation %s TOTAL %s' % (name, ' '.join('%s=%d' % kv for kv in sorted(total.items()))))
        for rname, _, _ in REGIONS:
            row = ', '.join('%d' % counts[rname].get(col, 0) for col in STATUS_COLUMNS)
            print('mutation_c %s     {%s}, /* %s */' % (name, row, rname))

    for fname, off, val, expected in TARGETED:
        b = bytearray(encoded[fname])
        assert b[off] != val, (fname, off, val)
        b[off] = val
        status, inv = decode(contexts[fname], b)
        print('targeted %s %d=0x%02x %s %s %s' % (fname, off, val, status, inv, 'OK' if inv == expected else 'DIFF'))
    for fname, off, val in ACCEPTED:
        b = bytearray(encoded[fname])
        assert b[off] != val, (fname, off, val)
        b[off] = val
        status, inv = decode(contexts[fname], b)
        print('accepted %s %d=0x%02x %s %s' % (fname, off, val, status, 'OK' if status == 'OK' else 'DIFF'))

    f1 = encoded['F1']
    for n in list(range(0, STATE_SIZE)) + [STATE_SIZE + 1]:
        b = f1[:n] if n <= STATE_SIZE else f1 + b'\x00'
        status, _ = decode(C1, b)
        assert status == 'MALFORMED', (n, status)
    print('truncations 0..%d and +1 byte: all MALFORMED' % (STATE_SIZE - 1))
    for old in (1, 2):
        b = bytearray(f1)
        struct.pack_into('<H', b, 10, old)
        assert decode(C1, b)[0] == 'SCHEMA_MISMATCH'
        print('schema %d at %d bytes: SCHEMA_MISMATCH' % (old, STATE_SIZE))

    for label, ctx, base in (('G1/C1', C1, setup_g1()), ('G3/C3', C3, setup_g3())):
        classes = setup_sweep(ctx, base)
        tok = tbad = 0
        order = [('battle', 'rng_initstate'), ('battle', 'rng_initseq')]
        for s in range(2):
            for n in ('member_count', 'species_id', 'hp_max', 'move_count', 'mega_capable', 'move_id', 'pp_max'):
                order.append((s, n))
        for cls in order:
            ok, bad = classes[cls]
            tok += ok
            tbad += bad
            print('setup %s %s %s OK=%d INVALID=%d' % (label, cls[0], cls[1], ok, bad))
        print('setup %s TOTAL OK=%d INVALID=%d' % (label, tok, tbad))


if __name__ == '__main__':
    main()
