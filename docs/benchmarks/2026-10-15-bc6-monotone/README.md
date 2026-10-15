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

## Part 2: a missing move or a weaker move? (predeclared 2026-10-15, the Detect probe)

Part 1's wrong-way rate (about 21–22 %) has two readings. The value may misjudge a **weaker** move set. Or it may react
to a **missing** move: real teams always carry four moves, so a member with three is a state BC6 never saw. Part 2
separates the two by putting Detect where the move was, so the member keeps four moves, and comparing that with the
removal.

**This section is a predeclaration, committed and pushed before any run of part 2.** The run starts only on the
HauptSession's go, under the machine lock and the WSL watchdog, not exclusive, with at least 8 GB free.

### Positions and edits

- The same 100 games as part 1: recorded again by the same tool with the same seed `0x2026101500000509`, in the same
  environment as part 1's run (no pins). The recording is deterministic: the run recomputes part 1's rows (the removed
  edits) and checks, game by game, that their digest equals part 1's `rows.jsonl`, or stops by name, `games_differ`.
- Detect's slot takes the `pp_max` of the pool's own Detect slots, which must all agree (no PP rule is derived).
- The same positions and the same edits as part 1 (own and mirror, every move of every active member with at least
  2 moves). Each edit is now built twice, at the same positions:
  - **removed:** as in part 1;
  - **replaced:** the move's slot holds Detect instead, `move_count` unchanged, the other moves in their slots.
- The replaced setup goes through the engine's setup check like the removed one. Named refusals of the replaced
  edit, on top of part 1's (`setup_refused`, `removed_move_used`, `replay_diverged`):
  - `detect_not_allowed`: the engine's setup check refuses Detect for the member (counted apart from other setup
    refusals; the replaced setup differs from the accepted one only in that slot, and the engine's status of each
    refusal is recorded and reported);
  - `already_detect`: the member already has Detect (a duplicate move);
  - `removed_is_detect`: the edited move is Detect itself (the replacement would change nothing).
- **The paired set:** the (position, edit, viewing seat) rows for which both the removed and the replaced edit were
  built. Every comparison below is on this set; its size and its share of part 1's built edits are reported.
- Detect is not a neutral move: it has real value in doubles. It is chosen because it is legal on most members and
  deals no damage, not because it is worthless.
- **The reading's subset (HauptSession, 2026-10-15):** the edits of a member that **already carries Protect**, the
  edited move not being Protect. Only there is Detect nearly redundant, so only there is "|ΔV_rd| small" the right
  expectation. For a member without Protect, Detect is a real gain, and a large ΔV_rd is correct, not an artifact.
  Every other edit (no Protect; the edited move is Protect) is reported **descriptively only**, apart, with no
  influence on the reading.
- **Size of the subset, estimated from part 1's rows before the run:** of part 1's 6,135 built edits, 3,067 are of a
  member carrying Protect with another move edited (all 100 games, at most 63 in one game); 1,148 remove Protect itself,
  1,790 are of members without Protect, 101 of members already carrying Detect (`already_detect`) and 29 remove Detect
  (`removed_is_detect`). Legality (`detect_not_allowed`) is not known before the run and lowers the 3,067.
- **Legality refusals** (`detect_not_allowed`) are counted and reported, in the subset and outside it, because they
  restrict the sample to Pokémon that learn Detect.

### Metric

- **ΔV_rd** = V_X(replaced) − V_X(removed), on BC6's value scale [−1, 1], from seat X's view; V as in part 1.
- **Main result, on the subset's paired rows:** the distribution of |ΔV_rd|, own and mirror apart: the 1, 5, 25, 50, 75, 95 and 99 % quantiles and
  the mean, with a 95 % game-cluster bootstrap interval for the median and the mean (2,000 resamples, seed `0x509`).
- **The share that tells the readings apart:** the share of the subset's paired rows with |ΔV_rd| > 0.02 (one point
  of win probability), with a 95 % Wilson and a game-cluster interval, own and mirror apart.
- The same quantities for the other edits, apart and descriptive only.
- **Beside it, descriptive only:** the signed ΔV_rd quantiles; and, on the paired set, Δp(replaced − unedited)
  against Δp(removed − unedited): part 1's wrong-way rate computed both ways on the same rows, with the paired
  difference and its game-cluster interval. Since Detect has value of its own, the replaced edit's "wrong way" is not a
  monotonicity error; it is reported only to show how much of part 1's rate moves with the missing slot.

### Reading (fixed before the run)

- All of it on the subset only. If the subset has **fewer than 200 paired edits** (own or mirror), the reading is
  "no conclusion".
- If the **median |ΔV_rd| is at most 0.02** and the share above 0.02 is **at most 25 %** (own and mirror each), BC6
  values a removed move about as it values Detect in its place: the missing slot is not what drives part 1's rate, and
  part 1 stands as a measure of how BC6 values weaker move sets.
- If the **median |ΔV_rd| is above 0.02**, or the share above 0.02 is **above 50 %** (own or mirror), the missing slot
  itself moves the value: part 1's rate is partly an artifact of an out-of-distribution input, and later networks are
  compared on the replaced edits as well.
- Between the two: no conclusion; the numbers are reported as they are.
- Either way, a wrong way is a hint, not a proof (as in part 1).

### Reported (aggregates only)

The counts (positions, paired rows, each named refusal of either edit), the results above, the split by the replaced
move's category (physical, special, status, Protect-like) for the main result, and the provenance as in part 1: the
commit with `dirty: false`, the library's sha256, BC6's checkpoint sha256 and the pool config's sha256.

### Run

- The tool gains `--replace detect` on this branch, test-driven (the replaced setup, the new refusals, the subset,
  the paired set, the games' digest check). One run, label `bc6-detect`, through `tools/ci/wsl_lock_watchdog.sh`
  inside `tools/ci/machine_lock.sh`, not exclusive, at least 8 GB free at the start.
- The result goes to #509 as aggregates, with the commit, `dirty: false`, the library's sha256 and BC6's sha256.
- **Disclosed:** a smoke of 2 games may run before this section's final commit to check the tool; its numbers fix
  nothing and are not reported.
