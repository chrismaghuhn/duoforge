#include "state/closure_member.h"

#include "core/arith.h"
#include "data/formulas.h"
#include "data/pool_tables.h"


const dfi_pivot_move dfi_pivot_moves[DFI_PIVOT_MOVE_COUNT] = {
    {DFI_SWITCH_FLIP_TURN, DFI_MOVE_FLIPTURN},
    {DFI_SWITCH_UTURN, DFI_MOVE_UTURN},
};

const dfi_pivot_move *dfi_pivot_of_move(uint32_t move)
{
    for (uint32_t i = 0u; i < DFI_PIVOT_MOVE_COUNT; ++i) {
        if (dfi_pivot_moves[i].move == move) {
            return &dfi_pivot_moves[i];
        }
    }
    return NULL;
}

const dfi_pivot_move *dfi_pivot_of_flag(uint32_t flag)
{
    for (uint32_t i = 0u; i < DFI_PIVOT_MOVE_COUNT; ++i) {
        if (dfi_pivot_moves[i].flag == flag) {
            return &dfi_pivot_moves[i];
        }
    }
    return NULL;
}

dfi_kind_limits dfi_kind_limits_of(uint32_t data_kind)
{
    const bool pool = data_kind == DUOFORGE_DATA_KIND_POOL || data_kind == DUOFORGE_DATA_KIND_POOL_DEV;
    const bool team_c = data_kind == DUOFORGE_DATA_KIND_TEAM_C || data_kind == DUOFORGE_DATA_KIND_TEAM_C_DEV;
    /* The values of Team C's mechanics are valid under the TEAM_C and POOL kinds (the pool has them all). */
    const bool extended = team_c || pool;
    dfi_kind_limits lim;
    lim.forme_count = pool ? DFI_POOL_FORME_COUNT : team_c ? DFI_EXT_FORME_COUNT : DFI_FORME_COUNT;
    lim.move_count = pool ? DFI_POOL_MOVE_COUNT : team_c ? DFI_EXT_MOVE_COUNT : DFI_MOVE_COUNT;
    lim.item_count = pool ? DFI_POOL_ITEM_COUNT : team_c ? DFI_EXT_ITEM_COUNT : DFI_ITEM_COUNT;
    lim.ability_count = pool ? DFI_POOL_ABILITY_COUNT : team_c ? DFI_EXT_ABILITY_COUNT : DFI_ABILITY_COUNT;
    /* Flip Turn's flag is in the extended tables (Team C), U-turn's only in the pool's. */
    lim.switch_flag_max = pool ? DFI_SWITCH_UTURN : team_c ? DFI_SWITCH_FLIP_TURN : DFI_SWITCH_FAINTED;
    lim.status_max = extended ? DFI_STATUS_PSN : DFI_STATUS_SLP;
    lim.terrain_max = extended ? DFI_TERRAIN_PSYCHIC : DFI_TERRAIN_GRASSY;
    lim.vol_flags_mask = extended ? (DFI_VOL_FLAGS_MAX | DFI_VOL_FOLLOW_ME | DFI_VOL_HELPING_HAND | DFI_VOL_UNBURDEN |
                                     DFI_VOL_CHOICE_LOCK | DFI_VOL_NEWLY_SWITCHED)
                                  : DFI_VOL_FLAGS_MAX;
    lim.pool_rules = pool;
    lim.dev = data_kind == DUOFORGE_DATA_KIND_CLOSURE_DEV || data_kind == DUOFORGE_DATA_KIND_TEAM_C_DEV ||
              data_kind == DUOFORGE_DATA_KIND_POOL_DEV;
    return lim;
}

bool dfi_gender_legal(uint32_t gender_rule, uint32_t gender)
{
    switch (gender_rule) {
    case DFI_GENDER_RULE_ANY:
        return gender == DFI_GENDER_MALE || gender == DFI_GENDER_FEMALE;
    case DFI_GENDER_RULE_MALE:
        return gender == DFI_GENDER_MALE;
    case DFI_GENDER_RULE_FEMALE:
        return gender == DFI_GENDER_FEMALE;
    case DFI_GENDER_RULE_NONE:
        return gender == DFI_GENDER_NONE;
    default:
        return false;
    }
}

/* True iff move is one of the forme's set moves. */
static bool dfi_in_set(const dfi_forme_data *f, uint32_t move)
{
    for (uint32_t k = 0u; k < f->set_move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (f->set_moves[k] == move) {
            return true;
        }
    }
    return false;
}

/* True iff the forme learns the pool move (decision 0015 section 2). */
static bool dfi_pool_learns(uint32_t forme, uint32_t move)
{
    if (forme >= DFI_POOL_FORME_COUNT || move >= DFI_POOL_MOVE_COUNT) {
        return false;
    }
    return (((uint32_t)dfi_pool_forme_legal[forme].learnable[move / 8u] >> (move % 8u)) & 1u) != 0u;
}

