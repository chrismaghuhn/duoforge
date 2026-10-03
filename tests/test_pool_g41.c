/*
 * duoforge.state.pool_g41 (white-box): step G41 of the content expansion, Shadow Tag.
 *
 * Shadow Tag (data/abilities.ts:4156-4173) traps every adjacent foe that is not a holder itself and not a Ghost type: at the TURN
 * boundary the foe's request refuses every switch (src/combat/turn.c dfi_switch_trapped, read by src/state/request.c). It shows no
 * line and keeps no state, so the recorded battles cannot show it: this test builds the board from a recorded POOL battle
 * (the team step played, the leads in) and sets the abilities and types in the state, then asks the real request builder for the
 * complete joint domain of each player and looks for a switch in it.
 *
 *   - nobody has Shadow Tag: both players are offered switches (the base of every case below);
 *   - a Shadow Tag holder in one slot of side 1: both Pokemon of side 0 take no switch, and side 1, which has none to fear, does;
 *   - a holder is not trapped by the other side's holder: with a holder on each side, nobody is trapped;
 *   - a Ghost type is not trapped, but Soak's Water makes it trappable again; a Pokemon of the same side does not trap;
 *   - a holder at 0 HP traps nobody; the ability that counts is the current one (the tail's ability_now, a Trace copy);
 *   - the boundary of a replacement is free (the same state at a REPLACEMENT boundary offers a switch to the slot that needs one);
 *   - Shed Shell and Run Away, which would free the holder, are not marked (so the trap rule never meets them).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

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

static void team_bundle(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        r->pick_count = 4u;
        for (uint32_t i = 0; i < 4u; ++i) {
            r->picks[i] = st->picks[s][i];
        }
    }
}

/* Whether any candidate of `player`'s joint domain has a switch in a slot, and how many candidates there are. */
static bool offers_switch(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                          uint32_t slot, uint32_t *count)
{
    static duoforge_side_choice buf[4096];
    uint32_t n = 0u;
    DF_CHECK(t, duoforge_battle_candidates(ctx, b, player, buf, 4096u, &n) == DUOFORGE_OK);
    *count = n;
    for (uint32_t i = 0u; i < n && i < 4096u; ++i) {
        if (buf[i].slots[slot].kind == DUOFORGE_SLOT_SWITCH) {
            return true;
        }
    }
    return false;
}

static uint32_t occupant_of(const duoforge_battle *b, uint32_t side, uint32_t slot)
{
    return b->sides[side].positions[slot].occupant;
}

static void give_tag(duoforge_battle *b, uint32_t side, uint32_t slot)
{
    b->sides[side].members[occupant_of(b, side, slot)].ability = (uint8_t)(1u + DFI_ABILITY_SHADOWTAG);
}

