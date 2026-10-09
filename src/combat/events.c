/*
 * Event records of a step (docs/decisions/0007 section 6). The engine
 * records each event once with exact values; each player receives a
 * projection in which the opponent's HP is shown as the percent display,
 * as on that player's screen.
 */
#include "combat/events.h"

#include <stddef.h>
#include <string.h>

#include "state/knowledge.h"

_Static_assert(sizeof(duoforge_event) == 20u, "event is 20 bytes");
_Static_assert(offsetof(duoforge_event, id) == 4u, "event layout: id");
_Static_assert(offsetof(duoforge_event, hp) == 8u, "event layout: hp");
_Static_assert(offsetof(duoforge_event, hp_kind) == 12u, "event layout: hp kind");
_Static_assert(offsetof(duoforge_event, reserved) == 18u, "event layout: reserved");

duoforge_event dfi_event_make(uint32_t kind, uint32_t position)
{
    duoforge_event e;
    memset(&e, 0, sizeof e);
    e.kind = (uint8_t)kind;         /* <= DUOFORGE_EVENT_ITEM_START */
    e.position = (uint8_t)position; /* < 4 or DUOFORGE_NO_POSITION */
    e.other = (uint8_t)DUOFORGE_NO_POSITION;
    return e;
}

void dfi_events_push(dfi_events *events, const duoforge_event *e)
{
    if (events->count >= DUOFORGE_MAX_EVENTS) {
        events->overflow = true;
        return;
    }
    events->rec[events->count] = *e;
    events->count += 1u;
}

void dfi_event_project(const duoforge_event *in, uint32_t player, duoforge_event *out)
{
    *out = *in;
    /* The side channel of a disguised switch-in (reserved[0] = the shown roster index + 1, decision 0026 section 4) is internal:
     * the projection strips it, and the foe's copy names the disguise (the id). The owner's copy keeps the true roster index. */
    out->reserved[0] = 0u;
    out->reserved[1] = 0u;
    if ((in->kind == DUOFORGE_EVENT_SWITCH || in->kind == DUOFORGE_EVENT_DRAG) && in->reserved[0] != 0u &&
        in->position != DUOFORGE_NO_POSITION && (uint32_t)in->position / 2u != player) {
        out->id = (uint16_t)(in->reserved[0] - 1u); /* wide-operands-reviewed: reserved[0] is set only as roster index + 1 */
    }
    if (in->hp_kind != DUOFORGE_HP_EXACT || in->position == DUOFORGE_NO_POSITION ||
        (uint32_t)in->position / 2u == player) {
        return;
    }
    uint8_t percent = 0u;
    uint8_t flag = 0u;
    dfi_hp_display(in->hp, in->hp_max, &percent, &flag);
    out->hp = percent;
    out->hp_max = 100u;
    out->hp_kind = (uint8_t)DUOFORGE_HP_PERCENT;
    out->hp_flag = flag;
}

void dfi_event_set_hp(duoforge_event *e, const dfi_member *m)
{
    e->hp = m->hp;
    e->hp_max = m->hp_max;
    e->hp_kind = (uint8_t)DUOFORGE_HP_EXACT;
    e->status = m->hp != 0u ? m->status : (uint8_t)DUOFORGE_AILMENT_NONE;
}

duoforge_event dfi_event_switch(const struct duoforge_battle *b, uint32_t flat)
{
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_SWITCH, flat);
    const dfi_active_slot *pos = &b->sides[flat / 2u].positions[flat % 2u];
    e.id = pos->occupant; /* < 6 */
    dfi_event_set_hp(&e, &b->sides[flat / 2u].members[pos->occupant]);
    return e;
}

