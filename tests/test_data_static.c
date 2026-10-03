/*
 * duoforge.data.static (white-box): the static read API of decision 0020: duoforge_data_forme_static, _move_static,
 * _item_static, _ability_static, _nature_static and _type_effect.
 *
 *  - Every row of every table, under every combat kind, equals the generated table's row field by field (the oracle is
 *    written here from the table structs, never from the functions under test), for the rows below the kind's count;
 *    the same call at the count is E_INVALID_ARGUMENT and leaves the output untouched.
 *  - Spot checks of rows by name against the pinned data (types, base stats, weights, priorities, hit counts, every
 *    flag, every target class 1 to 15, every item and ability family, the Mega stones, the natures, the type chart).
 *  - The contract: NULL arguments, a SYNTHETIC context (E_UNSUPPORTED), the order of the checks, and that no output is
 *    written on an error. The two sizes of the generated columns and the struct sizes are pinned.
 *  - The values do not depend on the context: two contexts of one kind and of different kinds with the row in both give
 *    the same struct (pure functions of the kind's table and the id).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "support/check.h"

#define KIND_COUNT 6u
static const uint32_t k_kinds[KIND_COUNT] = {
    DUOFORGE_DATA_KIND_CLOSURE,    DUOFORGE_DATA_KIND_CLOSURE_DEV, DUOFORGE_DATA_KIND_TEAM_C,
    DUOFORGE_DATA_KIND_TEAM_C_DEV, DUOFORGE_DATA_KIND_POOL,        DUOFORGE_DATA_KIND_POOL_DEV,
};

static duoforge_context *make(df_test *t, uint32_t kind)
{
    duoforge_context *ctx = NULL;
    const duoforge_context_config cfg = {kind, 6u, 4u, 0u, 0u, NULL};
    DF_CHECK(t, duoforge_context_create(&cfg, &ctx) == DUOFORGE_OK);
    return ctx;
}

static uint32_t id_of(df_test *t, const duoforge_context *ctx, uint32_t table, const char *name)
{
    uint32_t id = 0xDEADBEEFu;
    DF_CHECK(t, duoforge_data_find(ctx, table, name, strlen(name), &id) == DUOFORGE_OK);
    return id;
}

/* ------------------------------------------------------------- every row */

static void rows_forme(df_test *t, const duoforge_context *ctx, uint32_t count)
{
    for (uint32_t id = 0u; id < count; ++id) {
        duoforge_forme_static got;
        memset(&got, 0xA5, sizeof got);
        if (!DF_CHECK(t, duoforge_data_forme_static(ctx, id, &got) == DUOFORGE_OK)) {
            continue;
        }
        const dfi_pool_forme_data *f = &dfi_pool_formes[id];
        DF_CHECK_EQ_U64(t, got.types[0], f->types[0]);
        DF_CHECK_EQ_U64(t, got.types[1], f->types[1] == DFI_CLOSURE_NONE ? DUOFORGE_DATA_NONE : f->types[1]);
        for (uint32_t s = 0u; s < 6u; ++s) {
            DF_CHECK_EQ_U64(t, got.base_stats[s], f->base[s]);
        }
        DF_CHECK_EQ_U64(t, got.weight_hg, f->weight_hg);
        DF_CHECK_EQ_U64(t, got.default_ability, f->ability);
        DF_CHECK_EQ_U64(t, got.is_mega, f->is_mega);
        DF_CHECK(t, got.types[0] < DFI_TYPE_COUNT && (got.types[1] == DUOFORGE_DATA_NONE || got.types[1] < DFI_TYPE_COUNT));
    }
}

