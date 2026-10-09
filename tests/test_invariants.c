/*
 * T9 duoforge.state.invariants (white-box): one targeted corruption per
 * invariant id v3 on a fixture copy (the exact first-violation id is
 * asserted), allowed structural states (every fixture, including
 * REPLACEMENT, PIVOT and TERMINAL boundaries that no mechanic produces yet),
 * range-before-use on hostile counts (runs under ASan/UBSan),
 * first-violation order and checker purity.
 * Expectations: the invariant contract (docs/decisions/0002, 0005, 0006).
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"

static void expect_inv(df_test *t, const duoforge_context *c1, const duoforge_battle *b, dfi_invariant expected,
                       const char *what)
{
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status st = dfi_state_check(c1, b, &got);
    const duoforge_status expected_status =
        expected == DFI_INV_CONTEXT_FINGERPRINT ? DUOFORGE_E_CONTEXT_MISMATCH : DUOFORGE_E_INVARIANT;
    if (!DF_CHECK(t, st == expected_status && got == expected)) {
        fprintf(stderr, "  case %s: got %s (%s), expected %s\n", what, dfi_invariant_name(got),
                duoforge_status_name(st), dfi_invariant_name(expected));
    }
    DF_CHECK(t, duoforge_battle_check(c1, b) == expected_status);
}

static void expect_ok(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const char *what)
{
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status st = dfi_state_check(ctx, b, &got);
    if (!DF_CHECK(t, st == DUOFORGE_OK)) {
        fprintf(stderr, "  valid case %s rejected: %s\n", what, dfi_invariant_name(got));
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.invariants");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_context *c3 = df_make_context(&df_config_c3);
    duoforge_context *c4 = df_make_context(&df_config_c4);
    duoforge_battle *g1 = df_make_g1(c1);
    duoforge_battle *f1 = df_make_f1(c1);
    duoforge_battle *f2 = df_make_f2(c1);
    duoforge_battle *f4 = df_make_f4(c1);
    duoforge_battle *f5 = df_make_f5(c1);
    duoforge_battle *f6 = df_make_f6(c1);

    /* Allowed structural states: every fixture (the builders already checked
     * them; this keeps the evidence in one place). */
    expect_ok(&t, c1, g1, "G1");
    expect_ok(&t, c1, f1, "F1");
    expect_ok(&t, c1, f2, "F2");
    expect_ok(&t, c1, f4, "F4 (two-side REPLACEMENT)");
    expect_ok(&t, c1, f5, "F5 (one-side PIVOT, every v3 group in use)");
    expect_ok(&t, c1, f6, "F6 (two-side PIVOT, every queue kind)");
    {
        duoforge_battle *g3 = df_make_g3(c3);
        duoforge_battle *f3 = df_make_f3(c3);
        duoforge_battle *others[7] = {df_make_g7(c4),  df_make_f8(c4),  df_make_f9(c4), df_make_f10(c4),
                                      df_make_f11(c4), df_make_f12(c4), df_make_f13(c4)};
        expect_ok(&t, c3, g3, "G3");
        expect_ok(&t, c3, f3, "F3");
        for (unsigned i = 0; i < 7; ++i) {
            expect_ok(&t, c4, others[i], "C4 fixture");
            duoforge_battle_destroy(others[i]);
        }
        duoforge_battle_destroy(g3);
        duoforge_battle_destroy(f3);
    }

    duoforge_battle *w = NULL;
    DF_CHECK(&t, duoforge_battle_clone(c1, f1, &w) == DUOFORGE_OK);
