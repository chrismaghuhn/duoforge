/*
 * duoforge.state.pool_g17 (white-box): step G17 of the content expansion, the recharge moves (Hyper Beam, Giga Impact,
 * Blast Burn, Frenzy Plant, Hydro Cannon, Meteor Assault, Rock Wrecker), in the POOL state tail (must_recharge of a
 * position, decision 0015 section 7), in the request (the one candidate MOVE with DUOFORGE_MOVE_SLOT_RECHARGE), in the
 * queue (the recharge action) and in the view extension (decision 0018: the MUST_RECHARGE bit of the position's
 * volatiles, supported bit 15).
 *
 * The recorded battles (g17_* under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares everything the reference shows (every HP, PP, event and
 * request, and the tape). Here the state that the reference does not show is read after every step: the tail's
 * must_recharge and encore_slot of every position, the candidates of every slot, and both viewers' extension.
 *
 *   g17_hyper_beam          a hit, the recharge turn (move 1: cant|recharge, no PP), and the turn after it
 *   g17_hyper_beam_protect  Protect stops it: no recharge
 *   g17_hyper_beam_immune   a Ghost is immune: no recharge
 *   g17_hyper_beam_miss     a miss: no recharge
 *   g17_hyper_beam_ko       a knocked-out target still gives the recharge
 *   g17_hyper_beam_encore   Encore on a Pokemon that must recharge (its recharge action is replaced, it recharges anyway)
 *   g17_hyper_beam_sucker   Sucker Punch fails against a Pokemon that must recharge
 *   g17_hyper_beam_flinch   Fake Out on the recharge turn: cant|recharge only
 *   g17_hyper_beam_scarf    a Choice Scarf holder is locked into Hyper Beam after its recharge
 *   g17_recharge_moves      Blast Burn, Frenzy Plant, Hydro Cannon and Rock Wrecker: four recharges on one turn
 *   g17_giga_impact         Giga Impact and Hyper Beam together
 *
 * Meteor Assault (Champions: 170 power) has the recharge bit but is not marked: its only learner, Sirfetch'd, has no
 * supported ability, so no setup can use it (checked below).
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


/* After each step of each battle: whether each position must recharge (-mustrecharge shows it, cant|X|recharge or the
 * occupant's leaving ends it) and which slot (slot + 1) it is Encored to: what the protocol lines say alone;
 * tools/reference/test_trace_to_c.py derives the rows from the committed traces and requires this table to be exactly
 * that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint8_t recharge[4];
    uint8_t encore[4];
} rows[] = {
    {"g17_giga_impact", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_giga_impact", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_giga_impact", 2u, {0u, 1u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_giga_impact", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 2u, {0u, 0u, 0u, 0u}, {1u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 3u, {1u, 0u, 0u, 0u}, {1u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 4u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_encore", 5u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_flinch", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_flinch", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_flinch", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_flinch", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_immune", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_immune", 1u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_immune", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_ko", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_ko", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_ko", 2u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_ko", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_miss", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_miss", 1u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_miss", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_protect", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_protect", 1u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_protect", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_scarf", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_scarf", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_scarf", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_scarf", 3u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_sucker", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_sucker", 1u, {1u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_sucker", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_hyper_beam_sucker", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_recharge_moves", 0u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_recharge_moves", 1u, {1u, 1u, 1u, 1u}, {0u, 0u, 0u, 0u}},
    {"g17_recharge_moves", 2u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
    {"g17_recharge_moves", 3u, {0u, 0u, 0u, 0u}, {0u, 0u, 0u, 0u}},
};

static const char *const names[] = {"g17_giga_impact", "g17_hyper_beam", "g17_hyper_beam_encore", "g17_hyper_beam_flinch", "g17_hyper_beam_immune", "g17_hyper_beam_ko", "g17_hyper_beam_miss", "g17_hyper_beam_protect", "g17_hyper_beam_scarf", "g17_hyper_beam_sucker", "g17_recharge_moves"};

static bool row_of(const char *battle, uint32_t step, const uint8_t **recharge, const uint8_t **encore)
{
    for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
        if (strcmp(rows[r].battle, battle) == 0 && rows[r].step == step) {
            *recharge = rows[r].recharge;
            *encore = rows[r].encore;
            return true;
        }
    }
    return false;
}

/* The candidates of every slot of `player` against the tail: a slot that must recharge is offered exactly one
 * candidate, MOVE with the recharge slot and no target, Mega or switch; no other slot is offered the recharge. */
