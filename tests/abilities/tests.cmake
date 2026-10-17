# C tests for abilities. Included from tests/ so binary and fixture paths stay unchanged.
# The ability families of decision 0015 (the "-ate" and pinch rules) against a table of the pinned handlers.
duoforge_add_test(NAME duoforge.combat.ability_family SOURCES abilities/test_ability_family.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
duoforge_add_test(NAME duoforge.state.ability_now SOURCES abilities/test_ability_now.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step AC1: Trace in the tail, the event and the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_ac1 SOURCES abilities/test_pool_ac1.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
duoforge_add_test(NAME duoforge.state.pool_g41 SOURCES abilities/test_pool_g41.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G57: Magic Bounce and the Mega Stones Absolite and Sablenite (the reflectable column against the pinned Dex, the marks).
duoforge_add_test(NAME duoforge.state.pool_g57 SOURCES abilities/test_pool_g57.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G61: Sheer Force (the strip and boost predicates on every pool move), Dragonize, Cameruptite and Feraligite: the marks and the named moves.
duoforge_add_test(NAME duoforge.state.pool_g61 SOURCES abilities/test_pool_g61.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45: six abilities of the simple kind (Steadfast, Moxie, Weak Armor, Telepathy, Volt Absorb, Punk Rock): the marks,
# the handler column, and the state after the recorded g45_* battles that show each rule.
duoforge_add_test(NAME duoforge.state.pool_g45 SOURCES abilities/test_pool_g45.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G22: the queued action of a fainted Swift Swim holder, and an Intimidate drop that the cap already took to nothing.
duoforge_add_test(NAME duoforge.state.pool_g22 SOURCES abilities/test_pool_g22.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G53 (decision 0030): Pressure and the foe's derived PP.
duoforge_add_test(NAME duoforge.state.pool_g53 SOURCES abilities/test_pool_g53.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G63 (decision 0015 5bj): the simple Mega abilities Sand Force, Shell Armor, Filter and Stalwart, and their six stones.
duoforge_add_test(NAME duoforge.state.pool_g63 SOURCES abilities/test_pool_g63.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G69 (decision 0015 5bm): Symbiosis, the pass of the item to an ally that has used up its own.
duoforge_add_test(NAME duoforge.state.pool_g69 SOURCES abilities/test_pool_g69.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G65 (decision 0015 5bk): the simple modifier abilities Unaware, Marvel Scale, Water Bubble, Reckless and Super Luck (their
# rows, the recoil and crash facts Reckless reads, and the Trace refusal of Water Bubble onto a burned holder; white-box).
duoforge_add_test(NAME duoforge.state.pool_g65 SOURCES abilities/test_pool_g65.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G73 (decision 0015 5bo): Moody (its residual order, its two samples on one site, the boost with the raised key first; white-box, with
# its recorded battles g73_*, which conformance_pool_data replays).
duoforge_add_test(NAME duoforge.state.pool_g73 SOURCES abilities/test_pool_g73.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G79 (decision 0015 5br): Cloud Nine, the weather suppression of a standing holder (its mark, Mega Sol's refusal under it, and
# the refusal of a Trace copy of it; white-box). The recorded battles g79_* are replayed by duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.state.pool_g79 SOURCES abilities/test_pool_g79.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G81 (decision 0015 entry 5bs, decision 0033): Frisk (the foes' items announced at its holder's switch-in, ITEM_SHOWN in
# the Frisk form), the switch-in order against Intimidate, two Frisk holders, and the fold that ignores the event.
duoforge_add_test(NAME duoforge.state.pool_g81 SOURCES abilities/test_pool_g81.c WHITEBOX TIMEOUT 120 TIER quick AREA abilities)

# Step K2 (decision 0015 5dd, #474): Piercing Drill and Excadrite (the marks, the stone link, the -zbroken event kind, the 0.25 rounding).
duoforge_add_test(NAME duoforge.state.pool_k2 SOURCES abilities/test_pool_k2.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Batch A1b (decision 0015 5dz): Fur Coat, Grass Pelt, Steely Spirit, Plus, Minus, Stakeout, Analytic, Fluffy, Heatproof and Light
# Ball, one damage chain member each: the marks, and each clause taken away before a hit of the covering battles fz_5102_* (the HP
# differs where the pin applies it, and not in its neighbour cases; white-box).
duoforge_add_test(NAME duoforge.state.pool_a1b SOURCES abilities/test_pool_a1b.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
