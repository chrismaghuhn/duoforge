/*
 * duoforge.state.pool_g85 (white-box): step G85 of the content expansion, Pickpocket and Magician (decision 0015 entry 5bu).
 *
 * Pickpocket (data/abilities.ts:3239-3261, onAfterMoveSecondary) and Magician (data/abilities.ts:2477-2499,
 * onAfterMoveSecondarySelf) take an item from the other Pokemon into their own hand (src/combat/turn.c dfi_pickpocket and
 * dfi_magician). The recorded battles of the step (tests/reference/specs/g85_*, replayed by conformance_pool_data) show the
 * lines; this file checks the state that the battles leave (item_now: 0 as the sheet says, DFI_TAIL_ITEM_NONE for nothing,
 * else item + 1) and the refusals, which no recorded battle can show (the reference draws on a tie, the engine refuses).
 *
 * State after the recorded turns:
 *   - g85_pickpocket_kowtow: the contact Kowtow Cleave takes the attacker's Black Glasses into Weavile (no item).
 *   - g85_pickpocket_balloon: the receiver takes an Air Balloon; its own line (ITEM_SHOWN) comes first.
 *   - g85_pickpocket_sheerforce: a Sheer Force attacker still loses its Muscle Band (Pickpocket is not gated).
 *   - g85_pickpocket_stickyhold: Sticky Hold on the attacker keeps its Leftovers; the holder keeps nothing.
 *   - g85_magician_mystical: Delphox takes the Black Glasses of Kingambit; the target has no line of its own.
 *   - g85_magician_substitute: the target's Substitute took the hit, and Delphox still takes the target's Leftovers.
 *   - g85_magician_stickyhold: Sticky Hold on the target keeps its item.
 *   - g85_trick_balloon: the Trick gives the target an Air Balloon (its own line first, the regression of G67).
 *
 * Refusals (E_UNSUPPORTED, decided before anything changes), each with its control accepted:
 *   - two AfterMoveSecondary holders of priority 0 in one move (a Pickpocket holder and a Red Card holder);
 *   - an exact speed tie between the hitTargets of Magician (two copies of one Pokemon, the same Speed);
 *   - a Mega Stone of the receiver's own species (Delphox takes Delphoxite).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "combat/turn.h"
#include "data/closure_tables.h"
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
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed: 2 bits */
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

/* The steps [from, to) of the recorded battle `cb` on `b`, each one as recorded (the tape consumed exactly). */
static bool advance(df_test *t, const duoforge_context *ctx, const df_conf_battle *cb, duoforge_battle *b, uint32_t from, uint32_t to)
{
    for (uint32_t si = from; si < to; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", cb->name, si, duoforge_status_name(status));
            return false;
        }
    }
    return true;
}

/* The recorded battle `name` replayed for its first `steps` steps (step 0 is the team step). */
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
    if (!advance(t, ctx, cb, b, 0u, steps)) {
        duoforge_battle_destroy(b);
        return NULL;
    }
    return b;
}


/* item_now of the member `m` of `side` after the recorded battle `name` has played `turns` turns (step 0 is the team). */
static void check_item_after(df_test *t, const duoforge_context *ctx, const char *name, uint32_t turns, uint32_t side, uint32_t m,
                             uint32_t expect)
{
    duoforge_battle *b = replay(t, ctx, name, turns + 1u);
    if (b == NULL) {
        return;
    }
    DF_CHECK_EQ_U64(t, b->tail.sides[side].item_now[m], expect);
    duoforge_battle_destroy(b);
}

/* item_now: 1 + the item's id for a held item, DFI_TAIL_ITEM_NONE for an item that is gone, 0 for the sheet's item. */
#define G85_HELD(item) ((uint32_t)(item) + 1u)
#define G85_NONE DFI_TAIL_ITEM_NONE
#define G85_SHEET 0u

