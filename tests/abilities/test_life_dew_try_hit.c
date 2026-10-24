/*
 * duoforge.abilities.life_dew_try_hit (white-box): decision 0015 entry 5ed (issue 641), docs/mechanics/abilities/5ed-life-dew-
 * runs-the-tryhit-abilities.md. Life Dew (Water, Status, target allies) reaches its targets through trySpreadMoveHit, so its
 * ally's TryHit abilities run before the heal (dfi_run_heal_move): Good as Gold is -immune, Water Absorb heals through the
 * ability ([of] the user) or is -immune at full HP; the ally leaves the targets and the [spread] list. The recorded battles
 * life_dew_good_as_gold and life_dew_water_absorb show the pin's lines (conformance_pool_data); this test shows that the hook is
 * the ally's ability: the same steps with the ally's ability changed to one without a TryHit for the move (Defiant, Volt
 * Absorb) heal the ally by the move, the user's own Good as Gold or Water Absorb is not asked (`target !== source`), and a
 * Water Absorb ally under Heal Block is -immune (its heal refused), where A2a refused the step.
 *
 * Decision 0015 entry 5ee (issue 672), docs/mechanics/moves/5ee-life-dew-misses-a-semi-invulnerable-ally.md: the Invulnerability
 * step comes first (hitStepInvulnerabilityEvent), so an ally in the charge of Phantom Force is -miss|user|ally and is not healed
 * (life_dew_phantom_force), and its TryHit abilities (Good as Gold, Water Absorb) are not asked. Its neighbours: the same ally
 * after its locked turn is healed, and No Guard on the ally or on the user lets the move reach it.
 */
#include <stdbool.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/formats/reg-mc/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define AB(x) (1u + DFI_ABILITY_##x)

/* What one replayed step showed at the user (position 0) and its ally (position 1), player 0's view. */
typedef struct life_dew_seen {
    duoforge_status status;
    bool tape_used;
    uint32_t move_lines;   /* Life Dew's move lines */
    uint32_t spread_flags; /* of them, with [spread] */
    uint32_t spread_mask;  /* the [spread] slots of the last one */
    uint32_t user_move_heals;
    uint32_t user_fails;
    uint32_t ally_move_heals;
    uint32_t ally_ability_heals; /* cause ABILITY, id2 `ability`, [of] the user */
    uint32_t ally_immune;        /* cause ABILITY, id2 `ability` */
    uint32_t ally_fails;         /* -fail at the ally (full HP) */
    uint32_t ally_misses;        /* -miss|user|ally */
    uint32_t miss_flags;         /* Life Dew's move lines with [miss] */
    uint32_t first_ally_line;    /* the index of the ally's first heal, immune, fail or -miss line after the move line */
    uint32_t first_user_line;    /* the index of the user's first heal or fail line after the move line */
} life_dew_seen;

static void run_life_dew_step(const duoforge_context *ctx, duoforge_battle *b, const df_conf_step *st, uint32_t ability,
                              life_dew_seen *out)
{
    static df_conf_run run;
    df_conf_run_step(ctx, b, st, &run);
    memset(out, 0, sizeof *out);
    out->status = run.status;
    out->tape_used = run.used == st->tape_len;
    out->first_ally_line = UINT32_MAX;
    out->first_user_line = UINT32_MAX;
    bool after = false;
    for (uint32_t i = 0u; i < run.count; ++i) {
        const duoforge_event *e = &run.events[i];
        if (e->kind == DUOFORGE_EVENT_MOVE) {
            after = e->id == DFI_MOVE_LIFEDEW && e->position == 0u;
            if (after) {
                out->move_lines += 1u;
                out->spread_flags += (e->flags & DUOFORGE_EVENT_FLAG_SPREAD) != 0u ? 1u : 0u;
                out->spread_mask = e->amount;
                out->miss_flags += (e->flags & DUOFORGE_EVENT_FLAG_MISS) != 0u ? 1u : 0u;
            }
            continue;
        }
        if (!after) {
            continue;
        }
        if (e->position == 0u && (e->kind == DUOFORGE_EVENT_HEAL || e->kind == DUOFORGE_EVENT_FAIL)) {
            out->user_move_heals += e->kind == DUOFORGE_EVENT_HEAL && e->cause == DUOFORGE_CAUSE_NONE ? 1u : 0u;
            out->user_fails += e->kind == DUOFORGE_EVENT_FAIL ? 1u : 0u;
            out->first_user_line = out->first_user_line == UINT32_MAX ? i : out->first_user_line;
        }
        if (e->kind == DUOFORGE_EVENT_MISS && e->position == 0u && e->other == 1u) {
            out->ally_misses += 1u;
            out->first_ally_line = out->first_ally_line == UINT32_MAX ? i : out->first_ally_line;
        }
        if (e->position == 1u && e->kind == DUOFORGE_EVENT_FAIL) {
            out->ally_fails += 1u;
            out->first_ally_line = out->first_ally_line == UINT32_MAX ? i : out->first_ally_line;
        }
        if (e->position == 1u && (e->kind == DUOFORGE_EVENT_HEAL || e->kind == DUOFORGE_EVENT_IMMUNE)) {
            if (e->kind == DUOFORGE_EVENT_HEAL && e->cause == DUOFORGE_CAUSE_NONE) {
                out->ally_move_heals += 1u;
            } else if (e->kind == DUOFORGE_EVENT_HEAL && e->cause == DUOFORGE_CAUSE_ABILITY && e->id2 == ability &&
                       e->other == 0u) {
                out->ally_ability_heals += 1u;
            } else if (e->kind == DUOFORGE_EVENT_IMMUNE && e->cause == DUOFORGE_CAUSE_ABILITY && e->id2 == ability) {
                out->ally_immune += 1u;
            }
            out->first_ally_line = out->first_ally_line == UINT32_MAX ? i : out->first_ally_line;
        }
    }
}

