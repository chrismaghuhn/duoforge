"""P1 private teacher data contracts. No battle rules or learner implementation."""
import base64
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from duoforge import features
from duoforge_replay.dataset import refuse_repository, fsync_dir

SCHEMA_VERSION = 1
KEY_VERSION = 1
MASS_TOLERANCE = 1e-6


class RowStatus(Enum):
    TARGET = "target"
    UNSELECTED = "unselected"
    CAP_RAW = "cap_raw"
    PUBLIC_REFUSAL = "public_refusal"
    WORK_EXHAUSTED = "work_exhausted"
    FORCED = "forced"
    UNREQUESTED = "unrequested"


def _freeze(value):
    if isinstance(value, np.ndarray):
        return np.frombuffer(value.tobytes(order="C"), dtype=value.dtype).reshape(value.shape)
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True, order=True)
class DecisionKey:
    game_id: int
    seat: int
    request_epoch: int


@dataclass(frozen=True)
class SparsePolicy:
    ids: np.ndarray
    probs: np.ndarray

    def __post_init__(self):
        object.__setattr__(self, "ids", _freeze(self.ids))
        object.__setattr__(self, "probs", _freeze(self.probs))


@dataclass(frozen=True)
class DataManifest:
    source_commit: str
    checkpoint_hash: str
    model_hash: str
    encoder: int
    ids_hash: str
    pool_hash: str
    belief_hash: str
    seed: int
    split_seed: int
    key_version: int
    device: str
    runtime: str
    compiler: str
    capacity: int
    workers: int
    parallel_games: int
    game_count: int
    rounds: int
    obs_width: int
    slot_width: int
    teacher_config: Mapping
    budget: Mapping
    evaluation: Mapping
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        for name in ("teacher_config", "budget", "evaluation"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class ExpertRow:
    key: DecisionKey
    logical_tick: int
    boundary: str
    obs: np.ndarray
    slots: np.ndarray
    legal_mask: np.ndarray
    sparse_policy: SparsePolicy | None
    status: RowStatus
    raw_action: int | None
    action: int | None
    behavior_logp: float | None
    requested: bool
    acting: bool
    learner: bool
    value_mask: bool
    admitted: bool
    reward: float
    done: bool
    collector_value: float
    bootstrap: float
    cause: str | None
    work: Mapping = field(default_factory=dict)
    audit: Mapping = field(default_factory=dict)

    def __post_init__(self):
        for name in ("obs", "slots", "legal_mask", "work", "audit"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


def _uint(value, name, maximum=(1 << 64) - 1):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an unsigned integer <= {maximum}")


def _key(key):
    if not isinstance(key, DecisionKey):
        raise ValueError("invalid decision key")
    _uint(key.game_id, "game_id")
    _uint(key.seat, "seat", 1)
    _uint(key.request_epoch, "request_epoch")


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, np.ndarray):
        return {"dtype": value.dtype.str, "shape": list(value.shape),
                "base64": base64.b64encode(value.tobytes(order="C")).decode("ascii")}
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("metadata keys must be strings")
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return _plain(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("metadata must be finite JSON values")


def _canonical(value):
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def validate_manifest(manifest: DataManifest) -> None:
    if not isinstance(manifest, DataManifest):
        raise ValueError("invalid manifest type")
    if type(manifest.schema_version) is not int or manifest.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported expert schema {manifest.schema_version!r}")
    if type(manifest.key_version) is not int or manifest.key_version != KEY_VERSION:
        raise ValueError(f"unsupported key version {manifest.key_version!r}")
    for name in ("source_commit", "checkpoint_hash", "model_hash", "ids_hash", "pool_hash", "belief_hash"):
        value = getattr(manifest, name)
        size = 40 if name == "source_commit" else 64
        if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{size}}}", value):
            raise ValueError(f"invalid manifest {name}")
    for name in ("seed", "split_seed", "encoder", "capacity", "workers", "parallel_games", "game_count",
                 "rounds", "obs_width", "slot_width"):
        _uint(getattr(manifest, name), name)
    if manifest.encoder != 4 or manifest.obs_width != features.obs_size(4) or manifest.slot_width != features.SLOT_FEATURES:
        raise ValueError("manifest encoder/feature dimensions must match P1 encoder 4")
    if (manifest.device, manifest.capacity, manifest.parallel_games) != ("cpu", 1024, 512) or manifest.workers not in (4, 8, 14):
        raise ValueError("manifest must pin the P1 CPU capacity/workers/parallel games")
    if manifest.rounds < 1 or manifest.game_count != manifest.parallel_games * manifest.rounds:
        raise ValueError("manifest game_count must match complete rounds")
    for name in ("runtime", "compiler"):
        if not isinstance(getattr(manifest, name), str) or not getattr(manifest, name):
            raise ValueError(f"manifest {name} must be recorded")
    if not isinstance(manifest.teacher_config, Mapping):
        raise ValueError("manifest teacher configuration must be recorded")
    for name in ("k", "m", "worlds"):
        _uint(manifest.teacher_config.get(name), name)
    if dict(manifest.teacher_config) != {"k": 8, "m": 8, "worlds": 16, "lam": .5}:
        raise ValueError("manifest teacher configuration must be 8x8/16/0.5")
    for name in ("budget", "evaluation"):
        if not isinstance(getattr(manifest, name), Mapping) or not getattr(manifest, name):
            raise ValueError(f"manifest {name} must be recorded")
    _uint(manifest.budget.get("labels"), "labels")
    if manifest.budget.get("labels") != 16384:
        raise ValueError("manifest label cap must be 16384")
    _canonical(manifest)


