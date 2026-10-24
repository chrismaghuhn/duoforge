# C tests for forms. Included from tests/ so binary and fixture paths stay unchanged.
# Step G23-A: the Mega of a member is found from (base forme, stone): every Mega forme of the pool, the second Megas included.
duoforge_add_test(NAME duoforge.state.mega_by_stone SOURCES forms/test_mega_by_stone.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
duoforge_add_test(NAME duoforge.forms.stance_change SOURCES forms/test_stance_change.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA forms)

# The Mega Stones and the Megas they lead to, one section per batch (G43, G51, G57, G59, G63, G75, Mega batch 2).
duoforge_add_test(NAME duoforge.forms.mega_stones SOURCES forms/test_mega_stones.c WHITEBOX TIMEOUT 60 TIER quick AREA forms)
