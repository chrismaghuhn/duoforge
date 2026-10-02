/*
 * duoforge.combat.ability_family (white-box): the ability families of
 * decision 0015 as the battle reads them (src/combat/ability_family.h). The
 * "-ate" and the pinch rules decide from the family column and its type and
 * the setters of the entry from the column and its weather or terrain, and
 * from nothing else; here every ability of the pool is run against every
 * type (and the typeless hit of Struggle), and for the pinch rule against
 * HP values around a third, and the answer is compared with a table written
 * down below from the pinned handlers (data/abilities.ts: the type of each
 * -ate ability's onModifyType and of each pinch ability's onModifyAtk and
 * onModifySpA), not read from the column.
 *
 * Pixilate, Refrigerate, Torrent and Swarm cannot be set up through the
 * public API (no pool forme can carry them yet), so this is also where their
 * dispatch is checked; duoforge.data.pool_families runs their pinned
 * handlers against the columns. What the families do to the damage is
 * checked by the recorded battles (the closure and Team C ones with Aerilate
 * and Blaze, duoforge.reference.conformance_pool_data with Overgrow).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/ability_family.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

typedef struct ability_type {
    uint32_t ability; /* DFI_ABILITY_* */
    uint32_t type;    /* DFI_TYPE_*: the type a Normal move becomes, or the type a pinch boosts */
} ability_type;

/* ATE: a Normal move becomes the type (and gets BasePower x4915/4096). */
static const ability_type ATES[] = {
    {DFI_ABILITY_AERILATE, DFI_TYPE_FLYING},
    {DFI_ABILITY_PIXILATE, DFI_TYPE_FAIRY},
    {DFI_ABILITY_REFRIGERATE, DFI_TYPE_ICE},
};

/* PINCH: Atk and SpA x1.5 for a move of the type at a third of the HP or less. */
static const ability_type PINCHES[] = {
    {DFI_ABILITY_BLAZE, DFI_TYPE_FIRE},
    {DFI_ABILITY_OVERGROW, DFI_TYPE_GRASS},
    {DFI_ABILITY_TORRENT, DFI_TYPE_WATER},
    {DFI_ABILITY_SWARM, DFI_TYPE_BUG},
};

/* WEATHER_SETTER and TERRAIN_SETTER: what the entry (onStart) sets, as the state value. */
static const ability_type WEATHER_SETTERS[] = {
    {DFI_ABILITY_DRIZZLE, DFI_WEATHER_RAIN},
    {DFI_ABILITY_DROUGHT, DFI_WEATHER_SUN},
};
static const ability_type TERRAIN_SETTERS[] = {
    {DFI_ABILITY_GRASSYSURGE, DFI_TERRAIN_GRASSY},
    {DFI_ABILITY_PSYCHICSURGE, DFI_TERRAIN_PSYCHIC},
};

#define N_WEATHER_SETTERS (sizeof WEATHER_SETTERS / sizeof WEATHER_SETTERS[0])
#define N_TERRAIN_SETTERS (sizeof TERRAIN_SETTERS / sizeof TERRAIN_SETTERS[0])
#define N_ATES (sizeof ATES / sizeof ATES[0])
#define N_PINCHES (sizeof PINCHES / sizeof PINCHES[0])

static uint32_t type_in(const ability_type *table, size_t n, uint32_t ability)
{
    for (size_t i = 0u; i < n; ++i) {
        if (table[i].ability == ability) {
            return table[i].type;
        }
    }
    return DFI_CLOSURE_NONE;
}

