# 0009 — Team C: the expansion track (data kind, gate, steps, evidence)

Status: **accepted** (owner, 2026-10-01: "bau das erstmal so"; setup rule: the closure rule, section 3.4). **Steps 1 to 12 built; the Team C track is complete** (section 10). Builds on decision `0004` (two reference teams), `0006` (data, state v3, draw sites, fixtures, evidence), `0007` (player view) and `0010` (the certified CLOSURE profile, the role of `CLOSURE_DEV`, draw alignment B confirmed), and on the research in `docs/research/third-team/` (PR #32). "M§n" means section n of `docs/research/third-team/mechanics.md`; X1 to X9 are its executed experiments.

## 1. Owner inputs (2026-10-01)

- Team C is **not part of the closure**. Decision 0004 keeps two teams; Team C is a separate expansion track. The closure's behaviour, its tests and traces, and its context fingerprint stay unchanged.
- The mechanics are built **as they are**; no cheaper item variants (M§9 stays a record).
- Male for every 50/50 species; every set states its gender.
- The sets are `docs/research/third-team/team-c.txt`, level 50, 66 Stat Points each: Sneasler (M) @ White Herb, Incineroar (M) @ Sitrus Berry, Salamence (M) @ Salamencite, Indeedee-F (F) @ Rocky Helmet, Kingambit (M) @ Chople Berry, Basculegion (M) @ Choice Scarf with Flip Turn instead of Protect.
- The order is M§7 with these two set changes. The support gate applies per step: Team C is rejected at setup until every mechanic it uses exists, and the rejection is explicit.

## 2. What stays unchanged, and how each PR shows it

| Closure artefact | Stays | Checked by |
|---|---|---|
| CLOSURE and CLOSURE_DEV fingerprints | byte-identical: data kind, counts 16 and 37, closure table hash; the certified context (6, 4) keeps `09d8d247…` (decision 0010) | the fingerprints pinned in `tests/test_closure_setup.c` (from `tools/state_model/state_v3_model.py`) |
| `src/data/closure_tables.{h,c}` | byte-identical; `gen_closure.py <pin> --check` passes | the sha256 pins in `tests/CMakeLists.txt`, the regeneration test under `DUOFORGE_PS_REFERENCE_DIR` |
| The closure specs and traces (87 since M5 step 3), `tests/reference/conformance.h` | byte-identical | `duoforge.reference.trace.*` (Showdown reruns), `duoforge.reference.conformance_tables` |
| State v3 | layout (1009 bytes), schema 3, semantics id; every value that is new for Team C stays invalid under the CLOSURE kinds | the codec, golden and invariant tests, plus new negative tests |
| Observation (736 bytes) and events | closure battles give the same bytes; additions are new enum values and bits of `reserved` fields that stay zero under CLOSURE | the conformance event and observation checks |
| Closure test files | not edited, except the shared conformance driver (section 6.1), whose closure build keeps its fixtures and checks, and two checks of `tests/test_closure_setup.c`: the unknown data kind is now 6 (4 and 5 are TEAM_C), and the manifest comparison covers the closure ids (the Team C ids: `duoforge.state.team_c_setup`) | review |

Every step's PR states this table as checked.

## 3. Data

### 3.1 Two new data kinds

| Kind | Value | Tables | Sets |
|---|---|---|---|
| `DUOFORGE_DATA_KIND_TEAM_C` | 4 | the extended tables (3.2) | format-legal, in CLOSURE's profile (3.4) |
| `DUOFORGE_DATA_KIND_TEAM_C_DEV` | 5 | the extended tables | as CLOSURE_DEV: also No Ability and the rosters CLOSURE_DEV allows |

The DEV kind exists for the reason of decision 0006 section 2.1: every Team C forme has exactly one ability, and Unburden (step 8) and Psychic Surge (step 10) come late, so without No Ability no Sneasler or Indeedee-F fixture could pass the gate before step 8 or 10. The owner kept `CLOSURE_DEV` as the development profile (decision 0010, accepted 2026-10-01), so TEAM_C_DEV follows it: No Ability and four to six registered members. The config contract is CLOSURE's (no counts, no table). A TEAM_C fingerprint differs from every CLOSURE one in the data kind, the counts and the table hash, so states and traces of the two kinds never mix. The names are a proposal.

### 3.2 One extended table set; the closure is its prefix

- `tools/datagen/gen_closure.py` gains a mode `--team-c` that writes `src/data/extended_tables.{h,c}`. It builds the closure exactly as today (`SETS` and `MOVES` untouched) and then appends Team C: formes 16 to 22 (Sneasler, Incineroar, Salamence, Salamence-Mega, Indeedee-F, Kingambit, Basculegion), moves 37 to 49 (the 13 new ones in team order; Struggle stays 36), items 11 to 15 and abilities 16 to 20 (the five new ones of each). The closure mode's output does not change.
- **The engine reads only the extended tables**, under every combat kind. Under the CLOSURE kinds the closure counts (16 formes, 37 moves, 11 items, 16 abilities) bound every id at setup and in the invariants, so a CLOSURE battle only ever reads the prefix.
- **The prefix is the closure.** For every closure id, every field of the extended row equals the closure row. The only extension inside the prefix is the poison immunity bit of the Poison and Steel types (3.3). The generator asserts this before it writes. A new test, `duoforge.data.extended_tables`, checks it field by field. It also recomputes the closure canonical bytes from the prefix, using the closure immunity bits only, and requires that they hash to `dfi_closure_table_hash`. So the CLOSURE fingerprint provably still names the data a CLOSURE battle reads.
- `closure_tables.{h,c}` stay as generated. They hold the row types and the closure constants (the extended header includes them and adds only the new constants), the CLOSURE hash, and what `test_closure_tables.c` checks.
- The extended canonical bytes use the generator's `canonical()` layout over the extended data. Their SHA-256 is the TEAM_C table hash, pinned like the closure's: a file sha256 in CTest and regeneration under `DUOFORGE_PS_REFERENCE_DIR`.
- **All Team C data is generated in step 1.** Every new callback is mapped to a named handler id (3.3), and every new mechanic stays unmarked in the manifest. The TEAM_C fingerprint is then fixed for the whole track, so a Team C trace recorded in step 2 still runs in step 11. A later step that finds a missing table fact changes the tables and the TEAM_C fingerprint, and says so.
- Moving the engine from `dfi_closure_*` to the extended arrays changes about two dozen reads in `src/combat/turn.c`, `src/state/{closure_member,context,battle,invariants}.c` and `src/data/support_manifest.{h,c}`. This is a behaviour-neutral change in shared files, made once in step 1. Step 1 also audits two assumptions: every read of the immunity table tests a named bit, and no code treats Struggle (36) as the last move id.

### 3.3 Encoding: no new row field

| Fact | Encoding | Consumer |
|---|---|---|
| `defrost` (Flare Blitz) | the free flag bit 128, `DFI_MOVE_FLAG_DEFROST` | step 2 |
| `ignoreDefensive`, `ignoreEvasion` (Darkest Lariat only) | special `DARKEST_LARIAT` | step 2 |
| `basePowerCallback` (Last Respects) | special `LAST_RESPECTS` | step 4 |
| `selfSwitch` of a damaging move (Flip Turn) | the existing `SELF_SWITCH` bit, read for the first time (today only the Parting Shot special pivots, M§1) | step 4 |
| Dire Claw's secondary: 30 percent (Champions override), `onHit` picks psn, par or slp | `sec_chance` 30 and a new secondary kind, the three-way status pick | step 6 |
| type-chart key `psn` (Poison, Steel) | new immunity bit 16, `DFI_IMMUNE_PSN`; `tox` stays ignored (no toxic source in the data) | step 6 |
| poison | status value 5, `DFI_STATUS_PSN` | step 6 |
| `onTry` (Sucker Punch), `onTryHit` and condition (Helping Hand), `onTry` and condition (Follow Me) | specials `SUCKER_PUNCH`, `HELPING_HAND`, `FOLLOW_ME` | steps 9b, 11 |
| Psychic Terrain | terrain value 2 | step 10 |

The table maps the seven rejections of M§1 deliberately and gives the type key and the two state values that the closure ignores or lacks today. The generator still fails on anything else it does not know. Items and abilities stay ids whose behaviour is C (decision 0006: metadata is not mechanics). Follow Me's `onTry` checks `activePerHalf > 1`, a format property, so it never fails in doubles.

### 3.4 Setup rules under TEAM_C

The CLOSURE rules apply over the extended tables, in the profile CLOSURE has when step 1 is built. Decision 0010's freeze (register exactly 6, bring 4; M5 step 2) applies to TEAM_C as well, and the four-to-six rosters stay with TEAM_C_DEV. The member rules of decision 0006 section 2.1 are: a base forme; 1 to 4 distinct moves of its set; a legal gender; nature and Stat Points; the forme's ability (or No Ability under TEAM_C_DEV); any table item or none; Species Clause and Item Clause per side. As in the closure, a side may mix closure and Team C members and anyone may hold any item. So placements outside the three teams become legal once their mechanics are marked: Choice Scarf on Archaludon with Electro Shot, White Herb on Mega Staraptor with Contrary, Rocky Helmet anywhere. Each step tests the placements its mechanic makes reachable (section 5). **Owner choice:** restrict TEAM_C members to their set item instead. That gives a smaller surface but a second rule. The recommendation is the closure rule.

Under the CLOSURE kinds nothing changes: a Team C species, move, item or ability is out of range (`E_INVALID_ARGUMENT`).

### 3.5 The support gate

The manifest grows to the extended ids; its closure entries stay as they are (all set). Each step sets only its own flags, after its tests. A rule-level mechanic without an id of its own is attached to its only source in the data: poison to Dire Claw, Psychic Terrain to Psychic Surge, the choice lock to Choice Scarf, ally targeting to Helping Hand and redirection to Follow Me. A setup that needs an unmarked mechanic fails with `E_UNSUPPORTED` after all validation, and a step checks the same for the battle it runs, as today.

| Member | Full set supported after step |
|---|---|
| Incineroar | 2 |
| Salamence | 3 |
| Basculegion | 7 |
| Sneasler | 8 |
| Kingambit | 9b |
| Indeedee-F | 11 |

The whole team passes after step 11. Until then, fixtures use TEAM_C_DEV and partial sets.

## 4. State, player view and draws: no layout change

### 4.1 State v3 holds Team C

| Mechanic | Where | Notes |
|---|---|---|
| Poison | member status 5, no counter | residual order 9, base max HP / 8 |
| Psychic Terrain | terrain 2 and its turns | 5 turns (no Terrain Extender in the data) |
| Follow Me, Helping Hand | position volatile flags, bits 8 and 16 | single-turn, like Protect |
| Unburden | bit 32 | set on item loss, cleared on leaving |
| Choice lock | bit 64; the move in the position's locked-move byte | see below |
| Newly switched (Helping Hand's `newlySwitched`) | bit 128 | set on entry, cleared at the turn start (`sim/battle.ts:1673`) |
| White Herb or Chople Berry used | the member's consumed flag | existing |
| Last Respects' fainted count | **derived, not stored** | see below |

The volatile flags byte uses 1, 2 and 4 today (Flinch, Protect, Flash Fire), so the five new bits fit. The locked-move byte is shared with the Electro Shot charge:

- Both locks can be set at once only on the same move: a choice lock disables every other move, and a charge starts only on Electro Shot.
- The locked target belongs to the charge only.
- The choice lock outlives the charge.

The invariant states exactly these three rules.

The fainted count is the number of members of the user's side at 0 HP. It equals `side.totalFainted` (`sim/battle.ts:2554`) for three reasons:

- The data has no revival.
- Every faint is processed before the next action starts.
- Nothing can make an ally faint inside Basculegion's own move before its base power is computed: Last Respects has a single target, and Rocky Helmet hurts the attacker after the hit.

Step 4 pins this with an ally that fainted earlier in the same turn (X6).

The invariants become kind-aware. The new values are valid only under the TEAM_C kinds; under CLOSURE the ranges stay what they are (volatile flags up to `DFI_VOL_FLAGS_MAX` 7, terrain 0 to 1, status 0 to 4). `tools/state_model/state_v3_model.py` learns the same ranges. There is no schema bump and no semantics change: the CLOSURE fingerprint and every closure state's bytes stay.

### 4.2 Player view (decision 0007)

- **New public values, appended:** `DUOFORGE_AILMENT_POISON` (5), `DUOFORGE_TERRAIN_PSYCHIC` (2), and a `DUOFORGE_FIELD_*` value for Psychic Terrain in FIELD_START and FIELD_END. These lines need no new event kind: `-status psn`, the residual `-damage`, `-fieldstart` with `[from] ability: Psychic Surge`, `-fail` (Sucker Punch, Helping Hand), and the Rocky Helmet `-damage` with `[from] item`.
- **New event kinds after 37**, for lines the closure never shows:
  - `-singleturn` of Follow Me and of Helping Hand (`[of]` the user);
  - `-activate|…|move: Psychic Terrain` for a blocked move, whose cause is neither an ability nor a move id;
  - the second `-enditem` of a resist berry, `[weaken]`, after the `[eat]` line.

  The event flags byte is full (eight bits in use), so a new distinction is a kind or a `detail` value, never a reused bit. White Herb's `-clearnegativeboost` is `[silent]`, and its `-enditem` is the existing ITEM_END. Unburden and the choice lock print nothing.
- **Observation.** Items are open (team sheet) and a used move is public, so a choice lock is public: `locked_slot` shows it, with `charging` 0. Follow Me and Helping Hand are public and can still be live at a PIVOT (Flip Turn or Parting Shot after Follow Me in the same turn), like `protecting`. Unburden is public by inference: the ability is open and the item use is shown. Proposal: three bits of the position view's `reserved` byte. They stay zero under CLOSURE, so the struct keeps 736 bytes and every closure observation its bytes.
- These are additive changes to the public header. Each step that adds one names it in its PR, bumps the library's minor version (coordinated with the main session at rebase) and needs the owner's approval (section 9).

### 4.3 Draws

There is one new site, `DFI_SITE_STATUS_PICK` (13), for Dire Claw's `sample(['psn', 'par', 'slp'])` = random(3). It is drawn after every successful secondary roll, even when the target cannot take the status (X9); for sleep, the existing SLEEP_TURNS follows. The harness records it as `SECONDARY[0,3)` in context `Hit`, and the converter maps it by that context. Draw alignment B (decision 0006 section 5.1, confirmed by the owner in decision 0010) decides whether the engine draws the pick when no status can apply; step 6 names and checks that rule. No other Team C mechanic adds a draw (M§5). Dynamic speed (Unburden, Choice Scarf) only changes the existing SPEED_TIE groups. `DFI_SITE_COUNT` becomes 14; no closure tape contains the new site.

## 5. Steps

There is one PR per step, in M§7's order with the owner's set changes. "Shared" lists the shared core files a step is expected to touch.

| Step | Content | New state or public values | Shared |
|---|---|---|---|
| 1 | Data kinds; extended tables (all of Team C) and the prefix test; kind-aware setup and invariants; manifest over the extended ids. Mechanics: Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet; Defiant (Competitive's shape, +2 Atk, foes only); Adaptability (STAB 2); the seven formes | two data kinds | turn.c, context.c, battle.c, closure_member.c, invariants.c, support_manifest, duoforge.h |
| 2 | Flare Blitz (`defrost`, recoil 33/100, 10 % burn), Darkest Lariat | - | turn.c |
| 3 | Salamencite, Salamence-Mega, Aerilate: type change before STAB and immunity; BasePower priority 23 first | - | turn.c |
| 4 | Last Respects (derived count); Flip Turn (a damaging pivot on the existing PIVOT boundary) | - | turn.c |
| 5 | Chople Berry (eaten inside ModifyDamage, after burn and before the 16-bit truncation); Rocky Helmet (`DamagingHit` with contact) | event kind (`[weaken]`) | turn.c |
| 6 | Dire Claw; poison (status 5, residual 9, Poison and Steel immune); the new draw site | AILMENT_POISON, site 13 | turn.c, draw.h |
| 7 | Choice Scarf: lock in the request and the domain; Struggle when the locked move has no PP; x1.5 in the speed chain | volatile bit; `locked_slot` | request.c, turn.c |
| 8 | White Herb (switch-in, AnySwitchIn, AnyAfterMega, AnyAfterMove, residual 29); Unburden (dynamic speed) | volatile bit, view bit | turn.c |
| 9a | Harness: ally targets in `ps_trace.js` (6.2) | - | tools only |
| 9b | Sucker Punch and Helping Hand: queue reads, `newlySwitched`, ally targets, BasePower priority 10 | volatile bits, view bit, event kind | turn.c, request.c |
| 10 | Psychic Surge and Psychic Terrain: field TryHit before Protect, terrain replacement, Psychic x5325/4096 | TERRAIN_PSYCHIC, field value, event kind | turn.c |
| 11 | Follow Me: redirects foe single-target moves, ahead of Lightning Rod | volatile bit, view bit, event kind | turn.c |
| 12 | **Team C gate (proposal):** the real Team C passes in the profile of decision 0010. As closure step 13: random real-team battles C-A, C-B, A-C, B-C and C-C with replay, codec continuation and information equivalence, plus real-team reference battles | - | tests |

**Interaction tests.** Each item of M§6 is tested in the step that makes it reachable. Recorded battles are used unless a test is marked as a unit test.

| Step | Interactions |
|---|---|
| 1 | Defiant against Intimidate (Incineroar, Salamence, Staraptor), Parting Shot and Snarl; no Defiant or Competitive after the user's own Draco Meteor or Close Combat drops; Grass Knot against the new weights (60, 80, 100); Hyper Voice's 0.75 spread modifier with a protecting target; rain on Wave Crash and Aqua Jet; Wave Crash recoil against Life Orb on the other side |
| 2 | Flare Blitz thaws a frozen user (Ice Beam freeze), recoil faint and the win rule, into Flash Fire, in rain and sun; Darkest Lariat through Coil and Stamina Defense boosts, Reflect still applies |
| 3 | Hyper Voice hits Ghost types only after the Mega (X8); Intimidate does not run again; Mega and Tailwind speed order; one Mega per side |
| 4 | Last Respects after an ally faint in the same turn (X6), with Adaptability; Flip Turn with a KO, into Protect, with an empty bench, and together with Emergency Exit (two switch flags in one action) |
| 5 | Chople Berry against Close Combat (Mega Staraptor, Sneasler) and Focus Blast, also without a KO; Rocky Helmet against Fake Out, Close Combat and Flip Turn (no pivot when the user faints); the order against recoil, drain, Life Orb and Emergency Exit; Sitrus Berry after Helmet damage |
| 6 | Dire Claw against Steel types (Gholdengo, Archaludon, Mega Golisopod: no poison), Raichu (no paralysis), Good as Gold (no block of a secondary) and an already statused target (the pick is still drawn, X9); poison's residual order against Leftovers, Grassy Terrain and burn |
| 7 | The request disables the other moves (X6); locked into Fake Out on the next turn (Struggle); Choice Scarf on Archaludon (charge and lock on Electro Shot); a Protect lock and its stall chance; Flip Turn ends the lock; x1.5 with Tailwind and paralysis in one rounding |
| 8 | An opening Intimidate consumes the herb inside the switch-in sequence, so Unburden is active on turn 1 (X1); herb after Close Combat (X2) and Draco Meteor; Parting Shot, Snarl; herb on Competitive Milotic and Contrary Mega Staraptor; Unburden after a berry; the mid-turn re-sort; Unburden ends on switch-out |
| 9b | Sucker Punch against Protect, Trick Room, Nasty Plot, Coil, Swords Dance, Reflect, a switch and a target that already moved; Armor Tail; Helping Hand, then Sucker Punch (X4); Helping Hand on a partner that switched in this turn (X4) and on one that already moved (fails); Helping Hand with a spread move |
| 10 | Psychic Terrain blocks Fake Out (Rillaboom, Raichu, Incineroar, Sneasler), Shadow Sneak, Aqua Jet and Sucker Punch into grounded targets, but not Helping Hand or a Fake Out into an ally (X5); Flying targets stay hittable; Grassy Surge against Psychic Surge (the later setter wins, Trick Room reverses the order); Grassy Seed; Psychic x1.3 for grounded users. Correction to M§6: Grassy Glide is never blocked, because its +1 needs Grassy Terrain (`data/moves.ts:7664-7665`), which Psychic Terrain replaces; a battle shows it at priority 0 |
| 11 | Follow Me beats Lightning Rod (X3); spread moves ignore it; the fainted-target retarget runs before it; an ally-targeted move is not redirected; Sucker Punch redirected to an Indeedee-F whose Follow Me already ran; Fake Out into Rocky Helmet through the redirect; Electro Shot's stored target; a fainted Follow Me user |

## 6. Evidence and tooling

### 6.1 Reference battles

- **Specs.** A spec goes in `tests/reference/specs/c<step>_<topic>.json` with a new field `"data": "team_c"`; closure specs stay without it.
- **Recording.** Record from the committed path, `node tools/reference/ps_trace.js C:/Dev/src/pokemon-showdown tests/reference/specs/<name>.json`. The trace stores the spec file name, so never record from a scratch copy. When a case must occur, find the seed with a predicate.
- **Conversion.** `python tools/reference/trace_to_c.py <repo>` writes the closure traces to `tests/reference/conformance.h` exactly as today. It writes the Team C traces, read with the extended tables, to `tests/reference/conformance_team_c.h`.
- **Replay.** A second CTest, `duoforge.reference.conformance_team_c`, compiles the shared conformance driver against that header. It uses TEAM_C contexts, or TEAM_C_DEV exactly where the closure driver falls back to CLOSURE_DEV (No Ability, or a roster outside the certified profile). It compares draw for draw, request candidates, events and knowledge, as for the closure. The closure build of the driver keeps its fixtures and checks.
- **No closure trace changes.** Harness and converter changes are additive and silent for the closure:
  - every `duoforge.reference.trace.*` check passes with the unchanged closure traces;
  - new snapshot fields appear only where a Team C mechanic is present;
  - `HARNESS_VERSION` stays 14. A bump would rewrite all 71 closure traces and needs the owner.

### 6.2 Known tooling gaps (M§8)

- **`gen_closure.py` (step 1):** the seven explicit rejections become the mappings of 3.3. Anything else still fails, and the closure mode stays byte-identical (`--check`).
- **`ps_trace.js` (step 9a):** today 17 of 36 ad-hoc Team C battles abort with `Invalid target for Helping Hand`, because the plan fix-up (`planMove`) aims every targeted move at foe 1. The fix aims an `adjacentAlly` move at the ally's slot (`-1` or `-2`); a spec may also name the ally target. Only plans with such a move change, and the closure has none. Built in step 9a (section 10.9).
- **`src/rng/draw.h` (step 6):** the STATUS_PICK site (4.3).
- **`trace_to_c.py`:** the second output, the extended tables, the STATUS_PICK mapping and each step's new protocol lines. It keeps failing loudly on anything unmapped.

### 6.3 What each step delivers

- **Positive tests:**
  - unit tests with reference-derived expectations;
  - the step's interaction tests (section 5);
  - recorded battles for each new mechanic.
- **Negative cases:**
  - the gate: before its step, a setup with the mechanic is `E_UNSUPPORTED`; after it, the setup is accepted;
  - the CLOSURE kinds: a Team C id at setup is `E_INVALID_ARGUMENT`, and a Team C value in a decoded state is `E_INVARIANT`;
  - the mechanic's own failure paths;
  - malformed-input atomicity;
  - negative controls for the converter: a deliberately wrong Team C trace must fail.
- **The full matrix, green:**
  - MSVC, GCC 16.2 and Clang 23, Debug and Release, with `-DDUOFORGE_WARNINGS_AS_ERRORS=ON` and `-DDUOFORGE_PS_REFERENCE_DIR=C:/Dev/src/pokemon-showdown`;
  - hosted CI with GCC ASan and UBSan;
  - the source lint;
  - the regeneration checks (`gen_closure.py --check`, `gen_closure.py --team-c --check`, `trace_to_c.py --check`);
  - the table in section 2.
- **No benchmarks.** Measurements belong to the main session.

## 7. Coordination with the main session

- **Own files:** `src/data/extended_tables.{h,c}`, the `--team-c` part of `gen_closure.py`, `tests/reference/specs/c*`, `tests/reference/traces/c*`, `tests/reference/conformance_team_c.h`, new `tests/test_team_c_*.c` and this note.
- **Shared files**, touched minimally and listed in each PR:
  - `src/combat/turn.c`, `src/state/request.c`, `src/state/{context,battle,closure_member,invariants}.c`;
  - `include/duoforge/duoforge.h` (new constants only);
  - `src/data/support_manifest.{h,c}`, `src/rng/draw.h`;
  - `tools/reference/{ps_trace.js,trace_to_c.py}`, `tests/test_conformance.c`, `tools/state_model/state_v3_model.py`.
- **Process:** rebase on `main` before each PR. The public API contract and the closure fingerprint change only with the owner.

## 8. Alternatives considered

- **Append Team C rows to `closure_tables.{h,c}`.** The closure files, counts, file pins, tests and fingerprint would all change. Rejected (owner input).
- **A table pointer per context**, so the closure keeps reading its own arrays. It gives the same guarantee as the prefix test, but every table read and about a dozen signatures change, and every read pays an indirection. Rejected.
- **A delta table with a range accessor.** It costs a branch on every read, and the poison immunity is a change inside a closure row, not an appended row. Rejected.
- **State v4 for the new fields.** Not needed (4.1), and it would change every closure state's bytes.
- **Generating Team C data step by step.** The TEAM_C fingerprint would change at every step, and earlier Team C traces would stop running. Rejected in favour of one generation in step 1.
- **Storing the fainted count per side.** There is no spare side byte without a layout change, and the count is exactly derivable (4.1).

## 9. Points for the owner

1. Two public data kinds, `TEAM_C` (4) and `TEAM_C_DEV` (5), names open (step 1).
2. The engine reads the extended tables under every combat kind. The closure is their exact prefix, proved by a test, so the CLOSURE fingerprint stays (3.2).
3. Setup rules under TEAM_C: the closure's (mixed teams, any item), or set items only (3.4).
4. Additive public changes per step, each with a minor version bump:
   - AILMENT_POISON, TERRAIN_PSYCHIC and a field value;
   - CAUSE_POISON for poison's residual line (added in step 6, not foreseen here);
   - new event kinds;
   - three bits of the position view's `reserved` byte (Follow Me, Helping Hand, Unburden);
   - the choice lock shown in `locked_slot` (4.2).
5. Last Respects' count is derived from the roster instead of stored (4.1).
6. Step 9a (harness) is its own PR, and step 12 (the Team C gate) closes the track.
7. The track follows draw alignment B and the DEV profile, both confirmed with decision 0010; TEAM_C takes over 0010's profile freeze (3.4).

## 10. As built

### 10.1 Step 1: data, kinds, gate and the data-only mechanics

- **Tables.** `gen_closure.py --team-c` writes `src/data/extended_tables.{h,c}`: 23 formes, 50 moves, 16 items and 21 abilities. The canonical bytes are 2438 long and hash to `d16b1cef…`. The closure group is built first, and the generator checks the prefix before it writes. `duoforge.data.extended_tables` checks:
  - the closure rows, field by field;
  - the closure canonical bytes recomputed from the prefix, which hash to the closure hash;
  - the Team C rows against literal values from the pin;
  - the stat lines against the pin's `spreadModify`. Basculegion (Jolly) is 197/164/85/90/95/143; mechanics.md section 2 had listed the Adamant line and is corrected.
- **Kinds.** The engine reads the extended tables under every combat kind. `dfi_kind_limits` keeps the CLOSURE kinds at the closure prefix (16 formes, 11 items). TEAM_C takes over the certified profile of decision 0010 (a context of 6 and 4, exactly six members per side, `dfi_kind_full_roster`); TEAM_C_DEV takes four to six, as CLOSURE_DEV. The state model gives the fingerprints KC `520eca89…` and KD `3005a212…`; K1 and K2 are unchanged.
- **Gate.** Step 1 marks Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet, Defiant and Adaptability. `duoforge.state.team_c_setup` checks the gate for each of the 22 Team C mechanics, together with validation and invariants per kind.
- **Mechanics.**
  - Defiant is Competitive's branch with Attack: per lowered stat and only from a foe, so a Parting Shot triggers it twice.
  - Adaptability makes STAB 8192/4096.
  - The five moves use existing paths.
- **Evidence.** Five recorded battles (`c01_*`, run by `duoforge.reference.conformance_team_c`; one, `c01_team_c_profile`, under TEAM_C itself with six registered members against the real Team A, the others under TEAM_C_DEV) cover:
  - Defiant and Competitive after Intimidate (at the lead and on a pivot-in), Snarl, and a foe's Parting Shot, with none after an ally's;
  - Hyper Voice against a Ghost type and against Protect;
  - Draco Meteor's accuracy and self-drop, and Kowtow Cleave;
  - Wave Crash in rain with recoil, Aqua Jet in Mega Charizard Y's sun, and Adaptability;
  - Grass Knot at 100, 80 and 60.

  Negative controls: without the Defiant branch, or with STAB 1.5 for Adaptability, these battles fail. A review agent's mutations (the six-member rule of a decoded TEAM_C state, the CLOSURE forme limit at setup) are caught by `duoforge.state.team_c_setup`.
- **Not reachable:** a self-inflicted drop on a Defiant or Competitive holder. Kingambit's and Milotic's sets have no self-drop move, so the corresponding item of section 5's step-1 row cannot occur.
- **Tooling.**
  - Specs with `"data": "team_c"` go to `tests/reference/conformance_team_c.h`. The converter reads them with the extended tables and maps Indeedee-F's protocol name "Indeedee" explicitly (`sim/pokemon.ts:329-330`).
  - At a PIVOT in the middle of the turn a fainted, unreplaced slot is not requested, because `checkFainted` runs only with an empty queue. `c01_defiant_competitive` reaches it (Salamence faints, then Incineroar uses Parting Shot); the main session's `mid_turn` rule (PR #37) converts it, and `conformance.h` is unchanged.
- **Version.** The two data kinds are an additive public change: the library goes from 0.8.0 to 0.9.0 (section 4.2).
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (two constants, comments);
  - `src/state/{context,battle,closure_member,invariants}.c` and their headers;
  - `src/combat/turn.c` (table reads, Defiant, Adaptability);
  - `src/data/support_manifest.{h,c}`;
  - `tests/test_closure_setup.c`, `tests/test_conformance.c`;
  - `tools/state_model/state_v3_model.py`.

### 10.2 Step 2: Flare Blitz and Darkest Lariat

- **Flare Blitz.** A frozen user of a defrost move skips the freeze check in BeforeMove: no draw and no counter (`data/mods/champions/conditions.ts:47`). The freeze's `onModifyMove`, inherited from `data/conditions.ts:106-111`, thaws the user before the move line. The event is CURE_STATUS with cause MOVE and the move id. Recoil, the 10 % burn and thawing a frozen target with a Fire hit use the existing paths.
- **Darkest Lariat.** `ignoreDefensive` sets the target's Defense stage to neutral in both directions (`sim/battle-actions.ts:1691-1700`). `ignoreEvasion` drops the target's evasion from the accuracy check (`:719`); no move in the data changes evasion, so this second part is unreachable. The guard against unknown special handlers in `turn.c` now admits `DARKEST_LARIAT`; later Team C specials still fail it explicitly.
- **Evidence.** Three recorded battles:
  - `c02_flare_blitz`: Flash Fire absorbs Flare Blitz (no recoil), Politoed resists it in rain, it is super effective into Gholdengo, and Incineroar faints from its own recoil;
  - `c02_flare_blitz_thaw`: Ice Beam freezes Incineroar (Fire types can be frozen; only Ice types are immune), then it thaws through Flare Blitz;
  - `c02_darkest_lariat`: hits through Coil and Stamina boosts, under Reflect.

  Negative controls: without the BeforeMove skip, without the ModifyMove thaw, or without `ignoreDefensive`, a battle fails.
- **Converter.** A `-curestatus` line keeps its `[from] move:` cause. `conformance.h` is unchanged.
- **Shared files touched:**
  - `src/combat/turn.c` (BeforeMove, ModifyMove, damage, accuracy, the specials guard);
  - `src/data/support_manifest.c`;
  - `include/duoforge/duoforge.h` (comment only);
  - `tools/reference/trace_to_c.py`.

### 10.3 Step 3: Salamencite, Salamence-Mega and Aerilate

- **Mega Evolution.** The existing machinery covers Salamencite: the Mega action, the forme's stats and ability from the extended tables, one Mega per side, and no second Intimidate. The manifest marks the stone and Aerilate.
- **Aerilate.** `onModifyType` (priority -1) turns a Normal move into Flying after Weather Ball's own type change and before immunity, type effectiveness and STAB. Weather Ball is in its `noModifyType` list, and Struggle is typeless by then. A move it changed gets 4915/4096 first in the BasePower chain (priority 23, ahead of Tough Claws' 21) (`data/abilities.ts:57-77`).
- **Evidence.** `c03_mega_salamence`:
  - the Normal Hyper Voice does not affect Ceruledge;
  - after the Mega, the Flying Hyper Voice hits Gholdengo (resisted) and Ceruledge;
  - Tailwind and Draco Meteor come from the Mega forme.

  Negative controls: without the type change, or without the BasePower boost, the battle fails.
- **Shared files touched:** `src/combat/turn.c` (move type, BasePower chain) and `src/data/support_manifest.c`.

### 10.4 Step 4: Last Respects and Flip Turn

- **Last Respects.** The base power is 50 + 50 for every member of the user's side at 0 HP (`data/moves.ts:10091-10105`). This equals `side.totalFainted` (`sim/battle.ts:2554`) for the reasons in section 4.1; nothing is stored.
- **Flip Turn.** At the point of `runMoveEffects`, after the damage and before the self-drops, secondaries, DamagingHit and Emergency Exit, the user is flagged to switch when the move hit a target and the user still stands (`sim/battle-actions.ts:1290-1312`). As for Parting Shot, the flag is set only when a reserve can come in. The existing PIVOT boundary does the rest.
- **One state change.** The switch flag byte gets the value 4, `DFI_SWITCH_FLIP_TURN`, which is valid only under the TEAM_C kinds (`dfi_kind_limits.switch_flag_max`). It is needed because the switch happens in the next step, and its event says `[from] Flip Turn` (Showdown keeps `switchFlag = move.id`). Under CLOSURE the value is out of range (VOLATILE). The layout does not change, and `state_v3_model.py` mirrors the range.
- **Evidence.** Three recorded battles:
  - `c04_flip_turn`: Flip Turn into Protect does not switch. When Flip Turn drops Golisopod below half, Emergency Exit and Flip Turn ask both sides at one PIVOT. With no reserve left, no switch is requested.
  - `c04_flip_turn_ko`: after a KO of its target, the user still switches.
  - `c04_last_respects`: an ally fainted earlier in the same turn already counts.

  Negative controls: without the flag, with a fixed base power of 50, or with `[from] Parting Shot`, a battle fails. A white-box test checks the flag range per kind.
- **Converter.** `[from] Flip Turn` is a MOVE cause, like Parting Shot.
- **Review findings, fixed.**
  - A slot that passes at a PIVOT keeps its flag (`choosePass`, `sim/side.ts:1330-1357`). With two flags on one side and one reserve (Flip Turn on its own ally, whose Emergency Exit fires), the side is asked again after the switch, with the Pokemon that left as the reserve. Before the fix the engine dropped the flag. `c04_flip_turn_double_pivot` records it, including the cancelled move of the second Pokemon to leave. The converter asks a slot exactly when its switch flag is set. That covers this case as well as main's mid-turn rule for fainted Pokemon, and `conformance.h` is unchanged.
  - The fainted count only counts brought members.
  - Last Respects is recorded at counts 0 and 1; 2 and 3 use the same formula, and no seed reached them.
- **Shared files touched:**
  - `src/combat/turn.c` (base power, the flag, the switch event);
  - `src/state/{battle_internal,closure_member}.h`, `closure_member.c`, `invariants.c`;
  - `src/data/support_manifest.c`;
  - `tools/reference/trace_to_c.py`, `tools/state_model/state_v3_model.py`.

### 10.5 Step 5: Chople Berry and Rocky Helmet

- **Chople Berry.** In the ModifyDamage chain of the damage calculation, after burn and before the 16-bit truncation (`data/items.ts:1030-1053`). The target eats it when the move is Fighting and super effective against it: `[-enditem] [eat]`, then `[-enditem] [weaken]`, then 2048/4096. The berry is gone for later hits (the consumed flag). The `[weaken]` line is ITEM_END with `detail` 1; the public header documents this (no new event kind, unlike the plan in section 5).
- **ModifyDamage order.** The reference runs the attacker's Life Orb and the target's Chople Berry by their holders' speed (`comparePriority`). A screen is a side condition, which counts as speed 0, so it runs last, or first under Trick Room, where the speeds are negative. Every order of the three modifiers (5324, 2048 and 2732) chains to the same value, and `turn.c` checks this at compile time. So the engine chains them in one fixed order without a speed comparison. When the two holders have the same speed, the reference shuffles the two handlers; the shuffle decides nothing. The converter drops that draw, and the engine does not draw (decision 0006 section 5.1, proposal B).
- **Rocky Helmet.** At DamagingHit with `onDamagingHitOrder` 2, before the order-less handlers (thaw, Stamina). Those run left to right (`compareLeftToRightOrder`, `sim/battle.ts:421-426`). The helmet also hits when the hit knocked its holder out, because the faint is not processed yet. A contact move costs the attacker floor(maxHP / 6), at least 1 (`data/items.ts:5295-5309`). Afterwards the attacker's own Emergency Exit is checked against its HP before DamagingHit (`data/mods/champions/scripts.ts:406, 419-420`). A Flip Turn user that the helmet knocks out loses its switch flag with the faint (`faint()`, `sim/pokemon.ts:1585`). The engine clears it with the position's other state when the faint is processed, so no pivot follows.
- **A win inside the hit loop.** With the attacker at 0 HP, which only Rocky Helmet causes, the hit loop's `faintMessages` also checks the win (`data/mods/champions/scripts.ts:546`). The result line therefore comes before the rest of the action. The reference still runs that rest and shows its lines, such as a target's Emergency Exit (`:578-590`). The engine shows RESULT there and not again at TERMINAL. Before this, an attacker could not be at 0 HP at that point. So under the TEAM_C kinds RESULT is no longer always the last event of the final step: an Emergency Exit can follow it, as in the reference. Under CLOSURE nothing changes; the batch runtime and the certifier scan all events for RESULT.
- **Evidence.** Ten recorded battles:
  - `c05_chople_berry`: eaten with Life Orb and Reflect in one chain, without a KO, and gone for the next hit.
  - `c05_chople_neutral`: Close Combat into a holder that Fighting hits neutrally does not eat the berry. The Life Orb and Chople Berry tie is recorded.
  - `c05_rocky_helmet`: Fake Out, and a KO of the holder before the attacker's recoil.
  - `c05_rocky_helmet_faint`: Staraptor faints to the helmet, with neither recoil nor Life Orb after it.
  - `c05_flip_turn_helmet`: no pivot after a helmet KO.
  - `c05_helmet_exit`: a non-contact move costs nothing. Golisopod's Emergency Exit fires after the helmet.
  - `c05_helmet_order`: Close Combat's self-drops and Leech Life's drain come before the helmet.
  - `c05_helmet_sitrus`: Sitrus Berry is eaten in the Update after the helmet's damage, before the faint line.
  - `c05_helmet_endgame`: Golisopod with the helmet and Emergency Exit. The helmet's damage comes before the target's Emergency Exit. When the helmet knocks out a side's last Pokemon, the order is `faint`, `win`, then Emergency Exit.
  - `c05_focus_blast_struggle`: Focus Blast eats the berry. Struggle makes contact, and the helmet's damage comes before Struggle's recoil.

  Eleven negative controls each make a battle fail:
  - no halving, eating on a neutral hit, no `[weaken]` line, no `[eat]`;
  - the helmet without the contact check, only for standing holders, at 1/8, or without the attacker's Emergency Exit;
  - the helmet moved before the self-drops or after the Update;
  - no win check in the hit loop.
- **Not recorded.**
  - The Life Orb and Chople Berry tie in a hit that eats the berry, and the three modifiers under Trick Room. The compile-time check covers both.
  - A frozen or Stamina holder of the helmet, whose handlers run after it by order.
- **Converter.** A ModifyDamage tie between `lifeorb` and `chopleberry` is dropped; any other ModifyDamage tie still fails.
- **Review findings, fixed.** The win inside the hit loop. The order argument, which assumed the screen always runs last. The citations. Two recorded battles added.
- **Version.** ITEM_END `detail` 1 is an additive public change, so the library goes to 0.12.0 (section 4.2; 0.11.0 is M7's).
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (comment of ITEM_END);
  - `src/combat/turn.c` (the chain, the eaten flag, DamagingHit, the attacker's Emergency Exit and the win in the hit loop);
  - `src/data/support_manifest.c`;
  - `tools/reference/trace_to_c.py` (`[weaken]`, the tie rule).

### 10.6 Step 6: Dire Claw and poison

- **Dire Claw.** The Champions override (`data/mods/champions/moves.ts:217-227`) has a 30 percent secondary. Its `onHit` draws `sample(['psn', 'par', 'slp'])` and calls `trySetStatus` without a source effect.
- **The pick is drawn whenever the reference draws it.** The reference draws it after every successful secondary roll (`sim/battle-actions.ts:1336-1352`). That includes a target the hit knocked out, a target that already has a status and a target that is immune to the pick, because the secondary's hit path checks no HP (X9).
  - The engine draws the pick at draw site 13, `DFI_SITE_STATUS_PICK`, under the same conditions.
  - The converter maps the harness's `SECONDARY[0,3)` in context `Hit` to that site and keeps every pick.
  - This settles the open question of section 4.3 under draw alignment B. Dropping a pick that decides nothing would need the target's status at that moment, which the converter cannot check against a trace. So no pick is dropped, as for the secondary roll at 100 percent.
- **The status.**
  - Poison is status 5, `DFI_STATUS_PSN`. It is valid in a member only under the TEAM_C kinds, through `dfi_kind_limits.status_max`, and has no counter.
  - Poison and Steel types are immune. They are read from the type chart's `psn` key, which is the immunity bit `DFI_IMMUNE_PSN`.
  - Electric types cannot be paralysed (existing).
  - A failed pick is silent, because the secondary has no `status` field.
  - A sleep the pick causes shows `-status|…|slp` without `[from]`: its source effect is not a move (`data/mods/champions/conditions.ts:13-20`). The other sleep sources keep `[from] move`.
- **Residual.** Poison's handler has order 9 (`data/conditions.ts:123-137`). It runs after Leftovers and Grassy Terrain (order 5) and before burn (order 10); same-order handlers run by speed. It deals baseMaxhp / 8, at least 1, with `[from] psn`.
- **Public values, appended:**
  - `DUOFORGE_AILMENT_POISON` (5);
  - `DUOFORGE_CAUSE_POISON` (14), for the residual line. This cause was not named in section 4.2.

  Both are additive: library 0.13.0, coordinated with the main session, which also moved the Python package's expected version.
- **Evidence.** Three recorded battles:
  - `c06_dire_claw` records:
    - the paralysis and sleep picks, the sleep line without `[from]`;
    - Raichu not paralysed and Sneasler not poisoned, both silently;
    - a pick drawn for a target that already has a status.
  - `c06_poison_residual` records poisoning, then Leftovers and Grassy Terrain before poison's damage, and two poisoned Pokémon in one residual phase. There the faster one is also in the earlier slot, so slot order is not ruled out by this battle. Giving poison's handlers no speed would still fail, because it adds a tie draw the tape does not have.
  - `c06_poison_burn` records:
    - poison before burn in one residual phase;
    - a Dire Claw that knocks its target out and still draws the pick;
    - Dire Claw into Archaludon (`-immune`).

  Ten negative controls each make a test fail:
  - no pick for a fainted target, or for a target with a status;
  - another pick order;
  - no poison immunity;
  - `[from] move` on the pick's sleep;
  - poison's order 11 or 4;
  - 1/16 damage;
  - burn's cause on poison's line;
  - poison valid under CLOSURE.
- **Not recorded.**
  - Good as Gold never meets Dire Claw's secondary, because a Poison move cannot hit Gholdengo (Steel). For the same reason, Steel's poison immunity cannot be reached through Dire Claw.
  - The minimum of 1 damage cannot be reached at level 50.
  - A speed tie between two poisoned Pokémon and a poison KO that ends the battle are reachable but not recorded. Both run through burn's existing code (the tie draw, the faint processing after each residual handler).
- **Converter.**
  - `psn` in the state and event maps;
  - `[from] psn` as cause 14;
  - the pick's site; any other draw in context `Hit` fails loudly;
  - an unknown status in an HP field fails loudly instead of reading as none.
- **Review findings, fixed.**
  - Two spec purposes claimed cases their battles do not show.
  - The converter's `Hit` guard checks every draw, not only SECONDARY.
  - An unhandled residual callback is `E_INVARIANT` instead of burn's damage.
  - A stale comment.
- **Shared files touched:**
  - `include/duoforge/duoforge.h`;
  - `src/rng/draw.h`;
  - `src/state/closure_member.{h,c}`;
  - `src/state/observation.c` (an assertion);
  - `src/combat/turn.c`;
  - `src/data/support_manifest.c`;
  - `tools/reference/trace_to_c.py`.

### 10.7 Step 7: Choice Scarf

- **Speed.** Choice Scarf's `onModifySpe` is `chainModify(1.5)` (`data/items.ts:983-1005`). It chains with Tailwind's `chainModify(2)` into one modifier, which is applied once. Paralysis then halves the result: its handler runs last, at priority -101, with `finalModify` and then floor 50/100 (`data/conditions.ts:30-37`). `dfi_speed_key` does the same. A fainted holder has no handlers, so it keeps its raw Speed.
- **The choice lock.** Choice Scarf's `onModifyMove` adds `choicelock`, whose `onStart` stores the move (`data/conditions.ts`).
  - **When it starts.** `ModifyMove` runs when the move is used: after BeforeMove and PP, before the move line. A move that BeforeMove stops (flinch, sleep, full paralysis) sets no lock. A move that Protect blocks or that fails does set it.
  - **Struggle sets none.** Struggle is not in the move slots, so `onDisableMove` would remove its lock at the next request, before it could matter.
- **State.** Volatile bit 64, `DFI_VOL_CHOICE_LOCK`, valid only under the TEAM_C kinds (`dfi_kind_limits.vol_flags_mask`). The move is in the locked-move byte, which the lock shares with a charging two-turn move.
  - The byte is set exactly when a charge or a choice lock is. Both together are on the same move: a choice lock disables every other move, and a charge starts only on Electro Shot.
  - A target is stored only while charging.
  - A choice lock needs its holder to hold a Choice Scarf.
  - When a charge ends, or a locked turn cannot move, the choice lock and its move stay ("the choice lock outlives the charge").
  - Leaving the field clears the lock with the rest of the position.
- **The request.** The lock offers only the locked move, with any of its targets (`onDisableMove`). With no PP, or with Champions' Fake Out rule, the slot gets Struggle. The lock does not trap.
  - The request's two-turn branch now tests `charge_turns`, no longer `locked_move`. Both meant the same before the choice lock.
- **Observation.** A choice lock is public: `locked_slot` shows it, `charging` is 0, and `locked_target` is `DUOFORGE_TARGET_NONE`. The own locked target is shown only while charging. That is an additive public change of an existing field (sections 4.2, 9.4): library 0.14.0, coordinated with the main session (the Python encoder reads `locked_slot` only as a flag). Under CLOSURE the views are byte-identical.
- **Harness and converter.**
  - `ps_trace.js` records a lock's slot as `choice`, only when the volatile exists, so every older trace is byte-identical (the harness version stays 14).
  - The converter compares it as volatile bit 8 and as the locked slot without a target. A lock on a move outside the slots, or on another move than a two-turn lock, fails loudly.
  - **A converter fix.** A slot plays Struggle when the reference's request offers Struggle. Before, the converter decided by "all PP 0", which missed a locked Fake Out (found by the differential-testing study). A request without Struggle while every PP is 0 fails loudly.
- **Evidence.** Five recorded battles:
  - `c07_lock_start`: Fake Out flinches Kingambit before its first move, so no lock, and the next request offers every move. Its first move then hits Protect, which locks it, and the next request offers only that move.
  - `c07_choice_lock`:
    - Basculegion's first move, Flip Turn, locks it, and leaving ends the lock; it returns unlocked;
    - Incineroar, locked into Fake Out, Struggles on its next turn, then switches out by choice;
    - x1.5 speed.
  - `c07_scarf_electro_shot`:
    - Archaludon's Electro Shot charges and locks at once, and the lock outlives the charge;
    - Farigiraf, locked into Protect, may only Protect, with the stall chance.
  - `c07_scarf_paralysis`: a paralysed Scarf Basculegion (143) has 107 and ties with Incineroar (107), so the queue draws. With paralysis before the Scarf it would have 106.
  - `c07_scarf_abort`: on the locked turn Archaludon cannot move, so the charge ends and the choice lock stays.

  Ten negative controls each make a test fail:
  - the lock set before BeforeMove;
  - no x1.5;
  - paralysis before the chain;
  - no lock at ModifyMove;
  - a request that ignores the lock;
  - a lock that traps;
  - a charge end, or an aborted locked turn, that drops the lock;
  - a choice lock showing a target;
  - no Choice item check.

  A choice lock valid under CLOSURE cannot be told apart, because the Choice item check rejects it there anyway.
- **Not recorded.** Tailwind with Choice Scarf: x3 is exact, and paralysis on top is the same chain as in `c07_scarf_paralysis`.
- **Review findings, fixed.**
  - When the lock starts was not recorded (`c07_lock_start`).
  - A choice-locked actor whose queued move is neither its locked move nor Struggle is `E_INVARIANT`. That needs a decoded state, because the request offers nothing else; choicelock's `onBeforeMove` (`-fail`) is unreachable.
  - The state model mirrors the domain and the observation: two-turn and Fake Out rules for every combat kind, the choice lock's slot filter, the own target only while charging. Its output is unchanged.
  - Bound comments.
- **Found on the way, outside this step.** The request offers Struggle with Mega declarations. The reference sends no `canMegaEvo` with a forced Struggle (`sim/pokemon.ts:1100-1106, 1132-1138`; `sim/side.ts:700-712`). This is a closure divergence that changes certified candidate counts, so it is left to a separate task and the owner.
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (comments of `locked_slot`, `locked_target`; version);
  - `src/state/{battle_internal,closure_member}.h`, `closure_member.c`, `invariants.c`, `observation.c`, `request.c`;
  - `src/combat/turn.c`;
  - `src/data/support_manifest.c`;
  - `tools/reference/{ps_trace.js,trace_to_c.py}`;
  - `tools/state_model/state_v3_model.py`;
  - `tests/test_conformance.c` (the lock comparison, the target only while charging).

### 10.8 Step 8: White Herb and Unburden

- **White Herb** (`data/items.ts:7658-7712`). Each of its handlers runs one check: a standing holder with a lowered stat uses the herb (`useItem`, `sim/pokemon.ts:1811-1849`). The use shows `[-enditem]`, then the lowered stages go back to 0 (`-clearnegativeboost` is `[silent]`). Raised stages stay. Then AfterUseItem runs (Unburden).
  - **Switch-in.** The check runs in `onAnySwitchIn` (priority -2), after the entry abilities (priority 0) and the Grassy Seeds (priority -1), for every holder on the field.
    - The herb's own `onStart` does not run at its holder's entry: an item with `onAnySwitchIn` keeps its `onStart` out of the switch-in event (`sim/battle.ts:1024-1025`).
    - The holders run in runSwitch's speed order. Their handlers' fractional speeds follow it (`sim/battle.ts:1008-1013`), so the event itself draws nothing.
    - runSwitch's speed sort shuffles every tie. The engine draws a tie group when it holds two entering Pokémon with an entry ability, as before, or two standing herb holders.
  - **AfterMega** (`sim/battle-actions.ts:1914`): after the Mega's entry ability.
  - **AfterMove** (`sim/battle-actions.ts:311-312`): after every move that got past BeforeMove, also after a move that Protect blocks or that fails. A move that BeforeMove stops has no AfterMove.
  - **The handlers of AfterMega and AfterMove.** In the data, White Herb's `onAnyAfterMega` and `onAnyAfterMove` are the only handlers of these events.
    - `runEvent` collects them from the standing holders: `side.allies()` keeps the Pokémon with HP. It takes the user's side first, then the foe side, each in slot order (`sim/battle.ts:1053-1063`).
    - `speedSort` shuffles equal speeds, so two holders at one speed draw at every AfterMega and AfterMove, even when no herb is due. The engine sorts and draws the same way.
  - **A user that fainted inside its own move.** `runEvent` collects Any handlers only while the user or runMove's target is active (`sim/battle.ts:1053`). A Pokémon whose faint the hit loop showed is not active (`:2566`).
    - So when a Fake Out into a Rocky Helmet makes both the user and its target faint, AfterMove runs no herb check and draws nothing. The herb waits for the next check.
    - The engine keeps runMove's target: getTarget's result, before any redirection.
    - A spread move's runMove target is a random foe that the engine does not draw. In that case the step is `E_UNSUPPORTED` when the handlers would do anything. With the data, only a Rocky Helmet makes the user faint there, against a single-target contact move.
  - **Residual, order 29.** This is an item, so sub-order 8.
    - The reference sorts the residual handlers once, with all their draws, before any runs. So the draws come in this order: the callbacks of orders 1 to 10, the side conditions (26), then the herbs (29).
    - The herbs run after the side conditions (26), Trick Room and the terrain (27), and before the volatiles' durations.
    - The engine keeps the side conditions without their kinds, so the start order of the herbs' shuffle can differ from the reference's. Two holders due in one group of equal speed are therefore `E_UNSUPPORTED`.
- **Unburden** (`data/abilities.ts:5235-5257`).
  - When its holder uses an item (a berry, a Grassy Seed or the herb), AfterUseItem adds the volatile.
  - The volatile is `chainModify(2)` in the speed chain while the holder holds no item. Once the volatile is set the holder never has an item again, since nothing in the data gives one back.
  - The volatile chains with Tailwind into one modifier, before paralysis (section 10.7). A Choice Scarf cannot be in the same chain, because the item is gone.
  - The queue is sorted again before each move action, so the new speed counts from the next move on, within the same turn. It also counts in the speed order of later events.
  - `onTakeItem` is unreachable: no move in the data takes an item.
  - Leaving the field ends the volatile with the rest of the position.
- **State.** Volatile bit 32, `DFI_VOL_UNBURDEN`. It is valid only under the TEAM_C kinds (`dfi_kind_limits.vol_flags_mask`), and only on an Unburden holder whose item is used (`item` set and `item_consumed` 1). The state model (`tools/state_model/state_v3_model.py`) mirrors the bit, this rule and the view's bit; its output is unchanged.
- **Observation.** Unburden is public: the ability is open, and the item's use is shown.
  - Under the TEAM_C kinds the position view's `reserved` byte carries `DUOFORGE_POSITION_FLAG_UNBURDEN` (4). Bits 1 and 2 stay 0 until Follow Me and Helping Hand are built. The byte keeps its name, so the change is additive; a rename to `flags` would not be, and is left to the owner.
  - Under CLOSURE the byte stays 0, so every closure view keeps its bytes.
  - Library 0.16.0, coordinated with the main session (0.15.0 went to `duoforge_batch_step_query`).
  - The Python feature encoder refuses a nonzero byte (`ValueError`), as it refuses every value it does not know, until it encodes the bit. Whether and how it should is the main session's decision.
- **Harness and converter.**
  - `ps_trace.js` already records every volatile; the converter compares `unburden` as volatile bit 16.
  - A runSwitch tie group now lists a standing Pokémon's `onAnySwitchIn` effects (White Herb), only when it has any. All 124 earlier traces are byte-identical, so the harness version stays 14.
  - The converter keeps a switch-order tie with two standing herb holders, and every AfterMove or AfterMega tie among herb handlers. A tie with any other handler fails loudly.
- **Evidence.** Eight recorded battles:
  - `c08_herb_intimidate`: the opening Intimidate lowers Sneasler's Attack, and the herb restores it in the switch-in sequence, after Milotic's Competitive. Unburden doubles Sneasler's Speed from turn 1 (X1), so it moves before a Choice Scarf Basculegion. A later Close Combat lowers its defences with no herb left.
  - `c08_herb_moves`: the herb after the holder's own Close Combat (X2) and after its own Draco Meteor.
  - `c08_herb_targets`: the herb after another Pokémon's move, Snarl and Parting Shot.
  - `c08_herb_competitive`: on Milotic, Intimidate lowers the Attack and Competitive raises the Special Attack by 2 inside that boost. The herb restores only the Attack, and the +2 stays for Ice Beam.
  - `c08_unburden_resort`: Grimmsnarl's Prankster Parting Shot (+1) lowers a slow Sneasler's attacks first, and the herb restores them. In the queue sorted again before the next move, Sneasler then moves before Raichu, which was faster at the start of the turn. Without the herb, Raichu moves first (checked in the reference, not recorded).
  - `c08_unburden_berry`: Unburden after a Sitrus Berry; switching out ends it, and the berry stays gone.
  - `c08_herb_mirror`: both sides lead Sneasler and Incineroar. Both Intimidates lower both Sneaslers' Attack, and the two herbs, at one Speed, run in runSwitch's drawn order.
  - `c08_herb_ties`: an unused herb on each side's Sneasler, at one Speed.
    - The AfterMega of Raichu's Mega Evolution, and every AfterMove, shuffle the two checks.
    - The residual sorts the herbs after Reflect and Grassy Terrain; this is the case the review found failing.
    - Close Combat then lowers one Sneasler's defences, and its herb restores them after the drawn order.

  Three tests through the public API:
  - Two herbs due at one switch-in: the faster holder's comes first. At one speed the tie is drawn, and over 16 seeds both orders show.
  - Fake Out into a Rocky Helmet (white-box states at 1 HP): with the user and the target fainting, the herb waits for the next move's AfterMove. With either one standing, it follows the Fake Out.
  - Unburden's bit is invalid on an Unburden holder whose item is still held.

  Fifteen negative controls each make a test fail:
  - no herb at a switch-in;
  - no herb after a move, by removing the check or by never setting the used-move point;
  - a herb without a lowered stat;
  - a herb that also resets raised stages;
  - no switch-in draw for two herb holders;
  - no AfterMove or AfterMega draw;
  - AfterMove's handlers collected with the user and the target fainted;
  - the herbs sorted with the early residual callbacks (the review's case);
  - no herb in the residual;
  - no Unburden on an item use;
  - no Unburden in the speed chain;
  - Unburden hidden in the view;
  - no ability check, or no item-used check, in the invariant.
- **Not recorded.**
  - A herb used in the residual or at AfterMega: with the data every lowered stat meets an earlier check, and no Mega forme lowers a stat on entry.
  - Two herbs due at one AfterMove: no move in the data lowers the stats of two herb holders, and the Item Clause keeps them on different sides. So the order within an AfterMove or AfterMega tie never shows; only its draws do.
  - The plan's Contrary Mega Staraptor (section 5): a Mega holds its stone, so it cannot hold the herb.
  - Whether AfterMove follows a move that BeforeMove stopped cannot be observed with the data: no herb stays due until then.
- **Review findings, fixed.**
  - **Blocking.** The herb's residual entry (order 29) broke the residual's split into callbacks and duration handlers. With a held herb and a side condition, Trick Room or a terrain, the end of the turn failed with `E_INVARIANT`. The residual now sorts as the reference does, as described above, and `c08_herb_ties` records it.
  - **Herb ties.** A tie between two herb holders now follows the reference's draws at the switch-in, at AfterMega and at AfterMove, where step 8's first version rejected it. A step-12 Team C mirror needs this.
  - **A user that fainted inside its move.** The case is now modelled exactly; before, a herb due there was `E_UNSUPPORTED`.
  - **Public field.** The `reserved` byte keeps its name; the rename to `flags` would not have been additive.
  - **Python encoder.** It refuses the new bit instead of dropping it silently.
  - **Smaller items.**
    - A test for the item-used rule.
    - The conformance diagnostic now prints Unburden.
    - Two spec purposes claimed a Speed effect that their battles do not show; now they claim only the volatile.
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (the bit of the position view's `reserved` byte, version);
  - `src/state/{battle_internal.h,closure_member.c,invariants.c,observation.c}`;
  - `src/combat/turn.c`;
  - `src/data/support_manifest.c`;
  - `python/duoforge/{features,_lib}.py`, `python/tests/{test_lib,test_policies_features}.py`;
  - `tools/reference/{ps_trace.js,trace_to_c.py}`, `tools/state_model/state_v3_model.py`;
  - `tests/reference/conformance.h` (a comment only);
  - `tests/test_conformance.c` (the Unburden comparison), `tests/test_api_atomicity.c` (version), `tests/test_team_c_setup.c`.

### 10.9 Step 9a: ally targets in the harness

- **The gap (section 6.2).** `ps_trace.js`'s plan fix-up gave target 1, a foe, to every planned move that takes a target and names none.
  - Helping Hand (`adjacentAlly`) takes only the ally's slot, so the reference rejected the choice ("Invalid target for Helping Hand") and the run aborted.
  - Plans that never name Helping Hand hit this too, through the fix-ups that pick another move: no PP left, or Fake Out disabled after the first turn.
- **The fix.** `planMove` aims an `adjacentAlly` move at the ally's slot: -2 from the left position, -1 from the right one.
  - A plan that names an own-side target (-1 or -2) keeps it, so a spec can name the ally target itself.
  - Nothing else changes.
- **Byte identity.**
  - No committed trace plans an `adjacentAlly` move: the closure has none, and Helping Hand is still gated.
  - `ps_trace.js --check` passes on all 126 committed traces, so the harness version stays 14.
- **Evidence (an ad-hoc run, not committed).** 36 random-plan battles of the real Team C (`docs/research/third-team/team-c.txt`) against Team A and Team B, with three rotations of Team C's order, three seeds and both sides.
  - Before the fix: 19 ran to the end; 17 aborted with "Invalid target for Helping Hand".
  - After the fix: all 36 ran to the end, with 0 UNKNOWN draw sites and Helping Hand used 23 times.
- **Shared files touched:** `tools/reference/ps_trace.js` (`planMove` and its comments).

### 10.10 Step 9b: Sucker Punch and Helping Hand

- **Sucker Punch** (`data/moves.ts:18396-18415`): priority +1, contact, Dark, 70 power.
  - Its `onTry` runs in trySpreadMoveHit after TryMove (Armor Tail) and before the hit steps (Protect), the same point as Fake Out's. It fails (`-fail`, `[still]`) unless `queue.willMove(target)` finds the target's queued move action and that move is not a status move.
  - `willMove` (`sim/battle-queue.ts:324-332`) reads the actions still queued. The engine reads its own queue, bound by the target's activation. So the move fails when the target already moved, when it switches (a newcomer has no move queued), and when it fainted. No Me First and no recharge are in the data.
  - Struggle counts as an attack; a two-turn or choice-locked move counts as its move.
- **Helping Hand** (`data/moves.ts:8573-8606`): priority +5, target `adjacentAlly`, no `protect` flag, so Protect does not stop it.
  - **Target.** It aims at the ally while the ally stands. With a fainted ally, or an empty slot (`getRandomTarget` finds no standing adjacent ally in doubles), the move has no target: `[notarget]` and `-fail`.
  - **Good as Gold.** The TryHit step comes first (`sim/battle-actions.ts:643-653`). There, Good as Gold stops a status move of any other Pokémon, its ally's included (`data/abilities.ts:1630-1636`), with `-immune` and no `-fail`, so a Gholdengo partner gets no boost.
  - **onTryHit.** It fails unless the ally switched in this turn (`newlySwitched`) or still has a move queued.
    - With the data the failure is unreachable. Only Indeedee-F knows the move, its priority comes before every other move, and an ally that switched in is newly switched. So the plan's "on one that already moved (fails)" cannot be recorded.
    - What is reachable is the reverse: Helping Hand on a partner that switched in this turn succeeds although the partner does not move (X4).
  - **The volatile.** The ally gets the volatile for the turn, shown as `[-singleturn] ally|Helping Hand|[of] user`.
    - The volatile is `chainModify(1.5)` in BasePower at priority 10: after Aerilate (23), Tough Claws (21) and the type items (15), before Grassy Terrain (6).
    - Its duration of 1 ends in the residual, where it counts among the duration handlers.
    - A second Helping Hand on the same Pokémon in a turn (`onRestart`) would need a second user, which doubles never has: `E_INVARIANT`.
- **State.** Two volatile bits, valid only under the TEAM_C kinds:
  - 16, Helping Hand: set until the residual, so never at a TURN or REPLACEMENT boundary;
  - 128, `newlySwitched`: set when a Pokémon switches in (`dfi_run_switch`) and cleared at the end of the turn (`sim/battle.ts:1673`), so never at a TURN boundary.

  A REPLACEMENT always follows the residual. A switch request in the middle of the turn is a PIVOT boundary, where both bits may be set. The state model mirrors both bits and these rules; its output is unchanged.
- **Observation.** Helping Hand is public: `DUOFORGE_POSITION_FLAG_HELPING_HAND` (2) in the position view's `reserved` byte, set only while the volatile lasts, so at a PIVOT boundary or at a TERMINAL one in the middle of a turn. `newlySwitched` is not shown; the switch-in line is.
- **Events.** `DUOFORGE_EVENT_SINGLE_TURN` (38): position = the ally, other = the user (`[of]`), id = the move. Protect's `-singleturn` stays `DUOFORGE_EVENT_PROTECT`.
- **Public changes, library 0.17.0** (sections 4.2 and 9.4), coordinated with the main session:
  - the event kind;
  - the view bit.
  - Python reads no event kinds, and its feature encoder already refuses a nonzero `reserved` byte.
- **Request.** The `adjacentAlly` class already offered the ally's position (`request.c`). The turn core now resolves it (`dfi_move_targets`).
- **Harness and converter.**
  - The harness is unchanged since step 9a.
  - The converter maps `-singleturn ... Helping Hand` to the new event, and any other `-singleturn` than Protect fails loudly. It compares `helpinghand` as volatile bit 32 and as the view bit.
  - `newlySwitched` is not recorded by the harness. Its effect is: Helping Hand on a partner that switched in this turn.
- **Evidence.** Four recorded battles:
  - `c09_sucker_punch`:
    - Sucker Punch fails against Gholdengo's Nasty Plot and Milotic's Coil;
    - it hits Gholdengo's Make It Rain;
    - Indeedee-F's Helping Hand comes first each turn (X4). The boosted Sucker Punch is a critical KO, so the x1.5 shows in Kingambit's later Iron Head hits.
  - `c09_sucker_punch_order`:
    - it fails against Ceruledge's faster Shadow Sneak (the target moved first), against Ceruledge's Protect, against Indeedee-F's Trick Room (a status move) and against a target that switches out;
    - under Trick Room the slower Kingambit moves before the Shadow Sneak and hits.
  - `c09_helping_hand`:
    - Helping Hand on a partner that switched in this turn (X4);
    - on Salamence's Hyper Voice, a spread move;
    - Farigiraf's Armor Tail stops Sucker Punch;
    - on Basculegion's Flip Turn, the boost is still shown at the PIVOT boundary.
  - `c09_gold_and_armor_tail`:
    - Good as Gold stops Helping Hand on its ally Gholdengo (`-immune`), so Make It Rain is not boosted;
    - Farigiraf's Armor Tail (TryMove) stops Sucker Punch at Milotic before Sucker Punch's own `onTry` would fail against Milotic's Coil.

  Tests through the public API:
  - at a PIVOT boundary, after Helping Hand, a Flip Turn and a foe's switch in the same turn, both bits are valid; at the next TURN boundary both are gone, and either one there is `VOLATILE`;
  - at a REPLACEMENT boundary, which follows the residual, Helping Hand's bit is `VOLATILE` and `newlySwitched`'s is valid;
  - the gate and the manifest now include both moves;
  - the CLOSURE masks hold neither bit.

  Twelve negative controls each make a test fail:
  - Sucker Punch that never fails, or that ignores the queued move's category;
  - no Helping Hand boost;
  - no `newlySwitched`, or `newlySwitched` never cleared;
  - Helping Hand that ignores `newlySwitched` or Good as Gold, that outlives the residual, without its line, or hidden in the view;
  - no TURN rule for the two bits, or no REPLACEMENT rule for Helping Hand.
- **Not recorded.** Swords Dance and Reflect against Sucker Punch: they take the status-move path of Nasty Plot and Coil.
- **Review findings, fixed.**
  - Good as Gold did not stop Helping Hand, because Helping Hand skipped the TryHit step. This was a silent divergence with a mixed team.
  - The residual list was sized for four duration ends per position; Helping Hand makes five. A decoded state could overflow it. It is now eight entries per position, with an explicit guard.
  - The REPLACEMENT rule and the Armor Tail order had no test.
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (the event kind, the view bit, version);
  - `src/state/{battle_internal.h,closure_member.c,invariants.c,observation.c}`;
  - `src/combat/{turn.c,events.c}`;
  - `src/data/support_manifest.c`;
  - `python/duoforge/_lib.py`, `python/tests/test_lib.py` (version);
  - `tools/reference/{trace_to_c.py,test_trace_to_c.py}`, `tools/state_model/state_v3_model.py`;
  - `tests/reference/conformance_types.h` (a comment only), `tests/support/conformance_compare.c`;
  - `tests/test_conformance.c`, `tests/test_api_atomicity.c` (version), `tests/test_team_c_setup.c`;
  - `docs/support/README.md`.

### 10.11 Step 10: Psychic Surge and Psychic Terrain

- **Psychic Surge** (`data/abilities.ts:3580-3588`) is an entry ability. Its `onStart` calls `setTerrain('psychicterrain')` (`sim/field.ts:130-157`).
  - The same terrain is not restarted.
  - A different terrain is replaced without an end line (no FieldEnd), and TerrainChange follows; a Grassy Seed acts only on Grassy Terrain.
  - Two setters entering together run in runSwitch's speed order, so the slower one's terrain stays.
- **Psychic Terrain** (`data/moves.ts`, `psychicterrain` condition) lasts 5 turns; the data has no Terrain Extender. It ends in the residual at order 27, sub-order 7, with `-fieldend|move: Psychic Terrain`.
  - **`onTryHit`** (priority 4, before Protect's 3) stops a move with positive priority at a grounded foe. It shows `-activate|target|move: Psychic Terrain` and returns null, so there is no `-fail`.
    - The priority is the one `getActionSpeed` wrote into the active move (`sim/battle.ts`, `action.move.priority = priority`), so Prankster's +1 counts. The engine uses `dfi_move_priority`, as Armor Tail does.
    - Allies, self moves and Flying targets are not stopped (the data has no other way to be ungrounded).
    - A spread move would run every target's terrain handler before any Protect handler, in one TryHit event. No spread move in the data has positive priority (Prankster raises status moves, and none of them is spread). The engine returns `E_UNSUPPORTED` for one rather than check target by target.
    - Stopped: Fake Out, Shadow Sneak, Aqua Jet, Sucker Punch (after its own `onTry`) and Grimmsnarl's Prankster Parting Shot.
    - Not stopped: Helping Hand on the ally and Protect.
    - Grassy Glide has priority 0 here: its +1 needs Grassy Terrain, which Psychic Terrain replaces.
  - **BasePower:** a grounded user's Psychic move gets ×5325/4096 at priority 6, the place of Grassy Terrain's boost; the two terrains are never up together.
- **State.** Terrain 2, `DFI_TERRAIN_PSYCHIC`, valid only under the TEAM_C kinds (`dfi_kind_limits.terrain_max`). The state model mirrors the range; its output is unchanged.
- **Public changes, library 0.18.0** (sections 4.2 and 9.4):
  - `DUOFORGE_TERRAIN_PSYCHIC` (2) in the observation's terrain;
  - `DUOFORGE_FIELD_PSYCHIC_TERRAIN` (3) in FIELD_START and FIELD_END;
  - the block as `DUOFORGE_EVENT_BLOCKED` with detail `DUOFORGE_FIELD_PSYCHIC_TERRAIN`; Protect's block keeps detail 0.

  **This differs from the plan.** Sections 4.2 and 5 planned a new event kind for this line. Section 4.2 also lets a new distinction be a `detail` value. A detail on the existing BLOCKED keeps "the move was blocked at this target" in one kind, so a reader of BLOCKED sees both blocks. The choice needs the owner's approval together with the other values.
- **Python.** `_layout.CONSTANTS` and `tools/layout/layout_dump.c` name the new terrain. The feature encoder keeps its terrains (none, Grassy): encoding Psychic Terrain would add a column to `OBS_SIZE`, which is the main session's decision. Until then the encoder refuses terrain 2 with `ValueError` (tested), as it refuses every value it does not know.
- **Converter.** It maps:
  - `-fieldstart|move: Psychic Terrain|[from] ability: Psychic Surge|[of] ...`;
  - `-fieldend|move: Psychic Terrain`;
  - `-activate|...|move: Psychic Terrain`;
  - the state's `psychicterrain`.

  The harness is unchanged.
- **Evidence.** Four recorded battles:
  - `c10_psychic_terrain`:
    - Raichu's Fake Out at Indeedee-F, Grimmsnarl's Prankster Parting Shot and Kingambit's Sucker Punch are stopped;
    - Sneasler's Fake Out at Flying Staraptor hits;
    - Helping Hand on the ally goes on.
  - `c10_priority_blocks`:
    - Fake Out, Basculegion's Aqua Jet and Ceruledge's Shadow Sneak are stopped;
    - Indeedee-F's Psychic gets the boost;
    - the terrain ends after five turns.
  - `c10_terrain_war`: Rillaboom's Grassy Surge, then Ceruledge's Grassy Seed, then the slower Indeedee-F's Psychic Surge, which replaces Grassy Terrain without an end line. Under Psychic Terrain Rillaboom's Grassy Glide has priority 0, so the terrain does not stop it: it hits the grounded Indeedee-F twice.
  - `c10_terrain_orders`:
    - Basculegion's Aqua Jet at a protecting Ceruledge gets Psychic Terrain's line, not Protect's;
    - Raichu's Fake Out at its own protecting ally gets Protect's line, because the terrain does not stop a move at an ally;
    - Raichu's Grassy Seed waits under Psychic Terrain. Rillaboom's Grassy Surge replaces the terrain without an end line, the seed acts, and Aqua Jet hits again.

  A white-box test: terrain 2 is valid under TEAM_C and `FIELD` under CLOSURE, and terrain 3 is `FIELD` under every kind.

  Ten negative controls each make a test fail:
  - no block;
  - a block at Flying targets too, or at allies too;
  - a block without priority;
  - Protect checked before the terrain;
  - no Psychic boost;
  - no terrain replacement;
  - the end always naming Grassy Terrain;
  - a Grassy Seed that acts on any terrain;
  - Psychic Terrain out of range under TEAM_C.
- **Not recorded.** Trick Room reversing the entry order of two setters: the order is runSwitch's speed order, which the closure's battles already pin.
- **Review findings, fixed.**
  - The terrain's place before Protect and its ally exception had no battle. `c10_terrain_orders` records both, and each has a negative control.
  - A spread move with positive priority would have been checked target by target. It now fails with `E_UNSUPPORTED`; the data cannot reach it.
  - The block's detail value differs from the plan's event kind. This section now says so.
  - The `c10_terrain_war` text above was wrong.
  - Grassy Glide's priority and both terrain boosts now use `dfi_grounded`.
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (the terrain, the field value, BLOCKED's detail, version);
  - `src/state/{battle_internal.h,closure_member.h,closure_member.c,invariants.c,observation.c}`;
  - `src/combat/turn.c`;
  - `src/data/support_manifest.c`;
  - `python/duoforge/{_layout,_lib}.py`, `python/tests/{test_lib,test_policies_features}.py`;
  - `tools/layout/layout_dump.c`, `tools/reference/trace_to_c.py`, `tools/state_model/state_v3_model.py`;
  - `tests/test_conformance.c`, `tests/test_api_atomicity.c` (version), `tests/test_team_c_setup.c`.

### 10.12 Step 11: Follow Me

- **Follow Me** (`data/moves.ts:6039-6074`) has priority +2 and targets the user.
  - Its `onTry` needs two active Pokémon per side (`activePerHalf > 1`). That is a format property, so it never fails in doubles.
  - The volatile lasts one turn: `-singleturn|user|move: Follow Me`, with no `[of]`. It ends in the residual without a line.
  - Its target is the user, and Psychic Terrain skips self moves, so the terrain never stops it.
- **Redirection** (`onFoeRedirectTarget`, priority 1). getMoveTargets runs the RedirectTarget event (`sim/pokemon.ts:821-844`, `sim/battle-actions.ts:457-468`):
  - after the move line and after the retarget of a fainted foe;
  - before TryMove.

  priorityEvent stops at the first handler that returns, in compareRedirectOrder (`sim/battle.ts:413-419`), which puts the higher priority first. So Follow Me comes before Lightning Rod (priority 0).
  - The handler comes only from a standing foe of the user: `foes()` keeps hp > 0 (`sim/side.ts:390-403`), and the handlers are collected in `sim/battle.ts:1053-1063`.
  - It takes the move when `validTarget(holder, user, move.target)` holds (`sim/battle.ts:2399-2435`). In doubles that is every single-target class here except self and the ally classes. A move aimed at the user's own ally, or at a fainted ally, is redirected too.
  - Spread moves never reach the event.
  - There is no line: retargetLastMove sets the move line's target. Sucker Punch's `onTry` and Armor Tail's TryMove then see the new target.
  - Electro Shot's charge turn stores the chosen target (`lastMoveTargetLoc`), not the redirected one. Its release is redirected again.
  - Two holders on one side would need the handlers' Speed order, so the engine returns `E_UNSUPPORTED`. Only Indeedee-F learns Follow Me, and Species Clause keeps one per side.
- **Correction to the plan** (section 5, step 11).
  - "An ally-targeted move is not redirected" is wrong for the pinned reference. Follow Me takes a move aimed at the user's own ally (`c11_follow_me`, `c11_follow_me_mirror`).
  - Only Helping Hand's class (adjacentAlly) is never redirected, and it cannot meet Follow Me anyway: Helping Hand (+5) always moves first.
  - For the same reason "Fake Out into Rocky Helmet through the redirect" cannot be recorded: Fake Out (+3) always moves before Follow Me. Flip Turn and Iron Head (`c11_follow_me`) and Wave Crash (`c11_follow_me_mirror`) show Rocky Helmet through the redirect instead.
- **State.** Volatile bit 8 (`DFI_VOL_FOLLOW_ME`) is valid only under the TEAM_C kinds. It may not be set at a TURN boundary, nor at a REPLACEMENT boundary (after the residual).
  - Its end is one more duration handler in the residual list, which now holds nine entries per position.
  - The reference draws ties among duration handlers, but such a draw decides nothing, and the converter drops it (decision 0006 section 5.1). So no battle can show that entry.
  - The state model mirrors the bit; its output is unchanged.
- **Public changes, library 0.19.0** (sections 4.2 and 9.4), coordinated with the main session:
  - `DUOFORGE_POSITION_FLAG_FOLLOW_ME` (1) in the position view's `reserved` byte. It is set while the volatile lasts, so at a PIVOT boundary or at a TERMINAL one in the middle of a turn.
  - DUOFORGE_EVENT_SINGLE_TURN (38) also carries Follow Me, with `other` `DUOFORGE_NO_POSITION`.

  Python reads no event kinds. Its encoder already refuses a nonzero `reserved`.
- **The real Team C passes the setup gate.** Follow Me was its last mechanic. `duoforge_battle_create` now accepts the real Team C under TEAM_C and TEAM_C_DEV, and setup rejects no Team C mechanic any more. Step 12, the Team C gate, still has to certify the team.
- **Converter.**
  - It maps `-singleturn|...|move: Follow Me`.
  - It compares `followme` as volatile bit 64 and as the view bit.
  - The control test for an unknown `-singleturn` now uses Rage Powder.
- **Evidence.** Four recorded battles, so 51 Team C battles in all:
  - `c11_follow_me`:
    - Kingambit's Sucker Punch, aimed at Milotic, goes to an Indeedee-F that already moved, and fails.
    - Basculegion's Flip Turn goes into Indeedee-F's Rocky Helmet and pivots while the volatile is live, so the view bit shows at the PIVOT boundary.
    - Milotic's own move is not redirected.
    - Charizard's Heat Wave hits both Pokémon.
    - Kingambit's Iron Head, aimed at its own ally, goes to Indeedee-F.
  - `c11_follow_me_rod`:
    - The foe Raichu's Zap Cannon, aimed at the Lightning Rod Raichu, goes to Indeedee-F.
    - Archaludon's Electro Shot charges under Follow Me. The next turn it is released at the chosen Raichu, whose Lightning Rod takes it without an `-activate` line.
  - `c11_follow_me_mirror` (two Indeedee-F):
    - With Follow Me on both sides, each side's moves go to the other side's user.
    - Both volatiles end in one residual, at a Speed tie.
    - A Wave Crash boosted by Helping Hand is redirected.
    - Milotic's Ice Beam, aimed at a foe that fainted this turn, is retargeted to the only standing foe, the Follow Me user, with the reference's random-target draws.
    - Kingambit's Iron Head, aimed at its own ally, is redirected.
    - After the user faints, Kingambit's Iron Head reaches its target.
  - `c11_follow_me_paths`:
    - Archaludon's Electro Shot charges at Farigiraf. Its release under Follow Me goes to Indeedee-F.
    - Basculegion's Aqua Jet, aimed at its own ally, goes to Indeedee-F, where Farigiraf's Armor Tail stops it: TryMove sees the new target.
    - After Farigiraf left, the same Aqua Jet is stopped by Psychic Terrain at the grounded Indeedee-F. The terrain's ally exception is decided on the new target.
    - Archaludon's Dragon Pulse (any target), aimed at its own ally, goes to Indeedee-F. It does so also after Gholdengo's Shadow Ball knocked that ally out in the same turn, so a move aimed at a fainted ally is redirected.

  API tests:
  - the bit at a PIVOT boundary, with the view bit for both players;
  - the bit at TURN and REPLACEMENT boundaries;
  - the CLOSURE masks;
  - the gate (Follow Me, the real Team C) and the manifest.

  Seventeen negative controls each make a test fail:
  - no redirect, or no redirect of a move aimed at the user's own side, at a fainted ally, with an any target, or released after a charge;
  - Armor Tail or Psychic Terrain judged on the chosen target instead of the new one;
  - Lightning Rod over Follow Me;
  - Follow Me taking its own side's moves;
  - spread moves redirected;
  - Electro Shot storing the redirected target;
  - Follow Me outliving the residual;
  - no line, or hidden in the view;
  - no TURN or REPLACEMENT rule;
  - out of range.

  Two controls stay green, as expected:
  - a residual end that is not counted, because its tie draws decide nothing and are dropped;
  - a fainted holder that still redirects, because the faint clears the volatile first.
- **Not recorded.**
  - Helping Hand and Fake Out against Follow Me: both always move first.
  - Two holders on one side: unreachable.
  - Struggle (a random target) against Follow Me: no recorded battle runs out of PP. Struggle takes the path of the other single-target classes.
  - The view bit at a TERMINAL boundary: the conformance compare skips `reserved` there.
- **Review findings, fixed.**
  - Several claimed paths had no battle: a move aimed at a fainted ally, an any-target move, Electro Shot's redirected release, and Armor Tail and Psychic Terrain after the redirect. `c11_follow_me_paths` records them, and five more controls are red.
  - The evidence list named Darkest Lariat, which no c11 battle uses.
  - A citation and two wordings above.
  - The converter now refuses a Follow Me line with any attribute (for example `[zeffect]`), with a control test.
  - Stale comments in `src/data/support_manifest.c` and `tests/test_team_c_setup.c`.
- **Shared files touched:**
  - `include/duoforge/duoforge.h` (the view bit, SINGLE_TURN's comment, version);
  - `src/state/{battle_internal.h,closure_member.c,invariants.c,observation.c}`;
  - `src/combat/turn.c`;
  - `src/data/support_manifest.c`;
  - `python/duoforge/_lib.py`, `python/tests/test_lib.py` (version);
  - `tools/reference/{trace_to_c.py,test_trace_to_c.py}`, `tools/state_model/state_v3_model.py`;
  - `tests/reference/conformance_types.h` (a comment only), `tests/support/conformance_compare.c`;
  - `tests/test_conformance.c`, `tests/test_api_atomicity.c` (version), `tests/test_team_c_setup.c`;
  - `docs/support/README.md`.

### 10.13 Step 12: the Team C gate

- **The gate** is `duoforge.combat.team_c_gate` (`tests/test_team_c_gate.c`), modelled on the closure gate (closure step 13).
  - **Teams:** the real Team C (`docs/research/third-team/team-c.txt`) and the two reference teams of decision 0004.
  - **Profile:** TEAM_C data, the certified profile of decision 0010 (six registered, four brought).
  - **Battles:** the five pairings C-A, C-B, A-C, B-C and C-C, 1000 seeds each, from team selection to TERMINAL. The choices are random and legal: team picks, moves, Mega Evolution, switches, replacements and PIVOT answers.
  - **Checks:**
    - every step returns OK, so no `E_UNSUPPORTED` or other error is reachable with these teams;
    - every committed state passes the checker;
    - a copy decoded from the bytes of every boundary continues byte for byte like the original;
    - a replay of the recorded bundles from the setup ends in the same bytes;
    - information equivalence holds at every boundary of every fourth battle, for both viewers, with the closure gate's pairs.
  - **Coverage:**
    - every move of the three teams is used;
    - all five Mega formes appear;
    - the Team C state is reached at committed boundaries: Psychic Terrain, poison, the choice lock, Unburden, and the volatiles of Follow Me and Helping Hand.
- **Result:** no check failed (1,462,709 checks).
  - 5000 battles in 71,157 steps (longest 42), with 5000 identical replays;
  - 15,045 REPLACEMENTs, 3,198 PIVOTs and 6,326 Megas;
  - 200,666 equivalent pairs and 81,017 shown HP changes.
- **Recorded battles of the real Team C.**
  - `tools/reference/gen_real_specs.py --team-c` records 40 candidates per pairing. It keeps 4 per pairing by the coverage they add: 20 battles `c12_real_*` (generator seed 2026100212, 237 features).
  - DuoForge matches all of them. 21 of the 70 Team C battles now run under TEAM_C itself, with six registered members.
  - Without `--team-c` the generator's output is unchanged: it reproduces all 16 `m5_real_*` specs byte for byte.
- **Negative controls**, each red in the gate alone:
  - Follow Me failing at run time (a step error);
  - the codec dropping Follow Me's bit (the decoded copy diverges);
  - no Unburden volatile (the Team C coverage);
  - the RNG's lowest bit in the view (an information leak).

  A first version of the last control used the RNG's second bit. It stayed green, because the gate's RNG pair flips only some bits of the state. The pairs are the closure gate's own.
- **Not part of the gate.** The M5 certification dataset (`certify/`) stays the closure's. A Team C certification is a later decision for the owner.
- **Shared files touched:**
  - `tools/reference/gen_real_specs.py`;
  - `tests/CMakeLists.txt`;
  - `tests/test_conformance.c` (the battle counts);
  - `docs/support/README.md`.
