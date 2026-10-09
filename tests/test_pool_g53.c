/*
 * duoforge.state.pool_g53 (white-box): step G53 of the content expansion (decision 0030 section 1), Pressure and the foe's derived
 * PP.
 *
 * Pressure (data/abilities.ts:3437-3449: onDeductPP returns 1 for a foe; useMoveInner sums the returns over the pressure targets
 * after the move's own PP, sim/battle-actions.ts:473-484) costs the user one more PP per standing foe with Pressure that the move
 * targets. The engine deducts it (src/combat/turn.c dfi_pressure_extra); the viewer of the foe derives it from the lines (the
 * fold in src/combat/events.c, dfi_pressure_charge): the foe's derived PP is pp_max minus the PP the viewer saw spent (decision
 * 0007, DUOFORGE_PP_DERIVED). The recorded battles (g53_* under "data": "pool") replay in duoforge.reference.conformance_pool_data,
 * which compares the engine's PP with the reference's. Here the facts that are not in that comparison:
 *
 *   - the marks and the flag: Pressure is supported; mustpressure (DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE, 0x800) is on
 *     Imprison, Spikes, Stealth Rock and Toxic Spikes, and on none of the moves that are not mustpressure in the pin;
 *   - at every boundary of every g53 battle, for both players, the foe's derived PP of every move slot equals the PP that the
 *     owner sees (its own PP is exact: the owner's view is the state). That is the statement "derived = pp_max minus the PP spent
 *     as the viewer saw it", checked against the state rather than against the reference's numbers;
 *   - the numbers of the Pressure cases, pinned: the single target (one extra per use), the mustpressure move (two extras for one
 *     target), the floor at 0 (the last PP of Trick Room takes what is left, no wrap).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
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

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step). */
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

/* The PP of move slot `k` of member `m` of `side`, as `viewer` sees it. */
static bool observe_pp(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer, duoforge_observation *ob)
{
    return DF_CHECK(t, duoforge_battle_observe(ctx, b, viewer, ob) == DUOFORGE_OK);
}

/* For every move slot of every member of both sides, at this boundary: the foe's view (derived) equals the owner's view
 * (exact). Returns the number of slots compared, 0 on a failure. */
static uint32_t check_derived_equals_exact(df_test *t, const duoforge_context *ctx, const duoforge_battle *b)
{
    duoforge_observation own[DUOFORGE_SIDE_COUNT];
    duoforge_observation foe[DUOFORGE_SIDE_COUNT];
    uint32_t compared = 0u;
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        if (!observe_pp(t, ctx, b, p, &own[p])) {
            return 0u;
        }
        if (!observe_pp(t, ctx, b, 1u - p, &foe[p])) {
            return 0u;
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        /* the owner (viewer `side`) sees its own PP exact; the other player (viewer 1 - side) sees it derived */
        const duoforge_side_view *ex = &own[side].sides[side];
        const duoforge_side_view *dv = &foe[side].sides[side]; /* foe[p] is viewer 1 - p: viewer 1 - side sees `side` */
        for (uint32_t m = 0u; m < ex->member_count; ++m) {
            for (uint32_t k = 0u; k < ex->members[m].move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                if (!DF_CHECK(t, ex->members[m].pp_kind == DUOFORGE_PP_EXACT && dv->members[m].pp_kind == DUOFORGE_PP_DERIVED)) {
                    return 0u;
                }
                if (!DF_CHECK(t, dv->members[m].pp[k] == ex->members[m].pp[k])) {
                    fprintf(stderr, "  side %u member %u slot %u: derived %u, exact %u\n", side, m, k,
                            (unsigned)dv->members[m].pp[k], (unsigned)ex->members[m].pp[k]);
                    return 0u;
                }
                compared += 1u;
            }
        }
    }
    return compared;
}

/* Every recorded g53 battle, at every boundary: the foe's derived PP is the owner's PP for both players. */
static void check_every_boundary(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {
        "g53_single_target", "g53_spread_protect", "g53_field_trick_room", "g53_mustpressure",
        "g53_fainted_holder", "g53_pressure_ally", "g53_sticky_web", "g53_trace_pressure",
        "g53_fainted_field", "g53_switch_pressure", "g53_expanding_force", "g53_trace_switch", "g53_mega_pressure",
        "g53_switch_in_pressure",
    };
    for (size_t i = 0u; i < sizeof names / sizeof names[0]; ++i) {
        const df_conf_battle *cb = find(names[i]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        for (uint32_t steps = 1u; steps <= cb->step_count; ++steps) {
            duoforge_battle *b = replay(t, ctx, names[i], steps);
            if (b == NULL) {
                break;
            }
            DF_CHECK(t, check_derived_equals_exact(t, ctx, b) != 0u);
            duoforge_battle_destroy(b);
        }
    }
}

static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_PRESSURE] != 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE, 0x800u);
    static const uint32_t must[] = {DFI_MOVE_IMPRISON, DFI_MOVE_SPIKES, DFI_MOVE_STEALTHROCK, DFI_MOVE_TOXICSPIKES};
    for (size_t i = 0u; i < sizeof must / sizeof must[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[must[i]] & DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) != 0u);
    }
    /* the moves that the battles use without the flag: a single target, a spread, a field move, a foe-side move that is not
     * mustpressure (Sticky Web) and a Protect */
    static const uint32_t plain[] = {DFI_MOVE_SHADOWBALL, DFI_MOVE_HYPERVOICE, DFI_MOVE_TRICKROOM, DFI_MOVE_STICKYWEB,
                                     DFI_MOVE_PROTECT, DFI_MOVE_EARTHQUAKE};
    for (size_t i = 0u; i < sizeof plain / sizeof plain[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[plain[i]] & DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) == 0u);
    }
}

