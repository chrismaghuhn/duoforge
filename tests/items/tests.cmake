# C tests for items. Included from tests/ so binary and fixture paths stay unchanged.
# The item families of decision 0015 (the type booster and the resist berry) against a table of the pinned handlers.
duoforge_add_test(NAME duoforge.combat.item_family SOURCES items/test_item_family.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G16: Knock Off in the tail's item_now, in the ITEM_END event with the cause ITEM_TAKEN, in what reads the held item and in the
# POOL view extension (the member's item_now, bit 11).
duoforge_add_test(NAME duoforge.items.knock_off SOURCES items/test_knock_off.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G29: Trick, Switcheroo, Thief and Covet (the held item as item_now, the received-item and left-item events, the view).
duoforge_add_test(NAME duoforge.items.item_transfer SOURCES items/test_item_transfer.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
# Step G49, the item rows Muscle Band, Wise Glasses and Bright Powder: the marks, the chain orders of Wide Lens and Bright Powder.
duoforge_add_test(NAME duoforge.state.pool_g49 SOURCES items/test_pool_g49.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
duoforge_add_test(NAME duoforge.items.duration_items SOURCES items/test_duration_items.c WHITEBOX TIMEOUT 60 TIER quick AREA items)
