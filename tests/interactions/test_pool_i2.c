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

#include "combat/events.h"
#include "codec/state_codec.h"
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "rng/pcg32.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/knowledge.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_compare.h"
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
    static float obs[1152]; /* at least the widest encoder's obs (duoforge_encoder_size; encoder 6 is 1094 wide) */
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
                uint32_t width = 0u;
                if (!DF_CHECK(t, duoforge_encoder_size(v, &width) == DUOFORGE_OK && width <= sizeof obs / sizeof obs[0])) {
                    continue; /* never encode past the buffer */
                }
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

/* A disguise up always has its name shown (one name per side). Without the name (shown and override zero, the disguise still up), the
 * state is invalid: the campaign showed such a state after the holder re-entered beside its own disguise name (fz_9730000_74). */
static void check_disguise_needs_name(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    uint32_t causes = 0u;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_OK); /* the real state is valid */
    b->tail.sides[0].illusion.shown = 0u;
    memset(b->tail.sides[0].illusion.override, 0, sizeof b->tail.sides[0].illusion.override);
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_E_INVARIANT);
    duoforge_battle_destroy(b);
}

/* The foe's knowledge of a disguised holder (decision 0026 section 4, the I2 amendment; invariants.c dfi_knowledge_valid): the
 * holder's own row is frozen at what the foe knew before the disguise, so it is exempt from the current HP check; the disguise
 * row and ill_override mirror the holder's current HP display. Three cases on the disguise of i2_illusion_break at step 1, with the
 * holder at 80 percent and its own row frozen at 100 percent:
 *   (a) the disguise row and ill_override mirror the holder: a valid state;
 *   (b) the disguise row shows another HP than the holder: refused, E_INVARIANT;
 *   (c) an undisguised occupant (side 1's, with a wrong HP) is still refused. */
static void check_knowledge_disguise(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    uint32_t pos = DUOFORGE_ACTIVE_PER_SIDE;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (dfi_illusion_disguise_up(&b->sides[0], &b->tail.sides[0], p)) {
            pos = p;
        }
    }
    if (!DF_CHECK(t, pos < DUOFORGE_ACTIVE_PER_SIDE && b->tail.sides[0].illusion.shown != 0u)) {
        duoforge_battle_destroy(b);
        return;
    }
    const uint32_t holder = b->sides[0].positions[pos].occupant;
    const uint32_t disguise = (uint32_t)b->tail.sides[0].illusion.shown - 1u;
    dfi_member *hm = &b->sides[0].members[holder];
    hm->hp = (uint16_t)((hm->hp_max * 4u) / 5u); /* 80 percent: the truth */
    uint8_t pct = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(hm->hp, hm->hp_max, &pct, &flag);
    /* The foe's knowledge: the holder frozen at 100 percent (its row before the disguise), the disguise row and ill_override at the
     * holder's current display. */
    b->sides[1].seen_mask = (uint8_t)(b->sides[1].seen_mask | (1u << holder) | (1u << disguise));
    b->sides[1].knowledge[holder].hp_percent = 100u;
    b->sides[1].knowledge[holder].hp_flag = 0u;
    b->sides[1].knowledge[disguise].hp_percent = pct;
    b->sides[1].knowledge[disguise].hp_flag = flag;
    b->tail.sides[0].illusion.override[0] = pct;
    b->tail.sides[0].illusion.override[1] = flag;
    uint32_t causes = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 1u, &causes), DUOFORGE_OK); /* (a) */

    b->sides[1].knowledge[disguise].hp_percent = 100u; /* (b): the disguise row shows another HP */
    b->sides[1].knowledge[disguise].hp_flag = 0u;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 1u, &causes), DUOFORGE_E_INVARIANT);
    b->sides[1].knowledge[disguise].hp_percent = pct;
    b->sides[1].knowledge[disguise].hp_flag = flag;

    const uint32_t foe = b->sides[1].positions[0].occupant; /* (c): an undisguised occupant of side 1 */
    const dfi_member *fm = &b->sides[1].members[foe];
    uint8_t tpct = 0u;
    uint8_t tflag = 0u;
    dfi_hp_display(fm->hp, fm->hp_max, &tpct, &tflag);
    uint8_t fpct = 0u;
    uint8_t fflag = 0u;
    dfi_hp_display(fm->hp_max / 2u, fm->hp_max, &fpct, &fflag); /* a wrong HP for the occupant (its truth is not half) */
    if (!DF_CHECK(t, fpct != tpct || fflag != tflag)) {
        duoforge_battle_destroy(b);
        return;
    }
    b->sides[0].knowledge[foe].hp_percent = fpct;
    b->sides[0].knowledge[foe].hp_flag = fflag;
    DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 0u, &causes), DUOFORGE_E_INVARIANT);
    duoforge_battle_destroy(b);
}

/* The faint of a disguised holder (decision 0026 section 4, amended by I2): the faint drops the disguise (the tail ends with the
 * occupant) and the faint line names the disguise, so the foe shows the shown name fainted on the position while the holder stands
 * there. The holder's own row stays as the foe knew it (frozen, possibly never seen). White-box: the state the fold leaves after a
 * faint of Zoroark at position 0 under the name Gholdengo (i2_illusion_break, step 1). Two cases: the foe had seen the holder at 100%
 * (its row is frozen at that value), and the foe never saw it (the shown name is the seen member). */
