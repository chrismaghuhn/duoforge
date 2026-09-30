#include "support/fixtures.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "state/transition.h"

/* T1: the 36 distinct team moves of decision 0004 in order (target classes
 * from data/moves.ts at the pin; decision 0005 section 4). */
#define N DUOFORGE_TARGET_CLASS_NORMAL
#define A DUOFORGE_TARGET_CLASS_ANY
#define S DUOFORGE_TARGET_CLASS_SELF
#define F DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES
#define Y DUOFORGE_TARGET_CLASS_ALLY_SIDE
#define L DUOFORGE_TARGET_CLASS_ALL
const uint8_t df_table_t1[36] = {
    N, N, N, N, A, N, Y, S, F, S, /* woodhammer .. coil */
    N, N, N, N, S, N, N, F, N, S, /* icebeam .. nastyplot */
    N, N, N, N, A, N, F, N, N, L, /* weatherball .. trickroom */
    F, A, N, Y, Y, N,             /* heatwave .. partingshot */
};
static const uint8_t df_table_t2[36] = {
    N, N, N, N, A, N, Y, S, F, S, N, N, N, N, S, N, N, F, N, S, N, N, N, N, A, N, F, N, N, L, F, A, N, Y, Y, S,
};
#undef N
#undef A
#undef S
#undef F
#undef Y
#undef L
static const uint8_t df_table_t4[9] = {1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u, 9u};

const duoforge_context_config df_config_c1 = {DUOFORGE_DATA_KIND_SYNTHETIC, 6u, 4u, 16u, 36u, df_table_t1};
const duoforge_context_config df_config_c2 = {DUOFORGE_DATA_KIND_SYNTHETIC, 6u, 4u, 16u, 36u, df_table_t2};
const duoforge_context_config df_config_c3 = {DUOFORGE_DATA_KIND_SYNTHETIC, 6u, 1u, 16u, 36u, df_table_t1};
const duoforge_context_config df_config_c4 = {DUOFORGE_DATA_KIND_SYNTHETIC, 4u, 2u, 8u, 9u, df_table_t4};

static void df_fail(const char *what)
{
    fprintf(stderr, "fixture setup failed: %s\n", what);
    exit(2);
}

static void set_member(duoforge_member_setup *m, uint32_t species, uint32_t hp_max, uint32_t mega,
                       uint32_t move_count, const uint32_t *ids, const uint32_t *pps)
{
    m->species_id = species;
    m->hp_max = hp_max;
    m->mega_capable = mega;
    m->move_count = move_count;
    for (uint32_t k = 0; k < move_count; ++k) {
        m->moves[k].move_id = ids[k];
        m->moves[k].pp_max = pps[k];
    }
}

void df_setup_g1(duoforge_battle_setup *out)
{
    memset(out, 0, sizeof *out);
    out->rng_initstate = 42u;
    out->rng_initseq = 54u;
    duoforge_side_setup *s0 = &out->sides[0];
    s0->member_count = 6u;
    for (uint32_t i = 0; i < 6u; ++i) {
        duoforge_member_setup *m = &s0->members[i];
        m->species_id = i + 1u;
        m->hp_max = 100u + 10u * i;
        m->move_count = (i % 4u) + 1u;
        m->mega_capable = (i == 1u || i == 3u) ? 1u : 0u;
        for (uint32_t k = 0; k < m->move_count; ++k) {
            m->moves[k].move_id = 4u * i + k;
            m->moves[k].pp_max = 5u + 5u * k;
        }
    }
    duoforge_side_setup *s1 = &out->sides[1];
    s1->member_count = 4u;
    for (uint32_t i = 0; i < 4u; ++i) {
        duoforge_member_setup *m = &s1->members[i];
        m->species_id = 10u + i;
        m->hp_max = 200u + i;
        m->move_count = 4u;
        m->mega_capable = i == 0u ? 1u : 0u;
        for (uint32_t k = 0; k < 4u; ++k) {
            m->moves[k].move_id = 31u - (4u * i + k);
            m->moves[k].pp_max = 8u * (k + 1u);
        }
    }
}

void df_setup_g3(duoforge_battle_setup *out)
{
    memset(out, 0, sizeof *out);
    out->rng_initstate = 42u;
    out->rng_initseq = 54u;
    duoforge_side_setup *s0 = &out->sides[0];
    s0->member_count = 3u;
    for (uint32_t i = 0; i < 3u; ++i) {
        s0->members[i].species_id = i;
        s0->members[i].hp_max = 50u + i;
        s0->members[i].move_count = 1u;
        s0->members[i].moves[0].move_id = i;
        s0->members[i].moves[0].pp_max = 1u;
    }
    duoforge_side_setup *s1 = &out->sides[1];
    s1->member_count = 2u;
    for (uint32_t i = 0; i < 2u; ++i) {
        s1->members[i].species_id = 15u - i;
        s1->members[i].hp_max = 65535u - i;
        s1->members[i].move_count = 2u;
        s1->members[i].moves[0].move_id = 31u;
        s1->members[i].moves[0].pp_max = 255u;
        s1->members[i].moves[1].move_id = 30u;
        s1->members[i].moves[1].pp_max = 1u;
    }
}

