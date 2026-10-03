"""The observation-only feature encoder (M7 spec section 5; the block of
encoder 3: decision 0018 section 10).

encode(observation, domain, ext, ext_supported) -> (obs_part, slot_part,
pair_mask) is a pure function of one player's observation, factored domain
and view extension, and encode_batch(observations, domains, ext,
ext_supported) the same for N players at once (vectorized; encode is
encode_batch of one player); it never reads a battle, so it carries nothing
beyond what decisions 0007 and 0018 prove for the views. Every value is
scaled to [0, 1] (ids by 65535, so a network can recover them exactly as
round(x * 65535) for an embedding), except a Recharge option's move slot
(5 / 4). A value outside the known sets below (an ailment, weather, terrain,
location, boundary kind, position flag bit or extension field this encoder
does not know) raises ValueError; it is never encoded as zeros.
So does a domain of another boundary than the observation's (another
epoch, or a request where the observation has none):
query() refreshes observations but not domains, query_factored() both.

obs_part, float32 (OBS_SIZE,), from the viewer's perspective (own side
first, then the foe):
  global: boundary kind one-hot (BOUNDARIES), turn / 100 (at most 1),
    weather one-hot (WEATHERS), weather turns / 8, terrain one-hot
    (TERRAINS), terrain turns / 8, trick room turns / 5
  per side, own then foe:
    side (8): member count / 6, mega used, requested, requested slot 0,
      requested slot 1, reflect / 8, light screen / 8, tailwind / 4
    per position, slot 0 then 1: stages / 12 (7), confused, charging,
      locked (a locked move slot), acted, protect chain / 3 (at most 1),
      flash fire, protecting, follow me, helping hand, unburden (the
      POSITION_FLAGS bits of the TEAM_C kinds; 0 under CLOSURE), occupant
      one-hot (7: roster 0..5, none)
    per member, roster 0..5: present (move count above 0: a registered
      member has 1 to 4 moves, an unregistered slot is all zero; not the
      species, since id 0 is a forme, Rillaboom), hp / hp_max (0 when
      hp_max is 0), location one-hot (LOCATIONS), status one-hot
      (AILMENTS), is mega, mega capable, item used, item / 255,
      ability / 255, gender / 3, nature / 24, species / 65535,
      move ids / 65535 (4), pp / pp_max (4, 0 when pp_max is 0),
      move count / 4, stat points / 32 (6), stats / 1000 (5, at most 1)
  the block of decision 0018 (EXT_SIZE columns, "ext." names):
    global (5): Sand, Snow, Electric Terrain, Misty Terrain (each 1 while it
      is the weather or terrain), gravity turns / 5
    per side, own then foe (7): aurora veil turns / 8, stealth rock,
      spikes / 3, toxic spikes / 2, sticky web, wide guard, quick guard
    per position, slot 0 then 1 (36): the 20 volatiles bits (VOLATILES),
      encore slot one-hot (none, slot 0..3), disable slot one-hot (none,
      slot 0..3), stockpile / 3, perish / 3, ability changed, ability now /
      255, type now 0 and 1 / 18
    per member, roster 0..5 (6): tox, forme changed, forme / 65535, item
      changed, item removed, item now / 255
  Every block column belongs to one DUOFORGE_VIEWEXT_FEATURE_* bit
  (EXT_COLUMN_FEATURES). ext_supported, the mask a network was trained with
  (a checkpoint property, never an input), zeros the columns of every clear
  bit. Sand, Snow, Electric, Misty and Tox come from the observation
  (BASE_VALUE_FEATURES): such a value leaves its old one-hot group all zero
  and needs its bit, else ValueError, so an old group never shows a value it
  cannot. Every other bit reads the extension records (ext, OBSERVATION_EXT
  per player, Batch.observe_ext): a set bit without records, records of
  another boundary or revision, a set bit the records' library does not
  support and a field outside its range raise ValueError. A record of
  revision 0 (every kind but POOL, where none of these effects can arise)
  reads as an empty record: zero, and "none" in the Encore and Disable
  one-hots. check_ext_supported is the check of a training mask against
  the library: a network never records a feature it could not see.

slot_part, float32 (2, 32, SLOT_FEATURES): for slot list s and entry i,
  valid (i < slot_count[s]), kind one-hot (4: none, move, switch, pass),
  move slot / 4 (moves only; Struggle is 4, Recharge is 5, any other slot
  is refused), target one-hot relative to
  the viewer (4: own slot 0, own slot 1, foe slot 0, foe slot 1; none for
  a move without a target), mega, reserve / 5 (switches only). All zero
  past slot_count and at team selection.

pair_mask, bool (32, 32): [i, j] is bit j of domain.allowed[i], the pair
  rule of the engine; its sum is the joint count at a SLOTS boundary and
  0 at team selection.

Versions: this encoder is ENCODER (3), and a checkpoint's config names the
version its network was trained with ("encoder"; a config without it is
1). Version 2 is the first BASE_OBS_SIZE columns, which know none of the
new values; version 1 took present from species_id != 0, so Rillaboom
(forme 0) was absent; every other column is the same. as_encoder(obs_part,
observations, version) and slots_as_encoder(slot_part, version) give such a
network exactly the inputs it learned on, and refuse what it cannot show.
"""
import numpy as np

