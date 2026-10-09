# P1 execution plan: keyed random-1/8 teacher pilot

**Status: revised proposal for owner approval, 2026-10-08. Docs only; no implementation or run authorized.** Sources: [0024](../../decisions/0024-expert-iteration.md), [spec](../specs/2026-10-05-m12-expert-iteration-design.md), [P0](../../learning/2026-10-08-stage3-p0/README.md). P0 X gain +0.2695 [0.2129, 0.3262] passes entry; CPU median ~50 ms/search is the planning input.

## Ownership, size and execution gates

After approval, estimate **eight subsequent PRs**: five small M12 code PRs below, one M12 aggregate result PR, one separate Learner v2 implementation-plan PR and one Learner v2 integration/control PR (split further if review requires). This plan contains **only M12 schema/teacher/evaluator and synthetic interface fixtures/tests**. Learner v2 implements `policy.py` integration, collection/training loop, optimizer/loss/drift/resume and continuation in its own plan; owner relays the contract. M12 must not implement a second learner or change Learner v2 files under this plan.

| M12 PR | Scope | Dependency | Estimate after contract agreement |
|---|---|---|---|
| C1 | schema, keys, label admission | none | 0.5–1 day |
| C2 | bounded matrix solver | independent of C1 | 1 day including private calibration |
| C3 | honest teacher, mapping, leak/determinism tests | C1 + C2 | 1 day |
| C4 | Learner v2 synthetic contract fixtures/tests only | C1; real-provider gate waits for its PR | 0.5 day |
| C5 | evaluation/compute-ledger validator | C1; runnable arms wait for Learner v2 | 0.5–1 day |
| R1 | aggregate pilot/control report | approved code, resources and completed runs | 0.5 day |

C1/C2 can progress independently; C4/C5 can follow C1 while C3 is reviewed. This is a dependency description, not permission to spawn parallel agents or run jobs concurrently. No training process/worker changes. Required full CI gate for **each code PR**: all 13 hosted checks on its head green, including Linux gcc Release/Python/JAX/reference and Windows gcc Debug/Python/reference; existing search, honest, PPO/returns/default-path suites remain enabled. R1 and this docs PR: links/diff/privacy review; runtime tests do not apply.

**Local rule:** run only the targeted `pytest python/tests/test_<x>.py -k ...` below in the configured Python/native/JAX environment. Full suites run on GitHub CI, never locally. Each step is red test commit → minimal implementation → identical targeted command green. Expected red is a missing API or failed assertion, never a native-library/environment import failure. No test weakening. New tests must remain unittest-compatible for hosted CTest: register expert_data/expert_eval in the NumPy list and expert_teacher/expert_contract in the learn/JAX list of `tests/CMakeLists.txt`. Existing `test_search_numpy.py` already has its gate. Names/commands below are proposed tests, not tests already run.

## Fixed contract (before any pilot)

Frozen teacher/collector/start params: 49333, SHA-256 `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb`. Honest CPU path, own/foe 8 candidates, W=S=16, lambda=0.5, value capacity 1024, native worker/core count selected from 4/8/14 by the short pre-freeze CPU probe below, then immutable in both pilot and control; 512 lockstep games/round. Preview raw/book off. No routing, GPU teacher batching, hindsight, double oracle, new head or PPO+distill. Teacher models the foe with **its own frozen net**, including league games.

Proposed public signatures, dataclass fields and enums (interfaces, not implementation):

