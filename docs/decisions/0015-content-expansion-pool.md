# 0015 — Content expansion: the POOL data kind, families as table rules, the fuzz corpus

Status: **accepted**. The owner decided the three open points of `docs/research/expansion/README.md` section 7 on 2026-10-02 ("ja" to the recommendations, collected by the main session). Builds on decisions 0006 (data, state v3, evidence), 0009 (Team C: the extended tables and their prefix test) and 0010 (the certified CLOSURE profile). The differential loop of `docs/research/expansion/differential-testing.md`, components 1 to 4, is on `main` (PRs #72, #74, #76, #79, #80, #85).

## 1. Owner decisions (2026-10-02)

1. **Data kind.** New kinds `POOL` (6) and `POOL_DEV` (7) for the growing tables. Closure and Team C are their exact, frozen prefix: the CLOSURE and TEAM_C fingerprints never change.
2. **Fuzz corpus.**
   - It lives in the repository: specs and gzip-compressed traces under `tests/reference/corpus/`.
   - It is curated: only battles that found a defect or covered a new path go in, never the whole fuzz output.
   - The cap is about 20 MB. Anything beyond it later moves to a release artifact.
3. **Machine.**
   - Fuzz runs go in chunks of at most 10 minutes under `tools/ci/machine_lock.sh`, with a 30 s yield between chunks.
   - For measurements fuzzing pauses completely: the driver checks a pause file before each chunk and waits while it exists.

## 2. POOL data

- **Tables.** `tools/datagen/gen_closure.py --pool` writes `src/data/pool_tables.{h,c}`:
  - the extended tables (closure, then Team C), unchanged, as the prefix;
  - then the new rows, in the order the steps add them.
- **Which tables the engine reads.** It reads the pool tables under every combat kind. The kind's counts bound every id at setup and in the invariants (CLOSURE: closure counts; TEAM_C: extended counts; POOL: pool counts). So a CLOSURE or TEAM_C battle reads only its prefix, as in decision 0009 section 3.2.
- **Family parameters.** New per-id columns:
  - for items: the family and its type;
  - for abilities: the family and its type, weather or terrain.
  - They are filled for every id, including the prefix, because the engine reads them under every kind.
  - The CLOSURE and TEAM_C canonical bytes do not include them, just as 0009 kept the poison immunity bit out of the closure bytes.
- **Prefix test** (the pattern of `duoforge.data.extended_tables`):
  - every closure and Team C row is field-equal in the pool tables;
  - the CLOSURE and TEAM_C canonical bytes, recomputed from the prefix, hash to their pinned table hashes;
  - the family parameters of the prefix ids equal what the engine hard-coded before (for example Mystic Water: type booster, Water; Chople Berry: resist berry, Fighting; Aerilate: "-ate", Flying; Blaze: pinch, Fire).
- **Deriving the parameters.**
  - The generator reads them from the pinned sources with one strict pattern per family. A handler that deviates from its family's pattern fails the generator; it never guesses.
  - A Node cross-check under `DUOFORGE_PS_REFERENCE_DIR` calls the pinned handlers with every type and must agree with the generated columns.
- **Legal moves and abilities per forme.** A forme has one set in the closure and Team C tables, but the real teams use table moves that are not in their forme's set (for example Milotic's Protect, Golisopod's Sucker Punch, Kingambit's Swords Dance) and abilities beyond the set's. So the pool tables get two more columns for every forme, in an array of their own:
  - **Learnable moves:** a bitset over the pool moves. A move is learnable when the forme lists it in the Champions learnsets at the pin (`data/mods/champions/learnsets.ts`). Every entry there is `"9M"` (no event, egg or level-up source), so learnable means listed. The generator parses the block strictly and requires the pool moves it finds to be exactly the pool moves that the pinned validator accepts for the species (`legal_pool.json`).
  - **Legal abilities:** a list over the pool abilities, in slot order. They are the forme's abilities in the pinned pokedex, filtered by what the validator allows in Champions (`abilities_legal` of `legal_pool.json`) and by the pool abilities. A Mega forme has its one ability. An ability that the pin tags as not released fails the generator explicitly (Lucario-Mega-Z's Aura Guard is the known case).
  - A Mega forme is reached in battle and never set up, so its learnable set is empty.
  - Both columns are part of the canonical pool bytes, as the family columns are, and not of the CLOSURE or TEAM_C bytes.
