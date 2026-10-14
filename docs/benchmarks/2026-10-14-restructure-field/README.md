# Restructure 4: field helpers — fresh evidence after main merge

The current proof compares clean C8 main **`c8ca7cee2c8586cc135ddecc55ff850fa0f23b9a`** to clean field source
**`081efc0a9b4b0e3dc962d23ca332af36a78974de`**, which includes final main **`a7dd956bee87c0643cf0e4cf7c83772066f0e7a3`** by merge. Both **dirty=false**. The earlier `fcb4650e` functional report is a
preliminary run; its complete performance gate remains valid as proven below. Performance gate: **PASS**.

Machine: **8c91664c82d0**, INTEL(R) XEON(R) PLATINUM 8573C, x86_64;
Linux-6.18.44-x86_64-with-glibc2.41; GCC cc (Debian 14.2.0-19) 14.2.0. CPU quota `400000 100000`,
allowed CPUs [0, 1, 2, 3, 4], benchmarks pinned to CPU 4.
Node 22.23.3, Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc`; `OPENBLAS_NUM_THREADS=1`.
[Machine metadata](machine.json) and every paired result retain provenance.

## Exact change and behavior

Fifteen existing bodies move into seven private family headers in
`src/combat/field/`: weather, terrain access/effects/seeds, duration,
side conditions and Trick Room's dragged-entrant speed key. There are no whole
file renames. Extraction commit `d520d013` credits
`split from src/combat/turn.c@aca58173`; the table below compares with current main.
The 15 body implementations and all 266
remaining `turn.c` function bodies are byte-equal, including damage, move body and residuals.
`turn.c`: 12385 → 12185 lines.

Every original helper interface is private `static inline` in the same
translation unit. Grounding and weather suppression keep their old bodies in
ordinary static implementation functions with tiny inline delegating wrappers.
This prevents the transitive code expansion measured in the preliminary run.
No new public API, external field calls, heap allocation, table replacement,
large-function phase split, generated-data edits or test weakening.
Field setters and countdowns remain explicitly ordered in turn flow. No central
list or predicate is replaced, so a new classification-generator equivalence
test is not applicable here; the existing move-handler equivalence test runs.

| Original function | Main source | Field source |
|---|---|---|
| `dfi_grounded` | `src/combat/turn.c:197-204@c8ca7cee` | `src/combat/field/terrain.h:14-21` (`dfi_grounded_test`) |
| `dfi_terrain_field_detail` | `src/combat/turn.c:207-213@c8ca7cee` | `src/combat/field/terrain.h:31-37` (`dfi_terrain_field_detail`) |
| `dfi_weather_rock` | `src/combat/turn.c:229-241@c8ca7cee` | `src/combat/field/weather.h:10-22` (`dfi_weather_rock`) |
| `dfi_weather_suppressed` | `src/combat/turn.c:283-292@c8ca7cee` | `src/combat/field/weather.h:30-39` (`dfi_weather_suppression_scan`) |
| `dfi_field_weather` | `src/combat/turn.c:295-298@c8ca7cee` | `src/combat/field/weather.h:49-52` (`dfi_field_weather`) |
| `dfi_move_weather` | `src/combat/turn.c:303-309@c8ca7cee` | `src/combat/field/weather.h:57-63` (`dfi_move_weather`) |
| `dfi_weather_speed_ability` | `src/combat/turn.c:444-453@c8ca7cee` | `src/combat/field/weather.h:69-78` (`dfi_weather_speed_ability`) |
| `dfi_field_start_turns` | `src/combat/turn.c:247-250@c8ca7cee` | `src/combat/field/duration.h:14-17` (`dfi_field_start_turns`) |
| `dfi_entrant_speed_key` | `src/combat/turn.c:828-832@c8ca7cee` | `src/combat/field/trick_room.h:15-19` (`dfi_entrant_speed_key`) |
| `dfi_break_screens` | `src/combat/turn.c:4529-4544@c8ca7cee` | `src/combat/field/side_conditions.h:14-29` (`dfi_break_screens`) |
| `dfi_side_turns` | `src/combat/turn.c:10590-10597@c8ca7cee` | `src/combat/field/side_conditions.h:31-38` (`dfi_side_turns`) |
| `dfi_clear_terrain` | `src/combat/turn.c:5564-5577@c8ca7cee` | `src/combat/field/terrain_effects.h:12-25` (`dfi_clear_terrain`) |
| `dfi_seed_terrain` | `src/combat/turn.c:9916-9931@c8ca7cee` | `src/combat/field/terrain_seeds.h:13-28` (`dfi_seed_terrain`) |
| `dfi_terrain_seed` | `src/combat/turn.c:9935-9955@c8ca7cee` | `src/combat/field/terrain_seeds.h:32-52` (`dfi_terrain_seed`) |
| `dfi_terrain_change` | `src/combat/turn.c:9959-9978@c8ca7cee` | `src/combat/field/terrain_seeds.h:56-75` (`dfi_terrain_change`) |

[source-audit.json](source-audit.json) and [extraction-map.json](extraction-map.json)
record body hashes, aliases and source-token equality. Active documentation
anchors and the one datagen test docstring path are corrected; no parsing,
assertions, expected values or registration changes. Frozen research at
`cfe18c0` and historic benchmark source references remain frozen.

## P1–P6

- **P1:** 1415 → 1415 names, sorted SHA
  `d0198d53282ca919d046b226141abe12d8e1fbef6e0803ac95513199c6e72832`. Tier counts: 215 quick + 31 full +
  1151 reference + 18 slow.
  All runtime properties identical, including commands,
  working directories, environments and labels; registration backtraces omitted.
  C8 before/final merged after **223/223 IPO**
  and **218/218 no-IPO** pass,
  zero failures, disabled or skipped tests. All quick tests, layout, perft,
  search bench and lint run in both profiles; full Live and regeneration additionally with IPO.
  Full hosted CI remains the merge gate and starts with the PR.
- **P2:** 10 variants, 2584 executions,
  **1129 unique battles**, 22472 steps and 8458 stops
  per profile. All before/after result bytes equal **with and without IPO**,
  canonical result SHA `9753fed420cbcddceaa7e4de1e77a73fda9195b093e4cf9e98a06140dd6c7dfd`.
  Final merged full Live suite: 53/53 methods; POOL **11,680 equal**,
  **563 refused**, **4** explicitly refused Unburden records and **162** tracker
  stops, all the independent pins of main unchanged (see live-summary.json).
  The captured battle names exactly equal the current source battle catalog;
  no record is omitted. State, requests, events, RNG consumption and stops are hashed
  via the existing test-only `--digest-out`; original assertions still run.
- **P3:** perft passes in both profiles, 10 positions / 24 pinned depths; global pins SHA
  `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56` unchanged.
- **P4:** search bench passes in both profiles; global `BENCH_SHA256`
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798` unchanged.
- **P5:** all three `gen_closure --check` modes, tiebreak regeneration,
  independent format pins and `gen_move_handlers --check` pass.
  All 23 frozen source/provenance/data/pin hashes unchanged.
