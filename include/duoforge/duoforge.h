#ifndef DUOFORGE_DUOFORGE_H
#define DUOFORGE_DUOFORGE_H
/*
 * DuoForge public API -- PROVISIONAL (combat closure, step 1). Not a frozen
 * ABI (docs/decisions/0002, 0005, 0006).
 *
 * The library holds no mutable global state. A context is immutable after
 * creation and is designed to be shareable read-only across threads; this is
 * not yet tested under concurrency (M6). A battle handle must not be used
 * concurrently. Public input structs are read exactly once per call.
 *
 * PRIVILEGED: encode, decode, digest, equal, check and reseed operate on the
 * full hidden state (including the gameplay RNG). Their outputs are
 * diagnostics, replay or search-host artifacts and must never be
 * model-facing (no observations, features or candidate ids).
 *
 * Failure atomicity: on any non-OK return no battle, context or RNG state is
 * mutated, no caller buffer is written and nothing is allocated or leaked.
 * The only out-parameter written on error is the required count of a
 * model-facing query on E_CAPACITY (decision 0005 section 7).
 *
 * Combat runs for CLOSURE, TEAM_C and POOL data (decisions 0006 section 4,
 * 0009, 0015): TURN, REPLACEMENT and PIVOT bundles execute the turn of the
 * combat closure; under SYNTHETIC data every combat bundle is rejected with
 * E_UNSUPPORTED.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VERSION_MAJOR 0
#define DUOFORGE_VERSION_MINOR 37
#define DUOFORGE_VERSION_PATCH 0
#define DUOFORGE_VERSION_STRING "0.37.0"

/* Identifiers of the artifacts that exist now (registry: decisions 0002, 0005, 0006). */
#define DUOFORGE_SEMANTICS_ID           3u   /* "duoforge-m3-closure" */
#define DUOFORGE_CONTEXT_SCHEMA_VERSION 3u
#define DUOFORGE_STATE_SCHEMA_VERSION   3u
#define DUOFORGE_STATE_V3_ENCODED_SIZE  1009u /* schema 3 only; size buffers via duoforge_battle_encoded_size */
#define DUOFORGE_DIGEST_SIZE            32u

/* Structural capacities of state schema 3 (initial profile bound). */
#define DUOFORGE_SIDE_COUNT       2u
#define DUOFORGE_ACTIVE_PER_SIDE  2u
#define DUOFORGE_MAX_ROSTER       6u
#define DUOFORGE_MAX_MOVE_SLOTS   4u
#define DUOFORGE_ROSTER_NONE      0xFFu /* "no member" */

/*
 * Status codes. Values 0..10 are stable since M1; 11 and 12 were added in M2.
 * Renumbering before the ABI-stability decision is a deliberate, reviewed
 * change (docs/decisions/0002).
 */
typedef uint32_t duoforge_status;
#define DUOFORGE_OK                   0u
#define DUOFORGE_E_NULL_ARGUMENT      1u  /* a required pointer argument is NULL */
#define DUOFORGE_E_INVALID_ARGUMENT   2u  /* config/setup/bundle value outside its domain */
#define DUOFORGE_E_CONTEXT_MISMATCH   3u  /* handle/encoding bound to another context fingerprint */
#define DUOFORGE_E_CAPACITY           4u  /* caller buffer too small; encode writes nothing */
#define DUOFORGE_E_MALFORMED          5u  /* encoded bytes structurally or semantically invalid */
#define DUOFORGE_E_SCHEMA_MISMATCH    6u  /* wrong artifact kind or unsupported schema version */
#define DUOFORGE_E_SEMANTICS_MISMATCH 7u  /* encoded under another semantics id */
#define DUOFORGE_E_INVARIANT          8u  /* internal consistency failure (engine bug): state
                                             invariant or internal contract violated */
#define DUOFORGE_E_EXHAUSTED          9u  /* a monotonic counter would overflow */
#define DUOFORGE_E_OUT_OF_MEMORY      10u
#define DUOFORGE_E_UNSUPPORTED        11u /* documented not-implemented path (e.g. combat in M2);
                                             nothing was mutated */
#define DUOFORGE_E_STALE_EPOCH        12u /* a response carries another request epoch */

const char *duoforge_version_string(void);
/* "DUOFORGE_OK", ...; any other value gives "DUOFORGE_STATUS_UNKNOWN". */
const char *duoforge_status_name(duoforge_status status);

/* ---- synthetic move target classes (decision 0005 section 4) ----
   1..5 take a target selector; 6..9 take DUOFORGE_TARGET_NONE. */
#define DUOFORGE_TARGET_CLASS_NORMAL                1u /* ally and both foe positions */
#define DUOFORGE_TARGET_CLASS_ANY                   2u /* every position except self */
#define DUOFORGE_TARGET_CLASS_ADJACENT_ALLY         3u /* ally */
#define DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF 4u /* self, ally */
#define DUOFORGE_TARGET_CLASS_ADJACENT_FOE          5u /* both foe positions */
#define DUOFORGE_TARGET_CLASS_SELF                  6u
#define DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES     7u
#define DUOFORGE_TARGET_CLASS_ALLY_SIDE             8u
#define DUOFORGE_TARGET_CLASS_ALL                   9u
#define DUOFORGE_TARGET_CLASS_COUNT                 9u
/* The classes of the pool rows that a synthetic table never has and that the request API never resolves; they appear in
   duoforge_move_static.target_class only (decision 0020). DUOFORGE_TARGET_CLASS_COUNT stays 9 for the request API. */
#define DUOFORGE_TARGET_CLASS_RANDOM_NORMAL         10u /* Struggle: a random foe, never selectable */
#define DUOFORGE_TARGET_CLASS_ALL_ADJACENT          11u /* every adjacent Pokemon, foes and ally (Earthquake) */
#define DUOFORGE_TARGET_CLASS_SCRIPTED              12u /* the target is the last attacker (Counter, Mirror Coat) */
#define DUOFORGE_TARGET_CLASS_ALLY_TEAM             13u /* the user's whole party (Heal Bell) */
#define DUOFORGE_TARGET_CLASS_ALLIES                14u /* the user and its ally (Life Dew) */
#define DUOFORGE_TARGET_CLASS_FOE_SIDE              15u /* the foes' side of the field (Spikes) */
#define DUOFORGE_TARGET_CLASS_STATIC_COUNT          15u /* the largest target_class of duoforge_move_static */
#define DUOFORGE_TARGET_NONE 0xFFu /* selector value for classes without a choosable target */

/* ---- decision boundaries (decision 0005 section 1) ---- */
#define DUOFORGE_BOUNDARY_TEAM_SELECTION 1u
#define DUOFORGE_BOUNDARY_TURN           2u
#define DUOFORGE_BOUNDARY_REPLACEMENT    3u /* end of turn: fainted positions with a reserve, Emergency Exit */
#define DUOFORGE_BOUNDARY_PIVOT          4u /* mid-turn switch: Parting Shot, Emergency Exit (decision 0006) */
#define DUOFORGE_BOUNDARY_TERMINAL       5u /* the battle is over: nobody is requested (decision 0006) */
#define DUOFORGE_BOUNDARY_COUNT          5u

/* ---- immutable context (decision 0006 section 2) ---- */
#define DUOFORGE_DATA_KIND_SYNTHETIC   1u /* synthetic ids and target classes; no combat ever */
#define DUOFORGE_DATA_KIND_CLOSURE     2u /* the generated closure tables; format-legal sets only;
                                             the certified profile (decision 0010): max_roster 6,
                                             brought_count 4, exactly 6 members per side */
#define DUOFORGE_DATA_KIND_CLOSURE_DEV 3u /* the closure tables; as CLOSURE, but a member may have
                                             No Ability and a side registers brought_count to
                                             max_roster members (development fixtures) */
#define DUOFORGE_DATA_KIND_TEAM_C      4u /* the extended tables, closure plus Team C (decision 0009);
                                             the CLOSURE rules and profile over them */
#define DUOFORGE_DATA_KIND_TEAM_C_DEV  5u /* the extended tables; as CLOSURE_DEV over them
                                             (development fixtures) */
#define DUOFORGE_DATA_KIND_POOL        6u /* the pool tables, the growing tables of the content
                                             expansion (decision 0015): the extended tables as
                                             their prefix, then the rows the steps add; the
                                             CLOSURE rules and profile over them, except that a
                                             member's moves are ones its forme learns and its
                                             ability one it may have, not the forme's one set.
                                             Its fingerprint changes with every change of the
                                             pool data (the CLOSURE and TEAM_C ones never do) */
#define DUOFORGE_DATA_KIND_POOL_DEV    7u /* the pool tables; as CLOSURE_DEV over them, with
                                             POOL's moves and abilities (development fixtures) */
typedef struct duoforge_context duoforge_context;
typedef struct duoforge_context_config {
    uint32_t data_kind;     /* DUOFORGE_DATA_KIND_* */
    uint32_t max_roster;    /* 1..DUOFORGE_MAX_ROSTER */
    uint32_t brought_count; /* 1..max_roster; picked at TEAM_SELECTION */
    uint32_t species_count; /* SYNTHETIC: 1..65535, species ids 0..species_count-1; CLOSURE, TEAM_C, POOL: 0 */
    uint32_t move_count;    /* SYNTHETIC: 1..65535, move ids 0..move_count-1; CLOSURE, TEAM_C, POOL: 0 */
    /* SYNTHETIC: move_count bytes, each a DUOFORGE_TARGET_CLASS_* value 1..9;
       copied at create (read once) and hashed into the fingerprint.
       CLOSURE, TEAM_C and POOL kinds: NULL (the generated tables are built in). */
    const uint8_t *move_target_classes;
} duoforge_context_config;
/* Checks: NULL(config, out) -> INVALID_ARGUMENT (fields in order, including
   a table given for a CLOSURE kind) -> NULL(synthetic table) ->
   INVALID_ARGUMENT (table entries) -> OUT_OF_MEMORY. */
duoforge_status duoforge_context_create(const duoforge_context_config *config,
                                        duoforge_context **out_context);
void duoforge_context_destroy(duoforge_context *context); /* NULL is a no-op */
/* SHA-256 of the canonical context bytes: semantics id, context schema,
   structural constants, config and the SHA-256 of the target-class table
   (SYNTHETIC), of the generated closure tables (CLOSURE kinds), of the
   extended tables (TEAM_C kinds) or of the pool tables with their family
   columns (POOL kinds). Independent of platform and build. */
