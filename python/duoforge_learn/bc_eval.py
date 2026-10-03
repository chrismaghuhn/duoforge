"""The play of a BC checkpoint on POOL teams (M11 BC spec section 10): python -m duoforge_learn.bc_eval.

The checkpoint's greedy network plays a suite (suite.make_suite) of the team pool against the random baseline and
against ScriptedPolicy (evaluate.play_suite, evaluate.scores), encoded with its own encoder and view-extension mask
as in the ladder. --baseline-random-net plays an untrained network of the same model the same way, for comparison.
Prints one JSON line: {"vs_random", "vs_scripted", ["random_net_vs_random", "random_net_vs_scripted"], "n_games"}.
"""
import argparse
import json

import jax

import duoforge
from duoforge import _layout, teams

from . import checkpoint, evaluate, policy, suite


def _parser():
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.bc_eval", description=__doc__.splitlines()[0])
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--teams", default=None, help="registry team ids, comma-separated (default: Teams A and B)")
    p.add_argument("--teams-root", default="data/teams")
    p.add_argument("--games", type=int, default=2, help="games per suite row pairing (suite.make_suite)")
    p.add_argument("--budget", type=int, default=512, help="suite rows for a pool larger than the complete suite")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--baseline-random-net", action="store_true",
                   help="also play an untrained network of the checkpoint's model")
    return p


def _pool(context, args):
    if args.teams is None:
        return teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
    return teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root)


def main(argv=None):
    args = _parser().parse_args(argv)
    params, config = checkpoint.load_current(args.checkpoint)
    model = policy.make(config["model"])
    encoder, mask = checkpoint.encoder_of(config), checkpoint.ext_supported_of(config)
    players = [("", evaluate.Player(model, params, encoder, "checkpoint", ext_supported=mask))]
    if args.baseline_random_net:
        untrained = model.init(jax.random.PRNGKey(args.seed))
        players.append(("random_net_", evaluate.Player(model, untrained, encoder, "random-net", ext_supported=mask)))
    out = {}
    with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as context:
        if config.get("data", {}).get("fingerprint") != context.fingerprint().hex():
            try:  # other tables than the checkpoint's: its embedded ids must still name the same rows
                checkpoint.check_ids(config, context)
            except ValueError as err:
                raise SystemExit(f"{args.checkpoint}: the context's tables differ from the checkpoint's: {err}") from None
        pool = _pool(context, args)
        rows = suite.make_suite(len(pool.ids), args.seed, games=args.games, budget=args.budget)
        for prefix, player in players:
            for opponent in ("random", "scripted"):
                records = evaluate.play_suite(context, pool, rows, player, opponent, args.workers, args.seed,
                                              max_steps=args.max_steps)
                out[f"{prefix}vs_{opponent}"] = evaluate.scores(records, len(pool.ids))
    out["n_games"] = int(rows.shape[0])
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
