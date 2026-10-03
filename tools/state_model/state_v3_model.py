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
# The POOL state tail (decision 0015 section 7): schema 0x0203 = "v3 + pool tail rev 2", 248 bytes after the 1009.
# Rev 1 (0x0103, 42 bytes) is no schema of any kind any more: it is refused as unknown, there is no migration.
SCHEMA_POOL_TAIL_REV1 = 0x0103
SCHEMA_POOL_TAIL_REV2 = 0x0203
TAIL_FIELD_SIZE = 8                 # gravity_turns, then 7 reserved bytes
TAIL_SIDE_SIZE = 120                # 6 side bytes + 2 reserved, 2 positions of 32, 6 members of 8
TAIL_POS_SIZE = 32
TAIL_MEMBER_SIZE = 8
TAIL_SIZE = TAIL_FIELD_SIZE + 2 * TAIL_SIDE_SIZE
POOL_STATE_SIZE = STATE_SIZE + TAIL_SIZE
TAIL_MOVE_MAX = 5
TAIL_ENCORE_SLOT_MAX = 4
TAIL_ENCORE_TURNS_MAX = 4
TAIL_THROAT_CHOP_MAX = 2
TAIL_HEAL_BLOCK_MAX = 5
TAIL_WIDE_GUARD_MAX = 1
TAIL_PERISH_MAX = 4
TAIL_TAUNT_MAX = 4
TAIL_DISABLE_SLOT_MAX = 4
TAIL_DISABLE_TURNS_MAX = 5
TAIL_TRAP_TURNS_MAX = 8
TAIL_SOURCE_MAX = 4
TAIL_YAWN_MAX = 2
TAIL_STOCKPILE_MAX = 3
TAIL_FLAG_MAX = 1
TAIL_AURORA_VEIL_MAX = 8
TAIL_TOXIC_SPIKES_MAX = 2
TAIL_STEALTH_ROCK_MAX = 1
TAIL_SPIKES_MAX = 3
TAIL_STICKY_WEB_MAX = 1
TAIL_GRAVITY_MAX = 5
TAIL_ITEM_NONE = 255
TAIL_TOXIC_STAGE_MAX = 15
TAIL_TOXIC_STATUS = 6               # DUOFORGE_AILMENT_TOX: no state has it yet (the status bound of every kind is below)
# What the pool tables hold (decision 0015 section 2, tests/test_pool_tables.c): the bounds of the member overrides.
POOL_FORME_COUNT, POOL_MOVE_COUNT, POOL_ITEM_COUNT, POOL_ABILITY_COUNT = 346, 511, 166, 215
# The byte fields of a position's tail in their encoded order (offset 0 to 21), then two u16: substitute_hp at 22 and
# trap_move at 24, then 6 reserved bytes.
TAIL_POS_BYTE_FIELDS = ['last_move', 'encore_slot', 'encore_turns', 'throat_chop', 'heal_block', 'perish', 'taunt',
                        'disable_slot', 'disable_turns', 'imprison', 'must_recharge', 'trap_turns', 'trap_source',
                        'trap_band', 'leech_seed', 'yawn', 'focus_energy', 'stockpile', 'stockpile_def',
                        'stockpile_spd', 'charge', 'glaive_rush']
TAIL_SIDE_BYTE_FIELDS = ['wide_guard', 'aurora_veil', 'toxic_spikes', 'stealth_rock', 'spikes', 'sticky_web']
TYPE_COUNT = 18
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
WEATHER_SAND, WEATHER_SNOW = 3, 4  # POOL kinds only (Sandstorm, Snowscape)
TERRAIN_NONE, TERRAIN_GRASSY = 0, 1
TERRAIN_PSYCHIC = 2  # TEAM_C kinds only (Psychic Surge)
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
MOVE_SLOT_RECHARGE = 5  # step G17: the recharge turn (POOL kinds), no target, no Mega
SWITCH_NONE, SWITCH_MOVE, SWITCH_EMERGENCY_EXIT, SWITCH_FAINTED = 0, 1, 2, 3
SWITCH_FLIP_TURN = 4  # TEAM_C and POOL kinds (decision 0009)
SWITCH_UTURN = 5  # POOL kinds only: U-turn's flag, a damaging pivot that names its move (step G5)
VOL_CHOICE_LOCK = 64  # TEAM_C kinds only: Choice Scarf's lock, its move in locked_move
VOL_FOLLOW_ME = 8  # TEAM_C kinds only: Follow Me's volatile, until the residual
VOL_HELPING_HAND = 16  # TEAM_C kinds only: Helping Hand's volatile, until the residual
VOL_UNBURDEN = 32  # TEAM_C kinds only: Unburden's volatile, set when its holder's item is used
VOL_NEWLY_SWITCHED = 128  # TEAM_C kinds only: newlySwitched, until the end of the turn
ABILITY_UNBURDEN = 17  # 1 + DFI_ABILITY_UNBURDEN (src/data/extended_tables.h)
POSITION_FLAG_FOLLOW_ME = 1  # in duoforge_position_view.reserved (TEAM_C kinds)
POSITION_FLAG_HELPING_HAND = 2  # in duoforge_position_view.reserved (TEAM_C kinds)
POSITION_FLAG_UNBURDEN = 4  # in duoforge_position_view.reserved (TEAM_C kinds)
ITEM_CHOICE_SCARF = 16  # 1 + DFI_ITEM_CHOICESCARF (src/data/extended_tables.h)
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
        if self.data_kind == KIND_CLOSURE and (self.max_roster != MAX_ROSTER or self.brought_count != 4):
            return False  # the certified profile: register 6, bring 4 (decision 0010)
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

