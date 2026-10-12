# C tests for mechanics. Included from tests/ so binary and fixture paths stay unchanged.

duoforge_add_test(NAME duoforge.unit.arith SOURCES mechanics/test_arith.c WHITEBOX TIER quick AREA mechanics)
duoforge_add_test(NAME duoforge.unit.modifier SOURCES mechanics/test_modifier.c WHITEBOX TIER quick AREA mechanics)
duoforge_add_test(NAME duoforge.state.knowledge SOURCES mechanics/test_knowledge.c WHITEBOX TIER quick AREA mechanics)
# The POOL player-view extension at tier 0 (decision 0018): layout, constants, the query, all zero.
duoforge_add_test(NAME duoforge.request.observation_ext SOURCES mechanics/test_observation_ext.c WHITEBOX TIER quick AREA mechanics)
# Step G7: Wide Guard in the tail, the stall counter and the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_g7 SOURCES mechanics/test_pool_g7.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Sandstorm and Snowscape (the weather step): the view of the weather battles against the protocol lines, the sources of
# immunity that stay unmarked, the weather values as state.
duoforge_add_test(NAME duoforge.state.pool_weather SOURCES mechanics/test_pool_weather.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
duoforge_add_test(NAME duoforge.state.pool_terrain SOURCES mechanics/test_pool_terrain.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Step G20: Aurora Veil in the tail's side turns, in the damage modifier, in the residual and in the POOL view extension
# (the side's aurora_veil_turns, bit 3).
duoforge_add_test(NAME duoforge.state.pool_g20 SOURCES mechanics/test_pool_g20.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Step G36: Toxic and the badly poisoned status: the tail's toxic_stage, the member's status Tox, the view's ailment value.
duoforge_add_test(NAME duoforge.state.pool_g36 SOURCES mechanics/test_pool_g36.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Step G37: the entry hazards (Stealth Rock, Spikes, Toxic Spikes, Sticky Web): the tail layers of each side and the view fields.
duoforge_add_test(NAME duoforge.state.pool_g37 SOURCES mechanics/test_pool_g37.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Step G72: Yawn on a charging (semi-invulnerable) target under Electric Terrain: the volatile starts on the locked turn, the
# residual sleep is not refused while the charge is up, and a Yawn without No Guard misses (decision 0015 item 5ce).
duoforge_add_test(NAME duoforge.state.pool_g72 SOURCES mechanics/test_pool_g72.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
# Step G20, Spiky Shield: the protect_kind of the position (POOL tail rev 3), the state round trip, the volatile.
duoforge_add_test(NAME duoforge.state.pool_g20_protect SOURCES mechanics/test_pool_g20_protect.c WHITEBOX TIMEOUT 60 TIER quick AREA mechanics)
