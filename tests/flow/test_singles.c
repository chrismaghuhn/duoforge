/*
 * Singles (decision 0083): DUOFORGE_DATA_KIND_POOL_SINGLES_DEV over the pool tables, with one position per side.
 *
 *   - the context: brought_count must equal max_roster; duoforge_context_active_per_side says 1 for it, 2 for the
 *     doubles kinds; the kind after it is none;
 *   - team selection: the factored domain picks one of the members (the lead), the candidates are the leads in roster
 *     order, a choice of four picks is refused, and the bench follows in roster order;
 *   - after it: slot 0 of each side holds the lead, slot 1 is empty and never requested; the request asks slot 0 only;
 *     a normal move targets the foe's slot 0 alone; a command in slot 1 is refused;
 *   - the public view: one foe lead (foe_leads[1] is none), the foe's bench order hidden; a world's pick order is the lead,
 *     then the rest ascending, and any other order is refused;
 *   - the invariant: a state with slot 1 occupied under the singles kind is SINGLES_SLOT, the same bytes under POOL_DEV
 *     are not (the doubles kind may occupy it);
 *   - the Endless Battle Clause: a turn that would start turn 101 is refused (E_UNSUPPORTED), the battle unchanged.
 * The battles against the pinned Showdown are tools/reference/singles (duoforge.reference.singles_conformance).
 */
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "state/battle_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/pool.h"