# TEAM_C contexts (decision 0009 section 3): the extended tables (closure plus
# Team C: 23 formes, 50 moves) and their hash, which
# tests/test_extended_tables.c recomputes from the extended canonical bytes.
EXTENDED_TABLE_HASH = bytes.fromhex('d16b1cef1b41f0a573ae74c10102c932c1f4de0ec3c1f33449f920e533a943e5')
KIND_TEAM_C, KIND_TEAM_C_DEV = 4, 5


class TeamCContext(ClosureContext):
    def __init__(self, data_kind, max_roster, brought_count):
        Context.__init__(self, data_kind, max_roster, brought_count, 346, 511, b'')

    def valid(self):
        if self.data_kind == KIND_TEAM_C and (self.max_roster != MAX_ROSTER or self.brought_count != 4):
            return False  # TEAM_C takes over the certified profile (decisions 0009, 0010)
        return (self.data_kind in (KIND_TEAM_C, KIND_TEAM_C_DEV) and 1 <= self.max_roster <= MAX_ROSTER
                and 1 <= self.brought_count <= self.max_roster)

    def canonical_bytes(self):
        b = MAGIC + struct.pack('<HHII', KIND_CONTEXT, SCHEMA, SEMANTICS, CONTEXT_BYTES_SIZE)
        b += bytes([2, 2, MAX_ROSTER, MOVE_SLOTS, self.data_kind, self.max_roster, self.brought_count])
        b += struct.pack('<HH', self.species_count, self.move_count)
        b += EXTENDED_TABLE_HASH
        assert len(b) == CONTEXT_BYTES_SIZE
        return b


KC = TeamCContext(KIND_TEAM_C, 6, 4)
KD = TeamCContext(KIND_TEAM_C_DEV, 6, 4)

# POOL contexts (decision 0015 section 2): the pool tables (the extended tables
# followed by the rows of the expansion steps and then every other forme, move,
# item and ability of the legal pool: 346 formes and 511 moves) and their hash,
# which tests/test_pool_tables.c recomputes from the pool canonical bytes: the
# pool layout over the pool data, then the family columns, the handler columns
# and the moves and abilities that each forme may have.
POOL_TABLE_HASH = bytes.fromhex('b75677f73ff8dc582f53f036b5192e3f074577cd2d1cd320c84119e7b801b014')
KIND_POOL, KIND_POOL_DEV = 6, 7


class PoolContext(ClosureContext):
    def __init__(self, data_kind, max_roster, brought_count):
        Context.__init__(self, data_kind, max_roster, brought_count, 346, 511, b'')

    def valid(self):
        if self.data_kind == KIND_POOL and (self.max_roster != MAX_ROSTER or self.brought_count != 4):
            return False  # POOL takes over the certified profile (decisions 0010, 0015)
        return (self.data_kind in (KIND_POOL, KIND_POOL_DEV) and 1 <= self.max_roster <= MAX_ROSTER
                and 1 <= self.brought_count <= self.max_roster)

    def canonical_bytes(self):
        b = MAGIC + struct.pack('<HHII', KIND_CONTEXT, SCHEMA, SEMANTICS, CONTEXT_BYTES_SIZE)
        b += bytes([2, 2, MAX_ROSTER, MOVE_SLOTS, self.data_kind, self.max_roster, self.brought_count])
        b += struct.pack('<HH', self.species_count, self.move_count)
        b += POOL_TABLE_HASH
        assert len(b) == CONTEXT_BYTES_SIZE
        return b


KP = PoolContext(KIND_POOL, 6, 4)
KPD = PoolContext(KIND_POOL_DEV, 6, 4)

# What each combat kind may carry. The values of Team C's mechanics (poison,
# Psychic Terrain, Flip Turn's switch flag, the new volatile bits) are valid
# under the TEAM_C and POOL kinds, which have all of them; the certified
# profile (exactly six registered members) is CLOSURE's, TEAM_C's and POOL's.
COMBAT_KINDS = (KIND_CLOSURE, KIND_CLOSURE_DEV, KIND_TEAM_C, KIND_TEAM_C_DEV, KIND_POOL, KIND_POOL_DEV)
EXTENDED_KINDS = (KIND_TEAM_C, KIND_TEAM_C_DEV, KIND_POOL, KIND_POOL_DEV)
POOL_KINDS = (KIND_POOL, KIND_POOL_DEV)
FULL_ROSTER_KINDS = (KIND_CLOSURE, KIND_TEAM_C, KIND_POOL)


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


def has_pool_tail(ctx):
    return ctx.data_kind in (KIND_POOL, KIND_POOL_DEV)


def empty_tail_pos():
    p = {f: 0 for f in TAIL_POS_BYTE_FIELDS}
    p['substitute_hp'] = 0
    p['trap_move'] = 0
    return p


def empty_tail_side():
    s = {f: 0 for f in TAIL_SIDE_BYTE_FIELDS}
    s['pos'] = [empty_tail_pos(), empty_tail_pos()]
    for f in ('ability_now', 'forme_now', 'soak', 'item_now', 'toxic_stage'):
        s[f] = [0] * MAX_ROSTER
    return s


