/*
 * duoforge.state.pool_mega2 (white-box): the Mega batch 2 of the content expansion: Swampertite (Swift Swim), Metagrossite
 * (Tough Claws) and Lucarionite Z with its Mega ability Aura Guard, a contact hit on its holder halved in the ModifyDamage
 * chain.
 *
 * The recorded battles (mb2_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the
 * reference's draws, which compares everything that the reference shows. Here are the facts that it does not show:
 *
 *   - the marks, the Mega of each stone and its support, and that Aura Guard is an engine row (no handler of its own);
 *   - the ModifyDamage chain with Aura Guard as the ninth modifier: `dfi_mods_commute` against a brute force over all orders
 *     for every subset that one hit can have (191 subsets, 113 of them commute, the 78 that do not are refused by the
 *     engine, E_UNSUPPORTED), where Aura Guard is exclusive with Solid Rock and Multiscale (the target's one ability);
 *   - the engine's refusal itself: in mb2_aura_guard_chain the Close Combat of a Life Orb Annihilape hits Lucario-Mega-Z
 *     (Aura Guard) behind a Reflect, super effective, and is played (Life Orb, Reflect and Aura Guard commute). With an
 *     Expert Belt in place of the Life Orb and a Friend Guard on the Reflect user, the four modifiers 4915, 2732, 2048 and
 *     3072 chain to different values by their order, and the hit is refused (E_UNSUPPORTED); with the Life Orb and the
 *     Friend Guard it is played again. Without Aura Guard in the chain's list the refusal would not happen.
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

enum { LO, EB, BERRY, SCREEN, GLAIVE, SR, MS, FG, AG, KINDS };
static const uint32_t values[KINDS] = {5324u, 4915u, 2048u, 2732u, 8192u, 3072u, 2048u, 3072u, 2048u};

/* The reference computation, independent of dfi_mods_commute: every permutation by recursion. */
static void walk(const uint32_t *mods, uint32_t n, uint32_t *used, uint32_t depth, uint32_t chain, uint32_t *first,
                 bool *same)
{
    if (depth == n) {
        if (*first == 0u) {
            *first = chain;
        } else if (*first != chain) {
            *same = false;
        }
        return;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        if ((*used & (1u << i)) == 0u) {
            *used |= 1u << i;
            walk(mods, n, used, depth + 1u, ((chain * mods[i]) + 2048u) >> 12, first, same);
            *used &= ~(1u << i);
        }
    }
}

static bool brute(const uint32_t *mods, uint32_t n)
{
    uint32_t used = 0u;
    uint32_t first = 0u;
    bool same = true;
    walk(mods, n, &used, 0u, 4096u, &first, &same);
    return same;
}

static void check_chain(df_test *t)
{
    uint32_t possible = 0u;
    uint32_t commuting = 0u;
    uint32_t bad = 0u;
    bool eb_glaive_ag = false;
    bool eb_fg_ag = false;
    bool lo_screen_ag_commutes = false;
    for (uint32_t set = 1u; set < (1u << KINDS); ++set) {
        /* one hit has one of Life Orb and Expert Belt (an item), one of Solid Rock, Multiscale and Aura Guard (an ability) */
        if (((set >> LO) & 1u) != 0u && ((set >> EB) & 1u) != 0u) {
            continue;
        }
        if (((set >> SR) & 1u) + ((set >> MS) & 1u) + ((set >> AG) & 1u) > 1u) {
            continue;
        }
        uint32_t mods[KINDS];
        uint32_t n = 0u;
        for (uint32_t k = 0u; k < KINDS; ++k) {
            if (((set >> k) & 1u) != 0u) {
                mods[n] = values[k];
                n += 1u;
            }
        }
        possible += 1u;
        const bool want = brute(mods, n);
        DF_CHECK_EQ_U64(t, dfi_mods_commute(mods, n) ? 1u : 0u, want ? 1u : 0u);
        if (want) {
            commuting += 1u;
        } else {
            bad += 1u;
        }
        eb_glaive_ag = eb_glaive_ag || (set == ((1u << EB) | (1u << GLAIVE) | (1u << AG)) && !want);
        eb_fg_ag = eb_fg_ag || (set == ((1u << EB) | (1u << FG) | (1u << AG)) && !want);
        lo_screen_ag_commutes = lo_screen_ag_commutes || (set == ((1u << LO) | (1u << SCREEN) | (1u << AG)) && want);
    }
    DF_CHECK_EQ_U64(t, possible, 191u);
    DF_CHECK_EQ_U64(t, commuting, 113u);
    DF_CHECK_EQ_U64(t, bad, 78u);
    /* named: an Expert Belt with Glaive Rush or with a Friend Guard partner at an Aura Guard holder is refused, a Life Orb and a
     * Reflect are played */
    DF_CHECK(t, eb_glaive_ag && eb_fg_ag && lo_screen_ag_commutes);
    /* Aura Guard does not make a seventh modifier: it is the target's one ability, with Solid Rock and Multiscale */
    DF_CHECK_EQ_U64(t, DFI_MODIFY_DAMAGE_MAX, 6u);
}

