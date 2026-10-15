#include "eval/inputs.h"
#include <stdio.h>
#include <string.h>
#include "eval/input_layout.inc"
const dfi_eval_column *dfi_eval_input_columns(void) { return dfi_eval_columns; }
static duoforge_status refuse(duoforge_status st, char reason[128], const char *kind, const char *name)
{
    if (reason) (void)snprintf(reason, 128u, "%s:%s", kind, name ? name : "");
    return st;
}
duoforge_status dfi_eval_input_schema(const char *const *names, uint32_t count, char reason[128])
{
    if (reason) reason[0] = '\0';
    if (!names) return refuse(DUOFORGE_E_NULL_ARGUMENT, reason, "eval_input_columns_null", "");
    if (count != DFI_EVAL_INPUT_WIDTH)
        return refuse(DUOFORGE_E_UNSUPPORTED, reason, "eval_input_columns_missing_or_extra", "");
    for (uint32_t i = 0; i < count; ++i) {
        if (!names[i] || !names[i][0]) return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_column_malformed", "");
        for (uint32_t j = 0; j < i; ++j) if (strcmp(names[i], names[j]) == 0)
            return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_column_duplicate", names[i]);
    }
    for (uint32_t i = 0; i < count; ++i) if (strcmp(names[i], dfi_eval_columns[i].name) != 0)
        return refuse(DUOFORGE_E_UNSUPPORTED, reason, "eval_input_column_unknown_or_order", names[i]);
    return DUOFORGE_OK;
}
static bool categorical(dfi_eval_group g)
{ return g == DFI_EVAL_GROUP_SPECIES || g == DFI_EVAL_GROUP_ITEM || g == DFI_EVAL_GROUP_ABILITY ||
         g == DFI_EVAL_GROUP_NATURE || g == DFI_EVAL_GROUP_MOVES; }
static bool metadata(dfi_eval_group g)
{ return g == DFI_EVAL_GROUP_PRESENT || g == DFI_EVAL_GROUP_MOVE_COUNT || g == DFI_EVAL_GROUP_OCCUPANT; }
duoforge_status dfi_eval_prepare_inputs(const uint32_t bits[DFI_EVAL_INPUT_WIDTH],
                                       const dfi_eval_scale scales[DFI_EVAL_INPUT_WIDTH],
                                       dfi_eval_id_capacities caps, dfi_eval_inputs *out, char reason[128])
{
    if (reason) reason[0] = '\0';
    if (!bits || !scales || !out) return refuse(DUOFORGE_E_NULL_ARGUMENT, reason, "eval_input_null", "");
    if (!caps.species || !caps.move || !caps.item || !caps.ability || !caps.nature)
        return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_capacity", "");
    memset(out, 0, sizeof(*out));
    uint8_t present[2][6] = {{0}}, occupied[2][2] = {{0}};
    for (uint32_t i = 0; i < DFI_EVAL_INPUT_WIDTH; ++i) {
        const dfi_eval_column *c = &dfi_eval_columns[i];
        if (!categorical(c->group) && !metadata(c->group)) continue;
        uint32_t factor = 1u, capacity = 2u, id = 0u;
        switch (c->group) {
        case DFI_EVAL_GROUP_SPECIES: factor = 65535u; capacity = caps.species; break;
        case DFI_EVAL_GROUP_MOVES: factor = 65535u; capacity = caps.move; break;
        case DFI_EVAL_GROUP_ITEM: factor = 255u; capacity = caps.item; break;
        case DFI_EVAL_GROUP_ABILITY: factor = 255u; capacity = caps.ability; break;
        case DFI_EVAL_GROUP_NATURE: factor = 24u; capacity = caps.nature; break;
        case DFI_EVAL_GROUP_MOVE_COUNT: factor = 4u; capacity = 5u; break;
        default: break;
        }
        duoforge_status st = dfi_eval_binary32_id(bits[i], factor, capacity, &id);
        if (st != DUOFORGE_OK) return refuse(st, reason, "eval_input_id", c->name);
        /* Meta one-hots/counts are emitted as exact multiples. Refuse malformed
           near-one-hot bits instead of argmax silently selecting a roster slot. */
        if ((c->group == DFI_EVAL_GROUP_PRESENT || c->group == DFI_EVAL_GROUP_OCCUPANT) &&
            bits[i] != 0u && bits[i] != UINT32_C(0x80000000) && bits[i] != UINT32_C(0x3f800000))
            return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_mask", c->name);
        if (c->group == DFI_EVAL_GROUP_MOVE_COUNT) {
            const uint32_t exact[5] = {0u, UINT32_C(0x3e800000), UINT32_C(0x3f000000),
                                       UINT32_C(0x3f400000), UINT32_C(0x3f800000)};
            if (bits[i] != exact[id] && !(id == 0u && bits[i] == UINT32_C(0x80000000)))
                return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_move_count", c->name);
        }
        switch (c->group) {
        case DFI_EVAL_GROUP_SPECIES: out->species[c->a][c->b] = id; break;
        case DFI_EVAL_GROUP_ITEM: out->item[c->a][c->b] = id; break;
        case DFI_EVAL_GROUP_ABILITY: out->ability[c->a][c->b] = id; break;
        case DFI_EVAL_GROUP_NATURE: out->nature[c->a][c->b] = id; break;
        case DFI_EVAL_GROUP_MOVES: out->moves[c->a][c->b][c->c] = id; break;
        case DFI_EVAL_GROUP_PRESENT: present[c->a][c->b] = (uint8_t)id; break;
        case DFI_EVAL_GROUP_MOVE_COUNT:
            out->move_count[c->a][c->b] = (uint8_t)id; out->registered[c->a][c->b] = id != 0u; break;
        case DFI_EVAL_GROUP_OCCUPANT:
            if (id) { ++occupied[c->a][c->b]; out->occupant[c->a][c->b] = (uint8_t)c->c; } break;
        default: return refuse(DUOFORGE_E_INVARIANT, reason, "eval_input_classification", c->name);
        }
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t m = 0; m < 6u; ++m) if (present[s][m] != out->registered[s][m])
            return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_registered_mask", "");
        for (uint32_t p = 0; p < 2u; ++p) if (occupied[s][p] != 1u)
            return refuse(DUOFORGE_E_INVALID_ARGUMENT, reason, "eval_input_occupant_mask", "");
    }
    for (uint32_t i = 0; i < DFI_EVAL_INPUT_WIDTH; ++i) {
        const dfi_eval_column *c = &dfi_eval_columns[i];
        if (categorical(c->group) || metadata(c->group)) continue;
        duoforge_status st = dfi_eval_binary32(bits[i], scales[i], &out->scalars[i]);
        if (st != DUOFORGE_OK) return refuse(st, reason, "eval_input_scalar", c->name);
    }
    return DUOFORGE_OK;
}
