# Restructure 6c: the moves tests under behaviour names — proof

Clean main **`757a00ca`** (#653) against the clean branch head **`8a763e74`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with
`DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py): those of 6b, where this step's renames are the done rows
that the before tree still has.

## Change

- **The renames.** `tools/restructure/rename_tests.py mv`, then `names --areas moves`, carry out the 22 planned renames of `tests/renames.tsv` (a commit with `git mv` only, then the names; as in 6b). `src/` changes in comments only.
- **A fix to the rename tools' own tests.** Their fixtures used G62 (Haze) as the example, so the rewrite renamed them too, because G62 is one of this step's rows. They are back as on main, with a made-up step G999 that no table row has.

| Old | New |
|---|---|
| `moves/test_pool_g11.c`, `duoforge.state.pool_g11` | `moves/test_soak.c`, `duoforge.moves.soak` |
| `moves/test_pool_g17.c`, `duoforge.state.pool_g17` | `moves/test_recharge.c`, `duoforge.moves.recharge` |
| `moves/test_pool_g26.c`, `duoforge.state.pool_g26` | `moves/test_perish_song.c`, `duoforge.moves.perish_song` |
| `moves/test_pool_g38.c`, `duoforge.state.pool_g38` | `moves/test_imprison.c`, `duoforge.moves.imprison` |
| `moves/test_pool_g50.c`, `duoforge.state.pool_g50` | `moves/test_double_shock.c`, `duoforge.moves.double_shock` |
| `moves/test_pool_g56.c`, `duoforge.state.pool_g56` | `moves/test_outrage_lock.c`, `duoforge.moves.outrage_lock` |
| `moves/test_pool_g58.c`, `duoforge.state.pool_g58` | `moves/test_phantom_force.c`, `duoforge.moves.phantom_force` |
| `moves/test_pool_g60.c`, `duoforge.state.pool_g60` | `moves/test_substitute.c`, `duoforge.moves.substitute` |
| `moves/test_pool_g62.c`, `duoforge.state.pool_g62` | `moves/test_haze.c`, `duoforge.moves.haze` |
| `moves/test_pool_g70.c`, `duoforge.state.pool_g70` | `moves/test_skill_swap.c`, `duoforge.moves.skill_swap` |
| `moves/test_pool_g71.c`, `duoforge.state.pool_g71` | `moves/test_attract.c`, `duoforge.moves.attract` |
| `moves/test_pool_g74.c`, `duoforge.state.pool_g74` | `moves/test_baton_pass.c`, `duoforge.moves.baton_pass` |
| `moves/test_pool_g78.c`, `duoforge.state.pool_g78` | `moves/test_dragon_darts.c`, `duoforge.moves.dragon_darts` |
| `moves/test_pool_g82.c`, `duoforge.state.pool_g82` | `moves/test_healing_wish.c`, `duoforge.moves.healing_wish` |
| `moves/test_pool_g87.c`, `duoforge.state.pool_g87` | `moves/test_attract_source_view.c`, `duoforge.moves.attract_source_view` |
| `moves/test_pool_g88.c`, `duoforge.state.pool_g88` | `moves/test_turn_history_moves.c`, `duoforge.moves.turn_history_moves` |
| `moves/test_pool_g9.c`, `duoforge.state.pool_g9` | `moves/test_encore.c`, `duoforge.moves.encore` |
| `moves/test_pool_g90.c`, `duoforge.state.pool_g90` | `moves/test_partial_trap.c`, `duoforge.moves.partial_trap` |
| `moves/test_pool_g92.c`, `duoforge.state.pool_g92` | `moves/test_confusion_moves.c`, `duoforge.moves.confusion_moves` |
| `moves/test_pool_k1.c`, `duoforge.state.pool_k1` | `moves/test_temper_flare.c`, `duoforge.moves.temper_flare` |
| `moves/test_pool_k3.c`, `duoforge.state.pool_k3` | `moves/test_speed_swap.c`, `duoforge.moves.speed_swap` |
| `moves/test_pool_lockfam_sleep.c`, `duoforge.state.pool_lockfam_sleep` | `moves/test_lockedmove_sleep.c`, `duoforge.moves.lockedmove_sleep` |

## Gate: the library is byte-equal

`libduoforge_shared.so` is the same before and after in all three profiles: IPO `0a1d3855…`, without IPO `57d79859…`,
Debug `8f4f3bef…`.

## P1–P6

- **P1:**
  - The inventory under the renames is identical: 1608 names.
  - Every renamed test keeps every property, its labels included; its command differs only in the name of its executable.
  - Selected runs: 279 with IPO and 274 without, before and after, all passed.
- **Full suite of `8a763e74`** (without IPO, Python, JAX on the CPU, pinned checkout):
  - 1608 tests, **1606 passed**.
  - One skipped: `duoforge.lint.no_mutable_globals` (not ELF here).
  - One failed: `duoforge.python.expert_teacher` (#585, known red on this machine).
  - 91 Python tests ran, none skipped.
- **The shard partition of #646:** `tools/ci/check_ctest_labels.py --partition` reports every one of the 1608 tests in exactly one shard.
- **P2:** 2808 executions and 1241 battles, byte-equal before and after with and without IPO (`77dc5c4a…`); the native reports are equal in all three profiles.
- **P3–P6:** all unchanged.
