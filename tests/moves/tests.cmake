# C tests for moves. Included from tests/ so binary and fixture paths stay unchanged.
# The rules that several moves share (step G10): the first-turn moves, power by weight, the thaw and heal columns.
duoforge_add_test(NAME duoforge.combat.move_rules SOURCES moves/test_move_rules.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G8: Throat Chop and Psychic Noise's Heal Block in the tail, the request and the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_g8 SOURCES moves/test_pool_g8.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G11: Soak in the tail's soak type, in what reads the types, in the TYPE_CHANGE event and in the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_g11 SOURCES moves/test_pool_g11.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G9: Encore in the tail, the queue, the request, the residual and the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_g9 SOURCES moves/test_pool_g9.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G17: the recharge moves in the tail, the request (the recharge slot), the queue and the POOL view extension.
duoforge_add_test(NAME duoforge.state.pool_g17 SOURCES moves/test_pool_g17.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G19: Coaching and Glaive Rush: the tail, the view extension, and the recorded battles.
duoforge_add_test(NAME duoforge.state.pool_g19 SOURCES moves/test_pool_g19.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G30: Rage Powder (the Follow Me bit told apart by the occupant's last move, the view extension's RAGE_POWDER bit 39), the
# powder immunity, Psychic Fangs, Solar Beam, Flame Body, Clear Body, Hospitality and Overcoat, on their recorded battles.
duoforge_add_test(NAME duoforge.state.pool_g26 SOURCES moves/test_pool_g26.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g48 SOURCES moves/test_pool_g48.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g50 SOURCES moves/test_pool_g50.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g60 SOURCES moves/test_pool_g60.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g74 SOURCES moves/test_pool_g74.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g70 SOURCES moves/test_pool_g70.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_k3 SOURCES moves/test_pool_k3.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g58 SOURCES moves/test_pool_g58.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G72b: Alluring Voice (the stats-raised position flag) and Dragon Cheer (the crit stage), the PIVOT refusal of the public
# record (decision 0015 5ce); the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.state.pool_g72b SOURCES moves/test_pool_g72b.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g76 SOURCES moves/test_pool_g76.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Step G78 (decision 0015 5ch, decision 0043): Dragon Darts, the split of its two hits; the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.state.pool_g78 SOURCES moves/test_pool_g78.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Step G88 (decision 0046): Lash Out and Assurance (the LOWERED and HURT position flags, bits 5 and 6), the PIVOT refusal with
# DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY (64); the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.state.pool_g88 SOURCES moves/test_pool_g88.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g86 SOURCES moves/test_pool_g86.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g92 SOURCES moves/test_pool_g92.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g90 SOURCES moves/test_pool_g90.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g80 SOURCES moves/test_pool_g80.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)

# Step G42: Roost and Stomping Tantrum: the move result classes (this and last) at every boundary of the g42 battles, the Roost
# volatile (the pivot boundary inside its turn), the view bits (40 supported, 41 not), the unclassified refusal.
duoforge_add_test(NAME duoforge.state.pool_g42 SOURCES moves/test_pool_g42.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step K1 (#476, decision 0015 entry 5dc): Temper Flare shares Stomping Tantrum's callback; the result classes of its user.
duoforge_add_test(NAME duoforge.state.pool_k1 SOURCES moves/test_pool_k1.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g44 SOURCES moves/test_pool_g44.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g54 SOURCES moves/test_pool_g54.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G56: lockedmove (Outrage, Thrash, Petal Dance): the count, its refusals and the information safety of its length.
duoforge_add_test(NAME duoforge.state.pool_g56 SOURCES moves/test_pool_g56.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g64 SOURCES moves/test_pool_g64.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g68 SOURCES moves/test_pool_g68.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g62 SOURCES moves/test_pool_g62.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g38 SOURCES moves/test_pool_g38.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G31: Taunt and Yawn in the tail's taunt_turns and yawn_turns, the request, the cant line, the residual and the POOL view
# extension (the position's TAUNT and YAWN bits, 14 and 25).
duoforge_add_test(NAME duoforge.state.pool_g31 SOURCES moves/test_pool_g31.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G71 (decision 0034, decision 0015 5bn): Attract's source bytes, the state check, the public bit, the from-view refusal and the
# clear of the holder's byte (white-box; the volatile's draws wait for G73's site).
duoforge_add_test(NAME duoforge.state.pool_g71 SOURCES moves/test_pool_g71.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)

# Step G87 (decision 0080): Attract's source is public: the observation's source bits (volatiles2 12-13), the from-view worlds that copy it,
# the refusal of an inconsistent view byte, the pair invariant, and the corpus of every recorded pool battle (every decision point with an
# infatuated occupant, both players' views built into worlds and compared with the engine).
duoforge_add_test(NAME duoforge.state.pool_g87 SOURCES moves/test_pool_g87.c WHITEBOX LIBS duoforge_batch TIMEOUT 600 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.state.pool_g82 SOURCES moves/test_pool_g82.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
