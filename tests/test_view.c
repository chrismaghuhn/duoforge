/*
 * duoforge.view: the public state, the world and the hypothesis (decision
 * 0023), over random play of Teams A, B and C under CLOSURE, TEAM_C and POOL,
 * at every state and for both players.
 *
 * - Round trip: from_view(public(s, p), hypothesis(s, p)) is s, byte for
 *   byte, apart from the RNG.
 * - Tightness: for random valid hypotheses h, public(from_view(public(s, p),
 *   h), p) is public(s, p), and p's observation (with its extension) is the
 *   same in every such world.
 * - The refusals (E_UNSUPPORTED) are counted, and only the documented ones
 *   occur.
 * - The integer uniforms: the extremes, and the middle words pick their value.
 * - The argument checks.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_view.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"
#include "state/battle_internal.h"
#include "codec/state_codec.h"

#define GAMES 80u
#define MAX_STEPS 400u
#define WORLDS 4u
#define RNG_OFF 52u
#define RNG_SIZE 24u

static uint32_t masks_checked;
static uint32_t masks_refused;
static uint32_t varied_picks;
static uint32_t varied_commands;

static uint64_t next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15u);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static void team(char letter, duoforge_side_setup *side)
{
    if (letter == 'C') {
        df_put_team_c(side);
        return;
    }
    duoforge_battle_setup s;
    (void)duoforge_reference_setup(letter == 'A' ? 0u : 1u, &s);
    *side = s.sides[0];
}

static duoforge_factored_choice random_choice(const duoforge_factored_domain *d, uint64_t *s)
{
    duoforge_factored_choice c;
    memset(&c, 0, sizeof c);
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        uint8_t order[DUOFORGE_MAX_ROSTER];
        for (uint8_t k = 0u; k < d->member_count; ++k) {
            order[k] = k;
        }
        for (uint32_t k = d->member_count; k > 1u; --k) {
            const uint32_t j = (uint32_t)(next(s) % k);
            const uint8_t tmp = order[k - 1u];
            order[k - 1u] = order[j];
            order[j] = tmp;
        }
        memcpy(c.picks, order, d->pick_count);
    } else if (d->kind == DUOFORGE_CHOICE_SLOTS) {
        uint32_t allowed = 0u;
        for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
            for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
                allowed += (d->allowed[i] >> j) & 1u;
            }
        }
        uint32_t pick = allowed > 0u ? (uint32_t)(next(s) % allowed) : 0u;
        for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
            for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
                if (((d->allowed[i] >> j) & 1u) != 0u && pick-- == 0u) {
                    c.slot[0] = (uint8_t)i;
                    c.slot[1] = (uint8_t)j;
                }
            }
        }
    }
    return c;
}

static bool build_bundle(const duoforge_request *rq, const duoforge_factored_domain *d,
                         const duoforge_factored_choice *c, duoforge_decision_bundle *b)
{
    memset(b, 0, sizeof *b);
    b->epoch = rq[0].epoch;
    for (uint32_t p = 0u; p < 2u; ++p) {
        if (rq[p].requested == 0u) {
            continue;
        }
        duoforge_side_choice *o = &b->responses[p];
        o->epoch = d[p].epoch;
        o->side = (uint8_t)p;
        o->kind = d[p].kind;
        if (d[p].kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
            o->pick_count = d[p].pick_count;
            memcpy(o->picks, c[p].picks, sizeof o->picks);
        } else if (d[p].kind == DUOFORGE_CHOICE_SLOTS) {
            const uint32_t i = c[p].slot[0];
            const uint32_t j = c[p].slot[1];
            if (i >= d[p].slot_count[0] || j >= d[p].slot_count[1] || ((d[p].allowed[i] >> j) & 1u) == 0u) {
                return false;
            }
            o->slots[0] = d[p].slots[0][i];
            o->slots[1] = d[p].slots[1][j];
        } else {
            return false;
        }
        b->response_mask = (uint8_t)(b->response_mask | (1u << p));
    }
    return true;
}

/* The canonical bytes of b with the RNG zeroed. */
static size_t bytes_of(const duoforge_context *ctx, const duoforge_battle *b, uint8_t *out)
{
    size_t n = df_encode_n(ctx, b, out);
    memset(out + RNG_OFF, 0, RNG_SIZE);
    return n;
}

