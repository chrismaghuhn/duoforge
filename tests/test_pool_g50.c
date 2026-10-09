/*
 * duoforge.state.pool_g50 (white-box): step G50 of the content expansion, Double Shock (decision 0025, items 1, 2 and 5).
 *
 * Double Shock fails without the Electric type (-fail and [still], data/moves.ts:3954-3959), and after a hit its self effect
 * sets the first type to ??? (soak_type DFI_TAIL_TYPE2_TYPELESS) with the second type in type2; the event is TYPE_CHANGE with
 * detail DUOFORGE_TYPE_NONE and amount the second type id + 1 (Fighting: 6). Only Pawmot (Electric and Fighting) is played: every
 * other shape with the Electric type is E_UNSUPPORTED. The recorded battles (g50_double_shock_*) are replayed through the step
 * with the reference's draws (duoforge.reference.conformance_pool_data compares the lines); here is what they do not show:
 *
 *   - the tail's soak type and second type of Pawmot after every step (rows derived from the committed traces: Double Shock
 *     sets ??? / Fighting, Soak replaces both with Water, switching out resets them);
 *   - the invariants of the typeless slot: DFI_TAIL_TYPE2_TYPELESS only with a second type in 1..18 on a standing member;
 *   - the two refused shapes (Electric after Soak; Electric as the second type), E_UNSUPPORTED from a step;
 *   - the public view of the typeless position: TYPE_CHANGED set, type_now = {0, 6} (no type, then Fighting);
 *   - the codec round trip of a state whose soak type is 255 is byte-equal (encode, decode, encode).
 */
#include <stdio.h>
#include <stdlib.h>
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

static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_DOUBLESHOCK] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DOUBLESHOCK].special, DFI_SPECIAL_DOUBLE_SHOCK);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DOUBLESHOCK].base_power, 120u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DOUBLESHOCK].accuracy, 100u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DOUBLESHOCK].type, DFI_TYPE_ELECTRIC);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_DOUBLESHOCK].category, DFI_CATEGORY_PHYSICAL);
    /* the Champions mod's punch flag: Iron Fist boosts the move (step G34) */
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_DOUBLESHOCK] & DFI_MOVE_FLAG2_PUNCH) != 0u);
    /* the public values of decision 0025 */
    DF_CHECK_EQ_U64(t, DUOFORGE_TYPE_NONE, 255u);
    DF_CHECK_EQ_U64(t, DFI_TAIL_TYPE2_TYPELESS, 255u);
    DF_CHECK_EQ_U64(t, DUOFORGE_TYPE_FIGHTING + 1u, 6u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_IRONFIST] != 0u); /* Pawmot's only usable ability */
}

/* Pawmot's soak type and second type after each step: [soak_type, type2] of side 0 member 0. Step 0 is the team selection.
 * Derived from the committed traces: the fail battle's first Double Shock hits (the rest fail), the switch battle's Pawmot is
 * replaced at step 3 (the replacement of the request after the foe's switch at step 2; the battle ends there), the soak
 * battle's Soak comes before Double Shock (the second fails for lack of Electric). */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t soak;
    uint32_t type2;
} rows[] = {
    {"g50_double_shock_fail", 0u, 0u, 0u},
    {"g50_double_shock_fail", 1u, 255u, 6u},
    {"g50_double_shock_fail", 2u, 255u, 6u},
    {"g50_double_shock_fail", 3u, 255u, 6u},
    {"g50_double_shock_switch", 0u, 0u, 0u},
    {"g50_double_shock_switch", 1u, 255u, 6u},
    {"g50_double_shock_switch", 2u, 255u, 6u},
    {"g50_double_shock_switch", 3u, 0u, 0u},
    {"g50_double_shock_soak", 0u, 0u, 0u},
    {"g50_double_shock_soak", 1u, 18u, 0u},
    {"g50_double_shock_soak", 2u, 18u, 0u},
    {"g50_double_shock_ground", 0u, 0u, 0u},
    {"g50_double_shock_ground", 1u, 255u, 6u},
};

static const char *const names[] = {"g50_double_shock_fail", "g50_double_shock_switch", "g50_double_shock_soak",
                                    "g50_double_shock_ground"};

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

/* A battle after its team selection (step 0 of the recording): Pawmot is the lead of side 0. */
static duoforge_battle *lead_battle(df_test *t, duoforge_context *ctx, const df_conf_battle *cb)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[0], b, &bd);
    duoforge_step_result res;
    uint32_t used = 0u;
    if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[cb->steps[0].tape_off], cb->steps[0].tape_len, &used, &res) ==
                          DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        return NULL;
    }
    return b;
}

/* The invariants of the typeless slot (TAIL_MEMBER): 255 only with a second type in 1..18, on a standing member. */
static void check_invariants(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g50_double_shock_fail");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle *b = lead_battle(t, ctx, cb);
    if (b == NULL) {
        return;
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    b->tail.sides[0].soak_type[0] = DFI_TAIL_TYPE2_TYPELESS;
    b->tail.sides[0].type2[0] = 0u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK); /* no second type */
    b->tail.sides[0].type2[0] = DFI_TYPE_FIGHTING + 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    b->tail.sides[0].type2[0] = (uint8_t)(DFI_TYPE_COUNT + 1u); /* 19 is not a type */
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.sides[0].type2[0] = DFI_TAIL_TYPE2_TYPELESS; /* a typeless second type (Burn Up later): not this step */
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    b->tail.sides[0].type2[0] = DFI_TYPE_FIGHTING + 1u;
    b->tail.sides[0].soak_type[0] = DFI_TYPE_COUNT + 1u; /* 19, not a soak type either */
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    /* a member that is not on the field keeps no typeless slot */
    b->tail.sides[0].soak_type[0] = DFI_TAIL_TYPE2_TYPELESS;
    b->tail.sides[0].type2[0] = DFI_TYPE_FIGHTING + 1u;
    b->sides[0].positions[0].occupant = 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) != DUOFORGE_OK);
    duoforge_battle_destroy(b);
}

