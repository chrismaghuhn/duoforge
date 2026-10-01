#include "support/fixtures.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "state/knowledge.h"
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
const duoforge_context_config df_config_k1 = {DUOFORGE_DATA_KIND_CLOSURE, 6u, 4u, 0u, 0u, NULL};
const duoforge_context_config df_config_k2 = {DUOFORGE_DATA_KIND_CLOSURE_DEV, 6u, 4u, 0u, 0u, NULL};

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

/* One member of decision 0004: species, gender, nature, Stat Points (HP, Atk,
 * Def, SpA, SpD, Spe), ability and item ids of the generated tables, moves. */
typedef struct df_set {
    uint32_t species;
    uint32_t gender;
    uint32_t nature;
    uint32_t sp[6];
    uint32_t ability;
    uint32_t item;
    uint32_t moves[4];
} df_set;

/* Ids from src/data/closure_tables.h; Stat Points and natures from the
 * pastes in decision 0004. Genders: Grimmsnarl is male in the paste and
 * male-only; Gholdengo is genderless; the others are chosen for the tests
 * (the owner specifies gender in every fixture). */
static const df_set df_team_a[6] = {
    {0u, 1u, 0u, {18u, 32u, 2u, 0u, 6u, 8u}, 0u, 0u, {0u, 1u, 2u, 3u}},      /* Rillaboom @ Miracle Seed */
    {1u, 2u, 11u, {32u, 0u, 0u, 0u, 2u, 32u}, 1u, 1u, {4u, 5u, 6u, 7u}},    /* Staraptor @ Staraptite */
    {3u, 2u, 4u, {32u, 0u, 29u, 0u, 5u, 0u}, 2u, 2u, {8u, 9u, 10u, 11u}},   /* Milotic @ Sitrus Berry */
    {4u, 1u, 0u, {31u, 7u, 24u, 0u, 3u, 1u}, 3u, 3u, {12u, 13u, 14u, 7u}},  /* Ceruledge @ Grassy Seed */
    {5u, 2u, 24u, {29u, 0u, 5u, 0u, 0u, 32u}, 4u, 4u, {15u, 16u, 2u, 7u}},  /* Raichu @ Raichunite Y */
    {7u, 3u, 15u, {17u, 0u, 2u, 17u, 16u, 14u}, 5u, 5u, {17u, 18u, 19u, 7u}}, /* Gholdengo @ Life Orb */
};
static const df_set df_team_b[6] = {
    {8u, 1u, 15u, {32u, 0u, 0u, 30u, 0u, 4u}, 6u, 6u, {20u, 8u, 10u, 7u}},    /* Politoed @ Mystic Water */
    {9u, 2u, 0u, {32u, 32u, 0u, 0u, 1u, 1u}, 7u, 7u, {21u, 22u, 23u, 7u}},    /* Golisopod @ Golisopite */
    {11u, 1u, 2u, {32u, 0u, 1u, 0u, 24u, 9u}, 8u, 8u, {24u, 25u, 26u, 7u}},   /* Archaludon @ Leftovers */
    {12u, 2u, 2u, {29u, 0u, 20u, 0u, 17u, 0u}, 9u, 2u, {27u, 28u, 29u, 7u}},  /* Farigiraf @ Sitrus Berry */
    {13u, 1u, 24u, {16u, 0u, 18u, 3u, 0u, 29u}, 10u, 9u, {30u, 20u, 31u, 7u}}, /* Charizard @ Charizardite Y */
    {15u, 1u, 22u, {32u, 0u, 14u, 0u, 20u, 0u}, 11u, 10u, {32u, 33u, 34u, 35u}}, /* Grimmsnarl @ Light Clay */
};

static void df_put_team(duoforge_side_setup *side, const df_set *team)
{
    side->member_count = 6u;
    for (uint32_t m = 0; m < 6u; ++m) {
        duoforge_member_setup *dst = &side->members[m];
        dst->species_id = team[m].species;
        dst->gender = team[m].gender;
        dst->nature = team[m].nature;
        for (uint32_t i = 0; i < 6u; ++i) {
            dst->stat_points[i] = team[m].sp[i];
        }
        dst->ability = team[m].ability + 1u;
        dst->item = team[m].item + 1u;
        dst->move_count = 4u;
        for (uint32_t k = 0; k < 4u; ++k) {
            dst->moves[k].move_id = team[m].moves[k];
        }
    }
}

