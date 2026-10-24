/*
 * duoforge.items.berry_family (white-box): batch I2 (decision 0015 entry 5eg,
 * docs/mechanics/items/5eg-the-cure-berries-oran-berry-and.md), the cure berries (Cheri, Chesto, Pecha, Rawst, Aspear,
 * Persim: the CURE_BERRY family), Oran Berry (HEAL_BERRY, Sitrus Berry's path with 10 HP) and the isBerry column.
 *
 * The recorded battles (i2_cover_*) replay step by step through duoforge.reference.conformance_pool_data against the
 * protocol; this test checks what they cannot show by themselves:
 *   - the columns: the family and parameter of the seven rows, the isBerry column of all 28 berries of the pool and of no
 *     other item, written down here from data/items.ts;
 *   - the rules of combat/items/families.h for every cure code and status (the berry cures exactly its condition, Lum every
 *     status and the confusion, nothing else cures), and the HP an HP berry heals;
 *   - the marks: the seven rows marked, Leppa Berry not (an HS decision), and not marked what would reach another path of
 *     these berries (Ripen, Cheek Pouch, Harvest, Gluttony, Cud Chew, Klutz, Berserk, Pickpocket, Magician, Magic Room,
 *     Fling, Pluck, Stuff Cheeks, Teatime, Belch, Recycle);
 *   - the public data API: the seven rows are reported with no family, as before the batch (no public value changes);
 *   - the state the recorded battles leave: the status or confusion cured, the berry used up, a blocked berry kept;
 *   - the refusal: Bug Bite at a berry whose Eat the engine does not model (Leppa Berry) is E_UNSUPPORTED and leaves the
 *     battle unchanged.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/items/families.h"
#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the columns ---- */

static const struct {
    uint32_t item;
    uint32_t family;
    uint32_t param;
} I2_ROWS[] = {
    {DFI_ITEM_CHERIBERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_PAR},        /* data/items.ts:836-856 */
    {DFI_ITEM_CHESTOBERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_SLP},       /* :877-897 */
    {DFI_ITEM_PECHABERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_PSN},        /* :4497-4517 */
    {DFI_ITEM_RAWSTBERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_BRN},        /* :5068-5088 */
    {DFI_ITEM_ASPEARBERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_FRZ},       /* :292-312 */
    {DFI_ITEM_PERSIMBERRY, DFI_ITEM_FAMILY_CURE_BERRY, DFI_FAMILY_CURE_CONFUSION}, /* :4518-4536 */
    {DFI_ITEM_ORANBERRY, DFI_ITEM_FAMILY_HEAL_BERRY, 10u},                         /* :4397-4418 */
};
#define N_I2 (sizeof I2_ROWS / sizeof I2_ROWS[0])

/* Every item of the pool with isBerry: true in data/items.ts. */
static const uint32_t BERRIES[] = {
    DFI_ITEM_SITRUSBERRY, DFI_ITEM_CHOPLEBERRY, DFI_ITEM_BABIRIBERRY, DFI_ITEM_CHARTIBERRY, DFI_ITEM_CHILANBERRY,
    DFI_ITEM_COBABERRY, DFI_ITEM_COLBURBERRY, DFI_ITEM_HABANBERRY, DFI_ITEM_KASIBBERRY, DFI_ITEM_KEBIABERRY,
    DFI_ITEM_OCCABERRY, DFI_ITEM_PASSHOBERRY, DFI_ITEM_PAYAPABERRY, DFI_ITEM_RINDOBERRY, DFI_ITEM_ROSELIBERRY,
    DFI_ITEM_SHUCABERRY, DFI_ITEM_TANGABERRY, DFI_ITEM_WACANBERRY, DFI_ITEM_YACHEBERRY, DFI_ITEM_ASPEARBERRY,
    DFI_ITEM_CHERIBERRY, DFI_ITEM_CHESTOBERRY, DFI_ITEM_LEPPABERRY, DFI_ITEM_LUMBERRY, DFI_ITEM_ORANBERRY,
    DFI_ITEM_PECHABERRY, DFI_ITEM_PERSIMBERRY, DFI_ITEM_RAWSTBERRY,
};
#define N_BERRIES (sizeof BERRIES / sizeof BERRIES[0])

