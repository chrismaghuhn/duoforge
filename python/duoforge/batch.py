"""A batch of environments over the C batch runtime (decision 0012, M7).

Python allocates every buffer once and calls the library once per batch
operation; the C side runs the environments on its worker pool with the GIL
released. A batch has one caller at a time.
"""
import ctypes

import numpy as np

from . import _layout
from ._lib import load_library, ptr, status_name, uint
from .errors import DuoforgeError, DuoforgeLibraryError

_SLOTS = _layout.CONSTANTS["DUOFORGE_CHOICE_SLOTS"]
_TEAM = _layout.CONSTANTS["DUOFORGE_CHOICE_TEAM_SELECTION"]
_OPTIONS = _layout.MAX_SLOT_OPTIONS
_INVALID_ARGUMENT = _layout.CONSTANTS["DUOFORGE_E_INVALID_ARGUMENT"]
_AUTORESET = _layout.CONSTANTS["DUOFORGE_BATCH_AUTORESET"]


def _require(array, dtype, shape, name):
    """The checks before a caller's array goes to C: dtype, shape, order."""
    if not isinstance(array, np.ndarray) or array.dtype != dtype:
        found = array.dtype if isinstance(array, np.ndarray) else type(array).__name__
        raise TypeError(f"{name} must be an ndarray of {dtype}, not {found}")
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, not {array.shape}")
    if not array.flags["C_CONTIGUOUS"]:
        raise ValueError(f"{name} must be C-contiguous")
    if not array.flags["ALIGNED"]:
        raise ValueError(f"{name} must be aligned for its dtype")


def _buffer(name):
    return property(lambda self: self._buffers[name],
                    doc=f"The batch's {name} buffer: allocated once, its attribute cannot be replaced.")


