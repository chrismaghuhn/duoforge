"""Ling-Ce's live closed-sheet games on PKMN Arena, in aggregates (#385, after step 5; owner, 2026-10-13).

    python tools/research/cts_live_eval.py --logs DIR [--since 2026-10-13T00:00:00Z] [--bot Ling-Ce] [--out FILE]
    python tools/research/cts_live_eval.py --logs DIR --replay [--out FILE]
    ... [--labels PRIVATE.json]: everything also per opponent, by letter

DIR holds the bot's private logs (outside the repository): the run logs arena-run-*.json (aggregates already) and the
battle logs battle-*.jsonl (match ids; read here, never printed). The result holds aggregates only, never a room id, a
user id or a name:
- battles: those played over the particles (a battle log with fed batches), apart from those of before the particles
  (answered with /choose default for closed_team_sheets) and others;
- results: wins, losses, ties, unfinished;
- the decisions of the particle battles but the team previews (every decision the bot made, with a search outcome
  or without one): searched share, raw fallbacks (a) and those whose named reasons include a refused particle
  (engine-refuses-record, #464), deadline misses, decisions answered with /choose default after a fallback;
- the battles' fallback reasons and named stops (named(): the reason's own words up to the first free text);
- the search's seconds per decision (search.seconds), n, p50, p95, p99 and max;
- --since keeps the battles by their first timestamp and the run logs by their start;
- the run logs since --since, summed: counts (wins, reconnects, deadline misses, ...), fallbacks, closes, the search's
  causes and the particle counters (cts);
- the code: the commit and dirty state of this tool (duoforge_live.arena.provenance).

--labels (HauptSession, 2026-10-13): the results also per opponent, each opponent by a letter that a private label file
(outside the repository) keeps across series; a new opponent takes the next letters, by battles then by first
appearance. The file holds the opponents' ids, so it never enters the repository, and no id is ever printed.

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
sys.path.append(str(ROOT / "python"))  # after PYTHONPATH: a measurement may run another checkout's code

from duoforge_live.arena import ENGINE_REFUSES  # noqa: E402  (#464: a record the engine refuses)



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
    """The aggregates of one battle log's records; bot: the bot's id (toid of its name). Every decision the bot made
    is counted (review of the evaluation tool): one with a search outcome by its cause, one without (a raw game after a
    class (b) error) as "no_search", a team choice as "team"; the seconds are the search's, but a dirty game's."""
    out = {"kind": "other", "result": "unfinished", "causes": collections.Counter(), "fallbacks": collections.Counter(),
           "engine_refuses_record": 0, "defaults": 0, "timer_missing": 0, "rejected": 0, "unavailable": 0,
           "dirty": False, "fallback": None, "stop": None, "seconds": [], "start": None}
    fed = False
    for r in records:
        line = r.get("in", "")
        if out["start"] is None and line.startswith("|t:|"):
            out["start"] = int(line[len("|t:|"):])  # the battle's first timestamp (unix seconds)
        if "feed" in r:
            fed = True
        elif "fallback" in r and "sent" not in r and out["fallback"] is None:
            out["fallback"] = r["fallback"]
            if r["fallback"].startswith("stop:") or r["fallback"].startswith("error:"):
                out["stop"] = named(r.get("detail", r["fallback"]))
        elif r.get("sent") == "default":
            out["defaults"] += 1
        elif "decision" in r and "sent" in r:
            s = r.get("search")
            cause = "team" if str(r["sent"]).startswith("team ") else (s["cause"] if s else "no_search")
            out["causes"][cause] += 1
            if s and s.get("fallback"):
                out["fallbacks"][s["fallback"]] += 1
            if s and s.get("fallback") == "a" and ENGINE_REFUSES in str(s.get("reason")):
                out["engine_refuses_record"] += 1  # a raw decision whose named reasons include a refused particle
            if s and s["cause"] not in ("team", "dirty"):
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
            end = r["end"]
            if end.startswith("|win|"):
                out["result"] = "win" if _toid(end[len("|win|"):]) == bot else "loss"
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


def opponent(records, bot):
    """The id (toid) of the battle's player who is not the bot, or None."""
    for r in records:
        line = r.get("in", "")
        if line.startswith("|player|"):
            parts = line.split("|")
            if len(parts) > 3 and parts[3] and _toid(parts[3]) != bot:
                return _toid(parts[3])
    return None


def _letters(k):
    """A, B, ..., Z, AA, AB, ..."""
    out = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        out = chr(65 + r) + out
    return out


