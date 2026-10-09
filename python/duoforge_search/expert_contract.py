"""The P1 learner contract (plan C4, decision 0024): reference and fixtures.

M12 states what Learner v2's distillation must compute and checks it; it
implements no optimizer, trainer or second learner. Everything is NumPy (no
JAX here). Two validators:

validate_provider(provider, obs, slots, legal): the real student provider,
full_joint_log_probs bound to its params, on real encoded rows: a log-softmax
over every legal joint action, -inf where illegal, a row without a legal
action refused.

validate_adapter(adapter, fixture): the learner's loss mathematics on the
fixture's precomputed head outputs. The adapter routes them through its own
code (e.g. its loss with a stub model whose apply returns the fixture's
log-probabilities):
- log_softmax(logits[B,1024], legal) -> [B,1024]: the pair normalization the
  loss uses; kl_grad(logits, legal, tau) -> d KL(tau || pi) / d logits;
- loss_terms(ContractBatch) -> {"target_kl", "reference_kl", "value_loss",
  "total"}, each a mean over its own rows, c_V its own constant;
- row_gradients(ContractBatch) -> (pair [B,1024], team [B,360], value [B]):
  d total / d each row's pair logits, team logits and value;
- value_targets(GaeRows) -> [N] per row, from shuffled rows;
- drift(history) -> (stop, best_epoch); recipe() -> the pinned recipe;
- target_batches(idx, epoch) -> [steps, 512] (-1 padding);
  non_target_batches(idx, cursor, steps) -> ([steps, 3584], cursor).
Optimizer-state restore stays a Learner v2 acceptance test.
"""
from dataclasses import dataclass
import math

import numpy as np

from duoforge_learn import returns

JOINT = 1024
TEAMS = 360
KINDS = ("target", "non_target", "waiting", "forced", "preview", "padded", "opponent", "held_out")
_TARGET = ("target",)
_REFERENCE = ("non_target", "preview")  # acting rows with >= 2 legal actions and no target
_VALUE = ("target", "non_target", "waiting", "forced", "preview")
RECIPE = {"batch": 4096, "target_rows": 512, "non_target_rows": 3584, "optimizer": "adam", "lr": 3e-5,
          "clip": 0.5, "max_epochs": 4, "max_steps": 128, "ref_coef": 0.1, "value_coef": 0.5, "gamma": 0.99,
          "lambda": 0.95, "patience": 2, "min_improvement": 1e-4, "max_ref_kl": 0.02, "ppo_policy": False,
          "magnet": False}


@dataclass(frozen=True)
class ContractBatch:
    """Rows of every kind with precomputed head outputs: pair logits and
    the frozen reference's (B, 1024) with the legal pair masks (empty for
    waiting and preview rows, one action for forced rows), team logits (B,
    360) normalized over all teams like the model's head with the team mask
    as the KL support, the teacher target as a full (B, 1024) distribution,
    values and value targets."""
    kind: np.ndarray
    logits: np.ndarray
    ref_logits: np.ndarray
    legal: np.ndarray
    team_logits: np.ndarray
    ref_team_logits: np.ndarray
    team_legal: np.ndarray
    tau: np.ndarray
    values: np.ndarray
    value_targets: np.ndarray


@dataclass(frozen=True)
class GaeRows:
    """Learner rows of several games in any order: game, seat, the per-game
    logical tick, acting, the actual reward and done, the collector's value
    and the stored bootstrap (read from each trajectory's last row)."""
    game_id: np.ndarray
    seat: np.ndarray
    logical_tick: np.ndarray
    acting: np.ndarray
    reward: np.ndarray
    done: np.ndarray
    collector_value: np.ndarray
    bootstrap: np.ndarray


@dataclass(frozen=True)
class ContractFixture:
    batch: ContractBatch
    gae: GaeRows
    drift_cases: tuple


@dataclass(frozen=True)
class ContractResult:
    passed: bool
    failures: tuple