/* The battle `name` replayed up to step `step`, then that step on a copy whose user (`user_ability`) or ally (`ally_ability`)
 * has another ability (0: unchanged) and whose ally is under Heal Block for `ally_heal_block` turns (0: as recorded). */
static bool life_dew_variant_hb(df_test *t, const duoforge_context *ctx, const char *name, uint32_t step, uint32_t ally_forme,
                                uint32_t user_ability, uint32_t ally_ability, uint32_t ally_heal_block, uint32_t seen_ability,
                                life_dew_seen *out)
{
    const df_conf_battle *cb = df_conf_find(name);
    if (!DF_CHECK(t, cb != NULL && cb->step_count > step)) {
        return false;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, step);
    if (b == NULL) {
        return false;
    }
    const uint32_t milotic = df_conf_member_of(b, 0u, DFI_FORME_MILOTIC);
    const uint32_t ally = df_conf_member_of(b, 0u, ally_forme);
    bool ok = DF_CHECK(t, milotic < DUOFORGE_MAX_ROSTER && ally < DUOFORGE_MAX_ROSTER);
    if (ok) {
        if (user_ability != 0u) {
            b->tail.sides[0].ability_now[milotic] = (uint16_t)user_ability;
        }
        if (ally_ability != 0u) {
            b->tail.sides[0].ability_now[ally] = (uint16_t)ally_ability;
        }
        if (ally_heal_block != 0u) {
            b->tail.sides[0].positions[1].heal_block_turns = (uint8_t)ally_heal_block; /* the ally stands at p1b */
        }
        ok = DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    }
    if (ok) {
        run_life_dew_step(ctx, b, &cb->steps[step], seen_ability, out);
        ok = DF_CHECK(t, out->status == DUOFORGE_OK) && DF_CHECK(t, out->tape_used) && DF_CHECK_EQ_U64(t, out->move_lines, 1u) &&
             DF_CHECK_EQ_U64(t, out->spread_flags, 1u);
    }
    duoforge_battle_destroy(b);
    return ok;
}

static bool life_dew_variant(df_test *t, const duoforge_context *ctx, const char *name, uint32_t step, uint32_t ally_forme,
                             uint32_t user_ability, uint32_t ally_ability, uint32_t seen_ability, life_dew_seen *out)
{
    return life_dew_variant_hb(t, ctx, name, step, ally_forme, user_ability, ally_ability, 0u, seen_ability, out);
}

