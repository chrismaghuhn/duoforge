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
from duoforge_replay import split as player_split

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
    """The BC encoder mask: the base-value features of the library's run-time mask that the tracker folds. ValueError
    naming both values
    when the tracker's parsed support differs from the run-time mask: the rows were folded under the former."""
    library = library_mask(context)
    if lines.LIBRARY_SUPPORTED != library:
        raise ValueError(f"the tracker's parsed support {lines.LIBRARY_SUPPORTED:#x} differs from the loaded library's "
                         f"run-time mask {library:#x}: rebuild the library or the checkout")
    # only the bits the tracker folds: a base-value bit it does not fold never reaches a row (its lines stop), so a
    # network would keep random input rows for it and record it as learned
    return features.BASE_VALUE_FEATURES & library & lines.TRACKER_FOLDS


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


def _pack(a):
    """(N, ...) bool -> (N, bytes) u8, little bit order."""
    return np.packbits(np.asarray(a, dtype=bool).reshape(len(a), -1), axis=1, bitorder="little")


def _unpack(bits, shape):
    n = len(bits)
    count = int(np.prod(shape))
    return np.unpackbits(bits, axis=1, count=count, bitorder="little").astype(bool).reshape((n,) + shape)


@dataclass
class Rows:
    """Training rows, one per shard row (N). obs, slots and the pair mask are features.encode_batch's. The three bool
    masks are kept bit-packed (1.1 million M-C and M-B rows must fit in memory) and read through mask, label_pairs and
    label_team."""
    obs: np.ndarray          # (N, OBS_SIZE) f32
    slots: np.ndarray        # (N, 2, 32, 12) f32
    mask_bits: np.ndarray    # (N, 128) u8: the pair mask (N, 32, 32)
    is_team: np.ndarray      # (N,) bool
    pair_bits: np.ndarray    # (N, 128) u8: the label set of a decision (N, 32, 32), empty for a team row
    team_bits: np.ndarray    # (N, 45) u8: the label set of a team selection (N, 360), empty for a decision
    reason: np.ndarray       # (N, 2) u8, the labels.* reason per slot
    z: np.ndarray            # (N,) f32, +1 won / -1 lost / 0 no winner
    has_z: np.ndarray        # (N,) bool
    weight: np.ndarray       # (N,) f32
    val: np.ndarray          # (N,) bool, the validation split
    side: np.ndarray         # (N,) u8
    fmt: np.ndarray          # (N,) str, the format id
    replay: np.ndarray       # (N,) str, the replay id (for errors)
    point: np.ndarray        # (N,) u16

    @classmethod
    def from_arrays(cls, mask, label_pairs, label_team, **rest):
        """Rows of unpacked bool masks."""
        return cls(mask_bits=_pack(mask), pair_bits=_pack(label_pairs), team_bits=_pack(label_team), **rest)

    @property
    def mask(self):
        return _unpack(self.mask_bits, (OPTIONS, OPTIONS))

    @property
    def label_pairs(self):
        return _unpack(self.pair_bits, (OPTIONS, OPTIONS))

    @property
    def label_team(self):
        return _unpack(self.team_bits, (TEAMS,))

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


def dataset_source(out):
    """The source of a dataset (its manifest.json): what a format version 2 manifest names ("sheet", "bo1_belief",
    "drop_sheets"), or "sheet" for format version 1, built before the source existed, when every dataset was a sheet
    build. ValueError for a later manifest without a source: a belief dataset never passes for sheets."""
    manifest = json.loads((Path(out) / "manifest.json").read_text(encoding="utf-8"))
    if "source" in manifest:
        if manifest["source"] not in dataset.SOURCES:
            raise ValueError(f"{out}: source {manifest['source']!r} is none of {dataset.SOURCES}")
        return manifest["source"]
    if manifest.get("format_version") == 1:
        return "sheet"
    raise ValueError(f"{out}: a format version {manifest.get('format_version')} manifest that names no source")


def _source_weight(out, source_weights):
    """The weight of a dataset's source: as named, 1 for sheets otherwise; any other source must be named."""
    source = dataset_source(out)
    if source == "drop_sheets":
        raise ValueError(f"{out}: a drop_sheets dataset holds the test split's games for validation; it never trains")
    if source in (source_weights or {}):
        return float(source_weights[source])
    if source == "sheet":
        return 1.0
    raise ValueError(f"{out}: source {source} needs --source-weight {source}=FACTOR (M11 Bo1 spec section 5: never "
                     "mixed with sheet rows by default)")


def _format_weight(fmt, format_weights):
    for prefix, factor in (format_weights or {}).items():
        if fmt.startswith(prefix):
            return float(factor)
    return 1.0


def _shard_rows(out):
    """The number of rows of every finished part's shards (their manifests)."""
    return sum(s["rows"] for part in dataset.parts(out)
               for s in json.loads((Path(part) / "manifest.json").read_text(encoding="utf-8"))["shards"])


