# M11 Bo1 belief source: validation (a) and (b) on Reg M-C (2026-10-10)

These are the measurements of `docs/superpowers/specs/2026-10-10-m11-bo1-belief-design.md` (option B, split by player hash), made with the code of `docs/superpowers/plans/2026-10-10-m11-bo1-belief.md`. The report holds aggregates only. No replay, player or game is named, and the data and outputs stay outside the repository. Validation (c), BC with and without the belief rows, is not run: no BC training runs until the engine expansion is done (owner, 2026-10-10).

**Code state measured:** branch `chris/m11-bo1-belief` at `779a87f4`.
- This is main with #331 and #328, **before #334**, the tracker folds for Throat Chop, Aurora Veil, Perish, Encore and ability and item changes.
- After #334 the shares of perspectives that run to the end rise, so the Bo1 build's funnel below is the pre-#334 state.
- Validation (a) does not depend on the tracker. Validation (b) compares rows of the same code, so it holds as a comparison.

**Inputs:**
- HF dataset HolidayOugi state 2026-10-05, `[Gen 9] CHAMPIONS VGC 2026_part4.parquet` (sha256 `6a7d913b4a28f08c…`), which holds all Reg M-C games;
- the replay prior of 227 VGCPastes pastes (`4d377f69af557f51…`);
- the library at 0.44.0 (MSVC release);
- seed 1, one draw per game.

## The split by player hash

A game is a test game when either player's hash `h` has `h % 20 == 0`.

| Reg M-C | training | test |
|---|---|---|
| games with two sheets | 43,409 (89.0 %) | 5,391 (11.0 %) |
| Bo1 games without sheets, set up by the belief build | 53,554 games, 570,494 rows | 5,056 games, 53,495 rows |

No player appears on both sides. A test game is usually a test player against a training player.

## The set corpus

| | |
|---|---|
| sets counted | 403,107 (training-split sheets, each team once, plus the registry's `PP_` and `LL_` teams) |
| sets with a name outside the tables | 39, not taken |
| training sheets left out because a test game shows them | 1,363 |

The last row is the training opponent's team. In the first run it was in the corpus, and 1,881 of 5,391 test games were skipped as `skip:sheet-in-corpus`. Those sheets now stay out of the corpus, so both sides of a test game are measured.

The corpus has sha256 `942a272a470d815c…`.

## Validation (a): drawn sets against the true sheets

The test games with two sheets were drawn from their logs alone, with the sheets dropped:
- 5,247 games measured, 62,964 members;
- not measured: 1 `skip:sheet-in-corpus`, 77 `skip:belief-unsupported` (a species with fewer than 5 sets), 36 Illusion, 21 names outside the tables, 12 Transform.

| per member | share |
|---|---|
| level L0, a whole corpus set agrees with every fact | 99.5 % (L1 0.5 %) |
| the whole move set right | 42.5 % |
| moves the log never showed that the drawn set has | 72.7 % (133,265 of 183,183) |
| item right where the log did not reveal it | 58.9 % (of 41,631) |
| ability right where the log did not reveal it | 89.2 % (of 47,457) |
| nature right | 57.0 % |
| same prior key level as the true set | 63.8 % |
| same prior stat points as the true set | 55.6 % |

**Stat points.** Replays never show stat points, and the open sheets do not either, so a distance to a true spread cannot be measured. The two prior rows above stand in for it: they say whether the drawn set gets the same stat points from the prior as the true set would.

## Validation (b): rows of the drawn sheets against the true sheets

The same test games were built twice, with their sheets (`--split test`) and with the sheets dropped and drawn (`--mode drop_sheets`). Rows are matched by game, side and point. Options and labels are compared by move identity, and members with their moves in id order.

| | |
|---|---|
| rows of the sheet build | 69,256 |
| rows of the drawn build | 68,354 (98.7 %), all also in the sheet build |
| label set identical | 90.2 % |
| label sets overlapping | 99.9 % |
| mean Jaccard of the legal action pairs | 0.81 |
| rows whose header differs | 0.9 % |
| rows whose positions differ | 5.2 % |
| rows whose own or foe member views differ in any byte | 99.8 % |

The last row is expected. One drawn field that differs (item, nature, an unseen move, the stat points and so the stats) already changes the view. The label and mask rows are the measure of what BC would see.

## The Bo1 build (pre-#334 funnel)

| Reg M-C Bo1 without sheets | |
|---|---|
| taken by the build | 63,454 |
| refused, counted | 4,844 (Illusion 1,261, Palafin-Hero 392, Transform 275, species with too few corpus sets, e.g. Squawkabilly-White 117, Florges 87, Roserade 86) |
| internal errors | 0 |
| set up | 58,610 (92.4 %) |
| perspectives to the end | 40,711 of 117,220 (34.7 %; the top stops are picks-incomplete, then ability change, item change, Throat Chop, Aurora Veil and Electric Terrain) |
| rows | 623,989 |

These rows form a separate `bo1_belief` dataset. `bc_data` loads it only with `--source-weight bo1_belief=W`, and its validation split follows the player hashes. Before #334's folds can reach BC, the shards need the extension record; that is the next PR.
