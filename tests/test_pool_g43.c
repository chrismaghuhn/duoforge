/*
 * duoforge.state.pool_g43 (white-box): step G43 (Mega batch 3), ten Mega Stones marked with no new rule: Dragoninite (Multiscale),
 * Glimmoranite (Adaptability), Blazikenite (Speed Boost), Absolite Z (Sharpness), Raichunite X (Electric Surge), Lopunnite
 * (Scrappy), Alakazite (Trace), Meowsticite (Trace, both Meowstic formes), Scizorite (Technician) and Galladite (Inner Focus).
 *
 * The recorded battles (g43_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the reference's
 * draws. Here are the facts that they do not show:
 *
 *   - the marks: each stone is a marked item with the handler NONE (mark only, no callback of its own), and each Mega ability
 *     and each base ability of the eleven pairs is marked and legal for its base forme;
 *   - the Mega of each (base forme, stone) pair: dfi_mega_of, the Mega forme's ability, and the support of the pair (the
 *     support of the Mega ability, 5p); Meowsticite gives one pair per Meowstic forme, and no other pair;
 *   - the setup with the stone is accepted (dfi_closure_member_setup_valid and init), the member is Mega capable, evolves into
 *     exactly that forme with that ability, and the public API (duoforge_data_mega_count and _at) reports the pair as supported.
 *
 * Un-marking any of the ten stones (or of a Mega or base ability) fails check_marks, check_pairs and check_setups.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

struct g43_pair {
    uint32_t base;       /* the base forme */
    uint32_t item;       /* the stone (its item id) */
    uint32_t mega;       /* the Mega forme that the stone gives */
    uint32_t ability;    /* the Mega forme's ability */
    uint32_t base_ability; /* the base forme's ability that the recorded battle uses */
};

static const struct g43_pair pairs[] = {
    {DFI_FORME_DRAGONITE, DFI_ITEM_DRAGONINITE, DFI_FORME_DRAGONITEMEGA, DFI_ABILITY_MULTISCALE, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_GLIMMORA, DFI_ITEM_GLIMMORANITE, DFI_FORME_GLIMMORAMEGA, DFI_ABILITY_ADAPTABILITY, DFI_ABILITY_TOXICDEBRIS},
    {DFI_FORME_BLAZIKEN, DFI_ITEM_BLAZIKENITE, DFI_FORME_BLAZIKENMEGA, DFI_ABILITY_SPEEDBOOST, DFI_ABILITY_SPEEDBOOST},
    {DFI_FORME_ABSOL, DFI_ITEM_ABSOLITEZ, DFI_FORME_ABSOLMEGAZ, DFI_ABILITY_SHARPNESS, DFI_ABILITY_JUSTIFIED},
    {DFI_FORME_RAICHU, DFI_ITEM_RAICHUNITEX, DFI_FORME_RAICHUMEGAX, DFI_ABILITY_ELECTRICSURGE, DFI_ABILITY_LIGHTNINGROD},
    {DFI_FORME_LOPUNNY, DFI_ITEM_LOPUNNITE, DFI_FORME_LOPUNNYMEGA, DFI_ABILITY_SCRAPPY, DFI_ABILITY_LIMBER},
    {DFI_FORME_ALAKAZAM, DFI_ITEM_ALAKAZITE, DFI_FORME_ALAKAZAMMEGA, DFI_ABILITY_TRACE, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_MEOWSTIC, DFI_ITEM_MEOWSTICITE, DFI_FORME_MEOWSTICMMEGA, DFI_ABILITY_TRACE, DFI_ABILITY_PRANKSTER},
    {DFI_FORME_MEOWSTICF, DFI_ITEM_MEOWSTICITE, DFI_FORME_MEOWSTICFMEGA, DFI_ABILITY_TRACE, DFI_ABILITY_COMPETITIVE},
    {DFI_FORME_SCIZOR, DFI_ITEM_SCIZORITE, DFI_FORME_SCIZORMEGA, DFI_ABILITY_TECHNICIAN, DFI_ABILITY_TECHNICIAN},
    {DFI_FORME_GALLADE, DFI_ITEM_GALLADITE, DFI_FORME_GALLADEMEGA, DFI_ABILITY_INNERFOCUS, DFI_ABILITY_SHARPNESS},
};

#define G43_PAIRS (sizeof pairs / sizeof pairs[0])
#define G43_STONES 10u

static bool base_ability_legal(uint32_t base, uint32_t ability)
{
    const dfi_forme_legal *l = &dfi_pool_forme_legal[base];
    for (uint32_t k = 0u; k < l->ability_count; ++k) {
        if (l->abilities[k] == ability) {
            return true;
        }
    }
    return false;
}

