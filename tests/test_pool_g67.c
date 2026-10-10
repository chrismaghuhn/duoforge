/*
 * duoforge.state.pool_g67 (white-box): step G67 of the content expansion, Magic Guard and Air Balloon (decision 0015 entry 5bl),
 * and the event ITEM_SHOWN (decision 0033).
 *
 * Magic Guard (data/abilities.ts:2465-2476) blocks every damage whose Showdown effect is not a Move: the Damage event
 * (sim/battle.ts:2093-2140) runs for each of them, and a directDamage (sim/pokemon.ts:1595) never reaches it. The turn code classes
 * every indirect damage with dfi_deal's required dfi_dmg_class (src/combat/turn.c). The class table, per recorded battle:
 *
 *   SIDE (Stealth Rock, Spikes), WEATHER (sandstorm), STATUS (burn, poison, toxic), CONDITION (Spiky Shield), RECOIL, ITEM (Life Orb,
 *   Rocky Helmet): skipped silently by a Magic Guard holder. ABILITY (Rough Skin, Solar Power): skipped with -activate of the
 *   ability's holder. DIRECT (Substitute and Clangorous Soul costs, Struggle's recoil) and MOVE (a move's hit, confusion's self-hit):
 *   taken. UNCLASSIFIED: refused (E_UNSUPPORTED) for a Magic Guard holder.
 *
 * The recorded battles (tests/reference/specs/g67_*) carry the reference's lines for each class, and test_conformance compares every
 * step with them. This test replays them to the end: the marks, that each battle replays with no refusal, and the event ITEM_SHOWN
 * (decision 0033) leaves the viewer's knowledge unchanged.
 *
 *   - g67_magic_guard_sandstorm: Clefable (Magic Guard) in the Sandstorm, Milotic (the control) takes the chip;
 *   - g67_magic_guard_hazards: Clefable (Magic Guard) comes in on Stealth Rock and takes no damage;
 *   - g67_magic_guard_recoil: Clefable (Magic Guard) into Garchomp's Rough Skin (-activate) and a Double-Edge with no recoil line;
 *   - g67_balloon_ground: Raichu (Air Balloon) is announced at its switch-in, immune to Earthquake (plain -immune), and popped by
 *     the Dragon Claw that knocks it out (the pop is before the faint);
 *   - g67_balloon_stealth_rock: the balloon holder takes Stealth Rock and keeps its balloon.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/events.h"
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

/* The marks: both rows are engine rows (handler NONE, read by id), and the switch-in line is the event kind 48. */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_MAGICGUARD] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_MAGICGUARD], DFI_HANDLER_NONE);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_AIRBALLOON] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_item_handler[DFI_ITEM_AIRBALLOON], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_ITEM_SHOWN, 48u); /* decision 0033 */
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_ITEM_SHOWN, DUOFORGE_EVENT_CLEAR_ALL_BOOSTS + 1u);
}

/* Each G67 battle replays to its end: the classes of the table above are what the recorded lines show, and the turn code
 * takes or skips the damage accordingly (test_conformance compares the HP and the lines of every step). */
static void check_battles(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g67_magic_guard_sandstorm", "g67_magic_guard_hazards", "g67_magic_guard_recoil",
                                        "g67_balloon_ground", "g67_balloon_stealth_rock"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        duoforge_battle *b = replay_all(t, ctx, names[i]);
        if (b != NULL) {
            duoforge_battle_destroy(b);
        }
    }
}

/* The fold ignores ITEM_SHOWN (decision 0033): the open team sheets already show the item, so a fold of this event leaves the
 * viewer's knowledge (the whole battle record, as the fold writes it) exactly as it was. */
static void check_fold_ignores_item_shown(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_all(t, ctx, "g67_balloon_ground");
    if (b == NULL) {
        return;
    }
    duoforge_battle *copy = malloc(sizeof *copy);
    if (!DF_CHECK(t, copy != NULL)) {
        duoforge_battle_destroy(b);
        return;
    }
    memcpy(copy, b, sizeof *copy);
    dfi_events ev;
    memset(&ev, 0, sizeof ev);
    ev.rec[0] = dfi_event_make(DUOFORGE_EVENT_ITEM_SHOWN, 2u);
    ev.rec[0].id2 = (uint16_t)(1u + DFI_ITEM_AIRBALLOON);
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, copy, &ev, 0u));
    DF_CHECK(t, memcmp(b, copy, sizeof *copy) == 0);
    free(copy);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g67");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_battles(&t, ctx);
    check_fold_ignores_item_shown(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
