"""python -m duoforge_replay prior --pastes DIR --out PRIOR.json
python -m duoforge_replay build --source PATH... --prior PRIOR.json --out DIR [--workers N] [--limit-parts N]
python -m duoforge_replay funnel DIR [--top N]
python -m duoforge_replay corpus --source PATH... --registry REPO --out CORPUS.json [--format-prefix P...]
python -m duoforge_replay validate-sets --source PATH... --corpus CORPUS.json --prior PRIOR.json --out REPORT.json
python -m duoforge_replay compare-rows SHEET_DIR DROP_DIR --out REPORT.json

prior: the stat point prior of a directory of Showdown pastes (Stat Points as EVs).
build: the replay dataset (docs/superpowers/specs/2026-10-02-m11-replay-data-design.md). Needs NumPy, pyarrow
for parquet sources, the library, Node and the pinned Showdown checkout (--ps-dir, default
$DUOFORGE_PS_REFERENCE_DIR). The output must lie outside the repository. Exit status 1 when a game raised an
internal error (a bug), 2 for a bad command line. A prefix that would take Reg M-A games is refused (owner, 2026-10-10).
funnel: per format id of a built dataset, read -> with sheets -> refused or set up -> perspectives to the end or
stopped by reason -> rows (duoforge_replay.funnel; aggregates only).
corpus: the set corpus of the Bo1 belief (training-split sheets once per team, and the registry; outside the
repository). build --mode bo1_belief takes the games without sheets, --mode drop_sheets the test-split sheet games
with their sheets dropped (the validation), both on sets drawn from --corpus (M11 Bo1 spec,
docs/superpowers/specs/2026-10-10-m11-bo1-belief-design.md).
validate-sets, compare-rows: its validation (a) and (b) (duoforge_replay.validate; aggregates only).
"""
import argparse
import json
import sys
from pathlib import Path

from . import build, dataset, funnel, prior, source


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
    b.add_argument("--mode", choices=source.MODES, default="sheet", help="which games and whose sheets")
    b.add_argument("--corpus", type=Path, default=None, help="the set corpus (bo1_belief, drop_sheets)")
    b.add_argument("--seed", type=int, default=0, help="the seed of the drawn sets")
    b.add_argument("--k", type=int, default=1, help="draws per game")
    b.add_argument("--split", choices=("train", "test"), default=None,
                   help="only games of this player split (drop_sheets: test)")
    c = sub.add_parser("corpus", help="the set corpus of the Bo1 belief")
    c.add_argument("--source", required=True, nargs="+", type=Path)
    c.add_argument("--registry", required=True, type=Path, help="a checkout whose data/teams is the registry")
    c.add_argument("--out", required=True, type=Path)
    c.add_argument("--format-prefix", nargs="+", default=["gen9championsvgc2026regmc"])
    v = sub.add_parser("validate-sets", help="validation (a): drawn sets against the true sheets of test games")
    v.add_argument("--source", required=True, nargs="+", type=Path)
    v.add_argument("--corpus", required=True, type=Path)
    v.add_argument("--prior", required=True, type=Path)
    v.add_argument("--out", required=True, type=Path)
    v.add_argument("--seed", type=int, default=0)
    v.add_argument("--format-prefix", nargs="+", default=["gen9championsvgc2026regmc"])
    r = sub.add_parser("compare-rows", help="validation (b): a sheet build against a drop_sheets build")
    r.add_argument("sheet", type=Path)
    r.add_argument("drop", type=Path)
    r.add_argument("--out", required=True, type=Path)
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
    if args.command in ("validate-sets", "compare-rows"):
        from . import validate
        if args.command == "compare-rows":
            print(validate.write(validate.compare_rows(args.sheet, args.drop), args.out))
            return 0
        from duoforge_live import data as live_data
        report = validate.sets(args.source, args.format_prefix, args.corpus, args.seed, args.out,
                               live_data.load(kind="pool"), args.prior)
        print(json.dumps(report, indent=1))
        return 0
    if args.command == "corpus":
        from duoforge_live import data as live_data
        from . import corpus
        counters = corpus.build(args.source, args.format_prefix, args.registry, args.out, live_data.load(kind="pool"))
        for key, value in sorted(counters.items()):
            print(f"{key} {value}")
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
                           ps_dir=args.ps_dir, mode=args.mode, corpus=args.corpus, seed=args.seed, k=args.k,
                           split_of=args.split)
    examples = counters.pop("internal.examples")
    for key, value in sorted(counters.items()):
        print(f"{key} {value}")
    if examples or any(key.startswith("internal:") for key in counters):
        print("internal errors (bugs) in the output's parts:", json.dumps(examples, indent=1))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
