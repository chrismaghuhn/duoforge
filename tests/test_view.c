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
#include "state/knowledge.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/request.h"

#define GAMES 80u
#define MAX_STEPS 400u
#define WORLDS 4u
#define RNG_OFF 52u
#define RNG_SIZE 24u
#define DFI_POSITIONS_MR_TEST 4u /* the flat positions of the move result check */

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
        /* the observation's part of the one predicate (duoforge_observation_causes) is the battle's mask but for the bits the
         * observation does not carry (a Substitute, a temporary forme, the foe's disguise state) */
        {
            duoforge_observation seen;
            uint32_t from_view = 0xFFFFFFFFu;
            uint32_t from_battle = 0xFFFFFFFFu;
            DF_CHECK(t, duoforge_battle_observe(ctx, b, p, &seen) == DUOFORGE_OK);
            DF_CHECK(t, duoforge_observation_causes(ctx, &seen, &from_view) == DUOFORGE_OK);
            DF_CHECK(t, duoforge_battle_public_causes(ctx, b, p, &from_battle) == DUOFORGE_OK);
            const uint32_t battle_only = DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE | DUOFORGE_PUBLIC_CAUSE_TEMP_FORME |
                                         DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE;
            DF_CHECK(t, (from_view & ~from_battle) == 0u && (from_battle & ~from_view & ~battle_only) == 0u);
        }
        if (st != DUOFORGE_OK) {
            ++ty->unsupported;
            continue;
        }
        ++ty->checked;
        /* the engine's verdict on a record (duoforge_public_record_check): its own records come back; a masked field filled
         * (the foe's exact HP of its first member) does not */
        DF_CHECK(t, duoforge_public_record_check(ctx, &view) == DUOFORGE_OK);
        {
            duoforge_public_state bad = view;
            uint8_t *hp = bad.state + DFI_ENC_SIDE_OFF + (p ^ 1u) * DFI_ENC_SIDE_SIZE + DFI_ENC_SIDE_MEMBERS_OFF + DFI_ENC_MEMBER_HP_OFF;
            hp[0] = (uint8_t)(hp[0] ^ 1u);
            DF_CHECK(t, duoforge_public_record_check(ctx, &bad) == DUOFORGE_E_MALFORMED);
        }
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

/* The differential check of duoforge_move_result against the engine (POOL play): the events of each step are cut into
 * move actions as the live tracker cuts them (python/duoforge_live/tracker.py _segment, _pre_action, _end_action), each
 * action is classified by the library, and after the step every standing position's tail move_result must hold what the
 * classifications say, this turn's and last turn's. A status move whose engine result the classifier gets wrong (a new
 * handler of the generic special, say) fails here instead of going silently into a record. An action the library refuses
 * (E_UNSUPPORTED) leaves its slot unknown until the next turn shift brings a known one. A status move whose targets include
 * a Substitute's holder is not asked (counted by reason): its blocked run prints a failed one's lines and is true at the pin,
 * which the events cannot tell (duoforge_move_result's precondition; the live tracker stops at a Substitute). The targets
 * are the move line's named one, or for a [still] line (which hides it) every position its target class can name, or the
 * positions a spread class reaches; a field or side move is never taken by a Substitute. */
typedef struct mr_track {
    uint8_t now[DFI_POSITIONS_MR_TEST];
    uint8_t last[DFI_POSITIONS_MR_TEST];
    bool known_now[DFI_POSITIONS_MR_TEST];
    bool known_last[DFI_POSITIONS_MR_TEST];
    bool fainted[DFI_POSITIONS_MR_TEST];
    uint32_t entries[DFI_POSITIONS_MR_TEST]; /* switches, drags and faints at the position: a changed occupant */
    bool sub[DFI_POSITIONS_MR_TEST];         /* a Substitute stands at the position */
} mr_track;

static uint32_t mr_classified;
static uint32_t mr_unclassified;
static uint32_t mr_compared;
static uint32_t mr_sub_named;  /* not asked: the named target holds a Substitute */
static uint32_t mr_sub_hidden; /* not asked: a [still] line hides the target, and a position it may name holds one */
static uint32_t mr_sub_spread; /* not asked: a position the spread move reaches holds one */