/* A two-turn move that would cost a Pressure extra is refused (E_UNSUPPORTED) at its PP: the charge turn names no target, so
 * the players could not derive the extra (src/combat/turn.c, dfi_run_move). Forretress learns Solar Beam (the pool), so the
 * setup of g53_mustpressure gives it Solar Beam in the slot of its Spikes, and the first move step of the battle aims it at
 * Kingambit (Pressure): refused, and the battle is unchanged. The control aims it at its ally Indeedee (no Pressure, the extra is
 * none): the same step is accepted. */
static void check_charge_refused(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g53_mustpressure");
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 2u)) {
        return;
    }
    for (uint32_t control = 0u; control < 2u; ++control) {
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        setup.sides[0].members[0].moves[0].move_id = DFI_MOVE_SOLARBEAM;
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            return;
        }
        const df_conf_step *team = &cb->steps[0];
        duoforge_decision_bundle bd;
        bundle_of(team, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[team->tape_off], team->tape_len, &used, &res) ==
                             DUOFORGE_OK && used == team->tape_len)) {
            duoforge_battle_destroy(b);
            return;
        }
        duoforge_observation before[DUOFORGE_SIDE_COUNT];
        duoforge_observation after[DUOFORGE_SIDE_COUNT];
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
            DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &before[p]) == DUOFORGE_OK);
        }
        bundle_of(&cb->steps[1], b, &bd);
        /* the recorded first move step: Forretress (side 0, slot 0) uses its move 1, now Solar Beam, at Kingambit (flat 2) or at
         * its ally Indeedee (flat 1) */
        bd.responses[0].slots[0].target = control != 0u ? 1u : 2u;
        const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
        if (control == 0u) {
            DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
            for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
                DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &after[p]) == DUOFORGE_OK);
                DF_CHECK(t, memcmp(&before[p], &after[p], sizeof before[p]) == 0);
            }
        } else {
            DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
    }
}

/* A move whose line hides its target (a [still] line names none) costs a Pressure extra that depends on the target: refused
 * (E_UNSUPPORTED), never guessed, because the viewer cannot tell which foe the extra came from (src/combat/turn.c, dfi_still).
 * g53_trace_pressure: Gardevoir has Pressure from its Trace copy; the first step's choices are Moonblast and Protect, and at
 * the second step Kingambit's Sucker Punch at Gardevoir fails, with its line hidden, if Gardevoir protects (its move 2). The
 * control is the recorded choice (Moonblast): the line names the target and the step is accepted. */
static void check_hidden_target_refused(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g53_trace_pressure");
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 2u)) {
        return;
    }
    for (uint32_t control = 0u; control < 2u; ++control) {
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            return;
        }
        const df_conf_step *team = &cb->steps[0];
        duoforge_decision_bundle bd;
        bundle_of(team, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[team->tape_off], team->tape_len, &used, &res) ==
                             DUOFORGE_OK && used == team->tape_len)) {
            duoforge_battle_destroy(b);
            return;
        }
        duoforge_observation before[DUOFORGE_SIDE_COUNT];
        duoforge_observation after[DUOFORGE_SIDE_COUNT];
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
            DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &before[p]) == DUOFORGE_OK);
        }
        bundle_of(&cb->steps[1], b, &bd);
        if (control == 0u) {
            bd.responses[0].slots[0].move_slot = 1u; /* Gardevoir (side 0, slot 0) protects: its move 2 */
            bd.responses[0].slots[0].target = DUOFORGE_TARGET_NONE; /* Protect takes no target */
        }
        const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
        if (control == 0u) {
            DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
            for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
                DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &after[p]) == DUOFORGE_OK);
                DF_CHECK(t, memcmp(&before[p], &after[p], sizeof before[p]) == 0);
            }
        } else {
            DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g53");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_marks(&t);
        check_every_boundary(&t, ctx);
        check_charge_refused(&t, ctx);
        check_hidden_target_refused(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
