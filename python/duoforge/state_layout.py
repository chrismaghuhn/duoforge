"""The canonical state encoding's fields by name, from the generated offsets (_state_layout.OFFSETS, the C macros
DFI_ENC_* of src/codec/state_codec.h). The public record's `state` is this encoding with the hidden fields masked
(decision 0023); the live tracker assembles one in this layout and the engine checks it (from_view, then public, byte
for byte). fields() lists every field as (name, start, size), each byte of the POOL encoding exactly once; diff(a, b)
names the fields where two encodings differ. Layout only: no battle rule here."""
from ._state_layout import OFFSETS as _O

SIDE_COUNT = 2
ACTIVE_PER_SIDE = 2
MAX_ROSTER = 6
QUEUE_CAPACITY = 12
MOVE_SLOTS = 4
V3_SIZE = 1009  # the v3 body; the POOL kinds add the tail (DUOFORGE_VIEW_STATE_MAX in all)


def _o(name):
    return _O["DFI_ENC_" + name]


def _block(prefix, base, members, size):
    """members: {name: relative offset} of one block of `size` bytes; each field runs to the next one."""
    ordered = sorted(members.items(), key=lambda kv: kv[1])
    out = []
    for i, (name, off) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else size
        if end == off and name == "reserved":
            continue  # an empty reserved block (the POOL tail side's since rev 4)
        out.append((f"{prefix}{name}", base + off, end - off))
    return out


def _sub(names):
    """{field: offset} of the DFI_ENC_<group>_<FIELD>_OFF macros given as (field, macro) pairs."""
    return {field: _o(macro) for field, macro in names}


