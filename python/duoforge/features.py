"""The observation-only feature encoder (M7 spec section 5).

encode(observation, domain) -> (obs_part, slot_part, pair_mask) is a pure
function of one player's observation and factored domain, and
encode_batch(observations, domains) the same for N players at once
(vectorized; encode is encode_batch of one player); it never reads a
battle, so it carries nothing beyond what decision 0007 proves for the
observation. Every value is scaled to [0, 1] (ids by 65535, so a network
can recover them exactly as round(x * 65535) for an embedding). A value
outside the known sets below (an ailment, weather, terrain, location or
boundary kind this encoder does not know) raises ValueError; it is never
encoded as zeros. So does a domain of another boundary than the
observation's (another epoch, or a request where the observation has none):
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
      flash fire, protecting, occupant one-hot (7: roster 0..5, none)
    per member, roster 0..5: present, hp / hp_max (0 when hp_max is 0),
      location one-hot (LOCATIONS), status one-hot (AILMENTS), is mega,
      mega capable, item used, item / 255, ability / 255, gender / 3,
      nature / 24, species / 65535, move ids / 65535 (4), pp / pp_max (4,
      0 when pp_max is 0), move count / 4, stat points / 32 (6),
      stats / 1000 (5, at most 1)

slot_part, float32 (2, 32, SLOT_FEATURES): for slot list s and entry i,
  valid (i < slot_count[s]), kind one-hot (4: none, move, switch, pass),
  move slot / 4 (moves only; Struggle is 4), target one-hot relative to
  the viewer (4: own slot 0, own slot 1, foe slot 0, foe slot 1; none for
  a move without a target), mega, reserve / 5 (switches only). All zero
  past slot_count and at team selection.

pair_mask, bool (32, 32): [i, j] is bit j of domain.allowed[i], the pair
  rule of the engine; its sum is the joint count at a SLOTS boundary and
  0 at team selection.
"""
import numpy as np

from . import _layout

C = _layout.CONSTANTS
OPTIONS = _layout.MAX_SLOT_OPTIONS

BOUNDARIES = tuple(C[f"DUOFORGE_BOUNDARY_{n}"] for n in ("TEAM_SELECTION", "TURN", "REPLACEMENT", "PIVOT",
                                                          "TERMINAL"))
WEATHERS = tuple(C[f"DUOFORGE_WEATHER_{n}"] for n in ("NONE", "RAIN", "SUN"))
TERRAINS = tuple(C[f"DUOFORGE_TERRAIN_{n}"] for n in ("NONE", "GRASSY"))
LOCATIONS = tuple(C[f"DUOFORGE_LOCATION_{n}"] for n in ("UNDETERMINED", "BENCH", "ACTIVE", "NOT_BROUGHT"))
AILMENTS = tuple(C[f"DUOFORGE_AILMENT_{n}"] for n in ("NONE", "BURN", "FREEZE", "PARALYSIS", "SLEEP", "POISON"))
SLOT_KINDS = tuple(C[f"DUOFORGE_SLOT_{n}"] for n in ("NONE", "MOVE", "SWITCH", "PASS"))

SLOT_FEATURES = 12
_GLOBAL = len(BOUNDARIES) + 1 + len(WEATHERS) + 1 + len(TERRAINS) + 2
_SIDE = 8
_POSITION = 7 + 7 + 7
_MEMBER = 2 + len(LOCATIONS) + len(AILMENTS) + 8 + 4 + 4 + 1 + 6 + 5
OBS_SIZE = _GLOBAL + 2 * (_SIDE + 2 * _POSITION + 6 * _MEMBER)


_F64 = np.float64
_F32 = np.float32
_OCCUPANTS = tuple(range(_layout.MAX_ROSTER)) + (C["DUOFORGE_ROSTER_NONE"],)


def _one_hot(values, known, what):
    """One-hot float32 rows over `known` for every value (any shape);
    ValueError for a value outside `known`."""
    values = np.asarray(values).astype(np.int64)
    table = np.full(max(256, int(values.max(initial=0)) + 1), -1, dtype=np.int64)
    table[list(known)] = np.arange(len(known))
    index = table[values]
    if (index < 0).any():
        bad = int(values[index < 0].flat[0])
        raise ValueError(f"{what} {bad} is not one this encoder knows: {known}")
    return np.eye(len(known), dtype=_F32)[index]


def _ratio(values, divisor):
    """values / divisor in float64, as float32 (the scale of a count)."""
    return (np.asarray(values).astype(_F64) / divisor).astype(_F32)


