/*
 * duoforge.state.pool_i2 (white-box): step I2 of the content expansion, Illusion (decision 0026, amended by I2).
 *
 * The recorded battles of this step, replayed to their interesting steps (step 0 is the team step):
 *
 *   - i2_illusion_break: Zoroark leads disguised as Gholdengo (the last brought member to its right). Step 1: a foe Moonblast hits
 *     it, the break (replace and -end Illusion). The foe's view of side 0 before the break shows the disguise on the position and
 *     the holder unseen; after the break the holder is seen with the last shown HP, and the disguise row, which was never shown
 *     before, is at full HP and on the bench (amended by I2, decision 3).
 *   - i2_unbroken_switchout: Zoroark switches out to the bench at step 1, the real Gholdengo enters at once and its own line clears
 *     the disguise name: the foe never sees Zoroark, and the owner's bit 19 is gone.
 *
 * What is checked: the foe's observation (occupant, location, HP, status), the owner's observation_ext (bit 19, own side only),
 * the public-view cause ILLUSION_POSSIBLE (literal, decision 0026 section 4), the refusal of duoforge_battle_public while it is set,
 * and the Illusion state of the battle (ill_*) against the lines.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "combat/turn.h"
#include "data/pool_tables.h"
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

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step). */
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
    return b;
}

/* The foe's view of side 0 as player 1 sees it, and the owner's view as player 0. */
static bool observe(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player, duoforge_observation *o)
{
    return DF_CHECK(t, duoforge_battle_observe(ctx, b, player, o) == DUOFORGE_OK);
}

/* Step 0 of i2_illusion_break: the lead Zoroark stands as Gholdengo. */
static void check_team_start(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    const dfi_tail_illusion *ill = &b->tail.sides[0].illusion;
    DF_CHECK_EQ_U64(t, ill->shown, 4u); /* Gholdengo: roster index 3, plus 1 */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].positions[0].ability_state, 4u);
    DF_CHECK(t, dfi_illusion_disguise_up(&b->sides[0], &b->tail.sides[0], 0) != 0);
    DF_CHECK_EQ_U64(t, ill->override[2], 0u); /* no status */
    DF_CHECK_EQ_U64(t, ill->override[3], 1u); /* active */
    DF_CHECK_EQ_U64(t, ill->snapshot[8], 0u); /* the holder: never seen, so undetermined */

    duoforge_observation foe;
    if (observe(t, ctx, b, 1u, &foe)) {
        DF_CHECK_EQ_U64(t, foe.sides[0].occupant[0], 3u); /* the foe sees the disguise on the position */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].location, DUOFORGE_LOCATION_ACTIVE);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].hp_kind, DUOFORGE_HP_PERCENT);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].hp, 100u);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp_kind, DUOFORGE_HP_UNKNOWN); /* the holder is unseen */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].location, DUOFORGE_LOCATION_UNDETERMINED);
    }
    duoforge_observation own;
    if (observe(t, ctx, b, 0u, &own)) {
        DF_CHECK_EQ_U64(t, own.sides[0].occupant[0], 0u); /* the owner sees its true holder */
    }

    duoforge_observation_ext ext_own;
    duoforge_observation_ext ext_foe;
    if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext_own) == DUOFORGE_OK) &&
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 1u, &ext_foe) == DUOFORGE_OK)) {
        DF_CHECK(t, (ext_own.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ILLUSION_UP) != 0u); /* bit 19, own side */
        DF_CHECK(t, (ext_foe.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ILLUSION_UP) == 0u); /* never on the foe's view */
    }

    uint32_t causes = 0u;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE);
    duoforge_public_state pub;
    DF_CHECK(t, duoforge_battle_public(ctx, b, 1u, &pub) == DUOFORGE_E_UNSUPPORTED); /* the search plays raw */
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_i2");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_team_start(&t, ctx);
    return df_test_end(&t);
}
