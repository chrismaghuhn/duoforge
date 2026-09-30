/*
 * T31 duoforge.request.step (white-box parts marked): the TEAM_SELECTION step
 * reproduces the white-box fixtures byte-exactly and reports the new
 * boundary; malformed-input atomicity as its own category (NULL, context,
 * stale epochs, masks, reserved bytes, side/kind fields, out-of-domain
 * responses, unrequested responses); a valid TURN/REPLACEMENT/PIVOT bundle
 * is E_UNSUPPORTED with nothing mutated (no fake success); counter
 * exhaustion is atomic; and rule-authorized re-prompt (DECISION_CONTRACT
 * section 6) is tested separately as a successful transition that seals the
 * other side's choice.
 */
#include <stdio.h>
#include <string.h>

#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"

static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];

static void raw(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE])
{
    df_encode(ctx, b, out);
}

static void team_choice(duoforge_side_choice *c, uint32_t epoch, uint32_t side, const uint8_t *picks, uint32_t n)
{
    memset(c, 0, sizeof *c);
    c->epoch = epoch;
    c->side = (uint8_t)side;
    c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
    c->pick_count = (uint8_t)n;
    for (uint32_t i = 0; i < n; ++i) {
        c->picks[i] = picks[i];
    }
}

static void team_bundle(duoforge_decision_bundle *bd, uint32_t epoch, const uint8_t *p0, const uint8_t *p1,
                        uint32_t n)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = epoch;
    bd->response_mask = 3u;
    team_choice(&bd->responses[0], epoch, 0, p0, n);
    team_choice(&bd->responses[1], epoch, 1, p1, n);
}

/* A step that must fail: expected status, battle bytes unchanged, result untouched. */
static void step_fails(df_test *t, const duoforge_context *ctx, duoforge_battle *b,
                       const duoforge_decision_bundle *bd, duoforge_status expected, const char *what)
{
    uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
    duoforge_step_result res;
    memset(&res, 0xA5, sizeof res);
    raw(ctx, b, before);
    const duoforge_status st = duoforge_battle_step(ctx, b, bd, &res);
    raw(ctx, b, after);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  step case %s: %s, expected %s\n", what, duoforge_status_name(st),
                duoforge_status_name(expected));
    }
    DF_CHECK_BYTES(t, after, before, sizeof after, what);
    DF_CHECK(t, res.epoch == 0xA5A5A5A5u && res.kind == 0xA5u && res.boundary_kind == 0xA5u &&
                    res.request_mask == 0xA5u && res.reserved == 0xA5u);
}

/* Builds a valid slot bundle for the requested sides from candidate index
 * pick[s] of each side's domain (0 for unrequested sides). */