static void check_faint_held(df_test *t, const duoforge_context *ctx)
{
    for (uint32_t seen = 0u; seen < 2u; ++seen) {
        duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
        if (b == NULL) {
            return;
        }
        b->tail.sides[0].positions[0].ability_state = 0u; /* the faint drops the disguise (dfi_process_faints) */
        b->sides[0].members[0].hp = 0u;                   /* the holder fainted */
        dfi_tail_illusion *ill = &b->tail.sides[0].illusion;
        memset(ill->snapshot, 0, 7u); /* the fold: the disguise row's snapshot and the pending counts go */
        memset(ill->pending, 0, sizeof ill->pending);
        ill->override[2] = 0u;
        ill->override[3] = 2u; /* fainted, not active */
        uint8_t pct = 0u;
        uint8_t flag = 0u;
        dfi_hp_display(0u, b->sides[0].members[3].hp_max, &pct, &flag);
        b->sides[1].knowledge[3].hp_percent = pct; /* the disguise row: fainted, as the fold shows it */
        b->sides[1].knowledge[3].hp_flag = flag;
        if (seen != 0u) {
            b->sides[1].seen_mask = (uint8_t)(b->sides[1].seen_mask | 1u);
            b->sides[1].knowledge[0].hp_percent = 100u; /* the holder's row, as the foe knew it before the disguise */
            b->sides[1].knowledge[0].hp_flag = 0u;
        }
        duoforge_observation foe;
        if (observe(t, ctx, b, 1u, &foe)) {
            DF_CHECK_EQ_U64(t, foe.sides[0].occupant[0], 3u); /* the foe sees the shown name on the position, not the holder */
        }
        uint32_t causes = 0u;
        DF_CHECK_EQ_U64(t, duoforge_battle_public_causes(ctx, b, 1u, &causes), DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE);
        duoforge_battle_destroy(b);
    }
}

/* One boundary of side 0 with a SWITCH of `reserve` into position `slot`, run on a copy of the battle the way request.c runs a boundary
 * (the copy is discarded: a refusal changes nothing, and a success is not committed here). */
static duoforge_status replacement_switch(const duoforge_context *ctx, const duoforge_battle *b, uint32_t slot, uint32_t reserve)
{
    struct duoforge_battle tmp = *b;
    tmp.boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    tmp.request_mask = 1u; /* side 0 only */
    tmp.sides[0].requested_slots = (uint8_t)(1u << slot);
    duoforge_side_choice responses[DUOFORGE_SIDE_COUNT];
    memset(responses, 0, sizeof responses);
    responses[0].side = 0u;
    responses[0].kind = DUOFORGE_CHOICE_SLOTS;
    responses[0].slots[slot].kind = DUOFORGE_SLOT_SWITCH;
    responses[0].slots[slot].reserve = (uint8_t)reserve;
    dfi_events events;
    memset(&events, 0, sizeof events);
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    draws.tape = NULL;
    draws.tape_len = 0u;
    return dfi_turn_run(ctx, &tmp, responses, &draws, &events);
}

/* M9 (decision 0026 section 3, amended by I2: one shown name per side): while the holder stands disguised as a name on position 0,
 * the member of that name entering on position 1 would show the name twice. Refused E_UNSUPPORTED at its switch-in, before any change.
 * White-box: i2_illusion_break at step 1 (Zoroark at position 0 disguised as roster 3, the name shown), roster 3 switching into
 * position 1 in place of roster 1. The negative control is a member that is not the shown name entering the same position: not refused. */
static void check_one_name_switch_in(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    if (!DF_CHECK(t, b->tail.sides[0].illusion.shown == 4u && b->tail.sides[0].positions[0].ability_state == 4u)) {
        duoforge_battle_destroy(b);
        return;
    }
    DF_CHECK_EQ_U64(t, replacement_switch(ctx, b, 1u, 3u), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.shown, 4u); /* the refused switch changed nothing (the copy was discarded) */
    DF_CHECK(t, replacement_switch(ctx, b, 1u, 2u) != DUOFORGE_E_UNSUPPORTED);
    duoforge_battle_destroy(b);
}

/* The clear of a holder fainted under its shown name (decision 0026 section 4, amended by I2; option B: the view must not read the
 * holder's true state). The real disguise member (roster 3) entering on the holder's fainted position while the foe still shows the
 * faint under its name is refused E_UNSUPPORTED at the switch-in, before any change. White-box: the state of check_faint_held (Zoroark
 * fainted at position 0 under the name of roster 3, the disguise dropped, i2_illusion_break step 1), with the foe having seen the
 * holder at 100 percent or never. Negative control: the same entry on a live holder (its unbroken switch-out) is not this case. */