/* The two shapes that Double Shock refuses (decision 0025 item 2): Electric after Soak, and Electric as the second type. The
 * first step is Pawmot's Double Shock (the recorded step 1 of the fail battle); the battle is fresh for each shape. */
static void check_unsupported(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g50_double_shock_fail");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    static const struct {
        uint32_t soak;
        uint32_t type2;
        const char *what;
    } shapes[] = {
        {DFI_TYPE_ELECTRIC + 1u, 0u, "Electric alone (after a Soak-like set)"},
        {DFI_TAIL_TYPE2_TYPELESS, DFI_TYPE_ELECTRIC + 1u, "Electric as the second type"},
    };
    for (size_t k = 0; k < sizeof shapes / sizeof shapes[0]; ++k) {
        duoforge_battle *b = lead_battle(t, ctx, cb);
        if (b == NULL) {
            continue;
        }
        b->tail.sides[0].soak_type[0] = (uint8_t)shapes[k].soak;
        b->tail.sides[0].type2[0] = (uint8_t)shapes[k].type2;
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        duoforge_decision_bundle bd;
        bundle_of(&cb->steps[1], b, &bd);
        duoforge_step_result res;
        const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
        if (!DF_CHECK(t, st == DUOFORGE_E_UNSUPPORTED)) {
            fprintf(stderr, "  %s: %s gave %s\n", shapes[k].what, "Double Shock", duoforge_status_name(st));
        }
        duoforge_battle_destroy(b);
    }
}

/* The view of the typeless position: TYPE_CHANGED with type_now {0, Fighting + 1}, and the codec round trip with the 255 byte. */
static void check_view_and_codec(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g50_double_shock_fail");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle *b = lead_battle(t, ctx, cb);
    if (b == NULL) {
        return;
    }
    b->tail.sides[0].soak_type[0] = DFI_TAIL_TYPE2_TYPELESS;
    b->tail.sides[0].type2[0] = DFI_TYPE_FIGHTING + 1u;
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_observation_ext ext[2];
    for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
        DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK);
        const duoforge_position_ext *p = &ext[viewer].sides[0].positions[0];
        DF_CHECK(t, (p->volatiles & DUOFORGE_POSITION_EXT_TYPE_CHANGED) != 0u);
        DF_CHECK_EQ_U64(t, p->type_now[0], 0u);
        DF_CHECK_EQ_U64(t, p->type_now[1], DUOFORGE_TYPE_FIGHTING + 1u);
    }
    /* the codec: encode, decode, encode again: byte-equal, and the decoded state keeps the 255 */
    uint8_t enc[DF_STATE_ENCODED_MAX];
    const size_t n = df_encode_n(ctx, b, enc);
    uint8_t *in = df_heap_copy(enc, n);
    duoforge_battle *made = NULL;
    const duoforge_status ds = duoforge_battle_create_decoded(ctx, in, n, &made);
    free(in);
    if (!DF_CHECK(t, ds == DUOFORGE_OK && made != NULL)) {
        duoforge_battle_destroy(b);
        return;
    }
    DF_CHECK_EQ_U64(t, made->tail.sides[0].soak_type[0], DFI_TAIL_TYPE2_TYPELESS);
    DF_CHECK_EQ_U64(t, made->tail.sides[0].type2[0], DFI_TYPE_FIGHTING + 1u);
    uint8_t enc2[DF_STATE_ENCODED_MAX];
    const size_t n2 = df_encode_n(ctx, made, enc2);
    DF_CHECK_EQ_U64(t, n2, n);
    DF_CHECK(t, memcmp(enc, enc2, n) == 0);
    duoforge_battle_destroy(made);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g50");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    uint32_t compared = 0u;
    uint32_t typeless_seen = 0u;
    check_facts(&t);
    check_invariants(&t, ctx);
    check_unsupported(&t, ctx);
    check_view_and_codec(&t, ctx);
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(&t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", names[n], duoforge_status_name(created));
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(&t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                  DUOFORGE_OK)) {
                break;
            }
            int found = 0;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0] && !found; ++r) {
                if (strcmp(rows[r].battle, names[n]) != 0 || rows[r].step != si) {
                    continue;
                }
                found = 1;
                DF_CHECK_EQ_U64(&t, b->tail.sides[0].soak_type[0], rows[r].soak);
                DF_CHECK_EQ_U64(&t, b->tail.sides[0].type2[0], rows[r].type2);
                typeless_seen += rows[r].soak == DFI_TAIL_TYPE2_TYPELESS ? 1u : 0u;
                compared += 1u;
            }
            if (!found) {
                DF_CHECK(&t, 0);
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
            }
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(&t, compared, (uint32_t)(sizeof rows / sizeof rows[0]));
    DF_CHECK(&t, typeless_seen != 0u);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