/* A random valid hypothesis that keeps the true picks of `truth`. */
static void random_hypothesis(const duoforge_context *ctx, duoforge_battle *scratch, const duoforge_hypothesis *truth,
                              const duoforge_public_state *v, uint64_t *s, duoforge_hypothesis *h)
{
    *h = *truth;
    uint32_t brought = 0u;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        brought += truth->pick_order[k] != DUOFORGE_VIEW_PICK_NONE ? 1u : 0u;
    }
    for (uint32_t p = 0u; p < 2u; ++p) {
        if ((v->foe_pending_mask & (1u << p)) == 0u) {
            continue;
        }
        for (uint32_t attempt = 0u; attempt < 16u; ++attempt) {
            duoforge_hypothesis candidate = *h;
            candidate.queued[p].move_slot = (uint8_t)(next(s) % DUOFORGE_MAX_MOVE_SLOTS);
            const uint32_t target = (uint32_t)(next(s) % 5u);
            candidate.queued[p].target = target == 4u ? (uint8_t)DUOFORGE_TARGET_NONE : (uint8_t)target;
            if (duoforge_battle_from_view(ctx, v, &candidate, scratch) == DUOFORGE_OK) {
                h->queued[p] = candidate.queued[p];
                break;
            }
        }
    }
    if (brought >= 2u) {
        uint8_t candidates[DUOFORGE_MAX_ROSTER];
        for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
            candidates[k] = (uint8_t)k;
        }
        for (uint32_t k = DUOFORGE_MAX_ROSTER; k > 1u; --k) {
            const uint32_t j = (uint32_t)(next(s) % k);
            const uint8_t tmp = candidates[k - 1u];
            candidates[k - 1u] = candidates[j];
            candidates[j] = tmp;
        }
        memset(h->pick_order + 2u, DUOFORGE_VIEW_PICK_NONE, DUOFORGE_MAX_ROSTER - 2u);
        uint32_t filled = 2u;
        uint32_t mask = (1u << h->pick_order[0]) | (1u << h->pick_order[1]);
        for (uint32_t pass = 0u; pass < 2u; ++pass) {
            for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER && filled < brought; ++k) {
                const uint32_t m = candidates[k];
                if ((mask & (1u << m)) == 0u && (pass != 0u || (v->foe_seen_mask & (1u << m)) != 0u)) {
                    h->pick_order[filled++] = (uint8_t)m;
                    mask |= 1u << m;
                }
            }
        }
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        uint32_t total = 0u;
        for (uint32_t i = 0u; i < 6u; ++i) {
            uint32_t points = (uint32_t)(next(s) % 33u);
            if (total + points > 66u) {
                points = 66u - total;
            }
            h->stat_points[m][i] = (uint8_t)points;
            total += points;
        }
        h->hp[m] = next(s);
    }
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            h->sleep[side][m] = next(s);
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            h->confusion[side][p] = next(s);
        }
    }
    for (uint32_t p = 0u; p < 2u; ++p) {
        h->charge_target[p] = next(s);
    }
    varied_picks += memcmp(h->pick_order, truth->pick_order, sizeof h->pick_order) != 0 ? 1u : 0u;
    varied_commands += memcmp(h->queued, truth->queued, sizeof h->queued) != 0 ? 1u : 0u;
}

typedef struct tally {
    uint32_t states;
    uint32_t checked;
    uint32_t unsupported;
    uint32_t sleeping;
    uint32_t confused;
    uint32_t charging;
    uint32_t contradicted;
} tally;

