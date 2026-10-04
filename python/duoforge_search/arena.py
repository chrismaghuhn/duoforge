"""The search in the arena (spec section 8, plan tasks 10 and 11).

SearchPlayer plays evaluate.play_suite's games with a Lookahead (the labeled
true-state oracle) or Honest (worlds from the player's public record). It has
the Player interface; play_suite passes it the step, its seat in every game
and the last-step flag.

The measurement (main: python -m duoforge_search.arena): a checkpoint with
the search, agents N (the Nash rule) and E (the expected value), against
the same network without it (R) and optionally a panel of the run's earlier
checkpoints, over the run's team suite; every configuration writes its games,
decision records and times, and summary.json holds the scores, Elo,
intervals, paired differences, diagnostics and the conditions a rerun needs.
bootstrap_mean, bootstrap_paired and elo are NumPy.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from collections import Counter

import numpy as np

import duoforge
from duoforge import _layout
from duoforge_learn import book_preview, evaluate, ladder, suite
from duoforge_learn.selfplay import choices_of

from . import lookahead, seeds

ARENA_SEED = 0x2026100300000222
BOOTSTRAP_SEED = 0x2026100300000220
RESAMPLES = 2000
GAMES = 2048
MAX_STEPS = 1000
AGENTS = {"N": "nash", "E": "ev", "X": "mix"}
PANEL = (25, 50, 75)  # percent of the run's last update
PARTS = ("network", "engine", "reduction", "split")
ORACLE = ("an oracle benchmark (ARCHITECTURE section 10): the search runs on the true state, so it knows the foe's "
          "stat points and their stats, its exact HP and the secret counters of both sides (spec section 3)")


class SearchPlayer:
    """A Lookahead as a player of evaluate.play_suite: indices(batch,
    choices, step, seats, last_step) gives the candidate index of the
    searched action of its seat in every game where that seat is requested,
    NO_CHOICE elsewhere, as Player.indices does.

    Decision keys: seeds.decision_keys(arena_seed, env, its episode, the
    root's request epoch, seat). At play_suite's last step (last_step) the
    leaves are scored by the tiebreak, as play_suite scores a game it cuts
    off (spec section 5.3).

    records: the lookahead's records of every game row (environment), each
    with its step. They accumulate over play_suite calls: a SearchPlayer
    (or clear()) per suite. Every leaf is valued from the searcher's side,
    a refused leaf -1 as the refused game is the learner's loss: the
    searcher plays as the learner (spec section 8.2). As the opponent its
    refused leaves still count -1 for itself, while play_suite counts a
    refused game as the learner's loss."""

    def __init__(self, lookahead, name, arena_seed):
        self.lookahead, self.name = lookahead, name
        self.arena_seed = int(arena_seed)
        self.records = {}

    def clear(self):
        """Forgets the records (a new suite)."""
        self.records = {}
        if hasattr(self.lookahead, "clear"):
            self.lookahead.clear()

    def indices(self, batch, choices, step=None, seats=None, last_step=None):
        if step is None or seats is None or last_step is None:
            raise ValueError("a SearchPlayer needs the arena's step, its seats and the last-step flag "
                             "(evaluate.play_suite passes them)")
        envs = batch.envs
        seats = np.asarray(seats)
        if seats.shape != (envs,) or not np.isin(seats, (-1, 0, 1)).all():
            raise ValueError(f"seats must hold 0, 1 or -1 for each of the {envs} games")
        seats = seats.astype(np.int64)
        every = np.arange(envs)
        out = np.full((envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
        playing = every[seats >= 0]
        asked = playing[batch.requests["requested"][playing, seats[playing]] != 0]
        if asked.size == 0:
            return out
        e, p = asked, seats[asked]
        keys = seeds.decision_keys(self.arena_seed, e, [batch.episode(int(x)) for x in e],
                                   batch.requests["epoch"][e, p], p)
        actions, records = self.lookahead.decide(batch, e, p, keys, np.full(e.size, bool(last_step)))
        for r in records:
            r["step"] = int(step)
            self.records.setdefault(r["env"], []).append(r)
        full = np.zeros((envs, 2), dtype=np.int64)
        full[e, p] = actions
        choices_of(batch, full, choices)
        mine = np.zeros((envs, 2), dtype=bool)
        mine[e, p] = True
        out[mine] = duoforge.joint_indices(batch.domains[mine], choices[mine])
        return out


def elo(score):
    """400 log10(s / (1 - s)) of a mean score s in [0, 1] (spec section 8.3):
    0 at 0.5, -inf at 0 and +inf at 1. A float for a number, an array for an
    array; ValueError outside [0, 1]."""
    s = np.asarray(score, dtype=np.float64)
    if (np.isnan(s) | (s < 0.0) | (s > 1.0)).any():
        raise ValueError(f"a score lies in [0, 1] (got {score!r})")
    with np.errstate(divide="ignore"):
        out = 400.0 * (np.log10(s) - np.log10(1.0 - s))
    return float(out) if out.ndim == 0 else out


def _resampled(n, resamples, seed):
    """The row indices (resamples, n) of a bootstrap, drawn from seed."""
    if n < 1 or int(resamples) < 1:
        raise ValueError(f"a bootstrap needs rows and resamples (got {n} rows, {resamples} resamples)")
    return np.random.default_rng(seed).integers(0, n, size=(int(resamples), n))


def _interval(stats):
    low, high = np.quantile(stats, (0.025, 0.975))
    return float(low), float(high)


def bootstrap_mean(values, resamples=RESAMPLES, seed=BOOTSTRAP_SEED):
    """The 95 % interval (low, high) of the mean of values, one per suite
    row: the 2.5 and 97.5 percentiles of the means of `resamples` resamples
    of the rows with replacement, drawn from seed (spec section 8.3)."""
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    return _interval(v[_resampled(v.size, resamples, seed)].mean(axis=1))


def bootstrap_paired(a, b, resamples=RESAMPLES, seed=BOOTSTRAP_SEED):
    """The 95 % interval of the mean paired difference a - b, one value of
    each per suite row, the rows of both resampled together (spec section
    8.2)."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"paired values need the same rows (got {a.size} and {b.size})")
    return _interval((a - b)[_resampled(a.size, resamples, seed)].mean(axis=1))


def _paired_elo(a, b, resamples=RESAMPLES, seed=BOOTSTRAP_SEED):
    """The 95 % interval of elo(mean a) - elo(mean b) over the same resampled rows."""
    idx = _resampled(np.asarray(a).size, resamples, seed)
    a, b = np.asarray(a, dtype=np.float64)[idx].mean(axis=1), np.asarray(b, dtype=np.float64)[idx].mean(axis=1)
    with np.errstate(invalid="ignore"):
        return _interval(elo(a) - elo(b))


def scores(records):
    """The learner's score of every game row (evaluate.RECORD): 1 a win, 0.5
    a tie, 0 a loss; a cut-off game is scored by its tiebreak and an
    unresolved one is the learner's loss, as play_suite records them."""
    return (np.asarray(records["result"]).astype(np.float64) + 1.0) / 2.0


def timing(records):
    """Median and p95 ms per searched decision, in total and split into the
    network (its share of the policy and value calls), the engine (expand
    and tiebreaks), the reduction and the split halves."""
    searched = [r for r in records if r["kind"] == "searched"]
    if not searched:
        return {"searched": 0, "ms": None}
    ms = {p: 1000.0 * np.array([r["time"][p] for r in searched], dtype=np.float64) for p in PARTS}
    ms["total"] = sum(ms[p] for p in PARTS)
    result = {"searched": len(searched),
              "ms": {p: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95))} for p, v in ms.items()}}
    if all("cost" in r for r in searched):
        result["cost_ms"] = {p: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95))}
                             for p in searched[0]["cost"]
                             for v in [1000 * np.array([r["cost"][p] for r in searched])]}
    return result