def fields(pool=True):
    """(name, start, size) of every field, in order; pool=False stops before the POOL tail."""
    out = _block("", 0, {
        "envelope": 0, "fingerprint": _o("FINGERPRINT_OFF"), "rng.state": _o("RNG_STATE_OFF"),
        "rng.inc": _o("RNG_INC_OFF"), "rng.draws": _o("RNG_DRAWS_OFF"),
        "next_activation_id": _o("NEXT_ACTIVATION_OFF"), "boundary": _o("BOUNDARY_OFF"),
        "request_mask": _o("REQUEST_MASK_OFF"), "request_epoch": _o("EPOCH_OFF"), "turn": _o("TURN_OFF"),
        "result": _o("RESULT_OFF"), "weather": _o("WEATHER_OFF"), "weather_turns": _o("WEATHER_TURNS_OFF"),
        "terrain": _o("TERRAIN_OFF"), "terrain_turns": _o("TERRAIN_TURNS_OFF"),
        "trick_room_turns": _o("TRICK_ROOM_OFF"), "queue_len": _o("QUEUE_LEN_OFF")}, _o("QUEUE_OFF"))
    rec = _o("QUEUE_RECORD_SIZE")
    for q in range(QUEUE_CAPACITY):
        out += _block(f"queue{q}.", _o("QUEUE_OFF") + q * rec, {
            "kind": 0, "side": 1, "slot": 2, "move_slot": 3, "target": 4, "reserve": 5,
            "activation_id": _o("QUEUE_ACTIVATION_OFF")}, rec)
    for s in range(SIDE_COUNT):
        base = _o("SIDE_OFF") + s * _o("SIDE_SIZE")
        out += _block(f"side{s}.", base, _sub((
            ("member_count", "SIDE_MEMBER_COUNT_OFF"), ("brought_mask", "SIDE_BROUGHT_OFF"),
            ("requested_slots", "SIDE_REQUESTED_OFF"), ("mega_used", "SIDE_MEGA_USED_OFF"),
            ("sealed", "SIDE_SEALED_OFF"), ("seen_mask", "SIDE_SEEN_OFF"), ("brought_order", "SIDE_ORDER_OFF"),
            ("reflect_turns", "SIDE_REFLECT_OFF"), ("light_screen_turns", "SIDE_LIGHT_SCREEN_OFF"),
            ("tailwind_turns", "SIDE_TAILWIND_OFF"))), _o("SIDE_POS_OFF"))
        for p in range(ACTIVE_PER_SIDE):
            out += _block(f"side{s}.position{p}.", base + _o("SIDE_POS_OFF") + p * _o("POS_SIZE"), {
                "occupant": 0, **_sub((
                    ("activation", "POS_ACTIVATION_OFF"), ("stages", "POS_STAGES_OFF"), ("flags", "POS_FLAGS_OFF"),
                    ("stall_level", "POS_STALL_LEVEL_OFF"), ("stall_turns", "POS_STALL_TURNS_OFF"),
                    ("confusion_turns", "POS_CONFUSION_OFF"), ("charge_turns", "POS_CHARGE_OFF"),
                    ("locked_move", "POS_LOCKED_MOVE_OFF"), ("locked_target", "POS_LOCKED_TARGET_OFF"),
                    ("move_actions", "POS_MOVE_ACTIONS_OFF"), ("switch_flag", "POS_SWITCH_FLAG_OFF")))},
                _o("POS_SIZE"))
        for p in range(ACTIVE_PER_SIDE):
            out += _block(f"side{s}.sealed{p}.", base + _o("SIDE_SEALED_CMD_OFF") + p * _o("CMD_SIZE"), {
                "kind": 0, "move_slot": 1, "target": 2, "mega": 3, "reserve": 4}, _o("CMD_SIZE"))
        for m in range(MAX_ROSTER):
            out += _block(f"side{s}.knowledge{m}.", base + _o("SIDE_KNOWLEDGE_OFF") + m * _o("KNOWLEDGE_SIZE"), {
                "hp_percent": 0, "hp_flag": 1, "revealed": 2, "moves_used": _o("KNOWLEDGE_USED_OFF")},
                _o("KNOWLEDGE_SIZE"))
        for m in range(MAX_ROSTER):
            mbase = base + _o("SIDE_MEMBERS_OFF") + m * _o("MEMBER_SIZE")
            out += _block(f"side{s}.member{m}.", mbase, _sub((
                ("species", "MEMBER_SPECIES_OFF"), ("hp", "MEMBER_HP_OFF"), ("hp_max", "MEMBER_HP_MAX_OFF"),
                ("stats", "MEMBER_STATS_OFF"), ("move_count", "MEMBER_MOVE_COUNT_OFF"),
                ("mega_capable", "MEMBER_MEGA_OFF"), ("is_mega", "MEMBER_IS_MEGA_OFF"),
                ("gender", "MEMBER_GENDER_OFF"), ("nature", "MEMBER_NATURE_OFF"),
                ("stat_points", "MEMBER_STAT_POINTS_OFF"), ("status", "MEMBER_STATUS_OFF"),
                ("status_counter", "MEMBER_STATUS_COUNTER_OFF"), ("item", "MEMBER_ITEM_OFF"),
                ("item_consumed", "MEMBER_ITEM_CONSUMED_OFF"), ("ability", "MEMBER_ABILITY_OFF"))),
                _o("MOVE_OFF"))
            for k in range(MOVE_SLOTS):
                out += _block(f"side{s}.member{m}.move{k}.", mbase + _o("MOVE_OFF") + k * _o("MOVE_SIZE"), {
                    "move_id": 0, "pp": 2, "pp_max": 3}, _o("MOVE_SIZE"))
    if not pool:
        return out
    tail = _o("TAIL_OFF")
    out += _block("tail.field.", tail, _sub((
        ("gravity_turns", "TAIL_FIELD_GRAVITY_OFF"), ("party_order", "TAIL_FIELD_PARTY_OFF"),
        ("reserved", "TAIL_FIELD_RESERVED_OFF"))), _o("TAIL_FIELD_SIZE"))
    for s in range(SIDE_COUNT):
        base = tail + _o("TAIL_SIDES_OFF") + s * _o("TAIL_SIDE_SIZE")
        out += _block(f"tail.side{s}.", base, _sub((
            ("wide_guard", "TAIL_WIDE_GUARD_OFF"), ("aurora_veil_turns", "TAIL_AURORA_VEIL_OFF"),
            ("toxic_spikes", "TAIL_TOXIC_SPIKES_OFF"), ("stealth_rock", "TAIL_STEALTH_ROCK_OFF"),
            ("spikes", "TAIL_SPIKES_OFF"), ("sticky_web", "TAIL_STICKY_WEB_OFF"), ("quick_guard", "TAIL_QUICK_GUARD_OFF"),
            ("hazard_order", "TAIL_HAZARD_ORDER_OFF"), ("reserved", "TAIL_SIDE_RESERVED_OFF"))), _o("TAIL_POS_OFF"))
        for p in range(ACTIVE_PER_SIDE):
            out += _block(f"tail.side{s}.position{p}.", base + _o("TAIL_POS_OFF") + p * _o("TAIL_POS_SIZE"), _sub((
                ("last_move", "TAIL_POS_LAST_MOVE_OFF"), ("encore_slot", "TAIL_POS_ENCORE_SLOT_OFF"),
                ("encore_turns", "TAIL_POS_ENCORE_TURNS_OFF"), ("throat_chop_turns", "TAIL_POS_THROAT_CHOP_OFF"),
                ("heal_block_turns", "TAIL_POS_HEAL_BLOCK_OFF"), ("perish", "TAIL_POS_PERISH_OFF"),
                ("taunt_turns", "TAIL_POS_TAUNT_OFF"), ("disable_slot", "TAIL_POS_DISABLE_SLOT_OFF"),
                ("disable_turns", "TAIL_POS_DISABLE_TURNS_OFF"), ("imprison", "TAIL_POS_IMPRISON_OFF"),
                ("must_recharge", "TAIL_POS_MUST_RECHARGE_OFF"), ("trap_turns", "TAIL_POS_TRAP_TURNS_OFF"),
                ("trap_source", "TAIL_POS_TRAP_SOURCE_OFF"), ("trap_band", "TAIL_POS_TRAP_BAND_OFF"),
                ("leech_seed_source", "TAIL_POS_LEECH_SEED_OFF"), ("yawn_turns", "TAIL_POS_YAWN_OFF"),
                ("focus_energy", "TAIL_POS_FOCUS_ENERGY_OFF"), ("stockpile", "TAIL_POS_STOCKPILE_OFF"),
                ("stockpile_def", "TAIL_POS_STOCKPILE_DEF_OFF"), ("stockpile_spd", "TAIL_POS_STOCKPILE_SPD_OFF"),
                ("charge", "TAIL_POS_CHARGE_OFF"), ("glaive_rush", "TAIL_POS_GLAIVE_RUSH_OFF"),
                ("substitute_hp", "TAIL_POS_SUBSTITUTE_OFF"), ("trap_move", "TAIL_POS_TRAP_MOVE_OFF"),
                ("protect_kind", "TAIL_POS_PROTECT_KIND_OFF"), ("move_result", "TAIL_POS_MOVE_RESULT_OFF"),
                ("single_turn", "TAIL_POS_SINGLE_TURN_OFF"), ("hits_taken", "TAIL_POS_HITS_TAKEN_OFF"),
                ("ability_state", "TAIL_POS_ABILITY_STATE_OFF"), ("lock_turns", "TAIL_POS_LOCK_TURNS_OFF"),
                ("reserved", "TAIL_POS_RESERVED_OFF"))), _o("TAIL_POS_SIZE"))
        for m in range(MAX_ROSTER):
            out += _block(f"tail.side{s}.member{m}.", base + _o("TAIL_MEMBER_OFF") + m * _o("TAIL_MEMBER_SIZE"), _sub((
                ("ability_now", "TAIL_MEMBER_ABILITY_OFF"), ("forme_now", "TAIL_MEMBER_FORME_OFF"),
                ("soak_type", "TAIL_MEMBER_SOAK_OFF"), ("item_now", "TAIL_MEMBER_ITEM_OFF"),
                ("toxic_stage", "TAIL_MEMBER_TOXIC_OFF"), ("type2", "TAIL_MEMBER_TYPE2_OFF"),
                ("flags", "TAIL_MEMBER_FLAGS_OFF"), ("reserved", "TAIL_MEMBER_RESERVED_OFF"))), _o("TAIL_MEMBER_SIZE"))
    tail5 = tail + _o("TAIL_REV4_SIZE")
    for s in range(SIDE_COUNT):
        out += _block(f"tail5.side{s}.", tail5 + _o("TAIL5_SIDES_OFF") + s * _o("TAIL5_SIDE_SIZE"), _sub((
            ("illusion_shown", "TAIL5_ILL_SHOWN_OFF"), ("illusion_override", "TAIL5_ILL_OVERRIDE_OFF"),
            ("illusion_snapshot", "TAIL5_ILL_SNAPSHOT_OFF"), ("illusion_pending", "TAIL5_ILL_PENDING_OFF"))),
            _o("TAIL5_SIDE_SIZE"))
    for flat in range(SIDE_COUNT * ACTIVE_PER_SIDE):
        out += _block(f"tail5.position{flat}.", tail5 + _o("TAIL5_POS_OFF") + flat * _o("TAIL5_POS_SIZE"), _sub((
            ("position_flags", "TAIL5_POSITION_FLAGS_OFF"), ("future_sight", "TAIL5_FUTURE_SIGHT_OFF"))),
            _o("TAIL5_POS_SIZE"))
    out.append(("tail5.reserved", tail5 + _o("TAIL5_RESERVED_OFF"), _o("TAIL5_RESERVED_SIZE")))
    return out


def diff(a, b, pool=True):
    """The names of the fields in which two encodings (bytes-like, the same size) differ, in order."""
    a, b = bytes(a), bytes(b)
    if len(a) != len(b):
        raise ValueError(f"encodings of different sizes ({len(a)} and {len(b)} bytes)")
    return [name for name, start, size in fields(pool) if start < len(a) and a[start:start + size] != b[start:start + size]]
