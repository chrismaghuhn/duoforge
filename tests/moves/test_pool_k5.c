/*
 * duoforge.state.pool_k5 (white-box): step K5 of the content expansion, Magic Room (#475, decision 0015 5dm).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the rows: Magic Room is a pool move of the pseudo weather DFI_PSEUDO_WEATHER_MAGIC_ROOM, marked supported; the public names
 *     (event detail 7, feature 47, the three flag bits of the turns); no pool ability is Persistent (the seven-turn form is not built);
 *   - the view: the field flags bits 0-2 hold the turns left (the residual of the start turn included), bits 3-5 stay zero (Wonder
 *     Room, K6), the setter's member code is in magic_room_source (1 + side * 6 + roster index), for both viewers, through the
 *     start, the countdown, the end of the five turns and the restart that ends the room early (setter on the field and benched);
 *   - a Choice-locked holder that would charge or lock with another move under the room is refused (E_UNSUPPORTED), atomically;
 *   - an Illusion holder whose disguise is up that uses Magic Room is refused (E_UNSUPPORTED), by the predicate and by the turn's
 *     dispatch: Showdown keeps the disguise on the benched setter (data/abilities.ts:2075-2079), so its end line would
 *     name the disguise while the digest hashes the member.
 * The engine's replay of the recorded battles (tests/reference/traces/k5_*.json: the events with the setter, the requests with the
 * lock, the item effects that are off) is pinned by duoforge.reference.conformance_pool and the converter; the six later recordings
 * are k5_mr_herb_end (the residual's herb after the room's end), k5_mr_tie (two Leftovers holders tie), k5_mr_tie_herb,
 * k5_mr_tie_seed, k5_mr_tie_switch and k5_mr_tie_update (ties of the other counting sites); the live tracker's fold by python/tests.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "combat/field/magic_room_refusal.h"
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
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

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
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

/* The recorded battle `name` after its first `steps` steps (step 0 is the team step, which places the leads). */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status = dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    return b;
}

static void check_rows(df_test *t)
{
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_MAGIC_ROOM, 7u);
    DF_CHECK_EQ_U64(t, DUOFORGE_VIEWEXT_FEATURE_MAGIC_ROOM, 47u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_FLAG_MAGIC_ROOM_BIT0, 1u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_FLAG_MAGIC_ROOM_BIT1, 2u);
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_FLAG_MAGIC_ROOM_BIT2, 4u);
    DF_CHECK_EQ_U64(t, DFI_PSEUDO_WEATHER_MAGIC_ROOM, 3u);
    DF_CHECK_EQ_U64(t, dfi_pool_moves[DFI_MOVE_MAGICROOM].pseudo_weather, DFI_PSEUDO_WEATHER_MAGIC_ROOM);
    DF_CHECK(t, dfi_support.moves[DFI_MOVE_MAGICROOM] != 0u);
    DF_CHECK(t, (dfi_support.view_ext_features & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_MAGIC_ROOM)) != 0u);
    for (uint32_t a = 0u; a < DFI_POOL_ABILITY_COUNT; ++a) {
        DF_CHECK(t, strcmp(dfi_pool_ability_names[a], "persistent") != 0); /* Magic Room's seven turns are not built */
    }
}

/* The view of the room after `steps` steps of the recorded battle: the turns in bits 0-2 of the flags and the setter's code, the same
 * for both viewers; no other flag bit. */
static void check_view(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps, uint32_t turns, uint32_t code)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
        duoforge_observation_ext ext;
        if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext) == DUOFORGE_OK)) {
            if (!DF_CHECK(t, (uint32_t)ext.field.flags == turns && (uint32_t)ext.field.magic_room_source == code)) {
                fprintf(stderr, "  %s after %u steps, viewer %u: flags %u (want %u), source %u (want %u)\n", name, steps, viewer,
                        (unsigned)ext.field.flags, turns, (unsigned)ext.field.magic_room_source, code);
            }
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    duoforge_battle_destroy(b);
}