static dfi_member holder(uint32_t ability, uint32_t hp, uint32_t hp_max)
{
    dfi_member m;
    memset(&m, 0, sizeof m);
    m.ability = (uint8_t)(ability + 1u); /* abilities are stored as 1 + id */
    m.hp = (uint16_t)hp;
    m.hp_max = (uint16_t)hp_max;
    return m;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.ability_family");

    /* Each family is closed: no ability in both, and together exactly the
     * abilities with a family column of these two kinds. */
    for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
        const bool ate = type_in(ATES, N_ATES, id) != DFI_CLOSURE_NONE;
        const bool pinch = type_in(PINCHES, N_PINCHES, id) != DFI_CLOSURE_NONE;
        DF_CHECK(&t, !(ate && pinch));
        const uint32_t family = dfi_pool_ability_family[id].family;
        DF_CHECK_EQ_U64(&t, family == DFI_ABILITY_FAMILY_ATE || family == DFI_ABILITY_FAMILY_PINCH, ate || pinch);
    }

    DF_CHECK_EQ_U64(&t, DFI_ATE_MODIFIER, 4915u);
    DF_CHECK_EQ_U64(&t, DFI_PINCH_MODIFIER, 6144u);

    uint32_t ate_changes = 0u;
    uint32_t ate_boosts = 0u;
    uint32_t pinch_hits = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
        const uint32_t ate_type = type_in(ATES, N_ATES, id);
        const uint32_t pinch_type = type_in(PINCHES, N_PINCHES, id);
        const dfi_member m = holder(id, 100u, 300u); /* exactly a third */
        /* Every move type, the typeless hit (DFI_TYPE_COUNT) and a value beyond it included. */
        for (uint32_t type = 0u; type <= DFI_TYPE_COUNT + 1u; ++type) {
            /* onModifyType: only a Normal move changes, to the ability's type. */
            const uint32_t want_type = ate_type != DFI_CLOSURE_NONE && type == DFI_TYPE_NORMAL ? ate_type : type;
            if (!DF_CHECK(&t, dfi_ate_type_of(&m, &dfi_pool_moves[DFI_MOVE_HYPERVOICE], type) == want_type)) {
                fprintf(stderr, "  ate type: ability %u, type %u: expected %u\n", (unsigned)id, (unsigned)type,
                        (unsigned)want_type);
            }
            ate_changes += want_type != type ? 1u : 0u;
            /* onBasePower: the move was Normal and is now of the ability's type. */
            for (uint32_t base = 0u; base <= DFI_TYPE_COUNT; ++base) {
                const bool want = ate_type != DFI_CLOSURE_NONE && base == DFI_TYPE_NORMAL && type == ate_type;
                if (!DF_CHECK(&t, dfi_ate_boosts(&m, base, type) == want)) {
                    fprintf(stderr, "  ate boost: ability %u, base %u, type %u: expected %d\n", (unsigned)id,
                            (unsigned)base, (unsigned)type, (int)want);
                }
                ate_boosts += want ? 1u : 0u;
            }
            /* The pinch: a move of the type at hp * 3 <= maxhp. */
            static const struct {
                uint32_t hp, hp_max;
                bool low;
            } cases[] = {
                {100u, 300u, true}, {99u, 300u, true}, {101u, 300u, false}, {1u, 300u, true},   {0u, 300u, true},
                {300u, 300u, false}, {1u, 3u, true},    {2u, 3u, false},     {67u, 200u, false}, {66u, 200u, true},
                {1u, 1u, false},
            };
            for (size_t c = 0u; c < sizeof cases / sizeof cases[0]; ++c) {
                const dfi_member h = holder(id, cases[c].hp, cases[c].hp_max);
                const bool want = pinch_type == type && cases[c].low;
                if (!DF_CHECK(&t, dfi_pinch_applies(&h, type) == want)) {
                    fprintf(stderr, "  pinch: ability %u, type %u, hp %u of %u: expected %d\n", (unsigned)id,
                            (unsigned)type, (unsigned)cases[c].hp, (unsigned)cases[c].hp_max, (int)want);
                }
                pinch_hits += want ? 1u : 0u;
            }
        }
    }
    /* Each -ate ability changes the one Normal type and boosts it once; each pinch ability fires for its one type
     * at the six low-HP cases of the table. */
    DF_CHECK_EQ_U64(&t, ate_changes, N_ATES);
    DF_CHECK_EQ_U64(&t, ate_boosts, N_ATES);
    DF_CHECK_EQ_U64(&t, pinch_hits, N_PINCHES * 6u);

    /* The moves an -ate ability leaves alone, by what the move is, not by its type: of the pool's Normal moves
     * only Weather Ball keeps its type (the handler's noModifyType list), every other one becomes the ability's. */
    for (size_t i = 0u; i < N_ATES; ++i) {
        const dfi_member m = holder(ATES[i].ability, 100u, 300u);
        uint32_t normal_moves = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            const dfi_move_data *md = &dfi_pool_moves[id];
            if (md->type != DFI_TYPE_NORMAL || id == DFI_MOVE_STRUGGLE) {
                continue;
            }
            normal_moves += 1u;
            const uint32_t want = id == DFI_MOVE_WEATHERBALL ? DFI_TYPE_NORMAL : ATES[i].type;
            if (!DF_CHECK(&t, dfi_ate_type_of(&m, md, DFI_TYPE_NORMAL) == want)) {
                fprintf(stderr, "  ate: ability %u, move %u: expected type %u\n", (unsigned)ATES[i].ability,
                        (unsigned)id, (unsigned)want);
            }
        }
        DF_CHECK(&t, normal_moves >= 2u); /* Weather Ball and at least one other */
    }

    /* The setters: every ability of the pool, the answer from the table above. The state values are the
     * engine's own (DFI_WEATHER_*, DFI_TERRAIN_*), not the family codes of the column. */
    for (uint32_t id = 0u; id < DFI_POOL_ABILITY_COUNT; ++id) {
        const dfi_member m = holder(id, 100u, 300u);
        const uint32_t weather = type_in(WEATHER_SETTERS, N_WEATHER_SETTERS, id);
        const uint32_t terrain = type_in(TERRAIN_SETTERS, N_TERRAIN_SETTERS, id);
        DF_CHECK_EQ_U64(&t, dfi_weather_set_by(&m), weather == DFI_CLOSURE_NONE ? DFI_WEATHER_NONE : weather);
        DF_CHECK_EQ_U64(&t, dfi_terrain_set_by(&m), terrain == DFI_CLOSURE_NONE ? DFI_TERRAIN_NONE : terrain);
        const uint32_t family = dfi_pool_ability_family[id].family;
        DF_CHECK_EQ_U64(&t, family == DFI_ABILITY_FAMILY_WEATHER_SETTER, weather != DFI_CLOSURE_NONE);
        DF_CHECK_EQ_U64(&t, family == DFI_ABILITY_FAMILY_TERRAIN_SETTER, terrain != DFI_CLOSURE_NONE);
    }
    DF_CHECK_EQ_U64(&t, N_WEATHER_SETTERS, 2u);
    DF_CHECK_EQ_U64(&t, N_TERRAIN_SETTERS, 2u);

    /* No ability at all, and a holder that is not there. */
    {
        dfi_member none = holder(0u, 1u, 300u);
        none.ability = 0u;
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            DF_CHECK(&t, dfi_ate_type_of(&none, &dfi_pool_moves[DFI_MOVE_HYPERVOICE], type) == type);
            DF_CHECK(&t, !dfi_ate_boosts(&none, DFI_TYPE_NORMAL, type));
            DF_CHECK(&t, !dfi_pinch_applies(&none, type));
            DF_CHECK_EQ_U64(&t, dfi_weather_set_by(&none), DFI_WEATHER_NONE);
            DF_CHECK_EQ_U64(&t, dfi_terrain_set_by(&none), DFI_TERRAIN_NONE);
            DF_CHECK_EQ_U64(&t, dfi_weather_set_by(NULL), DFI_WEATHER_NONE);
            DF_CHECK_EQ_U64(&t, dfi_terrain_set_by(NULL), DFI_TERRAIN_NONE);
            DF_CHECK(&t, dfi_ate_type_of(NULL, &dfi_pool_moves[DFI_MOVE_HYPERVOICE], type) == type);
            DF_CHECK(&t, !dfi_ate_boosts(NULL, DFI_TYPE_NORMAL, type));
            DF_CHECK(&t, !dfi_pinch_applies(NULL, type));
        }
        /* An id beyond the pool is no family (the invariant keeps it out of a state). */
        const dfi_member beyond = holder(DFI_POOL_ABILITY_COUNT, 1u, 300u);
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            DF_CHECK(&t, dfi_ate_type_of(&beyond, &dfi_pool_moves[DFI_MOVE_HYPERVOICE], type) == type);
            DF_CHECK(&t, !dfi_pinch_applies(&beyond, type));
        }
    }

    /* The gate: every -ate and pinch ability is marked supported since step P3, the setters since the
     * prefix. */
    for (size_t i = 0u; i < N_WEATHER_SETTERS; ++i) {
        DF_CHECK(&t, dfi_support.abilities[WEATHER_SETTERS[i].ability] != 0u);
    }
    for (size_t i = 0u; i < N_TERRAIN_SETTERS; ++i) {
        DF_CHECK(&t, dfi_support.abilities[TERRAIN_SETTERS[i].ability] != 0u);
    }
    for (size_t i = 0u; i < N_ATES; ++i) {
        DF_CHECK(&t, dfi_support.abilities[ATES[i].ability] != 0u);
    }
    for (size_t i = 0u; i < N_PINCHES; ++i) {
        DF_CHECK(&t, dfi_support.abilities[PINCHES[i].ability] != 0u);
    }
    return df_test_end(&t);
}