static void rows_move(df_test *t, const duoforge_context *ctx, uint32_t count)
{
    for (uint32_t id = 0u; id < count; ++id) {
        duoforge_move_static got;
        memset(&got, 0xA5, sizeof got);
        if (!DF_CHECK(t, duoforge_data_move_static(ctx, id, &got) == DUOFORGE_OK)) {
            continue;
        }
        const dfi_move_data *m = &dfi_pool_moves[id];
        DF_CHECK_EQ_U64(t, got.type, m->type);
        DF_CHECK_EQ_U64(t, got.category, m->category);
        DF_CHECK_EQ_U64(t, got.base_power, m->base_power);
        DF_CHECK_EQ_U64(t, got.accuracy, m->accuracy);
        DF_CHECK_EQ_U64(t, got.pp, m->pp_max); /* the table's pp_max is the derived Champions PP */
        DF_CHECK(t, (int32_t)got.priority == (int32_t)m->priority - 8);
        DF_CHECK_EQ_U64(t, got.target_class, m->target_class);
        DF_CHECK_EQ_U64(t, got.flags, dfi_pool_move_static_flags[id]);
        DF_CHECK_EQ_U64(t, got.crit_stage, (uint32_t)m->crit_ratio - 1u);
        DF_CHECK_EQ_U64(t, got.drain[0], m->drain[0]);
        DF_CHECK_EQ_U64(t, got.drain[1], m->drain[1]);
        DF_CHECK_EQ_U64(t, got.recoil[0], m->recoil[0]);
        DF_CHECK_EQ_U64(t, got.recoil[1], m->recoil[1]);
        DF_CHECK_EQ_U64(t, got.secondary_chance, m->sec_chance);
        DF_CHECK_EQ_U64(t, got.hits_min, dfi_pool_move_static_hits[id][0]);
        DF_CHECK_EQ_U64(t, got.hits_max, dfi_pool_move_static_hits[id][1]);
        /* what the values must be, whatever the tables say */
        DF_CHECK(t, got.type < DFI_TYPE_COUNT);
        DF_CHECK(t, got.category <= DUOFORGE_MOVE_CATEGORY_STATUS);
        DF_CHECK(t, got.target_class >= 1u && got.target_class <= DUOFORGE_TARGET_CLASS_STATIC_COUNT);
        DF_CHECK(t, got.hits_min >= 1u && got.hits_min <= got.hits_max);
        DF_CHECK(t, (int32_t)got.priority >= -7 && (int32_t)got.priority <= 5);
        DF_CHECK(t, got.pp >= 1u);
        DF_CHECK(t, (got.flags & ~0x7FFu) == 0u);
        DF_CHECK(t, got.category != DUOFORGE_MOVE_CATEGORY_STATUS || got.base_power == 0u);
    }
}

static void rows_item(df_test *t, const duoforge_context *ctx, uint32_t count)
{
    for (uint32_t id = 0u; id < count; ++id) {
        duoforge_item_static got;
        memset(&got, 0xA5, sizeof got);
        if (!DF_CHECK(t, duoforge_data_item_static(ctx, id, &got) == DUOFORGE_OK)) {
            continue;
        }
        const dfi_item_family *fam = &dfi_pool_item_family[id];
        DF_CHECK_EQ_U64(t, got.family, fam->family);
        DF_CHECK_EQ_U64(t, got.family_type, fam->family == 0u ? DUOFORGE_DATA_NONE : fam->type);
        const bool stone = dfi_pool_items[id].mega_forme != DFI_FORME_NONE;
        DF_CHECK_EQ_U64(t, got.is_mega_stone, stone ? 1u : 0u);
        DF_CHECK_EQ_U64(t, got.mega_species, stone ? dfi_pool_items[id].mega_forme : DUOFORGE_DATA_NONE);
        DF_CHECK(t, got.family <= DUOFORGE_ITEM_FAMILY_RESIST_BERRY);
        DF_CHECK(t, got.family == 0u || got.family_type < DFI_TYPE_COUNT);
    }
}

static void rows_ability(df_test *t, const duoforge_context *ctx, uint32_t count)
{
    for (uint32_t id = 0u; id < count; ++id) {
        duoforge_ability_static got;
        memset(&got, 0xA5, sizeof got);
        if (!DF_CHECK(t, duoforge_data_ability_static(ctx, id, &got) == DUOFORGE_OK)) {
            continue;
        }
        const dfi_ability_family *fam = &dfi_pool_ability_family[id];
        DF_CHECK_EQ_U64(t, got.family, fam->family);
        DF_CHECK_EQ_U64(t, got.family_param, fam->family == 0u ? DUOFORGE_DATA_NONE : fam->param);
        DF_CHECK(t, got.family <= DUOFORGE_ABILITY_FAMILY_TERRAIN_SETTER);
    }
}

