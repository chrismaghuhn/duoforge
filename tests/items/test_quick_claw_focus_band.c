/*
 * duoforge.items.quick_claw_focus_band (white-box): decision 0015 entry 5eh (docs/mechanics/items/5eh-quick-claw-and-focus-band-draws.md).
 * Quick Claw's roll at resolveAction (draw site 27, QUICK_CLAW) and Focus Band's roll in the holder's Damage event (draw site 28,
 * FOCUS_BAND), the two helpers of src/combat/items/draw_items.h, checked where the recorded battles cannot show it by themselves:
 *
 *   - the marks, the sites and the rows around them: both items marked; the pool's rows with a FractionalPriority or Damage
 *     handler that the rolls do not model (Quick Draw, Stall, Disguise, Heatproof, Poison Heal, Berserk, Gluttony, Aftermath for
 *     Damp's onAnyDamage, Endure) unmarked (tools/datagen/tablegen/items.py pins the pin's full list of such handlers);
 *   - the hook fires and the neighbours do not: a member without the item draws nothing and gets no event; the holder draws
 *     exactly one value of the site and bounds of the pin (1 in 5, 1 in 10), a success prints ACTIVATE with cause ITEM and the
 *     item, Quick Claw sets the record's bit DFI_QRES_QUICK_CLAW and nothing else of the byte, Focus Band leaves 1 HP only for a
 *     lethal damage of a Move, and a failed roll changes nothing;
 *   - the refusal by name: a Damage event of 0 for a Focus Band holder is E_UNSUPPORTED with no draw and the damage unchanged;
 *   - the draws stay off every path without the item: in every committed POOL battle, a tape entry of site 27 or 28 appears only
 *     in a battle where a member of the teams holds Quick Claw or Focus Band;
 *   - the recorded battles of 5eh (qc_*, fb_*): the ACTIVATE lines stand where the pin prints them (Quick Claw's before every other
 *     event of the step, Focus Band's directly before the holder's DAMAGE, which leaves 1 HP), for both viewers.
 *   - the observation digest accepts ACTIVATE with cause ITEM (decision 0082: a new cause is entered with a test).
 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/items/draw_items.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "rng/draw.h"
#include "state/battle_internal.h"
#include "state/observation_digest.h"
#include "state/request.h"
#include "support/check.h"
#include "support/conformance_replay.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void check_marks(df_test *t)
{
    DF_CHECK_EQ_U64(t, DFI_SITE_QUICK_CLAW, 27u);
    DF_CHECK_EQ_U64(t, DFI_SITE_FOCUS_BAND, 28u);
    DF_CHECK(t, strcmp(dfi_site_name(DFI_SITE_QUICK_CLAW), "quick-claw") == 0);
    DF_CHECK(t, strcmp(dfi_site_name(DFI_SITE_FOCUS_BAND), "focus-band") == 0);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_QUICKCLAW], 1u);
    DF_CHECK_EQ_U64(t, dfi_support.items[DFI_ITEM_FOCUSBAND], 1u);
    /* The rows of the pool whose FractionalPriority or Damage handler the rolls do not model must stay unmarked: Quick Draw and
     * Stall would change the relay value or the fraction, Disguise and Poison Heal (priority 1) stop the Damage event before
     * Focus Band, Heatproof halves a burn's damage before it, Berserk and Gluttony only record a flag, Damp's onAnyDamage stops
     * only Aftermath's damage, Endure (priority -10) prints its line before the roll. */
    static const uint32_t abilities[] = {DFI_ABILITY_QUICKDRAW, DFI_ABILITY_STALL, DFI_ABILITY_DISGUISE, DFI_ABILITY_POISONHEAL,
                                         DFI_ABILITY_HEATPROOF, DFI_ABILITY_BERSERK, DFI_ABILITY_GLUTTONY, DFI_ABILITY_AFTERMATH};
    for (size_t i = 0u; i < sizeof abilities / sizeof abilities[0]; ++i) {
        if (!DF_CHECK_EQ_U64(t, dfi_support.abilities[abilities[i]], 0u)) {
            fprintf(stderr, "  ability %u is marked: the rolls of 5eh do not model its Damage or FractionalPriority handler\n",
                    (unsigned)abilities[i]);
        }
    }
    DF_CHECK_EQ_U64(t, dfi_support.moves[DFI_MOVE_ENDURE], 0u);
    /* The cause ITEM of an ACTIVATE is a line of the observation digest (decision 0082), with its holder and id2. */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_ACTIVATE, 0u);
    e.cause = (uint8_t)DUOFORGE_CAUSE_ITEM;
    e.id2 = (uint16_t)(1u + DFI_ITEM_QUICKCLAW);
    const dfi_visible_identity identity = {0x0102u, 1u, 1u};
    uint8_t bytes[64];
    uint32_t size = 0u;
    DF_CHECK(t, dfi_observation_line_encode(&e, &identity, bytes, sizeof bytes, &size) == DUOFORGE_OK);
}

