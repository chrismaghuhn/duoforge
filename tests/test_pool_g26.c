/*
 * duoforge.state.pool_g26 (white-box): step G26 of the content expansion, Perish Song: the perish counter of the POOL
 * state tail (perish of a position, decision 0015 section 7: the duration, 4 from the cast, counted down by the residual
 * handler of order 24) and the view extension (decision 0018: the `perish` field of the position, the count that the game
 * announced, supported bit 4).
 *
 * The recorded battles (g26_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything the reference shows: every line of the casts, the
 * counts and the faints, the shuffles of the residual ties, and the win. Here the state that the reference does not
 * show is read after every step: the tail's counter of every position (3, 2, 1 after the residual that announced it,
 * 0 for none) and both viewers' extension, which carries the same count (public: every count is a line).
 *
 *   g26_perish_song     the cast (Protect does not stop it, Good as Gold is immune), Kingambit switches out and loses it,
 *                       a second cast that infects only the newcomer, the faints before the upkeep line
 *   g26_perish_recast   a cast that fails (everybody has it), a tie of two holders of the same Speed
 *   g26_perish_end      two cycles; the last Pokemon of both sides faint together and the last to faint wins
 *   g26_perish_survivor_a, _b   a Pokemon that the second cast did not infect (Good as Gold) wins with Protect: the battle ends at
 *                       the faint point of its stall counter and the tie with Protect's volatile decides whether it keeps Protect
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

/* The battle `name` after its first `steps` steps (the reference's draws as the tape); NULL when it fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}


/* After each step of each battle: the Perish count that the protocol lines have announced for each position (a
 * `-start|X|perishN` line; the cast's own line is [silent]; a faint, a switch or a drag clears it); tools/reference/
 * test_trace_to_c.py derives the rows from the committed traces and requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint8_t perish[4];
} rows[] = {
    {"g26_perish_song", 0u, {0u, 0u, 0u, 0u}},
    {"g26_perish_song", 1u, {3u, 0u, 3u, 3u}},
    {"g26_perish_song", 2u, {2u, 0u, 2u, 3u}},
    {"g26_perish_song", 3u, {1u, 0u, 1u, 2u}},
    {"g26_perish_song", 4u, {0u, 0u, 0u, 1u}},
    {"g26_perish_song", 5u, {0u, 0u, 0u, 1u}},
    {"g26_perish_song", 6u, {0u, 0u, 0u, 0u}},
    {"g26_perish_recast", 0u, {0u, 0u, 0u, 0u}},
    {"g26_perish_recast", 1u, {0u, 0u, 0u, 0u}},
    {"g26_perish_recast", 2u, {3u, 3u, 3u, 0u}},
    {"g26_perish_recast", 3u, {2u, 2u, 2u, 3u}},
    {"g26_perish_recast", 4u, {1u, 1u, 1u, 2u}},
    {"g26_perish_recast", 5u, {0u, 0u, 0u, 1u}},
    {"g26_perish_recast", 6u, {0u, 0u, 0u, 1u}},
    {"g26_perish_recast", 7u, {0u, 0u, 0u, 0u}},
    {"g26_perish_end", 0u, {0u, 0u, 0u, 0u}},
    {"g26_perish_end", 1u, {3u, 3u, 3u, 3u}},
    {"g26_perish_end", 2u, {2u, 2u, 2u, 2u}},
    {"g26_perish_end", 3u, {1u, 1u, 1u, 1u}},
    {"g26_perish_end", 4u, {0u, 0u, 0u, 0u}},
    {"g26_perish_end", 5u, {0u, 0u, 0u, 0u}},
    {"g26_perish_end", 6u, {3u, 3u, 3u, 3u}},
    {"g26_perish_end", 7u, {2u, 2u, 2u, 2u}},
    {"g26_perish_end", 8u, {1u, 1u, 1u, 1u}},
    {"g26_perish_end", 9u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_a", 0u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_a", 1u, {3u, 3u, 3u, 3u}},
    {"g26_perish_survivor_a", 2u, {2u, 2u, 2u, 2u}},
    {"g26_perish_survivor_a", 3u, {1u, 1u, 1u, 1u}},
    {"g26_perish_survivor_a", 4u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_a", 5u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_a", 6u, {0u, 3u, 3u, 3u}},
    {"g26_perish_survivor_a", 7u, {0u, 2u, 2u, 2u}},
    {"g26_perish_survivor_a", 8u, {0u, 1u, 1u, 1u}},
    {"g26_perish_survivor_a", 9u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_b", 0u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_b", 1u, {3u, 3u, 3u, 3u}},
    {"g26_perish_survivor_b", 2u, {2u, 2u, 2u, 2u}},
    {"g26_perish_survivor_b", 3u, {1u, 1u, 1u, 1u}},
    {"g26_perish_survivor_b", 4u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_b", 5u, {0u, 0u, 0u, 0u}},
    {"g26_perish_survivor_b", 6u, {0u, 3u, 3u, 3u}},
    {"g26_perish_survivor_b", 7u, {0u, 2u, 2u, 2u}},
    {"g26_perish_survivor_b", 8u, {0u, 1u, 1u, 1u}},
    {"g26_perish_survivor_b", 9u, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g26_perish_song", "g26_perish_recast", "g26_perish_end", "g26_perish_survivor_a", "g26_perish_survivor_b"};

static const uint8_t *row_of(const char *battle, uint32_t step)
{
    for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
        if (strcmp(rows[r].battle, battle) == 0 && rows[r].step == step) {
            return rows[r].perish;
        }
    }
    return NULL;
}

static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared, uint32_t *unannounced)
{
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
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
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            const uint8_t *want = row_of(names[n], si);
            if (!DF_CHECK(t, want != NULL)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                /* The tail keeps the duration, 4 from the cast to the residual that announces the first count: a state in the
                 * middle of the turn (a pivot's request) has 4 where the view and the protocol have nothing yet. */
                const uint32_t shown = tp->perish < (uint8_t)DFI_TAIL_PERISH_MAX ? tp->perish : 0u;
                *unannounced += tp->perish == (uint8_t)DFI_TAIL_PERISH_MAX ? 1u : 0u;
                if (!DF_CHECK(t, shown == want[flat])) {
                    fprintf(stderr, "  %s step %u position %u: perish %u, want %u\n", names[n], si, flat, tp->perish,
                            want[flat]);
                }
            }
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation_ext ext;
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext exp;
                memset(&exp, 0, sizeof exp);
                exp.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                exp.player = (uint8_t)viewer;
                exp.epoch = ob.epoch;
                exp.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    exp.sides[flat / 2u].positions[flat % 2u].perish = want[flat];
                }
                if (!DF_CHECK(t, memcmp(&ext, &exp, sizeof exp) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's\n", names[n], si,
                            viewer);
                }
                *compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
}