static void rows_nature(df_test *t, const duoforge_context *ctx)
{
    uint32_t neutral = 0u;
    for (uint32_t id = 0u; id < DFI_NATURE_COUNT; ++id) {
        duoforge_nature_static got;
        memset(&got, 0xA5, sizeof got);
        if (!DF_CHECK(t, duoforge_data_nature_static(ctx, id, &got) == DUOFORGE_OK)) {
            continue;
        }
        const uint32_t plus = dfi_closure_natures[id].plus;
        const uint32_t minus = dfi_closure_natures[id].minus;
        DF_CHECK_EQ_U64(t, got.raised_stat, plus == DFI_CLOSURE_NONE ? DUOFORGE_DATA_NONE : plus);
        DF_CHECK_EQ_U64(t, got.lowered_stat, minus == DFI_CLOSURE_NONE ? DUOFORGE_DATA_NONE : minus);
        DF_CHECK_EQ_U64(t, got.raised_stat == DUOFORGE_DATA_NONE, got.lowered_stat == DUOFORGE_DATA_NONE);
        if (got.raised_stat == DUOFORGE_DATA_NONE) {
            neutral += 1u;
        } else {
            DF_CHECK(t, got.raised_stat >= 1u && got.raised_stat <= 5u && got.lowered_stat >= 1u && got.lowered_stat <= 5u);
            DF_CHECK(t, got.raised_stat != got.lowered_stat);
        }
    }
    DF_CHECK_EQ_U64(t, neutral, 5u); /* Hardy, Docile, Serious, Bashful, Quirky */
}

static void rows_type_effect(df_test *t, const duoforge_context *ctx)
{
    uint32_t seen[4] = {0u, 0u, 0u, 0u};
    for (uint32_t atk = 0u; atk < DFI_TYPE_COUNT; ++atk) {
        for (uint32_t def = 0u; def < DFI_TYPE_COUNT; ++def) {
            uint32_t num = 0xA5A5A5A5u;
            uint32_t den = 0xA5A5A5A5u;
            if (!DF_CHECK(t, duoforge_data_type_effect(ctx, atk, def, &num, &den) == DUOFORGE_OK)) {
                continue;
            }
            const uint32_t code = dfi_closure_type_chart[def][atk];
            DF_CHECK_EQ_U64(t, num, code == DFI_EFFECT_SUPER ? 2u : code == DFI_EFFECT_IMMUNE ? 0u : 1u);
            DF_CHECK_EQ_U64(t, den, code == DFI_EFFECT_RESISTED ? 2u : 1u);
            seen[code] += 1u;
        }
    }
    for (uint32_t c = 0u; c < 4u; ++c) {
        DF_CHECK(t, seen[c] > 0u); /* all four multipliers occur */
    }
}

/* -------------------------------------------------------- spot checks (POOL) */

static void spot_checks(df_test *t, const duoforge_context *ctx)
{
    duoforge_forme_static fo;
    /* Rillaboom: a single Grass type, 900 hg; Staraptor: Normal and Flying; Charizard-Mega-Y is a Mega with its own ability */
    DF_CHECK(t, duoforge_data_forme_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "rillaboom"), &fo) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, fo.types[0], DUOFORGE_TYPE_GRASS);
    DF_CHECK_EQ_U64(t, fo.types[1], DUOFORGE_DATA_NONE);
    const uint32_t rilla[6] = {100u, 125u, 90u, 60u, 70u, 85u};
    for (uint32_t s = 0u; s < 6u; ++s) {
        DF_CHECK_EQ_U64(t, fo.base_stats[s], rilla[s]);
    }
    DF_CHECK_EQ_U64(t, fo.weight_hg, 900u);
    DF_CHECK_EQ_U64(t, fo.is_mega, 0u);
    DF_CHECK(t, duoforge_data_forme_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "staraptor"), &fo) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, fo.types[0], DUOFORGE_TYPE_NORMAL);
    DF_CHECK_EQ_U64(t, fo.types[1], DUOFORGE_TYPE_FLYING);
    DF_CHECK(t, duoforge_data_forme_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "staraptormega"), &fo) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, fo.is_mega, 1u);
    duoforge_forme_info info;
    DF_CHECK(t, duoforge_data_forme_info(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "staraptor"), &info) == DUOFORGE_OK);
    duoforge_forme_static base;
    DF_CHECK(t, duoforge_data_forme_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "staraptor"), &base) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, base.default_ability, info.abilities[0]); /* the first legal ability */
    DF_CHECK(t, duoforge_data_forme_static(ctx, info.mega_species, &fo) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, fo.default_ability, info.mega_ability); /* a Mega forme's own */

    /* moves */
    duoforge_move_static mv;