static void check_state(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, duoforge_battle *world,
                        uint64_t *rs, tally *ty)
{
    static uint8_t want[DF_STATE_ENCODED_MAX];
    static uint8_t got[DF_STATE_ENCODED_MAX];
    ++ty->states;
    for (uint32_t p = 0u; p < 2u; ++p) {
        duoforge_public_state view;
        duoforge_hypothesis h;
        const duoforge_status st = duoforge_battle_public(ctx, b, p, &view);
        DF_CHECK(t, st == DUOFORGE_OK || st == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, p, &h) == st);
        if (st != DUOFORGE_OK) {
            ++ty->unsupported;
            continue;
        }
        ++ty->checked;
        for (uint32_t side = 0u; side < 2u; ++side) {
            const uint8_t *sb = view.state + 215u + 397u * side;
            for (uint32_t m = 0u; m < 6u; ++m) {
                ty->sleeping += sb[109u + 48u * m + 28u] == DUOFORGE_VIEW_HIDDEN;
            }
            for (uint32_t q = 0u; q < 2u; ++q) {
                ty->confused += sb[15u + 21u * q + 15u] == DUOFORGE_VIEW_HIDDEN;
                ty->charging += sb[15u + 21u * q + 18u] == DUOFORGE_VIEW_HIDDEN_TARGET;
            }
        }
        DF_CHECK(t, duoforge_battle_from_view(ctx, &view, &h, world) == DUOFORGE_OK);
        /* Step G46 (decision 0023): the foe's bench order past its actives is not public, so an honest world takes it from
         * the hypothesis. Every other byte must equal the true state; the foe's actives must equal the truth. */
        static struct duoforge_battle truth;
        const uint32_t foe = p ^ 1u;
        DF_CHECK(t, dfi_party_entry(&world->tail, foe, 0u) == dfi_party_entry(&b->tail, foe, 0u));
        DF_CHECK(t, dfi_party_entry(&world->tail, foe, 1u) == dfi_party_entry(&b->tail, foe, 1u));
        truth = *b;
        memcpy(truth.tail.party_order[foe], world->tail.party_order[foe], sizeof truth.tail.party_order[foe]);
        /* The silent flinch is not public (view audit 2026-10-10): the record drops it where it has no effect (no move left
         * to run before the residual ends it) and refuses the state otherwise, so the world lacks it. */
        for (uint32_t side = 0u; side < 2u; ++side) {
            for (uint32_t slot = 0u; slot < 2u; ++slot) {
                truth.sides[side].positions[slot].flags = (uint8_t)(truth.sides[side].positions[slot].flags & ~DFI_VOL_FLINCH);
            }
        }
        const size_t n = bytes_of(ctx, &truth, want);
        DF_CHECK(t, bytes_of(ctx, world, got) == n);
        DF_CHECK(t, memcmp(want, got, n) == 0);
        duoforge_observation obs_true;
        duoforge_observation_ext ext_true;
        DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &obs_true) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, p, &ext_true) == DUOFORGE_OK);
        for (uint32_t w = 0u; w < WORLDS; ++w) {
            duoforge_hypothesis r;
            random_hypothesis(ctx, world, &h, &view, rs, &r);
            const duoforge_status ws = duoforge_battle_from_view(ctx, &view, &r, world);
            if (ws == DUOFORGE_E_INVALID_ARGUMENT) {
                /* a maximum HP under which no exact HP shows a flagged display: the true HP points fix it */
                ++ty->contradicted;
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    r.stat_points[m][0] = h.stat_points[m][0];
                }
                uint32_t total = 0u;
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    total = 0u;
                    for (uint32_t i = 0u; i < 6u; ++i) {
                        total += r.stat_points[m][i];
                    }
                    for (uint32_t i = 5u; total > 66u; --i) {
                        const uint32_t cut = r.stat_points[m][i] < total - 66u ? r.stat_points[m][i] : total - 66u;
                        r.stat_points[m][i] = (uint8_t)(r.stat_points[m][i] - cut);
                        total -= cut;
                    }
                }
                DF_CHECK(t, duoforge_battle_from_view(ctx, &view, &r, world) == DUOFORGE_OK);
            } else {
                DF_CHECK(t, ws == DUOFORGE_OK);
            }
            duoforge_public_state again;
            DF_CHECK(t, duoforge_battle_public(ctx, world, p, &again) == DUOFORGE_OK);
            DF_CHECK(t, memcmp(&view, &again, sizeof view) == 0);
            duoforge_observation obs;
            duoforge_observation_ext ext;
            DF_CHECK(t, duoforge_battle_observe(ctx, world, p, &obs) == DUOFORGE_OK);
            DF_CHECK(t, duoforge_battle_observe_ext(ctx, world, p, &ext) == DUOFORGE_OK);
            DF_CHECK(t, memcmp(&obs, &obs_true, sizeof obs) == 0);
            DF_CHECK(t, memcmp(&ext, &ext_true, sizeof ext) == 0);
        }
    }
}

/* Step G46 (decision 0023): the foe's party_order past the leads is hidden like its pick order. Varying the foe's TRUE bench
 * order (its positions 2 and 3 swapped, a permutation, with everything public unchanged) leaves the public record, the
 * observation and the honest world's encoding byte for byte equal; the honest world's foe bench is the hypothesis's order. */
