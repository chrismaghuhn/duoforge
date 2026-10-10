/*
 * duoforge.state.pool_g56 (white-box): step G56 of the content expansion (decision 0015 item 5au), Outrage as a lockedmove.
 *
 * The recorded battles (g56_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data. What they do not
 * show is the refusal: a locked user whose move is stopped before its use (a flinch, a freeze, a full paralysis) keeps its lock
 * into the residual, and the lock's end there is not modelled, so the step is refused with E_UNSUPPORTED and changes nothing.
 * A White Herb holder whose stats are down at the lock's last use is refused likewise (the White Herb and the lock's confusion
 * would both print at the end of the use, and their order is not modelled). Each refusal is checked here with the step's state
 * before and after; the chance rolls (freeze, full paralysis) are tried over a range of seeds, and the same battle must be refused
 * for some seeds and carry on for the others, as the reference does.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/closure_tables.h"
#include "data/extended_tables.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/context_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "reference/conformance_pool.h"
#include "support/pool.h"

static uint32_t g_first; /* side 0's member that learns Outrage and leads at position 0 (the locked lead) */

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
        /* side 0 leads with the member that learns Outrage (g_first) and keeps the others in order */
        uint32_t k = 0u;
        if (side == 0u) {
            c->picks[k++] = (uint8_t)g_first;
        }
        for (uint32_t i = 0u; i < 6u && k < 4u; ++i) {
            if (side == 0u && i == g_first) {
                continue;
            }
            c->picks[k++] = (uint8_t)i;
        }
    }
}

/* Move slot 0 of both leads, as the lock forces it for the locked lead (its locked move is slot 0 + 1). */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    static const uint8_t plan[2][2][2] = {{{0u, 2u}, {0u, 3u}}, {{0u, 0u}, {0u, 1u}}}; /* move slot, target */
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = plan[side][slot][0];
            /* a locked slot is offered its move with no target (its request), and the move is Outrage: no target is chosen */
            const bool locked = b->tail.sides[side].positions[slot].lock_turns != 0u;
            c->slots[slot].target = locked ? (uint8_t)DUOFORGE_TARGET_NONE : plan[side][slot][1];
        }
    }
}

static uint32_t g_lead; /* the lead of side 0 that is locked: its position */

/* The recorded battle `name` (conformance_pool.h): its setup, as the conformance test builds it. */
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

/* A battle at its first TURN boundary: the team of g56_outrage_switch against the foe of the same record. */
static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx)
{
    /* The team of the recorded battle g56_outrage_switch (a legal POOL team: Garchomp, member 1, has Outrage in slot 0). Its
     * Garchomp leads at position 0, the locked lead (team_bundle picks it first). */
    const df_conf_battle *cb = find_conf("g56_outrage_switch");
    DF_CHECK(t, cb != NULL);
    duoforge_battle_setup s;
    setup_from(cb, &s);
    g_first = 1u;
    g_lead = 0u;
    DF_CHECK(t, s.sides[0].members[g_first].moves[0].move_id == DFI_MOVE_OUTRAGE);
    duoforge_battle *b = df_make_battle(ctx, &s);
    DF_CHECK(t, b != NULL);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    return b;
}

/* The lead of side 0 at position 1 (Garchomp, whose move in slot 0 is Outrage) is locked into it, with two turns of the count (a hit to start it). */
static void lock_lead(duoforge_battle *b)
{
    b->tail.sides[0].positions[g_lead].lock_turns = 2u;
    b->sides[0].positions[g_lead].locked_move = 1u;
    b->tail.sides[0].positions[g_lead].last_move = 1u; /* a running lock's move is the one used last (Outrage, slot 0) */
}

/* A running lockedmove has its move as the occupant's last used one (view audit 2026-10-10; the public record's proxy,
 * dfi_maybe_lockedmove, relies on it): a lock whose last move is none or another move is a broken state, refused by the
 * state check as by the public record. */
static void test_lock_needs_its_last_move(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    lock_lead(b);
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    const uint32_t occ = b->sides[0].positions[g_lead].occupant;
    DF_CHECK(t, b->sides[0].members[occ].moves[1].move_id != DFI_MOVE_OUTRAGE);
    for (uint32_t last = 0u; last <= 2u; last += 2u) { /* none, then the move in slot 1 */
        b->tail.sides[0].positions[g_lead].last_move = (uint8_t)last;
        DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
        for (uint32_t p = 0u; p < 2u; ++p) {
            duoforge_public_state v;
            DF_CHECK(t, duoforge_battle_public(ctx, b, p, &v) == DUOFORGE_E_INVARIANT);
        }
    }
    duoforge_battle_destroy(b);
}

/* The step's state, as the encoding of the battle; a refused step must leave it as it was. */
static size_t state_of(const duoforge_context *ctx, const duoforge_battle *b, uint8_t *out)
{
    return dfi_encode_unchecked(ctx, b, out);
}

