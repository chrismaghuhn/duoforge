"""Replay games from local files, in file and row order (M11 spec section 3).

Parquet files (the HolidayOugi dataset: columns id, formatid, log) need
pyarrow, imported only here; JSON lines files ({"id", "formatid", "log"} per
line) serve tests and small samples. select() keeps the open-sheet games of
the format and counts the rest.
"""
import collections
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import funnel, split

MODES = ("sheet", "bo1_belief", "drop_sheets")  # the open-sheet games; the games without sheets; test-split sheet
# games with their sheets dropped (the Bo1 belief validation, M11 Bo1 spec section 6)

FORMAT_PREFIX = "gen9championsvgc2026regmc"


def files(paths):
    """The source files of paths (files, or directories: their *.parquet and *.jsonl), sorted by name."""
    out = []
    for path in map(Path, paths):
        if path.is_dir():
            out += sorted(p for p in path.iterdir() if p.suffix in (".parquet", ".jsonl"))
        elif path.suffix in (".parquet", ".jsonl"):
            out.append(path)
        else:
            raise ValueError(f"{path}: not a .parquet or .jsonl file or a directory")
    return out


def games(paths, format_prefix="", counters=None):
    """(id, formatid, log) of every game of the files, in file and row order: read_unit over units()."""
    counters = counters if counters is not None else {}
    for unit in units(paths):
        yield from read_unit(unit, format_prefix, counters)


@dataclass(frozen=True)
class Unit:
    """A fixed piece of the source: a parquet row group, or a block of unit_lines lines of a JSON lines file. A unit
    is one part of the dataset (build.py): which games it holds depends on the source files only."""
    id: str  # "<file stem as letters and digits>-<index>", unique per source set
    path: str
    index: int  # the row group, or the block
    unit_lines: int


def _stem(path):
    return re.sub(r"[^a-z0-9]", "", Path(path).stem.lower()) or "source"


def units(paths, unit_lines=4096):
    """The units of the source files, in file order then index order."""
    out = []
    for path in files(paths):
        if path.suffix == ".jsonl":
            with open(path, encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
            blocks = (count + unit_lines - 1) // unit_lines
        else:
            parquet = _parquet().ParquetFile(path)
            blocks = parquet.metadata.num_row_groups
        out += [Unit(f"{_stem(path)}-{i:05d}", str(path), i, unit_lines) for i in range(blocks)]
    ids = [u.id for u in out]
    if len(set(ids)) != len(ids):
        raise ValueError("two source files have the same name in letters and digits: their parts would collide")
    return out


def read_unit(unit, format_prefix, counters):
    """(id, formatid, log) of the games of one unit, in source order. A parquet row group without the format is
    skipped unread; its rows count as read and skipped (skip:format)."""
    path = Path(unit.path)
    if path.suffix == ".jsonl":
        start, stop = unit.index * unit.unit_lines, (unit.index + 1) * unit.unit_lines
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(line for line in f if line.strip()):
                if n >= stop:
                    break
                if n >= start:
                    row = json.loads(line)
                    yield row["id"], row["formatid"], row["log"]
        return
    parquet = _parquet().ParquetFile(path)
    formats = parquet.read_row_group(unit.index, columns=["formatid"]).column(0).to_pylist()
    if not any(f.startswith(format_prefix) for f in formats):
        counters["games.read"] = counters.get("games.read", 0) + len(formats)
        counters["games.skipped.skip:format"] = counters.get("games.skipped.skip:format", 0) + len(formats)
        for format_id, n in collections.Counter(formats).items():
            funnel.count(counters, format_id, "read", n)
            funnel.count(counters, format_id, "skipped.skip:format", n)
        return
    table = parquet.read_row_group(unit.index, columns=["id", "formatid", "log"])
    yield from zip(*(table.column(c).to_pylist() for c in ("id", "formatid", "log")))


def _parquet():
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise RuntimeError("reading parquet needs pyarrow (pip install pyarrow)") from e
    return pq


def select(rows, format_prefix, counters, mode="sheet", split_of=None):
    """(id, format id, log, dropped sheet hashes) of the games a build of `mode` takes; the others counted under
    games.skipped.<reason> and their funnel stage. sheet: exactly two |showteam| lines (skip:sheets). bo1_belief: none
    (skip:has-sheets). drop_sheets: exactly two, yielded without them and with their hashes. split_of ("train",
    "test" or None): only games of that player split (skip:split-<the other>; skip:split-players without both
    |player| lines)."""
    from .game import _hash8
    for replay_id, format_id, log in rows:
        counters["games.read"] += 1
        funnel.count(counters, format_id, "read")
        shown = log.count("\n|showteam|") + log.startswith("|showteam|")
        reason = None
        if not format_id.startswith(format_prefix):
            reason = "skip:format"
        elif mode == "bo1_belief" and shown:
            reason = "skip:has-sheets"
        elif mode != "bo1_belief" and shown != 2:
            reason = "skip:sheets"
        elif split_of is not None:
            try:
                got = split.of_game(split.players_of(log.split("\n")))
            except ValueError:
                got = "players"
            if got != split_of:
                reason = f"skip:split-{got}"
        if reason is not None:
            counters[f"games.skipped.{reason}"] += 1
            funnel.count(counters, format_id, f"skipped.{reason}")
            continue
        dropped = ()
        if mode == "drop_sheets":
            lines = log.split("\n")
            dropped = tuple(_hash8(line.split("|", 3)[3]) for line in lines if line.startswith("|showteam|"))
            log = "\n".join(line for line in lines if not line.startswith("|showteam|"))
        yield replay_id, format_id, log, dropped
