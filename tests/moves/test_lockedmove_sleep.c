/*
 * duoforge.moves.lockedmove_sleep (white-box): the fix of issue 606 (decision 0015 entry 5dv, design:
 * docs/research/expansion/lockfam-sleep.md). Before the fix the fatigue checks of the first scenario failed (the lock was
 * removed silently).
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
 * set white-box at the turn boundary (lock_turns, the locked move, the last move), as duoforge.moves.outrage_lock does. Every
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
 *
 * The PIVOT pause (decision 0015 5dv, HS variant (b)): scenario 1 with a pivot of side 0 AFTER Arcanine's `cant` and before
 * the residual, which then runs in the next call. The fact "this lock was not restarted this turn" is the state bit
 * DFI_SINGLE_TURN_LOCK_UNUSED, so it survives the pause. Side 0 is team B with Politoed replaced by a Scizor (U-turn) and
 * Grimmsnarl's Prankster by Frisk (its Parting Shot must come after Arcanine's turn); every side 0 Pokemon is slower than
 * Arcanine. Three cases, one per pivot kind, each over the seeds 1..16:
 *   6. pivot_uturn: Scizor's U-turn into Milotic;
 *   7. pivot_parting_shot: Grimmsnarl's Parting Shot into Milotic;
 *   8. pivot_emergency_exit: Grimmsnarl's Spirit Break into its ally Golisopod (Emergency Exit) at half its HP + 1.
 * At the pause: the bit stands on Arcanine's position; the codec round trip (encode, create_decoded, equal, encode again) keeps
 * it; the bit is hidden: the observation, its extension, the request and the factored domain of both players are byte-equal
 * with and without it (so the observation digest, built from these and the public lines, cannot see it). The decoded battle
 * then resumes with the first offered switch: the residual ends the lock with the fatigue confusion. The same battle with
 * the bit cleared resumes WITHOUT it (the bit carries the fact; a codec that dropped it would lose the confusion).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/extended_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/knowledge.h"
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

/* ---- the PIVOT pause (scenarios 6-8) ---- */

enum { PIVOT_UTURN = 0, PIVOT_PARTING_SHOT = 1, PIVOT_EMERGENCY_EXIT = 2 };

typedef struct pivot_case {
    const char *name;
    uint32_t kind;
} pivot_case;

/* Team B (side 0) for the pivots: Politoed -> Scizor @ no item, Technician, Adamant, 32 HP / 32 Atk, U-turn, Bug Bite, Swords
 * Dance, Bullet Punch (fz_6_175's Scizor without its stone); Grimmsnarl's ability Frisk (no Prankster priority). */
static uint32_t g_scizor, g_golisopod, g_grimmsnarl, g_farigiraf, g_archaludon;

static bool make_pivot_setup(df_test *t, duoforge_battle_setup *s)
{
    if (!make_setup(t, s)) {
        return false;
    }
    g_scizor = find_species(&s->sides[0], DFI_FORME_POLITOED);
    g_golisopod = find_species(&s->sides[0], DFI_FORME_GOLISOPOD);
    g_grimmsnarl = find_species(&s->sides[0], DFI_FORME_GRIMMSNARL);
    g_farigiraf = find_species(&s->sides[0], DFI_FORME_FARIGIRAF);
    g_archaludon = find_species(&s->sides[0], DFI_FORME_ARCHALUDON);
    if (!DF_CHECK(t, g_scizor != UINT32_MAX && g_golisopod != UINT32_MAX && g_grimmsnarl != UINT32_MAX &&
                         g_farigiraf != UINT32_MAX && g_archaludon != UINT32_MAX)) {
        return false;
    }
    duoforge_member_setup *z = &s->sides[0].members[g_scizor];
    memset(z, 0, sizeof *z);
    z->species_id = DFI_FORME_SCIZOR;
    z->gender = DUOFORGE_GENDER_MALE;
    z->nature = DFI_NATURE_ADAMANT;
    z->stat_points[0] = 32u;
    z->stat_points[1] = 32u;
    z->ability = 1u + DFI_ABILITY_TECHNICIAN;
    z->item = 0u;
    z->move_count = 4u;
    z->moves[0].move_id = DFI_MOVE_UTURN;
    z->moves[1].move_id = DFI_MOVE_BUGBITE;
    z->moves[2].move_id = DFI_MOVE_SWORDSDANCE;
    z->moves[3].move_id = DFI_MOVE_BULLETPUNCH;
    s->sides[0].members[g_grimmsnarl].ability = 1u + DFI_ABILITY_FRISK;
    return true;
}

