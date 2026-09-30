> **UNVERIFIED RESEARCH DRAFT.** Agent-generated on 2026-09-30 (research workflow plus critic pass) against Pokémon Showdown `b2cb775b` and public sources. **Not a contract and not evidence.** Re-verify every claim against the pinned source (`docs/decisions/0004`) before relying on it. Some local paths it mentions (for example `scratchpad/...`) no longer exist.

# Critic review: "DuoForge: Pokémon Champions as the rules basis" (Showdown pin `b2cb775b`)

This review checks the report against the pinned checkout (`git -C …/scratchpad/ps rev-parse HEAD` = `b2cb775b0616115b775534eaeff50300e1fc81fc`, 2026-09-30) and against a transpiled build of the same commit (`scratchpad/cmp/psfull`, clean status, same HEAD). All citations are `path:line` at that commit.

## 1. Factual errors and corrections

| # | Report says | Correct statement | Evidence |
|---|---|---|---|
| E1 | Emergency Exit and Wimp Out "no longer clear the attacker's `switchFlag`" | Base code clears the `switchFlag` of **every active Pokémon on both sides**. The Champions versions clear none. Wimp Out has **no M-C-legal holder**. Emergency Exit is only on Golisopod, which is M-C only. | Base: `data/abilities.ts:1253-1257,5496-5500`. Champions: `data/mods/champions/abilities.ts:22-29,96-103`. Holders: Dex query (§7). |
| E2 | "12 items are M-C only" | **18 items** are M-C only: 12 ordinary items (Eject Button, Leek, Air Balloon, Binding Band, Electric/Grassy/Misty/Psychic Seed, Normal Gem, Red Card, Rocky Helmet, Terrain Extender) and 6 Mega Stones (Absolite Z, Baxcalibrite, Garchompite Z, Golisopite, Lucarionite Z, Salamencite). | Dex query at the pin |
| E3 | Pool size: M-C 349 legal entries, M-B 314, "4 other battle-only formes" | The report's script counted only keys in the mod's `formats-data.ts`. The loaded Dex (`!isNonstandard && tier!=='Illegal'`) has **382** entries for M-C and **347** for M-B. The 33 extra entries inherit their legality: 19 Vivillon patterns, 7 Alcremie, Meowstic-F, Mimikyu-Busted, Morpeko-Hangry, Palafin-Hero, Maushold-Four, Polteageist-Antique and Sinistcha-Masterpiece. There are **7** non-Mega battle-only formes, not 4: Castform ×3, Aegislash-Blade, Mimikyu-Busted, Morpeko-Hangry and Palafin-Hero. Mega counts (82/76) and dex-number counts (231/208) are correct. | Dex query. Script: `scratchpad/synthv/megacount.mjs` |
| E4 | "default max 6 (`sim/dex-formats.ts:285`)" | Line 285 is `minTeamSize`. The max-6 default is at **`sim/dex-formats.ts:286`**. | Read |
| E5 | "The engine defaults to `set.level \|\| 100`" | The engine uses `clampIntRange(set.adjustLevel \|\| set.level \|\| 100, 1, 9999)`. Nothing in `sim/` sets `adjustLevel`. The Champions stat formula ignores level (`champions/scripts.ts:24-27`), but damage still uses it. A non-50 level therefore changes damage without changing stats. | `sim/pokemon.ts:337`; `grep adjustLevel sim/` |
| E6 | The Revival Blessing boundary is at `sim/battle.ts:2881-2889` | Those lines only cover the case where no switch-in target exists. Choosing the fainted member happens at `sim/side.ts:958-980`. Execution is at `sim/battle.ts:2781-2797`, and the request flag is at `sim/pokemon.ts:1183`. | Read |
| E7 | In M-B, Slash is "learned by 35 species" | This depends on how you count. Counting M-B-legal species entries whose own learnset contains Slash gives **28** (36 in M-C). Megas share the base forme's learnset. | Dex query |
| E8 | Trick Room row: "no 13-bit truncation" (only in the Trick Room context) | Base code applies `trunc(speed,13)` **always** (`sim/pokemon.ts:648`). The Champions override removes it outside Trick Room as well. | `champions/scripts.ts:46-54` vs `sim/pokemon.ts:641-649` |
| E9 | "Natural Cure always cures silently" | Base code also tags the line `[silent]`, but only emits it when `showCure` is set. It uses `onCheckShow`, which can emit only a count `-message` in doubles. Champions removes `onCheckShow` and always emits `-curestatus …\|[silent]`, so each individual cure becomes visible. | Base `data/abilities.ts:2812-2887`; `champions/abilities.ts:49-58` |
| E10 | Duplicate and out-of-range team picks at `side.ts:1060-1068` | The lines are `sim/side.ts:1061-1071`. | Read |
| E11 | Header: "`git status` is clean" | At 19:25 UTC, `git status` shows `M include/duoforge/duoforge.h` and `?? tools/state_model/`, with mtimes 19:22–19:24 UTC. HEAD is `2258167`. Who made these changes is not established here. This critic wrote nothing in the repo. | `git status`, `stat` |
| E12 | §4.6 / §6.3 Q9 treat PCG32 as "proposed" and the RNG choice as open | Since 19:20 UTC, HEAD contains `docs/decisions/0001-rng-pcg32-contract.md` (status: proposed; implemented and tested in M1). It **rejects the Showdown PRNG**, claims no seed or trace parity, and defers a test tape and draw-site wrappers to M3. | `docs/decisions/0001-rng-pcg32-contract.md` |

## 2. Overrides and rules the report omits

1. **Six unlocked "Future" abilities, each on exactly one M-C Mega.** All are implemented in base code and reachable only in Champions (`champions/abilities.ts:14-21,30-33,45-48,59-62,82-85`):
   - Dragonize: Feraligatr-Mega (`data/abilities.ts:1036-1057`).
   - Eelevate: Eelektross-Mega (`data/abilities.ts:1147-1160`; `sim/pokemon.ts:2156,2259-2260`).
   - Fire Mane: Pyroar-Mega (`:1295-1315`).
   - Mega Sol: Meganium-Mega (`:2558-2570`; `sim/pokemon.ts:2193-2197`).
   - Piercing Drill: Excadrill-Mega (`:3282-3295`).
   - Spicy Spray: Scovillain-Mega (`:4466-4475`).
