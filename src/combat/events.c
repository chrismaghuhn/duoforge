/*
 * Event records of a step (docs/decisions/0007 section 6). The engine
 * records each event once with exact values; each player receives a
 * projection in which the opponent's HP is shown as the percent display,
 * as on that player's screen.
 */
#include "combat/events.h"

#include <stddef.h>
#include <string.h>

#include "data/pool_tables.h"
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

/* The Pressure timeline of a viewer's own side (step G53). The viewer knows all of it: its own Pokemon show their exact HP
 * in the events, and the abilities are on its own sheet and in the lines that announce a change (Pressure's switch-in
 * line, Trace's copy, a Mega Evolution). From `before` and the events of the step, in order, it gives the Pressure holders
 * that stand at every move of a foe, which is what the foe's extra PP of that move is (dfi_pressure_charge). */
typedef struct dfi_own_pressure {
    uint32_t side;
    uint32_t occupant[DUOFORGE_ACTIVE_PER_SIDE]; /* roster index, DUOFORGE_MAX_ROSTER when empty */
    bool alive[DUOFORGE_MAX_ROSTER];
    bool pressure[DUOFORGE_MAX_ROSTER]; /* the member's ability now is Pressure */
} dfi_own_pressure;

static void dfi_own_init(dfi_own_pressure *o, const struct duoforge_battle *before, uint32_t side)
{
    o->side = side;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t occ = before->sides[side].positions[slot].occupant;
        o->occupant[slot] = occ < DUOFORGE_MAX_ROSTER ? occ : DUOFORGE_MAX_ROSTER;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        /* the ability now: the POOL tail's copy (Trace) or the sheet's, as dfi_ability_code reads it */
        const uint32_t now = before->tail.sides[side].ability_now[m];
        const uint32_t code = now != 0u ? now : before->sides[side].members[m].ability;
        o->alive[m] = before->sides[side].members[m].hp != 0u;
        o->pressure[m] = code == 1u + DFI_ABILITY_PRESSURE;
    }
}

/* One event of the viewer's own side moves the timeline (position is the viewer's own position). */
static void dfi_own_event(dfi_own_pressure *o, const struct duoforge_battle *after, const duoforge_event *e)
{
    const uint32_t slot = (uint32_t)e->position % 2u;
    const uint32_t m = o->occupant[slot];
    switch (e->kind) {
    case DUOFORGE_EVENT_SWITCH:
        /* a member that enters has its sheet's ability (the copy of Trace is cleared when it leaves) */
        if (e->id < DUOFORGE_MAX_ROSTER) {
            o->occupant[slot] = e->id;
            o->alive[e->id] = e->hp != 0u;
            o->pressure[e->id] = after->sides[o->side].members[e->id].ability == 1u + DFI_ABILITY_PRESSURE;
        }
        break;
    case DUOFORGE_EVENT_DAMAGE:
    case DUOFORGE_EVENT_HEAL:
        if (m < DUOFORGE_MAX_ROSTER && e->hp_kind == DUOFORGE_HP_EXACT) {
            o->alive[m] = e->hp != 0u;
        }
        break;
    case DUOFORGE_EVENT_FAINT:
        if (m < DUOFORGE_MAX_ROSTER) {
            o->alive[m] = false;
        }
        break;
    case DUOFORGE_EVENT_ABILITY:
        /* Trace's copy: cause ABILITY with the foe as `other` (public doc of the event kind); other ability lines name the
         * holder's ability already, so they change nothing here */
        if (m < DUOFORGE_MAX_ROSTER && e->cause == DUOFORGE_CAUSE_ABILITY && e->other != DUOFORGE_NO_POSITION) {
            o->pressure[m] = e->id2 == 1u + DFI_ABILITY_PRESSURE;
        }
        break;
    case DUOFORGE_EVENT_MEGA:
        /* a Mega Evolution changes the sheet's ability (the tail's copy is cleared there) */
        if (m < DUOFORGE_MAX_ROSTER) {
            o->pressure[m] = after->sides[o->side].members[m].ability == 1u + DFI_ABILITY_PRESSURE;
        }
        break;
    default:
        break;
    }
}

