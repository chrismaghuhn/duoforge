# Stage 3 P1, Learner v2 side: full-joint API, distillation loop and continuation control

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposal for owner review, 2026-10-08. Docs only. Merging it authorizes Task 1 (the API, no run). Tasks 2–6 wait for M12 C1 (`expert_data`) and C5 (`ComputeLedger`). Task 7's run waits for the measured pilot ledger and an owner GPU window.

**Goal:** Learner v2's half of the P1 contract:
- `Model.full_joint_log_probs`;
- a distillation trainer that turns M12's teacher shards into a raw student of `params-49333`;
- a continuation control from `params-49333` on Learner v2's own data, matched to the pilot's measured compute within 5 %.

**Architecture:**
- **API:** The full-joint log-probabilities come from the existing pair head (`Model.apply`). No new head.
- **Distillation:** It lives in two new modules beside `ppo.py`: `distill_data.py` (shards → arrays, GAE targets, strata, split) and `distill.py` (loss, keyed batching, epochs, drift guards, exact resume, CLI). They reuse `returns.gae`, `ppo.optimizer`, `checkpoint` and `runstate`'s atomic write.
- **Compute:** A small `ledger.py` measures CPU core-seconds and GPU-seconds the same way in both arms.
- **Control:** The continuation is `train.py` with a ledger stop rule and an optional CPU acting device.

**Tech stack:** Python 3.12, JAX 0.11.2, optax 0.2.8, NumPy; WSL CUDA for runs, CPU JAX for tests.

**Spec:**
- [stage-3 spec](../specs/2026-10-05-m12-expert-iteration-design.md) section 3, including "Success must beat continued training";
- [P1 plan](2026-10-08-stage3-p1-pilot.md) C4 steps 11–12 (the contract) and C5 step 14 (the ledger);
- [decision 0024](../../decisions/0024-expert-iteration.md).

## Global Constraints

**Start and frozen reference**
- Start/reference params: `many-c4e96e6/params-49333`, SHA-256 `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb`. The same model size in both arms, with a fresh optimizer in both arms.
- The frozen reference is params-49333 itself, held fixed for the whole pilot. Its outputs are wrapped in `jax.lax.stop_gradient`.

**Loss**
- Loss = `mean_target KL(tau || pi) + 0.1 * mean_non_target KL(pi_49333 || pi) + c_V * existing_value_loss`.
- Each mean divides by its own valid unpadded weight. Padding, opponent and held-out rows contribute zero to every gradient.
- The value loss is unchanged: `returns.gae` with gamma 0.99 and lambda 0.95, value coefficient c_V 0.5, the squared error of `ppo._loss`. It covers learner acting and waiting rows of both strata.
- The value targets come from the stored actual rewards, done flags, collector values and bootstrap. There is no outcome MSE.

**Optimizer and batching**
- Adam LR 3e-5 constant, gradient norm clip 0.5 (`ppo.optimizer(3e-5, 0.5)`).
- Minibatch 4096 = 512 target rows + 3584 non-target rows. Uniform row weights; the tail is padded with weight 0.
- Each training target is visited once per epoch. At most 4 epochs and 128 optimizer steps.

**Drift guards**
- Held-out = 20 % whole games, taken from the shard's split. No row is ever reassigned.
- After every epoch, compute the held-out teacher KL and the held-out non-target reference KL.
- Stop when any of these holds:
  - two epochs pass without an improvement of at least 1e-4 nats;
  - any nonfinite loss, gradient or metric appears;
  - the held-out reference KL exceeds 0.02 nats.
- Keep the best epoch. An epoch that breaches 0.02 is never "best".

**Off in the pilot**
- The PPO surrogate, the magnet/KL anchor of #216, hindsight and regret weights.
- Team-selection (preview) rows get no teacher target. In the non-target KL they use the team head.

**Determinism and privacy**
- Resume restores params, optimizer, both permutation streams, the cursors, the epoch, the step and the best record exactly.
- A resume is refused when the manifest, init or reference hash, constants, code config or runtime differ.
- Run directories, shards and checkpoints stay outside the repository (`train.refuse_in_repository`). Nothing goes to CI artifacts; reports carry aggregates only.

**Compute matching**
- 5 % relative tolerance, independently for CPU core-seconds and GPU-seconds: `abs(control - pilot) <= 0.05 * pilot`.
- Every smoke, calibration, JIT and restart is charged to its arm.
- If the control cannot match, the result is incomplete and goes back for a re-plan. The control is never stretched or cut to force a match.

