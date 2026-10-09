/*
 * duoforge.state.pool_g7 (white-box): step G7 of the content expansion, Wide Guard, in the POOL state tail
 * (decision 0015 section 7) and in the POOL view extension (decision 0018).
 *
 * The recorded battles (g7_wide_guard_a, _b, _ally and _pivot under "data": "pool") are replayed through the step with
 * the reference's draws, as in duoforge.reference.conformance_pool_data, which compares everything that the reference
 * shows (the -singleturn line, one -activate line per guarded target, the failed Wide Guard, the Protects that roll
 * against the counter that Wide Guard raised). Here is what the reference does not show, after every step:
 *
 *   - the side flag of the tail (wide_guard) is what the protocol lines say alone (the -singleturn line of the user
 *     sets its side, the |upkeep| line clears it: tools/reference/test_trace_to_c.py derives the rows of the table
 *     below from the committed traces and requires the table to be exactly that), so it is set only at a boundary
 *     inside a turn (a PIVOT, the guard is live at a mid-turn decision) and never at a TURN boundary;
 *   - the POOL view extension of both viewers, byte for byte: revision, viewer, epoch, the supported bits of the
 *     build and `guard_flags` of each side equal to the row, nothing else (no hidden counter leaves the engine);
 *   - the stall counter that Wide Guard raises without rolling (the user's stall level after the step).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
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

/* The side flags of Wide Guard after each step of the recorded battles (bit = side). */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t guard;
} guard_rows[] = {
    {"g7_wide_guard_a", 0u, 0x0u},
    {"g7_wide_guard_a", 1u, 0x0u},
    {"g7_wide_guard_a", 2u, 0x0u},
    {"g7_wide_guard_a", 3u, 0x0u},
    {"g7_wide_guard_a", 4u, 0x0u},
    {"g7_wide_guard_a", 5u, 0x0u},
    {"g7_wide_guard_b", 0u, 0x0u},
    {"g7_wide_guard_b", 1u, 0x0u},
    {"g7_wide_guard_b", 2u, 0x0u},
    {"g7_wide_guard_b", 3u, 0x0u},
    {"g7_wide_guard_b", 4u, 0x0u},
    {"g7_wide_guard_ally", 0u, 0x0u},
    {"g7_wide_guard_ally", 1u, 0x0u},
    {"g7_wide_guard_ally", 2u, 0x0u},
    {"g7_wide_guard_ally", 3u, 0x0u},
    {"g7_wide_guard_ally", 4u, 0x0u},
    {"g7_wide_guard_ally", 5u, 0x0u},
    {"g7_wide_guard_pivot", 0u, 0x0u},
    {"g7_wide_guard_pivot", 1u, 0x1u},
    {"g7_wide_guard_pivot", 2u, 0x0u},
    {"g7_wide_guard_pivot", 3u, 0x0u},
};

/* After which step of which battle a Pokemon's stall level is what, as Wide Guard and Protect leave it (positions are
 * side * 2 + slot): the counter that Wide Guard raises without a roll. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t position;
    uint32_t level;
} stall_rows[] = {
    {"g7_wide_guard_a", 1u, 0u, 1u},
    {"g7_wide_guard_a", 1u, 1u, 1u},
    {"g7_wide_guard_a", 2u, 0u, 0u},
    {"g7_wide_guard_a", 2u, 1u, 0u},
    {"g7_wide_guard_b", 1u, 0u, 0u},
    {"g7_wide_guard_b", 1u, 1u, 1u},
    {"g7_wide_guard_b", 2u, 0u, 1u},
    {"g7_wide_guard_b", 2u, 1u, 2u},
    {"g7_wide_guard_b", 3u, 0u, 2u},
    {"g7_wide_guard_b", 3u, 1u, 0u},
    {"g7_wide_guard_b", 4u, 0u, 0u},
    {"g7_wide_guard_b", 4u, 1u, 1u},
    {"g7_wide_guard_ally", 1u, 0u, 1u},
    {"g7_wide_guard_ally", 1u, 1u, 1u},
    {"g7_wide_guard_pivot", 1u, 0u, 1u},
};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g7");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    static const char *const names[] = {"g7_wide_guard_a", "g7_wide_guard_b", "g7_wide_guard_ally",
                                        "g7_wide_guard_pivot"};
    uint32_t compared = 0u;
    uint32_t live_mid_turn = 0u;
    (void)conf_events;
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(&t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
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
            uint32_t guard = 0xFFu;
            for (size_t r = 0u; r < sizeof guard_rows / sizeof guard_rows[0]; ++r) {
                if (strcmp(guard_rows[r].battle, names[n]) == 0 && guard_rows[r].step == si) {
                    guard = guard_rows[r].guard;
                }
            }
            if (!DF_CHECK(&t, guard != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            /* The tail, and the boundary: a guard is up only inside a turn. */
            DF_CHECK_EQ_U64(&t, b->tail.sides[0].wide_guard, (guard >> 0u) & 1u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].wide_guard, (guard >> 1u) & 1u);
            if (guard != 0u) {
                DF_CHECK_EQ_U64(&t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
                live_mid_turn += 1u;
            }
            if (b->boundary_kind == DUOFORGE_BOUNDARY_TURN) {
                DF_CHECK_EQ_U64(&t, guard, 0u);
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                 duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                /* The mask is the build's (later steps add their bits); the bits of G8, G11 and G7 are checked here. */
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(&t, (want.supported & (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD))) ==
                                (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD)));
                for (uint32_t s = 0u; s < 2u; ++s) {
                    want.sides[s].guard_flags = ((guard >> s) & 1u) != 0u ? (uint8_t)DUOFORGE_SIDE_GUARD_WIDE_GUARD : 0u;
                }
                for (uint32_t g42f = 0u; g42f < 4u; ++g42f) { /* step G42: move_failed is the last move result FALSE */
                    const uint32_t g42last = ((uint32_t)b->tail.sides[g42f / 2u].positions[g42f % 2u].move_result >> 2) & 3u;
                    want.sides[g42f / 2u].positions[g42f % 2u].move_failed = g42last == 2u ? 1u : 0u;
                }                if (!DF_CHECK(&t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (want guards 0x%x)\n",
                            names[n], si, viewer, guard);
                }
                compared += 1u;
            }
            DF_CHECK(&t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
            for (size_t r = 0u; r < sizeof stall_rows / sizeof stall_rows[0]; ++r) {
                if (strcmp(stall_rows[r].battle, names[n]) == 0 && stall_rows[r].step == si) {
                    const uint32_t flat = stall_rows[r].position;
                    DF_CHECK_EQ_U64(&t, b->sides[flat / 2u].positions[flat % 2u].stall_level, stall_rows[r].level);
                }
            }
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof guard_rows / sizeof guard_rows[0]));
    /* The guard is live at a mid-turn decision in the pivot battle (and only there). */
    DF_CHECK(&t, live_mid_turn != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