/* The pivot battle of a case at its first TURN boundary: side 0 leads the pivot user and its partner, Farigiraf and Archaludon
 * wait on the bench; side 1 leads Arcanine and Milotic. */
static duoforge_battle *pivot_battle(df_test *t, const duoforge_context *ctx, const pivot_case *pc)
{
    duoforge_battle_setup s;
    if (!make_pivot_setup(t, &s)) {
        return NULL;
    }
    duoforge_battle *b = df_make_battle(ctx, &s);
    if (!DF_CHECK(t, b != NULL)) {
        return NULL;
    }
    const uint32_t lead0 = pc->kind == PIVOT_UTURN ? g_scizor : pc->kind == PIVOT_PARTING_SHOT ? g_grimmsnarl : g_golisopod;
    const uint32_t lead1 = pc->kind == PIVOT_PARTING_SHOT ? g_scizor : g_grimmsnarl;
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    const uint32_t picks[2][4] = {{lead0, lead1, g_farigiraf, g_archaludon},
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
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].occupant, lead0);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].occupant, g_r.arcanine);
    return b;
}

/* The turn: side 0's pivot (slot 0) and its partner's move (slot 1); Arcanine's locked move; Milotic's Hypnosis on Arcanine. */
static void pivot_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const pivot_case *pc)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    duoforge_side_choice *c0 = &bd->responses[0];
    c0->epoch = b->request_epoch;
    c0->side = 0u;
    c0->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c0->slots[0].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c0->slots[1].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    if (pc->kind == PIVOT_UTURN) {
        c0->slots[0].move_slot = 0u; /* Scizor: U-turn into Milotic */
        c0->slots[0].target = (uint8_t)PARTNER;
        c0->slots[1].move_slot = 1u; /* Grimmsnarl: Reflect */
        c0->slots[1].target = (uint8_t)DUOFORGE_TARGET_NONE;
    } else if (pc->kind == PIVOT_PARTING_SHOT) {
        c0->slots[0].move_slot = 3u; /* Grimmsnarl: Parting Shot into Milotic */
        c0->slots[0].target = (uint8_t)PARTNER;
        c0->slots[1].move_slot = 2u; /* Scizor: Swords Dance */
        c0->slots[1].target = (uint8_t)DUOFORGE_TARGET_NONE;
    } else {
        c0->slots[0].move_slot = 2u; /* Golisopod: Drill Run into Milotic */
        c0->slots[0].target = (uint8_t)PARTNER;
        c0->slots[1].move_slot = 0u; /* Grimmsnarl: Spirit Break into its ally Golisopod */
        c0->slots[1].target = 0u;
    }
    duoforge_side_choice *c1 = &bd->responses[1];
    c1->epoch = b->request_epoch;
    c1->side = 1u;
    c1->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c1->slots[0].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c1->slots[0].move_slot = 0u;
    c1->slots[0].target = (uint8_t)DUOFORGE_TARGET_NONE;
    c1->slots[1].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c1->slots[1].move_slot = (uint8_t)g_r.hypnosis;
    c1->slots[1].target = (uint8_t)HOLDER;
}

/* Every byte a player's model-facing queries give: the observation, its POOL extension, the request and the factored domain. */
static void same_views(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *c)
{
    for (uint32_t p = 0u; p < 2u; ++p) {
        static duoforge_observation oa, oc;
        static duoforge_observation_ext ea, ec;
        static duoforge_factored_domain fa, fc;
        duoforge_request ra, rc;
        memset(&oa, 0, sizeof oa);
        memset(&oc, 0, sizeof oc);
        memset(&ea, 0, sizeof ea);
        memset(&ec, 0, sizeof ec);
        memset(&ra, 0, sizeof ra);
        memset(&rc, 0, sizeof rc);
        memset(&fa, 0, sizeof fa);
        memset(&fc, 0, sizeof fc);
        DF_CHECK(t, duoforge_battle_observe(ctx, a, p, &oa) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe(ctx, c, p, &oc) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, a, p, &ea) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, c, p, &ec) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_request(ctx, a, p, &ra) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_request(ctx, c, p, &rc) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, a, p, &fa) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, c, p, &fc) == DUOFORGE_OK);
        DF_CHECK(t, memcmp(&oa, &oc, sizeof oa) == 0);
        DF_CHECK(t, memcmp(&ea, &ec, sizeof ea) == 0);
        DF_CHECK(t, memcmp(&ra, &rc, sizeof ra) == 0);
        DF_CHECK(t, memcmp(&fa, &fc, sizeof fa) == 0);
    }
}

