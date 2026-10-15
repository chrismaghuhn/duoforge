# Mold Breaker sites at b246b8d1 (src/combat/turn.c, src/combat/field/terrain.h, src/state/view.c)

Reads of one of the 44 marked breakable abilities (a `dfi_ability(` call or a `1u + DFI_ABILITY_x` code comparison).
S = through the helper (holder may be a target, an ally or a third party); = holder is the actor or there is no move; U = Update/Start time; N = no holder read.

counts: = 9, N 3, S 65, U 10, total 87

| file:line | function | ability | class | note |
|---|---|---|---|---|
| src/combat/turn.c:254 | dfi_flower_veil_holder | FLOWERVEIL | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:291 | dfi_powder_immune | OVERCOAT | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:912 | dfi_boost | CONTRARY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:937 | dfi_boost | GUARDDOG | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:953 | dfi_boost | INNERFOCUS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:955 | dfi_boost | OBLIVIOUS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:970 | dfi_boost | HYPERCUTTER | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:992 | dfi_boost | KEENEYE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1000 | dfi_boost | BIGPECKS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1013 | dfi_boost | CLEARBODY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1033 | dfi_boost | MIRRORARMOR | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1034 | dfi_boost | MIRRORARMOR | N | effect.id2 compare (the Mirror Armor reflect marker), not a holder read |
| src/combat/turn.c:1543 | dfi_get_damage | SHELLARMOR | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1593 | dfi_get_damage | UNAWARE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1596 | dfi_get_damage | UNAWARE | = | Unaware of the attacker a |
| src/combat/turn.c:1624 | dfi_get_damage | MARVELSCALE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1800 | dfi_get_damage | PUNKROCK | = | Punk Rock of the attacker a (boost) |
| src/combat/turn.c:1859 | dfi_get_damage | FLASHFIRE | = | Flash Fire of the attacker a (boost) |
| src/combat/turn.c:1887 | dfi_get_damage | THICKFAT | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:1894 | dfi_get_damage | WATERBUBBLE | = | Water Bubble of the attacker a |
| src/combat/turn.c:1897 | dfi_get_damage | WATERBUBBLE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2040 | dfi_get_damage | SOLIDROCK | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2046 | dfi_get_damage | MULTISCALE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2056 | dfi_get_damage | AURAGUARD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2064 | dfi_get_damage | PUNKROCK | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2076 | dfi_get_damage | FRIENDGUARD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2291 | dfi_try_status | MAGMAARMOR | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2305 | dfi_try_status | THERMALEXCHANGE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2319 | dfi_try_status | WATERBUBBLE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2332 | dfi_try_status | LIMBER | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2354 | dfi_try_status | LEAFGUARD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2749 | dfi_add_volatile | INNERFOCUS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:2983 | dfi_bug_bite | STICKYHOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:3078 | dfi_knock_off | STICKYHOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:3345 | dfi_thief | STICKYHOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:3600 | dfi_sturdy_saves | STURDY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:3732 | dfi_attract_update | OBLIVIOUS | U | Oblivious Update cure (attract_update): runs at the Update after the action, no suppressor then |
| src/combat/turn.c:3754 | dfi_update | OBLIVIOUS | U | Oblivious Update order (bearers): same |
| src/combat/turn.c:3819 | dfi_sand_immune | SANDRUSH | = | Overcoat/Sand Rush/Sand Veil in the residual: no move, no actor |
| src/combat/turn.c:3820 | dfi_sand_immune | SANDVEIL | = | Sand Veil in the residual: no move, no actor |
| src/combat/turn.c:4517 | dfi_attract_start | OBLIVIOUS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:4679 | dfi_run_perish_song | GOODASGOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:4687 | dfi_run_perish_song | SOUNDPROOF | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5289 | dfi_yawn | LEAFGUARD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5396 | dfi_run_helping_hand | GOODASGOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5435 | dfi_run_coaching | GOODASGOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5876 | dfi_accuracy_check | UNAWARE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5877 | dfi_accuracy_check | UNAWARE | = | Unaware of the user |
| src/combat/turn.c:5881 | dfi_accuracy_check | KEENEYE | = | Keen Eye of the user |
| src/combat/turn.c:5899 | dfi_accuracy_check | SNOWCLOAK | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:5900 | dfi_accuracy_check | SANDVEIL | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6164 | dfi_run_curse | GOODASGOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6305 | dfi_run_belly_drum | CONTRARY | = | Contrary of the user (Belly Drum, self) |
| src/combat/turn.c:6485 | dfi_drag_blocked | SUCTIONCUPS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6687 | dfi_try_hit_abilities | FLASHFIRE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6700 | dfi_try_hit_abilities | LIGHTNINGROD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6707 | dfi_try_hit_abilities | GOODASGOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6710 | dfi_try_hit_abilities | STURDY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6715 | dfi_try_hit_abilities | BULLETPROOF | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6722 | dfi_try_hit_abilities | VOLTABSORB | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6733 | dfi_try_hit_abilities | TELEPATHY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6741 | dfi_try_hit_abilities | OBLIVIOUS | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6747 | dfi_try_hit_abilities | OVERCOAT | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6753 | dfi_try_hit_abilities | SOUNDPROOF | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6786 | dfi_try_hit_abilities | LEVITATE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6856 | dfi_accuracy_targets | SNOWCLOAK | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6857 | dfi_accuracy_targets | SANDVEIL | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:6953 | dfi_status_effects | MIRRORARMOR | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:7211 | dfi_bounce | ARMORTAIL | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:7682 | dfi_run_move_body | LIGHTNINGROD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:7788 | dfi_run_move_body | ARMORTAIL | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:7789 | dfi_run_move_body | QUEENLYMAJESTY | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:7869 | dfi_run_move_body | MAGICBOUNCE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:8216 | dfi_run_move_body | MAGICBOUNCE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:8244 | dfi_run_move_body | STICKYHOLD | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:9083 | dfi_run_move_body | THERMALEXCHANGE | S | holder is a target, ally or third party; the helper compares holder and user |
| src/combat/turn.c:9991 | dfi_trace | LIMBER | U | Trace group (entry, no action) |
| src/combat/turn.c:9996 | dfi_trace | WATERBUBBLE | U | Trace group |
| src/combat/turn.c:10001 | dfi_trace | MAGMAARMOR | U | Trace group |
| src/combat/turn.c:10006 | dfi_trace | OBLIVIOUS | U | Trace group |
| src/combat/turn.c:10116 | dfi_skill_swap_update_due | LIMBER | U | skill_swap_update_due Limber (refused already) |
| src/combat/turn.c:10119 | dfi_skill_swap_update_due | THERMALEXCHANGE | U | skill_swap_update_due Thermal Exchange |
| src/combat/turn.c:10122 | dfi_skill_swap_update_due | OBLIVIOUS | U | skill_swap_update_due Oblivious |
| src/combat/turn.c:10125 | dfi_skill_swap_update_due | MAGMAARMOR | U | skill_swap_update_due Magma Armor |
| src/combat/field/terrain.h:19 | dfi_grounded_test | LEVITATE | S | Levitate in isGrounded: by the caller, holder vs actor decided by the helper |
| src/state/view.c:811 | mr_absorbs | LIGHTNINGROD | N | view classification of an id (knowledge of an absorb), no holder read |
| src/state/view.c:812 | mr_absorbs | WATERABSORB | N | view classification of an id (knowledge of an absorb), no holder read |

