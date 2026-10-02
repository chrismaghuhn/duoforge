/*
 * duoforge.combat.item_family (white-box): the item families of decision 0015
 * as the battle reads them (src/combat/item_family.h). The type booster and
 * the resist berry decide from the family column and its type, and from
 * nothing else; here every item of the pool is run against every type, and
 * against the three kinds of hit (resisted, neutral, super effective), and
 * the answer is compared with a table written down below from the pinned
 * handlers (data/items.ts: the type of each booster's onBasePower and of each
 * berry's onSourceModifyDamage), not read from the column.
 *
 * What the families do to the damage is checked by the recorded battles
 * (duoforge.reference.conformance_pool_data and the closure and Team C ones
 * that hold Mystic Water, Miracle Seed and Chople Berry).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/item_family.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "support/check.h"

typedef struct item_type {
    uint32_t item; /* DFI_ITEM_* */
    uint32_t type; /* DFI_TYPE_* of the booster's move or of the berry's hit */
} item_type;

/* TYPE_BOOSTER: BasePower x4915/4096 for a move of the type. */
static const item_type BOOSTERS[] = {
    {DFI_ITEM_MYSTICWATER, DFI_TYPE_WATER},   {DFI_ITEM_MIRACLESEED, DFI_TYPE_GRASS},
    {DFI_ITEM_BLACKBELT, DFI_TYPE_FIGHTING},  {DFI_ITEM_BLACKGLASSES, DFI_TYPE_DARK},
    {DFI_ITEM_CHARCOAL, DFI_TYPE_FIRE},       {DFI_ITEM_DRAGONFANG, DFI_TYPE_DRAGON},
    {DFI_ITEM_FAIRYFEATHER, DFI_TYPE_FAIRY},  {DFI_ITEM_HARDSTONE, DFI_TYPE_ROCK},
    {DFI_ITEM_MAGNET, DFI_TYPE_ELECTRIC},     {DFI_ITEM_METALCOAT, DFI_TYPE_STEEL},
    {DFI_ITEM_NEVERMELTICE, DFI_TYPE_ICE},    {DFI_ITEM_POISONBARB, DFI_TYPE_POISON},
    {DFI_ITEM_SHARPBEAK, DFI_TYPE_FLYING},    {DFI_ITEM_SILKSCARF, DFI_TYPE_NORMAL},
    {DFI_ITEM_SILVERPOWDER, DFI_TYPE_BUG},    {DFI_ITEM_SOFTSAND, DFI_TYPE_GROUND},
    {DFI_ITEM_SPELLTAG, DFI_TYPE_GHOST},      {DFI_ITEM_TWISTEDSPOON, DFI_TYPE_PSYCHIC},
};

/* RESIST_BERRY: eaten by a super effective hit of the type (Chilan: by any Normal hit). */
static const item_type BERRIES[] = {
    {DFI_ITEM_CHOPLEBERRY, DFI_TYPE_FIGHTING}, {DFI_ITEM_BABIRIBERRY, DFI_TYPE_STEEL},
    {DFI_ITEM_CHARTIBERRY, DFI_TYPE_ROCK},     {DFI_ITEM_CHILANBERRY, DFI_TYPE_NORMAL},
    {DFI_ITEM_COBABERRY, DFI_TYPE_FLYING},     {DFI_ITEM_COLBURBERRY, DFI_TYPE_DARK},
    {DFI_ITEM_HABANBERRY, DFI_TYPE_DRAGON},    {DFI_ITEM_KASIBBERRY, DFI_TYPE_GHOST},
    {DFI_ITEM_KEBIABERRY, DFI_TYPE_POISON},    {DFI_ITEM_OCCABERRY, DFI_TYPE_FIRE},
    {DFI_ITEM_PASSHOBERRY, DFI_TYPE_WATER},    {DFI_ITEM_PAYAPABERRY, DFI_TYPE_PSYCHIC},
    {DFI_ITEM_RINDOBERRY, DFI_TYPE_GRASS},     {DFI_ITEM_ROSELIBERRY, DFI_TYPE_FAIRY},
    {DFI_ITEM_SHUCABERRY, DFI_TYPE_GROUND},    {DFI_ITEM_TANGABERRY, DFI_TYPE_BUG},
    {DFI_ITEM_WACANBERRY, DFI_TYPE_ELECTRIC},  {DFI_ITEM_YACHEBERRY, DFI_TYPE_ICE},
};

#define N_BOOSTERS (sizeof BOOSTERS / sizeof BOOSTERS[0])
#define N_BERRIES (sizeof BERRIES / sizeof BERRIES[0])

/* The type a table gives `item`, or DFI_CLOSURE_NONE when it is not in it. */
static uint32_t type_in(const item_type *table, size_t n, uint32_t item)
{
    for (size_t i = 0u; i < n; ++i) {
        if (table[i].item == item) {
            return table[i].type;
        }
    }
    return DFI_CLOSURE_NONE;
}

