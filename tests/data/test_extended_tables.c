/*
 * duoforge.data.extended_tables (white-box): the extended tables of decision
 * 0009, the closure followed by Team C.
 *
 * The closure ids are an exact prefix: every closure row equals the row of
 * src/data/closure_tables.c, the only extension inside the prefix is the
 * poison immunity bit, and the closure canonical bytes recomputed from the
 * prefix hash to the closure table hash (so the CLOSURE fingerprint still
 * names the data a CLOSURE battle reads). Team C rows are literal values read
 * at the pinned reference (docs/research/third-team/mechanics.md sections 2
 * and 3); the stat lines are what the pin's spreadModify gives for the sets of
 * docs/research/third-team/team-c.txt.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/bytes.h"
#include "core/sha256.h"
#include "data/extended_tables.h"
#include "data/formulas.h"
#include "support/check.h"

#define EXT_HASH_HEX "d16b1cef1b41f0a573ae74c10102c932c1f4de0ec3c1f33449f920e533a943e5"

typedef struct set_case {
    uint32_t forme;
    uint32_t nature;
    uint32_t sp[6];       /* Stat Points of the set in team-c.txt */
    uint32_t expected[6]; /* HP Atk Def SpA SpD Spe at the pin */
} set_case;

/* Salamence-Mega uses the Stat Points and nature of its base forme. */
static const set_case sets[] = {
    {DFI_FORME_SNEASLER, DFI_NATURE_ADAMANT, {2, 32, 0, 0, 0, 32}, {157, 200, 80, 54, 100, 172}},
    {DFI_FORME_INCINEROAR, DFI_NATURE_CAREFUL, {32, 0, 14, 0, 20, 0}, {202, 135, 124, 90, 143, 80}},
    {DFI_FORME_SALAMENCE, DFI_NATURE_TIMID, {2, 0, 0, 32, 0, 32}, {172, 139, 100, 162, 100, 167}},
    {DFI_FORME_SALAMENCEMEGA, DFI_NATURE_TIMID, {2, 0, 0, 32, 0, 32}, {172, 148, 150, 172, 110, 189}},
    {DFI_FORME_INDEEDEEF, DFI_NATURE_RELAXED, {32, 0, 32, 0, 2, 0}, {177, 75, 128, 115, 127, 94}},
    {DFI_FORME_KINGAMBIT, DFI_NATURE_ADAMANT, {32, 32, 0, 0, 2, 0}, {207, 205, 140, 72, 107, 70}},
    {DFI_FORME_BASCULEGION, DFI_NATURE_JOLLY, {2, 32, 0, 0, 0, 32}, {197, 164, 85, 90, 95, 143}},
};

static void check_move(df_test *t, uint32_t id, uint32_t type, uint32_t category, uint32_t bp, uint32_t acc,
                       uint32_t pp_base, uint32_t pp_max, uint32_t priority, uint32_t target_class, uint32_t flags,
                       uint32_t special, const char *what)
{
    const dfi_move_data *m = &dfi_ext_moves[id];
    if (!DF_CHECK(t, m->type == type && m->category == category && m->base_power == bp && m->accuracy == acc &&
                         m->pp_base == pp_base && m->pp_max == pp_max &&
                         m->priority == priority + DFI_PRIORITY_BIAS && m->target_class == target_class &&
                         m->flags == flags && m->special == special)) {
        fprintf(stderr, "  move %s: type %u cat %u bp %u acc %u pp %u/%u prio %u target %u flags %u special %u\n",
                what, m->type, m->category, m->base_power, m->accuracy, m->pp_base, m->pp_max, m->priority,
                m->target_class, m->flags, m->special);
    }
}

static void check_forme(df_test *t, uint32_t id, uint32_t type0, uint32_t type1, const uint32_t base[6],
                        uint32_t weight_hg, uint32_t ability, uint32_t gender_rule, uint32_t set_item,
                        const char *what)
{
    const dfi_forme_data *f = &dfi_ext_formes[id];
    uint32_t base_ok = 1u;
    for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
        base_ok &= f->base[k] == base[k] ? 1u : 0u;
    }
    if (!DF_CHECK(t, f->types[0] == type0 && f->types[1] == type1 && base_ok == 1u && f->weight_hg == weight_hg &&
                         f->ability == ability && f->gender_rule == gender_rule && f->set_item == set_item)) {
        fprintf(stderr, "  forme %s: types %u/%u weight %u ability %u gender %u item %u\n", what, f->types[0],
                f->types[1], f->weight_hg, f->ability, f->gender_rule, f->set_item);
    }
}

