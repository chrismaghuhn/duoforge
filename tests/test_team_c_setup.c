/*
 * duoforge.state.team_c_setup (white-box): the TEAM_C data kinds of decision
 * 0009 sections 3.1, 3.4 and 3.5.
 *
 * TEAM_C and TEAM_C_DEV read the extended tables (closure plus Team C); the
 * CLOSURE kinds keep seeing only the closure. Setups follow the closure rules
 * over the extended tables (mixed teams, any table item); TEAM_C_DEV also
 * allows No Ability. A legal setup whose mechanics are not all implemented is
 * rejected with E_UNSUPPORTED; until a step marks a Team C mechanic, every
 * setup that needs it fails that way.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "core/sha256.h"
#include "data/extended_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/team_c.h"

/* tools/state_model/state_v3_model.py (contexts KC and KD). */
#define FP_KC_HEX "520eca894c0c40b6fa6f316fa2c654c1f32a1bf69d58d63f929921d3911f047f"
#define FP_KD_HEX "3005a212f465cf749c9749e0b3c06eb07aaba5cb57ac1a5a7e93026bd87f17c3"

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

/* A legal setup: the gate decides between OK and E_UNSUPPORTED. */
static void legal(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, bool supported,
                  const char *what)
{
    create_expect(t, ctx, s, supported ? DUOFORGE_OK : DUOFORGE_E_UNSUPPORTED, DUOFORGE_OK, what);
}

