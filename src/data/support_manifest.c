#include <duoforge/duoforge.h>

#include "data/support_manifest.h"

/* Step 2 (turn core): turn order with speed ties, single-target and spread
 * damage, accuracy, critical hits, the random factor, STAB, the type chart,
 * stat stages, self-boosting moves, secondary stat changes, PP, Struggle and
 * Protect with its stall counter. Every move marked here uses nothing else.
 * Step 3: voluntary switches, fainting, replacements and the win rule.
 * Step 4: burn, paralysis, sleep and freeze (Champions variants), flinch
 * and confusion, from primary and secondary effects; Hurricane is taken
 * ahead of step 10 because it is the only move that confuses.
 * Step 5: the entry abilities Drizzle, Grassy Surge and Intimidate, rain,
 * Grassy Terrain's heal and the ordered residual phase (Drought and sun are
 * written and become reachable with Mega Evolution, step 11).
 * Step 6: Tailwind, Reflect, Light Screen and Trick Room.
 * Step 7: the reactive abilities of the base formes (Stamina, Competitive,
 * Flash Fire, Lightning Rod, Good as Gold, Armor Tail, Prankster, Blaze);
 * Contrary, No Guard and Tough Claws belong to Mega formes (step 11).
 * Step 8: Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Mystic Water and
 * Light Clay (Miracle Seed comes with the first Grass move, step 9).
 * Step 9: recoil (Wood Hammer, Brave Bird), drain (Bitter Blade, Leech
 * Life), self-drops (Close Combat, Make It Rain), Miracle Seed, Grassy
 * Terrain's boost for Grass moves and Flash Fire's boost.
 * Step 10a: Weather Ball, Grass Knot, Grassy Glide, Fake Out (disabled in
 * the request after the first move action, Champions).
 * Step 10b: Electro Shot (charge, rain, the locked move in the request).
 * Step 11: Mega Evolution (the megaEvo action, the forme's stats and
 * ability, once per side) with Drought, Contrary, No Guard, Tough Claws and
 * the four Mega Stones.
 * Step 12: Parting Shot and Emergency Exit with PIVOT boundaries (an
 * Emergency Exit in the residual phase returns E_UNSUPPORTED: decision 0006
 * section 4.12).
 *
 * Team C (decision 0009; the extended ids, reachable under the TEAM_C kinds):
 * Step 1: Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash and Aqua Jet
 * (data only), Defiant and Adaptability.
 * Step 2: Flare Blitz (defrost) and Darkest Lariat (ignoreDefensive,
 * ignoreEvasion).
 * Step 3: Salamencite (Salamence-Mega) and Aerilate.
 * Step 4: Last Respects (fainted members of the side) and Flip Turn (a
 * damaging pivot on the PIVOT boundary).
 * Step 5: Chople Berry (eaten inside ModifyDamage) and Rocky Helmet
 * (DamagingHit with contact).
 * Step 6: Dire Claw with poison (status 5, residual order 9) and the status
 * pick (draw site 13).
 * Step 7: Choice Scarf (x1.5 in the speed chain, the choice lock in the
 * request).
 * Step 8: White Herb (switch-in, after Mega, after a move, residual 29) and
 * Unburden (x2 Speed once its holder's item is used).
 * Step 9b: Sucker Punch (onTry reads the target's queued move) and Helping
 * Hand (the ally target, newlySwitched, BasePower x1.5).
 * Step 10: Psychic Surge and Psychic Terrain (priority moves stopped at
 * grounded foes, Psychic moves x5325/4096, the terrain replaced).
 * Step 11: Follow Me (a one-turn volatile; the RedirectTarget event takes the
 * foes' single-target moves before Lightning Rod).
 *
 * Pool (decision 0015; the ids the expansion adds after the extended ones):
 * step P1 added the ids and their family columns, step P2 makes the item
 * families rules (the type booster, BasePower x4915/4096, and the resist
 * berry, ModifyDamage x0.5, both read the family column) and marks the
 * sixteen new boosters and seventeen new berries; step P3 makes the "-ate"
 * and pinch abilities rules (the family columns of the ability, the type
 * change before STAB and immunity with BasePower x4915/4096, and ModifyAtk
 * and ModifySpA x1.5 at a third of the HP or less) and marks Pixilate,
 * Refrigerate, Overgrow, Torrent and Swarm.
 * Step G2 adds every row of the 17 target teams, all unmarked: the formes
 * Pelipper, Arcanine-Hisui, Annihilape and Floette-Eternal with its Mega, 22
 * moves (nine of them with a named handler id that the turn code refuses),
 * Focus Sash, Expert Belt, Floettite, Rock Head, Flower Veil and Fairy Aura.
 * It then marks the twelve moves whose data the existing paths already run
 * (Rock Slide, Double-Edge, Thunderbolt, Flash Cannon, Extreme Speed, Head
 * Smash, Bulk Up, Liquidation, Ice Punch, Shadow Claw, Drum Beating and
 * Dazzling Gleam), each used in one of the four reference battles under the
 * POOL kind g2_data_moves_a to _d. A move is marked only by the step that
 * records a reference battle with it.
 * Step G4 marks Focus Sash (a move hit or the confusion hit that would take all
 * of a full-HP holder's HP leaves it 1 HP) and Rock Head (no recoil from a
 * recoil move, Struggle's stays), each with recorded POOL battles. Step G5
 * marks U-turn: a damaging pivot whose switch flag names it (dfi_pivot_moves),
 * in the reference battles g5_uturn_a to _e.
 * The weather step marks Sand Stream and Snow Warning (table rules of the weather-setter family), Sandstorm and
 * Snowscape (named handlers) and the weather values Sand and Snow of the player view: Sandstorm's damage in
 * eachEvent order, the Rock and Ice defense boosts, Weather Ball's types, ten recorded POOL battles w1 to w8.
 * Step G8 marks Throat Chop (the sound moves barred for two turns, the cant
 * of a queued one) and Psychic Noise (Heal Block for two turns: every heal
 * of the holder refused, the heal-flag moves barred), which are secondary
 * kinds of the generic column plus the flags2 column, no longer handler ids
 * (seven remain); recorded as g8_throat_chop, g8_heal_block,
 * g8_heal_block_pair, g8_heal_block_tie_a and _b under the POOL kind.
 * Step G7 marks Wide Guard (a side condition for the turn that stops the spread moves of the foes at every target of
 * its side, with the stall counter raised and no roll; its handler id stays in the tables, the turn code runs it),
 * recorded as g7_wide_guard_a, _b, _ally and _pivot under the POOL kind.
 * Step G11 marks Soak (the target is pure Water until it leaves the field, faints or Mega Evolves: the soak type of the
 * POOL tail, read through dfi_types_of by every rule that reads a type; its handler id is code in the turn core now;
 * six handler ids remain), recorded as g11_soak, g11_soak_mega, g11_soak_stab and g11_soak_electro under the POOL kind.
 * Step G12 marks Flower Veil (it blocks the
 * stat drops and statuses that another Pokemon causes on a Grass-type ally), Fairy Aura
 * (5448/4096 for every Fairy move on the field, at the Mega Evolution of Floette-Eternal)
 * and Floettite, and the two moves of the real Floette set that nothing marked yet,
 * Moonblast (10 percent Special Attack drop, the Champions override) and Calm Mind,
 * in the reference battles g12_*.
 * Step G13 marks fourteen moves that the existing paths run, each in recorded POOL battles (g13_*): Flamethrower
 * (a burn secondary), Draining Kiss (drain 3/4), Rock Tomb and Icy Wind (a Speed drop at 100 percent, Icy Wind
 * spread), Hydro Pump, Power Gem and Earth Power (plain damage, a Special Defense secondary), Superpower (two
 * self drops), Light of Ruin (recoil 1/2), Aura Sphere (never misses, any target), Ice Shard and Quick Attack
 * (priority +1), Detect (Protect's handler and stall counter) and Poison Jab (a poison secondary).
 * Step G14 marks Rough Skin, Poison Touch and Thermal Exchange (abilities that the turn code runs by id: contact damage
 * before Rocky Helmet's, poison on a 3 in 10 roll after a contact hit, Attack +1 per Fire hit and no burn), recorded as
 * g14_rough_skin, g14_poison_touch and g14_thermal_exchange under the POOL kind.
 * Step G16 marks Knock Off (base power x1.5 while the target holds an item that can be taken, and the item taken after
 * the hit unless the target is alive with Sticky Hold; a Mega Stone is never taken from its own species) and Sticky
 * Hold, with the view bit 11 for the item that a move took (item_now of the member, public). Recorded as g16_* under
 * the POOL kind.
 * Step G29 marks the item-transfer moves Trick, Switcheroo, Thief and Covet (the item that a move gave is item_now too,
 * so bit 11 stays exact); a transfer that would make the receiver use the item on the spot (a White Herb with a lowered
 * stat, a terrain seed under its terrain) is E_UNSUPPORTED. Recorded as g29_* under the POOL kind.
 * Step G15 (Psychic Terrain) marks Expanding Force (80 base power; in Psychic Terrain, for a grounded user, x1.5 and the
 * target class allAdjacentFoes) and Psychic Seed (Grassy Seed's rule for Psychic Terrain and the Special Defense), in the
 * reference battles g15_*.
 * Step G18 marks four Mega Stones whose Mega ability the manifest already marks and whose base forme has a marked
 * ability and exactly one Mega: Tyranitarite (Sand Stream), Baxcalibrite (Thermal Exchange), Aerodactylite (Tough
 * Claws) and Manectite (Intimidate), recorded as g18_* under the POOL kind. The Mega Evolution itself is the generic
 * path. Charizardite X stays unmarked: the tables link one Mega per base forme (Charizard: Mega-Y).
 * Step G20 marks Aurora Veil (fails outside snow, 5 turns or 8 with Light Clay, 2732/4096 against every category unless a
 * crit or the screen of that category already does it, ends with its own line in the residual after Tailwind), with the
 * view bit 3 (aurora_veil_turns of the side, public). Recorded as g20_aurora_veil_* under the POOL kind.
 * Step G27 marks Disable and Cursed Body (30 percent on a damaging hit, the new draw site CURSED_BODY): the bar of the last move
 * for 4 turns (5 when the target had already moved) in the tail's disable_slot and disable_turns, the request's Struggle, the
 * Disable lines and the cant line (the new cause DISABLE), with the view bit 21 (disable_slot of the position, public).
 * Recorded as g27_* under the POOL kind.
 * Step G21 marks twenty-seven moves that the existing paths run (the rows were modelled before, with no unmodelled
 * feature; the pin was read again for each): Sludge Bomb and Gunk Shot (a poison secondary), Dragon Claw, Night Slash
 * and Slash (the last two with critical hit ratio 2), Air Slash, Icicle Crash, Waterfall and Dark Pulse (a flinch
 * secondary; Dark Pulse and Air Slash target any), Crunch and Bug Buzz and Mystical Fire (a stat drop secondary),
 * Struggle Bug (spread, a Special Attack drop on both foes), Nuzzle (paralysis at 100 percent), Fire Blast, Power Whip,
 * Overheat, Leaf Storm and Armor Cannon (self drops after the hit), Dragon Dance, Quiver Dance and Agility
 * (boosts of the user), Will-O-Wisp (a burn that Thermal Exchange and a Fire type refuse), Accelerock, Bullet Punch and
 * Mach Punch (priority +1) and Drain Punch (drain 1/2), recorded as g21_* under the POOL kind. Shell Smash (the pin
 * orders its boosts Defense, Special Defense, Attack, Special Attack, Speed, the engine in stat order), Earthquake,
 * Ancient Power, Blizzard, Dual Wingbeat, Feint, Life Dew, Acrobatics, Terrain Pulse and Expert Belt stay unmarked: each needs
 * logic that no column or handler has (docs/decisions/0015-content-expansion-pool.md, step G21).
 * Step G20 also marks Spiky Shield (Protect with a contact punishment, floor(max HP / 8) at the attacker; the variant is the tail's
 * protect_kind, tail rev 3). Baneful Bunker and King's Shield stay unmarked: their only learners (Toxapex, Aegislash) have no
 * supported ability, so no accepted battle could use them. Recorded as g20_spiky_shield_* under the POOL kind.
 * Step G31 marks Taunt (the Status moves barred for 3 turns, 4 when the target has been out a turn and has no move queued:
 * the request, the cant line with the new cause TAUNT, the end in the residual at order 15) and Yawn (the sleep at the end of
 * the next turn: the residual pass at order 23, no end line), with the view bits 14 and 25 (volatiles TAUNT and YAWN, public),
 * the new public values VOLATILE_TAUNT = 6 and VOLATILE_YAWN = 7 and CAUSE_TAUNT = 20. Recorded as g31_* under the POOL kind.
 * Step G24 (a Mega Stone batch) marks nine stones whose Mega ability and a base ability are marked and whose base forme has exactly
 * one Mega: Gardevoirite (Pixilate; the base forme's Trace has been marked since AC1: the Mega Evolution replaces the copied
 * ability), Abomasite (Snow Warning), Barbaracite (Tough Claws), Beedrillite (Adaptability), Falinksite (Defiant), Hawluchanite
 * (No Guard), Malamarite (Contrary), Sceptilite (Lightning Rod) and Scraftinite (Intimidate), recorded as g24_* under the POOL
 * kind. Meowsticite stays unmarked: one stone names two (base, Mega) pairs (Meowstic-M and -F) and its row links the first only.
 * Step G25 marks Electric Terrain and Misty Terrain (the moves: five turns, the same terrain fails, the other one is
 * replaced), Electric Surge (the entry setter of the terrain family), Electric Seed and Misty Seed (the seed rule of the other
 * terrains: Defense and Special Defense +1), Rising Voltage (base power doubled at a grounded target in Electric Terrain)
 * and Terrain Pulse (the terrain's type and twice the power for a grounded user, outside the -ate abilities), with the
 * terrains' own rules: 5325/4096 for a grounded user's Electric move, Dragon moves at a grounded target halved in Misty
 * Terrain, sleep refused to a grounded Pokemon in Electric Terrain and every status (and confusion) in Misty Terrain, the
 * view bits 5 and 32. Recorded as g25_* under the POOL kind.
 * Step G22 marks six abilities that the turn code runs by id: Sand Rush, Swift Swim, Slush Rush and Chlorophyll (Speed x2
 * in the speed key while their weather is up, a standing holder only; Sand Rush's holder also takes no Sandstorm damage),
 * Inner Focus (no flinch, and an Attack drop that Intimidate causes fails with -fail ... [from] ability: Inner Focus) and
 * Liquid Voice (a sound move is Water), recorded as g22_* under the POOL kind. Cursed Body, which needed the Disable
 * volatile, is marked by step G27.
 * Step G28 marks six moves and one item that the turn code now has rules for: Earthquake (the target class allAdjacent: the ally
 * is hit too, allies before foes; Wide Guard stops it; Grassy Terrain halves it at a grounded target), Shell Smash (which step G21 left out: the stats
 * change in the pinned order, Defense and Special Defense first), Acrobatics (twice the power while the user holds no item),
 * Blizzard (never misses in snow, the freeze at 10 percent is data), Ancient Power (a secondary that raises the user's five
 * stats at 10 percent: a new secondary kind), Feint (removes the target's Protect and the Wide Guard of its side, and its stall
 * counter) and Expert Belt (4915/4096 for a super effective hit), recorded as g28_* under the POOL kind.
 * Step G32 marks eleven moves, three abilities and an item whose rules are small: Eruption and Water Spout, Life Dew (the
 * target class allies), Body Press, Foul Play and Psyshock (the stat overrides of the damage formula), Rain Dance and Sunny Day,
 * Volt Switch (a pivot with a switch flag of its own), Clanging Scales (selfBoost), Freeze-Dry (Water is super effective), the
 * abilities Soundproof, Unnerve (no berries for the foes; announced first at the switch-in) and Speed Boost (the residual), and the
 * Champions Eject Button, recorded as g32_* under the POOL kind.
 * Step G26 marks Perish Song (the perish counter of the state tail, set on every active Pokemon without it; the residual
 * handler at order 24 shows the count and at 0 faints the holder; the volatile id DUOFORGE_VOLATILE_PERISH = 5), with the
 * view bit 4 (perish of the position, public). Soundproof (step G32) stops the cast at its holder, and a Heal Block that
 * ends in the same residual as a Perish count is refused (E_UNSUPPORTED). Recorded as g26_* under the POOL kind.
 * Step G33 marks three multi-hit moves and one ability: Dual Wingbeat and Twin Beam (two hits) and Triple Axel (three, a check
 * before each later hit, 20 x the hit as the power), each hit with its
 * own critical hit roll, damage roll and DamagingHit handlers; the hit count is the number of -damage lines, so the protocol's
 * -hitcount line is derived and no event is new. Mirror Armor (the drops that another Pokemon causes go back to it, one stat
 * at a time), recorded as g33_* under the POOL kind.
 * Step G57 (decision 0015, entry 5bg) marks Magic Bounce (the reflectable moves of the twenty marked rows bounce back at their user:
 * a single target after Protect, and a foeSide hazard through its holder on the foes' side; two holders refuse) and the Mega Stones
 * Absolite and Sablenite (Absol-Mega, with Justified, and Sableye-Mega, with Prankster). Recorded as g57_* under the POOL kind. */
