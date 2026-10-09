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
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
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
    check_disguise_needs_name(&t, ctx);
    check_knowledge_disguise(&t, ctx);
    check_expected_status(&t);
    check_faint_held(&t, ctx);
    check_one_name_switch_in(&t, ctx);
    check_faint_clear(&t, ctx);
    check_fold_status_line(&t, ctx);
    check_fold_switch_status(&t, ctx);
    return df_test_end(&t);
}
