/*
 * duoforge.state.pool_lockfam_sleep (white-box). PREPARED for the fix of issue 606 (decision 0015 entry 5dv, design:
 * docs/research/expansion/lockfam-sleep.md); NOT registered in tests/moves/tests.cmake until the fix lands, because the
 * fatigue checks of the first scenario fail on main by design (main removes the lock silently).
 *
 * lockedmove at the pin (data/conditions.ts:253-285; Outrage here, Thrash, Petal Dance and Raging Fury share it):
 * duration 2, onRestart sets it to 2 again when trueDuration >= 2, onAfterMove removes the lock at duration 1, onEnd adds
 * confusion unless trueDuration > 1, onResidual deletes the volatile silently when the holder is asleep and then counts
 * trueDuration down. The Residual event counts a handler's duration down FIRST (sim/battle.ts:515-522): at 0 it runs the
 * end (removeVolatile, so onEnd) and skips the handler's onResidual. A lock standing at the residual of a turn in which it
 * was not restarted is at duration 1, so its countdown ends it with onEnd, and the sleep branch of onResidual is never
 * reached. The tail's lock_turns is trueDuration (the engine counts it down at a restarted use).
 *
 * The battle: the reference teams B (side 0) and A (side 1) with side 1's Ceruledge replaced by an Arcanine with Outrage
 * in slot 0 (the set of the lane A campaign battle fz_6_175, marked on main). Arcanine leads at position 2 (side 1 slot 0)
 * beside Milotic (Hypnosis); side 0 leads Charizard and Grimmsnarl and switches both to Farigiraf and Archaludon, so the
 * Outrage always hits a target (no Fairy, no Protect) and its use restarts the lock when the count allows it. The lock is
 * set white-box at the turn boundary (lock_turns, the locked move, the last move), as duoforge.state.pool_g56 does. Every
 * scenario runs for the seeds 1..16 (the outcome does not depend on the draws: Milotic's accuracy is +6, so Hypnosis hits).
 *
 *   1. countdown_sleep_fatigue: lock_turns 1, Milotic at Speed +6 puts Arcanine to sleep before it moves (cant slp): the
 *      countdown ends the lock with onEnd, trueDuration 1 <= 1: fatigue confusion (one CONFUSION_TURNS draw, 2..5), its
 *      CONFUSION_START after the cant line (in the residual), no lock, no locked move. FAILS ON MAIN (issue 606).
 *   2. countdown_sleep_no_fatigue: as 1 with lock_turns 2: onEnd returns (trueDuration 2 > 1): no confusion, no lock.
 *   3. normal_last_use: lock_turns 1, Arcanine awake and first, Milotic uses Coil: the use does not restart the lock (count
 *      below 2), onAfterMove ends it, onEnd confuses: CONFUSION_START before Milotic's move, no lock (unchanged path).
 *   4. normal_restarted_use: lock_turns 2, as 3: the use restarts the lock, the residual counts it to 1; the lock and its
 *      locked move stay, no confusion (unchanged path).
 *   5. sleep_after_restarted_use: lock_turns 2, Arcanine first uses Outrage (restarted, duration 2), then Milotic puts it to
 *      sleep: the residual's countdown goes 2 -> 1 (no end), onResidual deletes the lock silently. No confusion although
 *      trueDuration is 1 by then: a fix that ended every sleeping holder's lock with onEnd would confuse here.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/extended_tables.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define HOLDER 2u  /* Arcanine: side 1, slot 0 */
#define PARTNER 3u /* Milotic: side 1, slot 1 */
#define SEEDS 16u

typedef struct roster {
    uint32_t lead0, lead1, res0, res1; /* side 0: Charizard, Grimmsnarl; Farigiraf, Archaludon */
    uint32_t arcanine, milotic, other0, other1;
    uint32_t hypnosis, coil; /* Milotic's move slots */
} roster;

static roster g_r;

static uint32_t find_species(const duoforge_side_setup *s, uint32_t species)
{
    for (uint32_t m = 0u; m < s->member_count; ++m) {
        if (s->members[m].species_id == species) {
            return m;
        }
    }
    return UINT32_MAX;
}