```python
# expert_data.py; ndarray fields have explicit schema/shape checks
class RowStatus(Enum):
    TARGET = "target"
    UNSELECTED = "unselected"
    CAP_RAW = "cap_raw"
    PUBLIC_REFUSAL = "public_refusal"
    WORK_EXHAUSTED = "work_exhausted"
    FORCED = "forced"
    UNREQUESTED = "unrequested"
# frozen DecisionKey(game_id: int, seat: int, request_epoch: int)
# frozen SparsePolicy(ids: ndarray[int64, K], probs: ndarray[float64, K])
# frozen DataManifest(schema_version=1, source/checkpoint/model/encoder/id/pool/
# belief hashes, seeds/key_version, devices/runtime/compiler, capacity/workers/
# parallel_games, game_count/rounds, split, budget and evaluation configs)
# frozen ExpertRow(key, logical_tick, boundary, obs, slots, legal_mask, sparse_policy|None, status,
# raw_action|None, action|None, behavior_logp|None, acting/learner/value masks,
# actual rewards/done/collector values/bootstrap, admission/work/audit provenance)
def validate_manifest(manifest: DataManifest) -> None: ...
def validate_row(row: ExpertRow, manifest: DataManifest) -> None: ...
def write_shard(path: Path, rows: Sequence[ExpertRow], manifest: DataManifest) -> str: ...
def read_shard(path: Path, expected: DataManifest) -> tuple[ExpertRow, ...]: ...
def selection_word(key: DecisionKey, seed: int, *, domain: str, version: int=1) -> int: ...
# LabelCursor(remaining: int, pending_reservations, dropped_games, logical_tick)
# AdmissionBatch(admitted_keys, cap_raw_keys, reserved_count); AdmissionOutcome(key, status)
def admit_tick(cursor: LabelCursor, requests: Sequence[DecisionKey]) -> AdmissionBatch: ...
def commit_tick(cursor: LabelCursor, outcomes: Sequence[AdmissionOutcome]) -> LabelCursor: ...

# matrix.py; budget optional, preserving original return/default behavior
class WorkStatus(Enum):
    OK = "ok"
    FLOAT_PIVOTS = "float_pivots"
    EXACT_PIVOTS = "exact_pivots"
    EXACT_OPS = "exact_ops"
    BITS = "bits"
# WorkBudget(float_pivots=4096, exact_pivots=32, exact_ops=250000, bits=4096)
# WorkCounters(float_pivots: int, exact_pivots: int, exact_ops: int, max_bits: int)
# mutable WorkLedger(limits: WorkBudget, consumed: WorkCounters)
# WorkBudgetExceeded(SearchError): status: WorkStatus, consumed: WorkCounters
# budget exhaustion is NEVER caught by the ordinary float->rescue retry
# W=1 reduction must use the same ledger through solve(a, *, budget=None)
def solve_bayes(tables: ndarray, weights: ndarray, *,
                budget: WorkLedger | None=None) -> BayesSolution: ...

# expert.py; no actual league-opponent model parameter
# TeacherConfig pins the CPU path and stream/config hashes above
# TeacherDecision(action, behavior_logp, target|None, status, work, audit,
# world_digest, table_digest, label_digest)
def include_student(candidates: ndarray, raw_action: int,
                    legal_mask: ndarray, *, k: int=8) -> CandidateSet: ...
def full_target(policy: SparsePolicy, legal_mask: ndarray) -> ndarray: ...  # (1024,)
def label_decision(search: Honest, roots: Batch, *, env: int, seat: int,
                   key: DecisionKey, raw_action: int, admitted: bool,
                   config: TeacherConfig) -> TeacherDecision: ...

# expert_eval.py; EvalManifest and ComputeLedger are immutable schema objects
# ComputeLedger(cpu_core_seconds: float, gpu_seconds: float,
#               phases: Mapping[str, PhaseCompute]); each PhaseCompute uses the same keys
# CPU = deltas of getrusage(SELF + CHILDREN).user + .sys;
# GPU = synchronous device-section wall time including JIT, with completion barrier
# GateStatus: PASS, FAIL, INCONCLUSIVE, INCOMPLETE
# EvalResult(status, scores, paired CIs, groups, provenance, budget causes)
def make_eval_rows(pool: TeamPool, manifest: EvalManifest) -> dict[str, ndarray]: ...
def validate_compute(pilot: ComputeLedger, control: ComputeLedger) -> None: ...
def evaluate_records(records: Mapping[str, ndarray], manifest: EvalManifest,
                     ledgers: tuple[ComputeLedger, ComputeLedger]) -> EvalResult: ...
def main(argv: Sequence[str] | None=None) -> int: ...
```

Paths/unknown schemas/illegal masks/incompatible resume/nonfinite data raise explicit errors; status enums cover documented policy fallbacks only. `write_shard` returns SHA-256 of canonical bytes; keys and ndarray serialization specify dtype/endianness/order and preserve exact float bits. No real table/row goes in synthetic fixtures.

## C1 — schema, selection and admission (three red/green steps)

**1. Schema/privacy.** Write `test_schema_refusal_and_private_roundtrip` in `python/tests/test_expert_data.py`. Red command: `pytest python/tests/test_expert_data.py -k schema_refusal_and_private_roundtrip` → **FAIL**, missing validator/writer. Implement `validate_manifest`, `validate_row`, `write_shard`, `read_shard` above using `refuse_repository` from **`python/duoforge_replay/dataset.py`**. Check shapes/dtypes, sparse mass tolerance 1e-6, masks/GAE provenance, unknown versions and mismatched manifest hash; canonical roundtrip and repository output refusal. Same command → **PASS**.

**2. Selection.** Write `test_selection_word_domains_and_frequency`. Red: `pytest python/tests/test_expert_data.py -k selection_word_domains_and_frequency` → **FAIL**. Implement `selection_word`: SHA-256 over version 1 tag `duoforge-expert`, length-prefixed UTF-8 domain and little-endian uint64(seed, game_id, seat, epoch); first eight digest bytes decoded little-endian give an unsigned uniform 64-bit word. Raw/SELECT/world/X/audit domains distinct; no Python hash or worker/timing input. Select exactly when SELECT word <2**61. Test known vectors, permutations, domain/version changes and **65536 predeclared keys; selected count must be 8192±384** (~4.5 binomial standard deviations); no tolerance adjustment. Same command → **PASS**. Raw policy word is drawn before selection; `tau` is precisely **X**, not the Nash component alone.