from . import _layout

C = _layout.CONSTANTS
OPTIONS = _layout.MAX_SLOT_OPTIONS

_BOUNDARY_NAMES = ("TEAM_SELECTION", "TURN", "REPLACEMENT", "PIVOT", "TERMINAL")
_WEATHER_NAMES = ("NONE", "RAIN", "SUN")
_TERRAIN_NAMES = ("NONE", "GRASSY", "PSYCHIC")
_LOCATION_NAMES = ("UNDETERMINED", "BENCH", "ACTIVE", "NOT_BROUGHT")
_AILMENT_NAMES = ("NONE", "BURN", "FREEZE", "PARALYSIS", "SLEEP", "POISON")
_SLOT_KIND_NAMES = ("NONE", "MOVE", "SWITCH", "PASS")
_POSITION_FLAG_NAMES = ("FOLLOW_ME", "HELPING_HAND", "UNBURDEN")
BOUNDARIES = tuple(C[f"DUOFORGE_BOUNDARY_{n}"] for n in _BOUNDARY_NAMES)
WEATHERS = tuple(C[f"DUOFORGE_WEATHER_{n}"] for n in _WEATHER_NAMES)
TERRAINS = tuple(C[f"DUOFORGE_TERRAIN_{n}"] for n in _TERRAIN_NAMES)
LOCATIONS = tuple(C[f"DUOFORGE_LOCATION_{n}"] for n in _LOCATION_NAMES)
AILMENTS = tuple(C[f"DUOFORGE_AILMENT_{n}"] for n in _AILMENT_NAMES)
SLOT_KINDS = tuple(C[f"DUOFORGE_SLOT_{n}"] for n in _SLOT_KIND_NAMES)
POSITION_FLAGS = tuple(C[f"DUOFORGE_POSITION_FLAG_{n}"] for n in _POSITION_FLAG_NAMES)

SLOT_FEATURES = 12
_GLOBAL = len(BOUNDARIES) + 1 + len(WEATHERS) + 1 + len(TERRAINS) + 2
_SIDE = 8
_POSITION = 7 + 7 + len(POSITION_FLAGS) + 7
_MEMBER = 2 + len(LOCATIONS) + len(AILMENTS) + 8 + 4 + 4 + 1 + 6 + 5
_SIDE_SIZE = _SIDE + 2 * _POSITION + 6 * _MEMBER
# The columns of encoders 1 and 2; encoder 3 appends the block after them.
BASE_OBS_SIZE = _GLOBAL + 2 * _SIDE_SIZE
# obs_part columns of the present flags: row 0 the own roster, row 1 the foe's.
_PRESENT = _GLOBAL + _SIDE + 2 * _POSITION + _SIDE_SIZE * np.arange(2)[:, None] + _MEMBER * np.arange(6)

# The view extension (decision 0018): the feature bits, the new values of the
# old fields with the bit of each, and the volatiles bits in bit order.
FEATURE_COUNT = C["DUOFORGE_VIEWEXT_FEATURE_COUNT"]
_FEATURE_PREFIX = "DUOFORGE_VIEWEXT_FEATURE_"
FEATURE_BITS = {name[len(_FEATURE_PREFIX):]: bit for name, bit in C.items()
                if name.startswith(_FEATURE_PREFIX) and name != _FEATURE_PREFIX + "COUNT"}
assert sorted(FEATURE_BITS.values()) == list(range(FEATURE_COUNT))
_FEATURE_NAME = {bit: name for name, bit in FEATURE_BITS.items()}
_NEW_WEATHERS = ((C["DUOFORGE_WEATHER_SAND"], "WEATHER_SAND"), (C["DUOFORGE_WEATHER_SNOW"], "WEATHER_SNOW"))
_NEW_TERRAINS = ((C["DUOFORGE_TERRAIN_ELECTRIC"], "TERRAIN_ELECTRIC"), (C["DUOFORGE_TERRAIN_MISTY"], "TERRAIN_MISTY"))
_TOX = C["DUOFORGE_AILMENT_TOX"]
# The bits the encoder reads from the observation itself, not from the records.
BASE_VALUE_FEATURES = sum(1 << FEATURE_BITS[n] for n in ("WEATHER_SAND", "WEATHER_SNOW", "TERRAIN_ELECTRIC",
                                                        "TERRAIN_MISTY", "AILMENT_TOX"))
