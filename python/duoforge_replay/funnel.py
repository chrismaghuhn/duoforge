"""The funnel of a replay build (owner, 2026-10-10): per format id, where its games go, as aggregates only.

    read -> other format / no two sheets -> with sheets -> refused (names, legality, Illusion, ...) / internal
    -> set up (processed) -> perspectives to the end / stopped by reason -> rows

A build with pick hypotheses counts their perspectives, turns and rows apart (M11 pick hypotheses spec, section 6):
never as turns without a stop, never in the rows column.

The build counts every stage under "funnel.<format id>.<stage>" beside the totals (source.read_unit, source.select,
build._work_unit), so the funnel of a dataset is its counters.json. Reg M-A is never built (REG_MA): its row
says why.
"""
import collections

PREFIX = "funnel."
# Reg M-A ran under another mechanics era (Showdown before Champions 1.1.0, then a mod of its own): never built
# (owner, 2026-10-10; build.build refuses a prefix that would take its games).
REG_MA = "gen9championsvgc2026regma"
EXCLUDED = {REG_MA: "excluded: other mechanics era (owner, 2026-10-10)"}


def count(counters, format_id, stage, n=1):
    """Adds n to the funnel stage of a format (a dict or a Counter)."""
    key = f"{PREFIX}{format_id}.{stage}"
    counters[key] = counters.get(key, 0) + n


def _empty():
    return {"read": 0, "skipped": collections.Counter(), "internal": 0, "processed": 0,
            "perspectives": {"kept": 0, "stopped": collections.Counter()}, "rows": 0,
            "turns": {"total": 0, "kept": 0, "refused": 0}, "both_kept": 0,
            "hypotheses": {"kept": 0, "stopped": collections.Counter(), "turns": 0, "rows": 0}}


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
        elif stage == "games.both_kept":
            f["both_kept"] += n
        elif stage == "rows.hypotheses":
            f["hypotheses"]["rows"] += n
        elif stage == "turns.hypotheses":
            f["hypotheses"]["turns"] += n
        elif stage == "perspectives.hypotheses_kept":
            f["hypotheses"]["kept"] += n
        elif stage.startswith("perspectives.hypotheses_stopped."):
            f["hypotheses"]["stopped"][stage[len("perspectives.hypotheses_stopped."):]] += n
        elif stage in ("turns.total", "turns.kept", "turns.refused"):
            f["turns"][stage[len("turns."):]] += n
        elif stage == "perspectives.kept":
            f["perspectives"]["kept"] += n
        elif stage.startswith("perspectives.stopped."):
            f["perspectives"]["stopped"][stage[len("perspectives.stopped."):]] += n
        else:
            raise ValueError(f"funnel stage {stage!r} of {format_id} is no stage of the funnel")
    for f in out.values():
        f["with_sheets"] = f["read"] - f["skipped"].get("skip:format", 0) - f["skipped"].get("skip:sheets", 0)
        selection = sum(v for k, v in f["skipped"].items() if k == "skip:has-sheets" or k.startswith("skip:split-"))
        f["taken"] = f["with_sheets"] - selection  # what the build's mode and split take (bo1_belief: no sheets)
        f["skipped"] = dict(f["skipped"])
        f["perspectives"]["stopped"] = dict(f["perspectives"]["stopped"])
        f["hypotheses"]["stopped"] = dict(f["hypotheses"]["stopped"])
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
        selection = {k: v for k, v in f["skipped"].items() if k == "skip:has-sheets" or k.startswith("skip:split-")}
        refused = {k: v for k, v in f["skipped"].items()
                   if k not in ("skip:format", "skip:sheets") and k not in selection}
        p = f["perspectives"]
        lines.append(f"{format_id}: read {f['read']}")
        if other:
            lines.append(f"  not in this build's formats {other}")
        lines.append(f"  without two sheets {f['skipped'].get('skip:sheets', 0)}, with sheets {f['with_sheets']}")
        if selection:
            lines.append(f"  not in this build's selection {sum(selection.values())} (has sheets, other split): "
                         + ", ".join(f"{k} {v}" for k, v in sorted(selection.items())))
        lines.append(f"  taken by this build {f['taken']}")
        lines.append(f"  refused {sum(refused.values())}, internal errors {f['internal']}, set up {f['processed']}")
        for reason, n in sorted(refused.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            lines.append(f"    {n} {reason}")
        both = 2 * f["processed"]
        share = f" ({100 * p['kept'] / both:.1f} %)" if both else ""
        lines.append(f"  perspectives to the end {p['kept']} of {both}{share}, stopped {sum(p['stopped'].values())}")
        for reason, n in sorted(p["stopped"].items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            lines.append(f"    {n} {reason}")
        t = f["turns"]
        every = t["total"] + t["refused"]
        if every:
            lines.append(f"  turns without a stop, of all its games taken {t['kept']} of {every} "
                         f"({100 * t['kept'] / every:.1f} %; a refused game's turns count, none kept)")
        if t["total"]:
            lines.append(f"  turns without a stop, of the games set up {t['kept']} of {t['total']} "
                         f"({100 * t['kept'] / t['total']:.1f} %)")
        taken = f["processed"] + f["internal"] + sum(v for k, v in f["skipped"].items()
                                                     if k not in ("skip:format", "skip:sheets", "skip:has-sheets")
                                                     and not k.startswith("skip:split-"))
        if taken:
            lines.append(f"  matches with both perspectives to the end {f['both_kept']} of {taken} taken "
                         f"({100 * f['both_kept'] / taken:.1f} %), of {f['processed']} set up "
                         f"({100 * f['both_kept'] / max(f['processed'], 1):.1f} %)")
        lines.append(f"  rows {f['rows']}")
        h = f["hypotheses"]
        perspectives = h["kept"] + sum(h["stopped"].values())
        if perspectives:
            lines.append(f"  pick hypotheses (marked rows, apart from the above): perspectives {perspectives}, "
                         f"to the end {h['kept']}, rows {h['rows']}")
            if t["total"]:
                lines.append(f"    turns with pick hypotheses {h['turns']} of {t['total']} "
                             f"({100 * h['turns'] / t['total']:.1f} % of the games set up)")
            for reason, n in sorted(h["stopped"].items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
                lines.append(f"    {n} {reason}")
    return "\n".join(lines) + "\n"
