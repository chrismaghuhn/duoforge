/*
 * duoforge.flow.residual_noorder_tie (white-box): the refusals of the residual's no-order phase around the equal-Speed tie
 * of issues 630 and 633 (docs/mechanics/flow/5ga-residual-noorder-tie.md). Each scenario checks that the refused step
 * returns E_UNSUPPORTED and leaves the battle byte-equal, and each refusal has a mutant that this test kills (the 5ga note
 * lists them). The battle: the reference teams B (side 0) and A (side 1); side 0 leads Politoed (Protect replaced by
 * Hypnosis, Speed and accuracy +6 where it must move first) and a second Pokemon; side 1 leads two Pokemon set here. Every
 * Pokemon set here is Jolly with 0 Atk and 32 Spe and holds no item, so Kangaskhan and Annihilape (both base 90) have one
 * Speed, Garchomp (102) is faster and the reference Milotic (Calm, 0 Spe) slower. Every scenario runs the seeds 1..16.
 *
 *   1. undrawn_equal_speed_refused: Kangaskhan (2, lock count 2: its Outrage restarts the lock) and Annihilape (3, Bulk Up,
 *      with the stall counter of a Protect of the last turn, which ends now) at one Speed; side 0's leads at Perish 1, its
 *      bench fainted. The no-order group of that Speed holds one callback (the lock) and the stall counter: not drawn (the
 *      conversion drops its draw). Kangaskhan's lock is the first faint point and ends the battle while Annihilape stands:
 *      whether its stall counter ran first is unknown (it shows in its stall counter). Refused (the old
 *      scenario phase6_equal_speed_refused of duoforge.moves.lockedmove_sleep, which is played since 5ga).
 *   2. pair_beside_lock_refused: as 1 with Tailwind on side 0 (3 turns): its handler at order 26 does not end, so its faint
 *      point ends the battle before phase 6. Annihilape's lone Protect / stall pair would draw at the battle end
 *      (dfi_residual_pair_draws), but the group of its Speed also holds Kangaskhan's lock: a bigger group, whose draw the
 *      conversion drops (lock_counter_tie). Refused. Before 5ga the engine drew the pair: a silent divergence.
 *   3. pair_before_drawn_group_refused: Kangaskhan on both sides with locks (side 0's at count 2, side 1's put to sleep by
 *      Politoed), Garchomp (faster) protects; side 0's Kangaskhan and Politoed are burned at 1 HP, side 0's bench fainted.
 *      The two locks are drawn in phase 2; the burns end the battle in phase 3; Garchomp's pair draw is then due, but the
 *      pin draws it in its sort before the slower lock group's draw: refused. When side 0's Kangaskhan's Outrage hit the
 *      protecting Garchomp its lock is not restarted and ends at once: no lock group, the pair draws and the step plays.
 *   4. pair_after_handler_draw_refused: Kangaskhan (lock count 1, put to sleep by Politoed: its lock ends in the residual
 *      with the fatigue, a CONFUSION_TURNS draw) and the slower Milotic (Protect); side 0's leads at Perish 1, bench
 *      fainted. Milotic's stall counter is the faint point that ends the battle: its pair draw would come after the
 *      fatigue's draw, the pin's before it. Refused.
 *   5. drawn_counter_pending_faint_refused: Kangaskhan on both sides with locks at count 2 and Annihilape (Protect) at their
 *      Speed: one drawn no-order group of two locks and Annihilape's two counters. Politoed (Perish 1) has a queued faint,
 *      side 0's bench stands. When Annihilape's counters come first in the drawn order, their faint point shows the faint,
 *      and which of its two counters keeps is not known: refused. When a lock comes first, its faint point shows it and
 *      the step plays. Both occur over the seeds.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/closure_tables.h"
#include "data/formats/reg-mc/extended_tables.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define SEEDS 16u
#define POSITIONS 4u

/* The members of the reference setup that the scenarios use (indices into each side's roster). */
static uint32_t g_politoed, g_farigiraf, g_bench0, g_bench1, g_y0, g_y1;

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

