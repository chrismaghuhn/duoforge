"""The live search's decision latency on closed-sheet streams (decision 0081, #385 step 4). Writes aggregates only.

    python tools/research/cts_search_latency.py dump --out STREAMS.json
    python tools/research/cts_search_latency.py dump-arena --logs DIR --out STREAMS.json
    python tools/research/cts_search_latency.py dump-local --arena DIR --out STREAMS.json
    python tools/research/cts_search_latency.py measure --streams STREAMS.json --checkpoint P --foe-net P --out DIR
        [--warmup STREAMS.json] [--arm closed|open|oracle] [--count 128] [--seed S]
    python tools/research/cts_search_latency.py compare DIR/choices-closed.json DIR/choices-oracle.json

dump (no JAX; node and the pinned Showdown checkout as the reference tests need them): every committed pool battle's
client stream of each player, as the pinned simulator sends it, in its batches, with the player's team and the choice it
made at each decision point. Only battles the runner played under the pool tables' own kind (no DEV fallback): the live
search reads records of that kind. Artificial pool teams: a stress case.

dump-arena: the bot's battle logs of real closed-sheet battles on PKMN Arena (private: they hold match and user ids)
that the bot answered with /choose default before the particles. A log of that time keeps no batches: each batch is
taken to end at a request line, where the bot answered. The own team is the one registry team (data/teams) the first
request matches (pkmn_arena.request_matches); a log matching none or several is skipped and counted. The team-preview
choice is read off the next request (its first four members, leads first); the turns' choices stay unknown (the server
chose them). The battles get anonymous keys (arena-<k>): STREAMS.json holds no id, and lies outside the repository.

dump-local: the search bot's games of a local closed-sheet arena (python -m duoforge_live.arena --closed: DIR/games.json
and DIR/logs, private), each as the events the bot's game took: every batch as fed and every accepted choice, in order
(the bot's log keeps them), with the own team and the foe's true team (the registry's pastes of the game's ids). Battles
get anonymous keys (local-<k>).

measure (JAX: the live search as python -m duoforge_live --search honest loads it, with its pinned foe network): COUNT
streams drawn by SEED (all of them when COUNT is larger), played as the live bot plays them. arm "closed" removes any
|showteam| line and plays over the particles (game.Game.closed_sheets, 16 particles, the committed set table); arm "open"
plays the stream as it is (game.Game), for comparison; arm "oracle" plays a closed stream with both true open sheets
put in after its team-preview request (a stream with the foe's true team: dump-local), as the particles put in theirs:
the v1 bias's upper bound.
Each arm writes the choice it played at every decision point (DIR/choices-<arm>.json, keyed by battle and epoch);
compare gives the share of decision points where closed and oracle play the same choice, by decision kind.
 Timed at each decision point where the player is asked:
- decision: game.candidates(), from the particles' encoding to the ranked choices, with no deadline (BUDGET), so the
  distribution is the search's own;
- complete: the feed of the batch that completed the decision point (the particles' redraws and checks) plus decision.
Then the stream's own choice is accepted where it is known. A batch that ends the battle (|win|, |tie) is not fed, as
the bot ends the battle there. Warm-up first (WARMUP, not counted): streams of --warmup
(default: --streams) until a team preview and a searched decision have run, as JAX compiles each input shape on its
first call; a counted decision during which the search compiled anyway is left out and counted ("compiled"). Tracker
stops and errors end a stream and are counted by name.

DIR/latency-<arm>.json: per decision kind (team_selection, turn, switch) and for the searched decisions n, p50, p95, p99
and max seconds of decision and complete; the outcome causes and fallback classes; the feed quantiles per batch; stops
and errors by name; the particle counters (cts.counter_kind); the settings. Run it alone on the machine
(tools/ci/machine_lock.sh --exclusive).
"""
import argparse
import collections
import glob
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))

BUDGET = 600.0  # seconds: no deadline during the measurement
SEED = 0x2026101300000400
WARMUP = 8  # streams at most for the warm-up


def _refuse_repository(path):
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(path)


def dump(args):
    _refuse_repository(Path(args.out).parent)
    from python.tests.live.test_live import Reference, record_kind
    pool = Reference.get().pool()
    out, skipped = [], collections.Counter()
    for battle in pool.battles:
        if record_kind(battle.name) is not None:
            skipped["dev_kind"] += 1
            continue
        steps = battle.trace["steps"]
        for player in (0, 1):
            seat = f"p{player + 1}"
            inputs = [step["input"].get(seat) for step in steps]
            out.append({"battle": battle.name, "player": player, "team": battle.spec["teams"][player],
                        "messages": battle.streams[player], "inputs": inputs})
    Path(args.out).write_text(json.dumps({"streams": out, "skipped": dict(skipped)}), encoding="utf-8")
    print(f"{len(out)} streams, skipped {dict(skipped)}")


