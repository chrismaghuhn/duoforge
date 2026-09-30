#!/usr/bin/env python3
"""DuoForge state v1 structural reference model (tests oracle).

Structural reference model for tests; not combat rules; never run by CTest.

It is written from the specification tables of docs/decisions/0002
(context bytes, setup validation, invariant order, canonical encoding v1,
strict decoding), not from the C sources, and prints every golden value
the C tests assert: context bytes and fingerprints, the F1/F2/F3 encodings
and digests, the single-byte mutation-sweep outcome counts per region,
the targeted invariant edits and the setup-sweep counts.

Usage: python3 tools/state_model/state_v1_model.py
Standard library only.
"""

import hashlib
import struct

MASK64 = (1 << 64) - 1
MAGIC = bytes([0x89, 0x44, 0x55, 0x4F, 0x0D, 0x0A, 0x1A, 0x0A])
KIND_CONTEXT = 1
KIND_BATTLE_STATE = 2
SCHEMA = 1
SEMANTICS = 1
STATE_SIZE = 380
CONTEXT_BYTES_SIZE = 31
MAX_ROSTER = 6
MOVE_SLOTS = 4
NONE = 0xFF

# ---------------------------------------------------------------- PCG32
PCG_MULT = 6364136223846793005


def pcg_step(state, inc):
    return (state * PCG_MULT + inc) & MASK64


def pcg_output(old):
    x = (((old >> 18) ^ old) >> 27) & 0xFFFFFFFF
    rot = old >> 59
    return ((x >> rot) | (x << ((32 - rot) & 31))) & 0xFFFFFFFF


def pcg_seed(initstate, initseq):
    inc = ((initseq << 1) | 1) & MASK64
    s = pcg_step(0, inc)
    s = (s + initstate) & MASK64
    s = pcg_step(s, inc)
    return s, inc


# ---------------------------------------------------------------- context
class Context:
    def __init__(self, data_kind, max_roster, brought_count, species_count, move_count):
        self.data_kind = data_kind
        self.max_roster = max_roster
        self.brought_count = brought_count
        self.species_count = species_count
        self.move_count = move_count

    def valid(self):
        return (self.data_kind == 1 and 1 <= self.max_roster <= MAX_ROSTER
                and 1 <= self.brought_count <= self.max_roster
                and 1 <= self.species_count <= 65535 and 1 <= self.move_count <= 65535)

    def canonical_bytes(self):
        b = MAGIC + struct.pack('<HHII', KIND_CONTEXT, SCHEMA, SEMANTICS, CONTEXT_BYTES_SIZE)
        b += bytes([2, 2, MAX_ROSTER, MOVE_SLOTS, self.data_kind, self.max_roster, self.brought_count])
        b += struct.pack('<HH', self.species_count, self.move_count)
        assert len(b) == CONTEXT_BYTES_SIZE
        return b

    def fingerprint(self):
        return hashlib.sha256(self.canonical_bytes()).digest()


C1 = Context(1, 6, 4, 16, 32)
C2 = Context(1, 6, 4, 16, 33)
C3 = Context(1, 6, 1, 16, 32)