duoforge_status duoforge_context_fingerprint(const duoforge_context *context,
                                             uint8_t out_fingerprint[DUOFORGE_DIGEST_SIZE]);

/* ---- battle setup. Every entry at or after a count must be all-zero. A
   battle starts at TEAM_SELECTION with an empty brought set and empty
   positions (decision 0005 section 2).
   SYNTHETIC: species, hp_max, moves with pp_max and the stone flag are
   caller inputs; the CLOSURE fields must be 0.
   CLOSURE kinds (decision 0006 section 2): species is a base forme of the
   closure tables; gender, nature, Stat Points, ability, item and 1 to 4
   moves of the forme's set; hp_max, pp_max and mega_capable must be 0
   because the engine derives stats, PP and the stone flag. Species Clause
   and Item Clause hold per side. A legal team whose mechanics are not all
   implemented yet is rejected with E_UNSUPPORTED.
   TEAM_C kinds (decision 0009): the same rules over the extended tables, so
   a side may mix closure and Team C members and hold any of their items.
   POOL kinds (decision 0015): the same rules over the pool tables, except
   the set rule: a member's 1 to 4 moves are moves of the tables that its
   forme learns (the Champions learnsets), and its ability is one of the
   forme's legal abilities. The other kinds keep the forme's one set. An id
   beyond the tables of the kind is E_INVALID_ARGUMENT, so a pool item is
   out of range under the CLOSURE and TEAM_C kinds. A move, item or ability
   whose mechanic is not marked in the support manifest is E_UNSUPPORTED
   after all validation. ---- */
#define DUOFORGE_GENDER_MALE   1u
#define DUOFORGE_GENDER_FEMALE 2u
#define DUOFORGE_GENDER_NONE   3u /* genderless species */
#define DUOFORGE_STAT_POINTS_MAX       32u /* per stat */
#define DUOFORGE_STAT_POINTS_TOTAL_MAX 66u /* per member */
typedef struct duoforge_move_setup {
    uint32_t move_id; /* < context move_count; CLOSURE: a move of the forme's set; POOL: a move it learns */
    uint32_t pp_max;  /* SYNTHETIC: 1..255; CLOSURE: 0 */
} duoforge_move_setup;
typedef struct duoforge_member_setup {
    uint32_t species_id;   /* < context species_count; CLOSURE: a base forme id */
    uint32_t hp_max;       /* SYNTHETIC: 1..65535; CLOSURE: 0 */
    uint32_t move_count;   /* 1..DUOFORGE_MAX_MOVE_SLOTS */
    uint32_t mega_capable; /* SYNTHETIC: 0/1 stand-in for "holds a matching Mega Stone"; CLOSURE: 0 */
    duoforge_move_setup moves[DUOFORGE_MAX_MOVE_SLOTS];
    uint32_t gender;         /* CLOSURE: DUOFORGE_GENDER_*, legal for the species */
    uint32_t nature;         /* CLOSURE: nature id 0..24 */
    uint32_t stat_points[6]; /* CLOSURE: HP, Atk, Def, SpA, SpD, Spe */
    uint32_t ability;        /* CLOSURE: 1 + the forme's ability id; POOL: 1 + one of its legal abilities;
                                0 = No Ability (the DEV kinds only) */
    uint32_t item;           /* CLOSURE: 1 + item id; 0 = no item */
} duoforge_member_setup;
typedef struct duoforge_side_setup {
    uint32_t member_count; /* brought_count..max_roster; registered roster, stable order */
    duoforge_member_setup members[DUOFORGE_MAX_ROSTER];
} duoforge_side_setup;
typedef struct duoforge_battle_setup {
    uint64_t rng_initstate;
    uint64_t rng_initseq; /* must be < 2^63 (decision 0001) */
    duoforge_side_setup sides[DUOFORGE_SIDE_COUNT];
} duoforge_battle_setup;

/* ---- data query: names and legality per context (the data kinds of decisions
   0006, 0009 and 0015) ----
   What a caller needs to build a setup that the context accepts, answered from
   the SAME tables and the same functions that duoforge_battle_create uses; the
   library holds no second copy of a rule. Everything is bound to the context's
   data kind: its counts bound the ids (the CLOSURE kinds see the closure
   prefix of the tables, the TEAM_C kinds the extended prefix, the POOL kinds
   all of them), and the rules are those of the kind (a member's moves and
   ability: the forme's one set under the CLOSURE and TEAM_C kinds, the moves
   the forme learns and its legal abilities under the POOL kinds).
   Pure and allocation-free: no state changes, every output is written only on
   success (the one exception is the required count on E_CAPACITY, as in
   duoforge_battle_candidates). A SYNTHETIC context has no tables: every call
   is E_UNSUPPORTED. A NULL pointer argument is E_NULL_ARGUMENT (also a NULL
   buffer with a capacity above 0); a table or id outside its domain and a
   name that is not in the kind's table are E_INVALID_ARGUMENT. Checks, in
   order: NULL, table, SYNTHETIC, id or name.
   An id is the row of the table (0-based). The setup fields differ in two
   places: a member's ability is 1 + the ability id and its item 1 + the item
   id (0 = none). Species are the formes of the tables: base formes and Mega
   formes; a Mega forme is reached in battle and never set up. */
#define DUOFORGE_DATA_TABLE_SPECIES 1u /* forme ids: the species_id of a member (base formes) */
#define DUOFORGE_DATA_TABLE_MOVE    2u
#define DUOFORGE_DATA_TABLE_ITEM    3u
#define DUOFORGE_DATA_TABLE_ABILITY 4u
#define DUOFORGE_DATA_TABLE_NATURE  5u /* 25 natures, the same under every kind */
#define DUOFORGE_DATA_TABLE_COUNT   5u
#define DUOFORGE_DATA_NONE          0xFFFFFFFFu /* "no such id" in a forme's info */
/* Profile bounds: a buffer of this size always suffices. The tables must stay
   within them (checked when the library is built); raising one is a reviewed,
   additive change. */
#define DUOFORGE_DATA_MAX_FORME_ABILITIES 3u   /* legal abilities of one forme */
#define DUOFORGE_DATA_MAX_FORME_MOVES     512u /* legal moves of one forme */
/* Bits of duoforge_forme_info.gender_mask. */
#define DUOFORGE_GENDER_BIT_MALE   1u
#define DUOFORGE_GENDER_BIT_FEMALE 2u
#define DUOFORGE_GENDER_BIT_NONE   4u

/* The number of ids of a table under the context's kind: the ids 0..count-1
   exist. An item or an ability is used at setup as 1 + its id. */
duoforge_status duoforge_data_count(const duoforge_context *ctx, uint32_t table, uint32_t *out_count);

/* The name of an id: its Showdown id (toID: lower-case letters and digits, for
   example "staraptormega", "closecombat", "leftovers"), a NUL-terminated
   string in constant data, valid while the library is loaded. The
   names come from the same generator run as the tables and are in no
   fingerprint. An id at or beyond the kind's count is E_INVALID_ARGUMENT. */
duoforge_status duoforge_data_name(const duoforge_context *ctx, uint32_t table, uint32_t id,
                                   const char **out_name);

/* The id of a name: the exact name as written by duoforge_data_name, `length`
   bytes (the string need not be NUL-terminated; a NUL inside matches nothing).
   Nothing is normalized. For the SPECIES table it also accepts the 29 cosmetic
   aliases of the POOL tables (Showdown ids of formes that the validator treats
   as their base forme, for example "vivillonpolar", "alcremierubycream"): an
   alias finds the row of its base forme, and duoforge_data_name of that row
   gives the canonical name, never the alias. An alias is bound by the kind's
   count like the row it stands for, so under the CLOSURE and TEAM_C kinds
   (whose tables hold none of those rows) it is refused like any unknown name.
   A name whose id is at or beyond the kind's count is
   refused like an unknown name, so a pool move under a TEAM_C context is
   E_INVALID_ARGUMENT. Struggle is a row of the move table (it is
   engine-internal): find returns it, and duoforge_data_name gives its name;
   no forme lists it, so it is legal for no member, and the support manifest
   leaves it unmarked (the turn core runs it), so duoforge_data_supported says
   false. Species include the Mega formes. */
duoforge_status duoforge_data_find(const duoforge_context *ctx, uint32_t table, const char *name, size_t length,
                                   uint32_t *out_id);

/* Whether a battle that uses the id passes the support gate of
   duoforge_battle_create (the support manifest: the mechanics that are
   implemented and tested). Setup validates first and then refuses an
   unsupported id with E_UNSUPPORTED. A move, item or ability is supported when
   the manifest marks it, and nothing is supported while the turn core is not;
   a species and a nature carry no mark of their own (supported with the turn
   core), except a Mega forme, which is supported when Mega Evolution into it
   is (see mega_supported). A member is supported exactly when its ability
   (if any), its item (if any) and each of its moves are, and, if it holds a
   Mega Stone of its forme (item 1 + the stone), Mega Evolution through that
   stone is supported (mega_supported of its forme for its first Mega Stone,
   duoforge_mega_info.supported for every stone). */
duoforge_status duoforge_data_supported(const duoforge_context *ctx, uint32_t table, uint32_t id,
                                        bool *out_supported);

/* What setup accepts for a species (a forme id of the kind). All fields are
   written for every species; Mega formes are not setup-legal and have no
   moves, abilities or genders. Unused entries are zero. */
typedef struct duoforge_forme_info {
    uint32_t dex_num;        /* national dex number: the Species Clause allows one member per number on a side */
    uint32_t is_mega;        /* 1 for a Mega forme */
    uint32_t setup_legal;    /* 1 iff a member may be this species: a base forme, not a Mega forme */
    uint32_t base_species;   /* the base forme (itself for a base forme) */
    uint32_t mega_species;   /* the Mega forme it reaches, DUOFORGE_DATA_NONE if none */
    uint32_t mega_stone;     /* the item id of its Mega Stone (a member holds it as item 1 + this id), or NONE */
    uint32_t mega_ability;   /* the ability id the Mega forme brings, or NONE */
    uint32_t mega_supported; /* 1 iff the forme has a Mega forme and Mega Evolution into it is supported */
    uint32_t gender_mask;    /* DUOFORGE_GENDER_BIT_*: the genders legal for the forme */
    uint32_t no_ability;     /* 1 iff a member may have ability 0 (No Ability): the DEV kinds only */
    uint32_t ability_count;  /* the legal abilities: ids in ascending order, at most DUOFORGE_DATA_MAX_FORME_ABILITIES */
    uint32_t abilities[DUOFORGE_DATA_MAX_FORME_ABILITIES]; /* a member's ability field is 1 + one of these */
    uint32_t move_count;     /* the legal moves of the forme, listed by duoforge_data_forme_moves */
} duoforge_forme_info; /* 60 bytes */
duoforge_status duoforge_data_forme_info(const duoforge_context *ctx, uint32_t species_id, duoforge_forme_info *out);