static void test_party_order_information_safety(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    duoforge_battle_setup s;
    df_setup_teams(&s);
    duoforge_battle *b = df_make_battle(ctx, &s);
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd.responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    static uint8_t enc_world_a[DF_STATE_ENCODED_MAX];
    static uint8_t enc_world_b[DF_STATE_ENCODED_MAX];
    for (uint32_t p = 0u; p < 2u; ++p) {
        const uint32_t foe = p ^ 1u;
        duoforge_public_state pub;
        memset(&pub, 0, sizeof pub);
        DF_CHECK(t, duoforge_battle_public(ctx, b, p, &pub) == DUOFORGE_OK);
        duoforge_hypothesis h;
        memset(&h, 0, sizeof h);
        DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, p, &h) == DUOFORGE_OK);
        duoforge_battle *w1 = df_make_battle(ctx, &s);
        DF_CHECK(t, duoforge_battle_from_view(ctx, &pub, &h, w1) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_check(ctx, w1) == DUOFORGE_OK);
        /* the foe's bench of the honest world is the hypothesis's brought order, minus the two actives */
        const uint32_t a = dfi_party_entry(&w1->tail, foe, 0u);
        const uint32_t c = dfi_party_entry(&w1->tail, foe, 1u);
        uint32_t want = 2u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            const uint32_t r = (uint32_t)h.pick_order[i] + 1u;
            if (r != a && r != c) {
                DF_CHECK_EQ_U64(t, dfi_party_entry(&w1->tail, foe, want), r);
                want += 1u;
            }
        }
        /* the true foe bench order swapped: a valid permutation, nothing public changes */
        struct duoforge_battle v = *b;
        const uint32_t e2 = dfi_party_entry(&v.tail, foe, 2u);
        const uint32_t e3 = dfi_party_entry(&v.tail, foe, 3u);
        DF_CHECK(t, e2 != e3);
        dfi_party_put(&v.tail, foe, 2u, e3);
        dfi_party_put(&v.tail, foe, 3u, e2);
        DF_CHECK(t, duoforge_battle_check(ctx, &v) == DUOFORGE_OK);
        duoforge_public_state pub_v;
        memset(&pub_v, 0, sizeof pub_v);
        DF_CHECK(t, duoforge_battle_public(ctx, &v, p, &pub_v) == DUOFORGE_OK);
        DF_CHECK(t, memcmp(&pub, &pub_v, sizeof pub) == 0);
        duoforge_observation obs_b;
        duoforge_observation obs_v;
        memset(&obs_b, 0, sizeof obs_b);
        memset(&obs_v, 0, sizeof obs_v);
        DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &obs_b) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_observe(ctx, &v, p, &obs_v) == DUOFORGE_OK);
        DF_CHECK(t, memcmp(&obs_b, &obs_v, sizeof obs_b) == 0);
        duoforge_battle *w2 = df_make_battle(ctx, &s);
        DF_CHECK(t, duoforge_battle_from_view(ctx, &pub_v, &h, w2) == DUOFORGE_OK);
        const size_t na = df_encode_n(ctx, w1, enc_world_a);
        const size_t nb = df_encode_n(ctx, w2, enc_world_b);
        DF_CHECK(t, na == nb && memcmp(enc_world_a, enc_world_b, na) == 0);
        duoforge_battle_destroy(w1);
        duoforge_battle_destroy(w2);
    }
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