def _array(value, dtype, shape, name):
    if not isinstance(value, np.ndarray) or value.dtype != np.dtype(dtype) or value.shape != shape:
        raise ValueError(f"{name} must be {dtype} with shape {shape}")
    if value.dtype.kind == "f" and not np.isfinite(value).all():
        raise ValueError(f"{name} must be finite")


def validate_row(row: ExpertRow, manifest: DataManifest) -> None:
    validate_manifest(manifest)
    if not isinstance(row, ExpertRow) or not isinstance(row.status, RowStatus):
        raise ValueError("invalid row/status")
    _key(row.key)
    _uint(row.logical_tick, "per-game logical tick")
    _array(row.obs, "<f4", (manifest.obs_width,), "obs")
    _array(row.slots, "<f4", (2, 32, manifest.slot_width), "slots")
    if row.boundary not in ("TURN", "REPLACEMENT", "PIVOT", "TEAM_SELECTION", "TERMINAL"):
        raise ValueError("unsupported row boundary")
    shape = (360,) if row.boundary == "TEAM_SELECTION" else (32,32)
    _array(row.legal_mask, "bool", shape, "legal_mask")
    for name in ("requested", "acting", "learner", "value_mask", "admitted", "done"):
        if type(getattr(row, name)) is not bool:
            raise ValueError(f"{name} must be bool")
    for name in ("reward", "collector_value", "bootstrap"):
        value = getattr(row, name)
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (float, int, np.floating, np.integer)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not row.learner:
        raise ValueError("only learner public-view rows belong in expert shards")
    if row.boundary == "TERMINAL" and row.requested:
        raise ValueError("terminal cannot request an action")
    if row.acting != row.requested or (row.value_mask and not row.learner):
        raise ValueError("invalid acting/learner/value masks")
    if row.status is RowStatus.UNREQUESTED:
        if row.requested or row.admitted or row.sparse_policy is not None or any(
                v is not None for v in (row.action, row.raw_action, row.behavior_logp)):
            raise ValueError("unrequested row cannot execute an action/target")
    else:
        if not row.requested:
            raise ValueError("requested status without request")
        for name in ("raw_action", "action"):
            action = getattr(row, name)
            _uint(action, name, row.legal_mask.size - 1)
            if not row.legal_mask.flat[action]:
                raise ValueError(f"illegal {name}")
        if row.behavior_logp is None or not math.isfinite(row.behavior_logp) or row.behavior_logp > 0:
            raise ValueError("invalid behavior likelihood")
    if row.status is RowStatus.TARGET:
        if row.boundary not in ("TURN", "REPLACEMENT", "PIVOT"):
            raise ValueError("preview/terminal cannot carry teacher labels")
        if not row.admitted or not row.learner or np.count_nonzero(row.legal_mask) < 2:
            raise ValueError("target requires admitted eligible learner")
        policy = row.sparse_policy
        if not isinstance(policy, SparsePolicy) or not isinstance(policy.ids, np.ndarray) or policy.ids.ndim != 1:
            raise ValueError("target requires sparse policy")
        k = len(policy.ids)
        if not 1 <= k <= 8:
            raise ValueError("invalid sparse candidate count")
        _array(policy.ids, "<i8", (k,), "sparse ids")
        _array(policy.probs, "<f8", (k,), "sparse probabilities")
        if len(np.unique(policy.ids)) != k or (policy.ids < 0).any() or (policy.ids >= 1024).any():
            raise ValueError("illegal/duplicate sparse ids")
        if not row.legal_mask.reshape(-1)[policy.ids].all() or (policy.probs < 0).any() or (policy.probs > 1).any():
            raise ValueError("illegal sparse mass")
        if abs(float(policy.probs.sum()) - 1.) > MASS_TOLERANCE:
            raise ValueError("sparse mass sum outside tolerance")
        if row.raw_action not in policy.ids:
            raise ValueError("target must include the pre-drawn student action")
        where = np.flatnonzero(policy.ids == row.action)
        if not len(where) or policy.probs[where[0]] <= 0 or abs(
                row.behavior_logp - math.log(float(policy.probs[where[0]]))) > MASS_TOLERANCE:
            raise ValueError("target behavior likelihood must be tau(action)")
        if row.cause is not None:
            raise ValueError("target cannot have a fallback cause")
    elif row.sparse_policy is not None:
        raise ValueError("non-target cannot carry a teacher policy")
    else:
        fallback = row.status in (RowStatus.PUBLIC_REFUSAL, RowStatus.WORK_EXHAUSTED)
        if row.admitted != fallback:
            raise ValueError("invalid non-target admission status")
        if row.status is not RowStatus.UNREQUESTED and row.action != row.raw_action:
            raise ValueError("non-target must execute the pre-drawn raw action")
        if fallback and (not isinstance(row.cause, str) or not row.cause):
            raise ValueError("fallback must name a cause")
        if not fallback and row.cause is not None:
            raise ValueError("unexpected fallback cause")
        if row.status is RowStatus.FORCED and (np.count_nonzero(row.legal_mask) != 1 or row.behavior_logp != 0.):
            raise ValueError("forced row must have one legal action and logp zero")
    if not isinstance(row.work, Mapping) or not isinstance(row.audit, Mapping):
        raise ValueError("work/audit provenance must be mappings")
    for name, count in row.work.items():
        _uint(count, f"work {name}")
    _canonical(row)


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def write_shard(path: Path, rows: Sequence[ExpertRow], manifest: DataManifest) -> str:
    path = Path(path)
    refuse_repository(path)
    validate_manifest(manifest)
    rows = tuple(rows)
    keys, ticks = set(), {}
    for row in rows:
        validate_row(row, manifest)
        identity = (row.key.game_id, row.key.seat, row.logical_tick)
        if identity in keys:
            raise ValueError("duplicate learner row tick in shard")
        stream = (row.key.game_id,row.key.seat)
        if stream in ticks and row.logical_tick <= ticks[stream]:
            raise ValueError("regressing learner row tick in shard")
        keys.add(identity)
        ticks[stream] = row.logical_tick
    payload = {"schema_version": SCHEMA_VERSION, "manifest": _plain(manifest),
               "manifest_sha256": _sha(manifest), "rows": [_plain(r) for r in rows]}
    data = _canonical({**payload, "content_sha256": _sha(payload)}) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental loss of private data. A partial
    # failed shard is not valid and cannot be resumed through read_shard.
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    fsync_dir(path.parent)
    return hashlib.sha256(data).hexdigest()


