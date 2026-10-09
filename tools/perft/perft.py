"""Perft/divide: frozen counts of the legal joint actions (docs/ROADMAP.md, "Perft/divide counts as an engine
regression test").

A position is a battle setup (a reference pairing of decision 0004 or two registry teams), a seed and a prefix of
joint choices from the battle's first boundary (TEAM_SELECTION). perft(position, d) counts the sequences of d joint
actions from it:

  - a joint action at a decision boundary is one response of every requested player, each taken from the engine's
    own domain (duoforge_battle_factored through duoforge_batch_query_factored), in the engine's order: player 0's
    rank major, player 1's minor when both are asked, the one player's rank when only one is (PIVOT, REPLACEMENT);
  - perft(node, 0) = 1; a TERMINAL node has no joint action, so perft(TERMINAL, d >= 1) = 0 (as a mate in chess
    perft); otherwise perft(node, d) = sum over its joint actions of perft(child, d - 1);
  - a child is the engine's fork of the node (decision 0022, duoforge_batch_expand): a copy of the node, its
    gameplay RNG replaced by duoforge_search_seeds(seed, 0, 0), stepped with the joint action to the next decision
    boundary. Chance is therefore fixed: every edge, the prefix's included, starts from the same seeds, and nothing
    here draws a random number.

The sequence hash of perft(position, d) is the SHA-256 over the records of every node at depths 0 .. d - 1 in
preorder (a node, then the subtrees of its children in joint order): boundary kind (u8), request mask (u8), and
each player's domain size (u32 little-endian, 0 when not requested). It changes when an option is added or removed
anywhere in the tree, and also when the order of a domain changes, which the counts alone would not show.

Python only counts and hashes: the domains, the steps and the chance are the engine's, through the public C API.
A position the engine refuses (a setup, a step, a leaf) raises PerftError naming the status; nothing is skipped.

usage:
  python tools/perft/perft.py                                  every pinned position and depth, printed
  python tools/perft/perft.py --check                          the same against the pins; exit 1 with a diff
  python tools/perft/perft.py --position NAME --depth 2 --divide
                                                               perft(child, depth - 1) of every first joint action
  python tools/perft/perft.py --write [--position NAME]        recompute the pins (never used by the test)
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

import duoforge  # noqa: E402
from duoforge import _layout, teams  # noqa: E402
from duoforge.errors import DuoforgeError  # noqa: E402

PINS = ROOT / "tests" / "perft" / "pins.json"
TEAMS = ROOT / "data" / "teams"

C = _layout.CONSTANTS
KINDS = {"CLOSURE": C["DUOFORGE_DATA_KIND_CLOSURE"], "POOL": C["DUOFORGE_DATA_KIND_POOL"]}
BOUNDARIES = {C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]: "TEAM_SELECTION", C["DUOFORGE_BOUNDARY_TURN"]: "TURN",
              C["DUOFORGE_BOUNDARY_REPLACEMENT"]: "REPLACEMENT", C["DUOFORGE_BOUNDARY_PIVOT"]: "PIVOT",
              C["DUOFORGE_BOUNDARY_TERMINAL"]: "TERMINAL"}
TERMINAL = C["DUOFORGE_BOUNDARY_TERMINAL"]
PAIRINGS = {0: ("A", "B"), 1: ("B", "A"), 2: ("A", "A"), 3: ("B", "B")}  # duoforge_reference_setup
ENCODER = 1  # the expansion encodes a row per leaf; the smallest encoder, its rows are not read here
CHUNK = 2048  # leaves per expansion
WORKERS = max(1, min(8, os.cpu_count() or 1))  # results do not depend on it (decision 0012)

RECORD = np.dtype([("boundary", "u1"), ("mask", "u1"), ("n0", "<u4"), ("n1", "<u4")])  # 10 bytes, packed


class PerftError(RuntimeError):
    """The engine refused a position, a step or a leaf, or a node has no request; the message says where."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def setup_of(ctx, spec):
    """The battle setup (SETUP, (1,)) of a position and what it is made of: the reference pairing or the registry
    teams with their file hashes, and the SHA-256 of the setup record."""
    if "pairing" in spec:
        pairing = int(spec["pairing"])
        if pairing not in PAIRINGS:
            raise PerftError(f"pairing {pairing} is not a reference pairing ({sorted(PAIRINGS)})")
        setup = duoforge.reference_setups([pairing])
        teams_info = {"reference": list(PAIRINGS[pairing])}
    elif "registry" in spec:
        ids = list(spec["registry"])
        if len(ids) != 2:
            raise PerftError(f"registry {ids}: a position has two teams, side 0 first")
        try:
            pool = teams.load(ctx, sorted(set(ids)), root=str(TEAMS))
        except teams.TeamError as err:
            raise PerftError(str(err)) from None
        order = list(pool.ids)
        setup = pool.setups([order.index(ids[0])], [order.index(ids[1])])
        teams_info = {"registry": ids, "sha256": [pool.sha256[order.index(t)] for t in ids]}
    else:
        raise PerftError(f"a position needs 'pairing' or 'registry': {spec}")
    return setup, teams_info, _sha(setup.tobytes())