/* The Mega formes that a species reaches, one per Mega Stone. duoforge_forme_info
   carries one link per forme and keeps its meaning (the first Mega Stone and its
   Mega forme); a species with a second Mega (Charizard: Mega-X and Mega-Y) or a
   stone that two species share (Meowsticite) is covered here. */
typedef struct duoforge_mega_info {
    uint32_t base_species; /* the base forme asked about */
    uint32_t stone;        /* the item id of the Mega Stone (a member holds it as item 1 + this id) */
    uint32_t mega_species; /* the Mega forme that the stone takes the species to */
    uint32_t mega_ability; /* the ability id the Mega forme brings */
    uint32_t supported;    /* 1 iff Mega Evolution into that Mega forme is supported (the manifest marks Mega Evolution
                              and the Mega forme's ability), as mega_supported of duoforge_forme_info for its first one;
                              whether the stone itself is marked is the ITEM table's answer of duoforge_data_supported */
} duoforge_mega_info; /* 5 words, 20 bytes */
/* How many Mega Stones take the species (a forme id of the kind) to a Mega forme under the kind: 0 for a Mega forme
   and for a species without one. E_INVALID_ARGUMENT for an id beyond the kind's count. */
duoforge_status duoforge_data_mega_count(const duoforge_context *ctx, uint32_t species_id, uint32_t *out_count);
/* The index-th of them, in ascending item id. E_INVALID_ARGUMENT for an id beyond the kind's count and for an index
   at or beyond duoforge_data_mega_count; *out is untouched on failure. */
duoforge_status duoforge_data_mega_at(const duoforge_context *ctx, uint32_t species_id, uint32_t index,
                                      duoforge_mega_info *out);

/* The moves a member of the species may have, in ascending id order: the
   moves of the forme's set under the CLOSURE and TEAM_C kinds, the moves it
   learns under the POOL kinds; empty for a Mega forme. A member has 1 to
   DUOFORGE_MAX_MOVE_SLOTS distinct ones. With capacity < count the call
   returns E_CAPACITY and writes ONLY *out_count = required; the buffer is
   untouched. Otherwise the first *out_count entries are written (the buffer
   may be NULL when capacity is 0). A buffer of DUOFORGE_DATA_MAX_FORME_MOVES
   entries always suffices. */
duoforge_status duoforge_data_forme_moves(const duoforge_context *ctx, uint32_t species_id, uint32_t *buffer,
                                          uint32_t capacity, uint32_t *out_count);
/* Not listed because they are constants or the same for every species: any
   item below duoforge_data_count(ITEM) is legal (0 = none; the Item Clause
   allows each item once per side); every nature below duoforge_data_count(
   NATURE) is legal; Stat Points are at most DUOFORGE_STAT_POINTS_MAX per stat
   and DUOFORGE_STAT_POINTS_TOTAL_MAX in all. */

/* ---- static features of the data rows (decision 0020) ----
   What a learner may know about a forme, move, item, ability or nature without a
   battle: pure functions of (kind, id), read from the same generated tables that
   setup and the turn code read, never computed from anything else. The same contract
   as duoforge_data_forme_info: a NULL pointer is E_NULL_ARGUMENT; an id at or beyond
   duoforge_data_count of the context's kind is E_INVALID_ARGUMENT; a SYNTHETIC
   context (no tables) is E_UNSUPPORTED (checks in that order); `out` is untouched on
   an error. The structs hold uint32_t fields (see priority for a negative value), unused entries
   are zero and an id that is not there is DUOFORGE_DATA_NONE; there is no
   allocation and no pointer into the tables. Every row answers, modelled or not:
   whether the engine can play a row is duoforge_data_supported, not a part of
   these. One call per id; a learner builds its own arrays at start-up. */

/* A forme: its types, base stats and weight. A Mega forme is a row like any
   other, so its types and stats are the post-Mega ones. 44 bytes. */
typedef struct duoforge_forme_static {
    uint32_t types[2];        /* DUOFORGE_TYPE_*; the second is DUOFORGE_DATA_NONE for a single type */
    uint32_t base_stats[6];   /* HP, Atk, Def, SpA, SpD, Spe */
    uint32_t weight_hg;       /* in hectograms (weight in kg times 10) */
    uint32_t default_ability; /* an ability id: a Mega forme's own, otherwise the first legal one (forme_info lists all) */
    uint32_t is_mega;         /* 1 for a Mega forme */
} duoforge_forme_static;
duoforge_status duoforge_data_forme_static(const duoforge_context *ctx, uint32_t species_id, duoforge_forme_static *out);

/* duoforge_move_static.category */
#define DUOFORGE_MOVE_CATEGORY_PHYSICAL 0u
#define DUOFORGE_MOVE_CATEGORY_SPECIAL  1u
#define DUOFORGE_MOVE_CATEGORY_STATUS   2u

/* duoforge_move_static.flags: one bit per Showdown flag name of the move, plus POWER_RULE; additive only. They are
   data about the move, not support: that a flag is reported says nothing about whether the engine implements what
   reads it (Bulletproof, Mega Launcher and the rest stay unmarked until a step gives them a reader). */
#define DUOFORGE_MOVE_STATIC_FLAG_CONTACT    0x001u
#define DUOFORGE_MOVE_STATIC_FLAG_SOUND      0x002u
#define DUOFORGE_MOVE_STATIC_FLAG_PUNCH      0x004u
#define DUOFORGE_MOVE_STATIC_FLAG_BITE       0x008u
#define DUOFORGE_MOVE_STATIC_FLAG_BULLET     0x010u
#define DUOFORGE_MOVE_STATIC_FLAG_PULSE      0x020u
#define DUOFORGE_MOVE_STATIC_FLAG_SLICING    0x040u
#define DUOFORGE_MOVE_STATIC_FLAG_WIND       0x080u
#define DUOFORGE_MOVE_STATIC_FLAG_DANCE      0x100u
#define DUOFORGE_MOVE_STATIC_FLAG_POWDER     0x200u
#define DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE 0x400u /* base_power is not the damage: a callback computes the power
                                                       (Low Kick, Last Respects); base_power is the pin's basePower, 0 then */

/* A move. 64 bytes. */
typedef struct duoforge_move_static {
    uint32_t type;             /* DUOFORGE_TYPE_* */
    uint32_t category;         /* DUOFORGE_MOVE_CATEGORY_* */
    uint32_t base_power;       /* the pin's basePower */
    uint32_t accuracy;         /* percent; 0 means the move never misses */
    uint32_t pp;               /* Champions PP after the cap and calculatePP: what a member starts with */
    uint32_t priority;         /* the pin's priority, -7 to +5, unbiased: a negative value is its 32-bit two's complement
                                  (0xFFFFFFF9 for -7); the library has no negative-capable field type, a caller casts */
    uint32_t target_class;     /* DUOFORGE_TARGET_CLASS_* 1..DUOFORGE_TARGET_CLASS_STATIC_COUNT; the request API does
                                  not resolve 10..15 */
    uint32_t flags;            /* DUOFORGE_MOVE_STATIC_FLAG_* */
    uint32_t crit_stage;       /* the critical-hit stage: 0 normal, 1 high (the pin's critRatio minus 1) */
    uint32_t drain[2];         /* numerator, denominator of the damage dealt; 0 and 0 for none */
    uint32_t recoil[2];        /* the same for recoil */
    uint32_t secondary_chance; /* percent of the secondary effect, 0 for none; its kind stays internal */
    uint32_t hits_min;         /* the pin's multihit: 2 and 5 for Bullet Seed, 2 and 2 for Dual Wingbeat, 3 and 3 for
                                  Triple Axel, 1 and 1 for a single hit */
    uint32_t hits_max;
} duoforge_move_static;
duoforge_status duoforge_data_move_static(const duoforge_context *ctx, uint32_t move_id, duoforge_move_static *out);

/* duoforge_item_static.family, as the generated family column of the tables */
#define DUOFORGE_ITEM_FAMILY_NONE         0u
#define DUOFORGE_ITEM_FAMILY_TYPE_BOOSTER 1u /* family_type: the type whose moves it strengthens */
#define DUOFORGE_ITEM_FAMILY_RESIST_BERRY 2u /* family_type: the type whose super effective hit it weakens */

/* An item. Everything else about an item is code, not data: it stays an id. 16 bytes. */
typedef struct duoforge_item_static {
    uint32_t family;        /* DUOFORGE_ITEM_FAMILY_* */
    uint32_t family_type;   /* DUOFORGE_TYPE_*; DUOFORGE_DATA_NONE without a family */
    uint32_t is_mega_stone; /* 1 for a Mega Stone of the tables */
    uint32_t mega_species;  /* the Mega forme it enables (a forme id), DUOFORGE_DATA_NONE if is_mega_stone is 0 */
} duoforge_item_static;
duoforge_status duoforge_data_item_static(const duoforge_context *ctx, uint32_t item_id, duoforge_item_static *out);

/* duoforge_ability_static.family */
#define DUOFORGE_ABILITY_FAMILY_NONE           0u
#define DUOFORGE_ABILITY_FAMILY_ATE            1u /* family_param: the type that it turns Normal moves into */
#define DUOFORGE_ABILITY_FAMILY_PINCH          2u /* family_param: the type that it strengthens at a third of the HP */
#define DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER 3u /* family_param: DUOFORGE_WEATHER_* */
#define DUOFORGE_ABILITY_FAMILY_TERRAIN_SETTER 4u /* family_param: DUOFORGE_TERRAIN_* */

