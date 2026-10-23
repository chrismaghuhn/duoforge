/*
 * duoforge.moves.hits_taken_hazard_moves (white-box): step G48 of the content expansion, the moves that use the tail's rev 4
 * fields that already exist, as one batch: Rage Fist (the position's hits_taken), Stone Axe and Ceaseless Edge (a hazard on the
 * foe's side after a hit, the G37 add: Stealth Rock, one Spikes layer) and Population Bomb (ten hits, multiaccuracy; its
 * accuracy 90 is covered by the later-hit proof of G33). Their marks, handler numbers and pinned numbers; and, after every step
 * of the recorded g48_* battles replayed with the reference's draws, the hits each position has taken since it came in (one per
 * damaging hit, saturating at 6, cleared when the occupant leaves) and the hazard layers of each side, against rows derived
 * from the committed traces. The reference's own lines are compared by duoforge.reference.conformance_pool_data.
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

static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_RAGEFIST] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_STONEAXE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_CEASELESSEDGE] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_POPULATIONBOMB] != 0u);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_QUICKGUARD] != 0u); /* marked by step G54 (decision 0029), not by this step */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RAGEFIST].special, DFI_SPECIAL_RAGE_FIST);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STONEAXE].special, DFI_SPECIAL_STONE_AXE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CEASELESSEDGE].special, DFI_SPECIAL_CEASELESS_EDGE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].special, DFI_SPECIAL_MULTI_HIT_10);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_QUICKGUARD].special, DFI_SPECIAL_QUICK_GUARD); /* step G54 */
    /* Population Bomb: ten hits, and the accuracy 90 that the later-hit proof covers (combat/moves/multiaccuracy.h) */
    DF_CHECK(t, dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][0] == 10u && dfi_pool_move_static_hits[DFI_MOVE_POPULATIONBOMB][1] == 10u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].accuracy, 90u);
    DF_CHECK(t, dfi_multiaccuracy_proven(dfi_pool_moves[DFI_MOVE_POPULATIONBOMB].accuracy));
    /* Rage Fist: power 50 at no hit, 350 from six hits on (the bound of the field) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_RAGEFIST].base_power, 50u);
    DF_CHECK_EQ_U64(t, DFI_TAIL_HITS_TAKEN_MAX, 6u);
    /* The hazard kinds of the two moves are the ones of G37 */
    DF_CHECK_EQ_U64(t, DUOFORGE_SIDE_STEALTH_ROCK, 5u);
    DF_CHECK_EQ_U64(t, DUOFORGE_SIDE_SPIKES, 6u);
}

/* The hits taken of each position and the hazard layers of each side after each step (see the header). */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t hits[4];
    uint32_t stealth[2];
    uint32_t spikes[2];
} rows[] = {
    {"g48_rage_fist_a", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_a", 1u, {1u, 0u, 1u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_a", 2u, {2u, 0u, 2u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_switch", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_switch", 1u, {1u, 0u, 1u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_switch", 2u, {1u, 0u, 1u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_rage_fist_switch", 3u, {0u, 0u, 1u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_stone_axe_rock", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_stone_axe_rock", 1u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_rock", 2u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_rock", 3u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_rock", 4u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_miss", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_stone_axe_miss", 1u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_stone_axe_miss", 2u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_miss", 3u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_stone_axe_miss", 4u, {0u, 0u, 1u, 0u}, {0u, 1u}, {0u, 0u}},
    {"g48_ceaseless_edge_spikes", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_ceaseless_edge_spikes", 1u, {0u, 0u, 1u, 0u}, {0u, 0u}, {0u, 1u}},
    {"g48_ceaseless_edge_spikes", 2u, {0u, 0u, 2u, 0u}, {0u, 0u}, {0u, 2u}},
    {"g48_ceaseless_edge_spikes", 3u, {0u, 0u, 3u, 0u}, {0u, 0u}, {0u, 3u}},
    {"g48_ceaseless_edge_spikes", 4u, {0u, 0u, 4u, 0u}, {0u, 0u}, {0u, 3u}},
    {"g48_population_bomb_fg_b", 0u, {0u, 0u, 0u, 0u}, {0u, 0u}, {0u, 0u}},
    {"g48_population_bomb_fg_b", 1u, {0u, 0u, 6u, 0u}, {0u, 0u}, {0u, 0u}},
};

static const char *const names[] = {"g48_rage_fist_a", "g48_rage_fist_switch", "g48_stone_axe_rock",
                                    "g48_stone_axe_miss", "g48_ceaseless_edge_spikes", "g48_population_bomb_fg_b"};

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.hits_taken_hazard_moves");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t hits_seen = 0u;
    uint32_t stealth_seen = 0u;
    uint32_t spikes_seen = 0u;
    check_facts(&t);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = df_conf_find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        df_conf_build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", names[n], duoforge_status_name(created));
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            df_conf_bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                  DUOFORGE_OK)) {
                break;
            }
            int found = 0;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0] && !found; ++r) {
                if (strcmp(rows[r].battle, names[n]) != 0 || rows[r].step != si) {
                    continue;
                }
                found = 1;
                for (uint32_t p = 0u; p < 4u; ++p) {
                    DF_CHECK_EQ_U64(&t, b->tail.sides[p / 2u].positions[p % 2u].hits_taken, rows[r].hits[p]);
                    hits_seen += rows[r].hits[p] != 0u ? 1u : 0u;
                }
                for (uint32_t s = 0u; s < 2u; ++s) {
                    DF_CHECK_EQ_U64(&t, b->tail.sides[s].stealth_rock, rows[r].stealth[s]);
                    DF_CHECK_EQ_U64(&t, b->tail.sides[s].spikes, rows[r].spikes[s]);
                    stealth_seen += rows[r].stealth[s] != 0u ? 1u : 0u;
                    spikes_seen += rows[r].spikes[s] != 0u ? 1u : 0u;
                }
                compared += 1u;
            }
            if (!found) {
                DF_CHECK(&t, 0);
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
            }
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, (uint32_t)(sizeof rows / sizeof rows[0]));
    /* Every quantity is up in some recorded step: the hits, Stealth Rock and Spikes. */
    DF_CHECK(&t, hits_seen != 0u && stealth_seen != 0u && spikes_seen != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