/* A Pokemon set here: Jolly, 0 Atk, 32 Spe, no item; Outrage in slot 0, Protect in slot 1, `move3` (if any) in slot 2. */
static void member(duoforge_member_setup *m, uint32_t species, uint32_t gender, uint32_t ability, uint32_t move3)
{
    memset(m, 0, sizeof *m);
    m->species_id = species;
    m->gender = gender;
    m->nature = DFI_NATURE_JOLLY;
    m->stat_points[5] = 32u;
    m->ability = 1u + ability;
    m->move_count = move3 != 0u ? 3u : 2u;
    m->moves[0].move_id = DFI_MOVE_OUTRAGE;
    m->moves[1].move_id = DFI_MOVE_PROTECT;
    m->moves[2].move_id = move3;
}

typedef struct lead {
    uint32_t species; /* 0: keep the reference member */
    uint32_t gender;
    uint32_t ability;
    uint32_t move3; /* a third move, 0 for none */
} lead;

/* The battle after team preview: side 0 leads Politoed and (x1 or Farigiraf), side 1 leads y0 and y1 (the members that
 * were Ceruledge and Milotic; a lead with species 0 keeps the reference member, Milotic with Protect in Coil's slot). */
static duoforge_battle *make_battle(df_test *t, const duoforge_context *ctx, lead x1, lead y0, lead y1)
{
    duoforge_battle_setup s;
    if (!DF_CHECK(t, duoforge_reference_setup(1u, &s) == DUOFORGE_OK)) {
        return NULL;
    }
    g_politoed = find_species(&s.sides[0], DFI_FORME_POLITOED);
    g_farigiraf = find_species(&s.sides[0], DFI_FORME_FARIGIRAF);
    g_bench0 = find_species(&s.sides[0], DFI_FORME_GRIMMSNARL);
    g_bench1 = find_species(&s.sides[0], DFI_FORME_ARCHALUDON);
    g_y0 = find_species(&s.sides[1], DFI_FORME_CERULEDGE);
    g_y1 = find_species(&s.sides[1], DFI_FORME_MILOTIC);
    if (!DF_CHECK(t, g_politoed != UINT32_MAX && g_farigiraf != UINT32_MAX && g_bench0 != UINT32_MAX && g_bench1 != UINT32_MAX &&
                         g_y0 != UINT32_MAX && g_y1 != UINT32_MAX)) {
        return NULL;
    }
    duoforge_member_setup *pol = &s.sides[0].members[g_politoed];
    const uint32_t protect_slot = find_move(pol, DFI_MOVE_PROTECT);
    if (!DF_CHECK(t, protect_slot != UINT32_MAX)) {
        return NULL;
    }
    pol->moves[protect_slot].move_id = DFI_MOVE_HYPNOSIS;
    if (x1.species != 0u) {
        member(&s.sides[0].members[g_farigiraf], x1.species, x1.gender, x1.ability, x1.move3);
    }
    if (y0.species != 0u) {
        member(&s.sides[1].members[g_y0], y0.species, y0.gender, y0.ability, y0.move3);
    }
    if (y1.species != 0u) {
        member(&s.sides[1].members[g_y1], y1.species, y1.gender, y1.ability, y1.move3);
    } else {
        duoforge_member_setup *mil = &s.sides[1].members[g_y1];
        const uint32_t coil = find_move(mil, DFI_MOVE_COIL);
        if (!DF_CHECK(t, coil != UINT32_MAX)) {
            return NULL;
        }
        mil->moves[coil].move_id = DFI_MOVE_PROTECT;
    }
    duoforge_battle *b = df_make_battle(ctx, &s);
    if (!DF_CHECK(t, b != NULL)) {
        return NULL;
    }
    uint32_t others[2] = {UINT32_MAX, UINT32_MAX};
    for (uint32_t m = 0u, k = 0u; m < s.sides[1].member_count && k < 2u; ++m) {
        if (m != g_y0 && m != g_y1) {
            others[k++] = m;
        }
    }
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    const uint32_t picks[2][4] = {{g_politoed, g_farigiraf, g_bench0, g_bench1}, {g_y0, g_y1, others[0], others[1]}};
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
    return b;
}