static uint32_t find_move(const duoforge_member_setup *m, uint32_t move)
{
    for (uint32_t k = 0u; k < m->move_count; ++k) {
        if (m->moves[k].move_id == move) {
            return k;
        }
    }
    return UINT32_MAX;
}

/* Team B against team A (pairing B-A), Ceruledge -> Arcanine @ Focus Sash, Intimidate, Jolly, 32 Atk / 32 Spe, Outrage,
 * Wild Charge, Flare Blitz, Extreme Speed (fz_6_175's set; Item Clause: no other Focus Sash on team A). */
static bool make_setup(df_test *t, duoforge_battle_setup *s)
{
    if (!DF_CHECK(t, duoforge_reference_setup(1u, s) == DUOFORGE_OK)) {
        return false;
    }
    const uint32_t c = find_species(&s->sides[1], DFI_FORME_CERULEDGE);
    if (!DF_CHECK(t, c != UINT32_MAX)) {
        return false;
    }
    duoforge_member_setup *a = &s->sides[1].members[c];
    memset(a, 0, sizeof *a);
    a->species_id = DFI_FORME_ARCANINE;
    a->gender = DUOFORGE_GENDER_MALE;
    a->nature = DFI_NATURE_JOLLY;
    a->stat_points[1] = 32u;
    a->stat_points[5] = 32u;
    a->ability = 1u + DFI_ABILITY_INTIMIDATE;
    a->item = 1u + DFI_ITEM_FOCUSSASH;
    a->move_count = 4u;
    a->moves[0].move_id = DFI_MOVE_OUTRAGE;
    a->moves[1].move_id = DFI_MOVE_WILDCHARGE;
    a->moves[2].move_id = DFI_MOVE_FLAREBLITZ;
    a->moves[3].move_id = DFI_MOVE_EXTREMESPEED;
    g_r.arcanine = c;
    g_r.milotic = find_species(&s->sides[1], DFI_FORME_MILOTIC);
    g_r.lead0 = find_species(&s->sides[0], DFI_FORME_CHARIZARD);
    g_r.lead1 = find_species(&s->sides[0], DFI_FORME_GRIMMSNARL);
    g_r.res0 = find_species(&s->sides[0], DFI_FORME_FARIGIRAF);
    g_r.res1 = find_species(&s->sides[0], DFI_FORME_ARCHALUDON);
    if (!DF_CHECK(t, g_r.milotic != UINT32_MAX && g_r.lead0 != UINT32_MAX && g_r.lead1 != UINT32_MAX &&
                         g_r.res0 != UINT32_MAX && g_r.res1 != UINT32_MAX)) {
        return false;
    }
    g_r.hypnosis = find_move(&s->sides[1].members[g_r.milotic], DFI_MOVE_HYPNOSIS);
    g_r.coil = find_move(&s->sides[1].members[g_r.milotic], DFI_MOVE_COIL);
    g_r.other0 = UINT32_MAX;
    g_r.other1 = UINT32_MAX;
    for (uint32_t m = 0u; m < s->sides[1].member_count; ++m) {
        if (m == g_r.arcanine || m == g_r.milotic) {
            continue;
        }
        if (g_r.other0 == UINT32_MAX) {
            g_r.other0 = m;
        } else if (g_r.other1 == UINT32_MAX) {
            g_r.other1 = m;
        }
    }
    return DF_CHECK(t, g_r.hypnosis != UINT32_MAX && g_r.coil != UINT32_MAX && g_r.other1 != UINT32_MAX);
}

/* A battle at its first TURN boundary: Arcanine and Milotic lead side 1, Charizard and Grimmsnarl side 0. */
static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle_setup s;
    if (!make_setup(t, &s)) {
        return NULL;
    }
    duoforge_battle *b = df_make_battle(ctx, &s);
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    const uint32_t picks[2][4] = {{g_r.lead0, g_r.lead1, g_r.res0, g_r.res1},
                                  {g_r.arcanine, g_r.milotic, g_r.other0, g_r.other1}};
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd.responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)picks[side][i];
        }
    }
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].occupant, g_r.arcanine);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[1].occupant, g_r.milotic);
    return b;
}

