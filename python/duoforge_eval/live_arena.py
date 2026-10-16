"""The live-path arena's entry point (moved from duoforge_live.arena, restructure step 8): the live search against raw
play, both through the real live client, on a local copy of the pinned Showdown server.

    python -m duoforge_eval.live_arena --checkpoint P --out DIR [--games 400] [--lanes 2] [--server-dir PATH] [--closed]

The arena's client code, its gates and its evaluation stay in duoforge_live.arena (see its docstring); this module
parses the arguments and runs it. Logs and results stay in DIR, outside the repository: they hold match ids
(AGENTS.md); a report quotes aggregates only.
"""
import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

from duoforge import runs
from duoforge_live.arena import (_ready, check_host, draw_pairs, evaluate, playable, pool_ids, provenance, run_lane,
                                 schedule, server_command)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_eval.live_arena", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--out", default=None, help="the private output directory (default: $DUOFORGE_RUNS/eval/<date>-live_arena)")
    p.add_argument("--games", type=int, default=400)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="localhost", help="the server's host (from WSL: the Windows host's address)")
    p.add_argument("--seed", type=int, default=0x2026101200000362)
    p.add_argument("--valid-teams", default=None,
                   help="the pool ids the pinned server accepts (stdout of tools/live/validate_pool.js); pairs come "
                        "from these only, the refused ones are reported")
    p.add_argument("--teams-from", default=None,
                   help="a pool network whose config's team pool the pairs are drawn from (default: --checkpoint's)")
    p.add_argument("--closed", action="store_true",
                   help="closed team sheets: both bots play over the particles (decision 0081), gates CTS_GATES")
    p.add_argument("--server-dir", default=None,
                   help="a pinned Showdown checkout to start with --no-security, bound to --host only "
                        "(on Windows with WSL bots: tools/live/local_server.ps1 starts it on the WSL host address)")
    from duoforge_live import search
    search.add_foe_net_arguments(p)  # the search bot's foe model, as in play
    args = p.parse_args(argv)
    if args.games % 2 or args.games < 2:
        raise SystemExit("the arena plays pairs: --games must be even")
    check_host(args.host)  # before anything is loaded or connected
    search.check_foe_net_arguments(args, True)
    foe_net = search.foe_net_path(search.foe_net_of(args))  # an unconfigured foe model stops here too
    if args.out is None:
        args.out = str(runs.default_out("eval", "live_arena"))
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    code = provenance()  # before anything is loaded or played: a result without its commit is refused
    manifest = runs.Manifest("eval", "duoforge_eval.live_arena", argv, seeds={"pairs": args.seed})
    from duoforge_learn import checkpoint
    from duoforge_live import client, data, policy
    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    _, config = checkpoint.load(args.checkpoint)
    ids = pool_ids(checkpoint.load(args.teams_from)[1] if args.teams_from else config)
    refused = []
    if args.valid_teams:
        valid = {line.strip() for line in Path(args.valid_teams).read_text(encoding="utf-8").splitlines() if line.strip()}
        ids, refused = playable(ids, valid)
    games = schedule(draw_pairs(ids, args.games // 2, args.seed))
    root = Path(__file__).resolve().parents[2] / "data" / "teams"
    texts = {t: (root / f"{t}.txt").read_text(encoding="utf-8") for t in {x for g in games for x in g[2:]}}
    server = None
    if args.server_dir:
        argv_, env = server_command(args.host, args.port)
        server = subprocess.Popen(argv_, env=env, cwd=args.server_dir, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        if not _ready(f"http://{args.host}:{args.port}/", 120):
            server.terminate()
            raise SystemExit("the local server did not answer within 120 s")
    url = f"ws://{args.host}:{args.port}/showdown/websocket"
    tables = data.load(kind=policy.table_kind(config))
    net = policy.load(args.checkpoint)
    prior = None
    if args.closed:
        from duoforge_live import cts
        prior = cts.SetPrior.from_table(tables)  # the pinned set table; tables it cannot read stop here
    records, start = [], time.monotonic()

    def make_bots(lane):
        def bot(role, live):
            cfg = client.Config(name=f"dfarena{lane}{role}bot", team="own", log_dir=str(out / "logs"),
                                team_link=None, server=url)
            return client.Bot(cfg, tables, net, login=lambda *a: "", search=live, team_texts={"own": ""},
                              prior=prior)
        return bot("s", search.load(args.checkpoint, foe_net=foe_net,
                                    foe_net_sha256=search.foe_net_sha256_of(args))), bot("r", None)

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
    report = {"foe_net": None if foe_net is None else {"sha256": search.foe_net_sha256_of(args)},  # the arm
              "checkpoint_config_teams": len(ids) + len(refused), "playable_teams": len(ids),
              "refused_teams": refused, "seed": args.seed, "games_planned": len(games),
              "lanes": args.lanes, "seconds": time.monotonic() - start, "code": code, "closed": args.closed,
              **evaluate(records, len(games), closed=args.closed)}
    (out / "games.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    (out / "arena.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    manifest.write(out)
    print(json.dumps({k: v for k, v in report.items() if k != "gates"}, indent=1), json.dumps(report["gates"]))
    return report


if __name__ == "__main__":
    main()
