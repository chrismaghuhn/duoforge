/*
 * T33 duoforge.request.information (white-box fixtures): the perspective-safe
 * observation prototype and the information boundary. Observation bytes of
 * every fixture and player equal the independent oracle; hand-derived
 * perspective rules (own exact, foe percent with the Champions colour flags
 * as last seen, tagged unknowns, private bench order); INFORMATION EQUIVALENCE: paired
 * states with the same authorized information and different hidden
 * information give byte-identical requests, candidates and observations and
 * identical statuses and counts for the viewer; legitimate differences do
 * show; queries are pure; argument checks are atomic.
 */
#include <stdio.h>
#include <string.h>

#include "core/sha256.h"
#include "state/battle_internal.h"
#include "state/knowledge.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"

typedef struct expect {
    const char *name;
    uint32_t player;
    const char *sha;
} expect;

/* Oracle output, verbatim ("observation" lines). */
static const expect expected[] = {
    {"G1", 0, "ff69d7816942571e4b64493bb42652055c2a2fb1009f9b09990a3777ead7fdd8"},
    {"G1", 1, "146fa0041a1e209a55f5a339f9f90b35b0d0cc01e5955945481a66654bd90fdc"},
    {"F1", 0, "acdb2db809f6ec55d86784c90e7b3acc82f33e1263cd51bd4d3dd049d7ee131c"},
    {"F1", 1, "73df927296ecd3adcaaf5b60eaaa4a9b67311ab4d0fc2a3c5960a4ac15803a92"},
    {"F2", 0, "eb19709d172994db1ab2336ef19bf8ff455376b6e66b3ac443e6c9cdb2cfe14a"},
    {"F2", 1, "fd81568a93625a16ee9e07ca4d6eb4e04c5e06749c46dac614a23f3445d78c87"},
    {"G3", 0, "6c53bcf4700ec67d8ca55d32405f8a23e87b6bf5f51aa081ec6de769f0671b65"},
    {"G3", 1, "d0d1524973ac3ef6d2c9fdc583057da565815d72606943c6ce114a9c0086ea82"},
    {"F3", 0, "987771ba510e494cbc750d8d6a4c18a66a248c32e4bd0199807d39b84b6519d0"},
    {"F3", 1, "ddfab8424835db3b7f75a5a3ebd88396ae075f435855379568e3c1a1f3ab4ed2"},
    {"F4", 0, "0237d3886a16097979a3899c3e32b1b45a54cc0f6a6e154847fedc61bcd1c775"},
    {"F4", 1, "47ab3152ab3a3e7b51c08d53555d24af0624ae93e2bc3f50f18a8193f735cd91"},
    {"F5", 0, "3743ceb929060da6f9b55ef2f79182a7192662f6c50031819848fadc201e2133"},
    {"F5", 1, "4ba1c6073c8fece6693ce9b0c51601e446e727a9252e89c2349952b08fe93dc5"},
    {"F6", 0, "3743ceb929060da6f9b55ef2f79182a7192662f6c50031819848fadc201e2133"},
    {"F6", 1, "b57c5ef71388813845ce71101aae51deab74edff96dccebe099a92732dcdd6b7"},
    {"G7", 0, "320b5c5afb75e9f9f19dede83a0eaebb406d0cf9de28d965ed1f61c4a8987458"},
    {"G7", 1, "e94992a5b5f3f97976835e2d5bdea2e7e1a50a088233f62bfbcf3ecc68ef5b03"},
    {"F8", 0, "fc121d62fd7e8c18f2d487e6273abaee5f14805ce6fee45bd9e71c15c21d34aa"},
    {"F8", 1, "33a6d89b64926cf80cc458bbd5c4d6c49ca323088b2395ff8491a9bd3aac1529"},
    {"F9", 0, "0d4f43e3e66f58c3664ffcbac1e392cd648426f2b79be218c9babe4ece216ea2"},
    {"F9", 1, "01c01cbc0912e150daf4d839c43625cf3fe74ab1bf866e36a7c5b2f5d1a12640"},
    {"F10", 0, "5cc63aa3715ddb6abf8b41dcce78bc68a65edc8d17b65db4505cfe8e2db374c3"},
    {"F10", 1, "b497c817cfe9a4a003d2bbe48cfb9830a977c3072892f3247f8ca2250e49b09b"},
    {"F11", 0, "26ca211fda2797e42490dd133f82ea6c57578eca8bc3810342718f310ef6bfdc"},
    {"F11", 1, "6c6c77c2748d318402926b3e703960969f2d42669d970dd0db1263b1afcb944b"},
    {"F12", 0, "c91322ba47059e41723577f64331302b984c9268a83aad89e67dfa7811871179"},
    {"F12", 1, "01c01cbc0912e150daf4d839c43625cf3fe74ab1bf866e36a7c5b2f5d1a12640"},
    {"F13", 0, "27f839bf8d32ada8655b4d7dc99e37a35e472298ad78ca04ca6d0a3684650dc1"},
    {"F13", 1, "eeaed669881a1e64c19fa4311090263bc4fe2132179fef289ba86bf2166a2b2d"},
};

