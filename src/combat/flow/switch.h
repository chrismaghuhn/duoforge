#ifndef DUOFORGE_COMBAT_FLOW_SWITCH_H
#define DUOFORGE_COMBAT_FLOW_SWITCH_H

/* Private flow implementation (restructure step 4, flow): move and switch actions: running a move action, switching,
 * Revival Blessing, Baton Pass, Illusion. Split from src/combat/turn.c@c02189e7; included by turn.c where the code
 * stood, so its dependencies and the turn order are unchanged. */
#include "combat/run_internal.h"

/* ---------------------------------------------------------------- switches */

/* insertChoice (sim/battle-queue.ts:369-401) of the entry action of the
 * Pokemon that came in: before the first action it sorts ahead of or ties
 * with. Among tied entries the reference draws a position; the engine does
 * not, because entries queued together run as one batch, ordered by Speed
 * in dfi_run_entries (decision 0006 section 5.1, converter rule INSERT_TIE). */
/* One move action: the body, then the result the action leaves in the user's position (step G42, tail rev 4's move_result,
 * decision 0015 section 7). Only the POOL kinds carry the tail. An action that did not run (an inactive actor) writes nothing. */
static duoforge_status dfi_run_move(dfi_run *r, const dfi_queue_record *q, bool *ran)
{
    r->mres = 0u;
    const duoforge_status st = dfi_run_move_body(r, q, ran);
    if (st != DUOFORGE_OK || !*ran || !dfi_kind_limits_of(r->ctx->data_kind).pool_rules) {
        return st;
    }
    uint32_t value = DFI_MOVE_RESULT_UNDEFINED;
    bool unclassified = true;
    if ((r->mres & DFI_MRES_UNCLASS) == 0u) {
        if ((r->mres & DFI_MRES_TRUE) != 0u) {
            value = DFI_MOVE_RESULT_TRUE;
            unclassified = false;
        } else if ((r->mres & DFI_MRES_FALSE) != 0u) {
            value = DFI_MOVE_RESULT_FALSE;
            unclassified = false;
        } else if ((r->mres & DFI_MRES_NULL) != 0u) {
            value = DFI_MOVE_RESULT_NULL;
            unclassified = false;
        }
    }
    /* The user may have moved during its own move (Ally Switch: the popped record is a copy the swap does not remap). The
     * activation id belongs to the Pokemon, so the slot that now holds it is the one the result is written to. */
    uint32_t slot = q->slot;
    if (q->activation_id != 0u) {
        for (uint32_t s = 0u; s < 2u; ++s) {
            const dfi_active_slot *now = dfi_pos(r->b, (uint32_t)q->side * 2u + s);
            if (now->occupant != DFI_OCCUPANT_NONE && now->activation_id == q->activation_id) {
                slot = s;
            }
        }
    }
    dfi_tail_pos *tp = &r->b->tail.sides[q->side].positions[slot];
    /* This turn's bits (0-1) and the unclassified-now bit (4) are the action's; the last turn's bits stay. */
    const uint32_t kept = (uint32_t)tp->move_result & ~0x13u;
    tp->move_result = (uint8_t)(kept | value | (unclassified ? DFI_MOVE_RESULT_UNCLASSIFIED_NOW : 0u)); /* wide-operands-reviewed: <= 0x3F */
    return DUOFORGE_OK;
}

static duoforge_status dfi_insert_run_switch(dfi_run *r, uint32_t side, uint32_t slot, uint32_t activation)
{
    struct duoforge_battle *b = r->b;
    if (b->queue_len >= DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_INVARIANT;
    }
    const dfi_queue_record rec = {activation, (uint8_t)DFI_Q_RUN_SWITCH, (uint8_t)side, (uint8_t)slot, 0u, 0u, 0u};
    dfi_key key;
    duoforge_status st = dfi_update_position_speed(r, side * 2u + slot);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = dfi_key_of(r, &rec, &key);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t n = b->queue_len;
    uint32_t index = n;
    for (uint32_t i = 0u; i < n; ++i) {
        dfi_key other;
        st = dfi_key_of(r, &b->queue[i], &other);
        if (st != DUOFORGE_OK) {
            return st;
        }
        if (dfi_compare(&key, &other) != 2u) {
            index = i; /* the first action it sorts ahead of or ties with */
            break;
        }
    }
    for (uint32_t i = n; i > index; --i) {
        b->queue[i] = b->queue[i - 1u];
    }
    b->queue[index] = rec;
    b->queue_len = (uint8_t)(n + 1u); /* wide-operands-reviewed: <= 12 */
    return DUOFORGE_OK;
}

