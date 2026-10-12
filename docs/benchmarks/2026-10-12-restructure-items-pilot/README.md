# Restructure step 3: item families and White Herb pilot

## Question and result

Can the existing item families and one bounded item effect leave the turn
monolith without changing battle behavior, test selection or the public surface?
The pilot extracts type-booster/resist-berry effects, live held-item access and
White Herb. Both IPO profiles retain every baseline reference digest, perft pin,
search signature, public layout and exported symbol. Timing results are mixed;
this report makes no performance-neutrality or speedup claim.

Baseline: **`ca17e507`**. Implementation/visibility regression/format-fact naming:
**`3a9d04d1`**. Main was fetched again and remains `ca17e507`; no rebase or main push.
The branch is `restructure/3-items-pilot`. **No PR has been opened**: HS must
release the Astra slot first. Before opening, fetch/merge current main and repeat
any proofs affected by that merge. HS alone merges the PR; PR-head CI remains
the merge gate even if this branch's manual CI is green.

## Implementation and lineage

The turn still chooses applicability, damage-chain position, handler collection,
speed sorting and RNG use. Item consumption remains its existing
`dfi_use_item`/AfterUseItem/Unburden/Symbiosis path; the berry and White Herb
helpers receive that exact function as a private callback. There is no handler
registry, added rule, allocation, changed field, event or draw order.

The private `dfi_run` scratch definition is copied unchanged, including field
order and lifetime. Position/event helpers are private inline definitions.
The moved position access names the existing `DUOFORGE_ACTIVE_PER_SIDE` (**2u**):
all four affected translation units have byte-identical expanded inputs before
and after this naming change ([witness](named-format-constant.json)).
[body-equivalence.json](body-equivalence.json) checks ten extracted bodies,
normalizing only that constant name and the supplied useItem callback name.
The turn file decreases from **12,678 to 12,489 lines** (189 lines).

| File move | Destination | Move commit |
|---|---|---|
| `src/combat/item_family.h` | `src/combat/items/families.h` | `67987baf`, git mv, **100% rename only** |

Includes/comments are edited only after that move commit. Function splits carry
their source credit: family/common extraction `6d4bab9d`, White Herb `7c3a5c52`.
The complete [function-extractions.json](function-extractions.json) map is:

| Function/type/constant | Old source | New source |
|---|---|---|
| `dfi_run (unchanged layout)` | `src/combat/turn.c@ca17e507:40-108` | `src/combat/run_internal.h:12-80` |
| `dfi_pos` | `src/combat/turn.c@ca17e507:121-124` | `src/combat/run_internal.h:82-85` |
| `dfi_at` | `src/combat/turn.c@ca17e507:127-134` | `src/combat/run_internal.h:88-95` |
| `dfi_emit` | `src/combat/turn.c@ca17e507:459-464` | `src/combat/run_internal.h:97-102` |
| `dfi_ev` | `src/combat/turn.c@ca17e507:467-474` | `src/combat/run_internal.h:105-112` |
| `dfi_item_code` | `src/combat/turn.c@ca17e507:305-324` | `src/combat/items/held.c:9-28` |
| `dfi_holds` | `src/combat/turn.c@ca17e507:327-330` | `src/combat/items/held.c:31-34` |
| `dfi_item_takeable` | `src/combat/turn.c@ca17e507:370-374` | `src/combat/items/held.c:42-46` |
| `dfi_type_booster_base_power` | `src/combat/turn.c@ca17e507:2078-2083` | `src/combat/items/families.c:4-14` |
| `dfi_resist_berry_hit` | `src/combat/turn.c@ca17e507:2302-2310` | `src/combat/items/families.c:19-33` |
| `dfi_herb_due` | `src/combat/turn.c@ca17e507:3636-3648` | `src/combat/items/white_herb.c:5-17` |
| `dfi_white_herb` | `src/combat/turn.c@ca17e507:3653-3665` | `src/combat/items/white_herb.c:22-34` |
| `dfi_herb_holder` | `src/combat/turn.c@ca17e507:3715-3719` | `src/combat/items/white_herb.c:38-42` |
| `DFI_POSITIONS` | `src/combat/turn.c@ca17e507:37-37` | `src/combat/run_internal.h:10-10` |