def reference_log_softmax(logits, legal):
    """float64 log-softmax over each row's legal entries, -inf elsewhere; a
    row without a legal entry raises ValueError."""
    logits = np.asarray(logits, np.float64)
    legal = np.asarray(legal, bool)
    if logits.shape != legal.shape or logits.ndim != 2:
        raise ValueError("logits and legal must be matching (B, N) arrays")
    if not legal.any(axis=1).all():
        raise ValueError("a row without a legal action has no distribution")
    masked = np.where(legal, logits, -np.inf)
    top = masked.max(axis=1, keepdims=True)
    return masked - (top + np.log(np.sum(np.exp(masked - top), axis=1, keepdims=True)))


def reference_kl_grad(logits, legal, tau):
    """d KL(tau || softmax_legal(logits)) / d logits = pi sum(tau) - tau,
    zero on illegal entries."""
    p = np.exp(reference_log_softmax(logits, legal))
    tau = np.asarray(tau, np.float64)
    return np.where(legal, p * tau.sum(axis=1, keepdims=True) - tau, 0.0)


def _kl(p_log, q_log, support):
    """KL(p || q) per row over support entries with mass (no 0 * -inf)."""
    p = np.where(support, np.exp(p_log), 0.0)
    has = p > 0
    return np.sum(np.where(has, p * (np.where(has, p_log, 0.0) - np.where(has, q_log, 0.0)), 0.0), axis=1)


def _mean(values, rows):
    return float(values[rows].sum() / rows.sum()) if rows.any() else 0.0


def _pair_logp(logits, legal):
    """The pair log-softmax for rows with a legal pair, -inf rows elsewhere."""
    out = np.full(np.shape(logits), -np.inf)
    rows = np.asarray(legal).any(axis=1)
    if rows.any():
        out[rows] = reference_log_softmax(np.asarray(logits)[rows], np.asarray(legal)[rows])
    return out


def _heads(batch):
    everything = np.ones(np.shape(batch.team_logits), bool)  # the model's team head: all 360 teams
    return (_pair_logp(batch.logits, batch.legal), _pair_logp(batch.ref_logits, batch.legal),
            reference_log_softmax(batch.team_logits, everything),
            reference_log_softmax(batch.ref_team_logits, everything))


def _groups(batch):
    return tuple(np.isin(batch.kind, k) for k in (_TARGET, _REFERENCE, _VALUE))


def reference_loss_terms(batch):
    """mean_target KL(tau || pi) + 0.1 mean_non_target KL(pi_ref || pi) +
    c_V mean_value (v - target)^2, each mean over its own rows (preview rows
    on the team head); padded, opponent and held-out rows count nowhere."""
    logp, ref, team_logp, team_ref = _heads(batch)
    targets, refs, values = _groups(batch)
    tau = np.asarray(batch.tau, np.float64)
    with np.errstate(divide="ignore"):
        tau_log = np.where(tau > 0, np.log(np.where(tau > 0, tau, 1.0)), -np.inf)
    target_kl = _kl(tau_log, logp, tau > 0)
    team = batch.kind == "preview"
    ref_kl = np.where(team, _kl(team_ref, team_logp, batch.team_legal), _kl(ref, logp, batch.legal))
    value = (np.asarray(batch.values, np.float64) - np.asarray(batch.value_targets, np.float64)) ** 2
    terms = {"target_kl": _mean(target_kl, targets), "reference_kl": _mean(ref_kl, refs),
             "value_loss": _mean(value, values)}
    terms["total"] = (terms["target_kl"] + RECIPE["ref_coef"] * terms["reference_kl"]
                      + RECIPE["value_coef"] * terms["value_loss"])
    return terms


