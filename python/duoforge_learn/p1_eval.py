"""The stage 3 P1 evaluation games (decision 0024; P1 plan C5, Learner v2 side): the runner that plays M12's
predeclared schedule and writes the records duoforge_search.expert_eval reads. expert_eval plays nothing; this
module plays everything and decides nothing about the gate.

- The games: expert_eval.make_eval_rows(pool, manifest), all 12288 of them (checked there against the manifest's
  pool and block hashes). For each row the student is the row's arm checkpoint (pilot or control) and the opponent
  the row's opponent checkpoint (control, frozen, BC, 3600, 11000 or ladder), with the row's student_team on
  student_seat and opponent_team on the other seat.
- The seeds (P1 plan, "Evaluation seeds and runner order", agreed with M12): every row of a (suite, opponent,
  bucket) block carries the block's one batch seed. The engine derives a battle's RNG from the batch seed, the
  environment and the episode only, so the runner plays one evaluate.play_suite call per (suite, opponent, arm,
  bucket, seat) with that seed and the block's pairs in pair order: environment = pair, episode 1. Pair p's battle
  RNG is duoforge_batch_seeds(seed, p, 1) on both seats and in both arms. A call needs pairs 0..k-1 (a prefix of
  its pairs, as the smoke takes them) and one seed; anything else is refused, never re-ordered.
- The players: raw greedy play for both sides (book and preview search off, as the manifest pins), each
  checkpoint a Player in the encoder layout it was trained with (checkpoint.load_trained / trained_model, never
  widened: P1's are encoder 4; an older format-2 layout is served by its own encoder through Batch.query_encoded).
  Each file is read once: its SHA-256 is of the very bytes that are loaded, and must be the manifest's for its name.
  Refused: a file load_trained cannot read (format 1, a feature list that is not its encoder's layout),
  checkpoints of several data kinds or none, and a network whose embedded ids do not name the same rows under the
  evaluation's tables (checkpoint.check_ids, when the data fingerprint differs).
- Determinism: on a GPU the network passes must use deterministic XLA ops (arena.require_deterministic_gpu, as the
  P0 arena); without them the run is refused before play.
- The records (expert_eval.RECORD_FIELDS): the schedule fields, score (the student's: 1 win, 0.5 tie, 0 loss) and
  finished, and the Trick Room diagnostic's TR_FIELDS from an expert_eval.TrickRoomTracker observing every call
  (environment e's fields go to pair e's row). A game the engine refused (E_UNSUPPORTED) or cut off at MAX_STEPS
  (tiebreak-resolved or not; owner 2026-10-09) is finished = False with score null, which leaves its group
  INCOMPLETE; the two are counted apart (cutoffs, refused). The records are canonical JSON: the same inputs give
  the same bytes.
- The run writes {"records": ..., "ledger": ...}, expert_eval main's --baseline file, once (never over an existing
  file) outside the repository.
- The smoke (--smoke, plan C5's fixed 64-game evaluation smoke): smoke_indices, a predeclared stratified selection
  (round robin over the 20 (suite, opponent, arm, bucket) units in schedule order, both seats, pairs in order, until
  64 games: pair 0 of every unit, then pair 1 of the first 12), so PP_ and LL_, every opponent (the older-encoder
  panel checkpoints too) and both arms play. It writes a report (games, seconds, games/s, forecast, cut-offs,
  refused, status, ledger) instead of records. Its SmokeClock times JIT apart: a network's first pass at a row count
  compiles; the warm rate counts only calls that compiled nothing. The forecast, an upper bound (the smoke's
  batches of 1-2 games are slower per game than the run's 256-512), is the full run's estimated JIT (per player
  its measured compile excess times the row counts it plays in the run) plus 12288 games at the warm rate. Status
  STOP when a game was cut off or refused, the warm rate is below 5 games/s or the forecast exceeds 60 minutes,
  else GO.
- The ledger (duoforge_learn.ledger, phase "evaluate") is the shared evaluation cost: a --ledger file sums every
  process that ran into it (the smoke, refusals, crashes, the run); it is saved whatever happens once it exists.
  GPU-seconds count only the network passes on a non-CPU device.
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys
import time
import zipfile
import zlib

import numpy as np

import duoforge

from . import evaluate, suite

MAX_STEPS = 1000  # play_suite's cut-off; a cut game is unfinished
PHASE = "evaluate"
SMOKE_GAMES = 64
SMOKE_MIN_RATE = 5.0  # games per second (plan C5)
SMOKE_MAX_FORECAST = 3600.0  # seconds of the whole evaluation including JIT (plan C5: 60 minutes)
CALL_KEY = ("suite", "opponent", "arm", "bucket", "student_seat")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _TimedModel:
    """A model whose act runs in one device section of ledger (until its outputs are ready)."""

    def __init__(self, model, ledger):
        self._model, self._ledger = model, ledger

    def act(self, *args, **kwargs):
        import jax
        with self._ledger.device():
            out = self._model.act(*args, **kwargs)
            jax.block_until_ready(out)
        return out

    def __getattr__(self, name):
        return getattr(self._model, name)


def load_checkpoints(paths, manifest):
    """{name: (params, config, sha256)} of every checkpoint the manifest pins, read in its own layout from the
    bytes that were hashed; ValueError for a missing or extra name, a SHA-256 the manifest does not pin for that
    name, or a file load_trained refuses."""
    from duoforge_search import expert_eval
    from . import checkpoint
    if set(paths) != set(expert_eval.CHECKPOINTS):
        raise ValueError(f"name exactly the checkpoints {expert_eval.CHECKPOINTS} (got {sorted(paths)})")
    out = {}
    for name in expert_eval.CHECKPOINTS:
        with open(paths[name], "rb") as f:
            data = f.read()
        sha = hashlib.sha256(data).hexdigest()
        if sha != manifest.checkpoints[name]:
            raise ValueError(f"checkpoint {name}: {paths[name]} has SHA-256 {sha}, the manifest pins "
                             f"{manifest.checkpoints[name]}")
        try:
            params, config = checkpoint.load_trained(io.BytesIO(data))
            checkpoint.ext_supported_of(config)  # a mask its encoder has no columns for is refused here
        except (ValueError, KeyError, zipfile.BadZipFile, zlib.error, EOFError) as err:  # damaged: a refusal
            raise ValueError(f"checkpoint {name}: {paths[name]}: {err}") from err
        out[name] = (params, config, sha)
    return out


def data_kind(loaded):
    """The one data kind (train.DATA_KINDS name) of the loaded checkpoints; ValueError for several or none."""
    kinds = {name: (config.get("data") or {}).get("kind") for name, (_, config, _) in loaded.items()}
    if len(set(kinds.values())) != 1 or None in kinds.values():
        raise ValueError(f"the checkpoints need one data kind: {kinds}")
    return next(iter(kinds.values()))


def make_players(loaded, context, ledger=None):
    """{name: evaluate.Player} of the loaded checkpoints under context, each reading its own encoder's rows.
    Checks that every network's ids name the same rows under context (as train --init does). With a ledger on a
    non-CPU device, each network pass is a device section."""
    from . import checkpoint
    on_gpu = ledger is not None and _platform() != "cpu"
    players = {}
    for name, (params, config, _) in loaded.items():
        if (config.get("data") or {}).get("fingerprint") != context.fingerprint().hex():
            try:
                checkpoint.check_ids(config, context)
            except ValueError as err:
                raise ValueError(f"checkpoint {name}: {err}") from err
        model = checkpoint.trained_model(config, params)
        if on_gpu:
            model = _TimedModel(model, ledger)
        players[name] = evaluate.Player(model, params, checkpoint.encoder_of(config), name,
                                        checkpoint.ext_supported_of(config))
    return players


def _platform():
    import jax
    return jax.devices()[0].platform


def call_groups(rows):
    """The play_suite calls of schedule rows: one index array per (suite, opponent, arm, bucket, seat), in pair
    order, the calls in game-id order of their first rows. ValueError unless a call's pairs are 0..k-1 (environment
    = pair) and its rows carry one seed."""
    keys = list(zip(*(np.asarray(rows[k]).tolist() for k in CALL_KEY)))
    groups = {}
    for i in np.argsort(np.asarray(rows["game_id"]), kind="stable").tolist():
        groups.setdefault(keys[i], []).append(i)
    out = []
    for key, members in groups.items():
        idx = np.array(members)
        idx = idx[np.argsort(np.asarray(rows["pair"])[idx], kind="stable")]
        pairs = np.asarray(rows["pair"])[idx]
        if not np.array_equal(pairs, np.arange(idx.size)):
            raise ValueError(f"the rows of call {key} must be pairs 0..{idx.size - 1} (environment = pair), "
                             f"not {pairs[:8].tolist()}...")
        if np.unique(np.asarray(rows["seed"])[idx]).size != 1:
            raise ValueError(f"the rows of call {key} must carry one seed (the block's batch seed)")
        out.append(idx)
    pairs = {}
    for i, key in enumerate(zip(*(np.asarray(rows[k]).tolist() for k in ("suite", "opponent", "bucket", "pair")))):
        same = (int(rows["seed"][i]), int(rows["student_team"][i]), int(rows["opponent_team"][i]))
        if pairs.setdefault(key, same) != same:
            raise ValueError(f"the seats and arms of pair {key} must share the seed and the teams")
    return out


def suite_rows(rows, idx):
    """play_suite's rows (suite.SUITE) of schedule rows idx: the student's team on its seat."""
    seat = np.asarray(rows["student_seat"])[idx].astype(np.int64)
    student = np.asarray(rows["student_team"])[idx]
    foe = np.asarray(rows["opponent_team"])[idx]
    out = np.zeros(idx.size, dtype=suite.SUITE)
    out["side0"] = np.where(seat == 0, student, foe)
    out["side1"] = np.where(seat == 0, foe, student)
    out["learner_seat"] = seat
    out["game"] = np.arange(idx.size)
    return out


def play_rows(context, pool, rows, players, *, workers=1, max_steps=MAX_STEPS, tracker=None, clock=None):
    """(records, counts) of schedule rows (SCHEDULE_FIELDS arrays: make_eval_rows' or a subset whose calls are
    pair prefixes): records the expert_eval.RECORD_FIELDS arrays in the rows' order, counts {"cutoffs",
    "refused"}. One play_suite call per call_groups entry: rows["arm"] against rows["opponent"] of players, seeded
    with the rows' seed, environment = pair, with tracker (an expert_eval.TrickRoomTracker, made for context when
    None) observing it. clock (a SmokeClock whose wrapped networks the players use) times every call."""
    from duoforge_search import expert_eval
    groups = call_groups(rows)  # refuses a malformed subset before any play
    if tracker is None:
        tracker = expert_eval.TrickRoomTracker(context)
    n = int(np.asarray(rows["game_id"]).size)
    out = {name: np.asarray(rows[name]).copy() for name in expert_eval.SCHEDULE_FIELDS}
    out["score"] = np.full(n, math.nan)
    out["finished"] = np.zeros(n, dtype=bool)
    for name in expert_eval.TR_FIELDS:
        out[name] = np.zeros(n, dtype=np.int64)
    counts = {"cutoffs": 0, "refused": 0}
    for idx in groups:
        first = idx[0]
        student, opponent = players[str(rows["arm"][first])], players[str(rows["opponent"][first])]
        if clock is not None:
            compiles, start = clock.compiles, clock.now()
        records = evaluate.play_suite(context, pool, suite_rows(rows, idx), student, opponent, workers,
                                      int(rows["seed"][first]), max_steps=max_steps, observers=(tracker,))
        if clock is not None:
            clock.calls.append((int(idx.size), clock.now() - start, clock.compiles > compiles))
        cut = records["unfinished"].astype(bool)
        refused = records["unresolved"].astype(bool) & ~cut  # play_suite: a refused game is unresolved, not cut
        finished = ~(cut | refused)
        counts["cutoffs"] += int(cut.sum())
        counts["refused"] += int(refused.sum())
        out["finished"][idx] = finished
        out["score"][idx] = np.where(finished, (records["result"].astype(np.float64) + 1.0) / 2.0, math.nan)
        fields = tracker.fields
        for name in expert_eval.TR_FIELDS:
            out[name][idx] = np.asarray(fields[name], dtype=np.int64)
    return out, counts


def smoke_indices(rows, games=SMOKE_GAMES):
    """The smoke's schedule indices (sorted): round robin over the (suite, opponent, arm, bucket) units in schedule
    order, both seats of a pair each turn, pairs in order, until `games` games."""
    keys = list(zip(*(np.asarray(rows[k]).tolist() for k in ("suite", "opponent", "arm", "bucket"))))
    units = {}
    for i in np.argsort(np.asarray(rows["game_id"]), kind="stable").tolist():
        units.setdefault(keys[i], {}).setdefault(int(rows["pair"][i]), []).append(i)
    picked, depth = [], 0
    while len(picked) < games:
        progress = False
        for pairs in units.values():
            if depth in pairs and len(picked) < games:
                if len(pairs[depth]) != 2 or games - len(picked) < 2:
                    raise ValueError("the smoke takes whole seat pairs")
                picked.extend(pairs[depth])
                progress = True
        if not progress:
            raise ValueError(f"the schedule has fewer than {games} games")
        depth += 1
    return np.array(sorted(picked))


class SmokeClock:
    """The smoke's timing, JIT apart from warm play. wrap(name, model) times every network pass of that player,
    keyed by its row count: the first pass of a (player, rows) key compiles (XLA traces a new shape), its excess
    over the key's later passes is that compile's JIT. play_rows records every call (games, seconds, compiled:
    whether any pass in it compiled); the warm rate counts only the calls that compiled nothing."""

    def __init__(self, now=time.perf_counter):
        self.now = now
        self.acts = {}  # (player, rows) -> [seconds of every pass]
        self.compiles = 0
        self.calls = []  # (games, seconds, compiled)

    def wrap(self, name, model):
        return _ClockedModel(model, name, self)

    def _pass(self, name, rows, seconds):
        key = (name, int(rows))
        if key not in self.acts:
            self.compiles += 1
        self.acts.setdefault(key, []).append(seconds)

    def jit_excess(self):
        """{player: the largest compile excess over its keys}: a key's first pass minus the mean of its later
        passes (else of the player's other later passes; else the whole first pass), at least 0."""
        later = {}
        for (name, _), times in self.acts.items():
            later.setdefault(name, []).extend(times[1:])
        out = {}
        for (name, _), times in self.acts.items():
            warm = times[1:] or later[name]
            excess = max(times[0] - (sum(warm) / len(warm) if warm else 0.0), 0.0)
            out[name] = max(out.get(name, 0.0), excess)
        return out

    def warm_rate(self):
        """Games per second over the calls that compiled nothing; None without such a call."""
        games = sum(g for g, _, compiled in self.calls if not compiled)
        seconds = sum(t for _, t, compiled in self.calls if not compiled)
        return games / seconds if games and seconds > 0 else None

    def jit_estimate(self, shapes):
        """The full run's JIT: per player its measured compile excess times the row counts it plays there (shapes,
        full_shapes). It assumes one compile per shape costs about the smoke's largest per player; XLA's compile
        time grows little with the batch dimension, but this is an estimate, not a measurement."""
        excess = self.jit_excess()
        missing = sorted(set(shapes) - set(excess))
        if missing:
            raise ValueError(f"no smoke measurement of {missing}: their JIT cannot be estimated")
        return float(sum(excess[name] * len(rows) for name, rows in shapes.items()))


class _ClockedModel:
    """A model whose every act is timed into a SmokeClock (until its outputs are ready)."""

    def __init__(self, model, name, clock):
        self._model, self._name, self._clock = model, name, clock

    def act(self, params, key, obs, *args, **kwargs):
        import jax
        start = self._clock.now()
        out = jax.block_until_ready(self._model.act(params, key, obs, *args, **kwargs))
        self._clock._pass(self._name, np.shape(obs)[0], self._clock.now() - start)
        return out

    def __getattr__(self, name):
        return getattr(self._model, name)


def full_shapes(rows):
    """{player: the network row counts (2 per environment) it plays in rows' calls}: the full schedule's are 1024
    (512 pairs, head to head) and 512 (256 pairs, panel and ladder)."""
    out = {}
    for idx in call_groups(rows):
        for name in (str(rows["arm"][idx[0]]), str(rows["opponent"][idx[0]])):
            out.setdefault(name, set()).add(2 * int(idx.size))
    return out


def smoke_report(games, counts, seconds, *, jit_seconds, warm_games_per_second, total=None):
    """The smoke's report and status. forecast_seconds = jit_seconds (the full run's estimated JIT,
    SmokeClock.jit_estimate) + total games at the warm rate (calls that compiled nothing); an upper bound, since
    the smoke's batches of 1-2 games run slower per game than the run's 256-512. STOP for any cut-off or refused
    game, a warm rate below SMOKE_MIN_RATE (or none measured), or a forecast above SMOKE_MAX_FORECAST; else GO.
    games_per_second (every smoke call, its compiles included) is reported, never a rule."""
    from duoforge_search import expert_eval
    total = expert_eval.GAMES if total is None else total
    warm = warm_games_per_second
    forecast = None if warm is None else float(jit_seconds + total / warm)
    reasons = []
    if counts["cutoffs"]:
        reasons.append(f"{counts['cutoffs']} cut-off games (unfinished at the step limit)")
    if counts["refused"]:
        reasons.append(f"{counts['refused']} games refused by the engine")
    if warm is None:
        reasons.append("no warm call (one that compiled nothing) to measure a rate")
    elif warm < SMOKE_MIN_RATE:
        reasons.append(f"{warm:.3f} warm games/s is below {SMOKE_MIN_RATE}")
    if forecast is not None and forecast > SMOKE_MAX_FORECAST:
        reasons.append(f"the forecast {forecast:.0f} s (JIT {jit_seconds:.0f} s + {total} games at {warm:.3f} "
                       f"games/s) exceeds {SMOKE_MAX_FORECAST:.0f} s")
    return {"games": int(games), "seconds": float(seconds),
            "games_per_second": float(games / seconds) if seconds > 0 else None,
            "warm_games_per_second": None if warm is None else float(warm), "jit_seconds": float(jit_seconds),
            "forecast_seconds": forecast, "forecast_is_upper_bound": True, "jit_is_estimate": True,
            "forecast_games": int(total),
            "cutoffs": int(counts["cutoffs"]), "refused": int(counts["refused"]),
            "status": "STOP" if reasons else "GO", "stop_reasons": reasons}


def records_json(records):
    """records as JSON values in expert_eval's exact types: integers, strings, booleans, score a float or null."""
    from duoforge_search import expert_eval
    out = {}
    for name in expert_eval.RECORD_FIELDS:
        values = np.asarray(records[name]).tolist()
        if name == "score":
            values = [None if math.isnan(v) else float(v) for v in values]
        out[name] = values
    return out


def records_bytes(records):
    """The canonical bytes of records (sorted keys, compact): the deterministic part of the output."""
    return json.dumps(records_json(records), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _load_json(path):
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"nonfinite JSON {c}")))


