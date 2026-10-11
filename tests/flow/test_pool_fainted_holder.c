/*
 * duoforge.state.pool_fainted_holder (white-box): the queued action of a fainted Pokemon (data/ability and item
 * effects on the sort key of the queue).
 *
 * After every action Showdown prices every queued action again (sim/battle.ts:2919-2926, getActionSpeed :2619-2662).
 * A Pokemon that fainted stays in the queue, is skipped when its action comes up (:2705-2707), but its action still
 * ties or does not tie with the others, and a tie is a shuffle that draws from the PRNG. faintMessages makes the
 * Pokemon inactive (:2566), and an inactive holder has no ability and no item (ignoringAbility, ignoringItem,
 * sim/pokemon.ts:858-859 and :879-881; runEvent :874-883) and no ModifySpe handler of its own or of its side
 * (findEventHandlers :1053). The engine reads that in dfi_move_priority (Prankster) and dfi_speed_key (Choice Scarf,
 * Tailwind, Unburden, paralysis). Three recorded battles (data pool) show it:
 *
 *   d04  P1's Prankster Grimmsnarl faints before its Reflect: at priority 0 it ties with the foe's Dazzling Gleam,
 *        and the reference draws a two-way shuffle that an engine with Prankster's +1 does not make.
 *   d05  both Grimmsnarl queue Light Screen at +1 and tie; one faints; the live +1 action is alone and the reference
 *        draws nothing more, where an engine with the +1 for the fainted holder draws a second tie.
 *   d06  P1's Choice Scarf Raichu faints before its Thunderbolt: at its raw Speed it ties with the foe's Raichu of
 *        the same raw Speed (no Scarf), a draw an engine with the x1.5 does not make.
 *
 * Every battle is replayed through the step with the reference's draws (a test-only tape, as in
 * duoforge.reference.conformance_pool_data). The decisive draw is the first tie that follows a damage roll in the
 * decisive step's tape. Two controls on a copy of the battle before that step:
 *   - d04 and d06: the tape without that entry fails exactly there (E_INVARIANT, every earlier entry consumed): the
 *     engine does draw the tie of the fainted holder's action;
 *   - d05: the tape with one more copy of that entry does not run to its end as it would if the engine drew a tie for
 *     the fainted holder's +1 action: the entry stays unconsumed or the step fails.
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

#define TAPE_MAX 64u

/* One battle: the steps before `decisive` replay on the tape; then the decisive step runs on copies of the battle. */
static void check_battle(df_test *t, const duoforge_context *ctx, const char *name, uint32_t decisive, bool engine_draws)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, decisive < cb->step_count)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < decisive; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            fprintf(stderr, "  %s step %u\n", name, si);
            duoforge_battle_destroy(b);
            return;
        }
    }
    const df_conf_step *st = &cb->steps[decisive];
    const dfi_tape_entry *tape = &conf_tape[st->tape_off];
    /* The decisive entry: the first shuffle after a damage roll (a Thunderbolt or Dazzling Gleam queued by a Pokemon
     * that fainted, or the residual of d05's step, where the engine used to draw one tie too many). */
    uint32_t at = st->tape_len;
    for (uint32_t i = 1u; i < st->tape_len; ++i) {
        if (tape[i].site == DFI_SITE_SPEED_TIE && tape[i - 1u].site == DFI_SITE_DAMAGE_ROLL) {
            at = i;
            break;
        }
    }
    if (!DF_CHECK(t, at < st->tape_len) || !DF_CHECK(t, st->tape_len < TAPE_MAX)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);

    /* The whole tape: consumed exactly, to the end of the reference's step. */
    {
        duoforge_battle *c = NULL;
        duoforge_step_result res;
        uint32_t used = 0u;
        if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
            DF_CHECK(t, dfi_battle_step_tape(ctx, c, &bd, tape, st->tape_len, &used, &res) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, used, st->tape_len);
            duoforge_battle_destroy(c);
        }
    }
    static dfi_tape_entry variant[TAPE_MAX];
    duoforge_battle *c = NULL;
    duoforge_step_result res;
    uint32_t used = 0u;
    if (engine_draws) {
        /* Without the entry: the engine asks for it exactly there. */
        uint32_t n = 0u;
        for (uint32_t i = 0u; i < st->tape_len; ++i) {
            if (i != at) {
                variant[n++] = tape[i];
            }
        }
        if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
            const duoforge_status s = dfi_battle_step_tape(ctx, c, &bd, variant, n, &used, &res);
            DF_CHECK(t, s == DUOFORGE_E_INVARIANT);
            if (!DF_CHECK_EQ_U64(t, used, at)) {
                fprintf(stderr, "  %s: the engine asked for the tie of the fainted holder's action after %u entries, not %u\n",
                        name, used, at);
            }
            duoforge_battle_destroy(c);
        }
    } else {
        /* One entry more: the engine does not draw for the fainted holder's action, so the extra entry is never
         * consumed as a tie (the step then ends one entry short or fails). */
        uint32_t n = 0u;
        for (uint32_t i = 0u; i < st->tape_len; ++i) {
            variant[n++] = tape[i];
            if (i == at) {
                variant[n++] = tape[i];
            }
        }
        if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &c) == DUOFORGE_OK)) {
            const duoforge_status s = dfi_battle_step_tape(ctx, c, &bd, variant, n, &used, &res);
            DF_CHECK(t, !(s == DUOFORGE_OK && used == n));
            duoforge_battle_destroy(c);
        }
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_fainted_holder");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    for (uint32_t k = 0u; k < 2u; ++k) {
        const duoforge_context *ctx = k == 0u ? kp : kd;
        check_battle(&t, ctx, "d04_fainted_prankster_reflect_tie", 2u, true);
        check_battle(&t, ctx, "d05_fainted_prankster_screen_no_tie", 6u, false);
        check_battle(&t, ctx, "d06_fainted_scarf_speed_tie", 1u, true);
    }
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
