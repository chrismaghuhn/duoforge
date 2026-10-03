"""Observation column groups by name, and the host check of the ids model v2
embeds (decision 0017, spec section 8).

columns(names) splits the encoder's columns (features.FEATURE_NAMES) into
the groups model v2 reads: global, side and position scalars, the occupant
one-hots, member scalars and the member ids. The columns of encoder 3's
block ("ext.global.*", "ext.<side>.*", "ext.<side>.pos<k>.*",
"ext.<side>.mem<r>.*") join the global, side, position and member scalars.
A name the grouping does not know raises, so a new encoder column is never
dropped silently; a checkpoint keeps its own names, so its groups follow its
layout.
"""
import dataclasses

import numpy as np

from duoforge import features

_SIDES = ("own", "foe")
_MEMBER_IDS = ("present", "item", "ability", "nature", "species", "move0", "move1", "move2", "move3", "pp0", "pp1",
               "pp2", "pp3", "move_count")
NATURE_DIM = 8  # model v2's nature embedding
_SCALES = {"species": 65535, "move": 65535, "item": 255, "ability": 255, "nature": 24}


@dataclasses.dataclass(frozen=True)
class Columns:
    """int64 index arrays into the observation and the option columns."""
    glob: np.ndarray        # (G,)
    side: np.ndarray        # (2, S)
    position: np.ndarray    # (2, 2, P): stages, flags, position flags
    occupant: np.ndarray    # (2, 2, 7): roster 0..5, none
    member: np.ndarray      # (2, 6, M): hp, location, status, mega flags, item used, gender, sp, stats
    present: np.ndarray     # (2, 6)
    species: np.ndarray     # (2, 6)
    item: np.ndarray        # (2, 6)
    ability: np.ndarray     # (2, 6)
    nature: np.ndarray      # (2, 6)
    moves: np.ndarray       # (2, 6, 4)
    pp: np.ndarray          # (2, 6, 4)
    move_count: np.ndarray  # (2, 6)
    slot_scalar: np.ndarray  # (10,): valid, kind, target, mega
    slot_move: np.ndarray    # (1,)
    slot_reserve: np.ndarray  # (1,)
    slot_is_move: np.ndarray  # (1,): kind.MOVE
    slot_is_switch: np.ndarray  # (1,): kind.SWITCH


def columns(feature_names=features.FEATURE_NAMES, slot_names=features.SLOT_FEATURE_NAMES):
    """The column groups of an encoder layout given by its names."""
    glob, side, position, occupant, member = [], {}, {}, {}, {}
    ids = {k: {} for k in _MEMBER_IDS}
    for i, name in enumerate(feature_names):
        parts = name.split(".")
        if parts[0] == "global" or parts[:2] == ["ext", "global"]:
            glob.append(i)
            continue
        if parts[0] == "ext" and len(parts) >= 3 and parts[1] in _SIDES:
            s = _SIDES.index(parts[1])
            if len(parts) == 3:
                side.setdefault(s, []).append(i)
            elif parts[2].startswith("pos") and parts[2][3:].isdigit():
                position.setdefault((s, int(parts[2][3:])), []).append(i)
            elif parts[2].startswith("mem") and parts[2][3:].isdigit():
                member.setdefault((s, int(parts[2][3:])), []).append(i)
            else:
                raise ValueError(f"observation column {name!r} is not one model v2 knows")
            continue
        if parts[0] not in _SIDES or len(parts) < 3:
            raise ValueError(f"observation column {name!r} is not one model v2 knows")
        s = _SIDES.index(parts[0])
        if parts[1] == "side":
            side.setdefault(s, []).append(i)
        elif parts[1].startswith("pos") and parts[2] in ("stage", "flag"):
            position.setdefault((s, int(parts[1][3:])), []).append(i)
        elif parts[1].startswith("pos") and parts[2] == "occupant":
            occupant.setdefault((s, int(parts[1][3:])), []).append(i)
        elif parts[1].startswith("member") and parts[2] in _MEMBER_IDS and len(parts) == 3:
            ids[parts[2]][(s, int(parts[1][6:]))] = i
        elif parts[1].startswith("member") and parts[2] in ("hp", "location", "status", "is_mega", "mega_capable",
                                                             "item_used", "gender", "sp", "stat"):
            member.setdefault((s, int(parts[1][6:])), []).append(i)
        else:
            raise ValueError(f"observation column {name!r} is not one model v2 knows")

    def grid(table, shape):
        out = np.array([table[(s, k)] for s in range(2) for k in range(shape[1])], dtype=np.int64)
        return out.reshape(shape + out.shape[1:])

    def ids_of(field):
        return np.array([[ids[field][(s, m)] for m in range(6)] for s in range(2)], dtype=np.int64)

    slot = {n: i for i, n in enumerate(slot_names)}
    for n in slot_names:
        if n not in ("valid", "move_slot", "mega", "reserve") and not n.startswith(("kind.", "target.")):
            raise ValueError(f"option column {n!r} is not one model v2 knows")
    return Columns(
        glob=np.array(glob, dtype=np.int64),
        side=np.array([side[s] for s in range(2)], dtype=np.int64),
        position=grid(position, (2, 2)),
        occupant=grid(occupant, (2, 2)),
        member=grid(member, (2, 6)),
        present=ids_of("present"), species=ids_of("species"), item=ids_of("item"), ability=ids_of("ability"),
        nature=ids_of("nature"),
        moves=np.stack([ids_of(f"move{k}") for k in range(4)], axis=-1),
        pp=np.stack([ids_of(f"pp{k}") for k in range(4)], axis=-1),
        move_count=ids_of("move_count"),
        slot_scalar=np.array([i for n, i in slot.items() if n not in ("move_slot", "reserve")], dtype=np.int64),
        slot_move=np.array([slot["move_slot"]], dtype=np.int64),
        slot_reserve=np.array([slot["reserve"]], dtype=np.int64),
        slot_is_move=np.array([slot["kind.MOVE"]], dtype=np.int64),
        slot_is_switch=np.array([slot["kind.SWITCH"]], dtype=np.int64),
    )


