/*
 * duoforge.view.causes (decision 0023, decision 0026 section 4): the causes of a public refusal, from C.
 *
 * duoforge_battle_public_causes writes the mask of the causes that the player's view decides (visible sleep, visible
 * confusion; ILLUSION_POSSIBLE stays 0). duoforge_battle_public refuses exactly while the mask is nonzero: both read one
 * predicate. A mask of 0 with a refusing duoforge_battle_public means another refusal (a PIVOT here).
 *
 * - Sleep only, confusion only, both, neither: the mask, and the refusal of the record, for both players and both sides.
 * - Info safety: two battles that differ only in what the player does not see (the foe's running counters, the RNG) give
 *   equal masks, for both players.
 * - The argument checks, in the order of duoforge_battle_public, and no write on any refusal.
 * - The batch form equals the single calls for every worker count, with no allocation (as duoforge.view's batch test).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge_batch.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define BATCH_ENVS 16u
#define UNTOUCHED 0x55555555u

static const uint32_t workers[] = {1u, 2u, 3u, 4u, 8u, 16u};

/* The team selection of the four leads' picks 0 to 3 (as tests/test_pool_tail.c): the battle at its first TURN boundary. */
static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle_setup setup;
    df_setup_teams(&setup);
    duoforge_battle *b = df_make_battle(ctx, &setup);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, b->boundary_kind == DUOFORGE_BOUNDARY_TURN);
    return b;
}

/* The mask of one player, the call must succeed. */
static uint32_t causes_of(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player)
{
    uint32_t mask = UNTOUCHED;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, player, &mask) == DUOFORGE_OK);
    return mask;
}

/* The one predicate: the record is refused exactly while the mask is nonzero, and a refused record is not written. */
static void check_agreement(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t expect)
{
    for (uint32_t p = 0u; p < 2u; ++p) {
        const uint32_t mask = causes_of(t, ctx, b, p);
        DF_CHECK(t, mask == expect);
        duoforge_public_state v;
        memset(&v, 0x55, sizeof v);
        const duoforge_status st = duoforge_battle_public(ctx, b, p, &v);
        if (mask != 0u) {
            DF_CHECK(t, st == DUOFORGE_E_UNSUPPORTED && v.revision == UNTOUCHED);
        } else {
            DF_CHECK(t, st == DUOFORGE_OK);
        }
    }
}

static void test_causes_cases(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    const struct duoforge_battle original = *b;
    /* neither */
    check_agreement(t, ctx, b, 0u);
    /* sleep only: the occupant of either side's lead, each counter the state can hold */
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t counter = 1u; counter <= 3u; ++counter) {
            *b = original;
            const uint32_t member = b->sides[side].positions[0].occupant;
            b->sides[side].members[member].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
            b->sides[side].members[member].status_counter = (uint8_t)counter;
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            check_agreement(t, ctx, b, DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP);
        }
    }
    /* sleep only, on a bench member of side 1 that is not brought: its status is in the view of its own side only (the
     * foe's member that the player has not seen shows no status), so the mask depends on the viewer. */
    *b = original;
    b->sides[1].members[5].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[1].members[5].status_counter = 2u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    DF_CHECK(t, causes_of(t, ctx, b, 1u) == DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP);
    DF_CHECK(t, causes_of(t, ctx, b, 0u) == 0u);
    {
        duoforge_public_state v0;
        DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &v0) == DUOFORGE_OK);
        duoforge_public_state v1;
        DF_CHECK(t, duoforge_battle_public(ctx, b, 1u, &v1) == DUOFORGE_E_UNSUPPORTED);
    }
    /* confusion only: either side's lead, each counter 1 to 5 */
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t counter = 1u; counter <= 5u; ++counter) {
            *b = original;
            b->sides[side].positions[0].confusion_turns = (uint8_t)counter;
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            check_agreement(t, ctx, b, DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION);
        }
    }
    /* both: a sleep on one side and a confusion on the other, and both on one side */
    *b = original;
    b->sides[0].members[b->sides[0].positions[0].occupant].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[0].members[b->sides[0].positions[0].occupant].status_counter = 1u;
    b->sides[1].positions[1].confusion_turns = 3u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    check_agreement(t, ctx, b, DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP | DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION);
    *b = original;
    b->sides[1].members[b->sides[1].positions[1].occupant].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[1].members[b->sides[1].positions[1].occupant].status_counter = 2u;
    b->sides[1].positions[0].confusion_turns = 5u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    check_agreement(t, ctx, b, DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP | DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION);
    *b = original;
    duoforge_battle_destroy(b);
}

