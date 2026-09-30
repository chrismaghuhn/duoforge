#include "state/transition.h"

#include "core/arith.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/invariants.h"

duoforge_status dfi_apply_team_selection(const duoforge_context *ctx, struct duoforge_battle *b,
                                         const dfi_team_picks *picks)
{
    if (b->boundary_kind != DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        return DUOFORGE_E_INVARIANT;
    }
    if (b->request_epoch == UINT32_MAX) {
        return DUOFORGE_E_EXHAUSTED;
    }
    const uint32_t brought_count = ctx->brought_count;
    if (brought_count < 1u || brought_count > DUOFORGE_MAX_ROSTER) {
        return DUOFORGE_E_INVARIANT;
    }
    struct duoforge_battle tmp = *b;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_side *side = &tmp.sides[s];
        uint32_t mask = 0u;
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
            if (i < brought_count) {
                const uint32_t r = picks->picks[s][i];
                if (r >= DUOFORGE_MAX_ROSTER || r >= side->member_count || ((mask >> r) & 1u) != 0u) {
                    return DUOFORGE_E_INVARIANT; /* out of range or duplicate: domain violation */
                }
                mask |= 1u << r;
                side->brought_order[i] = picks->picks[s][i];
            } else {
                side->brought_order[i] = (uint8_t)DUOFORGE_ROSTER_NONE;
            }
        }
        side->brought_mask = (uint8_t)mask; /* mask < 64 */
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE && k < brought_count; ++k) {
            dfi_binding binding = {{0u, 0u}, 0u};
            const dfi_position_id pos = {(uint8_t)s, (uint8_t)k};
            const duoforge_status st = dfi_place(&tmp, pos, picks->picks[s][k], &binding);
            if (st != DUOFORGE_OK) {
                return st == DUOFORGE_E_EXHAUSTED ? DUOFORGE_E_EXHAUSTED : DUOFORGE_E_INVARIANT;
            }
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const uint32_t occupied = dfi_side_occupied_mask(&tmp.sides[s]);
        tmp.sides[s].requested_slots = (uint8_t)occupied; /* <= 3 */
    }
    tmp.boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TURN;
    tmp.request_mask = 3u;
    uint32_t next_epoch = 0u;
    if (!dfi_add_u32(tmp.request_epoch, 1u, &next_epoch)) {
        return DUOFORGE_E_EXHAUSTED; /* unreachable after the check above */
    }
    tmp.request_epoch = next_epoch;
    if (dfi_state_check(ctx, &tmp, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    *b = tmp;
    return DUOFORGE_OK;
}