static void check_views(df_test *t, const duoforge_context *ctx)
{
    /* the state after k steps (step 0 is the team step... so k = 2 is after turn 1): 4 after the residual of the start turn, down to
     * the end line in the residual of turn 5 (k = 6) */
    static const uint32_t countdown[7] = {0u, 0u, 4u, 3u, 2u, 1u, 0u};
    for (uint32_t k = 0u; k < 7u; ++k) {
        check_view(t, ctx, "k5_mr_end_active", k, countdown[k], countdown[k] != 0u ? 1u : 0u);
        check_view(t, ctx, "k5_mr_end_benched", k, countdown[k], countdown[k] != 0u ? 1u : 0u); /* Alakazam (side 0, roster 0) benched */
    }
    /* the restart ends the room (turn 3), Alakazam sets it again on turn 4 */
    check_view(t, ctx, "k5_mr_restart_active", 3u, 3u, 1u);
    check_view(t, ctx, "k5_mr_restart_active", 4u, 0u, 0u);
    check_view(t, ctx, "k5_mr_restart_active", 5u, 4u, 1u);
    /* Alakazam benched on turn 2; the foe Gardevoir (side 1, roster 0: the code 7) ends the room and starts it on turn 4 */
    check_view(t, ctx, "k5_mr_restart_benched", 2u, 4u, 1u);
    check_view(t, ctx, "k5_mr_restart_benched", 3u, 0u, 0u);
    check_view(t, ctx, "k5_mr_restart_benched", 4u, 0u, 0u);
    check_view(t, ctx, "k5_mr_restart_benched", 5u, 4u, 7u);
}

/* A Choice-locked holder that uses a charge move under the room: the engine keeps one locked_move byte for the lock and for a charge,
 * so it refuses (E_UNSUPPORTED) and the refused step changes nothing. g58_phantom_choice_scarf: Annihilape (Choice Scarf) has Phantom
 * Force in slot 1 and Close Combat in slot 3; the state is the lead after the team step, with the Scarf's lock on Close Combat and
 * the room up, and the recorded turn 1 queues Phantom Force. Without the room the choice is not offered at all (the request names the locked move only): E_INVALID_ARGUMENT. */
static void check_lock_conflict(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g58_phantom_choice_scarf");
    for (uint32_t room = 0u; room < 2u; ++room) {
        duoforge_battle *b = replay(t, ctx, "g58_phantom_choice_scarf", 1u);
        if (!DF_CHECK(t, cb != NULL && b != NULL)) {
            return;
        }
        dfi_active_slot *lead = &b->sides[0].positions[0];
        lead->flags = (uint8_t)((uint32_t)lead->flags | DFI_VOL_CHOICE_LOCK);
        lead->locked_move = 3u;
        if (room != 0u) {
            b->tail.magic_room_turns = 3u;
            b->tail.magic_room_source = 1u; /* side 0, roster 0 */
        }
        duoforge_battle *before = NULL;
        DF_CHECK(t, duoforge_battle_clone(ctx, b, &before) == DUOFORGE_OK && before != NULL);
        duoforge_decision_bundle bd;
        bundle_of(&cb->steps[1], b, &bd);
        duoforge_step_result res;
        const duoforge_status refused = duoforge_battle_step(ctx, b, &bd, &res);
        const duoforge_status want = room != 0u ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_E_INVALID_ARGUMENT;
        if (!DF_CHECK(t, refused == want)) {
            fprintf(stderr, "  room %u: the step returned %s\n", room, duoforge_status_name(refused));
        }
        bool equal = false;
        DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, b, before, &equal) == DUOFORGE_OK && equal);
        duoforge_battle_destroy(before);
        duoforge_battle_destroy(b);
    }
}