**3. Cap before action.** Write `test_admission_precedes_tau_and_drops_games_in_order`. Red: `pytest python/tests/test_expert_data.py -k admission_precedes_tau_and_drops_games_in_order` → **FAIL**. Implement `admit_tick`/`commit_tick`: each complete logical lockstep tick sorts eligible selected roots by logical game id/seat/epoch, reserves up to remaining 16384 label tickets **before teacher execution**. Never admit by arrival order. Unadmitted games are marked CAP_RAW for the remaining collection, execute already drawn raw, and never play tau with a discarded label. Drop excess game-by-game in that logical order, counting games/roots; earlier labels stay in their original game's split. A valid teacher result consumes its reserved ticket and plays tau; public/work refusals release the ticket only after all tick outcomes commit. No labels are capped after executing tau. Persist pending reservations/dropped-game set/tick in resume; partial tick cannot advance actors. Test zero/one remaining slots, refusal release, regrouped requests, no overshoot, no tau without stored target. Same command → **PASS**.

Smoke policy (after code approval): **512 complete games once**, included in generation cap; its rows are forecast-only and excluded from training/validation. Production uses disjoint logical game ids and evaluation has its own namespace. Freeze production rounds before execution as `R=ceil(1.25*16384/(512*t))`, where t is smoke valid-targets/game at 1/8; game count=512R, ids/weights/seeds/split pinned. The 1.25 margin is fixed, not tuned. If t=0 or forecast exceeds budget, stop. No extra rounds after seeing production results. Production cap 16384 includes whole-game 20% held-out split (keyed split before collection); use realized counts, no row reassignment. Finish fixed games raw after cap to obtain valid GAE. If planned games yield fewer 16384 valid targets, report incomplete/re-plan, do not silently extend.

## C2 — bounded solver (independent of C1)

Commit both steps 4/5 red tests before implementing the shared budget extension in step 4; run both targeted commands red, then both green. This avoids inventing a later failing test for a property the shared implementation already satisfies.

**4. Work budget.** Add `test_bayes_budget_cumulative_and_default_identity` to **`python/tests/test_search_numpy.py`**. Red: `pytest python/tests/test_search_numpy.py -k bayes_budget_cumulative_and_default_identity` → **FAIL**, new keyword/exception missing. Implement `WorkBudget/WorkLedger/WorkBudgetExceeded` and `solve_bayes(..., budget=...)`; thread ledger through single-world `solve`, float/stable/exact and certificate conversion paths. Unit is **one primary teacher decision**, shared across every solve/retry; ledger never resets per call. Count pivots including initialization, Fraction construction/conversion, arithmetic(+,-,*,/,negation) and comparisons; check 4096-bit intermediate numerator/denominator before and after exact operations. Unexpected errors abort. Original 1e-9 certificate/payoffs/ties unchanged, budget=None byte-identical. Same command → **PASS**.

**5. Audit/clock exhaustion.** Write `test_primary_and_audit_budgets_with_clock_injection` in `python/tests/test_search_numpy.py`. Red: `pytest python/tests/test_search_numpy.py -k primary_and_audit_budgets_with_clock_injection` → **FAIL**. Exercise independent primary and **K+1 audit ledgers with identical caps** through the matrix API on synthetic tables; wire them into TeacherConfig in C3 step 9; audit selected by domain word <floor(2**64/100). It reuses worlds, never replaces target/action. Primary exhaustion→WORK_EXHAUSTED/raw/no label; audit exhaustion→counted incomplete audit, primary unchanged. Any incomplete required audit blocks the audit acceptance gate and re-plan, not a retry with larger cap. Audit work is charged to generation but excluded from primary >1% fallback numerator. Here inject arbitrary clock delay and require solver status/result/counter bytes identical; action/label invariance is tested in C3 step 10. Watchdog aborts incomplete shard, never changes an action. Same command → **PASS**.

**6. Private tail calibration, no new search run.** On 2026-10-08, a read-only scan found **all five #236 exact-rescue records with tables/weights/foe probabilities/key retained privately**. Proposed `expert_calibrate.py`: `load_rescue_fixture_set(manifest: Path) -> tuple[RescueFixture, ...]`, requiring count 5 and SHA-256 fingerprints. Implement this private fixture loader after the red `pytest python/tests/test_search_numpy.py -k rescue_manifest_missing_stops` → **FAIL** test for count/fingerprint validation, then → **PASS** with synthetic files. At calibration time revalidate five payload hashes privately and run bounded/unbounded replay, recording counts/certificates/exhaustions; no fixture upload. Missing data or failed calibration is an explicit **STOP**, not permission to regenerate a full arena. Synthetic ill-conditioned fixtures in CI are additional tests, not substitutes for that gate. Caps needing revision require owner re-plan.