static void set_member(duoforge_member_setup *m, uint32_t species, uint32_t gender, uint32_t ability_plus1,
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

/* Team C species with closure mechanics only: No Ability where the forme's
 * ability is a Team C mechanic, no Team C item and no Team C move. */
static void put_dev_side(duoforge_side_setup *side)
{
    const uint32_t sneasler[3] = {DFI_MOVE_CLOSECOMBAT, DFI_MOVE_PROTECT, DFI_MOVE_FAKEOUT};
    const uint32_t incineroar[2] = {DFI_MOVE_FAKEOUT, DFI_MOVE_PARTINGSHOT};
    const uint32_t salamence[2] = {DFI_MOVE_PROTECT, DFI_MOVE_TAILWIND};
    const uint32_t indeedee[2] = {DFI_MOVE_TRICKROOM, DFI_MOVE_PSYCHIC};
    const uint32_t kingambit[2] = {DFI_MOVE_IRONHEAD, DFI_MOVE_PROTECT};
    memset(side, 0, sizeof *side);
    side->member_count = 5u;
    set_member(&side->members[0], DFI_FORME_SNEASLER, DUOFORGE_GENDER_MALE, 0u, 0u, 3u, sneasler);
    set_member(&side->members[1], DFI_FORME_INCINEROAR, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE + 1u,
               DFI_ITEM_SITRUSBERRY + 1u, 2u, incineroar);
    set_member(&side->members[2], DFI_FORME_SALAMENCE, DUOFORGE_GENDER_MALE, DFI_ABILITY_INTIMIDATE + 1u, 0u, 2u,
               salamence);
    set_member(&side->members[3], DFI_FORME_INDEEDEEF, DUOFORGE_GENDER_FEMALE, 0u, 0u, 2u, indeedee);
    set_member(&side->members[4], DFI_FORME_KINGAMBIT, DUOFORGE_GENDER_MALE, 0u, 0u, 2u, kingambit);
}

/* The dev side with one Team C mechanic added. member: the member that gets
 * it (5 adds Basculegion); ability, item: + 1 or 0 to keep; move: a set move
 * that replaces move slot 0, or UINT32_MAX to keep. */
static void put_one(duoforge_battle_setup *s, uint32_t member, uint32_t ability_plus1, uint32_t item_plus1,
                    uint32_t move)
{
    put_dev_side(&s->sides[1]);
    duoforge_member_setup *m = &s->sides[1].members[member];
    if (member == 5u) {
        const uint32_t one[1] = {move};
        set_member(m, DFI_FORME_BASCULEGION, DUOFORGE_GENDER_MALE, 0u, 0u, 1u, one);
        s->sides[1].member_count = 6u;
    }
    if (ability_plus1 != 0u) {
        m->ability = ability_plus1;
    }
    if (item_plus1 != 0u) {
        m->item = item_plus1;
    }
    if (move != UINT32_MAX) {
        m->moves[0].move_id = move;
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.team_c_setup");

    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
    duoforge_context *kc = df_make_context(&df_config_team_c);
    duoforge_context *kd = df_make_context(&df_config_team_c_dev);

    /* Contexts: the canonical bytes carry the kind, the extended counts and
     * the extended table hash; the fingerprint is their SHA-256. All four
     * combat fingerprints differ. */
    {
        uint8_t bytes[DFI_CONTEXT_BYTES_SIZE];
        uint8_t fp[4][DUOFORGE_DIGEST_SIZE];
        uint8_t sha[DUOFORGE_DIGEST_SIZE];
        const duoforge_context *all[4] = {k1, k2, kc, kd};
        for (uint32_t i = 0u; i < 4u; ++i) {
            DF_CHECK(&t, duoforge_context_fingerprint(all[i], fp[i]) == DUOFORGE_OK);
        }
        dfi_context_canonical_bytes(kc, bytes);
        DF_CHECK(&t, bytes[24] == DUOFORGE_DATA_KIND_TEAM_C && bytes[27] == DFI_EXT_FORME_COUNT && bytes[28] == 0u &&
                         bytes[29] == DFI_EXT_MOVE_COUNT && bytes[30] == 0u);
        DF_CHECK_BYTES(&t, bytes + DFI_CONTEXT_TABLE_HASH_OFF, dfi_ext_table_hash, DUOFORGE_DIGEST_SIZE,
                       "TEAM_C table hash");
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK_BYTES(&t, sha, fp[2], sizeof sha, "TEAM_C fingerprint = sha256(canonical bytes)");
        dfi_context_canonical_bytes(kd, bytes);
        DF_CHECK(&t, bytes[24] == DUOFORGE_DATA_KIND_TEAM_C_DEV && bytes[27] == DFI_EXT_FORME_COUNT &&
                         bytes[29] == DFI_EXT_MOVE_COUNT);
        DF_CHECK(&t, dfi_sha256(bytes, sizeof bytes, sha));
        DF_CHECK_BYTES(&t, sha, fp[3], sizeof sha, "TEAM_C_DEV fingerprint = sha256(canonical bytes)");
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, df_hex_to_bytes(FP_KC_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp[2], want, sizeof want, "TEAM_C fingerprint (model)");
        DF_CHECK(&t, df_hex_to_bytes(FP_KD_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp[3], want, sizeof want, "TEAM_C_DEV fingerprint (model)");
        uint32_t same = 0u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            for (uint32_t j = 0u; j < i; ++j) {
                same += memcmp(fp[i], fp[j], DUOFORGE_DIGEST_SIZE) == 0 ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, same, 0u);
        /* The target classes are those of the extended moves (Helping Hand:
         * adjacentAlly, the first real use of class 3). */
        DF_CHECK_EQ_U64(&t, kc->move_count, DFI_EXT_MOVE_COUNT);
        DF_CHECK_EQ_U64(&t, kc->move_target_classes[DFI_MOVE_HELPINGHAND], DUOFORGE_TARGET_CLASS_ADJACENT_ALLY);
        DF_CHECK_EQ_U64(&t, k1->move_count, DFI_MOVE_COUNT);

        /* The config contract is CLOSURE's: no counts, no table. */
        duoforge_context_config c = df_config_team_c;
        duoforge_context *out = NULL;
        c.species_count = DFI_EXT_FORME_COUNT;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_team_c;
        c.data_kind = DUOFORGE_DATA_KIND_TEAM_C_DEV + 1u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        /* TEAM_C takes over the certified profile (decision 0010): a context
         * of roster 6 and brought 4 only; TEAM_C_DEV takes any. */
        c = df_config_team_c;
        c.max_roster = 5u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_team_c;
        c.brought_count = 3u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_E_INVALID_ARGUMENT && out == NULL);
        c = df_config_team_c_dev;
        c.max_roster = 5u;
        c.brought_count = 3u;
        DF_CHECK(&t, duoforge_context_create(&c, &out) == DUOFORGE_OK && out != NULL);
        duoforge_context_destroy(out);
    }

    /* The real Team C against the real Team A: legal under TEAM_C, gated
     * until its last mechanic exists; out of range under CLOSURE. */
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    duoforge_battle_setup s;
#define FRESH() (s = teams, df_put_team_c(&s.sides[1]))
    FRESH();
    legal(&t, kc, &s, false, "real Team C vs Team A");
    legal(&t, kd, &s, false, "real Team C vs Team A (dev)");
    invalid(&t, k1, &s, "Team C under CLOSURE");
    invalid(&t, k2, &s, "Team C under CLOSURE_DEV");
    /* The certified profile: TEAM_C registers exactly six, TEAM_C_DEV four
     * to six (decision 0010). */
    FRESH();
    s.sides[1].member_count = 5u;
    memset(&s.sides[1].members[5], 0, sizeof s.sides[1].members[5]);
    invalid(&t, kc, &s, "five members under TEAM_C");
    legal(&t, kd, &s, false, "five members under TEAM_C_DEV");

    /* The closure rules over the extended tables. */
    FRESH();
    s.sides[1].members[5].gender = DUOFORGE_GENDER_FEMALE; /* Basculegion: male only */
    invalid(&t, kc, &s, "female Basculegion");
    FRESH();
    s.sides[1].members[3].gender = DUOFORGE_GENDER_MALE; /* Indeedee-F: female only */
    invalid(&t, kc, &s, "male Indeedee-F");
    FRESH();
    s.sides[1].members[2].ability = DFI_ABILITY_AERILATE + 1u; /* the Mega forme's ability */
    invalid(&t, kc, &s, "Salamence with Aerilate");
    FRESH();
    s.sides[1].members[4].moves[0].move_id = DFI_MOVE_CLOSECOMBAT; /* not in Kingambit's set */
    invalid(&t, kc, &s, "Kingambit with Close Combat");
    FRESH();
    s.sides[1].members[2].species_id = DFI_FORME_SALAMENCEMEGA;
    invalid(&t, kc, &s, "Mega forme set up");
    FRESH();
    s.sides[1].members[2].species_id = DFI_EXT_FORME_COUNT;
    invalid(&t, kc, &s, "species beyond the tables");
    FRESH();
    s.sides[1].members[0].item = DFI_EXT_ITEM_COUNT + 1u;
    invalid(&t, kc, &s, "item beyond the tables");
    FRESH();
    s.sides[1].members[4].item = DFI_ITEM_SITRUSBERRY + 1u; /* Incineroar holds it */
    invalid(&t, kc, &s, "Item Clause");
    FRESH();
    s.sides[1].members[0].ability = 0u;
    invalid(&t, kc, &s, "No Ability under TEAM_C");
    legal(&t, kd, &s, false, "No Ability under TEAM_C_DEV");

    /* Any table item on any member, as in the closure: Choice Scarf on
     * Archaludon is legal, and supported since step 7. */
    s = teams;
    s.sides[0] = teams.sides[1];
    s.sides[1] = teams.sides[0];
    s.sides[0].members[2].item = DFI_ITEM_CHOICESCARF + 1u; /* Archaludon, Leftovers before */
    legal(&t, kc, &s, true, "Choice Scarf on Archaludon");
    s.sides[0].members[2].item = DFI_EXT_ITEM_COUNT + 1u;
    invalid(&t, kc, &s, "Archaludon with an item beyond the tables");
    /* The closure teams themselves under TEAM_C: every mechanic exists. */
    legal(&t, kc, &teams, true, "Team A vs Team B under TEAM_C");

    /* Team C species with closure mechanics only: supported, and the engine
     * derives their stats from the extended tables. */
    {
        s = teams;
        put_dev_side(&s.sides[1]);
        legal(&t, kd, &s, true, "Team C species, closure mechanics (dev)");
        invalid(&t, kc, &s, "the same with No Ability under TEAM_C");
        /* Under CLOSURE_DEV the same side fails on the species alone: every
         * other field is closure-legal (closure moves and item, No Ability). */
        invalid(&t, k2, &s, "Team C species under CLOSURE_DEV");
        duoforge_battle *b = NULL;
        DF_CHECK(&t, duoforge_battle_create(kd, &s, &b) == DUOFORGE_OK && b != NULL);
        if (b != NULL) {
            const dfi_member *king = &b->sides[1].members[4];
            /* Hardy, 32 HP / 32 Atk / 2 Spe: HP 100+32+75, Atk 135+32+20 */
            DF_CHECK(&t, king->hp_max == 207u && king->stats[0] == 187u && king->stats[4] == 72u);
            DF_CHECK_EQ_U64(&t, king->moves[0].pp_max, 16u); /* Iron Head: 15 -> 16 */
            dfi_invariant got = DFI_INV_NONE;
            DF_CHECK(&t, dfi_state_check(kd, b, &got) == DUOFORGE_OK);
            /* White-box: a Team C species or item never passes a CLOSURE
             * context, and an item beyond the tables never passes TEAM_C. */
            dfi_member saved = *king;
            b->sides[1].members[4].item = DFI_EXT_ITEM_COUNT + 1u;
            DF_CHECK(&t, dfi_state_check(kd, b, &got) == DUOFORGE_E_INVARIANT && got == DFI_INV_MEMBER_EXTRA);
            b->sides[1].members[4] = saved;
            duoforge_battle_destroy(b);
        }
        duoforge_battle *c = df_make_battle(k1, &teams);
        dfi_invariant got = DFI_INV_NONE;
        c->sides[1].members[0].species_id = DFI_FORME_KINGAMBIT;
        DF_CHECK(&t, dfi_state_check(k1, c, &got) == DUOFORGE_E_INVARIANT && got == DFI_INV_SPECIES_RANGE);
        c->sides[1].members[0].species_id = (uint16_t)teams.sides[1].members[0].species_id;
        c->sides[1].members[0].item = DFI_ITEM_WHITEHERB + 1u;
        DF_CHECK(&t, dfi_state_check(k1, c, &got) == DUOFORGE_E_INVARIANT && got == DFI_INV_MEMBER_EXTRA);
        duoforge_battle_destroy(c);
    }

    /* White-box: a TEAM_C state with five registered members fails the
     * member count rule (decision 0010, taken over by TEAM_C); the same state
     * under TEAM_C_DEV passes it. */
    for (uint32_t dev = 0u; dev < 2u; ++dev) {
        const duoforge_context *ctx = dev != 0u ? kd : kc;
        FRESH();
        duoforge_battle *w = NULL;
        DF_CHECK(&t, dfi_battle_create_ungated(ctx, &s, &w) == DUOFORGE_OK && w != NULL);
        if (w == NULL) {
            continue;
        }
        w->sides[1].member_count = 5u;
        memset(&w->sides[1].members[5], 0, sizeof w->sides[1].members[5]);
        dfi_invariant inv = DFI_INV_NONE;
        const duoforge_status st = dfi_state_check(ctx, w, &inv);
        if (dev != 0u) {
            DF_CHECK(&t, st == DUOFORGE_OK);
        } else {
            DF_CHECK(&t, st == DUOFORGE_E_INVARIANT && inv == DFI_INV_MEMBER_COUNT);
        }
        duoforge_battle_destroy(w);
    }

    /* White-box: Flip Turn's switch flag (4) is in range only under the
     * TEAM_C kinds. At a TURN boundary any flag breaks SWITCH_FLAG; under
     * CLOSURE the value itself is already out of range (VOLATILE). */
    for (uint32_t team_c = 0u; team_c < 2u; ++team_c) {
        const duoforge_context *ctx = team_c != 0u ? kc : k1;
        duoforge_battle *w = df_make_battle(ctx, &teams);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c->pick_count = 4u;
            for (uint32_t i = 0u; i < 4u; ++i) {
                c->picks[i] = (uint8_t)i;
            }
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(ctx, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        dfi_invariant inv = DFI_INV_NONE;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
        w->sides[0].positions[0].switch_flag = (uint8_t)DFI_SWITCH_FLIP_TURN;
        const duoforge_status st = dfi_state_check(ctx, w, &inv);
        DF_CHECK(&t, st == DUOFORGE_E_INVARIANT && inv == (team_c != 0u ? DFI_INV_SWITCH_FLAG : DFI_INV_VOLATILE));
        /* One past Flip Turn is out of range under every kind. */
        w->sides[0].positions[0].switch_flag = (uint8_t)(DFI_SWITCH_FLIP_TURN + 1u);
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        duoforge_battle_destroy(w);
    }

    /* White-box: poison (status 5, step 6) is in range only under the
     * TEAM_C kinds, without a counter; one past it is out of range under
     * every kind. */
    for (uint32_t team_c = 0u; team_c < 2u; ++team_c) {
        const duoforge_context *ctx = team_c != 0u ? kc : k1;
        duoforge_battle *w = df_make_battle(ctx, &teams);
        dfi_invariant inv = DFI_INV_NONE;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
        w->sides[0].members[0].status = (uint8_t)DFI_STATUS_PSN;
        const duoforge_status st = dfi_state_check(ctx, w, &inv);
        if (team_c != 0u) {
            DF_CHECK(&t, st == DUOFORGE_OK);
        } else {
            DF_CHECK(&t, st == DUOFORGE_E_INVARIANT && inv == DFI_INV_MEMBER_EXTRA);
        }
        w->sides[0].members[0].status_counter = 1u;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_MEMBER_EXTRA);
        w->sides[0].members[0].status_counter = 0u;
        w->sides[0].members[0].status = (uint8_t)(DFI_STATUS_PSN + 1u);
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_MEMBER_EXTRA);
        duoforge_battle_destroy(w);
    }

    /* White-box: the choice lock (bit 64, step 7) is in range only under the
     * TEAM_C kinds. It keeps a move slot in the locked-move byte without a
     * charge and without a target, and its holder holds a Choice Scarf. */
    for (uint32_t team_c = 0u; team_c < 2u; ++team_c) {
        const duoforge_context *ctx = team_c != 0u ? kc : k1;
        duoforge_battle *w = df_make_battle(ctx, &teams);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c->pick_count = 4u;
            for (uint32_t i = 0u; i < 4u; ++i) {
                c->picks[i] = (uint8_t)i;
            }
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(ctx, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        dfi_active_slot *pos = &w->sides[0].positions[0];
        dfi_member *holder = &w->sides[0].members[pos->occupant];
        dfi_invariant inv = DFI_INV_NONE;
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_CHOICE_LOCK);
        pos->locked_move = 1u;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        if (team_c != 0u) {
            holder->item = (uint8_t)(1u + DFI_ITEM_CHOICESCARF); /* the lock needs the Choice item */
            DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
            pos->locked_target = 1u; /* a target only while charging */
            DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
            pos->locked_target = 0u;
            pos->locked_move = 0u; /* the lock names its move */
            DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
            pos->locked_move = 1u;
            pos->flags = (uint8_t)((uint32_t)pos->flags & ~DFI_VOL_CHOICE_LOCK);
            DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        }
        duoforge_battle_destroy(w);
    }

    /* The gate per Team C mechanic: the dev side plus exactly one of them.
     * Steps (decision 0009 section 5) mark them one by one; step 1: Kowtow
     * Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet, Defiant and
     * Adaptability; step 2: Flare Blitz and Darkest Lariat; step 3: Salamencite
     * with Aerilate; step 4: Last Respects and Flip Turn; step 5: Chople Berry
     * and Rocky Helmet; step 6: Dire Claw (poison); step 7: Choice Scarf. */
    {
        typedef struct gate_case {
            uint32_t member, ability_plus1, item_plus1, move;
            bool supported;
            const char *what;
        } gate_case;
        const uint32_t keep = UINT32_MAX;
        const gate_case cases[] = {
            {0u, 0u, 0u, DFI_MOVE_DIRECLAW, true, "Dire Claw (poison)"},
            {1u, 0u, 0u, DFI_MOVE_FLAREBLITZ, true, "Flare Blitz"},
            {1u, 0u, 0u, DFI_MOVE_DARKESTLARIAT, true, "Darkest Lariat"},
            {2u, 0u, 0u, DFI_MOVE_HYPERVOICE, true, "Hyper Voice"},
            {2u, 0u, 0u, DFI_MOVE_DRACOMETEOR, true, "Draco Meteor"},
            {3u, 0u, 0u, DFI_MOVE_FOLLOWME, false, "Follow Me"},
            {3u, 0u, 0u, DFI_MOVE_HELPINGHAND, false, "Helping Hand"},
            {4u, 0u, 0u, DFI_MOVE_KOWTOWCLEAVE, true, "Kowtow Cleave"},
            {4u, 0u, 0u, DFI_MOVE_SUCKERPUNCH, false, "Sucker Punch"},
            {5u, 0u, 0u, DFI_MOVE_WAVECRASH, true, "Wave Crash"},
            {5u, 0u, 0u, DFI_MOVE_LASTRESPECTS, true, "Last Respects"},
            {5u, 0u, 0u, DFI_MOVE_FLIPTURN, true, "Flip Turn"},
            {5u, 0u, 0u, DFI_MOVE_AQUAJET, true, "Aqua Jet"},
            {0u, DFI_ABILITY_UNBURDEN + 1u, 0u, keep, false, "Unburden"},
            {3u, DFI_ABILITY_PSYCHICSURGE + 1u, 0u, keep, false, "Psychic Surge"},
            {4u, DFI_ABILITY_DEFIANT + 1u, 0u, keep, true, "Defiant"},
            {0u, 0u, DFI_ITEM_WHITEHERB + 1u, keep, false, "White Herb"},
            {2u, 0u, DFI_ITEM_SALAMENCITE + 1u, keep, true, "Salamencite (Mega, Aerilate)"},
            {3u, 0u, DFI_ITEM_ROCKYHELMET + 1u, keep, true, "Rocky Helmet"},
            {4u, 0u, DFI_ITEM_CHOPLEBERRY + 1u, keep, true, "Chople Berry"},
            {4u, 0u, DFI_ITEM_CHOICESCARF + 1u, keep, true, "Choice Scarf (the choice lock)"},
            {5u, DFI_ABILITY_ADAPTABILITY + 1u, 0u, DFI_MOVE_WAVECRASH, true, "Adaptability"},
        };
        for (size_t i = 0u; i < sizeof cases / sizeof cases[0]; ++i) {
            s = teams;
            put_one(&s, cases[i].member, cases[i].ability_plus1, cases[i].item_plus1, cases[i].move);
            legal(&t, kd, &s, cases[i].supported, cases[i].what);
        }
    }

    /* The manifest's Team C entries are exactly the mechanics of the steps
     * built so far (the closure entries: duoforge.state.closure_setup). */
    {
        uint8_t moves[DFI_EXT_MOVE_COUNT - DFI_MOVE_COUNT] = {0};
        uint8_t abilities[DFI_EXT_ABILITY_COUNT - DFI_ABILITY_COUNT] = {0};
        uint8_t items[DFI_EXT_ITEM_COUNT - DFI_ITEM_COUNT] = {0};
        static const uint32_t step1_moves[] = {DFI_MOVE_KOWTOWCLEAVE, DFI_MOVE_HYPERVOICE, DFI_MOVE_DRACOMETEOR,
                                               DFI_MOVE_WAVECRASH,    DFI_MOVE_AQUAJET,   DFI_MOVE_FLAREBLITZ,
                                               DFI_MOVE_DARKESTLARIAT, DFI_MOVE_LASTRESPECTS, DFI_MOVE_FLIPTURN,
                                               DFI_MOVE_DIRECLAW};
        for (size_t i = 0u; i < sizeof step1_moves / sizeof step1_moves[0]; ++i) {
            moves[step1_moves[i] - DFI_MOVE_COUNT] = 1u;
        }
        abilities[DFI_ABILITY_DEFIANT - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_ADAPTABILITY - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_AERILATE - DFI_ABILITY_COUNT] = 1u;
        items[DFI_ITEM_SALAMENCITE - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_CHOPLEBERRY - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_ROCKYHELMET - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_CHOICESCARF - DFI_ITEM_COUNT] = 1u;
        DF_CHECK_BYTES(&t, dfi_support.moves + DFI_MOVE_COUNT, moves, sizeof moves, "Team C moves in the manifest");
        DF_CHECK_BYTES(&t, dfi_support.abilities + DFI_ABILITY_COUNT, abilities, sizeof abilities,
                       "Team C abilities in the manifest");
        DF_CHECK_BYTES(&t, dfi_support.items + DFI_ITEM_COUNT, items, sizeof items, "Team C items in the manifest");
    }

    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    duoforge_context_destroy(kc);
    duoforge_context_destroy(kd);
    return df_test_end(&t);
}