/* True iff the ability (an id) is one of the forme's legal abilities. */
static bool dfi_pool_ability_legal(uint32_t forme, uint32_t ability)
{
    const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
    for (uint32_t k = 0u; k < l->ability_count && k < DFI_POOL_FORME_ABILITIES_MAX; ++k) {
        if (l->abilities[k] == ability) {
            return true;
        }
    }
    return false;
}

bool dfi_forme_setup_legal(const dfi_kind_limits *lim, uint32_t species)
{
    return species < lim->forme_count && dfi_pool_formes[species].is_mega == 0u;
}

bool dfi_forme_move_legal(const dfi_kind_limits *lim, uint32_t species, uint32_t move)
{
    if (move >= lim->move_count) {
        return false;
    }
    return lim->pool_rules ? dfi_pool_learns(species, move) : dfi_in_set(&dfi_pool_formes[species], move);
}

bool dfi_forme_ability_legal(const dfi_kind_limits *lim, uint32_t species, uint32_t ability)
{
    if (ability == 0u) {
        return lim->dev;
    }
    if (ability > lim->ability_count) {
        return false;
    }
    return lim->pool_rules ? dfi_pool_ability_legal(species, ability - 1u)
                           : ability == (uint32_t)dfi_pool_formes[species].ability + 1u;
}

uint32_t dfi_forme_stone(uint32_t species)
{
    const dfi_forme_data *f = &dfi_pool_formes[species];
    return f->mega_forme != DFI_CLOSURE_NONE ? (uint32_t)f->mega_item : (uint32_t)DFI_CLOSURE_NONE;
}

bool dfi_stat_points_valid(const uint32_t *sp)
{
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
        if (sp[i] > DUOFORGE_STAT_POINTS_MAX) {
            return false;
        }
        total += sp[i]; /* at most 6 * 32 */
    }
    return total <= DUOFORGE_STAT_POINTS_TOTAL_MAX;
}

bool dfi_closure_member_setup_valid(const dfi_kind_limits *lim, const duoforge_member_setup *m)
{
    if (m->species_id >= lim->forme_count) {
        return false;
    }
    const dfi_forme_data *f = &dfi_pool_formes[m->species_id];
    if (f->is_mega != 0u) {
        return false; /* a Mega forme is reached in battle, never set up */
    }
    if (m->hp_max != 0u || m->mega_capable != 0u) {
        return false; /* derived by the engine */
    }
    if (m->move_count < 1u || m->move_count > DUOFORGE_MAX_MOVE_SLOTS) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        const duoforge_move_setup *mv = &m->moves[k];
        if (k >= m->move_count) {
            if (mv->move_id != 0u || mv->pp_max != 0u) {
                return false;
            }
            continue;
        }
        if (mv->pp_max != 0u || !dfi_forme_move_legal(lim, m->species_id, mv->move_id)) {
            return false;
        }
        for (uint32_t j = 0u; j < k; ++j) {
            if (m->moves[j].move_id == mv->move_id) {
                return false;
            }
        }
    }
    if (!dfi_gender_legal(f->gender_rule, m->gender)) {
        return false;
    }
    if (m->nature >= DFI_NATURE_COUNT || !dfi_stat_points_valid(m->stat_points)) {
        return false;
    }
    if (!dfi_forme_ability_legal(lim, m->species_id, m->ability)) {
        return false;
    }
    if (m->item > lim->item_count) {
        return false;
    }
    return true;
}

bool dfi_closure_side_clauses_hold(const duoforge_side_setup *side)
{
    for (uint32_t a = 0u; a < side->member_count && a < DUOFORGE_MAX_ROSTER; ++a) {
        const duoforge_member_setup *x = &side->members[a];
        for (uint32_t b = 0u; b < a; ++b) {
            const duoforge_member_setup *y = &side->members[b];
            /* Species Clause: one member per national dex number. */
            if (dfi_pool_formes[x->species_id].dex_num == dfi_pool_formes[y->species_id].dex_num) {
                return false;
            }
            /* Item Clause: no item twice. */
            if (x->item != 0u && x->item == y->item) {
                return false;
            }
        }
    }
    return true;
}

/* True iff the member's item is the stone of its base forme. */
static bool dfi_holds_own_stone(uint32_t species, uint32_t item)
{
    const uint32_t stone = dfi_forme_stone(species);
    return item != 0u && stone != DFI_CLOSURE_NONE && stone + 1u == item;
}

bool dfi_manifest_move(const dfi_support_manifest *s, uint32_t move)
{
    return move < DFI_POOL_MOVE_COUNT && s->moves[move] != 0u;
}

