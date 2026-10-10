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
 * Visible sleep/confusion is currently unsupported; the mappings below only
 * preserve inactive counters (e.g. a faint awaiting cleanup) for round trips.
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
 *   - visible sleep or confusion: elapsed attempts are not in schema 3;
 *   - a PIVOT without a public current-turn move volatile (the pre-move phase can still
 *     hide a Mega declaration; a queue-kind refusal would leak it);
 *   - sealed opponent commands, or a queue with actions other than MOVE and
 *     RESIDUAL (switch/entry/mega continuations need another representation);
 *   - a foe Substitute (its HP follows hidden damage);
 *   - a partial trap or a locked move (no mechanic draws their turns yet).
 *
 * duoforge_battle_hypothesis is PRIVILEGED (decision 0002): it reads the true
 * hidden values, for tests and the oracle; it is never model-facing.
 */
#include <duoforge/duoforge.h>
#include <duoforge/duoforge_batch.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUOFORGE_VIEW_REVISION 2u
#define DUOFORGE_HYPOTHESIS_REVISION 2u
#define DUOFORGE_VIEW_STATE_MAX 1357u /* the largest canonical state (the POOL kinds, tail rev 5) */
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
    uint8_t foe_pending_mask; /* positions with a queued MOVE */
    uint8_t queue_count;      /* canonical queue records */
    uint8_t reserved[3];   /* zero */
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
    duoforge_slot_command queued[DUOFORGE_ACTIVE_PER_SIDE]; /* foe MOVE commands still pending; zero otherwise */
    uint8_t queue_order[12]; /* original index of each canonical queue record; permutation at PIVOT */
    uint8_t reserved2[4];
} duoforge_hypothesis;

/* The causes of a public refusal that the player's view decides (decision 0023; decision 0026 section 4). Bits of
 * duoforge_battle_public_causes' mask: a visible sleep (a member of either side), a visible confusion (a position of either
 * side), and ILLUSION_POSSIBLE, which stays 0 until Illusion is implemented. duoforge_battle_public refuses (E_UNSUPPORTED)
 * while the mask is nonzero, and also while a foe's Revival Blessing slot shows derived PP 0 (decision 0023's PP proxy,
 * decision 0025 item 11): that refusal has no cause bit, so the mask is 0 for it. A mask of 0 with a refusing
 * duoforge_battle_public therefore means another refusal (a PIVOT, sealed commands, a foe Substitute, a partial trap, a
 * locked move, or the Revival Blessing proxy). The mask depends only on the player's view. */
#define DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP 1u
#define DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION 2u
#define DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE 4u
/* SUBSTITUTE (decision 0032): either side, any position with VOLATILE_SUBSTITUTE up. The Substitute's HP is hidden from both
 * sides (the owner's request does not show it either), so an honest world cannot rebuild it: the public record and
 * duoforge_battle_from_view refuse with this cause. */
#define DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE 8u
/* TEMP_FORME (decision 0040, step G66): either side, any position in a temporary forme (Stance Change: Aegislash-Blade).
 * The view does not show that forme yet (member_ext.forme stays unfilled in G66, a later step), so duoforge_battle_from_view
 * and the public record refuse with this cause. */
#define DUOFORGE_PUBLIC_CAUSE_TEMP_FORME 16u
/* RAISED_THIS_TURN (step G72b, decision 0015 5ce): a PIVOT boundary (a switch inside a turn, the step stops there) while an
 * active Pokemon of either side has Alluring Voice among its known moves. The view does not carry stats_raised_this_turn
 * (set by any positive boost of the turn, cleared in endTurn and on switch-out, sim/battle.ts:1678, sim/battle-actions.ts:123),
 * so duoforge_battle_from_view and the public record cannot rebuild it mid-turn and refuse with this cause. A turn boundary
 * is not affected (the bit is zero there, endTurn cleared it), and neither is a REPLACEMENT at the end of a turn: the bit is
 * reset for the next turn anyway. */
#define DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN 32u

/* Argument errors touch no output. Otherwise statuses are per environment,
 * the return is the first failure, and each failing environment is atomic.
 * Both operations run on the batch workers without allocation. */
duoforge_status duoforge_batch_public(duoforge_batch *batch, const uint32_t *players,
                                      duoforge_public_state *out, duoforge_status *statuses);
/* The causes of every environment (duoforge_battle_public_causes, per environment, on the batch workers): the same arguments as
 * duoforge_batch_public, with out_masks[e] written for each environment that succeeds. */
duoforge_status duoforge_batch_public_causes(duoforge_batch *batch, const uint32_t *players, uint32_t *out_masks,
                                             duoforge_status *statuses);
duoforge_status duoforge_batch_from_view(duoforge_batch *worlds, const duoforge_public_state *views,
                                         const duoforge_hypothesis *hypotheses, uint32_t count,
                                         duoforge_status *statuses);
/* 32 x 32 pair mask of the foe's turn-start domain. Ambiguous unseen bench
 * membership is E_UNSUPPORTED: its switch options change the pair indices.
 * Targets are not compared. On any refusal mask is untouched. */
duoforge_status duoforge_public_queue_mask(const duoforge_context *ctx, const duoforge_public_state *turn_start,
                                           const duoforge_public_state *view, uint8_t *mask);

/* One player's public state of a battle. Checks: NULL -> E_NULL_ARGUMENT,
   CONTEXT_MISMATCH, player > 1 -> E_INVALID_ARGUMENT, the full state check ->
   E_INVARIANT, then E_UNSUPPORTED (above). *out is written only on success. */
duoforge_status duoforge_battle_public(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                       duoforge_public_state *out);

/* The causes of the refusal of duoforge_battle_public for this player, as the DUOFORGE_PUBLIC_CAUSE_* mask (above). A pure call:
   it writes nothing else. Checks in the order of duoforge_battle_public: NULL -> E_NULL_ARGUMENT (out_mask too), CONTEXT_MISMATCH,
   player > 1 -> E_INVALID_ARGUMENT, the full state check -> E_INVARIANT. *out_mask is written only on success. */
duoforge_status duoforge_battle_public_causes(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                              uint32_t *out_mask);

/* The world of a public state and a hypothesis, written into *out (a battle of
   the same context, as duoforge_battle_copy's destination). Its RNG is seeded
   with (0, 0): a search reseeds every leaf (decision 0022). Checks: NULL ->
   E_NULL_ARGUMENT; a revision -> E_SCHEMA_MISMATCH; reserved bytes, the size,
   the player -> E_MALFORMED; the fingerprint -> E_CONTEXT_MISMATCH; a
   hypothesis against the record (a spread past 32 or 66, a pick order that is
   not a brought set agreeing with the leads and the members seen, or any pick
   at TEAM_SELECTION) -> E_INVALID_ARGUMENT; the built world's full check ->
   E_MALFORMED. Unmodelled public features are E_UNSUPPORTED; a public
   support-query invariant failure is E_INVARIANT. *out is written only on success. */
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