/* cancelAction (sim/battle-queue.ts:334-343): the queued actions of one
 * activation are removed; the rest keeps its order. */
static void dfi_cancel_actions(struct duoforge_battle *b, uint32_t activation_id)
{
    const uint32_t len = b->queue_len;
    uint32_t n = 0u;
    for (uint32_t i = 0u; i < len && i < DFI_QUEUE_CAPACITY; ++i) {
        if (activation_id == 0u || b->queue[i].activation_id != activation_id) {
            b->queue[n] = b->queue[i];
            n += 1u;
        }
    }
    for (uint32_t i = n; i < len && i < DFI_QUEUE_CAPACITY; ++i) {
        b->queue[i] = (dfi_queue_record){0u, 0u, 0u, 0u, 0u, 0u, 0u};
    }
    b->queue_len = (uint8_t)n; /* <= len */
}

/* party_order (step G46, sim/battle-actions.ts:119-133): the incoming member takes the outgoing one's entry of side.pokemon and
 * the outgoing one takes the incoming's old entry, a fainted outgoing too. A slot with no occupant changes nothing (the pin's
 * `if (oldActive)`: only the start, where the leads come in through team selection). POOL kinds only: the tail is zero
 * under the other kinds. */
static void dfi_party_switch(dfi_run *r, uint32_t side, uint32_t slot, uint32_t incoming)
{
    struct duoforge_battle *b = r->b;
    if (!dfi_kind_limits_of(r->ctx->data_kind).pool_rules || b->sides[side].positions[slot].occupant == DFI_OCCUPANT_NONE) {
        return;
    }
    uint32_t j = DUOFORGE_MAX_ROSTER;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        if (dfi_party_entry(&b->tail, side, k) == incoming + 1u) {
            j = k;
        }
    }
    if (j >= DUOFORGE_MAX_ROSTER) {
        return; /* a brought member is always in the order (invariant TAIL_PARTY); nothing to do otherwise */
    }
    const uint32_t outgoing = dfi_party_entry(&b->tail, side, slot);
    dfi_party_put(&b->tail, side, slot, incoming + 1u);
    dfi_party_put(&b->tail, side, j, outgoing);
}

/* switchIn (sim/battle-actions.ts:57-149): the Pokemon in the slot leaves
 * (its position is cleared; a fainted one simply makes room), the reserve
 * comes in with a fresh activation and is seen by the opponent, and its
 * entry is queued. */
/* Revival Blessing's revive (decision 0025 items 6 and 9; sim/battle.ts 2781-2797): the member loses its fainted and
 * status, its HP is sethp(maxhp / 2), i.e. floor(maxhp / 2), then the -heal line: the REVIVE event with the member's
 * exact HP (the foe's copy is a percentage, as for every heal). A member that still stands in a position (it fainted there
 * and was never replaced) is queued for an instaswitch, appended to the queue as addChoice does. */
