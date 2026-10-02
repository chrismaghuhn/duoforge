/*
 * duoforge.state.pool_tail (white-box): the POOL state tail of decision 0015 section 7, schema 0x0103 = "v3 + pool
 * tail rev 1".
 *
 * The tail is part of the state under the two POOL kinds only: 42 more bytes (1051 in all) that the encoder, the
 * decoder, the digest, equal, the invariants, clone and copy all carry; under CLOSURE, CLOSURE_DEV, TEAM_C and
 * TEAM_C_DEV it is absent (all zero in memory, not in the encoding) and the states of those kinds are byte for byte
 * what they were: the digests below were taken from the tree before the tail existed. Nothing writes the tail yet
 * (G3 is the container); the tests set it by hand.
 *
 * The independent oracle is tools/state_model/state_v3_model.py (run with --pool-tail): the envelope, the 42 tail
 * bytes of the example and, for every tail byte, how many of the 255 other values the decoder accepts or refuses
 * with which invariant, are its output.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "codec/state_codec.h"
#include "core/sha256.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

/* The model's envelope of a POOL state (tools/state_model, "pool_tail envelope"): magic, kind 2, schema 0x0103,
 * semantics 3, length 1051. */
static const char ENVELOPE_HEX[] = "8944554f0d0a1a0a02000301030000001b040000";
/* The model's tail bytes of the example below ("pool_tail example"). */
static const char TAIL_HEX[] = "010000010203020500050000010200051200000000000000040401000300000000000000010000000000";

/* For every tail byte of the example: how many of the 255 other values give OK, TAIL_SIDE, TAIL_POSITION,
 * TAIL_MEMBER and TAIL_RESERVED ("pool_tail_sweep_c" of the model). */
static const unsigned sweep[DFI_ENC_TAIL_SIZE][5] = {
    {1, 254, 0, 0, 0},
    {0, 0, 0, 0, 255},
    {0, 0, 0, 0, 255},
    {5, 0, 250, 0, 0},
    {3, 0, 252, 0, 0},
    {3, 0, 252, 0, 0},
    {2, 0, 253, 0, 0},
    {5, 0, 250, 0, 0},
    {0, 0, 0, 0, 255},
    {5, 0, 250, 0, 0},
    {0, 0, 255, 0, 0},
    {0, 0, 255, 0, 0},
    {2, 0, 253, 0, 0},
    {5, 0, 250, 0, 0},
    {0, 0, 0, 0, 255},
    {18, 0, 0, 237, 0},
    {18, 0, 0, 237, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
    {1, 254, 0, 0, 0},
    {0, 0, 0, 0, 255},
    {0, 0, 0, 0, 255},
    {5, 0, 250, 0, 0},
    {3, 0, 252, 0, 0},
    {3, 0, 252, 0, 0},
    {2, 0, 253, 0, 0},
    {5, 0, 250, 0, 0},
    {0, 0, 0, 0, 255},
    {5, 0, 250, 0, 0},
    {0, 0, 255, 0, 0},
    {0, 0, 255, 0, 0},
    {2, 0, 253, 0, 0},
    {5, 0, 250, 0, 0},
    {0, 0, 0, 0, 255},
    {18, 0, 0, 237, 0},
    {18, 0, 0, 237, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
    {0, 0, 0, 255, 0},
};

/* Digests of the states of the four other kinds (Team A against B, or against Team C), at creation, after team
 * selection and after the first turn: taken from the tree before the POOL tail existed. */
static const struct {
    const char *kind;
    const char *point;
    const char *hex;
} before_the_tail[] = {
    {"CLOSURE", "created", "5af24be1c7439f0dd611e9e3b78711f007945abbe06e3637d4f163088232656c"},
    {"CLOSURE", "teams", "0b3fc1af884ad1255b177d27105ded8bbb86aefbc9190448975f21788b43fa4c"},
    {"CLOSURE", "turn1", "b3b20b79bcbbf1f6c989131f9bd439a94d09755d25d7fe7e3015b73d089ada80"},
    {"CLOSURE_DEV", "created", "eb90a7f7bf3057d0f43efeb01dd6229b26ee9fb8b83d63b66581204990b81c0c"},
    {"CLOSURE_DEV", "teams", "41a4977c5a594fa3ff3fcd41307e824030bbe97970457b28a1fc5be4197a7898"},
    {"CLOSURE_DEV", "turn1", "0859fe52c16fffe0eea65d6d0ca82725e4a28555d6a9fb22d2e445adfcd0d6e7"},
    {"TEAM_C", "created", "629f0ce576f616dbaf12e6d6e63fbfb9c4a09c973a1145aaaa06afa10a8ef629"},
    {"TEAM_C", "teams", "455cd10551e6c1a7e0a9c79b916eade004844b7166f5d06fa3559a913e052d9a"},
    {"TEAM_C", "turn1", "74108fd1935f4e516b2636d391535dd9aeeaea3f55a46c7587c26255a4862371"},
    {"TEAM_C_DEV", "created", "c85ba8c7e50aa37d9426d1a619bde9b5101f63db54d05b6517cf74ca53d7d6d1"},
    {"TEAM_C_DEV", "teams", "edb5bdf6376eee8c41535e75f6f5cc5fe1869aa54fd22f1926f7c1995676f722"},
    {"TEAM_C_DEV", "turn1", "8c1d956b020a13e14be5d7b60681f43ba9dc729753c94dd8843ca24627dd1430"}
};

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
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* Turn 1 of the reference teams' leads (valid for any items). */
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
            c->slots[slot].target = plan[side][slot][1];
        }
    }
}

