# 0041 - Skill Swap (G70): the ability swap, its events and its refusals

Status: **draft** (H11, lane A batch 4). Pending the lead's answers Q1 (the ABILITY event fields under cause MOVE) and Q2 (ally targets, OTS information safety). Builds on 0015 (the POOL kinds, the support gate, the step entry 5cd), 0018 (the view extension: `ability_now`, AC1) and 0028 (the transformed state: setAbility's Start and End). No new public value: the ability event is the existing kind 34 under the existing cause MOVE (1).

## Problem

Skill Swap (`data/moves.ts:16590-16606`) exchanges the two holders' abilities. The engine's ability state (AC1, the tail's `ability_now`) holds one copy from Trace. A swap changes two holders at once, and every rule that starts or ends with an ability has to run as the pin runs it, in the pin's order, with the pin's lines.

## The pin (b2cb775, no Champions override of `skillswap` or `skillSwap`)

- **The move:** flags protect, mirror, bypasssub, allyanim, metronome; accuracy true; no `onTryHit`; `onHit` returns `this.skillSwap(source, target)`. No `reflectable` flag: Magic Bounce does not bounce it.
- **`skillSwap`** (`sim/battle.ts:1311-1345`), in order:
  1. No effect and no line when either side is fainted or Dynamax, or either ability has `failskillswap`. The gen 5 same-ability refusal does not apply in gen 9: two equal abilities swap and run their Start and End.
  2. `SetAbility` runs on the target (carrying the source's ability), then on the source (carrying the target's). Ability Shield on the holder blocks it (`data/items.ts:11-17`). Ability Shield is not marked.
  3. The line (below).
  4. `End` of the source's old ability, then `End` of the target's old ability.
  5. The swap, with new ability states and `volatileStaleness` reset.
  6. `Start` of the ability now on the target, then `Start` of the one now on the source (gen > 3).
- **A refused swap** returns false from `onHit`, so the move prints `-fail|SOURCE` with `[still]` on the move line (`sim/battle-actions.ts:1303-1309`).
- **The foe line:** `-activate|SOURCE|Skill Swap|TARGET_ABILITY|SOURCE_ABILITY|[of] TARGET` (`battle.ts:1318-1321`). Public, in both streams. The first name is the ability the source now has. **The pin prints the literal `Skill Swap`, with no `move:` prefix.** Decision 0018 section 6.1 wrote `move: Skill Swap`; corrected below.
- **The ally line:** `-activate|SOURCE|Skill Swap|||[of] TARGET`, with empty names, plus the public `-hint|Skill Swap does not announce the abilities of the Pokémon when used between allies.` (`battle.ts:1316-1320`, `hint` at `:3071`).

## Failure rules

- `failskillswap` among the marked abilities: none on main (checked over the 92 manifest abilities against `data/abilities.ts`; the Champions overrides of Emergency Exit and Regenerator add none).
- **Stance Change has it** (`data/abilities.ts:4531`). A swap with an Aegislash holder on either side takes the `-fail` path. Its battle comes with G66 (H9).
- Ability Shield on either holder: `-block|HOLDER|item: Ability Shield`, then the `-fail` path. Not marked on main; the rule is written so that a later mark is still correct.

## The ability state after a swap

- Both holders' tail `ability_now` (AC1) are set to the new ability + 1, and **stored as 0 when the new ability equals the holder's sheet ability**, so the view's `ability_changed` keeps its meaning. A swap back to the sheet ability clears the copy.
- The switch-out reset is unchanged: the pin resets `ability` to `baseAbility` (`sim/pokemon.ts:1522`), which is the existing reset of `ability_now` (`identity.c:46`).
- Every rule of the turn code reads the ability through `dfi_ability_code` (`turn.c:332-354`), so the copy is seen everywhere. Verified: Regenerator's `onSwitchOut` (`turn.c:7629`) and Speed Boost's `onResidual` (`turn.c:8267-8276`) read the current ability and need no change.

## Start and End of the marked abilities

| Ability | Hook at the pin | What the swap does in the engine |
|---|---|---|
| Flash Fire | `onEnd` removes the `flashfire` volatile, which prints `-end|X|ability: Flash Fire|[silent]` (`data/abilities.ts:1351-1353`, `1373-1375`) | End: clear `DFI_VOL_FLASH_FIRE` on the holder, no line. Start: none. A swap into it adds no volatile (the volatile is added only by a Fire hit). |
| Unburden | `onAfterUseItem` / `onTakeItem` add the `unburden` volatile; `onEnd` removes it (`data/abilities.ts:5235-5245`) | End: clear `DFI_VOL_UNBURDEN`. Start: none. A swap into it adds no boost, because the boost is the volatile's and the volatile is added only by an item event. |
| Unnerve | `onStart` announces `-ability|X|Unnerve`; `onEnd` clears `unnerved` (`:5258-5275`) | End: nothing (`dfi_unnerved` derives it from the holder's ability). Start: the announce line, as the entry path (`dfi_entry_ability`). |
| Intimidate | `onStart`: `-ability|X|Intimidate|boost`, the foes' Attack drop, the Substitute `-immune` (`data/abilities.ts:2193-2212`) | Start: `dfi_entry_ability`, the existing code, with the holder's foes. |
| Weather setters (Drizzle, Drought, Sand Stream, Snow Warning) | `onStart` sets the weather; the same weather prints nothing | Start: `dfi_entry_ability`. |
| Surges (Electric, Grassy, Psychic) | `onStart` sets the terrain; the same terrain prints nothing | Start: `dfi_entry_ability`. |
| Fairy Aura, Pressure | `onStart` announce lines (`data/abilities.ts:3437-3449`) | Start: `dfi_entry_ability`. |
| Trace | `onStart` sets `seek` and runs `Update` at once: a random copy of a standing foe's ability (`data/abilities.ts:5118-5148`) | Start: `dfi_trace`, with the existing draw `DFI_SITE_TRACE`. No candidate is `E_UNSUPPORTED`, as today. |
| Hospitality | `onStart` heals the ally by a quarter (`data/abilities.ts`, the G30 row) | Start: `dfi_hospitality`, called explicitly (it is not in `dfi_has_entry`). |
| Imposter | `onSwitchIn` only (`data/abilities.ts:2115-2117`); the pin says it does not activate on a Skill Swap | Nothing. |
| Speed Boost | `onResidual` (`:4453-4465`) | Nothing: the swap leaves `activeTurns` as it is. |
| Regenerator (Champions: `inherit`, `onSwitchOut` with `[silent]` heal) | `onSwitchOut` | Nothing: it reads the current ability at the switch-out. |

## Update refusals

Abilities with an `onUpdate` run at each `Update`, which the pin calls after a move (`sim/battle-actions.ts:967`, `1003`). A swap that gives one of them to a Pokemon in the matching state cannot be modelled without the Update line, so it is refused with `E_UNSUPPORTED`, as `dfi_trace` refuses a Trace copy today:

- **Limber** (`data/abilities.ts:2368-2374`): the holder is paralysed.
- **Thermal Exchange**: the holder is burned.
- **Oblivious** (`data/abilities.ts:3008-3040`, `onUpdate` removes Taunt): the holder is taunted.

A swap that gives the ability to a Pokemon without the state is fine. Swapping them away is fine.

## Information (decided: Q2, lead and HauptSession)

Ally swaps are modelled, not refused. Both partners' current abilities are public under OTS: the sheet is public, and every earlier change of an ability has a public line. The swap itself is deterministic. So:
- A foe swap is public: both ability names are on the line.
- An ally swap prints no names. The C state and observation carry the new abilities for both viewers, from the same two ABILITY events, in the line's order. The converter maps `-activate|SRC|Skill Swap|||[of] TGT` (and the `-hint`) from the known abilities. No rule in Python.
- A named refusal (`E_UNSUPPORTED`) only where a holder's current ability is NOT known to the foe. In the pool that is a possible Illusion (lane B's ILLUSION_POSSIBLE). The checked list of other ways an ability can be hidden from the foe is in the phase 2 report; anything found there is refused by name, never guessed.

## Event fields (open: Q1)

The lead's preferred option C: the ABILITY event (34) with **cause MOVE** (1), `id2` = the move id (Skill Swap), and `id` = the new ability + 1. Two events per swap, in the line's order: position = the source, `other` = the target, id = the target's ability + 1; then position = the target, `other` = the source, id = the source's ability + 1. The ABILITY comment in `include/duoforge/duoforge.h` gets "with cause MOVE: id = the new ability + 1, id2 = the move" as a documentation change; no new number. The own-side Pressure timeline (`src/combat/events.c:126-131`) reads both causes: it recomputes both holders' Pressure flags from the events of the step. Not coded until the lead forwards the answer.

## Evidence plan

Recorded POOL battles with genders stated, six members a side, unique items, marked rows only: foe swaps with Intimidate and Pressure (the Start lines on the new holder, both `End`s); a same-weather Drizzle that prints nothing; Trace given to a holder (one draw); Hospitality; Flash Fire and Unburden ends with no boost on the swap into Unburden; the Limber, Thermal Exchange and Oblivious refusals; a failed swap with Stance Change (after G66); a swap through a Substitute (bypasssub); the ally variant as the lead decides. Mutants: the End and Start order, the Start on the wrong side, the `ability_now` normalisation, the event's position and `other`, the Unburden flag set on the swap-in, the Flash Fire volatile not cleared, Hospitality not called, the refusals removed. Campaign: about 300 battles through `diff_driver.py random`.

## 0018 section 6.1 correction

Decision 0018 section 6.1 wrote the Skill Swap line as `|-activate|POKEMON|move: Skill Swap|...|[of] SRC`. The pin prints `Skill Swap` without the `move:` prefix (`sim/battle.ts:1318-1321`). The row is corrected in this step, and the recorded battle confirms the form in phase 2.

## Implementation status (H11, phase 2)

- **Handler id 91**, `SKILL_SWAP` (the next free id on main; the integrator renumbers batch rows in merge order); UNMODELED becomes 92. The move is marked (`DFI_MOVE_SKILLSWAP` 405, flags3 bypasssub bit 2). The pool tables are regenerated (`--pool --check` ok, canonical sha256 `b42817bb3bc9eba17bba87e179469c6ec4a613eba58415055bc716cd9b0bde0b`); the POOL fingerprints are KP `fb97a0e4640c5e519408a68ed67fee06289b710447235f134110401cef0674ef` and KPD `8fbee3f1381a6fe754f3a0c7845dcf72796157dd568da3e6ddb9a5165018b50d`.
- **Engine** (`src/combat/turn.c`, `dfi_skill_swap`) follows the order above; the own-side Pressure timeline reads the MOVE-caused events (`src/combat/events.c`). Dispatch in the hit loop; the generic status path and the unknown-special gate exclude the handler.
- **Ally pair modelled** (Q2). The converter follows each holder's current ability (`tools/reference/trace_to_c.py`, `swap_partners`). A foe line names both abilities; an ally line names none and takes the pair the converter followed.
- **Known gap, Mega Evolved holder in an ally pair:** the converter refuses it explicitly (`ConversionError`, `skill-swap-ally`). The Mega forme's ability is in the forme data, which the converter does not read. No recorded battle hits it.
- **What can hide an ability from the foe** (Q2, the list the lead asked for): an Illusion that is still possible (lane B; refused by name once Illusion is marked). Nothing else on main: the sheet is public under OTS, every change has a public line (Trace, Mega, Skill Swap), Transform copies a public sheet (decision 0028), and Ability Shield is not marked.
- **Trace draw through a swap cannot arise in the pool:** a Trace holder's ability is replaced by its copy at its entry, so no holder carries Trace after the entry, and a swap cannot hand Trace to anyone. The code path (`dfi_entry_ability` to `dfi_trace`) is kept for the entry only. Not tested by a battle.
- **Recorded battles** (`tests/reference/specs/g70_skillswap_*.json`, six, genders stated, six members a side, no items): ally swap with a copied Contrary (`ally_trace`), ally swap that gives Intimidate to the ally and copies Pressure (`ally_intimidate`), a foe swap that gives Intimidate (`foe_intimidate`), a swap of two Drizzle and Pressure holders where the rain already stands (`ally_drizzle`), a Protect (`protect`), and two Flash Fire holders where Flash Fire ends silently (`flashfire_end`).
- **Not recorded**: Hospitality, Unburden, the Limber, Thermal Exchange and Oblivious refusals (a refusal is not a passing battle; the C test covers its state), the Stance Change failure (after G66).