def _object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError(f"duplicate JSON key {k}")
        result[k] = v
    return result


def _restore_array(value):
    if not isinstance(value, dict) or set(value) != {"dtype", "shape", "base64"}:
        raise ValueError("invalid encoded array")
    dtype = np.dtype(value["dtype"])
    if dtype.str not in ("<f4", "<f8", "<i8", "|b1"):
        raise ValueError("unsupported array dtype")
    shape = value["shape"]
    if not isinstance(shape, list) or not shape or len(shape) > 3:
        raise ValueError("invalid array shape")
    for n in shape:
        _uint(n, "array dimension", 1_000_000)
    raw = base64.b64decode(value["base64"], validate=True)
    if math.prod(shape) * dtype.itemsize != len(raw):
        raise ValueError("array shape/byte size mismatch")
    return np.frombuffer(raw, dtype).reshape(shape)


def read_shard(path: Path, expected: DataManifest) -> tuple[ExpertRow, ...]:
    path = Path(path)
    refuse_repository(path)
    validate_manifest(expected)
    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON constant {value}")
    payload = json.loads(path.read_bytes(), object_pairs_hook=_object, parse_constant=invalid_constant)
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported expert shard schema")
    if set(payload) != {"schema_version", "manifest", "manifest_sha256", "rows", "content_sha256"}:
        raise ValueError("invalid shard fields")
    content = {k: v for k, v in payload.items() if k != "content_sha256"}
    if payload["content_sha256"] != _sha(content):
        raise ValueError("shard integrity mismatch")
    if payload["manifest_sha256"] != _sha(payload["manifest"]) or payload["manifest_sha256"] != _sha(expected):
        raise ValueError("incompatible shard manifest")
    if not isinstance(payload["rows"], list):
        raise ValueError("invalid shard rows")
    rows, keys, ticks = [], set(), {}
    for value in payload["rows"]:
        try:
            v = dict(value)
            v["key"] = DecisionKey(**v["key"])
            v["status"] = RowStatus(v["status"])
            for name in ("obs", "slots", "legal_mask"):
                v[name] = _restore_array(v[name])
            if v["sparse_policy"] is not None:
                policy = v["sparse_policy"]
                if set(policy) != {"ids", "probs"}:
                    raise ValueError("invalid sparse policy fields")
                v["sparse_policy"] = SparsePolicy(_restore_array(policy["ids"]), _restore_array(policy["probs"]))
            row = ExpertRow(**v)
        except (KeyError, TypeError) as err:
            raise ValueError("invalid shard row fields") from err
        validate_row(row, expected)
        identity = (row.key.game_id, row.key.seat, row.logical_tick)
        if identity in keys:
            raise ValueError("duplicate learner row tick in shard")
        stream = (row.key.game_id,row.key.seat)
        if stream in ticks and row.logical_tick <= ticks[stream]:
            raise ValueError("regressing learner row tick in shard")
        keys.add(identity)
        ticks[stream] = row.logical_tick
        rows.append(row)
    return tuple(rows)


