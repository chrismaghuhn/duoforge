/*
 * duoforge.forms.mega_stones (white-box): the Mega Stones and the Megas they lead to, one section per batch of the content
 * expansion. Each section checks its batch's stones as one set: the stone is a marked item (handler NONE), it takes its base
 * forme to its Mega (dfi_mega_of, the support of the pair in the manifest), and, where the batch says so, the Mega and base
 * abilities are marked and legal, the setup with the stone is accepted and evolves once into that forme, and the public API
 * reports the pair as supported. The behaviour of the Megas is in the recorded battles of each batch (conformance_pool_data)
 * and in the abilities' own tests.
 *
 * The sections, from the tests of their steps (restructure step 6e; tests/renames.tsv maps the old names): Mega batch 2
 * (Swampertite, Metagrossite, Froslassite, Lucarionite Z), Mega batch 3 (G43: ten stones with no new rule), Mega batch 4 (G51:
 * ten stones with no new rule, and Keen Eye and Big Pecks marked for Pidgeot), the Magic Bounce stones (G57: Absolite,
 * Sablenite, Clefablite; Sharpedonite unmarked), the six new Mega abilities and their stones (G59), the simple Mega abilities'
 * stones (G63), the cheap set's stones (G75: Medichamite and Clefablite; Sharpedonite unmarked) and Starminite (batch I1,
 * decision 0015 entry 5ef: Starmie-Mega's Huge Power and the base forme's Illuminate and Natural Cure are marked).
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/damage_chain.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/formulas.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "reference/reflect_ref.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define G43_PAIRS (sizeof stones_batch3_pairs / sizeof stones_batch3_pairs[0])
#define G43_STONES 10u
#define G51_PAIRS (sizeof stones_batch4_pairs / sizeof stones_batch4_pairs[0])
#define G51_STONES 10u

static void stones_batch2_check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_AURAGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_AURAGUARD], DFI_HANDLER_NONE); /* an engine row: read by id */
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_AURAGUARD].family, DFI_ABILITY_FAMILY_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SWAMPERTITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_METAGROSSITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LUCARIONITEZ] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_FROSLASSITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_FROSLASSITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_SWAMPERTITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_METAGROSSITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LUCARIONITEZ], DFI_HANDLER_NONE);

    /* the Mega of each pair, its ability, and the support of the pair (the Mega ability is marked) */
    static const struct {
        uint32_t base, item, mega, ability;
    } pairs[] = {
        {DFI_FORME_SWAMPERT, DFI_ITEM_SWAMPERTITE, DFI_FORME_SWAMPERTMEGA, DFI_ABILITY_SWIFTSWIM},
        {DFI_FORME_METAGROSS, DFI_ITEM_METAGROSSITE, DFI_FORME_METAGROSSMEGA, DFI_ABILITY_TOUGHCLAWS},
        {DFI_FORME_LUCARIO, DFI_ITEM_LUCARIONITEZ, DFI_FORME_LUCARIOMEGAZ, DFI_ABILITY_AURAGUARD},
        {DFI_FORME_FROSLASS, DFI_ITEM_FROSLASSITE, DFI_FORME_FROSLASSMEGA, DFI_ABILITY_SNOWWARNING},
    };
    for (size_t i = 0u; i < sizeof pairs / sizeof pairs[0]; ++i) {
        const uint32_t mega = dfi_mega_of(pairs[i].base, 1u + pairs[i].item);
        DF_CHECK_EQ_U64(t, mega, pairs[i].mega);
        DF_CHECK_EQ_U64(t, dfi_pool_formes[mega].ability, pairs[i].ability);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, pairs[i].base, 1u + pairs[i].item));
        DF_CHECK(t, dfi_support.abilities[pairs[i].ability] != 0u);
    }
    /* Lucario's other stone is another Mega (Adaptability), not Lucario-Mega-Z, and the Z stone is no stone of another forme */
    DF_CHECK(t, dfi_mega_of(DFI_FORME_LUCARIO, 1u + DFI_ITEM_LUCARIONITE) != DFI_FORME_LUCARIOMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_METAGROSS, 1u + DFI_ITEM_LUCARIONITEZ), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SWAMPERT, 1u + DFI_ITEM_METAGROSSITE), DFI_FORME_NONE);
    /* the base abilities that the four need are marked: Torrent, Clear Body, Inner Focus and Cursed Body (step G27) */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_TORRENT] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CLEARBODY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INNERFOCUS] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CURSEDBODY] != 0u);
    /* Aura Guard is the Mega ability of Lucario-Mega-Z alone among the pool's formes' abilities that are marked here */
    uint32_t holders = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        holders += dfi_pool_formes[forme].ability == DFI_ABILITY_AURAGUARD ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, holders, 1u);
}

