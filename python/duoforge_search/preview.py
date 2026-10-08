"""Honest preview tables from reconstructed worlds only. C runs all entries/turns."""
import time

import numpy as np

import duoforge
from duoforge import _layout, view
from duoforge_learn.selfplay import TEAM_TABLE

from . import lookahead, matrix, seeds
from .errors import SearchError

C = _layout.CONSTANTS


def top(logp, count):
    logp = np.asarray(logp, np.float64)
    if logp.shape != (len(TEAM_TABLE),) or not np.isfinite(logp).all():
        raise SearchError("preview policy must give finite probabilities over the 360 team tuples")
    ids = np.argsort(-logp, kind="stable")[:count]
    return ids, np.exp(logp[ids])


def rollout(search, n, player, steps, costs):
    """Raw greedy play until the next TURN after turn 1 or TERMINAL.
    Only active leaves step; intermediate pivots/replacements are C requests.
    A bound exhaustion is an explicit whole-decision raw fallback.
    """
    batch = search.leaves
    failed = np.zeros(n, np.uint32)
    for _ in range(steps + 1):
        t = time.perf_counter()
        obs, slots, masks = batch.query_encoded(search.encoder, search.ext_supported)
        batch.query()  # the existing joint-index step consumes this public domain
        done = np.array([batch.result(e) != 0 for e in range(n)])
        at_next_turn = ((batch.requests[:n, player]["boundary_kind"] == C["DUOFORGE_BOUNDARY_TURN"]) &
                        (batch.observations[:n, player]["turn"] > 1))
        active = np.zeros(batch.envs, bool)
        active[:n] = ~done & ~at_next_turn & (failed == 0)
        costs["leaves"] += time.perf_counter() - t
        if not active.any():
            return failed, obs[:n, player].copy()
        if _ == steps:
            from .honest import Unreconstructible
            raise Unreconstructible("preview_rollout_limit")
        pp, _, seconds = search._policy(obs.reshape(2 * batch.envs, -1),
            slots.reshape((2 * batch.envs,) + slots.shape[2:]), masks.reshape((2 * batch.envs,) + masks.shape[2:]))
        costs["network"] += seconds
        pp = pp.reshape(batch.envs, 2, -1)
        indices = np.full((batch.envs, 2), _layout.NO_CHOICE, np.uint16)
        asked = active[:, None] & (batch.requests["requested"] != 0)
        legal = masks.reshape(batch.envs, 2, -1)
        if asked.any():
            if not legal[asked].any(axis=1).all() or not np.isfinite(pp[asked][legal[asked]]).all():
                raise SearchError("raw rollout needs a finite legal policy")
            # Same stable top-one choice as select(), using the existing
            # batched domain bijection instead of one lookup per leaf/seat.
            pair = np.argmax(np.where(legal[asked], pp[asked], -np.inf), axis=1)
            choice = np.zeros(len(pair), _layout.FACTORED_CHOICE)
            choice["slot"][:, 0], choice["slot"][:, 1] = np.divmod(pair, lookahead.OPTIONS)
            indices[asked] = duoforge.joint_indices(batch.domains[asked], choice)
        t = time.perf_counter()
        try:
            batch.step(indices, active=active)
        except duoforge.DuoforgeError as error:
            if error.statuses is None or ((error.statuses != 0) &
                    (error.statuses != C["DUOFORGE_E_UNSUPPORTED"])).any():
                raise
            failed[:] |= error.statuses[:n]
        costs["leaves"] += time.perf_counter() - t


