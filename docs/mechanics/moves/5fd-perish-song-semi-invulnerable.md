<a id="5fd"></a>

# 5fd. -, Perish Song misses a semi-invulnerable Pokemon

- Area: moves
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fd. **-, Perish Song misses a semi-invulnerable Pokemon** (Fuzz lane, branch `fuzz/553-perish-song-semi-invulnerable`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: Perish Song's onHitField (`data/moves.ts:13242-13260`) runs the Invulnerability event for each active Pokemon first: Phantom Force's charge returns false, so `-miss|user|target` shows, the Pokemon gets no volatile, and it counts as a result. The engine (`dfi_run_perish_song`) skipped the step (its comment still said no semi-invulnerable move was marked) and gave the charging Pokemon a perish count (fz_123_75). It now asks `dfi_invulnerable_to` (No Guard on either side lets it through) before Good as Gold and Soundproof. The move line gets no `[miss]` (the miss is onHitField's own line).

- **Evidence.** The recording `fz553_perish_song_phantom_force` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_perish_song_phantom_force` and by no other battle (`duoforge_diff_runner` over every pool record).
