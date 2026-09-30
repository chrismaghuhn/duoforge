#!/usr/bin/env python3
"""Structural model of DuoForge context v2, state v2, invariants v2, codec v2
and the M2 decision domains (decision 0005). Written from the decision notes,
not from the C sources. Stdlib only. CTest never runs it.

Prints every value the M2 C tests assert: context bytes and fingerprints,
fixture encodings and digests, per-region mutation counts, targeted invariant
edits, setup-sweep counts, and for every fixture and player the request, the
candidate count and the SHA-256 of the concatenated canonical candidates.
"""
import hashlib
import itertools
import struct

MAGIC = bytes([0x89, 0x44, 0x55, 0x4F, 0x0D, 0x0A, 0x1A, 0x0A])
KIND_CONTEXT = 1
KIND_BATTLE_STATE = 2
SCHEMA = 2
SEMANTICS = 2
CONTEXT_BYTES_SIZE = 63
STATE_SIZE = 438
SIDE_SIZE = 176
MEMBER_SIZE = 24
MAX_ROSTER = 6
MOVE_SLOTS = 4
NONE = 0xFF

TEAM_SELECTION, TURN, REPLACEMENT, PIVOT = 1, 2, 3, 4
BOUNDARY_NAMES = {1: 'TEAM_SELECTION', 2: 'TURN', 3: 'REPLACEMENT', 4: 'PIVOT'}
SLOT_NONE, SLOT_MOVE, SLOT_SWITCH, SLOT_PASS = 0, 1, 2, 3
CHOICE_TEAM_SELECTION, CHOICE_SLOTS = 1, 2
TARGET_NONE = 0xFF
# target classes
NORMAL, ANY, ADJ_ALLY, ADJ_ALLY_OR_SELF, ADJ_FOE, SELF, ALL_ADJ_FOES, ALLY_SIDE, ALL = range(1, 10)
CLASS_COUNT = 9


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