static duoforge_status dfi_run_revive(dfi_run *r, const dfi_queue_record *q)
{
    struct duoforge_battle *b = r->b;
    const uint32_t side = q->side;
    const uint32_t reserve = q->reserve;
    dfi_side *sd = &b->sides[side];
    if (reserve >= sd->member_count || ((uint32_t)sd->brought_mask >> reserve & 1u) == 0u ||
        sd->members[reserve].hp != 0u) {
        return DUOFORGE_E_INVARIANT; /* the request offers only brought fainted members */
    }
    dfi_member *m = &sd->members[reserve];
    m->status = DUOFORGE_AILMENT_NONE;
    b->tail.sides[side].sleep_cant[reserve] = 0u; /* decision 0066: the revival cures the sleep and its count */
    m->hp = (uint16_t)(m->hp_max / 2u); /* sethp(maxhp / 2): trunc, and maxhp is at least 2; wide-operands-reviewed: < 256 */
    duoforge_event e = dfi_event_make(DUOFORGE_EVENT_REVIVE, side * 2u + (uint32_t)q->slot);
    e.id = (uint16_t)reserve; /* wide-operands-reviewed: a roster index */
    dfi_event_set_hp(&e, m);
    e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
    e.id2 = (uint16_t)DFI_MOVE_REVIVALBLESSING; /* wide-operands-reviewed: a move id of the pool tables, a u16 */
    dfi_emit(r, &e);
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (sd->positions[p].occupant == reserve) {
            if (b->queue_len >= DFI_QUEUE_CAPACITY) {
                return DUOFORGE_E_INVARIANT;
            }
            b->queue[b->queue_len] = (dfi_queue_record){0u, (uint8_t)DFI_Q_INSTASWITCH, (uint8_t)side, (uint8_t)p, 0u, 0u,
                                                        (uint8_t)reserve};
            b->queue_len = (uint8_t)((uint32_t)b->queue_len + 1u); /* wide-operands-reviewed: <= 12 */
        }
    }
    return DUOFORGE_OK;
}

/* The switch of a reserve in: the outgoing Pokemon leaves and the reserve is placed (sim/battle-actions.ts switchIn). A drag
 * (step G46, `drag`) skips BeforeSwitchOut and its Update (sim/battle-actions.ts:80-85), takes no pivot or Parting Shot
 * cause, and its line is [drag] (DUOFORGE_EVENT_DRAG). The entry (runSwitch) is queued, or, for a drag, run at once by the
 * caller. `*activation` is the reserve's activation id. */
/* Baton Pass (decision 0042; sim/pokemon.ts copyVolatileFrom, the noCopy set left out). The leaver's volatiles that the pin
 * copies are taken before its position is cleared and given to the entering member after it: the stages, the confusion and
 * stall counters, Helping Hand and Follow Me, the Substitute's HP (hidden: no event, no view, no encoder carries it), the
 * bars and counters, the leech seed, the charge-type flags, the partial trap and the Dragon Cheer stage.
 * Not copied, because their condition is noCopy in the pin (data/moves.ts: Yawn 21147, Imprison 9500, Stockpile 17974,
 * Glaive Rush 6660): Yawn, Imprison, Stockpile and Glaive Rush stay with the leaver. A Yawn copied to the entering member
 * put it to sleep at the end of the turn (a SLEEP_TURNS draw the reference does not make; battle fz_74_236 step 24).
 * Not copied, as the pin's clearVolatile does: the last move, the move results, hits taken, the ability state, the
 * stats-raised bit and the flinch, the choice lock and the Flash Fire flag. */
typedef struct dfi_pass_copy {
    uint8_t stages[DFI_STAT_STAGE_COUNT];
    uint8_t confusion_turns;
    uint8_t stall_level;
    uint8_t stall_turns;
    uint8_t vol_flags;    /* DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME of the leaver, else 0 */
    dfi_tail_pos tail;    /* the leaver's tail position; dfi_pass_give takes only the copied fields of it */
} dfi_pass_copy;

static void dfi_pass_take(struct duoforge_battle *b, uint32_t flat, dfi_pass_copy *c)
{
    const dfi_active_slot *a = dfi_pos(b, flat);
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        c->stages[i] = a->stages[i];
    }
    c->confusion_turns = a->confusion_turns;
    c->stall_level = a->stall_level;
    c->stall_turns = a->stall_turns;
    c->vol_flags = (uint8_t)((uint32_t)a->flags & (DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME)); /* wide-operands-reviewed: < 256 */
    c->tail = b->tail.sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE];
}

