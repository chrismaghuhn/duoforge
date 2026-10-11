"""The live-path arena (issue #362; plan 2026-10-10-live-honest-search, Task 6): the live search against raw play, both
through the real live client, on a local copy of the pinned Showdown server.

    python -m duoforge_live.arena --checkpoint P --out DIR [--games 400] [--lanes 2] [--server-dir PATH]

Every pair of games draws two teams of the checkpoint's pool (its config's team ids) and plays them twice with the
seats' teams swapped: the search bot ("--search honest") against the raw bot, both the same network. The battle timer is
on, so the search's budget comes from the server's timer lines. Each lane is one search bot and one raw bot; the raw
bot challenges, the search bot accepts. The server is started with --no-security (guests need no login server).

The gates are predeclared (owner, 2026-10-10/11): the search bot's score has a 95% lower bound above 0.50 (over the
pairs' mean scores), no crash (an internal-error forfeit or a lane that fails), no class (b) error, raw fallbacks (a) at
most 5% of the search's decisions, deadline misses at most 1%, tracker stops at most 1% of the games, no timer loss,
and the search's p99 decision time within the 2 s cap. Logs and results stay in DIR, outside the repository: they
hold match ids (AGENTS.md); a report quotes aggregates only.
"""
import argparse
import asyncio
import json
import math
import random
import statistics
import subprocess
import time
from pathlib import Path

FORMAT = "gen9championsvgc2026regmc"
GATES = {"lower_bound": 0.50, "crashes": 0, "class_b": 0, "raw_fallback_share": 0.05, "deadline_share": 0.01,
         "tracker_stop_share": 0.01, "timer_losses": 0, "p99_seconds": 2.0}
START_WAIT = 60.0  # seconds for a challenge to open its battle room
GAME_WAIT = 1800.0  # seconds a game may take


def draw_pairs(ids, pairs, seed):
    """[(team of the search bot in the pair's first game, the raw bot's)]: a pure function of the ids and seed."""
    r = random.Random(seed)
    out = []
    while len(out) < pairs:
        a, b = r.choice(ids), r.choice(ids)
        if a != b:
            out.append((a, b))
    return out


def schedule(team_pairs):
    """[(pair, game, search team, raw team)]: each pair twice, the seats' teams swapped."""
    return [(k, g, *(pair if g == 0 else pair[::-1])) for k, pair in enumerate(team_pairs) for g in (0, 1)]


def read_game(log_path, search_name):
    """The search bot's view of one game from its private log."""
    out = {"result": None, "summary": None, "forfeit": None, "dirty": None, "timer_loss": False, "seconds": []}
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        text = r.get("in", "")
        if text.startswith("|win|"):
            out["result"] = "win" if "".join(ch for ch in text[5:].lower() if ch.isalnum()) == search_name else "loss"
        elif text == "|tie" or text.startswith("|tie|"):
            out["result"] = "tie"
        elif "lost due to inactivity" in text:
            out["timer_loss"] = True
        if "summary" in r:
            out["summary"] = r["summary"]
        if "forfeit" in r:
            out["forfeit"] = r["forfeit"]
        if "dirty" in r:
            out["dirty"] = r["dirty"]
        if r.get("search") and r["search"].get("cause") not in ("team",):
            out["seconds"].append(float(r["search"]["seconds"]))
    return out