/* An ability. 8 bytes. */
typedef struct duoforge_ability_static {
    uint32_t family;       /* DUOFORGE_ABILITY_FAMILY_* */
    uint32_t family_param; /* see the family; DUOFORGE_DATA_NONE without a family */
} duoforge_ability_static;
duoforge_status duoforge_data_ability_static(const duoforge_context *ctx, uint32_t ability_id,
                                             duoforge_ability_static *out);

/* A nature (the same 25 under every kind): the stat it raises and the one it lowers, as the stat indices of the
   public arrays (stat_points, base_stats: 0 HP, 1 Atk, 2 Def, 3 SpA, 4 SpD, 5 Spe; never HP). Both are
   DUOFORGE_DATA_NONE for a neutral nature. 8 bytes. A nature id at or beyond duoforge_data_count(NATURE) is
   E_INVALID_ARGUMENT, as above. */
typedef struct duoforge_nature_static {
    uint32_t raised_stat;
    uint32_t lowered_stat;
} duoforge_nature_static;
duoforge_status duoforge_data_nature_static(const duoforge_context *ctx, uint32_t nature_id,
                                            duoforge_nature_static *out);

/* The pinned type chart: the multiplier of an attack of attack_type on a defender of defend_type as the fraction
   *out_num / *out_den: 0/1 (immune), 1/2, 1/1 or 2/1. A type that is not a DUOFORGE_TYPE_* (0..17) is
   E_INVALID_ARGUMENT; the chart is the same under every kind with tables. Both outputs are untouched on an error. */
duoforge_status duoforge_data_type_effect(const duoforge_context *ctx, uint32_t attack_type, uint32_t defend_type,
                                          uint32_t *out_num, uint32_t *out_den);

/* ---- owned battle state: opaque, pointer-free, bound to a context by
   fingerprint (not by pointer); every call checks the fingerprint ---- */
typedef struct duoforge_battle duoforge_battle;

/* Allocating. */
duoforge_status duoforge_battle_create(const duoforge_context *ctx, const duoforge_battle_setup *setup,
                                       duoforge_battle **out_battle);
duoforge_status duoforge_battle_create_decoded(const duoforge_context *ctx, const uint8_t *bytes,
                                               size_t size, duoforge_battle **out_battle);
duoforge_status duoforge_battle_clone(const duoforge_context *ctx, const duoforge_battle *src,
                                      duoforge_battle **out_battle);
void duoforge_battle_destroy(duoforge_battle *battle); /* NULL is a no-op */
/* The reference teams of decision 0004 as a setup: pairing 0..3 = A-B, B-A,
   A-A, B-B (side 0 first), rng_initstate 2026 and rng_initseq 1001. Checks:
   NULL -> INVALID_ARGUMENT (pairing); *out is untouched on failure. */
duoforge_status duoforge_reference_setup(uint32_t pairing, duoforge_battle_setup *out);

/* Allocation-free. */
/* In-process snapshot/restore: after NULL and context checks, dst == src is a no-op. */
duoforge_status duoforge_battle_copy(const duoforge_context *ctx, duoforge_battle *dst,
                                     const duoforge_battle *src);
duoforge_status duoforge_battle_decode(const duoforge_context *ctx, duoforge_battle *dst,
                                       const uint8_t *bytes, size_t size);
/* The full state check. Create, step, decode, encode, digest and check run it;
   the model-facing queries (request, candidates, observe) run every rule but
   a CLOSURE member's derived values and move legality (stats, HP and PP
   maxima, moves of the set): a battle changes only through the calls that
   run the full check, and every index, count and divisor stays checked, so
   a query never reads out of bounds (decision 0011). */
duoforge_status duoforge_battle_check(const duoforge_context *ctx, const duoforge_battle *battle);
/* True iff the canonical encodings are byte-identical (covers every field,
   including the RNG state and draw counter). */
duoforge_status duoforge_battle_equal(const duoforge_context *ctx, const duoforge_battle *a,
                                      const duoforge_battle *b, bool *out_equal);
duoforge_status duoforge_battle_encoded_size(const duoforge_context *ctx, const duoforge_battle *battle,
                                             size_t *out_size);
duoforge_status duoforge_battle_encode(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t *buffer, size_t capacity, size_t *out_written);
duoforge_status duoforge_battle_digest(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint8_t out_digest[DUOFORGE_DIGEST_SIZE]);
/* Fork support (PRIVILEGED): replaces the gameplay RNG with a fresh seed
   (draw counter 0), e.g. to decorrelate a copied battle for search. Nothing
   else changes. rng_initseq must be < 2^63 (decision 0001). */
duoforge_status duoforge_battle_reseed(const duoforge_context *ctx, duoforge_battle *battle,
                                       uint64_t rng_initstate, uint64_t rng_initseq);

/* ---- M2 requests, joint commands and step (decision 0005) ----
   Model-facing. Records are padding-free and zero-filled by producers; a
   consumer-supplied record with any nonzero reserved byte is not in the
   domain. Requests and candidate enumeration are pure: no state, RNG or
   epoch change; enumerating twice gives identical bytes. */
#define DUOFORGE_SLOT_NONE   0u /* an unrequested slot */
#define DUOFORGE_SLOT_MOVE   1u
#define DUOFORGE_SLOT_SWITCH 2u
#define DUOFORGE_SLOT_PASS   3u /* forced no-action only where the profile says so */
/* move_slot of Struggle: offered, with no target and no Mega declaration,
   exactly when an occupant has no selectable move (no PP left, Fake Out
   disabled, a choice lock; sim/pokemon.ts, the reference's request). */
#define DUOFORGE_MOVE_SLOT_STRUGGLE 4u
/* move_slot of the recharge turn (POOL kinds, step G17): a Pokemon that used a recharge move (Hyper Beam) and hit must
   recharge on its next action. Its slot is offered exactly one candidate, MOVE with this move_slot, DUOFORGE_TARGET_NONE
   and no Mega declaration; no other move and no switch (sim/pokemon.ts getMoveRequestData, trapped; Showdown's
   "move 1" is the move "Recharge"). The action prints "cant|X|recharge" (DUOFORGE_CAUSE_RECHARGE) and uses no PP. */
#define DUOFORGE_MOVE_SLOT_RECHARGE 5u
#define DUOFORGE_CHOICE_TEAM_SELECTION 1u
#define DUOFORGE_CHOICE_SLOTS          2u
/* Profile bound on a complete side-choice domain: max(720 ordered picks of 6,
   28 x 28 joint slot choices). A caller may allocate this once. */
#define DUOFORGE_MAX_CANDIDATES 784u

typedef struct duoforge_slot_command {
    uint8_t kind;        /* DUOFORGE_SLOT_* */
    uint8_t move_slot;   /* MOVE: 0..3, or DUOFORGE_MOVE_SLOT_STRUGGLE, or DUOFORGE_MOVE_SLOT_RECHARGE */
    uint8_t target;      /* MOVE: flat position side*2+slot, or DUOFORGE_TARGET_NONE */
    uint8_t mega;        /* MOVE: 0/1 Mega Evolution declaration */
    uint8_t reserve;     /* SWITCH: roster index of the reserve */
    uint8_t reserved[3]; /* zero */
} duoforge_slot_command; /* 8 bytes */

typedef struct duoforge_side_choice {
    uint32_t epoch;      /* the request epoch answered */
    uint8_t side;        /* 0/1 */
    uint8_t kind;        /* DUOFORGE_CHOICE_* */
    uint8_t pick_count;  /* TEAM_SELECTION: context brought_count; else 0 */
    uint8_t picks[DUOFORGE_MAX_ROSTER]; /* TEAM_SELECTION: ordered roster indices, leads first; rest 0 */
    uint8_t reserved[3]; /* zero */
    duoforge_slot_command slots[DUOFORGE_ACTIVE_PER_SIDE]; /* SLOTS: unrequested slots are all-zero */
} duoforge_side_choice; /* 32 bytes */

typedef struct duoforge_decision_bundle {
    uint32_t epoch;
    uint8_t response_mask; /* must equal the request mask */
    uint8_t reserved[3];   /* zero */
    duoforge_side_choice responses[DUOFORGE_SIDE_COUNT]; /* responses[s] is all-zero unless bit s is set */
} duoforge_decision_bundle; /* 72 bytes */

/* The factored form of a player's joint domain (M7, decision 0013): the two
   slot lists and the pair rule as a bit matrix, 652 bytes in place of up to
   DUOFORGE_MAX_CANDIDATES joint choices. Unused entries and bits are zero. */
#define DUOFORGE_MAX_SLOT_OPTIONS 32u
typedef struct duoforge_factored_domain {
    uint32_t epoch;        /* the request epoch */
    uint8_t kind;          /* DUOFORGE_CHOICE_SLOTS or _TEAM_SELECTION; 0 when not requested */
    uint8_t slot_count[DUOFORGE_ACTIVE_PER_SIDE]; /* SLOTS: entries of each slot list, 1..32 */
    uint8_t member_count;  /* TEAM_SELECTION: roster size */
    uint8_t pick_count;    /* TEAM_SELECTION: brought count */
    uint8_t reserved[3];   /* zero */
    duoforge_slot_command slots[DUOFORGE_ACTIVE_PER_SIDE][DUOFORGE_MAX_SLOT_OPTIONS];
    uint32_t allowed[DUOFORGE_MAX_SLOT_OPTIONS]; /* bit j of allowed[i]: the pair (slots[0][i], slots[1][j]) */
} duoforge_factored_domain; /* 652 bytes */

typedef struct duoforge_factored_choice {
    uint8_t slot[DUOFORGE_ACTIVE_PER_SIDE]; /* SLOTS: indices into slots[0] and slots[1] */
    uint8_t picks[DUOFORGE_MAX_ROSTER];     /* TEAM_SELECTION: ordered roster indices, leads first; rest 0 */
} duoforge_factored_choice; /* 8 bytes */

typedef struct duoforge_request {
    uint32_t epoch;
    uint32_t candidate_count; /* exact size of this player's domain (0 when not requested) */
    uint8_t boundary_kind;    /* DUOFORGE_BOUNDARY_* */
    uint8_t player;
    uint8_t requested;        /* 1 iff this player must respond at this boundary */
    uint8_t slot_mask;        /* bit k: position k needs a slot command (0 at TEAM_SELECTION) */
} duoforge_request; /* 12 bytes */

