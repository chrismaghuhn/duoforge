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
- **Reading (HauptSession, 2026-10-15):** Falsche Richtung ist ein Hinweis, kein Beweis. Die Rate ist eine obere
  Schranke für Netzfehler, weil der Wert von BC6 den Ausgang unter menschenähnlichem Spiel schätzt.
- **Selection:** an edit is built only where the replay never used the removed move up to the position, so every
  built edit lies **before that move's first use** by its member; positions after it cannot be built by a replay and
  are refused (`removed_move_used`). The rate therefore holds for positions before first use, where using the move
  has not yet shaped the game. The refused share per category (below) shows which moves this drops most: the often
  chosen ones.

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
- The counts: positions, edits built, and each named refusal; the share refused as `removed_move_used` **per
  category** (physical, special, status, Protect-like), own and mirror apart, as a sign of the selection above.
- **Provenance:** the commit, `dirty: false`, the sha256 of `libduoforge_shared.so`, BC6's checkpoint sha256
  (`bda5de8e…`, in full in the results) and the pool config's sha256.

## Run

- **Tool:** `python -m duoforge_search.monotone`, to be built on this branch with tests. Rows are streamed to a JSONL
  file outside the repository; the report holds the aggregates.
- **One run**, label `bc6-mono`, through `tools/ci/wsl_lock_watchdog.sh` inside `tools/ci/machine_lock.sh`, not
  exclusive (no seconds are used). It starts only with at least 8 GB free on Windows.
- **Disclosed:** before this file's final commit, a smoke (2 games) may run to check the tool. Its numbers fix nothing
  and are not reported.

## Results (run 2026-10-14)

### Provenance

| | |
|---|---|
| Commit | `50ca34ba` (`search/509-monotone`), `dirty: false` |
| Library | `libduoforge_shared.so` built from it, sha256 `4bb8d6c789fbf0c41d7c9d0d05acb95067f5f2948c001cbb30976c0367be85d4` |
| BC6 | checkpoint sha256 `bda5de8e4e960f3df41b029cd4d3d87fc48838fdd47c8562a78649e222ee9f39`, encoder 6 |
| Pool | `--teams-from` config sha256 `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb` |
| Games | 100 (50 pairs, both seat assignments), seed `0x2026101500000509`; all 100 ended TERMINAL |
| Run | label `bc6-mono`, under the machine lock and the WSL watchdog, not exclusive, at least 8 GB free at the start |

**Disclosed:** the smoke (2 games) ran after this file's last predeclaration commit (`afbd6e5f`), not before it; the
file did not change because of it, and its numbers are not reported.

### Counts

11,792 (position, edit) pairs, each read from both seats (23,584 rows). Built: 6,135 edits. Refused: 5,657 edits as
`removed_move_used`; no `setup_refused`, no `replay_diverged`.

### The wrong-way rate (Δp beyond one point of win probability)

| | built | wrong way | rate | Wilson 95 % | game-cluster 95 % |
|---|---|---|---|---|---|
| own edit (Δp > +0.01) | 6,135 | 1,305 | **21.3 %** | 20.3–22.3 % | 19.4–23.1 % |
| mirror edit (Δp < −0.01) | 6,135 | 1,364 | **22.2 %** | 21.2–23.3 % | 20.3–24.2 % |

The comparison reading on the value scale (|ΔV| > 0.01 the wrong way): own 30.1 % (Wilson 29.0–31.3 %), mirror
30.3 % (29.1–31.4 %).

Falsche Richtung ist ein Hinweis, kein Beweis. Die Rate ist eine obere Schranke für Netzfehler, weil der Wert von BC6
den Ausgang unter menschenähnlichem Spiel schätzt.

### Distribution of Δp

| quantile | 1 % | 5 % | 25 % | 50 % | 75 % | 95 % | 99 % |
|---|---|---|---|---|---|---|---|
| own | −0.074 | −0.045 | −0.015 | −0.002 | +0.008 | +0.036 | +0.077 |
| mirror | −0.065 | −0.035 | −0.008 | +0.002 | +0.013 | +0.040 | +0.070 |

### Splits (rate, Wilson 95 %)

| removed move | built | own | mirror | refused as `removed_move_used` |
|---|---|---|---|---|
| physical | 2,674 | 19.2 % (17.7–20.7) | 22.6 % (21.0–24.2) | 46.5 % |
| special | 1,425 | 19.7 % (17.7–21.8) | 17.2 % (15.3–19.2) | 50.8 % |
| status | 2,036 | 25.2 % (23.3–27.1) | 25.3 % (23.5–27.3) | 47.8 % |
| Protect-like | 1,211 | 23.9 % (21.6–26.4) | 24.3 % (22.0–26.8) | 44.1 % |

Protect-like is a subset of status here; Silk Trap, Burning Bulwark and Obstruct are not in the pool. The refused share
is the same for own and mirror, since each edit is read from both seats.

By the viewing seat: own 22.6 % (seat 0) and 20.0 % (seat 1); mirror 21.5 % (seat 0) and 23.0 % (seat 1).
