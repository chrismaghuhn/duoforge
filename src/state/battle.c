#include <string.h>

#include "core/alloc.h"
#include "core/arith.h"
#include "state/battle_internal.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/invariants.h"

#define DFI_INITSEQ_LIMIT UINT64_C(0x8000000000000000)

static bool dfi_move_setup_is_zero(const duoforge_move_setup *mv)
{
    return mv->move_id == 0u && mv->pp_max == 0u;
}

static bool dfi_member_setup_is_zero(const duoforge_member_setup *m)
{
    if (m->species_id != 0u || m->hp_max != 0u || m->move_count != 0u || m->mega_capable != 0u) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_move_setup_is_zero(&m->moves[k])) {
            return false;
        }
    }
    return true;
}

static bool dfi_member_setup_valid(const struct duoforge_context *ctx, const duoforge_member_setup *m)
{
    if (m->species_id >= ctx->species_count) {
        return false;
    }
    if (m->hp_max < 1u || m->hp_max > UINT16_MAX) {
        return false;
    }
    if (m->move_count < 1u || m->move_count > DUOFORGE_MAX_MOVE_SLOTS) {
        return false;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        const duoforge_move_setup *mv = &m->moves[k];
        if (k < m->move_count) {
            if (mv->move_id >= ctx->move_count || mv->pp_max < 1u || mv->pp_max > UINT8_MAX) {
                return false;
            }
        } else if (!dfi_move_setup_is_zero(mv)) {
            return false;
        }
    }
    if (m->mega_capable > 1u) {
        return false;
    }
    return true;
}

static bool dfi_side_setup_valid(const struct duoforge_context *ctx, const duoforge_side_setup *side)
{
    const uint32_t member_count = side->member_count;
    /* Bounds member_count <= 6 for all later indexing. */
    if (member_count < ctx->brought_count || member_count > ctx->max_roster) {
        return false;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if (m < member_count) {
            if (!dfi_member_setup_valid(ctx, &side->members[m])) {
                return false;
            }
        } else if (!dfi_member_setup_is_zero(&side->members[m])) {
            return false;
        }
    }
    return true;
}

static duoforge_status dfi_init_member(const duoforge_member_setup *src, dfi_member *dst)
{
    uint8_t move_count = 0u;
    if (!dfi_u32_to_u16(src->species_id, &dst->species_id) || !dfi_u32_to_u16(src->hp_max, &dst->hp_max) ||
        !dfi_u32_to_u8(src->move_count, &move_count) || !dfi_u32_to_u8(src->mega_capable, &dst->mega_capable)) {
        return DUOFORGE_E_INVARIANT;
    }
    dst->hp = dst->hp_max;
    dst->move_count = move_count;
    for (uint32_t k = 0u; k < move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (!dfi_u32_to_u16(src->moves[k].move_id, &dst->moves[k].move_id) ||
            !dfi_u32_to_u8(src->moves[k].pp_max, &dst->moves[k].pp_max)) {
            return DUOFORGE_E_INVARIANT;
        }
        dst->moves[k].pp = dst->moves[k].pp_max;
    }
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_create(const duoforge_context *ctx, const duoforge_battle_setup *setup,
                                       duoforge_battle **out_battle)
{
    if (ctx == NULL || setup == NULL || out_battle == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_battle_setup s = *setup; /* read the input once */

    if (s.rng_initseq >= DFI_INITSEQ_LIMIT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        if (!dfi_side_setup_valid(ctx, &s.sides[side])) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }

    /* Build on a zeroed stack candidate; any failure below is an engine bug.
     * The battle starts at TEAM_SELECTION: nothing brought, no positions
     * filled, epoch 1, both sides requested (decision 0005). */
    struct duoforge_battle tmp;
    memset(&tmp, 0, sizeof tmp);
    for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
        tmp.context_fingerprint[i] = ctx->fingerprint[i];
    }
    dfi_rng_seed(&tmp.rng, s.rng_initstate, s.rng_initseq);
    tmp.next_activation_id = 1u;
    tmp.request_epoch = 1u;
    tmp.boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TEAM_SELECTION;
    tmp.request_mask = 3u;
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        const duoforge_side_setup *src = &s.sides[side];
        dfi_side *dst = &tmp.sides[side];
        if (!dfi_u32_to_u8(src->member_count, &dst->member_count)) {
            return DUOFORGE_E_INVARIANT;
        }
        for (uint32_t m = 0u; m < dst->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
            if (dfi_init_member(&src->members[m], &dst->members[m]) != DUOFORGE_OK) {
                return DUOFORGE_E_INVARIANT;
            }
        }
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
            dst->brought_order[i] = (uint8_t)DUOFORGE_ROSTER_NONE;
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            dfi_slot_clear(&dst->positions[p]);
        }
    }
    if (dfi_state_check(ctx, &tmp, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }

    struct duoforge_battle *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    *p = tmp;
    *out_battle = p;
    return DUOFORGE_OK;
}

void duoforge_battle_destroy(duoforge_battle *battle)
{
    dfi_free(battle);
}

duoforge_status duoforge_battle_clone(const duoforge_context *ctx, const duoforge_battle *src,
                                      duoforge_battle **out_battle)
{
    if (ctx == NULL || src == NULL || out_battle == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, src->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    struct duoforge_battle *p = dfi_alloc_zeroed(sizeof *p);
    if (p == NULL) {
        return DUOFORGE_E_OUT_OF_MEMORY;
    }
    *p = *src;
    *out_battle = p;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_copy(const duoforge_context *ctx, duoforge_battle *dst,
                                     const duoforge_battle *src)
{
    if (ctx == NULL || dst == NULL || src == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, dst->context_fingerprint) ||
        !dfi_context_fingerprint_matches(ctx, src->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (dst == src) {
        return DUOFORGE_OK;
    }
    *dst = *src;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_check(const duoforge_context *ctx, const duoforge_battle *battle)
{
    if (ctx == NULL || battle == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    return dfi_state_check(ctx, battle, NULL);
}

duoforge_status duoforge_battle_reseed(const duoforge_context *ctx, duoforge_battle *battle,
                                       uint64_t rng_initstate, uint64_t rng_initseq)
{
    if (ctx == NULL || battle == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, battle->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (rng_initseq >= DFI_INITSEQ_LIMIT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    dfi_rng_seed(&battle->rng, rng_initstate, rng_initseq);
    return DUOFORGE_OK;
}
