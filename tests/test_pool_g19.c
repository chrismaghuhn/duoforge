/*
 * duoforge.state.pool_g19 (white-box): step G19 of the content expansion, Coaching and Glaive Rush: Coaching's boosts
 * for the ally (target adjacentAlly, boost role PRIMARY_ALLY) and Glaive Rush's volatile in the POOL state tail
 * (glaive_rush of a position, decision 0015 section 7) and in the view extension (decision 0018: the GLAIVE_RUSH bit of
 * the position's volatiles, supported bit 20).
 *
 * The recorded battles (g19_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything the reference shows: every HP (so the doubled
 * damage), every boost line, the events, and the tape (no ACCURACY draw for a move against a Glaive Rush user). Here the
 * state that the reference does not show is read after every step: the tail's glaive_rush of every position and both
 * viewers' extension.
 *
 *   g19_coaching                 +1 Attack and Defense for the ally, twice, and the damage that shows it
 *   g19_coaching_contrary        an ally with Contrary is lowered by it
 *   g19_coaching_good_as_gold    an ally with Good as Gold is immune (a status move of another Pokemon)
 *   g19_coaching_no_ally         no standing ally: the move fails
 *   g19_coaching_protect         a Protecting ally is not stopped (no protect flag)
 *   g19_glaive_rush              the user is hit doubled until its next move starts, then normally
 *   g19_glaive_rush_protect      Protect stops it: no drawback
 *   g19_glaive_rush_immune       a Fairy is immune: no drawback
 *   g19_glaive_rush_flinch       Fake Out on the next turn: doubled, then the flinch, and the drawback is gone
 *   g19_glaive_rush_mega         Mega Baxcalibur (step G18) uses it on the turn it Mega Evolves
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The battle `name` after its first `steps` steps (the reference's draws as the tape); NULL when it fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}


/* After each step of each battle: whether each position is hit as vulnerable (Glaive Rush hit; its own next action,
 * whatever it does, or its leaving the field, ends it): what the protocol lines say alone; tools/reference/
 * test_trace_to_c.py derives the rows from the committed traces and requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint8_t glaive[4];
} rows[] = {
    {"g19_coaching", 0u, {0u, 0u, 0u, 0u}},
    {"g19_coaching", 1u, {0u, 0u, 0u, 0u}},
    {"g19_coaching", 2u, {0u, 0u, 0u, 0u}},
    {"g19_coaching", 3u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_contrary", 0u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_contrary", 1u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_contrary", 2u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_good_as_gold", 0u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_good_as_gold", 1u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_good_as_gold", 2u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_no_ally", 0u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_no_ally", 1u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_no_ally", 2u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_protect", 0u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_protect", 1u, {0u, 0u, 0u, 0u}},
    {"g19_coaching_protect", 2u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush", 0u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush", 1u, {1u, 0u, 0u, 0u}},
    {"g19_glaive_rush", 2u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_flinch", 0u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_flinch", 1u, {1u, 0u, 0u, 0u}},
    {"g19_glaive_rush_flinch", 2u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_immune", 0u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_immune", 1u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_immune", 2u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_mega", 0u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_mega", 1u, {1u, 0u, 0u, 0u}},
    {"g19_glaive_rush_mega", 2u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_protect", 0u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_protect", 1u, {0u, 0u, 0u, 0u}},
    {"g19_glaive_rush_protect", 2u, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g19_coaching", "g19_coaching_contrary", "g19_coaching_good_as_gold", "g19_coaching_no_ally", "g19_coaching_protect", "g19_glaive_rush", "g19_glaive_rush_flinch", "g19_glaive_rush_immune", "g19_glaive_rush_mega", "g19_glaive_rush_protect"};

static const uint8_t *row_of(const char *battle, uint32_t step)
{
    for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
        if (strcmp(rows[r].battle, battle) == 0 && rows[r].step == step) {
            return rows[r].glaive;
        }
    }
    return NULL;
}

static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            const uint8_t *want = row_of(names[n], si);
            if (!DF_CHECK(t, want != NULL)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                if (!DF_CHECK(t, tp->glaive_rush == want[flat])) {
                    fprintf(stderr, "  %s step %u position %u: glaive_rush %u, want %u\n", names[n], si, flat,
                            tp->glaive_rush, want[flat]);
                }
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext exp;
                memset(&exp, 0, sizeof exp);
                exp.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                exp.player = (uint8_t)viewer;
                exp.epoch = ob.epoch;
                exp.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    exp.sides[flat / 2u].positions[flat % 2u].volatiles =
                        want[flat] != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_GLAIVE_RUSH : 0u;
                }
                for (uint32_t g42f = 0u; g42f < 4u; ++g42f) { /* step G42: move_failed is the last move result FALSE */
                    const uint32_t g42last = ((uint32_t)b->tail.sides[g42f / 2u].positions[g42f % 2u].move_result >> 2) & 3u;
                    exp.sides[g42f / 2u].positions[g42f % 2u].move_failed = g42last == 2u ? 1u : 0u;
                }                if (!DF_CHECK(t, memcmp(&ext[viewer], &exp, sizeof exp) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's\n", names[n], si,
                            viewer);
                }
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g19");
    (void)conf_events;
    (void)replay;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH, 20u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH)) != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_COACHING] != 0u && dfi_support.moves[DFI_MOVE_GLAIVERUSH] != 0u);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_COACHING].boost_role, DFI_BOOST_ROLE_PRIMARY_ALLY);
    DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_GLAIVERUSH].special, DFI_SPECIAL_GLAIVE_RUSH);

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev); /* POOL_DEV: its own fingerprint, the same tables */
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
