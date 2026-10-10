#include "state/data_query.h"

#include "data/formulas.h"
#include "data/pool_tables.h"
#include "state/closure_member.h"
#include "state/context_internal.h"

/* The public buffers must hold what the tables can give. A growth of the
 * tables beyond a bound fails the build: raising a bound is a reviewed change
 * of the public header. */
_Static_assert(DFI_POOL_FORME_ABILITIES_MAX <= DUOFORGE_DATA_MAX_FORME_ABILITIES,
               "a forme may have more legal abilities than DUOFORGE_DATA_MAX_FORME_ABILITIES");
_Static_assert(DFI_POOL_MOVE_COUNT <= DUOFORGE_DATA_MAX_FORME_MOVES,
               "the pool has more moves than DUOFORGE_DATA_MAX_FORME_MOVES");

_Static_assert(sizeof(duoforge_forme_info) == 60u, "duoforge_forme_info is 15 words, as the header says");
_Static_assert(sizeof(duoforge_mega_info) == 20u, "duoforge_mega_info is 5 words, as the header says");

/* The ids of a table under the kind. */
static uint32_t dfi_table_count(const dfi_kind_limits *lim, uint32_t table)
{
    switch (table) {
    case DUOFORGE_DATA_TABLE_SPECIES:
        return lim->forme_count;
    case DUOFORGE_DATA_TABLE_MOVE:
        return lim->move_count;
    case DUOFORGE_DATA_TABLE_ITEM:
        return lim->item_count;
    case DUOFORGE_DATA_TABLE_ABILITY:
        return lim->ability_count;
    default:
        return DFI_NATURE_COUNT; /* DUOFORGE_DATA_TABLE_NATURE */
    }
}

/* The names of a table: the pool tables' arrays, of which every kind reads its prefix. */
static const char *const *dfi_table_names(uint32_t table)
{
    switch (table) {
    case DUOFORGE_DATA_TABLE_SPECIES:
        return dfi_pool_forme_names;
    case DUOFORGE_DATA_TABLE_MOVE:
        return dfi_pool_move_names;
    case DUOFORGE_DATA_TABLE_ITEM:
        return dfi_pool_item_names;
    case DUOFORGE_DATA_TABLE_ABILITY:
        return dfi_pool_ability_names;
    default:
        return dfi_pool_nature_names; /* DUOFORGE_DATA_TABLE_NATURE */
    }
}

static bool dfi_table_valid(uint32_t table)
{
    return table >= DUOFORGE_DATA_TABLE_SPECIES && table <= DUOFORGE_DATA_TABLE_COUNT;
}

bool dfi_data_supported(const dfi_support_manifest *manifest, uint32_t table, uint32_t id)
{
    if (manifest->turn_core == 0u) {
        return false; /* no battle passes the gate without the turn core */
    }
    switch (table) {
    case DUOFORGE_DATA_TABLE_MOVE:
        return dfi_manifest_move(manifest, id);
    case DUOFORGE_DATA_TABLE_ITEM:
        return dfi_manifest_item(manifest, id);
    case DUOFORGE_DATA_TABLE_ABILITY:
        return dfi_manifest_ability(manifest, id);
    case DUOFORGE_DATA_TABLE_SPECIES:
        /* No mark of its own; a Mega forme is reached by Mega Evolution of its base forme, and only the Mega forme
         * that the base forme's row links is reached (Charizard-Mega-X is a row of the pool, but the base forme
         * links Charizard-Mega-Y: the engine has no way into the other one). */
        return dfi_pool_formes[id].is_mega == 0u ||
               (dfi_pool_formes[dfi_pool_formes[id].base_forme].mega_forme == id &&
                dfi_manifest_mega(manifest, dfi_pool_formes[id].base_forme));
    default:
        return true; /* a nature carries no mark */
    }
}