ALL_FEATURES = (1 << FEATURE_COUNT) - 1
RECORD_FEATURES = ALL_FEATURES & ~BASE_VALUE_FEATURES
# (name, its DUOFORGE_POSITION_EXT_* bit, its feature) in bit order 0..19.
_VOLATILE_FEATURE = {"TYPE_CHANGED": "TYPE_CHANGE", "ILLUSION_UP": "ILLUSION"}
VOLATILES = tuple(sorted(((name[len("DUOFORGE_POSITION_EXT_"):], bit,
                           _VOLATILE_FEATURE.get(name[len("DUOFORGE_POSITION_EXT_"):],
                                                 name[len("DUOFORGE_POSITION_EXT_"):]))
                          for name, bit in C.items() if name.startswith("DUOFORGE_POSITION_EXT_")), key=lambda v: v[1]))
assert [v[1] for v in VOLATILES] == [1 << k for k in range(20)]
_GUARDS = ((C["DUOFORGE_SIDE_GUARD_WIDE_GUARD"], "WIDE_GUARD"), (C["DUOFORGE_SIDE_GUARD_QUICK_GUARD"], "QUICK_GUARD"))
_ITEM_NOW_NONE = C["DUOFORGE_ITEM_NOW_NONE"]
_EXT_REVISION = C["DUOFORGE_OBSERVATION_EXT_REVISION"]

# This encoder's version, which train writes into a checkpoint's config
# ("encoder"), and every version as_encoder serves (1: present from the
# species id; 2: without the block).
ENCODER = 3
ENCODERS = (1, 2, ENCODER)


_STAGES = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")
_FLAGS = ("confused", "charging", "locked", "acted", "protect_chain", "flash_fire", "protecting")
_STATS6 = ("hp", "atk", "def", "spa", "spd", "spe")
_SLOTS5 = ("none", "slot0", "slot1", "slot2", "slot3")


def _base_names():
    """One name per column of encoders 1 and 2, in the encoder's order (the
    layout of the module docstring), from the same tuples as the sizes above."""
    names = [f"global.boundary.{n}" for n in _BOUNDARY_NAMES] + ["global.turn"]
    names += [f"global.weather.{n}" for n in _WEATHER_NAMES] + ["global.weather_turns"]
    names += [f"global.terrain.{n}" for n in _TERRAIN_NAMES] + ["global.terrain_turns", "global.trick_room_turns"]
    for s in ("own", "foe"):
        names += [f"{s}.side.{n}" for n in ("member_count", "mega_used", "requested", "requested_slot0",
                                             "requested_slot1", "reflect_turns", "light_screen_turns",
                                             "tailwind_turns")]
        for p in range(2):
            pre = f"{s}.pos{p}"
            names += [f"{pre}.stage.{n}" for n in _STAGES] + [f"{pre}.flag.{n}" for n in _FLAGS]
            names += [f"{pre}.flag.{n.lower()}" for n in _POSITION_FLAG_NAMES]
            names += [f"{pre}.occupant.{k}" for k in range(_layout.MAX_ROSTER)] + [f"{pre}.occupant.none"]
        for m in range(_layout.MAX_ROSTER):
            pre = f"{s}.member{m}"
            names += [f"{pre}.present", f"{pre}.hp"] + [f"{pre}.location.{n}" for n in _LOCATION_NAMES]
            names += [f"{pre}.status.{n}" for n in _AILMENT_NAMES]
            names += [f"{pre}.{n}" for n in ("is_mega", "mega_capable", "item_used", "item", "ability", "gender",
                                              "nature", "species")]
            names += [f"{pre}.move{k}" for k in range(4)] + [f"{pre}.pp{k}" for k in range(4)]
            names += [f"{pre}.move_count"] + [f"{pre}.sp.{n}" for n in _STATS6]
            names += [f"{pre}.stat.{n}" for n in _STATS6[1:]]
    return names


def _ext_columns():
    """(name, feature bit) of every block column, in the encoder's order
    (decision 0018 section 10)."""
    f = FEATURE_BITS
    cols = [("ext.global.weather_sand", f["WEATHER_SAND"]), ("ext.global.weather_snow", f["WEATHER_SNOW"]),
            ("ext.global.terrain_electric", f["TERRAIN_ELECTRIC"]), ("ext.global.terrain_misty", f["TERRAIN_MISTY"]),
            ("ext.global.gravity_turns", f["GRAVITY"])]
    for s in ("own", "foe"):
        cols += [(f"ext.{s}.aurora_veil_turns", f["AURORA_VEIL"]), (f"ext.{s}.stealth_rock", f["STEALTH_ROCK"]),
                 (f"ext.{s}.spikes", f["SPIKES"]), (f"ext.{s}.toxic_spikes", f["TOXIC_SPIKES"]),
                 (f"ext.{s}.sticky_web", f["STICKY_WEB"]), (f"ext.{s}.wide_guard", f["WIDE_GUARD"]),
                 (f"ext.{s}.quick_guard", f["QUICK_GUARD"])]
        for p in range(2):
            pre = f"ext.{s}.pos{p}"
            cols += [(f"{pre}.volatile.{name.lower()}", f[feature]) for name, _, feature in VOLATILES]
            cols += [(f"{pre}.encore.{x}", f["ENCORE"]) for x in _SLOTS5]
            cols += [(f"{pre}.disable.{x}", f["DISABLE"]) for x in _SLOTS5]
            cols += [(f"{pre}.stockpile", f["STOCKPILE"]), (f"{pre}.perish", f["PERISH"]),
                     (f"{pre}.ability_changed", f["ABILITY_CHANGE"]), (f"{pre}.ability_now", f["ABILITY_CHANGE"]),
                     (f"{pre}.type_now0", f["TYPE_CHANGE"]), (f"{pre}.type_now1", f["TYPE_CHANGE"])]
        for m in range(_layout.MAX_ROSTER):
            pre = f"ext.{s}.mem{m}"
            cols += [(f"{pre}.tox", f["AILMENT_TOX"]), (f"{pre}.forme_changed", f["FORME_CHANGE"]),
                     (f"{pre}.forme", f["FORME_CHANGE"]), (f"{pre}.item_changed", f["ITEM_CHANGE"]),
                     (f"{pre}.item_removed", f["ITEM_CHANGE"]), (f"{pre}.item_now", f["ITEM_CHANGE"])]
    return cols


