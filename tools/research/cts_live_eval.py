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
particle holds (src/data/formats/reg-mc/pool_tables.c: a move, item or ability marked [unmodelled], or a Mega Stone whose Mega's ability
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
           "dirty": False, "fallback": None, "stop": None, "seconds": [], "start": None, "code": None, "arm": None,
           "foe_lead": None}
    fed = False
    sides, foe_lead, started = {}, [], False  # the foe's two leads: its switch lines before the first turn
    for r in records:
        line = r.get("in", "")
        parts = line.split("|") if isinstance(line, str) else []
        if len(parts) > 3 and parts[1] == "player" and parts[3]:
            sides[parts[2]] = _toid(parts[3]) == bot
        elif len(parts) > 1 and parts[1] == "turn":
            started = True
        elif len(parts) > 3 and parts[1] == "switch" and not started and sides.get(parts[2][:2]) is False:
            foe_lead.append(parts[3].split(",")[0].strip())
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
        elif "log_format" in r and (r.get("code") or r.get("search_rule")):
            if r.get("code"):
                out["code"] = r["code"]  # the bot's commit and dirty state, in every battle's first record (format 2)
            if r.get("search_rule"):
                out["arm"] = r["search_rule"]["arm"]  # the A/B test of the root rule (duoforge_live.ab)
        elif "summary" in r and out["code"] is None:
            out["code"] = (r["summary"] or {}).get("code")  # the bot's commit and dirty state (pkmn_arena, since #480)
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
    out["foe_lead"] = " + ".join(sorted(foe_lead)) if len(foe_lead) == 2 else None  # species only: no name
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


def wilson(k, n, z=1.96):
    """[k / n, low, high]: the Wilson interval of a share (z: 1.96 for 95%), None for n = 0."""
    import math
    if n == 0:
        return None
    p = k / n
    centre, half = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [p, (centre - half) / (1 + z * z / n), (centre + half) / (1 + z * z / n)]


# The A/B test's analysis (docs/benchmarks/2026-10-14-ab-root-rule/README.md, HauptSession, fixed before the deploy):
# read only at three looks, 30, 60 and 100 decided battles per arm; at 30 and 60 the difference's 99% interval, at 100
# its 95% one. The strata (per opponent, per foe lead) are described only, from 10 decided battles per arm on.
AB_LOOKS = {30: 2.576, 60: 2.576, 100: 1.96}  # the look -> its z (99%, 99%, 95%)
AB_STRATUM_MIN = 10


def _newcombe(x, y):
    """Newcombe's interval (his method 10) of the difference y - x of two shares from their Wilson intervals."""
    import math
    d = y[0] - x[0]
    return {"value": d, "low": d - math.sqrt((y[0] - y[1]) ** 2 + (x[2] - x[0]) ** 2),
            "high": d + math.sqrt((y[2] - y[0]) ** 2 + (x[0] - x[1]) ** 2)}


def ab_arms(rows):
    """The A/B test of the root rule (docs/benchmarks/2026-10-14-ab-root-rule): rows (battle(), opponent letter, foe
    lead) of the battles that name an arm, every one counted in its arm (intention to treat): the decided battles (a
    win, a loss or a tie), the wins, the unfinished ones, those played without the search after a class (b) error
    (dirty or a decision without a search), and the win rate with its Wilson interval. The difference 2e - 0 has
    Newcombe's interval at 95%; "look" names the last of AB_LOOKS both arms reached, and "at_look" the difference's
    interval at that look's level (None before the first look): the only reading a preference may rest on. The same
    per opponent letter and per foe lead (the foe's two lead species), descriptive only: a stratum with fewer than
    AB_STRATUM_MIN decided battles in an arm gives its counts only, and no stratum has a look."""
    from duoforge_live import ab

    def arms(subset, minimum=0, looks=True):
        out = {}
        for a in ab.ARMS:
            played = [b for b in subset if b["arm"] == a]
            decided = [b for b in played if b["result"] in ("win", "loss", "tie")]
            wins = sum(b["result"] == "win" for b in decided)
            out[a] = {"battles": len(played), "decided": len(decided), "wins": wins,
                      "unfinished": len(played) - len(decided),
                      "without_search": sum(1 for b in played if b["dirty"] or b["causes"].get("no_search")),
                      "kinds": dict(collections.Counter(b["kind"] for b in played)),
                      "win_rate": wilson(wins, len(decided)) if len(decided) >= max(1, minimum) else None}
        rates = [out[a]["win_rate"] for a in ab.ARMS]
        reached = [n for n in AB_LOOKS if all(out[a]["decided"] >= n for a in ab.ARMS)] if looks else []
        out["look"] = reached[-1] if reached else None
        if None in rates:
            out["difference"] = None
        else:
            at = None
            if out["look"] is not None:  # the look's level, from the wins and decided battles of each arm
                z = AB_LOOKS[out["look"]]
                x, y = (wilson(out[a]["wins"], out[a]["decided"], z) for a in ab.ARMS)
                at = {"level": {2.576: 0.99, 1.96: 0.95}[z], **{k: v for k, v in _newcombe(x, y).items() if k != "value"}}
            out["difference"] = {"of": f"{ab.ARMS[1]} - {ab.ARMS[0]}", **_newcombe(*rates), "at_look": at}
        return out
    battles = [b for b, _, _ in rows]
    return {"looks": {str(n): {2.576: 0.99, 1.96: 0.95}[z] for n, z in AB_LOOKS.items()},
            "stratum_min": AB_STRATUM_MIN, "all": arms(battles),
            "by_opponent": {o: arms([b for b, oo, _ in rows if oo == o], AB_STRATUM_MIN, looks=False)
                            for o in sorted({o for _, o, _ in rows})},
            "by_lead": {lead: arms([b for b, _, ll in rows if ll == lead], AB_STRATUM_MIN, looks=False)
                        for lead in sorted({ll for _, _, ll in rows if ll})}}