static void check_states(df_test *t, const duoforge_context *ctx)
{
    /* Pickpocket: the attacker's Black Glasses goes to the holder with none (side 0 is the attacker, side 1 the holder). */
    check_item_after(t, ctx, "g85_pickpocket_kowtow", 1u, 0u, 0u, G85_NONE);
    check_item_after(t, ctx, "g85_pickpocket_kowtow", 1u, 1u, 0u, G85_HELD(DFI_ITEM_BLACKGLASSES));
    /* the receiver of an Air Balloon */
    check_item_after(t, ctx, "g85_pickpocket_balloon", 1u, 0u, 0u, G85_NONE);
    check_item_after(t, ctx, "g85_pickpocket_balloon", 1u, 1u, 0u, G85_HELD(DFI_ITEM_AIRBALLOON));
    /* Sheer Force attacker: Pickpocket is not gated, the Muscle Band goes */
    check_item_after(t, ctx, "g85_pickpocket_sheerforce", 1u, 0u, 0u, G85_NONE);
    check_item_after(t, ctx, "g85_pickpocket_sheerforce", 1u, 1u, 0u, G85_HELD(DFI_ITEM_MUSCLEBAND));
    /* Sticky Hold on the attacker: nothing moves */
    check_item_after(t, ctx, "g85_pickpocket_stickyhold", 1u, 0u, 0u, G85_SHEET);
    check_item_after(t, ctx, "g85_pickpocket_stickyhold", 1u, 1u, 0u, G85_SHEET);
    /* Magician: the target loses its item with no line of its own; the user holds it (side 0 the user, side 1 the target) */
    check_item_after(t, ctx, "g85_magician_mystical", 1u, 0u, 0u, G85_HELD(DFI_ITEM_BLACKGLASSES));
    check_item_after(t, ctx, "g85_magician_mystical", 1u, 1u, 0u, G85_NONE);
    /* Magician on a Substitute's target: the target still loses its Leftovers after the Substitute took the hit (two turns) */
    check_item_after(t, ctx, "g85_magician_substitute", 2u, 0u, 0u, G85_HELD(DFI_ITEM_LEFTOVERS));
    check_item_after(t, ctx, "g85_magician_substitute", 2u, 1u, 0u, G85_NONE);
    /* Sticky Hold on the target: nothing moves */
    check_item_after(t, ctx, "g85_magician_stickyhold", 1u, 0u, 0u, G85_SHEET);
    check_item_after(t, ctx, "g85_magician_stickyhold", 1u, 1u, 0u, G85_SHEET);
    /* Trick: the target gets the user's Air Balloon, the user the target's Black Glasses (the regression of G67) */
    check_item_after(t, ctx, "g85_trick_balloon", 1u, 0u, 0u, G85_HELD(DFI_ITEM_BLACKGLASSES));
    check_item_after(t, ctx, "g85_trick_balloon", 1u, 1u, 0u, G85_HELD(DFI_ITEM_AIRBALLOON));
}

/* One turn of a battle built from the recorded battle `cb`: its team step as recorded, then the turn `cmd` (side s, slot k).
 * The setup is the caller's, changed from the recorded members. Returns the status of the turn. */
static duoforge_status one_turn(df_test *t, duoforge_context *ctx, duoforge_battle_setup *setup, const df_conf_battle *cb,
                                const duoforge_slot_command cmd[2][2])
{
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, setup, &b) == DUOFORGE_OK && b != NULL)) {
        return DUOFORGE_E_INVARIANT;
    }
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    bundle_of(&cb->steps[0], b, &bd); /* the team selection, as recorded */
    DF_CHECK_EQ_U64(t, duoforge_battle_step(ctx, b, &bd, &res), DUOFORGE_OK);
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    for (uint32_t s = 0; s < 2u; ++s) {
        duoforge_side_choice *r = &bd.responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        r->slots[0] = cmd[s][0];
        r->slots[1] = cmd[s][1];
    }
    const duoforge_status st = duoforge_battle_step(ctx, b, &bd, &res);
    duoforge_battle_destroy(b);
    return st;
}

static const duoforge_slot_command k_move0_none = {DUOFORGE_SLOT_MOVE, 0u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
static const duoforge_slot_command k_move1_none = {DUOFORGE_SLOT_MOVE, 1u, DUOFORGE_TARGET_NONE, 0u, 0u, {0u, 0u, 0u}};
static const duoforge_slot_command k_move0_foe0 = {DUOFORGE_SLOT_MOVE, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};

/* The member's moves: `n` ids, and every slot after them empty (a member's unused slots must be zero). */
static void set_moves(duoforge_member_setup *m, uint32_t n, const uint32_t *ids)
{
    m->move_count = n;
    for (uint32_t k = 0; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        m->moves[k].move_id = k < n ? ids[k] : 0u;
        m->moves[k].pp_max = 0u;
    }
}

/* Pickpocket with a second priority-0 holder in the move: the spread Hyper Voice of Salamence (side 0, slot 0, swapped with
 * Kingambit so the Species Clause holds) hits Weavile (Pickpocket, no item) and Primarina. Primarina's item is a Red Card in
 * the refusal; the control keeps the Rocky Helmet. */
static void check_pickpocket_refusal(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g85_pickpocket_kowtow");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    for (int red = 0; red < 2; ++red) {
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_member_setup tmp = setup.sides[0].members[0];
        setup.sides[0].members[0] = setup.sides[0].members[5]; /* Salamence (the row of member 5) to the front */
        setup.sides[0].members[5] = tmp;
        duoforge_member_setup *hv = &setup.sides[0].members[0];
        hv->item = 0u;
        const uint32_t hv_moves[2] = {DFI_MOVE_HYPERVOICE, DFI_MOVE_PROTECT};
        set_moves(hv, 2u, hv_moves);
        if (red) {
            setup.sides[1].members[1].item = (uint8_t)(1u + DFI_ITEM_REDCARD);
        }
        const duoforge_slot_command cmd[2][2] = {{k_move0_none, k_move1_none}, {k_move0_foe0, k_move0_foe0}};
        const duoforge_status st = one_turn(t, ctx, &setup, cb, cmd);
        DF_CHECK_EQ_U64(t, (uint64_t)st, (uint64_t)(red ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK));
    }
}

