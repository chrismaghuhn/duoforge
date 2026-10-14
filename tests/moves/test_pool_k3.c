/*
 * duoforge.state.pool_k3 (white-box): step K3 of the content expansion, Speed Swap (#473, decision 0015 5de).
 *
 * What this test pins, and where the rest of the evidence is:
 *   - the swap exchanges the two stored Speeds (dfi_member.stats[SPE]) and sets the presence bit (single_turn bit
 *     DFI_SINGLE_TURN_SPEED_SWAP) of both positions; the bit persists across the residual of the turn and of later turns;
 *   - the bit and the swapped Speed end with the occupant (a switch-out, a faint is the same rule), and only that occupant's
 *     Speed is rebuilt (the other swapped Pokemon keeps its swapped Speed);
 *   - a Mega Evolution rebuilds the stored stats and ends the swap; a Stance Change (the Blade forme) rebuilds them too;
 *   - a live swap refuses the public record with DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP (128), and a Protect blocks the swap;
 *   - the Blade's invariant (step G66) accepts a swapped Speed on an Aegislash-Blade (duoforge_battle_check is OK).
 * The engine's replay of the recorded battles (tests/reference/traces/k3_*.json) is pinned by duoforge.reference.conformance_pool
 * and the converter; the live tracker's fold is pinned by python/tests/replay.
 *
 * Expected Speeds (derived from the pinned formula, L50, the Speed Stat Points and Natures of the teams):
 *   Alakazam (Timid, 32 Spe)        189;  Milotic (Calm, 0 Spe)     101;  Baxcalibur (Adamant, 2 Spe) 109;  Aegislash (Impish, 0 Spe)  80;
 *   Gholdengo, Kingambit, ... are checked against their own derived value (dfi_closure_member_derive).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "combat/turn.h"
#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

#define K3_ALAKAZAM_SPE 189u
#define K3_MILOTIC_SPE 101u
#define K3_BAXCALIBUR_SPE 109u
#define K3_AEGISLASH_SPE 80u

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

/* The member on flat position `flat` (the occupant's record), and its stored Speed. */
static dfi_member *occupant_of(duoforge_battle *b, uint32_t flat)
{
    const uint32_t side = flat / DUOFORGE_ACTIVE_PER_SIDE;
    const uint32_t occ = b->sides[side].positions[flat % DUOFORGE_ACTIVE_PER_SIDE].occupant;
    return &b->sides[side].members[occ];
}

static uint32_t stored_spe(duoforge_battle *b, uint32_t flat)
{
    return occupant_of(b, flat)->stats[DFI_STAT_SPE - 1u];
}

static uint32_t derived_spe(duoforge_battle *b, uint32_t flat)
{
    dfi_member copy = *occupant_of(b, flat);
    if (!dfi_closure_member_derive(&copy)) {
        return 0xFFFFu;
    }
    return copy.stats[DFI_STAT_SPE - 1u];
}

static bool swapped(const duoforge_battle *b, uint32_t flat)
{
    return (b->tail.sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE].single_turn &
            DFI_SINGLE_TURN_SPEED_SWAP) != 0u;
}

static uint32_t public_mask(df_test *t, const duoforge_context *ctx, duoforge_battle *b, uint32_t player)
{
    uint32_t mask = 0xFFFFFFFFu;
    DF_CHECK(t, duoforge_battle_public_causes(ctx, b, player, &mask) == DUOFORGE_OK);
    return mask;
}

