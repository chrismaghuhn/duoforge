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

#define POOL_HASH_HEX "339834fa89c91b20ac6a5fb60d7ce6cba68645d606724c18da980d0c5e7c3288"

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
    uint32_t moves[16];
    uint32_t ability_count;
    uint32_t abilities[3];
} legal_case;

/* The pool moves that each base forme learns (the validator accepts a set
 * with that one move) and its legal abilities that are in the pool, in the
 * pokedex's slot order. The abilities of the pokedex that the pool does not
 * have (Reckless, Solar Power, Moxie, ...) are not listed. */
static const legal_case legal_formes[] = {
    {DFI_FORME_RILLABOOM, 10, {
        DFI_MOVE_WOODHAMMER, DFI_MOVE_GRASSYGLIDE, DFI_MOVE_FAKEOUT, DFI_MOVE_HIGHHORSEPOWER, DFI_MOVE_PROTECT,
        DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_SNARL, DFI_MOVE_GRASSKNOT, DFI_MOVE_HYPERVOICE
     },
     2, {DFI_ABILITY_OVERGROW, DFI_ABILITY_GRASSYSURGE}},
    {DFI_FORME_STARAPTOR, 8, {
        DFI_MOVE_BRAVEBIRD, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_TAILWIND, DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_HEATWAVE, DFI_MOVE_HURRICANE, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_MILOTIC, 11, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_COIL, DFI_MOVE_ICEBEAM, DFI_MOVE_HYPNOSIS,
        DFI_MOVE_WEATHERBALL, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HELPINGHAND,
        DFI_MOVE_FLIPTURN
     },
     1, {DFI_ABILITY_COMPETITIVE}},
    {DFI_FORME_CERULEDGE, 12, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_BITTERBLADE, DFI_MOVE_SHADOWSNEAK, DFI_MOVE_SWORDSDANCE,
        DFI_MOVE_SHADOWBALL, DFI_MOVE_IRONHEAD, DFI_MOVE_HEATWAVE, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN,
        DFI_MOVE_FLAREBLITZ, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_FLASHFIRE}},
    {DFI_FORME_RAICHU, 9, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_ZAPCANNON, DFI_MOVE_FOCUSBLAST, DFI_MOVE_NASTYPLOT,
        DFI_MOVE_GRASSKNOT, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_LIGHTNINGROD}},
    {DFI_FORME_GHOLDENGO, 9, {
        DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST, DFI_MOVE_MAKEITRAIN, DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT,
        DFI_MOVE_IRONHEAD, DFI_MOVE_PSYCHIC, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN
     },
     1, {DFI_ABILITY_GOODASGOLD}},
    {DFI_FORME_POLITOED, 9, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_HYPNOSIS, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_WEATHERBALL, DFI_MOVE_PSYCHIC, DFI_MOVE_HYPERVOICE, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_DRIZZLE}},
    {DFI_FORME_GOLISOPOD, 12, {
        DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_SWORDSDANCE,
        DFI_MOVE_FOCUSBLAST, DFI_MOVE_LEECHLIFE, DFI_MOVE_IRONHEAD, DFI_MOVE_DRILLRUN, DFI_MOVE_SNARL,
        DFI_MOVE_SUCKERPUNCH, DFI_MOVE_AQUAJET
     },
     1, {DFI_ABILITY_EMERGENCYEXIT}},
    {DFI_FORME_ARCHALUDON, 9, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_ELECTROSHOT,
        DFI_MOVE_SNARL, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_DRACOMETEOR
     },
     1, {DFI_ABILITY_STAMINA}},
    {DFI_FORME_FARIGIRAF, 12, {
        DFI_MOVE_HIGHHORSEPOWER, DFI_MOVE_PROTECT, DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT, DFI_MOVE_IRONHEAD,
        DFI_MOVE_PSYCHIC, DFI_MOVE_GRASSKNOT, DFI_MOVE_TRICKROOM, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN,
        DFI_MOVE_HYPERVOICE, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_ARMORTAIL}},
    {DFI_FORME_CHARIZARD, 9, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_WEATHERBALL, DFI_MOVE_DRAGONPULSE,
        DFI_MOVE_HEATWAVE, DFI_MOVE_HURRICANE, DFI_MOVE_FLAREBLITZ, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_BLAZE}},
    {DFI_FORME_GRIMMSNARL, 10, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_FOCUSBLAST, DFI_MOVE_NASTYPLOT, DFI_MOVE_LEECHLIFE,
        DFI_MOVE_SPIRITBREAK, DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_PARTINGSHOT, DFI_MOVE_SUCKERPUNCH
     },
     1, {DFI_ABILITY_PRANKSTER}},
    {DFI_FORME_SNEASLER, 9, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_SHADOWBALL, DFI_MOVE_NASTYPLOT, DFI_MOVE_GRASSKNOT, DFI_MOVE_DIRECLAW
     },
     1, {DFI_ABILITY_UNBURDEN}},
    {DFI_FORME_INCINEROAR, 14, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST,
        DFI_MOVE_NASTYPLOT, DFI_MOVE_LEECHLIFE, DFI_MOVE_IRONHEAD, DFI_MOVE_SNARL, DFI_MOVE_HEATWAVE,
        DFI_MOVE_PARTINGSHOT, DFI_MOVE_FLAREBLITZ, DFI_MOVE_DARKESTLARIAT, DFI_MOVE_HELPINGHAND
     },
     2, {DFI_ABILITY_BLAZE, DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_SALAMENCE, 9, {
        DFI_MOVE_TAILWIND, DFI_MOVE_PROTECT, DFI_MOVE_IRONHEAD, DFI_MOVE_DRAGONPULSE, DFI_MOVE_HEATWAVE,
        DFI_MOVE_HURRICANE, DFI_MOVE_HYPERVOICE, DFI_MOVE_DRACOMETEOR, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_INTIMIDATE}},
    {DFI_FORME_INDEEDEEF, 10, {
        DFI_MOVE_FAKEOUT, DFI_MOVE_PROTECT, DFI_MOVE_SHADOWBALL, DFI_MOVE_PSYCHIC, DFI_MOVE_TRICKROOM,
        DFI_MOVE_REFLECT, DFI_MOVE_LIGHTSCREEN, DFI_MOVE_HYPERVOICE, DFI_MOVE_FOLLOWME, DFI_MOVE_HELPINGHAND
     },
     1, {DFI_ABILITY_PSYCHICSURGE}},
    {DFI_FORME_KINGAMBIT, 8, {
        DFI_MOVE_PROTECT, DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_IRONHEAD, DFI_MOVE_SNARL,
        DFI_MOVE_GRASSKNOT, DFI_MOVE_KOWTOWCLEAVE, DFI_MOVE_SUCKERPUNCH
     },
     1, {DFI_ABILITY_DEFIANT}},
    {DFI_FORME_BASCULEGION, 8, {
        DFI_MOVE_PROTECT, DFI_MOVE_MUDDYWATER, DFI_MOVE_ICEBEAM, DFI_MOVE_SHADOWBALL, DFI_MOVE_LASTRESPECTS,
        DFI_MOVE_WAVECRASH, DFI_MOVE_AQUAJET, DFI_MOVE_FLIPTURN
     },
     1, {DFI_ABILITY_ADAPTABILITY}},
};

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

    /* Counts: the extended formes and moves, 16 + 33 items (16 type boosters
     * and 17 resist berries are new) and 21 + 5 abilities. The new ids start
     * where the extended ones end. */
    DF_CHECK_EQ_U64(&t, DFI_POOL_FORME_COUNT, DFI_EXT_FORME_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_POOL_MOVE_COUNT, DFI_EXT_MOVE_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_POOL_ITEM_COUNT, 49u);
    DF_CHECK_EQ_U64(&t, DFI_POOL_ABILITY_COUNT, 26u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_BLACKBELT, DFI_EXT_ITEM_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_YACHEBERRY, DFI_POOL_ITEM_COUNT - 1u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_TWISTEDSPOON, DFI_EXT_ITEM_COUNT + 15u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_BABIRIBERRY, DFI_EXT_ITEM_COUNT + 16u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_PIXILATE, DFI_EXT_ABILITY_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_SWARM, DFI_POOL_ABILITY_COUNT - 1u);
    DF_CHECK_EQ_U64(&t, n_new_items, DFI_POOL_ITEM_COUNT - DFI_EXT_ITEM_COUNT);
    DF_CHECK_EQ_U64(&t, n_new_abilities, DFI_POOL_ABILITY_COUNT - DFI_EXT_ABILITY_COUNT);

    /* The prefix is the extended tables, and so the closure, row by row. */
    {
        uint32_t diff = 0u;
        for (uint32_t i = 0u; i < DFI_EXT_FORME_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_formes[i], (const uint8_t *)&dfi_ext_formes[i],
                                    sizeof dfi_pool_formes[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_EXT_MOVE_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_moves[i], (const uint8_t *)&dfi_ext_moves[i],
                                    sizeof dfi_pool_moves[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_EXT_ITEM_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_items[i], (const uint8_t *)&dfi_ext_items[i],
                                    sizeof dfi_pool_items[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_FORME_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_formes[i], (const uint8_t *)&dfi_closure_formes[i],
                                    sizeof dfi_pool_formes[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_MOVE_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_moves[i], (const uint8_t *)&dfi_closure_moves[i],
                                    sizeof dfi_pool_moves[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_ITEM_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_pool_items[i], (const uint8_t *)&dfi_closure_items[i],
                                    sizeof dfi_pool_items[i]) ? 0u : 1u;
        }
        /* The type immunity bits are the extended ones (the closure's plus
         * psn); the pool adds no type. */
        diff += dfi_bytes_equal(dfi_pool_type_immunity, dfi_ext_type_immunity, DFI_TYPE_COUNT) ? 0u : 1u;
        DF_CHECK_EQ_U64(&t, diff, 0u);
    }

    /* The new items are no Mega Stone: no forme holds one as its stone. */
    {
        uint32_t stones = 0u;
        for (uint32_t i = DFI_EXT_ITEM_COUNT; i < DFI_POOL_ITEM_COUNT; ++i) {
            stones += dfi_pool_items[i].mega_base != DFI_CLOSURE_NONE || dfi_pool_items[i].mega_forme != DFI_CLOSURE_NONE
                          ? 1u
                          : 0u;
        }
        DF_CHECK_EQ_U64(&t, stones, 0u);
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

    /* The pool hash: SHA-256 of the pool canonical bytes, which are the
     * closure layout over every pool row followed by the family columns (an
     * item's family and type, then an ability's family and parameter, in id
     * order) and the legal moves and abilities of the formes (per forme the
     * learnable bytes, the ability count and the three ability ids); equal to
     * the generator's literal and different from the other two. */
    {
        uint8_t bytes[DFI_POOL_CANONICAL_SIZE + 8u];
        uint8_t rows[DFI_POOL_CANONICAL_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        memset(bytes, 0xA5, sizeof bytes);
        const size_t n = dfi_pool_canonical_bytes(bytes, sizeof bytes);
        DF_CHECK_EQ_U64(&t, n, DFI_POOL_CANONICAL_SIZE);
        /* 12 + 23 * 24 + 50 * 29 + 49 * 2 + 324 + 18 + 50, then 49 * 2 + 26 * 2,
         * then 23 * (7 + 1 + 3) */
        DF_CHECK_EQ_U64(&t, DFI_POOL_CANONICAL_SIZE, 2907u);
        DF_CHECK(&t, bytes[DFI_POOL_CANONICAL_SIZE] == 0xA5u);
        const size_t row_bytes = dfi_pool_canonical_bytes_of(rows, sizeof rows, DFI_POOL_FORME_COUNT,
                                                             DFI_POOL_MOVE_COUNT, DFI_POOL_ITEM_COUNT,
                                                             DFI_POOL_ABILITY_COUNT, 0xFFu);
        DF_CHECK_EQ_U64(&t, row_bytes, 2504u);
        DF_CHECK_BYTES(&t, bytes, rows, row_bytes, "pool rows");
        uint32_t at = (uint32_t)row_bytes;
        uint32_t bad = 0u;
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
        DF_CHECK_EQ_U64(&t, bad, 0u);
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
        /* A buffer that is too small gets nothing; counts beyond the tables
         * are refused. */
        uint8_t small[16];
        memset(small, 0xA5, sizeof small);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes(small, sizeof small), 0u);
        DF_CHECK(&t, small[0] == 0xA5u && small[15] == 0xA5u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes(bytes, DFI_POOL_CANONICAL_SIZE - 1u), 0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, DFI_POOL_FORME_COUNT + 1u,
                                                        DFI_POOL_MOVE_COUNT, DFI_POOL_ITEM_COUNT,
                                                        DFI_POOL_ABILITY_COUNT, 0xFFu),
                        0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, DFI_POOL_FORME_COUNT,
                                                        DFI_POOL_MOVE_COUNT, DFI_POOL_ITEM_COUNT + 1u,
                                                        DFI_POOL_ABILITY_COUNT, 0xFFu),
                        0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_canonical_bytes_of(bytes, sizeof bytes, DFI_POOL_FORME_COUNT,
                                                        DFI_POOL_MOVE_COUNT, DFI_POOL_ITEM_COUNT,
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
     * many bytes as the moves need; the base formes are the literal cases
     * above, a Mega forme has no learnable move and its one ability. */
    {
        DF_CHECK_EQ_U64(&t, DFI_POOL_LEARN_BYTES, (DFI_POOL_MOVE_COUNT + 7u) / 8u);
        DF_CHECK_EQ_U64(&t, DFI_POOL_LEARN_BYTES, 7u);
        DF_CHECK_EQ_U64(&t, DFI_POOL_FORME_ABILITIES_MAX, 3u);
        uint32_t base_formes = 0u;
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            base_formes += dfi_pool_formes[f].is_mega == 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, base_formes, sizeof legal_formes / sizeof legal_formes[0]);
        uint32_t seen = 0u;
        for (size_t c = 0u; c < sizeof legal_formes / sizeof legal_formes[0]; ++c) {
            const legal_case *lc = &legal_formes[c];
            const dfi_forme_legal *l = &dfi_pool_forme_legal[lc->forme];
            DF_CHECK(&t, dfi_pool_formes[lc->forme].is_mega == 0u);
            seen += 1u;
            uint32_t wrong = 0u;
            for (uint32_t move = 0u; move < DFI_POOL_MOVE_COUNT; ++move) {
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
            wrong += l->ability_count != lc->ability_count ? 1u : 0u;
            for (uint32_t k = 0u; k < DFI_POOL_FORME_ABILITIES_MAX; ++k) {
                wrong += l->abilities[k] != (k < lc->ability_count ? lc->abilities[k] : DFI_CLOSURE_NONE) ? 1u : 0u;
            }
            if (!DF_CHECK(&t, wrong == 0u)) {
                fprintf(stderr, "  forme %u: %u wrong bits or abilities\n", lc->forme, wrong);
            }
            /* The forme's own set is legal for it. */
            const dfi_forme_data *f = &dfi_pool_formes[lc->forme];
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
        DF_CHECK_EQ_U64(&t, seen, base_formes);
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
     * pinch ones): every new item and ability is marked, and so is every
     * item and ability with a family column that makes it a rule, the prefix
     * included. */
    {
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.moves, DFI_POOL_MOVE_COUNT);
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.abilities, DFI_POOL_ABILITY_COUNT);
        DF_CHECK_EQ_U64(&t, sizeof dfi_support.items, DFI_POOL_ITEM_COUNT);
        for (uint32_t id = DFI_EXT_ITEM_COUNT; id < DFI_POOL_ITEM_COUNT; ++id) {
            DF_CHECK(&t, dfi_support.items[id] != 0u);
            DF_CHECK(&t, dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            if (dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.items[id] != 0u);
            }
        }
        for (uint32_t id = DFI_EXT_ABILITY_COUNT; id < DFI_POOL_ABILITY_COUNT; ++id) {
            DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            DF_CHECK(&t, dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            if (dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            }
        }
    }

    return df_test_end(&t);
}
