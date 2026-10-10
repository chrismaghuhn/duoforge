/*
 * duoforge.state.pool_g74 (white-box): step G74 of the content expansion, Baton Pass (decision 0042).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the marks: Baton Pass is supported and its pivot row is DFI_SWITCH_BATON_PASS; Shed Tail, Transform and the Imposter
 *     ability are unmarked (the guard: no engine state for Transform or Imposter exists yet, so no refusal can be reached);
 *   - the view fold (lead's requirement): after the recorded pass, the receiver's view shows exactly the passer's boost stages
 *     and confused flag, on both sides' views, and none of the passer's other per-occupant view fields (acted, protect chain,
 *     Protect, charge, Flash Fire, the locked slot, the reserved flags);
 *   - the receiver's public refusal (lead's requirement): a standing Substitute on the receiving position refuses the public
 *     record with the SUBSTITUTE cause on both viewers, and its HP stays in the engine (no view carries it);
 *   - the Substitute bound per side (lead's decision A): the largest quarter of the brought members, not the occupant's;
 *   - the refusals of the passer (decision 0042 section 6): Encore and Disable on the passer are E_UNSUPPORTED; an Illusion
 *     tail is refused by the state invariant until decision 0026 writes it.
 * The engine's behaviour along the way (the switch line, the copy, the draws) is pinned by the recorded battles
 * tests/reference/traces/g74_pass_*.json, replayed by duoforge.reference.conformance_pool_data.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/turn.h"
#include "state/request.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/invariants.h"
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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
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

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step), by the engine itself. */
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
    return b;
}

/* The observation of both players after the first `steps` steps of `name`. */
static bool observe_both(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, duoforge_observation ob[2])
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (b == NULL) {
        return false;
    }
    bool ok = true;
    for (uint32_t v = 0u; v < 2u; ++v) {
        ok = DF_CHECK_EQ_U64(t, duoforge_battle_observe(ctx, b, v, &ob[v]), DUOFORGE_OK) && ok;
    }
    duoforge_battle_destroy(b);
    return ok;
}

/* The marks and the pivot row (decision 0042). */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_BATONPASS] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_SHEDTAIL] == 0u);   /* refused by 0032 and 0042, unchanged */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_TRANSFORM] == 0u);  /* guard: no Transform state in the engine yet (decision 0028) */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_IMPOSTER] == 0u); /* guard: no Imposter state yet (decision 0027) */
    const dfi_pivot_move *pm = dfi_pivot_of_move(DFI_MOVE_BATONPASS);
    DF_CHECK(t, pm != NULL && pm->flag == DFI_SWITCH_BATON_PASS && dfi_pivot_of_flag(DFI_SWITCH_BATON_PASS) == pm);
    DF_CHECK_EQ_U64(t, DFI_SWITCH_BATON_PASS, 8u);
}

/* The view fold (lead's requirement): the receiver's position shows the passer's stages and confused flag, the same on both
 * viewers, and nothing else of the passer's per-occupant fields. The pass is the first step where the occupant of side 0's
 * position 0 changes; the state before it is the passer's, the state after it is the receiver's. */
static void check_view_fold(df_test *t, const duoforge_context *ctx)
{
    static const char *name = "g74_pass_confused";
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_observation first[2];
    if (!observe_both(t, ctx, name, 1u, first)) {
        return;
    }
    uint32_t post = 0u;
    duoforge_observation cur[2];
    for (uint32_t s = 2u; s <= cb->step_count && post == 0u; ++s) {
        if (!observe_both(t, ctx, name, s, cur)) {
            return;
        }
        if (cur[0].sides[0].occupant[0] != first[0].sides[0].occupant[0]) {
            post = s;
        }
    }
    if (!DF_CHECK(t, post != 0u)) {
        return;
    }
    duoforge_observation pre[2];
    if (!observe_both(t, ctx, name, post - 1u, pre)) {
        return;
    }
    for (uint32_t v = 0u; v < 2u; ++v) {
        const duoforge_position_view *a = &pre[v].sides[0].positions[0];
        const duoforge_position_view *c = &cur[v].sides[0].positions[0];
        /* the passer: +1 SpA and +1 SpD (biased by 6), confused */
        DF_CHECK_EQ_U64(t, a->stages[2], 7u);
        DF_CHECK_EQ_U64(t, a->stages[3], 7u);
        DF_CHECK_EQ_U64(t, a->confused, 1u);
        /* the receiver: the same stages and the same confused flag, from the copy, with no line */
        for (uint32_t i = 0u; i < 7u; ++i) {
            DF_CHECK_EQ_U64(t, c->stages[i], a->stages[i]);
        }
        DF_CHECK_EQ_U64(t, c->confused, a->confused);
        /* nothing else of the passer's per-occupant view: the receiver has not acted, and holds no Protect, charge, Flash
         * Fire, locked slot or flag */
        DF_CHECK_EQ_U64(t, c->acted, 0u);
        DF_CHECK_EQ_U64(t, c->protect_chain, 0u);
        DF_CHECK_EQ_U64(t, c->protecting, 0u);
        DF_CHECK_EQ_U64(t, c->charging, 0u);
        DF_CHECK_EQ_U64(t, c->flash_fire, 0u);
        DF_CHECK_EQ_U64(t, c->locked_slot, (uint64_t)DUOFORGE_MOVE_SLOT_NONE);
        DF_CHECK_EQ_U64(t, c->reserved, 0u);
        DF_CHECK(t, cur[v].sides[0].occupant[0] != first[v].sides[0].occupant[0]);
    }
}