#define MOVE(name) (id_of(t, ctx, DUOFORGE_DATA_TABLE_MOVE, name))
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("lowkick"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE) != 0u && mv.base_power == 0u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("lastrespects"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE) != 0u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("closecombat"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE) == 0u && mv.base_power == 120u);
    DF_CHECK_EQ_U64(t, mv.type, DUOFORGE_TYPE_FIGHTING);
    DF_CHECK_EQ_U64(t, mv.category, DUOFORGE_MOVE_CATEGORY_PHYSICAL);
    DF_CHECK_EQ_U64(t, mv.accuracy, 100u);
    DF_CHECK(t, (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_CONTACT) != 0u);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_NORMAL);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("fakeout"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (int32_t)mv.priority == 3);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("quickattack"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (int32_t)mv.priority == 1);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("trickroom"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, (int32_t)mv.priority == -7);
    DF_CHECK_EQ_U64(t, mv.category, DUOFORGE_MOVE_CATEGORY_STATUS);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("bulletseed"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.hits_min == 2u && mv.hits_max == 5u && (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_BULLET) != 0u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("dualwingbeat"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.hits_min == 2u && mv.hits_max == 2u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("tripleaxel"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.hits_min == 3u && mv.hits_max == 3u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("populationbomb"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.hits_min == 10u && mv.hits_max == 10u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("shadowball"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.hits_min == 1u && mv.hits_max == 1u && (mv.flags & DUOFORGE_MOVE_STATIC_FLAG_BULLET) != 0u);
    DF_CHECK_EQ_U64(t, mv.secondary_chance, 20u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("flareblitz"), &mv) == DUOFORGE_OK);
    DF_CHECK(t, mv.recoil[0] == 33u && mv.recoil[1] == 100u);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("struggle"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_RANDOM_NORMAL);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("earthquake"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_ALL_ADJACENT);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("counter"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_SCRIPTED);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("healbell"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_ALLY_TEAM);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("lifedew"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_ALLIES);
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("spikes"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.target_class, DUOFORGE_TARGET_CLASS_FOE_SIDE);
    /* every flag, each on a move that has it in the pin */
    static const struct {
        const char *move;
        uint32_t flag;
    } flagged[] = {
        {"icepunch", DUOFORGE_MOVE_STATIC_FLAG_PUNCH},     {"crunch", DUOFORGE_MOVE_STATIC_FLAG_BITE},
        {"aurasphere", DUOFORGE_MOVE_STATIC_FLAG_PULSE},   {"leafblade", DUOFORGE_MOVE_STATIC_FLAG_SLICING},
        {"hurricane", DUOFORGE_MOVE_STATIC_FLAG_WIND},     {"swordsdance", DUOFORGE_MOVE_STATIC_FLAG_DANCE},
        {"sleeppowder", DUOFORGE_MOVE_STATIC_FLAG_POWDER}, {"hypervoice", DUOFORGE_MOVE_STATIC_FLAG_SOUND},
        {"flareblitz", DUOFORGE_MOVE_STATIC_FLAG_CONTACT}, {"shadowball", DUOFORGE_MOVE_STATIC_FLAG_BULLET},
    };
    for (uint32_t i = 0u; i < sizeof flagged / sizeof flagged[0]; ++i) {
        DF_CHECK(t, duoforge_data_move_static(ctx, MOVE(flagged[i].move), &mv) == DUOFORGE_OK);
        DF_CHECK(t, (mv.flags & flagged[i].flag) != 0u);
    }
    DF_CHECK(t, duoforge_data_move_static(ctx, MOVE("protect"), &mv) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, mv.flags, 0u);
#undef MOVE

    /* items and abilities */
    duoforge_item_static it;
    DF_CHECK(t, duoforge_data_item_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ITEM, "miracleseed"), &it) == DUOFORGE_OK);
    DF_CHECK(t, it.family == DUOFORGE_ITEM_FAMILY_TYPE_BOOSTER && it.family_type == DUOFORGE_TYPE_GRASS && it.is_mega_stone == 0u);
    DF_CHECK_EQ_U64(t, it.mega_species, DUOFORGE_DATA_NONE);
    DF_CHECK(t, duoforge_data_item_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ITEM, "occaberry"), &it) == DUOFORGE_OK);
    DF_CHECK(t, it.family == DUOFORGE_ITEM_FAMILY_RESIST_BERRY && it.family_type == DUOFORGE_TYPE_FIRE);
    DF_CHECK(t, duoforge_data_item_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ITEM, "leftovers"), &it) == DUOFORGE_OK);
    DF_CHECK(t, it.family == DUOFORGE_ITEM_FAMILY_NONE && it.family_type == DUOFORGE_DATA_NONE);
    DF_CHECK(t, duoforge_data_item_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ITEM, "staraptite"), &it) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, it.is_mega_stone, 1u);
    DF_CHECK_EQ_U64(t, it.mega_species, id_of(t, ctx, DUOFORGE_DATA_TABLE_SPECIES, "staraptormega"));
    duoforge_ability_static ab;
    DF_CHECK(t, duoforge_data_ability_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ABILITY, "drizzle"), &ab) == DUOFORGE_OK);
    DF_CHECK(t, ab.family == DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER && ab.family_param == DUOFORGE_WEATHER_RAIN);
    DF_CHECK(t, duoforge_data_ability_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ABILITY, "grassysurge"), &ab) == DUOFORGE_OK);
    DF_CHECK(t, ab.family == DUOFORGE_ABILITY_FAMILY_TERRAIN_SETTER && ab.family_param == DUOFORGE_TERRAIN_GRASSY);
    DF_CHECK(t, duoforge_data_ability_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ABILITY, "blaze"), &ab) == DUOFORGE_OK);
    DF_CHECK(t, ab.family == DUOFORGE_ABILITY_FAMILY_PINCH && ab.family_param == DUOFORGE_TYPE_FIRE);
    DF_CHECK(t, duoforge_data_ability_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ABILITY, "pixilate"), &ab) == DUOFORGE_OK);
    DF_CHECK(t, ab.family == DUOFORGE_ABILITY_FAMILY_ATE && ab.family_param == DUOFORGE_TYPE_FAIRY);
    DF_CHECK(t, duoforge_data_ability_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_ABILITY, "intimidate"), &ab) == DUOFORGE_OK);
    DF_CHECK(t, ab.family == DUOFORGE_ABILITY_FAMILY_NONE && ab.family_param == DUOFORGE_DATA_NONE);

    /* natures: +Atk -SpA, +SpA -Atk, +Spe -Atk, +Def -Atk, and a neutral one */
    static const struct {
        const char *name;
        uint32_t up;
        uint32_t down;
    } natures[] = {{"adamant", 1u, 3u}, {"modest", 3u, 1u}, {"timid", 5u, 1u}, {"bold", 2u, 1u},
                   {"hardy", DUOFORGE_DATA_NONE, DUOFORGE_DATA_NONE}};
    for (uint32_t i = 0u; i < sizeof natures / sizeof natures[0]; ++i) {
        duoforge_nature_static nat;
        DF_CHECK(t, duoforge_data_nature_static(ctx, id_of(t, ctx, DUOFORGE_DATA_TABLE_NATURE, natures[i].name), &nat) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, nat.raised_stat, natures[i].up);
        DF_CHECK_EQ_U64(t, nat.lowered_stat, natures[i].down);
    }

    /* the chart */
    static const struct {
        uint32_t atk;
        uint32_t def;
        uint32_t num;
        uint32_t den;
    } chart[] = {
        {DUOFORGE_TYPE_FIRE, DUOFORGE_TYPE_GRASS, 2u, 1u},      {DUOFORGE_TYPE_GRASS, DUOFORGE_TYPE_FIRE, 1u, 2u},
        {DUOFORGE_TYPE_WATER, DUOFORGE_TYPE_FIRE, 2u, 1u},      {DUOFORGE_TYPE_NORMAL, DUOFORGE_TYPE_GHOST, 0u, 1u},
        {DUOFORGE_TYPE_ELECTRIC, DUOFORGE_TYPE_GROUND, 0u, 1u}, {DUOFORGE_TYPE_NORMAL, DUOFORGE_TYPE_NORMAL, 1u, 1u},
        {DUOFORGE_TYPE_FAIRY, DUOFORGE_TYPE_DRAGON, 2u, 1u},    {DUOFORGE_TYPE_DRAGON, DUOFORGE_TYPE_FAIRY, 0u, 1u},
    };
    for (uint32_t i = 0u; i < sizeof chart / sizeof chart[0]; ++i) {
        uint32_t num = 9u;
        uint32_t den = 9u;
        DF_CHECK(t, duoforge_data_type_effect(ctx, chart[i].atk, chart[i].def, &num, &den) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, num, chart[i].num);
        DF_CHECK_EQ_U64(t, den, chart[i].den);
    }
}

