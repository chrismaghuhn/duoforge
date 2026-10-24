# C tests for moves. Included from tests/ so binary and fixture paths stay unchanged.
# The rules that several moves share (step G10): the first-turn moves, power by weight, the thaw and heal columns.
duoforge_add_test(NAME duoforge.combat.move_rules SOURCES moves/test_move_rules.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G8: Throat Chop and Psychic Noise's Heal Block in the tail, the request and the POOL view extension.
duoforge_add_test(NAME duoforge.moves.throat_chop SOURCES moves/test_throat_chop.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.heal_block SOURCES moves/test_heal_block.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.switch_clears_volatiles SOURCES moves/test_switch_clears_volatiles.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.throat_chop_heal_block_view SOURCES moves/test_throat_chop_heal_block_view.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G11: Soak in the tail's soak type, in what reads the types, in the TYPE_CHANGE event and in the POOL view extension.
duoforge_add_test(NAME duoforge.moves.soak SOURCES moves/test_soak.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G9: Encore in the tail, the queue, the request, the residual and the POOL view extension.
duoforge_add_test(NAME duoforge.moves.encore SOURCES moves/test_encore.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G17: the recharge moves in the tail, the request (the recharge slot), the queue and the POOL view extension.
duoforge_add_test(NAME duoforge.moves.recharge SOURCES moves/test_recharge.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G19: Coaching and Glaive Rush: the tail, the view extension, and the recorded battles.
duoforge_add_test(NAME duoforge.moves.glaive_rush_tail_view SOURCES moves/test_glaive_rush_tail_view.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G30: Rage Powder (the Follow Me bit told apart by the occupant's last move, the view extension's RAGE_POWDER bit 39), the
# powder immunity, Psychic Fangs, Solar Beam, Flame Body, Clear Body, Hospitality and Overcoat, on their recorded battles.
duoforge_add_test(NAME duoforge.moves.perish_song SOURCES moves/test_perish_song.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.hits_taken_hazard_moves SOURCES moves/test_hits_taken_hazard_moves.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.rage_fist SOURCES moves/test_rage_fist.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.double_shock SOURCES moves/test_double_shock.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.substitute SOURCES moves/test_substitute.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.baton_pass SOURCES moves/test_baton_pass.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.skill_swap SOURCES moves/test_skill_swap.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.speed_swap SOURCES moves/test_speed_swap.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.phantom_force SOURCES moves/test_phantom_force.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G72b: Alluring Voice (the stats-raised position flag) and Dragon Cheer (the crit stage), the PIVOT refusal of the public
# record (decision 0015 5ce); the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.moves.alluring_voice_dragon_cheer_rows SOURCES moves/test_alluring_voice_dragon_cheer_rows.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.alluring_voice SOURCES moves/test_alluring_voice.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.dragon_cheer SOURCES moves/test_dragon_cheer.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.destiny_bond_final_gambit_rows SOURCES moves/test_destiny_bond_final_gambit_rows.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.destiny_bond SOURCES moves/test_destiny_bond.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.final_gambit SOURCES moves/test_final_gambit.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Step G78 (decision 0015 5ch, decision 0043): Dragon Darts, the split of its two hits; the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.moves.dragon_darts SOURCES moves/test_dragon_darts.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Step G88 (decision 0046): Lash Out and Assurance (the LOWERED and HURT position flags, bits 5 and 6), the PIVOT refusal with
# DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY (64); the recorded battles are duoforge.reference.conformance_pool_data.
duoforge_add_test(NAME duoforge.moves.turn_history_moves SOURCES moves/test_turn_history_moves.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.power_move_rows SOURCES moves/test_power_move_rows.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.heavy_slam SOURCES moves/test_heavy_slam.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.hard_press SOURCES moves/test_hard_press.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.confusion_moves SOURCES moves/test_confusion_moves.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.partial_trap SOURCES moves/test_partial_trap.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.psych_up_howl_ally_switch_rows SOURCES moves/test_psych_up_howl_ally_switch_rows.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.ally_switch SOURCES moves/test_ally_switch.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Decision 0083 section 7: Last Respects after Revival Blessing is refused (o2_last_respects_revival continued).
duoforge_add_test(NAME duoforge.state.last_respects_revival SOURCES moves/test_last_respects_revival.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)

# Step G42: Roost and Stomping Tantrum: the move result classes (this and last) at every boundary of the g42 battles, the Roost
# volatile (the pivot boundary inside its turn), the view bits (40 supported, 41 not), the unclassified refusal.
duoforge_add_test(NAME duoforge.moves.move_result_roost SOURCES moves/test_move_result_roost.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step K1 (#476, decision 0015 entry 5dc): Temper Flare shares Stomping Tantrum's callback; the result classes of its user.
duoforge_add_test(NAME duoforge.moves.temper_flare SOURCES moves/test_temper_flare.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.simple_move_rows SOURCES moves/test_simple_move_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.power_trip SOURCES moves/test_power_trip.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.tri_attack SOURCES moves/test_tri_attack.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.moves_batch_rows SOURCES moves/test_moves_batch_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.multi_hit_count SOURCES moves/test_multi_hit_count.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.quick_guard_view SOURCES moves/test_quick_guard_view.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G56: lockedmove (Outrage, Thrash, Petal Dance): the count, its refusals and the information safety of its length.
duoforge_add_test(NAME duoforge.moves.outrage_lock SOURCES moves/test_outrage_lock.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.lockedmove_sleep SOURCES moves/test_lockedmove_sleep.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.moves_batch_2_rows SOURCES moves/test_moves_batch_2_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.moves_batch_4_rows SOURCES moves/test_moves_batch_4_rows.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.haze SOURCES moves/test_haze.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.imprison SOURCES moves/test_imprison.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G31: Taunt and Yawn in the tail's taunt_turns and yawn_turns, the request, the cant line, the residual and the POOL view
# extension (the position's TAUNT and YAWN bits, 14 and 25).
duoforge_add_test(NAME duoforge.moves.taunt_yawn_tail_view SOURCES moves/test_taunt_yawn_tail_view.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
# Step G71 (decision 0034, decision 0015 5bn): Attract's source bytes, the state check, the public bit, the from-view refusal and the
# clear of the holder's byte (white-box; the volatile's draws wait for G73's site).
duoforge_add_test(NAME duoforge.moves.attract SOURCES moves/test_attract.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)

# Step G87 (decision 0080): Attract's source is public: the observation's source bits (volatiles2 12-13), the from-view worlds that copy it,
# the refusal of an inconsistent view byte, the pair invariant, and the corpus of every recorded pool battle (every decision point with an
# infatuated occupant, both players' views built into worlds and compared with the engine).
duoforge_add_test(NAME duoforge.moves.attract_source_view SOURCES moves/test_attract_source_view.c WHITEBOX LIBS duoforge_batch TIMEOUT 600 TIER quick AREA moves)
duoforge_add_test(NAME duoforge.moves.healing_wish SOURCES moves/test_healing_wish.c WHITEBOX LIBS duoforge_batch TIMEOUT 60 TIER quick AREA moves)
# Step G30: Rage Powder's RAGE_POWDER bit of the view extension (decision 0018, bit 39), told apart from Follow Me.
duoforge_add_test(NAME duoforge.moves.rage_powder_view SOURCES moves/test_rage_powder_view.c WHITEBOX TIMEOUT 60 TIER quick AREA moves)