KEY_DOMAINS = frozenset(("raw", "SELECT", "world", "X", "audit", "split"))


def selection_word(key: DecisionKey, seed: int, *, domain: str, version: int = 1) -> int:
    """Uniform uint64 word with version/domain separation; SELECT < 2**61 is 1/8."""
    _key(key)
    _uint(seed, "seed")
    if type(version) is not int or version != KEY_VERSION:
        raise ValueError(f"unsupported key version {version!r}")
    if not isinstance(domain, str) or domain not in KEY_DOMAINS:
        raise ValueError(f"unsupported key domain {domain!r}")
    tag = domain.encode("utf-8")
    data = (b"duoforge-expert" + struct.pack("<II", version, len(tag)) + tag
            + struct.pack("<QQQQ", seed, key.game_id, key.seat, key.request_epoch))
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "little")


LABEL_LIMIT = 16384


@dataclass
class LabelCursor:
    """Admission state for complete logical ticks; pending tickets precede tau.

    admit_tick mutates this object to reserve tickets. commit_tick returns a
    new cursor, leaving the pending checkpoint usable for deterministic resume.
    Only the caller that has assembled the COMPLETE tick may call admit_tick;
    grouping teacher execution does not permit incremental admission calls.
    """
    remaining: int = LABEL_LIMIT
    pending_reservations: tuple[DecisionKey, ...] | None = None
    cap_raw_keys: tuple[DecisionKey, ...] = ()
    dropped_games: frozenset[int] = frozenset()
    logical_tick: int = 0
    last_epochs: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.pending_reservations is not None:
            self.pending_reservations = tuple(self.pending_reservations)
        self.cap_raw_keys = tuple(self.cap_raw_keys)
        self.dropped_games = frozenset(self.dropped_games)
        self.last_epochs = MappingProxyType(dict(self.last_epochs))


