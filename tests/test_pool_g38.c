/*
 * duoforge.state.pool_g38 (white-box): step G38 of the content expansion, Imprison, in the POOL tail's `imprison` flag of each
 * position (decision 0015 section 7), in the events (VOLATILE_START with the detail DUOFORGE_VOLATILE_IMPRISON for
 * `-start|X|move: Imprison`, CANT with the cause DUOFORGE_CAUSE_IMPRISON and the stopped move in id for
 * `cant|X|move: Imprison|Move`) and in the view extension (decision 0018: bit 2 IMPRISON of the position's volatiles, supported
 * bit 12). The pin: data/moves.ts:9489-9523 imprison (onFoeDisableMove :9504-9510, onFoeBeforeMove at priority 4 :9511-9519),
 * sim/pokemon.ts:1025-1027 and :1625-1636 (the disable is hidden), sim/side.ts:718-737 (the choice of such a move is rejected),
 * sim/pokemon.ts:1508 clearVolatile (it ends with the occupant), data/moves.ts:4754-4775 encore and data/conditions.ts:324-363
 * choicelock (their onDisableMove).
 *
 * The recorded battles (under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares every HP, stage, request and event the reference shows, and so the
 * moves that a foe's request offers while an Imprison stands (the converter reads the harness's `hidden` rows: the request shows a
 * hidden-disabled move as enabled for the last active Pokemon, the choice of it is rejected, and with no move left the choice
 * is Struggle). Here the state that the reference does not show is read after every step: the tail's flag of the four positions,
 * the step's events and both viewers' whole extension.
 *
 * The rows are what the protocol lines say alone, derived by tools/reference/test_trace_to_c.py from the committed traces, which
 * requires this table to be exactly that: after each step the positions that stand with Imprison (bit side * 2 + slot: the line
 * `|-start|X|move: Imprison` sets it, a switch, a drag or a faint of that position clears it), the number of such start lines of
 * the step (`started`) and of `cant` lines naming Imprison (`cant`).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

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

/* ROWS-BEGIN */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t mask;
    uint32_t started;
    uint32_t cant;
} rows[] = {
    {"g38_imprison_mask", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_mask", 1u, 0x1u, 1u, 1u},
    {"g38_imprison_mask", 2u, 0x1u, 0u, 0u},
    {"g38_imprison_mask", 3u, 0x1u, 0u, 0u},
    {"g38_imprison_mask", 4u, 0x1u, 0u, 0u},
    {"g38_imprison_struggle", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_struggle", 1u, 0x1u, 1u, 0u},
    {"g38_imprison_struggle", 2u, 0x1u, 0u, 0u},
    {"g38_imprison_struggle", 3u, 0x1u, 0u, 0u},
    {"g38_imprison_cant", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_cant", 1u, 0x1u, 1u, 1u},
    {"g38_imprison_cant", 2u, 0x0u, 0u, 0u},
    {"g38_imprison_cant", 3u, 0x0u, 0u, 0u},
    {"g38_imprison_encore", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_encore", 1u, 0x0u, 0u, 0u},
    {"g38_imprison_encore", 2u, 0x0u, 0u, 0u},
    {"g38_imprison_encore", 3u, 0x1u, 1u, 1u},
    {"g38_imprison_encore", 4u, 0x1u, 0u, 0u},
    {"g38_imprison_encore", 5u, 0x1u, 0u, 0u},
    {"g38_imprison_choice", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_choice", 1u, 0x1u, 1u, 0u},
    {"g38_imprison_choice", 2u, 0x1u, 0u, 0u},
    {"g38_imprison_choice", 3u, 0x1u, 0u, 0u},
    {"g38_imprison_choice", 4u, 0x1u, 0u, 0u},
    {"g38_imprison_end", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_end", 1u, 0x1u, 1u, 0u},
    {"g38_imprison_end", 2u, 0x1u, 0u, 0u},
    {"g38_imprison_end", 3u, 0x0u, 0u, 0u},
    {"g38_imprison_end", 4u, 0x0u, 0u, 0u},
    {"g38_imprison_pair", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_pair", 1u, 0x3u, 2u, 1u},
    {"g38_imprison_pair", 2u, 0x3u, 0u, 0u},
    {"g38_imprison_pair", 3u, 0x3u, 0u, 0u},
    {"g38_imprison_struggle_b", 0u, 0x0u, 0u, 0u},
    {"g38_imprison_struggle_b", 1u, 0x1u, 1u, 0u},
    {"g38_imprison_struggle_b", 2u, 0x1u, 0u, 0u},
    {"g38_imprison_struggle_b", 3u, 0x1u, 0u, 0u},
};
/* ROWS-END */

static const char *const battle_names[] = {"g38_imprison_mask",   "g38_imprison_struggle", "g38_imprison_cant", "g38_imprison_encore",
                                           "g38_imprison_choice", "g38_imprison_end",      "g38_imprison_pair", "g38_imprison_struggle_b"};

static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    uint32_t cants = 0u;
    uint32_t starts = 0u;
    for (size_t n = 0u; n < sizeof battle_names / sizeof battle_names[0]; ++n) {
        const df_conf_battle *cb = find(battle_names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            if (!DF_CHECK(t, dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res,
                                                          buffers) == DUOFORGE_OK)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            int row = -1;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, battle_names[n]) == 0 && rows[r].step == si) {
                    row = (int)r;
                }
            }
            if (!DF_CHECK(t, row >= 0)) {
                fprintf(stderr, "  %s step %u: no row\n", battle_names[n], si);
                continue;
            }
            /* The tail: the flag of each position. */
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t k = 0u; k < 2u; ++k) {
                    const uint32_t want = (rows[row].mask >> (s * 2u + k)) & 1u;
                    if (!DF_CHECK_EQ_U64(t, b->tail.sides[s].positions[k].imprison, want)) {
                        fprintf(stderr, "  %s step %u: position %u of side %u\n", battle_names[n], si, k, s);
                    }
                }
            }
            /* The events: both viewers see both kinds of line (public); the cant line names a move of the pool and no PP is
             * used; the start line has the user's position and no source. */
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t started = 0u;
                uint32_t cant = 0u;
                for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                    const duoforge_event *e = &buffers[viewer].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_VOLATILE_START && e->detail == (uint8_t)DUOFORGE_VOLATILE_IMPRISON) {
                        started += 1u;
                        DF_CHECK(t, e->position < 4u);
                    } else if (e->kind == (uint8_t)DUOFORGE_EVENT_CANT && e->cause == (uint8_t)DUOFORGE_CAUSE_IMPRISON) {
                        cant += 1u;
                        DF_CHECK(t, e->position < 4u && e->id < DFI_POOL_MOVE_COUNT && e->id != DFI_MOVE_STRUGGLE);
                    }
                }
                if (!DF_CHECK(t, started == rows[row].started && cant == rows[row].cant)) {
                    fprintf(stderr, "  %s step %u viewer %u: %u starts (want %u), %u cants (want %u)\n", battle_names[n], si, viewer,
                            started, rows[row].started, cant, rows[row].cant);
                }
                if (viewer == 0u) {
                    starts += started;
                    cants += cant;
                }
            }
            /* The extension: bit 2 of the position's volatiles is the flag, public for both viewers. */
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK);
                for (uint32_t s = 0u; s < 2u; ++s) {
                    for (uint32_t k = 0u; k < 2u; ++k) {
                        const uint32_t has = (ext[viewer].sides[s].positions[k].volatiles & DUOFORGE_POSITION_EXT_IMPRISON) != 0u;
                        const uint32_t want = (rows[row].mask >> (s * 2u + k)) & 1u;
                        if (!DF_CHECK_EQ_U64(t, has, want)) {
                            fprintf(stderr, "  %s step %u viewer %u: view bit of position %u of side %u\n", battle_names[n], si,
                                    viewer, k, s);
                        }
                    }
                }
                DF_CHECK(t, (ext[viewer].supported & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_IMPRISON)) != 0u);
                *compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
    /* The battles show the start and the stop of a queued move, both. */
    DF_CHECK(t, starts >= 8u && cants >= 4u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g38");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The new public values and the ids that the step uses. */
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_IMPRISON, 8u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_CAUSE_IMPRISON, 21u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_IMPRISON, 55u);
    DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_IMPRISON].special == DFI_SPECIAL_IMPRISON);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_IMPRISON] != 0u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_POSITION_EXT_IMPRISON, 4u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_IMPRISON, 12u);

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    check_battles(&t, kd, &compared);
    DF_CHECK_EQ_U64(&t, compared, 4u * (uint32_t)(sizeof rows / sizeof rows[0]));

    duoforge_context_destroy(kp);
    duoforge_context_destroy(kd);
    return df_test_end(&t);
}
