/*
 * duoforge.state.pool_g29 (white-box): step G29 of the content expansion, the item-transfer moves Trick, Switcheroo, Thief
 * and Covet, in the POOL tail's item_now (decision 0015 section 7), in the events (ITEM_START for a
 * `-item` line, ITEM_END with the cause ITEM_TAKEN for the silent `-enditem` of an item that left), in what reads the held
 * item and in the view extension (decision 0018: item_now of the member, bit 11).
 *
 * The recorded battles (under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares every HP, stage, request and event the reference shows (and the
 * item that each member holds, the old item_used of both viewers, Unburden's Speed in the order of the moves, the Choice
 * lock in the requests). Here the state that the reference does not show is read after every step: the tail's item_now of
 * every roster member, the step's events, and both viewers' whole extension. The pin: data/moves.ts:19865-19911 trick,
 * :18644-18690 switcheroo, :19302-19330 thief, :3099-3123 covet, sim/pokemon.ts:1851-1889 takeItem and setItem,
 * data/abilities.ts:4622-4635 stickyhold and :5240-5242 unburden, data/items.ts:27 (the Mega Stone's onTakeItem).
 *
 * The rows are what the protocol lines say alone, derived by tools/reference/test_trace_to_c.py from the committed traces,
 * which requires this table to be exactly that: after each step the expected item_now of every roster member (side * 6 +
 * roster index): `|-item|X|Item|[from] move: M` gives X the item (item id + 1), `|-enditem|X|Item|[silent]|[from] move: M`
 * and the `[of] Y` of a Thief or Covet line take it away (255, DUOFORGE_ITEM_NOW_NONE); a used-up item changes nothing (the
 * tail keeps the id: the member's consumed flag says so), and neither does a switch.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/invariants.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

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

/* After each step: the item_now of the 12 roster members (side 0 first), and how many `-item` lines (`received`: the
 * ITEM_START events each viewer sees) and how many silent `-enditem ... [from] move:` lines (`left`: the ITEM_END
 * events of cause ITEM_TAKEN) the step has. */
