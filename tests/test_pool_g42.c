/*
 * duoforge.state.pool_g42 (white-box): step G42, Roost and Stomping Tantrum (decision 0015 section 7, tail rev 4: move_result,
 * single_turn; decision 0018: the ROOST volatile of the position, supported bit 40; MOVE_FAILED, bit 41, stays clear).
 *
 * The recorded battles (g42_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool, which compares what the reference shows (the damage, the Flying type of the target, the
 * doubling of Stomping Tantrum). Here is what the reference does not show, after every step of each battle:
 *
 *   - the move result of each position, both of its two-bit values: `this` (bits 0-1, the turn so far) and `last` (bits 2-3,
 *     the turn before), against the table below. The table is the pin's moveThisTurnResult and moveLastTurnResult, read off
 *     the protocol lines of the committed traces: TRUE (1) when a target took the move (damage, a heal, a status, a Protect
 *     that went up), FALSE (2) for a miss, an immunity, a failed move (`-fail`, a Protect that fails in a row, Recover at full
 *     HP) and a stop before the move (`cant`, a full paralysis), NULL (3) for a move that Protect took (NOT_FAIL: it is no
 *     failure) and a recharge stop, UNDEFINED (0) for a position with no move this turn. At the end of a turn `this` is
 *     undefined and `last` holds the turn's results; a position that fainted or switched out is undefined in both, and the
 *     boundary of a pivot or a replacement inside a turn shows the results so far (`this`) and the turn before (`last`).
 *   - the ROOST bit of single_turn, which is set at the Roost's heal and ends in the residual of its turn (order 25): it is set
 *     only at a boundary inside the Roost turn (the pivot of g42_roost_pivot), and clear at every turn end.
 *   - the unclassified bits (4: this turn, 5: last turn). Every exit of the move body writes a class (true, false, null or the
 *     charge's null), so an action is unclassified only if no exit writes one, and none of these battles has that: the table
 *     has no unclassified position. Bits 6-7 are zero. Stomping Tantrum refuses on the last bit (below).
 *   - the classes of the review: a Protect that succeeds (TRUE), a repeated Protect that fails (FALSE), a Tailwind that sets
 *     the side (TRUE) and one that fails on a side that has it (FALSE), a self boost of Coil (TRUE), the Tantrum after each.
 *   - the POOL view extension of both viewers, byte for byte: the revision, the viewer, the epoch, the supported bits of the
 *     build (bit 40 yes, bit 41 no), the ROOST presence bit of each position and MOVE_FAILED = the last result is FALSE.
 *   - an unclassified last result (bit 5, which no battle here produces) makes Stomping Tantrum refuse with E_UNSUPPORTED.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The boundary after each step of each battle: the move result of each position (this, last) and its ROOST bit. Derived
 * from the committed traces as described in the header. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t flat;
    uint32_t this_result;
    uint32_t last_result;
    uint32_t roost;
    uint32_t uthis;
    uint32_t ulast;
} rows[] = {
    {"g42_roost_full", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_full", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_full", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_full", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_full", 1u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_full", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 1u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_full", 2u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_full", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 3u, 0u, 0u, 3u, 0u, 0u, 0u},
    {"g42_roost_full", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 3u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 3u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_full", 4u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_full", 4u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_full", 4u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 1u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 1u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 2u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 3u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 3u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 3u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 4u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 4u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_switch", 4u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_heal", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_heal", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_heal", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_heal", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 1u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 2u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 3u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_heal", 3u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_heal", 3u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 4u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 4u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_heal", 4u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 1u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 1u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 2u, 0u, 1u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 2u, 1u, 2u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 2u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 2u, 3u, 2u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 3u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 3u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_paralysis", 3u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 1u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 3u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tantrum_miss", 3u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 1u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 2u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 3u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_ground_order", 3u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_pivot", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_pivot", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_pivot", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_pivot", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_roost_pivot", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 1u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_pivot", 1u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 2u, 0u, 1u, 1u, 1u, 0u, 0u},
    {"g42_roost_pivot", 2u, 1u, 1u, 2u, 0u, 0u, 0u},
    {"g42_roost_pivot", 2u, 2u, 2u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 2u, 3u, 1u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_roost_pivot", 3u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_roost_pivot", 3u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 2u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_tantrum", 2u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 2u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 3u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 3u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 4u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 4u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_protect_stall_tantrum", 4u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 2u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 2u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 3u, 0u, 0u, 2u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 3u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 3u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 4u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 4u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_tailwind_tantrum", 4u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 0u, 0u, 0u, 0u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 0u, 1u, 0u, 0u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 0u, 2u, 0u, 0u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 0u, 3u, 0u, 0u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 1u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 1u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 1u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 1u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 2u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 2u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 2u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 2u, 3u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 3u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 3u, 1u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 3u, 2u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 3u, 3u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 4u, 0u, 0u, 1u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 4u, 1u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 4u, 2u, 0u, 2u, 0u, 0u, 0u},
    {"g42_coil_tantrum", 4u, 3u, 0u, 1u, 0u, 0u, 0u},
};

static const char *const names[] = {"g42_roost_full", "g42_tantrum_switch", "g42_roost_heal", "g42_tantrum_paralysis",
                                    "g42_tantrum_miss", "g42_roost_ground_order", "g42_roost_pivot", "g42_protect_tantrum",
                                    "g42_protect_stall_tantrum", "g42_tailwind_tantrum", "g42_coil_tantrum"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g42");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t roosts = 0u;
    uint32_t trues = 0u;
    uint32_t falses = 0u;
    uint32_t nulls = 0u;
    uint32_t unclass = 0u;
    uint32_t steps_run = 0u;

    /* The bits of the step: the move result classes, the Roost volatile, the supported view bits (decision 0018 section 7.1). */
    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_TRUE, 1u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_FALSE, 2u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_NULL, 3u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_UNCLASSIFIED_NOW, 0x10u);
    DF_CHECK_EQ_U64(&t, DFI_MOVE_RESULT_UNCLASSIFIED_LAST, 0x20u);
    DF_CHECK_EQ_U64(&t, DFI_TAIL_MOVE_RESULT_MASK, 0x3Fu);
    DF_CHECK_EQ_U64(&t, DFI_SINGLE_TURN_ROOST, 2u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_ROOST, 40u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_MOVE_FAILED, 41u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_POSITION_EXT_ROOST, 0x00100000u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ROOST)) != 0u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_MOVE_FAILED)) == 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_ROOST] != 0u && dfi_support.moves[DFI_MOVE_STOMPINGTANTRUM] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_ROOST].special, DFI_SPECIAL_ROOST);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_STOMPINGTANTRUM].special, DFI_SPECIAL_STOMPING_TANTRUM);

    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", names[n], duoforge_status_name(created));
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                  DUOFORGE_OK)) {
                break;
            }
            steps_run += 1u;
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                uint32_t want_this = 0u;
                uint32_t want_last = 0u;
                uint32_t want_roost = 0u;
                uint32_t want_uthis = 0u;
                uint32_t want_ulast = 0u;
                uint32_t found = 0u;
                for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                    if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si && rows[r].flat == flat) {
                        want_this = rows[r].this_result;
                        want_last = rows[r].last_result;
                        want_roost = rows[r].roost;
                        want_uthis = rows[r].uthis;
                        want_ulast = rows[r].ulast;
                        found += 1u;
                    }
                }
                if (!DF_CHECK(&t, found == 1u)) {
                    fprintf(stderr, "  %s step %u position %u: %u rows\n", names[n], si, flat, found);
                    continue;
                }
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                const uint32_t mr = (uint32_t)tp->move_result;
                const bool ok = (mr & 3u) == want_this && ((mr >> DFI_MOVE_RESULT_LAST_SHIFT) & 3u) == want_last &&
                                (mr & 0xF0u) == ((want_uthis != 0u ? 0x10u : 0u) | (want_ulast != 0u ? 0x20u : 0u)) &&
                                ((tp->single_turn & DFI_SINGLE_TURN_ROOST) != 0u ? 1u : 0u) == want_roost &&
                                (tp->single_turn & ~DFI_TAIL_SINGLE_TURN_MASK) == 0u;
                if (!DF_CHECK(&t, ok)) {
                    fprintf(stderr, "  %s step %u position %u: move_result %#x (this %u last %u roost %u), want this %u last %u roost %u\n",
                            names[n], si, flat, mr, mr & 3u, (mr >> DFI_MOVE_RESULT_LAST_SHIFT) & 3u,
                            (tp->single_turn & DFI_SINGLE_TURN_ROOST) != 0u ? 1u : 0u, want_this, want_last, want_roost);
                }
                roosts += want_roost;
            }
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation_ext ext;
                DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK);
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext exp;
                memset(&exp, 0, sizeof exp);
                exp.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                exp.player = (uint8_t)viewer;
                exp.epoch = ob.epoch;
                exp.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                    uint32_t want_roost = 0u;
                    uint32_t want_last = 0u;
                    for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                        if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si && rows[r].flat == flat) {
                            want_roost = rows[r].roost;
                            want_last = rows[r].last_result;
                        }
                    }
                    /* the view: ROOST while the Roost turn is open, MOVE_FAILED = the last result is FALSE (classified: an
                     * unclassified exit leaves no FALSE in the bits, so it reads 0; bit 41 is not supported and says so) */
                    exp.sides[flat / 2u].positions[flat % 2u].volatiles =
                        want_roost != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_ROOST : 0u;
                    exp.sides[flat / 2u].positions[flat % 2u].move_failed = want_last == 2u ? 1u : 0u;
                    exp.sides[flat / 2u].positions[flat % 2u].encore_slot = tp->encore_slot;
                }
                if (!DF_CHECK(&t, memcmp(&ext, &exp, sizeof exp) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the expected one\n", names[n], si,
                            viewer);
                }
                compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }

    /* A Stomping Tantrum whose user's last result carries the unclassified bit refuses with E_UNSUPPORTED (decision 0015
     * section 7): g42_tantrum_switch, after step 3 the Dragonite that switched in has no last result (zero), so the bit alone
     * is valid; its step 4 is a Stomping Tantrum. */
    {
        const df_conf_battle *cb = find("g42_tantrum_switch");
        if (DF_CHECK(&t, cb != NULL && cb->step_count == 5u)) {
            duoforge_battle_setup setup;
            build_setup(cb, &setup);
            duoforge_battle *b = NULL;
            if (DF_CHECK(&t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
                duoforge_status st = DUOFORGE_OK;
                for (uint32_t si = 0u; si < 4u && st == DUOFORGE_OK; ++si) {
                    duoforge_decision_bundle bd;
                    bundle_of(&cb->steps[si], b, &bd);
                    duoforge_step_result res;
                    uint32_t used = 0u;
                    st = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[si].tape_off], cb->steps[si].tape_len, &used,
                                              &res);
                }
                DF_CHECK_EQ_U64(&t, st, DUOFORGE_OK);
                dfi_tail_pos *dragonite = &b->tail.sides[0].positions[0];
                DF_CHECK_EQ_U64(&t, dragonite->move_result, 0u);
                dragonite->move_result = (uint8_t)DFI_MOVE_RESULT_UNCLASSIFIED_LAST; /* the last result is unclassified */
                DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                bundle_of(&cb->steps[4], b, &bd);
                duoforge_step_result res;
                uint32_t used = 0u;
                DF_CHECK_EQ_U64(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[4].tape_off], cb->steps[4].tape_len,
                                                         &used, &res),
                                DUOFORGE_E_UNSUPPORTED);
                duoforge_battle_destroy(b);
            }
        }
    }

    for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
        const uint32_t v = rows[r].this_result != 0u ? rows[r].this_result : rows[r].last_result;
        trues += v == 1u ? 1u : 0u;
        falses += v == 2u ? 1u : 0u;
        nulls += v == 3u ? 1u : 0u;
        unclass += rows[r].uthis != 0u || rows[r].ulast != 0u ? 1u : 0u;
    }
    fprintf(stderr, "  %u steps in %zu battles; %u boundary positions; results true %u, false %u, null %u, unclassified %u; %u Roost "
                    "boundaries; %u viewer extensions\n",
            steps_run, sizeof names / sizeof names[0], steps_run * 4u, trues, falses, nulls, unclass, roosts, compared);
    DF_CHECK_EQ_U64(&t, sizeof rows / sizeof rows[0], 196u); /* 49 steps of eleven battles, four positions each */ /* 31 steps of seven battles, four positions each */
    DF_CHECK_EQ_U64(&t, compared, 2u * steps_run);
    DF_CHECK(&t, trues != 0u && falses != 0u && nulls != 0u && roosts == 1u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