def reference_row_gradients(batch):
    """d total / d (each row's pair logits, team logits, value)."""
    logp, ref, team_logp, team_ref = _heads(batch)
    targets, refs, values = _groups(batch)
    team = batch.kind == "preview"
    g_pair = np.zeros(logp.shape)
    g_team = np.zeros(team_logp.shape)
    if targets.any():
        g_pair[targets] += reference_kl_grad(batch.logits[targets], batch.legal[targets], batch.tau[targets]) \
            / targets.sum()
    if refs.any():
        coef = RECIPE["ref_coef"] / refs.sum()
        pair_rows, team_rows = refs & ~team, refs & team
        g_pair[pair_rows] += coef * np.where(batch.legal, np.exp(logp) - np.exp(ref), 0.0)[pair_rows]
        # KL(p_ref || p) over the team support, p normalized over all teams.
        mass = np.where(batch.team_legal, np.exp(team_ref), 0.0)
        g_team[team_rows] += coef * (np.exp(team_logp) * mass.sum(axis=1, keepdims=True) - mass)[team_rows]
    g_value = np.zeros(len(batch.kind))
    if values.any():
        diff = np.asarray(batch.values, np.float64) - np.asarray(batch.value_targets, np.float64)
        g_value[values] = RECIPE["value_coef"] * 2.0 * diff[values] / values.sum()
    return g_pair, g_team, g_value


def reference_value_targets(rows):
    """Per row: returns.gae's value target of its (game, seat) trajectory,
    in logical-tick order (gapless from 0), the other seat absent, the
    stored bootstrap of the trajectory's last row (a cut-off game)."""
    out = np.zeros(np.shape(rows.game_id), np.float64)
    keys = set(zip(np.asarray(rows.game_id).tolist(), np.asarray(rows.seat).tolist()))
    for game, seat in sorted(keys):
        idx = np.flatnonzero((rows.game_id == game) & (rows.seat == seat))
        idx = idx[np.argsort(rows.logical_tick[idx], kind="stable")]
        if not np.array_equal(rows.logical_tick[idx], np.arange(idx.size)):
            raise ValueError(f"game {game} seat {seat}: logical ticks have a gap or repeat")
        if np.asarray(rows.done[idx[:-1]]).any():
            raise ValueError(f"game {game} seat {seat}: done before the last row")
        t = idx.size
        values, rewards, acting = (np.zeros((t, 1, 2)) for _ in range(3))
        values[:, 0, seat] = rows.collector_value[idx]
        rewards[:, 0, seat] = rows.reward[idx]
        acting[:, 0, seat] = rows.acting[idx]
        done = np.asarray(rows.done[idx], bool).reshape(t, 1)
        bootstrap = np.zeros((1, 2))
        bootstrap[0, seat] = rows.bootstrap[idx[-1]]
        out[idx] = returns.gae(values, rewards, done, acting.astype(bool), bootstrap,
                               gamma=RECIPE["gamma"], lam=RECIPE["lambda"])[2][:, 0, seat]
    return out


def reference_drift(history):
    """(stop, best_epoch) after the epochs so far. history[0] is the held-out
    evaluation before training (epoch 0); each entry holds held_kl (teacher),
    ref_kl and value_loss. Stop at any nonfinite metric, a reference KL
    above 0.02 (that epoch is never best), two epochs without a 1e-4-nat
    teacher-KL gain over the best so far, or the fourth epoch. The best epoch
    is the last one with such a gain (0: none)."""
    first = history[0]
    if not all(math.isfinite(v) for v in first.values()):
        return True, 0
    best, best_kl, stale = 0, first["held_kl"], 0
    for epoch, h in enumerate(history[1:], start=1):
        if not all(math.isfinite(v) for v in h.values()) or h["ref_kl"] > RECIPE["max_ref_kl"]:
            return True, best
        if h["held_kl"] < best_kl - RECIPE["min_improvement"]:
            best, best_kl, stale = epoch, h["held_kl"], 0
        else:
            stale += 1
        if stale >= RECIPE["patience"] or epoch >= RECIPE["max_epochs"]:
            return True, best
    return False, best