typedef struct scenario {
    const char *name;
    uint32_t lock_turns;   /* trueDuration at the turn boundary */
    bool partner_first;    /* Milotic at Speed +6 moves before Arcanine */
    bool hypnosis;         /* Milotic uses Hypnosis on Arcanine, else Coil */
    /* expected after the step */
    bool asleep;
    uint32_t lock_after;
    bool confused;          /* a fatigue confusion: CONFUSION_START for the holder, confusion_turns 2..5 */
    bool confusion_in_residual; /* the confusion's line comes after every move line (else before Milotic's move) */
} scenario;

/* Side 0 switches both leads out; Arcanine's locked slot takes its move with no target; Milotic Hypnosis or Coil. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const scenario *sc)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    duoforge_side_choice *c0 = &bd->responses[0];
    c0->epoch = b->request_epoch;
    c0->side = 0u;
    c0->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c0->slots[0].kind = (uint8_t)DUOFORGE_SLOT_SWITCH;
    c0->slots[0].reserve = (uint8_t)g_r.res0;
    c0->slots[1].kind = (uint8_t)DUOFORGE_SLOT_SWITCH;
    c0->slots[1].reserve = (uint8_t)g_r.res1;
    duoforge_side_choice *c1 = &bd->responses[1];
    c1->epoch = b->request_epoch;
    c1->side = 1u;
    c1->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c1->slots[0].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c1->slots[0].move_slot = 0u;
    c1->slots[0].target = (uint8_t)DUOFORGE_TARGET_NONE;
    c1->slots[1].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c1->slots[1].move_slot = (uint8_t)(sc->hypnosis ? g_r.hypnosis : g_r.coil);
    c1->slots[1].target = sc->hypnosis ? (uint8_t)HOLDER : (uint8_t)DUOFORGE_TARGET_NONE;
}

/* Arcanine is locked into Outrage (slot 0) with `turns` of the count; Milotic's accuracy is +6 (Hypnosis always hits) and,
 * when it is to move first, its Speed +6. */
static void arrange(duoforge_battle *b, const scenario *sc)
{
    b->tail.sides[1].positions[0].lock_turns = (uint8_t)sc->lock_turns;
    b->sides[1].positions[0].locked_move = 1u;
    b->tail.sides[1].positions[0].last_move = 1u; /* a running lock's move is the one used last (Outrage, slot 0) */
    b->sides[1].positions[1].stages[5] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
    if (sc->partner_first) {
        b->sides[1].positions[1].stages[4] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
    }
}

static duoforge_event g_ev[2][DUOFORGE_MAX_EVENTS];

static uint32_t find_event(uint32_t p, uint32_t count, uint8_t kind, uint8_t position, uint32_t from)
{
    for (uint32_t i = from; i < count; ++i) {
        if (g_ev[p][i].kind == kind && g_ev[p][i].position == position) {
            return i;
        }
    }
    return UINT32_MAX;
}

static uint32_t count_events(uint32_t p, uint32_t count, uint8_t kind, uint8_t position)
{
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < count; ++i) {
        n += (g_ev[p][i].kind == kind && g_ev[p][i].position == position) ? 1u : 0u;
    }
    return n;
}