/* Answers the PIVOT request with each requested player's first candidate (a switch to a bench Pokemon) and runs the rest of the
 * turn; returns the number of CONFUSION_START lines of the holder that the players saw (both must agree), or UINT32_MAX. */
static uint32_t resume(df_test *t, const duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    for (uint32_t p = 0u; p < 2u; ++p) {
        duoforge_request rq;
        if (!DF_CHECK(t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK)) {
            return UINT32_MAX;
        }
        if (rq.requested == 0u) {
            continue;
        }
        static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
        uint32_t n = 0u;
        if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK && n != 0u)) {
            return UINT32_MAX;
        }
        bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
        bd.responses[p] = cands[0];
    }
    duoforge_event_buffer buf[2] = {{g_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {g_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
    duoforge_step_result res;
    const duoforge_status st = duoforge_battle_step_events(ctx, b, &bd, &res, buf);
    if (!DF_CHECK(t, st == DUOFORGE_OK)) {
        fprintf(stderr, "  resume: status %d\n", (int)st);
        return UINT32_MAX;
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    DF_CHECK(t, b->boundary_kind == DUOFORGE_BOUNDARY_TURN || b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT);
    const uint32_t c0 = count_events(0u, buf[0].count, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER);
    const uint32_t c1 = count_events(1u, buf[1].count, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER);
    DF_CHECK_EQ_U64(t, c0, c1);
    return c0;
}

static void run_pivot(df_test *t, const duoforge_context *ctx, const pivot_case *pc)
{
    const unsigned long failed_before = t->failures;
    duoforge_battle *base = pivot_battle(t, ctx, pc);
    if (base == NULL) {
        return;
    }
    static const scenario fatigue = {"pivot", 1u, true, true, true, 0u, true, true};
    for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
        duoforge_battle *y = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
            break;
        }
        DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
        arrange(y, &fatigue);
        if (pc->kind == PIVOT_EMERGENCY_EXIT) {
            dfi_member *g = &y->sides[0].members[g_golisopod];
            g->hp = (uint16_t)(g->hp_max / 2u + 1u); /* Emergency Exit at the next hit that does not knock it out */
            dfi_knowledge *k = &y->sides[1].knowledge[g_golisopod]; /* what the foe was shown of it */
            dfi_hp_display(g->hp, g->hp_max, &k->hp_percent, &k->hp_flag);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
        duoforge_decision_bundle bd;
        pivot_bundle(&bd, y, pc);
        duoforge_event_buffer buf[2] = {{g_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {g_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
        duoforge_step_result res;
        const duoforge_status st = duoforge_battle_step_events(ctx, y, &bd, &res, buf);
        if (!DF_CHECK(t, st == DUOFORGE_OK)) {
            fprintf(stderr, "  %s seed %u: status %d\n", pc->name, (unsigned)seed, (int)st);
            duoforge_battle_destroy(y);
            continue;
        }
        /* the pause: Arcanine slept through its turn (cant slp), the lock stands with its unused bit, nothing confused yet */
        DF_CHECK_EQ_U64(t, y->boundary_kind, DUOFORGE_BOUNDARY_PIVOT);
        DF_CHECK(t, find_event(0u, buf[0].count, DUOFORGE_EVENT_CANT, (uint8_t)HOLDER, 0u) != UINT32_MAX);
        DF_CHECK_EQ_U64(t, count_events(0u, buf[0].count, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER), 0u);
        DF_CHECK_EQ_U64(t, y->sides[1].members[g_r.arcanine].status, DFI_STATUS_SLP);
        DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[0].lock_turns, 1u);
        DF_CHECK(t, (y->tail.sides[1].positions[0].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) != 0u);
        DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
        /* the codec round trip keeps the bit */
        static uint8_t bytes[4096], again[4096];
        size_t size = 0u, size2 = 0u;
        duoforge_battle *dec = NULL;
        bool equal = false;
        DF_CHECK(t, duoforge_battle_encode(ctx, y, bytes, sizeof bytes, &size) == DUOFORGE_OK);
        if (!DF_CHECK(t, duoforge_battle_create_decoded(ctx, bytes, size, &dec) == DUOFORGE_OK && dec != NULL)) {
            duoforge_battle_destroy(y);
            continue;
        }
        DF_CHECK(t, duoforge_battle_equal(ctx, y, dec, &equal) == DUOFORGE_OK && equal);
        DF_CHECK(t, duoforge_battle_encode(ctx, dec, again, sizeof again, &size2) == DUOFORGE_OK && size2 == size &&
                        memcmp(bytes, again, size) == 0);
        DF_CHECK(t, (dec->tail.sides[1].positions[0].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) != 0u);
        /* the bit is hidden: every model-facing byte of both players is the same without it */
        duoforge_battle *cleared = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, dec, &cleared) == DUOFORGE_OK && cleared != NULL);
        if (cleared != NULL) {
            uint8_t *bits = &cleared->tail.sides[1].positions[0].single_turn;
            *bits = (uint8_t)(*bits & ~DFI_SINGLE_TURN_LOCK_UNUSED);
            DF_CHECK(t, duoforge_battle_check(ctx, cleared) == DUOFORGE_OK);
            same_views(t, ctx, dec, cleared);
        }
        /* the bit's use is behind it: a queued move of the marked position is a broken state (the same record is valid without
         * the bit) */
        {
            duoforge_battle *q = NULL;
            DF_CHECK(t, duoforge_battle_clone(ctx, dec, &q) == DUOFORGE_OK && q != NULL);
            if (q != NULL && DF_CHECK(t, q->queue_len < DFI_QUEUE_CAPACITY)) {
                for (uint32_t k = q->queue_len; k > 0u; --k) {
                    q->queue[k] = q->queue[k - 1u];
                }
                dfi_queue_record mv;
                memset(&mv, 0, sizeof mv);
                mv.activation_id = q->sides[1].positions[0].activation_id;
                mv.kind = (uint8_t)DFI_Q_MOVE;
                mv.side = 1u;
                mv.slot = 0u;
                mv.move_slot = 0u;
                mv.target = (uint8_t)DUOFORGE_TARGET_NONE;
                q->queue[0] = mv;
                q->queue_len = (uint8_t)(q->queue_len + 1u);
                dfi_invariant inv = DFI_INV_NONE;
                DF_CHECK(t, dfi_state_check(ctx, q, &inv) == DUOFORGE_E_INVARIANT);
                DF_CHECK_EQ_U64(t, inv, DFI_INV_TAIL_POSITION);
                uint8_t *qbits = &q->tail.sides[1].positions[0].single_turn;
                *qbits = (uint8_t)(*qbits & ~DFI_SINGLE_TURN_LOCK_UNUSED);
                DF_CHECK(t, dfi_state_check(ctx, q, NULL) == DUOFORGE_OK);
            }
            duoforge_battle_destroy(q);
        }
        /* the bit follows its Pokemon on a swap of the two positions (Ally Switch moves the tail position whole) */
        {
            duoforge_battle *w = NULL;
            DF_CHECK(t, duoforge_battle_clone(ctx, dec, &w) == DUOFORGE_OK && w != NULL);
            if (w != NULL) {
                dfi_swap_position_state(w, 1u, 0u, 1u);
                DF_CHECK_EQ_U64(t, w->tail.sides[1].positions[0].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED, 0u);
                DF_CHECK(t, (w->tail.sides[1].positions[1].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) != 0u);
                DF_CHECK_EQ_U64(t, w->tail.sides[1].positions[1].lock_turns, 1u);
            }
            duoforge_battle_destroy(w);
        }
        /* cured after its `cant` (no marked move or ability cures within the turn yet, so white-box at the pause): the bit is
         * read, not the status, and the countdown still ends the lock with the fatigue (the one behaviour change against main,
         * which kept an awake holder's lock) */
        {
            duoforge_battle *cu = NULL;
            DF_CHECK(t, duoforge_battle_clone(ctx, dec, &cu) == DUOFORGE_OK && cu != NULL);
            if (cu != NULL) {
                dfi_member *am = &cu->sides[1].members[g_r.arcanine];
                am->status = 0u;
                am->status_counter = 0u;
                cu->tail.sides[1].sleep_cant[g_r.arcanine] = 0u;
                DF_CHECK(t, duoforge_battle_check(ctx, cu) == DUOFORGE_OK);
                DF_CHECK_EQ_U64(t, resume(t, ctx, cu), 1u);
                DF_CHECK_EQ_U64(t, cu->tail.sides[1].positions[0].lock_turns, 0u);
                DF_CHECK_EQ_U64(t, cu->sides[1].positions[0].locked_move, 0u);
                DF_CHECK(t, cu->sides[1].positions[0].confusion_turns >= 2u && cu->sides[1].positions[0].confusion_turns <= 5u);
            }
            duoforge_battle_destroy(cu);
        }
        /* the decoded battle resumes: the residual ends the lock with the fatigue confusion (count 1) */
        DF_CHECK_EQ_U64(t, resume(t, ctx, dec), 1u);
        DF_CHECK_EQ_U64(t, dec->tail.sides[1].positions[0].lock_turns, 0u);
        DF_CHECK_EQ_U64(t, dec->sides[1].positions[0].locked_move, 0u);
        DF_CHECK_EQ_U64(t, dec->tail.sides[1].positions[0].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED, 0u);
        DF_CHECK(t, dec->sides[1].positions[0].confusion_turns >= 2u && dec->sides[1].positions[0].confusion_turns <= 5u);
        /* without the bit the same pause resumes into the silent removal: the bit is what carries the fact */
        if (cleared != NULL) {
            DF_CHECK_EQ_U64(t, resume(t, ctx, cleared), 0u);
            DF_CHECK_EQ_U64(t, cleared->tail.sides[1].positions[0].lock_turns, 0u);
            DF_CHECK_EQ_U64(t, cleared->sides[1].positions[0].confusion_turns, 0u);
        }
        duoforge_battle_destroy(cleared);
        duoforge_battle_destroy(dec);
        duoforge_battle_destroy(y);
    }
    duoforge_battle_destroy(base);
    if (t->failures != failed_before) {
        fprintf(stderr, "  scenario %s: %lu failed checks\n", pc->name, t->failures - failed_before);
    } else {
        fprintf(stderr, "  scenario %s: ok\n", pc->name);
    }
}

/* ---- phase 6 of the residual with two lock holders (scenarios 9-11) ----
 * Side 1 leads two lock holders: position 2 (slot 0) and position 3 (slot 1), both Jolly 32 Atk / 32 Spe, no item, Outrage and
 * Protect. Side 0 leads Politoed (Protect replaced by Hypnosis; Speed and accuracy +6: it puts position 2 to sleep before it moves)
 * and Farigiraf (Psychic into its ally Politoed, last); Grimmsnarl and Archaludon wait on the bench. No side 0 lead is a Fairy, so the restarted
 * holder's Outrage always hits (a Fairy's immunity would leave its lock unrestarted).
 *   9. phase6_restarted_faint_point: Arcanine (2, count 1, put to sleep: marked) and a faster Garchomp (3, count 2: its use restarts
 *      the lock). Both side 0 leads have Perish 1 and side 0's bench has fainted: the residual's Perish ends queue their faints
 *      (an end is no faint point), and the first faint point is Garchomp's lockedmove onResidual in phase 6 (sim/battle.ts:565-566).
 *      The battle ends there, side 1 wins, and Arcanine's countdown never runs: no fatigue line, its lock and its bit stand at
 *      TERMINAL (where the invariant allows the bit; the codec round trip keeps it).
 *  10. phase6_equal_speed_refused: as 9 with Kangaskhan (2, marked) and Annihilape (3, restarted), whose Speeds are equal (both
 *      base 90): which of the two handlers runs first is the shuffle, so whether the fatigue came before the battle's end is not
 *      known: E_UNSUPPORTED, the battle unchanged.
 *  11. phase6_both_marked: Arcanine and Garchomp, both asleep at the start (white-box, as duoforge.moves.outrage_lock) with count 1, no
 *      Perish: both `cant`, both marked, both end with the fatigue in the residual, both bits cleared. */
static uint32_t g_p6_holder0, g_p6_holder1, g_p6_politoed, g_p6_farigiraf, g_p6_bench0, g_p6_bench1;

static void p6_member(duoforge_member_setup *m, uint32_t species, uint32_t gender, uint32_t ability)
{
    memset(m, 0, sizeof *m);
    m->species_id = species;
    m->gender = gender;
    m->nature = DFI_NATURE_JOLLY;
    m->stat_points[1] = 32u;
    m->stat_points[5] = 32u;
    m->ability = 1u + ability;
    m->item = 0u;
    m->move_count = 2u;
    m->moves[0].move_id = DFI_MOVE_OUTRAGE;
    m->moves[1].move_id = DFI_MOVE_PROTECT;
}

static duoforge_battle *p6_battle(df_test *t, const duoforge_context *ctx, uint32_t sp0, uint32_t g0, uint32_t ab0, uint32_t sp1,
                                  uint32_t g1, uint32_t ab1)
{
    duoforge_battle_setup s;
    if (!DF_CHECK(t, duoforge_reference_setup(1u, &s) == DUOFORGE_OK)) {
        return NULL;
    }
    g_p6_holder0 = find_species(&s.sides[1], DFI_FORME_CERULEDGE);
    g_p6_holder1 = find_species(&s.sides[1], DFI_FORME_MILOTIC);
    g_p6_politoed = find_species(&s.sides[0], DFI_FORME_POLITOED);
    g_p6_farigiraf = find_species(&s.sides[0], DFI_FORME_FARIGIRAF);
    g_p6_bench0 = find_species(&s.sides[0], DFI_FORME_GRIMMSNARL);
    g_p6_bench1 = find_species(&s.sides[0], DFI_FORME_ARCHALUDON);
    if (!DF_CHECK(t, g_p6_holder0 != UINT32_MAX && g_p6_holder1 != UINT32_MAX && g_p6_politoed != UINT32_MAX &&
                         g_p6_farigiraf != UINT32_MAX && g_p6_bench0 != UINT32_MAX && g_p6_bench1 != UINT32_MAX)) {
        return NULL;
    }
    p6_member(&s.sides[1].members[g_p6_holder0], sp0, g0, ab0);
    p6_member(&s.sides[1].members[g_p6_holder1], sp1, g1, ab1);
    duoforge_member_setup *pol = &s.sides[0].members[g_p6_politoed];
    const uint32_t protect_slot = find_move(pol, DFI_MOVE_PROTECT);
    if (!DF_CHECK(t, protect_slot != UINT32_MAX)) {
        return NULL;
    }
    pol->moves[protect_slot].move_id = DFI_MOVE_HYPNOSIS;
    duoforge_battle *b = df_make_battle(ctx, &s);
    if (!DF_CHECK(t, b != NULL)) {
        return NULL;
    }
    uint32_t others[2] = {UINT32_MAX, UINT32_MAX};
    for (uint32_t m = 0u, k = 0u; m < s.sides[1].member_count && k < 2u; ++m) {
        if (m != g_p6_holder0 && m != g_p6_holder1) {
            others[k++] = m;
        }
    }
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    const uint32_t picks[2][4] = {{g_p6_politoed, g_p6_farigiraf, g_p6_bench0, g_p6_bench1},
                                  {g_p6_holder0, g_p6_holder1, others[0], others[1]}};
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
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].occupant, g_p6_holder0);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[1].occupant, g_p6_holder1);
    return b;
}