static void check_set_moves(df_test *t, uint32_t forme, const uint32_t moves[4], const char *what)
{
    const dfi_forme_data *f = &dfi_ext_formes[forme];
    uint32_t same = f->set_move_count == 4u ? 1u : 0u;
    for (uint32_t k = 0u; k < 4u; ++k) {
        same &= f->set_moves[k] == moves[k] ? 1u : 0u;
    }
    if (!DF_CHECK(t, same == 1u)) {
        fprintf(stderr, "  set moves of %s differ\n", what);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.data.extended_tables");

    /* Counts: the closure plus 7 formes (6 sets and Salamence-Mega), 13
     * moves, 5 abilities and 5 items (mechanics.md section 1). Team C ids
     * start where the closure's end. */
    DF_CHECK_EQ_U64(&t, DFI_EXT_FORME_COUNT, 23u);
    DF_CHECK_EQ_U64(&t, DFI_EXT_MOVE_COUNT, 50u);
    DF_CHECK_EQ_U64(&t, DFI_EXT_ABILITY_COUNT, 21u);
    DF_CHECK_EQ_U64(&t, DFI_EXT_ITEM_COUNT, 16u);
    DF_CHECK_EQ_U64(&t, DFI_FORME_SNEASLER, DFI_FORME_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_FORME_BASCULEGION, DFI_EXT_FORME_COUNT - 1u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_DIRECLAW, DFI_MOVE_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_FLIPTURN, DFI_EXT_MOVE_COUNT - 1u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_STRUGGLE, 36u);
    DF_CHECK_EQ_U64(&t, DFI_ABILITY_UNBURDEN, DFI_ABILITY_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_WHITEHERB, DFI_ITEM_COUNT);
    DF_CHECK_EQ_U64(&t, DFI_ITEM_CHOICESCARF, DFI_EXT_ITEM_COUNT - 1u);

    /* The prefix is the closure, row by row. */
    {
        uint32_t diff = 0u;
        for (uint32_t i = 0u; i < DFI_FORME_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_ext_formes[i], (const uint8_t *)&dfi_closure_formes[i],
                                   sizeof dfi_ext_formes[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_MOVE_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_ext_moves[i], (const uint8_t *)&dfi_closure_moves[i],
                                   sizeof dfi_ext_moves[i]) ? 0u : 1u;
        }
        for (uint32_t i = 0u; i < DFI_ITEM_COUNT; ++i) {
            diff += dfi_bytes_equal((const uint8_t *)&dfi_ext_items[i], (const uint8_t *)&dfi_closure_items[i],
                                   sizeof dfi_ext_items[i]) ? 0u : 1u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
    }

    /* The only extension inside the prefix: Poison and Steel are immune to
     * poison (data/typechart.ts key psn); every closure bit is unchanged. */
    {
        const uint32_t closure_bits = DFI_IMMUNE_BRN | DFI_IMMUNE_FRZ | DFI_IMMUNE_PAR | DFI_IMMUNE_PRANKSTER;
        uint32_t diff = 0u;
        for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
            const uint32_t ext = dfi_ext_type_immunity[i];
            const uint32_t psn = i == DFI_TYPE_POISON || i == DFI_TYPE_STEEL ? DFI_IMMUNE_PSN : 0u;
            diff += (ext & closure_bits) != dfi_closure_type_immunity[i] ? 1u : 0u;
            diff += (ext & ~closure_bits) != psn ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
    }

    /* The closure canonical bytes recomputed from the prefix (closure
     * immunity bits only) are the closure's, so they hash to the closure
     * table hash that the CLOSURE fingerprint carries. */
    {
        uint8_t closure[DFI_CLOSURE_CANONICAL_SIZE];
        uint8_t prefix[DFI_EXT_CANONICAL_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        const uint32_t closure_bits = DFI_IMMUNE_BRN | DFI_IMMUNE_FRZ | DFI_IMMUNE_PAR | DFI_IMMUNE_PRANKSTER;
        DF_CHECK_EQ_U64(&t, dfi_closure_canonical_bytes(closure, sizeof closure), DFI_CLOSURE_CANONICAL_SIZE);
        const size_t n = dfi_ext_canonical_bytes_of(prefix, sizeof prefix, DFI_FORME_COUNT, DFI_MOVE_COUNT,
                                                    DFI_ITEM_COUNT, DFI_ABILITY_COUNT, closure_bits);
        DF_CHECK_EQ_U64(&t, n, DFI_CLOSURE_CANONICAL_SIZE);
        DF_CHECK_BYTES(&t, prefix, closure, DFI_CLOSURE_CANONICAL_SIZE, "closure canonical bytes from the prefix");
        DF_CHECK(&t, dfi_sha256(prefix, n, sha));
        DF_CHECK_BYTES(&t, sha, dfi_closure_table_hash, sizeof sha, "sha256(prefix) = closure table hash");
    }

    /* The extended hash: SHA-256 of the extended canonical bytes, equal to
     * the generator's literal and different from the closure's. */
    {
        uint8_t bytes[DFI_EXT_CANONICAL_SIZE + 8u];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        memset(bytes, 0xA5, sizeof bytes);
        const size_t n = dfi_ext_canonical_bytes(bytes, sizeof bytes);
        DF_CHECK_EQ_U64(&t, n, DFI_EXT_CANONICAL_SIZE);
        DF_CHECK_EQ_U64(&t, DFI_EXT_CANONICAL_SIZE, 2438u); /* 12 + 23 * 24 + 50 * 29 + 16 * 2 + 324 + 18 + 50 */
        DF_CHECK(&t, bytes[DFI_EXT_CANONICAL_SIZE] == 0xA5u);
        DF_CHECK(&t, dfi_sha256(bytes, n, sha));
        DF_CHECK(&t, df_hex_to_bytes(EXT_HASH_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, sha, want, sizeof sha, "sha256(extended canonical bytes)");
        DF_CHECK_BYTES(&t, dfi_ext_table_hash, want, sizeof want, "dfi_ext_table_hash");
        DF_CHECK(&t, !dfi_bytes_equal(dfi_ext_table_hash, dfi_closure_table_hash, sizeof want));
        uint8_t small[16];
        memset(small, 0xA5, sizeof small);
        DF_CHECK_EQ_U64(&t, dfi_ext_canonical_bytes(small, sizeof small), 0u);
        DF_CHECK(&t, small[0] == 0xA5u && small[15] == 0xA5u);
        DF_CHECK_EQ_U64(&t, dfi_ext_canonical_bytes_of(bytes, sizeof bytes, DFI_EXT_FORME_COUNT + 1u,
                                                       DFI_EXT_MOVE_COUNT, DFI_EXT_ITEM_COUNT,
                                                       DFI_EXT_ABILITY_COUNT, 0xFFu),
                        0u); /* counts beyond the tables are refused */
    }

    /* Team C formes (mechanics.md section 2, data/pokedex.ts at the pin). */
    {
        const uint32_t sneasler[6] = {80, 130, 60, 40, 80, 120};
        const uint32_t incineroar[6] = {95, 115, 90, 80, 90, 60};
        const uint32_t salamence[6] = {95, 135, 80, 110, 80, 100};
        const uint32_t salamencemega[6] = {95, 145, 130, 120, 90, 120};
        const uint32_t indeedeef[6] = {70, 55, 65, 95, 105, 85};
        const uint32_t kingambit[6] = {100, 135, 120, 60, 85, 50};
        const uint32_t basculegion[6] = {120, 112, 65, 80, 75, 78};
        check_forme(&t, DFI_FORME_SNEASLER, DFI_TYPE_FIGHTING, DFI_TYPE_POISON, sneasler, 430u, DFI_ABILITY_UNBURDEN,
                    DFI_GENDER_RULE_ANY, DFI_ITEM_WHITEHERB, "sneasler");
        check_forme(&t, DFI_FORME_INCINEROAR, DFI_TYPE_FIRE, DFI_TYPE_DARK, incineroar, 830u, DFI_ABILITY_INTIMIDATE,
                    DFI_GENDER_RULE_ANY, DFI_ITEM_SITRUSBERRY, "incineroar");
        check_forme(&t, DFI_FORME_SALAMENCE, DFI_TYPE_DRAGON, DFI_TYPE_FLYING, salamence, 1026u,
                    DFI_ABILITY_INTIMIDATE, DFI_GENDER_RULE_ANY, DFI_ITEM_SALAMENCITE, "salamence");
        check_forme(&t, DFI_FORME_SALAMENCEMEGA, DFI_TYPE_DRAGON, DFI_TYPE_FLYING, salamencemega, 1126u,
                    DFI_ABILITY_AERILATE, DFI_GENDER_RULE_ANY, DFI_ITEM_SALAMENCITE, "salamencemega");
        check_forme(&t, DFI_FORME_INDEEDEEF, DFI_TYPE_PSYCHIC, DFI_TYPE_NORMAL, indeedeef, 280u,
                    DFI_ABILITY_PSYCHICSURGE, DFI_GENDER_RULE_FEMALE, DFI_ITEM_ROCKYHELMET, "indeedeef");
        check_forme(&t, DFI_FORME_KINGAMBIT, DFI_TYPE_DARK, DFI_TYPE_STEEL, kingambit, 1200u, DFI_ABILITY_DEFIANT,
                    DFI_GENDER_RULE_ANY, DFI_ITEM_CHOPLEBERRY, "kingambit");
        check_forme(&t, DFI_FORME_BASCULEGION, DFI_TYPE_WATER, DFI_TYPE_GHOST, basculegion, 1100u,
                    DFI_ABILITY_ADAPTABILITY, DFI_GENDER_RULE_MALE, DFI_ITEM_CHOICESCARF, "basculegion");

        /* Mega links: only Salamence, through Salamencite. */
        const dfi_forme_data *s = &dfi_ext_formes[DFI_FORME_SALAMENCE];
        const dfi_forme_data *m = &dfi_ext_formes[DFI_FORME_SALAMENCEMEGA];
        DF_CHECK(&t, s->is_mega == 0u && s->mega_forme == DFI_FORME_SALAMENCEMEGA && s->mega_item == DFI_ITEM_SALAMENCITE &&
                         s->base_forme == DFI_FORME_SALAMENCE);
        DF_CHECK(&t, m->is_mega == 1u && m->base_forme == DFI_FORME_SALAMENCE && m->mega_item == DFI_ITEM_SALAMENCITE &&
                         m->set_move_count == 0u && m->dex_num == s->dex_num);
        DF_CHECK(&t, dfi_ext_items[DFI_ITEM_SALAMENCITE].mega_base == DFI_FORME_SALAMENCE &&
                         dfi_ext_items[DFI_ITEM_SALAMENCITE].mega_forme == DFI_FORME_SALAMENCEMEGA);
        uint32_t others = 0u;
        for (uint32_t i = DFI_FORME_COUNT; i < DFI_EXT_FORME_COUNT; ++i) {
            const dfi_forme_data *x = &dfi_ext_formes[i];
            if (i != DFI_FORME_SALAMENCE && i != DFI_FORME_SALAMENCEMEGA) {
                others += x->is_mega != 0u || x->mega_forme != DFI_CLOSURE_NONE || x->mega_item != DFI_CLOSURE_NONE ||
                                  x->base_forme != i
                              ? 1u
                              : 0u;
            }
        }
        for (uint32_t i = DFI_ITEM_COUNT; i < DFI_EXT_ITEM_COUNT; ++i) {
            if (i != DFI_ITEM_SALAMENCITE) {
                others += dfi_ext_items[i].mega_base != DFI_CLOSURE_NONE ||
                                  dfi_ext_items[i].mega_forme != DFI_CLOSURE_NONE
                              ? 1u
                              : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, others, 0u);
    }

    /* The set moves, in the order of team-c.txt. */
    {
        const uint32_t sneasler[4] = {DFI_MOVE_CLOSECOMBAT, DFI_MOVE_DIRECLAW, DFI_MOVE_PROTECT, DFI_MOVE_FAKEOUT};
        const uint32_t incineroar[4] = {DFI_MOVE_FAKEOUT, DFI_MOVE_FLAREBLITZ, DFI_MOVE_PARTINGSHOT,
                                        DFI_MOVE_DARKESTLARIAT};
        const uint32_t salamence[4] = {DFI_MOVE_PROTECT, DFI_MOVE_HYPERVOICE, DFI_MOVE_DRACOMETEOR, DFI_MOVE_TAILWIND};
        const uint32_t indeedeef[4] = {DFI_MOVE_FOLLOWME, DFI_MOVE_TRICKROOM, DFI_MOVE_HELPINGHAND, DFI_MOVE_PSYCHIC};
        const uint32_t kingambit[4] = {DFI_MOVE_KOWTOWCLEAVE, DFI_MOVE_SUCKERPUNCH, DFI_MOVE_IRONHEAD, DFI_MOVE_PROTECT};
        const uint32_t basculegion[4] = {DFI_MOVE_WAVECRASH, DFI_MOVE_LASTRESPECTS, DFI_MOVE_FLIPTURN, DFI_MOVE_AQUAJET};
        check_set_moves(&t, DFI_FORME_SNEASLER, sneasler, "sneasler");
        check_set_moves(&t, DFI_FORME_INCINEROAR, incineroar, "incineroar");
        check_set_moves(&t, DFI_FORME_SALAMENCE, salamence, "salamence");
        check_set_moves(&t, DFI_FORME_INDEEDEEF, indeedeef, "indeedeef");
        check_set_moves(&t, DFI_FORME_KINGAMBIT, kingambit, "kingambit");
        check_set_moves(&t, DFI_FORME_BASCULEGION, basculegion, "basculegion");
    }

    /* Stat lines of the sets at the pin (Champions spreadModify). */
    {
        uint32_t bad = 0u;
        for (size_t i = 0u; i < sizeof sets / sizeof sets[0]; ++i) {
            const dfi_forme_data *f = &dfi_ext_formes[sets[i].forme];
            for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
                uint16_t v = 0u;
                const bool ok = dfi_champions_stat(k, f->base[k], sets[i].sp[k], sets[i].nature, &v);
                if (!ok || v != sets[i].expected[k]) {
                    fprintf(stderr, "  set %zu stat %u: got %u want %u\n", i, k, v, sets[i].expected[k]);
                    ++bad;
                }
            }
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
    }

    /* Team C moves (data/moves.ts with the champions overrides at the pin;
     * PP after the Champions rule; mechanics.md section 3). */
    {
        const uint32_t CP = DFI_MOVE_FLAG_CONTACT | DFI_MOVE_FLAG_PROTECT;
        const uint32_t P = DFI_MOVE_FLAG_PROTECT;
        check_move(&t, DFI_MOVE_DIRECLAW, DFI_TYPE_POISON, DFI_CATEGORY_PHYSICAL, 80, 100, 15, 16, 0, 1, CP,
                   DFI_SPECIAL_NONE, "direclaw");
        check_move(&t, DFI_MOVE_FLAREBLITZ, DFI_TYPE_FIRE, DFI_CATEGORY_PHYSICAL, 120, 100, 15, 16, 0, 1,
                   CP | DFI_MOVE_FLAG_DEFROST, DFI_SPECIAL_NONE, "flareblitz");
        check_move(&t, DFI_MOVE_DARKESTLARIAT, DFI_TYPE_DARK, DFI_CATEGORY_PHYSICAL, 85, 100, 10, 12, 0, 1, CP,
                   DFI_SPECIAL_DARKEST_LARIAT, "darkestlariat");
        check_move(&t, DFI_MOVE_HYPERVOICE, DFI_TYPE_NORMAL, DFI_CATEGORY_SPECIAL, 90, 100, 10, 12, 0, 7, P,
                   DFI_SPECIAL_NONE, "hypervoice");
        check_move(&t, DFI_MOVE_DRACOMETEOR, DFI_TYPE_DRAGON, DFI_CATEGORY_SPECIAL, 130, 90, 5, 8, 0, 1, P,
                   DFI_SPECIAL_NONE, "dracometeor");
        check_move(&t, DFI_MOVE_FOLLOWME, DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0, 0, 20, 20, 2, 6, 0u,
                   DFI_SPECIAL_FOLLOW_ME, "followme");
        check_move(&t, DFI_MOVE_HELPINGHAND, DFI_TYPE_NORMAL, DFI_CATEGORY_STATUS, 0, 0, 20, 20, 5, 3, 0u,
                   DFI_SPECIAL_HELPING_HAND, "helpinghand");
        check_move(&t, DFI_MOVE_KOWTOWCLEAVE, DFI_TYPE_DARK, DFI_CATEGORY_PHYSICAL, 85, 0, 10, 12, 0, 1, CP,
                   DFI_SPECIAL_NONE, "kowtowcleave");
        check_move(&t, DFI_MOVE_SUCKERPUNCH, DFI_TYPE_DARK, DFI_CATEGORY_PHYSICAL, 70, 100, 5, 8, 1, 1, CP,
                   DFI_SPECIAL_SUCKER_PUNCH, "suckerpunch");
        check_move(&t, DFI_MOVE_LASTRESPECTS, DFI_TYPE_GHOST, DFI_CATEGORY_PHYSICAL, 50, 100, 10, 12, 0, 1, P,
                   DFI_SPECIAL_LAST_RESPECTS, "lastrespects");
        check_move(&t, DFI_MOVE_WAVECRASH, DFI_TYPE_WATER, DFI_CATEGORY_PHYSICAL, 120, 100, 10, 12, 0, 1, CP,
                   DFI_SPECIAL_NONE, "wavecrash");
        check_move(&t, DFI_MOVE_AQUAJET, DFI_TYPE_WATER, DFI_CATEGORY_PHYSICAL, 40, 100, 20, 20, 1, 1, CP,
                   DFI_SPECIAL_NONE, "aquajet");
        check_move(&t, DFI_MOVE_FLIPTURN, DFI_TYPE_WATER, DFI_CATEGORY_PHYSICAL, 60, 100, 20, 20, 0, 1,
                   CP | DFI_MOVE_FLAG_SELF_SWITCH, DFI_SPECIAL_NONE, "flipturn");

        /* Secondary effects, recoil and self drops. */
        const dfi_move_data *m = &dfi_ext_moves[DFI_MOVE_DIRECLAW]; /* champions override: 30, not 50 */
        DF_CHECK(&t, m->sec_chance == 30u && m->sec_kind == DFI_SECONDARY_STATUS_PICK && m->sec_param == 0u);
        m = &dfi_ext_moves[DFI_MOVE_FLAREBLITZ];
        DF_CHECK(&t, m->sec_chance == 10u && m->sec_kind == DFI_SECONDARY_STATUS && m->sec_param == DFI_STATUS_BRN &&
                         m->recoil[0] == 33u && m->recoil[1] == 100u);
        m = &dfi_ext_moves[DFI_MOVE_WAVECRASH];
        DF_CHECK(&t, m->recoil[0] == 33u && m->recoil[1] == 100u && m->sec_chance == 0u);
        m = &dfi_ext_moves[DFI_MOVE_DRACOMETEOR];
        DF_CHECK(&t, m->boost_role == DFI_BOOST_ROLE_SELF_AFTER_HIT && m->boosts[DFI_STAGE_SPA] == 4u &&
                         m->boosts[DFI_STAGE_ATK] == 6u && m->sec_chance == 0u);
        m = &dfi_ext_moves[DFI_MOVE_KOWTOWCLEAVE];
        DF_CHECK(&t, m->sec_chance == 0u && m->boost_role == DFI_BOOST_ROLE_NONE && m->recoil[1] == 0u);
    }

    /* New encodings keep clear of the closure's. */
    DF_CHECK_EQ_U64(&t, DFI_STATUS_PSN, 5u);
    DF_CHECK_EQ_U64(&t, DFI_IMMUNE_PSN, 16u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_FLAG_DEFROST, 128u);
    DF_CHECK_EQ_U64(&t, DFI_SECONDARY_STATUS_PICK, 4u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_DARKEST_LARIAT, DFI_SPECIAL_STRUGGLE + 1u);

    return df_test_end(&t);
}