2. **Aura Guard is reachable even though it is still `Future` (not unlocked).** Lucario with Lucarionite Z validates in `gen9championsvgc2026regmc` and becomes Lucario-Mega-Z with ability `auraguard` (executed, §7). The base code is at `data/abilities.ts:310-319` and carries `// TODO check breakable` at `:315`. An ability's `isNonstandard` status does not block gaining it through Mega Evolution.
3. **Parental Bond `-hitcount` suppression.** Champions omits `-hitcount` when only the first hit landed (`champions/scripts.ts:547-548` vs `sim/battle-actions.ts:977`). Kangaskhan-Mega is legal. This changes the protocol and what the model sees.
4. **Move overrides left out, all on moves that are Past or Future in M-C (unreachable):**
   - Base power: Anchor Shot 90, Bolt Beak 80, Fishious Rend 80, Gear Grind 60 with 90% accuracy, Astral Barrage 110, Blood Moon 130, Dragon Hammer 100, Hyper Drill 120, Revelation Dance 100, Triple Dive 35.
   - PP: Nihil Light, Obstruct and Purify → 5; Shell Trap and Spin Out → 10.
   - Flags: Metal Claw gains slicing.

   Source: `champions/moves.ts:14-17,30-34,72-76,81-84,280-284,395-398,447-451,520-524,630-634,693-704,789-792,809-813,879-882,944-948,1075-1079`.

   In total there are 66 move entries with non-legality content, 50 of them on M-C-legal moves. Rage Fist's entry (`:793-796`) is only a comment.
5. **The PP cap (`init`, `champions/scripts.ts:3-9`) affects 34 M-C-legal moves** (base PP > 20).
6. **Items.** Leek is the only ordinary item unlocked relative to base. Totals: 85 ordinary + 81 Mega Stones = 166. Choice Band, Choice Specs, Assault Vest and Booster Energy are not legal.
7. **Team preview also reveals gender, level and shiny** through `details` (`sim/pokemon.ts:536-541`). Champions no longer masks Gourgeist sizes. Base masked them (`data/rulesets.ts:648-651`), and Gourgeist-Small, -Large and -Super are all M-C-legal.
8. **Gender is drawn from the RNG at construction** when `set.gender` is empty (`sim/pokemon.ts:340`). With `Obtainable` (which includes Obtainable Misc, `data/rulesets.ts:170`), the validator does not fill in `'N'` (`sim/team-validator.ts:1140-1142`). This matters for trace fixtures.
9. **Mega is not offered while a Pokémon is locked into a move** (`sim/pokemon.ts:1137-1138`).
10. **Champions Flat Rules differ from base Flat Rules.** Champions uses `Adjust Level = 50` (levels are raised as well as lowered) plus `Min Team Size = 6`, and has no Greninja-Bond ban. Base uses `Adjust Level Down = 50` and bans Greninja-Bond (`champions/rulesets.ts:31-32` vs `data/rulesets.ts:41-42`).
11. **The Bo1 format only offers open team sheets as a UI button.** The sim emits an `uhtml` button (`data/rulesets.ts:1990-1995`). The actual reveal happens only through the stream command `>show-openteamsheets` (`sim/battle-stream.ts:209-210`) or the Bo3 format's `Force Open Team Sheets` (`config/formats.ts:295-299`; `data/rulesets.ts:2012-2014`).
12. **In PS, M-B shares all Champions behaviour code** (`championsregmb/scripts.ts:2`). It overrides only formats-data, item legality, the Archaludon learnset and two PP values. PS M-B is therefore not an archived M-B mechanics snapshot.
13. **Official 1.2.0 also removes Metal Burst and Mirror Coat from Archaludon.** PS models exactly that. M-B has both (`championsregmb/learnsets.ts:30,33`). The M-C learnset adds Slash and drops both.
14. **Sheer Force still suppresses Emergency Exit** (`champions/scripts.ts:578`), which is asymmetric with the unsuppressed AfterMoveSecondary.
15. **Reachability in M-C:**
    - Anger Shell and Wimp Out: no legal holder.
    - Run Away (Thievul), Milk Drink (Gogoat), Double Shock (Pawmot), Emergency Exit (Golisopod), Eject Button: M-C only.
    - Unseen Fist: Golurk-Mega only.
    - Rage Fist: Annihilape. Gigaton Hammer: Tinkaton. Revival Blessing: Pawmot.
    - Power Shift is unlocked but has no legal learner.

## 3. Overclaims

- **O1.** The unqualified claim "`git status` is clean" (E11).
- **O2.** "About 10 abilities and items" and a §2 delta table presented as complete, while it misses items 1–3 of §2.
- **O3.** "349 legal species entries" marked ✔ as verified, although the counting method undercounts (E3).
- **O4.** "Bench order is semantically observable … therefore all ordered 4-tuples." Bench order is observable only through Illusion (Zoroark or Zoroark-Hisui). Without Illusion there are 180 semantically distinct picks (6P2 × C(4,2)). The 360-tuple domain is a safe superset but not strictly required.
- **O5.** The recommended oracle `gen9championsvgc2026regmc` cannot exercise the proposed forced team sheets (§2 item 11).
- **O6.** "Emergency Exit/Wimp Out … switches both sides." Wimp Out is unreachable.
- **O7.** "Gigaton Hammer is reachable" as evidence for the Disable change. The change skips only the before-move cancellation (`champions/moves.ts:232-237`). Selection-time disabling is unchanged, so the change is reachable only in narrow cases.
- **O8.** "M-C-era fixes landed about 3 weeks before the pin." This cannot be verified from the depth-1 pinned clone (`git log` shows only the pin commit). It comes from the sweep.
- **O9.** Treating the RNG decision as open (E12).

---

# DuoForge: Pokémon Champions as the rules basis (Showdown pin `b2cb775b`), critic-corrected

Prepared 2026-09-30 and critic-revised the same day. This is a proposal for the owner and engineers; every choice is the owner's decision.

**Repo state.** The critic made no writes in `/home/user/duoforge`. At 19:25 UTC, `git status` shows `M include/duoforge/duoforge.h` and `?? tools/state_model/` (mtimes 19:22–19:24 UTC, origin not established). HEAD is `2258167` ("rng: pinned PCG32 contract…").

Citations are `path:line` at `b2cb775b0616115b775534eaeff50300e1fc81fc`.

**Labels:**
- **[PS]**: what Showdown implements.
- **[OFF]**: official source.
- **[UNOFF]**: community source.
- **[UNK]**: open or uncertain.
- **✔**: re-checked at the pin by reading or executing, in the synthesis or the critic pass (see §7).

## 0. Summary

**Recommended regulation (owner decides): Reg M-C.** Showdown mod `champions`, format `gen9championsvgc2026regmc`.
- **[OFF]** Ver. 1.2.0 (2026-09-08) "Pokémon and held items have been added for Regulation Set M-C" ✔.
- **[OFF]** The M-C window of 2026-09-08 to 2026-12-01 comes from pokemon.com via the sweep. It was not re-fetched (NOT_RUN).
- **[PS]** M-B is hidden with `searchShow:false` (`config/formats.ts:300-314` ✔).
- **[PS]** PS M-B inherits all Champions behaviour code (`championsregmb/scripts.ts:2` ✔).