@dataclass(frozen=True)
class AdmissionBatch:
    admitted_keys: tuple[DecisionKey, ...]
    cap_raw_keys: tuple[DecisionKey, ...]
    reserved_count: int


@dataclass(frozen=True)
class AdmissionOutcome:
    key: DecisionKey
    status: RowStatus


def _requests(requests):
    keys = tuple(requests)
    for k in keys:
        _key(k)
    if len(keys) > 512 or len({k.game_id for k in keys}) != len(keys):
        raise ValueError("tick needs unique learner game requests, at most 512")
    return tuple(sorted(keys))


def _validate_cursor(cursor):
    if not isinstance(cursor, LabelCursor):
        raise ValueError("invalid label cursor")
    _uint(cursor.remaining, "remaining labels", LABEL_LIMIT)
    _uint(cursor.logical_tick, "logical tick")
    for game in cursor.dropped_games:
        _uint(game, "dropped game")
    for game, epoch in cursor.last_epochs.items():
        _uint(game, "history game")
        _uint(epoch, "history epoch")
    if cursor.pending_reservations is None:
        if cursor.cap_raw_keys:
            raise ValueError("cap-raw keys without pending tick")
        return
    pending = cursor.pending_reservations
    raw = cursor.cap_raw_keys
    _requests(pending + raw)
    if pending != tuple(sorted(pending)) or raw != tuple(sorted(raw)):
        raise ValueError("pending admission keys must be canonical")
    if cursor.remaining + len(pending) > LABEL_LIMIT:
        raise ValueError("reserved labels exceed capacity")
    if any(k.game_id in cursor.dropped_games for k in pending) or any(
            k.game_id not in cursor.dropped_games for k in raw):
        raise ValueError("invalid dropped-game admission state")
    for k in pending + raw:
        if k.game_id in cursor.last_epochs and k.request_epoch <= cursor.last_epochs[k.game_id]:
            raise ValueError("pending request repeats/regresses an epoch")


def admit_tick(cursor: LabelCursor, requests: Sequence[DecisionKey]) -> AdmissionBatch:
    _validate_cursor(cursor)
    if cursor.pending_reservations is not None:
        raise ValueError("pending tick must commit before another admission")
    keys = _requests(requests)
    for k in keys:
        if k.game_id in cursor.last_epochs and k.request_epoch <= cursor.last_epochs[k.game_id]:
            raise ValueError("request repeats/regresses an epoch")
    remaining = cursor.remaining
    dropped = set(cursor.dropped_games)
    admitted, raw = [], []
    for key in keys:
        if key.game_id in dropped or not remaining:
            dropped.add(key.game_id)
            raw.append(key)
        else:
            admitted.append(key)
            remaining -= 1
    # Validation above completes before any caller-visible state changes.
    cursor.remaining = remaining
    cursor.pending_reservations = tuple(admitted)
    cursor.cap_raw_keys = tuple(raw)
    cursor.dropped_games = frozenset(dropped)
    return AdmissionBatch(tuple(admitted), tuple(raw), len(admitted))


