"""Self-play PPO training (decisions 0014, 0017).

    python -m duoforge_learn.train --envs 256 --workers 16 --minutes 60 --out runs/trial
    python -m duoforge_learn.train --resume runs/trial --minutes 60

Collects --rollout batch steps, updates the policy with PPO and logs one
JSON line per update to <out>/log.jsonl. The first --self-play-share of the
environments play self-play; the others play the learner against frozen
snapshots of itself in --league-slots slots (league.py), which reload a
snapshot drawn from the run's pool every --slot-refresh updates, at an
episode boundary. Snapshots go to <out>/params-<update>.npz (checkpoint
format 2) every --snapshot-every updates and at each evaluation; every
--eval-every updates the greedy policy plays the evaluation suite (suite.py)
against the random baseline and the previous evaluation's parameters
(vs_previous above 0.5: still improving), with a score per team.

The run state (runstate.py) is saved every --save-minutes, at the end and
after SIGTERM or SIGINT (then the run ends at the next update boundary).
--resume continues a run from it: running episodes are dropped and every
environment starts its next episode, so no battle seed repeats; options
given on the command line replace the saved ones where a resume allows it.
"""
import argparse
import json
import os
import re
import sys
import time

import jax
import numpy as np

import duoforge
from duoforge import _layout, features, teams

from . import checkpoint, evaluate, league, pairing, policy, ppo, runstate, schedule, suite
from .returns import gae, samples_of
from .selfplay import SelfPlay

_DIMS = ("embed", "member", "position", "hidden", "layers", "option")
# Options a resume may change; any other option that differs from the saved run is refused.
_RESUMABLE = ("envs", "workers", "minutes", "updates", "self_play_share", "league_slots", "snapshot_every",
              "slot_refresh", "entropy", "eval_every", "eval_games", "eval_budget", "save_minutes", "teams",
              "team_weights", "teams_root", "opponent_precision", "minibatch")
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


