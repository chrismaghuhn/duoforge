/*
 * T7 duoforge.state.setup (public + white-box): battle creation from the
 * synthetic setup, deterministic init, and the single-fault table
 * (INVALID_ARGUMENT, *out untouched, nothing leaked). Expectations: the setup
 * contract (docs/decisions/0002) and the pinned KAT after-seed values.
 * Fault values of the form 2^w + valid detect narrow-before-validate bugs.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"

typedef void (*mutator)(duoforge_battle_setup *s);

static void check_fails(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *base,
                        mutator mutate, const char *what)
{
    duoforge_battle_setup s = *base;
    mutate(&s);
    df_sentinel sentinel;
    duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
    duoforge_battle *out = marker;
    const duoforge_status st = duoforge_battle_create(ctx, &s, &out);
    const bool ok = DF_CHECK(t, st == DUOFORGE_E_INVALID_ARGUMENT) && DF_CHECK(t, out == marker);
    if (!ok) {
        fprintf(stderr, "  case: %s (status %s)\n", what, duoforge_status_name(st));
        if (st == DUOFORGE_OK && out != marker) {
            duoforge_battle_destroy(out);
        }
    }
}

#define FAULT(name, body)                           \
    static void name(duoforge_battle_setup *s)      \
    {                                               \
        body;                                       \
    }

FAULT(f_seq_2_63, s->rng_initseq = UINT64_C(0x8000000000000000))
FAULT(f_seq_max, s->rng_initseq = UINT64_MAX)
FAULT(f_s0_mc0, s->sides[0].member_count = 0u)
FAULT(f_s0_mc3, s->sides[0].member_count = 3u)
FAULT(f_s0_mc7, s->sides[0].member_count = 7u)
FAULT(f_s0_mc262, s->sides[0].member_count = 262u)
FAULT(f_s1_mc3, s->sides[1].member_count = 3u)
FAULT(f_species16, s->sides[0].members[1].species_id = 16u)
FAULT(f_species65536, s->sides[0].members[1].species_id = 65536u)
FAULT(f_hp0, s->sides[0].members[2].hp_max = 0u)
FAULT(f_hp65536, s->sides[0].members[2].hp_max = 65536u)
FAULT(f_hp65636, s->sides[0].members[2].hp_max = 65636u)
FAULT(f_mc_move0, s->sides[0].members[0].move_count = 0u)
FAULT(f_mc_move5, s->sides[0].members[0].move_count = 5u)
FAULT(f_mc_move257, s->sides[0].members[0].move_count = 257u)
FAULT(f_move_id32, s->sides[1].members[0].moves[2].move_id = 32u)
FAULT(f_move_id65536, s->sides[1].members[0].moves[2].move_id = 65536u)
FAULT(f_pp0, s->sides[0].members[0].moves[0].pp_max = 0u)
FAULT(f_pp256, s->sides[0].members[0].moves[0].pp_max = 256u)
FAULT(f_pp261, s->sides[0].members[0].moves[0].pp_max = 261u)
FAULT(f_unused_move_id, s->sides[0].members[0].moves[1].move_id = 3u)
FAULT(f_unused_move_pp, s->sides[0].members[0].moves[1].pp_max = 1u)
FAULT(f_unused_member_species, s->sides[1].members[5].species_id = 1u)
FAULT(f_unused_member_move_pp, s->sides[1].members[5].moves[2].pp_max = 1u)
FAULT(f_mask_out_of_range, s->sides[1].brought_mask = 0x1Eu)
FAULT(f_mask_bit31, s->sides[0].brought_mask = UINT32_C(0x8000000F))
FAULT(f_mask_pop3, s->sides[0].brought_mask = 0x07u)
FAULT(f_mask_pop5, s->sides[0].brought_mask = 0x1Fu)
FAULT(f_lead_not_brought, s->sides[0].leads[0] = 4u)
FAULT(f_lead_ge_count, s->sides[1].leads[0] = 4u)
FAULT(f_lead1_none, s->sides[0].leads[1] = DUOFORGE_ROSTER_NONE)
FAULT(f_lead_dup, s->sides[0].leads[1] = 2u)
FAULT(f_lead0_0x102, s->sides[0].leads[0] = 0x102u)
FAULT(f_lead1_0x100, s->sides[1].leads[1] = 0x100u)
/* C3 (brought 1) faults. */
FAULT(f_c3_lead1_set, s->sides[0].leads[1] = 0u)
FAULT(f_c3_lead0_none, s->sides[1].leads[0] = DUOFORGE_ROSTER_NONE)
FAULT(f_c3_lead1_0x1ff, s->sides[0].leads[1] = 0x1FFu)

