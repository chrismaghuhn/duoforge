"""Check the existing CI skip/presence gates using CTest's labels.

The inventory is from --show-only=json-v1 for the same configured build.
This reads results; it never selects, reruns, or changes a test.

The linux-full job runs as shards that select tests by label (ctest -L / -LE).
A shard passes its selection here (--shard-include / --shard-exclude, the same
regular expressions): the gates then apply to the tests of that shard, every
one of them must have run exactly once, and --partition checks that the shard
selections together cover every test of the inventory exactly once, so a label
change cannot drop or double a test. No artifact is needed.
"""
import argparse
import json
from pathlib import Path
import re


def labels_of(inventory):
    return {
        test["name"]: set(next((prop["value"] for prop in test.get("properties", [])
                               if prop["name"] == "LABELS"), []))
        for test in inventory["tests"]
    }


def in_shard(tags, include, exclude):
    # ctest semantics: -L keeps a test with a label matching the expression, -LE drops one.
    if include and not any(re.search(include, tag) for tag in tags):
        return False
    if exclude and any(re.search(exclude, tag) for tag in tags):
        return False
    return True


def check_partition(inventory, shards):
    """shards: name -> (include, exclude). Every test must fall into exactly one shard."""
    wrong = {}
    for name, tags in labels_of(inventory).items():
        hits = [shard for shard, (include, exclude) in shards.items() if in_shard(tags, include, exclude)]
        if len(hits) != 1:
            wrong[name] = hits
    if wrong:
        raise ValueError(f"tests not in exactly one shard: {wrong}")
    return len(labels_of(inventory))


def check(inventory, log, no_skip_label, exclude_label, present_label,
          present_count, nonempty_label, shard_include=None, shard_exclude=None):
    all_labels = labels_of(inventory)
    labels = {name: tags for name, tags in all_labels.items()
              if in_shard(tags, shard_include, shard_exclude)}
    sharded = bool(shard_include or shard_exclude)

    def selected(label, pool):
        return {name for name, tags in pool.items() if label in tags}

    # The presence count is a property of the whole inventory, also when one shard runs.
    if len(selected(present_label, all_labels)) != present_count or not selected(no_skip_label, all_labels) \
            or not selected(nonempty_label, all_labels):
        raise ValueError("required CI labels are missing or their presence count changed")
    required = selected(no_skip_label, labels)
    if exclude_label:
        required -= selected(exclude_label, labels)
    present = selected(present_label, labels)
    nonempty = selected(nonempty_label, labels)

    rows, counts = {}, {}
    for line in log.splitlines():
        match = re.search(r"Test\s+#\s*\d+:\s+(\S+)", line)
        if match:
            rows[match.group(1)] = line
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    skipped = sorted(name for name in required if "***Skipped" in rows.get(name, ""))
    missing = sorted(present - rows.keys())
    traces = sorted(nonempty & rows.keys())
    if sharded:
        not_run = sorted(set(labels) - counts.keys())
        foreign = sorted(set(counts) - set(labels))
        doubled = sorted(name for name, count in counts.items() if count > 1)
        if not_run or foreign or doubled:
            raise ValueError(f"shard did not run={not_run}; ran outside the shard={foreign}; ran twice={doubled}")
    if skipped or missing or (nonempty and not traces):
        raise ValueError(f"skipped={skipped}; missing={missing}; labelled traces={len(traces)}")
    return len(required), len(present), len(traces)


def parse_shard(spec):
    # name:include:exclude, either expression may be empty
    name, include, exclude = spec.split(":", 2)
    return name, (include or None, exclude or None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--no-skip-label")
    parser.add_argument("--exclude-label")
    parser.add_argument("--present-label")
    parser.add_argument("--present-count", type=int)
    parser.add_argument("--nonempty-label")
    parser.add_argument("--shard-include", help="the shard's ctest -L expression")
    parser.add_argument("--shard-exclude", help="the shard's ctest -LE expression")
    parser.add_argument("--partition", nargs="+", metavar="NAME:INCLUDE:EXCLUDE",
                        help="every test of the inventory must fall into exactly one of these shards")
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    try:
        if args.partition:
            total = check_partition(inventory, dict(parse_shard(spec) for spec in args.partition))
            print(f"CTest label gate: {total} tests, each in exactly one of {len(args.partition)} shards")
        if args.log:
            counts = check(inventory, args.log.read_text(encoding="utf-8-sig"), args.no_skip_label,
                           args.exclude_label, args.present_label, args.present_count,
                           args.nonempty_label, args.shard_include, args.shard_exclude)
            print(f"CTest label gate: {counts[0]} skip-guard tests, "
                  f"{counts[1]} presence checks, {counts[2]} reference traces")
    except ValueError as error:
        parser.exit(1, f"CTest label gate: {error}\n")


if __name__ == "__main__":
    main()