static void run_scenario(df_test *t, const duoforge_context *ctx, const duoforge_battle *base, const scenario *sc)
{
    const unsigned long failed_before = t->failures;
    for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
        duoforge_battle *y = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
            return;
        }
        DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
        arrange(y, sc);
        DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
        duoforge_decision_bundle bd;
        turn_bundle(&bd, y, sc);
        duoforge_event_buffer buf[2] = {{g_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {g_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
        duoforge_step_result res;
        const duoforge_status st = duoforge_battle_step_events(ctx, y, &bd, &res, buf);
        if (!DF_CHECK(t, st == DUOFORGE_OK)) {
            fprintf(stderr, "  %s seed %u: status %d\n", sc->name, (unsigned)seed, (int)st);
            duoforge_battle_destroy(y);
            continue;
        }
        DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, y->boundary_kind, DUOFORGE_BOUNDARY_TURN);
        const dfi_member *arc = &y->sides[1].members[g_r.arcanine];
        const dfi_active_slot *pos = &y->sides[1].positions[0];
        DF_CHECK_EQ_U64(t, pos->occupant, g_r.arcanine);
        DF_CHECK_EQ_U64(t, arc->status == DFI_STATUS_SLP ? 1u : 0u, sc->asleep ? 1u : 0u);
        DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[0].lock_turns, sc->lock_after);
        DF_CHECK_EQ_U64(t, pos->locked_move, sc->lock_after != 0u ? 1u : 0u);
        for (uint32_t p = 0u; p < 2u; ++p) {
            const uint32_t n = buf[p].count;
            const uint32_t used = find_event(p, n, DUOFORGE_EVENT_MOVE, (uint8_t)HOLDER, 0u);
            const uint32_t cant = find_event(p, n, DUOFORGE_EVENT_CANT, (uint8_t)HOLDER, 0u);
            const uint32_t partner_move = find_event(p, n, DUOFORGE_EVENT_MOVE, (uint8_t)PARTNER, 0u);
            /* the holder moved, or the sleep stopped it before its move */
            DF_CHECK_EQ_U64(t, used != UINT32_MAX ? 1u : 0u, sc->partner_first ? 0u : 1u);
            DF_CHECK_EQ_U64(t, cant != UINT32_MAX ? 1u : 0u, sc->partner_first ? 1u : 0u);
            if (cant != UINT32_MAX) {
                DF_CHECK_EQ_U64(t, g_ev[p][cant].cause, DUOFORGE_CAUSE_SLEEP);
            }
            DF_CHECK(t, partner_move != UINT32_MAX);
            const uint32_t start = find_event(p, n, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER, 0u);
            const bool fatigue_line = DF_CHECK_EQ_U64(t, count_events(p, n, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER),
                                                      sc->confused ? 1u : 0u);
            if (fatigue_line && start != UINT32_MAX) {
                if (sc->confusion_in_residual) {
                    /* the residual: after every move line and the cant line, before the TURN line */
                    for (uint32_t i = start; i < n; ++i) {
                        DF_CHECK(t, g_ev[p][i].kind != DUOFORGE_EVENT_MOVE && g_ev[p][i].kind != DUOFORGE_EVENT_CANT);
                    }
                    DF_CHECK(t, find_event(p, n, DUOFORGE_EVENT_TURN, DUOFORGE_NO_POSITION, start) != UINT32_MAX);
                } else {
                    /* the lock's end at the use (onAfterMove): after the holder's move, before Milotic's */
                    DF_CHECK(t, used != UINT32_MAX && used < start && start < partner_move);
                }
            }
        }
        if (sc->confused) {
            DF_CHECK(t, pos->confusion_turns >= 2u && pos->confusion_turns <= 5u);
        } else {
            DF_CHECK_EQ_U64(t, pos->confusion_turns, 0u);
        }
        duoforge_battle_destroy(y);
    }
    if (t->failures != failed_before) {
        fprintf(stderr, "  scenario %s: %lu failed checks\n", sc->name, t->failures - failed_before);
    } else {
        fprintf(stderr, "  scenario %s: ok\n", sc->name);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_lockfam_sleep");
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_battle *base = turn_battle(&t, kp);
    if (base != NULL) {
        static const scenario sc[] = {
            {"countdown_sleep_fatigue", 1u, true, true, true, 0u, true, true},
            {"countdown_sleep_no_fatigue", 2u, true, true, true, 0u, false, false},
            {"normal_last_use", 1u, false, false, false, 0u, true, false},
            {"normal_restarted_use", 2u, false, false, false, 1u, false, false},
            {"sleep_after_restarted_use", 2u, false, true, true, 0u, false, false},
        };
        for (size_t i = 0u; i < sizeof sc / sizeof sc[0]; ++i) {
            run_scenario(&t, kp, base, &sc[i]);
        }
        duoforge_battle_destroy(base);
    }
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
