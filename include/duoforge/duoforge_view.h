#ifndef DUOFORGE_VIEW_H
#define DUOFORGE_VIEW_H

/*
 * Views and worlds (decision 0023, roadmap M12): a player's complete public
 * knowledge of a battle, and complete battles built from it and a sampled
 * assignment of what it leaves open ("determinization", decision 0013
 * section 6.2).
 *
 * The public state holds the battle's canonical encoding (decision 0002,
 * src/codec/state_codec.h) with every value hidden from the player replaced:
 *   - the RNG is zero;
 *   - the foe's stat points, stats, maximum HP, exact HP and PP are zero (the
 *     player's knowledge in the same bytes keeps the HP displays and the move
 *     uses it saw);
 *   - the foe's brought set is empty and its pick order keeps only the leads;
 *   - a sleep counter (either side) and a confusion counter (either side)
 *     that runs reads DUOFORGE_VIEW_HIDDEN;
 *   - the target of a charging foe reads DUOFORGE_VIEW_HIDDEN_TARGET.
 * Everything else in the encoding is public: a human at the table knows it.
 *
 * A hypothesis holds numbers only. A uniform is a 64-bit word u read as
 * u / 2^64; the engine maps it in integer arithmetic (no floating point):
 * u picks the floor(u * n / 2^64)-th of n equally weighted values, or under
 * integer weights the value whose cumulative range holds floor(u * W / 2^64).
 *   - foe HP: among the exact values whose display is the one the player
 *     saw, under the world's maximum HP; a member the player never saw is at
 *     full HP;
 *   - a sleep counter: 1, 2 or 3 turns left, weights 3, 3, 2 (sample([2, 3,
 *     3]) seen at a random point of the sleep; the state keeps no elapsed
 *     count to condition on);
 *   - a confusion counter: 1 to 5, weights 4, 4, 3, 2, 1 (random(2, 6));
 *   - a charging target: among the targets the move's class allows.
 *
 * Refused (E_UNSUPPORTED), all decided by public facts:
 *   - a PIVOT where the foe has sealed or queued commands left (a later step
 *     samples them);
 *   - a foe Substitute (its HP follows hidden damage);
 *   - a partial trap or a locked move (no mechanic draws their turns yet).
 *
 * duoforge_battle_hypothesis is PRIVILEGED (decision 0002): it reads the true
 * hidden values, for tests and the oracle; it is never model-facing.
 */
#include <duoforge/duoforge.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VIEW_REVISION 1u
#define DUOFORGE_HYPOTHESIS_REVISION 1u
#define DUOFORGE_VIEW_STATE_MAX 1297u /* the largest canonical state (the POOL kinds) */
#define DUOFORGE_VIEW_HIDDEN 0xFFu    /* a running counter whose value is hidden */
#define DUOFORGE_VIEW_HIDDEN_TARGET 0xFEu
#define DUOFORGE_VIEW_PICK_NONE 0xFFu

typedef struct duoforge_public_state {
    uint32_t revision;     /* DUOFORGE_VIEW_REVISION */
    uint32_t player;       /* 0 or 1 */
    uint32_t state_size;   /* bytes of state[] in use: the context's canonical size */
    uint32_t boundary;     /* DUOFORGE_BOUNDARY_*, as in the state */
    uint32_t turn;
    uint32_t request_mask;
    uint32_t epoch;
    uint8_t foe_seen_mask; /* the foe members the player has seen in battle */
    uint8_t foe_leads[2];  /* roster indices; DUOFORGE_VIEW_PICK_NONE before the leads are out */
    uint8_t reserved[5];   /* zero */
    uint8_t state[DUOFORGE_VIEW_STATE_MAX]; /* the masked canonical encoding; zero past state_size */
    uint8_t pad[3];                         /* zero */
} duoforge_public_state;

typedef struct duoforge_hypothesis {
    uint32_t revision; /* DUOFORGE_HYPOTHESIS_REVISION */
    uint32_t reserved0;
    uint8_t stat_points[DUOFORGE_MAX_ROSTER][6]; /* the foe's, per roster member (hp, atk, def, spa, spd, spe) */
    uint8_t pick_order[DUOFORGE_MAX_ROSTER];     /* the foe's; DUOFORGE_VIEW_PICK_NONE past the brought count and
                                                    everywhere at TEAM_SELECTION */
    uint8_t reserved1[6];
    uint64_t hp[DUOFORGE_MAX_ROSTER];                        /* foe member's exact HP */
    uint64_t sleep[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_ROSTER]; /* per side and member */
    uint64_t confusion[DUOFORGE_SIDE_COUNT][DUOFORGE_ACTIVE_PER_SIDE];
    uint64_t charge_target[DUOFORGE_ACTIVE_PER_SIDE]; /* the foe's positions */
} duoforge_hypothesis;

/* One player's public state of a battle. Checks: NULL -> E_NULL_ARGUMENT,
   CONTEXT_MISMATCH, player > 1 -> E_INVALID_ARGUMENT, the full state check ->
   E_INVARIANT, then E_UNSUPPORTED (above). *out is written only on success. */
duoforge_status duoforge_battle_public(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                       duoforge_public_state *out);

/* The world of a public state and a hypothesis, written into *out (a battle of
   the same context, as duoforge_battle_copy's destination). Its RNG is seeded
   with (0, 0): a search reseeds every leaf (decision 0022). Checks: NULL ->
   E_NULL_ARGUMENT; a revision -> E_SCHEMA_MISMATCH; reserved bytes, the size,
   the player -> E_MALFORMED; the fingerprint -> E_CONTEXT_MISMATCH; a
   hypothesis against the record (a spread past 32 or 66, a pick order that is
   not a brought set agreeing with the leads and the members seen, or any pick
   at TEAM_SELECTION) -> E_INVALID_ARGUMENT; the built world's full check ->
   E_MALFORMED. *out is written only on success. */
duoforge_status duoforge_battle_from_view(const duoforge_context *ctx, const duoforge_public_state *view,
                                          const duoforge_hypothesis *hypothesis, duoforge_battle *out);

/* PRIVILEGED: the hypothesis that rebuilds the battle from the player's
   public state (each uniform the middle of the words that pick the true
   value). Checks as duoforge_battle_public, whose refusals it shares. */
duoforge_status duoforge_battle_hypothesis(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_hypothesis *out);

#ifdef __cplusplus
}
#endif

#endif
