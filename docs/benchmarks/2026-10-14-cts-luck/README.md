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

### The known limit

The worlds after the turn are drawn anew and hold what the turn revealed. The actual successor and the alternatives therefore come from nearly the same distribution, not exactly the same one, as they do engine against engine (luck.py). A turn's luck has mean zero only approximately. This is one more reason why only the series means say something.

## Running it

```
python tools/research/cts_live_eval.py --logs DIR --luck --checkpoint BC6 --checkpoint-sha256 bda5de8e… \
    --foe-net BC6 (--code COMMIT | --bot-commit COMMIT) [--labels PRIVATE.json] [--samples 8] --out PRIVATE.json
```

- It runs locally, under the machine lock, never on the VPS.
- The checkpoint and the logs are private and stay outside the repository.
- The result names the tool's and the engine's commit and dirty state, the pins and C.
