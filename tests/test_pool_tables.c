/*
 * duoforge.data.pool_tables (white-box): the pool tables of decision 0015, the
 * extended tables followed by the rows of the content expansion, with the
 * family columns of every item and ability.
 *
 * The extended tables, and so the closure, are an exact prefix: every row
 * equals the row of src/data/extended_tables.c and src/data/closure_tables.c;
 * the canonical bytes recomputed from the prefix, without the family columns,
 * hash to the CLOSURE and TEAM_C table hashes (so their fingerprints still
 * name the data a battle of their kind reads). The family columns of the
 * prefix ids are what the engine hard-coded before they existed (the checks
 * of src/combat/turn.c: the Mystic Water and Miracle Seed boost, Chople
 * Berry, Aerilate, Blaze, and the entry abilities); the family and the type
 * of every new row are literal values read from the pinned handlers in
 * data/items.ts and data/abilities.ts (duoforge.data.pool_families runs
 * those handlers against the columns).
 *
 * Every forme also has the pool moves it learns and its legal abilities
 * (decision 0015 section 2). Both are checked against literal lists that were
 * written from the validator's answer in docs/research/expansion/data/
 * legal_pool.json (every species with every single move, and its legal
 * abilities), not from the Champions learnsets that the generator parses:
 * the two sources agree. The set of every forme is among them.
 *
 * Step G2 adds every row that the 17 target teams need (docs/research/expansion/
 * data/team_gaps.json "pool_rows"): the formes Pelipper, Arcanine-Hisui,
 * Annihilape, Floette-Eternal and Floette-Mega, 22 moves, the items Focus Sash,
 * Expert Belt and Floettite and the abilities Rock Head, Flower Veil and Fairy
 * Aura. Their values are literal, as the pin has them; nine of the moves have a
 * callback or a field that the columns do not model and carry a named handler id
 * in the special column. The items and abilities are unmarked in the support
 * manifest; twelve moves are marked, and U-turn and the nine handler moves are not.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/bytes.h"
#include "core/sha256.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "support/check.h"

#define POOL_HASH_HEX "592eb60a176ce88d0569ec7e6f7b3c9f05221505e18dd84df3e2353184e115e1"
/* SHA-256 of the closure-layout bytes of the rows of the steps (P1 and G2: 28 formes, 72 moves, 52 items, 29
 * abilities). The whole-pool step must not move one of them (decision 0015 section 4.2); the pool generator before it
 * produced the same bytes. */
#define STEPS_ROWS_HASH_HEX "52e85b0461b75d92729656791e39b11ed58263da70af82a20e638d1f33010b87"

/* The counts of the rows of the steps, and of the whole pool (legal_pool.json: 264 distinct selectable formes and
 * 82 Mega formes, 510 moves and Struggle, 166 items, 215 abilities). */
#define G2_FORMES 28u
#define G2_MOVES 72u
#define G2_ITEMS 52u
#define G2_ABILITIES 29u
#define POOL_FORMES 346u
#define POOL_MOVES 511u
#define POOL_ITEMS 166u
#define POOL_ABILITIES 215u

/* The rows that the tables do not model, pinned (the generator reports the same counts). */
#define UNMODELED_MOVES 323u
#define UNMODELED_ITEMS 45u
#define UNMODELED_ABILITIES 188u

/* How many rows of the manifest are marked and half modelled: marked, and with the UNMODELED handler or a list of
 * unmodelled features (decision 0015 section 4.2). A step marks only what it fully models. */
static uint32_t half_modelled_marks(const dfi_support_manifest *s)
{
    uint32_t half = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        half += s->moves[id] != 0u &&
                        (dfi_pool_moves[id].special == DFI_SPECIAL_UNMODELED || dfi_pool_move_unmodeled[id] != NULL)
                    ? 1u
                    : 0u;
    }
    for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
        half += s->items[id] != 0u &&
                        (dfi_pool_item_handler[id] == DFI_HANDLER_UNMODELED || dfi_pool_item_unmodeled[id] != NULL)
                    ? 1u
                    : 0u;
    }
    for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
        half += s->abilities[id] != 0u &&
                        (dfi_pool_ability_handler[id] == DFI_HANDLER_UNMODELED || dfi_pool_ability_unmodeled[id] != NULL)
                    ? 1u
                    : 0u;
    }
    return half;
}

/* An extended (or closure) link against the pool's: the u8 "none" of the old rows is DFI_FORME_NONE. */
static bool link_equals(uint32_t pool, uint32_t old)
{
    return old == DFI_CLOSURE_NONE ? pool == DFI_FORME_NONE : pool == old;
}

static bool forme_equals_ext(const dfi_pool_forme_data *p, const dfi_forme_data *e)
{
    bool ok = p->dex_num == e->dex_num && p->weight_hg == e->weight_hg && p->types[0] == e->types[0] &&
              p->types[1] == e->types[1] && p->ability == e->ability && p->gender_rule == e->gender_rule &&
              p->is_mega == e->is_mega && link_equals(p->base_forme, e->base_forme) &&
              link_equals(p->mega_forme, e->mega_forme) && p->mega_item == e->mega_item &&
              p->set_item == e->set_item && p->set_move_count == e->set_move_count;
    for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
        ok = ok && p->base[k] == e->base[k];
    }
    for (uint32_t k = 0u; k < 4u; ++k) {
        ok = ok && p->set_moves[k] == e->set_moves[k];
    }
    return ok;
}

static bool item_equals_ext(const dfi_pool_item_data *p, const dfi_item_data *e)
{
    return link_equals(p->mega_base, e->mega_base) && link_equals(p->mega_forme, e->mega_forme);
}

typedef struct family_case {
    uint32_t id;
    uint32_t family;
    uint32_t param; /* type, weather or terrain */
    const char *what;
} family_case;

/* Type boosters not in the prefix, then resist berries not in the prefix:
 * each item's handler (data/items.ts) tests move.type === T, and a resist
 * berry's naturalGift names the same type. */
static const family_case new_items[] = {
    {DFI_ITEM_BLACKBELT, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_FIGHTING, "Black Belt"},
    {DFI_ITEM_BLACKGLASSES, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_DARK, "Black Glasses"},
    {DFI_ITEM_CHARCOAL, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_FIRE, "Charcoal"},
    {DFI_ITEM_DRAGONFANG, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_DRAGON, "Dragon Fang"},
    {DFI_ITEM_FAIRYFEATHER, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_FAIRY, "Fairy Feather"},
    {DFI_ITEM_HARDSTONE, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_ROCK, "Hard Stone"},
    {DFI_ITEM_MAGNET, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_ELECTRIC, "Magnet"},
    {DFI_ITEM_METALCOAT, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_STEEL, "Metal Coat"},
    {DFI_ITEM_NEVERMELTICE, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_ICE, "Never-Melt Ice"},
    {DFI_ITEM_POISONBARB, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_POISON, "Poison Barb"},
    {DFI_ITEM_SHARPBEAK, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_FLYING, "Sharp Beak"},
    {DFI_ITEM_SILKSCARF, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_NORMAL, "Silk Scarf"},
    {DFI_ITEM_SILVERPOWDER, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_BUG, "Silver Powder"},
    {DFI_ITEM_SOFTSAND, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_GROUND, "Soft Sand"},
    {DFI_ITEM_SPELLTAG, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_GHOST, "Spell Tag"},
    {DFI_ITEM_TWISTEDSPOON, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_PSYCHIC, "Twisted Spoon"},
    {DFI_ITEM_BABIRIBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_STEEL, "Babiri Berry"},
    {DFI_ITEM_CHARTIBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_ROCK, "Charti Berry"},
    /* Chilan Berry halves any Normal hit; a Normal move is never super
     * effective, so the Normal berry has no extra column, only its type. */
    {DFI_ITEM_CHILANBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_NORMAL, "Chilan Berry"},
    {DFI_ITEM_COBABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_FLYING, "Coba Berry"},
    {DFI_ITEM_COLBURBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_DARK, "Colbur Berry"},
    {DFI_ITEM_HABANBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_DRAGON, "Haban Berry"},
    {DFI_ITEM_KASIBBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_GHOST, "Kasib Berry"},
    {DFI_ITEM_KEBIABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_POISON, "Kebia Berry"},
    {DFI_ITEM_OCCABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_FIRE, "Occa Berry"},
    {DFI_ITEM_PASSHOBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_WATER, "Passho Berry"},
    {DFI_ITEM_PAYAPABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_PSYCHIC, "Payapa Berry"},
    {DFI_ITEM_RINDOBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_GRASS, "Rindo Berry"},
    {DFI_ITEM_ROSELIBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_FAIRY, "Roseli Berry"},
    {DFI_ITEM_SHUCABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_GROUND, "Shuca Berry"},
    {DFI_ITEM_TANGABERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_BUG, "Tanga Berry"},
    {DFI_ITEM_WACANBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_ELECTRIC, "Wacan Berry"},
    {DFI_ITEM_YACHEBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_ICE, "Yache Berry"},
};

/* The prefix ids that have a family, as the engine hard-codes them
 * (src/combat/turn.c): Mystic Water boosts Water and Miracle Seed Grass,
 * Chople Berry halves a Fighting hit. */
static const family_case prefix_items[] = {
    {DFI_ITEM_MYSTICWATER, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_WATER, "Mystic Water"},
    {DFI_ITEM_MIRACLESEED, DFI_ITEM_FAMILY_TYPE_BOOSTER, DFI_TYPE_GRASS, "Miracle Seed"},
    {DFI_ITEM_CHOPLEBERRY, DFI_ITEM_FAMILY_RESIST_BERRY, DFI_TYPE_FIGHTING, "Chople Berry"},
};

/* Aerilate turns Normal moves Flying and boosts them; Blaze boosts Fire at a
 * third of the HP or less; Drizzle sets rain, Drought sun, Grassy Surge
 * Grassy Terrain and Psychic Surge Psychic Terrain. */