static void check_faint_clear(df_test *t, const duoforge_context *ctx)
{
    for (uint32_t seen = 0u; seen < 2u; ++seen) {
        duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
        if (b == NULL) {
            return;
        }
        b->tail.sides[0].positions[0].ability_state = 0u;
        b->sides[0].members[0].hp = 0u;
        dfi_tail_illusion *ill = &b->tail.sides[0].illusion;
        memset(ill->snapshot, 0, 7u);
        memset(ill->pending, 0, sizeof ill->pending);
        ill->override[2] = 0u;
        ill->override[3] = 2u;
        uint8_t pct = 0u;
        uint8_t flag = 0u;
        dfi_hp_display(0u, b->sides[0].members[3].hp_max, &pct, &flag);
        b->sides[1].knowledge[3].hp_percent = pct;
        b->sides[1].knowledge[3].hp_flag = flag;
        if (seen != 0u) {
            b->sides[1].seen_mask = (uint8_t)(b->sides[1].seen_mask | 1u);
            b->sides[1].knowledge[0].hp_percent = 100u;
            b->sides[1].knowledge[0].hp_flag = 0u;
        }
        DF_CHECK_EQ_U64(t, replacement_switch(ctx, b, 0u, 3u), DUOFORGE_E_UNSUPPORTED);
        DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.shown, 4u);
        DF_CHECK_EQ_U64(t, b->sides[0].positions[0].occupant, 0u);
        /* The holder benched after its faint (its replacement took the position, the name stays: the campaign's fz_130): the name's
         * member entering on the other position is refused too. The holder moves to position 1; roster 1 stands on position 0. */
        b->sides[0].positions[0].occupant = 1u;
        b->sides[0].positions[1].occupant = 0u;
        DF_CHECK_EQ_U64(t, replacement_switch(ctx, b, 0u, 3u), DUOFORGE_E_UNSUPPORTED);
        DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.shown, 4u);
        duoforge_battle_destroy(b);
    }
    duoforge_battle *live = replay(t, ctx, "i2_illusion_break", 1u);
    if (live != NULL) {
        DF_CHECK(t, replacement_switch(ctx, live, 0u, 3u) != DUOFORGE_E_UNSUPPORTED); /* the holder alive: its unbroken switch-out */
        duoforge_battle_destroy(live);
    }
}

/* A replacement boundary of side 0 with a SWITCH of reserve[slot] into every position of `mask`, run on a copy of the battle as
 * replacement_switch runs one (the copy is discarded). `events` gets the step's events. */
static duoforge_status replacement_switches(const duoforge_context *ctx, const duoforge_battle *b, uint32_t mask,
                                            const uint32_t reserve[DUOFORGE_ACTIVE_PER_SIDE], dfi_events *events)
{
    struct duoforge_battle tmp = *b;
    tmp.boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_REPLACEMENT;
    tmp.request_mask = 1u; /* side 0 only */
    tmp.sides[0].requested_slots = (uint8_t)mask;
    duoforge_side_choice responses[DUOFORGE_SIDE_COUNT];
    memset(responses, 0, sizeof responses);
    responses[0].side = 0u;
    responses[0].kind = DUOFORGE_CHOICE_SLOTS;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        if ((mask >> slot & 1u) != 0u) {
            responses[0].slots[slot].kind = DUOFORGE_SLOT_SWITCH;
            responses[0].slots[slot].reserve = (uint8_t)reserve[slot];
        }
    }
    memset(events, 0, sizeof *events);
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    draws.tape = NULL;
    draws.tape_len = 0u;
    return dfi_turn_run(ctx, &tmp, responses, &draws, events);
}

/* The SWITCH events of `events` that bring roster `reserve` in. */
static uint32_t switches_of(const dfi_events *events, uint32_t reserve)
{
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < events->count; ++i) {
        n += events->rec[i].kind == DUOFORGE_EVENT_SWITCH && events->rec[i].id == reserve ? 1u : 0u;
    }
    return n;
}

/* Issue 602 (decision 0026 section 4, amended by I2, lead decision A: the duplicate name). White-box: i2_illusion_break at team start,
 * made into the double replacement of the campaign's fz_4301_17 (its step 4): both actives of side 0 fainted (the two brought members
 * that are neither Zoroark, roster 0, nor Gholdengo, roster 3), Zoroark and Gholdengo on the bench in that party order, no name shown.
 * Both positions are replaced in one step. The two switches run in the order of the speed of the fainted members they replace (the
 * action's Pokemon, dfi_key_of), set here, so each order is pinned:
 *   - Zoroark first, disguised as Gholdengo (the last standing member to its right), then Gholdengo into the other position, which
 *     would show its name twice: refused E_UNSUPPORTED at Gholdengo's switch-in, before its SWITCH event. The old check compared with
 *     the shown name, which the fold writes only at the end of the step, so it let this through (E_INVARIANT at the end of the step).
 *     Pinned for both position pairs.
 *   - Gholdengo first, then Zoroark: its disguise would be the other active, refused at Zoroark's switch-in (the check before this fix).
 * Negative controls, the legal switch-ins: Gholdengo first into position 0, then Zoroark into position 1 (the bench to its right holds
 * only fainted members: no disguise, in one step); Zoroark alone into a fainted position (its disguise stays on the bench); Gholdengo
 * alone next to a Zoroark whose disguise is broken (i2_illusion_break replayed through its step 1, the break); and Gholdengo into the
 * disguised Zoroark's own position (its unbroken switch-out). */
