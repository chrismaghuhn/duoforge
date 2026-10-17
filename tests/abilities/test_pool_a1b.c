/*
 * duoforge.state.pool_a1b (white-box): batch A1b of the Champions-100 track (decision 0015 entry 5dz), POOL build. Nine abilities
 * and one item, each one member of an existing chain of the damage phases (src/combat/mechanics/damage/) or a clause of the burn
 * residual:
 *   Fur Coat, Grass Pelt   ModifyDef (stats.h): x2; x1.5 in Grassy Terrain
 *   Steely Spirit          BasePower (base_power.h, priority 22): x1.5 for a Steel move of the holder or its partner
 *   Analytic               BasePower (priority 21): x5325/4096 when no other active Pokemon still has a move queued
 *   Plus, Minus            ModifySpA (attack.h): x1.5 beside a standing Plus or Minus partner
 *   Stakeout               ModifyAtk/SpA: x2 against a defender that came in this turn (NEWLY_SWITCHED)
 *   Heatproof              ModifyAtk/SpA: x0.5 for a Fire move at the holder; the burn damage halved (the residual)
 *   Light Ball             ModifyAtk/SpA: x2 for a Pikachu holder
 *   Fluffy                 ModifyDamage (modify_damage.h): x2 Fire without contact, x0.5 contact that is not Fire
 *
 * The covering battles fz_5102_* (campaign 5102 of the batch, "data": "pool") are replayed by
 * duoforge.reference.conformance_pool_data against the pinned Showdown. This test shows what the replay does not: that each
 * clause fires where the pin applies it and stays out where it does not. For each case the battle is replayed with its tape up to
 * one step, the holder of the clause (in a position before it) loses it just before that step (its ability now is Keen Eye, which
 * acts on no hit, or its item is gone), and the step is played with the same tape. Stakeout's flag cannot be given to an old target
 * that way (the invariant clears NEWLY_SWITCHED at every TURN boundary), so a hit at a new target and one at an old target stand
 * for it. A case
 * where the clause applies must end with other HP than the recording; a neighbour (the same holder in a hit the clause does not
 * touch) with the same HP. Every case is first played unchanged and must equal the recording. The checked Pokemon takes one hit in
 * the step (and only fixed residual heals or damage), so the comparison is of that hit. The cases were found in the traces by a
 * script of the batch's campaign (the A1b report); the members are named by their base forme, so one that enters in the step is
 * found too.
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

/* ---- the marks and the columns */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_FURCOAT, DFI_ABILITY_GRASSPELT, DFI_ABILITY_STEELYSPIRIT,
                                         DFI_ABILITY_PLUS,    DFI_ABILITY_MINUS,     DFI_ABILITY_STAKEOUT,
                                         DFI_ABILITY_ANALYTIC, DFI_ABILITY_FLUFFY,   DFI_ABILITY_HEATPROOF};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LIGHTBALL] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LIGHTBALL], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_family[DFI_ITEM_LIGHTBALL].family, DFI_ITEM_FAMILY_NONE);
    /* Fur Coat, Grass Pelt, Fluffy and Heatproof are breakable: Mold Breaker is not marked, so no hit ignores them. */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    /* Light Ball's baseSpecies test: Pikachu (dex 25) is one forme of the pool, so the base forme id is the test. */
    uint32_t pikachus = 0u;
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT; ++f) {
        pikachus += dfi_pool_formes[f].dex_num == 25u ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, pikachus, 1u);
    DF_CHECK_EQ_U64(t, dfi_pool_formes[DFI_FORME_PIKACHU].dex_num, 25u);
}

/* ---- the replay with one clause taken away */
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

enum { TAKE_NONE, TAKE_ABILITY, TAKE_ITEM };

typedef struct a1b_case {
    const char *what;      /* the clause and the hit */
    const char *battle;    /* a covering battle */
    uint32_t step;         /* the step of the hit (conformance step index) */
    uint32_t holder_side;  /* the member whose clause is taken: side and base forme */
    uint32_t holder;
    uint32_t take;         /* TAKE_*; the holder is in a position before the step (a tail value of a benched member is invalid) */
    uint32_t checked_side; /* the member whose HP after the step is compared: side and base forme */
    uint32_t checked;
    bool applies;          /* the clause applies to the hit: the HP must differ without it */
} a1b_case;

