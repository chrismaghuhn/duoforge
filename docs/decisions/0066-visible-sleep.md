# 0066 - Visible sleep: the sleep counter is sampled per world (Champions: 2 or 3 turns), issue #442

Status: **in progress** (H33, lane A, branch `chris/442-visible-sleep`). The design was approved by the lead and HS on 2026-10-12 (the public value, the hypothesis revision, the law of section 4, no encoder feature). Open points: section 9.

## 1. Problem

A member that is visibly asleep makes the public record refuse (`DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP`, `src/state/view.c` predicate), because the sleep counter is hidden from both players. The honest search therefore falls back to raw play for about 13 to 15 % of the decisions of battles with Hypnosis, Sleep Powder or Yawn (PKMN Arena) and 4.5 to 4.7 % of the stage-0 ladder decisions (issue #442).

Today the view hides the counter and `duoforge_hypothesis.sleep[side][member]` (a uint64 word, `view.c` `dfi_sleep_weights` = {3,3,2} over the counter values 1..3) fills it. That law is not the pin: a fresh sleeper has counter 2 or 3 and the weights give counter 1 with probability 3/8. This decision replaces it with the exact law.

## 2. The pin (Showdown b2cb775, Champions mod first)

- Champions `slp` (`data/mods/champions/conditions.ts:11-30`): `inherit: true` (line 12); `onStart` sets `this.effectState.startTime = this.sample([2, 3, 3])` (line 23) and `time = startTime`.
- Base `onBeforeMove` (`data/conditions.ts:66-81`, inherited): priority 10 (line 66); each move attempt of the sleeper runs `statusState.time--` (line 71); when `time <= 0` it cures the status with no line and the move runs (lines 72-75); otherwise it prints `cant|X|slp` (line 76). A `sleepUsable` move still runs after the cant line (lines 77-79).
- So with start S, the sleeper prints S - 1 cant lines and wakes on the S-th move attempt. S = 2: one cant line, then the wake on the second attempt. S = 3: two cant lines, then the wake on the third attempt.
- The counted unit is the move attempt (`BeforeMove`), not the turn. A switch-out does not tick the counter: a switch is not a move. The public value is therefore the number of cant lines, not the elapsed turns.
- The start counter is one draw, `random(3)` mapped as `sleep_turns` = {2, 3, 3} (engine `dfi_try_status` in `src/combat/turn.c`, draw site `DFI_SITE_SLEEP_TURNS` = 7, `src/rng/draw.h:32`). The pin's `sample([2, 3, 3])` is the same draw.

## 3. Sources

Every source that sets `slp` through `slp.onStart` has the same law (the sample of section 2): Hypnosis (`data/moves.ts:9220`), Sleep Powder (16851), Spore (17748), Sing (16505), Dark Void (3355; Darkrai only), the 10 % secondary of Relic Song (14934), Effect Spore (ability), and Yawn (21146-21157, duration 2, then `trySetStatus('slp')` at the end of the residual). Yawn draws its counter when it is applied.

Different laws, refused:
- **Rest** (14957-14994): `onHit` sets the status (14984) and then `time = 3`, `startTime = 3` (14986-14987). The start is the point mass S = 3. The pin's sample still runs first and consumes one random number before it is overwritten. Rest is not marked on main (`src/data/support_manifest.c`); it stays an unsupported setup refusal.
- **Early Bird** (ability): `time--` runs twice per attempt (`data/conditions.ts:68-69`). Not marked; refused.
- **Comatose**: no `slp` status at all. Not implemented (no engine reference); refused.
- **Sleep Talk, Snore** (`sleepUsable`): the cant line still counts, so the law holds; they are not marked and stay refused at setup.

Marked on main today (`src/data/support_manifest.c`): Hypnosis (215), Sleep Powder (341), Yawn (367), Sing (509). Spore, Relic Song, Dark Void and Effect Spore are unmarked; they get the same law when they are marked, and until then they are refused at setup.

Champions ruleset: `Sleep Clause Mod` (`data/mods/champions/rulesets.ts:20`) limits the sleepers of a side; it does not change the counter law.

### 3a. Every decrement counts (review of the search lane, binding)

The count is the number of `time--` decrements of the sleeper, and each non-waking decrement prints exactly one `cant|X|slp` line:
- A plain attempt: one decrement, one cant line (pin lines 71, 76).
- Sleep Talk and Snore (`sleepUsable`, `data/moves.ts:16875` and `17161`, the only two in the pin): the decrement and the cant line come first (pin lines 71, 76), then `sleepUsable` lets the move run (lines 77-79). The cant still counts, so the law holds per attempt. They are **refused explicitly**: the engine's move gate refuses a sleeping user that picks Sleep Talk or Snore (`E_UNSUPPORTED`, turn.c, sleep branch), so no silent posterior is ever used for them. They are unmarked today in any case (refused by the `dfi_support.moves` gate in `dfi_run_move_body`, `src/combat/turn.c`).
- Early Bird (`data/conditions.ts:68-69`): two decrements per attempt, so the posterior of section 4 does not hold. **Refused explicitly**: a sleeping holder of Early Bird is `E_UNSUPPORTED` in the engine's sleep branch and in `duoforge_battle_from_view`, and the public record refuses it. Unmarked today.

### 3b. Rest (point mass, never picked)

Rest sets `slp` in its `onHit` and overwrites the counter with S = 3 (`data/moves.ts:14986-14987`). The engine has no Rest handler and Rest is unmarked: the `dfi_support.moves` gate in `dfi_run_move_body` (`src/combat/turn.c`) refuses Rest before any status is set, so a Rest sleeper cannot exist in a POOL battle. The sleep draw of section 5 is never applied to a Rest sleeper. If Rest is ever marked, it needs its own path (a source bit, the point mass S = 3) and its own decision; this step does not add it. A test asserts the refusal (section 9).

## 4. The law (posterior)

Let c be the number of cant lines the member has printed since its sleep started (0 to 2), and S the hidden start, S in {2, 3} with prior P(S=2) = 1/3, P(S=3) = 2/3. The member is still asleep after c attempts only if S > c. So the posterior is:

| c (cant lines seen) | S | counter (remaining cant lines before the wake) |
|---|---|---|
| 0 | 2 with 1/3, 3 with 2/3 | S - 0 = S |
| 1 | 2 with 1/3, 3 with 2/3 (both still asleep) | S - 1 |
| 2 | 3 (point mass) | 1 |
| 3 or more | impossible: refused (E_MALFORMED) | - |

A wake that is observed clears the status and the counter; no hidden value remains.

## 5. State (the engine)

- The engine keeps the remaining counter in `member.status_counter` (member block byte +28, as today), so `counter = S - c` holds in the engine state at all times.
- New: **`sleep_cant`**, one byte per roster member in the POOL tail, the member block's reserved byte +9 (`DFI_ENC_TAIL_MEMBER_RESERVED_OFF`, the tail member block of 10 bytes at `DFI_ENC_TAIL_MEMBER_OFF` 80 per side; no tail revision bump, the same pattern as G90's position byte 32). Older decoders refuse a nonzero value through the reserved check, as before.
- Written in `src/combat/turn.c` and `src/combat/flow/` (`dfi_run_revive` in `switch.h`, `dfi_check_fainted` in `turn.h`): `+1` at each `cant|X|slp` in `dfi_before_move`; `0` at the start of a sleep in `dfi_try_status` and at the status-clearing sites in `dfi_lum_cure`, `dfi_before_move`, `dfi_run_move_body`, `dfi_run_revive`, `dfi_wish_heal` and `dfi_check_fainted`. Function names are the source anchors; line offsets change when helpers move.
- Invariant (POOL kinds only, `pool_rules` guard): `sleep_cant != 0` implies `status == SLP`; `sleep_cant <= 2`; a non-POOL state has zero. The law itself is not an invariant of the state (fixtures set counters directly); it is tested through the sweep and the recordings.

