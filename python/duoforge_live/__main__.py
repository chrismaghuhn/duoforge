"""python -m duoforge_live: the night run's bot on a Pokémon Showdown server (decision 0016), or on PKMN Arena.

The password of a registered name comes only from the environment variable
DUOFORGE_PS_PASSWORD; without it the bot logs in as a guest.

    python -m duoforge_live --server arena --format ID --checkpoint P [--team FILE] [--team-pool FILE]
                            [--search honest [--foe-net P | --no-foe-net]] ...

plays on PKMN Arena (pkmn_arena): the bot's name comes from ARENA_BOT_NAME and its token from ARENA_BOT_TOKEN, only
from the environment; no option takes the token.
"""
import argparse
import asyncio
import os
import sys
import urllib.parse
from pathlib import Path

from . import client, data, pkmn_arena, policy, search

ARENA = "arena"  # --server arena: the PKMN Arena mode


def _log_dir():
    return str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "duoforge-live")


def _arguments(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_live", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="a checkpoint of this encoder's width (widen a 594 one first)")
    p.add_argument("--name", required=True, help="the bot's name; it must contain 'bot'")
    p.add_argument("--team", default="random", choices=("A", "B", "random"))
    p.add_argument("--server", default=client.OFFICIAL_SERVER, help=f"a Showdown websocket URL, or {ARENA!r}")
    p.add_argument("--log-dir", default=_log_dir())
    p.add_argument("--team-link", default=None, help="a link to Team A and B, added to the sheet message")
    p.add_argument("--challenge", default=None, help="local server only: challenge this user after login")
    p.add_argument("--search", default="raw", choices=("raw", "honest"),
                   help="honest: the honest search (HONEST_SETTINGS: ladder step 2e, the best answer) plays the turn "
                        "decisions (plan 2026-10-10-live-honest-search); "
                        "--checkpoint must then be the trained (not widened) format-2 file")
    p.add_argument("--challenge-format", default="gen9championsvgc2026regmc", choices=sorted(client.FORMATS))
    search.add_foe_net_arguments(p)  # with --search honest: the pinned foe model BC6 (owner 2026-10-12)
    return p.parse_args(argv)


def _arena_arguments(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_live --server arena", allow_abbrev=False,
                                description="PKMN Arena: name and token only from ARENA_BOT_NAME and ARENA_BOT_TOKEN")
    p.add_argument("--server", required=True, choices=(ARENA,))
    p.add_argument("--format", required=True, choices=pkmn_arena.FORMATS,
                   help="the format the bot is registered for; its random-team ladder (+random) is played too")
    p.add_argument("--checkpoint", required=True, help="a checkpoint the live policy loads (format 2: model v2 too)")
    p.add_argument("--team", default=None, help="the team's paste, sent with /utm after every login")
    p.add_argument("--team-pool", default=None,
                   help="the random ladder's published teams (pastes after '=== ... ===' lines): a random-team battle "
                        "is played by the policy only when one of them matches its request")
    p.add_argument("--search", default="raw", choices=("raw", "honest"),
                   help="honest: the honest search (HONEST_SETTINGS: ladder step 2e, the best answer) plays the turn "
                        "decisions (a trained format-2 checkpoint)")
    search.add_foe_net_arguments(p)  # with --search honest: the pinned foe model BC6 (owner 2026-10-12)
    p.add_argument("--ab-root-rule", action="store_true",
                   help="with --search honest and --team: the A/B test of the root rule (duoforge_live.ab), every team "
                        "battle one arm, ladder step 0 or 2e in blocks of two; the run log names the seed")
    p.add_argument("--ab-seed", type=int, default=None,
                   help="with --ab-root-rule: the draw's seed (default: a new random one, named in the run log)")
    p.add_argument("--log-dir", default=_log_dir(), help="private logs, outside the repository")
    return p.parse_args(argv)


def _is_arena(argv):
    return any(a == "--server" and i + 1 < len(argv) and argv[i + 1] == ARENA or a == f"--server={ARENA}"
               for i, a in enumerate(argv))


def arena_main(argv):
    pkmn_arena.check_argv(argv)  # before argparse, whose errors echo the arguments
    args = _arena_arguments(argv)
    try:
        search.check_foe_net_arguments(args, args.search == "honest")
    except ValueError as err:
        pkmn_arena._refuse(str(err))
    if args.ab_seed is not None and not args.ab_root_rule:
        pkmn_arena._refuse("--ab-seed is the seed of --ab-root-rule: give both or neither")
    if args.ab_root_rule and (args.search != "honest" or not args.team or args.team_pool):
        pkmn_arena._refuse("--ab-root-rule tests the honest search's root rule on the --team's battles: it needs "
                           "--search honest and --team, and no --team-pool")
    name = pkmn_arena.credentials()  # the token's value is never shown
    from .arena import provenance
    code = provenance()  # every result names the code that runs (HauptSession, 2026-10-13): none, no start
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.log_dir)  # the battle logs hold match ids (AGENTS.md)
    except ValueError as err:
        pkmn_arena._refuse(str(err))
    team_text = Path(args.team).read_text(encoding="utf-8") if args.team else None
    pool = pkmn_arena.read_pool(args.team_pool) if args.team_pool else []
    if team_text is None and not pool:
        pkmn_arena._refuse("--team (the team ladder) or --team-pool (the random-team ladder) is needed")
    foe_path = None
    if args.search == "honest":
        from .tracker import Tracker
        search.check_tracker(Tracker)
        try:  # the pinned foe model BC6 by default (owner 2026-10-12): unconfigured stops here, before any loading
            foe_path = search.foe_net_path(search.foe_net_of(args))
        except ValueError as err:
            pkmn_arena._refuse(str(err))
    net, tables = policy.load(args.checkpoint), data.for_checkpoint(args.checkpoint)
    pkmn_arena.check_teams(tables, team_text, pool)
    live, foe_check = None, None
    if args.search == "honest":
        live = search.load(args.checkpoint, foe_net=foe_path, foe_net_sha256=search.foe_net_sha256_of(args))
        foe_check = live.foe_check
    mode = args.search + ("+foe_net" if foe_path is not None else "")
    ab_seed = None
    if args.ab_root_rule:
        from . import ab
        ab_seed = ab.new_seed() if args.ab_seed is None else args.ab_seed
    bot = pkmn_arena.ArenaBot(name, tables, net, args.log_dir, args.format, team_text=team_text, pool=pool,
                              search=live, mode=mode, foe_check=foe_check, code=code, ab_seed=ab_seed)
    try:
        bot.warm_up()  # before the first battle: its decisions compile nothing (2.0 s at a cold team preview)
        asyncio.run(bot.run())
    finally:
        bot.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pkmn_arena.check_argv(argv)  # in every mode, before argparse, whose errors echo the arguments
    if _is_arena(argv):
        return arena_main(argv)
    args = _arguments(argv)
    if args.server == ARENA or (urllib.parse.urlparse(args.server).hostname or "") == pkmn_arena.HOST:
        print(f"duoforge_live: {pkmn_arena.HOST} is PKMN Arena: use --server {ARENA}", file=sys.stderr)
        raise SystemExit(2)
    config = client.Config(name=args.name, team=args.team, log_dir=args.log_dir, team_link=args.team_link,
                           challenge=args.challenge, challenge_format=args.challenge_format, server=args.server)
    client.check_arguments(config)  # before anything is loaded or connected
    search.check_foe_net_arguments(args, args.search == "honest")
    foe_path = None
    if args.search == "honest":
        from .tracker import Tracker
        search.check_tracker(Tracker)
        foe_path = search.foe_net_path(search.foe_net_of(args))  # an unconfigured foe model stops here, before loading
    # the tables of the network's data kind, a format-2 file's fingerprint checked: a mismatch stops here, before a game
    net, tables = policy.load(args.checkpoint), data.for_checkpoint(args.checkpoint)
    live = None
    if args.search == "honest":
        live = search.load(args.checkpoint, foe_net=foe_path, foe_net_sha256=search.foe_net_sha256_of(args))
    bot = client.Bot(config, tables, net, search=live)  # bot.close() closes the search too
    try:
        asyncio.run(bot.run())
    finally:
        bot.close()


if __name__ == "__main__":
    main()
