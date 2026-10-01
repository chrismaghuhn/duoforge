# 0007 — What a player sees: observation v2 and the event log

Status: **accepted** (owner, 2026-10-01: points A and B decided, C follows the principle). Builds on decision `0005` section 6 (information profile prototype) and decision `0006` section 6 (events, knowledge, observation). **Implemented:** step 2, the observation v2 (section 10). The event log (step 3) is next.

## 1. Owner inputs (2026-10-01)

- The observation is **exactly what a human player can see**.
- **Abilities are very important.**
- Design everything a player may see **at once** (state and history together), so that no observation v3 is needed later.

## 2. The principle

A player's view is what a human at the table knows, with perfect memory and full knowledge of the rules:

1. their own team, exactly;
2. the open team sheets of both teams (decision `0005` section 6: species and forme, gender, item, ability, moves, nature; never Stat Points);
3. the battle as the game shows it to this player: every public message, and the exact values that only this player's own screen shows;
4. nothing else.

Anything that follows from 1 to 3 may be handed to the model directly, so it does not have to rebuild the state from the history (for example the remaining turns of Tailwind, or how often a foe has used a move). Anything that is rolled in secret and never shown stays hidden, **for the owner's side as well** (for example how long a Pokémon will sleep or stay confused).

## 3. What changes against the prototype

| Information | Prototype (0005) | Player view (this note) |
|---|---|---|
| Own HP, PP, Stat Points, stats | exact | exact |
| Foe HP | percent and colour flag, as last seen | unchanged |
| Foe PP | unknown | **derived**: maximum PP (open) minus the uses the player saw; equal to the real value in the closure (no Pressure, no PP items). Owner decision A |
| Foe Stat Points and stats | hidden | hidden |
| Status (burn, paralysis, sleep, freeze) | not shown | shown for every seen member, both sides |
| Sleep and freeze turns, confusion turns | not shown | **not shown**, also for the own side: the duration is rolled in secret; the event log shows when it started |
| Stat stages, confusion, charging (Electro Shot) | not shown | shown for the actives of both sides |
| Weather, terrain, Trick Room, Reflect, Light Screen, Tailwind | not shown | shown with remaining turns (start, duration and Light Clay are public) |
| Mega Evolution | side-wide flag | per member (the forme is visible) |
| Item | open on the sheet | sheet item plus "used up" when it was consumed in view |
| Ability | not shown | sheet ability; after Mega Evolution the Mega forme's ability |
| Moves the foe used | not shown | count per move slot |
| Whether the opponent must answer a pause | own flag only | **shown**: a human sees the opponent being asked (Parting Shot, Emergency Exit, a faint). Replaces the proposal of decision `0006` section 11 point 7. Owner decision B |
| Brought set and pick order of the foe | private until seen | unchanged |
| RNG, the opponent's choice before it runs | hidden | hidden |

## 4. Observation v2 (state at a decision)

- **Per member, both sides:** species and current forme, gender, nature, ability (current), item and whether it is used up, the four moves, Mega capability and whether it has Mega Evolved; location (active, bench, not brought, not yet seen); HP (own exact, foe percent and flag); PP (own exact, foe derived per point A); status; observed move uses (foe).
- **Per active position:** occupant, stat stages, confused or not, charging and the locked move and target, whether Fake Out is still usable (first move action after entering), the Protect chain length.
- **Field and sides:** weather, terrain and Trick Room with remaining turns; per side Reflect, Light Screen, Tailwind with remaining turns; Mega used; which sides must answer the current request.
- Fixed size, no pointers, like the prototype; a new layout version (observation v2), byte-for-byte stable.

## 5. Abilities

- **On the sheet:** every member's ability is open from team preview on; the observation shows it, and after Mega Evolution the Mega forme's ability.
- **When it acts:** the event log carries an ability event whenever the game shows one. In the closure (Showdown at the pin):

| Ability | What the game shows |
|---|---|
| Intimidate | own line, then the Attack drops |
| Drizzle, Drought, Grassy Surge | the weather or terrain start, tagged with the ability |
| Emergency Exit | own line, then the switch |
| Armor Tail | the blocked move, tagged with the ability |
| Lightning Rod | the redirect, the absorbed move and the Special Attack rise |
| Flash Fire | the absorbed move and the boost starting |
| Good as Gold | the blocked status move |
| Stamina, Competitive, Contrary | the stat changes, tagged with the ability where the game tags them |
| Prankster | nothing of its own; a Dark target's immunity shows as a failed move |
| Blaze, No Guard, Tough Claws | nothing (silent modifiers); known from the sheet only |