/* One tape entry of `site` [0, hi) with `value`; the draws of the helper under test come from it alone. */
static dfi_draws tape_of(const dfi_tape_entry *tape, uint32_t len)
{
    dfi_draws d;
    memset(&d, 0, sizeof d);
    d.tape = tape;
    d.tape_len = len;
    return d;
}

static void set_item(duoforge_battle *b, uint32_t flat, uint32_t item_code)
{
    dfi_member *m = dfi_at(b, flat);
    m->item = (uint8_t)item_code; /* wide-operands-reviewed: an item code of the pool */
    m->item_consumed = 0u;
    b->tail.sides[flat / 2u].item_now[b->sides[flat / 2u].positions[flat % 2u].occupant] = 0u;
}

static void check_helpers(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = df_conf_replay_by_name(t, ctx, "life_dew_water_absorb", 1u);
    if (b == NULL) {
        return;
    }
    static dfi_events ev;
    dfi_run r;
    memset(&r, 0, sizeof r);
    r.ctx = ctx;
    r.b = b;
    r.events = &ev;
    /* Quick Claw: no holder, no draw and no event. */
    set_item(b, 0u, 1u + DFI_ITEM_LEFTOVERS);
    dfi_draws none = tape_of(NULL, 0u);
    r.draws = &none;
    ev.count = 0u;
    uint8_t reserve = 0x1Cu; /* original-target bits set: they must stay */
    DF_CHECK(t, dfi_quick_claw_roll(&r, 0u, dfi_at(b, 0u), &reserve) == DUOFORGE_OK);
    DF_CHECK(t, none.tape_pos == 0u && !none.failed && none.log_len == 0u && ev.count == 0u && reserve == 0x1Cu);
    /* A holder: one draw of random(5); 0 succeeds (ACTIVATE, the bit), 1 to 4 fail (nothing). */
    set_item(b, 0u, 1u + DFI_ITEM_QUICKCLAW);
    for (uint32_t v = 0u; v < 5u; ++v) {
        const dfi_tape_entry tape[1] = {{DFI_SITE_QUICK_CLAW, 0u, 5u, v}};
        dfi_draws d = tape_of(tape, 1u);
        r.draws = &d;
        ev.count = 0u;
        reserve = 0x1Cu;
        DF_CHECK(t, dfi_quick_claw_roll(&r, 0u, dfi_at(b, 0u), &reserve) == DUOFORGE_OK);
        DF_CHECK(t, d.tape_pos == 1u && !d.failed);
        if (v == 0u) {
            DF_CHECK_EQ_U64(t, reserve, 0x1Cu | DFI_QRES_QUICK_CLAW);
            DF_CHECK(t, ev.count == 1u && ev.rec[0].kind == DUOFORGE_EVENT_ACTIVATE && ev.rec[0].position == 0u &&
                            ev.rec[0].cause == DUOFORGE_CAUSE_ITEM && ev.rec[0].id2 == 1u + DFI_ITEM_QUICKCLAW &&
                            ev.rec[0].other == DUOFORGE_NO_POSITION && ev.rec[0].id == 0u);
        } else {
            DF_CHECK(t, reserve == 0x1Cu && ev.count == 0u);
        }
    }
    /* The pin's bounds: a tape that answers random(10) at the site is a mismatch (the draw is random(5)). */
    {
        const dfi_tape_entry wrong[1] = {{DFI_SITE_QUICK_CLAW, 0u, 10u, 0u}};
        dfi_draws d = tape_of(wrong, 1u);
        r.draws = &d;
        reserve = 0u;
        DF_CHECK(t, dfi_quick_claw_roll(&r, 0u, dfi_at(b, 0u), &reserve) == DUOFORGE_E_INVARIANT && reserve == 0u);
    }
    /* Focus Band: no holder, no draw. */
    dfi_member *m = dfi_at(b, 2u);
    const uint32_t hp = m->hp;
    set_item(b, 2u, 1u + DFI_ITEM_SITRUSBERRY);
    none = tape_of(NULL, 0u);
    r.draws = &none;
    ev.count = 0u;
    uint32_t amount = hp + 50u;
    DF_CHECK(t, dfi_focus_band_roll(&r, 2u, m, true, &amount) == DUOFORGE_OK);
    DF_CHECK(t, none.tape_pos == 0u && !none.failed && ev.count == 0u && amount == hp + 50u);
    set_item(b, 2u, 1u + DFI_ITEM_FOCUSBAND);
    /* The refusal: a Damage event of 0, no draw, the damage unchanged. */
    amount = 0u;
    DF_CHECK(t, dfi_focus_band_roll(&r, 2u, m, true, &amount) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, none.tape_pos == 0u && !none.failed && ev.count == 0u && amount == 0u);
    /* (value, a Move's damage, the damage) -> the damage after the handler and whether it printed. */
    static const struct {
        uint32_t value;
        bool move_effect;
        uint32_t extra; /* damage = hp + extra, or hp - 1 for UINT32_MAX */
        bool saved;
    } cases[] = {
        {0u, true, 0u, true},           /* exactly lethal: saved */
        {0u, true, 300u, true},         /* overkill: saved */
        {0u, false, 300u, false},       /* recoil, an item, the weather: drawn, never saved */
        {0u, true, UINT32_MAX, false},  /* not lethal: drawn, not saved */
        {1u, true, 300u, false},        /* the roll fails */
        {9u, true, 0u, false},
    };
    for (size_t i = 0u; i < sizeof cases / sizeof cases[0]; ++i) {
        const dfi_tape_entry tape[1] = {{DFI_SITE_FOCUS_BAND, 0u, 10u, cases[i].value}};
        dfi_draws d = tape_of(tape, 1u);
        r.draws = &d;
        ev.count = 0u;
        const uint32_t before = cases[i].extra == UINT32_MAX ? hp - 1u : hp + cases[i].extra;
        amount = before;
        DF_CHECK(t, dfi_focus_band_roll(&r, 2u, m, cases[i].move_effect, &amount) == DUOFORGE_OK);
        DF_CHECK(t, d.tape_pos == 1u && !d.failed && m->hp == hp);
        if (cases[i].saved) {
            DF_CHECK_EQ_U64(t, amount, hp - 1u);
            DF_CHECK(t, ev.count == 1u && ev.rec[0].kind == DUOFORGE_EVENT_ACTIVATE && ev.rec[0].position == 2u &&
                            ev.rec[0].cause == DUOFORGE_CAUSE_ITEM && ev.rec[0].id2 == 1u + DFI_ITEM_FOCUSBAND);
        } else if (!DF_CHECK(t, amount == before && ev.count == 0u)) {
            fprintf(stderr, "  focus band case %u: damage %u -> %u, %u events\n", (unsigned)i, before, amount, ev.count);
        }
    }
    duoforge_battle_destroy(b);
}

