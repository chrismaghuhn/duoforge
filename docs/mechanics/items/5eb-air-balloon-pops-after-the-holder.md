<a id="5eb"></a>

# 5eb. Air Balloon pops after the holder's own DamagingHit abilities

- Area: items
- Step: -
- Tests: duoforge.items.air_balloon_pop_order, duoforge.reference.conformance_pool_data, duoforge.reference.conformance_pool

5eb. **Air Balloon pops after the holder's own DamagingHit abilities** (Content lane, issue 639, found by the A2a builder and confirmed by the A2a review; branch chris/fix-639-air-balloon-order; no public value taken). Pin (b2cb775): `findPokemonEventHandlers` gathers a Pokemon's ability handler before its item handler (`sim/battle.ts:1117-1130`); for an array of targets `findEventHandlers` gathers each target's own handlers, then the attacker's `onSource` handlers, with the target's index (`:1035-1048`, `:1067-1069`); DamagingHit (`sim/battle-actions.ts:1121`, `data/mods/champions/scripts.ts:409`) sorts them with `compareLeftToRightOrder` (`sim/battle.ts:421-426`: order, priority, index), a stable sort. Air Balloon's `onDamagingHit` (`data/items.ts:197-202`: `-enditem`, the item cleared, then `runEvent('AfterUseItem')`, where an ally's Symbiosis passes its item) has no order, and neither do the holder's DamagingHit abilities (Toxic Debris, Cursed Body, Flame Body, Justified, Weak Armor, Spicy Spray, Static, Poison Point, Gooey, Cute Charm, Stamina, Thermal Exchange). So per target the ability runs first, then the pop, then the attacker's Poison Touch. Every line of the holder's ability prints before `-enditem|holder|Air Balloon`, and so before the Symbiosis pass that the pop triggers.

**The divergence on main.** For a standing holder, `dfi_move_body_hit_loop` (`src/combat/turn.c`) popped the balloon after Stamina, Thermal Exchange, Poison Point and Gooey but before Toxic Debris, Cursed Body, Flame Body, Justified, Weak Armor, Spicy Spray, Static and Cute Charm. The draws were in the pin's order (the pop draws nothing), but the protocol lines were not: `-enditem` and the Symbiosis line came before the ability's lines. Nothing refused the combination, so this was a silent event-order divergence. It dates from step G67 (95ab4beb). The path for a holder that the hit knocked out already popped after the abilities and kept its order. On that path the pop also comes after Poison Touch, where the pin has it before, but nothing can show it: Poison Touch on a holder that is down draws its roll and prints nothing.

**The fix.** One clause moved: the standing holder's pop now comes after Cute Charm, the last of the holder's own handlers, and before the attacker's Poison Touch. Like the down path, it comes after all of the holder's abilities; unlike it, it comes before Poison Touch, as in the pin. No state, no public value and no draw changes.

- **Evidence.** Three battles recorded from the pinned Showdown (`ps_trace.js`, `--check` matches), committed as pool battles:
  - `f639_balloon_toxic_debris`: Quick Attack on the standing Glimmora (Toxic Debris, Air Balloon). `-activate` Toxic Debris and `-sidestart` Toxic Spikes, then `-enditem`, then Floette-Eternal's Symbiosis pass of Leftovers.
  - `f639_balloon_weak_armor_justified`: Bullet Punch on Armarouge (Weak Armor: `-ability`, `-unboost` def, `-boost` spe, then `-enditem`), and Night Slash on Lucario (Justified: `-ability`, `-boost` atk, then `-enditem`, then the Symbiosis pass).
  - `f639_balloon_cursed_body`: a draw-taking ability. Bullet Punch on Gengar (Cursed Body, Air Balloon); the roll 2 of 10 disables Bullet Punch (`-start|...|Disable|...|[from] ability: Cursed Body`), then `-enditem`, then the Symbiosis pass. The seed was searched: the first of 639a03 to 639a07 whose roll succeeds.

  RESULTS_PLACEHOLDER
- **Open.** Nothing in this entry. The order of the ordered DamagingHit handlers (Rough Skin 1, Rocky Helmet 2) is unchanged and already the pin's. No other DamagingHit item (Weakness Policy, Absorb Bulb, Cell Battery, Luminous Moss, Snowball, Jaboca or Rowap Berry) is implemented in the hit loop, so none of them can meet this order.
