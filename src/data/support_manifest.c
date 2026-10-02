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
 * grounded foes, Psychic moves x5325/4096, the terrain replaced). */
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
        },
};