_EXT = _ext_columns()
EXT_SIZE = len(_EXT)
OBS_SIZE = BASE_OBS_SIZE + EXT_SIZE
# The DUOFORGE_VIEWEXT_FEATURE_* bit of every block column.
EXT_COLUMN_FEATURES = np.array([bit for _, bit in _EXT], dtype=np.int64)
FEATURE_NAMES = tuple(_base_names() + [name for name, _ in _EXT])
SLOT_FEATURE_NAMES = (("valid",) + tuple(f"kind.{n}" for n in _SLOT_KIND_NAMES) + ("move_slot",)
                      + tuple(f"target.{n}" for n in ("own0", "own1", "foe0", "foe1")) + ("mega", "reserve"))
assert len(FEATURE_NAMES) == OBS_SIZE and len(SLOT_FEATURE_NAMES) == SLOT_FEATURES
assert len(_base_names()) == BASE_OBS_SIZE and EXT_SIZE == 5 + 2 * (7 + 2 * 36 + 6 * 6)
_EXT_SIDE = 7 + 2 * 36 + 6 * 6
_VOLATILE_SHIFTS = np.arange(len(VOLATILES))
_EYE5 = np.eye(5)
# One side's columns of an empty record: no Encore and no Disable at either position ("none" of each one-hot).
_EMPTY_SIDE = np.zeros(_EXT_SIDE)
_EMPTY_SIDE[[7 + 36 * k + len(VOLATILES) + g for k in range(2) for g in (0, 5)]] = 1.0
_MOVE_SLOT = SLOT_FEATURE_NAMES.index("move_slot")
_KIND_MOVE = SLOT_FEATURE_NAMES.index("kind.MOVE")


def obs_size(encoder):
    """The obs_part width of encoder version `encoder`."""
    _check_version(encoder)
    return OBS_SIZE if encoder == ENCODER else BASE_OBS_SIZE


def feature_names(encoder):
    """The column names of encoder version `encoder` (its obs_part order)."""
    return FEATURE_NAMES[:obs_size(encoder)]


_F64 = np.float64
_F32 = np.float32
_OCCUPANTS = tuple(range(_layout.MAX_ROSTER)) + (C["DUOFORGE_ROSTER_NONE"],)


def _one_hot(values, known, what, blank=()):
    """One-hot float32 rows over `known` for every value (any shape); a value
    in `blank` gives an all-zero row; ValueError for any other value."""
    values = np.asarray(values).astype(np.int64)
    table = np.full(max(256, int(values.max(initial=0)) + 1), -1, dtype=np.int64)
    table[list(known)] = np.arange(len(known))
    table[list(blank)] = len(known)
    index = table[values]
    if (index < 0).any():
        bad = int(values[index < 0].flat[0])
        raise ValueError(f"{what} {bad} is not one this encoder knows: {known}")
    return np.eye(len(known) + 1, len(known), dtype=_F32)[index]


def _ratio(values, divisor):
    """values / divisor in float64, as float32 (the scale of a count)."""
    return (np.asarray(values).astype(_F64) / divisor).astype(_F32)


