/*
 * duoforge.state.pool_g20_protect (white-box): step G20, Spiky Shield, in the POOL state tail rev 3 (decision 0015 section 7: the
 * protect_kind of a position; the schema is 0x0503 since rev 5).
 *
 * The recorded battles (g20_spiky_shield_* under "data": "pool") are replayed through the step with the reference's draws,
 * as in duoforge.reference.conformance_pool_data, which compares everything that the reference shows (the -singleturn
 * line, the -activate line of the stopped move, the damage to a contact attacker with [from] Spiky Shield [of] the
 * holder, the attacker that the punishment knocks out, the stall counter that Protect and Spiky Shield share). Here is
 * what the reference does not show, after every step:
 *
 *   - the tail's protect_kind of each position is what the protocol lines say alone (the Spiky Shield move line followed
 *     by `-singleturn|X|move: Protect` sets 1, the |upkeep| line clears it: tools/reference/test_trace_to_c.py derives
 *     the rows of the table below from the committed traces and requires the table to be exactly that), so the variant is
 *     live at a boundary inside a turn (a PIVOT) and never at a TURN boundary;
 *   - the state round-trips through its encoding at every boundary, the variant included (schema 0x0503 since rev 5), and the
 *     decoded state has the same tail;
 *   - the position's Protect volatile is up exactly when the move's own -singleturn line says so.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "codec/state_codec.h"
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

/* The protect_kind of each position (side * 2 + slot) after each step of the recorded battles. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t kind[4];
} kind_rows[] = {
    {"g20_spiky_shield_a", 0u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_a", 1u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_a", 2u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_a", 3u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_a", 4u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_a", 5u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_ko", 0u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_ko", 1u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_ko", 2u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_ko", 3u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_ko", 4u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_pivot", 0u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_pivot", 1u, {1u, 0u, 0u, 0u}},
    {"g20_spiky_shield_pivot", 2u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_pivot", 3u, {0u, 0u, 0u, 0u}},
    {"g20_spiky_shield_pivot", 4u, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g20_spiky_shield_a", "g20_spiky_shield_ko", "g20_spiky_shield_pivot"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g20_protect");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t live = 0u;
    uint32_t mid_turn = 0u;
    (void)conf_events;
    DF_CHECK_EQ_U64(&t, DFI_PROTECT_SPIKY_SHIELD, 1u);
    DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV5, 0x0503u); /* the schema of the state since rev 5 (rev 4 is 0x0403) */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_SPIKYSHIELD] != 0u && dfi_support.moves[DFI_MOVE_BANEFULBUNKER] == 0u &&
                     dfi_support.moves[DFI_MOVE_KINGSSHIELD] == 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_SPIKYSHIELD].special, DFI_SPECIAL_SPIKY_SHIELD);
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
            uint32_t want[4] = {0xFFu, 0xFFu, 0xFFu, 0xFFu};
            for (size_t r = 0u; r < sizeof kind_rows / sizeof kind_rows[0]; ++r) {
                if (strcmp(kind_rows[r].battle, names[n]) == 0 && kind_rows[r].step == si) {
                    for (uint32_t k = 0u; k < 4u; ++k) {
                        want[k] = kind_rows[r].kind[k];
                    }
                }
            }
            if (!DF_CHECK(&t, want[0] != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            uint32_t any = 0u;
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const uint32_t kind = b->tail.sides[flat / 2u].positions[flat % 2u].protect_kind;
                DF_CHECK_EQ_U64(&t, kind, want[flat]);
                /* The variant belongs to the volatile. */
                DF_CHECK(&t, kind == 0u || ((uint32_t)b->sides[flat / 2u].positions[flat % 2u].flags & DFI_VOL_PROTECT) != 0u);
                any |= kind;
            }
            live += any != 0u ? 1u : 0u;
            if (any != 0u) {
                DF_CHECK_EQ_U64(&t, b->boundary_kind, DUOFORGE_BOUNDARY_PIVOT); /* it ends in the residual */
                mid_turn += 1u;
            }
            /* The encoding round trip, the variant included. */
            uint8_t enc[DF_STATE_ENCODED_MAX];
            size_t written = 0u;
            duoforge_battle *copy = NULL;
            if (DF_CHECK(&t, duoforge_battle_encode(ctx, b, enc, sizeof enc, &written) == DUOFORGE_OK &&
                                 written == DFI_STATE_POOL_ENCODED_SIZE) &&
                DF_CHECK(&t, duoforge_battle_create(ctx, &setup, &copy) == DUOFORGE_OK && copy != NULL)) {
                DF_CHECK(&t, duoforge_battle_decode(ctx, copy, enc, written) == DUOFORGE_OK);
                DF_CHECK(&t, memcmp(&copy->tail, &b->tail, sizeof b->tail) == 0);
                bool equal = false;
                DF_CHECK(&t, duoforge_battle_equal(ctx, b, copy, &equal) == DUOFORGE_OK && equal);
            }
            if (copy != NULL) {
                duoforge_battle_destroy(copy);
            }
            compared += 1u;
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, (uint32_t)(sizeof kind_rows / sizeof kind_rows[0]));
    /* The variant is live at a boundary inside a turn (the pivot battle), and only there. */
    DF_CHECK(&t, live != 0u && mid_turn != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