static void step_ok(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const duoforge_decision_bundle *bd,
                    const char *what)
{
    duoforge_step_result res;
    if (!DF_CHECK(t, duoforge_battle_step(ctx, b, bd, &res) == DUOFORGE_OK)) {
        fprintf(stderr, "  step %s failed\n", what);
    }
}

/* A battle of `ctx` at the first TURN boundary: Team A against B, or against Team C for the TEAM_C kinds. */
static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx, bool team_c)
{
    duoforge_battle_setup s;
    df_setup_teams(&s);
    if (team_c) {
        df_put_team_c(&s.sides[1]);
    }
    duoforge_battle *b = df_make_battle(ctx, &s);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    step_ok(t, ctx, b, &bd, "team selection");
    return b;
}

/* The example of the model: a value in every field, valid for the leads 0 and 1 of both sides. */
static void set_example_tail(duoforge_battle *b)
{
    memset(&b->tail, 0, sizeof b->tail);
    dfi_tail_side *a = &b->tail.sides[0];
    a->wide_guard = 1u;
    a->positions[0] = (dfi_tail_pos){1u, 2u, 3u, 2u, 5u};
    a->positions[1] = (dfi_tail_pos){5u, 0u, 0u, 1u, 2u};
    a->soak_type[0] = 5u;
    a->soak_type[1] = 18u;
    dfi_tail_side *c = &b->tail.sides[1];
    c->positions[0] = (dfi_tail_pos){4u, 4u, 1u, 0u, 3u};
    c->soak_type[0] = 1u;
}

static void digest_of(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_DIGEST_SIZE])
{
    DF_CHECK(t, duoforge_battle_digest(ctx, b, out) == DUOFORGE_OK);
}

static void check_hex(df_test *t, const uint8_t *got, const char *hex, size_t n, const char *what)
{
    uint8_t want[DFI_STATE_ENCODED_MAX];
    DF_CHECK(t, n <= sizeof want && df_hex_to_bytes(hex, want, n));
    DF_CHECK_BYTES(t, got, want, n, what);
}

/* The decode of `bytes` under `ctx` through both entry points: they agree, and nothing is written on failure. */
static duoforge_status decode_both(df_test *t, const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                   dfi_invariant *inv)
{
    uint8_t *in = df_heap_copy(bytes, size);
    duoforge_battle *made = NULL;
    const duoforge_status s1 = duoforge_battle_create_decoded(ctx, in, size, &made);
    duoforge_battle_destroy(made);
    duoforge_battle tmp;
    memset(&tmp, 0xA5, sizeof tmp);
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status s2 = dfi_decode_state(ctx, in, size, &tmp, &got);
    DF_CHECK(t, s1 == s2);
    df_free(in);
    if (inv != NULL) {
        *inv = got;
    }
    return s2;
}

/* The bytes of the tail of a state in memory (the struct has no padding: every field is a byte). */
static uint8_t *tail_byte(duoforge_battle *b, size_t i)
{
    return &((uint8_t *)&b->tail)[i];
}

static const char *inv_name(dfi_invariant inv)
{
    return dfi_invariant_name(inv);
}