const dfi_support_manifest dfi_support = {
    .turn_core = 1u,
    .switching = 1u,
    .mega_evolution = 1u,
    .moves =
        {
            [DFI_MOVE_HIGHHORSEPOWER] = 1u,
            [DFI_MOVE_PROTECT] = 1u,
            [DFI_MOVE_ROAR] = 1u,        /* step G46: forceSwitch, the drag (decision 0015 section 4) */
            [DFI_MOVE_WHIRLWIND] = 1u,   /* step G46 */
            [DFI_MOVE_DRAGONTAIL] = 1u,  /* step G46 */
            [DFI_MOVE_CIRCLETHROW] = 1u, /* step G46 */
            [DFI_MOVE_MUDDYWATER] = 1u,
            [DFI_MOVE_COIL] = 1u,
            [DFI_MOVE_SHADOWSNEAK] = 1u,
            [DFI_MOVE_SWORDSDANCE] = 1u,
            [DFI_MOVE_FOCUSBLAST] = 1u,
            [DFI_MOVE_SHADOWBALL] = 1u,
            [DFI_MOVE_NASTYPLOT] = 1u,
            [DFI_MOVE_DRILLRUN] = 1u,
            [DFI_MOVE_DRAGONPULSE] = 1u,
            [DFI_MOVE_SNARL] = 1u,
            [DFI_MOVE_PSYCHIC] = 1u,
            [DFI_MOVE_SPIRITBREAK] = 1u,
            [DFI_MOVE_ICEBEAM] = 1u,
            [DFI_MOVE_HYPNOSIS] = 1u,
            [DFI_MOVE_ZAPCANNON] = 1u,
            [DFI_MOVE_IRONHEAD] = 1u,
            [DFI_MOVE_HEATWAVE] = 1u,
            [DFI_MOVE_HURRICANE] = 1u,
            [DFI_MOVE_TAILWIND] = 1u,
            [DFI_MOVE_REFLECT] = 1u,
            [DFI_MOVE_LIGHTSCREEN] = 1u,
            [DFI_MOVE_TRICKROOM] = 1u,
            [DFI_MOVE_WOODHAMMER] = 1u,
            [DFI_MOVE_BRAVEBIRD] = 1u,
            [DFI_MOVE_BITTERBLADE] = 1u,
            [DFI_MOVE_LEECHLIFE] = 1u,
            [DFI_MOVE_CLOSECOMBAT] = 1u,
            [DFI_MOVE_MAKEITRAIN] = 1u,
            [DFI_MOVE_WEATHERBALL] = 1u,
            [DFI_MOVE_GRASSKNOT] = 1u,
            [DFI_MOVE_GRASSYGLIDE] = 1u,
            [DFI_MOVE_FAKEOUT] = 1u,
            [DFI_MOVE_ELECTROSHOT] = 1u,
            [DFI_MOVE_PARTINGSHOT] = 1u,
            [DFI_MOVE_KOWTOWCLEAVE] = 1u,
            [DFI_MOVE_HYPERVOICE] = 1u,
            [DFI_MOVE_DRACOMETEOR] = 1u,
            [DFI_MOVE_WAVECRASH] = 1u,
            [DFI_MOVE_AQUAJET] = 1u,
            [DFI_MOVE_FLAREBLITZ] = 1u,
            [DFI_MOVE_DARKESTLARIAT] = 1u,
            [DFI_MOVE_LASTRESPECTS] = 1u,
            [DFI_MOVE_FLIPTURN] = 1u,
            [DFI_MOVE_DIRECLAW] = 1u,
            [DFI_MOVE_SUCKERPUNCH] = 1u,
            [DFI_MOVE_HELPINGHAND] = 1u,
            [DFI_MOVE_FOLLOWME] = 1u,
            [DFI_MOVE_ROCKSLIDE] = 1u,
            [DFI_MOVE_DOUBLEEDGE] = 1u,
            [DFI_MOVE_THUNDERBOLT] = 1u,
            [DFI_MOVE_FLASHCANNON] = 1u,
            [DFI_MOVE_EXTREMESPEED] = 1u,
            [DFI_MOVE_HEADSMASH] = 1u,
            [DFI_MOVE_BULKUP] = 1u,
            [DFI_MOVE_LIQUIDATION] = 1u,
            [DFI_MOVE_ICEPUNCH] = 1u,
            [DFI_MOVE_SHADOWCLAW] = 1u,
            [DFI_MOVE_FIRSTIMPRESSION] = 1u,
            [DFI_MOVE_SCALD] = 1u,
            [DFI_MOVE_RECOVER] = 1u,
            [DFI_MOVE_LOWKICK] = 1u,
            [DFI_MOVE_DRUMBEATING] = 1u,
            [DFI_MOVE_DAZZLINGGLEAM] = 1u,
            [DFI_MOVE_UTURN] = 1u,
            [DFI_MOVE_SANDSTORM] = 1u,
            [DFI_MOVE_SNOWSCAPE] = 1u,
            [DFI_MOVE_THROATCHOP] = 1u,
            [DFI_MOVE_PSYCHICNOISE] = 1u,
            [DFI_MOVE_WIDEGUARD] = 1u,
            [DFI_MOVE_SOAK] = 1u,
            [DFI_MOVE_ENCORE] = 1u,
            [DFI_MOVE_MOONBLAST] = 1u,
            [DFI_MOVE_CALMMIND] = 1u,
            [DFI_MOVE_FLAMETHROWER] = 1u,
            [DFI_MOVE_DRAININGKISS] = 1u,
            [DFI_MOVE_ROCKTOMB] = 1u,
            [DFI_MOVE_HYDROPUMP] = 1u,
            [DFI_MOVE_SUPERPOWER] = 1u,
            [DFI_MOVE_LIGHTOFRUIN] = 1u,
            [DFI_MOVE_EARTHPOWER] = 1u,
            [DFI_MOVE_POWERGEM] = 1u,
            [DFI_MOVE_AURASPHERE] = 1u,
            [DFI_MOVE_ICYWIND] = 1u,
            [DFI_MOVE_ICESHARD] = 1u,
            [DFI_MOVE_QUICKATTACK] = 1u,
            [DFI_MOVE_DETECT] = 1u,
            [DFI_MOVE_EXPANDINGFORCE] = 1u,
            [DFI_MOVE_POISONJAB] = 1u,
            /* Step G17: the recharge moves (flags2 RECHARGE, mustrecharge): the user recharges after a hit. Meteor Assault is
             * not marked: its only learner, Sirfetch'd, has no supported ability (Steadfast, Scrappy), so no setup can use it. */
            [DFI_MOVE_BLASTBURN] = 1u,
            [DFI_MOVE_FRENZYPLANT] = 1u,
            [DFI_MOVE_GIGAIMPACT] = 1u,
            [DFI_MOVE_HYDROCANNON] = 1u,
            [DFI_MOVE_HYPERBEAM] = 1u,
            /* Step G19: Coaching (boosts to the ally) and Glaive Rush (its user is hit by moves that never miss and take twice the damage). */
            [DFI_MOVE_COACHING] = 1u,
            [DFI_MOVE_GLAIVERUSH] = 1u,
            [DFI_MOVE_ROCKWRECKER] = 1u,
            [DFI_MOVE_KNOCKOFF] = 1u,
            [DFI_MOVE_TRICK] = 1u,
            [DFI_MOVE_SWITCHEROO] = 1u,
            [DFI_MOVE_THIEF] = 1u,
            [DFI_MOVE_COVET] = 1u,
            [DFI_MOVE_SLUDGEBOMB] = 1u,
            [DFI_MOVE_GUNKSHOT] = 1u,
            [DFI_MOVE_DRAGONCLAW] = 1u,
            [DFI_MOVE_DRAGONDANCE] = 1u,
            [DFI_MOVE_QUIVERDANCE] = 1u,
            [DFI_MOVE_AGILITY] = 1u,
            [DFI_MOVE_MYSTICALFIRE] = 1u,
            [DFI_MOVE_STRUGGLEBUG] = 1u,
            [DFI_MOVE_DARKPULSE] = 1u,
            [DFI_MOVE_AIRSLASH] = 1u,
            [DFI_MOVE_ICICLECRASH] = 1u,
            [DFI_MOVE_WATERFALL] = 1u,
            [DFI_MOVE_OVERHEAT] = 1u,
            [DFI_MOVE_LEAFSTORM] = 1u,
            [DFI_MOVE_ARMORCANNON] = 1u,
            [DFI_MOVE_WILLOWISP] = 1u,
            [DFI_MOVE_NIGHTSLASH] = 1u,
            [DFI_MOVE_SLASH] = 1u,
            [DFI_MOVE_FIREBLAST] = 1u,
            [DFI_MOVE_POWERWHIP] = 1u,
            [DFI_MOVE_ACCELEROCK] = 1u,
            [DFI_MOVE_BULLETPUNCH] = 1u,
            [DFI_MOVE_MACHPUNCH] = 1u,
            [DFI_MOVE_CRUNCH] = 1u,
            [DFI_MOVE_BUGBUZZ] = 1u,
            [DFI_MOVE_DRAINPUNCH] = 1u,
            [DFI_MOVE_NUZZLE] = 1u,
            [DFI_MOVE_AURORAVEIL] = 1u,
            [DFI_MOVE_DISABLE] = 1u,
            /* Step G30: the powder moves (Rage Powder with its redirection, the status powders with the Grass type's and
             * Overcoat's immunity), Psychic Fangs (breaks the screens), Solar Beam (the two-turn charge that sun skips)
             * and the data rows that only wait for a recorded battle: Matcha Gotcha, Giga Drain, Energy Ball, Play Rough.
             * Cotton Spore (boosts to the foes) and Magic Powder (a type change) stay unmodelled; so does Stomping Tantrum
             * (it needs a last-move-failed flag that the state does not have). */
            [DFI_MOVE_RAGEPOWDER] = 1u,
            [DFI_MOVE_SLEEPPOWDER] = 1u,
            [DFI_MOVE_STUNSPORE] = 1u,
            [DFI_MOVE_POISONPOWDER] = 1u,
            [DFI_MOVE_PSYCHICFANGS] = 1u,
            [DFI_MOVE_SOLARBEAM] = 1u,
            [DFI_MOVE_MATCHAGOTCHA] = 1u,
            [DFI_MOVE_GIGADRAIN] = 1u,
            [DFI_MOVE_ENERGYBALL] = 1u,
            [DFI_MOVE_PLAYROUGH] = 1u,
            [DFI_MOVE_SPIKYSHIELD] = 1u,
            /* Step G36: Toxic (badly poisoned; a Poison-type user never misses) and Poison Fang (a 50 percent tox secondary). */
            [DFI_MOVE_TOXIC] = 1u,
            [DFI_MOVE_POISONFANG] = 1u,
            /* Step G37: the four entry hazards (foeSide moves: layers in the state tail, damage, status and stat drop at the
             * switch-in), recorded as g37_*. */
            [DFI_MOVE_STEALTHROCK] = 1u,
            [DFI_MOVE_SPIKES] = 1u,
            [DFI_MOVE_TOXICSPIKES] = 1u,
            [DFI_MOVE_STICKYWEB] = 1u,
            /* Step G25: Electric Terrain and Misty Terrain (the terrain moves), Rising Voltage and Terrain Pulse (their base power
             * and Terrain Pulse's type follow the terrain). */
            [DFI_MOVE_ELECTRICTERRAIN] = 1u,
            [DFI_MOVE_MISTYTERRAIN] = 1u,
            [DFI_MOVE_RISINGVOLTAGE] = 1u,
            [DFI_MOVE_TERRAINPULSE] = 1u,
            [DFI_MOVE_TAUNT] = 1u,
            [DFI_MOVE_YAWN] = 1u,
    [DFI_MOVE_REVIVALBLESSING] = 1u,
            /* Step G42: Roost (the heal, then the Flying type is off for the turn) and Stomping Tantrum (base power x2 after a
             * FALSE last move result; the move_result of tail rev 4, decision 0015 section 7). */
            [DFI_MOVE_ROOST] = 1u,
            [DFI_MOVE_STOMPINGTANTRUM] = 1u,
            /* Step G50: Double Shock (Pawmot only: the Electric and Fighting types become ??? and Fighting; decision 0025). */
            [DFI_MOVE_DOUBLESHOCK] = 1u,
            /* Step G32: Eruption and Water Spout (power by the user's HP), Life Dew (the user and its ally), Body Press, Foul Play
             * and Psyshock (the stat overrides), Rain Dance and Sunny Day, Volt Switch (a pivot of its own), Clanging Scales (the
             * user's Defense falls after the hit) and Freeze-Dry (Water takes it super effective). */
            [DFI_MOVE_ERUPTION] = 1u,
            [DFI_MOVE_WATERSPOUT] = 1u,
            [DFI_MOVE_LIFEDEW] = 1u,
            [DFI_MOVE_BODYPRESS] = 1u,
            [DFI_MOVE_FOULPLAY] = 1u,
            [DFI_MOVE_PSYSHOCK] = 1u,
            [DFI_MOVE_RAINDANCE] = 1u,
            [DFI_MOVE_SUNNYDAY] = 1u,
            [DFI_MOVE_VOLTSWITCH] = 1u,
            [DFI_MOVE_CLANGINGSCALES] = 1u,
            [DFI_MOVE_FREEZEDRY] = 1u,
            /* Step G33: the multi-hit loop (two hits: Dual Wingbeat, Twin Beam; three: Triple Axel). */
            [DFI_MOVE_DUALWINGBEAT] = 1u,
            [DFI_MOVE_TRIPLEAXEL] = 1u,
            [DFI_MOVE_TWINBEAM] = 1u,
            /* Step G48: Population Bomb (ten hits, multiaccuracy; accuracy 90, which the later-hit proof of G33 covers), Rage Fist
             * (its power is 50 + 50 per hit the user took, the tail's hits_taken), Stone Axe and Ceaseless Edge (a hazard on the
             * foe's side after a hit, the G37 add). Recorded as g48_*. */
            [DFI_MOVE_POPULATIONBOMB] = 1u,
            [DFI_MOVE_RAGEFIST] = 1u,
            [DFI_MOVE_STONEAXE] = 1u,
            [DFI_MOVE_CEASELESSEDGE] = 1u,
            /* Step G28: Shell Smash (its boosts in the pin's order), Acrobatics (doubled without an item), Blizzard (never misses
             * in snow), Ancient Power (a secondary that boosts its user), Feint (breaks Protect and Wide Guard). */
            [DFI_MOVE_SHELLSMASH] = 1u,
            [DFI_MOVE_ACROBATICS] = 1u,
            [DFI_MOVE_BLIZZARD] = 1u,
            [DFI_MOVE_ANCIENTPOWER] = 1u,
            [DFI_MOVE_FEINT] = 1u,
            [DFI_MOVE_EARTHQUAKE] = 1u, /* hits the ally too (allAdjacent); Grassy Terrain halves it */
            /* Step G34: Steel Roller (ends the terrain), Clangorous Soul, Brick Break (the screens go), and the data rows that waited
             * for a recorded battle: Fiery Dance, Psycho Cut, Iron Defense, Electroweb. */
            [DFI_MOVE_STEELROLLER] = 1u,
            [DFI_MOVE_CLANGOROUSSOUL] = 1u,
            [DFI_MOVE_BRICKBREAK] = 1u,
            /* Step G38: Imprison (the foes may not use the moves it knows; duoforge.state.pool_g38). */
            [DFI_MOVE_IMPRISON] = 1u,
            [DFI_MOVE_FIERYDANCE] = 1u,
            [DFI_MOVE_PSYCHOCUT] = 1u,
            [DFI_MOVE_IRONDEFENSE] = 1u,
            [DFI_MOVE_ELECTROWEB] = 1u,
            /* Step G35: the data rows that waited for a recorded battle (Gigaton Hammer is deferred: its only learner has no
             * marked ability). */
            [DFI_MOVE_THUNDERPUNCH] = 1u,
            [DFI_MOVE_XSCISSOR] = 1u,
            [DFI_MOVE_LUMINACRASH] = 1u,
            [DFI_MOVE_OVERDRIVE] = 1u,
            [DFI_MOVE_SCORCHINGSANDS] = 1u,
            [DFI_MOVE_LEAFBLADE] = 1u,
            [DFI_MOVE_BOOMBURST] = 1u,
            [DFI_MOVE_SLUDGEWAVE] = 1u,
            [DFI_MOVE_VOLTTACKLE] = 1u,
            [DFI_MOVE_DISCHARGE] = 1u,
            /* Step G26: Perish Song (the perish counter of the tail, the residual at order 24, view bit 4). */
            [DFI_MOVE_PERISHSONG] = 1u,
            /* Step G39: Charm and Fake Tears (a status move whose primary boosts go to its one target), Sacred Sword (Darkest
             * Lariat's rules: the target's Defense and evasion stages are ignored) and Super Fang (half the target's HP). */
            [DFI_MOVE_CHARM] = 1u,
            [DFI_MOVE_FAKETEARS] = 1u,
            [DFI_MOVE_SACREDSWORD] = 1u,
            [DFI_MOVE_SUPERFANG] = 1u,
            /* Step G44 (simple moves, decision 0015 item 5an). Handlers: Thunder (never misses in rain, 50 under sun), Power Trip
             * (20 plus 20 per positive stage of the user), Ice Fang (a freeze roll, then a flinch roll) and Tri Attack (a
             * 20 percent pick of burn, paralysis or freeze). Data rows: Breaking Swipe, Vacuum Wave, Stone Edge, Aqua Cutter,
             * Hammer Arm, Trop Kick and Meteor Mash. */
            [DFI_MOVE_THUNDER] = 1u,
            [DFI_MOVE_POWERTRIP] = 1u,
            [DFI_MOVE_ICEFANG] = 1u,
            [DFI_MOVE_TRIATTACK] = 1u,
            [DFI_MOVE_BREAKINGSWIPE] = 1u,
            [DFI_MOVE_VACUUMWAVE] = 1u,
            [DFI_MOVE_STONEEDGE] = 1u,
            [DFI_MOVE_AQUACUTTER] = 1u,
            [DFI_MOVE_HAMMERARM] = 1u,
            [DFI_MOVE_TROPKICK] = 1u,
            [DFI_MOVE_METEORMASH] = 1u,
            /* Step G56 (Outrage, decision 0015 item 5au): the lock (lockedmove; a random count of 2 or 3 uses, the
             * confusion when it ends, the switch-out and the faint clear it). Thrash and Petal Dance stay unmarked:
             * no recorded battle yet. */
            [DFI_MOVE_OUTRAGE] = 1u,
            /* Step G54 (decision 0015 item 5at). Handlers: Icicle Spear and Scale Shot (2 to 5 hits, the Champions weighted count,
             * Scale Shot's self boost after the last hit), Quick Guard (Wide Guard's shape against the priority moves), Upper Hand
             * (Sucker Punch's queue read: a queued priority move), Heal Pulse (half of the target's HP) and Strength Sap (heals by
             * the target's Attack and lowers it). Data row: Sing. Left out: Steel Beam and Final Gambit (decision 0015 5at).
             * Haze came in with step G62 (decision 0031, the event -clearallboost). */
            [DFI_MOVE_ICICLESPEAR] = 1u,
            [DFI_MOVE_SCALESHOT] = 1u,
            [DFI_MOVE_QUICKGUARD] = 1u,
            [DFI_MOVE_UPPERHAND] = 1u,
            [DFI_MOVE_HEALPULSE] = 1u,
            [DFI_MOVE_STRENGTHSAP] = 1u,
            [DFI_MOVE_SING] = 1u,
            /* Step G64 (decision 0015 item 5ca). Poltergeist: fails without a target item, and reveals the item after Protect. */
            [DFI_MOVE_POLTERGEIST] = 1u,
            [DFI_MOVE_BEATUP] = 1u,
            [DFI_MOVE_SHEERCOLD] = 1u,
            [DFI_MOVE_BUGBITE] = 1u,
            [DFI_MOVE_HAZE] = 1u, /* step G62, decision 0031 */
            [DFI_MOVE_AFTERYOU] = 1u, /* step G62, decision 0015 entry 5az: the queued move of the target goes next */
            [DFI_MOVE_QUASH] = 1u,    /* step G62, decision 0015 entry 5az: the queued move of the target goes last */
        },
    .abilities =
        {
            [DFI_ABILITY_DRIZZLE] = 1u,
            [DFI_ABILITY_GRASSYSURGE] = 1u,
            [DFI_ABILITY_INTIMIDATE] = 1u,
            [DFI_ABILITY_STAMINA] = 1u,
            [DFI_ABILITY_COMPETITIVE] = 1u,
            [DFI_ABILITY_FLASHFIRE] = 1u,
            [DFI_ABILITY_LIGHTNINGROD] = 1u,
            [DFI_ABILITY_GOODASGOLD] = 1u,
            [DFI_ABILITY_ARMORTAIL] = 1u,
            [DFI_ABILITY_PRANKSTER] = 1u,
            [DFI_ABILITY_BLAZE] = 1u,
            [DFI_ABILITY_DROUGHT] = 1u,
            [DFI_ABILITY_CONTRARY] = 1u,
            [DFI_ABILITY_NOGUARD] = 1u,
            [DFI_ABILITY_TOUGHCLAWS] = 1u,
            [DFI_ABILITY_EMERGENCYEXIT] = 1u,
            [DFI_ABILITY_DEFIANT] = 1u,
            [DFI_ABILITY_ADAPTABILITY] = 1u,
            [DFI_ABILITY_AERILATE] = 1u,
            [DFI_ABILITY_UNBURDEN] = 1u,
            [DFI_ABILITY_PSYCHICSURGE] = 1u,
            [DFI_ABILITY_ROCKHEAD] = 1u,
            [DFI_ABILITY_SANDSTREAM] = 1u,
            [DFI_ABILITY_SNOWWARNING] = 1u,
            [DFI_ABILITY_PIXILATE] = 1u,
            [DFI_ABILITY_REFRIGERATE] = 1u,
            [DFI_ABILITY_OVERGROW] = 1u,
            [DFI_ABILITY_TORRENT] = 1u,
            [DFI_ABILITY_SWARM] = 1u,
            [DFI_ABILITY_FLOWERVEIL] = 1u,
            [DFI_ABILITY_FAIRYAURA] = 1u,
            [DFI_ABILITY_TRACE] = 1u,
            [DFI_ABILITY_ROUGHSKIN] = 1u,
            [DFI_ABILITY_POISONTOUCH] = 1u,
            [DFI_ABILITY_THERMALEXCHANGE] = 1u,
            [DFI_ABILITY_STICKYHOLD] = 1u,
            /* Step G30: Flame Body, Clear Body, Hospitality and Overcoat (the sand and powder immunity). */
            [DFI_ABILITY_FLAMEBODY] = 1u,
            [DFI_ABILITY_CLEARBODY] = 1u,
            [DFI_ABILITY_HOSPITALITY] = 1u,
            [DFI_ABILITY_OVERCOAT] = 1u,
            [DFI_ABILITY_CURSEDBODY] = 1u,
            [DFI_ABILITY_LEVITATE] = 1u,
            /* Step G22: the weather Speed abilities (doubled Speed in their weather; Sand Rush also takes no Sandstorm damage),
             * Inner Focus (no flinch, no Intimidate drop) and Liquid Voice (sound moves are Water). */
            [DFI_ABILITY_SANDRUSH] = 1u,
            [DFI_ABILITY_SWIFTSWIM] = 1u,
            [DFI_ABILITY_SLUSHRUSH] = 1u,
            [DFI_ABILITY_CHLOROPHYLL] = 1u,
            [DFI_ABILITY_INNERFOCUS] = 1u,
            [DFI_ABILITY_LIQUIDVOICE] = 1u,
            /* Step G34: Compound Eyes, Iron Fist, Sharpness, Solid Rock, Technician, Multiscale and Gale Wings. */
            [DFI_ABILITY_COMPOUNDEYES] = 1u,
            [DFI_ABILITY_IRONFIST] = 1u,
            [DFI_ABILITY_SHARPNESS] = 1u,
            [DFI_ABILITY_SOLIDROCK] = 1u,
            [DFI_ABILITY_TECHNICIAN] = 1u,
            [DFI_ABILITY_MULTISCALE] = 1u,
            [DFI_ABILITY_GALEWINGS] = 1u,
            [DFI_ABILITY_SOUNDPROOF] = 1u, /* step G32 */
            [DFI_ABILITY_UNNERVE] = 1u,
            [DFI_ABILITY_SPEEDBOOST] = 1u,
            [DFI_ABILITY_RAINDISH] = 1u, /* step G35 */
            [DFI_ABILITY_ELECTRICSURGE] = 1u, /* step G25 */
            [DFI_ABILITY_FRIENDGUARD] = 1u,
            [DFI_ABILITY_MIRRORARMOR] = 1u, /* step G33 */
            [DFI_ABILITY_AURAGUARD] = 1u, /* Mega batch 2 (the Mega ability of Lucario-Mega-Z) */
            /* Step G39: Hyper Cutter, Scrappy, Infiltrator, Queenly Majesty, Damp (inert), Sturdy, Snow Cloak, Sand Veil, Static,
             * Justified, Limber, Solar Power and Regenerator. */
            [DFI_ABILITY_HYPERCUTTER] = 1u,
            [DFI_ABILITY_SCRAPPY] = 1u,
            [DFI_ABILITY_INFILTRATOR] = 1u,
            [DFI_ABILITY_QUEENLYMAJESTY] = 1u,
            [DFI_ABILITY_DAMP] = 1u,
            [DFI_ABILITY_STURDY] = 1u,
            [DFI_ABILITY_SNOWCLOAK] = 1u,
            [DFI_ABILITY_SANDVEIL] = 1u,
            [DFI_ABILITY_STATIC] = 1u,
            [DFI_ABILITY_JUSTIFIED] = 1u,
            [DFI_ABILITY_LIMBER] = 1u,
            [DFI_ABILITY_SOLARPOWER] = 1u,
            [DFI_ABILITY_REGENERATOR] = 1u,
            [DFI_ABILITY_TOXICDEBRIS] = 1u, /* step G37: a Physical hit puts Toxic Spikes on the attacker's side */
            [DFI_ABILITY_SHADOWTAG] = 1u, /* step G41 */
            [DFI_ABILITY_PRESSURE] = 1u, /* step G53: a foe's move costs one more PP per standing Pressure target */
            [DFI_ABILITY_SUCTIONCUPS] = 1u, /* step G46: a DragOut blocker (the forced switch is not made) */
            [DFI_ABILITY_GUARDDOG] = 1u,    /* step G46: a DragOut blocker */
            [DFI_ABILITY_STEADFAST] = 1u, /* step G45: a flinch that stops the move raises Speed by 1 */
            [DFI_ABILITY_WEAKARMOR] = 1u, /* step G45: a Physical hit lowers Defense by 1 and raises Speed by 2, each hit */
            [DFI_ABILITY_TELEPATHY] = 1u, /* step G45: a damaging move of an ally is stopped */
            [DFI_ABILITY_VOLTABSORB] = 1u, /* step G45: an Electric move heals a quarter of the HP, or is stopped */
            [DFI_ABILITY_PUNKROCK] = 1u, /* step G45: sound moves: x1.3 for the holder, x0.5 against it */
            [DFI_ABILITY_MOXIE] = 1u, /* step G45: a Move's knock-out raises Attack by the number of faints it caused at once */
            [DFI_ABILITY_SYNCHRONIZE] = 1u, /* step G47: the status passed back to a source (data/abilities.ts:4857-4871) */
            [DFI_ABILITY_OBLIVIOUS] = 1u,   /* step G47: Taunt, and Intimidate's Attack drop (data/abilities.ts:3008-3040) */
            [DFI_ABILITY_KEENEYE] = 1u,   /* step G51: the base ability of Pidgeot (with Pidgeotite), an engine row */
            [DFI_ABILITY_BIGPECKS] = 1u,  /* step G51: the other base ability of Pidgeot, an engine row */
            [DFI_ABILITY_MAGICBOUNCE] = 1u, /* step G57: reflects the reflectable moves (decision 0015 5bg) */
        },
    .items =
        {
            [DFI_ITEM_LEFTOVERS] = 1u,
            [DFI_ITEM_SITRUSBERRY] = 1u,
            [DFI_ITEM_GRASSYSEED] = 1u,
            [DFI_ITEM_LIFEORB] = 1u,
            [DFI_ITEM_MYSTICWATER] = 1u,
            [DFI_ITEM_LIGHTCLAY] = 1u,
            [DFI_ITEM_MIRACLESEED] = 1u,
            [DFI_ITEM_STARAPTITE] = 1u,
            [DFI_ITEM_RAICHUNITEY] = 1u,
            [DFI_ITEM_GOLISOPITE] = 1u,
            [DFI_ITEM_CHARIZARDITEY] = 1u,
            [DFI_ITEM_SALAMENCITE] = 1u,
            [DFI_ITEM_ROCKYHELMET] = 1u,
            [DFI_ITEM_CHOPLEBERRY] = 1u,
            [DFI_ITEM_CHOICESCARF] = 1u,
            [DFI_ITEM_WHITEHERB] = 1u,
            [DFI_ITEM_FOCUSSASH] = 1u,
            [DFI_ITEM_FLOETTITE] = 1u,
            [DFI_ITEM_PSYCHICSEED] = 1u,
            [DFI_ITEM_EXPERTBELT] = 1u, /* step G28 */
            [DFI_ITEM_WIDELENS] = 1u,   /* step G34 */
            [DFI_ITEM_MUSCLEBAND] = 1u,  /* step G49 */
            [DFI_ITEM_WISEGLASSES] = 1u, /* step G49 */
            [DFI_ITEM_BRIGHTPOWDER] = 1u, /* step G49 */
            [DFI_ITEM_DAMPROCK] = 1u,      /* step G55 */
            [DFI_ITEM_HEATROCK] = 1u,      /* step G55 */
            [DFI_ITEM_SMOOTHROCK] = 1u,    /* step G55 */
            [DFI_ITEM_ICYROCK] = 1u,       /* step G55 */
            [DFI_ITEM_TERRAINEXTENDER] = 1u, /* step G55 */
            [DFI_ITEM_EJECTBUTTON] = 1u, /* step G32 */
            [DFI_ITEM_ELECTRICSEED] = 1u, /* step G25 */
            [DFI_ITEM_MISTYSEED] = 1u,    /* step G25 */
            [DFI_ITEM_TYRANITARITE] = 1u,
            [DFI_ITEM_BAXCALIBRITE] = 1u,
            [DFI_ITEM_AERODACTYLITE] = 1u,
            [DFI_ITEM_MANECTITE] = 1u,
            [DFI_ITEM_CHARIZARDITEX] = 1u,
            [DFI_ITEM_GARCHOMPITEZ] = 1u,
            [DFI_ITEM_DELPHOXITE] = 1u,
            [DFI_ITEM_GENGARITE] = 1u, /* step G41: the Mega Stone of Gengar, whose Mega has Shadow Tag */
            [DFI_ITEM_REDCARD] = 1u,   /* step G46: forced switch of the attacker, without the Sheer Force gate (Champions) */
            [DFI_ITEM_GARDEVOIRITE] = 1u,
            [DFI_ITEM_ABOMASITE] = 1u,
            [DFI_ITEM_BARBARACITE] = 1u,
            [DFI_ITEM_BEEDRILLITE] = 1u,
            [DFI_ITEM_FALINKSITE] = 1u,
            [DFI_ITEM_HAWLUCHANITE] = 1u,
            [DFI_ITEM_MALAMARITE] = 1u,
            [DFI_ITEM_SCEPTILITE] = 1u,
            [DFI_ITEM_SCRAFTINITE] = 1u,
            /* Mega batch 2: Swampertite (Swift Swim), Metagrossite (Tough Claws), Lucarionite Z (Aura Guard) and Froslassite
             * (Snow Warning); the base formes' abilities (Torrent, Clear Body, Inner Focus, Cursed Body since G27) are marked. */
            [DFI_ITEM_SWAMPERTITE] = 1u,
            [DFI_ITEM_METAGROSSITE] = 1u,
            [DFI_ITEM_LUCARIONITEZ] = 1u,
            [DFI_ITEM_FROSLASSITE] = 1u,
            /* Step G51 (Mega batch 4, mark only for the stones; Keen Eye and Big Pecks are engine rows): ten Mega Stones whose Mega
             * ability is marked already (Infiltrator, Solar Power, Adaptability, Regenerator, Iron Fist, Levitate, Refrigerate,
             * Aerilate, Prankster, No Guard) and whose base forme's ability is marked: Chandelurite, Houndoominite, Lucarionite (not
             * the Z stone), Dragalgite, Crabominite, Chimechite, Glalitite, Pinsirite, Banettite and Pidgeotite. */
            [DFI_ITEM_CHANDELURITE] = 1u,
            [DFI_ITEM_HOUNDOOMINITE] = 1u,
            [DFI_ITEM_LUCARIONITE] = 1u,
            [DFI_ITEM_DRAGALGITE] = 1u,
            [DFI_ITEM_CRABOMINITE] = 1u,
            [DFI_ITEM_CHIMECHITE] = 1u,
            [DFI_ITEM_GLALITITE] = 1u,
            [DFI_ITEM_PINSIRITE] = 1u,
            [DFI_ITEM_BANETTITE] = 1u,
            [DFI_ITEM_PIDGEOTITE] = 1u,
            /* Step G43 (Mega batch 3, mark only): ten Mega Stones whose Mega ability is marked already (Multiscale, Adaptability,
             * Speed Boost, Sharpness, Electric Surge, Scrappy, Trace, Technician, Inner Focus) and whose base formes' abilities are
             * marked: Dragoninite, Glimmoranite, Blazikenite, Absolite Z, Raichunite X, Lopunnite, Alakazite, Meowsticite (both
             * Meowstic formes), Scizorite and Galladite. */
            [DFI_ITEM_DRAGONINITE] = 1u,
            [DFI_ITEM_GLIMMORANITE] = 1u,
            [DFI_ITEM_BLAZIKENITE] = 1u,
            [DFI_ITEM_ABSOLITEZ] = 1u,
            [DFI_ITEM_RAICHUNITEX] = 1u,
            [DFI_ITEM_LOPUNNITE] = 1u,
            [DFI_ITEM_ALAKAZITE] = 1u,
            [DFI_ITEM_MEOWSTICITE] = 1u,
            [DFI_ITEM_SCIZORITE] = 1u,
            [DFI_ITEM_GALLADITE] = 1u,
            /* Step G57 (Mega batch 4): Absolite (Absol-Mega, with the base's Justified) and Sablenite (Sableye-Mega, with the base's
             * Prankster). Absolite Z is marked by G43; Clefablite stays unmarked (Clefable's abilities are unmarked). */
            [DFI_ITEM_ABSOLITE] = 1u,
            [DFI_ITEM_SABLENITE] = 1u,
            [DFI_ITEM_BLACKBELT] = 1u,
            [DFI_ITEM_BLACKGLASSES] = 1u,
            [DFI_ITEM_CHARCOAL] = 1u,
            [DFI_ITEM_DRAGONFANG] = 1u,
            [DFI_ITEM_FAIRYFEATHER] = 1u,
            [DFI_ITEM_HARDSTONE] = 1u,
            [DFI_ITEM_MAGNET] = 1u,
            [DFI_ITEM_METALCOAT] = 1u,
            [DFI_ITEM_NEVERMELTICE] = 1u,
            [DFI_ITEM_POISONBARB] = 1u,
            [DFI_ITEM_SHARPBEAK] = 1u,
            [DFI_ITEM_SILKSCARF] = 1u,
            [DFI_ITEM_SILVERPOWDER] = 1u,
            [DFI_ITEM_SOFTSAND] = 1u,
            [DFI_ITEM_LUMBERRY] = 1u,   /* step G47: a status or a confusion is cured by the berry (data/items.ts:3537-3560) */
            [DFI_ITEM_MENTALHERB] = 1u, /* step G47: the four volatiles (data/items.ts:3889-3926) */
            [DFI_ITEM_SPELLTAG] = 1u,
            [DFI_ITEM_TWISTEDSPOON] = 1u,
            [DFI_ITEM_BABIRIBERRY] = 1u,
            [DFI_ITEM_CHARTIBERRY] = 1u,
            [DFI_ITEM_CHILANBERRY] = 1u,
            [DFI_ITEM_COBABERRY] = 1u,
            [DFI_ITEM_COLBURBERRY] = 1u,
            [DFI_ITEM_HABANBERRY] = 1u,
            [DFI_ITEM_KASIBBERRY] = 1u,
            [DFI_ITEM_KEBIABERRY] = 1u,
            [DFI_ITEM_OCCABERRY] = 1u,
            [DFI_ITEM_PASSHOBERRY] = 1u,
            [DFI_ITEM_PAYAPABERRY] = 1u,
            [DFI_ITEM_RINDOBERRY] = 1u,
            [DFI_ITEM_ROSELIBERRY] = 1u,
            [DFI_ITEM_SHUCABERRY] = 1u,
            [DFI_ITEM_TANGABERRY] = 1u,
            [DFI_ITEM_WACANBERRY] = 1u,
            [DFI_ITEM_YACHEBERRY] = 1u,
        },    /* The POOL player-view extension (decision 0018): a bit is set by the step that implements the feature and
     * records its battles. Step G8: Throat Chop and Heal Block (the position bits of duoforge_observation_ext, public,
     * verified against g8_throat_chop, g8_heal_block, g8_heal_block_pair and _tie_a/_b step by step in
     * duoforge.state.pool_g8). Step G11: the type change of Soak (bit 9: TYPE_CHANGED and type_now of the position, public,
     * verified against the four g11 battles in duoforge.state.pool_g11). Step G7: Wide Guard (bit 17: guard_flags, public,
     * verified in duoforge.state.pool_g7). Step G9: Encore (bit 7: encore_slot of the position, public, verified against
     * the g09_encore battles step by step in duoforge.state.pool_g9). Step G17: the recharge (bit 15: MUST_RECHARGE of the
     * position's volatiles, public, verified against the g17 battles step by step in duoforge.state.pool_g17). Step G19: Glaive Rush (bit 20:
     * GLAIVE_RUSH of the position's volatiles, public, verified against the g19 battles in duoforge.state.pool_g19). Step G20:
     * Aurora Veil (bit 3: aurora_veil_turns of the side, public, verified against the g20_aurora_veil battles step by step
     * in duoforge.state.pool_g20). Step G30: Rage Powder (bit 39: RAGE_POWDER of the position's volatiles, public, the value
     * that decision 0018 gave it, at a PIVOT boundary only; verified against the g30 battles in duoforge.state.pool_g30). Step G26: Perish Song (bit 4: perish of the position, public: the count that the game
     * announced, 3 to 1, verified against the g26 battles step by step in duoforge.state.pool_g26). */
    /* Step G38: Imprison (bit 12: IMPRISON of the position's volatiles, bit 2, public, verified against the g38 battles in
     * duoforge.state.pool_g38). */
    /* Step Sandstorm and Snowscape: bits 0 and 1, the weather values of the old observation's weather field (the
     * -weather lines of Sand Stream, Snow Warning and the two moves, verified step by step in duoforge.state.pool_weather).
     * Step AC1: the ability change of Trace (bit 2: position_ext.ability_now, public, verified against the ac1 battles in
     * duoforge.state.pool_ac1). Every other source of a changed ability stays E_UNSUPPORTED (an unmarked move or
     * ability), so the bit is exact: a zero is "no change". */
    /* Step G42: Roost (bit 40: the ROOST volatile of the position, public: the -singleturn line of Roost, set at its heal and
     * ended in the residual of order 25, verified against the g42 battles). MOVE_FAILED (bit 41) stays clear: the field is exact
     * only when the last result is classified, and an unclassified exit (decision 0015 section 7) reads 0 where the reference
     * may read 1. The expression stays plain terms: python/duoforge_live/lines.py parses it. */
    .view_ext_features = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ENCORE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_DISABLE) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_PERISH) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_IMPRISON) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TAUNT) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_YAWN) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_SPIKES) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ROOST) |
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD)
};
