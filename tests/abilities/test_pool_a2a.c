/*
 * duoforge.state.pool_a2a (white-box): batch A2a of the Champions-100 track (decision 0015 entry 5dy), fourteen abilities with
 * one clause each at an existing hook. The recorded POOL battles a2a_cover_a to a2a_cover_i (campaigns 52002 and 52003) are
 * replayed against the pool rows by duoforge.reference.conformance_pool_data; this test checks what the replays alone do not:
 *
 *   1. The marks and the handler column: the fourteen rows are marked engine rows (handler NONE); Insomnia, Vital Spirit and
 *      Immunity stay unmarked UNMODELED rows (HS decision: stragglers after the abilities move, their Trace refusal belongs in
 *      dfi_trace). Poison Point's draw site is 26 (HS grant) with its own name.
 *   2. The hook fires and the neighbours do not: at the step of a recorded battle where the clause decides something, the step
 *      replays with the reference's tape; with the holder's ability changed to a marked neighbour of the same hook (Volt Absorb
 *      for Water Absorb and Earth Eater, Lightning Rod for Motor Drive, Rain Dish for Ice Body, Static for Poison Point, ...)
 *      the same step no longer reproduces the reference (another status, another tape use or other events).
 *   3. The refusals that no campaign battle reaches: an Illuminate or White Smoke holder that is a Grass type next to a Flower
 *      Veil holder (two TryBoost handlers for one drop; g12_flower_veil_a and g31_yawn_flower_veil with the protected Rillaboom's
 *      ability changed, Sylveon's Yawn slot holding Mud-Slap, which it learns), and a multi-accuracy move's later hit at a
 *      confused Tangled Feet holder (a2a_cover_c with Gardevoir's Will-O-Wisp slot holding Triple Axel, which it learns):
 *      E_UNSUPPORTED (r->deferred resp. the later-hit refusal), the battle unchanged; the controls play.
 *   5. Life Dew (a Water heal move of the user and its ally) at an ally with Water Absorb: the heal path does not run the TryHit
 *      abilities, so it is refused before anything changes (g32_life_dew step 3 with Kingambit's ability changed); the user's own
 *      Water Absorb is not asked (target === source) and the control plays.
 *   6. Natural Cure's CURE_STATUS has cause ABILITY and id2 Natural Cure + 1 (a2a_cover_b step 2), and the observation digest's
 *      line schema accepts it.
 *   4. Tangled Feet's 2048 and Compound Eyes' 5325 (both priority -1) give the same chain in both orders, from 4096 and from
 *      Gravity's 6840 (the accuracy chain applies them in one fixed order).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/abilities/current.h"
#include "core/modifier.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/observation_digest.h"
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

/* The recorded battle after its first `steps` steps (step 0 is the team step), the reference's draws as the tape. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
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
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            fprintf(stderr, "  %s step %u\n", cb->name, si);
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The roster index of the member of `side` with forme `forme` (its first such member), or DUOFORGE_MAX_ROSTER. */
static uint32_t member_of(const duoforge_battle *b, uint32_t side, uint32_t forme)
{
    for (uint32_t m = 0u; m < b->sides[side].member_count; ++m) {
        if (b->sides[side].members[m].species_id == forme) {
            return m;
        }
    }
    return DUOFORGE_MAX_ROSTER;
}

/* The step's status, tape use and player 0's events. */
typedef struct a2a_run {
    duoforge_status status;
    uint32_t used;
    uint32_t count;
    duoforge_event events[DUOFORGE_MAX_EVENTS];
} a2a_run;

