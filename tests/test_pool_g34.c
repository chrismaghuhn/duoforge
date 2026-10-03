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
#include "support/check.h"
#include "support/fixtures.h"

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
    DF_CHECK_EQ_U64(t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_BRICK_BREAK + 1u);
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

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g34");
    check_facts(&t);
    check_chain(&t);
    return df_test_end(&t);
}
