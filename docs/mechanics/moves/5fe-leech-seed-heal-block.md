<a id="5fe"></a>

# 5fe. -, Leech Seed does not heal a heal-blocked seeder

- Area: moves
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fe. **-, Leech Seed does not heal a heal-blocked seeder** (Fuzz lane, branch `fuzz/553-leech-seed-heal-block`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: Leech Seed's residual calls this.heal for the seeder (`data/moves.ts:10223-10225`), and Battle.heal runs TryHeal first (`sim/battle.ts:2271-2272`): Heal Block's onTryHeal returns false (`data/moves.ts:8324-8333`), so a seeder under Heal Block (Psychic Noise) gains nothing, silently. The engine (`dfi_leech_drain`) healed it (fz_422_53); it now tests `dfi_heal_blocked`. The seeded Pokemon still loses its HP.

- **Evidence.** The recording `fz553_leech_seed_heal_block` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_leech_seed_heal_block` and by no other battle (`duoforge_diff_runner` over every pool record).