static void check_requests(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, const uint8_t *recharge,
                           const char *name, uint32_t step)
{
    static duoforge_side_choice buf[DUOFORGE_MAX_CANDIDATES];
    for (uint32_t player = 0u; player < 2u; ++player) {
        uint32_t count = 0u;
        if (duoforge_battle_candidates(ctx, b, player, buf, DUOFORGE_MAX_CANDIDATES, &count) != DUOFORGE_OK) {
            continue; /* terminal, or nothing requested of this player */
        }
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            for (uint32_t i = 0u; i < count; ++i) {
                const duoforge_slot_command *c = &buf[i].slots[slot];
                const bool is_recharge = c->kind == (uint8_t)DUOFORGE_SLOT_MOVE && c->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE;
                if (b->boundary_kind != DUOFORGE_BOUNDARY_TURN || c->kind == (uint8_t)DUOFORGE_SLOT_NONE) {
                    continue;
                }
                if (recharge[player * 2u + slot] != 0u) {
                    if (!DF_CHECK(t, is_recharge && c->target == DUOFORGE_TARGET_NONE && c->mega == 0u)) {
                        fprintf(stderr, "  %s step %u player %u slot %u: candidate kind %u slot %u\n", name, step, player, slot,
                                (unsigned)c->kind, (unsigned)c->move_slot);
                    }
                } else {
                    DF_CHECK(t, !is_recharge);
                }
            }
        }
    }
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
            const uint8_t *want_recharge = NULL;
            const uint8_t *want_encore = NULL;
            if (!DF_CHECK(t, row_of(names[n], si, &want_recharge, &want_encore))) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            for (uint32_t flat = 0u; flat < 4u; ++flat) {
                const dfi_tail_pos *tp = &b->tail.sides[flat / 2u].positions[flat % 2u];
                if (!DF_CHECK(t, tp->must_recharge == want_recharge[flat] && tp->encore_slot == want_encore[flat])) {
                    fprintf(stderr, "  %s step %u position %u: must_recharge %u encore %u, want %u and %u\n", names[n], si,
                            flat, tp->must_recharge, tp->encore_slot, want_recharge[flat], want_encore[flat]);
                }
            }
            check_requests(t, ctx, b, want_recharge, names[n], si);
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
                want.supported = dfi_support.view_ext_features;
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    duoforge_position_ext *pe = &want.sides[flat / 2u].positions[flat % 2u];
                    pe->encore_slot = want_encore[flat];
                    pe->volatiles = want_recharge[flat] != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_MUST_RECHARGE : 0u;
                }
                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
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
    df_test_begin(&t, "duoforge.state.pool_g17");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The new public values as numbers. */
    DF_CHECK_EQ_U64(&t, DUOFORGE_MOVE_SLOT_RECHARGE, 5u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VOLATILE_MUST_RECHARGE, 3u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_CAUSE_RECHARGE, 18u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE, 15u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE)) != 0u);
    /* The seven recharge moves of the pool are exactly the ones with the recharge bit; six are marked. */
    {
        uint32_t flagged = 0u;
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            const bool bit = (dfi_pool_move_flags2[id] & DFI_MOVE_FLAG2_RECHARGE) != 0u;
            flagged += bit ? 1u : 0u;
            if (bit) {
                DF_CHECK(&t, (dfi_support.moves[id] != 0u) == (id != DFI_MOVE_METEORASSAULT));
                DF_CHECK(&t, dfi_pool_moves[id].special == DFI_SPECIAL_NONE);
            }
        }
        DF_CHECK_EQ_U64(&t, flagged, 7u);
        DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_HYPERBEAM] & DFI_MOVE_FLAG2_RECHARGE) != 0u);
        DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_METEORASSAULT] & DFI_MOVE_FLAG2_RECHARGE) != 0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_moves[DFI_MOVE_METEORASSAULT].base_power, 170u); /* the Champions mod's power */
        DF_CHECK(&t, (dfi_pool_move_flags2[DFI_MOVE_FLAMETHROWER] & DFI_MOVE_FLAG2_RECHARGE) == 0u);
    }

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev); /* POOL_DEV: its own fingerprint, the same tables */
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    /* The recharge turn uses no PP and leaves the last move (g17_hyper_beam, steps 1 to 2: Raichu is position 0). */
    {
        duoforge_battle *b1 = replay(&t, kp, "g17_hyper_beam", 2u);
        duoforge_battle *b2 = replay(&t, kp, "g17_hyper_beam", 3u);
        if (b1 != NULL && b2 != NULL) {
            const dfi_member *m1 = &b1->sides[0].members[b1->sides[0].positions[0].occupant];
            const dfi_member *m2 = &b2->sides[0].members[b2->sides[0].positions[0].occupant];
            for (uint32_t k = 0u; k < m1->move_count; ++k) {
                DF_CHECK_EQ_U64(&t, m2->moves[k].pp, m1->moves[k].pp); /* the recharge turn spent none */
            }
            DF_CHECK_EQ_U64(&t, b1->tail.sides[0].positions[0].last_move, 1u); /* Hyper Beam, the first slot */
            DF_CHECK_EQ_U64(&t, b2->tail.sides[0].positions[0].last_move, 1u);
            DF_CHECK(&t, m1->moves[0].pp + 1u == m1->moves[0].pp_max || m1->moves[0].pp < m1->moves[0].pp_max);
        }
        if (b1 != NULL) {
            duoforge_battle_destroy(b1);
        }
        if (b2 != NULL) {
            duoforge_battle_destroy(b2);
        }
    }

    /* The recharge slot offers nothing else: another move or a switch for it is refused, and the battle stays
     * as it was (g17_hyper_beam after step 1: Raichu must recharge). */
    {
        duoforge_battle *b = replay(&t, kp, "g17_hyper_beam", 2u);
        const df_conf_battle *cb = find("g17_hyper_beam");
        if (b != NULL && cb != NULL) {
            for (uint32_t variant = 0u; variant < 3u; ++variant) {
                const df_conf_step *st = &cb->steps[2];
                duoforge_decision_bundle bd;
                bundle_of(st, b, &bd);
                duoforge_slot_command *c = &bd.responses[0].slots[0];
                if (variant == 0u) {
                    *c = (duoforge_slot_command){(uint8_t)DUOFORGE_SLOT_MOVE, 1u, 2u, 0u, 0u, {0u, 0u, 0u}}; /* Thunderbolt */
                } else if (variant == 1u) {
                    *c = (duoforge_slot_command){(uint8_t)DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 2u, {0u, 0u, 0u}};
                } else {
                    *c = (duoforge_slot_command){(uint8_t)DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
                }
                duoforge_step_result res;
                DF_CHECK(&t, duoforge_battle_step(kp, b, &bd, &res) != DUOFORGE_OK);
                DF_CHECK(&t, b->tail.sides[0].positions[0].must_recharge == 1u);
            }
            duoforge_battle_destroy(b);
        }
    }

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