def empty_tail():
    return {'gravity': 0, 'sides': [empty_tail_side(), empty_tail_side()]}


def empty_state(ctx):
    # 'tailed': the state carries the POOL tail (schema 0x0203); 'tail': the field block and the two sides, all zero
    # unless a test sets them.
    return {'tailed': has_pool_tail(ctx), 'tail': empty_tail(),
            'fp': ctx.fingerprint(), 'rng_state': 0, 'rng_inc': 0, 'draws': 0, 'next': 1,
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
              'SEALED_RULE', 'SEALED_COMMAND', 'ACTIVATION_DUPLICATE', 'SEEN_MASK', 'KNOWLEDGE', 'QUEUE',
              'TAIL_KIND', 'TAIL_SIDE', 'TAIL_POSITION', 'TAIL_MEMBER', 'TAIL_SCHEMA', 'TAIL_RESERVED', 'TAIL_FIELD']
assert len(INVARIANTS) == 50


def cmd_is_zero(c):
    return not (c['kind'] or c['move_slot'] or c['target'] or c['mega'] or c['reserve'])


def sealed_cmd_valid(c, mc):
    if c['kind'] == SLOT_MOVE:
        if c['move_slot'] in (MOVE_SLOT_STRUGGLE, MOVE_SLOT_RECHARGE):
            target_ok = c['target'] == TARGET_NONE
        else:
            target_ok = c['move_slot'] < MOVE_SLOTS and (c['target'] < 4 or c['target'] == TARGET_NONE)
        # Struggle never carries a Mega declaration.
        mega_max = 0 if c['move_slot'] in (MOVE_SLOT_STRUGGLE, MOVE_SLOT_RECHARGE) else 1
        return target_ok and c['mega'] <= mega_max and c['reserve'] == 0
    if c['kind'] == SLOT_SWITCH:
        return c['reserve'] < mc and not (c['move_slot'] or c['target'] or c['mega'])
    if c['kind'] in (SLOT_NONE, SLOT_PASS):
        return not (c['move_slot'] or c['target'] or c['mega'] or c['reserve'])
    return False


def member_extra_is_zero(mem):
    return not (any(mem['stats']) or mem['is_mega'] or mem['gender'] or mem['nature'] or any(mem['sp'])
                or mem['status'] or mem['status_counter'] or mem['item'] or mem['item_consumed']
                or mem['ability'])


def volatile_valid(p, move_count, switch_flag_max=None, vol_flags_mask=None):
    """Value ranges of an occupied position's volatile block."""
    if p['switch_flag'] > (SWITCH_FAINTED if switch_flag_max is None else switch_flag_max):
        return False
    mask = VOL_FLAGS_MAX if vol_flags_mask is None else vol_flags_mask
    if any(s > STAGE_MAX for s in p['stages']) or p['flags'] & ~mask:
        return False
    if p['stall_level'] > STALL_LEVEL_MAX or p['stall_turns'] > STALL_TURNS_MAX:
        return False
    if (p['stall_level'] == 0) != (p['stall_turns'] == 0):
        return False
    if p['confusion_turns'] > CONFUSION_TURNS_MAX or p['charge_turns'] > CHARGE_TURNS_MAX:
        return False
    # The locked-move byte: a charging two-turn move, a choice lock, or both on one move.
    choice = bool(p['flags'] & VOL_CHOICE_LOCK)
    if p['locked_move'] > move_count or (p['locked_move'] != 0) != (p['charge_turns'] != 0 or choice):
        return False
    if p['charge_turns'] == 0:
        return p['locked_target'] == 0
    return p['locked_target'] < 4 or p['locked_target'] == TARGET_NONE