/* A mask of 0 with a refusing record: a PIVOT with no public current-turn move volatile (decision 0023, section 4). The
 * same state as tests/test_view.c's early-pivot case. */
static void test_other_refusal_is_mask_zero(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle *b = turn_battle(t, ctx);
    const uint32_t actor = b->sides[1].positions[0].activation_id;
    const dfi_queue_record move = {actor, (uint8_t)DFI_Q_MOVE, 1u, 0u, 0u, 0u, 0u};
    const dfi_queue_record residual = {0u, (uint8_t)DFI_Q_RESIDUAL, 0u, 0u, 0u, 0u, 0u};
    b->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    b->request_mask = 1u;
    ++b->request_epoch;
    b->sides[0].requested_slots = 1u;
    b->sides[1].requested_slots = 0u;
    b->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_EMERGENCY_EXIT;
    b->turn = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            b->sides[side].positions[slot].move_actions = 2u;
        }
    }
    b->queue_len = 2u;
    b->queue[0] = move;
    b->queue[1] = residual;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    for (uint32_t p = 0u; p < 2u; ++p) {
        DF_CHECK(t, causes_of(t, ctx, b, p) == 0u);
        duoforge_public_state v;
        memset(&v, 0x55, sizeof v);
        DF_CHECK(t, duoforge_battle_public(ctx, b, p, &v) == DUOFORGE_E_UNSUPPORTED && v.revision == UNTOUCHED);
    }
    /* the same PIVOT with a visible sleep: the mask names the sleep, and the record is refused for that cause too */
    b->sides[1].members[b->sides[1].positions[0].occupant].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[1].members[b->sides[1].positions[0].occupant].status_counter = 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    DF_CHECK(t, causes_of(t, ctx, b, 0u) == DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

/* Information safety: the mask is a function of the player's view. Two battles that differ only in hidden values (the
 * running counters of the foe, which the record hides, and the RNG) have equal masks and equal refusals, for both players. */
static void test_hidden_values_do_not_change_the_mask(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = turn_battle(t, ctx);
    const struct duoforge_battle original = *b;
    const uint32_t foe_lead = b->sides[1].positions[0].occupant;
    /* a visible sleep of the foe's lead: the counter is the hidden value */
    b->sides[1].members[foe_lead].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
    b->sides[1].members[foe_lead].status_counter = 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    const struct duoforge_battle sleeping = *b;
    uint32_t reference[2];
    for (uint32_t p = 0u; p < 2u; ++p) {
        reference[p] = causes_of(t, ctx, b, p);
        DF_CHECK(t, reference[p] == DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP);
    }
    for (uint32_t counter = 1u; counter <= 3u; ++counter) {
        for (uint32_t rng = 0u; rng < 3u; ++rng) {
            *b = sleeping;
            b->sides[1].members[foe_lead].status_counter = (uint8_t)counter;
            b->rng.state = (uint64_t)0x9E3779B97F4A7C15ull * (rng + 1u);
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            for (uint32_t p = 0u; p < 2u; ++p) {
                DF_CHECK(t, causes_of(t, ctx, b, p) == reference[p]);
            }
        }
    }
    /* a visible confusion of the foe's lead: its counter 1 to 5 is hidden, the mask is the same for each */
    *b = original;
    b->sides[1].positions[0].confusion_turns = 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    const struct duoforge_battle confused = *b;
    for (uint32_t p = 0u; p < 2u; ++p) {
        reference[p] = causes_of(t, ctx, b, p);
        DF_CHECK(t, reference[p] == DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION);
    }
    for (uint32_t counter = 1u; counter <= 5u; ++counter) {
        *b = confused;
        b->sides[1].positions[0].confusion_turns = (uint8_t)counter;
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        for (uint32_t p = 0u; p < 2u; ++p) {
            DF_CHECK(t, causes_of(t, ctx, b, p) == reference[p]);
        }
    }
    *b = original;
    duoforge_battle_destroy(b);
}

static void test_arguments(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_battle *b = turn_battle(t, ctx);
    duoforge_battle *pool = turn_battle(t, kp);
    uint32_t mask = UNTOUCHED;
    DF_CHECK(t, duoforge_battle_public_causes(NULL, b, 0u, &mask) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public_causes(ctx, NULL, 0u, &mask) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, mask == UNTOUCHED);
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 2u, &mask) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, mask == UNTOUCHED);
    /* the fingerprint: a POOL battle under the CLOSURE context */
    DF_CHECK(t, duoforge_battle_public_causes(ctx, pool, 0u, &mask) == DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK(t, mask == UNTOUCHED);
    /* the full state check, before the causes: an invariant (the field's gravity above 5) writes nothing */
    pool->tail.gravity_turns = 6u;
    DF_CHECK(t, duoforge_battle_public_causes(kp, pool, 0u, &mask) == DUOFORGE_E_INVARIANT);
    DF_CHECK(t, mask == UNTOUCHED);
    /* the same refusals as the record, in the same order */
    duoforge_public_state v;
    DF_CHECK(t, duoforge_battle_public(kp, pool, 0u, &v) == DUOFORGE_E_INVARIANT);
    DF_CHECK(t, duoforge_battle_public(ctx, pool, 0u, &v) == DUOFORGE_E_CONTEXT_MISMATCH);
    DF_CHECK(t, duoforge_battle_public(ctx, b, 2u, &v) == DUOFORGE_E_INVALID_ARGUMENT);
    /* the causes are never ILLUSION_POSSIBLE yet */
    DF_CHECK(t, causes_of(t, ctx, b, 0u) == 0u && causes_of(t, ctx, b, 1u) == 0u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP, 1u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION, 2u);
    DF_CHECK_EQ_U64(t, DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, 4u);
    duoforge_battle_destroy(pool);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(kp);
    duoforge_context_destroy(ctx);
}

