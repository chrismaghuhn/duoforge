"""Ling-Ce's live closed-sheet games on PKMN Arena, in aggregates (#385, after step 5; owner, 2026-10-13).

    python tools/research/cts_live_eval.py --logs DIR [--since 2026-10-13T00:00:00Z] [--bot Ling-Ce] [--out FILE]

DIR holds the bot's private logs (outside the repository): the run logs arena-run-*.json (aggregates already) and the
battle logs battle-*.jsonl (match ids; read here, never printed). The result holds aggregates only, never a room id, a
user id or a name:
- battles: those played over the particles (a battle log with fed batches), apart from those of before the particles
  (answered with /choose default for closed_team_sheets) and others;
- results: wins, losses, ties, unfinished;
- the decisions of the particle battles but the team previews: searched share, raw fallbacks (a) and their #464 part
  (engine-refuses-record), deadline misses, decisions answered with /choose default after a fallback;
- the battles' fallback reasons and named stops (named(): the reason's own words up to the first free text);
- the search's seconds per decision (search.seconds), n, p50, p95, p99 and max;
- the run logs since --since, summed: counts (wins, reconnects, deadline misses, ...), fallbacks, closes, the search's
  causes and the particle counters (cts);
- the code: the commit and dirty state of this tool (duoforge_live.arena.provenance).
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

ENGINE_REFUSES = "engine-refuses-record"  # the tracker's reason of a record the engine refuses (#464)


def _toid(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def named(detail):
    """A fallback's detail cut to its named reason: the words that are names of the code ("stop:cts:redraw-cap",
    "stop:feature:SUBSTITUTE"), up to the first free text. A word without ':' or one that ends with ':' (whose text
    follows: a nickname, a message) ends it."""
    out = []
    for word in detail.split(" "):
        if ":" not in word:
            break
        out.append(word.rstrip(":"))
        if word.endswith(":"):
            break
    return " ".join(out)


def battle(records, bot):
    """The aggregates of one battle log's records; bot: the bot's id (toid of its name)."""
    out = {"kind": "other", "result": "unfinished", "causes": collections.Counter(), "fallbacks": collections.Counter(),
           "engine_refuses_record": 0, "defaults": 0, "timer_missing": 0, "rejected": 0, "unavailable": 0,
           "dirty": False, "fallback": None, "stop": None, "seconds": []}
    fed = False
    for r in records:
        if "feed" in r:
            fed = True
        elif "fallback" in r and "sent" not in r and out["fallback"] is None:
            out["fallback"] = r["fallback"]
            if r["fallback"].startswith("stop:") or r["fallback"].startswith("error:"):
                out["stop"] = named(r.get("detail", r["fallback"]))
        elif r.get("sent") == "default":
            out["defaults"] += 1
        elif "decision" in r and "search" in r:
            s = r["search"]
            out["causes"][s["cause"]] += 1
            if s.get("fallback"):
                out["fallbacks"][s["fallback"]] += 1
            if s.get("fallback") == "a" and ENGINE_REFUSES in str(s.get("reason")):
                out["engine_refuses_record"] += 1
            if s["cause"] != "team":
                out["seconds"].append(float(s["seconds"]))
        elif r.get("timer") == "missing":
            out["timer_missing"] += 1
        elif "rejected" in r:
            out["rejected"] += 1
        elif "unavailable" in r:
            out["unavailable"] += 1
        elif "dirty" in r:
            out["dirty"] = True
        elif "end" in r:
            line = r["end"]
            if line.startswith("|win|"):
                out["result"] = "win" if _toid(line[len("|win|"):]) == bot else "loss"
            else:
                out["result"] = "tie"
    if out["fallback"] == "closed_team_sheets":
        out["kind"] = "before_particles"
    elif fed:
        out["kind"] = "particles"
    out["causes"], out["fallbacks"] = dict(out["causes"]), dict(out["fallbacks"])
    return out


def _quantiles(seconds):
    import numpy as np
    if not seconds:
        return {"n": 0}
    s = np.asarray(seconds, dtype=np.float64)
    p50, p95, p99 = (float(np.quantile(s, q, method="higher")) for q in (0.50, 0.95, 0.99))
    return {"n": int(s.size), "p50": p50, "p95": p95, "p99": p99, "max": float(s.max())}


def summarize(battles):
    """The aggregates over battle() results: every count over the battles played over the particles."""
    out = {"battles": dict(collections.Counter(b["kind"] for b in battles))}
    played = [b for b in battles if b["kind"] == "particles"]
    out["results"] = dict(collections.Counter(b["result"] for b in played))
    causes = collections.Counter()
    for b in played:
        causes.update(b["causes"])
    decisions = sum(n for c, n in causes.items() if c != "team")
    out.update({
        "causes": dict(causes), "decisions": decisions,
        "searched_share": causes.get("searched", 0) / max(1, decisions),
        "raw_a": sum(b["fallbacks"].get("a", 0) for b in played),
        "engine_refuses_record": sum(b["engine_refuses_record"] for b in played),
        "deadline": sum(b["fallbacks"].get("deadline", 0) for b in played),
        "defaulted_decisions": sum(b["defaults"] for b in played),
        "fallback_battles": dict(collections.Counter(b["fallback"] for b in played if b["fallback"])),
        "stops": dict(collections.Counter(b["stop"] for b in played if b["stop"])),
        "timer_missing": sum(b["timer_missing"] for b in played),
        "rejected": sum(b["rejected"] for b in played), "unavailable": sum(b["unavailable"] for b in played),
        "dirty": sum(1 for b in played if b["dirty"]),
        "seconds": _quantiles([x for b in played for x in b["seconds"]])})
    out["engine_refuses_record_share"] = out["engine_refuses_record"] / max(1, decisions)
    return out


def run_logs(directory, since=None):
    """The run logs (arena-run-*.json) started at or after `since` (ISO, UTC), summed."""
    out = {"files": 0, "counts": collections.Counter(), "fallback_battles": collections.Counter(),
           "fallback_decisions": collections.Counter(), "closes": collections.Counter(),
           "search_causes": collections.Counter(), "cts": collections.Counter()}
    for path in sorted(Path(directory).glob("arena-run-*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        if since is not None and r.get("started", "") < since:
            continue
        out["files"] += 1
        for key in ("counts", "fallback_battles", "fallback_decisions", "closes", "search_causes", "cts"):
            out[key].update(r.get(key, {}))
    return {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in out.items()}


def main(argv=None):
    p = argparse.ArgumentParser(prog="cts_live_eval.py", description=__doc__.split("\n")[0])
    p.add_argument("--logs", required=True, help="the private log directory (outside the repository)")
    p.add_argument("--since", default=None, help="the run logs started at or after this ISO time (UTC)")
    p.add_argument("--bot", default="Ling-Ce", help="the bot's name: its battle logs end with -<id>.jsonl")
    p.add_argument("--out", default=None, help="a JSON file for the result (outside the repository)")
    args = p.parse_args(argv)
    from duoforge_live.arena import provenance
    from duoforge_replay.dataset import refuse_repository
    if args.out:
        refuse_repository(Path(args.out).parent)
    code = provenance(ROOT)
    bot = _toid(args.bot)
    battles = []
    for path in sorted(Path(args.logs).glob(f"battle-*-{bot}.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        battles.append(battle(records, bot))
    result = {"code": code, "since": args.since, **summarize(battles), "runs": run_logs(args.logs, args.since)}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