static void dfi_pass_give(struct duoforge_battle *b, uint32_t flat, const dfi_pass_copy *c)
{
    dfi_active_slot *a = dfi_pos(b, flat);
    dfi_tail_pos *t = &b->tail.sides[flat / DUOFORGE_ACTIVE_PER_SIDE].positions[flat % DUOFORGE_ACTIVE_PER_SIDE];
    const dfi_tail_pos *s = &c->tail;
    for (uint32_t i = 0u; i < DFI_STAT_STAGE_COUNT; ++i) {
        a->stages[i] = c->stages[i];
    }
    a->confusion_turns = c->confusion_turns;
    a->stall_level = c->stall_level;
    a->stall_turns = c->stall_turns;
    a->flags = (uint8_t)(((uint32_t)a->flags & ~(uint32_t)(DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME)) | c->vol_flags); /* wide-operands-reviewed: < 256 */
    t->substitute_hp = s->substitute_hp;
    t->taunt_turns = s->taunt_turns;
    t->heal_block_turns = s->heal_block_turns;
    t->perish = s->perish;
    t->throat_chop_turns = s->throat_chop_turns;
    t->leech_seed_source = s->leech_seed_source;
    t->focus_energy = s->focus_energy;
    t->charge = s->charge;
    t->trap_turns = s->trap_turns;
    t->trap_source = s->trap_source;
    t->trap_band = s->trap_band;
    t->trap_elapsed = s->trap_elapsed; /* the partial trap has no noCopy (pin: copyVolatileFrom, pokemon.ts:1251): the count goes too */
    t->trap_move = s->trap_move;
    /* copyVolatileFrom (sim/pokemon.ts:1246-1251): Curse has no noCopy, so the passer's Curse goes to the new occupant (step G84b). */
    t->position_flags = (uint8_t)((uint32_t)s->position_flags & (DFI_POSFLAG_DRAGON_CHEER_MASK | DFI_POSFLAG_CURSED)); /* wide-operands-reviewed: < 256 */
}

/* Illusion (decision 0026 sections 2 and 4; pin data/abilities.ts:2056-2069, onBeforeSwitchIn): the disguise of a holder that
 * enters `slot` is the last non-fainted member to the right of it in side.pokemon, which is the party order (the entries above
 * `slot`, highest first). `word` is the side's party word after the switch (the holder at entry `slot`). The other active may
 * be the disguise only when every bench member to the right has fainted; the caller refuses that case. */
static uint32_t dfi_party_entry_of(uint32_t word, uint32_t k)
{
    return word >> (k * DFI_PARTY_ENTRY_BITS) & DFI_PARTY_ENTRY_MASK;
}

static uint32_t dfi_party_word_put(uint32_t word, uint32_t k, uint32_t value)
{
    word &= ~(DFI_PARTY_ENTRY_MASK << (k * DFI_PARTY_ENTRY_BITS));
    return word | ((value & DFI_PARTY_ENTRY_MASK) << (k * DFI_PARTY_ENTRY_BITS));
}

/* The party word of `side` after dfi_party_switch(slot, incoming), computed without writing it (sim/battle-actions.ts:119-133). */
static uint32_t dfi_party_word_after(const struct duoforge_battle *b, uint32_t side, uint32_t slot, uint32_t incoming, bool pool)
{
    uint32_t w = dfi_party_word(&b->tail, side);
    if (!pool || b->sides[side].positions[slot].occupant == DFI_OCCUPANT_NONE) {
        return w;
    }
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        if (dfi_party_entry_of(w, k) == incoming + 1u) {
            const uint32_t outgoing = dfi_party_entry_of(w, slot);
            w = dfi_party_word_put(w, slot, incoming + 1u);
            return dfi_party_word_put(w, k, outgoing);
        }
    }
    return w;
}

static bool dfi_illusion_disguise(const struct duoforge_battle *b, uint32_t side, uint32_t word, uint32_t slot, uint32_t *roster)
{
    for (uint32_t k = DUOFORGE_MAX_ROSTER; k > slot + 1u; --k) {
        const uint32_t e = dfi_party_entry_of(word, k - 1u);
        if (e != 0u && b->sides[side].members[e - 1u].hp != 0u) {
            *roster = e - 1u;
            return true;
        }
    }
    return false;
}