#define DUOFORGE_STEP_BOUNDARY 1u /* a new decision boundary was reached */
#define DUOFORGE_STEP_REPROMPT 2u /* rule-authorized re-prompt (no M2 mechanic produces it) */
typedef struct duoforge_step_result {
    uint32_t epoch;        /* the new request epoch */
    uint8_t kind;          /* DUOFORGE_STEP_* */
    uint8_t boundary_kind; /* the new boundary */
    uint8_t request_mask;  /* who must respond next */
    uint8_t reserved;      /* zero */
} duoforge_step_result; /* 8 bytes */

/* The request of one player, built only from that player's authorized view.
   Checks: NULL -> CONTEXT_MISMATCH -> INVALID_ARGUMENT (player) -> INVARIANT
   (engine-side failure) -> UNSUPPORTED. An alive occupant with no selectable
   move is offered Struggle (DUOFORGE_MOVE_SLOT_STRUGGLE). */
duoforge_status duoforge_battle_request(const duoforge_context *ctx, const duoforge_battle *battle,
                                        uint32_t player, duoforge_request *out_request);
/* The battle's result: DUOFORGE_RESULT_SIDE_0, _SIDE_1 or _TIE at TERMINAL, 0
   before. Checks as duoforge_battle_request (NULL -> CONTEXT_MISMATCH ->
   INVARIANT); *out_result is written only on success. */
duoforge_status duoforge_battle_result(const duoforge_context *ctx, const duoforge_battle *battle,
                                       uint32_t *out_result);
/* The result Battle.tiebreak() of the pinned reference would give the battle
   as it stands (sim/battle.ts:1467-1508), without changing it: the side with
   the most Pokemon not fainted wins; among equals the larger HP percentage
   (the sum of hp / maxhp over the brought Pokemon, in the reference's IEEE-754
   binary64 arithmetic, times 100, divided by 6); among equals the larger total
   HP; else a tie. *out_result is DUOFORGE_RESULT_SIDE_0, _SIDE_1 or _TIE. At
   TERMINAL it is the battle's own result. Before the picks are made the
   Pokemon counted are the whole roster. Under every data kind. Checks: NULL ->
   E_NULL_ARGUMENT, then CONTEXT_MISMATCH -> INVARIANT as the other queries;
   *out_result is written only on success.
   E_UNSUPPORTED: the HP percentages of the two sides are one rounding apart
   for some order of the benches, and the order of the reference's
   side.pokemon, which the engine does not keep, would decide the winner. */
duoforge_status duoforge_battle_tiebreak(const duoforge_context *ctx, const duoforge_battle *battle,
                                         uint32_t *out_result);
/* The complete joint side-choice domain of one player in documented order
   (decision 0005 section 3). With capacity < count the call returns
   E_CAPACITY and writes ONLY *out_count = required; the buffer is untouched.
   Otherwise the first *out_count records are written. */
duoforge_status duoforge_battle_candidates(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_side_choice *buffer, uint32_t capacity,
                                           uint32_t *out_count);
/* The same domain in factored form, checked as duoforge_battle_candidates;
   *out is written only on success. Exact: the allowed pairs in row-major
   (i, j) order, each made a side choice with the epoch and side, are byte for
   byte the candidate list, in its order. At TEAM_SELECTION only kind,
   member_count and pick_count are set besides the epoch (the domain is the
   ordered tuples of distinct roster indices, lexicographic); a player without
   a request gets kind 0. */
duoforge_status duoforge_battle_factored(const duoforge_context *ctx, const duoforge_battle *battle,
                                         uint32_t player, duoforge_factored_domain *out);
/* Submits the responses of exactly the requested sides. Checks: NULL ->
   CONTEXT_MISMATCH -> INVARIANT -> STALE_EPOCH (bundle or response epoch) ->
   INVALID_ARGUMENT (mask, reserved bytes, side/kind fields, a response
   outside the offered domain, a nonzero response of an unrequested side).
   A valid TEAM_SELECTION bundle performs the transition to TURN (for
   CLOSURE, TEAM_C and POOL data with the leads' entry effects). A valid TURN or
   REPLACEMENT bundle of such a battle runs the turn (decision 0006); a mechanic the
   support manifest does not mark returns E_UNSUPPORTED, as does every
   combat bundle under SYNTHETIC data. A valid PIVOT bundle (switches for
   the flagged positions) continues the stored rest of the turn. At TERMINAL every
   bundle is INVALID_ARGUMENT: the battle is over.
   E_EXHAUSTED if the epoch or activation counter would overflow. Every
   step records its events (decision 0007 sections 11, 12): each player's
   knowledge of the opponent is folded from the lines it sees, and a step
   beyond DUOFORGE_MAX_EVENTS lines is E_INVARIANT. Every failure leaves the
   battle unchanged and *out_result unwritten. */
duoforge_status duoforge_battle_step(const duoforge_context *ctx, duoforge_battle *battle,
                                     const duoforge_decision_bundle *bundle, duoforge_step_result *out_result);

/* ---- observation v2: what a player sees (decision 0007) ----
   A player's view is what a human at the table knows, with perfect memory:
   the own team exactly, the open team sheets of both teams, and the battle
   as the game shows it to that player. Anything that follows from these is
   given directly (remaining turns, the foe's PP as maximum minus the uses
   the viewer saw); anything rolled in secret stays hidden, on the own side
   as well (sleep, freeze and confusion turns, the foe's locked target).
   Unknown values are TAGGED (kind fields) or documented as zero, never
   encoded as facts. */
#define DUOFORGE_HP_EXACT   1u
#define DUOFORGE_HP_PERCENT 2u /* hp = floor percent (1..100 while alive, 0 fainted), hp_max = 100 */
#define DUOFORGE_HP_UNKNOWN 3u
#define DUOFORGE_PP_EXACT   1u
#define DUOFORGE_PP_DERIVED 2u /* the foe: pp_max minus the uses the viewer saw */
#define DUOFORGE_PP_UNKNOWN 3u
#define DUOFORGE_HP_FLAG_NONE   0u
#define DUOFORGE_HP_FLAG_RED    1u /* exactly 20 percent and hp*5 <= hp_max */
#define DUOFORGE_HP_FLAG_YELLOW 2u /* exactly 20 percent above that, or exactly 50 and hp*2 <= hp_max */
#define DUOFORGE_HP_FLAG_GREEN  3u /* exactly 50 percent and hp*2 > hp_max */
#define DUOFORGE_LOCATION_UNDETERMINED 0u /* foe not yet seen; anyone before team selection */
#define DUOFORGE_LOCATION_BENCH        1u
#define DUOFORGE_LOCATION_ACTIVE       2u
#define DUOFORGE_LOCATION_NOT_BROUGHT  3u /* own side only */
#define DUOFORGE_AILMENT_NONE      0u
#define DUOFORGE_AILMENT_BURN      1u
#define DUOFORGE_AILMENT_FREEZE    2u
#define DUOFORGE_AILMENT_PARALYSIS 3u
#define DUOFORGE_AILMENT_SLEEP     4u
#define DUOFORGE_AILMENT_POISON    5u /* Team C: Dire Claw */
#define DUOFORGE_AILMENT_TOX       6u /* POOL (decision 0018): badly poisoned; produced since step G36 (#184: badly poisoned, as a primary and as a secondary effect) */
#define DUOFORGE_WEATHER_NONE 0u
#define DUOFORGE_WEATHER_RAIN 1u
#define DUOFORGE_WEATHER_SUN  2u
#define DUOFORGE_WEATHER_SAND 3u /* POOL (decision 0018): produced since step 5b of decision 0015 (#124: Sandstorm, Sand Stream) */
#define DUOFORGE_WEATHER_SNOW 4u /* POOL: produced since step 5b of decision 0015 (#124: Snowscape, Snow Warning) */
#define DUOFORGE_TERRAIN_NONE   0u
#define DUOFORGE_TERRAIN_GRASSY 1u
#define DUOFORGE_TERRAIN_PSYCHIC 2u /* Team C (Psychic Surge) */
#define DUOFORGE_TERRAIN_ELECTRIC 3u /* POOL (decision 0018): produced since step G25 (#163: Electric Terrain, Electric Surge; Steel Roller ends it) */
#define DUOFORGE_TERRAIN_MISTY    4u /* POOL: produced since step G25 (#163: Misty Terrain; Steel Roller ends it) */
#define DUOFORGE_MOVE_SLOT_NONE 0xFFu /* position view: no locked move */

typedef struct duoforge_member_view {
    uint16_t species_id; /* open; 0 with all other fields 0 for an unregistered slot */
    uint16_t hp;         /* per hp_kind */
    uint16_t hp_max;     /* per hp_kind */
    uint16_t move_ids[DUOFORGE_MAX_MOVE_SLOTS]; /* open; unused slots 0 */
    uint16_t stats[5];                          /* own side: the current Attack, Defense, Sp. Atk, Sp.
                                                   Def, Speed (the Mega forme's after Mega Evolution);
                                                   0 for the foe (hidden) and under SYNTHETIC data */
    uint8_t pp[DUOFORGE_MAX_MOVE_SLOTS];        /* per pp_kind */
    uint8_t pp_max[DUOFORGE_MAX_MOVE_SLOTS];    /* open; unused slots 0 */
    uint8_t stat_points[6];                     /* own side: the set's stat points, HP .. Speed; 0 for
                                                   the foe (hidden) */
    uint8_t move_count;                         /* open */
    uint8_t hp_kind;                            /* DUOFORGE_HP_* */
    uint8_t hp_flag;                            /* DUOFORGE_HP_FLAG_* (PERCENT only) */
    uint8_t pp_kind;                            /* DUOFORGE_PP_*: own EXACT, foe DERIVED */
    uint8_t location;                           /* DUOFORGE_LOCATION_* */
    uint8_t mega_capable;                       /* open (the stone is on the sheet) */
    uint8_t is_mega;                            /* public once it happened */
    uint8_t gender;                             /* open (0 under SYNTHETIC data) */
    uint8_t nature;                             /* open */
    uint8_t ability;                            /* open: current ability + 1 (the Mega forme's after
                                                   Mega Evolution), 0 none */
    uint8_t item;                               /* open: sheet item + 1, 0 none */
    uint8_t item_used;                          /* public: used up in view */
    uint8_t status;                             /* public: DUOFORGE_AILMENT_*; NONE for a foe not yet
                                                   seen and for a fainted member */
    uint8_t reserved;                           /* zero */
} duoforge_member_view; /* 52 bytes */