def evaluate(games):
    """The gates over the played games (records of play_game with the raw bot's forfeit added)."""
    played = [g for g in games if g.get("result") in ("win", "loss", "tie")]
    score = {"win": 1.0, "tie": 0.5, "loss": 0.0}
    by_pair = {}
    for g in played:
        by_pair.setdefault(g["pair"], []).append(score[g["result"]])
    means = [statistics.fmean(v) for v in by_pair.values() if len(v) == 2]
    mean = statistics.fmean(means) if means else float("nan")
    half = 1.96 * statistics.stdev(means) / math.sqrt(len(means)) if len(means) > 1 else float("inf")
    decisions = fallback_a = deadline = 0
    seconds = []
    for g in played:
        s = g.get("summary") or {}
        causes = s.get("causes", {})
        decisions += sum(n for c, n in causes.items() if c not in ("team", "dirty"))
        fallback_a += s.get("fallback", {}).get("a", 0)
        deadline += s.get("fallback", {}).get("deadline", 0)
        seconds += g.get("seconds", [])
    stops = sum(1 for g in games for f in (g.get("forfeit"), g.get("raw_forfeit")) if f and f.startswith("stop:"))
    crashes = sum(1 for g in games for f in (g.get("forfeit"), g.get("raw_forfeit"))
                  if f and not f.startswith("stop:") and "sheets" not in f) + sum(1 for g in games if g.get("crash"))
    out = {
        "games": len(games), "played": len(played), "pairs": len(means), "score": mean,
        "lower_bound": mean - half, "upper_bound": mean + half,
        "decisions": decisions, "raw_fallback_share": fallback_a / max(1, decisions),
        "deadline_share": deadline / max(1, decisions),
        "tracker_stops": stops, "tracker_stop_share": stops / max(1, len(games)),
        "crashes": crashes, "class_b": sum(1 for g in games if g.get("dirty")),
        "timer_losses": sum(1 for g in games if g.get("timer_loss")),
        "p99_seconds": float(sorted(seconds)[min(len(seconds) - 1, int(0.99 * len(seconds)))]) if seconds else 0.0,
        "not_started": sum(1 for g in games if g.get("result") == "not_started"),
    }
    out["gates"] = {
        "lower_bound": out["lower_bound"] > GATES["lower_bound"],
        "crashes": out["crashes"] <= GATES["crashes"], "class_b": out["class_b"] <= GATES["class_b"],
        "raw_fallback_share": out["raw_fallback_share"] <= GATES["raw_fallback_share"],
        "deadline_share": out["deadline_share"] <= GATES["deadline_share"],
        "tracker_stop_share": out["tracker_stop_share"] <= GATES["tracker_stop_share"],
        "timer_losses": out["timer_losses"] <= GATES["timer_losses"],
        "p99_seconds": out["p99_seconds"] <= GATES["p99_seconds"],
        "all_played": out["not_started"] == 0}
    out["pass"] = all(out["gates"].values())
    return out


async def _until(predicate, timeout, step=0.2):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            return False
        await asyncio.sleep(step)
    return True


async def play_game(search_bot, raw_bot, search_text, raw_text, record):
    """One game: the raw bot challenges the search bot with the given teams; fills record."""
    from . import client, teams
    search_bot.team_texts = {"own": search_text, "foe": raw_text}
    raw_bot.team_texts = {"own": raw_text, "foe": search_text}
    before = set(search_bot.finished) | set(search_bot.battles)
    raw_bot.busy = {"user": client.toid(search_bot.config.name), "format": FORMAT, "games": 1, "team": "own",
                    "since": raw_bot.clock(), "room": False}
    await raw_bot.send("|/utm " + teams.pack(raw_text))
    await raw_bot.send(f"|/challenge {search_bot.config.name}, {FORMAT}")
    if not await _until(lambda: set(search_bot.battles) - before, START_WAIT):
        record["result"] = "not_started"
        record["reason"] = "paused" if search_bot.paused else "no battle room"
        raw_bot.busy = None
        await raw_bot.send("|/cancelchallenge " + client.toid(search_bot.config.name))
        return
    room = next(iter(set(search_bot.battles) - before))
    record["room"] = room
    await search_bot.send(f"{room}|/timer on")
    if not await _until(lambda: room in search_bot.finished and room not in raw_bot.battles, GAME_WAIT):
        record["result"] = "not_finished"
        return
    record.update(read_game(Path(search_bot.config.log_dir) / f"{room}-{client.toid(search_bot.config.name)}.jsonl",
                            client.toid(search_bot.config.name)))
    raw_log = Path(raw_bot.config.log_dir) / f"{room}-{client.toid(raw_bot.config.name)}.jsonl"
    record["raw_forfeit"] = read_game(raw_log, "")["forfeit"] if raw_log.exists() else None


