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
 * manifest; thirteen moves are marked (twelve in G2, U-turn in G5), and the nine handler moves are not.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/bytes.h"
#include "core/modifier.h"
#include "core/sha256.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"

#define POOL_HASH_HEX "45f3aa3336d9d497e9b38b16b157463aa124240be9e66475bdfa66f122ab2856" /* the canonical hash of the rows of the lane A batch (G42, G44, G46, G47, G48, G49, G50, G56, G52, G54) */
/* SHA-256 of the closure-layout bytes of the rows of the steps (P1 and G2: 28 formes, 72 moves, 52 items, 29
 * abilities). The whole-pool step must not move one of them (decision 0015 section 4.2); the pool generator before it
 * produced the same bytes. Step G10 moved two of them on purpose: Scald and Recover are data now (the thaw bit and
 * the heal column) and have the special NONE instead of the handler ids that G2 gave them, so the value is the
 * one the generator computes for the rows with that change and nothing else. */
#define STEPS_ROWS_HASH_HEX "b4d25af552d4c2d734289633b197c420901ecf924099dab578508d1e874c5635"

/* The counts of the rows of the steps, and of the whole pool (legal_pool.json: 264 distinct selectable formes and
 * 82 Mega formes, 510 moves and Struggle, 166 items, 215 abilities). */
#define G2_FORMES 28u
#define G2_MOVES 72u
#define G2_ITEMS 52u
#define G2_ABILITIES 29u
#define POOL_FORMES 346u
#define POOL_MOVES 511u
#define SOUND_MOVES 25u /* the pool moves with the pinned sound flag (duoforge.data.pool_regen reproduces the table from the pin) */
#define HEAL_MOVES 23u  /* and with the heal flag */
#define RECHARGE_MOVES 7u /* and with the recharge bit (step G17: flags2 bit 8): Blast Burn, Frenzy Plant, Giga Impact, Hydro Cannon, Hyper Beam, Meteor Assault, Rock Wrecker */
#define THAW_MOVES 3u   /* and with thawsTarget (step G10: flags2 bit 4): Scald, Matcha Gotcha, Scorching Sands */
#define POOL_ITEMS 166u
#define POOL_ABILITIES 215u

/* The rows that the tables do not model, pinned (the generator reports the same counts). */
#define UNMODELED_MOVES 189u /* 193 before step G62 (the merge of G62 onto G64) modelled Haze, After You and Quash; 196 before step G64 modelled Beat Up, Bug Bite, Poltergeist and Sheer Cold (decision 0015 item 5ca); 208 before step G42 modelled Roost and Stomping Tantrum; 217 before step G44 modelled Thunder, Power Trip, Ice Fang and Tri Attack (213 after it); 213 with the four of step G46 (Roar, Whirlwind, Dragon Tail, Circle Throw) removed too: 209; 221 before step G48 modelled Rage Fist, Population Bomb, Stone Axe and Ceaseless Edge; 225 before step G37 modelled Stealth Rock, Spikes, Toxic Spikes and Sticky Web (target foeSide, side conditions 5 to 8); 227 before step G31 modelled Taunt and Yawn; 230 before step G33 modelled Dual Wingbeat, Triple Axel and Twin Beam (its count was not carried through the batch merges); 246 before step G39 modelled Charm, Fake Tears, Sacred Sword, Super Fang and the twelve other status moves of one target with primary boosts; 250 before step G29 modelled Trick, Switcheroo, Thief and Covet; 251 before step G38 modelled Imprison; 252 before step G26 modelled Perish Song; 256 before step G25 modelled Electric Terrain, Misty Terrain, Rising Voltage and Terrain Pulse; 257 before step G27 modelled Disable; 260 before step G34 (262 before step G36 modelled Toxic and Poison Fang); 262 before step G34 modelled Steel Roller, Clangorous Soul and Brick Break (the other four rows of the step were already modelled); 273 before step G32 modelled Eruption, Water Spout, Life Dew, Body Press, Foul Play, Psyshock, Rain Dance, Sunny Day, Volt Switch, Clanging Scales and Freeze-Dry; 276 before step G30 modelled Rage Powder, Psychic Fangs and Solar Beam; 299 before step G28 modelled Acrobatics, Blizzard, Feint and the rows of the new secondary self boost (Ancient Power, Aqua Step, Charge Beam, Fiery Dance, Flame Charge, Meteor Mash, Psyshield Bash, Steel Wing, Torch Song, Trailblaze) and the allAdjacent moves; 300 before step G20 modelled Spiky Shield; 301 before it modelled Aurora Veil; 303 before step G19 modelled Coaching and Glaive Rush; 305u before step G15 modelled Expanding Force; 306 before step G16 modelled Knock Off; 313 before step G17 modelled the seven recharge moves; 319 before step G13 modelled Detect, Light of Ruin and the poison secondaries (Cross Poison, Gunk Shot, Poison Jab, Sludge Bomb); 324 before step G10 */
#define UNMODELED_ITEMS 23u /* five fewer since step G55 modelled Damp Rock, Heat Rock, Smooth Rock, Icy Rock and Terrain Extender; two fewer since step G47 made Lum Berry and Mental Herb engine rows; three fewer since step G49 modelled Muscle Band, Wise Glasses and Bright Powder; one fewer since step G46 modelled Red Card; two fewer since step G25 modelled Electric Seed and Misty Seed; one fewer since step G34 modelled Wide Lens; one fewer since step G32 modelled Eject Button; one fewer since step G28 modelled Expert Belt; five fewer since step G23-A found the Mega of a stone from (forme, stone); one fewer since step G15 modelled Psychic Seed */
#define UNMODELED_ABILITIES 117u /* six fewer since step G59 made Mega Launcher, Huge Power, Thick Fat, Fire Mane, Spicy Spray and Mega Sol engine rows; 123 before step G59; 124 before step G53 made Pressure an engine row; 125 before step G57 made Magic Bounce an engine row; 127 before step G51 made Keen Eye and Big Pecks engine rows; 129 before step G47 made Synchronize and Oblivious engine rows; 135 before step G45 made Steadfast, Moxie, Weak Armor, Telepathy, Volt Absorb and Punk Rock engine rows; 137 before step G46 made Suction Cups and Guard Dog engine rows; 138 before step G41 made Shadow Tag an engine row; 139 before step G37 made Toxic Debris an engine row; 152 before step G39 modelled thirteen abilities (Hyper Cutter, Regenerator, Solar Power, Scrappy, Infiltrator, Queenly Majesty, Damp, Sturdy, Snow Cloak, Sand Veil, Static, Justified, Limber); 153 before Mega batch 2 made Aura Guard an engine row; 154 before step G33 made Mirror Armor an engine row; 155 before step G25 made Electric Surge a terrain setter; 156 before step G27 made Cursed Body an engine row; 158 before step G35 made Rain Dish and Friend Guard engine rows; 165 before step G34 made Compound Eyes, Iron Fist, Sharpness, Solid Rock, Technician, Multiscale and Gale Wings engine rows; 168 before step G32 made Soundproof, Unnerve and Speed Boost engine rows; 172 before step G30 made Flame Body, Clear Body, Hospitality and Overcoat engine rows; 178 before step G22 made six abilities engine rows; 179 before step G23-C made Levitate an engine row; 180 before step AC1 made Trace an engine row; 181 before step G16 made Sticky Hold an engine row; 184 before step G14 made Rough Skin, Poison Touch and Thermal Exchange engine rows */

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

/* The weather setters of the Sandstorm and Snowscape step (their handlers are in data/abilities.ts: onStart sets
 * the weather, no Primal guard): table rules like Drizzle and Drought, marked by that step. */