def _request(line):
    return json.loads(line[len("|request|"):]) if line.startswith("|request|") else None


def dump_arena(args):
    _refuse_repository(Path(args.out).parent)
    from duoforge_live import data, pkmn_arena
    root = data.ROOT / "data" / "teams"
    pastes = [(root / (t["id"] + ".txt")).read_text(encoding="utf-8")
              for t in json.loads((root / "index.json").read_text(encoding="utf-8"))["teams"]]
    out, skipped = [], collections.Counter()
    for k, path in enumerate(sorted(glob.glob(str(Path(args.logs) / "battle-*.jsonl")))):
        lines = [r["in"] for r in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if "in" in r]
        batches, batch = [], []
        for line in lines:
            batch.append(line)
            if line.startswith("|request|"):
                batches.append(batch)
                batch = []
        if batch:
            batches.append(batch)
        requests = [r for r in map(_request, lines) if r is not None]
        if not requests or not requests[0].get("teamPreview") or len(requests) < 2:
            skipped["no_team_preview"] += 1
            continue
        found = [p for p in pastes if pkmn_arena.request_matches(requests[0]["side"]["pokemon"], p)]
        if len(found) != 1:
            skipped["team_unknown" if not found else "team_ambiguous"] += 1
            continue
        preview = [p["ident"] for p in requests[0]["side"]["pokemon"]]
        brought = [p["ident"] for p in requests[1]["side"]["pokemon"]][:requests[0]["maxChosenTeamSize"]]
        player = int(requests[0]["side"]["id"][1]) - 1
        out.append({"battle": f"arena-{k}", "player": player, "team": found[0], "messages": batches,
                    "inputs": ["team " + "".join(str(preview.index(i) + 1) for i in brought)]})
    Path(args.out).write_text(json.dumps({"streams": out, "skipped": dict(skipped)}), encoding="utf-8")
    print(f"{len(out)} streams, skipped {dict(skipped)}")


def dump_local(args):
    _refuse_repository(Path(args.out).parent)
    from duoforge_live import data
    games = json.loads((Path(args.arena) / "games.json").read_text(encoding="utf-8"))
    root = data.ROOT / "data" / "teams"
    out, skipped = [], collections.Counter()
    for k, g in enumerate(games):
        if g.get("result") not in ("win", "loss", "tie") or not g.get("room"):
            skipped["not_played"] += 1
            continue
        logs = sorted((Path(args.arena) / "logs").glob(f"{g['room']}-*sbot.jsonl"))
        if len(logs) != 1:
            skipped["no_search_log"] += 1
            continue
        events = []
        for r in map(json.loads, logs[0].read_text(encoding="utf-8").splitlines()):
            if "feed" in r:
                events.append(["feed", r["feed"]])
            elif "accepted" in r:
                events.append(["accepted", r["accepted"]])
        own, foe = ((root / f"{g[key]}.txt").read_text(encoding="utf-8") for key in ("search_team", "raw_team"))
        out.append({"battle": f"local-{k}", "player": None, "team": own, "foe_team": foe, "events": events})
    Path(args.out).write_text(json.dumps({"streams": out, "skipped": dict(skipped)}), encoding="utf-8")
    print(f"{len(out)} streams, skipped {dict(skipped)}")


def _with_sheets(lines, own, foe):
    """A batch with both true open sheets put in right after its team-preview request (the oracle arm), as
    cts.ParticleTracker puts in a particle's: the foe's true team in the particles' form (cts.true_sheet: no stat
    points, as the server shows it; review of #385 step 5)."""
    from duoforge_live import cts, teams
    for i, line in enumerate(lines):
        side = cts._preview_side(line)
        if side is not None:  # the own sheet as the particles put it in, the foe's as the server shows it (no EVs)
            packed = (teams.pack(own), cts.true_sheet(foe))
            sheets = [f"|showteam|p{s + 1}|" + (packed[0] if s == side else packed[1]) for s in (0, 1)]
            return lines[:i + 1] + sheets + lines[i + 1:]
    return lines


def compare(args):
    """The share of decision points where the two arms play the same choice, by kind (aggregates only)."""
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.first, args.second))
    common = sorted(set(a) & set(b))
    by_kind = collections.defaultdict(lambda: [0, 0])
    for key in common:
        kind = a[key][0]
        by_kind[kind][1] += 1
        by_kind[kind][0] += a[key][1] == b[key][1]
    out = {"common": len(common), "only_first": len(set(a) - set(b)), "only_second": len(set(b) - set(a)),
           "agree": {k: {"same": s, "of": n, "share": s / n} for k, (s, n) in sorted(by_kind.items())}}
    same, n = sum(s for s, _ in by_kind.values()), sum(n for _, n in by_kind.values())
    out["agree"]["all"] = {"same": same, "of": n, "share": same / max(1, n)}
    print(json.dumps(out, indent=1))


