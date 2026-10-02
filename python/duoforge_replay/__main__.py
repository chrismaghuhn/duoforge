"""python -m duoforge_replay prior --pastes DIR --out PRIOR.json
python -m duoforge_replay build --source PATH... --prior PRIOR.json --out DIR [--workers N] [--limit-games N]

prior: the stat point prior of a directory of Showdown pastes (Stat Points as EVs).
build: the replay dataset (docs/superpowers/specs/2026-10-02-m11-replay-data-design.md). Needs NumPy, pyarrow
for parquet sources, the library, Node and the pinned Showdown checkout (--ps-dir, default
$DUOFORGE_PS_REFERENCE_DIR). The output must lie outside the repository. Exit status 1 when a game raised an
internal error (a bug), 2 for a bad command line.
"""
import argparse
import json
import sys
from pathlib import Path

from . import build, prior


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m duoforge_replay", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prior", help="the stat point prior of a directory of pastes")
    p.add_argument("--pastes", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    b = sub.add_parser("build", help="a replay dataset")
    b.add_argument("--source", required=True, nargs="+", type=Path, help="parquet or jsonl files, or directories")
    b.add_argument("--prior", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--workers", type=int, default=1)
    b.add_argument("--limit-games", type=int, default=None)
    b.add_argument("--format-prefix", default="gen9championsvgc2026regmc")
    b.add_argument("--node", default="node")
    b.add_argument("--ps-dir", default=None)
    args = parser.parse_args(argv)
    if args.command == "prior":
        built = prior.build(args.pastes)
        args.out.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"prior: {built['pastes']} pastes, skipped {built['skipped']}, keys per level "
              f"{[len(level) for level in built['levels']]}")
        return 0
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    counters = build.build(args.source, args.prior, args.out, workers=args.workers, limit_games=args.limit_games,
                           format_prefix=args.format_prefix, node=args.node, ps_dir=args.ps_dir)
    examples = counters.pop("internal.examples")
    for key, value in sorted(counters.items()):
        print(f"{key} {value}")
    if examples:
        print("internal errors (bugs):", json.dumps(examples, indent=1))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
