/*
 * duoforge.state.pool_g83 (white-box): step G83 of the content expansion, Bulletproof, Rivalry, Leaf Guard and Iron Ball
 * (decision 0015 entry 5bt). All four are engine rows read by id; the turn code reads them in these places:
 *
 *   - Bulletproof (data/abilities.ts:480-491, onTryHit): a move with the bullet flag stops at its holder, -immune with
 *     [from] ability: Bulletproof, no accuracy draw (dfi_try_hit_abilities, before the immunity and accuracy steps);
 *   - Rivalry (data/abilities.ts:3881-3898, onBasePowerPriority 24): x1.25 for the same gender, x0.75 for the other, nothing
 *     for a genderless side (the base power chain, before Iron Fist's 23);
 *   - Leaf Guard (data/abilities.ts:2291-2310): in sun its holder's statuses are refused, the own move's with -immune, and the
 *     Yawn volatile is refused with -immune (dfi_try_status, dfi_yawn);
 *   - Iron Ball (data/items.ts:3050-3067): grounded whatever its types (dfi_grounded, and the Ground immunity of dfi_try_hit_abilities),
 *     Speed x0.5 (the item chain of dfi_speed_key).
 *
 * The recorded battles (tests/reference/specs/g83_*) carry the reference's lines for each row, and test_conformance compares every
 * step with them. This test replays them to the end and checks the marks.
 *
 *   - g83_bulletproof_bullets: Chesnaught (Bulletproof) takes Shadow Ball and Sludge Bomb (-immune, twice), not Thunderbolt;
 *   - g83_ironball_ground: Staraptor (Iron Ball, Flying) takes Earthquake from two Pokemon;
 *   - g83_rivalry_gender: Luxray (Rivalry) hits a female Pyroar (x0.75) and a male Luxray (x1.25);
 *   - g83_rivalry_genderless: Luxray (Rivalry) hits a genderless Gholdengo (no multiplier);
 *   - g83_leafguard_sun: Meganium (Leaf Guard) in Drought's sun is refused Thunder Wave and Yawn (-immune, twice).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
#include "combat/turn.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
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

/* The recorded battle `name` replayed to its end (every step is checked against the tape of the reference). */
static duoforge_battle *replay_all(df_test *t, const duoforge_context *ctx, const char *name)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < cb->step_count; ++si) {
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

/* The marks: the four rows are engine rows (handler NONE, read by id). */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_BULLETPROOF] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_BULLETPROOF], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RIVALRY] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_RIVALRY], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_LEAFGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_LEAFGUARD], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_IRONBALL] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_IRONBALL], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG3_BULLET, 0x10u); /* the bullet bit of the flags3 column the Bulletproof reader tests (approved) */
}

/* Each G83 battle replays to its end with the lines and HP of the reference (test_conformance compares them step by step). */
static void check_battles(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g83_bulletproof_bullets", "g83_ironball_ground", "g83_ironball_spikes",
                                        "g83_ironball_speed", "g83_rivalry_gender", "g83_rivalry_genderless",
                                        "g83_leafguard_sun", "g83_leafguard_yawn_residual"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        duoforge_battle *b = replay_all(t, ctx, names[i]);
        if (b != NULL) {
            duoforge_battle_destroy(b);
        }
    }
}

/* Mega Sol and Leaf Guard (step G83, decision 0015 5bt), reached through Trace. Gardevoir (Trace, not Grass) copies Leaf Guard
 * from the Meganium foe at its start. A Mega Meganium (Mega Sol) uses Poison Powder on her in no sun: the pin's Leaf Guard reads
 * Pokemon#effectiveWeather of the target, which is sun for the user's move (sim/pokemon.ts:2193), and refuses the poison. Poison
 * Powder has 75% accuracy, and Trace copies only when Meganium is on the field before Gardevoir: over 16 seeds the step must return
 * DUOFORGE_E_UNSUPPORTED in some of them. The control is the same battle with no Mega evolution: every seed plays, no refusal.
 * Setup: the recorded battle g83_bulletproof_bullets (its weather is rain from Politoed, who is on the bench); side 0 member 0
 * is Meganium (Leaf Guard, Meganiumite), side 1 member 0 is Gardevoir (female, Trace, Protect). */