/* The batch form equals the single calls, for every worker count. Each environment is a battle of the same teams, stepped
 * to its first TURN; some carry a visible sleep or confusion (the batch owns those battles, the test edits them through the
 * environment pointer before the calls). */
static void test_batch(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle_setup setup;
    df_setup_teams(&setup);
    for (uint32_t k = 0u; k < sizeof workers / sizeof workers[0]; ++k) {
        duoforge_battle_setup setups[BATCH_ENVS];
        for (uint32_t e = 0u; e < BATCH_ENVS; ++e) {
            setups[e] = setup;
        }
        duoforge_batch_config config = {BATCH_ENVS, workers[k], 42u, setups};
        duoforge_batch *batch = NULL;
        DF_CHECK(t, duoforge_batch_create(ctx, &config, &batch) == DUOFORGE_OK);
        duoforge_decision_bundle bundles[BATCH_ENVS];
        duoforge_step_result results[BATCH_ENVS];
        duoforge_status statuses[BATCH_ENVS];
        for (uint32_t e = 0u; e < BATCH_ENVS; ++e) {
            team_bundle(&bundles[e], duoforge_batch_env(batch, e));
        }
        DF_CHECK(t, duoforge_batch_step(batch, bundles, statuses, results) == DUOFORGE_OK);
        for (uint32_t e = 0u; e < BATCH_ENVS; ++e) {
            /* The batch owns its environments; the test edits them in place, through a union (no cast that drops const). */
            union {
                const duoforge_battle *c;
                duoforge_battle *m;
            } view_of_env;
            view_of_env.c = duoforge_batch_env(batch, e);
            duoforge_battle *env = view_of_env.m;
            DF_CHECK(t, env->boundary_kind == DUOFORGE_BOUNDARY_TURN);
            const uint32_t foe_lead = env->sides[1].positions[0].occupant;
            if (e % 3u == 0u) {
                env->sides[1].members[foe_lead].status = (uint8_t)DUOFORGE_AILMENT_SLEEP;
                env->sides[1].members[foe_lead].status_counter = (uint8_t)(1u + e % 3u);
            } else if (e % 3u == 1u) {
                env->sides[0].positions[1].confusion_turns = (uint8_t)(1u + e % 5u);
            }
            DF_CHECK(t, duoforge_battle_check(ctx, env) == DUOFORGE_OK);
        }
        uint32_t players[BATCH_ENVS];
        uint32_t masks[BATCH_ENVS];
        for (uint32_t e = 0u; e < BATCH_ENVS; ++e) {
            players[e] = e % 2u;
        }
        memset(masks, 0x55, sizeof masks);
        memset(statuses, 0x55, sizeof statuses);
        DF_CHECK(t, duoforge_batch_public_causes(batch, players, masks, statuses) == DUOFORGE_OK);
        uint32_t nonzero = 0u;
        for (uint32_t e = 0u; e < BATCH_ENVS; ++e) {
            const duoforge_battle *env = duoforge_batch_env(batch, e);
            DF_CHECK(t, statuses[e] == DUOFORGE_OK);
            DF_CHECK(t, masks[e] == causes_of(t, ctx, env, players[e]));
            nonzero += masks[e] != 0u ? 1u : 0u;
        }
        DF_CHECK(t, nonzero > 0u);
        /* a refused player writes nothing, and the first failure is returned */
        players[BATCH_ENVS - 1u] = 2u;
        memset(masks, 0x55, sizeof masks);
        memset(statuses, 0x55, sizeof statuses);
        DF_CHECK(t, duoforge_batch_public_causes(batch, players, masks, statuses) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, statuses[0] == UNTOUCHED && masks[0] == UNTOUCHED);
        DF_CHECK(t, duoforge_batch_public_causes(batch, NULL, masks, statuses) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(t, duoforge_batch_public_causes(batch, players, NULL, statuses) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(t, duoforge_batch_public_causes(batch, players, masks, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        duoforge_batch_destroy(batch);
    }
}

/* decision 0023 (the PP proxy, HauptSession): the record refuses while a foe's Revival Blessing slot shows derived PP 0,
 * whether or not a revive happened (the record keeps no history), with the generic cause (the mask stays 0); a foe's
 * slot at PP 1 is not refused for this, and an own slot at PP 0 is never refused for it. The battle is the recorded fail
 * battle g52_fail_no_fainted_pawmot (side 0 is Pawmot with Revival Blessing in slot 1); the viewer is player 1, so
 * side 0 is the foe; the viewer's knowledge of the foe's moves is set directly. */
static const df_conf_battle *find_conf_battle(const char *name)
{
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

static void build_pool_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
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

static void test_foe_revive_proxy(df_test *t, const duoforge_context *kp)
{
    const df_conf_battle *cb = find_conf_battle("g52_fail_no_fainted_pawmot");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_pool_setup(cb, &setup);
    duoforge_battle *b = NULL;
    DF_CHECK(t, duoforge_battle_create(kp, &setup, &b) == DUOFORGE_OK && b != NULL);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(kp, b, &bd, &res) == DUOFORGE_OK);
    DF_CHECK(t, b->boundary_kind == DUOFORGE_BOUNDARY_TURN);

    const uint32_t viewer = 1u;
    const uint32_t foe = 0u;
    /* the foe member with Revival Blessing (any roster member: the record shows the foe's moves of seen members) */
    uint32_t lead = DUOFORGE_MAX_ROSTER;
    uint32_t rb = DUOFORGE_MAX_MOVE_SLOTS;
    for (uint32_t m = 0u; m < b->sides[foe].member_count && lead == DUOFORGE_MAX_ROSTER; ++m) {
        for (uint32_t k = 0u; k < b->sides[foe].members[m].move_count; ++k) {
            if (b->sides[foe].members[m].moves[k].move_id == DFI_MOVE_REVIVALBLESSING) {
                lead = m;
                rb = k;
                break;
            }
        }
    }
    if (!DF_CHECK(t, lead < DUOFORGE_MAX_ROSTER && rb < DUOFORGE_MAX_MOVE_SLOTS)) {
        duoforge_battle_destroy(b);
        return;
    }
    dfi_member *fm = &b->sides[foe].members[lead];
    const uint32_t pp_max = fm->moves[rb].pp_max;
    b->sides[viewer].seen_mask = (uint8_t)(b->sides[viewer].seen_mask | (1u << lead));
    duoforge_public_state v;

    /* the foe used it once (derived PP 0), no revive: refused, mask 0 */
    b->sides[viewer].knowledge[lead].moves_used[rb] = (uint8_t)pp_max;
    DF_CHECK(t, duoforge_battle_public(kp, b, viewer, &v) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, causes_of(t, kp, b, viewer) == 0u);

    /* the same knowledge with an actual revive (the foe's member at half its maximum, as a revive leaves it): refused */
    dfi_member *mm = &b->sides[foe].members[lead];
    const uint16_t hp = mm->hp;
    mm->hp = (uint16_t)(mm->hp_max / 2u);
    DF_CHECK(t, duoforge_battle_public(kp, b, viewer, &v) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, causes_of(t, kp, b, viewer) == 0u);
    mm->hp = hp;

    /* the foe's slot at PP 1 (never used): not refused for this reason */
    b->sides[viewer].knowledge[lead].moves_used[rb] = 0u;
    DF_CHECK(t, duoforge_battle_public(kp, b, viewer, &v) == DUOFORGE_OK);
    duoforge_battle_destroy(b);

    /* the own side's Revival Blessing at PP 0 (the own PP is exact): not refused for this reason. Viewer 0 sees side 0. */
    duoforge_battle *o = NULL;
    DF_CHECK(t, duoforge_battle_create(kp, &setup, &o) == DUOFORGE_OK && o != NULL);
    team_bundle(&bd, o);
    DF_CHECK(t, duoforge_battle_step(kp, o, &bd, &res) == DUOFORGE_OK);
    for (uint32_t m = 0u; m < o->sides[0].member_count; ++m) {
        for (uint32_t k = 0u; k < o->sides[0].members[m].move_count; ++k) {
            if (o->sides[0].members[m].moves[k].move_id == DFI_MOVE_REVIVALBLESSING) {
                o->sides[0].members[m].moves[k].pp = 0u;
            }
        }
    }
    DF_CHECK(t, duoforge_battle_public(kp, o, 0u, &v) == DUOFORGE_OK);
    duoforge_battle_destroy(o);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.view.causes");
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *kp = df_make_context(&df_config_pool);
    test_arguments(&t);
    test_causes_cases(&t, k1);
    test_causes_cases(&t, kp);
    test_foe_revive_proxy(&t, kp);
    test_other_refusal_is_mask_zero(&t);
    test_hidden_values_do_not_change_the_mask(&t, k1);
    test_hidden_values_do_not_change_the_mask(&t, kp);
    test_batch(&t, k1);
    test_batch(&t, kp);
    duoforge_context_destroy(kp);
    duoforge_context_destroy(k1);
    return df_test_end(&t);
}
