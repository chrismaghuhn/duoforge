/*
 * duoforge.state.pool_g80 (white-box): step G80 of the content expansion (decision 0044): Psych Up, Howl and Ally Switch.
 *
 * The behaviour is replayed by duoforge.reference.conformance_pool_data: the recorded battles g80_* under "data": "pool" cover
 * Psych Up copying a Dragon Cheer stage 2 and the boosts, Howl on a Soundproof partner, Ally Switch's swap and the targets that
 * follow it, its consecutive roll, and Stomping Tantrum after the roll. This file checks what the battles do not show directly:
 * the rows (the special ids, the boost role and the target class, the support marks, the event and draw numbers), the Ally
 * Switch byte of the tail: its codec round trip in reserve bytes 4..7, the invariant that refuses a level or a turn count out of
 * range, and the Illusion refusal (E_UNSUPPORTED) of a swap whose partner may hold Illusion, set through the tail's ability_now.
 */
#include <stdio.h>
#include <string.h>

#include <stdlib.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "codec/state_codec.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* One slot's command of a turn: move slot and target flat position. */
typedef struct g80_cmd {
    uint8_t kind;
    uint8_t move_slot;
    uint8_t target;
    uint8_t reserve;
} g80_cmd;

#define MV(slot, target) {DUOFORGE_SLOT_MOVE, (slot), (target), 0u}
#define NO DUOFORGE_TARGET_NONE

static const df_conf_battle *find_conf(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void setup_from(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0u; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

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

static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b, const g80_cmd cmd[2][2])
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = cmd[side][slot].kind;
            c->slots[slot].move_slot = cmd[side][slot].move_slot;
            c->slots[slot].target = cmd[side][slot].target;
            c->slots[slot].reserve = cmd[side][slot].reserve;
        }
    }
}

/* Starts the recorded battle `name` (its context, its battle, the team preview). */
static bool start(df_test *t, const char *name, duoforge_context **ctx, duoforge_battle **b, duoforge_decision_bundle *bd,
                  duoforge_step_result *res)
{
    *ctx = df_make_context(&df_config_pool);
    DF_CHECK(t, *ctx != NULL);
    const df_conf_battle *cb = find_conf(name);
    DF_CHECK(t, cb != NULL);
    if (*ctx == NULL || cb == NULL) {
        return false;
    }
    duoforge_battle_setup s;
    setup_from(cb, &s);
    *b = df_make_battle(*ctx, &s);
    DF_CHECK(t, *b != NULL);
    if (*b == NULL) {
        return false;
    }
    team_bundle(bd, *b);
    return duoforge_battle_step(*ctx, *b, bd, res) == DUOFORGE_OK;
}

static void finish(duoforge_context *ctx, duoforge_battle *b)
{
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* The rows: the special ids and their order, the boost role and the target class, the unmodelled lists, the support marks, the
 * event numbers, the draw site and the Ally Switch byte's place in the reserve. */
static void test_rows(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PSYCH_UP, DFI_SPECIAL_DRAGON_CHEER + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ALLY_SWITCH, DFI_SPECIAL_PSYCH_UP + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_ALLY_SWITCH + 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_PSYCHUP].special, DFI_SPECIAL_PSYCH_UP);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_ALLYSWITCH].special, DFI_SPECIAL_ALLY_SWITCH);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HOWL].boost_role, DFI_BOOST_ROLE_PRIMARY_TARGET);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HOWL].target_class, DFI_TARGET_CLASS_ALLIES);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_PSYCHUP] == NULL);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_HOWL] == NULL);
    DF_CHECK(t, dfi_pool_move_unmodeled[DFI_MOVE_ALLYSWITCH] == NULL);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_PSYCHUP], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_HOWL], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ALLYSWITCH], 1u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_SWAP, 49u);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_COPY_BOOST, 50u);
    DF_CHECK_EQ_U64(t, DFI_SITE_ALLY_SWITCH, 23u);
    DF_CHECK_EQ_U64(t, DFI_SITE_COUNT, 24u);
    DF_CHECK_EQ_U64(t, DFI_ALLY_SWITCH_MAX, 26u); /* level 6, two turns: (6 << 2) | 2 */
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL5_ALLY_SWITCH_OFF, 4u);
    DF_CHECK_EQ_U64(t, DFI_ENC_TAIL5_ALLY_SWITCH_COUNT, 4u);
}