def _sides(s):
    """The side features of SIDE_VIEW records s (N,): (N, side size)."""
    n = s.shape[0]
    rs = s["requested_slots"].astype(np.int64)
    head = np.stack([s["member_count"].astype(_F64) / 6, s["mega_used"].astype(_F64), s["requested"].astype(_F64),
                     (rs & 1).astype(_F64), ((rs >> 1) & 1).astype(_F64), s["reflect_turns"].astype(_F64) / 8,
                     s["light_screen_turns"].astype(_F64) / 8, s["tailwind_turns"].astype(_F64) / 4],
                    axis=1).astype(_F32)
    pos = s["positions"]
    flags = np.stack([pos["confused"].astype(_F64), pos["charging"].astype(_F64),
                      (pos["locked_slot"] != C["DUOFORGE_MOVE_SLOT_NONE"]).astype(_F64), pos["acted"].astype(_F64),
                      np.clip(pos["protect_chain"].astype(_F64) / 3, 0.0, 1.0), pos["flash_fire"].astype(_F64),
                      pos["protecting"].astype(_F64)], axis=-1).astype(_F32)
    positions = np.concatenate([pos["stages"].astype(_F32) / 12, flags,
                                _one_hot(s["occupant"], _OCCUPANTS, "occupant")], axis=-1).reshape(n, -1)
    m = s["members"]
    hp_max = m["hp_max"].astype(_F64)
    hp = np.divide(m["hp"].astype(_F64), hp_max, out=np.zeros(hp_max.shape), where=hp_max > 0)
    pp_max = m["pp_max"].astype(_F32)
    members = np.concatenate([
        np.stack([(m["species_id"] != 0).astype(_F64), hp], axis=-1).astype(_F32),
        _one_hot(m["location"], LOCATIONS, "location"),
        _one_hot(m["status"], AILMENTS, "ailment"),
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


def encode_batch(observations, domains):
    """(obs_part (N, OBS_SIZE), slot_part (N, 2, 32, SLOT_FEATURES),
    pair_mask (N, 32, 32)) of N players' observations (OBSERVATION, (N,))
    and factored domains (FACTORED_DOMAIN, (N,)); row n is encode of
    player n. See the module docstring for the layout."""
    ob = np.asarray(observations)
    d = np.asarray(domains)
    if ob.dtype != _layout.OBSERVATION or ob.ndim != 1:
        raise TypeError("observations must be a one-dimensional OBSERVATION array")
    if d.dtype != _layout.FACTORED_DOMAIN or d.shape != ob.shape:
        raise TypeError("domains must be a FACTORED_DOMAIN array of the observations' shape")
    if ((ob["epoch"] != d["epoch"]) | ((ob["requested"] != 0) != (d["kind"] != 0))).any():
        raise ValueError("the domain is not of the observation's boundary (query_factored() refreshes both)")
    n = ob.shape[0]
    rows = np.arange(n)
    viewer = ob["player"].astype(np.int64)
    glob = np.concatenate([
        _one_hot(ob["boundary_kind"], BOUNDARIES, "boundary kind"),
        np.clip(ob["turn"].astype(_F64) / 100, 0.0, 1.0)[:, None].astype(_F32),
        _one_hot(ob["weather"], WEATHERS, "weather"),
        _ratio(ob["weather_turns"], 8)[:, None],
        _one_hot(ob["terrain"], TERRAINS, "terrain"),
        np.stack([_ratio(ob["terrain_turns"], 8), _ratio(ob["trick_room_turns"], 5)], axis=1),
    ], axis=1)
    obs_part = np.concatenate([glob, _sides(ob["sides"][rows, viewer]), _sides(ob["sides"][rows, 1 - viewer])],
                              axis=1).astype(_F32)

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
    f[move, 5] = _ratio(cmd["move_slot"][move], 4)
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


def encode(observation, domain):
    """(obs_part, slot_part, pair_mask) of one player's observation
    (OBSERVATION) and factored domain (FACTORED_DOMAIN); encode_batch of
    one player."""
    ob = np.asarray(observation)
    if ob.dtype != _layout.OBSERVATION or ob.shape != ():
        raise TypeError("observation must be one OBSERVATION record")
    d = np.asarray(domain)
    if d.dtype != _layout.FACTORED_DOMAIN or d.shape != ():
        raise TypeError("domain must be one FACTORED_DOMAIN record")
    obs_part, slot_part, pair_mask = encode_batch(ob.reshape(1), d.reshape(1))
    return obs_part[0], slot_part[0], pair_mask[0]
