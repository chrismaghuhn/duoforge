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

--replay also counts the risky choices (owner, via the HauptSession, 2026-10-14): a searched decision (the bot's log
record: search cause "searched") whose played pair the network gave less than RISKY. The bot logs each decision's
candidates with the network's raw probability (the mean over the particles); a searched decision's first candidate is
the search's pair, so its probability is read from the log, never recomputed. What follows a searched decision, risky or
not: the material balance (material(): the own side's alive members and HP fractions minus the foe's, from the
tracker's observation) at the first decision point 1 and 2 turns later, its change against the decision point; a
battle that ended before is counted as ended, one without a point at that turn as missing. And the results of the
battles with a risky choice and of those with searched decisions but none. Per opponent and team with --labels, per
bot commit always.
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

RISKY = 0.05  # a searched pair the network gave less than this is a risky choice (owner, 2026-10-14)
AFTER = (1, 2)  # the turns after a searched decision whose material balance is compared



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
           "dirty": False, "fallback": None, "stop": None, "seconds": [], "start": None, "code": None}
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
        elif "log_format" in r and r.get("code"):
            out["code"] = r["code"]  # the bot's commit and dirty state, in every battle's first record (format 2)
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


def material(observation):
    """(alive, hp): the viewer's side minus the foe's, from a tracker observation (layout OBSERVATION). A side's brought
    members (location active or bench) count: alive those above 0 HP, hp the sum of their HP fractions (the foe's in
    percent, as shown). A foe member not seen yet counts whole: the foe brings as many as the viewer (VGC, 4 of 6)."""
    from duoforge import _layout
    C = _layout.CONSTANTS
    seen = (C["DUOFORGE_LOCATION_BENCH"], C["DUOFORGE_LOCATION_ACTIVE"])
    out, brought = [], None
    for side in (int(observation["player"]), 1 - int(observation["player"])):
        alive, hp, n = 0, 0.0, 0
        for m in observation["sides"][side]["members"]:
            if int(m["location"]) not in seen:
                continue
            n += 1
            alive += int(m["hp"]) > 0
            hp += int(m["hp"]) / int(m["hp_max"]) if int(m["hp_max"]) else 0.0
        if brought is None:
            brought = n
        else:
            unseen = max(0, brought - n)
            alive, hp = alive + unseen, hp + unseen
        out.append((alive, hp))
    return out[0][0] - out[1][0], out[0][1] - out[1][1]


def searched_choice(record):
    """(the network's probability of the searched pair, its text) of a decision's log record, None for a decision the
    search did not decide (another cause, no record, no candidates)."""
    if not record or (record.get("search") or {}).get("cause") != "searched" or not record.get("top"):
        return None
    text, p = record["top"][0]
    if text != record.get("sent"):  # the first candidate is the one sent first: anything else is no search's pair
        raise ValueError(f"a searched decision sent {record.get('sent')!r}, not its first candidate {text!r}")
    return float(p), text


def follow(points):
    """The searched points of a battle with what followed: [{"risky", "p", "after": {k: (d alive, d hp) or "ended" or
    "missing"}}], k in AFTER; points: [{"turn", "material", "choice"}] in order."""
    out = []
    for i, point in enumerate(points):
        if point["choice"] is None:
            continue
        after = {}
        for k in AFTER:
            later = next((q for q in points[i + 1:] if q["turn"] >= point["turn"] + k), None)
            if later is None:
                after[k] = "ended"
            elif later["turn"] != point["turn"] + k:
                after[k] = "missing"
            else:
                after[k] = tuple(b - a for a, b in zip(point["material"], later["material"]))
        out.append({"risky": point["choice"][0] < RISKY, "p": point["choice"][0], "after": after})
    return out


