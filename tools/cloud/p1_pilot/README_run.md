# Stage 3 P1 pilot: the run script

`run.sh` runs the P1 pilot ([pilot plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md),
[Learner v2 plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-learner.md)) without interaction on one GPU
machine. A launcher starts it after checking out a fixed commit. It does not create instances, and its only AWS calls
are `aws s3 cp/sync/ls`.

| File | Purpose |
| --- | --- |
| `run.sh` | the run, `--on-interrupt`, `--dry-run` and `--check-env` |
| `p1_manifest.py` | writes the collector's `DataManifest` with the hashes the collector CLI checks; `freeze` computes the production rounds from the smoke |
| `p1_match.py` | compute matching of the control: from the calibration updates, the update GPU share q and the resume flags |
| `p1_export.py` | the control's final parameters from its run state as a format-2 checkpoint (a budget stop writes no snapshot) |
| `test_p1_tools.py` | offline tests: `p1_match.solve`, `p1_manifest.freeze`, the RUN_ID guard (`python tools/cloud/p1_pilot/test_p1_tools.py`) |

## Environment

| Variable | Meaning |
| --- | --- |
| `BUCKET`, `RUN_PREFIX`, `RUN_ID` | required for a run. `RUN_ID` is one path segment: letters, digits, `.`, `_`, `-`, no leading `.`, not `inputs`. `RUN_PREFIX` must be exactly `p1/<RUN_ID>/`. `run.sh --check-env` checks these alone (no file, no aws call) |
| `DUOFORGE_COMMIT` | the commit the launcher checked out. It must equal `git HEAD` when the source is a checkout, and it is required when it is not |
| `WORKERS` | native workers, 4, 8 or 14 (default 14, the frozen probe result for 16 vCPU) |
| `AFFINITY` | `taskset` CPU list for every phase of both arms (default `0-(WORKERS-1)`) |
| `LADDER_FILE` | the ladder checkpoint among the inputs (default `params-39400.npz`, M12 2026-10-09) |
| `TEAMS_DIR` | the team registry directory among the inputs (default `teams`) |
| `WORK_DIR` | work directory outside the repository (default `~/p1-work`, dry run `~/p1-dry/work`). Outputs are in `$WORK_DIR/out`. The tools' states hold absolute paths, so a resume must use the same `WORK_DIR`. Every start records `work_dir`, `run_id` and `mode` in run-info; a start whose earlier run-info differs in any of them (another WORK_DIR, a new RUN_ID, a run after a dry run in the same directory) stops with 11, so it never inherits markers or outputs. `--check-env` with `WORK_DIR` set also checks this |
| `VENV` | an existing Python environment to use instead of creating `$WORK_DIR/venv` |
| `UPLOAD_EVERY`, `INTERRUPT_WAIT` | periodic upload interval (900 s); how long an interrupt waits for the phase to save (60 s) |

There are no secrets in the script. AWS credentials come from the machine's instance profile.

**Inputs** are taken from `s3://$BUCKET/p1/inputs/`:
- `params-49333.npz` (frozen, init and reference), `params-0.npz` (BC), `params-3600.npz`, `params-11000.npz`, `$LADDER_FILE`;
- `teams.txt`, `team_weights.txt` (one comma-separated line each);
- the registry `teams/`;
- `SHA256SUMS` (`sha256sum` format, paths relative to the inputs directory).

Before any phase, `SHA256SUMS` must list exactly the files present, and every file must match. `params-49333.npz` must
also match the pinned hash `ef1abe65…961cb`.

**Setup:**
- Builds `duoforge_shared` (CMake Release) in `$WORK_DIR/build`.
- Creates a Python 3.12 venv with `numpy==2.5.3`, `jax[cuda12]==0.11.2` and `optax==0.2.8`. These are all the
  third-party modules `python/` imports. The versions are verified, and JAX's default device must be a GPU.
