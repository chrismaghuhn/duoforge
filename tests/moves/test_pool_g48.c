/*
 * duoforge.state.pool_g48 (white-box): step G48 of the content expansion, the moves that use the tail's rev 4 fields that
 * already exist: Rage Fist (its power is 50 + 50 per damaging hit the user took, the position's hits_taken), Stone Axe and
 * Ceaseless Edge (a hazard on the foe's side after a hit, the G37 add: Stealth Rock, one Spikes layer) and Population Bomb
 * (ten hits, multiaccuracy; its accuracy 90 is covered by the later-hit proof of G33).
 *
 * The recorded battles (g48_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything the reference shows (the damage of every hit, the
 * Stealth Rock and Spikes lines, the accuracy draws and the secondary rolls of the two hazard moves). Here is what it does not
 * show, after every step:
 *
 *   - the hits that each position has taken since it came in (timesAttacked: one per damaging hit of a move, saturating at 6,
 *     cleared when the occupant leaves) and the hazard layers of each side: the rows below are derived from the committed
 *     traces (one hit per public -damage line of a move's target, a switch or a faint clears the position; -sidestart and
 *     -sideend of the hazards), by a scratch helper that is not committed;
 *   - the bounds of the field: 6 is valid and 7 is refused by the invariants (Rage Fist's power is capped at 6 hits);
 *   - the marks: the four moves are supported; Quick Guard was dropped here (its block line needs a new BLOCKED detail) and
 *     is marked by step G54 with DUOFORGE_BLOCK_QUICK_GUARD (decision 0029).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "combat/multiaccuracy.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
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
    /* Population Bomb: ten hits, and the accuracy 90 that the later-hit proof covers (combat/multiaccuracy.h) */
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

/* The invariant of the field: six hits is the largest value (Rage Fist is at its cap then), a seventh is refused. */
static void check_bound(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g48_rage_fist_a");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    /* the team selection first: a position holds a tail only with a standing occupant (TAIL_POSITION) */
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[0], b, &bd);
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
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return 0u;
    }
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[0], b, &bd);
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
    bundle_of(&cb->steps[1], b, &turn);
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
    const df_conf_battle *cb = find("g48_rage_fist_a");
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
    df_test_begin(&t, "duoforge.state.pool_g48");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t hits_seen = 0u;
    uint32_t stealth_seen = 0u;
    uint32_t spikes_seen = 0u;
    check_facts(&t);
    check_bound(&t, ctx);
    check_power(&t, ctx);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", names[n], duoforge_status_name(created));
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
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