`542d04de` is the separate step-2 follow-up requested by HS: only the two specs
reads in `format_pins.py` and `_reference_pins.load` gain `encoding="utf-8"`.
Both readers pass under an ASCII default locale for **1,129 specs / 1,056 live
pins** ([utf8-check.json](utf8-check.json)); no parsing/assertion/expected-value
changes. `70af1214` adds one case to the existing Python layout suite (4 → 5)
to reject all eight newly shared item helper names at the actual DLL boundary.
It introduces no CTest name or property change.

## P1: test inventory and execution

Before/after **1,407 names identical**, SHA-256
`fbd60c25eedbe427e6097993964249e12d5b39e30fdd167137fbb00b2b305913`.
[test-inventory.txt](test-inventory.txt) and
[inventory-comparison.json](inventory-comparison.json) retain the sorted
`ctest -N` inventory and complete per-test JSON comparison: commands, working
directories, environment, labels, timeouts, fixtures and registration order
are unchanged; only registration backtraces are excluded.
Exactly one tier each: **207 quick + 31 full + 1,151 reference + 18 slow**.
CI selectors and workflows have no diff.

[local-test-results.json](local-test-results.json): **242/242 CTests** on the
final IPO implementation (238 quick/full + 3 data regenerations + tiebreak
regeneration), plus **6/6** selected no-IPO checks; no failure/skip/disabled.
The IPO run includes frozen-pin `--check`: **1,129 certificates/fixture pins
and 1,056 live pins**. The baseline proof selection passed 9/9.
Both full native P2 captures also execute all original runner assertions.