def diagnostics(records, games):
    """The summary of a configuration's decision records (spec section 8.5)."""
    kinds = Counter(r["kind"] for r in records)
    searched = [r for r in records if r["kind"] == "searched"]
    leaves = Counter()
    for r in searched:
        leaves.update(r["leaves"])
    out = {"decisions": {k: kinds.get(k, 0) for k in ("searched", "forced", "team")},
           "searched_per_game": len(searched) / games, "leaves": dict(leaves)}
    if kinds["unreconstructible"] or kinds["raw"] or any(r.get("search") == "honest" for r in records):
        out["decisions"].update({k: kinds[k] for k in ("unreconstructible", "raw")})
        out["unreconstructible_reasons"] = dict(Counter(r["reason"] for r in records if r["kind"] == "unreconstructible"))
        causes = Counter(c for r in records if r["kind"] == "unreconstructible" for c in r.get("causes", [r["reason"]]))
        out["unreconstructible_share"] = kinds["unreconstructible"] / len(records) if records else 0.0
        for cause in ("visible_sleep", "visible_confusion"):
            causes.setdefault(cause, 0)
        out["unreconstructible_by_cause"] = {c: {"decisions": count, "share_of_decisions": count / len(records)}
                                             for c, count in causes.items()}
    if any("bench_dropped" in r for r in searched):
        out["bench_dropped"] = sum(r.get("bench_dropped", 0) for r in searched)
        out["respreads"] = sum(r.get("respreads", 0) for r in searched)
    if not searched:
        return out
    out["roots"] = {b: sum(r["boundary"] == b for r in searched) for b in ("TURN", "REPLACEMENT", "PIVOT")}
    out["changed"] = float(np.mean([r["changed"] for r in searched]))
    out["coverage"] = float(np.mean([r["coverage"] for r in searched]))
    out["near_duplicates"] = int(sum(r["near_duplicates"] for r in searched))
    nash = [r for r in searched if r["rule"] == "nash"]
    if nash:
        out["exact"] = int(sum(r["exact"] for r in nash))
        out["support"] = float(np.mean([r["support"][0] for r in nash]))
        halves = [float(np.mean(r["split"]["exploitability"])) for r in nash if r["split"]]
        out["split_exploitability"] = float(np.mean(halves)) if halves else None
    expected = [r for r in searched if r["rule"] == "ev"]
    if expected:
        same = [r["split"]["same_choice"] for r in expected if r["split"]]
        out["split_same_choice"] = float(np.mean(same)) if same else None
    return out