## C3 — teacher (four isolated risk steps)

**7. Full-space mapping.** Write `test_full_target_kl_and_displacement_ties` in `python/tests/test_expert_teacher.py`. Red: `pytest python/tests/test_expert_teacher.py -k full_target_kl_and_displacement_ties` → **FAIL**. Implement `include_student` and `full_target`: deterministic lowest-ranked displacement keeps K=8; illegal/duplicate ids, negative/nonfinite mass, sum outside 1±1e-6 raise. Values at 1024 joint indices, zero elsewhere. Synthetic NumPy KL reference must distinguish full-legal normalization from candidate-only renormalization; include tied candidates, absent raw id and raw already present. Same command → **PASS**. K+1 audit uses 1152 leaves/capacity 1024, reports changed action/value/certificate without pretending equality across restricted games.

**8. Leak trap first.** Write `test_teacher_foe_model_and_privileged_traps`. Red: `pytest python/tests/test_expert_teacher.py -k teacher_foe_model_and_privileged_traps` → **FAIL**. Implement `label_decision` using existing Honest public construction, a foe-sensitive synthetic net, and teacher-owned params only. Swapping a real-opponent-network mock with identical public prefixes must leave **world/table/label digests identical**; true-stat/bench mutations likewise. Privileged calls are patched to raise and must never execute. Include an injected-leak negative control that changes a digest, not a blind toy value. Refer to existing **`test_honest.py`, `test_search.py`, `test_search_numpy.py`** for boundary/certificate fixtures. Same command → **PASS**.

**9. Action likelihood.** Write `test_tau_execution_and_explicit_fallbacks`. Red: `pytest python/tests/test_expert_teacher.py -k tau_execution_and_explicit_fallbacks` → **FAIL**. Implement X sparse policy and keyed draw; target rows use log tau(executed), other requested rows use log raw(executed), forced/unrequested masks explicit. Labels only for admitted valid learner TURN/REPLACEMENT/PIVOT with >=2 legal actions; alternate learner seat by game id, actual rewards/bootstrap retained. Public sleep/confusion/queue causes explicit; no oracle/hindsight. Same command → **PASS**.

**10. Determinism first.** Write `test_teacher_resume_permutation_regrouping_clock_bytes`. Red: `pytest python/tests/test_expert_teacher.py -k teacher_resume_permutation_regrouping_clock_bytes` → **FAIL**. Implement key/config/shard cursor and history checkpoint contract plus admission state restoration. Compare complete canonical action/target/status/work bytes uninterrupted vs resumed, permuted input list, regrouped same logical tick and injected clock pauses. Pin 512 games/capacity 1024; permutation cannot change per-game leaves or label admission. Reject wrong runtime/device/config/key version and partial/incompatible resume. Same command → **PASS**. No GPU/cross-capacity trajectory bit claim.

## C4 — Learner v2 contract only; separate loop plan required

Proposed M12 module `expert_contract.py`: `validate_adapter(adapter: StudentAdapter, fixture: ContractFixture) -> ContractResult`. Fixtures include acting/waiting/terminal/truncated/preview/padded/opponent/held-out rows, sparse tau and stored GAE inputs. They contain no trained weights.

**11. Full-joint API test.** Write `test_full_joint_provider_normalization_and_gradient` in `python/tests/test_expert_contract.py`. Red: `pytest python/tests/test_expert_contract.py -k full_joint_provider_normalization_and_gradient` → **FAIL**, contract API missing. Implement validator/fixture only in M12. **Required Learner v2 signature:** `Model.full_joint_log_probs(params, obs, slots, legal_mask) -> jax.Array[B,1024]`; differentiated masked log-softmax over all legal joint actions, illegal=-inf, zero-legal requested row explicitly refused. `_evaluate` currently returns chosen logp/entropy/value; `Model.apply` already exposes full pair outputs, so this is a new learner-facing contract, not a new head. Learner v2 may reuse apply's normalized output, never candidate-only re-normalize. A synthetic provider with deliberate candidate-only normalization must fail; valid provider passes normalization/illegal/gradient tests. Same command → **PASS** for validator/fixture; real provider test remains a **separate Learner v2 CI gate**, not claimed delivered here.