/* The positions other than `user` that a move of target class `cls` may hit (a field or side class: none). */
static uint32_t mr_class_reach(uint32_t user, uint32_t cls, bool *single)
{
    const uint32_t ally = 1u << (user ^ 1u);
    const uint32_t foes = user < 2u ? 0xCu : 0x3u;
    *single = true;
    switch (cls) {
    case DUOFORGE_TARGET_CLASS_NORMAL:
    case DUOFORGE_TARGET_CLASS_ANY:
    case DUOFORGE_TARGET_CLASS_RANDOM_NORMAL:
    case DUOFORGE_TARGET_CLASS_SCRIPTED:
        return ally | foes;
    case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY:
    case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF:
        return ally;
    case DUOFORGE_TARGET_CLASS_ADJACENT_FOE:
        return foes;
    case DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES:
        *single = false;
        return foes;
    case DUOFORGE_TARGET_CLASS_ALL_ADJACENT:
    case DUOFORGE_TARGET_CLASS_ALLIES:
        *single = false;
        return cls == DUOFORGE_TARGET_CLASS_ALLIES ? ally : ally | foes;
    default:
        *single = false;
        return 0u; /* self, a side, the field, the party: no Substitute takes them */
    }
}

/* The Substitutes of the state before a step (the tail), which the step's events then start and end. */
static void mr_subs_from(const duoforge_battle *b, mr_track *tr)
{
    for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
        tr->sub[p] = b->tail.sides[p / 2u].positions[p % 2u].substitute_hp != 0u;
    }
}

static void mr_clear(mr_track *tr, uint32_t pos)
{
    tr->now[pos] = 0u;
    tr->last[pos] = 0u;
    tr->known_now[pos] = true;
    tr->known_last[pos] = true;
}

static void mr_set(df_test *t, const duoforge_context *ctx, mr_track *tr, uint32_t pos, const duoforge_event *ev,
                   uint32_t n)
{
    uint8_t out = 0u;
    const duoforge_status st = duoforge_move_result(ctx, pos, ev, n, &out);
    DF_CHECK(t, st == DUOFORGE_OK || st == DUOFORGE_E_UNSUPPORTED);
    tr->known_now[pos] = st == DUOFORGE_OK;
    tr->now[pos] = out;
    if (st == DUOFORGE_OK) {
        ++mr_classified;
    } else {
        ++mr_unclassified;
    }
}

/* The result of the action ev[start, end) of `pos` (its user still the one that began it, not fainted), and of a run
 * that Magic Bounce reflected inside it, for the holder. */
static void mr_end_action(df_test *t, const duoforge_context *ctx, mr_track *tr, const duoforge_event *ev, uint32_t start,
                          uint32_t end, uint32_t pos, uint32_t entry, uint32_t subs)
{
    uint32_t *reason = NULL;
    for (uint32_t j = start; j < end; ++j) {
        const duoforge_event *mv = &ev[j];
        if (mv->kind != DUOFORGE_EVENT_MOVE || mv->position != pos || mv->id >= DFI_POOL_MOVE_COUNT) {
            continue;
        }
        const dfi_move_data *md = &dfi_pool_moves[mv->id];
        if (md->category == DFI_CATEGORY_STATUS) {
            bool single = false;
            const uint32_t reach = mr_class_reach(pos, md->target_class, &single);
            const bool named = single && mv->other < DFI_POSITIONS_MR_TEST;
            const uint32_t targets = named ? (1u << mv->other) & reach : reach;
            if ((targets & subs) != 0u) {
                reason = named ? &mr_sub_named : single ? &mr_sub_hidden : &mr_sub_spread;
            }
        }
        break;
    }
    if (reason != NULL) {
        tr->known_now[pos] = false; /* not asked: duoforge_move_result's precondition */
        ++*reason;
    } else if (tr->entries[pos] == entry && !tr->fainted[pos]) {
        mr_set(t, ctx, tr, pos, &ev[start], end - start);
    }
    for (uint32_t j = start; j < end; ++j) {
        const uint32_t h = ev[j].position;
        if (ev[j].kind == DUOFORGE_EVENT_MOVE && ev[j].cause == DUOFORGE_CAUSE_ABILITY && h < DFI_POSITIONS_MR_TEST &&
            !tr->fainted[h]) {
            mr_set(t, ctx, tr, h, &ev[j], end - j);
        }
    }
}

