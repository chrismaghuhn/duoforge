/*
 * T22 duoforge.state.setup_sweep (black-box): every scalar of the setup v2
 * (148 fields) is set, one at a time, to each value of a fixed set (29 u32
 * values; 32 for the two RNG fields). The result must always be OK or
 * INVALID_ARGUMENT (never INVARIANT or anything else), *out must stay at its
 * sentinel on error, a created battle must pass check, and the OK/INVALID
 * counts per (side, class) must equal the independent structural model
 * (tools/state_model/state_v2_model.py). 8,596 creates in total.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"

static const uint32_t v32[] = {
    0u, 1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u, 15u, 16u, 31u, 32u, 33u, 63u, 255u, 256u, 257u, 258u, 261u, 262u, 511u,
    65535u, 65536u, 65552u, 65636u, 0x7FFFFFFFu, 0x80000000u, 0xFFFFFFFFu,
};
#define V32_COUNT (sizeof v32 / sizeof v32[0])
static const uint64_t v64_extra[] = {UINT64_C(0x7FFFFFFFFFFFFFFF), UINT64_C(0x8000000000000000), UINT64_MAX};

enum cls {
    CLS_INITSTATE,
    CLS_INITSEQ,
    CLS_MEMBER_COUNT,
    CLS_SPECIES,
    CLS_HP_MAX,
    CLS_MOVE_COUNT,
    CLS_MEGA,
    CLS_MOVE_ID,
    CLS_PP_MAX,
    CLS_COUNT
};

typedef struct counts {
    unsigned ok[2][CLS_COUNT];
    unsigned bad[2][CLS_COUNT];
    unsigned creates;
    unsigned unexpected;
} counts;

/* Pointer to the scalar for (side, member, move, class) in a setup. */
static uint32_t *field32(duoforge_battle_setup *s, unsigned side, unsigned m, unsigned k, enum cls c)
{
    duoforge_side_setup *sd = &s->sides[side];
    switch (c) {
    case CLS_MEMBER_COUNT:
        return &sd->member_count;
    case CLS_SPECIES:
        return &sd->members[m].species_id;
    case CLS_HP_MAX:
        return &sd->members[m].hp_max;
    case CLS_MOVE_COUNT:
        return &sd->members[m].move_count;
    case CLS_MEGA:
        return &sd->members[m].mega_capable;
    case CLS_MOVE_ID:
        return &sd->members[m].moves[k].move_id;
    case CLS_PP_MAX:
        return &sd->members[m].moves[k].pp_max;
    default:
        return NULL;
    }
}

static void run_one(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, unsigned side,
                    enum cls c, counts *n)
{
    df_sentinel sentinel;
    duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
    duoforge_battle *out = marker;
    const duoforge_status st = duoforge_battle_create(ctx, s, &out);
    n->creates++;
    if (st == DUOFORGE_OK) {
        n->ok[side][c]++;
        DF_CHECK(t, duoforge_battle_check(ctx, out) == DUOFORGE_OK);
        duoforge_battle_destroy(out);
    } else if (st == DUOFORGE_E_INVALID_ARGUMENT) {
        n->bad[side][c]++;
        if (out != marker) {
            n->unexpected++;
        }
    } else {
        n->unexpected++;
        fprintf(stderr, "unexpected status %s (side %u class %d)\n", duoforge_status_name(st), side, (int)c);
    }
}

