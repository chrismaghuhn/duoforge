/*
 * duoforge.state.closure_setup (white-box parts marked): CLOSURE contexts,
 * setup validation of real sets, the support gate and the member invariant
 * of CLOSURE data (decision 0006 section 2).
 *
 * Expectations: the stat lines of decision 0004's sets as recomputed by
 * tools/research/verify_inventory.py (the same literals as
 * duoforge.data.closure_tables), the M2 target-class table T1 (which mirrors
 * the 36 team moves), the fingerprints of tools/state_model/state_v3_model.py
 * and the setup contract in include/duoforge/duoforge.h.
 */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "codec/state_codec.h"
#include "data/closure_tables.h"
#include "data/support_manifest.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"

/* HP Atk Def SpA SpD Spe of each member of df_setup_teams, base forme
 * (docs/research/mechanics-inventory.md section 1). */
static const uint16_t expected_stats[2][6][6] = {
    {
        {193, 194, 112, 72, 96, 113},  /* Rillaboom */
        {192, 140, 90, 63, 82, 167},   /* Staraptor */
        {202, 72, 128, 120, 165, 101}, /* Milotic */
        {181, 167, 124, 72, 123, 106}, /* Ceruledge */
        {164, 99, 80, 110, 100, 178},  /* Raichu */
        {179, 72, 117, 187, 127, 118}, /* Gholdengo */
    },
    {
        {197, 85, 95, 154, 120, 94},   /* Politoed */
        {182, 194, 160, 72, 111, 61},  /* Golisopod */
        {197, 112, 166, 145, 109, 114}, /* Archaludon */
        {224, 99, 121, 130, 107, 80},  /* Farigiraf */
        {169, 93, 116, 132, 105, 163}, /* Charizard */
        {202, 140, 99, 115, 126, 72},  /* Grimmsnarl */
    },
};
/* Members holding their own Mega Stone. */
static const uint8_t expected_stone[2][6] = {{0, 1, 0, 0, 1, 0}, {0, 1, 0, 0, 1, 0}};

#define FP_K1_HEX "09d8d247c926610b2c3957002644221c01cc07d268bfa98461575c3b1c6a8306"
#define FP_K2_HEX "36488dfd2614a4454dd427bc6a4998d4e18fa22d9cb5bdf8a85fca3b2a48477d"

static void create_fails(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s,
                         duoforge_status expected, const char *what)
{
    df_sentinel sentinel;
    duoforge_battle *const marker = (duoforge_battle *)(void *)&sentinel;
    duoforge_battle *out = marker;
    const duoforge_status st = duoforge_battle_create(ctx, s, &out);
    if (!DF_CHECK(t, st == expected && out == marker)) {
        fprintf(stderr, "  create %s: %s, expected %s\n", what, duoforge_status_name(st),
                duoforge_status_name(expected));
    }
}

/* White-box: the setup is invalid for the public create and for the
 * ungated build alike. */
static void invalid(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, const char *what)
{
    create_fails(t, ctx, s, DUOFORGE_E_INVALID_ARGUMENT, what);
    duoforge_battle *out = NULL;
    const duoforge_status st = dfi_battle_create_ungated(ctx, s, &out);
    if (!DF_CHECK(t, st == DUOFORGE_E_INVALID_ARGUMENT && out == NULL)) {
        fprintf(stderr, "  ungated %s: %s\n", what, duoforge_status_name(st));
    }
    duoforge_battle_destroy(out);
}

/* White-box: legal but gated. */
static void legal(df_test *t, const duoforge_context *ctx, const duoforge_battle_setup *s, const char *what)
{
    create_fails(t, ctx, s, DUOFORGE_E_UNSUPPORTED, what);
    duoforge_battle *out = NULL;
    const duoforge_status st = dfi_battle_create_ungated(ctx, s, &out);
    if (!DF_CHECK(t, st == DUOFORGE_OK && out != NULL)) {
        fprintf(stderr, "  ungated %s: %s\n", what, duoforge_status_name(st));
    }
    duoforge_battle_destroy(out);
}

