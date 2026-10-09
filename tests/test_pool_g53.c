/*
 * duoforge.state.pool_g53 (white-box): step G53 of the content expansion (decision 0030), Pressure and the PP a viewer can
 * attribute to a foe's moves.
 *
 * Pressure (data/abilities.ts:3437-3449: onDeductPP returns 1 for a foe; useMoveInner sums the returns over the pressure
 * targets after the move's own PP, sim/battle-actions.ts:473-484) costs the user one more PP per standing foe with Pressure
 * that the move targets. The engine deducts it in the state, exactly. The viewer of the foe attributes the extra only where the
 * targets are visible to it (the fold in src/combat/events.c, dfi_pressure_charge): a single-target move whose line names its
 * target, and the classes whose targets follow from the class and the board (field, spread, mustpressure). A line made
 * [still] blanks the target (sim/battle.ts:3123-3138, attrLastMove), so that extra is not attributed: the foe's derived PP
 * is then higher than the owner's exact PP by exactly that extra. The recorded battles (g53_* under "data": "pool") replay
 * in duoforge.reference.conformance_pool_data, which compares the engine's PP with what the reference's lines allow the
 * viewer to attribute. Here the facts that battle comparison does not state:
 *
 *   - the marks and the flag: Pressure is supported; mustpressure (DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE, 0x800, and the
 *     engine bit DFI_MOVE_FLAG3_MUST_PRESSURE) is on
 *     Imprison, Spikes, Stealth Rock and Toxic Spikes, and on none of the moves the battles use without it;
 *   - at every boundary of every g53 battle, for both players and every move slot, the foe's derived PP equals the owner's
 *     exact PP, except the hidden extra of a [still] move, which is pinned below: g53_still_pressure, where the Sucker Punch
 *     of Kingambit (side 1, roster 0, slot 1) is one attributable PP higher after its first use and two after the second;
 *   - a control with a shown target (g53_trace_pressure, the Moonblast of Gardevoir) where the two are equal;
 *   - the charge of a two-turn move and of a [still] move is deducted in the state (accepted, not refused): Solar Beam at a
 *     Pressure foe costs its user two PP, one of its own and one for the foe; at its ally, one.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
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

/* The PP a player attributes to a foe move that its line hides: the one Pressure extra of the [still] Sucker Punch (its
 * target Gardevoir has Pressure from Trace, and no line names it), at Kingambit (side 1, roster 0, move slot 1), after
 * `steps` steps of g53_still_pressure: one use per move step, and each use is a [still] one. */
static uint32_t hidden_gap(const char *name, uint32_t steps, uint32_t side, uint32_t member, uint32_t slot)
{
    if (strcmp(name, "g53_still_pressure") != 0 || side != 1u || member != 0u || slot != 1u || steps < 2u) {
        return 0u;
    }
    return steps - 1u; /* the first step is the team step */
}

/* For every move slot of every member of both sides, at this boundary: the foe's view (derived) equals the owner's view
 * (exact) plus the hidden gap of the battle, which is 0 everywhere but the pinned [still] case. Returns the number of slots
 * compared, 0 on a failure. */
static uint32_t check_derived(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const char *name, uint32_t steps)
{
    duoforge_observation own[DUOFORGE_SIDE_COUNT];
    duoforge_observation foe[DUOFORGE_SIDE_COUNT];
    uint32_t compared = 0u;
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        if (!DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &own[p]) == DUOFORGE_OK) ||
            !DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u - p, &foe[p]) == DUOFORGE_OK)) {
            return 0u;
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        /* the owner (viewer `side`) sees its PP exact; the other player (viewer 1 - side) attributes it: foe[side] */
        const duoforge_side_view *ex = &own[side].sides[side];
        const duoforge_side_view *dv = &foe[side].sides[side];
        for (uint32_t m = 0u; m < ex->member_count; ++m) {
            for (uint32_t k = 0u; k < ex->members[m].move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                if (!DF_CHECK(t, ex->members[m].pp_kind == DUOFORGE_PP_EXACT && dv->members[m].pp_kind == DUOFORGE_PP_DERIVED)) {
                    return 0u;
                }
                const uint32_t gap = hidden_gap(name, steps, side, m, k);
                if (!DF_CHECK(t, (uint32_t)dv->members[m].pp[k] == (uint32_t)ex->members[m].pp[k] + gap)) {
                    fprintf(stderr, "  %s step %u: side %u member %u slot %u: attributed %u, exact %u, gap %u\n", name, steps,
                            side, m, k, (unsigned)dv->members[m].pp[k], (unsigned)ex->members[m].pp[k], gap);
                    return 0u;
                }
                compared += 1u;
            }
        }
    }
    return compared;
}