- Requires M12's `duoforge_search.eval_manifest` to import from the checked-out commit; without it the run stops
  with 50 before any phase, so no run mixes commits.
- Sets one shared base environment for every phase: `DUOFORGE_LIBRARY`, `PYTHONPATH=<repo>/python`,
  `PYTHONDONTWRITEBYTECODE=1`, `XLA_FLAGS=--xla_gpu_deterministic_ops=true`, `XLA_PYTHON_CLIENT_PREALLOCATE=false`,
  `OMP_NUM_THREADS=4`, `OPENBLAS_NUM_THREADS=4`. It unsets `JAX_PLATFORMS`, `XLA_PYTHON_CLIENT_MEM_FRACTION`,
  `XLA_PYTHON_CLIENT_ALLOCATOR`, `JAX_ENABLE_X64` and `CUDA_VISIBLE_DEVICES`.
- Adds per phase (`PHASE_ENV_*` in `run.sh`):

  | Phases | Added | Why |
  | --- | --- | --- |
  | collector smoke and production, manifest writes | `JAX_PLATFORMS=cpu` | the manifest pins `device: cpu` |
  | training of both arms: distill; the control's calibration and matched run | `XLA_PYTHON_CLIENT_ALLOCATOR=platform` | see below; both arms' training shares it, so their GPU-seconds compare fairly |
  | evaluation: `eval_manifest`, `p1_eval` smokes and full run | nothing (JAX's default pool allocator) | a shared phase, charged half to each arm, so its allocator does not bias the comparison; the pool allocator is fast (dry run: 242 games/s at full width, against 47 with the platform allocator) |

- Why the platform allocator for training: with the default pool allocator and no preallocation, distill's held-out
  evaluation (`_eval_sums`, 4096 rows) leaves its grown pool reserved. Loading the next kernel (`jit__step`) then fails
  with "Failed to load in-memory CUBIN ... CUDA_ERROR_OUT_OF_MEMORY" on the 8 GB 4060 Ti. Measured on 2026-10-09
  (v2-M, encoder 4, 4096 rows, one fresh process each):
  - eval then step, deterministic: fails;
  - the same with `jax.clear_caches()` between: fails;
  - step alone: passes;
  - eval then step without deterministic ops: passes, but gives up determinism;
  - eval then step with the platform allocator: passes, about 0.24 s per step slower.
- Logs the environment and writes `run-info/run-info-<start>.json` on every start. That file holds: commit, work
  directory, versions (pip freeze), devices, CPU, GPU, compiler, seeds, the base and per-phase environment and the
  input hashes.

## Phases

Every phase writes `out/markers/<phase>.done` and uploads. A restart first restores `s3://$BUCKET/$RUN_PREFIX` into
`out/`, skips phases that are done, and resumes an interrupted collector, distill or train run from its own state. A
directory left without a resumable state is moved to `<dir>.aside-<time>`, never deleted.

0. **Pre-training evaluation smoke** (shared ledger `ledgers/eval.json`): `eval_manifest` and `p1_eval --smoke` with
   params-49333 standing in for pilot and control (the other checkpoints as pinned), in `eval-pretrain/`. It checks
   the evaluation's throughput, JIT and cut-offs before any training spend, and anything but GO stops the run (40).
   Its manifest `eval-pretrain/manifest.json` is never used for the gate.
1. **Collection** (pilot ledger `ledgers/pilot.json`, phase `generate`).
   - **Smoke:** its own manifest (`manifests/smoke.json`, 1 round = 512 games, `first_game_id` 0), charged to the pilot ledger.
   - **Freeze:** `p1_manifest.py freeze` writes `manifests/freeze.json` with
     `R = ceil(1.25 * 16384 / (512 t))`, where `t` is targets per game. It STOPs on any of these:
     - `t = 0`;
     - a forecast of generation CPU above 28800 core-seconds (smoke CPU × (1 + 512R / smoke games));
     - primary work fallbacks above 1 % of the selected roots.
   - **Production:** `manifests/production.json` (`first_game_id` 512, R rounds). After it, the script checks again:
     fallbacks, actual generation CPU ≤ 28800, and targets ≥ 16384. It then writes the shard list
     `collect-production/shards.sha256`.
   - Seeds: `0x2026100900000101`, split `0x2026100900000102`.
2. **Distillation** (pilot ledger): `distill --init/--reference params-49333 --shards collect-production/data/shards`,
   giving `distill/params-best.npz`.
3. **Control** (`ledgers/control.json`):
   - **Recipe:** `train --init params-49333 --keep-init-encoder` with magnet + LR decay and `--eval-every 100000`.
     The script also passes `--eval-budget 1`: a stop by `--updates` (the end of each calibration block) plays the
     run's two end suites, and this keeps them at one game each (charged to the control's CPU).
   - **Calibration:** 6 updates with `--update-gpu-share 0`, then a resume to 12 with `--update-gpu-share 1`. Acting
     is on the CPU throughout (`--act-gpu-share 0`). Each block is marked done only when the saved run state holds
     exactly 6 (12) updates; a block cut short (a signal, the `--minutes` default) stops the start, and the next
     start resumes it.
   - **Matching:** `p1_match.py` writes `control/match.json`. It STOPs when the calibration spent more than 10 % of
     either pilot axis (33), or when no share q in [0, 1] hits both axes (INFEASIBLE, 30).
     - **Calibrate more:** p1_match skips each process's first update (its JIT). When a device is left with no warm
       update (interrupts during a short block), it exits 5 and names the device. The script then plays one extra
       block on that device: its own process of 2 updates (one JIT, one warm), recorded in
       `control/extra-calibration.json`. Then it runs p1_match again. At most 3 extra blocks per device, else STOP 30.
       Extra blocks are charged to the control and count against the 10 % cap.
     - Otherwise the script
     resumes with its flags: q, the pilot totals as ledger stops, `--updates 0`, a `--minutes` safety cap of twice
     the forecast, and `--learning-rate-schedule 0:1,D:0.1`.
   - **Budget stop:** "reached" is decided from the restored control ledger (saved with the run state) against the
     stops in `match.json`; a run that ends without reaching them stops with 32.
   - **Export:** `p1_export.py` writes `control/params-final.npz`.
   - **Check:** `expert_eval.validate_compute` compares both ledgers (5 % per axis) and writes
     `control/compute-check.json`.
