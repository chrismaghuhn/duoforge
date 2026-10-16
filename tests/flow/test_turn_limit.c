/*
 * The turn limit (decision 0015 entry 5dt, the turn-1000 tie; before the fix the doubles checks below failed: the
 * doubles kinds played turn 1001).
 *
 * The pin ends every format as a tie when endTurn makes the turn counter pass 1000 (sim/battle.ts:1624 turn++, then
 * maybeTriggerEndlessBattleClause :1773: `if (this.turn <= 100) return;` :1836, `if (this.turn > 1000)` the message
 * and tie() :1839-1843). The check comes before the Endless Battle Clause's rule test (:1854), so it applies to
 * Reg M-C (Flat Rules, no clause) as well. No `|turn|1001` line is printed; the state's turn is 1001.
 * Recorded against the pin: tests/reference/prepared/turn1000_tie (both sides switch both slots for 1000 turns).
 *
 *   - doubles (POOL): a step that starts turn 1000 (from 999) is an ordinary TURN boundary;
 *   - doubles (POOL): the step after it (from 1000) ends the battle: TERMINAL, result TIE, turn 1001, nobody requested,
 *     the step's last event for each player is RESULT with detail TIE and no TURN event is emitted; a further bundle
 *     is INVALID_ARGUMENT (the battle is over);
 *   - doubles (POOL_DEV): the same tie;
 *   - singles (POOL_SINGLES_DEV): unchanged, the Endless Battle Clause's refusal at turn 101 (decision 0083 section 6):
 *     from turn 99 the step starts turn 100, from turn 100 it is E_UNSUPPORTED and the battle unchanged. (The limit is
 *     checked before the clause, as in the pin, but a singles battle never gets past turn 100 to reach it.)
 */
#include <string.h>

#include <duoforge/duoforge.h>

#include "state/battle_internal.h"
#include "support/check.h"
#include "support/pool.h"

#define DF_TURN_LIMIT 1000u

/* Team selection by the first candidate of each side. */
static bool to_turn(df_test *t, const duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    static duoforge_side_choice cand[DUOFORGE_MAX_CANDIDATES];
    for (uint32_t s = 0u; s < 2u; ++s) {
        uint32_t n = 0u;
        if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, s, cand, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK &&
                             n > 0u)) {
            return false;
        }
        bd.responses[s] = cand[0];
    }
    duoforge_step_result res;
    return DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK) &&
           DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
}

/* Every requested slot of both sides switches, each to a different reserve: no PP, no damage, no faint. */
static bool switch_bundle(df_test *t, const duoforge_context *ctx, const duoforge_battle *b,
                          duoforge_decision_bundle *out)
{
    memset(out, 0, sizeof *out);
    out->epoch = b->request_epoch;
    out->response_mask = 3u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        duoforge_factored_domain ds;
        if (!DF_CHECK(t, duoforge_battle_factored(ctx, b, s, &ds) == DUOFORGE_OK)) {
            return false;
        }
        duoforge_side_choice *r = &out->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        uint32_t taken = DUOFORGE_MAX_ROSTER;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            r->slots[slot] = ds.slots[slot][0]; /* the NONE command of an unrequested slot (singles slot 1) */
            for (uint32_t i = 0u; i < ds.slot_count[slot]; ++i) {
                const duoforge_slot_command *c = &ds.slots[slot][i];
                if (c->kind == DUOFORGE_SLOT_SWITCH && c->reserve != taken) {
                    r->slots[slot] = *c;
                    taken = c->reserve;
                    break;
                }
            }
        }
    }
    return true;
}