def load(dirs, context, mask, format_weights=None, weights="rating", source_weights=None):
    """The Rows of every shard of the datasets `dirs`, encoded under `mask`, into arrays allocated once (no copy of
    the whole set). weights: "rating" (rating_weight) or "uniform"; format_weights: {format prefix: factor};
    source_weights: {dataset source: factor} (dataset_source; a source other than sheet must be named)."""
    if weights not in ("rating", "uniform"):
        raise ValueError(f"weights must be 'rating' or 'uniform', not {weights!r}")
    for out in dirs:
        _check_dataset(out, context)
    source_weight = {out: _source_weight(out, source_weights) for out in dirs}
    by_players = {out: dataset_source(out) != "sheet" for out in dirs}  # drawn sheets change with each draw
    n = sum(_shard_rows(out) for out in dirs)
    if n == 0:
        raise ValueError(f"no rows in {list(map(str, dirs))}")
    rows = Rows(obs=np.empty((n, features.OBS_SIZE), np.float32),
                slots=np.empty((n, 2, OPTIONS, features.SLOT_FEATURES), np.float32),
                mask_bits=np.empty((n, OPTIONS * OPTIONS // 8), np.uint8), is_team=np.empty(n, bool),
                pair_bits=np.empty((n, OPTIONS * OPTIONS // 8), np.uint8), team_bits=np.empty((n, 45), np.uint8),
                reason=np.empty((n, 2), np.uint8), z=np.empty(n, np.float32), has_z=np.empty(n, bool),
                weight=np.empty(n, np.float32), val=np.empty(n, bool), side=np.empty(n, np.uint8),
                fmt=np.empty(n, object), replay=np.empty(n, object), point=np.empty(n, np.uint16))
    at = 0
    for out in dirs:
        games_of = {}
        for shard in dataset.read(out):
            part = shard["part"]
            if part not in games_of:
                games_of[part] = dataset.read_games(Path(out) / part)
            g = games_of[part]
            k = len(shard["game"])
            sl = slice(at, at + k)
            game, side = shard["game"].astype(np.int64), shard["side"].astype(np.int64)
            obs, slots, pair_mask = features.encode_batch(shard["observation"], shard["domain"], ext=None,
                                                          ext_supported=mask)
            is_team = shard["domain"]["kind"] == TEAM
            pairs = (_bits(shard["label_slots"][:, 0], OPTIONS)[:, :, None]
                     & _bits(shard["label_slots"][:, 1], OPTIONS)[:, None, :] & pair_mask)
            pairs[is_team] = False
            team = shard["label_team"].copy()
            team[~is_team] = 0
            winner = g["winner"][game].astype(np.int64)
            has_z = winner >= 0
            fmt = g["format_id"][game]
            rating = g["ratings"][game, side]
            rows.obs[sl], rows.slots[sl] = obs, slots
            rows.mask_bits[sl], rows.pair_bits[sl], rows.team_bits[sl] = _pack(pair_mask), _pack(pairs), team
            rows.is_team[sl], rows.reason[sl] = is_team, shard["label_reason"]
            rows.has_z[sl] = has_z
            rows.z[sl] = np.where(~has_z, 0.0, np.where(winner == side, 1.0, -1.0))
            rows.weight[sl] = [(rating_weight(int(r)) if weights == "rating" else 1.0)
                               * _format_weight(f, format_weights) * source_weight[out] for r, f in zip(rating, fmt)]
            if by_players[out]:
                rows.val[sl] = [player_split.of_game(tuple(int(h) for h in g["players"][i])) == "test" for i in game]
            else:
                rows.val[sl] = [split_key(g["sheets"][i]) for i in game]
            rows.side[sl], rows.fmt[sl], rows.replay[sl] = shard["side"], fmt, g["replay_id"][game]
            rows.point[sl] = shard["point"]
            at += k
    if at != n:
        raise ValueError(f"the manifests name {n} rows, the shards hold {at}")
    rows.fmt, rows.replay = rows.fmt.astype(str), rows.replay.astype(str)
    return rows


def check_labels(rows):
    """ValueError naming the first row whose label set is empty (a decision without a pair inside its pair mask, a
    team selection without a tuple): the labeler guarantees the logged choice is inside, so an empty set is a bug,
    never a row to train on with -log 0."""
    empty = np.where(rows.is_team, ~rows.team_bits.any(axis=1), ~rows.pair_bits.any(axis=1))
    if empty.any():
        i = int(np.flatnonzero(empty)[0])
        raise ValueError(f"replay {rows.replay[i]} point {int(rows.point[i])} side {int(rows.side[i])}: an empty label "
                         f"set ({int(empty.sum())} rows)")


def batches(rows, index, size, rng):
    """Rows of `index` in a random order (rng), `size` at a time; the last batch may be smaller."""
    order = np.asarray(index)[rng.permutation(len(index))]
    for start in range(0, len(order), size):
        yield rows.take(order[start:start + size])
