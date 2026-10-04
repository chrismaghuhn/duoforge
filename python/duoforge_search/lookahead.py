"""The one-turn lookahead (spec sections 4.2, 5 and 7, decision 0022).

A decision of seat p at a root: the K own pairs the network's policy ranks
highest and the M foe pairs the opponent model ranks highest (stage 1: the
same network on the foe's row of the root), S samples per cell. Every leaf
is the root after one step with an own and a foe pair, its gameplay RNG
first replaced by the search seeds of (search seed, decision key, sample)
(Batch.expand), and is valued from p's side: the value head on p's row of
the leaf, the exact result at TERMINAL, the reference's tiebreak at the
arena's cut-off. The table A[i, j] is the mean over the samples. The Nash
rule plays its equilibrium strategy by the decision's play draw; the
expected-value rule plays the row with the highest expected value under the
foe's probabilities.

The search knows no rule: legality is the engine's pair mask, outcomes,
results and the tiebreak are the engine's, values are the network's. Every
refusal is explicit (spec section 7): a refused leaf (E_UNSUPPORTED) counts
-1 and is counted; any other leaf status and every encoder refusal stop the
run with a SearchError that carries the leaf's reproduction data.

select, leaf_plan, table, split_half and near_duplicates are NumPy; the
Lookahead runs the network through duoforge_learn.policy.Model (JAX).
"""
import math
import time
from typing import NamedTuple

import numpy as np

import duoforge
from duoforge import _layout, features, status_name
from duoforge.context import reference_setups

from . import matrix, seeds
from .errors import SearchError

C = _layout.CONSTANTS
SEARCH_SEED = 0x2026100300000221
CAPACITY = 16384  # leaves per expand and value call (the leaf capacity L)
NEAR_DUPLICATE = 1e-6  # two rows of a table whose largest difference is below it are near-duplicates
OPTIONS = _layout.MAX_SLOT_OPTIONS
PAIRS = OPTIONS * OPTIONS
NO_FOE = -1  # the foe's pair where the foe has no request (its empty response)
UNRESOLVED = -1  # the tiebreak of a leaf the engine cannot resolve (the reference's bench order would decide)
RULES = ("nash", "ev", "mix")

_SLOTS = C["DUOFORGE_CHOICE_SLOTS"]
_TEAM = C["DUOFORGE_CHOICE_TEAM_SELECTION"]
_WINS = (C["DUOFORGE_RESULT_SIDE_0"], C["DUOFORGE_RESULT_SIDE_1"])
_TIE = C["DUOFORGE_RESULT_TIE"]
_RESULTS = (_WINS[0], _WINS[1], _TIE)
_UNSUPPORTED = C["DUOFORGE_E_UNSUPPORTED"]
_BOUNDARIES = {C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]: "TEAM_SELECTION", C["DUOFORGE_BOUNDARY_TURN"]: "TURN",
               C["DUOFORGE_BOUNDARY_REPLACEMENT"]: "REPLACEMENT", C["DUOFORGE_BOUNDARY_PIVOT"]: "PIVOT",
               C["DUOFORGE_BOUNDARY_TERMINAL"]: "TERMINAL"}


def select(logp, mask, k):
    """The candidate pairs of one row (spec section 5.1): (flat pair
    indices, probabilities) of the legal pairs of mask, ranked by logp,
    highest first, equal values (compared exactly) to the lower flat index;
    k' = min(k, legal pairs). logp (1024,) log-probabilities and mask
    (1024,) or (32, 32) bool, flat index i0 * 32 + i1; the probabilities
    are exp(logp) in float64."""
    if int(k) < 1:
        raise ValueError(f"k must be at least 1 (got {k})")
    logp = np.asarray(logp).reshape(-1)
    legal = np.flatnonzero(np.asarray(mask, dtype=bool).reshape(-1))
    if logp.shape != (PAIRS,) or legal.size == 0 or legal[-1] >= PAIRS:
        raise SearchError(f"a requested row needs {PAIRS} log-probabilities and a legal pair")
    if not np.isfinite(logp[legal]).all():
        raise SearchError("the policy gives a legal pair a log-probability that is not finite")
    top = legal[np.argsort(-logp[legal], kind="stable")[:int(k)]]
    return top.astype(np.int64), np.exp(logp[top].astype(np.float64))