static void check_double_replacement(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    dfi_side *sd = &b->sides[0];
    uint32_t others[2] = {DUOFORGE_MAX_ROSTER, DUOFORGE_MAX_ROSTER};
    uint32_t n_others = 0u;
    for (uint32_t m = 0u; m < sd->member_count; ++m) {
        if (((uint32_t)sd->brought_mask >> m & 1u) != 0u && m != 0u && m != 3u && n_others < 2u) {
            others[n_others++] = m;
        }
    }
    if (!DF_CHECK(t, n_others == 2u && ((uint32_t)sd->brought_mask >> 3u & 1u) != 0u)) {
        duoforge_battle_destroy(b);
        return;
    }
    sd->positions[0].occupant = (uint8_t)others[0]; /* wide-operands-reviewed: a roster index */
    sd->positions[1].occupant = (uint8_t)others[1]; /* wide-operands-reviewed: a roster index */
    sd->members[others[0]].hp = 0u;
    sd->members[others[1]].hp = 0u;
    dfi_party_put(&b->tail, 0u, 0u, others[0] + 1u);
    dfi_party_put(&b->tail, 0u, 1u, others[1] + 1u);
    dfi_party_put(&b->tail, 0u, 2u, 1u); /* Zoroark */
    dfi_party_put(&b->tail, 0u, 3u, 4u); /* Gholdengo, to its right */
    b->tail.sides[0].positions[0].ability_state = 0u;
    b->tail.sides[0].positions[1].ability_state = 0u;
    memset(&b->tail.sides[0].illusion, 0, sizeof b->tail.sides[0].illusion);
    struct duoforge_battle first0 = *b; /* position 0 is replaced first */
    first0.sides[0].members[others[0]].stats[4] = 200u;
    first0.sides[0].members[others[1]].stats[4] = 100u;
    struct duoforge_battle first1 = *b; /* position 1 is replaced first */
    first1.sides[0].members[others[0]].stats[4] = 100u;
    first1.sides[0].members[others[1]].stats[4] = 200u;
    duoforge_battle_destroy(b);

    dfi_events ev;
    const uint32_t zoroark_a[2] = {0u, 3u}; /* Zoroark into position 0, Gholdengo into position 1 */
    const uint32_t zoroark_b[2] = {3u, 0u}; /* Gholdengo into position 0, Zoroark into position 1 */
    DF_CHECK_EQ_U64(t, replacement_switches(ctx, &first0, 3u, zoroark_a, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, ev.count != 0u && ev.rec[0].kind == DUOFORGE_EVENT_SWITCH && ev.rec[0].id == 0u && ev.rec[0].reserved[0] == 4u);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 0u), 1u); /* Zoroark entered, disguised as Gholdengo (roster 3 + 1) */
    DF_CHECK_EQ_U64(t, switches_of(&ev, 3u), 0u); /* refused before Gholdengo's SWITCH */
    DF_CHECK_EQ_U64(t, replacement_switches(ctx, &first1, 3u, zoroark_b, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, ev.count != 0u && ev.rec[0].kind == DUOFORGE_EVENT_SWITCH && ev.rec[0].id == 0u && ev.rec[0].reserved[0] == 4u);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 0u), 1u);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 3u), 0u);
    DF_CHECK_EQ_U64(t, replacement_switches(ctx, &first1, 3u, zoroark_a, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 3u), 1u); /* Gholdengo entered first */
    DF_CHECK_EQ_U64(t, switches_of(&ev, 0u), 0u); /* refused at Zoroark's switch-in */

    /* Negative control: Gholdengo first into position 0, Zoroark into position 1 with only fainted members to its right: no disguise,
     * one name on the field. */
    DF_CHECK_EQ_U64(t, replacement_switches(ctx, &first0, 3u, zoroark_b, &ev), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 3u), 1u);
    DF_CHECK_EQ_U64(t, switches_of(&ev, 0u), 1u);
    /* Negative control: Zoroark alone into position 0, the member on position 1 standing again: the disguise is Gholdengo on the
     * bench. */
    struct duoforge_battle single = first0;
    single.sides[0].members[others[1]].hp = single.sides[0].members[others[1]].hp_max;
    DF_CHECK_EQ_U64(t, replacement_switches(ctx, &single, 1u, zoroark_a, &ev), DUOFORGE_OK);
    DF_CHECK(t, ev.count != 0u && ev.rec[0].kind == DUOFORGE_EVENT_SWITCH && ev.rec[0].id == 0u && ev.rec[0].reserved[0] == 4u);

    /* Negative control: the disguise broken (i2_illusion_break through its step 1, Moonblast: Zoroark on position 0 under its own
     * name), Gholdengo into position 1 shows no name twice. */
    duoforge_battle *broken = replay(t, ctx, "i2_illusion_break", 2u);
    if (broken != NULL) {
        DF_CHECK_EQ_U64(t, broken->tail.sides[0].positions[0].ability_state, 0u);
        DF_CHECK_EQ_U64(t, replacement_switch(ctx, broken, 1u, 3u), DUOFORGE_OK);
        duoforge_battle_destroy(broken);
    }
    /* Negative control: Gholdengo into the disguised Zoroark's own position (its unbroken switch-out): not the duplicate. */
    duoforge_battle *live = replay(t, ctx, "i2_illusion_break", 1u);
    if (live != NULL) {
        DF_CHECK_EQ_U64(t, replacement_switch(ctx, live, 0u, 3u), DUOFORGE_OK);
        duoforge_battle_destroy(live);
    }
}

/* Issue 619: one turn of the state built by check_faint_drag, on a copy with the generator seeded by `seed`, the way request.c runs a
 * step: dfi_turn_run, then (when `full`) the knowledge fold and the state invariants. Side 0: Milotic (position 0) uses Scald on the
 * foe's Primarina, which holds Red Card, and Primarina (position 1) switches to Zoroark. Side 1: Primarina uses Calm Mind, Staraptor
 * Brave Bird on position 1 when `hit`, Protect otherwise. `events` gets the step's events (a caller may put earlier ones in first:
 * `keep`). */