/* Every recorded g53 battle, at every boundary (k steps replayed for k = 1 to the battle's steps). */
static void check_every_boundary(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {
        "g53_single_target", "g53_spread_protect", "g53_field_trick_room", "g53_mustpressure",
        "g53_fainted_holder", "g53_pressure_ally", "g53_sticky_web", "g53_trace_pressure",
        "g53_fainted_field", "g53_switch_pressure", "g53_expanding_force", "g53_trace_switch", "g53_mega_pressure",
        "g53_switch_in_pressure", "g53_still_pressure",
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
            DF_CHECK(t, check_derived(t, ctx, b, names[i], steps) != 0u);
            duoforge_battle_destroy(b);
        }
    }
}

/* The hidden extra is a real charge: the [still] battle has its Sucker Punch exact at 6 after one use, and the foe sees 7. */
static void check_still_pinned(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g53_still_pressure", 2u);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    duoforge_observation own;
    duoforge_observation foe;
    DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &own) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &foe) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, own.sides[1].members[0].pp[1], 6u);  /* exact: 8 - (1 + the extra of Gardevoir) */
    DF_CHECK_EQ_U64(t, foe.sides[1].members[0].pp[1], 7u);  /* attributed: 8 - 1 */
    duoforge_battle_destroy(b);
}

static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_PRESSURE] != 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE, 0x800u);
    static const uint32_t must[] = {DFI_MOVE_IMPRISON, DFI_MOVE_SPIKES, DFI_MOVE_STEALTHROCK, DFI_MOVE_TOXICSPIKES};
    for (size_t i = 0u; i < sizeof must / sizeof must[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[must[i]] & DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) != 0u);
    }
    /* the moves the battles use without the flag: a single target, a spread, a field move, a foe-side move that is not
     * mustpressure (Sticky Web) and a Protect */
    static const uint32_t plain[] = {DFI_MOVE_SHADOWBALL, DFI_MOVE_HYPERVOICE, DFI_MOVE_TRICKROOM, DFI_MOVE_STICKYWEB,
                                     DFI_MOVE_PROTECT, DFI_MOVE_EARTHQUAKE};
    for (size_t i = 0u; i < sizeof plain / sizeof plain[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[plain[i]] & DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) == 0u);
    }
    /* The engine reads the third flags byte (DFI_MOVE_FLAG3_MUST_PRESSURE; decision 0020: the static flags have no engine
     * reader): it carries the public flag's value for every move, and its free bits are 0. */
    uint32_t must_rows = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const bool pub = (dfi_pool_move_static_flags[id] & DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) != 0u;
        const bool eng = (dfi_pool_move_flags3[id] & DFI_MOVE_FLAG3_MUST_PRESSURE) != 0u;
        DF_CHECK(t, pub == eng);
        DF_CHECK_EQ_U64(t, (uint32_t)dfi_pool_move_flags3[id] & ~(DFI_MOVE_FLAG3_REFLECTABLE | DFI_MOVE_FLAG3_MUST_PRESSURE |
                                                                  DFI_MOVE_FLAG3_BYPASSSUB), 0u);
        must_rows += eng ? 1u : 0u;
    }
    DF_CHECK(t, must_rows >= sizeof must / sizeof must[0]);
}

/* A two-turn charge into a Pressure foe is accepted and deducted: Solar Beam of Forretress (side 0, slot 0) at Kingambit costs 2
 * PP in the state (one of its own, one for the foe). Its control at the ally Indeedee costs 1. The battle is the recorded
 * g53_mustpressure, with Solar Beam in the slot of its Spikes, and the first move step. */