def leaf_plan(k_counts, m_counts, s):
    """(decision, i, j, sample) of every leaf, int64 arrays ordered by
    decision, then i, j and sample: decision d has k_counts[d] x m_counts[d]
    cells of s samples each."""
    k_counts = np.asarray(k_counts, dtype=np.int64).reshape(-1)
    m_counts = np.asarray(m_counts, dtype=np.int64).reshape(-1)
    s = int(s)
    if k_counts.shape != m_counts.shape or (k_counts < 1).any() or (m_counts < 1).any() or s < 1:
        raise ValueError(f"a plan needs positive counts and samples (got {k_counts}, {m_counts}, {s})")
    sizes = k_counts * m_counts * s
    decision = np.repeat(np.arange(sizes.size, dtype=np.int64), sizes)
    rank = np.arange(decision.size, dtype=np.int64) - np.repeat(np.cumsum(sizes) - sizes, sizes)
    cell, sample = np.divmod(rank, s)
    i, j = np.divmod(cell, m_counts[decision])
    return decision, i, j, sample


class Table(NamedTuple):
    """The table of one decision: a (K', M') float64 cell means, stderr
    (K', M') their standard errors (NaN for one sample), counts of the
    leaf kinds, and values (K', M', S) every leaf's value."""
    a: np.ndarray
    stderr: np.ndarray
    counts: dict
    values: np.ndarray


def _side(results, seat):
    """+1 where results is seat's win, 0 for a tie, -1 for the other side's."""
    return np.where(results == _WINS[seat], 1.0, np.where(results == _TIE, 0.0, -1.0))


def _leaf_error(leaf, what):
    err = SearchError(f"leaf {leaf}: {what}")
    err.leaf = leaf
    return err


