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
#include <duoforge/duoforge_encode.h>
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

static bool dfi_bytes_zero_i2(const void *p, size_t n)
{
    const uint8_t *q = (const uint8_t *)p;
    for (size_t i = 0u; i < n; ++i) {
        if (q[i] != 0u) {
            return false;
        }
    }
    return true;
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

/* Step 1 of i2_illusion_break: the foe's Moonblast breaks the disguise; the holder is seen with the last shown HP, and the disguise
 * row, never shown before, is at full HP on the bench (decision 0026 section 4, amended by I2). */
static void check_break(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 2u);
    if (b == NULL) {
        return;
    }
    const dfi_tail_illusion *ill = &b->tail.sides[0].illusion;
    DF_CHECK(t, dfi_bytes_zero_i2(ill, sizeof *ill)); /* the break clears every ill_* field */
    duoforge_observation foe;
    if (observe(t, ctx, b, 1u, &foe)) {
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp_kind, DUOFORGE_HP_PERCENT); /* the holder is seen now */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp, 1u); /* the last shown value under the disguise name: 1% */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].location, DUOFORGE_LOCATION_ACTIVE); /* the holder stays on the field (Shadow Ball) */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].hp, 100u); /* decision 3: never shown, so full HP */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].location, DUOFORGE_LOCATION_BENCH);
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].hp_kind, DUOFORGE_HP_PERCENT);
    }
    uint32_t causes = 0u;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, 0u); /* the holder is shown on the field under its own name */
    duoforge_battle_destroy(b);
}

/* Step 1 of i2_unbroken_switchout: the holder leaves unbroken and the real Gholdengo's own line clears the disguise name. */
static void check_unbroken(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_unbroken_switchout", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK(t, dfi_bytes_zero_i2(&b->tail.sides[0].illusion, sizeof b->tail.sides[0].illusion)); /* the real line cleared it */
    duoforge_observation_ext ext;
    if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 0u, &ext) == DUOFORGE_OK)) {
        DF_CHECK(t, (ext.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_ILLUSION_UP) == 0u);
    }
    duoforge_observation foe;
    if (observe(t, ctx, b, 1u, &foe)) {
        DF_CHECK_EQ_U64(t, foe.sides[0].members[0].hp_kind, DUOFORGE_HP_UNKNOWN); /* the foe never sees Zoroark */
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].location, DUOFORGE_LOCATION_ACTIVE);
    }
    duoforge_battle_destroy(b);
}

/* Information safety (decision 0026, lead point 1c): A is the disguised holder at team start, shown as Gholdengo; B is the real Gholdengo
 * entering after the holder left unbroken (i2_unbroken_switchout, step 1). The foe was shown the same lines for side 0 (Gholdengo at 100%
 * on the field, the holder never shown), so the foe's view of side 0, the public refusal and the cause mask must be equal, although
 * the truth differs (the holder is on the field in A only). Compared: the occupants, the rows of the four Pokemon side 0 shows (HP,
 * location, status) and the position volatiles, not the turn (A is the team step, B a later one). */
static void check_ab_info_safety(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *a = replay(t, ctx, "i2_illusion_break", 1u);
    duoforge_battle *b = replay(t, ctx, "i2_unbroken_switchout", 2u);
    if (a == NULL || b == NULL) {
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_observation fa;
    duoforge_observation fb;
    if (observe(t, ctx, a, 1u, &fa) && observe(t, ctx, b, 1u, &fb)) {
        DF_CHECK_EQ_U64(t, fa.sides[0].occupant[0], fb.sides[0].occupant[0]);
        DF_CHECK_EQ_U64(t, fa.sides[0].occupant[1], fb.sides[0].occupant[1]);
        for (uint32_t m = 0u; m < 4u; ++m) {
            const duoforge_member_view *ma = &fa.sides[0].members[m];
            const duoforge_member_view *mb = &fb.sides[0].members[m];
            DF_CHECK_EQ_U64(t, ma->hp_kind, mb->hp_kind);
            DF_CHECK_EQ_U64(t, ma->hp, mb->hp);
            DF_CHECK_EQ_U64(t, ma->location, mb->location);
            DF_CHECK_EQ_U64(t, ma->status, mb->status);
        }
    }
    duoforge_observation_ext ea;
    duoforge_observation_ext eb;
    if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, a, 1u, &ea) == DUOFORGE_OK) &&
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, 1u, &eb) == DUOFORGE_OK)) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            DF_CHECK_EQ_U64(t, ea.sides[0].positions[p].volatiles, eb.sides[0].positions[p].volatiles); /* bit 19 is off for the foe in both */
        }
    }
    uint32_t ca = 0u;
    uint32_t cb = 0u;
    if (DF_CHECK(t, duoforge_battle_public_causes(ctx, a, 1u, &ca) == DUOFORGE_OK) &&
        DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &cb) == DUOFORGE_OK)) {
        DF_CHECK_EQ_U64(t, ca, cb);
    }
    duoforge_public_state pa;
    duoforge_public_state pb;
    DF_CHECK_EQ_U64(t, duoforge_battle_public(ctx, a, 1u, &pa), duoforge_battle_public(ctx, b, 1u, &pb));
    duoforge_battle_destroy(a);
    duoforge_battle_destroy(b);
}