**12. Loss/drift/GAE handoff test.** Write `test_learner_contract_gae_masks_drift_resume`. Red: `pytest python/tests/test_expert_contract.py -k learner_contract_gae_masks_drift_resume` → **FAIL**. Implement schema assertions/reference fixtures, not optimizer/trainer. Required Learner v2 plan: unchanged `returns.gae`/existing value loss/c_V/gamma/lambda, learner waiting rows included; actual rewards/done/bootstrap; no outcome MSE. Loss=`mean_target KL(tau||pi)+0.1*mean_non_target KL(pi49333||pi)+c_V*existing_value_loss`; each valid mean separate, padding/opponent/held-out gradients zero. Batch 4096=512 target+3584 non-target (waiting value-only); reference KL correct requested head, preview regularization allowed. Fresh Adam LR 3e-5/clip 0.5, max 4 epochs/128 steps, label visited once/epoch, padded tail, uniform weights. Stop after 2 epochs without 1e-4-nat held-out KL improvement, nonfinite or held-out reference KL>0.02; keep best epoch and exact optimizer/shuffle/RNG cursor resume. Pilot PPO-policy/magnet off; continuation owns its usual recipe and **its own data**. Same targeted command → **PASS** against synthetic reference; real loss/loop/drift/restore tests are acceptance steps in Learner v2's own plan/PR. Owner relays confirmation; no confirmed loop means no pilot run.

## C5 — evaluation and fixed resource ledger

**13. Pair/group gate.** Write `test_eval_pairings_groups_and_ci_stop` in `python/tests/test_expert_eval.py`. Red: `pytest python/tests/test_expert_eval.py -k eval_pairings_groups_and_ci_stop` → **FAIL**. Implement `make_eval_rows`/`evaluate_records` above with 2000 paired-seat bootstrap resamples. Primary student vs continuation 2048 games: point>=0.52/lower 95%>0.50. Student vs frozen 49333 another 2048: point>=0.53/lower 95%>0.50. Panel BC/3600/11000, **equal weights 1/3**, pinned hashes: student-minus-continuation pooled lower 95%>0. Required PP_/A/B/C and LL_ bucket-specific panel lower 95%>-0.03; missing/failing/inconclusive blocks promotion. All raw play, book/previewsearch off. Test swapped-seat pairing, no chosen-success endpoint, absent LL_, nonfinite/unfinished results and synthetic borderline CIs. Same command → **PASS**.

**14. Compute/fixed CLI.** Write `test_eval_compute_tolerance_cost_and_privacy`. Red: `pytest python/tests/test_expert_eval.py -k eval_compute_tolerance_cost_and_privacy` → **FAIL**. Implement `validate_compute`/`main` with **5% relative tolerance independently for actual CPU-core-seconds and GPU-seconds**, `abs(control-pilot)<=0.05*pilot`; pilot=0 requires control=0. Account generation/JIT/audits/restarts to arm; shared eval half each. Equal caps/steps alone cannot pass. Continuation is sized to measured pilot use by Learner v2; unable to match means incomplete/re-plan. CLI: `python -m duoforge_search.expert_eval --manifest PRIVATE --pilot PRIVATE --control PRIVATE --baseline PRIVATE --out PRIVATE`; bad manifest/pairing/compute/repository paths exit 2 with cause, complete report exit 0 even for FAIL/INCONCLUSIVE strength (structured status). Same targeted command → **PASS**. CLI defaults cannot silently alter seeds/panel/budgets.

Evaluation predeclared **12288 raw-play games**: two H2Hs 2048 each + panel 3 opponents×1024×2 arms=6144 + ladder 1024×2 arms=2048. LL_ is **included**, not an extra unbudgeted suite: every suite is half PP_/A/B/C and half LL_, paired seats within bucket. Thus panel per opponent/arm is 512 games/bucket; H2H 1024/bucket. No unlabelled comparison to P0's PP-only pool. Approved LL_ registry and fixed weights/hashes are prerequisites.

Reserve **60 GPU minutes evaluation/JIT, 30 training minutes per arm**, total120 minutes, eval charged 30/arm. Planning floor 5 completed raw games/s gives 12288/5=2457.6s=40.96min; add fixed20% timing margin8.19min +8min compilation allowance =**57.15min**, within 60. This is an explicit conservative **assumption**, not an existing throughput measurement. A fixed64-game evaluation smoke, included in the ledger/reserve, must verify>=5games/s and forecast incl.JIT<=60 min; otherwise STOP/re-plan **before training**. No shrinking groups/budgets to force fit. Matching actual training use still obeys 5% tolerance; 30 min ceilings do not imply equal actual use. Every measurement/failed setup/validation is charged; no run starts merely because this plan is merged.

Generation cap **8 CPU core-hours = 28800 cpu_core_seconds**, equivalent to the former 2 h ×4 cores with full use; this is no budget increase. Use the chosen core count in both arms. CPU wall time and allocated-core estimates are diagnostics, not the matching ledger or collection stop counter. At P0's 50 ms, 16k labels alone ~14min; ~15k games at 1/8 is only an initial order estimate. Smoke freezes eligible/valid targets/game, R, shard forecast and audit cost. Projected/actual 28800-CPU-second breach→STOP/re-plan; no extra rounds or worker changes after freeze. Primary work fallbacks>1% of selected eligible roots→STOP; public reconstruction refusals excluded from that numerator and reported separately. Wall watchdog aborts incomplete run, never timed raw fallback. Nonfinite/drift/leak/resume/strength failure or inconclusive required groups stop. No best-of-seeds trials, automatic scale-up or silent fixture replacement.

