"""Luck-adjusted evaluation: the value head as a control variate over chance.

At every step of an evaluate.play_suite game, the joint action both seats
chose is also played from the same root under K other chance seeds
(Batch.expand, decision 0022). The step's luck, from the learner's seat, is
the value of the state that happened minus the mean value of the K
alternatives. The actual successor and the alternatives come from the same
chance distribution, so a step's luck has mean zero whatever the value head
is worth; a game's adjusted result, its result minus its summed luck, keeps
the expected score and loses the variance the value head explains.

A leaf's value from the learner's seat: a refused step (E_UNSUPPORTED) -1,
as play_suite scores a game the engine refuses; a terminal leaf its result
(+1, -1, 0 for a tie); otherwise the value head (about -1..1, the scale of a
result). The actual successor is valued the same way. play_suite's last
step (max_steps - 1) is never corrected: a cut-off game is scored by the
tiebreak, which the leaves do not reproduce, and leaving out a term keeps
the mean. Chance inside a step is resolved in C in one call, so a step (a
turn, a replacement, a pivot) is the finest unit without engine changes.

Keys: a step's leaves of environment e at loop index t are seeded with
search_seeds(seed, draw(seed, LUCK_TAG, e, t), sample), sample = 0..K-1:
the luck is a pure function of the seeds and the capacity (the value calls'
shape, as in the lookahead), independent of the workers.
"""
import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge.context import reference_setups

from .pairing import draw

LUCK_SEED = 0x2026100500000001
LUCK_TAG = 0x4C55434B  # "LUCK"
CAPACITY = 1024

C = _layout.CONSTANTS
_WINS = (C["DUOFORGE_RESULT_SIDE_0"], C["DUOFORGE_RESULT_SIDE_1"])
_TIE = C["DUOFORGE_RESULT_TIE"]
_RESULTS = (_WINS[0], _WINS[1], _TIE)
_UNSUPPORTED = C["DUOFORGE_E_UNSUPPORTED"]


class LuckError(RuntimeError):
    """A leaf the luck measurement cannot value: the run stops."""


def _side(results, seats):
    """+1 where results is seats' win, 0 for a tie, -1 for the other side's."""
    win = np.where(np.asarray(seats) == 0, _WINS[0], _WINS[1])
    return np.where(results == win, 1.0, np.where(results == _TIE, 0.0, -1.0))


def leaf_values(values, step_statuses, encode_statuses, leaf_results, seat):
    """The value of every leaf from seat's side (an int or one per leaf), float64."""
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    step = np.asarray(step_statuses).astype(np.int64).reshape(-1)
    encode = np.asarray(encode_statuses).astype(np.int64).reshape(-1)
    results = np.asarray(leaf_results).astype(np.int64).reshape(-1)
    seats = np.broadcast_to(np.asarray(seat, dtype=np.int64), values.shape)
    bad = np.flatnonzero((step != 0) & (step != _UNSUPPORTED))
    if bad.size:
        raise LuckError(f"leaf {bad[0]}: the engine refused the step with status {step[bad[0]]}")
    refused = step == _UNSUPPORTED
    terminal = ~refused & (results != 0)
    bad = np.flatnonzero(terminal & ~np.isin(results, _RESULTS))
    if bad.size:
        raise LuckError(f"leaf {bad[0]}: an unknown result {results[bad[0]]}")
    open_ = ~refused & ~terminal
    bad = np.flatnonzero(open_ & (encode != 0))
    if bad.size:
        raise LuckError(f"leaf {bad[0]}: the encoder refused the row with status {encode[bad[0]]}")
    bad = np.flatnonzero(open_ & ~np.isfinite(values))
    if bad.size:
        raise LuckError(f"leaf {bad[0]}: the value head gives {values[bad[0]]!r}")
    out = values.copy()
    out[refused] = -1.0
    out[terminal] = _side(results[terminal], seats[terminal])
    return out


def adjusted_scores(records, totals):
    """The luck-adjusted score of every record: (result - summed luck + 1) / 2.
    It may leave [0, 1]; its mean estimates the expected score."""
    return (records["result"].astype(np.float64) - np.asarray(totals, dtype=np.float64) + 1.0) / 2.0