/* Side 0 is p1, side 1 p2. The members are named by their base forme, so a member that enters in the step itself is found. */
static const a1b_case cases[] = {
    {"Fur Coat: Zen Headbutt (physical) at the holder", "fz_5102_1481", 3u, 1u, DFI_FORME_FURFROU, TAKE_ABILITY, 1u,
     DFI_FORME_FURFROU, true},
    {"Fur Coat: Overdrive (special) at the holder", "fz_5102_1368", 10u, 1u, DFI_FORME_PERSIANALOLA, TAKE_ABILITY, 1u,
     DFI_FORME_PERSIANALOLA, false},
    {"Grass Pelt: U-turn (physical) at the holder in Grassy Terrain", "fz_5102_1368", 1u, 1u, DFI_FORME_GOGOAT, TAKE_ABILITY, 1u,
     DFI_FORME_GOGOAT, true},
    {"Grass Pelt: Crunch (physical) at the holder without a terrain", "fz_5102_1481", 3u, 1u, DFI_FORME_GOGOAT, TAKE_ABILITY, 1u,
     DFI_FORME_GOGOAT, false},
    {"Steely Spirit: the holder's Heavy Slam", "fz_5102_1368", 11u, 0u, DFI_FORME_PERRSERKER, TAKE_ABILITY, 1u,
     DFI_FORME_HOUNDSTONE, true},
    {"Steely Spirit: the partner's Iron Tail (Pikachu beside the holder)", "fz_5102_224", 1u, 0u, DFI_FORME_PERRSERKER, TAKE_ABILITY,
     1u, DFI_FORME_WATCHOG, true},
    {"Steely Spirit: the holder's Close Combat (not Steel)", "fz_5102_1368", 9u, 0u, DFI_FORME_PERRSERKER, TAKE_ABILITY, 1u,
     DFI_FORME_RILLABOOM, false},
    {"Plus: Toxtricity's Overdrive (special) beside Ampharos (Plus)", "fz_5102_873", 2u, 1u, DFI_FORME_TOXTRICITY, TAKE_ABILITY, 0u,
     DFI_FORME_SINISTCHA, true},
    {"Minus: Manectric's Flamethrower (special) beside Toxtricity (Plus)", "fz_5102_1368", 3u, 0u, DFI_FORME_MANECTRIC,
     TAKE_ABILITY, 0u, DFI_FORME_TOXTRICITY, true},
    {"Minus: Manectric's Flamethrower (special) beside Ampharos (Plus)", "fz_5102_757", 4u, 1u, DFI_FORME_MANECTRIC, TAKE_ABILITY,
     1u, DFI_FORME_AMPHAROS, true},
    {"Minus: the partner's Plus taken (Manectric's Flamethrower)", "fz_5102_757", 4u, 1u, DFI_FORME_AMPHAROS, TAKE_ABILITY, 1u,
     DFI_FORME_AMPHAROS, true},
    {"Plus: Ampharos's Thunder Punch (physical) beside Manectric (Minus)", "fz_5102_1368", 2u, 0u, DFI_FORME_AMPHAROS, TAKE_ABILITY,
     1u, DFI_FORME_PERSIANALOLA, false},
    {"Minus: Manectric's Thunderbolt beside a fainted Toxtricity", "fz_5102_873", 6u, 1u, DFI_FORME_MANECTRIC, TAKE_ABILITY, 0u,
     DFI_FORME_THIEVUL, false},
    {"Stakeout: Knock Off at a target that came in this turn", "fz_5102_1481", 5u, 0u, DFI_FORME_THIEVUL, TAKE_ABILITY, 1u,
     DFI_FORME_HOUNDSTONE, true},
    {"Stakeout: Psychic Fangs at a target in since an earlier turn", "fz_5102_873", 5u, 0u, DFI_FORME_MABOSSTIFF, TAKE_ABILITY, 1u,
     DFI_FORME_MANECTRIC, false},
    {"Analytic: Watchog's Flamethrower as the last mover", "fz_5102_873", 1u, 0u, DFI_FORME_WATCHOG, TAKE_ABILITY, 0u,
     DFI_FORME_MABOSSTIFF, true},
    {"Analytic: Starmie's Flash Cannon before another mover", "fz_5102_1481", 1u, 0u, DFI_FORME_STARMIE, TAKE_ABILITY, 1u,
     DFI_FORME_FURFROU, false},
    {"Fluffy: Heat Wave (Fire, no contact) at the holder", "fz_5102_1355", 7u, 1u, DFI_FORME_HOUNDSTONE, TAKE_ABILITY, 1u,
     DFI_FORME_HOUNDSTONE, true},
    {"Fluffy: Heavy Slam (contact, not Fire) at the holder", "fz_5102_1368", 11u, 1u, DFI_FORME_HOUNDSTONE, TAKE_ABILITY, 1u,
     DFI_FORME_HOUNDSTONE, true},
    {"Fluffy: Sludge Bomb (neither) at the holder", "fz_5102_1368", 17u, 1u, DFI_FORME_HOUNDSTONE, TAKE_ABILITY, 1u,
     DFI_FORME_HOUNDSTONE, false},
    {"Fluffy: Flare Blitz (Fire and contact: chainModify(1)) at the holder", "fz_5102_1433", 1u, 1u, DFI_FORME_HOUNDSTONE,
     TAKE_ABILITY, 1u, DFI_FORME_HOUNDSTONE, false},
    {"Heatproof: Flamethrower at the holder", "fz_5102_1481", 3u, 0u, DFI_FORME_SINISTCHA, TAKE_ABILITY, 0u, DFI_FORME_SINISTCHA,
     true},
    {"Heatproof: Leaf Blade (not Fire) at the holder", "fz_5102_1481", 4u, 0u, DFI_FORME_SINISTCHA, TAKE_ABILITY, 0u,
     DFI_FORME_SINISTCHA, false},
    {"Heatproof: the burn residual of the holder", "fz_5102_341", 2u, 0u, DFI_FORME_SINISTCHA, TAKE_ABILITY, 0u,
     DFI_FORME_SINISTCHA, true},
    {"Light Ball: Pikachu's Iron Tail", "fz_5102_873", 1u, 1u, DFI_FORME_PIKACHU, TAKE_ITEM, 1u, DFI_FORME_TOXTRICITY, true},
    {"Light Ball: Charizard's Flamethrower (not a Pikachu)", "fz_5102_1481", 3u, 0u, DFI_FORME_CHARIZARD, TAKE_ITEM, 0u,
     DFI_FORME_SINISTCHA, false},
};