bool dfi_manifest_ability(const dfi_support_manifest *s, uint32_t ability)
{
    return ability < DFI_POOL_ABILITY_COUNT && s->abilities[ability] != 0u;
}

bool dfi_manifest_item(const dfi_support_manifest *s, uint32_t item)
{
    return item < DFI_POOL_ITEM_COUNT && s->items[item] != 0u;
}

bool dfi_manifest_mega(const dfi_support_manifest *s, uint32_t species)
{
    if (species >= DFI_POOL_FORME_COUNT || dfi_pool_formes[species].mega_forme == DFI_CLOSURE_NONE) {
        return false;
    }
    /* Mega Evolution, and the ability the Mega forme brings. */
    const dfi_forme_data *mega = &dfi_pool_formes[dfi_pool_formes[species].mega_forme];
    return s->mega_evolution != 0u && dfi_manifest_ability(s, mega->ability);
}

static bool dfi_member_supported(const dfi_support_manifest *s, const duoforge_member_setup *m)
{
    if (m->ability != 0u && !dfi_manifest_ability(s, m->ability - 1u)) {
        return false;
    }
    if (m->item != 0u && !dfi_manifest_item(s, m->item - 1u)) {
        return false;
    }
    if (dfi_holds_own_stone(m->species_id, m->item) && !dfi_manifest_mega(s, m->species_id)) {
        return false;
    }
    for (uint32_t k = 0u; k < m->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_manifest_move(s, m->moves[k].move_id)) {
            return false;
        }
    }
    return true;
}

bool dfi_closure_setup_supported(const dfi_support_manifest *manifest, const duoforge_battle_setup *setup)
{
    /* Every battle needs the turn core (with Struggle, reachable by any
     * team). Switching and fainting are checked when a step needs them. */
    if (manifest->turn_core == 0u) {
        return false;
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const duoforge_side_setup *side = &setup->sides[s];
        for (uint32_t m = 0u; m < side->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            if (!dfi_member_supported(manifest, &side->members[m])) {
                return false;
            }
        }
    }
    return true;
}

bool dfi_closure_battle_supported(const dfi_support_manifest *manifest, const struct duoforge_battle *b)
{
    if (manifest->turn_core == 0u) {
        return false;
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const dfi_side *side = &b->sides[s];
        for (uint32_t m = 0u; m < side->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *mem = &side->members[m];
            if (mem->ability != 0u && !dfi_manifest_ability(manifest, mem->ability - 1u)) {
                return false;
            }
            if (mem->item != 0u && !dfi_manifest_item(manifest, mem->item - 1u)) {
                return false;
            }
            if (mem->mega_capable != 0u && !dfi_manifest_mega(manifest, mem->species_id)) {
                return false;
            }
            for (uint32_t k = 0u; k < mem->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                if (!dfi_manifest_move(manifest, mem->moves[k].move_id)) {
                    return false;
                }
            }
        }
    }
    return true;
}

/* hp_max from the base forme and stats[] from the current forme. */
static bool dfi_derive_stats(uint32_t species, uint32_t is_mega, uint32_t nature, const uint8_t *sp,
                             uint16_t *hp_max, uint16_t *stats)
{
    const dfi_forme_data *base = &dfi_pool_formes[species];
    const dfi_forme_data *cur = base;
    if (is_mega != 0u) {
        if (base->mega_forme == DFI_CLOSURE_NONE) {
            return false;
        }
        cur = &dfi_pool_formes[base->mega_forme];
    }
    if (!dfi_champions_stat(DFI_STAT_HP, base->base[DFI_STAT_HP], sp[DFI_STAT_HP], nature, hp_max)) {
        return false;
    }
    for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
        const uint32_t stat = i + 1u;
        if (!dfi_champions_stat(stat, cur->base[stat], sp[stat], nature, &stats[i])) {
            return false;
        }
    }
    return true;
}

static bool dfi_derive_pp(uint32_t move, uint8_t *out)
{
    const dfi_move_data *mv = &dfi_pool_moves[move];
    return dfi_champions_pp_max(mv->pp_base, (mv->flags & DFI_MOVE_FLAG_NO_PP_BOOSTS) != 0u, out);
}