static void run_step(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st, a2a_run *out)
{
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    duoforge_step_result res;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    memset(out->events, 0, sizeof out->events);
    duoforge_event_buffer buffers[2] = {{out->events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    out->used = 0u;
    out->status = dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &out->used, &res, buffers);
    out->count = buffers[0].count;
}

#define AB(x) (1u + DFI_ABILITY_##x)

/* One clause at its decisive step: the battle, the step, the holder (side and forme), the clause's ability the holder has at the
 * step (its sheet's or, for the Trace holder, the copied one), and the marked neighbour of the same hook. */
typedef struct a2a_case {
    const char *battle;
    uint32_t step;
    uint32_t side;
    uint32_t forme;
    uint32_t ability;
    uint32_t neighbour;
    const char *what;
} a2a_case;

static const a2a_case cases[] = {
    {"a2a_cover_a", 10u, 0u, DFI_FORME_WATCHOG, AB(ILLUMINATE), AB(BIGPECKS), "Illuminate deletes Mud-Slap's accuracy drop"},
    {"a2a_cover_c", 3u, 0u, DFI_FORME_STARMIE, AB(ILLUMINATE), AB(BIGPECKS), "Illuminate ignores Gardevoir's evasion"},
    {"a2a_cover_a", 5u, 1u, DFI_FORME_TORKOAL, AB(WHITESMOKE), AB(HYPERCUTTER), "White Smoke deletes Muddy Water's drop (roll 21)"},
    {"a2a_cover_b", 2u, 0u, DFI_FORME_VAPOREON, AB(WATERABSORB), AB(VOLTABSORB), "Water Absorb takes Surf at full HP (-immune)"},
    {"a2a_cover_g", 1u, 1u, DFI_FORME_ORTHWORM, AB(EARTHEATER), AB(VOLTABSORB), "Earth Eater takes Earthquake at full HP"},
    {"a2a_cover_b", 13u, 0u, DFI_FORME_EMOLGA, AB(MOTORDRIVE), AB(LIGHTNINGROD), "Motor Drive: Wild Charge raises Speed"},
    {"a2a_cover_b", 14u, 1u, DFI_FORME_AVALUGG, AB(ICEBODY), AB(RAINDISH), "Ice Body heals in snow"},
    {"a2a_cover_d", 10u, 1u, DFI_FORME_RAICHUALOLA, AB(SURGESURFER), AB(SWIFTSWIM), "Surge Surfer doubles Speed in Electric Terrain"},
    {"a2a_cover_c", 3u, 1u, DFI_FORME_GARDEVOIR, AB(QUICKFEET), AB(CHLOROPHYLL), "Quick Feet (traced) of a paralysed Gardevoir"},
    {"a2a_cover_e", 1u, 1u, DFI_FORME_SALAZZLE, AB(CORROSION), AB(OBLIVIOUS), "Corrosion: Toxic poisons a Poison type"},
    {"a2a_cover_a", 9u, 1u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt refuses Hypnosis"},
    {"a2a_cover_a", 6u, 1u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt refuses Yawn"},
    {"a2a_cover_d", 10u, 0u, DFI_FORME_GARGANACL, AB(PURIFYINGSALT), AB(LEAFGUARD), "Purifying Salt halves Shadow Ball"},
    {"a2a_cover_f", 1u, 0u, DFI_FORME_GOODRA, AB(GOOEY), AB(WEAKARMOR), "Gooey lowers Corviknight's Speed (Mirror Armor)"},
    {"a2a_cover_a", 1u, 0u, DFI_FORME_DRAGALGE, AB(POISONPOINT), AB(STATIC), "Poison Point rolls on site 26"},
    {"a2a_cover_c", 15u, 0u, DFI_FORME_PIDGEOT, AB(TANGLEDFEET), AB(SANDVEIL), "Tangled Feet halves Snarl's accuracy"},
    {"a2a_cover_b", 2u, 1u, DFI_FORME_PAWMOT, AB(NATURALCURE), AB(REGENERATOR), "Natural Cure cures tox at the switch-out"},
};

static void check_case(df_test *t, const duoforge_context *ctx, const a2a_case *c)
{
    const df_conf_battle *cb = find(c->battle);
    if (!DF_CHECK(t, cb != NULL && c->step < cb->step_count)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, c->step);
    if (b == NULL) {
        return;
    }
    const uint32_t m = member_of(b, c->side, c->forme);
    if (!DF_CHECK(t, m < DUOFORGE_MAX_ROSTER) ||
        !DF_CHECK_EQ_U64(t, dfi_ability_code(b, &b->sides[c->side].members[m]), c->ability)) {
        fprintf(stderr, "  %s: the holder is not found with its ability\n", c->what);
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[c->step];
    static a2a_run base;
    static a2a_run moved;
    duoforge_battle *x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        run_step(ctx, x, st, &base);
        if (!DF_CHECK(t, base.status == DUOFORGE_OK) || !DF_CHECK_EQ_U64(t, base.used, st->tape_len)) {
            fprintf(stderr, "  %s: the recorded step does not replay\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        const uint32_t sheet = x->sides[c->side].members[m].ability;
        x->tail.sides[c->side].ability_now[m] = (uint16_t)(c->neighbour == sheet ? 0u : c->neighbour);
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        run_step(ctx, x, st, &moved);
        const bool same = moved.status == DUOFORGE_OK && moved.used == st->tape_len && moved.count == base.count &&
                          memcmp(moved.events, base.events, (size_t)base.count * sizeof base.events[0]) == 0;
        if (!DF_CHECK(t, !same)) {
            fprintf(stderr, "  %s: the neighbour ability plays the same step\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

static void check_marks(df_test *t)
{
    static const uint32_t rows[] = {DFI_ABILITY_ILLUMINATE, DFI_ABILITY_WHITESMOKE, DFI_ABILITY_WATERABSORB, DFI_ABILITY_EARTHEATER,
                                    DFI_ABILITY_MOTORDRIVE, DFI_ABILITY_ICEBODY, DFI_ABILITY_SURGESURFER, DFI_ABILITY_QUICKFEET,
                                    DFI_ABILITY_CORROSION, DFI_ABILITY_PURIFYINGSALT, DFI_ABILITY_GOOEY, DFI_ABILITY_POISONPOINT,
                                    DFI_ABILITY_TANGLEDFEET, DFI_ABILITY_NATURALCURE};
    for (size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[rows[i]], DFI_HANDLER_NONE);
    }
    static const uint32_t stragglers[] = {DFI_ABILITY_INSOMNIA, DFI_ABILITY_VITALSPIRIT, DFI_ABILITY_IMMUNITY};
    for (size_t i = 0; i < sizeof stragglers / sizeof stragglers[0]; ++i) {
        DF_CHECK_EQ_U64(t, dfi_support.abilities[stragglers[i]], 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[stragglers[i]], DFI_HANDLER_UNMODELED);
    }
    DF_CHECK_EQ_U64(t, DFI_SITE_POISON_POINT, 26u);
    const char *name = dfi_site_name(DFI_SITE_POISON_POINT);
    DF_CHECK(t, name != NULL && strcmp(name, "poison-point") == 0);
    DF_CHECK(t, DFI_SITE_POISON_POINT != DFI_SITE_STATIC && DFI_SITE_POISON_POINT != DFI_SITE_FLAME_BODY);
}

/* 3. The refusals. (a) White Smoke on the protected Rillaboom of g12_flower_veil_a (step 1, the reference's tape: the drops are the
 * recorded ones). */
static void check_flower_veil_refusals(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g12_flower_veil_a");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 1u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, 1u);
    if (b == NULL) {
        return;
    }
    const uint32_t rilla = member_of(b, 0u, DFI_FORME_RILLABOOM);
    if (!DF_CHECK(t, rilla < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[1];
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    /* (a) White Smoke on the protected Rillaboom: Snarl's and Parting Shot's drops meet Flower Veil and White Smoke. */
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        if (variant == 1u) {
            x->tail.sides[0].ability_now[rilla] = (uint16_t)AB(WHITESMOKE);
        }
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        uint32_t used = 0u;
        const duoforge_status s = dfi_battle_step_tape(ctx, x, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (variant == 0u) {
            DF_CHECK(t, s == DUOFORGE_OK); /* the control: the recorded step */
        } else {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

/* (b) Illuminate on the protected Rillaboom of g31_yawn_flower_veil (step 1): Sylveon's Yawn slot holds Mud-Slap, whose accuracy
 * drop (a secondary of chance 100) meets Flower Veil and Illuminate. The step runs on the battle's own generator (the changed move
 * draws what it draws). The control keeps Rillaboom's own ability. */
static void check_illuminate_flower_veil(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g31_yawn_flower_veil");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 1u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, 1u);
    if (b == NULL) {
        return;
    }
    const uint32_t rilla = member_of(b, 1u, DFI_FORME_RILLABOOM);
    const uint32_t sylveon = member_of(b, 0u, DFI_FORME_SYLVEON);
    if (!DF_CHECK(t, rilla < DUOFORGE_MAX_ROSTER && sylveon < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[1], b, &bd);
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        dfi_member *sm = &x->sides[0].members[sylveon];
        for (uint32_t k = 0u; k < sm->move_count; ++k) {
            if (sm->moves[k].move_id == DFI_MOVE_YAWN) {
                sm->moves[k].move_id = (uint16_t)DFI_MOVE_MUDSLAP;
            }
        }
        if (variant == 1u) {
            x->tail.sides[1].ability_now[rilla] = (uint16_t)AB(ILLUMINATE);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        const duoforge_status s = duoforge_battle_step(ctx, x, &bd, &res);
        if (variant == 0u) {
            DF_CHECK(t, s == DUOFORGE_OK);
        } else {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

/* Tangled Feet's later-hit refusal: a2a_cover_c step 4 (Gardevoir's Will-O-Wisp at Pidgeot) with Triple Axel in that slot,
 * Gardevoir at +6 accuracy (its first hit lands: 90 x 0.5 x 3 > 100) and burned instead of paralysed (no full paralysis draw; its
 * traced Quick Feet keeps it first), and Pidgeot confused (3 turns; at 88 of 190 HP it stands after the 20-power first hit). With
 * Tangled Feet the second hit's ModifyAccuracy is refused (E_UNSUPPORTED, the battle unchanged); with Keen Eye in its place the step plays. The
 * step runs on the battle's own generator. */
static void check_tangled_feet_later_hit(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("a2a_cover_c");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 4u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, 4u);
    if (b == NULL) {
        return;
    }
    const uint32_t gard = member_of(b, 1u, DFI_FORME_GARDEVOIR);
    const uint32_t pidgeot = member_of(b, 0u, DFI_FORME_PIDGEOT);
    uint32_t gard_slot = 2u;
    uint32_t pidgeot_slot = 2u;
    for (uint32_t p = 0u; p < 2u; ++p) {
        gard_slot = b->sides[1].positions[p].occupant == gard ? p : gard_slot;
        pidgeot_slot = b->sides[0].positions[p].occupant == pidgeot ? p : pidgeot_slot;
    }
    if (!DF_CHECK(t, gard < DUOFORGE_MAX_ROSTER && pidgeot < DUOFORGE_MAX_ROSTER && gard_slot < 2u && pidgeot_slot < 2u)) {
        duoforge_battle_destroy(b);
        return;
    }
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[4], b, &bd);
    for (uint32_t variant = 0u; variant < 2u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        dfi_member *gm = &x->sides[1].members[gard];
        uint32_t pp_max = 0u; /* Triple Axel has Psychic's 10 PP: the slot takes Psychic's maximum */
        for (uint32_t k = 0u; k < gm->move_count; ++k) {
            pp_max = gm->moves[k].move_id == DFI_MOVE_PSYCHIC ? gm->moves[k].pp_max : pp_max;
        }
        DF_CHECK(t, pp_max != 0u);
        for (uint32_t k = 0u; k < gm->move_count; ++k) {
            if (gm->moves[k].move_id == DFI_MOVE_WILLOWISP) {
                gm->moves[k].move_id = (uint16_t)DFI_MOVE_TRIPLEAXEL;
                gm->moves[k].pp_max = (uint8_t)pp_max;
                gm->moves[k].pp = (uint8_t)pp_max;
            }
        }
        gm->status = (uint8_t)DFI_STATUS_BRN;
        gm->status_counter = 0u;
        x->sides[1].positions[gard_slot].stages[DFI_STAGE_ACCURACY] = (uint8_t)DFI_BIAS6_MAX;
        x->sides[0].positions[pidgeot_slot].confusion_turns = 3u;
        if (variant == 0u) {
            x->tail.sides[0].ability_now[pidgeot] = (uint16_t)AB(KEENEYE);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        const duoforge_status s = duoforge_battle_step(ctx, x, &bd, &res);
        if (variant == 0u) {
            DF_CHECK(t, s == DUOFORGE_OK);
        } else {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

/* 5. Life Dew at an ally with Water Absorb (g32_life_dew step 3: Milotic's Life Dew heals Milotic and Kingambit). */
static void check_life_dew(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g32_life_dew");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 3u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, 3u);
    if (b == NULL) {
        return;
    }
    const uint32_t milotic = member_of(b, 0u, DFI_FORME_MILOTIC);
    const uint32_t ally = member_of(b, 0u, DFI_FORME_KINGAMBIT);
    if (!DF_CHECK(t, milotic < DUOFORGE_MAX_ROSTER && ally < DUOFORGE_MAX_ROSTER)) {
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[3];
    duoforge_decision_bundle bd;
    bundle_of(st, b, &bd);
    for (uint32_t variant = 0u; variant < 3u; ++variant) {
        duoforge_battle *x = NULL;
        if (!DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
            continue;
        }
        if (variant == 1u) {
            x->tail.sides[0].ability_now[ally] = (uint16_t)AB(WATERABSORB); /* the ally: refused */
        } else if (variant == 2u) {
            x->tail.sides[0].ability_now[milotic] = (uint16_t)AB(WATERABSORB); /* the user itself: not asked */
        }
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, x, &before) == DUOFORGE_OK);
        duoforge_step_result res;
        uint32_t used = 0u;
        const duoforge_status s = dfi_battle_step_tape(ctx, x, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (variant == 1u) {
            DF_CHECK(t, s == DUOFORGE_E_UNSUPPORTED);
            bool equal = false;
            DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, x, before, &equal) == DUOFORGE_OK && equal);
        } else {
            DF_CHECK(t, s == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, used, st->tape_len);
        }
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

/* 6. Natural Cure's event (a2a_cover_b step 2: Pawmot, badly poisoned, switches out) and the digest's line schema. */
static void check_natural_cure_event(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("a2a_cover_b");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > 2u)) {
        return;
    }
    duoforge_battle *b = replay(t, ctx, cb, 2u);
    if (b == NULL) {
        return;
    }
    static a2a_run run;
    run_step(ctx, b, &cb->steps[2], &run);
    DF_CHECK(t, run.status == DUOFORGE_OK);
    uint32_t found = 0u;
    for (uint32_t i = 0u; i < run.count; ++i) {
        const duoforge_event *e = &run.events[i];
        if (e->kind == DUOFORGE_EVENT_CURE_STATUS && e->cause == DUOFORGE_CAUSE_ABILITY) {
            found += 1u;
            DF_CHECK_EQ_U64(t, e->id2, AB(NATURALCURE));
            DF_CHECK_EQ_U64(t, e->detail, DUOFORGE_AILMENT_TOX);
            DF_CHECK_EQ_U64(t, e->flags, 0u); /* [silent]: no [msg] */
            uint8_t line[64];
            uint32_t size = 0u;
            DF_CHECK(t, dfi_observation_line_encode(e, NULL, line, (uint32_t)sizeof line, &size) == DUOFORGE_OK);
        }
    }
    DF_CHECK_EQ_U64(t, found, 1u);
    duoforge_battle_destroy(b);
}

/* 4. The priority -1 accuracy group: Tangled Feet's 2048 and Compound Eyes' 5325 in both orders. */
static void check_dyadic_order(df_test *t)
{
    static const uint32_t starts[] = {4096u, 6840u};
    for (size_t i = 0; i < sizeof starts / sizeof starts[0]; ++i) {
        uint32_t a = 0u;
        uint32_t b = 0u;
        DF_CHECK(t, dfi_chain_modify(starts[i], 5325u, &a) && dfi_chain_modify(a, 2048u, &a));
        DF_CHECK(t, dfi_chain_modify(starts[i], 2048u, &b) && dfi_chain_modify(b, 5325u, &b));
        DF_CHECK_EQ_U64(t, a, b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_a2a");
    check_marks(&t);
    check_dyadic_order(&t);
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            check_case(&t, kp, &cases[i]);
        }
        check_flower_veil_refusals(&t, kp);
        check_illuminate_flower_veil(&t, kp);
        check_tangled_feet_later_hit(&t, kp);
        check_life_dew(&t, kp);
        check_natural_cure_event(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
