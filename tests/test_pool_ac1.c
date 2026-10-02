/*
 * duoforge.state.pool_ac1 (white-box): step AC1 of the ability-change work, Trace, in the POOL state tail (the member's
 * ability_now, decision 0015 section 7), in the event and in the view extension (decision 0018: position_ext.ability_now,
 * bit 2).
 *
 * The recorded battles ac1_trace_* (under "data": "pool") are replayed through the step with the reference's draws, as
 * in duoforge.reference.conformance_pool_data, which compares every HP, stage, request and event the reference shows
 * (a copied Intimidate or Drizzle shows in the lines that follow the -ability line; a copied Defiant shows when it
 * triggers) and the draws, among them Trace's: random(n) with n the candidates, also for one (the site TRACE).
 * Here the state that the reference does not show is read after every step: the tail's ability_now of every roster
 * member and both viewers' whole extension.
 *
 * What the battles show (the pin: data/abilities.ts:5118-5148 trace, sim/pokemon.ts:1908-1949 setAbility, :1508-1530
 * clearVolatile):
 *   ac1_trace_intimidate  two candidates (Incineroar: Intimidate, Kingambit: Defiant): the draw copies Intimidate, which
 *                         runs at once on both foes (Kingambit's Defiant answers).
 *   ac1_trace_defiant     the other pick: Defiant, a passive copy; Gardevoir has it when Incineroar's Intimidate comes.
 *   ac1_trace_drizzle     Politoed's Drizzle: the rain is set at once, the holder is the tracer.
 *   ac1_trace_single      the other foe is a Gardevoir whose ability is Trace (notrace), so Kingambit is the only
 *                         candidate and the draw is random(1); the slower foe Gardevoir then copies Intimidate from
 *                         Staraptor (the first Gardevoir's Defiant was a candidate as well).
 *   ac1_trace_switch      the switch-out reset: the copy ends when Gardevoir switches out, and it traces again, with a
 *                         new draw, when it comes back.
 * Also: a Mega Evolution ends a copied ability (formeChange -> setAbility), checked on a recorded Mega battle with a
 * ability_now (equal to the sheet's) written into the tail.
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

#define AB(name) (1u + DFI_ABILITY_##name)

/* The ability that each position's occupant has copied after each step of each battle (ability id + 1, 0 for none), as
 * the protocol lines alone say: `|-ability|X|NEW|OLD|[from] ability: Trace|[of] foe` sets it, a `|switch|`, `|drag|`,
 * `|replace|`, `|faint|` or `|-mega|` of the position clears it (decision 0018 section 6.1). The positions are p1a, p1b,
 * p2a, p2b. tools/reference/test_trace_to_c.py derives the rows from the committed traces and requires this table to
 * be exactly that, so the engine's tail and extension are checked against the protocol and not against itself. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t copied[4];
} rows[] = {
    {"ac1_trace_intimidate", 0u, {AB(INTIMIDATE), 0u, 0u, 0u}},
    {"ac1_trace_intimidate", 1u, {AB(INTIMIDATE), 0u, 0u, 0u}},
    {"ac1_trace_defiant", 0u, {AB(DEFIANT), 0u, 0u, 0u}},
    {"ac1_trace_defiant", 1u, {AB(DEFIANT), 0u, 0u, 0u}},
    {"ac1_trace_drizzle", 0u, {AB(DRIZZLE), 0u, 0u, 0u}},
    {"ac1_trace_drizzle", 1u, {AB(DRIZZLE), 0u, 0u, 0u}},
    {"ac1_trace_single", 0u, {AB(DEFIANT), 0u, 0u, AB(INTIMIDATE)}},
    {"ac1_trace_single", 1u, {AB(DEFIANT), 0u, 0u, AB(INTIMIDATE)}},
    {"ac1_trace_switch", 0u, {AB(INTIMIDATE), 0u, 0u, 0u}},
    {"ac1_trace_switch", 1u, {AB(INTIMIDATE), 0u, 0u, 0u}},
    {"ac1_trace_switch", 2u, {0u, 0u, 0u, 0u}},
    {"ac1_trace_switch", 3u, {AB(DEFIANT), 0u, 0u, 0u}},
    {"ac1_trace_switch", 4u, {AB(DEFIANT), 0u, 0u, 0u}},
    {"ac1_trace_switch", 5u, {AB(DEFIANT), 0u, 0u, 0u}},
};

/* After every step of the battles: the tail's ability_now by roster member is exactly the occupants' copies of the
 * rows (and no other member has one), the sheet abilities are untouched, and both viewers' extension equals the
 * expected one byte for byte: revision, viewer, epoch, the supported bits, ability_now at those positions and nothing
 * else. A copy is public (the -ability line is in both players' streams), so the two sides' sections are the same. */
static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    static const char *const names[] = {"ac1_trace_intimidate", "ac1_trace_defiant", "ac1_trace_drizzle",
                                        "ac1_trace_single", "ac1_trace_switch"};
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
            const uint32_t *copied = NULL;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, names[n]) == 0 && rows[r].step == si) {
                    copied = rows[r].copied;
                }
            }
            if (!DF_CHECK(t, copied != NULL)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    uint32_t want = 0u;
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        if (b->sides[s].positions[p].occupant == m) {
                            want = copied[s * 2u + p];
                        }
                    }
                    if (!DF_CHECK_EQ_U64(t, b->tail.sides[s].ability_now[m], want)) {
                        fprintf(stderr, "  %s step %u: side %u member %u\n", names[n], si, s, m);
                    }
                    /* The sheet's ability is never touched: the copy is the tail's. */
                    DF_CHECK(t, want == 0u || b->sides[s].members[m].ability == AB(TRACE));
                }
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(t, (want.supported & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE)) != 0u);
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    want.sides[flat / 2u].positions[flat % 2u].ability_now = (uint16_t)copied[flat];
                }
                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's\n", names[n], si,
                            viewer);
                }
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