/* What a scenario sets at the turn boundary and chooses. */
typedef struct scenario {
    const char *name;
    lead x1, y0, y1;
    uint8_t lock_turns[POSITIONS]; /* 0: no lock */
    uint8_t perish[POSITIONS];
    bool burned_at_1[POSITIONS];
    bool bench_fainted;
    bool politoed_first;    /* Speed and accuracy +6 */
    uint8_t tailwind0;      /* side 0's Tailwind turns */
    uint8_t slot[POSITIONS];   /* the move slot each position uses */
    uint8_t target[POSITIONS]; /* its target (a flat position), DUOFORGE_TARGET_NONE for none */
    uint8_t old_stall[POSITIONS]; /* a stall counter from the last turn's Protect (level 1, its last turn) */
    bool may_play;          /* some seeds play the step (the refusal depends on a draw) */
} scenario;

static void arrange(duoforge_battle *y, const scenario *sc)
{
    for (uint32_t flat = 0u; flat < POSITIONS; ++flat) {
        dfi_tail_pos *tp = &y->tail.sides[flat / 2u].positions[flat % 2u];
        if (sc->lock_turns[flat] != 0u) {
            tp->lock_turns = sc->lock_turns[flat];
            y->sides[flat / 2u].positions[flat % 2u].locked_move = 1u;
            tp->last_move = 1u;
        }
        tp->perish = sc->perish[flat];
        if (sc->old_stall[flat] != 0u) {
            y->sides[flat / 2u].positions[flat % 2u].stall_level = 1u;
            y->sides[flat / 2u].positions[flat % 2u].stall_turns = 1u;
        }
        if (sc->burned_at_1[flat]) {
            dfi_member *m = &y->sides[flat / 2u].members[y->sides[flat / 2u].positions[flat % 2u].occupant];
            m->status = (uint8_t)DFI_STATUS_BRN;
            m->hp = 1u;
            df_knowledge_see_hp(y, flat / 2u, y->sides[flat / 2u].positions[flat % 2u].occupant); /* the foe saw it */
        }
    }
    if (sc->bench_fainted) {
        y->sides[0].members[g_bench0].hp = 0u;
        y->sides[0].members[g_bench1].hp = 0u;
    }
    if (sc->politoed_first) {
        y->sides[0].positions[0].stages[4] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
        y->sides[0].positions[0].stages[5] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
    }
    y->sides[0].tailwind_turns = sc->tailwind0;
}

static void bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const scenario *sc)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t k = 0u; k < 2u; ++k) {
            c->slots[k].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[k].move_slot = sc->slot[side * 2u + k];
            c->slots[k].target = sc->target[side * 2u + k];
        }
    }
}

