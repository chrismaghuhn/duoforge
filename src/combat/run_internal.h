#ifndef DUOFORGE_COMBAT_RUN_INTERNAL_H
#define DUOFORGE_COMBAT_RUN_INTERNAL_H

/* Private scratch for one turn action. Extracted without changing its layout
 * or lifetime; positional initializers remain in turn.c. No public API. */
#include "combat/events.h"
#include "rng/draw.h"
#include "state/battle_internal.h"

#define DFI_POSITIONS 4u

typedef struct dfi_run {
    const struct duoforge_context *ctx;
    struct duoforge_battle *b;
    dfi_draws *draws;
    /* Pokemon whose HP reached 0 during the current action, in that order
     * (the reference's faintQueue). */
    uint32_t faint_queue[DFI_POSITIONS];
    uint32_t faint_count;
    uint32_t faint_announced; /* how many of them a faintMessages already showed */
    uint32_t last_fainted; /* flat position of the last processed faint */
    bool ended;
    /* The result a hit loop's faintMessages already showed (DFI_RESULT_*),
     * DFI_RESULT_NONE when the end of the action shows it. */
    uint32_t early_result;
    /* pokemon.speed: the speed key of each position at the reference's last
     * updateSpeed while its Pokemon stood (a fainted Pokemon keeps it). */
    uint32_t speed_seen[DFI_POSITIONS];
    /* residualPokemon: each position's HP before the residual events. */
    uint32_t residual_hp[DFI_POSITIONS];
    /* The step's events (docs/decisions/0007 section 6), NULL for none, and
     * the index of the current action's move event, which later protocol
     * lines amend (attrLastMove, retargetLastMove), or UINT32_MAX. */
    dfi_events *events;
    uint32_t last_move;
    /* The current move action got past BeforeMove and used its move
     * (useMove ran): the AfterMove event follows. */
    bool move_used;
    /* runMove's target, which AfterMove gets (DFI_MOVE_TARGET_*). */
    uint32_t move_target;
    /* move.hit (step G33): the hit of a multi-hit move that is being made, 1 for every other move. */
    uint32_t hit_index;
    /* step G46: the positions whose switch flag (forceSwitchFlag) a forced switch set and that have not been dragged in
     * yet (bit flat). Transient: it lives in the run, never in the state, and only the phazing step after the action
     * clears it. Emergency Exit and Eject Button ignore such a holder (Champions abilities.ts:24, items.ts:270). */
    uint32_t drag_pending;
    /* step G56: the positions whose lockedmove (Outrage, Thrash, Petal Dance) duration is 2 in this step: started, or
     * restarted with a count of 2 or more (onRestart). Transient, like drag_pending; read and cleared by the AfterMove of the use (the
     * count goes down there, so no residual of a later call needs it). */
    uint32_t lock_restarted;
    /* step G42: the classification of the current move action's result (DFI_MRES_*, bits; 0 = none seen). */
    uint32_t mres;
    /* Step G45, Moxie: the cause of the last faint queued (faintData, the last of faintQueue, sim/battle.ts:2549-2601): the
     * flat position of the Pokemon that caused it, and whether it is the direct damage of a Move (effect.effectType 'Move').
     * Read only while faint_count is not 0; every queued faint sets both.
     * Run-scoped scratch, not state: they are set and read inside one step's dfi_run (between the faint announcement and
     * AfterFaint, or the process of the same action), never saved in the battle, the codec or the digest. The epilogue of
     * every action runs dfi_process_faints before the step can end (a PIVOT boundary included), which resets faint_count, so
     * the fields are dead at a step boundary. If that ever stopped being true they would be state: stop and report. */
    uint32_t last_faint_by;
    bool last_faint_move;
    /* step G64, Beat Up: the base power of each hit of the move being made (dfi_beat_up_hits fills it when the move is used; the
     * hit count is the number of entries). Transient, read only by dfi_get_damage of that move. Last in the struct: the
     * initializers of dfi_run are positional, so a field before the end would shift their values. */
    uint32_t beat_up_bp[DUOFORGE_MAX_ROSTER];
    /* Decision 0032: set only while the damage of a Substitute's hit is computed. The damage then ignores the target's resist
     * berry (pin: `hitSub`, data/items.ts:1030-1046 and its siblings: the berry is not eaten for a hit that the Substitute takes). */
    bool sub_hit;
    /* step G78, Dragon Darts (decision 0043): the move's smartTarget flag during one move. It is set when the move is split
     * over two targets and cleared by a drop of a step, as Showdown clears it (sim/battle-actions.ts:607, :633, :661, :739,
     * data/moves.ts:1010-1011). Run-scoped scratch, never state. Last in the struct (positional initializers). */
    bool smart;
    /* Step G69, Symbiosis: an E_UNSUPPORTED found inside a handler that returns nothing (dfi_use_item_of and the eaters around
     * it). The turn runs on a working copy (src/state/request.c), so dfi_turn_run returns it at its end and nothing is
     * committed. Last in the struct: the initializers of dfi_run are positional. */
    duoforge_status deferred;
    /* The pin's activeTarget for the Substitute hit that sub_hit marks (sim/battle-actions.ts:693, :1154). Last in the struct
     * (positional initializers, which take 0u here). */
    uint32_t sub_active;
    /* step K2 (Piercing Drill, decision 0015 5dd): the flat positions (bit t) whose protection the current hit's move passed through
     * by the holder's HitProtect bypass. Transient: cleared before each hit's protection checks, read by that hit's damage. Last in
     * the struct (positional initializers, which take 0u here). */
    uint32_t protect_bypass;
} dfi_run;

static inline dfi_active_slot *dfi_pos(struct duoforge_battle *b, uint32_t flat)
{
    return &b->sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE];
}

/* The member at a flat position, or NULL when it is empty. */
static inline dfi_member *dfi_at(struct duoforge_battle *b, uint32_t flat)
{
    const uint32_t occupant = dfi_pos(b, flat)->occupant;
    if (occupant >= DUOFORGE_MAX_ROSTER) {
        return NULL;
    }
    return &b->sides[flat / DUOFORGE_ACTIVE_PER_SIDE].members[occupant];
}

static inline void dfi_emit(dfi_run *r, const duoforge_event *e)
{
    if (r->events != NULL) {
        dfi_events_push(r->events, e);
    }
}

/* An event about `position` with a cause ([from], [of]). */
static inline duoforge_event dfi_ev(uint32_t kind, uint32_t position, uint32_t cause, uint32_t id2, uint32_t other)
{
    duoforge_event e = dfi_event_make(kind, position);
    e.cause = (uint8_t)cause; /* <= DUOFORGE_CAUSE_POISON */
    e.id2 = (uint16_t)id2;    /* < 2^16 */
    e.other = (uint8_t)other; /* < 4 or DUOFORGE_NO_POSITION */
    return e;
}

#endif