4. **Evaluation** (shared ledger `ledgers/eval.json`, in `eval/`):
   - **Manifest:** `python -m duoforge_search.eval_manifest` (M12; seed `0x2026100900000301`, `first_game_id`
     1000000000) with the checkpoints pilot = distill best, control = the export, frozen, BC, 3600, 11000 and ladder.
   - **Smoke:** `p1_eval --smoke` on the real students. Anything but GO stops the run.
   - **Full run:** `p1_eval`, giving `eval/B.json`.
   - **Report:** `expert_eval`, giving `eval/REPORT.json` (its exit 2 is 41, any other failure a crash).

**Uploads.** Everything in `out/` goes to `s3://$BUCKET/$RUN_PREFIX` as `sync --delete`. The local tree is the
authoritative state after the restore; without a completed restore (`.restored` is reset on every start) only the
logs are uploaded, under `logs-unrestored/`.
- What `out/` holds: manifests, ledgers, logs (`logs/run-<start>.log` per start, one log per phase, `timings.jsonl`),
  run-info, shards and their SHA list, distill and control run directories (final params of both arms), evaluation
  records and reports, and `STATUS.json`.
- When uploads happen: after every phase, every `UPLOAD_EVERY` seconds, and at exit, including on failure. At exit
  the script first waits (up to `INTERRUPT_WAIT` s) for a running phase to save, and closes its log, then uploads.