**Tests**
- Each new test module is registered in the learn/JAX list of `tests/CMakeLists.txt` (`foreach(_learn ...)`).
- Locally, run only the targeted `python -m unittest ...` commands below (CPU JAX). Full suites run on hosted CI: all checks green per PR.

## Review Focus

1. **Zero mass meeting an illegal action:** a `tau` with zero mass, or a reference with zero probability on an illegal joint action, meets `-inf` from the full-joint API. The loss and gradient must stay finite (no `0 * -inf`).
2. **Truncated or unfinished games:** GAE must use the stored bootstrap, not treat the cut as terminal. A game with no learner rows in one stratum must not break the grouping.
3. **Held-out leakage:** no row of a held-out game may ever enter a training minibatch, through either the target or the non-target stream.
4. **Team-selection rows:** in the non-target stratum their KL runs over the 360-action team head, never over the 1024 pair outputs.
5. **Resume between steps of an epoch:** the remaining steps, the non-target permutation that wraps over epochs, and the best record must equal the uninterrupted run byte for byte on CPU.

Each item has its test in the owning task: 1 in Task 3, 2 and 3 in Task 2, 4 in Task 3, 5 in Task 5.

---

## File structure

| File | Responsibility |
|---|---|
| `python/duoforge_learn/policy.py` (modify) | `Model.full_joint_log_probs` (Task 1) |
| `python/duoforge_learn/distill_data.py` (new) | shards → `DistillData` arrays; GAE targets per game and seat; strata; split (Task 2) |
| `python/duoforge_learn/distill.py` (new) | `distill_loss`, keyed batch plan, epoch loop, drift guards, best-epoch keep, state and resume, CLI (Tasks 3–5) |
| `python/duoforge_learn/ledger.py` (new) | `Ledger` CPU core-seconds and GPU-seconds, JSON in M12's `ComputeLedger` form (Task 6) |
| `python/duoforge_learn/train.py` (modify) | `--ledger`, `--stop-cpu-core-seconds`, `--stop-gpu-seconds`, `--act-device` for the continuation (Task 7) |
| `python/tests/test_learn_v2.py` (modify) | Task 1 test |
| `python/tests/test_distill.py` (new; registered) | Tasks 2–5 |
| `python/tests/test_ledger.py` (new; registered) | Tasks 6–7 |

---

### Task 1: `Model.full_joint_log_probs` (C4 step 11, Learner v2 gate)

**Files:** modify `python/duoforge_learn/policy.py`; test in `python/tests/test_learn_v2.py`.

**Interfaces:**
- Consumes: `Model.apply(params, obs, slots, mask) -> (logp_pairs (B,1024), logp_team (B,360), value (B,))`. The mask is `(B, MAX_SLOT_OPTIONS, MAX_SLOT_OPTIONS)` bool; the joint id is `i * 32 + j` (row-major, as `apply` flattens it).
- Produces:
  - `Model.full_joint_log_probs(params, obs, slots, legal_mask) -> jax.Array (B, 1024) float32`. `legal_mask` is `(B, 32, 32)` or `(B, 1024)` bool.
  - It returns `apply`'s pair log-softmax at legal ids and `-inf` at illegal ids. That is a masked log-softmax over all legal joint actions, never renormalized over candidates.
  - It checks on the host first, as `act` does:
    - an id past a capacity raises (`Model.check`; model v2 would otherwise clip it);
    - a row with no legal action raises `ValueError` naming the row;
    - a traced `obs` or mask (inside `jit`) raises, pointing at the traced variant.
  - Also `Model.full_joint_log_probs_traced` (no host checks), for jitted losses over rows that Tasks 2–3 validate at load.
  - A loss over these values must skip zero-mass entries, because `0 * -inf` is NaN.
  - Delivered in #245.

- [ ] **Step 1: Write the failing test** `FullJointTest.test_full_joint_is_the_masked_pair_softmax_with_gradients` (v2 preset S config, PRNGKey(7), 6 synthetic rows from `features`/`selfplay` shapes). Assertions:
  - shape `(6, 1024)`, float32;
  - illegal ids exactly `-inf`;
  - `logsumexp` over the legal ids = 0 within 1e-5 per row;
  - legal values equal `apply(...)[0]` at those ids;
  - a `(B, 1024)` mask gives the same result as the `(B, 32, 32)` one;
  - a row with exactly one legal id gives 0.0;
  - an all-false row raises `ValueError` matching `"row 3"`;
  - `jax.grad` of `sum_legal tau * logp` (tau uniform over 3 legal ids) w.r.t. params is finite and nonzero;
  - a "candidate-only" renormalization of the same row (logsumexp over 3 ids) differs from the API in at least one value by > 1e-3, so the test distinguishes the two.