static const family_case weather_abilities[] = {
    {DFI_ABILITY_SANDSTREAM, DFI_ABILITY_FAMILY_WEATHER_SETTER, DFI_WEATHER_SAND, "Sand Stream"},
    {DFI_ABILITY_SNOWWARNING, DFI_ABILITY_FAMILY_WEATHER_SETTER, DFI_WEATHER_SNOW, "Snow Warning"},
    {DFI_ABILITY_ELECTRICSURGE, DFI_ABILITY_FAMILY_TERRAIN_SETTER, DFI_FAMILY_TERRAIN_ELECTRIC, "Electric Surge"}, /* step G25 */
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
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 100u, DFI_SECONDARY_LOCKOUT, 0u, 0u, NB, 0u},
    {DFI_MOVE_ENCORE, "Encore", DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0u, 100u, 8u, 8u, 1u, 1u, DFI_MOVE_FLAG_PROTECT,
     {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_ENCORE},
    {DFI_MOVE_DOUBLEEDGE, "Double-Edge", DFI_TYPE_NORMAL, DFI_CATEGORY_PHYSICAL, 120u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT, {33u, 100u}, 0u, 0u, 0u, 0u, NB, 0u},
    {DFI_MOVE_THUNDERBOLT, "Thunderbolt", DFI_TYPE_ELECTRIC, DFI_CATEGORY_SPECIAL, 90u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 10u, DFI_SECONDARY_STATUS, DFI_STATUS_PAR, 0u, NB, 0u},
    {DFI_MOVE_SCALD, "Scald", DFI_TYPE_WATER, DFI_CATEGORY_SPECIAL, 80u, 100u, 16u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT | DFI_MOVE_FLAG_DEFROST, {0u, 0u}, 30u, DFI_SECONDARY_STATUS, DFI_STATUS_BRN, 0u, NB,
     DFI_SPECIAL_NONE}, /* step G10: thawsTarget is bit 4 of the second flags byte */
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
     0u, {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_NONE}, /* step G10: heal is the heal column */
    {DFI_MOVE_SOAK, "Soak", DFI_TYPE_WATER, DFI_CATEGORY_STATUS, 0u, 100u, 20u, 8u, 1u, 1u, DFI_MOVE_FLAG_PROTECT,
     {0u, 0u}, 0u, 0u, 0u, 0u, NB, DFI_SPECIAL_SOAK},
    {DFI_MOVE_PSYCHICNOISE, "Psychic Noise", DFI_TYPE_PSYCHIC, DFI_CATEGORY_SPECIAL, 75u, 100u, 12u, 8u, 1u, 1u,
     DFI_MOVE_FLAG_PROTECT, {0u, 0u}, 100u, DFI_SECONDARY_HEAL_BLOCK, 0u, 0u, NB, 0u},
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
         * psn) plus the pool's own bit, DFI_IMMUNE_SAND, which is set for Ground, Rock and Steel and for no other
         * type; the pool adds no type. */
        for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
            const bool sand = i == DFI_TYPE_GROUND || i == DFI_TYPE_ROCK || i == DFI_TYPE_STEEL;
            diff += dfi_pool_type_immunity[i] == (dfi_ext_type_immunity[i] | (sand ? DFI_IMMUNE_SAND : 0u)) ? 0u : 1u;
        }
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
            handlers += dfi_pool_moves[i].special >= DFI_SPECIAL_ENCORE &&
                                dfi_pool_moves[i].special <= DFI_SPECIAL_TRIPLE_AXEL
                            ? 1u
                            : 0u;
        }
        /* Seven ids of G2 remain after step G8 (Scald and Recover are not any move's after step G10), the two
         * weather moves (Sandstorm and Snowscape: the field `weather`, which no column models) have one each, and
         * Knock Off (step G16: its onAfterHit and onBasePower) the id after them. */
        DF_CHECK_EQ_U64(&t, handlers, DFI_SPECIAL_TRIPLE_AXEL - DFI_SPECIAL_ENCORE + 1u - 2u + 2u); /* step G33 adds two handlers for three moves (Dual Wingbeat and Twin Beam share one); step G15 adds Expanding Force's, step G20 Aurora Veil's and Spiky Shield's, step G30 Rage Powder's, Psychic Fangs' and Solar Beam's */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_ENCORE, DFI_SPECIAL_FOLLOW_ME + 1u);
        /* UNMODELED follows them. Step G10 made Scald and Recover data (the thaw bit and the heal column): their ids
         * are still defined, and no pool move has them. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_LOW_KICK + 1u, DFI_SPECIAL_SANDSTORM);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SANDSTORM + 1u, DFI_SPECIAL_SNOWSCAPE);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_KNOCK_OFF, DFI_SPECIAL_SNOWSCAPE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_EXPANDING_FORCE, DFI_SPECIAL_KNOCK_OFF + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_GLAIVE_RUSH, DFI_SPECIAL_EXPANDING_FORCE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_AURORA_VEIL, DFI_SPECIAL_GLAIVE_RUSH + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SPIKY_SHIELD, DFI_SPECIAL_AURORA_VEIL + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_RAGE_POWDER, DFI_SPECIAL_FEINT + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_PSYCHIC_FANGS, DFI_SPECIAL_RAGE_POWDER + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SOLAR_BEAM, DFI_SPECIAL_PSYCHIC_FANGS + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_STEEL_ROLLER, DFI_SPECIAL_CLANGING_SCALES + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_CLANGOROUS_SOUL, DFI_SPECIAL_STEEL_ROLLER + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_BRICK_BREAK, DFI_SPECIAL_CLANGOROUS_SOUL + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_DISABLE, DFI_SPECIAL_BRICK_BREAK + 1u); /* step G27, after the handlers of the other steps */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_DISABLE].special, DFI_SPECIAL_DISABLE);
        /* Step G25: the four handlers of the terrains, after step G27's Disable and before UNMODELED. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_ELECTRIC_TERRAIN, DFI_SPECIAL_DISABLE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_MISTY_TERRAIN, DFI_SPECIAL_ELECTRIC_TERRAIN + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_RISING_VOLTAGE, DFI_SPECIAL_MISTY_TERRAIN + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TERRAIN_PULSE, DFI_SPECIAL_RISING_VOLTAGE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_PERISH_SONG, DFI_SPECIAL_TERRAIN_PULSE + 1u); /* step G26, after the four of step G25 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_MULTI_HIT_2, DFI_SPECIAL_PERISH_SONG + 1u); /* step G33 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TRIPLE_AXEL, DFI_SPECIAL_MULTI_HIT_2 + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_IMPRISON, DFI_SPECIAL_TRIPLE_AXEL + 1u); /* step G38 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TRICK, DFI_SPECIAL_IMPRISON + 1u); /* step G29 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SUPER_FANG, DFI_SPECIAL_COVET + 1u); /* step G39 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TAUNT, DFI_SPECIAL_SUPER_FANG + 1u); /* step G31 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_YAWN, DFI_SPECIAL_TAUNT + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_RAGE_FIST, DFI_SPECIAL_YAWN + 1u); /* step G48, after the handlers of G31 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_STONE_AXE, DFI_SPECIAL_RAGE_FIST + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_CEASELESS_EDGE, DFI_SPECIAL_STONE_AXE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_MULTI_HIT_10, DFI_SPECIAL_CEASELESS_EDGE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_DOUBLE_SHOCK, DFI_SPECIAL_TRI_ATTACK + 1u); /* step G50 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_ROOST, DFI_SPECIAL_DOUBLE_SHOCK + 1u); /* step G42 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_STOMPING_TANTRUM, DFI_SPECIAL_ROOST + 1u); /* step G42 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_HAZE, DFI_SPECIAL_SHEER_COLD + 1u); /* step G62 (decision 0031), after the four of G64 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_AFTER_YOU, DFI_SPECIAL_HAZE + 1u); /* step G62 */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_QUASH, DFI_SPECIAL_AFTER_YOU + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_QUASH + 1u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TAUNT].special, DFI_SPECIAL_TAUNT);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_YAWN].special, DFI_SPECIAL_YAWN);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_PERISHSONG].special, DFI_SPECIAL_PERISH_SONG);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ELECTRICTERRAIN].special, DFI_SPECIAL_ELECTRIC_TERRAIN);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_MISTYTERRAIN].special, DFI_SPECIAL_MISTY_TERRAIN);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_RISINGVOLTAGE].special, DFI_SPECIAL_RISING_VOLTAGE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_RISINGVOLTAGE].base_power, 70u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TERRAINPULSE].special, DFI_SPECIAL_TERRAIN_PULSE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TERRAINPULSE].base_power, 50u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TERRAINPULSE].type, DFI_TYPE_NORMAL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ELECTRICTERRAIN].target_class, DUOFORGE_TARGET_CLASS_ALL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SPIKYSHIELD].special, DFI_SPECIAL_SPIKY_SHIELD);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SPIKY_SHIELD, 28u);
        /* Baneful Bunker and King's Shield stay unmodelled and unmarked: their learners have no supported ability. */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_BANEFULBUNKER].special, DFI_SPECIAL_UNMODELED);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_KINGSSHIELD].special, DFI_SPECIAL_UNMODELED);
        /* Step G28: the four handlers of the move rules, after Spiky Shield (G20) and before UNMODELED. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SHELL_SMASH, DFI_SPECIAL_SPIKY_SHIELD + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_ACROBATICS, DFI_SPECIAL_SHELL_SMASH + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_BLIZZARD, DFI_SPECIAL_ACROBATICS + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_FEINT, DFI_SPECIAL_BLIZZARD + 1u);
        /* Step G32: the eight handlers of the small rules, after the four of G28 and before UNMODELED. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_HP_POWER, DFI_SPECIAL_SOLAR_BEAM + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_BODY_PRESS, DFI_SPECIAL_HP_POWER + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_FOUL_PLAY, DFI_SPECIAL_BODY_PRESS + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_PSYSHOCK, DFI_SPECIAL_FOUL_PLAY + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_RAIN_DANCE, DFI_SPECIAL_PSYSHOCK + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SUNNY_DAY, DFI_SPECIAL_RAIN_DANCE + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_FREEZE_DRY, DFI_SPECIAL_SUNNY_DAY + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_CLANGING_SCALES, DFI_SPECIAL_FREEZE_DRY + 1u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_STEEL_ROLLER, DFI_SPECIAL_CLANGING_SCALES + 1u); /* step G34 follows */
        /* Step G33: the two handlers of the multi-hit moves, after the three of step G34 and before UNMODELED. */
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TRIPLE_AXEL, DFI_SPECIAL_MULTI_HIT_2 + 1u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_DUALWINGBEAT].special, DFI_SPECIAL_MULTI_HIT_2);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TWINBEAM].special, DFI_SPECIAL_MULTI_HIT_2);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_TRIPLEAXEL].special, DFI_SPECIAL_TRIPLE_AXEL);
        /* Population Bomb (step G48): ten hits, its own handler (its learners Maushold and Maushold-Four have Friend Guard). */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].special, DFI_SPECIAL_MULTI_HIT_10);
        DF_CHECK(&t, dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][0] == 10u && dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][1] == 10u);
        /* the hit counts of the four rows are the engine's (dfi_move_hits) and the static column's too */
        DF_CHECK(&t, dfi_pool_move_static_hits[DFI_MOVE_DUALWINGBEAT][0] == 2u && dfi_pool_move_static_hits[DFI_MOVE_DUALWINGBEAT][1] == 2u);
        DF_CHECK(&t, dfi_pool_move_static_hits[DFI_MOVE_TWINBEAM][0] == 2u && dfi_pool_move_static_hits[DFI_MOVE_TWINBEAM][1] == 2u);
        DF_CHECK(&t, dfi_pool_move_static_hits[DFI_MOVE_TRIPLEAXEL][0] == 3u && dfi_pool_move_static_hits[DFI_MOVE_TRIPLEAXEL][1] == 3u);
        DF_CHECK(&t, dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][0] == 10u && dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][1] == 10u); /* data only */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ERUPTION].special, DFI_SPECIAL_HP_POWER);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_WATERSPOUT].special, DFI_SPECIAL_HP_POWER);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_BODYPRESS].special, DFI_SPECIAL_BODY_PRESS);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FOULPLAY].special, DFI_SPECIAL_FOUL_PLAY);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_PSYSHOCK].special, DFI_SPECIAL_PSYSHOCK);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_RAINDANCE].special, DFI_SPECIAL_RAIN_DANCE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SUNNYDAY].special, DFI_SPECIAL_SUNNY_DAY);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FREEZEDRY].special, DFI_SPECIAL_FREEZE_DRY);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_CLANGINGSCALES].special, DFI_SPECIAL_CLANGING_SCALES);
        /* Life Dew (target allies) and Volt Switch (a pivot) are data: no handler. The Champions Freeze-Dry has no secondary. */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_LIFEDEW].special, DFI_SPECIAL_NONE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_LIFEDEW].target_class, DFI_TARGET_CLASS_ALLIES);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_VOLTSWITCH].special, DFI_SPECIAL_NONE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FREEZEDRY].sec_kind, 0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SHELLSMASH].special, DFI_SPECIAL_SHELL_SMASH);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ACROBATICS].special, DFI_SPECIAL_ACROBATICS);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_BLIZZARD].special, DFI_SPECIAL_BLIZZARD);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FEINT].special, DFI_SPECIAL_FEINT);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_FEINT].priority, DFI_PRIORITY_BIAS + 2u);
        /* Ancient Power: a secondary that boosts its user (the new kind), data otherwise. */
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ANCIENTPOWER].special, DFI_SPECIAL_NONE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ANCIENTPOWER].sec_kind, DFI_SECONDARY_SELF_BOOST);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ANCIENTPOWER].sec_chance, 10u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ANCIENTPOWER].boost_role, DFI_BOOST_ROLE_SECONDARY_SELF);
        for (uint32_t k = 0u; k < 5u; ++k) {
            DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ANCIENTPOWER].boosts[k], k == 0u || k == 1u || k == 2u || k == 3u || k == 4u ? 7u : 6u);
        }
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_AURORAVEIL].special, DFI_SPECIAL_AURORA_VEIL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_EXPANDINGFORCE].special, DFI_SPECIAL_EXPANDING_FORCE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_EXPANDINGFORCE].base_power, 80u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_EXPANDINGFORCE].target_class, DUOFORGE_TARGET_CLASS_NORMAL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_EXPANDINGFORCE].category, DFI_CATEGORY_SPECIAL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_EXPANDINGFORCE].type, DFI_TYPE_PSYCHIC);
        DF_CHECK(&t, dfi_pool_move_unmodeled[DFI_MOVE_EXPANDINGFORCE] == NULL);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_KNOCK_OFF, 24u);
        DF_CHECK_EQ_U64(&t, DFI_SPECIAL_AURORA_VEIL, 27u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_AURORAVEIL].special, DFI_SPECIAL_AURORA_VEIL);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_KNOCKOFF].special, DFI_SPECIAL_KNOCK_OFF);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SANDSTORM].special, DFI_SPECIAL_SANDSTORM);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SNOWSCAPE].special, DFI_SPECIAL_SNOWSCAPE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SCALD].special, DFI_SPECIAL_NONE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_RECOVER].special, DFI_SPECIAL_NONE);
        /* Step G8: Throat Chop and Psychic Noise are modelled (a secondary kind of their own, chance 100), not
         * handlers; the second flags byte holds the pinned sound and heal flags and nothing else. Every named move
         * has its bits; the counts over the whole pool are those of the pinned data (the generator's test reads
         * them from the pinned text). */
        static const struct {
            uint32_t move;
            uint32_t flags2;
        } flagged[] = {{DFI_MOVE_SNARL, DFI_MOVE_FLAG2_SOUND}, {DFI_MOVE_PARTINGSHOT, DFI_MOVE_FLAG2_SOUND},
                       {DFI_MOVE_HYPERVOICE, DFI_MOVE_FLAG2_SOUND}, {DFI_MOVE_PSYCHICNOISE, DFI_MOVE_FLAG2_SOUND},
                       {DFI_MOVE_BITTERBLADE, DFI_MOVE_FLAG2_HEAL | DFI_MOVE_FLAG2_SLICING},
                       {DFI_MOVE_ICEPUNCH, DFI_MOVE_FLAG2_PUNCH}, {DFI_MOVE_SLASH, DFI_MOVE_FLAG2_SLICING}, {DFI_MOVE_LEECHLIFE, DFI_MOVE_FLAG2_HEAL},
                       {DFI_MOVE_RECOVER, DFI_MOVE_FLAG2_HEAL}, {DFI_MOVE_THROATCHOP, 0u}, {DFI_MOVE_PROTECT, 0u},
                       {DFI_MOVE_SCALD, DFI_MOVE_FLAG2_THAWS_TARGET},
                       {DFI_MOVE_MATCHAGOTCHA, DFI_MOVE_FLAG2_HEAL | DFI_MOVE_FLAG2_THAWS_TARGET},
                       {DFI_MOVE_SCORCHINGSANDS, DFI_MOVE_FLAG2_THAWS_TARGET}};
        for (size_t k = 0u; k < sizeof flagged / sizeof flagged[0]; ++k) {
            DF_CHECK_EQ_U64(&t, dfi_pool_move_flags2[flagged[k].move], flagged[k].flags2);
        }
        uint32_t sound = 0u;
        uint32_t heal = 0u;
        uint32_t other = 0u;
        uint32_t thaw = 0u;
        uint32_t recharge = 0u;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            recharge += (dfi_pool_move_flags2[i] & DFI_MOVE_FLAG2_RECHARGE) != 0u ? 1u : 0u;
            thaw += (dfi_pool_move_flags2[i] & DFI_MOVE_FLAG2_THAWS_TARGET) != 0u ? 1u : 0u;
            sound += (dfi_pool_move_flags2[i] & DFI_MOVE_FLAG2_SOUND) != 0u ? 1u : 0u;
            heal += (dfi_pool_move_flags2[i] & DFI_MOVE_FLAG2_HEAL) != 0u ? 1u : 0u;
            other += (dfi_pool_move_flags2[i] &
                      ~(uint32_t)(DFI_MOVE_FLAG2_SOUND | DFI_MOVE_FLAG2_HEAL | DFI_MOVE_FLAG2_THAWS_TARGET | DFI_MOVE_FLAG2_RECHARGE |
                                    DFI_MOVE_FLAG2_POWDER | DFI_MOVE_FLAG2_PUNCH | DFI_MOVE_FLAG2_SLICING |
                                    DFI_MOVE_FLAG2_FORCE_SWITCH)) != 0u
                         ? 1u
                         : 0u;
        }
        DF_CHECK_EQ_U64(&t, other, 0u);
        /* No move has both the sound and the heal flag: the BeforeMove tie of a Pokemon with Throat Chop and Heal Block
         * shows in no move (trace_to_c.py drops it; the generator fails for such a move). */
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            DF_CHECK(&t, (dfi_pool_move_flags2[i] & (DFI_MOVE_FLAG2_SOUND | DFI_MOVE_FLAG2_HEAL)) !=
                             (DFI_MOVE_FLAG2_SOUND | DFI_MOVE_FLAG2_HEAL));
        }
        DF_CHECK_EQ_U64(&t, sound, SOUND_MOVES);
        DF_CHECK_EQ_U64(&t, heal, HEAL_MOVES);
        DF_CHECK_EQ_U64(&t, thaw, THAW_MOVES);
        DF_CHECK_EQ_U64(&t, recharge, RECHARGE_MOVES);
        /* The heal column (step G10): Recover and Slack Off heal 1/2, and (modelled since step G32) Life Dew 1/4; no other move
         * heals by a fraction. */
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            const bool halves = i == DFI_MOVE_RECOVER || i == DFI_MOVE_SLACKOFF || i == DFI_MOVE_ROOST; /* Roost: step G42 */
            const bool quarter = i == DFI_MOVE_LIFEDEW;
            DF_CHECK_EQ_U64(&t, dfi_pool_move_heal[i][0], (halves || quarter) ? 1u : 0u);
            DF_CHECK_EQ_U64(&t, dfi_pool_move_heal[i][1], halves ? 2u : quarter ? 4u : 0u);
            DF_CHECK(&t, dfi_pool_move_heal[i][1] == 0u || (dfi_pool_move_flags2[i] & DFI_MOVE_FLAG2_HEAL) != 0u);
        }
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_THROATCHOP].special, DFI_SPECIAL_NONE);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_PSYCHICNOISE].special, DFI_SPECIAL_NONE);
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
        const uint32_t ext_bits = closure_bits | DFI_IMMUNE_PSN; /* every bit but the pool's DFI_IMMUNE_SAND */
        DF_CHECK_EQ_U64(&t, dfi_closure_canonical_bytes(closure, sizeof closure), DFI_CLOSURE_CANONICAL_SIZE);
        size_t n = dfi_pool_canonical_bytes_of(from_pool, sizeof from_pool, DFI_FORME_COUNT, DFI_MOVE_COUNT,
                                               DFI_ITEM_COUNT, DFI_ABILITY_COUNT, closure_bits);
        DF_CHECK_EQ_U64(&t, n, DFI_CLOSURE_CANONICAL_SIZE);
        DF_CHECK_BYTES(&t, from_pool, closure, DFI_CLOSURE_CANONICAL_SIZE, "closure canonical bytes from the pool prefix");
        DF_CHECK(&t, dfi_sha256(from_pool, n, sha));
        DF_CHECK_BYTES(&t, sha, dfi_closure_table_hash, sizeof sha, "sha256(closure prefix) = closure table hash");

        DF_CHECK_EQ_U64(&t, dfi_ext_canonical_bytes(ext, sizeof ext), DFI_EXT_CANONICAL_SIZE);
        n = dfi_pool_canonical_bytes_of(from_pool, sizeof from_pool, DFI_EXT_FORME_COUNT, DFI_EXT_MOVE_COUNT,
                                        DFI_EXT_ITEM_COUNT, DFI_EXT_ABILITY_COUNT, ext_bits);
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
                                                     DFI_IMMUNE_BRN | DFI_IMMUNE_FRZ | DFI_IMMUNE_PAR |
                                                         DFI_IMMUNE_PRANKSTER | DFI_IMMUNE_PSN);
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
         * 346 * (64 + 1 + 3), then the second flags byte of 511 moves (step G8) */
        DF_CHECK_EQ_U64(&t, DFI_POOL_CANONICAL_SIZE, 12u + POOL_FORMES * 26u + POOL_MOVES * 29u + POOL_ITEMS * 4u + 324u +
                                                         18u + 50u + POOL_ITEMS * 2u + POOL_ABILITIES * 2u +
                                                         POOL_ITEMS + POOL_ABILITIES +
                                                         POOL_FORMES * (DFI_POOL_LEARN_BYTES + 1u + 3u) + POOL_MOVES +
                                                         POOL_MOVES * 2u + POOL_MOVES * 4u + POOL_MOVES * 2u + POOL_MOVES);
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
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            bad += bytes[at + i] != dfi_pool_move_flags2[i] ? 1u : 0u;
        }
        at += DFI_POOL_MOVE_COUNT;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) { /* the heal fractions (step G10), the last part */
            bad += bytes[at + 2u * i] != dfi_pool_move_heal[i][0] || bytes[at + 2u * i + 1u] != dfi_pool_move_heal[i][1]
                       ? 1u
                       : 0u;
        }
        at += 2u * DFI_POOL_MOVE_COUNT;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) { /* the static flags (decision 0020), 4 bytes little-endian */
            const uint32_t v = (uint32_t)bytes[at + 4u * i] | ((uint32_t)bytes[at + 4u * i + 1u] << 8) |
                               ((uint32_t)bytes[at + 4u * i + 2u] << 16) | ((uint32_t)bytes[at + 4u * i + 3u] << 24);
            bad += v != dfi_pool_move_static_flags[i] ? 1u : 0u;
        }
        at += 4u * DFI_POOL_MOVE_COUNT;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) { /* the hit counts (decision 0020), the last part */
            bad += bytes[at + 2u * i] != dfi_pool_move_static_hits[i][0] ||
                           bytes[at + 2u * i + 1u] != dfi_pool_move_static_hits[i][1]
                       ? 1u
                       : 0u;
        }
        at += 2u * DFI_POOL_MOVE_COUNT;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) { /* the third flags byte (steps G57, G53), the very last part */
            bad += bytes[at + i] != dfi_pool_move_flags3[i] ? 1u : 0u;
        }
        at += DFI_POOL_MOVE_COUNT;
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
        for (size_t i = 0u; i < sizeof weather_abilities / sizeof weather_abilities[0]; ++i) {
            check_ability(&t, &weather_abilities[i]);
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
            if (!listed(prefix_abilities, n_prefix_abilities, id) && !listed(new_abilities, n_new_abilities, id) &&
                !listed(weather_abilities, sizeof weather_abilities / sizeof weather_abilities[0], id)) {
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
        /* Step G4 marks Focus Sash (onDamage at the move-damage call), step G12 Floettite (the Mega Stone of
         * Floette-Eternal, with Fairy Aura), step G18 four more Mega Stones (Tyranitarite, Baxcalibrite,
         * Aerodactylite, Manectite: the Mega ability is marked and the base forme has exactly one Mega), the Mega batch nine
         * more (Gardevoirite, Abomasite, Barbaracite, Beedrillite, Falinksite, Hawluchanite, Malamarite, Sceptilite,
         * Scraftinite), step G23-C Charizardite X, Garchompite Z and Delphoxite; Expert Belt stays unmarked. */
        DF_CHECK(&t, dfi_support.items[DFI_ITEM_FOCUSSASH] != 0u);
        for (uint32_t id = DFI_ITEM_FOCUSSASH + 1u; id < DFI_POOL_ITEM_COUNT; ++id) {
            const bool stone = id == DFI_ITEM_FLOETTITE || id == DFI_ITEM_PSYCHICSEED || id == DFI_ITEM_ELECTRICSEED ||
                               id == DFI_ITEM_MISTYSEED || id == DFI_ITEM_EXPERTBELT || id == DFI_ITEM_EJECTBUTTON || id == DFI_ITEM_TYRANITARITE ||
                               id == DFI_ITEM_BAXCALIBRITE || id == DFI_ITEM_AERODACTYLITE || id == DFI_ITEM_MANECTITE ||
                               id == DFI_ITEM_GARDEVOIRITE || id == DFI_ITEM_ABOMASITE || id == DFI_ITEM_BARBARACITE ||
                               id == DFI_ITEM_BEEDRILLITE || id == DFI_ITEM_FALINKSITE || id == DFI_ITEM_HAWLUCHANITE ||
                               id == DFI_ITEM_MALAMARITE || id == DFI_ITEM_SCEPTILITE || id == DFI_ITEM_SCRAFTINITE ||
                               id == DFI_ITEM_CHARIZARDITEX || id == DFI_ITEM_GARCHOMPITEZ || id == DFI_ITEM_DELPHOXITE ||
                               id == DFI_ITEM_SWAMPERTITE || id == DFI_ITEM_METAGROSSITE || id == DFI_ITEM_LUCARIONITEZ || id == DFI_ITEM_FROSLASSITE /* Mega batch 2 */ ||
                               id == DFI_ITEM_WIDELENS /* step G34: the accuracy modifier, by id */ ||
                               id == DFI_ITEM_GENGARITE /* step G41: the Mega Stone of Gengar */ ||
                               /* step G51 (Mega batch 4, mark only): ten more Mega Stones */
                               id == DFI_ITEM_CHANDELURITE || id == DFI_ITEM_HOUNDOOMINITE || id == DFI_ITEM_LUCARIONITE ||
                               id == DFI_ITEM_DRAGALGITE || id == DFI_ITEM_CRABOMINITE || id == DFI_ITEM_CHIMECHITE ||
                               id == DFI_ITEM_GLALITITE || id == DFI_ITEM_PINSIRITE || id == DFI_ITEM_BANETTITE ||
                               id == DFI_ITEM_PIDGEOTITE ||
                               /* step G47: Lum Berry and Mental Herb, by id (a status, a confusion, the four volatiles) */
                               id == DFI_ITEM_LUMBERRY || id == DFI_ITEM_MENTALHERB ||
                               /* step G43 (Mega batch 3): ten more Mega Stones, mark only */
                               id == DFI_ITEM_DRAGONINITE || id == DFI_ITEM_GLIMMORANITE || id == DFI_ITEM_BLAZIKENITE ||
                               id == DFI_ITEM_ABSOLITE || id == DFI_ITEM_SABLENITE /* step G57: Absolite and Sablenite */ ||
                               id == DFI_ITEM_ABSOLITEZ || id == DFI_ITEM_RAICHUNITEX || id == DFI_ITEM_LOPUNNITE ||
                               id == DFI_ITEM_ALAKAZITE || id == DFI_ITEM_MEOWSTICITE || id == DFI_ITEM_SCIZORITE ||
                               id == DFI_ITEM_GALLADITE ||
                               /* step G59: six Mega Stones, mark only */
                               id == DFI_ITEM_BLASTOISINITE || id == DFI_ITEM_MAWILITE || id == DFI_ITEM_VENUSAURITE ||
                               id == DFI_ITEM_PYROARITE || id == DFI_ITEM_SCOVILLAINITE || id == DFI_ITEM_MEGANIUMITE ||
                               id == DFI_ITEM_REDCARD || id == DFI_ITEM_MUSCLEBAND || id == DFI_ITEM_WISEGLASSES || id == DFI_ITEM_BRIGHTPOWDER /* step G46: Red Card (no Sheer Force gate); step G49: the three item rows */ ||
                               /* step G55: the four rocks and Terrain Extender (the duration rows, read by the setter's item) */
                               id == DFI_ITEM_DAMPROCK || id == DFI_ITEM_HEATROCK || id == DFI_ITEM_SMOOTHROCK ||
                               id == DFI_ITEM_ICYROCK || id == DFI_ITEM_TERRAINEXTENDER;
            DF_CHECK_EQ_U64(&t, dfi_support.items[id] != 0u ? 1u : 0u, stone ? 1u : 0u);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            if (dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.items[id] != 0u);
            }
        }
        /* The P1 abilities (Pixilate to Swarm, ids below Rock Head) are marked by step P3 and have a family; the
         * G2 abilities after them have none, and all three are marked: Rock Head (step G4: no recoil from a recoil
         * move), Flower Veil and Fairy Aura (step G12). */
        for (uint32_t id = DFI_EXT_ABILITY_COUNT; id < DFI_ABILITY_ROCKHEAD; ++id) {
            DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            DF_CHECK(&t, dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = DFI_ABILITY_ROCKHEAD; id <= DFI_ABILITY_FAIRYAURA; ++id) {
            DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            DF_CHECK_EQ_U64(&t, dfi_pool_ability_family[id].family, DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = DFI_ABILITY_FAIRYAURA + 1u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            /* Of the whole-pool abilities after Fairy Aura only Sand Stream and Snow Warning have a family (the weather
             * setters of the Sandstorm and Snowscape step) and are marked; Rough Skin, Poison Touch and Thermal
             * Exchange (step G14) are marked without a family: the turn code runs them by id. */
            const bool setter = id == DFI_ABILITY_SANDSTREAM || id == DFI_ABILITY_SNOWWARNING;
            const bool terrain_setter = id == DFI_ABILITY_ELECTRICSURGE; /* step G25 */
            /* ... and Rough Skin, Poison Touch, Thermal Exchange (step G14) and Sticky Hold (step G16): engine rows that the turn code runs by id. */
            const bool engine = id == DFI_ABILITY_ROUGHSKIN || id == DFI_ABILITY_POISONTOUCH ||
                                id == DFI_ABILITY_THERMALEXCHANGE || id == DFI_ABILITY_STICKYHOLD ||
                                id == DFI_ABILITY_TRACE /* step AC1: Trace, by id too */ ||
                                id == DFI_ABILITY_LEVITATE /* step G23-C: isGrounded and the Ground immunity */ ||
                                /* step G22: the weather Speed abilities, Inner Focus and Liquid Voice, by id */
                                id == DFI_ABILITY_SANDRUSH || id == DFI_ABILITY_SWIFTSWIM ||
                                id == DFI_ABILITY_SLUSHRUSH || id == DFI_ABILITY_CHLOROPHYLL ||
                                id == DFI_ABILITY_INNERFOCUS || id == DFI_ABILITY_LIQUIDVOICE ||
                                /* step G30: Flame Body, Clear Body, Hospitality and Overcoat, by id */
                                id == DFI_ABILITY_FLAMEBODY || id == DFI_ABILITY_CLEARBODY ||
                                id == DFI_ABILITY_HOSPITALITY || id == DFI_ABILITY_OVERCOAT ||
                                /* step G32: Soundproof, Unnerve and Speed Boost, by id */
                                id == DFI_ABILITY_SOUNDPROOF || id == DFI_ABILITY_UNNERVE || id == DFI_ABILITY_SPEEDBOOST ||
                                /* step G34: Compound Eyes, Iron Fist, Sharpness, Solid Rock, Technician, Multiscale and
                                 * Gale Wings, by id */
                                id == DFI_ABILITY_COMPOUNDEYES || id == DFI_ABILITY_IRONFIST ||
                                id == DFI_ABILITY_SHARPNESS || id == DFI_ABILITY_SOLIDROCK ||
                                id == DFI_ABILITY_TECHNICIAN || id == DFI_ABILITY_MULTISCALE ||
                                id == DFI_ABILITY_GALEWINGS ||
                             /* step G39: Hyper Cutter, Scrappy, Infiltrator, Queenly Majesty, Damp, Sturdy, Snow Cloak, Sand Veil,
                              * Static, Justified, Limber, Solar Power and Regenerator, by id */
                             id == DFI_ABILITY_HYPERCUTTER || id == DFI_ABILITY_SCRAPPY || id == DFI_ABILITY_INFILTRATOR ||
                             id == DFI_ABILITY_QUEENLYMAJESTY || id == DFI_ABILITY_DAMP || id == DFI_ABILITY_STURDY ||
                             id == DFI_ABILITY_SNOWCLOAK || id == DFI_ABILITY_SANDVEIL || id == DFI_ABILITY_STATIC ||
                             id == DFI_ABILITY_JUSTIFIED || id == DFI_ABILITY_LIMBER || id == DFI_ABILITY_SOLARPOWER ||
                             id == DFI_ABILITY_REGENERATOR ||
                                /* step G35: Rain Dish and Friend Guard, by id */
                                id == DFI_ABILITY_RAINDISH || id == DFI_ABILITY_FRIENDGUARD ||
                                id == DFI_ABILITY_CURSEDBODY /* step G27: Cursed Body, by id too */ ||
                                /* step G33: Mirror Armor, by id */
                                id == DFI_ABILITY_MIRRORARMOR ||
                                /* Mega batch 2: Aura Guard, by id */
                                id == DFI_ABILITY_AURAGUARD ||
                                id == DFI_ABILITY_TOXICDEBRIS /* step G37: Toxic Debris, by id (a Physical hit adds Toxic Spikes) */ ||
                                /* step G41: Shadow Tag, by id (the request builder asks dfi_switch_trapped) */
                                id == DFI_ABILITY_SHADOWTAG ||
                                /* step G46: Suction Cups and Guard Dog, the DragOut blockers, by id */
                                id == DFI_ABILITY_SUCTIONCUPS || id == DFI_ABILITY_GUARDDOG ||
                                /* step G45: Steadfast, Moxie, Weak Armor, Telepathy, Volt Absorb and Punk Rock, by id */
                                id == DFI_ABILITY_STEADFAST || id == DFI_ABILITY_MOXIE || id == DFI_ABILITY_WEAKARMOR ||
                                id == DFI_ABILITY_TELEPATHY || id == DFI_ABILITY_VOLTABSORB || id == DFI_ABILITY_PUNKROCK ||
                                /* step G47: Synchronize and Oblivious, by id (dfi_synchronize, Taunt's and Intimidate's guard) */
                                id == DFI_ABILITY_SYNCHRONIZE || id == DFI_ABILITY_OBLIVIOUS ||
                                /* step G59: the six Mega abilities, by id (Mega Launcher, Huge Power, Thick Fat, Fire Mane,
                                 * Spicy Spray, Mega Sol) */
                                id == DFI_ABILITY_MEGALAUNCHER || id == DFI_ABILITY_HUGEPOWER || id == DFI_ABILITY_THICKFAT ||
                                id == DFI_ABILITY_FIREMANE || id == DFI_ABILITY_SPICYSPRAY || id == DFI_ABILITY_MEGASOL ||
                                /* step G51: Keen Eye and Big Pecks, by id (dfi_boost and dfi_accuracy_check) */
                                id == DFI_ABILITY_KEENEYE || id == DFI_ABILITY_BIGPECKS ||
                                /* step G57: Magic Bounce, by id (the bounced path of the move body) */
                                id == DFI_ABILITY_MAGICBOUNCE ||
                                /* step G53: Pressure, by id (dfi_pressure_extra, the switch-in line) */
                                id == DFI_ABILITY_PRESSURE;
            DF_CHECK_EQ_U64(&t, dfi_support.abilities[id] != 0u ? 1u : 0u, (setter || terrain_setter || engine) ? 1u : 0u);
            DF_CHECK_EQ_U64(&t, dfi_pool_ability_family[id].family,
                            setter ? DFI_ABILITY_FAMILY_WEATHER_SETTER
                            : terrain_setter ? DFI_ABILITY_FAMILY_TERRAIN_SETTER : DFI_ABILITY_FAMILY_NONE);
        }
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            if (dfi_pool_ability_family[id].family != DFI_ABILITY_FAMILY_NONE) {
                DF_CHECK(&t, dfi_support.abilities[id] != 0u);
            }
        }
        /* Steps G2, G5, G7, G8, G9, G10, G11 and G12 mark twenty-six moves in all (G9: Encore, whose handler id the turn
         * code implements: g09_encore_*; G10: First Impression, Scald, Recover, Low Kick: g10_*), and step G13 fourteen
         * more of the whole pool (Flamethrower, Draining Kiss, Rock Tomb, Hydro Pump, Superpower, Light of Ruin, Earth
         * Power, Power Gem, Aura Sphere, Icy Wind, Ice Shard, Quick Attack, Detect and Poison Jab: g13_*), each used in a
         * reference battle under the POOL kind (g2_data_moves_a to _d; U-turn: g5_uturn_a to _e; Throat Chop and Psychic
         * Noise, whose lockout and Heal Block are secondary kinds, not handlers: g8_throat_chop, g8_heal_block,
         * g8_heal_block_pair and _tie_a/_b; Wide Guard, whose handler id the turn code runs: g7_wide_guard_*; Soak, whose
         * handler id the turn code implements since step G11: g11_soak, _mega, _stab and _electro; Moonblast and Calm
         * Mind: g12_floette_moves); step G19 Coaching and Glaive Rush (g19_*); step G21 twenty-seven moves of the whole pool on columns that exist (Sludge Bomb, Gunk
         * Shot, Dragon Claw, Dragon Dance, Quiver Dance, Agility, Mystical Fire, Struggle Bug, Dark Pulse, Air
         * Slash, Icicle Crash, Waterfall, Overheat, Leaf Storm, Armor Cannon, Will-O-Wisp, Night Slash, Slash, Fire Blast,
         * Power Whip, Accelerock, Bullet Punch, Mach Punch, Crunch, Bug Buzz, Drain Punch and Nuzzle: g21_*); step G17 six of the seven recharge moves (g17_*; Meteor Assault stays unmarked: its only learner, Sirfetch'd, has no supported ability). No move with a handler id is left
         * unmarked. */
        static const uint32_t marked_moves[] = {DFI_MOVE_ROCKSLIDE, DFI_MOVE_DOUBLEEDGE, DFI_MOVE_THUNDERBOLT,
                                                DFI_MOVE_FLASHCANNON, DFI_MOVE_EXTREMESPEED, DFI_MOVE_HEADSMASH,
                                                DFI_MOVE_BULKUP, DFI_MOVE_LIQUIDATION, DFI_MOVE_ICEPUNCH,
                                                DFI_MOVE_SHADOWCLAW, DFI_MOVE_DRUMBEATING, DFI_MOVE_DAZZLINGGLEAM,
                                                DFI_MOVE_UTURN, DFI_MOVE_THROATCHOP, DFI_MOVE_PSYCHICNOISE,
                                                DFI_MOVE_WIDEGUARD, DFI_MOVE_SOAK, DFI_MOVE_ENCORE, DFI_MOVE_MOONBLAST,
                                                DFI_MOVE_CALMMIND, DFI_MOVE_FIRSTIMPRESSION, DFI_MOVE_SCALD,
                                                DFI_MOVE_RECOVER, DFI_MOVE_LOWKICK, DFI_MOVE_SANDSTORM,
                                                DFI_MOVE_SNOWSCAPE,
                                                DFI_MOVE_FLAMETHROWER, DFI_MOVE_DRAININGKISS, DFI_MOVE_ROCKTOMB,
                                                DFI_MOVE_HYDROPUMP, DFI_MOVE_SUPERPOWER, DFI_MOVE_LIGHTOFRUIN,
                                                DFI_MOVE_EARTHPOWER, DFI_MOVE_POWERGEM, DFI_MOVE_AURASPHERE,
                                                DFI_MOVE_ICYWIND, DFI_MOVE_ICESHARD, DFI_MOVE_QUICKATTACK,
                                                DFI_MOVE_DETECT, DFI_MOVE_POISONJAB,
                                                DFI_MOVE_BLASTBURN, DFI_MOVE_FRENZYPLANT, DFI_MOVE_GIGAIMPACT,
                                                DFI_MOVE_HYDROCANNON, DFI_MOVE_HYPERBEAM, DFI_MOVE_ROCKWRECKER, DFI_MOVE_KNOCKOFF,
                                                DFI_MOVE_SLUDGEBOMB, DFI_MOVE_GUNKSHOT, DFI_MOVE_DRAGONCLAW, DFI_MOVE_DRAGONDANCE,
                                                DFI_MOVE_QUIVERDANCE, DFI_MOVE_AGILITY, DFI_MOVE_MYSTICALFIRE,
                                                DFI_MOVE_STRUGGLEBUG, DFI_MOVE_DARKPULSE, DFI_MOVE_AIRSLASH, DFI_MOVE_ICICLECRASH,
                                                DFI_MOVE_WATERFALL, DFI_MOVE_OVERHEAT, DFI_MOVE_LEAFSTORM, DFI_MOVE_ARMORCANNON,
                                                DFI_MOVE_WILLOWISP, DFI_MOVE_NIGHTSLASH, DFI_MOVE_SLASH, DFI_MOVE_FIREBLAST,
                                                DFI_MOVE_POWERWHIP, DFI_MOVE_ACCELEROCK, DFI_MOVE_BULLETPUNCH, DFI_MOVE_MACHPUNCH,
                                                DFI_MOVE_CRUNCH, DFI_MOVE_BUGBUZZ, DFI_MOVE_DRAINPUNCH, DFI_MOVE_NUZZLE,
                                                DFI_MOVE_EXPANDINGFORCE,
                                                DFI_MOVE_COACHING, DFI_MOVE_GLAIVERUSH, DFI_MOVE_AURORAVEIL,
                                                DFI_MOVE_ELECTRICTERRAIN, DFI_MOVE_MISTYTERRAIN, DFI_MOVE_RISINGVOLTAGE,
                                                DFI_MOVE_TERRAINPULSE,
                                                DFI_MOVE_SHELLSMASH, DFI_MOVE_ACROBATICS, DFI_MOVE_BLIZZARD,
                                                DFI_MOVE_ANCIENTPOWER, DFI_MOVE_FEINT, DFI_MOVE_EARTHQUAKE,
                                                DFI_MOVE_SPIKYSHIELD,
                                                /* step G30 */
                                                DFI_MOVE_RAGEPOWDER, DFI_MOVE_SLEEPPOWDER, DFI_MOVE_STUNSPORE,
                                                DFI_MOVE_POISONPOWDER, DFI_MOVE_PSYCHICFANGS, DFI_MOVE_SOLARBEAM,
                                                DFI_MOVE_MATCHAGOTCHA, DFI_MOVE_GIGADRAIN, DFI_MOVE_ENERGYBALL,
                                                DFI_MOVE_PLAYROUGH,
                                                /* step G32 */
                                                DFI_MOVE_ERUPTION, DFI_MOVE_WATERSPOUT, DFI_MOVE_LIFEDEW, DFI_MOVE_BODYPRESS,
                                                DFI_MOVE_FOULPLAY, DFI_MOVE_PSYSHOCK, DFI_MOVE_RAINDANCE, DFI_MOVE_SUNNYDAY,
                                                DFI_MOVE_VOLTSWITCH, DFI_MOVE_CLANGINGSCALES, DFI_MOVE_FREEZEDRY,
                                                /* step G34 */
                                                DFI_MOVE_STEELROLLER, DFI_MOVE_CLANGOROUSSOUL, DFI_MOVE_BRICKBREAK,
                                                DFI_MOVE_FIERYDANCE, DFI_MOVE_PSYCHOCUT, DFI_MOVE_IRONDEFENSE,
                                                DFI_MOVE_ELECTROWEB,
                                                /* step G36 */
                                                DFI_MOVE_TOXIC, DFI_MOVE_POISONFANG,
                                                /* step G35 (Gigaton Hammer is deferred) */
                                                DFI_MOVE_THUNDERPUNCH, DFI_MOVE_XSCISSOR, DFI_MOVE_LUMINACRASH,
                                                DFI_MOVE_OVERDRIVE, DFI_MOVE_SCORCHINGSANDS, DFI_MOVE_LEAFBLADE,
                                                DFI_MOVE_BOOMBURST, DFI_MOVE_SLUDGEWAVE, DFI_MOVE_VOLTTACKLE,
                                                DFI_MOVE_DISCHARGE,
                                                /* step G27 */
                                                DFI_MOVE_DISABLE,
                                                /* step G26 */
                                                DFI_MOVE_PERISHSONG,
                                                /* step G33 */
                                                DFI_MOVE_DUALWINGBEAT, DFI_MOVE_TRIPLEAXEL, DFI_MOVE_TWINBEAM,
                                                /* step G38 */
                                                DFI_MOVE_IMPRISON,
                                                /* step G29 */
                                                DFI_MOVE_TRICK, DFI_MOVE_SWITCHEROO, DFI_MOVE_THIEF, DFI_MOVE_COVET,
                                                /* step G39 */
                                                DFI_MOVE_CHARM, DFI_MOVE_FAKETEARS, DFI_MOVE_SACREDSWORD, DFI_MOVE_SUPERFANG,
                                                /* step G31 */
                                                DFI_MOVE_TAUNT, DFI_MOVE_YAWN,
                                                /* step G37: the four hazards */
                                                DFI_MOVE_STEALTHROCK, DFI_MOVE_SPIKES, DFI_MOVE_TOXICSPIKES, DFI_MOVE_STICKYWEB,
                                                /* step G44: four handlers (Thunder, Power Trip, Ice Fang, Tri Attack) and seven data rows */
                                                DFI_MOVE_THUNDER, DFI_MOVE_POWERTRIP, DFI_MOVE_ICEFANG, DFI_MOVE_TRIATTACK,
                                                DFI_MOVE_BREAKINGSWIPE, DFI_MOVE_VACUUMWAVE, DFI_MOVE_STONEEDGE, DFI_MOVE_AQUACUTTER,
                                                DFI_MOVE_HAMMERARM, DFI_MOVE_TROPKICK, DFI_MOVE_METEORMASH,
                                                /* step G46: the forced switch (the drag): Roar, Whirlwind, Dragon Tail, Circle Throw */
                                                DFI_MOVE_ROAR, DFI_MOVE_WHIRLWIND, DFI_MOVE_DRAGONTAIL, DFI_MOVE_CIRCLETHROW,
                                                /* step G48: Rage Fist, Stone Axe, Ceaseless Edge and Population Bomb */
                                                DFI_MOVE_RAGEFIST, DFI_MOVE_STONEAXE, DFI_MOVE_CEASELESSEDGE, DFI_MOVE_POPULATIONBOMB,
                                                /* step G50: Double Shock */
                                                DFI_MOVE_DOUBLESHOCK,
                                                /* step G42: Roost (a heal and a self volatile) and Stomping Tantrum (a base power callback) */
                                                DFI_MOVE_ROOST, DFI_MOVE_STOMPINGTANTRUM,
                                                /* step G54: Icicle Spear, Scale Shot, Quick Guard, Upper Hand, Heal Pulse, Strength Sap and Sing */
                                                DFI_MOVE_ICICLESPEAR, DFI_MOVE_SCALESHOT, DFI_MOVE_QUICKGUARD, DFI_MOVE_UPPERHAND,
                                                DFI_MOVE_HEALPULSE, DFI_MOVE_STRENGTHSAP, DFI_MOVE_SING, DFI_MOVE_HAZE,
                                                DFI_MOVE_AFTERYOU, DFI_MOVE_QUASH,
                                                /* step G56: Outrage (the lock); step G52: Revival Blessing */
                                                DFI_MOVE_OUTRAGE, DFI_MOVE_REVIVALBLESSING,
                                                /* step G64: Poltergeist, Beat Up, Bug Bite and Sheer Cold (decision 0015 item 5ca) */
                                                DFI_MOVE_POLTERGEIST, DFI_MOVE_BEATUP, DFI_MOVE_BUGBITE, DFI_MOVE_SHEERCOLD,
                                                /* step G62: Haze, After You, Quash (decision 0031, 0015 entry 5az) */
                                                DFI_MOVE_HAZE, DFI_MOVE_AFTERYOU, DFI_MOVE_QUASH};
        uint32_t marked_count = 0u;
        for (uint32_t id = DFI_EXT_MOVE_COUNT; id < DFI_POOL_MOVE_COUNT; ++id) {
            bool want = false;
            for (size_t k = 0u; k < sizeof marked_moves / sizeof marked_moves[0]; ++k) {
                want = want || marked_moves[k] == id;
            }
            DF_CHECK_EQ_U64(&t, dfi_support.moves[id] != 0u ? 1u : 0u, want ? 1u : 0u);
            /* A marked move has a handler id only if the engine has the code for it: First Impression (Fake Out's
             * family), Low Kick (Grass Knot's), Soak (step G11), Wide Guard (step G7), the two weather moves and Detect
             * (Protect's, step G13), Knock Off (step G16), Aurora Veil and Spiky Shield (step G20), Perish Song (step G26); the others are data. Never the UNMODELED one. */
            DF_CHECK(&t, !want || dfi_pool_moves[id].special == DFI_SPECIAL_NONE ||
                             id == DFI_MOVE_FIRSTIMPRESSION || id == DFI_MOVE_LOWKICK || id == DFI_MOVE_SOAK ||
                             id == DFI_MOVE_ENCORE || id == DFI_MOVE_SANDSTORM || id == DFI_MOVE_SNOWSCAPE ||
                             id == DFI_MOVE_KNOCKOFF || id == DFI_MOVE_EXPANDINGFORCE || id == DFI_MOVE_GLAIVERUSH || id == DFI_MOVE_AURORAVEIL || id == DFI_MOVE_SPIKYSHIELD || id == DFI_MOVE_DISABLE ||
                             id == DFI_MOVE_SHELLSMASH || id == DFI_MOVE_ACROBATICS || id == DFI_MOVE_BLIZZARD ||
                             id == DFI_MOVE_FEINT ||
                             id == DFI_MOVE_RAGEPOWDER || id == DFI_MOVE_PSYCHICFANGS || id == DFI_MOVE_SOLARBEAM ||
                             id == DFI_MOVE_STEELROLLER || id == DFI_MOVE_CLANGOROUSSOUL || id == DFI_MOVE_BRICKBREAK ||
                             id == DFI_MOVE_ERUPTION || id == DFI_MOVE_WATERSPOUT ||
                             id == DFI_MOVE_BODYPRESS || id == DFI_MOVE_FOULPLAY || id == DFI_MOVE_PSYSHOCK ||
                             id == DFI_MOVE_RAINDANCE || id == DFI_MOVE_SUNNYDAY || id == DFI_MOVE_FREEZEDRY ||
                             id == DFI_MOVE_CLANGINGSCALES || id == DFI_MOVE_IMPRISON || id == DFI_MOVE_TAUNT || id == DFI_MOVE_YAWN ||
                             id == DFI_MOVE_SUPERFANG ||
                             (id == DFI_MOVE_SACREDSWORD && dfi_pool_moves[id].special == DFI_SPECIAL_DARKEST_LARIAT) ||
                             id == DFI_MOVE_ELECTRICTERRAIN || id == DFI_MOVE_MISTYTERRAIN || id == DFI_MOVE_RISINGVOLTAGE ||
                             id == DFI_MOVE_TERRAINPULSE || id == DFI_MOVE_PERISHSONG ||
                             id == DFI_MOVE_THUNDER || id == DFI_MOVE_POWERTRIP || id == DFI_MOVE_ICEFANG || id == DFI_MOVE_TRIATTACK ||
                             id == DFI_MOVE_DUALWINGBEAT || id == DFI_MOVE_TRIPLEAXEL || id == DFI_MOVE_TWINBEAM ||
                             id == DFI_MOVE_TRICK || id == DFI_MOVE_SWITCHEROO || id == DFI_MOVE_THIEF || id == DFI_MOVE_COVET ||
                             id == DFI_MOVE_RAGEFIST || id == DFI_MOVE_STONEAXE || id == DFI_MOVE_CEASELESSEDGE ||
                             id == DFI_MOVE_POPULATIONBOMB || id == DFI_MOVE_DOUBLESHOCK ||
                             id == DFI_MOVE_ROOST || id == DFI_MOVE_STOMPINGTANTRUM ||
                             id == DFI_MOVE_ICICLESPEAR || id == DFI_MOVE_SCALESHOT || id == DFI_MOVE_QUICKGUARD ||
                             id == DFI_MOVE_UPPERHAND || id == DFI_MOVE_HEALPULSE || id == DFI_MOVE_STRENGTHSAP || id == DFI_MOVE_OUTRAGE || id == DFI_MOVE_REVIVALBLESSING || id == DFI_MOVE_POLTERGEIST || id == DFI_MOVE_BEATUP || id == DFI_MOVE_BUGBITE || id == DFI_MOVE_SHEERCOLD || id == DFI_MOVE_HAZE || id == DFI_MOVE_AFTERYOU || id == DFI_MOVE_QUASH ||
                             (id == DFI_MOVE_WIDEGUARD && dfi_pool_moves[id].special == DFI_SPECIAL_WIDE_GUARD) ||
                             (id == DFI_MOVE_DETECT && dfi_pool_moves[id].special == DFI_SPECIAL_PROTECT));
            DF_CHECK(&t, !want || dfi_pool_moves[id].special != DFI_SPECIAL_UNMODELED);
            marked_count += dfi_support.moves[id] != 0u ? 1u : 0u;
        }
        /* Step G46 guards: rows that stay UNMARKED until a battle uses them. Substitute: once it is marked, Dragon Tail and
         * Circle Throw must stop their drag at a Substitute (no target, forceSwitch skipped) and Roar must bypass it
         * (bypasssub). Mold Breaker: Suction Cups and Guard Dog are breakable (their DragOut is ignored under Mold Breaker),
         * so Mold Breaker is marked only with that rule. Sheer Force: Red Card has no Sheer Force gate under Champions
         * (scripts.ts:595-600), so once Sheer Force is marked a battle must show Red Card against a Sheer Force attacker. */
        DF_CHECK_EQ_U64(&t, dfi_support.moves[DFI_MOVE_SUBSTITUTE] != 0u ? 1u : 0u, 0u);
        DF_CHECK_EQ_U64(&t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER] != 0u ? 1u : 0u, 0u);
        DF_CHECK_EQ_U64(&t, dfi_support.abilities[DFI_ABILITY_SHEERFORCE] != 0u ? 1u : 0u, 0u);
        /* Step G46, the forceSwitchFlag gates of the pin (decision 0015 section 7): Shell Bell (items.ts:5658) and Pickpocket
         * (abilities.ts:3242) are skipped while the holder has a forceSwitchFlag. Both are unmodelled and stay UNMARKED; once
         * one is marked it must read the drag_pending bit of dfi_run for its holder (as Emergency Exit and the Eject Button
         * do). Wimp Out (abilities.ts:5495, champions :99) has no pool row; if one is added it must read the same bit. */
        DF_CHECK_EQ_U64(&t, dfi_support.items[DFI_ITEM_SHELLBELL] != 0u ? 1u : 0u, 0u);
        DF_CHECK_EQ_U64(&t, dfi_support.abilities[DFI_ABILITY_PICKPOCKET] != 0u ? 1u : 0u, 0u);
        /* The equivalence of the drag-in DragOut re-check (mutant M1, step G46): no marked row changes a blocker's ability
         * between the hit-time DragOut and the drag-in. Skill Swap (and any move that changes abilities mid-turn) would make
         * that re-check live: once it is marked, the drag-in DragOut must read the holder's ability at the drag-in. */
        DF_CHECK_EQ_U64(&t, dfi_support.moves[DFI_MOVE_SKILLSWAP] != 0u ? 1u : 0u, 0u);
        DF_CHECK_EQ_U64(&t, marked_count, 187u); /* step G64: Poltergeist, Beat Up, Bug Bite and Sheer Cold (decision 0015 item 5ca). Before: 180; seven more: step G54 (Icicle Spear, Scale Shot, Quick Guard, Upper Hand, Heal Pulse, Strength Sap, Sing) */ /* the eleven of step G44 (Thunder, Power Trip, Ice Fang, Tri Attack and seven data rows), the four of step G46 (Roar, Whirlwind, Dragon Tail, Circle Throw), the four of step G48, Taunt and Yawn (G31), the four hazards (G37), the four of step G39, the four of step G29, Imprison (G38), the three of step G33, Perish Song (G26), the four of step G25, Disable (G27), the ten of step G35, Toxic and Poison Fang (G36), the ten of step G30, the eleven of step G32 and the seven of step G34 */
    }

    /* Step AC1: Trace copies the ability of a foe unless that has the pin's notrace flag. The turn code excludes only
     * Trace itself (dfi_trace in src/combat/turn.c), which is right while no other ability with the flag is marked: the
     * nine abilities of the pinned data with the flag (tools/datagen/pool_families.js checks the list against the pin)
     * are all unmarked but Trace. Marking one of them needs its place in that rule. */
    {
        static const char *const notrace[] = {"disguise", "forecast", "hungerswitch", "illusion", "imposter", "receiver",
                                              "stancechange", "trace", "zerotohero"};
        uint32_t found = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            for (size_t k = 0u; k < sizeof notrace / sizeof notrace[0]; ++k) {
                if (strcmp(dfi_pool_ability_names[id], notrace[k]) == 0) {
                    found += 1u;
                    DF_CHECK_EQ_U64(&t, dfi_support.abilities[id] != 0u ? 1u : 0u, id == DFI_ABILITY_TRACE ? 1u : 0u);
                }
            }
        }
        DF_CHECK_EQ_U64(&t, found, 9u);
    }

    /* Step G12: Fairy Aura and Flower Veil. The engine reads them by id (no family column: one legal holder each);
     * what it does not implement must not be in the tables. Aura Break (3072/4096 instead of 5448/4096) and Dark Aura
     * are in no pool ability, and Mold Breaker (which ignores the breakable Flower Veil) is not either. */
    {
        static const char *const absent[] = {"aurabreak", "darkaura", "moldbreaker", "teravolt", "turboblaze",
                                             "neutralizinggas", "cleanbody", "whitesmoke"};
        for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
            for (size_t k = 0u; k < sizeof absent / sizeof absent[0]; ++k) {
                /* a row of the whole pool may have the name; nothing that makes a member play it is marked */
                DF_CHECK(&t, strcmp(dfi_pool_ability_names[id], absent[k]) != 0 || dfi_support.abilities[id] == 0u);
            }
        }
        DF_CHECK(&t, strcmp(dfi_pool_ability_names[DFI_ABILITY_FAIRYAURA], "fairyaura") == 0 &&
                         strcmp(dfi_pool_ability_names[DFI_ABILITY_FLOWERVEIL], "flowerveil") == 0);
        DF_CHECK(&t, dfi_pool_ability_family[DFI_ABILITY_FAIRYAURA].family == DFI_ABILITY_FAMILY_NONE &&
                         dfi_pool_ability_family[DFI_ABILITY_FLOWERVEIL].family == DFI_ABILITY_FAMILY_NONE);
        /* The BasePower chain of a Fairy move: Fairy Aura (5448, priority 20), the type booster (4915, 15) and Helping
         * Hand (6144, 10) chain in that order in the engine; the Pokemon of the pool give a Fairy move any of them, and
         * the six orders must give one base power for every damaging Fairy move of the tables (the rounding of a
         * chained modifier depends on the order, the base power it makes must not: a move that breaks that needs the
         * order tested by a battle). */
        static const uint32_t mods[3] = {5448u, 4915u, 6144u};
        static const uint8_t orders[6][3] = {{0, 1, 2}, {0, 2, 1}, {1, 0, 2}, {1, 2, 0}, {2, 0, 1}, {2, 1, 0}};
        uint32_t fairy_moves = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            const dfi_move_data *md = &dfi_pool_moves[id];
            if (md->type != DFI_TYPE_FAIRY || md->category == DFI_CATEGORY_STATUS || md->base_power == 0u ||
                dfi_support.moves[id] == 0u) {
                continue; /* a move that the engine plays; the step that marks another keeps this true */
            }
            fairy_moves += 1u;
            uint32_t first = 0u;
            for (size_t o = 0u; o < 6u; ++o) {
                uint32_t chain = 4096u;
                for (size_t k = 0u; k < 3u; ++k) {
                    DF_CHECK(&t, dfi_chain_modify(chain, mods[orders[o][k]], &chain));
                }
                const uint32_t power = dfi_modify(md->base_power, chain);
                if (o == 0u) {
                    first = power;
                }
                DF_CHECK_EQ_U64(&t, power, first);
            }
        }
        DF_CHECK(&t, fairy_moves >= 1u); /* Dazzling Gleam; the marked Fairy moves of later steps join it */
    }

    /* Step G16: Knock Off and Sticky Hold. Sticky Hold is read by id (no family column: it blocks the item taken by
     * Knock Off while its holder is alive) and is an engine row; the Mega Stones keep their onTakeItem as data of their
     * Mega link, which is the one thing the turn code asks of an item (dfi_item_takeable: not from its own species). */
    {
        DF_CHECK(&t, dfi_support.abilities[DFI_ABILITY_STICKYHOLD] != 0u && dfi_support.moves[DFI_MOVE_KNOCKOFF] != 0u);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_STICKYHOLD] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_family[DFI_ABILITY_STICKYHOLD].family == DFI_ABILITY_FAMILY_NONE);
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_KNOCKOFF].type == DFI_TYPE_DARK &&
                         dfi_pool_moves[DFI_MOVE_KNOCKOFF].category == DFI_CATEGORY_PHYSICAL &&
                         dfi_pool_moves[DFI_MOVE_KNOCKOFF].base_power == 65u &&
                         dfi_pool_moves[DFI_MOVE_KNOCKOFF].accuracy == 100u &&
                         (dfi_pool_moves[DFI_MOVE_KNOCKOFF].flags & DFI_MOVE_FLAG_CONTACT) != 0u &&
                         dfi_pool_moves[DFI_MOVE_KNOCKOFF].sec_chance == 0u);
        DF_CHECK(&t, dfi_pool_move_unmodeled[DFI_MOVE_KNOCKOFF] == NULL);
    }

    /* The whole-pool rows: what the tables model and what they do not (decision 0015 section 4.2). A move, item or
     * ability row that has any callback, field, target class or flag that the tables do not model carries the UNMODELED
     * handler (the move's special column, the handler column of an item or an ability) and a list of those features;
     * the three always agree. The closure, Team C and G2 rows are never UNMODELED: the closure and Team C rows are
     * code in the turn core, the G2 moves with a callback have a handler id of their own, and of the G2 items and
     * abilities the engine implements Focus Sash, Rock Head (G4), Floettite, Flower Veil and Fairy Aura (G12) by id
     * (ENGINE_ROWS of the generator). */
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
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_EXPERTBELT] == DFI_HANDLER_NONE); /* an engine row, step G28 */
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_SCOPELENS] == DFI_HANDLER_UNMODELED);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_FLOWERVEIL] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_FAIRYAURA] == DFI_HANDLER_NONE); /* engine rows, G12 */
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_ROUGHSKIN] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_POISONTOUCH] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_THERMALEXCHANGE] == DFI_HANDLER_NONE); /* engine rows, G14 */
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_SANDRUSH] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_SWIFTSWIM] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_SLUSHRUSH] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_CHLOROPHYLL] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_INNERFOCUS] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_handler[DFI_ABILITY_LIQUIDVOICE] == DFI_HANDLER_NONE); /* engine rows, G22 */
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_CURSEDBODY] == DFI_HANDLER_NONE); /* an engine row, G27 */
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_FLOETTITE] == DFI_HANDLER_NONE); /* a Mega Stone: data of its link */
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_PSYCHICSEED] == DFI_HANDLER_NONE &&
                         dfi_pool_item_handler[DFI_ITEM_ELECTRICSEED] == DFI_HANDLER_NONE &&
                         dfi_pool_item_handler[DFI_ITEM_MISTYSEED] == DFI_HANDLER_NONE); /* engine rows, G15 and G25 */
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_UTURN].special == DFI_SPECIAL_NONE);
        /* A few whole-pool rows, by what the pin says. Earthquake: allAdjacent, a class that the turn code lacks;
         * Hydro Pump: pure data; Substitute: a volatile with callbacks; Stealth Rock: a side condition and a class
         * that the closure lacks; Absolite Z: the second Mega Stone of Absol, data of its Mega link since the Mega of a
         * stone is found from (forme, stone); Damp Rock: no callback, read by id in
         * data/conditions.ts; Levitate: no callback, read by id elsewhere; Intimidate: code in the turn core. */
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_EARTHQUAKE].special == DFI_SPECIAL_NONE &&
                         dfi_pool_moves[DFI_MOVE_EARTHQUAKE].target_class == DFI_TARGET_CLASS_ALL_ADJACENT &&
                         dfi_pool_move_unmodeled[DFI_MOVE_EARTHQUAKE] == NULL); /* since step G28 the turn code has the class */
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_HYDROPUMP].special == DFI_SPECIAL_NONE &&
                         dfi_pool_move_unmodeled[DFI_MOVE_HYDROPUMP] == NULL && dfi_pool_moves[DFI_MOVE_HYDROPUMP].base_power == 110u &&
                         dfi_pool_moves[DFI_MOVE_HYDROPUMP].accuracy == 80u);
        DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_SUBSTITUTE].special == DFI_SPECIAL_UNMODELED &&
                         strstr(dfi_pool_move_unmodeled[DFI_MOVE_SUBSTITUTE], "primary volatile substitute") != NULL);
        /* Since step G37 the four hazards are modelled: the target class foeSide (the turn code runs it) and a side condition
         * column that is the DUOFORGE_SIDE_* value of its SIDE_START line (Aurora Veil, 4, is a handler of its own). */
        DF_CHECK(&t, dfi_pool_move_unmodeled[DFI_MOVE_STEALTHROCK] == NULL && dfi_pool_move_unmodeled[DFI_MOVE_SPIKES] == NULL &&
                         dfi_pool_move_unmodeled[DFI_MOVE_TOXICSPIKES] == NULL && dfi_pool_move_unmodeled[DFI_MOVE_STICKYWEB] == NULL &&
                         dfi_pool_moves[DFI_MOVE_STEALTHROCK].side_condition == DUOFORGE_SIDE_STEALTH_ROCK &&
                         dfi_pool_moves[DFI_MOVE_SPIKES].side_condition == DUOFORGE_SIDE_SPIKES &&
                         dfi_pool_moves[DFI_MOVE_TOXICSPIKES].side_condition == DUOFORGE_SIDE_TOXIC_SPIKES &&
                         dfi_pool_moves[DFI_MOVE_STICKYWEB].side_condition == DUOFORGE_SIDE_STICKY_WEB &&
                         dfi_pool_moves[DFI_MOVE_STEALTHROCK].target_class == DFI_TARGET_CLASS_FOE_SIDE &&
                         dfi_pool_moves[DFI_MOVE_SPIKES].target_class == DFI_TARGET_CLASS_FOE_SIDE &&
                         dfi_pool_moves[DFI_MOVE_TOXICSPIKES].target_class == DFI_TARGET_CLASS_FOE_SIDE &&
                         dfi_pool_moves[DFI_MOVE_STICKYWEB].target_class == DFI_TARGET_CLASS_FOE_SIDE);
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_ABSOLITEZ] == DFI_HANDLER_NONE &&
                         dfi_pool_item_unmodeled[DFI_ITEM_ABSOLITEZ] == NULL &&
                         dfi_pool_item_handler[DFI_ITEM_ABSOLITE] == DFI_HANDLER_NONE);
        /* Step G55: Damp Rock is an engine row (the rain's 8 turns), so it has no unmodelled feature any more. */
        DF_CHECK(&t, dfi_pool_item_handler[DFI_ITEM_DAMPROCK] == DFI_HANDLER_NONE && dfi_pool_item_unmodeled[DFI_ITEM_DAMPROCK] == NULL);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_LEVITATE] == DFI_HANDLER_NONE &&
                         dfi_pool_ability_unmodeled[DFI_ABILITY_LEVITATE] == NULL); /* an engine row since step G23-C */
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_EELEVATE] == DFI_HANDLER_UNMODELED);
        DF_CHECK(&t, dfi_pool_ability_handler[DFI_ABILITY_INTIMIDATE] == DFI_HANDLER_NONE);
        /* The target classes of the pool beyond the public ones: encoded, never a public value. */
        DF_CHECK_EQ_U64(&t, DFI_TARGET_CLASS_ALL_ADJACENT, 11u);
        DF_CHECK(&t, DFI_TARGET_CLASS_FOE_SIDE == 15u && DFI_TARGET_CLASS_FOE_SIDE > DFI_TARGET_CLASS_RANDOM_NORMAL);
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            /* A target class beyond the closure's is never in a modelled row. */
            DF_CHECK(&t, dfi_pool_moves[id].target_class <= DFI_TARGET_CLASS_RANDOM_NORMAL ||
                             dfi_pool_moves[id].target_class == DFI_TARGET_CLASS_ALL_ADJACENT ||
                             dfi_pool_moves[id].target_class == DFI_TARGET_CLASS_ALLIES || dfi_pool_moves[id].target_class == DFI_TARGET_CLASS_FOE_SIDE ||
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

    /* The Mega of a (base forme, stone) pair (step G23-A): the second Mega formes of Absol, Charizard, Garchomp, Lucario
     * and Raichu are not the link of their base forme, and the stone's own row finds them; every Mega forme is reached by
     * its own stone from its own base forme, and by no other pair. */
    {
        uint32_t second = 0u;
        for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
            const dfi_pool_forme_data *fo = &dfi_pool_formes[f];
            if (fo->is_mega == 0u) {
                continue;
            }
            if (dfi_pool_formes[fo->base_forme].mega_forme != f) {
                second += 1u;
            }
            DF_CHECK_EQ_U64(&t, dfi_mega_of(fo->base_forme, 1u + fo->mega_item), f);
            for (uint32_t other = 0u; other < DFI_POOL_FORME_COUNT; ++other) {
                if (other != fo->base_forme) {
                    DF_CHECK(&t, dfi_mega_of(other, 1u + fo->mega_item) != f);
                }
            }
        }
        DF_CHECK_EQ_U64(&t, second, 5u);
        /* The pairs by name, and what is no pair. */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, 1u + DFI_ITEM_CHARIZARDITEY), DFI_FORME_CHARIZARDMEGAY);
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, 1u + DFI_ITEM_CHARIZARDITEX), DFI_FORME_CHARIZARDMEGAX);
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_MEOWSTIC, 1u + DFI_ITEM_MEOWSTICITE), DFI_FORME_MEOWSTICMMEGA);
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_MEOWSTICF, 1u + DFI_ITEM_MEOWSTICITE), DFI_FORME_MEOWSTICFMEGA);
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, 0u), DFI_FORME_NONE);                          /* no item */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, 1u + DFI_ITEM_SALAMENCITE), DFI_FORME_NONE);   /* another forme's stone */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, 1u + DFI_ITEM_LEFTOVERS), DFI_FORME_NONE);     /* no stone */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARDMEGAX, 1u + DFI_ITEM_CHARIZARDITEX), DFI_FORME_NONE); /* a Mega forme */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_FORME_CHARIZARD, DFI_POOL_ITEM_COUNT + 1u), DFI_FORME_NONE);    /* beyond the table */
        DF_CHECK_EQ_U64(&t, dfi_mega_of(DFI_POOL_FORME_COUNT, 1u + DFI_ITEM_CHARIZARDITEX), DFI_FORME_NONE);
        /* The support gate follows the pair: Charizard-Mega-X brings Tough Claws, which is marked (and Charizardite X is
         * marked since step G23-C); Absol-Mega-Z brings Sharpness, marked since step G34, and Absolite Z is marked by step G43. */
        DF_CHECK(&t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_CHARIZARD, 1u + DFI_ITEM_CHARIZARDITEX));
        DF_CHECK(&t, !dfi_manifest_mega_of(&dfi_support, DFI_FORME_CHARIZARD, 1u + DFI_ITEM_LEFTOVERS));
        DF_CHECK(&t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_ABSOL, 1u + DFI_ITEM_ABSOLITEZ)); /* Sharpness is marked since step G34 */
        dfi_support_manifest sharp = dfi_support;
        sharp.abilities[DFI_ABILITY_SHARPNESS] = 0u;
        DF_CHECK(&t, !dfi_manifest_mega_of(&sharp, DFI_FORME_ABSOL, 1u + DFI_ITEM_ABSOLITEZ)); /* the pair follows the Mega's ability */
        DF_CHECK(&t, dfi_support.items[DFI_ITEM_CHARIZARDITEX] != 0u && dfi_support.items[DFI_ITEM_ABSOLITEZ] != 0u); /* G43 marks Absolite Z */
        /* The support is that of the pair's own Mega ability: with Tough Claws unmarked Charizardite X is unsupported and
         * Charizardite Y (Drought) is not. */
        dfi_support_manifest claws = dfi_support;
        claws.abilities[DFI_ABILITY_TOUGHCLAWS] = 0u;
        DF_CHECK(&t, !dfi_manifest_mega_of(&claws, DFI_FORME_CHARIZARD, 1u + DFI_ITEM_CHARIZARDITEX));
        DF_CHECK(&t, dfi_manifest_mega_of(&claws, DFI_FORME_CHARIZARD, 1u + DFI_ITEM_CHARIZARDITEY));
    }

    return df_test_end(&t);
}
