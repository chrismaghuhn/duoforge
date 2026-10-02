/*
 * duoforge.combat.team_c_gate (step 12 of docs/decisions/0009): the real
 * Team C (docs/research/third-team/team-c.txt) and the two reference teams
 * of decision 0004 under TEAM_C data, in the five pairings C-A, C-B, A-C,
 * B-C and C-C, from team selection to TERMINAL with random legal choices,
 * with the checks of duoforge.combat.closure_gate:
 *
 *  - every step returns OK: the battles reach no E_UNSUPPORTED (or any
 *    other error); every move slot of every member of the three teams is
 *    used and all five Mega formes appear (Team C brings Salamence-Mega);
 *  - every committed state passes the checker, and a copy decoded from the
 *    bytes of every boundary continues byte for byte like the original;
 *  - a replay of the recorded bundles from the setup ends in the same bytes;
 *  - information equivalence on real states at every boundary of every
 *    fourth battle, for both viewers, with the pairs of the closure gate, a
 *    stronger RNG pair (every bit of the state, the stream and the draw
 *    count) and the locked-target pair only for a charging move (a choice
 *    lock has no target);
 *  - the Team C state is reached at the boundaries the gate continues from
 *    (not TERMINAL), in all battles and in the battles with information
 *    pairs: Psychic Terrain, poison, the choice lock, Unburden, and at a
 *    PIVOT the volatiles of Follow Me and Helping Hand and newlySwitched.
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "data/closure_tables.h"
#include "data/extended_tables.h"
#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/team_c.h"

#define GATE_SEEDS 1000u    /* per pairing */
#define GATE_PAIRS_EVERY 4u  /* information pairs in every 4th battle */
#define GATE_MAX_STEPS 1000u /* per battle */

/* The complete model-visible surface of one viewer (as in
 * duoforge.request.information). */
typedef struct surface {
    duoforge_status req_status;
    duoforge_request req;
    duoforge_status cand_status;
    uint32_t count;
    duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    duoforge_status obs_status;
    duoforge_observation obs;
} surface;

static surface sa;
static surface sb;
static duoforge_side_choice pool[DUOFORGE_MAX_CANDIDATES];
static duoforge_decision_bundle tape[GATE_MAX_STEPS];
static bool used_slot[3][DUOFORGE_MAX_ROSTER][DUOFORGE_MAX_MOVE_SLOTS]; /* team, member, move slot */
static bool mega_forme[DFI_EXT_FORME_COUNT];

/* The Team C state the gate must reach at a committed boundary. */
#define SEEN_PSYCHIC_TERRAIN 1u
#define SEEN_POISON 2u
#define SEEN_CHOICE_LOCK 4u
#define SEEN_UNBURDEN 8u
#define SEEN_FOLLOW_ME 16u
#define SEEN_HELPING_HAND 32u
#define SEEN_NEWLY_SWITCHED 64u
#define SEEN_ALL 127u

static uint32_t team_c_state(const duoforge_battle *b)
{
    /* Follow Me, Helping Hand and newlySwitched live inside a turn: a PIVOT
     * is where the gate continues from them. */
    const bool pivot = b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT;
    uint32_t seen = b->terrain == DFI_TERRAIN_PSYCHIC ? SEEN_PSYCHIC_TERRAIN : 0u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        const dfi_side *sd = &b->sides[s];
        for (uint32_t m = 0u; m < sd->member_count; ++m) {
            seen |= sd->members[m].status == DFI_STATUS_PSN ? SEEN_POISON : 0u;
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            const uint32_t flags = sd->positions[p].flags;
            seen |= (flags & DFI_VOL_CHOICE_LOCK) != 0u ? SEEN_CHOICE_LOCK : 0u;
            seen |= (flags & DFI_VOL_UNBURDEN) != 0u ? SEEN_UNBURDEN : 0u;
            seen |= pivot && (flags & DFI_VOL_FOLLOW_ME) != 0u ? SEEN_FOLLOW_ME : 0u;
            seen |= pivot && (flags & DFI_VOL_HELPING_HAND) != 0u ? SEEN_HELPING_HAND : 0u;
            seen |= pivot && (flags & DFI_VOL_NEWLY_SWITCHED) != 0u ? SEEN_NEWLY_SWITCHED : 0u;
        }
    }
    return seen;
}