def decide(search, record, observation, player, key, logp_team, excluded, last_step, costs):
    """Own top K; foe top M by mean sampled-world team probability.
    Columns keep the same roster tuple across worlds; no true foe row is read.
    """
    from .honest import reduce
    if int(record["boundary"]) != C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
        raise SearchError("preview search requires TEAM_SELECTION")
    if any(int(s["member_count"]) != 6 for s in observation["sides"]):
        raise SearchError("preview search supports only six-member teams")
    foe = 1 - player
    members = [(int(m["species_id"]), int(m["nature"]), int(m["item"])) for m in observation["sides"][foe]["members"][:6]]
    t = time.perf_counter()
    sampled = search.belief.sample(members, search.s, search.seed, key, excluded)
    hypotheses = view.hypotheses(search.s)
    for field in ("stat_points", "hp", "sleep", "confusion", "charge_target"):
        hypotheses[field] = sampled[field]
    if search._build(record, hypotheses).any():
        raise SearchError("sampled spread invalid at preview")
    costs["world_builds"] += time.perf_counter() - t
    _, team, seconds, _, obs, _slots, query_seconds = search._world_policy()
    costs["world_builds"] += query_seconds
    costs["team_head"] += seconds
    if not all(np.array_equal(obs[w, player], obs[0, player]) for w in range(search.s)):
        raise SearchError("preview own row differs across worlds")
    own, own_probs = top(logp_team, search.k)
    probabilities = np.exp(team[:, foe].astype(np.float64))
    if not np.isfinite(probabilities).all():
        raise SearchError("foe preview policy is not finite")
    mean = np.sum(sampled["weights"][:, None] * probabilities, axis=0)
    other = np.argsort(-mean, kind="stable")[:search.m]
    qs = probabilities[:, other]
    i, j, w = np.indices((len(own), len(other), search.s)).reshape(3, -1)
    total = len(w)
    choices = np.zeros((total, 2), _layout.FACTORED_CHOICE)
    choices["picks"][:, player, :4] = TEAM_TABLE[own[i]]
    choices["picks"][:, foe, :4] = TEAM_TABLE[other[j]]
    values = np.zeros(total, np.float32)
    st, enc, results, tiebreaks = (np.zeros(total, np.uint32) for _ in range(4))
    keys, viewers = np.full(search.s, key, np.uint64), np.full(search.s, player, np.uint8)
    for start in range(0, total, search.capacity):
        end = min(total, start + search.capacity)
        n = end - start
        t = time.perf_counter()
        rows, status, encoding, _, res = search.leaves.expand(search.worlds, search.encoder,
            search.ext_supported, search.seed, keys, viewers, w[start:end].astype(np.uint32),
            w[start:end].astype(np.uint32), choices[start:end])
        st[start:end], enc[start:end], results[start:end] = status, encoding, res
        rows = rows.copy()
        costs["leaves"] += time.perf_counter() - t
        if search.preview_mode == "turn1" and not last_step:
            if status.any() or encoding.any():
                from .honest import Unreconstructible
                if (status == C["DUOFORGE_E_UNSUPPORTED"]).any() and not encoding.any() and \
                        np.isin(status, [0, C["DUOFORGE_E_UNSUPPORTED"]]).all():
                    raise Unreconstructible("preview_entry_unsupported")
                raise SearchError("preview entry refused before rollout")
            failed, rows = rollout(search, n, player, search.preview_steps, costs)
            st[start:end] = failed
            results[start:end] = [search.leaves.result(e) for e in range(n)]
        if last_step:
            for e in np.flatnonzero((st[start:end] == 0) & (results[start:end] == 0)):
                try:
                    tiebreaks[start + e] = search.leaves.tiebreak(int(e))
                except duoforge.DuoforgeError as error:
                    if error.status_name != "DUOFORGE_E_UNSUPPORTED":
                        raise
                    tiebreaks[start + e] = np.uint32(0xFFFFFFFF)
        search._rows.fill(0)
        search._rows[:n] = rows
        t = time.perf_counter()
        values[start:end] = np.asarray(search.model.value(search.params, search._rows))[:n]
        costs["network"] += time.perf_counter() - t
    breaks = tiebreaks.astype(np.int64)
    breaks[breaks == 0xFFFFFFFF] = lookahead.UNRESOLVED
    table = lookahead.table(values, st, enc, results, breaks, (i, j, w), player, last_step)
    tables = table.values.transpose(2, 0, 1)
    t = time.perf_counter()
    outcomes, reduced = reduce(tables, sampled["weights"], qs, np.arange(len(own)),
        float(seeds.play_uniforms(search.seed, np.array([key], np.uint64))[0]), search.lam)
    costs["solve"] += time.perf_counter() - t
    chosen = int(own[outcomes[search.rule]])
    gap = matrix.bayes_certify(tables, sampled["weights"], np.array(reduced["x"]),
                              [np.array(y) for y in reduced["ys"]])
    search.last.append({"tables": tables.copy(), "hypotheses": hypotheses.copy(), "choices": choices.copy()})
    return {"kind": "searched", "rule": search.rule, "k": len(own), "m": len(other), "s": search.s,
        "preview_eval": search.preview_mode, "rollout_steps_limit": search.preview_steps,
        "own_teams": own.tolist(), "foe_teams": other.tolist(), "own_probs": own_probs.tolist(),
        "foe_probs": qs.tolist(), "weights": sampled["weights"].tolist(), "coverage": float(qs.mean(axis=0).sum()),
        "table": table.a.tolist(), "tables": tables.tolist(), "stderr": table.stderr.tolist(),
        "choice": chosen, "raw": int(own[0]), "changed": chosen != int(own[0]),
        "outcomes": outcomes, "leaves": table.counts, "near_duplicates": lookahead.near_duplicates(table.a),
        "split": None, "certificate_gap": gap, **reduced}
