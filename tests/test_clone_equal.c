/*
 * T10 duoforge.state.clone_equal: clone, copy (snapshot/restore), equality,
 * fork independence, padding independence, context mismatch, corrupt-state
 * safety and reseeding a fork. Expectations: the clone/copy/equal contract
 * (docs/decisions/0002) and golden F2 v3 (independent model).
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "rng/pcg32.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"

static bool api_equal(df_test *t, const duoforge_context *ctx, const duoforge_battle *a, const duoforge_battle *b)
{
    bool eq = false;
    DF_CHECK(t, duoforge_battle_equal(ctx, a, b, &eq) == DUOFORGE_OK);
    return eq;
}

/* The kinds of this test are all schema 3 (no POOL tail): any such context encodes them. */
static const duoforge_context *enc_ctx;

static void raw(const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE])
{
    memset(out, 0, DUOFORGE_STATE_V3_ENCODED_SIZE);
    (void)dfi_encode_unchecked(enc_ctx, b, out);
}

/* Runs an equal() call that must fail, with *out preset to both false and
 * true (rule S3); it must stay unchanged. */
static void equal_fails(df_test *t, const duoforge_context *ctx, const duoforge_battle *a,
                        const duoforge_battle *b, duoforge_status expected)
{
    for (unsigned preset = 0; preset < 2; ++preset) {
        bool out = preset == 1;
        DF_CHECK(t, duoforge_battle_equal(ctx, a, b, &out) == expected);
        DF_CHECK(t, out == (preset == 1));
    }
}

/* Copies every named field of src into dst (whose padding bytes hold a
 * background pattern). */