# ---------------------------------------------------------------- state
def empty_member():
    return {'species': 0, 'hp': 0, 'hp_max': 0, 'move_count': 0,
            'moves': [{'id': 0, 'pp': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]}


def empty_state(ctx):
    return {
        'fp': ctx.fingerprint(), 'rng_state': 0, 'rng_inc': 0, 'draws': 0, 'next': 1,
        'sides': [{'member_count': 0, 'brought': 0,
                   'pos': [{'occ': NONE, 'act': 0}, {'occ': NONE, 'act': 0}],
                   'members': [empty_member() for _ in range(MAX_ROSTER)]} for _ in range(2)],
    }


def place(st, side, slot, roster):
    sd = st['sides'][side]
    assert sd['pos'][slot]['occ'] == NONE
    assert roster < sd['member_count'] and (sd['brought'] >> roster) & 1
    assert sd['pos'][1 - slot]['occ'] != roster
    assert st['next'] != 0xFFFFFFFF
    sd['pos'][slot] = {'occ': roster, 'act': st['next']}
    st['next'] += 1


def vacate(st, side, slot):
    assert st['sides'][side]['pos'][slot]['occ'] != NONE
    st['sides'][side]['pos'][slot] = {'occ': NONE, 'act': 0}


# ---------------------------------------------------------------- setup
SETUP_FIELDS = []  # (side or None, member or None, move or None, name)


def build_field_list():
    SETUP_FIELDS.append((None, None, None, 'rng_initstate'))
    SETUP_FIELDS.append((None, None, None, 'rng_initseq'))
    for s in range(2):
        for name in ('member_count', 'brought_mask', 'lead0', 'lead1'):
            SETUP_FIELDS.append((s, None, None, name))
        for m in range(MAX_ROSTER):
            for name in ('species_id', 'hp_max', 'move_count'):
                SETUP_FIELDS.append((s, m, None, name))
            for k in range(MOVE_SLOTS):
                for name in ('move_id', 'pp_max'):
                    SETUP_FIELDS.append((s, m, k, name))


build_field_list()
assert len(SETUP_FIELDS) == 142


def setup_member(species, hp_max, moves):
    mv = [{'move_id': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]
    for k, (mid, ppm) in enumerate(moves):
        mv[k] = {'move_id': mid, 'pp_max': ppm}
    return {'species_id': species, 'hp_max': hp_max, 'move_count': len(moves), 'moves': mv}


def zero_setup_member():
    return {'species_id': 0, 'hp_max': 0, 'move_count': 0,
            'moves': [{'move_id': 0, 'pp_max': 0} for _ in range(MOVE_SLOTS)]}


def setup_f1():
    s0 = [setup_member(i + 1, 100 + 10 * i, [(4 * i + k, 5 + 5 * k) for k in range((i % 4) + 1)])
          for i in range(6)]
    s1 = [setup_member(10 + i, 200 + i, [(31 - (4 * i + k), 8 * (k + 1)) for k in range(4)])
          for i in range(4)] + [zero_setup_member() for _ in range(2)]
    return {'rng_initstate': 42, 'rng_initseq': 54, 'sides': [
        {'member_count': 6, 'brought_mask': 0x0F, 'lead0': 2, 'lead1': 0, 'members': s0},
        {'member_count': 4, 'brought_mask': 0x0F, 'lead0': 1, 'lead1': 3, 'members': s1}]}


def setup_f3():
    s0 = [setup_member(i, 50 + i, [(i, 1)]) for i in range(3)] + [zero_setup_member() for _ in range(3)]
    s1 = [setup_member(15 - i, 65535 - i, [(31, 255), (30, 1)]) for i in range(2)] + \
         [zero_setup_member() for _ in range(4)]
    return {'rng_initstate': 42, 'rng_initseq': 54, 'sides': [
        {'member_count': 3, 'brought_mask': 0x04, 'lead0': 2, 'lead1': NONE, 'members': s0},
        {'member_count': 2, 'brought_mask': 0x01, 'lead0': 0, 'lead1': NONE, 'members': s1}]}


def copy_setup(su):
    return {'rng_initstate': su['rng_initstate'], 'rng_initseq': su['rng_initseq'], 'sides': [
        {'member_count': sd['member_count'], 'brought_mask': sd['brought_mask'], 'lead0': sd['lead0'],
         'lead1': sd['lead1'],
         'members': [{'species_id': m['species_id'], 'hp_max': m['hp_max'], 'move_count': m['move_count'],
                      'moves': [dict(x) for x in m['moves']]} for m in sd['members']]}
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


def popcount(v):
    return bin(v).count('1')


def validate_setup(ctx, su):
    """Section 11 order. Returns True for OK, False for INVALID_ARGUMENT."""
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
            else:
                if (mem['species_id'] or mem['hp_max'] or mem['move_count']
                        or any(x['move_id'] or x['pp_max'] for x in mem['moves'])):
                    return False
        mask = sd['brought_mask']
        if (mask >> mc) != 0:
            return False
        if popcount(mask) != ctx.brought_count:
            return False
        l0, l1 = sd['lead0'], sd['lead1']
        if not (l0 < mc and (mask >> l0) & 1):
            return False
        if ctx.brought_count >= 2:
            if not (l1 < mc and (mask >> l1) & 1 and l1 != l0):
                return False
        elif l1 != NONE:
            return False
    return True


def init_state(ctx, su):
    assert validate_setup(ctx, su)
    st = empty_state(ctx)
    st['rng_state'], st['rng_inc'] = pcg_seed(su['rng_initstate'], su['rng_initseq'])
    for s, sd in enumerate(su['sides']):
        out = st['sides'][s]
        out['member_count'] = sd['member_count']
        out['brought'] = sd['brought_mask']
        for m in range(sd['member_count']):
            src = sd['members'][m]
            dst = out['members'][m]
            dst['species'] = src['species_id']
            dst['hp'] = dst['hp_max'] = src['hp_max']
            dst['move_count'] = src['move_count']
            for k in range(src['move_count']):
                dst['moves'][k] = {'id': src['moves'][k]['move_id'], 'pp': src['moves'][k]['pp_max'],
                                   'pp_max': src['moves'][k]['pp_max']}
    for s in range(2):
        for slot, lead in ((0, su['sides'][s]['lead0']), (1, su['sides'][s]['lead1'])):
            if lead != NONE:
                place(st, s, slot, lead)
    assert check_state(ctx, st) == 'OK'
    return st


# ---------------------------------------------------------------- invariants
INVARIANTS = ['NONE', 'CONTEXT_FINGERPRINT', 'RNG_INC_EVEN', 'NEXT_ACTIVATION_ZERO', 'MEMBER_COUNT',
              'SPECIES_RANGE', 'HP_MAX_ZERO', 'HP_ABOVE_MAX', 'MOVE_COUNT', 'MOVE_ID_RANGE', 'PP_MAX_ZERO',
              'PP_ABOVE_MAX', 'UNUSED_MOVE_NONZERO', 'UNUSED_MEMBER_NONZERO', 'BROUGHT_OUT_OF_RANGE',
              'BROUGHT_COUNT', 'EMPTY_WITH_ACTIVATION', 'OCCUPIED_WITHOUT_ACTIVATION', 'OCCUPANT_RANGE',
              'OCCUPANT_NOT_BROUGHT', 'ACTIVATION_NOT_ISSUED', 'OCCUPANT_DUPLICATE', 'ACTIVATION_DUPLICATE']
assert len(INVARIANTS) == 23


def check_state(ctx, st):
    """Section 12 order; returns 'OK' or the first violated invariant name."""
    if st['fp'] != ctx.fingerprint():
        return 'CONTEXT_FINGERPRINT'
    if st['rng_inc'] & 1 == 0:
        return 'RNG_INC_EVEN'
    if st['next'] == 0:
        return 'NEXT_ACTIVATION_ZERO'
    for sd in st['sides']:
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
            else:
                if (mem['species'] or mem['hp'] or mem['hp_max'] or mem['move_count']
                        or any(x['id'] or x['pp'] or x['pp_max'] for x in mem['moves'])):
                    return 'UNUSED_MEMBER_NONZERO'
        if (sd['brought'] >> mc) != 0:
            return 'BROUGHT_OUT_OF_RANGE'
        if popcount(sd['brought']) != ctx.brought_count:
            return 'BROUGHT_COUNT'
        for p in sd['pos']:
            if p['occ'] == NONE:
                if p['act'] != 0:
                    return 'EMPTY_WITH_ACTIVATION'
                continue
            if p['act'] == 0:
                return 'OCCUPIED_WITHOUT_ACTIVATION'
            if p['occ'] >= mc:
                return 'OCCUPANT_RANGE'
            if not (sd['brought'] >> p['occ']) & 1:
                return 'OCCUPANT_NOT_BROUGHT'
            if p['act'] >= st['next']:
                return 'ACTIVATION_NOT_ISSUED'
        if sd['pos'][0]['occ'] != NONE and sd['pos'][0]['occ'] == sd['pos'][1]['occ']:
            return 'OCCUPANT_DUPLICATE'
    acts = [p['act'] for sd in st['sides'] for p in sd['pos'] if p['occ'] != NONE]
    if len(acts) != len(set(acts)):
        return 'ACTIVATION_DUPLICATE'
    return 'OK'


# ---------------------------------------------------------------- codec
def encode(st):
    b = bytearray(MAGIC + struct.pack('<HHII', KIND_BATTLE_STATE, SCHEMA, SEMANTICS, STATE_SIZE))
    b += st['fp']
    b += struct.pack('<QQQI', st['rng_state'], st['rng_inc'], st['draws'], st['next'])
    for sd in st['sides']:
        b += bytes([sd['member_count'], sd['brought']])
        for p in sd['pos']:
            b += bytes([p['occ']]) + struct.pack('<I', p['act'])
        for mem in sd['members']:
            b += struct.pack('<HHHB', mem['species'], mem['hp'], mem['hp_max'], mem['move_count'])
            for mv in mem['moves']:
                b += struct.pack('<HBB', mv['id'], mv['pp'], mv['pp_max'])
    assert len(b) == STATE_SIZE
    return bytes(b)


def parse(b):
    st = {'fp': bytes(b[20:52])}
    st['rng_state'], st['rng_inc'], st['draws'], st['next'] = struct.unpack_from('<QQQI', b, 52)
    st['sides'] = []
    for s in range(2):
        o = 80 + 150 * s
        sd = {'member_count': b[o], 'brought': b[o + 1],
              'pos': [{'occ': b[o + 2], 'act': struct.unpack_from('<I', b, o + 3)[0]},
                      {'occ': b[o + 7], 'act': struct.unpack_from('<I', b, o + 8)[0]}],
              'members': []}
        for m in range(MAX_ROSTER):
            mo = o + 12 + 23 * m
            species, hp, hp_max, mc = struct.unpack_from('<HHHB', b, mo)
            moves = []
            for k in range(MOVE_SLOTS):
                mid, pp, ppm = struct.unpack_from('<HBB', b, mo + 7 + 4 * k)
                moves.append({'id': mid, 'pp': pp, 'pp_max': ppm})
            sd['members'].append({'species': species, 'hp': hp, 'hp_max': hp_max, 'move_count': mc,
                                  'moves': moves})
        st['sides'].append(sd)
    return st


def decode(ctx, b):
    """Section 13.4 order; returns (status, invariant-or-None)."""
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


# ---------------------------------------------------------------- fixtures
def fixture_f1():
    return init_state(C1, setup_f1())


def fixture_f2():
    st = fixture_f1()
    s, inc = st['rng_state'], st['rng_inc']
    for _ in range(16):
        s = pcg_step(s, inc)
    st['rng_state'] = s
    st['draws'] = 16
    vacate(st, 0, 0)
    place(st, 0, 0, 3)
    vacate(st, 1, 1)
    st['sides'][0]['members'][0]['hp'] = 0
    st['sides'][0]['members'][1]['hp'] = 57
    st['sides'][0]['members'][1]['moves'][0]['pp'] = 0
    st['sides'][1]['members'][2]['hp'] = 0
    st['sides'][1]['members'][0]['moves'][3]['pp'] = 7
    assert check_state(C1, st) == 'OK'
    return st


def fixture_f3():
    return init_state(C3, setup_f3())


REGIONS = [('magic', 0, 8), ('kind', 8, 10), ('schema', 10, 12), ('semantics', 12, 16),
           ('total_length', 16, 20), ('fingerprint', 20, 52), ('rng.state', 52, 60),
           ('rng.inc', 60, 68), ('rng.draws', 68, 76), ('next_activation', 76, 80),
           ('side0.header', 80, 92), ('side0.members', 92, 230), ('side1.header', 230, 242),
           ('side1.members', 242, 380)]

V32 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 31, 32, 33, 63, 255, 256, 257, 258, 261, 262, 511, 65535,
       65536, 65552, 65636, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
V64 = V32 + [(1 << 63) - 1, 1 << 63, MASK64]


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


TARGETED = [((60, 0x6C), 'RNG_INC_EVEN'), ((76, 0), 'NEXT_ACTIVATION_ZERO'), ((80, 3), 'MEMBER_COUNT'),
            ((80, 7), 'MEMBER_COUNT'), ((92, 16), 'SPECIES_RANGE'), ((96, 0), 'HP_MAX_ZERO'),
            ((94, 101), 'HP_ABOVE_MAX'), ((98, 0), 'MOVE_COUNT'), ((98, 5), 'MOVE_COUNT'),
            ((99, 32), 'MOVE_ID_RANGE'), ((102, 0), 'PP_MAX_ZERO'), ((101, 6), 'PP_ABOVE_MAX'),
            ((103, 1), 'UNUSED_MOVE_NONZERO'), ((334, 1), 'UNUSED_MEMBER_NONZERO'),
            ((231, 0x17), 'BROUGHT_OUT_OF_RANGE'), ((81, 0x07), 'BROUGHT_COUNT'),
            ((82, 0xFF), 'EMPTY_WITH_ACTIVATION'), ((238, 0), 'OCCUPIED_WITHOUT_ACTIVATION'),
            ((232, 4), 'OCCUPANT_RANGE'), ((81, 0x3C), 'OCCUPANT_NOT_BROUGHT'),
            ((83, 5), 'ACTIVATION_NOT_ISSUED'), ((87, 2), 'OCCUPANT_DUPLICATE'),
            ((233, 1), 'ACTIVATION_DUPLICATE')]


def main():
    for name, ctx in (('C1', C1), ('C2', C2), ('C3', C3)):
        assert ctx.valid()
        print('context %s bytes %s' % (name, ctx.canonical_bytes().hex()))
        print('context %s fingerprint %s' % (name, ctx.fingerprint().hex()))

    fixtures = (('F1', C1, fixture_f1()), ('F2', C1, fixture_f2()), ('F3', C3, fixture_f3()))
    encoded = {}
    for name, ctx, st in fixtures:
        b = encode(st)
        encoded[name] = b
        assert decode(ctx, b) == ('OK', None)
        print('fixture %s sha256 %s' % (name, hashlib.sha256(b).hexdigest()))
        for off in range(0, STATE_SIZE, 20):
            print('fixture %s %03d: %s' % (name, off, b[off:off + 20].hex()))

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
    print('truncations 0..379 and +1 byte: all MALFORMED')
    for n in (20, 21, 51, 52, 79, 80, 229, 379):
        b = bytearray(f1[:n])
        struct.pack_into('<I', b, 16, n)
        assert decode(C1, b)[0] == 'MALFORMED'
    print('consistent short inputs: all MALFORMED')
    b = bytearray(f1)
    struct.pack_into('<H', b, 10, 2)
    assert decode(C1, b)[0] == 'SCHEMA_MISMATCH'
    b = bytearray(f1) + bytearray(20)
    struct.pack_into('<H', b, 10, 2)
    struct.pack_into('<I', b, 16, 400)
    assert decode(C1, b)[0] == 'SCHEMA_MISMATCH'
    print('schema 2 at 380 and 400 bytes: SCHEMA_MISMATCH')

    for label, ctx, base in (('F1/C1', C1, setup_f1()), ('F3/C3', C3, setup_f3())):
        classes = setup_sweep(ctx, base)
        tok = tbad = 0
        order = [('battle', 'rng_initstate'), ('battle', 'rng_initseq')]
        for s in range(2):
            for n in ('member_count', 'brought_mask', 'lead0', 'lead1', 'species_id', 'hp_max',
                      'move_count', 'move_id', 'pp_max'):
                order.append((s, n))
        for cls in order:
            ok, bad = classes[cls]
            tok += ok
            tbad += bad
            print('setup %s %s %s OK=%d INVALID=%d' % (label, cls[0], cls[1], ok, bad))
        print('setup %s TOTAL OK=%d INVALID=%d' % (label, tok, tbad))


if __name__ == '__main__':
    main()
