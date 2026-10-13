"""Ling-Ce's live closed-sheet games on PKMN Arena, in aggregates (#385, after step 5; owner, 2026-10-13).

    python tools/research/cts_live_eval.py --logs DIR [--since 2026-10-13T00:00:00Z] [--bot Ling-Ce] [--out FILE]
    python tools/research/cts_live_eval.py --logs DIR --replay [--out FILE]

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

--replay (#473-#477, the content fixes' before and after): every battle log over the particles is replayed through a
cts.ParticleTracker as the bot played it (its batches as fed and its accepted choices, cts.SEED, the room as the key;
the own team is the registry team its first request matches). At every decision point but the team preview it counts
whether the engine refuses a particle's record (engine-refuses-record) and which unmodelled content each refused
particle holds (src/data/pool_tables.c: a move, item or ability marked [unmodelled], or a Mega Stone whose Mega's ability
is). The result: the points, the refused ones, the share without a refusal (where the search can run), and per content
the points it occurs in and those it alone explains; with the commit and dirty state of the tool and of the engine code
that ran (the checkout duoforge_live is imported from).
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


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def unmodelled(pool_tables):
    """(names of the moves, items and abilities marked [unmodelled], {mega forme: its ability}) of pool_tables.c's text."""
    names = {_key(m.group(1)) for m in re.finditer(r"/\* ([^*\n]+?) -- data/(?:moves|items)\.ts[^\n]*\[unmodelled",
                                                    pool_tables)}
    names |= {m.group(1) for m in re.finditer(r"\*\s+([a-z0-9]+) -- data/abilities\.ts[^\n]*\[unmodelled", pool_tables)}
    megas = {_key(m.group(1)): m.group(2)
             for m in re.finditer(r"/\* ([A-Za-z-]+-Mega(?:-[XY])?) -- abilities: ([a-z0-9]+) \*/", pool_tables)}
    return names, megas


def held(s, content):
    """The unmodelled content a set holds: "move:", "item:", "ability:" or "mega:<forme>(<ability>)" names."""
    names, megas = content
    out = {"move:" + _key(m) for m in s["moves"] if _key(m) in names}
    for kind in ("item", "ability"):
        if s[kind] and _key(s[kind]) in names:
            out.add(f"{kind}:{_key(s[kind])}")
    item, species = _key(s["item"] or ""), _key(s["species"])
    for forme, ability in megas.items():
        if ability in names and item.endswith("ite") and forme.startswith(species) and item[:4] == forme[:4]:
            out.add(f"mega:{forme}({ability})")
    return out


def replay(records, tables, prior, team, room, content):
    """One battle log replayed through the particles: {"points", "refused": [the content per refused particle, per
    refused point]}."""
    from duoforge_live import cts
    t = cts.ParticleTracker(tables, team, prior, cts.SEED, room, cts.PARTICLES)
    out, done = {"points": 0, "refused": []}, 0
    for r in records:
        if "accepted" in r:
            t.accepted(r["accepted"])
            continue
        if "feed" not in r:
            continue
        t.feed(r["feed"])
        if not (t.ready and t.epoch > done):
            continue
        done = t.epoch
        if t.request.get("wait") or t.request.get("teamPreview"):
            continue
        out["points"] += 1
        bad = [i for i, p in enumerate(t.public_parts()) if p["reason"] == ENGINE_REFUSES]
        if bad:
            out["refused"].append([sorted(set().union(*(held(s, content) for s in t.particles[i].sets)))
                                   for i in bad])
    return out


def replay_all(directory, bot, root):
    """--replay over a log directory: the aggregates of replay() (module docstring)."""
    from duoforge_live import cts, data, pkmn_arena
    from duoforge_live.arena import provenance
    tables = data.load(kind="pool")
    prior = cts.SetPrior.from_table(tables)
    engine_root = Path(cts.__file__).resolve().parents[2]
    content = unmodelled((engine_root / "src" / "data" / "pool_tables.c").read_text(encoding="utf-8"))
    teams_dir = data.ROOT / "data" / "teams"
    pastes = [(teams_dir / (t["id"] + ".txt")).read_text(encoding="utf-8")
              for t in json.loads((teams_dir / "index.json").read_text(encoding="utf-8"))["teams"]]
    points, refused, unexplained, skipped = 0, 0, 0, collections.Counter()
    occurs, alone = collections.Counter(), collections.Counter()
    for path in sorted(Path(directory).glob(f"battle-*-{bot}.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any("feed" in r for r in records):
            skipped["no_particles"] += 1
            continue
        first = next(json.loads(r["in"][len("|request|"):]) for r in records
                     if "in" in r and r["in"].startswith("|request|"))
        team = [p for p in pastes if pkmn_arena.request_matches(first["side"]["pokemon"], p)]
        if len(team) != 1:
            skipped["team_unknown"] += 1
            continue
        out = replay(records, tables, prior, team[0], path.name[:-len(f"-{bot}.jsonl")], content)
        points += out["points"]
        for per in out["refused"]:
            refused += 1
            union = set().union(*map(set, per))
            occurs.update(union)
            if any(not c for c in per):
                unexplained += 1
            elif len(union) == 1:
                alone.update(union)
    return {"points": points, "refused": refused, "searchable_share": 1.0 - refused / max(1, points),
            "unexplained": unexplained, "skipped": dict(skipped),
            "content": {c: {"occurs": n, "alone": alone[c]} for c, n in occurs.most_common()},
            "engine_code": provenance(engine_root), "tool_code": provenance(root)}


def main(argv=None):
    p = argparse.ArgumentParser(prog="cts_live_eval.py", description=__doc__.split("\n")[0])
    p.add_argument("--logs", required=True, help="the private log directory (outside the repository)")
    p.add_argument("--since", default=None, help="the run logs started at or after this ISO time (UTC)")
    p.add_argument("--bot", default="Ling-Ce", help="the bot's name: its battle logs end with -<id>.jsonl")
    p.add_argument("--out", default=None, help="a JSON file for the result (outside the repository)")
    p.add_argument("--replay", action="store_true",
                   help="replay the logs through the particles: the refused decision points and their content")
    args = p.parse_args(argv)
    from duoforge_live.arena import provenance
    from duoforge_replay.dataset import refuse_repository
    if args.out:
        refuse_repository(Path(args.out).parent)
    code = provenance(ROOT)
    bot = _toid(args.bot)
    if args.replay:
        text = json.dumps({"since": None, **replay_all(args.logs, bot, ROOT)}, indent=1, sort_keys=True)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return
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
