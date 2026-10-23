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
# step G45 of the content expansion (decision 0015 entry 5ba), six abilities of the simple kind as one batch: Steadfast, Moxie, Weak Armor, Telepathy, ...
duoforge_add_test(NAME duoforge.abilities.simple_ability_rows SOURCES abilities/test_simple_ability_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G45 of the content expansion (decision 0015 entry 5ba), Steadfast: replays g45_steadfast to the turn where the flinch of Machamp (a Fake Out in ...
duoforge_add_test(NAME duoforge.abilities.steadfast SOURCES abilities/test_steadfast.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G45 of the content expansion (decision 0015 entry 5ba), Moxie: replays g45_moxie_double, where Krookodile's Earthquake knocks out two foes at ...
duoforge_add_test(NAME duoforge.abilities.moxie SOURCES abilities/test_moxie.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G45 of the content expansion (decision 0015 entry 5ba), Weak Armor: replays g45_weak_armor, where one Physical hit (Garchomp's Earthquake) ...
duoforge_add_test(NAME duoforge.abilities.weak_armor SOURCES abilities/test_weak_armor.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G45 of the content expansion (decision 0015 entry 5ba), Telepathy: replays g45_telepathy, where the Earthquake of Garchomp does not reach ...
duoforge_add_test(NAME duoforge.abilities.telepathy SOURCES abilities/test_telepathy.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G45 of the content expansion (decision 0015 entry 5ba), Volt Absorb: replays g45_volt_absorb, where a Thunderbolt at full HP is absorbed (no ...
duoforge_add_test(NAME duoforge.abilities.volt_absorb SOURCES abilities/test_volt_absorb.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G22 of the content expansion (decision 0015 entry 5o), the queued action of a fainted Swift Swim holder, under both POOL kinds. In ...
duoforge_add_test(NAME duoforge.abilities.swift_swim_fainted_holder SOURCES abilities/test_swift_swim_fainted_holder.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G22 of the content expansion (decision 0015 entry 5o), an Intimidate drop that the cap already took to nothing, under both POOL kinds. ...
duoforge_add_test(NAME duoforge.abilities.inner_focus_intimidate_cap SOURCES abilities/test_inner_focus_intimidate_cap.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G53 (decision 0030): Pressure and the foe's derived PP.
duoforge_add_test(NAME duoforge.abilities.pressure SOURCES abilities/test_pressure.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# step G63 of the content expansion (decision 0015 entry 5bj), the simple Mega abilities as one batch: Sand Force (BasePower 5325/4096 for a Rock, ...
duoforge_add_test(NAME duoforge.abilities.simple_mega_abilities SOURCES abilities/test_simple_mega_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G63 of the content expansion (decision 0015 entry 5bj), the one fact that Stalwart's redirection rule depends on: no marked move has the ...
duoforge_add_test(NAME duoforge.abilities.stalwart SOURCES abilities/test_stalwart.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# Step G69 (decision 0015 5bm): Symbiosis, the pass of the item to an ally that has used up its own.
duoforge_add_test(NAME duoforge.abilities.symbiosis SOURCES abilities/test_symbiosis.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)

# step G65 of the content expansion (decision 0015 entry 5bk), the simple modifier abilities as one batch, POOL build: Unaware (onAnyModifyBoost), ...
duoforge_add_test(NAME duoforge.abilities.modifier_abilities SOURCES abilities/test_modifier_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G65 of the content expansion (decision 0015 entry 5bk), the rows that Reckless's recoil clause relies on: Struggle has no recoil (its ...
duoforge_add_test(NAME duoforge.abilities.reckless SOURCES abilities/test_reckless.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# step G65 of the content expansion (decision 0015 entry 5bk), Trace copying Water Bubble onto a burned holder is refused (E_UNSUPPORTED) and the ...
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

# batch A2a of the Champions-100 track (decision 0015 entry 5dy), fourteen abilities with one clause each at an existing hook, as one batch. The ...
duoforge_add_test(NAME duoforge.abilities.one_clause_abilities SOURCES abilities/test_one_clause_abilities.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# batch A2a of the Champions-100 track (decision 0015 entry 5dy), the refusals that no campaign battle reaches: an Illuminate or White Smoke holder ...
duoforge_add_test(NAME duoforge.abilities.flower_veil_drop_refusals SOURCES abilities/test_flower_veil_drop_refusals.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# batch A2a of the Champions-100 track (decision 0015 entry 5dy), Tangled
duoforge_add_test(NAME duoforge.abilities.tangled_feet SOURCES abilities/test_tangled_feet.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# batch A2a of the Champions-100 track (decision 0015 entry 5dy), Life Dew (a Water heal move of the user and its ally) at an ally with Water Absorb: ...
duoforge_add_test(NAME duoforge.abilities.life_dew_water_absorb SOURCES abilities/test_life_dew_water_absorb.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
# batch A2a of the Champions-100 track (decision 0015 entry 5dy), Natural Cure's CURE_STATUS has cause ABILITY and id2 Natural Cure + 1 (a2a_cover_b ...
duoforge_add_test(NAME duoforge.abilities.natural_cure SOURCES abilities/test_natural_cure.c WHITEBOX TIMEOUT 60 TIER quick AREA abilities)
