/*
 * The reference teams of decision 0004 as battle setups (M7, decision
 * 0013): Team A and Team B in the four pairings of the certified profile
 * (decision 0010). Moved from the test support, which now calls it.
 */
#include <duoforge/duoforge.h>

#include <string.h>

/* One member: species, gender, nature, Stat Points (HP, Atk, Def, SpA, SpD,
 * Spe), ability and item ids of the generated tables, moves. */
typedef struct dfi_reference_set {
    uint32_t species;
    uint32_t gender;
    uint32_t nature;
    uint32_t sp[6];
    uint32_t ability;
    uint32_t item;
    uint32_t moves[4];
} dfi_reference_set;

/* Ids from src/data/closure_tables.h; Stat Points and natures from the
 * pastes in decision 0004. Genders: Grimmsnarl is male in the paste and
 * male-only; Gholdengo is genderless; the others were chosen for the tests
 * (the owner specifies gender in every fixture). */
static const dfi_reference_set dfi_team_a[6] = {
    {0u, 1u, 0u, {18u, 32u, 2u, 0u, 6u, 8u}, 0u, 0u, {0u, 1u, 2u, 3u}},        /* Rillaboom @ Miracle Seed */
    {1u, 2u, 11u, {32u, 0u, 0u, 0u, 2u, 32u}, 1u, 1u, {4u, 5u, 6u, 7u}},      /* Staraptor @ Staraptite */
    {3u, 2u, 4u, {32u, 0u, 29u, 0u, 5u, 0u}, 2u, 2u, {8u, 9u, 10u, 11u}},     /* Milotic @ Sitrus Berry */
    {4u, 1u, 0u, {31u, 7u, 24u, 0u, 3u, 1u}, 3u, 3u, {12u, 13u, 14u, 7u}},    /* Ceruledge @ Grassy Seed */
    {5u, 2u, 24u, {29u, 0u, 5u, 0u, 0u, 32u}, 4u, 4u, {15u, 16u, 2u, 7u}},    /* Raichu @ Raichunite Y */
    {7u, 3u, 15u, {17u, 0u, 2u, 17u, 16u, 14u}, 5u, 5u, {17u, 18u, 19u, 7u}}, /* Gholdengo @ Life Orb */
};
static const dfi_reference_set dfi_team_b[6] = {
    {8u, 1u, 15u, {32u, 0u, 0u, 30u, 0u, 4u}, 6u, 6u, {20u, 8u, 10u, 7u}},       /* Politoed @ Mystic Water */
    {9u, 2u, 0u, {32u, 32u, 0u, 0u, 1u, 1u}, 7u, 7u, {21u, 22u, 23u, 7u}},       /* Golisopod @ Golisopite */
    {11u, 1u, 2u, {32u, 0u, 1u, 0u, 24u, 9u}, 8u, 8u, {24u, 25u, 26u, 7u}},      /* Archaludon @ Leftovers */
    {12u, 2u, 2u, {29u, 0u, 20u, 0u, 17u, 0u}, 9u, 2u, {27u, 28u, 29u, 7u}},     /* Farigiraf @ Sitrus Berry */
    {13u, 1u, 24u, {16u, 0u, 18u, 3u, 0u, 29u}, 10u, 9u, {30u, 20u, 31u, 7u}},   /* Charizard @ Charizardite Y */
    {15u, 1u, 22u, {32u, 0u, 14u, 0u, 20u, 0u}, 11u, 10u, {32u, 33u, 34u, 35u}}, /* Grimmsnarl @ Light Clay */
};

static void dfi_put_team(duoforge_side_setup *side, const dfi_reference_set *team)
{
    side->member_count = 6u;
    for (uint32_t m = 0u; m < 6u; ++m) {
        duoforge_member_setup *dst = &side->members[m];
        dst->species_id = team[m].species;
        dst->gender = team[m].gender;
        dst->nature = team[m].nature;
        for (uint32_t i = 0u; i < 6u; ++i) {
            dst->stat_points[i] = team[m].sp[i];
        }
        dst->ability = team[m].ability + 1u;
        dst->item = team[m].item + 1u;
        dst->move_count = 4u;
        for (uint32_t k = 0u; k < 4u; ++k) {
            dst->moves[k].move_id = team[m].moves[k];
        }
    }
}

duoforge_status duoforge_reference_setup(uint32_t pairing, duoforge_battle_setup *out)
{
    static const dfi_reference_set *const sides[4][2] = {
        {dfi_team_a, dfi_team_b}, {dfi_team_b, dfi_team_a}, {dfi_team_a, dfi_team_a}, {dfi_team_b, dfi_team_b}};
    if (out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (pairing > 3u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    duoforge_battle_setup s;
    memset(&s, 0, sizeof s);
    s.rng_initstate = 2026u;
    s.rng_initseq = 1001u;
    dfi_put_team(&s.sides[0], sides[pairing][0]);
    dfi_put_team(&s.sides[1], sides[pairing][1]);
    *out = s;
    return DUOFORGE_OK;
}
