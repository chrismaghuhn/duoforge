/*
 * duoforge.state.pool_setup (white-box): the POOL data kinds of decision 0015
 * section 2.
 *
 * POOL and POOL_DEV read the pool tables (the extended tables plus the
 * rows of the content expansion); the kind's counts bound every id at setup
 * and in the invariants, so a pool id is out of range under the CLOSURE and
 * TEAM_C kinds: E_INVALID_ARGUMENT at setup and E_INVARIANT (the member
 * invariant) in a state, which a decode reports as E_MALFORMED. The setup
 * rules are the closure rules over the pool tables with the certified
 * profile (register 6, bring 4) under POOL; POOL_DEV is as the other DEV
 * kinds: also No Ability and four to six registered members. The one change
 * is the set rule: under the POOL kinds a member's moves are ones its forme
 * learns and its ability one of the forme's legal abilities, in a setup and
 * in the member invariant; the four other kinds keep the forme's set. The
 * support manifest decides what a battle may use: the new items (the type
 * boosters and resist berries) are marked since step P2, the new abilities
 * are not, so a setup that uses one fails with E_UNSUPPORTED after all
 * validation, and so does every step of a battle that holds one; an unmarked
 * item (the manifest edited in a copy) is gone the same way.
 *
 * The fingerprints are those of tools/state_model/state_v3_model.py (the
 * contexts KP and KPD).
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "codec/state_codec.h"
#include "core/sha256.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

#define FP_KP_HEX "66e30759b6b926a739e99712ec974a0774d06b640f3e3dda9014febf9e508a60"
#define FP_KPD_HEX "3560f266a9afbb938df9cf06cd56ea26031400ffb52795e339fc7ccb0b5ae905"

/* The public create under `ctx` gives `gated`, and the build without the
 * support gate `ungated`. */
static void create_expect(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s,
                          duoforge_status gated, duoforge_status ungated, const char *what)
{
    duoforge_battle *made = NULL;
    const duoforge_status cs = duoforge_battle_create(ctx, s, &made);
    if (!DF_CHECK(t, cs == gated && (made != NULL) == (gated == DUOFORGE_OK))) {
        fprintf(stderr, "  create %s: %s, expected %s\n", what, duoforge_status_name(cs),
                duoforge_status_name(gated));
    }
    duoforge_battle_destroy(made);
    duoforge_battle *out = NULL;
    const duoforge_status us = dfi_battle_create_ungated(ctx, s, &out);
    if (!DF_CHECK(t, us == ungated && (out != NULL) == (ungated == DUOFORGE_OK))) {
        fprintf(stderr, "  ungated %s: %s, expected %s\n", what, duoforge_status_name(us),
                duoforge_status_name(ungated));
    }
    duoforge_battle_destroy(out);
}

static void invalid(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, const char *what)
{
    create_expect(t, ctx, s, DUOFORGE_E_INVALID_ARGUMENT, DUOFORGE_E_INVALID_ARGUMENT, what);
}

/* A legal setup: the gate decides between OK and E_UNSUPPORTED, and the build
 * without the gate accepts it either way. */
static void legal(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, bool supported,
                  const char *what)
{
    create_expect(t, ctx, s, supported ? DUOFORGE_OK : DUOFORGE_E_UNSUPPORTED, DUOFORGE_OK, what);
}

static void expect_inv(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, dfi_invariant want,
                       const char *what)
{
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status st = dfi_state_check(ctx, b, &got);
    const bool ok = want == DFI_INV_NONE ? st == DUOFORGE_OK : (st == DUOFORGE_E_INVARIANT && got == want);
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  state %s: %s (%s), expected %s\n", what, duoforge_status_name(st), dfi_invariant_name(got),
                dfi_invariant_name(want));
    }
}

/* A decoded state: the bytes of `b` (as they are, even if the context's
 * invariants reject them) decode to `want`, with the invariant named when the
 * decode refuses. */
static void expect_decode(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, duoforge_status want,
                          dfi_invariant want_inv, const char *what)
{
    uint8_t bytes[DUOFORGE_STATE_V3_ENCODED_SIZE];
    dfi_encode_unchecked(b, bytes);
    uint8_t *in = df_heap_copy(bytes, sizeof bytes);
    struct duoforge_battle decoded;
    memset(&decoded, 0, sizeof decoded);
    dfi_invariant inv = DFI_INV_NONE;
    const duoforge_status st = dfi_decode_state(ctx, in, sizeof bytes, &decoded, &inv);
    if (!DF_CHECK(t, st == want && inv == want_inv)) {
        fprintf(stderr, "  decode %s: %s (%s), expected %s (%s)\n", what, duoforge_status_name(st),
                dfi_invariant_name(inv), duoforge_status_name(want), dfi_invariant_name(want_inv));
    }
    df_free(in);
}

static dfi_support_manifest full_manifest(void)
{
    dfi_support_manifest m;
    memset(&m, 1, sizeof m);
    return m;
}

/* True iff the forme learns the pool move (the bit of dfi_pool_forme_legal). */
static bool forme_learns(uint32_t forme, uint32_t move)
{
    return (((uint32_t)dfi_pool_forme_legal[forme].learnable[move / 8u] >> (move % 8u)) & 1u) != 0u;
}

/* A member of base forme `forme` after the template `tpl` (nature, Stat Points): the ability id, the item (1 + its
 * id, 0 none), `count` moves, and the gender that the forme's rule allows (male for a 50/50 forme, as the owner
 * states them). */
static duoforge_member_setup member_of(const duoforge_member_setup *tpl, uint32_t forme, uint32_t ability,
                                       uint32_t item, uint32_t count, const uint32_t *moves)
{
    duoforge_member_setup m = *tpl;
    const uint32_t rule = dfi_pool_formes[forme].gender_rule;
    m.species_id = forme;
    m.gender = rule == DFI_GENDER_RULE_FEMALE ? DUOFORGE_GENDER_FEMALE
               : rule == DFI_GENDER_RULE_NONE ? DUOFORGE_GENDER_NONE
                                              : DUOFORGE_GENDER_MALE;
    m.ability = ability + 1u;
    m.item = item;
    m.move_count = count;
    memset(m.moves, 0, sizeof m.moves);
    for (uint32_t k = 0u; k < count; ++k) {
        m.moves[k].move_id = moves[k];
    }
    return m;
}

/* The two team-selection choices: both sides bring their first four members. */
static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* Turn 1 of the reference teams' leads (Wood Hammer and Brave Bird into the
 * foes, Weather Ball and Leech Life into them): valid for any items. */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    static const uint8_t plan[2][2][2] = {{{0u, 2u}, {0u, 3u}}, {{0u, 0u}, {0u, 1u}}}; /* move slot, target */
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = plan[side][slot][0];
            c->slots[slot].target = plan[side][slot][1];
        }
    }
}