/* An active position as both players see it. An empty one has neutral
   stages, no locked slot or target and every flag 0. */
typedef struct duoforge_position_view {
    uint8_t stages[7];     /* public: atk def spa spd spe accuracy evasion, biased by 6 (6 = neutral) */
    uint8_t confused;      /* public: 1 while confused; the turns stay hidden */
    uint8_t charging;      /* public: 1 while a two-turn move is charged */
    uint8_t locked_slot;   /* public: the locked move slot (a charging two-turn move, or a Choice
                              item's lock, Team C), DUOFORGE_MOVE_SLOT_NONE if none */
    uint8_t locked_target; /* own side only: the stored target (flat position) of a charging two-turn
                              move; DUOFORGE_TARGET_NONE without one, for a choice lock and for the foe */
    uint8_t acted;         /* public: 1 once the occupant took a move action since it entered */
    uint8_t protect_chain; /* public: consecutive successful Protects (stall counter level) */
    uint8_t flash_fire;    /* public: 1 while Flash Fire's boost is active */
    uint8_t protecting;    /* public: 1 while Protect is up this turn ([-singleturn] Protect) */
    uint8_t reserved;      /* zero under CLOSURE; under the TEAM_C and POOL kinds DUOFORGE_POSITION_FLAG_* */
} duoforge_position_view; /* 16 bytes */

/* Bits of duoforge_position_view.reserved under the TEAM_C and POOL kinds
   (decision 0009 section 4.2). */
#define DUOFORGE_POSITION_FLAG_FOLLOW_ME    1u /* Follow Me draws the foes' moves this turn ([-singleturn]) */
#define DUOFORGE_POSITION_FLAG_HELPING_HAND 2u /* Helping Hand's boost for this turn ([-singleturn]) */
#define DUOFORGE_POSITION_FLAG_UNBURDEN     4u /* Unburden doubles the occupant's Speed */

typedef struct duoforge_side_view {
    duoforge_member_view members[DUOFORGE_MAX_ROSTER];
    duoforge_position_view positions[DUOFORGE_ACTIVE_PER_SIDE];
    uint8_t member_count;                        /* open */
    uint8_t occupant[DUOFORGE_ACTIVE_PER_SIDE];  /* public: roster index or DUOFORGE_ROSTER_NONE */
    uint8_t mega_used;                           /* public */
    uint8_t brought_order[DUOFORGE_MAX_ROSTER];  /* own side; all DUOFORGE_ROSTER_NONE for the foe */
    uint8_t requested;                           /* public: this side must answer the current request */
    uint8_t requested_slots;                     /* public: its requested positions (bit k slot k) */
    uint8_t reflect_turns;                       /* public: remaining turns, 0 when absent */
    uint8_t light_screen_turns;                  /* public */
    uint8_t tailwind_turns;                      /* public */
    uint8_t reserved;                            /* zero */
} duoforge_side_view; /* 360 bytes */

typedef struct duoforge_observation {
    uint32_t epoch;
    uint8_t boundary_kind;
    uint8_t player;           /* the viewer; sides[] stays in absolute side order */
    uint8_t requested;        /* as in duoforge_request */
    uint8_t slot_mask;
    uint16_t turn;            /* public */
    uint8_t weather;          /* public: DUOFORGE_WEATHER_* */
    uint8_t weather_turns;    /* public: remaining turns */
    uint8_t terrain;          /* public: DUOFORGE_TERRAIN_* */
    uint8_t terrain_turns;    /* public */
    uint8_t trick_room_turns; /* public: remaining turns, 0 when absent */
    uint8_t reserved;         /* zero */
    duoforge_side_view sides[DUOFORGE_SIDE_COUNT];
} duoforge_observation; /* 736 bytes */

/* Pure. Checks: NULL -> CONTEXT_MISMATCH -> INVALID_ARGUMENT (player) ->
   INVARIANT. Writes *out_observation only on success. */
duoforge_status duoforge_battle_observe(const duoforge_context *ctx, const duoforge_battle *battle,
                                        uint32_t player, duoforge_observation *out_observation);

/* ---- the POOL player-view extension (decision 0018) ----
   What the 736-byte observation has no room for: the effects of the content
   expansion that a player sees (weather and terrain beyond the old values are
   in the old fields; everything else is here). Fixed size, no pointers, no
   padding, reserved bytes zero. Under every kind except POOL and POOL_DEV the
   whole struct is zero (revision 0); under the POOL kinds revision is
   DUOFORGE_OBSERVATION_EXT_REVISION. Every field is declared now and stays
   zero until the step that implements its mechanic sets its bit in `supported`
   (DUOFORGE_VIEWEXT_FEATURE_*, a bit number): a zero field of a clear bit is
   "not yet supported", of a set bit "absent". Nothing here is private to one
   side: a field is public, and a field that only the owner could see would be
   zero in the opponent's section (none is, in revision 1). Hidden durations
   are never exposed. sides[] is in absolute side order, as in
   duoforge_observation. Growth: a field is only ever appended into a reserve,
   which is an additive change; a larger struct is a new revision with its own
   struct and function. Ids: forme, ability and item ids are those of the data
   tables (duoforge_data_*), "+ 1" meaning 0 is none; type ids are the
   alphabetical DUOFORGE_TYPE_* below. */
#define DUOFORGE_OBSERVATION_EXT_SIZE     192u
#define DUOFORGE_OBSERVATION_EXT_REVISION 1u

/* Type ids (alphabetical), for type_now (id + 1). */
#define DUOFORGE_TYPE_BUG      0u
#define DUOFORGE_TYPE_DARK     1u
#define DUOFORGE_TYPE_DRAGON   2u
#define DUOFORGE_TYPE_ELECTRIC 3u
#define DUOFORGE_TYPE_FAIRY    4u
#define DUOFORGE_TYPE_FIGHTING 5u
#define DUOFORGE_TYPE_FIRE     6u
#define DUOFORGE_TYPE_FLYING   7u
#define DUOFORGE_TYPE_GHOST    8u
#define DUOFORGE_TYPE_GRASS    9u
#define DUOFORGE_TYPE_GROUND   10u
#define DUOFORGE_TYPE_ICE      11u
#define DUOFORGE_TYPE_NORMAL   12u
#define DUOFORGE_TYPE_POISON   13u
#define DUOFORGE_TYPE_PSYCHIC  14u
#define DUOFORGE_TYPE_ROCK     15u
#define DUOFORGE_TYPE_STEEL    16u
#define DUOFORGE_TYPE_WATER    17u

/* Bits of duoforge_position_ext.volatiles (bits 20 to 31 are reserved, 0). */
#define DUOFORGE_POSITION_EXT_SUBSTITUTE   0x00000001u
#define DUOFORGE_POSITION_EXT_TAUNT        0x00000002u
#define DUOFORGE_POSITION_EXT_IMPRISON     0x00000004u
#define DUOFORGE_POSITION_EXT_LEECH_SEED   0x00000008u
#define DUOFORGE_POSITION_EXT_YAWN         0x00000010u
#define DUOFORGE_POSITION_EXT_FOCUS_ENERGY 0x00000020u
#define DUOFORGE_POSITION_EXT_DRAGON_CHEER 0x00000040u
#define DUOFORGE_POSITION_EXT_MUST_RECHARGE 0x00000080u
#define DUOFORGE_POSITION_EXT_PARTIAL_TRAP 0x00000100u
#define DUOFORGE_POSITION_EXT_GLAIVE_RUSH  0x00000200u
#define DUOFORGE_POSITION_EXT_DESTINY_BOND 0x00000400u
#define DUOFORGE_POSITION_EXT_CURSE        0x00000800u
#define DUOFORGE_POSITION_EXT_NO_RETREAT   0x00001000u
#define DUOFORGE_POSITION_EXT_SALT_CURE    0x00002000u
#define DUOFORGE_POSITION_EXT_CHARGE       0x00004000u
#define DUOFORGE_POSITION_EXT_HEAL_BLOCK   0x00008000u
#define DUOFORGE_POSITION_EXT_THROAT_CHOP  0x00010000u
#define DUOFORGE_POSITION_EXT_RAGE_POWDER  0x00020000u
#define DUOFORGE_POSITION_EXT_TYPE_CHANGED 0x00040000u
#define DUOFORGE_POSITION_EXT_ILLUSION_UP  0x00080000u
/* Bits of duoforge_side_ext.guard_flags (this turn only). */
#define DUOFORGE_SIDE_GUARD_WIDE_GUARD  1u
#define DUOFORGE_SIDE_GUARD_QUICK_GUARD 2u
/* duoforge_member_ext.item_now: the member holds nothing (Knock Off, Thief). */
#define DUOFORGE_ITEM_NOW_NONE 255u

/* Bit numbers of duoforge_observation_ext.supported, by tier (decision 0018 section 7.1). Bits 40 to 63 are free. */
#define DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND     0u
#define DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW     1u
#define DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE   2u
#define DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL      3u
#define DUOFORGE_VIEWEXT_FEATURE_PERISH           4u
#define DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC 5u
#define DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP      6u
#define DUOFORGE_VIEWEXT_FEATURE_ENCORE           7u
#define DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES     8u
#define DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE      9u
#define DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX      10u
#define DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE      11u
#define DUOFORGE_VIEWEXT_FEATURE_IMPRISON         12u
#define DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK     13u
#define DUOFORGE_VIEWEXT_FEATURE_TAUNT            14u
#define DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE    15u
#define DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK       16u
#define DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD       17u
#define DUOFORGE_VIEWEXT_FEATURE_PARTIAL_TRAP     18u
#define DUOFORGE_VIEWEXT_FEATURE_FORME_CHANGE     19u
#define DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH      20u
#define DUOFORGE_VIEWEXT_FEATURE_DISABLE          21u
#define DUOFORGE_VIEWEXT_FEATURE_STOCKPILE        22u
#define DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE       23u
#define DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER     24u
#define DUOFORGE_VIEWEXT_FEATURE_YAWN             25u
#define DUOFORGE_VIEWEXT_FEATURE_ILLUSION         26u
#define DUOFORGE_VIEWEXT_FEATURE_GRAVITY          27u
#define DUOFORGE_VIEWEXT_FEATURE_LEECH_SEED       28u
#define DUOFORGE_VIEWEXT_FEATURE_FOCUS_ENERGY     29u
#define DUOFORGE_VIEWEXT_FEATURE_SPIKES           30u
#define DUOFORGE_VIEWEXT_FEATURE_CHARGE           31u
#define DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY    32u
#define DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB       33u
#define DUOFORGE_VIEWEXT_FEATURE_SALT_CURE        34u
#define DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND     35u
#define DUOFORGE_VIEWEXT_FEATURE_CURSE            36u
#define DUOFORGE_VIEWEXT_FEATURE_NO_RETREAT       37u
#define DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD      38u
#define DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER      39u
#define DUOFORGE_VIEWEXT_FEATURE_COUNT            40u