struct g43_pair {
    uint32_t base;       /* the base forme */
    uint32_t item;       /* the stone (its item id) */
    uint32_t mega;       /* the Mega forme that the stone gives */
    uint32_t ability;    /* the Mega forme's ability */
    uint32_t base_ability; /* the base forme's ability that the recorded battle uses */
};

static const struct g43_pair stones_batch3_pairs[] = {
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
static void stones_batch3_check_marks(df_test *t)
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
        const struct g43_pair *p = &stones_batch3_pairs[i];
        DF_CHECK(t, dfi_support.items[p->item] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->ability] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->base_ability] != 0u);
        DF_CHECK(t, base_ability_legal(p->base, p->base_ability));
    }
    /* the Mega formes' single ability is the one of the pair (the pool row), and Trace is the ability of three of them */
    uint32_t trace = 0u;
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        DF_CHECK_EQ_U64(t, dfi_pool_formes[stones_batch3_pairs[i].mega].ability, stones_batch3_pairs[i].ability);
        trace += stones_batch3_pairs[i].ability == DFI_ABILITY_TRACE ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, trace, 3u);
}

/* Each pair: the Mega of the (base forme, stone) pair, its ability, the support of the pair, and no other Mega for the stone. */
static void stones_batch3_check_pairs(df_test *t)
{
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &stones_batch3_pairs[i];
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
static bool stones_batch3_build_setup(const dfi_kind_limits *lim, uint32_t species, uint32_t item, duoforge_member_setup *out)
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
static void stones_batch3_check_setups(df_test *t)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &stones_batch3_pairs[i];
        duoforge_member_setup setup;
        dfi_member m;
        memset(&m, 0, sizeof m);
        if (!DF_CHECK(t, stones_batch3_build_setup(&lim, p->base, 1u + p->item, &setup))) {
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
static void stones_batch3_check_api(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (!DF_CHECK(t, ctx != NULL)) {
        return;
    }
    for (size_t i = 0u; i < G43_PAIRS; ++i) {
        const struct g43_pair *p = &stones_batch3_pairs[i];
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

struct g51_pair {
    uint32_t base;         /* the base forme */
    uint32_t item;         /* the stone (its item id) */
    uint32_t mega;         /* the Mega forme that the stone gives */
    uint32_t ability;      /* the Mega forme's ability */
    uint32_t base_ability; /* the base forme's ability that the recorded battle uses */
};

static const struct g51_pair stones_batch4_pairs[] = {
    {DFI_FORME_CHANDELURE, DFI_ITEM_CHANDELURITE, DFI_FORME_CHANDELUREMEGA, DFI_ABILITY_INFILTRATOR, DFI_ABILITY_FLASHFIRE},
    {DFI_FORME_HOUNDOOM, DFI_ITEM_HOUNDOOMINITE, DFI_FORME_HOUNDOOMMEGA, DFI_ABILITY_SOLARPOWER, DFI_ABILITY_FLASHFIRE},
    {DFI_FORME_LUCARIO, DFI_ITEM_LUCARIONITE, DFI_FORME_LUCARIOMEGA, DFI_ABILITY_ADAPTABILITY, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_DRAGALGE, DFI_ITEM_DRAGALGITE, DFI_FORME_DRAGALGEMEGA, DFI_ABILITY_REGENERATOR, DFI_ABILITY_ADAPTABILITY},
    {DFI_FORME_CRABOMINABLE, DFI_ITEM_CRABOMINITE, DFI_FORME_CRABOMINABLEMEGA, DFI_ABILITY_IRONFIST, DFI_ABILITY_HYPERCUTTER},
    {DFI_FORME_CHIMECHO, DFI_ITEM_CHIMECHITE, DFI_FORME_CHIMECHOMEGA, DFI_ABILITY_LEVITATE, DFI_ABILITY_LEVITATE},
    {DFI_FORME_GLALIE, DFI_ITEM_GLALITITE, DFI_FORME_GLALIEMEGA, DFI_ABILITY_REFRIGERATE, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_PINSIR, DFI_ITEM_PINSIRITE, DFI_FORME_PINSIRMEGA, DFI_ABILITY_AERILATE, DFI_ABILITY_HYPERCUTTER},
    {DFI_FORME_BANETTE, DFI_ITEM_BANETTITE, DFI_FORME_BANETTEMEGA, DFI_ABILITY_PRANKSTER, DFI_ABILITY_CURSEDBODY},
    {DFI_FORME_PIDGEOT, DFI_ITEM_PIDGEOTITE, DFI_FORME_PIDGEOTMEGA, DFI_ABILITY_NOGUARD, DFI_ABILITY_KEENEYE},
};

/* The ten stones are marked items with no handler of their own; Keen Eye and Big Pecks are marked engine rows; the Mega and base
 * abilities are marked and legal for their formes. */
static void stones_batch4_check_marks(df_test *t)
{
    static const uint32_t stones[G51_STONES] = {DFI_ITEM_CHANDELURITE, DFI_ITEM_HOUNDOOMINITE, DFI_ITEM_LUCARIONITE,
                                                DFI_ITEM_DRAGALGITE,   DFI_ITEM_CRABOMINITE,   DFI_ITEM_CHIMECHITE,
                                                DFI_ITEM_GLALITITE,    DFI_ITEM_PINSIRITE,     DFI_ITEM_BANETTITE,
                                                DFI_ITEM_PIDGEOTITE};
    for (uint32_t i = 0u; i < G51_STONES; ++i) {
        DF_CHECK(t, dfi_support.items[stones[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[stones[i]], DFI_HANDLER_NONE);
    }
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &stones_batch4_pairs[i];
        DF_CHECK(t, dfi_support.items[p->item] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->ability] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->base_ability] != 0u);
        DF_CHECK(t, base_ability_legal(p->base, p->base_ability));
        DF_CHECK_EQ_U64(t, dfi_pool_formes[p->mega].ability, p->ability);
    }
    /* the two engine rows of this step: marked, read by id (handler NONE), and both legal for Pidgeot */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_KEENEYE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_BIGPECKS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_KEENEYE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_BIGPECKS], DFI_HANDLER_NONE);
    DF_CHECK(t, base_ability_legal(DFI_FORME_PIDGEOT, DFI_ABILITY_KEENEYE));
    DF_CHECK(t, base_ability_legal(DFI_FORME_PIDGEOT, DFI_ABILITY_BIGPECKS));
}

/* Each pair: the Mega of the (base forme, stone) pair and its support; Lucario's two stones give its two Mega formes. */
static void stones_batch4_check_pairs(df_test *t)
{
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &stones_batch4_pairs[i];
        DF_CHECK_EQ_U64(t, dfi_mega_of(p->base, 1u + p->item), p->mega);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, p->base, 1u + p->item));
    }
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_LUCARIO, 1u + DFI_ITEM_LUCARIONITEZ), DFI_FORME_LUCARIOMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_PIDGEOT, 1u + DFI_ITEM_CHANDELURITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CHIMECHO, 1u + DFI_ITEM_PIDGEOTITE), DFI_FORME_NONE);
}

