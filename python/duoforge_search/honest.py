"""Visible-information lookahead (D0023). Only C builds and checks worlds.

The actual root supplies the deciding player's public record and row. Foe
rows are evaluated exclusively in reconstructed worlds. No privileged call
or true-root encoding is used, even for error reproduction.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import time
import weakref

import numpy as np

import duoforge
from duoforge import _layout, data, teams, view
from duoforge_learn.selfplay import TEAM_TABLE

from . import belief, lookahead, matrix, seeds
from .errors import SearchError

C = _layout.CONSTANTS
RULES = lookahead.RULES
MAX_RESPREADS = 256
# The stated-spread teams of the belief (decision 0023): A/B/C and the PP_ teams of the D0023 pool, pinned on
# 2026-10-09 (79 sources, 444 sets, table sha256 1795524c...). New registry teams never widen it silently;
# a wider belief is an owner decision with a new list.
SPREAD_SOURCES = ("A", "B", "C", "PP_0071E895C381DD1C", "PP_097433EFCC505367", "PP_0A93AE91073CC690",
                  "PP_102E046831526921", "PP_1B067B3C97217EAF", "PP_1E6A03DC1764214E", "PP_1F4DA9800A6AD851",
                  "PP_202C514602D9ABE9", "PP_246AECB752FACC29", "PP_24B7E1E280B1088F", "PP_25161F401C0A2005",
                  "PP_297320B831FB73B8", "PP_2C4D3FBB866C4D2C", "PP_2D234B4EC11A9ACA", "PP_2F25D07C9B26E73C",
                  "PP_369E75B64155B6A1", "PP_37083BBE99A1BF42", "PP_3C4611CCBA18D35A", "PP_3E44CC0D5FBA21F8",
                  "PP_470A6EC2468AF8A4", "PP_4BFCE88CE42A966A", "PP_4C6EB1D0D2CBB3F3", "PP_4FCE711199944AE0",
                  "PP_56F0A0120CD736E5", "PP_56F517BBD665899F", "PP_58C15A8BD78B30AB", "PP_5B9FAE64B204F805",
                  "PP_5CEDF6DD944DB220", "PP_5D8E24080B6D3200", "PP_62AA4EF34EE42F01", "PP_674AC2A18201012A",
                  "PP_6853674468737B2E", "PP_6F1B0E8DF51CC57D", "PP_6F1D5B2B15285F2B", "PP_7C9C0663EF60180E",
                  "PP_7F7E07BF0F953B0A", "PP_8025F0AEF5F2D1B6", "PP_81D3F0FFE6EF750C", "PP_8536A2B4F89D3E72",
                  "PP_8606ABBA447D2E2E", "PP_89FAA497014B5641", "PP_8E37C3B00CBBA6B6", "PP_8F4C2600A4A63A90",
                  "PP_90F7CCC7AB5B3D0B", "PP_9F21D2E809A9F09D", "PP_9FED7BFC061AD8BB", "PP_A0582A49F5490809",
                  "PP_A5DFCE8794A63B55", "PP_A702BF47F522438B", "PP_A8154C05ECFA0E20", "PP_A982BEAEE27D32EC",
                  "PP_B80C5F3E363597C2", "PP_BB66FF17A1C4A911", "PP_BED443F8A0ACBE11", "PP_BFE773D9CDA8999C",
                  "PP_C8F60C5168BD6A83", "PP_D3277B02C40781F3", "PP_D3A1849223A946F8", "PP_D668DD98C6C7177B",
                  "PP_D6B2F01DDF4FEE52", "PP_D7C70DFF2BD9F5CF", "PP_D828BB9033A964A0", "PP_D943321333ED8846",
                  "PP_DBC606408D738253", "PP_DDCF443E371A3A19", "PP_DEB9DAC3FF5777D5", "PP_E01AD4BAD0DA9CCC",
                  "PP_E2B7674A54DEBEE7", "PP_E4AA1030C5E684B4", "PP_ECDECC58B9116D68", "PP_EE7A2C6A9F775208",
                  "PP_EEDF279FBC3AD845", "PP_F85133BAC58B317F", "PP_F853DAF986849F1D", "PP_FC5A33ABDD155CA3",
                  "PP_FD6FE5BB94A024FB")


@dataclass(frozen=True)
class LeafRequest:
    """A prepared decision (Honest._prepare): its seat, key, own candidates,
    cut-off flag, world weights, foe pairs and probabilities, the leaves'
    choices and (i, j, w) plan, their copied rows (L, width) float32, step/
    encode/result statuses and tiebreaks, and which leaves the table reads a
    value of (open)."""
    p: int
    key: int
    own: np.ndarray
    last_step: bool
    weights: np.ndarray
    foe_pairs: np.ndarray
    qs: np.ndarray
    choices: np.ndarray
    plan: tuple
    rows: np.ndarray
    step: np.ndarray
    encode: np.ndarray
    results: np.ndarray
    tiebreaks: np.ndarray
    open: np.ndarray


class Unreconstructible(Exception):
    """An explicitly counted absence of a supported public reconstruction."""


def spread_table(ctx, root=None, sources=SPREAD_SOURCES):
    """Read the pinned A/B/C and PP_ stated spreads, never LL_ importer guesses
    (sources=None: every A/B/C and PP_ team of an explicitly chosen root).

    Sets absent from the context's tables cannot occur there; count those
    exclusions. Source ids, counts and hashes are saved beside the table hash.
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2] / "data/teams"
    registry = {r["id"]: r for r in json.loads((root / "index.json").read_text(encoding="utf-8"))["teams"]}
    if sources is None:  # an explicitly chosen registry: all of its stated A/B/C and PP_ teams
        sources = [x for x in registry if x in ("A", "B", "C") or x.startswith("PP_")]
    missing = [x for x in sources if x not in registry]
    if missing:
        raise SearchError(f"pinned spread sources missing from the registry: {missing}")
    sources = [registry[x] for x in sorted(sources)]
    cols = ([], [], [], [], [])
    counts = {"sets": 0, "unstated": 0, "outside_context": 0}
    for t, source in enumerate(sources):
        raw = (root / (source["id"] + ".txt")).read_bytes()
        if teams.text_sha256(raw) != source["sha256"]:
            raise SearchError(f"spread source {source['id']} differs from the registry hash")
        for member in teams.parse(raw.decode("utf-8"), source["id"]):
            sp = member["stat_points"]
            if not any(sp):
                counts["unstated"] += 1
                continue
            try:
                species = data.find(ctx, data.TABLE_SPECIES, data.to_id(member["species"]))
                nature = data.find(ctx, data.TABLE_NATURE, data.to_id(member["nature"]))
                item = 0 if member["item"] is None else 1 + data.find(ctx, data.TABLE_ITEM, data.to_id(member["item"]))
            except duoforge.DuoforgeError as err:
                if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                    raise
                counts["outside_context"] += 1
                continue
            for col, value in zip(cols, (t, species, nature, item, sp)):
                col.append(value)
            counts["sets"] += 1
    table = belief.SpreadTable(*cols)
    return table, {s["id"]: i for i, s in enumerate(sources)}, {**counts, "sources": sources, "sha256": table.sha256()}


