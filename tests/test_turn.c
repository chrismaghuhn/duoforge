/*
 * duoforge.combat.turn: the turn core, switching and fainting through the
 * public API with the battle's own PCG (the reference conformance runs on a
 * tape in duoforge.reference.conformance). Development teams (CLOSURE_DEV,
 * No Ability, no items, implemented moves only):
 *
 *  - a turn advances turn and epoch, spends PP, changes HP, and the
 *    opponent sees the new HP display;
 *  - a switch: a fresh activation, the newcomer is seen, the leaver keeps
 *    its last display; a faint at the end of a turn asks the side for a
 *    replacement;
 *  - determinism: the same inputs give the same bytes; a battle encoded and
 *    decoded at every boundary continues exactly like the original;
 *  - honest E_UNSUPPORTED, atomically: a member whose mechanics are not
 *    marked (decoded state), and every combat bundle under SYNTHETIC;
 *  - random play to the end: random legal choices (moves, switches, passes,
 *    replacements) keep every invariant and end at TERMINAL with a result.
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "data/closure_tables.h"
#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"

/* Bulky development teams: damage stays low, so many turns pass before a
 * faint (which needs step 3). */
static void dev_setup(duoforge_battle_setup *s, uint64_t seed)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = seed;
    s->rng_initseq = 77u;
    static const struct {
        uint32_t species, gender, nature, sp[6], moves[4], move_count;
    } a[4] = {
        {DFI_FORME_ARCHALUDON, 1u, DFI_NATURE_BOLD, {32u, 0u, 1u, 0u, 24u, 9u},
         {DFI_MOVE_DRAGONPULSE, DFI_MOVE_ELECTROSHOT, DFI_MOVE_SNARL, DFI_MOVE_PROTECT}, 4u},
        {DFI_FORME_MILOTIC, 2u, DFI_NATURE_CALM, {32u, 0u, 29u, 0u, 5u, 0u},
         {DFI_MOVE_MUDDYWATER, DFI_MOVE_COIL, 0u, 0u}, 2u},
        {DFI_FORME_GOLISOPOD, 2u, DFI_NATURE_ADAMANT, {32u, 32u, 0u, 0u, 1u, 1u},
         {DFI_MOVE_DRILLRUN, DFI_MOVE_PROTECT, 0u, 0u}, 2u},
        {DFI_FORME_FARIGIRAF, 1u, DFI_NATURE_BOLD, {29u, 0u, 20u, 0u, 17u, 0u},
         {DFI_MOVE_PSYCHIC, DFI_MOVE_PROTECT, 0u, 0u}, 2u},
    };
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = 4u;
        for (uint32_t m = 0; m < 4u; ++m) {
            duoforge_member_setup *d = &s->sides[side].members[m];
            d->species_id = a[m].species;
            d->gender = side == 0u ? a[m].gender : 3u - a[m].gender;
            d->nature = a[m].nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                d->stat_points[i] = a[m].sp[i];
            }
            d->move_count = a[m].move_count;
            for (uint32_t k = 0; k < a[m].move_count; ++k) {
                d->moves[k].move_id = a[m].moves[k];
            }
        }
    }
    /* Electro Shot needs step 10: Archaludon keeps only the turn-core moves. */
    s->sides[0].members[0].moves[1].move_id = DFI_MOVE_PROTECT;
    s->sides[0].members[0].moves[3].move_id = 0u;
    s->sides[0].members[0].move_count = 3u;
    s->sides[1].members[0] = s->sides[0].members[0];
    s->sides[1].members[0].gender = 2u;
}

/* A bundle from candidate index i of each side (modulo the count). */
static duoforge_status bundle_from(const duoforge_context *ctx, const duoforge_battle *b, uint32_t i0, uint32_t i1,
                                   duoforge_decision_bundle *bd)
{
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = b->request_mask;
    const uint32_t pick[2] = {i0, i1};
    for (uint32_t s = 0; s < 2u; ++s) {
        if (((uint32_t)b->request_mask >> s & 1u) == 0u) {
            continue;
        }
        uint32_t n = 0;
        const duoforge_status st = duoforge_battle_candidates(ctx, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n);
        if (st != DUOFORGE_OK || n == 0u) {
            return st == DUOFORGE_OK ? DUOFORGE_E_INVARIANT : st;
        }
        bd->responses[s] = cands[pick[s] % n];
    }
    return DUOFORGE_OK;
}

/* A candidate of each requested side, chosen from `seed`: at TURN one whose
 * slots move (no Mega) or pass, or with allow_switch any candidate. */