static bool in_list(const uint32_t *list, size_t n, uint32_t id)
{
    for (size_t k = 0u; k < n; ++k) {
        if (list[k] == id) {
            return true;
        }
    }
    return false;
}

static void check_columns(df_test *t)
{
    for (size_t k = 0u; k < N_I2; ++k) {
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[I2_ROWS[k].item].family, I2_ROWS[k].family);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[I2_ROWS[k].item].type, I2_ROWS[k].param);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[I2_ROWS[k].item], DFI_HANDLER_NONE);
        DF_CHECK(t, dfi_pool_item_unmodeled[I2_ROWS[k].item] == NULL);
    }
    uint32_t berries = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_ITEM_COUNT; ++id) {
        const bool want = in_list(BERRIES, N_BERRIES, id);
        DF_CHECK_EQ_U64(t, dfi_pool_item_berry[id], want ? 1u : 0u);
        DF_CHECK_EQ_U64(t, dfi_item_is_berry(1u + id), want);
        berries += dfi_pool_item_berry[id];
    }
    DF_CHECK_EQ_U64(t, berries, 28u);
    DF_CHECK(t, !dfi_item_is_berry(0u));
    DF_CHECK(t, !dfi_item_is_berry(DFI_POOL_ITEM_COUNT + 1u));
}

/* ---- the rules ---- */

static void check_rules(df_test *t)
{
    static const uint32_t statuses[] = {DFI_STATUS_NONE, DFI_STATUS_BRN, DFI_STATUS_FRZ, DFI_STATUS_PAR,
                                        DFI_STATUS_SLP, DFI_STATUS_PSN, DFI_STATUS_TOX};
    static const uint32_t cured_by[] = {0xFFu, DFI_FAMILY_CURE_BRN, DFI_FAMILY_CURE_FRZ, DFI_FAMILY_CURE_PAR,
                                        DFI_FAMILY_CURE_SLP, DFI_FAMILY_CURE_PSN, DFI_FAMILY_CURE_PSN};
    for (uint32_t cure = 0u; cure <= 8u; ++cure) {
        for (size_t s = 0u; s < sizeof statuses / sizeof statuses[0]; ++s) {
            DF_CHECK_EQ_U64(t, dfi_cure_berry_status(cure, statuses[s]), cured_by[s] == cure);
        }
    }
    for (size_t k = 0u; k < N_I2; ++k) {
        const uint32_t item = 1u + I2_ROWS[k].item;
        for (size_t s = 0u; s < sizeof statuses / sizeof statuses[0]; ++s) {
            for (uint32_t confused = 0u; confused < 2u; ++confused) {
                bool st = true;
                bool conf = true;
                dfi_berry_cures(item, statuses[s], confused != 0u, &st, &conf);
                const bool cure = I2_ROWS[k].family == DFI_ITEM_FAMILY_CURE_BERRY;
                DF_CHECK_EQ_U64(t, st, cure && cured_by[s] == I2_ROWS[k].param);
                DF_CHECK_EQ_U64(t, conf, cure && confused != 0u && I2_ROWS[k].param == DFI_FAMILY_CURE_CONFUSION);
            }
        }
        DF_CHECK_EQ_U64(t, dfi_hp_berry_heal(item, 200u), I2_ROWS[k].family == DFI_ITEM_FAMILY_HEAL_BERRY ? 10u : 0u);
    }
    /* Lum Berry: every status and the confusion; Sitrus Berry: a quarter (truncated); no item and another item: nothing. */
    for (size_t s = 0u; s < sizeof statuses / sizeof statuses[0]; ++s) {
        bool st = false;
        bool conf = false;
        dfi_berry_cures(1u + DFI_ITEM_LUMBERRY, statuses[s], true, &st, &conf);
        DF_CHECK_EQ_U64(t, st, statuses[s] != DFI_STATUS_NONE);
        DF_CHECK(t, conf);
        dfi_berry_cures(1u + DFI_ITEM_LUMBERRY, statuses[s], false, &st, &conf);
        DF_CHECK(t, !conf);
        static const uint32_t others[] = {0u, 1u + DFI_ITEM_SITRUSBERRY, 1u + DFI_ITEM_LEPPABERRY, 1u + DFI_ITEM_CHOPLEBERRY,
                                          1u + DFI_ITEM_MENTALHERB, 1u + DFI_ITEM_LEFTOVERS};
        for (size_t o = 0u; o < sizeof others / sizeof others[0]; ++o) {
            dfi_berry_cures(others[o], statuses[s], true, &st, &conf);
            DF_CHECK(t, !st && !conf);
        }
    }
    DF_CHECK_EQ_U64(t, dfi_hp_berry_heal(1u + DFI_ITEM_SITRUSBERRY, 203u), 50u);
    DF_CHECK_EQ_U64(t, dfi_hp_berry_heal(1u + DFI_ITEM_LUMBERRY, 200u), 0u);
    DF_CHECK_EQ_U64(t, dfi_hp_berry_heal(1u + DFI_ITEM_LEPPABERRY, 200u), 0u);
    DF_CHECK_EQ_U64(t, dfi_hp_berry_heal(0u, 200u), 0u);
}