/* The roster index of the member of `side` with base forme `forme`, or DUOFORGE_MAX_ROSTER. */
static uint32_t member_of(const duoforge_battle *b, uint32_t side, uint32_t forme)
{
    for (uint32_t m = 0u; m < b->sides[side].member_count; ++m) {
        if (b->sides[side].members[m].species_id == forme) {
            return m;
        }
    }
    return DUOFORGE_MAX_ROSTER;
}

static bool take(duoforge_battle *b, uint32_t side, uint32_t member, uint32_t what)
{
    if (what == TAKE_NONE) {
        return true;
    }
    bool active = false;
    for (uint32_t slot = 0u; slot < 2u; ++slot) {
        active = active || b->sides[side].positions[slot].occupant == member;
    }
    if (what == TAKE_ABILITY) {
        b->tail.sides[side].ability_now[member] = (uint16_t)(1u + DFI_ABILITY_KEENEYE);
    } else if (what == TAKE_ITEM) {
        b->tail.sides[side].item_now[member] = (uint8_t)DFI_TAIL_ITEM_NONE;
    }
    return active;
}

/* Replays `c` with its clause taken (or not, TAKE_NONE), and returns the checked member's HP after the step and its recorded HP. */
static bool play_case(df_test *t, const duoforge_context *ctx, const a1b_case *c, uint32_t what, uint32_t *hp, uint32_t *want)
{
    const df_conf_battle *cb = find(c->battle);
    if (!DF_CHECK(t, cb != NULL && c->step < cb->step_count)) {
        return false;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return false;
    }
    const uint32_t holder = member_of(b, c->holder_side, c->holder);
    const uint32_t checked = member_of(b, c->checked_side, c->checked);
    bool ok = DF_CHECK(t, holder < DUOFORGE_MAX_ROSTER && checked < DUOFORGE_MAX_ROSTER);
    for (uint32_t si = 0u; si <= c->step && ok; ++si) {
        const df_conf_step *st = &cb->steps[si];
        if (si == c->step) {
            ok = DF_CHECK(t, take(b, c->holder_side, holder, what));
        }
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        ok = ok && DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                   DUOFORGE_OK);
    }
    if (ok) {
        *hp = b->sides[c->checked_side].members[checked].hp;
        *want = cb->steps[c->step].mons[c->checked_side][checked].hp;
    }
    duoforge_battle_destroy(b);
    return ok;
}

static void check_cases(df_test *t, const duoforge_context *ctx)
{
    for (size_t i = 0u; i < sizeof cases / sizeof cases[0]; ++i) {
        const a1b_case *c = &cases[i];
        uint32_t hp = 0u;
        uint32_t want = 0u;
        /* as recorded */
        if (!play_case(t, ctx, c, TAKE_NONE, &hp, &want) || !DF_CHECK_EQ_U64(t, hp, want)) {
            printf("  case %zu (%s): the unchanged replay does not equal the recording\n", i, c->what);
            continue;
        }
        if (!play_case(t, ctx, c, c->take, &hp, &want)) {
            printf("  case %zu (%s): the replay without the clause failed\n", i, c->what);
            continue;
        }
        if (!DF_CHECK(t, (hp != want) == c->applies)) {
            printf("  case %zu (%s): HP %u without the clause, %u recorded\n", i, c->what, (unsigned)hp, (unsigned)want);
        }
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_a1b");
    check_facts(&t);
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_cases(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