static duoforge_status faint_drag_turn(const duoforge_context *ctx, const duoforge_battle *b, uint64_t seed, bool hit, bool full,
                                       bool keep, dfi_events *events)
{
    struct duoforge_battle tmp = *b;
    dfi_rng_seed(&tmp.rng, seed, 54u);
    duoforge_side_choice responses[DUOFORGE_SIDE_COUNT];
    memset(responses, 0, sizeof responses);
    responses[0].side = 0u;
    responses[0].kind = DUOFORGE_CHOICE_SLOTS;
    responses[0].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 1u, 2u, 0u, 0u, {0u, 0u, 0u}}; /* Scald -> p2a */
    responses[0].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 0u, {0u, 0u, 0u}}; /* Zoroark */
    responses[1].side = 1u;
    responses[1].kind = DUOFORGE_CHOICE_SLOTS;
    responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 2u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}}; /* Calm Mind */
    responses[1].slots[1] = hit ? (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 2u, 1u, 0u, 0u, {0u, 0u, 0u}}   /* Brave Bird -> p1b */
                                : (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 3u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}}; /* Protect */
    if (!keep) {
        memset(events, 0, sizeof *events);
    }
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    const duoforge_status st = dfi_turn_run(ctx, &tmp, responses, &draws, events);
    if (st != DUOFORGE_OK || !full) {
        return st;
    }
    if (!dfi_events_fold_knowledge(b, &tmp, events, 0u)) {
        fprintf(stderr, "  faint_drag_turn seed %llu: the fold failed\n", (unsigned long long)seed);
        return DUOFORGE_E_INVARIANT;
    }
    dfi_invariant first = DFI_INV_NONE;
    if (dfi_state_check(ctx, &tmp, &first) != DUOFORGE_OK) {
        fprintf(stderr, "  faint_drag_turn seed %llu: invariant %u\n", (unsigned long long)seed, (unsigned)first);
        return DUOFORGE_E_INVARIANT;
    }
    return DUOFORGE_OK;
}

/* The roster index that the Red Card drag of `events` brings into position 0 of side 0, DUOFORGE_MAX_ROSTER for none. */
static uint32_t dragged_in(const dfi_events *events)
{
    for (uint32_t i = 0u; i < events->count; ++i) {
        if (events->rec[i].kind == DUOFORGE_EVENT_DRAG && events->rec[i].position == 0u) {
            return events->rec[i].id;
        }
    }
    return DUOFORGE_MAX_ROSTER;
}

/* The count of `kind` events of position `flat` in `events`. */
static uint32_t events_of(const dfi_events *events, uint32_t kind, uint32_t flat)
{
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < events->count; ++i) {
        n += events->rec[i].kind == kind && events->rec[i].position == flat ? 1u : 0u;
    }
    return n;
}

/* Issue 619 (decision 0026 section 4, amended by I2, lead decision B: the clear of a faint-held name). A holder that enters disguised and
 * faints without a hit in the same step keeps the name on its fainted position; the real disguise member dragged in later in that step
 * would clear the name while the holder stands fainted. The faint dropped the disguise (ability_state, dfi_process_faints) and the fold
 * writes the shown name only at the end of the step, so no check of dfi_switch_in saw it: the step ended in E_INVARIANT (the foe's
 * occupant of the fainted position was the holder, never seen). Now refused E_UNSUPPORTED at the drag-in, before its DRAG event.
 * White-box: i2_illusion_break at team start, made into a turn boundary with Milotic (roster 1) on position 0, Primarina (roster 2) on
 * position 1, Zoroark (roster 0, at 1 HP) and Gholdengo (roster 3) on the bench in that party order, Stealth Rock on side 0, and Red
 * Card on the foe's Primarina. The turn (faint_drag_turn): Zoroark switches into position 1 disguised as Gholdengo (the last standing
 * member to its right), Stealth Rock knocks it out (a KO that is not a hit: the name stays), Milotic's Scald hits the Red Card holder,
 * and the drag brings a random bench member (Primarina or Gholdengo) into position 0. The seed of each case is the first whose drag
 * brings the wanted member in a control without Illusion (Zoroark's ability cleared; Illusion draws nothing, so the draws are the same
 * up to the drag).
 *   - Refused: Gholdengo dragged in next to the fainted holder (before its DRAG event).
 *   - Not refused (DUOFORGE_OK, with the fold and the invariants): Primarina dragged in instead; and Zoroark knocked out by a hit
 *     (Staraptor's Brave Bird, no Stealth Rock), which breaks the disguise first (ILLUSION_END), then Gholdengo dragged in.
 *   - The name set earlier in the same step is read for every check of dfi_switch_in: with a SWITCH line of Zoroark disguised as Milotic
 *     put in front of the step's events (a holder that already entered once in this step, the variant of two entries), Zoroark's entry
 *     disguised as Gholdengo would need a second name: refused (white-box, the events are synthetic). */