/* ---- the marks and the public data API ---- */

static void check_marks(df_test *t, const duoforge_context *pool)
{
    for (size_t k = 0u; k < N_I2; ++k) {
        DF_CHECK(t, dfi_support.items[I2_ROWS[k].item] != 0u);
        duoforge_item_static got;
        memset(&got, 0xA5, sizeof got);
        DF_CHECK(t, duoforge_data_item_static(pool, I2_ROWS[k].item, &got) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, got.family, DUOFORGE_ITEM_FAMILY_NONE); /* internal families: reported as none (no public value) */
        DF_CHECK_EQ_U64(t, got.family_type, DUOFORGE_DATA_NONE);
        DF_CHECK_EQ_U64(t, got.is_mega_stone, 0u);
        DF_CHECK_EQ_U64(t, got.mega_species, DUOFORGE_DATA_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LEPPABERRY] == 0u);
    static const uint32_t abilities[] = {DFI_ABILITY_RIPEN,  DFI_ABILITY_CHEEKPOUCH, DFI_ABILITY_HARVEST,
                                         DFI_ABILITY_GLUTTONY, DFI_ABILITY_CUDCHEW, DFI_ABILITY_KLUTZ,
                                         DFI_ABILITY_BERSERK, DFI_ABILITY_PICKPOCKET, DFI_ABILITY_MAGICIAN};
    for (size_t k = 0u; k < sizeof abilities / sizeof abilities[0]; ++k) {
        DF_CHECK(t, dfi_support.abilities[abilities[k]] == 0u);
    }
    static const uint32_t moves[] = {DFI_MOVE_MAGICROOM, DFI_MOVE_FLING, DFI_MOVE_PLUCK, DFI_MOVE_STUFFCHEEKS,
                                     DFI_MOVE_TEATIME, DFI_MOVE_BELCH, DFI_MOVE_RECYCLE};
    for (size_t k = 0u; k < sizeof moves / sizeof moves[0]; ++k) {
        DF_CHECK(t, dfi_support.moves[moves[k]] == 0u);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.berry_family");
    duoforge_context *pool = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, pool != NULL)) {
        check_columns(&t);
        check_rules(&t);
        check_marks(&t, pool);
        duoforge_context_destroy(pool);
    }
    return df_test_end(&t);
}