# ---------------------------------------------------------------- state
def empty_member():
    return {'species': 0, 'hp': 0, 'hp_max': 0, 'move_count': 0, 'mega_capable': 0,
            'moves': [{'id': 0, 'pp': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]}


def zero_cmd():
    return {'kind': 0, 'move_slot': 0, 'target': 0, 'mega': 0, 'reserve': 0}


def empty_side():
    return {'member_count': 0, 'brought': 0, 'requested_slots': 0, 'mega_used': 0, 'sealed': 0,
            'seen': 0, 'order': [NONE] * MAX_ROSTER,
            'pos': [{'occ': NONE, 'act': 0}, {'occ': NONE, 'act': 0}],
            'sealed_cmds': [zero_cmd(), zero_cmd()],
            'members': [empty_member() for _ in range(MAX_ROSTER)]}


def empty_state(ctx):
    return {'fp': ctx.fingerprint(), 'rng_state': 0, 'rng_inc': 0, 'draws': 0, 'next': 1,
            'boundary': TEAM_SELECTION, 'request_mask': 3, 'epoch': 1,
            'sides': [empty_side(), empty_side()]}


def place(st, side, slot, roster):
    sd = st['sides'][side]
    assert sd['pos'][slot]['occ'] == NONE
    assert roster < sd['member_count'] and (sd['brought'] >> roster) & 1
    assert sd['pos'][1 - slot]['occ'] != roster
    assert st['next'] != 0xFFFFFFFF
    sd['pos'][slot] = {'occ': roster, 'act': st['next']}
    st['next'] += 1
    st['sides'][1 - side]['seen'] |= 1 << roster


def vacate(st, side, slot):
    assert st['sides'][side]['pos'][slot]['occ'] != NONE
    st['sides'][side]['pos'][slot] = {'occ': NONE, 'act': 0}


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
    """Setup validation order (decision 0005 section 9 / src/state/battle.c).
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
              'EPOCH_ZERO', 'REQUEST_MASK', 'MEMBER_COUNT', 'SPECIES_RANGE', 'HP_MAX_ZERO', 'HP_ABOVE_MAX',
              'MOVE_COUNT', 'MOVE_ID_RANGE', 'PP_MAX_ZERO', 'PP_ABOVE_MAX', 'UNUSED_MOVE_NONZERO',
              'MEGA_CAPABLE_RANGE', 'UNUSED_MEMBER_NONZERO', 'BROUGHT_OUT_OF_RANGE', 'BROUGHT_COUNT',
              'BROUGHT_ORDER', 'MEGA_USED_RANGE', 'EMPTY_WITH_ACTIVATION', 'OCCUPIED_WITHOUT_ACTIVATION',
              'OCCUPANT_RANGE', 'OCCUPANT_NOT_BROUGHT', 'ACTIVATION_NOT_ISSUED', 'OCCUPANT_DUPLICATE',
              'REQUESTED_SLOTS', 'SEALED_RANGE', 'SEALED_RULE', 'SEALED_COMMAND', 'ACTIVATION_DUPLICATE',
              'SEEN_MASK']
assert len(INVARIANTS) == 34


def cmd_is_zero(c):
    return not (c['kind'] or c['move_slot'] or c['target'] or c['mega'] or c['reserve'])


def sealed_cmd_valid(c, mc):
    if c['kind'] == SLOT_MOVE:
        return (c['move_slot'] < MOVE_SLOTS and (c['target'] < 4 or c['target'] == TARGET_NONE)
                and c['mega'] <= 1 and c['reserve'] == 0)
    if c['kind'] == SLOT_SWITCH:
        return c['reserve'] < mc and not (c['move_slot'] or c['target'] or c['mega'])
    if c['kind'] in (SLOT_NONE, SLOT_PASS):
        return not (c['move_slot'] or c['target'] or c['mega'] or c['reserve'])
    return False


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
        else:
            if (mem['species'] or mem['hp'] or mem['hp_max'] or mem['move_count'] or mem['mega_capable']
                    or any(x['id'] or x['pp'] or x['pp_max'] for x in mem['moves'])):
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
    if sd['sealed'] > 1:
        return 'SEALED_RANGE'
    if kind in (TEAM_SELECTION, REPLACEMENT):
        if sd['sealed'] != 0:
            return 'SEALED_RULE'
    elif kind == TURN:
        if sd['sealed'] != (0 if requested else 1):
            return 'SEALED_RULE'
    for c in sd['sealed_cmds']:
        if sd['sealed'] == 0:
            if not cmd_is_zero(c):
                return 'SEALED_COMMAND'
        elif not sealed_cmd_valid(c, mc):
            return 'SEALED_COMMAND'
    return 'OK'


def check_state(ctx, st):
    """Invariant order (decision 0005 section 9); returns 'OK' or the first
    violated invariant name."""
    if st['fp'] != ctx.fingerprint():
        return 'CONTEXT_FINGERPRINT'
    if st['rng_inc'] & 1 == 0:
        return 'RNG_INC_EVEN'
    if st['next'] == 0:
        return 'NEXT_ACTIVATION_ZERO'
    if not (1 <= st['boundary'] <= 4):
        return 'BOUNDARY_KIND'
    if st['epoch'] == 0:
        return 'EPOCH_ZERO'
    if not (1 <= st['request_mask'] <= 3):
        return 'REQUEST_MASK'
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
    return 'OK'


# ---------------------------------------------------------------- codec
def encode(st):
    b = bytearray(MAGIC + struct.pack('<HHII', KIND_BATTLE_STATE, SCHEMA, SEMANTICS, STATE_SIZE))
    b += st['fp']
    b += struct.pack('<QQQI', st['rng_state'], st['rng_inc'], st['draws'], st['next'])
    b += struct.pack('<BBI', st['boundary'], st['request_mask'], st['epoch'])
    assert len(b) == 86
    for sd in st['sides']:
        b += bytes([sd['member_count'], sd['brought'], sd['requested_slots'], sd['mega_used'], sd['sealed'],
                    sd['seen']])
        b += bytes(sd['order'])
        for p in sd['pos']:
            b += bytes([p['occ']]) + struct.pack('<I', p['act'])
        for c in sd['sealed_cmds']:
            b += bytes([c['kind'], c['move_slot'], c['target'], c['mega'], c['reserve']])
        for mem in sd['members']:
            b += struct.pack('<HHHBB', mem['species'], mem['hp'], mem['hp_max'], mem['move_count'],
                             mem['mega_capable'])
            for mv in mem['moves']:
                b += struct.pack('<HBB', mv['id'], mv['pp'], mv['pp_max'])
    assert len(b) == STATE_SIZE
    return bytes(b)


def parse(b):
    st = {'fp': bytes(b[20:52])}
    st['rng_state'], st['rng_inc'], st['draws'], st['next'] = struct.unpack_from('<QQQI', b, 52)
    st['boundary'], st['request_mask'], st['epoch'] = struct.unpack_from('<BBI', b, 80)
    st['sides'] = []
    for s in range(2):
        o = 86 + SIDE_SIZE * s
        sd = {'member_count': b[o], 'brought': b[o + 1], 'requested_slots': b[o + 2], 'mega_used': b[o + 3],
              'sealed': b[o + 4], 'seen': b[o + 5], 'order': list(b[o + 6:o + 12]),
              'pos': [{'occ': b[o + 12], 'act': struct.unpack_from('<I', b, o + 13)[0]},
                      {'occ': b[o + 17], 'act': struct.unpack_from('<I', b, o + 18)[0]}],
              'sealed_cmds': [], 'members': []}
        for c in range(2):
            co = o + 22 + 5 * c
            sd['sealed_cmds'].append({'kind': b[co], 'move_slot': b[co + 1], 'target': b[co + 2],
                                      'mega': b[co + 3], 'reserve': b[co + 4]})
        for m in range(MAX_ROSTER):
            mo = o + 32 + MEMBER_SIZE * m
            species, hp, hp_max, mc, mega = struct.unpack_from('<HHHBB', b, mo)
            moves = []
            for k in range(MOVE_SLOTS):
                mid, pp, ppm = struct.unpack_from('<HBB', b, mo + 8 + 4 * k)
                moves.append({'id': mid, 'pp': pp, 'pp_max': ppm})
            sd['members'].append({'species': species, 'hp': hp, 'hp_max': hp_max, 'move_count': mc,
                                  'mega_capable': mega, 'moves': moves})
        st['sides'].append(sd)
    return st


def decode(ctx, b):
    """Strict decode order (decision 0002 section 6, sizes of v2); returns
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
    """Per-slot candidates in documented order, or 'UNSUPPORTED' (Struggle)."""
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
            for tgt in selectable_targets(ctx.table[mv['id']], side, slot):
                for mg in megas:
                    out.append(cmd(SLOT_MOVE, k, tgt, mg))
        moves = len(out)
        for r in reserves(sd):
            out.append(cmd(SLOT_SWITCH, reserve=r))
        if moves == 0:
            return 'UNSUPPORTED'
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
    320 bytes, absolute side order."""
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
                    pct, flag = hp_percent(mem['hp'], mem['hp_max'])
                    hp, hp_max, hp_kind = pct, 100, HP_PERCENT
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
    st = fixture_f1()
    for _ in range(16):
        pcg_next(st)
    vacate(st, 0, 0)
    place(st, 0, 0, 3)
    vacate(st, 1, 1)
    st['sides'][1]['requested_slots'] = 1
    s0, s1 = st['sides']
    s0['members'][0]['hp'] = 0
    s0['members'][1]['hp'] = 57
    s0['members'][1]['moves'][0]['pp'] = 0
    s1['members'][2]['hp'] = 0
    s1['members'][0]['moves'][3]['pp'] = 7
    s0['mega_used'] = 1
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
    st['boundary'] = REPLACEMENT
    st['epoch'] = 3
    st['request_mask'] = 3
    st['sides'][0]['requested_slots'] = 1
    st['sides'][1]['requested_slots'] = 2
    assert check_state(C1, st) == 'OK'
    return st


def sealed_pair_f5():
    return ([cmd(SLOT_MOVE, 0, 2, 0), cmd(SLOT_MOVE, 1, 3, 0)],
            [cmd(SLOT_SWITCH, reserve=0), cmd(SLOT_MOVE, 2, 0, 0)])


def fixture_f5():
    """One-side PIVOT (side 0, slot a); both sides' turn choices sealed."""
    st = fixture_f1()
    st['boundary'] = PIVOT
    st['epoch'] = 3
    st['request_mask'] = 1
    st['sides'][0]['requested_slots'] = 1
    st['sides'][1]['requested_slots'] = 0
    s0c, s1c = sealed_pair_f5()
    for s, c in ((0, s0c), (1, s1c)):
        st['sides'][s]['sealed'] = 1
        st['sides'][s]['sealed_cmds'] = c
    assert check_state(C1, st) == 'OK'
    return st


def fixture_f6():
    """Two-side PIVOT (Emergency Exit plus Eject Button): s0a and s1b."""
    st = fixture_f5()
    st['request_mask'] = 3
    st['sides'][1]['requested_slots'] = 2
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
    assert check_state(C4, st) == 'OK'
    return st


def fixture_f12():
    """F9 with side 0 slot a alive but every move at pp 0 (Struggle: UNSUPPORTED)."""
    st = fixture_f9()
    for mv in st['sides'][0]['members'][0]['moves'][:2]:
        mv['pp'] = 0
    assert check_state(C4, st) == 'OK'
    return st


FIXTURES = [('G1', C1, fixture_g1), ('F1', C1, fixture_f1), ('F2', C1, fixture_f2), ('G3', C3, fixture_g3),
            ('F3', C3, fixture_f3), ('F4', C1, fixture_f4), ('F5', C1, fixture_f5), ('F6', C1, fixture_f6),
            ('G7', C4, fixture_g7), ('F8', C4, fixture_f8), ('F9', C4, fixture_f9), ('F10', C4, fixture_f10),
            ('F11', C4, fixture_f11), ('F12', C4, fixture_f12)]

REGIONS = [('magic', 0, 8), ('kind', 8, 10), ('schema', 10, 12), ('semantics', 12, 16), ('total_length', 16, 20),
           ('fingerprint', 20, 52), ('rng.state', 52, 60), ('rng.inc', 60, 68), ('rng.draws', 68, 76),
           ('next_activation', 76, 80), ('boundary', 80, 86), ('side0.header', 86, 118),
           ('side0.members', 118, 262), ('side1.header', 262, 294), ('side1.members', 294, 438)]


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


# One targeted single-byte edit of the F1 encoding per invariant id that a
# single byte can trigger (offsets from the v2 layout).
TARGETED = [((60, 0x6C), 'RNG_INC_EVEN'), ((76, 0), 'NEXT_ACTIVATION_ZERO'), ((80, 0), 'BOUNDARY_KIND'),
            ((80, 5), 'BOUNDARY_KIND'), ((82, 0), 'EPOCH_ZERO'), ((81, 0), 'REQUEST_MASK'),
            ((81, 4), 'REQUEST_MASK'), ((86, 3), 'MEMBER_COUNT'), ((86, 7), 'MEMBER_COUNT'),
            ((118, 16), 'SPECIES_RANGE'), ((122, 0), 'HP_MAX_ZERO'), ((120, 101), 'HP_ABOVE_MAX'),
            ((124, 0), 'MOVE_COUNT'), ((124, 5), 'MOVE_COUNT'), ((126, 36), 'MOVE_ID_RANGE'),
            ((129, 0), 'PP_MAX_ZERO'), ((128, 6), 'PP_ABOVE_MAX'), ((130, 1), 'UNUSED_MOVE_NONZERO'),
            ((125, 2), 'MEGA_CAPABLE_RANGE'), ((390, 1), 'UNUSED_MEMBER_NONZERO'),
            ((263, 0x17), 'BROUGHT_OUT_OF_RANGE'), ((87, 0x07), 'BROUGHT_COUNT'), ((92, 5), 'BROUGHT_ORDER'),
            ((95, 0xFF), 'BROUGHT_ORDER'), ((96, 0), 'BROUGHT_ORDER'), ((89, 2), 'MEGA_USED_RANGE'),
            ((98, 0xFF), 'EMPTY_WITH_ACTIVATION'), ((280, 0), 'OCCUPIED_WITHOUT_ACTIVATION'),
            ((274, 4), 'OCCUPANT_RANGE'), ((98, 4), 'OCCUPANT_NOT_BROUGHT'),
            ((99, 5), 'ACTIVATION_NOT_ISSUED'), ((103, 2), 'OCCUPANT_DUPLICATE'), ((88, 1), 'REQUESTED_SLOTS'),
            ((88, 4), 'REQUESTED_SLOTS'), ((90, 2), 'SEALED_RANGE'), ((90, 1), 'SEALED_RULE'),
            ((108, 1), 'SEALED_COMMAND'), ((275, 1), 'ACTIVATION_DUPLICATE'), ((91, 0x1A), 'SEEN_MASK'),
            ((91, 0x08), 'SEEN_MASK'), ((267, 0x10), 'SEEN_MASK')]


def main():
    for name, ctx in (('C1', C1), ('C2', C2), ('C3', C3), ('C4', C4)):
        assert ctx.valid()
        print('context %s bytes %s' % (name, ctx.canonical_bytes().hex()))
        print('context %s table_sha256 %s' % (name, hashlib.sha256(ctx.table).hexdigest()))
        print('context %s fingerprint %s' % (name, ctx.fingerprint().hex()))

    encoded = {}
    for name, ctx, build in FIXTURES:
        st = build()
        b = encode(st)
        encoded[name] = b
        assert decode(ctx, b) == ('OK', None)
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

    for name in ('F1', 'F2'):
        counts = mutation_counts(C1, encoded[name])
        total = {}
        for rname, _, _ in REGIONS:
            c = counts[rname]
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
            print('mutation %s %s %s' % (name, rname, ' '.join('%s=%d' % kv for kv in sorted(c.items()))))
        print('mutation %s TOTAL %s' % (name, ' '.join('%s=%d' % kv for kv in sorted(total.items()))))

    f1 = encoded['F1']
    for (off, val), expected in TARGETED:
        b = bytearray(f1)
        b[off] = val
        status, inv = decode(C1, b)
        print('targeted %d=0x%02x %s %s %s' % (off, val, status, inv, 'OK' if inv == expected else 'DIFF'))

    for n in list(range(0, STATE_SIZE)) + [STATE_SIZE + 1]:
        b = f1[:n] if n <= STATE_SIZE else f1 + b'\x00'
        status, _ = decode(C1, b)
        assert status == 'MALFORMED', (n, status)
    print('truncations 0..437 and +1 byte: all MALFORMED')
    b = bytearray(f1)
    struct.pack_into('<H', b, 10, 1)
    assert decode(C1, b)[0] == 'SCHEMA_MISMATCH'
    print('schema 1 at 438 bytes: SCHEMA_MISMATCH')

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