static void check_member_fields(df_test *t, const dfi_member *m, const duoforge_member_setup *src)
{
    DF_CHECK_EQ_U64(t, m->species_id, src->species_id);
    DF_CHECK_EQ_U64(t, m->hp_max, src->hp_max);
    DF_CHECK_EQ_U64(t, m->hp, src->hp_max);
    DF_CHECK_EQ_U64(t, m->move_count, src->move_count);
    for (unsigned k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (k < src->move_count) {
            DF_CHECK_EQ_U64(t, m->moves[k].move_id, src->moves[k].move_id);
            DF_CHECK_EQ_U64(t, m->moves[k].pp_max, src->moves[k].pp_max);
            DF_CHECK_EQ_U64(t, m->moves[k].pp, src->moves[k].pp_max);
        } else {
            DF_CHECK(t, m->moves[k].move_id == 0u && m->moves[k].pp == 0u && m->moves[k].pp_max == 0u);
        }
    }
}

static bool member_is_zero(const dfi_member *m)
{
    bool z = m->species_id == 0u && m->hp == 0u && m->hp_max == 0u && m->move_count == 0u;
    for (unsigned k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        z = z && m->moves[k].move_id == 0u && m->moves[k].pp == 0u && m->moves[k].pp_max == 0u;
    }
    return z;
}

