"""python -m duoforge_replay prior --pastes DIR --out PRIOR.json
python -m duoforge_replay build --source PATH... --prior PRIOR.json --out DIR [--workers N] [--limit-parts N]
python -m duoforge_replay funnel DIR [--top N]

prior: the stat point prior of a directory of Showdown pastes (Stat Points as EVs).
build: the replay dataset (docs/superpowers/specs/2026-10-02-m11-replay-data-design.md). Needs NumPy, pyarrow
for parquet sources, the library, Node and the pinned Showdown checkout (--ps-dir, default
$DUOFORGE_PS_REFERENCE_DIR). The output must lie outside the repository. Exit status 1 when a game raised an
internal error (a bug), 2 for a bad command line. A prefix that would take Reg M-A games is refused (owner, 2026-10-10).
funnel: per format id of a built dataset, read -> with sheets -> refused or set up -> perspectives to the end or
stopped by reason -> rows (duoforge_replay.funnel; aggregates only).
"""
import argparse
import json
import sys
from pathlib import Path

from . import build, dataset, funnel, prior


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
    b.add_argument("--limit-parts", type=int, default=None, help="write at most N more parts (a short run)")
    b.add_argument("--unit-lines", type=int, default=4096, help="lines per part of a JSON lines source")
    b.add_argument("--format-prefix", nargs="+", default=["gen9championsvgc2026regmc"],
                   help="format id prefixes (several: Reg M-C and Reg M-B)")
    b.add_argument("--node", default="node")
    b.add_argument("--ps-dir", default=None)
    f = sub.add_parser("funnel", help="where a dataset's games went, per format id (aggregates only)")
    f.add_argument("dir", type=Path, help="a replay dataset (its counters.json)")
    f.add_argument("--top", type=int, default=8, help="reasons listed per stage")
    args = parser.parse_args(argv)
    if args.command == "funnel":
        counters = json.loads((args.dir / "counters.json").read_text(encoding="utf-8"))
        report = funnel.report(counters)
        if not report:
            print(f"{args.dir}: no funnel counters (a dataset built before the funnel): rebuild it", file=sys.stderr)
            return 2
        print(funnel.text(report, top=args.top), end="")
        return 0
    if args.command == "prior":
        dataset.refuse_repository(args.out)  # derived from public pastes, kept with the data (decision 0019)
        built = prior.build(args.pastes)
        args.out.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"prior: {built['pastes']} pastes, skipped {built['skipped']}, keys per level "
              f"{[len(level) for level in built['levels']]}")
        return 0
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.limit_parts is not None and args.limit_parts < 0:
        parser.error("--limit-parts must be 0 or more")
    if args.unit_lines < 1:
        parser.error("--unit-lines must be at least 1")
    counters = build.build(args.source, args.prior, args.out, workers=args.workers, limit_parts=args.limit_parts,
                           format_prefix=args.format_prefix, unit_lines=args.unit_lines, node=args.node,
                           ps_dir=args.ps_dir)
    examples = counters.pop("internal.examples")
    for key, value in sorted(counters.items()):
        print(f"{key} {value}")
    if examples or any(key.startswith("internal:") for key in counters):
        print("internal errors (bugs) in the output's parts:", json.dumps(examples, indent=1))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