**Interrupts.** `run.sh --on-interrupt` is run by the launcher with the same environment. It marks the run
interrupted, SIGTERMs the running phase process (collector, distill and train save on it), uploads at once, waits up
to `INTERRUPT_WAIT` s, uploads again and exits 0. A SIGTERM or SIGINT to `run.sh` itself does the same from inside.
Once the run is marked interrupted, no phase starts and the phase that was running counts as interrupted, whatever its
exit code (train answers SIGTERM by saving and exiting 0): `run.sh` exits 60, and the next start resumes.

## Deviations from the plans (agreed 2026-10-09)

- **Evaluation smoke before training.** Plan C5 asks for the 64-game evaluation smoke to verify throughput "before
  training". The real smoke needs the trained students, so the run plays it twice: before any training with
  params-49333 standing in for pilot and control (phase 0, a separate manifest never used for the gate), and again
  after training with the real students (phase 4). Both are charged to the shared evaluation ledger.
- **Calibration first, with acting on the CPU (p = 0).** The Learner v2 plan forecasts the shares (q, p) from unit
  costs before any GPU spend. Here the calibration (6 CPU + 6 GPU updates of the control itself) is the measurement:
  p is fixed at 0, q is solved from the measured costs, and the calibration is capped at 10 % of each pilot axis
  (STOP 33 above it). A q outside [0, 1] would need acting on the GPU: INFEASIBLE (30), back to the owner.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | done (the run: REPORT.json written; dry run: rehearsal complete) |
| 1 | crash (a tool error, a failed export or check, a calibration block cut short, expert_eval crash) |
| 2 | usage (missing or invalid environment, bad arguments) |
| 10 | inputs: a file missing (the ladder too), SHA256SUMS not exact, any hash mismatch |
| 11 | setup: a tool, build, venv, version pin or GPU missing; commit mismatch; earlier starts in WORK_DIR with another work_dir, run_id or mode |
| 13 | a phase CLI refused its inputs (exit 2) |
| 20 | smoke STOP: t = 0 |
| 21 | STOP: forecast or actual generation CPU above 28800 core-seconds |
| 22 | STOP: primary work fallbacks above 1 % |
| 23 | production incomplete: fewer than 16384 targets (re-plan) |
| 30 | matching infeasible, or still no warm calibration update after 3 extra blocks on a device (`control/match.json`) |
| 31 | compute mismatch above 5 % (`control/compute-check.json`) |
| 32 | the control ended without reaching its ledger budget |
| 33 | the calibration spent more than 10 % of a pilot axis (`control/match.json`) |
| 40 | evaluation smoke STOP (pre-training or post-training) |
| 41 | expert_eval refused (exit 2) |
| 50 | M12's `duoforge_search.eval_manifest` does not import from the commit (checked in setup) |
| 60 | interrupted (signal or `--on-interrupt`); the next start resumes |

## Dry run

`run.sh --dry-run LOCAL_INPUTS_DIR` makes no aws call (the S3 wrapper refuses one). It reads the inputs in place,
checking them exactly as above, and writes to `$WORK_DIR/out`.
- **Pre-training smoke:** as in the run (STOP 40).
- **Collection:** the collector smoke only (1 round of 512 games, the size the manifest pins). Then the freeze. A
  t = 0 stops; a budget or fallback STOP is only reported.
- **Distillation:** on the smoke's shards with the smoke manifest. `DRY_DISTILL_DEVICE=cpu` (dry run only; a run
  refuses it with 2) puts it on the CPU.
- **Control:** calibration 3 + 3 updates (a block keeps a warm update through one interrupt), then `p1_match.py`
  with its extra calibration blocks as in the run.
  - **Dry-run-only stand-in:** a matching STOP (INFEASIBLE, over the 10 % cap, extras exhausted) is only reported.
    It is expected, because the pilot ledger has no production. The rehearsal then goes on without the matched run:
    the export takes the calibrated state, and the compute check is only reported. A run always stops there.
- **Evaluation:** the manifest and the `p1_eval` smoke on the real students. The run exits 0 on GO and 40 on STOP.