def _finite(obj):
    """obj with every float that is not finite as None (strict JSON)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cpu_model():
    """The CPU's model name (/proc/cpuinfo on Linux, else platform.processor())."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        return platform.processor()


def require_deterministic_gpu(jax):
    """The existing arena reproduction requirement, shared with the book A/B."""
    if jax.default_backend() == "gpu" and "--xla_gpu_deterministic_ops=true" not in os.environ.get("XLA_FLAGS", ""):
        raise SystemExit("on the GPU the value calls must be deterministic: set "
                         "XLA_FLAGS=--xla_gpu_deterministic_ops=true (spec section 6)")


def _commit():
    """(commit, dirty) of the checkout this module runs from; (None, None) outside git."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return head, bool(dirty)
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _checkpoint_path(run_dir, name):
    """A checkpoint given as a path, as a file of the run, or as params-<update> of the run."""
    for path in (name, os.path.join(run_dir, name), os.path.join(run_dir, f"{name}.npz")):
        if os.path.isfile(path):
            return path
    raise SystemExit(f"no checkpoint {name!r}, as a path or in {run_dir}")


def best_checkpoint(run_dir):
    """The run's best checkpoint by its ladder file (RUN/ladder.json): the
    highest Elo among this run's players."""
    path = os.path.join(run_dir, "ladder.json")
    if not os.path.isfile(path):
        raise SystemExit(f"{run_dir} has no ladder.json: name the checkpoint (--checkpoint)")
    with open(path, encoding="utf-8") as f:
        players = json.load(f)["players"]
    label = os.path.basename(os.path.normpath(run_dir))
    ranked = [(row["elo"], int(m.group(1))) for row in players
              if (m := re.fullmatch(re.escape(label) + r" update (\d+)", row["player"]))]
    if not ranked:
        raise SystemExit(f"{path} rates no checkpoint of {label}: name the checkpoint (--checkpoint)")
    return _checkpoint_path(run_dir, f"params-{max(ranked)[1]}")