## 6. Public value (the view)

- `sleep_cant` is **public** for both viewers, as the cant lines are in the battle log. It sits in the tail byte, which the view copies as it is.
- The counter byte stays `DUOFORGE_VIEW_HIDDEN` (0xFF) for both viewers, as today.
- `DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP` is no longer set for a POOL kind (the public record accepts a visible sleep). It stays set for every non-POOL kind, which has no tail byte to carry the count: those kinds still refuse publicly.
- No new view feature, no encoder feature, no new public constant (HS, 2026-10-12).

## 7. Rebuild (`duoforge_battle_from_view`, `src/state/view.c`)

For a member whose counter is hidden (asleep, `DUOFORGE_VIEW_HIDDEN`), with its `sleep_cant` c and its word `h = hypothesis->sleep[side][m]`:
- POOL kind only. A non-POOL kind with a hidden sleeper is `E_UNSUPPORTED` (no count is shown there).
- `c > 2`: `E_MALFORMED`.
- `c == 2`: S = 3; the word is ignored.
- `c` in {0, 1}: S = 2 if `dfi_pick(h, 3) == 0` (probability 1/3), otherwise S = 3 (probability 2/3).
- The counter becomes `S - c`.
- A nonzero `c` on a member that is not asleep: `E_INVALID_ARGUMENT`.
- The words of members that are not hidden are ignored (no refusal). This keeps the current contract: `honest.py` copies every word of the world unmasked.
- A hypothesis of a revision below 4 with a hidden POOL sleeper is `E_UNSUPPORTED` (the revision before this decision, like `DUOFORGE_HYPOTHESIS_REVISION_NO_TRAP`).

