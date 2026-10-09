/*
 * duoforge.state.pool_g59 (white-box): step G59, six Mega abilities and their six Mega Stones (decision 0015 5bh).
 *
 *   Blastoise-Mega   Mega Launcher   pulse moves x1.5 (BasePower, priority 19)
 *   Mawile-Mega      Huge Power      Attack x2 (ModifyAtk, priority 5)
 *   Venusaur-Mega    Thick Fat       Ice and Fire moves at the holder x0.5 (ModifyAtk and ModifySpA, the defender's)
 *   Pyroar-Mega      Fire Mane       Fire moves of the holder x1.5 (ModifyAtk and ModifySpA, priority 5)
 *   Scovillain-Mega  Spicy Spray     a damaging hit burns the attacker (DamagingHit, no roll, no contact test)
 *   Meganium-Mega    Mega Sol        the holder's Fire x1.5, Water x0.5 (WeatherModifyDamage, whatever the weather)
 *
 * The recorded battles (g59_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data, which compares every
 * event with the reference. Here are the facts that it does not show:
 *
 *   - the marks: the six abilities and six stones; their base abilities are marked; Mold Breaker, which would ignore the
 *     `breakable` flag of Thick Fat, is not (no interaction is implemented, none is needed);
 *   - the six Mega formes and their stones (dfi_mega_of), their abilities, and the support of each pair;
 *   - the public static flag PULSE that Mega Launcher reads: the pulse moves of the pool carry it, the others do not;
 *   - Mega Sol's refusal (dfi_mega_sol_refused): the recorded Meganium-Mega battle g59_mega_sol is played in sun, and the same
 *     battle with the field's weather changed to rain is refused (E_UNSUPPORTED) at Solar Beam and at Weather Ball, its two
 *     weather-reading moves, and played as recorded when the weather is not changed.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/damage_chain.h"
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

/* ---- the marks, the Mega formes and the stones */
static void check_facts(df_test *t)
{
    static const uint32_t abilities[] = {DFI_ABILITY_MEGALAUNCHER, DFI_ABILITY_HUGEPOWER, DFI_ABILITY_THICKFAT,
                                         DFI_ABILITY_FIREMANE, DFI_ABILITY_SPICYSPRAY, DFI_ABILITY_MEGASOL};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE); /* an engine row: read by id */
        DF_CHECK_EQ_U64(t, dfi_pool_ability_family[abilities[i]].family, DFI_ABILITY_FAMILY_NONE);
    }
    static const uint32_t items[] = {DFI_ITEM_BLASTOISINITE, DFI_ITEM_MAWILITE, DFI_ITEM_VENUSAURITE, DFI_ITEM_PYROARITE,
                                     DFI_ITEM_SCOVILLAINITE, DFI_ITEM_MEGANIUMITE};
    for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
        DF_CHECK(t, dfi_support.items[items[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[items[i]], DFI_HANDLER_NONE); /* mark only */
    }

    /* the Mega of each stone's base forme, the Mega's ability, and the support of the pair (its base abilities are marked) */
    static const struct {
        uint32_t base, item, mega, ability, base_ability_a, base_ability_b;
    } pairs[] = {
        {DFI_FORME_BLASTOISE, DFI_ITEM_BLASTOISINITE, DFI_FORME_BLASTOISEMEGA, DFI_ABILITY_MEGALAUNCHER, DFI_ABILITY_TORRENT,
         DFI_ABILITY_RAINDISH},
        {DFI_FORME_MAWILE, DFI_ITEM_MAWILITE, DFI_FORME_MAWILEMEGA, DFI_ABILITY_HUGEPOWER, DFI_ABILITY_HYPERCUTTER,
         DFI_ABILITY_INTIMIDATE},
        {DFI_FORME_VENUSAUR, DFI_ITEM_VENUSAURITE, DFI_FORME_VENUSAURMEGA, DFI_ABILITY_THICKFAT, DFI_ABILITY_OVERGROW,
         DFI_ABILITY_CHLOROPHYLL},
        {DFI_FORME_PYROAR, DFI_ITEM_PYROARITE, DFI_FORME_PYROARMEGA, DFI_ABILITY_FIREMANE, DFI_ABILITY_UNNERVE,
         DFI_ABILITY_MOXIE},
        {DFI_FORME_SCOVILLAIN, DFI_ITEM_SCOVILLAINITE, DFI_FORME_SCOVILLAINMEGA, DFI_ABILITY_SPICYSPRAY, DFI_ABILITY_CHLOROPHYLL,
         DFI_ABILITY_CHLOROPHYLL},
        {DFI_FORME_MEGANIUM, DFI_ITEM_MEGANIUMITE, DFI_FORME_MEGANIUMMEGA, DFI_ABILITY_MEGASOL, DFI_ABILITY_OVERGROW,
         DFI_ABILITY_OVERGROW},    };
    for (size_t i = 0u; i < sizeof pairs / sizeof pairs[0]; ++i) {
        const uint32_t mega = dfi_mega_of(pairs[i].base, 1u + pairs[i].item);
        DF_CHECK_EQ_U64(t, mega, pairs[i].mega);
        DF_CHECK_EQ_U64(t, dfi_pool_formes[mega].ability, pairs[i].ability);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, pairs[i].base, 1u + pairs[i].item));
        DF_CHECK(t, dfi_support.abilities[pairs[i].base_ability_a] != 0u);
        DF_CHECK(t, dfi_support.abilities[pairs[i].base_ability_b] != 0u);
    }
    /* the Mega Stones are the stones of their own formes only */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_MEGANIUM, 1u + DFI_ITEM_VENUSAURITE), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_VENUSAUR, 1u + DFI_ITEM_MEGANIUMITE), DFI_FORME_NONE);

    /* what stays unmarked: Mold Breaker (no breakable ability of the step is ignored), and the Mega formes of the other stones */
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER], 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MOLDBREAKER], DFI_HANDLER_UNMODELED);
}

