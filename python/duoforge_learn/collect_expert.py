"""The teacher-data collector of stage 3 P1 (decision 0024; Learner v2 plan 2026-10-08-stage3-p1-learner, task 8).

It plays the manifest's lockstep self-play rounds and writes M12's expert shards. M12's teacher (expert.py) labels
the admitted learner roots; everything else is here, and no battle rule is: the engine decides legality, outcomes,
the tiebreak and the request epochs, M12's expert_data the keys, the selection and the admission.

- Self-play only: both seats play the frozen collector network (params-49333 in production); no league.
- One game per environment per round: game_id = first_game_id + round * parallel_games + env. Its teams are the
  pool's pairing of the game id (pairing.pairings(manifest.seed, game_ids, 0, pool.weights)) and its battle is
  episode `round` of environment `env` of a batch seeded with manifest.seed, so a game depends on its id alone. A
  finished game does not start another episode: it stays idle (Batch.step's active mask) until the round ends.
- The learner seat of a game is expert.learner_seat(game_id); only its rows are stored, one on every lockstep step
  of the game (waiting steps are UNREQUESTED), logical_tick 0.. from the team-preview row on.
- Raw draws, both seats: the action is drawn from the network's full legal distribution (the pair head's
  log-softmax over every legal joint action, as Model.full_joint_log_probs gives it, or the team head's 360 actions
  at team preview) by inverse CDF over the action ids in ascending order, with u = word / 2**64 of the decision
  key's raw word (expert_data.selection_word, domain "raw"); raw_logp is the drawn action's log-probability
  (one legal action: FORCED, logp 0). The opponent seat draws the same way with its own key.
- Per logical tick, M12's collector contract (EXPERT_TEACHER.md): query the roots, observe every learner request,
  admit the complete tick's eligible selected roots before any teacher work, label the admitted ones, raw_decision
  for the others, commit the tick, and only then step the engine.
- A game is cut after max_steps steps and scored by the reference's tiebreak as SelfPlay scores it (done; an
  unresolvable tiebreak or a step the engine refuses with E_UNSUPPORTED is a loss), so every stored trajectory
  ends with done on its last row and no bootstrap is needed. A round that does not finish (a stop, a crash) is
  discarded and played again from its start, so no truncated trajectory is ever written.
- Resume at round boundaries: the collection state (the next round, the label cursor with the teacher's history
  via expert.teacher_checkpoint, the counters, the shards) is saved atomically after every completed round.
"""
import contextlib
import dataclasses
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np

import duoforge
from duoforge import _layout

from . import pairing
from .selfplay import BROUGHT, ROSTER, TEAM_ACTIONS, TEAM_TABLE, _REWARDS

C = _layout.CONSTANTS
MAX_STEPS = 500  # the cut-off of SelfPlay
STATE = "collect-state.json"
STATE_VERSION = 1
PARAMS_49333_SHA256 = "ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb"
_TEAM = C["DUOFORGE_CHOICE_TEAM_SELECTION"]
_TERMINAL = C["DUOFORGE_BOUNDARY_TERMINAL"]
_UNSUPPORTED = C["DUOFORGE_E_UNSUPPORTED"]
_BOUNDARIES = {C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]: "TEAM_SELECTION", C["DUOFORGE_BOUNDARY_TURN"]: "TURN",
               C["DUOFORGE_BOUNDARY_REPLACEMENT"]: "REPLACEMENT", C["DUOFORGE_BOUNDARY_PIVOT"]: "PIVOT"}
COUNTERS = ("eligible", "selected", "admitted", "targets", "public_refusals", "work_exhausted", "capped", "forced",
            "unselected", "unrequested", "audits", "games", "rows", "cuts", "unresolved", "engine_unsupported")


def _ed():
    from duoforge_search import expert_data
    return expert_data


SHARD_ROWS = _ed().MAX_SHARD_ROWS  # rows per shard (at most expert_data.MAX_SHARD_ROWS)


@dataclasses.dataclass(frozen=True)
class CollectResult:
    """The collection so far: games finished, rows and targets written, the counters, whether every requested
    round is complete, and the next round to play."""
    games: int
    rows: int
    targets: int
    counters: dict
    complete: bool
    next_round: int