def records(batch, n):
    """The node records (RECORD, (n,)) of environments 0 .. n - 1 after a query, and their joint domain sizes.
    A non-TERMINAL node that requests nobody raises."""
    req = batch.requests[:n]
    boundary = req["boundary_kind"][:, 0]
    if (req["boundary_kind"][:, 1] != boundary).any():
        raise PerftError("the two players' requests name different boundaries")
    asked = req["requested"].astype(bool)
    out = np.zeros(n, dtype=RECORD)
    out["boundary"] = boundary
    out["mask"] = asked[:, 0] | (asked[:, 1] << 1)
    for p, field in ((0, "n0"), (1, "n1")):
        rows = np.flatnonzero(asked[:, p])
        if rows.size:
            out[field][rows] = duoforge.joint_counts(batch.domains[rows, p])
    idle = (out["mask"] == 0) & (boundary != TERMINAL)
    if idle.any():
        raise PerftError(f"a {BOUNDARIES.get(int(boundary[idle][0]), boundary[idle][0])} node requests nobody")
    if ((out["mask"] != 0) & (boundary == TERMINAL)).any():
        raise PerftError("a TERMINAL node requests a player")
    n0 = np.where(asked[:, 0], out["n0"].astype(np.int64), 1)
    n1 = np.where(asked[:, 1], out["n1"].astype(np.int64), 1)
    joint = np.where(boundary == TERMINAL, 0, n0 * n1)
    return out, joint


