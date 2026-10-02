"""The replay dataset on disk (M11 spec section 11): shards of rows, a games table, a manifest, counters.

    rows-00000.npz ...  observation (OBSERVATION), domain (FACTORED_DOMAIN), game (u32), side (u8),
                        point (u16), label_slots (u32 x2), label_team (u8 x45), label_reason (u8 x2),
                        prior_level (u8 x6)
    games.npz           replay_id, format_id, bo3_game, ratings (i32 x2), winner (i8), turns, players and
                        sheets (u64 x2)
    manifest.json       provenance, the shards with rows and SHA-256, the counters
    counters.json       the counters

Writer refuses a directory inside the repository: replays and anything
derived from them never go there. Files are written with fixed zip
timestamps, so the same games and code give byte-identical files.
"""
import collections
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np

from duoforge import _layout
from duoforge_live.data import ROOT

from .labels import TEAM_BYTES

FORMAT_VERSION = 1
_DATE = (1980, 1, 1, 0, 0, 0)


def _common_dir(path):
    """The git common directory of the work tree that holds path (its nearest existing ancestor), or None."""
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    out = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True)
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 else None


def refuse_repository(path):
    """ValueError when path lies in any work tree of this repository (the checkout of this code, its main
    checkout, any worktree): replay data never goes there."""
    path = Path(path).resolve()
    root = ROOT.resolve()
    ours = _common_dir(root)
    if path == root or root in path.parents or (ours is not None and _common_dir(path) == ours):
        raise ValueError(f"the output {path} is inside the repository: replay data never goes there")


def write_npz(path, arrays):
    """An .npz with fixed timestamps and a fixed member order (byte-identical for equal arrays)."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(arrays):
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer, np.ascontiguousarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, buffer.getvalue())


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Writer:
    def __init__(self, out_dir, manifest, shard_rows=65536):
        refuse_repository(out_dir)
        self.out = Path(out_dir)
        if self.out.exists() and any(self.out.iterdir()):
            raise ValueError(f"the output {out_dir} is not empty: old shards would mix with new ones")
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest = dict(manifest)
        self.shard_rows = shard_rows
        self.rows = []
        self.games = []
        self.shards = []
        self.counters = collections.Counter()

    def add(self, result):
        """One game's rows and counters (game.GameResult)."""
        index = len(self.games)
        self.games.append(result.record)
        self.counters.update(result.counters)
        self.counters["games.written"] += 1
        for row in result.rows:
            self.rows.append((index, row))
            if len(self.rows) == self.shard_rows:
                self._flush()

    def _flush(self):
        if not self.rows:
            return
        n = len(self.rows)
        arrays = {
            "observation": np.zeros(n, dtype=_layout.OBSERVATION),
            "domain": np.zeros(n, dtype=_layout.FACTORED_DOMAIN),
            "game": np.zeros(n, dtype=np.uint32), "side": np.zeros(n, dtype=np.uint8),
            "point": np.zeros(n, dtype=np.uint16), "label_slots": np.zeros((n, 2), dtype=np.uint32),
            "label_team": np.zeros((n, TEAM_BYTES), dtype=np.uint8), "label_reason": np.zeros((n, 2), dtype=np.uint8),
            "prior_level": np.zeros((n, 6), dtype=np.uint8),
        }
        for i, (game, row) in enumerate(self.rows):
            arrays["observation"][i] = row.observation
            arrays["domain"][i] = row.domain
            arrays["game"][i], arrays["side"][i], arrays["point"][i] = game, row.side, row.point
            arrays["label_slots"][i] = row.label.slots
            arrays["label_team"][i] = np.frombuffer(row.label.team, dtype=np.uint8)
            arrays["label_reason"][i] = row.label.reasons
            arrays["prior_level"][i] = row.prior_level
        name = f"rows-{len(self.shards):05d}.npz"
        write_npz(self.out / name, arrays)
        self.shards.append({"file": name, "rows": n, "sha256": _sha256(self.out / name)})
        self.rows = []

    def close(self):
        """Writes the last shard, the games table, the manifest and the counters; returns the counters."""
        self._flush()
        g = self.games
        write_npz(self.out / "games.npz", {
            "replay_id": np.array([r.replay_id for r in g], dtype=str),
            "format_id": np.array([r.format_id for r in g], dtype=str),
            "bo3_game": np.array([r.bo3_game for r in g], dtype=np.uint8),
            "ratings": np.array([r.ratings for r in g], dtype=np.int32).reshape(len(g), 2),
            "winner": np.array([r.winner for r in g], dtype=np.int8),
            "turns": np.array([r.turns for r in g], dtype=np.uint16),
            "players": np.array([r.players for r in g], dtype=np.uint64).reshape(len(g), 2),
            "sheets": np.array([r.sheets for r in g], dtype=np.uint64).reshape(len(g), 2),
        })
        counters = dict(sorted(self.counters.items()))
        manifest = {**self.manifest, "format_version": FORMAT_VERSION, "games": len(g), "shards": self.shards,
                    "games_sha256": _sha256(self.out / "games.npz"), "counters": counters}
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                                encoding="utf-8")
        (self.out / "counters.json").write_text(json.dumps(counters, indent=1) + "\n", encoding="utf-8")
        return collections.Counter(self.counters)


def parts(out_dir):
    """The part directories of a dataset built in parts (build.py), in name order; [out_dir] for a single one."""
    out = Path(out_dir)
    found = sorted(p for p in out.glob("part-*") if p.is_dir() and not p.name.endswith(".tmp"))
    return found if found else [out]


def read(out_dir):
    """The shards of a dataset, in order: one dict of arrays per shard, with "part" naming its part directory (a row's
    game indexes that part's games table)."""
    for part in parts(out_dir):
        manifest = json.loads((part / "manifest.json").read_text(encoding="utf-8"))
        for shard in manifest["shards"]:
            with np.load(part / shard["file"]) as z:
                arrays = {name: z[name] for name in z.files}
            arrays["part"] = part.name
            yield arrays


def read_games(part_dir):
    """The games table of one part (or of a single-part dataset)."""
    with np.load(Path(part_dir) / "games.npz") as z:
        return {name: z[name] for name in z.files}