## Final owner gates

Owner approves this revised plan, the separate Learner v2 plan/API/control recipe, LL_ evaluation manifest and resource windows. CPU daytime generation and exclusive local GPU night windows must not contend with Learner v2 A/B/training. Documentation/small targeted tests can coexist. AWS only after engine meta coverage and a new owner budget. After code/CI/private-fixture/contract gates, schedule the bounded pilot/control/evaluation; R1 publishes aggregates/fingerprints only. P1 success requires a new promotion decision, not P2 execution.

All real rows/worlds/tables/checkpoints/runs stay outside repository and CI artifacts under `refuse_repository`. This PR changes only this plan. No approvals, test outcomes, learner integration or measured evaluation throughput are presumed complete.


## Owner amendment and Learner v2 handoff (2026-10-08)

Before the production freeze, compare **4/8/14 native workers** with the existing CPU honest teacher, frozen 49333, capacity 1024,512 root games, identical seeds/inputs and fixed OMP/OpenBLAS thread environment. Set affinity before the interpreter starts, so numerical helper threads inherit it. One warm-up and two timed repetitions per count; choose highest median **searched decisions / whole-probe elapsed time**, fixed tie-break lowest count. Also report service-only rate, process CPU seconds and identical decision/table/policy digests; a short prefix is not a full-game scaling guarantee. No generation labels or training are produced by the probe. Charge profiling/smoke/JIT/calibration inside the same 8-core-hour collection allocation; no gain in budget from higher concurrency. A later code/config change that invalidates this profile requires re-plan before a new freeze.

Confirm contract with Learner v2 [plan #244](https://github.com/chrismaghuhn/duoforge/pull/244) / [API #245](https://github.com/chrismaghuhn/duoforge/pull/245): **every learner row, including waiting rows, has required `logical_tick`**, the step index within its logical game. It is distinct from request_epoch and global batch tick. GAE reconstructs complete per-game chronological rows; row identity is (game_id, seat, logical_tick), so waiting rows with unchanged request epochs are not deduplicated. Missing/duplicate/regressing ticks refuse the relevant dataset/trajectory contract. Raw/teacher RNG still uses immutable decision keys, not batching positions. No training-loop implementation moves to M12.

Ledger wire keys are exactly **`cpu_core_seconds`, `gpu_seconds`, `phases`**. CPU is the sum of self+children user+system CPU-time deltas (native threads count in self); collect/reap child sections at phase boundaries or account their own reported deltas exactly once. GPU seconds sum wall duration of nonoverlapping synchronous device sections, including JIT, ending at a device completion barrier. CPU and GPU charges may overlap; never subtract one from the other. Phase charges sum to each axis' total; no allocated-cores×wall substitution for CPU. Both control and pilot use identical measurement code/core count, with the existing 5% tolerance independently on these two actual axes. Report wall-clock separately; watchdogs only abort incomplete work and never select a policy fallback.


### Worker probe result and proposed freeze

Existing main source `f985bbea` (before P1 code), checkpoint hash above, library 0.43.0, CPU JAX 0.11.2; 512 paired root games, max 6 batch steps, preview raw, capacity 1024, same seeds/public-world teacher. The probe searches up to 96 requests per repetition and then uses raw; 94 were actually searched. One warm-up plus two timed repetitions per worker count, affinity set **before process/interpreter/thread initialization**, OMP/OpenBLAS 4. Rates below are medians over the two timed repetitions. The whole-probe denominator includes raw controller/engine steps, not just search service. No strength result, generation labels or GPU work.

| Native workers / logical CPU affinity | Searches/s, whole probe | Searches/s, service only | Process CPU seconds, all three repetitions + setup |
|---|---:|---:|---:|
| 4 | 12.94 | 20.15 | 65.78 |
| 8 | 15.20 | 23.00 | 79.25 |
| 14 | 15.90 | 23.60 | 102.58 |

**Freeze 14 workers and 14 logical CPU affinity slots in both pilot and control**, under the same 28800 measured CPU-second cap. Highest median whole-probe rate chooses 14; 14-vs-8 is only about 4.6%, not a broad scaling claim. Valid comparison CPU cost 247.62s (0.069 core-hours); all nine decision/table/X-policy digests agree. Superseded setup probes remain private and are excluded from the throughput comparison; record profiling/setup charges separately before the production resource freeze. No private paths/tables/games are published. This short first-turn-prefix probe does not replace the generation forecast smoke or its budget/refusal gates.

## Evaluation seeds and runner order (2026-10-09, agreed with Learner v2)

The engine derives a battle's RNG from the batch seed, the environment index and the episode only (`duoforge_batch.h`), never from a per-game seed. So every row of a (suite, opponent, bucket) block carries **one batch seed**, the same for all its pairs, both arms and both seats. The runner (`duoforge_learn.p1_eval` over `evaluate.play_suite`) plays one batch per (block, arm, bucket, seat), with that seed and the block's pairs in pair order (environment = pair, episode 1). Pair p's battle RNG is therefore `duoforge_batch_seeds(seed, p, 1)` on both seats and in both arms. `_check_records` still requires each pair's seed to equal the schedule. Games cut off at the step limit stay unfinished and leave their group INCOMPLETE (owner, 2026-10-09). The 64-game smoke reports their count, and any cut-off is a STOP before the run.

## Owner amendment: Trick Room diagnostic (2026-10-09)

Trick Room (TR) is a plan that spans several turns. The search (one turn plus a value) sees it only through the net, so the owner expects weaknesses here. This amendment adds a **diagnostic** to the P1 evaluation. It needs no extra run: the 12288 evaluation games carry its fields in their records. It changes no gate, no promotion and no schedule. `evaluate_records` requires the new fields (a record without them is broken, not a game without TR) and includes them in `records_sha256`, but no gate status reads them.

**Record fields** (`expert_eval.TR_FIELDS`, part of `RECORD_FIELDS`). Every field is an integer per game. *Student* is the evaluated arm's seat, *opponent* the other seat.

| Field | Meaning |
|---|---|
| `tr_setter_student`, `tr_setter_opponent` | 1 if a member of that side's team sheet (brought or not) knows Trick Room (the side's own view at the first observation), else 0 |
| `tr_sets_student`, `tr_sets_opponent` | turns on which that side set TR |
| `tr_first_set_turn_student` | the view's `turn` before the student's first set; 0 if never |
| `tr_reversals_student` | the student ended an active TR **the opponent set** with its own Trick Room |
| `tr_blocks_student` | the student's chosen block attempts against the opponent's TR (see below) |
| `tr_turns` | observed turns that began with `trick_room_turns > 0` (at their TURN boundary; a same-turn replacement does not count) |
| `tr_unattributed` | field changes this rule cannot attribute |
| `tr_last_turn_choice` | 1 if a side chose Trick Room on the game's last turn, whose field change is never observed |

