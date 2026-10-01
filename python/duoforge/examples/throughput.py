"""Throughput of the Python loop against the native mode (M7, decision 0013).

    python -m duoforge.examples.throughput --envs 256 --workers 16 --episodes 4 --repeats 5

Environment e plays the reference pairing e % 4. Every mode plays rounds of
episodes (round k: every environment plays episode k from a fresh reset):
  native    Batch.play_random: the whole episode in C (decision 0012)
  autoreset query, RandomPolicy.choose, step, reset_terminal: every
            environment starts its next episode at once (the RL loop), until
            envs * episodes battles have ended
  autoreset-single  the same, re-seeding the policy one environment at a
            time (the loop before step_query and start_episodes)
  fused     the same loop with one step_query(autoreset=True) per step
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

MODES = ("native", "fused", "autoreset", "autoreset-single", "index", "factored", "scripted")
_TERMINAL = duoforge._layout.CONSTANTS["DUOFORGE_BOUNDARY_TERMINAL"]


class _Phases:
    """Seconds spent per phase of the autoreset loop (--phases)."""

    def __init__(self):
        self.seconds = {}
        self._last = time.perf_counter()

    def mark(self, name):
        now = time.perf_counter()
        self.seconds[name] = self.seconds.get(name, 0.0) + now - self._last
        self._last = now


def _play(batch, mode, episodes, seed, phases=None):
    """Plays the rounds of one mode; returns (battles, decisions)."""
    if mode == "native":
        records = batch.play_random(episodes, 1000)
        return records.size, int(records["decisions"].sum())
    policy = duoforge.ScriptedPolicy() if mode == "scripted" else duoforge.RandomPolicy(seed, batch.envs)
    decisions = 0
    if mode in ("autoreset", "autoreset-single", "fused"):
        for e in range(batch.envs):
            batch.reset(e, 1)
        episode = np.ones(batch.envs, dtype=np.uint64)  # autoreset moves an environment on by one episode
        policy.start_episodes(np.arange(batch.envs), episode)
        ended = 0
        mark = phases.mark if phases is not None else (lambda name: None)
        batch.query()
        mark("setup")
        while ended < batch.envs * episodes:
            decisions += int((batch.requests["requested"] != 0).sum())
            indices = policy.choose(batch)
            mark("policy")
            if mode == "fused":
                batch.step_query(indices, autoreset=True)
                mark("step_query")
            else:
                batch.step(indices)
                mark("step")
            if mode == "fused":
                terminal = np.flatnonzero(batch.episode_results)  # exactly the environments reset
            else:
                terminal = np.flatnonzero(batch.results["boundary_kind"] == _TERMINAL)
            if terminal.size:
                ended += terminal.size
                if mode != "fused":
                    batch.reset_terminal()
                    mark("reset")
                if mode == "autoreset-single":
                    for e in terminal:
                        policy.start_episode(e, batch.episode(e))
                else:
                    episode[terminal] += np.uint64(1)
                    policy.start_episodes(terminal, episode[terminal])
                mark("reseed")
            if mode != "fused":
                batch.query()
                mark("query")
            mark("python")
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
    parser.add_argument("--phases", action="store_true", help="time the phases of the autoreset and fused loops")
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
    phases = {m: _Phases() for m in ("autoreset", "autoreset-single", "fused")} if args.phases else {}
    with duoforge.Context() as ctx:
        setups = duoforge.reference_setups([e % 4 for e in range(args.envs)])
        for _ in range(args.repeats):
            for mode in args.modes:
                episodes = args.episodes * (args.native_factor if mode == "native" else 1)
                with duoforge.Batch(ctx, setups, args.workers, args.seed) as batch:
                    start = time.perf_counter()
                    battles, decisions = _play(batch, mode, episodes, args.seed, phases.get(mode))
                    seconds = time.perf_counter() - start
                rates[mode].append((battles / seconds, decisions / seconds, battles))
    for mode in args.modes:
        games = [r[0] for r in rates[mode]]
        decisions = [r[1] for r in rates[mode]]
        print(f"{mode:9s} {rates[mode][0][2]:6d} battles/run  games/s median {statistics.median(games):9.0f} "
              f"best {max(games):9.0f}  decisions/s median {statistics.median(decisions):10.0f} "
              f"best {max(decisions):10.0f}")
    for mode, timer in phases.items():
        if timer.seconds:
            total = sum(v for k, v in timer.seconds.items() if k != "setup")
            print(f"{mode} phases: " + ", ".join(f"{k} {100 * v / total:.1f}%" for k, v in timer.seconds.items()
                                                 if k != "setup"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
