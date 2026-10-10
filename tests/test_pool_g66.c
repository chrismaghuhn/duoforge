/*
 * duoforge.state.pool_g66 (white-box): step G66, Aegislash (decision 0015 5cb, decision 0040): King's Shield as protect_kind 2,
 * the battle-only Aegislash-Blade row, Stance Change's marks, the codec round trip of protect_kind 2, the strict stats rule of
 * a temporary forme (the Blade's stats only for an Aegislash on the Blade forme, the sheet's stats in every other case), and the
 * public refusal of a position in a temporary forme (DUOFORGE_PUBLIC_CAUSE_TEMP_FORME).
 *
 * The recorded battles are compared by duoforge.reference.conformance_pool_data: g66_blade_shield_cycle, g66_blade_stats,
 * g66_switch_revert, g66_phantom_breaks_kings, g66_feint_breaks_kings, g66_intimidate_blade, g66_kings_status_pass,
 * g66_kings_noncontact_block, g66_kings_contact_drop and g66_trace_skips_stance (Trace copies a foe that has no notrace flag;
 * Stance Change has it). This file checks what those do not show.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>
#include <duoforge/duoforge_view.h>

#include "codec/state_codec.h"
#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

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

/* The reference teams with side 0's lead replaced by an Aegislash (Stance Change, male: the rule is any gender): its four
 * moves are King's Shield, Iron Head, Protect and Shadow Ball, all learnable by the forme (the Champions learnset). */
static void aegislash_setup(duoforge_battle_setup *s)
{
    df_setup_teams(s);
    duoforge_member_setup *lead = &s->sides[0].members[0];
    lead->species_id = DFI_FORME_AEGISLASH;
    lead->ability = DFI_ABILITY_STANCECHANGE + 1u; /* the setup's ability is 1 + the ability id (POOL) */
    lead->gender = DUOFORGE_GENDER_MALE;
    lead->move_count = 4u;
    lead->moves[0].move_id = DFI_MOVE_KINGSSHIELD;
    lead->moves[1].move_id = DFI_MOVE_IRONHEAD;
    lead->moves[2].move_id = DFI_MOVE_PROTECT;
    lead->moves[3].move_id = DFI_MOVE_SHADOWBALL;
}

