"""The funnel of a replay build (owner, 2026-10-10): per format id, where its games go, as aggregates only.

    read -> other format / no two sheets -> with sheets -> refused (names, legality, Illusion, ...) / internal
    -> set up (processed) -> perspectives to the end / stopped by reason -> rows

The build counts every stage under "funnel.<format id>.<stage>" beside the totals (source.read_unit, source.select,
build._work_unit), so the funnel of a dataset is its counters.json. Reg M-A is never built (build.REG_MA): its row
says why.
"""
import collections

PREFIX = "funnel."
EXCLUDED = {"gen9championsvgc2026regma": "excluded: other mechanics era (owner, 2026-10-10)"}


def count(counters, format_id, stage, n=1):
    """Adds n to the funnel stage of a format (a dict or a Counter)."""
    key = f"{PREFIX}{format_id}.{stage}"
    counters[key] = counters.get(key, 0) + n


def _empty():
    return {"read": 0, "skipped": collections.Counter(), "internal": 0, "processed": 0,
            "perspectives": {"kept": 0, "stopped": collections.Counter()}, "rows": 0}


def report(counters):
    """The funnel per format id of a build's counters: read, skipped (reason -> games), internal, processed,
    with_sheets, perspectives (kept, stopped: reason -> perspectives) and rows. ValueError for a stage it does not know."""
    out = {}
    for key, n in counters.items():
        if not key.startswith(PREFIX):
            continue
        format_id, stage = key[len(PREFIX):].split(".", 1)
        f = out.setdefault(format_id, _empty())
        if stage in ("read", "processed", "rows"):
            f[stage] += n
        elif stage.startswith("skipped."):
            f["skipped"][stage[len("skipped."):]] += n
        elif stage.startswith("internal:"):
            f["internal"] += n
        elif stage == "perspectives.kept":
            f["perspectives"]["kept"] += n
        elif stage.startswith("perspectives.stopped."):
            f["perspectives"]["stopped"][stage[len("perspectives.stopped."):]] += n
        else:
            raise ValueError(f"funnel stage {stage!r} of {format_id} is no stage of the funnel")
    for f in out.values():
        f["with_sheets"] = f["read"] - f["skipped"].get("skip:format", 0) - f["skipped"].get("skip:sheets", 0)
        f["skipped"] = dict(f["skipped"])
        f["perspectives"]["stopped"] = dict(f["perspectives"]["stopped"])
    return out


def _excluded(format_id):
    return next((why for prefix, why in EXCLUDED.items() if format_id.startswith(prefix)), None)


def text(report, top=8):
    """The funnel as lines, one block per format id (sorted), the top reasons of refusals and stops."""
    lines = []
    for format_id in sorted(report):
        f = report[format_id]
        why = _excluded(format_id)
        if why is not None:
            lines.append(f"{format_id}: {f['read']} games, {why}")
            continue
        other = f["skipped"].get("skip:format", 0)
        refused = {k: v for k, v in f["skipped"].items() if k not in ("skip:format", "skip:sheets")}
        p = f["perspectives"]
        lines.append(f"{format_id}: read {f['read']}")
        if other:
            lines.append(f"  not in this build's formats {other}")
        lines.append(f"  without two sheets {f['skipped'].get('skip:sheets', 0)}, with sheets {f['with_sheets']}")
        lines.append(f"  refused {sum(refused.values())}, internal errors {f['internal']}, set up {f['processed']}")
        for reason, n in sorted(refused.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            lines.append(f"    {n} {reason}")
        both = 2 * f["processed"]
        share = f" ({100 * p['kept'] / both:.1f} %)" if both else ""
        lines.append(f"  perspectives to the end {p['kept']} of {both}{share}, stopped {sum(p['stopped'].values())}")
        for reason, n in sorted(p["stopped"].items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            lines.append(f"    {n} {reason}")
        lines.append(f"  rows {f['rows']}")
    return "\n".join(lines) + "\n"
