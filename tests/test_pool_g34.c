/*
 * duoforge.state.pool_g34 (white-box): step G34 of the content expansion, a batch of small rules: Gale Wings, Compound Eyes,
 * Wide Lens, Technician, Iron Fist, Sharpness, Solid Rock, Multiscale, Steel Roller, Clangorous Soul, Brick Break, and the data
 * rows Fiery Dance, Psycho Cut, Iron Defense and Electroweb.
 *
 * The recorded battles (g34_* under "data": "pool") are replayed by duoforge.reference.conformance_pool_data with the
 * reference's draws, which compares everything that the reference shows. Here are the facts that it does not show:
 *
 *   - the marks, the special numbers of the three new handlers and the two new bits of the second flags byte (punch and
 *     slicing: internal; the engine must not read decision 0020's static column, which duoforge.data.static_unread checks);
 *   - which moves carry them: exactly the punch and slicing moves of the pin, whatever their power;
 *   - the ModifyDamage chain: the engine chains Life Orb or Expert Belt, a resist berry, a screen, Glaive Rush's x2, Solid Rock
 *     and Multiscale in an order that it cannot know (speed ties are shuffled), so every combination that one hit can have must
 *     chain to one value in every order, or the engine refuses it (E_UNSUPPORTED). `dfi_mods_commute` is that test: it is
 *     compared here with a brute-force over all orders for every subset of the seven modifiers, 53 of 71 commute and the 18
 *     that do not are listed.
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

enum { LO, EB, BERRY, SCREEN, GLAIVE, SR, MS, KINDS };
static const uint32_t values[KINDS] = {5324u, 4915u, 2048u, 2732u, 8192u, 3072u, 2048u};

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
    uint32_t bad_mask[32] = {0u};
    uint32_t bad = 0u;
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
        } else if (bad < 32u) {
            bad_mask[bad] = set;
            bad += 1u;
        }
    }
    DF_CHECK_EQ_U64(t, possible, 71u);
    DF_CHECK_EQ_U64(t, commuting, 53u);
    DF_CHECK_EQ_U64(t, bad, 18u);
    /* A group of three or more that does not commute, by name: Glaive Rush with three others, an Expert Belt with a berry and
     * Glaive Rush (found by the checks of step G34: G28 had left it), the berry and Solid Rock with the Expert Belt, ... */
    bool eb_berry_glaive = false;
    bool lo_berry_screen_glaive = false;
    for (uint32_t i = 0u; i < bad; ++i) {
        eb_berry_glaive = eb_berry_glaive || bad_mask[i] == ((1u << EB) | (1u << BERRY) | (1u << GLAIVE));
        lo_berry_screen_glaive = lo_berry_screen_glaive ||
                                 bad_mask[i] == ((1u << LO) | (1u << BERRY) | (1u << SCREEN) | (1u << GLAIVE));
    }
    DF_CHECK(t, eb_berry_glaive && lo_berry_screen_glaive);
    /* no pair commutes wrongly: the chain of two is order independent by construction, a quick guard on the helper */
    const uint32_t pair[2] = {5324u, 2732u};
    DF_CHECK(t, dfi_mods_commute(pair, 2u));
    /* the helper refuses more than its bound */
    const uint32_t many[7] = {2048u, 2048u, 2048u, 2048u, 2048u, 2048u, 2048u};
    DF_CHECK(t, !dfi_mods_commute(many, 7u));
}