/* ---- Mega Launcher reads the public static flag PULSE of the pool row (decision 0020) */
static void check_pulse(df_test *t)
{
    static const uint32_t pulse[] = {DFI_MOVE_AURASPHERE, DFI_MOVE_DARKPULSE, DFI_MOVE_WATERPULSE};
    for (size_t i = 0u; i < sizeof pulse / sizeof pulse[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_static_flags[pulse[i]] & DUOFORGE_MOVE_STATIC_FLAG_PULSE) != 0u);
    }
    DF_CHECK_EQ_U64(t, dfi_pool_move_static_flags[DFI_MOVE_SOLARBEAM] & DUOFORGE_MOVE_STATIC_FLAG_PULSE, 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_move_static_flags[DFI_MOVE_SUNNYDAY] & DUOFORGE_MOVE_STATIC_FLAG_PULSE, 0u);
}

/* ---- Mega Sol's refusal: the recorded battle g59_mega_sol, played as recorded and with the field's weather changed */
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

/* The steps of g59_mega_sol (step 0 is the team selection): Sunny Day, then Solar Beam with the Mega Evolution, then Weather
 * Ball. The field's weather is changed to rain before the step with the move `which` (the step index), or not at all. */
#define MS_SOLAR_STEP 2u
#define MS_WEATHER_STEP 3u
#define NO_CHANGE 0xffffffffu

static duoforge_status play_ms(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t rain_before)
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
        if (si == rain_before) {
            b->weather = (uint8_t)DFI_WEATHER_RAIN;
            b->weather_turns = (uint8_t)DFI_FIELD_TURNS_MAX;
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

static void check_mega_sol(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g59_mega_sol");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > MS_WEATHER_STEP)) {
        duoforge_context_destroy(ctx);
        return;
    }
    /* as recorded, in sun: Solar Beam takes no charge turn and Weather Ball is Fire, both under Mega Sol and the sun alike */
    DF_CHECK_EQ_U64(t, play_ms(t, ctx, cb, NO_CHANGE), DUOFORGE_OK);
    /* the field's weather is rain when the holder's Solar Beam or Weather Ball is used: Mega Sol's weather is sun there, the
     * engine reads rain for those two moves, so the step is refused, not played */
    DF_CHECK_EQ_U64(t, play_ms(t, ctx, cb, MS_SOLAR_STEP), DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, play_ms(t, ctx, cb, MS_WEATHER_STEP), DUOFORGE_E_UNSUPPORTED);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g59");
    check_facts(&t);
    check_pulse(&t);
    check_mega_sol(&t);
    return df_test_end(&t);
}
