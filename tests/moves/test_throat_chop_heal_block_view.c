/*
 * duoforge.moves.throat_chop_heal_block_view (white-box): step G8 of the content expansion, the public view extension (decision
 * 0018) of Throat Chop and Heal Block: after every step of the five recorded g8_* battles, both viewers' extension equals the
 * expected one byte for byte (revision, viewer, epoch, the two supported bits, the two position bits of the table and nothing
 * else; the hidden counters never show, Throat Chop is public, so the foe sees it as well), and the two viewers' position
 * sections are the same. The table is what the protocol lines say alone; tools/reference/test_trace_to_c.py derives it from the
 * committed traces.
 *
 * Split by subject from the test of step G8 (restructure step 6e; tests/renames.tsv maps the old name).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The public view extension (decision 0018) after each step of the recorded battles: for every step, which positions
 * (bit = side * 2 + slot) have Throat Chop and which have Heal Block. The rows are what the protocol lines say alone
 * (a -start|X|Throat Chop|[silent] or -start|X|move: Heal Block sets it, the matching -end, a switch, a drag or a
 * faint of the position clears it: decision 0018 section 6.1); tools/reference/test_trace_to_c.py derives them
 * from the committed traces and requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t throat_chop;
    uint32_t heal_block;
} view_ext_rows[] = {
    {"g8_throat_chop", 0u, 0x0u, 0x0u},
    {"g8_throat_chop", 1u, 0xcu, 0x0u},
    {"g8_throat_chop", 2u, 0x0u, 0x0u},
    {"g8_throat_chop", 3u, 0x0u, 0x0u},
    {"g8_throat_chop", 4u, 0x0u, 0x0u},
    {"g8_throat_chop", 5u, 0x0u, 0x0u},
    {"g8_throat_chop", 6u, 0x0u, 0x0u},
    {"g8_throat_chop", 7u, 0x0u, 0x0u},
    {"g8_heal_block", 0u, 0x0u, 0x0u},
    {"g8_heal_block", 1u, 0x0u, 0x4u},
    {"g8_heal_block", 2u, 0x0u, 0x8u},
    {"g8_heal_block", 3u, 0x0u, 0x0u},
    {"g8_heal_block", 4u, 0x0u, 0x0u},
    {"g8_heal_block", 5u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 0u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 1u, 0x0u, 0x5u},
    {"g8_heal_block_pair", 2u, 0x0u, 0x5u},
    {"g8_heal_block_pair", 3u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 4u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 5u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 0u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 1u, 0x0u, 0x5u},
    {"g8_heal_block_tie_a", 2u, 0x0u, 0x5u},
    {"g8_heal_block_tie_a", 3u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 4u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 5u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 0u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 1u, 0x0u, 0x5u},
    {"g8_heal_block_tie_b", 2u, 0x0u, 0x5u},
    {"g8_heal_block_tie_b", 3u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 4u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 5u, 0x0u, 0x0u},
};

/* Both viewers' extension after every step of every battle of the table equals the expected one byte for byte:
 * revision, viewer, epoch, the two supported bits, the two position bits of the rows and nothing else (the
 * hidden counters never show; Throat Chop is public, so the foe sees it as well), and the two viewers' position
 * sections are the same. */
static void check_view_ext(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g8_throat_chop", "g8_heal_block", "g8_heal_block_pair", "g8_heal_block_tie_a",
                                        "g8_heal_block_tie_b"};
    uint32_t compared = 0u;
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = df_conf_find(names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        df_conf_build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            df_conf_bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            uint32_t tc = 0xFFu;
            uint32_t hb = 0xFFu;
            for (size_t r = 0u; r < sizeof view_ext_rows / sizeof view_ext_rows[0]; ++r) {
                if (strcmp(view_ext_rows[r].battle, names[n]) == 0 && view_ext_rows[r].step == si) {
                    tc = view_ext_rows[r].throat_chop;
                    hb = view_ext_rows[r].heal_block;
                }
            }
            if (!DF_CHECK(t, tc != 0xFFu && hb != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                /* The mask is the build's: G8's two bits are set (checked here) and later steps add theirs. */
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(t, (want.supported & (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                               ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK))) ==
                                (((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK)));
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    want.sides[flat / 2u].positions[flat % 2u].volatiles =
                        (((tc >> flat) & 1u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_THROAT_CHOP : 0u) |
                        (((hb >> flat) & 1u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_HEAL_BLOCK : 0u);
                }
                for (uint32_t g42f = 0u; g42f < 4u; ++g42f) { /* step G42: move_failed is the last move result FALSE */
                    const uint32_t g42last = ((uint32_t)b->tail.sides[g42f / 2u].positions[g42f % 2u].move_result >> 2) & 3u;
                    want.sides[g42f / 2u].positions[g42f % 2u].move_failed = g42last == 2u ? 1u : 0u;
                }                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (want Throat Chop "
                                    "0x%x, Heal Block 0x%x)\n",
                            names[n], si, viewer, tc, hb);
                }
                compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(t, compared, 2u * (uint32_t)(sizeof view_ext_rows / sizeof view_ext_rows[0]));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.moves.throat_chop_heal_block_view");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_view_ext(&t, kp);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
