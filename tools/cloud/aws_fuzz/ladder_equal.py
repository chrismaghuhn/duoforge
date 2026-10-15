"""The equality proof of an AWS ladder campaign (#484): one ladder arm's report (ladder.json) from this machine and the
same arm's from AWS, the same commit, seed and arm. AWS ladder results count only after this proof.

    python tools/cloud/aws_fuzz/ladder_equal.py LOCAL/ladder.json AWS/ladder.json [--out equal.json]

Every field of the two reports is compared, at any depth, except the ones that measure time or name the machine
(TIMING): the CPU's name, wall seconds, a run's seconds and the p99 of the decision times. AWS times are never used for
a latency gate. A report's decision digests (decisions_sha256: [env, step, seat, kind, choice] of every decision),
per-game scores, pair intervals, counts and diagnostics must be bit-identical. Both runs must name the same commit, and
neither may be dirty. The result names every field that differs: "equal" only when none does, so the report states
openly which parts are bit-identical. Exit status 0 when equal, 1 when not, 2 for an unusable input.
"""
import argparse
import json
import sys

TIMING = frozenset({"cpu", "wall_seconds", "seconds", "p99_seconds", "p99_source"})


def differences(a, b, path=""):
    """The paths where a and b differ (TIMING keys skipped at any depth); floats compared exactly."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key in TIMING:
                continue
            here = f"{path}.{key}" if path else key
            if key not in a or key not in b:
                out.append(here + (" (local only)" if key in a else " (AWS only)"))
            else:
                out.extend(differences(a[key], b[key], here))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path} (length {len(a)} vs {len(b)})"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    if type(a) is not type(b) or a != b:
        return [path]
    return []


def compare(local, aws):
    """The proof's result: equal, the differing paths, and per opponent and arm whether the decision digest is equal."""
    for name, report in (("local", local), ("AWS", aws)):
        conditions = report.get("conditions")
        if not isinstance(conditions, dict) or "commit" not in conditions or "dirty" not in conditions:
            raise ValueError(f"the {name} report has no conditions with commit and dirty")
        if conditions["dirty"] is not False:
            raise ValueError(f"the {name} run is dirty (or names no clean tree): no proof from it")
    digests = {}
    for opponent in sorted(set(local.get("opponents", {})) | set(aws.get("opponents", {}))):
        arms_l = local.get("opponents", {}).get(opponent, {}).get("arms", {})
        arms_a = aws.get("opponents", {}).get(opponent, {}).get("arms", {})
        for arm in sorted(set(arms_l) | set(arms_a)):
            d_l, d_a = arms_l.get(arm, {}).get("decisions_sha256"), arms_a.get(arm, {}).get("decisions_sha256")
            digests[f"{opponent}.{arm}"] = {"local": d_l, "aws": d_a, "equal": d_l is not None and d_l == d_a}
    diffs = differences(local, aws)
    return {"equal": not diffs, "commit": local["conditions"]["commit"], "differs": diffs, "digests": digests,
            "skipped": sorted(TIMING)}


def main(argv=None):
    p = argparse.ArgumentParser(prog="ladder_equal.py", description=__doc__.split("\n\n")[0])
    p.add_argument("local", help="this machine's ladder.json")
    p.add_argument("aws", help="the AWS run's ladder.json")
    p.add_argument("--out", default=None, help="write the result here as JSON")
    args = p.parse_args(argv)
    try:
        reports = []
        for path in (args.local, args.aws):
            with open(path, encoding="utf-8") as f:
                reports.append(json.load(f))
        result = compare(*reports)
    except (OSError, ValueError) as err:
        print(f"ladder_equal: {err}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0 if result["equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