class Batch:
    """Environments of one context stepped together (duoforge_batch_*).

    Buffers, allocated once: requests (E,2), observations (E,2), candidates
    (E,2,784), counts (E,2) uint32, domains (E,2) for the factored form,
    statuses (E,) uint32, results (E,) and episode_results (E,) uint32. Their contents may be read and
    written; the attributes cannot be replaced, since C writes into them.
    """

    requests = _buffer("requests")
    observations = _buffer("observations")
    candidates = _buffer("candidates")
    counts = _buffer("counts")
    domains = _buffer("domains")
    statuses = _buffer("statuses")
    results = _buffer("results")
    episode_results = _buffer("episode_results")

    def __init__(self, context, setups, workers, seed):
        self._handle = None  # set only after a successful create, so __del__ is safe
        if context.handle is None:
            raise ValueError("the context is closed")
        if not isinstance(setups, np.ndarray) or setups.ndim != 1 or setups.shape[0] < 1:
            raise ValueError("setups must be a one-dimensional ndarray with at least one setup")
        _require(setups, _layout.SETUP, setups.shape, "setups")
        self._lib = load_library()
        self.context = context
        self.envs = int(setups.shape[0])
        self.seed = uint(seed, 64, "seed")
        self._setups = setups.copy()  # what the environments run, for records of this batch
        self.setups = self._setups.view()  # read-only to callers; reset_setups updates it
        self.setups.flags.writeable = False
        config = np.zeros((), dtype=_layout.BATCH_CONFIG)
        config["env_count"] = self.envs
        config["worker_count"] = uint(workers, 32, "workers")
        config["seed"] = self.seed
        config["setups"] = setups.ctypes.data  # copied by the create
        handle = ctypes.c_void_p()
        st = self._lib.duoforge_batch_create(context.handle, ptr(config), ctypes.byref(handle))
        if st != 0:
            raise DuoforgeError(status_name(st))
        self._handle = handle
        context._batches.add(self)
        envs = self.envs
        self._buffers = {
            "requests": np.zeros((envs, 2), dtype=_layout.REQUEST),
            "observations": np.zeros((envs, 2), dtype=_layout.OBSERVATION),
            "candidates": np.zeros((envs, 2, _layout.MAX_CANDIDATES), dtype=_layout.SIDE_CHOICE),
            "counts": np.zeros((envs, 2), dtype=np.uint32),
            "domains": np.zeros((envs, 2), dtype=_layout.FACTORED_DOMAIN),
            "statuses": np.zeros(envs, dtype=np.uint32),
            "results": np.zeros(envs, dtype=_layout.STEP_RESULT),
            "episode_results": np.zeros(envs, dtype=np.uint32),
        }

    # ---------------------------------------------------------- step mode

    def public(self, players):
        """Public records (E,) and per-env statuses. Both returned arrays are
        borrowed buffers overwritten by the next public() call; copy them
        to retain a history snapshot.

        An invalid batch argument raises before C touches any environment;
        an unsupported environment keeps its record and reports its status.
        """
        _require(players, np.uint32, (self.envs,), "players")
        if (players > 1).any():
            raise ValueError("players must hold 0 or 1")
        if "public" not in self._buffers:
            self._buffers["public"] = (np.zeros(self.envs, _layout.PUBLIC_STATE), np.zeros(self.envs, np.uint32))
        views, statuses = self._buffers["public"]
        statuses.fill(0xFFFFFFFF)
        st = self._lib.duoforge_batch_public(self._live(), ptr(players), ptr(views), ptr(statuses))
        if st and (statuses == 0xFFFFFFFF).all():
            self._check(st)
        return views, statuses

    def public_causes(self, players):
        """The DUOFORGE_PUBLIC_CAUSE_* mask of every environment (E,) uint32 and
        per-env statuses (duoforge_batch_public_causes, decision 0026 section 4):
        why public() refuses, decided by the player's view alone (a visible
        sleep or confusion, a possible Illusion); 0 when public() succeeds or
        refuses for another cause. Borrowed buffers, overwritten by the next
        call. An invalid batch argument raises before C touches any
        environment."""
        _require(players, np.uint32, (self.envs,), "players")
        if (players > 1).any():
            raise ValueError("players must hold 0 or 1")
        if "public_causes" not in self._buffers:
            self._buffers["public_causes"] = (np.zeros(self.envs, np.uint32), np.zeros(self.envs, np.uint32))
        masks, statuses = self._buffers["public_causes"]
        masks.fill(0)
        statuses.fill(0xFFFFFFFF)
        st = self._lib.duoforge_batch_public_causes(self._live(), ptr(players), ptr(masks), ptr(statuses))
        if st and (statuses == 0xFFFFFFFF).all():
            self._check(st)
        return masks, statuses

    def from_view(self, views, hypotheses, count=None):
        """Build the first count worlds; return per-env statuses, preserving
        each failed environment. Inputs must be contiguous structured arrays.
        """
        if count is None:
            count = len(views)
        count = uint(count, 32, "count")
        if count > self.envs:
            raise ValueError(f"{count} worlds do not fit {self.envs} environments")
        _require(views, _layout.PUBLIC_STATE, (count,), "views")
        _require(hypotheses, _layout.HYPOTHESIS, (count,), "hypotheses")
        if "from_view" not in self._buffers:
            self._buffers["from_view"] = np.zeros(self.envs, np.uint32)
        statuses = self._buffers["from_view"][:count]
        statuses.fill(0xFFFFFFFF)
        st = self._lib.duoforge_batch_from_view(self._live(), ptr(views), ptr(hypotheses), count, ptr(statuses))
        if st and (statuses == 0xFFFFFFFF).all():
            self._check(st)
        return statuses

    def query(self):
        """Fills requests, observations, candidates and counts."""
        self._check(self._lib.duoforge_batch_query(self._live(), ptr(self.requests), ptr(self.observations),
                                                   ptr(self.candidates), ptr(self.counts)))

    def step(self, indices, active=None):
        """Steps every non-TERMINAL environment by candidate index: uint16,
        shape (E,2), NO_CHOICE for players without a request. With active
        (bool, shape (E,)), the environments outside it are not stepped and
        keep their state (their statuses read OK); their indices must be
        NO_CHOICE. A failure raises DuoforgeError with the per-environment
        statuses, named after the lowest failing environment."""
        _require(indices, np.uint16, (self.envs, 2), "indices")
        if active is not None:
            _require(active, np.bool_, (self.envs,), "active")
            if (indices[~active] != _layout.NO_CHOICE).any():
                raise ValueError("an environment outside active has a choice")
        status = self._lib.duoforge_batch_step_indices(
            self._live(), ptr(self.requests), ptr(self.candidates), ptr(self.counts), ptr(indices),
            ptr(self.statuses), ptr(self.results))
        if status != 0 and active is not None:
            # Outside active, NO_CHOICE fails a requested player's environment
            # with E_INVALID_ARGUMENT and leaves it unchanged (outcomes are
            # atomic per environment): that is the skip, not a failure.
            self.statuses[~active & (self.statuses == _INVALID_ARGUMENT)] = 0
            failed = np.flatnonzero(self.statuses)
            status = int(self.statuses[failed[0]]) if failed.size else 0
        self._check(status, per_env=True)

    def step_query(self, indices, autoreset=False, observations=True):
        """step(indices), then - with autoreset - the reset of every TERMINAL
        environment to its next episode, then query(), in one pass over the
        environments (duoforge_batch_step_query): the RL loop's step.
        episode_results holds the result (DUOFORGE_RESULT_*, never 0) of every
        episode that is TERMINAL after the step and 0 for the others. With
        autoreset, np.flatnonzero(batch.episode_results) are exactly the
        environments this call reset - also those already TERMINAL on entry,
        whose results entry is all-zero - so a loop should re-seed by it.
        With observations=False the observation buffer keeps its contents. A
        failure raises DuoforgeError with the per-environment statuses."""
        _require(indices, np.uint16, (self.envs, 2), "indices")
        self._check(self._lib.duoforge_batch_step_query(
            self._live(), _AUTORESET if autoreset else 0, ptr(indices), ptr(self.requests),
            ptr(self.observations) if observations else None, ptr(self.candidates), ptr(self.counts),
            ptr(self.episode_results), ptr(self.statuses), ptr(self.results)), per_env=True)

    def query_factored(self):
        """Fills requests, observations and the factored domains."""
        self._check(self._lib.duoforge_batch_query_factored(self._live(), ptr(self.requests),
                                                            ptr(self.observations), ptr(self.domains)))

    def step_factored(self, choices):
        """Steps every non-TERMINAL environment by factored choice
        (FACTORED_CHOICE, shape (E,2)), as step()."""
        _require(choices, _layout.FACTORED_CHOICE, (self.envs, 2), "choices")
        self._check(self._lib.duoforge_batch_step_factored(
            self._live(), ptr(self.requests), ptr(self.domains), ptr(choices), ptr(self.statuses),
            ptr(self.results)), per_env=True)

    def reset(self, env, episode):
        """Resets one environment to `episode` (the seed derivation's battle)."""
        self._check(self._lib.duoforge_batch_reset(self._live(), self._env(env), uint(episode, 32, "episode")))

    def reset_setups(self, envs, episodes, setups):
        """Resets environments envs (uint32, (K,)) to episodes (uint32, (K,))
        with new setups (SETUP, (K,)), which become theirs; atomic per
        environment. A refused entry raises DuoforgeError whose statuses are
        the K per-entry statuses; the other entries are applied."""
        if not isinstance(envs, np.ndarray) or envs.ndim != 1:
            raise TypeError("envs must be a one-dimensional ndarray of uint32")
        k = envs.shape[0]
        _require(envs, np.dtype(np.uint32), (k,), "envs")
        _require(episodes, np.dtype(np.uint32), (k,), "episodes")
        _require(setups, _layout.SETUP, (k,), "setups")
        statuses = np.zeros(k, dtype=np.uint32)
        st = self._lib.duoforge_batch_reset_setups(self._live(), k, ptr(envs), ptr(episodes), ptr(setups),
                                                   ptr(statuses))
        if st != 0 and not statuses.any():
            statuses[:] = st  # refused before any change: a duplicate or out-of-range environment
        applied = statuses == 0
        self._setups[envs[applied]] = setups[applied]
        if st != 0:
            raise DuoforgeError(status_name(st), statuses)

    def reset_terminal(self):
        """Resets every TERMINAL environment to its next episode."""
        self._check(self._lib.duoforge_batch_reset_terminal(self._live()))

    # -------------------------------------------------------- native mode

    def play_random(self, episodes, max_steps):
        """Native mode: every environment plays `episodes` further episodes
        with the uniform random policy; the records, shape (E, episodes)."""
        episodes = uint(episodes, 32, "episodes")
        records = np.zeros(self.envs * episodes, dtype=_layout.EPISODE)
        self._check(self._lib.duoforge_batch_play_random(self._live(), episodes, uint(max_steps, 32, "max_steps"),
                                                         ptr(records)))
        return records.reshape(self.envs, episodes)

    # ------------------------------------------------------- environments

    def result(self, env):
        """DUOFORGE_RESULT_* of the environment's battle, 0 before TERMINAL."""
        out = ctypes.c_uint32()
        self._check(self._lib.duoforge_battle_result(self.context.handle, self._battle(env), ctypes.byref(out)))
        return out.value

    def tiebreak(self, env):
        """DUOFORGE_RESULT_* the pinned reference's tiebreak gives the
        environment's battle as it stands (duoforge_battle_tiebreak); its own
        result at TERMINAL. DuoforgeError E_UNSUPPORTED where the reference's
        bench order would decide."""
        out = ctypes.c_uint32()
        self._check(self._lib.duoforge_battle_tiebreak(self.context.handle, self._battle(env), ctypes.byref(out)))
        return out.value

    def digest(self, env):
        """The environment's state digest (32 bytes)."""
        out = (ctypes.c_uint8 * _layout.DIGEST_SIZE)()
        self._check(self._lib.duoforge_battle_digest(self.context.handle, self._battle(env), out))
        return bytes(out)

    def encode(self, env):
        """The canonical encoding of the environment's battle (bytes,
        duoforge_battle_encode): the whole state, the hidden values and the
        RNG included. A privileged read (decision 0002), for reproduction
        data such as a search's refused leaf (decision 0022)."""
        battle = self._battle(env)
        size = ctypes.c_size_t()
        self._check(self._lib.duoforge_battle_encoded_size(self.context.handle, battle, ctypes.byref(size)))
        out = (ctypes.c_uint8 * size.value)()
        written = ctypes.c_size_t()
        self._check(self._lib.duoforge_battle_encode(self.context.handle, battle, out, size.value,
                                                     ctypes.byref(written)))
        return bytes(out[:written.value])

    def observe_ext(self, out=None):
        """The view extension of both players of every environment at the
        current boundary (OBSERVATION_EXT, (envs, 2); decision 0018): all zero
        under every kind but POOL, the epoch that of observations after
        query(); duoforge_batch_observe_ext, in the workers. out, an array of
        that dtype and shape, is filled and returned when given."""
        if out is None:
            out = np.zeros((self.envs, 2), dtype=_layout.OBSERVATION_EXT)
        else:
            _require(out, _layout.OBSERVATION_EXT, (self.envs, 2), "out")
        self._check(self._lib.duoforge_batch_observe_ext(self._live(), ptr(out)))  # its statuses are not the step's
        return out

    def query_encoded(self, version, ext_supported=0):
        """The policy inputs of every player (decision 0021): requests,
        observations and domains as query_factored() refreshes them, and in
        the same pass in the workers the encoding of duoforge_encode, which is
        byte-equal to features.encode_batch with as_encoder and
        slots_as_encoder for that version and mask. Returns (obs (envs, 2,
        obs_size) float32, slots (envs, 2, 2, 32, 12) float32, pair_mask
        (envs, 2, 32, 32) bool), arrays this batch reuses on the next call.
        An encoder refusal raises the reference's own ValueError (the refused
        environment is encoded once more by features.py); it never reads as a
        battle's failure. A failing query raises DuoforgeError as
        query_factored() does."""
        from . import features
        size = features.obs_size(version)  # ValueError for an unknown version
        ext_supported = features._mask_of(ext_supported)  # as the reference: a bool or another type is no mask
        key = ("encoded", int(version))
        if key not in self._buffers:
            self._buffers[key] = (np.zeros((self.envs, 2, size), dtype=np.float32),
                                  np.zeros((self.envs, 2, 2, _layout.MAX_SLOT_OPTIONS, features.SLOT_FEATURES),
                                           dtype=np.float32),
                                  np.zeros((self.envs, 2, _layout.MAX_SLOT_OPTIONS, _layout.MAX_SLOT_OPTIONS),
                                           dtype=np.uint8),
                                  np.zeros(self.envs, dtype=np.uint32))
        obs, slots, pairs, statuses = self._buffers[key]
        statuses[:] = 0
        st = self._lib.duoforge_batch_query_encoded(
            self._live(), uint(version, 32, "version"), uint(ext_supported, 64, "ext_supported"), ptr(self.requests),
            ptr(self.observations), ptr(self.domains), ptr(obs), ptr(slots), ptr(pairs), ptr(statuses))
        if st != 0:
            self._refused(version, ext_supported, st, statuses)
        return obs, slots, pairs.view(np.bool_)

    def expand(self, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices):
        """Search leaves (decision 0022, duoforge_batch_expand), called on the
        leaf batch. Leaf i, in environment i of this batch, is a copy of
        environment root_envs[i] of the batch `roots`, reseeded with
        search_seeds(seed, keys[root_envs[i]], samples[i]), stepped with the
        factored choices choices[i] of both players in the domains of the
        roots' last query (roots.requests and roots.domains, as
        query_factored() or query_encoded() left them) and, unless the step
        fails or the leaf is TERMINAL, its viewer viewers[root_envs[i]]
        encoded as query_encoded() encodes one row.

        keys (roots.envs,) uint64; viewers (roots.envs,) uint8 (0 or 1);
        root_envs and samples (n,) uint32; choices (n, 2) FACTORED_CHOICE;
        n at most this batch's envs. The environments from n on are not
        touched.

        Returns (obs (n, size) float32, step_statuses (n,) uint32,
        encode_statuses (n,) uint32, results (n,) STEP_RESULT, leaf_results
        (n,) uint32): views of arrays this batch reuses on the next call.
        A leaf's refusal is returned, never raised: a refused step in
        step_statuses, a refused row in encode_statuses (the search decides
        what each means, spec section 7). A refusal of the arguments before
        any leaf raises DuoforgeError and touches no leaf (the library's
        checks: the contexts, a mask past the version's features, roots being
        this batch, a root environment or a viewer out of range); an unknown
        version or an ext_supported that is no mask of the feature bits
        raises ValueError as in query_encoded(), and arrays of another dtype
        or shape raise TypeError or ValueError. The rows' width is checked
        against the library's (duoforge_encoder_size) before its first write:
        another width raises DuoforgeLibraryError."""
        from . import features
        if not isinstance(roots, Batch):
            raise TypeError(f"roots must be a Batch, not {type(roots).__name__}")
        size = features.obs_size(version)  # ValueError for an unknown version
        ext_supported = features._mask_of(ext_supported)  # as the reference: a bool or another type is no mask
        root_envs = np.asarray(root_envs)
        if root_envs.ndim != 1:
            raise ValueError(f"root_envs must be one-dimensional, not of shape {root_envs.shape}")
        n = int(root_envs.shape[0])
        if n > self.envs:
            raise ValueError(f"{n} leaves do not fit this batch of {self.envs} environments")
        _require(keys, np.uint64, (roots.envs,), "keys")
        _require(viewers, np.uint8, (roots.envs,), "viewers")
        _require(root_envs, np.uint32, (n,), "root_envs")
        _require(samples, np.uint32, (n,), "samples")
        _require(choices, _layout.FACTORED_CHOICE, (n, 2), "choices")
        key = ("expand", int(version))
        if key not in self._buffers:
            width = ctypes.c_uint32()  # the library writes rows of its own width: the buffer's must equal it
            self._check(self._lib.duoforge_encoder_size(uint(version, 32, "version"), ctypes.byref(width)))
            if width.value != size:
                raise DuoforgeLibraryError(f"encoder version {version}: the library writes rows of {width.value} "
                                           f"values, the package's are {size}")
            self._buffers[key] = (np.zeros((self.envs, size), dtype=np.float32),
                                  np.zeros(self.envs, dtype=np.uint32), np.zeros(self.envs, dtype=np.uint32),
                                  np.zeros(self.envs, dtype=_layout.STEP_RESULT), np.zeros(self.envs, dtype=np.uint32))
        obs, step_statuses, encode_statuses, results, leaf_results = self._buffers[key]
        untouched = np.uint32(0xFFFFFFFF)  # no status of the library; the argument checks write nothing
        step_statuses[:n] = untouched  # every leaf writes its step status
        st = self._lib.duoforge_batch_expand(
            self._live(), roots._live(), uint(version, 32, "version"), uint(ext_supported, 64, "ext_supported"),
            uint(seed, 64, "seed"), ptr(roots.requests), ptr(roots.domains), ptr(keys), ptr(viewers), n,
            ptr(root_envs), ptr(samples), ptr(choices), ptr(step_statuses), ptr(encode_statuses), ptr(results),
            ptr(leaf_results), ptr(obs))
        if st != 0 and (step_statuses[:n] == untouched).all():  # refused before any leaf (n may be 0)
            raise DuoforgeError(status_name(st))
        return obs[:n], step_statuses[:n], encode_statuses[:n], results[:n], leaf_results[:n]

    def _refused(self, version, ext_supported, status, statuses):
        """Raises for a failed query_encoded: the reference's ValueError for
        an encoder refusal, DuoforgeError for a failing query."""
        from . import features
        failed = np.flatnonzero(statuses)
        if failed.size == 0:  # refused before any environment: the version or the mask
            raise ValueError(f"the encoder refuses version {version} with ext_supported {int(ext_supported):#x} "
                             f"({status_name(status)})")
        self.query_factored()  # an engine failure raises here, as without the encoder
        e = int(failed[0])
        ext = self.observe_ext() if int(ext_supported) & features.RECORD_FEATURES else None
        for p in range(2):
            record = None if ext is None else ext[e, p]
            obs_part, slot_part, _ = features.encode(self.observations[e, p], self.domains[e, p], record,
                                                     ext_supported)
            features.as_encoder(obs_part, self.observations[e, p], version)
            features.slots_as_encoder(slot_part, version)
        raise RuntimeError(f"the C encoder refused environment {e} ({status_name(int(statuses[e]))}) where "
                           "features.py encodes it: the encoder and its reference disagree")

    def episode(self, env):
        """The environment's episode number."""
        return int(self._lib.duoforge_batch_env_episode(self._live(), self._env(env)))

    def close(self):
        """Destroys the batch; a second close is a no-op."""
        if self._handle is not None:
            self._lib.duoforge_batch_destroy(self._handle)
            self._handle = None
            self.context._batches.discard(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    # ----------------------------------------------------------- internals

    def _live(self):
        if self._handle is None:
            raise ValueError("the batch is closed")
        return self._handle

    def _env(self, env):
        env = int(env)
        if not 0 <= env < self.envs:
            raise IndexError(f"environment {env} is outside 0..{self.envs - 1}")
        return env

    def _battle(self, env):
        return self._lib.duoforge_batch_env(self._live(), self._env(env))

    def _check(self, status, per_env=False):
        if status != 0:
            raise DuoforgeError(status_name(status), self.statuses.copy() if per_env else None)


def search_seeds(seed, key, sample):
    """(rng_initstate, rng_initseq) of a search leaf (duoforge_search_seeds,
    decision 0022): a pure function of the search seed, the decision key
    and the sample."""
    out = [ctypes.c_uint64() for _ in range(2)]
    load_library().duoforge_search_seeds(uint(seed, 64, "seed"), uint(key, 64, "key"), uint(sample, 32, "sample"),
                                         *(ctypes.byref(v) for v in out))
    return tuple(v.value for v in out)


# ------------------------------------------------- factored domain helpers
#
# The rank of a choice in the joint list (spec section 2): for SLOTS the
# number of allowed pairs before (i, j) in row-major order, for
# TEAM_SELECTION the lexicographic rank of the ordered tuple. A bijection
# between two encodings of the engine's domain; legality stays in C.


def _falling(n, m):
    """n * (n - 1) * ... * (n - m + 1): ordered tuples of m of n indices."""
    p = 1
    for i in range(m):
        p *= n - i
    return p


def _pair_bits(domains):
    """The allowed pairs of SLOTS domains as uint8 0/1, shape (N, 32 * 32),
    in row-major (i, j) order: bit j of allowed[i] at i * 32 + j."""
    raw = np.ascontiguousarray(domains["allowed"], dtype="<u4").view(np.uint8)
    return np.unpackbits(raw, axis=-1, bitorder="little")


def _domains(domains):
    domains = np.asarray(domains)
    if domains.dtype != _layout.FACTORED_DOMAIN:
        raise TypeError(f"domains must be of FACTORED_DOMAIN, not {domains.dtype}")
    domains = domains.reshape(-1)
    if not np.isin(domains["kind"], (_SLOTS, _TEAM)).all():
        raise ValueError("only a requested player's domain (SLOTS or TEAM_SELECTION) has choices")
    return domains


def joint_counts(domains):
    """The joint domain sizes of domains (N,): allowed pairs or tuples."""
    domains = _domains(domains)
    counts = np.zeros(domains.shape[0], dtype=np.int64)
    slots = domains["kind"] == _SLOTS
    counts[slots] = np.bitwise_count(domains["allowed"][slots]).sum(axis=1)
    for row in np.flatnonzero(domains["kind"] == _TEAM):
        counts[row] = _falling(int(domains[row]["member_count"]), int(domains[row]["pick_count"]))
    return counts


def _unrank_team(n, m, k):
    """The ordered tuple of m distinct indices below n of lexicographic rank k."""
    unused = list(range(n))
    picks = []
    for i in range(m):
        digit, k = divmod(k, _falling(n - 1 - i, m - 1 - i))
        picks.append(unused.pop(digit))
    return picks


def factored_choices(domains, ks):
    """The factored choices of joint ranks ks (N,) in domains (N,)."""
    domains = _domains(domains)
    ks = np.asarray(ks)
    if ks.dtype.kind not in "iu":
        raise TypeError(f"joint indices must be integers, not {ks.dtype}")
    ks = ks.astype(np.int64).reshape(-1)
    if ks.shape != domains.shape:
        raise ValueError("one joint index per domain")
    if ((ks < 0) | (ks >= joint_counts(domains))).any():
        raise ValueError("a joint index is outside its domain")
    out = np.zeros(domains.shape[0], dtype=_layout.FACTORED_CHOICE)
    slots = np.flatnonzero(domains["kind"] == _SLOTS)
    if slots.size:
        ranks = np.cumsum(_pair_bits(domains[slots]), axis=1, dtype=np.int64)
        pos = np.argmax(ranks > ks[slots, None], axis=1)
        out["slot"][slots, 0] = pos // _OPTIONS
        out["slot"][slots, 1] = pos % _OPTIONS
    for row in np.flatnonzero(domains["kind"] == _TEAM):
        d = domains[row]
        picks = _unrank_team(int(d["member_count"]), int(d["pick_count"]), int(ks[row]))
        out["picks"][row, :len(picks)] = picks
    return out


def joint_indices(domains, choices):
    """The joint ranks of choices (N,) in domains (N,); ValueError for a
    choice outside its domain."""
    domains = _domains(domains)
    choices = np.asarray(choices)
    if choices.dtype != _layout.FACTORED_CHOICE:
        raise TypeError(f"choices must be of FACTORED_CHOICE, not {choices.dtype}")
    choices = choices.reshape(-1)
    if choices.shape != domains.shape:
        raise ValueError("one choice per domain")
    out = np.zeros(domains.shape[0], dtype=np.int64)
    slots = np.flatnonzero(domains["kind"] == _SLOTS)
    if slots.size:
        d = domains[slots]
        i = choices["slot"][slots, 0].astype(np.int64)
        j = choices["slot"][slots, 1].astype(np.int64)
        if ((i >= d["slot_count"][:, 0]) | (j >= d["slot_count"][:, 1])).any():
            raise ValueError("a slot index is past its list")
        bits = _pair_bits(d)
        at = i * _OPTIONS + j
        rows = np.arange(slots.size)
        if not bits[rows, at].all():
            raise ValueError("a pair is not allowed")
        out[slots] = np.cumsum(bits, axis=1, dtype=np.int64)[rows, at] - 1
    for row in np.flatnonzero(domains["kind"] == _TEAM):
        d, c = domains[row], choices[row]
        n, m = int(d["member_count"]), int(d["pick_count"])
        picks = [int(x) for x in c["picks"][:m]]
        if len(set(picks)) != m or any(x >= n for x in picks) or c["picks"][m:].any():
            raise ValueError("the team choice is not an ordered tuple of distinct roster indices")
        unused = list(range(n))
        rank = 0
        for pos, pick in enumerate(picks):
            rank += unused.index(pick) * _falling(n - 1 - pos, m - 1 - pos)
            unused.remove(pick)
        out[row] = rank
    return out


def factored_choice(domain, k):
    """The factored choice of joint rank k in one domain."""
    return factored_choices(np.asarray(domain).reshape(1), [k])[0]


def joint_index(domain, choice):
    """The joint rank of one factored choice in its domain."""
    return int(joint_indices(np.asarray(domain).reshape(1), np.asarray(choice).reshape(1))[0])