def commit_tick(cursor: LabelCursor, outcomes: Sequence[AdmissionOutcome]) -> LabelCursor:
    _validate_cursor(cursor)
    if cursor.pending_reservations is None:
        raise ValueError("no pending admission tick")
    results = {}
    for outcome in outcomes:
        if not isinstance(outcome, AdmissionOutcome) or not isinstance(outcome.status, RowStatus):
            raise ValueError("invalid admission outcome")
        _key(outcome.key)
        if outcome.key in results:
            raise ValueError("duplicate admission outcome")
        results[outcome.key] = outcome.status
    admitted, raw = cursor.pending_reservations, cursor.cap_raw_keys
    if set(results) != set(admitted + raw):
        raise ValueError("all pending tick outcomes must commit together")
    released = 0
    for k in admitted:
        if results[k] not in (RowStatus.TARGET, RowStatus.PUBLIC_REFUSAL, RowStatus.WORK_EXHAUSTED):
            raise ValueError("admitted root needs target or named refusal/exhaustion")
        released += results[k] is not RowStatus.TARGET
    if any(results[k] is not RowStatus.CAP_RAW for k in raw):
        raise ValueError("cap-raw game cannot play tau or acquire a target")
    history = dict(cursor.last_epochs)
    history.update({k.game_id: k.request_epoch for k in admitted + raw})
    result = LabelCursor(remaining=cursor.remaining + released, dropped_games=cursor.dropped_games,
                         logical_tick=cursor.logical_tick + 1, last_epochs=history)
    _validate_cursor(result)
    return result


def cursor_bytes(cursor: LabelCursor, manifest: DataManifest) -> bytes:
    """Canonical in-memory checkpoint, bound to the complete immutable manifest."""
    validate_manifest(manifest)
    _validate_cursor(cursor)
    state = {"remaining": cursor.remaining, "pending_reservations": cursor.pending_reservations,
             "cap_raw_keys": cursor.cap_raw_keys, "dropped_games": sorted(cursor.dropped_games),
             "logical_tick": cursor.logical_tick, "last_epochs": sorted(cursor.last_epochs.items())}
    content = {"schema_version": SCHEMA_VERSION, "manifest_sha256": _sha(manifest), "cursor": state}
    return _canonical({**content, "content_sha256": _sha(content)})


def restore_cursor(data: bytes, manifest: DataManifest) -> LabelCursor:
    validate_manifest(manifest)
    state = json.loads(data, object_pairs_hook=_object)
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported cursor schema")
    if set(state) != {"schema_version", "manifest_sha256", "cursor", "content_sha256"}:
        raise ValueError("invalid cursor fields")
    content = {k: v for k, v in state.items() if k != "content_sha256"}
    if state["content_sha256"] != _sha(content):
        raise ValueError("cursor integrity mismatch")
    if state["manifest_sha256"] != _sha(manifest):
        raise ValueError("incompatible cursor manifest")
    try:
        v = dict(state["cursor"])
        if set(v) != {"remaining", "pending_reservations", "cap_raw_keys", "dropped_games", "logical_tick", "last_epochs"}:
            raise ValueError("invalid cursor state fields")
        if v["pending_reservations"] is not None:
            v["pending_reservations"] = tuple(DecisionKey(**k) for k in v["pending_reservations"])
        v["cap_raw_keys"] = tuple(DecisionKey(**k) for k in v["cap_raw_keys"])
        for name in ("dropped_games", "last_epochs"):
            if not isinstance(v[name], list):
                raise ValueError(f"invalid cursor {name}")
        if len(set(v["dropped_games"])) != len(v["dropped_games"]):
            raise ValueError("duplicate dropped game")
        history = dict(v["last_epochs"])
        if len(history) != len(v["last_epochs"]):
            raise ValueError("duplicate history game")
        v["last_epochs"] = history
        cursor = LabelCursor(**v)
    except (TypeError, KeyError) as err:
        raise ValueError("invalid cursor state") from err
    _validate_cursor(cursor)
    return cursor