The exact lines per ability are fixed during implementation against the pinned protocol, one test per ability.

## 6. The event log (history since the last decision)

- **Per player.** Each step returns the events this player may see, in the order the game shows them. The owner's events carry exact HP; the opponent's carry the percent display.
- **Kinds:** turn start; switch in and out (with the reason: chosen, Parting Shot, Emergency Exit, replacement); move used (user, move, target, and "locked" for the second Electro Shot turn); cannot move (paralysis, sleep, freeze, flinch, confusion, and the self-hit); miss, immune, failed, blocked by Protect or by an ability; critical hit; effectiveness; damage and heal (with the source: move, recoil, drain, Life Orb, burn, Leftovers, Grassy Terrain, Sitrus Berry); status start and cure; stat stage change; confusion start and end; ability shown (section 5); item used or shown; weather, terrain, Trick Room and side condition start and end; Mega Evolution; faint; the result.
- **Events are outputs, not state** (decision `0006` section 6): staged during the step; a too-small caller buffer returns `E_CAPACITY` with the required count and commits nothing (decision `0005` section 7).
- **One source for knowledge:** the per-player knowledge in the state is updated only from the events that player sees; the observation reads the own state plus this knowledge, never the opponent's state.

## 7. Evidence

- **Information equivalence:** the paired tests (synthetic fixtures and the closure gate on real states) are extended to every new field and to the events: states that differ only in hidden information give the same observation and the same events for that player.
- **Against the reference:** Showdown sends each player its own copy of every split line. The converter rebuilds both players' views from the recorded traces (as it already does for the HP display) and compares the events and the new observation fields at every step of all recorded battles.
- **Oracle:** the Python model of the state gets the new layout and the information rules (structure only, no game rules).
- **Negative controls** for every rule that hides something, for example the own sleep turns.

## 8. Steps

1. **This note** (owner review).
2. **Observation v2:** the layout, the fields of section 4, the paired tests, the oracle, the comparison with the traces.
3. **Event log:** the API, the kinds of section 6 with the abilities of section 5, the knowledge folded from events, the comparison with the traces.
4. **Benchmark API** follows (separate task), so it measures the final observation and event cost.

State v3 is expected to suffice: the remaining turns, statuses and volatiles exist already, and the hidden rolled durations stay where they are. If a field is missing, it is added once, before step 2.

## 9. Owner decisions (2026-10-01)

- **A. Foe PP: shown** as the derived value (a human can count the uses).
- **B. The opponent's request: shown.** A human sees it at once: switches run first in a turn, before Mega Evolution and before the moves in priority order (from the highest priority down, speed within one priority), so a switch, chosen or forced, is visible the moment it happens.
- **C. Own hidden durations: hidden**, as proposed: the game never shows sleep or confusion turns, so they stay hidden on the owner's side as well (follows from the principle in section 2).

## 10. Observation v2 as built (step 2)

- **Layout:** 544 bytes (was 320): a 16-byte header with the turn, weather, terrain and Trick Room and their remaining turns; per side six 36-byte member views, two 16-byte position views, occupancy, Mega used, the own pick order, who must answer, and the side conditions with remaining turns. Public constants `DUOFORGE_AILMENT_*`, `DUOFORGE_WEATHER_*`, `DUOFORGE_TERRAIN_*`, `DUOFORGE_PP_DERIVED`, `DUOFORGE_MOVE_SLOT_NONE`. Library version 0.5.0.
- **Sources:** own side from the state; both sheets; public facts of the battle; for the opponent the viewer's knowledge (seen mask, last HP display, items seen used up, Mega Evolutions seen, move uses seen). The opponent's exact HP and PP, bench and pick order, sealed commands, its charged move's target and the RNG are not read. Until the event log exists (step 3), the knowledge is still updated by the engine directly, as in decision `0006`.
- **State:** unchanged (state v3), as expected in section 8.
- **Evidence:**
  - The Python oracle builds the same bytes for all 15 fixtures and both players.
  - The paired tests on real states (closure gate) cover the hidden sleep and freeze turns and confusion turns on both sides and the foe's charged target, and show a changed field turn or foe stat stage. Planted leaks of each are reported by their pair.
  - The conformance test compares both players' observations with every step of the 58 recorded battles: the derived foe PP equals Showdown's PP, and statuses, Mega formes, items used up, stat stages, confusion, charged moves, field and side conditions match. Planted errors (foe PP at its maximum, foe status hidden) turn it red.