/* A legal member of the base forme holding the stone (the first legal move, ability and gender, as mega_by_stone builds it). */
static bool stones_batch4_build_setup(const dfi_kind_limits *lim, uint32_t species, uint32_t item, uint32_t ability, duoforge_member_setup *out)
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
    m.ability = (uint8_t)ability;
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
static void stones_batch4_check_setups(df_test *t)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &stones_batch4_pairs[i];
        duoforge_member_setup setup;
        dfi_member m;
        memset(&m, 0, sizeof m);
        if (!DF_CHECK(t, stones_batch4_build_setup(&lim, p->base, 1u + p->item, 1u + p->base_ability, &setup))) {
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
static void stones_batch4_check_api(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (!DF_CHECK(t, ctx != NULL)) {
        return;
    }
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &stones_batch4_pairs[i];
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

/* Absolite and Sablenite are marked; Clefablite was unmarked by G57 (its Mega ability, Magic Bounce, passed the forme gate but its
 * base's abilities were not), and is marked since step G75 (Clefable's hidden Unaware, marked by G65). Starminite is marked since
 * batch I1 (Illuminate and Natural Cure, A2a); Sharpedonite stays unmarked, so an unmarked stone is still refused. Absol has two Mega pairs, and each stone takes it to
 * its own Mega (dfi_mega_of: the stone is 1 + its id, the base's own link first). */
static void test_mega_stones(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_ABSOLITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SABLENITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_CLEFABLITE] != 0u); /* marked since step G75 */
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SHARPEDONITE] == 0u); /* still unmarked: an unmarked stone is refused */
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STARMINITE] != 0u);   /* marked since batch I1 (decision 0015 entry 5ef) */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_ABSOL, DFI_ITEM_ABSOLITE + 1u), DFI_FORME_ABSOLMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_ABSOL, DFI_ITEM_ABSOLITEZ + 1u), DFI_FORME_ABSOLMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SABLEYE, DFI_ITEM_SABLENITE + 1u), DFI_FORME_SABLEYEMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_SABLEYE, DFI_ITEM_SABLENITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_ABSOL, DFI_ITEM_ABSOLITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_CLEFABLE, DFI_ITEM_CLEFABLITE + 1u));
}

