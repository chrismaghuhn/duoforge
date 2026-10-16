"""Write the P1 evaluation manifest (plan C5) for a run: the pool from the team registry and every checkpoint's
file SHA-256, then expert_eval.make_manifest. Plays nothing; no battle rules here.

python -m duoforge_search.eval_manifest --teams IDS --team-weights WS --teams-root ROOT --seed S
    --first-game-id G --checkpoint NAME=PATH (one per expert_eval.CHECKPOINTS name) --out MANIFEST

Exit 0 with the manifest written once (never overwritten) outside the repository; exit 2 with the cause for a
missing, unknown or repeated checkpoint name, a missing file, a pool without both buckets or a path inside the
repository. Run it after both arms are trained and before the evaluation smoke.
"""
import argparse
import hashlib
import json
import sys
from typing import Sequence

import duoforge
from duoforge import _layout, teams
from duoforge_replay.dataset import refuse_repository

from . import expert_eval


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoints(pairs):
    out = {}
    for pair in pairs:
        name, sep, path = pair.partition("=")
        if not sep or not path:
            raise ValueError(f"--checkpoint takes NAME=PATH (got {pair!r})")
        if name not in expert_eval.CHECKPOINTS:
            raise ValueError(f"unknown checkpoint {name!r}: the evaluation names {expert_eval.CHECKPOINTS}")
        if name in out:
            raise ValueError(f"checkpoint {name!r} given twice")
        out[name] = path
    missing = [n for n in expert_eval.CHECKPOINTS if n not in out]
    if missing:
        raise ValueError(f"checkpoints missing: {', '.join(missing)}")
    return {name: _file_sha256(path) for name, path in out.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m duoforge_search.eval_manifest")
    parser.add_argument("--teams", required=True, help="registry team ids, comma-separated")
    parser.add_argument("--team-weights", required=True, help="their sampling weights, comma-separated")
    parser.add_argument("--teams-root", required=True, help="the team registry")
    parser.add_argument("--seed", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--first-game-id", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--checkpoint", action="append", default=[], help="NAME=PATH, once per evaluation name")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        refuse_repository(args.out)
        checkpoints = _checkpoints(args.checkpoint)
        ids = [t.strip() for t in args.teams.split(",")]
        weights = [float(w) for w in args.team_weights.split(",")]
        with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = teams.load(ctx, ids, root=args.teams_root, weights=weights)
            manifest = expert_eval.make_manifest(pool, seed=args.seed, first_game_id=args.first_game_id,
                                                 checkpoints=checkpoints)
        data = json.dumps(expert_eval.manifest_mapping(manifest), indent=1, sort_keys=True)
        with open(args.out, "x", encoding="utf-8") as f:
            f.write(data)
    except (ValueError, TypeError, KeyError, OSError, duoforge.DuoforgeError) as err:
        print(f"eval_manifest: {err}", file=sys.stderr)
        return 2
    print(json.dumps({"manifest": args.out, "sha256": hashlib.sha256(data.encode()).hexdigest(),
                      "pool_teams": len(pool.ids), "first_game_id": args.first_game_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