void dfi_data_forme_info(const dfi_kind_limits *lim, const dfi_support_manifest *manifest, uint32_t species,
                         duoforge_forme_info *out)
{
    const dfi_pool_forme_data *f = &dfi_pool_formes[species];
    duoforge_forme_info info = {0};
    info.dex_num = f->dex_num;
    info.is_mega = f->is_mega;
    info.setup_legal = dfi_forme_setup_legal(lim, species) ? 1u : 0u;
    info.base_species = f->base_forme;
    info.mega_species = f->mega_forme != DFI_FORME_NONE ? (uint32_t)f->mega_forme : DUOFORGE_DATA_NONE;
    const uint32_t stone = dfi_forme_stone(species);
    info.mega_stone = stone != DFI_CLOSURE_NONE ? stone : DUOFORGE_DATA_NONE;
    info.mega_ability = f->mega_forme != DFI_FORME_NONE ? (uint32_t)dfi_pool_formes[f->mega_forme].ability
                                                          : DUOFORGE_DATA_NONE;
    info.mega_supported = manifest->turn_core != 0u && dfi_manifest_mega(manifest, species) ? 1u : 0u;
    if (info.setup_legal != 0u) {
        const uint32_t genders[3] = {DUOFORGE_GENDER_MALE, DUOFORGE_GENDER_FEMALE, DUOFORGE_GENDER_NONE};
        const uint32_t bits[3] = {DUOFORGE_GENDER_BIT_MALE, DUOFORGE_GENDER_BIT_FEMALE, DUOFORGE_GENDER_BIT_NONE};
        for (uint32_t g = 0u; g < 3u; ++g) {
            if (dfi_gender_legal(f->gender_rule, genders[g])) {
                info.gender_mask |= bits[g];
            }
        }
        info.no_ability = lim->dev ? 1u : 0u;
        for (uint32_t a = 0u; a < lim->ability_count; ++a) {
            if (dfi_forme_ability_legal(lim, species, a + 1u)) {
                if (info.ability_count < DUOFORGE_DATA_MAX_FORME_ABILITIES) {
                    info.abilities[info.ability_count] = a;
                }
                info.ability_count += 1u; /* counted past the bound too, so that a caller can see it */
            }
        }
        for (uint32_t m = 0u; m < lim->move_count; ++m) {
            if (dfi_forme_move_legal(lim, species, m)) {
                info.move_count += 1u;
            }
        }
    }
    *out = info;
}

