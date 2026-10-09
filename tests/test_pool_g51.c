/*
 * duoforge.state.pool_g51 (white-box): step G51 (Mega batch 4). Ten Mega Stones marked with no new rule: Chandelurite
 * (Infiltrator, base Flash Fire), Houndoominite (Solar Power, base Flash Fire), Lucarionite (Adaptability, base Inner Focus; not
 * the Z stone), Dragalgite (Regenerator, base Adaptability), Crabominite (Iron Fist, base Hyper Cutter), Chimechite (Levitate,
 * base Levitate), Glalitite (Refrigerate, base Inner Focus), Pinsirite (Aerilate, base Hyper Cutter), Banettite (Prankster,
 * base Cursed Body) and Pidgeotite (No Guard, base Keen Eye or Big Pecks). Keen Eye and Big Pecks are the two base abilities
 * of Pidgeot that the Pidgeotite battles need: engine rows (src/combat/turn.c, dfi_boost and dfi_accuracy_check) that the
 * recorded battles g51_keen_eye and g51_big_pecks exercise.
 *
 * The recorded battles (g51_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the
 * reference's draws. Here are the facts that they do not show:
 *
 *   - the marks: each stone is a marked item with the handler NONE; each Mega ability, each base ability of the eleven
 *     pairs and Keen Eye and Big Pecks are marked, and each base ability is legal for its base forme;
 *   - the Mega of each (base forme, stone) pair (dfi_mega_of) and the support of the pair, Lucarionite and Lucarionite Z
 *     giving two different Mega formes of Lucario;
 *   - the setup with each stone is accepted, the member is Mega capable, evolves once into that forme with that ability, and
 *     the public API reports the pair as supported (duoforge_data_mega_count and _at);
 *   - the Keen Eye holder's ignoreEvasion (dfi_accuracy_check): a Keen Eye Pidgeot's Hurricane still hits a target whose
 *     evasion stage is raised by hand, where the same draw would miss without the ability.
 *
 * Un-marking any of the ten stones (or of a Mega or base ability) fails check_marks, check_pairs and check_setups.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formulas.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

struct g51_pair {
    uint32_t base;         /* the base forme */
    uint32_t item;         /* the stone (its item id) */
    uint32_t mega;         /* the Mega forme that the stone gives */
    uint32_t ability;      /* the Mega forme's ability */
    uint32_t base_ability; /* the base forme's ability that the recorded battle uses */
};

static const struct g51_pair pairs[] = {
    {DFI_FORME_CHANDELURE, DFI_ITEM_CHANDELURITE, DFI_FORME_CHANDELUREMEGA, DFI_ABILITY_INFILTRATOR, DFI_ABILITY_FLASHFIRE},
    {DFI_FORME_HOUNDOOM, DFI_ITEM_HOUNDOOMINITE, DFI_FORME_HOUNDOOMMEGA, DFI_ABILITY_SOLARPOWER, DFI_ABILITY_FLASHFIRE},
    {DFI_FORME_LUCARIO, DFI_ITEM_LUCARIONITE, DFI_FORME_LUCARIOMEGA, DFI_ABILITY_ADAPTABILITY, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_DRAGALGE, DFI_ITEM_DRAGALGITE, DFI_FORME_DRAGALGEMEGA, DFI_ABILITY_REGENERATOR, DFI_ABILITY_ADAPTABILITY},
    {DFI_FORME_CRABOMINABLE, DFI_ITEM_CRABOMINITE, DFI_FORME_CRABOMINABLEMEGA, DFI_ABILITY_IRONFIST, DFI_ABILITY_HYPERCUTTER},
    {DFI_FORME_CHIMECHO, DFI_ITEM_CHIMECHITE, DFI_FORME_CHIMECHOMEGA, DFI_ABILITY_LEVITATE, DFI_ABILITY_LEVITATE},
    {DFI_FORME_GLALIE, DFI_ITEM_GLALITITE, DFI_FORME_GLALIEMEGA, DFI_ABILITY_REFRIGERATE, DFI_ABILITY_INNERFOCUS},
    {DFI_FORME_PINSIR, DFI_ITEM_PINSIRITE, DFI_FORME_PINSIRMEGA, DFI_ABILITY_AERILATE, DFI_ABILITY_HYPERCUTTER},
    {DFI_FORME_BANETTE, DFI_ITEM_BANETTITE, DFI_FORME_BANETTEMEGA, DFI_ABILITY_PRANKSTER, DFI_ABILITY_CURSEDBODY},
    {DFI_FORME_PIDGEOT, DFI_ITEM_PIDGEOTITE, DFI_FORME_PIDGEOTMEGA, DFI_ABILITY_NOGUARD, DFI_ABILITY_KEENEYE},
};

#define G51_PAIRS (sizeof pairs / sizeof pairs[0])
#define G51_STONES 10u

