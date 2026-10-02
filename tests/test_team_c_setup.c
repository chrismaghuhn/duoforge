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
#include "state/knowledge.h"
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

/* The number of player 0's move lines before White Herb's [-enditem] in
 * `events` (n of them), 0 when there is none; *side gets the herb holder's
 * side of the first one (2 when there is none), *herbs the number of them. */
static uint32_t herb_lines(const duoforge_event *events, uint32_t n, uint32_t *side, uint32_t *herbs)
{
    uint32_t moves = 0u;
    uint32_t before = 0u;
    *side = 2u;
    *herbs = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        if (events[i].kind == DUOFORGE_EVENT_MOVE) {
            moves += 1u;
        } else if (events[i].kind == DUOFORGE_EVENT_ITEM_END && events[i].id2 == 1u + DFI_ITEM_WHITEHERB) {
            if (*herbs == 0u) {
                *side = (uint32_t)events[i].position / 2u;
                before = moves;
            }
            *herbs += 1u;
        }
    }
    return before;
}

/* Step 8: the dev side against itself, each Sneasler with a White Herb and
 * side 1's at `spe` Speed points (side 0's: 2), the RNG seeded with `seed`.
 * Both Incineroar leads' Intimidates lower both Sneaslers' Attack, so both
 * herbs are due on AnySwitchIn. Returns the team step's status; *herbs
 * counts the herbs' [-enditem] lines and *first is the side of the first
 * (2 when there is none). */
static duoforge_status herb_pair(const duoforge_context *ctx, const duoforge_battle_setup *teams, uint8_t spe,
                                 uint64_t seed, uint32_t *herbs, uint32_t *first)
{
    duoforge_battle_setup s = *teams;
    s.rng_initstate = seed;
    put_dev_side(&s.sides[0]);
    put_dev_side(&s.sides[1]);
    s.sides[0].members[0].item = DFI_ITEM_WHITEHERB + 1u;
    s.sides[1].members[0].item = DFI_ITEM_WHITEHERB + 1u;
    s.sides[1].members[0].stat_points[1] = (uint8_t)(34u - spe); /* 66 points in all */
    s.sides[1].members[0].stat_points[5] = spe;
    duoforge_battle *w = df_make_battle(ctx, &s);
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
            c->picks[i] = (uint8_t)i; /* Sneasler and Incineroar lead */
        }
    }
    duoforge_event events[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events[0], DUOFORGE_MAX_EVENTS, 0u}, {events[1], DUOFORGE_MAX_EVENTS, 0u}};
    duoforge_step_result res;
    const duoforge_status st = duoforge_battle_step_events(ctx, w, &bd, &res, buffers);
    (void)herb_lines(events[0], st == DUOFORGE_OK ? buffers[0].count : 0u, first, herbs);
    duoforge_battle_destroy(w);
    return st;
}

/* White-box (step 8): the dev side against itself, Sneasler and Kingambit
 * against Sneasler, here with a Rocky Helmet, and Indeedee-F, here with a
 * White Herb and, when `lowered`, Defense -1. Turn 1: Sneasler's Fake Out
 * (+3) into the Helmet first. At 1 HP (`faints`) the Helmet makes the user
 * faint inside its move; at 1 HP (`ko`) the Helmet holder faints too. Then
 * Psychic, Iron Head and the flinched Close Combat. Returns the turn's
 * status; *moves is the number of move lines before the herb's [-enditem],
 * 0 when there is none. */
