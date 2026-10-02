"""Builds a replay dataset in parts that a run can resume (M11 spec section 12; the owner's VM rules, 2026-10-02).

A part is one unit of the source (source.Unit: a parquet row group, or a block
of lines of a JSON lines file), so which games a part holds depends on the
source files only, never on the worker count. Each part is written to
part-<unit>.tmp/ and renamed to part-<unit>/ once complete: a part directory is
finished by definition. A run started again on the same output skips the
finished parts, removes the half-written .tmp ones and writes the rest; the
inputs (sources, prior, filters, unit size, code commit) must be the ones the
output was started with (replay-dataset.json), otherwise it refuses.

Per part: shards, games.npz, counters.json and manifest.json (dataset.Writer).
On stdout one line per finished part (games, rows, seconds, games per second
so far), for a first throughput reading. At the end the output's own
counters.json (the sum over all parts) and manifest.json (provenance, parts,
counters, the run's timing). Between parts the build waits while the fuzz
pause file exists. A game that raises anything but Skip is internal:<type>,
with up to ten replay ids; the command exits 1 then.
"""
import collections
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from duoforge_live import data as live_data

from . import dataset, game, source
from .prior import Prior

DATA_KIND_POOL = 6  # DUOFORGE_DATA_KIND_POOL (include/duoforge/duoforge.h)
MARKER = "replay-dataset.json"
_STATE = {}


def pause_file():
    return os.environ.get("DUOFORGE_FUZZ_PAUSE") or os.path.join(tempfile.gettempdir(), "duoforge-fuzz.pause")


def _init(prior_path, stats_factory, node, ps_dir, format_prefix, out_dir, part_manifest):
    from .stats import StatSource
    _STATE["data"] = live_data.load(kind="pool")
    _STATE["prior"] = Prior.load(prior_path)
    _STATE["stats"] = stats_factory() if stats_factory is not None else StatSource(node, ps_dir)
    _STATE["format_prefix"] = format_prefix
    _STATE["out"] = Path(out_dir)
    _STATE["manifest"] = part_manifest


def _work_unit(unit):
    """Writes one part; returns (unit id, counters, internal examples, seconds)."""
    start = time.monotonic()
    counters = collections.Counter()
    examples = []
    tmp = _STATE["out"] / f"part-{unit.id}.tmp"
    writer = dataset.Writer(tmp, {**_STATE["manifest"], "unit": unit.id, "source": Path(unit.path).name})
    rows = source.select(source.read_unit(unit, _STATE["format_prefix"], counters), _STATE["format_prefix"], counters)
    for replay_id, format_id, log in rows:
        try:
            result = game.process(replay_id, format_id, log, _STATE["data"], _STATE["prior"], _STATE["stats"])
        except game.Skip as e:
            counters[f"games.skipped.{e.reason}"] += 1
            continue
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # noqa: BLE001 - a bug (a SystemExit too): counted and reported, the run goes on
            key = f"internal:{type(e).__name__}"
            counters[key] += 1
            if len(examples) < 10:
                examples.append(f"{replay_id}: {type(e).__name__}: {str(e)[:120]}")
            continue
        counters["games.processed"] += 1
        writer.add(result)
    writer.counters.update(counters)
    total = writer.close()
    os.replace(tmp, _STATE["out"] / f"part-{unit.id}")
    return unit.id, total, examples, time.monotonic() - start