_CAUSES = ((C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP"], "visible_sleep"),
           (C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION"], "visible_confusion"),
           (C["DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE"], "illusion_possible"),
           (C["DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE"], "substitute"),  # decision 0032 (step G60)
           (C["DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN"], "raised_this_turn"))  # step G72: Alluring Voice at a PIVOT


def visible_causes(roots, env, player):
    """The causes (names) of environment env's public refusal for player, from the library's own predicate
    (duoforge_batch_public_causes, decision 0026 section 4): a visible sleep or confusion, a possible Illusion, a
    Substitute on either side (decision 0032: its HP is no public fact). The library decides them from the player's
    view, so no rule is restated here; an empty list is another refusal."""
    players = np.zeros(roots.envs, dtype=np.uint32)
    players[env] = player
    masks, statuses = roots.public_causes(players)
    if statuses[env] != 0:
        raise SearchError(f"public causes refused: {duoforge.status_name(int(statuses[env]))}")
    mask = int(masks[env])
    return [name for bit, name in _CAUSES if mask & bit]


def draw_word(probabilities, word):
    """Network categorical draw, in index order, by its separate world word."""
    try:
        return belief.draw_index(probabilities, word)
    except ValueError as err:
        raise SearchError("no probability remains after public-fact filtering") from err


def reduce(tables, weights, qs, prior_rank, uniform, lam, oracle=False, budget=None):
    """One strategy for all worlds, with every N/E/X outcome recorded.
    budget: an optional matrix.WorkLedger for the solve (P1 teacher)."""
    # Without a budget the solvers are called exactly as before the teacher existed.
    extra = {} if budget is None else {"budget": budget}
    if oracle:
        single = matrix.solve(tables[0], **extra)
        sol = matrix.BayesSolution(single.x, [single.y], single.value, single.exact)
    else:
        sol = matrix.solve_bayes(tables, weights, **extra)
    # A float basis can leave roundoff at a pure vertex (e.g. 1e-16 on
    # another row). Canonicalize only within four float64 ulps of a vertex,
    # and only if the candidate still satisfies the unchanged certificate.
    def vertex(strategy):
        best = int(np.argmax(strategy))
        if 1.0 - float(strategy[best]) > 4 * np.finfo(np.float64).eps:
            return strategy
        candidate = np.zeros_like(strategy)
        candidate[best] = 1.0
        return candidate

    x, ys = vertex(sol.x), [vertex(y) for y in sol.ys]
    try:
        matrix.bayes_certify(tables, weights, x, ys)
    except SearchError:
        pass  # retain the original certified solution; do not approximate it
    else:
        sol = matrix.BayesSolution(x, ys, sol.value, sol.exact)
    expected = matrix.bayes_expected_values(tables, weights, qs)
    best = np.flatnonzero(expected == expected.max())
    ev = int(best[np.argmin(np.asarray(prior_rank)[best])])
    mixed = matrix.mix(sol.x, ev, lam)
    return {"nash": matrix.draw(sol.x, prior_rank, uniform), "ev": ev,
            "mix": matrix.draw(mixed, prior_rank, uniform)}, {
                "x": sol.x.tolist(), "ys": [y.tolist() for y in sol.ys], "value": sol.value,
                "exact": sol.exact, "expected": expected.tolist(), "pi_X": mixed.tolist(),
                "u": uniform, "lam": lam,
                "support": [int((sol.x >= matrix.PROBABILITY_FLOOR).sum()),
                            int(sum((y >= matrix.PROBABILITY_FLOOR).sum() for y in sol.ys))]}


class Honest(lookahead.Lookahead):
    def __init__(self, context, model, params, encoder, ext_supported, k=8, m=8, s=16, rule="mix",
                 seed=lookahead.SEARCH_SEED, capacity=lookahead.CAPACITY, workers=8, lam=0.5,
                 table=None, exclude_teams=None, preview_mode="raw", preview_only=False, preview_steps=16):
        if rule not in RULES or not 0 <= lam <= 1:
            raise ValueError("honest search needs nash/ev/mix and 0 <= lam <= 1")
        if preview_mode not in ("raw", "value", "turn1") or type(preview_steps) is not int or preview_steps < 1:
            raise ValueError("preview requires raw/value/turn1 and a positive rollout bound")
        if preview_only and preview_mode == "raw":
            raise ValueError("preview_only requires preview search")
        self.preview_mode, self.preview_only, self.preview_steps = preview_mode, preview_only, preview_steps
        if table is None:
            table, _, self.table_info = spread_table(context)
        else:
            self.table_info = {"sha256": table.sha256(), "sets": len(table.team)}
        self.belief = belief.Belief(table)
        self.lam = float(lam)
        self.exclude_teams = exclude_teams
        self.history = weakref.WeakKeyDictionary()
        self.worlds = None
        super().__init__(context, model, params, encoder, ext_supported, k, m, s, "nash", seed, capacity, workers, lam=lam)
        self.rule = rule
        try:
            self.worlds = duoforge.Batch(context, np.resize(duoforge.reference_setups([0]), self.s), workers, seed)
        except BaseException:
            super().close()
            raise

    def close(self):
        if self.worlds is not None:
            self.worlds.close()
        super().close()

    def clear(self):
        self.history.clear()

    def _policy(self, obs, slots, pairs):
        inputs = (np.ascontiguousarray(obs), np.ascontiguousarray(slots), np.ascontiguousarray(pairs))
        self.model.check(inputs[0])
        shape = tuple(x.shape for x in inputs)
        if shape not in self._compiled:
            np.asarray(self.model.apply(self.params, *inputs)[0])
            self._compiled.add(shape)
        t = time.perf_counter()
        pair, team, _ = self.model.apply(self.params, *inputs)
        return np.asarray(pair), np.asarray(team), time.perf_counter() - t

    def _build(self, record, hypotheses):
        statuses = self.worlds.from_view(np.repeat(record.reshape(1), self.s), hypotheses).copy()
        if (statuses == C["DUOFORGE_E_UNSUPPORTED"]).any():
            raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: world build")
        bad = np.flatnonzero((statuses != 0) & (statuses != C["DUOFORGE_E_INVALID_ARGUMENT"]))
        if bad.size:
            raise SearchError(f"world {bad[0]} refused: {duoforge.status_name(int(statuses[bad[0]]))}")
        return statuses

    def _world_policy(self):
        start = time.perf_counter()
        obs, slots, pairs = self.worlds.query_encoded(self.encoder, self.ext_supported)
        query_seconds = time.perf_counter() - start
        pp, pt, seconds = self._policy(obs.reshape(2 * self.s, -1), slots.reshape((2 * self.s,) + slots.shape[2:]),
                                       pairs.reshape((2 * self.s,) + pairs.shape[2:]))
        return (pp.reshape(self.s, 2, -1), pt.reshape(self.s, 2, -1), seconds,
                pairs.copy(), obs.copy(), slots.copy(), query_seconds)

    def _hypotheses(self, record, observation, history, key, excluded, costs):
        if "preview" not in history:
            raise Unreconstructible("missing team-preview record")
        foe = 1 - int(record["player"])
        side = observation["sides"][foe]
        members = [(int(m["species_id"]), int(m["nature"]), int(m["item"]))
                   for m in side["members"][:int(side["member_count"])]]
        attempts = np.zeros((self.s, 6), np.int64)
        dropped = respreads = 0
        queue_mask = None
        if int(record["boundary"]) == C["DUOFORGE_BOUNDARY_PIVOT"]:
            start = history.get("turn_start")
            if start is None or int(start["turn"]) != int(record["turn"]) or int(start["player"]) != int(record["player"]):
                raise Unreconstructible("missing or stale turn-start record")
            t = time.perf_counter()
            try:
                queue_mask = duoforge.queue_mask(self.worlds.context, history["turn_start"], record)
            except duoforge.DuoforgeError as err:
                if err.status_name == "DUOFORGE_E_UNSUPPORTED":
                    raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: queue mask") from err
                raise
            finally:
                costs["public_records"] += time.perf_counter() - t
        for _ in range(MAX_RESPREADS):
            t = time.perf_counter()
            sampled = self.belief.sample(members, self.s, self.seed, key, excluded, attempts)
            weights = sampled["weights"]
            h = view.hypotheses(self.s)
            for name in ("stat_points", "hp", "sleep", "confusion", "charge_target"):
                h[name] = sampled[name]
            if self._build(history["preview"], h).any():
                raise SearchError("a sampled spread is invalid at team preview")
            costs["world_builds"] += time.perf_counter() - t
            _, team, elapsed, _, _, _, query_seconds = self._world_policy()
            costs["world_builds"] += query_seconds
            costs["team_head"] += elapsed
            keep = np.all(TEAM_TABLE[:, :2] == record["foe_leads"], axis=1)
            for m in range(6):
                if int(record["foe_seen_mask"]) & (1 << m):
                    keep &= (TEAM_TABLE == m).any(axis=1)
            dropped = int((~keep).sum()) * self.s
            for w in range(self.s):
                probs = np.exp(team[w, foe].astype(np.float64)) * keep
                h[w]["pick_order"][:TEAM_TABLE.shape[1]] = TEAM_TABLE[draw_word(probs, sampled["bench"][w])]
            queue_pairs = []
            if queue_mask is not None:
                t = time.perf_counter()
                st = self._build(history["turn_start"], h)
                costs["world_builds"] += time.perf_counter() - t
                if st.any():
                    attempts[st != 0] += 1
                    respreads += int((st != 0).sum())
                    continue
                pp, _, elapsed, legal, _, _, query_seconds = self._world_policy()
                costs["world_builds"] += query_seconds
                costs["network"] += elapsed
                for w in range(self.s):
                    probs = np.exp(pp[w, foe].astype(np.float64)) * queue_mask.reshape(-1) * legal[w, foe].reshape(-1)
                    pair = draw_word(probs, sampled["queue"][w])
                    queue_pairs.append(pair)
                    indices = divmod(pair, lookahead.OPTIONS)
                    for p in range(2):
                        if int(record["foe_pending_mask"]) & (1 << p):
                            h[w]["queued"][p] = self.worlds.domains[w, foe]["slots"][p, indices[p]]
                    h[w]["queue_order"][:int(record["queue_count"])] = np.arange(int(record["queue_count"]), dtype=np.uint8)
            t = time.perf_counter()
            statuses = self._build(record, h)
            costs["world_builds"] += time.perf_counter() - t
            if not statuses.any():
                return h, weights, dropped, respreads, queue_pairs
            # The current C API reports a failed world, not the member. Redraw
            # all its spreads; keep its HP/counter/bench/queue words unchanged.
            attempts[statuses != 0] += 1
            respreads += int((statuses != 0).sum())
        raise SearchError(f"a world still contradicts the public view after {MAX_RESPREADS} spread draws")

    def decide(self, roots, envs, seats, keys, last_step):
        envs, seats = np.asarray(envs, np.int64), np.asarray(seats, np.int64)
        keys, last_step = np.asarray(keys, np.uint64), np.asarray(last_step, bool)
        n = envs.size
        if any(x.shape != (n,) for x in (envs, seats, keys, last_step)) or len(set(envs.tolist())) != n or \
                (envs < 0).any() or (envs >= roots.envs).any() or not np.isin(seats, [0, 1]).all():
            raise ValueError("decisions need unique valid environments and one seat/key/last-step flag each")
        if not n:
            return np.zeros(0, np.int64), []
        t = time.perf_counter()
        obs, slots, pairs = roots.query_encoded(self.encoder, self.ext_supported)
        players = np.zeros(roots.envs, np.uint32)
        players[envs] = seats
        records, statuses = roots.public(players)
        public_time = (time.perf_counter() - t) / n
        # The network sees only the viewer's rows of the real root.
        pp, pt, network_time = self._policy(obs[envs, seats], slots[envs, seats], pairs[envs, seats])
        actions, output = np.zeros(n, np.int64), []
        self.last = []
        for d, (e, p) in enumerate(zip(envs, seats)):
            e, p = int(e), int(p)
            record = records[e:e + 1].reshape(()).copy()
            history = self._observe(roots, e, p, record, statuses[e])
            boundary = int(roots.requests[e, p]["boundary_kind"])
            costs = {k: 0.0 for k in ("public_records", "world_builds", "team_head", "leaves", "network", "solve")}
            costs["public_records"], costs["network"] = public_time, network_time / n
            base = {"env": e, "seat": p, "key": int(keys[d]), "epoch": int(roots.requests[e, p]["epoch"]),
                    "boundary": lookahead._BOUNDARIES[boundary], "last_step": bool(last_step[d]),
                    "search": "honest", "w": self.s, "table_sha256": self.table_info["sha256"], "lam": self.lam}
            if boundary == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                actions[d] = int(np.argmax(pt[d]))
                result = {"kind": "team", "choice": int(actions[d])}
                if self.preview_mode != "raw" and self.k != 1:
                    excluded = None if self.exclude_teams is None else self.exclude_teams[e]
                    try:
                        if statuses[e] == C["DUOFORGE_E_UNSUPPORTED"]:
                            raise Unreconstructible("preview_public_record_unsupported")
                        if statuses[e] != 0:
                            raise SearchError(f"preview public record refused: {duoforge.status_name(int(statuses[e]))}")
                        from . import preview
                        result = preview.decide(self, record, roots.observations[e, p], p, int(keys[d]),
                                                pt[d], excluded, bool(last_step[d]), costs)
                        actions[d] = result["choice"]
                    except Unreconstructible as error:
                        result.update(kind="unreconstructible", reason=str(error), causes=[str(error)])
                    except (SearchError, duoforge.DuoforgeError, ValueError) as error:
                        stop = SearchError(str(error))
                        stop.reproduction = {**base, "public_view": record.tobytes().hex() if statuses[e] == 0 else None}
                        raise stop from error
            else:
                own, own_p = lookahead.select(pp[d], pairs[e, p], self.k)
                actions[d] = int(own[0])
                result = {"kind": "forced" if pairs[e, p].sum() == 1 else "raw", "choice": int(actions[d])}
                excluded = None if self.exclude_teams is None else self.exclude_teams[e]
                if result["kind"] != "forced" and self.k != 1 and not self.preview_only:
                    try:
                        if statuses[e] == C["DUOFORGE_E_UNSUPPORTED"]:
                            result["causes"] = visible_causes(roots, e, p) or ["public_record_unsupported"]
                            raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: public record")
                        if statuses[e] != 0:
                            raise SearchError(f"public record refused: {duoforge.status_name(int(statuses[e]))}")
                        hypotheses, weights, dropped, respreads, queue_pairs = self._hypotheses(record, roots.observations[e, p], history,
                                                                         int(keys[d]), excluded, costs)
                        result = self._decision(p, int(keys[d]), own, own_p, weights, bool(last_step[d]), costs)
                        self.last[-1]["hypotheses"] = hypotheses.copy()
                        result.update({"bench_dropped": dropped, "respreads": respreads, "exclude_team": excluded,
                                       "queue_pairs": queue_pairs})
                        actions[d] = result["choice"]
                    except Unreconstructible as err:
                        result.update({"kind": "unreconstructible", "reason": str(err)})
                        result.setdefault("causes", [str(err)])
                    except (SearchError, duoforge.DuoforgeError, ValueError) as err:
                        stop = SearchError(str(err))
                        stop.reproduction = {**getattr(err, "reproduction", {}), **base,
                                             "public_view": record.tobytes().hex() if statuses[e] == 0 else None,
                                             "search_seed": self.seed, "exclude_team": excluded,
                                             "preview": history["preview"].tobytes().hex() if "preview" in history else None,
                                             "turn_start": history["turn_start"].tobytes().hex() if "turn_start" in history else None}
                        raise stop from err
            output.append({**base, **result, "cost": costs,
                           "time": {"network": costs["network"] + costs["team_head"],
                                    "engine": costs["public_records"] + costs["world_builds"] + costs["leaves"],
                                    "reduction": costs["solve"], "split": 0.0}})
        return actions, output

    def _observe(self, roots, e, p, record, status):
        """The public history of seat p in environment e (team preview,
        turn start), updated from its current request; returns it."""
        if roots.requests[e, p]["requested"] == 0:
            raise ValueError(f"seat {p} of environment {e} has no request")
        histories = self.history.setdefault(roots, {})
        episode = roots.episode(e)
        history = histories.setdefault((e, p), {})
        if history.get("episode") != episode:
            history.clear()
            history["episode"] = episode
        boundary = int(roots.requests[e, p]["boundary_kind"])
        current_turn = int(roots.observations[e, p]["turn"])
        start = history.get("turn_start")
        if start is not None and int(start["turn"]) != current_turn:
            history.pop("turn_start")
        if boundary == C["DUOFORGE_BOUNDARY_TURN"] and roots.requests[e, 0]["requested"] and roots.requests[e, 1]["requested"]:
            history.pop("turn_start", None)
        if status == 0:
            if boundary == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                history["preview"] = record.copy()
            if boundary == C["DUOFORGE_BOUNDARY_TURN"] and int(record["request_mask"]) == 3:
                history["turn_start"] = record.copy()
        return history

    def _decision(self, p, key, own, own_p, weights, last_step, costs, budget=None):
        request = self._prepare(p, key, own, weights, last_step, costs)
        return self._finish(request, self._values(request, costs), own_p, costs, budget)

    def _prepare(self, p, key, own, weights, last_step, costs):
        """Phase one of a decision on the current worlds: the worlds' policy,
        the foe's pairs and every expand chunk with its tiebreaks. The rows
        and statuses are copied out, so later roots may reuse the worlds and
        the leaf batch before this request is finished (stage 3 P2)."""
        pp, _, elapsed, masks, obs, slots, query_seconds = self._world_policy()
        costs["world_builds"] += query_seconds
        costs["network"] += elapsed
        for w in range(1, self.s):
            if not np.array_equal(obs[w, p], obs[0, p]) or not np.array_equal(slots[w, p], slots[0, p]) or \
                    not np.array_equal(masks[w, p], masks[0, p]):
                raise SearchError("the viewer's encoded row differs across worlds")
        foe = 1 - p
        if self.worlds.requests[0, foe]["requested"]:
            probabilities = np.exp(pp[:, foe].astype(np.float64))
            mean = np.sum(weights[:, None] * probabilities, axis=0)
            order = np.lexsort((np.arange(mean.size), -mean))
            # Switch options can name different hidden bench members in each
            # world. Filter the common probability ranking through C's mask
            # per world; each column is that world's legal best response.
            ranked = [order[masks[w, foe].reshape(-1)[order] != 0][:self.m] for w in range(self.s)]
            m = min(len(x) for x in ranked)
            if not m:
                raise SearchError("a requested foe has no legal pair")
            foe_pairs = np.array([x[:m] for x in ranked])
            qs = np.take_along_axis(probabilities, foe_pairs, axis=1)
        else:
            foe_pairs, qs = np.full((self.s, 1), lookahead.NO_FOE, np.int64), np.ones((self.s, 1))
        i, j, w = np.indices((own.size, foe_pairs.shape[1], self.s)).reshape(3, -1)
        total = w.size
        choices = np.zeros((total, 2), _layout.FACTORED_CHOICE)
        choices["slot"][:, p, 0], choices["slot"][:, p, 1] = np.divmod(own[i], lookahead.OPTIONS)
        other = foe_pairs[w, j]
        asked = other != lookahead.NO_FOE
        choices["slot"][asked, foe, 0], choices["slot"][asked, foe, 1] = np.divmod(other[asked], lookahead.OPTIONS)
        rows = np.zeros((total, self._rows.shape[1]), np.float32)
        step, encode, results, tiebreaks = (np.zeros(total, np.uint32) for _ in range(4))
        root_keys, viewers = np.full(self.s, key, np.uint64), np.full(self.s, p, np.uint8)
        for start in range(0, total, self.capacity):
            end = min(total, start + self.capacity)
            t = time.perf_counter()
            row, st, enc, _, res = self.leaves.expand(self.worlds, self.encoder, self.ext_supported, self.seed,
                                                      root_keys, viewers, w[start:end].astype(np.uint32),
                                                      w[start:end].astype(np.uint32), choices[start:end])
            step[start:end], encode[start:end], results[start:end] = st, enc, res
            rows[start:end] = row
            if last_step:
                for x in np.flatnonzero((st == 0) & (res == 0)):
                    try:
                        tiebreaks[start + x] = self.leaves.tiebreak(int(x))
                    except duoforge.DuoforgeError as err:
                        if err.status_name != "DUOFORGE_E_UNSUPPORTED":
                            raise
                        tiebreaks[start + x] = np.uint32(0xFFFFFFFF)
            costs["leaves"] += time.perf_counter() - t
        # The table reads a value only where the step ran, the leaf is not terminal and not cut off.
        open_ = (step == 0) & (results == 0) & (not last_step)
        return LeafRequest(p, key, own.copy(), bool(last_step), np.array(weights, copy=True), foe_pairs, qs, choices,
                           (i, j, w), rows, step, encode, results, tiebreaks, open_)

    def _values(self, request, costs):
        """Today's per-root value calls: the request's rows in capacity
        chunks through the preallocated row buffer, padded with zeros."""
        total = request.rows.shape[0]
        values = np.zeros(total, np.float32)
        for start in range(0, total, self.capacity):
            end = min(total, start + self.capacity)
            self._rows.fill(0)
            self._rows[:end - start] = request.rows[start:end]
            t = time.perf_counter()
            values[start:end] = np.asarray(self.model.value(self.params, self._rows))[:end - start]
            costs["network"] += time.perf_counter() - t
        return values

    def _finish(self, request, values, own_p, costs, budget=None):
        """Phase two: the table from the request's leaves and their values
        (float32; non-open leaves are never read: a SearchError reproduction
        records them as given), the reduction and the decision record."""
        values = np.asarray(values)
        if values.shape != request.step.shape or values.dtype != np.float32:
            raise ValueError("a request needs one float32 value per leaf")
        p, key, own, weights, qs = request.p, request.key, request.own, request.weights, request.qs
        i, j, w = request.plan
        t = time.perf_counter()
        breaks = request.tiebreaks.astype(np.int64)
        breaks[breaks == 0xFFFFFFFF] = lookahead.UNRESOLVED
        try:
            tab = lookahead.table(values, request.step, request.encode, request.results, breaks, (i, j, w), p,
                                  request.last_step)
        except SearchError as err:
            err.reproduction = {"values": values.tolist(), "step_statuses": request.step.tolist(),
                                "encode_statuses": request.encode.tolist(), "samples": w.tolist(),
                                "choices": request.choices.tobytes().hex()}
            raise
        tables = tab.values.transpose(2, 0, 1)
        rank = np.arange(own.size)
        try:
            outcomes, reduced = reduce(tables, weights, qs, rank,
                                       float(seeds.play_uniforms(self.seed, np.array([key], np.uint64))[0]), self.lam,
                                       budget=budget)
        except SearchError as err:
            err.reproduction = {"tables": tables.tolist(), "weights": weights.tolist(), "foe_probs": qs.tolist()}
            raise
        costs["solve"] += time.perf_counter() - t
        self.last.append({"tables": tables.copy(), "choices": request.choices.copy(),
                          "samples": w.copy(), "values": tab.values.copy()})
        foe_pairs = request.foe_pairs
        action = int(own[outcomes[self.rule]])
        return {"kind": "searched", "rule": self.rule, "k": own.size, "m": foe_pairs.shape[1], "s": self.s,
                "own_pairs": own.tolist(), "own_probs": own_p.tolist(), "foe_pairs": foe_pairs.tolist(),
                "foe_probs": qs.tolist(), "weights": weights.tolist(), "coverage": float(np.sum(weights * qs.sum(axis=1))),
                "table": tab.a.tolist(), "tables": tables.tolist(), "stderr": tab.stderr.tolist(),
                "choice": action, "raw": int(own[0]), "changed": action != int(own[0]), "outcomes": outcomes,
                "leaves": tab.counts, "near_duplicates": lookahead.near_duplicates(tab.a), "split": None, **reduced}
