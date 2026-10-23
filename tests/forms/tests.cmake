# C tests for forms. Included from tests/ so binary and fixture paths stay unchanged.
# Step G23-A: the Mega of a member is found from (base forme, stone): every Mega forme of the pool, the second Megas included.
duoforge_add_test(NAME duoforge.state.mega_by_stone SOURCES forms/test_mega_by_stone.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
# Mega batch 2: Swampertite, Metagrossite, Lucarionite Z and Aura Guard: the marks, the Mega of each pair, Aura Guard in the
# commutation test and the refusal of the ModifyDamage chain.
duoforge_add_test(NAME duoforge.state.pool_mega2 SOURCES forms/test_pool_mega2.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
duoforge_add_test(NAME duoforge.forms.stance_change SOURCES forms/test_stance_change.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA forms)
# Step G43 (Mega batch 3): ten Mega Stones marked with no new rule (Dragoninite, Glimmoranite, Blazikenite, Absolite Z,
# Raichunite X, Lopunnite, Alakazite, Meowsticite, Scizorite, Galladite): the marks, the Mega of each pair, the setup and the API.
duoforge_add_test(NAME duoforge.state.pool_g43 SOURCES forms/test_pool_g43.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
duoforge_add_test(NAME duoforge.state.pool_g59 SOURCES forms/test_pool_g59.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)

# Step G51 (Mega batch 4): ten Mega Stones marked with no new rule, Keen Eye and Big Pecks as engine rows (turn.c), the marks, the
# Mega of each pair, the setup, the API, and the Keen Eye ignoreEvasion check (white-box).
duoforge_add_test(NAME duoforge.state.pool_g51 SOURCES forms/test_pool_g51.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
# the Mega Stones and the Megas they lead to. Step G63 of the content expansion (decision 0015 entry 5bj): Garchompite, Steelixite, Slowbronite, ...
duoforge_add_test(NAME duoforge.forms.mega_stones SOURCES forms/test_mega_stones.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
