<a id="5eb"></a>

# 5eb. Air Balloon pops after the holder's own DamagingHit abilities

- Area: items
- Step: -
- Tests: duoforge.items.air_balloon_pop_order, duoforge.reference.conformance_pool_data

5eb. **Air Balloon pops after the holder's own DamagingHit abilities** (Content lane, issue 639, found by the A2a builder and confirmed by the A2a review; branch chris/fix-639-air-balloon-order; no public value taken). The engine was fixed by decision 0015 entry 5fa (c), PR #628 (issue 546). 5eb adds the evidence for the remaining DamagingHit abilities of issue 639, which 546's single Weak Armor case does not cover. This entry changes no engine code.

**Pin (b2cb775).**
- `findPokemonEventHandlers` gathers a Pokemon's ability handler before its item handler (`sim/battle.ts:1117-1130`).
- For an array of targets, `findEventHandlers` gathers each target's own handlers first, then the attacker's `onSource` handlers, each tagged with the target's index (`:1035-1048`, `:1067-1069`).
- DamagingHit (`sim/battle-actions.ts:1121`, `data/mods/champions/scripts.ts:409`) sorts them with `compareLeftToRightOrder` (`sim/battle.ts:421-426`: order, then priority, then index), a stable sort.
- Air Balloon's `onDamagingHit` (`data/items.ts:197-202`) prints `-enditem`, clears the item, then runs `runEvent('AfterUseItem')`, where an ally's Symbiosis passes its item. It has no order.
- The holder's DamagingHit abilities have no order either: Toxic Debris, Cursed Body, Flame Body, Justified, Weak Armor, Spicy Spray, Static, Poison Point, Gooey, Cute Charm, Stamina and Thermal Exchange.

So for each target, the ability runs first, then the pop, then the attacker's Poison Touch. Every line of the holder's ability prints before `-enditem|holder|Air Balloon`, and so before the Symbiosis pass that the pop triggers.

**The divergence (before 5fa).** Since step G67 (95ab4beb), `dfi_move_body_hit_loop` (`src/combat/turn.c`) popped a standing holder's balloon after Stamina, Thermal Exchange, Poison Point and Gooey, but before Toxic Debris, Cursed Body, Flame Body, Justified, Weak Armor, Spicy Spray, Static and Cute Charm. The draws were in the pin's order (the pop draws nothing), but the protocol lines were not: `-enditem` and the Symbiosis line came before the ability's lines. Nothing refused the combination, so it was a silent event-order divergence.

Since 5fa (c), the standing holder's pop comes after Cute Charm, the last of the holder's own handlers, and before the attacker's Poison Touch, which is the pin's order.

The path for a holder that the hit knocked out already popped after the abilities. On that path the pop also comes after Poison Touch, where the pin has it before. No battle can show this: on a holder that is down, Poison Touch draws its roll and prints nothing.

- **Evidence.** Three battles recorded from the pinned Showdown (`ps_trace.js`, `--check` matches) are committed as pool battles. Each turn 1 shows the order:
  - `f639_balloon_toxic_debris`: Quick Attack on the standing Glimmora (Toxic Debris, Air Balloon). First Toxic Debris's `-activate` and the Toxic Spikes `-sidestart`, then `-enditem`, then Floette-Eternal's Symbiosis pass of Leftovers.
  - `f639_balloon_weak_armor_justified`: Bullet Punch on Armarouge (Weak Armor: `-ability`, `-unboost` def, `-boost` spe, then `-enditem`). Then Night Slash on Lucario (Justified: `-ability`, `-boost` atk, then `-enditem`, then the Symbiosis pass).
  - `f639_balloon_cursed_body`: a draw-taking ability. Bullet Punch on Gengar (Cursed Body, Air Balloon). The roll of 2 out of 10 disables Bullet Punch (`-start|...|Disable|...|[from] ability: Cursed Body`), then `-enditem`, then the Symbiosis pass. The seed was searched: 639a07 is the first seed from 639a03 on whose roll succeeds.

  RESULTS_PLACEHOLDER
- **Open.** Nothing in this entry. The ordered DamagingHit handlers (Rough Skin with order 1, Rocky Helmet with order 2) are unchanged and already in the pin's order. The hit loop implements no other DamagingHit item (Weakness Policy, Absorb Bulb, Cell Battery, Luminous Moss, Snowball, Jaboca or Rowap Berry), so none of them can meet this order.