static const family_case prefix_abilities[] = {
    {DFI_ABILITY_AERILATE, DFI_ABILITY_FAMILY_ATE, DFI_TYPE_FLYING, "Aerilate"},
    {DFI_ABILITY_BLAZE, DFI_ABILITY_FAMILY_PINCH, DFI_TYPE_FIRE, "Blaze"},
    {DFI_ABILITY_DRIZZLE, DFI_ABILITY_FAMILY_WEATHER_SETTER, DFI_WEATHER_RAIN, "Drizzle"},
    {DFI_ABILITY_DROUGHT, DFI_ABILITY_FAMILY_WEATHER_SETTER, DFI_WEATHER_SUN, "Drought"},
    {DFI_ABILITY_GRASSYSURGE, DFI_ABILITY_FAMILY_TERRAIN_SETTER, DFI_TERRAIN_GRASSY, "Grassy Surge"},
    {DFI_ABILITY_PSYCHICSURGE, DFI_ABILITY_FAMILY_TERRAIN_SETTER, DFI_TERRAIN_PSYCHIC, "Psychic Surge"},
};

/* The new abilities: "-ate" (data/abilities.ts sets move.type to the type)
 * and pinch (move.type === T at a third of the HP or less). */
static const family_case new_abilities[] = {
    {DFI_ABILITY_PIXILATE, DFI_ABILITY_FAMILY_ATE, DFI_TYPE_FAIRY, "Pixilate"},
    {DFI_ABILITY_REFRIGERATE, DFI_ABILITY_FAMILY_ATE, DFI_TYPE_ICE, "Refrigerate"},
    {DFI_ABILITY_OVERGROW, DFI_ABILITY_FAMILY_PINCH, DFI_TYPE_GRASS, "Overgrow"},
    {DFI_ABILITY_TORRENT, DFI_ABILITY_FAMILY_PINCH, DFI_TYPE_WATER, "Torrent"},
    {DFI_ABILITY_SWARM, DFI_ABILITY_FAMILY_PINCH, DFI_TYPE_BUG, "Swarm"},
};

typedef struct legal_case {
    uint32_t forme;
    uint32_t move_count;
    uint32_t moves[32];
    uint32_t ability_count;
    uint32_t abilities[3];
} legal_case;

/* The pool moves that each base forme learns (the validator accepts a set
 * with that one move) and its legal abilities that are in the pool, in the
 * pokedex's slot order. The abilities of the pokedex that the pool does not
 * have (Reckless, Solar Power, Moxie, ...) are not listed. */
static const legal_case legal_formes[] = {
    {DFI_FORME_RILLABOOM, 15, {
        DFI_MOVE_WOODHAMMER, DFI_MOVE_GRASSYGLIDE, DFI_MOVE_FAKEOUT, DFI_MOVE_HIGHHORSEPOWER, DFI_MOVE_PROTECT,
        DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_SNARL, DFI_MOVE_GRASSKNOT, DFI_MOVE_HYPERVOICE,
        DFI_MOVE_UTURN, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_BULKUP, DFI_MOVE_DRUMBEATING, DFI_MOVE_LOWKICK
     },
     2, {DFI_ABILITY_OVERGROW, DFI_ABILITY_GRASSYSURGE}},
    {DFI_FORME_STARAPTOR, 11, {
        DFI_MOVE_BRAVEBIRD, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_TAILWIND, DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_HEATWAVE, DFI_MOVE_HURRICANE, DFI_MOVE_HELPINGHAND, DFI_MOVE_UTURN, DFI_MOVE_DOUBLEEDGE,
        DFI_MOVE_BULKUP
     },
     1, {DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_MILOTIC, 14, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_COIL, DFI_MOVE_ICEBEAM, DFI_MOVE_HYPNOSIS,
        DFI_MOVE_WEATHERBALL, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_FLIPTURN, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_SCALD, DFI_MOVE_RECOVER
     },
     1, {DFI_ABILITY_COMPETITIVE}},
    {DFI_FORME_CERULEDGE, 15, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_BITTERBLADE, DFI_MOVE_SHADOWSNEAK, DFI_MOVE_SWORDSDANCE,
        DFI_MOVE_SHADOWBALL, DFI_MOVE_IRONHEAD, DFI_MOVE_HEATWAVE, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN,
        DFI_MOVE_FLAREBLITZ, DFI_MOVE_HELPINGHAND, DFI_MOVE_THROATCHOP, DFI_MOVE_BULKUP, DFI_MOVE_SHADOWCLAW
     },
     1, {DFI_ABILITY_FLASHFIRE}},
    {DFI_FORME_RAICHU, 12, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_ZAPCANNON, DFI_MOVE_FOCUSBLAST, DFI_MOVE_NASTYPLOT,
        DFI_MOVE_GRASSKNOT, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HELPINGHAND, DFI_MOVE_ENCORE,
        DFI_MOVE_THUNDERBOLT, DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_LIGHTNINGROD}},
    {DFI_FORME_GHOLDENGO, 14, {
        DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST, DFI_MOVE_MAKEITRAIN, DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT,
        DFI_MOVE_IRONHEAD, DFI_MOVE_PSYCHIC, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_THUNDERBOLT,
        DFI_MOVE_FLASHCANNON, DFI_MOVE_RECOVER, DFI_MOVE_LOWKICK, DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_GOODASGOLD}},
    {DFI_FORME_POLITOED, 14, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_HYPNOSIS, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_WEATHERBALL, DFI_MOVE_PSYCHIC, DFI_MOVE_HYPERVOICE, DFI_MOVE_HELPINGHAND, DFI_MOVE_ENCORE,
        DFI_MOVE_DOUBLEEDGE, DFI_MOVE_LIQUIDATION, DFI_MOVE_ICEPUNCH, DFI_MOVE_LOWKICK
     },
     1, {DFI_ABILITY_DRIZZLE}},
    {DFI_FORME_GOLISOPOD, 21, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_SWORDSDANCE,
        DFI_MOVE_FOCUSBLAST, DFI_MOVE_LEECHLIFE, DFI_MOVE_IRONHEAD, DFI_MOVE_DRILLRUN, DFI_MOVE_SNARL,
        DFI_MOVE_SUCKERPUNCH, DFI_MOVE_AQUAJET, DFI_MOVE_UTURN, DFI_MOVE_ROCKSLIDE, DFI_MOVE_THROATCHOP,
        DFI_MOVE_SCALD, DFI_MOVE_WIDEGUARD, DFI_MOVE_FIRSTIMPRESSION, DFI_MOVE_BULKUP, DFI_MOVE_LIQUIDATION,
        DFI_MOVE_SHADOWCLAW
     },
     1, {DFI_ABILITY_EMERGENCYEXIT}},
    {DFI_FORME_ARCHALUDON, 13, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_ELECTROSHOT,
        DFI_MOVE_SNARL, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_DRACOMETEOR, DFI_MOVE_ROCKSLIDE,
        DFI_MOVE_DOUBLEEDGE, DFI_MOVE_THUNDERBOLT, DFI_MOVE_FLASHCANNON
     },
     1, {DFI_ABILITY_STAMINA}},
    {DFI_FORME_FARIGIRAF, 17, {
        DFI_MOVE_HIGHHORSEPOWER, DFI_MOVE_PROTECT, DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT, DFI_MOVE_IRONHEAD,
        DFI_MOVE_PSYCHIC, DFI_MOVE_GRASSKNOT, DFI_MOVE_TRICKROOM, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN,
        DFI_MOVE_HYPERVOICE, DFI_MOVE_HELPINGHAND, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_THUNDERBOLT,
        DFI_MOVE_PSYCHICNOISE, DFI_MOVE_LOWKICK, DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_ARMORTAIL}},
    {DFI_FORME_CHARIZARD, 12, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_WEATHERBALL, DFI_MOVE_DRAGONPULSE,
        DFI_MOVE_HEATWAVE, DFI_MOVE_HURRICANE, DFI_MOVE_FLAREBLITZ, DFI_MOVE_HELPINGHAND, DFI_MOVE_ROCKSLIDE,
        DFI_MOVE_DOUBLEEDGE, DFI_MOVE_SHADOWCLAW
     },
     1, {DFI_ABILITY_BLAZE}},
    {DFI_FORME_GRIMMSNARL, 16, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST, DFI_MOVE_NASTYPLOT, DFI_MOVE_LEECHLIFE,
        DFI_MOVE_SPIRITBREAK, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_PARTINGSHOT, DFI_MOVE_SUCKERPUNCH,
        DFI_MOVE_THROATCHOP, DFI_MOVE_BULKUP, DFI_MOVE_ICEPUNCH, DFI_MOVE_SHADOWCLAW, DFI_MOVE_LOWKICK,
        DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_PRANKSTER}},
    {DFI_FORME_SNEASLER, 15, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT, DFI_MOVE_GRASSKNOT, DFI_MOVE_DIRECLAW, DFI_MOVE_UTURN,
        DFI_MOVE_ROCKSLIDE, DFI_MOVE_THROATCHOP, DFI_MOVE_BULKUP, DFI_MOVE_SHADOWCLAW, DFI_MOVE_LOWKICK
     },
     1, {DFI_ABILITY_UNBURDEN}},
    {DFI_FORME_INCINEROAR, 19, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_NASTYPLOT, DFI_MOVE_LEECHLIFE, DFI_MOVE_IRONHEAD, DFI_MOVE_SNARL, DFI_MOVE_HEATWAVE,
        DFI_MOVE_PARTINGSHOT, DFI_MOVE_FLAREBLITZ, DFI_MOVE_DARKESTLARIAT, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_THROATCHOP, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_BULKUP, DFI_MOVE_SHADOWCLAW, DFI_MOVE_LOWKICK
     },
     2, {DFI_ABILITY_BLAZE, DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_SALAMENCE, 12, {
        DFI_MOVE_TAILWIND, DFI_MOVE_PROTECT, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_HEATWAVE,
        DFI_MOVE_HURRICANE, DFI_MOVE_HYPERVOICE, DFI_MOVE_DRACOMETEOR, DFI_MOVE_HELPINGHAND, DFI_MOVE_ROCKSLIDE,
        DFI_MOVE_DOUBLEEDGE, DFI_MOVE_SHADOWCLAW
     },
     1, {DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_INDEEDEEF, 11, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_SHADOWBALL, DFI_MOVE_PSYCHIC, DFI_MOVE_TRICKROOM,
        DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HYPERVOICE, DFI_MOVE_FOLLOWME, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_PSYCHICSURGE}},
    {DFI_FORME_KINGAMBIT, 12, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_IRONHEAD, DFI_MOVE_SNARL,
        DFI_MOVE_GRASSKNOT, DFI_MOVE_KOWTOWCLEAVE, DFI_MOVE_SUCKERPUNCH, DFI_MOVE_THROATCHOP,
        DFI_MOVE_FLASHCANNON, DFI_MOVE_SHADOWCLAW, DFI_MOVE_LOWKICK
     },
     1, {DFI_ABILITY_DEFIANT}},
    {DFI_FORME_BASCULEGION, 12, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_SHADOWBALL, DFI_MOVE_LASTRESPECTS,
        DFI_MOVE_WAVECRASH, DFI_MOVE_AQUAJET, DFI_MOVE_FLIPTURN, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_HEADSMASH,
        DFI_MOVE_LIQUIDATION, DFI_MOVE_SOAK
     },
     1, {DFI_ABILITY_ADAPTABILITY}},
    {DFI_FORME_PELIPPER, 12, {
        DFI_MOVE_BRAVEBIRD, DFI_MOVE_TAILWIND, DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM,
        DFI_MOVE_WEATHERBALL, DFI_MOVE_HURRICANE, DFI_MOVE_HELPINGHAND, DFI_MOVE_UTURN, DFI_MOVE_WIDEGUARD,
        DFI_MOVE_LIQUIDATION, DFI_MOVE_SOAK
     },
     1, {DFI_ABILITY_DRIZZLE}},
    {DFI_FORME_ARCANINEHISUI, 13, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_SNARL,
        DFI_MOVE_HEATWAVE, DFI_MOVE_FLAREBLITZ, DFI_MOVE_HYPERVOICE, DFI_MOVE_HELPINGHAND, DFI_MOVE_ROCKSLIDE,
        DFI_MOVE_DOUBLEEDGE, DFI_MOVE_EXTREMESPEED, DFI_MOVE_HEADSMASH
     },
     3, {DFI_ABILITY_INTIMIDATE, DFI_ABILITY_FLASHFIRE, DFI_ABILITY_ROCKHEAD}},
    {DFI_FORME_ANNIHILAPE, 15, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST, DFI_MOVE_SHADOWBALL, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_UTURN, DFI_MOVE_ROCKSLIDE, DFI_MOVE_THROATCHOP, DFI_MOVE_ENCORE, DFI_MOVE_DOUBLEEDGE,
        DFI_MOVE_THUNDERBOLT, DFI_MOVE_BULKUP, DFI_MOVE_ICEPUNCH, DFI_MOVE_SHADOWCLAW, DFI_MOVE_LOWKICK
     },
     1, {DFI_ABILITY_DEFIANT}},
    {DFI_FORME_FLOETTEETERNAL, 6, {
        DFI_MOVE_PROTECT, DFI_MOVE_PSYCHIC, DFI_MOVE_GRASSKNOT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_DAZZLINGGLEAM
     },
     1, {DFI_ABILITY_FLOWERVEIL}},
};