/* The step fails with `want`, and nothing was mutated. */
static void step_expect(df_test *t, const duoforge_context *ctx, duoforge_battle *b,
                        const duoforge_decision_bundle *bd, duoforge_status want, const char *what)
{
    uint8_t before[DUOFORGE_STATE_V3_ENCODED_SIZE];
    uint8_t after[DUOFORGE_STATE_V3_ENCODED_SIZE];
    df_encode(ctx, b, before);
    duoforge_step_result res;
    const duoforge_status st = duoforge_battle_step(ctx, b, bd, &res);
    if (!DF_CHECK(t, st == want)) {
        fprintf(stderr, "  step %s: %s, expected %s\n", what, duoforge_status_name(st), duoforge_status_name(want));
    }
    if (want != DUOFORGE_OK) {
        df_encode(ctx, b, after);
        DF_CHECK_BYTES(t, after, before, sizeof after, what);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_setup");

    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
    duoforge_context *kc = df_make_context(&df_config_team_c);
    duoforge_context *kd = df_make_context(&df_config_team_c_dev);
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kq = df_make_context(&df_config_pool_dev);

    /* Contexts: the canonical bytes carry the kind, the pool counts and the
     * pool table hash (with its family columns); the fingerprint is their
     * SHA-256 and equals the model's. All six combat fingerprints differ. */
    {
        uint8_t bytes[DFI_CONTEXT_BYTES_SIZE];
        uint8_t fp[6][DUOFORGE_DIGEST_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        const duoforge_context *all[6] = {k1, k2, kc, kd, kp, kq};
        for (uint32_t i = 0u; i < 6u; ++i) {
            DF_CHECK(&t, duoforge_context_fingerprint(all[i], fp[i]) == DUOFORGE_OK);
        }
        dfi_context_canonical_bytes(kp, bytes);
        DF_CHECK(&t, bytes[24] == DUOFORGE_DATA_KIND_POOL && bytes[25] == 6u && bytes[26] == 4u &&
                         bytes[27] == DFI_POOL_FORME_COUNT && bytes[28] == 0u && bytes[29] == DFI_POOL_MOVE_COUNT &&
                         bytes[30] == 0u);
        DF_CHECK_BYTES(&t, bytes + DFI_CONTEXT_TABLE_HASH_OFF, dfi_pool_table_hash, DUOFORGE_DIGEST_SIZE,
                       "POOL table hash");
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK_BYTES(&t, sha, fp[4], sizeof sha, "POOL fingerprint = sha256(canonical bytes)");
        dfi_context_canonical_bytes(kq, bytes);
        DF_CHECK(&t, bytes[24] == DUOFORGE_DATA_KIND_POOL_DEV && bytes[27] == DFI_POOL_FORME_COUNT &&
                         bytes[29] == DFI_POOL_MOVE_COUNT);
        DF_CHECK_BYTES(&t, bytes + DFI_CONTEXT_TABLE_HASH_OFF, dfi_pool_table_hash, DUOFORGE_DIGEST_SIZE,
                       "POOL_DEV table hash");
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK_BYTES(&t, sha, fp[5], sizeof sha, "POOL_DEV fingerprint = sha256(canonical bytes)");
        DF_CHECK(&t, df_hex_to_bytes(FP_KP_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp[4], want, sizeof want, "POOL fingerprint (model)");
        DF_CHECK(&t, df_hex_to_bytes(FP_KPD_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp[5], want, sizeof want, "POOL_DEV fingerprint (model)");
        uint32_t same = 0u;
        for (uint32_t i = 0u; i < 6u; ++i) {
            for (uint32_t j = 0u; j < i; ++j) {
                same += memcmp(fp[i], fp[j], DUOFORGE_DIGEST_SIZE) == 0 ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, same, 0u);
        /* The data of the kinds: the pool counts are those of step G2 so
         * far, and the target classes are those of the pool's moves. */
        DF_CHECK_EQ_U64(&t, kp->species_count, DFI_POOL_FORME_COUNT);
        DF_CHECK_EQ_U64(&t, kp->move_count, DFI_POOL_MOVE_COUNT);
        DF_CHECK_EQ_U64(&t, kq->species_count, DFI_POOL_FORME_COUNT);
        DF_CHECK_EQ_U64(&t, kq->move_count, DFI_POOL_MOVE_COUNT);
        uint32_t classes = 0u;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            classes += kp->move_target_classes[i] != dfi_pool_moves[i].target_class ||
                               kq->move_target_classes[i] != dfi_pool_moves[i].target_class
                           ? 1u
                           : 0u;
        }
        DF_CHECK_EQ_U64(&t, classes, 0u);
        DF_CHECK_EQ_U64(&t, kp->move_target_classes[DFI_MOVE_STRUGGLE], 10u);
        DF_CHECK_EQ_U64(&t, kp->move_target_classes[DFI_POOL_MOVE_COUNT], 0u);
        /* The CLOSURE and TEAM_C kinds keep their counts and their hashes. */
        DF_CHECK(&t, k1->species_count == DFI_FORME_COUNT && k1->move_count == DFI_MOVE_COUNT &&
                         kc->species_count == DFI_EXT_FORME_COUNT && kc->move_count == DFI_EXT_MOVE_COUNT);
        DF_CHECK_BYTES(&t, k1->table_hash, dfi_closure_table_hash, DUOFORGE_DIGEST_SIZE, "CLOSURE hash");
        DF_CHECK_BYTES(&t, kc->table_hash, dfi_ext_table_hash, DUOFORGE_DIGEST_SIZE, "TEAM_C hash");
        DF_CHECK_BYTES(&t, kp->table_hash, dfi_pool_table_hash, DUOFORGE_DIGEST_SIZE, "POOL hash");
    }

    /* The config contract is CLOSURE's: no counts, no table; POOL takes over
     * the certified profile (register 6, bring 4), POOL_DEV takes any; kind
     * 8 is the first unknown one. */
    {
        duoforge_context_config c = df_config_pool;
        duoforge_context *out = NULL;
        c.species_count = DFI_POOL_FORME_COUNT;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_pool_dev;
        c.move_count = DFI_POOL_MOVE_COUNT;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_pool;
        c.move_target_classes = df_table_t1;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_pool;
        c.max_roster = 5u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_pool;
        c.brought_count = 3u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_pool_dev;
        c.max_roster = 5u;
        c.brought_count = 3u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_OK && out != NULL);
        duoforge_context_destroy(out);
        out = NULL;
        c = df_config_pool_dev;
        c.data_kind = DUOFORGE_DATA_KIND_POOL_DEV + 1u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        DF_CHECK_EQ_U64(&t, c.data_kind, 8u);
        c.data_kind = 0u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
    }

    /* The kind limits: the pool bounds ids at its own counts, the CLOSURE and
     * TEAM_C kinds at theirs, and POOL has the values of Team C's mechanics. */
    {
        const dfi_kind_limits lp = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL);
        const dfi_kind_limits lq = dfi_kind_limits_of(DUOFORGE_DATA_KIND_POOL_DEV);
        const dfi_kind_limits lc = dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C);
        const dfi_kind_limits l1 = dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE);
        DF_CHECK(&t, lp.forme_count == DFI_POOL_FORME_COUNT && lp.item_count == DFI_POOL_ITEM_COUNT && !lp.dev);
        DF_CHECK(&t, lq.forme_count == DFI_POOL_FORME_COUNT && lq.item_count == DFI_POOL_ITEM_COUNT && lq.dev);
        DF_CHECK(&t, lc.forme_count == DFI_EXT_FORME_COUNT && lc.item_count == DFI_EXT_ITEM_COUNT && !lc.dev);
        DF_CHECK(&t, l1.forme_count == DFI_FORME_COUNT && l1.item_count == DFI_ITEM_COUNT && !l1.dev);
        DF_CHECK(&t, dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE_DEV).dev &&
                         dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C_DEV).dev);
        DF_CHECK(&t, lp.switch_flag_max == lc.switch_flag_max && lp.status_max == lc.status_max &&
                         lp.terrain_max == lc.terrain_max && lp.vol_flags_mask == lc.vol_flags_mask);
        DF_CHECK(&t, lq.switch_flag_max == lc.switch_flag_max && lq.status_max == lc.status_max &&
                         lq.terrain_max == lc.terrain_max && lq.vol_flags_mask == lc.vol_flags_mask);
        DF_CHECK(&t, lp.switch_flag_max == DFI_SWITCH_FLIP_TURN && lp.status_max == DFI_STATUS_PSN &&
                         lp.terrain_max == DFI_TERRAIN_PSYCHIC && l1.switch_flag_max == DFI_SWITCH_FAINTED &&
                         l1.status_max == DFI_STATUS_SLP && l1.terrain_max == DFI_TERRAIN_GRASSY);
    }

    /* Setup rules under POOL are the CLOSURE rules over the pool tables:
     * the real Team C against Team A, legal and supported (every mechanic of
     * the extended tables is marked); out of range under CLOSURE. */
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    duoforge_battle_setup s;
#define FRESH() (s = teams, df_put_team_c(&s.sides[1]))
    FRESH();
    legal(&t, kp, &s, true, "real Team C vs Team A");
    legal(&t, kq, &s, true, "real Team C vs Team A (dev)");
    invalid(&t, k1, &s, "Team C under CLOSURE");
    legal(&t, kc, &s, true, "Team C under TEAM_C");
    legal(&t, kp, &teams, true, "Team A vs Team B under POOL");
    legal(&t, kq, &teams, true, "Team A vs Team B under POOL_DEV");
    /* Register exactly six under POOL, four to six under POOL_DEV. */
    FRESH();
    s.sides[1].member_count = 5u;
    memset(&s.sides[1].members[5], 0, sizeof s.sides[1].members[5]);
    invalid(&t, kp, &s, "five members under POOL");
    legal(&t, kq, &s, true, "five members under POOL_DEV");
    /* The member and side rules. */
    FRESH();
    s.sides[1].members[5].gender = DUOFORGE_GENDER_FEMALE; /* Basculegion: male only */
    invalid(&t, kp, &s, "female Basculegion");
    FRESH();
    s.sides[1].members[2].ability = DFI_ABILITY_AERILATE + 1u; /* the Mega forme's ability */
    invalid(&t, kp, &s, "Salamence with Aerilate");
    FRESH();
    s.sides[1].members[4].moves[0].move_id = DFI_MOVE_CLOSECOMBAT; /* Kingambit does not learn it */
    invalid(&t, kp, &s, "Kingambit with Close Combat");
    FRESH();
    s.sides[1].members[2].species_id = DFI_FORME_SALAMENCEMEGA;
    invalid(&t, kp, &s, "Mega forme set up");
    FRESH();
    s.sides[1].members[2].species_id = DFI_POOL_FORME_COUNT;
    invalid(&t, kp, &s, "species beyond the tables");
    FRESH();
    s.sides[1].members[4].item = DFI_ITEM_SITRUSBERRY + 1u; /* Incineroar holds it */
    invalid(&t, kp, &s, "Item Clause");
    FRESH();
    s.sides[1].members[0].ability = 0u;
    invalid(&t, kp, &s, "No Ability under POOL");
    legal(&t, kq, &s, true, "No Ability under POOL_DEV");
    /* Any table item on any member, as in the closure. */
    s = teams;
    s.sides[0] = teams.sides[1];
    s.sides[1] = teams.sides[0];
    s.sides[0].members[2].item = DFI_ITEM_CHOICESCARF + 1u; /* Archaludon, Leftovers before */
    legal(&t, kp, &s, true, "Choice Scarf on Archaludon");

    /* The item bound is the pool's own: the last pool item is in range, the
     * next one is not. Every id the pool adds is out of range under the
     * CLOSURE and TEAM_C kinds, whose bounds are 11 and 16 items. */
    s = teams;
    s.sides[0].members[3].item = DFI_POOL_ITEM_COUNT; /* Floettite */
    legal(&t, kp, &s, false, "the last pool item (Floettite, unmarked)");
    legal(&t, kq, &s, false, "the last pool item (dev)");
    invalid(&t, kc, &s, "the last pool item under TEAM_C");
    s.sides[0].members[3].item = DFI_POOL_ITEM_COUNT + 1u;
    invalid(&t, kp, &s, "an item beyond the pool");
    invalid(&t, kq, &s, "an item beyond the pool (dev)");
    s = teams;
    s.sides[0].members[0].item = DFI_ITEM_BLACKBELT + 1u; /* the first pool item */
    legal(&t, kp, &s, true, "the first pool item");
    invalid(&t, k1, &s, "a pool item under CLOSURE");
    invalid(&t, k2, &s, "a pool item under CLOSURE_DEV");
    invalid(&t, kc, &s, "a pool item under TEAM_C");
    invalid(&t, kd, &s, "a pool item under TEAM_C_DEV");
    s.sides[0].members[0].item = DFI_ITEM_CHOICESCARF + 1u; /* the last extended item */
    invalid(&t, k1, &s, "an extended item under CLOSURE");
    legal(&t, kc, &s, true, "an extended item under TEAM_C");
    legal(&t, kp, &s, true, "an extended item under POOL");
    /* A new ability is legal only for a forme that may have it: Rillaboom
     * may have Overgrow (so that setup is legal and, as Overgrow is not
     * marked, E_UNSUPPORTED), and none of the other four. Under the CLOSURE
     * and TEAM_C kinds Rillaboom has Grassy Surge only. */
    {
        static const struct {
            uint32_t ability;
            bool legal_for_rillaboom;
            const char *what;
        } added[] = {
            {DFI_ABILITY_PIXILATE, false, "Pixilate"}, {DFI_ABILITY_REFRIGERATE, false, "Refrigerate"},
            {DFI_ABILITY_OVERGROW, true, "Overgrow"},  {DFI_ABILITY_TORRENT, false, "Torrent"},
            {DFI_ABILITY_SWARM, false, "Swarm"},
        };
        for (size_t i = 0u; i < sizeof added / sizeof added[0]; ++i) {
            s = teams;
            s.sides[0].members[0].ability = added[i].ability + 1u;
            if (added[i].legal_for_rillaboom) {
                legal(&t, kp, &s, false, "Rillaboom with Overgrow (legal, unmarked)");
                legal(&t, kq, &s, false, "Rillaboom with Overgrow (legal, unmarked, dev)");
            } else {
                invalid(&t, kp, &s, added[i].what);
                invalid(&t, kq, &s, added[i].what);
            }
            invalid(&t, kc, &s, "a pool ability under TEAM_C");
            invalid(&t, kd, &s, "a pool ability under TEAM_C_DEV");
            invalid(&t, k1, &s, "a pool ability under CLOSURE");
            invalid(&t, k2, &s, "a pool ability under CLOSURE_DEV");
        }
    }

    /* The set rule (decision 0015 section 2): under the POOL kinds a member's
     * moves are ones its forme learns and its ability one of its legal
     * abilities, as the real teams use them; the frozen kinds keep the set. */
    {
        /* Milotic of Team A with Protect for Hypnosis, and Golisopod of Team B
         * with Sucker Punch for Drill Run: moves of the tables that are not
         * in the set of their forme. Both are 50/50 species, so male as the
         * owner states them; both mechanics are marked. */
        s = teams;
        s.sides[0].members[2].gender = DUOFORGE_GENDER_MALE;
        s.sides[0].members[2].moves[3].move_id = DFI_MOVE_PROTECT;
        legal(&t, kp, &s, true, "Milotic with Protect (learned, not in the set)");
        legal(&t, kq, &s, true, "Milotic with Protect (dev)");
        invalid(&t, k1, &s, "Milotic with Protect under CLOSURE");
        invalid(&t, k2, &s, "Milotic with Protect under CLOSURE_DEV");
        invalid(&t, kc, &s, "Milotic with Protect under TEAM_C");
        invalid(&t, kd, &s, "Milotic with Protect under TEAM_C_DEV");
        s = teams;
        s.sides[1].members[1].gender = DUOFORGE_GENDER_MALE;
        s.sides[1].members[1].moves[2].move_id = DFI_MOVE_SUCKERPUNCH;
        legal(&t, kp, &s, true, "Golisopod with Sucker Punch");
        legal(&t, kq, &s, true, "Golisopod with Sucker Punch (dev)");
        invalid(&t, k1, &s, "Golisopod with Sucker Punch under CLOSURE");
        invalid(&t, kc, &s, "Golisopod with Sucker Punch under TEAM_C");
        invalid(&t, kd, &s, "Golisopod with Sucker Punch under TEAM_C_DEV");
        /* One move is enough, and a move the forme does not learn is not. */
        s = teams;
        s.sides[0].members[2].move_count = 1u;
        s.sides[0].members[2].moves[0].move_id = DFI_MOVE_PROTECT;
        for (uint32_t k = 1u; k < 4u; ++k) {
            s.sides[0].members[2].moves[k].move_id = 0u;
        }
        legal(&t, kp, &s, true, "one learned move");
        s.sides[0].members[2].moves[0].move_id = DFI_MOVE_ELECTROSHOT; /* Archaludon's */
        invalid(&t, kp, &s, "Milotic with Electro Shot");
        invalid(&t, kq, &s, "Milotic with Electro Shot (dev)");
        s = teams;
        s.sides[0].members[2].moves[3].move_id = DFI_MOVE_STRUGGLE; /* nobody learns it */
        invalid(&t, kp, &s, "Struggle as a move");
        s.sides[0].members[2].moves[3].move_id = DFI_POOL_MOVE_COUNT; /* a move beyond the tables */
        invalid(&t, kp, &s, "a move beyond the tables");
        s.sides[0].members[2].moves[3].move_id = 0xFFFFFFFFu;
        invalid(&t, kp, &s, "move id 2^32 - 1");
        s = teams;
        s.sides[0].members[2].moves[3].move_id = DFI_MOVE_COIL; /* a repeated move */
        invalid(&t, kp, &s, "a repeated move");
        s = teams;
        s.sides[0].members[2].moves[3].move_id = DFI_MOVE_PROTECT;
        s.sides[0].members[2].moves[3].pp_max = 8u; /* derived by the engine */
        s.sides[0].members[2].gender = DUOFORGE_GENDER_MALE;
        invalid(&t, kp, &s, "pp_max given");
        /* Kingambit (Team C) learns Swords Dance, not Fake Out. */
        FRESH();
        s.sides[1].members[4].moves[1].move_id = DFI_MOVE_SWORDSDANCE; /* Kingambit learns it */
        legal(&t, kp, &s, true, "Kingambit with Swords Dance");
        s.sides[1].members[4].moves[1].move_id = DFI_MOVE_FAKEOUT;
        invalid(&t, kp, &s, "Kingambit with Fake Out");
        /* Incineroar may have Blaze as well as Intimidate: Blaze is marked, so
         * that is legal and supported under POOL, and the set's ability only
         * under TEAM_C. */
        FRESH();
        s.sides[1].members[1].ability = DFI_ABILITY_BLAZE + 1u;
        legal(&t, kp, &s, true, "Incineroar with Blaze (legal, marked)");
        legal(&t, kq, &s, true, "Incineroar with Blaze (dev)");
        invalid(&t, kc, &s, "Incineroar with Blaze under TEAM_C");
        invalid(&t, kd, &s, "Incineroar with Blaze under TEAM_C_DEV");
        s.sides[1].members[1].ability = DFI_ABILITY_DROUGHT + 1u; /* Charizard-Mega-Y's: not Incineroar's */
        invalid(&t, kp, &s, "Incineroar with Drought");
        s.sides[1].members[1].ability = DFI_ABILITY_INTIMIDATE + 1u; /* its set's */
        legal(&t, kp, &s, true, "Incineroar with Intimidate");
        /* No Ability: under the DEV kind only, with any learned move. */
        s.sides[1].members[1].ability = 0u;
        invalid(&t, kp, &s, "No Ability under POOL");
        s.sides[1].members[1].moves[2].move_id = DFI_MOVE_SNARL; /* learned, not in the set */
        legal(&t, kq, &s, true, "No Ability under POOL_DEV with a learned move");
        /* A Mega-capable base forme takes the base forme's moves: Staraptor
         * with Helping Hand for Tailwind. Mega Evolution keeps them. */
        s = teams;
        s.sides[0].members[1].moves[2].move_id = DFI_MOVE_HELPINGHAND;
        legal(&t, kp, &s, true, "Staraptor with Helping Hand");
        invalid(&t, k1, &s, "Staraptor with Helping Hand under CLOSURE");
        duoforge_battle *w = df_make_battle(kp, &s);
        duoforge_decision_bundle bd;
        team_bundle(&bd, w);
        step_expect(&t, kp, w, &bd, DUOFORGE_OK, "team selection with Helping Hand");
        turn_bundle(&bd, w);
        bd.responses[0].slots[1].mega = 1u; /* Staraptor mega evolves into Brave Bird */
        step_expect(&t, kp, w, &bd, DUOFORGE_OK, "Mega Evolution with a learned move");
        DF_CHECK(&t, w->sides[0].members[1].is_mega == 1u && duoforge_battle_check(kp, w) == DUOFORGE_OK);
        duoforge_battle_destroy(w);
        /* A legal ability that is not marked stops at the gate, in the
         * state as well: Rillaboom with Overgrow. */
        s = teams;
        s.sides[0].members[0].ability = DFI_ABILITY_OVERGROW + 1u;
        w = NULL;
        DF_CHECK(&t, dfi_battle_create_ungated(kp, &s, &w) == DUOFORGE_OK && w != NULL);
        if (w != NULL) {
            expect_inv(&t, kp, w, DFI_INV_NONE, "Overgrow on Rillaboom");
            expect_decode(&t, kp, w, DUOFORGE_OK, DFI_INV_NONE, "Overgrow on Rillaboom");
            team_bundle(&bd, w);
            step_expect(&t, kp, w, &bd, DUOFORGE_E_UNSUPPORTED, "team selection with Overgrow");
            duoforge_battle_destroy(w);
        }
    }

    /* Step G2 (docs/research/expansion/data/team_gaps.json): the formes Pelipper, Arcanine-Hisui, Annihilape and
     * Floette-Eternal under the set rule, and the 22 new moves behind the gate. The moves are all unmarked, so a
     * setup that has one is E_UNSUPPORTED after all validation; a species is complete with its base data, so a
     * Pelipper whose ability, item and moves are marked is a supported setup. Team B's lead is replaced. */
    {
        const duoforge_member_setup *tpl = &teams.sides[1].members[0];
        /* Every new move: a learner with a legal ability that is marked, with no item, on a side where it does not
         * clash with the Species Clause. The gate function with a fully marked manifest accepts the setup (the
         * control), and refuses it when only that move is unmarked, as the real manifest does. */
        for (uint32_t mv = DFI_EXT_MOVE_COUNT; mv < DFI_POOL_MOVE_COUNT; ++mv) {
            bool found = false;
            for (uint32_t pass = 0u; pass < 2u && !found; ++pass) {
                const uint32_t side = 1u - pass;
                for (uint32_t forme = 0u; forme < DFI_POOL_FORME_COUNT && !found; ++forme) {
                    const dfi_forme_legal *l = &dfi_pool_forme_legal[forme];
                    uint32_t ability = DFI_CLOSURE_NONE; /* a legal ability that is marked */
                    for (uint32_t k = 0u; k < l->ability_count; ++k) {
                        ability = ability == DFI_CLOSURE_NONE && dfi_support.abilities[l->abilities[k]] != 0u
                                      ? l->abilities[k]
                                      : ability;
                    }
                    if (dfi_pool_formes[forme].is_mega != 0u || !forme_learns(forme, mv) || ability == DFI_CLOSURE_NONE) {
                        continue;
                    }
                    bool clash = false;
                    for (uint32_t k = 1u; k < teams.sides[side].member_count; ++k) {
                        clash = clash || dfi_pool_formes[teams.sides[side].members[k].species_id].dex_num ==
                                             dfi_pool_formes[forme].dex_num;
                    }
                    if (clash) {
                        continue;
                    }
                    found = true;
                    s = teams;
                    s.sides[side].members[0] = member_of(&s.sides[side].members[0], forme, ability, 0u, 1u, &mv);
                    legal(&t, kp, &s, false, "a new move (unmarked)");
                    legal(&t, kq, &s, false, "a new move (unmarked, dev)");
                    invalid(&t, kc, &s, "a pool forme under TEAM_C");
                    const dfi_support_manifest full = full_manifest();
                    DF_CHECK(&t, dfi_closure_setup_supported(&full, &s));
                    dfi_support_manifest without = full;
                    without.moves[mv] = 0u;
                    DF_CHECK(&t, !dfi_closure_setup_supported(&without, &s));
                    DF_CHECK(&t, !dfi_closure_setup_supported(&dfi_support, &s));
                }
            }
            if (!DF_CHECK(&t, found)) {
                fprintf(stderr, "  no learner of the new move %u\n", mv);
            }
        }

        /* Pelipper: Drizzle only (Keen Eye and Rain Dish are not pool abilities), every move marked and Mystic Water
         * (Politoed's, who is replaced): a supported setup. Wide Guard is the one unmarked move of its usual set. */
        static const uint32_t pelipper_moves[4] = {DFI_MOVE_WEATHERBALL, DFI_MOVE_HURRICANE, DFI_MOVE_TAILWIND,
                                                   DFI_MOVE_PROTECT};
        s = teams;
        s.sides[1].members[0] = member_of(tpl, DFI_FORME_PELIPPER, DFI_ABILITY_DRIZZLE, DFI_ITEM_MYSTICWATER + 1u, 4u,
                                          pelipper_moves);
        legal(&t, kp, &s, true, "Pelipper with Drizzle and marked moves");
        legal(&t, kq, &s, true, "Pelipper (dev)");
        invalid(&t, k1, &s, "Pelipper under CLOSURE");
        invalid(&t, kc, &s, "Pelipper under TEAM_C");
        s.sides[1].members[0].moves[3].move_id = DFI_MOVE_WIDEGUARD;
        legal(&t, kp, &s, false, "Pelipper with Wide Guard (legal, unmarked)");
        s.sides[1].members[0].moves[3].move_id = DFI_MOVE_PROTECT;
        s.sides[1].members[0].ability = DFI_ABILITY_OVERGROW + 1u;
        invalid(&t, kp, &s, "Pelipper with Overgrow");
        s.sides[1].members[0].ability = DFI_ABILITY_DRIZZLE + 1u;
        s.sides[1].members[0].moves[3].move_id = DFI_MOVE_ELECTROSHOT; /* Archaludon's: Pelipper does not learn it */
        invalid(&t, kp, &s, "Pelipper with Electro Shot");

        /* Arcanine-Hisui: Intimidate, Flash Fire and Rock Head (the last unmarked); not Defiant. */
        static const uint32_t arcanine_moves[4] = {DFI_MOVE_FLAREBLITZ, DFI_MOVE_PROTECT, DFI_MOVE_HEATWAVE,
                                                   DFI_MOVE_HYPERVOICE};
        static const struct {
            uint32_t ability;
            int supported; /* 1 supported, 0 legal but unmarked, -1 not legal */
            const char *what;
        } arcanine[] = {
            {DFI_ABILITY_INTIMIDATE, 1, "Arcanine-Hisui with Intimidate"},
            {DFI_ABILITY_FLASHFIRE, 1, "Arcanine-Hisui with Flash Fire"},
            {DFI_ABILITY_ROCKHEAD, 0, "Arcanine-Hisui with Rock Head (unmarked)"},
            {DFI_ABILITY_DEFIANT, -1, "Arcanine-Hisui with Defiant"},
        };
        for (size_t i = 0u; i < sizeof arcanine / sizeof arcanine[0]; ++i) {
            s = teams;
            s.sides[1].members[0] = member_of(tpl, DFI_FORME_ARCANINEHISUI, arcanine[i].ability,
                                              DFI_ITEM_MYSTICWATER + 1u, 4u, arcanine_moves);
            if (arcanine[i].supported < 0) {
                invalid(&t, kp, &s, arcanine[i].what);
            } else {
                legal(&t, kp, &s, arcanine[i].supported == 1, arcanine[i].what);
            }
        }
        /* Focus Sash is unmarked, and a genderless Arcanine-Hisui is not legal. */
        s = teams;
        s.sides[1].members[0] = member_of(tpl, DFI_FORME_ARCANINEHISUI, DFI_ABILITY_INTIMIDATE, DFI_ITEM_FOCUSSASH + 1u,
                                          4u, arcanine_moves);
        legal(&t, kp, &s, false, "Arcanine-Hisui with a Focus Sash");
        s.sides[1].members[0].item = DFI_ITEM_EXPERTBELT + 1u;
        legal(&t, kp, &s, false, "Arcanine-Hisui with an Expert Belt");
        s.sides[1].members[0].item = 0u;
        legal(&t, kp, &s, true, "Arcanine-Hisui without an item");
        s.sides[1].members[0].gender = DUOFORGE_GENDER_NONE;
        invalid(&t, kp, &s, "genderless Arcanine-Hisui");

        /* Annihilape: Defiant (marked), Choice Scarf (marked); Ice Punch, Shadow Claw and U-turn are unmarked. */
        static const uint32_t annihilape_moves[4] = {DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_SHADOWBALL,
                                                     DFI_MOVE_HELPINGHAND};
        s = teams;
        s.sides[1].members[0] = member_of(tpl, DFI_FORME_ANNIHILAPE, DFI_ABILITY_DEFIANT, DFI_ITEM_CHOICESCARF + 1u, 4u,
                                          annihilape_moves);
        legal(&t, kp, &s, true, "Annihilape with marked moves");
        s.sides[1].members[0].moves[3].move_id = DFI_MOVE_ICEPUNCH;
        legal(&t, kp, &s, false, "Annihilape with Ice Punch (unmarked)");
        s.sides[1].members[0].moves[3].move_id = DFI_MOVE_FLAREBLITZ; /* Annihilape does not learn it */
        invalid(&t, kp, &s, "Annihilape with Flare Blitz");

        /* Floette-Eternal is female only; its Mega forme is reached in battle, never set up. Flower Veil, Floettite
         * and the Mega's Fairy Aura are all unmarked, so the setup is E_UNSUPPORTED until each is. */
        static const uint32_t floette_moves[2] = {DFI_MOVE_PROTECT, DFI_MOVE_DAZZLINGGLEAM};
        s = teams;
        s.sides[1].members[0] = member_of(tpl, DFI_FORME_FLOETTEETERNAL, DFI_ABILITY_FLOWERVEIL,
                                          DFI_ITEM_FLOETTITE + 1u, 2u, floette_moves);
        DF_CHECK_EQ_U64(&t, s.sides[1].members[0].gender, DUOFORGE_GENDER_FEMALE);
        legal(&t, kp, &s, false, "Floette-Eternal with Floettite (legal, unmarked)");
        {
            dfi_support_manifest m = full_manifest();
            DF_CHECK(&t, dfi_closure_setup_supported(&m, &s));
            m.abilities[DFI_ABILITY_FAIRYAURA] = 0u; /* the ability the Mega forme brings */
            DF_CHECK(&t, !dfi_closure_setup_supported(&m, &s));
            m = full_manifest();
            m.items[DFI_ITEM_FLOETTITE] = 0u;
            DF_CHECK(&t, !dfi_closure_setup_supported(&m, &s));
            m = full_manifest();
            m.abilities[DFI_ABILITY_FLOWERVEIL] = 0u;
            DF_CHECK(&t, !dfi_closure_setup_supported(&m, &s));
        }
        s.sides[1].members[0].gender = DUOFORGE_GENDER_MALE;
        invalid(&t, kp, &s, "male Floette-Eternal");
        s.sides[1].members[0].gender = DUOFORGE_GENDER_FEMALE;
        s.sides[1].members[0].species_id = DFI_FORME_FLOETTEMEGA;
        invalid(&t, kp, &s, "Floette-Mega set up");
        s.sides[1].members[0].species_id = DFI_FORME_FLOETTEETERNAL;
        s.sides[1].members[0].ability = DFI_ABILITY_FAIRYAURA + 1u; /* the Mega's ability, not the base forme's */
        invalid(&t, kp, &s, "Floette-Eternal with Fairy Aura");
        s.sides[1].members[0].ability = DFI_ABILITY_FLOWERVEIL + 1u;

        /* The states of the new formes are valid in a POOL state, and decode back. */
        s = teams;
        s.sides[1].members[0] = member_of(tpl, DFI_FORME_FLOETTEETERNAL, DFI_ABILITY_FLOWERVEIL,
                                          DFI_ITEM_FLOETTITE + 1u, 2u, floette_moves);
        s.sides[1].members[1] = member_of(tpl, DFI_FORME_ANNIHILAPE, DFI_ABILITY_DEFIANT, DFI_ITEM_CHOICESCARF + 1u, 4u,
                                          annihilape_moves);
        duoforge_battle *w = NULL;
        duoforge_decision_bundle bd;
        DF_CHECK(&t, dfi_battle_create_ungated(kp, &s, &w) == DUOFORGE_OK && w != NULL);
        if (w != NULL) {
            expect_inv(&t, kp, w, DFI_INV_NONE, "Floette-Eternal and Annihilape in a POOL state");
            expect_decode(&t, kp, w, DUOFORGE_OK, DFI_INV_NONE, "Floette-Eternal and Annihilape");
            DF_CHECK_EQ_U64(&t, w->sides[1].members[0].mega_capable, 1u);
            DF_CHECK_EQ_U64(&t, w->sides[1].members[0].moves[1].pp_max, dfi_pool_moves[DFI_MOVE_DAZZLINGGLEAM].pp_max);
            team_bundle(&bd, w);
            step_expect(&t, kp, w, &bd, DUOFORGE_E_UNSUPPORTED, "team selection with Floettite");
            duoforge_battle_destroy(w);
        }
    }

    /* The gate. A new item is marked since step P2: one member per family
     * is legal and supported under POOL and POOL_DEV, and E_INVALID_ARGUMENT
     * under every other kind (above). */
    {
        static const struct {
            uint32_t side, member, item;
            const char *what;
        } items[] = {
            {0u, 0u, DFI_ITEM_BLACKBELT, "a type booster (Black Belt)"},
            {0u, 5u, DFI_ITEM_TWISTEDSPOON, "a type booster (Twisted Spoon)"},
            {0u, 5u, DFI_ITEM_OCCABERRY, "a resist berry (Occa Berry)"},
            {1u, 2u, DFI_ITEM_CHILANBERRY, "the Normal resist berry (Chilan Berry)"},
            {1u, 3u, DFI_ITEM_YACHEBERRY, "a resist berry (Yache Berry)"},
        };
        for (size_t i = 0u; i < sizeof items / sizeof items[0]; ++i) {
            s = teams;
            s.sides[items[i].side].members[items[i].member].item = items[i].item + 1u;
            legal(&t, kp, &s, true, items[i].what);
            legal(&t, kq, &s, true, items[i].what);
            invalid(&t, kc, &s, items[i].what);
        }
        /* After all validation: another fault is INVALID_ARGUMENT, not UNSUPPORTED
         * (here with an unmarked ability, Rillaboom with Overgrow). */
        s = teams;
        s.sides[0].members[0].ability = DFI_ABILITY_OVERGROW + 1u;
        s.sides[0].members[5].gender = DUOFORGE_GENDER_MALE; /* Gholdengo is genderless */
        invalid(&t, kp, &s, "an unmarked ability and a gender fault");
        s = teams;
        s.sides[0].members[0].item = DFI_ITEM_BLACKBELT + 1u;
        s.sides[0].members[1].item = DFI_ITEM_BLACKBELT + 1u; /* Item Clause */
        invalid(&t, kp, &s, "a pool item twice");
        /* The same members with their original items pass. */
        s = teams;
        legal(&t, kp, &s, true, "the same teams without the pool item");

        /* The abilities: only Rillaboom may have a new one through the API
         * (Overgrow, above); the gate function itself rejects each of the
         * five: no mark, no support, with the full manifest as the control. */
        static const uint32_t added[] = {DFI_ABILITY_PIXILATE, DFI_ABILITY_REFRIGERATE, DFI_ABILITY_OVERGROW,
                                         DFI_ABILITY_TORRENT, DFI_ABILITY_SWARM};
        for (size_t i = 0u; i < sizeof added / sizeof added[0]; ++i) {
            s = teams;
            s.sides[0].members[0].ability = added[i] + 1u;
            const dfi_support_manifest full = full_manifest();
            DF_CHECK(&t, dfi_closure_setup_supported(&full, &s));
            DF_CHECK(&t, !dfi_closure_setup_supported(&dfi_support, &s));
            DF_CHECK_EQ_U64(&t, dfi_support.abilities[added[i]], 0u);
        }
        /* An item: marked, so supported; an unmarked one (the manifest
         * copied and edited, for every new id) is gone. */
        for (uint32_t id = DFI_EXT_ITEM_COUNT; id < DFI_POOL_ITEM_COUNT; ++id) {
            s = teams;
            s.sides[0].members[0].item = id + 1u;
            DF_CHECK(&t, dfi_closure_setup_supported(&dfi_support, &s));
            dfi_support_manifest unmarked = dfi_support;
            unmarked.items[id] = 0u;
            DF_CHECK(&t, !dfi_closure_setup_supported(&unmarked, &s));
        }
        /* The prefix items keep their marks. */
        for (uint32_t id = 0u; id < DFI_EXT_ITEM_COUNT; ++id) {
            s = teams;
            s.sides[0].members[0].item = id + 1u;
            DF_CHECK(&t, dfi_closure_setup_supported(&dfi_support, &s));
        }
    }

    /* The step runs the same gate on the battle: a state that holds a pool
     * item runs (it is marked), and one that holds an unmarked ability is
     * E_UNSUPPORTED at every step, atomically; the same step of the state
     * without it runs. */
    {
        s = teams;
        s.sides[0].members[0].item = DFI_ITEM_OCCABERRY + 1u;
        duoforge_battle *b = NULL;
        DF_CHECK(&t, dfi_battle_create_ungated(kp, &s, &b) == DUOFORGE_OK && b != NULL);
        if (b != NULL) {
            expect_inv(&t, kp, b, DFI_INV_NONE, "pool item in a POOL state");
            duoforge_decision_bundle bd;
            team_bundle(&bd, b);
            step_expect(&t, kp, b, &bd, DUOFORGE_OK, "team selection with a resist berry");
            duoforge_battle_destroy(b);
        }
        /* At a TURN boundary: the gate runs again at the start of the turn. */
        duoforge_battle *w = df_make_battle(kp, &teams);
        duoforge_decision_bundle bd;
        team_bundle(&bd, w);
        step_expect(&t, kp, w, &bd, DUOFORGE_OK, "team selection");
        DF_CHECK(&t, w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        duoforge_battle *x = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, w, &x) == DUOFORGE_OK && x != NULL);
        if (x != NULL) {
            x->sides[0].members[3].item = DFI_ITEM_SOFTSAND + 1u; /* a booster on the bench */
            expect_inv(&t, kp, x, DFI_INV_NONE, "pool item at a TURN boundary");
            turn_bundle(&bd, x);
            step_expect(&t, kp, x, &bd, DUOFORGE_OK, "turn with a type booster on the bench");
            duoforge_battle_destroy(x);
        }
        DF_CHECK(&t, duoforge_battle_clone(kp, w, &x) == DUOFORGE_OK && x != NULL);
        if (x != NULL) {
            x->sides[0].members[0].ability = DFI_ABILITY_OVERGROW + 1u; /* Rillaboom, a lead */
            expect_inv(&t, kp, x, DFI_INV_NONE, "Overgrow at a TURN boundary");
            turn_bundle(&bd, x);
            step_expect(&t, kp, x, &bd, DUOFORGE_E_UNSUPPORTED, "turn with an unmarked ability");
            duoforge_battle_destroy(x);
        }
        turn_bundle(&bd, w);
        step_expect(&t, kp, w, &bd, DUOFORGE_OK, "the same turn without the pool item");
        duoforge_battle_destroy(w);
    }

    /* A pool id under the CLOSURE and TEAM_C kinds: out of range in a state
     * (the member invariant), and so in a decoded one (MALFORMED); the same
     * state is valid under POOL. */
    {
        const duoforge_context *kinds[] = {k1, k2, kc, kd};
        for (size_t i = 0u; i < sizeof kinds / sizeof kinds[0]; ++i) {
            duoforge_battle *w = df_make_battle(kinds[i], &teams);
            expect_inv(&t, kinds[i], w, DFI_INV_NONE, "as built");
            w->sides[0].members[3].item = DFI_ITEM_BLACKBELT + 1u;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "a pool item");
            expect_decode(&t, kinds[i], w, DUOFORGE_E_MALFORMED, DFI_INV_MEMBER_EXTRA, "a pool item");
            w->sides[0].members[3].item = DFI_POOL_ITEM_COUNT; /* the last pool item */
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "the last pool item");
            w->sides[0].members[3].item = (uint8_t)teams.sides[0].members[3].item;
            w->sides[0].members[3].ability = (uint8_t)(DFI_ABILITY_TORRENT + 1u);
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "a pool ability");
            duoforge_battle_destroy(w);
        }
        /* Under POOL the item is in range (even unmarked, as a state), one
         * past the pool is not, and the ability stays the forme's own. */
        duoforge_battle *w = df_make_battle(kp, &teams);
        w->sides[0].members[3].item = DFI_ITEM_BLACKBELT + 1u;
        expect_inv(&t, kp, w, DFI_INV_NONE, "a pool item under POOL");
        expect_decode(&t, kp, w, DUOFORGE_OK, DFI_INV_NONE, "a pool item under POOL");
        w->sides[0].members[3].item = DFI_POOL_ITEM_COUNT;
        expect_inv(&t, kp, w, DFI_INV_NONE, "the last pool item under POOL");
        w->sides[0].members[3].item = DFI_POOL_ITEM_COUNT + 1u;
        expect_inv(&t, kp, w, DFI_INV_MEMBER_EXTRA, "an item beyond the pool");
        expect_decode(&t, kp, w, DUOFORGE_E_MALFORMED, DFI_INV_MEMBER_EXTRA, "an item beyond the pool");
        w->sides[0].members[3].item = (uint8_t)teams.sides[0].members[3].item;
        w->sides[0].members[3].ability = (uint8_t)(DFI_ABILITY_TORRENT + 1u);
        expect_inv(&t, kp, w, DFI_INV_MEMBER_EXTRA, "a pool ability on a forme without it");
        w->sides[0].members[3].ability = (uint8_t)teams.sides[0].members[3].ability;
        /* A consumed pool item is as any consumed item. */
        w->sides[0].members[3].item = DFI_ITEM_OCCABERRY + 1u;
        w->sides[0].members[3].item_consumed = 1u;
        expect_inv(&t, kp, w, DFI_INV_NONE, "a consumed pool item");
        duoforge_battle_destroy(w);
        /* A Species of the pool beyond its 28 formes is out of range. */
        w = df_make_battle(kp, &teams);
        w->sides[0].members[0].species_id = (uint16_t)DFI_POOL_FORME_COUNT;
        expect_inv(&t, kp, w, DFI_INV_SPECIES_RANGE, "a species beyond the pool");
        duoforge_battle_destroy(w);
    }

    /* The member invariant follows the set rule: a move the forme learns is
     * valid in a POOL state and not in the CLOSURE and TEAM_C ones; a move it
     * does not learn is out of range everywhere; a legal ability outside the
     * set is valid under POOL only (member 3 of Team A, Ceruledge, and the
     * Incineroar of Team C). */
    {
        const dfi_move_data *protect = &dfi_pool_moves[DFI_MOVE_PROTECT];
        const dfi_move_data *electro = &dfi_pool_moves[DFI_MOVE_ELECTROSHOT];
        duoforge_battle_setup mixed;
        const duoforge_context *kinds[] = {k1, k2, kc, kd, kp, kq};
        for (size_t i = 0u; i < sizeof kinds / sizeof kinds[0]; ++i) {
            const bool pool_kind = kinds[i] == kp || kinds[i] == kq;
            duoforge_battle *w = df_make_battle(kinds[i], &teams);
            dfi_member *milotic = &w->sides[0].members[2];
            const uint8_t was_move = (uint8_t)milotic->moves[3].move_id;
            const uint8_t was_pp = milotic->moves[3].pp_max;
            milotic->moves[3].move_id = DFI_MOVE_PROTECT;
            milotic->moves[3].pp_max = protect->pp_max;
            milotic->moves[3].pp = protect->pp_max;
            expect_inv(&t, kinds[i], w, pool_kind ? DFI_INV_NONE : DFI_INV_MEMBER_EXTRA, "Protect on Milotic");
            expect_decode(&t, kinds[i], w, pool_kind ? DUOFORGE_OK : DUOFORGE_E_MALFORMED,
                          pool_kind ? DFI_INV_NONE : DFI_INV_MEMBER_EXTRA, "Protect on Milotic");
            milotic->moves[3].move_id = DFI_MOVE_ELECTROSHOT;
            milotic->moves[3].pp_max = electro->pp_max;
            milotic->moves[3].pp = electro->pp_max;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "Electro Shot on Milotic");
            milotic->moves[3].move_id = DFI_MOVE_STRUGGLE;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "Struggle as a move");
            milotic->moves[3].move_id = DFI_MOVE_COIL; /* a repeated move */
            milotic->moves[3].pp_max = milotic->moves[1].pp_max;
            milotic->moves[3].pp = milotic->moves[1].pp_max;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "a repeated move");
            milotic->moves[3].move_id = was_move;
            milotic->moves[3].pp_max = was_pp;
            milotic->moves[3].pp = was_pp;
            expect_inv(&t, kinds[i], w, DFI_INV_NONE, "restored");
            /* PP is a function of the move: Protect with another maximum. */
            milotic->moves[3].move_id = DFI_MOVE_PROTECT;
            milotic->moves[3].pp_max = (uint8_t)(protect->pp_max + 1u);
            milotic->moves[3].pp = milotic->moves[3].pp_max;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "Protect with the wrong PP maximum");
            duoforge_battle_destroy(w);
        }
        mixed = teams;
        df_put_team_c(&mixed.sides[1]);
        for (size_t i = 0u; i < sizeof kinds / sizeof kinds[0]; ++i) {
            const bool pool_kind = kinds[i] == kp || kinds[i] == kq;
            if (kinds[i] == k1 || kinds[i] == k2) {
                continue; /* Team C is out of range */
            }
            duoforge_battle *w = df_make_battle(kinds[i], &mixed);
            dfi_member *incineroar = &w->sides[1].members[1];
            incineroar->ability = (uint8_t)(DFI_ABILITY_BLAZE + 1u);
            expect_inv(&t, kinds[i], w, pool_kind ? DFI_INV_NONE : DFI_INV_MEMBER_EXTRA, "Blaze on Incineroar");
            incineroar->ability = (uint8_t)(DFI_ABILITY_DROUGHT + 1u);
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "Drought on Incineroar");
            incineroar->ability = (uint8_t)(DFI_ABILITY_INTIMIDATE + 1u);
            expect_inv(&t, kinds[i], w, DFI_INV_NONE, "Intimidate on Incineroar");
            duoforge_battle_destroy(w);
        }
    }

    /* The values of Team C's mechanics under POOL, as under TEAM_C: poison
     * (status 5, no counter), Psychic Terrain (terrain 2), Flip Turn's switch
     * flag (4); one past each is out of range, and under CLOSURE they are. */
    {
        const duoforge_context *kinds[] = {k1, kc, kp, kq};
        for (size_t i = 0u; i < sizeof kinds / sizeof kinds[0]; ++i) {
            const bool extended = kinds[i] == kc || kinds[i] == kp || kinds[i] == kq;
            duoforge_battle *w = df_make_battle(kinds[i], &teams);
            w->sides[0].members[0].status = (uint8_t)DFI_STATUS_PSN;
            expect_inv(&t, kinds[i], w, extended ? DFI_INV_NONE : DFI_INV_MEMBER_EXTRA, "poison");
            w->sides[0].members[0].status_counter = 1u;
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "poison with a counter");
            w->sides[0].members[0].status_counter = 0u;
            w->sides[0].members[0].status = (uint8_t)(DFI_STATUS_PSN + 1u);
            expect_inv(&t, kinds[i], w, DFI_INV_MEMBER_EXTRA, "status 6");
            w->sides[0].members[0].status = 0u;
            w->terrain = (uint8_t)DFI_TERRAIN_PSYCHIC;
            w->terrain_turns = 5u;
            expect_inv(&t, kinds[i], w, extended ? DFI_INV_NONE : DFI_INV_FIELD, "Psychic Terrain");
            w->terrain = (uint8_t)(DFI_TERRAIN_PSYCHIC + 1u);
            expect_inv(&t, kinds[i], w, DFI_INV_FIELD, "terrain 3");
            duoforge_battle_destroy(w);
        }
        /* Five registered members: MEMBER_COUNT under POOL, valid under POOL_DEV. */
        for (uint32_t dev = 0u; dev < 2u; ++dev) {
            const duoforge_context *ctx = dev != 0u ? kq : kp;
            FRESH();
            duoforge_battle *w = NULL;
            DF_CHECK(&t, dfi_battle_create_ungated(ctx, &s, &w) == DUOFORGE_OK && w != NULL);
            if (w == NULL) {
                continue;
            }
            w->sides[1].member_count = 5u;
            memset(&w->sides[1].members[5], 0, sizeof w->sides[1].members[5]);
            expect_inv(&t, ctx, w, dev != 0u ? DFI_INV_NONE : DFI_INV_MEMBER_COUNT, "five registered members");
            duoforge_battle_destroy(w);
        }
        /* No Ability is a legal current ability under POOL_DEV only. */
        s = teams;
        s.sides[0].members[0].ability = 0u;
        duoforge_battle *d = NULL;
        DF_CHECK(&t, dfi_battle_create_ungated(kq, &s, &d) == DUOFORGE_OK && d != NULL);
        expect_inv(&t, kq, d, DFI_INV_NONE, "No Ability under POOL_DEV");
        dfi_invariant got = DFI_INV_NONE;
        DF_CHECK(&t, dfi_state_check(kp, d, &got) == DUOFORGE_E_CONTEXT_MISMATCH && got == DFI_INV_CONTEXT_FINGERPRINT);
        duoforge_battle_destroy(d);
        duoforge_battle *w = df_make_battle(kp, &teams);
        w->sides[0].members[0].ability = 0u;
        expect_inv(&t, kp, w, DFI_INV_MEMBER_EXTRA, "No Ability under POOL");
        duoforge_battle_destroy(w);
    }

    /* The states of the kinds do not mix: the same bytes under another kind
     * are a context mismatch. */
    {
        duoforge_battle *w = df_make_battle(kp, &teams);
        uint8_t enc[DUOFORGE_STATE_V3_ENCODED_SIZE];
        df_encode(kp, w, enc);
        uint8_t *in = df_heap_copy(enc, sizeof enc);
        duoforge_battle *d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(kp, in, sizeof enc, &d) == DUOFORGE_OK && d != NULL);
        bool eq = false;
        DF_CHECK(&t, duoforge_battle_equal(kp, w, d, &eq) == DUOFORGE_OK && eq);
        duoforge_battle_destroy(d);
        d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(kq, in, sizeof enc, &d) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_create_decoded(kc, in, sizeof enc, &d) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, duoforge_battle_create_decoded(k1, in, sizeof enc, &d) == DUOFORGE_E_CONTEXT_MISMATCH);
        df_free(in);
        duoforge_battle_destroy(w);
    }
#undef FRESH

    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    duoforge_context_destroy(kc);
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    duoforge_context_destroy(kq);
    return df_test_end(&t);
}