static bool base_ability_legal(uint32_t base, uint32_t ability)
{
    const dfi_forme_legal *l = &dfi_pool_forme_legal[base];
    for (uint32_t k = 0u; k < l->ability_count; ++k) {
        if (l->abilities[k] == ability) {
            return true;
        }
    }
    return false;
}

/* The ten stones are marked items with no handler of their own; Keen Eye and Big Pecks are marked engine rows; the Mega and base
 * abilities are marked and legal for their formes. */
static void check_marks(df_test *t)
{
    static const uint32_t stones[G51_STONES] = {DFI_ITEM_CHANDELURITE, DFI_ITEM_HOUNDOOMINITE, DFI_ITEM_LUCARIONITE,
                                                DFI_ITEM_DRAGALGITE,   DFI_ITEM_CRABOMINITE,   DFI_ITEM_CHIMECHITE,
                                                DFI_ITEM_GLALITITE,    DFI_ITEM_PINSIRITE,     DFI_ITEM_BANETTITE,
                                                DFI_ITEM_PIDGEOTITE};
    for (uint32_t i = 0u; i < G51_STONES; ++i) {
        DF_CHECK(t, dfi_support.items[stones[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[stones[i]], DFI_HANDLER_NONE);
    }
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &pairs[i];
        DF_CHECK(t, dfi_support.items[p->item] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->ability] != 0u);
        DF_CHECK(t, dfi_support.abilities[p->base_ability] != 0u);
        DF_CHECK(t, base_ability_legal(p->base, p->base_ability));
        DF_CHECK_EQ_U64(t, dfi_pool_formes[p->mega].ability, p->ability);
    }
    /* the two engine rows of this step: marked, read by id (handler NONE), and both legal for Pidgeot */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_KEENEYE] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_BIGPECKS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_KEENEYE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_BIGPECKS], DFI_HANDLER_NONE);
    DF_CHECK(t, base_ability_legal(DFI_FORME_PIDGEOT, DFI_ABILITY_KEENEYE));
    DF_CHECK(t, base_ability_legal(DFI_FORME_PIDGEOT, DFI_ABILITY_BIGPECKS));
}

/* Flower Veil (a Grass type's TryBoost) would race Keen Eye and Big Pecks by Speed on a Grass forme with either ability, and
 * dfi_boost assumes none exists: no forme of the pool with Keen Eye or Big Pecks as a legal ability is a Grass type. */
static void check_no_grass_holder(df_test *t)
{
    uint32_t holders = 0u;
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[f];
        bool holds = false;
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            holds = holds || l->abilities[k] == DFI_ABILITY_KEENEYE || l->abilities[k] == DFI_ABILITY_BIGPECKS;
        }
        if (holds) {
            holders += 1u;
            DF_CHECK(t, dfi_pool_formes[f].types[0] != DFI_TYPE_GRASS && dfi_pool_formes[f].types[1] != DFI_TYPE_GRASS);
        }
    }
    DF_CHECK(t, holders >= 1u); /* Pidgeot is one of them */
}

/* Each pair: the Mega of the (base forme, stone) pair and its support; Lucario's two stones give its two Mega formes. */
static void check_pairs(df_test *t)
{
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &pairs[i];
        DF_CHECK_EQ_U64(t, dfi_mega_of(p->base, 1u + p->item), p->mega);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, p->base, 1u + p->item));
    }
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_LUCARIO, 1u + DFI_ITEM_LUCARIONITEZ), DFI_FORME_LUCARIOMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_PIDGEOT, 1u + DFI_ITEM_CHANDELURITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_CHIMECHO, 1u + DFI_ITEM_PIDGEOTITE), DFI_FORME_NONE);
}

/* A legal member of the base forme holding the stone (the first legal move, ability and gender, as mega_by_stone builds it). */
static bool build_setup(const dfi_kind_limits *lim, uint32_t species, uint32_t item, uint32_t ability, duoforge_member_setup *out)
{
    duoforge_member_setup m;
    memset(&m, 0, sizeof m);
    m.species_id = species;
    m.nature = 0u;
    m.item = (uint8_t)item;
    m.stat_points[0] = 2u;
    m.stat_points[1] = 32u;
    m.stat_points[5] = 32u;
    for (uint32_t move = 0u; move < lim->move_count; ++move) {
        if (dfi_forme_move_legal(lim, species, move)) {
            m.move_count = 1u;
            m.moves[0].move_id = (uint16_t)move;
            break;
        }
    }
    m.ability = (uint8_t)ability;
    for (uint32_t g = DUOFORGE_GENDER_MALE; g <= DUOFORGE_GENDER_NONE; ++g) {
        m.gender = (uint8_t)g;
        if (dfi_closure_member_setup_valid(lim, &m)) {
            *out = m;
            return true;
        }
    }
    return false;
}