def check_side(ctx, st, s):
    sd = st['sides'][s]
    kind = st['boundary']
    requested = (st['request_mask'] >> s) & 1
    mc = sd['member_count']
    if not (ctx.brought_count <= mc <= ctx.max_roster):
        return 'MEMBER_COUNT'
    if ctx.data_kind in FULL_ROSTER_KINDS and mc != ctx.max_roster:
        return 'MEMBER_COUNT'  # the certified profile registers exactly six (decisions 0010, 0009, 0015)
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
        else:
            team_c = ctx.data_kind in EXTENDED_KINDS
            mem = sd['members'][p['occ']]
            team_c_mask = (VOL_FLAGS_MAX | VOL_FOLLOW_ME | VOL_HELPING_HAND | VOL_UNBURDEN | VOL_CHOICE_LOCK |
                           VOL_NEWLY_SWITCHED)
            switch_max = SWITCH_UTURN if ctx.data_kind in (KIND_POOL, KIND_POOL_DEV) else SWITCH_FLIP_TURN if team_c else None
            if not volatile_valid(p, mem['move_count'], switch_max,
                                  team_c_mask if team_c else None):
                return 'VOLATILE'
            if p['flags'] & VOL_CHOICE_LOCK and (mem['item'] != ITEM_CHOICE_SCARF or mem['item_consumed']):
                return 'VOLATILE'
            # The holder is the Pokemon whose ability now is Unburden: the sheet's, or the tail's ability_now.
            ability_now = (st['tail']['sides'][s]['ability_now'][p['occ']] if has_pool_tail(ctx) else 0) or mem['ability']
            if p['flags'] & VOL_UNBURDEN and (ability_now != ABILITY_UNBURDEN or not mem['item']
                                              or not mem['item_consumed']):
                return 'VOLATILE'
            # Follow Me and Helping Hand end in the residual, newlySwitched at the end of the turn.
            if kind == TURN and p['flags'] & (VOL_FOLLOW_ME | VOL_HELPING_HAND | VOL_NEWLY_SWITCHED):
                return 'VOLATILE'
            if kind == REPLACEMENT and p['flags'] & (VOL_FOLLOW_ME | VOL_HELPING_HAND):
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
            if m < opp['member_count'] and opp['members'][m]['is_mega']:
                return False  # a Mega Evolution happens on the field, in view
            continue
        mem = opp['members'][m]
        if not hp_display_valid(k['hp_pct'], k['hp_flag']):
            return False
        # Revealed facts are facts: a consumed item, a Mega forme.
        if k['revealed'] > REVEALED_ITEM_CONSUMED | REVEALED_MEGA:
            return False
        if k['revealed'] & REVEALED_ITEM_CONSUMED and mem['item_consumed'] != 1:
            return False
        if bool(k['revealed'] & REVEALED_MEGA) != (mem['is_mega'] == 1):
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
        return (bound and r['reserve'] == 0 and r['move_slot'] <= MOVE_SLOT_RECHARGE
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
    if (st['weather'] > (WEATHER_SNOW if ctx.data_kind in POOL_KINDS else WEATHER_SUN) or st['weather_turns'] > FIELD_TURNS_MAX
            or (st['weather'] == 0) != (st['weather_turns'] == 0)
            or st['terrain'] > (TERRAIN_PSYCHIC if ctx.data_kind in EXTENDED_KINDS else TERRAIN_GRASSY)
            or st['terrain_turns'] > FIELD_TURNS_MAX
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
    return check_tail(ctx, st)


def tail_is_zero(tail):
    def side_zero(ts):
        return (all(ts[f] == 0 for f in TAIL_SIDE_BYTE_FIELDS)
                and all(v == 0 for p in ts['pos'] for v in p.values())
                and all(v == 0 for f in ('ability_now', 'forme_now', 'soak', 'item_now', 'toxic_stage') for v in ts[f]))
    return tail['gravity'] == 0 and all(side_zero(ts) for ts in tail['sides'])


def tail_pos_valid(ctx, tp, flat, mem):
    """The tail of a standing occupant's position (the rules of decision 0015 section 7)."""
    mc = mem['move_count']
    if not (tp['last_move'] <= TAIL_MOVE_MAX and (tp['last_move'] == TAIL_MOVE_MAX or tp['last_move'] <= mc)
            and tp['encore_slot'] <= TAIL_ENCORE_SLOT_MAX and tp['encore_slot'] <= mc
            and tp['encore_turns'] <= TAIL_ENCORE_TURNS_MAX and (tp['encore_slot'] == 0) == (tp['encore_turns'] == 0)):
        return False
    if not (tp['throat_chop'] <= TAIL_THROAT_CHOP_MAX and tp['heal_block'] <= TAIL_HEAL_BLOCK_MAX
            and tp['perish'] <= TAIL_PERISH_MAX and tp['taunt'] <= TAIL_TAUNT_MAX and tp['yawn'] <= TAIL_YAWN_MAX):
        return False
    if not (tp['disable_slot'] <= TAIL_DISABLE_SLOT_MAX and tp['disable_slot'] <= mc
            and tp['disable_turns'] <= TAIL_DISABLE_TURNS_MAX and (tp['disable_slot'] == 0) == (tp['disable_turns'] == 0)):
        return False
    if not all(tp[f] <= TAIL_FLAG_MAX for f in ('imprison', 'must_recharge', 'focus_energy', 'charge', 'glaive_rush')):
        return False
    if tp['substitute_hp'] > mem['hp_max'] // 4:
        return False
    if not (tp['trap_turns'] <= TAIL_TRAP_TURNS_MAX and tp['trap_source'] <= TAIL_SOURCE_MAX
            and tp['trap_source'] != flat + 1 and tp['trap_move'] <= ctx.move_count
            and (tp['trap_turns'] == 0) == (tp['trap_source'] == 0) and (tp['trap_turns'] == 0) == (tp['trap_move'] == 0)
            and tp['trap_band'] <= TAIL_FLAG_MAX and (tp['trap_turns'] != 0 or tp['trap_band'] == 0)):
        return False
    if not (tp['leech_seed'] <= TAIL_SOURCE_MAX and tp['leech_seed'] != flat + 1):
        return False
    return (tp['stockpile'] <= TAIL_STOCKPILE_MAX and tp['stockpile_def'] <= tp['stockpile']
            and tp['stockpile_spd'] <= tp['stockpile'])


def check_tail(ctx, st):
    """The POOL tail: absent (all zero) under every other kind; under POOL each value in range, none at a position
    without a standing occupant, the member overrides only where they can be (a soak type, a current ability and a
    toxic stage on a standing member of the field; step G11: a Mega Evolved member can be Soaked, so the Mega forme is
    no part of the rule)."""
    tail = st['tail']
    if not has_pool_tail(ctx):
        return 'OK' if tail_is_zero(tail) else 'TAIL_KIND'
    if tail['gravity'] > TAIL_GRAVITY_MAX:
        return 'TAIL_FIELD'
    for s in range(2):
        ts, sd = tail['sides'][s], st['sides'][s]
        if (ts['wide_guard'] > TAIL_WIDE_GUARD_MAX or ts['aurora_veil'] > TAIL_AURORA_VEIL_MAX
                or ts['toxic_spikes'] > TAIL_TOXIC_SPIKES_MAX or ts['stealth_rock'] > TAIL_STEALTH_ROCK_MAX
                or ts['spikes'] > TAIL_SPIKES_MAX or ts['sticky_web'] > TAIL_STICKY_WEB_MAX):
            return 'TAIL_SIDE'
        for p in range(2):
            tp = ts['pos'][p]
            occ = sd['pos'][p]['occ']
            standing = occ < MAX_ROSTER and occ < sd['member_count'] and sd['members'][occ]['hp'] != 0
            if not standing:
                if any(v != 0 for v in tp.values()):
                    return 'TAIL_POSITION'
                continue
            if not tail_pos_valid(ctx, tp, 2 * s + p, sd['members'][occ]):
                return 'TAIL_POSITION'
        for m in range(MAX_ROSTER):
            ab, fo, ty, it, tx = ts['ability_now'][m], ts['forme_now'][m], ts['soak'][m], ts['item_now'][m], ts['toxic_stage'][m]
            if ab == 0 and fo == 0 and ty == 0 and it == 0 and tx == 0:
                continue
            if m >= sd['member_count']:
                return 'TAIL_MEMBER'
            mem = sd['members'][m]
            on_field = mem['hp'] != 0 and (sd['pos'][0]['occ'] == m or sd['pos'][1]['occ'] == m)
            if ty != 0 and (ty > TYPE_COUNT or not on_field):
                return 'TAIL_MEMBER'
            if ab != 0 and (ab > POOL_ABILITY_COUNT or not on_field):
                return 'TAIL_MEMBER'
            if fo > POOL_FORME_COUNT:
                return 'TAIL_MEMBER'
            if it != 0 and it != TAIL_ITEM_NONE and it > POOL_ITEM_COUNT:
                return 'TAIL_MEMBER'
            if tx != 0 and (tx > TAIL_TOXIC_STAGE_MAX or not on_field or mem['status'] != TAIL_TOXIC_STATUS):
                return 'TAIL_MEMBER'
    return 'OK'


# ---------------------------------------------------------------- codec
POS_BYTE_FIELDS = ['flags', 'stall_level', 'stall_turns', 'confusion_turns', 'charge_turns', 'locked_move',
                   'locked_target', 'move_actions', 'switch_flag']
MEMBER_HEAD_FIELDS = ['move_count', 'mega_capable', 'is_mega', 'gender', 'nature']
MEMBER_TAIL_FIELDS = ['status', 'status_counter', 'item', 'item_consumed', 'ability']
QUEUE_BYTE_FIELDS = ['kind', 'side', 'slot', 'move_slot', 'target', 'reserve']


def encode(st):
    schema, size = (SCHEMA_POOL_TAIL_REV2, POOL_STATE_SIZE) if st['tailed'] else (SCHEMA, STATE_SIZE)
    b = bytearray(MAGIC + struct.pack('<HHII', KIND_BATTLE_STATE, schema, SEMANTICS, size))
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
    if st['tailed']:
        b += tail_bytes(st['tail'])
        assert len(b) == POOL_STATE_SIZE
    return bytes(b)


def tail_bytes(tail):
    """The 248 encoded bytes of a tail (the layout of src/codec/state_codec.h), reserved bytes zero."""
    out = bytearray([tail['gravity']]) + bytes(TAIL_FIELD_SIZE - 1)
    for ts in tail['sides']:
        out += bytes([ts[f] for f in TAIL_SIDE_BYTE_FIELDS]) + bytes(2)
        for tp in ts['pos']:
            out += bytes([tp[f] for f in TAIL_POS_BYTE_FIELDS])
            out += struct.pack('<HH', tp['substitute_hp'], tp['trap_move']) + bytes(6)
        for m in range(MAX_ROSTER):
            out += struct.pack('<HH', ts['ability_now'][m], ts['forme_now'][m])
            out += bytes([ts['soak'][m], ts['item_now'][m], ts['toxic_stage'][m], 0])
    assert len(out) == TAIL_SIZE
    return bytes(out)


def tail_reserved_offsets():
    """The offsets (within the tail) of the 47 reserved bytes."""
    offs = list(range(1, TAIL_FIELD_SIZE))
    for s in range(2):
        so = TAIL_FIELD_SIZE + TAIL_SIDE_SIZE * s
        offs += [so + 6, so + 7]
        for p in range(2):
            offs += [so + 8 + TAIL_POS_SIZE * p + 26 + i for i in range(6)]
        offs += [so + 72 + TAIL_MEMBER_SIZE * m + 7 for m in range(MAX_ROSTER)]
    assert len(offs) == 47
    return offs


def tail_reserved_zero(b):
    return all(b[STATE_SIZE + o] == 0 for o in tail_reserved_offsets())


def parse_tail(b):
    o = STATE_SIZE
    tail = {'gravity': b[o], 'sides': []}
    for s in range(2):
        so = o + TAIL_FIELD_SIZE + TAIL_SIDE_SIZE * s
        ts = {f: b[so + i] for i, f in enumerate(TAIL_SIDE_BYTE_FIELDS)}
        ts['pos'] = []
        for p in range(2):
            po = so + 8 + TAIL_POS_SIZE * p
            tp = {f: b[po + i] for i, f in enumerate(TAIL_POS_BYTE_FIELDS)}
            tp['substitute_hp'], tp['trap_move'] = struct.unpack_from('<HH', b, po + 22)
            ts['pos'].append(tp)
        for f in ('ability_now', 'forme_now', 'soak', 'item_now', 'toxic_stage'):
            ts[f] = []
        for m in range(MAX_ROSTER):
            mo = so + 72 + TAIL_MEMBER_SIZE * m
            ab, fo = struct.unpack_from('<HH', b, mo)
            ts['ability_now'].append(ab)
            ts['forme_now'].append(fo)
            ts['soak'].append(b[mo + 4])
            ts['item_now'].append(b[mo + 5])
            ts['toxic_stage'].append(b[mo + 6])
        tail['sides'].append(ts)
    return tail


def parse(b):
    st = {'fp': bytes(b[20:52]), 'tailed': False, 'tail': empty_tail()}
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
    # Rev 1 of the tail (0x0103) is refused here like every schema that is not v3 or v3 + pool tail rev 2.
    if kind != KIND_BATTLE_STATE or schema not in (SCHEMA, SCHEMA_POOL_TAIL_REV2):
        return 'SCHEMA_MISMATCH', None
    if semantics != SEMANTICS:
        return 'SEMANTICS_MISMATCH', None
    if total != size:
        return 'MALFORMED', None
    tailed = schema == SCHEMA_POOL_TAIL_REV2
    if size != (POOL_STATE_SIZE if tailed else STATE_SIZE):
        return 'MALFORMED', None
    if bytes(b[20:52]) != ctx.fingerprint():
        return 'CONTEXT_MISMATCH', None
    # The schema is the one of the context's kind; the reserved bytes of the tail are zero (both are invariants).
    if tailed != has_pool_tail(ctx):
        return 'MALFORMED', 'TAIL_SCHEMA'
    if tailed and not tail_reserved_zero(b):
        return 'MALFORMED', 'TAIL_RESERVED'
    st = parse(b)
    if tailed:
        st['tailed'] = True
        st['tail'] = parse_tail(b)
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
    target, no Mega declaration) when the occupant has no selectable move."""
    sd = st['sides'][side]
    pos = sd['pos'][slot]
    out = []
    if st['boundary'] == TURN:
        if pos['occ'] == NONE or sd['members'][pos['occ']]['hp'] == 0:
            return [cmd(SLOT_PASS)]
        mem = sd['members'][pos['occ']]
        combat = ctx.data_kind in COMBAT_KINDS
        # A charging two-turn move (combat data): that move at the stored target only.
        if combat and pos['charge_turns'] != 0:
            return [cmd(SLOT_MOVE, pos['locked_move'] - 1, pos['locked_target'], 0)]
        # A choice lock (TEAM_C kinds): only the locked move; it does not trap.
        choice = pos['flags'] & VOL_CHOICE_LOCK
        megas = [0, 1] if mem['mega_capable'] and not sd['mega_used'] else [0]
        for k in range(mem['move_count']):
            mv = mem['moves'][k]
            if mv['pp'] == 0 or (choice and k + 1 != pos['locked_move']):
                continue
            # Champions disables Fake Out (closure move 2) after a move action.
            if combat and mv['id'] == 2 and pos['move_actions'] != 0:
                continue
            for tgt in selectable_targets(ctx.table[mv['id']], side, slot):
                for mg in megas:
                    out.append(cmd(SLOT_MOVE, k, tgt, mg))
        if not out:
            # Struggle locks the request: no Mega declaration with it.
            out.append(cmd(SLOT_MOVE, MOVE_SLOT_STRUGGLE, TARGET_NONE, 0))
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
PP_EXACT, PP_DERIVED, PP_UNKNOWN = 1, 2, 3
MOVE_SLOT_NONE = 0xFF  # observation v2: no locked move
TARGET_NONE = 0xFF  # observation v2: no locked target (none, or the foe's)
FLAG_NONE, FLAG_RED, FLAG_YELLOW, FLAG_GREEN = 0, 1, 2, 3
LOC_UNDETERMINED, LOC_BENCH, LOC_ACTIVE, LOC_NOT_BROUGHT = 0, 1, 2, 3
OBSERVATION_SIZE = 736
MEMBER_VIEW_SIZE = 52


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
    """Observation v2 of `player` (decision 0007): what a human at the table
    knows. 736 bytes, absolute side order. Own side exact (stats and stat
    points included), except the turns
    the game never shows (sleep, freeze, confusion). Open sheets of both
    sides. Public facts of the battle. For the opponent only the player's
    knowledge: seen mask, last HP display, items seen used up, Mega Evolutions
    seen, move uses seen (its PP is the maximum minus those uses). Never the
    opponent's exact HP or PP, bench or pick order, sealed commands, the
    target of its charged move, or the RNG."""
    requested = (st['request_mask'] >> player) & 1
    b = bytearray(struct.pack('<IBBBB', st['epoch'], st['boundary'], player, requested,
                              st['sides'][player]['requested_slots'] if requested else 0))
    b += struct.pack('<H', st['turn'])
    b += bytes([st['weather'], st['weather_turns'], st['terrain'], st['terrain_turns'], st['trick_room_turns'], 0])
    for s in range(2):
        sd = st['sides'][s]
        own = s == player
        seen = st['sides'][player]['seen']
        occupants = [p['occ'] for p in sd['pos']]
        for m in range(MAX_ROSTER):
            mem = sd['members'][m]
            if m >= sd['member_count']:
                b += bytes(MEMBER_VIEW_SIZE)
                continue
            pp_max = [mv['pp_max'] for mv in mem['moves']]
            if own:
                hp, hp_max, hp_kind, flag = mem['hp'], mem['hp_max'], HP_EXACT, FLAG_NONE
                pp, pp_kind = [mv['pp'] for mv in mem['moves']], PP_EXACT
                is_mega, item_used = mem['is_mega'], mem['item_consumed']
                status = mem['status'] if mem['hp'] else 0
                if st['boundary'] == TEAM_SELECTION:
                    loc = LOC_UNDETERMINED
                elif m in occupants:
                    loc = LOC_ACTIVE
                elif (sd['brought'] >> m) & 1:
                    loc = LOC_BENCH
                else:
                    loc = LOC_NOT_BROUGHT
            else:
                know = st['sides'][player]['know'][m]
                pp = [mx - u if u < mx else 0 for mx, u in zip(pp_max, know['used'])]
                pp_kind = PP_DERIVED
                is_mega = 1 if know['revealed'] & REVEALED_MEGA else 0
                item_used = 1 if know['revealed'] & REVEALED_ITEM_CONSUMED else 0
                if (seen >> m) & 1:
                    hp, hp_max, hp_kind, flag = know['hp_pct'], 100, HP_PERCENT, know['hp_flag']
                    loc = LOC_ACTIVE if m in occupants else LOC_BENCH
                    status = mem['status'] if know['hp_pct'] else 0
                else:
                    hp, hp_max, hp_kind, flag = 0, 0, HP_UNKNOWN, FLAG_NONE
                    loc = LOC_UNDETERMINED
                    status = 0
            b += struct.pack('<HHH', mem['species'], hp, hp_max)
            b += struct.pack('<HHHH', *[mv['id'] for mv in mem['moves']])
            b += struct.pack('<5H', *(mem['stats'] if own else [0] * 5))
            b += bytes(pp) + bytes(pp_max)
            b += bytes(mem['sp'] if own else [0] * 6)
            b += bytes([mem['move_count'], hp_kind, flag, pp_kind, loc, mem['mega_capable'], is_mega,
                        mem['gender'], mem['nature'], mem['ability'], mem['item'], item_used, status, 0])
        for k in range(2):
            pos = sd['pos'][k]
            if pos['occ'] == NONE:
                b += bytes([6] * 7 + [0, 0, MOVE_SLOT_NONE, TARGET_NONE, 0, 0, 0, 0, 0])
                continue
            locked = pos['locked_move'] != 0
            b += bytes(pos['stages'])
            b += bytes([1 if pos['confusion_turns'] else 0, 1 if pos['charge_turns'] else 0,
                        pos['locked_move'] - 1 if locked else MOVE_SLOT_NONE,
                        pos['locked_target'] if pos['charge_turns'] and own else TARGET_NONE,
                        1 if pos['move_actions'] else 0, pos['stall_level'],
                        1 if pos['flags'] & VOL_FLASH_FIRE else 0,
                        1 if pos['flags'] & VOL_PROTECT else 0,
                        (POSITION_FLAG_FOLLOW_ME if pos['flags'] & VOL_FOLLOW_ME else 0) |
                        (POSITION_FLAG_HELPING_HAND if pos['flags'] & VOL_HELPING_HAND else 0) |
                        (POSITION_FLAG_UNBURDEN if pos['flags'] & VOL_UNBURDEN else 0)])
        side_requested = (st['request_mask'] >> s) & 1
        b += bytes([sd['member_count'], occupants[0], occupants[1], sd['mega_used']])
        b += bytes(sd['order'] if own else [NONE] * MAX_ROSTER)
        b += bytes([side_requested, sd['requested_slots'] if side_requested else 0,
                    sd['reflect'], sd['light_screen'], sd['tailwind'], 0])
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
    ('F5', S1 + P(0, 18), 4, 'VOLATILE'), ('F5', S0 + P(1, 17), 2, 'VOLATILE'), ('F1', S0 + P(0, 20), 4, 'VOLATILE'),
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


# ---------------------------------------------------------------- the POOL tail (decision 0015 section 7)
# The maximum HP of the members 0 and 1 of both sides in the state of tests/test_pool_tail.c (Team A against Team B
# under POOL: the leads). The Substitute bound is a quarter of it, so it is part of the example; the test asserts the
# values, so a drift of the teams or the formulas is noticed there.
LEAD_HP_MAX = [[193, 192], [197, 182]]


def tail_pos(**kw):
    p = empty_tail_pos()
    p.update(kw)
    return p


# A tail with a value in every field that a state can hold, for the state of tests/test_pool_tail.c: both sides have
# members 0 and 1 on the field (all standing, four moves, none Mega Evolved, no ailment), so the toxic stages are the
# one thing that stays zero (no state has the status they need). Flat positions: side 0 is 0 and 1, side 1 is 2 and 3.
def tail_example():
    t = empty_tail()
    t['gravity'] = 5
    a, c = t['sides']
    a.update(wide_guard=1, aurora_veil=8, toxic_spikes=2, stealth_rock=1, spikes=3, sticky_web=1)
    a['pos'][0] = tail_pos(last_move=1, encore_slot=2, encore_turns=3, throat_chop=2, heal_block=5, perish=3, taunt=4,
                           disable_slot=3, disable_turns=5, imprison=1, trap_turns=6, trap_source=3, trap_band=1,
                           leech_seed=4, yawn=2, focus_energy=1, stockpile=3, stockpile_def=2, stockpile_spd=3,
                           charge=1, substitute_hp=20, trap_move=37)
    a['pos'][1] = tail_pos(last_move=5, throat_chop=1, heal_block=2, perish=1, taunt=1, must_recharge=1, stockpile=1,
                           stockpile_def=1, glaive_rush=1, substitute_hp=1)
    a['ability_now'][:2] = [5, POOL_ABILITY_COUNT]
    a['forme_now'][:3] = [300, POOL_FORME_COUNT, 1]
    a['soak'][:2] = [5, 18]
    a['item_now'][:4] = [12, TAIL_ITEM_NONE, POOL_ITEM_COUNT, 1]
    c.update(spikes=1)
    c['pos'][0] = tail_pos(last_move=4, encore_slot=4, encore_turns=1, heal_block=3, leech_seed=1, yawn=1)
    c['pos'][1] = tail_pos(trap_turns=1, trap_source=3, trap_move=511)
    c['ability_now'][0] = 1
    c['forme_now'][5] = 7
    c['soak'][0] = 1
    c['item_now'][5] = 100
    return t


def tail_model_state():
    st = empty_state(KP)
    for s, sd in enumerate(st['sides']):
        sd['member_count'] = 6
        sd['pos'][0]['occ'], sd['pos'][1]['occ'] = 0, 1
        for m, mem in enumerate(sd['members']):
            mem['hp'], mem['move_count'] = 1, 4
            mem['hp_max'] = LEAD_HP_MAX[s][m] if m < 2 else 1
    return st


def tail_outcome(raw):
    """decode() of the tail alone: the reserved bytes first, then the tail rules, over tail_model_state()."""
    full = bytes(STATE_SIZE) + raw
    if not tail_reserved_zero(full):
        return 'TAIL_RESERVED'
    st = tail_model_state()
    st['tail'] = parse_tail(full)
    return check_tail(KP, st)


SWEEP_COLUMNS = ('OK', 'TAIL_SIDE', 'TAIL_POSITION', 'TAIL_MEMBER', 'TAIL_FIELD', 'TAIL_RESERVED')


def print_pool_tail():
    example = tail_example()
    base_tail = tail_bytes(example)
    assert tail_outcome(base_tail) == 'OK' and len(base_tail) == TAIL_SIZE
    head = MAGIC + struct.pack('<HHII', KIND_BATTLE_STATE, SCHEMA_POOL_TAIL_REV2, SEMANTICS, POOL_STATE_SIZE)
    print('pool_tail envelope %s' % head.hex())
    print('pool_tail example %s' % base_tail.hex())
    reserved = set(tail_reserved_offsets())
    for off in range(TAIL_SIZE):
        counts = {}
        for v in range(256):
            if v == base_tail[off]:
                continue
            raw = bytearray(base_tail)
            raw[off] = v
            r = tail_outcome(bytes(raw))
            counts[r] = counts.get(r, 0) + 1
        assert (off in reserved) == (counts.get('TAIL_RESERVED', 0) == 255)
        print('pool_tail_sweep %3d %s' % (off, ' '.join('%s=%d' % kv for kv in sorted(counts.items()))))
        print('pool_tail_sweep_c %3d {%s},' % (off, ', '.join(str(counts.get(c, 0)) for c in SWEEP_COLUMNS)))
    # Decode order with the tail: the schema of the artifact against the context's kind.
    for ctx_name, ctx in (('C1', C1), ('KP', KP)):
        st = empty_state(ctx)
        st['tailed'] = has_pool_tail(ctx)
        b = bytearray(encode(st))
        print('pool_tail decode %s size %d status %s' % (ctx_name, len(b), decode(ctx, b)))
    for label, ctx, tailed in (('KP', KP, False), ('C1', C1, True)):
        st = empty_state(ctx)
        st['tailed'] = tailed
        b = bytearray(encode(st))
        print('pool_tail wrong-schema %s tailed=%s %s' % (label, tailed, decode(ctx, b)))
    # Rev 1 (0x0103) and schema 4 are unknown schemas of every kind: an artifact that carries them is refused.
    for label, ctx, tailed in (('KP', KP, False), ('C1', C1, True)):
        st = empty_state(ctx)
        st['tailed'] = tailed
        for schema in (SCHEMA_POOL_TAIL_REV1, 4):
            b = bytearray(encode(st))
            struct.pack_into('<H', b, 10, schema)
            print('pool_tail schema %#06x %s tailed=%s %s' % (schema, label, tailed, decode(ctx, b)))


def main():
    sys.stdout.reconfigure(newline=chr(10))  # LF on every platform
    if '--pool-tail' in sys.argv[1:]:
        print_pool_tail()
        return
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
    for name, ctx in (('K1', K1), ('K2', K2), ('KC', KC), ('KD', KD), ('KP', KP), ('KPD', KPD)):
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

    print_pool_tail()

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