/* The disguise of the lead that stands in `slot` at team start (decision 0026 section 2; the leads come first in the party order,
 * and no switch has happened yet). False when the holder has no Illusion or no disguise. */
bool dfi_illusion_lead_disguise(const struct duoforge_battle *b, uint32_t side, uint32_t slot, uint32_t *roster)
{
    const uint32_t occupant = b->sides[side].positions[slot].occupant;
    if (occupant >= DUOFORGE_MAX_ROSTER || !dfi_ability(b, &b->sides[side].members[occupant], DFI_ABILITY_ILLUSION)) {
        return false;
    }
    return dfi_illusion_disguise(b, side, dfi_party_word(&b->tail, side), slot, roster);
}

/* Illusion (decision 0026 section 4; issue 619): the name that the foe's fold shows for `side` at this point of the step, + 1 (0 for
 * none), in *out. The fold (src/combat/events.c) writes illusion.shown only at the end of the step, so the tail holds the name as the
 * previous step left it: a name set or ended earlier in this step is read from the step's own SWITCH, DRAG and ILLUSION_END events of
 * the side, in order, as the fold applies them: a disguised entry shows its disguise (reserved[0]), an entry of the shown name's real
 * member ends the name, and the break ends it. A faint keeps it. Without the step's events (no buffer, or one past its bound) the name
 * cannot be known: E_INVARIANT, never the tail's name in their place (every step runs with the staged buffer of request.c). */
static duoforge_status dfi_illusion_shown_now(const dfi_run *r, uint32_t side, uint32_t *out)
{
    const dfi_events *ev = r->events;
    if (ev == NULL || ev->overflow || ev->count > DUOFORGE_MAX_EVENTS) {
        return DUOFORGE_E_INVARIANT;
    }
    uint32_t shown = r->b->tail.sides[side].illusion.shown;
    for (uint32_t i = 0u; i < ev->count; ++i) {
        const duoforge_event *e = &ev->rec[i];
        if (e->position >= 2u * DUOFORGE_ACTIVE_PER_SIDE || (uint32_t)e->position / 2u != side) {
            continue;
        }
        if (e->kind == DUOFORGE_EVENT_ILLUSION_END) {
            shown = 0u;
        } else if (e->kind == DUOFORGE_EVENT_SWITCH || e->kind == DUOFORGE_EVENT_DRAG) {
            if (e->reserved[0] != 0u) {
                shown = e->reserved[0];
            } else if (shown != 0u && shown - 1u == (uint32_t)e->id) {
                shown = 0u;
            }
        }
    }
    *out = shown;
    return DUOFORGE_OK;
}

/* The position `p` of the side shows the name (given that a name is shown): its holder's disguise is up, or the holder stands there
 * fainted under it (dfi_illusion_shown_occupant with the step's name). */
static bool dfi_illusion_shows_name(const dfi_side *sd, const dfi_tail_side *ts, uint32_t p)
{
    const uint32_t occ = sd->positions[p].occupant;
    return occ < DUOFORGE_MAX_ROSTER && occ < sd->member_count &&
           (dfi_illusion_disguise_up(sd, ts, p) ||
            (sd->members[occ].ability == DFI_ABILITY_ILLUSION + 1u && sd->members[occ].hp == 0u));
}