/* The extra PP of a foe's move that the viewer counts (step G53): the same rule as dfi_pressure_extra of the turn code,
 * read from the events. `e` is a MOVE of the foe that is not locked. A mustpressure move, a field move and a spread move
 * count every standing Pressure holder of the viewer's side (all of them are targets); a foeSide move none; the holders of
 * the allies' classes none; a single target counts once when it stands with Pressure and the move line names it. The move
 * line names the target after any redirection (retargetLastMove). A line made [still] (attrLastMove, sim/battle.ts:3123-3138)
 * or a two-turn charge names none: the single target is then not attributable, so no extra is counted (the engine's state
 * still deducts it; decision 0030 section 1). */
static uint32_t dfi_pressure_charge(const dfi_own_pressure *o, const duoforge_event *e)
{
    uint32_t standing = 0u;
    for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
        const uint32_t m = o->occupant[slot];
        standing += (m < DUOFORGE_MAX_ROSTER && o->alive[m] && o->pressure[m]) ? 1u : 0u;
    }
    if ((e->flags & DUOFORGE_EVENT_FLAG_STILL) != 0u) {
        return 0u; /* a [still] line blanks the targets: none can be known (the tracker's rule too) */
    }
    if (e->id >= DFI_POOL_MOVE_COUNT) {
        return 0u; /* no move row: a corrupt line (the fold counts its use against no slot either) */
    }
    const uint32_t cls = dfi_pool_moves[e->id].target_class;
    if ((dfi_pool_move_flags3[e->id] & DFI_MOVE_FLAG3_MUST_PRESSURE) != 0u) {
        return standing;
    }
    if (cls == DFI_TARGET_CLASS_FOE_SIDE) {
        return 0u;
    }
    if (cls == DUOFORGE_TARGET_CLASS_ALL || cls == DUOFORGE_TARGET_CLASS_ALL_ADJACENT_FOES || cls == DFI_TARGET_CLASS_ALL_ADJACENT) {
        return standing;
    }
    if ((e->flags & DUOFORGE_EVENT_FLAG_SPREAD) != 0u) {
        return (cls == DFI_TARGET_CLASS_ALLIES || cls == DFI_TARGET_CLASS_ALLY_TEAM) ? 0u : standing;
    }
    if (e->other >= 2u * DUOFORGE_ACTIVE_PER_SIDE || (uint32_t)e->other / 2u != o->side) {
        return 0u;
    }
    const uint32_t m = o->occupant[(uint32_t)e->other % 2u];
    return (m < DUOFORGE_MAX_ROSTER && o->alive[m] && o->pressure[m]) ? 1u : 0u;
}

/* For every event about an opposing position, in order: a switch makes the
 * member seen and shows its HP, damage and heal show the HP, a move other
 * than a locked turn is one use of the slot that holds it on the open team
 * sheet (Struggle is on none), an item that ended and a Mega Evolution are
 * revealed facts. The occupants follow the switches of the step. A move
 * costs the foe one PP more for every standing Pressure holder of the viewer
 * that it targets (step G53, dfi_pressure_charge), so the use counts 1 plus
 * that extra. */
