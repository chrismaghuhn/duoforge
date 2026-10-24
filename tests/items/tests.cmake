# C tests for items. Included from tests/ so binary and fixture paths stay unchanged.
# The item families of decision 0015 (the type booster and the resist berry) against a table of the pinned handlers.
duoforge_add_test(NAME duoforge.combat.item_family SOURCES items/test_item_family.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G16: Knock Off in the tail's item_now, in the ITEM_END event with the cause ITEM_TAKEN, in what reads the held item and in the
# POOL view extension (the member's item_now, bit 11).
duoforge_add_test(NAME duoforge.items.knock_off SOURCES items/test_knock_off.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G29: Trick, Switcheroo, Thief and Covet (the held item as item_now, the received-item and left-item events, the view).
duoforge_add_test(NAME duoforge.items.item_transfer SOURCES items/test_item_transfer.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
duoforge_add_test(NAME duoforge.items.duration_items SOURCES items/test_duration_items.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G49 (decision 0015 entry 5ao): the batch of Muscle Band, Wise Glasses and Bright Powder: their marks and recorded battles.
duoforge_add_test(NAME duoforge.items.power_and_accuracy_items SOURCES items/test_power_and_accuracy_items.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G49 (decision 0015 entry 5ao): Bright Powder: the two orders of its priority -2 group with Wide Lens, and the two refusals.
duoforge_add_test(NAME duoforge.items.bright_powder SOURCES items/test_bright_powder.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# 5eb (-): Air Balloon pops after the holder's own DamagingHit abilities. Scaffolded by tools/new_mechanic.py.
duoforge_add_test(NAME duoforge.items.air_balloon_pop_order SOURCES items/test_air_balloon_pop_order.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# 5eg (I2): The cure berries, Oran Berry and the isBerry column. Scaffolded by tools/new_mechanic.py.
duoforge_add_test(NAME duoforge.items.berry_family SOURCES items/test_berry_family.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