static void play(df_test *t, const duoforge_context_config *config, const char *pairs, uint32_t games, uint64_t seed,
                 tally *ty)
{
    duoforge_context *ctx = df_make_context(config);
    uint64_t rs = seed;
    for (uint32_t g = 0u; g < games; ++g) {
        duoforge_battle_setup setup;
        memset(&setup, 0, sizeof setup);
        const uint32_t k = g % ((uint32_t)strlen(pairs) / 2u);
        team(pairs[2u * k], &setup.sides[0]);
        team(pairs[2u * k + 1u], &setup.sides[1]);
        setup.rng_initstate = next(&rs);
        setup.rng_initseq = next(&rs) >> 1;
        duoforge_battle *b = df_make_battle(ctx, &setup);
        duoforge_battle *world = df_make_battle(ctx, &setup);
        duoforge_public_state starts[2];
        bool saved[2] = {false, false};
        duoforge_factored_choice chosen[2] = {0};
        for (uint32_t step = 0u; step < MAX_STEPS; ++step) {
            check_state(t, ctx, b, world, &rs, ty);
            duoforge_request rq[2];
            duoforge_factored_domain d[2];
            duoforge_factored_choice c[2];
            for (uint32_t p = 0u; p < 2u; ++p) {
                DF_CHECK(t, duoforge_battle_request(ctx, b, p, &rq[p]) == DUOFORGE_OK);
                DF_CHECK(t, duoforge_battle_factored(ctx, b, p, &d[p]) == DUOFORGE_OK);
                c[p] = random_choice(&d[p], &rs);
            }
            if (rq[0].boundary_kind == DUOFORGE_BOUNDARY_TURN && rq[0].requested && rq[1].requested) {
                for (uint32_t p = 0u; p < 2u; ++p) {
                    saved[p] = duoforge_battle_public(ctx, b, p, &starts[p]) == DUOFORGE_OK;
                    chosen[p] = c[p];
                }
            }
            if (rq[0].boundary_kind == DUOFORGE_BOUNDARY_PIVOT) {
                for (uint32_t p = 0u; p < 2u; ++p) {
                    duoforge_public_state v;
                    if (!saved[p] || duoforge_battle_public(ctx, b, p, &v) != DUOFORGE_OK) {
                        continue;
                    }
                    uint8_t mask[DUOFORGE_MAX_SLOT_OPTIONS * DUOFORGE_MAX_SLOT_OPTIONS];
                    const duoforge_status ms = duoforge_public_queue_mask(ctx, &starts[p], &v, mask);
                    DF_CHECK(t, ms == DUOFORGE_OK || ms == DUOFORGE_E_UNSUPPORTED);
                    if (ms == DUOFORGE_OK) {
                        ++masks_checked;
                        const duoforge_factored_choice *f = &chosen[p ^ 1u];
                        DF_CHECK(t, mask[(uint32_t)f->slot[0] * DUOFORGE_MAX_SLOT_OPTIONS + f->slot[1]] != 0u);
                        duoforge_public_state bad_start = starts[p];
                        bad_start.reserved[0] = 1u;
                        memset(mask, 0x55, sizeof mask);
                        DF_CHECK(t, duoforge_public_queue_mask(ctx, &bad_start, &v, mask) == DUOFORGE_E_MALFORMED);
                        DF_CHECK(t, mask[0] == 0x55u);
                        bad_start = starts[p];
                        bad_start.pad[0] = 1u;
                        DF_CHECK(t, duoforge_public_queue_mask(ctx, &bad_start, &v, mask) == DUOFORGE_E_MALFORMED);
                    } else {
                        ++masks_refused;
                    }
                }
            }
            if (rq[0].boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                break;
            }
            duoforge_decision_bundle bundle;
            DF_CHECK(t, build_bundle(rq, d, c, &bundle));
            duoforge_step_result r;
            const duoforge_status st = duoforge_battle_step(ctx, b, &bundle, &r);
            if (st == DUOFORGE_E_UNSUPPORTED) {
                break; /* a mechanic the manifest does not mark: the game ends here */
            }
            DF_CHECK(t, st == DUOFORGE_OK);
            if (st != DUOFORGE_OK) {
                break;
            }
        }
        duoforge_battle_destroy(world);
        duoforge_battle_destroy(b);
    }
    duoforge_context_destroy(ctx);
}

static void test_uniforms(df_test *t)
{
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    DF_CHECK(t, sizeof(duoforge_public_state) == 1396u); /* the state array holds the POOL state of tail rev 5 (1357 bytes); was 1336 */
    DF_CHECK(t, sizeof(duoforge_hypothesis) == 280u);
}

static void test_arguments(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup setup;
    (void)duoforge_reference_setup(0u, &setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    duoforge_public_state v;
    duoforge_hypothesis h;
    DF_CHECK(t, duoforge_battle_public(NULL, b, 0u, &v) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public(ctx, NULL, 0u, &v) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 2u, &v) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 2u, &h) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &v) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_from_view(NULL, &v, &h, b) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_from_view(ctx, NULL, &h, b) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, NULL, b) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &h, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    duoforge_public_state bad = v;
    bad.revision = 99u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &bad, &h, b) == DUOFORGE_E_SCHEMA_MISMATCH);
    bad = v;
    bad.reserved[0] = 1u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &bad, &h, b) == DUOFORGE_E_MALFORMED);
    bad = v;
    bad.state_size -= 1u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &bad, &h, b) == DUOFORGE_E_MALFORMED);
    bad = v;
    bad.player = 2u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &bad, &h, b) == DUOFORGE_E_MALFORMED);
    bad = v;
    bad.state[20] ^= 1u; /* the fingerprint */
    DF_CHECK(t, duoforge_battle_from_view(ctx, &bad, &h, b) == DUOFORGE_E_CONTEXT_MISMATCH);
    duoforge_hypothesis hb = h;
    hb.revision = 9u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &hb, b) == DUOFORGE_E_SCHEMA_MISMATCH);
    hb = h;
    hb.stat_points[0][0] = 33u;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &hb, b) == DUOFORGE_E_INVALID_ARGUMENT);
    hb = h;
    memset(hb.stat_points[1], 12, 6u); /* 72 > 66 */
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &hb, b) == DUOFORGE_E_INVALID_ARGUMENT);
    hb = h;
    hb.pick_order[0] = 0u; /* a pick at TEAM_SELECTION */
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &hb, b) == DUOFORGE_E_INVALID_ARGUMENT);
    hb = h;
    hb.queued[0].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &v, &hb, b) == DUOFORGE_E_INVALID_ARGUMENT);
    uint8_t mask[DUOFORGE_MAX_SLOT_OPTIONS * DUOFORGE_MAX_SLOT_OPTIONS];
    memset(mask, 0x55, sizeof mask);
    DF_CHECK(t, duoforge_public_queue_mask(ctx, &v, &v, mask) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, mask[0] == 0x55u && mask[sizeof mask - 1u] == 0x55u);
    /* nothing written on a refusal */
    uint8_t before[DF_STATE_ENCODED_MAX];
    uint8_t after[DF_STATE_ENCODED_MAX];
    const size_t n = df_encode_n(ctx, b, before);
    (void)duoforge_battle_from_view(ctx, &v, &hb, b);
    DF_CHECK(t, df_encode_n(ctx, b, after) == n && memcmp(before, after, n) == 0);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