static void slot_bundle(df_test *t, const duoforge_context *ctx, const duoforge_battle *b,
                        duoforge_decision_bundle *bd, const uint32_t pick[2])
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = b->request_mask;
    for (uint32_t s = 0; s < 2; ++s) {
        if ((((uint32_t)b->request_mask >> s) & 1u) == 0u) {
            continue;
        }
        uint32_t n = 0;
        DF_CHECK(t, duoforge_battle_candidates(ctx, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        DF_CHECK(t, pick[s] < n);
        bd->responses[s] = cands[pick[s] < n ? pick[s] : 0];
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.step");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_context *c4 = df_make_context(&df_config_c4);
    static const uint8_t p0[4] = {2u, 0u, 1u, 3u};
    static const uint8_t p1[4] = {1u, 3u, 0u, 2u};

    /* The public step reproduces the white-box F1 exactly (and G3 -> F3,
     * G7 -> F8 / F9) and reports the new boundary. */
    {
        duoforge_battle *g = df_make_g1(c1);
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_decision_bundle bd;
        duoforge_step_result res;
        memset(&res, 0xA5, sizeof res);
        team_bundle(&bd, 1u, p0, p1, 4u);
        DF_CHECK(&t, duoforge_battle_step(c1, g, &bd, &res) == DUOFORGE_OK);
        DF_CHECK(&t, res.epoch == 2u && res.kind == DUOFORGE_STEP_BOUNDARY &&
                         res.boundary_kind == DUOFORGE_BOUNDARY_TURN && res.request_mask == 3u && res.reserved == 0u);
        bool eq = false;
        DF_CHECK(&t, duoforge_battle_equal(c1, g, f1, &eq) == DUOFORGE_OK && eq);
        uint8_t enc[DUOFORGE_STATE_V3_ENCODED_SIZE];
        raw(c1, g, enc);
        DF_CHECK_BYTES(&t, enc, df_golden_f1, sizeof enc, "step(G1) == golden F1");
        /* The bench order is stored privately; the leads occupy the slots. */
        DF_CHECK(&t, g->sides[0].brought_order[2] == 1u && g->sides[0].brought_order[3] == 3u);
        DF_CHECK(&t, g->sides[1].positions[0].occupant == 1u && g->sides[1].positions[1].occupant == 3u);
        DF_CHECK(&t, g->sides[0].seen_mask == 0x0Au && g->sides[1].seen_mask == 0x05u);
        /* Turn 1 begins; each side sees the opposing leads at full HP. */
        DF_CHECK(&t, g->turn == 1u && g->queue_len == 0u && g->result == 0u);
        DF_CHECK(&t, g->sides[0].knowledge[1].hp_percent == 100u && g->sides[0].knowledge[3].hp_percent == 100u &&
                         g->sides[0].knowledge[0].hp_percent == 0u && g->sides[1].knowledge[2].hp_percent == 100u);
        /* A late duplicate of the same bundle is stale, atomically. */
        step_fails(&t, c1, g, &bd, DUOFORGE_E_STALE_EPOCH, "late team-selection bundle");
        duoforge_battle_destroy(g);
        duoforge_battle_destroy(f1);

        duoforge_battle *g3 = df_make_g3(c3);
        duoforge_battle *f3 = df_make_f3(c3);
        static const uint8_t q0[1] = {2u};
        static const uint8_t q1[1] = {0u};
        team_bundle(&bd, 1u, q0, q1, 1u);
        DF_CHECK(&t, duoforge_battle_step(c3, g3, &bd, &res) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(c3, g3, f3, &eq) == DUOFORGE_OK && eq);
        DF_CHECK(&t, g3->sides[0].positions[1].occupant == DFI_OCCUPANT_NONE); /* brought 1: slot b empty */
        duoforge_battle_destroy(g3);
        duoforge_battle_destroy(f3);

        static const uint8_t r0[2] = {1u, 3u};
        static const uint8_t r1[2] = {2u, 0u};
        duoforge_battle *g7 = df_make_g7(c4);
        duoforge_battle *f8 = df_make_f8(c4);
        team_bundle(&bd, 1u, r0, r1, 2u);
        DF_CHECK(&t, duoforge_battle_step(c4, g7, &bd, &res) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(c4, g7, f8, &eq) == DUOFORGE_OK && eq);
        duoforge_battle_destroy(g7);
        duoforge_battle_destroy(f8);
    }

    /* Every enumerated TEAM_SELECTION candidate is accepted by step (the
     * accepted set is the enumerated set): all 12 x 6 pairs on G7. */
    {
        duoforge_battle *g7 = df_make_g7(c4);
        uint32_t n0 = 0;
        uint32_t n1 = 0;
        duoforge_side_choice d0[12];
        duoforge_side_choice d1[6];
        DF_CHECK(&t, duoforge_battle_candidates(c4, g7, 0, d0, 12, &n0) == DUOFORGE_OK && n0 == 12u);
        DF_CHECK(&t, duoforge_battle_candidates(c4, g7, 1, d1, 6, &n1) == DUOFORGE_OK && n1 == 6u);
        unsigned accepted = 0;
        for (uint32_t i = 0; i < n0; ++i) {
            for (uint32_t j = 0; j < n1; ++j) {
                duoforge_battle *w = NULL;
                DF_CHECK(&t, duoforge_battle_clone(c4, g7, &w) == DUOFORGE_OK);
                duoforge_decision_bundle bd;
                memset(&bd, 0, sizeof bd);
                bd.epoch = 1u;
                bd.response_mask = 3u;
                bd.responses[0] = d0[i];
                bd.responses[1] = d1[j];
                duoforge_step_result res;
                if (duoforge_battle_step(c4, w, &bd, &res) == DUOFORGE_OK) {
                    ++accepted;
                    DF_CHECK(&t, duoforge_battle_check(c4, w) == DUOFORGE_OK);
                    DF_CHECK(&t, w->sides[0].positions[0].occupant == d0[i].picks[0] &&
                                     w->sides[0].positions[1].occupant == d0[i].picks[1] &&
                                     w->sides[1].positions[0].occupant == d1[j].picks[0] &&
                                     w->sides[1].positions[1].occupant == d1[j].picks[1]);
                }
                duoforge_battle_destroy(w);
            }
        }
        DF_CHECK_EQ_U64(&t, accepted, 72u);
        duoforge_battle_destroy(g7);
    }

    /* Malformed-input atomicity at TEAM_SELECTION (its own category). */
    {
        duoforge_battle *g = df_make_g1(c1);
        duoforge_decision_bundle bd;
        duoforge_decision_bundle good;
        team_bundle(&good, 1u, p0, p1, 4u);
        duoforge_step_result res;
        memset(&res, 0xA5, sizeof res);
        DF_CHECK(&t, duoforge_battle_step(NULL, g, &good, &res) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_step(c1, NULL, &good, &res) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_step(c1, g, NULL, &res) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_step(c1, g, &good, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, res.epoch == 0xA5A5A5A5u);
        {
            uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
            uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
            raw(c1, g, before);
            memset(&res, 0xA5, sizeof res);
            DF_CHECK(&t, duoforge_battle_step(c3, g, &good, &res) == DUOFORGE_E_CONTEXT_MISMATCH);
            raw(c1, g, after);
            DF_CHECK_BYTES(&t, after, before, sizeof after, "context mismatch");
            DF_CHECK(&t, res.epoch == 0xA5A5A5A5u);
        }
        bd = good;
        bd.epoch = 2u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_STALE_EPOCH, "bundle epoch ahead");
        bd = good;
        bd.epoch = 0u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_STALE_EPOCH, "bundle epoch 0");
        bd = good;
        bd.responses[1].epoch = 2u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_STALE_EPOCH, "response epoch stale");
        static const uint8_t masks[] = {0u, 1u, 2u, 4u, 7u, 0xFFu};
        for (unsigned i = 0; i < sizeof masks; ++i) {
            bd = good;
            bd.response_mask = masks[i];
            step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "response mask");
        }
        bd = good;
        bd.reserved[1] = 1u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "bundle reserved byte");
        bd = good;
        bd.responses[0].reserved[2] = 1u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "choice reserved byte");
        bd = good;
        bd.responses[0].slots[1].reserved[0] = 1u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "slot reserved byte");
        bd = good;
        bd.responses[0].side = 1u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "wrong side field");
        bd = good;
        bd.responses[1].kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "wrong choice kind");
        bd = good;
        bd.responses[1].kind = 0u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "choice kind 0");
        bd = good;
        bd.responses[0].picks[3] = 2u; /* duplicate */
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "duplicate pick");
        bd = good;
        bd.responses[1].picks[0] = 4u; /* side 1 has 4 members */
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pick out of range");
        bd = good;
        bd.responses[1].picks[0] = 0xFFu;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pick 0xFF");
        bd = good;
        bd.responses[0].pick_count = 3u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pick_count 3");
        bd = good;
        bd.responses[0].pick_count = 5u;
        bd.responses[0].picks[4] = 4u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pick_count 5");
        bd = good;
        bd.responses[0].picks[4] = 1u; /* tail must be zero */
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pick tail nonzero");
        bd = good;
        bd.responses[0].slots[0].kind = (uint8_t)DUOFORGE_SLOT_PASS;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "slot command in a team selection");
        /* Precedence: a stale epoch is reported before a bad mask; a bad mask
         * before a bad response. */
        bd = good;
        bd.epoch = 9u;
        bd.response_mask = 1u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_STALE_EPOCH, "epoch before mask");
        bd = good;
        bd.response_mask = 1u;
        bd.responses[0].picks[3] = 2u;
        step_fails(&t, c1, g, &bd, DUOFORGE_E_INVALID_ARGUMENT, "mask before response");
        /* Corrupt state (white-box): one opaque INVARIANT, nothing written. */
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, g, &x) == DUOFORGE_OK);
        x->sides[0].members[0].hp = 0xFFFFu;
        memset(&res, 0xA5, sizeof res);
        DF_CHECK(&t, duoforge_battle_step(c1, x, &good, &res) == DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, res.epoch == 0xA5A5A5A5u);
        duoforge_battle_destroy(x);
        /* The good bundle still works afterwards: nothing above leaked state. */
        DF_CHECK(&t, duoforge_battle_step(c1, g, &good, &res) == DUOFORGE_OK);
        duoforge_battle_destroy(g);
    }

    /* Counter exhaustion is checked before any mutation. */
    {
        duoforge_battle *g = df_make_g1(c1);
        duoforge_decision_bundle bd;
        g->request_epoch = UINT32_MAX;
        team_bundle(&bd, UINT32_MAX, p0, p1, 4u);
        step_fails(&t, c1, g, &bd, DUOFORGE_E_EXHAUSTED, "epoch exhausted");
        duoforge_battle_destroy(g);
        g = df_make_g1(c1);
        g->next_activation_id = UINT32_MAX - 2u; /* room for two of four placements */
        team_bundle(&bd, 1u, p0, p1, 4u);
        step_fails(&t, c1, g, &bd, DUOFORGE_E_EXHAUSTED, "activation ids exhausted mid-transition");
        duoforge_battle_destroy(g);
    }

    /* Honest execution: valid TURN, REPLACEMENT and PIVOT bundles are
     * E_UNSUPPORTED after full validation, with nothing mutated; invalid
     * ones are INVALID_ARGUMENT. The two categories stay distinguishable. */
    {
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_decision_bundle bd;
        const uint32_t pick[2] = {0u, 0u};
        slot_bundle(&t, c1, f1, &bd, pick);
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_UNSUPPORTED, "valid TURN bundle");
        const uint32_t last[2] = {32u, 117u};
        slot_bundle(&t, c1, f1, &bd, last);
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_UNSUPPORTED, "valid TURN bundle (last candidates)");
        /* Out-of-domain slot choices. */
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].slots[0].mega = 1u; /* roster 2 holds no stone */
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "Mega without a stone");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[1].slots[0] = bd.responses[1].slots[1] =
            (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "two switches to the same reserve");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 1u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "Mega on a switch");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 1u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "switch to an active member");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 4u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "switch to a nonexistent member");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 3u, 1u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "move slot beyond move_count");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "targeting self with a NORMAL move");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pass with an able actor");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].slots[1].kind = (uint8_t)DUOFORGE_SLOT_NONE;
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "missing slot command");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "team selection at TURN");
        slot_bundle(&t, c1, f1, &bd, pick);
        bd.responses[0].pick_count = 4u;
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "picks at TURN");
        duoforge_battle_destroy(f1);

        /* A move at pp 0 is not selectable (F2: s0 roster 1 is a reserve, so
         * use F12's side 1 with an F9-like pp poke instead). */
        duoforge_battle *f9 = df_make_f9(c4);
        f9->sides[1].members[1].moves[0].pp = 0u; /* s1a roster 1: its only move */
        /* That actor now has no selectable move: the request is UNSUPPORTED
         * (Struggle), and so is any step involving that side. */
        duoforge_request r;
        DF_CHECK(&t, duoforge_battle_request(c4, f9, 1, &r) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(&t, duoforge_battle_request(c4, f9, 0, &r) == DUOFORGE_OK); /* side 0 unaffected */
        memset(&bd, 0, sizeof bd);
        bd.epoch = 2u;
        bd.response_mask = 3u;
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c4, f9, 0, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        bd.responses[0] = cands[0];
        bd.responses[1].epoch = 2u;
        bd.responses[1].side = 1u;
        bd.responses[1].kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        bd.responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        bd.responses[1].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c4, f9, &bd, DUOFORGE_E_UNSUPPORTED, "step with a Struggle side");
        duoforge_battle_destroy(f9);

        duoforge_battle *f4 = df_make_f4(c1);
        slot_bundle(&t, c1, f4, &bd, pick);
        step_fails(&t, c1, f4, &bd, DUOFORGE_E_UNSUPPORTED, "valid two-side REPLACEMENT bundle");
        slot_bundle(&t, c1, f4, &bd, pick);
        bd.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f4, &bd, DUOFORGE_E_INVALID_ARGUMENT, "pass while a reserve is available");
        slot_bundle(&t, c1, f4, &bd, pick);
        bd.responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f4, &bd, DUOFORGE_E_INVALID_ARGUMENT, "switch to the other active member");
        slot_bundle(&t, c1, f4, &bd, pick);
        bd.responses[0].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 0u, 2u, 0u, 0u, {0u, 0u, 0u}};
        step_fails(&t, c1, f4, &bd, DUOFORGE_E_INVALID_ARGUMENT, "command for an unrequested slot");
        duoforge_battle_destroy(f4);

        duoforge_battle *f5 = df_make_f5(c1);
        slot_bundle(&t, c1, f5, &bd, pick);
        step_fails(&t, c1, f5, &bd, DUOFORGE_E_UNSUPPORTED, "valid one-side PIVOT bundle");
        slot_bundle(&t, c1, f5, &bd, pick);
        bd.responses[1].epoch = 3u; /* the waiting side must stay all-zero */
        step_fails(&t, c1, f5, &bd, DUOFORGE_E_INVALID_ARGUMENT, "response of an unrequested side");
        slot_bundle(&t, c1, f5, &bd, pick);
        bd.response_mask = 3u;
        step_fails(&t, c1, f5, &bd, DUOFORGE_E_INVALID_ARGUMENT, "mask includes the waiting side");
        duoforge_battle_destroy(f5);

        duoforge_battle *f6 = df_make_f6(c1);
        slot_bundle(&t, c1, f6, &bd, pick);
        step_fails(&t, c1, f6, &bd, DUOFORGE_E_UNSUPPORTED, "valid two-side PIVOT bundle");
        duoforge_battle_destroy(f6);
    }

    /* Rule-authorized re-prompt (white-box): a successful transition of its
     * own kind, separate from malformed input. Side 0 must choose again;
     * side 1's accepted choice is sealed and the epoch advances. */
    {
        duoforge_battle *f1 = df_make_f1(c1);
        duoforge_battle *before = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &before) == DUOFORGE_OK);
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c1, f1, 1, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        const duoforge_side_choice s1 = cands[5];
        /* Preconditions are engine contracts, checked atomically. */
        duoforge_battle *g = df_make_g1(c1);
        uint8_t e1[DUOFORGE_STATE_V3_ENCODED_SIZE];
        uint8_t e2[DUOFORGE_STATE_V3_ENCODED_SIZE];
        raw(c1, g, e1);
        DF_CHECK(&t, dfi_reprompt_side(c1, g, 0, &s1) == DUOFORGE_E_INVARIANT);
        raw(c1, g, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "re-prompt at TEAM_SELECTION rejected");
        duoforge_battle_destroy(g);
        raw(c1, f1, e1);
        DF_CHECK(&t, dfi_reprompt_side(c1, f1, 2, &s1) == DUOFORGE_E_INVARIANT);
        duoforge_side_choice bad = s1;
        bad.slots[0].kind = 9u;
        DF_CHECK(&t, dfi_reprompt_side(c1, f1, 0, &bad) == DUOFORGE_E_INVARIANT);
        f1->request_epoch = UINT32_MAX;
        DF_CHECK(&t, dfi_reprompt_side(c1, f1, 0, &s1) == DUOFORGE_E_EXHAUSTED);
        f1->request_epoch = 2u;
        raw(c1, f1, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "failed re-prompts change nothing");
        /* The transition. */
        DF_CHECK(&t, dfi_reprompt_side(c1, f1, 0, &s1) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_check(c1, f1) == DUOFORGE_OK);
        DF_CHECK(&t, f1->request_epoch == 3u && f1->request_mask == 1u &&
                         f1->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        DF_CHECK(&t, f1->sides[1].sealed == 1u && f1->sides[1].requested_slots == 0u && f1->sides[0].sealed == 0u);
        DF_CHECK(&t, f1->sides[1].sealed_cmds[0].kind == s1.slots[0].kind &&
                         f1->sides[1].sealed_cmds[0].move_slot == s1.slots[0].move_slot &&
                         f1->sides[1].sealed_cmds[0].target == s1.slots[0].target &&
                         f1->sides[1].sealed_cmds[1].kind == s1.slots[1].kind &&
                         f1->sides[1].sealed_cmds[1].target == s1.slots[1].target);
        /* Only the re-prompt bookkeeping changed: positions, members, RNG and
         * the other side's data are byte-identical to the state before. */
        DF_CHECK(&t, f1->rng.draws == before->rng.draws && f1->next_activation_id == before->next_activation_id);
        DF_CHECK(&t, memcmp(f1->sides[0].members, before->sides[0].members, sizeof f1->sides[0].members) == 0);
        DF_CHECK(&t, memcmp(f1->sides[1].members, before->sides[1].members, sizeof f1->sides[1].members) == 0);
        /* Requests: side 0 requested with its unchanged domain, side 1 waiting. */
        duoforge_request r0;
        duoforge_request r1;
        DF_CHECK(&t, duoforge_battle_request(c1, f1, 0, &r0) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_request(c1, f1, 1, &r1) == DUOFORGE_OK);
        DF_CHECK(&t, r0.epoch == 3u && r0.requested == 1u && r0.candidate_count == 33u && r0.slot_mask == 3u);
        DF_CHECK(&t, r1.epoch == 3u && r1.requested == 0u && r1.candidate_count == 0u && r1.slot_mask == 0u);
        /* A second re-prompt is not possible (mask is no longer 3). */
        DF_CHECK(&t, dfi_reprompt_side(c1, f1, 1, &s1) == DUOFORGE_E_INVARIANT);
        /* Late response with the old epoch: stale. New epoch, mask 1, valid
         * choice: honest UNSUPPORTED. Mask 3: malformed. */
        duoforge_decision_bundle bd;
        const uint32_t pick[2] = {3u, 0u};
        slot_bundle(&t, c1, f1, &bd, pick);
        duoforge_decision_bundle late = bd;
        late.epoch = 2u;
        late.responses[0].epoch = 2u;
        step_fails(&t, c1, f1, &late, DUOFORGE_E_STALE_EPOCH, "late response after re-prompt");
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_UNSUPPORTED, "re-prompted TURN bundle");
        bd.response_mask = 3u;
        step_fails(&t, c1, f1, &bd, DUOFORGE_E_INVALID_ARGUMENT, "sealed side answering again");
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(f1);
    }

    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