/* A Heal Block that ends in the same residual as a Perish count is refused: the engine runs Heal Block's duration handler
 * (order 20) after the callbacks, so its end line would come after the counts that the pin prints after it (order 24).
 * g26_perish_song before its third turn, with Politoed's Heal Block set to its last turn by hand. */
static void check_heal_block_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g26_perish_song");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 3u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, "g26_perish_song", 3u);
    if (b == NULL) {
        return;
    }
    DF_CHECK(t, b->tail.sides[0].positions[0].perish == 2u);
    const df_conf_step *st = &cb->steps[3];
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_battle *c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) == DUOFORGE_OK);
        duoforge_battle_destroy(c);
    }
    c = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        c->tail.sides[1].positions[0].heal_block_turns = 1u; /* Wigglytuff: Heal Block ends in this residual */
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                        DUOFORGE_E_UNSUPPORTED);
        duoforge_battle_destroy(c);
    }
    duoforge_battle_destroy(b);
}

/* The faint points of the residual meet the side conditions, whose tie between the two sides is a shuffle that the
 * conversion drops when the handlers only count down. Two cases where the order would show, and so are refused:
 *   - one side's Tailwind ends in this residual and the other's does not, with faints still queued (the faints come after
 *     the one that does not end: before or after the other's end line by the shuffle);
 *   - neither ends, and the first one's faint point ends the battle (which side's counter ran is the shuffle's).
 * With one side's Tailwind only, the order is fixed and the battle ends there (g26_perish_end's last turn).
 * g26_perish_end before its last turn (four counts at 1, the last four Pokemon faint), the Tailwinds set by hand. */
