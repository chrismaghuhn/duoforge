# Stage 3 P1 pilot: the run script

`run.sh` runs the P1 pilot ([pilot plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md),
[Learner v2 plan](../../../docs/superpowers/plans/2026-10-08-stage3-p1-learner.md)) without interaction on one GPU
machine. A launcher starts it after checking out a fixed commit. It does not create instances, and its only AWS calls
are `aws s3 cp/sync/ls`.

| File | Purpose |
| --- | --- |
| `run.sh` | the run, `--on-interrupt` and `--dry-run` |
| `p1_manifest.py` | writes the collector's `DataManifest` with the hashes the collector CLI checks; `freeze` computes the production rounds from the smoke |
| `p1_match.py` | compute matching of the control: from the calibration updates, the update GPU share q and the resume flags |
| `p1_export.py` | the control's final parameters from its run state as a format-2 checkpoint (a budget stop writes no snapshot) |

## Environment

| Variable | Meaning |
| --- | --- |
| `BUCKET`, `RUN_PREFIX`, `RUN_ID` | required for a run. `RUN_PREFIX` must be `p1/<RUN_ID>/` |
| `DUOFORGE_COMMIT` | the commit the launcher checked out. It must equal `git HEAD` when the source is a checkout, and it is required when it is not |
| `WORKERS` | native workers, 4, 8 or 14 (default 14, the frozen probe result for 16 vCPU) |
| `AFFINITY` | `taskset` CPU list for every phase of both arms (default `0-(WORKERS-1)`) |
| `LADDER_FILE` | the ladder checkpoint among the inputs (default `params-39400.npz`, M12 2026-10-09) |
| `TEAMS_DIR` | the team registry directory among the inputs (default `teams`) |
| `WORK_DIR` | work directory outside the repository (default `~/p1-work`, dry run `~/p1-dry/work`). Outputs are in `$WORK_DIR/out` |
| `VENV` | an existing Python environment to use instead of creating `$WORK_DIR/venv` |
| `UPLOAD_EVERY`, `INTERRUPT_WAIT` | periodic upload interval (900 s); how long `--on-interrupt` waits for the phase to save (60 s) |

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
- Sets the same runtime environment for every phase of both arms: `DUOFORGE_LIBRARY`, `PYTHONPATH=<repo>/python`,
  `PYTHONDONTWRITEBYTECODE=1`, `XLA_FLAGS=--xla_gpu_deterministic_ops=true`, `XLA_PYTHON_CLIENT_PREALLOCATE=false`,
  `OMP_NUM_THREADS=4`, `OPENBLAS_NUM_THREADS=4`.
- Unsets `JAX_PLATFORMS`, `XLA_PYTHON_CLIENT_MEM_FRACTION`, `XLA_PYTHON_CLIENT_ALLOCATOR`, `JAX_ENABLE_X64` and
  `CUDA_VISIBLE_DEVICES`.
- Only the collector additionally gets `JAX_PLATFORMS=cpu`, because its manifest pins `device: cpu`.
- Logs the environment and writes `run-info/run-info-<start>.json` on every start. That file holds: commit, versions
  (pip freeze), devices, CPU, GPU, compiler, seeds, environment and input hashes.

## Phases

Every phase writes `out/markers/<phase>.done` and uploads. A restart first restores `s3://$BUCKET/$RUN_PREFIX` into
`out/`, skips phases that are done, and resumes an interrupted collector, distill or train run from its own state. A
directory left without a resumable state is moved to `<dir>.aside-<time>`, never deleted.

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
     is on the CPU throughout (`--act-gpu-share 0`).
   - **Matching:** `p1_match.py` writes `control/match.json`. INFEASIBLE stops the run. Otherwise the script resumes
     with its flags: q, the pilot totals as ledger stops, `--updates 0`, a `--minutes` safety cap of twice the
     forecast, and `--learning-rate-schedule 0:1,D:0.1`. The run must end with its budget stop.
   - **Export:** `p1_export.py` writes `control/params-final.npz`.
   - **Check:** `expert_eval.validate_compute` compares both ledgers (5 % per axis) and writes
     `control/compute-check.json`.
4. **Evaluation** (shared ledger `ledgers/eval.json`):
   - **Manifest:** `python -m duoforge_search.eval_manifest` (M12; seed `0x2026100900000301`, `first_game_id`
     1000000000) with the checkpoints pilot = distill best, control = the export, frozen, BC, 3600, 11000 and ladder.
   - **Smoke:** `p1_eval --smoke`. Anything but GO stops the run.
   - **Full run:** `p1_eval`, giving `eval/B.json`.
   - **Report:** `expert_eval`, giving `eval/REPORT.json`.

**Uploads.** Everything in `out/` goes to `s3://$BUCKET/$RUN_PREFIX` as `sync --delete`. The local tree is the
authoritative state after the restore; without a completed restore only the logs are uploaded, under `logs-unrestored/`.
- What `out/` holds: manifests, ledgers, logs, timings, run-info, shards and their SHA list, distill and control run
  directories (final params of both arms), evaluation records and reports, and `STATUS.json`.
- When uploads happen: after every phase, every `UPLOAD_EVERY` seconds, and at exit, including on failure.

**`run.sh --on-interrupt`** is run by the launcher with the same environment. It SIGTERMs the running phase process
(collector, distill and train save on it), uploads at once, waits up to `INTERRUPT_WAIT` s, uploads again and exits 0.
The main `run.sh` then exits 60.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | done (the run: REPORT.json written; dry run: rehearsal complete) |
| 1 | crash (a tool error, a failed export or check) |
| 2 | usage (missing or invalid environment, bad arguments) |
| 10 | inputs: a file missing (the ladder too), SHA256SUMS not exact, any hash mismatch |
| 11 | setup: a tool, build, venv, version pin or GPU missing; commit mismatch |
| 13 | a phase CLI refused its inputs (exit 2) |
| 20 | smoke STOP: t = 0 |
| 21 | STOP: forecast or actual generation CPU above 28800 core-seconds |
| 22 | STOP: primary work fallbacks above 1 % |
| 23 | production incomplete: fewer than 16384 targets (re-plan) |
| 30 | matching infeasible (`control/match.json`) |
| 31 | compute mismatch above 5 % (`control/compute-check.json`) |
| 32 | the control ended without its ledger budget stop |
| 40 | evaluation smoke STOP |
| 41 | expert_eval refused (exit 2) |
| 50 | M12's `duoforge_search.eval_manifest` is not in the commit |
| 60 | interrupted (signal or `--on-interrupt`); the next start resumes |

## Dry run

`run.sh --dry-run LOCAL_INPUTS_DIR` makes no aws call (the S3 wrapper refuses one). It reads the inputs in place,
checking them exactly as above, and writes to `$WORK_DIR/out`.
- **Collection:** the collector smoke only (1 round of 512 games, the size the manifest pins). Then the freeze. A
  t = 0 stops; a budget or fallback STOP is only reported.
- **Distillation:** on the smoke's shards with the smoke manifest.
- **Control:** calibration 2 + 2 updates, then `p1_match.py`. Its result is printed only; INFEASIBLE is expected,
  because the pilot ledger has no production. Then the export, and the compute check, which is only reported.
- **Evaluation:** exit 50 if `eval_manifest` is absent. Otherwise the manifest and the `p1_eval` smoke. The run exits
  0 on GO and 40 on STOP.