def input_sources(cfg, cols, feature_names, slot_names):
    """For every row of input_rows, the set of observation columns (indices into feature_names) that feed it: one
    for a row of its own, every member's (both sides) for a shared member row, every position's for a shared
    position row, none for the rows of embeddings, earlier layers and option features."""
    e, dm, dp, do = cfg["embed"], cfg["member"], cfg["position"], cfg["option"]

    def fixed(n):
        return [set() for _ in range(n)]

    member = [set(int(i) for i in cols.member[:, :, k].ravel()) for k in range(cols.member.shape[2])]
    position = [set(int(i) for i in cols.position[:, :, k].ravel()) for k in range(cols.position.shape[2])]
    return {
        ("member1",): fixed(5 * e + NATURE_DIM) + member + fixed(2),
        ("position",): position + fixed(1) + fixed(dm),
        ("torso", 0): ([{int(i)} for i in cols.glob] + [{int(i)} for i in cols.side.reshape(-1)]
                       + fixed(4 * dp) + fixed(4 * dm)),
        ("option1",): fixed(len(cols.slot_scalar)) + fixed(e + 2 * dm + do),
    }


def decode(obs, index, table):
    """The integer ids at obs[..., index] of a table scaled by the encoder."""
    return np.rint(np.asarray(obs)[..., index].astype(np.float64) * _SCALES[table]).astype(np.int64)


def check_ids(obs, cols, capacities):
    """Raises ValueError for an id at or past its table's capacity (obs (B, O))."""
    for table, index in (("species", cols.species), ("move", cols.moves), ("item", cols.item),
                         ("ability", cols.ability), ("nature", cols.nature)):
        top = int(decode(obs, index, table).max(initial=0))
        if top >= capacities[table]:
            raise ValueError(f"{table} id {top} is outside the model's capacity {capacities[table]}")


def input_rows(cfg, cols, feature_names, slot_names):
    """The row labels of every layer that reads encoder columns: a column's
    field name where a row comes from the encoder, '#<block>:<i>' for the
    rows of embeddings and earlier layers. widening maps rows by label."""
    e, dm, dp, h, do = cfg["embed"], cfg["member"], cfg["position"], cfg["hidden"], cfg["option"]

    def fixed(block, n):
        return [f"#{block}:{i}" for i in range(n)]

    member = [feature_names[i].split(".", 2)[2] for i in cols.member[0, 0]]
    position = [feature_names[i].split(".", 2)[2] for i in cols.position[0, 0]]
    return {
        ("member1",): fixed("embeddings", 5 * e + NATURE_DIM) + member + ["#side_flag", "#registered"],
        ("position",): position + ["#occupied"] + fixed("occupant", dm),
        ("torso", 0): ([feature_names[i] for i in cols.glob] + [feature_names[i] for i in cols.side.reshape(-1)]
                       + fixed("positions", 4 * dp) + fixed("pools", 4 * dm)),
        ("option1",): [slot_names[i] for i in cols.slot_scalar] + fixed("gathered", e + 2 * dm + do),
    }