def table(values, step_statuses, encode_statuses, leaf_results, tiebreaks, plan, seat, last_step=False):
    """The Table of one decision from its leaves (spec sections 5.3, 5.4 and
    7). plan is (i, j, sample) of every leaf (leaf_plan's last three arrays
    for this decision), seat the deciding seat: every value is from its
    side. A leaf's value:
      - a refused step (E_UNSUPPORTED): -1, counted as refused (the arena
        scores a game the engine refuses as the agent's loss);
      - TERMINAL (leaf_results): +1, -1, or 0 for a tie;
      - at the arena's cut-off (last_step): its tiebreak, tiebreaks holding
        the DUOFORGE_RESULT_* of Batch.tiebreak, or UNRESOLVED where the
        engine cannot resolve it, which counts -1; counted as cut off;
      - else the value head's (values, float32).
    Any other step status, any encoder refusal, a tiebreak missing at the
    cut-off or present before it, and a value that is not finite raise
    SearchError naming the leaf (attribute leaf: its index in these
    arrays): the run stops. counts: refused, terminal, cut_off,
    unresolved."""
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    n = values.size
    step = np.asarray(step_statuses).astype(np.int64).reshape(-1)
    encode = np.asarray(encode_statuses).astype(np.int64).reshape(-1)
    results = np.asarray(leaf_results).astype(np.int64).reshape(-1)
    tiebreaks = np.asarray(tiebreaks).astype(np.int64).reshape(-1)
    i, j, sample = (np.asarray(x, dtype=np.int64).reshape(-1) for x in plan)
    if n == 0 or any(x.size != n for x in (step, encode, results, tiebreaks, i, j, sample)):
        raise ValueError(f"a table needs the same positive number of every leaf array (got {n} values)")
    if seat not in (0, 1):
        raise ValueError(f"a seat is 0 or 1 (got {seat!r})")
    k, m, s = int(i.max()) + 1, int(j.max()) + 1, int(sample.max()) + 1
    cell = (i * m + j) * s + sample
    if n != k * m * s or (i < 0).any() or (j < 0).any() or (sample < 0).any() or \
            not (np.bincount(cell, minlength=n) == 1).all():
        raise ValueError(f"the plan must hold every (i, j, sample) of a {k} x {m} x {s} table once")
    bad = np.flatnonzero((step != 0) & (step != _UNSUPPORTED))
    if bad.size:
        raise _leaf_error(int(bad[0]), f"the engine refused the step with {status_name(int(step[bad[0]]))}")
    bad = np.flatnonzero(encode != 0)
    if bad.size:
        raise _leaf_error(int(bad[0]), f"the encoder refused the row with {status_name(int(encode[bad[0]]))}")
    refused = step == _UNSUPPORTED
    terminal = ~refused & (results != 0)
    bad = np.flatnonzero(terminal & ~np.isin(results, _RESULTS))
    if bad.size:
        raise _leaf_error(int(bad[0]), f"an unknown result {int(results[bad[0]])}")
    open_ = ~refused & ~terminal
    v = values.astype(np.float64)
    v[refused] = -1.0
    v[terminal] = _side(results[terminal], seat)
    cut = open_ if last_step else np.zeros(n, dtype=bool)
    unresolved = cut & (tiebreaks == UNRESOLVED)
    bad = np.flatnonzero((cut & ~unresolved & ~np.isin(tiebreaks, _RESULTS)) | (~cut & (tiebreaks != 0)))
    if bad.size:
        raise _leaf_error(int(bad[0]), f"a tiebreak {int(tiebreaks[bad[0]])} where the leaf is "
                                       f"{'at' if cut[bad[0]] else 'not at'} the cut-off")
    resolved = cut & ~unresolved
    v[resolved] = _side(tiebreaks[resolved], seat)
    v[unresolved] = -1.0
    bad = np.flatnonzero(~np.isfinite(v))
    if bad.size:
        raise _leaf_error(int(bad[0]), f"the value head gives {v[bad[0]]!r}")
    cube = np.empty(n, dtype=np.float64)
    cube[cell] = v
    cube = cube.reshape(k, m, s)
    a = np.empty((k, m), dtype=np.float64)
    stderr = np.full((k, m), np.nan, dtype=np.float64)
    for r in range(k):
        for c in range(m):
            x = cube[r, c].tolist()
            mean = math.fsum(x) / s
            a[r, c] = mean
            if s > 1:
                stderr[r, c] = math.sqrt(math.fsum((t - mean) ** 2 for t in x) / (s - 1) / s)
    counts = {"refused": int(refused.sum()), "terminal": int(terminal.sum()), "cut_off": int(cut.sum()),
              "unresolved": int(unresolved.sum())}
    return Table(a, stderr, counts, cube)


def _means(cube):
    k, m, s = cube.shape
    return np.array([[math.fsum(cube[r, c].tolist()) / s for c in range(m)] for r in range(k)], dtype=np.float64)


