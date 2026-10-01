"""Throughput of the Python loop against the native mode (M7, decision 0013).

    python -m duoforge.examples.throughput --envs 256 --workers 16 --episodes 4 --repeats 5

Environment e plays the reference pairing e % 4. Every mode plays rounds of
episodes (round k: every environment plays episode k from a fresh reset):
  native    Batch.play_random: the whole episode in C (decision 0012)
  autoreset query, RandomPolicy.choose, step, reset_terminal: every
            environment starts its next episode at once (the RL loop), until
            envs * episodes battles have ended
  index     query, RandomPolicy.choose, step: one C call per batch operation
  factored  query_factored, choose_factored, step_factored
  scripted  query, ScriptedPolicy.choose, step
The modes run interleaved, --repeats times; the native mode plays
--native-factor times the episodes so its runs are long enough to time.
Prints the median and the best games/s and decisions/s of each mode; the
machine should be quiet (decision 0008).
"""
import argparse
import platform
import statistics
import sys
import time

import numpy as np

import duoforge

MODES = ("native", "autoreset", "index", "factored", "scripted")
_TERMINAL = duoforge._layout.CONSTANTS["DUOFORGE_BOUNDARY_TERMINAL"]


def _play(batch, mode, episodes, seed):
    """Plays the rounds of one mode; returns (battles, decisions)."""
    if mode == "native":
        records = batch.play_random(episodes, 1000)
        return records.size, int(records["decisions"].sum())
    policy = duoforge.ScriptedPolicy() if mode == "scripted" else duoforge.RandomPolicy(seed, batch.envs)
    decisions = 0
    if mode == "autoreset":
        for e in range(batch.envs):
            policy.start_episode(e, 1)
            batch.reset(e, 1)
        ended = 0
        while ended < batch.envs * episodes:
            batch.query()
            decisions += int((batch.requests["requested"] != 0).sum())
            batch.step(policy.choose(batch))
            terminal = np.flatnonzero(batch.results["boundary_kind"] == _TERMINAL)
            if terminal.size:
                ended += terminal.size
                batch.reset_terminal()
                for e in terminal:
                    policy.start_episode(e, batch.episode(e))
        return ended, decisions
    for k in range(batch.episode(0) + 1, batch.episode(0) + 1 + episodes):
        for e in range(batch.envs):
            if mode != "scripted":
                policy.start_episode(e, k)
            batch.reset(e, k)
        while True:
            if mode == "factored":
                batch.query_factored()
            else:
                batch.query()
            requested = batch.requests["requested"] != 0
            if not requested.any():
                break
            decisions += int(requested.sum())
            if mode == "factored":
                batch.step_factored(policy.choose_factored(batch))
            else:
                batch.step(policy.choose(batch))
    return batch.envs * episodes, decisions


def _arguments(argv):
    parser = argparse.ArgumentParser(prog="python -m duoforge.examples.throughput",
                                     description="Throughput of the Python loop against the native mode.")
    parser.add_argument("--envs", type=int, default=64)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--episodes", type=int, default=16, help="episodes per environment and run")
    parser.add_argument("--native-factor", type=int, default=8, help="the native mode plays this many times more")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--modes", default=",".join(MODES), help="comma-separated subset of " + ",".join(MODES))
    parser.add_argument("--seed", type=lambda s: int(s, 0), default=0x2026100200000018)
    args = parser.parse_args(argv)
    args.modes = args.modes.split(",")
    if any(m not in MODES for m in args.modes):
        parser.error(f"--modes takes {','.join(MODES)}")
    if min(args.envs, args.workers, args.episodes, args.native_factor, args.repeats) < 1:
        parser.error("counts must be positive")
    return args


def main(argv=None):
    args = _arguments(sys.argv[1:] if argv is None else list(argv))
    print(f"library {duoforge.version()} ({duoforge.library_path()}), Python {platform.python_version()}, "
          f"NumPy {np.__version__}")
    print(f"envs {args.envs}, workers {args.workers}, episodes {args.episodes} "
          f"(native x{args.native_factor}), repeats {args.repeats}")
    rates = {m: [] for m in args.modes}
    with duoforge.Context() as ctx:
        setups = duoforge.reference_setups([e % 4 for e in range(args.envs)])
        for _ in range(args.repeats):
            for mode in args.modes:
                episodes = args.episodes * (args.native_factor if mode == "native" else 1)
                with duoforge.Batch(ctx, setups, args.workers, args.seed) as batch:
                    start = time.perf_counter()
                    battles, decisions = _play(batch, mode, episodes, args.seed)
                    seconds = time.perf_counter() - start
                rates[mode].append((battles / seconds, decisions / seconds, battles))
    for mode in args.modes:
        games = [r[0] for r in rates[mode]]
        decisions = [r[1] for r in rates[mode]]
        print(f"{mode:9s} {rates[mode][0][2]:6d} battles/run  games/s median {statistics.median(games):9.0f} "
              f"best {max(games):9.0f}  decisions/s median {statistics.median(decisions):10.0f} "
              f"best {max(decisions):10.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
