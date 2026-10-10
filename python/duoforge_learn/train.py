"""Self-play PPO training (decisions 0014, 0017).

    python -m duoforge_learn.train --envs 256 --workers 16 --minutes 60 --out runs/trial
    python -m duoforge_learn.train --resume runs/trial --minutes 60

Collects --rollout batch steps, updates the policy with PPO and logs one
JSON line per update to <out>/log.jsonl. The first --self-play-share of the
environments play self-play; the others play the learner against frozen
snapshots of itself in --league-slots slots (league.py), which reload a
snapshot drawn from the run's pool every --slot-refresh updates, at an
episode boundary: uniformly, or with --league-pfsp-share and
--league-anchor-share partly by prioritized fictitious self-play over the
league's win rates and partly from the earliest snapshots (league.Refill).
Snapshots go to <out>/params-<update>.npz (checkpoint format 2) every
--snapshot-every updates and at each evaluation; every --eval-every updates
the greedy policy plays the evaluation suite (suite.py) against the random
baseline and the previous evaluation's parameters (vs_previous above 0.5: still improving), with a score per team.

The run state (runstate.py) is saved every --save-minutes, at the end and
after SIGTERM or SIGINT (then the run ends at the next update boundary).
--resume continues a run from it: running episodes are dropped and every
environment starts its next episode, so no battle seed repeats; options
given on the command line replace the saved ones where a resume allows it.
"""
import argparse
import contextlib
import json
import math
import os
import re
import sys
import time

import jax
import numpy as np

import duoforge
from duoforge import _layout, features, teams

from . import budget_match, checkpoint, evaluate, league, ledger, pairing, policy, ppo, runstate, schedule, suite
from .returns import gae, samples_of
from .selfplay import SelfPlay

_DIMS = ("embed", "member", "position", "hidden", "layers", "option")
# Options a resume may change; any other option that differs from the saved run is refused.
_RESUMABLE = ("envs", "workers", "minutes", "updates", "self_play_share", "league_slots", "snapshot_every",
              "slot_refresh", "entropy", "eval_every", "eval_games", "eval_budget", "save_minutes", "teams",
              "team_weights", "teams_root", "opponent_precision", "minibatch", "learning_rate_schedule", "kl_ref",
              "kl_coef", "kl_refresh", "stop_cpu_core_seconds", "stop_gpu_seconds", "update_gpu_share",
              "act_gpu_share", "league_pfsp_share", "league_anchor_share", "league_anchors", "pfsp_weighting",
              "pfsp_min_weight", "pfsp_prior", "pfsp_prior_games")
# The refill options (league.Refill) and their defaults, which reproduce the uniform refills of the runs before them;
# a run saves one only where it differs from its default, so a run without them saves what such a run saved.
_REFILL = {"league_pfsp_share": ("pfsp_share", 0.0), "league_anchor_share": ("anchor_share", 0.0),
           "league_anchors": ("anchors", 1), "pfsp_weighting": ("weighting", "hard"),
           "pfsp_min_weight": ("min_weight", 0.05), "pfsp_prior": ("prior", 0.5),
           "pfsp_prior_games": ("prior_games", 4.0)}
DATA_KINDS = {"closure": _layout.CONSTANTS["DUOFORGE_DATA_KIND_CLOSURE"],
              "team_c": _layout.CONSTANTS["DUOFORGE_DATA_KIND_TEAM_C"],
              "pool": _layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]}
EVAL_SEED = 0x2026100200000020


def model_config(args):
    """The model configuration of the command line: v1 (with --hidden) or a
    v2 preset with its dimension overrides."""
    dims = {k: getattr(args, k) for k in _DIMS if getattr(args, k) is not None}
    if args.model == "v1":
        extra = sorted(set(dims) - {"hidden"})
        if extra:
            raise SystemExit(f"model v1 takes only --hidden, not {extra}")
        return {**policy.V1_DEFAULT, **dims}
    return policy.v2_config(args.preset, **dims)


def _share(text):
    """--update-gpu-share: a number, or 'match' (budget_match)."""
    return text if text == "match" else float(text)


def _on_default(index, share):
    """Whether the index-th call of a share runs on the default device: floor((index + 1) * share) > floor(index *
    share), so share 1 is every call, 0 none, and a resume continues the pattern."""
    return math.floor((index + 1) * share) > math.floor(index * share)


def _rows(o, e):
    return (o.obs.reshape(2 * e, -1), o.slots.reshape((2 * e,) + o.slots.shape[2:]),
            o.mask.reshape((2 * e,) + o.mask.shape[2:]), o.is_team.reshape(-1))


def collect(env, params, act, key, steps, state=None, opponents=None, timings=None):
    """One rollout: arrays over (T, E, 2) and the bootstrap values. With a
    league (state, opponents), the opponent seat of every league
    environment plays its slot's snapshot. timings (a dict) receives the
    seconds of the engine (step and query), the encoder (observe) and the
    policy (act, opponents)."""
    e = env.batch.envs
    clock = time.perf_counter
    spent = {"t_engine": 0.0, "t_encode": 0.0, "t_policy": 0.0}
    keep = {k: [] for k in ("obs", "slots", "mask", "is_team", "acting", "actions", "logp", "values", "rewards",
                            "done")}
    episodes = 0
    playing = state is not None and state.has_league
    if playing:
        league_envs = np.flatnonzero(~state.self_play)
        opponent_rows = 2 * league_envs + (1 - state.learner_seat[league_envs])
    for _ in range(steps):
        t0 = clock()
        o = env.observe()
        t1 = clock()
        key, sub, other = jax.random.split(key, 3)
        obs, slots, mask, is_team = _rows(o, e)
        actions, logp, values = act(params, sub, obs, slots, mask, is_team)
        actions = np.array(actions).reshape(e, 2)
        if playing:
            r = opponent_rows
            chosen = opponents.act(other, obs[r], slots[r], mask[r], is_team[r], state.slot_of[league_envs])
            actions.reshape(-1)[r] = chosen
        logp, values = np.asarray(logp), np.asarray(values)
        t2 = clock()
        rewards, done = env.step(actions)
        t3 = clock()
        spent["t_encode"] += t1 - t0
        spent["t_policy"] += t2 - t1
        spent["t_engine"] += t3 - t2
        episodes += int(done.sum())
        for name, value in (("obs", o.obs), ("slots", o.slots), ("mask", o.mask), ("is_team", o.is_team),
                            ("acting", o.acting), ("actions", actions), ("logp", np.asarray(logp).reshape(e, 2)),
                            ("values", np.asarray(values).reshape(e, 2)), ("rewards", rewards), ("done", done)):
            keep[name].append(value)
    o = env.observe()
    key, sub = jax.random.split(key)
    _, _, bootstrap = act(params, sub, *_rows(o, e))
    rollout = {k: np.stack(v) for k, v in keep.items()}
    if timings is not None:
        timings.update(spent)
    return rollout, np.asarray(bootstrap).reshape(e, 2), episodes, key


