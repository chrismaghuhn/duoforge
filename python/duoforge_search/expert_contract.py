"""The P1 learner contract (plan C4, decision 0024): reference and fixtures.

M12 states what Learner v2's distillation must compute and checks an adapter
against it; it implements no optimizer, trainer or second learner. The
adapter is NumPy in, NumPy out (no JAX here):

- log_softmax(logits[B,1024], legal[B,1024]) -> [B,1024]: the full-joint
  normalization the loss uses, over every legal joint action, -inf where
  illegal; a row without a legal action raises ValueError;
- kl_grad(logits, legal, tau) -> [B,1024]: d KL(tau || pi) / d logits;
- loss_terms(ContractBatch) -> {"target_kl", "reference_kl", "value_loss",
  "total"}: each a mean over its own valid rows;
- row_grad_norms(ContractBatch) -> [B]: zero for padded, opponent and
  held-out rows;
- value_targets(GaeFixture) -> [T]: returns.gae on the stored inputs;
- drift(history) -> (stop, best_epoch); recipe() -> the pinned recipe.
"""
from dataclasses import dataclass
import math

import numpy as np

from duoforge_learn import returns

JOINT = 1024
TEAMS = 360
KINDS = ("target", "non_target", "waiting", "preview", "padded", "opponent", "held_out")
_TARGET = ("target",)
_REFERENCE = ("non_target", "preview")  # acting rows without a target: KL(pi49333 || pi)
_VALUE = ("target", "non_target", "waiting", "preview")
RECIPE = {"batch": 4096, "target_rows": 512, "non_target_rows": 3584, "optimizer": "adam", "lr": 3e-5,
          "clip": 0.5, "max_epochs": 4, "max_steps": 128, "ref_coef": 0.1, "patience": 2, "min_improvement": 1e-4,
          "max_ref_kl": 0.02}


@dataclass(frozen=True)
class ContractBatch:
    """Rows of every kind with precomputed head outputs: pair logits and
    the frozen reference's (B, 1024), their legal masks, team logits for
    preview rows (B, 360), the sparse teacher target as a full (B, 1024)
    distribution, values and value targets, and the value coefficient."""
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
    c_v: float


@dataclass(frozen=True)
class GaeFixture:
    """returns.gae inputs of one game: values/rewards/acting (T, 1, 2),
    done (T, 1), bootstrap (1, 2), and the learner's seat."""
    values: np.ndarray
    rewards: np.ndarray
    done: np.ndarray
    acting: np.ndarray
    bootstrap: np.ndarray
    seat: int


@dataclass(frozen=True)
class ContractFixture:
    batch: ContractBatch
    gae: GaeFixture
    drift_cases: tuple


@dataclass(frozen=True)
class ContractResult:
    passed: bool
    failures: tuple


def reference_log_softmax(logits, legal):
    """float64 log-softmax over each row's legal entries, -inf elsewhere."""
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
    """d KL(tau || softmax_legal(logits)) / d logits = pi * sum(tau) - tau,
    zero on illegal entries."""
    p = np.exp(reference_log_softmax(logits, legal))
    tau = np.asarray(tau, np.float64)
    return np.where(legal, p * tau.sum(axis=1, keepdims=True) - tau, 0.0)


def _kl(p_log, q_log, legal):
    """KL(p || q) per row over legal entries with mass (no 0 * -inf)."""
    p = np.where(legal, np.exp(p_log), 0.0)
    return np.sum(np.where(p > 0, p * (np.where(p > 0, p_log, 0.0) - np.where(p > 0, q_log, 0.0)), 0.0), axis=1)


def _mean(values, rows):
    return float(values[rows].sum() / rows.sum()) if rows.any() else 0.0


def _heads(batch):
    team = batch.kind == "preview"
    logp = reference_log_softmax(batch.logits, batch.legal)
    ref = reference_log_softmax(batch.ref_logits, batch.legal)
    team_logp = reference_log_softmax(batch.team_logits, batch.team_legal)
    team_ref = reference_log_softmax(batch.ref_team_logits, batch.team_legal)
    return team, logp, ref, team_logp, team_ref


def reference_loss_terms(batch):
    """mean_target KL(tau || pi) + 0.1 mean_non_target KL(pi_ref || pi) +
    c_V mean_value (v - target)^2, each mean over its own rows; padded,
    opponent and held-out rows count nowhere."""
    team, logp, ref, team_logp, team_ref = _heads(batch)
    tau = np.asarray(batch.tau, np.float64)
    with np.errstate(divide="ignore"):
        tau_log = np.where(tau > 0, np.log(np.where(tau > 0, tau, 1.0)), -np.inf)
    target_kl = _kl(tau_log, logp, tau > 0)
    ref_kl = np.where(team, _kl(team_ref, team_logp, batch.team_legal), _kl(ref, logp, batch.legal))
    value = (np.asarray(batch.values, np.float64) - np.asarray(batch.value_targets, np.float64)) ** 2
    terms = {"target_kl": _mean(target_kl, np.isin(batch.kind, _TARGET)),
             "reference_kl": _mean(ref_kl, np.isin(batch.kind, _REFERENCE)),
             "value_loss": _mean(value, np.isin(batch.kind, _VALUE))}
    terms["total"] = terms["target_kl"] + RECIPE["ref_coef"] * terms["reference_kl"] + batch.c_v * terms["value_loss"]
    return terms


