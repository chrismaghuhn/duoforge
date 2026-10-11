"""python -m duoforge_live: the night run's bot on a Pokémon Showdown server (decision 0016).

The password of a registered name comes only from the environment variable
DUOFORGE_PS_PASSWORD; without it the bot logs in as a guest.
"""
import argparse
import asyncio
import os
from pathlib import Path

from . import client, data, policy, search


def _arguments(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_live", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="a checkpoint of this encoder's width (widen a 594 one first)")
    p.add_argument("--name", required=True, help="the bot's name; it must contain 'bot'")
    p.add_argument("--team", default="random", choices=("A", "B", "random"))
    p.add_argument("--server", default=client.OFFICIAL_SERVER)
    p.add_argument("--log-dir", default=str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "duoforge-live"))
    p.add_argument("--team-link", default=None, help="a link to Team A and B, added to the sheet message")
    p.add_argument("--challenge", default=None, help="local server only: challenge this user after login")
    p.add_argument("--search", default="raw", choices=("raw", "honest"),
                   help="honest: the honest search X plays the turn decisions (plan 2026-10-10-live-honest-search); "
                        "--checkpoint must then be the trained (not widened) format-2 file")
    p.add_argument("--challenge-format", default="gen9championsvgc2026regmc", choices=sorted(client.FORMATS))
    return p.parse_args(argv)


def main(argv=None):
    args = _arguments(argv)
    config = client.Config(name=args.name, team=args.team, log_dir=args.log_dir, team_link=args.team_link,
                           challenge=args.challenge, challenge_format=args.challenge_format, server=args.server)
    client.check_arguments(config)  # before anything is loaded or connected
    if args.search == "honest":
        from .tracker import Tracker
        search.check_tracker(Tracker)
    # the tables of the network's data kind, a format-2 file's fingerprint checked: a mismatch stops here, before a game
    net, tables = policy.load(args.checkpoint), data.for_checkpoint(args.checkpoint)
    live = search.load(args.checkpoint) if args.search == "honest" else None
    bot = client.Bot(config, tables, net, search=live)  # bot.close() closes the search too
    try:
        asyncio.run(bot.run())
    finally:
        bot.close()


if __name__ == "__main__":
    main()