static void check_facts(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_AURAGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_AURAGUARD], DFI_HANDLER_NONE); /* an engine row: read by id */
    DF_CHECK_EQ_U64(t, dfi_pool_ability_family[DFI_ABILITY_AURAGUARD].family, DFI_ABILITY_FAMILY_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SWAMPERTITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_METAGROSSITE] != 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_LUCARIONITEZ] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_SWAMPERTITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_METAGROSSITE], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_LUCARIONITEZ], DFI_HANDLER_NONE);

    /* the Mega of each pair, its ability, and the support of the pair (the Mega ability is marked) */
    static const struct {
        uint32_t base, item, mega, ability;
    } pairs[] = {
        {DFI_FORME_SWAMPERT, DFI_ITEM_SWAMPERTITE, DFI_FORME_SWAMPERTMEGA, DFI_ABILITY_SWIFTSWIM},
        {DFI_FORME_METAGROSS, DFI_ITEM_METAGROSSITE, DFI_FORME_METAGROSSMEGA, DFI_ABILITY_TOUGHCLAWS},
        {DFI_FORME_LUCARIO, DFI_ITEM_LUCARIONITEZ, DFI_FORME_LUCARIOMEGAZ, DFI_ABILITY_AURAGUARD},
    };
    for (size_t i = 0u; i < sizeof pairs / sizeof pairs[0]; ++i) {
        const uint32_t mega = dfi_mega_of(pairs[i].base, 1u + pairs[i].item);
        DF_CHECK_EQ_U64(t, mega, pairs[i].mega);
        DF_CHECK_EQ_U64(t, dfi_pool_formes[mega].ability, pairs[i].ability);
        DF_CHECK(t, dfi_manifest_mega_of(&dfi_support, pairs[i].base, 1u + pairs[i].item));
        DF_CHECK(t, dfi_support.abilities[pairs[i].ability] != 0u);
    }
    /* Lucario's other stone is another Mega (Adaptability), not Lucario-Mega-Z, and the Z stone is no stone of another forme */
    DF_CHECK(t, dfi_mega_of(DFI_FORME_LUCARIO, 1u + DFI_ITEM_LUCARIONITE) != DFI_FORME_LUCARIOMEGAZ);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_METAGROSS, 1u + DFI_ITEM_LUCARIONITEZ), DFI_FORME_NONE);
    DF_CHECK_EQ_U64(t, dfi_mega_of(DFI_FORME_SWAMPERT, 1u + DFI_ITEM_METAGROSSITE), DFI_FORME_NONE);
    /* the base abilities that the three need are marked: Torrent, Clear Body and Inner Focus */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_TORRENT] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_CLEARBODY] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_INNERFOCUS] != 0u);
    /* Aura Guard is the Mega ability of Lucario-Mega-Z alone among the pool's formes' abilities that are marked here */
    uint32_t holders = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        holders += dfi_pool_formes[forme].ability == DFI_ABILITY_AURAGUARD ? 1u : 0u;
    }
    DF_CHECK_EQ_U64(t, holders, 1u);
}

/* ---- the engine's refusal of a ModifyDamage chain that does not commute, with Aura Guard in it */
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

#define CC_STEP 2u          /* the step of Annihilape's Close Combat at Lucario-Mega-Z in mb2_aura_guard_chain */
#define LUCARIO_SIDE 0u
#define GRIMMSNARL_ROSTER 1u /* Lucario's partner, the Reflect user (the second member of the first team) */
#define ANNIHILAPE_SIDE 1u
#define ANNIHILAPE_ROSTER 0u

enum { AS_RECORDED, WITH_FRIEND_GUARD, WITH_BELT_AND_FRIEND_GUARD };

/* Plays the steps before the Close Combat as recorded, changes the state as `variant` says, and returns the status of the
 * step with the Close Combat. */
static duoforge_status play_cc(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, int variant)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_status status = DUOFORGE_OK;
    for (uint32_t si = 0; si <= CC_STEP; ++si) {
        const df_conf_step *st = &cb->steps[si];
        if (si == CC_STEP) {
            if (variant != AS_RECORDED) {
                /* Lucario's partner has Friend Guard (the ability override of the tail: Trace, Skill Swap and the like) */
                b->tail.sides[LUCARIO_SIDE].ability_now[GRIMMSNARL_ROSTER] = (uint16_t)(1u + DFI_ABILITY_FRIENDGUARD);
            }
            if (variant == WITH_BELT_AND_FRIEND_GUARD) {
                b->sides[ANNIHILAPE_SIDE].members[ANNIHILAPE_ROSTER].item = (uint8_t)(1u + DFI_ITEM_EXPERTBELT);
            }
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

static void check_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("mb2_aura_guard_chain");
    if (!DF_CHECK(t, cb != NULL && cb->step_count > CC_STEP)) {
        return;
    }
    /* as recorded (Life Orb, Reflect, Aura Guard): played; a Friend Guard on top of it (Life Orb, Reflect, Aura Guard, Friend
     * Guard commute) is played too; an Expert Belt with the Friend Guard is refused */
    DF_CHECK_EQ_U64(t, play_cc(t, ctx, cb, AS_RECORDED), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, play_cc(t, ctx, cb, WITH_FRIEND_GUARD), DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, play_cc(t, ctx, cb, WITH_BELT_AND_FRIEND_GUARD), DUOFORGE_E_UNSUPPORTED);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_mega2");
    check_facts(&t);
    check_chain(&t);
    check_refusal(&t);
    return df_test_end(&t);
}
