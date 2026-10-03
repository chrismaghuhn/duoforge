/*
 * duoforge.state.pool_g16 (white-box): step G16 of the content expansion, Knock Off, in the POOL tail's item_now (decision
 * 0015 section 7), in the ITEM_END event with the cause ITEM_TAKEN, in what reads the held item and in the view
 * extension (decision 0018: item_now of the member, DUOFORGE_ITEM_NOW_NONE, bit 11).
 *
 * The recorded battles (under "data": "pool") are replayed through the step with the reference's draws, as in
 * duoforge.reference.conformance_pool_data, which compares every HP, stage, request and event the reference shows: the
 * damage lines carry what the item does to the power (the 1.5 of a hit at a Pokemon that holds an item that can be taken,
 * the plain power for a Mega Stone on its own species, an eaten or used-up item and an empty hand), the requests carry
 * the Choice lock that ends with the Scarf, the order of the moves the Speed that Unburden doubles. Here the state that
 * the reference does not show is read after every step: the tail's item_now of every roster member, and both viewers'
 * whole extension. The pin: data/moves.ts:9959-9984 knockoff, sim/pokemon.ts:1851-1866 takeItem,
 * data/mods/champions/scripts.ts:411-415 AfterHit (no test of the user's HP, unlike sim/battle-actions.ts:1123),
 * data/abilities.ts:4622-4635 stickyhold and :5240-5242 unburden.
 *
 *   g16_removal       Pelipper's Sitrus Berry is taken before the berry can be eaten (the hit leaves it at half or less);
 *                     Sneasler's Charizardite Y, a Mega Stone of another species, is taken (and stays gone after a switch-out);
 *                     a Knock Off at a Pokemon without an item has the plain power and no line.
 *   g16_unburden      Sneasler's Sitrus Berry is taken: Unburden doubles its Speed from the next turn (it moves before the
 *                     Meowscarada that was faster), a Gholdengo loses its Life Orb.
 *   g16_stones        Staraptite on Staraptor and Salamencite on Salamence stay: no 1.5, no -enditem, also after the Mega
 *                     Evolution.
 *   g16_sticky_hold   Sticky Hold of a Swalot that is alive: -activate and the Leftovers stay (the hit is boosted anyway);
 *                     a Focus Sash that the hit uses up is not taken a second time; a fainted Swalot loses its item.
 *   g16_scarf_helmet  A Choice Scarf goes with the lock, the Rocky Helmet hurts the user first and goes.
 *   g16_helmet_faint  A user that the Rocky Helmet knocks out takes the item all the same (the Champions mod).
 *   g16_scarf_lock_stays  A Choice Scarf holder that has moved loses the Scarf to a Knock Off later in a turn that stops for
 *                     a replacement: the choicelock volatile is still there (conditions.ts onDisableMove ends it in endTurn,
 *                     sim/battle.ts:1691); next turn it is gone.
 *
 * Step G24 adds one check of the state: g24_hawlucha_malamar, where a Knock Off finds Hawlucha (Unburden) with its own
 * Hawluchanite: the volatile is set and the stone stays (check_invariants).
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

/* After each step of each battle, what the protocol lines say alone: the members that hold nothing since a Knock Off took
 * their item (a bit per side * 6 + roster index; the line `|-enditem|X|Item|[from] move: Knock Off|[of] Y` sets it and
 * nothing clears it: the item stays gone across a switch-out and a faint), how many of those lines the step has (`taken`:
 * the ITEM_END events of cause ITEM_TAKEN each viewer sees) and how many `|-activate|X|ability: Sticky Hold` lines
 * (`blocked`). tools/reference/test_trace_to_c.py derives the rows from the committed traces and requires this table to be
 * exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t gone;
    uint32_t taken;
    uint32_t blocked;
} rows[] = {
    {"g16_removal", 0u, 0x0u, 0u, 0u},
    {"g16_removal", 1u, 0xc0u, 2u, 0u},
    {"g16_removal", 2u, 0x1c0u, 1u, 0u},
    {"g16_removal", 3u, 0x1c0u, 0u, 0u},
    {"g16_removal", 4u, 0x1c0u, 0u, 0u},
    {"g16_unburden", 0u, 0x0u, 0u, 0u},
    {"g16_unburden", 1u, 0xc0u, 2u, 0u},
    {"g16_unburden", 2u, 0xc0u, 0u, 0u},
    {"g16_unburden", 3u, 0xc0u, 0u, 0u},
    {"g16_stones", 0u, 0x0u, 0u, 0u},
    {"g16_stones", 1u, 0x0u, 0u, 0u},
    {"g16_stones", 2u, 0x0u, 0u, 0u},
    {"g16_stones", 3u, 0x0u, 0u, 0u},
    {"g16_sticky_hold", 0u, 0x0u, 0u, 0u},
    {"g16_sticky_hold", 1u, 0x1u, 1u, 1u},
    {"g16_sticky_hold", 2u, 0x1u, 0u, 2u},
    {"g16_sticky_hold", 3u, 0x41u, 1u, 0u},
    {"g16_sticky_hold", 4u, 0x41u, 0u, 0u},
    {"g16_scarf_helmet", 0u, 0x0u, 0u, 0u},
    {"g16_scarf_helmet", 1u, 0xc0u, 2u, 0u},
    {"g16_scarf_helmet", 2u, 0xc0u, 0u, 0u},
    {"g16_scarf_helmet", 3u, 0xc0u, 0u, 0u},
    {"g16_helmet_faint", 0u, 0x0u, 0u, 0u},
    {"g16_helmet_faint", 1u, 0x0u, 0u, 0u},
    {"g16_helmet_faint", 2u, 0x0u, 0u, 0u},
    {"g16_helmet_faint", 3u, 0x40u, 1u, 0u},
    {"g16_scarf_lock_stays", 0u, 0x0u, 0u, 0u},
    {"g16_scarf_lock_stays", 1u, 0x40u, 1u, 0u},
    {"g16_scarf_lock_stays", 2u, 0x40u, 0u, 0u},
    {"g16_scarf_lock_stays", 3u, 0xc0u, 1u, 0u},
};

static const char *const battle_names[] = {"g16_removal",      "g16_unburden",     "g16_stones",
                                           "g16_sticky_hold", "g16_scarf_helmet", "g16_helmet_faint",
                                           "g16_scarf_lock_stays"};

/* After every step of the battles: the tail's item_now of every roster member is DUOFORGE_ITEM_NOW_NONE exactly for the
 * members of the row (and nothing else of the tail is touched by the item: no other tail field is set here), the step's
 * events carry what the lines say, and both viewers' extension equals the expected one byte for byte: revision, viewer,
 * epoch, the supported bits, item_now at those members and nothing else. The item that a move took is public, so the foe
 * sees what the owner sees, and the two sections are the same. */
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
            const uint32_t gone_none = 0xFFFFFFFFu;
            uint32_t gone = gone_none;
            uint32_t want_taken = 0u;
            uint32_t want_blocked = 0u;
            for (size_t r = 0u; r < sizeof rows / sizeof rows[0]; ++r) {
                if (strcmp(rows[r].battle, battle_names[n]) == 0 && rows[r].step == si) {
                    gone = rows[r].gone;
                    want_taken = rows[r].taken;
                    want_blocked = rows[r].blocked;
                }
            }
            if (!DF_CHECK(t, gone != gone_none)) {
                fprintf(stderr, "  %s step %u: no row\n", battle_names[n], si);
                continue;
            }
            /* The tail. */
            for (uint32_t s = 0u; s < 2u; ++s) {
                for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                    const uint32_t want = ((gone >> (s * 6u + m)) & 1u) != 0u ? DUOFORGE_ITEM_NOW_NONE : 0u;
                    if (!DF_CHECK_EQ_U64(t, b->tail.sides[s].item_now[m], want)) {
                        fprintf(stderr, "  %s step %u: side %u member %u\n", battle_names[n], si, s, m);
                    }
                }
            }
            /* The events: both viewers see the removal (public) and the Sticky Hold line; an ITEM_TAKEN event names the
             * move, its user and the item, and is no used-up item (no EATEN flag). */
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                uint32_t taken = 0u;
                uint32_t blocked = 0u;
                for (uint32_t i = 0u; i < buffers[viewer].count; ++i) {
                    const duoforge_event *e = &buffers[viewer].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_ITEM_END && e->cause == (uint8_t)DUOFORGE_CAUSE_ITEM_TAKEN) {
                        taken += 1u;
                        DF_CHECK_EQ_U64(t, e->id, DFI_MOVE_KNOCKOFF);
                        DF_CHECK(t, e->id2 != 0u && e->id2 <= DFI_POOL_ITEM_COUNT);
                        DF_CHECK(t, e->other < 4u && e->position < 4u && e->other / 2u != e->position / 2u);
                        DF_CHECK(t, (e->flags & DUOFORGE_EVENT_FLAG_EATEN) == 0u && e->detail == 0u);
                    } else if (e->kind == (uint8_t)DUOFORGE_EVENT_ACTIVATE && e->cause == (uint8_t)DUOFORGE_CAUSE_ABILITY &&
                               e->id2 == 1u + DFI_ABILITY_STICKYHOLD) {
                        blocked += 1u;
                    }
                }
                if (!DF_CHECK(t, taken == want_taken && blocked == want_blocked)) {
                    fprintf(stderr, "  %s step %u viewer %u: %u taken (want %u), %u blocked (want %u)\n", battle_names[n], si,
                            viewer, taken, want_taken, blocked, want_blocked);
                }
            }
            /* The extension. */
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = dfi_support.view_ext_features;
                DF_CHECK(t, (want.supported & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE)) != 0u);
                for (uint32_t s = 0u; s < 2u; ++s) {
                    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
                        if (((gone >> (s * 6u + m)) & 1u) != 0u) {
                            want.sides[s].members[m].item_now = (uint8_t)DUOFORGE_ITEM_NOW_NONE;
                        }
                    }
                }
                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (gone 0x%x)\n",
                            battle_names[n], si, viewer, gone);
                }
                *compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
}