static duoforge_status tailwind_case(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                     uint8_t side0, uint8_t side1)
{
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_battle *c = NULL;
    if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        return DUOFORGE_E_INVARIANT;
    }
    c->sides[0].tailwind_turns = side0;
    c->sides[1].tailwind_turns = side1;
    duoforge_step_result res;
    uint32_t used = 0u;
    const duoforge_status s = dfi_battle_step_tape(ctx, c, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
    duoforge_battle_destroy(c);
    return s;
}

static void check_side_condition_refusals(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g26_perish_end");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 9u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, "g26_perish_end", 9u);
    if (b == NULL) {
        return;
    }
    DF_CHECK(t, b->tail.sides[0].positions[1].perish == 1u);
    const df_conf_step *st = &cb->steps[9];
    DF_CHECK_EQ_U64(t, tailwind_case(t, ctx, b, st, 3u, 0u), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, tailwind_case(t, ctx, b, st, 1u, 3u), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, tailwind_case(t, ctx, b, st, 3u, 1u), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, tailwind_case(t, ctx, b, st, 2u, 3u), DUOFORGE_E_UNSUPPORTED);
    duoforge_battle_destroy(b);
}

/* The handlers of the volatiles that have no order (the stall counter, a charge, Protect's and Helping Hand's duration)
 * run last, in Speed order, and a faint point at one that does not end can end the battle: the handlers after it have not
 * run and keep their counters. The tie between a Pokemon's Protect volatile and its stall counter is a shuffle of the
 * reference that shows only then, in the volatile that a Pokemon still standing keeps: the engine draws it (the tape's
 * entry states which ran first: 0 the stall counter, 1 Protect's volatile) when the battle ends in the residual and such a
 * Pokemon stands (dfi_residual_pair_draws). Anything else that the order would show is refused (a survivor with another
 * handler too, two Pokemon of equal Speed: only the differential campaigns reach the second).
 * g26_perish_end before its last turn, with one side not infected, so that it survives while the other's counts end:
 * that turn Politoed (side 1) uses Protect, a stall counter that does not end (and Protect's own volatile), and
 * Staraptor (side 0, in its Tailwind, which ends in this residual) has Helping Hand's volatile. `pair_value` is the
 * tape's entry for the pair's draw, appended to the recorded tape (UINT32_MAX: none); the Protect flag of Politoed after
 * the step goes to *protect_after. */
static duoforge_status no_order_case(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                     uint32_t survivors, uint32_t pair_value, uint8_t side0_tailwind, uint8_t politoed_extra_flags,
                                     uint32_t *protect_after)
{
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_battle *c = NULL;
    if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
        return DUOFORGE_E_INVARIANT;
    }
    c->sides[0].tailwind_turns = side0_tailwind; /* 1: it ends in this residual, a handler that ends, so no faint point; 3: it does not end */
    c->sides[1].tailwind_turns = 0u;
    for (uint32_t p = 0u; p < 2u; ++p) {
        c->tail.sides[survivors].positions[p].perish = 0u; /* this side is not infected: it survives */
    }
    c->sides[1].positions[0].flags = (uint8_t)((uint32_t)c->sides[1].positions[0].flags | politoed_extra_flags);
    dfi_tape_entry tape[256];
    uint32_t len = st->tape_len;
    if (!DF_CHECK(t, len + 1u <= sizeof tape / sizeof tape[0])) {
        duoforge_battle_destroy(c);
        return DUOFORGE_E_INVARIANT;
    }
    for (uint32_t k = 0u; k < len; ++k) {
        tape[k] = conf_tape[st->tape_off + k];
    }
    if (pair_value != UINT32_MAX) {
        tape[len] = (dfi_tape_entry){(uint32_t)DFI_SITE_SPEED_TIE, 0u, 2u, pair_value};
        len += 1u;
    }
    duoforge_step_result res;
    uint32_t used = 0u;
    const duoforge_status s = dfi_battle_step_tape(ctx, c, &bd, tape, len, &used, &res);
    *protect_after = ((uint32_t)c->sides[1].positions[0].flags & DFI_VOL_PROTECT) != 0u ? 1u : 0u;
    duoforge_battle_destroy(c);
    return s;
}

