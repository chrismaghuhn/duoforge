"""The search ladder (issue #440): one search improvement measured against the step before it, paired game by game.

    python -m duoforge_search.ladder --checkpoint MAIN --foe-net FOE (--teams-from POOLNET | --matchup OURS FOE
        [--fill-stat-points smogon]) --step N [--previous P] [--raw] [--h2h] --opponent NAME=PATH [--opponent ...]
        --out DIR [--pairs 1024] [--seed SEED] [--workers 8] [--max-steps 1000] [--previous-run OLD/ladder.json]
        [--latency-run LATENCY/ladder.json] [--paired-with RUN/ladder.json]
    python -m duoforge_search.ladder verdict RUN/ladder.json [--latency-run LATENCY/ladder.json]

The networks stay fixed along the ladder: MAIN (BC6) searches and plays, FOE (BC6) is the foe model in the searched
worlds, and the team pool is POOLNET's (--teams-from: a pool network's config). --matchup is a sanity arm instead: our
team OURS (a registry paste or a packed team) against one fixed foe team FOE (a packed team), the learner always
playing OURS on both seats; a packed team's members without stat points are refused unless --fill-stat-points smogon
gives them their Smogon spread of their nature. A step is a settings dict for
honest.Honest: step N is its base step's settings plus its own delta (STEPS, step_settings); step 0 is the measured
baseline (STEP0: the live settings until 2e went live, owner 2026-10-14), so every recorded run stays reproducible.

Each opponent (a raw greedy network: bc6, bot or ppo) meets the arms "step", "previous" (with --previous) and "R" (with
--raw: MAIN's raw play) over the same suite rows and batch seed, so their games are paired: rows 2k and 2k + 1 are one
team pair, its teams and seats swapped. A searching arm leaves the opponent's own team out of the spread table, as
foe_arena does. --h2h plays step N against the previous step, both searching, over the same rows. --paired-with RUN/
ladder.json pairs step N with a recorded run's step arm on that run's first games, without replaying it (exclusive with
--previous, --h2h and --previous-run; paired_guard checks the recorded run before any network is loaded).

The gates (GATES, verdict()), a pure function of a finished report: strength (the head-to-head's lower bound above 0.50,
with no unresolved game), no harm (each gated opponent, bot and bc6, measured and at least 0.50 at its upper bound
against the previous step), reproduced (each gated opponent's previous arm plays the recorded step arm's games and
decisions, --previous-run), fallbacks (raw fallbacks per gated opponent at most 5 %, or the previous share plus 1 point
where that is above 5 %) and latency (the step's p99 wall seconds per searched decision at most 2.0, measured by an
exclusive latency run, --latency-run: this run shares the machine with its workers). Without a latency run the verdict
is pending: its latency gate and adopt are None. The output directory lies outside the repository; the networks stay
private and the report holds aggregates, per-game scores and decision digests only.
"""
import argparse
import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np

from . import foe_arena

SEED = 0x2026101200000440
OPPONENT_NAMES = ("bc6", "bot", "ppo")
GATED_OPPONENTS = ("bot", "bc6")  # ppo is reported, not gated
GATES = {"lower_bound": 0.50, "no_harm_upper": 0.50, "p99_seconds": 2.0, "fallback_share": 0.05,
         "fallback_over_previous": 0.01}
# Step 0, the ladder's baseline: the live search as every step up to 2 measured it (the approved spec's X, mix with
# lambda 0.5; owner 2026-10-10). Pinned here: the live settings moved on to step 2e (owner, 2026-10-14), step 0 did not.
STEP0 = {"k": 8, "m": 8, "s": 16, "rule": "mix", "lam": 0.5, "species_prior": "count", "capacity": 1024}
STEPS = {"0": {"base": None, "settings": {}},
         # Step 1 (#363): the team preview as a Nash matrix game over the foe network's candidates; 1e and 1x are its
         # controls (the best answer to the foe model, and the live mix rule).
         "1": {"base": "0", "settings": {"preview_mode": "value", "preview_rule": "nash"}},
         "1e": {"base": "0", "settings": {"preview_mode": "value", "preview_rule": "ev"}},
         "1x": {"base": "0", "settings": {"preview_mode": "value", "preview_rule": "mix"}},
         # Step 1b (#440): the turn-1 rollout, the only preview form that gained in #241, its foe seat played by the
         # foe network; "1b" plays its table by the ev rule (the best answer), "1bn" by nash (its control).
         "1b": {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "ev"}},
         "1bn": {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "nash"}},
         # Preview width (owner, 2026-10-13): 1b with one candidate per bring-and-lead combination, every own member
         # brought by at least one (the arena's top 8 were 4 orderings of 2 combinations, none with Gholdengo).
         "1bw": {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "ev", "preview_width": "distinct"}},
         # 1bw corrected (review of #462): the lead seats kept, only the bench order merged.
         "1bws": {"base": "0", "settings": {"preview_mode": "turn1", "preview_rule": "ev", "preview_width": "seats"}},
         # The budget-scaling arms (owner, 2026-10-12): one lever or one fixed combination each. Budget = k * m * s
         # leaves, relative to step 0's 8 * 8 * 16 = 1024 (the factors x2 to x16); capacity = k * m * s, so the leaf
         # buffer matches.
         "b-s32": {"base": "0", "settings": {"s": 32, "capacity": 2048}},
         "b-s64": {"base": "0", "settings": {"s": 64, "capacity": 4096}},
         "b-s128": {"base": "0", "settings": {"s": 128, "capacity": 8192}},
         "b-s256": {"base": "0", "settings": {"s": 256, "capacity": 16384}},
         "b-k16": {"base": "0", "settings": {"k": 16, "capacity": 2048}},
         "b-m16": {"base": "0", "settings": {"m": 16, "capacity": 2048}},
         "b-km16": {"base": "0", "settings": {"k": 16, "m": 16, "capacity": 4096}},
         "b-km16-s64": {"base": "0", "settings": {"k": 16, "m": 16, "s": 64, "capacity": 16384}},
         # Step 2 (#433, predeclared 2026-10-13): 2e, the best answer to the foe model and the worlds (lambda 0, no Nash
         # share), passed every gate (phase B, the README) and is the live search since 2026-10-14 (owner). Its
         # siblings 2d and 2l were screened on search/2-width and did not qualify.
         "2e": {"base": "0", "settings": {"rule": "ev"}}}


