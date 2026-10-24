/*
 * duoforge.interactions.leaf_guard_mega_sol_refusal (white-box): step G83 of the content expansion (decision 0015 entry 5bt),
 * Mega Sol and Leaf Guard, reached through Trace: Gardevoir (Trace, not Grass) copies Leaf Guard from the Meganium foe, and a
 * Mega Meganium (Mega Sol) uses Poison Powder on her in no sun. The pin's Leaf Guard reads Pokemon#effectiveWeather of the
 * target, which is sun for the user's move (sim/pokemon.ts:2193), and refuses the poison; the engine does not model that, so
 * over 16 seeds the step returns DUOFORGE_E_UNSUPPORTED in some of them (Poison Powder's 75% accuracy, and Trace copies only
 * when Meganium is on the field first). The control, the same battle with no Mega evolution, plays every seed with no refusal.
 *
 * Split by subject from the test of step G83 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* Mega Sol and Leaf Guard (step G83, decision 0015 5bt), reached through Trace. Gardevoir (Trace, not Grass) copies Leaf Guard
 * from the Meganium foe at its start. A Mega Meganium (Mega Sol) uses Poison Powder on her in no sun: the pin's Leaf Guard reads
 * Pokemon#effectiveWeather of the target, which is sun for the user's move (sim/pokemon.ts:2193), and refuses the poison. Poison
 * Powder has 75% accuracy, and Trace copies only when Meganium is on the field before Gardevoir: over 16 seeds the step must return
 * DUOFORGE_E_UNSUPPORTED in some of them. The control is the same battle with no Mega evolution: every seed plays, no refusal.
 * Setup: the recorded battle g83_bulletproof_bullets (its weather is rain from Politoed, who is on the bench); side 0 member 0
 * is Meganium (Leaf Guard, Meganiumite), side 1 member 0 is Gardevoir (female, Trace, Protect). */
static duoforge_status run_poison_powder(df_test *t, const duoforge_context *ctx, const df_conf_battle *base,
                                         uint64_t seed, bool mega)
{
    static df_conf_member mem[2][6];
    df_conf_battle cb = *base;
    memcpy(mem, base->members, sizeof mem);
    cb.members = (const df_conf_member (*)[6])mem;
    mem[0][0].species = DFI_FORME_MEGANIUM;
    mem[0][0].item = DFI_ITEM_MEGANIUMITE + 1u; /* the setup stores an ability and an item as its id + 1 (0 is none), as the recorded members */
    mem[0][0].ability = DFI_ABILITY_LEAFGUARD + 1u;
    mem[0][0].moves[0] = DFI_MOVE_POISONPOWDER;
    mem[0][0].moves[2] = DFI_MOVE_ENERGYBALL; /* Meganium learns no Focus Blast: the recorded Chesnaught's third move */
    mem[1][0].species = DFI_FORME_GARDEVOIR;
    mem[1][0].gender = DUOFORGE_GENDER_FEMALE;
    mem[1][0].ability = DFI_ABILITY_TRACE + 1u;
    mem[1][0].item = DFI_ITEM_LIFEORB + 1u;
    mem[1][0].move_count = 1u;
    /* Trace copies from a foe already on the field: Meganium (base Speed 80) enters before Gardevoir (base 60, no Speed points) */
    mem[1][0].sp[0] = 32u; mem[1][0].sp[1] = 0u; mem[1][0].sp[2] = 0u; mem[1][0].sp[3] = 32u; mem[1][0].sp[4] = 2u; mem[1][0].sp[5] = 0u;
    mem[1][0].moves[0] = DFI_MOVE_PSYCHIC; /* not Protect: a protecting target would block the Poison Powder before the status */
    mem[1][0].moves[1] = 0u; /* slots beyond move_count are zero: the recorded Gengar's moves are dropped */
    mem[1][0].moves[2] = 0u;
    mem[1][0].moves[3] = 0u;
    duoforge_battle_setup setup;
    df_conf_build_setup(&cb, &setup);
    setup.rng_initstate = seed;
    duoforge_battle *b = NULL;
    const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
    if (!DF_CHECK(t, created == DUOFORGE_OK && b != NULL)) {
        fprintf(stderr, "  poison powder setup: the battle is rejected: %s\n", duoforge_status_name(created));
        return created;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    df_conf_bundle_of(&cb.steps[0], b, &bd);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    df_conf_step st1 = cb.steps[1];
    /* side 0 slot 0 (Meganium, flat 0): Poison Powder on flat 2 (Gardevoir) */
    st1.cmds[0][0].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[0][0].move_slot = 0u;
    st1.cmds[0][0].target = 2u;
    st1.cmds[0][0].mega = mega ? 1u : 0u;
    /* side 0 slot 1 (Garchomp): the recorded command; side 1: Gardevoir and the Meganium foe protect */
    st1.cmds[1][0].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[1][0].move_slot = 0u;
    st1.cmds[1][0].target = 1u; /* Psychic on flat 1 (Garchomp) */
    st1.cmds[1][0].mega = 0u;
    st1.cmds[1][1].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[1][1].move_slot = 3u;
    st1.cmds[1][1].target = DUOFORGE_TARGET_NONE;
    st1.cmds[1][1].mega = 0u;
    df_conf_bundle_of(&st1, b, &bd);
    const duoforge_status status = duoforge_battle_step(ctx, b, &bd, &res);
    duoforge_battle_destroy(b);
    return status;
}

static void check_mega_sol_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *base = df_conf_find("g83_bulletproof_bullets");
    if (!DF_CHECK(t, base != NULL)) {
        return;
    }
    int refused = 0;
    for (uint64_t seed = 1; seed <= 16; ++seed) {
        const duoforge_status status = run_poison_powder(t, ctx, base, seed, true);
        if (status == DUOFORGE_E_UNSUPPORTED) {
            refused += 1;
        } else {
            if (status != DUOFORGE_OK) { fprintf(stderr, "  mega seed %u: the step returned %s\n", (unsigned)seed, duoforge_status_name(status)); }
            DF_CHECK(t, status == DUOFORGE_OK);
        }
    }
    DF_CHECK(t, refused >= 1); /* the poison hits in some seeds, and then the Mega Sol refusal is the answer */
    for (uint64_t seed = 1; seed <= 16; ++seed) {
        const duoforge_status status = run_poison_powder(t, ctx, base, seed, false); /* the control: no Mega Sol */
        DF_CHECK(t, status == DUOFORGE_OK);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.interactions.leaf_guard_mega_sol_refusal");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_mega_sol_refusal(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