static void check_faint_drag(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    dfi_side *sd = &b->sides[0];
    if (!DF_CHECK(t, sd->brought_mask == 0x0Fu && b->sides[1].positions[0].occupant == 0u && b->sides[1].positions[1].occupant == 1u)) {
        duoforge_battle_destroy(b);
        return;
    }
    sd->positions[0].occupant = 1u; /* Milotic */
    sd->positions[1].occupant = 2u; /* Primarina */
    dfi_party_put(&b->tail, 0u, 0u, 2u);
    dfi_party_put(&b->tail, 0u, 1u, 3u);
    dfi_party_put(&b->tail, 0u, 2u, 1u); /* Zoroark */
    dfi_party_put(&b->tail, 0u, 3u, 4u); /* Gholdengo, to its right */
    sd->members[0].hp = 1u;
    b->tail.sides[0].positions[0].ability_state = 0u;
    b->tail.sides[0].positions[1].ability_state = 0u;
    memset(&b->tail.sides[0].illusion, 0, sizeof b->tail.sides[0].illusion);
    b->sides[1].seen_mask = (uint8_t)(b->sides[1].seen_mask | 1u << 2u); /* the foe saw Primarina come in */
    b->sides[1].knowledge[2].hp_percent = 100u;
    b->sides[1].members[0].item = DFI_ITEM_REDCARD + 1u;
    if (!DF_CHECK_EQ_U64(t, dfi_state_check(ctx, b, NULL), DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return;
    }
    struct duoforge_battle rocks = *b;
    rocks.tail.sides[0].stealth_rock = 1u;
    rocks.tail.sides[0].hazard_order = 0u; /* slot 0: DFI_HAZARD_STEALTH_ROCK */
    duoforge_battle_destroy(b);

    /* The seeds: the first whose drag brings Gholdengo (roster 3) and Primarina (roster 2), in the control without Illusion. */
    dfi_events ev;
    uint64_t seed_g[2] = {0u, 0u}; /* [hit] */
    uint64_t seed_p = 0u;
    for (uint32_t hit = 0u; hit < 2u; ++hit) {
        struct duoforge_battle control = rocks;
        if (hit != 0u) {
            control.tail.sides[0].stealth_rock = 0u;
        }
        control.sides[0].members[0].ability = 0u;
        for (uint64_t s = 1u; s < 64u && (seed_g[hit] == 0u || (hit == 0u && seed_p == 0u)); ++s) {
            if (faint_drag_turn(ctx, &control, s, hit != 0u, false, false, &ev) != DUOFORGE_OK) {
                continue;
            }
            const uint32_t in = dragged_in(&ev);
            if (in == 3u && seed_g[hit] == 0u) {
                seed_g[hit] = s;
            } else if (in == 2u && hit == 0u && seed_p == 0u) {
                seed_p = s;
            }
        }
    }
    if (!DF_CHECK(t, seed_g[0] != 0u && seed_g[1] != 0u && seed_p != 0u)) {
        return;
    }

    /* Refused: Gholdengo dragged in next to the holder fainted under its name. */
    DF_CHECK_EQ_U64(t, faint_drag_turn(ctx, &rocks, seed_g[0], false, true, false, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, ev.count != 0u && ev.rec[0].kind == DUOFORGE_EVENT_SWITCH && ev.rec[0].position == 1u && ev.rec[0].id == 0u &&
                    ev.rec[0].reserved[0] == 4u); /* Zoroark entered, disguised as Gholdengo */
    DF_CHECK_EQ_U64(t, events_of(&ev, DUOFORGE_EVENT_FAINT, 1u), 1u);        /* and fainted under the name */
    DF_CHECK_EQ_U64(t, events_of(&ev, DUOFORGE_EVENT_ILLUSION_END, 1u), 0u); /* without a break */
    DF_CHECK_EQ_U64(t, dragged_in(&ev), DUOFORGE_MAX_ROSTER);                /* refused before Gholdengo's DRAG */

    /* Not refused: Primarina dragged in instead. */
    DF_CHECK_EQ_U64(t, faint_drag_turn(ctx, &rocks, seed_p, false, true, false, &ev), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, events_of(&ev, DUOFORGE_EVENT_FAINT, 1u), 1u);
    DF_CHECK_EQ_U64(t, dragged_in(&ev), 2u);

    /* Not refused: the holder knocked out by a hit, which breaks the disguise first; Gholdengo dragged in then shows no name twice. */
    struct duoforge_battle bare = rocks;
    bare.tail.sides[0].stealth_rock = 0u;
    DF_CHECK_EQ_U64(t, faint_drag_turn(ctx, &bare, seed_g[1], true, true, false, &ev), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, events_of(&ev, DUOFORGE_EVENT_ILLUSION_END, 1u), 1u);
    DF_CHECK_EQ_U64(t, events_of(&ev, DUOFORGE_EVENT_FAINT, 1u), 1u);
    DF_CHECK_EQ_U64(t, dragged_in(&ev), 3u);

    /* The variant of two entries in one step (synthetic events): a name set earlier in the step is the shown name of the one-name
     * check. A SWITCH of Zoroark disguised as Milotic (roster 1 + 1) is put in front of the step's events; Zoroark's switch-in
     * disguised as Gholdengo would need a second name: refused before its SWITCH event. Without that line (the control), the same turn
     * is not refused for this reason. */
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_SWITCH, 1u);
    ev.rec[0].id = 0u;
    ev.rec[0].reserved[0] = 2u;
    ev.count = 1u;
    DF_CHECK_EQ_U64(t, faint_drag_turn(ctx, &bare, seed_g[1], false, false, true, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, ev.count, 1u);
    DF_CHECK(t, faint_drag_turn(ctx, &bare, seed_g[1], false, false, false, &ev) != DUOFORGE_E_UNSUPPORTED);
}

/* The fold writes the status the lines show on the name (decision 0026 section 4, amended by I2): a STATUS line of the disguised holder
 * sets the override status, a CURE_STATUS line clears it. One line folded on the battle with the disguise up (i2_illusion_break,
 * step 1); the fold reads `before` only at its start, so the battle serves as both. */
static void check_fold_status_line(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    dfi_events ev;
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_STATUS, 0u);
    ev.rec[0].detail = DFI_STATUS_BRN;
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, b, &ev, 0u));
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.override[2], DFI_STATUS_BRN);
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_CURE_STATUS, 0u);
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, b, &ev, 0u));
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.override[2], DUOFORGE_AILMENT_NONE);
    duoforge_battle_destroy(b);
}