/* One step of `turn` on a clone of `base`, reseeded: the status and the state after it. */
static duoforge_status step_clone(df_test *t, const duoforge_context *ctx, const duoforge_battle *base, uint64_t seed,
                                  duoforge_battle **out_clone)
{
    duoforge_battle *y = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL);
    DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
    *out_clone = y;
    duoforge_decision_bundle bd;
    turn_bundle(&bd, y);
    duoforge_step_result res;
    return duoforge_battle_step(ctx, y, &bd, &res);
}

/* The refusal leaves the battle as it was: the clone's encoding is the same after the refused step as before it. */
static void check_refused_atomically(df_test *t, const duoforge_context *ctx, const duoforge_battle *base, uint64_t seed)
{
    static uint8_t before[DF_STATE_ENCODED_MAX];
    static uint8_t after[DF_STATE_ENCODED_MAX];
    duoforge_battle *y = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, base, &y) == DUOFORGE_OK && y != NULL);
    DF_CHECK(t, duoforge_battle_reseed(ctx, y, seed, 2u) == DUOFORGE_OK);
    const size_t nb = state_of(ctx, y, before);
    duoforge_decision_bundle bd;
    turn_bundle(&bd, y);
    duoforge_step_result res;
    const duoforge_status dst = duoforge_battle_step(ctx, y, &bd, &res);
    DF_CHECK(t, dst == DUOFORGE_E_UNSUPPORTED);
    const size_t na = state_of(ctx, y, after);
    DF_CHECK_EQ_U64(t, nb, na);
    DF_CHECK_BYTES(t, after, before, nb, "a refused step changes nothing");
    duoforge_battle_destroy(y);
}

/* Over the seeds, the step is refused for some and carries on for the others: a chance roll (the freeze's thaw, the full
 * paralysis) decides, and the refusal is the same for every battle that the roll stops. */
static void check_chance(df_test *t, const duoforge_context *ctx, const duoforge_battle *base, const char *what)
{
    unsigned refused = 0u;
    unsigned carried = 0u;
    for (uint64_t seed = 1u; seed <= 64u; ++seed) {
        duoforge_battle *y = NULL;
        const duoforge_status st = step_clone(t, ctx, base, seed, &y);
        if (st == DUOFORGE_E_UNSUPPORTED) {
            refused += 1u;
        } else {
            DF_CHECK(t, st == DUOFORGE_OK);
            carried += 1u;
        }
        duoforge_battle_destroy(y);
    }
    if (!DF_CHECK(t, refused > 0u && carried > 0u)) {
        fprintf(stderr, "  %s: refused %u, carried on %u\n", what, refused, carried);
    }
}

/* Information safety of the lock length (view audit 2026-10-10). The count (2 or 3) is drawn; its end shows a fatigue
 * confusion, which Misty Terrain stops silently for a grounded holder. A lead that used Outrage last may then still be
 * locked (count 1 left) or free (a 2-turn lock that ended without a line): both players must see the same refusal, and the
 * foe's observation the same locked slot of a choice-locked holder. */