#define RESET() DF_CHECK(&t, duoforge_battle_copy(c1, w, f1) == DUOFORGE_OK)
#define RESET_TO(src) DF_CHECK(&t, duoforge_battle_copy(c1, w, (src)) == DUOFORGE_OK)

    w->sides[0].members[2].hp = 0u; /* fainted occupant (s0a) */
    df_knowledge_refresh_active(w);
    expect_ok(&t, c1, w, "fainted occupant");
    RESET();
    w->sides[0].members[5].hp = 0u; /* fainted reserve */
    expect_ok(&t, c1, w, "fainted reserve");
    RESET();
    w->sides[1].members[0].moves[0].pp = 0u;
    expect_ok(&t, c1, w, "pp 0");
    RESET();
    dfi_slot_clear(&w->sides[1].positions[0]);
    dfi_slot_clear(&w->sides[1].positions[1]);
    w->sides[1].requested_slots = 0u;
    expect_ok(&t, c1, w, "both slots of a side empty (the knowledge about them stays)");
    RESET();
    w->rng.draws = UINT64_MAX;
    w->rng.state = 0u;
    expect_ok(&t, c1, w, "any rng state and draws");
    RESET();
    w->sides[0].positions[0].activation_id = 3u; /* ids 3,2,4 plus 7 < next 9 */
    w->sides[1].positions[0].activation_id = 7u;
    w->next_activation_id = 9u;
    expect_ok(&t, c1, w, "non-contiguous activation ids");
    RESET();
    w->sides[0].seen_mask = 0x0Fu; /* seeing more brought members than the leads is legal */
    expect_ok(&t, c1, w, "seen superset of occupants");
    RESET();
    w->request_epoch = UINT32_MAX; /* exhausted but structurally fine */
    expect_ok(&t, c1, w, "epoch at maximum");
    RESET();
    /* v3 groups at their range ends: structural, not reachable yet. */
    w->turn = UINT16_MAX;
    w->weather = (uint8_t)DFI_WEATHER_SUN;
    w->weather_turns = 5u;
    w->terrain = (uint8_t)DFI_TERRAIN_GRASSY;
    w->terrain_turns = 1u;
    w->trick_room_turns = 5u;
    w->sides[0].reflect_turns = 8u;
    w->sides[0].light_screen_turns = 8u;
    w->sides[1].tailwind_turns = 4u;
    expect_ok(&t, c1, w, "field and side conditions at their maxima");
    RESET();
    for (unsigned i = 0; i < DFI_STAT_STAGE_COUNT; ++i) {
        w->sides[0].positions[0].stages[i] = (i & 1u) != 0u ? 12u : 0u;
    }
    w->sides[0].positions[0].flags = 7u;
    w->sides[0].positions[0].stall_level = 6u;
    w->sides[0].positions[0].stall_turns = 1u;
    w->sides[0].positions[0].confusion_turns = 5u;
    w->sides[0].positions[0].charge_turns = 2u;
    w->sides[0].positions[0].locked_move = 3u; /* roster 2 has three moves */
    w->sides[0].positions[0].locked_target = 3u;
    w->sides[0].positions[0].move_actions = 255u;
    expect_ok(&t, c1, w, "volatile block at its maxima");
    RESET_TO(f5);
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    expect_ok(&t, c1, w, "the other pivot cause");
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_FAINTED;
    expect_ok(&t, c1, w, "checkFainted's flag kept by a pass");
    RESET();
    w->sides[0].knowledge[2].hp_percent = 20u; /* s1 member 2 is on the bench */
    w->sides[0].knowledge[2].hp_flag = (uint8_t)DUOFORGE_HP_FLAG_YELLOW;
    w->sides[0].seen_mask = 0x0Eu;
    w->sides[0].knowledge[2].moves_used[3] = 255u;
    expect_ok(&t, c1, w, "any valid display for a seen member on the bench");
    RESET();
    /* A re-prompt at TURN: side 1 waits with a sealed choice. */
    w->request_mask = 1u;
    w->sides[1].requested_slots = 0u;
    w->sides[1].sealed = 1u;
    w->sides[1].sealed_cmds[0] = (dfi_slot_cmd){DFI_SLOT_SWITCH, 0u, 0u, 0u, 0u};
    w->sides[1].sealed_cmds[1] = (dfi_slot_cmd){DFI_SLOT_MOVE, 2u, 0u, 0u, 0u};
    expect_ok(&t, c1, w, "re-prompt at TURN with a sealed side");
    duoforge_battle *rp = NULL;
    DF_CHECK(&t, duoforge_battle_clone(c1, w, &rp) == DUOFORGE_OK);
    RESET();

    /* One corruption per invariant id (in check order). */
    w->context_fingerprint[31] ^= 1u;
    expect_inv(&t, c1, w, DFI_INV_CONTEXT_FINGERPRINT, "fingerprint");
    w->context_fingerprint[31] ^= 1u; /* copy() refuses a foreign dst */
    RESET();
    w->rng.inc &= ~UINT64_C(1);
    expect_inv(&t, c1, w, DFI_INV_RNG_INC_EVEN, "inc even");
    RESET();
    w->next_activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_NEXT_ACTIVATION_ZERO, "next 0");
    RESET();
    w->boundary_kind = 0u;
    expect_inv(&t, c1, w, DFI_INV_BOUNDARY_KIND, "boundary 0");
    RESET();
    w->boundary_kind = 6u;
    expect_inv(&t, c1, w, DFI_INV_BOUNDARY_KIND, "boundary 6");
    RESET();
    w->request_epoch = 0u;
    expect_inv(&t, c1, w, DFI_INV_EPOCH_ZERO, "epoch 0");
    RESET();
    w->request_mask = 0u;
    expect_inv(&t, c1, w, DFI_INV_REQUEST_MASK, "request mask 0");
    RESET();
    w->request_mask = 4u;
    expect_inv(&t, c1, w, DFI_INV_REQUEST_MASK, "request mask 4");
    RESET();
    w->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL; /* a finished battle requests nobody */
    expect_inv(&t, c1, w, DFI_INV_REQUEST_MASK, "request mask at TERMINAL");
    RESET();
    w->turn = 0u;
    expect_inv(&t, c1, w, DFI_INV_TURN_COUNTER, "turn 0 after team selection");
    RESET_TO(g1);
    w->turn = 1u;
    expect_inv(&t, c1, w, DFI_INV_TURN_COUNTER, "turn 1 at TEAM_SELECTION");
    RESET();
    w->result = (uint8_t)DFI_RESULT_SIDE1;
    expect_inv(&t, c1, w, DFI_INV_RESULT, "result before TERMINAL");
    RESET();
    w->result = 4u;
    expect_inv(&t, c1, w, DFI_INV_RESULT, "result 4");
    RESET();
    w->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_TERMINAL;
    w->request_mask = 0u;
    expect_inv(&t, c1, w, DFI_INV_RESULT, "TERMINAL without a result");
    RESET();
    w->weather = 3u;
    w->weather_turns = 1u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "weather 3");
    RESET();
    w->weather = (uint8_t)DFI_WEATHER_RAIN;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "weather without turns");
    RESET();
    w->weather_turns = 2u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "weather turns without weather");
    RESET();
    w->weather = (uint8_t)DFI_WEATHER_SUN;
    w->weather_turns = 6u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "weather turns 6");
    RESET();
    w->terrain = 2u;
    w->terrain_turns = 1u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "terrain 2");
    RESET();
    w->terrain = (uint8_t)DFI_TERRAIN_GRASSY;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "terrain without turns");
    RESET();
    w->terrain_turns = 5u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "terrain turns without terrain");
    RESET();
    w->trick_room_turns = 6u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "Trick Room turns 6");
    RESET();
    w->sides[0].member_count = 3u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_COUNT, "member_count below brought");
    RESET();
    w->sides[1].member_count = 7u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_COUNT, "member_count 7");
    RESET();
    w->sides[0].members[0].species_id = 16u;
    expect_inv(&t, c1, w, DFI_INV_SPECIES_RANGE, "species 16");
    RESET();
    w->sides[0].members[0].hp_max = 0u;
    expect_inv(&t, c1, w, DFI_INV_HP_MAX_ZERO, "hp_max 0");
    RESET();
    w->sides[0].members[0].hp = 101u;
    expect_inv(&t, c1, w, DFI_INV_HP_ABOVE_MAX, "hp above max");
    RESET();
    w->sides[0].members[0].move_count = 0u;
    expect_inv(&t, c1, w, DFI_INV_MOVE_COUNT, "move_count 0");
    RESET();
    w->sides[0].members[0].move_count = 5u;
    expect_inv(&t, c1, w, DFI_INV_MOVE_COUNT, "move_count 5");
    RESET();
    w->sides[0].members[0].moves[0].move_id = 36u;
    expect_inv(&t, c1, w, DFI_INV_MOVE_ID_RANGE, "move id 36");
    RESET();
    w->sides[0].members[0].moves[0].pp_max = 0u;
    expect_inv(&t, c1, w, DFI_INV_PP_MAX_ZERO, "pp_max 0");
    RESET();
    w->sides[0].members[0].moves[0].pp = 6u;
    expect_inv(&t, c1, w, DFI_INV_PP_ABOVE_MAX, "pp above max");
    RESET();
    w->sides[0].members[0].moves[1].pp = 1u;
    expect_inv(&t, c1, w, DFI_INV_UNUSED_MOVE_NONZERO, "unused move");
    RESET();
    w->sides[0].members[0].mega_capable = 2u;
    expect_inv(&t, c1, w, DFI_INV_MEGA_CAPABLE_RANGE, "mega_capable 2");
    RESET();
    /* SYNTHETIC data has none of the v3 member fields. */
    w->sides[0].members[3].stats[4] = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "stat on a synthetic member");
    RESET();
    w->sides[0].members[1].is_mega = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "is_mega");
    RESET();
    w->sides[0].members[0].gender = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "gender");
    RESET();
    w->sides[0].members[0].nature = 24u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "nature");
    RESET();
    w->sides[1].members[3].stat_points[5] = 32u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "stat points");
    RESET();
    w->sides[0].members[0].status = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "status");
    RESET();
    w->sides[0].members[0].status_counter = 3u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "status counter");
    RESET();
    w->sides[0].members[0].item = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "item");
    RESET();
    w->sides[0].members[0].item_consumed = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "item consumed");
    RESET();
    w->sides[0].members[0].ability = 1u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "ability");
    RESET();
    w->sides[1].members[4].hp = 1u;
    expect_inv(&t, c1, w, DFI_INV_UNUSED_MEMBER_NONZERO, "unused member");
    RESET();
    w->sides[1].members[5].ability = 1u;
    expect_inv(&t, c1, w, DFI_INV_UNUSED_MEMBER_NONZERO, "unused member v3 field");
    RESET();
    w->sides[1].members[5].mega_capable = 1u;
    expect_inv(&t, c1, w, DFI_INV_UNUSED_MEMBER_NONZERO, "unused member mega flag");
    RESET();
    w->sides[1].brought_mask = 0x17u;
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_OUT_OF_RANGE, "brought out of range");
    RESET();
    w->sides[0].brought_mask = 0x07u;
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_COUNT, "brought count");
    RESET_TO(g1);
    w->sides[0].brought_mask = 0x0Fu;
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_COUNT, "brought at TEAM_SELECTION");
    RESET();
    w->sides[0].brought_order[0] = 5u; /* not brought */
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_ORDER, "order entry not brought");
    RESET();
    w->sides[0].brought_order[0] = 6u; /* >= member_count, before the bit test */
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_ORDER, "order entry out of range");
    RESET();
    w->sides[0].brought_order[1] = 2u; /* duplicate of order[0] */
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_ORDER, "order duplicate");
    RESET();
    w->sides[0].brought_order[4] = 0u; /* must be NONE */
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_ORDER, "order tail not NONE");
    RESET();
    w->sides[0].mega_used = 2u;
    expect_inv(&t, c1, w, DFI_INV_MEGA_USED_RANGE, "mega_used 2");
    RESET();
    w->sides[0].reflect_turns = 9u;
    expect_inv(&t, c1, w, DFI_INV_SIDE_CONDITION, "Reflect turns 9");
    RESET();
    w->sides[1].light_screen_turns = 9u;
    expect_inv(&t, c1, w, DFI_INV_SIDE_CONDITION, "Light Screen turns 9");
    RESET();
    w->sides[1].tailwind_turns = 5u;
    expect_inv(&t, c1, w, DFI_INV_SIDE_CONDITION, "Tailwind turns 5");
    RESET();
    w->sides[0].positions[0].occupant = DFI_OCCUPANT_NONE;
    expect_inv(&t, c1, w, DFI_INV_EMPTY_WITH_ACTIVATION, "empty with activation");
    RESET();
    w->sides[1].positions[1].activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPIED_WITHOUT_ACTIVATION, "occupied without activation");
    RESET();
    w->sides[1].positions[0].occupant = 4u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPANT_RANGE, "occupant range");
    RESET();
    w->sides[0].positions[0].occupant = 4u; /* member 4 exists but is not brought */
    expect_inv(&t, c1, w, DFI_INV_OCCUPANT_NOT_BROUGHT, "occupant not brought");
    RESET();
    w->sides[0].positions[0].activation_id = 5u;
    expect_inv(&t, c1, w, DFI_INV_ACTIVATION_NOT_ISSUED, "activation not issued");
    RESET();
    w->sides[0].positions[1].occupant = 2u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPANT_DUPLICATE, "occupant duplicate");
    RESET();
    /* Volatile block: ranges, paired fields, and the cleared empty position. */
    w->sides[0].positions[0].stages[6] = 13u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "stage 13");
    RESET();
    w->sides[0].positions[0].flags = 8u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "flags 8");
    RESET();
    w->sides[0].positions[0].stall_level = 7u;
    w->sides[0].positions[0].stall_turns = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "stall level 7");
    RESET();
    w->sides[0].positions[0].stall_level = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "stall level without turns");
    RESET();
    w->sides[0].positions[0].stall_turns = 2u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "stall turns without level");
    RESET();
    w->sides[0].positions[0].stall_level = 1u;
    w->sides[0].positions[0].stall_turns = 3u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "stall turns 3");
    RESET();
    w->sides[0].positions[0].confusion_turns = 6u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "confusion turns 6");
    RESET();
    w->sides[0].positions[0].charge_turns = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "charging without a locked move");
    RESET();
    w->sides[0].positions[0].locked_move = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "locked move without charging");
    RESET();
    w->sides[0].positions[0].charge_turns = 3u;
    w->sides[0].positions[0].locked_move = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "charge turns 3");
    RESET();
    w->sides[0].positions[1].charge_turns = 1u;
    w->sides[0].positions[1].locked_move = 2u; /* roster 0 has one move */
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "locked move beyond the move count");
    RESET();
    w->sides[0].positions[0].charge_turns = 1u;
    w->sides[0].positions[0].locked_move = 1u;
    w->sides[0].positions[0].locked_target = 4u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "locked target 4");
    RESET();
    w->sides[0].positions[0].locked_target = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "locked target without a locked move");
    RESET();
    w->sides[0].positions[0].switch_flag = 4u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "switch flag 4");
    RESET_TO(f2);
    w->sides[1].positions[1].switch_flag = (uint8_t)DFI_SWITCH_MOVE; /* s1b is empty in F2 */
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "empty position with a switch flag");
    RESET_TO(f2);
    w->sides[1].positions[1].stages[0] = 0u; /* s1b is empty in F2 */
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "empty position with a stage");
    RESET_TO(f2);
    w->sides[1].positions[1].move_actions = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "empty position with move actions");
    RESET();
    w->sides[0].requested_slots = 4u;
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "requested slots 4");
    RESET();
    w->sides[0].requested_slots = 1u; /* TURN: must equal the occupied mask */
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "requested slots != occupied at TURN");
    RESET_TO(g1);
    w->sides[1].requested_slots = 1u;
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "requested slots at TEAM_SELECTION");
    RESET_TO(f4);
    w->sides[0].requested_slots = 0u;
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "REPLACEMENT with no requested slot");
    RESET_TO(f2);
    w->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    w->request_epoch = 3u;
    w->sides[0].requested_slots = 1u;
    w->sides[1].requested_slots = 2u; /* s1b is empty in F2 */
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "REPLACEMENT slot on an empty position");
    RESET_TO(f5);
    w->sides[1].requested_slots = 1u; /* side 1 is not requested */
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "slots on an unrequested side");
    /* Switch flags mark exactly the requested slots of a PIVOT. */
    RESET();
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_MOVE;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "switch flag at TURN");
    RESET_TO(f4);
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "switch flag at REPLACEMENT");
    RESET_TO(f5);
    w->sides[0].positions[0].switch_flag = 0u;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "requested pivot slot without a flag");
    RESET_TO(f5);
    w->sides[0].positions[1].switch_flag = (uint8_t)DFI_SWITCH_MOVE;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "flag on an unrequested slot");
    RESET_TO(f5);
    w->sides[1].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "flag on the waiting side");
    RESET();
    w->sides[0].sealed = 2u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_RANGE, "sealed 2");
    RESET();
    w->sides[0].sealed = 1u; /* requested at TURN: nothing may be sealed */
    expect_inv(&t, c1, w, DFI_INV_SEALED_RULE, "sealed while requested at TURN");
    RESET();
    w->request_mask = 1u; /* re-prompt of side 0: side 1 must be sealed */
    w->sides[1].requested_slots = 0u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_RULE, "unsealed while waiting at TURN");
    RESET_TO(f4);
    w->sides[1].sealed = 1u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_RULE, "sealed at REPLACEMENT");
    RESET_TO(f5);
    w->sides[1].sealed = 1u; /* at a PIVOT the rest of the turn is in the queue */
    expect_inv(&t, c1, w, DFI_INV_SEALED_RULE, "sealed at PIVOT");
    RESET_TO(f6);
    w->sides[0].sealed = 1u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_RULE, "sealed while requested at PIVOT");
    RESET();
    w->sides[0].sealed_cmds[1].kind = (uint8_t)DFI_SLOT_MOVE;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "command while unsealed");
    RESET_TO(rp);
    w->sides[1].sealed_cmds[0].kind = 4u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed kind 4");
    RESET_TO(rp);
    w->sides[1].sealed_cmds[1].target = 4u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed move target 4");
    RESET_TO(rp);
    w->sides[1].sealed_cmds[0].reserve = 4u; /* side 1 has 4 members */
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed switch reserve out of range");
    RESET_TO(rp);
    w->sides[1].sealed_cmds[1] = (dfi_slot_cmd){DFI_SLOT_PASS, 0u, 0u, 1u, 0u};
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed pass with mega");
    RESET_TO(rp);
    w->sides[1].sealed_cmds[1] =
        (dfi_slot_cmd){DFI_SLOT_MOVE, DUOFORGE_MOVE_SLOT_STRUGGLE, DUOFORGE_TARGET_NONE, 0u, 0u};
    expect_ok(&t, c1, w, "sealed Struggle");
    w->sides[1].sealed_cmds[1].mega = 1u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed Struggle with mega");
    RESET();
    w->sides[1].positions[0].activation_id = 1u;
    expect_inv(&t, c1, w, DFI_INV_ACTIVATION_DUPLICATE, "activation duplicate");
    RESET();
    w->sides[0].seen_mask = 0x1Au; /* bit 4 >= side 1 member_count */
    expect_inv(&t, c1, w, DFI_INV_SEEN_MASK, "seen out of range");
    RESET();
    w->sides[1].seen_mask = 0x15u; /* side 0 member 4 exists but is not brought */
    expect_inv(&t, c1, w, DFI_INV_SEEN_MASK, "seen not brought");
    RESET();
    w->sides[0].seen_mask = 0x08u; /* side 1's active roster 1 no longer seen */
    expect_inv(&t, c1, w, DFI_INV_SEEN_MASK, "occupant not seen");
    RESET();
    /* Knowledge: nothing about the unseen, a possible display, and the
     * current display for an active member. */
    w->sides[0].knowledge[0].hp_percent = 100u; /* s1 member 0 is unseen */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "HP of an unseen member");
    RESET();
    w->sides[0].knowledge[2].moves_used[0] = 1u;
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "move use of an unseen member");
    RESET();
    w->sides[0].knowledge[2].revealed = (uint8_t)DFI_REVEALED_MEGA;
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "revealed fact of an unseen member");
    RESET();
    w->sides[0].knowledge[1].revealed = (uint8_t)DFI_REVEALED_ITEM_CONSUMED; /* nothing was consumed */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "revealed item consumption that did not happen");
    RESET();
    w->sides[0].knowledge[1].revealed = (uint8_t)DFI_REVEALED_MEGA; /* no Mega forme */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "revealed Mega that did not happen");
    RESET();
    w->sides[0].knowledge[1].revealed = 4u;
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "revealed 4");
    RESET();
    w->sides[1].knowledge[0].moves_used[1] = 1u; /* s0 member 0 has one move */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "use of a move the member does not have");
    RESET();
    w->sides[0].knowledge[1].hp_percent = 99u; /* s1 member 1 is active at full HP */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "stale display of an active member");
    RESET();
    w->sides[1].members[1].hp = 100u; /* 49 percent of 201, not refreshed */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "HP change of an active member without the display");
    RESET_TO(f2);
    w->sides[1].knowledge[2].hp_percent = 101u; /* s0 member 2 is on the bench */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "display above 100 percent");
    RESET_TO(f2);
    w->sides[1].knowledge[2].hp_flag = (uint8_t)DUOFORGE_HP_FLAG_GREEN; /* 20 percent is red or yellow */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "impossible flag at 20 percent");
    RESET_TO(f2);
    w->sides[1].knowledge[2].hp_percent = 21u; /* a flag exists only at 20 and 50 */
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "flag away from 20 and 50 percent");
    RESET_TO(f2);
    w->sides[0].members[2].hp = 1u; /* the bench changes unseen: still valid */
    expect_ok(&t, c1, w, "benched member differs from the last display");
    RESET();
    /* Queue: present exactly at PIVOT, canonical tail, per-kind operands. */
    w->queue_len = 1u;
    w->queue[0] = (dfi_queue_record){.kind = DFI_Q_RESIDUAL};
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "queue outside PIVOT");
    RESET();
    w->queue[11].target = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "unused record not zero");
    RESET_TO(f5);
    w->queue_len = 0u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "PIVOT with an empty queue");
    RESET_TO(f5);
    w->queue_len = 13u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "queue length 13");
    RESET_TO(f5);
    w->queue[0].kind = 7u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "record kind 7");
    RESET_TO(f5);
    w->queue[0].side = 2u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "record side 2");
    RESET_TO(f5);
    w->queue[0].slot = 2u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "record slot 2");
    RESET_TO(f5);
    w->queue[0].move_slot = 6u; /* 5 is the recharge turn since step G17 */
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "move slot 6");
    RESET_TO(f5);
    w->queue[0].target = 4u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "move target 4");
    RESET_TO(f5);
    w->queue[0].reserve = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "move with a reserve");
    RESET_TO(f5);
    w->queue[0].activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "move without a binding");
    RESET_TO(f5);
    w->queue[0].activation_id = 5u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "move bound to an id not issued");
    RESET_TO(f5);
    w->queue[2].slot = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "residual with an operand");
    RESET_TO(f6);
    w->queue[0].reserve = 6u; /* SWITCH_IN of side 0, which has 6 members */
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "switch-in reserve out of range");
    RESET_TO(f6);
    w->queue[0].activation_id = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "switch-in with a binding");
    RESET_TO(f6);
    w->queue[1].reserve = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "run-switch with a reserve");
    RESET_TO(f6);
    w->queue[2].reserve = 4u; /* SWITCH of side 1, which has 4 members */
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "switch reserve out of range");
    RESET_TO(f6);
    w->queue[3].move_slot = 1u;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "Mega with a move slot");
    RESET();

    /* Hostile counts are range-checked before use as index or shift. */
    w->sides[0].member_count = 0xFFu;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_COUNT, "member_count 0xFF");
    RESET();
    w->sides[1].members[1].move_count = 0xFFu;
    expect_inv(&t, c1, w, DFI_INV_MOVE_COUNT, "move_count 0xFF");
    RESET();
    w->sides[0].positions[1].occupant = 0xFEu;
    expect_inv(&t, c1, w, DFI_INV_OCCUPANT_RANGE, "occupant 0xFE");
    RESET();
    w->sides[0].brought_order[0] = 0xFEu;
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_ORDER, "order entry 0xFE");
    RESET();
    w->sides[0].seen_mask = 0xFFu;
    expect_inv(&t, c1, w, DFI_INV_SEEN_MASK, "seen 0xFF");
    RESET();
    w->queue_len = 0xFFu;
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "queue length 0xFF");
    RESET_TO(f5);
    w->queue[0].side = 0xFFu; /* before it indexes a side */
    expect_inv(&t, c1, w, DFI_INV_QUEUE, "record side 0xFF");
    RESET();
    w->sides[0].positions[0].locked_move = 0xFFu;
    w->sides[0].positions[0].charge_turns = 1u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "locked move 0xFF");
    RESET();

    /* Two simultaneous faults report the first in check order. */
    w->sides[1].positions[0].activation_id = 1u;  /* ACTIVATION_DUPLICATE (late) */
    w->sides[0].members[3].species_id = 99u;     /* SPECIES_RANGE (earlier) */
    expect_inv(&t, c1, w, DFI_INV_SPECIES_RANGE, "two faults");
    RESET();
    w->rng.inc = 2u;
    w->next_activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_RNG_INC_EVEN, "rng before next");
    RESET();
    w->boundary_kind = 0u;
    w->request_epoch = 0u;
    w->request_mask = 0u;
    expect_inv(&t, c1, w, DFI_INV_BOUNDARY_KIND, "boundary before epoch and mask");
    RESET();
    /* A fingerprint mismatch is reported before any invariant violation. */
    w->context_fingerprint[0] ^= 1u;
    w->rng.inc = 2u;
    w->sides[0].member_count = 0u;
    expect_inv(&t, c1, w, DFI_INV_CONTEXT_FINGERPRINT, "context before invariants");
    w->context_fingerprint[0] ^= 1u;
    RESET();
    /* Side 0 is checked completely before side 1. */
    w->sides[1].member_count = 7u;
    w->sides[0].positions[1].activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPIED_WITHOUT_ACTIVATION, "side 0 before side 1");
    RESET();
    /* Members before the brought mask, the mask before positions, positions
     * before request slots, side checks before the knowledge check. */
    w->sides[0].brought_mask = 0x07u;
    w->sides[0].members[5].moves[0].pp = 30u;
    expect_inv(&t, c1, w, DFI_INV_PP_ABOVE_MAX, "members before mask");
    RESET();
    w->sides[0].brought_mask = 0x07u;
    w->sides[0].positions[0].activation_id = 9u;
    expect_inv(&t, c1, w, DFI_INV_BROUGHT_COUNT, "mask before positions");
    RESET();
    w->sides[0].requested_slots = 4u;
    w->sides[0].positions[0].activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPIED_WITHOUT_ACTIVATION, "positions before requested slots");
    RESET();
    w->sides[0].seen_mask = 0x08u;
    w->sides[1].positions[0].activation_id = 1u;
    expect_inv(&t, c1, w, DFI_INV_ACTIVATION_DUPLICATE, "activation duplicate before seen");
    RESET();
    /* The v3 ids in their place: header fields before the sides, the side
     * conditions before the positions, the volatile block between the
     * occupants and the request slots, knowledge after the seen masks, the
     * queue last. */
    w->turn = 0u;
    w->result = 1u;
    w->weather = 3u;
    expect_inv(&t, c1, w, DFI_INV_TURN_COUNTER, "turn before result and field");
    RESET();
    w->result = 1u;
    w->weather = 3u;
    expect_inv(&t, c1, w, DFI_INV_RESULT, "result before field");
    RESET();
    w->weather = 3u;
    w->sides[0].member_count = 7u;
    expect_inv(&t, c1, w, DFI_INV_FIELD, "field before the sides");
    RESET();
    w->sides[0].members[0].ability = 1u;
    w->sides[0].members[1].species_id = 99u;
    expect_inv(&t, c1, w, DFI_INV_MEMBER_EXTRA, "member 0 completely before member 1");
    RESET();
    w->sides[0].tailwind_turns = 5u;
    w->sides[0].positions[0].activation_id = 0u;
    expect_inv(&t, c1, w, DFI_INV_SIDE_CONDITION, "side conditions before positions");
    RESET();
    w->sides[0].positions[0].flags = 8u;
    w->sides[0].positions[1].occupant = 2u;
    expect_inv(&t, c1, w, DFI_INV_OCCUPANT_DUPLICATE, "occupants before the volatile block");
    RESET();
    w->sides[0].positions[0].flags = 8u;
    w->sides[0].requested_slots = 4u;
    expect_inv(&t, c1, w, DFI_INV_VOLATILE, "volatile block before request slots");
    RESET();
    w->sides[0].requested_slots = 4u;
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_MOVE;
    expect_inv(&t, c1, w, DFI_INV_REQUESTED_SLOTS, "request slots before switch flags");
    RESET();
    w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_MOVE;
    w->sides[0].sealed = 2u;
    expect_inv(&t, c1, w, DFI_INV_SWITCH_FLAG, "switch flags before the sealed record");
    RESET();
    w->sides[0].knowledge[0].hp_percent = 1u;
    w->sides[0].seen_mask = 0x1Au;
    expect_inv(&t, c1, w, DFI_INV_SEEN_MASK, "seen mask before knowledge");
    RESET();
    w->sides[0].knowledge[0].hp_percent = 1u;
    w->queue_len = 1u;
    expect_inv(&t, c1, w, DFI_INV_KNOWLEDGE, "knowledge before the queue");
    RESET();

    /* Checking a C1 battle under C2 is a context mismatch. */
    DF_CHECK(&t, dfi_state_check(c2, f1, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);

    /* The checker does not mutate. */
    {
        w->sides[0].members[3].species_id = 99u;
        uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE] = {0};
        uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE] = {0};
        (void)dfi_encode_unchecked(c1, w, before);
        (void)dfi_state_check(c1, w, NULL);
        (void)duoforge_battle_check(c1, w);
        (void)dfi_encode_unchecked(c1, w, after);
        DF_CHECK_BYTES(&t, after, before, sizeof after, "checker purity");
        RESET();
    }
    /* Names cover every id; the count is pinned. */
    for (unsigned i = 0; i < (unsigned)DFI_INV_COUNT; ++i) {
        DF_CHECK(&t, strcmp(dfi_invariant_name((dfi_invariant)i), "UNKNOWN") != 0);
    }
    /* 43 before the POOL tail (decision 0015 section 7), then TAIL_KIND, _SIDE, _POSITION, _MEMBER, _SCHEMA,
     * _RESERVED and (rev 2) _FIELD; test_pool_tail.c checks each of the seven. */
    DF_CHECK_EQ_U64(&t, (unsigned)DFI_INV_COUNT, 51u); /* step G46: TAIL_PARTY */
#undef RESET
#undef RESET_TO

    duoforge_battle_destroy(w);
    duoforge_battle_destroy(rp);
    duoforge_battle_destroy(g1);
    duoforge_battle_destroy(f1);
    duoforge_battle_destroy(f2);
    duoforge_battle_destroy(f4);
    duoforge_battle_destroy(f5);
    duoforge_battle_destroy(f6);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c2);
    duoforge_context_destroy(c3);
    duoforge_context_destroy(c4);
    return df_test_end(&t);
}