def save(path, params, config):
    """A format-1 checkpoint (decision 0014): params with a free config, as
    the runs of 2026-10-02 wrote them; new runs write format 2
    (checkpoint.save)."""
    flat, _ = jax.tree_util.tree_flatten_with_path(params)
    arrays = {jax.tree_util.keystr(k): np.asarray(v) for k, v in flat}
    np.savez(path, config=json.dumps(config), **arrays)


def _teams_json(pool):
    return {"ids": list(pool.ids), "sha256": list(pool.sha256), "weights": [float(w) for w in pool.weights]}


def _data_json(kind, context):
    return {"kind": kind, "fingerprint": context.fingerprint().hex()}


def snapshot_config(train_config, model_cfg, context, pool, update, decisions, encoder, ext_supported,
                    layout=(features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)):
    """The format-2 config of a snapshot of this run; layout: the (feature, slot feature) names its network reads
    (the current encoder's, or the init's own under --keep-init-encoder)."""
    return {"model": model_cfg, "encoder": encoder, "ext_supported": ext_supported,
            "ids": checkpoint.ids_of(context), "features": list(layout[0]),
            "slot_features": list(layout[1]),
            "data": _data_json(train_config["data_kind"], context),
            "teams": _teams_json(pool), "update": update, "decisions": decisions, "train": train_config}


def _parser(suppress=False):
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.train", description="Self-play PPO training.",
                                argument_default=argparse.SUPPRESS if suppress else None)

    def add(name, **kw):
        if suppress:
            kw.pop("default", None)
        p.add_argument(name, **kw)

    add("--envs", type=int, default=256)
    add("--workers", type=int, default=16)
    add("--rollout", type=int, default=32, help="batch steps per update")
    add("--minutes", type=float, default=60.0, help="stop after this time (0: --updates only)")
    add("--updates", type=int, default=0, help="stop after this many updates in all (0: --minutes only)")
    add("--epochs", type=int, default=4)
    add("--minibatch", type=int, default=4096)
    add("--learning-rate", type=float, default=3e-4)
    add("--learning-rate-schedule", default="1",
        help="a multiplier of the learning rate over learner decisions, as --entropy (for example 0:1,200M:0.1)")
    add("--learning-rate-over", choices=("decisions", "budget"), default="decisions",
        help="the axis of --learning-rate-schedule: learner decisions, or (with --update-gpu-share match) permille "
             "of --stop-cpu-core-seconds spent by the ledger (0:1,900:0.1: decayed to 0.1 at 90 %%)")
    add("--kl-ref", default=None, help="the reference policy of the KL anchor: a checkpoint of the same model, or "
                                       "'magnet', a frozen copy of the learner refreshed every --kl-refresh updates")
    add("--kl-refresh", type=int, default=500, help="updates between the magnet's refreshes (--kl-ref magnet)")
    add("--kl-coef", type=float, default=0.0, help="the weight of KL(policy || --kl-ref) in the loss (k3 estimate)")
    add("--entropy", type=str, default="0.01",
        help="entropy bonus: a number, or a schedule over decisions such as 0:0.02,500M:0.01,2G:0.003")
    add("--eval-every", type=int, default=25)
    add("--eval-games", type=int, default=2, help="games per pairing and seat of the evaluation suite (<= 8 teams)")
    add("--eval-budget", type=int, default=512, help="games of the evaluation suite with more than 8 teams")
    add("--seed", type=lambda s: int(s, 0), default=0x2026100200000021)
    add("--max-steps", type=int, default=500,
        help="steps before a self-play episode is cut off and scored by the reference's tiebreak")
    add("--out", default=None, help="a fresh run directory (not with --resume)")
    add("--resume", default=None, help="continue the run in this directory")
    add("--model", choices=("v1", "v2"), default="v1")
    add("--preset", choices=("S", "M", "L"), default="S", help="model v2 size")
    for dim in _DIMS:
        add(f"--{dim}", type=int, default=None, help="overrides the preset (v1: --hidden only)")
    add("--self-play-share", type=float, default=0.5, help="environments with the learner on both seats")
    add("--opponent-precision", choices=league.PRECISIONS, default="float32",
        help="the league opponents' matrix products (the learner stays float32)")
    add("--league-slots", type=int, default=4, help="frozen snapshots playing the league environments")
    add("--snapshot-every", type=int, default=200, help="updates between snapshots of the learner")
    add("--slot-refresh", type=int, default=50, help="updates between league slot reloads")
    add("--league-pfsp-share", type=float, default=_REFILL["league_pfsp_share"][1],
        help="share of slot reloads drawn by prioritized fictitious self-play over the learner's win rates (the "
             "rest not given to --league-anchor-share is uniform; self-play environments stay --self-play-share)")
    add("--league-anchor-share", type=float, default=_REFILL["league_anchor_share"][1],
        help="share of slot reloads drawn from the --league-anchors earliest snapshots")
    add("--league-anchors", type=int, default=_REFILL["league_anchors"][1],
        help="the earliest snapshots that are anchors (1: params-0, the initial or --init network)")
    add("--pfsp-weighting", choices=league.WEIGHTINGS, default=_REFILL["pfsp_weighting"][1],
        help="f(p) of a snapshot the learner beats with rate p: hard (1-p)^2, linear 1-p, variance p(1-p)")
    add("--pfsp-min-weight", type=float, default=_REFILL["pfsp_min_weight"][1],
        help="the least PFSP weight of a snapshot, so none starves (f is at most 1)")
    add("--pfsp-prior", type=float, default=_REFILL["pfsp_prior"][1],
        help="the win rate a snapshot starts from (an unseen snapshot's p)")
    add("--pfsp-prior-games", type=float, default=_REFILL["pfsp_prior_games"][1],
        help="the pseudo-games of --pfsp-prior added to each snapshot's record")
    add("--save-minutes", type=float, default=10.0, help="minutes between saves of the run state")
    add("--teams", default=None, help="registry team ids, comma-separated (default: Teams A and B of the "
                                      "reference setups)")
    add("--team-weights", default=None, help="sampling weights of the teams, comma-separated (default: equal)")
    add("--teams-root", default="data/teams", help="the team registry")
    add("--data-kind", choices=tuple(DATA_KINDS), default="closure", help="the data kind of the battles")
    add("--init", default=None,
        help="a checkpoint (format 2) a new run starts from, a behavior-cloning network (M11 BC spec section 8): "
             "its model and data kind unless given, fresh optimizer, league and counters; a resume never re-applies "
             "it")
    add("--ledger", default=None, help="a compute ledger (ledger.py, stage 3 P1): CPU core-seconds and GPU-seconds of "
                                       "the run, summed over its restarts")
    add("--stop-cpu-core-seconds", type=float, default=0.0,
        help="stop at the first update where the ledger's CPU core-seconds reach this (0: no such stop)")
    add("--stop-gpu-seconds", type=float, default=0.0,
        help="stop at the first update where the ledger's GPU-seconds reach this (0: no such stop)")
    add("--update-gpu-share", type=_share, default=1.0,
        help="the share of updates on the default device, the rest on the CPU (update u, from 0: on the default "
             "device when floor((u+1)q) > floor(uq)); or 'match': each update's device chosen from the ledger so that "
             "both stops are met within 5 %% (budget_match; needs --ledger and both stops, which then end the run "
             "together: matched, or incomplete when no device fits)")
    add("--act-gpu-share", type=float, default=1.0,
        help="the same share for the collection's network calls (learner and league opponents)")
    add("--keep-init-encoder", action="store_true", default=False,
        help="a new run from --init keeps the init's encoder layout (its feature names and ext_supported) instead "
             "of widening it to the current encoder: the stage 3 P1 continuation control stays on params-49333's "
             "encoder 4; a resume keeps the run's layout")
    add("--ext-supported", type=lambda s: int(s, 0), default=None,
        help="the view-extension features the network reads (decision 0018), a mask of DUOFORGE_VIEWEXT_FEATURE_* "
             "bits (default: every feature the library supports under the data kind)")
    return p