/* Illusion in the fold (decision 0026 section 4, amended by I2). While a foe's holder is disguised, its position shows the disguise.
 * The fold keeps what the lines cannot give: the disguise row's knowledge before it came in (snapshot bytes 0..6), the holder's status
 * and location as the foe knew them before (snapshot bytes 7..8, while ill_shown != 0), the holder's moves that are not on the
 * disguise's sheet (pending, per holder move slot, attributed at the break), the values shown on the name (override: the HP percent
 * and flag mirror the disguise row's knowledge, the status is the one the lines showed, the flags are active, fainted and item used),
 * and the shown name. The truth of the holder is read from the record only where the public event carries it (SWITCH and DRAG, the
 * break). */
#define DFI_ILL_OVR_ACTIVE 1u
#define DFI_ILL_OVR_FAINTED 2u
#define DFI_ILL_OVR_ITEM 4u
#define DFI_ILL_LOC_UNDETERMINED 0u
#define DFI_ILL_LOC_BENCH 1u

static void dfi_ill_snapshot_take(const dfi_knowledge *k, uint8_t *snap)
{
    snap[0] = k->hp_percent;
    snap[1] = k->hp_flag;
    snap[2] = k->revealed;
    for (uint32_t j = 0u; j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
        snap[3u + j] = k->moves_used[j];
    }
}

static void dfi_ill_snapshot_restore(dfi_knowledge *k, const uint8_t *snap)
{
    k->hp_percent = snap[0];
    k->hp_flag = snap[1];
    k->revealed = snap[2];
    for (uint32_t j = 0u; j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
        k->moves_used[j] = snap[3u + j];
    }
}

/* The override follows the disguise row after every applied event of the foe: its HP and flag, and the item it used (the knowledge
 * row of the shown name). The status and the flags active and fainted are written by the events themselves. */
static void dfi_ill_sync(dfi_tail_illusion *ill, const dfi_knowledge *k)
{
    const uint32_t item = ((uint32_t)k->revealed & (uint32_t)DFI_REVEALED_ITEM_CONSUMED) != 0u ? DFI_ILL_OVR_ITEM : 0u;
    ill->override[0] = k->hp_percent;
    ill->override[1] = k->hp_flag;
    ill->override[3] = (uint8_t)(((uint32_t)ill->override[3] & ~(uint32_t)DFI_ILL_OVR_ITEM) | item); /* wide-operands-reviewed: < 8 */
}

/* A switch or drag of the foe's position (applied after `first`). `shown` is the projected id (the disguise for a disguised entry),
 * `raw` the record: its id is the truth, reserved[0] the disguise + 1 and status the status the line shows. An unbroken switch-out of
 * a disguised holder keeps the name (override, BENCH) and the holder's row (bytes 7..8); the real disguise member's line ends both. */
static void dfi_fold_illusion_switch(dfi_tail_illusion *ill, dfi_side *viewer, uint32_t shown, const duoforge_event *raw, bool apply,
                                     bool *disg, uint32_t *holder, uint32_t slot)
{
    if (apply && disg[slot]) {
        memset(ill->snapshot, 0, 7u);
        memset(ill->pending, 0, sizeof ill->pending);
        ill->override[3] = (uint8_t)((uint32_t)ill->override[3] & ~(uint32_t)DFI_ILL_OVR_ACTIVE); /* wide-operands-reviewed: < 8 */
    }
    disg[slot] = false;
    if (apply && ill->shown != 0u && (uint32_t)ill->shown - 1u == shown) {
        memset(ill, 0, sizeof *ill); /* a line about the real disguise member: its own values replace the override */
    }
    holder[slot] = raw->id;
    if (raw->reserved[0] != 0u) {
        disg[slot] = true;
        if (apply) {
            const uint32_t disguise = (uint32_t)raw->reserved[0] - 1u;
            const bool holder_seen = ((uint32_t)viewer->seen_mask >> raw->id & 1u) != 0u;
            ill->shown = raw->reserved[0];
            dfi_ill_snapshot_take(&viewer->knowledge[disguise], ill->snapshot);
            ill->snapshot[7] = raw->status;
            ill->snapshot[8] = (uint8_t)(holder_seen ? DFI_ILL_LOC_BENCH : DFI_ILL_LOC_UNDETERMINED); /* wide-operands-reviewed: < 2 */
            memset(ill->pending, 0, sizeof ill->pending);
            ill->override[2] = raw->status;
            ill->override[3] = (uint8_t)DFI_ILL_OVR_ACTIVE; /* wide-operands-reviewed: < 8 */
        }
    }
}