/* The switch-in of a disguised holder with a status on its line (M11, decision 0026 section 3 as amended by I2): byte 7 of the snapshot
 * is the holder's status as the foe was shown it, and the override carries the same status. The team-start state has the disguise up;
 * a SWITCH line of position 0 names the holder (roster 0) and its disguise (reserved[0] = 3 + 1), at 167/167 and burned. */
static void check_fold_switch_status(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    dfi_events ev;
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_SWITCH, 0u);
    ev.rec[0].id = 0u;
    ev.rec[0].reserved[0] = 4u; /* the disguise (roster 3) + 1 */
    ev.rec[0].hp = b->sides[0].members[0].hp_max;
    ev.rec[0].hp_max = b->sides[0].members[0].hp_max;
    ev.rec[0].hp_kind = DUOFORGE_HP_EXACT;
    ev.rec[0].status = DFI_STATUS_BRN;
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, b, &ev, 0u));
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.snapshot[7], DFI_STATUS_BRN);
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.override[2], DFI_STATUS_BRN);
    duoforge_battle_destroy(b);
}

/* Negative controls of the expected foe status (conformance_compare.c df_conf_expected_status; decision 0026 section 4, "A faint while
 * disguised"). The one exception is the holder fainted under its shown name, which the foe never saw faint (its display is nonzero):
 * (a) a fainted foe member that is not the holder shows none, even with a nonzero display (a broad gate shows its status and fails
 * here); (b) without the holder exception the holder's status would be lost (it must show the status it knew); a holder the foe saw
 * fainted shows none; the owner sees its true status alive and none fainted. */
static void check_expected_status(df_test *t)
{
    df_conf_member holder;
    df_conf_member plain;
    memset(&holder, 0, sizeof holder);
    memset(&plain, 0, sizeof plain);
    holder.ability = DFI_ABILITY_ILLUSION + 1u;
    df_conf_mon e;
    memset(&e, 0, sizeof e);
    e.present = 1u;
    e.seen = 1u;
    e.seen_percent = 50u; /* the foe's last display: never shown fainted */
    e.fainted = 1u;
    e.status = DFI_STATUS_PSN;
    e.shown_status = DFI_STATUS_BRN;
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &plain, 1u, 0u), 0u);                      /* (a) non-holder, fainted */
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &holder, 1u, 0u), DFI_STATUS_BRN);         /* (b) holder under its name */
    e.seen_percent = 0u;
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &holder, 1u, 0u), 0u);                     /* holder the foe saw fainted */
    e.seen_percent = 50u;
    e.fainted = 0u;
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &plain, 1u, 0u), DFI_STATUS_BRN);          /* alive foe: the shown status */
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &plain, 0u, 0u), DFI_STATUS_PSN);          /* the owner: its true status */
    e.fainted = 1u;
    DF_CHECK_EQ_U64(t, df_conf_expected_status(&e, &plain, 0u, 0u), 0u);                      /* the owner, fainted */
}

/* Audit (2026-10-10, HauptSession's view.c audit), item (a), decision 0026 section 6 (amended): the foe's public record hides the
 * secret parts of the disguise: the holder's identity (ability_state's roster index), the disguise flag, snapshot bytes 0..6 and
 * the pending counts. The shown name (ill_shown) and the override are what the foe saw on the field, so they stay visible.
 * (i) Masked bytes: with a disguise up, duoforge_battle_public refuses the foe's record (ILLUSION_POSSIBLE, decision 0026 section
 *     4), so the masked bytes do not leave through the public call at all; the test pins the refusal and the cause.
 * (ii) Visible bytes: the owner's record carries its own Illusion bytes exactly as the true state holds them (the owner's view is
 *     not masked). The visible values of the foe's view are the values the reference fold derives from the shown lines alone; that
 *     is compared per recorded battle by the conformance tables (shown_status, pp_foe in conformance_compare.c). */
static void check_public_mask(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    uint32_t causes = 0u;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 1u, &causes) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, causes & DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE, DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE);
    duoforge_public_state foe_pub;
    DF_CHECK(t, duoforge_battle_public(ctx, b, 1u, &foe_pub) == DUOFORGE_E_UNSUPPORTED);
    duoforge_public_state own_pub;
    if (DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &own_pub) == DUOFORGE_OK)) {
        const size_t side_off = DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE + DFI_ENC_TAIL5_SIDES_OFF + 0u * DFI_ENC_TAIL5_SIDE_SIZE;
        const dfi_tail_illusion *ill = &b->tail.sides[0].illusion;
        DF_CHECK(t, memcmp(own_pub.state + side_off + DFI_ENC_TAIL5_ILL_SNAPSHOT_OFF, ill->snapshot, 7u) == 0);
        DF_CHECK(t, memcmp(own_pub.state + side_off + DFI_ENC_TAIL5_ILL_PENDING_OFF, ill->pending, sizeof ill->pending) == 0);
        const size_t pos_off = DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_SIDES_OFF + 0u * DFI_ENC_TAIL_SIDE_SIZE + DFI_ENC_TAIL_POS_OFF;
        DF_CHECK_EQ_U64(t, own_pub.state[pos_off + DFI_ENC_TAIL_POS_ABILITY_STATE_OFF], b->tail.sides[0].positions[0].ability_state);
        DF_CHECK(t, b->tail.sides[0].positions[0].ability_state != 0u); /* the disguise flag is up, so the owner's copy is not zero */
    }
    duoforge_battle_destroy(b);
}