def size_refusal(name):
    """Why step `name` is refused before any run, or None: its Bayesian LP is above the size limit (matrix.
    MAX_BAYES_CELLS; owner on #440, 2026-10-13: b-s64 and b-km16 stopped in the exact rescue).
    The struck arms stay declared above."""
    from . import matrix
    settings = step_settings(name)
    if settings["k"] == 1:
        return None
    from . import preview
    most = settings["k"] + (preview.COVER_MAX if settings.get("preview_width", "top") != "top" else 0)
    if settings.get("root_solver", "lp") == "rm" and settings.get("preview_mode", "raw") == "raw":
        return None  # the turns' CFR+ has no tableau (D1, #481); only a preview still solves an LP
    try:
        matrix.check_bayes_size(most, settings["m"], settings["s"], f"step {name!r}")
    except ValueError as err:
        return str(err)
    return None


def step_settings(name):
    """The settings of a step for honest.Honest: STEP0 with the deltas of its base chain applied, base first. A fresh
    dict: STEP0 is never changed. ValueError for an unknown step or a broken base chain."""
    if name not in STEPS:
        raise ValueError(f"unknown step {name!r}: the known steps are {sorted(STEPS)}")
    chain, seen, current = [], set(), name
    while current is not None:
        if current in seen:
            raise ValueError(f"step {name!r}: its base chain loops at {current!r}")
        if current not in STEPS:
            raise ValueError(f"step {current!r}, a base of {name!r}, is unknown")
        seen.add(current)
        chain.append(current)
        current = STEPS[current]["base"]
    settings = copy.deepcopy(STEP0)
    for step in reversed(chain):
        settings.update(copy.deepcopy(STEPS[step]["settings"]))
    return settings


def _pair_bootstrap(per_pair, resamples, seed):
    """The 2.5 and 97.5 percentiles of the means of resampled team pairs (foe_arena.verdict's draw)."""
    if int(resamples) < 1:
        raise ValueError(f"a bootstrap needs resamples (got {resamples})")
    idx = np.random.default_rng(seed).integers(0, per_pair.size, size=(int(resamples), per_pair.size))
    low, high = np.quantile(per_pair[idx].mean(axis=1), (0.025, 0.975))
    return float(low), float(high)


def pair_interval(score, resamples=2000, seed=SEED):
    """The mean score of paired games and its 95 % bootstrap interval over the team pairs: rows 2k and 2k + 1 are one
    pair, averaged first, and the pairs are resampled. {"pairs", "score", "95": [low, high]}."""
    s = np.asarray(score, np.float64).reshape(-1)
    if s.size == 0 or s.size % 2:
        raise ValueError(f"paired games need two rows per team pair (got {s.size} rows)")
    per_pair = s.reshape(-1, 2).mean(axis=1)
    return {"pairs": int(per_pair.size), "score": float(s.mean()),
            "95": list(_pair_bootstrap(per_pair, resamples, seed))}


def paired_h(score_a, score_b, resamples=2000, seed=SEED):
    """The head-to-head h = 0.5 + mean(a - b) / 2 of two arms' paired games (team pairs as in pair_interval), with its
    95 % interval by the same bootstrap over the team pairs (foe_arena.verdict's math)."""
    a = np.asarray(score_a, np.float64).reshape(-1)
    b = np.asarray(score_b, np.float64).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"paired scores need the same rows (got {a.size} and {b.size})")
    if a.size == 0 or a.size % 2:
        raise ValueError(f"paired scores need two rows per team pair (got {a.size} rows)")
    per_pair = (a - b).reshape(-1, 2).mean(axis=1)
    low, high = _pair_bootstrap(per_pair, resamples, seed)
    return {"pairs": int(per_pair.size), "mean": 0.5 + float(per_pair.mean()) / 2,
            "95": [0.5 + low / 2, 0.5 + high / 2]}


def paired_entry(scores):
    """One opponent's paired comparisons from its arms' per-game scores: step against previous, and step against R,
    each when that arm was played (paired_h)."""
    out = {}
    if "previous" in scores:
        out["step_vs_previous"] = paired_h(scores["step"], scores["previous"])
    if "R" in scores:
        out["step_vs_R"] = paired_h(scores["step"], scores["R"])
    return out


def refused_leaves(decisions):
    """The refused leaves of the searched decisions. A record's leaves are (k + the refused pairs dropped by #443) * m
    * s: k counts the kept rows only, refused_pairs lists the dropped ones. Refused are those the engine refused
    (E_UNSUPPORTED). unreconstructible_engine_refused counts the decisions that played raw because of such leaves."""
    searched = [r for r in decisions if r["kind"] == "searched"]
    leaves = sum((r["k"] + len(r.get("refused_pairs", []))) * r["m"] * r["s"] for r in searched)
    refused = sum(r["leaves"]["refused"] for r in searched)
    return {"leaves": int(leaves), "refused": int(refused),
            "decisions_with_refused": sum(r["leaves"]["refused"] > 0 for r in searched),
            "refused_share": refused / leaves if leaves else 0.0,
            "unreconstructible_engine_refused": sum(r["kind"] == "unreconstructible"
                                                    and r.get("reason") == "engine_refused_leaves"
                                                    for r in decisions)}