- **P6:** public include diff empty; **238 exports**, same type/name
  bytes in both profiles, SHA `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  33 public structs / 250 constants; raw layouts byte-equal, SHA `0bad5754bb4c85b07bbd99aa54a5700a8f2c82135b4eb75734b9fe86c8a3530e`.
  All 17 private helper names absent from both before/after shared libraries
  in both profiles: **68 negative symbol lookups**, no new exports.

| Variant | Battles | Before=after digest |
|---|---:|---|
| `duoforge_reference_conformance` | 90 | `620dd6f94faa5fc2751158f062c58edf75f48394aba7a9a49e6bc96bf8f9f271` |
| `duoforge_reference_conformance_pool` | 90 | `8be6753e961e86e6a8dbcb77e053f308ea71c31c12a6c11b5212a954fccf79a6` |
| `duoforge_reference_conformance_pool_data` | 966 | `8fbc168fb2199930340a1fabf4923bce5d2553ede17253bd215b7f1ad5b4d200` |
| `duoforge_reference_conformance_team_c` | 73 | `1acfad0da5393e2095176d094ab2748800b305cfbfee048e04f127a1720c39c5` |
| `duoforge_reference_conformance_team_c_pool` | 73 | `4459b937648f3e470ffee6da4761ce0f3d54b2c19f59906774888844bb515792` |
| `duoforge_reference_tiebreak` | 90 | `b374c2d908d5bd00776a571f7bc6842722f0fb6e6401c9770b3f27001c07e4ea` |
| `duoforge_reference_tiebreak_pool` | 90 | `f0d14608caf783a1f99c79dfb78265e18878aaa139865c7ce3500f10635d41cb` |
| `duoforge_reference_tiebreak_pool_data` | 966 | `9bc7b21e8cfc6994147dcc7843581d2a1a08f63aaf1d9db2417511615cd1049f` |
| `duoforge_reference_tiebreak_team_c` | 73 | `78e1cb58a1fd273b438d99fb9d5db2bdc876b174da5bc73339bc002b2de7fb34` |
| `duoforge_reference_tiebreak_team_c_pool` | 73 | `c63fe2df60c180eff91e1c81d297036b2873a342cc32016dab93ae8165ad913b` |

[proof-summary.json](proof-summary.json), [test-inventory.txt](test-inventory.txt),
[per-battle-digests.tsv](per-battle-digests.tsv) retain counts, hashes and all fixture
names. No raw state/request/event/replay payload is published.

## Performance gate carried forward with HS approval

**Direction:** `100 × (after/before − 1)` is the change in elapsed time.
**Positive = slower; negative = faster.** Throughput is the reciprocal ratio.
Measured binaries: main `aca58173d389613b6b4a89a95d8b1b5e3fe7b2fa`
versus field `d15b13afe6b2418487233b0492ec9abdc5b6bc8c`, both **dirty=false**,
on the machine above. The complete 32-pair result is carried forward with HS's
explicit authorization. `git diff --quiet` proves that **all** C/public-header,
C-build CMake settings and CI, benchmark, reference/data/pin and generator/tool inputs match
final main and final merged field respectively.
[performance-carry-forward.json](performance-carry-forward.json) records those
exact commits and path scopes. The eventual report-only PR-head commit changes
none of those inputs. These timing results are the complete earlier measurement,
not new timings of the Python-only merged commits.

Fixed protocol: **32 change pairs and 32 identical-binary control pairs per
profile**, four series rotated across positions (eight per position), 16 AB and
16 BA orders. Each side: 1,024 battles per closure pairing, two warmups,
three timed repetitions, plain and Events, policy seed 20261001/battle seed 7001,
max steps 128, CPU 4. No build/test overlaps measurement. All samples of the complete run retained.
Median of 32 paired median-time ratios; 20,000 paired-bootstrap median resamples,
seed 20261012, percentile 95% interval. Gate: median time ratio ≤1.02 **or** inside
matching A/A 95% interval. This is an observed-median gate; broad confidence
intervals do not certify a true loss below 2% on every machine.

| Profile | Workload | Time change | Change 95% CI | A/A change | A/A 95% CI | Gate |
|---|---|---:|---|---:|---|---|
| ipo | plain | +1.34% | [+0.18%, +5.11%] | +0.32% | [-2.46%, +1.88%] | pass |
| ipo | events | +0.27% | [-1.32%, +1.10%] | +0.38% | [-0.89%, +3.71%] | pass |
| noipo | plain | +0.38% | [-1.10%, +3.96%] | -0.92% | [-3.21%, +0.96%] | pass |
| noipo | events | +0.24% | [-0.78%, +1.90%] | -0.30% | [-2.42%, +0.90%] | pass |

[paired-bench-ipo.json](paired-bench-ipo.json),
[paired-bench-noipo.json](paired-bench-noipo.json),
[control-ipo.json](control-ipo.json), [control-noipo.json](control-noipo.json)
retain every pair's provenance, all timed samples and the raw manifests.
Identical-binary controls use the exact same baseline file twice (matching SHA).
All records/choices agree, zero errors, truncations or time skips.

## Inlining and call sites

`objdump -d` conservative reachable Events graphs include compiler clones,
tail jumps/cold branches and resolved local PLT targets; counts are static call
instructions, not dynamic invocations. IPO bench folds wrappers into a shared
internal implementation. Grounding/suppression body aliases are normalized to
original identities; actual names remain in [call-audit.json](call-audit.json).

| Artifact/profile | Direct call sites main → field | Indirect call sites |
|---|---:|---:|
| ipo-bench | 695 → 700 | 1 → 1 |
| ipo-shared | 1357 → 1362 | 1 → 1 |
| noipo-bench | 1306 → 1311 | 3 → 3 |
| noipo-shared | 1339 → 1344 | 3 → 3 |

Per-helper definitions, direct/tail calls and changed edges are preserved in
that audit. Tiny wrappers have no out-of-line call sites; body predicates retain
main's calls. Terrain-seed inlining duplicates instruction sites in its two
callers; source ordering and runtime work are unchanged. No calls across new
translation-unit boundaries and no exported field helpers.

## Final-main merge and performance applicability

HS moved the Content collection after this PR. #483 and #486 are merged in
`a7dd956bee87c0643cf0e4cf7c83772066f0e7a3`; this branch includes it by merge, never rebase. The diff
from C8 contains exactly 15 Python/documentation paths.
[upstream-audit.json](upstream-audit.json) lists every path and the protected
input areas. All 48 CMake registration/build files have identical blobs;
C/public headers, generated reference/data and pins, CI/build flags, benchmark
workloads and reference tooling are unchanged. Therefore the C8 baseline and
performance-input baseline remain applicable to final main. The complete earlier
performance gate applies unchanged by the full source/input equality proved above.
Its 128 pairs were independently re-verified, including artifact hashes,
compiled revisions, AB/BA orders, all samples and matching controls. The
unnecessary additional run on the merged head was stopped after the owner's
question, has no final statistic/gate, and is **not** used as performance proof.
Its 59 partial pairs are retained outside the checkout; counts/status are in
[additional-run-status.json](additional-run-status.json).

Build, tests, all reference captures in both profiles, perft, BENCH_SHA256,
layouts and exports were rerun on `081efc0a9b4b0e3dc962d23ca332af36a78974de`, after the final merge. The
1,415-name C8 inventory also represents final main because registration files
are identical. Functional proof results were rerun after the merge.
The `fcb4650e` functional report remains a preliminary run; its complete timing
gate is applicable because the measured inputs are unchanged, as explicitly
authorized by HS.

## Reproduction and review

[proofs.py](proofs.py) lists the actual commands and selection; collect metadata
**after** build. [matched-bench.py](matched-bench.py) is the exact fixed protocol;
adapt outside-repo paths only. The artifacts live outside the checkout during
runs. Docs publish only public-fixture hashes and aggregate timings/counts.
No weights, checkpoints, run directories, private replay or live logs are committed.
A self-review checks source-token/body equality, support-table preservation,
public linkage, output privacy and unchanged tests; no blocking security findings. Unit/reference/data/perft/bench
and source lint gates apply. UI e2e is not applicable to this internal C extraction.
Coverage: no configured instrumentation/threshold gate for this restructure
(not applicable; a project coverage job would improve numeric coverage evidence); the owner-prescribed
P1–P6 and independent source-body witnesses are used.

Prepared with Codex using fullstack-dev-kit:create-pr. HS merges; no PR is merged
or auto-merge enabled by this branch.