static duoforge_status run_poison_powder(df_test *t, const duoforge_context *ctx, const df_conf_battle *base,
                                         uint64_t seed, bool mega)
{
    static df_conf_member mem[2][6];
    df_conf_battle cb = *base;
    memcpy(mem, base->members, sizeof mem);
    cb.members = (const df_conf_member (*)[6])mem;
    mem[0][0].species = DFI_FORME_MEGANIUM;
    mem[0][0].item = DFI_ITEM_MEGANIUMITE + 1u; /* the setup stores an ability and an item as its id + 1 (0 is none), as the recorded members */
    mem[0][0].ability = DFI_ABILITY_LEAFGUARD + 1u;
    mem[0][0].moves[0] = DFI_MOVE_POISONPOWDER;
    mem[0][0].moves[2] = DFI_MOVE_ENERGYBALL; /* Meganium learns no Focus Blast: the recorded Chesnaught's third move */
    mem[1][0].species = DFI_FORME_GARDEVOIR;
    mem[1][0].gender = DUOFORGE_GENDER_FEMALE;
    mem[1][0].ability = DFI_ABILITY_TRACE + 1u;
    mem[1][0].item = DFI_ITEM_LIFEORB + 1u;
    mem[1][0].move_count = 1u;
    /* Trace copies from a foe already on the field: Meganium (base Speed 80) enters before Gardevoir (base 60, no Speed points) */
    mem[1][0].sp[0] = 32u; mem[1][0].sp[1] = 0u; mem[1][0].sp[2] = 0u; mem[1][0].sp[3] = 32u; mem[1][0].sp[4] = 2u; mem[1][0].sp[5] = 0u;
    mem[1][0].moves[0] = DFI_MOVE_PSYCHIC; /* not Protect: a protecting target would block the Poison Powder before the status */
    mem[1][0].moves[1] = 0u; /* slots beyond move_count are zero: the recorded Gengar's moves are dropped */
    mem[1][0].moves[2] = 0u;
    mem[1][0].moves[3] = 0u;
    duoforge_battle_setup setup;
    build_setup(&cb, &setup);
    setup.rng_initstate = seed;
    duoforge_battle *b = NULL;
    const duoforge_status created = duoforge_battle_create(ctx, &setup, &b);
    if (!DF_CHECK(t, created == DUOFORGE_OK && b != NULL)) {
        fprintf(stderr, "  poison powder setup: the battle is rejected: %s\n", duoforge_status_name(created));
        return created;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    bundle_of(&cb.steps[0], b, &bd);
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    df_conf_step st1 = cb.steps[1];
    /* side 0 slot 0 (Meganium, flat 0): Poison Powder on flat 2 (Gardevoir) */
    st1.cmds[0][0].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[0][0].move_slot = 0u;
    st1.cmds[0][0].target = 2u;
    st1.cmds[0][0].mega = mega ? 1u : 0u;
    /* side 0 slot 1 (Garchomp): the recorded command; side 1: Gardevoir and the Meganium foe protect */
    st1.cmds[1][0].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[1][0].move_slot = 0u;
    st1.cmds[1][0].target = 1u; /* Psychic on flat 1 (Garchomp) */
    st1.cmds[1][0].mega = 0u;
    st1.cmds[1][1].kind = DUOFORGE_SLOT_MOVE;
    st1.cmds[1][1].move_slot = 3u;
    st1.cmds[1][1].target = DUOFORGE_TARGET_NONE;
    st1.cmds[1][1].mega = 0u;
    bundle_of(&st1, b, &bd);
    const duoforge_status status = duoforge_battle_step(ctx, b, &bd, &res);
    duoforge_battle_destroy(b);
    return status;
}

static void check_mega_sol_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *base = find("g83_bulletproof_bullets");
    if (!DF_CHECK(t, base != NULL)) {
        return;
    }
    int refused = 0;
    for (uint64_t seed = 1; seed <= 16; ++seed) {
        const duoforge_status status = run_poison_powder(t, ctx, base, seed, true);
        if (status == DUOFORGE_E_UNSUPPORTED) {
            refused += 1;
        } else {
            if (status != DUOFORGE_OK) { fprintf(stderr, "  mega seed %u: the step returned %s\n", (unsigned)seed, duoforge_status_name(status)); }
            DF_CHECK(t, status == DUOFORGE_OK);
        }
    }
    DF_CHECK(t, refused >= 1); /* the poison hits in some seeds, and then the Mega Sol refusal is the answer */
    for (uint64_t seed = 1; seed <= 16; ++seed) {
        const duoforge_status status = run_poison_powder(t, ctx, base, seed, false); /* the control: no Mega Sol */
        DF_CHECK(t, status == DUOFORGE_OK);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g83");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_battles(&t, ctx);
    check_mega_sol_refusal(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
