#include "eval/graph.h"
#include "eval/kernels.h"
#include "eval/normalization.h"
#include <limits.h>
#include <string.h>
#include <stdio.h>

#include "eval/graph_registry.inc"
_Static_assert(sizeof(dfi_eval_inputs) <= 2688u, "canonical input slot capacity");

typedef struct tensor_binding { void *data; dfi_eval_scale *scales; } tensor_binding;
typedef struct graph_parameters {
    const dfi_eval_shape *shape;
    int16_t unit;
    dfi_eval_normalization normalization;
    dfi_eval_scale input_scales[1094];
    tensor_binding tensors[28];
} graph_parameters;

const dfi_eval_shape *dfi_eval_shape_lookup(uint32_t id)
{
    for (size_t i = 0; i < sizeof dfi_shapes / sizeof dfi_shapes[0]; ++i)
        if (dfi_shapes[i].graph->id == id) return &dfi_shapes[i];
    return NULL;
}
static duoforge_status graph_error(duoforge_eval_error *error, duoforge_status st, const char *reason)
{
    return dfi_eval_error(error, st, "graph", reason);
}
static uint64_t little(const uint8_t *bytes, size_t n)
{
    uint64_t value = 0u;
    for (size_t i = 0; i < n; ++i) value |= (uint64_t)bytes[i] << (8u * i);
    return value;
}
static int64_t decode_signed(uint64_t bits, uint32_t width)
{
    if (width == 8u) return bits <= INT64_MAX ? (int64_t)bits : -1 - (int64_t)(UINT64_MAX - bits);
    const uint64_t sign = UINT64_C(1) << (width * 8u - 1u);
    const uint64_t mask = (sign << 1u) - 1u;
    return bits < sign ? (int64_t)bits : -1 - (int64_t)(mask - bits);
}
duoforge_status dfi_eval_graph_bind(duoforge_evaluator *model, duoforge_eval_error *error)
{
    const dfi_eval_shape *shape = dfi_eval_shape_lookup(model->graph->id);
    /* E2's private whitebox descriptors never become production graphs. */
    if (shape == NULL || shape->graph != model->graph) return DUOFORGE_OK;
    const dfi_eval_graph *graph = shape->graph;
    size_t bytes = sizeof(graph_parameters);
    for (uint32_t i = 0; i < graph->tensor_count; ++i) {
        const uint8_t *entry = model->file + 256u + (size_t)i * 128u;
        const uint64_t payload = little(entry + 64u, 8u);
        const size_t scales = (size_t)graph->tensors[i].scale_count * sizeof(dfi_eval_scale);
        if (bytes > SIZE_MAX-7u)
            return graph_error(error, DUOFORGE_E_CAPACITY, "eval_parameter_capacity");
        bytes = (bytes + 7u) & ~(size_t)7u;
        if (payload > SIZE_MAX-bytes) return graph_error(error, DUOFORGE_E_CAPACITY, "eval_parameter_capacity");
        bytes += (size_t)payload;
        if (bytes > SIZE_MAX-7u) return graph_error(error, DUOFORGE_E_CAPACITY, "eval_parameter_capacity");
        bytes = (bytes + 7u) & ~(size_t)7u;
        if (scales > SIZE_MAX-bytes) return graph_error(error, DUOFORGE_E_CAPACITY, "eval_parameter_capacity");
        bytes += scales;
    }
    if ((uint64_t)bytes > graph->file_max + 65536u)
        return graph_error(error, DUOFORGE_E_CAPACITY, "eval_parameter_capacity");
    graph_parameters *p = model->allocator.allocate(bytes, model->allocator.user);
    if (p == NULL) return graph_error(error, DUOFORGE_E_OUT_OF_MEMORY, "eval_parameter_allocation");
    memset(p, 0, bytes);
    model->parameters = p;
    model->parameter_bytes = bytes;
    p->shape = shape;
    size_t cursor = sizeof *p;
    for (uint32_t i = 0; i < graph->tensor_count; ++i) {
        const dfi_eval_tensor_spec *spec = &graph->tensors[i];
        const uint8_t *entry = model->file + 256u + (size_t)i * 128u;
        const uint32_t width = 1u << (spec->dtype - 1u);
        const size_t payload = (size_t)little(entry + 64u, 8u);
        const uint8_t *data = model->file + (size_t)little(entry + 56u, 8u);
        cursor = (cursor + 7u) & ~(size_t)7u;
        void *dest = (uint8_t *)p + cursor;
        p->tensors[i].data = dest;
        for (size_t j = 0; j < payload / width; ++j) {
            const int64_t value = decode_signed(little(data + j * width, width), width);
            if (width == 1u) ((int8_t *)dest)[j] = (int8_t)value;
            else if (width == 2u) ((int16_t *)dest)[j] = (int16_t)value;
            else if (width == 4u) ((int32_t *)dest)[j] = (int32_t)value;
            else ((int64_t *)dest)[j] = value;
        }
        cursor += payload;
        /* Scale records need uint32 alignment even after an I8 payload. */
        cursor = (cursor + 7u) & ~(size_t)7u;
        p->tensors[i].scales = (dfi_eval_scale *)((uint8_t *)p + cursor);
        const uint8_t *scales = model->file + (size_t)little(entry + 72u, 8u);
        for (uint32_t j = 0; j < spec->scale_count; ++j) {
            p->tensors[i].scales[j] = (dfi_eval_scale){(uint32_t)little(scales + 8u*j, 4u),
                (uint32_t)little(scales + 8u*j + 4u, 4u)};
        }
        cursor += (size_t)spec->scale_count * sizeof(dfi_eval_scale);
    }
    p->unit = *(const int16_t *)p->tensors[0].data;
    const uint32_t unit = p->unit > 0 ? (uint32_t)p->unit : 0u;
    if (unit < 256u || unit > 16384u || (unit & (unit - 1u)) != 0u)
        return graph_error(error, DUOFORGE_E_MALFORMED, "eval_input_unit");
    int16_t epsilon = 0;
    /* The teacher's exact binary32 epsilon, in the declared squared units. */
    const duoforge_status st = dfi_eval_binary32(UINT32_C(0x3727c5ac),
        (dfi_eval_scale){unit * unit, 0u}, &epsilon);
    if (st != DUOFORGE_OK || epsilon <= 0)
        return graph_error(error, DUOFORGE_E_MALFORMED, "eval_normalization_epsilon");
    p->normalization = (dfi_eval_normalization){(uint64_t)epsilon, 31u, 47u, {1u,16u}, {1u,0u}};
    for (uint32_t i = 0u; i < 1094u; ++i) p->input_scales[i] = (dfi_eval_scale){unit,0u};
    return DUOFORGE_OK;
}