/* An Illusion holder with its disguise up that uses Magic Room is refused: the lead of i2_illusion_break (Zoroark, disguised after the team
 * step) is refused as the user, no other position is, and a battle without a disguise (k5_mr_end_active) refuses nobody. No pool species
 * has Illusion and Magic Room together (the member rules refuse a move outside the learnset), so this function checks the predicate
 * the move's dispatch asks (dfi_magic_room_refused, combat/field/magic_room_refusal.h), and check_illusion_step checks the dispatch's
 * E_UNSUPPORTED through a step. */
static void check_illusion_setter(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (DF_CHECK(t, b != NULL)) {
        DF_CHECK(t, dfi_illusion_disguise_up(&b->sides[0], &b->tail.sides[0], 0u) != 0);
        DF_CHECK(t, dfi_magic_room_refused(b, 0u));
        for (uint32_t user = 1u; user < 2u * DUOFORGE_ACTIVE_PER_SIDE; ++user) {
            DF_CHECK(t, !dfi_magic_room_refused(b, user));
        }
        duoforge_battle_destroy(b);
    }
    b = replay(t, ctx, "k5_mr_end_active", 1u);
    if (DF_CHECK(t, b != NULL)) {
        for (uint32_t user = 0u; user < 2u * DUOFORGE_ACTIVE_PER_SIDE; ++user) {
            DF_CHECK(t, !dfi_magic_room_refused(b, user));
        }
        duoforge_battle_destroy(b);
    }
}

/* The dispatch of the move asks that predicate: i2_illusion_break after its team step (Zoroark, disguised, leads side 0), Magic Room in
 * the first move slot of that lead, and the recorded command of turn 1 for slot 0 (the move, with no target). The turn runs on a copy
 * the way request.c runs it (dfi_turn_run), because duoforge_battle_step refuses this state before the dispatch: a Zoroark that
 * knows Magic Room fails the state check (E_INVARIANT). The turn returns E_UNSUPPORTED, and the battle the caller holds is equal to
 * its clone. */
static void check_illusion_step(df_test *t, const duoforge_context *ctx)
{
    const df_conf_battle *cb = find("i2_illusion_break");
    duoforge_battle *b = replay(t, ctx, "i2_illusion_break", 1u);
    if (!DF_CHECK(t, cb != NULL && b != NULL)) {
        return;
    }
    DF_CHECK(t, dfi_illusion_disguise_up(&b->sides[0], &b->tail.sides[0], 0u) != 0);
    b->sides[0].members[b->sides[0].positions[0].occupant].moves[0].move_id = (uint16_t)DFI_MOVE_MAGICROOM;
    duoforge_battle *before = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, b, &before) == DUOFORGE_OK && before != NULL);
    duoforge_decision_bundle bd;
    bundle_of(&cb->steps[1], b, &bd);
    bd.responses[0].slots[0] = (duoforge_slot_command){DFI_SLOT_MOVE, 0u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
    for (uint32_t k = 0u; k < 2u; ++k) { /* the foe passes, so that the recorded Moonblast does not break the disguise first */
        bd.responses[1].slots[k] = (duoforge_slot_command){DFI_SLOT_PASS, 0u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
    }
    struct duoforge_battle tmp = *b;
    dfi_events events;
    memset(&events, 0, sizeof events);
    dfi_draws draws = dfi_draws_from_rng(&tmp.rng);
    draws.tape = NULL;
    draws.tape_len = 0u;
    const duoforge_status refused = dfi_turn_run(ctx, &tmp, bd.responses, &draws, &events);
    if (!DF_CHECK(t, refused == DUOFORGE_E_UNSUPPORTED)) {
        fprintf(stderr, "  the turn returned %s\n", duoforge_status_name(refused));
    }
    bool equal = false;
    DF_CHECK(t, before != NULL && duoforge_battle_equal(ctx, b, before, &equal) == DUOFORGE_OK && equal);
    duoforge_battle_destroy(before);
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_k5");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(&t, ctx != NULL);
    if (ctx != NULL) {
        check_rows(&t);
        check_views(&t, ctx);
        check_lock_conflict(&t, ctx);
        check_illusion_setter(&t, ctx);
        check_illusion_step(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