/* 1. Good as Gold (life_dew_good_as_gold; step 1: Milotic at full HP, step 2: Milotic hurt, Gholdengo hurt both times). */
static void check_good_as_gold(df_test *t, const duoforge_context *ctx)
{
    life_dew_seen s;
    /* Step 1: the ally is -immune before the user's -fail, the [spread] list is empty (no target left a heal). */
    if (life_dew_variant(t, ctx, "life_dew_good_as_gold", 1u, DFI_FORME_GHOLDENGO, 0u, 0u, AB(GOODASGOLD), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_immune, 1u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_fails, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.spread_mask, 0u);
    }
    /* Step 2: the ally is -immune, the user heals, the [spread] list is the user's slot alone. */
    if (life_dew_variant(t, ctx, "life_dew_good_as_gold", 2u, DFI_FORME_GHOLDENGO, 0u, 0u, AB(GOODASGOLD), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_immune, 1u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* The ally without a TryHit for the move (Defiant): healed by the move, both slots in the [spread] list. */
    if (life_dew_variant(t, ctx, "life_dew_good_as_gold", 2u, DFI_FORME_GHOLDENGO, 0u, AB(DEFIANT), AB(GOODASGOLD), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_immune, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 3u);
    }
    /* The user's own Good as Gold is not asked (target === source): the user heals; the ally keeps its own. */
    if (life_dew_variant(t, ctx, "life_dew_good_as_gold", 2u, DFI_FORME_GHOLDENGO, AB(GOODASGOLD), 0u, AB(GOODASGOLD), &s)) {
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.ally_immune, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
}

/* 2. Water Absorb (life_dew_water_absorb; step 1: Vaporeon hurt, step 2: Vaporeon at full HP, Milotic hurt both times). */
static void check_water_absorb(df_test *t, const duoforge_context *ctx)
{
    life_dew_seen s;
    /* Step 1: the ally heals through Water Absorb with [of] the user, before the user's heal by the move. */
    if (life_dew_variant(t, ctx, "life_dew_water_absorb", 1u, DFI_FORME_VAPOREON, 0u, 0u, AB(WATERABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 1u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.ally_immune, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* Step 2: the ally at full HP is -immune. */
    if (life_dew_variant(t, ctx, "life_dew_water_absorb", 2u, DFI_FORME_VAPOREON, 0u, 0u, AB(WATERABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_immune, 1u);
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* The neighbour of the same TryHit branch for another type (Volt Absorb): the Water move heals the ally by the move. */
    if (life_dew_variant(t, ctx, "life_dew_water_absorb", 1u, DFI_FORME_VAPOREON, 0u, AB(VOLTABSORB), AB(VOLTABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 0u);
        DF_CHECK_EQ_U64(t, s.ally_immune, 0u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 3u);
    }
    /* Step 1 with the hurt ally under Heal Block (Psychic Noise's two turns): Water Absorb's this.heal is refused by Heal Block's
     * onTryHeal (data/moves.ts:8324-8332, `return false`), so the handler shows -immune|ally|[from] ability: Water Absorb
     * (data/abilities.ts:5364-5370) and still stops the move for the ally; the user heals by the move. A2a refused this. */
    if (life_dew_variant_hb(t, ctx, "life_dew_water_absorb", 1u, DFI_FORME_VAPOREON, 0u, 0u, 2u, AB(WATERABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_immune, 1u);
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* The user's own Water Absorb is not asked (target === source): the user heals by the move. */
    if (life_dew_variant(t, ctx, "life_dew_water_absorb", 1u, DFI_FORME_VAPOREON, AB(WATERABSORB), 0u, AB(WATERABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 1u);
    }
}

/* 3. The Invulnerability step (life_dew_phantom_force; step 1: Milotic at full HP, Gengar charging; step 2: both hurt, Gengar's
 * locked Phantom Force has run; step 3: both hurt, Gengar charging again). */
static void check_invulnerable(df_test *t, const duoforge_context *ctx)
{
    life_dew_seen s;
    /* Step 1: -miss|Milotic|Gengar before the user's -fail; no [miss] on the [spread] line, no line at the ally, no slot. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 1u, DFI_FORME_GENGAR, 0u, 0u, 0u, &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 1u);
        DF_CHECK_EQ_U64(t, s.ally_fails, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_fails, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.miss_flags, 0u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 0u);
    }
    /* Step 3: the hurt charging ally is -miss and not healed, the user heals, the [spread] list is the user's slot alone. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 3u, DFI_FORME_GENGAR, 0u, 0u, 0u, &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 1u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK(t, s.first_ally_line < s.first_user_line);
        DF_CHECK_EQ_U64(t, s.miss_flags, 0u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* Step 2, the control: the locked turn removed the volatile before Life Dew, so both are healed, both slots in [spread]. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 2u, DFI_FORME_GENGAR, 0u, 0u, 0u, &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 3u);
    }
    /* The order: the Invulnerability step comes before the TryHit abilities (sim/battle-actions.ts:556-559). Step 3 with the
     * charging ally given Good as Gold or Water Absorb: -miss only, no -immune and no ability heal. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 3u, DFI_FORME_GENGAR, 0u, AB(GOODASGOLD), AB(GOODASGOLD), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 1u);
        DF_CHECK_EQ_U64(t, s.ally_immune, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 3u, DFI_FORME_GENGAR, 0u, AB(WATERABSORB), AB(WATERABSORB), &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 1u);
        DF_CHECK_EQ_U64(t, s.ally_immune, 0u);
        DF_CHECK_EQ_U64(t, s.ally_ability_heals, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 0u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 1u);
    }
    /* Step 3 with No Guard on the charging ally (onAnyInvulnerability returns 0, data/abilities.ts:2970-2974): no -miss, the
     * ally is healed by the move. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 3u, DFI_FORME_GENGAR, 0u, AB(NOGUARD), 0u, &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 0u);
        DF_CHECK_EQ_U64(t, s.ally_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.user_move_heals, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 3u);
    }
    /* Step 1 with No Guard on the user: the move reaches the charging ally at full HP, which fails as the user does. */
    if (life_dew_variant(t, ctx, "life_dew_phantom_force", 1u, DFI_FORME_GENGAR, AB(NOGUARD), 0u, 0u, &s)) {
        DF_CHECK_EQ_U64(t, s.ally_misses, 0u);
        DF_CHECK_EQ_U64(t, s.ally_fails, 1u);
        DF_CHECK_EQ_U64(t, s.user_fails, 1u);
        DF_CHECK_EQ_U64(t, s.spread_mask, 0u);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.abilities.life_dew_try_hit");
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        check_good_as_gold(&t, kp);
        check_water_absorb(&t, kp);
        check_invulnerable(&t, kp);
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