**The Champions mod is a bounded delta on gen9 base (✔):**
- **Formulas:** stat formula (Stat Points; level-independent); PP formula plus a cap of 20.
- **Status:** paralysis, sleep and freeze.
- **Ordering:** Trick Room ordering (no underflow, no 13-bit truncation); Encore re-queueing.
- **Formes:** Megas do not revert on faint; ability-driven `-formechange` lacks `[from]`.
- **Engine hooks:** after-hit hooks run when the user has fainted; Sheer Force no longer suppresses AfterMoveSecondary; Parental Bond `-hitcount` suppression.
- **Abilities:** 9 behaviour overrides, of which Wimp Out and Anger Shell are unreachable in M-C. 6 unlocked Future abilities, each on one M-C Mega.
- **Items:** 1 behaviour override (Eject Button).
- **Moves:** 66 move entries with non-legality content, 50 of them on M-C-legal moves.
- **Information:** HP display, team-preview masking and open-team-sheet content.
- **Damage formula:** numerically unchanged ✔.
- **Also reachable:** Aura Guard, which is still `Future`, through Lucario-Mega-Z ✔ (executed).

**Side-wide resource: only Mega Evolution.** At most one per side per battle. Tera, Dynamax and Z-Moves are absent. Z-crystals are blocked only by item legality (35 Z-crystals, all `Past`), so the DuoForge setup gate must reject them.

**M1 needs almost nothing Champions-specific:**
- no Tera, Dynamax or Z state;
- signed action-speed keys;
- the pinned arithmetic helper semantics;
- an ordered brought-four mapping;
- no invariant saying a fainted Pokémon reverts from its Mega forme.

**Showdown's reference tests are thin.** `test/sim/champions.js` covers only Curse (21 cases ✔).

## 1. Profile identifiers and exact parameters

### 1.1 M-B vs M-C

| | Reg M-B | Reg M-C |
|---|---|---|
| **[OFF]** Validity window | 2026-06-16 7:00 pm PDT to 2026-09-01 6:59 pm PDT (pokemon.com, via sweep; NOT_RUN) | 2026-09-08 7:00 pm PDT to 2026-12-01 5:59 pm PST (pokemon.com, via sweep; re-fetch blocked, NOT_RUN) |
| **[OFF]** Game patch | Ver. 1.1.0 (2026-06-16): "Pokémon and held items added for Regulation Set M-B" ✔ | Ver. 1.2.0 (2026-09-08): M-C Pokémon and items. Also: Politoed loses Pound; Archaludon loses Mirror Coat and Metal Burst; "Slash can now be used"; Wish and Strength Sap 12→8 ✔ |
| **[UNOFF]** | Victory Road: M-B extended to 2026-09-09 and used at Worlds 2026 (not verified) | — |
| **[PS]** Format | `[Gen 9 Champions] VGC 2026 Reg M-B` (+ Bo3), mod `championsregmb`, `searchShow:false` (`config/formats.ts:300-314` ✔) | `[Gen 9 Champions] VGC 2026 Reg M-C` (`:287-293`) and `… (Bo3)` (`:294-299`), mod `champions` ✔ |
| **[PS]** Mod chain | `championsregmb` → `champions` → base gen9 (`championsregmb/scripts.ts:2`; `sim/dex.ts:44,693,773` ✔) | `champions` → base gen9 |