The word of a hypothesis built from a true state: S = 2 takes `dfi_word_of(0, 3)`, S = 3 takes `dfi_word_of(1, 3)` (the middle of each bucket).

## 7a. Non-POOL kinds: a hidden sleeper is refused by the rebuild

A non-POOL kind (closure, Team C) has no count byte, so a hidden counter there has no start that can be derived. The rebuild
(`duoforge_battle_from_view`) refuses it with E_UNSUPPORTED instead of drawing one. This does not change any game: the public
view already refuses a visible sleep under every non-POOL kind (the cause VISIBLE_SLEEP stays), so a view that comes from a
battle never reaches the rebuild with a hidden sleeper there. Only a hand-made view can, and then the refusal is the explicit
answer. The former weighted fill for these kinds is removed with the table (section 7).

## 8. Hypothesis revision

- `DUOFORGE_HYPOTHESIS_REVISION` 3 -> 4 (the meaning of `sleep[][]` changes for a hidden sleeper; the layout does not change: `sleep` stays a uint64 per side and member, `reserved1` and `reserved0` stay zero).
- Python: `python/tests/search/test_search_numpy.py` (revision 3 expectation) and `python/tests/search/test_honest.py` (`test_pinned_abc_decisions` normalises the revision to 4 before the hash; the hash itself is unchanged, the sleep words are not changed by this decision).
- `python/duoforge_replay` (bo1_belief writes hypotheses): the revision line only, with a test that a sleeper case round-trips (HS, 2026-10-12).

## 9. Tests (the engine's and the refusals)

- S = 2: attempt 1 prints one cant (c = 1, counter 1); attempt 2 wakes (status and c cleared). S = 3: attempt 1 (c = 1, counter 2), attempt 2 (c = 2, counter 1, still asleep), attempt 3 wakes.
- Rest: a POOL battle that uses Rest is `E_UNSUPPORTED` at the move gate and sets no status.
- Sleep Talk and Snore of a sleeper: `E_UNSUPPORTED`. Early Bird holder asleep: `E_UNSUPPORTED` (engine and from_view).
- The expectation changes in the tests are listed in the step report, each with its cause (search lane tests move with this PR, atomically).

## 10. Open points

1. The 7 mutants of the step report: decrement off by one; the old {3,3,2} fill; S = 2 allowed at c = 2; `sleep_cant` not reset at a clear site; `sleep_cant` incremented on a switch or on the wake; threshold 1/2 instead of 1/3; counter != S - c.

## 11. Mutant results (step 442, local, one lock job)

