# The luck meter of the live evaluation (#494)

Fixed before the first report (HauptSession, 2026-10-14). This file is the definition. **From the commit of this file on, the definition is frozen.** Results come later, as aggregates, per series of a bot commit (`--code`) and per opponent letter.

**Purpose:** to separate bad luck from bad play in Ling-Ce's live series, so that small series say more.
- It describes; it is no gate, and it does not replace paired ladder measurements.
- **Only the series means carry meaning.** A single battle's luck is an anecdote, and so is a single turn's.

## Definition

For each searched turn of a closed-sheet battle the bot played:

> **luck(turn) = V(the state that happened) − mean over the worlds and C chance seeds of V(the next state | the same actions)**

Per battle: the summed luck, and the largest single turn. Per series: the mean summed luck per battle, the mean result, and the mean result with the luck taken off (result − summed luck), each with a normal 95% interval over the battles.

The parts:

1. **The worlds.**
   - They are the search's own worlds of the decision point. `cts.LogReplay` replays the bot's log with the bot's seed, the room as the key and the pinned set prior, and the honest search decides it again.
   - World w is particle w. It is weighted as the search weights it (the decision record's `weights`).
   - **The search is the series' own.** A series is replayed with the settings its bot played.
     - From the bot that names them, they come from its run logs' head (`search_settings`).
     - Before that, they come from the bot commit through the ladder step whose settings equal that commit's live `HONEST_SETTINGS` (`SEARCH_STEPS`): 1ffa6a03 → step 0, a7dd956b and 5c503d8a → 2e. An unknown commit is refused by name.
     - The logs of series 1 and 2 name no code. Their commit comes from the content (`--bot-commit`, HauptSession, 2026-10-14). Every run log in the directory must have started as that process (`PROCESS_STARTS`: 1ffa6a03 at 2026-10-13T19:23:34Z), and only battle logs with fed particle batches are replayed.
     - Of the processes before a7dd956b, only 1ffa6a03 played over the particles: a75c380a has no `cts.py` and answered closed sheets with `/choose default`. `|t:|` lines and file times are no source.
     - Battle logs without particle batches are counted by name (`skipped.no_particles`).
   - **Each replayed decision is compared with the bot's:** the logged search's cause, and for a searched one its pair. The share that differs is reported (`search_differs_share`). Above 5%, or with no decision compared at all, the result is `report_blocked`: no report until the cause is known.
   - Run logs count only for their own series: those of the series' bot commit, or those that name no code for `--bot-commit`. Other bots' run logs in a shared directory are ignored.
   - No second particle or world implementation exists: the luck meter, the KO check and the live evaluation replay through `duoforge_live.cts`.
2. **The same actions.**
   - Our side: the bot's accepted choice (`cts.logged_choice`, `cts.pair_texts`).
   - The foe's side, per world: the action that the turn's lines show. `duoforge_replay.labels.turn_label` reads it on that world's own foe options (the engine's domain) with that particle's sheets.
   - A switched-in member is found by its base species (a Mega's, Aegislash's) in the **world's** engine roster, from the world's observation. An option's reserve is a roster index of the world. In the committed test battles the world's roster order is the particle's; the meter reads the world's own all the same, so nothing rests on that. A base species on two members of a world is refused by name (`roster-ambiguous`).
   - **A world that cannot play what the lines show is left out**, like a refuted one. In that case the world's options hold no option the lines show, the label tells nothing where another world's label does, or the world's own domain bars the pair: a Choice lock, Taunt, Disable, Encore or Imprison in that world. A world also draws the foe's hidden bring (its pick order), so a world whose bench lacks the member the lines show switching in cannot play the turn either. In a committed test battle with the true team as the prior, 11 of 16 worlds drew another bring for such a turn.
     - This is read from the labels on the world's engine domain, never from a rule in Python.
     - It is counted in the share of worlds left out.
   - The labels read the log, which is not a battle rule. This is the same reading as the BC labels, from the foe's side.
   - **A world the turn refutes is left out.** The facts of the foe's lines through the turn (`duoforge_replay.facts.side_facts`, as the particle filter takes them) are tested against each world's sets with the particle filter's own test (`cts.agrees`: a used move, a revealed item or ability its set lacks). A world that fails could not have played the turn. The particle filter draws such a particle anew after the turn, and the meter leaves its world out of this turn. The remaining worlds are renormalized with the search's weights.
   - Where the lines narrow a foe slot to more than one option (a move that never showed because the member fainted or left first, or an unknown target), the alternatives are **mixed** over every allowed pair of that set. Each pair is weighted by the search's foe model in that world (the pinned BC6 foe network, read through Honest's world policy), renormalized on the set. Python only averages.
