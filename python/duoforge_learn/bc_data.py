"""The replay shards as behavior-cloning training arrays (M11 BC spec sections 5 and 6). NumPy only.

load() reads datasets of duoforge_replay (built in parts), checks that each was
built under the run's library (the context fingerprint in replay-dataset.json),
encodes every row once with features.encode_batch under the BC mask, and gives:

- the label sets: for a decision, the pairs (i, j) of the two slot label masks
  inside the pair mask (pair index i * 32 + j, as the model's pair head); for a
  team selection, the 360 tuple bits over TEAM_TABLE;
- the value target: +1 when the row's side won, -1 when it lost (none without a
  winner);
- the row weight: the acting side's rating (rating_weight) times its format's
  weight;
- the split: validation for the games whose sorted sheet-hash pair lands in
  bucket 0 of 20 (split_key), so the games of one Bo3 match share a side.

The mask (bc_mask) is the base-value features the loaded library supports at run
time (observe_ext's `supported`, as SelfPlay reads it). It must equal the support
the tracker parsed when it folded the rows (lines.LIBRARY_SUPPORTED); a mismatch
is an explicit error. The shards carry no extension records, so no record bit
can be in the mask.
"""
import hashlib
import json
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge_live import lines
from duoforge_replay import dataset

TEAM = _layout.CONSTANTS["DUOFORGE_CHOICE_TEAM_SELECTION"]
OPTIONS = 32
TEAMS = 360
SPLIT_BUCKETS = 20  # bucket 0 is the validation set (about 5 %)


def library_mask(context):
    """The view-extension features the loaded library supports under the context at run time: the `supported` of a
    battle's observe_ext (SelfPlay's reading), on the reference pairing."""
    pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
    batch = duoforge.Batch(context, pool.setups(np.array([0]), np.array([1])), 1, 0)
    try:
        return int(batch.observe_ext()[0, 0]["supported"])
    finally:
        batch.close()


def bc_mask(context):
    """The BC encoder mask: the base-value features of the library's run-time mask. ValueError naming both values
    when the tracker's parsed support differs from the run-time mask: the rows were folded under the former."""
    library = library_mask(context)
    if lines.LIBRARY_SUPPORTED != library:
        raise ValueError(f"the tracker's parsed support {lines.LIBRARY_SUPPORTED:#x} differs from the loaded library's "
                         f"run-time mask {library:#x}: rebuild the library or the checkout")
    return features.BASE_VALUE_FEATURES & library


def rating_weight(rating):
    """1 at a rating of 1300 or more, rising linearly from 0.25 at 1000; 0.25 below 1000 or unrated (-1)."""
    if rating >= 1300:
        return 1.0
    if rating <= 1000:
        return 0.25
    return 0.25 + 0.75 * (rating - 1000) / 300


def split_key(sheets):
    """True for the validation set: bucket 0 of 20 of the sha256 of the sorted pair of sheet hashes, so both sides
    and every game of one match land on the same side of the split."""
    a, b = sorted(int(x) for x in sheets)
    digest = hashlib.sha256(a.to_bytes(8, "little") + b.to_bytes(8, "little")).digest()
    return int.from_bytes(digest[:8], "little") % SPLIT_BUCKETS == 0


@dataclass
class Rows:
    """Training rows, one per shard row (N). obs, slots and mask are features.encode_batch's."""
    obs: np.ndarray          # (N, OBS_SIZE) f32
    slots: np.ndarray        # (N, 2, 32, 12) f32
    mask: np.ndarray         # (N, 32, 32) bool, the pair mask
    is_team: np.ndarray      # (N,) bool
    label_pairs: np.ndarray  # (N, 32, 32) bool, the label set of a decision (False for a team row)
    label_team: np.ndarray   # (N, 360) bool, the label set of a team selection (False for a decision)
    reason: np.ndarray       # (N, 2) u8, the labels.* reason per slot
    z: np.ndarray            # (N,) f32, +1 won / -1 lost / 0 no winner
    has_z: np.ndarray        # (N,) bool
    weight: np.ndarray       # (N,) f32
    val: np.ndarray          # (N,) bool, the validation split
    side: np.ndarray         # (N,) u8
    fmt: np.ndarray          # (N,) str, the format id
    replay: np.ndarray       # (N,) str, the replay id (for errors)
    point: np.ndarray        # (N,) u16

    def take(self, index):
        return Rows(**{f.name: getattr(self, f.name)[index] for f in fields(self)})

    def __len__(self):
        return len(self.weight)


