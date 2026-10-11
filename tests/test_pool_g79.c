/*
 * duoforge.state.pool_g79 (white-box): step G79, Cloud Nine (decision 0015 5br).
 *
 *   Altaria and Drampa       Cloud Nine     the weather is suppressed while a holder stands (data/abilities.ts:543-562,
 *                                           sim/field.ts:106-116); its switch-in prints -ability and nothing else
 *
 * The recorded battles (g79_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares every
 * event with the reference. Here are the facts that it does not show:
 *
 *   - the mark: Cloud Nine is an engine row (read by id, no family, no handler of its own);
 *   - Mega Sol's refusal under Cloud Nine (dfi_mega_sol_refused): the recorded Meganium-Mega battle g59_mega_sol, with a foe that
 *     holds Cloud Nine from step 2 on, is refused (E_UNSUPPORTED) at its Solar Beam, while the same battle as recorded is played;
 *   - the refusal of a copied Cloud Nine (dfi_trace): the g79_cloud_nine_skill_swap battle with its Gardevoir set to Trace is
 *     played on sixteen seeds; a step that copies Cloud Nine is refused, and no played step ends with a Cloud Nine copy. The
 *     same battle with the ability as recorded is played on the same seeds and never refused.
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* ---- the mark */
static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CLOUDNINE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_CLOUDNINE], DFI_HANDLER_NONE); /* an engine row: read by id */
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_CLOUDNINE].family, DFI_ABILITY_FAMILY_NONE);
}

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

/* ---- Mega Sol under Cloud Nine: the steps of g59_mega_sol (step 0 is the team selection), with a foe that holds Cloud Nine
 * from the step `cn_before` on (NO_CHANGE: as recorded). */
#define MS_SOLAR_STEP 2u
#define NO_CHANGE 0xffffffffu

static duoforge_status play_cn_mega_sol(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t cn_before)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_status status = DUOFORGE_OK;
    for (uint32_t si = 0; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        if (si == cn_before) {
            /* the foe's lead (side 1, position 0) holds Cloud Nine: it is active, so the weather is suppressed */
            const uint32_t occ = b->sides[1].positions[0].occupant;
            b->tail.sides[1].ability_now[occ] = (uint16_t)(1u + DFI_ABILITY_CLOUDNINE);
        }
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (status != DUOFORGE_OK) {
            break;
        }
    }
    duoforge_battle_destroy(b);
    return status;
}

static void check_mega_sol_cloud_nine(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g59_mega_sol");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > MS_SOLAR_STEP)) {
        duoforge_context_destroy(ctx);
        return;
    }
    /* as recorded: Solar Beam takes no charge turn in the sun */
    DF_CHECK_EQ_U64(t, play_cn_mega_sol(t, ctx, cb, NO_CHANGE), DUOFORGE_OK);
    /* a foe with Cloud Nine suppresses the sun for everything but Mega Sol's own reading; the Mega Sol user's Solar Beam reads
     * the suppressed field, which is not modelled (the -activate line), so the step is refused */
    DF_CHECK_EQ_U64(t, play_cn_mega_sol(t, ctx, cb, MS_SOLAR_STEP), DUOFORGE_E_UNSUPPORTED);
    duoforge_context_destroy(ctx);
}

/* ---- Trace copying Cloud Nine: the recorded battle g79_cloud_nine_skill_swap, its Gardevoir (member 1, Telepathy as recorded)
 * set to Trace, and the first step (the team selection and the switch-ins) stepped on a seed of the battle's own generator. */
#define TRACE_SEEDS 16u

/* Plays the first step; `holds_cn` says whether the side's own lead holds a copied Cloud Nine after a successful step. */
static duoforge_status play_trace_lead(duoforge_context *ctx, const df_conf_battle *cb, uint64_t seed, bool trace, bool *holds_cn)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    setup.rng_initstate = seed;
    if (trace) {
        setup.sides[0].members[1].ability = 1u + DFI_ABILITY_TRACE;
    }
    duoforge_battle *b = NULL;
    if (duoforge_battle_create(ctx, &setup, &b) != DUOFORGE_OK || b == NULL) {
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[0], b, &bd);
    duoforge_step_result res;
    const duoforge_status status = duoforge_battle_step(ctx, b, &bd, &res);
    *holds_cn = false;
    for (uint32_t k = 0u; k < 2u; ++k) {
        const uint32_t occ = b->sides[0].positions[k].occupant;
        if (b->tail.sides[0].ability_now[occ] == 1u + DFI_ABILITY_CLOUDNINE) {
            *holds_cn = true;
        }
    }
    duoforge_battle_destroy(b);
    return status;
}

static void check_trace_cloud_nine(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g79_cloud_nine_skill_swap");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 0u)) {
        duoforge_context_destroy(ctx);
        return;
    }
    /* control: the recorded Telepathy lead plays every seed */
    for (uint64_t seed = 1u; seed <= TRACE_SEEDS; ++seed) {
        bool holds = true;
        DF_CHECK_EQ_U64(t, play_trace_lead(ctx, cb, seed, false, &holds), DUOFORGE_OK);
        DF_CHECK(t, !holds);
    }
    /* Trace draws one of the two standing foes (Altaria, Cloud Nine, or Incineroar): the step that copies Cloud Nine is refused,
     * every other is played, and no played step ends with a copied Cloud Nine */
    uint32_t refused = 0u;
    uint32_t played = 0u;
    for (uint64_t seed = 1u; seed <= TRACE_SEEDS; ++seed) {
        bool holds = false;
        const duoforge_status status = play_trace_lead(ctx, cb, seed, true, &holds);
        if (status == DUOFORGE_E_UNSUPPORTED) {
            refused += 1u;
        } else {
            DF_CHECK_EQ_U64(t, status, DUOFORGE_OK);
            DF_CHECK(t, !holds);
            played += 1u;
        }
    }
    DF_CHECK(t, refused > 0u);
    DF_CHECK(t, played > 0u);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g79");
    check_facts(&t);
    check_mega_sol_cloud_nine(&t);
    check_trace_cloud_nine(&t);
    return df_test_end(&t);
}