def _git(cwd, *args):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def inputs(paths, prior_path, format_prefix, unit_lines):
    """What a dataset's parts depend on: a resumed run must have the same."""
    return {
        "code": {"commit": _git(live_data.ROOT, "rev-parse", "HEAD"),
                 "dirty": bool(_git(live_data.ROOT, "status", "--porcelain", "--untracked-files=no"))},
        "sources": [{"file": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in source.files(paths)],
        "prior_sha256": _sha256(prior_path),
        "filters": {"format_prefix": format_prefix, "open_sheets": 2},
        "unit_lines": unit_lines,
    }


def provenance(ps_dir):
    import duoforge
    from duoforge import _lib
    tables = live_data.load(kind="pool").tables
    names = {t: [k for k, _ in sorted(((k, v) for k, v in tables[t].items() if k != "COUNT"), key=lambda kv: kv[1])]
             for t in ("FORME", "MOVE", "ITEM", "ABILITY", "NATURE")}
    with duoforge.Context(data_kind=DATA_KIND_POOL) as context:
        fingerprint = context.fingerprint().hex()
    return {"library_version": _lib.EXPECTED_VERSION, "data_kind": "POOL", "fingerprint": fingerprint,
            "names": names, "showdown": _git(ps_dir, "rev-parse", "HEAD") if ps_dir else None}


def _prepare(out, wanted):
    """Creates the output or checks that it is this dataset; removes half-written parts; returns the finished ones."""
    dataset.refuse_repository(out)
    marker = out / MARKER
    if out.exists() and any(out.iterdir()):
        if not marker.exists():
            raise ValueError(f"the output {out} is not a replay dataset: an empty directory or a started one")
        if json.loads(marker.read_text(encoding="utf-8")) != wanted:
            raise ValueError(f"the output {out} was started with other inputs ({MARKER}): use a new directory")
    else:
        out.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(wanted, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for tmp in out.glob("part-*.tmp"):
        shutil.rmtree(tmp)
    return {p.name[len("part-"):] for p in out.glob("part-*") if p.is_dir()}


def build(paths, prior_path, out_dir, workers=1, limit_parts=None, format_prefix=source.FORMAT_PREFIX,
          unit_lines=4096, stats_factory=None, node="node", ps_dir=None, log=None):
    """Builds or resumes the dataset; returns the counters of the whole output (parts.written, parts.skipped.done
    for this run; internal:<type> for bugs, with examples under internal.examples)."""
    log = log or (lambda text: print(text, flush=True))
    ps_dir = ps_dir or os.environ.get("DUOFORGE_PS_REFERENCE_DIR")
    paths = [Path(p) for p in paths]
    out = Path(out_dir)
    wanted = inputs(paths, prior_path, format_prefix, unit_lines)
    done = _prepare(out, wanted)
    units = source.units(paths, unit_lines)
    todo = [u for u in units if u.id not in done]
    if limit_parts is not None:
        todo = todo[:limit_parts]
    part_manifest = {"inputs": wanted, **provenance(ps_dir)}
    initargs = (prior_path, stats_factory, node, ps_dir, format_prefix, out, part_manifest)
    run = collections.Counter({"parts.skipped.done": sum(1 for u in units if u.id in done)})
    examples = []
    start = time.monotonic()
    games_now = 0

    def dispatch():
        for unit in todo:
            while os.path.exists(pause_file()):
                time.sleep(5)
            yield unit

    def take(result):
        nonlocal games_now
        unit_id, counters, unit_examples, seconds = result
        run["parts.written"] += 1
        examples.extend(unit_examples)
        games_now += counters.get("games.processed", 0)
        elapsed = max(time.monotonic() - start, 1e-9)
        log(f"part {unit_id}: {counters.get('games.processed', 0)} games, {counters.get('points.written', 0)} rows, "
            f"{seconds:.1f} s; {run['parts.written']}/{len(todo)} parts this run, {games_now / elapsed:.1f} games/s")

    if workers == 1:
        _init(*initargs)
        for unit in dispatch():
            take(_work_unit(unit))
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(workers, initializer=_init, initargs=initargs) as pool:
            for result in pool.imap_unordered(_work_unit, dispatch()):
                take(result)
    seconds = time.monotonic() - start
    total = collections.Counter()
    parts = []
    for part in (p for p in dataset.parts(out) if p != out):
        manifest = json.loads((part / "manifest.json").read_text(encoding="utf-8"))
        total.update(manifest["counters"])
        parts.append({"part": part.name, "rows": sum(s["rows"] for s in manifest["shards"]),
                      "games": manifest["games"]})
    counters = dict(sorted(total.items()))
    (out / "counters.json").write_text(json.dumps(counters, indent=1) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "format_version": dataset.FORMAT_VERSION, "layout": "parts", "inputs": wanted, **provenance(ps_dir),
        "parts": parts, "counters": counters,
        "run": {"workers": workers, "parts_written": run["parts.written"], "seconds": round(seconds, 1),
                "games_per_second": round(games_now / max(seconds, 1e-9), 1)},
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total.update(run)
    total["internal.examples"] = examples
    if examples:
        print(f"internal errors (bugs): {len(examples)} examples", file=sys.stderr)
    return total
