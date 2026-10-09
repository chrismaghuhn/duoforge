"""The private tail calibration's fixture set (P1 plan C2 step 6).

The five exact-rescue records of the honest arena (#236) are kept privately,
outside the repository. A manifest names each payload file next to it and its
SHA-256; load_rescue_fixture_set requires exactly five, revalidates every
fingerprint and the arrays the bounded/unbounded replay needs. Anything
missing, extra, altered or malformed is a CalibrationStop: calibration stops
and is re-planned, never replaced by regenerated data. No battle rules here.

Manifest: {"schema": "duoforge-rescue-fixtures-1", "fixtures": [{"file":
"<plain name beside the manifest>", "sha256": "<of the file bytes>"}, ...]}.
Payload: a JSON object with at least key (uint64), exact (true), tables
(W, K, M), weights (W,) and foe_probs (W, M), as the honest search records
them.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
from duoforge_replay.dataset import refuse_repository

from .errors import SearchError

SCHEMA = "duoforge-rescue-fixtures-1"
FIXTURE_COUNT = 5
PROBABILITY_TOLERANCE = 1e-6


class CalibrationStop(SearchError):
    """The calibration's fixtures are missing or invalid: STOP and re-plan."""


@dataclass(frozen=True)
class RescueFixture:
    key: int
    tables: np.ndarray  # (W, K, M) float64, read-only
    weights: np.ndarray  # (W,) positive float64, read-only
    foe_probs: np.ndarray  # (W, M) float64, read-only
    sha256: str


def _numbers(value):
    if isinstance(value, list):
        return all(_numbers(v) for v in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _array(value, name, ndim):
    # Only JSON numbers: strings, booleans, ragged lists and integers beyond
    # int64 (object arrays) stop instead of being converted.
    if not _numbers(value):
        raise CalibrationStop(f"rescue fixture {name} must hold only numbers")
    try:
        raw = np.array(value)
    except (TypeError, ValueError) as err:
        raise CalibrationStop(f"rescue fixture {name} is not a numeric array") from err
    if raw.dtype.kind not in "iuf":
        raise CalibrationStop(f"rescue fixture {name} must hold only numbers (got {raw.dtype})")
    a = raw.astype(np.float64)
    if a.ndim != ndim or 0 in a.shape or not np.isfinite(a).all():
        raise CalibrationStop(f"rescue fixture {name} must be a finite {ndim}-d array (got shape {a.shape})")
    a.setflags(write=False)
    return a


def _fixture(data, sha):
    def invalid_constant(value):
        raise CalibrationStop(f"rescue fixture has a nonfinite JSON constant {value}")

    try:
        payload = json.loads(data, parse_constant=invalid_constant)
    except ValueError as err:
        raise CalibrationStop("rescue fixture is not JSON") from err
    if not isinstance(payload, dict) or not {"key", "tables", "weights", "foe_probs", "exact"} <= set(payload):
        raise CalibrationStop("rescue fixture needs key, tables, weights, foe_probs and exact")
    if payload["exact"] is not True:
        raise CalibrationStop("rescue fixture is not an exact-rescue record")
    key = payload["key"]
    if isinstance(key, bool) or not isinstance(key, int) or not 0 <= key < 1 << 64:
        raise CalibrationStop(f"rescue fixture key must be a uint64 (got {key!r})")
    tables = _array(payload["tables"], "tables", 3)
    weights = _array(payload["weights"], "weights", 1)
    foe_probs = _array(payload["foe_probs"], "foe_probs", 2)
    nw, _, m = tables.shape
    if weights.shape != (nw,) or (weights <= 0).any():
        raise CalibrationStop(f"rescue fixture weights must be {nw} positive numbers")
    if foe_probs.shape != (nw, m) or (foe_probs < 0).any():
        raise CalibrationStop(f"rescue fixture foe_probs must be ({nw}, {m}) nonnegative numbers")
    # Each world's top-M foe probabilities cover part of its policy: mass in (0, 1].
    coverage = foe_probs.sum(axis=1)
    if not ((coverage > 0) & (coverage <= 1 + PROBABILITY_TOLERANCE)).all():
        raise CalibrationStop("rescue fixture foe_probs rows must carry mass in (0, 1]")
    return RescueFixture(key, tables, weights, foe_probs, sha)


def load_rescue_fixture_set(manifest: Path) -> tuple[RescueFixture, ...]:
    """The five private rescue fixtures in manifest order; CalibrationStop otherwise."""
    manifest = Path(manifest)
    try:
        refuse_repository(manifest)
    except ValueError as err:
        raise CalibrationStop(f"rescue fixtures stay private: {err}") from err
    try:
        index = json.loads(manifest.read_text(encoding="ascii"))
    except (OSError, ValueError) as err:
        raise CalibrationStop(f"rescue fixture manifest {manifest} is missing or unreadable") from err
    if not isinstance(index, dict) or set(index) != {"schema", "fixtures"} or index["schema"] != SCHEMA:
        raise CalibrationStop(f"rescue fixture manifest must be {SCHEMA}")
    entries = index["fixtures"]
    if not isinstance(entries, list) or len(entries) != FIXTURE_COUNT:
        raise CalibrationStop(f"the calibration needs exactly {FIXTURE_COUNT} rescue fixtures")
    fixtures = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"file", "sha256"}:
            raise CalibrationStop("each rescue fixture entry needs file and sha256")
        name, sha = entry["file"], entry["sha256"]
        if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
            raise CalibrationStop(f"rescue fixture file must be a plain name beside the manifest (got {name!r})")
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise CalibrationStop("rescue fixture sha256 must be 64 lowercase hex digits")
        try:
            data = (manifest.parent / name).read_bytes()
        except OSError as err:
            raise CalibrationStop(f"rescue fixture {name} is missing") from err
        if hashlib.sha256(data).hexdigest() != sha:
            raise CalibrationStop(f"rescue fixture {name} does not match its fingerprint")
        fixtures.append(_fixture(data, sha))
    if len({f.sha256 for f in fixtures}) != FIXTURE_COUNT or len({e["file"] for e in entries}) != FIXTURE_COUNT:
        raise CalibrationStop("rescue fixtures must be five distinct records")
    return tuple(fixtures)
