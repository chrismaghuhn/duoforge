/*
 * T33 duoforge.request.information (white-box fixtures): observation v2
 * (decision 0007, what a player sees) and the information boundary. Observation bytes of
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
    {"G1", 0, "519c85df6ec7aec4691b26c91594f9ede9c2360e642db5072780e17f81302075"},
    {"G1", 1, "f73889ba0e3e78979179426a4478431b3d6e860216a2b3c413bcf7fb518edca5"},
    {"F1", 0, "b90b26d1e05f9b7dee349f01f09aa7ad9378b1c387c6ac5776e9d309793897e3"},
    {"F1", 1, "2096d4bde010abecabffc5c401bee74d8fc3660bebe2fce48dd275f7ae195c8b"},
    {"F2", 0, "3c15bcf1602601b1debf8ea1d41a27cd2a1967331892663fc03568ad833d7b0c"},
    {"F2", 1, "022aa42984f1c049eb30dc963a32057b8c53073479ea9f0b54b1d5a3473d0c7e"},
    {"G3", 0, "1496e26881f87dbec7b926596d5feb2c03bdd00ba64c38bb3b6a7581947be6d3"},
    {"G3", 1, "4e9d9e306cbf5a975b7260fcdfc96bdfd5aa4d83a9140938e37dc578fc10425b"},
    {"F3", 0, "23780993864e50206768ae9f24069df4292f0f6a8bdd3e9520b4c1b021e0446b"},
    {"F3", 1, "c00eb039517fb449c9ed9f77a43d515b2f6a761f1fdcfa2e2a7eb343c7274fba"},
    {"F4", 0, "02211e642e116e8453f12c64322036141bc59ac8aa217cc1a587e61712b06091"},
    {"F4", 1, "829f70c9baed2f7a4ede61f10dd684cad3fc553531a5704d0f1ea6b5f586020c"},
    {"F5", 0, "24b1e27f98727203941929fe47252ec0cc86b89df5cacd91dabec1b6eafec297"},
    {"F5", 1, "b13bda2077e5d222272d6b54a679d981177e47b58206c784146a08d3f8129e62"},
    {"F6", 0, "07a4af9c6b351cececc629996130111c8210605c9ff97c53f52325f893b18eb0"},
    {"F6", 1, "55d597dcf91e3bb580cf545197bbeb5c35dc7fb28de25dcc57786de19460cfcc"},
    {"G7", 0, "b695b4fdc1d75ebc8297590169ce01aee4b965960d31bb43154937417b63c9ad"},
    {"G7", 1, "e9dc2369c91f31a7267ee538c009c1f13dd71a98c38e04cc4848986a3d791993"},
    {"F8", 0, "8105b3d43f1ecb3b8a80fe75383e20c3f3cc80bfa7bcd1f852011bd88bbb510a"},
    {"F8", 1, "6085308a49bd538bdd8b1fbcd448964eae1f60a3be532fd823d702d03daafe6e"},
    {"F9", 0, "b8fce812c2ffd4773ab2c6b9bb34c1c96269195f012df34cbe07b37c5d6274e3"},
    {"F9", 1, "d80a34fc406b71c1b10ead2cc9f3623a4756c958073b1127d9578e78ee1d14e2"},
    {"F10", 0, "57ed372f30a50b63103a2f0d5fe51f1da24d9111dac79514a69f11c5980c1318"},
    {"F10", 1, "621da480350fea757e11926d39410176ac96e1d162fd67e26028335d411f5c23"},
    {"F11", 0, "1320923b7436197c860e7b3939441e4502a081d0693a6e5a47ffb79d40c2faec"},
    {"F11", 1, "43006eae624736e7233e0896a4bcb037f71768dd3380ff848f0fc5a5c06caae2"},
    {"F12", 0, "9c2d8fd91da6ef06aecc6baab2d465900d2042b955f9ed230a3010af3078f01a"},
    {"F12", 1, "d80a34fc406b71c1b10ead2cc9f3623a4756c958073b1127d9578e78ee1d14e2"},
    {"F13", 0, "524ac28fa34c75ff35f12415d2f475ab8af5986fbc4cb56be83ef4d1e690c6d5"},
    {"F13", 1, "4493bf275ddef82c980089b8f51719d50eb64ea9cc03eb05d55f6747374993e4"},
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
         * PP derived from the uses the viewer saw (none yet: the maximum),
         * bench order hidden, occupancy public (decision 0007). */
        DF_CHECK(&t, foe->members[1].species_id == 11u && foe->members[1].move_ids[0] == 27u &&
                         foe->members[1].move_count == 4u && foe->members[0].mega_capable == 1u);
        DF_CHECK(&t, foe->members[1].hp_kind == DUOFORGE_HP_PERCENT && foe->members[1].hp == 100u &&
                         foe->members[1].hp_max == 100u && foe->members[1].hp_flag == DUOFORGE_HP_FLAG_NONE &&
                         foe->members[1].location == DUOFORGE_LOCATION_ACTIVE);
        DF_CHECK(&t, foe->members[0].hp_kind == DUOFORGE_HP_UNKNOWN && foe->members[0].hp == 0u &&
                         foe->members[0].hp_max == 0u && foe->members[0].location == DUOFORGE_LOCATION_UNDETERMINED);
        DF_CHECK(&t, foe->members[1].pp_kind == DUOFORGE_PP_DERIVED && foe->members[1].pp_max[0] != 0u);
        for (unsigned k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            DF_CHECK(&t, foe->members[1].pp[k] == foe->members[1].pp_max[k]);
        }
        /* Active positions: neutral stages, nothing locked, no target (none
         * is never encoded as position 0). */
        DF_CHECK(&t, foe->positions[0].stages[0] == 6u && foe->positions[0].locked_slot == DUOFORGE_MOVE_SLOT_NONE &&
                         foe->positions[0].locked_target == DUOFORGE_TARGET_NONE && own->positions[1].stages[4] == 6u &&
                         own->positions[1].locked_target == DUOFORGE_TARGET_NONE && own->positions[1].protecting == 0u);
        /* Own sheet: stats and stat points; the foe's stay hidden. */
        DF_CHECK(&t, own->members[0].stat_points[0] == f1->sides[0].members[0].stat_points[0] &&
                         own->members[0].stats[4] == f1->sides[0].members[0].stats[4]);
        for (unsigned i = 0; i < 5u; ++i) {
            DF_CHECK(&t, foe->members[1].stats[i] == 0u);
        }
        for (unsigned i = 0; i < 6u; ++i) {
            DF_CHECK(&t, foe->members[1].stat_points[i] == 0u);
        }
        DF_CHECK(&t, foe->members[4].species_id == 0u && foe->members[4].hp_kind == 0u); /* unregistered */
        unsigned hidden = 0;
        for (unsigned i = 0; i < DUOFORGE_MAX_ROSTER; ++i) {
            hidden += foe->brought_order[i] == DUOFORGE_ROSTER_NONE ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, hidden, 6u);
        DF_CHECK(&t, foe->occupant[0] == 1u && foe->occupant[1] == 3u && foe->member_count == 4u);
        DF_CHECK(&t, o.sides[0].reserved == 0u && o.sides[1].reserved == 0u && o.reserved == 0u);
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