def reference_row_grad_norms(batch):
    """Per row, the norm of d total / d (its logits, its value)."""
    team, logp, ref, team_logp, team_ref = _heads(batch)
    targets, refs, values = (np.isin(batch.kind, k) for k in (_TARGET, _REFERENCE, _VALUE))
    tau = np.asarray(batch.tau, np.float64)
    g_pair = np.zeros(logp.shape)
    g_team = np.zeros(team_logp.shape)
    if targets.any():
        g_pair[targets] += reference_kl_grad(batch.logits, batch.legal, tau)[targets] / targets.sum()
    if refs.any():
        coef = RECIPE["ref_coef"] / refs.sum()
        pair_rows, team_rows = refs & ~team, refs & team
        g_pair[pair_rows] += coef * np.where(batch.legal, np.exp(logp) - np.exp(ref), 0.0)[pair_rows]
        g_team[team_rows] += coef * np.where(batch.team_legal, np.exp(team_logp) - np.exp(team_ref), 0.0)[team_rows]
    g_value = np.zeros(len(batch.kind))
    if values.any():
        diff = np.asarray(batch.values, np.float64) - np.asarray(batch.value_targets, np.float64)
        g_value[values] = batch.c_v * 2.0 * diff[values] / values.sum()
    return np.sqrt(np.sum(g_pair ** 2, axis=1) + np.sum(g_team ** 2, axis=1) + g_value ** 2)


def reference_value_targets(gae):
    """returns.gae's value targets of the learner's seat (unchanged gamma,
    lambda; a cut-off game uses its stored bootstrap)."""
    return returns.gae(gae.values, gae.rewards, gae.done, gae.acting, gae.bootstrap)[2][:, 0, gae.seat]


def reference_drift(history):
    """(stop, best_epoch) after the epochs so far. history[0] is the
    held-out evaluation before training (epoch 0); each later entry holds an
    epoch's held-out teacher KL and reference KL. Stop at a nonfinite metric,
    a reference KL above 0.02 (that epoch is never best), two epochs without
    a 1e-4-nat teacher-KL gain, or the fourth epoch. The best epoch is the
    last one with such a gain (0: none)."""
    first = history[0]
    if not (math.isfinite(first["held_kl"]) and math.isfinite(first["ref_kl"])):
        return True, 0
    best, best_kl, stale = 0, first["held_kl"], 0
    for epoch, h in enumerate(history[1:], start=1):
        held, ref = h["held_kl"], h["ref_kl"]
        if not (math.isfinite(held) and math.isfinite(ref)) or ref > RECIPE["max_ref_kl"]:
            return True, best
        if held < best_kl - RECIPE["min_improvement"]:
            best, best_kl, stale = epoch, held, 0
        else:
            stale += 1
        if stale >= RECIPE["patience"] or epoch >= RECIPE["max_epochs"]:
            return True, best
    return False, best


def _drift_cases():
    def h(*pairs):
        return tuple({"held_kl": held, "ref_kl": ref} for held, ref in pairs)
    return (
        (h((1.0, 0.0), (0.9, 0.01), (0.8, 0.01), (0.7, 0.01), (0.6, 0.01)), (True, 4)),  # fourth epoch
        (h((1.0, 0.0), (0.99995, 0.01), (0.99999, 0.01)), (True, 0)),  # two epochs below the minimum gain
        (h((1.0, 0.0), (0.8, 0.01), (0.7, 0.03)), (True, 1)),  # reference KL breach, never best
        (h((1.0, 0.0), (math.nan, 0.01)), (True, 0)),  # nonfinite
        (h((1.0, 0.0), (0.9, 0.01)), (False, 1)),  # still running
        (h((1.0, 0.0), (0.9, 0.01), (0.89995, 0.01), (0.7, 0.01)), (False, 3)),  # a gain resets patience
    )


