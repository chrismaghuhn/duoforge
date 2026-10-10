# 0047. Leech Seed and Curse (G84, decision 0015 letter 5cm)

Status: PHASE 1, design proposal (builder H19). No engine code, no recordings, no lock use. Waiting for the lead's answer.
Pin: Pokemon Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`).

## 1. Pin semantics

**Leech Seed** (`data/moves.ts:10202-10231`): Grass, Status, accuracy 90, flags `protect, reflectable, mirror, metronome`
(10210), `volatileStatus: 'leechseed'` (10211). No Champions override for `leechseed` (`data/mods/champions/moves.ts` has
none; the learnset is `learnsets.ts:29`, Venusaur among others).
- Grass immunity: `onTryImmunity(target)` returns `!target.hasType('Grass')` (10229-10231).
- Substitute: the Substitute condition's `onTryPrimaryHit` (`data/moves.ts:18340-18343`) returns (lets the move through) only
  for `target === source`, `move.flags['bypasssub']` or `move.infiltrates`. Leech Seed has none of these, so a standing
  Substitute on the target blocks it. **This is the pin line the batch note asked for: Leech Seed does not go through a
  Substitute.** Curse has `bypasssub` (3274) and does go through.
- Source: `addVolatile` stores `source` and `sourceSlot = source.getSlot()` (`sim/pokemon.ts:2000-2003`).
- Residual, order 8 (`onResidualOrder: 8`, 10216): the target is `this.getAtSlot(sourceSlot)`, i.e. whoever stands at that
  slot now, not the original Pokemon (10218). No target, a fainted one or hp <= 0: nothing (10219-10222). Otherwise
  `this.damage(baseMaxhp / 8, pokemon, target)` on the holder (10223), then `this.heal(damage, target, pokemon)` on the target
  (10224-10226).
- Substitute and residual: the Substitute absorbs only move hits (`data/moves.ts:18341-18371`, the substitute's own hit
  path); `spreadDamage` (`sim/battle.ts:2204`) has no Substitute check outside gen 1. So the holder's drain goes through a
  Substitute, and the heal goes to the source slot regardless.
- Big Root: `onTryHeal` multiplies the heal by 5324/4096 for effect `leechseed` (`data/items.ts:489-493`). Big Root is **not**
  in the duoforge pool (`legal_pool.json`: `in_duoforge: false`), so it is not modelled and cannot appear in a team.
- Baton Pass: `copyVolatileFrom` copies every volatile unless the condition is `noCopy` (`sim/pokemon.ts:1246-1251`). The
  Leech Seed condition has no `noCopy` (10212-10228), so it is copied; `sourceSlot` goes with it unchanged.
- Protect: Leech Seed has the `protect` flag, so Protect blocks it (10210).

**Curse** (base `data/moves.ts:3266-3308`, Champions override `data/mods/champions/moves.ts:165-196`):
- Flags `bypasssub, metronome` (3274): through a Substitute, and **no** `protect` flag, so Protect does not block it.
- Ghost user (`source.hasType('Ghost')`):
  - `onModifyMove` (champions 172-174): target `randomNormal` when there is no target or the target is an ally of the user.
  - `onTryHit` (champions 178-180): returns false (fails) when the target already has `curse`.
  - `onHit` (champions 187): `directDamage(source.maxhp / 2, source, source)`: half the user's max HP, to the user.
  - champions 188-194: an ally target is replaced by `getRandomTarget(source, 'Curse')`; then `delete target.volatiles['curse']`
    and `target.addVolatile('curse')` (a refresh).
- Non-Ghost user: `onModifyMove` sets `target = 'self'` (champions 168-171, and the base 3276-3281); `onHit`
  (champions 184-186) `this.boost({ spe: -1, atk: 1, def: 1 }, source, source)`. No volatile.
- Curse condition (base 3295-3303, inherited by the override): `onStart` prints `-start|X|Curse|[of] source`; residual
  `onResidualOrder: 12` (3299): `this.damage(pokemon.baseMaxhp / 4)` on the holder (no source).
- Residual order of the pin: futuremove 3 (`conditions.ts` 389), psn 9 (133), tox 9 (154), brn 10 (15), **Leech Seed 8**
  (10216), **Curse 12** (3299), partially trapped 13 (233). Leech Seed runs before poison and burn; Curse runs after them and
  before binding.

## 2. State

- **Leech Seed:** reuse the tail field `leech_seed_source` (`src/state/battle_internal.h:315`, rev 4, codec
  `state_codec.c:42/172`, invariant `invariants.c:673`: at most 4, never the occupant's own position). Set on a hit (source
  flat + 1). Cleared with the holder's occupancy (`dfi_tail_clear_occupant`). Nothing new.
- **Curse:** no state on main. The volatile flags byte is full (`DFI_VOL_*`, bits 0 to 7, `battle_internal.h:68-76`). Two
  options for a per-position bit, to be decided by the lead:
  - (a) bit 7 of `position_flags` (the lane A byte; bits 0, 1-3 are taken, 4 is G76's, 5-6 are G88's). The invariant
    (`dfi_position_flags_ok`) would allow bit 7 at a standing, fainted and empty position, and it would be cleared with the
    occupant like the others. Interaction with G88 and G76 to coordinate.
  - (b) a new rev 5 byte, if the lead does not want bit 7 used.
  Cleared with the occupant (a switch-out ends it, as the pin's `clearVolatile` does) and copied by Baton Pass (no `noCopy`).
- The curse volatile id, if one is needed: `DUOFORGE_VOLATILE_CURSE` (lane A's volatile is 12, per the batch note).

## 3. Information safety (decisions 0007, 0023)

Both are public. The move line shows the user; `-start|X|move: Leech Seed` shows the holder; the drain lines show the
holder and the source (heal `[of]`); `-start|X|Curse|[of] source` shows the source. The seeding user is in the public move line,
so the source slot is known to both viewers. No refusal.

## 4. Public values

- Views: `DUOFORGE_POSITION_EXT_LEECH_SEED` (0x8, feature 28) and `DUOFORGE_POSITION_EXT_CURSE` (0x800, feature 36) already
  exist, and both features are in encoder 5's list (`src/encode/encode.c:81-83`). No encoder change is needed for them.
  **But nothing produces these bits on main**: `src/state/observation.c` has no Leech Seed or Curse line. G84 adds them.
- Causes: the residual drain is `[from] Leech Seed` with the holder and the source, and the Curse residual is its own line.
  No existing cause covers a volatile residual drain (`include/duoforge/duoforge.h` causes). **Ask:** a cause for Leech Seed
  (`DUOFORGE_CAUSE_LEECH_SEED`) and one for the Curse residual, if the pin's line needs one (I have not guessed it; the pin's
  damage line for a condition is checked with ps_trace in phase 2).
- Volatile id for Curse: `DUOFORGE_VOLATILE_CURSE` (12). **Ask.**
- Event kinds: none beyond the existing DAMAGE, HEAL, VOLATILE_START and VOLATILE_END (for Curse), if the lead agrees.

## 5. Recordings (POOL; six members a side; unique items; real genders; marked content; learnsets from `learnsets.ts`)

Legal sets found in `legal_pool.json` (learners and abilities legal): Venusaur (Overgrow, Chlorophyll) and Meganium for Leech
Seed; Gengar (Ghost/Poison, Cursed Body, marked since G27) and Tauros (Normal, Intimidate, Sheer Force) for Curse; Sitrus Berry
is in the pool (`in_duoforge: true`) for the tie. Each of the items, moves and abilities must be marked before the recording
(the manifest is the mark; G84 adds `leechseed` and `curse`, which are not marked on main).

- L1 seed drain: Venusaur seeds a non-Grass foe; the residual drains the holder, the heal goes to Venusaur.
- L2 Grass immunity: Venusaur's Leech Seed on a Grass foe (Meganium), `-immune`, no volatile.
- L3 Substitute: the foe's standing Substitute stops the Leech Seed.
- L4 slot identity: the seeded foe switches out; the Pokemon that enters the slot is drained into Venusaur (getAtSlot).
- L5 Protect: the foe's Protect blocks the Leech Seed.
- L6 Sitrus tie: Sitrus Berry on both sides with identical Venusaur-and-Meganium sets (equal Speed): the each:Update ties draw.
- C1 Ghost Curse: Gengar halves its HP; the foe takes 1/4 residual at order 12, after poison (9) or burn (10) of the same turn.
- C2 second Curse: fails with `-fail` (onTryHit).
- C3 non-Ghost Curse: Tauros's self boost (Speed -1, Attack +1, Defense +1).
- C4 Curse through Substitute: Gengar's Curse reaches the foe behind a Substitute (bypasssub).
- C5 ally target (doubles): a Ghost Curse aimed at an ally goes to a random foe (`randomNormal`).
- Baton Pass copy (if Baton Pass is marked): the seed and the curse are copied to the new Pokemon at the slot.

## 6. Mutants (each with the test that catches it)

- M1 no Grass immunity; M2 Leech Seed passes a Substitute; M3 the drain heal goes to the holder; M4 the drain uses the
  original source instead of the slot; M5 residual order 8 moved to 10; M6 the Substitute absorbs the residual drain;
  M7 Curse blocked by Protect (flag added); M8 Ghost Curse does not halve the user's HP; M9 second Curse not refused;
  M10 non-Ghost Curse boosts with the wrong sign; M11 the Curse residual is 1/8 not 1/4; M12 the view bit not set (LEECH_SEED
  or CURSE); M13 the curse not copied by Baton Pass; M14 the curse not cleared at switch-out.
  Catching tests: the conformance replay of the recorded battles (L1-C5), the state tests (`pool_g84`), and the view
  test (M12), as in G82.

## 7. Refusals (E_UNSUPPORTED)

- Big Root: not in the pool, so no team can hold it; the heal multiplier is not modelled (refuse if it ever appears).
- Leech Seed is `reflectable`: **tell the lead before pushing**, because lane B's Magic Bounce (G57) must handle every marked
  reflectable move (builder rules), and Leech Seed will be marked reflectable.
- A residual order that the engine cannot place (the ambiguity test in `combat/residual_order.h`) keeps its existing refusal.
- Curse's per-position state: if the lead picks option (b), no refusal; if neither, refuse Curse explicitly.

## 8. Decisions (lead, 2026-10-10; phase 2 approved)

1. **Curse state:** `position_flags` bit 7 = `DFI_POSFLAG_CURSED`, per OCCUPANT: cleared when the occupant changes (a switch-out,
   a replacement, a faint), unlike the Healing Wish bit 0, which belongs to the slot. The byte is then full. The invariant and
   the Python state model are extended for it.
2. **Values (the lane A block, assigned by the lead, reported to HauptSession):**
   - `DUOFORGE_VOLATILE_CURSE = 12u`.
   - `DUOFORGE_VOLATILE_LEECH_SEED = 13u`: main has no volatile id for Leech Seed, and its `-start|X|move: Leech Seed` line needs
     one. If an existing representation covered the start line, 13 would be released; none does (the position bit LEECH_SEED
     is state, not a start event).
   - `DUOFORGE_CAUSE_LEECH_SEED = 22u`: the drain, holder plus source, `[from] Leech Seed`.
   - `DUOFORGE_CAUSE_CURSE = 23u`, provisional: the residual line is checked with ps_trace (phase 2). If it is `[from] Curse`, 23
     stays; if an existing cause covers it, 23 is released.
3. **Leech Seed is `reflectable`** (as in the pin, flags 10210). That extends the handled list in `tests/test_pool_g57.c` by one
   entry; no existing entry and no existing Magic Bounce refusal changes. Evidence: one battle in which Magic Bounce reflects
   Leech Seed, if a marked Magic Bounce holder fits.
4. **Baton Pass is not on main** (it is G74, batch 5). So there is no Baton Pass battle in G84. G74 already copies Leech Seed;
   the integrator checks the copy of Curse and Leech Seed after both are merged.

The view bits LEECH_SEED (feature 28) and CURSE (feature 36) are already in encoder 5 (`src/encode/encode.c:81-83`), and
`python/duoforge/features.py` already knows them, so no encoder change is needed for G84 (checked before the first lock job).

Phase 2: recordings L1-L6 (L6 with the Sitrus tie) and C1-C5; mutants M1-M14, each with its catching test and a green
baseline; then the campaign. One lock job at a time, everything in one job; the full run goes through
`gh workflow run ci.yml --ref <branch>`.