/* The last event of ev[start, end) is a line of `pos` that comes before its action's first line (_pre_action). */
static bool mr_pre_action(const duoforge_event *ev, uint32_t start, uint32_t end, uint32_t pos)
{
    const duoforge_event *e = &ev[end - 1u];
    if (e->position != pos) {
        return false;
    }
    if (end - 1u > start && ev[end - 2u].kind == DUOFORGE_EVENT_ITEM_END && ev[end - 2u].position == pos) {
        return false;
    }
    return (e->kind == DUOFORGE_EVENT_CURE_STATUS && (e->flags & DUOFORGE_EVENT_FLAG_MESSAGE) != 0u &&
            e->cause == DUOFORGE_CAUSE_NONE) ||
           e->kind == DUOFORGE_EVENT_CONFUSION_END ||
           (e->kind == DUOFORGE_EVENT_ACTIVATE && e->cause == DUOFORGE_CAUSE_MOVE && e->id2 == DFI_MOVE_STRUGGLE);
}

static void mr_step(df_test *t, const duoforge_context *ctx, mr_track *tr, const duoforge_event *ev, uint32_t n)
{
    bool open = false;
    bool confused = false;
    uint32_t start = 0u;
    uint32_t user = 0u;
    uint32_t entry = 0u;
    uint32_t subs = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        const duoforge_event *e = &ev[i];
        const uint32_t pos = e->position;
        if (e->kind == DUOFORGE_EVENT_UPKEEP || e->kind == DUOFORGE_EVENT_TURN) {
            if (open) {
                mr_end_action(t, ctx, tr, ev, start, i, user, entry, subs);
                open = false;
            }
            if (e->kind == DUOFORGE_EVENT_TURN) {
                for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
                    tr->last[p] = tr->now[p];
                    tr->known_last[p] = tr->known_now[p];
                    tr->now[p] = 0u;
                    tr->known_now[p] = true;
                }
            }
            continue;
        }
        const bool starts = pos < DFI_POSITIONS_MR_TEST &&
                            ((e->kind == DUOFORGE_EVENT_MOVE && e->cause == DUOFORGE_CAUSE_NONE) ||
                             e->kind == DUOFORGE_EVENT_CONFUSED ||
                             (e->kind == DUOFORGE_EVENT_CANT && e->cause != DUOFORGE_CAUSE_ABILITY));
        if (starts && open && user == pos && confused && e->kind != DUOFORGE_EVENT_CONFUSED) {
            confused = false; /* the move the confusion line let through, or its [cant] */
        } else if (starts) {
            uint32_t first = i;
            while (open && first > start && mr_pre_action(ev, start, first, pos)) {
                --first;
            }
            if (open) {
                mr_end_action(t, ctx, tr, ev, start, first, user, entry, subs);
            }
            open = true;
            start = first;
            user = pos;
            entry = tr->entries[pos];
            subs = 0u;
            for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
                subs |= tr->sub[p] ? 1u << p : 0u;
            }
            confused = e->kind == DUOFORGE_EVENT_CONFUSED;
        }
        if (pos < DFI_POSITIONS_MR_TEST &&
            (e->kind == DUOFORGE_EVENT_SWITCH || e->kind == DUOFORGE_EVENT_DRAG || e->kind == DUOFORGE_EVENT_FAINT)) {
            tr->entries[pos] += 1u;
            tr->fainted[pos] = e->kind == DUOFORGE_EVENT_FAINT;
            mr_clear(tr, pos); /* the tail of the position is cleared (a new occupant, or the faint) */
            /* Baton Pass hands the Substitute to the one it brings in (dfi_pass_give); any other entry or a faint ends it */
            tr->sub[pos] = tr->sub[pos] && e->kind == DUOFORGE_EVENT_SWITCH && e->cause == DUOFORGE_CAUSE_MOVE &&
                           e->id2 == DFI_MOVE_BATONPASS;
        }
        if (pos < DFI_POSITIONS_MR_TEST && (e->kind == DUOFORGE_EVENT_VOLATILE_START || e->kind == DUOFORGE_EVENT_VOLATILE_END) &&
            e->detail == DUOFORGE_VOLATILE_SUBSTITUTE) {
            tr->sub[pos] = e->kind == DUOFORGE_EVENT_VOLATILE_START;
        }
    }
    if (open) {
        mr_end_action(t, ctx, tr, ev, start, n, user, entry, subs);
    }
}

/* The known deviations of the engine from the pin that the check finds, each listed with its issue, never left out silently:
 * the check counts the slots that differ as listed, and fails when a listed slot no longer differs (the engine is fixed: drop
 * the entry) or another one does. `last` names the slot of last turn's result, else this turn's. */
typedef struct mr_known_slot {
    const char *battle;
    uint32_t step; /* the recorded step after which the slot is compared */
    uint32_t pos;
    bool last;
    uint32_t engine;   /* the engine's value of the slot (this turn's form: the unclassified bit as UNCLASSIFIED_NOW) */
    uint32_t expected; /* the classified value, the pin's */
} mr_known_slot;

