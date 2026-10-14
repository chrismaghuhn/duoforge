# The luck meter of the live evaluation (#494)

Fixed before the first report (HauptSession, 2026-10-14). This file is the definition. Results come later, as aggregates, per series of a bot commit (`--code`) and per opponent letter.

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
   - No second particle or world implementation exists: the luck meter, the KO check and the live evaluation replay through `duoforge_live.cts`.
2. **The same actions.**
   - Our side: the bot's accepted choice (`cts.logged_choice`, `cts.pair_texts`).
   - The foe's side, per world: the action that the turn's lines show. `duoforge_replay.labels.turn_label` reads it on that world's own foe options (the engine's domain) with that particle's sheets.
   - The labels read the log, which is not a battle rule. This is the same reading as the BC labels, from the foe's side.
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

The engine does every step. Python averages and classifies nothing about the battle: it never reads a crit, a miss or a damage roll from a line.

### Changes to the decided definition

- **Wait points are valued** (HauptSession, 2026-10-14). The issue's definition values the next decision point. After a turn in which the bot knocks out a foe, the next point is often a wait request: only the foe replaces.
  - Excluding those turns would systematically cut off the luck of the bot's own KOs.
  - So the state that happened is valued at a wait point too (`LogReplay(waits=True)`; the default is unchanged).
- **Hidden foe actions:** OPEN, awaiting the HauptSession's decision.
  - A foe that faints before it acts never shows its action.
  - Excluding those turns would cut off luck of the same kind.
  - The proposal is to mix over the label set, weighted by the search's foe model in that world.

### Excluded turns, by name

Every excluded turn is counted by its reason and reported with its share. None is guessed.

| Reason | When |
|---|---|
| `not-searched:<cause>` | the decision was not searched (forced, raw, unreconstructible, …): no worlds |
| `not-turn:<boundary>` | a replacement or pivot point |
| `foe-action-ambiguous` | a foe slot's label holds more than one option (see the open point above) |
| `foe-action-unmatched` | a foe slot's label holds no option |
| `foe-action-not-allowed` | the foe pair is not in the world's pair mask |
| `own-choice-not-allowed`, `not_accepted` | the bot's played choice is not one of the point's pairs, or the log shows none accepted |
| `leaf-refused` | the engine refuses a leaf (#464, unsupported content) |
| `no-end` | the log stops in the turn without an end |

A battle that the replay does not follow is counted under the replay's named reason (`refused_battles`).

### C and its check

- **C = 8.** The check uses **C = 32 on series 3** (`2026-10-14-2e`, the battles of bot commit `a7dd956b`), fixed in advance.
- If the series means at C = 8 and C = 32 differ by more than the C = 8 interval, C is raised before anything is reported.

### Before the first live report

The comparison with `duoforge_learn.luck` on battles whose state is known is **mandatory** (HauptSession, 2026-10-14). Its method is OPEN, awaiting the HauptSession's decision. The proposal: the committed pool battles with the true team as the prior, where luck.py values the true world and the meter values its particles.

### The known limit

The worlds after the turn are drawn anew and hold what the turn revealed. The actual successor and the alternatives therefore come from nearly the same distribution, not exactly the same one, as they do engine against engine (luck.py). A turn's luck has mean zero only approximately. This is one more reason why only the series means say something.

## Running it

```
python tools/research/cts_live_eval.py --logs DIR --luck --checkpoint BC6 --checkpoint-sha256 bda5de8e… \
    --foe-net BC6 --code COMMIT [--labels PRIVATE.json] [--samples 8] --out PRIVATE.json
```

- It runs locally, under the machine lock, never on the VPS.
- The checkpoint and the logs are private and stay outside the repository.
- The result names the tool's and the engine's commit and dirty state, the pins and C.
