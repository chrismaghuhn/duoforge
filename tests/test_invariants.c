/*
 * T9 duoforge.state.invariants (white-box): one targeted corruption per
 * invariant id v2 on an F1 copy (the exact first-violation id is asserted),
 * allowed structural states (every fixture, including REPLACEMENT and PIVOT
 * boundaries that no mechanic produces yet), range-before-use on hostile
 * counts (runs under ASan/UBSan), first-violation order and checker purity.
 * Expectations: the invariant contract (docs/decisions/0002, 0005).
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "state/invariants.h"
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
    expect_ok(&t, c1, f5, "F5 (one-side PIVOT, sealed)");
    expect_ok(&t, c1, f6, "F6 (two-side PIVOT)");
    {
        duoforge_battle *g3 = df_make_g3(c3);
        duoforge_battle *f3 = df_make_f3(c3);
        duoforge_battle *others[6] = {df_make_g7(c4),  df_make_f8(c4),  df_make_f9(c4),
                                      df_make_f10(c4), df_make_f11(c4), df_make_f12(c4)};
        expect_ok(&t, c3, g3, "G3");
        expect_ok(&t, c3, f3, "F3");
        for (unsigned i = 0; i < 6; ++i) {
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
    expect_ok(&t, c1, w, "fainted occupant");
    RESET();
    w->sides[0].members[5].hp = 0u; /* fainted reserve */
    expect_ok(&t, c1, w, "fainted reserve");
    RESET();
    w->sides[1].members[0].moves[0].pp = 0u;
    expect_ok(&t, c1, w, "pp 0");
    RESET();
    w->sides[1].positions[0] = (dfi_active_slot){0u, DFI_OCCUPANT_NONE};
    w->sides[1].positions[1] = (dfi_active_slot){0u, DFI_OCCUPANT_NONE};
    w->sides[1].requested_slots = 0u;
    expect_ok(&t, c1, w, "both slots of a side empty");
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
    w->boundary_kind = 5u;
    expect_inv(&t, c1, w, DFI_INV_BOUNDARY_KIND, "boundary 5");
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
    w->sides[1].members[4].hp = 1u;
    expect_inv(&t, c1, w, DFI_INV_UNUSED_MEMBER_NONZERO, "unused member");
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
    RESET();
    w->sides[0].sealed_cmds[1].kind = (uint8_t)DFI_SLOT_MOVE;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "command while unsealed");
    RESET_TO(f5);
    w->sides[0].sealed_cmds[0].kind = 4u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed kind 4");
    RESET_TO(f5);
    w->sides[0].sealed_cmds[0].target = 4u;
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed move target 4");
    RESET_TO(f5);
    w->sides[1].sealed_cmds[0].reserve = 4u; /* side 1 has 4 members */
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed switch reserve out of range");
    RESET_TO(f5);
    w->sides[0].sealed_cmds[1] = (dfi_slot_cmd){DFI_SLOT_PASS, 0u, 0u, 1u, 0u};
    expect_inv(&t, c1, w, DFI_INV_SEALED_COMMAND, "sealed pass with mega");
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

    /* Checking a C1 battle under C2 is a context mismatch. */
    DF_CHECK(&t, dfi_state_check(c2, f1, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);

    /* The checker does not mutate. */
    {
        w->sides[0].members[3].species_id = 99u;
        uint8_t before[DUOFORGE_STATE_V2_ENCODED_SIZE] = {0};
        uint8_t after[DUOFORGE_STATE_V2_ENCODED_SIZE] = {0};
        dfi_encode_unchecked(w, before);
        (void)dfi_state_check(c1, w, NULL);
        (void)duoforge_battle_check(c1, w);
        dfi_encode_unchecked(w, after);
        DF_CHECK_BYTES(&t, after, before, sizeof after, "checker purity");
        RESET();
    }
    /* Names cover every id; the count is pinned. */
    for (unsigned i = 0; i < (unsigned)DFI_INV_COUNT; ++i) {
        DF_CHECK(&t, strcmp(dfi_invariant_name((dfi_invariant)i), "UNKNOWN") != 0);
    }
    DF_CHECK_EQ_U64(&t, (unsigned)DFI_INV_COUNT, 34u);
#undef RESET
#undef RESET_TO

    duoforge_battle_destroy(w);
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
