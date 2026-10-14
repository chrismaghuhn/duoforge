# BC6's value under a removed move (#509, predeclared 2026-10-15)

#509 asks how monotone BC6's value function is. When a Pokémon loses one of its moves, the value of its own side
should not rise. When the foe loses one, the value should not fall. **This is a measurement only, with no training
and no gate.** The rate it finds is a fixed yardstick for every later network (D4 candidates, self-play). Whether
consistency losses enter training is decided in the self-play spec (#450).

**This file is a predeclaration, committed and pushed before any run.** The run starts only on the HauptSession's go,
under the machine lock and the WSL watchdog.

## Positions

- **Games, recorded fresh.** No recorder today stores both seats' choices, so the games are played and recorded by the
  tool:
  - 100 self-play games, BC6 against BC6, on the ladder's pool (`--teams-from`, open team sheets, no particles);
  - team pairs from `foe_arena.games(n_teams, 50, seed)`, each pair played with both seat assignments;
  - seed `0x2026101500000509`, at most 1,000 steps per game;
  - both seats sample from BC6's own policy (team head at team preview, pair head at turns) with a JAX key derived
    from (seed, game, step), so the games are deterministic.
  
  Each step's choices of both seats are stored **by label**: the move id, target, mega flag and the member a switch
  brings in, not slot indices, because removing a move shifts the slots. The records stay outside the repository.
- **Positions:** every TURN boundary of every game, from each seat X in {0, 1}.
- **Edits at a position, for seat X:**
  - **own:** for each occupied, not fainted active position of X whose member has at least 2 moves, each move is
    removed once;
  - **mirror:** the same for X's foe's active members. The value is still X's.
  
  Moves are removed, not replaced: the pool's contexts accept only a member's legal moves, so a Splash replacement is
  not built.

## Building an edited position (engine APIs only, refusals named)

1. The setup with the move removed is built through the engine's setup path: the member's move list without that
   move, `move_count − 1`. The engine's setup check decides. A refusal is counted as `setup_refused`.
2. The battle is reset to the edited setup at the game's environment index and episode under the game's seed
   (`Batch.reset_setups`), so its RNG stream is the original's.
3. The recorded choices are replayed by label up to the position. Two named refusals stop an edit:
   - a recorded choice that uses the removed move: `removed_move_used`;
   - any step whose engine events (decision 0007) for either seat differ from the unedited replay's:
     `replay_diverged`.
4. The unedited position is rebuilt the same way from the unedited setup, so before and after share one pipeline.

Python rewrites no battle bytes and derives no rule. It only resolves labels against the engine's offered options
and compares the engine's event records.

## Metric

- **V_X:** BC6's value of seat X's encoded row at the position (`query_encoded` with BC6's encoder and feature mask
  from its config, then `model.value`). Its scale is [−1, 1] (a terminal win is +1), so the win probability is
  p = (1 + V) / 2.
- **Δp** = (V_X(edited) − V_X(unedited)) / 2.
- **Wrong way:**
  - own edit: Δp > +0.01, one point of win probability, i.e. ΔV > 0.02;
  - mirror edit: Δp < −0.01.
- The issue's wording ("an increase > 0.01") can also be read on the value scale. That reading (|ΔV| > 0.01) is
  reported beside the main one, for comparison with other authors' 12–18 %; it does not replace it.

## Reported (aggregates only)

- The wrong-way rate, own and mirror apart, over the built edits (refused edits are left out):
  - with a 95 % Wilson interval;
  - with a 95 % game-cluster bootstrap (2,000 resamples, seed `0x509`), because the edits of one game are not
    independent.
- The distribution of Δp: the 1, 5, 25, 50, 75, 95 and 99 % quantiles, own and mirror apart.
- Splits, each with its rate and interval:
  - by the removed move's category: physical, special or status, from the engine's `move_static`. Protect-like is a
    fixed reporting set (Protect, Detect, Spiky Shield, King's Shield, Baneful Bunker, Silk Trap, Burning Bulwark,
    Obstruct, Wide Guard, Quick Guard), resolved through the engine's `data.find`; names the pool lacks are listed;
  - by seat;
  - by own or mirror edit.
- The counts: positions, edits built, and each named refusal.
- **Provenance:** the commit, `dirty: false`, the sha256 of `libduoforge_shared.so`, BC6's checkpoint sha256
  (`bda5de8e…`, in full in the results) and the pool config's sha256.

## Run

- **Tool:** `python -m duoforge_search.monotone`, to be built on this branch with tests. Rows are streamed to a JSONL
  file outside the repository; the report holds the aggregates.
- **One run**, label `bc6-mono`, through `tools/ci/wsl_lock_watchdog.sh` inside `tools/ci/machine_lock.sh`, not
  exclusive (no seconds are used). It starts only with at least 8 GB free on Windows.
- **Disclosed:** before this file's final commit, a smoke (2 games) may run to check the tool. Its numbers fix nothing
  and are not reported.