/* The arguments every call checks before it looks at the context's kind. */
static duoforge_status dfi_data_begin(const duoforge_context *ctx, uint32_t table, bool table_given,
                                      dfi_kind_limits *lim)
{
    if (table_given && !dfi_table_valid(table)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (!dfi_context_is_closure(ctx)) {
        return DUOFORGE_E_UNSUPPORTED; /* SYNTHETIC: no tables */
    }
    *lim = dfi_kind_limits_of(ctx->data_kind);
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_count(const duoforge_context *ctx, uint32_t table, uint32_t *out_count)
{
    if (ctx == NULL || out_count == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, table, true, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *out_count = dfi_table_count(&lim, table);
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_name(const duoforge_context *ctx, uint32_t table, uint32_t id, const char **out_name)
{
    if (ctx == NULL || out_name == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, table, true, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (id >= dfi_table_count(&lim, table)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_name = dfi_table_names(table)[id];
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_find(const duoforge_context *ctx, uint32_t table, const char *name, size_t length,
                                   uint32_t *out_id)
{
    if (ctx == NULL || name == NULL || out_id == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, table, true, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const char *const *names = dfi_table_names(table);
    const uint32_t count = dfi_table_count(&lim, table);
    for (uint32_t id = 0u; id < count; ++id) {
        const char *candidate = names[id];
        size_t k = 0u;
        while (k < length && candidate[k] != '\0' && candidate[k] == name[k]) {
            ++k;
        }
        /* The whole name matched and the candidate ends with it. The scan stops at the candidate's
         * terminator, so a NUL inside the given name never matches. */
        if (k == length && candidate[k] == '\0') {
            *out_id = id;
            return DUOFORGE_OK;
        }
    }
    if (table == DUOFORGE_DATA_TABLE_SPECIES) {
        /* The cosmetic aliases (generated data, decision 0015 section 4.2): the row of the base forme, bound by the
         * kind's count like the row itself. The same exact, NUL-safe comparison as above. */
        for (uint32_t a = 0u; a < DFI_POOL_ALIAS_COUNT; ++a) {
            const char *candidate = dfi_pool_forme_aliases[a].name;
            size_t k = 0u;
            while (k < length && candidate[k] != '\0' && candidate[k] == name[k]) {
                ++k;
            }
            if (k == length && candidate[k] == '\0' && (uint32_t)dfi_pool_forme_aliases[a].forme < count) {
                *out_id = (uint32_t)dfi_pool_forme_aliases[a].forme;
                return DUOFORGE_OK;
            }
        }
    }
    return DUOFORGE_E_INVALID_ARGUMENT;
}

duoforge_status duoforge_data_supported(const duoforge_context *ctx, uint32_t table, uint32_t id,
                                        bool *out_supported)
{
    if (ctx == NULL || out_supported == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, table, true, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (id >= dfi_table_count(&lim, table)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_supported = dfi_data_supported(&dfi_support, table, id);
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_forme_info(const duoforge_context *ctx, uint32_t species_id, duoforge_forme_info *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (species_id >= lim.forme_count) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    duoforge_forme_info info;
    dfi_data_forme_info(&lim, &dfi_support, species_id, &info);
    if (info.ability_count > DUOFORGE_DATA_MAX_FORME_ABILITIES) {
        return DUOFORGE_E_INVARIANT; /* a table beyond the public bound: an engine bug */
    }
    *out = info;
    return DUOFORGE_OK;
}

uint32_t dfi_data_mega_count(const dfi_kind_limits *lim, uint32_t species)
{
    uint32_t count = 0u;
    for (uint32_t item = 0u; item < lim->item_count; ++item) {
        count += dfi_mega_of(species, item + 1u) != DFI_FORME_NONE ? 1u : 0u;
    }
    return count;
}

void dfi_data_mega_at(const dfi_kind_limits *lim, const dfi_support_manifest *manifest, uint32_t species,
                      uint32_t index, duoforge_mega_info *out)
{
    uint32_t seen = 0u;
    for (uint32_t item = 0u; item < lim->item_count; ++item) {
        const uint32_t mega = dfi_mega_of(species, item + 1u);
        if (mega == DFI_FORME_NONE) {
            continue;
        }
        if (seen == index) {
            duoforge_mega_info info = {0};
            info.base_species = species;
            info.stone = item;
            info.mega_species = mega;
            info.mega_ability = dfi_pool_formes[mega].ability;
            info.supported = manifest->turn_core != 0u && dfi_manifest_mega_of(manifest, species, item + 1u) ? 1u : 0u;
            *out = info;
            return;
        }
        seen += 1u;
    }
}

duoforge_status duoforge_data_mega_count(const duoforge_context *ctx, uint32_t species_id, uint32_t *out_count)
{
    if (ctx == NULL || out_count == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (species_id >= lim.forme_count) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_count = dfi_data_mega_count(&lim, species_id);
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_mega_at(const duoforge_context *ctx, uint32_t species_id, uint32_t index,
                                      duoforge_mega_info *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (species_id >= lim.forme_count || index >= dfi_data_mega_count(&lim, species_id)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    dfi_data_mega_at(&lim, &dfi_support, species_id, index, out);
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_forme_moves(const duoforge_context *ctx, uint32_t species_id, uint32_t *buffer,
                                          uint32_t capacity, uint32_t *out_count)
{
    if (ctx == NULL || out_count == NULL || (buffer == NULL && capacity != 0u)) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (species_id >= lim.forme_count) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    uint32_t count = 0u;
    if (dfi_forme_setup_legal(&lim, species_id)) {
        for (uint32_t m = 0u; m < lim.move_count; ++m) {
            if (dfi_forme_move_legal(&lim, species_id, m)) {
                count += 1u;
            }
        }
    }
    if (count > capacity) {
        *out_count = count; /* the required count, nothing else (decision 0005 section 7) */
        return DUOFORGE_E_CAPACITY;
    }
    uint32_t n = 0u;
    if (count != 0u) {
        for (uint32_t m = 0u; m < lim.move_count; ++m) {
            if (dfi_forme_move_legal(&lim, species_id, m)) {
                buffer[n] = m;
                n += 1u;
            }
        }
    }
    *out_count = n;
    return DUOFORGE_OK;
}

/* ---- static features (decision 0020): plain reads of the generated tables, no rule of the engine ---- */

_Static_assert(sizeof(duoforge_forme_static) == 44u, "duoforge_forme_static is 11 words, as the header says");
_Static_assert(sizeof(duoforge_move_static) == 64u, "duoforge_move_static is 16 words, as the header says");
_Static_assert(sizeof(duoforge_item_static) == 16u, "duoforge_item_static is 4 words, as the header says");
_Static_assert(sizeof(duoforge_ability_static) == 8u, "duoforge_ability_static is 2 words, as the header says");
_Static_assert(sizeof(duoforge_nature_static) == 8u, "duoforge_nature_static is 2 words, as the header says");
_Static_assert(DFI_TARGET_CLASS_FOE_SIDE == DUOFORGE_TARGET_CLASS_STATIC_COUNT,
               "the static target classes are the tables' 1 to 15");
_Static_assert(DFI_TYPE_COUNT == 18u, "the public type ids are the tables' 18 types");

/* The checks every static read makes after the NULL ones: SYNTHETIC, then the id. */
static duoforge_status dfi_static_begin(const duoforge_context *ctx, uint32_t table, uint32_t id)
{
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return id < dfi_table_count(&lim, table) ? DUOFORGE_OK : DUOFORGE_E_INVALID_ARGUMENT;
}

/* A table byte that is DFI_CLOSURE_NONE (255) is DUOFORGE_DATA_NONE in the public structs. */
static uint32_t dfi_public_id(uint32_t table_byte)
{
    return table_byte == DFI_CLOSURE_NONE ? DUOFORGE_DATA_NONE : table_byte;
}

duoforge_status duoforge_data_forme_static(const duoforge_context *ctx, uint32_t species_id, duoforge_forme_static *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_static_begin(ctx, DUOFORGE_DATA_TABLE_SPECIES, species_id);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const dfi_pool_forme_data *f = &dfi_pool_formes[species_id];
    duoforge_forme_static r = {0};
    r.types[0] = f->types[0];
    r.types[1] = dfi_public_id(f->types[1]);
    for (uint32_t s = 0u; s < DFI_STAT_COUNT; ++s) {
        r.base_stats[s] = f->base[s];
    }
    r.weight_hg = f->weight_hg;
    r.default_ability = f->ability;
    r.is_mega = f->is_mega;
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_move_static(const duoforge_context *ctx, uint32_t move_id, duoforge_move_static *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_static_begin(ctx, DUOFORGE_DATA_TABLE_MOVE, move_id);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const dfi_move_data *m = &dfi_pool_moves[move_id];
    uint8_t pp = 0u;
    if (!dfi_champions_pp_max(m->pp_base, (m->flags & DFI_MOVE_FLAG_NO_PP_BOOSTS) != 0u, &pp)) {
        return DUOFORGE_E_INVARIANT; /* a table row that setup could not use: an engine bug */
    }
    duoforge_move_static r = {0u};
    r.type = m->type;
    r.category = m->category;
    r.base_power = m->base_power;
    r.accuracy = m->accuracy;
    r.pp = pp;
    r.priority = (uint32_t)m->priority - (uint32_t)DFI_PRIORITY_BIAS; /* wraps: the two's complement of a negative priority */
    r.target_class = m->target_class;
    r.flags = dfi_pool_move_static_flags[move_id];
    if (m->special == DFI_SPECIAL_LOCKED_MOVE) {
        r.flags |= DUOFORGE_MOVE_STATIC_FLAG_LOCKED_MOVE;
    }
    r.crit_stage = m->crit_ratio > 0u ? (uint32_t)m->crit_ratio - 1u : 0u;
    r.drain[0] = m->drain[0];
    r.drain[1] = m->drain[1];
    r.recoil[0] = m->recoil[0];
    r.recoil[1] = m->recoil[1];
    r.secondary_chance = m->sec_chance;
    r.hits_min = dfi_pool_move_static_hits[move_id][0];
    r.hits_max = dfi_pool_move_static_hits[move_id][1];
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_item_static(const duoforge_context *ctx, uint32_t item_id, duoforge_item_static *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_static_begin(ctx, DUOFORGE_DATA_TABLE_ITEM, item_id);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const dfi_item_family *fam = &dfi_pool_item_family[item_id];
    duoforge_item_static r = {0u};
    r.family = fam->family;
    r.family_type = fam->family == DFI_ITEM_FAMILY_NONE ? DUOFORGE_DATA_NONE : dfi_public_id(fam->type);
    r.is_mega_stone = dfi_pool_items[item_id].mega_forme != DFI_FORME_NONE ? 1u : 0u;
    r.mega_species = r.is_mega_stone != 0u ? (uint32_t)dfi_pool_items[item_id].mega_forme : DUOFORGE_DATA_NONE;
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_ability_static(const duoforge_context *ctx, uint32_t ability_id,
                                             duoforge_ability_static *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_static_begin(ctx, DUOFORGE_DATA_TABLE_ABILITY, ability_id);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const dfi_ability_family *fam = &dfi_pool_ability_family[ability_id];
    duoforge_ability_static r = {0u};
    r.family = fam->family;
    r.family_param = fam->family == DFI_ABILITY_FAMILY_NONE ? DUOFORGE_DATA_NONE : dfi_public_id(fam->param);
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_nature_static(const duoforge_context *ctx, uint32_t nature_id, duoforge_nature_static *out)
{
    if (ctx == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status st = dfi_static_begin(ctx, DUOFORGE_DATA_TABLE_NATURE, nature_id);
    if (st != DUOFORGE_OK) {
        return st;
    }
    duoforge_nature_static r = {0u, 0u};
    r.raised_stat = dfi_public_id(dfi_closure_natures[nature_id].plus);
    r.lowered_stat = dfi_public_id(dfi_closure_natures[nature_id].minus);
    *out = r;
    return DUOFORGE_OK;
}

duoforge_status duoforge_data_type_effect(const duoforge_context *ctx, uint32_t attack_type, uint32_t defend_type,
                                          uint32_t *out_num, uint32_t *out_den)
{
    if (ctx == NULL || out_num == NULL || out_den == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_kind_limits lim;
    const duoforge_status st = dfi_data_begin(ctx, 0u, false, &lim);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (attack_type >= DFI_TYPE_COUNT || defend_type >= DFI_TYPE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    uint32_t num = 1u;
    uint32_t den = 1u;
    switch (dfi_closure_type_chart[defend_type][attack_type]) {
    case DFI_EFFECT_SUPER:
        num = 2u;
        break;
    case DFI_EFFECT_RESISTED:
        den = 2u;
        break;
    case DFI_EFFECT_IMMUNE:
        num = 0u;
        break;
    default:
        break; /* DFI_EFFECT_NEUTRAL */
    }
    *out_num = num;
    *out_den = den;
    return DUOFORGE_OK;
}