void df_setup_teams(duoforge_battle_setup *out)
{
    memset(out, 0, sizeof *out);
    out->rng_initstate = 2026u;
    out->rng_initseq = 1001u;
    df_put_team(&out->sides[0], df_team_a);
    df_put_team(&out->sides[1], df_team_b);
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
    df_see_active(b); /* the leads' [switch] lines */
    df_checked(ctx, b, what);
}

void df_knowledge_see_hp(duoforge_battle *b, uint32_t side, uint32_t roster)
{
    const dfi_member *mem = &b->sides[side].members[roster];
    dfi_knowledge *k = &b->sides[1u - side].knowledge[roster];
    dfi_hp_display(mem->hp, mem->hp_max, &k->hp_percent, &k->hp_flag);
}

void df_knowledge_refresh_active(duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER) {
                df_knowledge_see_hp(b, s, occupant);
            }
        }
    }
}

void df_see_active(duoforge_battle *b)
{
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[s].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER) {
                b->sides[1u - s].seen_mask = (uint8_t)(b->sides[1u - s].seen_mask | (1u << occupant));
                df_knowledge_see_hp(b, s, occupant);
            }
        }
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
    b->sides[0].members[2].hp = 24u; /* 20 percent of 120, red: what side 1 sees last */
    df_knowledge_refresh_active(b);
    if (dfi_vacate(b, s0a) != DUOFORGE_OK || dfi_place(b, s0a, 3u, &binding) != DUOFORGE_OK ||
        dfi_vacate(b, s1b) != DUOFORGE_OK) {
        df_fail("F2 identity primitives");
    }
    df_see_active(b); /* roster 3's [switch] line */
    b->sides[1].requested_slots = 1u;
    b->sides[0].members[2].hp = 40u; /* on the bench: unseen by side 1 */
    b->sides[0].members[0].hp = 0u;
    b->sides[0].members[1].hp = 57u;
    b->sides[0].members[1].moves[0].pp = 0u;
    b->sides[1].members[2].hp = 0u;
    b->sides[1].members[0].moves[3].pp = 7u;
    b->sides[0].mega_used = 1u;
    df_knowledge_refresh_active(b);
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
    df_knowledge_refresh_active(b);
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
    b->turn = 7u;
    dfi_side *s0 = &b->sides[0];
    dfi_side *s1 = &b->sides[1];
    s0->requested_slots = 1u;
    s1->requested_slots = 0u;
    b->weather = (uint8_t)DFI_WEATHER_RAIN;
    b->weather_turns = 3u;
    b->terrain = (uint8_t)DFI_TERRAIN_GRASSY;
    b->terrain_turns = 5u;
    b->trick_room_turns = 2u;
    s0->reflect_turns = 8u;
    s0->tailwind_turns = 1u;
    s1->light_screen_turns = 4u;
    s1->tailwind_turns = 3u;
    static const uint8_t stages_s0a[DFI_STAT_STAGE_COUNT] = {0u, 6u, 12u, 6u, 7u, 6u, 5u};
    static const uint8_t stages_s1b[DFI_STAT_STAGE_COUNT] = {6u, 6u, 6u, 6u, 6u, 5u, 8u};
    for (uint32_t i = 0; i < DFI_STAT_STAGE_COUNT; ++i) {
        s0->positions[0].stages[i] = stages_s0a[i];
        s1->positions[1].stages[i] = stages_s1b[i];
    }
    s0->positions[0].move_actions = 3u;
    s0->positions[1].flags = (uint8_t)(DFI_VOL_PROTECT | DFI_VOL_FLASH_FIRE);
    s0->positions[1].stall_level = 2u;
    s0->positions[1].stall_turns = 1u;
    s0->positions[1].move_actions = 1u;
    s1->positions[0].confusion_turns = 4u;
    s1->positions[0].charge_turns = 1u;
    s1->positions[0].locked_move = 3u;
    s1->positions[0].locked_target = 0u;
    s1->positions[0].move_actions = 255u;
    s1->positions[1].flags = (uint8_t)DFI_VOL_FLINCH;
    s1->positions[1].charge_turns = 2u;
    s1->positions[1].locked_move = 1u;
    s1->positions[1].locked_target = (uint8_t)DUOFORGE_TARGET_NONE;
    s0->positions[0].switch_flag = (uint8_t)DFI_SWITCH_MOVE; /* Parting Shot */
    s1->members[1].hp = 101u; /* 50 percent of 201, green */
    df_knowledge_refresh_active(b);
    static const uint8_t used_s0[2][DUOFORGE_MAX_MOVE_SLOTS] = {{2u, 0u, 1u, 0u}, {0u, 0u, 0u, 255u}};
    static const uint8_t used_s1[2][DUOFORGE_MAX_MOVE_SLOTS] = {{1u, 1u, 0u, 0u}, {9u, 0u, 0u, 0u}};
    for (uint32_t k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        s0->knowledge[1].moves_used[k] = used_s0[0][k];
        s0->knowledge[3].moves_used[k] = used_s0[1][k];
        s1->knowledge[2].moves_used[k] = used_s1[0][k];
        s1->knowledge[0].moves_used[k] = used_s1[1][k];
    }
    b->queue_len = 3u;
    b->queue[0] = (dfi_queue_record){.kind = DFI_Q_MOVE, .side = 1u, .slot = 0u, .move_slot = 2u, .target = 0u,
                                     .activation_id = 3u};
    b->queue[1] = (dfi_queue_record){.kind = DFI_Q_MOVE, .side = 1u, .slot = 1u,
                                     .move_slot = DFI_MOVE_SLOT_STRUGGLE, .target = DUOFORGE_TARGET_NONE,
                                     .activation_id = 4u};
    b->queue[2] = (dfi_queue_record){.kind = DFI_Q_RESIDUAL};
    df_checked(c1, b, "F5 check");
    return b;
}