/* ---- the marks, the Mega formes and the stones */
static void new_mega_abilities_check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_MEGALAUNCHER, DFI_ABILITY_HUGEPOWER, DFI_ABILITY_THICKFAT,
                                         DFI_ABILITY_FIREMANE, DFI_ABILITY_SPICYSPRAY, DFI_ABILITY_MEGASOL};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    static const uint32_t items[] = {DFI_ITEM_BLASTOISINITE, DFI_ITEM_MAWILITE, DFI_ITEM_VENUSAURITE, DFI_ITEM_PYROARITE,
                                     DFI_ITEM_SCOVILLAINITE, DFI_ITEM_MEGANIUMITE};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE); /* mark only */
    }

    /* the Mega of each stone's base forme, the Mega's ability, and the support of the pair (its base abilities are marked) */
    static const struct {
        uint32_t base, item, mega, ability, base_ability_a, base_ability_b;
    } pairs[] = {
        {DFI_FORME_BLASTOISE, DFI_ITEM_BLASTOISINITE, DFI_FORME_BLASTOISEMEGA, DFI_ABILITY_MEGALAUNCHER, DFI_ABILITY_TORRENT,
         DFI_ABILITY_RAINDISH},
        {DFI_FORME_MAWILE, DFI_ITEM_MAWILITE, DFI_FORME_MAWILEMEGA, DFI_ABILITY_HUGEPOWER, DFI_ABILITY_HYPERCUTTER,
         DFI_ABILITY_INTIMIDATE},
        {DFI_FORME_VENUSAUR, DFI_ITEM_VENUSAURITE, DFI_FORME_VENUSAURMEGA, DFI_ABILITY_THICKFAT, DFI_ABILITY_OVERGROW,
         DFI_ABILITY_CHLOROPHYLL},
        {DFI_FORME_PYROAR, DFI_ITEM_PYROARITE, DFI_FORME_PYROARMEGA, DFI_ABILITY_FIREMANE, DFI_ABILITY_UNNERVE,
         DFI_ABILITY_MOXIE},
        {DFI_FORME_SCOVILLAIN, DFI_ITEM_SCOVILLAINITE, DFI_FORME_SCOVILLAINMEGA, DFI_ABILITY_SPICYSPRAY, DFI_ABILITY_CHLOROPHYLL,
         DFI_ABILITY_CHLOROPHYLL},
        {DFI_FORME_MEGANIUM, DFI_ITEM_MEGANIUMITE, DFI_FORME_MEGANIUMMEGA, DFI_ABILITY_MEGASOL, DFI_ABILITY_OVERGROW,
         DFI_ABILITY_OVERGROW},    };
    for (size_t i = 0u; i < sizeof pairs / sizeof pairs[0]; ++i) {
        const uint32_t mega = dfi_mega_of(pairs[i].base, 1u + pairs[i].item);
        DF_CHECK_EQ_U64(t, mega, pairs[i].mega);
        DF_CHECK_EQ_U64(t, dfi_pool_formes[mega].ability, pairs[i].ability);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, pairs[i].base, 1u + pairs[i].item));
        DF_CHECK(t, dfi_support.abilities[pairs[i].base_ability_a] != 0u);
        DF_CHECK(t, dfi_support.abilities[pairs[i].base_ability_b] != 0u);
    }
    /* the Mega Stones are the stones of their own formes only */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEGANIUM, 1u + DFI_ITEM_VENUSAURITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_VENUSAUR, 1u + DFI_ITEM_MEGANIUMITE), DFI_FORME_NONE);

    /* what stays unmarked: Mold Breaker (no breakable ability of the step is ignored), and the Mega formes of the other stones */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