/* The locks (Outrage in slot 0, used last), Politoed's +6 Speed and accuracy; with `perish` side 0's leads at Perish 1 and its bench
 * fainted; with `both_asleep` both holders asleep (three turns). */
static void p6_arrange(duoforge_battle *y, uint32_t count0, uint32_t count1, bool perish, bool both_asleep)
{
    const uint32_t counts[2] = {count0, count1};
    for (uint32_t p = 0u; p < 2u; ++p) {
        y->tail.sides[1].positions[p].lock_turns = (uint8_t)counts[p];
        y->sides[1].positions[p].locked_move = 1u;
        y->tail.sides[1].positions[p].last_move = 1u;
    }
    y->sides[0].positions[0].stages[4] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
    y->sides[0].positions[0].stages[5] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
    if (perish) {
        y->tail.sides[0].positions[0].perish = 1u;
        y->tail.sides[0].positions[1].perish = 1u;
        y->sides[0].members[g_p6_bench0].hp = 0u;
        y->sides[0].members[g_p6_bench1].hp = 0u;
    }
    if (both_asleep) {
        for (uint32_t p = 0u; p < 2u; ++p) {
            dfi_member *h = &y->sides[1].members[y->sides[1].positions[p].occupant];
            h->status = (uint8_t)DFI_STATUS_SLP;
            h->status_counter = 3u;
        }
    }
}

