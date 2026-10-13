# Content files: one definition per move, ability and item

Status: **owner-approved**, 2026-10-12 (the six decisions are in section 10, after the HS review on #452). Addendum to
`2026-10-11-extension-system-design.md` (owner-approved) and to
the restructure plan `../plans/2026-10-11-repo-restructure.md` (steps 0-2 merged at ca17e507, step 3 in preparation).
Design only: no product code, no build and no measurement were made for this document; every number below is read from
the repository at ca17e507 or from the two documents above.

## The owner's idea and what this addendum decides

The owner's idea (2026-10-12): create one file for **every** move, ability and item of the format at once. An entry the
engine does not support yet gets a stub that refuses by name. Each agent then works in its own file, and what is missing
is visible at a glance.

This addendum keeps the idea and fixes the one thing that would otherwise defeat it: most moves are "damage plus one side
effect", whose logic must exist once, not five hundred times. So the design has **two layers**:

- **One definition file per entry** (`data/entries/<kind>/<showdown-id>.toml`): the modelling decision, the pinned source
  facts, the support status with its refusal cause, the family row, the owned numbers and state, the evidence pointers.
  Every entry of the format has one, supported or not. This is the file an agent owns.
- **Code per family or per bespoke mechanic, never per data-only entry.** A family (type booster, protect variant, two-turn
  charge, ...) is one C file whose rule reads the rows; a true one-off (Knock Off, Ally Switch) is one C file of its own.
  Data-only entries have no code at all.

Everything that is a hand-maintained central list today (the handler ids and facts in `gen_closure.py`, the marks in
`support_manifest.c`, the `md->special != ...` allow-list, the hand-assigned draw sites and residual kinds, the lines of
`docs/support/README.md` and of decision 0015) is **generated from the entry files**. A content PR then touches its own
files plus regenerated output; with the pin per entry (section 6) no shared hand-edited line is left.

## Measured starting point (main ca17e507)

| What | Today |
|---|---|
| Pool rows | 511 moves (340 marked), 215 abilities (125 marked), 166 items (132 marked), 347 formes; about 295 unmarked rows |
| Move handler ids | `DFI_SPECIAL_*` 0-121 in a `uint8_t` column, positional in the generator's `SPECIAL_IDS` list |
| Dispatch in `turn.c` (12,678 lines, about 300 functions) | about 150 `md->special ==` comparisons, about 270 `DFI_ABILITY_*` references, 50 `dfi_holds(...)`; families exist for two item kinds and four ability kinds only (`item_family.h`, `ability_family.h`) |
| The move-special phase gate (step-4 update) | Generated `dfi_special_has_handler` / `dfi_special_status_hit` tables in `src/combat/generated/move_handlers.h`, from explicit phase classes in `tools/datagen/move_handler_source.py`; checked against the frozen old predicates |
| Facts against the pin | about 60 `*_FACTS` tuples and 35 `check_g*_facts` functions in the 5,885-line generator |
| Number spaces assigned by hand | draw sites (26 used of 34, lane ranges frozen by HS), residual kinds (26), volatile and position flag bits, tail bytes, 52 view-extension feature bits |
| Classification (`docs/research/expansion/data/classification.json`, an older head) | moves: 140 pure data, 146 data plus a generic extension, 142 family members, 87 bespoke; abilities: 186 family, 128 bespoke; items: 81 Mega Stones, 68 family, 17 bespoke |
| Retro (the spec's basis) | median step: 13 artifact kinds, 41 files; 82 merges renumbered shared ids; one collision reached `main` |

## 1. Granularity: what gets a file, what gets code

**Decision.** Three handler classes, stated in the entry file (`[model].handler`):

| Class | Entries (by the classification) | Code | What the agent writes |
|---|---|---|---|
| `data` | pure-data moves (a secondary status, volatile or boost, recoil, drain, flags), Mega Stones, inert entries | none: the generic move path runs the row | the entry file and the evidence |
| `family` | protect variants, two-turn charge, semi-invulnerable, hazards, screens, weather accuracy, base-power predicates, status and stat-drop immunities, -ate, pinch, contact triggers, type boosters, resist and cure berries, extenders, seeds, ... | one C file per family in its area folder; it reads `(family, params)` rows and names no member | a row in the entry file; the family file only when the family is new |
| `bespoke` | the true one-offs: Knock Off, Trick, Ally Switch, Substitute, Skill Swap, Illusion, ... | one C file per entry in its area folder, registered by the entry file | the entry file, the C file, the tests |

**Rule for "needs code".** An entry needs code exactly when its pinned source has a callback, condition or field that no
table column and no family row models. That is the generator's existing `entry_features` test (the UNMODELED column). The
generator refuses a `data` entry with such a feature, and a `family` row whose pinned handler deviates from the family's
pattern (decision 0015 section 2, today's rule). The class is checked, not trusted.

**Why not one C file per move.** 140 pure-data moves would become 140 files that call the same generic path, and the 146
class-B moves would copy the same secondary handling with one flag each. Copies drift (the retro's duplication items), the
review cost grows with the copies, and the hot path gains a call per move for nothing. The owner's goal, an own file and
visible gaps, is met by the entry file; the code layer is where it creates no copies.

**Why not families only, without entry files.** Then the modelling decision, the pin facts, the status and the evidence
pointers stay scattered over the generator's dictionaries, the manifest and 0015, which is the measured conflict and the
reason the gaps are invisible today.

**Formes.** Species data (stats, types, learnsets, legal abilities) stays derived from the pin into the pool tables. A forme
gets an entry file only when it carries behaviour (Aegislash's Stance Change; a Mega pair's rules sit on the stone's and
the ability's entries). No file per species (owner decision 3).

## 2. The entry file

**Format: TOML** (owner decision 1), read with `tomllib` (standard library since Python 3.11; the three CI Python jobs
run 3.12, `ci.yml:172, 340, 424`, and so does the VPS on Ubuntu 24.04, checked by HS). Alternatives: JSON (no
comments, poor for multi-line facts); a C header fragment per entry with X-macros (a compile-time registry without a
generator, but no place for facts, docs and status, and the include list is a central file again). The generator exists and
checks facts already; the file format only has to be diff-friendly and editable by hand.

Each file holds only what the pin cannot give. The generator keeps deriving type, power, accuracy, PP, flags, secondaries,
family parameters and learnsets from the pinned sources (one source for data). The entry file holds the **decisions**:

```toml
# data/entries/moves/knockoff.toml   (bespoke)
[entry]
kind = "move"
id = "knockoff"                       # the Showdown id; the file name
name = "Knock Off"
status = "supported"                  # supported | refused
since = "G16"                         # the step that implemented it

[pin]                                 # the generator checks that every fact is still in the pinned entry, whitespace aside
gen9 = "data/moves.ts:9887-9918"
champions = "data/mods/champions/moves.ts:512-519"
facts = [
  "onBasePower(basePower, source, target, move) { const item = target.getItem(); ...",
  "onAfterHit(target, source) { if (source.hp) { const item = target.takeItem(); ...",
]

[model]
handler = "bespoke"
source = "src/combat/moves/knock_off.c"
hooks = ["move.base_power", "move.after_hit"]     # the hook points its functions answer (generated switch cases)
limits = ""                                       # shapes refused at run time with E_UNSUPPORTED, if any

[state]                                           # storage the entry owns (hand-assigned until part D; two owners fail)
tail = ["item_now"]
view_features = ["ITEM_CHANGE"]

[evidence]
tests = ["tests/moves/knockoff/"]
scenarios = "tests/scenarios/moves/knockoff/"
battles = ["g16_knockoff_*"]                      # reference battle name patterns under tests/reference/battles/<format>/
doc = "docs/mechanics/moves/knockoff.md"
decision = "0015#5aj"                             # the frozen 0015 entry id (the redirect table of plan step 11)
```

```toml
# data/entries/items/charcoal.toml   (a family row)
[entry]
kind = "item"; id = "charcoal"; name = "Charcoal"; status = "supported"; since = "P2"
[pin]
gen9 = "data/items.ts:1101-1112"
[model]
handler = "family"; family = "type_booster"; params = { type = "Fire" }
[evidence]
battles = ["p2_booster_fire"]; crosscheck = "pool_families.js"; doc = "docs/mechanics/items/type_booster.md"
```

```toml
# data/entries/abilities/moldbreaker.toml   (a stub)
[entry]
kind = "ability"; id = "moldbreaker"; name = "Mold Breaker"; status = "refused"
refusal = "onModifyMove sets move.ignoreAbility; the breakable flag of every ability hook is not modelled (family mold_breaker, 3 members)"
[pin]
gen9 = "data/abilities.ts:2651-2663"
[model]
handler = "none"; family = "mold_breaker"      # the classification's family, for the status report only
```

```toml
# data/entries/moves/appleacid.toml   (data only)
[entry]
kind = "move"; id = "appleacid"; name = "Apple Acid"; status = "supported"; since = "C2"
[pin]
gen9 = "data/moves.ts:655-668"; champions = "data/mods/champions/moves.ts:40-43"
fields = { basePower = 90 }                    # a value the implementation relies on (today's check_c2_facts)
[model]
handler = "data"
[evidence]
battles = ["c2_*"]
```

The line numbers in the examples are illustrative; CF0 (section 7) takes the real ones from the table comments.

**Families** have a file of their own, `data/entries/families/<family>.toml`: the parameter schema, the hook points the
family answers with their Showdown priority, the C source, the doc. A family file is created by the PR that creates the
family; it is a shared interface and is serialised like any other (plan rule).

**Core numbers** that belong to the flow, not to an entry (the speed tie, accuracy, crit, damage roll, secondary and stall
draws, the sleep turns; the residual kinds of weather, burn, poison, ...), live in `data/entries/core/draw_sites.toml` and
`data/entries/core/residual_kinds.toml`. They change rarely.

**Validation** is a quick-tier test, `duoforge.data.entries`, run from the committed files without a checkout: the schema;
every `id` is a pool row of the format (a stub may name a legal row that is not in the pool yet); every referenced source,
doc and test path exists; every family has a family file and the params fit its schema; no two entries own the same number,
byte or bit; a `supported` entry names at least one evidence record (a reference battle, a campaign record of spec C2, or
the family cross-check), which is the evidence rule of 0015; a `refused` entry has a refusal text and no source. With
`DUOFORGE_PS_REFERENCE_DIR` the facts are checked against the pin, as `duoforge.data.closure_regen` does today.

## 3. Generated artifacts, registration, stable ids

**Generated from the entries** (all `--check`ed in CI, `linguist-generated`, "do not edit" header; regenerated after every
merge, never resolved by hand):

| Artifact | Replaces |
|---|---|
| `src/data/pool_tables.{h,c}`: the special, family and flag columns; new, a family column for moves | the generator's `SPECIAL_*` and `POOL_*` lists |
| `src/data/support_manifest.c` | the hand-edited marks (1,017 lines, touched by every step) |
| `src/combat/generated/hooks_{moves,abilities,items}.{h,c}`: hook masks, one switch per hook point, the prototypes | the `md->special ==` chains and the allow-list (plan item 5) |
| `src/combat/generated/draw_sites.h`, `residual_kinds.h`: ids and the name switch, which stays the compile-time duplicate guard | the hand lists in `rng/draw.h` and `residual_order.h` |
| `src/data/refusals.c`: `dfi_pool_<kind>_refusal[id]` strings | `dfi_pool_<kind>_unmodeled[]` |
| `python/duoforge/_tables.py`: names, ids, durations | the tracker's `FIELD_TURNS` copies (spec part A, interim step) |
| `docs/support/README.md` (the mechanics section), `docs/support/status.md` and `status.json` | the hand-written README (plan step 11) |

**Registration without a central file.**
- C sources: `file(GLOB CONFIGURE_DEPENDS src/combat/<area>/*.c)` per area, the pattern `tests/reference/data.cmake` uses
  already. Alternative: a generated `sources.cmake` per area; same effect, one more generated file. A deleted C file is
  loud: its functions are missing from the generated switches and the link fails (checked by HS).
- Tests: `tests/<area>/<entry>/tests.cmake` per entry, included by a glob in the area's `tests.cmake`, so no area file gains a
  line per entry. The restructure's per-area registration stays for the existing tests. A missing test folder fails
  `duoforge.data.entries`, because every entry names its test paths.
- Reference battles: one file per battle, a directory registry (plan step 2, merged). New battles are named by entry.
- Docs: one file per entry under `docs/mechanics/<area>/<entry>.md`; the index is generated.

**Stable ids.**
- *Pool row ids* (moves, abilities, items, formes) are table indices: append-only, part of the canonical bytes and of encoded
  states. They are **not** in the entry file. Each format has an append-only id ledger, `data/formats/<format>.ids.toml`
  (generated once, then frozen and `--check`ed). Because the owner's bulk step creates every entry of the format at once, the
  Reg M-C ledger is written once, and content PRs never append to it. A later format appends to its own ledger.
- *Handler keys*: a bespoke move is dispatched by its **move id**, not by a `special` id, so no handler number is allocated
  per mechanic any more (owner decision 5). The `special` column (`uint8_t`, 122 of 256 values used) keeps its width and
  serves the existing handlers and the kinds several moves share; new bespoke code keys on the row id. This removes the
  number space OU would overflow (316 more moves) without touching the canonical bytes.
- *Draw sites and residual kinds owned by a mechanic* are declared in the entry file and **derived, not allocated**:
  `DFI_SITE_ENTRY_BASE + (kind << 14) + (row_id << 3) + k` for the k-th site of the entry (the site and kind fields are
  `uint32_t` already; existing sites keep their frozen small numbers). The bounds are part of the contract: `row_id < 2048`
  and `k < 8`, so the three fields cannot overlap; the generated header guards them with `static_assert` against every
  format's row counts (511 moves today, about 830 with OU) and the generator refuses an entry with a ninth site. Two
  agents cannot collide, nothing is renumbered, and the fixture rule "never renumber" holds by construction. The generated name switch keeps the compile-time duplicate guard;
  `dfi_draw`'s bound check becomes a lookup in the generated table.
- *Storage* (tail bytes, volatile and position flag bits, view-extension feature bits) is the scarce resource of part D.
  Until D, an entry **declares** what it owns (`[state]`), the generator fails on two owners of one byte or bit, and the
  assignment itself stays a hand decision with HS, as today.

## 4. Dispatch in the hot path

**Hook points.** The flow keeps deciding when and in which order effects run (spec non-goal, plan rule). It calls named hook
points; the entry files say who answers. The kinds follow the extension spec's list and today's phases in `turn.c`:

- moves: `target_class`, `try` (the fail conditions before the targets), `try_hit` (per target), `base_power`,
  `modify_type`, `hit` (per target, after the damage), `after_hit`, `status_primary`, `field`, `move_end`, `request_disable`;
- abilities and items: `entry`, `try_hit`, `base_power`, `modify_stat` (atk, def, spa, spd, spe, accuracy),
  `modify_damage`, `damaging_hit`, `try_boost`, `set_status`, `residual` (with order and sub-order), `switch_out`, `faint`,
  `before_move`, `modify_priority`, `weather`, `update`, `eat`, `take_item`.

**Decision: hook masks plus generated switches, no function pointers.**
- Per entry a `uint64_t` hook mask (one bit per hook point) in a `const` table. At a hook point the flow first tests the
  masks of the participants (the move, the user's and the targets' abilities and items). The common case, nobody answers,
  is one AND per participant, cheaper than today's compare chains.
- When a bit is set, the flow calls the generated function of that hook point: `switch (move_id)` or `switch (ability_id)`
  over the bespoke entries, a direct call per case. Family rows are handled by the family's one function, keyed by the
  family column, before or after the bespoke switch as the hook point's Showdown priority list says.
- Why not function pointers: an indirect call per participant and hook point defeats inlining even with IPO, needs a
  devirtualisation the compiler cannot do on a table indexed by a run-time id, and its target changes with every action in
  random play. A switch compiles to a jump table (one well-formed indirect jump) or a compare tree; the handler bodies stay
  inlinable under IPO, and without IPO each case is a direct call. Both forms can be generated, so if the bench prefers a
  table for one hook point the generator emits it there; the measurement decides, not the design.

**Order and determinism.**
- Several responders at one hook point are called in Showdown's order: the handler priority from the entry file (static,
  sorted by the generator), then the flow's speed order with the existing tie draws, then the sub-order (condition 2,
  ability 7, item 8). Where today's code refuses an order it cannot compute (`dfi_mods_commute` for ModifyDamage, the
  ambiguous residual lists of `residual_order.h`), the refusal stays. The order is proven per hook point, not claimed: the
  migration PR of a hook point compares the per-battle digests of every reference set before and after (the P2 command of
  plan step 2), and a hook point whose digests differ is not merged.
- **RNG.** A hook never draws on its own: it calls `dfi_draw` with a site declared in its entry file. The draw order is the
  flow's call order, and the migration proves it unchanged by the per-battle digests (the RNG use is part of the digest). A
  test per entry checks, over its reference battles, that every drawn site is declared and every declared site is drawn: the
  draw contract of an entry is explicit.
- **No heap.** Every table is `const`; responder lists are fixed-size arrays sized by the generator from the entries (as
  `DFI_MODIFY_DAMAGE_MAX` is sized today); masks are integers.

**Measurement plan** (per migration PR, under `machine_lock.sh --exclusive`, results in the PR body):

| Item | Setting |
|---|---|
| Workloads | `closure-pairings-v1` (the bench baseline: STEP_CORE 6,888 battles/s, GCC 14.2 Release with IPO, Xeon 8573C, `docs/benchmarks/2026-10-11-restructure-baseline/`) and a new `pool-random-v1` (seeded random registry teams, so the content paths run) |
| Builds | GCC Release with IPO on and off, MSVC Release, clang Release (the CI matrix) |
| Procedure | one warmup, five repetitions, paired before and after on the same two commits with the same flags; median and min of battles/s and of CPU ns |
| Gate | the after/before ratio of the medians lies within the baseline's own repetition spread and is not below 0.98; P2, P3 and P4 unchanged |
| On failure | the hook point keeps its direct code (the spec's risk rule); the number goes into the PR body |
| Secondary | compile time and binary size with IPO (the plan's split-risk item) |

## 5. Stubs and the support status

- A stub is an entry file with `status = "refused"` and a refusal text. The generator leaves its manifest mark at 0 and
  emits no handler. Setup and the move body refuse it with `E_UNSUPPORTED` exactly as today (the `dfi_support` checks in
  `src/combat/turn.c`, including `dfi_run_move_body`). Nothing is silent: a `supported` entry without evidence fails `duoforge.data.entries`.
- **By name.** The refusal text is data: `dfi_pool_<kind>_refusal[id]` (generated, replaces `*_unmodeled`), read by the test
  support, by the scenario runner's `expect refused <entry>` (spec C1) and by the status report. Which ids are refused is
  public already through `duoforge_data_supported`; Python names the refused entry through that query (data, no rule).
  The text stays out of the public API (owner decision 4: no header change, P6 empty) until the live path needs it.
- **Status report.** `tools/content/status.py` generates `docs/support/status.md`: per area and family the supported and
  refused counts, every stub with its refusal cause and, when the private coverage data is given as an argument, the replay
  games each stub blocks (the shape of `registry_blockers.json`). It is the "what is missing at a glance" list.
- **Promotion** of a stub is the normal content step: flip the status, add the model (a family row or a C file), the
  scenarios, the recorded battles, the doc. The validation test enforces the order: no status flip without evidence.

## 6. Where everything of one entry lives

| Part | Place | Shared with other entries? |
|---|---|---|
| definition | `data/entries/<kind>/<id>.toml` | no |
| code | `src/combat/<area>/<id>.c` (bespoke) or `src/combat/<area>/families/<family>.c` (family) | the family file: yes, serialised |
| tests | `tests/<area>/<id>/` with its own `tests.cmake` | no |
| scenarios (spec C1) | `tests/scenarios/<area>/<id>/` | no |
| reference battles | `tests/reference/battles/<format>/<set>/<id>_*.json` plus the per-battle pin | no |
| independent pin | `tests/reference/pins/<format>/<id>.json`, hand-maintained: the names, the count and the counted values (certified, stops, outcomes) of the entry's reference battles | no |
| doc | `docs/mechanics/<area>/<id>.md` | no |
| generated output | pool tables, manifest, hooks, refusals, support docs | regenerated, never hand-merged |

**Pins per entry (owner decision 2).** No generator writes a pin. The format sums (battle count, certified, tiebreak
stops, live outcomes and stops, own-PP pairs) are derived from the per-entry pins and checked against the battle files, so
a missing or renamed battle file breaks the pin of its entry, and a content PR creates only the pin of its own entry.
Battles that belong to no entry (today's closure, Team C and pool sets) keep one collective pin per set, which content PRs
never change. The transition from `tests/reference/pins/reg-mc.json` is its own migration step (CF4 in section 7).

A family-row promotion touches four kinds and at most eight files (the entry, the scenarios, the battles with their pin,
the doc); a bespoke one adds the C file and the test folder. That meets the spec's success measure. Shared interfaces (a new hook point
in the flow, a new family, new storage) are their own small PRs, serialised, as the plan rules.

## 7. Embedding in the restructure plan and the extension spec

Astra builds the restructure; nothing here is built twice:

| Plan item | This addendum |
|---|---|
| step 3 (items pilot, now) | unchanged. Request: name the files by family (`type_booster.c`, `resist_berry.c`) and keep the rule functions free of any dispatch; they become the family files of section 1 as they are |
| step 4 (areas; the generated per-special table) | the table is generated from the generator's lists as planned; CF1 below re-points its source to the entry files with byte-identical output |
| step 5 (definition files, number spaces, generator split) | **is** CF0 and CF2: the entry files are the definition files; the split is one reader and one writer per kind |
| step 10 (format definition) | the format file lists its entries by Showdown id and gets the id ledger (sections 3 and 8) |
| step 11 (docs per mechanic, the generated support README) | file names are entry ids; the README and the status page are generated from the entries; the 0015 anchors are the `decision` field |
| step 12 (scaffold) | `tools/content/promote.py <id>` instead of `new_mechanic.py`: the entry exists already; the tool writes the C file from the family or bespoke template, the test folder and the scenario folder. A `new` mode stays for an entry of a new format |
| spec B (hook table, families as rows) | section 4 is the hook table; the B pilot (the damage-modifier family) is CF6 and uses the family files from the start |
| spec C1 (scenario language) | scenario folders per entry, referenced from the entry file |
| spec A interim (durations into Python) | generated from the core and entry files (`_tables.py`) |
| spec D (declared storage) | the `[state]` declaration is the forerunner; D turns it into the generated codec and swap rules, unchanged otherwise |

**Migration in PR-sized steps**, each behaviour-neutral, each with the plan's P1-P6 in the PR body:

| # | PR | Proof beyond P1-P6 |
|--:|---|---|
| CF0 | extract the entry files from today's sources with a one-off tool (the status from the manifest, the handler and the facts from the generator's dictionaries, the pin lines from the table comments, the 0015 anchors from the step comments); the reader and `duoforge.data.entries` | the generator, reading the entries, writes `pool_tables` and `support_manifest.c` byte-identical; every old facts check passes through the generic check |
| CF1 | the allow table and the refusal strings from the entries; delete the hand lists | old predicate and table agree for every special (the plan's test); `*_unmodeled` equals the refusal strings |
| CF2 | draw sites and residual kinds declared per entry; the generated headers; the core file | every existing site and kind keeps its number (the static-assert table of plan step 5); fixtures unchanged |
| CF3 | the generated support README section and status page; the 0015 redirect table (plan step 11) | README content equal (diff in the PR body); every 0015 id resolves to one file |
| CF4 | the pin per entry: `tests/reference/pins/<format>/<id>.json` for every entry with recorded battles, one collective pin per legacy set, the sums derived and checked against the battle files; `reg-mc.json` retired | the derived sums equal the frozen values of `reg-mc.json` (battles 90/73/966, certified 26/23/966, tiebreak stops 833/734/5,324, the live outcomes and stops, the own-PP pairs); the mutation controls of plan step 2 still fail on a deleted or renamed battle file and on a changed count |
| CF5 | hook masks and the first generated switch (`move.try`, the fail conditions), then one hook point per PR | the bench table of section 4 per PR; digests identical |
| CF6 | the first family through a family file and the move family column (the B pilot) | the spec's B proof: identical results for the migrated members, one new member as a row only, the cost against the retro median |
| CF7 | per-entry test folders and `promote.py` (plan step 12) | a promoted dummy builds and its empty test runs, then is removed |
| CF8 | the id ledger and the status per mod (section 8) | P5 byte-identical for Reg M-C |

CF0 takes the slot of plan step 5 (after steps 3 and 4, whose moved files it reads; owner decision 6, step 4 is not
delayed), so the plan's sequence holds. CF1-CF3 are the plan's own steps 4, 5 and 11, executed through the entries. CF4
is the pin transition of owner decision 2. CF5 and CF6 are the extension spec's part B and come after C1 and A, in the
owner's order.

## 8. The format axis (#413)

- An entry file is keyed by the Showdown id, so every format that contains the entry shares it. The format file
  (`data/formats/<format>.toml`, plan step 10) lists its entries; the generator (`--format`) writes that format's tables and
  its id ledger. Reg M-C stays byte-identical (P5).
- Facts and status are **per mod**: `[pin].champions` and `[pin].gen9`; `status` is one value when the mods agree and a
  table (`status.champions`, `status.gen9`) when the Champions mod overrides the entry (Fake Out's disable, the sleep
  variants). The generator knows which entries the mod overrides and refuses a single status there.
- A rule that differs by format is switched by a named flag of the format definition inside the family or bespoke code
  (plan rule), never by a second entry file. Hook points, draw sites and residual kinds are format-neutral; the position
  count and the team size come from the named constants.
- Evidence carries the format: `tests/reference/battles/<format>/`, scenario files name their format, campaigns record it.
- Storage per format (EVs/IVs, Terastallization) is part D's job, as decided.

## 9. Risks

- **The bulk creation PR** (about 900 generated files): reviewed by its generator and by spot checks, with the round-trip
  proof of CF0; never hand-written.
- **Hot path**: masks and switches are expected neutral or better; every hook point is measured and keeps its direct code
  if not.
- **Compile time and IPO** with many small translation units: measured in the plan's steps 3 and 4 already; the generated
  switch files are the only new large units.
- **Two agents, one family**: the family file is a shared interface; the second PR waits, or the family is created in a
  separate small PR first.
- **Pins per entry**: the format sums become derived, so the independence rests on the hand-maintained per-entry files and
  on the check against the battle files; the legacy sets' collective pins and the mutation controls of plan step 2 keep
  the guard until every battle belongs to an entry.
- **The classification's age**: `classification.json` is from an older head; CF0 derives the classes from the current
  generator and manifest, not from it.
- **Stale references** in about 26 docs to `turn.c` lines (plan risk) are not made worse: the entry file is the stable anchor.

## 10. Owner decisions (2026-10-12, via HS, on #452)

1. **TOML** is the format of the entry files.
2. **One pin per entry**, `tests/reference/pins/<format>/<entry>.json`, hand-maintained, with the names, the count and the
   counted values of the entry's reference battles. The format sums are derived from the pins and checked. Today's closure,
   Team C and pool sets get one collective pin per set. The transition from `reg-mc.json` is its own step (CF4).
3. **Formes**: only a forme with behaviour of its own gets a file.
4. **The refusal text** lives in the test support, the docs and the status page only; no header change. A public API comes
   when the live path needs it.
5. **Dispatch by move id** for new bespoke moves; the `special` column stays at 8 bits, the canonical bytes do not change.
6. **CF0** takes the slot of restructure step 5; step 4 is not delayed.

HS's two review additions are in: the bounds and `static_assert` of the derived draw-site numbers (section 3) and the
digest proof of the responder order per hook point (section 4).