typedef struct fixture {
    const char *name;
    const duoforge_context *ctx;
    duoforge_battle *b;
} fixture;

/* The complete model-visible surface of one viewer. */
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

static void capture(const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer, surface *s)
{
    memset(s, 0, sizeof *s);
    s->req_status = duoforge_battle_request(ctx, b, viewer, &s->req);
    s->cand_status = duoforge_battle_candidates(ctx, b, viewer, s->cands, DUOFORGE_MAX_CANDIDATES, &s->count);
    s->obs_status = duoforge_battle_observe(ctx, b, viewer, &s->obs);
}

static bool same_surface(const surface *x, const surface *y)
{
    return memcmp(x, y, sizeof *x) == 0;
}

/* Paired states: identical surface for `viewer` (statuses, sizes, bytes). */
static void equivalent(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *b,
                       uint32_t viewer, const char *what)
{
    capture(ctx, a, viewer, &sa);
    capture(ctx, b, viewer, &sb);
    if (!DF_CHECK(t, same_surface(&sa, &sb))) {
        fprintf(stderr, "  information leak: %s (viewer %u)\n", what, viewer);
    }
    bool eq = true;
    DF_CHECK(t, duoforge_battle_equal(ctx, a, b, &eq) == DUOFORGE_OK && !eq); /* the pair really differs */
}

static void differs(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *b,
                    uint32_t viewer, const char *what)
{
    capture(ctx, a, viewer, &sa);
    capture(ctx, b, viewer, &sb);
    if (!DF_CHECK(t, !same_surface(&sa, &sb))) {
        fprintf(stderr, "  authorized difference hidden: %s (viewer %u)\n", what, viewer);
    }
}