def assign_labels(opponents, labels):
    """labels extended by the opponents (one entry per battle) it lacks: the next letters, by battles, then by first
    appearance."""
    out = dict(labels)
    counts, first = collections.Counter(opponents), {}
    for i, o in enumerate(opponents):
        first.setdefault(o, i)
    for o in sorted((o for o in counts if o not in out), key=lambda o: (-counts[o], first[o])):
        out[o] = _letters(len(out))
    return out


def load_labels(path):
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(Path(path).parent)
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_labels(path, labels):
    Path(path).write_text(json.dumps(labels, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def unmodelled(pool_tables):
    """The names (keys) of the moves, items and abilities pool_tables.c's text marks [unmodelled]."""
    names = {_key(m.group(1)) for m in re.finditer(r"/\* ([^*\n]+?) -- data/(?:moves|items)\.ts[^\n]*\[unmodelled",
                                                    pool_tables)}
    names |= {m.group(1) for m in re.finditer(r"\*\s+([a-z0-9]+) -- data/abilities\.ts[^\n]*\[unmodelled", pool_tables)}
    return names


def held(s, names, tables):
    """The unmodelled content a set holds: "move:", "item:", "ability:", or "mega:<forme>(<ability>)" for a Mega Stone
    whose Mega forme (the library's own holder and stone pairs, Data.mega_of) has an unmodelled ability."""
    out = {"move:" + _key(m) for m in s["moves"] if _key(m) in names}
    for kind in ("item", "ability"):
        if s[kind] and _key(s[kind]) in names:
            out.add(f"{kind}:{_key(s[kind])}")
    if s["item"]:
        item = tables.tables["ITEM"].get(_key(s["item"]).upper())
        mega = None if item is None else tables.mega_of(tables.forme(s["species"]), item + 1)
        if mega is not None:
            formes = {v: k for k, v in tables.tables["FORME"].items() if k != "COUNT"}
            abilities = {v: k for k, v in tables.tables["ABILITY"].items() if k != "COUNT"}
            ability = abilities.get(tables.ability_of(mega) - 1, "").lower()
            if ability in names:
                out.add(f"mega:{formes[mega].lower()}({ability})")
    return out


def replay(records, tables, prior, team, room, names):
    """One battle log replayed through the particles: {"points", "refused": [the content per refused particle, per
    refused point], "stopped": None or the named reason the replay ended with}. What the bot's own fold catches ends
    the replay by name, as the bot's battle fell back there."""
    from duoforge_live import cts
    own = set().union(*(held(s, names, tables) for s in teams_sets(team)))
    out = {"points": 0, "refused": [], "stopped": None}
    replayed = cts.LogReplay(records, tables, None, team, prior, room)  # the one replay core (Search's ko_check too)
    for game, _ in replayed:
        t = game.tracker
        if t.request.get("teamPreview"):
            continue
        out["points"] += 1
        bad = [i for i, p in enumerate(t.public_parts()) if p["reason"] == ENGINE_REFUSES]
        if bad:  # a refused particle holding no foe content is put on the own team's, when that has any
            out["refused"].append([sorted(set().union(*(held(s, names, tables) for s in t.particles[i].sets))
                                          or {"own:" + c for c in own}) for i in bad])
    # the replay's own stop or failure, else the bot's named fallback; a failure of this tool (public_parts, held)
    # propagates and ends --replay: it is no fallback of the bot
    out["stopped"] = replayed.stopped
    out["diverged"] = replayed.diverged
    return out


def teams_sets(text):
    from duoforge_live import teams
    return teams._paste(text)


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def replay_all(directory, bot, root, labels=None, since=None):
    """--replay over a log directory: the aggregates of replay() (module docstring); with labels (opponent id ->
    letter) also per opponent; with since (unix seconds) only the battles that started then or later."""
    import os
    from duoforge_live import cts, data, pkmn_arena
    from duoforge_live.arena import provenance
    tables = data.load(kind="pool")
    prior = cts.SetPrior.from_table(tables)
    engine_root = Path(cts.__file__).resolve().parents[2]
    names = unmodelled((engine_root / "src" / "data" / "pool_tables.c").read_text(encoding="utf-8"))
    if not names:
        raise SystemExit("no [unmodelled] marker found in src/data/pool_tables.c: its format changed")
    library = os.environ.get("DUOFORGE_LIBRARY")
    import hashlib
    played = {json.loads(p.read_text(encoding="utf-8")).get("team_sha256")
              for p in Path(directory).glob("arena-run-*.json")} - {None}  # the bot's --team, when its run logs name it
    teams_dir = data.ROOT / "data" / "teams"
    pastes = [(teams_dir / (t["id"] + ".txt")).read_text(encoding="utf-8")
              for t in json.loads((teams_dir / "index.json").read_text(encoding="utf-8"))["teams"]]
    points, refused, unexplained, skipped, stopped = 0, 0, 0, collections.Counter(), collections.Counter()
    per = collections.defaultdict(lambda: {"battles": 0, "points": 0, "refused": 0})
    occurs, alone = collections.Counter(), collections.Counter()
    for path in sorted(Path(directory).glob(f"battle-*-{bot}.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any("feed" in r for r in records):
            skipped["no_particles"] += 1
            continue
        if since is not None and (battle(records, bot)["start"] or 0) < since:
            skipped["before_since"] += 1
            continue
        first = next((json.loads(r["in"][len("|request|"):]) for r in records
                      if "in" in r and r["in"].startswith("|request|")), None)
        if first is None:
            skipped["no_request"] += 1
            continue
        team = [p for p in pastes if pkmn_arena.request_matches(first["side"]["pokemon"], p)]
        if len(team) != 1:
            skipped["team_unknown"] += 1
            continue
        if played and hashlib.sha256(team[0].encode("utf-8")).hexdigest() not in played:
            skipped["team_differs"] += 1  # the registry paste is not the --team the bot played (its stats may differ)
            continue
        out = replay(records, tables, prior, team[0], cts.room_of_log(path, bot), names)
        points += out["points"]
        if labels is not None:
            group = per[labels.get(opponent(records, bot), "?")]
            group["battles"] += 1
            group["points"] += out["points"]
            group["refused"] += len(out["refused"])
        if out["stopped"]:
            stopped[out["stopped"]] += 1
        if out["diverged"]:
            skipped["diverged"] += 1  # the replay and the bot disagree on a stop: a determinism break, named
        for held_by in out["refused"]:
            refused += 1
            union = set().union(*map(set, held_by))
            occurs.update(union)
            if any(not c for c in held_by):
                unexplained += 1
            elif len(union) == 1:
                alone.update(union)
    engine = {**provenance(engine_root),
              "library_sha256": _sha256(library) if library and Path(library).exists() else None}
    return {"points": points, "refused": refused, "searchable_share": 1.0 - refused / max(1, points),
            "unexplained": unexplained, "skipped": dict(skipped), "stopped_battles": dict(stopped),
            "content": {c: {"occurs": n, "alone": alone[c]} for c, n in occurs.most_common()},
            "engine_code": engine, "tool_code": provenance(root),
            **({} if labels is None else {"by_opponent": {
                k: {**v, "searchable_share": 1.0 - v["refused"] / max(1, v["points"])} for k, v in sorted(per.items())}})}


def _unix(iso):
    from datetime import datetime, timezone
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def main(argv=None):
    p = argparse.ArgumentParser(prog="cts_live_eval.py", description=__doc__.split("\n")[0])
    p.add_argument("--logs", required=True, help="the private log directory (outside the repository)")
    p.add_argument("--since", default=None,
                   help="only the battles (by their first timestamp) and run logs that started at or after this "
                        "ISO time (UTC), e.g. 2026-10-13T00:00:00Z")
    p.add_argument("--bot", default="Ling-Ce", help="the bot's name: its battle logs end with -<id>.jsonl")
    p.add_argument("--out", default=None, help="a JSON file for the result (outside the repository)")
    p.add_argument("--labels", default=None,
                   help="a private JSON file (outside the repository) of the opponents' letters, kept across series")
    p.add_argument("--replay", action="store_true",
                   help="replay the logs through the particles: the refused decision points and their content")
    args = p.parse_args(argv)
    from duoforge_live.arena import provenance
    from duoforge_replay.dataset import refuse_repository
    if args.out:
        refuse_repository(Path(args.out).parent)
    code = provenance(ROOT)
    bot = _toid(args.bot)
    since = None if args.since is None else _unix(args.since)
    paths = sorted(Path(args.logs).glob(f"battle-*-{bot}.jsonl"))
    logs = [[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for path in paths]
    kept = [records for records in logs if since is None or (battle(records, bot)["start"] or 0) >= since]
    labels = None
    if args.labels:
        labels = assign_labels([o for o in (opponent(r, bot) for r in kept) if o], load_labels(args.labels))
        save_labels(args.labels, labels)
    if args.replay:
        result = {"since": args.since, **replay_all(args.logs, bot, ROOT, labels, since)}
    else:
        battles, groups = [], collections.defaultdict(list)
        for records in kept:
            battles.append(battle(records, bot))
            if labels is not None:
                groups[labels.get(opponent(records, bot), "?")].append(battles[-1])
        result = {"code": code, "since": args.since, "logs": len(logs), "since_kept": len(kept),
                  **summarize(battles), "runs": run_logs(args.logs, args.since)}
        if labels is not None:
            result["by_opponent"] = {k: summarize(v) for k, v in sorted(groups.items())}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
