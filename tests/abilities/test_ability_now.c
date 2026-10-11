/*
 * duoforge.state.ability_now (white-box): the ability that the turn code reads is the one of dfi_ability_code
 * (src/combat/turn.c): the POOL tail's ability_now of the member when it is not zero, else the sheet's ability
 * (decision 0015 section 7; step AC0 of the ability-change work, which moves every rule onto that read and changes no
 * behaviour).
 *
 * Nothing writes ability_now yet (the effects that change an ability come with the steps after AC0), so the test
 * writes it: before a step of a recorded battle (g2_data_moves_a to _d under "data": "pool", replayed with the
 * reference's draws up to the step) the battle is cloned and every standing member of the clone is given an
 * ability_now; the clones take the same step with the same native RNG.
 *  - ability_now equal to the sheet's ability changes nothing: after the step the state is byte-identical to the
 *    state of the clone that was not given anything, once ability_now is cleared again (the step may have cleared
 *    it on a switch, which is the same);
 *  - an ability X that a rule reads makes the step different from the step of a clone given Pressure, an ability
 *    that no rule of the engine reads (both clones lose the sheet abilities' effects, so what differs is X's own):
 *    Contrary (the stat change rule), Adaptability (the damage rule), Pixilate (the family rules), Emergency Exit
 *    and Unburden (the rules that read the ability by id, and the Unburden invariant);
 *  - the sheet's ability is never touched.
 * A rule that still read dfi_member.ability would not see X, and its variant would never differ from the baseline
 * (tests/mutation checks of the step: duoforge.state.ability_now goes red for each of them).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

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

/* The battle after its first `steps` steps, with the reference's draws as the tape; NULL when it fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
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
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK)) {
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* Every standing member: ability_now = `code` (1 + an ability id), or, with 0, the member's own ability. */
static void give(struct duoforge_battle *b, uint32_t code)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER && b->sides[s].members[occupant].hp != 0u) {
                b->tail.sides[s].ability_now[occupant] = (uint16_t)(code != 0u ? code : b->sides[s].members[occupant].ability);
            }
        }
    }
}

static void clear(struct duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            b->tail.sides[s].ability_now[m] = 0u;
        }
    }
}

/* The sheet abilities of both sides, as one comparable block. */
static void sheet(const struct duoforge_battle *b, uint8_t out[DUOFORGE_SIDE_COUNT * DUOFORGE_MAX_ROSTER])
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            out[s * DUOFORGE_MAX_ROSTER + m] = b->sides[s].members[m].ability;
        }
    }
}

/* One step of the recorded battle on two clones of `base`, the one given `code` (0: the sheet's own ability) and the
 * other `control_code` (NO_POKE: nothing); true when their states differ afterwards (ability_now cleared again). */
#define NO_POKE 0xFFFFFFFFu
#define BASELINE (1u + DFI_ABILITY_PRESSURE) /* read by no rule of the engine */

static bool differs(df_test *t, const duoforge_context *ctx, const duoforge_battle *base, const df_conf_step *st,
                    uint32_t control_code, uint32_t code, bool *same_sheet)
{
    duoforge_battle *control = NULL;
    duoforge_battle *poked = NULL;
    if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &control) == DUOFORGE_OK &&
                         duoforge_battle_clone(ctx, base, &poked) == DUOFORGE_OK)) {
        duoforge_battle_destroy(control);
        duoforge_battle_destroy(poked);
        return false;
    }
    if (control_code != NO_POKE) {
        give(control, control_code);
    }
    give(poked, code);
    uint8_t before[DUOFORGE_SIDE_COUNT * DUOFORGE_MAX_ROSTER];
    sheet(poked, before);
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    bundle_of(st, base, &bd);
    const duoforge_status a = duoforge_battle_step(ctx, control, &bd, &res);
    const duoforge_status b = duoforge_battle_step(ctx, poked, &bd, &res);
    bool differs_now = false;
    if (DF_CHECK(t, a == DUOFORGE_OK) && b != DUOFORGE_OK) {
        /* Emergency Exit in a residual phase is E_UNSUPPORTED (decision 0006 section 4.12): the rule read the field. */
        if (!DF_CHECK(t, b == DUOFORGE_E_UNSUPPORTED)) {
            fprintf(stderr, "  poked step: %s\n", duoforge_status_name(b));
        }
        differs_now = true;
    } else if (a == DUOFORGE_OK) {
        uint8_t after[DUOFORGE_SIDE_COUNT * DUOFORGE_MAX_ROSTER];
        sheet(poked, after);
        *same_sheet = *same_sheet && memcmp(before, after, sizeof before) == 0;
        clear(control);
        clear(poked);
        bool equal = false;
        DF_CHECK(t, duoforge_battle_equal(ctx, control, poked, &equal) == DUOFORGE_OK);
        differs_now = !equal;
    }
    duoforge_battle_destroy(control);
    duoforge_battle_destroy(poked);
    return differs_now;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.ability_now");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);

    static const char *const names[] = {"g2_data_moves_a", "g2_data_moves_b", "g2_data_moves_c", "g2_data_moves_d"};
    uint32_t steps_seen = 0u;
    uint32_t same_differs = 0u;
    uint32_t contrary_differs = 0u;
    uint32_t adaptability_differs = 0u;
    uint32_t pixilate_differs = 0u;
    uint32_t exit_differs = 0u;
    uint32_t unburden_differs = 0u;
    bool same_sheet = true;
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            duoforge_battle *base = replay(&t, kp, cb, si);
            if (base == NULL) {
                continue;
            }
            const df_conf_step *st = &cb->steps[si];
            steps_seen += 1u;
            same_differs += differs(&t, kp, base, st, NO_POKE, 0u, &same_sheet) ? 1u : 0u;
            contrary_differs += differs(&t, kp, base, st, BASELINE, 1u + DFI_ABILITY_CONTRARY, &same_sheet) ? 1u : 0u;
            adaptability_differs += differs(&t, kp, base, st, BASELINE, 1u + DFI_ABILITY_ADAPTABILITY, &same_sheet) ? 1u : 0u;
            pixilate_differs += differs(&t, kp, base, st, BASELINE, 1u + DFI_ABILITY_PIXILATE, &same_sheet) ? 1u : 0u;
            exit_differs += differs(&t, kp, base, st, BASELINE, 1u + DFI_ABILITY_EMERGENCYEXIT, &same_sheet) ? 1u : 0u;
            unburden_differs += differs(&t, kp, base, st, BASELINE, 1u + DFI_ABILITY_UNBURDEN, &same_sheet) ? 1u : 0u;
            duoforge_battle_destroy(base);
        }
    }
    fprintf(stderr,
            "  %u steps: ability_now = the sheet's ability changes %u, Contrary %u, Adaptability %u, Pixilate %u, "
            "Emergency Exit %u, Unburden %u\n",
            steps_seen, same_differs, contrary_differs, adaptability_differs, pixilate_differs, exit_differs,
            unburden_differs);
    DF_CHECK(&t, steps_seen > 10u);
    DF_CHECK_EQ_U64(&t, same_differs, 0u);
    DF_CHECK(&t, contrary_differs > 0u);
    DF_CHECK(&t, adaptability_differs > 0u);
    DF_CHECK(&t, pixilate_differs > 0u);
    DF_CHECK(&t, exit_differs > 0u);
    DF_CHECK(&t, unburden_differs > 0u);
    DF_CHECK(&t, same_sheet);

    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
