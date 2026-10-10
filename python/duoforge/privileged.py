"""Privileged true-state helpers for tests and the oracle, never an honest player."""
import ctypes

import numpy as np

from . import _layout
from ._lib import ptr, status_name, uint
from .errors import DuoforgeError

C = _layout.CONSTANTS


class _EventBuffer(ctypes.Structure):  # duoforge_event_buffer
    _fields_ = [("events", ctypes.c_void_p), ("capacity", ctypes.c_uint32), ("count", ctypes.c_uint32)]


def hypothesis(batch, env, player):
    """The true hypothesis of one batch environment (PRIVILEGED)."""
    out = np.zeros((), _layout.HYPOTHESIS)
    st = batch._lib.duoforge_battle_hypothesis(batch.context.handle, batch._battle(env),
                                               uint(player, 32, "player"), ptr(out))
    if st:
        raise DuoforgeError(status_name(st))
    return out


def _bundle(batch, env, choice):
    """The decision bundle the batch builds from a factored choice (FACTORED_CHOICE, both sides) in its last query's
    requests and domains (dfi_factored_bundle): a requested side's slot commands, or its picks."""
    bundle = np.zeros((), _layout.DECISION_BUNDLE)
    bundle["epoch"] = batch.requests[env, 0]["epoch"]
    mask = 0
    for p in (0, 1):
        if batch.requests[env, p]["requested"] == 0:
            continue
        d, c, out = batch.domains[env, p], choice[p], bundle["responses"][p]
        out["epoch"], out["side"], out["kind"] = d["epoch"], p, d["kind"]
        if int(d["kind"]) == C["DUOFORGE_CHOICE_TEAM_SELECTION"]:
            out["pick_count"] = d["pick_count"]
            out["picks"] = c["picks"]
        else:
            i, k = int(c["slot"][0]), int(c["slot"][1])
            if int(d["kind"]) != C["DUOFORGE_CHOICE_SLOTS"] or i >= int(d["slot_count"][0]) or \
                    k >= int(d["slot_count"][1]) or not (int(d["allowed"][i]) >> k) & 1:
                raise ValueError(f"side {p}'s pair ({i}, {k}) is not in the domain of its request")
            out["slots"][0], out["slots"][1] = d["slots"][0, i], d["slots"][1, k]
        mask |= 1 << p
    bundle["response_mask"] = mask
    return bundle


def step_events(batch, env, choice, rng=None):
    """The step of batch environment env by its factored choice (FACTORED_CHOICE (2,), as step_factored takes it, in
    the last query's domains) on a copy of its battle, reseeded with rng = (initstate, initseq) when given
    (PRIVILEGED: the oracle and the test positions). Returns {"status", "result" (STEP_RESULT), "events" (one EVENT
    array per player, as each sees the step), "digest" (the copy's digest after the step), "battle_result" (0 before
    TERMINAL, else DUOFORGE_RESULT_*)}. The environment itself is never changed; a pair outside the domain is
    ValueError."""
    lib, ctx = batch._lib, batch.context.handle
    bundle = _bundle(batch, env, np.asarray(choice))
    copy = ctypes.c_void_p()
    st = lib.duoforge_battle_clone(ctx, batch._battle(env), ctypes.byref(copy))
    if st:
        raise DuoforgeError(status_name(st))
    try:
        if rng is not None:
            st = lib.duoforge_battle_reseed(ctx, copy, uint(rng[0], 64, "rng initstate"), uint(rng[1], 64, "rng initseq"))
            if st:
                raise DuoforgeError(status_name(st))
        events = [np.zeros(C["DUOFORGE_MAX_EVENTS"], _layout.EVENT) for _ in range(2)]
        buffers = (_EventBuffer * 2)(*(_EventBuffer(e.ctypes.data, len(e), 0) for e in events))
        result = np.zeros((), _layout.STEP_RESULT)
        status = lib.duoforge_battle_step_events(ctx, copy, ptr(bundle), ptr(result), buffers)
        digest = np.zeros(_layout.DIGEST_SIZE, np.uint8)
        ended = ctypes.c_uint32(0)
        if status == 0:
            for st in (lib.duoforge_battle_digest(ctx, copy, ptr(digest)),
                       lib.duoforge_battle_result(ctx, copy, ctypes.byref(ended))):
                if st:
                    raise DuoforgeError(status_name(st))
        return {"status": int(status), "result": result,
                "events": [events[p][:buffers[p].count].copy() for p in (0, 1)] if status == 0 else [None, None],
                "digest": digest, "battle_result": int(ended.value)}
    finally:
        lib.duoforge_battle_destroy(copy)
