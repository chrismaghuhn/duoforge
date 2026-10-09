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
        for (uint32_t slot = 0u; slot < DUOFORGE_ACTIVE_PER_SIDE; ++slot) {
            occupant[slot] = before->sides[foe].positions[slot].occupant;
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
            } else if (e.kind == DUOFORGE_EVENT_MOVE && ((uint32_t)e.flags & DUOFORGE_EVENT_FLAG_LOCKED) == 0u) {
                for (uint32_t j = 0u; j < fs->members[m].move_count && j < DUOFORGE_MAX_MOVE_SLOTS; ++j) {
                    if (fs->members[m].moves[j].move_id == e.id && k->moves_used[j] < UINT8_MAX) {
                        k->moves_used[j] = (uint8_t)((uint32_t)k->moves_used[j] + 1u); /* wide-operands-reviewed */
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
