#include "state/closure_member.h"

#include "core/arith.h"
#include "data/extended_tables.h"
#include "data/formulas.h"


dfi_kind_limits dfi_kind_limits_of(uint32_t data_kind)
{
    const bool team_c = data_kind == DUOFORGE_DATA_KIND_TEAM_C || data_kind == DUOFORGE_DATA_KIND_TEAM_C_DEV;
    dfi_kind_limits lim;
    lim.forme_count = team_c ? DFI_EXT_FORME_COUNT : DFI_FORME_COUNT;
    lim.item_count = team_c ? DFI_EXT_ITEM_COUNT : DFI_ITEM_COUNT;
    lim.switch_flag_max = team_c ? DFI_SWITCH_FLIP_TURN : DFI_SWITCH_FAINTED;
    lim.status_max = team_c ? DFI_STATUS_PSN : DFI_STATUS_SLP;
    lim.vol_flags_mask = team_c ? (DFI_VOL_FLAGS_MAX | DFI_VOL_CHOICE_LOCK) : DFI_VOL_FLAGS_MAX;
    lim.dev = data_kind == DUOFORGE_DATA_KIND_CLOSURE_DEV || data_kind == DUOFORGE_DATA_KIND_TEAM_C_DEV;
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

static bool dfi_stat_points_valid(const uint32_t *sp)
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
    const dfi_forme_data *f = &dfi_ext_formes[m->species_id];
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
        if (mv->pp_max != 0u || !dfi_in_set(f, mv->move_id)) {
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
    const bool no_ability_ok = lim->dev && m->ability == 0u;
    if (!no_ability_ok && m->ability != (uint32_t)f->ability + 1u) {
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
            if (dfi_ext_formes[x->species_id].dex_num == dfi_ext_formes[y->species_id].dex_num) {
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
    const dfi_forme_data *f = &dfi_ext_formes[species];
    return item != 0u && f->mega_forme != DFI_CLOSURE_NONE && (uint32_t)f->mega_item + 1u == item;
}

static bool dfi_member_supported(const dfi_support_manifest *s, const duoforge_member_setup *m)
{
    if (m->ability != 0u && s->abilities[m->ability - 1u] == 0u) {
        return false;
    }
    if (m->item != 0u && s->items[m->item - 1u] == 0u) {
        return false;
    }
    if (dfi_holds_own_stone(m->species_id, m->item)) {
        /* Mega Evolution, and the ability the Mega forme brings. */
        const dfi_forme_data *mega = &dfi_ext_formes[dfi_ext_formes[m->species_id].mega_forme];
        if (s->mega_evolution == 0u || s->abilities[mega->ability] == 0u) {
            return false;
        }
    }
    for (uint32_t k = 0u; k < m->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (s->moves[m->moves[k].move_id] == 0u) {
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
            if (mem->ability != 0u && manifest->abilities[mem->ability - 1u] == 0u) {
                return false;
            }
            if (mem->item != 0u && manifest->items[mem->item - 1u] == 0u) {
                return false;
            }
            if (mem->mega_capable != 0u) {
                const dfi_forme_data *mega = &dfi_ext_formes[dfi_ext_formes[mem->species_id].mega_forme];
                if (manifest->mega_evolution == 0u || manifest->abilities[mega->ability] == 0u) {
                    return false;
                }
            }
            for (uint32_t k = 0u; k < mem->move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                if (manifest->moves[mem->moves[k].move_id] == 0u) {
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
    const dfi_forme_data *base = &dfi_ext_formes[species];
    const dfi_forme_data *cur = base;
    if (is_mega != 0u) {
        if (base->mega_forme == DFI_CLOSURE_NONE) {
            return false;
        }
        cur = &dfi_ext_formes[base->mega_forme];
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
    const dfi_move_data *mv = &dfi_ext_moves[move];
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
    const dfi_forme_data *base = &dfi_ext_formes[m->species_id];
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
    m->ability = (uint8_t)((uint32_t)dfi_ext_formes[base->mega_forme].ability + 1u); /* wide-operands-reviewed: < 22 */
    return true;
}

bool dfi_closure_member_ranges(const dfi_kind_limits *lim, const dfi_member *m)
{
    const dfi_forme_data *base = &dfi_ext_formes[m->species_id]; /* below the context species count */
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
        if (m->ability != (uint32_t)dfi_ext_formes[base->mega_forme].ability + 1u) {
            return false;
        }
    } else if (m->ability != (uint32_t)base->ability + 1u && !(lim->dev && m->ability == 0u)) {
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
    const dfi_forme_data *base = &dfi_ext_formes[m->species_id]; /* below the context species count */
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
        if (!dfi_in_set(base, move) || !dfi_derive_pp(move, &pp_max) || pp_max != m->moves[k].pp_max) {
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
