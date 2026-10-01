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

- **Layout:** 736 bytes (was 320): a 16-byte header with the turn, weather, terrain and Trick Room and their remaining turns; per side six 52-byte member views (the open sheet; for the own side also the current stats and the stat points, 0 for the foe), two 16-byte position views (an empty position has neutral stages, `DUOFORGE_MOVE_SLOT_NONE` and `DUOFORGE_TARGET_NONE`; the foe's locked target is `DUOFORGE_TARGET_NONE`; `protecting` while Protect is up this turn), occupancy, Mega used, the own pick order, who must answer, and the side conditions with remaining turns. Public constants `DUOFORGE_AILMENT_*`, `DUOFORGE_WEATHER_*`, `DUOFORGE_TERRAIN_*`, `DUOFORGE_PP_DERIVED`, `DUOFORGE_MOVE_SLOT_NONE`. Library version 0.5.0.
- **Sources:** own side from the state; both sheets; public facts of the battle; for the opponent the viewer's knowledge (seen mask, last HP display, items seen used up, Mega Evolutions seen, move uses seen). The opponent's exact HP and PP, bench and pick order, sealed commands, its charged move's target and the RNG are not read. Until the event log exists (step 3), the knowledge is still updated by the engine directly, as in decision `0006`. The foe's status and ability are read from its state: both are public whenever they change (statuses are announced when they start and end; the ability changes only by a Mega Evolution, which is always shown, and an invariant ties `is_mega` to the revealed fact).
- **State:** unchanged (state v3), as expected in section 8.
- **Evidence:**
  - The Python oracle builds the same bytes for all 15 fixtures and both players.
  - The paired tests on real states (closure gate) cover the hidden sleep and freeze turns and confusion turns on both sides and the foe's charged target, and show a changed field turn or foe stat stage. Planted leaks of each are reported by their pair.
  - The conformance test compares both players' observations with every step of the recorded battles: the derived foe PP equals Showdown's PP, and statuses, abilities (the Mega forme's after Mega Evolution), Mega formes, items used up, stat stages, confusion, the locked slot and the own locked target, a charged move, Protect, Flash Fire and the stall counter (as Showdown's volatiles), field and side conditions match; at TERMINAL only the stat stages. Planted errors (foe PP at its maximum, foe status hidden) turn it red. The closure gate fails if any kind of pair never ran.