static duoforge_status helmet_turn(const duoforge_context *ctx, const duoforge_battle_setup *teams, bool faints,
                                   bool ko, bool lowered, uint32_t *moves)
{
    duoforge_battle_setup s = *teams;
    put_dev_side(&s.sides[0]);
    put_dev_side(&s.sides[1]);
    duoforge_battle *w = df_make_battle(ctx, &s);
    const uint8_t picks[2][4] = {{0u, 4u, 1u, 2u}, {0u, 3u, 1u, 2u}}; /* leads first */
    const uint8_t plan[2][2][2] = {{{2u, 2u}, {0u, 3u}}, {{0u, 0u}, {1u, 0u}}}; /* move slot, target */
    duoforge_event events[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer buffers[2] = {{events[0], DUOFORGE_MAX_EVENTS, 0u}, {events[1], DUOFORGE_MAX_EVENTS, 0u}};
    duoforge_decision_bundle bd;
    duoforge_step_result res;
    duoforge_status st = DUOFORGE_OK;
    *moves = 0u;
    for (uint32_t step = 0u; step < 2u && st == DUOFORGE_OK; ++step) {
        if (step == 1u) {
            if (w->boundary_kind != DUOFORGE_BOUNDARY_TURN) {
                st = DUOFORGE_E_INVARIANT;
                break;
            }
            for (uint32_t side = 0u; side < 2u; ++side) {
                if (side == 0u ? !faints : !ko) {
                    continue;
                }
                dfi_member *m = &w->sides[side].members[0];
                dfi_knowledge *shown = &w->sides[1u - side].knowledge[0]; /* the foe sees the HP bar */
                m->hp = 1u;
                dfi_hp_display(m->hp, m->hp_max, &shown->hp_percent, &shown->hp_flag);
            }
            w->sides[1].members[0].item = (uint8_t)(1u + DFI_ITEM_ROCKYHELMET);
            w->sides[1].members[3].item = (uint8_t)(1u + DFI_ITEM_WHITEHERB);
            if (lowered) {
                w->sides[1].positions[1].stages[DFI_STAGE_DEF] = (uint8_t)(DFI_STAGE_NEUTRAL - 1u);
            }
        }
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            if (step == 0u) {
                c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                c->pick_count = 4u;
                memcpy(c->picks, picks[side], sizeof picks[side]);
                continue;
            }
            c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t slot = 0u; slot < 2u; ++slot) {
                c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
                c->slots[slot].move_slot = plan[side][slot][0];
                c->slots[slot].target = plan[side][slot][1];
            }
        }
        st = duoforge_battle_step_events(ctx, w, &bd, &res, buffers);
    }
    if (st == DUOFORGE_OK) {
        uint32_t side = 2u;
        uint32_t herbs = 0u;
        *moves = herb_lines(events[0], buffers[0].count, &side, &herbs);
    }
    duoforge_battle_destroy(w);
    return st;
}

/* One step of slot commands: per side and slot {kind, move slot or reserve,
 * target}; a side outside `mask` answers nothing, and a slot of kind 0 is
 * left all-zero (not requested). */