def make_fixture(seed=20261016):
    """The deterministic synthetic fixture: every row kind, sparse targets
    with low-logit support, preview rows on the team head, a cut-off game
    for GAE and the drift cases. No trained weights."""
    rng = np.random.default_rng(seed)
    kind = np.array(["target"] * 3 + ["non_target"] * 3 + ["waiting"] * 2 + ["preview"] * 2 + ["padded"] * 2
                    + ["opponent"] + ["held_out"] * 2)
    b = kind.size
    legal = rng.random((b, JOINT)) < 0.2
    legal[:, :2] = True
    logits = rng.normal(size=(b, JOINT)).astype(np.float32)
    ref_logits = (logits + rng.normal(scale=0.3, size=(b, JOINT))).astype(np.float32)
    team_legal = rng.random((b, TEAMS)) < 0.5
    team_legal[:, 0] = True
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
    batch = ContractBatch(kind, logits, ref_logits, legal, team_logits, ref_team_logits, team_legal, tau,
                          values, value_targets, 0.5)
    t, seat = 5, 1
    acting = np.zeros((t, 1, 2), bool)
    acting[[0, 2, 3], 0, seat] = True  # the learner waits at steps 1 and 4
    rewards = np.zeros((t, 1, 2))
    rewards[3, 0, seat] = 0.25
    gae = GaeFixture(rng.uniform(-1, 1, (t, 1, 2)), rewards, np.zeros((t, 1), bool), acting,
                     np.array([[0.0, 0.37]]), seat)
    return ContractFixture(batch, gae, _drift_cases())


def validate_adapter(adapter, fixture) -> ContractResult:
    """Every contract check against the reference; failures name the check.
    Any exception of the adapter fails its check (zero_legal expects one)."""
    b = fixture.batch
    failures = []

    def check(name, fn):
        try:
            message = fn()
        except Exception as err:  # the adapter is under test: report, never mask
            message = f"{type(err).__name__}: {err}"
        if message:
            failures.append(f"{name}: {message}")

    def normalization():
        got = np.asarray(adapter.log_softmax(b.logits, b.legal), np.float64)
        if got.shape != b.logits.shape:
            return f"shape {got.shape}"
        if not np.isneginf(got[~b.legal]).all():
            return "illegal joint actions must be -inf"
        if not np.allclose(got[b.legal], reference_log_softmax(b.logits, b.legal)[b.legal], rtol=0, atol=1e-5):
            return "not the log-softmax over every legal joint action"
        return None

    def zero_legal():
        legal = b.legal[:2].copy()
        legal[1] = False
        try:
            adapter.log_softmax(b.logits[:2], legal)
        except ValueError:
            return None
        return "a row without a legal action was not refused"

    def gradient():
        rows = np.isin(b.kind, ("target", "held_out"))
        got = np.asarray(adapter.kl_grad(b.logits[rows], b.legal[rows], b.tau[rows]), np.float64)
        if not np.isfinite(got).all():
            return "nonfinite gradient"
        if (got[~b.legal[rows]] != 0).any():
            return "gradient on illegal joint actions"
        if not np.allclose(got, reference_kl_grad(b.logits[rows], b.legal[rows], b.tau[rows]), rtol=0, atol=1e-6):
            return "not d KL(tau || pi) / d logits of the full-legal softmax"
        return None

    def loss():
        got, want = adapter.loss_terms(b), reference_loss_terms(b)
        if set(got) != set(want):
            return f"terms {sorted(got)}"
        bad = [k for k in want if not math.isclose(float(got[k]), want[k], rel_tol=1e-6, abs_tol=1e-9)]
        return f"terms differ: {bad}" if bad else None

    def masks():
        got = np.asarray(adapter.row_grad_norms(b), np.float64)
        dead = np.isin(b.kind, ("padded", "opponent", "held_out"))
        if got.shape != (len(b.kind),):
            return f"shape {got.shape}"
        if (got[dead] != 0).any():
            return "padded, opponent or held-out rows receive gradient"
        if not np.allclose(got[~dead], reference_row_grad_norms(b)[~dead], rtol=1e-5, atol=1e-9):
            return "row gradients differ from the reference loss"
        return None

    def gae():
        got = np.asarray(adapter.value_targets(fixture.gae), np.float64)
        want = reference_value_targets(fixture.gae)
        if got.shape != want.shape or not np.allclose(got, want, rtol=0, atol=1e-9):
            return "value targets are not returns.gae on the stored inputs"
        return None

    def drift():
        bad = [i for i, (history, want) in enumerate(fixture.drift_cases) if tuple(adapter.drift(history)) != want]
        return f"cases {bad}" if bad else None

    def recipe():
        got = dict(adapter.recipe())
        return None if got == RECIPE else f"{ {k: got.get(k) for k in RECIPE if got.get(k) != RECIPE[k]} }"

    for name, fn in (("normalization", normalization), ("zero_legal", zero_legal), ("gradient", gradient),
                     ("loss", loss), ("masks", masks), ("gae", gae), ("drift", drift), ("recipe", recipe)):
        check(name, fn)
    return ContractResult(not failures, tuple(failures))