static void check_no_order_faint_point(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g26_perish_end");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 9u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, "g26_perish_end", 9u);
    if (b == NULL) {
        return;
    }
    const df_conf_step *st = &cb->steps[9];
    uint32_t keeps = 9u;
    /* Side 1 survives: Politoed's stall counter does not end and Protect's volatile does, and the faint point of the first
     * ends the battle. Without the tape's entry for their tie the step cannot be made; with it the survivor keeps Protect
     * when the stall counter ran first (0) and loses it when Protect's own handler did (1). */
    DF_CHECK(t, no_order_case(t, ctx, b, st, 1u, UINT32_MAX, 1u, 0u, &keeps) != DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, no_order_case(t, ctx, b, st, 1u, 0u, 1u, 0u, &keeps), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, keeps, 1u);
    DF_CHECK_EQ_U64(t, no_order_case(t, ctx, b, st, 1u, 1u, 1u, 0u, &keeps), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, keeps, 0u);
    /* Side 0 survives, Politoed's four counts end with the others: its stall counter's faint point ends the battle, the
     * Staraptor's Helping Hand (of another Speed) is not a pair and not a tie, and the order is the Speed's: no draw. */
    DF_CHECK_EQ_U64(t, no_order_case(t, ctx, b, st, 0u, UINT32_MAX, 1u, 0u, &keeps), DUOFORGE_OK);
    /* The battle ends earlier, at the faint point of a Tailwind that does not end (before every no-order handler): the
     * pair's draw is spent unseen, and neither value takes Protect's volatile from the survivor. */
    DF_CHECK_EQ_U64(t, no_order_case(t, ctx, b, st, 1u, 0u, 3u, 0u, &keeps), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, keeps, 1u);
    DF_CHECK_EQ_U64(t, no_order_case(t, ctx, b, st, 1u, 1u, 3u, 0u, &keeps), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, keeps, 1u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g26");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_PERISH, 4u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_PERISH, 5u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_PERISH)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_PERISHSONG] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_PERISHSONG].special, DFI_SPECIAL_PERISH_SONG);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_PERISHSONG].target_class, DUOFORGE_TARGET_CLASS_ALL);
    /* Soundproof stays unmarked: it would stop the move, and nothing here models that. */
    DF_CHECK_EQ_U64(&t, dfi_support.abilities[DFI_ABILITY_SOUNDPROOF], 0u);

    uint32_t compared = 0u;
    uint32_t unannounced = 0u;
    check_battles(&t, kp, &compared, &unannounced);
    DF_CHECK(&t, unannounced >= 4u); /* g26_perish_recast has a request in the middle of the turn of a cast */
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    check_heal_block_refusal(&t, kp);
    check_heal_block_refusal(&t, kd);
    check_side_condition_refusals(&t, kp);
    check_side_condition_refusals(&t, kd);
    check_no_order_faint_point(&t, kp);
    check_no_order_faint_point(&t, kd);
    uint32_t compared_dev = 0u;
    uint32_t unannounced_dev = 0u;
    check_battles(&t, kd, &compared_dev, &unannounced_dev);
    DF_CHECK_EQ_U64(&t, unannounced_dev, unannounced); /* POOL_DEV: its own fingerprint, the same tables */
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