/* ---- Step G2: the rows that the 17 target teams need (docs/research/expansion/data/team_gaps.json) ---- */

/* The new formes, as the validator's record of docs/research/expansion/data/legal_pool.json and the pinned
 * data/pokedex.ts have them: dex number, weight in hectograms, types, base stats, gender rule. */
typedef struct forme_case {
    uint32_t id;
    const char *what;
    uint32_t dex_num, weight_hg, type0, type1, base[6], gender_rule, is_mega;
} forme_case;

static const forme_case new_formes[] = {
    {DFI_FORME_PELIPPER, "Pelipper", 279u, 280u, DFI_TYPE_WATER, DFI_TYPE_FLYING, {60u, 50u, 100u, 95u, 70u, 65u},
     DFI_GENDER_RULE_ANY, 0u},
    {DFI_FORME_ARCANINEHISUI, "Arcanine-Hisui", 59u, 1680u, DFI_TYPE_FIRE, DFI_TYPE_ROCK,
     {95u, 115u, 80u, 95u, 80u, 90u}, DFI_GENDER_RULE_ANY, 0u},
    {DFI_FORME_ANNIHILAPE, "Annihilape", 979u, 560u, DFI_TYPE_FIGHTING, DFI_TYPE_GHOST,
     {110u, 115u, 80u, 50u, 90u, 90u}, DFI_GENDER_RULE_ANY, 0u},
    {DFI_FORME_FLOETTEETERNAL, "Floette-Eternal", 670u, 9u, DFI_TYPE_FAIRY, DFI_CLOSURE_NONE,
     {74u, 65u, 67u, 125u, 128u, 92u}, DFI_GENDER_RULE_FEMALE, 0u},
    {DFI_FORME_FLOETTEMEGA, "Floette-Mega", 670u, 1008u, DFI_TYPE_FAIRY, DFI_CLOSURE_NONE,
     {74u, 85u, 87u, 155u, 148u, 102u}, DFI_GENDER_RULE_FEMALE, 1u},
};

/* The new moves as the pinned data/moves.ts (and the Champions mod: First Impression's base power is 100) has them.
 * pp_max is Champions' (calculatePP over pp capped at 20); the priority is the stored one (priority + 8); boosts are
 * the unbiased stage changes (atk, def, spa, spd, spe, accuracy, evasion). A handler id is the special column. */
typedef struct move_case {
    uint32_t id;
    const char *what;
    uint32_t type, category, base_power, accuracy, pp_max, priority, target_class, crit_ratio, flags;
    uint32_t recoil[2], sec_chance, sec_kind, sec_param, boost_role;
    int32_t boosts[7];
    uint32_t special;
} move_case;

