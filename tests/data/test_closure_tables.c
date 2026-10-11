/*
 * T40 duoforge.data.closure_tables (white-box): the generated closure tables
 * and the Champions formulas. Expectations are independent of the generator's
 * C output: literal values read at the pinned reference (listed with their
 * source in docs/research/mechanics-inventory.md), the stat lines recomputed
 * by tools/research/verify_inventory.py, the M2 target-class table T1, and
 * the table hash recomputed in C from the canonical bytes.
 */
#include <stdio.h>
#include <string.h>

#include "core/sha256.h"
#include "data/closure_tables.h"
#include "data/formulas.h"
#include "support/check.h"
#include "support/fixtures.h"

#define TABLE_HASH_HEX "86ca9d9f548042473c0980c496e9bd6bebbde4b3df0ed10a9ba25aa62316ef5c"

typedef struct set_case {
    uint32_t forme;
    uint32_t nature;
    uint32_t sp[6];       /* Stat Points of the set in decision 0004 */
    uint32_t expected[6]; /* HP Atk Def SpA SpD Spe */
} set_case;

/* Sets of decision 0004; Mega formes use the Stat Points and nature of their
 * base forme. Expected lines: docs/research/mechanics-inventory.md section 1. */
static const set_case sets[] = {
    {DFI_FORME_RILLABOOM, DFI_NATURE_ADAMANT, {18, 32, 2, 0, 6, 8}, {193, 194, 112, 72, 96, 113}},
    {DFI_FORME_STARAPTOR, DFI_NATURE_JOLLY, {32, 0, 0, 0, 2, 32}, {192, 140, 90, 63, 82, 167}},
    {DFI_FORME_STARAPTORMEGA, DFI_NATURE_JOLLY, {32, 0, 0, 0, 2, 32}, {192, 160, 120, 72, 112, 178}},
    {DFI_FORME_MILOTIC, DFI_NATURE_CALM, {32, 0, 29, 0, 5, 0}, {202, 72, 128, 120, 165, 101}},
    {DFI_FORME_CERULEDGE, DFI_NATURE_ADAMANT, {31, 7, 24, 0, 3, 1}, {181, 167, 124, 72, 123, 106}},
    {DFI_FORME_RAICHU, DFI_NATURE_TIMID, {29, 0, 5, 0, 0, 32}, {164, 99, 80, 110, 100, 178}},
    {DFI_FORME_RAICHUMEGAY, DFI_NATURE_TIMID, {29, 0, 5, 0, 0, 32}, {164, 108, 80, 180, 100, 200}},
    {DFI_FORME_GHOLDENGO, DFI_NATURE_MODEST, {17, 0, 2, 17, 16, 14}, {179, 72, 117, 187, 127, 118}},
    {DFI_FORME_POLITOED, DFI_NATURE_MODEST, {32, 0, 0, 30, 0, 4}, {197, 85, 95, 154, 120, 94}},
    {DFI_FORME_GOLISOPOD, DFI_NATURE_ADAMANT, {32, 32, 0, 0, 1, 1}, {182, 194, 160, 72, 111, 61}},
    {DFI_FORME_GOLISOPODMEGA, DFI_NATURE_ADAMANT, {32, 32, 0, 0, 1, 1}, {182, 222, 195, 81, 141, 61}},
    {DFI_FORME_ARCHALUDON, DFI_NATURE_BOLD, {32, 0, 1, 0, 24, 9}, {197, 112, 166, 145, 109, 114}},
    {DFI_FORME_FARIGIRAF, DFI_NATURE_BOLD, {29, 0, 20, 0, 17, 0}, {224, 99, 121, 130, 107, 80}},
    {DFI_FORME_CHARIZARD, DFI_NATURE_TIMID, {16, 0, 18, 3, 0, 29}, {169, 93, 116, 132, 105, 163}},
    {DFI_FORME_CHARIZARDMEGAY, DFI_NATURE_TIMID, {16, 0, 18, 3, 0, 29}, {169, 111, 116, 182, 135, 163}},
    {DFI_FORME_GRIMMSNARL, DFI_NATURE_SASSY, {32, 0, 14, 0, 20, 0}, {202, 140, 99, 115, 126, 72}},
};

