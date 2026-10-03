/*
 * duoforge.state.mega_by_stone (white-box): step G23-A, the Mega of a member is found from (base forme, stone).
 *
 * Every Mega forme row of the POOL tables is reached from its base forme holding its own stone and from no other
 * pair: a member built from the setup is Mega capable, evolves into exactly that forme (the stats and the ability of
 * the forme's row, the HP of the base forme), and the evolved member passes the whole member check. The pairs that
 * the single link of a base forme could not give are among them: the second Megas of Absol, Charizard, Garchomp,
 * Lucario and Raichu, and Meowsticite for both Meowstic formes. A member that holds the stone of another forme is
 * not Mega capable and does not evolve.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"

/* A legal setup of the base forme holding `item` (1 + the id): the first legal move, ability and gender. */
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

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.mega_by_stone");
    const dfi_kind_limits lim = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
    uint32_t megas = 0u;
    uint32_t second = 0u;
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
        const dfi_pool_forme_data *mega = &dfi_pool_formes[f];
        if (mega->is_mega == 0u) {
            continue;
        }
        megas += 1u;
        const uint32_t base = mega->base_forme;
        const dfi_pool_forme_data *bf = &dfi_pool_formes[base];
        second += bf->mega_forme != f ? 1u : 0u;
        const uint32_t item = 1u + mega->mega_item;
        duoforge_member_setup setup;
        if (!DF_CHECK(&t, build_setup(&lim, base, item, &setup))) {
            fprintf(stderr, "  no legal setup of %s with %s\n", dfi_pool_forme_names[base], dfi_pool_item_names[mega->mega_item]);
            continue;
        }
        dfi_member m;
        memset(&m, 0, sizeof m);
        DF_CHECK(&t, dfi_closure_member_init(&setup, &m));
        DF_CHECK(&t, m.mega_capable == 1u && m.is_mega == 0u);
        DF_CHECK(&t, dfi_closure_member_valid(&lim, &m));
        DF_CHECK(&t, dfi_closure_member_mega_evolve(&m));
        DF_CHECK(&t, m.is_mega == 1u && m.item == item);
        DF_CHECK_EQ_U64(&t, m.ability, 1u + (uint32_t)mega->ability); /* the Mega forme's ability */
        for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
            uint16_t want = 0u;
            DF_CHECK(&t, dfi_champions_stat(i + 1u, mega->base[i + 1u], setup.stat_points[i + 1u], setup.nature, &want));
            DF_CHECK_EQ_U64(&t, m.stats[i], want); /* the stats of the Mega forme that this stone reaches */
        }
        uint16_t hp = 0u;
        DF_CHECK(&t, dfi_champions_stat(DFI_STAT_HP, bf->base[DFI_STAT_HP], setup.stat_points[0], setup.nature, &hp));
        DF_CHECK_EQ_U64(&t, m.hp_max, hp); /* the HP of the base forme */
        DF_CHECK(&t, dfi_closure_member_valid(&lim, &m));
        DF_CHECK(&t, !dfi_closure_member_mega_evolve(&m)); /* once only */
        /* The Mega of another base forme's stone is no Mega of this one. */
        for (uint32_t other = 0u; other < DFI_POOL_FORME_COUNT; ++other) {
            if (dfi_pool_formes[other].is_mega == 0u && other != base && dfi_pool_formes[other].mega_item != mega->mega_item) {
                DF_CHECK(&t, dfi_mega_of(other, item) != f);
            }
        }
    }
    DF_CHECK(&t, megas > 50u && second == 5u);
    /* A holder of a stone that is not its own does not evolve (Charizard with Salamencite, Garchomp with Charizardite X). */
    const uint32_t wrong[2][2] = {{DFI_FORME_CHARIZARD, DFI_ITEM_SALAMENCITE}, {DFI_FORME_GARCHOMP, DFI_ITEM_CHARIZARDITEX}};
    for (uint32_t k = 0u; k < 2u; ++k) {
        duoforge_member_setup setup;
        dfi_member m;
        memset(&m, 0, sizeof m);
        if (DF_CHECK(&t, build_setup(&lim, wrong[k][0], 1u + wrong[k][1], &setup)) && DF_CHECK(&t, dfi_closure_member_init(&setup, &m))) {
            DF_CHECK(&t, m.mega_capable == 0u && !dfi_closure_member_mega_evolve(&m));
        }
    }
    return df_test_end(&t);
}