def parse(argv):
    """The options of argv; given (the options argv names explicitly) is
    kept in args._given for a resume."""
    p = _parser()
    args = p.parse_args(argv)
    args._given = sorted(vars(_parser(suppress=True).parse_args(argv)))
    schedule.Schedule.parse(args.entropy)  # refuses a malformed schedule now
    if (args.out is None) == (args.resume is None):
        p.error("give --out for a new run or --resume for an existing one")
    if args.init is not None and args.resume is not None:
        p.error("--init starts a new run: a resume keeps the run's own parameters")
    if args.keep_init_encoder and args.resume is None and args.init is None:
        p.error("--keep-init-encoder keeps the layout of --init: give --init")
    match = args.update_gpu_share == "match"
    if args.resume is None:  # a resume's own options are checked in _run, after merging the saved ones
        try:
            _check_match(args)
        except ValueError as err:
            p.error(str(err))
    for share in ("update_gpu_share", "act_gpu_share") if not match else ("act_gpu_share",):
        if not 0.0 <= getattr(args, share) <= 1.0:
            p.error(f"--{share.replace('_', '-')} must lie between 0 and 1")
    budget = args.stop_cpu_core_seconds > 0 or args.stop_gpu_seconds > 0
    if args.resume is None:
        if budget and args.ledger is None:
            p.error("--stop-cpu-core-seconds and --stop-gpu-seconds need --ledger")
        if budget and "minutes" not in args._given:
            args.minutes = 0.0  # the ledger's budget replaces the 60-minute default
        if args.minutes <= 0 and args.updates <= 0 and not budget:
            p.error("give --minutes or --updates")
    return args


def _check_match(args):
    """ValueError unless --update-gpu-share match and --learning-rate-over budget have what they need."""
    if args.update_gpu_share == "match" and not (args.stop_cpu_core_seconds > 0 and args.stop_gpu_seconds > 0):
        raise ValueError("--update-gpu-share match needs --stop-cpu-core-seconds and --stop-gpu-seconds (and --ledger)")
    if args.learning_rate_over == "budget" and args.update_gpu_share != "match":
        raise ValueError("--learning-rate-over budget needs --update-gpu-share match")


def _merged(args, saved):
    """The options of a resumed run: the saved ones, replaced by the ones
    the command line gives where a resume allows it; and the changes."""
    defaults = vars(_parser().parse_args(["--out", "-"]))  # options a run of an older version did not save
    merged = argparse.Namespace(**{**{k: v for k, v in defaults.items() if k in vars(args)},
                                   **{k: v for k, v in saved.items() if k in vars(args)}})
    changes = {}
    for name in args._given:
        if name in ("resume", "out", "ext_supported"):  # ext_supported: _run compares it with the resolved mask
            continue
        new, old = getattr(args, name), saved.get(name)
        if new == old:
            continue
        if name not in _RESUMABLE:
            raise SystemExit(f"a resume cannot change {name} ({old!r} -> {new!r})")
        setattr(merged, name, new)
        changes[name] = [old, new]
    merged.resume, merged.out = args.resume, args.resume
    merged._given = args._given
    return merged, changes