static void check_slot(df_test *t, const dfi_active_slot *slot, uint32_t act, uint32_t occupant)
{
    DF_CHECK_EQ_U64(t, slot->activation_id, act);
    DF_CHECK_EQ_U64(t, slot->occupant, occupant);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.setup");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_battle_setup f1;
    duoforge_battle_setup f3;
    df_setup_f1(&f1);
    df_setup_f3(&f3);

    /* F1 under C1. */
    {
        duoforge_battle *b = df_make_battle(c1, &f1);
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, b->rng.state, UINT64_C(0x185706b82c2e03f8));
        DF_CHECK_EQ_U64(&t, b->rng.inc, UINT64_C(0x6d));
        DF_CHECK_EQ_U64(&t, b->rng.draws, 0u);
        for (unsigned s = 0; s < 2; ++s) {
            DF_CHECK_EQ_U64(&t, b->sides[s].member_count, f1.sides[s].member_count);
            DF_CHECK_EQ_U64(&t, b->sides[s].brought_mask, f1.sides[s].brought_mask);
            for (unsigned m = 0; m < DUOFORGE_MAX_ROSTER; ++m) {
                if (m < f1.sides[s].member_count) {
                    check_member_fields(&t, &b->sides[s].members[m], &f1.sides[s].members[m]);
                } else {
                    DF_CHECK(&t, member_is_zero(&b->sides[s].members[m]));
                }
            }
        }
        check_slot(&t, &b->sides[0].positions[0], 1u, 2u);
        check_slot(&t, &b->sides[0].positions[1], 2u, 0u);
        check_slot(&t, &b->sides[1].positions[0], 3u, 1u);
        check_slot(&t, &b->sides[1].positions[1], 4u, 3u);
        DF_CHECK_EQ_U64(&t, b->next_activation_id, 5u);
        duoforge_battle_destroy(b);
    }

    /* F3 under C3 (brought 1: slot b stays empty). */
    {
        duoforge_battle *b = df_make_battle(c3, &f3);
        DF_CHECK(&t, duoforge_battle_check(c3, b) == DUOFORGE_OK);
        check_slot(&t, &b->sides[0].positions[0], 1u, 2u);
        check_slot(&t, &b->sides[0].positions[1], 0u, 0xFFu);
        check_slot(&t, &b->sides[1].positions[0], 2u, 0u);
        check_slot(&t, &b->sides[1].positions[1], 0u, 0xFFu);
        DF_CHECK_EQ_U64(&t, b->next_activation_id, 3u);
        DF_CHECK_EQ_U64(&t, b->sides[1].members[0].hp_max, 65535u); /* accepted maximum */
        DF_CHECK_EQ_U64(&t, b->sides[1].members[0].moves[0].pp_max, 255u);
        duoforge_battle_destroy(b);
    }

    /* Determinism: identical setups give identical encodings; a seed change
     * only touches the RNG bytes. */
    {
        uint8_t e1[DUOFORGE_STATE_V1_ENCODED_SIZE];
        uint8_t e2[DUOFORGE_STATE_V1_ENCODED_SIZE];
        duoforge_battle *a = df_make_battle(c1, &f1);
        duoforge_battle *b = df_make_battle(c1, &f1);
        df_encode(c1, a, e1);
        df_encode(c1, b, e2);
        DF_CHECK_BYTES(&t, e1, e2, sizeof e1, "F1 twice");
        duoforge_battle_destroy(b);

        duoforge_battle_setup v = f1;
        v.rng_initstate = 43u;
        b = df_make_battle(c1, &v);
        df_encode(c1, b, e2);
        unsigned outside = 0;
        for (unsigned i = 0; i < sizeof e1; ++i) {
            outside += (e1[i] != e2[i] && (i < 52u || i >= 60u)) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, outside, 0u);
        DF_CHECK(&t, memcmp(e1 + 52, e2 + 52, 8) != 0);
        duoforge_battle_destroy(b);

        v = f1;
        v.rng_initseq = 55u;
        b = df_make_battle(c1, &v);
        df_encode(c1, b, e2);
        outside = 0;
        for (unsigned i = 0; i < sizeof e1; ++i) {
            outside += (e1[i] != e2[i] && (i < 52u || i >= 68u)) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, outside, 0u);
        duoforge_battle_destroy(b);

        v = f1;
        v.rng_initseq = UINT64_C(0x7FFFFFFFFFFFFFFF); /* 2^63 - 1 is accepted */
        b = df_make_battle(c1, &v);
        duoforge_battle_destroy(b);
        duoforge_battle_destroy(a);
    }

    /* NULL arguments. */
    {
        df_sentinel sentinel;
        duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
        duoforge_battle *out = marker;
        DF_CHECK(&t, duoforge_battle_create(NULL, &f1, &out) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create(c1, NULL, &out) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_create(c1, &f1, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, out == marker);
    }

    /* Single-fault table under C1. */
    static const struct {
        mutator fn;
        const char *what;
    } c1_faults[] = {
        {f_seq_2_63, "initseq 2^63"},
        {f_seq_max, "initseq UINT64_MAX"},
        {f_s0_mc0, "s0 member_count 0"},
        {f_s0_mc3, "s0 member_count 3 (< brought)"},
        {f_s0_mc7, "s0 member_count 7"},
        {f_s0_mc262, "s0 member_count 262 (u8 -> 6)"},
        {f_s1_mc3, "s1 member_count 3"},
        {f_species16, "species 16"},
        {f_species65536, "species 65536 (u16 -> 0)"},
        {f_hp0, "hp_max 0"},
        {f_hp65536, "hp_max 65536"},
        {f_hp65636, "hp_max 65636 (u16 -> 100)"},
        {f_mc_move0, "move_count 0"},
        {f_mc_move5, "move_count 5"},
        {f_mc_move257, "move_count 257 (u8 -> 1)"},
        {f_move_id32, "move_id 32"},
        {f_move_id65536, "move_id 65536 (u16 -> 0)"},
        {f_pp0, "pp_max 0"},
        {f_pp256, "pp_max 256"},
        {f_pp261, "pp_max 261 (u8 -> 5)"},
        {f_unused_move_id, "unused move with id"},
        {f_unused_move_pp, "unused move with pp_max"},
        {f_unused_member_species, "unused member with species"},
        {f_unused_member_move_pp, "unused member with move pp_max"},
        {f_mask_out_of_range, "brought bit >= member_count (s1)"},
        {f_mask_bit31, "mask bit 31 (u8 -> 0x0F)"},
        {f_mask_pop3, "popcount 3"},
        {f_mask_pop5, "popcount 5"},
        {f_lead_not_brought, "lead not brought"},
        {f_lead_ge_count, "lead >= member_count (s1)"},
        {f_lead1_none, "leads[1] NONE with brought 4"},
        {f_lead_dup, "duplicate leads"},
        {f_lead0_0x102, "s0 leads[0] 0x102 (u8 -> 2)"},
        {f_lead1_0x100, "s1 leads[1] 0x100 (u8 -> 0)"},
    };
    for (unsigned i = 0; i < sizeof c1_faults / sizeof c1_faults[0]; ++i) {
        check_fails(&t, c1, &f1, c1_faults[i].fn, c1_faults[i].what);
    }
    /* Setting a max_roster-5 context makes member_count 6 invalid. */
    {
        duoforge_context_config cfg = df_config_c1;
        cfg.max_roster = 5u;
        duoforge_context *c5 = df_make_context(&cfg);
        df_sentinel sentinel;
        duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
        duoforge_battle *out = marker;
        DF_CHECK(&t, duoforge_battle_create(c5, &f1, &out) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, out == marker);
        duoforge_context_destroy(c5);
    }
    static const struct {
        mutator fn;
        const char *what;
    } c3_faults[] = {
        {f_c3_lead1_set, "C3 leads[1] set"},
        {f_c3_lead0_none, "C3 leads[0] NONE"},
        {f_c3_lead1_0x1ff, "C3 leads[1] 0x1FF (u8 -> NONE)"},
    };
    for (unsigned i = 0; i < sizeof c3_faults / sizeof c3_faults[0]; ++i) {
        check_fails(&t, c3, &f3, c3_faults[i].fn, c3_faults[i].what);
    }

    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    return df_test_end(&t);
}
