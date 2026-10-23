/*
 * duoforge.state.pool_g87 (white-box): step G87 of the content expansion (decision 0080): Attract's source is public. The observation
 * carries the source's flat position in volatiles2 bits 12 and 13 (for both players), a from-view world copies the source byte of the
 * view, and an inconsistent byte in a view is refused (E_MALFORMED). The corpus test replays every recorded pool battle, and at every
 * decision point with an infatuated occupant it builds both players' views into worlds and compares them with the engine.
 *
 * The battles are the recorded pool battles of tests/reference/conformance_pool.h; the rev 5 reserve bytes 0 to 3 are the Attract
 * sources (1 + side * 6 + roster index), so a source byte names its member, and the member's flat position is its occupant's position.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The battle g65_water_bubble: flat 0 Araquanid (M, side 0 roster 0), flat 1 Milotic (F, side 0 roster 1), flat 2 Incineroar (M,
 * side 1 roster 0), flat 3 Skeledirge (F, side 1 roster 1); Sneasler (M) is side 1 roster 3 and benched. */
#define G87_ARA 0u
#define G87_MIL 1u
#define G87_INC 2u
#define G87_SKE 3u

#define G87_ATTRACT_OFF (DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE + DFI_ENC_TAIL5_ATTRACT_OFF)

static uint8_t code_of(uint32_t side, uint32_t m)
{
    return (uint8_t)(1u + side * DUOFORGE_MAX_ROSTER + m);
}

static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void setup_from(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0u; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

/* The decision bundle of one recorded step (as test_conformance.c runs it). */
static void step_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const df_conf_step *st)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u));
    for (uint32_t s = 0u; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0u; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0u; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* The recorded battle `name` after its team preview, under POOL. */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (*ctx == NULL || cb == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    team_bundle(&bd, *b);
    return duoforge_battle_step(*ctx, *b, &bd, &res) == DUOFORGE_OK;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* The observation's Attract bits of both players, for a battle: the source flats and the presence bits must agree. */
static bool observe(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer, duoforge_observation_ext *o)
{
    memset(o, 0, sizeof *o);
    DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, viewer, o), DUOFORGE_OK);
    return o->revision != 0u;
}

/* The bits of the observation: each infatuated position shows its source's flat position in bits 12-13 of volatiles2, and an
 * empty source is zero everywhere; a position without infatuation has no bits at all. */
static void test_observation_bits(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    duoforge_observation_ext o;
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        observe(t, ctx, b, viewer, &o);
        for (uint32_t s = 0u; s < 2u; ++s) {
            for (uint32_t p = 0u; p < 2u; ++p) {
                DF_CHECK_EQ_U64(t, o.volatiles2[s][p], 0u);
                DF_CHECK_EQ_U64(t, o.sides[s].positions[p].volatiles & DUOFORGE_POSITION_EXT_ATTRACT, 0u);
            }
        }
    }
    /* Milotic (ally, flat 1) infatuates Araquanid (flat 0): the source is flat 1; Skeledirge (foe, flat 3) infatuates Incineroar
     * (flat 2): the source is flat 3. */
    b->tail.attract_source[G87_ARA] = code_of(0u, 1u);
    b->tail.attract_source[G87_INC] = code_of(1u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        observe(t, ctx, b, viewer, &o);
        DF_CHECK_EQ_U64(t, o.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ATTRACT, DUOFORGE_POSITION_EXT_ATTRACT);
        DF_CHECK_EQ_U64(t, o.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_ATTRACT, DUOFORGE_POSITION_EXT_ATTRACT);
        DF_CHECK_EQ_U64(t, o.volatiles2[0][0], (uint32_t)G87_MIL << 12u);
        DF_CHECK_EQ_U64(t, o.volatiles2[1][0], (uint32_t)G87_SKE << 12u);
        DF_CHECK_EQ_U64(t, o.volatiles2[0][1], 0u);
        DF_CHECK_EQ_U64(t, o.volatiles2[1][1], 0u);
        DF_CHECK_EQ_U64(t, o.sides[0].positions[1].volatiles & DUOFORGE_POSITION_EXT_ATTRACT, 0u);
        /* the bits are the same word in both players' records (the source is public for both) */
        DF_CHECK_EQ_U64(t, o.volatiles2[0][0] & ~0x3000u, 0u);
    }
    /* a source that stands on the bench is an invariant failure, so no observation is made from it (the state check) */
    b->tail.attract_source[G87_ARA] = code_of(1u, 3u);
    DF_CHECK_EQ_U64(t, duoforge_battle_observe_ext(ctx, b, 0u, &o), DUOFORGE_E_INVARIANT);
    b->tail.attract_source[G87_ARA] = 0u;
    b->tail.attract_source[G87_INC] = 0u;
    finish(ctx, b);
}

