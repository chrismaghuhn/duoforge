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

Recorded POOL battles under `tests/reference/specs` (`g62_haze_*`, genders stated), with the engine checks of `duoforge.state.pool_g62` and the conformance of `duoforge.reference.conformance_pool_data`. Each battle shows the events and the stages after the step, against the pinned reference. The battles include: boosts on both sides (cleared on all positions), a volatile that survives (a Taunt or another volatile the pool supports, which is not a boost), a fainted slot on the field (no change to it), and a Haze in the same turn as a switch or a Mega.
