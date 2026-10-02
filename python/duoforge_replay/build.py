"""Builds a replay dataset (M11 spec section 12): source games -> game.process in workers -> dataset.Writer.

Workers take chunks of games and return their results; the writer takes
them in source order, so the output does not depend on the worker count.
Between chunks the build waits while the fuzz pause file exists
($DUOFORGE_FUZZ_PAUSE, else duoforge-fuzz.pause in the temporary directory),
the machine's signal for a quiet measurement. A game that raises anything
but Skip is counted as internal:<type> with up to ten replay ids, and the
command exits 1 at the end.
"""
import collections
import hashlib
import itertools
import multiprocessing
import os
import subprocess
import tempfile
import time
from pathlib import Path

from duoforge_live import data as live_data

from . import dataset, game, source
from .prior import Prior

DATA_KIND_POOL = 6  # DUOFORGE_DATA_KIND_POOL (include/duoforge/duoforge.h)
_STATE = {}


def pause_file():
    return os.environ.get("DUOFORGE_FUZZ_PAUSE") or os.path.join(tempfile.gettempdir(), "duoforge-fuzz.pause")


def _init(prior_path, stats_factory, node, ps_dir):
    from .stats import StatSource
    _STATE["data"] = live_data.load(kind="pool")
    _STATE["prior"] = Prior.load(prior_path)
    _STATE["stats"] = stats_factory() if stats_factory is not None else StatSource(node, ps_dir)


def _work(chunk):
    out = []
    for replay_id, format_id, log in chunk:
        try:
            out.append(("ok", game.process(replay_id, format_id, log, _STATE["data"], _STATE["prior"],
                                           _STATE["stats"])))
        except game.Skip as e:
            out.append(("skip", e.reason, replay_id))
        except Exception as e:  # noqa: BLE001 - a bug: counted and reported, the run goes on
            out.append(("internal", f"{type(e).__name__}: {str(e)[:120]}", replay_id))
    return out


def _chunks(rows, size):
    rows = iter(rows)
    while True:
        chunk = list(itertools.islice(rows, size))
        if not chunk:
            return
        while os.path.exists(pause_file()):
            time.sleep(5)
        yield chunk


def _git(cwd, *args):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest(paths, prior_path, format_prefix, ps_dir, workers, limit_games):
    """The provenance of a build (no timestamps: equal inputs and code give an equal manifest)."""
    import duoforge
    from duoforge import _lib
    tables = live_data.load(kind="pool").tables
    names = {t: [k for k, _ in sorted(((k, v) for k, v in tables[t].items() if k != "COUNT"), key=lambda kv: kv[1])]
             for t in ("FORME", "MOVE", "ITEM", "ABILITY", "NATURE")}
    with duoforge.Context(data_kind=DATA_KIND_POOL) as context:
        fingerprint = context.fingerprint().hex()
    return {
        "code": {"commit": _git(live_data.ROOT, "rev-parse", "HEAD"),
                 "dirty": bool(_git(live_data.ROOT, "status", "--porcelain", "--untracked-files=no"))},
        "library_version": _lib.EXPECTED_VERSION,
        "data_kind": "POOL", "fingerprint": fingerprint, "names": names,
        "sources": [{"file": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in source.files(paths)],
        "filters": {"format_prefix": format_prefix, "open_sheets": 2},
        "prior_sha256": _sha256(prior_path),
        "showdown": _git(ps_dir, "rev-parse", "HEAD") if ps_dir else None,
        "build": {"workers": workers, "limit_games": limit_games},
    }


def build(paths, prior_path, out_dir, workers=1, limit_games=None, format_prefix=source.FORMAT_PREFIX, chunk=64,
          stats_factory=None, node="node", ps_dir=None):
    """Builds the dataset; returns the counters (internal:<type> counts bugs; examples under internal.examples)."""
    ps_dir = ps_dir or os.environ.get("DUOFORGE_PS_REFERENCE_DIR")
    paths = [Path(p) for p in paths]
    writer = dataset.Writer(out_dir, manifest(paths, prior_path, format_prefix, ps_dir, workers, limit_games))
    counters = collections.Counter()
    rows = source.select(source.games(paths, format_prefix), format_prefix, counters)
    if limit_games is not None:
        rows = itertools.islice(rows, limit_games)
    examples = collections.defaultdict(list)

    def take(results):
        for kind, *rest in results:
            if kind == "ok":
                counters["games.processed"] += 1
                writer.add(rest[0])
            elif kind == "skip":
                counters[f"games.skipped.{rest[0]}"] += 1
            else:
                key = f"internal:{rest[0].split(':')[0]}"
                counters[key] += 1
                if len(examples[key]) < 10:
                    examples[key].append(f"{rest[1]}: {rest[0]}")

    if workers == 1:
        _init(prior_path, stats_factory, node, ps_dir)
        for c in _chunks(rows, chunk):
            take(_work(c))
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(workers, initializer=_init, initargs=(prior_path, stats_factory, node, ps_dir)) as pool:
            for results in pool.imap(_work, _chunks(rows, chunk)):
                take(results)
    writer.counters.update(counters)
    total = writer.close()
    total["internal.examples"] = dict(examples)
    return total