Each mutant was applied to the committed source, `duoforge_view_sleep_count` rebuilt and run, and the source restored from git.
Every mutant is caught (exit 1):

| mutant | caught by (first failing check) | failures |
|---|---|---|
| M1 the first cant is not counted | `sleep_cant == cant` after the first attempt | 3 |
| M2 old 1..3 fill (counter 1 + pick) | `rebuilt counter == S - c` | 33 |
| M3 S = 2 allowed at c = 2 | `from_view == OK` (counter 0) | 12 |
| M4 the wake keeps the count | `duoforge_battle_step == OK` (invariant) | 6 |
| M5 the wake increments the count | `duoforge_battle_step == OK` (invariant) | 6 |
| M6 threshold 1/2 instead of 1/3 | rebuilt counter == expected counter | 5 |
| M7 counter = S instead of S - c | `rebuilt counter == S - c` | 18 |

Clean rebuild after the mutants: exit 0, 0 failures. Runner (duoforge_view_sleep_count) SHA-256 2fd26bcb97bcbbb0f038eb60111b7ac44186c763837c902dfb0047f41389060d.

## 12. Evidence from the Showdown traces already in the repository (pin b2cb775)

Every sleep episode in `tests/reference/traces` that ends in a wake was counted: the cant lines printed for the member before its
`-curestatus`. The wake comes at attempt S, so S = cant lines + 1 (the law of section 4). Counts by battle kind:

| kind | source | S = 2 (c = 1 before the wake) | S = 3 (c = 2 before the wake) |
|---|---|---|---|
| POOL | Hypnosis | 1 | 0 (recording open, see section 13) |
| POOL | Sing | 2 | 1 |
| POOL | Sleep Powder | 1 | 1 |
| POOL | Yawn | 5 | 10 |
| Team C | Hypnosis | 1 | 8 |
| Team C | Yawn | 2 | 0 |
| closure | Hypnosis | 11 | 13 |

The c = 2 state (two cant lines, the sleeper still asleep with counter 1) occurs in every S = 3 episode. No episode contradicts
the law. The conformance replays of these battles are green on the branch (section 9's tests), so the engine's counters agree
with Showdown at every step.

## 13. Open: one POOL recording

POOL has no Hypnosis episode with S = 3. One recording is open: a POOL battle in which a Hypnosis user (learnset entry
`hypnosis` in `data/mods/champions/learnsets.ts`; Gengar, Gardevoir, Musharna and Espathra are in the pool tables) lands the
move and the foe wakes at attempt 3. The seed decides S (sample([2, 3, 3])), so the spec needs a seed with S = 3, at most two
attempts. Not recorded in this step.

## 14. Campaign (random differential, Showdown judge, seed 442)

Two POOL team files (X: a Hypnosis team with Milotic, from `g22_liquid_voice` team 0; Y: a Sleep Powder team, from `g30_powder_a` team 0),
pairings XY, YX, XX, YY, 300 battles, `--keep-traces`, `tools/reference/diff_driver.py random`. Result: PASS 300, 0 divergences.

| measure | value |
|---|---|
| battles with a sleep | 172 of 300 |
| sleep starts, Hypnosis | 208 |
| sleep starts, Sleep Powder | 140 |
| sleep starts, total | 348 (no Sing or Yawn: these teams do not use them) |
| cant lines (cant|X|slp) | 521 |
| wakes, Hypnosis at attempt 2 (S = 2) / attempt 3 (S = 3) | 66 / 97 |
| wakes, Sleep Powder at attempt 2 / attempt 3 | 41 / 60 |
| episodes with a count above 2 | 0 |

The count is checked by the evidence logic of section 4: the engine's invariants (c <= 2, only SLP) run on every step, and the
counter comparison of the replay covers S - c at every step, so an explicit comparison of c in the driver is not needed.
Each woken episode woke at exactly S - 1 cant lines plus one (attempt 2 or 3), as section 4 says. The POOL Hypnosis S = 3 case
of section 13 is therefore recorded by this campaign (97 episodes), and section 13 is closed.