static const duoforge_member_view *foe_view(const duoforge_context *ctx, const duoforge_battle *b, uint32_t viewer,
                                            uint32_t m, duoforge_observation *o)
{
    if (duoforge_battle_observe(ctx, b, viewer, o) != DUOFORGE_OK) {
        return NULL;
    }
    return &o->sides[1u - viewer].members[m];
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.information");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_context *c4 = df_make_context(&df_config_c4);
    fixture fx[] = {
        {"G1", c1, df_make_g1(c1)},  {"F1", c1, df_make_f1(c1)},   {"F2", c1, df_make_f2(c1)},
        {"G3", c3, df_make_g3(c3)},  {"F3", c3, df_make_f3(c3)},   {"F4", c1, df_make_f4(c1)},
        {"F5", c1, df_make_f5(c1)},  {"F6", c1, df_make_f6(c1)},   {"G7", c4, df_make_g7(c4)},
        {"F8", c4, df_make_f8(c4)},  {"F9", c4, df_make_f9(c4)},   {"F10", c4, df_make_f10(c4)},
        {"F11", c4, df_make_f11(c4)}, {"F12", c4, df_make_f12(c4)}, {"F13", c4, df_make_f13(c4)},
    };
    const unsigned nfx = sizeof fx / sizeof fx[0];

    /* Every fixture and player against the oracle; observation is pure. */
    for (unsigned i = 0; i < sizeof expected / sizeof expected[0]; ++i) {
        const fixture *f = NULL;
        for (unsigned j = 0; j < nfx; ++j) {
            if (strcmp(fx[j].name, expected[i].name) == 0) {
                f = &fx[j];
            }
        }
        if (!DF_CHECK(&t, f != NULL)) {
            continue;
        }
        uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
        uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
        df_encode(f->ctx, f->b, before);
        duoforge_observation o;
        memset(&o, 0xA5, sizeof o);
        DF_CHECK(&t, duoforge_battle_observe(f->ctx, f->b, expected[i].player, &o) == DUOFORGE_OK);
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, dfi_sha256((const uint8_t *)&o, sizeof o, sha));
        DF_CHECK(&t, df_hex_to_bytes(expected[i].sha, want, sizeof want));
        if (!DF_CHECK_BYTES(&t, sha, want, sizeof sha, expected[i].name)) {
            fprintf(stderr, "  %s p%u observation digest differs\n", expected[i].name, expected[i].player);
        }
        df_encode(f->ctx, f->b, after);
        DF_CHECK_BYTES(&t, after, before, sizeof after, "observe is pure");
        DF_CHECK(&t, o.player == expected[i].player && o.epoch == f->b->request_epoch);
    }

    /* Hand-derived perspective rules on F1, viewer 0 (side 1 leads 1 and 3). */
    {
        duoforge_observation o;
        const duoforge_battle *f1 = fx[1].b;
        DF_CHECK(&t, duoforge_battle_observe(c1, f1, 0, &o) == DUOFORGE_OK);
        DF_CHECK(&t, o.boundary_kind == DUOFORGE_BOUNDARY_TURN && o.requested == 1u && o.slot_mask == 3u);
        const duoforge_side_view *own = &o.sides[0];
        const duoforge_side_view *foe = &o.sides[1];
        /* Own: exact HP and PP, locations, private order visible to its owner. */
        DF_CHECK(&t, own->members[2].hp == 120u && own->members[2].hp_max == 120u &&
                         own->members[2].hp_kind == DUOFORGE_HP_EXACT && own->members[2].pp_kind == DUOFORGE_PP_EXACT);
        DF_CHECK(&t, own->members[2].location == DUOFORGE_LOCATION_ACTIVE &&
                         own->members[1].location == DUOFORGE_LOCATION_BENCH &&
                         own->members[4].location == DUOFORGE_LOCATION_NOT_BROUGHT);
        DF_CHECK(&t, own->members[3].pp[3] == 20u && own->members[3].mega_capable == 1u);
        DF_CHECK(&t, own->brought_order[0] == 2u && own->brought_order[3] == 3u && own->occupant[0] == 2u &&
                         own->occupant[1] == 0u && own->member_count == 6u && own->mega_used == 0u);
        /* Foe: sheet open, HP as percent for the seen leads, unknown otherwise,
         * PP unknown, bench order hidden, occupancy public. */
        DF_CHECK(&t, foe->members[1].species_id == 11u && foe->members[1].move_ids[0] == 27u &&
                         foe->members[1].move_count == 4u && foe->members[0].mega_capable == 1u);
        DF_CHECK(&t, foe->members[1].hp_kind == DUOFORGE_HP_PERCENT && foe->members[1].hp == 100u &&
                         foe->members[1].hp_max == 100u && foe->members[1].hp_flag == DUOFORGE_HP_FLAG_NONE &&
                         foe->members[1].location == DUOFORGE_LOCATION_ACTIVE);
        DF_CHECK(&t, foe->members[0].hp_kind == DUOFORGE_HP_UNKNOWN && foe->members[0].hp == 0u &&
                         foe->members[0].hp_max == 0u && foe->members[0].location == DUOFORGE_LOCATION_UNDETERMINED);
        DF_CHECK(&t, foe->members[1].pp_kind == DUOFORGE_PP_UNKNOWN && foe->members[1].pp[0] == 0u);
        DF_CHECK(&t, foe->members[4].species_id == 0u && foe->members[4].hp_kind == 0u); /* unregistered */
        unsigned hidden = 0;
        for (unsigned i = 0; i < DUOFORGE_MAX_ROSTER; ++i) {
            hidden += foe->brought_order[i] == DUOFORGE_ROSTER_NONE ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, hidden, 6u);
        DF_CHECK(&t, foe->occupant[0] == 1u && foe->occupant[1] == 3u && foe->member_count == 4u);
        DF_CHECK(&t, o.sides[0].reserved[0] == 0u && o.sides[1].reserved[1] == 0u);
        /* Before team selection nothing is located and nothing is seen. */
        DF_CHECK(&t, duoforge_battle_observe(c1, fx[0].b, 1, &o) == DUOFORGE_OK);
        DF_CHECK(&t, o.requested == 1u && o.slot_mask == 0u && o.sides[1].members[0].location == 0u &&
                         o.sides[0].members[2].hp_kind == DUOFORGE_HP_UNKNOWN && o.sides[1].members[0].hp_kind == DUOFORGE_HP_EXACT);
        /* A waiting side at a pivot: not requested; the queued rest of the
         * turn is invisible (the surface has no field for it at all). */
        DF_CHECK(&t, duoforge_battle_observe(c1, fx[6].b, 1, &o) == DUOFORGE_OK);
        DF_CHECK(&t, o.requested == 0u && o.slot_mask == 0u && o.boundary_kind == DUOFORGE_BOUNDARY_PIVOT);
        /* A finished battle: nobody is requested. */
        DF_CHECK(&t, duoforge_battle_observe(c4, fx[14].b, 0, &o) == DUOFORGE_OK);
        DF_CHECK(&t, o.requested == 0u && o.slot_mask == 0u && o.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL &&
                         o.sides[1].members[1].hp == 0u && o.sides[1].members[1].hp_kind == DUOFORGE_HP_PERCENT);
    }

    /* Champions HP display at the profile's precision (white-box pokes of the
     * seen foe active s1 roster 1, hp_max 201, viewed by player 0; and of
     * F2's s0 roster 3, hp_max 130, viewed by player 1). The viewer's
     * knowledge follows every HP change of an active member. */
    {
        static const struct {
            uint32_t hp;
            uint32_t pct;
            uint32_t flag;
        } table201[] = {
            {201, 100, DUOFORGE_HP_FLAG_NONE}, {200, 99, DUOFORGE_HP_FLAG_NONE}, {101, 50, DUOFORGE_HP_FLAG_GREEN},
            {100, 49, DUOFORGE_HP_FLAG_NONE},  {41, 20, DUOFORGE_HP_FLAG_YELLOW}, {40, 19, DUOFORGE_HP_FLAG_NONE},
            {2, 1, DUOFORGE_HP_FLAG_NONE},     {1, 1, DUOFORGE_HP_FLAG_NONE},     {0, 0, DUOFORGE_HP_FLAG_NONE},
        };
        duoforge_battle *w = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &w) == DUOFORGE_OK);
        for (unsigned i = 0; i < sizeof table201 / sizeof table201[0]; ++i) {
            duoforge_observation o;
            w->sides[1].members[1].hp = (uint16_t)table201[i].hp;
            dfi_knowledge_refresh_active(w);
            const duoforge_member_view *v = foe_view(c1, w, 0, 1, &o);
            if (DF_CHECK(&t, v != NULL) &&
                !DF_CHECK(&t, v->hp == table201[i].pct && v->hp_flag == table201[i].flag &&
                                  v->hp_kind == DUOFORGE_HP_PERCENT && v->hp_max == 100u)) {
                fprintf(stderr, "  hp %u/201 -> %u flag %u\n", table201[i].hp, v->hp, v->hp_flag);
            }
            /* A fainted occupant keeps its position (and stays ACTIVE). */
            DF_CHECK(&t, v == NULL || v->location == DUOFORGE_LOCATION_ACTIVE);
        }
        duoforge_battle_destroy(w);
        static const struct {
            uint32_t hp;
            uint32_t pct;
            uint32_t flag;
        } table130[] = {
            {26, 20, DUOFORGE_HP_FLAG_RED}, {27, 20, DUOFORGE_HP_FLAG_YELLOW}, {65, 50, DUOFORGE_HP_FLAG_YELLOW},
            {66, 50, DUOFORGE_HP_FLAG_GREEN}, {130, 100, DUOFORGE_HP_FLAG_NONE},
        };
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[2].b, &w) == DUOFORGE_OK);
        for (unsigned i = 0; i < sizeof table130 / sizeof table130[0]; ++i) {
            duoforge_observation o;
            w->sides[0].members[3].hp = (uint16_t)table130[i].hp;
            dfi_knowledge_refresh_active(w);
            const duoforge_member_view *v = foe_view(c1, w, 1, 3, &o);
            if (DF_CHECK(&t, v != NULL) &&
                !DF_CHECK(&t, v->hp == table130[i].pct && v->hp_flag == table130[i].flag)) {
                fprintf(stderr, "  hp %u/130 -> %u flag %u\n", table130[i].hp, v->hp, v->hp_flag);
            }
        }
        /* F2: side 1 saw roster 2 leave at 24 of 120 HP. It is benched but
         * known as last seen (20 percent, red), although it has 40 HP now. */
        duoforge_observation o;
        const duoforge_member_view *v = foe_view(c1, fx[2].b, 1, 2, &o);
        DF_CHECK(&t, v != NULL && v->location == DUOFORGE_LOCATION_BENCH && v->hp_kind == DUOFORGE_HP_PERCENT);
        DF_CHECK(&t, fx[2].b->sides[0].members[2].hp == 40u);
        DF_CHECK(&t, v != NULL && v->hp == 20u && v->hp_max == 100u && v->hp_flag == DUOFORGE_HP_FLAG_RED);
        duoforge_battle_destroy(w);
    }

    /* INFORMATION EQUIVALENCE. Each pair differs only in information hidden
     * from the viewer; the whole surface (statuses, counts, bytes) must agree. */
    {
        duoforge_battle *a = NULL;
        duoforge_battle *b = NULL;
        /* (a) the opponent's private bench order */
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &b) == DUOFORGE_OK);
        b->sides[1].brought_order[2] = 2u;
        b->sides[1].brought_order[3] = 0u;
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        equivalent(&t, c1, a, b, 0, "foe bench order");
        differs(&t, c1, a, b, 1, "own bench order is visible to its owner");
        /* (b) exact HP and PP of an unseen foe reserve */
        DF_CHECK(&t, duoforge_battle_copy(c1, b, a) == DUOFORGE_OK);
        b->sides[1].members[0].hp = 150u;
        b->sides[1].members[0].moves[2].pp = 1u;
        equivalent(&t, c1, a, b, 0, "unseen foe reserve hp/pp");
        /* (c) PP of the active foe */
        DF_CHECK(&t, duoforge_battle_copy(c1, b, a) == DUOFORGE_OK);
        b->sides[1].members[1].moves[0].pp = 3u;
        equivalent(&t, c1, a, b, 0, "active foe pp");
        differs(&t, c1, a, b, 1, "own pp change is visible and changes the domain");
        /* (d) the gameplay RNG, for both viewers */
        DF_CHECK(&t, duoforge_battle_copy(c1, b, a) == DUOFORGE_OK);
        b->rng.state ^= UINT64_C(0x123456789);
        b->rng.draws = 77u;
        equivalent(&t, c1, a, b, 0, "rng");
        equivalent(&t, c1, a, b, 1, "rng");
        /* (e) what the opponent knows about me */
        DF_CHECK(&t, duoforge_battle_copy(c1, b, a) == DUOFORGE_OK);
        b->sides[1].seen_mask = 0x0Fu;
        equivalent(&t, c1, a, b, 0, "opponent knowledge");
        /* (f) exact HP inside one percent bucket with the same flag (F3: the
         * foe active has hp_max 65535; 32768 and 33000 both show 50 GREEN) */
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        DF_CHECK(&t, duoforge_battle_clone(c3, fx[4].b, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c3, fx[4].b, &b) == DUOFORGE_OK);
        a->sides[1].members[0].hp = 32768u;
        b->sides[1].members[0].hp = 33000u;
        dfi_knowledge_refresh_active(a);
        dfi_knowledge_refresh_active(b);
        equivalent(&t, c3, a, b, 0, "same hp bucket and flag");
        b->sides[1].members[0].hp = 32767u; /* 49 percent: a legitimate revelation */
        dfi_knowledge_refresh_active(b);
        differs(&t, c3, a, b, 0, "bucket change");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        /* (g) the rest of the turn at a pivot: the queued actions of the
         * opponent (its move, its target, even whether it still acts) */
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[6].b, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[6].b, &b) == DUOFORGE_OK);
        b->queue[0].move_slot = 3u;
        b->queue[0].target = 1u;
        b->queue[1] = (dfi_queue_record){.kind = DFI_Q_RESIDUAL};
        b->queue[2] = (dfi_queue_record){.kind = DFI_Q_NONE};
        b->queue_len = 2u;
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        equivalent(&t, c1, a, b, 0, "foe actions in the queue");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        /* (j) a seen foe member changes on the bench (F2: s0 roster 2 left
         * at 20 percent): the viewer keeps the last display, the owner sees
         * the exact value */
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[2].b, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[2].b, &b) == DUOFORGE_OK);
        b->sides[0].members[2].hp = 90u;
        b->sides[0].members[2].moves[1].pp = 1u;
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        equivalent(&t, c1, a, b, 1, "benched foe member after it was seen");
        differs(&t, c1, a, b, 0, "own benched member is exact for its owner");
        /* ... and what the viewer remembers is part of its own surface */
        DF_CHECK(&t, duoforge_battle_copy(c1, b, a) == DUOFORGE_OK);
        b->sides[1].knowledge[2].hp_percent = 50u;
        b->sides[1].knowledge[2].hp_flag = (uint8_t)DUOFORGE_HP_FLAG_YELLOW;
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        differs(&t, c1, a, b, 1, "own knowledge is visible to its owner");
        equivalent(&t, c1, a, b, 0, "what the opponent remembers about me");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        /* (h) after a re-prompt of side 0, side 1's sealed choice is hidden:
         * two different sealed choices give side 0 the same surface. */
        duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &b) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_candidates(c1, a, 1, cands, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK && n > 9);
        DF_CHECK(&t, dfi_reprompt_side(c1, a, 0, &cands[3]) == DUOFORGE_OK);
        DF_CHECK(&t, dfi_reprompt_side(c1, b, 0, &cands[9]) == DUOFORGE_OK);
        equivalent(&t, c1, a, b, 0, "sealed choice after re-prompt");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        /* (i) a Struggle state of side 0 (F12) is invisible to side 1: F9 and
         * F12 give side 1 the same surface including statuses. */
        equivalent(&t, c4, fx[10].b, fx[13].b, 1, "foe struggle state");
        differs(&t, c4, fx[10].b, fx[13].b, 0, "own struggle state (UNSUPPORTED request)");
    }

    /* Argument checks: atomic, opaque. */
    {
        duoforge_observation o;
        memset(&o, 0xA5, sizeof o);
        DF_CHECK(&t, duoforge_battle_observe(NULL, fx[1].b, 0, &o) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_observe(c1, NULL, 0, &o) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_observe(c1, fx[1].b, 0, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_observe(c3, fx[1].b, 0, &o) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_observe(c1, fx[1].b, 2, &o) == DUOFORGE_E_INVALID_ARGUMENT);
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &x) == DUOFORGE_OK);
        x->request_mask = 0u;
        DF_CHECK(&t, duoforge_battle_observe(c1, x, 0, &o) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(x);
        DF_CHECK(&t, o.epoch == 0xA5A5A5A5u && o.sides[1].members[5].hp == 0xA5A5u);
    }

    for (unsigned j = 0; j < nfx; ++j) {
        duoforge_battle_destroy(fx[j].b);
    }
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