def _sides(s, tox):
    """The side features of SIDE_VIEW records s (N,): (N, side size); tox: Tox
    is a known status (its old one-hot is all zero)."""
    n = s.shape[0]
    rs = s["requested_slots"].astype(np.int64)
    head = np.stack([s["member_count"].astype(_F64) / 6, s["mega_used"].astype(_F64), s["requested"].astype(_F64),
                     (rs & 1).astype(_F64), ((rs >> 1) & 1).astype(_F64), s["reflect_turns"].astype(_F64) / 8,
                     s["light_screen_turns"].astype(_F64) / 8, s["tailwind_turns"].astype(_F64) / 4],
                    axis=1).astype(_F32)
    pos = s["positions"]
    bits = pos["reserved"].astype(np.int64)  # DUOFORGE_POSITION_FLAG_* of the TEAM_C kinds (decision 0009 4.2)
    unknown = bits & ~sum(POSITION_FLAGS)
    if unknown.any():
        bad = int(bits[unknown != 0].flat[0])
        raise ValueError(f"position flags {bad} are not ones this encoder knows: {POSITION_FLAGS}")
    flags = np.stack([pos["confused"].astype(_F64), pos["charging"].astype(_F64),
                      (pos["locked_slot"] != C["DUOFORGE_MOVE_SLOT_NONE"]).astype(_F64), pos["acted"].astype(_F64),
                      np.clip(pos["protect_chain"].astype(_F64) / 3, 0.0, 1.0), pos["flash_fire"].astype(_F64),
                      pos["protecting"].astype(_F64)] + [((bits & bit) != 0).astype(_F64) for bit in POSITION_FLAGS],
                     axis=-1).astype(_F32)
    positions = np.concatenate([pos["stages"].astype(_F32) / 12, flags,
                                _one_hot(s["occupant"], _OCCUPANTS, "occupant")], axis=-1).reshape(n, -1)
    m = s["members"]
    hp_max = m["hp_max"].astype(_F64)
    hp = np.divide(m["hp"].astype(_F64), hp_max, out=np.zeros(hp_max.shape), where=hp_max > 0)
    pp_max = m["pp_max"].astype(_F32)
    members = np.concatenate([
        np.stack([(m["move_count"] != 0).astype(_F64), hp], axis=-1).astype(_F32),
        _one_hot(m["location"], LOCATIONS, "location"),
        _one_hot(m["status"], AILMENTS, "ailment", (_TOX,) if tox else ()),
        np.stack([m["is_mega"].astype(_F64), m["mega_capable"].astype(_F64), m["item_used"].astype(_F64),
                  m["item"].astype(_F64) / 255, m["ability"].astype(_F64) / 255, m["gender"].astype(_F64) / 3,
                  m["nature"].astype(_F64) / 24, m["species_id"].astype(_F64) / 65535], axis=-1).astype(_F32),
        m["move_ids"].astype(_F32) / 65535,
        np.divide(m["pp"].astype(_F32), pp_max, out=np.zeros(pp_max.shape, _F32), where=pp_max > 0),
        _ratio(m["move_count"], 4)[..., None],
        m["stat_points"].astype(_F32) / 32,
        np.minimum(m["stats"].astype(_F32) / 1000, 1.0),
    ], axis=-1).reshape(n, -1)
    return np.concatenate([head, positions, members], axis=1)


def _mask_of(ext_supported):
    """ext_supported as an int mask of DUOFORGE_VIEWEXT_FEATURE_* bits;
    ValueError for anything else."""
    if (not isinstance(ext_supported, (int, np.integer)) or isinstance(ext_supported, bool)
            or not 0 <= int(ext_supported) <= ALL_FEATURES):
        raise ValueError(f"ext_supported {ext_supported!r} is not a mask of the {FEATURE_COUNT} feature bits")
    return int(ext_supported)


def check_ext_supported(ext_supported, library):
    """ext_supported as an int mask when every bit of it is one the library
    supports (library: the `supported` of its duoforge_observation_ext under
    the context, 0 under every kind but POOL). ValueError for anything else,
    naming the first bit the library lacks: a network must never record a
    feature it could not see while it learned."""
    mask = _mask_of(ext_supported)
    extra = mask & ~int(library)
    if extra:
        bit = (extra & -extra).bit_length() - 1
        raise ValueError(f"ext_supported {mask:#x} has the bit of {_FEATURE_NAME[bit]}, which the library does not "
                         f"support under this context ({int(library):#x})")
    return mask


def _new_values(mask):
    """The new values of the old fields that mask shows: (weathers, terrains,
    tox)."""
    weathers = tuple(v for v, name in _NEW_WEATHERS if mask >> FEATURE_BITS[name] & 1)
    terrains = tuple(v for v, name in _NEW_TERRAINS if mask >> FEATURE_BITS[name] & 1)
    return weathers, terrains, bool(mask >> FEATURE_BITS["AILMENT_TOX"] & 1)


# Each record field with the largest value the encoder takes: the documented range (decision 0018 section 3), and
# ability_now at most 255, the width of the member view's ability id it overlays (POOL has 215 abilities).
_SIDE_RANGES = (("aurora_veil_turns", 8), ("stealth_rock", 1), ("spikes", 3), ("toxic_spikes", 2), ("sticky_web", 1))
_POSITION_RANGES = (("encore_slot", 4), ("disable_slot", 4), ("stockpile", 3), ("perish", 3), ("ability_now", 255),
                    ("type_now", 18))


