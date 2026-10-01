#include "support/team_c.h"

#include <string.h>

#include "data/extended_tables.h"

const duoforge_context_config df_config_team_c = {DUOFORGE_DATA_KIND_TEAM_C, 6u, 4u, 0u, 0u, NULL};
const duoforge_context_config df_config_team_c_dev = {DUOFORGE_DATA_KIND_TEAM_C_DEV, 6u, 4u, 0u, 0u, NULL};

typedef struct df_set_c {
    uint32_t species, gender, nature, sp[6], ability, item, moves[4];
} df_set_c;

/* docs/research/third-team/team-c.txt; ability and item are table ids. */
static const df_set_c df_team_c[6] = {
    {DFI_FORME_SNEASLER, DUOFORGE_GENDER_MALE, DFI_NATURE_ADAMANT, {2u, 32u, 0u, 0u, 0u, 32u}, DFI_ABILITY_UNBURDEN,
     DFI_ITEM_WHITEHERB, {DFI_MOVE_CLOSECOMBAT, DFI_MOVE_DIRECLAW, DFI_MOVE_PROTECT, DFI_MOVE_FAKEOUT}},
    {DFI_FORME_INCINEROAR, DUOFORGE_GENDER_MALE, DFI_NATURE_CAREFUL, {32u, 0u, 14u, 0u, 20u, 0u},
     DFI_ABILITY_INTIMIDATE, DFI_ITEM_SITRUSBERRY,
     {DFI_MOVE_FAKEOUT, DFI_MOVE_FLAREBLITZ, DFI_MOVE_PARTINGSHOT, DFI_MOVE_DARKESTLARIAT}},
    {DFI_FORME_SALAMENCE, DUOFORGE_GENDER_MALE, DFI_NATURE_TIMID, {2u, 0u, 0u, 32u, 0u, 32u}, DFI_ABILITY_INTIMIDATE,
     DFI_ITEM_SALAMENCITE, {DFI_MOVE_PROTECT, DFI_MOVE_HYPERVOICE, DFI_MOVE_DRACOMETEOR, DFI_MOVE_TAILWIND}},
    {DFI_FORME_INDEEDEEF, DUOFORGE_GENDER_FEMALE, DFI_NATURE_RELAXED, {32u, 0u, 32u, 0u, 2u, 0u},
     DFI_ABILITY_PSYCHICSURGE, DFI_ITEM_ROCKYHELMET,
     {DFI_MOVE_FOLLOWME, DFI_MOVE_TRICKROOM, DFI_MOVE_HELPINGHAND, DFI_MOVE_PSYCHIC}},
    {DFI_FORME_KINGAMBIT, DUOFORGE_GENDER_MALE, DFI_NATURE_ADAMANT, {32u, 32u, 0u, 0u, 2u, 0u}, DFI_ABILITY_DEFIANT,
     DFI_ITEM_CHOPLEBERRY, {DFI_MOVE_KOWTOWCLEAVE, DFI_MOVE_SUCKERPUNCH, DFI_MOVE_IRONHEAD, DFI_MOVE_PROTECT}},
    {DFI_FORME_BASCULEGION, DUOFORGE_GENDER_MALE, DFI_NATURE_JOLLY, {2u, 32u, 0u, 0u, 0u, 32u},
     DFI_ABILITY_ADAPTABILITY, DFI_ITEM_CHOICESCARF,
     {DFI_MOVE_WAVECRASH, DFI_MOVE_LASTRESPECTS, DFI_MOVE_FLIPTURN, DFI_MOVE_AQUAJET}},
};

void df_put_team_c(duoforge_side_setup *side)
{
    memset(side, 0, sizeof *side);
    side->member_count = 6u;
    for (uint32_t m = 0u; m < 6u; ++m) {
        duoforge_member_setup *dst = &side->members[m];
        dst->species_id = df_team_c[m].species;
        dst->gender = df_team_c[m].gender;
        dst->nature = df_team_c[m].nature;
        for (uint32_t i = 0u; i < 6u; ++i) {
            dst->stat_points[i] = df_team_c[m].sp[i];
        }
        dst->ability = df_team_c[m].ability + 1u;
        dst->item = df_team_c[m].item + 1u;
        dst->move_count = 4u;
        for (uint32_t k = 0u; k < 4u; ++k) {
            dst->moves[k].move_id = df_team_c[m].moves[k];
        }
    }
}