## 11. The event log as built (step 3)

- **API:** `duoforge_battle_step_events(ctx, battle, bundle, out_result, buffers)` takes one `duoforge_event_buffer` per player and otherwise works like `duoforge_battle_step`, which now runs the same code without events. An event is 20 bytes: kind, position, other position, cause, `id`, `id2`, HP (`hp`, `hp_max`, `hp_kind`, `hp_flag`, `status`), `detail`, `amount`, `flags`. Kinds `DUOFORGE_EVENT_*` 1 to 37, causes `DUOFORGE_CAUSE_*`, flags `DUOFORGE_EVENT_FLAG_*`, field and side codes. Library version 0.6.0.
- **Errors, atomically:** a NULL buffer array is `E_NULL_ARGUMENT`; a buffer without storage but with capacity is `E_INVALID_ARGUMENT`; a buffer too small for the step is `E_CAPACITY` with the required count written to both counts, checked before the commit, so the battle, the result and the RNG stay as they were. `DUOFORGE_MAX_EVENTS` (512) bounds a step; a step beyond it is `E_INVARIANT`, never a truncated log. The events are staged on the stack (no heap).
- **One event per line** of the protocol the game shows that player (the public copy of a split line for the opponent, the own copy for the owner), in protocol order. Attributes that amend an earlier line are folded into its event: `[still]` and `[notarget]` (the move event loses its target), `[miss]`, `[spread]` with the slots still hit as a mask in `amount`, and Lightning Rod's redirection (the move event's target). `-supereffective` and `-resisted` carry the Champions magnitude, min(|typeMod|, 2), in `amount`. `[silent]` lines, hints and layout lines are not events.
- **Per player:** the engine records each event once, exactly; each player's copy shows the opponent's HP as the percent display with its colour flag (`dfi_event_project`, the same display as the knowledge), the own HP exactly. Every other field is the same for both players.
- **Spread moves:** the reference labels a spread move's line with a random main target and then replaces it with `[spread]`; the engine shows no target (the converter drops that draw, as before). No closure spread move can stop between its move line and the end of its hit steps (Armor Tail needs positive priority, which no closure spread move has), so the label is never shown.
- **Order that only the log shows.** Ties whose outcome was invisible before decide the order of lines now, and the engine draws them like the reference: `eachEvent` sorts the active Pokémon by speed for Update (Sitrus Berry) and TerrainChange (Grassy Seed), and a tie between two holders draws (the converter keeps exactly those draws); when both sides' same side condition runs out in one residual, a draw orders the two end lines. For the latter the converter states the outcome (which side's line comes first): the reference's order before the shuffle depends on the insertion order of each side's conditions, which the state does not hold. To keep the draws aligned, the engine also runs the Update of the `beforeTurn` action and the two Updates that end the hit loop of a status move that did something. Decision `0006` section 4.7 called these sorts unobservable; for the order of lines that no longer holds.
- **Engine errors found and fixed:** `Battle.boost` now caps every change of one boost against the stages before the first change (`getCappedBoost`); before, Competitive's rise could change the cap of a later stat of the same boost (Parting Shot on a Competitive holder at -6 Special Attack). A fainted Pokémon is not active, so no `ModifySpe` handler runs for it: its queued action and its replacement sort by its raw Speed, without Tailwind or paralysis (found by the mirror battle below).
- **Not yet (step 3c):** the knowledge is still updated by the engine directly, not folded from the events.
- **Evidence:**
  - The conformance test compares every event of both players, field by field, at every step of 60 recorded battles: 18,808 events of all 37 kinds. Two new battles cover the new ties: `s14_mirror_condition_ends` (Tailwind, Reflect and Light Screen of both sides end together, five times) and `s14_seed_tie` (two Grassy Seed holders of the same Speed when Grassy Surge starts the terrain).
  - `duoforge.combat.turn` checks the API: the three failures leave state, result and counts as they were (except the required count), an exact buffer takes the step, and the state equals the same step without events; in 40 random battles with every status, each step's events are checked on both players (same lines, HP as the owner and the opponent see it, the last event starting the next turn or giving the result).
  - Negative controls E1 to E14 (opponent sees exact HP, wrong positions, faints announced late, ties not drawn, a fainted Pokémon keeping Tailwind, missing lines of a change of 0, `[miss]` on a spread move, `E_CAPACITY` without count or with a commit, Struggle's line missing, missing Updates, the old boost cap) each turn a named test red.
