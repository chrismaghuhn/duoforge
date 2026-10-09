# Stage 3 P1 pilot: the run script

`run.sh` runs the P1 pilot ([pilot plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md),
[Learner v2 plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-learner.md)) without interaction on one GPU
machine. A launcher starts it after checking out a fixed commit. It does not create instances, and its only AWS calls
are `aws s3 cp/sync/ls`.

| File | Purpose |
| --- | --- |
| `run.sh` | the run, `--on-interrupt`, `--dry-run` and `--check-env` |
| `p1_manifest.py` | writes the collector's `DataManifest` with the hashes the collector CLI checks; `freeze` computes the production rounds from the smoke |
| `p1_export.py` | the control's final parameters from its run state as a format-2 checkpoint (a budget stop writes no snapshot) |
| `test_p1_tools.py` | offline tests: `p1_manifest.freeze`, the RUN_ID guard (`python tools/cloud/p1_pilot/test_p1_tools.py`) |

## Environment

| Variable | Meaning |
| --- | --- |
| `BUCKET`, `RUN_PREFIX`, `RUN_ID` | required for a run. `RUN_ID` is one path segment: letters, digits, `.`, `_`, `-`, no leading `.`, not `inputs`. `RUN_PREFIX` must be exactly `p1/<RUN_ID>/`. `run.sh --check-env` checks these alone (no file, no aws call) |
| `PILOT_RUN_ID` | optional: take the pilot arm (phases 1-2) from that earlier run, read only, instead of playing them (see "Pilot from an earlier run"). Same format as `RUN_ID`, and another run. The launcher's `--from-run` sets it |
| `DRY_PILOT_DIR` | the same for a dry run: the `out/` directory of an earlier dry run (dry run only) |
| `DUOFORGE_COMMIT` | the commit the launcher checked out. It must equal `git HEAD` when the source is a checkout, and it is required when it is not |
| `WORKERS` | native workers, 4, 8 or 14 (default 14, the frozen probe result for 16 vCPU) |
| `AFFINITY` | `taskset` CPU list for every phase of both arms (default `0-(WORKERS-1)`) |
| `LADDER_FILE` | the ladder checkpoint among the inputs (default `params-39400.npz`, M12 2026-10-09) |
| `TEAMS_DIR` | the team registry directory among the inputs (default `teams`) |
| `WORK_DIR` | work directory outside the repository (default `~/p1-work`, dry run `~/p1-dry/work`). Outputs are in `$WORK_DIR/out`. The tools' states hold absolute paths, so a resume must use the same `WORK_DIR`. Every start records `work_dir`, `run_id`, `mode` and `pilot_source` in run-info; a start whose earlier run-info differs in any of them (another WORK_DIR, a new RUN_ID, a run after a dry run in the same directory) stops with 11, so it never inherits markers or outputs. `--check-env` with `WORK_DIR` set also checks this |
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
  | training of both arms: distill; the control | `XLA_PYTHON_CLIENT_ALLOCATOR=platform` | see below; both arms' training shares it, so their GPU-seconds compare fairly |
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
3. **Control** (`ledgers/control-fresh.json`, in `control-fresh/`; owner decision 2026-10-09):
   - **Recipe:** `train --init params-49333 --keep-init-encoder` with magnet + LR decay and `--eval-every 100000`,
     acting on the CPU (`--act-gpu-share 0`). One run from the start, no calibration.
   - **Budget matching:** `--update-gpu-share match` with the pilot's totals as `--stop-cpu-core-seconds` and
     `--stop-gpu-seconds` (`duoforge_learn.budget_match`). Before every update the ledger decides the device: the
     GPU axis first (GPU updates until it reaches 95 %, then CPU updates; only a GPU update raises it, and its first
     update in a process pays a JIT of about 22 % of the axis), and only a device whose expected
     step keeps both axes at 105 % or below. The expected step is the most expensive one measured for that device,
     the first one of a process (JIT, start-up) until the device ran in this process; an unmeasured step counts as
     25 % of each axis it spends. The run stops `matched` when both axes reach 95 %, or `incomplete` when no device
     fits, or the GPU axis is below 95 % and no GPU update fits (STOP 30, re-plan). Restarts and JIT are absorbed:
     a resumed process reads the measured steps from the run's log; only a restart in the last updates of the GPU
     phase (GPU axis 83-95 %) cannot fit its JIT. The run plays no end suites (its ledger is training only). The
     device sequence depends on measured costs; each update logs it (`update_device`, `match`).
   - **Learning rate:** `--learning-rate-over budget --learning-rate-schedule 0:1,900:0.1`: the decay runs over the
     CPU budget spent (permille), so it ends at 90 % of the run without a forecast.
   - **Safety:** `--minutes 90` per process. A run that ends without `matched` or `incomplete` stops with 32, and
     the next start resumes it. A stop counts only when the saved run state holds the update of that log line (the
     log can be uploaded before the state is saved); otherwise the next start resumes the saved state.
   - **Export:** `p1_export.py` writes `control-fresh/params-final.npz`.
   - **Check:** `expert_eval.validate_compute` compares both ledgers (5 % per axis) and writes
     `control-fresh/compute-check.json` (31 on a mismatch).
   - Runs before 2026-10-10 used a calibration and `p1_match.py` (an update share q forecast once); its control
     (`control/`, `ledgers/control.json`) is left as it is.
4. **Evaluation** (shared ledger `ledgers/eval.json`, in `eval/`):
   - **Manifest:** `python -m duoforge_search.eval_manifest` (M12; seed `0x2026100900000301`, `first_game_id`
     1000000000) with the checkpoints pilot = distill best, control = the export, frozen, BC, 3600, 11000 and ladder.
   - **Smoke:** `p1_eval --smoke` on the real students. Anything but GO stops the run.
   - **Full run:** `p1_eval`, giving `eval/B.json`.
   - **Report:** `expert_eval`, giving `eval/REPORT.json` (its exit 2 is 41, any other failure a crash).