def ranks_of(record, k):
    """Each player's rank in its own domain for joint rank k of a node (None for a player not asked)."""
    mask, n1 = int(record["mask"]), int(record["n1"])
    if mask == 3:
        return [k // n1, k % n1]
    return [k, None] if mask == 1 else [None, k]


class Tree:
    """The perft tree of one position: its context, the root batch and one leaf batch per level."""

    def __init__(self, spec, workers=WORKERS, chunk=CHUNK):
        kind = spec["data_kind"]
        if kind not in KINDS:
            raise PerftError(f"data kind {kind!r} is not one of {sorted(KINDS)}")
        self.spec = spec
        self.seed = int(spec["seed"])
        self.workers, self.chunk = workers, chunk
        self.ctx = duoforge.Context(data_kind=KINDS[kind])
        self.setup, self.teams, self.setup_sha256 = setup_of(self.ctx, spec)
        self._levels = {}
        self._cursor = [self._batch(1), self._batch(1)]
        self.node = self._walk(spec.get("prefix", []))

    def _batch(self, envs):
        try:
            return duoforge.Batch(self.ctx, np.repeat(self.setup, envs), self.workers, self.seed)
        except DuoforgeError as err:
            raise PerftError(f"position {self.spec['name']}: the engine refuses the setup: {err}") from None

    def _level(self, k):
        if k not in self._levels:
            self._levels[k] = self._batch(self.chunk)
        return self._levels[k]

    def close(self):
        for b in list(self._levels.values()) + self._cursor:
            b.close()
        self.ctx.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _expand(self, roots, env, leaves, choices, where):
        """Children of node (roots, env) with factored choices (m, 2) into leaves 0 .. m - 1, queried."""
        m = choices.shape[0]
        keys = np.zeros(roots.envs, dtype=np.uint64)
        viewers = np.zeros(roots.envs, dtype=np.uint8)
        _, steps, encodes, _, _ = leaves.expand(roots, ENCODER, 0, self.seed, keys, viewers,
                                                np.full(m, env, dtype=np.uint32), np.zeros(m, dtype=np.uint32),
                                                choices)
        for name, statuses in (("step", steps), ("leaf encoding", encodes)):
            bad = np.flatnonzero(statuses)
            if bad.size:
                raise PerftError(f"position {self.spec['name']}: the engine refuses the {name} of child "
                                 f"{int(bad[0])} of {where}: {duoforge.status_name(int(statuses[bad[0]]))}")
        leaves.query_factored()

    def _choices(self, batch, env, record, ks):
        """The factored choices (len(ks), 2) of joint ranks ks of node (batch, env)."""
        out = np.zeros((len(ks), 2), dtype=_layout.FACTORED_CHOICE)
        mask, n1 = int(record["mask"]), int(record["n1"])
        ks = np.asarray(ks, dtype=np.int64)
        per = (ks // n1, ks % n1) if mask == 3 else ((ks, None) if mask == 1 else (None, ks))
        for p in (0, 1):
            if per[p] is not None:
                out[:, p] = duoforge.factored_choices(np.repeat(batch.domains[env, p:p + 1], len(ks)), per[p])
        return out

    def _walk(self, prefix):
        """The prefix's end node, as (batch, env, record); each step is a fork as in the tree."""
        batch = self._cursor[0]
        batch.query_factored()
        for step, ranks in enumerate(prefix):
            rec, joint = records(batch, 1)
            mask = int(rec[0]["mask"])
            want = [r is not None for r in ranks]
            if want != [bool(mask & 1), bool(mask & 2)]:
                raise PerftError(f"position {self.spec['name']}: prefix step {step} gives ranks {ranks} but the "
                                 f"node asks players {[p for p in (0, 1) if mask >> p & 1]}")
            n = [int(rec[0]["n0"]), int(rec[0]["n1"])]
            if any(r is not None and not 0 <= r < n[p] for p, r in enumerate(ranks)):
                raise PerftError(f"position {self.spec['name']}: prefix step {step} ranks {ranks} are outside the "
                                 f"domains of sizes {n}")
            k = (ranks[0] * n[1] + ranks[1]) if mask == 3 else (ranks[0] if mask == 1 else ranks[1])
            nxt = self._cursor[1] if batch is self._cursor[0] else self._cursor[0]
            self._expand(batch, 0, nxt, self._choices(batch, 0, rec[0], [k]), f"prefix step {step}")
            batch = nxt
        rec, _ = records(batch, 1)
        return batch, 0, rec[0]

    def boundary(self):
        return BOUNDARIES[int(self.node[2]["boundary"])]

    def children(self, batch, env, record, d, level, hasher):
        """perft(child, d - 1) of every joint action of node (batch, env) in joint order (int64 array), d >= 1;
        the records of the children's subtrees go into hasher in preorder."""
        mask = int(record["mask"])
        if int(record["boundary"]) == TERMINAL:
            return np.zeros(0, dtype=np.int64)
        joint = (int(record["n0"]) if mask & 1 else 1) * (int(record["n1"]) if mask & 2 else 1)
        if d == 1:
            return np.ones(joint, dtype=np.int64)
        out = np.zeros(joint, dtype=np.int64)
        leaves = self._level(level)
        for start in range(0, joint, self.chunk):
            ks = np.arange(start, min(joint, start + self.chunk))
            self._expand(batch, env, leaves, self._choices(batch, env, record, ks),
                         f"a depth-{level} node at joint rank {start}..{start + ks.size - 1}")
            recs, joints = records(leaves, ks.size)
            if d == 2:
                hasher.update(recs.tobytes())
                out[ks] = joints
                continue
            for i in range(ks.size):
                hasher.update(recs[i:i + 1].tobytes())
                out[start + i] = self.children(leaves, i, recs[i], d - 1, level + 1, hasher).sum()
        return out

    def perft(self, d):
        """(count, sequence sha256, divide array) of perft(position, d)."""
        if d < 1:
            raise PerftError(f"depth {d}: perft is defined here for depth 1 and more")
        batch, env, record = self.node
        hasher = hashlib.sha256()
        hasher.update(np.asarray([record], dtype=RECORD).tobytes())
        per_child = self.children(batch, env, record, d, 1, hasher)
        return int(per_child.sum()), hasher.hexdigest(), per_child

    def labels(self, k):
        """A readable form of joint action k of the position: each asked player's rank and slot commands."""
        batch, env, record = self.node
        ranks = ranks_of(record, k)
        parts = []
        for p, r in enumerate(ranks):
            if r is None:
                parts.append(f"p{p}: -")
                continue
            dom = batch.domains[env, p]
            ch = duoforge.factored_choice(dom, r)
            if int(dom["kind"]) == C["DUOFORGE_CHOICE_TEAM_SELECTION"]:
                picks = "".join(str(int(x)) for x in ch["picks"][:int(dom["pick_count"])])
                parts.append(f"p{p}#{r}: picks {picks}")
                continue
            slots = [_slot(dom["slots"][s][int(ch["slot"][s])]) for s in (0, 1)
                     if int(dom["slot_count"][s]) > 0]
            parts.append(f"p{p}#{r}: " + " , ".join(slots))
        return " | ".join(parts)


def _slot(cmd):
    """A slot command as text: m<slot+1>@<flat target>[+mega], struggle, recharge, switch<r>, pass, revive<r>, and
    - for a slot that is not asked."""
    kind = int(cmd["kind"])
    if kind == C["DUOFORGE_SLOT_NONE"]:
        return "-"
    if kind == C["DUOFORGE_SLOT_MOVE"]:
        slot = int(cmd["move_slot"])
        name = {C["DUOFORGE_MOVE_SLOT_STRUGGLE"]: "struggle", C["DUOFORGE_MOVE_SLOT_RECHARGE"]: "recharge"}.get(
            slot, f"m{slot + 1}")
        target = int(cmd["target"])
        return name + ("" if target == C["DUOFORGE_TARGET_NONE"] else f"@{target}") + (
            "+mega" if int(cmd["mega"]) else "")
    if kind == C["DUOFORGE_SLOT_SWITCH"]:
        return f"switch{int(cmd['reserve'])}"
    if kind == C["DUOFORGE_SLOT_PASS"]:
        return "pass"
    if kind == C["DUOFORGE_SLOT_REVIVE"]:
        return f"revive{int(cmd['reserve'])}"
    return f"kind{kind}"


# ---------------------------------------------------------------- pins


def load_pins(path=PINS):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def measure(spec, depths=None, workers=WORKERS):
    """What the pins hold for one position, computed now."""
    depths = sorted(int(d) for d in (depths if depths is not None else spec["depths"]))
    with Tree(spec, workers=workers) as tree:
        out = {"boundary": tree.boundary(), "teams": tree.teams, "setup_sha256": tree.setup_sha256,
               "context_fingerprint": tree.ctx.fingerprint().hex(), "depths": {}}
        for d in depths:
            count, seq, _ = tree.perft(d)
            out["depths"][str(d)] = {"count": count, "sequence_sha256": seq}
    return out


def diff(spec, now):
    """The differences between a pinned position and what it is now, as readable lines ([] when equal)."""
    name, lines = spec["name"], []
    for key in ("boundary", "teams", "setup_sha256"):
        if spec.get(key) != now[key]:
            lines.append(f"{name}: {key}: pinned {spec.get(key)!r}, now {now[key]!r}")
    for d, pin in sorted(spec["depths"].items(), key=lambda kv: int(kv[0])):
        got = now["depths"].get(d)
        if pin is None:
            lines.append(f"{name} depth {d}: not pinned yet (now {got['count']}); run --write")
            continue
        if got["count"] != pin["count"]:
            lines.append(f"{name} depth {d}: count pinned {pin['count']}, now {got['count']} "
                         f"({got['count'] - pin['count']:+d})")
        if got["sequence_sha256"] != pin["sequence_sha256"]:
            lines.append(f"{name} depth {d}: sequence sha256 pinned {pin['sequence_sha256'][:16]}..., now "
                         f"{got['sequence_sha256'][:16]}... (an option or the order of a domain changed)")
    if lines:
        lines.append(f"  pinned with library {spec.get('library_version')} context "
                     f"{str(spec.get('context_fingerprint'))[:16]}..., now {duoforge.version()} context "
                     f"{now['context_fingerprint'][:16]}...")
        lines.append(f"  find the changed first joint action: python tools/perft/perft.py --position {name} "
                     f"--depth {max(int(d) for d in spec['depths'])} --divide; a wanted change is pinned with "
                     f"--write --position {name} and its reason in the commit message")
    return lines


def check(pins, names=None, workers=WORKERS):
    """Every difference of the selected pinned positions (all when names is None)."""
    lines = []
    for spec in pins["positions"]:
        if names is None or spec["name"] in names:
            lines += diff(spec, measure(spec, workers=workers))
    return lines


def write(pins, names=None, path=PINS, workers=WORKERS):
    for spec in pins["positions"]:
        if names is None or spec["name"] in names:
            now = measure(spec, workers=workers)
            spec.update({k: now[k] for k in ("boundary", "teams", "setup_sha256", "context_fingerprint")})
            spec["library_version"] = duoforge.version()
            spec["depths"] = now["depths"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(pins))


_ORDER = ("name", "data_kind", "pairing", "registry", "seed", "prefix", "boundary", "teams", "setup_sha256",
          "context_fingerprint", "library_version", "depths")


def dumps(pins):
    """The pins file: one line per field of a position and per pinned depth, keys in a fixed order."""
    one = lambda v: json.dumps(v, separators=(", ", ": "))  # noqa: E731
    out = ["{"]
    for key, value in pins.items():
        if key != "positions":
            out.append(f"  {one(key)}: {one(value)},")
    out.append('  "positions": [')
    for i, spec in enumerate(pins["positions"]):
        unknown = set(spec) - set(_ORDER)
        if unknown:
            raise PerftError(f"position {spec.get('name')}: unknown fields {sorted(unknown)}")
        fields = [f"      {one(k)}: {one(spec[k])}" for k in _ORDER if k in spec and k != "depths"]
        depths = [f"        {one(d)}: {one(v)}" for d, v in sorted(spec["depths"].items(), key=lambda kv: int(kv[0]))]
        fields.append('      "depths": {\n' + ",\n".join(depths) + "\n      }")
        out.append("    {\n" + ",\n".join(fields) + "\n    }" + ("," if i + 1 < len(pins["positions"]) else ""))
    out.append("  ]")
    out.append("}")
    return "\n".join(out) + "\n"


def _position(pins, name):
    for spec in pins["positions"]:
        if spec["name"] == name:
            return spec
    raise SystemExit(f"no position {name!r} in the pins; known: {', '.join(s['name'] for s in pins['positions'])}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pins", default=str(PINS))
    ap.add_argument("--position", action="append", help="a position name (repeatable); default: all")
    ap.add_argument("--depth", type=int, help="one depth (default: the pinned ones)")
    ap.add_argument("--divide", action="store_true", help="perft(child, depth - 1) of every first joint action")
    ap.add_argument("--check", action="store_true", help="compare with the pins; exit 1 on a difference")
    ap.add_argument("--write", action="store_true", help="recompute and write the pins of the selected positions")
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args(argv)
    pins = load_pins(args.pins)
    names = set(args.position) if args.position else None
    if names:
        for n in names:
            _position(pins, n)
    if args.write:
        write(pins, names, path=args.pins, workers=args.workers)
        print(f"wrote {args.pins}")
        return 0
    if args.check:
        lines = check(pins, names, workers=args.workers)
        print("\n".join(lines) if lines else "perft: every pin matches")
        return 1 if lines else 0
    if args.divide:
        if not names or len(names) != 1 or args.depth is None:
            ap.error("--divide needs one --position and --depth")
        spec = _position(pins, next(iter(names)))
        with Tree(spec, workers=args.workers) as tree:
            count, seq, per = tree.perft(args.depth)
            for k, v in enumerate(per.tolist()):
                print(f"{k:6d}  {tree.labels(k)}: {v}")
            print(f"{spec['name']} depth {args.depth} [{tree.boundary()}]: {count} sequence {seq}")
        return 0
    for spec in pins["positions"]:
        if names is not None and spec["name"] not in names:
            continue
        depths = [args.depth] if args.depth is not None else spec["depths"]
        t = time.perf_counter()
        now = measure(spec, depths, workers=args.workers)
        for d, v in now["depths"].items():
            print(f"{spec['name']} [{now['boundary']}] depth {d}: {v['count']} sequence {v['sequence_sha256']}")
        print(f"  {time.perf_counter() - t:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