def snapshot_config(train_config, model_cfg, context, pool, update, decisions, encoder, ext_supported):
    """The format-2 config of a snapshot of this run."""
    return {"model": model_cfg, "encoder": encoder, "ext_supported": ext_supported,
            "ids": checkpoint.ids_of(context), "features": list(features.FEATURE_NAMES),
            "slot_features": list(features.SLOT_FEATURE_NAMES),
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
    if args.resume is None:
        if args.minutes <= 0 and args.updates <= 0:
            p.error("give --minutes or --updates")
    return args


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
    exact, new rows zero); the run takes its model and data kind unless the command line gives them, and then they
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
    """The run's snapshots: update numbers whose params-<update>.npz exist."""

    def __init__(self, out):
        self.out = out
        found = [int(m.group(1)) for f in os.listdir(out) for m in [re.match(r"params-(\d+)\.npz$", f)] if m]
        self.updates = sorted(found)

    def path(self, update):
        return os.path.join(self.out, f"params-{update}.npz")

    def save(self, update, params, config):
        checkpoint.save(self.path(update), params, config)
        if update not in self.updates:
            self.updates.append(update)

    def load(self, update):
        """A snapshot's parameters, widened to the current encoder layout."""
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

    def draw(self, seed, update):
        u = pairing.draw(seed, pairing.LEAGUE_SNAPSHOT, np.array([update]), np.array([0]))
        chosen = self.updates[int(pairing.pick(u, np.ones(len(self.updates)))[0])]
        return chosen, self.load(chosen)


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
    train_config = {k: v for k, v in vars(args).items() if not k.startswith("_") and k not in ("resume",)}
    train_config["entropy"] = str(entropy)
    if saved_state is not None and saved_state["data"]["fingerprint"] != context.fingerprint().hex():
        # Other tables (the data kind cannot change on resume): the run goes on when every id its network embeds
        # still names the same row (spec 12.4), and is refused otherwise.
        try:
            checkpoint.check_ids(saved_state, context)
        except ValueError as err:
            raise SystemExit(f"the context's tables differ from the run's "
                             f"({saved_state['data']['fingerprint']} -> {context.fingerprint().hex()}): {err}") from None
        changes["data"] = [saved_state["data"]["fingerprint"], context.fingerprint().hex()]
    encoder = saved_state["encoder"] if saved_state is not None else features.ENCODER
    widening = saved_state is not None and (saved_state["features"] != list(features.FEATURE_NAMES) or
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
    net = policy.make(model_cfg)
    tx = ppo.optimizer(args.learning_rate)
    snapshots = _Pool(out)
    if saved_state is None:
        key = jax.random.fold_in(jax.random.PRNGKey(args.seed & 0xFFFFFFFF), args.seed >> 32)
        key, sub = jax.random.split(key)
        params = net.init(sub) if init is None else jax.device_put(init_params)
        opt_state = tx.init(params)
        rng = np.random.default_rng(args.seed)
        update = decisions = episodes = last_eval = 0
        snapshots.save(0, params, snapshot_config(train_config, model_cfg, context, pool, 0, 0, encoder,
                                                  ext_supported))
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
        runstate.save_state(out, {
            "params": params, "opt_leaves": jax.tree_util.tree_leaves(opt_state), "episodes_seen": everyone,
            "jax_key": np.asarray(key), "counters": {"update": update, "decisions": decisions, "episodes": episodes,
                                                     "last_eval": last_eval},
            "league": state.to_dict(), "numpy_rng": rng.bit_generator.state, "teams": _teams_json(pool),
            "data": _data_json(args.data_kind, context), "model": model_cfg,
            "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
            "encoder": encoder, "ext_supported": ext_supported, "ids": ids, "train": train_config})

    act = net.act
    start = time.perf_counter()
    saved_at = start
    with open(os.path.join(out, "log.jsonl"), "a", encoding="utf-8") as log:
        if saved_state is None and init is not None:
            log.write(json.dumps({"init": train_config["init"]}) + chr(10))
        if saved_state is not None:
            line = {"resume": changes, "at_update": update}
            if abandoned:
                line |= {"abandoned_snapshots": abandoned, "abandoned_dir": abandoned_dir}
            log.write(json.dumps(line) + "\n")
        while True:
            update += 1
            counts[:] = 0
            t0 = time.perf_counter()
            timings = {}
            cuts_before, unresolved_before, refused_before = env.cuts, env.unresolved, env.engine_unsupported
            rollout, bootstrap, ended, key = collect(env, params, act, key, args.rollout, state, opponents, timings)
            advantages, _, value_targets = gae(rollout["values"], rollout["rewards"], rollout["done"],
                                               rollout["acting"], bootstrap)
            samples = samples_of(rollout, advantages, value_targets, learner_rows)
            acted = int(samples["acting"].sum())
            t1 = time.perf_counter()
            entropy_coef = entropy(decisions)
            params, opt_state, stats = ppo.update(params, opt_state, tx, samples, rng, net.evaluate,
                                                  epochs=args.epochs, minibatch=args.minibatch,
                                                  entropy_coef=entropy_coef)
            t2 = time.perf_counter()
            decisions += acted
            episodes += ended
            record = {"update": update, "seconds": round(t2 - start, 1), "decisions": decisions,
                      "episodes": episodes, "collect_s": round(t1 - t0, 3), "update_s": round(t2 - t1, 3),
                      "decisions_per_s": round(acted / (t2 - t0)), "policy_rows": acted,
                      "acted_rows": int(rollout["acting"].sum()), "entropy_coef": round(entropy_coef, 8),
                      "team_episodes": counts.tolist(), "cut_episodes": env.cuts - cuts_before,
                      "tiebreak_unresolved": env.unresolved - unresolved_before,
                      "engine_unsupported": env.engine_unsupported - refused_before}
            record |= {k: round(v, 4) for k, v in timings.items()}
            record["t_other"] = round(max(0.0, (t1 - t0) - sum(timings.values())), 4)
            record |= {k: round(float(v), 5) for k, v in stats.items()}
            elapsed_min = (t2 - start) / 60
            last = ((args.updates and update >= args.updates) or (args.minutes and elapsed_min >= args.minutes)
                    or stop.requested)
            evaluating = update % args.eval_every == 0 or (last and not stop.requested)
            if update % args.snapshot_every == 0 or evaluating:
                snapshots.save(update, params, snapshot_config(train_config, model_cfg, context, pool, update,
                                                               decisions, encoder, ext_supported))
            if state.has_league:
                state.tick(update)
                slot = state.ready()
                if slot >= 0:
                    chosen, snapshot = snapshots.draw(args.seed, update)
                    opponents.set(slot, snapshot)
                    state.load(slot, str(chosen))
                    record["league_load"] = {"slot": slot, "snapshot": chosen}
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
