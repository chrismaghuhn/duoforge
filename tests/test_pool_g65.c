/*
 * duoforge.state.pool_g65 (white-box): step G65 of the content expansion (decision 0015, item 5bk, simple modifier abilities),
 * POOL build.
 *
 * Five engine rows, read by id in combat/turn.c:
 *   Unaware       onAnyModifyBoost: the stat stages read for the other side's attacks (the holder as target zeroes the user's
 *                 attack-side reads, the holder as user the target's defence-side reads, and the accuracy and evasion of the draw)
 *   Marvel Scale  onModifyDef at priority 6: x1.5 on the Defence of a holder with a status
 *   Water Bubble  onSourceModifyAtk/SpA x0.5 for Fire at the holder, onModifyAtk/SpA x2 for its Water moves, the burn refused
 *   Reckless      onBasePower at priority 23: x4915/4096 for a move with a recoil (not Struggle, not the crash moves)
 *   Super Luck    onModifyCritRatio +1
 *
 * The recorded battles (g65_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares every
 * event, HP and draw with the reference. Here are the facts that they do not show by themselves:
 *   - the marks and the handler columns: the five rows are marked engine rows (family NONE, handler NONE), Mold Breaker, which
 *     would ignore a breakable ability, is not marked and stays UNMODELLED, and Reckless's crash clause is not modelled;
 *   - the rows the step relies on: Struggle has no recoil (its struggleRecoil is a flag), the recoil moves carry their fraction,
 *     and the crash moves (Axe Kick, High Jump Kick, Supercell Slam) are UNMODELLED, so no Reckless boost is reachable through them;
 *   - the four unmodified reads of the pin (getStat(..., true), which runs no ModifyBoost: moves.ts:10367 Light That Burns the
 *     Sky, :13346 Photon Geyser, :16230 Shell Side Arm, abilities.ts:1022 Download): Shell Side Arm is the only one in the pool,
 *     and it is an UNMODELLED row, so no read of it reaches Unaware; the other three are not pool rows;
 *   - Trace copying Water Bubble onto a burned holder is refused (E_UNSUPPORTED) and the battle is unchanged, as Limber's is:
 *     the Water Bubble onUpdate that would cure the burn is not modelled. The battle is the recorded ac1_trace_switch with
 *     both foes given Water Bubble as their ability now, and Gardevoir burned when it comes back in.
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

#define AB(name) (1u + DFI_ABILITY_##name)

/* ---- the marks, the handler columns and the rows that stay out */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_UNAWARE, DFI_ABILITY_MARVELSCALE, DFI_ABILITY_WATERBUBBLE,
                                         DFI_ABILITY_RECKLESS, DFI_ABILITY_SUPERLUCK};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    /* Mold Breaker (and so Teravolt and Turboblaze, which are not in the pool) would ignore the breakable flag of Unaware, Marvel
     * Scale and Water Bubble: it is not marked, and its row is UNMODELLED, so no team with it is played. */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

/* ---- the moves that Reckless's recoil clause reads, and the ones it must not reach */
static void check_recoil_rows(df_test *t)
{
    /* the recoil fraction of the move data: numerator and denominator (sim/battle-actions.ts applyRecoilDamage) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRAVEBIRD].recoil[0], 33u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRAVEBIRD].recoil[1], 100u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HEADSMASH].recoil[1], 2u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_WILDCHARGE].recoil[1], 4u);
    /* Struggle has no move.recoil (struggleRecoil is a flag, moves.ts:18228): Reckless does not boost it */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STRUGGLE].recoil[1], 0u);
    /* the crash moves (hasCrashDamage) are UNMODELLED: no Reckless boost reaches them, and the generator refuses a modelled one
     * while Reckless has no crash clause (pool_families.js checkG65) */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_AXEKICK].special, DFI_SPECIAL_UNMODELED);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_HIGHJUMPKICK].special, DFI_SPECIAL_UNMODELED);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SUPERCELLSLAM].special, DFI_SPECIAL_UNMODELED);
    /* Shell Side Arm reads the unmodified Attack and Special Attack (sim/battle-actions.ts getStat(..., true), moves.ts:16230):
     * the row is UNMODELLED, so no Unaware stage is zeroed in that read. Once it is modelled, its read is to be exempt. */
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_SHELLSIDEARM].special, DFI_SPECIAL_UNMODELED);
}

/* ---- Trace copying Water Bubble onto a burned holder: refused, the battle unchanged */
static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

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

static void check_trace_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("ac1_trace_switch");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 3u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < 3u; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK)) {
            duoforge_battle_destroy(b);
            return;
        }
    }
    /* Both foes hold Water Bubble now (so the draw of Trace keeps its two candidates), and the Trace holder that comes back in
     * is burned. */
    for (uint32_t p = 0u; p < 2u; ++p) {
        const uint32_t occupant = b->sides[1].positions[p].occupant;
        if (DF_CHECK(t, occupant < DUOFORGE_MAX_ROSTER && b->sides[1].members[occupant].hp != 0u)) {
            b->tail.sides[1].ability_now[occupant] = (uint16_t)AB(WATERBUBBLE);
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    /* the Trace holder of step 3 is the one that enters: it is burned before its entry (and before the copy of the battle) */
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if (b->sides[0].members[m].species_id == DFI_FORME_GARDEVOIR) {
            b->sides[0].members[m].status = DFI_STATUS_BRN;
        }
    }
    duoforge_battle *before = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &before) == DUOFORGE_OK && before != NULL)) {
        const df_conf_step *st = &cb->steps[3];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                        DUOFORGE_E_UNSUPPORTED);
        bool equal = false;
        DF_CHECK(t, duoforge_battle_equal(ctx, b, before, &equal) == DUOFORGE_OK && equal);
    }
    duoforge_battle_destroy(before);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g65");
    duoforge_context *kp = df_make_context(&df_config_pool);
    check_facts(&t);
    check_recoil_rows(&t);
    if (kp != NULL) {
        check_trace_refusal(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