def _load_init(args):
    """(params, config) of --init, widened to the current encoder layout by name (checkpoint.load_current: old rows
    exact, new rows zero), or with --keep-init-encoder in the layout it was trained with (checkpoint.load_trained,
    never widened); the run takes its model and data kind unless the command line gives them, and then they
    must agree. SystemExit for anything it cannot take: an output inside the repository (a network that descends
    from replay data, decision 0019), an unknown encoder, another model or kind."""
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
        raw = checkpoint.load(args.init)[1]
        format_version = raw.get("format", 1)
        if format_version != 2:
            raise ValueError(f"format-{format_version} checkpoints cannot start a run; --init needs format 2")
        encoder = checkpoint.encoder_of(raw)
        if encoder not in checkpoint.WIDENABLE_ENCODERS:
            raise ValueError(f"a checkpoint of encoder {encoder} (format {raw.get('format')}) cannot start a run of "
                             f"encoder {features.ENCODER}")
        if args.keep_init_encoder:
            params, config = checkpoint.load_trained(args.init)
        else:
            params, config = checkpoint.load_current(args.init)
    except ValueError as err:
        raise SystemExit(f"--init {args.init}: {err}") from None
    if any(k in args._given for k in ("model", "preset") + _DIMS):
        if model_config(args) != config["model"]:
            raise SystemExit(f"--init {args.init}: the checkpoint's model {config['model']} differs from the given "
                             f"{model_config(args)}")
    else:
        args.preset = None  # the model is the checkpoint's (its config), not the parser's default preset
    args.model = "v2" if config["model"]["version"] == 2 else "v1"
    kind = config["data"]["kind"]
    if "data_kind" in args._given and args.data_kind != kind:
        raise SystemExit(f"--init {args.init}: the checkpoint's data kind {kind} differs from --data-kind "
                         f"{args.data_kind}")
    args.data_kind = kind
    return params, config


def _init_mask(params, config, ext_supported, path):
    """(params, info) of --init under the run's mask: every bit beyond the checkpoint's has its input rows zeroed
    (checkpoint.zero_columns, exact: those columns were 0 while it learned); a mask without a bit the checkpoint
    reads is refused."""
    old = checkpoint.ext_supported_of(config)
    if old & ~ext_supported:
        raise SystemExit(f"--init {path}: the run's ext_supported {ext_supported:#x} lacks bits the checkpoint reads "
                         f"({old:#x}): a narrower mask would drop features it relies on (or the library lacks them)")
    extra = ext_supported & ~old
    changes = {}
    if extra:
        try:
            params = checkpoint.zero_columns(params, config, features.columns_of(extra))
        except ValueError as err:
            raise SystemExit(f"--init {path}: {err}") from None
        changes["ext_supported"] = [old, ext_supported]
    with open(path, "rb") as f:
        import hashlib
        sha = hashlib.sha256(f.read()).hexdigest()
    return params, {"path": str(path), "sha256": sha, "ext_supported": old, "changes": changes}


def _widen_state(params, opt_leaves, model_cfg, names, slot_names, tx):
    """(params, optimizer state) of a saved run widened from the encoder
    layout (names, slot_names) to the current one: zero rows for new
    columns in the parameters and in both Adam moments; the step count
    stays."""
    config = {"model": model_cfg, "features": list(names), "slot_features": list(slot_names)}
    current = (features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
    wide, _ = checkpoint.widen(params, config, *current)
    narrow_template = tx.init(params)
    saved = jax.tree_util.tree_unflatten(jax.tree_util.tree_structure(narrow_template),
                                         [np.asarray(x) for x in opt_leaves])
    tree_like = jax.tree_util.tree_structure(params)

    def widen_node(node):
        if jax.tree_util.tree_structure(node) == tree_like:
            return checkpoint.widen(node, config, *current, fill="zeros")[0]
        return node

    widened = jax.tree_util.tree_map(widen_node, saved, is_leaf=lambda n: jax.tree_util.tree_structure(n) == tree_like)
    return wide, widened


class _Pool:
    """The run's snapshots: update numbers whose params-<update>.npz exist. keep: the run keeps its init's layout
    (--keep-init-encoder), so a snapshot is read as trained, never widened."""

    def __init__(self, out, keep=False):
        self.out, self.keep = out, keep
        found = [int(m.group(1)) for f in os.listdir(out) for m in [re.match(r"params-(\d+)\.npz$", f)] if m]
        self.updates = sorted(found)

    def path(self, update):
        return os.path.join(self.out, f"params-{update}.npz")

    def save(self, update, params, config):
        checkpoint.save(self.path(update), params, config)
        if update not in self.updates:
            self.updates.append(update)

    def load(self, update):
        """A snapshot's parameters, widened to the current encoder layout (or in the run's own, keep)."""
        if self.keep:
            return checkpoint.load_trained(self.path(update))[0]
        return checkpoint.load_current(self.path(update))[0]

    def set_aside(self, after):
        """Moves the snapshots newer than update `after` (written after the
        saved state by a run that then died) to <out>/abandoned-<after>/, so
        the pool and the ladder see only the resumed run's history."""
        newer = [u for u in self.updates if u > after]
        if not newer:
            return [], None
        folder = f"abandoned-{after}"
        os.makedirs(os.path.join(self.out, folder), exist_ok=True)
        for u in newer:
            os.replace(self.path(u), os.path.join(self.out, folder, f"params-{u}.npz"))
            self.updates.remove(u)
        return newer, folder

    def draw(self, seed, update, refill, stats):
        """(chosen update, its parameters, source) of a slot's refill (league.Refill)."""
        chosen, source = refill.draw(seed, update, self.updates, stats)
        return chosen, self.load(chosen), source


def _default_pool():
    return teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])