def duplicate_rows(decisions, tolerance=1e-6):
    """The table rows of the searched decisions that equal an earlier row of their own table: a row counts when its
    entries differ from an earlier row's by at most tolerance (the largest absolute difference). VALUE-equality: a hint
    of redundancy in the search, not a proof of equivalence. Only searched records without preview_eval count; each
    record's table must be k x m (ValueError otherwise). share is 0.0 without rows."""
    records = [r for r in decisions if r["kind"] == "searched" and "preview_eval" not in r]
    rows = duplicates = with_duplicates = 0
    for r in records:
        table = np.asarray(r["table"], np.float64)
        if table.shape != (r["k"], r["m"]):
            raise ValueError(f"a searched record's table is {table.shape}, not k x m = {(r['k'], r['m'])}")
        gap = np.abs(table[:, None, :] - table[None, :, :]).max(axis=2)  # gap[i, j]: row i against row j
        repeated = np.tril(gap <= tolerance, k=-1).any(axis=1)  # row i equals an earlier row j < i
        count = int(repeated.sum())
        rows += table.shape[0]
        duplicates += count
        with_duplicates += int(count > 0)
    return {"decisions": len(records), "decisions_with_duplicates": with_duplicates, "rows": rows,
            "duplicate_rows": duplicates, "share": duplicates / rows if rows else 0.0}


def fallback_allowed(previous_share):
    """The fallback share a step may have against its previous step's share (foe_arena's rule): 5 %, or the previous
    share plus one point where that share is above 5 %."""
    if previous_share <= GATES["fallback_share"]:
        return GATES["fallback_share"]
    return previous_share + GATES["fallback_over_previous"]


def _pooled_share(opponents, arm):
    """The fallback share of an arm over all opponents' non-team decisions (reported, not gated). None when an
    opponent's arm lacks the counts: reports written before fallback_decisions and non_team_decisions were added
    (step 1's) carry the per-opponent shares only, and a pooled share cannot be recovered from shares."""
    if any("fallback_decisions" not in entry["arms"][arm] or "non_team_decisions" not in entry["arms"][arm]
           for entry in opponents.values()):
        return None
    fallbacks = sum(entry["arms"][arm]["fallback_decisions"] for entry in opponents.values())
    non_team = sum(entry["arms"][arm]["non_team_decisions"] for entry in opponents.values())
    return fallbacks / max(1, non_team)


def _check_latency(latency, step_name, commit):
    """ValueError unless the latency run measured this step on this commit. An unknown commit (None) matches nothing."""
    measured = latency["conditions"]["step"]["name"]
    if measured != step_name:
        raise ValueError(f"the latency run measured step {measured!r}, not the step {step_name!r}")
    if commit is None:
        raise ValueError("the commit is unknown (no git checkout): a latency run cannot be matched to the report")
    if latency["conditions"]["commit"] != commit:
        raise ValueError(f"the latency run ran on commit {latency['conditions']['commit']!r}, not on {commit!r}")


def verdict(report, latency=None):
    """The predeclared gates (GATES) of a finished ladder.json, as a pure function of it. report: main's dict, with a
    head-to-head (ValueError without one). latency: an exclusive latency run's ladder.json of the same step and commit
    (ValueError otherwise); without it the latency gate and adopt are None (pending).

    The gates: strength (the head-to-head's lower bound above 0.50, and no unresolved game: evaluate scores one as the
    learner's loss); no_harm (each gated opponent's step against previous at least 0.50 at its upper bound); reproduced
    (each gated opponent's same_games_as_recorded is True); fallback (each gated opponent's step share at most
    fallback_allowed of its previous share); latency (the latency run's p99 at most 2.0 seconds). The inputs and the
    notes come back with the gates."""
    h2h = report["h2h"]
    if h2h is None:
        raise ValueError("the report has no head-to-head: the gates need a run with --h2h")
    step_name, commit = report["conditions"]["step"]["name"], report["conditions"]["commit"]
    if latency is not None:
        _check_latency(latency, step_name, commit)
    opponents = report["opponents"]
    notes = []

    unresolved = int(h2h["unresolved"])
    if unresolved:
        notes.append(f"{unresolved} head-to-head game(s) unresolved: evaluate scores each as the learner's loss, "
                     "so strength fails whatever the interval says")
    strength = h2h["95"][0] > GATES["lower_bound"] and unresolved == 0

    fallback_per = {}
    for name, entry in opponents.items():
        previous = entry["arms"]["previous"]["fallback_share"]
        fallback_per[name] = {"step": entry["arms"]["step"]["fallback_share"], "previous": previous,
                              "allowed": fallback_allowed(previous), "gated": name in GATED_OPPONENTS}
    no_harm = reproduced = fallback = True
    for name in GATED_OPPONENTS:
        entry = opponents.get(name)
        if entry is None:
            notes.append(f"{name}: not measured, so no-harm, reproduction and fallbacks fail")
            no_harm = reproduced = fallback = False
            continue
        vs_previous = entry.get("paired", {}).get("step_vs_previous")  # a gated opponent without a measurement
        if vs_previous is None or vs_previous["95"][1] < GATES["no_harm_upper"]:  # is no evidence of no harm
            no_harm = False
        if entry.get("same_games_as_recorded") is not True:
            reproduced = False
        share = fallback_per[name]
        if share["step"] > share["allowed"] + 1e-12:  # shares are ratios of counts: the tolerance is float noise only
            fallback = False

    if latency is None:
        latency_gate, p99, source = None, None, None
        notes.append("latency pending: adopt waits for the exclusive latency run (--latency-run)")
    else:
        p99 = latency["p99_seconds"]
        latency_gate = p99 is not None and p99 <= GATES["p99_seconds"]
        source = {"run": "latency", "step": latency["conditions"]["step"]["name"],
                  "commit": latency["conditions"]["commit"]}
    pooled = {"step": _pooled_share(opponents, "step"), "previous": _pooled_share(opponents, "previous")}
    if None in pooled.values():
        notes.append("pooled fallback shares not reported: the report has no fallback_decisions or "
                     "non_team_decisions (an old-format report); the fallback gate reads the per-opponent shares")
    gates = {"strength": strength, "no_harm": no_harm, "reproduced": reproduced, "fallback": fallback,
             "latency": latency_gate}
    return {"gates": gates, "adopt": None if latency is None else all(gates.values()),
            "h2h": h2h,
            "paired": {name: entry["paired"]["step_vs_previous"] for name, entry in opponents.items()
                       if "step_vs_previous" in entry.get("paired", {})},
            "fallback": {"per_opponent": fallback_per, "pooled": pooled},
            "p99_seconds": p99, "p99_source": source, "notes": notes}