def risk_summary(battles):
    """The risky-choice aggregates over [(result, follow())] of battles."""
    def group(choices):
        g = {"n": len(choices)}
        for k in AFTER:
            known = [c["after"][k] for c in choices if isinstance(c["after"][k], tuple)]
            g[f"after_{k}"] = {"n": len(known), "ended": sum(c["after"][k] == "ended" for c in choices),
                               "missing": sum(c["after"][k] == "missing" for c in choices),
                               "alive_mean": sum(a for a, _ in known) / len(known) if known else None,
                               "hp_mean": sum(h for _, h in known) / len(known) if known else None}
        return g
    choices = [c for _, cs in battles for c in cs]
    risky = [c for c in choices if c["risky"]]
    with_risky = collections.Counter(r for r, cs in battles if any(c["risky"] for c in cs))
    without = collections.Counter(r for r, cs in battles if cs and not any(c["risky"] for c in cs))
    return {"threshold": RISKY, "searched": len(choices), "risky": len(risky),
            "risky_share": len(risky) / len(choices) if choices else None,
            "risky_after": group(risky), "other_after": group([c for c in choices if not c["risky"]]),
            "battles_with_risky": dict(with_risky), "battles_searched_without_risky": dict(without)}


def replay(records, tables, prior, team, room, names):
    """One battle log replayed through the particles: {"points", "refused": [the content per refused particle, per
    refused point], "stopped": None or the named reason the replay ended with}. What the bot's own fold catches ends
    the replay by name, as the bot's battle fell back there."""
    from duoforge_live import cts
    own = set().union(*(held(s, names, tables) for s in teams_sets(team)))
    out = {"points": 0, "refused": [], "stopped": None}
    replayed = cts.LogReplay(records, tables, None, team, prior, room)  # the one replay core (Search's ko_check too)
    points = []
    for game, record in replayed:
        t = game.tracker
        if t.request.get("teamPreview"):
            continue
        out["points"] += 1
        observation = t.observations()[0]  # the public HP and locations are every particle's
        points.append({"turn": int(observation["turn"]), "material": material(observation),
                       "choice": searched_choice(record)})
        bad = [i for i, p in enumerate(t.public_parts()) if p["reason"] == ENGINE_REFUSES]
        if bad:  # a refused particle holding no foe content is put on the own team's, when that has any
            out["refused"].append([sorted(set().union(*(held(s, names, tables) for s in t.particles[i].sets))
                                          or {"own:" + c for c in own}) for i in bad])
    # the replay's own stop or failure, else the bot's named fallback; a failure of this tool (public_parts, held)
    # propagates and ends --replay: it is no fallback of the bot
    out["stopped"] = replayed.stopped
    out["diverged"] = replayed.diverged
    out["choices"] = follow(points)
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


def replay_all(directory, bot, root, labels=None, since=None, code=None, details=None):
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
    per_team = collections.defaultdict(lambda: {"battles": 0, "points": 0, "refused": 0})
    occurs, alone = collections.Counter(), collections.Counter()
    risks = collections.defaultdict(list)  # group -> [(result, follow())] of its battles
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
        out = replay(records, tables, prior, team[0], cts.room_of_log(path, bot), names)
        points += out["points"]
        groups = ["all", "code:" + _code_key(battle(records, bot)["code"])]
        if labels is not None:
            o = opponent(records, bot)
            groups += ["opponent:" + labels.get(o, "?"), "team:" + team_label(labels, o, foe_team(records, bot))]
        for g in groups:
            risks[g].append((battle(records, bot)["result"], out["choices"]))
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
            "risky": {g: risk_summary(b) for g, b in sorted(risks.items())},
            **({} if labels is None else {
                "by_opponent": {k: {**v, "searchable_share": 1.0 - v["refused"] / max(1, v["points"])}
                                for k, v in sorted(per.items())},
                "by_team": {k: {**v, "searchable_share": 1.0 - v["refused"] / max(1, v["points"])}
                            for k, v in sorted(per_team.items())}})}


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
    if args.replay:
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
        if labels is not None:
            result["by_opponent"] = {k: summarize(v) for k, v in sorted(groups.items())}
            result["by_team"] = {k: summarize(v) for k, v in sorted(teams.items())}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