/* No known deviation is left: the issue #389 (a Baton Pass without a reserve left its result unclassified) is fixed, and the
 * entries that listed it (the four of the first merge and the thirty of the move-result corpus) are removed. The sentinel keeps the array non-empty; the count excludes it. */
static const mr_known_slot MR_KNOWN[] = {
    {NULL, 0u, 0u, false},
};
#define MR_KNOWN_COUNT (sizeof MR_KNOWN / sizeof MR_KNOWN[0] - 1u)

static const char *mr_name = "playout"; /* the recorded battle being replayed, or the playouts */
static uint32_t mr_step_index;
static uint32_t mr_known_seen;

/* The slot equals the classifications, or differs as a known deviation lists (counted). */
static void mr_slot(df_test *t, uint32_t pos, bool last, uint32_t engine, uint32_t expected)
{
    if (engine == expected) {
        return;
    }
    for (size_t k = 0u; k + 1u < sizeof MR_KNOWN / sizeof MR_KNOWN[0]; ++k) { /* the sentinel is not an entry */
        const mr_known_slot *e = &MR_KNOWN[k];
        if (strcmp(e->battle, mr_name) == 0 && e->step == mr_step_index && e->pos == pos && e->last == last) {
            /* a half fix or another wrong value is no longer the listed deviation */
            DF_CHECK(t, engine == e->engine && expected == e->expected);
            mr_known_seen += engine == e->engine && expected == e->expected ? 1u : 0u;
            return;
        }
    }
    printf("move result differs: %s step %u position %u %s slot: engine %u, classified %u\n", mr_name, mr_step_index, pos,
           last ? "last turn's" : "this turn's", engine, expected);
    DF_CHECK(t, engine == expected);
}

static void mr_compare(df_test *t, const duoforge_battle *b, const mr_track *tr)
{
    for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
        const uint32_t occupant = b->sides[p / 2u].positions[p % 2u].occupant;
        if (occupant >= DUOFORGE_MAX_ROSTER || b->sides[p / 2u].members[occupant].hp == 0u) {
            continue;
        }
        const uint32_t mr = b->tail.sides[p / 2u].positions[p % 2u].move_result;
        if (tr->known_now[p]) {
            mr_slot(t, p, false, mr & (DFI_MOVE_RESULT_VALUE_MASK | DFI_MOVE_RESULT_UNCLASSIFIED_NOW), tr->now[p]);
            ++mr_compared;
        }
        if (tr->known_last[p]) {
            const uint32_t last = ((mr >> DFI_MOVE_RESULT_LAST_SHIFT) & DFI_MOVE_RESULT_VALUE_MASK) |
                                  ((mr & DFI_MOVE_RESULT_UNCLASSIFIED_LAST) != 0u ? DFI_MOVE_RESULT_UNCLASSIFIED_NOW : 0u);
            mr_slot(t, p, true, last, tr->last[p]);
            ++mr_compared;
        }
    }
}

static duoforge_event mr_events[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_EVENTS];

/* The same differential check over the recorded pool corpus (tests/reference/conformance_pool.h), replayed with its kept draws
 * and recorded commands as the conformance replay does, under POOL or, for the development teams, POOL_DEV: the battles of each
 * new mechanic come with it which the playouts' teams may not reach. */