def _pool_of_args(args, context):
    """The pool the options name: registry teams (--teams) or Teams A and B."""
    weights = None if args.team_weights is None else [float(w) for w in args.team_weights.split(",")]
    if args.teams is None:
        return _default_pool() if weights is None else _default_pool().with_weights(weights)
    return teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root, weights=weights)


def _check_teams(saved, pool):
    old = dict(zip(saved["ids"], saved["sha256"]))
    for tid, sha in zip(pool.ids, pool.sha256):
        if tid in old and old[tid] != sha:
            raise SystemExit(f"team {tid} changed since the run started (sha256 {old[tid]} -> {sha})")


def main(argv=None):
    return run(parse(sys.argv[1:] if argv is None else list(argv)))


def refuse_in_repository(path):
    """SystemExit for a run directory inside a work tree of this repository: runs, their checkpoints and league
    snapshots are private (AGENTS.md) and never written where a commit could pick them up."""
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(path)
    except ValueError:
        raise SystemExit(f"{path} is inside the repository: runs, checkpoints and snapshots never go there") from None


def run(args, pool=None, on_start=None):
    """Trains a new run (args.out) or resumes one (args.resume). pool: the
    teams (default Teams A and B); on_start(envs, episodes) is called
    whenever episodes start (tests)."""
    refuse_in_repository(args.out if args.resume is None else args.resume)
    stop = runstate.StopFlag().install()
    try:
        return _run(args, pool, on_start, stop)
    finally:
        stop.restore()