static dfi_member holder(uint32_t item)
{
    dfi_member m;
    memset(&m, 0, sizeof m);
    m.item = (uint8_t)(item + 1u); /* items are stored as 1 + id */
    return m;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.item_family");

    /* Eighteen of each, no item twice, and together exactly the items that have a family. */
    DF_CHECK_EQ_U64(&t, N_BOOSTERS, 18u);
    DF_CHECK_EQ_U64(&t, N_BERRIES, 18u);
    for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
        const bool booster = type_in(BOOSTERS, N_BOOSTERS, id) != DFI_CLOSURE_NONE;
        const bool berry = type_in(BERRIES, N_BERRIES, id) != DFI_CLOSURE_NONE;
        DF_CHECK(&t, !(booster && berry));
        DF_CHECK_EQ_U64(&t, dfi_pool_item_family[id].family != DFI_ITEM_FAMILY_NONE, booster || berry);
    }

    /* The modifiers: the pinned handlers' 4915/4096 and 0.5. */
    DF_CHECK_EQ_U64(&t, DFI_TYPE_BOOSTER_MODIFIER, 4915u);
    DF_CHECK_EQ_U64(&t, DFI_RESIST_BERRY_MODIFIER, 2048u);

    uint32_t booster_hits = 0u;
    uint32_t berry_hits = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
        const uint32_t booster_type = type_in(BOOSTERS, N_BOOSTERS, id);
        const uint32_t berry_type = type_in(BERRIES, N_BERRIES, id);
        dfi_member m = holder(id);
        /* Every move type, the typeless hit of Struggle (DFI_TYPE_COUNT) and a value beyond it included. */
        for (uint32_t type = 0u; type <= DFI_TYPE_COUNT + 1u; ++type) {
            const bool want_booster = booster_type == type;
            if (!DF_CHECK(&t, dfi_type_booster_applies(&m, type) == want_booster)) {
                fprintf(stderr, "  booster: item %u, type %u: expected %d\n", (unsigned)id, (unsigned)type,
                        (int)want_booster);
            }
            booster_hits += want_booster ? 1u : 0u;
            for (uint32_t mod = 0u; mod <= DFI_BIAS6_MAX; ++mod) {
                /* A berry weakens a super effective hit of its type; Chilan's type alone. */
                const bool want_berry = berry_type == type && (mod > DFI_BIAS6 || berry_type == DFI_TYPE_NORMAL);
                if (!DF_CHECK(&t, dfi_resist_berry_applies(&m, type, mod) == want_berry)) {
                    fprintf(stderr, "  berry: item %u, type %u, mod %u: expected %d\n", (unsigned)id,
                            (unsigned)type, (unsigned)mod, (int)want_berry);
                }
                berry_hits += want_berry ? 1u : 0u;
            }
        }
        /* A used-up item is not held, whatever it was. */
        m.item_consumed = 1u;
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            DF_CHECK(&t, !dfi_type_booster_applies(&m, type));
            DF_CHECK(&t, !dfi_resist_berry_applies(&m, type, DFI_BIAS6 + 2u));
        }
    }
    /* Each booster fires for its one type, each berry for its one type at each of the six super effective mods;
     * Chilan fires at all thirteen mods. */
    DF_CHECK_EQ_U64(&t, booster_hits, N_BOOSTERS);
    DF_CHECK_EQ_U64(&t, berry_hits, (N_BERRIES - 1u) * (DFI_BIAS6_MAX - DFI_BIAS6) + (DFI_BIAS6_MAX + 1u));

    /* No item at all, and a holder that is not there. */
    {
        dfi_member none = holder(0u);
        none.item = 0u;
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            DF_CHECK(&t, !dfi_type_booster_applies(&none, type));
            DF_CHECK(&t, !dfi_resist_berry_applies(&none, type, DFI_BIAS6 + 2u));
            DF_CHECK(&t, !dfi_type_booster_applies(NULL, type));
            DF_CHECK(&t, !dfi_resist_berry_applies(NULL, type, DFI_BIAS6 + 2u));
        }
        /* An id beyond the pool is no family (the invariant keeps it out of a state). */
        dfi_member beyond = holder(DFI_POOL_ITEM_COUNT);
        for (uint32_t type = 0u; type < DFI_TYPE_COUNT; ++type) {
            DF_CHECK(&t, !dfi_type_booster_applies(&beyond, type));
            DF_CHECK(&t, !dfi_resist_berry_applies(&beyond, type, DFI_BIAS6 + 2u));
        }
    }

    /* Focus Sash (data/items.ts:2275-2282): at full HP, a hit of at least its HP; not below full HP, not for
     * a smaller hit, not once used up, not for another item, not for a missing holder. */
    {
        dfi_member m = holder(DFI_ITEM_FOCUSSASH);
        m.hp = 150u;
        m.hp_max = 150u;
        DF_CHECK(&t, dfi_focus_sash_saves(&m, 150u));
        DF_CHECK(&t, dfi_focus_sash_saves(&m, 151u));
        DF_CHECK(&t, dfi_focus_sash_saves(&m, 4000u));
        DF_CHECK(&t, !dfi_focus_sash_saves(&m, 149u));
        DF_CHECK(&t, !dfi_focus_sash_saves(&m, 1u));
        m.hp = 149u;
        DF_CHECK(&t, !dfi_focus_sash_saves(&m, 4000u));
        m.hp = 150u;
        m.item_consumed = 1u;
        DF_CHECK(&t, !dfi_focus_sash_saves(&m, 4000u));
        m.item_consumed = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
            if (id != DFI_ITEM_FOCUSSASH) {
                m.item = (uint8_t)(id + 1u);
                DF_CHECK(&t, !dfi_focus_sash_saves(&m, 4000u));
            }
        }
        m.item = 0u;
        DF_CHECK(&t, !dfi_focus_sash_saves(&m, 4000u));
        DF_CHECK(&t, !dfi_focus_sash_saves(NULL, 4000u));
    }

    /* The gate: every booster and berry is marked supported since step P2, no other new id is an item. */
    for (size_t i = 0u; i < N_BOOSTERS; ++i) {
        DF_CHECK(&t, dfi_support.items[BOOSTERS[i].item] != 0u);
    }
    for (size_t i = 0u; i < N_BERRIES; ++i) {
        DF_CHECK(&t, dfi_support.items[BERRIES[i].item] != 0u);
    }
    return df_test_end(&t);
}