/* The ten stones are marked items with no handler of their own; the Mega and base abilities are marked. */
static void check_marks(df_test *t)
{
    static const uint32_t stones[G43_STONES] = {DFI_ITEM_DRAGONINITE, DFI_ITEM_GLIMMORANITE, DFI_ITEM_BLAZIKENITE,
                                                DFI_ITEM_ABSOLITEZ,   DFI_ITEM_RAICHUNITEX,  DFI_ITEM_LOPUNNITE,
                                                DFI_ITEM_ALAKAZITE,   DFI_ITEM_MEOWSTICITE,  DFI_ITEM_SCIZORITE,
                                                DFI_ITEM_GALLADITE};
    for (uint32_t i = 0u; i < G43_STONES; ++i) {
        DF_CHECK(t, dfi_support.items[stones[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[stones[i]], DFI_HANDLER_NONE);
    }
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &pairs[i];
        DF_CHECK(t, dfi_support.items[p->item] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->ability] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->base_ability] != 0u);
        DF_CHECK(t, base_ability_legal(p->base, p->base_ability));
    }
    /* the Mega formes' single ability is the one of the pair (the pool row), and Trace is the ability of three of them */
    uint32_t trace = 0u;
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        DF_CHECK_EQ_U64(t, dfi_pool_formes[pairs[i].mega].ability, pairs[i].ability);
        trace += pairs[i].ability == DFI_ABILITY_TRACE ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, trace, 3u);
}

/* Each pair: the Mega of the (base forme, stone) pair, its ability, the support of the pair, and no other Mega for the stone. */
static void check_pairs(df_test *t)
{
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &pairs[i];
        DF_CHECK_EQ_U64(t, dfi_mega_of(p->base, 1u + p->item), p->mega);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, p->base, 1u + p->item));
    }
    /* a stone of another forme gives nothing here: Galladite on Scizor, Glimmoranite on Blaziken */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SCIZOR, 1u + DFI_ITEM_GALLADITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_BLAZIKEN, 1u + DFI_ITEM_GLIMMORANITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEOWSTIC, 1u + DFI_ITEM_MEOWSTICITE), DFI_FORME_MEOWSTICMMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEOWSTICF, 1u + DFI_ITEM_MEOWSTICITE), DFI_FORME_MEOWSTICFMEGA);
}

/* A legal member of the base forme holding the stone (the first legal move, ability and gender, as mega_by_stone builds it). */
static bool build_setup(const dfi_kind_limits *lim, uint32_t species, uint32_t item, duoforge_member_setup *out)
{
    duoforge_member_setup m;
    memset(&m, 0, sizeof m);
    m.species_id = species;
    m.nature = 0u;
    m.item = (uint8_t)item;
    m.stat_points[0] = 2u;
    m.stat_points[1] = 32u;
    m.stat_points[5] = 32u;
    for (uint32_t move = 0u; move < lim->move_count; ++move) {
        if (dfi_forme_move_legal(lim, species, move)) {
            m.move_count = 1u;
            m.moves[0].move_id = (uint16_t)move;
            break;
        }
    }
    for (uint32_t a = 1u; a <= lim->ability_count; ++a) {
        if (dfi_forme_ability_legal(lim, species, a)) {
            m.ability = (uint8_t)a;
            break;
        }
    }
    for (uint32_t g = DUOFORGE_GENDER_MALE; g <= DUOFORGE_GENDER_NONE; ++g) {
        m.gender = (uint8_t)g;
        if (dfi_closure_member_setup_valid(lim, &m)) {
            *out = m;
            return true;
        }
    }
    return false;
}

/* The setup with each stone is accepted, the member is Mega capable and evolves into the pair's forme with its ability. */
static void check_setups(df_test *t)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &pairs[i];
        duoforge_member_setup setup;
        dfi_member m;
        memset(&m, 0, sizeof m);
        if (!DF_CHECK(t, build_setup(&lim, p->base, 1u + p->item, &setup))) {
            continue;
        }
        if (!DF_CHECK(t, dfi_closure_member_init(&setup, &m))) {
            continue;
        }
        DF_CHECK(t, m.mega_capable == 1u && m.is_mega == 0u);
        DF_CHECK(t, dfi_closure_member_mega_evolve(&m));
        DF_CHECK(t, m.is_mega == 1u && m.item == 1u + p->item);
        DF_CHECK_EQ_U64(t, m.ability, 1u + p->ability);
        DF_CHECK(t, !dfi_closure_member_mega_evolve(&m)); /* once only */
    }
}

/* The public API: every pair is reached from its base forme with its stone, and reports the Mega and its support. */
static void check_api(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (!DF_CHECK(t, ctx != NULL)) {
        return;
    }
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &pairs[i];
        uint32_t n = 0u;
        if (!DF_CHECK(t, duoforge_data_mega_count(ctx, p->base, &n) == DUOFORGE_OK)) {
            continue;
        }
        uint32_t found = 0u;
        for (uint32_t k = 0u; k < n; ++k) {
            duoforge_mega_info mi;
            if (!DF_CHECK(t, duoforge_data_mega_at(ctx, p->base, k, &mi) == DUOFORGE_OK)) {
                continue;
            }
            if (mi.stone != p->item) {
                continue;
            }
            found += 1u;
            DF_CHECK_EQ_U64(t, mi.mega_species, p->mega);
            DF_CHECK_EQ_U64(t, mi.mega_ability, p->ability);
            DF_CHECK_EQ_U64(t, mi.supported, 1u);
        }
        DF_CHECK_EQ_U64(t, found, 1u);
    }
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g43");
    check_marks(&t);
    check_pairs(&t);
    check_setups(&t);
    check_api(&t);
    return df_test_end(&t);
}