/* The kinds of pairs; each must run at least once in the gate. */
static const char *const pair_kinds[] = {
    "active foe pp",           "confusion turns",           "foe actions in the queue",
    "foe hp inside one display bucket", "foe pick order",   "opponent knowledge",
    "rng",                     "rng, every bit",            "sleep or freeze turns",
    "the foe's locked target",
    "unseen foe reserve hp/pp", "which members the opponent brought",
};
#define PAIR_KINDS (sizeof pair_kinds / sizeof pair_kinds[0])

typedef struct counts {
    unsigned equivalent; /* pairs with the same surface, as required */
    unsigned shown;      /* HP changes that move the display, and show */
    unsigned leaks;
    unsigned runs[PAIR_KINDS]; /* pairs run, by kind */
} counts;

static uint32_t dfi_popcount_mask(uint32_t x)
{
    uint32_t n = 0u;
    for (; x != 0u; x &= x - 1u) {
        ++n;
    }
    return n;
}

static void capture(const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer, surface *s)
{
    memset(s, 0, sizeof *s);
    s->req_status = duoforge_battle_request(ctx, b, viewer, &s->req);
    s->cand_status = duoforge_battle_candidates(ctx, b, viewer, s->cands, DUOFORGE_MAX_CANDIDATES, &s->count);
    s->obs_status = duoforge_battle_observe(ctx, b, viewer, &s->obs);
}

static void expect_same(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *b,
                        uint32_t viewer, const char *what, counts *c)
{
    bool known = false;
    for (size_t i = 0; i < PAIR_KINDS; ++i) {
        if (strcmp(what, pair_kinds[i]) == 0) {
            c->runs[i] += 1u;
            known = true;
        }
    }
    DF_CHECK(t, known);
    capture(ctx, a, viewer, &sa);
    capture(ctx, b, viewer, &sb);
    if (!DF_CHECK(t, memcmp(&sa, &sb, sizeof sa) == 0)) {
        fprintf(stderr, "  information leak: %s (viewer %u)\n", what, viewer);
        c->leaks += 1u;
        return;
    }
    c->equivalent += 1u;
}