/* ----------------------------------------------------------- the contract */

static void contract(df_test *t, const duoforge_context *ctx, const duoforge_context *synthetic, uint32_t counts[6])
{
    duoforge_forme_static fo;
    duoforge_move_static mv;
    duoforge_item_static it;
    duoforge_ability_static ab;
    duoforge_nature_static nat;
    uint32_t a = 0xA5A5A5A5u;
    uint32_t b = 0xA5A5A5A5u;
    /* NULL */
    DF_CHECK(t, duoforge_data_forme_static(NULL, 0u, &fo) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_static(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_move_static(NULL, 0u, &mv) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_move_static(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_item_static(NULL, 0u, &it) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_item_static(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_ability_static(NULL, 0u, &ab) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_ability_static(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_nature_static(NULL, 0u, &nat) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_nature_static(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(NULL, 0u, 0u, &a, &b) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(ctx, 0u, 0u, NULL, &b) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(ctx, 0u, 0u, &a, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, a == 0xA5A5A5A5u && b == 0xA5A5A5A5u);
    /* an id at the count (or beyond it) is E_INVALID_ARGUMENT and writes nothing */
    memset(&fo, 0xA5, sizeof fo);
    memset(&mv, 0xA5, sizeof mv);
    memset(&it, 0xA5, sizeof it);
    memset(&ab, 0xA5, sizeof ab);
    memset(&nat, 0xA5, sizeof nat);
    duoforge_forme_static fo_ref = fo;
    duoforge_move_static mv_ref = mv;
    duoforge_item_static it_ref = it;
    duoforge_ability_static ab_ref = ab;
    duoforge_nature_static nat_ref = nat;
    DF_CHECK(t, duoforge_data_forme_static(ctx, counts[DUOFORGE_DATA_TABLE_SPECIES], &fo) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_static(ctx, 0xFFFFFFFFu, &fo) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_move_static(ctx, counts[DUOFORGE_DATA_TABLE_MOVE], &mv) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_item_static(ctx, counts[DUOFORGE_DATA_TABLE_ITEM], &it) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_ability_static(ctx, counts[DUOFORGE_DATA_TABLE_ABILITY], &ab) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_nature_static(ctx, counts[DUOFORGE_DATA_TABLE_NATURE], &nat) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(ctx, DFI_TYPE_COUNT, 0u, &a, &b) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(ctx, 0u, DFI_TYPE_COUNT, &a, &b) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_type_effect(ctx, 0xFFFFFFFFu, 0xFFFFFFFFu, &a, &b) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, memcmp(&fo, &fo_ref, sizeof fo) == 0 && memcmp(&mv, &mv_ref, sizeof mv) == 0 &&
                    memcmp(&it, &it_ref, sizeof it) == 0 && memcmp(&ab, &ab_ref, sizeof ab) == 0 &&
                    memcmp(&nat, &nat_ref, sizeof nat) == 0 && a == 0xA5A5A5A5u && b == 0xA5A5A5A5u);
    /* a SYNTHETIC context has no tables: E_UNSUPPORTED, also for an id that no table has (the check order: NULL, kind, id) */
    DF_CHECK(t, duoforge_data_forme_static(synthetic, 0u, &fo) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_forme_static(synthetic, 0xFFFFFFFFu, &fo) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_move_static(synthetic, 0u, &mv) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_item_static(synthetic, 0u, &it) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_ability_static(synthetic, 0u, &ab) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_nature_static(synthetic, 0u, &nat) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_type_effect(synthetic, 0u, 0u, &a, &b) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_type_effect(synthetic, 99u, 99u, &a, &b) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_move_static(synthetic, 0xFFFFFFFFu, &mv) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_item_static(synthetic, 0xFFFFFFFFu, &it) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_ability_static(synthetic, 0xFFFFFFFFu, &ab) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_nature_static(synthetic, 0xFFFFFFFFu, &nat) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_data_forme_static(NULL, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, memcmp(&fo, &fo_ref, sizeof fo) == 0 && memcmp(&mv, &mv_ref, sizeof mv) == 0 &&
                    memcmp(&it, &it_ref, sizeof it) == 0 && memcmp(&ab, &ab_ref, sizeof ab) == 0 &&
                    memcmp(&nat, &nat_ref, sizeof nat) == 0 && a == 0xA5A5A5A5u && b == 0xA5A5A5A5u);
}

static void layout(df_test *t)
{
    DF_CHECK_EQ_U64(t, sizeof(duoforge_forme_static), 44u);
    DF_CHECK_EQ_U64(t, sizeof(duoforge_move_static), 64u);
    DF_CHECK_EQ_U64(t, sizeof(duoforge_item_static), 16u);
    DF_CHECK_EQ_U64(t, sizeof(duoforge_ability_static), 8u);
    DF_CHECK_EQ_U64(t, sizeof(duoforge_nature_static), 8u);
    DF_CHECK_EQ_U64(t, DUOFORGE_TARGET_CLASS_COUNT, 9u); /* the request API's count does not move */
    DF_CHECK_EQ_U64(t, DUOFORGE_TARGET_CLASS_STATIC_COUNT, 15u);
    /* the flag bits are distinct single bits, in the documented order */
    static const uint32_t bits[] = {
        DUOFORGE_MOVE_STATIC_FLAG_CONTACT, DUOFORGE_MOVE_STATIC_FLAG_SOUND,  DUOFORGE_MOVE_STATIC_FLAG_PUNCH,
        DUOFORGE_MOVE_STATIC_FLAG_BITE,    DUOFORGE_MOVE_STATIC_FLAG_BULLET, DUOFORGE_MOVE_STATIC_FLAG_PULSE,
        DUOFORGE_MOVE_STATIC_FLAG_SLICING, DUOFORGE_MOVE_STATIC_FLAG_WIND,   DUOFORGE_MOVE_STATIC_FLAG_DANCE,
        DUOFORGE_MOVE_STATIC_FLAG_POWDER,  DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE,
    };
    for (uint32_t i = 0u; i < sizeof bits / sizeof bits[0]; ++i) {
        DF_CHECK_EQ_U64(t, bits[i], 1u << i);
    }
    DF_CHECK_EQ_U64(t, DFI_POOL_CANONICAL_SIZE, 54153u); /* the pool canonical bytes: 4 + 2 bytes more per move */
}

/* Every target class 1..15 but one, every item and ability family and every flag occurs in the pool's rows. */
static void coverage(df_test *t, const duoforge_context *pool)
{
    uint32_t classes = 0u;
    uint32_t flags = 0u;
    uint32_t items = 0u;
    uint32_t abilities = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        duoforge_move_static mv;
        if (duoforge_data_move_static(pool, id, &mv) == DUOFORGE_OK) {
            classes |= 1u << mv.target_class;
            flags |= mv.flags;
        }
    }
    for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
        duoforge_item_static it;
        if (duoforge_data_item_static(pool, id, &it) == DUOFORGE_OK) {
            items |= 1u << it.family;
        }
    }
    for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
        duoforge_ability_static ab;
        if (duoforge_data_ability_static(pool, id, &ab) == DUOFORGE_OK) {
            abilities |= 1u << ab.family;
        }
    }
    /* 1..15 but ADJACENT_FOE (5), which no row of the pool has (the pin has it for a few moves outside the format) */
    DF_CHECK_EQ_U64(t, classes, 0xFFDEu);
    DF_CHECK_EQ_U64(t, flags, 0x7FFu);
    DF_CHECK_EQ_U64(t, items, 0x7u);
    DF_CHECK_EQ_U64(t, abilities, 0x1Fu);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.data.static");
    layout(&t);
    duoforge_context *pool = NULL;
    for (uint32_t k = 0u; k < KIND_COUNT; ++k) {
        duoforge_context *ctx = make(&t, k_kinds[k]);
        if (ctx == NULL) {
            continue;
        }
        uint32_t counts[6] = {0u};
        for (uint32_t table = 1u; table <= DUOFORGE_DATA_TABLE_COUNT; ++table) {
            DF_CHECK(&t, duoforge_data_count(ctx, table, &counts[table]) == DUOFORGE_OK);
        }
        rows_forme(&t, ctx, counts[DUOFORGE_DATA_TABLE_SPECIES]);
        rows_move(&t, ctx, counts[DUOFORGE_DATA_TABLE_MOVE]);
        rows_item(&t, ctx, counts[DUOFORGE_DATA_TABLE_ITEM]);
        rows_ability(&t, ctx, counts[DUOFORGE_DATA_TABLE_ABILITY]);
        rows_nature(&t, ctx);
        rows_type_effect(&t, ctx);
        if (k_kinds[k] == DUOFORGE_DATA_KIND_POOL) {
            pool = ctx;
            spot_checks(&t, ctx);
            coverage(&t, ctx);
            const uint8_t classes[3] = {DUOFORGE_TARGET_CLASS_NORMAL, DUOFORGE_TARGET_CLASS_SELF, DUOFORGE_TARGET_CLASS_ALL};
            duoforge_context *synthetic = NULL;
            const duoforge_context_config cfg = {DUOFORGE_DATA_KIND_SYNTHETIC, 6u, 4u, 3u, 3u, classes};
            if (DF_CHECK(&t, duoforge_context_create(&cfg, &synthetic) == DUOFORGE_OK)) {
                contract(&t, ctx, synthetic, counts);
                duoforge_context_destroy(synthetic);
            }
        } else {
            /* a kind with fewer rows: the first rows are the pool's, the count ends the table */
            DF_CHECK(&t, counts[DUOFORGE_DATA_TABLE_MOVE] <= DFI_POOL_MOVE_COUNT);
            if (counts[DUOFORGE_DATA_TABLE_MOVE] < DFI_POOL_MOVE_COUNT) {
                duoforge_move_static mv;
                DF_CHECK(&t, duoforge_data_move_static(ctx, counts[DUOFORGE_DATA_TABLE_MOVE], &mv) == DUOFORGE_E_INVALID_ARGUMENT);
            }
        }
        if (ctx != pool) {
            duoforge_context_destroy(ctx);
        }
    }
    /* the value of a row does not depend on the kind that reads it */
    duoforge_context *closure = make(&t, DUOFORGE_DATA_KIND_CLOSURE);
    if (closure != NULL && pool != NULL) {
        for (uint32_t id = 0u; id < DFI_MOVE_COUNT; ++id) {
            duoforge_move_static a;
            duoforge_move_static b;
            DF_CHECK(&t, duoforge_data_move_static(closure, id, &a) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_data_move_static(pool, id, &b) == DUOFORGE_OK);
            DF_CHECK(&t, memcmp(&a, &b, sizeof a) == 0);
        }
    }
    if (closure != NULL) {
        duoforge_context_destroy(closure);
    }
    if (pool != NULL) {
        duoforge_context_destroy(pool);
    }
    return df_test_end(&t);
}