/* The setup with each stone is accepted, the member is Mega capable and evolves into the pair's forme with its ability. */
static void check_setups(df_test *t)
{
    const dfi_kind_limits lim = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &pairs[i];
        duoforge_member_setup setup;
        dfi_member m;
        memset(&m, 0, sizeof m);
        if (!DF_CHECK(t, build_setup(&lim, p->base, 1u + p->item, 1u + p->base_ability, &setup))) {
            continue;
        }
        if (!DF_CHECK(t, dfi_closure_member_init(&setup, &m))) {
            continue;
        }
        DF_CHECK(t, m.mega_capable == 1u && m.is_mega == 0u);
        DF_CHECK(t, dfi_closure_member_mega_evolve(&m));
        DF_CHECK(t, m.is_mega == 1u && m.item == 1u + p->item);
        DF_CHECK_EQ_U64(t, m.ability, 1u + p->ability);
        DF_CHECK(t, !dfi_closure_member_mega_evolve(&m)); /* once only */
    }
}

/* The public API: every pair is reached from its base forme with its stone, and reports the Mega and its support. */
static void check_api(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (!DF_CHECK(t, ctx != NULL)) {
        return;
    }
    for (size_t i = 0u; i < G51_PAIRS; ++i) {
        const struct g51_pair *p = &pairs[i];
        uint32_t n = 0u;
        if (!DF_CHECK(t, duoforge_data_mega_count(ctx, p->base, &n) == DUOFORGE_OK)) {
            continue;
        }
        uint32_t found = 0u;
        for (uint32_t k = 0u; k < n; ++k) {
            duoforge_mega_info mi;
            if (!DF_CHECK(t, duoforge_data_mega_at(ctx, p->base, k, &mi) == DUOFORGE_OK)) {
                continue;
            }
            if (mi.stone != p->item) {
                continue;
            }
            found += 1u;
            DF_CHECK_EQ_U64(t, mi.mega_species, p->mega);
            DF_CHECK_EQ_U64(t, mi.mega_ability, p->ability);
            DF_CHECK_EQ_U64(t, mi.supported, 1u);
        }
        DF_CHECK_EQ_U64(t, found, 1u);
    }
    duoforge_context_destroy(ctx);
}

static void conf_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
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

static void conf_bundle(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
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

static const df_conf_battle *conf_find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The battle `name` after its first `steps` steps, the reference's draws as the tape; NULL when one fails. */
static duoforge_battle *conf_replay(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, uint32_t steps)
{
    duoforge_battle_setup setup;
    conf_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        conf_bundle(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK) ||
            !DF_CHECK_EQ_U64(t, used, st->tape_len)) {
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

/* The events of one step with the reference's tape, player 0's view; returns the engine's status. */
static duoforge_status conf_step_events(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st,
                                        duoforge_event *events, uint32_t *count)
{
    duoforge_decision_bundle bd;
    conf_bundle(st, b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    static duoforge_event other[DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events, DUOFORGE_MAX_EVENTS, 0u}, {other, DUOFORGE_MAX_EVENTS, 0u}};
    const duoforge_status s =
        dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
    *count = buffers[0].count;
    return s;
}

/* 2. The ignoreEvasion of Keen Eye (dfi_accuracy_check). In g51_keen_eye the Pidgeot (Keen Eye, no stone) uses Hurricane (accuracy
 * 70) on the foe Milotic in step 2, and the reference's accuracy draw is 31: a hit with evasion stage 0. The test raises that foe's
 * evasion stage by six by hand (a stage of +6 would cut the chance to 70 x 3 / 9 = 23.3 and the draw 31 would miss), so the hit
 * stands only if the Keen Eye user ignores the evasion. The tape of the step then still fits: the same hit and the same draws. */
static void check_keen_eye_evasion(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = conf_find("g51_keen_eye");
    if (!DF_CHECK(t, cb != NULL) || !DF_CHECK(t, cb->step_count > 2u)) {
        return;
    }
    duoforge_battle *b = conf_replay(t, ctx, cb, 2u);
    if (b == NULL) {
        return;
    }
    b->sides[1].positions[0].stages[DFI_STAGE_EVASION] = (uint8_t)DFI_STAGE_MAX; /* +6, biased by 12 */
    static duoforge_event events[DUOFORGE_MAX_EVENTS];
    uint32_t n = 0u;
    if (DF_CHECK(t, conf_step_events(ctx, b, &cb->steps[2], events, &n) == DUOFORGE_OK)) {
        uint32_t hits = 0u;
        uint32_t misses = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            if (events[i].kind == DUOFORGE_EVENT_DAMAGE && events[i].position == 2u) {
                hits += 1u; /* the foe Milotic (p2a) takes the Hurricane */
            }
            misses += events[i].kind == DUOFORGE_EVENT_MISS ? 1u : 0u;
        }
        DF_CHECK(t, hits >= 1u);
        DF_CHECK_EQ_U64(t, misses, 0u);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g51");
    check_marks(&t);
    check_no_grass_holder(&t);
    check_pairs(&t);
    check_setups(&t);
    check_api(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_keen_eye_evasion(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