/* Encoders 1 to 4 refuse a battle with an Illusion member on either sheet (decision 0026 section 4, amended by I2, point (b)); encoder 5
 * does not. The refusal is the first check of the encoder, before the domain is read: the observation alone decides it. */
static void check_encoder_refusal(df_test *t)
{
    static float obs[850];
    static float slots[DUOFORGE_ENCODER_SLOT_VALUES];
    static uint8_t pairs[DUOFORGE_ENCODER_PAIR_VALUES];
    duoforge_factored_domain dom;
    memset(&dom, 0, sizeof dom);
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t with = 0u; with < 2u; ++with) {
            duoforge_observation ob;
            memset(&ob, 0, sizeof ob);
            ob.player = 0u;
            ob.sides[side].member_count = 1u;
            ob.sides[side].members[0].ability = with != 0u ? (uint8_t)(DFI_ABILITY_ILLUSION + 1u) : 0u;
            for (uint32_t v = 4u; v <= 5u; ++v) {
                const duoforge_status st = duoforge_encode(v, 0u, &ob, &dom, NULL, obs, slots, pairs);
                if (v == 4u && with != 0u) {
                    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
                } else if (v == 4u) {
                    DF_CHECK(t, st != DUOFORGE_E_UNSUPPORTED);
                } else {
                    DF_CHECK(t, st != DUOFORGE_E_UNSUPPORTED); /* encoder 5 has no refusal for Illusion */
                }
            }
        }
    }
}

/* M5 (decision 0026 section 4, amended by I2): the disguise row shows the status the lines showed on the name (ill_override), not the
 * disguise member's own state. Here the true Gholdengo is burned while the shown status is none; the foe must see none. */
static void check_disguise_status(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    b->sides[0].members[3].status = DFI_STATUS_BRN; /* the truth of the shown member; the foe was never shown it */
    duoforge_observation foe;
    if (observe(t, ctx, b, 1u, &foe)) {
        DF_CHECK_EQ_U64(t, foe.sides[0].members[3].status, DUOFORGE_AILMENT_NONE);
    }
    duoforge_battle_destroy(b);
}

/* M6 (decision 0026 section 4, amended by I2, point (a)): a holder the viewer has seen fainted under its own name is not a possible
 * disguise, whether or not it is on the field. Here the holder is benched and unseen in the unbroken battle; the foe's knowledge of it
 * is set to fainted (white-box), and ILLUSION_POSSIBLE must be clear. */
static void check_possible_fainted(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_unbroken_switchout", 2u);
    if (b == NULL) {
        return;
    }
    b->sides[1].seen_mask = (uint8_t)(b->sides[1].seen_mask | 1u);
    b->sides[1].knowledge[0].hp_percent = 0u;
    b->sides[1].knowledge[0].hp_flag = 0u;
    uint32_t causes = 0u;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, 0u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_i2");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_team_start(&t, ctx);
    check_break(&t, ctx);
    check_unbroken(&t, ctx);
    check_ab_info_safety(&t, ctx);
    check_encoder_refusal(&t);
    check_disguise_status(&t, ctx);
    check_possible_fainted(&t, ctx);
    return df_test_end(&t);
}