/* Patches the envelope of an artifact: schema and total length. */
static void set_envelope(uint8_t *bytes, uint32_t schema, uint32_t length)
{
    bytes[DFI_ENVELOPE_SCHEMA_OFF] = (uint8_t)(schema & 0xFFu);
    bytes[DFI_ENVELOPE_SCHEMA_OFF + 1u] = (uint8_t)((schema >> 8u) & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF] = (uint8_t)(length & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF + 1u] = (uint8_t)((length >> 8u) & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF + 2u] = 0u;
    bytes[DFI_ENVELOPE_LENGTH_OFF + 3u] = 0u;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_tail");
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
    duoforge_context *kc = df_make_context(&df_config_team_c);
    duoforge_context *kd = df_make_context(&df_config_team_c_dev);
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kq = df_make_context(&df_config_pool_dev);
    duoforge_context *c1 = df_make_context(&df_config_c1);

    /* The layout: sizes, schema ids, which kinds carry the tail. */
    {
        DF_CHECK_EQ_U64(&t, DFI_STATE_POOL_ENCODED_SIZE, 1051u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_ENCODED_MAX, DF_STATE_ENCODED_MAX);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_OFF, 1009u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_SIZE, 42u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_V3, 3u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV1, 0x0103u);
        DF_CHECK(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV1 != 4u); /* schema 4 stays free: certified pool teams */
        DF_CHECK_EQ_U64(&t, sizeof(dfi_pool_tail), 34u);     /* the 42 bytes without the 8 reserved ones */
        const duoforge_context *with[] = {kp, kq};
        const duoforge_context *without[] = {k1, k2, kc, kd, c1};
        for (size_t i = 0u; i < 2u; ++i) {
            DF_CHECK(&t, dfi_context_has_pool_tail(with[i]));
            DF_CHECK_EQ_U64(&t, dfi_state_schema_of(with[i]), 0x0103u);
            DF_CHECK_EQ_U64(&t, dfi_state_encoded_size_of(with[i]), 1051u);
        }
        for (size_t i = 0u; i < 5u; ++i) {
            DF_CHECK(&t, !dfi_context_has_pool_tail(without[i]));
            DF_CHECK_EQ_U64(&t, dfi_state_schema_of(without[i]), 3u);
            DF_CHECK_EQ_U64(&t, dfi_state_encoded_size_of(without[i]), 1009u);
        }
    }

    /* The other four kinds are byte for byte what they were: size 1009, schema 3, and the digests of three states
     * of each, taken before the tail existed. A tail in memory is refused there (below). */
    {
        const duoforge_context *kinds[4] = {k1, k2, kc, kd};
        static const char *const names[4] = {"CLOSURE", "CLOSURE_DEV", "TEAM_C", "TEAM_C_DEV"};
        for (size_t i = 0u; i < 4u; ++i) {
            duoforge_battle_setup s;
            df_setup_teams(&s);
            if (i >= 2u) {
                df_put_team_c(&s.sides[1]);
            }
            duoforge_battle *b = df_make_battle(kinds[i], &s);
            uint8_t enc[DF_STATE_ENCODED_MAX];
            uint8_t d[DUOFORGE_DIGEST_SIZE];
            for (unsigned point = 0u; point < 3u; ++point) {
                if (point == 1u) {
                    duoforge_decision_bundle bd;
                    team_bundle(&bd, b);
                    step_ok(&t, kinds[i], b, &bd, "team selection");
                } else if (point == 2u) {
                    duoforge_decision_bundle bd;
                    turn_bundle(&bd, b);
                    step_ok(&t, kinds[i], b, &bd, "turn 1");
                }
                DF_CHECK_EQ_U64(&t, df_encode_n(kinds[i], b, enc), 1009u);
                DF_CHECK(&t, enc[DFI_ENVELOPE_SCHEMA_OFF] == 3u && enc[DFI_ENVELOPE_SCHEMA_OFF + 1u] == 0u);
                digest_of(&t, kinds[i], b, d);
                size_t found = 0u;
                for (size_t k = 0u; k < sizeof before_the_tail / sizeof before_the_tail[0]; ++k) {
                    static const char *const points[3] = {"created", "teams", "turn1"};
                    if (strcmp(before_the_tail[k].kind, names[i]) == 0 && strcmp(before_the_tail[k].point, points[point]) == 0) {
                        check_hex(&t, d, before_the_tail[k].hex, DUOFORGE_DIGEST_SIZE, "digest before the tail");
                        ++found;
                    }
                }
                DF_CHECK_EQ_U64(&t, found, 1u);
            }
            duoforge_battle_destroy(b);
        }
    }

    /* The state of a POOL battle at its first TURN boundary, with and without the example tail. */
    duoforge_battle *w = turn_battle(&t, kp, false);
    uint8_t zero_enc[DF_STATE_ENCODED_MAX];
    uint8_t enc[DF_STATE_ENCODED_MAX];
    uint8_t d0[DUOFORGE_DIGEST_SIZE];
    uint8_t d1[DUOFORGE_DIGEST_SIZE];
    {
        /* The example is valid because of who stands on the field: members 0 and 1 of both sides, standing, with
         * four moves and no Mega forme (the model's state). */
        for (uint32_t s = 0u; s < 2u; ++s) {
            DF_CHECK_EQ_U64(&t, w->sides[s].member_count, 6u);
            DF_CHECK(&t, w->sides[s].positions[0].occupant == 0u && w->sides[s].positions[1].occupant == 1u);
            for (uint32_t m = 0u; m < 6u; ++m) {
                DF_CHECK(&t, w->sides[s].members[m].hp != 0u && w->sides[s].members[m].move_count == 4u &&
                                 w->sides[s].members[m].is_mega == 0u);
            }
        }
        uint8_t zero_tail[DFI_ENC_TAIL_SIZE];
        memset(zero_tail, 0, sizeof zero_tail);
        DF_CHECK_EQ_U64(&t, df_encode_n(kp, w, zero_enc), 1051u);
        DF_CHECK_BYTES(&t, zero_enc + DFI_ENC_TAIL_OFF, zero_tail, sizeof zero_tail, "an empty tail is 42 zero bytes");
        digest_of(&t, kp, w, d0);

        set_example_tail(w);
        const size_t n = df_encode_n(kp, w, enc);
        DF_CHECK_EQ_U64(&t, n, 1051u);
        check_hex(&t, enc, ENVELOPE_HEX, DFI_ENVELOPE_SIZE, "envelope of a POOL state (model)");
        check_hex(&t, enc + DFI_ENC_TAIL_OFF, TAIL_HEX, DFI_ENC_TAIL_SIZE, "tail of the example (model)");
        /* The rest of the state is untouched by the tail. */
        DF_CHECK_BYTES(&t, enc + DFI_ENVELOPE_SIZE, zero_enc + DFI_ENVELOPE_SIZE, DFI_ENC_TAIL_OFF - DFI_ENVELOPE_SIZE,
                       "the body of the state does not depend on the tail");
        /* The reserved bytes are zero: two per side, one per position. */
        for (size_t s = 0u; s < 2u; ++s) {
            const uint8_t *so = enc + DFI_ENC_TAIL_OFF + s * DFI_ENC_TAIL_SIDE_SIZE;
            DF_CHECK(&t, so[1] == 0u && so[2] == 0u && so[3 + 5] == 0u && so[3 + 6 + 5] == 0u);
        }
        DF_CHECK(&t, duoforge_battle_check(kp, w) == DUOFORGE_OK);
        digest_of(&t, kp, w, d1);
        DF_CHECK(&t, memcmp(d0, d1, sizeof d0) != 0);
        size_t size = 0u;
        DF_CHECK(&t, duoforge_battle_encoded_size(kp, w, &size) == DUOFORGE_OK && size == 1051u);
    }

    /* Round trip, equality, clone, copy, load into an existing handle; nothing of the tail is lost. */
    {
        uint8_t *in = df_heap_copy(enc, DFI_STATE_POOL_ENCODED_SIZE);
        duoforge_battle *d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(kp, in, DFI_STATE_POOL_ENCODED_SIZE, &d) == DUOFORGE_OK && d != NULL);
        bool eq = false;
        DF_CHECK(&t, duoforge_battle_equal(kp, w, d, &eq) == DUOFORGE_OK && eq);
        DF_CHECK(&t, memcmp(&d->tail, &w->tail, sizeof w->tail) == 0);
        uint8_t again[DF_STATE_ENCODED_MAX];
        DF_CHECK_EQ_U64(&t, df_encode_n(kp, d, again), 1051u);
        DF_CHECK_BYTES(&t, again, enc, DFI_STATE_POOL_ENCODED_SIZE, "decode then encode");
        uint8_t dd[DUOFORGE_DIGEST_SIZE];
        digest_of(&t, kp, d, dd);
        DF_CHECK_BYTES(&t, dd, d1, sizeof dd, "digest of the decoded state");
        duoforge_battle_destroy(d);

        duoforge_battle *k = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, w, &k) == DUOFORGE_OK && k != NULL);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, k, &eq) == DUOFORGE_OK && eq);
        DF_CHECK(&t, memcmp(&k->tail, &w->tail, sizeof w->tail) == 0);
        /* copy into a handle that holds another tail (the empty one), and load into one. */
        duoforge_battle *other = turn_battle(&t, kp, false);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && !eq); /* the tail alone differs */
        DF_CHECK(&t, duoforge_battle_copy(kp, other, w) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && eq);
        memset(&other->tail, 0, sizeof other->tail);
        DF_CHECK(&t, duoforge_battle_decode(kp, other, in, DFI_STATE_POOL_ENCODED_SIZE) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && eq);
        /* A refused load changes nothing (atomic): a reserved byte of the tail that is not zero. */
        uint8_t bad[DF_STATE_ENCODED_MAX];
        memcpy(bad, enc, DFI_STATE_POOL_ENCODED_SIZE);
        bad[DFI_ENC_TAIL_OFF + 1u] = 1u;
        uint8_t *bad_in = df_heap_copy(bad, DFI_STATE_POOL_ENCODED_SIZE);
        uint8_t before[DF_STATE_ENCODED_MAX];
        uint8_t after[DF_STATE_ENCODED_MAX];
        (void)df_encode_n(kp, other, before);
        DF_CHECK(&t, duoforge_battle_decode(kp, other, bad_in, DFI_STATE_POOL_ENCODED_SIZE) == DUOFORGE_E_MALFORMED);
        (void)df_encode_n(kp, other, after);
        DF_CHECK_BYTES(&t, after, before, DFI_STATE_POOL_ENCODED_SIZE, "a refused load changes nothing");
        df_free(bad_in);
        df_free(in);
        duoforge_battle_destroy(other);
        duoforge_battle_destroy(k);
    }

    /* The digest changes if and only if the tail changes: 22 single settings (every field of the tail that a state
     * can hold on its own; Encore is a pair) give 22 digests, all different from each other and from the empty
     * tail's, and clearing the field brings the digest back. */
    {
        enum { VARIANTS = 22 };
        uint8_t digests[VARIANTS][DUOFORGE_DIGEST_SIZE];
        unsigned n = 0u;
        duoforge_battle *x = turn_battle(&t, kp, false);
        uint8_t base[DUOFORGE_DIGEST_SIZE];
        digest_of(&t, kp, x, base);
        for (uint32_t s = 0u; s < 2u; ++s) {
            for (uint32_t variant = 0u; variant < 11u; ++variant) {
                memset(&x->tail, 0, sizeof x->tail);
                dfi_tail_side *ts = &x->tail.sides[s];
                if (variant == 0u) {
                    ts->wide_guard = 1u;
                } else if (variant < 9u) {
                    dfi_tail_pos *tp = &ts->positions[(variant - 1u) / 4u];
                    switch ((variant - 1u) % 4u) {
                    case 0u:
                        tp->last_move = 1u;
                        break;
                    case 1u:
                        tp->encore_slot = 1u;
                        tp->encore_turns = 1u;
                        break;
                    case 2u:
                        tp->throat_chop_turns = 1u;
                        break;
                    default:
                        tp->heal_block_turns = 1u;
                        break;
                    }
                } else {
                    ts->soak_type[variant - 9u] = 1u;
                }
                DF_CHECK(&t, duoforge_battle_check(kp, x) == DUOFORGE_OK);
                digest_of(&t, kp, x, digests[n]);
                DF_CHECK(&t, memcmp(digests[n], base, sizeof base) != 0);
                for (unsigned j = 0u; j < n; ++j) {
                    DF_CHECK(&t, memcmp(digests[n], digests[j], sizeof base) != 0);
                }
                ++n;
                memset(&x->tail, 0, sizeof x->tail);
                uint8_t back[DUOFORGE_DIGEST_SIZE];
                digest_of(&t, kp, x, back);
                DF_CHECK_BYTES(&t, back, base, sizeof back, "the digest comes back with the empty tail");
            }
        }
        DF_CHECK_EQ_U64(&t, n, VARIANTS);
        duoforge_battle_destroy(x);
    }

    /* Mutation of the artifact: every byte of the tail to every other value. The decoder accepts the value or
     * refuses it with the invariant that the model names, and the counts per byte are the model's. */
    {
        unsigned wrong = 0u;
        for (size_t off = 0u; off < DFI_ENC_TAIL_SIZE; ++off) {
            unsigned got[5] = {0u, 0u, 0u, 0u, 0u};
            uint8_t m[DF_STATE_ENCODED_MAX];
            memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
            for (unsigned v = 0u; v < 256u; ++v) {
                if (v == enc[DFI_ENC_TAIL_OFF + off]) {
                    continue;
                }
                m[DFI_ENC_TAIL_OFF + off] = (uint8_t)v;
                dfi_invariant inv = DFI_INV_NONE;
                const duoforge_status st = decode_both(&t, kp, m, DFI_STATE_POOL_ENCODED_SIZE, &inv);
                if (st == DUOFORGE_OK) {
                    got[0] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_SIDE) {
                    got[1] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_POSITION) {
                    got[2] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_MEMBER) {
                    got[3] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_RESERVED) {
                    got[4] += 1u;
                } else {
                    DF_CHECK(&t, false);
                    fprintf(stderr, "  tail byte %u = %u: %s (%s)\n", (unsigned)off, v, duoforge_status_name(st), inv_name(inv));
                }
            }
            if (memcmp(got, sweep[off], sizeof got) != 0) {
                ++wrong;
                fprintf(stderr, "  tail byte %u: ok %u side %u position %u member %u reserved %u\n", (unsigned)off, got[0],
                        got[1], got[2], got[3], got[4]);
            }
        }
        DF_CHECK_EQ_U64(&t, wrong, 0u);
        /* The eight reserved bytes accept nothing but zero. */
        static const size_t reserved[8] = {1u, 2u, 8u, 14u, 22u, 23u, 29u, 35u};
        for (size_t i = 0u; i < 8u; ++i) {
            DF_CHECK_EQ_U64(&t, sweep[reserved[i]][4], 255u);
        }
    }

    /* The schema is the one of the context's kind; sizes, schema ids and truncations. */
    {
        uint8_t m[DF_STATE_ENCODED_MAX + 1u]; /* one byte past a state, for the length check */
        dfi_invariant inv = DFI_INV_NONE;
        /* A POOL state with the schema and length of schema 3 and without its tail. */
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 3u, 1009u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1009u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_SCHEMA);
        DF_CHECK(&t, decode_both(&t, kq, m, 1009u, &inv) == DUOFORGE_E_CONTEXT_MISMATCH); /* the POOL fingerprint */
        /* Pool schema and no tail; schema 3 with a tail; wrong lengths; a revision and a schema that do not exist. */
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 0x0103u, 1009u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1009u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 3u, 1051u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1051u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        static const uint32_t unknown[] = {0u, 1u, 2u, 4u, 0x0100u, 0x0203u, 0x0303u, 0x0104u, 0x8103u, 0xFFFFu};
        for (size_t i = 0u; i < sizeof unknown / sizeof unknown[0]; ++i) {
            memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
            set_envelope(m, unknown[i], 1051u);
            DF_CHECK(&t, decode_both(&t, kp, m, 1051u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        }
        /* Every length from 0 to 1050 bytes, and one byte more, is malformed (the length field says 1051). */
        unsigned not_malformed = 0u;
        for (size_t n = 0u; n <= 1050u; ++n) {
            not_malformed += decode_both(&t, kp, enc, n, NULL) != DUOFORGE_E_MALFORMED ? 1u : 0u;
        }
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        m[DFI_STATE_POOL_ENCODED_SIZE] = 0u;
        not_malformed += decode_both(&t, kp, m, DFI_STATE_POOL_ENCODED_SIZE + 1u, NULL) != DUOFORGE_E_MALFORMED ? 1u : 0u;
        DF_CHECK_EQ_U64(&t, not_malformed, 0u);
        /* An artifact of a POOL state is not the state of another kind: the fingerprint is. */
        DF_CHECK(&t, decode_both(&t, k1, enc, DFI_STATE_POOL_ENCODED_SIZE, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, decode_both(&t, kq, enc, DFI_STATE_POOL_ENCODED_SIZE, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);

        /* A state of another kind with a tail appended and the pool schema: refused by the invariant, whatever the
         * tail holds (the all-zero one included), and the other way round for POOL. */
        const duoforge_context *kinds[4] = {k1, k2, kc, kd};
        for (size_t i = 0u; i < 4u; ++i) {
            duoforge_battle *b = turn_battle(&t, kinds[i], i >= 2u);
            uint8_t base[DF_STATE_ENCODED_MAX];
            DF_CHECK_EQ_U64(&t, df_encode_n(kinds[i], b, base), 1009u);
            for (unsigned with_tail = 0u; with_tail < 2u; ++with_tail) {
                memcpy(m, base, 1009u);
                memset(m + 1009u, 0, DFI_ENC_TAIL_SIZE);
                if (with_tail != 0u) {
                    DF_CHECK(&t, df_hex_to_bytes(TAIL_HEX, m + 1009u, DFI_ENC_TAIL_SIZE));
                }
                set_envelope(m, 0x0103u, 1051u);
                DF_CHECK(&t, decode_both(&t, kinds[i], m, 1051u, &inv) == DUOFORGE_E_MALFORMED &&
                                 inv == DFI_INV_TAIL_SCHEMA);
            }
            duoforge_battle_destroy(b);
        }
    }

    /* A tail in memory under the four other kinds (and the SYNTHETIC one): every byte of it is refused. The checker
     * says E_INVARIANT / TAIL_KIND, and check, encode and digest follow; with the byte cleared all of them pass. */
    {
        const duoforge_context *kinds[5] = {k1, k2, kc, kd, c1};
        for (size_t i = 0u; i < 5u; ++i) {
            duoforge_battle *b = i < 4u ? turn_battle(&t, kinds[i], i >= 2u) : df_make_f1(c1);
            unsigned refused = 0u;
            for (size_t k = 0u; k < sizeof b->tail; ++k) {
                *tail_byte(b, k) = 1u;
                dfi_invariant inv = DFI_INV_NONE;
                uint8_t out[DF_STATE_ENCODED_MAX];
                uint8_t dg[DUOFORGE_DIGEST_SIZE];
                size_t written = 77u;
                size_t size = 0u;
                if (dfi_state_check(kinds[i], b, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_TAIL_KIND &&
                    duoforge_battle_check(kinds[i], b) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_encode(kinds[i], b, out, sizeof out, &written) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_digest(kinds[i], b, dg) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_encoded_size(kinds[i], b, &size) == DUOFORGE_OK && size == 1009u && written == 77u) {
                    ++refused;
                }
                *tail_byte(b, k) = 0u;
            }
            DF_CHECK_EQ_U64(&t, refused, sizeof b->tail);
            DF_CHECK(&t, duoforge_battle_check(kinds[i], b) == DUOFORGE_OK);
            duoforge_battle_destroy(b);
        }
    }

    /* Under POOL the checks of the tail: a value out of range, a tail at a position without a standing occupant, a
     * soak type on a member that is not standing on the field. Each is E_INVARIANT with its id. (Step G11: a soak type
     * on a Mega Evolved member is valid, as a Pokemon that has Mega Evolved can be Soaked; this case was an error
     * before, on the assumption that a Mega Evolution always comes after the type, which the pin does not say.) */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        duoforge_battle *short_moves = NULL; /* side 1's lead has two moves: Politoed with Weather Ball and Muddy Water */
        {
            duoforge_battle_setup s;
            df_setup_teams(&s);
            s.sides[1].members[0].move_count = 2u;
            s.sides[1].members[0].moves[2].move_id = 0u;
            s.sides[1].members[0].moves[3].move_id = 0u;
            short_moves = df_make_battle(kp, &s);
            duoforge_decision_bundle bd;
            team_bundle(&bd, short_moves);
            step_ok(&t, kp, short_moves, &bd, "team selection (two moves)");
        }
        enum { CASES = 21 };
        static const struct {
            const char *what;
            dfi_invariant inv;
        } cases[CASES] = {{"wide guard above 1", DFI_INV_TAIL_SIDE},
                          {"last move above Struggle", DFI_INV_TAIL_POSITION},
                          {"last move beyond the move count", DFI_INV_TAIL_POSITION},
                          {"Encore slot beyond the move count", DFI_INV_TAIL_POSITION},
                          {"Encore without turns", DFI_INV_TAIL_POSITION},
                          {"Encore turns without a slot", DFI_INV_TAIL_POSITION},
                          {"Encore slot above 4", DFI_INV_TAIL_POSITION},
                          {"Encore turns above 4", DFI_INV_TAIL_POSITION},
                          {"Throat Chop above 2", DFI_INV_TAIL_POSITION},
                          {"Heal Block above 5", DFI_INV_TAIL_POSITION},
                          {"a tail at an empty position", DFI_INV_TAIL_POSITION},
                          {"a tail at a fainted occupant", DFI_INV_TAIL_POSITION},
                          {"a soak type above 18", DFI_INV_TAIL_MEMBER},
                          {"a soak type on a reserve", DFI_INV_TAIL_MEMBER},
                          {"a soak type on a fainted member", DFI_INV_TAIL_MEMBER},
                          {"a soak type on a Mega Evolved member is valid (Soak after the Mega Evolution)", DFI_INV_NONE},
                          {"a soak type on a member that has left the field", DFI_INV_TAIL_MEMBER},
                          {"Struggle as the last move is valid for any move count", DFI_INV_NONE},
                          {"the last Encore turn and slot 4 are valid", DFI_INV_NONE},
                          {"every maximum at once is valid", DFI_INV_NONE},
                          {"a soak type 18 on the second lead is valid", DFI_INV_NONE}};
        for (size_t i = 0u; i < CASES; ++i) {
            duoforge_battle *y = NULL;
            DF_CHECK(&t, duoforge_battle_clone(kp, i == 2u || i == 3u ? short_moves : x, &y) == DUOFORGE_OK && y != NULL);
            dfi_tail_side *ts = i == 2u || i == 3u ? &y->tail.sides[1] : &y->tail.sides[0];
            dfi_tail_pos *p0 = &ts->positions[0];
            switch (i) {
            case 0u:
                ts->wide_guard = 2u;
                break;
            case 1u:
                p0->last_move = 6u;
                break;
            case 2u:
                p0->last_move = 3u; /* the lead has two moves */
                break;
            case 3u:
                p0->encore_slot = 3u;
                p0->encore_turns = 1u;
                break;
            case 4u:
                p0->encore_slot = 1u;
                break;
            case 5u:
                p0->encore_turns = 1u;
                break;
            case 6u:
                p0->encore_slot = 5u;
                p0->encore_turns = 1u;
                break;
            case 7u:
                p0->encore_slot = 1u;
                p0->encore_turns = 5u;
                break;
            case 8u:
                p0->throat_chop_turns = 3u;
                break;
            case 9u:
                p0->heal_block_turns = 6u;
                break;
            case 10u:
                dfi_slot_clear(&y->sides[0].positions[1]);
                y->sides[0].requested_slots = 1u; /* the occupied mask */
                ts->positions[1].heal_block_turns = 1u;
                break;
            case 11u:
                y->sides[0].members[1].hp = 0u;
                df_knowledge_refresh_active(y);
                ts->positions[1].throat_chop_turns = 1u;
                break;
            case 12u:
                ts->soak_type[0] = 19u;
                break;
            case 13u:
                ts->soak_type[3] = 1u;
                break;
            case 14u:
                y->sides[0].members[1].hp = 0u;
                df_knowledge_refresh_active(y);
                ts->soak_type[1] = 1u;
                break;
            case 15u:
                DF_CHECK(&t, dfi_closure_member_mega_evolve(&y->sides[0].members[1]));
                y->sides[0].mega_used = 1u;
                y->sides[1].knowledge[1].revealed = (uint8_t)(y->sides[1].knowledge[1].revealed | DFI_REVEALED_MEGA);
                ts->soak_type[1] = 1u;
                break;
            case 16u:
                ts->soak_type[2] = 1u; /* member 2 is a reserve */
                break;
            case 17u:
                p0->last_move = 5u;
                break;
            case 18u:
                p0->encore_slot = 4u;
                p0->encore_turns = 1u;
                break;
            case 19u:
                ts->wide_guard = 1u;
                ts->positions[0] = (dfi_tail_pos){5u, 4u, 4u, 2u, 5u};
                ts->positions[1] = (dfi_tail_pos){4u, 4u, 4u, 2u, 5u};
                break;
            default:
                ts->soak_type[1] = 18u;
                break;
            }
            dfi_invariant inv = DFI_INV_NONE;
            const duoforge_status st = dfi_state_check(kp, y, &inv);
            const bool want_ok = cases[i].inv == DFI_INV_NONE;
            if (!DF_CHECK(&t, want_ok ? st == DUOFORGE_OK : (st == DUOFORGE_E_INVARIANT && inv == cases[i].inv))) {
                fprintf(stderr, "  %s: %s (%s), expected %s\n", cases[i].what, duoforge_status_name(st), inv_name(inv),
                        inv_name(cases[i].inv));
            }
            /* The same through the public API, and a step refuses it atomically. */
            DF_CHECK(&t, (duoforge_battle_check(kp, y) == DUOFORGE_OK) == want_ok);
            if (!want_ok) {
                uint8_t before[DF_STATE_ENCODED_MAX];
                uint8_t after[DF_STATE_ENCODED_MAX];
                const size_t n = dfi_encode_unchecked(kp, y, before);
                duoforge_decision_bundle bd;
                turn_bundle(&bd, y);
                duoforge_step_result res;
                DF_CHECK(&t, duoforge_battle_step(kp, y, &bd, &res) == DUOFORGE_E_INVARIANT);
                DF_CHECK_EQ_U64(&t, dfi_encode_unchecked(kp, y, after), n);
                DF_CHECK_BYTES(&t, after, before, n, "a refused step changes nothing");
            }
            duoforge_battle_destroy(y);
        }
        duoforge_battle_destroy(short_moves);
        duoforge_battle_destroy(x);
    }

    /* A valid tail passes through a step: the residual counts the Throat Chop and Heal Block timers of every position
     * down by one (step G8) and ends the wide guard of both sides (step G7: a side condition of duration 1), and nothing
     * else of it changes (the last move, Encore and the soak types stay: nothing in this turn ends them). Before step G8 nothing wrote the tail and it stayed byte for byte; the turn
     * is the same, and with the soak types of the example (Fighting and Water on the leads, which the types now read:
     * step G11) it no longer ends in a knock-out before its residual. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        set_example_tail(x);
        dfi_pool_tail want = x->tail;
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            want.sides[s].wide_guard = 0u;
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                dfi_tail_pos *tp = &want.sides[s].positions[p];
                tp->throat_chop_turns = (uint8_t)(tp->throat_chop_turns != 0u ? tp->throat_chop_turns - 1u : 0u);
                tp->heal_block_turns = (uint8_t)(tp->heal_block_turns != 0u ? tp->heal_block_turns - 1u : 0u);
            }
        }
        duoforge_decision_bundle bd;
        turn_bundle(&bd, x);
        step_ok(&t, kp, x, &bd, "a turn with a tail");
        DF_CHECK(&t, memcmp(&x->tail, &want, sizeof want) == 0);
        DF_CHECK(&t, duoforge_battle_check(kp, x) == DUOFORGE_OK);
        duoforge_battle_destroy(x);
    }

    /* Capacity: a POOL state needs its 1051 bytes, the others 1009; POOL_DEV is a POOL kind. */
    {
        uint8_t big[DF_STATE_ENCODED_MAX];
        size_t written = 0u;
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1009u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1050u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1051u, &written) == DUOFORGE_OK && written == 1051u);
        duoforge_battle *q = turn_battle(&t, kq, false);
        set_example_tail(q);
        DF_CHECK(&t, duoforge_battle_encode(kq, q, big, 1051u, &written) == DUOFORGE_OK && written == 1051u);
        DF_CHECK(&t, duoforge_battle_check(kq, q) == DUOFORGE_OK);
        duoforge_battle_destroy(q);
        duoforge_battle *b1 = turn_battle(&t, k1, false);
        DF_CHECK(&t, duoforge_battle_encode(k1, b1, big, 1008u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(k1, b1, big, 1009u, &written) == DUOFORGE_OK && written == 1009u);
        duoforge_battle_destroy(b1);
    }

    duoforge_battle_destroy(w);
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    duoforge_context_destroy(kc);
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    duoforge_context_destroy(kq);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
