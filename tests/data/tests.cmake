# C tests for data. Included from tests/ so binary and fixture paths stay unchanged.
duoforge_add_test(NAME duoforge.unit.sha256 SOURCES data/test_sha256.c WHITEBOX)

duoforge_add_test(NAME duoforge.state.context SOURCES data/test_context.c)
duoforge_add_test(NAME duoforge.state.closure_setup SOURCES data/test_closure_setup.c WHITEBOX)

# M3: generated closure tables and Champions formulas (decision 0006).
duoforge_add_test(NAME duoforge.data.closure_tables SOURCES data/test_closure_tables.c WHITEBOX)
# Team C (decision 0009): the extended tables, whose prefix is the closure.
duoforge_add_test(NAME duoforge.data.extended_tables SOURCES data/test_extended_tables.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.team_c_setup SOURCES data/test_team_c_setup.c WHITEBOX)
# POOL (decision 0015): the pool tables, whose prefix is the extended tables, with their family
# columns, and the POOL kinds.
duoforge_add_test(NAME duoforge.data.pool_tables SOURCES data/test_pool_tables.c WHITEBOX)
duoforge_add_test(NAME duoforge.state.pool_setup SOURCES data/test_pool_setup.c WHITEBOX TIMEOUT 60)
# The data query API (duoforge_data_*): names and legality per kind, differential against the setup.
duoforge_add_test(NAME duoforge.data.api SOURCES data/test_data_api.c WHITEBOX TIMEOUT 120)
# Decision 0020: the static read API (forme, move, item, ability, nature, type effect) against the generated tables.
duoforge_add_test(NAME duoforge.data.static SOURCES data/test_data_static.c WHITEBOX TIMEOUT 120)
# The POOL state tail (decision 0015 section 7): schema "v3 + pool tail rev 1", present under the POOL kinds only.
duoforge_add_test(NAME duoforge.state.pool_tail SOURCES data/test_pool_tail.c WHITEBOX TIMEOUT 120)