static void test_lock_length_information_safety(df_test *t, const duoforge_context *ctx)
{
    for (uint32_t choice = 0u; choice < 2u; ++choice) {
        duoforge_status st[2][2];
        uint8_t locked_slot[2];
        for (uint32_t running = 0u; running < 2u; ++running) {
            duoforge_battle *b = turn_battle(t, ctx);
            const uint32_t occ = b->sides[0].positions[g_lead].occupant;
            b->tail.sides[0].positions[g_lead].last_move = 1u; /* Outrage, slot 0, used last */
            b->tail.sides[0].positions[g_lead].lock_turns = running != 0u ? 1u : 0u;
            b->sides[0].positions[g_lead].locked_move = (running != 0u || choice != 0u) ? 1u : 0u;
            if (choice != 0u) {
                b->sides[0].members[occ].item = (uint8_t)(1u + DFI_ITEM_CHOICESCARF);
                b->sides[0].positions[g_lead].flags =
                    (uint8_t)((uint32_t)b->sides[0].positions[g_lead].flags | DFI_VOL_CHOICE_LOCK);
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_public_state v;
                st[running][p] = duoforge_battle_public(ctx, b, p, &v);
            }
            duoforge_observation o;
            DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &o) == DUOFORGE_OK);
            locked_slot[running] = o.sides[0].positions[g_lead].locked_slot;
            duoforge_battle_destroy(b);
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            DF_CHECK(t, st[0][p] == st[1][p]);
        }
        DF_CHECK(t, locked_slot[0] == locked_slot[1]);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g56");
    duoforge_context *kp = df_make_context(&df_config_pool);

    /* A lock with nothing that stops its use: the step carries on, and the count goes down (a hit or a miss alike). */
    duoforge_battle *base = turn_battle(&t, kp);
    lock_lead(base);
    DF_CHECK(&t, duoforge_battle_check(kp, base) == DUOFORGE_OK);
    {
        duoforge_battle *y = NULL;
        DF_CHECK(&t, step_clone(&t, kp, base, 1u, &y) == DUOFORGE_OK);
        DF_CHECK(&t, y != NULL);
        duoforge_battle_destroy(y);
    }

    /* A flinch on the locked user: its move is stopped before its use, so the lock would reach the residual: refused, and
     * the battle is left as it was. */
    {
        duoforge_battle *f = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &f) == DUOFORGE_OK && f != NULL);
        f->sides[0].positions[g_lead].flags = (uint8_t)((uint32_t)f->sides[0].positions[g_lead].flags | DFI_VOL_FLINCH);
        check_refused_atomically(&t, kp, f, 1u);
        duoforge_battle_destroy(f);
    }

    /* A locked user that is confused (a lock may start under confusion, and the confusion's self-hit stops its move: refused,
     * as the lock then reaches the residual unused; the campaign's three UNSUPPORTED battles are this shape). The self-hit is
     * a roll: refused for some seeds, carried on for the others. */
    {
        duoforge_battle *cf = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &cf) == DUOFORGE_OK && cf != NULL);
        cf->sides[0].positions[g_lead].confusion_turns = 3u;
        check_chance(&t, kp, cf, "confusion self-hit");
        duoforge_battle_destroy(cf);
    }

    /* A freeze with two turns to go: the thaw is a roll of one in four; the frozen user's move is stopped (refused), and the
     * thawed one moves (carried on). */
    {
        duoforge_battle *fr = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &fr) == DUOFORGE_OK && fr != NULL);
        const uint32_t occ = fr->sides[0].positions[g_lead].occupant;
        fr->sides[0].members[occ].status = (uint8_t)DFI_STATUS_FRZ;
        fr->sides[0].members[occ].status_counter = 2u;
        check_chance(&t, kp, fr, "freeze");
        duoforge_battle_destroy(fr);
    }

    /* A full paralysis roll of one in eight: refused when it comes up, carried on otherwise. */
    {
        duoforge_battle *pa = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &pa) == DUOFORGE_OK && pa != NULL);
        const uint32_t occ = pa->sides[0].positions[g_lead].occupant;
        pa->sides[0].members[occ].status = (uint8_t)DFI_STATUS_PAR;
        check_chance(&t, kp, pa, "full paralysis");
        duoforge_battle_destroy(pa);
    }

    /* A White Herb holder with its stat down, at the lock's last use (count 1, no restart): the White Herb and the lock's
     * confusion would both print at the end of the use, so the step is refused. */
    {
        duoforge_battle *h = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &h) == DUOFORGE_OK && h != NULL);
        h->tail.sides[0].positions[g_lead].lock_turns = 1u;
        const uint32_t occ = h->sides[0].positions[g_lead].occupant;
        h->sides[0].members[occ].item = (uint8_t)(1u + DFI_ITEM_WHITEHERB); /* the item code: 1 + the item id */
        h->tail.sides[0].item_now[occ] = (uint8_t)(1u + DFI_ITEM_WHITEHERB); /* what the member holds now (the tail's copy) */
        h->sides[0].positions[g_lead].stages[1] = (uint8_t)(DFI_STAGE_NEUTRAL - 1u);
        /* the lead moves first (speed +6), so its Outrage's AfterMove is the first one of the turn: the herb is still due then */
        h->sides[0].positions[g_lead].stages[4] = (uint8_t)(DFI_STAGE_NEUTRAL + 6u);
        DF_CHECK(&t, duoforge_battle_check(kp, h) == DUOFORGE_OK);
        check_refused_atomically(&t, kp, h, 1u);
        duoforge_battle_destroy(h);
    }

    /* A sleeping holder: the sleep stops its move (not a refusal), and the residual deletes its lock silently (lockedmove's
     * onResidual, data/conditions.ts:260-262): no lock and no locked move after the turn. */
    {
        duoforge_battle *sl = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, base, &sl) == DUOFORGE_OK && sl != NULL);
        const uint32_t occ = sl->sides[0].positions[g_lead].occupant;
        sl->sides[0].members[occ].status = (uint8_t)DFI_STATUS_SLP;
        sl->sides[0].members[occ].status_counter = 3u;
        duoforge_battle *after = NULL;
        DF_CHECK(&t, step_clone(&t, kp, sl, 1u, &after) == DUOFORGE_OK && after != NULL);
        if (after != NULL) {
            DF_CHECK_EQ_U64(&t, after->tail.sides[0].positions[g_lead].lock_turns, 0u);
            DF_CHECK_EQ_U64(&t, after->sides[0].positions[g_lead].locked_move, 0u);
        }
        duoforge_battle_destroy(after);
        duoforge_battle_destroy(sl);
    }

    test_lock_length_information_safety(&t, kp);
    test_lock_needs_its_last_move(&t, kp);

    duoforge_battle_destroy(base);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
