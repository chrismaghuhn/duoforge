"""The stage 3 P1 evaluation games (decision 0024; P1 plan C5, Learner v2 side): the runner that plays M12's
predeclared schedule and writes the records duoforge_search.expert_eval reads. expert_eval plays nothing; this
module plays everything and decides nothing about the gate.

- The games: expert_eval.make_eval_rows(pool, manifest), all 12288 of them (checked there against the manifest's
  pool and block hashes), in game-id order. For each row the student is the row's arm checkpoint (pilot or
  control) and the opponent the row's opponent checkpoint (control, frozen, BC, 3600, 11000 or ladder), with the
  row's student_team on student_seat and opponent_team on the other seat.
- The seed: a row's battle is evaluate.play_suite's single game seeded with the row's seed, i.e. episode 1 of
  environment 0 of a batch seeded with it. The engine derives a battle's RNG from (batch seed, environment,
  episode) (duoforge_batch_seeds), so games of different seeds can share no batch, and every row is its own
  play_suite call: the two seats of a pair (the same seed) play the same battle RNG, and a game depends on its row
  alone, never on grouping or order.
- The players: raw greedy play for both sides (book and preview search off, as the manifest pins), each
  checkpoint a Player in the encoder layout it was trained with (checkpoint.load_trained / trained_model, never
  widened: P1's are encoder 4; an older format-2 layout is served by its own encoder through Batch.query_encoded).
  A checkpoint load_trained cannot read (format 1, a feature list that is not its encoder's layout) is refused, as
  is a file whose SHA-256 is not the one the manifest pins for its name, checkpoints of different data kinds, and
  one whose embedded ids do not mean the same rows under the evaluation's tables (checkpoint.check_ids).
- The records (expert_eval.RECORD_FIELDS): the schedule fields, score (the student's: 1 win, 0.5 tie, 0 loss) and
  finished, and the Trick Room diagnostic's TR_FIELDS from an expert_eval.TrickRoomTracker observing every game.
  A game the engine refused (E_UNSUPPORTED) or cut off at MAX_STEPS (tiebreak-resolved or not) is finished =
  False with score null (NaN): play_suite records both as unfinished or unresolved.
- The output: {"records": ..., "ledger": ...}, expert_eval main's --baseline file, written once (never over an
  existing file) outside the repository. The records part is canonical JSON: the same inputs give the same bytes.
  The ledger (duoforge_learn.ledger, phase "evaluate") is the shared evaluation cost: a --ledger file sums every
  process that ran into it (the smoke, restarts); GPU-seconds count only the network passes on a non-CPU device.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time

import numpy as np

import duoforge

from . import evaluate, suite

MAX_STEPS = 1000  # play_suite's cut-off; a cut game is unfinished
PHASE = "evaluate"


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
    """{name: (params, config, sha256)} of every checkpoint the manifest pins, read in its own layout;
    ValueError for a missing or extra name, a SHA-256 the manifest does not pin for that name, or a file
    load_trained refuses."""
    from duoforge_search import expert_eval
    from . import checkpoint
    if set(paths) != set(expert_eval.CHECKPOINTS):
        raise ValueError(f"name exactly the checkpoints {expert_eval.CHECKPOINTS} (got {sorted(paths)})")
    out = {}
    for name in expert_eval.CHECKPOINTS:
        sha = file_sha256(paths[name])
        if sha != manifest.checkpoints[name]:
            raise ValueError(f"checkpoint {name}: {paths[name]} has SHA-256 {sha}, the manifest pins "
                             f"{manifest.checkpoints[name]}")
        params, config = checkpoint.load_trained(paths[name])
        checkpoint.ext_supported_of(config)  # a mask its encoder has no columns for is refused here
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


def suite_row(rows, i):
    """play_suite's row (suite.SUITE, (1,)) of schedule row i: the student's team on its seat."""
    seat = int(rows["student_seat"][i])
    student, foe = int(rows["student_team"][i]), int(rows["opponent_team"][i])
    out = np.zeros(1, dtype=suite.SUITE)
    out["side0"], out["side1"] = (student, foe) if seat == 0 else (foe, student)
    out["learner_seat"] = seat
    return out


def play_rows(context, pool, rows, players, *, workers=1, max_steps=MAX_STEPS, tracker=None):
    """The records (expert_eval.RECORD_FIELDS arrays) of schedule rows (SCHEDULE_FIELDS arrays, any subset of
    make_eval_rows'), each row one play_suite game: rows["arm"] against rows["opponent"] of players, seeded with
    rows["seed"], with tracker (an expert_eval.TrickRoomTracker, made for context when None) observing it."""
    from duoforge_search import expert_eval
    if tracker is None:
        tracker = expert_eval.TrickRoomTracker(context)
    n = int(rows["game_id"].size)
    out = {name: np.asarray(rows[name]).copy() for name in expert_eval.SCHEDULE_FIELDS}
    out["score"] = np.full(n, math.nan)
    out["finished"] = np.zeros(n, dtype=bool)
    for name in expert_eval.TR_FIELDS:
        out[name] = np.zeros(n, dtype=np.int64)
    for i in range(n):
        student, opponent = players[str(rows["arm"][i])], players[str(rows["opponent"][i])]
        record = evaluate.play_suite(context, pool, suite_row(rows, i), student, opponent, workers,
                                     int(rows["seed"][i]), max_steps=max_steps, observers=(tracker,))[0]
        finished = not (record["unfinished"] or record["unresolved"])
        out["finished"][i] = finished
        if finished:
            out["score"][i] = (int(record["result"]) + 1) / 2.0  # +1 win, 0 tie, -1 loss -> 1, 0.5, 0
        fields = tracker.fields
        for name in expert_eval.TR_FIELDS:
            out[name][i] = int(fields[name][0])
    return out


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


def main(argv=None):
    """python -m duoforge_learn.p1_eval --manifest M --checkpoint NAME=PATH (each of expert_eval.CHECKPOINTS)
    --teams IDS [--team-weights W] [--teams-root R] --out O [--ledger L] [--workers N] [--games N].
    Exit 2 with the cause for a refusal before play (paths inside the repository, an existing --out, a checkpoint
    hash, layout or data kind, a pool or schedule that is not the manifest's); exit 0 after writing --out. An error
    during play is a crash (exit 1) and writes nothing. --games N plays only the first N games in game-id order (a
    smoke; whole seat pairs, so N is even): expert_eval then reports the missing blocks INCOMPLETE."""
    from duoforge_search import expert_eval
    parser = argparse.ArgumentParser(prog="python -m duoforge_learn.p1_eval",
                                     description="Stage 3 P1 evaluation games (expert_eval's --baseline file).")
    parser.add_argument("--manifest", required=True, help="the evaluation manifest (expert_eval.EvalManifest)")
    parser.add_argument("--checkpoint", action="append", default=[], required=True,
                        help=f"NAME=PATH, once for each of {', '.join(expert_eval.CHECKPOINTS)}")
    parser.add_argument("--teams", required=True, help="the evaluation pool's registry team ids, comma-separated")
    parser.add_argument("--team-weights", default=None, help="their weights, comma-separated")
    parser.add_argument("--teams-root", default="data/teams", help="the team registry")
    parser.add_argument("--out", required=True, help="the baseline file to write, outside the repository")
    parser.add_argument("--ledger", default=None, help="the evaluation's compute ledger file (phase evaluate)")
    parser.add_argument("--workers", type=int, default=1, help="native workers of each game's batch")
    parser.add_argument("--games", type=int, default=None, help="smoke: only the first N games (N even)")
    args = parser.parse_args(argv)
    context = None
    try:
        from duoforge import teams
        from duoforge_replay.dataset import refuse_repository
        from . import ledger as ledger_mod
        from .train import DATA_KINDS
        refuse_repository(args.out)
        if os.path.exists(args.out):
            raise ValueError(f"{args.out} exists: the evaluation output is written once")
        if args.workers < 1:
            raise ValueError("--workers must be at least 1")
        book = ledger_mod.Ledger(args.ledger)
        manifest = expert_eval.EvalManifest(**_load_json(args.manifest))
        loaded = load_checkpoints(_checkpoint_args(args.checkpoint), manifest)
        kind = data_kind(loaded)
        if kind not in DATA_KINDS:
            raise ValueError(f"unknown data kind {kind!r}")
        context = duoforge.Context(data_kind=DATA_KINDS[kind])
        weights = None if args.team_weights is None else [float(w) for w in args.team_weights.split(",")]
        pool = teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root, weights=weights)
        rows = expert_eval.make_eval_rows(pool, manifest)  # the manifest's pool and blocks, or ValueError
        if args.games is not None:
            if args.games < 2 or args.games % 2 or args.games > rows["game_id"].size:
                raise ValueError(f"--games must be even, from 2 to {rows['game_id'].size} (got {args.games})")
            rows = {k: v[:args.games] for k, v in rows.items()}
        players = make_players(loaded, context, book)
        tracker = expert_eval.TrickRoomTracker(context)
    except (ValueError, OSError, KeyError, TypeError) as err:
        print(f"p1_eval: {err}", file=sys.stderr)
        if context is not None:
            context.close()
        return 2
    try:
        start = time.perf_counter()
        with book.phase(PHASE):
            records = play_rows(context, pool, rows, players, workers=args.workers, max_steps=MAX_STEPS,
                                tracker=tracker)
        seconds = time.perf_counter() - start
    finally:
        context.close()
        if book.path is not None:
            book.save()  # a crashed attempt is charged too
    totals = book.totals() if book.path is None else json.loads(book.path.read_text())
    baseline = {"records": records_json(records), "ledger": totals}
    expert_eval.ComputeLedger.from_mapping(baseline["ledger"])  # the form expert_eval reads
    data = json.dumps(baseline, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with open(args.out, "x", encoding="ascii") as f:
        f.write(data)
    finished = records["finished"]
    print(json.dumps({"games": int(finished.size), "finished": int(finished.sum()), "seconds": round(seconds, 3),
                      "encoders": {name: int(p.encoder) for name, p in players.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
