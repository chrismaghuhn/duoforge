# 0031 - Haze and the event -clearallboost (step G62, lane A batch 2)

Status: accepted by HauptSession and the lead (2026-10-09, after the proposal of builder H3). Part of decision 0015 (the content expansion), entry 5az.

## Why a new event

Haze prints `-clearallboost` and clears the boosts of every standing active Pokemon. No public event expresses "clear all boosts". The boost events 16 (BOOST) and 17 (UNBOOST) are one stat each, and the reference prints one line for Haze, so seven BOOST lines would not match the protocol. Step G54 dropped Haze for this reason (decision 0015, entry 5at). Decision 0029 kept the small values of the lane; this one is a public event of its own.

## The value

`DUOFORGE_EVENT_CLEAR_ALL_BOOSTS` = 47u, a new public event kind. The name is chosen so that `CLEAR_BOOSTS` stays free for a single-target `-clearboost` (Clear Smog, not marked). The number 47 is the first free value after DRAG (45): 46 belongs to lane B's Illusion (decision 0026). HauptSession confirms the number against the lane B branch at merge.

## Pin

- `data/moves.ts:8156-8172` (Haze): `onHitField` runs `this.add('-clearallboost')`, then `pokemon.clearBoosts()` for each of `this.getAllActive()`. Haze has `accuracy: true`, `target: "all"`, no protect flag, priority 0. The Champions mod (`data/mods/champions/`) has no Haze override.
- `sim/pokemon.ts:1232-1237` (`clearBoosts`): zeroes the boosts in `this.boosts`, which are the seven `BoostID` keys (atk, def, spa, spd, spe, accuracy, evasion). Nothing else: volatiles such as Focus Energy, the stall counters and the substitute stay.
- `sim/battle.ts:1365-1375` (`getAllActive(includeFainted?)`): a fainted Pokemon is skipped unless `includeFainted` is passed. Haze does not pass it, so only the standing actives are cleared. (`sim/pokemon.ts:1508`, `clearVolatile`, resets the boosts on a faint or a switch as well, so a fainted slot is neutral already; the engine follows `getAllActive` all the same.)
- `sim/battle-actions.ts:1265-1270`: a `target: "all"` move runs `onHitField` through `singleEvent('HitField', ...)`; its return is undefined, so the move's hit result is undefined.

## Fields

`kind` 47; `position` NO_POSITION; `other` NO_POSITION; `cause` NONE (the line has no `[from]`); `id`, `id2` 0; `hp`, `hp_max`, `hp_kind`, `hp_flag`, `status` 0; `detail` 0; `amount` 0; `flags` 0. Emitted once, after the MOVE event of Haze (the move line) and before the next action.

## What each side sees

The event is public: both players get the same event with the same content. `-clearallboost` names no Pokemon and no stat.

## View

The engine sets the seven stages of every standing active position to `DFI_STAGE_NEUTRAL` (the biased neutral, 6). Standing means the member is alive (`dfi_alive`), as `getAllActive()` takes it. An empty position and a fainted one do not change. The stages were already public (`src/state/observation.c`, `dfi_view_position`: both sides' stages are in the observation; only confusion turns and the foe's locked target are hidden). So the change of the view is only the stage values; no field is added.

## Encoder

No change. The seven stage columns of each position already exist (`src/encode/encode.c`); their values change.

## Tail

None. No schema change, no layout change, no new tail byte. The move result of Haze is not classified (its hit returns undefined): the engine leaves the result bits at zero, which marks the move result as unclassified for the rest of the turn. Only Stomping Tantrum and Roost read that mark, and they refuse with E_UNSUPPORTED, never guess.

## Live adapter and converter

- `tools/reference/trace_to_c.py` maps the line `|-clearallboost` (no arguments, no attributes; any other form is refused with the rule `protocol-line`) to the event above.
- `python/duoforge_live/lines.py` lists `-clearallboost` in `UNREPRESENTABLE_KINDS`; that Python change belongs to HauptSession (branch `hs/g62-python`), not to this step.
- `python/duoforge/_layout.py` mirrors the event numbers; the new constant is added with the Python side.

## Version

The version is not bumped by the builder. HauptSession collects the value into the next MINOR version at merge (0.45.0).

## Evidence

Four recorded POOL battles under `tests/reference/specs` and `traces` (`g62_haze_*`; every gendered Pokemon has its gender in the paste; each six-member team, four brought). They are replayed by `duoforge.reference.conformance_pool_data` (489 POOL battles, 6994 checks, 0 failures), and their trace state is compared with the engine after every step.

