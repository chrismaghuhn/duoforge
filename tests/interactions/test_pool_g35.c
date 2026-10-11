/*
 * duoforge.state.pool_g35 (white-box): step G35 of the content expansion, ten data rows (Thunder Punch, X-Scissor, Lumina Crash,
 * Overdrive, Scorching Sands, Leaf Blade, Boomburst, Sludge Wave, Volt Tackle, Discharge) and two small rules (Rain Dish and Friend
 * Guard).
 *
 * The recorded battles (g35_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the
 * reference's draws, which compares everything that the reference shows. Here are the facts that it does not show:
 *
 *   - the marks, and that the two abilities are engine rows (no handler of their own: the turn code reads them by id);
 *   - the flags of the data rows that other rules read (punch, slicing, sound);
 *   - Gigaton Hammer, left out of the step, stays unmarked because no learner of it has a marked ability: the day one has, this
 *     test fails and the move is the next row to record;
 *   - the ModifyDamage chain with Friend Guard as an eighth modifier: `dfi_mods_commute` is compared with a brute force over all
 *     orders for every subset that one hit can have (143 subsets, 85 of them commute, the 58 that do not are refused by the
 *     engine, E_UNSUPPORTED), and the engine's refusal itself.
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
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

enum { LO, EB, BERRY, SCREEN, GLAIVE, SR, MS, FG, KINDS };
static const uint32_t values[KINDS] = {5324u, 4915u, 2048u, 2732u, 8192u, 3072u, 2048u, 3072u};

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
    bool eb_ms_fg = false;
    bool lo_ms_fg_commutes = false;
    for (uint32_t set = 1u; set < (1u << KINDS); ++set) {
        /* one hit has one of Life Orb and Expert Belt (an item), one of Solid Rock and Multiscale (an ability) */
        if (((set >> LO) & 1u) != 0u && ((set >> EB) & 1u) != 0u) {
            continue;
        }
        if (((set >> SR) & 1u) != 0u && ((set >> MS) & 1u) != 0u) {
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
        eb_ms_fg = eb_ms_fg || (set == ((1u << EB) | (1u << MS) | (1u << FG)) && !want);
        lo_ms_fg_commutes = lo_ms_fg_commutes || (set == ((1u << LO) | (1u << MS) | (1u << FG)) && want);
    }
    DF_CHECK_EQ_U64(t, possible, 143u);
    DF_CHECK_EQ_U64(t, commuting, 85u);
    DF_CHECK_EQ_U64(t, bad, 58u);
    /* named: an Expert Belt attacker at a Multiscale target with a Friend Guard partner is refused, a Life Orb one is played */
    DF_CHECK(t, eb_ms_fg && lo_ms_fg_commutes);
    /* six modifiers are the most that one hit has: Life Orb or Expert Belt, a berry, a screen, Glaive Rush, Solid Rock or
     * Multiscale, Friend Guard */
    DF_CHECK_EQ_U64(t, DFI_MODIFY_DAMAGE_MAX, 6u);
}

static void check_facts(df_test *t)
{
    static const uint32_t moves[] = {DFI_MOVE_THUNDERPUNCH, DFI_MOVE_XSCISSOR,   DFI_MOVE_LUMINACRASH, DFI_MOVE_OVERDRIVE,
                                     DFI_MOVE_SCORCHINGSANDS, DFI_MOVE_LEAFBLADE, DFI_MOVE_BOOMBURST,   DFI_MOVE_SLUDGEWAVE,
                                     DFI_MOVE_VOLTTACKLE,   DFI_MOVE_DISCHARGE};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_moves[moves[i]].special, DFI_SPECIAL_NONE); /* data rows, no handler */
    }
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RAINDISH] != 0u);
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_FRIENDGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_RAINDISH], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_FRIENDGUARD], DFI_HANDLER_NONE);
    /* the flags that other rules read: Iron Fist (punch), Sharpness (slicing), Soundproof and Throat Chop (sound) */
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_THUNDERPUNCH] & DFI_MOVE_FLAG2_PUNCH) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_XSCISSOR] & DFI_MOVE_FLAG2_SLICING) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_LEAFBLADE] & DFI_MOVE_FLAG2_SLICING) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_OVERDRIVE] & DFI_MOVE_FLAG2_SOUND) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_BOOMBURST] & DFI_MOVE_FLAG2_SOUND) != 0u);
    DF_CHECK(t, (dfi_pool_move_flags2[DFI_MOVE_VOLTTACKLE] & (DFI_MOVE_FLAG2_PUNCH | DFI_MOVE_FLAG2_SLICING)) == 0u);
    /* Gigaton Hammer (cantusetwice) is not part of the step: it is unmarked, and so is every ability of every forme that learns it */
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_GIGATONHAMMER] == 0u);
    uint32_t learners = 0u;
    for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT; ++forme) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
        if ((((uint32_t)l->learnable[DFI_MOVE_GIGATONHAMMER / 8u] >> (DFI_MOVE_GIGATONHAMMER % 8u)) & 1u) == 0u) {
            continue;
        }
        learners += 1u;
        DF_CHECK_EQ_U64(t, forme, DFI_FORME_TINKATON);
        for (uint32_t k = 0u; k < l->ability_count; ++k) {
            DF_CHECK(t, dfi_support.abilities[l->abilities[k]] == 0u);
        }
    }
    DF_CHECK_EQ_U64(t, learners, 1u);
}

/* ---- the engine's refusal of a ModifyDamage chain that does not commute, with Friend Guard in it
 *
 * g35_friend_guard has Garchomp's Rock Slide and Dragon Claw at Dragonite (Multiscale, full HP at the first hit) whose partner
 * Maushold has Friend Guard, and Salamence's Life Orb Hyper Voice at both: Life Orb, Multiscale and Friend Guard commute and the
 * engine plays it (the conformance test compares it). With an Expert Belt on Garchomp the modifiers 4915, 2048 and 3072 of its
 * super effective hit chain to different values by their order, so the engine must refuse the hit: E_UNSUPPORTED, from the step
 * with that hit, and not an invariant failure or a played hit. */
static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s, uint32_t belt_for)
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
            if (src->species == belt_for) {
                dst->item = 1u + DFI_ITEM_EXPERTBELT;
            }
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

/* The first step that does not return OK (or step_count when none), and its status. */
static uint32_t play(df_test *t, duoforge_context *ctx, const df_conf_battle *cb, uint32_t belt_for, duoforge_status *status)
{
    duoforge_battle_setup setup;
    build_setup(cb, &setup, belt_for);
    duoforge_battle *b = NULL;
    *status = DUOFORGE_OK;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return 0u;
    }
    uint32_t si = 0u;
    for (; si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        *status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (*status != DUOFORGE_OK) {
            break;
        }
    }
    duoforge_battle_destroy(b);
    return si;
}

#define G35_REFUSED_STEP 1u /* the step of the first Garchomp hit at Dragonite in g35_friend_guard (set from the recorded battle) */

static void check_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g35_friend_guard");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    /* as recorded: every step is played */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, 0xFFFFFFFFu, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* Garchomp with an Expert Belt: refused at its first super effective hit at Dragonite */
    const uint32_t refused = play(t, ctx, cb, DFI_FORME_GARCHOMP, &st);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, refused, G35_REFUSED_STEP);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g35");
    check_facts(&t);
    check_chain(&t);
    check_refusal(&t);
    return df_test_end(&t);
}