static void sweep(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *base, counts *n)
{
    memset(n, 0, sizeof *n);
    /* Battle-wide RNG fields (counted under side 0). */
    for (unsigned i = 0; i < V32_COUNT + 3; ++i) {
        const uint64_t v = i < V32_COUNT ? v32[i] : v64_extra[i - V32_COUNT];
        duoforge_battle_setup s = *base;
        s.rng_initstate = v;
        run_one(t, ctx, &s, 0, CLS_INITSTATE, n);
        s = *base;
        s.rng_initseq = v;
        run_one(t, ctx, &s, 0, CLS_INITSEQ, n);
    }
    for (unsigned side = 0; side < 2; ++side) {
        for (unsigned i = 0; i < V32_COUNT; ++i) {
            duoforge_battle_setup s = *base;
            *field32(&s, side, 0, 0, CLS_MEMBER_COUNT) = v32[i];
            run_one(t, ctx, &s, side, CLS_MEMBER_COUNT, n);
        }
        for (unsigned m = 0; m < DUOFORGE_MAX_ROSTER; ++m) {
            const enum cls member_fields[] = {CLS_SPECIES, CLS_HP_MAX, CLS_MOVE_COUNT, CLS_MEGA};
            for (unsigned f = 0; f < 4; ++f) {
                for (unsigned i = 0; i < V32_COUNT; ++i) {
                    duoforge_battle_setup s = *base;
                    *field32(&s, side, m, 0, member_fields[f]) = v32[i];
                    run_one(t, ctx, &s, side, member_fields[f], n);
                }
            }
            for (unsigned k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                const enum cls move_fields[] = {CLS_MOVE_ID, CLS_PP_MAX};
                for (unsigned f = 0; f < 2; ++f) {
                    for (unsigned i = 0; i < V32_COUNT; ++i) {
                        duoforge_battle_setup s = *base;
                        *field32(&s, side, m, k, move_fields[f]) = v32[i];
                        run_one(t, ctx, &s, side, move_fields[f], n);
                    }
                }
            }
        }
    }
}

/* Expected OK/INVALID per class: [class][side] (independent model). */
typedef struct expect {
    unsigned ok[CLS_COUNT][2];
    unsigned bad[CLS_COUNT][2];
} expect;

static void compare(df_test *t, const counts *n, const expect *e, const char *label)
{
    static const char *names[CLS_COUNT] = {"rng_initstate", "rng_initseq", "member_count", "species_id",
                                           "hp_max",        "move_count",  "mega_capable", "move_id",
                                           "pp_max"};
    for (unsigned c = 0; c < CLS_COUNT; ++c) {
        for (unsigned side = 0; side < 2; ++side) {
            if (!DF_CHECK(t, n->ok[side][c] == e->ok[c][side] && n->bad[side][c] == e->bad[c][side])) {
                fprintf(stderr, "  %s side %u %s: OK=%u INVALID=%u, expected OK=%u INVALID=%u\n", label, side,
                        names[c], n->ok[side][c], n->bad[side][c], e->ok[c][side], e->bad[c][side]);
            }
        }
    }
    DF_CHECK_EQ_U64(t, n->creates, 4298u);
    DF_CHECK_EQ_U64(t, n->unexpected, 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.setup_sweep");
    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_battle_setup g1;
    duoforge_battle_setup g3;
    df_setup_g1(&g1);
    df_setup_g3(&g3);

    /* Values from tools/state_model/state_v2_model.py (setup section). */
    static const expect e_g1 = {
        .ok = {{32, 0}, {30, 0}, {1, 1}, {60, 42}, {132, 90}, {6, 6}, {12, 10}, {193, 232}, {206, 248}},
        .bad = {{0, 0}, {2, 0}, {28, 28}, {114, 132}, {42, 84}, {168, 168}, {162, 164}, {503, 464}, {490, 448}},
    };
    static const expect e_g3 = {
        .ok = {{32, 0}, {30, 0}, {1, 1}, {33, 24}, {69, 48}, {6, 6}, {9, 8}, {63, 76}, {66, 80}},
        .bad = {{0, 0}, {2, 0}, {28, 28}, {141, 150}, {105, 126}, {168, 168}, {165, 166}, {633, 620}, {630, 616}},
    };
    counts n;
    sweep(&t, c1, &g1, &n);
    compare(&t, &n, &e_g1, "G1/C1");
    sweep(&t, c3, &g3, &n);
    compare(&t, &n, &e_g3, "G3/C3");

    duoforge_context_destroy(c1);
    duoforge_context_destroy(c3);
    return df_test_end(&t);
}