/* The pairs of one boundary for one viewer; `a` is the committed state. */
static void pairs(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, uint32_t viewer, counts *c)
{
    const uint32_t foe = 1u - viewer;
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_clone(ctx, a, &b) == DUOFORGE_OK)) {
        return;
    }
    /* the gameplay RNG */
    b->rng.state ^= UINT64_C(0x9E3779B97F4A7C15);
    b->rng.draws += 5u;
    expect_same(t, ctx, a, b, viewer, "rng", c);
    /* every bit of its state, its stream (inc stays odd) and its draw count */
    DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
    b->rng.state = ~a->rng.state;
    b->rng.inc ^= 2u;
    b->rng.draws ^= 1u;
    expect_same(t, ctx, a, b, viewer, "rng, every bit", c);

    const dfi_side *fs = &a->sides[foe];
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const uint32_t occ = fs->positions[p].occupant;
        if (occ >= fs->member_count || fs->members[occ].hp == 0u) {
            continue;
        }
        /* the PP of an active foe */
        for (uint32_t k = 0u; k < fs->members[occ].move_count; ++k) {
            if (fs->members[occ].moves[k].pp > 1u) {
                DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
                b->sides[foe].members[occ].moves[k].pp = (uint8_t)(fs->members[occ].moves[k].pp - 1u);
                DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
                expect_same(t, ctx, a, b, viewer, "active foe pp", c);
                break;
            }
        }
        /* one HP less: the same display hides it, a new display shows it */
        if (fs->members[occ].hp > 1u) {
            DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
            b->sides[foe].members[occ].hp = (uint16_t)(fs->members[occ].hp - 1u);
            df_knowledge_refresh_active(b);
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            if (memcmp(&a->sides[viewer].knowledge[occ], &b->sides[viewer].knowledge[occ],
                       sizeof a->sides[viewer].knowledge[occ]) == 0) {
                expect_same(t, ctx, a, b, viewer, "foe hp inside one display bucket", c);
            } else {
                capture(ctx, a, viewer, &sa);
                capture(ctx, b, viewer, &sb);
                if (DF_CHECK(t, memcmp(&sa, &sb, sizeof sa) != 0)) {
                    c->shown += 1u;
                }
            }
        }
    }
    /* a brought foe member the viewer has not seen: its HP and PP */
    for (uint32_t m = 0u; m < fs->member_count; ++m) {
        const bool brought = ((uint32_t)fs->brought_mask >> m & 1u) != 0u;
        const bool seen = ((uint32_t)a->sides[viewer].seen_mask >> m & 1u) != 0u;
        if (brought && !seen && fs->members[m].hp > 1u && fs->members[m].moves[0].pp > 1u) {
            DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
            b->sides[foe].members[m].hp = (uint16_t)(fs->members[m].hp - 1u);
            b->sides[foe].members[m].moves[0].pp = (uint8_t)(fs->members[m].moves[0].pp - 1u);
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            expect_same(t, ctx, a, b, viewer, "unseen foe reserve hp/pp", c);
            break;
        }
    }
    /* what the opponent knows about the viewer's side: one HP display */
    for (uint32_t m = 0u; m < a->sides[viewer].member_count; ++m) {
        if (((uint32_t)fs->seen_mask >> m & 1u) != 0u) {
            DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
            dfi_knowledge *kn = &b->sides[foe].knowledge[m];
            kn->hp_percent = kn->hp_percent == 100u ? 99u : 100u;
            kn->hp_flag = (uint8_t)DUOFORGE_HP_FLAG_NONE;
            if (duoforge_battle_check(ctx, b) == DUOFORGE_OK) {
                expect_same(t, ctx, a, b, viewer, "opponent knowledge", c);
            }
            break;
        }
    }
    /* Observation v2 (decision 0007): what the game never shows stays
     * hidden on both sides, what it shows is visible. */
    for (uint32_t s = 0u; s < 2u; ++s) {
        const dfi_side *sd = &a->sides[s];
        for (uint32_t m = 0u; m < sd->member_count; ++m) {
            const dfi_member *mem = &sd->members[m];
            /* sleep and freeze turns: rolled in secret, hidden for both */
            if (mem->hp != 0u && (mem->status == DFI_STATUS_SLP || mem->status == DFI_STATUS_FRZ)) {
                DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
                const uint32_t turns = mem->status_counter == 1u ? 2u : 1u;
                b->sides[s].members[m].status_counter = (uint8_t)turns;
                if (DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK)) {
                    expect_same(t, ctx, a, b, viewer, "sleep or freeze turns", c);
                }
                break;
            }
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            const dfi_active_slot *slot = &sd->positions[p];
            /* confusion turns: hidden for both */
            if (slot->confusion_turns != 0u) {
                DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
                const uint32_t turns = slot->confusion_turns == 1u ? 2u : 1u;
                b->sides[s].positions[p].confusion_turns = (uint8_t)turns;
                if (DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK)) {
                    expect_same(t, ctx, a, b, viewer, "confusion turns", c);
                }
            }
            /* the foe's charged move: its target is hidden, the move is not
             * (a choice lock has no target) */
            if (s == foe && slot->locked_move != 0u && slot->charge_turns != 0u) {
                DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
                const uint32_t other = slot->locked_target == viewer * 2u ? viewer * 2u + 1u : viewer * 2u;
                b->sides[s].positions[p].locked_target = (uint8_t)other;
                if (duoforge_battle_check(ctx, b) == DUOFORGE_OK) {
                    expect_same(t, ctx, a, b, viewer, "the foe's locked target", c);
                }
            }
        }
    }
    /* shown: the field's remaining turns and a foe's stat stage */
    if (a->weather != DFI_WEATHER_NONE && a->weather_turns > 1u) {
        DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
        b->weather_turns = (uint8_t)((uint32_t)a->weather_turns - 1u);
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        capture(ctx, a, viewer, &sa);
        capture(ctx, b, viewer, &sb);
        c->shown += DF_CHECK(t, memcmp(&sa, &sb, sizeof sa) != 0) ? 1u : 0u;
    }
    for (uint32_t p = 0u; p < 2u; ++p) {
        if (fs->positions[p].occupant < fs->member_count && fs->positions[p].stages[0] > 0u) {
            DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
            b->sides[foe].positions[p].stages[0] = (uint8_t)((uint32_t)fs->positions[p].stages[0] - 1u);
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            capture(ctx, a, viewer, &sa);
            capture(ctx, b, viewer, &sb);
            c->shown += DF_CHECK(t, memcmp(&sa, &sb, sizeof sa) != 0) ? 1u : 0u;
            break;
        }
    }
    /* the opponent's private pick order */
    if (dfi_popcount_mask(fs->brought_mask) >= 2u) {
        DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
        const uint8_t first = b->sides[foe].brought_order[0];
        b->sides[foe].brought_order[0] = b->sides[foe].brought_order[1];
        b->sides[foe].brought_order[1] = first;
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        expect_same(t, ctx, a, b, viewer, "foe pick order", c);
    }
    /* which members the opponent brought: an unseen brought member that never
     * entered swaps with one left at home (both untouched) */
    for (uint32_t u = 0u; u < fs->member_count; ++u) {
        const bool u_free = ((uint32_t)fs->brought_mask >> u & 1u) != 0u &&
                            ((uint32_t)a->sides[viewer].seen_mask >> u & 1u) == 0u &&
                            fs->positions[0].occupant != u && fs->positions[1].occupant != u;
        bool queued = false;
        for (uint32_t i = 0u; i < a->queue_len; ++i) {
            queued = queued || (a->queue[i].side == foe && a->queue[i].reserve == u &&
                                (a->queue[i].kind == DFI_Q_SWITCH || a->queue[i].kind == DFI_Q_SWITCH_IN));
        }
        if (!u_free || queued) {
            continue;
        }
        uint32_t v = fs->member_count;
        for (uint32_t k = 0u; k < fs->member_count && v == fs->member_count; ++k) {
            v = ((uint32_t)fs->brought_mask >> k & 1u) == 0u ? k : v;
        }
        if (v == fs->member_count) {
            break;
        }
        DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
        dfi_side *bs = &b->sides[foe];
        bs->brought_mask = (uint8_t)(((uint32_t)bs->brought_mask & ~(1u << u)) | (1u << v));
        for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
            if (bs->brought_order[i] == u) {
                bs->brought_order[i] = (uint8_t)v;
            }
        }
        if (DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK)) {
            expect_same(t, ctx, a, b, viewer, "which members the opponent brought", c);
        }
        break;
    }
    /* at a PIVOT: the opponent's actions in the rest of the turn */
    if (a->boundary_kind == DUOFORGE_BOUNDARY_PIVOT) {
        DF_CHECK(t, duoforge_battle_copy(ctx, b, a) == DUOFORGE_OK);
        uint32_t n = 0u;
        for (uint32_t i = 0u; i < b->queue_len; ++i) {
            if (b->queue[i].kind != DFI_Q_MOVE || b->queue[i].side != foe) {
                b->queue[n] = b->queue[i];
                n += 1u;
            }
        }
        if (n != b->queue_len) {
            for (uint32_t i = n; i < b->queue_len; ++i) {
                b->queue[i] = (dfi_queue_record){.kind = DFI_Q_NONE};
            }
            b->queue_len = (uint8_t)n;
            if (DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK)) {
                expect_same(t, ctx, a, b, viewer, "foe actions in the queue", c);
            }
        }
    }
    duoforge_battle_destroy(b);
}