typedef struct graph_row {
    dfi_eval_inputs *input;
    int16_t *tokens, *members, *positions, *member_in, *move_in, *position_in, *torso_in;
    int32_t *torso, *dense, *norm, *operator_scratch;
    int16_t *move_pool, *side_pool;
} graph_row;
typedef struct arena { uint8_t *base; size_t size, used; bool valid; } arena;
static void *reserve(arena *a, size_t element, uint32_t width, uint32_t row)
{
    if (!a->valid || a->used > SIZE_MAX - 127u) { a->valid = false; return NULL; }
    const size_t at = (a->used + 127u) & ~(size_t)127u;
    if (width > SIZE_MAX / 16u / element) { a->valid = false; return NULL; }
    const size_t length = (size_t)width * 16u * element;
    if (at > a->size || length > a->size - at) { a->valid = false; return NULL; }
    a->used = at + length;
    return a->base == NULL ? NULL : a->base + at + (size_t)row * width * element;
}
static void layout(arena *a, const dfi_eval_shape *s, uint32_t row, graph_row *r)
{
    /* Two existing-row reservations; no count*1094 encoder slab. */
    a->used += 2u * 4376u;
    r->input = reserve(a, 1u, 2688u, row);
    r->tokens = reserve(a, 2u, 48u*s->embed, row);
    r->members = reserve(a, 2u, 12u*s->member, row);
    r->positions = reserve(a, 2u, 4u*s->position, row);
    r->member_in = reserve(a, 2u, 5u*s->embed+42u, row);
    r->move_in = reserve(a, 2u, s->embed+1u, row);
    r->position_in = reserve(a, 2u, 106u+s->member, row);
    r->torso_in = reserve(a, 2u, 94u+4u*s->position+4u*s->member, row);
    r->torso = reserve(a, 4u, s->hidden, row);
    r->dense = reserve(a, 4u, s->hidden, row);
    r->norm = reserve(a, 4u, s->hidden, row);
    r->operator_scratch = reserve(a, 4u, s->hidden, row);
    r->move_pool = reserve(a, 2u, 2u*s->embed, row);
    r->side_pool = reserve(a, 2u, 4u*s->member, row);
    /* Tile values/statuses; caller outputs remain separately accounted for. */
    (void)reserve(a, 4u, 2u, 0u);
}
size_t dfi_eval_graph_scratch(const dfi_eval_shape *shape)
{
    if (shape == NULL || shape->graph == NULL || dfi_eval_shape_lookup(shape->graph->id) != shape) return 0u;
    arena a = {NULL, SIZE_MAX, 0u, true};
    graph_row row;
    layout(&a, shape, 0u, &row);
    return a.valid ? a.used + 127u : 0u;
}
static duoforge_status emit(const dfi_eval_trace *trace, const char *name, uint32_t index,
    uint32_t type, const void *values, uint32_t count)
{
    return trace == NULL || trace->emit == NULL ? DUOFORGE_OK
        : trace->emit(trace->user, name, index, type, values, count);
}
static duoforge_status group(const dfi_eval_inputs *input, dfi_eval_group kind,
    uint32_t side, uint32_t member, int16_t *out, uint32_t width)
{
    const dfi_eval_column *columns = dfi_eval_input_columns();
    uint32_t count = 0u;
    for (uint32_t i = 0; i < 1094u; ++i) {
        const dfi_eval_column *c = &columns[i];
        if (c->group != kind) continue;
        if (kind != DFI_EVAL_GROUP_GLOB && c->a != side) continue;
        if ((kind == DFI_EVAL_GROUP_MEMBER || kind == DFI_EVAL_GROUP_POSITION || kind == DFI_EVAL_GROUP_PP) && c->b != member) continue;
        if (count == width) return DUOFORGE_E_INVARIANT;
        out[count++] = input->scalars[i];
    }
    return count == width ? DUOFORGE_OK : DUOFORGE_E_INVARIANT;
}
static duoforge_status dense16(const graph_parameters *p, uint32_t tensor,
    const int16_t *in, uint32_t ni, uint32_t no, int16_t *out)
{
    return dfi_eval_dense(in, ni, p->tensors[tensor].data, p->tensors[tensor+1u].data,
        p->tensors[tensor].scales, no, true, out);
}