bool dfi_closure_member_init(const duoforge_member_setup *src, dfi_member *dst)
{
    if (!dfi_u32_to_u16(src->species_id, &dst->species_id) || !dfi_u32_to_u8(src->move_count, &dst->move_count) ||
        !dfi_u32_to_u8(src->gender, &dst->gender) || !dfi_u32_to_u8(src->nature, &dst->nature) ||
        !dfi_u32_to_u8(src->ability, &dst->ability) || !dfi_u32_to_u8(src->item, &dst->item)) {
        return false;
    }
    for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
        if (!dfi_u32_to_u8(src->stat_points[i], &dst->stat_points[i])) {
            return false;
        }
    }
    if (!dfi_derive_stats(src->species_id, 0u, src->nature, dst->stat_points, &dst->hp_max, dst->stats)) {
        return false;
    }
    dst->hp = dst->hp_max;
    dst->mega_capable = dfi_holds_own_stone(src->species_id, src->item) ? 1u : 0u;
    for (uint32_t k = 0u; k < dst->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_u32_to_u16(src->moves[k].move_id, &dst->moves[k].move_id) ||
            !dfi_derive_pp(src->moves[k].move_id, &dst->moves[k].pp_max)) {
            return false;
        }
        dst->moves[k].pp = dst->moves[k].pp_max;
    }
    return true;
}

bool dfi_closure_member_mega_evolve(dfi_member *m)
{
    const dfi_forme_data *base = &dfi_pool_formes[m->species_id];
    if (m->is_mega != 0u || m->mega_capable == 0u || base->mega_forme == DFI_CLOSURE_NONE) {
        return false;
    }
    uint16_t hp_max = 0u;
    uint16_t stats[DFI_MEMBER_STAT_COUNT] = {0};
    if (!dfi_derive_stats(m->species_id, 1u, m->nature, m->stat_points, &hp_max, stats) || hp_max != m->hp_max) {
        return false;
    }
    m->is_mega = 1u;
    for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
        m->stats[i] = stats[i];
    }
    m->ability = (uint8_t)((uint32_t)dfi_pool_formes[base->mega_forme].ability + 1u); /* wide-operands-reviewed: < 26 */
    return true;
}

bool dfi_closure_member_ranges(const dfi_kind_limits *lim, const dfi_member *m)
{
    const dfi_forme_data *base = &dfi_pool_formes[m->species_id]; /* below the context species count */
    if (base->is_mega != 0u || !dfi_gender_legal(base->gender_rule, m->gender)) {
        return false;
    }
    if (m->nature >= DFI_NATURE_COUNT) {
        return false;
    }
    uint32_t sp[DFI_STAT_POINT_COUNT];
    for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
        sp[i] = m->stat_points[i];
    }
    if (!dfi_stat_points_valid(sp)) {
        return false;
    }
    if (m->is_mega > 1u || m->item > lim->item_count || m->item_consumed > 1u) {
        return false;
    }
    if (m->item_consumed != 0u && m->item == 0u) {
        return false;
    }
    const bool stone = dfi_holds_own_stone(m->species_id, m->item);
    if (m->mega_capable != (stone ? 1u : 0u) || (m->is_mega != 0u && !stone)) {
        return false;
    }
    /* The current ability: the Mega forme's after Mega Evolution. */
    if (m->is_mega != 0u) {
        if (m->ability != (uint32_t)dfi_pool_formes[base->mega_forme].ability + 1u) {
            return false;
        }
    } else if (!dfi_forme_ability_legal(lim, m->species_id, m->ability)) {
        return false;
    }
    /* Sleep and freeze carry a counter 1..3 (Champions: sleep lasts
     * sample([2, 3, 3]), freeze at most 3); nothing else has one. Poison
     * exists under the TEAM_C kinds only. Whether a fainted member may still
     * have a status depends on the boundary (dfi_check_side). */
    const uint32_t status = m->status;
    if (status > lim->status_max) {
        return false;
    }
    if (status == DFI_STATUS_SLP || status == DFI_STATUS_FRZ) {
        return m->status_counter >= 1u && m->status_counter <= 3u;
    }
    return m->status_counter == 0u;
}

bool dfi_closure_member_valid(const dfi_kind_limits *lim, const dfi_member *m)
{
    if (!dfi_closure_member_ranges(lim, m)) {
        return false;
    }
    uint16_t hp_max = 0u;
    uint16_t stats[DFI_MEMBER_STAT_COUNT] = {0};
    if (!dfi_derive_stats(m->species_id, m->is_mega, m->nature, m->stat_points, &hp_max, stats) ||
        hp_max != m->hp_max) {
        return false;
    }
    for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
        if (stats[i] != m->stats[i]) {
            return false;
        }
    }
    for (uint32_t k = 0u; k < m->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        const uint32_t move = m->moves[k].move_id;
        uint8_t pp_max = 0u;
        if (!dfi_forme_move_legal(lim, m->species_id, move) || !dfi_derive_pp(move, &pp_max) ||
            pp_max != m->moves[k].pp_max) {
            return false;
        }
        for (uint32_t j = 0u; j < k; ++j) {
            if (m->moves[j].move_id == move) {
                return false;
            }
        }
    }
    return true;
}
