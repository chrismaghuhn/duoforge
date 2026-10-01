"""Write a trajectory recipe, then replay it (M7 spec section 7).

    python -m duoforge.examples.generate --envs 64 --episodes 10 \\
        --policy random|scripted --workers N --seed S --out DIR/NAME

Environment e plays the reference pairing e % 4 (A-B, B-A, A-A, B-B). Each of
--episodes rounds plays one episode per environment to TERMINAL (or
--max-steps steps); the recipe goes to DIR/NAME.npz and DIR/NAME.json and is
replayed at once. Prints battles, decisions, results per pairing, bytes on
disk and the rates of both passes; the exit status is 0 only after a clean
replay.
"""
import argparse
import os
import sys
import time

import numpy as np

import duoforge
from duoforge import recipes

PAIRINGS = ["A-B", "B-A", "A-A", "B-B"]


def _arguments(argv):
    parser = argparse.ArgumentParser(prog="python -m duoforge.examples.generate",
                                     description="Write a trajectory recipe, then replay it.")
    parser.add_argument("--envs", type=int, default=64, help="environments (default 64)")
    parser.add_argument("--episodes", type=int, default=10, help="episodes per environment (default 10)")
    parser.add_argument("--policy", choices=["random", "scripted"], default="random")
    parser.add_argument("--workers", type=int, default=1, help="batch worker threads (default 1)")
    parser.add_argument("--seed", type=lambda s: int(s, 0), default=0x2026100200000017, help="batch seed")
    parser.add_argument("--max-steps", type=int, default=1000, help="steps before an episode is truncated")
    parser.add_argument("--out", required=True, help="DIR/NAME of the recipe files")
    args = parser.parse_args(argv)
    if args.envs < 1 or args.episodes < 1 or args.workers < 1 or args.max_steps < 1:
        parser.error("--envs, --episodes, --workers and --max-steps must be positive")
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    args = _arguments(argv)
    folder = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(folder, exist_ok=True)
    setup_index = np.arange(args.envs) % len(PAIRINGS)
    if args.policy == "random":
        chooser, entry = duoforge.RandomPolicy(args.seed, args.envs), {"name": "random", "seed": args.seed}
    else:
        chooser, entry = duoforge.ScriptedPolicy(), {"name": "scripted"}
    command = "python -m duoforge.examples.generate " + " ".join(argv)

    with duoforge.Context() as ctx:
        setups = duoforge.reference_setups(setup_index.tolist())
        with duoforge.Batch(ctx, setups, args.workers, args.seed) as batch:
            with recipes.RecipeWriter(args.out, context=ctx, seed=args.seed, max_steps=args.max_steps,
                                      setups=PAIRINGS, policies=[entry], command=command) as writer:
                start = time.perf_counter()
                recipes.record(batch, chooser, writer, episodes=args.episodes, setup=setup_index, policy=(0, 0))
                generated = time.perf_counter() - start

    recipe = recipes.load(args.out)
    a = recipe.arrays
    battles, decisions = len(recipe), int(a["choice"].shape[0])
    print(f"battles: {battles}, decisions: {decisions} "
          f"(generation: {battles / generated:.0f} games/s, {decisions / generated:.0f} decisions/s)")
    for i, name in enumerate(PAIRINGS):
        mine = a["setup"] == i
        r = a["result"][mine]
        print(f"  {name}: {int(mine.sum())} battles, side 0 won {int((r == 1).sum())}, "
              f"side 1 won {int((r == 2).sum())}, ties {int((r == 3).sum())}, "
              f"truncated {int(a['truncated'][mine].sum())}")
    size = os.path.getsize(args.out + ".npz") + os.path.getsize(args.out + ".json")
    print(f"bytes on disk: {size} ({size / battles:.0f} per battle)")

    mismatches = 0
    start = time.perf_counter()
    try:
        recipes.replay(recipe, workers=args.workers)
    except recipes.ReplayMismatch as err:
        mismatches = 1
        print(f"mismatch: {err}")
    replayed = time.perf_counter() - start
    print(f"replay: {battles} episodes, {mismatches} mismatches "
          f"({battles / replayed:.0f} games/s, {decisions / replayed:.0f} decisions/s)")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