def _check_records(ob, ext, mask):
    """The records (OBSERVATION_EXT, ob.shape) as encode_batch reads them:
    TypeError for another dtype or shape, ValueError for records of another
    boundary or revision, a mask bit their library does not support or a
    field outside its range. Returns the rows of revision 1."""
    ext = np.asarray(ext)
    if ext.dtype != _layout.OBSERVATION_EXT or ext.shape != ob.shape:
        raise TypeError("ext must be an OBSERVATION_EXT array of the observations' shape")
    revision = ext["revision"]
    absent = revision == 0
    if np.ascontiguousarray(ext).view(np.uint8).reshape(ob.shape[0], -1)[absent].any():
        raise ValueError("an extension record of revision 0 must be all zero")
    present = ~absent
    if (revision[present] != _EXT_REVISION).any():
        raise ValueError(f"extension revision {int(revision[present][revision[present] != _EXT_REVISION][0])} is not "
                         f"one this encoder knows ({_EXT_REVISION})")
    if ((ext["player"] != ob["player"]) | (ext["epoch"] != ob["epoch"]))[present].any():
        raise ValueError("the extension is not of the observation's boundary (another player or epoch)")
    missing = mask & ~np.bitwise_and.reduce(ext["supported"][present].astype(np.uint64), initial=np.uint64(ALL_FEATURES))
    if present.any() and int(missing):
        bit = (int(missing) & -int(missing)).bit_length() - 1
        raise ValueError(f"ext_supported has the bit of {_FEATURE_NAME[bit]}, which this library does not support")
    rec = ext[present]
    checks = [("gravity_turns", rec["field"]["gravity_turns"], 5)]
    checks += [(name, rec["sides"][name], top) for name, top in _SIDE_RANGES]
    checks += [(name, rec["sides"]["positions"][name], top) for name, top in _POSITION_RANGES]
    for name, values, top in checks:
        if (values > top).any():
            raise ValueError(f"extension field {name} {int(values[values > top].flat[0])} is above {top}")
    guards = rec["sides"]["guard_flags"].astype(np.int64) & ~sum(bit for bit, _ in _GUARDS)
    if guards.any():
        raise ValueError(f"extension field guard_flags bits {int(guards[guards != 0].flat[0])} are not ones this "
                         "encoder knows")
    volatiles = rec["sides"]["positions"]["volatiles"].astype(np.int64)
    unknown = volatiles & ~sum(bit for _, bit, _ in VOLATILES)
    if unknown.any():
        raise ValueError(f"extension field volatiles bits {int(unknown[unknown != 0].flat[0])} are not ones "
                         "this encoder knows")
    typed = (rec["sides"]["positions"]["type_now"] != 0).any(axis=-1)
    if (typed & ((volatiles & C["DUOFORGE_POSITION_EXT_TYPE_CHANGED"]) == 0)).any():
        raise ValueError("extension field type_now is set while the volatile TYPE_CHANGED is clear")
    return present


def _ext_block(ob, ext, present, viewer):
    """The block of the module docstring (N, EXT_SIZE) before the mask. Each
    side's columns are built for both absolute sides at once, then ordered
    own first by the viewer. A row whose record has revision 0 (every kind
    but POOL, where none of these effects can arise) reads as an empty
    record: zero, and "none" in the Encore and Disable one-hots."""
    n = ob.shape[0]
    rows = np.arange(n)[:, None]
    order = np.stack([viewer, 1 - viewer], axis=1)  # (N, 2): the absolute side of own, of foe
    block = np.zeros((n, EXT_SIZE), dtype=_F32)
    sides = block[:, 5:].reshape(n, 2, _EXT_SIDE)  # a view of the per-side columns, own then foe
    if ext is not None and not present.any():
        sides[...] = _EMPTY_SIDE
    elif ext is not None:
        rec = np.asarray(ext)
        s = rec["sides"]  # (N, 2), absolute
        guards = s["guard_flags"].astype(np.int64)
        head = np.stack([s["aurora_veil_turns"] / 8, s["stealth_rock"], s["spikes"] / 3, s["toxic_spikes"] / 2,
                         s["sticky_web"]] + [(guards & bit) != 0 for bit, _ in _GUARDS], axis=-1)  # (N, 2, 7)
        pos = s["positions"]  # (N, 2, 2)
        ability = pos["ability_now"].astype(np.int64)
        position = np.concatenate([
            (pos["volatiles"].astype(np.int64)[..., None] >> _VOLATILE_SHIFTS) & 1,
            _EYE5[pos["encore_slot"]], _EYE5[pos["disable_slot"]],
            np.stack([pos["stockpile"] / 3, pos["perish"] / 3, ability != 0, ability / 255], axis=-1),
            pos["type_now"] / 18], axis=-1)  # (N, 2, 2, 36)
        forme = s["members"]["forme"].astype(np.int64)
        item = s["members"]["item_now"].astype(np.int64)
        member = np.stack([np.zeros(forme.shape), forme != 0, forme / 65535, item != 0, item == _ITEM_NOW_NONE,
                           item / 255], axis=-1)  # (N, 2, 6, 6); the tox column comes from the observation
        absolute = np.concatenate([head, position.reshape(n, 2, 72), member.reshape(n, 2, 36)], axis=-1)
        absolute[~present] = _EMPTY_SIDE
        sides[...] = absolute[rows, order]
        block[:, 4] = np.where(present, rec["field"]["gravity_turns"] / 5, 0.0)
    # The base values, from the observation itself.
    block[:, 0] = ob["weather"] == C["DUOFORGE_WEATHER_SAND"]
    block[:, 1] = ob["weather"] == C["DUOFORGE_WEATHER_SNOW"]
    block[:, 2] = ob["terrain"] == C["DUOFORGE_TERRAIN_ELECTRIC"]
    block[:, 3] = ob["terrain"] == C["DUOFORGE_TERRAIN_MISTY"]
    sides[:, :, 79::6] = (ob["sides"]["members"]["status"] == _TOX)[rows, order]
    return block