/* Field-wide, public. */
typedef struct duoforge_field_ext {
    uint8_t gravity_turns; /* 0 to 5: remaining turns */
    uint8_t reserved[15];  /* zero */
} duoforge_field_ext; /* 16 bytes */

/* One active position; all zero when empty. */
typedef struct duoforge_position_ext {
    uint32_t volatiles;    /* DUOFORGE_POSITION_EXT_* presence bits */
    uint16_t ability_now;  /* ability id + 1 when it differs from duoforge_member_view.ability, else 0 */
    uint8_t type_now[2];   /* type id + 1 (0: none) while DUOFORGE_POSITION_EXT_TYPE_CHANGED is set, else 0 */
    uint8_t encore_slot;   /* the forced move slot + 1; 0: not encored */
    uint8_t disable_slot;  /* the barred move slot + 1; 0: none */
    uint8_t stockpile;     /* 0 to 3 levels */
    uint8_t perish;        /* the Perish count shown, 3 to 1; 0: none */
    uint8_t reserved[4];   /* zero */
} duoforge_position_ext; /* 16 bytes */

/* One roster member, bench included. */
typedef struct duoforge_member_ext {
    uint16_t forme;   /* forme id + 1 when the current forme differs from the sheet's (and the Mega forme); else 0 */
    uint8_t item_now; /* 0: as the member view; 1 to 254: it now holds item (value - 1); DUOFORGE_ITEM_NOW_NONE */
    uint8_t reserved; /* zero */
} duoforge_member_ext; /* 4 bytes */

typedef struct duoforge_side_ext {
    duoforge_position_ext positions[DUOFORGE_ACTIVE_PER_SIDE];
    duoforge_member_ext members[DUOFORGE_MAX_ROSTER];
    uint8_t aurora_veil_turns; /* 0 to 8 */
    uint8_t stealth_rock;      /* 0/1 */
    uint8_t spikes;            /* 0 to 3 layers */
    uint8_t toxic_spikes;      /* 0 to 2 layers */
    uint8_t sticky_web;        /* 0/1 */
    uint8_t guard_flags;       /* DUOFORGE_SIDE_GUARD_*: this turn only, so only at a PIVOT boundary */
    uint8_t reserved[2];       /* zero */
} duoforge_side_ext; /* 64 bytes */

typedef struct duoforge_observation_ext {
    uint8_t revision;     /* 0: absent (not a POOL kind), the struct is all zero; else the layout revision */
    uint8_t player;       /* the viewer, as duoforge_observation.player; 0 when revision is 0 */
    uint8_t reserved0[2]; /* zero */
    uint32_t epoch;       /* the request epoch of the paired duoforge_observation; 0 when revision is 0 */
    uint64_t supported;   /* bit DUOFORGE_VIEWEXT_FEATURE_* set: the feature's mechanic is implemented and tested */
    duoforge_field_ext field;
    duoforge_side_ext sides[DUOFORGE_SIDE_COUNT];
    uint8_t reserved1[32]; /* zero: room for a whole new record */
} duoforge_observation_ext; /* DUOFORGE_OBSERVATION_EXT_SIZE bytes */
/* A size mismatch is a compile error here (negative array size), in C and in C++. */
typedef char duoforge_observation_ext_size_check[(sizeof(duoforge_observation_ext) == DUOFORGE_OBSERVATION_EXT_SIZE) ? 1 : -1];

/* The extension of one player's view. Pure, allocation-free, with the checks
   of duoforge_battle_observe: NULL -> E_NULL_ARGUMENT -> E_CONTEXT_MISMATCH ->
   E_INVALID_ARGUMENT (player) -> E_INVARIANT. *out is written only on
   success. Under a kind other than POOL and POOL_DEV (SYNTHETIC included) the
   checks run and *out is all zero. */
duoforge_status duoforge_battle_observe_ext(const duoforge_context *ctx, const duoforge_battle *battle,
                                            uint32_t viewer, duoforge_observation_ext *out);

/* ---- event log (decision 0007 section 6) ----
   What happened during a step, per player, in the order the game shows it:
   one event per line of the public battle protocol that the game shows to
   that player (sim/battle.ts at the pin). HP in an event is exact for the
   player's own Pokemon and the percent display for the opponent's, as on
   the two players' screens. Events are outputs of a step, not state. */
#define DUOFORGE_MAX_EVENTS 512u /* profile bound: events per player and step */
#define DUOFORGE_NO_POSITION 0xFFu

/* Event kinds; the protocol line each one stands for in brackets. */
#define DUOFORGE_EVENT_TURN            1u  /* [turn] id: the turn that starts */
#define DUOFORGE_EVENT_SWITCH          2u  /* [switch] position, id: roster index, HP; cause MOVE + id2 when a move made it */
#define DUOFORGE_EVENT_MOVE            3u  /* [move] position: user, other: target or NO_POSITION, id: move, flags; SPREAD: amount = the slots hit (bit = position) */
#define DUOFORGE_EVENT_DAMAGE          4u  /* [-damage] position, HP after; cause (+ id2, other) */
#define DUOFORGE_EVENT_HEAL            5u  /* [-heal] position, HP after; cause (+ id2, other) */
#define DUOFORGE_EVENT_FAINT           6u  /* [faint] position */
#define DUOFORGE_EVENT_CANT            7u  /* [cant] position, cause: why; ABILITY + id2 with id: the stopped move, other */
#define DUOFORGE_EVENT_MISS            8u  /* [-miss] position: user, other: target */
#define DUOFORGE_EVENT_CRIT            9u  /* [-crit] position: target */
#define DUOFORGE_EVENT_SUPER_EFFECTIVE 10u /* [-supereffective] position: target, amount: 1 or 2 (x2, x4) */
#define DUOFORGE_EVENT_RESISTED        11u /* [-resisted] position: target, amount: 1 or 2 (x1/2, x1/4) */
#define DUOFORGE_EVENT_IMMUNE          12u /* [-immune] position; cause ABILITY + id2 when an ability did it */
#define DUOFORGE_EVENT_FAIL            13u /* [-fail] position; detail: the ailment it already has, when that is why.
                                              POOL kinds: cause ABILITY + id2 (Inner Focus), other the holder:
                                              [-fail] unboost atk [from] ability: Inner Focus, an Intimidate drop. */
#define DUOFORGE_EVENT_PROTECT         14u /* [-singleturn Protect] position */
#define DUOFORGE_EVENT_BLOCKED         15u /* [-activate move: Protect] position: the protected Pokemon
                                              (detail 0); detail DUOFORGE_FIELD_PSYCHIC_TERRAIN: [-activate move:
                                              Psychic Terrain], a priority move stopped at a grounded target
                                              (Team C); detail DUOFORGE_BLOCK_WIDE_GUARD: [-activate move: Wide
                                              Guard], a spread move stopped at a target of the guarded side
                                              (POOL kinds) */
#define DUOFORGE_EVENT_BOOST           16u /* [-boost] position, detail: stat (0 atk .. 6 evasion), amount; cause */
#define DUOFORGE_EVENT_UNBOOST         17u /* [-unboost] as BOOST */
#define DUOFORGE_EVENT_STATUS          18u /* [-status] position, detail: DUOFORGE_AILMENT_* */
#define DUOFORGE_EVENT_CURE_STATUS     19u /* [-curestatus] position, detail: the ailment that ended; cause MOVE
                                              + id2 when a defrost move thaws its user (Team C) */
#define DUOFORGE_EVENT_CONFUSION_START 20u /* [-start confusion] position */
#define DUOFORGE_EVENT_CONFUSION_END   21u /* [-end confusion] position */
#define DUOFORGE_EVENT_CONFUSED        22u /* [-activate confusion] position: it is confused as it tries to act */
#define DUOFORGE_EVENT_FLASH_FIRE      23u /* [-start ability: Flash Fire] position */
#define DUOFORGE_EVENT_WEATHER         24u /* [-weather] detail: DUOFORGE_WEATHER_*; flags UPKEEP; cause ABILITY + id2, other */
#define DUOFORGE_EVENT_FIELD_START     25u /* [-fieldstart] detail: DUOFORGE_FIELD_*; cause ABILITY + id2, other */
#define DUOFORGE_EVENT_FIELD_END       26u /* [-fieldend] detail: DUOFORGE_FIELD_* */
#define DUOFORGE_EVENT_SIDE_START      27u /* [-sidestart] detail: the side, amount: DUOFORGE_SIDE_* */
#define DUOFORGE_EVENT_SIDE_END        28u /* [-sideend] as SIDE_START */
#define DUOFORGE_EVENT_ITEM_END        29u /* [-enditem] position, id2: item + 1; flags EATEN; detail 1: the
                                              [weaken] line of a resist berry (Team C) */
#define DUOFORGE_EVENT_FORME           30u /* [detailschange] position, id: the new forme */
#define DUOFORGE_EVENT_MEGA            31u /* [-mega] position, id2: the stone (item + 1) */
#define DUOFORGE_EVENT_PREPARE         32u /* [-prepare] position, id: the move it charges */
#define DUOFORGE_EVENT_ANIMATION       33u /* [-anim] position, other, id: the move shown; flags MISS, NOTARGET
                                                    (the last move line once shown) */
#define DUOFORGE_EVENT_ABILITY         34u /* [-ability] position, id2: ability + 1. POOL kinds, cause ABILITY (Trace copying
                                               a foe's): other is the foe, id2 the copied ability + 1 */
#define DUOFORGE_EVENT_ACTIVATE        35u /* [-activate] position; cause ABILITY + id2 (Lightning Rod, Emergency Exit) or MOVE + id2 (Struggle);
                                                    Flower Veil's [-block] too: position the protected Pokemon, other the holder ([of]);
                                                    POOL kinds: [-fieldactivate|move: Perish Song] is cause MOVE, id2 the move, position
                                                    and other DUOFORGE_NO_POSITION */