/* A battle of ctx built from `s` at the first turn boundary (the team selection done). */
static duoforge_battle *turn_battle_of(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s)
{
    duoforge_battle *b = df_make_battle(ctx, s);
    if (!DF_CHECK(t, b != NULL)) {
        return NULL;
    }
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    duoforge_step_result res;
    DF_CHECK(t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK);
    return b;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g66");

    /* The constants: protect_kind 2 is King's Shield (the tail's maximum), the Blade is the last pool forme. */
    DF_CHECK_EQ_U64(&t, DFI_PROTECT_KINGS_SHIELD, 2u);
    DF_CHECK_EQ_U64(&t, DFI_TAIL_PROTECT_KIND_MAX, 2u);
    DF_CHECK_EQ_U64(&t, DFI_PROTECT_SPIKY_SHIELD, 1u);
    DF_CHECK_EQ_U64(&t, DFI_SPECIAL_KINGS_SHIELD, DFI_SPECIAL_SKILL_SWAP + 1u); /* merged order: Steel Beam, Thunder Wave (G68) and Skill Swap (G70) come first */
    DF_CHECK_EQ_U64(&t, DFI_FORME_AEGISLASHBLADE, DFI_POOL_FORME_COUNT - 1u);

    /* The marks: King's Shield (move) and Stance Change (ability) are supported; Baneful Bunker stays unmarked. */
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_KINGSSHIELD] != 0u);
    DF_CHECK(&t, dfi_support.moves[DFI_MOVE_BANEFULBUNKER] == 0u);
    DF_CHECK(&t, dfi_support.abilities[DFI_ABILITY_STANCECHANGE] != 0u);
    DF_CHECK(&t, dfi_pool_moves[DFI_MOVE_KINGSSHIELD].special == DFI_SPECIAL_KINGS_SHIELD);

    /* The Blade row: the Shield's Aegislash as its base forme, the Blade's base stats (base[0] is HP, then Atk, Def, SpA, SpD,
     * Spe), the one legal ability, and no learnable move (battle-only: no set can hold it). */
    {
        const dfi_pool_forme_data *blade = &dfi_pool_formes[DFI_FORME_AEGISLASHBLADE];
        DF_CHECK_EQ_U64(&t, blade->base_forme, DFI_FORME_AEGISLASH);
        DF_CHECK_EQ_U64(&t, blade->base[0], 60u);
        DF_CHECK_EQ_U64(&t, blade->base[1], 140u);
        DF_CHECK_EQ_U64(&t, blade->base[2], 50u);
        DF_CHECK_EQ_U64(&t, blade->base[3], 140u);
        DF_CHECK_EQ_U64(&t, blade->base[4], 50u);
        DF_CHECK_EQ_U64(&t, blade->base[5], 60u);
        DF_CHECK_EQ_U64(&t, blade->is_mega, 0u);
        DF_CHECK_EQ_U64(&t, dfi_pool_formes[DFI_FORME_AEGISLASH].dex_num, blade->dex_num);
        uint32_t learn_bits = 0u;
        for (uint32_t k = 0u; k < DFI_POOL_LEARN_BYTES; ++k) {
            learn_bits |= (uint32_t)dfi_pool_forme_legal[DFI_FORME_AEGISLASHBLADE].learnable[k];
        }
        DF_CHECK_EQ_U64(&t, learn_bits, 0u);
    }

    /* The codec round trip of protect_kind 2 (King's Shield) on the first position of side 0: the decoder accepts it, the
     * decoded state has it, and the encoding comes back byte for byte. */
    {
        duoforge_context *kp = df_make_context(&df_config_pool);
        duoforge_battle_setup s;
        df_setup_teams(&s);
        duoforge_battle *b = turn_battle_of(&t, kp, &s);
        if (DF_CHECK(&t, b != NULL)) {
            b->sides[0].positions[0].flags = (uint8_t)((uint32_t)b->sides[0].positions[0].flags | DFI_VOL_PROTECT);
            b->tail.sides[0].positions[0].protect_kind = DFI_PROTECT_KINGS_SHIELD;
            uint8_t enc[DF_STATE_ENCODED_MAX];
            const size_t n = dfi_encode_unchecked(kp, b, enc);
            uint8_t in[DF_STATE_ENCODED_MAX];
            memcpy(in, enc, n);
            duoforge_battle *back = NULL;
            DF_CHECK_EQ_U64(&t, duoforge_battle_create_decoded(kp, in, n, &back), DUOFORGE_OK);
            if (DF_CHECK(&t, back != NULL)) {
                DF_CHECK_EQ_U64(&t, back->tail.sides[0].positions[0].protect_kind, DFI_PROTECT_KINGS_SHIELD);
                uint8_t again[DF_STATE_ENCODED_MAX];
                DF_CHECK_EQ_U64(&t, dfi_encode_unchecked(kp, back, again), n);
                DF_CHECK_BYTES(&t, again, enc, n, "the encoding of protect_kind 2 comes back byte for byte");
            }
            duoforge_battle_destroy(back);
        }
        duoforge_battle_destroy(b);
        duoforge_context_destroy(kp);
    }

    /* The strict stats rule and the temporary-forme refusal, on a battle whose side-0 lead is an Aegislash. The Blade's stats
     * are allowed ONLY for an Aegislash on the Blade forme (forme_now = its id + 1); every other case has the sheet's stats. */
    {
        duoforge_context *kp = df_make_context(&df_config_pool);
        duoforge_battle_setup s;
        aegislash_setup(&s);
        duoforge_battle *b = turn_battle_of(&t, kp, &s);
        if (DF_CHECK(&t, b != NULL)) {
            const uint32_t occ = b->sides[0].positions[0].occupant;
            DF_CHECK(&t, occ < DUOFORGE_MAX_ROSTER);
            dfi_member *m = &b->sides[0].members[occ];
            DF_CHECK_EQ_U64(&t, m->species_id, DFI_FORME_AEGISLASH);
            uint16_t sheet[DFI_MEMBER_STAT_COUNT];
            uint16_t blade[DFI_MEMBER_STAT_COUNT];
            memcpy(sheet, m->stats, sizeof sheet);
            DF_CHECK(&t, dfi_closure_member_forme_stats(m, DFI_FORME_AEGISLASHBLADE, blade));
            DF_CHECK(&t, memcmp(sheet, blade, sizeof sheet) != 0); /* the two formes have different stats */
            DF_CHECK(&t, duoforge_battle_check(kp, b) == DUOFORGE_OK); /* the sheet's forme with the sheet's stats: valid */

            /* (a) The Blade's stats under the Shield's forme (forme_now 0): refused. */
            memcpy(m->stats, blade, sizeof blade);
            DF_CHECK(&t, duoforge_battle_check(kp, b) != DUOFORGE_OK);

            /* (b) The Blade's forme with the sheet's stats: refused. */
            memcpy(m->stats, sheet, sizeof sheet);
            b->tail.sides[0].forme_now[occ] = (uint16_t)(DFI_FORME_AEGISLASHBLADE + 1u);
            DF_CHECK(&t, duoforge_battle_check(kp, b) != DUOFORGE_OK);

            /* (c) The Blade's forme with the Blade's stats: valid, and the position is a temporary forme in the public view. */
            memcpy(m->stats, blade, sizeof blade);
            DF_CHECK(&t, duoforge_battle_check(kp, b) == DUOFORGE_OK);
            uint32_t mask = 0u;
            DF_CHECK(&t, duoforge_battle_public_causes(kp, b, 0u, &mask) == DUOFORGE_OK);
            DF_CHECK(&t, (mask & DUOFORGE_PUBLIC_CAUSE_TEMP_FORME) != 0u);
            duoforge_public_state pub;
            DF_CHECK(&t, duoforge_battle_public(kp, b, 0u, &pub) == DUOFORGE_E_UNSUPPORTED);

            /* (d) Back to the sheet's forme and stats: valid, no temporary-forme cause, and the record is public again. */
            b->tail.sides[0].forme_now[occ] = 0u;
            memcpy(m->stats, sheet, sizeof sheet);
            DF_CHECK(&t, duoforge_battle_check(kp, b) == DUOFORGE_OK);
            mask = 0u;
            DF_CHECK(&t, duoforge_battle_public_causes(kp, b, 0u, &mask) == DUOFORGE_OK);
            DF_CHECK(&t, (mask & DUOFORGE_PUBLIC_CAUSE_TEMP_FORME) == 0u);
            DF_CHECK(&t, duoforge_battle_public(kp, b, 0u, &pub) == DUOFORGE_OK);

            /* (e) The species check of the strict rule: the opposing lead is not an Aegislash, and the Blade's forme with the
             * Blade's stats is still refused for it (the stats alone would pass). */
            const uint32_t occ1 = b->sides[1].positions[0].occupant;
            DF_CHECK(&t, occ1 < DUOFORGE_MAX_ROSTER);
            dfi_member *m1 = &b->sides[1].members[occ1];
            DF_CHECK(&t, m1->species_id != DFI_FORME_AEGISLASH);
            uint16_t sheet1[DFI_MEMBER_STAT_COUNT];
            uint16_t blade1[DFI_MEMBER_STAT_COUNT];
            memcpy(sheet1, m1->stats, sizeof sheet1);
            DF_CHECK(&t, dfi_closure_member_forme_stats(m1, DFI_FORME_AEGISLASHBLADE, blade1));
            memcpy(m1->stats, blade1, sizeof blade1);
            b->tail.sides[1].forme_now[occ1] = (uint16_t)(DFI_FORME_AEGISLASHBLADE + 1u);
            DF_CHECK(&t, duoforge_battle_check(kp, b) != DUOFORGE_OK);
            b->tail.sides[1].forme_now[occ1] = 0u;
            memcpy(m1->stats, sheet1, sizeof sheet1);
            DF_CHECK(&t, duoforge_battle_check(kp, b) == DUOFORGE_OK);
        }
        duoforge_battle_destroy(b);
        duoforge_context_destroy(kp);
    }

    return df_test_end(&t);
}