def _quantiles(seconds):
    import numpy as np
    if not seconds:
        return {"n": 0}
    s = np.asarray(seconds, dtype=np.float64)
    p50, p95, p99 = (float(np.quantile(s, q, method="higher")) for q in (0.50, 0.95, 0.99))
    return {"n": int(s.size), "p50": p50, "p95": p95, "p99": p99, "max": float(s.max())}


def _kind(request):
    if request.get("teamPreview"):
        return "team_selection"
    return "switch" if request.get("forceSwitch") else "turn"


def _drawn(streams, count, seed):
    """COUNT streams by the SHA-256 of (seed, battle, player): a pure function of the dump and the seed."""
    def rank(s):
        return hashlib.sha256(f"{seed}|{s['battle']}|{s['player']}".encode()).hexdigest()
    return sorted(streams, key=rank)[:count]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _Play:
    """Plays streams as the live bot does and keeps the timings of the counted ones."""

    def __init__(self, arm, tables, net, live, prior, detail=False):
        self.arm, self.tables, self.net, self.live, self.prior = arm, tables, net, live, prior
        self.detail, self.details = detail, collections.Counter()
        self.decision, self.complete = collections.defaultdict(list), collections.defaultdict(list)
        self.feed = []
        self.causes, self.fallback, self.stops, self.errors, self.counters, self.skipped, self.reasons = \
            (collections.Counter() for _ in range(7))
        self.episode = 0
        self.seen = set()  # warm-up: the decision kinds the search has compiled for (team, searched)
        self.choices = {}  # "battle|epoch" -> (kind, the choice played), of the counted decision points

    def compiled(self):
        return len(getattr(self.live.searcher, "_compiled", ()))

    def stream(self, s, counted):
        from duoforge_live import cts, game, lines
        if "events" in s:  # the bot's own events (dump-local): every batch as fed, every accepted choice
            events = [tuple(e) for e in s["events"]]
        else:
            events = [("feed", m) for m in s["messages"]]
        # a stream without the foe's true team (the warm-up's pool streams) plays the oracle arm as it is: open sheets
        oracle = self.arm == "oracle" and "foe_team" in s
        if self.arm == "closed" or oracle:
            events = [(k, [line for line in p if not line.startswith("|showteam|")] if k == "feed" else p)
                      for k, p in events]
        if oracle:
            events = [(k, _with_sheets(p, s["team"], s["foe_team"]) if k == "feed" else p) for k, p in events]
        if self.arm == "closed":
            g = game.Game.closed_sheets(self.tables, self.net, s["team"], self.prior, search=self.live,
                                        room=s["battle"], episode=self.episode)
        else:
            g = game.Game(self.tables, self.net, s["team"], search=self.live, room=s["battle"], episode=self.episode)
        self.episode += 1
        done = 0
        try:
            for k, m in events:
                if k == "accepted":
                    g.accepted(m)
                    continue
                if any(line.startswith("|win|") or line == "|tie" or line.startswith("|tie|") for line in m):
                    break  # the battle is over: the bot ends it without feeding the batch (pkmn_arena._end)
                start = time.perf_counter()
                g.feed(m)
                fed = time.perf_counter() - start
                if counted:
                    self.feed.append(fed)
                if not (g.ready and g.epoch > done):
                    continue
                done = g.epoch
                if g.asked():
                    before, compiled = len(g.outcomes), self.compiled()
                    start = time.perf_counter()
                    ranked = g.candidates(BUDGET)
                    seconds = time.perf_counter() - start
                    if counted:
                        self.choices[f"{s['battle']}|{g.epoch}"] = (_kind(g.request), ranked[0].text)
                    outcome = g.outcomes[-1] if len(g.outcomes) > before else None
                    if outcome is not None:
                        self.seen.add(outcome.cause)
                    if counted and self.compiled() > compiled:
                        self.skipped["compiled"] += 1
                    elif counted:
                        kind = _kind(g.request)
                        self.decision[kind].append(seconds)
                        self.complete[kind].append(fed + seconds)
                        if outcome is not None:
                            self.causes[outcome.cause] += 1
                            if outcome.fallback is not None:
                                self.fallback[outcome.fallback] += 1
                                self.reasons[str(outcome.reason)[:160]] += 1  # the named reason, the tracker's beside the search's
                            if outcome.cause == "searched":
                                self.decision["searched"].append(seconds)
                                self.complete["searched"].append(fed + seconds)
                if "events" in s:
                    continue  # the accepted choices are events of their own
                choice = s["inputs"][done - 1] if done - 1 < len(s["inputs"]) else None
                if choice is not None:
                    g.accepted(choice)
        except lines.Stop as stop:
            if counted:
                self.stops[stop.reason.split(" ")[0] if stop.reason.startswith("cts:") else stop.reason.split(":")[0]] += 1
                if self.detail:
                    self.details[f"stop {stop.reason}"[:120]] += 1
        except ValueError as err:
            if counted:
                self.errors[type(err).__name__] += 1
                if self.detail:  # the stream's own text, only for streams that hold no private name (--detail)
                    self.details[f"{type(err).__name__}: {err}"[:120]] += 1
        if counted and g.closed:
            for key, n in g.tracker.counters.items():
                self.counters[cts.counter_kind(key)] += n


