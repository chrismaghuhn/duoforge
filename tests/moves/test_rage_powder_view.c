/*
 * duoforge.moves.rage_powder_view (white-box): step G30 of the content expansion, Rage Powder in the view extension. Rage
 * Powder shares the position's Follow Me bit with Follow Me, and the last move of the occupant tells them apart
 * (dfi_last_move_id). After every step of the recorded g30_* battles, replayed with the reference's draws: the extension of
 * both viewers has the position bit RAGE_POWDER (decision 0018, supported bit 39, public) exactly where the protocol says Rage
 * Powder stands, at the PIVOT boundary inside the turn of g30_rage_powder_pivot and at no turn boundary (the residual ends it);
 * no position shows Follow Me's flag in the player view; and no other volatile bit of the extension is set.
 *
 * Split by subject from the test of step G30 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

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

static const char *const names[] = {
    "g30_rage_powder_a",     "g30_overcoat_rage",      "g30_rage_powder_pivot", "g30_overcoat_powder", "g30_powder_a",
    "g30_powder_b",          "g30_psychic_fangs",      "g30_solar_beam_sun_rain", "g30_solar_beam_sand_snow",
    "g30_flame_body",        "g30_flame_body_ko",      "g30_clear_body",        "g30_hospitality",      "g30_hospitality_trace",
    "g30_matcha_drain_rows"};

/* The one boundary of the battles where Rage Powder stands: after step 1 of g30_rage_powder_pivot (the request for the
 * U-turn's switch, inside the turn), on side 0 position 0 (Sinistcha). */
static uint32_t rage_powder_at(const char *battle, uint32_t step, uint32_t side, uint32_t pos)
{
    return strcmp(battle, "g30_rage_powder_pivot") == 0 && step == 1u && side == 0u && pos == 0u
               ? DUOFORGE_POSITION_EXT_RAGE_POWDER
               : 0u;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.rage_powder_view");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t rage_seen = 0u;
    (void)conf_events;
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = df_conf_find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            fprintf(stderr, "  %s: not in the conformance data\n", names[n]);
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
                fprintf(stderr, "  %s step %u: the step fails\n", names[n], si);
                break;
            }
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                duoforge_observation_ext ext;
                memset(&ob, 0, sizeof ob);
                memset(&ext, 0, sizeof ext);
                if (!DF_CHECK(&t, duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK &&
                                      duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK)) {
                    continue;
                }
                for (uint32_t s = 0u; s < 2u; ++s) {
                    for (uint32_t p = 0u; p < 2u; ++p) {
                        const uint32_t want = rage_powder_at(names[n], si, s, p);
                        if (!DF_CHECK_EQ_U64(&t, ext.sides[s].positions[p].volatiles, want)) {
                            fprintf(stderr, "  %s step %u viewer %u side %u position %u: volatiles %08x, want %08x\n",
                                    names[n], si, viewer, s, p, (unsigned)ext.sides[s].positions[p].volatiles,
                                    (unsigned)want);
                        }
                        rage_seen += (ext.sides[s].positions[p].volatiles & DUOFORGE_POSITION_EXT_RAGE_POWDER) != 0u ? 1u : 0u;
                        DF_CHECK_EQ_U64(&t, ob.sides[s].positions[p].reserved & DUOFORGE_POSITION_FLAG_FOLLOW_ME, 0u);
                    }
                }
                compared += 1u;
            }
        }
        duoforge_battle_destroy(b);
    }
    /* The bit was seen at the one boundary of each viewer, and every comparison ran. */
    DF_CHECK_EQ_U64(&t, rage_seen, 2u);
    DF_CHECK(&t, compared != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