#define DUOFORGE_EVENT_UPKEEP          36u /* [upkeep] the end-of-turn effects are done */
#define DUOFORGE_EVENT_RESULT          37u /* [win] or [tie] detail: DUOFORGE_RESULT_* */
#define DUOFORGE_EVENT_SINGLE_TURN     38u /* [-singleturn] position (Team C): id: the move; other: the user ([of]) for
                                              Helping Hand, DUOFORGE_NO_POSITION for Follow Me */
#define DUOFORGE_EVENT_VOLATILE_START  39u /* [-start] position (POOL kinds), detail: DUOFORGE_VOLATILE_* (a volatile that the
                                              game shows: -start|X|move: Heal Block) */
#define DUOFORGE_EVENT_VOLATILE_END    40u /* [-end] position (POOL kinds), detail: DUOFORGE_VOLATILE_* */
#define DUOFORGE_EVENT_TYPE_CHANGE     41u /* [-start|X|typechange|TYPE] position (POOL kinds): the occupant's type is now the single
                                              type in detail (DUOFORGE_TYPE_*; Soak: Water); cause MOVE, id2: the move */

/* Causes ([from] and [of] in the protocol). */
#define DUOFORGE_CAUSE_NONE      0u /* the move or the plain mechanic */
#define DUOFORGE_CAUSE_MOVE      1u /* id2: move id (Parting Shot's switch; a sleep that a move caused; POOL kinds: the damage that
                                        Spiky Shield does to a contact attacker, [-damage] ... [from] Spiky Shield [of] the holder,
                                        the holder in other) */
#define DUOFORGE_CAUSE_ITEM      2u /* id2: item + 1 */
#define DUOFORGE_CAUSE_ABILITY   3u /* id2: ability + 1; other: its holder when shown */
#define DUOFORGE_CAUSE_RECOIL    4u
#define DUOFORGE_CAUSE_DRAIN     5u /* other: the drained Pokemon */
#define DUOFORGE_CAUSE_BURN      6u
#define DUOFORGE_CAUSE_CONFUSION 7u
#define DUOFORGE_CAUSE_TERRAIN   8u /* Grassy Terrain's heal */
#define DUOFORGE_CAUSE_PARALYSIS 9u /* CANT */
#define DUOFORGE_CAUSE_SLEEP     10u
#define DUOFORGE_CAUSE_FREEZE    11u
#define DUOFORGE_CAUSE_FLINCH    12u
#define DUOFORGE_CAUSE_NO_PP     13u
#define DUOFORGE_CAUSE_POISON    14u /* poison's residual damage (Team C) */
#define DUOFORGE_CAUSE_WEATHER   16u /* DAMAGE (POOL kinds): the residual damage of a weather ([from] Sandstorm); id2: the
                                         DUOFORGE_WEATHER_* value. Generic for every weather that damages; in this format
                                         it fires only for Sand: Snow has no residual damage and Hail is not in the format */
#define DUOFORGE_CAUSE_RECHARGE  18u /* CANT (POOL kinds): the recharge turn after a recharge move ([cant] recharge) */
#define DUOFORGE_CAUSE_DISABLE   19u /* CANT (POOL kinds): the move that Disable bars ([cant] Disable|move); id: the move */
#define DUOFORGE_CAUSE_HEAL_BLOCK 15u /* CANT (POOL kinds): a move that heals, stopped by Heal Block; id: the stopped move.
                                         A sound move stopped by Throat Chop is CANT with cause MOVE, id2: Throat Chop
                                         (the line names no move, so id is 0) */
#define DUOFORGE_CAUSE_ITEM_TAKEN 17u /* ITEM_END (POOL kinds): the item was taken by a move ([from] move: Knock Off [of]
                                         the user); id: the move, other: the user, id2: item + 1. The old item_used
                                         of the view shows it gone as for an item used up; item_now tells them apart
                                         (DUOFORGE_ITEM_NOW_NONE) */
#define DUOFORGE_CAUSE_IMPRISON  21u /* CANT (POOL kinds): a move that the foe's Imprison forbids, queued before it was used
                                         ([cant] move: Imprison|Move); id: the stopped move, no PP is used */

#define DUOFORGE_EVENT_FLAG_STILL  1u  /* MOVE: the charge turn of a two-turn move */
#define DUOFORGE_EVENT_FLAG_LOCKED 2u  /* MOVE: the locked turn ([from] lockedmove) */
#define DUOFORGE_EVENT_FLAG_SPREAD 4u  /* MOVE: a spread move; other is NO_POSITION */
#define DUOFORGE_EVENT_FLAG_UPKEEP 8u  /* WEATHER: it continues at the end of the turn */
#define DUOFORGE_EVENT_FLAG_EATEN  16u /* ITEM_END: a berry eaten */
#define DUOFORGE_EVENT_FLAG_MESSAGE 32u /* CURE_STATUS: with its own message ([msg]) */
#define DUOFORGE_EVENT_FLAG_MISS     64u  /* MOVE: a single-target move missed ([miss]) */
#define DUOFORGE_EVENT_FLAG_NOTARGET 128u /* MOVE: no target left ([notarget]) */

#define DUOFORGE_BLOCK_WIDE_GUARD 4u /* BLOCKED detail: Wide Guard (POOL kinds); 0 Protect, 3 Psychic Terrain */
#define DUOFORGE_VOLATILE_HEAL_BLOCK 1u /* VOLATILE_START / VOLATILE_END: Heal Block (Psychic Noise, 2 turns) */
#define DUOFORGE_VOLATILE_ENCORE     2u /* VOLATILE_START / VOLATILE_END: Encore (-start|X|Encore, -end|X|Encore) */
#define DUOFORGE_VOLATILE_MUST_RECHARGE 3u /* VOLATILE_START: -mustrecharge|X (a recharge move hit); no END, it ends with the
                                              [cant] recharge line or with the occupant */
#define DUOFORGE_VOLATILE_DISABLE    4u /* VOLATILE_START / VOLATILE_END: Disable (-start|X|Disable|MOVE, -end|X|Disable); START: id: the
                                              barred move, and for Cursed Body cause ABILITY, id2: ability + 1, other: its holder */
#define DUOFORGE_VOLATILE_PERISH     5u /* VOLATILE_START: -start|X|perishN (Perish Song): amount N, 3 to 0, one line per count
                                              in the residual; at 0 the holder faints (a FAINT event follows the UPKEEP). No
                                              END; the cast itself shows nothing (its -start perish3 is [silent]) */
#define DUOFORGE_VOLATILE_IMPRISON   8u /* VOLATILE_START (POOL kinds): -start|X|move: Imprison; no END, it ends with the occupant
                                              (position: the Pokemon that used it; its foes may not use the moves it knows) */
#define DUOFORGE_FIELD_GRASSY_TERRAIN 1u
#define DUOFORGE_FIELD_TRICK_ROOM     2u
#define DUOFORGE_FIELD_PSYCHIC_TERRAIN 3u /* Team C */
#define DUOFORGE_FIELD_ELECTRIC_TERRAIN 4u /* POOL kinds (step G25): FIELD_START / FIELD_END detail */
#define DUOFORGE_FIELD_MISTY_TERRAIN   5u /* POOL kinds (step G25) */
#define DUOFORGE_SIDE_TAILWIND     1u
#define DUOFORGE_SIDE_REFLECT      2u
#define DUOFORGE_SIDE_LIGHT_SCREEN 3u
#define DUOFORGE_SIDE_AURORA_VEIL  4u /* SIDE_START / SIDE_END amount (POOL kinds): -sidestart|side|move: Aurora Veil */
#define DUOFORGE_RESULT_SIDE_0 1u
#define DUOFORGE_RESULT_SIDE_1 2u
#define DUOFORGE_RESULT_TIE    3u

typedef struct duoforge_event {
    uint8_t kind;     /* DUOFORGE_EVENT_* */
    uint8_t position; /* side * 2 + slot of the Pokemon it is about, or DUOFORGE_NO_POSITION */
    uint8_t other;    /* the other Pokemon (target, source, holder), or DUOFORGE_NO_POSITION */
    uint8_t cause;    /* DUOFORGE_CAUSE_* */
    uint16_t id;      /* per kind: move, roster index, forme, turn */
    uint16_t id2;     /* per cause: move id, item + 1, ability + 1 */
    uint16_t hp;      /* HP after (SWITCH, DAMAGE, HEAL), per hp_kind */
    uint16_t hp_max;  /* per hp_kind */
    uint8_t hp_kind;  /* DUOFORGE_HP_EXACT (own), DUOFORGE_HP_PERCENT (opponent), 0 without HP */
    uint8_t hp_flag;  /* DUOFORGE_HP_FLAG_* (PERCENT only) */
    uint8_t status;   /* DUOFORGE_AILMENT_* shown with the HP */
    uint8_t detail;   /* per kind */
    uint8_t amount;   /* per kind: stages, side condition */
    uint8_t flags;    /* DUOFORGE_EVENT_FLAG_* */
    uint8_t reserved[2]; /* zero */
} duoforge_event; /* 20 bytes */

/* One player's event buffer: the caller provides `events` with `capacity`
   records; the step writes `count`. */
typedef struct duoforge_event_buffer {
    duoforge_event *events; /* may be NULL when capacity is 0 */
    uint32_t capacity;
    uint32_t count;
} duoforge_event_buffer;

/* duoforge_battle_step, and the events each player sees: buffers[p] gets
   player p's events of this step in order (decision 0007 section 11).
   Checks as duoforge_battle_step; buffers NULL is NULL_ARGUMENT, a buffer
   with capacity but no storage INVALID_ARGUMENT. If a buffer is too small,
   E_CAPACITY: the battle is unchanged, *out_result unwritten, and only the
   two `count` fields are written, each with the required number (decision
   0005 section 7). A step has at most DUOFORGE_MAX_EVENTS events; more
   would be E_INVARIANT, never a truncated log. */
duoforge_status duoforge_battle_step_events(const duoforge_context *ctx, duoforge_battle *battle,
                                            const duoforge_decision_bundle *bundle,
                                            duoforge_step_result *out_result,
                                            duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT]);

#ifdef __cplusplus
}
#endif

#endif