static duoforge_status pick_bundle(const duoforge_context *ctx, const duoforge_battle *b, uint32_t seed,
                                   bool allow_switch, duoforge_decision_bundle *bd)
{
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = b->request_mask;
    const bool turn = b->boundary_kind == DUOFORGE_BOUNDARY_TURN;
    for (uint32_t s = 0; s < 2u; ++s) {
        if (((uint32_t)b->request_mask >> s & 1u) == 0u) {
            continue;
        }
        uint32_t n = 0;
        if (duoforge_battle_candidates(ctx, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK) {
            return DUOFORGE_E_INVARIANT;
        }
        bool found = false;
        for (uint32_t j = 0; j < n && !found; ++j) {
            const duoforge_side_choice *c = &cands[(j + seed * (s + 3u)) % n];
            bool ok = true;
            for (uint32_t k = 0; k < 2u && turn && !allow_switch; ++k) {
                const uint32_t kind = c->slots[k].kind;
                ok = ok && ((kind == DUOFORGE_SLOT_MOVE && c->slots[k].mega == 0u) || kind == DUOFORGE_SLOT_PASS ||
                            kind == DUOFORGE_SLOT_NONE);
            }
            for (uint32_t k = 0; k < 2u; ++k) {
                ok = ok && c->slots[k].mega == 0u;
            }
            if (ok) {
                bd->responses[s] = *c;
                found = true;
            }
        }
        if (!found) {
            return DUOFORGE_E_INVARIANT;
        }
    }
    return DUOFORGE_OK;
}

static duoforge_status move_bundle(const duoforge_context *ctx, const duoforge_battle *b, uint32_t seed,
                                   duoforge_decision_bundle *bd)
{
    return pick_bundle(ctx, b, seed, false, bd);
}

static void encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t *out)
{
    df_encode(ctx, b, out);
}