/* Audit item (b): the predicate ILLUSION_POSSIBLE reads the Illusion state of the sides, which is safe because every public call
 * checks the state first (dfi_view_check_args runs dfi_state_check, the rev 5 rule of invariants.c: no Illusion byte without a holder
 * on the side's sheet). Counter-case: a holder-less side (the foe, side 1) with a pending count is refused E_INVARIANT by the public
 * causes call and by the public record, whatever the player. */
static void check_illusion_invariant(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    bool holderless = true;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        holderless = holderless && b->sides[1].members[m].ability != DFI_ABILITY_ILLUSION + 1u;
    }
    if (DF_CHECK(t, holderless)) {
        b->tail.sides[1].illusion.pending[0] = 1u;
        uint32_t causes = 0u;
        DF_CHECK(t, duoforge_battle_public_causes(ctx, b, 0u, &causes) == DUOFORGE_E_INVARIANT);
        duoforge_public_state pub;
        DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &pub) == DUOFORGE_E_INVARIANT);
    }
    duoforge_battle_destroy(b);
}

/* The instaswitch of a disguised holder (decision 0025 item 10 with decision 0026 section 4): the revived holder goes back into its own
 * position, and a disguise would be decided at that switch-in. The reference has no line for a revive under a disguise, so the
 * switch is refused E_UNSUPPORTED before any change and before any event (the explicit refusal of flow/switch.h dfi_switch_in). White-box:
 * i2_illusion_break at step 1 (Zoroark, the holder, active at position 0 and disguised as roster 3, the name shown). The queue of a
 * copy holds the instaswitch of the holder into position 0. Negative control: the same instaswitch with no bench member to the right
 * standing (no disguise decided) is not refused for this reason. */
static duoforge_status insta_switch(const duoforge_context *ctx, const duoforge_battle *b, dfi_events *events)
{
    struct duoforge_battle tmp = *b;
    /* The pivot boundary keeps the queue (dfi_resume_pivot only puts its own entries in front); the replacement boundary rebuilds
     * it (dfi_queue_choices). With no request the pivot adds nothing, so the queued instaswitch is the first action. */
    tmp.boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    tmp.request_mask = 0u;
    tmp.queue[0] = (dfi_queue_record){0u, (uint8_t)DFI_Q_INSTASWITCH, 0u, 0u, 0u, 0u, 0u};
    tmp.queue_len = 1u;
    duoforge_side_choice responses[DUOFORGE_SIDE_COUNT];
    memset(responses, 0, sizeof responses);
    memset(events, 0, sizeof *events);
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    draws.tape = NULL;
    draws.tape_len = 0u;
    return dfi_turn_run(ctx, &tmp, responses, &draws, events);
}

static void check_insta_disguise(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (b == NULL) {
        return;
    }
    if (!DF_CHECK(t, b->tail.sides[0].illusion.shown == 4u && b->sides[0].positions[0].occupant == 0u &&
                         b->sides[0].members[0].hp != 0u && dfi_illusion_disguise_up(&b->sides[0], &b->tail.sides[0], 0u) != 0)) {
        duoforge_battle_destroy(b);
        return;
    }
    dfi_events ev;
    DF_CHECK_EQ_U64(t, insta_switch(ctx, b, &ev), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, ev.count, 0u); /* refused before any event */
    DF_CHECK_EQ_U64(t, b->tail.sides[0].illusion.shown, 4u); /* and before any change of the disguise */
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].occupant, 0u);

    /* negative control: no name is shown and the bench to the right is fainted, so no disguise is decided and the switch is not
     * refused here (a shown name with no disguise would be the one-name refusal, not this one) */
    struct duoforge_battle nc = *b;
    memset(&nc.tail.sides[0].illusion, 0, sizeof nc.tail.sides[0].illusion);
    nc.tail.sides[0].positions[0].ability_state = 0u;
    for (uint32_t m = 1u; m < DUOFORGE_MAX_ROSTER && m < nc.sides[0].member_count; ++m) {
        nc.sides[0].members[m].hp = 0u;
    }
    DF_CHECK(t, insta_switch(ctx, &nc, &ev) != DUOFORGE_E_UNSUPPORTED);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_i2");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_team_start(&t, ctx);
    check_public_mask(&t, ctx);
    check_illusion_invariant(&t, ctx);
    check_break(&t, ctx);
    check_unbroken(&t, ctx);
    check_ab_info_safety(&t, ctx);
    check_encoder_refusal(&t);
    check_disguise_status(&t, ctx);
    check_possible_fainted(&t, ctx);
    check_disguise_needs_name(&t, ctx);
    check_knowledge_disguise(&t, ctx);
    check_expected_status(&t);
    check_faint_held(&t, ctx);
    check_one_name_switch_in(&t, ctx);
    check_faint_clear(&t, ctx);
    check_double_replacement(&t, ctx);
    check_faint_drag(&t, ctx);
    check_insta_disguise(&t, ctx);
    check_fold_status_line(&t, ctx);
    check_fold_switch_status(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