static void check_charge_accepted(df_test *t, const duoforge_context *ctx)
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
        duoforge_observation before;
        duoforge_observation after;
        DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &before) == DUOFORGE_OK);
        bundle_of(&cb->steps[1], b, &bd);
        /* Forretress (side 0, slot 0) uses its move 1, now Solar Beam, at Kingambit (flat 2) or at its ally Indeedee (flat 1) */
        bd.responses[0].slots[0].target = control != 0u ? 1u : 2u;
        const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
        DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &after) == DUOFORGE_OK);
        /* the charge is deducted in the state: its own PP and the foe's extra (2 at Kingambit, 1 at the ally) */
        const uint32_t drop = (uint32_t)before.sides[0].members[0].pp[0] - (uint32_t)after.sides[0].members[0].pp[0];
        DF_CHECK_EQ_U64(t, drop, control != 0u ? 1u : 2u);
        duoforge_battle_destroy(b);
    }
}

/* White-box (a constructed event list, the fold of the viewer): a Pokemon whose faint line has no damage line before it leaves the
 * count of the Pressure extra at once. g53_pressure_ally after its team step: Kingambit (Pressure) is on side 0 slot 1, and
 * Gholdengo (side 1 slot 1) Shadow Balls it in the next event; with the faint first, the Shadow Ball counts 1 (no extra). */
static void check_fold_fainted_holder(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g53_pressure_ally", 1u);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    static struct duoforge_battle after;
    memcpy(&after, b, sizeof after);
    dfi_events ev;
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_FAINT, 1u);
    duoforge_event shadow = dfi_event_make(DUOFORGE_EVENT_MOVE, 3u);
    shadow.id = (uint16_t)DFI_MOVE_SHADOWBALL;
    shadow.other = 1u; /* Kingambit's position, the only target of the line */
    ev.rec[1] = shadow;
    ev.count = 2u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, &after, &ev, 0u));
    /* the viewer's knowledge of Gholdengo (roster 1 of side 1), its Shadow Ball (move slot 0): one use, no extra */
    DF_CHECK_EQ_U64(t, after.sides[0].knowledge[1].moves_used[0], 1u);
    duoforge_battle_destroy(b);
}

/* White-box (the step API, a constructed locked turn): after the charge of Solar Beam into Kingambit (2 PP: its own and the
 * extra), the locked turn of the same move costs nothing: a locked move has no PP and no extra (sim/battle-actions.ts:289). */
static void check_locked_turn_free(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g53_mustpressure");
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 2u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    setup.sides[0].members[0].moves[0].move_id = DFI_MOVE_SOLARBEAM;
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    uint32_t used = 0xFFFFFFFFu;
    const df_conf_step *team = &cb->steps[0];
    bundle_of(team, b, &bd);
    if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[team->tape_off], team->tape_len, &used, &res) == DUOFORGE_OK &&
                         used == team->tape_len)) {
        duoforge_battle_destroy(b);
        return;
    }
    bundle_of(&cb->steps[1], b, &bd);
    bd.responses[0].slots[0].target = 2u; /* the charge at Kingambit */
    if (!DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_observation before;
    duoforge_observation after;
    DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &before) == DUOFORGE_OK);
    /* the locked turn: Forretress has only its locked move; Kingambit and Indeedee protect */
    /* the choices come from the engine's own domain: side 0 takes its locked Solar Beam (move 0) in slot 0, side 1 any choice */
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        static duoforge_side_choice cands[4096];
        uint32_t n = 0u;
        if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, s, cands, 4096u, &n) == DUOFORGE_OK && n != 0u)) {
            duoforge_battle_destroy(b);
            return;
        }
        uint32_t pick = n;
        for (uint32_t i = 0u; i < n && pick == n; ++i) {
            if (s == 0u ? (cands[i].slots[0].kind == DUOFORGE_SLOT_MOVE && cands[i].slots[0].move_slot == 0u) : true) {
                pick = i;
            }
        }
        if (!DF_CHECK(t, pick < n)) {
            duoforge_battle_destroy(b);
            return;
        }
        bd.responses[s] = cands[pick];
    }
    const duoforge_status locked_status = duoforge_battle_step(ctx, b, &bd, &res);
    if (locked_status != DUOFORGE_OK) {
        fprintf(stderr, "  locked turn: %s\n", duoforge_status_name(locked_status));
    }
    if (!DF_CHECK(t, locked_status == DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return;
    }
    DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &after) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, (uint32_t)before.sides[0].members[0].pp[0] - (uint32_t)after.sides[0].members[0].pp[0], 0u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g53");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_marks(&t);
        check_every_boundary(&t, ctx);
        check_still_pinned(&t, ctx);
        check_charge_accepted(&t, ctx);
        check_fold_fainted_holder(&t, ctx);
        check_locked_turn_free(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