static void copy_named_fields(duoforge_battle *x, const duoforge_battle *src)
{
    memcpy(x->context_fingerprint, src->context_fingerprint, DUOFORGE_DIGEST_SIZE);
    x->rng.state = src->rng.state;
    x->rng.inc = src->rng.inc;
    x->rng.draws = src->rng.draws;
    x->next_activation_id = src->next_activation_id;
    x->request_epoch = src->request_epoch;
    x->boundary_kind = src->boundary_kind;
    x->request_mask = src->request_mask;
    x->turn = src->turn;
    x->result = src->result;
    x->weather = src->weather;
    x->weather_turns = src->weather_turns;
    x->terrain = src->terrain;
    x->terrain_turns = src->terrain_turns;
    x->trick_room_turns = src->trick_room_turns;
    x->queue_len = src->queue_len;
    for (unsigned i = 0; i < DFI_QUEUE_CAPACITY; ++i) {
        x->queue[i].activation_id = src->queue[i].activation_id;
        x->queue[i].kind = src->queue[i].kind;
        x->queue[i].side = src->queue[i].side;
        x->queue[i].slot = src->queue[i].slot;
        x->queue[i].move_slot = src->queue[i].move_slot;
        x->queue[i].target = src->queue[i].target;
        x->queue[i].reserve = src->queue[i].reserve;
    }
    for (unsigned s = 0; s < 2; ++s) {
        const dfi_side *ss = &src->sides[s];
        dfi_side *ds = &x->sides[s];
        ds->member_count = ss->member_count;
        ds->brought_mask = ss->brought_mask;
        ds->requested_slots = ss->requested_slots;
        ds->mega_used = ss->mega_used;
        ds->sealed = ss->sealed;
        ds->seen_mask = ss->seen_mask;
        ds->reflect_turns = ss->reflect_turns;
        ds->light_screen_turns = ss->light_screen_turns;
        ds->tailwind_turns = ss->tailwind_turns;
        for (unsigned i = 0; i < DUOFORGE_MAX_ROSTER; ++i) {
            ds->brought_order[i] = ss->brought_order[i];
            ds->knowledge[i].hp_percent = ss->knowledge[i].hp_percent;
            ds->knowledge[i].hp_flag = ss->knowledge[i].hp_flag;
            ds->knowledge[i].revealed = ss->knowledge[i].revealed;
            for (unsigned q = 0; q < DUOFORGE_MAX_MOVE_SLOTS; ++q) {
                ds->knowledge[i].moves_used[q] = ss->knowledge[i].moves_used[q];
            }
        }
        for (unsigned p = 0; p < 2; ++p) {
            ds->positions[p].occupant = ss->positions[p].occupant;
            ds->positions[p].activation_id = ss->positions[p].activation_id;
            for (unsigned i = 0; i < DFI_STAT_STAGE_COUNT; ++i) {
                ds->positions[p].stages[i] = ss->positions[p].stages[i];
            }
            ds->positions[p].flags = ss->positions[p].flags;
            ds->positions[p].stall_level = ss->positions[p].stall_level;
            ds->positions[p].stall_turns = ss->positions[p].stall_turns;
            ds->positions[p].confusion_turns = ss->positions[p].confusion_turns;
            ds->positions[p].charge_turns = ss->positions[p].charge_turns;
            ds->positions[p].locked_move = ss->positions[p].locked_move;
            ds->positions[p].locked_target = ss->positions[p].locked_target;
            ds->positions[p].move_actions = ss->positions[p].move_actions;
            ds->positions[p].switch_flag = ss->positions[p].switch_flag;
            ds->sealed_cmds[p].kind = ss->sealed_cmds[p].kind;
            ds->sealed_cmds[p].move_slot = ss->sealed_cmds[p].move_slot;
            ds->sealed_cmds[p].target = ss->sealed_cmds[p].target;
            ds->sealed_cmds[p].mega = ss->sealed_cmds[p].mega;
            ds->sealed_cmds[p].reserve = ss->sealed_cmds[p].reserve;
        }
        for (unsigned m = 0; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *sm = &ss->members[m];
            dfi_member *dm = &ds->members[m];
            dm->species_id = sm->species_id;
            dm->hp = sm->hp;
            dm->hp_max = sm->hp_max;
            dm->move_count = sm->move_count;
            dm->mega_capable = sm->mega_capable;
            for (unsigned q = 0; q < DFI_MEMBER_STAT_COUNT; ++q) {
                dm->stats[q] = sm->stats[q];
            }
            for (unsigned q = 0; q < DFI_STAT_POINT_COUNT; ++q) {
                dm->stat_points[q] = sm->stat_points[q];
            }
            dm->is_mega = sm->is_mega;
            dm->gender = sm->gender;
            dm->nature = sm->nature;
            dm->status = sm->status;
            dm->status_counter = sm->status_counter;
            dm->item = sm->item;
            dm->item_consumed = sm->item_consumed;
            dm->ability = sm->ability;
            for (unsigned q = 0; q < DUOFORGE_MAX_MOVE_SLOTS; ++q) {
                dm->moves[q].move_id = sm->moves[q].move_id;
                dm->moves[q].pp = sm->moves[q].pp;
                dm->moves[q].pp_max = sm->moves[q].pp_max;
            }
        }
        /* The POOL tail (decision 0015 section 7): zero under these kinds, but named like every other field. */
        const dfi_tail_side *st = &src->tail.sides[s];
        dfi_tail_side *dt = &x->tail.sides[s];
        dt->wide_guard = st->wide_guard;
        dt->aurora_veil_turns = st->aurora_veil_turns;
        dt->toxic_spikes = st->toxic_spikes;
        dt->stealth_rock = st->stealth_rock;
        dt->spikes = st->spikes;
        dt->sticky_web = st->sticky_web;
        dt->quick_guard = st->quick_guard;
        dt->hazard_order = st->hazard_order;
        dt->illusion = st->illusion; /* tail rev 5 (decision 0026) */
        for (unsigned p = 0; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *sp = &st->positions[p];
            dfi_tail_pos *dp = &dt->positions[p];
            dp->substitute_hp = sp->substitute_hp;
            dp->trap_move = sp->trap_move;
            dp->last_move = sp->last_move;
            dp->encore_slot = sp->encore_slot;
            dp->encore_turns = sp->encore_turns;
            dp->throat_chop_turns = sp->throat_chop_turns;
            dp->heal_block_turns = sp->heal_block_turns;
            dp->perish = sp->perish;
            dp->taunt_turns = sp->taunt_turns;
            dp->disable_slot = sp->disable_slot;
            dp->disable_turns = sp->disable_turns;
            dp->imprison = sp->imprison;
            dp->must_recharge = sp->must_recharge;
            dp->trap_turns = sp->trap_turns;
            dp->trap_source = sp->trap_source;
            dp->trap_band = sp->trap_band;
            dp->leech_seed_source = sp->leech_seed_source;
            dp->yawn_turns = sp->yawn_turns;
            dp->focus_energy = sp->focus_energy;
            dp->stockpile = sp->stockpile;
            dp->stockpile_def = sp->stockpile_def;
            dp->stockpile_spd = sp->stockpile_spd;
            dp->charge = sp->charge;
            dp->glaive_rush = sp->glaive_rush;
            dp->protect_kind = sp->protect_kind;
            dp->move_result = sp->move_result;
            dp->single_turn = sp->single_turn;
            dp->hits_taken = sp->hits_taken;
            dp->ability_state = sp->ability_state;
            dp->lock_turns = sp->lock_turns;
            dp->position_flags = sp->position_flags; /* tail rev 5 */
            dp->future_sight = sp->future_sight;
        }
        for (unsigned m = 0; m < DUOFORGE_MAX_ROSTER; ++m) {
            dt->ability_now[m] = st->ability_now[m];
            dt->forme_now[m] = st->forme_now[m];
            dt->soak_type[m] = st->soak_type[m];
            dt->item_now[m] = st->item_now[m];
            dt->toxic_stage[m] = st->toxic_stage[m];
            dt->type2[m] = st->type2[m];
            dt->member_flags[m] = st->member_flags[m];
        }
    }
    x->tail.gravity_turns = src->tail.gravity_turns;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        for (uint32_t i = 0u; i < DFI_PARTY_BYTES_PER_SIDE; ++i) {
            x->tail.party_order[s][i] = src->tail.party_order[s][i]; /* step G46 */
        }
    }
    x->tail.field_pad = src->tail.field_pad;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.clone_equal");

    duoforge_context *c1 = df_make_context(&df_config_c1);
    enc_ctx = c1;
    duoforge_context *c2 = df_make_context(&df_config_c2);
    duoforge_battle *f1 = df_make_f1(c1);
    duoforge_battle *f2 = df_make_f2(c1);
    duoforge_battle *f5 = df_make_f5(c1);
    uint8_t e1[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t e2[DUOFORGE_STATE_V3_ENCODED_SIZE];

    /* Clone of F1: equal, same encoding and digest. */
    duoforge_battle *k = NULL;
    DF_CHECK(&t, duoforge_battle_clone(c1, f1, &k) == DUOFORGE_OK && k != NULL);
    DF_CHECK(&t, api_equal(&t, c1, f1, k));
    df_encode(c1, f1, e1);
    df_encode(c1, k, e2);
    DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "clone encoding");
    {
        uint8_t d1[DUOFORGE_DIGEST_SIZE];
        uint8_t d2[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, duoforge_battle_digest(c1, f1, d1) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_digest(c1, k, d2) == DUOFORGE_OK);
        DF_CHECK_BYTES(&t, d2, d1, sizeof d1, "clone digest");
    }
    /* Clone of a decoded golden F2. */
    {
        uint8_t *in = df_heap_copy(df_golden_f2, DUOFORGE_STATE_V3_ENCODED_SIZE);
        duoforge_battle *d = NULL;
        duoforge_battle *dc = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(c1, in, DUOFORGE_STATE_V3_ENCODED_SIZE, &d) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, d, &dc) == DUOFORGE_OK);
        df_encode(c1, dc, e2);
        DF_CHECK_BYTES(&t, e2, df_golden_f2, sizeof e2, "clone of decoded F2");
        DF_CHECK(&t, api_equal(&t, c1, dc, f2));
        duoforge_battle_destroy(dc);
        duoforge_battle_destroy(d);
        df_free(in);
    }
    /* copy F2 into a battle created fresh (restore from snapshot), and a
     * PIVOT snapshot (F5) into a TURN handle: boundaries restore too. */
    {
        duoforge_battle *dst = df_make_g1(c1);
        DF_CHECK(&t, duoforge_battle_copy(c1, dst, f2) == DUOFORGE_OK);
        df_encode(c1, dst, e2);
        DF_CHECK_BYTES(&t, e2, df_golden_f2, sizeof e2, "copy F2 into G1 handle");
        DF_CHECK(&t, duoforge_battle_copy(c1, dst, f5) == DUOFORGE_OK);
        DF_CHECK(&t, api_equal(&t, c1, dst, f5));
        DF_CHECK(&t, duoforge_battle_check(c1, dst) == DUOFORGE_OK);
        duoforge_battle_destroy(dst);
    }
    /* Aliased copy: OK and unchanged under the matching context ... */
    DF_CHECK(&t, duoforge_battle_copy(c1, k, k) == DUOFORGE_OK);
    DF_CHECK(&t, api_equal(&t, c1, k, f1));
    /* ... but a context mismatch comes first even when dst == src. */
    raw(k, e1);
    DF_CHECK(&t, duoforge_battle_copy(c2, k, k) == DUOFORGE_E_CONTEXT_MISMATCH);
    raw(k, e2);
    DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "aliased mismatch unchanged");

    /* Independence: a draw or HP poke on the clone does not touch the source. */
    {
        raw(f1, e1);
        uint32_t v = 0;
        DF_CHECK(&t, dfi_rng_next_u32(&k->rng, &v) == DUOFORGE_OK);
        raw(f1, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "source unchanged after clone draw");
        DF_CHECK(&t, !api_equal(&t, c1, f1, k));
        DF_CHECK(&t, duoforge_battle_copy(c1, k, f1) == DUOFORGE_OK);
        k->sides[1].members[2].hp = 1u;
        raw(f1, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "source unchanged after clone poke");
        DF_CHECK(&t, !api_equal(&t, c1, f1, k));
        DF_CHECK(&t, duoforge_battle_copy(c1, k, f1) == DUOFORGE_OK);
    }

    /* Forks draw identical streams (64 raw draws). */
    {
        duoforge_battle *a = NULL;
        duoforge_battle *b = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &a) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_clone(c1, f2, &b) == DUOFORGE_OK);
        unsigned diff = 0;
        for (unsigned i = 0; i < 64; ++i) {
            uint32_t x = 0;
            uint32_t y = 1;
            (void)dfi_rng_next_u32(&a->rng, &x);
            (void)dfi_rng_next_u32(&b->rng, &y);
            diff += x != y ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, diff, 0u);
        DF_CHECK(&t, api_equal(&t, c1, a, b));
        /* Reseeding a fork decorrelates it; nothing but the RNG (52..76) changes. */
        raw(a, e1);
        DF_CHECK(&t, duoforge_battle_reseed(c1, b, 7u, 9u) == DUOFORGE_OK);
        raw(b, e2);
        unsigned outside = 0;
        for (unsigned i = 0; i < sizeof e1; ++i) {
            outside += (e1[i] != e2[i] && (i < 52u || i >= 76u)) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, outside, 0u);
        dfi_rng fresh;
        dfi_rng_seed(&fresh, 7u, 9u);
        DF_CHECK(&t, b->rng.state == fresh.state && b->rng.inc == fresh.inc && b->rng.draws == 0u);
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        DF_CHECK(&t, !api_equal(&t, c1, a, b));
        /* Reseed failures are atomic. */
        raw(b, e1);
        DF_CHECK(&t, duoforge_battle_reseed(c1, b, 1u, UINT64_C(0x8000000000000000)) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(c2, b, 1u, 2u) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_reseed(NULL, b, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(&t, duoforge_battle_reseed(c1, NULL, 1u, 2u) == DUOFORGE_E_NULL_ARGUMENT);
        raw(b, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "reseed failures unchanged");
        duoforge_battle_destroy(a);
        duoforge_battle_destroy(b);
    }

    /* Equality relation over F1, F2 and 28 single-field variants of F1 (all
     * valid states): equal <=> encodings identical <=> digests equal. */
    {
        enum { N = 30 };
        duoforge_battle *v[N];
        for (unsigned i = 0; i < N; ++i) {
            v[i] = NULL;
            DF_CHECK(&t, duoforge_battle_clone(c1, i == 1 ? f2 : f1, &v[i]) == DUOFORGE_OK);
        }
        v[2]->rng.state ^= 1u;
        v[3]->rng.inc ^= 2u;
        v[4]->rng.draws += 1u;
        v[5]->next_activation_id += 1u;
        v[6]->sides[0].members[0].hp = (uint16_t)(v[6]->sides[0].members[0].hp - 1u);
        v[7]->sides[1].members[3].hp_max = (uint16_t)(v[7]->sides[1].members[3].hp_max + 1u);
        v[8]->sides[0].members[5].species_id = 7u;
        v[9]->sides[1].members[0].moves[2].pp = (uint8_t)(v[9]->sides[1].members[0].moves[2].pp - 1u);
        v[10]->sides[0].members[3].moves[3].pp_max = (uint8_t)(v[10]->sides[0].members[3].moves[3].pp_max + 1u);
        v[11]->sides[0].members[1].moves[1].move_id = 30u;
        v[12]->sides[1].positions[1].activation_id = 9u;
        v[12]->next_activation_id = 10u;
        v[13]->sides[0].positions[0].occupant = 3u;
        v[13]->sides[1].seen_mask |= 0x08u; /* the replacement was seen */
        v[14]->sides[1].brought_mask = 0x0Fu; /* unchanged value: must stay equal to F1 */
        v[15]->sides[0].members[4].hp = 0u;
        v[16]->sides[1].members[1].moves[0].pp = 0u;
        v[17]->rng.state ^= UINT64_C(0x8000000000000000);
        v[18]->rng.draws = UINT64_MAX;
        v[19]->sides[0].brought_order[2] = 3u; /* private bench order swapped */
        v[19]->sides[0].brought_order[3] = 1u;
        v[20]->sides[1].mega_used = 1u;
        v[21]->request_epoch = 7u;
        /* One field of every v3 group. */
        v[22]->turn = 2u;
        v[23]->weather = (uint8_t)DFI_WEATHER_RAIN;
        v[23]->weather_turns = 1u;
        v[24]->trick_room_turns = 1u;
        v[25]->sides[0].tailwind_turns = 1u;
        v[26]->sides[1].positions[0].stages[4] = 7u;
        v[27]->sides[0].positions[1].move_actions = 1u;
        v[28]->sides[1].positions[1].flags = (uint8_t)DFI_VOL_FLASH_FIRE;
        v[29]->sides[0].knowledge[3].moves_used[0] = 1u;
        /* What the opponent sees follows the HP and occupant edits above. */
        for (unsigned i = 0; i < N; ++i) {
            df_knowledge_refresh_active(v[i]);
        }
        unsigned mismatches = 0;
        for (unsigned i = 0; i < N; ++i) {
            for (unsigned j = 0; j < N; ++j) {
                uint8_t a[DUOFORGE_STATE_V3_ENCODED_SIZE];
                uint8_t b[DUOFORGE_STATE_V3_ENCODED_SIZE];
                uint8_t da[DUOFORGE_DIGEST_SIZE];
                uint8_t db[DUOFORGE_DIGEST_SIZE];
                raw(v[i], a);
                raw(v[j], b);
                const bool bytes_eq = memcmp(a, b, sizeof a) == 0;
                const bool api_eq = api_equal(&t, c1, v[i], v[j]);
                DF_CHECK(&t, duoforge_battle_digest(c1, v[i], da) == DUOFORGE_OK);
                DF_CHECK(&t, duoforge_battle_digest(c1, v[j], db) == DUOFORGE_OK);
                const bool dig_eq = memcmp(da, db, sizeof da) == 0;
                mismatches += (bytes_eq != api_eq || bytes_eq != dig_eq) ? 1u : 0u;
                mismatches += (i == j && !api_eq) ? 1u : 0u;                          /* reflexive */
                mismatches += (api_eq != api_equal(&t, c1, v[j], v[i])) ? 1u : 0u; /* symmetric */
            }
        }
        DF_CHECK_EQ_U64(&t, mismatches, 0u);
        DF_CHECK(&t, api_equal(&t, c1, v[14], v[0]));
        for (unsigned i = 1; i < N; ++i) {
            if (i != 14) {
                DF_CHECK(&t, !api_equal(&t, c1, v[i], v[0]));
            }
        }
        for (unsigned i = 0; i < N; ++i) {
            duoforge_battle_destroy(v[i]);
        }
    }

    /* Padding independence: states assembled on 0x00 and 0xAA backgrounds with
     * the same named fields compare equal, encode and digest identically. */
    {
        const duoforge_battle *srcs[2] = {f2, f5};
        const uint8_t *goldens[2] = {df_golden_f2, df_golden_f5};
        for (unsigned s = 0; s < 2; ++s) {
            duoforge_battle *a = NULL;
            duoforge_battle *b = NULL;
            DF_CHECK(&t, duoforge_battle_clone(c1, srcs[s], &a) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_battle_clone(c1, srcs[s], &b) == DUOFORGE_OK);
            memset(a, 0x00, sizeof *a);
            memset(b, 0xAA, sizeof *b);
            copy_named_fields(a, srcs[s]);
            copy_named_fields(b, srcs[s]);
            DF_CHECK(&t, api_equal(&t, c1, a, b));
            DF_CHECK(&t, api_equal(&t, c1, a, srcs[s]));
            df_encode(c1, a, e1);
            df_encode(c1, b, e2);
            DF_CHECK_BYTES(&t, e1, e2, sizeof e1, "padding-independent encoding");
            if (goldens[s] != NULL) {
                DF_CHECK_BYTES(&t, e1, goldens[s], sizeof e1, "padding-independent encoding = golden");
            }
            uint8_t da[DUOFORGE_DIGEST_SIZE];
            uint8_t db[DUOFORGE_DIGEST_SIZE];
            DF_CHECK(&t, duoforge_battle_digest(c1, a, da) == DUOFORGE_OK);
            DF_CHECK(&t, duoforge_battle_digest(c1, b, db) == DUOFORGE_OK);
            DF_CHECK_BYTES(&t, da, db, sizeof da, "padding-independent digest");
            duoforge_battle_destroy(a);
            duoforge_battle_destroy(b);
        }
    }

    /* Context mismatch: copy/equal/clone fail and change nothing. */
    {
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &x) == DUOFORGE_OK);
        x->context_fingerprint[0] ^= 0xFFu; /* bound to "another context" */
        raw(x, e1);
        DF_CHECK(&t, duoforge_battle_copy(c1, x, f1) == DUOFORGE_E_CONTEXT_MISMATCH);
        raw(x, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "copy dst mismatch unchanged");
        raw(k, e1);
        DF_CHECK(&t, duoforge_battle_copy(c1, k, x) == DUOFORGE_E_CONTEXT_MISMATCH);
        raw(k, e2);
        DF_CHECK_BYTES(&t, e2, e1, sizeof e1, "copy src mismatch unchanged");
        equal_fails(&t, c1, f1, x, DUOFORGE_E_CONTEXT_MISMATCH);
        equal_fails(&t, c1, x, f1, DUOFORGE_E_CONTEXT_MISMATCH);
        df_sentinel sentinel;
        duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
        duoforge_battle *out = marker;
        DF_CHECK(&t, duoforge_battle_clone(c1, x, &out) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, out == marker);
        duoforge_battle_destroy(x);
    }

    /* Corrupt state: copy/clone/equal succeed (no invariant check) and stay
     * memory-safe; equal is deterministic. */
    {
        duoforge_battle *x = NULL;
        duoforge_battle *y = NULL;
        DF_CHECK(&t, duoforge_battle_clone(c1, f1, &x) == DUOFORGE_OK);
        x->sides[0].member_count = 0xFFu;
        DF_CHECK(&t, duoforge_battle_clone(c1, x, &y) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_copy(c1, k, x) == DUOFORGE_OK);
        DF_CHECK(&t, api_equal(&t, c1, x, y));
        DF_CHECK(&t, api_equal(&t, c1, x, y));
        DF_CHECK(&t, duoforge_battle_check(c1, x) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(x);
        duoforge_battle_destroy(y);
    }

    duoforge_battle_destroy(k);
    duoforge_battle_destroy(f1);
    duoforge_battle_destroy(f2);
    duoforge_battle_destroy(f5);
    duoforge_context_destroy(c1);
    duoforge_context_destroy(c2);
    return df_test_end(&t);
}