/* A candidate of each requested side: with `any` any candidate, else one
 * whose slots move (Mega allowed) or pass, if there is one. */
static duoforge_status pick(const duoforge_context *ctx, const duoforge_battle *b, uint32_t r, bool any,
                            duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = b->request_mask;
    for (uint32_t s = 0u; s < 2u; ++s) {
        if (((uint32_t)b->request_mask >> s & 1u) == 0u) {
            continue;
        }
        uint32_t n = 0u;
        const duoforge_status st = duoforge_battle_candidates(ctx, b, s, pool, DUOFORGE_MAX_CANDIDATES, &n);
        if (st != DUOFORGE_OK || n == 0u) {
            return st == DUOFORGE_OK ? DUOFORGE_E_INVARIANT : st;
        }
        const uint32_t start = (r >> (s * 8u)) % n;
        uint32_t chosen = start;
        for (uint32_t j = 0u; j < n && !any && b->boundary_kind == DUOFORGE_BOUNDARY_TURN; ++j) {
            const duoforge_side_choice *c = &pool[(start + j) % n];
            if (c->slots[0].kind != DUOFORGE_SLOT_SWITCH && c->slots[1].kind != DUOFORGE_SLOT_SWITCH) {
                chosen = (start + j) % n;
                break;
            }
        }
        bd->responses[s] = pool[chosen];
    }
    return DUOFORGE_OK;
}