Manual branch CI on source **`3a9d04d1`**:
[12-job matrix](https://github.com/chrismaghuhn/duoforge/actions/runs/38302940369),
[RNG reference](https://github.com/chrismaghuhn/duoforge/actions/runs/38306118385).
**All 12 matrix jobs and the RNG check are green** on that source commit,
recorded in [ci-results.json](ci-results.json). The
conditional quick-profile guard is intentionally skipped in full mode.
Windows GCC/Python/reference already passed **1,407 registrations**, including
`duoforge.python.layout` with its new export guard (0.15 s); JAX-only skips are
the workflow's existing allowance. The earlier run on `7c3a5c52` was superseded
by the current source/guard run and is not a final proof. Fresh PR-head checks
will run after HS releases the slot; no CI timeout or scheduling changes.

## P2: every reference result

[reference-results-before.json](reference-results-before.json),
[reference-results-ipo.json](reference-results-ipo.json) and
[reference-results-noipo.json](reference-results-noipo.json) are **byte-equal**:
each profile has **10 variants / 2,584 executions / 1,129 unique battles**,
**11,236 steps / 8,458 stops**. Complete JSON SHA-256:
`712387e820ed6a87f21ac8e047f384abab71fbb80ea99f0e1487a5de846d35e7`.
Every per-battle hash is retained, not merely dataset aggregates. Capture uses
the internal step-2 digest tool; its same-commit observer witness remains in the
step-2 report. No reference payload/trace/spec/pin is moved or regenerated here.

| Variant | Battles | Before = IPO = no IPO SHA-256 |
|---|---:|---|
| `duoforge_reference_conformance` | 90 | `620dd6f94faa5fc2751158f062c58edf75f48394aba7a9a49e6bc96bf8f9f271` |
| `duoforge_reference_conformance_pool` | 90 | `af3d4958fd43894492aac19e7911b5b5d9e266fc7afa81cb7a70cc0d878be174` |
| `duoforge_reference_conformance_pool_data` | 966 | `c452a188b6fd32a5796f9b3181a69542b6be335d4ea5a2c9a1b286da3b36d36b` |
| `duoforge_reference_conformance_team_c` | 73 | `1acfad0da5393e2095176d094ab2748800b305cfbfee048e04f127a1720c39c5` |
| `duoforge_reference_conformance_team_c_pool` | 73 | `a951cbfde3e2f00a7ccd9848f7e031f8e3199eea29ce9505cd9bb44713784812` |
| `duoforge_reference_tiebreak` | 90 | `b374c2d908d5bd00776a571f7bc6842722f0fb6e6401c9770b3f27001c07e4ea` |
| `duoforge_reference_tiebreak_pool` | 90 | `5d2dcf40c944203659d77ed19f7b1e42eaaece4cde930b9bf5d392971eaeaab9` |
| `duoforge_reference_tiebreak_pool_data` | 966 | `866ff996d0a311c1f394a5cbc42a8683ae8c24852ed6ad5854e1d5dd8b7d625b` |
| `duoforge_reference_tiebreak_team_c` | 73 | `78e1cb58a1fd273b438d99fb9d5db2bdc876b174da5bc73339bc002b2de7fb34` |
| `duoforge_reference_tiebreak_team_c_pool` | 73 | `6eb6ff381045b710ff04748b0faa5ce587cdcb961a31afc73fddf5af93a40fec` |

## P3–P6

[verification.json](verification.json) and [source-hashes.json](source-hashes.json)
retain the counts and **20 unchanged source hashes** for data tables, their
generator, public headers, binding layouts, perft pins and the search bench.

- **P3:** perft passes in both profiles: **10 positions / 24 pinned depths**;
  pin-file SHA-256 `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both profiles pass the **2-case / 8-root / 7-searched-root** search
  bench; `BENCH_SHA256` stays
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** closure/extended/pool `gen_closure --check`, conformance and tiebreak
  regeneration checks, and frozen battle-pin `--check` pass. Generated data,
  IDs, table ordering, per-battle observations and the independent format pins
  have no diff. UNMODELED pins remain **146 moves / 18 items / 90 abilities**.
- **P6:** public-header diff empty; both profiles retain the same **238**
  exported type/name entries, SHA-256
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`;
  [layout.json](layout.json) retains **33 structs / 250 constants**, SHA-256
  `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`.
  [exported-symbols.txt](exported-symbols.txt) contains no new entry.

Only the new item declarations have hidden visibility on ELF. On Windows their
definitions live in an archive outside CMake's `WINDOWS_EXPORT_ALL_SYMBOLS`
object scan; GNU PE also gets `--exclude-libs` for precisely that archive. MSVC
keeps its existing shared-library IPO policy. Existing exports remain public;
the new layout case verifies eight negative symbol lookups, including Windows
MinGW. No public API/ABI change or library-wide visibility change.

## Bench with IPO on and off

[bench-comparison.json](bench-comparison.json) records samples, CPU/wall timing,
manifests and counter equality. Same cloud/toolchain: GCC 14.2.0, Release
`-O3 -DNDEBUG`, CMake 4.4.4/Ninja 1.13.2, CPU quota **4**, no competing local
build/test during timing. Native: **2 warmups / 9 repetitions**, four closure
pairings, **512 battles each** (2,048), cap 128 steps, fixed policy/battle seeds
20261001/7001. The work is identical before/after in both profiles:
**37,199 steps / 27,204 turns / 66,803 side decisions**, zero errors/truncations
and identical move/choice tallies. No repetition is marked disturbed by the
driver's CPU/wall criterion.

Search: the existing `Bench.signature()` with all margin assertions and the
pinned hash, **1 warmup / 5 repetitions**, `OPENBLAS_NUM_THREADS=1`, hash network
(no trained weights). Native closure timing does not exercise Team C's White
Herb; whole-battle Team C references and the pool search cover the integration.

| IPO | Workload | Before median ms | After median ms | Change |
|---|---|---:|---:|---:|
| on | STEP_CORE / plain | 357.944 | 371.625 | +3.82% |
| on | STEP_CORE / events | 364.096 | 393.768 | +8.15% |
| on | EPISODE_NATIVE / uniform-random | 575.871 | 597.731 | +3.80% |
| on | pinned honest search | 2982.413 | 2555.788 | -14.30% |
| off | STEP_CORE / plain | 435.949 | 408.343 | -6.33% |
| off | STEP_CORE / events | 424.384 | 427.173 | +0.66% |
| off | EPISODE_NATIVE / uniform-random | 703.446 | 634.386 | -9.82% |
| off | pinned honest search | 2473.761 | 2321.056 | -6.17% |

These are one environment/sample per profile, not a clean causal speed estimate.
In particular the native events profile with IPO is **+8.15%**, while the search
and no-IPO observations often move the other way. No unmeasured neutrality or
improvement is claimed and no behavior/test change was made to improve timings.
No-IPO timings were captured on `7c3a5c52`; after constant naming the final
shared library is byte-identical to the measured one. IPO timings use `3a9d04d1`.

## Location-dependency audit

Active C/C++, Python, CMake, shell, CI, generators and docs have no remaining
`combat/item_family.h` consumer. The item-family test changes only its include
and explanatory path. Shared helpers retain their names/bodies; consumers now
include the private item interface. Reference runners, fixture paths, CTest
invocations, public headers and generated-data inputs remain at their old paths.

[doc-citation-map.json](doc-citation-map.json) maps **35** numbered decision
citations to named helpers. Approximate/abbreviated turn references are also
replaced; `dfi_place` correctly points at `src/state/identity.c`. The independent
historical expansion reports and generator entries are explicitly tied to their
`cfe18c0`/`1aab4c2` snapshots; the third-team citation is a `3133fcc` permalink.
Their generated inventories are retained unchanged rather than hand-edited to
pretend they describe the modern engine. The held-item/header/test paths in
decision 0015 are updated as well. No private weights, checkpoints, replay data,
live logs or run directories are committed; evidence here is public counts,
fixture names, hashes and source paths only.

## Reproduction

Configure as CI: Python 3.12 with NumPy and JAX/optax, Node 22, exactly the pinned
Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc`, `OPENBLAS_NUM_THREADS=1`.
Use one Release build with `-DDUOFORGE_ENABLE_IPO=ON`, another with it `OFF`.
Set existing `DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`, `DUOFORGE_NODE` and
`DUOFORGE_PS_REFERENCE_DIR` options. Keep captures outside the repository:

```sh
cmake --build build/restructure --parallel 4
ctest --test-dir build/restructure -L '^(quick|full)$' --parallel 4 --output-on-failure
ctest --test-dir build/restructure -R '^duoforge\.(data\.(closure|extended|pool)_regen|reference\.tiebreak_ref)$' --output-on-failure
python tools/restructure/capture_reference.py . build/restructure <outside-repo-ipo-output>
python tools/restructure/capture_reference.py . build/restructure3-noipo <outside-repo-noipo-output>
build/restructure/bench/duoforge_bench --battles 512 --repetitions 9 --warmup 2 --max-steps 128 --families step,events,episode --out <outside-repo-ipo-bench.json>
build/restructure3-noipo/bench/duoforge_bench --battles 512 --repetitions 9 --warmup 2 --max-steps 128 --families step,events,episode --out <outside-repo-noipo-bench.json>
```

To repeat the search timings, set `PYTHONPATH=<repo>/python:<repo>` and
`DUOFORGE_LIBRARY` to the profile's shared library; run the same snippet in each
fresh process (no CTest/build in parallel):

```python
import statistics, time
from python.tests.search.test_bench import BENCH_SHA256, Bench
test = Bench()
assert test.signature()[1] == BENCH_SHA256  # warmup, all existing assertions
samples = []
for _ in range(5):
    start = time.perf_counter()
    rows, digest = test.signature()
    samples.append(time.perf_counter() - start)
    assert digest == BENCH_SHA256
print(samples, statistics.median(samples), digest)
```
