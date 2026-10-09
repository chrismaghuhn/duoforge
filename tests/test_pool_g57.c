/*
 * duoforge.state.pool_g57 (white-box): step G57 of the content expansion, Magic Bounce and the Mega Stones Absolite and Sablenite
 * (decision 0015, entry 5bg).
 *
 * Magic Bounce (data/abilities.ts:2437-2464) bounces a reflectable move that is aimed at its holder, or a hazard that a foe
 * sets on the holder's side, back at the move's user. The bounced run is in src/combat/turn.c (dfi_bounce). The reflectable
 * moves are a generated column (dfi_pool_move_reflectable, tools/datagen/gen_closure.py), checked here against the pinned Dex
 * (tests/reference/reflect_ref.h, tools/reference/reflect_ref.js). The bounce is handled for the twenty marked ones below; a
 * marked reflectable move outside this list fails the guard until it has a bounced path (or is refused).
 *
 * The recorded battles of this step (tests/reference/specs/g57_*.json) are replayed by test_conformance; the refusals of the
 * bounced run are checked here by replaying a battle and stepping the refused turn with the public API.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "reference/reflect_ref.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

/* The twenty marked moves that Magic Bounce handles (step G57): the rows of dfi_bounce_kind_ok and the foeSide hazards. */
static const char *const handled[] = {
    "roar", "whirlwind", "hypnosis", "partingshot", "soak", "encore", "willowisp", "disable", "sleeppowder", "stunspore",
    "poisonpowder", "toxic", "stealthrock", "spikes", "toxicspikes", "stickyweb", "taunt", "yawn", "charm", "faketears",
};

static bool in_list(const char *name, const char *const *list, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        if (strcmp(name, list[i]) == 0) {
            return true;
        }
    }
    return false;
}

static bool in_reflect_ref(const char *name)
{
    for (size_t i = 0; i < DF_REFLECT_REF_COUNT; ++i) {
        if (strcmp(name, df_reflect_ref[i].id) == 0) {
            return true;
        }
    }
    return false;
}

/* The generated column is the pinned Dex's flags.reflectable, move by move (the pool rows only). */
static void test_reflect_column_matches_the_dex(df_test *t)
{
    uint32_t pool_reflect = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const char *name = dfi_pool_move_names[id];
        const bool dex = name != NULL && in_reflect_ref(name);
        DF_CHECK(t, (dfi_pool_move_reflectable[id] != 0u) == dex);
        pool_reflect += dfi_pool_move_reflectable[id] != 0u ? 1u : 0u;
    }
    /* Every reflectable Dex move of the list is a pool row (the list is the Champions Dex, the pool is its moves). */
    uint32_t listed = 0u;
    for (size_t i = 0; i < DF_REFLECT_REF_COUNT; ++i) {
        for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
            if (dfi_pool_move_names[id] != NULL && strcmp(dfi_pool_move_names[id], df_reflect_ref[i].id) == 0) {
                listed += 1u;
                break;
            }
        }
    }
    DF_CHECK_EQ_U64(t, pool_reflect, listed);
}

/* The marked reflectable moves are exactly the handled list: a new mark that is reflectable fails here until it is handled. */
static void test_marked_reflectable_moves_are_the_handled_list(df_test *t)
{
    uint32_t marked = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        if (dfi_support.moves[id] == 0u || dfi_pool_move_reflectable[id] == 0u) {
            continue;
        }
        const char *name = dfi_pool_move_names[id];
        DF_CHECK(t, name != NULL && in_list(name, handled, sizeof handled / sizeof handled[0]));
        marked += 1u;
    }
    DF_CHECK_EQ_U64(t, marked, 20u);
}

/* Magic Bounce: the engine reads it by id (its handler is NONE, its mark is set), with the pinned texts checked by the generator. */
static void test_magic_bounce_row(df_test *t)
{
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MAGICBOUNCE], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MAGICBOUNCE] != 0u);
}

/* Absolite and Sablenite are marked; Clefablite is not (Clefable's three abilities are unmarked). Absol has two Mega pairs, and
 * each stone takes it to its own Mega (dfi_mega_of: the stone is 1 + its id, the base's own link first). */
static void test_mega_stones(df_test *t)
{
    DF_CHECK(t, dfi_support.items[DFI_ITEM_ABSOLITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SABLENITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_CLEFABLITE] == 0u);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_ABSOL, DFI_ITEM_ABSOLITE + 1u), DFI_FORME_ABSOLMEGA);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_ABSOL, DFI_ITEM_ABSOLITEZ + 1u), DFI_FORME_ABSOLMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SABLEYE, DFI_ITEM_SABLENITE + 1u), DFI_FORME_SABLEYEMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_SABLEYE, DFI_ITEM_SABLENITE + 1u));
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_ABSOL, DFI_ITEM_ABSOLITE + 1u));
    DF_CHECK(t, !dfi_manifest_mega_of(&dfi_support, DFI_FORME_CLEFABLE, DFI_ITEM_CLEFABLITE + 1u));
}

/* Every marked reflectable move is a single-target or a foeSide move: a spread one would need the TryHit of every target
 * (not modelled; dfi_run_move_body refuses it), and none is marked. */
static void test_marked_reflectable_moves_are_not_spread(df_test *t)
{
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        if (dfi_support.moves[id] == 0u || dfi_pool_move_reflectable[id] == 0u) {
            continue;
        }
        const uint32_t target = dfi_pool_moves[id].target_class;
        DF_CHECK(t, target == DUOFORGE_TARGET_CLASS_NORMAL || target == DUOFORGE_TARGET_CLASS_ANY ||
                        target == DFI_TARGET_CLASS_FOE_SIDE);
    }
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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* Two Magic Bounce holders on the foes' side (Espeon and, here, Umbreon, whose set is given the ability): a foeSide move that
 * the foes set there has an order between the two onAllyTryHitSide handlers (the speed sort, a shuffle draw on a tie), which
 * is not modelled, so the turn is refused with E_UNSUPPORTED (dfi_run_move_body, the hazard branch). The recorded battle
 * g57_mb_stealth_rock otherwise runs unchanged up to that turn (its turn 1 is the Stealth Rock). */
static void test_two_holders_of_a_hazard_are_refused(df_test *t)
{
    const df_conf_battle *cb = find("g57_mb_stealth_rock");
    if (!DF_CHECK(t, cb != NULL && cb->step_count >= 2u)) {
        return;
    }
    duoforge_context *ctx = df_make_context(&df_config_pool);
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    setup.sides[1].members[1].ability = DFI_ABILITY_MAGICBOUNCE + 1u; /* Umbreon: the second holder */
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    uint32_t used = 0xFFFFFFFFu;
    const df_conf_step *team = &cb->steps[0];
    bundle_of(team, b, &bd);
    DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[team->tape_off], team->tape_len, &used, &res) == DUOFORGE_OK);
    const df_conf_step *turn = &cb->steps[1];
    bundle_of(turn, b, &bd);
    used = 0xFFFFFFFFu;
    DF_CHECK_EQ_U64(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[turn->tape_off], turn->tape_len, &used, &res),
                    DUOFORGE_E_UNSUPPORTED);
    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g57");
    test_reflect_column_matches_the_dex(&t);
    test_marked_reflectable_moves_are_the_handled_list(&t);
    test_marked_reflectable_moves_are_not_spread(&t);
    test_magic_bounce_row(&t);
    test_mega_stones(&t);
    test_two_holders_of_a_hazard_are_refused(&t);
    return df_test_end(&t);
}
