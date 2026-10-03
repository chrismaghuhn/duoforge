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
 * Hold, with the view bit 11 for the item that a move took (item_now of the member, public): Trick, Switcheroo and
 * Thief stay unmarked, so no accepted battle has an item that was swapped. Recorded as g16_* under the POOL kind.
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
 * Step G24 (a Mega Stone batch) marks nine stones whose Mega ability and a base ability are marked and whose base forme has exactly
 * one Mega: Gardevoirite (Pixilate; the base forme's Trace has been marked since AC1: the Mega Evolution replaces the copied
 * ability), Abomasite (Snow Warning), Barbaracite (Tough Claws), Beedrillite (Adaptability), Falinksite (Defiant), Hawluchanite
 * (No Guard), Malamarite (Contrary), Sceptilite (Lightning Rod) and Scraftinite (Intimidate), recorded as g24_* under the POOL
 * kind. Meowsticite stays unmarked: one stone names two (base, Mega) pairs (Meowstic-M and -F) and its row links the first only.
 * Step G22 marks six abilities that the turn code runs by id: Sand Rush, Swift Swim, Slush Rush and Chlorophyll (Speed x2
 * in the speed key while their weather is up, a standing holder only; Sand Rush's holder also takes no Sandstorm damage),
 * Inner Focus (no flinch, and an Attack drop that Intimidate causes fails with -fail ... [from] ability: Inner Focus) and
 * Liquid Voice (a sound move is Water), recorded as g22_* under the POOL kind. Cursed Body stays unmarked: it needs the
 * Disable volatile.
 * Step G26 marks Perish Song (the perish counter of the state tail, set on every active Pokemon without it; the residual
 * handler at order 24 shows the count and at 0 faints the holder; the volatile id DUOFORGE_VOLATILE_PERISH = 5), with the
 * view bit 4 (perish of the position, public). Soundproof stays unmarked (it would stop the move), and a Heal Block that
 * ends in the same residual as a Perish count is refused (E_UNSUPPORTED). Recorded as g26_* under the POOL kind. */
const dfi_support_manifest dfi_support = {
    .turn_core = 1u,
    .switching = 1u,
    .mega_evolution = 1u,
    .moves =
        {
            [DFI_MOVE_HIGHHORSEPOWER] = 1u,
            [DFI_MOVE_PROTECT] = 1u,
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
            [DFI_MOVE_SPIKYSHIELD] = 1u,
            /* Step G26: Perish Song (the perish counter of the tail, the residual at order 24, view bit 4). */
            [DFI_MOVE_PERISHSONG] = 1u,
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
            [DFI_ABILITY_LEVITATE] = 1u,
            /* Step G22: the weather Speed abilities (doubled Speed in their weather; Sand Rush also takes no Sandstorm damage),
             * Inner Focus (no flinch, no Intimidate drop) and Liquid Voice (sound moves are Water). */
            [DFI_ABILITY_SANDRUSH] = 1u,
            [DFI_ABILITY_SWIFTSWIM] = 1u,
            [DFI_ABILITY_SLUSHRUSH] = 1u,
            [DFI_ABILITY_CHLOROPHYLL] = 1u,
            [DFI_ABILITY_INNERFOCUS] = 1u,
            [DFI_ABILITY_LIQUIDVOICE] = 1u,
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
            [DFI_ITEM_TYRANITARITE] = 1u,
            [DFI_ITEM_BAXCALIBRITE] = 1u,
            [DFI_ITEM_AERODACTYLITE] = 1u,
            [DFI_ITEM_MANECTITE] = 1u,
            [DFI_ITEM_CHARIZARDITEX] = 1u,
            [DFI_ITEM_GARCHOMPITEZ] = 1u,
            [DFI_ITEM_DELPHOXITE] = 1u,
            [DFI_ITEM_GARDEVOIRITE] = 1u,
            [DFI_ITEM_ABOMASITE] = 1u,
            [DFI_ITEM_BARBARACITE] = 1u,
            [DFI_ITEM_BEEDRILLITE] = 1u,
            [DFI_ITEM_FALINKSITE] = 1u,
            [DFI_ITEM_HAWLUCHANITE] = 1u,
            [DFI_ITEM_MALAMARITE] = 1u,
            [DFI_ITEM_SCEPTILITE] = 1u,
            [DFI_ITEM_SCRAFTINITE] = 1u,
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
     * in duoforge.state.pool_g20). Step G26: Perish Song (bit 4: perish of the position, public: the count that the game
     * announced, 3 to 1, verified against the g26 battles step by step in duoforge.state.pool_g26). */
    /* Step Sandstorm and Snowscape: bits 0 and 1, the weather values of the old observation's weather field (the
     * -weather lines of Sand Stream, Snow Warning and the two moves, verified step by step in duoforge.state.pool_weather).
     * Step AC1: the ability change of Trace (bit 2: position_ext.ability_now, public, verified against the ac1 battles in
     * duoforge.state.pool_ac1). Every other source of a changed ability stays E_UNSUPPORTED (an unmarked move or
     * ability), so the bit is exact: a zero is "no change". */
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
                         ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_PERISH),
};