/* The state before a failing step and its bundle, for the report. */
static void dump(const duoforge_battle *b, const duoforge_decision_bundle *bd)
{
    fprintf(stderr, "    boundary %u turn %u mask %u queue %u:", (unsigned)b->boundary_kind, (unsigned)b->turn,
            (unsigned)b->request_mask, (unsigned)b->queue_len);
    for (uint32_t i = 0u; i < b->queue_len; ++i) {
        fprintf(stderr, " [k%u s%u p%u m%u t%u]", (unsigned)b->queue[i].kind, (unsigned)b->queue[i].side,
                (unsigned)b->queue[i].slot, (unsigned)b->queue[i].move_slot, (unsigned)b->queue[i].target);
    }
    fprintf(stderr, "\n");
    for (uint32_t s = 0u; s < 2u; ++s) {
        const dfi_side *sd = &b->sides[s];
        fprintf(stderr, "    side %u requested %u mega_used %u:", s, (unsigned)sd->requested_slots,
                (unsigned)sd->mega_used);
        for (uint32_t p = 0u; p < 2u; ++p) {
            const uint32_t occ = sd->positions[p].occupant;
            if (occ < sd->member_count) {
                fprintf(stderr, " pos%u=m%u(species %u hp %u/%u flag %u lock %u)", p, occ,
                        (unsigned)sd->members[occ].species_id, (unsigned)sd->members[occ].hp,
                        (unsigned)sd->members[occ].hp_max, (unsigned)sd->positions[p].switch_flag,
                        (unsigned)sd->positions[p].locked_move);
            } else {
                fprintf(stderr, " pos%u=empty", p);
            }
        }
        fprintf(stderr, "; bundle:");
        for (uint32_t k = 0u; k < 2u; ++k) {
            const duoforge_slot_command *c = &bd->responses[s].slots[k];
            fprintf(stderr, " (kind %u move %u target %u mega %u reserve %u)", (unsigned)c->kind,
                    (unsigned)c->move_slot, (unsigned)c->target, (unsigned)c->mega, (unsigned)c->reserve);
        }
        fprintf(stderr, "\n");
    }
}