/* The receiver of a standing Substitute refuses the public record with the SUBSTITUTE cause on both viewers (lead's
 * requirement), its presence shows on both sides, and the HP stays in the engine. The state is the recorded
 * g74_pass_sub_damaged after the step where Ninetales enters position 1. */
static void check_receiver_refusal(df_test *t, const duoforge_context *ctx)
{
    static const char *name = "g74_pass_sub_damaged";
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_observation first[2];
    if (!observe_both(t, ctx, name, 1u, first)) {
        return;
    }
    uint32_t post = 0u;
    duoforge_observation cur[2];
    for (uint32_t s = 2u; s <= cb->step_count && post == 0u; ++s) {
        if (!observe_both(t, ctx, name, s, cur)) {
            return;
        }
        if (cur[0].sides[0].occupant[1] != first[0].sides[0].occupant[1]) {
            post = s;
        }
    }
    if (!DF_CHECK(t, post != 0u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, name, post);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    DF_CHECK(t, b->tail.sides[0].positions[1].substitute_hp != 0u); /* the inherited Substitute stands (hidden HP) */
    for (uint32_t v = 0u; v < 2u; ++v) {
        duoforge_observation_ext ob;
        DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, v, &ob), DUOFORGE_OK);
        for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const bool bit = (ob.sides[side].positions[p].volatiles & DUOFORGE_POSITION_EXT_SUBSTITUTE) != 0u;
                DF_CHECK_EQ_U64(t, (uint64_t)bit, (uint64_t)(side == 0u && p == 1u));
            }
        }
        uint32_t mask = 0u;
        duoforge_public_state out;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, v, &mask), DUOFORGE_OK);
        DF_CHECK(t, (mask & DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE) != 0u);
        DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, v, &out), DUOFORGE_E_UNSUPPORTED);
    }
    duoforge_battle_destroy(b);
}

/* The bound of a Substitute on a side: the largest quarter among the brought members (decision 0042, lead's decision A). The
 * state after the pass: the receiver's quarter is at most the cap, and one more is an invariant failure. */
static void check_substitute_cap(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g74_pass_sub_damaged", 6u);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    const dfi_side *s = &b->sides[0];
    uint32_t cap = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER && m < s->member_count; ++m) {
        if (((uint32_t)s->brought_mask >> m) & 1u) {
            const uint32_t q = (uint32_t)s->members[m].hp_max / 4u;
            cap = q > cap ? q : cap;
        }
    }
    dfi_tail_pos *tp = &b->tail.sides[0].positions[1];
    const uint16_t keep = tp->substitute_hp;
    dfi_invariant inv = DFI_INV_NONE;
    tp->substitute_hp = (uint16_t)cap;
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_OK);
    tp->substitute_hp = (uint16_t)(cap + 1u);
    DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_POSITION);
    tp->substitute_hp = keep;
    duoforge_battle_destroy(b);
}

/* The passer's refusals (decision 0042 section 6). Encore on the Baton Pass slot and Disable on Calm Mind's slot make the pass
 * legal and still refuse it: E_UNSUPPORTED. An Illusion tail is refused by the state invariant until decision 0026 writes it. */
static void check_passer_refusals(df_test *t, const duoforge_context *ctx)
{
    static const char *name = "g74_pass_confused";
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    /* the decision of the pass: the first step whose side 0 slot 0 chooses move 2 (Baton Pass) */
    uint32_t pass = 0u;
    for (uint32_t s = 1u; s < cb->step_count && pass == 0u; ++s) {
        const df_conf_cmd *c = &cb->steps[s].cmds[0][0];
        if (c->kind == 1u && c->move_slot == 1u && cb->steps[s].answered0) { /* kind 1: a move (trace_to_c convert_choice) */
            pass = s;
        }
    }
    if (!DF_CHECK(t, pass != 0u)) {
        return;
    }
    for (int kind = 0; kind < 2; ++kind) {
        duoforge_battle *b = replay(t, ctx, name, pass);
        if (!DF_CHECK(t, b != NULL)) {
            return;
        }
        dfi_tail_pos *tp = &b->tail.sides[0].positions[0];
        if (kind == 0) {
            tp->encore_slot = 2u; /* the Baton Pass slot (1-based) is the one move Encore allows */
            tp->encore_turns = 2u;
        } else {
            tp->disable_slot = 1u; /* Calm Mind's slot (move slot + 1) is barred; the pass stays legal */
            tp->disable_turns = 2u;
        }
        duoforge_decision_bundle bd;
        bundle_of(&cb->steps[pass], b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status st = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[pass].tape_off],
                                                        cb->steps[pass].tape_len, &used, &res);
        DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
        duoforge_battle_destroy(b);
    }
    /* Illusion: a nonzero tail for the side is refused by the state invariant (rev 5, decision 0026 not landed) */
    duoforge_battle *b = replay(t, ctx, name, pass);
    if (DF_CHECK(t, b != NULL)) {
        dfi_invariant inv = DFI_INV_NONE;
        b->tail.sides[0].illusion.shown = 1u;
        DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, &inv), DUOFORGE_E_INVARIANT);
        DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_SIDE);
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g74");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(&t, ctx != NULL);
    check_marks(&t);
    if (ctx != NULL) {
        check_view_fold(&t, ctx);
        check_receiver_refusal(&t, ctx);
        check_substitute_cap(&t, ctx);
        check_passer_refusals(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