/* A move of a disguised holder that is not on the disguise's sheet: one use of the holder's move slot, pending until the break. */
static void dfi_fold_illusion_pending(dfi_tail_illusion *ill, const dfi_side *fs, uint32_t holder, uint32_t move_id)
{
    if (holder >= DUOFORGE_MAX_ROSTER || holder >= fs->member_count) {
        return;
    }
    for (uint32_t j = 0u; j < fs->members[holder].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
        if (fs->members[holder].moves[j].move_id == move_id && ill->pending[j] < UINT8_MAX) {
            ill->pending[j] = (uint8_t)((uint32_t)ill->pending[j] + 1u); /* wide-operands-reviewed */
        }
    }
}

/* The break (`replace` and `-end Illusion`, one ILLUSION_END event): the holder's row takes the last shown HP and status, the item
 * it used up while disguised and its move uses (the pending ones, and the disguise row's uses above the snapshot, mapped by move id),
 * the disguise's row goes back to its snapshot, and the foe's occupant is the true holder. Returns false on an inconsistent break. */
static bool dfi_fold_illusion_break(dfi_tail_illusion *ill, dfi_side *viewer, const dfi_side *fs, uint32_t slot, const duoforge_event *e,
                                    uint32_t *occupant, bool *disg, uint32_t *holder)
{
    const uint32_t truth = e->id;
    if (!disg[slot] || ill->shown == 0u || truth >= DUOFORGE_MAX_ROSTER || truth >= fs->member_count) {
        return false;
    }
    const uint32_t disguise = (uint32_t)ill->shown - 1u;
    if (disguise >= DUOFORGE_MAX_ROSTER || disguise >= fs->member_count) {
        return false;
    }
    dfi_knowledge *h = &viewer->knowledge[truth];
    dfi_knowledge *d = &viewer->knowledge[disguise];
    const uint32_t newly = (uint32_t)d->revealed & ~(uint32_t)ill->snapshot[2] & (uint32_t)DFI_REVEALED_ITEM_CONSUMED;
    h->hp_percent = (uint8_t)e->hp; /* the percent display: <= 100 */
    h->hp_flag = e->hp_flag;
    h->revealed = (uint8_t)((uint32_t)h->revealed | newly); /* wide-operands-reviewed */
    for (uint32_t j = 0u; j < fs->members[truth].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
        const uint32_t sum = (uint32_t)h->moves_used[j] + (uint32_t)ill->pending[j];
        h->moves_used[j] = (uint8_t)(sum > UINT8_MAX ? UINT8_MAX : sum); /* wide-operands-reviewed: clamped to UINT8_MAX */
    }
    for (uint32_t k = 0u; k < fs->members[disguise].move_count && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        const uint32_t old = ill->snapshot[3u + k];
        if (d->moves_used[k] <= old) {
            continue;
        }
        const uint32_t delta = (uint32_t)d->moves_used[k] - old;
        for (uint32_t j = 0u; j < fs->members[truth].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
            if (fs->members[truth].moves[j].move_id == fs->members[disguise].moves[k].move_id) {
                const uint32_t sum = (uint32_t)h->moves_used[j] + delta;
                h->moves_used[j] = (uint8_t)(sum > UINT8_MAX ? UINT8_MAX : sum); /* wide-operands-reviewed: clamped to UINT8_MAX */
                break;
            }
        }
    }
    dfi_ill_snapshot_restore(d, ill->snapshot);
    viewer->seen_mask = (uint8_t)((uint32_t)viewer->seen_mask | 1u << truth); /* wide-operands-reviewed: < 64 */
    *occupant = truth;
    holder[slot] = truth;
    disg[slot] = false;
    memset(ill, 0, sizeof *ill);
    return true;
}