**Recommendation (owner's decision): M-C.** It is newer and is the only regulation Showdown keeps on the ladder.

Its M-C-only content makes several Champions behaviour overrides reachable that are unreachable in PS M-B:
- Eject Button (behaviour; item `Past` in M-B);
- Run Away (Thievul);
- Milk Drink (Gogoat);
- Double Shock (Pawmot);
- Emergency Exit (Golisopod).

The community dates these changes to around 2026-09-09 [UNOFF, not verified].

Per ARCHITECTURE §1, never infer "the current regulation". Name M-C and the pin explicitly. After 2026-12-01 the profile stays M-C at `b2cb775b` unless it is re-pinned.

### 1.2 Proposed identifiers (the five axes in ARCHITECTURE §1)

| Axis | Proposed identifier | Content |
|---|---|---|
| Mechanics semantics | `mech:ps-b2cb775b:champions` | Mod `champions` at the pin: gen9 base plus the §2 overrides, including base code reachable only through Champions Megas |
| Format legality | `fmt:champions-vgc2026-regmc:ps-b2cb775b` | §1.3 parameters, with DuoForge deviations marked |
| Information policy | `info:champions-ots-forced:v0` | Sheets forced at preview; floor-percent HP with 20%/50% flags (§3.5) |
| Operational limits | `ops:v0` | Logical turn and wall budget. Hitting it is a truncation, not an in-game draw. Showdown's turn-1000 tie is not adopted. |
| Coverage certificate | none yet | Created after team selection (pre-M3) |

Label the result "research profile modelled on Showdown Champions M-C; not a claim of official VGC compliance".

### 1.3 Exact parameters

| Parameter | [PS] M-C | [OFF] | Proposed |
|---|---|---|---|
| Game type | doubles (`config/formats.ts:290` ✔) | doubles (handbook §4.1, `vgchandbook.txt:312-317` ✔) | doubles |
| Registered team size | Exactly 6: `Min Team Size = 6` (`champions/rulesets.ts:31` ✔) and default max 6 (`sim/dex-formats.ts:286` ✔) | "between four and six … depending on the tournament format" (`vgchandbook.txt:115` ✔) | **Owner decision.** The state carries a count. |
| Brought / leads | 4, ordered, first two lead (`sim/dex-formats.ts:336-341`; `sim/side.ts:1031-1095` ✔). PS trims over-long lists (`:1051`) and fills in partial ones (`:1052-1058`). Unpicked Pokémon are dropped from `side.pokemon` (`sim/battle.ts:2750-2756` ✔). | Select 4; the order determines leads (`vgchandbook.txt:313-315` ✔) | 4, with an explicit full order and no fill-in |
| Level | 50 via `Adjust Level = 50`, which raises and lowers levels (Champions Flat Rules; base uses `Adjust Level Down`, `data/rulesets.ts:41`). Enforced only by the validator (`sim/team-validator.ts:611-617,1143` ✔). The engine uses `clamp(set.adjustLevel \|\| set.level \|\| 100, 1, 9999)` (`sim/pokemon.ts:337` ✔). Stats ignore level, but damage uses it. | "above and below Lv. 50 … auto-leveled to Lv. 50" (`vgchandbook.txt:145` ✔) | 50 as a profile constant. The setup gate rejects or normalizes (owner decides). |
| Stat Points | ≤32 per stat, ≤66 total (`team-validator.ts:1313-1318,1357-1363`; `dex-formats.ts:348-350` ✔) | Not in the handbook. Official spreads fit 66/32 (pokemon.com via sweep, not verified). | Same as PS |
| IVs | All 31 required (`team-validator.ts:1155,1165-1168` ✔) | Not stated | Fixed; the formula has no IV term |
| Stat formula | HP = B + SP + 75; others = B + SP + 20, then nature `tr(tr(x·110,16)/100)` or ×90 (`champions/scripts.ts:23-39` ✔) | [UNOFF] formula matches | Same as PS |
| Clauses | Obtainable, Team Preview, Species Clause (dex number), Nickname Clause, Item Clause = 1, Adjust Level = 50, Picked Team Size = Auto, Min Team Size = 6, Cancel Mod; bans Mythical and Restricted Legendary (`champions/rulesets.ts:31-32` ✔). No Greninja-Bond ban, but Battle-Bond Greninja is rejected as Greninja-Bond `Past` (`champions/formats-data.ts:3290-3292`; validator executed ✔). | One per dex number (`vgchandbook.txt:136`); unique items; Battle Bond banned (`:144`); nickname rules (§2.3.1) ✔ | Species and Item Clause in the setup gate; nicknames out of scope |
| Absent rules | No Sleep Clause Mod, OHKO/Evasion clauses, Endless Battle Clause or HP Percentage Mod. The turn-1000 tie applies anyway (`sim/battle.ts:1836-1843` ✔). | — | Turn cap is operational only |
| Mega | Yes, one per side per battle (`sim/side.ts:780-781`; `sim/battle-actions.ts:1904-1912` ✔). Not offered while locked (`sim/pokemon.ts:1137-1138` ✔). | Mega Evolution exists in-game (Ver. 1.0.3 notes mention a "MEGA EVOLVE" menu bug ✔). No official once-per-battle statement found. | Yes |
| Tera | `canTerastallize` returns null (`champions/scripts.ts:179-181` ✔). The validator deletes `teraType` (`team-validator.ts:713-726` ✔). Side request omits it (`sim/pokemon.ts:1185-1188` ✔). | Not mentioned | Reject `teraType` in specs |
| Dynamax / Z | Dynamax gen 8 only (`sim/side.ts:311-312` ✔). `canZMove` is not gated by gen (`sim/battle-actions.ts:1450-1481`; `sim/pokemon.ts:1142` ✔). Z-crystals are only `Past`. | — | Reject Z-crystals at setup |
| PP | Base PP capped at 20; max PP = (pp/5+1)·4, so 5→8, 10→12, 15→16, 20→20; `noPPBoosts` keep base (Struggle and Revival Blessing: 1) (`champions/scripts.ts:3-9,41-43` ✔). The cap affects 34 legal moves. | 1.2.0 "Wish: 12 → 8, Strength Sap: 12 → 8" ✔ | Same as PS |
| Timer / Bo3 / OTS | VGC Timer: start 420, grace 90, max 55 per turn, 90 on the first turn (`data/rulesets.ts:778-787` ✔). Bo1: OTS is only a UI accept button (`:1980-2001`); the reveal needs `>show-openteamsheets` (`sim/battle-stream.ts:209-210`). Bo3: forced reveal at preview (`:2002-2015`) ✔. | 90 s preview, 45 s move, 7 min Your Time, 20 min game (`vgchandbook.txt:347-350` ✔). Lists always open (§2.4 ✔). | Timers and series outside the core; OTS forced |

### 1.4 Executable differences between M-C and M-B (all [PS] ✔)

- **Wish and Strength Sap:** PP 5 (max 8) in M-C vs 10 (max 12) in M-B (`championsregmb/moves.ts:1-10`).
- **Items:** 18 are M-C only: 12 ordinary items (Eject Button, Leek, Air Balloon, Binding Band, four Terrain Seeds, Normal Gem, Red Card, Rocky Helmet, Terrain Extender) and 6 Mega Stones. There are no M-B-only items.
- **Species:** 35 entries are M-C only (for example Pawmot, Golisopod and Golisopod-Mega, Rillaboom, Baxcalibur and Baxcalibur-Mega, Salamence-Mega, Absol-Mega-Z, Garchomp-Mega-Z, Lucario-Mega-Z, Thievul, Gogoat).
- **Pool** (loaded Dex):
  - M-C: 382 entries, of which 82 Megas, 7 other battle-only formes and 293 others (26 of them cosmetic); 231 dex numbers.
  - M-B: 347 entries, 76 Megas, 208 dex numbers.
- **Learnsets:** only Archaludon differs. M-C adds Slash and drops Metal Burst and Mirror Coat (`championsregmb/learnsets.ts:30,33`), matching the official 1.2.0 note.
- **Unchanged:** ruleset, timer, OTS rules and all battle behaviour code are identical.

## 2. Mechanics delta vs gen9 base

Impact codes: **M1** primitives and owned state; **M2** commands and information; **M3** first combat slice; **M4** doubles closure.

"Reach" is the M-C-legal holder or learner, from Dex queries at the pin.

| Area | [PS] change vs gen9 base (✔) | Source | Official status | Impact |
|---|---|---|---|---|
| Stats | Stat Point formula. The Level Clause Mod branch applies only to random formats. | `champions/scripts.ts:10-40`; base `sim/battle.ts:2354-2372`; `config/formats.ts:252,285` | [UNOFF] matches | M3 |
| PP | Cap 20; `(pp/5+1)*4`; PP Ups ignored | `champions/scripts.ts:3-9,41-43`; base `sim/battle.ts:2374-2379` | [OFF] partial | M3; M1: max PP ≤ 20 |
| Per-move PP (legal) | 5 (max 8): Protect, King's Shield (also unlocked), Spiky Shield, Baneful Bunker, Wish, Strength Sap, Sandstorm, Snowscape, Beak Blast. Night Slash: 20 (max 20). Past/Future only: Obstruct, Purify, Nihil Light → 5; Shell Trap, Spin Out → 10. | `champions/moves.ts:43-51,564-568,689-692,765-768,855-858,928-931,940-943,981-984,1132-1135` (+`:693-704,789-792,879-882,944-948`) | [UNOFF]; Night Slash unsourced | M3/M4 data |
| Action speed | `−speed` under Trick Room. No `10000−speed`, and no 13-bit truncation **in any case**. Speed cap of 10000 kept (`sim/pokemon.ts:637`). | `champions/scripts.ts:45-54` vs `sim/pokemon.ts:641-649` | [UNOFF] matches | M1 signed key; M3/M4 |
| Dynamic re-sort | Gen 8+ re-sort after each action is inherited | `sim/battle.ts:2919-2926` | — | M3/M4 |
| Mega timing | Switch (103) before megaEvo (104), inherited | `sim/battle-queue.ts:183-184` | [UNOFF] issue #11907 reportedly closed "invalid" (not verified: BLOCKED) | M4 |
| Mega eligibility | Only `item.megaStone[baseSpecies.name]`; base also falls back to the base-species name | `champions/scripts.ts:182-194`; base `sim/battle-actions.ts:1869-1888` | — | M2 |
| Mega on faint | The Item branch omits `formeRegression`, so the Mega persists after fainting (executed: revived Gengar-Mega keeps Shadow Tag; re-run by critic, identical output) | `champions/scripts.ts:55-121`; base `sim/pokemon.ts:1468`, `sim/battle.ts:2558-2575` | [UNOFF] code comment only | M1 (no revert invariant); M4 |
| Forme-change protocol | No default `source`, so ability-driven `-formechange` lacks `[from] ability`. Reach: Stance Change (`data/abilities.ts:4529`) and Hunger Switch (`:1901`). | `champions/scripts.ts:56,99-103` vs `sim/pokemon.ts:1427-1430` | [UNK] may be unintended | M4 information |
| Tera | Removed | §1.3 | [OFF] not mentioned | M1/M2 |
| Damage | Numerically identical (`diff -w`). `-supereffective` / `-resisted` carry `min(\|typeMod\|,2)`. Random factor 85–100 inherited. | `champions/scripts.ts:196-312` vs `sim/battle-actions.ts:1724-1849`; `:270,277`; `sim/battle.ts:2391-2393` | [UNOFF] | M3 (visible event detail) |
| Parental Bond | `-hitcount` omitted when only hit 1 landed. Reach: Kangaskhan-Mega. | `champions/scripts.ts:547-548` vs `sim/battle-actions.ts:977` | [UNK] | M4 information |
| Protect bypass | Unseen Fist uses `onHitProtect`: contact moves go through Protect at ×0.25 with `-zbroken` (base: full damage, `protect` flag deleted). Piercing Drill does the same (unlocked). The ×0.25 code is base code. Reach: Golurk-Mega, Excadrill-Mega. | `champions/abilities.ts:86-95,59-62`; `data/abilities.ts:5276-5284,3282-3295`; `sim/battle.ts:1300-1309`; `sim/battle-actions.ts:1828-1835` | [UNOFF] | M4 |
| Unlocked Mega abilities | Dragonize (Feraligatr-Mega), Eelevate (Eelektross-Mega), Fire Mane (Pyroar-Mega), Mega Sol (Meganium-Mega), Spicy Spray (Scovillain-Mega), all base code | `champions/abilities.ts:14-21,18-21,30-33,45-48,82-85`; `data/abilities.ts:1036-1057,1147-1160,1295-1315,2558-2570,4466-4475`; `sim/pokemon.ts:2156,2193-2197,2259-2260` | [UNK] | M4 (only if held) |
| Aura Guard | Still `Future`, but Lucario-Mega-Z (Lucarionite Z, M-C only) receives it in battle (executed). Contact damage ×0.5; `breakable` marked TODO. | `data/abilities.ts:310-319` | [UNK] | M4; setup-gate policy |
| After-hit hooks | `onAfterHit` runs even when the attacker fainted: Knock Off, Rapid Spin, Mortal Spin, Covet, Thief, Ice Spinner, Stone Axe, Ceaseless Edge (complete list) | `champions/scripts.ts:411` vs `sim/battle-actions.ts:1123` | [UNK] | M4 |
| Sheer Force | AfterMoveSecondary is no longer suppressed (Eject Button, Red Card etc. fire). Emergency Exit is still suppressed (`champions/scripts.ts:578`). Berserk loses its exception (reach: Drampa and Drampa-Mega); Anger Shell has no holder. | `champions/scripts.ts:594-599` vs `sim/battle-actions.ts:811-818`; `champions/abilities.ts:2-13` | [UNK] | M4 |
| Paralysis | Full paralysis 1/8 (base 1/4); Speed halving unchanged | `champions/conditions.ts:2-9` vs `data/conditions.ts:41` | [UNOFF] | M4 |
| Sleep | `sample([2,3,3])`: 1 turn asleep with p = 1/3, 2 turns with p = 2/3 (base `random(2,5)`, 1–3 turns). One draw over 3 values. | `champions/conditions.ts:23` vs `data/conditions.ts:59` | [UNOFF] | M4 |
| Freeze | Counter 3, decremented per move attempt. Thaws if `time<=0 \|\| randomChance(1,4)`. The third attempt thaws without an RNG draw (base: 1/5 every attempt). | `champions/conditions.ts:43-54` vs `data/conditions.ts:99` | [UNOFF] | M4 (RNG accounting) |
| Emergency Exit / Wimp Out | No longer clear the `switchFlag` of **all active Pokémon on both sides**. Reach: Golisopod only (Wimp Out none). | `champions/abilities.ts:22-29,96-103` vs `data/abilities.ts:1253-1257,5496-5500` | [UNK] | M2 (two-side pivot); M4 |
| Healer / Natural Cure / Regenerator | Healer 1/2 (base 3/10). Natural Cure always emits `-curestatus …\|[silent]`; `onCheckShow` is removed. Regenerator emits `-heal …\|[silent]`. | `champions/abilities.ts:34-44,49-58,63-70`; base `data/abilities.ts:1817-1827,2811-2887,3833-3836` | [UNK] | M4 information |
| Run Away | Priority −10 handlers clear `trapped` and `maybeTrapped`. Reach: Thievul. | `champions/abilities.ts:71-81` | [UNOFF] | M2; M4 |
| Eject Button | Does not cancel the attacker's self-switch (M-C only). Executed: U-turn into Eject Button gives both sides `forceSwitch`; base gives only the target's side. | `champions/items.ts:266-281` vs `data/items.ts:1695-1696`; `championsregmb/items.ts:274-277` | [UNOFF] Smogon 3788180 | M2; M4 |
| Fake Out / First Impression | `onDisableMove` once `activeMoveActions > 0`; the counter increments before BeforeMove (`sim/battle-actions.ts:217,255`) | `champions/moves.ts:354-361,386-394` | [UNOFF] | M2 |
| Belch / Stuff Cheeks | `onDisableMove` removed; the moves fail through `onTry` | `champions/moves.ts:52-55,985-988` | [UNK] | M2 |
| Curse | Reworked. Non-Ghost user: target is `self` at queue time. Ghost Curse aimed at an ally redirects to a random foe. | `champions/moves.ts:165-196`; `sim/battle-queue.ts:263-266` | [UNOFF] | M2; M4 |
| Encore | Re-queues the pending action as the Encored move with no `targetLoc`, so `getRandomTarget` runs at Encore time. In doubles that is an RNG draw for any non-self target (`sim/battle.ts:2501-2521`). Skipped with Mental Herb. The gen 8+ re-sort recomputes priority (executed: Prankster Growl moved ahead of a faster foe). | `champions/moves.ts:309-345`; `sim/battle-queue.ts:268-271`; `sim/battle.ts:2619-2650,2919-2926` | [UNOFF] | M4 |
| Disable | The before-move check skips `cantusetwice` moves; selection-time disabling is unchanged. Reach: narrow (Tinkaton / Gigaton Hammer). | `champions/moves.ts:228-239` vs `data/moves.ts:3698-3703` | [UNK] | M4 |
| Milk Drink | `adjacentAllyOrSelf`. Reach: Gogoat. | `champions/moves.ts:648-651` | [UNOFF] | M2 |
| Rage Fist | `timesAttacked` resets in `clearVolatile` (switch-out, faint, Baton Pass) | `champions/scripts.ts:168`; callers `sim/battle-actions.ts:117`, `sim/battle.ts:2563` | [UNK] | M4 |
| Move numbers (legal) | BP: Apple Acid, Fire Lash, Grav Apple, Spirit Shackle 90; Bone Rush 30; First Impression 100; Infernal Parade 65; Meteor Assault 170 (unlocked); Mountain Gale 120; Night Daze 90; Psyshield Bash 90; Slash 80; Snipe Shot 85; Trop Kick 85; Beak Blast 120. Accuracy: Clangorous Soul never misses; Crabhammer 95; Make It Rain 95; Syrup Bomb 90. Also changed but Past: see Critic §2 item 4. | `champions/moves.ts` (e.g. `:18-21,635-639,903-906,1084-1087`) | [UNOFF]; Slash 80 unsourced | M3/M4 data |
| Move effects | Freeze-Dry: no freeze. Iron Head flinch 20%. Moonblast 10%. Dire Claw 30% + slicing. Make It Rain −2 SpA. Toxic Thread −2 Spe. Salt Cure 1/16 (1/8 vs Water/Steel). Slicing on Crush Claw, Dragon Claw, Shadow Claw (Metal Claw is Past). Punch on Double Shock; sound on Dragon Cheer; bypasssub on Howl. Growth becomes Grass; Snap Trap becomes Steel. | `champions/moves.ts:415-418,545-551,664-672,217-227,609-617,1065-1070,838-846,157-160,272-275,871-874,256-259,268-271,512-515,472-475,919-923` | [UNOFF] | M4 |
| Legality | 190 moves become `Past` (including Tackle and Tera Blast); 11 unlocked (Power Shift has no legal learner). 166 items (81 Mega Stones + 85 others; Leek is the only non-Mega unlock). Learnsets replaced; no prevo inheritance. | `champions/moves.ts`, `items.ts`, `learnsets.ts`; `sim/dex-species.ts:748` | [OFF] roster in-game / HOME (`vgchandbook.txt:118-124`) | Setup gate |
| HP display | Opponents see `floor(100·hp/maxhp)`, minimum 1; `y`/`r` at 20% (`r` only at exactly 20%) and `g`/`y` at 50%. Own side exact. Exact for everyone only with `format.debug`. | `sim/pokemon.ts:2066-2074`; `sim/battle.ts:227` | [UNOFF] | M2 |
| Team preview | Exact formes (only Xerneas, Zacian and Zamazenta masked; Gourgeist sizes now revealed). `details` also carries level, gender and shiny. Item empty. | `champions/rulesets.ts:34-54` vs `data/rulesets.ts:643-652`; `sim/pokemon.ts:536-541` | [UNK] shiny may be unintended | M2 |
| Team sheets | Nature revealed for Champions mods | `sim/battle.ts:3195` | [OFF] "stat alignment" listed (`vgchandbook.txt:184`) | M2 |

## 3. Impact on the M2 decision domain

### 3.1 Side-wide resources

**Mega Evolution only.**
- **Declared** as a modifier on a move command (`move X mega`), never on a switch.
- **Offered** when `canMegaEvo` is set. It is computed at construction (`sim/pokemon.ts:490`) and not offered while locked (`:1137-1138`).
- **A second Mega in the same side choice** is a choice error: "You can only mega-evolve once per battle" (`sim/side.ts:780-781`). Item Clause allows different stones, so two Mega-capable actives are possible.
- **Consumed** at execution (order 104): `canMegaEvo=false` for every Pokémon on the side (`sim/battle-actions.ts:1904-1912`).
- **After fainting** the forme persists (executed).

**Tera, Dynamax and Z:** none. Reject `teraType` and Z-crystals explicitly.

**[OFF] gap:** no official "one Mega per battle" or "no Tera" statement was retrieved.

### 3.2 Team preview and brought selection

- **[PS]** Ordered pick of 4; slots 1–2 lead. Duplicates and out-of-range picks are choice errors (`sim/side.ts:1061-1071`).
- **Bench order matters semantically only through Illusion**, which Zoroark and Zoroark-Hisui have (both legal; `champions/formats-data.ts:2884-2889`; validator executed).
  - With Illusion: 360 / 120 / 24 ordered picks for 6 / 5 / 4 registered.
  - Without Illusion: 180 distinct picks for 6 registered (6P2 × C(4,2)).
  - Enumerating all ordered 4-tuples is a safe superset.
- Do not copy PS's trimming or fill-in (`:1051-1058`).
- Registered size: 6 (PS) vs 4–6 (official). Owner decision, §6.3.

### 3.3 Mid-turn boundaries

- **Two-side simultaneous pivot.** U-turn or Volt Switch plus the target's Eject Button (M-C only), or Emergency Exit (Golisopod), leaves both flags set. One `makeRequest('switch')` goes to both sides (`sim/battle.ts:2877-2915`).
  - Executed (critic): M-C `p1.forceSwitch=[true,false]` and `p2.forceSwitch=[true,false]`; base gives only p2.
  - DECISION_CONTRACT §5 describes one-side pivots and §8 names "two-side replacement". This pivot case extends both.
- **Revival Blessing (Pawmot, M-C only).** The player picks a fainted party member (`sim/side.ts:958-980`; `sim/battle.ts:2781-2797`; request flag `sim/pokemon.ts:1183`). The revived Pokémon keeps its Mega forme and ability.
- **Encore.** A random target is drawn at Encore time. This is an RNG draw, not a decision boundary.

### 3.4 Per-slot selectable-domain changes

| Change | Effect |
|---|---|
| Fake Out, First Impression | Disabled once `activeMoveActions > 0`. The counter also increments on attempts stopped by sleep, paralysis or flinch, and for Dancer or Instruct. |
| Belch, Stuff Cheeks | Always offered; they fail on execution |
| Milk Drink | Target: self or adjacent ally |
| Curse | Request target depends on Ghost type (`sim/pokemon.ts:999-1003`). A non-Ghost user is forced to `self` at resolution. Do not pre-resolve Ghost redirection in candidates. |
| Run Away | Holder is never trapped or maybe-trapped. Interacts with hidden-trapping rejection. |
| Mega | Not offered while locked (§3.1) |

### 3.5 Information policy

- **[OFF]** Lists are always open. Everything except stats is shown to the opponent (`vgchandbook.txt:159-184` ✔). Gender is listed only when it is a battle-relevant form, for example Meowstic or Indeedee.
- **[PS] `showOpenTeamSheets`** publicly reveals species (set string), item, ability, moves, nature, gender and level for all registered Pokémon. Stat Points and IVs are nulled (`sim/battle.ts:3184-3224`). `teraType` would be shown if the validator were bypassed (`:3202`).
  - Bo1: the sim needs `>show-openteamsheets`.
  - Bo3: the reveal is automatic.
- **Team preview in PS** already reveals exact formes plus level, gender and shiny for every Pokémon, independent of OTS.
- **Proposed:**
  - Forced sheets revealing species and forme, item, ability, moves and nature.
  - Gender always (PS) or only when battle-relevant (official): owner decision.
  - Never reveal stats or Stat Points. No shiny or nickname data.
  - The brought four and their order stay private until sent in.
- **HP:** floor-percent (minimum 1) with 20%/50% flags; own side exact. [UNK] beyond the community colour-threshold report.
- **Events carrying extra information:**
  - `-supereffective` / `-resisted` magnitude;
  - Regenerator `-heal`;
  - Natural Cure per-Pokémon `-curestatus`;
  - `-formechange` without `[from]`;
  - Parental Bond single-hit `-hitcount` omission.

## 4. M1 (primitives and owned state): must / must not

**Must:**
1. **Roster shape.** Registered capacity 6 with a count; an ordered brought-four; two active positions; identity separate from position.
2. **Arithmetic helpers.** `trunc(x)` = ToUint32; `trunc(x,bits)` = `(x>>>0) mod 2^bits` (`sim/dex.ts:365-368`). The Custom Game formats use `Math.trunc` and remove the 10000 Speed cap (`config/formats.ts:320,329`; `sim/pokemon.ts:637`). Name the ladder variant.
3. **Signed ordering keys.** Speed is negative under Trick Room.
4. **Value ranges.**
   - Max PP ≤ 20 (1 for Struggle and Revival Blessing).
   - Stat Points ≤ 32 per stat, ≤ 66 total.
   - In the M-C pool: HP ≤ 160+32+75 = 267; other stats ≤ tr((230+32+20)·1.1) = 310.
   - uint16 suffices, with explicit capacity checks.
5. **Formes.** A fainted Pokémon may be in a Mega forme. No revert-on-faint invariant.
6. **RNG.**
   - Champions adds no RNG primitive (`sim/prng.ts:91-152`).
   - PS also draws gender at construction when it is unspecified (`sim/pokemon.ts:340`).
   - Decision 0001 (proposed; HEAD `2258167`) fixes PCG32 and rejects Showdown PRNG parity. Draw-for-draw differential traces therefore need controlled-RNG injection or a separate validated compatibility layer. A test tape is deferred to M3.

**Must not:** Tera, Dynamax or Z fields; a Mega side flag before M2; stat, PP, status or damage formulas; a level field beyond the profile constant 50; timers or Bo3 state; the turn-1000 tie as an in-game result.

## 5. Reference fixtures

**`test/sim/champions.js`** (366 lines ✔): `describe('Curse')` with **21** cases, 10 of them doubles, at lines 23, 39, 56, 74, 95, 114, 125, 139, 155, 177, 198, 219, 233, 246, 260, 275, 288, 301, 315, 334 and 349.
- **Coverage:** ally→foe redirection; Protean, Trick-or-Treat, Soak, Electrify and Skill Swap type changes; Pressure PP cost; Fly / semi-invulnerable targets; Ally Switch; Encore-forced Curse. Random targets are asserted through sums or disjunctions.
- **Harness:** `gen9championsdoublescustomgame@@@!teampreview` / `gen9championscustomgame@@@!teampreview`, seed `gen5,99176924e1c86af0`, `strictChoices` (`test/common.js:19,109-110` ✔). These formats run in `debug` (exact HP), use `Math.trunc`, have no Speed cap, and use unvalidated teams (sets without ability, item, Stat Points or gender, so gender is drawn from the RNG).
- **Legality:** the fixtures use M-C-illegal species and moves (Caterpie, Metapod, Magikarp, Kecleon, Wynaut, Deoxys; Splash). They are synthetic mechanic fixtures and should be labelled so per ARCHITECTURE §8.
- **Flaws:** the L260-273 Pressure case gives Aerodactyl no ability (`sim/pokemon.ts:421` has no default), and in L74-93 the variable `greninja` holds a Gengar.

**Other in-repo Champions tests: none ✔.** At the pin, `git ls-tree` shows only `test/sim/champions.js`, plus the mod's learnsets loaded in `test/sim/data.js:297`. Gen9 tests are not valid for mechanics that Champions overrides.

**Recommendation.** Derive DuoForge fixtures from the pinned code using the ladder formats (truncation, Speed cap, non-debug HP):
- `gen9championsvgc2026regmc` for Bo1 behaviour;
- `gen9championsvgc2026regmcbo3`, or `>show-openteamsheets`, to exercise the forced-sheet reveal.

Always specify gender. Record the seed format and exact team specs. Bypass the validator only for labelled synthetic cases.

## 6. Discrepancies and open questions

### 6.1 Showdown vs official sources

| # | Topic | [PS] | [OFF] | Assessment |
|---|---|---|---|---|
| 1 | Registered size | Exactly 6 (`champions/rulesets.ts:31`) | 4–6 (`vgchandbook.txt:115`) | Owner decision |
| 2 | Disclosure | OTS opt-in in Bo1, forced in Bo3. Preview shows gender, level and shiny for all. | Always open; gender only as a form | Profile decision |
| 3 | Timers | 55 s per turn, no game clock | 45 s / 7 min / 20 min (`vgchandbook.txt:347-350`) | Outside the core |
| 4 | Simultaneous last faint | Side of the last-fainted Pokémon wins, gen > 4 (`sim/battle.ts:2606-2610`) | "coded rules … whose Pokémon fainted first …" (`vgchandbook.txt:357-359`) | Adopt PS, labelled unverified |
| 5 | Turn limit | Tie after turn 1000 (`sim/battle.ts:1839-1843`) | None | Operational truncation |
| 6 | PS M-B vs official M-B | Slash (80 BP) legal in M-B. Politoed has no Pound. Archaludon has Mirror Coat and Metal Burst (`championsregmb/learnsets.ts:30,33`). | 1.2.0: "Slash can now be used"; Politoed loses Pound; Archaludon loses Mirror Coat and Metal Burst ✔ | Archaludon matches. Slash and Pound imply PS M-B diverges from official M-B [UNK, inference]. PS M-B also runs M-C-era behaviour code. |
| 7 | Slash 80, Night Slash 20 PP | Implemented | No source | [UNK] |
| 8 | Mega once per battle; no Tera | Implemented | Not stated | [UNK] |
| 9 | M-C new Pokémon | 23 base species / 26 non-Mega, non-cosmetic entries (35 incl. 6 Megas and 3 Squawkabilly colours) | "24 newly available" (via sweep) | [UNK] counting convention |
| 10 | Moving target | Fixed pin | [UNOFF] server-side calculations, patched without version bumps (`scratchpad/web/smogon-research-page-1.txt:4`) | The reference is the pin |

### 6.2 Community-reported divergences not fixed at the pin

All [UNOFF], not executed.

| Report | PS at the pin |
|---|---|
| Speed Swap then Mega keeps the swapped Speed (Alakazam, Raichu-Alola and Emolga learn Speed Swap) | Mega `setSpecies` overwrites stored stats (`sim/pokemon.ts:1407-1418`); inferred |
| Perish Song ends the game once one side has lost | Faints all affected Pokémon |
| Steel Beam recoil faint before the target's faint | Recoil after the target's faint |
| Sitrus Berry before the Dragon Tail forced switch | Berry eaten first |
| Mega/switch order (#11907) | Switch before Mega (`sim/battle-queue.ts:183-184`) |
| Struggle auto-select in the right slot offers switch-or-fight | Not implemented |
| Grassy Terrain heal in port order | Not implemented |
| Replacement order after simultaneous Eject Button | Not implemented |

### 6.3 Decisions for the owner

1. Regulation: M-C recommended.
2. Registered size: 6 or 4–6.
3. Non-50 levels: reject or normalize.
4. Information profile: forced sheets; nature (yes recommended); gender always or when battle-relevant; HP encoding.
5. §6.2 divergences: keep PS as the reference, record them as known divergences, and avoid them in certified teams where possible.
6. Simultaneous final faint: adopt the PS rule? Turn cap: operational truncation only?
7. Reject `teraType` and Z-crystals as setup errors.
8. Differential oracle: ladder formats, with the Bo3 variant (or `>show-openteamsheets`) for sheet reveal.
9. RNG: decision 0001 (proposed) already rejects Showdown PRNG parity. Confirm controlled-RNG injection for traces in M3.
10. **New:** Aura Guard (still `Future`, TODO-marked) and the six unlocked Mega abilities. Include them in the closure, or exclude the holders from certified teams?
11. Re-pin policy. The mod's commit history cannot be seen in the depth-1 clone.
12. Datamined data: no import without a provenance decision.

## 7. Verification log

**Re-read at the pin (report plus critic):**
- **Champions mod, full:** `champions/{scripts,conditions,abilities,items,rulesets}.ts` in full; `moves.ts` all non-legality entries; `championsregmb/*` in full.
- **Core sim at the cited lines:** `sim/{pokemon,battle,side,battle-queue,battle-actions,dex,dex-formats,dex-species,team-validator,prng,battle-stream}.ts`.
- **Base data and config:** `data/{conditions,rulesets,moves,items,abilities}.ts`; `config/formats.ts:240-331`; `test/sim/champions.js`; `test/common.js`.
- **`diff -w`, base vs Champions:** `modifyDamage`, `spreadMoveHit`, `hitStepMoveHitLoop` (critic found the Parental Bond line), `formeChange`, `clearVolatile`.

**Executed:**

| Command | Result | Wall time |
|---|---|---|
| `node scratchpad/synthv/v1.js` (report) | PASS: Encore priority recomputed; Mega persists through faint and revival | 0.54 s (report) |
| Same, re-run by critic | PASS; output identical to `v1.out` | 0.68 s |
| `node --experimental-strip-types scratchpad/synthv/megacount.mjs` (report) | Ran; formats-data-key counts 349/314 (method undercounts, see E3) | 0.24 s (report) |
| Critic Dex and validator queries (`scratchpad/crit/q1.js`, `q2.js`, inline `node -e` against `cmp/psfull/dist/sim`) | PASS: counts and reachability as stated; Battle-Bond Greninja rejected; Lucario + Lucarionite Z, Zoroark valid | not recorded |
| `node scratchpad/crit/auraguard.js cmp/psfull` | PASS: Lucario-Mega-Z has ability `auraguard` | 0.56 s (internal timer) |
| `node scratchpad/crit/ejectpivot.js cmp/psfull` | PASS: M-C both sides `forceSwitch`; base only the target's side | 0.51 s (internal timer) |

**Official artifacts:**
- Handbook PDF sha256 `a19683b8…afecc202` ✔ (revision 2026-09-01).
- Nintendo patch-notes HTML, Ver. 1.2.0 / 1.1.0 / 1.0.3 text ✔.

**NOT_RUN / BLOCKED:**
- pokemon.com M-B and M-C articles: 403 (report); not attempted by the critic.
- Bulbapedia and X posts.
- GitHub issue #11907: BLOCKED (repository not accessible in this session).
- Commit history of the Champions mod: unavailable in the depth-1 clone.
- §6.2 divergences not executed.

Proposed next step, only if the owner authorizes it: a small reviewed decision note recording the §6.3 answers and the §1.2 identifiers. Then the pre-M3 team-selection task can scope the closure against §2.

---

# Critic notes

- **Method.** I read all eight `data/mods/champions/*.ts` files and all five `championsregmb` files. For `moves.ts`, `items.ts` and `formats-data.ts` I extracted every entry with non-legality content by script. I also grepped every `champions` gate in `sim/` and `data/*.ts`. Counts and reachability came from the transpiled pin (`cmp/psfull`, clean, HEAD `b2cb775b`).
- **Most important corrections:**
  - Six unlocked Mega abilities were missing, and the still-`Future` Aura Guard is reachable (executed).
  - The Parental Bond protocol change was missing.
  - The Emergency Exit mechanism was misdescribed (base clears every active's flag), and Wimp Out and Anger Shell are unreachable.
  - The species and item counts were method errors.
  - Bo1 open team sheets are not forced inside the sim.
  - The RNG context is stale (decision 0001 now exists).
- **Remaining uncertainty:**
  - The official regulation dates were not re-verified.
  - Whether Aura Guard is intended to be active in-game.
  - Whether the `[from]`-less `-formechange` and the shiny leak at preview are intentional.
  - Every §6.2 item.
- **Repo.** `/home/user/duoforge` was not modified by this critic. It currently has uncommitted changes from 19:22–19:24 UTC whose origin is not established. Critic scratch files are in `/tmp/claude-0/-home-user-duoforge/29f5fd95-2022-56c3-9a4d-d660fae9aa6a/scratchpad/crit/`: `q1.js`, `q2.js`, `auraguard.js`, `ejectpivot.js`, `v1.rerun.out`, and the diff extracts.