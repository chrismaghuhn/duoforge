"""The set corpus of the Bo1 belief (M11 Bo1 spec section 3): whole sets of open team sheets, counted once per team.

build() reads the games with exactly two sheets of the training split (split.of_game), counts each distinct sheet
(its hash) once, so a Bo3 team is one team however often it was played, and adds every PP_ and LL_ team of the
registry once. The file holds sets derived from unlicensed replays: it is refused inside the repository. It keeps
the sheet hashes it was built from, so a game whose own sheet is in it can be refused (game.process).

    {"version": 1, "format_prefix": [...], "split": "train", "sources": [...], "registry": {...},
     "sheet_hashes": [u64, ...], "sets": {species key: [[item, ability, nature, [moves...], count], ...]}}

A species key is trace_to_c.key of the tables' canonical name; names keep the sheet's spelling.
"""
import collections
import hashlib
import json
from pathlib import Path

from duoforge_live import teams
from duoforge_live.data import trace_to_c

from . import dataset, source, split
from .game import _hash8
from .prior import parse_paste

VERSION = 1


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(paths, format_prefix, registry_root, out_path, data):
    """Writes the corpus of the sources' training-split sheet games and the registry; returns its counters."""
    dataset.refuse_repository(out_path)
    prefix = (format_prefix,) if isinstance(format_prefix, str) else tuple(format_prefix)
    counts = collections.defaultdict(collections.Counter)
    seen, counters = set(), collections.Counter()

    def add(species, item, ability, nature, moves):
        try:
            key = trace_to_c.key(data.canonical(species))
        except ValueError:
            counters["sets.skipped.name"] += 1
            return
        counts[key][(item, ability, nature, tuple(sorted(moves)))] += 1
        counters["sets.counted"] += 1

    for unit in source.units(paths):
        for _, format_id, log in source.read_unit(unit, prefix, counters):
            if not format_id.startswith(prefix):
                continue
            lines = log.split("\n")
            packed = [line.split("|", 3)[3] for line in lines if line.startswith("|showteam|")]
            if len(packed) != 2:
                counters["games.skipped.sheets"] += 1
                continue
            try:
                players = split.players_of(lines)
            except ValueError:
                counters["games.skipped.players"] += 1
                continue
            if split.of_game(players) != "train":
                counters["games.skipped.test"] += 1
                continue
            counters["games.read"] += 1
            for payload in packed:
                h = _hash8(payload)
                if h in seen:
                    continue
                seen.add(h)
                for s in teams.unpack(payload):
                    add(s["species"], s["item"], s["ability"], s["nature"], s["moves"])
    registry = Path(registry_root) / "data" / "teams"
    index = json.loads((registry / "index.json").read_text(encoding="utf-8"))
    ids = [e["id"] for e in index["teams"] if e["id"].startswith(("PP_", "LL_"))]
    for team_id in ids:
        for species, item, ability, nature, moves, _ in parse_paste((registry / f"{team_id}.txt").read_text(
                encoding="utf-8")):
            add(species, item, ability, nature, moves)
    out = {"version": VERSION, "format_prefix": list(prefix), "split": "train",
           "sources": [{"file": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in source.files(paths)],
           "registry": {"teams": len(ids), "index_sha256": _sha256(registry / "index.json")},
           "sheet_hashes": sorted(seen), "counters": dict(sorted(counters.items())),
           "sets": {k: sorted([list(e[:3]) + [list(e[3]), n] for e, n in v.items()]) for k, v in sorted(counts.items())}}
    dataset.write_json_atomic(Path(out_path), out)
    return counters


class Corpus:
    """A loaded corpus: sets(key) -> [(item, ability, nature, moves tuple, count)], sheet_hashes, sha256."""

    def __init__(self, sets, sheet_hashes, sha256):
        self._sets = {k: [tuple(e) for e in v] for k, v in sets.items()}
        self.sheet_hashes = frozenset(sheet_hashes)
        self.sha256 = sha256

    def sets(self, key):
        return list(self._sets.get(key, ()))


def load(path):
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    if doc.get("version") != VERSION:
        raise ValueError(f"{path}: not a version {VERSION} set corpus")
    sets = {k: [(e[0], e[1], e[2], tuple(e[3]), e[4]) for e in v] for k, v in doc["sets"].items()}
    return Corpus(sets, doc["sheet_hashes"], hashlib.sha256(raw).hexdigest())