3. **The alternatives.**
   - `Batch.expand` of every world, with both choices, under **C = 8** chance seeds.
   - The seeds are `search_seeds(LUCK_SEED, key, sample)`, sample 0..C−1. The key is drawn from the decision's search key, which is a pure function of the room and the epoch.
   - These are common random numbers: the seeds never depend on the choices. `LUCK_SEED = 0x2026101400000494`.
4. **V.**
   - The bot's own value network from its seat: the checkpoint of the measured bot (BC6, pinned by its SHA-256, which is checked before every run), with its foe network.
   - A leaf that ends the battle counts as its result (+1, −1, 0), as in `duoforge_learn.luck.leaf_values`.
5. **The state that happened.**
   - It is the next decision point's particles, each view encoded as the search encodes its root, with the particles weighted alike.
   - If the battle ended in the turn, it is the battle's result. The turn's lines then come from the last batch, which the bot received (`{"in"}`) but no longer fed.
   - **A foe's pivot inside the turn** (U-turn, Volt Switch, Eject Button: the bot waits while the foe chooses its switch) is a wait point.
     - The turn is valued there, where the engine's leaves stop too.
     - The rest of the turn is valued nowhere. It is counted apart from the exclusions, as a partial turn (`turns_partial.rest-after-foe-pivot`), because the turn itself is valued: a wait point with no `|upkeep|` in the turn's lines before it.
     - The bot's own pivot inside a turn is the same: the turn is valued at the bot's switch request there, and the rest is counted as `rest-after-own-pivot`.
     - A foe slot that had not acted by then is mixed (point 2), and counts as mixed.

The engine does every step. Python averages and classifies nothing about the battle: it never reads a crit, a miss or a damage roll from a line.

### Changes to the decided definition, and the diagnostic run that showed them

The definition was fixed in the issue first. Before any report, one private diagnostic run of the first implementation on **series 3** (`2026-10-14-2e`, bot commit `a7dd956b`, C = 8) showed three biases of the method. That run was never a report and gave no number for one; its luck figures are not used.
- With the issue's rules, only 105 of the 362 decision points were valued.
- The exclusions fell exactly where the bot's own KOs and the foe's new information happen.

All three changes below remove a bias of the method, not of a result. The HauptSession approved each of them (2026-10-14).

A review of the implementation (2026-10-14) found three more places of the same kind before any report. The HauptSession approved the changes: worlds that cannot play the turn are left out, a foe's pivot is valued at the pivot with the rest counted, and each series' own search is replayed and compared. A suspected bug, a switched-in member looked up in the particle's roster rather than the world's, was ruled out on closer look. The rosters agree; the worlds differed in the foe's hidden bring, which they draw themselves (below). The meter reads the world's own roster anyway.

- **Wait points are valued** (HauptSession, 2026-10-14). The issue's definition values the next decision point. After a turn in which the bot knocks out a foe, the next point is often a wait request: only the foe replaces.
  - Excluding those turns would systematically cut off the luck of the bot's own KOs.
  - So the state that happened is valued at a wait point too (`LogReplay(waits=True)`; the default is unchanged).
