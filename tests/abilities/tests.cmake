# C tests for abilities. Included from tests/ so binary and fixture paths stay unchanged.
# The ability families of decision 0015 (the "-ate" and pinch rules) against a table of the pinned handlers.
duoforge_add_test(NAME duoforge.combat.ability_family SOURCES abilities/test_ability_family.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
duoforge_add_test(NAME duoforge.state.ability_now SOURCES abilities/test_ability_now.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step AC1: Trace in the tail, the event and the POOL view extension.
duoforge_add_test(NAME duoforge.abilities.trace SOURCES abilities/test_trace.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
duoforge_add_test(NAME duoforge.abilities.shadow_tag SOURCES abilities/test_shadow_tag.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G57: Magic Bounce and the Mega Stones Absolite and Sablenite (the reflectable column against the pinned Dex, the marks).
duoforge_add_test(NAME duoforge.abilities.magic_bounce SOURCES abilities/test_magic_bounce.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G61: Sheer Force (the strip and boost predicates on every pool move), Dragonize, Cameruptite and Feraligite: the marks and the named moves.
duoforge_add_test(NAME duoforge.abilities.sheer_force SOURCES abilities/test_sheer_force.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): the batch of six simple abilities: their marks and handlers, Mold Breaker unmarked.
duoforge_add_test(NAME duoforge.abilities.simple_ability_rows SOURCES abilities/test_simple_ability_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): Steadfast: the Speed boost after the flinch of g45_steadfast.
duoforge_add_test(NAME duoforge.abilities.steadfast SOURCES abilities/test_steadfast.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): Moxie: the Attack boost by the number of faints.
duoforge_add_test(NAME duoforge.abilities.moxie SOURCES abilities/test_moxie.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): Weak Armor: the Defense drop and Speed boost after a Physical hit.
duoforge_add_test(NAME duoforge.abilities.weak_armor SOURCES abilities/test_weak_armor.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): Telepathy: the ally untouched by Earthquake.
duoforge_add_test(NAME duoforge.abilities.telepathy SOURCES abilities/test_telepathy.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G45 (decision 0015 entry 5ba): Volt Absorb: the absorbed Thunderbolt at full HP and the heal after damage.
duoforge_add_test(NAME duoforge.abilities.volt_absorb SOURCES abilities/test_volt_absorb.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G22 (decision 0015 entry 5o): the tie of a fainted Swift Swim holder's queued action, both POOL kinds.
duoforge_add_test(NAME duoforge.abilities.swift_swim_fainted_holder SOURCES abilities/test_swift_swim_fainted_holder.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G22 (decision 0015 entry 5o): an Intimidate drop the cap already took to nothing against Inner Focus, both POOL kinds.
duoforge_add_test(NAME duoforge.abilities.inner_focus_intimidate_cap SOURCES abilities/test_inner_focus_intimidate_cap.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G53 (decision 0030): Pressure and the foe's derived PP.
duoforge_add_test(NAME duoforge.abilities.pressure SOURCES abilities/test_pressure.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G63 (decision 0015 entry 5bj): the batch of four Mega abilities: their rows and the base abilities they leave unmodelled.
duoforge_add_test(NAME duoforge.abilities.simple_mega_abilities SOURCES abilities/test_simple_mega_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G63 (decision 0015 entry 5bj): Stalwart: no marked move has the scripted target class.
duoforge_add_test(NAME duoforge.abilities.stalwart SOURCES abilities/test_stalwart.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G69 (decision 0015 5bm): Symbiosis, the pass of the item to an ally that has used up its own.
duoforge_add_test(NAME duoforge.abilities.symbiosis SOURCES abilities/test_symbiosis.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G65 (decision 0015 entry 5bk): the batch of five modifier abilities: their marks and handlers, Mold Breaker unmarked.
duoforge_add_test(NAME duoforge.abilities.modifier_abilities SOURCES abilities/test_modifier_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G65 (decision 0015 entry 5bk): Reckless: the recoil and crash rows its clause reads, and the unmodified reads Unaware never meets.
duoforge_add_test(NAME duoforge.abilities.reckless SOURCES abilities/test_reckless.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step G65 (decision 0015 entry 5bk): Trace copying Water Bubble onto a burned holder, refused.
duoforge_add_test(NAME duoforge.abilities.trace_water_bubble SOURCES abilities/test_trace_water_bubble.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G73 (decision 0015 5bo): Moody (its residual order, its two samples on one site, the boost with the raised key first; white-box, with
# its recorded battles g73_*, which conformance_pool_data replays).
duoforge_add_test(NAME duoforge.abilities.moody SOURCES abilities/test_moody.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G79 (decision 0015 5br): Cloud Nine, the weather suppression of a standing holder (its mark, Mega Sol's refusal under it, and
# the refusal of a Trace copy of it; white-box). The recorded battles g79_* are replayed by duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.abilities.cloud_nine SOURCES abilities/test_cloud_nine.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G81 (decision 0015 entry 5bs, decision 0033): Frisk (the foes' items announced at its holder's switch-in, ITEM_SHOWN in
# the Frisk form), the switch-in order against Intimidate, two Frisk holders, and the fold that ignores the event.
duoforge_add_test(NAME duoforge.abilities.frisk SOURCES abilities/test_frisk.c WHITEBOX TIMEOUT 120 TIER quick AREA abilities)

# Step K2 (decision 0015 5dd, #474): Piercing Drill and Excadrite (the marks, the stone link, the -zbroken event kind, the 0.25 rounding).
duoforge_add_test(NAME duoforge.abilities.piercing_drill SOURCES abilities/test_piercing_drill.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step A2a (decision 0015 entry 5dy): the batch of fourteen one-clause abilities: the marks, and each clause at its decisive step against a marked neighbour.
duoforge_add_test(NAME duoforge.abilities.one_clause_abilities SOURCES abilities/test_one_clause_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step A2a (decision 0015 entry 5dy): Illuminate or White Smoke on a Grass holder next to Flower Veil, refused.
duoforge_add_test(NAME duoforge.abilities.flower_veil_drop_refusals SOURCES abilities/test_flower_veil_drop_refusals.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step A2a (decision 0015 entry 5dy): Tangled Feet: the later hit's refusal and the order of the priority -1 accuracy group.
duoforge_add_test(NAME duoforge.abilities.tangled_feet SOURCES abilities/test_tangled_feet.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step A2a (decision 0015 entry 5dy): Life Dew at an ally with Water Absorb, refused before anything changes.
duoforge_add_test(NAME duoforge.abilities.life_dew_water_absorb SOURCES abilities/test_life_dew_water_absorb.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# Step A2a (decision 0015 entry 5dy): Natural Cure's CURE_STATUS event and its digest line.
duoforge_add_test(NAME duoforge.abilities.natural_cure SOURCES abilities/test_natural_cure.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