static void check_domain(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool);
    const df_conf_battle *cb = &conf_battles[0];
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b0 = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b0) == DUOFORGE_OK && b0 != NULL)) {
        return;
    }
    duoforge_decision_bundle bd;
    team_bundle(&cb->steps[0], b0, &bd);
    uint32_t used = 0u;
    duoforge_step_result res;
    DF_CHECK(t, dfi_battle_step_tape(ctx, b0, &bd, &conf_tape[cb->steps[0].tape_off], cb->steps[0].tape_len, &used, &res) ==
                    DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, b0->boundary_kind, DUOFORGE_BOUNDARY_TURN);
    uint32_t n = 0u;
    /* the base: nobody has Shadow Tag, so everybody may switch */
    for (uint32_t p = 0u; p < 2u; ++p) {
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            DF_CHECK(t, offers_switch(t, ctx, b0, p, slot, &n));
            DF_CHECK(t, !dfi_switch_trapped(b0, p * 2u + slot));
        }
    }
    duoforge_battle *b = NULL;
    /* a holder in slot 1 of side 1: side 0 is trapped in both slots, side 1 is free (a holder is exempt) */
    DF_CHECK(t, duoforge_battle_clone(ctx, b0, &b) == DUOFORGE_OK);
    give_tag(b, 1u, 1u);
    for (uint32_t slot = 0u; slot < 2u; ++slot) {
        DF_CHECK(t, dfi_switch_trapped(b, slot));
        DF_CHECK(t, !offers_switch(t, ctx, b, 0u, slot, &n));
        DF_CHECK(t, n != 0u); /* the moves are still offered */
        DF_CHECK(t, !dfi_switch_trapped(b, 2u + slot));
        DF_CHECK(t, offers_switch(t, ctx, b, 1u, slot, &n));
    }
    /* a holder at 0 HP traps nobody (the foe's handler does not run for a Pokemon that is down) */
    b->sides[1].members[occupant_of(b, 1u, 1u)].hp = 0u;
    DF_CHECK(t, !dfi_switch_trapped(b, 0u));
    b->sides[1].members[occupant_of(b, 1u, 1u)].hp = 1u;
    DF_CHECK(t, dfi_switch_trapped(b, 0u));
    /* a holder on each side: neither is trapped, and neither holder traps the other's partner... both sides' non-holders are
     * trapped by the other side's holder */
    give_tag(b, 0u, 0u);
    DF_CHECK(t, !dfi_switch_trapped(b, 0u));  /* the holder is exempt */
    DF_CHECK(t, dfi_switch_trapped(b, 1u));   /* its partner is trapped by side 1's holder */
    DF_CHECK(t, dfi_switch_trapped(b, 2u));   /* side 1's slot 0 is trapped by side 0's holder */
    DF_CHECK(t, !dfi_switch_trapped(b, 3u));  /* the holder is exempt */
    /* a Ghost type is not trapped: slot 0 of side 0 becomes a Ghost forme, slot 1 stays */
    duoforge_battle *g = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, b0, &g) == DUOFORGE_OK);
    give_tag(g, 1u, 0u);
    uint32_t ghost = DFI_POOL_FORME_COUNT;
    for (uint32_t f = 0u; f < DFI_POOL_FORME_COUNT && ghost == DFI_POOL_FORME_COUNT; ++f) {
        if (dfi_pool_formes[f].is_mega == 0u &&
            (dfi_pool_formes[f].types[0] == DFI_TYPE_GHOST || dfi_pool_formes[f].types[1] == DFI_TYPE_GHOST)) {
            ghost = f;
        }
    }
    if (DF_CHECK(t, ghost != DFI_POOL_FORME_COUNT)) {
        const uint32_t occ = occupant_of(g, 0u, 0u);
        g->sides[0].members[occ].species_id = (uint16_t)ghost;
        DF_CHECK(t, !dfi_switch_trapped(g, 0u));
        DF_CHECK(t, offers_switch(t, ctx, g, 0u, 0u, &n));
        DF_CHECK(t, dfi_switch_trapped(g, 1u));
        DF_CHECK(t, !offers_switch(t, ctx, g, 0u, 1u, &n));
        /* Soak makes it a single Water type: trapped again */
        g->tail.sides[0].soak_type[occ] = (uint8_t)(DFI_TYPE_WATER + 1u);
        DF_CHECK(t, dfi_switch_trapped(g, 0u));
        DF_CHECK(t, !offers_switch(t, ctx, g, 0u, 0u, &n));
    }
    /* the current ability: a Trace copy of Shadow Tag (ability_now) makes a holder of a member whose own ability is another */
    duoforge_battle *c = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, b0, &c) == DUOFORGE_OK);
    c->tail.sides[1].ability_now[occupant_of(c, 1u, 0u)] = (uint16_t)(1u + DFI_ABILITY_SHADOWTAG);
    DF_CHECK(t, dfi_switch_trapped(c, 0u));
    DF_CHECK(t, dfi_switch_trapped(c, 1u));
    /* a pivot (and a replacement) is free: the same trapped board at a PIVOT boundary of slot 0 takes the switch */
    DF_CHECK(t, !offers_switch(t, ctx, c, 0u, 0u, &n));
    c->boundary_kind = (uint8_t)DUOFORGE_BOUNDARY_PIVOT;
    c->sides[0].requested_slots = 1u;
    c->sides[1].requested_slots = 0u;
    DF_CHECK(t, offers_switch(t, ctx, c, 0u, 0u, &n));
    duoforge_battle_destroy(c);
    duoforge_battle_destroy(g);
    duoforge_battle_destroy(b);
    duoforge_battle_destroy(b0);
    duoforge_context_destroy(ctx);
}

static void check_marks(df_test *t)
{
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_SHADOWTAG] != 0u);
    DF_CHECK_EQ_U64(t, dfi_pool_ability_handler[DFI_ABILITY_SHADOWTAG], DFI_HANDLER_NONE);
    /* what would free the holder is not marked: marking either needs the trap rule to read it (the Champions runaway and
     * the item's onTrapPokemon at priority -10) */
    DF_CHECK(t, dfi_support.abilities[DFI_ABILITY_RUNAWAY] == 0u);
    DF_CHECK(t, dfi_support.items[DFI_ITEM_SHEDSHELL] == 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g41");
    check_marks(&t);
    check_domain(&t);
    return df_test_end(&t);
}