def wsl_path(path):
    """The WSL spelling of a Windows drive path ("C:/x" -> "/mnt/c/x"); any other path unchanged."""
    if len(path) >= 3 and path[1] == ":" and path[2] in "/\\":
        return f"/mnt/{path[0].lower()}/" + path[3:].replace("\\", "/")
    return path


def _checkout():
    """(commit, dirty) of this checkout. arena._commit runs git in it; under WSL, git cannot follow a Windows worktree's
    .git pointer ("gitdir: C:/..."), so the gitdir the pointer names is given to git as GIT_DIR instead. Under WSL
    `dirty` is best effort only (line-ending config can mark files dirty). --no-optional-locks keeps the status from
    rewriting the Windows index."""
    from . import arena
    commit, dirty = arena._commit()
    if commit is not None:
        return commit, dirty
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(os.path.join(root, ".git"), encoding="utf-8") as f:
            pointer = f.read().strip()
        if not pointer.startswith("gitdir:"):
            return None, None
        env = dict(os.environ, GIT_DIR=wsl_path(pointer[len("gitdir:"):].strip()), GIT_WORK_TREE=root)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, env=env,
                                cwd=root).stdout.strip()
        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True, check=True, env=env, cwd=root).stdout.strip()
        return commit, bool(status)
    except (OSError, subprocess.CalledProcessError):
        return None, None


def same_games(scores_a, scores_b):
    """True when two runs' per-game score arrays are identical (the determinism gate)."""
    a, b = np.asarray(scores_a, np.float64), np.asarray(scores_b, np.float64)
    return a.shape == b.shape and bool(np.array_equal(a, b))


def numpy_simd():
    """NumPy's SIMD dispatch in this process (#484): the targets NPY_DISABLE_CPU_FEATURES disables, NumPy's baseline and
    the dispatch targets found and not found. NumPy picks its exp, log and sum routines at run time (AVX-512 on the AWS
    box's EPYC, AVX2 on the local Ryzen), so two runs whose decisions are to be bit-identical record the same here, and
    ladder_equal.py compares it. NumPy's float64 exp and log have SIMD loops for AVX-512 only: with those off, both run
    the C library's (glibc's) scalar ones, which is why the conditions name the libc as well. None where NumPy does not
    expose it."""
    try:
        from numpy._core import _multiarray_umath as m
    except ImportError:
        return None
    return {"disabled": os.environ.get("NPY_DISABLE_CPU_FEATURES", "").split(), "baseline": list(m.__cpu_baseline__),
            "found": [t for t in m.__cpu_dispatch__ if m.__cpu_features__.get(t)],
            "not_found": [t for t in m.__cpu_dispatch__ if not m.__cpu_features__.get(t)]}


def decisions_digest(decisions):
    """The sha256 hex of every decision as a JSON line [env, step, seat, kind, choice], in (env, step, seat) order: two
    runs that decide alike give the same digest, whatever the order of their records."""
    rows = [[r["env"], r["step"], r["seat"], r["kind"], r.get("choice")] for r in decisions]
    rows.sort(key=lambda row: (row[0], row[1], row[2], json.dumps(row)))
    return hashlib.sha256("\n".join(json.dumps(row) for row in rows).encode("utf-8")).hexdigest()


def games_digests(decisions, games):
    """decisions_digest of each game alone, game g's decisions being those of env g (one game per env in a ladder arm):
    a list of `games` digests, the empty game's digest where a game has no decision. Two runs whose decisions_sha256
    differ name the first game that differs (#484: AWS against local, 2026-10-14). ValueError for an env outside."""
    per_game = [[] for _ in range(games)]
    for r in decisions:
        if not 0 <= int(r["env"]) < games:
            raise ValueError(f"a decision of env {r['env']} outside the arm's {games} games")
        per_game[int(r["env"])].append(r)
    return [decisions_digest(rows) for rows in per_game]


def recorded_reproduction(scores, digest, recorded_arm, recorded_dir, name):
    """Whether this run's previous arm plays the recorded step arm's games: True when the per-game scores and the digest
    of the decisions both match, False when either differs. None when the recorded run has no such arm, or when its
    decisions cannot be checked (no stored digest and no decision file step-NAME-decisions.jsonl in recorded_dir):
    never True without the evidence."""
    if recorded_arm is None:
        return None
    if not same_games(scores, recorded_arm["scores"]):
        return False
    recorded = recorded_arm.get("decisions_sha256")
    if recorded is None:
        path = os.path.join(recorded_dir, f"step-{name}-decisions.jsonl")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            recorded = decisions_digest([json.loads(line) for line in f if line.strip()])
    return recorded == digest


def paired_guard(recorded, seed, pairs, max_steps, digests):
    """SystemExit naming the field unless this run can be paired with the recorded run (--paired-with), checked before
    any network is loaded: the same seed and max_steps; at least this run's pairs (this run plays the recorded run's
    first games); the same sha256 prefix of main, foe, teams and every opponent of this run; and a recorded step arm for
    each opponent with at least 2 * pairs games. digests: role -> this run's sha256 hex."""
    conditions = recorded.get("conditions", {})
    for field, value in (("seed", hex(seed)), ("max_steps", max_steps)):
        if conditions.get(field) != value:
            raise SystemExit(f"--paired-with's {field} is {conditions.get(field)!r}, this run's is {value!r}")
    recorded_pairs = conditions.get("pairs")
    if not isinstance(recorded_pairs, int) or recorded_pairs < pairs:
        raise SystemExit(f"--paired-with's pairs is {recorded_pairs!r}, this run's is {pairs!r}: "
                         "the recorded run needs at least as many")
    sha = conditions.get("sha256_prefix", {})
    for role, digest in digests.items():
        if sha.get(role) != digest[:12]:
            raise SystemExit(f"--paired-with's sha256_prefix of {role} is {sha.get(role)!r}, "
                             f"this run's is {digest[:12]!r}")
    opponents = recorded.get("opponents", {})
    for role in digests:
        if not role.startswith("opponent "):
            continue
        name = role[len("opponent "):]
        arm = opponents.get(name, {}).get("arms", {}).get("step")
        if arm is None:
            raise SystemExit(f"--paired-with's run has no step arm for opponent {name!r}: nothing to pair with")
        games = len(arm.get("scores", []))
        if games < 2 * pairs:
            raise SystemExit(f"--paired-with's step arm of {name!r} has {games} games, this run needs {2 * pairs}")


