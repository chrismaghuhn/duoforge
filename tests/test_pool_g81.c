/*
 * duoforge.state.pool_g81 (white-box): step G81 of the content expansion, Frisk (decision 0015 entry 5bs), and the event
 * ITEM_SHOWN in its Frisk form (decision 0033).
 *
 * Frisk (data/abilities.ts:1545-1557) announces, at its holder's switch-in, the item of every foe in foes() order that holds one:
 * `-item|X|Item|[from] ability: Frisk|[of] Y` (no [identify]: the pin prints none). The turn code emits ITEM_SHOWN with the foe as
 * the position, the Frisk user in other, cause ABILITY, id = Frisk + 1 and id2 = the item + 1 (dfi_frisk, src/combat/turn.c). The
 * switch-in order is the one of the entry handlers (the leads are on the field before any of them runs, as the reference's
 * `|switch|` lines come first).
 *
 * The recorded battles (tests/reference/specs/g81_*) carry the reference's lines, and test_conformance compares every step with
 * them. This test replays them to the end and checks:
 *   - the marks: Frisk is an engine row (handler NONE) and the event kind is 48;
 *   - g81_frisk_two_foes: two foes with items, two lines in slot order;
 *   - g81_frisk_foe_no_item: one foe with an item and one without (one line);
 *   - g81_frisk_before_intimidate: the Frisk user is faster, so its line comes before the Intimidate line;
 *   - g81_frisk_after_intimidate: the Frisk user is slower, so the Intimidate line comes first;
 *   - g81_frisk_two_holders: two Frisk holders, each announcing the items of the other side;
 *   - the fold ignores the Frisk form of ITEM_SHOWN: the battle record (the state and the viewers' knowledge) is unchanged, because
 *     the open team sheets already show every item (no view change).
 *
 * Not in this test: Frisk against an Illusion-disguised foe (refused with E_UNSUPPORTED, decision 0015 entry 5bs, not reached by a
 * recorded battle).
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

/* The marks: Frisk is an engine row (handler NONE, read by id), and the switch-in line of its items is the event kind 48. */
static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_FRISK] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_FRISK], DFI_HANDLER_NONE);
    DF_CHECK_EQ_U64(t, DUOFORGE_EVENT_ITEM_SHOWN, 48u); /* decision 0033 */
}

/* Each G81 battle replays to its end: test_conformance compares every step's lines and HP with the reference. The per-battle
 * checks of the Frisk lines are the conformance lines themselves; this loop only proves that each replays with no refusal. */
static void check_battles(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g81_frisk_two_foes", "g81_frisk_foe_no_item", "g81_frisk_before_intimidate",
                                        "g81_frisk_after_intimidate", "g81_frisk_two_holders"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; ++i) {
        duoforge_battle *b = replay_all(t, ctx, names[i]);
        if (b != NULL) {
            duoforge_battle_destroy(b);
        }
    }
}

/* The fold ignores the Frisk form of ITEM_SHOWN (decision 0033): the open team sheets already show the item, so a fold of this event
 * leaves the battle record (the state and the viewers' knowledge) exactly as it was. The Frisk user is the foe's opposite. */
static void check_fold_ignores_frisk_item_shown(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_all(t, ctx, "g81_frisk_two_foes");
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
    ev.rec[0].cause = DUOFORGE_CAUSE_ABILITY;
    ev.rec[0].id = (uint16_t)(1u + DFI_ABILITY_FRISK); /* wide-operands-reviewed: 67, below 2^16 */
    ev.rec[0].id2 = (uint16_t)(1u + DFI_ITEM_AIRBALLOON); /* wide-operands-reviewed: any held item, below 2^16 */
    ev.rec[0].other = 0u;
    ev.count = 1u;
    DF_CHECK(t, dfi_events_fold_knowledge(b, copy, &ev, 0u));
    DF_CHECK(t, memcmp(b, copy, sizeof *copy) == 0);
    free(copy);
    duoforge_battle_destroy(b);
}

/* Frisk against an Illusion-disguised foe that holds an item is refused (E_UNSUPPORTED, decision 0015 entry 5bs): the handler
 * checks every standing foe before it emits its first line, so the refusal stands before any ITEM_SHOWN is made. The setup is the
 * I2 battle i2_illusion_break: Zoroark (Focus Sash, Illusion) leads on side 0 disguised as Gholdengo, the disguise up at its
 * switch-in. Side 1's lead is made a Frisk holder (Noivern, a legal pool forme), so it enters beside the disguised foe; the battle
 * is not created. */
static void check_illusion_refusal(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("i2_illusion_break");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    setup.sides[1].members[0].species_id = DFI_FORME_NOIVERN;
    setup.sides[1].members[0].ability = DFI_ABILITY_FRISK + 1u;
    setup.sides[1].members[0].gender = DFI_GENDER_MALE;
    /* Noivern learns Protect and Hurricane (the setup checks each move of the forme): Primarina's moves are replaced. */
    setup.sides[1].members[0].move_count = 2u;
    setup.sides[1].members[0].moves[0].move_id = DFI_MOVE_HURRICANE;
    setup.sides[1].members[0].moves[1].move_id = DFI_MOVE_PROTECT;
    duoforge_battle *b = NULL;
    DF_CHECK_EQ_U64(t, (uint64_t)duoforge_battle_create(ctx, &setup, &b), (uint64_t)DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, b == NULL);
    if (b != NULL) {
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g81");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    check_marks(&t);
    check_battles(&t, ctx);
    check_fold_ignores_frisk_item_shown(&t, ctx);
    check_illusion_refusal(&t, ctx);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
