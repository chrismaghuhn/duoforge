# 0030 — Lane B's small overnight values (Pressure)

Status: **accepted** under the owner's night authorization of 2026-10-09. The authorization covers extending schemas where a mechanic needs it; this note was reviewed by the lane B lead, and HauptSession checked the Python side. It sits on the owner's review list for 2026-10-10. Decision number assigned by HauptSession. The model is 0029 (lane A's overnight values).

## 1. Pressure and the foe's derived PP

**The pin.** In `data/abilities.ts`, Pressure's `onDeductPP` returns 1 for a move of a foe. Pressure has no Champions override. `useMoveInner` adds those returns over `pressureTargets` after the move's own PP (`sim/battle-actions.ts:473-484`). The pressure targets are the move's targets (`getMoveTargets`, `sim/pokemon.ts:847-853`), with three exceptions:
- a field move (target `all`) counts every standing foe;
- a `foeSide` move counts none;
- a `mustpressure` move counts every standing foe. In the pool these are Imprison, Spikes, Stealth Rock (`data/moves.ts:17822`) and Toxic Spikes (`:19757`).

Allies never count, and neither does a fainted holder.

**Decision 0007 already named Pressure** as the exception to `DUOFORGE_PP_DERIVED` ("equal to the real value in the closure (no Pressure, no PP items)"). A player can derive the extra PP exactly from public facts:
- the holder's ability, from the open sheet and the `-ability|P|Pressure` line;
- the move line with its target;
- the target class and the board, for spread and field moves.

**Change of meaning (no new field):**
- `DUOFORGE_PP_DERIVED` becomes "pp_max minus the PP the viewer saw spent". It was "minus the uses".
- The engine's foe knowledge (`dfi_knowledge.moves_used`, saturating) counts 1 + the Pressure extra per use.
- The live tracker does the same from the lines. HauptSession builds that side, against the flag below.

## 2. New public value

| Value | Kind | Note |
|---|---|---|
| `DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE` = 0x800 | `duoforge_move_static.flags` bit | the pin's `flags.mustpressure`, written by the generator (`gen_closure.py`) from the pinned data, never hand-listed. The tracker reads it, so that Python holds no move list. |
| `DUOFORGE_PP_DERIVED` | meaning | "pp_max minus the PP the viewer saw spent" (Pressure included) |

**Version:** MINOR at merge. The encoders see no new column: PP columns already read the derived PP.

## 3. Evidence (the Pressure step)

- **Recorded POOL battles:**
  - a single-target move into a Pressure foe;
  - a spread move into two Pressure foes, one of them Protected (it still counts);
  - an ally's move into a Pressure ally (no extra);
  - a field move (Trick Room or a weather) against a Pressure foe;
  - a mustpressure move (Stealth Rock or Spikes);
  - a Pressure holder that has fainted (no extra);
  - the `-ability|Pressure` announcement at switch-in.
- **The foe's derived PP checked in the view tests**, for both players.
- **Mutation checks**, a campaign of about 300 battles, and a 0015 entry.