/* Alakazam (flat 0) swaps with Milotic (flat 2) on turn 1; the Speeds are exchanged and both positions carry the bit. */
static void check_swap_and_persistence(df_test *t, const duoforge_context *ctx)
{
    const char *name = "k3_speed_swap_basic";
    duoforge_battle *before = replay(t, ctx, name, 1u);
    if (DF_CHECK(t, before != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(before, 0u), K3_ALAKAZAM_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(before, 2u), K3_MILOTIC_SPE);
        DF_CHECK(t, !swapped(before, 0u) && !swapped(before, 2u));
        DF_CHECK_EQ_U64(t, public_mask(t, ctx, before, 0u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP, 0u);
        duoforge_battle_destroy(before);
    }
    duoforge_battle *after = replay(t, ctx, name, 2u);
    if (DF_CHECK(t, after != NULL)) {
        /* the swap exchanged the stored Speeds: Alakazam now holds Milotic's, Milotic Alakazam's */
        DF_CHECK_EQ_U64(t, stored_spe(after, 0u), K3_MILOTIC_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(after, 2u), K3_ALAKAZAM_SPE);
        DF_CHECK(t, swapped(after, 0u) && swapped(after, 2u));
        DF_CHECK(t, !swapped(after, 1u) && !swapped(after, 3u));
        DF_CHECK(t, (public_mask(t, ctx, after, 0u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
        DF_CHECK(t, (public_mask(t, ctx, after, 1u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
        DF_CHECK(t, duoforge_battle_check(ctx, after) == DUOFORGE_OK);
        duoforge_battle_destroy(after);
    }
    /* the bit persists across the residual of turn 1 and of turns 2 and 3 (never cleared with the turn) */
    for (uint32_t steps = 3u; steps <= 4u; ++steps) {
        duoforge_battle *later = replay(t, ctx, name, steps);
        if (DF_CHECK(t, later != NULL)) {
            DF_CHECK(t, swapped(later, 0u) && swapped(later, 2u));
            DF_CHECK_EQ_U64(t, stored_spe(later, 0u), K3_MILOTIC_SPE);
            duoforge_battle_destroy(later);
        }
    }
}

/* A Protect blocks the swap: nothing is exchanged and no bit is set (Milotic protects on turn 1). */
static void check_protect(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "k3_speed_swap_protect", 2u);
    if (DF_CHECK(t, b != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(b, 0u), K3_ALAKAZAM_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(b, 2u), K3_MILOTIC_SPE);
        DF_CHECK(t, !swapped(b, 0u) && !swapped(b, 2u));
        duoforge_battle_destroy(b);
    }
}

/* Milotic switches out on turn 2: its Speed is rebuilt from its own forme (101) and its bit ends; Alakazam keeps the swap.
 * Alakazam switches out on turn 3: its Speed is its own (158) again, and the other slot's occupant is untouched. */
static void check_switch_reset(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *out = replay(t, ctx, "k3_speed_swap_switch", 3u);
    if (DF_CHECK(t, out != NULL)) {
        DF_CHECK(t, !swapped(out, 2u));                       /* Milotic's position: Gholdengo came in, bit clear */
        DF_CHECK(t, swapped(out, 0u));                        /* Alakazam keeps the swap (the leaver's reset is its own) */
        DF_CHECK_EQ_U64(t, stored_spe(out, 0u), K3_MILOTIC_SPE);
        {
            /* Milotic (roster 0 of side 1) left: its stored Speed is its own derived one again */
            dfi_member milotic = out->sides[1].members[0];
            DF_CHECK(t, dfi_closure_member_derive(&milotic));
            DF_CHECK_EQ_U64(t, out->sides[1].members[0].stats[DFI_STAT_SPE - 1u], milotic.stats[DFI_STAT_SPE - 1u]);
            DF_CHECK_EQ_U64(t, milotic.stats[DFI_STAT_SPE - 1u], K3_MILOTIC_SPE);
        }
        duoforge_battle_destroy(out);
    }
    duoforge_battle *back = replay(t, ctx, "k3_speed_swap_switch", 4u);
    if (DF_CHECK(t, back != NULL)) {
        DF_CHECK(t, !swapped(back, 0u));                      /* Alakazam switched out: Kingambit's own bit state */
        DF_CHECK_EQ_U64(t, stored_spe(back, 0u), derived_spe(back, 0u));
        DF_CHECK_EQ_U64(t, back->sides[0].members[0].stats[DFI_STAT_SPE - 1u], K3_ALAKAZAM_SPE);
        duoforge_battle_destroy(back);
    }
}

/* Stance Change: Aegislash's Iron Head makes it the Blade (the stats are rebuilt, so the swapped Speed and the bit end). */
static void check_stance_change_reset(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "k3_aegislash_shield_reset", 2u);
    if (DF_CHECK(t, b != NULL)) {
        DF_CHECK(t, b->tail.sides[1].forme_now[b->sides[1].positions[0].occupant] != 0u); /* the Blade */
        DF_CHECK(t, !swapped(b, 2u));
        DF_CHECK_EQ_U64(t, stored_spe(b, 2u), derived_spe(b, 2u));
        DF_CHECK_EQ_U64(t, stored_spe(b, 2u), K3_AEGISLASH_SPE);
        DF_CHECK(t, swapped(b, 0u));
        DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        duoforge_battle_destroy(b);
    }
}

/* A swap onto the Blade (Aegislash-Blade from turn 1): the Blade keeps the swapped Speed and the bit; the invariant (step G66,
 * the Blade's stats) accepts it. */
static void check_blade_swap(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *before = replay(t, ctx, "k3_aegislash_blade_swap", 2u);
    if (DF_CHECK(t, before != NULL)) {
        DF_CHECK(t, !swapped(before, 2u));
        DF_CHECK_EQ_U64(t, stored_spe(before, 2u), K3_AEGISLASH_SPE);
        duoforge_battle_destroy(before);
    }
    duoforge_battle *after = replay(t, ctx, "k3_aegislash_blade_swap", 3u);
    if (DF_CHECK(t, after != NULL)) {
        DF_CHECK(t, swapped(after, 2u) && swapped(after, 0u));
        DF_CHECK_EQ_U64(t, stored_spe(after, 2u), K3_ALAKAZAM_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(after, 0u), K3_AEGISLASH_SPE);
        DF_CHECK(t, after->tail.sides[1].forme_now[after->sides[1].positions[0].occupant] != 0u); /* still the Blade */
        DF_CHECK(t, duoforge_battle_check(ctx, after) == DUOFORGE_OK);
        for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
            duoforge_observation_ext bext;
            if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, after, viewer, &bext) == DUOFORGE_OK)) {
                DF_CHECK(t, (bext.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) != 0u);
                DF_CHECK(t, (bext.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) != 0u);
            }
        }
        duoforge_battle_destroy(after);
    }
}

/* Mega Evolution on turn 2: the Mega's stats are rebuilt (its Speed is the Mega forme's, derived), and the bit ends. */
static void check_mega_reset(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *before = replay(t, ctx, "k3_speed_swap_mega", 2u);
    if (DF_CHECK(t, before != NULL)) {
        DF_CHECK(t, swapped(before, 0u) && !before->sides[0].mega_used);
        duoforge_battle_destroy(before);
    }
    duoforge_battle *after = replay(t, ctx, "k3_speed_swap_mega", 3u);
    if (DF_CHECK(t, after != NULL)) {
        DF_CHECK(t, after->sides[0].members[0].is_mega == 1u);
        DF_CHECK(t, !swapped(after, 0u));
        for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
            duoforge_observation_ext mext;
            if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, after, viewer, &mext) == DUOFORGE_OK)) {
                DF_CHECK(t, (mext.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) == 0u); /* Alakazam: the Mega ends its swap */
                DF_CHECK(t, (mext.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) != 0u); /* Milotic keeps it */
            }
        }
        DF_CHECK_EQ_U64(t, stored_spe(after, 0u), derived_spe(after, 0u));
        duoforge_battle_destroy(after);
    }
}