static void check_doubles(df_test *t, const duoforge_context_config *config, const char *what)
{
    duoforge_context *ctx = NULL;
    duoforge_battle_setup setup;
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_context_create(config, &ctx) == DUOFORGE_OK) ||
        !DF_CHECK(t, duoforge_reference_setup(0u, &setup) == DUOFORGE_OK) ||
        !DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL) || !to_turn(t, ctx, b)) {
        duoforge_battle_destroy(b);
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_decision_bundle sw;
    if (!switch_bundle(t, ctx, b, &sw)) {
        duoforge_battle_destroy(b);
        duoforge_context_destroy(ctx);
        return;
    }
    for (uint32_t s = 0u; s < 2u; ++s) {
        DF_CHECK_EQ_U64(t, sw.responses[s].slots[0].kind, DUOFORGE_SLOT_SWITCH);
        DF_CHECK_EQ_U64(t, sw.responses[s].slots[1].kind, DUOFORGE_SLOT_SWITCH);
    }
    duoforge_step_result res;
    static duoforge_event ev[2][DUOFORGE_MAX_EVENTS];

    /* 999 -> 1000: an ordinary turn (the pin prints the warning line "... in 0 turns (on turn 1000)" and |turn|1000). */
    struct duoforge_battle late = *b;
    late.turn = (uint16_t)(DF_TURN_LIMIT - 1u);
    DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, late.turn, DF_TURN_LIMIT);
    DF_CHECK_EQ_U64(t, late.boundary_kind, DUOFORGE_BOUNDARY_TURN);
    DF_CHECK_EQ_U64(t, res.boundary_kind, DUOFORGE_BOUNDARY_TURN);

    /* 1000 -> 1001: the tie (src/combat/flow/turn.h, dfi_end_turn). */
    late = *b;
    late.turn = (uint16_t)DF_TURN_LIMIT;
    duoforge_event_buffer buffers[2] = {{ev[0], DUOFORGE_MAX_EVENTS, 0u}, {ev[1], DUOFORGE_MAX_EVENTS, 0u}};
    if (DF_CHECK(t, duoforge_battle_step_events(ctx, &late, &sw, &res, buffers) == DUOFORGE_OK)) {
        DF_CHECK(t, late.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL && res.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL);
        DF_CHECK_EQ_U64(t, late.request_mask, 0u);
        DF_CHECK_EQ_U64(t, late.turn, DF_TURN_LIMIT + 1u);
        DF_CHECK_EQ_U64(t, late.request_epoch, b->request_epoch + 1u); /* one advance: dfi_terminal's, not the TURN one too */
        for (uint32_t flat = 0u; flat < 2u * DUOFORGE_ACTIVE_PER_SIDE; ++flat) {
            /* the end-of-turn updates run before the limit check (sim/battle.ts:1665-1771, then :1839) */
            const dfi_active_slot *pos = &late.sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE];
            DF_CHECK_EQ_U64(t, (uint32_t)pos->flags & DFI_VOL_NEWLY_SWITCHED, 0u);
        }
        uint32_t result = 0u;
        DF_CHECK(t, duoforge_battle_result(ctx, &late, &result) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, result, DUOFORGE_RESULT_TIE);
        for (uint32_t p = 0u; p < 2u; ++p) {
            bool turn_event = false;
            for (uint32_t i = 0u; i < buffers[p].count; ++i) {
                turn_event = turn_event || ev[p][i].kind == DUOFORGE_EVENT_TURN;
            }
            DF_CHECK(t, !turn_event); /* no |turn|1001 */
            DF_CHECK(t, buffers[p].count > 0u && ev[p][buffers[p].count - 1u].kind == DUOFORGE_EVENT_RESULT &&
                            ev[p][buffers[p].count - 1u].detail == DUOFORGE_RESULT_TIE);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, &late) == DUOFORGE_OK);
        /* 1001: the battle is over; any bundle is refused and nothing changes. */
        const struct duoforge_battle over = late;
        DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, memcmp(&late, &over, sizeof late) == 0);
    }
    (void)what;
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* Singles: the clause's refusal at turn 101 stays first and unchanged (decision 0083 section 6). */
static void check_singles(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle_setup setup;
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_context_create(&df_config_pool_singles, &ctx) == DUOFORGE_OK) ||
        !DF_CHECK(t, duoforge_reference_setup(0u, &setup) == DUOFORGE_OK) ||
        !DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL) || !to_turn(t, ctx, b)) {
        duoforge_battle_destroy(b);
        duoforge_context_destroy(ctx);
        return;
    }
    duoforge_decision_bundle sw;
    if (switch_bundle(t, ctx, b, &sw)) {
        duoforge_step_result res;
        struct duoforge_battle late = *b;
        late.turn = 99u;
        DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, late.turn, 100u);
        late = *b;
        late.turn = 100u;
        const struct duoforge_battle before = late;
        DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, memcmp(&late, &before, sizeof late) == 0);
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.flow.turn_limit");
    check_doubles(&t, &df_config_pool, "POOL");
    check_doubles(&t, &df_config_pool_dev, "POOL_DEV");
    check_singles(&t);
    return df_test_end(&t);
}