static void corpus_move_results(df_test *t)
{
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    for (size_t bi = 0u; bi < sizeof conf_battles / sizeof conf_battles[0]; ++bi) {
        const df_conf_battle *cb = &conf_battles[bi];
        duoforge_battle_setup setup;
        memset(&setup, 0, sizeof setup);
        setup.rng_initstate = 1u;
        setup.rng_initseq = 2u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            setup.sides[side].member_count = cb->member_count;
            for (uint32_t m = 0u; m < cb->member_count; ++m) {
                const df_conf_member *src = &cb->members[side][m];
                duoforge_member_setup *dst = &setup.sides[side].members[m];
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
        duoforge_battle *b = NULL;
        const duoforge_context *ctx = kp;
        if (duoforge_battle_create(kp, &setup, &b) != DUOFORGE_OK) {
            ctx = kd;
            if (!DF_CHECK(t, duoforge_battle_create(kd, &setup, &b) == DUOFORGE_OK)) {
                continue;
            }
        }
        mr_track track;
        memset(&track, 0, sizeof track);
        for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
            mr_clear(&track, p);
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
            for (uint32_t side = 0u; side < 2u; ++side) {
                if ((side == 0u && !st->answered0) || (side == 1u && !st->answered1)) {
                    continue;
                }
                duoforge_side_choice *r = &bd.responses[side];
                r->epoch = b->request_epoch;
                r->side = (uint8_t)side;
                if (st->team) {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                    r->pick_count = 4u;
                    for (uint32_t i = 0u; i < 4u; ++i) {
                        r->picks[i] = st->picks[side][i];
                    }
                } else {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                    for (uint32_t k = 0u; k < 2u; ++k) {
                        const df_conf_cmd *c = &st->cmds[side][k];
                        r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
                    }
                }
            }
            duoforge_step_result res;
            uint32_t used = 0u;
            duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{mr_events[0], DUOFORGE_MAX_EVENTS, 0u},
                                                                  {mr_events[1], DUOFORGE_MAX_EVENTS, 0u}};
            mr_subs_from(b, &track);
            if (dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers) !=
                DUOFORGE_OK) {
                break; /* a battle that ends in a recorded refusal (its trace's own last step) */
            }
            mr_name = cb->name;
            mr_step_index = si;
            mr_step(t, ctx, &track, mr_events[0], buffers[0].count);
            mr_compare(t, b, &track);
        }
        duoforge_battle_destroy(b);
    }
    mr_name = "playout";
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
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
        mr_track track;
        memset(&track, 0, sizeof track);
        for (uint32_t p = 0u; p < DFI_POSITIONS_MR_TEST; ++p) {
            mr_clear(&track, p);
        }
        const bool pool_play = config == &df_config_pool;
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
            duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{mr_events[0], DUOFORGE_MAX_EVENTS, 0u},
                                                                  {mr_events[1], DUOFORGE_MAX_EVENTS, 0u}};
            if (pool_play) {
                mr_subs_from(b, &track);
            }
            const duoforge_status st = duoforge_battle_step_events(ctx, b, &bundle, &r, buffers);
            if (st == DUOFORGE_E_UNSUPPORTED) {
                break; /* a mechanic the manifest does not mark: the game ends here */
            }
            DF_CHECK(t, st == DUOFORGE_OK);
            if (st != DUOFORGE_OK) {
                break;
            }
            if (pool_play) {
                mr_step(t, ctx, &track, mr_events[0], buffers[0].count);
                mr_compare(t, b, &track);
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
        static duoforge_public_state v[2][2]; /* [flinch][player] */
        duoforge_status st[2][2];
        for (uint32_t flinch = 0u; flinch < 2u; ++flinch) {
            duoforge_battle *b = flinch_pivot(t, ctx, pending != 0u, flinch != 0u);
            for (uint32_t p = 0u; p < 2u; ++p) {
                memset(&v[flinch][p], 0x55, sizeof v[flinch][p]);
                st[flinch][p] = duoforge_battle_public(ctx, b, p, &v[flinch][p]);
            }
            duoforge_battle_destroy(b);
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            DF_CHECK(t, st[0][p] == st[1][p]);
            DF_CHECK(t, st[0][p] == (pending != 0u ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK));
        }
        for (uint32_t p = 0u; pending == 0u && p < 2u; ++p) { /* both players' records, the flinched foe's and its owner's */
            DF_CHECK(t, memcmp(&v[0][p], &v[1][p], sizeof v[0][p]) == 0);
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


/* duoforge_hp_display: the engine's HP display (the knowledge fold's dfi_hp_display) for every exact HP of a range of maxima,
 * the documented edge values, and the argument checks with nothing written on a refusal. */
static void test_hp_display(df_test *t)
{
    for (uint32_t hp_max = 1u; hp_max <= 400u; ++hp_max) {
        for (uint32_t hp = 0u; hp <= hp_max; ++hp) {
            uint8_t want_pc = 0u;
            uint8_t want_fl = 0u;
            dfi_hp_display(hp, hp_max, &want_pc, &want_fl);
            uint8_t pc = 0xAAu;
            uint8_t fl = 0xAAu;
            if (!DF_CHECK(t, duoforge_hp_display(hp, hp_max, &pc, &fl) == DUOFORGE_OK) ||
                !DF_CHECK(t, pc == want_pc && fl == want_fl)) {
                return;
            }
        }
    }
    uint8_t pc = 0u;
    uint8_t fl = 0u;
    DF_CHECK(t, duoforge_hp_display(1u, 181u, &pc, &fl) == DUOFORGE_OK && pc == 1u && fl == DUOFORGE_HP_FLAG_NONE);
    DF_CHECK(t, duoforge_hp_display(0u, 181u, &pc, &fl) == DUOFORGE_OK && pc == 0u && fl == DUOFORGE_HP_FLAG_NONE);
    DF_CHECK(t, duoforge_hp_display(181u, 181u, &pc, &fl) == DUOFORGE_OK && pc == 100u);
    DF_CHECK(t, duoforge_hp_display(150u, 193u, &pc, &fl) == DUOFORGE_OK && pc == 77u); /* the record of m5_real_aa_1 */
    DF_CHECK(t, duoforge_hp_display(20u, 100u, &pc, &fl) == DUOFORGE_OK && pc == 20u && fl == DUOFORGE_HP_FLAG_RED);
    DF_CHECK(t, duoforge_hp_display(41u, 201u, &pc, &fl) == DUOFORGE_OK && pc == 20u && fl == DUOFORGE_HP_FLAG_YELLOW);
    DF_CHECK(t, duoforge_hp_display(50u, 100u, &pc, &fl) == DUOFORGE_OK && pc == 50u && fl == DUOFORGE_HP_FLAG_YELLOW);
    DF_CHECK(t, duoforge_hp_display(101u, 201u, &pc, &fl) == DUOFORGE_OK && pc == 50u && fl == DUOFORGE_HP_FLAG_GREEN);
    pc = 0x55u;
    fl = 0x55u;
    DF_CHECK(t, duoforge_hp_display(1u, 2u, NULL, &fl) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_hp_display(1u, 2u, &pc, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_hp_display(0u, 0u, &pc, &fl) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_hp_display(3u, 2u, &pc, &fl) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_hp_display(1u, 0x10000u, &pc, &fl) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, pc == 0x55u && fl == 0x55u);
}

/* An event of the move-result tests. */
static duoforge_event mr_ev(uint8_t kind, uint8_t position, uint8_t other, uint8_t cause, uint16_t id, uint16_t id2)
{
    duoforge_event e;
    memset(&e, 0, sizeof e);
    e.kind = kind;
    e.position = position;
    e.other = other;
    e.cause = cause;
    e.id = id;
    e.id2 = id2;
    return e;
}

static uint8_t mr_of(df_test *t, const duoforge_context *ctx, uint32_t user, const duoforge_event *ev, uint32_t n)
{
    uint8_t out = 0xAAu;
    if (!DF_CHECK(t, duoforge_move_result(ctx, user, ev, n, &out) == DUOFORGE_OK)) {
        return 0xAAu;
    }
    return out;
}

/* duoforge_move_result: the classes of the engine's rule on hand-built actions (the corpus comparison is the live test's,
 * duoforge.python.live), the unclassified bit, the refusals with nothing written, the argument checks. */
static void test_move_result(df_test *t)
{
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *k1 = df_make_context(&df_config_k1);
    const uint8_t none = (uint8_t)DUOFORGE_NO_POSITION;
    duoforge_event ev[6];
    /* a [cant] (paralysis): false; the recharge turn: null */
    ev[0] = mr_ev(DUOFORGE_EVENT_CANT, 1u, none, DUOFORGE_CAUSE_PARALYSIS, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 1u) == DFI_MOVE_RESULT_FALSE);
    ev[0].cause = DUOFORGE_CAUSE_RECHARGE;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 1u) == DFI_MOVE_RESULT_NULL);
    /* a damaging move: a hit target true; a miss false; Protect null; a hit and a protected target: true */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 0u, 2u, DUOFORGE_CAUSE_NONE, DFI_MOVE_THUNDERBOLT, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_DAMAGE, 2u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    ev[1] = mr_ev(DUOFORGE_EVENT_MISS, 0u, 2u, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 2u) == DFI_MOVE_RESULT_FALSE);
    ev[1] = mr_ev(DUOFORGE_EVENT_BLOCKED, 2u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 2u) == DFI_MOVE_RESULT_NULL);
    ev[2] = mr_ev(DUOFORGE_EVENT_DAMAGE, 3u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 3u) == DFI_MOVE_RESULT_TRUE);
    /* an absorbing ability (Lightning Rod's -ability, then its boost): false, the boost is no hit */
    ev[1] = mr_ev(DUOFORGE_EVENT_ABILITY, 2u, none, DUOFORGE_CAUSE_NONE, 0u, (uint16_t)(1u + DFI_ABILITY_LIGHTNINGROD));
    ev[2] = mr_ev(DUOFORGE_EVENT_BOOST, 2u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[2].amount = 1u;
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 3u) == DFI_MOVE_RESULT_FALSE);
    /* a self boost: true when a stage rose, false at +6 (a boost of 0) */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, 1u, DUOFORGE_CAUSE_NONE, DFI_MOVE_SWORDSDANCE, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_BOOST, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[1].amount = 2u;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    ev[1].amount = 0u;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_FALSE);
    /* a status cured in the same action (a Lum Berry): the status did not change, false */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 3u, 0u, DUOFORGE_CAUSE_NONE, DFI_MOVE_WILLOWISP, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_STATUS, 0u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 3u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    ev[2] = mr_ev(DUOFORGE_EVENT_CURE_STATUS, 0u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 3u, ev, 3u) == DFI_MOVE_RESULT_FALSE);
    /* Haze sets no class: the unclassified bit alone */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 0u, none, DUOFORGE_CAUSE_NONE, DFI_MOVE_HAZE, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_CLEAR_ALL_BOOSTS, none, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 0u, ev, 2u) == DFI_MOVE_RESULT_UNCLASSIFIED_NOW);
    /* Baneful Bunker (G94a, dfi_run_protect): its -singleturn Protect, true; the stall fail (-fail with [still]) false */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, 1u, DUOFORGE_CAUSE_NONE, DFI_MOVE_BANEFULBUNKER, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_PROTECT, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    ev[0].flags = DUOFORGE_EVENT_FLAG_STILL;
    ev[1] = mr_ev(DUOFORGE_EVENT_FAIL, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_FALSE);
    /* Imprison: its volatile on the user, true; a second one (-fail with [still], dfi_run_imprison) false */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, 1u, DUOFORGE_CAUSE_NONE, DFI_MOVE_IMPRISON, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_VOLATILE_START, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[1].detail = (uint8_t)DUOFORGE_VOLATILE_IMPRISON;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    ev[0].flags = DUOFORGE_EVENT_FLAG_STILL;
    ev[1] = mr_ev(DUOFORGE_EVENT_FAIL, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_FALSE);
    /* a [still] -fail: false; the lines of another position before the action are skipped */
    ev[0] = mr_ev(DUOFORGE_EVENT_DAMAGE, 3u, none, DUOFORGE_CAUSE_POISON, 0u, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, none, DUOFORGE_CAUSE_NONE, DFI_MOVE_TAILWIND, 0u);
    ev[1].flags = DUOFORGE_EVENT_FLAG_STILL;
    ev[2] = mr_ev(DUOFORGE_EVENT_FAIL, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 3u) == DFI_MOVE_RESULT_FALSE);
    /* the residual's events after the turn's last action are not the move's (found by the playouts below): a screen's
     * end, the weather's end, a Perish count, Yawn's sleep; Trick Room's own end by the Trick Room move is */
    ev[3] = mr_ev(DUOFORGE_EVENT_SIDE_END, none, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[4] = mr_ev(DUOFORGE_EVENT_WEATHER, none, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[5] = mr_ev(DUOFORGE_EVENT_VOLATILE_START, 2u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[5].detail = (uint8_t)DUOFORGE_VOLATILE_PERISH;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 6u) == DFI_MOVE_RESULT_FALSE);
    ev[5] = mr_ev(DUOFORGE_EVENT_STATUS, 2u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[5].detail = (uint8_t)DFI_STATUS_SLP;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 6u) == DFI_MOVE_RESULT_FALSE);
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, none, DUOFORGE_CAUSE_NONE, DFI_MOVE_TRICKROOM, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_FIELD_END, none, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[1].detail = (uint8_t)DUOFORGE_FIELD_TRICK_ROOM;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 2u) == DFI_MOVE_RESULT_TRUE);
    /* a stage change an ability announces (Moody's -ability|X|Moody|boost in the residual) is the ability's: a failed
     * Swords Dance stays false */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 1u, 1u, DUOFORGE_CAUSE_NONE, DFI_MOVE_SWORDSDANCE, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_BOOST, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[1].amount = 0u;
    ev[2] = mr_ev(DUOFORGE_EVENT_ABILITY, 0u, none, DUOFORGE_CAUSE_NONE, 0u, (uint16_t)(1u + DFI_ABILITY_MOODY));
    ev[3] = mr_ev(DUOFORGE_EVENT_BOOST, 0u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[3].amount = 2u;
    ev[4] = mr_ev(DUOFORGE_EVENT_UNBOOST, 0u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[4].amount = 1u;
    DF_CHECK(t, mr_of(t, kp, 1u, ev, 5u) == DFI_MOVE_RESULT_FALSE);
    /* a damaging hit that a Substitute takes is a hit (-activate|X|Substitute|[damage]), beside a protected target: true */
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 2u, none, DUOFORGE_CAUSE_NONE, DFI_MOVE_THUNDERBOLT, 0u);
    ev[1] = mr_ev(DUOFORGE_EVENT_BLOCKED, 0u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[2] = mr_ev(DUOFORGE_EVENT_ACTIVATE, 1u, none, DUOFORGE_CAUSE_MOVE, 0u, (uint16_t)DFI_MOVE_SUBSTITUTE);
    DF_CHECK(t, mr_of(t, kp, 2u, ev, 3u) == DFI_MOVE_RESULT_TRUE);
    DF_CHECK(t, mr_of(t, kp, 2u, ev, 2u) == DFI_MOVE_RESULT_NULL);
    /* the hit that breaks the Substitute shows only its -end (VOLATILE_END, cause NONE, dfi_substitute_takes): a hit too
     * (HIT_SUBSTITUTE), so a spread move with one target protected and the other's Substitute broken is true */
    ev[0].flags = DUOFORGE_EVENT_FLAG_SPREAD;
    ev[2] = mr_ev(DUOFORGE_EVENT_VOLATILE_END, 1u, none, DUOFORGE_CAUSE_NONE, 0u, 0u);
    ev[2].detail = (uint8_t)DUOFORGE_VOLATILE_SUBSTITUTE;
    DF_CHECK(t, mr_of(t, kp, 2u, ev, 3u) == DFI_MOVE_RESULT_TRUE);
    /* refusals, nothing written: a handler not mapped (Substitute), no action of the user, a context without the tail */
    uint8_t out = 0x55u;
    ev[0] = mr_ev(DUOFORGE_EVENT_MOVE, 0u, 0u, DUOFORGE_CAUSE_NONE, DFI_MOVE_SUBSTITUTE, 0u);
    DF_CHECK(t, duoforge_move_result(kp, 0u, ev, 1u, &out) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_move_result(kp, 2u, ev, 1u, &out) == DUOFORGE_E_UNSUPPORTED);
    ev[0] = mr_ev(DUOFORGE_EVENT_CANT, 1u, none, DUOFORGE_CAUSE_PARALYSIS, 0u, 0u);
    DF_CHECK(t, duoforge_move_result(k1, 1u, ev, 1u, &out) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, duoforge_move_result(kp, 1u, ev, 0u, &out) == DUOFORGE_E_UNSUPPORTED);
    /* the argument checks */
    DF_CHECK(t, duoforge_move_result(NULL, 1u, ev, 1u, &out) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_move_result(kp, 1u, NULL, 1u, &out) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_move_result(kp, 1u, ev, 1u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_move_result(kp, 4u, ev, 1u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, out == 0x55u);
    /* the argument checks of the two predicate calls */
    duoforge_observation o;
    memset(&o, 0, sizeof o);
    uint32_t mask = 0x55u;
    DF_CHECK(t, duoforge_observation_causes(NULL, &o, &mask) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_observation_causes(kp, NULL, &mask) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_observation_causes(kp, &o, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    o.player = 2u;
    DF_CHECK(t, duoforge_observation_causes(kp, &o, &mask) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, mask == 0x55u);
    duoforge_public_state rec;
    memset(&rec, 0, sizeof rec);
    DF_CHECK(t, duoforge_public_record_check(NULL, &rec) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_public_record_check(kp, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_public_record_check(kp, &rec) == DUOFORGE_E_MALFORMED); /* no size: not a record of the context */
    duoforge_context_destroy(k1);
    duoforge_context_destroy(kp);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.view");
    test_uniforms(&t);
    test_hp_display(&t);
    test_move_result(&t);
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
    corpus_move_results(&t);
    printf("move results: %u actions classified, %u refused, %u slots compared with the engine\n", mr_classified,
           mr_unclassified, mr_compared);
    printf("move results not asked, a status move into a Substitute: %u named targets, %u hidden ([still]), %u spread\n",
           mr_sub_named, mr_sub_hidden, mr_sub_spread);
    printf("move results: %u slots differ as the known deviations list them (%u listed)\n", mr_known_seen,
           (unsigned)MR_KNOWN_COUNT);
    DF_CHECK(&t, mr_classified > 0u && mr_compared > 0u);
    DF_CHECK(&t, mr_known_seen == MR_KNOWN_COUNT); /* every listed deviation still differs, once */
    return df_test_end(&t);
}