void df_setup_g7(duoforge_battle_setup *out)
{
    /* Move id c-1 has target class c under C4's table. */
    static const uint32_t m0i[] = {0u, 5u}, m0p[] = {2u, 1u};
    static const uint32_t m1i[] = {1u}, m1p[] = {1u};
    static const uint32_t m2i[] = {2u, 3u, 4u, 8u}, m2p[] = {3u, 3u, 3u, 3u};
    static const uint32_t m3i[] = {6u, 7u}, m3p[] = {5u, 5u};
    static const uint32_t n0i[] = {0u, 1u, 5u}, n0p[] = {1u, 1u, 1u};
    static const uint32_t n1i[] = {4u}, n1p[] = {2u};
    static const uint32_t n2i[] = {8u, 0u}, n2p[] = {1u, 1u};
    memset(out, 0, sizeof *out);
    out->rng_initstate = 7u;
    out->rng_initseq = 9u;
    out->sides[0].member_count = 4u;
    set_member(&out->sides[0].members[0], 0u, 30u, 1u, 2u, m0i, m0p);
    set_member(&out->sides[0].members[1], 1u, 31u, 0u, 1u, m1i, m1p);
    set_member(&out->sides[0].members[2], 2u, 32u, 1u, 4u, m2i, m2p);
    set_member(&out->sides[0].members[3], 3u, 33u, 0u, 2u, m3i, m3p);
    out->sides[1].member_count = 3u;
    set_member(&out->sides[1].members[0], 4u, 40u, 0u, 3u, n0i, n0p);
    set_member(&out->sides[1].members[1], 5u, 41u, 1u, 1u, n1i, n1p);
    set_member(&out->sides[1].members[2], 6u, 42u, 0u, 2u, n2i, n2p);
}

duoforge_context *df_make_context(const duoforge_context_config *config)
{
    duoforge_context *ctx = NULL;
    if (duoforge_context_create(config, &ctx) != DUOFORGE_OK || ctx == NULL) {
        df_fail("duoforge_context_create");
    }
    return ctx;
}

duoforge_battle *df_make_battle(const duoforge_context *ctx, const duoforge_battle_setup *setup)
{
    duoforge_battle *b = NULL;
    if (duoforge_battle_create(ctx, setup, &b) != DUOFORGE_OK || b == NULL) {
        df_fail("duoforge_battle_create");
    }
    return b;
}

static void df_checked(const duoforge_context *ctx, const duoforge_battle *b, const char *what)
{
    if (duoforge_battle_check(ctx, b) != DUOFORGE_OK) {
        df_fail(what);
    }
}

static void df_select(const duoforge_context *ctx, duoforge_battle *b, const uint8_t *p0, const uint8_t *p1,
                      uint32_t n, const char *what)
{
    dfi_team_picks picks;
    memset(&picks, 0xFF, sizeof picks);
    for (uint32_t i = 0; i < n; ++i) {
        picks.picks[0][i] = p0[i];
        picks.picks[1][i] = p1[i];
    }
    if (dfi_apply_team_selection(ctx, b, &picks) != DUOFORGE_OK) {
        df_fail(what);
    }
}

duoforge_battle *df_make_g1(const duoforge_context *c1)
{
    duoforge_battle_setup setup;
    df_setup_g1(&setup);
    return df_make_battle(c1, &setup);
}

duoforge_battle *df_make_f1(const duoforge_context *c1)
{
    static const uint8_t p0[4] = {2u, 0u, 1u, 3u};
    static const uint8_t p1[4] = {1u, 3u, 0u, 2u};
    duoforge_battle *b = df_make_g1(c1);
    df_select(c1, b, p0, p1, 4u, "F1 team selection");
    return b;
}

duoforge_battle *df_make_f2(const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f1(c1);
    for (unsigned i = 0; i < 16; ++i) {
        uint32_t v = 0;
        if (dfi_rng_next_u32(&b->rng, &v) != DUOFORGE_OK) {
            df_fail("F2 draws");
        }
    }
    dfi_binding binding;
    const dfi_position_id s0a = {0, 0};
    const dfi_position_id s1b = {1, 1};
    if (dfi_vacate(b, s0a) != DUOFORGE_OK || dfi_place(b, s0a, 3u, &binding) != DUOFORGE_OK ||
        dfi_vacate(b, s1b) != DUOFORGE_OK) {
        df_fail("F2 identity primitives");
    }
    b->sides[1].requested_slots = 1u;
    b->sides[0].members[0].hp = 0u;
    b->sides[0].members[1].hp = 57u;
    b->sides[0].members[1].moves[0].pp = 0u;
    b->sides[1].members[2].hp = 0u;
    b->sides[1].members[0].moves[3].pp = 7u;
    b->sides[0].mega_used = 1u;
    df_checked(c1, b, "F2 check");
    return b;
}