/* Every committed POOL battle: a tape entry of site 27 or 28 only where a member holds the item of the site. */
static void check_no_draw_without_item(df_test *t)
{
    uint32_t qc_battles = 0u;
    uint32_t fb_battles = 0u;
    for (size_t i = 0u; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        const df_conf_battle *cb = &conf_battles[i];
        bool qc = false;
        bool fb = false;
        for (uint32_t s = 0u; s < 2u; ++s) {
            for (uint32_t k = 0u; k < cb->member_count; ++k) {
                qc = qc || cb->members[s][k].item == 1u + DFI_ITEM_QUICKCLAW;
                fb = fb || cb->members[s][k].item == 1u + DFI_ITEM_FOCUSBAND;
            }
        }
        uint32_t n27 = 0u;
        uint32_t n28 = 0u;
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            for (uint32_t k = 0u; k < st->tape_len; ++k) {
                const dfi_tape_entry *e = &conf_tape[st->tape_off + k];
                n27 += e->site == DFI_SITE_QUICK_CLAW ? 1u : 0u;
                n28 += e->site == DFI_SITE_FOCUS_BAND ? 1u : 0u;
                if (e->site == DFI_SITE_QUICK_CLAW) {
                    DF_CHECK(t, e->lo == 0u && e->hi == 5u && e->value < 5u);
                }
                if (e->site == DFI_SITE_FOCUS_BAND) {
                    DF_CHECK(t, e->lo == 0u && e->hi == 10u && e->value < 10u);
                }
            }
        }
        if (!DF_CHECK(t, (n27 == 0u || qc) && (n28 == 0u || fb))) {
            fprintf(stderr, "  %s: %u Quick Claw and %u Focus Band draws without the item\n", cb->name, n27, n28);
        }
        qc_battles += n27 != 0u ? 1u : 0u;
        fb_battles += n28 != 0u ? 1u : 0u;
    }
    /* The recorded battles of 5eh are among them (a lower bound: more battles may hold the items later). */
    DF_CHECK(t, qc_battles >= 1u && fb_battles >= 1u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.items.quick_claw_focus_band");
    check_marks(&t);
    check_no_draw_without_item(&t);
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_helpers(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