static void check_facts(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG2_PUNCH, 32u);
    DF_CHECK_EQ_U64(t, DFI_MOVE_FLAG2_SLICING, 64u);
    /* the marks */
    static const uint32_t moves[] = {DFI_MOVE_STEELROLLER, DFI_MOVE_CLANGOROUSSOUL, DFI_MOVE_BRICKBREAK, DFI_MOVE_FIERYDANCE,
                                     DFI_MOVE_PSYCHOCUT,   DFI_MOVE_IRONDEFENSE,    DFI_MOVE_ELECTROWEB};
    for (size_t i = 0u; i < sizeof moves / sizeof moves[0]; ++i) {
        DF_CHECK(t, dfi_support.moves[moves[i]] != 0u);
    }
    static const uint32_t abilities[] = {DFI_ABILITY_COMPOUNDEYES, DFI_ABILITY_IRONFIST,  DFI_ABILITY_SHARPNESS,
                                         DFI_ABILITY_SOLIDROCK,    DFI_ABILITY_TECHNICIAN, DFI_ABILITY_MULTISCALE,
                                         DFI_ABILITY_GALEWINGS};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        DF_CHECK(t, dfi_support.abilities[abilities[i]] != 0u);
        DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[abilities[i]], DFI_HANDLER_NONE);
    }
    DF_CHECK(t, dfi_support.items[DFI_ITEM_WIDELENS] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_WIDELENS], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_STEELROLLER].special, DFI_SPECIAL_STEEL_ROLLER);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_CLANGOROUSSOUL].special, DFI_SPECIAL_CLANGOROUS_SOUL);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_BRICKBREAK].special, DFI_SPECIAL_BRICK_BREAK);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_BRICK_BREAK, DFI_SPECIAL_CLANGOROUS_SOUL + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_CLANGOROUS_SOUL, DFI_SPECIAL_STEEL_ROLLER + 1u);
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_DISABLE, DFI_SPECIAL_BRICK_BREAK + 1u); /* step G27, after the handlers of the other steps */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_ELECTRIC_TERRAIN, DFI_SPECIAL_DISABLE + 1u); /* step G25's four handlers follow */
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_PERISH_SONG, DFI_SPECIAL_TERRAIN_PULSE + 1u); /* step G26 follows */
    /* Clangorous Soul: the Champions mod's accuracy true, five +1 boosts on the user, the sound flag (Throat Chop bars it) */
    const dfi_move_data *cs = &dfi_pool_moves[DFI_MOVE_CLANGOROUSSOUL];
    DF_CHECK_EQ_U64(t, cs->accuracy, 0u);
    DF_CHECK_EQ_U64(t, cs->boost_role, DFI_BOOST_ROLE_PRIMARY_SELF);
    DF_CHECK((t), (dfi_pool_move_flags2[DFI_MOVE_CLANGOROUSSOUL] & DFI_MOVE_FLAG2_SOUND) != 0u);
    /* the punch and slicing flags of the pin, on every move that has them */
    static const uint32_t punch[] = {DFI_MOVE_BULLETPUNCH, DFI_MOVE_MACHPUNCH, DFI_MOVE_DRAINPUNCH, DFI_MOVE_ICEPUNCH};
    for (size_t i = 0u; i < sizeof punch / sizeof punch[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_flags2[punch[i]] & DFI_MOVE_FLAG2_PUNCH) != 0u);
        DF_CHECK(t, (dfi_pool_move_flags2[punch[i]] & DFI_MOVE_FLAG2_SLICING) == 0u);
    }
    static const uint32_t slicing[] = {DFI_MOVE_PSYCHOCUT, DFI_MOVE_NIGHTSLASH, DFI_MOVE_SLASH};
    for (size_t i = 0u; i < sizeof slicing / sizeof slicing[0]; ++i) {
        DF_CHECK(t, (dfi_pool_move_flags2[slicing[i]] & DFI_MOVE_FLAG2_SLICING) != 0u);
        DF_CHECK(t, (dfi_pool_move_flags2[slicing[i]] & DFI_MOVE_FLAG2_PUNCH) == 0u);
    }
    /* every pool move with the punch flag in the public static column has the internal bit, and the same for slicing */
    for (uint32_t m = 0u; m < DFI_POOL_MOVE_COUNT; ++m) {
        DF_CHECK_EQ_U64(t, (dfi_pool_move_flags2[m] & DFI_MOVE_FLAG2_PUNCH) != 0u ? 1u : 0u,
                        (dfi_pool_move_static_flags[m] & DUOFORGE_MOVE_STATIC_FLAG_PUNCH) != 0u ? 1u : 0u);
        DF_CHECK_EQ_U64(t, (dfi_pool_move_flags2[m] & DFI_MOVE_FLAG2_SLICING) != 0u ? 1u : 0u,
                        (dfi_pool_move_static_flags[m] & DUOFORGE_MOVE_STATIC_FLAG_SLICING) != 0u ? 1u : 0u);
    }
}

/* ---- the engine's refusal of a ModifyDamage chain that does not commute (turn.c, dfi_get_damage)
 *
 * g34_damage_chain has Rillaboom's Life Orb Wood Hammer at a Rhyperior (Solid Rock, Rindo Berry): Life Orb, berry and Solid Rock
 * commute and the engine plays it (the conformance test compares it). With an Expert Belt in the place of the Life Orb the three
 * modifiers 4915, 2048 and 3072 chain to 1843 or 1844 by their order, so the engine must refuse the hit: E_UNSUPPORTED, from
 * the step with that hit, and not an invariant failure or a played hit. */
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

static void check_refusal(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = find("g34_damage_chain");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_status st = DUOFORGE_OK;
    /* as recorded: every step is played */
    DF_CHECK_EQ_U64(t, play(t, ctx, cb, 0xFFFFFFFFu, &st), cb->step_count);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_OK);
    /* Rillaboom with an Expert Belt: refused at the first Wood Hammer that reaches Rhyperior, step 2 (step 1 is blocked by a Protect) */
    const uint32_t refused = play(t, ctx, cb, DFI_FORME_RILLABOOM, &st);
    DF_CHECK_EQ_U64(t, st, DUOFORGE_E_UNSUPPORTED);
    DF_CHECK_EQ_U64(t, refused, 2u);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g34");
    check_facts(&t);
    check_chain(&t);
    check_refusal(&t);
    return df_test_end(&t);
}