def _checkpoint_args(values):
    paths = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or not path:
            raise ValueError(f"--checkpoint takes NAME=PATH (got {value!r})")
        if name in paths:
            raise ValueError(f"checkpoint {name} is named twice")
        paths[name] = path
    return paths


def _require_deterministic(jax):
    """ValueError on a GPU without deterministic XLA ops (the arena's requirement, spec section 6)."""
    from duoforge_search import arena
    try:
        arena.require_deterministic_gpu(jax)
    except SystemExit as err:
        raise ValueError(str(err)) from None


def main(argv=None):
    """python -m duoforge_learn.p1_eval --manifest M --checkpoint NAME=PATH (each of expert_eval.CHECKPOINTS)
    --teams IDS [--team-weights W] [--teams-root R] --out O [--ledger L] [--workers N] [--smoke].
    Exit 2 with the cause for a refusal before play (paths inside the repository, an existing --out, a checkpoint
    hash, layout, data kind or ids, a pool or schedule that is not the manifest's, a GPU without deterministic ops);
    exit 0 after writing --out: the baseline file, or with --smoke the smoke report (its status GO or STOP). An
    error during play is a crash (exit 1) and writes no --out. Once the ledger exists it is saved in every case."""
    from duoforge_search import expert_eval
    parser = argparse.ArgumentParser(prog="python -m duoforge_learn.p1_eval",
                                     description="Stage 3 P1 evaluation games (expert_eval's --baseline file).")
    parser.add_argument("--manifest", required=True, help="the evaluation manifest (expert_eval.EvalManifest)")
    parser.add_argument("--checkpoint", action="append", default=[], required=True,
                        help=f"NAME=PATH, once for each of {', '.join(expert_eval.CHECKPOINTS)}")
    parser.add_argument("--teams", required=True, help="the evaluation pool's registry team ids, comma-separated")
    parser.add_argument("--team-weights", default=None, help="their weights, comma-separated")
    parser.add_argument("--teams-root", default="data/teams", help="the team registry")
    parser.add_argument("--out", required=True, help="the file to write, outside the repository")
    parser.add_argument("--ledger", default=None, help="the evaluation's compute ledger file (phase evaluate)")
    parser.add_argument("--workers", type=int, default=1, help="native workers of each call's batch")
    parser.add_argument("--smoke", action="store_true",
                        help=f"the predeclared {SMOKE_GAMES}-game smoke: a report with GO or STOP, no records")
    args = parser.parse_args(argv)
    try:
        from duoforge_replay.dataset import refuse_repository
        from . import ledger as ledger_mod
        refuse_repository(args.out)
        if os.path.exists(args.out):
            raise ValueError(f"{args.out} exists: the evaluation output is written once")
        if args.workers < 1:
            raise ValueError("--workers must be at least 1")
        book = ledger_mod.Ledger(args.ledger)
    except (ValueError, OSError) as err:
        print(f"p1_eval: {err}", file=sys.stderr)
        return 2
    context = None
    try:  # from here on every outcome is charged to the ledger
        try:
            import jax
            from duoforge import teams
            from .train import DATA_KINDS
            _require_deterministic(jax)
            manifest = expert_eval.EvalManifest(**_load_json(args.manifest))
            loaded = load_checkpoints(_checkpoint_args(args.checkpoint), manifest)
            kind = data_kind(loaded)
            if kind not in DATA_KINDS:
                raise ValueError(f"unknown data kind {kind!r}")
            context = duoforge.Context(data_kind=DATA_KINDS[kind])
            weights = None if args.team_weights is None else [float(w) for w in args.team_weights.split(",")]
            pool = teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root,
                              weights=weights)
            rows = expert_eval.make_eval_rows(pool, manifest)  # the manifest's pool and blocks, or ValueError
            shapes = full_shapes(rows)
            if args.smoke:
                rows = {k: v[smoke_indices(rows)] for k, v in rows.items()}
            call_groups(rows)
            players = make_players(loaded, context, book)
            clock = None
            if args.smoke:
                clock = SmokeClock()
                for name, player in players.items():
                    player.model = clock.wrap(name, player.model)
            tracker = expert_eval.TrickRoomTracker(context)
        except (ValueError, OSError, KeyError, TypeError) as err:
            print(f"p1_eval: {err}", file=sys.stderr)
            return 2
        start = time.perf_counter()
        with book.phase(PHASE):
            records, counts = play_rows(context, pool, rows, players, workers=args.workers, max_steps=MAX_STEPS,
                                        tracker=tracker, clock=clock)
        seconds = time.perf_counter() - start
    finally:
        if context is not None:
            context.close()
        if book.path is not None:
            book.save()
    totals = book.totals() if book.path is None else json.loads(book.path.read_text())
    expert_eval.ComputeLedger.from_mapping(totals)  # the form expert_eval reads
    games = int(records["finished"].size)
    if args.smoke:
        out = {**smoke_report(games, counts, seconds, jit_seconds=clock.jit_estimate(shapes),
                              warm_games_per_second=clock.warm_rate()), "ledger": totals,
               "encoders": {name: int(p.encoder) for name, p in players.items()}}
    else:
        out = {"records": records_json(records), "ledger": totals}
    data = json.dumps(out, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with open(args.out, "x", encoding="ascii") as f:
        f.write(data)
    print(json.dumps({"games": games, "finished": int(records["finished"].sum()), **counts,
                      "seconds": round(seconds, 3), "encoders": {name: int(p.encoder) for name, p in players.items()},
                      **({"status": out["status"]} if args.smoke else {})}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