duoforge_battle *df_make_g3(const duoforge_context *c3)
{
    duoforge_battle_setup setup;
    df_setup_g3(&setup);
    return df_make_battle(c3, &setup);
}

duoforge_battle *df_make_f3(const duoforge_context *c3)
{
    static const uint8_t p0[1] = {2u};
    static const uint8_t p1[1] = {0u};
    duoforge_battle *b = df_make_g3(c3);
    df_select(c3, b, p0, p1, 1u, "F3 team selection");
    return b;
}

duoforge_battle *df_make_f4(const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f1(c1);
    b->sides[0].members[2].hp = 0u;
    b->sides[1].members[3].hp = 0u;
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    b->request_epoch = 3u;
    b->request_mask = 3u;
    b->sides[0].requested_slots = 1u;
    b->sides[1].requested_slots = 2u;
    df_checked(c1, b, "F4 check");
    return b;
}

duoforge_battle *df_make_f5(const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f1(c1);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    b->request_epoch = 3u;
    b->request_mask = 1u;
    b->sides[0].requested_slots = 1u;
    b->sides[1].requested_slots = 0u;
    b->sides[0].sealed = 1u;
    b->sides[0].sealed_cmds[0] = (dfi_slot_cmd){DFI_SLOT_MOVE, 0u, 2u, 0u, 0u};
    b->sides[0].sealed_cmds[1] = (dfi_slot_cmd){DFI_SLOT_MOVE, 1u, 3u, 0u, 0u};
    b->sides[1].sealed = 1u;
    b->sides[1].sealed_cmds[0] = (dfi_slot_cmd){DFI_SLOT_SWITCH, 0u, 0u, 0u, 0u};
    b->sides[1].sealed_cmds[1] = (dfi_slot_cmd){DFI_SLOT_MOVE, 2u, 0u, 0u, 0u};
    df_checked(c1, b, "F5 check");
    return b;
}

duoforge_battle *df_make_f6(const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f5(c1);
    b->request_mask = 3u;
    b->sides[1].requested_slots = 2u;
    df_checked(c1, b, "F6 check");
    return b;
}

duoforge_battle *df_make_g7(const duoforge_context *c4)
{
    duoforge_battle_setup setup;
    df_setup_g7(&setup);
    return df_make_battle(c4, &setup);
}

duoforge_battle *df_make_f8(const duoforge_context *c4)
{
    static const uint8_t p0[2] = {1u, 3u};
    static const uint8_t p1[2] = {2u, 0u};
    duoforge_battle *b = df_make_g7(c4);
    df_select(c4, b, p0, p1, 2u, "F8 team selection");
    return b;
}

duoforge_battle *df_make_f9(const duoforge_context *c4)
{
    static const uint8_t p0[2] = {0u, 2u};
    static const uint8_t p1[2] = {1u, 2u};
    duoforge_battle *b = df_make_g7(c4);
    df_select(c4, b, p0, p1, 2u, "F9 team selection");
    return b;
}

duoforge_battle *df_make_f10(const duoforge_context *c4)
{
    duoforge_battle *b = df_make_f9(c4);
    b->sides[1].members[2].hp = 0u;
    b->sides[0].mega_used = 1u;
    df_checked(c4, b, "F10 check");
    return b;
}

duoforge_battle *df_make_f11(const duoforge_context *c4)
{
    duoforge_battle *b = df_make_f9(c4);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    b->request_epoch = 3u;
    b->request_mask = 1u;
    b->sides[0].members[0].hp = 0u;
    b->sides[0].members[2].hp = 0u;
    b->sides[0].requested_slots = 3u;
    b->sides[1].requested_slots = 0u;
    df_checked(c4, b, "F11 check");
    return b;
}

duoforge_battle *df_make_f12(const duoforge_context *c4)
{
    duoforge_battle *b = df_make_f9(c4);
    b->sides[0].members[0].moves[0].pp = 0u;
    b->sides[0].members[0].moves[1].pp = 0u;
    df_checked(c4, b, "F12 check");
    return b;
}

void df_encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V2_ENCODED_SIZE])
{
    size_t written = 0;
    if (duoforge_battle_encode(ctx, b, out, DUOFORGE_STATE_V2_ENCODED_SIZE, &written) != DUOFORGE_OK ||
        written != DUOFORGE_STATE_V2_ENCODED_SIZE) {
        df_fail("duoforge_battle_encode");
    }
}