duoforge_battle *df_make_f6(const duoforge_context *c1)
{
    duoforge_battle *b = df_make_f5(c1);
    b->request_mask = 3u;
    b->sides[1].requested_slots = 2u;
    b->sides[1].positions[1].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    b->queue_len = 6u;
    b->queue[0] = (dfi_queue_record){.kind = DFI_Q_SWITCH_IN, .side = 0u, .slot = 0u, .reserve = 5u};
    b->queue[1] = (dfi_queue_record){.kind = DFI_Q_RUN_SWITCH, .side = 0u, .slot = 1u, .activation_id = 2u};
    b->queue[2] = (dfi_queue_record){.kind = DFI_Q_SWITCH, .side = 1u, .slot = 0u, .reserve = 0u, .activation_id = 3u};
    b->queue[3] = (dfi_queue_record){.kind = DFI_Q_MEGA, .side = 0u, .slot = 1u, .activation_id = 2u};
    b->queue[4] = (dfi_queue_record){.kind = DFI_Q_MOVE, .side = 1u, .slot = 1u, .move_slot = 0u, .target = 1u,
                                     .activation_id = 4u};
    b->queue[5] = (dfi_queue_record){.kind = DFI_Q_RESIDUAL};
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
    df_knowledge_refresh_active(b);
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
    df_knowledge_refresh_active(b);
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

duoforge_battle *df_make_f13(const duoforge_context *c4)
{
    duoforge_battle *b = df_make_f9(c4);
    b->sides[1].members[1].hp = 0u;
    b->sides[1].members[2].hp = 0u;
    df_knowledge_refresh_active(b);
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL;
    b->request_epoch = 3u;
    b->request_mask = 0u;
    b->turn = 12u;
    b->result = (uint8_t)DFI_RESULT_SIDE0;
    b->sides[0].requested_slots = 0u;
    b->sides[1].requested_slots = 0u;
    df_checked(c4, b, "F13 check");
    return b;
}

void df_encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE])
{
    size_t written = 0;
    if (duoforge_battle_encode(ctx, b, out, DUOFORGE_STATE_V3_ENCODED_SIZE, &written) != DUOFORGE_OK ||
        written != DUOFORGE_STATE_V3_ENCODED_SIZE) {
        df_fail("duoforge_battle_encode");
    }
}