static void expect_member_inv(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, bool bad,
                              const char *what)
{
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status st = dfi_state_check(ctx, b, &got);
    const bool ok = bad ? (st == DUOFORGE_E_INVARIANT && got == DFI_INV_MEMBER_EXTRA) : st == DUOFORGE_OK;
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  member case %s: %s (%s)\n", what, duoforge_status_name(st), dfi_invariant_name(got));
    }
}

static dfi_support_manifest full_manifest(void)
{
    dfi_support_manifest m;
    memset(&m, 1, sizeof m);
    return m;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.closure_setup");

    /* Contexts. */
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
    {
        uint8_t fp[DUOFORGE_DIGEST_SIZE];
        uint8_t want[DUOFORGE_DIGEST_SIZE];
        DF_CHECK(&t, duoforge_context_fingerprint(k1, fp) == DUOFORGE_OK);
        DF_CHECK(&t, df_hex_to_bytes(FP_K1_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp, want, sizeof fp, "K1 fingerprint");
        DF_CHECK(&t, duoforge_context_fingerprint(k2, fp) == DUOFORGE_OK);
        DF_CHECK(&t, df_hex_to_bytes(FP_K2_HEX, want, sizeof want));
        DF_CHECK_BYTES(&t, fp, want, sizeof fp, "K2 fingerprint");
        /* White-box: the canonical bytes carry the kind, the table counts and
         * the closure table hash. */
        uint8_t bytes[DFI_CONTEXT_BYTES_SIZE];
        dfi_context_canonical_bytes(k1, bytes);
        DF_CHECK(&t, bytes[24] == DUOFORGE_DATA_KIND_CLOSURE && bytes[27] == 16u && bytes[28] == 0u &&
                         bytes[29] == 37u && bytes[30] == 0u);
        DF_CHECK_BYTES(&t, bytes + DFI_CONTEXT_TABLE_HASH_OFF, dfi_closure_table_hash, DUOFORGE_DIGEST_SIZE,
                       "closure hash in the preimage");
        /* The closure target classes equal the M2 table T1 for the 36 team
         * moves; Struggle has the never-selectable class 10. */
        DF_CHECK_BYTES(&t, k1->move_target_classes, df_table_t1, sizeof df_table_t1, "closure classes = T1");
        DF_CHECK(&t, k1->move_target_classes[36] == 10u && k1->move_target_classes[37] == 0u);
        DF_CHECK(&t, k1->species_count == 16u && k1->move_count == 37u);
    }
    {
        /* Config validation for the closure kinds (atomic: *out untouched). */
        static const struct {
            duoforge_context_config c;
            duoforge_status expected;
            const char *what;
        } cases[] = {
            {{DUOFORGE_DATA_KIND_CLOSURE, 6u, 4u, 16u, 0u, NULL}, DUOFORGE_E_INVALID_ARGUMENT, "species count given"},
            {{DUOFORGE_DATA_KIND_CLOSURE, 6u, 4u, 0u, 37u, NULL}, DUOFORGE_E_INVALID_ARGUMENT, "move count given"},
            {{DUOFORGE_DATA_KIND_CLOSURE_DEV, 6u, 4u, 0u, 0u, df_table_t1}, DUOFORGE_E_INVALID_ARGUMENT,
             "table given"},
            {{DUOFORGE_DATA_KIND_CLOSURE, 7u, 4u, 0u, 0u, NULL}, DUOFORGE_E_INVALID_ARGUMENT, "roster 7"},
            {{DUOFORGE_DATA_KIND_CLOSURE, 6u, 0u, 0u, 0u, NULL}, DUOFORGE_E_INVALID_ARGUMENT, "brought 0"},
            {{4u, 6u, 4u, 0u, 0u, NULL}, DUOFORGE_E_INVALID_ARGUMENT, "data kind 4"},
            {{0u, 6u, 4u, 16u, 36u, df_table_t1}, DUOFORGE_E_INVALID_ARGUMENT, "data kind 0"},
            {{DUOFORGE_DATA_KIND_CLOSURE, 4u, 2u, 0u, 0u, NULL}, DUOFORGE_OK, "roster 4, brought 2"},
        };
        for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            df_sentinel sentinel;
            duoforge_context *const marker = (duoforge_context *)(void *)&sentinel;
            duoforge_context *out = marker;
            const duoforge_status st = duoforge_context_create(&cases[i].c, &out);
            const bool ok = cases[i].expected == DUOFORGE_OK ? (st == DUOFORGE_OK && out != marker)
                                                             : (st == cases[i].expected && out == marker);
            if (!DF_CHECK(&t, ok)) {
                fprintf(stderr, "  context case %s: %s\n", cases[i].what, duoforge_status_name(st));
            }
            if (st == DUOFORGE_OK) {
                duoforge_context_destroy(out);
            }
        }
    }

    /* The two reference teams are legal and gated: E_UNSUPPORTED from the
     * public create under both kinds, nothing allocated. */
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    create_fails(&t, k1, &teams, DUOFORGE_E_UNSUPPORTED, "reference teams (CLOSURE)");
    create_fails(&t, k2, &teams, DUOFORGE_E_UNSUPPORTED, "reference teams (CLOSURE_DEV)");
    /* The same setup is invalid under a SYNTHETIC context (closure fields). */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        create_fails(&t, c1, &teams, DUOFORGE_E_INVALID_ARGUMENT, "closure setup under SYNTHETIC");
        duoforge_context_destroy(c1);
    }

    /* White-box: what the teams would be. Derived stats, PP and stone flags,
     * stored ids, a TEAM_SELECTION state that passes the invariants. */
    duoforge_battle *b = NULL;
    DF_CHECK(&t, dfi_battle_create_ungated(k1, &teams, &b) == DUOFORGE_OK && b != NULL);
    if (b == NULL) {
        return df_test_end(&t);
    }
    DF_CHECK(&t, duoforge_battle_check(k1, b) == DUOFORGE_OK);
    DF_CHECK(&t, b->boundary_kind == DUOFORGE_BOUNDARY_TEAM_SELECTION && b->turn == 0u);
    for (unsigned s = 0; s < 2; ++s) {
        const duoforge_side_setup *src = &teams.sides[s];
        for (unsigned m = 0; m < 6; ++m) {
            const dfi_member *mem = &b->sides[s].members[m];
            const uint16_t *e = expected_stats[s][m];
            bool ok = mem->hp_max == e[0] && mem->hp == e[0];
            for (unsigned i = 0; i < 5; ++i) {
                ok = ok && mem->stats[i] == e[i + 1];
            }
            ok = ok && mem->species_id == src->members[m].species_id && mem->gender == src->members[m].gender &&
                 mem->nature == src->members[m].nature && mem->ability == src->members[m].ability &&
                 mem->item == src->members[m].item && mem->mega_capable == expected_stone[s][m] &&
                 mem->is_mega == 0u && mem->status == 0u && mem->item_consumed == 0u && mem->move_count == 4u;
            for (unsigned i = 0; i < 6; ++i) {
                ok = ok && mem->stat_points[i] == src->members[m].stat_points[i];
            }
            for (unsigned k = 0; k < 4; ++k) {
                const uint32_t id = src->members[m].moves[k].move_id;
                ok = ok && mem->moves[k].move_id == id && mem->moves[k].pp_max == dfi_closure_moves[id].pp_max &&
                     mem->moves[k].pp == mem->moves[k].pp_max;
            }
            if (!DF_CHECK(&t, ok)) {
                fprintf(stderr, "  member %u/%u differs from the set\n", s, m);
            }
        }
    }
    /* Champions PP spot checks (base PP capped at 20, then (pp / 5 + 1) * 4):
     * Protect 5 (Champions mod, data/mods/champions/moves.ts:765-768) -> 8,
     * Fake Out 10 -> 12, Tailwind 15 -> 16, Grassy Glide 20 -> 20. */
    DF_CHECK(&t, b->sides[0].members[1].moves[3].pp_max == 8u);  /* Staraptor Protect */
    DF_CHECK(&t, b->sides[0].members[0].moves[1].pp_max == 20u); /* Rillaboom Grassy Glide */
    DF_CHECK(&t, b->sides[0].members[0].moves[2].pp_max == 12u); /* Rillaboom Fake Out */
    DF_CHECK(&t, b->sides[0].members[1].moves[2].pp_max == 16u); /* Staraptor Tailwind */
    /* Codec round trip of a CLOSURE state. */
    {
        uint8_t enc[DUOFORGE_STATE_V3_ENCODED_SIZE];
        df_encode(k1, b, enc);
        uint8_t *in = df_heap_copy(enc, sizeof enc);
        duoforge_battle *d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(k1, in, sizeof enc, &d) == DUOFORGE_OK);
        bool eq = false;
        DF_CHECK(&t, duoforge_battle_equal(k1, b, d, &eq) == DUOFORGE_OK && eq);
        duoforge_battle_destroy(d);
        /* The same bytes under the other kind are a context mismatch. */
        DF_CHECK(&t, duoforge_battle_create_decoded(k2, in, sizeof enc, &d) == DUOFORGE_E_CONTEXT_MISMATCH);
        df_free(in);
    }

    /* Setup validation, one fault at a time (each on a fresh copy). */
    {
        duoforge_battle_setup s;
#define FRESH() (s = teams)
        FRESH();
        s.sides[0].members[1].species_id = 2u; /* Staraptor-Mega */
        invalid(&t, k1, &s, "Mega forme at setup");
        FRESH();
        s.sides[0].members[0].species_id = 16u;
        invalid(&t, k1, &s, "species 16");
        FRESH();
        s.sides[0].members[0].hp_max = 193u;
        invalid(&t, k1, &s, "hp_max given");
        FRESH();
        s.sides[0].members[1].mega_capable = 1u;
        invalid(&t, k1, &s, "stone flag given");
        FRESH();
        s.sides[0].members[0].moves[0].pp_max = 12u;
        invalid(&t, k1, &s, "pp_max given");
        FRESH();
        s.sides[0].members[0].moves[3].move_id = 7u; /* Protect is not in Rillaboom's set */
        invalid(&t, k1, &s, "move outside the set");
        FRESH();
        s.sides[0].members[0].moves[3].move_id = 0u;
        invalid(&t, k1, &s, "repeated move");
        FRESH();
        s.sides[0].members[0].move_count = 0u;
        invalid(&t, k1, &s, "move count 0");
        FRESH();
        s.sides[0].members[0].move_count = 5u;
        invalid(&t, k1, &s, "move count 5");
        FRESH();
        s.sides[0].members[0].move_count = 3u; /* slot 3 still holds a move */
        invalid(&t, k1, &s, "used slot beyond the count");
        FRESH();
        s.sides[0].members[5].gender = DUOFORGE_GENDER_MALE; /* Gholdengo is genderless */
        invalid(&t, k1, &s, "gender on a genderless species");
        FRESH();
        s.sides[1].members[5].gender = DUOFORGE_GENDER_FEMALE; /* Grimmsnarl is male-only */
        invalid(&t, k1, &s, "female Grimmsnarl");
        FRESH();
        s.sides[0].members[0].gender = DUOFORGE_GENDER_NONE;
        invalid(&t, k1, &s, "genderless Rillaboom");
        FRESH();
        s.sides[0].members[0].gender = 0u;
        invalid(&t, k1, &s, "gender unspecified");
        FRESH();
        s.sides[0].members[0].nature = 25u;
        invalid(&t, k1, &s, "nature 25");
        FRESH();
        s.sides[0].members[0].stat_points[2] = 33u;
        invalid(&t, k1, &s, "33 Stat Points");
        FRESH();
        s.sides[0].members[0].stat_points[3] = 1u; /* 67 in total */
        invalid(&t, k1, &s, "67 Stat Points in total");
        FRESH();
        s.sides[0].members[0].ability = 2u; /* Intimidate on Rillaboom */
        invalid(&t, k1, &s, "ability of another forme");
        FRESH();
        s.sides[0].members[0].ability = 0u;
        invalid(&t, k1, &s, "No Ability under CLOSURE");
        legal(&t, k2, &s, "No Ability under CLOSURE_DEV");
        FRESH();
        s.sides[0].members[0].ability = 17u;
        invalid(&t, k2, &s, "ability id out of range");
        FRESH();
        s.sides[0].members[0].item = 12u;
        invalid(&t, k1, &s, "item id out of range");
        FRESH();
        s.sides[0].members[0].item = 0u;
        legal(&t, k1, &s, "no item");
        FRESH();
        s.sides[0].members[0].item = 2u; /* Staraptite on Rillaboom: legal, no stone flag */
        s.sides[0].members[1].item = 1u; /* Miracle Seed on Staraptor */
        legal(&t, k1, &s, "a Mega Stone of another species");
        FRESH();
        s.sides[0].members[0].item = 3u; /* a second Sitrus Berry */
        invalid(&t, k1, &s, "Item Clause");
        FRESH();
        s.sides[1].members[2] = s.sides[1].members[0]; /* a second Politoed, other item below */
        s.sides[1].members[2].item = 0u;
        invalid(&t, k1, &s, "Species Clause");
        FRESH();
        s.sides[0].members[3] = s.sides[0].members[1]; /* both on one side: same species, same item */
        invalid(&t, k1, &s, "duplicate member");
        FRESH();
        s.sides[0].member_count = 5u; /* member 5 must then be all-zero */
        invalid(&t, k1, &s, "unused member not zero");
        FRESH();
        s.sides[0].member_count = 5u;
        memset(&s.sides[0].members[5], 0, sizeof s.sides[0].members[5]);
        s.sides[0].members[5].nature = 1u;
        invalid(&t, k1, &s, "unused member with a nature");
        FRESH();
        s.sides[0].member_count = 5u;
        memset(&s.sides[0].members[5], 0, sizeof s.sides[0].members[5]);
        legal(&t, k1, &s, "five members");
        FRESH();
        s.sides[0].members[0].move_count = 1u; /* one move is enough */
        s.sides[0].members[0].moves[1].move_id = 0u;
        s.sides[0].members[0].moves[2].move_id = 0u;
        s.sides[0].members[0].moves[3].move_id = 0u;
        legal(&t, k1, &s, "one move");
        FRESH();
        s.rng_initseq = UINT64_C(0x8000000000000000);
        invalid(&t, k1, &s, "rng initseq");
#undef FRESH
    }
    /* SYNTHETIC setups must leave every CLOSURE field zero. */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle_setup g;
        for (unsigned f = 0; f < 5; ++f) {
            df_setup_g1(&g);
            duoforge_member_setup *m = &g.sides[1].members[f < 4 ? 0 : 5]; /* member 5 is unused */
            switch (f) {
            case 0:
                m->gender = 1u;
                break;
            case 1:
                m->nature = 1u;
                break;
            case 2:
                m->stat_points[5] = 1u;
                break;
            case 3:
                m->ability = 1u;
                break;
            default:
                m->item = 1u;
                break;
            }
            create_fails(&t, c1, &g, DUOFORGE_E_INVALID_ARGUMENT, "closure field under SYNTHETIC");
        }
        duoforge_context_destroy(c1);
    }

    /* The gate (white-box, with test manifests). */
    {
        dfi_support_manifest m = full_manifest();
        DF_CHECK(&t, dfi_closure_setup_supported(&m, &teams));
        DF_CHECK(&t, !dfi_closure_setup_supported(&dfi_support, &teams)); /* abilities: not yet */
        /* The manifest of this build, pinned: the turn core, switching and the
         * moves of steps 2 to 4. A step that implements a mechanic changes this
         * deliberately. */
        {
            static const uint32_t step2_moves[] = {
                DFI_MOVE_HIGHHORSEPOWER, DFI_MOVE_PROTECT,     DFI_MOVE_MUDDYWATER, DFI_MOVE_COIL,
                DFI_MOVE_SHADOWSNEAK,    DFI_MOVE_SWORDSDANCE, DFI_MOVE_FOCUSBLAST, DFI_MOVE_SHADOWBALL,
                DFI_MOVE_NASTYPLOT,      DFI_MOVE_DRILLRUN,    DFI_MOVE_DRAGONPULSE, DFI_MOVE_SNARL,
                DFI_MOVE_PSYCHIC,        DFI_MOVE_SPIRITBREAK, DFI_MOVE_ICEBEAM,    DFI_MOVE_HYPNOSIS,
                DFI_MOVE_ZAPCANNON,      DFI_MOVE_IRONHEAD,    DFI_MOVE_HEATWAVE,   DFI_MOVE_HURRICANE,
            };
            dfi_support_manifest want;
            memset(&want, 0, sizeof want);
            want.turn_core = 1u;
            want.switching = 1u;
            for (size_t i = 0; i < sizeof step2_moves / sizeof step2_moves[0]; ++i) {
                want.moves[step2_moves[i]] = 1u;
            }
            DF_CHECK_BYTES(&t, (const uint8_t *)&dfi_support, (const uint8_t *)&want, sizeof want, "manifest");
        }
        m.turn_core = 0u;
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.switching = 0u; /* checked when a step needs it, not at setup */
        DF_CHECK(&t, dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.moves[DFI_MOVE_PARTINGSHOT] = 0u;
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.moves[DFI_MOVE_STRUGGLE] = 0u; /* part of the core, never in a set */
        DF_CHECK(&t, dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.abilities[DFI_ABILITY_GOODASGOLD] = 0u;
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.items[DFI_ITEM_LEFTOVERS] = 0u;
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.mega_evolution = 0u;
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        m = full_manifest();
        m.abilities[DFI_ABILITY_DROUGHT] = 0u; /* Charizard-Mega-Y's ability */
        DF_CHECK(&t, !dfi_closure_setup_supported(&m, &teams));
        /* Without the stones, Mega Evolution and the Mega abilities are not
         * needed; without abilities (development) neither are those. */
        duoforge_battle_setup s = teams;
        for (unsigned side = 0; side < 2; ++side) {
            for (unsigned i = 0; i < 6; ++i) {
                if (expected_stone[side][i] != 0u) {
                    s.sides[side].members[i].item = 0u;
                }
                s.sides[side].members[i].ability = 0u;
            }
        }
        m = full_manifest();
        m.mega_evolution = 0u;
        memset(m.abilities, 0, sizeof m.abilities);
        m.items[DFI_ITEM_STARAPTITE] = 0u; /* the removed stones */
        m.items[DFI_ITEM_RAICHUNITEY] = 0u;
        m.items[DFI_ITEM_GOLISOPITE] = 0u;
        m.items[DFI_ITEM_CHARIZARDITEY] = 0u;
        DF_CHECK(&t, dfi_closure_setup_supported(&m, &s));
        legal(&t, k2, &s, "development teams without abilities and stones");
    }

    /* The member invariant of CLOSURE data (white-box edits of the built
     * state; MEMBER_EXTRA is the reported id). */
    {
        duoforge_battle *w = NULL;
        DF_CHECK(&t, duoforge_battle_clone(k1, b, &w) == DUOFORGE_OK);
#define RESET() DF_CHECK(&t, duoforge_battle_copy(k1, w, b) == DUOFORGE_OK)
        dfi_member *raichu = &w->sides[0].members[4];
        dfi_member *rilla = &w->sides[0].members[0];
        expect_member_inv(&t, k1, w, false, "as built");
        rilla->species_id = 2u; /* a Mega forme as base species */
        expect_member_inv(&t, k1, w, true, "Mega forme as species");
        RESET();
        rilla->gender = DFI_GENDER_NONE;
        expect_member_inv(&t, k1, w, true, "illegal gender");
        RESET();
        rilla->nature = 25u;
        expect_member_inv(&t, k1, w, true, "nature 25");
        RESET();
        rilla->stat_points[0] = 33u;
        expect_member_inv(&t, k1, w, true, "33 Stat Points");
        RESET();
        rilla->stat_points[3] = 1u;
        expect_member_inv(&t, k1, w, true, "67 Stat Points");
        RESET();
        rilla->hp_max = 194u;
        rilla->hp = 1u;
        expect_member_inv(&t, k1, w, true, "hp_max off the formula");
        RESET();
        rilla->stats[4] = 114u;
        expect_member_inv(&t, k1, w, true, "Speed off the formula");
        RESET();
        rilla->hp = 1u; /* current HP is free */
        expect_member_inv(&t, k1, w, false, "damaged");
        RESET();
        rilla->moves[3].move_id = 7u; /* Protect, with its own correct PP maximum */
        rilla->moves[3].pp_max = 8u;
        rilla->moves[3].pp = 8u;
        expect_member_inv(&t, k1, w, true, "move outside the set");
        RESET();
        rilla->moves[1].move_id = 0u;
        expect_member_inv(&t, k1, w, true, "repeated move");
        RESET();
        rilla->moves[0].pp_max = 17u; /* Wood Hammer: 15 -> 16 */
        expect_member_inv(&t, k1, w, true, "pp_max off the rule");
        RESET();
        rilla->moves[0].pp = 0u; /* PP use is free */
        expect_member_inv(&t, k1, w, false, "PP used");
        RESET();
        rilla->ability = 2u;
        expect_member_inv(&t, k1, w, true, "wrong ability");
        RESET();
        rilla->ability = 0u;
        expect_member_inv(&t, k1, w, true, "No Ability under CLOSURE");
        RESET();
        rilla->item = 12u;
        expect_member_inv(&t, k1, w, true, "item out of range");
        RESET();
        rilla->item_consumed = 2u;
        expect_member_inv(&t, k1, w, true, "consumed flag 2");
        RESET();
        rilla->item = 0u;
        rilla->item_consumed = 1u;
        expect_member_inv(&t, k1, w, true, "consumed without an item");
        RESET();
        rilla->item_consumed = 1u; /* a consumed Miracle Seed: structurally fine */
        expect_member_inv(&t, k1, w, false, "item consumed");
        RESET();
        raichu->mega_capable = 0u;
        expect_member_inv(&t, k1, w, true, "stone flag off the item");
        RESET();
        rilla->mega_capable = 1u;
        expect_member_inv(&t, k1, w, true, "stone flag without a stone");
        RESET();
        rilla->is_mega = 1u;
        expect_member_inv(&t, k1, w, true, "Mega without a stone");
        RESET();
        raichu->is_mega = 2u;
        expect_member_inv(&t, k1, w, true, "Mega flag 2");
        RESET();
        raichu->is_mega = 1u; /* base stats and ability left: inconsistent */
        expect_member_inv(&t, k1, w, true, "Mega with base stats");
        /* Raichu-Mega-Y (decision 0004 line, mechanics inventory):
         * 164 108 80 180 100 200, ability Raichu-Mega-Y's (+1). */
        static const uint16_t mega_stats[5] = {108u, 80u, 180u, 100u, 200u};
        for (unsigned i = 0; i < 5; ++i) {
            raichu->stats[i] = mega_stats[i];
        }
        expect_member_inv(&t, k1, w, true, "Mega stats with the base ability");
        raichu->ability = dfi_closure_formes[DFI_FORME_RAICHUMEGAY].ability;
        raichu->ability++;
        expect_member_inv(&t, k1, w, false, "Raichu-Mega-Y");
        RESET();
        rilla->status = 5u;
        expect_member_inv(&t, k1, w, true, "status 5");
        RESET();
        rilla->status = DFI_STATUS_SLP;
        expect_member_inv(&t, k1, w, true, "asleep without a counter");
        rilla->status_counter = 3u;
        expect_member_inv(&t, k1, w, false, "asleep for up to 3 turns");
        rilla->status_counter = 4u;
        expect_member_inv(&t, k1, w, true, "sleep counter 4");
        RESET();
        rilla->status = DFI_STATUS_FRZ;
        rilla->status_counter = 1u;
        expect_member_inv(&t, k1, w, false, "frozen");
        RESET();
        rilla->status = DFI_STATUS_PAR;
        rilla->status_counter = 1u;
        expect_member_inv(&t, k1, w, true, "paralysis with a counter");
        rilla->status_counter = 0u;
        expect_member_inv(&t, k1, w, false, "paralysed");
        RESET();
        /* Under CLOSURE_DEV, No Ability is a legal current ability. */
        {
            duoforge_battle_setup s = teams;
            s.sides[0].members[0].ability = 0u;
            duoforge_battle *d = NULL;
            DF_CHECK(&t, dfi_battle_create_ungated(k2, &s, &d) == DUOFORGE_OK);
            expect_member_inv(&t, k2, d, false, "No Ability under CLOSURE_DEV");
            duoforge_battle_destroy(d);
        }
#undef RESET
        duoforge_battle_destroy(w);
    }

    duoforge_battle_destroy(b);
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    return df_test_end(&t);
}
