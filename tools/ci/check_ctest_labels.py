"""Check the existing CI skip/presence gates using CTest's labels.

The inventory is from --show-only=json-v1 for the same configured build.
This reads results; it never selects, reruns, or changes a test.
"""
import argparse
import json
from pathlib import Path
import re


def check(inventory, log, no_skip_label, exclude_label, present_label,
          present_count, nonempty_label):
    labels = {
        test["name"]: set(next((prop["value"] for prop in test.get("properties", [])
                               if prop["name"] == "LABELS"), []))
        for test in inventory["tests"]
    }

    def selected(label):
        return {name for name, tags in labels.items() if label in tags}

    required = selected(no_skip_label)
    if exclude_label:
        required -= selected(exclude_label)
    present = selected(present_label)
    nonempty = selected(nonempty_label)
    if not required or len(present) != present_count or not nonempty:
        raise ValueError("required CI labels are missing or their presence count changed")

    rows = {}
    for line in log.splitlines():
        match = re.search(r"Test\s+#\s*\d+:\s+(\S+)", line)
        if match:
            rows[match.group(1)] = line
    skipped = sorted(name for name in required if "***Skipped" in rows.get(name, ""))
    missing = sorted(present - rows.keys())
    traces = sorted(nonempty & rows.keys())
    if skipped or missing or not traces:
        raise ValueError(f"skipped={skipped}; missing={missing}; labelled traces={len(traces)}")
    return len(required), len(present), len(traces)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--no-skip-label", required=True)
    parser.add_argument("--exclude-label")
    parser.add_argument("--present-label", required=True)
    parser.add_argument("--present-count", type=int, required=True)
    parser.add_argument("--nonempty-label", required=True)
    args = parser.parse_args()
    try:
        counts = check(json.loads(args.inventory.read_text(encoding="utf-8")),
                       args.log.read_text(encoding="utf-8-sig"), args.no_skip_label,
                       args.exclude_label, args.present_label, args.present_count,
                       args.nonempty_label)
    except ValueError as error:
        parser.exit(1, f"CTest label gate: {error}\n")
    print(f"CTest label gate: {counts[0]} skip-guard tests, "
          f"{counts[1]} presence checks, {counts[2]} reference traces")


if __name__ == "__main__":
    main()