def _run(args, pool, on_start, stop):
    saved_state, changes = None, {}
    if args.resume is not None:
        saved_state = runstate.load_state(args.resume)
        # The run keeps the mask it resolved when it started; only an explicit, different --ext-supported is a change.
        explicit = args.ext_supported if "ext_supported" in args._given else None
        stored = saved_state.get("ext_supported", 0)
        if explicit is not None and explicit != stored:
            raise SystemExit(f"a resume cannot change ext_supported ({stored:#x} -> {explicit:#x})")
        args, changes = _merged(args, saved_state["train"])
    try:
        refill = league.Refill(**{name: getattr(args, option) for option, (name, _) in _REFILL.items()})
    except ValueError as err:
        raise SystemExit(str(err)) from None
    init = _load_init(args) if saved_state is None and args.init is not None else None
    context = duoforge.Context(data_kind=DATA_KINDS[args.data_kind])
    if init is not None and init[1]["data"]["fingerprint"] != context.fingerprint().hex():
        try:  # other tables than the checkpoint's: every id its network embeds must still name the same row
            checkpoint.check_ids(init[1], context)
        except ValueError as err:
            raise SystemExit(f"--init {args.init}: the context's tables differ from the checkpoint's: {err}") from None
    ids = checkpoint.ids_of(context)  # what the embedded ids mean (spec 12.4), kept in the run state
    pool = _pool_of_args(args, context) if pool is None else pool
    if saved_state is not None:
        if list(pool.ids) != saved_state["teams"]["ids"] or \
                [float(w) for w in pool.weights] != saved_state["teams"]["weights"]:
            changes["teams"] = [saved_state["teams"]["ids"], list(pool.ids)]
        _check_teams(saved_state["teams"], pool)
    else:
        if os.path.isdir(args.out) and os.listdir(args.out):
            raise SystemExit(f"{args.out} is not empty: a run writes into a fresh directory")
        os.makedirs(args.out, exist_ok=True)
    out = args.out
    entropy = schedule.Schedule.parse(args.entropy)
    lr_scale = schedule.Schedule.parse(args.learning_rate_schedule)
    if args.kl_coef and not args.kl_ref:
        raise SystemExit("--kl-coef needs --kl-ref: the reference policy of the KL anchor")
    if (args.stop_cpu_core_seconds > 0 or args.stop_gpu_seconds > 0) and not args.ledger:
        raise SystemExit("--stop-cpu-core-seconds and --stop-gpu-seconds need --ledger")
    try:
        _check_match(args)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    match = args.update_gpu_share == "match"
    targets = (args.stop_cpu_core_seconds, args.stop_gpu_seconds)
    book = ledger.Ledger(args.ledger) if args.ledger else None
    train_config = {k: v for k, v in vars(args).items() if not k.startswith("_") and k not in ("resume",)}
    train_config["entropy"] = str(entropy)
    train_config["learning_rate_schedule"] = str(lr_scale)
    for option, (_, default) in _REFILL.items():
        if train_config[option] == default:
            del train_config[option]
    keep = bool(args.keep_init_encoder)
    if not keep:
        train_config.pop("keep_init_encoder", None)  # the saved options of a run without it are as before
    if train_config.get("learning_rate_over") == "decisions":
        del train_config["learning_rate_over"]  # its default: saved only by a budget-matched run
    if saved_state is not None and saved_state["data"]["fingerprint"] != context.fingerprint().hex():
        # Other tables (the data kind cannot change on resume): the run goes on when every id its network embeds
        # still names the same row (spec 12.4), and is refused otherwise.
        try:
            checkpoint.check_ids(saved_state, context)
        except ValueError as err:
            old_print, new_print = saved_state["data"]["fingerprint"], context.fingerprint().hex()
            raise SystemExit(f"the context's tables differ from the run's ({old_print} -> {new_print}): "
                             f"{err}") from None
        changes["data"] = [saved_state["data"]["fingerprint"], context.fingerprint().hex()]
    encoder = saved_state["encoder"] if saved_state is not None else features.ENCODER
    # The (feature, slot feature) names the run's network reads: the current encoder's, or under
    # --keep-init-encoder the init's own, which a resume keeps (no widening).
    layout = (list(features.FEATURE_NAMES), list(features.SLOT_FEATURE_NAMES))
    if keep and saved_state is not None:
        layout = (list(saved_state["features"]), list(saved_state["slot_features"]))
    elif keep:
        encoder = checkpoint.encoder_of(init[1])
        layout = (list(init[1]["features"]), list(init[1]["slot_features"]))
    widening = saved_state is not None and not keep and (
        saved_state["features"] != list(features.FEATURE_NAMES) or
        saved_state["slot_features"] != list(features.SLOT_FEATURE_NAMES))
    if widening and encoder != features.ENCODER:
        # A run of encoder 2 or 3 widened by name continues on this encoder's inputs: the new rows start at zero,
        # and its mask, which lies inside the columns it had, stays.
        if encoder not in (2, 3):
            raise SystemExit(f"a run of encoder {encoder} cannot be widened to encoder {features.ENCODER}")
        changes["encoder"] = [encoder, features.ENCODER]
        encoder = features.ENCODER
    model_cfg = (saved_state["model"] if saved_state is not None else init[1]["model"] if init is not None
                 else model_config(args))
    if saved_state is None:
        print(json.dumps(train_config | {"devices": [str(d) for d in jax.devices()], "model": model_cfg}), flush=True)

    state = league.LeagueState(args.envs, args.self_play_share, args.league_slots, args.slot_refresh, args.seed)
    seen = (np.asarray(saved_state["episodes_seen"], dtype=np.int64) if saved_state is not None
            else np.zeros(0, dtype=np.int64))
    if seen.shape[0] < args.envs:
        seen = np.concatenate([seen, np.full(args.envs - seen.shape[0], -1, dtype=np.int64)])
    starts = (seen[:args.envs] + 1).astype(np.uint32)
    counts = np.zeros(len(pool.ids), dtype=np.int64)
    sides = [None]

    def started(envs, episodes):
        state.start(envs, episodes)
        if sides[0] is not None:
            p0, p1 = sides[0].pairing[np.asarray(envs, dtype=np.int64)].T
            np.add.at(counts, p0, 1)
            np.add.at(counts, p1, 1)
        if on_start is not None:
            on_start(envs, episodes)

    # A resumed run keeps the mask it trained with (a run from before encoder 3 had none: 0); a new one takes
    # --ext-supported, by default every feature the library supports under the context.
    ext_supported = saved_state.get("ext_supported", 0) if saved_state is not None else args.ext_supported
    if keep and saved_state is None:  # the init's own mask: its columns, nothing zeroed or dropped
        own = checkpoint.ext_supported_of(init[1])
        if "ext_supported" in args._given and args.ext_supported != own:
            raise SystemExit(f"--keep-init-encoder runs the init's ext_supported {own:#x}, not "
                             f"--ext-supported {args.ext_supported:#x}")
        ext_supported = own
    env = SelfPlay(args.envs, args.workers, args.seed, pool=pool, max_steps=args.max_steps, start_episodes=starts,
                   encoder=encoder, context=context, on_start=started, ext_supported=ext_supported,
                   on_end=lambda envs, rewards: state.end(envs, league.learner_results(state, envs, rewards)))
    ext_supported = env.ext_supported
    if init is not None:
        try:
            init_params, init_info = _init_mask(init[0], init[1], ext_supported, args.init)
        except SystemExit:
            env.close()
            raise
        train_config["init"] = init_info
    sides[0] = env
    learner_rows = state.learner_rows()
    net = policy.make(model_cfg) if not keep else policy.make(model_cfg, *layout)
    tx = ppo.optimizer(args.learning_rate)
    ref_params = None
    magnet = args.kl_ref == "magnet"  # MMD/R-NaD style: the reference is the learner itself, frozen and refreshed
    if magnet and args.kl_refresh <= 0:
        raise SystemExit("--kl-refresh must be positive for --kl-ref magnet")
    if args.kl_ref and not magnet:  # the KL anchor's reference: a checkpoint of this run's model, widened
        if keep:  # read in its own layout, which must be the run's
            try:
                ref_params, ref_config = checkpoint.load_trained(args.kl_ref)
            except ValueError as err:
                raise SystemExit(f"--kl-ref {args.kl_ref}: {err}") from None
            if (list(ref_config["features"]), list(ref_config["slot_features"])) != layout:
                raise SystemExit(f"--kl-ref {args.kl_ref}: its layout (encoder {checkpoint.encoder_of(ref_config)}) "
                                 f"is not the run's (encoder {encoder})")
        else:
            ref_params, ref_config = checkpoint.load_current(args.kl_ref)
        ref_cfg = checkpoint.model_config(ref_config, ref_params)
        if ref_cfg != model_cfg:
            raise SystemExit(f"--kl-ref {args.kl_ref}: its model {ref_cfg} is not the run's {model_cfg}")
    snapshots = _Pool(out, keep)
    if saved_state is None:
        key = jax.random.fold_in(jax.random.PRNGKey(args.seed & 0xFFFFFFFF), args.seed >> 32)
        key, sub = jax.random.split(key)
        params = net.init(sub) if init is None else jax.device_put(init_params)
        opt_state = tx.init(params)
        rng = np.random.default_rng(args.seed)
        update = decisions = episodes = last_eval = act_calls = 0
        snapshots.save(0, params, snapshot_config(train_config, model_cfg, context, pool, 0, 0, encoder,
                                                  ext_supported, layout))
        previous = params
    else:
        params, opt_leaves = saved_state["params"], saved_state["opt_leaves"]
        if widening:
            params, opt_state = _widen_state(params, opt_leaves, model_cfg, saved_state["features"],
                                             saved_state["slot_features"], tx)
            changes["features"] = [len(saved_state["features"]), features.OBS_SIZE]
        else:
            opt_state = runstate.restore_opt(tx, params, opt_leaves)
        key = np.asarray(saved_state["jax_key"])
        rng = np.random.default_rng()
        rng.bit_generator.state = saved_state["numpy_rng"]
        c = saved_state["counters"]
        update, decisions, episodes, last_eval = c["update"], c["decisions"], c["episodes"], c["last_eval"]
        act_calls = c.get("act_calls", 0)
        abandoned, abandoned_dir = snapshots.set_aside(update)
        previous = snapshots.load(last_eval) if last_eval in snapshots.updates else params
        old = saved_state["league"]
        # A slot of a run without league holds "init": the initial parameters, params-0.
        state.snapshots = [old["snapshots"][k] if k < len(old["snapshots"]) and old["snapshots"][k].isdigit()
                           and int(old["snapshots"][k]) in snapshots.updates else "0" for k in range(state.slots)]
        state.stats = {k: list(v) for k, v in old["stats"].items()}
        state.next_drain = old["next_drain"] % max(state.slots, 1)
    opponents = None
    if state.has_league:
        opponents = league.Opponents(net, state.slots, precision=args.opponent_precision)
        for slot in range(state.slots):
            label = state.snapshots[slot]
            if saved_state is None:
                state.load(slot, "0")
                opponents.set(slot, params)
            else:
                opponents.set(slot, snapshots.load(int(label)))

    def save_run():
        everyone = np.maximum(seen, -1)
        everyone[:args.envs] = env.episodes.astype(np.int64)
        if book is not None:  # the ledger first: a crash between the two never leaves a state ahead of its ledger
            book.save()
        runstate.save_state(out, {
            "params": params, "opt_leaves": jax.tree_util.tree_leaves(opt_state), "episodes_seen": everyone,
            "jax_key": np.asarray(key), "counters": {"update": update, "decisions": decisions, "episodes": episodes,
                                                     "last_eval": last_eval, "act_calls": calls["act"]},
            "league": state.to_dict(), "numpy_rng": rng.bit_generator.state, "teams": _teams_json(pool),
            "data": _data_json(args.data_kind, context), "model": model_cfg,
            "features": list(layout[0]), "slot_features": list(layout[1]),
            "encoder": encoder, "ext_supported": ext_supported, "ids": ids, "train": train_config})
        if book is not None:  # and again with the state's own saving booked
            book.save()

    # The continuation control of stage 3 P1: a ledger, and each update and collection call on the default device
    # or the CPU by a deterministic share. Without them the run is as before.
    controlled = book is not None or args.update_gpu_share != 1.0 or args.act_gpu_share != 1.0
    default_device, cpu_device = (jax.devices()[0], jax.devices("cpu")[0]) if controlled else (None, None)
    calls = {"act": act_calls, "default": 0, "device": None, "on": False}
    placed = {}

    def section(on_default):
        return book.device() if book is not None and on_default else contextlib.nullcontext()

    def phase(name):
        return book.phase(name) if book is not None else contextlib.nullcontext()

    def controlled_act(p, k, obs, slots, mask, is_team):
        on = _on_default(calls["act"], args.act_gpu_share)
        calls["act"] += 1
        calls["default"] += on
        device = default_device if on else cpu_device
        calls["device"], calls["on"] = device, on
        with section(on):
            if device not in placed:
                placed[device] = jax.device_put(p, device)
            return jax.block_until_ready(net.act(placed[device], jax.device_put(k, device), obs, slots, mask,
                                                 is_team))

    class _ControlledOpponents:
        def act(self, k, obs, slot_part, mask, is_team, slot_idx):
            with section(calls["on"]):
                return opponents.act(k, obs, slot_part, mask, is_team, slot_idx, device=calls["device"])

    act = controlled_act if controlled else net.act
    start = time.perf_counter()
    saved_at = start
    next_device = point = None
    if match:  # budget_match: the steps measured so far (a resume reads them from the log), then the first device
        log_path = os.path.join(out, "log.jsonl")
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                costs = budget_match.Costs.from_log(line for line in f if line.strip())
        else:
            costs = budget_match.Costs()
        totals = book.totals()
        point = (totals["cpu_core_seconds"], totals["gpu_seconds"])
        next_device, match_stop = budget_match.choose(point, targets, costs)
    with open(os.path.join(out, "log.jsonl"), "a", encoding="utf-8") as log:
        if saved_state is None and init is not None:
            log.write(json.dumps({"init": train_config["init"]}) + chr(10))
        if saved_state is not None:
            line = {"resume": changes, "at_update": update}
            if abandoned:
                line |= {"abandoned_snapshots": abandoned, "abandoned_dir": abandoned_dir}
            log.write(json.dumps(line) + "\n")
        if match and next_device is None:  # a resume of a run whose budget is already matched or incomplete
            log.write(json.dumps({"stopped": match_stop, "at_update": update}) + "\n")
        while not (match and next_device is None):
            update += 1
            counts[:] = 0
            t0 = time.perf_counter()
            timings = {}
            cuts_before, unresolved_before, refused_before = env.cuts, env.unresolved, env.engine_unsupported
            calls["default"] = 0
            placed.clear()
            players = _ControlledOpponents() if controlled and opponents is not None else opponents
            with phase("collect"):
                rollout, bootstrap, ended, key = collect(env, params, act, key, args.rollout, state, players, timings)
                advantages, _, value_targets = gae(rollout["values"], rollout["rewards"], rollout["done"],
                                                   rollout["acting"], bootstrap)
                samples = samples_of(rollout, advantages, value_targets, learner_rows)
            acted = int(samples["acting"].sum())
            t1 = time.perf_counter()
            entropy_coef = entropy(decisions)
            magnet_refreshed = magnet and (ref_params is None or update % args.kl_refresh == 0)
            if magnet_refreshed:  # the magnet: the learner as it is now, frozen until the next refresh
                ref_params = jax.tree_util.tree_map(lambda x: x, params)
            scale = lr_scale(1000 * point[0] / targets[0] if args.learning_rate_over == "budget" else decisions)
            on_default = next_device == "default" if match else _on_default(update - 1, args.update_gpu_share)
            device = default_device if on_default else cpu_device
            with phase("update"), section(on_default and controlled), \
                    (jax.default_device(device) if controlled else contextlib.nullcontext()):
                if controlled:
                    params, opt_state = jax.device_put(params, device), jax.device_put(opt_state, device)
                if ref_params is not None:  # the reference's log-probability of each taken action, once per update
                    ref = jax.device_put(ref_params, device) if controlled else ref_params
                    samples["ref_logp"] = ppo.reference_logp(ref, samples, net.evaluate, args.minibatch)
                params, opt_state, stats = ppo.update(params, opt_state, tx, samples, rng, net.evaluate,
                                                      epochs=args.epochs, minibatch=args.minibatch,
                                                      entropy_coef=entropy_coef, kl_coef=args.kl_coef,
                                                      lr_scale=scale)
                if controlled:
                    jax.block_until_ready(params)
            t2 = time.perf_counter()
            decisions += acted
            episodes += ended
            record = {"update": update, "seconds": round(t2 - start, 1), "decisions": decisions,
                      "episodes": episodes, "collect_s": round(t1 - t0, 3), "update_s": round(t2 - t1, 3),
                      "decisions_per_s": round(acted / (t2 - t0)), "policy_rows": acted,
                      "acted_rows": int(rollout["acting"].sum()), "entropy_coef": round(entropy_coef, 8),
                      "lr_scale": round(scale, 8), "kl_coef": args.kl_coef, "magnet_refreshed": magnet_refreshed,
                      "team_episodes": counts.tolist(), "cut_episodes": env.cuts - cuts_before,
                      "tiebreak_unresolved": env.unresolved - unresolved_before,
                      "engine_unsupported": env.engine_unsupported - refused_before}
            record |= {k: round(v, 4) for k, v in timings.items()}
            record["t_other"] = round(max(0.0, (t1 - t0) - sum(timings.values())), 4)
            record |= {k: round(float(v), 5) for k, v in stats.items()}
            if controlled:
                record["update_device"] = "default" if on_default else "cpu"
                record["act_default_calls"] = calls["default"]
            budget = False
            if book is not None:
                totals = book.totals()
                record["ledger"] = {k: round(totals[k], 3) for k in ("cpu_core_seconds", "gpu_seconds")}
            if match:  # this step's cost, then the next device or the stop
                now = (totals["cpu_core_seconds"], totals["gpu_seconds"])
                costs.observe(next_device, now[0] - point[0], now[1] - point[1])
                point = now
                next_device, match_stop = budget_match.choose(point, targets, costs)
                budget = next_device is None
                record["match"] = {"fractions": [round(now[0] / targets[0], 5), round(now[1] / targets[1], 5)],
                                   "next": next_device or match_stop}
            elif book is not None:
                budget = bool((args.stop_cpu_core_seconds > 0
                               and totals["cpu_core_seconds"] >= args.stop_cpu_core_seconds)
                              or (args.stop_gpu_seconds > 0 and totals["gpu_seconds"] >= args.stop_gpu_seconds))
            elapsed_min = (t2 - start) / 60
            last = ((args.updates and update >= args.updates) or (args.minutes and elapsed_min >= args.minutes)
                    or stop.requested or budget)
            # A budget stop plays no final suites: whatever it played would be charged to the arm.
            # A match run's ledger is training only: no suites, neither periodic nor at an update or minutes cap.
            evaluating = not match and (update % args.eval_every == 0 or (last and not stop.requested and not budget))
            if update % args.snapshot_every == 0 or evaluating:
                snapshots.save(update, params, snapshot_config(train_config, model_cfg, context, pool, update,
                                                               decisions, encoder, ext_supported, layout))
            if state.has_league:
                state.tick(update)
                slot = state.ready()
                if slot >= 0:
                    chosen, snapshot, source = snapshots.draw(args.seed, update, refill, state.stats)
                    opponents.set(slot, snapshot)
                    state.load(slot, str(chosen))
                    record["league_load"] = {"slot": slot, "snapshot": chosen}
                    if refill.enabled:  # a run without PFSP or anchors logs what the uniform runs logged
                        p = float(refill.win_rates([chosen], state.stats)[0])
                        record["league_load"] |= {"source": source, "win_rate": round(p, 4)}
            if evaluating:
                rows = suite.make_suite(len(pool.ids), args.seed, games=args.eval_games, budget=args.eval_budget)
                me = evaluate.Player(net, params, encoder, "learner", ext_supported)
                for name, opponent in (("random", "random"),
                                       ("previous", evaluate.Player(net, previous, encoder, "previous",
                                                                    ext_supported))):
                    games = evaluate.play_suite(context, pool, rows, me, opponent, args.workers, EVAL_SEED)
                    result = evaluate.scores(games, len(pool.ids))
                    record[f"vs_{name}"] = round(result["score"], 4)
                    record[f"vs_{name}_by_team"] = [None if x is None else round(x, 4) for x in result["by_team"]]
                    if games["unfinished"].any():
                        record[f"unfinished_vs_{name}"] = int(games["unfinished"].sum())
                    if games["unresolved"].any():
                        record[f"unresolved_vs_{name}"] = int(games["unresolved"].sum())
                if state.has_league:
                    record["league"] = {k: list(v) for k, v in state.stats.items()}
                previous, last_eval = params, update
            if stop.requested:
                record["stopped"] = "signal"
            elif budget:  # the ledger's budget; with match: "matched", "incomplete" or "overshoot" (budget_match)
                record["stopped"] = match_stop if match else "budget"
            log.write(json.dumps(record) + "\n")
            log.flush()
            print(json.dumps(record), flush=True)
            if last or time.perf_counter() - saved_at >= args.save_minutes * 60:
                save_run()
                saved_at = time.perf_counter()
            if last:
                break
    env.close()
    context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