def split_half(values, q, rule):
    """Split-half stability of one decision (spec section 8.5): the tables
    of the samples [0, S/2) and [S/2, S) of values (K', M', S), compared.
    Rule "ev": {"same_choice"}, whether both halves' expected-value rows
    agree (q the foe's probabilities). Rule "nash": {"exploitability"}, each
    half's equilibrium measured in the other half's table, (first in second,
    second in first). None for an odd S."""
    values = np.asarray(values, dtype=np.float64)
    s = values.shape[2]
    if s % 2:
        return None
    first, second = _means(values[:, :, :s // 2]), _means(values[:, :, s // 2:])
    rank = np.arange(values.shape[0])
    if rule == "ev":
        return {"same_choice": matrix.expected_choice(first, q, rank) == matrix.expected_choice(second, q, rank)}
    if rule == "nash":
        a, b = matrix.solve(first), matrix.solve(second)
        return {"exploitability": [matrix.exploitability(second, a.x, a.y), matrix.exploitability(first, b.x, b.y)]}
    raise ValueError(f"unknown rule {rule!r}: one of {RULES}")


def near_duplicates(a, tol=NEAR_DUPLICATE):
    """The number of pairs of rows of a whose largest difference is below
    tol (the review of #199 asked how often real tables have them)."""
    a = np.asarray(a, dtype=np.float64)
    return int(sum(np.max(np.abs(a[r] - a[t])) < tol for r in range(a.shape[0]) for t in range(r + 1, a.shape[0])))


class Lookahead:
    """The one-turn lookahead of one network (spec section 4.2), on the true
    state of a root batch: an oracle benchmark (ARCHITECTURE section 10).

    model and params: a duoforge_learn.policy.Model and its parameters;
    encoder and ext_supported: the encoder version and view-extension mask
    they were trained with, refused here by a zero-leaf probe when the C
    encoder refuses them; k, m, s: candidates and samples (spec section 5);
    rule: "nash" or "ev"; seed: the search seed; capacity: the leaves of
    one expand and value call (the leaf batch, created here, and the value
    call's padded rows); workers: the leaf batch's workers.

    A decision is reproduced bit for bit by the same seeds, network,
    library, JAX version, device and capacity: a row's value does not depend
    on its position in the value call, but another batch shape changes the
    network's float32 values in the last bits.

    Times per decision (records' "time", seconds): the network (its share of
    the root policy call and of the value calls), the engine (its share of
    the expand calls and tiebreaks), the reduction (table and rule) and the
    split halves' extra solves. The value call is compiled here and the
    policy call once per root batch size, outside the timed calls."""

    def __init__(self, context, model, params, encoder, ext_supported, k=8, m=8, s=16, rule="nash",
                 seed=SEARCH_SEED, capacity=CAPACITY, workers=8, lam=0.5):
        if rule not in RULES:
            raise ValueError(f"unknown rule {rule!r}: one of {RULES}")
        if not 0 <= lam <= 1:
            raise ValueError("lam must be between 0 and 1")
        self.lam = float(lam)
        for name, x in (("k", k), ("m", m), ("s", s), ("capacity", capacity), ("workers", workers)):
            if int(x) < 1:
                raise ValueError(f"{name} must be at least 1 (got {x})")
        width = features.obs_size(encoder)
        if width != len(model.feature_names):
            raise ValueError(f"encoder {encoder} gives rows of {width} values, the model reads "
                             f"{len(model.feature_names)}")
        self.model, self.params = model, params
        self.encoder, self.ext_supported = int(encoder), int(ext_supported)
        self.k, self.m, self.s, self.rule, self.seed = int(k), int(m), int(s), rule, int(seed)
        self.capacity = int(capacity)
        self.leaves = duoforge.Batch(context, np.resize(reference_setups([0]), self.capacity), int(workers), seed)
        try:
            with duoforge.Batch(context, reference_setups([0]), 1, seed) as probe:
                self.leaves.expand(probe, self.encoder, self.ext_supported, self.seed, np.zeros(1, np.uint64),
                                   np.zeros(1, np.uint8), np.zeros(0, np.uint32), np.zeros(0, np.uint32),
                                   np.zeros((0, 2), _layout.FACTORED_CHOICE))
        except BaseException:
            self.leaves.close()
            raise
        self._rows = np.zeros((self.capacity, width), dtype=np.float32)
        self.model.value(self.params, self._rows)  # compiled here: no decision's time holds the compilation
        self._compiled = set()  # the root batch sizes the policy call is compiled for
        self.last = None  # the leaves of the last decide (diagnostics and tests)

    def close(self):
        self.leaves.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def decide(self, roots, envs, seats, keys, last_step):
        """The actions of seats[d] in environments envs[d] of the Batch
        roots, with decision keys keys[d] (seeds.decision_keys) and
        last_step[d] true where this step is the arena's last: (actions
        (len(envs),) int64 in the model's convention, a flat pair index at
        a turn and a team tuple index at TEAM_SELECTION (selfplay.choices_of),
        records, one dict per decision). Every listed seat must be requested;
        an environment is listed once.

        roots is queried here (query_encoded with the search's encoder and
        mask), and its requests and domains are the leaves' roots. Spec
        section 5.7: TEAM_SELECTION and a forced decision (one legal pair)
        are played by the raw network without leaves; every other decision
        is searched. The records hold the fields of spec section 8.5."""
        start = time.perf_counter()
        envs = np.asarray(envs, dtype=np.int64).reshape(-1)
        n = envs.size
        seats = np.asarray(seats, dtype=np.int64).reshape(-1)
        keys = np.asarray(keys, dtype=np.uint64).reshape(-1)
        last_step = np.asarray(last_step, dtype=bool).reshape(-1)
        if seats.size != n or keys.size != n or last_step.size != n:
            raise ValueError("envs, seats, keys and last_step need one entry per decision")
        if n and ((envs < 0).any() or (envs >= roots.envs).any() or np.unique(envs).size != n
                  or not np.isin(seats, (0, 1)).all()):
            raise ValueError("decisions need distinct environments of the roots and seats 0 or 1")
        obs, slots, pairs = roots.query_encoded(self.encoder, self.ext_supported)
        requests, domains = roots.requests, roots.domains
        if n == 0:
            self.last = None
            return np.zeros(0, dtype=np.int64), []
        rows = 2 * roots.envs
        inputs = (obs.reshape(rows, -1), slots.reshape((rows,) + slots.shape[2:]),
                  pairs.reshape((rows,) + pairs.shape[2:]))
        self.model.check(inputs[0])
        query_time = time.perf_counter() - start
        if rows not in self._compiled:  # compiled outside the timed call
            np.asarray(self.model.apply(self.params, *inputs)[0])
            self._compiled.add(rows)
        start = time.perf_counter()
        logp_pairs, logp_team, _ = self.model.apply(self.params, *inputs)
        logp_pairs = np.asarray(logp_pairs).reshape(roots.envs, 2, PAIRS)
        logp_team = np.asarray(logp_team).reshape(roots.envs, 2, -1)
        policy_time = (query_time + time.perf_counter() - start) / n

        actions = np.zeros(n, dtype=np.int64)
        records = [None] * n
        searched = []  # (decision, own pairs, their probabilities, foe pairs, theirs)
        for d in range(n):
            e, p = int(envs[d]), int(seats[d])
            if requests[e, p]["requested"] == 0:
                raise ValueError(f"seat {p} of environment {e} has no request: there is no decision")
            boundary = int(requests[e, p]["boundary_kind"])
            base = {"search": "oracle", "env": e, "seat": p, "key": int(keys[d]), "epoch": int(requests[e, p]["epoch"]),
                    "boundary": _BOUNDARIES.get(boundary, boundary), "last_step": bool(last_step[d])}
            kind = int(domains[e, p]["kind"])
            if kind == _TEAM:
                actions[d] = int(np.argmax(logp_team[e, p]))
                records[d] = {**base, "kind": "team", "choice": int(actions[d])}
                continue
            if kind != _SLOTS:
                raise SearchError(f"environment {e}, seat {p}: a request of choice kind {kind}")
            legal = pairs[e, p].reshape(-1)
            if int(legal.sum()) == 1:
                actions[d] = int(np.flatnonzero(legal)[0])
                records[d] = {**base, "kind": "forced", "choice": int(actions[d])}
                continue
            own, own_p = select(logp_pairs[e, p], legal, self.k)
            f = 1 - p
            if requests[e, f]["requested"] != 0:
                if int(domains[e, f]["kind"]) != _SLOTS:
                    raise SearchError(f"environment {e}: the foe's request has choice kind "
                                      f"{int(domains[e, f]['kind'])} at a turn")
                foe, foe_p = select(logp_pairs[e, f], pairs[e, f], self.m)
            else:
                foe, foe_p = np.array([NO_FOE], dtype=np.int64), np.array([1.0])
            searched.append((d, own, own_p, foe, foe_p))
            records[d] = base
        if searched:
            self._search(roots, envs, seats, keys, last_step, searched, actions, records, policy_time)
        else:
            self.last = None
        for d in range(n):
            if records[d]["kind"] != "searched":
                records[d]["time"] = {"network": policy_time, "engine": 0.0, "reduction": 0.0, "split": 0.0}
        return actions, records

    def _search(self, roots, envs, seats, keys, last_step, searched, actions, records, policy_time):
        q_count = len(searched)
        own_tab = np.full((q_count, self.k), -1, dtype=np.int64)
        foe_tab = np.full((q_count, self.m), -1, dtype=np.int64)
        for q, (_, own, _, foe, _) in enumerate(searched):
            own_tab[q, :own.size] = own
            foe_tab[q, :foe.size] = foe
        dec = np.array([x[0] for x in searched], dtype=np.int64)
        decision, ci, cj, sample = leaf_plan([x[1].size for x in searched], [x[3].size for x in searched], self.s)
        total = decision.size
        own_pair = own_tab[decision, ci]
        foe_pair = foe_tab[decision, cj]
        seat = seats[dec][decision]
        choices = np.zeros((total, 2), dtype=_layout.FACTORED_CHOICE)
        slot = choices["slot"]
        leaf = np.arange(total)
        slot[leaf, seat, 0], slot[leaf, seat, 1] = np.divmod(own_pair, OPTIONS)
        asked = foe_pair != NO_FOE
        slot[leaf[asked], 1 - seat[asked], 0], slot[leaf[asked], 1 - seat[asked], 1] = \
            np.divmod(foe_pair[asked], OPTIONS)
        root_envs = envs[dec][decision].astype(np.uint32)
        samples = sample.astype(np.uint32)
        root_keys = np.zeros(roots.envs, dtype=np.uint64)
        root_keys[envs[dec]] = keys[dec]
        viewers = np.zeros(roots.envs, dtype=np.uint8)
        viewers[envs[dec]] = seats[dec]
        last_leaf = last_step[dec][decision]

        values = np.zeros(total, dtype=np.float32)
        step_statuses = np.zeros(total, dtype=np.uint32)
        encode_statuses = np.zeros(total, dtype=np.uint32)
        leaf_results = np.zeros(total, dtype=np.uint32)
        boundaries = np.zeros(total, dtype=np.uint32)
        tiebreaks = np.zeros(total, dtype=np.int64)
        engine_time = np.zeros(q_count)
        network_time = np.zeros(q_count)
        for c0 in range(0, total, self.capacity):
            c1 = min(total, c0 + self.capacity)
            t0 = time.perf_counter()
            obs, st, enc, res, lres = self.leaves.expand(roots, self.encoder, self.ext_supported, self.seed,
                                                         root_keys, viewers, root_envs[c0:c1], samples[c0:c1],
                                                         choices[c0:c1])
            step_statuses[c0:c1], encode_statuses[c0:c1], leaf_results[c0:c1] = st, enc, lres
            boundaries[c0:c1] = res["boundary_kind"]
            for x in np.flatnonzero(last_leaf[c0:c1] & (st == 0) & (lres == 0)):  # the arena's cut-off
                try:
                    tiebreaks[c0 + x] = self.leaves.tiebreak(int(x))
                except duoforge.DuoforgeError as err:
                    if err.status_name != "DUOFORGE_E_UNSUPPORTED":
                        raise
                    tiebreaks[c0 + x] = UNRESOLVED
            t1 = time.perf_counter()
            self._rows[:c1 - c0] = obs
            self._rows[c1 - c0:] = 0.0  # one compiled shape; the padding rows are not read
            values[c0:c1] = np.asarray(self.model.value(self.params, self._rows))[:c1 - c0]
            t2 = time.perf_counter()
            share = np.bincount(decision[c0:c1], minlength=q_count) / (c1 - c0)
            engine_time += (t1 - t0) * share
            network_time += (t2 - t1) * share
        self.last = {"decision": decision, "i": ci, "j": cj, "sample": sample, "root_envs": root_envs,
                     "samples": samples, "choices": choices, "values": values, "step_statuses": step_statuses,
                     "encode_statuses": encode_statuses, "leaf_results": leaf_results, "boundaries": boundaries,
                     "tiebreaks": tiebreaks, "tables": []}

        first = np.searchsorted(decision, np.arange(q_count))
        stop = np.searchsorted(decision, np.arange(q_count), side="right")
        for q, (d, own, own_p, foe, foe_p) in enumerate(searched):
            t0 = time.perf_counter()
            sl = slice(int(first[q]), int(stop[q]))
            try:
                tab = table(values[sl], step_statuses[sl], encode_statuses[sl], leaf_results[sl], tiebreaks[sl],
                            (ci[sl], cj[sl], sample[sl]), int(seats[d]), bool(last_step[d]))
            except SearchError as err:
                if not hasattr(err, "leaf"):
                    raise
                x = sl.start + err.leaf
                raise self._stopped(roots, err, int(envs[d]), int(seats[d]), int(keys[d]), int(own_pair[x]),
                                    int(foe_pair[x]), int(sample[x]), int(step_statuses[x]),
                                    int(encode_statuses[x])) from err
            self.last["tables"].append(tab)
            rank = np.arange(own.size)
            try:
                from .honest import reduce
                u = float(seeds.play_uniforms(self.seed, keys[d:d + 1])[0])
                outcomes, reduced = reduce(tab.a[None], np.ones(1), foe_p[None], rank, u, self.lam, oracle=True)
                row = outcomes[self.rule]
                reduced["outcomes"] = outcomes
                reduced["y"] = reduced["ys"][0]
                t1 = time.perf_counter()
                split = split_half(tab.values, foe_p, "nash" if self.rule == "mix" else self.rule)
            except SearchError as err:
                raise self._unsolved(err, int(envs[d]), int(seats[d]), int(keys[d]), own, foe, foe_p, tab) from err
            t2 = time.perf_counter()
            actions[d] = int(own[row])
            ok = step_statuses[sl] == 0
            kinds = boundaries[sl][ok]
            records[d] = {
                **records[d], "kind": "searched", "rule": self.rule, "k": int(own.size), "m": int(foe.size),
                "s": self.s, "own_pairs": own.tolist(), "own_probs": own_p.tolist(), "foe_pairs": foe.tolist(),
                "foe_probs": foe_p.tolist(), "coverage": math.fsum(foe_p.tolist()), "table": tab.a.tolist(),
                "stderr": tab.stderr.tolist(), **reduced, "choice": int(actions[d]), "raw": int(own[0]),
                "changed": int(actions[d]) != int(own[0]), "split": split, "near_duplicates": near_duplicates(tab.a),
                "leaves": {**tab.counts, **{name: int((kinds == b).sum()) for b, name in _BOUNDARIES.items()
                                            if name != "TEAM_SELECTION"}},
                "time": {"network": policy_time + float(network_time[q]), "engine": float(engine_time[q]),
                         "reduction": t1 - t0, "split": t2 - t1}}

    def _unsolved(self, err, env, seat, key, own, foe, foe_p, tab):
        """The SearchError that stops the run when a table cannot be reduced
        (spec section 7: a missed Nash certificate writes the table), with the
        decision, its table and its leaf values in the attribute
        reproduction."""
        stop = SearchError(f"{err} (environment {env}, seat {seat}, rule {self.rule}): the run stops "
                           f"(spec section 7)")
        stop.reproduction = {"env": env, "seat": seat, "key": key, "search_seed": self.seed, "rule": self.rule,
                             "own_pairs": own.tolist(), "foe_pairs": foe.tolist(), "foe_probs": foe_p.tolist(),
                             "table": tab.a.tolist(), "values": tab.values.tolist()}
        return stop

    def _stopped(self, roots, err, env, seat, key, own_pair, foe_pair, sample, step_status, encode_status):
        """The SearchError that stops the run at a leaf (spec section 7),
        with its reproduction data in the attribute reproduction: the
        root's canonical encoding (privileged), the pair, the sample and the
        seeds."""
        initstate, initseq = duoforge.search_seeds(self.seed, key, sample)
        stop = SearchError(f"{err} (environment {env}, seat {seat}, own pair {own_pair}, foe pair {foe_pair}, "
                           f"sample {sample}): the run stops (spec section 7)")
        stop.reproduction = {"env": env, "seat": seat, "key": key, "search_seed": self.seed, "sample": sample,
                             "initstate": initstate, "initseq": initseq, "own_pair": own_pair, "foe_pair": foe_pair,
                             "step_status": status_name(step_status), "encode_status": status_name(encode_status),
                             "encoder": self.encoder, "ext_supported": self.ext_supported,
                             "root": roots.encode(env).hex()}
        return stop
