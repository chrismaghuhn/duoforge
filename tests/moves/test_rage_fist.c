/*
 * duoforge.moves.rage_fist (white-box): step G48 of the content expansion, Rage Fist's bound and power: six hits taken is the
 * largest valid value and a seventh is refused by the invariants; the power is 50 + 50 per hit, so the damage of
 * g48_rage_fist_a's Annihilape with 0, 1, 5 and 6 hits taken grows with 50, 100, 300 and 350 (the cap at six hits, which no
 * recorded battle reaches).
 *
 * Split by subject from the test of step G48 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "combat/moves/multiaccuracy.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The invariant of the field: six hits is the largest value (Rage Fist is at its cap then), a seventh is refused. */
static void check_bound(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g48_rage_fist_a");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    /* the team selection first: a position holds a tail only with a standing occupant (TAIL_POSITION) */
    duoforge_decision_bundle bd;
    df_conf_bundle_of(&cb->steps[0], b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[0].tape_off], cb->steps[0].tape_len, &used, &res) ==
                          DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return;
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    b->tail.sides[0].positions[0].hits_taken = 6u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    b->tail.sides[0].positions[0].hits_taken = 7u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    duoforge_battle_destroy(b);
}

/* Rage Fist's power by the hits (the cap 350 is reached at six hits, and no recorded battle gets there): Annihilape with `hits`
 * taken uses Rage Fist on the foe in slot 0 (Kingambit, Dark and Steel: x0.5), and the others protect. The battle's own draws
 * are the same for every `hits` (the seed is the same and the power draws nothing), so the damage dealt grows with the power:
 * 50, 100, 300 and 350 for 0, 1, 5 and 6 hits. Returns the HP the foe lost. */
static uint32_t rage_fist_dealt(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t hits)
{
    duoforge_battle_setup setup;
    df_conf_build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return 0u;
    }
    duoforge_decision_bundle bd;
    df_conf_bundle_of(&cb->steps[0], b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[0].tape_off], cb->steps[0].tape_len, &used, &res) ==
                          DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return 0u;
    }
    b->tail.sides[0].positions[0].hits_taken = (uint8_t)hits;
    const uint32_t before = b->sides[1].members[0].hp;
    /* the recorded first turn of the battle (its choices are valid by construction; the foe's Iron Head hits Annihilape after
     * its Rage Fist, which is the one that is measured here) */
    duoforge_decision_bundle turn;
    df_conf_bundle_of(&cb->steps[1], b, &turn);
    duoforge_step_result turn_res;
    const duoforge_status turn_st = duoforge_battle_step(ctx, b, &turn, &turn_res);
    if (!DF_CHECK(t, turn_st == DUOFORGE_OK)) {
        fprintf(stderr, "  rage fist turn with %u hits: %s\n", hits, duoforge_status_name(turn_st));
        duoforge_battle_destroy(b);
        return 0u;
    }
    const uint32_t after = b->sides[1].members[0].hp;
    duoforge_battle_destroy(b);
    return after <= before ? before - after : 0u;
}

static void check_power(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = df_conf_find("g48_rage_fist_a");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    const uint32_t d0 = rage_fist_dealt(t, ctx, cb, 0u);
    const uint32_t d1 = rage_fist_dealt(t, ctx, cb, 1u);
    const uint32_t d5 = rage_fist_dealt(t, ctx, cb, 5u);
    const uint32_t d6 = rage_fist_dealt(t, ctx, cb, 6u);
    fprintf(stderr, "  rage fist dealt: 0 hits %u, 1 hit %u, 5 hits %u, 6 hits %u\n", d0, d1, d5, d6);
    DF_CHECK(t, d0 > 0u);
    DF_CHECK(t, d0 < d1 && d1 < d5 && d5 < d6);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.rage_fist");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_bound(&t, ctx);
    check_power(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