static void p6_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    duoforge_side_choice *c0 = &bd->responses[0];
    c0->epoch = b->request_epoch;
    c0->side = 0u;
    c0->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    c0->slots[0].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c0->slots[0].move_slot = 3u; /* Politoed: Hypnosis (Protect's slot) into position 2 */
    c0->slots[0].target = (uint8_t)HOLDER;
    c0->slots[1].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    c0->slots[1].move_slot = 0u; /* Farigiraf: Psychic into its ally Politoed (it moves last; a hit on a holder could knock it out) */
    c0->slots[1].target = 0u;
    duoforge_side_choice *c1 = &bd->responses[1];
    c1->epoch = b->request_epoch;
    c1->side = 1u;
    c1->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    for (uint32_t k = 0u; k < 2u; ++k) {
        c1->slots[k].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
        c1->slots[k].move_slot = 0u;
        c1->slots[k].target = (uint8_t)DUOFORGE_TARGET_NONE;
    }
}

static void run_phase6(df_test *t, const duoforge_context *ctx)
{
    /* 9: the restarted holder's faint point ends the battle before the marked holder's countdown */
    {
        const unsigned long failed_before = t->failures;
        duoforge_battle *base = p6_battle(t, ctx, DFI_FORME_ARCANINE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE, DFI_FORME_GARCHOMP,
                                          DUOFORGE_GENDER_FEMALE, DFI_ABILITY_ROUGHSKIN);
        if (base != NULL) {
            DF_CHECK(t, base->sides[1].members[g_p6_holder1].stats[DFI_STAT_SPE - 1u] >
                            base->sides[1].members[g_p6_holder0].stats[DFI_STAT_SPE - 1u]); /* Garchomp is faster */
            for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
                duoforge_battle *y = NULL;
                if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
                    break;
                }
                DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
                p6_arrange(y, 1u, 2u, true, false);
                DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                p6_bundle(&bd, y);
                duoforge_event_buffer buf[2] = {{g_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {g_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
                duoforge_step_result res;
                const duoforge_status st = duoforge_battle_step_events(ctx, y, &bd, &res, buf);
                if (DF_CHECK(t, st == DUOFORGE_OK)) {
                    uint32_t result = 0u;
                    DF_CHECK_EQ_U64(t, y->boundary_kind, DUOFORGE_BOUNDARY_TERMINAL);
                    DF_CHECK(t, duoforge_battle_result(ctx, y, &result) == DUOFORGE_OK && result == DUOFORGE_RESULT_SIDE_1);
                    DF_CHECK(t, find_event(0u, buf[0].count, DUOFORGE_EVENT_CANT, (uint8_t)HOLDER, 0u) != UINT32_MAX);
                    DF_CHECK_EQ_U64(t, count_events(0u, buf[0].count, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER), 0u);
                    DF_CHECK_EQ_U64(t, count_events(1u, buf[1].count, DUOFORGE_EVENT_CONFUSION_START, (uint8_t)HOLDER), 0u);
                    DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[0].lock_turns, 1u);
                    DF_CHECK(t, (y->tail.sides[1].positions[0].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED) != 0u);
                    DF_CHECK_EQ_U64(t, y->sides[1].positions[0].confusion_turns, 0u);
                    DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[1].lock_turns, 1u); /* restarted: counted down at its use */
                    DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
                    /* the bit at TERMINAL survives the codec round trip */
                    static uint8_t tb[4096];
                    size_t tn = 0u;
                    duoforge_battle *td = NULL;
                    bool equal = false;
                    DF_CHECK(t, duoforge_battle_encode(ctx, y, tb, sizeof tb, &tn) == DUOFORGE_OK);
                    DF_CHECK(t, duoforge_battle_create_decoded(ctx, tb, tn, &td) == DUOFORGE_OK && td != NULL);
                    DF_CHECK(t, td != NULL && duoforge_battle_equal(ctx, y, td, &equal) == DUOFORGE_OK && equal);
                    duoforge_battle_destroy(td);
                } else {
                    fprintf(stderr, "  phase6_restarted_faint_point seed %u: status %d\n", (unsigned)seed, (int)st);
                }
                duoforge_battle_destroy(y);
            }
            duoforge_battle_destroy(base);
        }
        fprintf(stderr, "  scenario phase6_restarted_faint_point: %s\n", t->failures == failed_before ? "ok" : "FAILED");
    }
    /* 10: equal Speeds at the battle-ending faint point: refused */
    {
        const unsigned long failed_before = t->failures;
        duoforge_battle *base = p6_battle(t, ctx, DFI_FORME_KANGASKHAN, DUOFORGE_GENDER_FEMALE, DFI_ABILITY_INNERFOCUS,
                                          DFI_FORME_ANNIHILAPE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INNERFOCUS);
        if (base != NULL) {
            DF_CHECK_EQ_U64(t, base->sides[1].members[g_p6_holder0].stats[DFI_STAT_SPE - 1u],
                            base->sides[1].members[g_p6_holder1].stats[DFI_STAT_SPE - 1u]);
            for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
                duoforge_battle *y = NULL;
                if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
                    break;
                }
                DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
                p6_arrange(y, 1u, 2u, true, false);
                DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
                static uint8_t before[4096], after[4096];
                size_t nb = 0u, na = 0u;
                DF_CHECK(t, duoforge_battle_encode(ctx, y, before, sizeof before, &nb) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                p6_bundle(&bd, y);
                duoforge_step_result res;
                const duoforge_status st = duoforge_battle_step(ctx, y, &bd, &res);
                if (!DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED)) {
                    fprintf(stderr, "  phase6_equal_speed_refused seed %u: status %d\n", (unsigned)seed, (int)st);
                }
                DF_CHECK(t, duoforge_battle_encode(ctx, y, after, sizeof after, &na) == DUOFORGE_OK && na == nb &&
                                memcmp(before, after, nb) == 0); /* a refused step leaves the battle unchanged */
                duoforge_battle_destroy(y);
            }
            duoforge_battle_destroy(base);
        }
        fprintf(stderr, "  scenario phase6_equal_speed_refused: %s\n", t->failures == failed_before ? "ok" : "FAILED");
    }
    /* 11: both positions marked in one turn */
    {
        const unsigned long failed_before = t->failures;
        duoforge_battle *base = p6_battle(t, ctx, DFI_FORME_ARCANINE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE, DFI_FORME_GARCHOMP,
                                          DUOFORGE_GENDER_FEMALE, DFI_ABILITY_ROUGHSKIN);
        if (base != NULL) {
            for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
                duoforge_battle *y = NULL;
                if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
                    break;
                }
                DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
                p6_arrange(y, 1u, 1u, false, true);
                DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                p6_bundle(&bd, y);
                duoforge_event_buffer buf[2] = {{g_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {g_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
                duoforge_step_result res;
                const duoforge_status st = duoforge_battle_step_events(ctx, y, &bd, &res, buf);
                if (DF_CHECK(t, st == DUOFORGE_OK)) {
                    DF_CHECK_EQ_U64(t, y->boundary_kind, DUOFORGE_BOUNDARY_TURN);
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        const uint8_t flat = (uint8_t)(HOLDER + p);
                        DF_CHECK(t, find_event(0u, buf[0].count, DUOFORGE_EVENT_CANT, flat, 0u) != UINT32_MAX);
                        DF_CHECK_EQ_U64(t, count_events(0u, buf[0].count, DUOFORGE_EVENT_CONFUSION_START, flat), 1u);
                        DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[p].lock_turns, 0u);
                        DF_CHECK_EQ_U64(t, y->tail.sides[1].positions[p].single_turn & DFI_SINGLE_TURN_LOCK_UNUSED, 0u);
                        DF_CHECK(t, y->sides[1].positions[p].confusion_turns >= 2u && y->sides[1].positions[p].confusion_turns <= 5u);
                    }
                } else {
                    fprintf(stderr, "  phase6_both_marked seed %u: status %d\n", (unsigned)seed, (int)st);
                }
                duoforge_battle_destroy(y);
            }
            duoforge_battle_destroy(base);
        }
        fprintf(stderr, "  scenario phase6_both_marked: %s\n", t->failures == failed_before ? "ok" : "FAILED");
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.lockedmove_sleep");
    duoforge_context *kp = df_make_context(&df_config_pool);
    static const pivot_case pivots[] = {
        {"pivot_uturn", PIVOT_UTURN},
        {"pivot_parting_shot", PIVOT_PARTING_SHOT},
        {"pivot_emergency_exit", PIVOT_EMERGENCY_EXIT},
    };
    for (size_t i = 0u; i < sizeof pivots / sizeof pivots[0]; ++i) {
        run_pivot(&t, kp, &pivots[i]);
    }
    run_phase6(&t, kp);
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