static void test_batch(df_test *t)
{
    const uint32_t workers[] = {1u, 2u, 3u, 4u, 8u, 16u};
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup setups[16];
    for (uint32_t e = 0u; e < 16u; ++e) {
        (void)duoforge_reference_setup(e % 2u, &setups[e]);
    }
    for (uint32_t k = 0u; k < 6u; ++k) {
        duoforge_batch_config config = {16u, workers[k], 42u, setups};
        duoforge_batch *b = NULL;
        DF_CHECK(t, duoforge_batch_create(ctx, &config, &b) == DUOFORGE_OK);
        duoforge_public_state views[16];
        duoforge_hypothesis hypotheses[16];
        duoforge_status statuses[16];
        uint32_t players[16];
        for (uint32_t e = 0u; e < 16u; ++e) {
            players[e] = e % 2u;
        }
        DF_CHECK(t, duoforge_batch_public(b, players, views, statuses) == DUOFORGE_OK);
        for (uint32_t e = 0u; e < 16u; ++e) {
            duoforge_public_state single;
            const duoforge_battle *battle = duoforge_batch_env(b, e);
            DF_CHECK(t, duoforge_battle_public(ctx, battle, players[e], &single) == DUOFORGE_OK);
            DF_CHECK(t, statuses[e] == DUOFORGE_OK && memcmp(&single, &views[e], sizeof single) == 0);
            DF_CHECK(t, duoforge_battle_hypothesis(ctx, battle, players[e], &hypotheses[e]) == DUOFORGE_OK);
        }
        DF_CHECK(t, duoforge_batch_from_view(b, views, hypotheses, 16u, statuses) == DUOFORGE_OK);
        players[15] = 2u;
        memset(statuses, 0x55, sizeof statuses);
        DF_CHECK(t, duoforge_batch_public(b, players, views, statuses) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, statuses[0] == 0x55555555u);
        DF_CHECK(t, duoforge_batch_from_view(b, views, hypotheses, 17u, statuses) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, statuses[0] == 0x55555555u);
        hypotheses[3].revision = 999u;
        DF_CHECK(t, duoforge_batch_from_view(b, views, hypotheses, 16u, statuses) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(t, statuses[3] == DUOFORGE_E_SCHEMA_MISMATCH && statuses[4] == DUOFORGE_OK);
        DF_CHECK(t, duoforge_batch_from_view(b, NULL, NULL, 0u, NULL) == DUOFORGE_OK);
        duoforge_batch_destroy(b);
    }
    duoforge_context_destroy(ctx);
}

static void test_early_pivot_information_boundary(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup setup;
    (void)duoforge_reference_setup(0u, &setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    duoforge_request rq[2];
    duoforge_factored_domain domains[2];
    duoforge_factored_choice choices[2] = {0};
    for (uint32_t p = 0u; p < 2u; ++p) {
        DF_CHECK(t, duoforge_battle_request(ctx, b, p, &rq[p]) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, b, p, &domains[p]) == DUOFORGE_OK);
        for (uint32_t i = 0u; i < 4u; ++i) {
            choices[p].picks[i] = (uint8_t)i;
        }
    }
    duoforge_decision_bundle bundle;
    DF_CHECK(t, build_bundle(rq, domains, choices, &bundle));
    duoforge_step_result result;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bundle, &result) == DUOFORGE_OK);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    b->request_mask = 1u;
    ++b->request_epoch;
    b->sides[0].requested_slots = 1u;
    b->sides[1].requested_slots = 0u;
    b->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    const uint32_t actor = b->sides[1].positions[0].activation_id;
    const dfi_queue_record move = {actor, (uint8_t)DFI_Q_MOVE, 1u, 0u, 0u, 0u, 0u};
    const dfi_queue_record residual = {0u, (uint8_t)DFI_Q_RESIDUAL, 0u, 0u, 0u, 0u, 0u};
    b->turn = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            b->sides[side].positions[slot].move_actions = 2u;
        }
    }
    b->queue_len = 2u;
    b->queue[0] = move;
    b->queue[1] = residual;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_public_state v;
    memset(&v, 0x55, sizeof v);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &v) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, v.revision == 0x55555555u);
    /* Same public pre-move facts, a hidden Mega declaration in the queue. */
    b->queue_len = 3u;
    b->queue[0] = (dfi_queue_record){actor, (uint8_t)DFI_Q_MEGA, 1u, 0u, 0u, 0u, 0u};
    b->queue[1] = move;
    b->queue[2] = residual;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &v) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, v.revision == 0x55555555u);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* A PIVOT after a public Protect, the foe's lead (side 1, position 0) still to move when `pending`; `flinch` sets the
 * silent flinch volatile on that lead (a secondary's roll, never shown until its [cant] line). */
static duoforge_battle *flinch_pivot(df_test *t, const duoforge_context *ctx, bool pending, bool flinch)
{
    duoforge_battle_setup setup;
    (void)duoforge_reference_setup(0u, &setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    duoforge_request rq[2];
    duoforge_factored_domain domains[2];
    duoforge_factored_choice choices[2] = {0};
    for (uint32_t p = 0u; p < 2u; ++p) {
        DF_CHECK(t, duoforge_battle_request(ctx, b, p, &rq[p]) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, b, p, &domains[p]) == DUOFORGE_OK);
        for (uint32_t i = 0u; i < 4u; ++i) {
            choices[p].picks[i] = (uint8_t)i;
        }
    }
    duoforge_decision_bundle bundle;
    DF_CHECK(t, build_bundle(rq, domains, choices, &bundle));
    duoforge_step_result result;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bundle, &result) == DUOFORGE_OK);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    b->request_mask = 1u;
    ++b->request_epoch;
    b->sides[0].requested_slots = 1u;
    b->sides[1].requested_slots = 0u;
    b->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    b->sides[0].positions[1].flags = (uint8_t)DFI_VOL_PROTECT; /* the moves of this turn have started, publicly */
    b->turn = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            b->sides[side].positions[slot].move_actions = 2u;
        }
    }
    const uint32_t actor = b->sides[1].positions[0].activation_id;
    b->queue_len = 0u;
    if (pending) {
        b->queue[b->queue_len++] = (dfi_queue_record){actor, (uint8_t)DFI_Q_MOVE, 1u, 0u, 0u, 0u, 0u};
    }
    b->queue[b->queue_len++] = (dfi_queue_record){0u, (uint8_t)DFI_Q_RESIDUAL, 0u, 0u, 0u, 0u, 0u};
    if (flinch) {
        b->sides[1].positions[0].flags = (uint8_t)(b->sides[1].positions[0].flags | DFI_VOL_FLINCH);
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}

