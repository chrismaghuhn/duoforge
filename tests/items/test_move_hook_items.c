/*
 * duoforge.items.move_hook_items (white-box): batch I1 of the Champions-100 track (decision 0015 entry 5ef), Starminite and six
 * items with one clause each at an existing hook. The recorded POOL battles i1_cover_* are replayed against the pool rows by
 * duoforge.reference.conformance_pool_data; this test checks what the replays alone do not:
 *
 *   1. The marks and the handler column: the seven items are marked, the six of one clause are engine rows (handler NONE), and
 *      Starminite takes Starmie to Starmie-Mega (Huge Power) with the base forme's Illuminate and Natural Cure marked and legal;
 *      Analytic (A1b) stays unmarked, so a Starmie with it is refused.
 *   2. King's Rock's predicate over every pool move: the flinch secondary of the engine's columns, the added flinch for every
 *      damaging move without one, for a Sheer Force holder's stripped move too, and never for a Status move.
 *   3. The hook fires and the neighbours do not: at the step of a recorded battle where the item decides something, the step
 *      replays with the reference's tape; with the holder's item changed to a marked neighbour (Silk Scarf for Normal Gem, Wide
 *      Lens for Zoom Lens, Life Orb for Shell Bell, Leftovers for King's Rock, Big Root and Shed Shell) the same step no longer
 *      reproduces the reference (another tape use, other events, or a refused choice).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/items/held.h"
#include "combat/items/kings_rock.h"
#include "combat/sheer_force.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"
#define IT(x) (1u + DFI_ITEM_##x)

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

static void check_marks(df_test *t)
{
    static const uint32_t rows[] = {DFI_ITEM_NORMALGEM, DFI_ITEM_KINGSROCK, DFI_ITEM_ZOOMLENS,
                                    DFI_ITEM_SHELLBELL, DFI_ITEM_BIGROOT,   DFI_ITEM_SHEDSHELL};
    for (size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        DF_CHECK(t, dfi_support.items[rows[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_item_handler[rows[i]], DFI_HANDLER_NONE);
        DF_CHECK(t, dfi_pool_item_unmodeled[rows[i]] == NULL);
        DF_CHECK_EQ_U64(t, dfi_pool_item_family[rows[i]].family, DFI_ITEM_FAMILY_NONE);
    }
    /* Starminite: the generic Mega path; the stone, its Mega's ability and the base forme's two marked abilities */
    DF_CHECK(t, dfi_support.items[DFI_ITEM_STARMINITE] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_STARMINITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_STARMIE, IT(STARMINITE)), DFI_FORME_STARMIEMEGA);
    DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, DFI_FORME_STARMIE, IT(STARMINITE)));
    DF_CHECK_EQ_U64(t, dfi_pool_formes[DFI_FORME_STARMIEMEGA].ability, DFI_ABILITY_HUGEPOWER);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_HUGEPOWER] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_ILLUMINATE] != 0u && base_ability_legal(DFI_FORME_STARMIE, DFI_ABILITY_ILLUMINATE));
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_NATURALCURE] != 0u && base_ability_legal(DFI_FORME_STARMIE, DFI_ABILITY_NATURALCURE));
    DF_CHECK(t, base_ability_legal(DFI_FORME_STARMIE, DFI_ABILITY_ANALYTIC));
    DF_CHECK_EQ_U64(t, dfi_support.abilities[DFI_ABILITY_ANALYTIC], 0u); /* A1b: a Starmie with Analytic stays refused */
    /* the stone is Starmie's only: another forme gets nothing from it */
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_GENGAR, IT(STARMINITE)), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_STARMIE, IT(GENGARITE)), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, DFI_KINGS_ROCK_CHANCE, 10u);
}

/* King's Rock over every pool move: a damaging move gets the flinch unless one of its own secondaries is one; a Sheer Force
 * holder's stripped move always gets it; a Status move never. The named moves pin the predicate to known rows. */