#define NB {0, 0, 0, 0, 0, 0, 0}
static const move_case new_moves[] = {
    {DFI_MOVE_UTURN, "U-turn", DFI_TYPE_BUG, DFI_CATEGORY_PHYSICAL, 70u, 100u, 20u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT | DFI_MOVE_FLAG_SELF_SWITCH, {0u, 0u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_ROCKSLIDE, "Rock Slide", DFI_TYPE_ROCK, DFI_CATEGORY_PHYSICAL, 75u, 90u, 12u, 8u,
     DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES, 1u, DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 30u, DFI_SECONDARY_VOLATILE,
     DFI_VOLATILE_FLINCH, 0u, NB, 0u},
    {DFI_MOVE_THROATCHOP, "Throat Chop", DFI_TYPE_DARK, DFI_CATEGORY_PHYSICAL, 80u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_THROAT_CHOP},
    {DFI_MOVE_ENCORE, "Encore", DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0u, 100u, 8u, 8u, 1u, 1u, DFI_MOVE_FLAG_PROTECT,
     {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_ENCORE},
    {DFI_MOVE_DOUBLEEDGE, "Double-Edge", DFI_TYPE_NORMAL, DFI_CATEGORY_PHYSICAL, 120u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {33u, 100u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_THUNDERBOLT, "Thunderbolt", DFI_TYPE_ELECTRIC, DFI_CATEGORY_SPECIAL, 90u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 10u, DFI_SECONDARY_STATUS, DFI_STATUS_PAR, 0u, NB, 0u},
    {DFI_MOVE_SCALD, "Scald", DFI_TYPE_WATER, DFI_CATEGORY_SPECIAL, 80u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT | DFI_MOVE_FLAG_DEFROST, {0u, 0u}, 30u, DFI_SECONDARY_STATUS, DFI_STATUS_BRN, 0u, NB,
     DFI_SPECIAL_SCALD},
    {DFI_MOVE_WIDEGUARD, "Wide Guard", DFI_TYPE_ROCK, DFI_CATEGORY_STATUS, 0u, 0u, 12u, 11u,
     DUOFORGE_TARGET_CLASS_ALLY_SIDE, 1u, 0u, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_WIDE_GUARD},
    {DFI_MOVE_FLASHCANNON, "Flash Cannon", DFI_TYPE_STEEL, DFI_CATEGORY_SPECIAL, 80u, 100u, 12u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 10u, DFI_SECONDARY_BOOST, 0u, DFI_BOOST_ROLE_SECONDARY_TARGET,
     {0, 0, 0, -1, 0, 0, 0}, 0u},
    {DFI_MOVE_EXTREMESPEED, "Extreme Speed", DFI_TYPE_NORMAL, DFI_CATEGORY_PHYSICAL, 80u, 100u, 8u, 10u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_HEADSMASH, "Head Smash", DFI_TYPE_ROCK, DFI_CATEGORY_PHYSICAL, 150u, 80u, 8u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {1u, 2u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_FIRSTIMPRESSION, "First Impression", DFI_TYPE_BUG, DFI_CATEGORY_PHYSICAL, 100u, 100u, 12u, 10u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_FIRST_IMPRESSION},
    {DFI_MOVE_BULKUP, "Bulk Up", DFI_TYPE_FIGHTING, DFI_CATEGORY_STATUS, 0u, 0u, 20u, 8u,
     DUOFORGE_TARGET_CLASS_SELF, 1u, 0u, {0u, 0u}, 0u, 0u, 0u, DFI_BOOST_ROLE_PRIMARY_SELF, {1, 1, 0, 0, 0, 0, 0}, 0u},
    {DFI_MOVE_LIQUIDATION, "Liquidation", DFI_TYPE_WATER, DFI_CATEGORY_PHYSICAL, 85u, 100u, 12u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 20u, DFI_SECONDARY_BOOST, 0u,
     DFI_BOOST_ROLE_SECONDARY_TARGET, {0, -1, 0, 0, 0, 0, 0}, 0u},
    {DFI_MOVE_ICEPUNCH, "Ice Punch", DFI_TYPE_ICE, DFI_CATEGORY_PHYSICAL, 75u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 10u, DFI_SECONDARY_STATUS, DFI_STATUS_FRZ, 0u, NB, 0u},
    {DFI_MOVE_SHADOWCLAW, "Shadow Claw", DFI_TYPE_GHOST, DFI_CATEGORY_PHYSICAL, 70u, 100u, 16u, 8u, 1u, 2u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_RECOVER, "Recover", DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0u, 0u, 8u, 8u, DUOFORGE_TARGET_CLASS_SELF, 1u,
     0u, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_RECOVER},
    {DFI_MOVE_SOAK, "Soak", DFI_TYPE_WATER, DFI_CATEGORY_STATUS, 0u, 100u, 20u, 8u, 1u, 1u, DFI_MOVE_FLAG_PROTECT,
     {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_SOAK},
    {DFI_MOVE_PSYCHICNOISE, "Psychic Noise", DFI_TYPE_PSYCHIC, DFI_CATEGORY_SPECIAL, 75u, 100u, 12u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_PSYCHIC_NOISE},
    {DFI_MOVE_DRUMBEATING, "Drum Beating", DFI_TYPE_GRASS, DFI_CATEGORY_PHYSICAL, 80u, 100u, 12u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 100u, DFI_SECONDARY_BOOST, 0u, DFI_BOOST_ROLE_SECONDARY_TARGET,
     {0, 0, 0, 0, -1, 0, 0}, 0u},
    {DFI_MOVE_LOWKICK, "Low Kick", DFI_TYPE_FIGHTING, DFI_CATEGORY_PHYSICAL, 0u, 100u, 20u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_LOW_KICK},
    {DFI_MOVE_DAZZLINGGLEAM, "Dazzling Gleam", DFI_TYPE_FAIRY, DFI_CATEGORY_SPECIAL, 80u, 100u, 12u, 8u,
     DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES, 1u, DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 0u, 0u, 0u, 0u, NB, 0u},
};
#undef NB

static void check_forme_row(df_test *t, const forme_case *c)
{
    const dfi_pool_forme_data *f = &dfi_pool_formes[c->id];
    bool ok = f->dex_num == c->dex_num && f->weight_hg == c->weight_hg && f->types[0] == c->type0 &&
              f->types[1] == c->type1 && f->gender_rule == c->gender_rule && f->is_mega == c->is_mega;
    for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
        ok = ok && f->base[k] == c->base[k];
    }
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  forme %s: a field differs from the pin\n", c->what);
    }
}

static void check_move_row(df_test *t, const move_case *c)
{
    const dfi_move_data *m = &dfi_pool_moves[c->id];
    bool ok = m->type == c->type && m->category == c->category && m->base_power == c->base_power &&
              m->accuracy == c->accuracy && m->pp_max == c->pp_max && m->priority == c->priority &&
              m->target_class == c->target_class && m->crit_ratio == c->crit_ratio && m->flags == c->flags &&
              m->recoil[0] == c->recoil[0] && m->recoil[1] == c->recoil[1] && m->drain[0] == 0u && m->drain[1] == 0u &&
              m->sec_chance == c->sec_chance && m->sec_kind == c->sec_kind && m->sec_param == c->sec_param &&
              m->boost_role == c->boost_role && m->primary_status == DFI_STATUS_NONE && m->side_condition == 0u &&
              m->pseudo_weather == 0u && m->special == c->special;
    for (uint32_t k = 0u; k < DFI_STAGE_COUNT; ++k) {
        ok = ok && (int32_t)m->boosts[k] - (int32_t)DFI_STAGE_BIAS == c->boosts[k];
    }
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  move %s: a field differs from the pin\n", c->what);
    }
}

static void check_item(df_test *t, const family_case *c)
{
    const dfi_item_family *f = &dfi_pool_item_family[c->id];
    if (!DF_CHECK(t, f->family == c->family && f->type == c->param)) {
        fprintf(stderr, "  item %s: family %u type %u, expected %u and %u\n", c->what, f->family, f->type,
                c->family, c->param);
    }
}

static void check_ability(df_test *t, const family_case *c)
{
    const dfi_ability_family *f = &dfi_pool_ability_family[c->id];
    if (!DF_CHECK(t, f->family == c->family && f->param == c->param)) {
        fprintf(stderr, "  ability %s: family %u param %u, expected %u and %u\n", c->what, f->family, f->param,
                c->family, c->param);
    }
}

/* Bit `index` of a bitset (bit index % 8 of byte index / 8). */
static bool bit_of(const uint8_t *bytes, uint32_t index)
{
    return (((uint32_t)bytes[index / 8u] >> (index % 8u)) & 1u) != 0u;
}

static bool listed(const family_case *list, size_t n, uint32_t id)
{
    for (size_t i = 0u; i < n; ++i) {
        if (list[i].id == id) {
            return true;
        }
    }
    return false;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.data.pool_tables");
    const size_t n_new_items = sizeof new_items / sizeof new_items[0];
    const size_t n_prefix_items = sizeof prefix_items / sizeof prefix_items[0];
    const size_t n_prefix_abilities = sizeof prefix_abilities / sizeof prefix_abilities[0];
    const size_t n_new_abilities = sizeof new_abilities / sizeof new_abilities[0];

    /* Counts. Step P1 added 16 type boosters, 17 resist berries and 5 abilities (items 16 to 48, abilities 21 to 25);
     * step G2 added 5 formes (23 to 27), 22 moves (50 to 71), 3 items (49 to 51) and 3 abilities (26 to 28), in the
     * order of the research's pool_rows; the whole-pool step (decision 0015 section 4.2) appends a row for every
     * other forme, move, item and ability of the legal pool. The ids of every step start where the previous ones end,
     * and the counts are those of docs/research/expansion/data/legal_pool.json: 293 selectable formes of which 29 are
     * cosmetic copies (264 rows), 82 Mega formes, the 510 moves and Struggle, 166 items and 215 abilities. */
    DF_CHECK_EQ_U64(&t, DFI_POOL_FORME_COUNT, POOL_FORMES);
    DF_CHECK_EQ_U64(&t, DFI_POOL_MOVE_COUNT, POOL_MOVES);
    DF_CHECK_EQ_U64(&t, DFI_POOL_ITEM_COUNT, POOL_ITEMS);
    DF_CHECK_EQ_U64(&t, DFI_POOL_ABILITY_COUNT, POOL_ABILITIES);
    DF_CHECK_EQ_U64(&t, DFI_POOL_ALIAS_COUNT, 29u);
    DF_CHECK_EQ_U64(&t, DFI_FORME_PELIPPER, DFI_EXT_FORME_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_FORME_FLOETTEMEGA, G2_FORMES - 1u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_UTURN, DFI_EXT_MOVE_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_DAZZLINGGLEAM, G2_MOVES - 1u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_BLACKBELT, DFI_EXT_ITEM_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_YACHEBERRY, DFI_ITEM_FOCUSSASH - 1u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_FLOETTITE, G2_ITEMS - 1u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_TWISTEDSPOON, DFI_EXT_ITEM_COUNT + 15u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_BABIRIBERRY, DFI_EXT_ITEM_COUNT + 16u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_PIXILATE, DFI_EXT_ABILITY_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_SWARM, DFI_ABILITY_ROCKHEAD - 1u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_FAIRYAURA, G2_ABILITIES - 1u);
    DF_CHECK_EQ_U64(&t, n_new_items, DFI_ITEM_FOCUSSASH - DFI_EXT_ITEM_COUNT);
    DF_CHECK_EQ_U64(&t, n_new_abilities, DFI_ABILITY_ROCKHEAD - DFI_EXT_ABILITY_COUNT);
    DF_CHECK_EQ_U64(&t, sizeof new_formes / sizeof new_formes[0], G2_FORMES - DFI_EXT_FORME_COUNT);
    DF_CHECK_EQ_U64(&t, sizeof new_moves / sizeof new_moves[0], G2_MOVES - DFI_EXT_MOVE_COUNT);
    /* The whole-pool rows begin right after the rows of the steps, with the first id of the legal pool's order. */
    DF_CHECK_EQ_U64(&t, DFI_MOVE_ACCELEROCK, G2_MOVES);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_ABOMASITE, G2_ITEMS);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_AFTERMATH, G2_ABILITIES);
    DF_CHECK_EQ_U64(&t, DFI_FORME_VENUSAUR, G2_FORMES);

    /* The prefix is the extended tables, and so the closure, row by row. The pool's forme and item rows have u16
     * forme links, so a row is compared field by field (DFI_FORME_NONE for the closure's 0xFF); a move row is the same
     * type and compared byte by byte. */
    {
        uint32_t diff = 0u;
        for (uint32_t i = 0u; i < DFI_EXT_FORME_COUNT; ++i) {
            diff += forme_equals_ext(&dfi_pool_formes[i], &dfi_ext_formes[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_EXT_MOVE_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_moves[i], (const uint8_t *)&dfi_ext_moves[i],
                                    sizeof dfi_pool_moves[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_EXT_ITEM_COUNT; ++i) {
            diff += item_equals_ext(&dfi_pool_items[i], &dfi_ext_items[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_FORME_COUNT; ++i) {
            diff += forme_equals_ext(&dfi_pool_formes[i], &dfi_closure_formes[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_MOVE_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_moves[i], (const uint8_t *)&dfi_closure_moves[i],
                                    sizeof dfi_pool_moves[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_ITEM_COUNT; ++i) {
            diff += item_equals_ext(&dfi_pool_items[i], &dfi_closure_items[i]) ? 0u : 1u;
        }
        /* The type immunity bits are the extended ones (the closure's plus
         * psn); the pool adds no type. */
        diff += dfi_bytes_equal(dfi_pool_type_immunity, dfi_ext_type_immunity, DFI_TYPE_COUNT) ? 0u : 1u;
        DF_CHECK_EQ_U64(&t, diff, 0u);
    }

    /* The Mega formes and stones of the whole pool. 82 Mega formes, 81 Mega Stones (Meowsticite serves both
     * Meowstics), and 77 base formes that link a Mega forme through their row (Absol, Charizard, Garchomp, Lucario
     * and Raichu have two Mega formes; the base forme links the first, the Mega forme of the other stone is a row of
     * its own with the same base forme). The item row of a stone names its first (base, Mega) pair; the engine
     * reads the forme rows. */
    {
        uint32_t stones = 0u;
        uint32_t megas = 0u;
        uint32_t linked = 0u;
        uint32_t odd = 0u;
        for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
            stones += dfi_pool_items[i].mega_base != DFI_FORME_NONE ? 1u : 0u;
            /* A stone's pair is two rows that name each other: the Mega forme has the stone and the base forme. */
            if (dfi_pool_items[i].mega_base != DFI_FORME_NONE) {
                const dfi_pool_forme_data *m = &dfi_pool_formes[dfi_pool_items[i].mega_forme];
                odd += (m->is_mega == 1u && m->mega_item == i && m->base_forme == dfi_pool_items[i].mega_base &&
                        dfi_pool_formes[dfi_pool_items[i].mega_base].is_mega == 0u)
                           ? 0u
                           : 1u;
            }
        }
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            const dfi_pool_forme_data *x = &dfi_pool_formes[f];
            megas += x->is_mega;
            linked += x->mega_forme != DFI_FORME_NONE ? 1u : 0u;
            if (x->is_mega != 0u) {
                odd += (x->mega_forme == DFI_FORME_NONE && x->base_forme < f && dfi_pool_formes[x->base_forme].is_mega == 0u &&
                        x->set_item == x->mega_item && x->mega_item != DFI_CLOSURE_NONE)
                           ? 0u
                           : 1u;
            } else if (x->mega_forme != DFI_FORME_NONE) {
                const dfi_pool_forme_data *m = &dfi_pool_formes[x->mega_forme];
                odd += (m->is_mega == 1u && m->base_forme == f && m->mega_item == x->mega_item) ? 0u : 1u;
            }
        }
        DF_CHECK_EQ_U64(&t, stones, 81u);
        DF_CHECK_EQ_U64(&t, megas, 82u);
        DF_CHECK_EQ_U64(&t, linked, 77u);
        DF_CHECK_EQ_U64(&t, odd, 0u);
        DF_CHECK(&t, dfi_pool_items[DFI_ITEM_FLOETTITE].mega_base == DFI_FORME_FLOETTEETERNAL &&
                         dfi_pool_items[DFI_ITEM_FLOETTITE].mega_forme == DFI_FORME_FLOETTEMEGA);
        const dfi_pool_forme_data *base = &dfi_pool_formes[DFI_FORME_FLOETTEETERNAL];
        const dfi_pool_forme_data *mega = &dfi_pool_formes[DFI_FORME_FLOETTEMEGA];
        DF_CHECK(&t, base->set_item == DFI_ITEM_FLOETTITE && base->mega_item == DFI_ITEM_FLOETTITE &&
                         base->mega_forme == DFI_FORME_FLOETTEMEGA && base->base_forme == DFI_FORME_FLOETTEETERNAL &&
                         mega->base_forme == DFI_FORME_FLOETTEETERNAL && mega->mega_forme == DFI_FORME_NONE &&
                         mega->mega_item == DFI_ITEM_FLOETTITE && mega->ability == DFI_ABILITY_FAIRYAURA &&
                         base->ability == DFI_ABILITY_FLOWERVEIL);
        /* No other new forme has a Mega forme. */
        for (uint32_t i = DFI_FORME_PELIPPER; i <= DFI_FORME_ANNIHILAPE; ++i) {
            DF_CHECK(&t, dfi_pool_formes[i].mega_forme == DFI_FORME_NONE && dfi_pool_formes[i].mega_item == DFI_CLOSURE_NONE &&
                             dfi_pool_formes[i].base_forme == i);
        }
    }

    /* The new formes and moves against the pin, literal values (see the cases above); every handler id of a move
     * that the columns cannot model is a special of its own, and no other move has a special that is new. */
    {
        for (size_t i = 0u; i < sizeof new_formes / sizeof new_formes[0]; ++i) {
            check_forme_row(&t, &new_formes[i]);
        }
        for (size_t i = 0u; i < sizeof new_moves / sizeof new_moves[0]; ++i) {
            check_move_row(&t, &new_moves[i]);
        }
        uint32_t handlers = 0u;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            handlers += dfi_pool_moves[i].special >= DFI_SPECIAL_THROAT_CHOP &&
                                dfi_pool_moves[i].special <= DFI_SPECIAL_LOW_KICK
                            ? 1u
                            : 0u;
        }
        DF_CHECK_EQ_U64(&t, handlers, DFI_SPECIAL_LOW_KICK - DFI_SPECIAL_THROAT_CHOP + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_THROAT_CHOP, DFI_SPECIAL_FOLLOW_ME + 1u);
        /* UNMODELED follows the nine handlers of G2. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_LOW_KICK + 1u);
    }

    /* The closure and extended canonical bytes recomputed from the prefix,
     * without the family columns, are theirs and hash to the table hashes
     * that the CLOSURE and TEAM_C fingerprints carry. */
    {
        uint8_t closure[DFI_CLOSURE_CANONICAL_SIZE];
        uint8_t from_pool[DFI_POOL_CANONICAL_SIZE];
        uint8_t ext[DFI_EXT_CANONICAL_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        const uint32_t closure_bits = DFI_IMMUNE_BRN | DFI_IMMUNE_FRZ | DFI_IMMUNE_PAR | DFI_IMMUNE_PRANKSTER;
        DF_CHECK_EQ_U64(&t, dfi_closure_canonical_bytes(closure, sizeof closure), DFI_CLOSURE_CANONICAL_SIZE);
        size_t n = dfi_pool_canonical_bytes_of(from_pool, sizeof from_pool, DFI_FORME_COUNT, DFI_MOVE_COUNT,
                                               DFI_ITEM_COUNT, DFI_ABILITY_COUNT, closure_bits);
        DF_CHECK_EQ_U64(&t, n, DFI_CLOSURE_CANONICAL_SIZE);
        DF_CHECK_BYTES(&t, from_pool, closure, DFI_CLOSURE_CANONICAL_SIZE, "closure canonical bytes from the pool prefix");
        DF_CHECK(&t, dfi_sha256(from_pool, n, sha));
        DF_CHECK_BYTES(&t, sha, dfi_closure_table_hash, sizeof sha, "sha256(closure prefix) = closure table hash");

        DF_CHECK_EQ_U64(&t, dfi_ext_canonical_bytes(ext, sizeof ext), DFI_EXT_CANONICAL_SIZE);
        n = dfi_pool_canonical_bytes_of(from_pool, sizeof from_pool, DFI_EXT_FORME_COUNT, DFI_EXT_MOVE_COUNT,
                                        DFI_EXT_ITEM_COUNT, DFI_EXT_ABILITY_COUNT, 0xFFu);
        DF_CHECK_EQ_U64(&t, n, DFI_EXT_CANONICAL_SIZE);
        DF_CHECK_BYTES(&t, from_pool, ext, DFI_EXT_CANONICAL_SIZE, "extended canonical bytes from the pool prefix");
        DF_CHECK(&t, dfi_sha256(from_pool, n, sha));
        DF_CHECK_BYTES(&t, sha, dfi_ext_table_hash, sizeof sha, "sha256(extended prefix) = extended table hash");
    }

    /* The rows of the steps (P1 and G2) are unchanged by the whole-pool rows: the closure-layout bytes of those 28
     * formes, 72 moves, 52 items and 29 abilities hash to the value that the pool generator before the whole-pool step
     * produced for them. The closure layout holds forme links as one byte, so it cannot hold the whole pool: with the
     * pool counts the function refuses (a link above 254). */
    {
        static uint8_t rows[DFI_POOL_CANONICAL_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        const size_t n = dfi_pool_canonical_bytes_of(rows, sizeof rows, G2_FORMES, G2_MOVES, G2_ITEMS, G2_ABILITIES,
                                                     0xFFu);
        DF_CHECK_EQ_U64(&t, n, 12u + G2_FORMES * 24u + G2_MOVES * 29u + G2_ITEMS * 2u + 324u + 18u + 50u);
        DF_CHECK(&t, dfi_sha256(rows, n, sha));
        DF_CHECK(&t, df_hex_to_bytes(STEPS_ROWS_HASH_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, sha, want, sizeof sha, "sha256(the rows of the steps P1 and G2, closure layout)");
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(rows, sizeof rows, DFI_POOL_FORME_COUNT, DFI_POOL_MOVE_COUNT,
                                                        DFI_POOL_ITEM_COUNT, DFI_POOL_ABILITY_COUNT, 0xFFu),
                        0u);
    }

    /* The pool hash: SHA-256 of the canonical pool bytes, the pool layout: the six counts; per forme 26 bytes (the
     * closure's 24 with the base and Mega links as u16); per move the closure's 29; per item the two links as u16; the
     * type chart, the immunity bits and the natures; then the family column of every item and of every ability, the
     * handler column of every item and of every ability, and the legal moves and abilities of every forme (the
     * learnable bytes, the ability count and the three ability ids). The test walks the layout independently of the
     * generated writer; the size is the generator's literal and the hash is different from the other two. */
    {
        static uint8_t bytes[DFI_POOL_CANONICAL_SIZE + 8u];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        memset(bytes, 0xA5, sizeof bytes);
        const size_t n = dfi_pool_canonical_bytes(bytes, sizeof bytes);
        DF_CHECK_EQ_U64(&t, n, DFI_POOL_CANONICAL_SIZE);
        /* 12 + 346 * 26 + 511 * 29 + 166 * 4 + 324 + 18 + 50, then 166 * 2 + 215 * 2, then 166 + 215, then
         * 346 * (64 + 1 + 3) */
        DF_CHECK_EQ_U64(&t, DFI_POOL_CANONICAL_SIZE, 12u + POOL_FORMES * 26u + POOL_MOVES * 29u + POOL_ITEMS * 4u + 324u +
                                                         18u + 50u + POOL_ITEMS * 2u + POOL_ABILITIES * 2u +
                                                         POOL_ITEMS + POOL_ABILITIES +
                                                         POOL_FORMES * (DFI_POOL_LEARN_BYTES + 1u + 3u));
        DF_CHECK(&t, bytes[DFI_POOL_CANONICAL_SIZE] == 0xA5u);
        uint32_t at = 0u;
        uint32_t bad = 0u;
        const uint32_t counts[6] = {DFI_POOL_FORME_COUNT, DFI_POOL_MOVE_COUNT, DFI_POOL_ITEM_COUNT,
                                    DFI_POOL_ABILITY_COUNT, DFI_TYPE_COUNT, DFI_NATURE_COUNT};
        for (uint32_t k = 0u; k < 6u; ++k) {
            bad += (uint32_t)bytes[at] + 256u * (uint32_t)bytes[at + 1u] != counts[k] ? 1u : 0u;
            at += 2u;
        }
#define U16(v) ((uint8_t)((v) & 0xFFu)), ((uint8_t)(((v) >> 8) & 0xFFu))
        for (uint32_t i = 0u; i < DFI_POOL_FORME_COUNT; ++i) {
            const dfi_pool_forme_data *f = &dfi_pool_formes[i];
            const uint8_t want_row[26] = {
                U16(f->dex_num), f->types[0], f->types[1], f->base[0], f->base[1], f->base[2], f->base[3], f->base[4],
                f->base[5], U16(f->weight_hg), f->ability, f->gender_rule, f->is_mega, U16(f->base_forme),
                U16(f->mega_forme), f->mega_item, f->set_item, f->set_move_count, f->set_moves[0], f->set_moves[1],
                f->set_moves[2], f->set_moves[3]};
            bad += dfi_bytes_equal(bytes + at, want_row, sizeof want_row) ? 0u : 1u;
            at += (uint32_t)sizeof want_row;
        }
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            const dfi_move_data *m = &dfi_pool_moves[i];
            const uint8_t want_row[29] = {m->type, m->category, m->base_power, m->accuracy, m->pp_base, m->pp_max,
                                          m->priority, m->target_class, m->crit_ratio, m->flags, m->recoil[0],
                                          m->recoil[1], m->drain[0], m->drain[1], m->sec_chance, m->sec_kind,
                                          m->sec_param, m->boost_role, m->boosts[0], m->boosts[1], m->boosts[2],
                                          m->boosts[3], m->boosts[4], m->boosts[5], m->boosts[6], m->primary_status,
                                          m->side_condition, m->pseudo_weather, m->special};
            bad += dfi_bytes_equal(bytes + at, want_row, sizeof want_row) ? 0u : 1u;
            at += (uint32_t)sizeof want_row;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
            const uint8_t want_row[4] = {U16(dfi_pool_items[i].mega_base), U16(dfi_pool_items[i].mega_forme)};
            bad += dfi_bytes_equal(bytes + at, want_row, sizeof want_row) ? 0u : 1u;
            at += (uint32_t)sizeof want_row;
        }
#undef U16
        for (uint32_t d = 0u; d < DFI_TYPE_COUNT; ++d) {
            for (uint32_t a = 0u; a < DFI_TYPE_COUNT; ++a) {
                bad += bytes[at] != dfi_closure_type_chart[d][a] ? 1u : 0u;
                at += 1u;
            }
        }
        for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
            bad += bytes[at] != dfi_pool_type_immunity[i] ? 1u : 0u;
            at += 1u;
        }
        for (uint32_t i = 0u; i < DFI_NATURE_COUNT; ++i) {
            bad += bytes[at] != dfi_closure_natures[i].plus || bytes[at + 1u] != dfi_closure_natures[i].minus ? 1u : 0u;
            at += 2u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
            bad += bytes[at] != dfi_pool_item_family[i].family || bytes[at + 1u] != dfi_pool_item_family[i].type ? 1u : 0u;
            at += 2u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
            bad += bytes[at] != dfi_pool_ability_family[i].family || bytes[at + 1u] != dfi_pool_ability_family[i].param
                       ? 1u
                       : 0u;
            at += 2u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
            bad += bytes[at] != dfi_pool_item_handler[i] ? 1u : 0u;
            at += 1u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
            bad += bytes[at] != dfi_pool_ability_handler[i] ? 1u : 0u;
            at += 1u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_FORME_COUNT; ++i) {
            const dfi_forme_legal *l = &dfi_pool_forme_legal[i];
            for (uint32_t k = 0u; k < DFI_POOL_LEARN_BYTES; ++k) {
                bad += bytes[at + k] != l->learnable[k] ? 1u : 0u;
            }
            at += DFI_POOL_LEARN_BYTES;
            bad += bytes[at] != l->ability_count ? 1u : 0u;
            at += 1u;
            for (uint32_t k = 0u; k < DFI_POOL_FORME_ABILITIES_MAX; ++k) {
                bad += bytes[at + k] != l->abilities[k] ? 1u : 0u;
            }
            at += DFI_POOL_FORME_ABILITIES_MAX;
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        DF_CHECK_EQ_U64(&t, at, DFI_POOL_CANONICAL_SIZE);
        DF_CHECK(&t, dfi_sha256(bytes, n, sha));
        DF_CHECK(&t, df_hex_to_bytes(POOL_HASH_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, sha, want, sizeof sha, "sha256(pool canonical bytes)");
        DF_CHECK_BYTES(&t, dfi_pool_table_hash, want, sizeof want, "dfi_pool_table_hash");
        DF_CHECK(&t, !dfi_bytes_equal(dfi_pool_table_hash, dfi_closure_table_hash, sizeof want));
        DF_CHECK(&t, !dfi_bytes_equal(dfi_pool_table_hash, dfi_ext_table_hash, sizeof want));
        /* A buffer that is too small gets nothing; counts beyond the tables are refused. */
        uint8_t small[16];
        memset(small, 0xA5, sizeof small);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes(small, sizeof small), 0u);
        DF_CHECK(&t, small[0] == 0xA5u && small[15] == 0xA5u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes(bytes, DFI_POOL_CANONICAL_SIZE - 1u), 0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, DFI_POOL_FORME_COUNT + 1u, G2_MOVES,
                                                        G2_ITEMS, G2_ABILITIES, 0xFFu),
                        0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, G2_FORMES, DFI_POOL_MOVE_COUNT + 1u,
                                                        G2_ITEMS, G2_ABILITIES, 0xFFu),
                        0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, G2_FORMES, G2_MOVES,
                                                        DFI_POOL_ITEM_COUNT + 1u, G2_ABILITIES, 0xFFu),
                        0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, G2_FORMES, G2_MOVES, G2_ITEMS,
                                                        DFI_POOL_ABILITY_COUNT + 1u, 0xFFu),
                        0u);
    }

    /* The family columns. The prefix ids carry what the engine hard-coded;
     * every other prefix id has no family; the new rows are the literal
     * values above. */
    {
        for (size_t i = 0u; i < n_prefix_items; ++i) {
            check_item(&t, &prefix_items[i]);
        }
        for (size_t i = 0u; i < n_new_items; ++i) {
            check_item(&t, &new_items[i]);
        }
        for (size_t i = 0u; i < n_prefix_abilities; ++i) {
            check_ability(&t, &prefix_abilities[i]);
        }
        for (size_t i = 0u; i < n_new_abilities; ++i) {
            check_ability(&t, &new_abilities[i]);
        }
        uint32_t stray = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            if (!listed(prefix_items, n_prefix_items, id) && !listed(new_items, n_new_items, id)) {
                stray += dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE ||
                                 dfi_pool_item_family[id].type != DFI_FAMILY_PARAM_NONE
                             ? 1u
                             : 0u;
            }
        }
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            if (!listed(prefix_abilities, n_prefix_abilities, id) && !listed(new_abilities, n_new_abilities, id)) {
                stray += dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE ||
                                 dfi_pool_ability_family[id].param != DFI_FAMILY_PARAM_NONE
                             ? 1u
                             : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, stray, 0u);
        /* Every id appears once in the lists: the prefix items are the three
         * named, so the other 13 prefix items are the ids without a family. */
        DF_CHECK_EQ_U64(&t, n_prefix_items + n_new_items, 3u + 33u);
        DF_CHECK_EQ_U64(&t, n_prefix_abilities, 6u);
        /* All 18: each type has exactly one booster and one resist berry. */
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            uint32_t boosters = 0u;
            uint32_t berries = 0u;
            for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
                boosters += dfi_pool_item_family[id].family == DFI_ITEM_FAMILY_TYPE_BOOSTER &&
                                    dfi_pool_item_family[id].type == type
                                ? 1u
                                : 0u;
                berries += dfi_pool_item_family[id].family == DFI_ITEM_FAMILY_RESIST_BERRY &&
                                   dfi_pool_item_family[id].type == type
                               ? 1u
                               : 0u;
            }
            if (!DF_CHECK(&t, boosters == 1u && berries == 1u)) {
                fprintf(stderr, "  type %u: %u boosters and %u resist berries\n", type, boosters, berries);
            }
        }
    }

    /* The legal moves and abilities of the formes. A bit per pool move, in as
     * many bytes as the moves need. The literal cases above are the answers of the validator for the formes of the
     * closure, Team C and G2 and for the 72 moves of those steps; the whole pool has more moves and abilities for
     * the same formes, so a case holds for the moves below G2_MOVES and its abilities are listed in the forme's
     * list in that order. Every other base forme is checked against the validator by pool_families.js and against
     * legal_pool.json by pool_rows.py. A Mega forme has no learnable move and its one ability. */
    {
        DF_CHECK_EQ_U64(&t, DFI_POOL_LEARN_BYTES, (DFI_POOL_MOVE_COUNT + 7u) / 8u);
        DF_CHECK_EQ_U64(&t, DFI_POOL_LEARN_BYTES, 64u);
        DF_CHECK_EQ_U64(&t, DFI_POOL_FORME_ABILITIES_MAX, 3u);
        uint32_t base_formes = 0u;
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            base_formes += dfi_pool_formes[f].is_mega == 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, base_formes, 264u);
        uint32_t seen = 0u;
        for (size_t c = 0u; c < sizeof legal_formes / sizeof legal_formes[0]; ++c) {
            const legal_case *lc = &legal_formes[c];
            const dfi_forme_legal *l = &dfi_pool_forme_legal[lc->forme];
            DF_CHECK(&t, dfi_pool_formes[lc->forme].is_mega == 0u);
            seen += 1u;
            uint32_t wrong = 0u;
            for (uint32_t move = 0u; move < G2_MOVES; ++move) {
                bool listed_move = false;
                for (uint32_t k = 0u; k < lc->move_count; ++k) {
                    listed_move = listed_move || lc->moves[k] == move;
                }
                wrong += bit_of(l->learnable, move) != listed_move ? 1u : 0u;
            }
            /* No bit beyond the last pool move. */
            for (uint32_t move = DFI_POOL_MOVE_COUNT; move < DFI_POOL_LEARN_BYTES * 8u; ++move) {
                wrong += bit_of(l->learnable, move) ? 1u : 0u;
            }
            /* The abilities of the case, in the case's order, within the forme's list (at most three). */
            wrong += l->ability_count < lc->ability_count || l->ability_count > DFI_POOL_FORME_ABILITIES_MAX ? 1u : 0u;
            uint32_t from = 0u;
            for (uint32_t k = 0u; k < lc->ability_count; ++k) {
                while (from < l->ability_count && l->abilities[from] != lc->abilities[k]) {
                    from += 1u;
                }
                wrong += from >= l->ability_count ? 1u : 0u;
                from += 1u;
            }
            for (uint32_t k = l->ability_count; k < DFI_POOL_FORME_ABILITIES_MAX; ++k) {
                wrong += l->abilities[k] != DFI_CLOSURE_NONE ? 1u : 0u;
            }
            if (!DF_CHECK(&t, wrong == 0u)) {
                fprintf(stderr, "  forme %u: %u wrong bits or abilities\n", lc->forme, wrong);
            }
            /* The forme's own set is legal for it. */
            const dfi_pool_forme_data *f = &dfi_pool_formes[lc->forme];
            uint32_t outside = 0u;
            for (uint32_t k = 0u; k < f->set_move_count; ++k) {
                outside += bit_of(l->learnable, f->set_moves[k]) ? 0u : 1u;
            }
            bool own = false;
            for (uint32_t k = 0u; k < l->ability_count; ++k) {
                own = own || l->abilities[k] == f->ability;
            }
            DF_CHECK(&t, outside == 0u && own);
        }
        DF_CHECK_EQ_U64(&t, seen, 22u); /* the base formes of the closure, Team C and G2: 28 rows less 6 Mega formes */
        uint32_t odd = 0u;
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            const dfi_forme_legal *l = &dfi_pool_forme_legal[f];
            if (dfi_pool_formes[f].is_mega != 0u) {
                for (uint32_t k = 0u; k < DFI_POOL_LEARN_BYTES; ++k) {
                    odd += l->learnable[k] != 0u ? 1u : 0u;
                }
                odd += l->ability_count != 1u || l->abilities[0] != dfi_pool_formes[f].ability ||
                               l->abilities[1] != DFI_CLOSURE_NONE || l->abilities[2] != DFI_CLOSURE_NONE
                           ? 1u
                           : 0u;
            }
            /* Nobody learns Struggle, and every legal ability is in the pool. */
            odd += bit_of(l->learnable, DFI_MOVE_STRUGGLE) ? 1u : 0u;
            for (uint32_t k = 0u; k < l->ability_count; ++k) {
                odd += l->abilities[k] >= DFI_POOL_ABILITY_COUNT ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, odd, 0u);
    }

    /* The encodings of the columns: the family values are the table's own,
     * and the weather and terrain codes are the state values of the engine,
     * which P2 reads without a translation. */
    DF_CHECK_EQ_U64(&t, DFI_FAMILY_WEATHER_RAIN, DFI_WEATHER_RAIN);
    DF_CHECK_EQ_U64(&t, DFI_FAMILY_WEATHER_SUN, DFI_WEATHER_SUN);
    DF_CHECK_EQ_U64(&t, DFI_FAMILY_TERRAIN_GRASSY, DFI_TERRAIN_GRASSY);
    DF_CHECK_EQ_U64(&t, DFI_FAMILY_TERRAIN_PSYCHIC, DFI_TERRAIN_PSYCHIC);
    DF_CHECK_EQ_U64(&t, DFI_FAMILY_PARAM_NONE, DFI_CLOSURE_NONE);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_FAMILY_NONE, 0u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_FAMILY_NONE, 0u);
    DF_CHECK(&t, DFI_ITEM_FAMILY_TYPE_BOOSTER != DFI_ITEM_FAMILY_RESIST_BERRY);
    DF_CHECK(&t, DFI_ABILITY_FAMILY_ATE != DFI_ABILITY_FAMILY_PINCH &&
                     DFI_ABILITY_FAMILY_WEATHER_SETTER != DFI_ABILITY_FAMILY_TERRAIN_SETTER);

    /* The support manifest covers the pool ids. Step P2 made the two item
     * families rules and step P3 the two ability families (the "-ate" and
     * pinch ones): every new item and ability of those steps is marked, and
     * so is every item and ability with a family column that makes it a rule,
     * the prefix included. Step G2 adds the items Focus Sash, Expert Belt and
     * Floettite and the abilities Rock Head, Flower Veil and Fairy Aura (none
     * has a family): they stay unmarked until the steps that make them rules,
     * and so do the G2 moves apart from the twelve marked with the recorded
     * battles that test them. */
    {
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.moves, DFI_POOL_MOVE_COUNT);
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.abilities, DFI_POOL_ABILITY_COUNT);
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.items, DFI_POOL_ITEM_COUNT);
        for (uint32_t id = DFI_EXT_ITEM_COUNT; id < DFI_ITEM_FOCUSSASH; ++id) {
            DF_CHECK(&t, dfi_support.items[id] != 0u);
            DF_CHECK(&t, dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE);
        }
        /* Step G4 marks Focus Sash (onDamage at the move-damage call); Expert Belt and Floettite stay unmarked. */
        DF_CHECK(&t, dfi_support.items[DFI_ITEM_FOCUSSASH] != 0u);
        for (uint32_t id = DFI_ITEM_FOCUSSASH + 1u; id < DFI_POOL_ITEM_COUNT; ++id) {
            DF_CHECK_EQ_U64(&t, dfi_support.items[id], 0u);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            if (dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.items[id] != 0u);
            }
        }
        /* The P1 abilities (Pixilate to Swarm, ids below Rock Head) are marked by step P3 and have a family; the
         * G2 abilities after them have none, and of those only Rock Head is marked (step G4: no recoil from a
         * recoil move), Flower Veil and Fairy Aura stay unmarked until their steps. */
        for (uint32_t id = DFI_EXT_ABILITY_COUNT; id < DFI_ABILITY_ROCKHEAD; ++id) {
            DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            DF_CHECK(&t, dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = DFI_ABILITY_ROCKHEAD; id < DFI_POOL_ABILITY_COUNT; ++id) {
            DF_CHECK_EQ_U64(&t, dfi_support.abilities[id] != 0u ? 1u : 0u, id == DFI_ABILITY_ROCKHEAD ? 1u : 0u);
            DF_CHECK_EQ_U64(&t, dfi_pool_ability_family[id].family, DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            if (dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            }
        }
        /* Step G2 marks twelve of its 22 moves, each used in a reference battle under the POOL kind (g2_data_moves_a
         * to _d); U-turn (its switch cause is G5) and the nine moves with a handler id stay unmarked. */
        static const uint32_t marked_moves[] = {DFI_MOVE_ROCKSLIDE, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_THUNDERBOLT,
                                                DFI_MOVE_FLASHCANNON, DFI_MOVE_EXTREMESPEED, DFI_MOVE_HEADSMASH,
                                                DFI_MOVE_BULKUP, DFI_MOVE_LIQUIDATION, DFI_MOVE_ICEPUNCH,
                                                DFI_MOVE_SHADOWCLAW, DFI_MOVE_DRUMBEATING, DFI_MOVE_DAZZLINGGLEAM};
        uint32_t marked_count = 0u;
        for (uint32_t id = DFI_EXT_MOVE_COUNT; id < DFI_POOL_MOVE_COUNT; ++id) {
            bool want = false;
            for (size_t k = 0u; k < sizeof marked_moves / sizeof marked_moves[0]; ++k) {
                want = want || marked_moves[k] == id;
            }
            DF_CHECK_EQ_U64(&t, dfi_support.moves[id] != 0u ? 1u : 0u, want ? 1u : 0u);
            /* A marked move has no handler id: the engine has no code for one. */
            DF_CHECK(&t, !want || dfi_pool_moves[id].special == DFI_SPECIAL_NONE);
            marked_count += dfi_support.moves[id] != 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, marked_count, 12u);
    }

    /* The whole-pool rows: what the tables model and what they do not (decision 0015 section 4.2). A move, item or
     * ability row that has any callback, field, target class or flag that the tables do not model carries the UNMODELED
     * handler (the move's special column, the handler column of an item or an ability) and a list of those features;
     * the three always agree. The closure, Team C and G2 rows are never UNMODELED: the closure and Team C rows are
     * code in the turn core, the G2 moves with a callback have a handler id of their own, and of the G2 items and
     * abilities the engine implements Focus Sash and Rock Head by id (ENGINE_ROWS of the generator). */
    {
        uint32_t odd = 0u;
        uint32_t unmodeled_moves = 0u;
        uint32_t unmodeled_items = 0u;
        uint32_t unmodeled_abilities = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            const bool handler = dfi_pool_moves[id].special == DFI_SPECIAL_UNMODELED;
            const bool listed = dfi_pool_move_unmodeled[id] != NULL;
            odd += handler != listed ? 1u : 0u;
            odd += listed && dfi_pool_move_unmodeled[id][0] == '\0' ? 1u : 0u;
            odd += id < G2_MOVES && handler ? 1u : 0u;
            odd += dfi_pool_moves[id].special > DFI_SPECIAL_UNMODELED ? 1u : 0u;
            unmodeled_moves += handler ? 1u : 0u;
        }
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            const bool handler = dfi_pool_item_handler[id] == DFI_HANDLER_UNMODELED;
            const bool listed = dfi_pool_item_unmodeled[id] != NULL;
            odd += dfi_pool_item_handler[id] > DFI_HANDLER_UNMODELED ? 1u : 0u;
            odd += handler != listed ? 1u : 0u;
            odd += listed && dfi_pool_item_unmodeled[id][0] == '\0' ? 1u : 0u;
            odd += id < DFI_EXT_ITEM_COUNT && handler ? 1u : 0u;
            odd += dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE && handler ? 1u : 0u; /* a family is a rule */
            unmodeled_items += handler ? 1u : 0u;
        }
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            const bool handler = dfi_pool_ability_handler[id] == DFI_HANDLER_UNMODELED;
            const bool listed = dfi_pool_ability_unmodeled[id] != NULL;
            odd += dfi_pool_ability_handler[id] > DFI_HANDLER_UNMODELED ? 1u : 0u;
            odd += handler != listed ? 1u : 0u;
            odd += listed && dfi_pool_ability_unmodeled[id][0] == '\0' ? 1u : 0u;
            odd += id < DFI_EXT_ABILITY_COUNT && handler ? 1u : 0u;
            odd += dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE && handler ? 1u : 0u;
            unmodeled_abilities += handler ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, odd, 0u);
        /* The counts are pinned: a change of the generator's rules or of the pin moves them, and is reviewed. */
        DF_CHECK_EQ_U64(&t, unmodeled_moves, UNMODELED_MOVES);
        DF_CHECK_EQ_U64(&t, unmodeled_items, UNMODELED_ITEMS);
        DF_CHECK_EQ_U64(&t, unmodeled_abilities, UNMODELED_ABILITIES);
        /* The rows of the steps. */
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_FOCUSSASH] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_ROCKHEAD] == DFI_HANDLER_NONE);
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_EXPERTBELT] == DFI_HANDLER_UNMODELED &&
                         dfi_pool_ability_handler[DFI_ABILITY_FLOWERVEIL] == DFI_HANDLER_UNMODELED &&
                         dfi_pool_ability_handler[DFI_ABILITY_FAIRYAURA] == DFI_HANDLER_UNMODELED);
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_FLOETTITE] == DFI_HANDLER_NONE); /* a Mega Stone: data of its link */
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_UTURN].special == DFI_SPECIAL_NONE);
        /* A few whole-pool rows, by what the pin says. Earthquake: allAdjacent, a class that the turn code lacks;
         * Hydro Pump: pure data; Substitute: a volatile with callbacks; Stealth Rock: a side condition and a class
         * that the closure lacks; Absolite Z: the second Mega Stone of Absol; Damp Rock: no callback, read by id in
         * data/conditions.ts; Levitate: no callback, read by id elsewhere; Intimidate: code in the turn core. */
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_EARTHQUAKE].special == DFI_SPECIAL_UNMODELED &&
                         dfi_pool_moves[DFI_MOVE_EARTHQUAKE].target_class == DFI_TARGET_CLASS_ALL_ADJACENT &&
                         strcmp(dfi_pool_move_unmodeled[DFI_MOVE_EARTHQUAKE], "target allAdjacent") == 0);
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_HYDROPUMP].special == DFI_SPECIAL_NONE &&
                         dfi_pool_move_unmodeled[DFI_MOVE_HYDROPUMP] == NULL && dfi_pool_moves[DFI_MOVE_HYDROPUMP].base_power == 110u &&
                         dfi_pool_moves[DFI_MOVE_HYDROPUMP].accuracy == 80u);
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_SUBSTITUTE].special == DFI_SPECIAL_UNMODELED &&
                         strstr(dfi_pool_move_unmodeled[DFI_MOVE_SUBSTITUTE], "primary volatile substitute") != NULL);
        DF_CHECK(&t, strstr(dfi_pool_move_unmodeled[DFI_MOVE_STEALTHROCK], "side condition stealthrock") != NULL &&
                         strstr(dfi_pool_move_unmodeled[DFI_MOVE_STEALTHROCK], "target foeSide") != NULL &&
                         dfi_pool_moves[DFI_MOVE_STEALTHROCK].side_condition == 0u);
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_ABSOLITEZ] == DFI_HANDLER_UNMODELED &&
                         strstr(dfi_pool_item_unmodeled[DFI_ITEM_ABSOLITEZ], "second Mega forme absolmegaz") != NULL &&
                         dfi_pool_item_handler[DFI_ITEM_ABSOLITE] == DFI_HANDLER_NONE);
        DF_CHECK(&t, strcmp(dfi_pool_item_unmodeled[DFI_ITEM_DAMPROCK], "read by id in data/conditions.ts") == 0);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_LEVITATE] == DFI_HANDLER_UNMODELED &&
                         strstr(dfi_pool_ability_unmodeled[DFI_ABILITY_LEVITATE], "read by id in sim/pokemon.ts") != NULL);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_INTIMIDATE] == DFI_HANDLER_NONE);
        /* The target classes of the pool beyond the public ones: encoded, never a public value. */
        DF_CHECK_EQ_U64(&t, DFI_TARGET_CLASS_ALL_ADJACENT, 11u);
        DF_CHECK(&t, DFI_TARGET_CLASS_FOE_SIDE == 15u && DFI_TARGET_CLASS_FOE_SIDE > DFI_TARGET_CLASS_RANDOM_NORMAL);
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            /* A target class beyond the closure's is never in a modelled row. */
            DF_CHECK(&t, dfi_pool_moves[id].target_class <= DFI_TARGET_CLASS_RANDOM_NORMAL ||
                             dfi_pool_moves[id].special == DFI_SPECIAL_UNMODELED);
            /* The effect columns of an UNMODELED row are neutral: it claims nothing beyond its plain data. */
            if (dfi_pool_moves[id].special == DFI_SPECIAL_UNMODELED) {
                const dfi_move_data *m = &dfi_pool_moves[id];
                DF_CHECK(&t, m->sec_chance == 0u && m->sec_kind == 0u && m->sec_param == 0u && m->boost_role == 0u &&
                                 m->primary_status == 0u && m->side_condition == 0u && m->pseudo_weather == 0u);
            }
        }
    }

    /* Nothing half-modelled reaches a marked row: no mark in the support manifest on a row with the UNMODELED
     * handler or a list of unmodelled features. The check is made on the manifest of this build and, to show that it
     * can fail, on copies that mark one UNMODELED row of each table. */
    {
        DF_CHECK_EQ_U64(&t, half_modelled_marks(&dfi_support), 0u);
        uint32_t seen = 0u;
        for (uint32_t table = 0u; table < 3u; ++table) {
            const uint32_t count = table == 0u ? DFI_POOL_MOVE_COUNT : table == 1u ? DFI_POOL_ITEM_COUNT : DFI_POOL_ABILITY_COUNT;
            for (uint32_t id = 0u; id < count; ++id) {
                const bool unmodeled = table == 0u   ? dfi_pool_moves[id].special == DFI_SPECIAL_UNMODELED
                                       : table == 1u ? dfi_pool_item_handler[id] == DFI_HANDLER_UNMODELED
                                                     : dfi_pool_ability_handler[id] == DFI_HANDLER_UNMODELED;
                if (!unmodeled) {
                    continue;
                }
                dfi_support_manifest copy = dfi_support;
                (table == 0u ? copy.moves : table == 1u ? copy.items : copy.abilities)[id] = 1u;
                DF_CHECK_EQ_U64(&t, half_modelled_marks(&copy), 1u);
                seen += 1u;
                break;
            }
        }
        DF_CHECK_EQ_U64(&t, seen, 3u);
        /* A modelled row that is not marked is no half-modelled mark (the whole pool is unmarked beyond the steps). */
        dfi_support_manifest copy = dfi_support;
        copy.moves[DFI_MOVE_HYDROPUMP] = 1u;
        DF_CHECK_EQ_U64(&t, half_modelled_marks(&copy), 0u);
    }

    /* A Mega forme that its base forme does not link is not reachable: the second Mega formes of Absol, Charizard,
     * Garchomp, Lucario and Raichu are rows, and every manifest says that Mega Evolution into them is unsupported. */
    {
        uint32_t second = 0u;
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            if (dfi_pool_formes[f].is_mega != 0u && dfi_pool_formes[dfi_pool_formes[f].base_forme].mega_forme != f) {
                second += 1u;
            }
        }
        DF_CHECK_EQ_U64(&t, second, 5u);
    }

    return df_test_end(&t);
}
