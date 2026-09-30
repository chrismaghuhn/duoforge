/*
 * T30 duoforge.request.domain (black-box unless marked): for every fixture
 * and player the request fields, the exact candidate count and the SHA-256
 * of the concatenated canonical candidates equal the independent oracle
 * (tools/state_model/state_v3_model.py, "domain" lines); hand-derived small
 * domains are listed literally; enumeration is stable (same bytes twice) and
 * pure (state and rng.draws unchanged); the output convention (decision 0005
 * section 7): E_CAPACITY writes only the required count; Struggle states are
 * E_UNSUPPORTED; the profile bound DUOFORGE_MAX_CANDIDATES holds, with the
 * maximal synthetic fixtures pinned by hand (720 picks; 636 joint choices).
 */
#include <stdio.h>
#include <string.h>

#include "core/sha256.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

#define UNSUP 0xFFFFFFFFu

typedef struct expect {
    const char *name;
    uint32_t player;
    uint32_t epoch;
    uint32_t boundary;
    uint32_t requested;
    uint32_t slots;
    uint32_t count; /* UNSUP: request and candidates fail with E_UNSUPPORTED */
    const char *sha;
} expect;

/* Oracle output, verbatim. */
static const expect expected[] = {
    {"G1", 0, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 360, "c4745d6c8c511804170b61cbcf65adcee420166b1b8d34ed2408f88fccfb5460"},
    {"G1", 1, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 24, "eb37dc6495e1f8c7206b8508ac2efb246cd6d6fc6aab246a25525619bb2d08f2"},
    {"F1", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 33, "8a6b1826267bbe3cbda3ac98feac40f1fa9d8a512a8e6f273f5bd627781914d7"},
    {"F1", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 118, "606414e6bec06a82fbe5fe31870155bdaf713ff74918784057a7cac2353244ce"},
    {"F2", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 12, "7dcdf75fa19a91f33855d00e10ec774a3d59d0eddacb09fb98800a3ce7c5f83e"},
    {"F2", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 1, 12, "442e5cd211a4e210e94657bc8f2161a1c5f2e5691db9de4918168694925f2045"},
    {"G3", 0, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 3, "286c959d35277c30495a2102299552a5dc6384a9fede4a3bed05e5ef759625cd"},
    {"G3", 1, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 2, "54145c8d9b9e8aaf7f20e233f523f02a16834826621daccd55e70246b841489d"},
    {"F3", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 1, 3, "f8defb56cc6c1e3f93050ad4542b3ff06a2b3ea3610fb0e5a8918be7d44a2301"},
    {"F3", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 1, 4, "d84fda3d2165211b65e1a370738a76b726cff79022de7732c641d52a7e390568"},
    {"F4", 0, 3, DUOFORGE_BOUNDARY_REPLACEMENT, 1, 1, 2, "31582da76c915a65f7b9c0d9998665d72918bd48f278246e494af0d904c71906"},
    {"F4", 1, 3, DUOFORGE_BOUNDARY_REPLACEMENT, 1, 2, 2, "2f843b9158529152b9848cacf462e32c711cf37be902c053c854e5e7d93708d1"},
    {"F5", 0, 3, DUOFORGE_BOUNDARY_PIVOT, 1, 1, 2, "31582da76c915a65f7b9c0d9998665d72918bd48f278246e494af0d904c71906"},
    {"F5", 1, 3, DUOFORGE_BOUNDARY_PIVOT, 0, 0, 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"F6", 0, 3, DUOFORGE_BOUNDARY_PIVOT, 1, 1, 2, "31582da76c915a65f7b9c0d9998665d72918bd48f278246e494af0d904c71906"},
    {"F6", 1, 3, DUOFORGE_BOUNDARY_PIVOT, 1, 2, 2, "2f843b9158529152b9848cacf462e32c711cf37be902c053c854e5e7d93708d1"},
    {"G7", 0, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 12, "716980ace9a7dc25e09c44d3de89072c1a1a88cc9f48ed032078aaa23b4ab12a"},
    {"G7", 1, 1, DUOFORGE_BOUNDARY_TEAM_SELECTION, 1, 0, 6, "7430e635ef2db845fddc204a3da86cbe3154486b3cb5949615313c281afd2c85"},
    {"F8", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 6, "8b3e55cfc0ba718bbd2a0ad3d26cc873e0f050990c9a8920726f06c270358896"},
    {"F8", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 28, "d3cbc0a0e80acf5bed8e74150bca7d5698ca3266b84be0ca7ea099c13c931081"},
    {"F9", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 72, "5a1648e545dc529e7987770ac75157ca11a8efc627a40b7b2ab11d0726d66233"},
    {"F9", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 16, "84a9e8f87772fc3e05683e4a95072caf35e6a147649b5d8fc149f1371025fc84"},
    {"F10", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 24, "9d21e189c0ba3e35e05604cb3c5fbe6084b8628b1bc0bd9691350e9e257c5ce5"},
    {"F10", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 4, "b96ebe01bf5c9923865053904ea3b3dd8aeffb89868972b2088b2439c7752251"},
    {"F11", 0, 3, DUOFORGE_BOUNDARY_REPLACEMENT, 1, 3, 1, "8fc0a1589628b1ab966f1ec4c4f78d951ae1b0849fbad4063d178f9a2d171fce"},
    {"F11", 1, 3, DUOFORGE_BOUNDARY_REPLACEMENT, 0, 0, 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"F12", 0, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, UNSUP, ""},
    {"F12", 1, 2, DUOFORGE_BOUNDARY_TURN, 1, 3, 16, "84a9e8f87772fc3e05683e4a95072caf35e6a147649b5d8fc149f1371025fc84"},
    {"F13", 0, 3, DUOFORGE_BOUNDARY_TERMINAL, 0, 0, 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {"F13", 1, 3, DUOFORGE_BOUNDARY_TERMINAL, 0, 0, 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
};

typedef struct fixture {
    const char *name;
    const duoforge_context *ctx;
    duoforge_battle *b;
} fixture;

static duoforge_side_choice buf_a[DUOFORGE_MAX_CANDIDATES];
static duoforge_side_choice buf_b[DUOFORGE_MAX_CANDIDATES];

static void encode_raw(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE])
{
    df_encode(ctx, b, out);
}

/* One fixture/player against the oracle row; returns the count. */
static void check_row(df_test *t, const fixture *f, const expect *e)
{
    uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
    encode_raw(f->ctx, f->b, before);
    duoforge_request r;
    memset(&r, 0xA5, sizeof r);
    duoforge_status st = duoforge_battle_request(f->ctx, f->b, e->player, &r);
    uint32_t count = 0xDEADBEEFu;
    memset(buf_a, 0xA5, sizeof buf_a);
    if (e->count == UNSUP) {
        DF_CHECK(t, st == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, r.epoch == 0xA5A5A5A5u); /* untouched */
        st = duoforge_battle_candidates(f->ctx, f->b, e->player, buf_a, DUOFORGE_MAX_CANDIDATES, &count);
        DF_CHECK(t, st == DUOFORGE_E_UNSUPPORTED && count == 0xDEADBEEFu);
        encode_raw(f->ctx, f->b, after);
        DF_CHECK_BYTES(t, after, before, sizeof after, "unsupported request is pure");
        return;
    }
    if (!DF_CHECK(t, st == DUOFORGE_OK)) {
        fprintf(stderr, "  %s p%u request: %s\n", e->name, e->player, duoforge_status_name(st));
        return;
    }
    const bool fields = r.epoch == e->epoch && r.boundary_kind == e->boundary && r.player == e->player &&
                        r.requested == e->requested && r.slot_mask == e->slots && r.candidate_count == e->count;
    if (!DF_CHECK(t, fields)) {
        fprintf(stderr, "  %s p%u request epoch=%u kind=%u req=%u slots=%u count=%u\n", e->name, e->player,
                r.epoch, r.boundary_kind, r.requested, r.slot_mask, r.candidate_count);
    }
    st = duoforge_battle_candidates(f->ctx, f->b, e->player, buf_a, DUOFORGE_MAX_CANDIDATES, &count);
    DF_CHECK(t, st == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, count, e->count);
    DF_CHECK(t, count <= DUOFORGE_MAX_CANDIDATES);
    if (count > DUOFORGE_MAX_CANDIDATES) {
        return;
    }
    /* Digest of the concatenated records (padding-free, zero-filled). */
    uint8_t sha[DUOFORGE_DIGEST_SIZE];
    uint8_t want[DUOFORGE_DIGEST_SIZE];
    DF_CHECK(t, dfi_sha256((const uint8_t *)buf_a, (size_t)count * sizeof buf_a[0], sha));
    DF_CHECK(t, df_hex_to_bytes(e->sha, want, sizeof want));
    if (!DF_CHECK_BYTES(t, sha, want, sizeof sha, e->name)) {
        fprintf(stderr, "  %s p%u candidate digest differs\n", e->name, e->player);
    }
    /* Every record carries the request epoch, the side and the right kind;
     * unrequested slots are all-zero; reserved bytes are zero. */
    unsigned bad = 0;
    for (uint32_t i = 0; i < count; ++i) {
        const duoforge_side_choice *c = &buf_a[i];
        bad += c->epoch != e->epoch || c->side != e->player ? 1u : 0u;
        bad += c->reserved[0] != 0u || c->reserved[1] != 0u || c->reserved[2] != 0u ? 1u : 0u;
        if (e->boundary == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
            bad += c->kind != DUOFORGE_CHOICE_TEAM_SELECTION ? 1u : 0u;
        } else {
            bad += c->kind != DUOFORGE_CHOICE_SLOTS || c->pick_count != 0u ? 1u : 0u;
            for (unsigned k = 0; k < 2; ++k) {
                const bool req = ((e->slots >> k) & 1u) != 0u;
                bad += (!req && c->slots[k].kind != DUOFORGE_SLOT_NONE) ? 1u : 0u;
                bad += (req && c->slots[k].kind == DUOFORGE_SLOT_NONE) ? 1u : 0u;
                bad += (c->slots[k].reserved[0] != 0u || c->slots[k].reserved[1] != 0u ||
                        c->slots[k].reserved[2] != 0u) ? 1u : 0u;
            }
        }
    }
    DF_CHECK_EQ_U64(t, bad, 0u);
    /* Candidates are pairwise distinct. */
    unsigned dup = 0;
    for (uint32_t i = 0; i < count; ++i) {
        for (uint32_t j = i + 1; j < count; ++j) {
            dup += memcmp(&buf_a[i], &buf_a[j], sizeof buf_a[0]) == 0 ? 1u : 0u;
        }
    }
    DF_CHECK_EQ_U64(t, dup, 0u);
    /* Stable: a second enumeration gives identical bytes. */
    memset(buf_b, 0x5A, sizeof buf_b);
    uint32_t count2 = 0;
    DF_CHECK(t, duoforge_battle_candidates(f->ctx, f->b, e->player, buf_b, DUOFORGE_MAX_CANDIDATES, &count2) ==
                    DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, count2, count);
    DF_CHECK(t, memcmp(buf_a, buf_b, (size_t)count * sizeof buf_a[0]) == 0);
    /* Pure: the state (including rng.draws) is unchanged. */
    encode_raw(f->ctx, f->b, after);
    DF_CHECK_BYTES(t, after, before, sizeof after, "queries are pure");
    /* Output convention: too small -> E_CAPACITY, only *out_count written. */
    if (count > 0) {
        memset(buf_b, 0x5A, sizeof buf_b);
        uint8_t pattern[sizeof buf_b];
        memset(pattern, 0x5A, sizeof pattern);
        count2 = 0xDEADBEEFu;
        DF_CHECK(t, duoforge_battle_candidates(f->ctx, f->b, e->player, buf_b, count - 1u, &count2) ==
                        DUOFORGE_E_CAPACITY);
        DF_CHECK_EQ_U64(t, count2, count);
        DF_CHECK(t, memcmp(buf_b, pattern, sizeof buf_b) == 0);
        count2 = 0xDEADBEEFu;
        DF_CHECK(t, duoforge_battle_candidates(f->ctx, f->b, e->player, NULL, 0u, &count2) == DUOFORGE_E_CAPACITY);
        DF_CHECK_EQ_U64(t, count2, count);
        /* Exactly enough and more than enough both succeed; the tail is untouched. */
        count2 = 0;
        DF_CHECK(t, duoforge_battle_candidates(f->ctx, f->b, e->player, buf_b, count, &count2) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, count2, count);
        DF_CHECK(t, memcmp(buf_b, buf_a, (size_t)count * sizeof buf_a[0]) == 0);
        if (count < DUOFORGE_MAX_CANDIDATES) {
            DF_CHECK(t, memcmp((const uint8_t *)&buf_b[count], pattern, sizeof buf_b[0]) == 0);
        }
    } else {
        count2 = 0xDEADBEEFu;
        DF_CHECK(t, duoforge_battle_candidates(f->ctx, f->b, e->player, NULL, 0u, &count2) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, count2, 0u);
    }
}

static void expect_cmd(df_test *t, const duoforge_slot_command *c, uint32_t kind, uint32_t move_slot,
                       uint32_t target, uint32_t mega, uint32_t reserve)
{
    DF_CHECK(t, c->kind == kind && c->move_slot == move_slot && c->target == target && c->mega == mega &&
                    c->reserve == reserve);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.request.domain");

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

    for (unsigned i = 0; i < sizeof expected / sizeof expected[0]; ++i) {
        const fixture *f = NULL;
        for (unsigned j = 0; j < nfx; ++j) {
            if (strcmp(fx[j].name, expected[i].name) == 0) {
                f = &fx[j];
            }
        }
        if (DF_CHECK(&t, f != NULL)) {
            check_row(&t, f, &expected[i]);
        }
    }

    /* Hand-derived small domains (independent of the oracle): G3 picks,
     * F3 turn choices, F4 forced replacements. */
    {
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c3, fx[3].b, 0, buf_a, 8, &n) == DUOFORGE_OK && n == 3);
        for (unsigned i = 0; i < 3; ++i) {
            DF_CHECK(&t, buf_a[i].kind == DUOFORGE_CHOICE_TEAM_SELECTION && buf_a[i].pick_count == 1u &&
                             buf_a[i].picks[0] == i);
        }
        /* F3 p0: roster 2 at s0a, one move (id 2, NORMAL) -> targets 1, 2, 3. */
        DF_CHECK(&t, duoforge_battle_candidates(c3, fx[4].b, 0, buf_a, 8, &n) == DUOFORGE_OK && n == 3);
        expect_cmd(&t, &buf_a[0].slots[0], DUOFORGE_SLOT_MOVE, 0, 1, 0, 0);
        expect_cmd(&t, &buf_a[1].slots[0], DUOFORGE_SLOT_MOVE, 0, 2, 0, 0);
        expect_cmd(&t, &buf_a[2].slots[0], DUOFORGE_SLOT_MOVE, 0, 3, 0, 0);
        expect_cmd(&t, &buf_a[2].slots[1], DUOFORGE_SLOT_NONE, 0, 0, 0, 0);
        /* F3 p1: roster 0 at s1a, moves id 31 (ANY -> 0, 1, 3) and 30 (spread -> NONE). */
        DF_CHECK(&t, duoforge_battle_candidates(c3, fx[4].b, 1, buf_a, 8, &n) == DUOFORGE_OK && n == 4);
        expect_cmd(&t, &buf_a[0].slots[0], DUOFORGE_SLOT_MOVE, 0, 0, 0, 0);
        expect_cmd(&t, &buf_a[1].slots[0], DUOFORGE_SLOT_MOVE, 0, 1, 0, 0);
        expect_cmd(&t, &buf_a[2].slots[0], DUOFORGE_SLOT_MOVE, 0, 3, 0, 0);
        expect_cmd(&t, &buf_a[3].slots[0], DUOFORGE_SLOT_MOVE, 1, DUOFORGE_TARGET_NONE, 0, 0);
        /* F4 p0: slot a fainted; alive reserves 1 and 3; exactly one switch. */
        DF_CHECK(&t, duoforge_battle_candidates(c1, fx[5].b, 0, buf_a, 8, &n) == DUOFORGE_OK && n == 2);
        expect_cmd(&t, &buf_a[0].slots[0], DUOFORGE_SLOT_SWITCH, 0, 0, 0, 1);
        expect_cmd(&t, &buf_a[1].slots[0], DUOFORGE_SLOT_SWITCH, 0, 0, 0, 3);
        expect_cmd(&t, &buf_a[1].slots[1], DUOFORGE_SLOT_NONE, 0, 0, 0, 0);
        /* F11 p0: both actives fainted and no reserve (F9 brought {0, 2}), so
         * min(2, 0) = 0 switches: the single choice is (PASS, PASS). */
        DF_CHECK(&t, duoforge_battle_candidates(c4, fx[12].b, 0, buf_a, 8, &n) == DUOFORGE_OK && n == 1);
        expect_cmd(&t, &buf_a[0].slots[0], DUOFORGE_SLOT_PASS, 0, 0, 0, 0);
        expect_cmd(&t, &buf_a[0].slots[1], DUOFORGE_SLOT_PASS, 0, 0, 0, 0);
        /* F2 p0: s0a holds roster 3 (moves 12..15 = N N S N -> 3+3+1+3 = 10;
         * Mega already used), s0b holds fainted roster 0 -> PASS; alive
         * reserves are 1 (hp 57) and 2 (vacated earlier): 10 + 2 = 12. */
        DF_CHECK(&t, duoforge_battle_candidates(c1, fx[2].b, 0, buf_a, 16, &n) == DUOFORGE_OK && n == 12);
        expect_cmd(&t, &buf_a[9].slots[0], DUOFORGE_SLOT_MOVE, 3, 3, 0, 0);
        expect_cmd(&t, &buf_a[10].slots[0], DUOFORGE_SLOT_SWITCH, 0, 0, 0, 1);
        expect_cmd(&t, &buf_a[11].slots[0], DUOFORGE_SLOT_SWITCH, 0, 0, 0, 2);
        expect_cmd(&t, &buf_a[11].slots[1], DUOFORGE_SLOT_PASS, 0, 0, 0, 0);
    }

    /* Mega declarations: F9 p0 leads 0 and 2 both hold stones; a joint choice
     * never declares two, and F10 (Mega used) offers none. */
    {
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c4, fx[10].b, 0, buf_a, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        unsigned single = 0;
        unsigned dbl = 0;
        for (uint32_t i = 0; i < n; ++i) {
            const unsigned m = (buf_a[i].slots[0].mega ? 1u : 0u) + (buf_a[i].slots[1].mega ? 1u : 0u);
            single += m == 1u ? 1u : 0u;
            dbl += m == 2u ? 1u : 0u;
            DF_CHECK(&t, buf_a[i].slots[0].kind != DUOFORGE_SLOT_SWITCH || buf_a[i].slots[0].mega == 0u);
        }
        DF_CHECK_EQ_U64(&t, dbl, 0u);
        DF_CHECK(&t, single > 0u);
        DF_CHECK(&t, duoforge_battle_candidates(c4, fx[11].b, 0, buf_a, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        unsigned any = 0;
        for (uint32_t i = 0; i < n; ++i) {
            any += (uint32_t)buf_a[i].slots[0].mega + (uint32_t)buf_a[i].slots[1].mega;
        }
        DF_CHECK_EQ_U64(&t, any, 0u);
    }

    /* Argument checks are atomic and reveal nothing: NULL, context mismatch,
     * player 2, corrupt state (opaque INVARIANT). */
    {
        duoforge_request r;
        uint32_t n = 0xDEADBEEFu;
        memset(&r, 0xA5, sizeof r);
        DF_CHECK(&t, duoforge_battle_request(NULL, fx[1].b, 0, &r) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_request(c1, NULL, 0, &r) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_request(c1, fx[1].b, 0, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_request(c3, fx[1].b, 0, &r) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_request(c1, fx[1].b, 2, &r) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_request(c1, fx[1].b, 0xFFFFFFFFu, &r) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, r.epoch == 0xA5A5A5A5u);
        memset(buf_a, 0xA5, sizeof buf_a[0]);
        DF_CHECK(&t, duoforge_battle_candidates(NULL, fx[1].b, 0, buf_a, 1, &n) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_candidates(c1, NULL, 0, buf_a, 1, &n) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_candidates(c1, fx[1].b, 0, NULL, 1, &n) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_candidates(c1, fx[1].b, 0, buf_a, 1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_candidates(c3, fx[1].b, 0, buf_a, 1, &n) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_candidates(c1, fx[1].b, 2, buf_a, 1, &n) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, n == 0xDEADBEEFu && buf_a[0].epoch == 0xA5A5A5A5u);
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, fx[1].b, &x) == DUOFORGE_OK);
        x->sides[1].members[0].moves[0].pp = 99u; /* white-box corruption */
        DF_CHECK(&t, duoforge_battle_request(c1, x, 0, &r) == DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, duoforge_battle_candidates(c1, x, 0, buf_a, 1, &n) == DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, r.epoch == 0xA5A5A5A5u && n == 0xDEADBEEFu && buf_a[0].epoch == 0xA5A5A5A5u);
        duoforge_battle_destroy(x);
    }

    /* Profile bound: 6 registered, 6 brought -> 720 ordered picks; a TURN
     * state with two 4-move NORMAL stone holders and four reserves gives
     * 28 x 28 - 4 same-reserve pairs - 12 x 12 double-Mega pairs = 636. */
    {
        duoforge_context_config cfg = df_config_c1;
        cfg.brought_count = 6u;
        duoforge_context *c6 = df_make_context(&cfg);
        duoforge_battle_setup s;
        memset(&s, 0, sizeof s);
        s.rng_initstate = 1u;
        s.rng_initseq = 1u;
        for (unsigned side = 0; side < 2; ++side) {
            s.sides[side].member_count = 6u;
            for (unsigned m = 0; m < 6; ++m) {
                duoforge_member_setup *mem = &s.sides[side].members[m];
                mem->species_id = m;
                mem->hp_max = 10u;
                mem->move_count = 4u;
                mem->mega_capable = 1u;
                for (unsigned k = 0; k < 4; ++k) {
                    mem->moves[k].move_id = 0u; /* T1[0] = NORMAL */
                    mem->moves[k].pp_max = 1u;
                }
            }
        }
        duoforge_battle *g = df_make_battle(c6, &s);
        duoforge_request r;
        DF_CHECK(&t, duoforge_battle_request(c6, g, 0, &r) == DUOFORGE_OK && r.candidate_count == 720u);
        uint32_t n = 0;
        DF_CHECK(&t, duoforge_battle_candidates(c6, g, 1, buf_a, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, n, 720u);
        DF_CHECK(&t, buf_a[0].picks[0] == 0u && buf_a[0].picks[5] == 5u);
        DF_CHECK(&t, buf_a[719].picks[0] == 5u && buf_a[719].picks[5] == 0u);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = 1u;
        bd.response_mask = 3u;
        for (unsigned side = 0; side < 2; ++side) {
            bd.responses[side] = buf_a[0];
            bd.responses[side].side = (uint8_t)side;
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(c6, g, &bd, &res) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_request(c6, g, 0, &r) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, r.candidate_count, 636u);
        DF_CHECK(&t, duoforge_battle_candidates(c6, g, 0, buf_a, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, n, 636u);
        duoforge_battle_destroy(g);
        duoforge_context_destroy(c6);
    }

    for (unsigned j = 0; j < nfx; ++j) {
        duoforge_battle_destroy(fx[j].b);
    }
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