- **Refuted worlds are left out** (HauptSession, 2026-10-14). The worlds of the decision point are the particles before the turn. When the foe uses a move for the first time, many worlds do not hold it.
  - In the diagnostic run, 84 turns came out "unknown". The foe acted visibly, but no option of the world held that action, for one of three reasons:
    - the world's sets lacked a newly shown move;
    - its domain barred the move;
    - or a switched-in member that the world's own drawn bring left on the bench (the foe's hidden pick order).
  - Those worlds are now left out (point 1 above), and every report gives the share of worlds left out (`worlds_dropped_share`).
  - A turn that refutes every world is excluded by name (`foe-action-not-in-worlds`).
- **Hidden foe actions are mixed** (HauptSession, 2026-10-14). A foe that faints or leaves before it acts never shows its action. Excluding those turns would cut off the luck of the bot's own KOs in the same way.
  - Such a turn is therefore mixed over the options the log allows, weighted by BC6 as the foe model (point 2 above).
  - The weighting can itself be biased against foes that play unlike BC6. So every report gives the share of mixed turns, and the series means **with and without** them (`luck_per_battle_unmixed`, `result_minus_luck_unmixed`).

### Excluded turns, by name

Every excluded turn is counted by its reason and reported with its share. None is guessed.

| Reason | When |
|---|---|
| `not-searched:<cause>` | the decision was not searched (forced, raw, unreconstructible, …): no worlds |
| `not-turn:<boundary>` | a replacement or pivot point |
| `foe-action-unknown` | the log tells nothing of a foe slot in every world (no line: the game ended before anyone acted) |
| `foe-model-zero` | the foe model gives every pair of a mixed set probability 0 |
| `foe-action-not-in-worlds` | no world remains: the turn refutes every world, or none can play what the lines show |
| `roster-ambiguous` | a base species on two members of a world's roster |
| `no-decision-record` | a point the bot was asked at but wrote no decision record for (or answered `/choose default`) |
| `facts:<skip>` | the foe's facts through the turn cannot be read (the particle filter's named skips, e.g. Transform) |
| `own-choice-not-allowed`, `not_accepted` | the bot's played choice is not one of the point's pairs, or the log shows none accepted |
| `leaf-refused` | the engine refuses a leaf (#464, unsupported content) |
| `no-end` | the log stops in the turn without an end (an unfinished battle: counted under `unfinished_excluded`) |

A battle that the replay does not follow is counted under the replay's named reason (`refused_battles`).

### C and its check

- **C = 8.** The check uses **C = 32 on series 3** (`2026-10-14-2e`, the battles of bot commit `a7dd956b`), fixed in advance.
- If the series means at C = 8 and C = 32 differ by more than the C = 8 interval, C is raised before anything is reported.

### The first report

- It holds the series the diagnostic run never saw: series 1 (`2026-10-13`) and series 2 (`2026-10-13b`), and the new series from `5c503d8a` once it has battles.
- It also holds series 3 (`2026-10-14-2e`, `a7dd956b`), marked as **the diagnostic series** and kept apart from the other series, because the method's three changes were found on it.
- Each series is reported apart (`--code`), with its exclusions, its mixed share and its share of worlds left out.

### Before the first live report

The comparison with `duoforge_learn.luck` on battles whose state is known is a **mandatory gate before every live report** (HauptSession, 2026-10-14):

- **Battles:** every fifth committed pool battle by its id, in sorted order (indices 0, 5, 10, …), both players. They are real Showdown battles (`tools/reference/ps_client.js` gives each player's stream) that the engine reproduces.
- **The count, derived** (note of 2026-10-15, added before the full run at the HauptSession's request; the selection and the criterion are unchanged; only a three-battle trial run on `0fed9c23` came before it):
  - `tests/reference/traces` holds 1,142 battles. A pool battle is one whose data set is `pool` (`trace_to_c.spec_data`): 979 of them. The other 163 are not pool battles: 90 `closure` battles (a spec without data) and 73 `team_c` battles (decision 0009). Neither is read under the pool data (decision 0015) that the bot and BC6 play.
  - Every fifth of the 979, sorted by id: indices 0, 5, …, 975, which is ⌈979 / 5⌉ = **196 battles**, 392 player streams. No battle is dropped from the selection; the streams of the pinned Showdown hold both players of all 196.
  - At run time a player's battle can still drop out, and each is counted by name in `player_battles_skipped`: `no-stream`, `meter:<error>` (the meter cannot replay the log) and `oracle:<error>` (luck.py's side cannot be built).
  - A turn drops out of the comparison by name: the meter's exclusions (`meter_excluded`, the table above) and luck.py's (`luck_py_skipped`): `hidden-counter` (a sleep or confusion counter, `partiallytrapped` or `twoturnmove` on the field, which the public record does not carry), `roster-unmatched`, `choice-not-allowed`, `choice-unmatched`, `no-input` and `no-end`.
- **Two arms on the same turns:**
  - The meter values each player's stream as a closed-sheet log, with the true foe team as the set prior.
  - luck.py (`Luck`, unchanged) values the true world of the same decision point. That world is built with `Batch.from_view` from the public record and the true hidden parts, taken from the trace's state.
  - Both use the same value network (BC6) and the trace's joint choice.
  - A hidden part that does not map unambiguously gets no silent default: the turn is excluded from the comparison by name.
- **Passed** when the 95% interval of the mean per-turn difference (meter − luck.py) includes 0, **or** |mean difference| < 0.01. The correlation is reported only.
- **Failed** means no live report: the cause is searched first and reported to the HauptSession.

### The result of the comparison (2026-10-15)

`tools/research/cts_luck_check.py` on `8c9e8933` (clean); the library is the WSL build of that commit (sha256 `fe8506d0…cec9df7`); BC6 sha256 `bda5de8e…`. A second run on the same commit gave the same result byte for byte. The selection is that of `8c9e8933`'s 1,142 traces. Main has held 11 more pool battles (`k3_*`) since `16b9abf9`; they sort in among the others and shift every fifth. The gate's 196 battles are therefore committed as `gate-battles.txt` (`--battles`; `--traces-at 8c9e8933` gives the same list).

**The rerun at the PR's head** `bc5b7bd6` (clean, main `16b9abf9` merged in; library sha256 `4bb8d6c7…be85d4`) with `--battles gate-battles.txt` gives the same numbers to the last digit. It also has the review's fixes:
- only named refusals are counted, by their message;
- a leaf the engine refused would skip the turn on luck.py's side too (`luck-leaf-refused`: none);
- the new name `true-record-unsupported:<reason>`.

- **By the criterion fixed in advance:** 196 battles, 1,448 turns compared. The mean difference (meter − luck.py) is **+0.0060**, 95% interval **[0.0017, 0.0102]**, correlation 0.773.
- **Descriptive, with a battle's turns as one cluster** (`half_width_by_battle`; turns of one battle are not independent, and both players of a battle are in the sample): ±0.0050, so [0.0009, 0.0110]. Unmixed: ±0.0025.
- **Narrow:** it passes only through |mean difference| < 0.01. The interval does not include 0, and its upper end lies just above 0.01.
- **Gate status (HauptSession, 2026-10-15): passed,** with the renaming below and its test (`test_cts_luck_check`) in the same PR. Before that it was provisionally passed.

**Dropped out, by name:**
- **Player battles, 30 of 392** (`player_battles_skipped`):
  - 29 stop at the particle filter's redraw cap (`meter:SearchError:the replay and the bot disagree on a stop (the replay stop:cts:redraw-cap, the bot did not)`): both players of 14 battles and player 1 of `g78_fainted_target`, all hand-built test battles: `c5_endeavor_ghost`, `g60_sub_dragontail`, `g60_sub_scale_shot`, `g67_magic_guard_substitute`, `g72b_dc_second`, `g76_db_ally_ko`, `g80_allyswitch_selftarget`, `g84b_ghost_substitute_faint`, `h18_magic_bounce_substitute_sitrus_mirror`, `h18_yawn_substitute_stomping_sitrus_mirror`, `sub2_ancientpower_substitute_tyrantrum`, `sub3_lava_plume_spread_unaware_appletun_168`, `xr3_beatup_sub` and `xr3_sheercold_ice_sub`. The fixture log has no fallback record of the bot, so the meter names them "the replay and the bot disagree on a stop".
  - 1 is the tracker's explicit refusal `meter:ValueError:slot 1 is locked into outrage without a known target` (from `tracker.domain()`).
  - The measured run keyed them by the message's first word (the log's name). The rerun gives the names above.
  - Live, each of these is a named stop of the bot, and it is counted.
- **The meter's turns** (`meter_excluded`): `no-decision-record` 302, `not-turn:REPLACEMENT` 119, `not-searched:unreconstructible` 81, `not-searched:forced` 15, `not-turn:PIVOT` 1, `foe-action-unknown` 1, `leaf-refused` 1.
- **luck.py's turns** (`luck_py_skipped`): `hidden-counter` 77, and 34 that the measured run named `true-world-refused:DUOFORGE_E_SCHEMA_MISMATCH`. That name was **not in the list fixed in advance**. Since the renaming they are `true-record-unsupported:engine-refuses-record` (32) and `true-record-unsupported:pivot-switch-reason-unknown` (2). Their investigation:
  - **The name is misleading.** No field of the record mismatches its schema.
    - At these 34 points the open-sheet tracker gives no public record: `record.assemble` returns the zero record with `E_UNSUPPORTED` and a named reason.
    - The measured tool did not check that status and handed the zero record to `Batch.from_view`, whose first check refuses revision 0 as `SCHEMA_MISMATCH`.
    - The tool now checks that status first and names the turn `true-record-unsupported:<reason>` (HauptSession, 2026-10-15). The test `test_cts_luck_check` hands in a zero record with that status and expects the named reason, not a schema error. The renaming changes no number: the same turns drop out.
  - **The reasons:**
    - 32 are `engine-refuses-record`: the engine's own public refusal (`duoforge_public_record_check`; decisions 0023 and 0026: a PIVOT, sealed commands, a locked move, the Revival Blessing proxy).
    - 2 are the tracker's `pivot-switch-reason-unknown`.
  - **They hang on three mechanics,** in 15 battles. In each case the point is where the true world of the turn or of its successor would be built.
    - **A pivot inside the turn, 29:** U-turn, Parting Shot (including into Mirror Armor, the 2 tracker refusals), Emergency Exit, an Eject Button through Symbiosis, and a drag. The battles are `g5_uturn_d` (6), `g71_faint_source_herb` (4), `g26_perish_recast`, `g30_rage_powder_pivot`, `g33_mirror_armor`, `g43_lopunnite`, `g46_fainted_reserve_drag`, `g62_quash_pivot`, `g69_symbiosis_eject`, `g7_wide_guard_pivot_own` and `g86_belly_faint_setboost` (2 each), and `g78_protect_p` (1).
    - **Revival Blessing, 4:** `g52_revive_win_milotic` (3) and `g52_fail_no_fainted_pawmot` (1).
    - **A move locked by Outrage at a replacement, 1:** `g56_outrage_cut`.
  - **The meter** values such a turn at the pivot from its particles, which the engine encodes itself (`search._encoded`, no public record), and counts the rest as a partial turn. luck.py has no true world there. These turns are therefore missing from the comparison, not wrongly valued.

### The second comparison, after S3 (2026-10-15)

Run as the HauptSession asked: after #512 S3 (#540) made a targeted foe move with more than one possible target `TARGET_UNKNOWN`, so that the meter mixes more turns. The tool, the criterion and the battles are the same: `gate-battles.txt`, 196 battles. The first result above stays as it is.

- **Provenance:**
  - the commit is `ec2e6dc4` (main with #540), clean;
  - the library is the WSL build of that commit, sha256 `e52c40108d251d77bd00627b2b114766cf70e857eae826006674b2fa78328332`;
  - BC6 sha256 `bda5de8e4e960f3df41b029cd4d3d87fc48838fdd47c8562a78649e222ee9f39`;
  - under the lock and the watchdog, not exclusive, with 14 GB free at the start.

| Run | Turns | Mixed turns (share) | Mean difference, 95% interval | Battle-clustered | Correlation | Unmixed: turns, mean, 95% | By the criterion fixed in advance |
|---|---|---|---|---|---|---|---|
| first, `8c9e8933` / `bc5b7bd6` | 1,448 | 238 (16%) | +0.0060 [0.0017, 0.0102] | ±0.0050 | 0.773 | 1,210, −0.0019 ± 0.0029 | passed, narrowly |
| **after S3**, `ec2e6dc4` | 1,448 | **917 (63%)** | **+0.0177 [0.0111, 0.0242]** | ±0.0096 | 0.606 | 531, −0.0019 ± 0.0034 | **not passed** |

- **By the criterion fixed in advance, the second comparison fails:** |mean| is above 0.01, and the interval does not include 0.
- **The mixed turns carry the difference again.** Derived from the two means, the 917 mixed turns run about +0.029 per turn above luck.py (no interval computed). The 531 unmixed turns agree with luck.py, their interval includes 0. S3 moved 679 turns from unmixed to mixed. A mixed turn's bias is smaller than before (+0.029 against +0.046), but there are almost four times as many.
- **Dropped out, by name:** the same as in the first run.
  - player battles: redraw cap 29, Outrage lock 1;
  - the meter's turns: `no-decision-record` 302, `not-turn:REPLACEMENT` 119, `not-searched:unreconstructible` 81, `not-searched:forced` 15, `not-turn:PIVOT` 1, `foe-action-unknown` 1, `leaf-refused` 1;
  - luck.py's turns: `hidden-counter` 77, `true-record-unsupported:engine-refuses-record` 32, `true-record-unsupported:pivot-switch-reason-unknown` 2.
- **What follows from it** is the HauptSession's decision. By the README, a failed gate means no live report until the cause is reported. The cause is the known one: the weighting of hidden foe actions by BC6 (#509), now on 63% of the turns.
- **The HauptSession's decision (2026-10-15):** live reports of the meter are suspended until a new comparison passes.

### The third comparison: target candidates from the engine's replay (fixed in advance)

**Fixed on 2026-10-15, before any code or run of it** (HauptSession: "the target is information, not luck"). Since S3, a targeted foe move whose line names one of several possible targets is `TARGET_UNKNOWN`, and the meter mixes its candidates by BC6. The target the line shows is public, though. Narrowing the candidates to it takes no luck away; it only takes away a mixing that is not needed.

**The method.** It changes only the foe slots whose reason is `target-unknown` (`labels.TARGET_UNKNOWN`).
- **Hidden moves stay as they were.** `move-hidden` and the other reasons are mixed by BC6 as before.
- **Replaying each candidate.** In each world the meter keeps (the rules above unchanged), each candidate pair of that world is stepped on a copy of the world:
  - with the bot's accepted choice and that pair;
  - under each of the turn's C = 8 seeds (`search_seeds(LUCK_SEED, turn_key, sample)`, the seeds of the expectation itself);
  - by `duoforge.privileged.step_events`, which steps a copy and returns the events.

  `privileged.step_events` is the tests' and the oracle's helper. Here it steps only the search's own hypotheses, never a true state, so the meter stays honest; the meter is no player.
- **The comparison.** For a target-unknown foe slot, the engine's `DUOFORGE_EVENT_MOVE` of that slot's user names a target (`other`), as the line `|move|<user>|<move>|<target>` does: the target the move resolved to, after any redirection.
  - **Reproduced:** a candidate is reproduced when, under at least one of the eight seeds, the engine's target is the line's target. A random retarget is chance, so one seed is enough.
  - **Not compared:** a slot whose line names no single target (a spread move, a move without a target, or no |move| line at all) is not compared, and its set stays as it is.
- **Narrowing.** The world keeps only the reproduced candidates.
  - One left: the slot is unique in that world, with no mixing.
  - Several left: they are mixed by BC6, renormalized on them.
  - None left: the world is left out, counted by name `target-not-reproduced`.
- **No rule in Python.** No redirection rule (Follow Me, Rage Powder, Storm Drain, Lightning Rod, Ally Switch, a fainted target, ...) is written in Python. The comparison only reads the engine's result. A turn whose every world is left out is excluded as `foe-action-not-in-worlds`, as before.
- **The tool.** `cts_luck.py` (the meter) changes. `tools/research/cts_luck_check.py` and the luck.py side are unchanged, and so is everything else of the definition: C, the seeds, the worlds, the exclusions and the pivot limit.

**Two battle sets, both fixed now:**
- **The gate's 196**, `gate-battles.txt`: every fifth pool battle of `8c9e8933`'s traces, from index 0. They have been seen three times, and the method changes after seeing their results.
- **A disjoint set of 196**, `gate-battles-disjoint.txt`: the same rule from index 2 (indices 2, 7, 12, …, 977 of the same 979 pool battles). It has no battle in common with the gate's; the file was written with that check. Its streams come from the same pinned Showdown.

**The criterion is the one fixed in advance, and BOTH sets must pass it:** the 95% interval of the mean per-turn difference (meter − luck.py) includes 0, or |mean| < 0.01. The new method becomes the meter's only if both pass. The meter goes live again only then, with its own README row.

**Reported per set:**
- the commit and dirty flag, the library's and BC6's sha256;
- the turns compared, the mean difference with its 95% interval, and the battle-clustered interval (descriptive);
- the correlation;
- mixed and unmixed apart;
- how many of the turns mixed by the after-S3 method become unique;
- `target-not-reproduced` worlds, and every exclusion by name.

### After the fact (after seeing the result)

The HauptSession set this on 2026-10-15, after the result above was known; it is not part of the definition fixed in advance.

- **The unmixed number is the main number of every live report:** −0.0019 ± 0.0029 on 1,210 turns, an interval that includes 0. The mixed number is shown beside it as a description only.
- **Why:** the whole difference sits in the mixed turns, those whose hidden foe action the meter weights by BC6. Derived from the two means, the 238 mixed turns run about **+0.046 per turn** above luck.py, which knows the true action. No interval was computed for them. Without them, the meter agrees with luck.py.

### The known limits

- **No pivot turn is compared.** The comparison holds no turn that ends at a pivot inside the turn (U-turn, Parting Shot, Emergency Exit, Eject Button, a drag), nor Revival Blessing or Outrage at a replacement. The rule `rest-after-foe-pivot` is therefore **not checked**. It is the same engine gap as in the replays, #524: the engine cannot build a world in the middle of a turn while moves are still queued. Once #524 is solved, the comparison is repeated for the pivots.
- **BC6 as the weight of a hidden foe action.** The mixing by BC6 estimates about +0.046 too much luck per mixed turn (238 turns). This fits #509, where BC6 was found not to be monotone. BC6 is only of limited use as the weight of hidden foe actions; the unmixed number does not depend on it.
- **Worlds drawn anew.** The worlds after the turn are drawn anew and hold what the turn revealed. The actual successor and the alternatives therefore come from nearly the same distribution, not exactly the same one, as they do engine against engine (luck.py). A turn's luck has mean zero only approximately. This is one more reason why only the series means say something.

## Running it

```
python tools/research/cts_live_eval.py --logs DIR --luck --checkpoint BC6 --checkpoint-sha256 bda5de8e… \
    --foe-net BC6 (--code COMMIT | --bot-commit COMMIT) [--labels PRIVATE.json] [--samples 8] --out PRIVATE.json
```

- It runs locally, under the machine lock, never on the VPS.
- The checkpoint and the logs are private and stay outside the repository.
- The result names the tool's and the engine's commit and dirty state, the pins and C.

The gate's comparison with luck.py (the streams come from the pinned Showdown: `node tools/reference/ps_client.js <checkout> <repo> --every > STREAMS.jsonl`):

```
python tools/research/cts_luck_check.py STREAMS.jsonl BC6 bda5de8e… OUT.json     --battles docs/benchmarks/2026-10-14-cts-luck/gate-battles.txt
```
