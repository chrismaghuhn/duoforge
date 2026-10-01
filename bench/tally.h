#ifndef DUOFORGE_BENCH_TALLY_H
#define DUOFORGE_BENCH_TALLY_H
/*
 * What a player chose (docs/decisions/0008): counts of the side choices one
 * player submitted, by kind of command. Pure bookkeeping on public types:
 * the choice plus the player's own observation (for the move ids), no rule
 * logic. Call dfb_tally_choice at the boundary, before the step that
 * submits the choice.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

#define DFB_TALLY_MOVE_IDS 1024u /* move ids counted per id; larger ids only in `moves` */

typedef struct dfb_tally {
    uint64_t choices;         /* side choices counted */
    uint64_t team_selections; /* of them at TEAM_SELECTION */
    uint64_t slot_commands;   /* commands for requested positions */
    uint64_t moves;           /* move commands, Struggle included */
    uint64_t struggles;
    uint64_t megas;           /* move commands that declare Mega Evolution */
    uint64_t switches;        /* switches chosen at TURN (voluntary) */
    uint64_t replacements;    /* switches at REPLACEMENT or PIVOT */
    uint64_t passes;
    uint64_t target_foe;      /* moves aimed at a foe position */
    uint64_t target_ally;     /* moves aimed at the ally */
    uint64_t target_none;     /* moves without a chosen target (spread, self, side, field) */
    uint64_t leads[DUOFORGE_MAX_ROSTER];      /* team selection: roster index led with */
    uint64_t move_uses[DFB_TALLY_MOVE_IDS];   /* move commands by move id */
} dfb_tally;

void dfb_tally_reset(dfb_tally *tally);

/* Counts `choice` of `player` at the current boundary of `battle`.
 * E_INVALID_ARGUMENT when the choice does not fit the boundary (wrong kind,
 * a command for an empty position or an unknown move slot); the tally is
 * then unchanged. */
duoforge_status dfb_tally_choice(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                 const duoforge_side_choice *choice, dfb_tally *tally);

/* Adds `from` into `into`. */
void dfb_tally_add(dfb_tally *into, const dfb_tally *from);

#endif