## dfi_grounded callers (Levitate through isGrounded, pin sim/pokemon.ts:2156)

| file:line | function | ability | class | note |
|---|---|---|---|---|
| src/combat/turn.c:471 | dfi_move_priority | LEVITATE (via dfi_grounded, holder m)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:493 | dfi_effective_target_class | LEVITATE (via dfi_grounded, holder m)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:562 | dfi_move_type_now | LEVITATE (via dfi_grounded, holder m)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:1697 | dfi_get_damage | LEVITATE (via dfi_grounded, holder d)) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:1702 | dfi_get_damage | LEVITATE (via dfi_grounded, holder a)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:1804 | dfi_get_damage | LEVITATE (via dfi_grounded, holder a)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:1810 | dfi_get_damage | LEVITATE (via dfi_grounded, holder d) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:1817 | dfi_get_damage | LEVITATE (via dfi_grounded, holder a) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:1826 | dfi_get_damage | LEVITATE (via dfi_grounded, holder a) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:1830 | dfi_get_damage | LEVITATE (via dfi_grounded, holder d) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:1837 | dfi_get_damage | LEVITATE (via dfi_grounded, holder a)) | = | holder is the actor (attacker/user) |
| src/combat/turn.c:2379 | dfi_try_status | LEVITATE (via dfi_grounded, holder m) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:2689 | dfi_hazards_enter | LEVITATE (via dfi_grounded, holder m)) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:2696 | dfi_hazards_enter | LEVITATE (via dfi_grounded, holder m)) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:2713 | dfi_hazards_enter | LEVITATE (via dfi_grounded, holder m)) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:2764 | dfi_add_volatile | LEVITATE (via dfi_grounded, holder m) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:2793 | dfi_confuse_primary | LEVITATE (via dfi_grounded, holder m) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:5314 | dfi_yawn | LEVITATE (via dfi_grounded, holder tm) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:6604 | dfi_protect_targets | LEVITATE (via dfi_grounded, holder dfi_at(b, t)) | S | holder is the target or an entering Pokemon; the helper compares holder and user (hazards: the drag window) |
| src/combat/turn.c:11212 | dfi_residual_events_run | LEVITATE (via dfi_grounded, holder m) | = | residual heal: no move, no suppressor |

grounded callers: {'=': 9, 'S': 11}, total 20
