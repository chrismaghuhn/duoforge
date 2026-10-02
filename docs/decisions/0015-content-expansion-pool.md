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
   - A spec with `"data": "pool"` is converted with the pool tables into `tests/reference/conformance_pool.h` and runs under POOL alone (no DEV fallback, so the records name the data kind). The records writer, the diff runner and the replay driver carry that third kind; random play over POOL teams (`diff_random.py`) is a separate step, as it needs team files that carry the new members (step G5 did it: `DATA_KINDS` of the driver has `pool`, a team with an id beyond Team C's is pool data, and `duoforge.reference.diff_pool_smoke` plays one that carries U-turn).
3. **P3, abilities:** "-ate" and pinch become table rules, Pixilate, Refrigerate, Overgrow, Torrent and Swarm are marked, with recorded battles.
   - Only Overgrow on Rillaboom is reachable through the setup rules now (a pool forme with Pixilate, Refrigerate, Torrent or Swarm comes with the content steps), so the recorded battle is Overgrow in pinch range; Aerilate (Normal move from Mega Salamence) is already recorded. The others are covered by a unit test of the dispatch over every ability and type and by the Node cross-check of their pinned handlers against the family columns.
4. **P4:** weather setters and surges become table rules over the prefix members. There is no behaviour change, which the conformance tests show.
   - Done: `dfi_has_entry` and `dfi_entry_ability` read the weather and terrain columns through `src/combat/ability_family.h`; Intimidate is no family and stays named. The Primal exception of the pinned weather handlers (Kyogre with Blue Orb, Groudon with Red Orb) is checked by the cross-check; no Primal forme is in the pool.
5. **G2, the rows of the 17 target teams** (`docs/research/expansion/team-gaps.md`, `data/team_gaps.json` `pool_rows`): every row they need, added at once and unmarked, so that the pool table content is fixed for the rest of the track: the formes Pelipper, Arcanine-Hisui, Annihilape, Floette-Eternal and Floette-Mega, 22 moves, the items Focus Sash, Expert Belt and Floettite and the abilities Rock Head, Flower Veil and Fairy Aura, with their learnable moves and legal abilities. No new column: a move whose callback or field no column models is mapped to a named handler id in its special column (decision 0009 section 3.3), which the turn code refuses; a step that needs a column changes the tables and the POOL fingerprint and says so. A move is marked by the step that records a reference battle with it under the POOL kind: G2 marks twelve (the data-only ones, in four battles `g2_data_moves_a` to `_d`), not U-turn and not the nine handler moves. **G5 marks U-turn** (`team-gaps.md`): the switch flag of a damaging pivot is the move's own (`dfi_pivot_moves`, one value per move, valid under the POOL kinds for U-turn: `switch_flag_max` is `DFI_SWITCH_UTURN` there and `DFI_SWITCH_FLIP_TURN` under the TEAM_C kinds), so the switch event names the move that pivots (`[from] U-turn`, `[from] Flip Turn`); a self-switch move without a flag is refused at the move (`E_UNSUPPORTED`). Evidence: `g5_uturn_a` to `_e` under the POOL kind (a knock-out, Protect, an empty bench, Emergency Exit in the same action, a Rocky Helmet that faints the user); the Flip Turn battles are unchanged.
5a. **G8, Throat Chop and Psychic Noise** (the first mechanics on the tail; decision 0015 section 7). Both leave the handler list: each is a **secondary kind** of the generic secondary column, plus one new column. The new column is `dfi_pool_move_flags2[]` (a byte per pool move: bit 1 the pinned `sound` flag, bit 2 the `heal` flag), added as the last part of the canonical pool bytes of the whole-pool layout (section 4.2: after the legal moves and abilities of the formes), so the POOL fingerprints change (KP f82c6cfc..., KPD 65d23ec1... on the whole-pool tables); the generator reads exactly the secondary text of each (`secondary: {chance: 100, onHit(target) {target.addVolatile('throatchop')}}`, and Psychic Noise's `volatileStatus: 'healblock'` secondary) and the condition facts it relies on (duration 2, Heal Block's `durationCallback` 2 for Psychic Noise, silent Throat Chop start and end) and fails on any other text. Throat Chop: `-start`/`-end` are silent, so no event; the sound moves are disabled in the request for two turns (counter 2 on the hit, one counted down by the residual of that turn, so the next request has them barred and the one after has them back); a barred move that was queued is `cant|X|move: Throat Chop` with no PP spent. Heal Block (Psychic Noise, 2 turns): `-start`/`-end|move: Heal Block` are shown (new events `VOLATILE_START`/`VOLATILE_END`, the cause `HEAL_BLOCK` for `cant|X|move: Heal Block|<move>`), every heal of the holder is refused (onTryHeal: `data/moves.ts` healblock; Leftovers and Grassy Terrain's residual heal and Sitrus Berry through the same onTryEatItem, which is why the berry is not eaten, `data/items.ts` sitrusberry, `sim/pokemon.ts` eatItem) and the moves with the heal flag are disabled in the request (Bitter Blade, Leech Life in the pool; Recover stays unmarked). The counters live in the POOL tail; a switch, a faint or a replacement clears the position's five tail fields and the occupant's Soak type (`dfi_tail_clear_occupant`). The Heal Block end is a duration handler of order 20 and Throat Chop's of order 22 (before the side conditions at 26): two blocks that end in one residual come in the speed order of their holders, and at equal Speed (a self-play mirror) the reference shuffles the pair (one `SPEED_TIE` draw, `random(start, start + 2)`) and the two `-end` lines show the outcome, so the converter KEEPS that tie as an entry that states which line is first (`heal_block_end_tie`, like `side_end_tie`; the precondition is that two of the holders end in the step, checked against the step's log, and a draw that contradicts the lines is an error) and the engine draws the `SPEED_TIE` after the callbacks of the sort and orders the pair by it. The drop rule for duration ties stays for ties without two visible lines (a tie of which fewer than two end), and `drop_reason` needs the log to apply it. Three or four equal-Speed holders ending together need the longer shuffle: `E_UNSUPPORTED` in the engine, `heal-block-tie-size` in the converter. A side-condition end tie in the same step as a Heal Block tie draws in the engine's order (side first), the reference's is Heal Block (20) first: a tape mismatch, never a silent difference. `dfi_pool_move_flags2` is the general second flags byte of the pool moves: bit 1 `sound`, bit 2 `heal`, bits 4 to 128 free for the next consumers (a step that reads another pinned flag adds its bit and the generator's name for it); Heal Block refuses every heal-flag move through bit 2 alone, so a later heal move (Recover) is blocked without more code. Correction to the research note: the Sitrus Berry is not eaten under Heal Block (it was assumed eaten). Marked: Throat Chop and Psychic Noise, by `g8_throat_chop`, `g8_heal_block`, `g8_heal_block_pair` (two blocks of different Speed) and `g8_heal_block_tie_a` and `_b` (equal Speed, the two orders of the shuffle); the request domain was also checked against Showdown with the random-play domain check over the teams of the two specs under POOL. View extension (decision 0018, tier 0 is on main): G8 fills `duoforge_position_ext.volatiles` bits `HEAL_BLOCK` and `THROAT_CHOP` (both public, for both viewers; presence of the tail counters, never the counters) and sets the supported bits 16 and 6; `duoforge.state.pool_g8` compares both viewers' whole extension with the protocol's after every step of the five G8 battles (rows derived from the `-start`/`-end`/OUT lines by `tools/reference/test_trace_to_c.py`, section 6.1 of 0018). New public constants (owner's OK needed): `DUOFORGE_EVENT_VOLATILE_START` 39, `DUOFORGE_EVENT_VOLATILE_END` 40, `DUOFORGE_CAUSE_HEAL_BLOCK` 15, `DUOFORGE_VOLATILE_HEAL_BLOCK` 1; no view field.
6. **G3, the POOL state tail** (section 7): the container for the state of G7 to G11, under the POOL kinds only, as its own schema (0x0103). No mechanic and no public field; the CLOSURE and TEAM_C states are byte for byte unchanged.

7. **The whole legal pool as rows** (roadmap M11: learning from all Showdown replays; owner request of 2026-10-02): DuoForge must **encode** every team of the format, not simulate it, so a row for every forme, move, item and ability of the legal pool is added to the POOL tables (section 4.2). Every new row is unmarked; nothing about the engine changes.

### 4.1 Data query API (names and legality)


One query API answers what a caller needs to build a setup that a context accepts (`duoforge_data_count`, `_name`, `_find`, `_supported`, `_forme_info`, `_forme_moves`; public header, section "data query").

- **Same rule, one implementation.** The legality of a move or ability for a forme, the legal genders, the Mega forme and its stone, and the support gate by id are functions of `closure_member.c`. Setup, the member invariant and the API all call them; the API holds no copy of a rule.
- **Names.** `gen_closure.py --pool` writes the Showdown id (toID) of every forme (the Mega formes included), move, item, ability and nature into `pool_tables.c` in the same run as the tables, as designated initializers, so a name cannot drift from its id. They are in no canonical bytes, table hash or fingerprint. A kind reads its prefix; an id at or beyond the kind's count is `E_INVALID_ARGUMENT` for every call, so a POOL move under TEAM_C is refused.
- **Ids.** An id is the table row. A member's ability and item fields are 1 + the id (0 is none), as at setup.
- **Struggle.** It is a row of the move table. `find` returns it, no forme lists it (so it is legal for no member), and the manifest leaves it unmarked, so `duoforge_data_supported` says false for it.
- **Support.** `supported` is the gate of `duoforge_battle_create` by id: the manifest mark, and nothing while the turn core is not marked. A member is supported exactly when its ability, item and moves are and, if it holds its forme's stone, Mega Evolution into the Mega forme is (`mega_supported` of the forme info). A test checks that composition against the white-box gate over random manifests.
- **Evidence.** `duoforge.data.api` builds random members and sides, seeded, only from what the API reports under all six combat kinds, and requires setup to accept them (or to return `E_UNSUPPORTED` exactly when the API says so); mutations to something the API excludes, and an exhaustive sweep of formes against move, ability, gender, item, nature and species ids, must be `E_INVALID_ARGUMENT`. The names are checked against the headers' macros and `trace_to_c.key` (`duoforge.data.pool_names`) and against the pinned dex (`duoforge.data.pool_families`).

### 4.2 The whole legal pool (step 7)

Section 8 rejected generating the whole pool once, because the row format had to grow first and 510 moves would have been encoded before any was tested. The owner now asks for it, with a rule that keeps the first objection: a row is only data, and a row the tables do not fully model says so.

- **Rows.** Every legal forme (264 rows for the 293 selectable formes, the 29 cosmetic copies being **name aliases** in `dfi_pool_forme_aliases`, plus the 82 Mega formes), move (510 and Struggle), item (166) and ability (215) of `docs/research/expansion/data/legal_pool.json`, re-validated at the pin, after the rows of P1 and G2. The closure, Team C and G2 rows are unchanged (the prefix test compares the closure and Team C rows with the extended tables and pins the hash of the closure-layout bytes of the 28 formes, 72 moves, 52 items and 29 abilities of the steps).
- **UNMODELED.** A row that has any callback, any field, target class or flag that the tables do not model gets the handler `UNMODELED` (the special column of a move, a handler column for items and abilities) and the list of those features, as a generated comment and as data (`dfi_pool_*_unmodeled`). The generator still fails for what it cannot read (a type, category, target class, PP or flag it does not know; a value that does not fit its byte). The rules are in `tools/datagen/README.md`.
- **Never marked.** Every new row is unmarked, modelled or not. A test fails for a marked row with the UNMODELED handler or a feature list (`duoforge.data.pool_tables`); a step that implements a row makes it modelled in the generator first (a handler id of its own for a move, `ENGINE_ROWS` for an item or ability, `ENGINE_PIVOT_MOVES` for a pivot), then marks it with its recorded battles.
- **Flags.** The move flags byte is not widened. A flag that no bit holds matters only when a modelled row reads it, and then the move rows that carry it are UNMODELED with the flag in their list.
- **Formes.** Types, base stats, abilities and legal abilities, the Champions learnsets (as P1b), the gender rule and the Mega links (stone, Mega forme, Mega ability). A base forme links the first Mega forme of its stones; the second Mega forme of Absol, Charizard, Garchomp, Lucario and Raichu is a row of its own that the engine cannot reach (the data query API says it is unsupported).
- **Widths.** The pool has 346 formes and 511 moves, more than a u8 holds, so the **pool rows have their own types with u16 forme links** (the closure and extended rows and their bytes are unchanged) and the pool canonical bytes are a new layout, so the POOL fingerprint changes (it is expected to change with every pool row change). Ids are u16 in the state, the observation and the events (a member's species and each move slot), an item or ability is 1 + the id in a byte (an id is at most 254); the generator reads these widths from the sources and `closure_member.c` asserts them at build time.
- **Names and the data API.** The names are generated as for every other row (section 4.1) and the API answers for all rows; aliases are data (`dfi_pool_forme_aliases`) and **not** yet reachable through `duoforge_data_find`, whose contract names exactly the names `duoforge_data_name` writes. The differential test of the API (`duoforge.data.api`) runs over the whole pool: every row of every table is in a setup that the oracle written from the API's answers judges, and setup returns `E_UNSUPPORTED` exactly when the API says so.
- **Evidence.** `duoforge.data.pool_tables` (counts, prefix, hashes, layout, handler columns, no marked half-modelled row), `duoforge.data.pool_rows` (the tables against the validator's output, no checkout), `duoforge.data.gen_closure_refusals`, `duoforge.data.pool_families` (the pinned entries and the validator, 191 thousand probes), `duoforge.data.api`, `duoforge.state.pool_setup`. No battle changes: every conformance header and the tiebreak fixture are byte for byte as before.

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

## 7. The POOL state tail (step G3)

The owner decided (2026-10-02): the pool mechanics of steps G7 to G11 (Wide Guard, Throat Chop and Heal Block, Encore, Soak) need state that the schema-3 layout has no room for. They get a **POOL-only tail**, not schema 4.

- **Registry.** The state artifact (kind BATTLE_STATE, semantics 3) now has two schemas, told apart by the envelope's `schema_version` (u16; the low byte is the layout of the body, the high byte the revision of the tail):

  | Schema | Name | Size | Carried by |
  |---|---|---|---|
  | 3 (0x0003) | v3 | 1009 | CLOSURE, CLOSURE_DEV, TEAM_C, TEAM_C_DEV, SYNTHETIC: unchanged, byte for byte |
  | 0x0103 | v3 + pool tail rev 1 | 1051 | POOL, POOL_DEV |
  | 4 | (reserved) | - | the certified pool teams, see below |

  The context artifact and the semantics id are unchanged, so no fingerprint changes (the POOL fingerprint does not depend on the state layout). The schema is a function of the context's kind: a POOL context decodes only 0x0103 and every other kind only 3.
- **Layout.** The 1009 bytes of schema 3, then 42 bytes (`src/codec/state_codec.h` has the offsets and static asserts; `tools/state_model/state_v3_model.py` is the oracle, `--pool-tail`). Per side (21 bytes): `wide_guard`; two reserved bytes; per position (6 bytes): `last_move`, `encore_slot`, `encore_turns`, `throat_chop_turns`, `heal_block_turns` and one reserved byte; then `soak_type` of each of the six roster members. The reserved bytes are the reserve (8 of the 42): they are always written as zero, a decoder refuses anything else, and a later revision may give them a meaning. The size is fixed; in memory the tail is a plain struct of 34 bytes in the battle (`dfi_pool_tail`), with no padding, no pointer and no allocation.
- **Values (rev 1).** `last_move` 0 none, 1 to 4 move slot + 1, 5 Struggle; `encore_slot` 0 or 1 to 4, `encore_turns` 0 to 4, zero exactly together; `throat_chop_turns` 0 to 2; `heal_block_turns` 0 to 5; `wide_guard` 0 or 1; `soak_type` 0 or a type id + 1 (1 to 18). These are bounds from the pinned data and the research (team-gaps.md), not mechanics: nothing reads or writes the tail yet, and a step that finds a bound wrong changes the revision (0x0203) and says so.
- **Under POOL the tail is state like any other:** encode, decode, digest, `equal`, `clone`, `copy`, the invariants and the model-facing query check all carry it, and a state of 1009 bytes is not a POOL state. A tail never enters an observation, a view or an event: G3 adds no public field, size or constant (`DUOFORGE_STATE_V3_ENCODED_SIZE` stays 1009 and means schema 3; a caller sizes its buffer with `duoforge_battle_encoded_size`, which says 1051 under the POOL kinds).
- **Under the other kinds it is absent:** all zero in memory (invariant `TAIL_KIND`, so check, encode and digest return `E_INVARIANT` for a state that has one) and not in the encoding. The digests of states of those kinds are what they were (tests pin three digests of each kind taken before the tail existed).
- **Invariants** (after the side checks): the ranges above; a position without a standing occupant (empty or fainted) has no tail (`TAIL_POSITION`, with the Encore pair and the move count of the occupant); a soak type only on a member standing on the field and not Mega Evolved (`TAIL_MEMBER`); `TAIL_SIDE` for the Wide Guard flag. The decoder adds `TAIL_SCHEMA` (the artifact's schema is not the one of the context's kind: an artifact with a tail under another kind, or a POOL state without one) and `TAIL_RESERVED`; both are reported as MALFORMED with the invariant id, as every decode refusal is (decision 0002 section 6, step 9). A mechanic that writes the tail clears it where it clears the position (a switch, a faint, a Mega Evolution): the invariants catch a miss.
- **Schema 4 comes only with the certified pool teams** (roadmap "Later"): a certification of the M8 teams is when the state layout is frozen into one schema for every kind; until then the tail keeps CLOSURE and TEAM_C states and their certified evidence untouched. The tail may be revised (0x0203, and so on) until then.

## 8. Alternatives considered

- **Generate the whole legal pool once, with a fixed fingerprint.** The row format must grow first (the move flags byte is full; the family parameters are missing), and 510 moves would be encoded before any of them is tested. Rejected at the time; **done as step 7** (section 4.2, owner request of 2026-10-02) once the columns existed and with the UNMODELED rule, so that no row is encoded as if it were tested. The fingerprint still changes with every pool row change.
- **Schema 4 for every kind now** (the pool tail in every state). Every CLOSURE and TEAM_C golden, digest and certified battle would change, and the evidence of decisions 0006 to 0010 would no longer name the bytes it was recorded on. Rejected until the pool teams are certified.
- **Grow TEAM_C's extended tables.** The TEAM_C fingerprint would change with every step, and Team C's gate evidence would no longer name its data. Rejected.