def run_logs(directory, since=None, code=None):
    """The run logs (arena-run-*.json) started at or after `since` (ISO, UTC), with code: of a bot commit that starts
    with it, summed."""
    out = {"files": 0, "counts": collections.Counter(), "fallback_battles": collections.Counter(),
           "fallback_decisions": collections.Counter(), "closes": collections.Counter(),
           "search_causes": collections.Counter(), "cts": collections.Counter()}
    for path in sorted(Path(directory).glob("arena-run-*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        if since is not None and r.get("started", "") < since:
            continue
        if code is not None and not _in_series(r.get("code"), code):
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


def foe_team(records, bot):
    """A short digest of the opponent's team: its team-preview species (|poke| lines of its side), sorted. Species are
    public game facts; the digest only tells one team of an opponent from another."""
    import hashlib
    side, species = None, set()  # a set: a resync logs the |poke| lines again
    for r in records:
        line = r.get("in", "")
        parts = line.split("|")
        if line.startswith("|player|") and len(parts) > 3 and parts[3] and _toid(parts[3]) != bot:
            side = parts[2]
    for r in records:
        line = r.get("in", "")
        if side and line.startswith(f"|poke|{side}|"):
            species.add(line.split("|")[3].split(",")[0])
    if not species:
        return None  # no foe side or no preview: the team is unknown ("?"), never one digest for all
    return hashlib.sha256(",".join(sorted(species)).encode("utf-8")).hexdigest()[:12]


def assign_teams(pairs, labels):
    """labels extended by the (opponent, team) pairs (one per battle, in order) it lacks: each opponent's teams are
    numbered by first appearance ("team:<opponent>|<team>" -> number), kept across series."""
    out = dict(labels)
    for o, t in pairs:
        if t is None:
            continue
        key = f"team:{o}|{t}"
        if key not in out:
            out[key] = 1 + sum(1 for k in out if k.startswith(f"team:{o}|"))
    return out


def team_label(labels, o, t):
    """An opponent's team as its letter and number (A1, B2, ...), "?" for an unknown one."""
    letter, number = labels.get(o), labels.get(f"team:{o}|{t}")
    return f"{letter}{number}" if letter and number else "?"


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
    for o in sorted((o for o in counts if o not in out), key=lambda o: (-counts[o], first[o])):  # opponents only
        out[o] = _letters(sum(1 for k in out if not k.startswith("team:")))
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


def selected(directory, bot, since, code, skipped):
    """The battle logs of the bot over the particles that a replay follows, in name order: (path, records, own team
    paste), the paste the registry team the battle's first request matches. What is left out is counted in skipped by
    reason (no_particles, before_since, other_code, no_request, team_unknown, team_differs)."""
    import hashlib
    from duoforge_live import data, pkmn_arena
    played = {json.loads(p.read_text(encoding="utf-8")).get("team_sha256")
              for p in Path(directory).glob("arena-run-*.json")} - {None}  # the bot's --team, when its run logs name it
    teams_dir = data.ROOT / "data" / "teams"
    pastes = [(teams_dir / (t["id"] + ".txt")).read_text(encoding="utf-8")
              for t in json.loads((teams_dir / "index.json").read_text(encoding="utf-8"))["teams"]]
    for path in sorted(Path(directory).glob(f"battle-*-{bot}.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any("feed" in r for r in records):
            skipped["no_particles"] += 1
            continue
        if since is not None and (battle(records, bot)["start"] or 0) < since:
            skipped["before_since"] += 1
            continue
        if code is not None and not _in_series(battle(records, bot)["code"], code):
            skipped["other_code"] += 1
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
        yield path, records, team[0]


def replay_all(directory, bot, root, labels=None, since=None, code=None, details=None):
    """--replay over a log directory: the aggregates of replay() (module docstring); with labels (opponent id ->
    letter) also per opponent; with since (unix seconds) only the battles that started then or later."""
    import os
    from duoforge_live import cts, data, pkmn_arena
    from duoforge_live.arena import provenance
    tables = data.load(kind="pool")
    prior = cts.SetPrior.from_table(tables)
    engine_root = Path(cts.__file__).resolve().parents[2]
    names = unmodelled((engine_root / "src" / "data" / "formats" / "reg-mc" / "pool_tables.c").read_text(encoding="utf-8"))
    if not names:
        raise SystemExit("no [unmodelled] marker found in src/data/formats/reg-mc/pool_tables.c: its format changed")
    library = os.environ.get("DUOFORGE_LIBRARY")
    points, refused, unexplained, skipped, stopped = 0, 0, 0, collections.Counter(), collections.Counter()
    per = collections.defaultdict(lambda: {"battles": 0, "points": 0, "refused": 0})
    per_team = collections.defaultdict(lambda: {"battles": 0, "points": 0, "refused": 0})
    occurs, alone = collections.Counter(), collections.Counter()
    for path, records, team in selected(directory, bot, since, code, skipped):
        out = replay(records, tables, prior, team, cts.room_of_log(path, bot), names)
        points += out["points"]
        if labels is not None:
            o = opponent(records, bot)
            for group in (per[labels.get(o, "?")], per_team[team_label(labels, o, foe_team(records, bot))]):
                group["battles"] += 1
                group["points"] += out["points"]
                group["refused"] += len(out["refused"])
        if details is not None:  # private: the battle's room is in it (written outside the repository only)
            held_by = collections.Counter(c for point in out["refused"] for c in set().union(*map(set, point)))
            details.append({"room": cts.room_of_log(path, bot),
                            "team": None if labels is None else team_label(labels, opponent(records, bot),
                                                                           foe_team(records, bot)),
                            "points": out["points"], "refused": len(out["refused"]), "content": dict(held_by),
                            "stopped": out["stopped"], "diverged": out["diverged"]})
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
            **({} if labels is None else {
                "by_opponent": {k: {**v, "searchable_share": 1.0 - v["refused"] / max(1, v["points"])}
                                for k, v in sorted(per.items())},
                "by_team": {k: {**v, "searchable_share": 1.0 - v["refused"] / max(1, v["points"])}
                            for k, v in sorted(per_team.items())}})}


def interval(values):
    """(mean, half width of a normal 95% interval) of values, None for none; the half width None for one value."""
    import statistics
    if not values:
        return None
    mean = statistics.fmean(values)
    return {"mean": mean, "half": None if len(values) < 2 else 1.96 * statistics.stdev(values) / len(values) ** 0.5,
            "n": len(values)}


def luck_series(battles):
    """The luck aggregates of battles ({"turns", "mixed", "dropped", "worlds", "result", "excluded"} each,
    cts_luck.battle; the share of the valued turns' worlds the turn refuted): per battle its
    summed luck and its largest turn, per series the mean summed luck and the result with the luck taken off, with
    intervals, each also without the turns whose foe action was mixed over a set (only the series' means say
    something; a single battle is an anecdote). Every mean is over the battles with a result; the unfinished ones (a log
    without its end) are counted apart, with their valued turns."""
    unfinished = [b for b in battles if b["result"] is None]
    battles = [b for b in battles if b["result"] is not None]  # every mean over the same battles: those with a result
    finished = battles
    excluded = collections.Counter()
    for b in battles:
        excluded.update(b["excluded"])
    valued = sum(len(b["turns"]) for b in battles)
    mixed = sum(sum(b["mixed"]) for b in battles)

    def unmixed(b):  # the battle's luck without its mixed turns (HauptSession: the series mean with and without them)
        return sum(t for t, m in zip(b["turns"], b["mixed"]) if not m)
    return {"battles": len(battles) + len(unfinished), "finished": len(finished), "unfinished": len(unfinished),
            "turns_valued": valued, "turns_unfinished": sum(len(b["turns"]) for b in unfinished),
            "turns_partial": dict(sum((collections.Counter(b.get("partial", {})) for b in battles),
                                      collections.Counter())),
            "unfinished_excluded": dict(sorted(sum((collections.Counter(b["excluded"]) for b in unfinished),
                                                   collections.Counter()).items())),
            "turns_excluded": dict(sorted(excluded.items())),
            "valued_share": valued / max(1, valued + sum(excluded.values())),
            "turns_mixed": mixed, "mixed_share": mixed / max(1, valued),
            "worlds_dropped_share": sum(sum(b["dropped"]) for b in battles)
            / max(1, sum(len(b["dropped"]) * b["worlds"] for b in battles)),
            "luck_per_battle": interval([sum(b["turns"]) for b in battles]),
            "luck_per_battle_unmixed": interval([unmixed(b) for b in battles]),
            "largest_turn": interval([max(b["turns"], key=abs) for b in battles if b["turns"]]),
            "result": interval([b["result"] for b in finished]),
            "result_minus_luck": interval([b["result"] - sum(b["turns"]) for b in finished]),
            "result_minus_luck_unmixed": interval([b["result"] - unmixed(b) for b in finished])}


# The live search of each bot commit (HauptSession, 2026-10-14): a series is replayed with the settings its bot played,
# the ladder step whose settings equal that commit's live HONEST_SETTINGS (checked against each commit's
# python/duoforge_live/search.py). An unknown commit is refused by name, never guessed. From the bot that writes its
# search settings in the run log's head on (search_settings), the head names them, and a known commit's step must agree.
SEARCH_STEPS = {"1ffa6a03": "0", "a7dd956b": "2e", "5c503d8a": "2e"}
SEARCH_DIFFERS_LIMIT = 0.05  # a larger share of replayed decisions the bot decided otherwise: no report (HauptSession)
# The bot processes of the series whose logs name no code (the HauptSession, from the VPS, 2026-10-14): a process's start
# is its run log's name and "started". Of the processes before a7dd956b only 1ffa6a03 played over the particles
# (a75c380a has no cts.py and answered closed sheets with /choose default), so a battle log with fed batches whose
# directory's run logs all started with 1ffa6a03 is that process's. Anything else is refused by name.
PROCESS_STARTS = {"1ffa6a03": "2026-10-13T19:23:34Z"}


def series_run_logs(directory, code=None):
    """The heads of the run logs of a series: with code, those of that bot commit (clean); without, those that name no
    code (the bots before the run logs named it). Other bots' run logs in a shared directory are not the series'."""
    heads = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(directory).glob("arena-run-*.json"))]
    return [h for h in heads if (_in_series(h.get("code"), code) if code is not None else not h.get("code"))]


def check_bot_commit(directory, commit):
    """SystemExit unless the run logs that name no code (series_run_logs) all started as commit's process
    (PROCESS_STARTS), and there is one: --bot-commit is the content's assignment of logs that name no code, never a
    declaration."""
    start = PROCESS_STARTS.get(str(commit or "")[:8])
    if start is None:
        raise SystemExit(f"--bot-commit {commit!r}: no process start is known for it (PROCESS_STARTS names "
                         f"{sorted(PROCESS_STARTS)})")
    starts = sorted({h.get("started") for h in series_run_logs(directory)})
    if starts != [start]:
        raise SystemExit(f"--bot-commit {commit!r}: the run logs without a code started {starts}, not as its "
                         f"process ({start})")


def search_step(commit):
    """The ladder step of a bot commit (SEARCH_STEPS, by its first 8 characters); SystemExit for an unknown one."""
    step = SEARCH_STEPS.get(str(commit or "")[:8])
    if step is None:
        raise SystemExit(f"the live search of bot commit {commit!r} is unknown: SEARCH_STEPS names "
                         f"{sorted(SEARCH_STEPS)}")
    return step


def luck_all(directory, bot, root, checkpoint, checkpoint_sha256, foe_net, foe_net_sha256, labels=None, since=None,
             code=None, samples=None, bot_commit=None):
    """--luck over a log directory (#494, docs/benchmarks/2026-10-14-cts-luck/README.md): every battle log a replay
    follows (selected) valued by cts_luck.battle with the checkpoint's honest search (the bot's: its file pinned by
    checkpoint_sha256, the foe network by foe_net_sha256); the aggregates of luck_series, per opponent and team with
    labels, the battles the replay refuses by name. The search plays the settings of the series' bot commit (code, or
    bot_commit for logs that name none: then no battle may name one); the share of replayed decisions the bot decided
    otherwise is reported, and above SEARCH_DIFFERS_LIMIT (or with nothing compared) the result says report_blocked."""
    from duoforge_live import cts, cts_luck, data, pkmn_arena, policy as live_policy, search as live_search
    from duoforge_live.arena import provenance
    if pkmn_arena.sha256_of(checkpoint) != checkpoint_sha256:
        raise SystemExit(f"{checkpoint}: not the pinned checkpoint {checkpoint_sha256}")
    samples = cts_luck.SAMPLES if samples is None else samples
    if (code is None) == (bot_commit is None):
        raise SystemExit("--luck replays one bot commit's series: give --code, or --bot-commit for logs without a code")
    from duoforge_search import ladder
    if bot_commit is not None:
        check_bot_commit(directory, bot_commit)
    named = [h.get("search_settings") for h in series_run_logs(directory, code)]  # this series' run logs only
    if any(x is not None for x in named):  # the bot names its search in its run logs' head: that one, the same in all
        if any(x != named[0] for x in named):
            raise SystemExit(f"the run logs of {directory} name different search settings: not one series")
        settings, step = dict(named[0]), "run-log"
        known = SEARCH_STEPS.get(str(code if code is not None else bot_commit)[:8])
        if known is not None and ladder.step_settings(known) != settings:
            raise SystemExit(f"the run logs' search settings are not step {known}'s, which SEARCH_STEPS gives the commit")
    else:
        step = search_step(code if code is not None else bot_commit)
        settings = ladder.step_settings(step)
    tables = data.for_checkpoint(checkpoint)
    prior = cts.SetPrior.from_table(tables)
    net = live_policy.load(checkpoint)
    live = live_search.load(checkpoint, settings=settings, foe_net=foe_net, foe_net_sha256=foe_net_sha256)
    skipped, refused = collections.Counter(), collections.Counter()
    battles, per, per_team = [], collections.defaultdict(list), collections.defaultdict(list)
    try:
        live.searcher = cts.Capture(live.searcher)
        with cts_luck.Meter(live.searcher.searcher, samples) as meter:
            for path, records, team in selected(directory, bot, since, code, skipped):
                if bot_commit is not None and battle(records, bot)["code"]:
                    raise SystemExit("--bot-commit is for logs without a code: this series names its own")
                try:
                    out = cts_luck.battle(path, tables, net, live, team, bot, prior, meter)
                except cts.Refused as r:
                    refused[str(r).split(" ")[0]] += 1
                    continue
                battles.append(out)
                if labels is not None:
                    o = opponent(records, bot)
                    per[labels.get(o, "?")].append(out)
                    per_team[team_label(labels, o, foe_team(records, bot))].append(out)
    finally:
        live.close()
    engine_root = Path(cts.__file__).resolve().parents[2]
    searches = sum(b["searches"] for b in battles)
    differs = sum(b["search_differs"] for b in battles)
    share = differs / max(1, searches)
    return {**luck_series(battles), "skipped": dict(skipped), "refused_battles": dict(refused), "samples": samples,
            "search_step": step, "bot_commit": code if code is not None else bot_commit,
            "searches": searches, "search_differs": differs, "search_differs_share": share,
            "report_blocked": searches == 0 or share > SEARCH_DIFFERS_LIMIT,  # nothing compared blocks it too
            "checkpoint_sha256": checkpoint_sha256, "foe_net_sha256": foe_net_sha256,
            "engine_code": provenance(engine_root), "tool_code": provenance(root),
            **({} if labels is None else {"by_opponent": {k: luck_series(v) for k, v in sorted(per.items())},
                                          "by_team": {k: luck_series(v) for k, v in sorted(per_team.items())}})}

def _code_of(b):
    """A battle's bot commit (its log's code), "" when the log names none."""
    return str((b.get("code") or {}).get("commit") or "")


def _code_key(code):
    """A code as by_code counts it: the commit's first 8 characters, "+dirty" for a dirty checkout, "none"."""
    commit = str((code or {}).get("commit") or "")
    return (commit[:8] + ("+dirty" if (code or {}).get("dirty") else "")) if commit else "none"


def _in_series(code, prefix):
    """Whether a code belongs to the measurement series of a commit prefix: that commit, clean (a dirty run of the same
    commit ran other code)."""
    return bool(code) and str(code.get("commit") or "").startswith(prefix) and code.get("dirty") is False


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
    p.add_argument("--details", default=None,
                   help="--replay: a private JSON file (outside the repository) of each battle's refused points, its room "
                        "named: for a look at single battles, never for a report")
    p.add_argument("--code", default=None,
                   help="only the battles and run logs of a bot commit that starts with this (a measurement series)")
    p.add_argument("--replay", action="store_true",
                   help="replay the logs through the particles: the refused decision points and their content")
    p.add_argument("--luck", action="store_true",
                   help="the luck meter (#494): replay the logs with the bot's search and value each searched turn's "
                        "luck (needs --checkpoint and --checkpoint-sha256)")
    p.add_argument("--checkpoint", default=None, help="--luck: the bot's checkpoint (private, outside the repository)")
    p.add_argument("--checkpoint-sha256", default=None, help="--luck: the checkpoint's pin, checked before loading")
    p.add_argument("--samples", type=int, default=None, help="--luck: chance seeds per world (default: cts_luck.SAMPLES)")
    p.add_argument("--bot-commit", default=None,
                   help="--luck: the bot commit of a series whose logs name none (its search settings, SEARCH_STEPS)")
    from duoforge_live import search as live_search
    live_search.add_foe_net_arguments(p)
    args = p.parse_args(argv)
    if args.luck and (args.replay or args.details):
        raise SystemExit("--luck is its own replay: not with --replay or --details")
    if args.luck and not (args.checkpoint and args.checkpoint_sha256):
        raise SystemExit("--luck values with the bot's network: it needs --checkpoint and --checkpoint-sha256")
    if not args.luck and (args.checkpoint or args.checkpoint_sha256 or args.samples is not None or args.bot_commit):
        raise SystemExit("--checkpoint, --checkpoint-sha256, --samples and --bot-commit belong to --luck")
    live_search.check_foe_net_arguments(args, args.luck)
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
    by_code = dict(collections.Counter(_code_key(battle(records, bot)["code"]) for records in kept))
    if args.code is not None:
        kept = [records for records in kept if _in_series(battle(records, bot)["code"], args.code)]
    labels = None
    if args.labels:
        labels = assign_labels([o for o in (opponent(r, bot) for r in kept) if o], load_labels(args.labels))
        labels = assign_teams([(opponent(r, bot), foe_team(r, bot)) for r in kept if opponent(r, bot)], labels)
        save_labels(args.labels, labels)
    details = None
    if args.details:
        if not args.replay:
            raise SystemExit("--details is the replay's per-battle file: it needs --replay")
        refuse_repository(Path(args.details).parent)
        details = []
    if args.luck:
        result = {"since": args.since, "code_filter": args.code, "by_code": by_code,
                  **luck_all(args.logs, bot, ROOT, args.checkpoint, args.checkpoint_sha256,
                             live_search.foe_net_of(args), live_search.foe_net_sha256_of(args), labels, since,
                             args.code, args.samples, args.bot_commit)}
    elif args.replay:
        result = {"since": args.since, "code_filter": args.code, "by_code": by_code,
                  **replay_all(args.logs, bot, ROOT, labels, since, args.code, details)}
        if details is not None:
            Path(args.details).write_text(json.dumps(details, indent=1) + "\n", encoding="utf-8")
    else:
        battles, groups, teams = [], collections.defaultdict(list), collections.defaultdict(list)
        for records in kept:
            battles.append(battle(records, bot))
            if labels is not None:
                o = opponent(records, bot)
                groups[labels.get(o, "?")].append(battles[-1])
                teams[team_label(labels, o, foe_team(records, bot))].append(battles[-1])
        result = {"code": code, "since": args.since, "code_filter": args.code, "logs": len(logs), "kept": len(kept),
                  "by_code": by_code, **summarize(battles), "runs": run_logs(args.logs, args.since, args.code)}
        tested = [(b, labels.get(opponent(records, bot), "?") if labels is not None else "?", b["foe_lead"])
                  for records, b in zip(kept, battles) if b["arm"] is not None]
        if tested:  # the A/B test of the root rule: its battles by arm
            result["ab_root_rule"] = ab_arms(tested)
        if labels is not None:
            result["by_opponent"] = {k: summarize(v) for k, v in sorted(groups.items())}
            result["by_team"] = {k: summarize(v) for k, v in sorted(teams.items())}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