def paired_against_recorded(score, recorded, name, pairs):
    """step_vs_recorded: this run's step scores against the recorded run's step arm of the same opponent, on the same
    games (its first 2 * pairs games; paired_guard checked there are that many). The recorded step is not replayed."""
    old = recorded["opponents"][name]["arms"]["step"]["scores"][:2 * pairs]
    return paired_h(score, old)


def paired_with_condition(recorded, path):
    """The conditions' record of --paired-with: the recorded step's name and commit and the file's basename only."""
    return {"step": recorded["conditions"]["step"]["name"], "commit": recorded["conditions"]["commit"],
            "file": os.path.basename(path)}


def wall_seconds(decisions):
    """The p50, p95, p99 and max wall seconds of the searched decisions; None without any."""
    wall = np.array([r["wall"] for r in decisions if r["kind"] == "searched"], np.float64)
    if wall.size == 0:
        return None
    return {q: float(np.percentile(wall, v)) for q, v in (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))}


def _summary(records, games, decisions=None, seconds=None):
    """One arm on one opponent: the per-game scores, their pair interval, the unfinished and unresolved games and, for
    a searching arm (decisions given), its decision shares and digest, refused leaves, wall times and diagnostics."""
    from . import arena  # JAX: imported where a run needs it, not where the pure functions are used
    scores = arena.scores(records)
    out = {"scores": [float(x) for x in scores], "pair_interval": pair_interval(scores),
           "unfinished": int(records["unfinished"].sum()), "unresolved": int(records["unresolved"].sum())}
    if decisions is not None:
        non_team = [r for r in decisions if r["kind"] != "team"]
        out.update({"searched": sum(r["kind"] == "searched" for r in decisions),
                    "fallback_share": foe_arena.fallback_share(decisions),
                    "fallback_decisions": sum(r["kind"] in foe_arena.FALLBACK_KINDS for r in non_team),
                    "non_team_decisions": len(non_team), "decisions_sha256": decisions_digest(decisions),
                    "games_sha256": games_digests(decisions, games),
                    "refused_leaves": refused_leaves(decisions), "wall_seconds": wall_seconds(decisions),
                    "duplicate_rows": duplicate_rows(decisions)})
        if decisions:
            out["diagnostics"] = arena.diagnostics(decisions, games)
    if seconds is not None:
        out["seconds"] = seconds
    return out


MATCHUP_LABELS = ("ours", "foe")
FILL_STAT_POINTS = ("smogon",)


def matchup_rows(pairs):
    """The suite rows of --matchup: ours (team 0) against the foe (team 1) in every game, the learner always team 0.
    Pair k is rows 2k (ours on seat 0) and 2k + 1 (ours on seat 1), both of game k. ValueError for fewer than a pair."""
    from duoforge_learn import suite
    if pairs < 1:
        raise ValueError(f"a matchup needs at least one pair (got {pairs})")
    rows = []
    for k in range(pairs):
        rows += [(0, 1, 0, k), (1, 0, 1, k)]
    return np.array(rows, dtype=suite.SUITE)


def _packed_member(s, name):
    """A member dict (teams.parse's shape) of one set unpacked by duoforge_live.teams.unpack; ValueError for a level
    other than 50 (battles are at level 50) or a gender other than M, F or empty."""
    if s["level"] != 50:
        raise ValueError(f"{name}: {s['name']} is at level {s['level']}: battles are at level 50")
    if s["gender"] not in ("", "M", "F"):
        raise ValueError(f"{name}: {s['name']} has the gender {s['gender']!r}: M, F or empty")
    return {"species": s["species"], "gender": s["gender"] or None, "item": s["item"] or None,
            "ability": s["ability"], "nature": s["nature"], "moves": list(s["moves"]), "stat_points": list(s["evs"])}


def read_team(path):
    """(members, packed, sha256 of the file's bytes). A packed team (Showdown's: its stripped content has "|" and no
    line starts with "Ability:") is unpacked into members; any other file is a registry paste (teams.parse). The
    file name is all a message names of the file."""
    from duoforge import teams
    from duoforge_live import teams as live
    with open(path, "rb") as f:
        raw = f.read()
    text, name = raw.decode("utf-8"), os.path.basename(path)
    stripped = text.strip()
    packed = "|" in stripped and not any(line.strip().startswith("Ability:") for line in stripped.splitlines())
    digest = hashlib.sha256(raw).hexdigest()
    if not packed:
        return teams.parse(text, name), False, digest
    return [_packed_member(s, name) for s in live.unpack(stripped)], True, digest


def fill_stat_points(members, table):
    """(members, filled): a copy of the members, and for each member whose stat points are all zero, its stat points
    become the highest-weight spread of its species in the table (the shape of smogon_spreads.load_table()) among the
    spreads of its own nature; ties keep the table's order. filled lists {"species", "nature", "spread"} per filled
    member. SystemExit naming the member for a species the table lacks or a nature it has no spread of: another nature
    or a default spread is never guessed."""
    from duoforge import data
    out, filled = copy.deepcopy(members), []
    for k, member in enumerate(out):
        if any(member["stat_points"]):
            continue
        label = f"member {k + 1} ({member['species']})"
        entry = table["species"].get(data.to_id(member["species"]))
        if entry is None:
            raise SystemExit(f"{label}: the Smogon table has no spreads for this species (--fill-stat-points)")
        best = None
        for nature, spread, weight in entry["spreads"]:
            if nature == member["nature"] and (best is None or weight > best[1]):
                best = (spread, weight)
        if best is None:
            raise SystemExit(f"{label}: the Smogon table has no spread of the nature {member['nature']}")
        member["stat_points"] = [int(x) for x in best[0].split("/")]
        filled.append({"species": member["species"], "nature": member["nature"], "spread": best[0]})
    return out, filled