**Uploads.** Everything in `out/` goes to `s3://$BUCKET/$RUN_PREFIX` as `sync --delete`. The local tree is the
authoritative state after the restore; without a completed restore (`.restored` is reset on every start) only the
logs are uploaded, under `logs-unrestored/`. The launcher's paths under the prefix (`log/`, `out/`,
`logs-unrestored/`) are excluded from the restore and from the `--delete` upload. A sync whose only errors are
refused deletes (a role without `s3:DeleteObject`) is a logged warning naming the count, not an upload failure.
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

## Pilot from an earlier run

With `PILOT_RUN_ID` (or `DRY_PILOT_DIR`) the run plays no collection and no distillation. Phase `pilot-import`
copies the earlier run's pilot results with `aws s3 cp` into `out/pilot-source/`; nothing is written to the earlier
run. The files: `markers/distill.done`, `ledgers/pilot.json`, `distill/params-best.npz`,
`distill-meta/params-best.sha256`, its `run-info/`, and (not in a dry run) `markers/collect-production.done`,
`manifests/production.json` and `collect-production/shards.sha256`. Then it checks:
- every file is there (else 51), and `params-best.npz` has the SHA256 the earlier run recorded (else 52);
- against the earlier run's newest run-info: the runtime environment (`XLA_FLAGS`, preallocation, thread counts), the
  collect and train phase environments (the allocator), the Python, JAX, jaxlib, optax and NumPy versions, and the
  engine sources (`git diff` of `src` and `include` between its commit and this one; a shallow clone fetches its
  commit): any difference stops with 52.
It writes `run-info/pilot-source.json` (the source, its commit and run-info, the SHA256 of every copied file). The
control and the evaluation then use `pilot-source/ledgers/pilot.json` (read only) and
`pilot-source/distill/params-best.npz`.

## Deviations from the plans (agreed 2026-10-09)

- **Evaluation smoke before training.** Plan C5 asks for the 64-game evaluation smoke to verify throughput "before
  training". The real smoke needs the trained students, so the run plays it twice: before any training with
  params-49333 standing in for pilot and control (phase 0, a separate manifest never used for the gate), and again
  after training with the real students (phase 4). Both are charged to the shared evaluation ledger.
- **Budget-matched control, acting on the CPU (p = 0).** The Learner v2 plan forecasts the shares (q, p) from unit
  costs. The first run on AWS (2026-10-09) did that with a calibration and one q, and missed the CPU axis by 20 %
  (the resumed process's first GPU update paid a 13 GPU-s JIT the forecast did not know). The control now chooses
  each update's device from its ledger (owner decision 2026-10-09); p stays 0, the 5 % match of both totals is
  unchanged.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | done (the run: REPORT.json written; dry run: rehearsal complete) |
| 1 | crash (a tool error, a failed export or check, expert_eval crash) |
| 2 | usage (missing or invalid environment, bad arguments) |
| 10 | inputs: a file missing (the ladder too), SHA256SUMS not exact, any hash mismatch |
| 11 | setup: a tool, build, venv, version pin or GPU missing; commit mismatch; earlier starts in WORK_DIR with another work_dir, run_id, mode or pilot source |
| 13 | a phase CLI refused its inputs (exit 2) |
| 20 | smoke STOP: t = 0 |
| 21 | STOP: forecast or actual generation CPU above 28800 core-seconds |
| 22 | STOP: primary work fallbacks above 1 % |
| 23 | production incomplete: fewer than 16384 targets (re-plan) |
| 30 | the control is incomplete: no device fits within 105 % before both axes reach 95 % (`control-fresh/run/log.jsonl`) |
| 31 | compute mismatch above 5 % (`control-fresh/compute-check.json`) |
| 32 | the control ended without its budget stop (the `--minutes` cap); the next start resumes it |
| 40 | evaluation smoke STOP (pre-training or post-training) |
| 41 | expert_eval refused (exit 2) |
| 50 | M12's `duoforge_search.eval_manifest` does not import from the commit (checked in setup) |
| 51 | `PILOT_RUN_ID`: a pilot file or its run-info is missing |
| 52 | `PILOT_RUN_ID`: the pilot differs (params SHA256, environment, versions or engine sources; `run-info/pilot-source.json`) |
| 60 | interrupted (signal or `--on-interrupt`); the next start resumes |

## Dry run

`run.sh --dry-run LOCAL_INPUTS_DIR` makes no aws call (the S3 wrapper refuses one). It reads the inputs in place,
checking them exactly as above, and writes to `$WORK_DIR/out`.
- **Pre-training smoke:** as in the run (STOP 40).
- **Collection:** the collector smoke only (1 round of 512 games, the size the manifest pins). Then the freeze. A
  t = 0 stops; a budget or fallback STOP is only reported.
- **Distillation:** on the smoke's shards with the smoke manifest. `DRY_DISTILL_DEVICE=cpu` (dry run only; a run
  refuses it with 2) puts it on the CPU.
- **Control:** as in the run, with an `--updates 4` cap; a stop by the cap or as incomplete is only reported, and
  the compute check is only reported. A pilot ledger without GPU-seconds (distill on the CPU) gets a 1 s target.
- **Pilot from an earlier dry run:** `DRY_PILOT_DIR=<earlier WORK_DIR>/out` rehearses the import with `cp`.
- **Evaluation:** the manifest and the `p1_eval` smoke on the real students. The run exits 0 on GO and 40 on STOP.