static void check_context(df_test *t)
{
    duoforge_context *ctx = NULL;
    uint32_t active = 0u;
    DF_CHECK(t, duoforge_context_create(&df_config_pool_singles, &ctx) == DUOFORGE_OK && ctx != NULL);
    DF_CHECK(t, duoforge_context_active_per_side(ctx, &active) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, active, 1u);
    DF_CHECK(t, duoforge_context_active_per_side(NULL, &active) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_context_active_per_side(ctx, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    duoforge_context_destroy(ctx);

    /* Every other kind occupies both positions. */
    ctx = NULL;
    DF_CHECK(t, duoforge_context_create(&df_config_pool_dev, &ctx) == DUOFORGE_OK);
    active = 0u;
    DF_CHECK(t, duoforge_context_active_per_side(ctx, &active) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, active, 2u);
    duoforge_context_destroy(ctx);

    /* Singles brings every registered member: brought_count = max_roster, any roster up to six. */
    duoforge_context_config c = df_config_pool_singles;
    c.brought_count = 4u;
    ctx = NULL;
    DF_CHECK(t, duoforge_context_create(&c, &ctx) == DUOFORGE_E_INVALID_ARGUMENT && ctx == NULL);
    c.max_roster = 3u;
    c.brought_count = 3u;
    DF_CHECK(t, duoforge_context_create(&c, &ctx) == DUOFORGE_OK && ctx != NULL);
    duoforge_context_destroy(ctx);
    c = df_config_pool_singles;
    c.data_kind = DUOFORGE_DATA_KIND_POOL_SINGLES_DEV + 1u;
    ctx = NULL;
    DF_CHECK(t, duoforge_context_create(&c, &ctx) == DUOFORGE_E_INVALID_ARGUMENT && ctx == NULL);
}

static duoforge_decision_bundle team_bundle(const duoforge_battle *b, uint32_t lead0, uint32_t lead1)
{
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = b->request_epoch;
    bd.response_mask = 3u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        duoforge_side_choice *r = &bd.responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        r->pick_count = 1u;
        r->picks[0] = (uint8_t)(s == 0u ? lead0 : lead1);
    }
    return bd;
}

static void check_battle(df_test *t)
{
    duoforge_context *ctx = NULL;
    DF_CHECK(t, duoforge_context_create(&df_config_pool_singles, &ctx) == DUOFORGE_OK);
    duoforge_battle_setup setup;
    DF_CHECK(t, duoforge_reference_setup(0u, &setup) == DUOFORGE_OK); /* Team A against Team B */
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        duoforge_context_destroy(ctx);
        return;
    }

    /* TEAM_SELECTION: one pick of six, the six leads in roster order. */
    duoforge_factored_domain d;
    DF_CHECK(t, duoforge_battle_factored(ctx, b, 0u, &d) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, d.kind, DUOFORGE_CHOICE_TEAM_SELECTION);
    DF_CHECK_EQ_U64(t, d.member_count, 6u);
    DF_CHECK_EQ_U64(t, d.pick_count, 1u);
    static duoforge_side_choice cand[DUOFORGE_MAX_CANDIDATES];
    uint32_t n = 0u;
    DF_CHECK(t, duoforge_battle_candidates(ctx, b, 0u, cand, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, n, 6u);
    for (uint32_t i = 0u; i < n && i < 6u; ++i) {
        DF_CHECK(t, cand[i].pick_count == 1u && cand[i].picks[0] == i && cand[i].picks[1] == 0u);
    }

    /* Four picks, as a doubles team choice: not in the domain, the battle unchanged. */
    duoforge_decision_bundle four = team_bundle(b, 0u, 0u);
    for (uint32_t s = 0u; s < 2u; ++s) {
        four.responses[s].pick_count = 4u;
        four.responses[s].picks[1] = 1u;
        four.responses[s].picks[2] = 2u;
        four.responses[s].picks[3] = 3u;
    }
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &four, &res) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TEAM_SELECTION);

    /* Lead 2 for side 0, lead 0 for side 1: the bench follows in roster order. */
    duoforge_decision_bundle bd = team_bundle(b, 2u, 0u);
    if (!DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK)) {
        duoforge_battle_destroy(b);
        duoforge_context_destroy(ctx);
        return;
    }
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    const uint8_t order0[6] = {2u, 0u, 1u, 3u, 4u, 5u};
    for (uint32_t i = 0u; i < 6u; ++i) {
        DF_CHECK_EQ_U64(t, b->sides[0].brought_order[i], order0[i]);
        DF_CHECK_EQ_U64(t, b->sides[1].brought_order[i], i);
    }
    DF_CHECK_EQ_U64(t, b->sides[0].brought_mask, 0x3Fu);
    for (uint32_t s = 0u; s < 2u; ++s) {
        DF_CHECK_EQ_U64(t, b->sides[s].positions[0].occupant, s == 0u ? 2u : 0u);
        DF_CHECK_EQ_U64(t, b->sides[s].positions[1].occupant, DFI_OCCUPANT_NONE);
        DF_CHECK_EQ_U64(t, b->sides[s].requested_slots, 1u);
        duoforge_request rq;
        DF_CHECK(t, duoforge_battle_request(ctx, b, s, &rq) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, rq.slot_mask, 1u);
    }

    /* The public view: one foe lead, the bench order hidden; a world takes the bench in roster order and refuses another. */
    {
        duoforge_public_state view;
        duoforge_hypothesis h;
        DF_CHECK(t, duoforge_battle_public(ctx, b, 0u, &view) == DUOFORGE_OK);
        DF_CHECK(t, duoforge_battle_hypothesis(ctx, b, 0u, &h) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, view.foe_leads[0], 0u);
        DF_CHECK_EQ_U64(t, view.foe_leads[1], DUOFORGE_VIEW_PICK_NONE);
        for (uint32_t i = 0u; i < 6u; ++i) {
            DF_CHECK_EQ_U64(t, h.pick_order[i], i);
        }
        duoforge_battle *world = NULL;
        DF_CHECK(t, duoforge_battle_create(ctx, &setup, &world) == DUOFORGE_OK);
        if (world != NULL) {
            DF_CHECK(t, duoforge_battle_from_view(ctx, &view, &h, world) == DUOFORGE_OK);
            DF_CHECK_EQ_U64(t, world->sides[1].positions[0].occupant, 0u);
            duoforge_hypothesis swapped = h;
            swapped.pick_order[2] = h.pick_order[3];
            swapped.pick_order[3] = h.pick_order[2];
            DF_CHECK(t, duoforge_battle_from_view(ctx, &view, &swapped, world) == DUOFORGE_E_INVALID_ARGUMENT);
            duoforge_battle_destroy(world);
        }
    }

    /* The turn: slot 1 is one NONE command (an unrequested slot), slot 0 the moves and the five switches; a normal move
     * targets the foe's slot 0 (flat 2 for side 0) and nothing else. */
    DF_CHECK(t, duoforge_battle_factored(ctx, b, 0u, &d) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, d.kind, DUOFORGE_CHOICE_SLOTS);
    DF_CHECK_EQ_U64(t, d.slot_count[1], 1u);
    DF_CHECK_EQ_U64(t, d.slots[1][0].kind, DUOFORGE_SLOT_NONE);
    uint32_t moves = 0u;
    uint32_t switches = 0u;
    for (uint32_t i = 0u; i < d.slot_count[0]; ++i) {
        const duoforge_slot_command *c = &d.slots[0][i];
        if (c->kind == DUOFORGE_SLOT_MOVE) {
            moves += 1u;
            DF_CHECK(t, c->target == 2u || c->target == 0u || c->target == DUOFORGE_TARGET_NONE);
        } else if (c->kind == DUOFORGE_SLOT_SWITCH) {
            switches += 1u;
        }
    }
    DF_CHECK_EQ_U64(t, switches, 5u);
    DF_CHECK(t, moves >= 1u && moves + switches == d.slot_count[0]);
    n = 0u;
    DF_CHECK(t, duoforge_battle_candidates(ctx, b, 0u, cand, DUOFORGE_MAX_CANDIDATES, &n) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, n, d.slot_count[0]);

    /* A command in slot 1 is not in the domain. */
    duoforge_decision_bundle bad;
    memset(&bad, 0, sizeof bad);
    bad.epoch = b->request_epoch;
    bad.response_mask = 3u;
    for (uint32_t s = 0u; s < 2u; ++s) {
        duoforge_side_choice *r = &bad.responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        r->slots[0] = d.slots[0][0];
        r->slots[1] = d.slots[0][0];
    }
    bad.responses[1].slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 1u, {0u, 0u, 0u}};
    bad.responses[1].slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_NONE, 0u, 0u, 0u, 0u, {0u, 0u, 0u}};
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bad, &res) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK_EQ_U64(t, b->boundary_kind, DUOFORGE_BOUNDARY_TURN);

    /* The invariant: slot 1 occupied is SINGLES_SLOT under the singles kind. */
    struct duoforge_battle w = *b;
    w.sides[0].positions[1] = w.sides[0].positions[0];
    w.sides[0].positions[1].occupant = 1u;
    w.sides[0].positions[1].activation_id = w.next_activation_id;
    w.next_activation_id += 1u;
    dfi_invariant first = DFI_INV_NONE;
    DF_CHECK(t, dfi_state_check(ctx, &w, &first) == DUOFORGE_E_INVARIANT);
    DF_CHECK_EQ_U64(t, first, DFI_INV_SINGLES_SLOT);
    DF_CHECK(t, strcmp(dfi_invariant_name(DFI_INV_SINGLES_SLOT), "SINGLES_SLOT") == 0);
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);

    /* The Endless Battle Clause (decision 0083 section 6): a turn that would start turn 101 is refused, the battle
     * unchanged; the turn before it starts turn 100. Both sides switch, so no Pokemon faints. */
    {
        duoforge_decision_bundle sw;
        memset(&sw, 0, sizeof sw);
        sw.epoch = b->request_epoch;
        sw.response_mask = 3u;
        for (uint32_t s = 0u; s < 2u; ++s) {
            duoforge_factored_domain ds;
            DF_CHECK(t, duoforge_battle_factored(ctx, b, s, &ds) == DUOFORGE_OK);
            duoforge_side_choice *r = &sw.responses[s];
            r->epoch = b->request_epoch;
            r->side = (uint8_t)s;
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t i = 0u; i < ds.slot_count[0]; ++i) {
                if (ds.slots[0][i].kind == DUOFORGE_SLOT_SWITCH) {
                    r->slots[0] = ds.slots[0][i];
                    break;
                }
            }
            r->slots[1] = ds.slots[1][0];
            DF_CHECK_EQ_U64(t, r->slots[0].kind, DUOFORGE_SLOT_SWITCH);
        }
        struct duoforge_battle late = *b;
        late.turn = 99u;
        DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, late.turn, 100u);
        late = *b;
        late.turn = 100u;
        const struct duoforge_battle before = late;
        DF_CHECK(t, duoforge_battle_step(ctx, &late, &sw, &res) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, memcmp(&late, &before, sizeof late) == 0);
    }

    duoforge_battle_destroy(b);
    duoforge_context_destroy(ctx);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.singles");
    check_context(&t);
    check_battle(&t);
    return df_test_end(&t);
}