/* A from-view world copies the source byte of a consistent view, and an inconsistent byte in the view is refused (E_MALFORMED): the
 * holder itself, a benched member, a code past the roster, and a holder position that is empty. */
static void test_from_view(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    duoforge_battle_setup s;
    setup_from(find_conf("g65_water_bubble"), &s);
    duoforge_battle *world = df_make_battle(ctx, &s);
    DF_CHECK(t, world != NULL);
    b->tail.attract_source[G87_ARA] = code_of(1u, 1u);
    duoforge_public_state view;
    duoforge_hypothesis hyp;
    memset(&view, 0, sizeof view);
    memset(&hyp, 0, sizeof hyp);
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, b, 0u, &view), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_hypothesis(ctx, b, 0u, &hyp), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &view, &hyp, world), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, world->tail.attract_source[G87_ARA], code_of(1u, 1u));
    for (uint32_t f = 0u; f < DFI_ATTRACT_SLOTS; ++f) {
        DF_CHECK_EQ_U64(t, world->tail.attract_source[f], b->tail.attract_source[f]);
    }
    /* the view's byte, tampered: each inconsistent value is malformed */
    const uint8_t bad[] = {code_of(0u, 0u), code_of(1u, 3u), DFI_ATTRACT_MEMBER_MAX + 1u};
    for (uint32_t k = 0u; k < sizeof bad / sizeof bad[0]; ++k) {
        view.state[G87_ATTRACT_OFF + G87_ARA] = bad[k];
        DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &view, &hyp, world), DUOFORGE_E_MALFORMED);
    }
    /* an empty holder position: the holder's occupant byte is DFI_OCCUPANT_NONE */
    view.state[G87_ATTRACT_OFF + G87_ARA] = code_of(1u, 1u);
    view.state[DFI_ENC_SIDE_OFF + DFI_ENC_SIDE_POS_OFF] = DFI_OCCUPANT_NONE;
    DF_CHECK_EQ_U64(t, duoforge_battle_from_view(ctx, &view, &hyp, world), DUOFORGE_E_MALFORMED);
    b->tail.attract_source[G87_ARA] = 0u;
    if (world != NULL) {
        duoforge_battle_destroy(world);
    }
    finish(ctx, b);
}

/* Pair invariant on the engine's state: the byte names an active source of the other gender pair, so a benched source is refused
 * (E_INVARIANT by the check and by the observation). */
