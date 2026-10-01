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
 * Combat runs for CLOSURE data (decision 0006 section 4): TURN,
 * REPLACEMENT and PIVOT bundles execute the turn of the combat closure;
 * under SYNTHETIC data every combat bundle is rejected with E_UNSUPPORTED.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VERSION_MAJOR 0
#define DUOFORGE_VERSION_MINOR 5
#define DUOFORGE_VERSION_PATCH 0
#define DUOFORGE_VERSION_STRING "0.5.0"

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
#define DUOFORGE_DATA_KIND_CLOSURE     2u /* the generated closure tables; format-legal sets only */
#define DUOFORGE_DATA_KIND_CLOSURE_DEV 3u /* the closure tables; as CLOSURE, but a member may have
                                             No Ability (development fixtures) */
typedef struct duoforge_context duoforge_context;
typedef struct duoforge_context_config {
    uint32_t data_kind;     /* DUOFORGE_DATA_KIND_* */
    uint32_t max_roster;    /* 1..DUOFORGE_MAX_ROSTER */
    uint32_t brought_count; /* 1..max_roster; picked at TEAM_SELECTION */
    uint32_t species_count; /* SYNTHETIC: 1..65535, species ids 0..species_count-1; CLOSURE: 0 */
    uint32_t move_count;    /* SYNTHETIC: 1..65535, move ids 0..move_count-1; CLOSURE: 0 */
    /* SYNTHETIC: move_count bytes, each a DUOFORGE_TARGET_CLASS_* value 1..9;
       copied at create (read once) and hashed into the fingerprint.
       CLOSURE: NULL (the generated tables are built in). */
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
   (SYNTHETIC) or of the generated closure tables (CLOSURE kinds).
   Independent of platform and build. */
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
   implemented yet is rejected with E_UNSUPPORTED. ---- */
#define DUOFORGE_GENDER_MALE   1u
#define DUOFORGE_GENDER_FEMALE 2u
#define DUOFORGE_GENDER_NONE   3u /* genderless species */
#define DUOFORGE_STAT_POINTS_MAX       32u /* per stat */
#define DUOFORGE_STAT_POINTS_TOTAL_MAX 66u /* per member */
typedef struct duoforge_move_setup {
    uint32_t move_id; /* < context move_count; CLOSURE: a move of the forme's set */
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
    uint32_t ability;        /* CLOSURE: 1 + the forme's ability id; 0 = No Ability (CLOSURE_DEV only) */
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

/* Allocation-free. */
/* In-process snapshot/restore: after NULL and context checks, dst == src is a no-op. */
duoforge_status duoforge_battle_copy(const duoforge_context *ctx, duoforge_battle *dst,
                                     const duoforge_battle *src);
duoforge_status duoforge_battle_decode(const duoforge_context *ctx, duoforge_battle *dst,
                                       const uint8_t *bytes, size_t size);
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
/* move_slot of Struggle: offered, with no target, exactly when an occupant
   has no move with PP left (sim/side.ts, the reference's request). */
#define DUOFORGE_MOVE_SLOT_STRUGGLE 4u
#define DUOFORGE_CHOICE_TEAM_SELECTION 1u
#define DUOFORGE_CHOICE_SLOTS          2u
/* Profile bound on a complete side-choice domain: max(720 ordered picks of 6,
   28 x 28 joint slot choices). A caller may allocate this once. */
#define DUOFORGE_MAX_CANDIDATES 784u

typedef struct duoforge_slot_command {
    uint8_t kind;        /* DUOFORGE_SLOT_* */
    uint8_t move_slot;   /* MOVE: 0..3, or DUOFORGE_MOVE_SLOT_STRUGGLE */
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
/* The complete joint side-choice domain of one player in documented order
   (decision 0005 section 3). With capacity < count the call returns
   E_CAPACITY and writes ONLY *out_count = required; the buffer is untouched.
   Otherwise the first *out_count records are written. */
duoforge_status duoforge_battle_candidates(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_side_choice *buffer, uint32_t capacity,
                                           uint32_t *out_count);
/* Submits the responses of exactly the requested sides. Checks: NULL ->
   CONTEXT_MISMATCH -> INVARIANT -> STALE_EPOCH (bundle or response epoch) ->
   INVALID_ARGUMENT (mask, reserved bytes, side/kind fields, a response
   outside the offered domain, a nonzero response of an unrequested side).
   A valid TEAM_SELECTION bundle performs the transition to TURN (for
   CLOSURE data with the leads' entry effects). A valid TURN or REPLACEMENT
   bundle of a CLOSURE battle runs the turn (decision 0006); a mechanic the
   support manifest does not mark returns E_UNSUPPORTED, as does every
   combat bundle under SYNTHETIC data. A valid PIVOT bundle (switches for
   the flagged positions) continues the stored rest of the turn. At TERMINAL every
   bundle is INVALID_ARGUMENT: the battle is over.
   E_EXHAUSTED if the epoch or activation counter would overflow. Every
   failure leaves the battle unchanged and *out_result unwritten. */
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
#define DUOFORGE_WEATHER_NONE 0u
#define DUOFORGE_WEATHER_RAIN 1u
#define DUOFORGE_WEATHER_SUN  2u
#define DUOFORGE_TERRAIN_NONE   0u
#define DUOFORGE_TERRAIN_GRASSY 1u
#define DUOFORGE_MOVE_SLOT_NONE 0xFFu /* position view: no locked move */

typedef struct duoforge_member_view {
    uint16_t species_id; /* open; 0 with all other fields 0 for an unregistered slot */
    uint16_t hp;         /* per hp_kind */
    uint16_t hp_max;     /* per hp_kind */
    uint16_t move_ids[DUOFORGE_MAX_MOVE_SLOTS]; /* open; unused slots 0 */
    uint8_t pp[DUOFORGE_MAX_MOVE_SLOTS];        /* per pp_kind */
    uint8_t pp_max[DUOFORGE_MAX_MOVE_SLOTS];    /* open; unused slots 0 */
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
} duoforge_member_view; /* 36 bytes */

/* An active position as both players see it; all zero for an empty one. */
typedef struct duoforge_position_view {
    uint8_t stages[7];     /* public: atk def spa spd spe accuracy evasion, biased by 6 (6 = neutral) */
    uint8_t confused;      /* public: 1 while confused; the turns stay hidden */
    uint8_t charging;      /* public: 1 while a two-turn move is charged */
    uint8_t locked_slot;   /* public: the locked move slot, DUOFORGE_MOVE_SLOT_NONE if none */
    uint8_t locked_target; /* own side only: the stored target (flat position); 0 for the foe */
    uint8_t acted;         /* public: 1 once the occupant took a move action since it entered */
    uint8_t protect_chain; /* public: consecutive successful Protects (stall counter level) */
    uint8_t flash_fire;    /* public: 1 while Flash Fire's boost is active */
    uint8_t reserved[2];   /* zero */
} duoforge_position_view; /* 16 bytes */

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
} duoforge_side_view; /* 264 bytes */

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
} duoforge_observation; /* 544 bytes */

/* Pure. Checks: NULL -> CONTEXT_MISMATCH -> INVALID_ARGUMENT (player) ->
   INVARIANT. Writes *out_observation only on success. */
duoforge_status duoforge_battle_observe(const duoforge_context *ctx, const duoforge_battle *battle,
                                        uint32_t player, duoforge_observation *out_observation);

#ifdef __cplusplus
}
#endif

#endif