def reference_target_batches(idx, epoch, *, seed):
    """Each epoch a keyed permutation of the training targets, RECIPE
    target_rows per step, the last step padded with -1."""
    order = np.random.default_rng([seed, 1, epoch]).permutation(np.asarray(idx))
    rows = RECIPE["target_rows"]
    steps = -(-len(order) // rows)
    out = np.full(steps * rows, -1, np.int64)
    out[:len(order)] = order
    return out.reshape(steps, rows)


def reference_non_target_batches(idx, cursor, steps, *, seed):
    """One stream of non-target rows across steps and epochs, a keyed
    permutation per lap; the cursor (lap, position) resumes it."""
    idx = np.asarray(idx)
    lap, pos = cursor
    need, parts = steps * RECIPE["non_target_rows"], []
    while need:
        perm = np.random.default_rng([seed, 2, lap]).permutation(idx)
        take = perm[pos:pos + need]
        parts.append(take)
        need -= len(take)
        pos += len(take)
        if pos == len(idx):
            lap, pos = lap + 1, 0
    return np.concatenate(parts).reshape(steps, RECIPE["non_target_rows"]), (lap, pos)


def _drift_cases():
    def h(*entries):
        return tuple({"held_kl": held, "ref_kl": ref, "value_loss": value} for held, ref, value in entries)
    ok = 0.01
    return (
        (h((1.0, 0.0, 0.3), (0.9, ok, 0.3), (0.8, ok, 0.3), (0.7, ok, 0.3), (0.6, ok, 0.3)), (True, 4)),
        (h((1.0, 0.0, 0.3), (0.99995, ok, 0.3), (0.99999, ok, 0.3)), (True, 0)),  # below the minimum gain
        (h((1.0, 0.0, 0.3), (0.99994, ok, 0.3), (0.99988, ok, 0.3)), (False, 2)),  # gain counted against the best
        (h((1.0, 0.0, 0.3), (0.8, ok, 0.3), (0.7, 0.03, 0.3)), (True, 1)),  # reference KL breach, never best
        (h((1.0, 0.0, 0.3), (0.9, 0.02, 0.3)), (False, 1)),  # exactly 0.02 is allowed
        (h((1.0, 0.0, 0.3), (0.9, math.nan, 0.3)), (True, 0)),
        (h((1.0, 0.0, 0.3), (0.9, ok, math.inf)), (True, 0)),  # any nonfinite metric
        (h((math.nan, 0.0, 0.3)), (True, 0)),
        (h((1.0, 0.0, 0.3), (0.9, ok, 0.3)), (False, 1)),
        (h((1.0, 0.0, 0.3), (0.9, ok, 0.3), (0.89995, ok, 0.3), (0.7, ok, 0.3)), (False, 3)),  # a gain resets
    )


def _gae_rows(rng):
    """Two games, shuffled: game 11 learner seat 1 cut off (bootstrap 0.37),
    game 12 learner seat 0 ending with a win; both with waiting rows."""
    cols = {k: [] for k in ("game_id", "seat", "logical_tick", "acting", "reward", "done", "collector_value",
                            "bootstrap")}
    for game, seat, acting, final, done in ((11, 1, (1, 0, 1, 1, 0), 0.0, False), (12, 0, (1, 1, 0, 1), 1.0, True)):
        for tick, act in enumerate(acting):
            last = tick == len(acting) - 1
            for name, value in (("game_id", game), ("seat", seat), ("logical_tick", tick), ("acting", bool(act)),
                                ("reward", final if last else 0.0), ("done", done and last),
                                ("collector_value", float(rng.uniform(-1, 1))),
                                ("bootstrap", 0.37 if last and not done else 0.0)):
                cols[name].append(value)
    order = rng.permutation(len(cols["game_id"]))
    return GaeRows(**{k: np.asarray(v)[order] for k, v in cols.items()})


def make_fixture(seed=20261016):
    """The deterministic synthetic fixture: every row kind with real mask
    shapes, sparse targets with low-logit support, shuffled GAE rows and the
    drift cases. No trained weights."""
    rng = np.random.default_rng(seed)
    kind = np.array(["target"] * 3 + ["non_target"] * 3 + ["waiting"] * 2 + ["forced"] * 2 + ["preview"] * 2
                    + ["padded"] * 2 + ["opponent"] + ["held_out"] * 2)
    b = kind.size
    legal = rng.random((b, JOINT)) < 0.2
    legal[:, :2] = True
    legal[np.isin(kind, ("waiting", "preview"))] = False
    legal[kind == "forced"] = False
    legal[kind == "forced", 5] = True
    logits = rng.normal(size=(b, JOINT)).astype(np.float32)
    ref_logits = (logits + rng.normal(scale=0.3, size=(b, JOINT))).astype(np.float32)
    team_logits = rng.normal(size=(b, TEAMS)).astype(np.float32)
    ref_team_logits = (team_logits + rng.normal(scale=0.3, size=(b, TEAMS))).astype(np.float32)
    tau = np.zeros((b, JOINT))
    for row in np.flatnonzero(np.isin(kind, ("target", "held_out"))):
        ids = np.flatnonzero(legal[row])
        order = ids[np.argsort(logits[row, ids], kind="stable")]  # lowest logits first
        support = np.concatenate([order[:4], order[-4:]])  # the teacher may favour low-prior actions
        mass = rng.random(support.size) + 0.05
        tau[row, support] = mass / math.fsum(mass.tolist())
    values = rng.uniform(-1, 1, b).astype(np.float32)
    value_targets = rng.uniform(-1, 1, b)
    batch = ContractBatch(kind, logits, ref_logits, legal, team_logits, ref_team_logits, np.ones((b, TEAMS), bool),
                          tau, values, value_targets)
    return ContractFixture(batch, _gae_rows(rng), _drift_cases())


def _collect(checks):
    failures = []
    for name, fn in checks:
        try:
            message = fn()
        except Exception as err:  # the code under test may fail anywhere: report, never mask
            message = f"{type(err).__name__}: {err}"
        if message:
            failures.append(f"{name}: {message}")
    return ContractResult(not failures, tuple(failures))


def _normalized(got, legal):
    got = np.asarray(got, np.float64)
    if got.shape != legal.shape:
        return f"shape {got.shape}"
    if not np.isneginf(got[~legal]).all():
        return "illegal joint actions must be -inf"
    if not np.isfinite(got[legal]).all():
        return "a legal joint action has no finite log-probability"
    lse = np.log(np.sum(np.exp(np.where(legal, got, -np.inf)), axis=1))
    if not np.allclose(lse, 0.0, rtol=0, atol=1e-5):
        return "not a log-softmax over every legal joint action"
    return None


def _refuses(fn):
    try:
        fn()
    except ValueError:
        return None
    return "a row without a legal action was not refused"


def validate_provider(provider, obs, slots, legal) -> ContractResult:
    """The real full_joint_log_probs (params bound) on real rows with at
    least one legal action each: normalization and the zero-legal refusal."""
    legal = np.asarray(legal, bool).reshape(len(obs), -1)

    def zero_legal():
        empty = legal.copy()
        empty[-1] = False
        return _refuses(lambda: provider(obs, slots, empty.reshape(np.shape(legal))))

    return _collect((("normalization", lambda: _normalized(provider(obs, slots, legal), legal)),
                     ("zero_legal", zero_legal)))


def validate_adapter(adapter, fixture) -> ContractResult:
    """Every loss-side contract check against the reference; failures name
    the check. Any exception of the adapter fails its check."""
    b = fixture.batch
    pair_rows = b.legal.any(axis=1)

    def normalization():
        got = adapter.log_softmax(b.logits[pair_rows], b.legal[pair_rows])
        message = _normalized(got, b.legal[pair_rows])
        if message:
            return message
        want = reference_log_softmax(b.logits[pair_rows], b.legal[pair_rows])
        if not np.allclose(np.asarray(got, np.float64)[b.legal[pair_rows]], want[b.legal[pair_rows]], rtol=0,
                           atol=1e-5):
            return "differs from the full-legal log-softmax"
        return None

    def zero_legal():
        legal = b.legal[:2].copy()
        legal[1] = False
        return _refuses(lambda: adapter.log_softmax(b.logits[:2], legal))

    def gradient():
        rows = np.isin(b.kind, ("target", "held_out"))
        got = np.asarray(adapter.kl_grad(b.logits[rows], b.legal[rows], b.tau[rows]), np.float64)
        if not np.isfinite(got).all():
            return "nonfinite gradient"
        if (got[~b.legal[rows]] != 0).any():
            return "gradient on illegal joint actions"
        if not np.allclose(got, reference_kl_grad(b.logits[rows], b.legal[rows], b.tau[rows]), rtol=1e-5, atol=1e-6):
            return "not d KL(tau || pi) / d logits of the full-legal softmax"
        return None

    def loss():
        got, want = adapter.loss_terms(b), reference_loss_terms(b)
        if set(got) != set(want):
            return f"terms {sorted(got)}"
        bad = [k for k in want if not math.isclose(float(got[k]), want[k], rel_tol=1e-5, abs_tol=1e-8)]
        return f"terms differ: {bad}" if bad else None

    def gradients():
        got = tuple(np.asarray(x, np.float64) for x in adapter.row_gradients(b))
        want = reference_row_gradients(b)
        dead = np.isin(b.kind, ("padded", "opponent", "held_out"))
        for name, g, w in zip(("pair", "team", "value"), got, want):
            if g.shape != w.shape:
                return f"{name} shape {g.shape}"
            if (g[dead] != 0).any():
                return f"padded, opponent or held-out rows receive {name} gradient"
            if not np.allclose(g, w, rtol=1e-5, atol=1e-7):
                return f"{name} gradients differ from the reference loss"
        return None

    def gae():
        got = np.asarray(adapter.value_targets(fixture.gae), np.float64)
        want = reference_value_targets(fixture.gae)
        if got.shape != want.shape or not np.allclose(got, want, rtol=0, atol=1e-6):
            return "value targets are not returns.gae per (game, seat) in tick order with the stored bootstrap"
        return None

    def drift():
        bad = [i for i, (history, want) in enumerate(fixture.drift_cases) if tuple(adapter.drift(history)) != want]
        return f"cases {bad}" if bad else None

    def recipe():
        got = dict(adapter.recipe())
        return None if got == RECIPE else f"{ {k: got.get(k) for k in RECIPE if got.get(k) != RECIPE[k]} }"

    def batches():
        idx = np.arange(1100) + 7
        rows = RECIPE["target_rows"]
        epochs = [np.asarray(adapter.target_batches(idx, e)) for e in (0, 1)]
        for e, tb in enumerate(epochs):
            if tb.ndim != 2 or tb.shape[1] != rows or tb.shape[0] != -(-idx.size // rows):
                return f"epoch {e} target batches have shape {tb.shape}"
            flat = tb.reshape(-1)
            if sorted(flat[flat >= 0].tolist()) != idx.tolist() or (flat[idx.size:] != -1).any():
                return f"epoch {e} does not visit every label once with a padded tail"
        if np.array_equal(epochs[0], epochs[1]):
            return "the target order does not change between epochs"
        if not np.array_equal(np.asarray(adapter.target_batches(idx, 0)), epochs[0]):
            return "target batches are not a pure function of the epoch"
        pool = np.arange(5000) + 3
        whole, end = adapter.non_target_batches(pool, (0, 0), 5)
        first, cursor = adapter.non_target_batches(pool, (0, 0), 2)
        rest, end2 = adapter.non_target_batches(pool, cursor, 3)
        whole = np.asarray(whole)
        if whole.shape != (5, RECIPE["non_target_rows"]):
            return f"non-target batches have shape {whole.shape}"
        if not np.array_equal(np.concatenate([first, rest]), whole) or tuple(end2) != tuple(end):
            return "the non-target stream does not resume from its cursor"
        counts = np.bincount(whole.reshape(-1)[:3 * pool.size] - 3, minlength=pool.size)
        if not (counts == 3).all():
            return "each lap of the non-target stream must visit every row once"
        return None

    return _collect((("normalization", normalization), ("zero_legal", zero_legal), ("gradient", gradient),
                     ("loss", loss), ("gradients", gradients), ("gae", gae), ("drift", drift),
                     ("recipe", recipe), ("batches", batches)))