static void test_pair_invariant(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->tail.attract_source[G87_ARA] = code_of(1u, 3u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.attract_source[G87_ARA] = code_of(0u, 0u);
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.attract_source[G87_ARA] = code_of(0u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    b->tail.attract_source[G87_ARA] = 0u;
    finish(ctx, b);
}

/* The corpus: every recorded pool battle, replayed step by step (as test_conformance.c). At every decision point (the end of a step)
 * with an infatuated occupant, both players' views are built into worlds: public(world) equals the view, the world's source bytes
 * equal the engine's, and the observation's Attract bits of the world equal the engine's. */
typedef struct g87_counts {
    uint32_t steps;               /* the steps (decision points) with an infatuated occupant, in any battle */
    uint32_t points[2];           /* per viewer: the steps where the view was taken */
    uint32_t public_refused[2];   /* a refusal of the view for another cause (not Attract) */
    uint32_t built[2];            /* from_view built the world */
    uint32_t mismatch[2];         /* a check of the world failed */
    uint32_t infatuated[2];       /* the infatuated positions the views showed, summed over the points */
    uint32_t battles;             /* battles replayed to the end */
    uint32_t skipped;             /* battles the context refused */
} g87_counts;

static bool any_attract(const duoforge_battle *b)
{
    for (uint32_t f = 0u; f < DFI_ATTRACT_SLOTS; ++f) {
        if (b->tail.attract_source[f] != 0u) {
            return true;
        }
    }
    return false;
}

static void check_point(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, duoforge_battle *world, uint32_t viewer,
                        g87_counts *c)
{
    c->points[viewer] += 1u;
    duoforge_public_state view;
    duoforge_hypothesis hyp;
    memset(&view, 0, sizeof view);
    memset(&hyp, 0, sizeof hyp);
    const duoforge_status pub = duoforge_battle_public(ctx, b, viewer, &view);
    if (pub != DUOFORGE_OK) {
        uint32_t causes = 0u;
        (void)duoforge_battle_public_causes(ctx, b, viewer, &causes);
        fprintf(stderr, "  g87 public refusal (viewer %u, step %u, boundary %u): %s, causes %u\n", viewer, c->steps,
                (unsigned)b->boundary_kind, duoforge_status_name(pub), causes);
        c->public_refused[viewer] += 1u;
        return;
    }
    for (uint32_t f = 0u; f < DFI_ATTRACT_SLOTS; ++f) {
        c->infatuated[viewer] += b->tail.attract_source[f] != 0u ? 1u : 0u;
    }
    if (duoforge_battle_hypothesis(ctx, b, viewer, &hyp) != DUOFORGE_OK ||
        duoforge_battle_from_view(ctx, &view, &hyp, world) != DUOFORGE_OK) {
        c->mismatch[viewer] += 1u;
        return;
    }
    c->built[viewer] += 1u;
    duoforge_public_state again;
    memset(&again, 0, sizeof again);
    bool same = duoforge_battle_public(ctx, world, viewer, &again) == DUOFORGE_OK && again.state_size == view.state_size &&
                memcmp(again.state, view.state, view.state_size) == 0;
    for (uint32_t f = 0u; f < DFI_ATTRACT_SLOTS; ++f) {
        same = same && world->tail.attract_source[f] == b->tail.attract_source[f];
    }
    duoforge_observation_ext eb;
    duoforge_observation_ext ew;
    memset(&eb, 0, sizeof eb);
    memset(&ew, 0, sizeof ew);
    same = same && duoforge_battle_observe_ext(ctx, b, viewer, &eb) == DUOFORGE_OK &&
           duoforge_battle_observe_ext(ctx, world, viewer, &ew) == DUOFORGE_OK;
    for (uint32_t s = 0u; s < 2u; ++s) {
        for (uint32_t p = 0u; p < 2u; ++p) {
            same = same && eb.volatiles2[s][p] == ew.volatiles2[s][p] &&
                   (eb.sides[s].positions[p].volatiles & DUOFORGE_POSITION_EXT_ATTRACT) ==
                       (ew.sides[s].positions[p].volatiles & DUOFORGE_POSITION_EXT_ATTRACT);
        }
    }
    if (!same) {
        c->mismatch[viewer] += 1u;
    }
    (void)t;
}

static void test_corpus(df_test *t)
{
    g87_counts c;
    memset(&c, 0, sizeof c);
    duoforge_context *k1 = df_make_context(&df_config_pool);
    duoforge_context *k2 = df_make_context(&df_config_pool_dev);
    DF_CHECK(t, k1 != NULL && k2 != NULL);
    for (size_t bi = 0u; bi < sizeof conf_battles / sizeof conf_battles[0]; ++bi) {
        const df_conf_battle *cb = &conf_battles[bi];
        duoforge_battle_setup setup;
        setup_from(cb, &setup);
        const duoforge_context *ctx = k1;
        duoforge_battle *b = NULL;
        if (duoforge_battle_create(k1, &setup, &b) != DUOFORGE_OK) {
            ctx = k2;
            if (duoforge_battle_create(k2, &setup, &b) != DUOFORGE_OK) {
                c.skipped += 1u;
                continue;
            }
        }
        duoforge_battle *world = NULL;
        if (duoforge_battle_create(ctx, &setup, &world) != DUOFORGE_OK) {
            c.skipped += 1u;
            duoforge_battle_destroy(b);
            continue;
        }
        bool replayed = true;
        for (uint32_t si = 0u; si < cb->step_count && replayed; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            step_bundle(&bd, b, st);
            duoforge_step_result res;
            uint32_t used = 0xFFFFFFFFu;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            const duoforge_status status =
                dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
            replayed = status == DUOFORGE_OK && used == st->tape_len;
            if (!replayed) {
                break;
            }
            if (any_attract(b)) {
                c.steps += 1u;
                for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                    check_point(t, ctx, b, world, viewer, &c);
                }
            }
        }
        if (replayed) {
            c.battles += 1u;
        }
        duoforge_battle_destroy(world);
        duoforge_battle_destroy(b);
    }
    fprintf(stderr,
            "  g87 corpus: %u battles to the end (%u skipped), %u steps with an infatuated occupant; per viewer 0 / 1: "
            "views %u / %u, public refused %u / %u, worlds built %u / %u, mismatches %u / %u, infatuated positions %u / %u\n",
            c.battles, c.skipped, c.steps, c.points[0], c.points[1], c.public_refused[0], c.public_refused[1], c.built[0], c.built[1],
            c.mismatch[0], c.mismatch[1], c.infatuated[0], c.infatuated[1]);
    /* Measured on the committed pool corpus: 22 decision points with an infatuated occupant (steps), each with both views taken.
     * One view per player is refused for an older reason, the PIVOT without a public move (E_UNSUPPORTED, no cause bit) at the same
     * step; every other view builds a world, and every world equals the engine (no mismatch). */
    DF_CHECK_EQ_U64(t, c.steps, 22u);
    DF_CHECK_EQ_U64(t, c.mismatch[0] + c.mismatch[1], 0u);
    DF_CHECK_EQ_U64(t, c.public_refused[0], 1u);
    DF_CHECK_EQ_U64(t, c.public_refused[1], 1u);
    DF_CHECK_EQ_U64(t, c.built[0], 21u);
    DF_CHECK_EQ_U64(t, c.built[1], 21u);
    DF_CHECK_EQ_U64(t, c.built[0] + c.built[1], 42u);
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
}

/* Issue #395: an Attract source that fainted keeps its byte only at TERMINAL (the battle's last action runs no Update: the pin's
 * runAction returns after the faintMessages that ends the battle, sim/battle.ts:2837, before the Update at 2845). Outside TERMINAL the
 * same state is refused, and the source keeps its position (occupant) as the observation's bits name it. */
static void test_fainted_source(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    if (!start(t, "g65_water_bubble", &ctx, &b)) {
        finish(ctx, b);
        return;
    }
    b->tail.attract_source[G87_ARA] = code_of(1u, 1u); /* Skeledirge (F, flat 3) infatuates Araquanid (M) */
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    /* the foe's HP display of a seen fainted member reads 0 (side 0's knowledge of side 1): with it, the byte is the only rule
     * that the fainted source can break, so the negatives below test the attract rule and nothing else */
    dfi_knowledge saved_k_live[DUOFORGE_MAX_ROSTER];
    memcpy(saved_k_live, b->sides[0].knowledge, sizeof saved_k_live);
    b->sides[0].knowledge[1].hp_percent = 0u;
    b->sides[0].knowledge[1].hp_flag = DUOFORGE_HP_FLAG_NONE;
    b->sides[1].members[1].hp = 0u; /* the source faints (its position keeps it as occupant) */
    b->tail.attract_source[G87_ARA] = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK); /* without the byte the fainted state is valid */
    b->tail.attract_source[G87_ARA] = code_of(1u, 1u);
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_E_INVARIANT); /* a live battle: the Update must have ended it */
    memcpy(b->sides[0].knowledge, saved_k_live, sizeof saved_k_live);
    b->sides[0].knowledge[1].hp_percent = 0u;
    b->sides[0].knowledge[1].hp_flag = DUOFORGE_HP_FLAG_NONE;
    /* the same state at the end of the battle (TERMINAL, the result set, no request): accepted, and the observation names the
     * fainted source's position (flat 3, bits 12-13) for both players */
    const uint8_t boundary = b->boundary_kind;
    const uint8_t mask = b->request_mask;
    const uint8_t result = b->result;
    /* the battle ends when the losing side has no Pokemon left: side 1 faints entirely (its occupants keep their positions); a
     * finished battle requests nothing (request_mask and requested_slots zero) */
    uint16_t saved_hp[DUOFORGE_MAX_ROSTER];
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        saved_hp[m] = b->sides[1].members[m].hp;
        b->sides[1].members[m].hp = 0u;
    }
    const uint8_t saved_req0 = b->sides[0].requested_slots;
    const uint8_t saved_req1 = b->sides[1].requested_slots;
    b->sides[0].requested_slots = 0u;
    b->sides[1].requested_slots = 0u;
    b->boundary_kind = DUOFORGE_BOUNDARY_TERMINAL;
    b->request_mask = 0u;
    b->result = DFI_RESULT_SIDE0;
    /* the foe's HP display of a seen fainted member reads 0 (the knowledge of side 0 about side 1) */
    dfi_knowledge saved_k[DUOFORGE_MAX_ROSTER];
    memcpy(saved_k, b->sides[0].knowledge, sizeof saved_k);
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if ((((uint32_t)b->sides[0].seen_mask >> m) & 1u) != 0u) { /* seen_mask: the foe members that side 0 has seen */
            b->sides[0].knowledge[m].hp_percent = 0u;
            b->sides[0].knowledge[m].hp_flag = DUOFORGE_HP_FLAG_NONE;
        }
    }
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        duoforge_observation_ext o;
        observe(t, ctx, b, viewer, &o);
        DF_CHECK_EQ_U64(t, o.volatiles2[0][0], (uint32_t)G87_SKE << 12u);
        DF_CHECK_EQ_U64(t, o.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ATTRACT, DUOFORGE_POSITION_EXT_ATTRACT);
    }
    b->boundary_kind = boundary;
    b->request_mask = mask;
    b->result = result;
    b->sides[0].requested_slots = saved_req0;
    b->sides[1].requested_slots = saved_req1;
    memcpy(b->sides[0].knowledge, saved_k, sizeof saved_k);
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        b->sides[1].members[m].hp = saved_hp[m];
    }
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g87");
    test_observation_bits(&t);
    test_from_view(&t);
    test_pair_invariant(&t);
    test_fainted_source(&t);
    test_corpus(&t);
    return df_test_end(&t);
}