def measure(args):
    _refuse_repository(args.out)
    from duoforge_live.arena import provenance
    code = provenance(ROOT)  # the commit and dirty state, named in the report (never None)
    from duoforge_live import cts, data, policy, search as live_search
    streams = json.loads(Path(args.streams).read_text(encoding="utf-8"))["streams"]
    warmup = json.loads(Path(args.warmup or args.streams).read_text(encoding="utf-8"))["streams"]
    drawn = _drawn(streams, args.count, args.seed)
    tables = data.for_checkpoint(args.checkpoint)
    net = policy.load(args.checkpoint)
    foe_sha = args.foe_net_sha256 or live_search.FOE_NET_SHA256
    live = live_search.load(args.checkpoint, foe_net=args.foe_net, foe_net_sha256=foe_sha)
    prior = cts.SetPrior.from_table(tables) if args.arm == "closed" else None
    play = _Play(args.arm, tables, net, live, prior, args.detail)
    try:
        warmed = 0
        for s in _drawn(warmup, WARMUP, args.seed + 1):
            if {"team", "searched"} <= play.seen:
                break
            play.stream(s, counted=False)
            warmed += 1
        if not {"team", "searched"} <= play.seen:
            raise SystemExit(f"the warm-up met no team preview and searched decision in {warmed} streams")
        for s in drawn:
            play.stream(s, counted=True)
    finally:
        live.close()
    every = [x for k, v in play.decision.items() if k != "searched" for x in v]
    every_complete = [x for k, v in play.complete.items() if k != "searched" for x in v]
    report = {
        "arm": args.arm, "streams": len(drawn), "warmup_streams": warmed, "seed": args.seed, "code": code,
        "decision": {**{k: _quantiles(v) for k, v in sorted(play.decision.items())}, "all": _quantiles(every)},
        "complete": {**{k: _quantiles(v) for k, v in sorted(play.complete.items())}, "all": _quantiles(every_complete)},
        "feed": _quantiles(play.feed), "causes": dict(play.causes), "fallback": dict(play.fallback),
        "stops": dict(play.stops), "errors": dict(play.errors), "left_out": dict(play.skipped), "reasons": dict(play.reasons), "details": dict(play.details),
        "particle_counters": dict(play.counters),
        "settings": {"search": live_search.HONEST_SETTINGS, "particles": cts.PARTICLES if args.arm == "closed" else None,
                     "checkpoint_sha256": _sha256(args.checkpoint), "foe_net_sha256": foe_sha,
                     "machine": platform.platform(), "python": platform.python_version()}}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"choices-{args.arm}.json").write_text(json.dumps(play.choices) + "\n", encoding="utf-8")
    (out / f"latency-{args.arm}.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("decision", "complete", "causes", "stops", "errors", "left_out")}, indent=1))


def main(argv=None):
    p = argparse.ArgumentParser(prog="cts_search_latency.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    a = sub.add_parser("dump-arena")
    a.add_argument("--logs", required=True)
    a.add_argument("--out", required=True)
    loc = sub.add_parser("dump-local")
    loc.add_argument("--arena", required=True)
    loc.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("first")
    c.add_argument("second")
    m = sub.add_parser("measure")
    m.add_argument("--streams", required=True)
    m.add_argument("--warmup", default=None)
    m.add_argument("--checkpoint", required=True)
    m.add_argument("--foe-net", required=True)
    m.add_argument("--foe-net-sha256", default=None)
    m.add_argument("--out", required=True)
    m.add_argument("--arm", choices=("closed", "open", "oracle"), default="closed")
    m.add_argument("--count", type=int, default=128)
    m.add_argument("--seed", type=int, default=SEED)
    m.add_argument("--detail", action="store_true",
                   help="also count the stops' and errors' own texts (never for streams with private names)")
    args = p.parse_args(argv)
    {"dump": dump, "dump-arena": dump_arena, "dump-local": dump_local, "measure": measure,
     "compare": compare}[args.command](args)


if __name__ == "__main__":
    main()