bool dfi_events_fold_knowledge(const struct duoforge_battle *before, struct duoforge_battle *after,
                               const dfi_events *events, uint32_t first)
{
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        const uint32_t foe = 1u - p;
        const dfi_side *fs = &after->sides[foe];
        dfi_side *viewer = &after->sides[p];
        uint32_t occupant[DUOFORGE_ACTIVE_PER_SIDE];
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            occupant[slot] = before->sides[foe].positions[slot].occupant;
        }
        dfi_own_pressure own;
        dfi_own_init(&own, before, p);
        for (uint32_t i = 0u; i < events->count && i < DUOFORGE_MAX_EVENTS; ++i) {
            duoforge_event e;
            dfi_event_project(&events->rec[i], p, &e);
            if (e.position < 2u * DUOFORGE_ACTIVE_PER_SIDE && (uint32_t)e.position / 2u == p) {
                dfi_own_event(&own, after, &e); /* the viewer's own side: every event of it, before and after `first` */
            }
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
            /* Revival Blessing (decision 0025 item 9): the revived member is named by its roster index in `id`, not by a
             * position. On the foe's side its line is a percentage (the projection above), which is the member's HP display;
             * on the viewer's own side it tells the viewer nothing new. */
            if (e.kind == DUOFORGE_EVENT_REVIVE) {
                if (i >= first && e.position < 2u * DUOFORGE_ACTIVE_PER_SIDE && (uint32_t)e.position / 2u == foe &&
                    e.id < DUOFORGE_MAX_ROSTER && e.id < fs->member_count) {
                    if (e.hp_kind != DUOFORGE_HP_PERCENT) {
                        return false; /* never a silent 0 */
                    }
                    viewer->knowledge[e.id].hp_percent = (uint8_t)e.hp; /* the percent display: <= 100 */
                    viewer->knowledge[e.id].hp_flag = e.hp_flag;
                }
                continue;
            }
            if (e.position >= 2u * DUOFORGE_ACTIVE_PER_SIDE || (uint32_t)e.position / 2u != foe) {
                continue;
            }
            const uint32_t slot = (uint32_t)e.position % 2u;
            /* a drag (step G46) enters a member as a switch does: the opponent sees it, and its occupant */
            if (e.kind == DUOFORGE_EVENT_SWITCH || e.kind == DUOFORGE_EVENT_DRAG) {
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
            } else if (e.kind == DUOFORGE_EVENT_MOVE && ((uint32_t)e.flags & DUOFORGE_EVENT_FLAG_LOCKED) == 0u &&
                       e.cause != DUOFORGE_CAUSE_ABILITY) {
                /* A bounced move (Magic Bounce, cause ABILITY, step G57) uses no PP: the pin's useMove deducts none. */
                /* one use costs its PP and the Pressure extra of the targets that stand with Pressure (step G53) */
                const uint32_t use = 1u + dfi_pressure_charge(&own, &e);
                for (uint32_t j = 0u; j < fs->members[m].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
                    if (fs->members[m].moves[j].move_id == e.id && k->moves_used[j] < UINT8_MAX) {
                        const uint32_t used = (uint32_t)k->moves_used[j];
                        k->moves_used[j] = (uint8_t)(used + use > UINT8_MAX ? UINT8_MAX : used + use); /* wide-operands-reviewed */
                    }
                }
            } else if (e.kind == DUOFORGE_EVENT_ITEM_END) {
                /* An item that is gone: used up, or taken by a move (Knock Off, ITEM_TAKEN). The old item_used says it
                 * is gone either way, as the reference's state does; the view's item_now tells the two apart. */
                k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
            } else if (e.kind == DUOFORGE_EVENT_FAINT) {
                /* A faint that no damage line announced (Perish Song's, step G26): the screen shows the foe at 0. */
                dfi_hp_display(0u, fs->members[m].hp_max, &k->hp_percent, &k->hp_flag);
            } else if (e.kind == DUOFORGE_EVENT_ITEM_START) {
                /* The Pokemon now holds the item that a move gave it (step G29): the old item_used is no longer "gone". */
                k->revealed = (uint8_t)((uint32_t)k->revealed & ~(uint32_t)DFI_REVEALED_ITEM_CONSUMED); /* wide-operands-reviewed */
            } else if (e.kind == DUOFORGE_EVENT_MEGA) {
                k->revealed = (uint8_t)((uint32_t)k->revealed | DFI_REVEALED_MEGA); /* wide-operands-reviewed */
            }
        }
    }
    return true;
}