- [ ] **Step 2: Run it.** `python -m unittest test_learn_v2.FullJointTest -v` with `PYTHONPATH=python:python/tests`, CPU JAX, library of the PR's main. Expected: **ERROR**, `AttributeError: 'Model' object has no attribute 'full_joint_log_probs'`.
- [ ] **Step 3: Implement both methods.** Reshape a `(B, 1024)` mask to `(B, 32, 32)` for `apply`. The output is `jnp.where(flat_mask, logp_pairs, -jnp.inf)`; the gradient through `where` reaches only the legal entries, which are finite. The host check is `np.asarray(mask).reshape(B, -1).any(axis=1)`.
- [ ] **Step 4: Run it.** Same command. Expected: **OK**.
- [ ] **Step 5: Commit** ("Model.full_joint_log_probs: the masked full-joint pair distribution (stage 3 C4)").

### Task 2: shards → `DistillData` (needs M12 C1 merged)

**Files:** create `python/duoforge_learn/distill_data.py`, `python/tests/test_distill.py`; register `distill` in `tests/CMakeLists.txt`.

**Interfaces:**
- Consumes:
  - M12 `duoforge_search.expert_data.read_shard(path, expected) -> tuple[ExpertRow, ...]`, `DataManifest`, `RowStatus`;
  - `returns.gae(values, rewards, done, acting, bootstrap, gamma=0.99, lam=0.95)`.
- Produces:
  - A frozen dataclass `DistillData` (NumPy arrays, one row per learner row):
    - `obs, slots, mask (N,32,32) bool, is_team bool`;
    - `target_ids (N,8) int64` with `-1` padding, `target_probs (N,8) float32`. K stays 8: the student's action displaces the lowest candidate (spec section 1);
    - `has_target bool`, `policy_row bool` (acting, ≥2 legal, no target), `value_row bool`, `value_target float32`;
    - `game_id int64`, `held_out bool`.
  - `load(shard_dir: Path, manifest: DataManifest) -> DistillData`.
  - `strata(data) -> (target_idx, non_target_idx)` for train and held-out separately, as `dict[str, ndarray]` with keys `train_target`, `train_non`, `held_target`, `held_non`.
- **Row rules:**
  - Learner rows only. Opponent rows raise `ValueError` (the shard must not carry them).
  - `has_target` iff the status is `TARGET`.
  - `policy_row`: an acting non-target row with ≥2 legal actions. That covers UNSELECTED, CAP_RAW, PUBLIC_REFUSAL and WORK_EXHAUSTED. FORCED and UNREQUESTED rows are value-only.
  - Waiting rows are value-only.
  - **Value targets:** `returns.gae` per game, with its own shapes:
    - `values`, `rewards` and `acting` are `(T, 1, 2)`; `done` is `(T, 1)`; `bootstrap` is `(1, 2)`;
    - T is the game's lockstep steps, ordered by the per-game step index;
    - the learner's seat holds its rows; the other seat is acting = False and value 0, and its targets are discarded.
    - At a truncation the stored bootstrap applies.
  - **Contract item for M12 C1:** every learner row, acting or waiting, carries a per-game step index (the logical tick). `request_epoch` alone does not order waiting rows.
  - **Validation:** each of these raises:
    - a nonfinite value;
    - a zero-legal policy row;
    - a `target_ids` id outside the legal mask.
    Team-selection rows are checked against their 360 team actions, not the pair mask.

- [ ] **Step 1: Write the failing tests.** They build synthetic shards through M12's `write_shard` into a temp dir outside the repo.
  - `test_strata_split_and_value_targets` covers 4 games (1 held-out):
    - the strata index sets are disjoint;
    - no held-out game id appears in `train_*` (Review Focus 3);
    - value targets equal a hand-computed `returns.gae` for a 3-step game;
    - a truncated game uses its bootstrap: its targets equal a hand computation with bootstrap 0.37, and differ from the terminal-at-cut version (Review Focus 2);
    - a waiting row's target is its seat's next decision's return;
    - a game whose learner never acted still yields value rows;
    - FORCED rows are `value_row` only.
  - `test_load_refuses_bad_rows`: an illegal target id, a zero-legal policy row, an opponent row and a nonfinite reward each raise `ValueError`.