/* The Ally Switch byte of each position travels in the encoding (reserve bytes 4..7) and comes back unchanged. */
static void test_codec_round_trip(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g80_allyswitch_swap", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    b->tail.sides[0].positions[0].ally_switch = (uint8_t)((1u << DFI_ALLY_SWITCH_LEVEL_SHIFT) | 2u); /* level 1, two turns */
    b->tail.sides[0].positions[1].ally_switch = (uint8_t)DFI_ALLY_SWITCH_MAX;                       /* level 6, two turns */
    b->tail.sides[1].positions[0].ally_switch = (uint8_t)((3u << DFI_ALLY_SWITCH_LEVEL_SHIFT) | 1u); /* level 3, one turn */
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    size_t size = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_encoded_size(ctx, b, &size), DUOFORGE_OK);
    uint8_t *bytes = (uint8_t *)malloc(size);
    DF_CHECK(t, bytes != NULL);
    if (bytes == NULL) {
        finish(ctx, b);
        return;
    }
    size_t written = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_encode(ctx, b, bytes, size, &written), DUOFORGE_OK);
    const df_conf_battle *cb = find_conf("g80_allyswitch_swap");
    duoforge_battle_setup setup;
    setup_from(cb, &setup);
    duoforge_battle *dst = df_make_battle(ctx, &setup);
    DF_CHECK(t, dst != NULL);
    if (dst != NULL) {
        DF_CHECK_EQ_U64(t, duoforge_battle_decode(ctx, dst, bytes, written), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, dst->tail.sides[0].positions[0].ally_switch, b->tail.sides[0].positions[0].ally_switch);
        DF_CHECK_EQ_U64(t, dst->tail.sides[0].positions[1].ally_switch, b->tail.sides[0].positions[1].ally_switch);
        DF_CHECK_EQ_U64(t, dst->tail.sides[1].positions[0].ally_switch, b->tail.sides[1].positions[0].ally_switch);
        DF_CHECK_EQ_U64(t, dst->tail.sides[1].positions[1].ally_switch, 0u);
        duoforge_battle_destroy(dst);
    }
    free(bytes);
    finish(ctx, b);
}

/* The invariant: a level 0, a level above 6, a turn count of 0 or 3 and a byte at a stopped position are refused. */
static void test_invariant(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g80_allyswitch_swap", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    static const uint8_t bad[] = {1u, 2u, 3u, 8u, 27u, 28u, 0xFFu}; /* level 0 (turns 1-3); level 2 with 0 turns; level 6 with 3 turns; level 7 */
    for (size_t i = 0u; i < sizeof bad / sizeof bad[0]; ++i) {
        b->tail.sides[0].positions[0].ally_switch = bad[i];
        DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_E_INVARIANT);
    }
    b->tail.sides[0].positions[0].ally_switch = 0u;
    b->tail.sides[0].positions[0].ally_switch_pad = 1u; /* the explicit pad byte is never set */
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_E_INVARIANT);
    b->tail.sides[0].positions[0].ally_switch_pad = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_check(ctx, b), DUOFORGE_OK);
    finish(ctx, b);
}

/* The Illusion refusal (decision 0044 section 5): a swap whose partner may hold Illusion is E_UNSUPPORTED before anything
 * changes. Illusion is not modelled, so the holder is set through the tail's ability_now of the partner's roster member. */
static void test_illusion_refusal(df_test *t)
{
    duoforge_context *ctx = NULL;
    duoforge_battle *b = NULL;
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    if (!start(t, "g80_allyswitch_swap", &ctx, &b, &bd, &res)) {
        finish(ctx, b);
        return;
    }
    const uint32_t partner_member = b->sides[0].positions[1].occupant;
    DF_CHECK(t, partner_member < DUOFORGE_MAX_ROSTER);
    if (partner_member >= DUOFORGE_MAX_ROSTER) {
        finish(ctx, b);
        return;
    }
    b->tail.sides[0].ability_now[partner_member] = (uint16_t)(DFI_ABILITY_ILLUSION + 1u);
    /* As the recorded swap battle's first turn: Chimecho (slot 0) and Audino (slot 1) use Ally Switch (move 0, no target); the
     * foe's Malamar aims Foul Play at our slot 0 and Spiritomb at our slot 1 (targets are flat positions) */
    static const g80_cmd turn1[2][2] = {{MV(0, NO), MV(0, NO)}, {MV(0, 0u), MV(0, NO)}};
    turn_bundle(&bd, b, turn1);
    const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    finish(ctx, b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g80");
    test_rows(&t);
    test_codec_round_trip(&t);
    test_invariant(&t);
    test_illusion_refusal(&t);
    return df_test_end(&t);
}