static void encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t *out)
{
    df_encode(ctx, b, out);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.combat.team_c_gate");
    duoforge_context *kc = df_make_context(&df_config_team_c);
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    duoforge_side_setup three[3]; /* team A, team B, Team C */
    three[0] = teams.sides[0];
    three[1] = teams.sides[1];
    df_put_team_c(&three[2]);
    static const char *const names[5] = {"C-A", "C-B", "A-C", "B-C", "C-C"};
    static const uint32_t pairing[5][2] = {{2u, 0u}, {2u, 1u}, {0u, 2u}, {1u, 2u}, {2u, 2u}};

    dfi_rng rng;
    dfi_rng_seed(&rng, 1313u, 13u);
    counts c;
    memset(&c, 0, sizeof c);
    unsigned steps = 0;
    unsigned ended = 0;
    unsigned results[4] = {0, 0, 0, 0};
    uint32_t team_c_seen = 0u; /* at the boundaries the gate continues from */
    uint32_t paired_seen = 0u; /* the same, in the battles with information pairs */
    unsigned errors = 0;
    unsigned mismatches = 0;
    unsigned replays = 0;
    unsigned replacements = 0;
    unsigned pivots = 0;
    unsigned exits = 0; /* REPLACEMENT slots of a standing Pokemon: Emergency Exit at the end of a turn */
    unsigned megas = 0;
    unsigned longest = 0;
    for (uint32_t pi = 0u; pi < 5u; ++pi) {
        for (uint32_t seed = 1u; seed <= GATE_SEEDS; ++seed) {
            duoforge_battle_setup s = teams;
            s.sides[0] = three[pairing[pi][0]];
            s.sides[1] = three[pairing[pi][1]];
            s.rng_initstate = (uint64_t)seed * 7919u + pi;
            s.rng_initseq = 2026u + pi;
            duoforge_battle *b = NULL;
            if (!DF_CHECK(&t, duoforge_battle_create(kc, &s, &b) == DUOFORGE_OK && b != NULL)) {
                fprintf(stderr, "  %s seed %u: the setup is rejected\n", names[pi], seed);
                continue;
            }
            uint32_t n = 0u;
            for (; n < GATE_MAX_STEPS && b->boundary_kind != DUOFORGE_BOUNDARY_TERMINAL; ++n) {
                uint32_t r = 0u;
                (void)dfi_rng_next_u32(&rng, &r);
                duoforge_decision_bundle *bd = &tape[n];
                if (!DF_CHECK(&t, pick(kc, b, r, (r >> 28) == 0u, bd) == DUOFORGE_OK)) {
                    errors += 1u;
                    break;
                }
                uint8_t bytes[DUOFORGE_STATE_V3_ENCODED_SIZE];
                encode(kc, b, bytes);
                duoforge_battle *copy = NULL;
                DF_CHECK(&t, duoforge_battle_create_decoded(kc, bytes, sizeof bytes, &copy) == DUOFORGE_OK);
                duoforge_battle *before = NULL;
                DF_CHECK(&t, duoforge_battle_clone(kc, b, &before) == DUOFORGE_OK);
                duoforge_step_result res;
                const duoforge_status st = duoforge_battle_step(kc, b, bd, &res);
                if (!DF_CHECK(&t, st == DUOFORGE_OK)) {
                    fprintf(stderr, "  %s seed %u step %u: %s\n", names[pi], seed, n, duoforge_status_name(st));
                    if (before != NULL) {
                        dump(before, bd);
                    }
                    duoforge_battle_destroy(before);
                    errors += 1u;
                    duoforge_battle_destroy(copy);
                    break;
                }
                duoforge_battle_destroy(before);
                if (copy != NULL) {
                    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
                    uint8_t after2[DUOFORGE_STATE_V3_ENCODED_SIZE];
                    duoforge_step_result res2;
                    DF_CHECK(&t, duoforge_battle_step(kc, copy, bd, &res2) == DUOFORGE_OK);
                    encode(kc, b, after);
                    encode(kc, copy, after2);
                    mismatches += memcmp(after, after2, sizeof after) != 0 ? 1u : 0u;
                    duoforge_battle_destroy(copy);
                }
                DF_CHECK(&t, duoforge_battle_check(kc, b) == DUOFORGE_OK);
                if (b->boundary_kind != DUOFORGE_BOUNDARY_TERMINAL) {
                    const uint32_t state = team_c_state(b);
                    team_c_seen |= state;
                    paired_seen |= seed % GATE_PAIRS_EVERY == 1u ? state : 0u;
                }
                if (seed % GATE_PAIRS_EVERY == 1u) {
                    pairs(&t, kc, b, 0u, &c);
                    pairs(&t, kc, b, 1u, &c);
                }
                replacements += b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT ? 1u : 0u;
                pivots += b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT ? 1u : 0u;
                for (uint32_t side = 0u; side < 2u && b->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT; ++side) {
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        const uint32_t occ = b->sides[side].positions[p].occupant;
                        exits += (((uint32_t)b->sides[side].requested_slots >> p & 1u) != 0u &&
                                  occ < b->sides[side].member_count && b->sides[side].members[occ].hp != 0u)
                                     ? 1u
                                     : 0u;
                    }
                }
                steps += 1u;
            }
            longest = n > longest ? n : longest;
            if (b->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                ended += 1u;
                results[b->result & 3u] += 1u;
                megas += (unsigned)b->sides[0].mega_used + (unsigned)b->sides[1].mega_used;
                for (uint32_t side = 0u; side < 2u; ++side) {
                    const dfi_side *sd = &b->sides[side];
                    for (uint32_t m = 0u; m < sd->member_count; ++m) {
                        const dfi_member *mem = &sd->members[m];
                        for (uint32_t k = 0u; k < mem->move_count; ++k) {
                            if (mem->moves[k].pp < mem->moves[k].pp_max && m < DUOFORGE_MAX_ROSTER &&
                                k < DUOFORGE_MAX_MOVE_SLOTS) {
                                used_slot[pairing[pi][side]][m][k] = true;
                            }
                        }
                        if (mem->is_mega != 0u && mem->species_id < DFI_EXT_FORME_COUNT) {
                            mega_forme[mem->species_id] = true;
                        }
                    }
                }
                /* the replay of the recorded bundles ends in the same bytes */
                duoforge_battle *again = NULL;
                bool same = false;
                if (DF_CHECK(&t, duoforge_battle_create(kc, &s, &again) == DUOFORGE_OK)) {
                    bool ok = true;
                    for (uint32_t i = 0u; i < n && ok; ++i) {
                        duoforge_step_result res;
                        ok = duoforge_battle_step(kc, again, &tape[i], &res) == DUOFORGE_OK;
                    }
                    same = ok && duoforge_battle_equal(kc, b, again, &same) == DUOFORGE_OK && same;
                    duoforge_battle_destroy(again);
                }
                replays += same ? 1u : 0u;
            }
            duoforge_battle_destroy(b);
        }
    }
    /* Coverage: every move slot of every member of the three teams was used
     * (the members keep their team order in a side), every Mega forme seen. */
    unsigned unused = 0;
    for (uint32_t side = 0u; side < 3u; ++side) {
        for (uint32_t m = 0u; m < three[side].member_count; ++m) {
            const duoforge_member_setup *d = &three[side].members[m];
            for (uint32_t k = 0u; k < d->move_count; ++k) {
                if (!used_slot[side][m][k]) {
                    fprintf(stderr, "  never used: move %u of species %u (team %u)\n", d->moves[k].move_id,
                            d->species_id, side);
                    unused += 1u;
                }
            }
        }
    }
    unsigned mega_kinds = 0;
    for (uint32_t f = 0u; f < DFI_EXT_FORME_COUNT; ++f) {
        mega_kinds += mega_forme[f] ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(&t, unused, 0u);
    DF_CHECK_EQ_U64(&t, mega_kinds, 5u);
    DF_CHECK_EQ_U64(&t, errors, 0u);
    DF_CHECK_EQ_U64(&t, ended, 5u * GATE_SEEDS);
    DF_CHECK_EQ_U64(&t, replays, 5u * GATE_SEEDS);
    DF_CHECK_EQ_U64(&t, mismatches, 0u);
    DF_CHECK_EQ_U64(&t, c.leaks, 0u);
    for (size_t i = 0; i < PAIR_KINDS; ++i) {
        if (!DF_CHECK(&t, c.runs[i] > 0u)) {
            fprintf(stderr, "  the pair \"%s\" never ran\n", pair_kinds[i]);
        }
    }
    DF_CHECK_EQ_U64(&t, team_c_seen, SEEN_ALL);
    DF_CHECK_EQ_U64(&t, paired_seen, SEEN_ALL);
    DF_CHECK(&t, results[1] > 0u && results[2] > 0u && replacements > 0u && pivots > 0u && megas > 0u &&
                     c.equivalent > 0u && c.shown > 0u);
    fprintf(stderr,
            "  team c gate: %u battles ended in %u steps (longest %u; side 0 %u, side 1 %u, tie %u), "
            "%u replays identical; REPLACEMENTs %u (Emergency Exits at the end of a turn %u), PIVOTs %u, Megas %u; "
            "equivalent pairs %u, shown changes (HP displays, weather turns, stat stages) %u\n",
            ended, steps, longest, results[1], results[2], results[3], replays, replacements, exits, pivots, megas,
            c.equivalent, c.shown);
    duoforge_context_destroy(kc);
    return df_test_end(&t);
}