- `g62_haze_boosts_a`: Kingambit (M) Swords Dances on both sides (+2 Attack each); Milotic (F) Hazes, both Kingambit lose the boost. Two `-clearallboost` lines.
- `g62_haze_taunt`: Gardevoir (F) Taunts Primarina (F) on turn 1; Milotic (F) Hazes on turn 2 and Kingambit (M) loses its boost; the Taunt volatile of Primarina survives the Haze and ends at the residual of turn 4 (`-end ... move: Taunt`). A volatile is not a boost.
- `g62_haze_mega`: Gardevoir (F) Mega-evolves (`-mega`) before Milotic (F) Hazes in the same turn (the Mega, order 104, runs before the move, order 200); the Haze clears the Kingambit (M) boost.
- `g62_haze_faint`: a fainted slot on the field when Haze is used. In turn 12 Salamence (M, p2b) faints from Struggle recoil (`|faint|p2b: Salamence`); in the same turn, before its replacement (which is asked only after the turn), Milotic (F, p2a) Hazes; then Kingambit (M, p1b) faints. The fainted slot is skipped: `getAllActive()` (`sim/battle.ts:1365-1375`) takes `includeFainted` as undefined, so a fainted Pokemon is not in the list. A fainted slot has no boosts to lose anyway (`clearVolatile`, `sim/pokemon.ts:1508`, resets them at the faint), so the battle proves the state, not a visible difference.

Mutation and campaign numbers are in the decision entry 5az of decision 0015.

## The queue marker (After You and Quash): what is done

After You and Quash change the order of a queued move (decision 0015 entry 5az). The engine keeps that order in the queue record's `reserve` byte, for move records only (`DFI_QRES_PRIORITIZED` 1: After You, `prioritizeAction` sets `order = 3`, `sim/battle-queue.ts:282-292`; `DFI_QRES_QUASHED` 2: Quash, `action.order = 201`, `data/moves.ts:14454-14475`). The gen-9 re-sort after each action (`sim/battle.ts:2919-2926`, `this.queue.sort()` after `updateSpeed`) reads the order through `dfi_key_of`. The invariant `dfi_queue_record_valid` (`src/state/invariants.c`) and the Python state model (`tools/state_model/state_v3_model.py`, `queue_record_valid`) admit 0, 1 or 2 for a move record. The byte layout does not change: no size change, no public value, no tail field.

- **Done and recorded:** After You (`reserve` 1), in four POOL battles: the ally, the foe, a target that already moved, and a target that switched out (`g62_after_you_*`). All four replay exactly.
- **Quash (`reserve` 2) is marked and recorded**: `g62_quash_protect` (Quash stopped by Protect), `g62_quash_moved` (Quash on a target that already moved, `-fail`, `[still]`), and `g62_quash_pivot` (Quash, then a U-turn pivot: the quashed move stays queued across the PIVOT boundary and runs last). All three replay exactly.
- **The residual shuffle is not Quash's.** In the Quash battles the reference draws `SPEED_TIE` under `field:Residual` for each Protected Pokemon's two end handlers, `H:protect:<pos>:end` and `H:stall:<pos>:end`. Both sides treat that pair as no-order, non-callback duration ends: the engine adds them as `DFI_RES_DURATION` with `DFI_RES_NO_ORDER`, sub-order 2, `callback = false` (`src/combat/turn.c`, the `ends` loop of the residual list), so it never draws; the converter's rule `residual tie of duration counters` (`tools/reference/trace_to_c.py`, the `all(... endswith(':end'))` branch) drops the draw. The same pair is in `g62_after_you_moved`, which already replays. An earlier "residual" diagnosis was wrong: the Quash failures came from the status whitelist in `dfi_run_move_body`, which did not list Quash.
- **The codec and invariants.** The reserve of a move record is 0, 1 or 2 (`tests/test_invariants.c`, `tests/test_codec_mutation.c`, `reserve_round_trip`); 3 is refused, and a non-move record with a reserve is refused. The exhaustive byte sweep of the F5 (PIVOT) fixture gives the model's queue row `{33, 30822}` (the two move records take 1 and 2).
- **Pivot persistence:** the Quash pivot battle carries the marker across the PIVOT boundary (the queue is stored in the state) and runs the quashed move last.