def pairing_of(manifest, pool, game_ids):
    """(side-0 team, side-1 team) of each game id (n, 2): the pool's pairing of the game id, a pure function of the
    manifest seed and the id (pairing.pairings with episode 0)."""
    ids = np.asarray(game_ids, np.uint64).reshape(-1)
    side0, side1 = pairing.pairings(manifest.seed, ids, np.zeros(ids.size, np.uint64), pool.weights)
    return np.stack([side0, side1], axis=1)


def raw_draws(logps, legal, keys, seed):
    """The raw actions of rows logps (B, N) over their legal actions legal (B, N) bool, one decision key each:
    inverse CDF over the legal ids in ascending order at u = word / 2**64 of the key's raw word (manifest seed);
    returns (actions (B,) int64, their log-probabilities (B,) float64). A row with one legal action gives it with
    log-probability 0 (FORCED). Each row's draw depends only on its own row and key. ValueError for a row without a
    legal action or with a nonfinite or positive log-probability on one."""
    ed = _ed()
    logps, legal = np.asarray(logps), np.asarray(legal, bool)
    keys = list(keys)
    if logps.ndim != 2 or legal.shape != logps.shape or len(keys) != logps.shape[0]:
        raise ValueError("raw_draws needs (B, N) log-probabilities, a (B, N) legal mask and B keys")
    actions, out = np.zeros(len(keys), np.int64), np.zeros(len(keys), np.float64)
    for i, key in enumerate(keys):
        ids = np.flatnonzero(legal[i])
        if not ids.size:
            raise ValueError(f"raw draw: row {i} has no legal action")
        lp = logps[i, ids].astype(np.float64)
        if not np.isfinite(lp).all() or (lp > 0).any():
            raise ValueError(f"raw draw: row {i} needs finite log-probabilities <= 0 on its legal actions")
        if ids.size == 1:
            actions[i], out[i] = ids[0], 0.0
            continue
        cdf = np.cumsum(np.exp(lp))
        u = ed.selection_word(key, seed, domain="raw") / 2 ** 64
        j = int(np.searchsorted(cdf, u * cdf[-1], side="right"))  # the first id whose cumulative mass exceeds u
        if j == ids.size:  # u rounded to 1.0 (word >= 2**64 - 2**10): the inverse CDF's limit, the last mass
            j = int(np.flatnonzero(np.exp(lp) > 0)[-1])
        actions[i], out[i] = ids[j], lp[j]
    return actions, out


def distributions(model, params, obs, slots, mask, is_team):
    """One network pass over rows (B, ...): (pairs (B, 1024) float32, team (B, 360) float32, value (B,) float32).
    pairs is the pair head's log-softmax at the legal joint actions of mask and -inf elsewhere, which is
    Model.full_joint_log_probs (full_joint_log_probs_traced's definition, here on the rows of one fixed-shape pass);
    team is the team head (Model.apply's), for the team-preview rows is_team. Ids are checked first, as act does."""
    import jax
    obs, slots, mask = np.asarray(obs), np.asarray(slots), np.asarray(mask, bool)
    model.check(obs)
    logp_pairs, logp_team, value = jax.block_until_ready(model.apply(params, obs, slots, mask))
    b = obs.shape[0]
    pairs = np.where(mask.reshape(b, -1), np.asarray(logp_pairs, np.float32), np.float32(-np.inf))
    return pairs, np.asarray(logp_team, np.float32), np.asarray(value, np.float32)


def params_digest(params):
    """SHA-256 over every parameter array (name, dtype, shape, bytes) in sorted name order."""
    from . import checkpoint
    h = hashlib.sha256()
    for name, value in sorted(checkpoint.flatten(params).items()):
        a = np.ascontiguousarray(np.asarray(value))
        h.update(name.encode("utf-8") + a.dtype.str.encode("ascii") + repr(a.shape).encode("ascii") + a.tobytes())
    return h.hexdigest()


def _plain(value):
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, np.generic):
        return value.item()
    return value


def _sha(value):
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def manifest_digest(manifest):
    """SHA-256 of the manifest's fields as canonical JSON."""
    return _sha({f.name: getattr(manifest, f.name) for f in dataclasses.fields(manifest)})


def pool_digest(pool):
    """SHA-256 of the pool's team ids, file hashes and weights as canonical JSON."""
    return _sha({"ids": list(pool.ids), "sha256": list(pool.sha256), "weights": [float(w) for w in pool.weights]})


def read_state(out):
    """The collection state of out (a dict); ValueError without one."""
    path = Path(out) / STATE
    if not path.exists():
        raise ValueError(f"{out}: no collection state to resume ({STATE})")
    return json.loads(path.read_text(encoding="ascii"))


