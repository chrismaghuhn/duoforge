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
 * No Mega Evolution is implemented yet. */
const dfi_support_manifest dfi_support = {
    .turn_core = 1u,
    .switching = 1u,
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
        },
};