async def run_lane(lane, games, make_bots, out_records):
    search_bot, raw_bot = make_bots(lane)
    tasks = [asyncio.create_task(search_bot.run()), asyncio.create_task(raw_bot.run())]
    try:
        if not await _until(lambda: search_bot.named and raw_bot.named, 60):
            raise RuntimeError(f"lane {lane}: the bots did not log in")
        for k, g, s_team, r_team in games:
            record = {"lane": lane, "pair": k, "game": g, "search_team": s_team, "raw_team": r_team}
            texts = make_bots.texts
            try:
                await play_game(search_bot, raw_bot, texts[s_team], texts[r_team], record)
            except Exception as err:  # a crash of the lane: counted, the lane goes on with its next game
                record["crash"] = f"{type(err).__name__}: {err}"
            out_records.append(record)
            make_bots.progress(record)
            if search_bot.paused:  # a class (b) error: the session takes no new challenge (by design)
                break
    finally:
        for t in tasks:
            t.cancel()
        search_bot.close()
        raw_bot.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_live.arena", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--games", type=int, default=400)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="localhost", help="the server's host (from WSL: the Windows host's address)")
    p.add_argument("--seed", type=int, default=0x2026101200000362)
    p.add_argument("--server-dir", default=None, help="a pinned Showdown checkout to start with --no-security")
    args = p.parse_args(argv)
    if args.games % 2 or args.games < 2:
        raise SystemExit("the arena plays pairs: --games must be even")
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    from duoforge_learn import checkpoint
    from . import client, data, policy, search
    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    _, config = checkpoint.load(args.checkpoint)
    ids = list(config["teams"]["ids"])
    games = schedule(draw_pairs(ids, args.games // 2, args.seed))
    root = Path(__file__).resolve().parents[2] / "data" / "teams"
    texts = {t: (root / f"{t}.txt").read_text(encoding="utf-8") for t in {x for g in games for x in g[2:]}}
    server = None
    if args.server_dir:
        server = subprocess.Popen(["node", "pokemon-showdown", "start", "--no-security", str(args.port)],
                                  cwd=args.server_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(15)
    url = f"ws://{args.host}:{args.port}/showdown/websocket"
    tables = data.load(kind=policy.table_kind(config))
    net = policy.load(args.checkpoint)
    records, start = [], time.monotonic()

    def make_bots(lane):
        def bot(role, live):
            cfg = client.Config(name=f"dfarena{lane}{role}bot", team="own", log_dir=str(out / "logs"),
                                team_link=None, server=url)
            return client.Bot(cfg, tables, net, login=lambda *a: "", search=live, team_texts={"own": ""})
        return bot("s", search.load(args.checkpoint)), bot("r", None)

    def progress(record):
        done = len(records)
        if done % 10 == 0:
            print(f"arena: {done}/{len(games)} games, {time.monotonic() - start:.0f} s", flush=True)
            (out / "games.json").write_text(json.dumps(records, indent=1), encoding="utf-8")

    make_bots.texts, make_bots.progress = texts, progress
    lanes = [games[i::args.lanes] for i in range(args.lanes)]

    async def everything():
        await asyncio.gather(*(run_lane(i, lane, make_bots, records) for i, lane in enumerate(lanes)))

    try:
        asyncio.run(everything())
    finally:
        if server is not None:
            server.terminate()
    report = {"checkpoint_config_teams": len(ids), "seed": args.seed, "games_planned": len(games),
              "lanes": args.lanes, "seconds": time.monotonic() - start, **evaluate(records)}
    (out / "games.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    (out / "arena.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "gates"}, indent=1), json.dumps(report["gates"]))
    return report


if __name__ == "__main__":
    main()