/* Magician with two targets of one Speed: Delphox (no item, Magician) uses the spread Dazzling Gleam on two foes of Speed 105
 * each (Ceruledge, Serious, no Speed points; Gholdengo, Calm, 8 Speed points: base Speed 85 and 84, both 105 at level 50), so the
 * speedSort of hitTargets draws and the engine refuses. The control keeps the sheet's Weavile and Primarina, of other Speeds. */
static void check_magician_tie(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g85_pickpocket_kowtow");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    for (int tie = 0; tie < 2; ++tie) {
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_member_setup *dl = &setup.sides[0].members[0];
        dl->species_id = DFI_FORME_DELPHOX;
        dl->gender = DUOFORGE_GENDER_FEMALE;
        dl->ability = (uint8_t)(1u + DFI_ABILITY_MAGICIAN);
        dl->item = 0u;
        const uint32_t dl_moves[2] = {DFI_MOVE_DAZZLINGGLEAM, DFI_MOVE_PROTECT};
        set_moves(dl, 2u, dl_moves);
        if (tie) {
            duoforge_member_setup ceruledge = setup.sides[0].members[4];
            ceruledge.nature = DFI_NATURE_SERIOUS;
            ceruledge.stat_points[5] = 0u;
            ceruledge.item = 0u;
            const uint32_t c_moves[1] = {DFI_MOVE_BITTERBLADE};
            set_moves(&ceruledge, 1u, c_moves);
            duoforge_member_setup gholdengo = setup.sides[0].members[3];
            gholdengo.nature = DFI_NATURE_CALM;
            gholdengo.stat_points[5] = 8u;
            gholdengo.item = 0u;
            const uint32_t g_moves[1] = {DFI_MOVE_SHADOWBALL};
            set_moves(&gholdengo, 1u, g_moves);
            /* side 1 keeps its Species Clause: its Ceruledge (member 4) moves to slot 1 and its Primarina (member 1) to member 4 */
            const duoforge_member_setup primarina = setup.sides[1].members[1];
            setup.sides[1].members[0] = gholdengo;
            setup.sides[1].members[1] = ceruledge;
            setup.sides[1].members[4] = primarina;
        }
        const duoforge_slot_command cmd[2][2] = {{k_move0_none, k_move1_none}, {k_move0_foe0, k_move0_foe0}};
        const duoforge_status st = one_turn(t, ctx, &setup, cb, cmd);
        DF_CHECK_EQ_U64(t, (uint64_t)st, (uint64_t)(tie ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK));
    }
}

/* Magician taking a Mega Stone of the user's own species (Delphoxite from Weavile): refused. The control holds Black Glasses. */
static void check_magician_stone(df_test *t, duoforge_context *ctx)
{
    const df_conf_battle *cb = find("g85_pickpocket_kowtow");
    if (!DF_CHECK(t, cb != NULL)) {
        return;
    }
    for (int stone = 0; stone < 2; ++stone) {
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_member_setup *dl = &setup.sides[0].members[0];
        dl->species_id = DFI_FORME_DELPHOX;
        dl->gender = DUOFORGE_GENDER_FEMALE;
        dl->ability = (uint8_t)(1u + DFI_ABILITY_MAGICIAN);
        dl->item = 0u;
        const uint32_t dl_fire[1] = {DFI_MOVE_MYSTICALFIRE};
        set_moves(dl, 1u, dl_fire);
        setup.sides[1].members[0].item = (uint8_t)(stone ? 1u + DFI_ITEM_DELPHOXITE : 1u + DFI_ITEM_BLACKGLASSES);
        const duoforge_slot_command cmd[2][2] = {{{DUOFORGE_SLOT_MOVE, 0u, 2u, 0u, 0u, {0u, 0u, 0u}}, k_move1_none},
                                                 {k_move0_foe0, k_move0_foe0}};
        const duoforge_status st = one_turn(t, ctx, &setup, cb, cmd);
        DF_CHECK_EQ_U64(t, (uint64_t)st, (uint64_t)(stone ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK));
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g85");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    if (DF_CHECK(&t, ctx != NULL)) {
        check_states(&t, ctx);
        check_pickpocket_refusal(&t, ctx);
        check_magician_tie(&t, ctx);
        check_magician_stone(&t, ctx);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