duoforge_status dfi_eval_graph_row(const duoforge_evaluator *model,
    void *scratch, size_t bytes, uint32_t row, const uint32_t bits[1094],
    const dfi_eval_trace *trace, int32_t *value, duoforge_eval_error *error)
{
    if (model == NULL || scratch == NULL || bits == NULL || value == NULL)
        return graph_error(error, DUOFORGE_E_NULL_ARGUMENT, "eval_graph_argument");
    const graph_parameters *p = model->parameters;
    const dfi_eval_shape *s = dfi_eval_shape_lookup(model->graph->id);
    if (p == NULL || s == NULL || p->shape != s || model->graph != s->graph)
        return graph_error(error, DUOFORGE_E_UNSUPPORTED, "eval_graph_unregistered");
    if (row >= 16u || bytes < dfi_eval_graph_scratch(s))
        return graph_error(error, DUOFORGE_E_CAPACITY, "eval_graph_scratch");
    const uintptr_t address = (uintptr_t)scratch;
    const size_t address_low = (size_t)address & 127u;
    const size_t padding = (128u - address_low) & 127u;
    arena a = {(uint8_t *)scratch + padding, bytes-padding, 0u, true};
    graph_row r;
    layout(&a, s, row, &r);
    if (!a.valid) return graph_error(error, DUOFORGE_E_CAPACITY, "eval_graph_scratch");
    duoforge_status st = DUOFORGE_OK;
    char reason[128] = {0};
#define TRY(call, stage) do { st = (call); if (st != DUOFORGE_OK) return graph_error(error, st, (stage)); } while (0)
#define TRACE(name, index, type, data, width) TRY(emit(trace, name, index, type, data, width), "eval_trace_refused")
    /* Common scales are immutable cold data; encoder/raw-row slots stay intact. */
    st = dfi_eval_prepare_inputs(bits, p->input_scales, (dfi_eval_id_capacities){1024u,1024u,256u,256u,25u}, r.input, reason);
    if (st != DUOFORGE_OK) return graph_error(error, st, reason);
    TRACE("scalars", 0u, 1u, r.input->scalars, 1094u);
    TRACE("registered", 0u, 4u, r.input->registered, 12u);
    TRACE("occupant", 0u, 4u, r.input->occupant, 4u);
    const dfi_eval_scale unity = {1u,0u};
    for (uint32_t side = 0u; side < 2u; ++side) for (uint32_t member = 0u; member < 6u; ++member) {
        const uint32_t index = 6u*side+member;
        int16_t pp[4];
        TRY(group(r.input, DFI_EVAL_GROUP_PP, side, member, pp, 4u), "eval_graph_pp");
        uint8_t mask[4];
        for (uint32_t move = 0u; move < 4u; ++move) {
            mask[move] = move < r.input->move_count[side][member] ? 1u : 0u;
            TRY(dfi_eval_embedding(p->tensors[2].data, 1024u, s->embed, r.input->moves[side][member][move],
                p->tensors[2].scales[0], r.move_in), "eval_graph_move_id");
            r.move_in[s->embed] = pp[move];
            TRACE("move_input", 4u*index+move, 1u, r.move_in, s->embed+1u);
            TRY(dense16(p, 6u, r.move_in, s->embed+1u, s->embed, r.tokens+(4u*index+move)*s->embed), "eval_graph_move_token");
            TRACE("move_token", 4u*index+move, 1u, r.tokens+(4u*index+move)*s->embed, s->embed);
        }
        TRY(dfi_eval_pool(r.tokens+4u*index*s->embed, mask, 4u, s->embed, false, unity, r.move_pool), "eval_graph_move_sum");
        TRY(dfi_eval_pool(r.tokens+4u*index*s->embed, mask, 4u, s->embed, true, unity, r.move_pool+s->embed), "eval_graph_move_max");
        TRACE("move_sum", index, 1u, r.move_pool, s->embed);
        TRACE("move_max", index, 1u, r.move_pool+s->embed, s->embed);
        TRY(dfi_eval_embedding(p->tensors[1].data,1024u,s->embed,r.input->species[side][member],p->tensors[1].scales[0],r.member_in),"eval_graph_species");
        memcpy(r.member_in+s->embed,r.move_pool,(size_t)2u*s->embed*sizeof(int16_t));
        TRY(dfi_eval_embedding(p->tensors[3].data,256u,s->embed,r.input->item[side][member],p->tensors[3].scales[0],r.member_in+3u*s->embed),"eval_graph_item");
        TRY(dfi_eval_embedding(p->tensors[4].data,256u,s->embed,r.input->ability[side][member],p->tensors[4].scales[0],r.member_in+4u*s->embed),"eval_graph_ability");
        TRY(dfi_eval_embedding(p->tensors[5].data,25u,8u,r.input->nature[side][member],p->tensors[5].scales[0],r.member_in+5u*s->embed),"eval_graph_nature");
        TRY(group(r.input,DFI_EVAL_GROUP_MEMBER,side,member,r.member_in+5u*s->embed+8u,32u),"eval_graph_member_columns");
        r.member_in[5u*s->embed+40u] = side == 0u ? p->unit : 0;
        r.member_in[5u*s->embed+41u] = r.input->registered[side][member] ? p->unit : 0;
        TRACE("member_input", index, 1u, r.member_in,5u*s->embed+42u);
        /* Approved shapes all have M=2E: the dead move-pool buffer is reused. */
        TRY(dense16(p,8u,r.member_in,5u*s->embed+42u,s->member,r.move_pool),"eval_graph_member1");
        TRACE("member1",index,1u,r.move_pool,s->member);
        int16_t *h = r.members+index*s->member;
        TRY(dense16(p,10u,r.move_pool,s->member,s->member,h),"eval_graph_member2");
        TRACE("member2",index,1u,h,s->member);
        if (!r.input->registered[side][member]) memset(h,0,(size_t)s->member*sizeof(int16_t));
        TRACE("member_mask",index,1u,h,s->member);
    }
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t pos = 0u; pos < 2u; ++pos) {
            const uint32_t index = 2u*side+pos, occupant = r.input->occupant[side][pos];
            TRY(group(r.input,DFI_EVAL_GROUP_POSITION,side,pos,r.position_in,105u),"eval_graph_position_columns");
            r.position_in[105] = occupant < 6u ? p->unit : 0;
            TRY(dfi_eval_gather(r.members+6u*side*s->member,6u,s->member,occupant,occupant<6u,r.position_in+106u),"eval_graph_gather");
            TRACE("gather",index,1u,r.position_in+106u,s->member);
            TRACE("position_input",index,1u,r.position_in,106u+s->member);
            TRY(dense16(p,12u,r.position_in,106u+s->member,s->position,r.positions+index*s->position),"eval_graph_position");
            TRACE("position",index,1u,r.positions+index*s->position,s->position);
        }
        TRY(dfi_eval_pool(r.members+6u*side*s->member,r.input->registered[side],6u,s->member,false,unity,r.side_pool+side*s->member),"eval_graph_side_sum");
        TRY(dfi_eval_pool(r.members+6u*side*s->member,r.input->registered[side],6u,s->member,true,unity,r.side_pool+(2u+side)*s->member),"eval_graph_side_max");
        TRACE("side_sum",side,1u,r.side_pool+side*s->member,s->member);
        TRACE("side_max",side,1u,r.side_pool+(2u+side)*s->member,s->member);
    }
    TRY(group(r.input,DFI_EVAL_GROUP_GLOB,0u,0u,r.torso_in,36u),"eval_graph_global_columns");
    TRY(group(r.input,DFI_EVAL_GROUP_SIDE,0u,0u,r.torso_in+36u,29u),"eval_graph_side_columns");
    TRY(group(r.input,DFI_EVAL_GROUP_SIDE,1u,0u,r.torso_in+65u,29u),"eval_graph_side_columns");
    memcpy(r.torso_in+94u,r.positions,(size_t)4u*s->position*sizeof(int16_t));
    memcpy(r.torso_in+94u+4u*s->position,r.side_pool,(size_t)4u*s->member*sizeof(int16_t));
    const uint32_t torso_width = 94u+4u*s->position+4u*s->member;
    TRACE("torso_input",0u,1u,r.torso_in,torso_width);
    for (uint32_t layer = 0u; layer < s->layers; ++layer) {
        const uint32_t tensor = 14u+4u*layer;
        if (layer == 0u) {
            TRY(dfi_eval_dense32(r.torso_in,torso_width,p->tensors[tensor].data,p->tensors[tensor+1u].data,
                p->tensors[tensor].scales,s->hidden,false,r.dense),"eval_graph_torso_dense");
        } else {
            TRY(dfi_eval_dense_i32(r.torso,s->hidden,p->tensors[tensor].data,p->tensors[tensor+1u].data,
                p->tensors[tensor].scales,s->hidden,false,r.dense),"eval_graph_torso_dense");
        }
        TRACE("torso_dense",layer,2u,r.dense,s->hidden);
        TRY(dfi_eval_layernorm32(r.dense,p->tensors[tensor+2u].data,p->tensors[tensor+3u].data,
            s->hidden,p->normalization,r.operator_scratch,s->hidden,r.norm),"eval_graph_normalization");
        TRACE("torso_norm",layer,2u,r.norm,s->hidden);
        for (uint32_t j = 0u; j < s->hidden; ++j) if (r.norm[j] < 0) r.norm[j] = 0;
        TRACE("torso_relu",layer,2u,r.norm,s->hidden);
        if (layer == 0u) memcpy(r.torso,r.norm,(size_t)s->hidden*sizeof(int32_t));
        else TRY(dfi_eval_residual32(r.torso,r.norm,s->hidden,unity,unity,unity,r.operator_scratch,s->hidden,r.torso),"eval_graph_residual");
        TRACE("torso",layer,2u,r.torso,s->hidden);
    }
    const uint32_t last = 14u+4u*s->layers;
    int32_t result;
    TRY(dfi_eval_dense_i32(r.torso,s->hidden,p->tensors[last].data,p->tensors[last+1u].data,
        p->tensors[last].scales,1u,false,&result),"eval_output_range");
    TRACE("value",0u,2u,&result,1u);
    *value = result;
    return dfi_eval_error(error,DUOFORGE_OK,"graph","");
#undef TRY
#undef TRACE
}
