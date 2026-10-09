/*
 * duoforge.state.pool_g45 (white-box): step G45 of the content expansion, six abilities of the simple kind: Steadfast, Moxie,
 * Weak Armor, Telepathy, Volt Absorb and Punk Rock. They are engine rows (ENGINE_ROWS) that src/combat/turn.c reads by id,
 * marked in src/data/support_manifest.c; the recorded POOL battles `g45_*` (tests/reference/specs) replay them, and the
 * conformance tests compare every event of those battles with Showdown. This test checks the marks and the handler column, and
 * replays the battles to the turns where a rule's number is visible in the state:
 *
 *   - g45_steadfast: the flinch of Machamp (a Fake Out in the first turn) raises its Speed stage by 1;
 *   - g45_moxie_double: Krookodile's Earthquake knocks out two foes at once and its Attack stage rises by 2 (the number of faints);
 *   - g45_weak_armor: one Physical hit (Garchomp's Earthquake) lowers Ceruledge's Defense stage by 1 and raises its Speed stage by 2;
 *   - g45_telepathy: the Earthquake of Garchomp does not reach Medicham (its ally, Telepathy): Medicham keeps its HP;
 *   - g45_volt_absorb: a Thunderbolt at full HP is absorbed (no heal, Jolteon stays full); after an Earthquake, the next Thunderbolt
 *     heals Jolteon by a quarter of its maximum HP;
 *   - Punk Rock: g45_punk_rock, Hyper Voice (a sound move) in both directions, is checked by the conformance comparison of its
 *     damage lines (the ability shows no line of its own).
 *
 * Breakable: Telepathy, Volt Absorb and Punk Rock are breakable. No marked ability ignores that flag: Mold Breaker is not marked,
 * Teravolt and Turboblaze are not in the pool, and Mycelium Might is not in the pool either (tests/test_pool_tables.c pins the
 * ids); a move with ignoreAbility is UNMODELED, so it is refused before any of these rules run.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The stage indices of dfi_active_slot.stages (biased by 6): atk 0, def 1, spa 2, spd 3, spe 4. */
#define G45_ATK 0u
#define G45_DEF 1u
#define G45_SPE 4u

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

static void check_marks(df_test *t)
{
    static const uint32_t rows[] = {DFI_ABILITY_STEADFAST, DFI_ABILITY_MOXIE, DFI_ABILITY_WEAKARMOR, DFI_ABILITY_TELEPATHY,
                                    DFI_ABILITY_VOLTABSORB, DFI_ABILITY_PUNKROCK};
    for (size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[rows[i]], DFI_HANDLER_NONE);
    }
    /* the Mold Breaker family, which would ignore the breakable flag of Telepathy, Volt Absorb and Punk Rock, is unmarked */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MOLDBREAKER] == 0u);
}

/* Steadfast: after the team step and the first turn, Machamp (side 1, position 0) was flinched by Fake Out: Speed +1, and it did
 * not move that turn. */
static void check_steadfast(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g45_steadfast", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].stages[G45_SPE], 7u);
    DF_CHECK_EQ_U64(t, b->sides[1].positions[0].stages[G45_ATK], 6u);
    duoforge_battle_destroy(b);
}

/* Moxie: after the first turn, Krookodile (side 0, position 0) knocked out two foes at once: Attack +2. */
static void check_moxie(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g45_moxie_double", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_ATK], 8u);
    /* both foes of the batch are down (members 0 and 1 of side 1: Pikachu and Raichu) */
    DF_CHECK_EQ_U64(t, b->sides[1].members[0].hp, 0u);
    DF_CHECK_EQ_U64(t, b->sides[1].members[1].hp, 0u);
    duoforge_battle_destroy(b);
}

/* Weak Armor: after the first turn, Ceruledge (side 0, position 0) took one Physical hit: Defense -1, Speed +2. */
static void check_weak_armor(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g45_weak_armor", 2u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_DEF], 5u);
    DF_CHECK_EQ_U64(t, b->sides[0].positions[0].stages[G45_SPE], 8u);
    duoforge_battle_destroy(b);
}

/* Telepathy: the Earthquake of Garchomp (side 0, position 0) in the second turn spreads to Medicham (side 0, position 1), which
 * Telepathy stops: its HP is unchanged (the Earthquake would take it without the ability). */
static void check_telepathy(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "g45_telepathy", 3u);
    if (b == NULL) {
        return;
    }
    const dfi_member *medicham = &b->sides[0].members[b->sides[0].positions[1].occupant];
    DF_CHECK_EQ_U64(t, medicham->hp, medicham->hp_max);
    duoforge_battle_destroy(b);
}

/* Volt Absorb: at full HP the first Thunderbolt is absorbed (Jolteon, side 1 position 0, stays at full HP); after the Earthquake
 * of the second turn the third turn's Thunderbolt heals it by a quarter of its maximum HP (the trace: 44 -> 87 of 172). */
static void check_volt_absorb(df_test *t, const duoforge_context *ctx)
{
    /* after the first turn: Raichu's Thunderbolt at full HP is absorbed, Jolteon (side 1, position 0) stays at full HP */
    duoforge_battle *b = replay(t, ctx, "g45_volt_absorb", 2u);
    if (b != NULL) {
        const dfi_member *jolteon = &b->sides[1].members[b->sides[1].positions[0].occupant];
        DF_CHECK_EQ_U64(t, jolteon->hp, jolteon->hp_max);
        duoforge_battle_destroy(b);
    }
    /* after the second turn (Garchomp's Earthquake) and its Leftovers: Jolteon is hurt */
    b = replay(t, ctx, "g45_volt_absorb", 3u);
    if (b == NULL) {
        return;
    }
    const uint32_t before = b->sides[1].members[b->sides[1].positions[0].occupant].hp;
    DF_CHECK(t, before < b->sides[1].members[b->sides[1].positions[0].occupant].hp_max);
    duoforge_battle_destroy(b);
    /* the third turn: Volt Absorb heals a quarter of the maximum HP (43 of 172), then Leftovers a sixteenth (10) */
    b = replay(t, ctx, "g45_volt_absorb", 4u);
    if (b == NULL) {
        return;
    }
    const dfi_member *jolteon = &b->sides[1].members[b->sides[1].positions[0].occupant];
    DF_CHECK_EQ_U64(t, jolteon->hp, before + jolteon->hp_max / 4u + jolteon->hp_max / 16u);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g45");
    check_marks(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_steadfast(&t, ctx);
    check_moxie(&t, ctx);
    check_weak_armor(&t, ctx);
    check_telepathy(&t, ctx);
    check_volt_absorb(&t, ctx);
    return df_test_end(&t);
}