def encode_batch(observations, domains, ext=None, ext_supported=0):
    """(obs_part (N, OBS_SIZE), slot_part (N, 2, 32, SLOT_FEATURES),
    pair_mask (N, 32, 32)) of N players' observations (OBSERVATION, (N,)),
    factored domains (FACTORED_DOMAIN, (N,)) and view extensions
    (OBSERVATION_EXT, (N,), or None when ext_supported needs no record) under
    the feature mask ext_supported; row n is encode of player n. See the
    module docstring for the layout and the rules of the mask."""
    ob = np.asarray(observations)
    d = np.asarray(domains)
    if ob.dtype != _layout.OBSERVATION or ob.ndim != 1:
        raise TypeError("observations must be a one-dimensional OBSERVATION array")
    if d.dtype != _layout.FACTORED_DOMAIN or d.shape != ob.shape:
        raise TypeError("domains must be a FACTORED_DOMAIN array of the observations' shape")
    if ((ob["epoch"] != d["epoch"]) | ((ob["requested"] != 0) != (d["kind"] != 0))).any():
        raise ValueError("the domain is not of the observation's boundary (query_factored() refreshes both)")
    mask = _mask_of(ext_supported)
    if ext is None:
        if mask & RECORD_FEATURES:
            bit = (mask & RECORD_FEATURES & -(mask & RECORD_FEATURES)).bit_length() - 1
            raise ValueError(f"ext_supported has the bit of {_FEATURE_NAME[bit]}, which needs the extension records "
                             "(ext)")
        present = np.zeros(ob.shape, dtype=bool)
    else:
        present = _check_records(ob, ext, mask)
    weathers, terrains, tox = _new_values(mask)
    n = ob.shape[0]
    rows = np.arange(n)
    viewer = ob["player"].astype(np.int64)
    glob = np.concatenate([
        _one_hot(ob["boundary_kind"], BOUNDARIES, "boundary kind"),
        np.clip(ob["turn"].astype(_F64) / 100, 0.0, 1.0)[:, None].astype(_F32),
        _one_hot(ob["weather"], WEATHERS, "weather", weathers),
        _ratio(ob["weather_turns"], 8)[:, None],
        _one_hot(ob["terrain"], TERRAINS, "terrain", terrains),
        np.stack([_ratio(ob["terrain_turns"], 8), _ratio(ob["trick_room_turns"], 5)], axis=1),
    ], axis=1)
    block = _ext_block(ob, ext, present, viewer)
    block[:, (mask >> EXT_COLUMN_FEATURES & 1) == 0] = 0.0
    obs_part = np.concatenate([glob, _sides(ob["sides"][rows, viewer], tox), _sides(ob["sides"][rows, 1 - viewer], tox),
                               block], axis=1).astype(_F32)

    slots = d["slots"]
    is_slots = d["kind"] == C["DUOFORGE_CHOICE_SLOTS"]
    if (d["slot_count"][is_slots] > OPTIONS).any():
        raise ValueError(f"a slot list has more than {OPTIONS} options")
    valid = (np.arange(OPTIONS)[None, None, :] < d["slot_count"][:, :, None]) & is_slots[:, None, None]
    slot_part = np.zeros((n, 2, OPTIONS, SLOT_FEATURES), dtype=_F32)
    where = np.nonzero(valid)
    cmd = slots[where]
    kind = cmd["kind"]
    f = np.zeros((cmd.shape[0], SLOT_FEATURES), dtype=_F32)
    f[:, 0] = 1.0
    f[:, 1:5] = _one_hot(kind, SLOT_KINDS, "slot command kind")
    move = kind == C["DUOFORGE_SLOT_MOVE"]
    move_slot = cmd["move_slot"][move]
    unknown = move_slot > C["DUOFORGE_MOVE_SLOT_RECHARGE"]
    if unknown.any():
        raise ValueError(f"move slot {int(move_slot[unknown][0])} is not one this encoder knows (0 to 3, Struggle or "
                         "Recharge)")
    f[move, _MOVE_SLOT] = _ratio(move_slot, C["DUOFORGE_MOVE_SLOT_STRUGGLE"])
    target = cmd["target"].astype(np.int64)
    aimed = move & (target != C["DUOFORGE_TARGET_NONE"])
    if (target[aimed] >= 4).any():
        raise ValueError(f"target {int(target[aimed][target[aimed] >= 4][0])} is not a position")
    rel = ((target[aimed] >> 1) ^ viewer[where[0]][aimed]) * 2 + (target[aimed] & 1)
    f[np.flatnonzero(aimed), 6 + rel] = 1.0
    f[move, 10] = cmd["mega"][move].astype(_F32)
    switch = kind == C["DUOFORGE_SLOT_SWITCH"]
    f[switch, 11] = _ratio(cmd["reserve"][switch], 5)
    slot_part[where] = f

    bits = np.unpackbits(np.ascontiguousarray(d["allowed"], dtype="<u4").view(np.uint8), axis=-1, bitorder="little")
    pair_mask = bits.reshape(n, OPTIONS, OPTIONS).astype(bool) & is_slots[:, None, None]
    return obs_part, slot_part, pair_mask