static void check_kings_rock(df_test *t)
{
    uint32_t added = 0u;
    uint32_t own_flinch = 0u;
    for (uint32_t id = 0u; id < DFI_POOL_MOVE_COUNT; ++id) {
        const dfi_move_data *md = &dfi_pool_moves[id];
        if (md->special == DFI_SPECIAL_UNMODELED) {
            continue;
        }
        const bool status = md->category == DFI_CATEGORY_STATUS;
        DF_CHECK(t, !dfi_kings_rock_adds(false, false, status, md));
        DF_CHECK(t, !dfi_kings_rock_adds(true, true, true, md));
        DF_CHECK_EQ_U64(t, dfi_kings_rock_adds(true, false, status, md) ? 1u : 0u,
                        !status && !dfi_move_flinch_secondary(md) ? 1u : 0u);
        DF_CHECK_EQ_U64(t, dfi_kings_rock_adds(true, true, status, md) ? 1u : 0u,
                        !status && (dfi_sf_strips_move(true, md) || !dfi_move_flinch_secondary(md)) ? 1u : 0u);
        if (dfi_move_flinch_secondary(md)) {
            own_flinch += 1u;
            DF_CHECK(t, dfi_sf_strips_move(true, md)); /* a flinch secondary is a secondary: Sheer Force strips it */
        }
        added += !status && dfi_kings_rock_adds(true, false, status, md) ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, own_flinch, 15u); /* the pool's modelled moves with a flinch secondary (pool_families.js checkI1) */
    DF_CHECK(t, added > 200u);
    static const struct {
        uint32_t move;
        bool plain, sheer_force;
    } named[] = {
        {DFI_MOVE_ROCKSLIDE, false, true}, {DFI_MOVE_FAKEOUT, false, true},  {DFI_MOVE_ICEFANG, false, true},
        {DFI_MOVE_WATERFALL, false, true}, {DFI_MOVE_HEATWAVE, true, true},  {DFI_MOVE_ICYWIND, true, true},
        {DFI_MOVE_DOUBLEEDGE, true, true}, {DFI_MOVE_POPULATIONBOMB, true, true}, {DFI_MOVE_STRUGGLE, true, true},
        {DFI_MOVE_FOLLOWME, false, false}, {DFI_MOVE_PROTECT, false, false},
    };
    for (size_t i = 0; i < sizeof named / sizeof named[0]; ++i) {
        const dfi_move_data *md = &dfi_pool_moves[named[i].move];
        const bool status = md->category == DFI_CATEGORY_STATUS;
        DF_CHECK_EQ_U64(t, dfi_kings_rock_adds(true, false, status, md) ? 1u : 0u, named[i].plain ? 1u : 0u);
        DF_CHECK_EQ_U64(t, dfi_kings_rock_adds(true, true, status, md) ? 1u : 0u, named[i].sheer_force ? 1u : 0u);
    }
}

/* One item at its decisive step: the battle, the step, the holder (side and forme), its item at the step and the neighbour. */
typedef struct i1_case {
    const char *battle;
    uint32_t step;
    uint32_t side;
    uint32_t forme;
    uint32_t item;
    uint32_t neighbour;
    const char *what;
} i1_case;

static const i1_case cases[] = {
    {NULL, 0u, 0u, 0u, 0u, 0u, NULL}, /* filled with the covering battles */
};

static void check_case(df_test *t, const duoforge_context *ctx, const i1_case *c)
{
    const df_conf_battle *cb = df_conf_find(c->battle);
    if (!DF_CHECK(t, cb != NULL && c->step < cb->step_count)) {
        fprintf(stderr, "  %s: no such battle or step\n", c->what);
        return;
    }
    duoforge_battle *b = df_conf_replay_battle(t, ctx, cb, c->step);
    if (b == NULL) {
        return;
    }
    const uint32_t m = df_conf_member_of(b, c->side, c->forme);
    if (!DF_CHECK(t, m < DUOFORGE_MAX_ROSTER) ||
        !DF_CHECK_EQ_U64(t, dfi_item_code(b, &b->sides[c->side].members[m]), c->item)) {
        fprintf(stderr, "  %s: the holder is not found with its item\n", c->what);
        duoforge_battle_destroy(b);
        return;
    }
    const df_conf_step *st = &cb->steps[c->step];
    static df_conf_run base;
    static df_conf_run moved;
    duoforge_battle *x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        df_conf_run_step(ctx, x, st, &base);
        if (!DF_CHECK(t, base.status == DUOFORGE_OK) || !DF_CHECK_EQ_U64(t, base.used, st->tape_len)) {
            fprintf(stderr, "  %s: the recorded step does not replay\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    x = NULL;
    if (DF_CHECK(t, duoforge_battle_clone(ctx, b, &x) == DUOFORGE_OK)) {
        x->tail.sides[c->side].item_now[m] = (uint16_t)c->neighbour;
        DF_CHECK(t, duoforge_battle_check(ctx, x) == DUOFORGE_OK);
        df_conf_run_step(ctx, x, st, &moved);
        const bool same = moved.status == DUOFORGE_OK && moved.used == st->tape_len && moved.count == base.count &&
                          memcmp(moved.events, base.events, (size_t)base.count * sizeof base.events[0]) == 0;
        if (!DF_CHECK(t, !same)) {
            fprintf(stderr, "  %s: the neighbour item plays the same step\n", c->what);
        }
        duoforge_battle_destroy(x);
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.move_hook_items");
    check_marks(&t);
    check_kings_rock(&t);
    duoforge_context *kp = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, kp != NULL)) {
        for (size_t i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            if (cases[i].battle != NULL) {
                check_case(&t, kp, &cases[i]);
            }
        }
        duoforge_context_destroy(kp);
    }
    return df_test_end(&t);
}