/* Speed Swap with the ally (k3_speed_swap_ally, flat 0 Alakazam, 1 Baxcalibur, 2 Milotic, 3 Staraptor). Turn 1: Alakazam
 * (158) swaps with Baxcalibur (107): Alakazam 107, Baxcalibur 158, both bits set, both sides refused with 128. Turn 2:
 * Baxcalibur (158) moves first, then Alakazam (107) swaps with Milotic (101): Alakazam 101, Milotic 107; three bits set. */
static void check_ally(df_test *t, const duoforge_context *ctx)
{
    const char *name = "k3_speed_swap_ally";
    duoforge_battle *one = replay(t, ctx, name, 2u);
    if (DF_CHECK(t, one != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(one, 0u), K3_BAXCALIBUR_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(one, 1u), K3_ALAKAZAM_SPE);
        DF_CHECK(t, swapped(one, 0u) && swapped(one, 1u));
        DF_CHECK(t, !swapped(one, 2u) && !swapped(one, 3u));
        DF_CHECK(t, (public_mask(t, ctx, one, 0u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
        DF_CHECK(t, (public_mask(t, ctx, one, 1u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
        DF_CHECK(t, duoforge_battle_check(ctx, one) == DUOFORGE_OK);
        duoforge_battle_destroy(one);
    }
    duoforge_battle *two = replay(t, ctx, name, 3u);
    if (DF_CHECK(t, two != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(two, 0u), K3_MILOTIC_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(two, 1u), K3_ALAKAZAM_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(two, 2u), K3_BAXCALIBUR_SPE);
        DF_CHECK(t, swapped(two, 0u) && swapped(two, 1u) && swapped(two, 2u));
        DF_CHECK(t, !swapped(two, 3u));
        DF_CHECK(t, duoforge_battle_check(ctx, two) == DUOFORGE_OK);
        duoforge_battle_destroy(two);
    }
}

/* Speed Swap changes the order of a later action of the same turn (k3_speed_swap_same_turn): Alakazam (158) swaps with
 * Milotic (101); Milotic (158 now) then moves before Baxcalibur (107), which it would not have done without the swap (the
 * queue re-sorts after a move, sim/battle.ts:2921). The order itself is pinned by the replay equality of the trace; here the
 * Speeds and the bits after turn 1 and turn 2 (the second swap restores them). */
static void check_same_turn(df_test *t, const duoforge_context *ctx)
{
    const char *name = "k3_speed_swap_same_turn";
    duoforge_battle *one = replay(t, ctx, name, 2u);
    if (DF_CHECK(t, one != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(one, 0u), K3_MILOTIC_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(one, 2u), K3_ALAKAZAM_SPE);
        DF_CHECK(t, swapped(one, 0u) && swapped(one, 2u));
        DF_CHECK(t, !swapped(one, 1u) && !swapped(one, 3u));
        duoforge_battle_destroy(one);
    }
    duoforge_battle *two = replay(t, ctx, name, 3u);
    if (DF_CHECK(t, two != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(two, 0u), K3_ALAKAZAM_SPE);
        DF_CHECK_EQ_U64(t, stored_spe(two, 2u), K3_MILOTIC_SPE);
        DF_CHECK(t, swapped(two, 0u) && swapped(two, 2u));
        DF_CHECK(t, duoforge_battle_check(ctx, two) == DUOFORGE_OK);
        duoforge_battle_destroy(two);
    }
}

/* A swapped Pokemon faints (k3_speed_swap_faint): Milotic (swapped to 158) is KO'd by Alakazam's Psyshock on turn 4. Alakazam
 * keeps its swapped Speed (101) and its bit, so the public record stays refused with 128. Milotic's own bit and Speed end
 * with its occupant when the replacement comes in (switch 3 = Kingambit): its Speed is its own derived one again. */
static void check_faint(df_test *t, const duoforge_context *ctx)
{
    const char *name = "k3_speed_swap_faint";
    duoforge_battle *fainted = replay(t, ctx, name, 5u);
    if (DF_CHECK(t, fainted != NULL)) {
        DF_CHECK(t, fainted->sides[1].members[0].hp == 0u);
        DF_CHECK(t, swapped(fainted, 0u));
        DF_CHECK_EQ_U64(t, stored_spe(fainted, 0u), K3_MILOTIC_SPE);
        DF_CHECK(t, (public_mask(t, ctx, fainted, 0u) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
        duoforge_battle_destroy(fainted);
    }
    duoforge_battle *replaced = replay(t, ctx, name, 6u);
    if (DF_CHECK(t, replaced != NULL)) {
        DF_CHECK(t, !swapped(replaced, 2u));                  /* the fainted Milotic's position: Kingambit, bit clear */
        DF_CHECK(t, swapped(replaced, 0u));                   /* Alakazam keeps the swap */
        DF_CHECK_EQ_U64(t, stored_spe(replaced, 0u), K3_MILOTIC_SPE);
        {
            dfi_member milotic = replaced->sides[1].members[0];
            DF_CHECK(t, dfi_closure_member_derive(&milotic));
            DF_CHECK_EQ_U64(t, milotic.stats[DFI_STAT_SPE - 1u], K3_MILOTIC_SPE);
        }
        DF_CHECK(t, duoforge_battle_check(ctx, replaced) == DUOFORGE_OK);
        duoforge_battle_destroy(replaced);
    }
}

/* The presence bit (DUOFORGE_POSITION_EXT_SPEED_SWAPPED, bit 23 under feature 46) of both swapped positions is public: each
 * viewer, the foe too, sees it on the swapped position of both sides and on no other (k3_speed_swap_basic after turn 1). */
static void check_view_bit(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *after = replay(t, ctx, "k3_speed_swap_basic", 2u);
    if (DF_CHECK(t, after != NULL)) {
        for (uint32_t viewer = 0u; viewer < DUOFORGE_SIDE_COUNT; ++viewer) {
            duoforge_observation_ext ext;
            if (DF_CHECK(t, duoforge_battle_observe_ext(ctx, after, viewer, &ext) == DUOFORGE_OK)) {
                DF_CHECK(t, (ext.sides[0].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) != 0u);
                DF_CHECK(t, (ext.sides[1].positions[0].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) != 0u);
                DF_CHECK(t, (ext.sides[0].positions[1].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) == 0u);
                DF_CHECK(t, (ext.sides[1].positions[1].volatiles & DUOFORGE_POSITION_EXT_SPEED_SWAPPED) == 0u);
                DF_CHECK(t, (ext.supported & ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_SPEED_SWAPPED)) != 0u);
            }
        }
        duoforge_battle_destroy(after);
    }
}

/* The owner's view shows its own unswapped Speed while a swap stands (the request shows baseStoredStats, sim/pokemon.ts:1159-1165;
 * Speed Swap writes storedStats only). After Alakazam swaps with the foe Milotic (k3_speed_swap_basic, turn 1): the stored Speed
 * of Alakazam is Milotic's 101 (internal), but viewer 0 sees Alakazam at its own 189 and never sees Milotic's Speed; viewer 1
 * sees Milotic at its own 101 and never Alakazam's. The foe's side is not public: its Speeds read 0 to the other viewer. */
static void check_owner_speed(df_test *t, const duoforge_context *ctx)
{
    duoforge_battle *b = replay(t, ctx, "k3_speed_swap_basic", 2u);
    if (DF_CHECK(t, b != NULL)) {
        DF_CHECK_EQ_U64(t, stored_spe(b, 0u), K3_MILOTIC_SPE);
        duoforge_observation ob0, ob1;
        if (DF_CHECK(t, duoforge_battle_observe(ctx, b, 0u, &ob0) == DUOFORGE_OK) &&
            DF_CHECK(t, duoforge_battle_observe(ctx, b, 1u, &ob1) == DUOFORGE_OK)) {
            DF_CHECK_EQ_U64(t, ob0.sides[0].members[0].stats[4], K3_ALAKAZAM_SPE);
            DF_CHECK_EQ_U64(t, ob0.sides[1].members[0].stats[4], 0u);
            DF_CHECK_EQ_U64(t, ob1.sides[1].members[0].stats[4], K3_MILOTIC_SPE);
            DF_CHECK_EQ_U64(t, ob1.sides[0].members[0].stats[4], 0u);
        }
        duoforge_battle_destroy(b);
    }
}

/* The byte of the canonical state that holds the single_turn bits of position `flat` (state codec, rev 4). */
static size_t single_turn_offset(uint32_t flat)
{
    const uint32_t s = flat / DUOFORGE_ACTIVE_PER_SIDE;
    const uint32_t p = flat % DUOFORGE_ACTIVE_PER_SIDE;
    return DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_SIDES_OFF + s * DFI_ENC_TAIL_SIDE_SIZE + DFI_ENC_TAIL_POS_OFF +
           p * DFI_ENC_TAIL_POS_SIZE + DFI_ENC_TAIL_POS_SINGLE_TURN_OFF;
}

/* The engine's record gate (step K3 proof 2a, HS brief): at a point with live swaps, the battle's own record is refused with
 * cause 128 for both players; the same battle with the presence bits cleared gives an OK record that the gate accepts; setting
 * the bit back in that record's state bytes makes the gate refuse it, so the engine decides from the bit, not the tracker. */
static void check_record_gate(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    duoforge_battle *b = replay(t, ctx, name, steps);
    if (!DF_CHECK(t, b != NULL)) {
        return;
    }
    uint8_t saved[DUOFORGE_SIDE_COUNT][DUOFORGE_ACTIVE_PER_SIDE];
    uint16_t saved_spe[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_ROSTER];
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            saved_spe[s][m] = b->sides[s].members[m].stats[DFI_STAT_SPE - 1u];
        }
    }
    uint32_t live[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
    uint32_t live_count = 0u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            saved[s][p] = b->tail.sides[s].positions[p].single_turn;
            if ((saved[s][p] & DFI_SINGLE_TURN_SPEED_SWAP) != 0u) {
                live[live_count++] = s * DUOFORGE_ACTIVE_PER_SIDE + p;
            }
        }
    }
    DF_CHECK(t, live_count > 0u);
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        duoforge_public_state real;
        DF_CHECK(t, duoforge_battle_public(ctx, b, player, &real) == DUOFORGE_E_UNSUPPORTED);
        DF_CHECK(t, (public_mask(t, ctx, b, player) & DUOFORGE_PUBLIC_CAUSE_SPEED_SWAP) != 0u);
    }
    /* the same state without the swap: each live swapped member gets its derived Speed (what a rebuild of its stats gives,
     * the stored Speed of a Pokemon that was never swapped) and the bit ends */
    for (uint32_t i = 0u; i < live_count; ++i) {
        const uint32_t flat = live[i];
        const uint32_t derived = derived_spe(b, flat);
        if (!DF_CHECK(t, derived != 0xFFFFu)) {
            break;
        }
        occupant_of(b, flat)->stats[DFI_STAT_SPE - 1u] = (uint16_t)derived;
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            b->tail.sides[s].positions[p].single_turn &= (uint8_t)~DFI_SINGLE_TURN_SPEED_SWAP;
        }
    }
    for (uint32_t player = 0u; player < DUOFORGE_SIDE_COUNT; ++player) {
        duoforge_public_state rec;
        const uint32_t other = public_mask(t, ctx, b, player);
        if (other != 0u) {
            /* the same state refuses for another named cause (the Blade forme is a temporary forme, TEMP_FORME): the point
             * proves nothing about the gate, and the refusal must be that named cause, not an invariant failure */
            DF_CHECK(t, (other & DUOFORGE_PUBLIC_CAUSE_TEMP_FORME) != 0u);
            DF_CHECK(t, duoforge_battle_public(ctx, b, player, &rec) == DUOFORGE_E_UNSUPPORTED);
            continue;
        }
        if (DF_CHECK_EQ_U64(t, (uint64_t)duoforge_battle_public(ctx, b, player, &rec), (uint64_t)DUOFORGE_OK)) {
            DF_CHECK(t, duoforge_public_record_check(ctx, &rec) == DUOFORGE_OK);
            for (uint32_t i = 0u; i < live_count; ++i) {
                const size_t off = single_turn_offset(live[i]);
                DF_CHECK(t, (rec.state[off] & DFI_SINGLE_TURN_SPEED_SWAP) == 0u);
                rec.state[off] = (uint8_t)(rec.state[off] | DFI_SINGLE_TURN_SPEED_SWAP);
            }
            DF_CHECK(t, duoforge_public_record_check(ctx, &rec) == DUOFORGE_E_UNSUPPORTED);
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            b->sides[s].members[m].stats[DFI_STAT_SPE - 1u] = saved_spe[s][m];
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            b->tail.sides[s].positions[p].single_turn = saved[s][p];
        }
    }
    duoforge_battle_destroy(b);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_k3");
    duoforge_context *ctx = df_make_context(&df_config_pool);
    DF_CHECK(&t, ctx != NULL);
    if (ctx != NULL) {
        check_swap_and_persistence(&t, ctx);
        check_protect(&t, ctx);
        check_switch_reset(&t, ctx);
        check_stance_change_reset(&t, ctx);
        check_blade_swap(&t, ctx);
        check_mega_reset(&t, ctx);
        check_ally(&t, ctx);
        check_same_turn(&t, ctx);
        check_faint(&t, ctx);
        check_view_bit(&t, ctx);
        check_owner_speed(&t, ctx);
        check_record_gate(&t, ctx, "k3_speed_swap_basic", 2u);
        check_record_gate(&t, ctx, "k3_speed_swap_mega", 3u);
        check_record_gate(&t, ctx, "k3_aegislash_blade_swap", 3u);
        duoforge_context_destroy(ctx);
    }
    return df_test_end(&t);
}