static duoforge_status dfi_switch_in(dfi_run *r, uint32_t side, uint32_t slot, uint32_t reserve, bool drag,
                                     bool insta, uint32_t *activation)
{
    struct duoforge_battle *b = r->b;
    const dfi_position_id where = {(uint8_t)side, (uint8_t)slot};
    const dfi_side *sd = &b->sides[side];
    if (reserve >= sd->member_count || sd->members[reserve].hp == 0u ||
        ((uint32_t)sd->brought_mask >> reserve & 1u) == 0u ||
        (insta ? sd->positions[slot].occupant != reserve
               : sd->positions[0].occupant == reserve || sd->positions[1].occupant == reserve)) {
        return DUOFORGE_E_INVARIANT; /* the domain offers only standing reserves */
    }
    const uint32_t ability = sd->members[reserve].ability;
    const uint32_t item = sd->members[reserve].item;
    if ((ability != 0u && (ability > DFI_POOL_ABILITY_COUNT || dfi_support.abilities[ability - 1u] == 0u)) ||
        (item != 0u && (item > DFI_POOL_ITEM_COUNT || dfi_support.items[item - 1u] == 0u))) {
        return DUOFORGE_E_UNSUPPORTED; /* not marked in the support manifest */
    }
    /* Regenerator on an instaswitch (decision 0025 item 10): the reference's SwitchOut path for the revived holder is not
     * modelled here, so the instaswitch of such a holder is refused explicitly, never played (flagged in the PR). */
    if (insta && dfi_ability(b, &sd->members[reserve], DFI_ABILITY_REGENERATOR)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* an instaswitch has no leaving Pokemon: the member is revived, not switched out (the reference would run its
     * SwitchOut, which Regenerator answers; that is refused below) */
    /* Illusion (decision 0026): the disguise is decided before anything is written, from the party order after the switch.
     * A disguise that would be the other active (every bench member to the right has fainted) shows one roster index in two
     * positions: refused explicitly, before any change. */
    const bool pool_rules = dfi_kind_limits_of(r->ctx->data_kind).pool_rules;
    bool disguised = false;
    uint32_t disguise = 0u;
    if (pool_rules && dfi_ability(b, &sd->members[reserve], DFI_ABILITY_ILLUSION)) {
        const uint32_t word = dfi_party_word_after(b, side, slot, reserve, pool_rules);
        disguised = dfi_illusion_disguise(b, side, word, slot, &disguise);
        if (disguised && disguise == sd->positions[1u - slot].occupant) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    /* The duplicate name (decision 0026 section 4, amended by I2, lead decision A; issue 602): the real member of the disguise that
     * the holder on the other position shows, entering, would put the disguise and its real member on the field together. The
     * holder's disguise is read from its position (ability_state, written at the holder's switch-in or, for a lead, at team start), not from the shown name
     * (illusion.shown, which the fold writes at the end of the step): a replacement of both positions in one step that brings the
     * holder first and its disguise member second is refused here, at the switch-in that makes the duplicate, before any change. */
    if (pool_rules && dfi_illusion_disguise_up(sd, &b->tail.sides[side], 1u - slot) &&
        (uint32_t)b->tail.sides[side].positions[1u - slot].ability_state - 1u == reserve) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* The shown name of the side as the fold has it at this point of the step (issue 619): the checks below read it, not
     * illusion.shown, which holds the name as the previous step's fold left it. A holder that entered disguised earlier in this step
     * and fainted without a hit (its disguise dropped with the faint) keeps that name on its fainted position, and the name's real
     * member dragged in later in the step is refused by the checks below (lead decision B, the faint-held name); a second entry of the
     * holder in one step compares with the name of its first; a name that a break or the name's own member ended earlier in this
     * step no longer refuses anything. */
    uint32_t shown = 0u;
    if (pool_rules) {
        const duoforge_status ss = dfi_illusion_shown_now(r, side, &shown);
        if (ss != DUOFORGE_OK) {
            return ss;
        }
    }
    /* Illusion, one shown name per side (amended by I2, decision 0026 section 3): while a name is still shown on the bench, the
     * holder may enter only disguised as that same name. Any other entry of the holder would need a second name, which the single
     * state cannot hold: refused before any change. */
    /* The shown name's own member entering while the holder stands disguised as it on the other position: two positions would show one
     * name (the fold ends the name on that member's line, and the holder's disguise would outlive it). Refused before any change; the
     * member's entry in its own position (the unbroken switch-out of the holder) is not this case. */
    if (pool_rules && shown != 0u && reserve == shown - 1u) {
        for (uint32_t other = 0u; other < DUOFORGE_ACTIVE_PER_SIDE; ++other) {
            if (other != slot && dfi_illusion_shows_name(sd, &b->tail.sides[side], other)) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    if (pool_rules && shown != 0u && reserve != shown - 1u && dfi_ability(b, &sd->members[reserve], DFI_ABILITY_ILLUSION) &&
        (!disguised || disguise != shown - 1u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    /* A holder fainted under its shown name (decision 0026 section 4, amended by I2, lead decision B): the faint of a disguised holder
     * is shown under the name, and the name stays after the holder has left the field (the replacement of the fainted holder puts
     * another member on its position). The real disguise member (the name's member) entering while that holder stands fainted, on
     * the field or on the bench, would clear the name, and the view would read the holder's true fainted state. Refused before any
     * change (option B, no deduction). */
    if (pool_rules && shown != 0u && reserve == shown - 1u) {
        for (uint32_t m = 0u; m < sd->member_count; ++m) {
            if (m != reserve && sd->members[m].ability == DFI_ABILITY_ILLUSION + 1u && sd->members[m].hp == 0u &&
                ((uint32_t)sd->brought_mask >> m & 1u) != 0u) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    /* An instaswitch (a revived holder, decision 0025) and a disguise together: the revive line has no disguise in the reference,
     * so the combination is refused explicitly, before any change (decision 0026, one composition not modelled). */
    if (insta && disguised) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const dfi_member *leaving = insta ? NULL : dfi_at(b, side * 2u + slot);
    const uint32_t flag = sd->positions[slot].switch_flag;
    const bool parting_shot = leaving != NULL && leaving->hp != 0u && flag == DFI_SWITCH_MOVE && !drag;
    /* A damaging pivot move's flag names the move that pivots. */
    const dfi_pivot_move *pivot = leaving != NULL && leaving->hp != 0u && !drag ? dfi_pivot_of_flag(flag) : NULL;
    if (leaving != NULL && leaving->hp != 0u && sd->positions[slot].switch_flag == 0u && !drag) {
        const duoforge_status us = dfi_update(r); /* BeforeSwitchOut, then Update (sim/battle-actions.ts:80-84) */
        if (us != DUOFORGE_OK) {
            return us;
        }
    }
    /* The SwitchOut event of the Pokemon that leaves (sim/battle-actions.ts:90, after BeforeSwitchOut and its Update, before
     * the abilities' End events and clearVolatile): Regenerator (step G39, data/abilities.ts:3833-3841 with the Champions
     * override, data/mods/champions/abilities.ts:63-70) heals the holder by floor(baseMaxhp / 3), Pokemon.heal: no TryHeal
     * event (Heal Block does not stop it) and nothing at full HP. The Champions line is `-heal|holder|hp|[from] ability:
     * Regenerator|[silent]`: silent only in that no client shows a message, the line is in the protocol with the holder's
     * new HP, so the opponent's display of the member (the knowledge fold of the events) follows it: the HEAL event, cause
     * ABILITY Regenerator, before the SWITCH event (the converter keeps this one [silent] line, trace_to_c.py). */
    if (leaving != NULL && leaving->hp != 0u && dfi_ability(b, leaving, DFI_ABILITY_REGENERATOR)) {
        dfi_member *lm = dfi_at(b, side * 2u + slot);
        if (lm->hp < lm->hp_max) {
            const uint32_t healed = (uint32_t)lm->hp_max / 3u;
            const uint32_t hp = (uint32_t)lm->hp + (healed == 0u ? 1u : healed);
            lm->hp = (uint16_t)(hp > lm->hp_max ? lm->hp_max : hp); /* wide-operands-reviewed: <= hp_max */
            dfi_emit_hp(r, dfi_ev(DUOFORGE_EVENT_HEAL, side * 2u + slot, DUOFORGE_CAUSE_ABILITY, 1u + DFI_ABILITY_REGENERATOR,
                                  DUOFORGE_NO_POSITION));
        }
    }
    if (leaving != NULL && leaving->hp != 0u) {
        /* cancelAction (sim/battle-actions.ts:107): a Pokemon that leaves
         * standing loses its queued actions. */
        dfi_cancel_actions(b, sd->positions[slot].activation_id);
    }
    dfi_party_switch(r, side, slot, reserve); /* step G46: side.pokemon order, sim/battle-actions.ts:119-133 */
    /* Baton Pass (decision 0042): the leaver's copied volatiles are taken before its position is cleared (copyVolatileFrom
     * runs before clearVolatile, sim/battle-actions.ts:114-117) and given to the entering member below. */
    const uint32_t pass_flat = side * DUOFORGE_ACTIVE_PER_SIDE + slot;
    const bool passing = leaving != NULL && leaving->hp != 0u && flag == DFI_SWITCH_BATON_PASS && !drag;
    dfi_pass_copy pass;
    if (passing) {
        dfi_pass_take(b, pass_flat, &pass);
    }
    if (sd->positions[slot].occupant != DFI_OCCUPANT_NONE) {
        const duoforge_status vs = dfi_vacate(b, where);
        if (vs != DUOFORGE_OK) {
            return vs;
        }
    }
    dfi_binding binding = {{0u, 0u}, 0u};
    const duoforge_status ps = dfi_place(b, where, (uint8_t)reserve, &binding);
    if (ps != DUOFORGE_OK) {
        return ps;
    }
    if (passing) {
        dfi_pass_give(b, pass_flat, &pass); /* the entering member takes the copy (decision 0042) */
    }
    if (disguised) {
        /* the disguise: its roster index + 1 (tail rev 4, ability_state, cleared with the occupant or by the break) */
        b->tail.sides[side].positions[slot].ability_state = (uint8_t)(disguise + 1u); /* wide-operands-reviewed: roster index + 1, at most 6 */
    }
    /* newlySwitched until the end of the turn (Team C: only Helping Hand
     * reads it). */
    dfi_active_slot *entered = dfi_pos(b, side * 2u + slot);
    const uint32_t newly = dfi_kind_limits_of(r->ctx->data_kind).vol_flags_mask & DFI_VOL_NEWLY_SWITCHED;
    entered->flags = (uint8_t)((uint32_t)entered->flags | newly); /* wide-operands-reviewed: < 256 */
    /* [switch], with [from] and the move (Parting Shot, Flip Turn, U-turn) when the move made it */
    duoforge_event e = dfi_event_make(drag ? DUOFORGE_EVENT_DRAG : DUOFORGE_EVENT_SWITCH, side * 2u + slot);
    e.id = (uint16_t)reserve;
    if (disguised) {
        /* the shown roster index (side channel of the record; the projection strips it, decision 0026 section 4) */
        e.reserved[0] = (uint8_t)(disguise + 1u); /* wide-operands-reviewed: roster index + 1, at most 6 */
    }
    if (insta) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE; /* the [switch] line has no [from]; the revive is the cause (decision 0025) */
        e.id2 = (uint16_t)DFI_MOVE_REVIVALBLESSING; /* wide-operands-reviewed: a move id of the pool tables, a u16 */
    } else if (parting_shot || pivot != NULL) {
        e.cause = (uint8_t)DUOFORGE_CAUSE_MOVE;
        e.id2 = (uint16_t)(parting_shot ? DFI_MOVE_PARTINGSHOT : pivot->move); /* wide-operands-reviewed: a move id of the pool tables, a u16 */
    }
    dfi_emit_hp(r, e);
    *activation = binding.activation_id;
    return DUOFORGE_OK;
}

static duoforge_status dfi_run_switch(dfi_run *r, const dfi_queue_record *q)
{
    uint32_t activation = 0u;
    const bool insta = q->kind == DFI_Q_INSTASWITCH; /* decision 0025 item 10: the revived member back into its own position */
    const duoforge_status st = dfi_switch_in(r, q->side, q->slot, q->reserve, false, insta, &activation);
    if (st != DUOFORGE_OK) {
        return st;
    }
    return dfi_insert_run_switch(r, q->side, q->slot, activation);
}

#endif