static void run(df_test *t, const duoforge_context *ctx, const scenario *sc)
{
    const unsigned long failed_before = t->failures;
    uint32_t refused = 0u;
    uint32_t played = 0u;
    duoforge_battle *base = make_battle(t, ctx, sc->x1, sc->y0, sc->y1);
    if (base != NULL) {
        for (uint64_t seed = 1u; seed <= SEEDS; ++seed) {
            duoforge_battle *y = NULL;
            if (!DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
            arrange(y, sc);
            if (!DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK)) {
                dfi_invariant inv = DFI_INV_COUNT;
                (void)dfi_state_check(ctx, y, &inv);
                fprintf(stderr, "  %s: invariant %s\n", sc->name, dfi_invariant_name(inv));
                duoforge_battle_destroy(y);
                break;
            }
            static uint8_t before[4096], after[4096];
            size_t nb = 0u, na = 0u;
            DF_CHECK(t, duoforge_battle_encode(ctx, y, before, sizeof before, &nb) == DUOFORGE_OK);
            duoforge_decision_bundle bd;
            bundle(&bd, y, sc);
            duoforge_step_result res;
            const duoforge_status st = duoforge_battle_step(ctx, y, &bd, &res);
            if (st == DUOFORGE_E_UNSUPPORTED) {
                refused += 1u;
                DF_CHECK(t, duoforge_battle_encode(ctx, y, after, sizeof after, &na) == DUOFORGE_OK && na == nb &&
                                memcmp(before, after, nb) == 0); /* a refused step leaves the battle unchanged */
            } else if (DF_CHECK_EQ_U64(t, st, DUOFORGE_OK)) {
                played += 1u;
                DF_CHECK(t, duoforge_battle_check(ctx, y) == DUOFORGE_OK);
            }
            duoforge_battle_destroy(y);
        }
        duoforge_battle_destroy(base);
    }
    DF_CHECK(t, refused != 0u);
    DF_CHECK(t, sc->may_play ? played + refused == SEEDS : played == 0u);
    if (sc->may_play && !DF_CHECK(t, played != 0u)) {
        fprintf(stderr, "  %s: expected some seeds to play\n", sc->name);
    }
    fprintf(stderr, "  scenario %s (%u refused, %u played): %s\n", sc->name, (unsigned)refused, (unsigned)played,
            t->failures == failed_before ? "ok" : "FAILED");
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.flow.residual_noorder_tie");
    duoforge_context *kp = df_make_context(&df_config_pool);
    const lead keep = {0u, 0u, 0u, 0u};
    const lead kangaskhan = {DFI_FORME_KANGASKHAN, DUOFORGE_GENDER_FEMALE, DFI_ABILITY_INNERFOCUS, 0u};
    const lead annihilape = {DFI_FORME_ANNIHILAPE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INNERFOCUS, DFI_MOVE_BULKUP};
    const lead garchomp = {DFI_FORME_GARCHOMP, DUOFORGE_GENDER_FEMALE, DFI_ABILITY_ROUGHSKIN, 0u};
    const uint8_t none = (uint8_t)DUOFORGE_TARGET_NONE;
    /* Politoed's slots: 2 Ice Beam, 3 Hypnosis; Farigiraf's 0 Psychic; a Pokemon set here: 0 Outrage, 1 Protect (Annihilape: 2 Bulk Up); the
     * reference Milotic: 1 Protect (Coil's slot). */
    const scenario scenarios[] = {
        {"undrawn_equal_speed_refused", keep, kangaskhan, annihilape, {0u, 0u, 2u, 0u}, {1u, 1u, 0u, 0u}, {false}, true, true,
         0u, {3u, 0u, 0u, 2u}, {1u, 0u, none, none}, {0u, 0u, 0u, 1u}, false},
        {"pair_beside_lock_refused", keep, kangaskhan, annihilape, {0u, 0u, 2u, 0u}, {1u, 1u, 0u, 0u}, {false}, true, true, 3u,
         {3u, 0u, 0u, 1u}, {1u, 0u, none, none}, {0u}, false},
        {"pair_before_drawn_group_refused", kangaskhan, kangaskhan, garchomp, {0u, 2u, 1u, 0u}, {0u}, {true, true, false, false},
         true, true, 0u, {3u, 0u, 0u, 1u}, {2u, none, none, none}, {0u}, true},
        {"pair_after_handler_draw_refused", keep, kangaskhan, keep, {0u, 0u, 1u, 0u}, {1u, 1u, 0u, 0u}, {false}, true, true, 0u,
         {3u, 0u, 0u, 1u}, {2u, 0u, none, none}, {0u}, false},
        {"drawn_counter_pending_faint_refused", kangaskhan, kangaskhan, annihilape, {0u, 2u, 2u, 0u}, {1u, 0u, 0u, 0u}, {false},
         false, false, 0u, {2u, 0u, 0u, 1u}, {3u, none, none, none}, {0u}, true},
    };
    for (size_t i = 0u; i < sizeof scenarios / sizeof scenarios[0]; ++i) {
        run(&t, kp, &scenarios[i]);
    }
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