def panel_checkpoints(run_dir, percents=PANEL):
    """[(percent, update, path)]: the run's checkpoints nearest to percents
    of its last update (spec section 8.2), ties to the earlier one."""
    found = ladder._checkpoints(run_dir)
    if not found:
        raise SystemExit(f"no checkpoints in {run_dir}")
    last = found[-1][0]
    picks = []
    for pct in percents:
        update, path = min(found, key=lambda x: (abs(x[0] - last * pct / 100.0), x[0]))
        picks.append((pct, update, path))
    return picks


def _update_of(path):
    m = re.search(r"params-(\d+)\.npz$", path)
    return int(m.group(1)) if m else None


def _write_games(path, records):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(("row",) + evaluate.RECORD.names + ("score",))
        for row, (r, score) in enumerate(zip(records, scores(records))):
            w.writerow((row,) + tuple(int(r[k]) for k in evaluate.RECORD.names) + (score,))


def _list(text, name, allowed=None):
    items = [x.strip() for x in str(text).split(",") if x.strip()]
    if not items or (allowed is not None and not set(items) <= set(allowed)):
        raise SystemExit(f"--{name} takes a comma list of {sorted(allowed) if allowed else 'values'} (got {text!r})")
    return items


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m duoforge_search.arena",
        description="The M12 arena (decisions 0022/0023): honest public-information search or the labeled oracle. A checkpoint with the "
                    "one-turn lookahead against the same network without it, over the run's team suite; "
                    f"{ORACLE}. Outputs in OUT: raw/<config>-games.csv (play_suite's records and the score), "
                    "raw/<config>-decisions.jsonl (the records of spec 8.5, searched configurations), "
                    "raw/<config>-timing.json and summary.json (scores, Elo, 95 % intervals, the paired "
                    "differences against R, the diagnostics and every condition a rerun needs). On the GPU "
                    "set XLA_FLAGS=--xla_gpu_deterministic_ops=true.")
    p.add_argument("--run-dir", required=True, help="the training run: its checkpoints, pool and ladder.json")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--checkpoint", default=None,
                   help="params-<update>, a file of the run or a path (default: the best by RUN/ladder.json)")
    p.add_argument("--agents", default="N,E", help="N (Nash), E (expected value), X (the mix)")
    p.add_argument("--search", choices=("honest", "oracle"), default="oracle",
                   help="honest public-information worlds or the labeled true-state oracle")
    p.add_argument("--lam", type=float, default=0.5, help="X's Nash weight, between 0 and 1")
    p.add_argument("--opponents", default="raw",
                   help="raw (the same network without search), panel (three earlier checkpoints) and/or "
                        "scripted (evaluate's ScriptedPolicy)")
    p.add_argument("--panel", default=None,
                   help="three checkpoints for the panel (default: nearest to 25, 50 and 75 %% of the run's updates)")
    p.add_argument("--games", type=int, default=GAMES, help="the suite's budget of games")
    p.add_argument("--km", default="8x8", help="candidates K x M, one or more: 8x8 or 4x4,16x16")
    p.add_argument("--s", "--samples", "--worlds", dest="s", default="16",
                   help="samples per cell: the sampled chance worlds of every pair of the table; one or more, "
                        "e.g. 16,32,64")
    p.add_argument("--capacity", type=int, default=lookahead.CAPACITY,
                   help="leaves per expand and value call (part of a decision's reproduction)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=MAX_STEPS)
    p.add_argument("--resamples", type=int, default=RESAMPLES, help="bootstrap resamples")
    book_preview.add_arguments(p)
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    evidence = book_preview.load_options(args)
    if not 0 <= args.lam <= 1:
        raise SystemExit("--lam must be between 0 and 1")
    agents = _list(args.agents, "agents", AGENTS)
    wanted = _list(args.opponents, "opponents", ("raw", "panel", "scripted"))
    km = []
    for item in _list(args.km, "km"):
        m = re.fullmatch(r"(\d+)x(\d+)", item)
        if not m or int(m.group(1)) < 1 or int(m.group(2)) < 1:
            raise SystemExit(f"--km takes K x M as 8x8 (got {item!r})")
        km.append((int(m.group(1)), int(m.group(2))))
    try:
        samples = [int(x) for x in _list(args.s, "s")]
    except ValueError:
        raise SystemExit(f"--s takes a comma list of sample counts, e.g. 16,32,64 (got {args.s!r})") from None
    if min(samples) < 1 or args.games < 1 or args.capacity < 1 or args.workers < 1 or args.max_steps < 1:
        raise SystemExit("samples, games, capacity, workers and max-steps must be positive")
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository: evaluation output is written outside it "
                         f"(AGENTS.md)") from None

    import importlib.metadata

    import jax

    from duoforge_learn import checkpoint, policy
    require_deterministic_gpu(jax)
    pool, kind = ladder._pool_of(args.run_dir)
    spread = source_ids = table_info = None
    if args.search == "honest":
        from . import honest
        with duoforge.Context(data_kind=kind) as ctx:
            spread, source_ids, table_info = honest.spread_table(ctx)
    rows = suite.make_suite(len(pool.ids), ARENA_SEED, budget=args.games)
    models = {}

    def load(path, name):
        params, config = checkpoint.load_current(path)
        cfg = checkpoint.model_config(config, params)
        key = json.dumps(cfg, sort_keys=True)
        if key not in models:
            models[key] = policy.make(cfg)
        encoder, ext = checkpoint.encoder_of(config), checkpoint.ext_supported_of(config)
        info = {"name": name, "file": os.path.basename(path), "update": _update_of(path), "sha256": _sha256(path),
                "model": cfg, "encoder": encoder, "ext_supported": ext}
        return evaluate.Player(models[key], params, encoder, name, ext), info

    path = _checkpoint_path(args.run_dir, args.checkpoint) if args.checkpoint else best_checkpoint(args.run_dir)
    raw, raw_info = load(path, "R")
    opponents = {}
    if "raw" in wanted:
        opponents["R"] = (raw, raw_info)
    if "panel" in wanted:
        if args.panel:
            names = _list(args.panel, "panel")
            if len(names) != len(PANEL):
                raise SystemExit(f"--panel names {len(PANEL)} checkpoints (got {args.panel!r})")
            picks = [(pct, None, _checkpoint_path(args.run_dir, n)) for pct, n in zip(PANEL, names)]
        else:
            picks = panel_checkpoints(args.run_dir)
        for pct, _, panel_path in picks:
            opponents[f"P{pct}"] = load(panel_path, f"P{pct}")
    if "scripted" in wanted:  # evaluate's ScriptedPolicy (play_suite's opponent "scripted"), a fixed non-network player
        opponents["S"] = ("scripted", {"name": "S", "scripted": True})

    commit, dirty = _commit()
    try:
        jaxlib = importlib.metadata.version("jaxlib")
    except importlib.metadata.PackageNotFoundError:
        jaxlib = None
    conditions = {
        "oracle": ORACLE, "capacity": args.capacity, "workers": args.workers, "max_steps": args.max_steps,
        "games": args.games, "suite_rows": int(rows.shape[0]), "agents": agents, "km": [f"{k}x{m}" for k, m in km],
        "s": samples, "search_seed": hex(lookahead.SEARCH_SEED), "arena_seed": hex(ARENA_SEED),
        "bootstrap_seed": hex(BOOTSTRAP_SEED), "resamples": args.resamples, "checkpoint": raw_info,
        "panel": [info for name, (_, info) in opponents.items() if name not in ("R", "S")],
        "pool": {"ids": list(pool.ids), "sha256": list(pool.sha256), "data_kind": int(kind)},
        "library": duoforge.version(), "commit": commit, "dirty": dirty, "python": platform.python_version(),
        "numpy": np.__version__, "jax": jax.__version__, "jaxlib": jaxlib, "backend": jax.default_backend(),
        "devices": [str(d) for d in jax.devices()], "cpu": cpu_model(), "platform": platform.platform(),
        "xla_flags": os.environ.get("XLA_FLAGS", "")}
    if evidence is not None:
        conditions["book"] = {**book_preview.info(args, evidence),
                              "scope": "candidate preview only; opponents unchanged"}
    if "S" in opponents:  # only then, so raw and panel runs keep their conditions byte for byte
        conditions["scripted"] = True
    conditions["search"] = args.search
    if args.search == "honest":
        conditions.pop("oracle", None)
        conditions.update({"belief": table_info, "w": samples, "lam": args.lam,
                           "leave_one_team_out": "foe pool index mapped to the spread source id"})
    elif "X" in agents:
        conditions["lam"] = args.lam
    os.makedirs(os.path.join(args.out, "raw"), exist_ok=True)

    configs = {}
    with duoforge.Context(data_kind=kind) as ctx:
        team_sheets = None if evidence is None else book_preview.sheets(ctx, pool)
        for opponent, (other, _) in opponents.items():
            base = f"R-vs-{opponent}"
            candidate = book_preview.wrap(raw, evidence, team_sheets, rows, args)
            records = evaluate.play_suite(ctx, pool, rows, candidate, other, args.workers, ARENA_SEED,
                                          max_steps=args.max_steps)
            _write_games(os.path.join(args.out, "raw", f"{base}-games.csv"), records)
            configs[base] = {"agent": "R", "opponent": opponent, "records": records}
            if evidence is not None:
                configs[base]["book"] = candidate.summary(games=len(rows))
            for agent in agents:
                for k, m in km:
                    for s in samples:
                        name = f"{agent}-k{k}m{m}s{s}-vs-{opponent}"
                        factory = lookahead.Lookahead
                        options = {"lam": args.lam}
                        if args.search == "honest":
                            factory = honest.Honest
                            foe_ids = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])
                            options.update({"table": spread,
                                            "exclude_teams": [source_ids.get(pool.ids[int(i)]) for i in foe_ids]})
                        with factory(ctx, raw.model, raw.params, raw.encoder, raw.ext_supported, k=k,
                                                 m=m, s=s, rule=AGENTS[agent], capacity=args.capacity,
                                                 workers=args.workers, **options) as look:
                            player = SearchPlayer(look, name, ARENA_SEED)
                            candidate = book_preview.wrap(player, evidence, team_sheets, rows, args, network=raw)
                            records = evaluate.play_suite(ctx, pool, rows, candidate, other, args.workers,
                                                          ARENA_SEED, max_steps=args.max_steps)
                        decisions = [r for row in sorted(player.records) for r in player.records[row]]
                        raw_dir = os.path.join(args.out, "raw")
                        _write_games(os.path.join(raw_dir, f"{name}-games.csv"), records)
                        with open(os.path.join(raw_dir, f"{name}-decisions.jsonl"), "w", encoding="utf-8") as f:
                            for r in decisions:
                                f.write(json.dumps(_finite(r), allow_nan=False) + "\n")
                        clock = timing(decisions)
                        with open(os.path.join(raw_dir, f"{name}-timing.json"), "w", encoding="utf-8") as f:
                            json.dump(clock, f, indent=1)
                        configs[name] = {"agent": agent, "opponent": opponent, "k": k, "m": m, "s": s,
                                         "rule": AGENTS[agent], "records": records,
                                         "diagnostics": diagnostics(decisions, int(rows.shape[0])), "timing": clock}
                        if evidence is not None:
                            configs[name]["book"] = candidate.summary(games=len(rows))

    summary = {}
    for name, c in configs.items():
        score = scores(c["records"])
        low, high = bootstrap_mean(score, args.resamples)
        out = {k: v for k, v in c.items() if k != "records"}
        out.update({"games": int(score.size), "score": float(score.mean()), "score_95": [low, high],
                    "elo": elo(float(score.mean())), "elo_95": [elo(low), elo(high)],
                    "unfinished": int(c["records"]["unfinished"].sum()),
                    "unresolved": int(c["records"]["unresolved"].sum())})
        if c["agent"] != "R":
            base = scores(configs[f"R-vs-{c['opponent']}"]["records"])
            out["paired_vs_R"] = {"score": float((score - base).mean()),
                                  "score_95": list(bootstrap_paired(score, base, args.resamples)),
                                  "elo": elo(float(score.mean())) - elo(float(base.mean())),
                                  "elo_95": list(_paired_elo(score, base, args.resamples))}
        summary[name] = out
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(_finite({"conditions": conditions, "configs": summary}), f, indent=1, allow_nan=False)
    for name, out in summary.items():
        lo, hi = out["score_95"]
        print(f"{name:>28}  score {out['score']:.3f} [{lo:.3f}, {hi:.3f}]  Elo {out['elo']:7.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