/* The Trace event of step 0 of ac1_trace_intimidate, as both players see it: one ABILITY event at Gardevoir (position
 * 0), the copied ability in id2 (ability + 1), cause ABILITY and the foe in `other` (Incineroar, position 2). */
static void check_event(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("ac1_trace_intimidate");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    const df_conf_step *st = &cb->steps[0];
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
    if (DF_CHECK(t, dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res,
                                                 buffers) == DUOFORGE_OK)) {
        for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
            uint32_t found = 0u;
            for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                const duoforge_event *e = &buffers[viewer].events[i];
                if (e->kind != (uint8_t)DUOFORGE_EVENT_ABILITY || e->cause != (uint8_t)DUOFORGE_CAUSE_ABILITY) {
                    continue;
                }
                found += 1u;
                DF_CHECK_EQ_U64(t, e->position, 0u);
                DF_CHECK_EQ_U64(t, e->other, 2u);
                DF_CHECK_EQ_U64(t, e->id2, AB(INTIMIDATE));
            }
            DF_CHECK_EQ_U64(t, found, 1u); /* the opponent sees the copy as well: it is public */
        }
    }
    duoforge_battle_destroy(b);
}

/* A Mega Evolution ends a copied ability: formeChange sets the ability to the Mega forme's (sim/pokemon.ts:1487). On
 * a recorded Mega battle every standing Pokemon is given an ability_now equal to its sheet's ability (nothing changes in
 * how the battle plays, so the recorded draws still fit) before each step; the Pokemon that Mega Evolves in the step has none after it,
 * and the others that stay on the field keep it. */
static void check_mega(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g12_floette_mega", "g11_soak_mega"};
    uint32_t megas = 0u;
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
            uint32_t mega_before[2][DUOFORGE_MAX_ROSTER];
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    mega_before[s][m] = b->sides[s].members[m].is_mega;
                }
                for (uint32_t p = 0u; p < 2u; ++p) {
                    const uint32_t occupant = b->sides[s].positions[p].occupant;
                    if (occupant < DUOFORGE_MAX_ROSTER && b->sides[s].members[occupant].hp != 0u) {
                        b->tail.sides[s].ability_now[occupant] = b->sides[s].members[occupant].ability; /* the sheet's own: no behaviour changes */
                    }
                }
            }
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    if (mega_before[s][m] == 0u && b->sides[s].members[m].is_mega != 0u) {
                        megas += 1u;
                        DF_CHECK_EQ_U64(t, b->tail.sides[s].ability_now[m], 0u);
                    }
                }
            }
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK(t, megas >= 2u);
}

/* Trace with no candidate: the pin goes on seeking at every later Update (effectState.seek), which is not modelled, so
 * the entry is E_UNSUPPORTED and the battle is unchanged (the step works on a copy). In ac1_trace_switch Gardevoir
 * switches out in step 2 and back in in step 3; before step 3 both foes are given Trace as their ability now (the
 * notrace ability, so neither can be copied), as if the only foe left were a Trace holder. */
static void check_no_candidate(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("ac1_trace_switch");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 3u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < 3u; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK)) {
            duoforge_battle_destroy(b);
            return;
        }
    }
    for (uint32_t p = 0u; p < 2u; ++p) {
        const uint32_t occupant = b->sides[1].positions[p].occupant;
        if (DF_CHECK(t, occupant < DUOFORGE_MAX_ROSTER && b->sides[1].members[occupant].hp != 0u)) {
            b->tail.sides[1].ability_now[occupant] = (uint16_t)AB(TRACE);
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_battle *before = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &before) == DUOFORGE_OK && before != NULL)) {
        const df_conf_step *st = &cb->steps[3];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                        DUOFORGE_E_UNSUPPORTED);
        bool equal = false;
        DF_CHECK(t, duoforge_battle_equal(ctx, b, before, &equal) == DUOFORGE_OK && equal);
    }
    duoforge_battle_destroy(before);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_ac1");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The public values this step uses, as numbers (all of them exist: the view bit and field of decision 0018, the
     * event kind and the cause; the new combination is documented in duoforge.h). */
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE, 2u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_EVENT_ABILITY, 34u);
    DF_CHECK_EQ_U64(&t, DFI_SITE_TRACE, 15u);
    DF_CHECK(&t, dfi_support.abilities[DFI_ABILITY_TRACE] != 0u);
    DF_CHECK(&t, dfi_pool_ability_family[DFI_ABILITY_TRACE].family == DFI_ABILITY_FAMILY_NONE);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE)) != 0u);

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    /* Two views per step: 14 rows. */
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    check_event(&t, kp);
    check_mega(&t, kp);
    check_no_candidate(&t, kp);

    /* The same battles under POOL_DEV (its own fingerprint, the same tables): the same tail and view. */
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev);
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