- **POOL fingerprint.** It is composed as today: data kind, roster sizes, species and move counts, target classes, and the hash of the canonical pool bytes, which include the family columns and the legal moves and abilities per forme.
  - It changes with every PR that changes the pool data.
  - A state or recipe of another pool version is rejected explicitly.
  - For training or a certification, a pool version is later frozen as its own named profile, as CLOSURE was.
- **Setup rules.**
  - POOL: the CLOSURE rules (decision 0006 section 2.1, and the register 6 / bring 4 freeze of 0010) over the pool tables, with mixed teams and any table item, and **one change, the set rule:**
    - a member's moves are 1 to 4 distinct pool moves that its forme learns;
    - its ability is one of its forme's legal abilities in the pool tables;
    - for a Mega-capable base forme these are the base forme's (the Mega forme is reached in battle);
    - the support gate still applies to every move, item and ability, so a legal choice that is not marked is `E_UNSUPPORTED` after all validation.
  - POOL_DEV: as the other DEV kinds, so also No Ability and 4 to 6 registered members; the same moves and abilities as POOL.
  - CLOSURE, CLOSURE_DEV, TEAM_C and TEAM_C_DEV keep the set rule (the moves and the ability of the forme's one set). Their behaviour and fingerprints are frozen.
  - The member invariant of a decoded state follows the same split: moves and ability by the set under the four frozen kinds, by the learnable moves and the legal abilities under the POOL kinds.
- **Support gate.** Every new id starts unmarked. A setup that needs an unmarked mechanic fails with `E_UNSUPPORTED` after all validation, as today. A step marks only what it tested.
- **Legality.** Only format-legal ids enter the pool: they must pass `TeamValidator` at the pin, which `docs/research/expansion/data/legal_pool.json` records.

## 3. Families as table rules

The families of the research note, section 7, with their legal members:

| Family | Members in the pool after the step | Prefix members |
|---|---|---|
| Type boosters (BasePower x4915/4096, priority 15) | all 18 | Mystic Water, Miracle Seed |
| Resist berries (ModifyDamage x0.5 on a super-effective hit; Chilan Berry: Normal, without that condition) | all 18 | Chople Berry |
| "-ate" (Normal to the type, BasePower x4915/4096 at priority 23) | Pixilate, Refrigerate | Aerilate |
| Pinch (ModifyAtk/SpA x1.5 at a third of the HP or less) | Overgrow, Torrent, Swarm | Blaze |
| Weather setters, surges | the prefix only | Drizzle, Drought, Grassy Surge, Psychic Surge |

- The engine's hard-coded checks (`turn.c`: the BasePower chain, ModifyAtk, ModifyDamage, the entry abilities) become reads of the family columns. They then hold for every member.
- New weather or terrain setters (Sand Stream, Snow Warning, Electric Surge) need new field mechanics. They follow later, ordered by usage. Galvanize and Misty Surge have no legal holder.

## 4. Steps

One PR per step.

1. **P1, data**, in two PRs:
   - **P1a:**
     - the POOL and POOL_DEV kinds and the pool tables: prefix, family columns, and the new rows of section 3, all unmarked;
     - the engine reads the pool tables;
     - prefix, fingerprint and setup tests.
     - No behaviour change: the closure and Team C conformance, the certified dataset and every digest stay byte-identical.
     - New public constants (the two kinds), so a minor version bump, agreed with the other sessions before the number is taken.
   - **P1b:**
     - the legal moves and abilities per forme (section 2) in the pool tables and their canonical bytes;
     - the set rule of the POOL kinds, in the setup and in the member invariant;
     - the CLOSURE and TEAM_C kinds stay as they are, which the conformance and fingerprint tests show.
2. **P2, items:**
   - type boosters and resist berries become table rules, and the new members are marked;
   - recorded reference battles for every variant: a booster of each kind of type the closure lacked, a resist berry with and without a KO, and Chilan Berry's Normal variant;
   - the interactions with Life Orb, Chople's ModifyDamage order, and a booster under Helping Hand.
   - A spec with `"data": "pool"` is converted with the pool tables into `tests/reference/conformance_pool.h` and runs under POOL alone (no DEV fallback, so the records name the data kind). The records writer, the diff runner and the replay driver carry that third kind; random play over POOL teams (`diff_random.py`) is a separate step, as it needs team files that carry the new members.
3. **P3, abilities:** "-ate" and pinch become table rules, Pixilate, Refrigerate, Overgrow, Torrent and Swarm are marked, with recorded battles.
   - Only Overgrow on Rillaboom is reachable through the setup rules now (a pool forme with Pixilate, Refrigerate, Torrent or Swarm comes with the content steps), so the recorded battle is Overgrow in pinch range; Aerilate (Normal move from Mega Salamence) is already recorded. The others are covered by a unit test of the dispatch over every ability and type and by the Node cross-check of their pinned handlers against the family columns.
4. **P4:** weather setters and surges become table rules over the prefix members. There is no behaviour change, which the conformance tests show.
5. **G2, the rows of the 17 target teams** (`docs/research/expansion/team-gaps.md`, `data/team_gaps.json` `pool_rows`): every row they need, added at once and unmarked, so that the pool table content is fixed for the rest of the track: the formes Pelipper, Arcanine-Hisui, Annihilape, Floette-Eternal and Floette-Mega, 22 moves, the items Focus Sash, Expert Belt and Floettite and the abilities Rock Head, Flower Veil and Fairy Aura, with their learnable moves and legal abilities. No new column: a move whose callback or field no column models is mapped to a named handler id in its special column (decision 0009 section 3.3), which the turn code refuses; a step that needs a column changes the tables and the POOL fingerprint and says so. A move is marked by the step that records a reference battle with it under the POOL kind: G2 marks twelve (the data-only ones, in four battles `g2_data_moves_a` to `_d`), not U-turn (G5) and not the nine handler moves.

## 5. Evidence for every step

- Unit tests with expectations derived from the reference, plus negative cases (the gate before marking; a POOL id under CLOSURE or TEAM_C is `E_INVALID_ARGUMENT` at setup and `E_INVARIANT` in a decoded state).
- Reference battles: spec, then `tools/reference/ps_trace.js` from the committed path, then `tools/reference/trace_to_c.py`, under the POOL kinds.
- A differential replay of all committed battles.
- A random campaign over teams that carry the new members. This needs teams beyond A, B and C: `diff_random.py` takes team files, and later the team generator (component 5).
- The full local CI.

## 6. Corpus and pause file (the differential loop, Builder A)

- **Corpus.** `tests/reference/corpus/` holds specs and `*.json.gz` traces.
  - A CTest replays them through the converter and the C runner without Node, so they run in every CI job, sanitizers included.
  - A battle is promoted when it found a defect (minimised to the shortest prefix that still shows it) or adds a protocol line, draw site or request situation that no committed battle has.
  - A test enforces the cap of about 20 MB.
- **Pause file.**
  - The path comes from `DUOFORGE_FUZZ_PAUSE`, by default `$TEMP/duoforge-fuzz.pause`.
  - `diff_random.py` checks it before each chunk and waits, with a log line, while it exists.
  - Measurements create it and remove it afterwards. `docs/TESTING_AND_BENCHMARKS.md` documents it.

## 7. Alternatives considered

- **Generate the whole legal pool once, with a fixed fingerprint.** The row format must grow first (the move flags byte is full; the family parameters are missing), and 510 moves would be encoded before any of them is tested. Rejected for now.
- **Grow TEAM_C's extended tables.** The TEAM_C fingerprint would change with every step, and Team C's gate evidence would no longer name its data. Rejected.
