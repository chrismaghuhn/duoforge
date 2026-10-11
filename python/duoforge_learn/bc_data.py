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
is an explicit error. The shards carry each row's extension record (format version 3), so the mask holds every
feature the tracker folds; a dataset built without the records (versions 1 and 2) or folded under other folds is
refused: its rows can hold fold states the encoder would not see.

Rows of pick hypotheses (H > 1, format version 4; M11 pick hypotheses spec, section 5) are left out unless
pick_hypotheses_weight W is given; then each weighs W/H. A version 3 dataset has none.

split="players" (for every source) takes a test player's game (duoforge_replay.split) out of training entirely and
validates only on the rows whose acting player is the test player; the other side of such a game is in neither (its
player trains in other games). With memmap (a directory outside the repository) the encoded rows go into one .npy
memmap per field there instead of memory (6.6 million rows are about 51 GB), flushed to disk with rows.json last
(the key, every array's dtype and shape); load_memmap opens such a directory again and checks them.
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
    return library & lines.TRACKER_FOLDS


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


def _check_folds(out):
    """ValueError unless the dataset carries the extension records (format version 3) and was folded under the
    tracker folds of this checkout."""
    manifest = json.loads((Path(out) / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("format_version")
    if not isinstance(version, int) or version < 3:
        raise ValueError(f"{out} was built without the extension record (format version {version}): since #334 its "
                         "rows can hold fold states the encoder cannot see; rebuild it")
    if manifest.get("tracker_folds") != lines.TRACKER_FOLDS:
        raise ValueError(f"{out}: rows folded under other folds ({manifest.get('tracker_folds')!r}, this checkout "
                         f"{lines.TRACKER_FOLDS:#x}): rebuild it")


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


def _version(out):
    return json.loads((Path(out) / "manifest.json").read_text(encoding="utf-8")).get("format_version")


def _shard_rows(out, hypotheses=True):
    """The number of rows of every finished part's shards (their manifests), without the rows of pick hypotheses
    unless `hypotheses`."""
    version = _version(out)
    n = 0
    for part in dataset.parts(out):
        for s in json.loads((Path(part) / "manifest.json").read_text(encoding="utf-8"))["shards"]:
            n += s["rows"]
            if not hypotheses and version >= 4:
                n -= s["hypothesis_rows"]
    return n


def _hypotheses(shard, version):
    """H of each row of a shard: its picks_hypotheses (format version 4), 1 for a version 3 shard."""
    if version >= 4:
        return shard["picks_hypotheses"].astype(np.int64)
    return np.ones(len(shard["game"]), np.int64)


SPLITS = ("sheet", "players")
# the Rows fields a memmap directory holds as .npy memmaps; fmt and replay (strings) are plain .npy files
_MEMMAP_FIELDS = ("obs", "slots", "mask_bits", "is_team", "pair_bits", "team_bits", "reason", "z", "has_z", "weight",
                  "val", "side", "point")
_MEMMAP_DONE = "rows.json"


def _alloc(memmap, name, shape, dtype):
    if memmap is None:
        return np.empty(shape, dtype)
    shape = shape if isinstance(shape, tuple) else (shape,)
    return np.lib.format.open_memmap(Path(memmap) / f"{name}.npy", mode="w+", dtype=dtype, shape=shape)


def _field_shapes(n):
    """The dtype and shape of every memmap field of n rows under this checkout's encoder."""
    return {"obs": ("float32", [n, features.OBS_SIZE]), "slots": ("float32", [n, 2, OPTIONS, features.SLOT_FEATURES]),
            "mask_bits": ("uint8", [n, OPTIONS * OPTIONS // 8]), "is_team": ("bool", [n]),
            "pair_bits": ("uint8", [n, OPTIONS * OPTIONS // 8]), "team_bits": ("uint8", [n, 45]),
            "reason": ("uint8", [n, 2]), "z": ("float32", [n]), "has_z": ("bool", [n]), "weight": ("float32", [n]),
            "val": ("bool", [n]), "side": ("uint8", [n]), "point": ("uint16", [n])}


def load_memmap(path, key=None):
    """The Rows of a memmap directory that load wrote (read-only memmaps). ValueError for a directory without its
    completion record (a run that did not finish writing it), of another key, or whose arrays are not this encoder's
    (rows.json's dtype and shape of each, and the files themselves)."""
    path = Path(path)
    try:
        done = json.loads((path / _MEMMAP_DONE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{path} is not a complete rows directory (no {_MEMMAP_DONE})") from None
    if key is not None and done.get("key") != key:
        raise ValueError(f"{path}: rows of key {done.get('key')!r}, not {key!r}")
    n = done["rows"]
    want = _field_shapes(n)
    arrays = {}
    for name in _MEMMAP_FIELDS:
        dtype, shape = want[name]
        if done["fields"].get(name) != {"dtype": dtype, "shape": shape}:
            raise ValueError(f"{path}: {name} is {done['fields'].get(name)}, this encoder's is {dtype} {shape}")
        a = np.load(path / f"{name}.npy", mmap_mode="r")
        if str(a.dtype) != dtype or list(a.shape) != shape:
            raise ValueError(f"{path}: {name}.npy is {a.dtype} {list(a.shape)}, rows.json names {dtype} {shape}")
        arrays[name] = a
    arrays.update({name: np.load(path / f"{name}.npy") for name in ("fmt", "replay")})
    if any(len(arrays[name]) != n for name in ("fmt", "replay")):
        raise ValueError(f"{path}: fmt or replay of another length than its {n} rows")
    return Rows(**arrays)


def _player_plans(out, with_hypotheses):
    """Per shard of a dataset, in dataset.read's order: (keep, val) of the players split (module docstring)."""
    plans = []
    for part in dataset.parts(out):
        games = dataset.read_games(part)
        test = np.array([[player_split.is_test_player(h) for h in pair] for pair in games["players"]],
                        dtype=bool).reshape(-1, 2)
        manifest = json.loads((Path(part) / "manifest.json").read_text(encoding="utf-8"))
        for shard in manifest["shards"]:
            with np.load(Path(part) / shard["file"]) as z:
                game, side = z["game"].astype(np.int64), z["side"].astype(np.int64)
                h = z["picks_hypotheses"] if "picks_hypotheses" in z.files else np.ones(len(game), np.uint8)
            actor = test[game, side]
            keep = ~test[game].any(axis=1) | actor
            if not with_hypotheses:
                keep &= h == 1
            plans.append((keep, actor[keep]))
    return plans


def load(dirs, context, mask, format_weights=None, weights="rating", source_weights=None,
         pick_hypotheses_weight=None, split="sheet", memmap=None, key=None):
    """The Rows of every shard of the datasets `dirs`, encoded under `mask`, into arrays allocated once (no copy of
    the whole set). weights: "rating" (rating_weight) or "uniform"; format_weights: {format prefix: factor};
    source_weights: {dataset source: factor} (dataset_source; a source other than sheet must be named);
    pick_hypotheses_weight: W above 0 takes the rows of pick hypotheses at W/H each (None leaves them out);
    split: "sheet" (the sheet pair for sheet datasets, the players for the others) or "players" (module docstring);
    memmap: a new directory outside the repository for the arrays, key: the cache key its rows.json records."""
    if weights not in ("rating", "uniform"):
        raise ValueError(f"weights must be 'rating' or 'uniform', not {weights!r}")
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, not {split!r}")
    if memmap is not None:
        dataset.refuse_repository(memmap)
        memmap = Path(memmap)
        if memmap.exists() and any(memmap.iterdir()):
            raise ValueError(f"the rows directory {memmap} is not empty: a run writes a new one")
        memmap.mkdir(parents=True, exist_ok=True)
    if pick_hypotheses_weight is not None and not float(pick_hypotheses_weight) > 0:
        raise ValueError(f"pick_hypotheses_weight must be above 0 (None leaves the rows out), "
                         f"not {pick_hypotheses_weight!r}")
    with_hypotheses = pick_hypotheses_weight is not None
    for out in dirs:
        _check_dataset(out, context)
        _check_folds(out)
    source_weight = {out: _source_weight(out, source_weights) for out in dirs}
    # drawn sheets change with each draw: a belief dataset always splits by its players
    by_players = {out: split == "players" or dataset_source(out) != "sheet" for out in dirs}
    plans = {out: _player_plans(out, with_hypotheses) for out in dirs} if split == "players" else None
    if plans is None:
        n = sum(_shard_rows(out, with_hypotheses) for out in dirs)
    else:
        n = sum(int(keep.sum()) for out in dirs for keep, _ in plans[out])
    if n == 0:
        raise ValueError(f"no rows in {list(map(str, dirs))}")
    m = memmap
    rows = Rows(obs=_alloc(m, "obs", (n, features.OBS_SIZE), np.float32),
                slots=_alloc(m, "slots", (n, 2, OPTIONS, features.SLOT_FEATURES), np.float32),
                mask_bits=_alloc(m, "mask_bits", (n, OPTIONS * OPTIONS // 8), np.uint8),
                is_team=_alloc(m, "is_team", n, bool),
                pair_bits=_alloc(m, "pair_bits", (n, OPTIONS * OPTIONS // 8), np.uint8),
                team_bits=_alloc(m, "team_bits", (n, 45), np.uint8), reason=_alloc(m, "reason", (n, 2), np.uint8),
                z=_alloc(m, "z", n, np.float32), has_z=_alloc(m, "has_z", n, bool),
                weight=_alloc(m, "weight", n, np.float32), val=_alloc(m, "val", n, bool),
                side=_alloc(m, "side", n, np.uint8), fmt=np.empty(n, object), replay=np.empty(n, object),
                point=_alloc(m, "point", n, np.uint16))
    at = 0
    for out in dirs:
        games_of = {}
        version = _version(out)
        for shard in dataset.read(out):
            part = shard["part"]
            if part not in games_of:
                games_of[part] = dataset.read_games(Path(out) / part)
            g = games_of[part]
            h = _hypotheses(shard, version)
            plan_val = None
            if plans is not None:
                keep, plan_val = plans[out].pop(0)
                shard = {name: (a[keep] if name != "part" else a) for name, a in shard.items()}
                h = h[keep]
            elif not with_hypotheses:
                keep = h == 1
                shard = {name: (a[keep] if name != "part" else a) for name, a in shard.items()}
                h = h[keep]
            k = len(shard["game"])
            sl = slice(at, at + k)
            game, side = shard["game"].astype(np.int64), shard["side"].astype(np.int64)
            obs, slots, pair_mask = features.encode_batch(shard["observation"], shard["domain"], ext=shard["ext"],
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
            if with_hypotheses:
                rows.weight[sl] *= np.where(h > 1, float(pick_hypotheses_weight) / h, 1.0).astype(np.float32)
            if plan_val is not None:
                rows.val[sl] = plan_val
            elif by_players[out]:
                rows.val[sl] = [player_split.of_game(tuple(int(h) for h in g["players"][i])) == "test" for i in game]
            else:
                rows.val[sl] = [split_key(g["sheets"][i]) for i in game]
            rows.side[sl], rows.fmt[sl], rows.replay[sl] = shard["side"], fmt, g["replay_id"][game]
            rows.point[sl] = shard["point"]
            at += k
    if at != n:
        raise ValueError(f"the manifests name {n} rows, the shards hold {at}")
    rows.fmt, rows.replay = rows.fmt.astype(str), rows.replay.astype(str)
    if memmap is not None:
        for name in _MEMMAP_FIELDS:
            getattr(rows, name).flush()
            dataset.fsync_file(memmap / f"{name}.npy")
        for name in ("fmt", "replay"):
            np.save(memmap / f"{name}.npy", getattr(rows, name))
            dataset.fsync_file(memmap / f"{name}.npy")
        fields_ = {name: {"dtype": dtype, "shape": shape} for name, (dtype, shape) in _field_shapes(n).items()}
        dataset.write_json_atomic(memmap / _MEMMAP_DONE, {"rows": n, "split": split, "key": key, "fields": fields_})
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
    """Rows of `index` in a random order (rng), `size` at a time; the last batch may be smaller. Memmap rows are taken
    in index order inside each batch, so the disk is read front to back (the same batches; rows in memory keep the
    order, bit-equal to the runs before memmaps)."""
    order = np.asarray(index)[rng.permutation(len(index))]
    on_disk = isinstance(rows.obs, np.memmap)
    for start in range(0, len(order), size):
        chunk = order[start:start + size]
        yield rows.take(np.sort(chunk) if on_disk else chunk)