def encode(observation, domain, ext=None, ext_supported=0):
    """(obs_part, slot_part, pair_mask) of one player's observation
    (OBSERVATION), factored domain (FACTORED_DOMAIN) and view extension
    (OBSERVATION_EXT or None); encode_batch of one player."""
    ob = np.asarray(observation)
    if ob.dtype != _layout.OBSERVATION or ob.shape != ():
        raise TypeError("observation must be one OBSERVATION record")
    d = np.asarray(domain)
    if d.dtype != _layout.FACTORED_DOMAIN or d.shape != ():
        raise TypeError("domain must be one FACTORED_DOMAIN record")
    if ext is not None:
        ext = np.asarray(ext)
        if ext.dtype != _layout.OBSERVATION_EXT or ext.shape != ():
            raise TypeError("ext must be one OBSERVATION_EXT record")
        ext = ext.reshape(1)
    obs_part, slot_part, pair_mask = encode_batch(ob.reshape(1), d.reshape(1), ext, ext_supported)
    return obs_part[0], slot_part[0], pair_mask[0]


def is_version(encoder):
    """encoder is an int version as_encoder serves (True == 1 and 1.0 == 1
    are not versions)."""
    return isinstance(encoder, (int, np.integer)) and not isinstance(encoder, bool) and encoder in ENCODERS


def _check_version(encoder):
    if not is_version(encoder):
        raise ValueError(f"encoder {encoder!r} is not one this encoder knows: {ENCODERS}")


def as_encoder(obs_part, observations, encoder):
    """obs_part of encode (OBSERVATION record, (OBS_SIZE,)) or encode_batch
    ((N,), (N, OBS_SIZE)) as encoder version `encoder` makes it, the inputs
    a network of that version was trained on: ENCODER gives obs_part
    itself; 2 a copy of the first BASE_OBS_SIZE columns; 1 that copy with
    every present flag back at species_id != 0. Versions 1 and 2 raise
    ValueError for an observation with a value they do not know (Sand, Snow,
    Electric or Misty Terrain, Tox); ValueError for another version."""
    ob = np.asarray(observations)
    part = np.asarray(obs_part)
    if ob.dtype != _layout.OBSERVATION or part.dtype != _F32 or part.shape != ob.shape + (OBS_SIZE,):
        raise TypeError("obs_part must be the float32 obs_part of encode or encode_batch for these observations")
    _check_version(encoder)
    if encoder == ENCODER:
        return obs_part
    ob = ob.reshape(-1)
    _one_hot(ob["weather"], WEATHERS, "weather")
    _one_hot(ob["terrain"], TERRAINS, "terrain")
    _one_hot(ob["sides"]["members"]["status"], AILMENTS, "ailment")
    out = part.reshape(-1, OBS_SIZE)[:, :BASE_OBS_SIZE].copy()
    if encoder == 1:
        rows = np.arange(ob.shape[0])
        viewer = ob["player"].astype(np.int64)
        for k, side in enumerate((viewer, 1 - viewer)):
            out[:, _PRESENT[k]] = (ob["sides"][rows, side]["members"]["species_id"] != 0).astype(_F32)
    return out.reshape(part.shape[:-1] + (BASE_OBS_SIZE,))


def slots_as_encoder(slot_part, encoder):
    """slot_part of encode or encode_batch as encoder version `encoder`
    makes it: itself, for every version; versions 1 and 2 raise ValueError
    for a Recharge option (move slot 5), which they do not know."""
    part = np.asarray(slot_part)
    if part.dtype != _F32 or part.shape[-3:] != (2, OPTIONS, SLOT_FEATURES):
        raise TypeError("slot_part must be the float32 slot_part of encode or encode_batch")
    _check_version(encoder)
    if encoder != ENCODER and ((part[..., _KIND_MOVE] == 1.0) & (part[..., _MOVE_SLOT] > 1.0)).any():
        raise ValueError(f"a Recharge option (move slot 5) is not one encoder {encoder} knows")
    return slot_part