def _bits(masks, width):
    """(N,) unsigned bit masks -> (N, width) bool."""
    masks = np.asarray(masks, dtype=np.uint64)
    return (masks[:, None] >> np.arange(width, dtype=np.uint64)) & np.uint64(1) == 1


def _check_dataset(out, context):
    marker = Path(out) / dataset.MARKER
    if not marker.exists():
        raise ValueError(f"{out} is no dataset built in parts ({dataset.MARKER} missing)")
    built = json.loads(marker.read_text(encoding="utf-8")).get("fingerprint")
    run = context.fingerprint().hex()
    if built != run:
        raise ValueError(f"{out} was built under the library fingerprint {built}, the run's is {run}: rebuild it")


def _format_weight(fmt, format_weights):
    for prefix, factor in (format_weights or {}).items():
        if fmt.startswith(prefix):
            return float(factor)
    return 1.0


def load(dirs, context, mask, format_weights=None, weights="rating"):
    """The Rows of every shard of the datasets `dirs`, encoded under `mask`. weights: "rating" (rating_weight) or
    "uniform"; format_weights: {format prefix: factor}."""
    if weights not in ("rating", "uniform"):
        raise ValueError(f"weights must be 'rating' or 'uniform', not {weights!r}")
    chunks = []
    for out in dirs:
        _check_dataset(out, context)
        games_of = {}
        for shard in dataset.read(out):
            part = shard["part"]
            if part not in games_of:
                games_of[part] = dataset.read_games(Path(out) / part)
            g = games_of[part]
            game, side = shard["game"].astype(np.int64), shard["side"].astype(np.int64)
            obs, slots, pair_mask = features.encode_batch(shard["observation"], shard["domain"], ext=None,
                                                          ext_supported=mask)
            is_team = shard["domain"]["kind"] == TEAM
            pairs = (_bits(shard["label_slots"][:, 0], OPTIONS)[:, :, None]
                     & _bits(shard["label_slots"][:, 1], OPTIONS)[:, None, :] & pair_mask)
            pairs[is_team] = False
            team = np.unpackbits(shard["label_team"], axis=1, bitorder="little")[:, :TEAMS].astype(bool)
            team[~is_team] = False
            winner = g["winner"][game].astype(np.int64)
            has_z = winner >= 0
            z = np.where(~has_z, 0.0, np.where(winner == side, 1.0, -1.0)).astype(np.float32)
            fmt = g["format_id"][game]
            rating = g["ratings"][game, side]
            w = np.array([(rating_weight(int(r)) if weights == "rating" else 1.0) * _format_weight(f, format_weights)
                          for r, f in zip(rating, fmt)], dtype=np.float32)
            val = np.array([split_key(g["sheets"][i]) for i in game], dtype=bool)
            chunks.append(Rows(obs=obs.astype(np.float32), slots=slots.astype(np.float32), mask=pair_mask,
                               is_team=is_team, label_pairs=pairs, label_team=team,
                               reason=shard["label_reason"].astype(np.uint8), z=z, has_z=has_z, weight=w,
                               val=val, side=shard["side"].astype(np.uint8), fmt=fmt,
                               replay=g["replay_id"][game], point=shard["point"].astype(np.uint16)))
    if not chunks:
        raise ValueError(f"no rows in {list(map(str, dirs))}")
    return Rows(**{f.name: np.concatenate([getattr(c, f.name) for c in chunks]) for f in fields(Rows)})


def check_labels(rows):
    """ValueError naming the first row whose label set is empty (a decision without a pair inside its pair mask, a
    team selection without a tuple): the labeler guarantees the logged choice is inside, so an empty set is a bug,
    never a row to train on with -log 0."""
    empty = np.where(rows.is_team, ~rows.label_team.any(axis=1), ~rows.label_pairs.reshape(len(rows), -1).any(axis=1))
    if empty.any():
        i = int(np.flatnonzero(empty)[0])
        raise ValueError(f"replay {rows.replay[i]} point {int(rows.point[i])} side {int(rows.side[i])}: an empty label "
                         f"set ({int(empty.sum())} rows)")


def batches(rows, index, size, rng):
    """Rows of `index` in a random order (rng), `size` at a time; the last batch may be smaller."""
    order = np.asarray(index)[rng.permutation(len(index))]
    for start in range(0, len(order), size):
        yield rows.take(order[start:start + size])