static duoforge_status slots_step(const duoforge_context *ctx, duoforge_battle *w, uint32_t mask,
                                  const uint8_t cmd[2][2][3])
{
    duoforge_decision_bundle bd;
    memset(&bd, 0, sizeof bd);
    bd.epoch = w->request_epoch;
    bd.response_mask = (uint8_t)mask;
    for (uint32_t side = 0u; side < 2u; ++side) {
        if (((mask >> side) & 1u) == 0u) {
            continue;
        }
        duoforge_side_choice *c = &bd.responses[side];
        c->epoch = w->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            const uint8_t *x = cmd[side][slot];
            c->slots[slot].kind = x[0];
            if (x[0] == DUOFORGE_SLOT_MOVE) {
                c->slots[slot].move_slot = x[1];
                c->slots[slot].target = x[2];
            } else if (x[0] == DUOFORGE_SLOT_SWITCH) {
                c->slots[slot].reserve = x[1];
            }
        }
    }
    duoforge_step_result res;
    return duoforge_battle_step(ctx, w, &bd, &res);
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

    /* The real Team C against the real Team A: legal under TEAM_C and
     * supported since step 11 built its last mechanic (Follow Me); out of
     * range under CLOSURE. */
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    duoforge_battle_setup s;
#define FRESH() (s = teams, df_put_team_c(&s.sides[1]))
    FRESH();
    legal(&t, kc, &s, true, "real Team C vs Team A");
    legal(&t, kd, &s, true, "real Team C vs Team A (dev)");
    invalid(&t, k1, &s, "Team C under CLOSURE");
    invalid(&t, k2, &s, "Team C under CLOSURE_DEV");
    /* The certified profile: TEAM_C registers exactly six, TEAM_C_DEV four
     * to six (decision 0010). */
    FRESH();
    s.sides[1].member_count = 5u;
    memset(&s.sides[1].members[5], 0, sizeof s.sides[1].members[5]);
    invalid(&t, kc, &s, "five members under TEAM_C");
    legal(&t, kd, &s, true, "five members under TEAM_C_DEV");

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
    legal(&t, kd, &s, true, "No Ability under TEAM_C_DEV");

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

    /* White-box (step 10): Psychic Terrain (terrain 2) is in range only under
     * the TEAM_C kinds; one past it is out of range under every kind. */
    for (uint32_t team_c = 0u; team_c < 2u; ++team_c) {
        const duoforge_context *ctx = team_c != 0u ? kc : k1;
        duoforge_battle *w = df_make_battle(ctx, &teams);
        dfi_invariant inv = DFI_INV_NONE;
        w->terrain = (uint8_t)DFI_TERRAIN_PSYCHIC;
        w->terrain_turns = 5u;
        const duoforge_status st = dfi_state_check(ctx, w, &inv);
        if (team_c != 0u) {
            DF_CHECK(&t, st == DUOFORGE_OK);
        } else {
            DF_CHECK(&t, st == DUOFORGE_E_INVARIANT && inv == DFI_INV_FIELD);
        }
        w->terrain = (uint8_t)(DFI_TERRAIN_PSYCHIC + 1u);
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_FIELD);
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
        const uint8_t original_item = holder->item;
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
        /* Unburden's volatile (bit 32, step 8): TEAM_C kinds only, and only
         * on an Unburden holder whose item is gone. */
        pos->flags = 0u;
        pos->locked_move = 0u;
        holder->item = original_item;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_OK);
        pos->flags = (uint8_t)DFI_VOL_UNBURDEN;
        DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        if (team_c != 0u) {
            holder->item_consumed = 1u; /* the item is gone, but the holder has no Unburden */
            DF_CHECK(&t, dfi_state_check(ctx, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
            holder->item_consumed = 0u;
        }
        duoforge_battle_destroy(w);
    }

    /* White-box (step 8): Unburden's bit needs an Unburden holder whose item
     * is used; with the item still held it is VOLATILE. */
    {
        duoforge_battle_setup u = teams;
        put_dev_side(&u.sides[0]);
        u.sides[0].members[0].ability = DFI_ABILITY_UNBURDEN + 1u; /* Sneasler leads */
        u.sides[0].members[0].item = DFI_ITEM_WHITEHERB + 1u;
        duoforge_battle *w = df_make_battle(kd, &u);
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
        DF_CHECK(&t, duoforge_battle_step(kd, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        dfi_active_slot *pos = &w->sides[0].positions[0];
        dfi_member *holder = &w->sides[0].members[pos->occupant];
        dfi_invariant inv = DFI_INV_NONE;
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_OK && holder->item_consumed == 0u);
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_UNBURDEN);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        holder->item_consumed = 1u; /* the herb used: the bit is valid */
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        duoforge_battle_destroy(w);
    }

    /* White-box (step 8): runEvent collects AfterMove's Any handlers only
     * while the user or runMove's target is active (sim/battle.ts:1053). A
     * user and a target that a Fake Out into a Rocky Helmet makes faint
     * inside the move are not: the herb then waits for the next move's
     * AfterMove (Indeedee-F's own Psychic). Either one standing is enough. */
    {
        uint32_t moves = 9u;
        DF_CHECK(&t, helmet_turn(kd, &teams, false, false, true, &moves) == DUOFORGE_OK && moves == 1u);
        DF_CHECK(&t, helmet_turn(kd, &teams, true, false, true, &moves) == DUOFORGE_OK && moves == 1u);
        DF_CHECK(&t, helmet_turn(kd, &teams, false, true, true, &moves) == DUOFORGE_OK && moves == 1u);
        DF_CHECK(&t, helmet_turn(kd, &teams, true, true, true, &moves) == DUOFORGE_OK && moves == 2u);
        DF_CHECK(&t, helmet_turn(kd, &teams, true, true, false, &moves) == DUOFORGE_OK && moves == 0u);
    }

    /* Step 8: two White Herbs due at one switch-in run in runSwitch's speed
     * order: the faster holder's first; at one speed the tie is drawn, so
     * over a few seeds both orders show. */
    {
        uint32_t herbs = 0u;
        uint32_t first = 2u;
        DF_CHECK(&t, herb_pair(kd, &teams, 32u, teams.rng_initstate, &herbs, &first) == DUOFORGE_OK && herbs == 2u &&
                         first == 1u);
        uint32_t firsts = 0u;
        for (uint64_t k = 0u; k < 16u; ++k) {
            const duoforge_status st = herb_pair(kd, &teams, 2u, teams.rng_initstate ^ k, &herbs, &first);
            DF_CHECK(&t, st == DUOFORGE_OK && herbs == 2u && first < 2u);
            firsts |= 1u << (first & 7u);
        }
        DF_CHECK(&t, firsts == 3u);
    }

    /* White-box (step 9b): Helping Hand's volatile (bit 16) and newlySwitched
     * (bit 128) are TEAM_C bits that live within a turn. Indeedee-F's Helping
     * Hand on Basculegion, whose Flip Turn then asks for a pivot, while the
     * foe's Sneasler switched out for Incineroar: at that PIVOT boundary both
     * bits are valid; at the next TURN boundary both are gone, and either
     * one there is VOLATILE. Under CLOSURE both are out of range. */
    {
        duoforge_battle_setup u = teams;
        put_dev_side(&u.sides[0]);
        put_dev_side(&u.sides[1]);
        const uint32_t indeedee[2] = {DFI_MOVE_HELPINGHAND, DFI_MOVE_PSYCHIC};
        const uint32_t basculegion[1] = {DFI_MOVE_FLIPTURN};
        set_member(&u.sides[0].members[3], DFI_FORME_INDEEDEEF, DUOFORGE_GENDER_FEMALE, 0u, 0u, 2u, indeedee);
        set_member(&u.sides[0].members[5], DFI_FORME_BASCULEGION, DUOFORGE_GENDER_MALE, 0u, 0u, 1u, basculegion);
        u.sides[0].member_count = 6u;
        duoforge_battle *w = df_make_battle(kd, &u);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        const uint8_t picks[2][4] = {{3u, 5u, 0u, 4u}, {0u, 4u, 1u, 2u}}; /* leads first */
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c->pick_count = 4u;
            memcpy(c->picks, picks[side], sizeof picks[side]);
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(kd, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        const uint8_t turn1[2][2][3] = {{{DUOFORGE_SLOT_MOVE, 0u, 1u}, {DUOFORGE_SLOT_MOVE, 0u, 3u}},
                                        {{DUOFORGE_SLOT_SWITCH, 1u, 0u}, {DUOFORGE_SLOT_MOVE, 0u, 1u}}};
        DF_CHECK(&t, slots_step(kd, w, 3u, turn1) == DUOFORGE_OK && w->boundary_kind == DUOFORGE_BOUNDARY_PIVOT);
        dfi_invariant inv = DFI_INV_NONE;
        DF_CHECK(&t, ((uint32_t)w->sides[0].positions[1].flags & DFI_VOL_HELPING_HAND) != 0u &&
                         ((uint32_t)w->sides[1].positions[0].flags & DFI_VOL_NEWLY_SWITCHED) != 0u &&
                         dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        const uint8_t pivot[2][2][3] = {{{0u, 0u, 0u}, {DUOFORGE_SLOT_SWITCH, 0u, 0u}}, {{0u, 0u, 0u}, {0u, 0u, 0u}}};
        DF_CHECK(&t, slots_step(kd, w, 1u, pivot) == DUOFORGE_OK && w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        uint32_t left = 0u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            for (uint32_t p = 0u; p < 2u; ++p) {
                left |= (uint32_t)w->sides[side].positions[p].flags & (DFI_VOL_HELPING_HAND | DFI_VOL_NEWLY_SWITCHED);
            }
        }
        DF_CHECK(&t, left == 0u && dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        dfi_active_slot *pos = &w->sides[0].positions[0];
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_HELPING_HAND);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        pos->flags = (uint8_t)(((uint32_t)pos->flags & ~DFI_VOL_HELPING_HAND) | DFI_VOL_NEWLY_SWITCHED);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        duoforge_battle_destroy(w);
        /* Under CLOSURE both bits are out of range. */
        const uint32_t bits = DFI_VOL_HELPING_HAND | DFI_VOL_NEWLY_SWITCHED;
        DF_CHECK(&t, (dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE).vol_flags_mask & bits) == 0u &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE_DEV).vol_flags_mask & bits) == 0u &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C).vol_flags_mask & bits) == bits &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C_DEV).vol_flags_mask & bits) == bits);
    }

    /* White-box (step 9b): a REPLACEMENT comes after the residual, so it holds
     * no Helping Hand, while newlySwitched still lasts until the end of the
     * turn. A Fake Out into a Rocky Helmet makes its 1-HP user faint, and side
     * 0 is asked for a replacement after the turn. */
    {
        duoforge_battle_setup u = teams;
        put_dev_side(&u.sides[0]);
        put_dev_side(&u.sides[1]);
        duoforge_battle *w = df_make_battle(kd, &u);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        const uint8_t picks[2][4] = {{0u, 4u, 1u, 2u}, {0u, 3u, 1u, 2u}}; /* leads first */
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c->pick_count = 4u;
            memcpy(c->picks, picks[side], sizeof picks[side]);
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(kd, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        dfi_member *user = &w->sides[0].members[0];
        dfi_knowledge *shown = &w->sides[1].knowledge[0];
        user->hp = 1u;
        dfi_hp_display(user->hp, user->hp_max, &shown->hp_percent, &shown->hp_flag);
        w->sides[1].members[0].item = (uint8_t)(1u + DFI_ITEM_ROCKYHELMET);
        const uint8_t turn1[2][2][3] = {{{DUOFORGE_SLOT_MOVE, 2u, 2u}, {DUOFORGE_SLOT_MOVE, 0u, 3u}},
                                        {{DUOFORGE_SLOT_MOVE, 0u, 0u}, {DUOFORGE_SLOT_MOVE, 1u, 0u}}};
        DF_CHECK(&t, slots_step(kd, w, 3u, turn1) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_REPLACEMENT);
        dfi_invariant inv = DFI_INV_NONE;
        dfi_active_slot *pos = &w->sides[1].positions[1]; /* the standing Indeedee-F */
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_HELPING_HAND);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        pos->flags = (uint8_t)(((uint32_t)pos->flags & ~DFI_VOL_HELPING_HAND) | DFI_VOL_FOLLOW_ME);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        pos->flags = (uint8_t)(((uint32_t)pos->flags & ~DFI_VOL_FOLLOW_ME) | DFI_VOL_NEWLY_SWITCHED);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        duoforge_battle_destroy(w);
    }

    /* White-box (step 11): Follow Me's volatile (bit 8) is a TEAM_C bit that
     * lives within a turn. Indeedee-F's Follow Me, then its partner
     * Basculegion's Flip Turn asks for a pivot: at that PIVOT boundary the
     * bit is valid and both players see DUOFORGE_POSITION_FLAG_FOLLOW_ME; at
     * the next TURN boundary it is gone, and the bit there is VOLATILE.
     * Under CLOSURE it is out of range. */
    {
        duoforge_battle_setup u = teams;
        put_dev_side(&u.sides[0]);
        put_dev_side(&u.sides[1]);
        const uint32_t indeedee[2] = {DFI_MOVE_FOLLOWME, DFI_MOVE_PSYCHIC};
        const uint32_t basculegion[1] = {DFI_MOVE_FLIPTURN};
        set_member(&u.sides[0].members[3], DFI_FORME_INDEEDEEF, DUOFORGE_GENDER_FEMALE, 0u, 0u, 2u, indeedee);
        set_member(&u.sides[0].members[5], DFI_FORME_BASCULEGION, DUOFORGE_GENDER_MALE, 0u, 0u, 1u, basculegion);
        u.sides[0].member_count = 6u;
        duoforge_battle *w = df_make_battle(kd, &u);
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bd.epoch = w->request_epoch;
        bd.response_mask = 3u;
        const uint8_t picks[2][4] = {{3u, 5u, 0u, 4u}, {0u, 4u, 1u, 2u}}; /* leads first */
        for (uint32_t side = 0u; side < 2u; ++side) {
            duoforge_side_choice *c = &bd.responses[side];
            c->epoch = w->request_epoch;
            c->side = (uint8_t)side;
            c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            c->pick_count = 4u;
            memcpy(c->picks, picks[side], sizeof picks[side]);
        }
        duoforge_step_result res;
        DF_CHECK(&t, duoforge_battle_step(kd, w, &bd, &res) == DUOFORGE_OK &&
                         w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        const uint8_t turn1[2][2][3] = {
            {{DUOFORGE_SLOT_MOVE, 0u, DUOFORGE_TARGET_NONE}, {DUOFORGE_SLOT_MOVE, 0u, 3u}},
            {{DUOFORGE_SLOT_SWITCH, 1u, 0u}, {DUOFORGE_SLOT_MOVE, 0u, 1u}}};
        DF_CHECK(&t, slots_step(kd, w, 3u, turn1) == DUOFORGE_OK && w->boundary_kind == DUOFORGE_BOUNDARY_PIVOT);
        dfi_invariant inv = DFI_INV_NONE;
        DF_CHECK(&t, ((uint32_t)w->sides[0].positions[0].flags & DFI_VOL_FOLLOW_ME) != 0u &&
                         dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        for (uint32_t player = 0u; player < 2u; ++player) {
            duoforge_observation ob;
            DF_CHECK(&t, duoforge_battle_observe(kd, w, player, &ob) == DUOFORGE_OK &&
                             ob.sides[0].positions[0].reserved == DUOFORGE_POSITION_FLAG_FOLLOW_ME);
        }
        const uint8_t pivot[2][2][3] = {{{0u, 0u, 0u}, {DUOFORGE_SLOT_SWITCH, 0u, 0u}}, {{0u, 0u, 0u}, {0u, 0u, 0u}}};
        DF_CHECK(&t, slots_step(kd, w, 1u, pivot) == DUOFORGE_OK && w->boundary_kind == DUOFORGE_BOUNDARY_TURN);
        uint32_t left = 0u;
        for (uint32_t side = 0u; side < 2u; ++side) {
            for (uint32_t p = 0u; p < 2u; ++p) {
                left |= (uint32_t)w->sides[side].positions[p].flags & DFI_VOL_FOLLOW_ME;
            }
        }
        DF_CHECK(&t, left == 0u && dfi_state_check(kd, w, &inv) == DUOFORGE_OK);
        dfi_active_slot *pos = &w->sides[0].positions[0];
        pos->flags = (uint8_t)((uint32_t)pos->flags | DFI_VOL_FOLLOW_ME);
        DF_CHECK(&t, dfi_state_check(kd, w, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_VOLATILE);
        duoforge_battle_destroy(w);
        DF_CHECK(&t, (dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE).vol_flags_mask & DFI_VOL_FOLLOW_ME) == 0u &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_CLOSURE_DEV).vol_flags_mask & DFI_VOL_FOLLOW_ME) == 0u &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C).vol_flags_mask & DFI_VOL_FOLLOW_ME) != 0u &&
                         (dfi_kind_limits_of(DUOFORGE_DATA_KIND_TEAM_C_DEV).vol_flags_mask & DFI_VOL_FOLLOW_ME) != 0u);
    }

    /* The gate per Team C mechanic: the dev side plus exactly one of them.
     * Steps (decision 0009 section 5) mark them one by one; step 1: Kowtow
     * Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet, Defiant and
     * Adaptability; step 2: Flare Blitz and Darkest Lariat; step 3: Salamencite
     * with Aerilate; step 4: Last Respects and Flip Turn; step 5: Chople Berry
     * and Rocky Helmet; step 6: Dire Claw (poison); step 7: Choice Scarf;
     * step 8: White Herb and Unburden; step 9b: Sucker Punch and Helping
     * Hand; step 10: Psychic Surge (Psychic Terrain); step 11: Follow Me. */
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
            {3u, 0u, 0u, DFI_MOVE_FOLLOWME, true, "Follow Me"},
            {3u, 0u, 0u, DFI_MOVE_HELPINGHAND, true, "Helping Hand"},
            {4u, 0u, 0u, DFI_MOVE_KOWTOWCLEAVE, true, "Kowtow Cleave"},
            {4u, 0u, 0u, DFI_MOVE_SUCKERPUNCH, true, "Sucker Punch"},
            {5u, 0u, 0u, DFI_MOVE_WAVECRASH, true, "Wave Crash"},
            {5u, 0u, 0u, DFI_MOVE_LASTRESPECTS, true, "Last Respects"},
            {5u, 0u, 0u, DFI_MOVE_FLIPTURN, true, "Flip Turn"},
            {5u, 0u, 0u, DFI_MOVE_AQUAJET, true, "Aqua Jet"},
            {0u, DFI_ABILITY_UNBURDEN + 1u, 0u, keep, true, "Unburden"},
            {3u, DFI_ABILITY_PSYCHICSURGE + 1u, 0u, keep, true, "Psychic Surge"},
            {4u, DFI_ABILITY_DEFIANT + 1u, 0u, keep, true, "Defiant"},
            {0u, 0u, DFI_ITEM_WHITEHERB + 1u, keep, true, "White Herb"},
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
                                               DFI_MOVE_DIRECLAW,     DFI_MOVE_SUCKERPUNCH, DFI_MOVE_HELPINGHAND,
                                               DFI_MOVE_FOLLOWME};
        for (size_t i = 0u; i < sizeof step1_moves / sizeof step1_moves[0]; ++i) {
            moves[step1_moves[i] - DFI_MOVE_COUNT] = 1u;
        }
        abilities[DFI_ABILITY_DEFIANT - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_ADAPTABILITY - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_AERILATE - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_UNBURDEN - DFI_ABILITY_COUNT] = 1u;
        abilities[DFI_ABILITY_PSYCHICSURGE - DFI_ABILITY_COUNT] = 1u;
        items[DFI_ITEM_SALAMENCITE - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_CHOPLEBERRY - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_ROCKYHELMET - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_CHOICESCARF - DFI_ITEM_COUNT] = 1u;
        items[DFI_ITEM_WHITEHERB - DFI_ITEM_COUNT] = 1u;
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