/* Information safety of the silent flinch (view audit 2026-10-10): whether a secondary's flinch landed is hidden from both
 * players until the flinched Pokemon tries to move. A record with a position still to move is refused (no public fact tells
 * whether a flinch is outstanding on it); with none left the flinch has no effect and the record does not carry it. */
static void test_flinch_information_safety(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    for (uint32_t pending = 0u; pending < 2u; ++pending) {
        duoforge_public_state v[2];
        duoforge_status st[2][2];
        for (uint32_t flinch = 0u; flinch < 2u; ++flinch) {
            duoforge_battle *b = flinch_pivot(t, ctx, pending != 0u, flinch != 0u);
            for (uint32_t p = 0u; p < 2u; ++p) {
                memset(&v[flinch], 0x55, sizeof v[flinch]);
                st[flinch][p] = duoforge_battle_public(ctx, b, p, &v[flinch]);
            }
            duoforge_battle_destroy(b);
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            DF_CHECK(t, st[0][p] == st[1][p]);
            DF_CHECK(t, st[0][p] == (pending != 0u ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK));
        }
        if (pending == 0u) { /* the last player's records (p = 1) of both battles */
            DF_CHECK(t, v[0].state_size == v[1].state_size && memcmp(v[0].state, v[1].state, v[0].state_size) == 0);
        }
    }
    duoforge_context_destroy(ctx);
}