def matchup_teams(ours, foe, fill=None):
    """The two teams of --matchup as {"ours": ..., "foe": ...}, each {"members", "packed", "sha256", "filled"}: the
    read_team of each file. A member without stat points is refused by SystemExit naming it, unless fill is "smogon",
    which gives it its Smogon spread (fill_stat_points)."""
    from . import smogon_spreads
    out = {}
    for label, path in zip(MATCHUP_LABELS, (ours, foe)):
        members, packed, digest = read_team(path)
        zero = [f"member {k + 1} ({m['species']})" for k, m in enumerate(members) if not any(m["stat_points"])]
        filled = []
        if zero:
            if fill is None:
                raise SystemExit(f"the {label} team has members without stat points ({', '.join(zero)}): give "
                                 "--fill-stat-points smogon for their Smogon spreads, or stat points in the team")
            members, filled = fill_stat_points(members, smogon_spreads.load_table())
        out[label] = {"members": members, "packed": packed, "sha256": digest, "filled": filled}
    return out


def matchup_pool(ctx, matchup):
    """The two-team pool of --matchup under the context: ours (team 0) and the foe (team 1). Each side is set up
    by teams.side_setup (a name the context does not have: SystemExit) and must pass teams.check."""
    import duoforge
    from duoforge import teams
    sides = []
    for label in MATCHUP_LABELS:
        try:
            side = teams.side_setup(ctx, matchup[label]["members"], label)
        except teams.TeamError as err:
            raise SystemExit(str(err)) from None
        status = teams.check(ctx, side)
        if status != 0:
            raise SystemExit(f"the {label} team is refused under this context's data kind: "
                             f"{duoforge.status_name(status)}")
        sides.append(side)
    return teams.TeamPool.from_setups(MATCHUP_LABELS, sides)