/* For every event about an opposing position, in order: a switch makes the
 * member seen and shows its HP, damage and heal show the HP, a move other
 * than a locked turn is one use of the slot that holds it on the open team
 * sheet (Struggle is on none), an item that ended and a Mega Evolution are
 * revealed facts. The occupants follow the switches of the step. */
bool dfi_events_fold_knowledge(const struct duoforge_battle *before, struct duoforge_battle *after,
                               const dfi_events *events, uint32_t first)
{
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        const uint32_t foe = 1u - p;
        const dfi_side *fs = &after->sides[foe];
        dfi_side *viewer = &after->sides[p];
        uint32_t occupant[DUOFORGE_ACTIVE_PER_SIDE];
        bool disg[DUOFORGE_ACTIVE_PER_SIDE];   /* Illusion: the position shows a disguise (decision 0026) */
        uint32_t holder[DUOFORGE_ACTIVE_PER_SIDE]; /* the true holder of the position (the record's truth) */
        dfi_tail_illusion *ill = &after->tail.sides[foe].illusion;
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            occupant[slot] = before->sides[foe].positions[slot].occupant;
            holder[slot] = occupant[slot];
            disg[slot] = before->tail.sides[foe].positions[slot].ability_state != 0u;
            if (disg[slot] && after->tail.sides[foe].illusion.shown != 0u) {
                occupant[slot] = (uint32_t)after->tail.sides[foe].illusion.shown - 1u; /* the name the foe sees */
            }
        }
        for (uint32_t i = 0u; i < events->count && i < DUOFORGE_MAX_EVENTS; ++i) {
            duoforge_event e;
            dfi_event_project(&events->rec[i], p, &e);
            /* An item that a move gave (ITEM_START, step G29): the Pokemon it came from ([of], in `other`; Covet prints no
             * line of its own for it) has lost its item. */
            if (i >= first && e.kind == DUOFORGE_EVENT_ITEM_START &&
                e.other < 2u * DUOFORGE_ACTIVE_PER_SIDE && (uint32_t)e.other / 2u == foe) {
                const uint32_t from = occupant[(uint32_t)e.other % 2u];
                if (from < DUOFORGE_MAX_ROSTER && from < fs->member_count) {
                    viewer->knowledge[from].revealed =
                        (uint8_t)((uint32_t)viewer->knowledge[from].revealed | DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
                }
            }
            if (e.position >= 2u * DUOFORGE_ACTIVE_PER_SIDE || (uint32_t)e.position / 2u != foe) {
                continue;
            }
            const uint32_t slot = (uint32_t)e.position % 2u;
            /* Illusion (decision 0026): the break is one event; it restores the disguise's row and makes the holder the occupant */
            if (e.kind == DUOFORGE_EVENT_ILLUSION_END) {
                if (i >= first && !dfi_fold_illusion_break(ill, viewer, fs, slot, &e, &occupant[slot], disg, holder)) {
                    return false;
                }
                continue;
            }
            /* a drag (step G46) enters a member as a switch does: the opponent sees it, and its occupant */
            if (e.kind == DUOFORGE_EVENT_SWITCH || e.kind == DUOFORGE_EVENT_DRAG) {
                dfi_fold_illusion_switch(ill, viewer, e.id, &events->rec[i], i >= first, disg, holder, slot);
                occupant[slot] = e.id;
            }
            const uint32_t m = occupant[slot];
            if (i < first || m >= DUOFORGE_MAX_ROSTER || m >= fs->member_count) {
                continue;
            }
            dfi_knowledge *k = &viewer->knowledge[m];
            if (e.kind == DUOFORGE_EVENT_SWITCH || e.kind == DUOFORGE_EVENT_DRAG) {
                viewer->seen_mask = (uint8_t)((uint32_t)viewer->seen_mask | 1u << m); /* wide-operands-reviewed: < 64 */
            }
            if (e.kind == DUOFORGE_EVENT_SWITCH || e.kind == DUOFORGE_EVENT_DRAG || e.kind == DUOFORGE_EVENT_DAMAGE ||
                e.kind == DUOFORGE_EVENT_HEAL) {
                if (e.hp_kind != DUOFORGE_HP_PERCENT) {
                    return false; /* never a silent 0 */
                }
                k->hp_percent = (uint8_t)e.hp; /* the percent display: <= 100 */
                k->hp_flag = e.hp_flag;
            } else if (e.kind == DUOFORGE_EVENT_MOVE && ((uint32_t)e.flags & DUOFORGE_EVENT_FLAG_LOCKED) == 0u) {
                bool on_sheet = false;
                for (uint32_t j = 0u; j < fs->members[m].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
                    if (fs->members[m].moves[j].move_id == e.id) {
                        on_sheet = true;
                    }
                    if (fs->members[m].moves[j].move_id == e.id && k->moves_used[j] < UINT8_MAX) {
                        k->moves_used[j] = (uint8_t)((uint32_t)k->moves_used[j] + 1u); /* wide-operands-reviewed */
                    }
                }
                /* Illusion: a move that is not on the disguise's sheet is the holder's: pending until the break (decision 0026) */
                if (!on_sheet && disg[slot]) {
                    dfi_fold_illusion_pending(&after->tail.sides[foe].illusion, fs, holder[slot], e.id);
                }
            } else if (e.kind == DUOFORGE_EVENT_ITEM_END) {
                /* An item that is gone: used up, or taken by a move (Knock Off, ITEM_TAKEN). The old item_used says it
                 * is gone either way, as the reference's state does; the view's item_now tells the two apart. */
                k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
            } else if (e.kind == DUOFORGE_EVENT_FAINT) {
                /* A faint that no damage line announced (Perish Song's, step G26): the screen shows the foe at 0. */
                dfi_hp_display(0u, fs->members[m].hp_max, &k->hp_percent, &k->hp_flag);
                /* Illusion: a faint of a disguised position is no break (the engine drops the disguise): no break will be shown, so
                 * the snapshot and the pending counts go (decision 0026 section 4). The shown name keeps the fainted values. */
                if (disg[slot]) {
                    disg[slot] = false;
                    memset(ill->snapshot, 0, 7u);
                    memset(ill->pending, 0, sizeof ill->pending);
                    ill->override[2] = DUOFORGE_AILMENT_NONE;
                    ill->override[3] = (uint8_t)(((uint32_t)ill->override[3] & ~(uint32_t)DFI_ILL_OVR_ACTIVE) | DFI_ILL_OVR_FAINTED); /* wide-operands-reviewed: < 8 */
                }
            } else if (e.kind == DUOFORGE_EVENT_STATUS) {
                if (disg[slot]) {
                    ill->override[2] = (uint8_t)e.detail; /* the status the line names: the holder's, shown on the name */
                }
            } else if (e.kind == DUOFORGE_EVENT_CURE_STATUS) {
                if (disg[slot]) {
                    ill->override[2] = DUOFORGE_AILMENT_NONE;
                }
            } else if (e.kind == DUOFORGE_EVENT_ITEM_START) {
                /* The Pokemon now holds the item that a move gave it (step G29): the old item_used is no longer "gone". */
                k->revealed = (uint8_t)((uint32_t)k->revealed & ~(uint32_t)DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
            } else if (e.kind == DUOFORGE_EVENT_MEGA) {
                k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_MEGA); /* wide-operands-reviewed */
            }
            if (ill->shown != 0u && (uint32_t)ill->shown - 1u < DUOFORGE_MAX_ROSTER) {
                dfi_ill_sync(ill, &viewer->knowledge[(uint32_t)ill->shown - 1u]);
            }
        }
    }
    return true;
}