/* ROWS-BEGIN */
static const struct {
    const char *battle;
    uint32_t step;
    uint8_t item_now[12];
    uint32_t received;
    uint32_t left;
} rows[] = {
    {"g29_trick_scarf", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_scarf", 1u, {16u, 0u, 0u, 0u, 0u, 0u, 9u, 0u, 0u, 0u, 0u, 0u}, 2u, 0u},
    {"g29_trick_scarf", 2u, {16u, 0u, 0u, 0u, 0u, 0u, 9u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_scarf", 3u, {16u, 0u, 0u, 0u, 0u, 0u, 9u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_scarf", 4u, {16u, 0u, 0u, 0u, 0u, 0u, 9u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_scarf", 5u, {16u, 0u, 0u, 0u, 0u, 0u, 9u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_empty_hands", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_empty_hands", 1u, {255u, 27u, 0u, 0u, 0u, 0u, 3u, 255u, 0u, 0u, 0u, 0u}, 2u, 2u},
    {"g29_empty_hands", 2u, {255u, 27u, 0u, 0u, 0u, 0u, 3u, 255u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_empty_hands", 3u, {255u, 255u, 0u, 0u, 0u, 0u, 3u, 27u, 0u, 0u, 0u, 0u}, 1u, 1u},
    {"g29_empty_hands", 4u, {255u, 255u, 0u, 0u, 0u, 0u, 3u, 27u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_empty_hands", 5u, {255u, 255u, 0u, 0u, 0u, 0u, 3u, 27u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 1u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 1u, 0u},
    {"g29_thief_covet", 2u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 3u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 4u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 5u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_covet", 6u, {3u, 14u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 255u, 0u, 0u}, 1u, 1u},
    {"g29_thief_covet", 7u, {3u, 14u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 255u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 2u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 3u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 4u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_fails", 5u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_edge_cases", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_edge_cases", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_edge_cases", 2u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 1u, 1u},
    {"g29_edge_cases", 3u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_edge_cases", 4u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_edge_cases", 5u, {3u, 0u, 0u, 0u, 0u, 0u, 255u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_lock_before_move", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_lock_before_move", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_lock_before_move", 2u, {16u, 0u, 0u, 0u, 0u, 0u, 6u, 0u, 0u, 0u, 0u, 0u}, 2u, 0u},
    {"g29_trick_lock_before_move", 3u, {16u, 0u, 0u, 0u, 0u, 0u, 6u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_trick_lock_before_move", 4u, {16u, 0u, 0u, 0u, 0u, 0u, 6u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_fainted", 0u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_fainted", 1u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_fainted", 2u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_fainted", 3u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
    {"g29_thief_fainted", 4u, {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u}, 0u, 0u},
};
/* ROWS-END */

static const char *const battle_names[] = {"g29_trick_scarf", "g29_empty_hands", "g29_thief_covet", "g29_trick_fails", "g29_edge_cases",
                                           "g29_trick_lock_before_move", "g29_thief_fainted"};

static void check_battles(df_test *t, const duoforge_context *ctx, uint32_t *compared)
{
    for (size_t n = 0u; n < sizeof battle_names / sizeof battle_names[0]; ++n) {
        const df_conf_battle *cb = find(battle_names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            if (!DF_CHECK(t, dfi_battle_step_events_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res,
                                                          buffers) == DUOFORGE_OK)) {
                break;
            }
            DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
            int row = -1;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, battle_names[n]) == 0 && rows[r].step == si) {
                    row = (int)r;
                }
            }
            if (!DF_CHECK(t, row >= 0)) {
                fprintf(stderr, "  %s step %u: no row\n", battle_names[n], si);
                continue;
            }
            const uint8_t *want_items = rows[row].item_now;
            /* The tail. */
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    if (!DF_CHECK_EQ_U64(t, b->tail.sides[s].item_now[m], want_items[s * 6u + m])) {
                        fprintf(stderr, "  %s step %u: side %u member %u\n", battle_names[n], si, s, m);
                    }
                }
            }
            /* The Choice lock through a Trick (g29_trick_lock_before_move, the Annihilape of side 1): locked by its Scarf at the
             * end of turn 1 (step 1), and at the stop of turn 2 (step 2) it has moved after the Prankster Trick took the
             * Scarf and gave it a Life Orb: choicelock's onBeforeMove ended the lock when it moved (data/conditions.ts:332-336),
             * so none stands although it was no Choice item that came (the lock is not ended by the item's going). */
            if (strcmp(battle_names[n], "g29_trick_lock_before_move") == 0 && (si == 1u || si == 2u)) {
                const dfi_active_slot *lp = &b->sides[1].positions[0];
                const bool locked = ((uint32_t)lp->flags & DFI_VOL_CHOICE_LOCK) != 0u;
                DF_CHECK(t, locked == (si == 1u));
                DF_CHECK(t, (lp->locked_move != 0u) == (si == 1u));
            }
            /* The events: both viewers see both kinds of line (items are public); the move is the one of the line and the item
             * is a real one; a received item has a position, a Thief's or Covet's line names the one it came from. */
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t received = 0u;
                uint32_t left = 0u;
                for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                    const duoforge_event *e = &buffers[viewer].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_ITEM_START) {
                        DF_CHECK(t, e->cause == (uint8_t)DUOFORGE_CAUSE_MOVE);
                        received += 1u;
                        DF_CHECK(t, e->id == DFI_MOVE_TRICK || e->id == DFI_MOVE_SWITCHEROO || e->id == DFI_MOVE_THIEF ||
                                        e->id == DFI_MOVE_COVET);
                        DF_CHECK(t, e->id2 != 0u && e->id2 <= DFI_POOL_ITEM_COUNT && e->position < 4u);
                        DF_CHECK(t, (e->other == DUOFORGE_NO_POSITION) == (e->id == DFI_MOVE_TRICK || e->id == DFI_MOVE_SWITCHEROO));
                    } else if (e->kind == (uint8_t)DUOFORGE_EVENT_ITEM_END && e->cause == (uint8_t)DUOFORGE_CAUSE_ITEM_TAKEN &&
                               e->id != DFI_MOVE_KNOCKOFF) {
                        left += 1u;
                        DF_CHECK(t, e->id == DFI_MOVE_TRICK || e->id == DFI_MOVE_SWITCHEROO || e->id == DFI_MOVE_THIEF);
                        DF_CHECK(t, e->id2 != 0u && e->id2 <= DFI_POOL_ITEM_COUNT && e->position < 4u);
                    }
                }
                if (!DF_CHECK(t, received == rows[row].received && left == rows[row].left)) {
                    fprintf(stderr, "  %s step %u viewer %u: %u received (want %u), %u left (want %u)\n", battle_names[n], si,
                            viewer, received, rows[row].received, left, rows[row].left);
                }
            }
            /* The extension: item_now at the members of the row, nothing else; both viewers see the same (public). */
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                for (uint32_t s = 0u; s < 2u; ++s) {
                    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                        if (!DF_CHECK_EQ_U64(t, ext[viewer].sides[s].members[m].item_now, want_items[s * 6u + m])) {
                            fprintf(stderr, "  %s step %u viewer %u: item_now of side %u member %u\n", battle_names[n], si,
                                    viewer, s, m);
                        }
                    }
                }
                DF_CHECK(t, (ext[viewer].supported & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE)) != 0u);
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

/* The rules that step G29 changed, for the kinds that have them and not for the others (decision 0015 section 7). Before the
 * step an Unburden volatile needed an item that was gone (the one exception: a holder of its own Mega Stone), and a member
 * without a sheet item could not have used one. A Trick, Thief or Covet makes both reachable: a swap sets the volatile when
 * the TakeItem handlers run, also when the move then fails or gives an item back, and an item that a move gave may be used
 * up. So under the POOL kinds the volatile may stand with an item held, and the consumed flag of a member without a sheet
 * item is valid when the tail's item_now names the item it used; under every other kind both stay refused (no move there
 * gives an item, and the tail is absent). The same battle, one on each kind, decides it. */
static void set_member_of(duoforge_member_setup *m, uint32_t species, uint32_t gender, uint32_t ability_plus1,
                          uint32_t item_plus1, uint32_t move_count, const uint32_t *moves)
{
    memset(m, 0, sizeof *m);
    m->species_id = species;
    m->gender = gender;
    m->nature = DFI_NATURE_HARDY;
    m->stat_points[0] = 32u;
    m->stat_points[1] = 32u;
    m->stat_points[5] = 2u;
    m->ability = ability_plus1;
    m->item = item_plus1;
    m->move_count = move_count;
    for (uint32_t k = 0u; k < move_count; ++k) {
        m->moves[k].move_id = moves[k];
    }
}

static void put_side(duoforge_side_setup *side, bool unburden_first)
{
    const uint32_t sneasler[3] = {DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_FAKEOUT};
    const uint32_t incineroar[2] = {DFI_MOVE_FAKEOUT, DFI_MOVE_PARTINGSHOT};
    const uint32_t salamence[2] = {DFI_MOVE_PROTECT, DFI_MOVE_TAILWIND};
    const uint32_t indeedee[2] = {DFI_MOVE_TRICKROOM, DFI_MOVE_PSYCHIC};
    const uint32_t kingambit[2] = {DFI_MOVE_IRONHEAD, DFI_MOVE_PROTECT};
    memset(side, 0, sizeof *side);
    side->member_count = 5u;
    set_member_of(&side->members[0], DFI_FORME_SNEASLER, DUOFORGE_GENDER_MALE,
                  unburden_first ? DFI_ABILITY_UNBURDEN + 1u : 0u, unburden_first ? DFI_ITEM_LEFTOVERS + 1u : 0u, 3u, sneasler);
    set_member_of(&side->members[1], DFI_FORME_INCINEROAR, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE + 1u,
                  DFI_ITEM_SITRUSBERRY + 1u, 2u, incineroar);
    set_member_of(&side->members[2], DFI_FORME_SALAMENCE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE + 1u, 0u, 2u, salamence);
    set_member_of(&side->members[3], DFI_FORME_INDEEDEEF, DUOFORGE_GENDER_FEMALE, 0u, 0u, 2u, indeedee);
    set_member_of(&side->members[4], DFI_FORME_KINGAMBIT, DUOFORGE_GENDER_MALE, 0u, 0u, 2u, kingambit);
}

static duoforge_battle *turn_one(const duoforge_context *ctx)
{
    duoforge_battle_setup s;
    memset(&s, 0, sizeof s);
    s.rng_initstate = 1u;
    s.rng_initseq = 2u;
    put_side(&s.sides[0], true);
    put_side(&s.sides[1], false);
    duoforge_battle *b = df_make_battle(ctx, &s);
    if (b == NULL) {
        return NULL;
    }
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd.responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
    duoforge_step_result res;
    if (duoforge_battle_step(ctx, b, &bd, &res) != DUOFORGE_OK || b->boundary_kind != DUOFORGE_BOUNDARY_TURN) {
        duoforge_battle_destroy(b);
        return NULL;
    }
    return b;
}

static void check_kind_rules(df_test *t, const duoforge_context *k_other, const duoforge_context *k_pool)
{
    for (uint32_t pass = 0u; pass < 2u; ++pass) {
        const duoforge_context *ctx = pass == 0u ? k_other : k_pool;
        const bool pool = pass == 1u;
        duoforge_battle *w = turn_one(ctx);
        if (!DF_CHECK(t, w != NULL)) {
            continue;
        }
        dfi_invariant inv = DFI_INV_NONE;
        dfi_active_slot *pos = &w->sides[0].positions[0];
        dfi_member *holder = &w->sides[0].members[pos->occupant];
        const duoforge_status first = dfi_state_check(ctx, w, &inv);
        if (first != DUOFORGE_OK) {
            fprintf(stderr, "  kind rules: pass %u first check %u inv %u\n", pass, (unsigned)first, (unsigned)inv);
        }
        DF_CHECK(t, first == DUOFORGE_OK && holder->item_consumed == 0u);
        /* An Unburden holder with the volatile and its Leftovers still held. */
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN);
        inv = DFI_INV_NONE;
        if (pool) {
            DF_CHECK(t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
        } else {
            DF_CHECK(t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        }
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_UNBURDEN);
        /* A member without a sheet item whose consumed flag is set: refused, unless (POOL) the tail names the item. */
        dfi_member *bare = &w->sides[0].members[2];
        DF_CHECK_EQ_U64(t, bare->item, 0u);
        bare->item_consumed = 1u;
        inv = DFI_INV_NONE;
        DF_CHECK(t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT);
        if (pool) {
            w->tail.sides[0].item_now[2] = (uint8_t)(1u + DFI_ITEM_LEFTOVERS);
            DF_CHECK(t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
            w->tail.sides[0].item_now[2] = (uint8_t)DUOFORGE_ITEM_NOW_NONE; /* taken, not used: the flag has no item behind it */
            DF_CHECK(t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT);
        }
        duoforge_battle_destroy(w);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g29");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);
    /* The ids that the step uses, and its marks. */
    DF_CHECK_EQ_U64(&t, DUOFORGE_EVENT_ITEM_START, 42u); /* the new public value (owner's OK pending) */
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_TRICK, 56u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SWITCHEROO, 57u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_THIEF, 58u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_COVET, 59u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_SUPER_FANG, 60u); /* step G39 follows */
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_STRENGTH_SAP + 1u); /* Taunt and Yawn (step G31) at 61 and 62; step G48 adds four handlers */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TRICK] != 0u && dfi_support.moves[DFI_MOVE_SWITCHEROO] != 0u &&
                     dfi_support.moves[DFI_MOVE_THIEF] != 0u && dfi_support.moves[DFI_MOVE_COVET] != 0u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE, 11u);
    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev);
    DF_CHECK_EQ_U64(&t, compared_dev, compared);
    duoforge_context *kt = df_make_context(&df_config_team_c_dev);
    check_kind_rules(&t, kt, kd);
    duoforge_context_destroy(kt);
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
