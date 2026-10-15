/*
 * duoforge.state.pool_k4_draws (white-box): step K4 (#475, decision 0015 5df), Gravity's accuracy rule with the draws of the
 * recorded k4 battles changed by one value each.
 *
 * The recorded battles are replayed by duoforge.reference.conformance_pool_data with the reference's draws. Here one
 * accuracy draw of each battle is set to a value that the rule decides and a variant of the rule would not:
 *
 *   - k4_gravity_accuracy, step 2: Milotic's Hypnosis (accuracy 60) at the first hit. Gravity multiplies it by 6840/4096:
 *     60 x 6840 = 410400, (410400 + 2047) / 4096 = 100, so the draw 70 (< 100) hits. Without the Gravity factor (M1) the
 *     threshold is 60 and 70 misses, the replay diverges and the check fails. The recorded draw is 43.
 *   - k4_gravity_multihit, step 2: Milotic's Triple Axel, the second (later) hit at stages 0: 90 x 6840 = 615600,
 *     (615600 + 2047) / 4096 = 150, so the draw 95 (< 150) hits. Without the later-hit integer rule (M2) the threshold is
 *     90 and 95 misses. The recorded draw is 52.
 *
 * Each check plays every step of the battle with the one value changed and expects every step to play (the recorded
 * outcome: the same path, the same draws after it).
 */
#include <stdint.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define K4_TAPE_MAX 256u

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
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
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u));
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

/* Replays the recorded battle. When set_step is a step, its tape is a copy with the accuracy draw of the old value
 * replaced by new_value. Returns the number of steps played (step_count when every step played). */
static uint32_t play(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t set_step, uint32_t old_value,
                     uint32_t new_value, duoforge_status *status)
{
    static dfi_tape_entry buf[K4_TAPE_MAX];
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    *status = DUOFORGE_OK;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return 0u;
    }
    uint32_t si = 0u;
    for (; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        const dfi_tape_entry *tape = &conf_tape[st->tape_off];
        uint32_t len = st->tape_len;
        if (si == set_step) {
            if (!DF_CHECK(t, len <= K4_TAPE_MAX)) {
                break;
            }
            memcpy(buf, tape, len * sizeof buf[0]);
            uint32_t hit = 0u;
            for (uint32_t k = 0; k < len; ++k) {
                if (buf[k].site == DFI_SITE_ACCURACY && buf[k].value == old_value) {
                    buf[k].value = new_value;
                    hit++;
                    break;
                }
            }
            DF_CHECK_EQ_U64(t, hit, 1u); /* the recorded accuracy draw of the step */
            tape = buf;
        }
        *status = dfi_battle_step_tape(ctx, b, &bd, tape, len, &used, &res);
        if (*status != DUOFORGE_OK) {
            break;
        }
        if (si == set_step) {
            /* the recorded path draws every value of the tape: a different outcome of the accuracy draw draws fewer or more */
            DF_CHECK_EQ_U64(t, used, len);
        }
    }
    duoforge_battle_destroy(b);
    return si;
}

static void check_gravity_first_hit(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("k4_gravity_accuracy");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    /* as recorded: every step is played */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, UINT32_MAX, 0u, 0u, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* step 2, Hypnosis (accuracy 60, Gravity 6840/4096 -> 100): a draw of 70 hits; every later step plays as recorded */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, 2u, 43u, 70u, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
}

static void check_gravity_later_hit(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("k4_gravity_multihit");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, UINT32_MAX, 0u, 0u, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* step 2, Triple Axel, the second hit (later hit, accuracy 90 x 6840 -> 150): a draw of 95 hits */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, 2u, 52u, 95u, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
}

/* 3. The later hit at a non-zero stage pair (M10, decision 0015 5df). In k4_gravity_multihit the Triple Axel step (step 2)
 * hits three times under Gravity with the recorded accuracy draws 47, 52 and 72. Here the user (Milotic, side 1) is raised
 * to accuracy +1 and the target (Metagross, side 0) to evasion +6, set on the live battle after steps 0 and 1; the reachable
 * pair (1, 6) is not reached by the marked content (Double Team is unmarked, Minimize and Sweet Scent are unmodelled), so
 * the rule is checked white-box. The first hit's threshold is then 150 x 4/3 x 3/9 = 66, so the draw 47 hits. The later hit:
 * accuracy 90 x (3+1)/3 x 3/(3+6) = 40 is an integer, and Gravity's 6840/4096 gives trunc((40 x 6840 + 2047) / 4096) = 67
 * (sim/battle.ts:929-932, the modify rounding of the integer value), so the draw 66 hits. Without the +2047 (the mutant)
 * the threshold is 66 and 66 misses: the later hit is not played and the step does not draw its tape. The draw after it
 * is 26, below 67, so the third hit lands too. The tape of the step is otherwise the recorded one; used must equal len. */
static void check_later_hit_stage_pair(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("k4_gravity_multihit");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 2u)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    for (uint32_t si = 0u; si < 2u; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            duoforge_battle_destroy(b);
            return;
        }
    }
    /* the stages of the pair: user accuracy +1 (biased 7), target evasion +6 (biased DFI_STAGE_MAX) */
    b->sides[1].positions[0].stages[DFI_STAGE_ACCURACY] = 7u;
    b->sides[0].positions[0].stages[DFI_STAGE_EVASION] = (uint8_t)DFI_STAGE_MAX;
    const df_conf_step *st = &cb->steps[2];
    static dfi_tape_entry buf[K4_TAPE_MAX];
    if (DF_CHECK(t, st->tape_len <= K4_TAPE_MAX)) {
        memcpy(buf, &conf_tape[st->tape_off], st->tape_len * sizeof buf[0]);
        uint32_t seen = 0u;
        uint32_t idx[3] = {0u, 0u, 0u};
        for (uint32_t k = 0u; k < st->tape_len && seen < 3u; ++k) {
            if (buf[k].site == DFI_SITE_ACCURACY) {
                idx[seen++] = k;
            }
        }
        if (DF_CHECK_EQ_U64(t, seen, 3u) && DF_CHECK_EQ_U64(t, buf[idx[0]].value, 47u) &&
            DF_CHECK_EQ_U64(t, buf[idx[1]].value, 52u)) {
            buf[idx[1]].value = 66u; /* the later hit: threshold 67 with the +2047 rule, 66 without */
            buf[idx[2]].value = 26u; /* the third hit: below both thresholds */
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, buf, st->tape_len, &used, &res) == DUOFORGE_OK)) {
                DF_CHECK_EQ_U64(t, used, st->tape_len);
            }
        }
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_k4_draws");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_gravity_first_hit(&t, ctx);
    check_gravity_later_hit(&t, ctx);
    check_later_hit_stage_pair(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
