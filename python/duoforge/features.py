"""The observation-only feature encoder (M7 spec section 5).

encode(observation, domain) -> (obs_part, slot_part, pair_mask) is a pure
function of one player's observation and factored domain; it never reads a
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


def _one_hot(value, known, what):
    value = int(value)
    if value not in known:
        raise ValueError(f"{what} {value} is not one this encoder knows: {known}")
    out = np.zeros(len(known), dtype=np.float32)
    out[known.index(value)] = 1.0
    return out


def _clip(x):
    return min(max(float(x), 0.0), 1.0)


def _member(m):
    hp_max = int(m["hp_max"])
    pp_max = m["pp_max"].astype(np.float32)
    pp = np.divide(m["pp"].astype(np.float32), pp_max, out=np.zeros(4, np.float32), where=pp_max > 0)
    head = [1.0 if int(m["species_id"]) != 0 else 0.0, int(m["hp"]) / hp_max if hp_max > 0 else 0.0]
    tail = [int(m["is_mega"]), int(m["mega_capable"]), int(m["item_used"]), int(m["item"]) / 255,
            int(m["ability"]) / 255, int(m["gender"]) / 3, int(m["nature"]) / 24, int(m["species_id"]) / 65535]
    return np.concatenate([
        np.array(head, np.float32),
        _one_hot(m["location"], LOCATIONS, "location"),
        _one_hot(m["status"], AILMENTS, "ailment"),
        np.array(tail, np.float32),
        m["move_ids"].astype(np.float32) / 65535,
        pp,
        np.array([int(m["move_count"]) / 4], np.float32),
        m["stat_points"].astype(np.float32) / 32,
        np.minimum(m["stats"].astype(np.float32) / 1000, 1.0),
    ])


def _position(pos, occupant):
    flags = [int(pos["confused"]), int(pos["charging"]),
             1.0 if int(pos["locked_slot"]) != C["DUOFORGE_MOVE_SLOT_NONE"] else 0.0,
             int(pos["acted"]), _clip(int(pos["protect_chain"]) / 3), int(pos["flash_fire"]), int(pos["protecting"])]
    occupants = tuple(range(_layout.MAX_ROSTER)) + (C["DUOFORGE_ROSTER_NONE"],)
    return np.concatenate([
        pos["stages"].astype(np.float32) / 12,
        np.array(flags, np.float32),
        _one_hot(occupant, occupants, "occupant"),
    ])


def _side(side):
    head = [int(side["member_count"]) / 6, int(side["mega_used"]), int(side["requested"]),
            int(side["requested_slots"]) & 1, (int(side["requested_slots"]) >> 1) & 1,
            int(side["reflect_turns"]) / 8, int(side["light_screen_turns"]) / 8, int(side["tailwind_turns"]) / 4]
    parts = [np.array(head, np.float32)]
    parts += [_position(side["positions"][k], side["occupant"][k]) for k in range(2)]
    parts += [_member(side["members"][i]) for i in range(_layout.MAX_ROSTER)]
    return np.concatenate(parts)


def _slot(cmd, viewer, f):
    f[0] = 1.0
    kind = int(cmd["kind"])
    f[1:5] = _one_hot(kind, SLOT_KINDS, "slot command kind")
    if kind == C["DUOFORGE_SLOT_MOVE"]:
        f[5] = int(cmd["move_slot"]) / 4
        target = int(cmd["target"])
        if target != C["DUOFORGE_TARGET_NONE"]:
            if not 0 <= target < 4:
                raise ValueError(f"target {target} is not a position")
            f[6 + ((target >> 1) ^ viewer) * 2 + (target & 1)] = 1.0
        f[10] = int(cmd["mega"])
    elif kind == C["DUOFORGE_SLOT_SWITCH"]:
        f[11] = int(cmd["reserve"]) / 5


def encode(observation, domain):
    """(obs_part, slot_part, pair_mask) of one player's observation
    (OBSERVATION) and factored domain (FACTORED_DOMAIN); see the module
    docstring for the layout."""
    ob = np.asarray(observation)
    if ob.dtype != _layout.OBSERVATION or ob.shape != ():
        raise TypeError("observation must be one OBSERVATION record")
    d = np.asarray(domain)
    if d.dtype != _layout.FACTORED_DOMAIN or d.shape != ():
        raise TypeError("domain must be one FACTORED_DOMAIN record")
    if int(ob["epoch"]) != int(d["epoch"]) or (int(ob["requested"]) != 0) != (int(d["kind"]) != 0):
        raise ValueError("the domain is not of the observation's boundary (query_factored() refreshes both)")
    me = int(ob["player"])
    glob = np.concatenate([
        _one_hot(ob["boundary_kind"], BOUNDARIES, "boundary kind"),
        np.array([_clip(int(ob["turn"]) / 100)], np.float32),
        _one_hot(ob["weather"], WEATHERS, "weather"),
        np.array([int(ob["weather_turns"]) / 8], np.float32),
        _one_hot(ob["terrain"], TERRAINS, "terrain"),
        np.array([int(ob["terrain_turns"]) / 8, int(ob["trick_room_turns"]) / 5], np.float32),
    ])
    obs_part = np.concatenate([glob, _side(ob["sides"][me]), _side(ob["sides"][1 - me])]).astype(np.float32)

    slot_part = np.zeros((2, OPTIONS, SLOT_FEATURES), dtype=np.float32)
    pair_mask = np.zeros((OPTIONS, OPTIONS), dtype=bool)
    if int(d["kind"]) == C["DUOFORGE_CHOICE_SLOTS"]:
        for s in range(2):
            for i in range(int(d["slot_count"][s])):
                _slot(d["slots"][s][i], me, slot_part[s, i])
        bits = np.unpackbits(np.ascontiguousarray(d["allowed"], dtype="<u4").view(np.uint8), bitorder="little")
        pair_mask = bits.reshape(OPTIONS, OPTIONS).astype(bool)
    return obs_part, slot_part, pair_mask