def _write_state(out, state):
    """Atomically: a temporary file, fsync, replace, and the directory flushed."""
    from duoforge_replay.dataset import fsync_dir
    path = Path(out) / STATE
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="ascii") as f:
        f.write(json.dumps(state, sort_keys=True, separators=(",", ":")))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def _file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _Collection:
    """One collection run: its inputs, the label cursor, the counters and the shards written."""

    def __init__(self, manifest, model, params, pool, search, out, config, max_steps, workers, ledger):
        self.manifest, self.model, self.params, self.pool, self.search = manifest, model, params, pool, search
        self.out, self.config, self.max_steps, self.workers, self.ledger = out, config, max_steps, workers, ledger
        self.shard_dir = out / "shards"
        self.context = search.leaves.context

    def roots(self, r):
        """The batch of round r: environment e plays game first_game_id + r * parallel_games + e as its episode r."""
        m = self.manifest
        n = m.parallel_games
        pairs = pairing_of(m, self.pool, m.first_game_id + r * n + np.arange(n))
        setups = self.pool.setups(pairs[:, 0], pairs[:, 1])
        roots = duoforge.Batch(self.context, setups, self.workers, m.seed)
        try:
            if r:
                roots.reset_setups(np.arange(n, dtype=np.uint32), np.full(n, r, np.uint32), setups)
        except BaseException:
            roots.close()
            raise
        return roots

    def device(self):
        return self.ledger.device() if self.ledger is not None else contextlib.nullcontext()

    def save(self, identity, next_round, cursor, roots, counters, shards):
        """The state after a completed round: the teacher's checkpoint is taken against the next round's (fresh)
        roots, so a resume restores it into a fresh search with restore_teacher."""
        from duoforge_search import expert as ex
        ed = _ed()
        teacher = None if roots is None else \
            ex.teacher_checkpoint(self.search, roots, cursor, self.config, self.manifest).decode("ascii")
        _write_state(self.out, {"version": STATE_VERSION, "identity": identity, "next_round": next_round,
                                "seed": self.manifest.seed, "cursor": ed.cursor_bytes(cursor, self.manifest).decode(
                                    "ascii"), "teacher": teacher, "counters": counters, "shards": shards})
        if self.ledger is not None:
            self.ledger.save()

    def play(self, r, roots, cursor, counters, stop):
        """Round r on roots; returns (cursor, shards written) or None when stop asked to end it (its shards stay
        on disk until a resume sets them aside)."""
        from duoforge_search import expert as ex
        ed = _ed()
        m, search = self.manifest, self.search
        n = m.parallel_games
        games = m.first_game_id + r * n + np.arange(n)
        seats = np.array([ex.learner_seat(int(g)) for g in games], np.int64)
        every = np.arange(n)
        running = np.ones(n, bool)
        pending, shards = [], []

        def flush(rows):
            path = self.shard_dir / f"round-{r:04d}-shard-{len(shards):04d}.json"
            sha = ed.write_shard(path, rows, m)
            shards.append({"name": path.name, "sha256": sha, "rows": len(rows)})

        for t in range(self.max_steps):
            if stop is not None and stop.requested:
                return None
            roots.query()  # the candidates Batch.step answers
            obs, slots, pairs = (x.copy() for x in roots.query_encoded(m.encoder, search.ext_supported))
            requests, domains = roots.requests.copy(), roots.domains.copy()
            requested = (requests["requested"] != 0) & running[:, None]
            team = requested & (domains["kind"] == _TEAM)
            if team.any():
                d = domains[team]
                if (d["member_count"] != ROSTER).any() or (d["pick_count"] != BROUGHT).any() or \
                        (duoforge.joint_counts(d) != TEAM_ACTIONS).any():
                    raise ValueError(f"the team head knows only the profile {ROSTER}/{BROUGHT}")
            with self.device():
                pair_logp, team_logp, value = distributions(
                    self.model, self.params, obs.reshape(2 * n, -1), slots.reshape((2 * n,) + slots.shape[2:]),
                    pairs.reshape(2 * n, *pairs.shape[2:]), team.reshape(-1))
            pair_logp, team_logp, value = (x.reshape((n, 2) + x.shape[1:]) for x in (pair_logp, team_logp, value))
            # Raw draws of every request of both seats, before any selection.
            raw_action, raw_logp = np.zeros((n, 2), np.int64), np.zeros((n, 2), np.float64)
            for rows, logp, legal in ((team, team_logp, lambda e, p: np.ones(TEAM_ACTIONS, bool)),
                                      (requested & ~team, pair_logp, lambda e, p: pairs[e, p].reshape(-1))):
                at = np.argwhere(rows)
                if not at.size:
                    continue
                keys = [ed.DecisionKey(int(games[e]), int(p), int(requests[e, p]["epoch"])) for e, p in at]
                a, lp = raw_draws(logp[at[:, 0], at[:, 1]], np.stack([legal(e, p) for e, p in at]), keys, m.seed)
                raw_action[at[:, 0], at[:, 1]], raw_logp[at[:, 0], at[:, 1]] = a, lp
            # The teacher sees every learner request of the tick.
            learner = requested[every, seats]
            envs = np.flatnonzero(learner)
            ex.observe(search, roots, envs, seats[envs])
            keys, legal_count, boundary = {}, {}, {}
            admission = []
            for e in envs:
                p = int(seats[e])
                keys[e] = ed.DecisionKey(int(games[e]), p, int(requests[e, p]["epoch"]))
                boundary[e] = _BOUNDARIES[int(requests[e, p]["boundary_kind"])]
                legal_count[e] = TEAM_ACTIONS if team[e, p] else int(np.count_nonzero(pairs[e, p]))
                if boundary[e] in ed.DECISION_BOUNDARIES and legal_count[e] >= 2:
                    counters["eligible"] += 1
                    if ed.is_selected(keys[e], m.seed):
                        counters["selected"] += 1
                        admission.append(ed.AdmissionRequest(keys[e], boundary[e], legal_count[e]))
            batch = ed.admit_tick(cursor, admission)  # before any teacher work
            admitted, capped = set(batch.admitted_keys), set(batch.cap_raw_keys)
            counters["admitted"] += len(admitted)
            decisions, outcomes = {}, []
            last_step = t == self.max_steps - 1
            for e in envs:
                p, key = int(seats[e]), keys[e]
                a, lp = int(raw_action[e, p]), float(raw_logp[e, p])
                if legal_count[e] == 1:
                    d = ex.raw_decision(ed.RowStatus.FORCED, a, 0.0, legal_count=1)
                elif key in admitted:
                    d = ex.label_decision(search, roots, env=int(e), seat=p, key=key, raw_action=a, raw_logp=lp,
                                          last_step=last_step, config=self.config, manifest=m)
                elif key in capped:
                    d = ex.raw_decision(ed.RowStatus.CAP_RAW, a, lp, legal_count=legal_count[e])
                else:
                    d = ex.raw_decision(ed.RowStatus.UNSELECTED, a, lp, legal_count=legal_count[e])
                if key in admitted or key in capped:
                    outcomes.append(ed.AdmissionOutcome(key, d.status))
                decisions[e] = d
            cursor = ed.commit_tick(cursor, outcomes)  # the whole tick, before any game advances
            # One engine step of every running game.
            actions = raw_action.copy()
            for e, d in decisions.items():
                actions[e, seats[e]] = d.action
            choices = np.zeros((n, 2), _layout.FACTORED_CHOICE)
            pair_rows = requested & ~team
            choices["slot"][..., 0] = np.where(pair_rows, actions // _layout.MAX_SLOT_OPTIONS, 0)
            choices["slot"][..., 1] = np.where(pair_rows, actions % _layout.MAX_SLOT_OPTIONS, 0)
            choices["picks"][..., :BROUGHT] = np.where(team[..., None], TEAM_TABLE[np.where(team, actions, 0)], 0)
            indices = np.full((n, 2), _layout.NO_CHOICE, np.uint16)
            indices[requested] = duoforge.joint_indices(domains[requested], choices[requested])
            failed = np.zeros(n, bool)
            try:
                roots.step(indices, active=running)
            except duoforge.DuoforgeError as err:
                # A game the engine refuses to step (E_UNSUPPORTED) ends as a loss, as in SelfPlay; anything else
                # stops the collection.
                if err.statuses is None:
                    raise
                failed = (err.statuses == _UNSUPPORTED) & running
                if (err.statuses[~failed] != 0).any():
                    raise
            terminal = running & ~failed & (roots.results["boundary_kind"] == _TERMINAL)
            reward = np.zeros(n, np.float64)
            for e in np.flatnonzero(terminal):
                reward[e] = _REWARDS[roots.result(e)][seats[e]]
            reward[failed] = -1.0
            counters["engine_unsupported"] += int(failed.sum())
            cut = running & ~terminal & ~failed & (t + 1 >= self.max_steps)
            for e in np.flatnonzero(cut):
                try:
                    reward[e] = _REWARDS[roots.tiebreak(e)][seats[e]]  # scored as the reference's tiebreak scores it
                except duoforge.DuoforgeError:
                    reward[e] = -1.0  # the reference's bench order would decide: a loss for both, as SelfPlay
                    counters["unresolved"] += 1
            done = terminal | failed | cut
            counters["cuts"] += int(cut.sum())
            # The learner rows of the tick, in game order.
            for e in np.flatnonzero(running):
                p = int(seats[e])
                kind = _BOUNDARIES[int(requests[e, p]["boundary_kind"])]
                mask = np.ones(TEAM_ACTIONS, bool) if kind == "TEAM_SELECTION" else pairs[e, p].copy()
                step = ex.StepData(key=ed.DecisionKey(int(games[e]), p, int(requests[e, p]["epoch"])),
                                   logical_tick=t, boundary=kind, obs=obs[e, p].copy(), slots=slots[e, p].copy(),
                                   legal_mask=mask, requested=bool(learner[e]), reward=float(reward[e]),
                                   done=bool(done[e]), collector_value=float(value[e, p]), bootstrap=0.0)
                row = ex.teacher_row(decisions.get(e), step, m)
                counters[{ed.RowStatus.TARGET: "targets", ed.RowStatus.PUBLIC_REFUSAL: "public_refusals",
                          ed.RowStatus.WORK_EXHAUSTED: "work_exhausted", ed.RowStatus.CAP_RAW: "capped",
                          ed.RowStatus.FORCED: "forced", ed.RowStatus.UNSELECTED: "unselected",
                          ed.RowStatus.UNREQUESTED: "unrequested"}[row.status]] += 1
                counters["audits"] += bool(row.audit.get("selected"))
                pending.append(row)
                if len(pending) >= SHARD_ROWS:
                    flush(pending[:SHARD_ROWS])
                    pending = pending[SHARD_ROWS:]
            counters["rows"] += int(running.sum())
            counters["games"] += int(done.sum())
            running &= ~done
            if not running.any():
                break
        if running.any():
            raise AssertionError("a game outlived the cut-off")
        if pending:
            flush(pending)
        return cursor, shards


def collect(manifest, model, params, pool, search, out_dir, *, rounds=None, max_steps=MAX_STEPS, label_limit=None,
            budget=None, audit_threshold=None, workers=None, ledger=None, resume=False, stop=None, identity=None):
    """Plays rounds [next round, rounds) of the manifest's collection into out_dir and returns a CollectResult.

    manifest: M12's DataManifest (written once as out_dir/manifest.json); model, params: the collector network,
    which plays both seats (self-play); pool: the teams the pairings index; search: the teacher's honest search
    (expert.TeacherConfig.from_manifest must match it, its spread table must be the manifest's belief_hash; a
    resume needs a fresh one). rounds: the rounds to have played at the end (default the manifest's);
    max_steps: the cut-off; label_limit: the label cap (default and production expert_data.LABEL_LIMIT; smaller only
    in tests); budget, audit_threshold: the teacher's overrides; workers: the roots' native workers (default the
    manifest's; results do not depend on it); ledger: a ledger.Ledger, phase "generate"; resume: continue out_dir
    from its last completed round (refused for another manifest or configuration); stop: an object whose
    `requested` ends the run at the next tick (the round in play is played again on resume); identity: more
    fields a resume must match (the CLI's checkpoint hash). Shards go to out_dir/shards (round-RRRR-shard-SSSS.json,
    in write order). ValueError for any refusal."""
    from duoforge_replay.dataset import refuse_repository
    from duoforge_search import expert as ex
    ed = _ed()
    ed.validate_manifest(manifest)
    out = Path(out_dir)
    refuse_repository(out)
    rounds = manifest.rounds if rounds is None else rounds
    label_limit = ed.LABEL_LIMIT if label_limit is None else label_limit
    for name, value, high in (("rounds", rounds, manifest.rounds), ("max_steps", max_steps, None),
                              ("label_limit", label_limit, ed.LABEL_LIMIT)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or (high is not None and value > high):
            raise ValueError(f"{name} must be an integer in [1, {high if high is not None else 'inf'}] (got {value!r})")
    if not 1 <= SHARD_ROWS <= ed.MAX_SHARD_ROWS:
        raise ValueError(f"shards hold 1 to {ed.MAX_SHARD_ROWS} rows")
    if search.encoder != manifest.encoder:
        raise ValueError(f"the search encodes version {search.encoder}, the manifest pins {manifest.encoder}")
    if search.table_info["sha256"] != manifest.belief_hash:
        raise ValueError("the search's spread table (belief) differs from the manifest's belief_hash")
    overrides = {k: v for k, v in (("budget", budget), ("audit_threshold", audit_threshold)) if v is not None}
    config = ex.TeacherConfig.from_manifest(manifest, search_seed=search.seed, **overrides)
    config.check(search)
    workers = manifest.workers if workers is None else workers
    excluded = None if search.exclude_teams is None else [None if x is None else int(x) for x in search.exclude_teams]
    ident = {"manifest_sha256": manifest_digest(manifest), "teacher": _plain(config), "max_steps": max_steps,
             "label_limit": label_limit, "shard_rows": SHARD_ROWS, "encoder": search.encoder,
             "ext_supported": int(search.ext_supported), "params_sha256": params_digest(params),
             "search_params_sha256": params_digest(search.params), "belief_sha256": search.table_info["sha256"],
             "exclude_teams": excluded, "pool": {"ids": list(pool.ids), "sha256": list(pool.sha256),
                                                 "weights": [float(w) for w in pool.weights]},
             **_plain(identity or {})}
    run = _Collection(manifest, model, params, pool, search, out, config, max_steps, workers, ledger)
    with contextlib.ExitStack() as stack:
        if ledger is not None:  # charged to phase generate; saved on every exit, after the phase has closed
            stack.callback(ledger.save)
            stack.enter_context(ledger.phase("generate"))
        if resume:
            state = read_state(out)
            if state.get("version") != STATE_VERSION:
                raise ValueError(f"resume refused: collection state version {state.get('version')!r}")
            changed = sorted(k for k in set(ident) | set(state["identity"]) if ident.get(k) != state["identity"].get(k))
            if changed:
                raise ValueError(f"resume refused: {', '.join(changed)} differ from the collection's")
            if ed.read_manifest(out / "manifest.json") != manifest:
                raise ValueError("resume refused: the manifest differs from the collection's")
            shards = state["shards"]
            for s in shards:
                path = run.shard_dir / s["name"]
                if not path.exists() or _file_sha(path) != s["sha256"]:
                    raise ValueError(f"resume refused: shard {s['name']} is missing or altered")
            listed = {s["name"] for s in shards}
            stray = sorted(p for p in run.shard_dir.glob("*") if p.name not in listed)
            if stray:  # an interrupted round's shards: set aside for diagnosis, never read as data
                discarded = out / "discarded"
                attempt = discarded / f"attempt-{len(list(discarded.glob('attempt-*'))):04d}"
                attempt.mkdir(parents=True)
                for p in stray:
                    os.replace(p, attempt / p.name)
            r, counters = state["next_round"], dict(state["counters"])
            roots = None
            if r < rounds:
                roots = run.roots(r)
                cursor = ex.restore_teacher(search, roots, state["teacher"].encode("ascii"), config, manifest)
        else:
            if (out / STATE).exists() or (out / "manifest.json").exists() or \
                    (run.shard_dir.exists() and any(run.shard_dir.iterdir())):
                raise ValueError(f"{out}: a collection exists there (resume it, or choose another directory)")
            run.shard_dir.mkdir(parents=True, exist_ok=True)
            ed.write_manifest(out / "manifest.json", manifest)
            r, counters, shards = 0, {k: 0 for k in COUNTERS}, []
            cursor = ed.LabelCursor(remaining=label_limit)
            roots = run.roots(0)
            run.save(ident, 0, cursor, roots, counters, shards)
        try:
            while r < rounds:
                played = run.play(r, roots, cursor, counters, stop)
                if played is None:
                    state = read_state(out)
                    return CollectResult(state["counters"]["games"], state["counters"]["rows"],
                                         state["counters"]["targets"], dict(state["counters"]), False, r)
                cursor, written = played
                shards = shards + written
                r += 1
                roots.close()
                roots = run.roots(r) if r < manifest.rounds else None
                run.save(ident, r, cursor, roots, counters, shards)
                if stop is not None and stop.requested and r < rounds:
                    return CollectResult(counters["games"], counters["rows"], counters["targets"], dict(counters),
                                         False, r)
        finally:
            if roots is not None:
                roots.close()
    return CollectResult(counters["games"], counters["rows"], counters["targets"], dict(counters), True, r)


def main(argv=None):
    """python -m duoforge_learn.collect_expert: exit 0 after the requested rounds, 3 when a signal stopped it
    (resume with --resume), 2 for a refusal (its cause on stderr)."""
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.collect_expert",
                                description="Stage 3 P1 teacher-data collection (self-play, honest teacher).")
    p.add_argument("--init", required=True, help="the collector, opponent and teacher network (params-49333)")
    p.add_argument("--manifest", required=True, help="the run's manifest file (expert_data.write_manifest)")
    p.add_argument("--out", required=True, help="the collection's directory, outside the repository")
    p.add_argument("--rounds", type=int, default=None, help="rounds to have played (default: the manifest's)")
    p.add_argument("--workers", type=int, default=None, help="native workers; must equal the manifest's")
    p.add_argument("--max-steps", type=int, default=MAX_STEPS, help="the cut-off, scored by tiebreak")
    p.add_argument("--teams", default=None, help="registry team ids, comma-separated (default: Teams A and B)")
    p.add_argument("--team-weights", default=None, help="sampling weights of the teams, comma-separated")
    p.add_argument("--teams-root", default="data/teams", help="the team registry")
    p.add_argument("--ledger", default=None, help="the arm's compute ledger (ledger.py), phase generate")
    p.add_argument("--resume", action="store_true", help="continue the collection in --out")
    p.add_argument("--allow-other-init", action="store_true", help="tests only: another network than params-49333")
    args = p.parse_args(argv)
    context = search = None
    try:
        from duoforge_replay.dataset import refuse_repository
        from duoforge import teams
        from duoforge_search import expert_data as ed, honest
        from . import checkpoint, policy, runstate
        from .train import DATA_KINDS
        refuse_repository(args.out)
        sha = _file_sha(args.init)
        if not args.allow_other_init and sha != PARAMS_49333_SHA256:
            raise ValueError(f"--init must be params-49333 ({PARAMS_49333_SHA256}), not {sha}")
        manifest = ed.read_manifest(Path(args.manifest))
        if manifest.checkpoint_hash != sha:
            raise ValueError(f"the manifest pins checkpoint {manifest.checkpoint_hash}, --init is {sha}")
        if args.workers is not None and args.workers != manifest.workers:
            raise ValueError(f"the manifest pins {manifest.workers} workers (--workers {args.workers})")
        params, config = checkpoint.load_current(args.init)
        encoder, ext = checkpoint.encoder_of(config), checkpoint.ext_supported_of(config)
        model = policy.make(checkpoint.model_config(config, params))
        context = duoforge.Context(data_kind=DATA_KINDS[config["data"]["kind"]])
        weights = None if args.team_weights is None else [float(w) for w in args.team_weights.split(",")]
        if args.teams is None:
            pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
            pool = pool if weights is None else pool.with_weights(weights)
        else:
            pool = teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root,
                              weights=weights)
        if manifest.pool_hash != pool_digest(pool):
            raise ValueError(f"the manifest pins pool {manifest.pool_hash}, the given teams are {pool_digest(pool)}")
        tc = manifest.teacher_config
        search = honest.Honest(context, model, params, encoder, ext, k=tc["k"], m=tc["m"], s=tc["worlds"],
                               rule="mix", capacity=manifest.capacity, workers=manifest.workers, lam=tc["lam"])
        book = None
        if args.ledger:
            from . import ledger as ledger_mod
            book = ledger_mod.Ledger(args.ledger)
        stop = runstate.StopFlag().install()
        try:
            result = collect(manifest, model, params, pool, search, args.out, rounds=args.rounds,
                             max_steps=args.max_steps, ledger=book, resume=args.resume, stop=stop,
                             identity={"init_sha256": sha, "allow_other_init": args.allow_other_init})
        finally:
            stop.restore()
    except (ValueError, OSError, KeyError) as err:
        print(f"collect_expert: {err}", file=sys.stderr)
        return 2
    finally:
        if search is not None:
            search.close()
        if context is not None:
            context.close()
    print(json.dumps({"complete": result.complete, "next_round": result.next_round, **result.counters}))
    return 0 if result.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