/* The battle `name` replayed through its first `steps` steps (step 0 is the team selection). */
static duoforge_battle *replay_to(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
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
    for (uint32_t si = 0u; si < steps && si < cb->step_count; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0u;
        if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                             DUOFORGE_OK)) {
            break;
        }
    }
    return b;
}

static dfi_invariant check_of(const duoforge_context *ctx, const duoforge_battle *b)
{
    dfi_invariant inv = DFI_INV_NONE;
    return dfi_state_check(ctx, b, &inv) == DUOFORGE_OK ? DFI_INV_NONE : inv;
}

/* The invariants that read the item (decision 0015 section 7): after a Knock Off took the item that Unburden's holder
 * had, its volatile is valid, and not without the loss; a choice lock needs a Choice item that the member still has. The
 * states are the ones of the recorded battles: Sneasler (Unburden, its Sitrus Berry taken) at the TURN boundary after step 1
 * of g16_unburden, and Annihilape of g16_scarf_helmet, whose Scarf is taken in step 1. */
static void check_invariants(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay_to(t, ctx, "g16_unburden", 2u);
    if (b != NULL) {
        dfi_active_slot *pos = &b->sides[1].positions[0];
        DF_CHECK_EQ_U64(t, b->tail.sides[1].item_now[pos->occupant], DUOFORGE_ITEM_NOW_NONE);
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u); /* set by the removal */
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        /* The same Pokemon with its item back: the volatile has no loss behind it. */
        b->tail.sides[1].item_now[pos->occupant] = 0u;
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_VOLATILE);
        /* An item that was only used up gives the volatile as before (Sitrus Berry eaten), the taken one as well. */
        b->sides[1].members[pos->occupant].item_consumed = 1u;
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        b->sides[1].members[pos->occupant].item_consumed = 0u;
        b->tail.sides[1].item_now[pos->occupant] = (uint8_t)DUOFORGE_ITEM_NOW_NONE;
        pos->flags = (uint8_t)((uint32_t)pos->flags & ~(uint32_t)DFI_VOL_UNBURDEN);
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE); /* the volatile is not required: it ends with the position */
        duoforge_battle_destroy(b);
    }
    /* Step G24: Hawlucha (Unburden) holds Hawluchanite, its own Mega Stone, and Knock Off finds it (turn 1 of
     * g24_hawlucha_malamar): the ability's onTakeItem answers before the item refuses, so the volatile is set and the stone
     * stays (data/abilities.ts:5240-5242). The volatile with the item held is valid for a holder of its own stone only; its
     * Mega Evolution (turn 3) ends the ability and with it the volatile (:5243-5245). */
    b = replay_to(t, ctx, "g24_hawlucha_malamar", 2u);
    if (b != NULL) {
        dfi_active_slot *pos = &b->sides[0].positions[0];
        dfi_member *hawlucha = &b->sides[0].members[pos->occupant];
        DF_CHECK_EQ_U64(t, hawlucha->species_id, DFI_FORME_HAWLUCHA);
        DF_CHECK_EQ_U64(t, hawlucha->item, 1u + DFI_ITEM_HAWLUCHANITE);
        DF_CHECK(t, b->tail.sides[0].item_now[pos->occupant] != DUOFORGE_ITEM_NOW_NONE); /* the stone stays */
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u);                    /* and the volatile is set */
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        /* The view shows no Unburden while the stone is held: nothing says it, and it doubles no Speed. */
        duoforge_observation obs;
        DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &obs) == DUOFORGE_OK);
        DF_CHECK(t, (obs.sides[0].positions[0].reserved & DUOFORGE_POSITION_FLAG_UNBURDEN) == 0u);
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        /* The same member with an item that is no stone of its own: the volatile has no loss behind it. */
        hawlucha->item = 1u + DFI_ITEM_SITRUSBERRY;
        hawlucha->mega_capable = 0u;
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_VOLATILE);
        duoforge_battle_destroy(b);
    }
    b = replay_to(t, ctx, "g24_hawlucha_malamar", 4u);
    if (b != NULL) {
        const dfi_active_slot *pos = &b->sides[0].positions[0];
        DF_CHECK_EQ_U64(t, b->sides[0].members[pos->occupant].is_mega, 1u);
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) == 0u); /* ended with the ability */
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        duoforge_battle_destroy(b);
    }
    b = replay_to(t, ctx, "g16_scarf_helmet", 2u);
    if (b != NULL) {
        dfi_active_slot *pos = &b->sides[1].positions[0];
        const uint32_t m = pos->occupant;
        DF_CHECK_EQ_U64(t, b->tail.sides[1].item_now[m], DUOFORGE_ITEM_NOW_NONE);
        DF_CHECK_EQ_U64(t, b->sides[1].members[m].item, 1u + DFI_ITEM_CHOICESCARF);
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u && pos->locked_move == 0u); /* ended with the Scarf */
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        /* A lock without the Scarf is refused; with the Scarf back (the sheet's item) it is valid. */
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_CHOICE_LOCK);
        pos->locked_move = 1u;
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_VOLATILE);
        b->tail.sides[1].item_now[m] = 0u;
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_KNOWLEDGE); /* the foe saw the item go: that is a fact too */
        b->sides[0].knowledge[m].revealed = (uint8_t)((uint32_t)b->sides[0].knowledge[m].revealed & ~(uint32_t)DFI_REVEALED_ITEM_CONSUMED);
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        duoforge_battle_destroy(b);
    }
    /* The lock stays until the pin ends it (g16_scarf_lock_stays): after step 1 (two entries) the turn stops at a replacement, the
     * Annihilape (p2a) has moved and lost the Scarf to a Knock Off, and the lock is still there, with the Scarf gone;
     * that state is valid at the replacement boundary; at a turn boundary it is refused (the g16_scarf_helmet block above:
     * DFI_INV_VOLATILE), only a boundary in the middle of a turn may show it. After step 2 (three entries) the turn
     * has ended: onDisableMove ended the lock. */
    b = replay_to(t, ctx, "g16_scarf_lock_stays", 2u);
    if (b != NULL) {
        dfi_active_slot *pos = &b->sides[1].positions[0];
        const uint32_t m = pos->occupant;
        DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_REPLACEMENT);
        DF_CHECK_EQ_U64(t, b->tail.sides[1].item_now[m], DUOFORGE_ITEM_NOW_NONE);
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u && pos->locked_move == 1u); /* Close Combat */
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        duoforge_battle_destroy(b);
    }
    b = replay_to(t, ctx, "g16_scarf_lock_stays", 3u);
    if (b != NULL) {
        const dfi_active_slot *pos = &b->sides[1].positions[0];
        DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
        DF_CHECK(t, ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) == 0u && pos->locked_move == 0u);
        DF_CHECK(t, check_of(ctx, b) == DFI_INV_NONE);
        duoforge_battle_destroy(b);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g16");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kd = df_make_context(&df_config_pool_dev);

    /* The new public value, as a number (the owner's OK: DUOFORGE_CAUSE_ITEM_TAKEN = 17), and the ids that the step uses. */
    DF_CHECK_EQ_U64(&t, DUOFORGE_CAUSE_ITEM_TAKEN, 17u);
    DF_CHECK_EQ_U64(&t, DUOFORGE_ITEM_NOW_NONE, DFI_TAIL_ITEM_NONE);
    DF_CHECK_EQ_U64(&t, DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE, 11u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_KNOCK_OFF, 24u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_EXPANDING_FORCE, 25u); /* step G15 */
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_GLAIVE_RUSH, 26u); /* step G19 */
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_UNMODELED, DFI_SPECIAL_TERRAIN_PULSE + 1u); /* after Aurora Veil (G20), Spiky Shield, the four of step G28, the three of step G30, the eight of step G32, the three of step G34 and the four of step G25 */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_KNOCKOFF] != 0u && dfi_support.abilities[DFI_ABILITY_STICKYHOLD] != 0u);
    DF_CHECK(&t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE)) != 0u);
    /* Trick, Switcheroo and Thief stay unmarked: no accepted battle has a swapped item (item_now is 0 or 255 only). */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_TRICK] == 0u && dfi_support.moves[DFI_MOVE_SWITCHEROO] == 0u &&
                     dfi_support.moves[DFI_MOVE_THIEF] == 0u);

    uint32_t compared = 0u;
    check_battles(&t, kp, &compared);
    DF_CHECK_EQ_U64(&t, compared, 2u * (uint32_t)(sizeof rows / sizeof rows[0]));
    check_invariants(&t, kp);

    /* The same battles under POOL_DEV (its own fingerprint, the same tables): the same tail and view. */
    uint32_t compared_dev = 0u;
    check_battles(&t, kd, &compared_dev);
    DF_CHECK_EQ_U64(&t, compared_dev, compared);

    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