**Attribution** uses only public engine output and the chosen actions. No battle rule is re-implemented in Python:
- The field is `trick_room_turns` of the student's view before and after each turn.
- A turn **sets** TR when it goes from 0 to above 0.
- It **ends TR early** when it goes from above 1 to 0.
- The change is attributed to a side only if exactly that side chose a Trick Room move that turn (the move id of the chosen slot's move in that side's own view). Otherwise it counts in `tr_unattributed`; it is never assigned silently.

**Block attempts:** a chosen action while TR is inactive and the opponent's team has a setter, of one of these kinds:
- Taunt or Fake Out aimed at an opponent position whose occupant knows Trick Room;
- Imprison by a student occupant that knows Trick Room, while an opponent occupant knowing it is active.

Block attempts are chosen actions, not results.

Move identity comes from the data API: the named constant `TR_MOVES` (`trickroom`, `taunt`, `fakeout`, `imprison`), resolved with `data.find(ctx, TABLE_MOVE, name)`. This list classifies actions for the report only; it is no battle rule, and nothing in it feeds any decision. The tracker `expert_eval.TrickRoomTracker` is vectorized over the batch and has the hook form of `duoforge_learn.luck.Luck`: `start(n, seats)`, `before(batch, indices, active, step, last_step)` after each query and before the step, `after(batch, dead)`, then `fields`. It reads only the batch buffers of that query and changes none. Learner v2 hooks it into `evaluate.play_suite` and writes `fields` into the records. Known limit: a field change on the turn that ends the battle is not observed. The report text states it with the count of games where `tr_last_turn_choice` is 1.

**Report** (`expert_eval.trick_room_report(records)`), per arm and per suite, plus pooled over suites:
- **(a)** Games where the student's team has a setter, and games where the opponent's team has one, each with score rate and a 95% bootstrap interval (`BOOTSTRAP_SEED`, `RESAMPLES`, resampling games).
- **(b)** Set rate of the student, and the distribution of the first set turn.
- **(c)** Reversals and block attempts per game in which the opponent set TR, or (for blocks) the opponent team has a setter.
- **(d)** Score rate in games with `tr_turns > 0` against games without, each with its interval.

Unfinished games count for none of these.

Tests: `test_trick_room_tracker_attribution` (synthetic observations: set, early end, natural expiry, both sides choosing TR → unattributed, a mid-turn switch request, blocks, last-turn choice) and `test_trick_room_report_groups`. CLI: the report is part of the `expert_eval` output JSON.