/* The six stones are marked, Heracronite is not, and each stone takes its base forme to its Mega (the manifest and the tables). */
static void test_mega_stones_g63(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_GARCHOMPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STEELIXITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SLOWBRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SCOLIPITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_AGGRONITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SKARMORITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_HERACRONITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u), DFI_FORME_GARCHOMPMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_STEELIX, DFI_ITEM_STEELIXITE + 1u), DFI_FORME_STEELIXMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SLOWBRO, DFI_ITEM_SLOWBRONITE + 1u), DFI_FORME_SLOWBROMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SCOLIPEDE, DFI_ITEM_SCOLIPITE + 1u), DFI_FORME_SCOLIPEDEMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_AGGRON, DFI_ITEM_AGGRONITE + 1u), DFI_FORME_AGGRONMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u), DFI_FORME_SKARMORYMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_GARCHOMP, DFI_ITEM_GARCHOMPITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_SKARMORY, DFI_ITEM_SKARMORITE + 1u));
}

/* ---- the marks of the two stones, and the stones that stay out */
static void check_stones(df_test *t)
{
    static const uint32_t items[] = {DFI_ITEM_MEDICHAMITE, DFI_ITEM_CLEFABLITE};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE);
    }
    /* the stones that stay out, and Strong Jaw, whose bite flag would need a pool column (deferred, not in this batch) */
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STARMINITE] != 0u); /* marked since batch I1 (decision 0015 entry 5ef) */
    DF_CHECK(t, dfi_support.items[DFI_ITEM_ALTARIANITE] != 0u); /* marked since A0 part 1 (decision 0015 entry 5ds) */
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_SHARPEDONITE], 0u);
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_STRONGJAW], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_STRONGJAW], DFI_HANDLER_UNMODELED);
}

/* ---- the Mega pairs of the two stones, and the legal base abilities of their base formes */
static void cheap_set_stones_check_pairs(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEDICHAM, 1u + DFI_ITEM_MEDICHAMITE), DFI_FORME_MEDICHAMMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_MEDICHAM, 1u + DFI_ITEM_MEDICHAMITE));
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CLEFABLE, 1u + DFI_ITEM_CLEFABLITE), DFI_FORME_CLEFABLEMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_CLEFABLE, 1u + DFI_ITEM_CLEFABLITE));
    /* the base formes of the battles hold the ability of each pair */
    DF_CHECK(t, base_ability_legal(DFI_FORME_MEDICHAM, DFI_ABILITY_PUREPOWER));
    DF_CHECK(t, base_ability_legal(DFI_FORME_CLEFABLE, DFI_ABILITY_UNAWARE));
    /* a stone of another forme gives nothing: Medichamite on Clefable, Clefablite on Medicham */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CLEFABLE, 1u + DFI_ITEM_MEDICHAMITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEDICHAM, 1u + DFI_ITEM_CLEFABLITE), DFI_FORME_NONE);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.forms.mega_stones");
    { /* stones batch2 */
        stones_batch2_check_facts(&t);
    }
    { /* stones batch3 */
        stones_batch3_check_marks(&t);
        stones_batch3_check_pairs(&t);
        stones_batch3_check_setups(&t);
        stones_batch3_check_api(&t);
    }
    { /* stones batch4 */
        stones_batch4_check_marks(&t);
        stones_batch4_check_pairs(&t);
        stones_batch4_check_setups(&t);
        stones_batch4_check_api(&t);
    }
    { /* magic bounce stones */
        test_mega_stones(&t);
    }
    { /* new mega abilities */
        new_mega_abilities_check_facts(&t);
    }
    { /* simple mega abilities */
        test_mega_stones_g63(&t);
    }
    { /* cheap set stones */
        check_stones(&t);
        cheap_set_stones_check_pairs(&t);
    }
    return df_test_end(&t);
}