static duoforge_battle *started(df_test *t, const duoforge_context *k2, uint64_t seed)
{
    duoforge_battle_setup s;
    dev_setup(&s, seed);
    duoforge_battle *b = NULL;
    DF_CHECK(t, duoforge_battle_create(k2, &s, &b) == DUOFORGE_OK);
    if (b == NULL) {
        return NULL;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    DF_CHECK(t, bundle_from(k2, b, 0u, 0u, &bd) == DUOFORGE_OK); /* picks 0,1,2,3 */
    DF_CHECK(t, duoforge_battle_step(k2, b, &bd, &res) == DUOFORGE_OK && b->turn == 1u);
    return b;
}

/* The bundle is rejected with `expected` and the battle is unchanged. */
static void rejected(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const duoforge_decision_bundle *bd,
                     duoforge_status expected, const char *what)
{
    uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
    encode(ctx, b, before);
    duoforge_step_result res;
    memset(&res, 0xA5, sizeof res);
    const duoforge_status st = duoforge_battle_step(ctx, b, bd, &res);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  %s: %s, expected %s\n", what, duoforge_status_name(st), duoforge_status_name(expected));
    }
    encode(ctx, b, after);
    DF_CHECK_BYTES(t, after, before, sizeof after, what);
    DF_CHECK(t, res.kind == 0xA5u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.turn");
    duoforge_context *k2 = df_make_context(&df_config_k2);

    /* One turn: Archaludon Dragon Pulse into side 1's Archaludon (slot a). */
    {
        duoforge_battle *b = started(&t, k2, 5u);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = b->request_epoch;
        bd.response_mask = 3u;
        for (uint32_t s = 0; s < 2u; ++s) {
            bd.responses[s].epoch = b->request_epoch;
            bd.responses[s].side = (uint8_t)s;
            bd.responses[s].kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            bd.responses[s].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, (uint8_t)((1u - s) * 2u), 0u,
                                                               0u, {0u, 0u, 0u}}; /* wide-operands-reviewed */
            bd.responses[s].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 1u, DUOFORGE_TARGET_NONE, 0u, 0u,
                                                               {0u, 0u, 0u}}; /* Milotic: Coil */
        }
        const uint32_t hp0 = b->sides[1].members[0].hp;
        const uint32_t epoch = b->request_epoch;
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(k2, b, &bd, &res) == DUOFORGE_OK);
        DF_CHECK(&t, res.kind == DUOFORGE_STEP_BOUNDARY && res.boundary_kind == DUOFORGE_BOUNDARY_TURN &&
                         res.request_mask == 3u && res.epoch == epoch + 1u);
        DF_CHECK(&t, b->turn == 2u && b->request_epoch == epoch + 1u);
        DF_CHECK(&t, b->sides[0].members[0].moves[0].pp == 11u && b->sides[0].members[1].moves[1].pp == 19u);
        DF_CHECK(&t, b->sides[0].positions[1].stages[0] == 7u && b->sides[0].positions[1].stages[1] == 7u &&
                         b->sides[0].positions[1].stages[5] == 7u);
        /* Dragon Pulse hits Archaludon (Dragon) super effectively unless it
         * misses (accuracy 100: it never does). */
        const uint32_t hp1 = b->sides[1].members[0].hp;
        DF_CHECK(&t, hp1 < hp0);
        /* The opponent sees the new HP display and the move use. */
        duoforge_observation o;
        DF_CHECK(&t, duoforge_battle_observe(k2, b, 0, &o) == DUOFORGE_OK);
        DF_CHECK(&t, o.sides[1].members[0].hp_kind == DUOFORGE_HP_PERCENT && o.sides[1].members[0].hp == hp1 * 100u / hp0);
        DF_CHECK(&t, b->sides[1].knowledge[0].moves_used[0] == 1u && b->sides[0].knowledge[1].moves_used[1] == 1u);
        DF_CHECK(&t, duoforge_battle_check(k2, b) == DUOFORGE_OK);
        duoforge_battle_destroy(b);
    }

    /* Determinism, and continuation across encode/decode at every boundary. */
    {
        duoforge_battle *a = started(&t, k2, 99u);
        duoforge_battle *b = started(&t, k2, 99u);
        unsigned turns = 0;
        bool same = true;
        for (uint32_t i = 0; i < 400u && a != NULL && b != NULL; ++i) {
            if (a->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                break;
            }
            duoforge_decision_bundle bd;
            DF_CHECK(&t, pick_bundle(k2, a, i, (i % 5u) == 4u, &bd) == DUOFORGE_OK);
            /* b goes through a full encode/decode before every step. */
            uint8_t enc[DUOFORGE_STATE_V3_ENCODED_SIZE];
            encode(k2, b, enc);
            DF_CHECK(&t, duoforge_battle_decode(k2, b, enc, sizeof enc) == DUOFORGE_OK);
            duoforge_step_result ra;
            duoforge_step_result rb;
            const duoforge_status sa = duoforge_battle_step(k2, a, &bd, &ra);
            const duoforge_status sb = duoforge_battle_step(k2, b, &bd, &rb);
            DF_CHECK(&t, sa == sb && sa == DUOFORGE_OK);
            if (sa != DUOFORGE_OK) {
                break;
            }
            bool eq = false;
            DF_CHECK(&t, duoforge_battle_equal(k2, a, b, &eq) == DUOFORGE_OK);
            same = same && eq;
            turns += 1u;
        }
        DF_CHECK(&t, same);
        DF_CHECK(&t, turns >= 3u);
        DF_CHECK(&t, a != NULL && a->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL && a->result != 0u);
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
    }

    /* A switch, a faint and the replacement. */
    {
        duoforge_battle *b = started(&t, k2, 7u);
        duoforge_decision_bundle bd;
        DF_CHECK(&t, move_bundle(k2, b, 0u, &bd) == DUOFORGE_OK);
        duoforge_decision_bundle sw = bd;
        sw.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 2u, {0u, 0u, 0u}};
        duoforge_battle *y = NULL;
        DF_CHECK(&t, duoforge_battle_clone(k2, b, &y) == DUOFORGE_OK);
        const uint32_t old_activation = y->sides[0].positions[0].activation_id;
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(k2, y, &sw, &res) == DUOFORGE_OK);
        DF_CHECK(&t, y->sides[0].positions[0].occupant == 2u &&
                         y->sides[0].positions[0].activation_id > old_activation);
        DF_CHECK(&t, (y->sides[1].seen_mask & 0x05u) == 0x05u); /* roster 0 left, roster 2 came: both seen */
        DF_CHECK(&t, y->sides[1].knowledge[0].hp_percent != 0u); /* the leaver keeps its display */
        duoforge_battle_destroy(y);
        /* A faint: side 1's Archaludon at 1 HP takes Dragon Pulse. */
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(k2, b, &x) == DUOFORGE_OK);
        x->sides[1].members[0].hp = 1u;
        dfi_knowledge_refresh_active(x);
        duoforge_decision_bundle hit = bd;
        hit.epoch = x->request_epoch;
        for (uint32_t s = 0; s < 2u; ++s) {
            hit.responses[s].epoch = x->request_epoch;
            hit.responses[s].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, (uint8_t)((1u - s) * 2u), 0u,
                                                                0u, {0u, 0u, 0u}}; /* wide-operands-reviewed */
            hit.responses[s].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 1u, DUOFORGE_TARGET_NONE, 0u,
                                                                0u, {0u, 0u, 0u}};
        }
        {
            duoforge_battle *z = NULL;
            DF_CHECK(&t, duoforge_battle_clone(k2, x, &z) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_battle_step(k2, z, &hit, &res) == DUOFORGE_OK);
            DF_CHECK(&t, z->sides[1].members[0].hp == 0u);
            /* At the end of the turn side 1 must replace slot a (it has two
             * reserves); side 0 waits. */
            DF_CHECK(&t, z->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT && z->request_mask == 2u &&
                             z->sides[1].requested_slots == 1u && z->turn == x->turn);
            DF_CHECK(&t, res.boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT && res.request_mask == 2u);
            duoforge_decision_bundle rep;
            DF_CHECK(&t, pick_bundle(k2, z, 1u, true, &rep) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_battle_step(k2, z, &rep, &res) == DUOFORGE_OK);
            DF_CHECK(&t, z->boundary_kind == DUOFORGE_BOUNDARY_TURN && z->turn == x->turn + 1u);
            DF_CHECK(&t, z->sides[1].members[z->sides[1].positions[0].occupant].hp != 0u);
            DF_CHECK(&t, duoforge_battle_check(k2, z) == DUOFORGE_OK);
            duoforge_battle_destroy(z);
        }
        /* A decoded member with an ability (Archaludon's Stamina) cannot be
         * played: the step checks the manifest too. */
        x->sides[1].members[0].hp = x->sides[1].members[0].hp_max;
        x->sides[1].members[0].ability = (uint8_t)(DFI_ABILITY_STAMINA + 1u); /* wide-operands-reviewed */
        dfi_knowledge_refresh_active(x);
        DF_CHECK(&t, duoforge_battle_check(k2, x) == DUOFORGE_OK);
        rejected(&t, k2, x, &hit, DUOFORGE_E_UNSUPPORTED, "an unmarked ability");
        duoforge_battle_destroy(x);
        duoforge_battle_destroy(b);
        /* Under SYNTHETIC every combat bundle stays unsupported. */
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_decision_bundle sb;
        DF_CHECK(&t, bundle_from(c1, f1, 0u, 0u, &sb) == DUOFORGE_OK);
        rejected(&t, c1, f1, &sb, DUOFORGE_E_UNSUPPORTED, "TURN under SYNTHETIC");
        duoforge_battle_destroy(f1);
        duoforge_context_destroy(c1);
    }

    /* Random play to the end: random legal choices (one in four may
     * switch) for many seeds; every committed state passes the checker and
     * every run ends at TERMINAL with a result. */
    {
        dfi_rng pick;
        dfi_rng_seed(&pick, 4242u, 1u);
        unsigned steps = 0;
        unsigned ended = 0;
        unsigned replacements = 0;
        unsigned results[4] = {0, 0, 0, 0};
        for (uint64_t seed = 1u; seed <= 40u; ++seed) {
            duoforge_battle *b = started(&t, k2, seed);
            if (b == NULL) {
                continue;
            }
            for (uint32_t i = 0; i < 600u && b->boundary_kind != DUOFORGE_BOUNDARY_TERMINAL; ++i) {
                uint32_t r = 0;
                (void)dfi_rng_next_u32(&pick, &r);
                duoforge_decision_bundle bd;
                if (!DF_CHECK(&t, pick_bundle(k2, b, r, (r & 3u) == 0u, &bd) == DUOFORGE_OK)) {
                    break;
                }
                replacements += b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT ? 1u : 0u;
                duoforge_step_result res;
                const duoforge_status st = duoforge_battle_step(k2, b, &bd, &res);
                if (!DF_CHECK(&t, st == DUOFORGE_OK)) {
                    fprintf(stderr, "  seed %u step %u: %s\n", (unsigned)seed, i, duoforge_status_name(st));
                    break;
                }
                DF_CHECK(&t, duoforge_battle_check(k2, b) == DUOFORGE_OK);
                steps += 1u;
            }
            if (b->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                ended += 1u;
                results[b->result & 3u] += 1u;
                /* A finished battle requests nobody and takes no bundle. */
                duoforge_request rq;
                DF_CHECK(&t, duoforge_battle_request(k2, b, 0u, &rq) == DUOFORGE_OK && rq.requested == 0u);
            }
            duoforge_battle_destroy(b);
        }
        DF_CHECK_EQ_U64(&t, ended, 40u);
        DF_CHECK(&t, replacements > 0u && results[1] > 0u && results[2] > 0u);
        fprintf(stderr, "  random play: %u steps, %u battles ended (side 0 %u, side 1 %u, tie %u), %u replacements\n",
                steps, ended, results[1], results[2], results[3], replacements);
    }

    duoforge_context_destroy(k2);
    return df_test_end(&t);
}