- [ ] **Step 2: Run them.** `python -m unittest test_distill.DataTest -v`. Expected: **ERROR**, no module `duoforge_learn.distill_data`.
- [ ] **Step 3: Implement `load` and `strata`.** Group rows by `(game_id, seat)`; per group, stack `[T, 1]` arrays for `returns.gae`.
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.**

### Task 3: the distillation loss

**Files:** create `python/duoforge_learn/distill.py`; tests in `python/tests/test_distill.py`.

**Interfaces:**
- Consumes:
  - Task 1 `full_joint_log_probs_traced`;
  - `Model.apply` (team head);
  - `DistillData` field names.
- Produces:
  - constants `LR = 3e-5`, `CLIP = 0.5`, `TARGET_ROWS = 512`, `NON_TARGET_ROWS = 3584`, `REF_COEF = 0.1`, `VALUE_COEF = 0.5`, `MAX_EPOCHS = 4`, `MAX_STEPS = 128`, `MIN_GAIN = 1e-4`, `PATIENCE = 2`, `REF_KL_MAX = 0.02`;
  - `distill_loss(params, ref_params, batch, model) -> (loss, aux)`, where `aux = {"teacher_kl", "ref_kl", "value_loss", "n_target", "n_policy", "n_value"}`.
- **Teacher KL:** `sum_k p_k (log p_k - logpi[id_k])` over `p_k > 0` only, gathered at the target ids. The loss never touches an illegal id, so no `-inf` enters.
- **Reference KL:** `sum_j p_ref(j) (logp_ref(j) - logpi(j))` with `where(p_ref > 0, ..., 0)`. Pair rows use the pair head; team rows use the team head (`apply`'s `logp_team`).
- **Weights:** the batch carries `weight` (0 for padding), `has_target`, `policy_row` and `value_row`. Each mean divides by `max(sum_of_its_weights, 1)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_loss_terms_match_numpy_reference`: a NumPy reference computes each of the three terms on 8 synthetic rows (2 target, 3 policy, 1 team policy, 2 waiting).
  - `test_loss_is_zero_kl_at_reference_and_finite_at_illegal`, where `params = ref_params` gives `ref_kl == 0` within 1e-6. Each of these is finite (Review Focus 1):
    - `tau` with a 0-mass entry;
    - a reference with zero mass on illegal ids;
    - the gradient.
  - `test_padding_and_team_rows`:
    - doubling the batch with weight-0 padding leaves the loss and gradient bitwise equal;
    - team rows' `ref_kl` equals the team-head KL and does not read the pair outputs (Review Focus 4: corrupting their pair mask changes nothing).
- [ ] **Step 2: Run them.** `python -m unittest test_distill.LossTest -v`. Expected: **ERROR**, no `distill_loss`.
- [ ] **Step 3: Implement `distill_loss`.** The reference forward runs inside the same jit under `stop_gradient`. The value term reuses the expression of `ppo._loss` (same coefficient and rows).
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.**

### Task 4: keyed batches, epochs and drift guards

**Files:** `python/duoforge_learn/distill.py`; tests in `python/tests/test_distill.py`.

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces:
  - `BatchPlan(seed: int)`:
    - `.targets(epoch, n) -> ndarray (steps, 512)` with `-1` padding: a permutation from `np.random.default_rng([seed, 1, epoch])`, each target exactly once per epoch.
    - `.non_targets(cursor, n, steps) -> (ndarray (steps, 3584), new_cursor)`: a stream of permutations `default_rng([seed, 2, lap])` that continues across steps and epochs and wraps by lap.
    - The cursor is `(lap, position)`.
  - `fit(data, model, init_params, ref_params, out, seed, ledger) -> FitResult`, with `FitResult(best_epoch, stop_reason, epochs: list[dict], steps)`.
  - `stop_reason` is one of `"max_epochs"`, `"max_steps"`, `"no_gain"`, `"ref_kl"`, `"nonfinite"`.
- **Epoch 0** is the baseline evaluation of `init_params` before any step.
- **Steps per epoch** are `ceil(n_train_target / 512)`. Training stops at 128 steps total even inside an epoch; that point is evaluated as the epoch's end.
- **Held-out evaluation** uses the same loss terms on `held_target` / `held_non`, in fixed chunks of 4096 rows (the last one padded). Each metric is the sum over all chunks divided by the summed weights, never a mean of chunk means.
- **Best epoch:** the lowest held-out teacher KL among epochs with ref KL ≤ 0.02 and all-finite metrics.
- **If the best epoch is 0** (no step improved on 49333), the fit reports `best_epoch = 0`. `params-best.npz` is then 49333 itself, marked `"no_gain"` in its config. M12's evaluation still runs as declared, and a student identical to 49333 cannot pass the gate against frozen 49333.
- **Outputs:**
  - `params-epoch-{e}.npz` and `params-best.npz`, written by `checkpoint.save` with 49333's config (so `ladder` and `evaluate` load them unchanged);
  - `log.jsonl`, one line per step: losses, counts, the global norm of the policy-term and value-term gradients (spec: "report policy:value counts/gradient magnitudes"), and seconds; one line per epoch with the held-out metrics.

- [ ] **Step 1: Write the failing tests.**
  - `test_batch_plan_covers_each_target_once_and_streams_non_targets`:
    - over 2 epochs, each train target appears exactly once per epoch;
    - the non-target stream continues across epochs (the cursor does not reset);
    - no held-out id appears in either stream (Review Focus 3).
  - `test_fit_stops_and_keeps_best`, each case on a tiny synthetic set (CPU):
    - held-out metrics over 3 chunks with a padded tail equal the one-pass weighted means;
    - (a) `REF_KL_MAX` patched to 0.0 stops with `"ref_kl"` after epoch 1, and best = 0, with `params-best` equal to the init and marked `no_gain`;
    - (b) `MIN_GAIN` patched to 1e9 stops with `"no_gain"` after epoch 2, and best = 0;
    - (c) a NaN injected into one value target stops with `"nonfinite"`, with no `params-best` from that epoch;
    - (d) with 32 targets (1 step per epoch), the run goes to `"max_epochs"` at 4 epochs;
    - (e) `MAX_STEPS` patched to 3 with 2 steps per epoch stops with `"max_steps"` at step 3.
- [ ] **Step 2: Run them.** `python -m unittest test_distill.FitTest -v`. Expected: **ERROR**, no `BatchPlan`/`fit`.
- [ ] **Step 3: Implement `BatchPlan` and `fit`.** Use `ppo.optimizer(LR, CLIP)`, fresh. Each step is one jitted `value_and_grad` + `tx.update`.
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.**

### Task 5: exact resume and the CLI

**Files:** `python/duoforge_learn/distill.py`; tests in `python/tests/test_distill.py`.

**Interfaces:**
- Consumes: `runstate`'s atomic write pattern (temp file, fsync, `.prev`, replace) and `runstate.StopSignal`.
- Produces:
  - `distill-state.npz`: params, opt leaves, the cursors, epoch, step, best record and the epoch log. It is written after every step's update when a stop is pending, and at every epoch end.
  - `fit(..., resume=True)` continues from it.
  - CLI `python -m duoforge_learn.distill --init PATH --reference PATH --shards DIR --manifest PATH --out DIR [--resume] [--seed N]`.
  - There are no flags for the pinned constants. The init and reference SHA-256 must both equal 49333's unless `--allow-other-init` (tests only, refused when `--out` is a pilot run marked in the manifest).
  - The CLI refuses `--out` inside the repository and refuses a resume with a different manifest hash, constants, init or reference hash, JAX/optax version or device kind.
  - Exit 0 is a finished fit (with any `stop_reason`); exit 2 is a refusal, with its cause on stderr.

- [ ] **Step 1: Write the failing tests.**
  - `test_resume_mid_epoch_is_bitwise_identical`: an uninterrupted fit vs a fit stopped after step 3 of epoch 2 (SIGTERM via `StopSignal`) and then resumed. Final params, opt leaves, `best_epoch` and the log lines (without seconds) are byte-identical on CPU (Review Focus 5).
  - `test_resume_refusals`: each of these exits 2 with a message:
    - a changed manifest hash;
    - a patched `LR`;
    - a different reference file;
    - `--out` inside the repo;
    - a missing state with `--resume`.
- [ ] **Step 2: Run them.** `python -m unittest test_distill.ResumeTest -v`. Expected: **FAIL/ERROR**, no state or CLI.
- [ ] **Step 3: Implement the state, resume and `main(argv)`.**
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.**

### Task 6: the compute ledger (both arms)

**Files:** create `python/duoforge_learn/ledger.py`, `python/tests/test_ledger.py`; register `ledger`.

**Interfaces:**
- Consumes: M12 C5's `ComputeLedger` field names. The JSON keys are agreed with M12 before this task; the proposal is `cpu_core_seconds`, `gpu_seconds`, `phases`.
- Produces: `Ledger(path)` with:
  - `.phase(name)` (a context manager);
  - `.device()`, a context manager timing one device-synchronous section that must end in `jax.block_until_ready`;
  - `.save()`.
- **CPU core-seconds** = the user+sys delta of `resource.getrusage(RUSAGE_SELF)` + `RUSAGE_CHILDREN`. That includes the native batch worker threads, which run in-process.
- **GPU-seconds** = the wall time of `.device()` sections: from submitting device work until `block_until_ready` returns, JIT included.
  - This is wall time reserved on the device, not a hardware busy-time counter, which CUDA does not give us per process.
  - The host's own CPU inside a section also counts as CPU. The same definition holds in both arms.
  - Sections never nest. Only code that issues device work runs inside them.
- **Phases:** every process start appends its totals, so restarts add up. Smokes, calibration, JIT and restarts are charged to their arm. The shared evaluation is charged half to each arm by M12's C5.
- **Shared definition with M12:** a fixture test runs one `Ledger` file of each arm through M12's `validate_compute`. It is added in this task once C5 is merged. If M12's generation measures differently, the plan is not ready.

- [ ] **Step 1: Write the failing tests.**
  - `test_ledger_counts_cpu_and_device_and_survives_restart`:
    - a busy loop of about 0.2 s raises `cpu_core_seconds` by ≥0.15;
    - a `device()` section around a jitted matmul with `block_until_ready` raises `gpu_seconds` > 0 (CPU JAX in CI: the section is still timed);
    - nesting `device()` raises;
    - two `Ledger` instances on one path sum;
    - writing inside the repository raises.
  - `test_ledgers_pass_m12_validate_compute`: two synthetic ledgers within 5 % pass; at 5.1 % they fail on the named axis.
- [ ] **Step 2: Run them.** `python -m unittest test_ledger -v`. Expected: **ERROR**, no module.
- [ ] **Step 3: Implement it.** Wrap `fit`'s steps and held-out evaluations in `.device()`.
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.**

### Task 7: the continuation control (code; the run is a separate owner-scheduled step)

**Files:** modify `python/duoforge_learn/train.py`; tests in `python/tests/test_ledger.py`.

**Why two continuous knobs:**
- Both axes must land within 5 %. Stopping at the first axis that reaches its budget only works if the run's ratio of GPU-seconds to CPU core-seconds already equals the pilot's.
- The pilot's ratio is extreme: about 8 core-hours of CPU generation against a few GPU minutes of training (128 steps at most, plus held-out evaluation and JIT).
- Discrete knobs (epochs, all-or-nothing acting device) cannot hit an arbitrary ratio, and epochs would change the recipe.
- So the device that runs each step is the knob, which leaves the RL recipe as it is:
  - acting on CPU or GPU, chosen per collection step;
  - each PPO update on CPU or GPU, chosen per update.
  - Only float rounding differs between the two devices.
- Moving updates to CPU lowers the ratio continuously toward 0. Moving acting to GPU raises it. Every ratio between "all CPU" and "all GPU" is reachable.

**Interfaces:**
- Consumes: Task 6 `Ledger`.
- Produces `train` options (all resumable):
  - `--ledger PATH`: `act` and `ppo.update` run inside `.device()` when on the GPU; the run is the phase `continuation`.
  - `--stop-cpu-core-seconds X` and `--stop-gpu-seconds Y`: a clean stop (save, exit 0) at the first update where either total reaches its value.
    - They replace the 60-minute default: with them, `--minutes`/`--updates` are not required. `--minutes` becomes only a safety cap, set to twice the forecast.
    - `--eval-every` is set beyond the run, so no in-run suites are played (anything played would be charged).
  - `--update-gpu-share q` (0..1): update u runs on the GPU iff `floor((u+1)·q) > floor(u·q)`, else on the CPU (params and optimizer state moved with `jax.device_put`). Deterministic, so a resume continues the same schedule.
  - `--act-gpu-share p` (0..1): the same rule per collection step for `act`.
  - Defaults q = 1, p = 1 are today's behaviour.
- **Recipe (owner decision, proposed):** the local A/B winner of 2026-10-05, from params-49333 via `--init` (fresh Adam):
  - `--learning-rate 3e-4` (the base);
  - `--kl-ref magnet --kl-coef 0.05 --kl-refresh 500`;
  - `--learning-rate-schedule 0:1,D:0.1`, where D = 0.9 × the forecast decisions of the matched budget. D is fixed before the run, so the decay completes within it; the A/B used 30M over its 33M;
  - entropy 0.01, `--epochs 4`, `--minibatch 2048`, `--envs 256`;
  - the run's teams and weights (core79 + LL_ 50/50, `--teams-root` of the frozen c4e96e6 registry);
  - `--workers` equal to the pilot's assigned core count, pinned with `taskset`.

- [ ] **Step 1: Write the failing tests.**
  - `test_train_stops_at_the_ledger_budget`:
    - a 2-env CPU run with `--stop-cpu-core-seconds` just above one update's measured cost stops after a few updates with exit 0, without `--minutes`;
    - its ledger total is ≥ the budget and below budget + one update;
    - a resume keeps the ledger sum.
  - `test_device_shares_are_deterministic_and_resumable`:
    - with q = 0.25 exactly 1 of every 4 updates is marked GPU in the log;
    - a resume after update 3 continues the same pattern;
    - q = 0 and p = 0 give `gpu_seconds == 0`.
- [ ] **Step 2: Run them.** Expected: **FAIL**, unknown options.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run them.** Expected: **OK**.
- [ ] **Step 5: Commit.** Open the integration PR (Tasks 2–7) with review.

**The control run (after the pilot's ledger is measured):**
1. **Forecast first, before any GPU spend.** Use per-unit costs from the Task 7 test machine:
   - CPU core-seconds per collection step on CPU and on GPU;
   - GPU-seconds per update on GPU;
   - CPU core-seconds per update on CPU.

   Solve for (q, p) so that the totals hit both pilot axes at the same update. If no (q, p) in [0, 1]² does, it is infeasible: report it to the owner and run nothing.
2. **Calibration** (charged, capped at 10 % of each pilot axis): one short run at the forecast (q, p) measures the real unit costs. Re-solve once.
3. **Run.** `--stop-cpu-core-seconds = pilot_cpu − calibration_cpu`, `--stop-gpu-seconds = pilot_gpu − calibration_gpu`.
4. **Check.** Run M12's `validate_compute` on both ledgers. If either axis misses 5 %, the control is **incomplete**: back to the owner, never extended or cut.

---

## What the owner decides with this plan

1. **The control's recipe:** the A/B winner (magnet + LR decay completing within the budget, proposed) or plain PPO at LR 3e-4. A stronger control makes the pilot's bar honest.
2. **The matching knobs:** the per-update and per-step device shares (above). Matching both axes is the main risk, because the pilot is almost all CPU. The forecast says before any run whether it is feasible.
3. **The ledger definitions and key names**, agreed with M12 (C5), and the per-game step index in M12 C1's rows (Task 2).
4. **Windows:**
   - The control runs on CPU for hours but needs a GPU free of other jobs, so its GPU-seconds are not inflated by contention.
   - The pilot's training plus evaluation needs an exclusive GPU window.
   - Neither runs during a night run.
5. **More cores** (owner, 2026-10-08): if M12 generates with more than 4 cores, the control uses the same count. Matching stays in core-seconds, so only wall time shrinks.

## Self-review

- **Spec coverage:** every item of section 3 maps to a task.
  - loss terms and means → Task 3;
  - 512 + 3584 rows → Task 4;
  - GAE semantics and waiting rows → Task 2;
  - drift and the best epoch → Task 4;
  - exact resume → Task 5;
  - PPO and magnet off (`distill.py` has neither) → Task 3;
  - continuation with its own data and matched compute → Tasks 6–7;
  - privacy → Task 5 refusals, outputs outside the repo.
- **C4 step 11** (normalization, illegal = `-inf`, zero-legal refused, gradient, the candidate-only counterexample) → Task 1.
- **What this plan does not do:** P2+ (batching, routing, hindsight); M12's teacher, schema and evaluator.