static void check_move(df_test *t, uint32_t id, uint32_t type, uint32_t category, uint32_t bp, uint32_t acc,
                       uint32_t pp_base, uint32_t pp_max, uint32_t priority, uint32_t flags, const char *what)
{
    const dfi_move_data *m = &dfi_closure_moves[id];
    if (!DF_CHECK(t, m->type == type && m->category == category && m->base_power == bp && m->accuracy == acc &&
                         m->pp_base == pp_base && m->pp_max == pp_max &&
                         m->priority == priority + DFI_PRIORITY_BIAS && m->flags == flags)) {
        fprintf(stderr, "  move %s: type %u cat %u bp %u acc %u pp %u/%u prio %u flags %u\n", what, m->type,
                m->category, m->base_power, m->accuracy, m->pp_base, m->pp_max, m->priority, m->flags);
    }
}

static uint32_t stage(const dfi_move_data *m, uint32_t index)
{
    return m->boosts[index];
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.data.closure_tables");

    /* Counts of the closure (decision 0004: 12 sets, 4 Mega formes, 36 moves
     * plus Struggle, 12 + 4 abilities, 11 distinct items). */
    DF_CHECK_EQ_U64(&t, DFI_FORME_COUNT, 16u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_COUNT, 37u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_COUNT, 16u);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_COUNT, 11u);
    DF_CHECK_EQ_U64(&t, DFI_TYPE_COUNT, 18u);
    DF_CHECK_EQ_U64(&t, DFI_NATURE_COUNT, 25u);

    /* The table hash equals the SHA-256 of the canonical bytes built in C
     * from the tables, and the literal printed by the generator. */
    {
        uint8_t bytes[DFI_CLOSURE_CANONICAL_SIZE + 8u];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        memset(bytes, 0xA5, sizeof bytes);
        const size_t n = dfi_closure_canonical_bytes(bytes, sizeof bytes);
        DF_CHECK_EQ_U64(&t, n, DFI_CLOSURE_CANONICAL_SIZE);
        DF_CHECK_EQ_U64(&t, DFI_CLOSURE_CANONICAL_SIZE, 1883u);
        DF_CHECK(&t, bytes[DFI_CLOSURE_CANONICAL_SIZE] == 0xA5u); /* nothing written past the size */
        DF_CHECK(&t, dfi_sha256(bytes, n, sha));
        DF_CHECK(&t, df_hex_to_bytes(TABLE_HASH_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, sha, want, sizeof sha, "sha256(canonical bytes)");
        DF_CHECK_BYTES(&t, dfi_closure_table_hash, want, sizeof want, "dfi_closure_table_hash");
        uint8_t small[16];
        memset(small, 0xA5, sizeof small);
        DF_CHECK_EQ_U64(&t, dfi_closure_canonical_bytes(small, sizeof small), 0u);
        DF_CHECK(&t, small[0] == 0xA5u && small[15] == 0xA5u);
    }

    /* Move ids 0..35 follow decision 0005: their target classes equal the M2
     * fixture table T1. Struggle is id 36 and is never selectable. */
    {
        unsigned diff = 0;
        for (uint32_t i = 0; i < 36u; ++i) {
            diff += dfi_closure_moves[i].target_class != df_table_t1[i] ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
        DF_CHECK_EQ_U64(&t, DFI_MOVE_STRUGGLE, 36u);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_STRUGGLE].target_class, DFI_TARGET_CLASS_RANDOM_NORMAL);
    }

    /* Moves: literal values read at the pin (data/moves.ts plus the champions
     * overrides for Protect, Iron Head and Make It Rain). */
    {
        const uint32_t CP = DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT;
        check_move(&t, DFI_MOVE_WOODHAMMER, DFI_TYPE_GRASS, DFI_CATEGORY_PHYSICAL, 120, 100, 15, 16, 0, CP, "woodhammer");
        check_move(&t, DFI_MOVE_FAKEOUT, DFI_TYPE_NORMAL, DFI_CATEGORY_PHYSICAL, 40, 100, 10, 12, 3, CP, "fakeout");
        check_move(&t, DFI_MOVE_PROTECT, DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0, 0, 5, 8, 4, DFI_MOVE_FLAG_STALLING, "protect");
        check_move(&t, DFI_MOVE_MUDDYWATER, DFI_TYPE_WATER, DFI_CATEGORY_SPECIAL, 90, 85, 10, 12, 0, DFI_MOVE_FLAG_PROTECT, "muddywater");
        check_move(&t, DFI_MOVE_SHADOWSNEAK, DFI_TYPE_GHOST, DFI_CATEGORY_PHYSICAL, 40, 100, 30, 20, 1, CP, "shadowsneak");
        check_move(&t, DFI_MOVE_ZAPCANNON, DFI_TYPE_ELECTRIC, DFI_CATEGORY_SPECIAL, 120, 50, 5, 8, 0, DFI_MOVE_FLAG_PROTECT, "zapcannon");
        check_move(&t, DFI_MOVE_MAKEITRAIN, DFI_TYPE_STEEL, DFI_CATEGORY_SPECIAL, 120, 95, 5, 8, 0, DFI_MOVE_FLAG_PROTECT, "makeitrain");
        check_move(&t, DFI_MOVE_ELECTROSHOT, DFI_TYPE_ELECTRIC, DFI_CATEGORY_SPECIAL, 130, 100, 10, 12, 0,
                   DFI_MOVE_FLAG_PROTECT | DFI_MOVE_FLAG_CHARGE, "electroshot");
        check_move(&t, DFI_MOVE_SNARL, DFI_TYPE_DARK, DFI_CATEGORY_SPECIAL, 55, 95, 15, 16, 0, DFI_MOVE_FLAG_PROTECT, "snarl");
        check_move(&t, DFI_MOVE_GRASSKNOT, DFI_TYPE_GRASS, DFI_CATEGORY_SPECIAL, 0, 100, 20, 20, 0, CP, "grassknot");
        check_move(&t, DFI_MOVE_HURRICANE, DFI_TYPE_FLYING, DFI_CATEGORY_SPECIAL, 110, 70, 10, 12, 0, DFI_MOVE_FLAG_PROTECT, "hurricane");
        check_move(&t, DFI_MOVE_LIGHTSCREEN, DFI_TYPE_PSYCHIC, DFI_CATEGORY_STATUS, 0, 0, 30, 20, 0, 0, "lightscreen");
        check_move(&t, DFI_MOVE_PARTINGSHOT, DFI_TYPE_DARK, DFI_CATEGORY_STATUS, 0, 100, 20, 20, 0,
                   DFI_MOVE_FLAG_PROTECT | DFI_MOVE_FLAG_SELF_SWITCH, "partingshot");
        check_move(&t, DFI_MOVE_STRUGGLE, DFI_TYPE_NORMAL, DFI_CATEGORY_PHYSICAL, 50, 0, 1, 1, 0,
                   CP | DFI_MOVE_FLAG_NO_PP_BOOSTS | DFI_MOVE_FLAG_STRUGGLE_RECOIL, "struggle");
        /* Trick Room has priority -7, stored biased. */
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_TRICKROOM].priority, 1u);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_TRICKROOM].pseudo_weather, DFI_PSEUDO_WEATHER_TRICK_ROOM);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_TRICKROOM].pp_max, 8u);
        /* Crit ratio: default 1, Drill Run 2. */
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_DRILLRUN].crit_ratio, 2u);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_DRAGONPULSE].crit_ratio, 1u);
        /* Recoil 33/100 and drain 1/2. */
        DF_CHECK(&t, dfi_closure_moves[DFI_MOVE_WOODHAMMER].recoil[0] == 33u && dfi_closure_moves[DFI_MOVE_WOODHAMMER].recoil[1] == 100u);
        DF_CHECK(&t, dfi_closure_moves[DFI_MOVE_BRAVEBIRD].recoil[0] == 33u && dfi_closure_moves[DFI_MOVE_BRAVEBIRD].recoil[1] == 100u);
        DF_CHECK(&t, dfi_closure_moves[DFI_MOVE_LEECHLIFE].drain[0] == 1u && dfi_closure_moves[DFI_MOVE_LEECHLIFE].drain[1] == 2u);
        DF_CHECK(&t, dfi_closure_moves[DFI_MOVE_BITTERBLADE].drain[0] == 1u && dfi_closure_moves[DFI_MOVE_BITTERBLADE].drain[1] == 2u);
        DF_CHECK(&t, dfi_closure_moves[DFI_MOVE_DRAGONPULSE].recoil[1] == 0u && dfi_closure_moves[DFI_MOVE_DRAGONPULSE].drain[1] == 0u);
        /* Secondary effects. */
        const dfi_move_data *m = &dfi_closure_moves[DFI_MOVE_IRONHEAD]; /* champions: 20 percent flinch */
        DF_CHECK(&t, m->sec_chance == 20u && m->sec_kind == DFI_SECONDARY_VOLATILE && m->sec_param == DFI_VOLATILE_FLINCH);
        m = &dfi_closure_moves[DFI_MOVE_FAKEOUT];
        DF_CHECK(&t, m->sec_chance == 100u && m->sec_kind == DFI_SECONDARY_VOLATILE && m->sec_param == DFI_VOLATILE_FLINCH &&
                         m->special == DFI_SPECIAL_FAKE_OUT);
        m = &dfi_closure_moves[DFI_MOVE_ICEBEAM];
        DF_CHECK(&t, m->sec_chance == 10u && m->sec_kind == DFI_SECONDARY_STATUS && m->sec_param == DFI_STATUS_FRZ);
        m = &dfi_closure_moves[DFI_MOVE_HEATWAVE];
        DF_CHECK(&t, m->sec_chance == 10u && m->sec_kind == DFI_SECONDARY_STATUS && m->sec_param == DFI_STATUS_BRN);
        m = &dfi_closure_moves[DFI_MOVE_ZAPCANNON];
        DF_CHECK(&t, m->sec_chance == 100u && m->sec_kind == DFI_SECONDARY_STATUS && m->sec_param == DFI_STATUS_PAR);
        m = &dfi_closure_moves[DFI_MOVE_HURRICANE];
        DF_CHECK(&t, m->sec_chance == 30u && m->sec_kind == DFI_SECONDARY_VOLATILE && m->sec_param == DFI_VOLATILE_CONFUSION &&
                         m->special == DFI_SPECIAL_HURRICANE);
        m = &dfi_closure_moves[DFI_MOVE_SNARL];
        DF_CHECK(&t, m->sec_chance == 100u && m->sec_kind == DFI_SECONDARY_BOOST &&
                         m->boost_role == DFI_BOOST_ROLE_SECONDARY_TARGET && stage(m, DFI_STAGE_SPA) == 5u &&
                         stage(m, DFI_STAGE_ATK) == 6u);
        m = &dfi_closure_moves[DFI_MOVE_MUDDYWATER];
        DF_CHECK(&t, m->sec_chance == 30u && m->sec_kind == DFI_SECONDARY_BOOST && stage(m, DFI_STAGE_ACCURACY) == 5u);
        m = &dfi_closure_moves[DFI_MOVE_SHADOWBALL];
        DF_CHECK(&t, m->sec_chance == 20u && stage(m, DFI_STAGE_SPD) == 5u);
        /* Self drops and primary boosts. */
        m = &dfi_closure_moves[DFI_MOVE_CLOSECOMBAT];
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT && stage(m, DFI_STAGE_DEF) == 5u &&
                         stage(m, DFI_STAGE_SPD) == 5u && stage(m, DFI_STAGE_ATK) == 6u && m->sec_chance == 0u);
        m = &dfi_closure_moves[DFI_MOVE_MAKEITRAIN]; /* champions: -2 SpA */
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT && stage(m, DFI_STAGE_SPA) == 4u);
        m = &dfi_closure_moves[DFI_MOVE_SWORDSDANCE];
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_PRIMARY_SELF && stage(m, DFI_STAGE_ATK) == 8u);
        m = &dfi_closure_moves[DFI_MOVE_NASTYPLOT];
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_PRIMARY_SELF && stage(m, DFI_STAGE_SPA) == 8u);
        m = &dfi_closure_moves[DFI_MOVE_COIL];
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_PRIMARY_SELF && stage(m, DFI_STAGE_ATK) == 7u &&
                         stage(m, DFI_STAGE_DEF) == 7u && stage(m, DFI_STAGE_ACCURACY) == 7u && stage(m, DFI_STAGE_SPE) == 6u);
        /* Primary status, side conditions and handlers. */
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_HYPNOSIS].primary_status, DFI_STATUS_SLP);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_HYPNOSIS].accuracy, 60u);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_TAILWIND].side_condition, DFI_SIDE_CONDITION_TAILWIND);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_REFLECT].side_condition, DFI_SIDE_CONDITION_REFLECT);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_LIGHTSCREEN].side_condition, DFI_SIDE_CONDITION_LIGHT_SCREEN);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_GRASSKNOT].special, DFI_SPECIAL_GRASS_KNOT);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_WEATHERBALL].special, DFI_SPECIAL_WEATHER_BALL);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_GRASSYGLIDE].special, DFI_SPECIAL_GRASSY_GLIDE);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_ELECTROSHOT].special, DFI_SPECIAL_ELECTRO_SHOT);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_PARTINGSHOT].special, DFI_SPECIAL_PARTING_SHOT);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_PROTECT].special, DFI_SPECIAL_PROTECT);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_STRUGGLE].special, DFI_SPECIAL_STRUGGLE);
        DF_CHECK_EQ_U64(&t, dfi_closure_moves[DFI_MOVE_DRAGONPULSE].special, DFI_SPECIAL_NONE);
        /* Every record is in range. */
        unsigned bad = 0;
        for (uint32_t i = 0; i < DFI_MOVE_COUNT; ++i) {
            const dfi_move_data *x = &dfi_closure_moves[i];
            bad += x->type >= DFI_TYPE_COUNT || x->category > DFI_CATEGORY_STATUS || x->target_class < 1u ||
                           x->target_class > 10u || x->crit_ratio < 1u || x->crit_ratio > 2u || x->pp_max > DFI_PP_CAP
                       ? 1u
                       : 0u;
            for (uint32_t k = 0; k < DFI_STAGE_COUNT; ++k) {
                bad += x->boosts[k] > 12u ? 1u : 0u;
            }
            bad += (x->boost_role == DFI_BOOST_ROLE_NONE) != (memcmp(x->boosts, "\6\6\6\6\6\6\6", 7) == 0) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
    }

    /* Formes: literal values read at the pin (data/pokedex.ts). */
    {
        const dfi_forme_data *f = &dfi_closure_formes[DFI_FORME_ARCHALUDON];
        DF_CHECK(&t, f->dex_num == 1018u && f->types[0] == DFI_TYPE_STEEL && f->types[1] == DFI_TYPE_DRAGON &&
                         f->weight_hg == 600u && f->ability == DFI_ABILITY_STAMINA && f->is_mega == 0u &&
                         f->mega_forme == DFI_CLOSURE_NONE && f->mega_item == DFI_CLOSURE_NONE &&
                         f->set_item == DFI_ITEM_LEFTOVERS && f->gender_rule == DFI_GENDER_RULE_ANY);
        DF_CHECK(&t, f->base[0] == 90u && f->base[1] == 105u && f->base[2] == 130u && f->base[3] == 125u &&
                         f->base[4] == 65u && f->base[5] == 85u);
        DF_CHECK(&t, f->set_move_count == 4u && f->set_moves[0] == DFI_MOVE_DRAGONPULSE &&
                         f->set_moves[1] == DFI_MOVE_ELECTROSHOT && f->set_moves[2] == DFI_MOVE_SNARL &&
                         f->set_moves[3] == DFI_MOVE_PROTECT);
        f = &dfi_closure_formes[DFI_FORME_MILOTIC];
        DF_CHECK(&t, f->types[0] == DFI_TYPE_WATER && f->types[1] == DFI_CLOSURE_NONE && f->weight_hg == 1620u &&
                         f->set_item == DFI_ITEM_SITRUSBERRY);
        DF_CHECK_EQ_U64(&t, dfi_closure_formes[DFI_FORME_FARIGIRAF].set_item, DFI_ITEM_SITRUSBERRY); /* once per team */
        DF_CHECK_EQ_U64(&t, dfi_closure_formes[DFI_FORME_GRIMMSNARL].gender_rule, DFI_GENDER_RULE_MALE);
        DF_CHECK_EQ_U64(&t, dfi_closure_formes[DFI_FORME_GHOLDENGO].gender_rule, DFI_GENDER_RULE_NONE);
        DF_CHECK_EQ_U64(&t, dfi_closure_formes[DFI_FORME_STARAPTOR].weight_hg, 249u); /* 24.9 kg */
        /* The four Mega formes: link, stone, own ability, changed typing. */
        static const struct {
            uint32_t base;
            uint32_t mega;
            uint32_t item;
            uint32_t ability;
        } megas[] = {
            {DFI_FORME_STARAPTOR, DFI_FORME_STARAPTORMEGA, DFI_ITEM_STARAPTITE, DFI_ABILITY_CONTRARY},
            {DFI_FORME_RAICHU, DFI_FORME_RAICHUMEGAY, DFI_ITEM_RAICHUNITEY, DFI_ABILITY_NOGUARD},
            {DFI_FORME_GOLISOPOD, DFI_FORME_GOLISOPODMEGA, DFI_ITEM_GOLISOPITE, DFI_ABILITY_TOUGHCLAWS},
            {DFI_FORME_CHARIZARD, DFI_FORME_CHARIZARDMEGAY, DFI_ITEM_CHARIZARDITEY, DFI_ABILITY_DROUGHT},
        };
        for (unsigned i = 0; i < 4; ++i) {
            const dfi_forme_data *b = &dfi_closure_formes[megas[i].base];
            const dfi_forme_data *g = &dfi_closure_formes[megas[i].mega];
            DF_CHECK(&t, b->is_mega == 0u && b->mega_forme == megas[i].mega && b->mega_item == megas[i].item &&
                             b->base_forme == megas[i].base);
            DF_CHECK(&t, g->is_mega == 1u && g->base_forme == megas[i].base && g->mega_forme == DFI_CLOSURE_NONE &&
                             g->ability == megas[i].ability && g->set_move_count == 0u && g->base[0] == b->base[0] &&
                             g->dex_num == b->dex_num && g->gender_rule == b->gender_rule);
            DF_CHECK(&t, dfi_closure_items[megas[i].item].mega_base == megas[i].base &&
                             dfi_closure_items[megas[i].item].mega_forme == megas[i].mega);
        }
        f = &dfi_closure_formes[DFI_FORME_STARAPTORMEGA];
        DF_CHECK(&t, f->types[0] == DFI_TYPE_FIGHTING && f->types[1] == DFI_TYPE_FLYING);
        f = &dfi_closure_formes[DFI_FORME_GOLISOPODMEGA];
        DF_CHECK(&t, f->types[0] == DFI_TYPE_BUG && f->types[1] == DFI_TYPE_STEEL && f->weight_hg == 1480u);
        /* Only the four stones are Mega Stones. */
        unsigned stones = 0;
        for (uint32_t i = 0; i < DFI_ITEM_COUNT; ++i) {
            stones += dfi_closure_items[i].mega_base != DFI_CLOSURE_NONE ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, stones, 4u);
        /* Base formes carry a complete set; every id is in range. */
        unsigned bad = 0;
        unsigned bases = 0;
        for (uint32_t i = 0; i < DFI_FORME_COUNT; ++i) {
            const dfi_forme_data *x = &dfi_closure_formes[i];
            bases += x->is_mega == 0u ? 1u : 0u;
            bad += x->ability >= DFI_ABILITY_COUNT || x->set_item >= DFI_ITEM_COUNT || x->types[0] >= DFI_TYPE_COUNT ||
                           x->base_forme >= DFI_FORME_COUNT || x->gender_rule > DFI_GENDER_RULE_NONE
                       ? 1u
                       : 0u;
            bad += (x->is_mega == 0u) != (x->set_move_count == 4u) ? 1u : 0u;
            for (uint32_t k = 0; k < x->set_move_count && k < 4u; ++k) {
                bad += x->set_moves[k] >= DFI_MOVE_STRUGGLE ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        DF_CHECK_EQ_U64(&t, bases, 12u);
    }

    /* Type chart and status immunities (data/typechart.ts). Rows are the
     * defender, columns the attacking type. */
    {
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_FLYING][DFI_TYPE_GROUND], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_FAIRY][DFI_TYPE_DRAGON], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_DRAGON][DFI_TYPE_FAIRY], DFI_EFFECT_SUPER);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_NORMAL][DFI_TYPE_GHOST], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_GHOST][DFI_TYPE_NORMAL], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_DARK][DFI_TYPE_PSYCHIC], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_GROUND][DFI_TYPE_ELECTRIC], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_STEEL][DFI_TYPE_POISON], DFI_EFFECT_IMMUNE);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_WATER][DFI_TYPE_FIRE], DFI_EFFECT_RESISTED);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_GRASS][DFI_TYPE_FIRE], DFI_EFFECT_SUPER);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_STEEL][DFI_TYPE_FIGHTING], DFI_EFFECT_SUPER);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_STEEL][DFI_TYPE_DRAGON], DFI_EFFECT_RESISTED);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_chart[DFI_TYPE_NORMAL][DFI_TYPE_NORMAL], DFI_EFFECT_NEUTRAL);
        /* Counts over the whole chart: 8 immunities, 51 super effective and
         * 61 resisted pairs in the 18-type chart. */
        unsigned n[4] = {0, 0, 0, 0};
        for (uint32_t d = 0; d < DFI_TYPE_COUNT; ++d) {
            for (uint32_t a = 0; a < DFI_TYPE_COUNT; ++a) {
                if (dfi_closure_type_chart[d][a] < 4u) {
                    n[dfi_closure_type_chart[d][a]]++;
                }
            }
        }
        DF_CHECK_EQ_U64(&t, n[DFI_EFFECT_IMMUNE], 8u);
        DF_CHECK_EQ_U64(&t, n[DFI_EFFECT_SUPER], 51u);
        DF_CHECK_EQ_U64(&t, n[DFI_EFFECT_RESISTED], 61u);
        DF_CHECK_EQ_U64(&t, n[0] + n[1] + n[2] + n[3], 324u);
        /* Status immunities: Fire burn, Ice freeze, Electric paralysis, Dark
         * Prankster. Fire is NOT immune to freeze. */
        DF_CHECK_EQ_U64(&t, dfi_closure_type_immunity[DFI_TYPE_FIRE], DFI_IMMUNE_BRN);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_immunity[DFI_TYPE_ICE], DFI_IMMUNE_FRZ);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_immunity[DFI_TYPE_ELECTRIC], DFI_IMMUNE_PAR);
        DF_CHECK_EQ_U64(&t, dfi_closure_type_immunity[DFI_TYPE_DARK], DFI_IMMUNE_PRANKSTER);
        unsigned others = 0;
        for (uint32_t i = 0; i < DFI_TYPE_COUNT; ++i) {
            others += dfi_closure_type_immunity[i] != 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, others, 4u);
    }

    /* Natures (data/natures.ts). */
    {
        DF_CHECK(&t, dfi_closure_natures[DFI_NATURE_BOLD].plus == DFI_STAT_DEF && dfi_closure_natures[DFI_NATURE_BOLD].minus == DFI_STAT_ATK);
        DF_CHECK(&t, dfi_closure_natures[DFI_NATURE_TIMID].plus == DFI_STAT_SPE && dfi_closure_natures[DFI_NATURE_TIMID].minus == DFI_STAT_ATK);
        DF_CHECK(&t, dfi_closure_natures[DFI_NATURE_SASSY].plus == DFI_STAT_SPD && dfi_closure_natures[DFI_NATURE_SASSY].minus == DFI_STAT_SPE);
        DF_CHECK(&t, dfi_closure_natures[DFI_NATURE_HARDY].plus == DFI_CLOSURE_NONE && dfi_closure_natures[DFI_NATURE_HARDY].minus == DFI_CLOSURE_NONE);
        unsigned neutral = 0;
        unsigned bad = 0;
        for (uint32_t i = 0; i < DFI_NATURE_COUNT; ++i) {
            const dfi_nature_data *x = &dfi_closure_natures[i];
            neutral += x->plus == DFI_CLOSURE_NONE ? 1u : 0u;
            bad += (x->plus == DFI_CLOSURE_NONE) != (x->minus == DFI_CLOSURE_NONE) ? 1u : 0u;
            bad += x->plus != DFI_CLOSURE_NONE && (x->plus < DFI_STAT_ATK || x->plus > DFI_STAT_SPE || x->plus == x->minus) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, neutral, 5u);
        DF_CHECK_EQ_U64(&t, bad, 0u);
    }

    /* Champions stat formula: all 16 formes with the sets of decision 0004. */
    for (unsigned i = 0; i < sizeof sets / sizeof sets[0]; ++i) {
        const dfi_forme_data *f = &dfi_closure_formes[sets[i].forme];
        uint32_t total = 0;
        for (uint32_t s = 0; s < DFI_STAT_COUNT; ++s) {
            uint16_t v = 0xA5A5u;
            total += sets[i].sp[s];
            DF_CHECK(&t, dfi_champions_stat(s, f->base[s], sets[i].sp[s], sets[i].nature, &v));
            if (!DF_CHECK(&t, v == sets[i].expected[s])) {
                fprintf(stderr, "  forme %u stat %u: %u, expected %u\n", sets[i].forme, s, v, sets[i].expected[s]);
            }
        }
        DF_CHECK_EQ_U64(&t, total, DFI_STAT_POINTS_TOTAL_MAX); /* every reference set spends all 66 points */
    }
    /* Formula edges and rejected arguments (*out untouched). */
    {
        uint16_t v = 0xA5A5u;
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_HP, 1u, 0u, DFI_NATURE_HARDY, &v) && v == 76u);
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_HP, 255u, 32u, DFI_NATURE_ADAMANT, &v) && v == 362u); /* nature never touches HP */
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_ATK, 255u, 32u, DFI_NATURE_ADAMANT, &v) && v == 337u); /* 307 * 110 / 100 */
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_SPA, 255u, 32u, DFI_NATURE_ADAMANT, &v) && v == 276u); /* 307 * 90 / 100 */
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_SPE, 1u, 0u, DFI_NATURE_HARDY, &v) && v == 21u);
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_DEF, 79u, 29u, DFI_NATURE_CALM, &v) && v == 128u); /* neutral for Def */
        v = 0xA5A5u;
        DF_CHECK(&t, !dfi_champions_stat(6u, 100u, 0u, DFI_NATURE_HARDY, &v));
        DF_CHECK(&t, !dfi_champions_stat(DFI_STAT_ATK, 0u, 0u, DFI_NATURE_HARDY, &v));
        DF_CHECK(&t, !dfi_champions_stat(DFI_STAT_ATK, 256u, 0u, DFI_NATURE_HARDY, &v));
        DF_CHECK(&t, !dfi_champions_stat(DFI_STAT_ATK, 100u, 33u, DFI_NATURE_HARDY, &v));
        DF_CHECK(&t, !dfi_champions_stat(DFI_STAT_ATK, 100u, 0u, 25u, &v));
        DF_CHECK(&t, !dfi_champions_stat(DFI_STAT_ATK, 100u, 0xFFFFFFFFu, DFI_NATURE_HARDY, &v));
        DF_CHECK_EQ_U64(&t, v, 0xA5A5u);
    }

    /* Champions PP: the table column equals the formula; literal cases. */
    {
        unsigned diff = 0;
        for (uint32_t i = 0; i < DFI_MOVE_COUNT; ++i) {
            const dfi_move_data *m = &dfi_closure_moves[i];
            uint8_t pp = 0xA5u;
            const bool ok = dfi_champions_pp_max(m->pp_base, (m->flags & DFI_MOVE_FLAG_NO_PP_BOOSTS) != 0u, &pp);
            diff += (!ok || pp != m->pp_max) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
        uint8_t pp = 0xA5u;
        DF_CHECK(&t, dfi_champions_pp_max(5u, false, &pp) && pp == 8u);
        DF_CHECK(&t, dfi_champions_pp_max(10u, false, &pp) && pp == 12u);
        DF_CHECK(&t, dfi_champions_pp_max(15u, false, &pp) && pp == 16u);
        DF_CHECK(&t, dfi_champions_pp_max(20u, false, &pp) && pp == 20u);
        DF_CHECK(&t, dfi_champions_pp_max(30u, false, &pp) && pp == 20u); /* capped at 20 first */
        DF_CHECK(&t, dfi_champions_pp_max(40u, false, &pp) && pp == 20u);
        DF_CHECK(&t, dfi_champions_pp_max(1u, true, &pp) && pp == 1u); /* Struggle */
        pp = 0xA5u;
        DF_CHECK(&t, !dfi_champions_pp_max(0u, false, &pp));
        DF_CHECK(&t, !dfi_champions_pp_max(7u, false, &pp)); /* not a multiple of 5 */
        DF_CHECK(&t, !dfi_champions_pp_max(256u, false, &pp));
        DF_CHECK_EQ_U64(&t, pp, 0xA5u);
    }

    return df_test_end(&t);
}
