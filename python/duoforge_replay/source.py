"""Replay games from local files, in file and row order (M11 spec section 3).

Parquet files (the HolidayOugi dataset: columns id, formatid, log) need
pyarrow, imported only here; JSON lines files ({"id", "formatid", "log"} per
line) serve tests and small samples. select() keeps the open-sheet games of
the format and counts the rest.
"""
import json
from pathlib import Path

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


def games(paths, format_prefix=""):
    """(id, formatid, log) of every game of the files, in file and row order. A parquet row group without a
    formatid starting with format_prefix is skipped unread (its rows are not yielded)."""
    for path in files(paths):
        if path.suffix == ".jsonl":
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        yield row["id"], row["formatid"], row["log"]
            continue
        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise RuntimeError("reading parquet needs pyarrow (pip install pyarrow)") from e
        parquet = pq.ParquetFile(path)
        for group in range(parquet.metadata.num_row_groups):
            formats = parquet.read_row_group(group, columns=["formatid"]).column(0).to_pylist()
            if not any(f.startswith(format_prefix) for f in formats):
                continue
            table = parquet.read_row_group(group, columns=["id", "formatid", "log"])
            yield from zip(*(table.column(c).to_pylist() for c in ("id", "formatid", "log")))


def select(rows, format_prefix, counters):
    """The rows of the format with exactly two |showteam| lines; the others counted under games.skipped.<reason>."""
    for replay_id, format_id, log in rows:
        counters["games.read"] += 1
        if not format_id.startswith(format_prefix):
            counters["games.skipped.skip:format"] += 1
        elif log.count("\n|showteam|") + log.startswith("|showteam|") != 2:
            counters["games.skipped.skip:sheets"] += 1
        else:
            yield replay_id, format_id, log