static void test_counter_information_safety(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup setup;
    (void)duoforge_reference_setup(0u, &setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    duoforge_request rq[2];
    duoforge_factored_domain d[2];
    duoforge_factored_choice c[2] = {0};
    for (uint32_t p = 0u; p < 2u; ++p) {
        DF_CHECK(t, duoforge_battle_request(ctx, b, p, &rq[p]) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_factored(ctx, b, p, &d[p]) == DUOFORGE_OK);
        for (uint32_t k = 0u; k < d[p].pick_count; ++k) {
            c[p].picks[k] = (uint8_t)k;
        }
    }
    duoforge_decision_bundle bundle;
    DF_CHECK(t, build_bundle(rq, d, c, &bundle));
    duoforge_step_result result;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bundle, &result) == DUOFORGE_OK);
    duoforge_public_state normal;
    duoforge_hypothesis h;
    DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &normal) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
    const struct duoforge_battle original = *b;
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t counter = 1u; counter <= 3u; ++counter) {
            *b = original;
            const uint32_t member = b->sides[side].positions[0].occupant;
            b->sides[side].members[member].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
            b->sides[side].members[member].status_counter = (uint8_t)counter;
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_public_state untouched;
                memset(&untouched, 0x55, sizeof untouched);
                DF_CHECK(t, duoforge_battle_public(ctx, b, p, &untouched) == DUOFORGE_E_UNSUPPORTED);
                DF_CHECK(t, untouched.revision == 0x55555555u);
            }
        }
        for (uint32_t counter = 1u; counter <= 5u; ++counter) {
            *b = original;
            b->sides[side].positions[0].confusion_turns = (uint8_t)counter;
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_public_state untouched;
                memset(&untouched, 0x55, sizeof untouched);
                DF_CHECK(t, duoforge_battle_public(ctx, b, p, &untouched) == DUOFORGE_E_UNSUPPORTED);
                DF_CHECK(t, untouched.revision == 0x55555555u);
            }
        }
    }
    *b = original;
    /* Even a caller-supplied masked record cannot bypass the support gate. */
    normal.state[DFI_ENC_SIDE_OFF + DFI_ENC_SIDE_MEMBERS_OFF + DFI_ENC_MEMBER_STATUS_OFF] = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    normal.state[DFI_ENC_SIDE_OFF + DFI_ENC_SIDE_MEMBERS_OFF + DFI_ENC_MEMBER_STATUS_COUNTER_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
    DF_CHECK(t, duoforge_battle_from_view(ctx, &normal, &h, b) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, memcmp(b, &original, sizeof original) == 0);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}


int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.view");
    test_uniforms(&t);
    test_arguments(&t);
    test_counter_information_safety(&t);
    test_batch(&t);
    test_early_pivot_information_boundary(&t);
    test_flinch_information_safety(&t);
    test_party_order_information_safety(&t);
    tally closure = {0};
    tally team_c = {0};
    tally pool = {0};
    play(&t, &df_config_k1, "ABBAAABB", GAMES, 0x2026100400000001u, &closure);
    play(&t, &df_config_team_c, "ACCBCCBA", GAMES, 0x2026100400000002u, &team_c);
    play(&t, &df_config_pool, "CABCCCAB", GAMES, 0x2026100400000003u, &pool);
    printf("closure: %u states, %u views, %u unsupported\n", closure.states, closure.checked, closure.unsupported);
    printf("team_c: %u states, %u views, %u unsupported\n", team_c.states, team_c.checked, team_c.unsupported);
    printf("pool: %u states, %u views, %u unsupported\n", pool.states, pool.checked, pool.unsupported);
    printf("hidden: %u sleep, %u confusion, %u charging target\n", closure.sleeping + team_c.sleeping + pool.sleeping,
           closure.confused + team_c.confused + pool.confused, closure.charging + team_c.charging + pool.charging);
    printf("worlds refused for a flagged display: %u\n", closure.contradicted + team_c.contradicted + pool.contradicted);
    DF_CHECK(&t, closure.checked > 0u && team_c.checked > 0u && pool.checked > 0u);
    printf("queue masks: %u sound, %u explicitly unsupported\n", masks_checked, masks_refused);
    /* Since the view audit of 2026-10-10 a PIVOT with a queued move left is refused (a silent flinch may be outstanding on
     * it), so no public record carries a foe's pending command: the masks checked are those of PIVOTs with no move left
     * (20 sound and 32 refused before), and no world varies a queued command. */
    DF_CHECK(&t, masks_checked == 6u && masks_refused == 6u);
    DF_CHECK(&t, varied_picks > 0u && varied_commands == 0u);
    return df_test_end(&t);
}