def _opponents(items):
    """NAME=PATH items as {name: path}: known names, each at most once, at least one."""
    out = {}
    for item in items:
        name, separator, path = item.partition("=")
        if not separator or not path:
            raise SystemExit(f"--opponent {item!r} is not NAME=PATH")
        if name not in OPPONENT_NAMES:
            raise SystemExit(f"unknown opponent {name!r}: one of {', '.join(OPPONENT_NAMES)}")
        if name in out:
            raise SystemExit(f"opponent {name!r} is given twice")
        out[name] = path
    if not out:
        raise SystemExit("give at least one --opponent NAME=PATH")
    return out


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main_verdict(argv):
    """`verdict RUN/ladder.json [--latency-run L/ladder.json]`: the gates of a finished run, printed and written
    beside it as verdict.json. It reads JSON files only: no network and no library."""
    p = argparse.ArgumentParser(prog="python -m duoforge_search.ladder verdict",
                                description="the gates of a finished ladder run")
    p.add_argument("run", metavar="RUN/ladder.json")
    p.add_argument("--latency-run", metavar="LATENCY/ladder.json",
                   help="the exclusive latency run of the same step and commit: its p99 is the latency gate")
    args = p.parse_args(argv)
    report = _load_json(args.run)
    latency = None if args.latency_run is None else _load_json(args.latency_run)
    try:
        result = verdict(report, latency)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    text = json.dumps(result, indent=1, allow_nan=False)
    with open(os.path.join(os.path.dirname(os.path.abspath(args.run)), "verdict.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["verdict"]:
        return main_verdict(argv[1:])
    p = argparse.ArgumentParser(prog="python -m duoforge_search.ladder", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="the main network (BC6): it searches; R is its raw play")
    p.add_argument("--foe-net", required=True, help="the foe model in the searched worlds (BC6)")
    p.add_argument("--teams-from", help="a pool network: its config's teams are the suite's pool")
    p.add_argument("--matchup", nargs=2, metavar=("OURS", "FOE"),
                   help="instead of --teams-from: our team OURS (a registry paste or a packed team) against the foe "
                        "team FOE (a packed team); the learner always plays OURS")
    p.add_argument("--fill-stat-points", choices=FILL_STAT_POINTS,
                   help="smogon: a --matchup member without stat points takes its Smogon spread of its nature")
    p.add_argument("--step", required=True, help="the step measured (STEPS)")
    p.add_argument("--previous", help="the previous step: the paired comparison and the head-to-head's opponent")
    p.add_argument("--raw", action="store_true", help="add arm R: the main network's raw play")
    p.add_argument("--h2h", action="store_true", help="step against previous, both searching, over the same rows")
    p.add_argument("--opponent", action="append", default=[], metavar="NAME=PATH",
                   help="a raw greedy opponent: bc6, bot or ppo (each once)")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--pairs", type=int, default=1024)
    p.add_argument("--seed", type=lambda text: int(text, 0), default=SEED)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--previous-run", metavar="LADDER.JSON",
                   help="a recorded run: the previous arm's games must equal its step arm's games")
    p.add_argument("--latency-run", metavar="LATENCY/ladder.json",
                   help="an exclusive latency run of this step on this commit: its p99 is the latency gate "
                        "(without it the verdict is pending)")
    p.add_argument("--paired-with", metavar="RUN/ladder.json",
                   help="a recorded run: this step is paired with its step arm on the same games (its first games), "
                        "without replaying the recorded step; exclusive with --previous, --h2h and --previous-run")
    args = p.parse_args(argv)
    if args.paired_with is not None:
        for flag, given in (("--previous", args.previous), ("--h2h", args.h2h), ("--previous-run", args.previous_run)):
            if given:
                raise SystemExit(f"--paired-with excludes {flag}: it pairs the step with a recorded step arm")

    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    opponents = _opponents(args.opponent)
    if (args.teams_from is None) == (args.matchup is None):
        raise SystemExit("give exactly one of --teams-from (a pool network's teams) and --matchup OURS FOE")
    if args.fill_stat_points is not None and args.matchup is None:
        raise SystemExit("--fill-stat-points applies to --matchup only")
    if args.h2h and args.matchup is not None:  # the previous step, searching as the foe team, would know our spreads
        raise SystemExit("--h2h is not supported with --matchup: no matchup team has a registry id to leave out of "
                         "the searching foe's belief")
    matchup = None if args.matchup is None else matchup_teams(*args.matchup, fill=args.fill_stat_points)
    if args.h2h and args.previous is None:
        raise SystemExit("--h2h needs --previous (the step it plays against)")
    if args.previous_run is not None and args.previous is None:
        raise SystemExit("--previous-run needs --previous")
    if args.latency_run is not None and not args.h2h:
        raise SystemExit("--latency-run needs --h2h: the latency gate belongs to the verdict of a head-to-head")
    try:
        step_cfg = step_settings(args.step)
        previous_cfg = None if args.previous is None else step_settings(args.previous)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    for name in (args.step, args.previous):
        refusal = None if name is None else size_refusal(name)
        if refusal is not None:
            raise SystemExit(refusal)
    recorded = recorded_dir = None
    if args.previous_run is not None:  # every check against the recorded run runs before any network is loaded
        recorded, recorded_dir = _load_json(args.previous_run), os.path.dirname(os.path.abspath(args.previous_run))
        name = recorded["conditions"]["step"]["name"]
        if name != args.previous:
            raise SystemExit(f"--previous-run measured step {name!r}, not the previous step {args.previous!r}")
        expected = {"seed": hex(args.seed), "pairs": args.pairs, "max_steps": args.max_steps, "games": 2 * args.pairs}
        for field, value in expected.items():  # a pair is two rows: the games of this run are 2 * pairs
            if recorded["conditions"].get(field) != value:
                raise SystemExit(f"--previous-run's {field} is {recorded['conditions'].get(field)!r}, "
                                 f"this run's is {value!r}")
    paired_run = None if args.paired_with is None else _load_json(args.paired_with)  # loaded before any network
    from . import arena
    paths = {"main": args.checkpoint, "foe": args.foe_net,  # a matchup has no pool network: its teams are hashed
             **({"teams": args.teams_from} if args.teams_from is not None else {}),  # in its conditions instead
             **{f"opponent {name}": path for name, path in opponents.items()}}
    digests = {role: arena._sha256(path) for role, path in paths.items()}
    if paired_run is not None:  # the same seed, pairs, networks and opponents: refused before any game or network
        paired_guard(paired_run, args.seed, args.pairs, args.max_steps, digests)
    if recorded is not None:  # the networks and the pool must be the recorded ones. An opponent the recorded run lacks
        # is allowed (its reproduction is None).
        sha = recorded["conditions"].get("sha256_prefix", {})
        roles = [role for role in ("main", "foe", "teams") if role in digests]
        for role in roles + [role for role in digests if role.startswith("opponent ") and role in sha]:
            if sha.get(role) != digests[role][:12]:
                raise SystemExit(f"--previous-run's sha256_prefix of {role} is {sha.get(role)!r}, "
                                 f"this run's is {digests[role][:12]!r}")
    commit, dirty = _checkout()  # git: slow under WSL on a Windows worktree, so after the guards that need none of it
    latency = None if args.latency_run is None else _load_json(args.latency_run)
    if latency is not None:
        try:
            _check_latency(latency, args.step, commit)
        except ValueError as err:
            raise SystemExit(str(err)) from None

    import duoforge
    from duoforge import _layout, teams
    from duoforge_learn import checkpoint as ck, evaluate
    from . import honest

    C = _layout.CONSTANTS

    def load(path):
        params, config = ck.load_trained(path)
        return {"model": ck.trained_model(config, params), "params": params, "encoder": ck.encoder_of(config),
                "ext": ck.ext_supported_of(config)}

    teams_config = None
    if args.teams_from is not None:
        _, teams_config = ck.load_trained(args.teams_from)
        if teams_config.get("data", {}).get("kind") != "pool":
            raise SystemExit("--teams-from's teams are no pool (its config's data kind must be pool)")
    main_net, foe_net = load(args.checkpoint), load(args.foe_net)
    opponent_nets = {name: load(path) for name, path in opponents.items()}
    foe_tuple = (foe_net["model"], foe_net["params"], foe_net["encoder"], foe_net["ext"])
    os.makedirs(args.out, exist_ok=True)

    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        if matchup is None:
            pool = teams.load(ctx, teams_config["teams"]["ids"])
            rows = foe_arena.games(len(pool.ids), args.pairs, args.seed)
        else:
            pool = matchup_pool(ctx, matchup)
            rows = matchup_rows(args.pairs)
        table, source_ids, table_info = honest.live_spread_table(ctx)
        if recorded is not None and recorded["conditions"].get("table_sha256") != table_info["sha256"]:
            raise SystemExit(f"--previous-run's table_sha256 is {recorded['conditions'].get('table_sha256')!r}, "
                             f"this run's is {table_info['sha256']!r}")
        if paired_run is not None and paired_run["conditions"].get("table_sha256") != table_info["sha256"]:
            raise SystemExit(f"--paired-with's table_sha256 is {paired_run['conditions'].get('table_sha256')!r}, "
                             f"this run's is {table_info['sha256']!r}")
        learner_team = np.where(rows["learner_seat"] == 0, rows["side0"], rows["side1"])
        opponent_team = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])

        def excluded(team_indices):
            return [source_ids.get(pool.ids[int(i)]) for i in team_indices]

        def searcher(step_name, exclude):
            options = dict(step_settings(step_name), table=table, exclude_teams=exclude, workers=args.workers,
                           foe_net=foe_tuple)
            return honest.Honest(ctx, main_net["model"], main_net["params"], main_net["encoder"], main_net["ext"],
                                 **options)

        def play_search(arm, step_name, opponent_player):
            with searcher(step_name, excluded(opponent_team)) as search:
                player = arena.SearchPlayer(foe_arena.Timed(search), arm, args.seed)
                records = evaluate.play_suite(ctx, pool, rows, player, opponent_player, args.workers, args.seed,
                                              max_steps=args.max_steps)
            return records, [r for row in sorted(player.records) for r in player.records[row]]

        arm_steps = [("step", args.step)] + ([("previous", args.previous)] if args.previous is not None else [])
        raw_player = evaluate.Player(main_net["model"], main_net["params"], main_net["encoder"], "R", main_net["ext"])
        opponent_out, pooled = {}, {"step": [], "previous": []}
        for name, net in opponent_nets.items():
            opponent_player = evaluate.Player(net["model"], net["params"], net["encoder"], name, net["ext"])
            arms, scores = {}, {}
            for arm, step_name in arm_steps:
                started = time.perf_counter()
                records, decisions = play_search(arm, step_name, opponent_player)
                seconds = time.perf_counter() - started
                pooled[arm].extend(decisions)
                with open(os.path.join(args.out, f"{arm}-{name}-decisions.jsonl"), "w", encoding="utf-8") as f:
                    for r in decisions:
                        f.write(json.dumps(arena._finite(r), allow_nan=False) + "\n")
                arms[arm] = _summary(records, rows.shape[0], decisions, seconds)
                scores[arm] = arena.scores(records)
            if args.raw:
                started = time.perf_counter()
                records = evaluate.play_suite(ctx, pool, rows, raw_player, opponent_player, args.workers, args.seed,
                                              max_steps=args.max_steps)
                arms["R"] = _summary(records, rows.shape[0], None, time.perf_counter() - started)
                scores["R"] = arena.scores(records)
            entry = {"arms": arms, "paired": paired_entry(scores),
                     "opponent_is_foe_model": digests[f"opponent {name}"] == digests["foe"]}
            if paired_run is not None:
                entry["paired"]["step_vs_recorded"] = paired_against_recorded(scores["step"], paired_run, name,
                                                                              args.pairs)
                entry["paired_with"] = {"step": paired_run["conditions"]["step"]["name"],
                                        "commit": paired_run["conditions"]["commit"], "pairs": args.pairs}
            if recorded is not None:  # the previous step rerun on this code plays the recorded step arm's games
                old = recorded.get("opponents", {}).get(name, {}).get("arms", {}).get("step")
                entry["same_games_as_recorded"] = recorded_reproduction(
                    scores["previous"], arms["previous"]["decisions_sha256"], old, recorded_dir, name)
            opponent_out[name] = entry

        h2h = None
        if args.h2h:
            with searcher(args.step, excluded(opponent_team)) as learner_search, \
                    searcher(args.previous, excluded(learner_team)) as opponent_search:
                learner = arena.SearchPlayer(foe_arena.Timed(learner_search), "step", args.seed)

                class SearchingOpponent(evaluate.Player):
                    """play_suite takes an evaluate.Player as its opponent and calls its indices; the searching
                    player has the same interface, so it is wrapped rather than changed."""

                    def __init__(self, player):
                        super().__init__(None, None, None, player.name)
                        self.player = player

                    def indices(self, batch, choices, step=None, seats=None, last_step=None):
                        return self.player.indices(batch, choices, step=step, seats=seats, last_step=last_step)

                opponent = SearchingOpponent(arena.SearchPlayer(foe_arena.Timed(opponent_search), "previous",
                                                                args.seed))
                records = evaluate.play_suite(ctx, pool, rows, learner, opponent, args.workers, args.seed,
                                              max_steps=args.max_steps)
            h2h = {**pair_interval(arena.scores(records)), "unfinished": int(records["unfinished"].sum()),
                   "unresolved": int(records["unresolved"].sum())}
        pool_teams, in_table = len(pool.ids), sum(x is not None for x in excluded(opponent_team))

    p99 = (wall_seconds(pooled["step"]) or {}).get("p99")
    matchup_out = None  # hash prefixes only: the team files are private paths, never written
    if matchup is not None:
        matchup_out = {"ours_sha256_prefix": matchup["ours"]["sha256"][:12],
                       "foe_sha256_prefix": matchup["foe"]["sha256"][:12],
                       "ours_packed": matchup["ours"]["packed"], "foe_packed": matchup["foe"]["packed"],
                       "fill": args.fill_stat_points,
                       "filled": matchup["ours"]["filled"] + matchup["foe"]["filled"]}
    conditions = {
        "seed": hex(args.seed), "pairs": args.pairs, "max_steps": args.max_steps, "matchup": matchup_out,
        "filled_count": None if matchup_out is None else len(matchup_out["filled"]),
        "step": {"name": args.step, "settings": step_cfg},
        "previous": None if args.previous is None else {"name": args.previous, "settings": previous_cfg},
        "arms": [arm for arm, _ in arm_steps] + (["R"] if args.raw else []), "h2h": args.h2h,
        "gates": GATES, "commit": commit, "dirty": dirty, "library": duoforge.version(), "cpu": arena.cpu_model(),
        "numpy_simd": numpy_simd(), "libc": list(platform.libc_ver()),
        "encoders": {"main": main_net["encoder"], "foe": foe_net["encoder"],
                     **{f"opponent {name}": net["encoder"] for name, net in opponent_nets.items()}},
        "sha256_prefix": {role: digest[:12] for role, digest in digests.items()},
        "pool_teams": pool_teams, "games": int(rows.shape[0]), "table_sha256": table_info["sha256"],
        "opponent_team_in_table": in_table,
        "paired_with": None if paired_run is None else paired_with_condition(paired_run, args.paired_with),
    }
    report = {"conditions": conditions, "opponents": opponent_out, "h2h": h2h, "p99_seconds": p99, "verdict": None}
    if args.h2h:
        report["verdict"] = verdict(report, latency)
    with open(os.path.join(args.out, "ladder.json"), "w", encoding="utf-8") as f:
        json.dump(arena._finite(report), f, indent=1, allow_nan=False)
    gates = report["verdict"] or {}
    print(json.dumps(arena._finite({
        "opponents": {name: {"scores": {arm: entry["arms"][arm]["pair_interval"]["score"] for arm in entry["arms"]},
                             "paired": entry["paired"]} for name, entry in opponent_out.items()},
        "h2h": h2h, "p99_seconds": p99, "gates": gates.get("gates"), "adopt": gates.get("adopt")}),
        indent=1, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
