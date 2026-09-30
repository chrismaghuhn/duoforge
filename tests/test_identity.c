/*
 * T8 duoforge.state.identity (white-box): positions, members, activation
 * bindings, stale-binding regression (a replacement or re-entry never
 * inherits an old binding), primitive failure atomicity, corrupt-count
 * safety (runs under ASan/UBSan) and activation-id exhaustion.
 * Expectations: the identity contract (docs/decisions/0002).
 */
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "state/identity.h"
#include "support/check.h"
#include "support/fixtures.h"

static const dfi_position_id S0A = {0, 0};
static const dfi_position_id S0B = {0, 1};
static const dfi_position_id S1A = {1, 0};
static const dfi_position_id S1B = {1, 1};

static void encode_raw(const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V1_ENCODED_SIZE])
{
    memset(out, 0, DUOFORGE_STATE_V1_ENCODED_SIZE);
    dfi_encode_unchecked(b, out);
}

/* Runs a failing place and checks: expected status, no mutation, out untouched. */
static void place_fails(df_test *t, duoforge_battle *b, dfi_position_id p, uint8_t roster,
                        duoforge_status expected, const char *what)
{
    uint8_t before[DUOFORGE_STATE_V1_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V1_ENCODED_SIZE];
    encode_raw(b, before);
    dfi_binding out = {{0xEEu, 0xEEu}, 0xDEADBEEFu};
    const duoforge_status st = dfi_place(b, p, roster, &out);
    encode_raw(b, after);
    if (!DF_CHECK(t, st == expected)) {
        fprintf(stderr, "  case: %s (status %s)\n", what, duoforge_status_name(st));
    }
    DF_CHECK_BYTES(t, after, before, sizeof after, what);
    DF_CHECK(t, out.position.side == 0xEEu && out.position.slot == 0xEEu && out.activation_id == 0xDEADBEEFu);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.identity");

    /* Position validity and flat index. */
    unsigned valid = 0;
    for (uint8_t side = 0; side < 4; ++side) {
        for (uint8_t slot = 0; slot < 4; ++slot) {
            const dfi_position_id p = {side, slot};
            if (dfi_position_valid(p)) {
                ++valid;
                DF_CHECK_EQ_U64(&t, dfi_position_flat(p), (uint64_t)side * 2u + slot);
            }
        }
    }
    DF_CHECK_EQ_U64(&t, valid, 4u);
    DF_CHECK_EQ_U64(&t, dfi_position_flat(S0A), 0u); /* p1a */
    DF_CHECK_EQ_U64(&t, dfi_position_flat(S0B), 1u); /* p1b */
    DF_CHECK_EQ_U64(&t, dfi_position_flat(S1A), 2u); /* p2a */
    DF_CHECK_EQ_U64(&t, dfi_position_flat(S1B), 3u); /* p2b */

    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_battle_setup f1;
    df_setup_f1(&f1);
    duoforge_battle *b = df_make_battle(c1, &f1);

    /* Member validity (F1: side 0 has 6 members, side 1 has 4). */
    DF_CHECK(&t, dfi_member_valid(b, (dfi_member_id){0, 5}));
    DF_CHECK(&t, !dfi_member_valid(b, (dfi_member_id){0, 6}));
    DF_CHECK(&t, dfi_member_valid(b, (dfi_member_id){1, 3}));
    DF_CHECK(&t, !dfi_member_valid(b, (dfi_member_id){1, 4}));
    DF_CHECK(&t, !dfi_member_valid(b, (dfi_member_id){2, 0}));

    /* F1 bindings: activations 1..4, all current. */
    const dfi_position_id all[4] = {S0A, S0B, S1A, S1B};
    for (unsigned i = 0; i < 4; ++i) {
        dfi_binding x = {{0, 0}, 0};
        DF_CHECK(&t, dfi_current_binding(b, all[i], &x) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, x.activation_id, i + 1u);
        DF_CHECK(&t, dfi_binding_is_current(b, x));
    }

    /* Vacate s0a: the old binding goes stale; the empty slot has activation 0. */
    const dfi_binding old1 = {S0A, 1u};
    DF_CHECK(&t, dfi_vacate(b, S0A) == DUOFORGE_OK);
    DF_CHECK(&t, !dfi_binding_is_current(b, old1));
    {
        dfi_binding x = {{9, 9}, 9};
        DF_CHECK(&t, dfi_current_binding(b, S0A, &x) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, x.activation_id, 0u);
        DF_CHECK(&t, !dfi_binding_is_current(b, x));
    }
    DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);

    /* Replacement: roster 3 into s0a gets activation 5. */
    dfi_binding bind5 = {{0, 0}, 0};
    DF_CHECK(&t, dfi_place(b, S0A, 3u, &bind5) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(&t, bind5.activation_id, 5u);
    DF_CHECK_EQ_U64(&t, b->next_activation_id, 6u);
    DF_CHECK(&t, !dfi_binding_is_current(b, old1));
    DF_CHECK(&t, dfi_binding_is_current(b, bind5));
    DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);

    /* Re-entry of the original member gets a fresh id; both old bindings stale. */
    DF_CHECK(&t, dfi_vacate(b, S0A) == DUOFORGE_OK);
    dfi_binding bind6 = {{0, 0}, 0};
    DF_CHECK(&t, dfi_place(b, S0A, 2u, &bind6) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(&t, bind6.activation_id, 6u);
    DF_CHECK(&t, !dfi_binding_is_current(b, old1));
    DF_CHECK(&t, !dfi_binding_is_current(b, bind5));
    DF_CHECK(&t, dfi_binding_is_current(b, bind6));
    DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
    /* A binding for another position with the same id is not current. */
    DF_CHECK(&t, !dfi_binding_is_current(b, (dfi_binding){S0B, 6u}));
    DF_CHECK(&t, !dfi_binding_is_current(b, (dfi_binding){{2, 0}, 6u}));

    /* Failing primitives: E_INVARIANT, no mutation, outputs untouched. */
    place_fails(&t, b, S0A, 3u, DUOFORGE_E_INVARIANT, "place into occupied slot");
    DF_CHECK(&t, dfi_vacate(b, S1B) == DUOFORGE_OK); /* s1b empty now; roster 1 active in s1a */
    place_fails(&t, b, S1B, 1u, DUOFORGE_E_INVARIANT, "member active in other slot");
    place_fails(&t, b, S1B, 4u, DUOFORGE_E_INVARIANT, "roster >= member_count");
    DF_CHECK(&t, dfi_vacate(b, S0B) == DUOFORGE_OK);
    place_fails(&t, b, S0B, 4u, DUOFORGE_E_INVARIANT, "non-brought member");
    place_fails(&t, b, (dfi_position_id){0, 2}, 1u, DUOFORGE_E_INVARIANT, "slot 2");
    place_fails(&t, b, (dfi_position_id){2, 0}, 1u, DUOFORGE_E_INVARIANT, "side 2");
    {
        uint8_t before[DUOFORGE_STATE_V1_ENCODED_SIZE];
        uint8_t after[DUOFORGE_STATE_V1_ENCODED_SIZE];
        encode_raw(b, before);
        DF_CHECK(&t, dfi_vacate(b, S0B) == DUOFORGE_E_INVARIANT); /* already empty */
        DF_CHECK(&t, dfi_vacate(b, (dfi_position_id){0, 2}) == DUOFORGE_E_INVARIANT);
        dfi_binding x = {{7, 7}, 77u};
        DF_CHECK(&t, dfi_current_binding(b, (dfi_position_id){0, 2}, &x) == DUOFORGE_E_INVARIANT);
        DF_CHECK(&t, x.position.side == 7u && x.position.slot == 7u && x.activation_id == 77u);
        encode_raw(b, after);
        DF_CHECK_BYTES(&t, after, before, sizeof after, "vacate/current failures");
    }
    DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);

    /* Corrupt-count safety: member_count 0xFF must not index or shift out of range. */
    {
        duoforge_battle *c = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, b, &c) == DUOFORGE_OK);
        c->sides[0].member_count = 0xFFu;
        place_fails(&t, c, S0B, 7u, DUOFORGE_E_INVARIANT, "corrupt count, roster 7");
        place_fails(&t, c, S0B, 200u, DUOFORGE_E_INVARIANT, "corrupt count, roster 200");
        DF_CHECK(&t, !dfi_member_valid(c, (dfi_member_id){0, 7}));
        duoforge_battle_destroy(c);
    }

    /* Activation-id exhaustion. */
    {
        b->next_activation_id = UINT32_MAX - 1u;
        dfi_binding x = {{0, 0}, 0};
        DF_CHECK(&t, dfi_place(b, S1B, 3u, &x) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(&t, x.activation_id, UINT32_MAX - 1u);
        DF_CHECK_EQ_U64(&t, b->next_activation_id, UINT32_MAX);
        DF_CHECK(&t, dfi_vacate(b, S1A) == DUOFORGE_OK);
        place_fails(&t, b, S1A, 1u, DUOFORGE_E_EXHAUSTED, "activation ids exhausted");
        /* A zero counter (corrupt) is an invariant violation, not success. */
        b->next_activation_id = 0u;
        place_fails(&t, b, S1A, 1u, DUOFORGE_E_INVARIANT, "zero activation counter");
    }

    duoforge_battle_destroy(b);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