## Owner amendment: the pilot runs on AWS (2026-10-09)

The first local attempt is superseded. On 2026-10-09 the generation finished locally on main `d3631151`: R = 39 frozen from the smoke (t = 534/512), 19968 games, 16384 targets, 0 cut-offs, 6173 CPU core-seconds. Distill then failed with a CUDA out-of-memory error on the local 8 GB GPU at its first step, after about 25 minutes of single-threaded shard loading that its ledger did not charge. The owner then moved the whole pilot to AWS. Its local shards serve only as a determinism cross-check against the AWS generation (shard SHA-256 lists) and are not used.

**Hardware:** one g6.4xlarge Spot machine (NVIDIA L4 24 GB, 16 vCPU, 64 GB, Frankfurt). It runs generation, distill, the control arm and the evaluation, so both arms' CPU core-seconds and GPU-seconds come from identical hardware and stay comparable within 5%. Ledgers from the local attempt are not mixed in. The worker freeze stays at 14 native workers on 14 logical CPUs, with OMP/OpenBLAS 4. Generation stays on the CPU, as frozen. One allocator setting holds for every GPU phase of both arms and is recorded in the report.

**Operation:**
- Only HauptSession starts and stops AWS machines, with the owner; every machine terminates itself.
- The run script is `tools/cloud/p1_pilot/run.sh` (Learner v2).
- Code, results, checkpoints, ledgers and logs stay in the private S3 bucket only.
- A Spot interruption is a pause at the last completed phase boundary. The run resumes from that boundary with the same commit and its own ledger. Work lost to an interruption is charged to its arm.

**Evaluation:**
- **Pool:** the 49333 training pool (652 teams: A/B/C and PP_ in the PP bucket, LL_ in the LL bucket, with its weights), approved by the owner as the LL_ registry. Its hash is pinned in the evaluation manifest.
- **Checkpoints** (file SHA-256 via `python -m duoforge_search.eval_manifest`, written after both arms are trained and before the evaluation smoke):
  - pilot and control: the arms' results;
  - frozen: params-49333;
  - panel: params-0 (BC), params-3600 and params-11000 of the many-c4e96e6 run;
  - ladder: params-39400 of the same run. The plan names a ladder opponent but never defines it. 39400 is the strongest ladder rung below 49333 (ladder Elo 749, 49333 768), so the separate ladder output faces a strong near opponent instead of duplicating BC. This is an M12 decision, not a gate: no gate group reads the ladder.
- **Seed and ids:** seed `0x2026100900000301`, first game id 10^9 (its own namespace).
- **Rate gate of the 64-game smoke:** measured on one extra warm call at full evaluation width (one block seat, 256 pairs, same players and form). That call is not recorded, but it is charged to the shared evaluation reserve, and its cut-offs and refusals count for STOP.
  - warm_rate comes from that call.
  - forecast = JIT + 12288 / warm_rate.
  - The thresholds are unchanged: any cut-off, any refusal, warm_rate < 5 games/s or forecast > 3600 s is a STOP.
  - The report shows both the narrow and the full-width rate.

### Control arm matching on AWS (owner decisions, 2026-10-09 evening)

**First AWS run** (2be0afe30d62-20261009T172944Z): generation took 16 min (4947 CPU core-seconds, 19968 games), loading 85 s and distill 1.3 min. The pilot ledger totals 5202 CPU core-seconds and 59.9 GPU-seconds.

**Calibration cap dropped:** the control's 10% calibration cap could not be met with a GPU budget of 60 seconds. One GPU update costs about 4.5 GPU-seconds and the match needs one warm update per device. The owner dropped the cap. It survives as a report field only; the binding rule stays both axes within 5% of the pilot. Calibration updates use the control recipe and count fully in the control's ledger.

**First control run discarded:** the continuation stopped with a compute mismatch. Control 4142 CPU core-seconds / 62.9 GPU-seconds against the pilot's 5202 / 59.9 put the GPU axis already outside 5% (|Δ| = 3.0 > 2.995) at −20% CPU. More training could not bring it back. Probable cause: the fixed GPU share left out the resume's GPU JIT (~13 GPU-seconds). The owner chose a fresh control run from params-49333. The discarded run and its ledger are reported but not charged. Pilot, generation and distill stay as run.

**The fresh control run** chooses each update's device by feedback (`train --update-gpu-share match`), with no calibration and no p1_match:
- Before each update it takes the device whose axis is further behind its pilot total.
- It never takes a device whose expected cost (the next update, including the JIT of a process's first update on that device) would push that axis above 1.05 of the pilot.
- It stops once both axes are ≥ 0.95. If no device is allowed before that, the run STOPs as incomplete; it never exceeds the tolerance.
- It runs in one process where possible, since every resume pays a JIT.

`expert_eval.validate_compute` checks the result unchanged: both axes within 5%.