class Luck:
    """The luck measurement of play_suite games (play_suite's luck=), valued
    by one fixed network (model, params, encoder, ext_supported). start()
    resets it for a suite; after the games, totals (one per row) holds each
    game's summed luck, terms the number of corrected steps and step_terms
    every step's luck. It owns a leaf batch of `capacity` environments:
    close it (or use it as a context manager)."""

    def __init__(self, context, model, params, encoder, ext_supported=0, k=8, seed=LUCK_SEED, capacity=CAPACITY,
                 workers=1):
        for name, x in (("k", k), ("capacity", capacity), ("workers", workers)):
            if int(x) < 1:
                raise ValueError(f"{name} must be at least 1 (got {x})")
        width = features.obs_size(encoder)
        if width != len(model.feature_names):
            raise ValueError(f"encoder {encoder} gives rows of {width} values, the model reads "
                             f"{len(model.feature_names)}")
        self.model, self.params = model, params
        self.encoder, self.ext_supported = int(encoder), int(ext_supported)
        self.k, self.seed, self.capacity = int(k), int(seed), int(capacity)
        self.leaves = duoforge.Batch(context, np.resize(reference_setups([0]), self.capacity), int(workers),
                                     self.seed)
        self._rows = np.zeros((self.capacity, width), dtype=np.float32)
        self.model.value(self.params, self._rows)  # compiled once, one shape
        self._actual = None
        self.start(0, np.zeros(0, dtype=np.int64))

    def close(self):
        self.leaves.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self, n, seats):
        """A new suite of n games, the learner on seats (n,)."""
        self.seats = np.asarray(seats, dtype=np.int64).reshape(-1)
        if self.seats.size != n:
            raise ValueError("one learner seat per game")
        self.totals = np.zeros(n, dtype=np.float64)
        self.terms = np.zeros(n, dtype=np.int64)
        self._steps = []
        self._pending = None

    @property
    def step_terms(self):
        """Every corrected step's luck, in order (float64)."""
        return np.concatenate(self._steps) if self._steps else np.zeros(0, dtype=np.float64)

    def before(self, batch, indices, active, step, last_step):
        """Before batch.step(indices): the mean value of the K alternatives of
        every active game's step. batch.requests and batch.domains are the
        query the indices were chosen in (play_suite's)."""
        self._pending = None
        if last_step:
            return
        envs = np.flatnonzero(np.asarray(active, dtype=bool))
        if envs.size == 0:
            return
        requested = batch.requests["requested"] != 0
        choices = np.zeros((envs.size, 2), dtype=_layout.FACTORED_CHOICE)
        for p in (0, 1):
            asked = requested[envs, p]
            if asked.any():
                e = envs[asked]
                choices[asked, p] = duoforge.factored_choices(batch.domains[e, p], indices[e, p])
        keys = np.zeros(batch.envs, dtype=np.uint64)
        keys[envs] = draw(self.seed, LUCK_TAG, envs, np.full(envs.size, int(step)))
        viewers = np.zeros(batch.envs, dtype=np.uint8)
        viewers[envs] = self.seats[envs]
        root_envs = np.repeat(envs, self.k).astype(np.uint32)
        samples = np.tile(np.arange(self.k, dtype=np.uint32), envs.size)
        leaf_choices = np.repeat(choices, self.k, axis=0)
        leaf_seats = self.seats[root_envs]
        total = root_envs.size
        values = np.empty(total, dtype=np.float64)
        for c0 in range(0, total, self.capacity):
            c1 = min(total, c0 + self.capacity)
            obs, st, enc, _, lres = self.leaves.expand(batch, self.encoder, self.ext_supported, self.seed, keys,
                                                       viewers, root_envs[c0:c1], samples[c0:c1],
                                                       leaf_choices[c0:c1])
            self._rows[:c1 - c0] = obs
            self._rows[c1 - c0:] = 0.0  # one compiled shape; the padding rows are not read
            head = np.asarray(self.model.value(self.params, self._rows))[:c1 - c0]
            values[c0:c1] = leaf_values(head, st, enc, lres, leaf_seats[c0:c1])
        self._pending = (envs, values.reshape(envs.size, self.k).mean(axis=1))

    def after(self, batch, dead):
        """After the step: each pending game's luck, the value of the state
        that happened minus its alternatives' mean. dead marks the games the
        engine refused (play_suite scores them -1)."""
        if self._pending is None:
            return
        envs, means = self._pending
        self._pending = None
        actual = np.empty(envs.size, dtype=np.float64)
        open_ = np.zeros(envs.size, dtype=bool)
        for i, e in enumerate(envs):
            if dead[e]:
                actual[i] = -1.0
                continue
            result = batch.result(int(e))
            if result == 0:
                open_[i] = True
            elif result in _RESULTS:
                actual[i] = _side(result, self.seats[e])
            else:
                raise LuckError(f"environment {e}: an unknown result {result}")
        if open_.any():
            obs, _, _ = batch.query_encoded(self.encoder, self.ext_supported)
            if self._actual is None or self._actual.shape[0] != batch.envs:
                self._actual = np.zeros((batch.envs, obs.shape[2]), dtype=np.float32)
            self._actual[:] = obs[np.arange(batch.envs), self.seats[:batch.envs]]
            head = np.asarray(self.model.value(self.params, self._actual), dtype=np.float64)[envs[open_]]
            if not np.isfinite(head).all():
                raise LuckError("the value head gives a value that is not finite at an actual successor")
            actual[open_] = head
        luck = actual - means
        self.totals[envs] += luck
        self.terms[envs] += 1
        self._steps.append(luck)
