/*
 * The comparators of the conformance tests: the engine's battle after a step
 * against what the pinned reference recorded (tests/reference/conformance_types.h).
 * Moved out of test_conformance.c so that other runners can use them; the
 * checks, their order and their messages are unchanged. Every message goes
 * to `out`.
 */
#include "support/conformance_compare.h"

#include <string.h>

#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"

static void print_event(FILE *out, const char *label, const duoforge_event *e)
{
    fprintf(out,
            "    %s kind %u pos %u other %u cause %u id %u id2 %u hp %u/%u kind %u flag %u status %u detail %u "
            "amount %u flags %u\n",
            label, e->kind, e->position, e->other, e->cause, e->id, e->id2, e->hp, e->hp_max, e->hp_kind, e->hp_flag,
            e->status, e->detail, e->amount, e->flags);
}

/* Each player's events of the step against the protocol lines the game
 * shows that player (decision 0007 section 6). */
unsigned df_conf_compare_events(FILE *out, const df_conf_step *st, const char *name, uint32_t step,
                                const duoforge_event_buffer *buffers, const duoforge_event *events,
                                unsigned *event_reports)
{
    unsigned bad = 0;
    for (uint32_t p = 0; p < 2u; ++p) {
        const duoforge_event *want = &events[st->ev_off[p]];
        const uint32_t nwant = st->ev_len[p];
        const duoforge_event *have = buffers[p].events;
        const uint32_t nhave = buffers[p].count;
        uint32_t i = 0;
        while (i < nwant && i < nhave && memcmp(&want[i], &have[i], sizeof want[i]) == 0) {
            ++i;
        }
        if (i < nwant || i < nhave) {
            ++bad;
            if (*event_reports < DF_CONF_EVENT_REPORT_CAP) {
                ++*event_reports;
                fprintf(out, "  %s step %u: player %u event %u differs\n", name, step, p, i);
                if (i < nwant) {
                    print_event(out, "reference", &want[i]);
                }
                if (i < nhave) {
                    print_event(out, "engine   ", &have[i]);
                }
            }
        }
    }
    return bad;
}

/* Observation v2 (decision 0007) of both players against the reference:
 * the derived foe PP equals the real PP, and statuses, Mega formes, items
 * used up, stat stages, confusion, charged moves, the field and the side
 * conditions are what the game shows. */
unsigned df_conf_compare_observation(FILE *out, const duoforge_context *ctx, const duoforge_battle *b,
                                     const df_conf_step *st, const df_conf_battle *cb, uint32_t step)
{
    unsigned bad = 0;
    for (uint32_t viewer = 0; viewer < 2u; ++viewer) {
        duoforge_observation o;
        if (duoforge_battle_observe(ctx, b, viewer, &o) != DUOFORGE_OK) {
            fprintf(out, "  %s step %u: no observation for player %u\n", cb->name, step, viewer);
            ++bad;
            continue;
        }
        const uint32_t field[7] = {o.trick_room_turns,           o.sides[0].tailwind_turns,
                                   o.sides[0].reflect_turns,     o.sides[0].light_screen_turns,
                                   o.sides[1].tailwind_turns,    o.sides[1].reflect_turns,
                                   o.sides[1].light_screen_turns};
        bool field_ok = o.weather == st->field[0] && o.weather_turns == st->field[1] && o.terrain == st->field[2] &&
                        o.terrain_turns == st->field[3];
        for (uint32_t i = 0; i < 7u; ++i) {
            field_ok = field_ok && field[i] == st->field[4u + i];
        }
        if (!field_ok) {
            fprintf(out, "  %s step %u: player %u sees another field\n", cb->name, step, viewer);
            ++bad;
        }
        for (uint32_t s = 0; s < 2u; ++s) {
            const duoforge_side_view *sv = &o.sides[s];
            for (uint32_t m = 0; m < 6u; ++m) {
                const df_conf_mon *e = &st->mons[s][m];
                const duoforge_member_view *v = &sv->members[m];
                if (!e->present) {
                    continue;
                }
                const bool visible = s == viewer || e->seen != 0u;
                const uint32_t status = (visible && !e->fainted) ? e->status : 0u;
                const uint32_t used = (cb->members[s][m].item != 0u && e->held == 0u) ? 1u : 0u;
                /* The ability on the sheet, the Mega forme's once it evolved. */
                const df_conf_member *set = &cb->members[s][m];
                uint32_t ability = set->ability;
                if (e->mega != 0u) {
                    ability = 1u + dfi_pool_formes[dfi_mega_of(set->species, set->item)].ability; /* the Mega of (forme, stone) */
                }
                bool ok = v->status == status && v->is_mega == e->mega && v->item_used == used && v->ability == ability;
                for (uint32_t k = 0; k < v->move_count && k < 4u; ++k) {
                    ok = ok && v->pp[k] == e->pp[k]; /* own exact, foe derived: the same in the closure */
                }
                if (!ok) {
                    fprintf(out,
                            "  %s step %u: player %u sees side %u member %u as status %u mega %u used %u pp %u, "
                            "reference %u %u %u %u\n",
                            cb->name, step, viewer, s, m, v->status, v->is_mega, v->item_used, v->pp[0], status,
                            e->mega, used, e->pp[0]);
                    ++bad;
                }
            }
            for (uint32_t k = 0; k < 2u; ++k) {
                const uint32_t occ = st->occupants[s][k];
                const duoforge_position_view *pv = &sv->positions[k];
                if (occ >= 6u) {
                    continue;
                }
                const df_conf_mon *e = &st->mons[s][occ];
                /* The locked target only for the own side and only while a
                 * two-turn move charges (a choice lock has none); Protect,
                 * Flash Fire, a charged move and the stall counter as
                 * Showdown's volatiles; Unburden's only while the item is gone (the volatile of a holder of its own Mega
                 * Stone, set by a Knock Off that the stone refused, doubles no Speed and shows nothing). */
                const uint32_t target =
                    (s == viewer && (e->vols & 4u) != 0u) ? e->locked_target : DUOFORGE_TARGET_NONE;
                bool ok = memcmp(pv->stages, e->stages, 7u) == 0 && pv->confused == (e->confusion != 0u ? 1u : 0u) &&
                          pv->locked_slot == e->locked_slot && pv->locked_target == target &&
                          pv->protecting == ((e->vols & 1u) != 0u ? 1u : 0u) &&
                          pv->flash_fire == ((e->vols & 2u) != 0u ? 1u : 0u) &&
                          pv->charging == ((e->vols & 4u) != 0u ? 1u : 0u) &&
                          pv->reserved == (((e->vols & 16u) != 0u && e->held == 0u ? DUOFORGE_POSITION_FLAG_UNBURDEN : 0u) |
                                           ((e->vols & 32u) != 0u ? DUOFORGE_POSITION_FLAG_HELPING_HAND : 0u) |
                                           ((e->vols & 64u) != 0u ? DUOFORGE_POSITION_FLAG_FOLLOW_ME : 0u)) &&
                          (pv->protect_chain != 0u) == (e->stall != 0u);
                if (b->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                    ok = memcmp(pv->stages, e->stages, 7u) == 0; /* locks are not compared at the end */
                }
                if (!ok) {
                    fprintf(out, "  %s step %u: player %u sees side %u position %u differently\n", cb->name, step,
                            viewer, s, k);
                    ++bad;
                }
            }
        }
    }
    return bad;
}

unsigned df_conf_compare_state(FILE *out, const duoforge_context *ctx, const duoforge_battle *b,
                               const df_conf_step *st, const char *name, uint32_t step)
{
    unsigned bad = 0;
    if (b->turn != st->turn) {
        fprintf(out, "  %s step %u: turn %u, reference %u\n", name, step, b->turn, st->turn);
        ++bad;
    }
    if (b->boundary_kind != st->boundary || b->result != st->result) {
        fprintf(out, "  %s step %u: boundary %u result %u, reference %u %u\n", name, step, b->boundary_kind,
                b->result, st->boundary, st->result);
        ++bad;
    }
    if (b->weather != st->field[0] || b->weather_turns != st->field[1] || b->terrain != st->field[2] ||
        b->terrain_turns != st->field[3]) {
        fprintf(out, "  %s step %u: field %u/%u %u/%u, reference %u/%u %u/%u\n", name, step, b->weather,
                b->weather_turns, b->terrain, b->terrain_turns, st->field[0], st->field[1], st->field[2],
                st->field[3]);
        ++bad;
    }
    /* Trick Room and the side conditions: their remaining turns. */
    const uint32_t conditions[7] = {b->trick_room_turns,          b->sides[0].tailwind_turns,
                                    b->sides[0].reflect_turns,     b->sides[0].light_screen_turns,
                                    b->sides[1].tailwind_turns,    b->sides[1].reflect_turns,
                                    b->sides[1].light_screen_turns};
    for (uint32_t i = 0; i < 7u; ++i) {
        if (conditions[i] != st->field[4u + i]) {
            fprintf(out, "  %s step %u: condition %u has %u turns, reference %u\n", name, step, i, conditions[i],
                    st->field[4u + i]);
            ++bad;
        }
    }
    /* The moves the request offers per slot match the reference's request:
     * disabled moves (no PP, Fake Out) and Struggle. A request that offers
     * only Struggle has no canMegaEvo (Struggle becomes its locked move in
     * sim/pokemon.ts getMoveRequestData), so no candidate declares Mega there. */
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TURN) {
        for (uint32_t s = 0; s < 2u; ++s) {
            static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
            uint32_t n = 0;
            if (duoforge_battle_candidates(ctx, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK) {
                fprintf(out, "  %s step %u: side %u has no candidates\n", name, step, s);
                ++bad;
                continue;
            }
            uint32_t mask[2] = {0u, 0u};
            bool mega[2] = {false, false};
            for (uint32_t i = 0; i < n; ++i) {
                for (uint32_t k = 0; k < 2u; ++k) {
                    const duoforge_slot_command *c = &cands[i].slots[k];
                    if (c->kind == DUOFORGE_SLOT_MOVE) {
                        mask[k] |= c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 0x10u : 1u << c->move_slot;
                        mega[k] = mega[k] || c->mega != 0u;
                    }
                }
            }
            for (uint32_t k = 0; k < 2u; ++k) {
                const uint32_t occ = b->sides[s].positions[k].occupant;
                const bool alive = occ < DUOFORGE_MAX_ROSTER && b->sides[s].members[occ].hp != 0u;
                if (st->enabled[s][k] != 0xFFu && alive && mask[k] != st->enabled[s][k]) {
                    fprintf(out, "  %s step %u: side %u slot %u offers 0x%x, reference 0x%x\n", name, step, s,
                            k, mask[k], st->enabled[s][k]);
                    ++bad;
                }
                if (st->enabled[s][k] == 0x10u && alive && mega[k]) {
                    fprintf(out, "  %s step %u: side %u slot %u offers Struggle with Mega\n", name, step, s, k);
                    ++bad;
                }
            }
        }
    }
    /* Entries in the reference's order have rising activation ids. */
    uint32_t last_activation = 0u;
    for (uint32_t i = 0; i < 4u && st->entries[i] != 0xFFu; ++i) {
        const uint32_t activation = b->sides[st->entries[i] / 2u].positions[st->entries[i] % 2u].activation_id;
        if (i > 0u && activation <= last_activation) {
            fprintf(out, "  %s step %u: entry %u (position %u) is out of the reference's order\n", name, step, i,
                    st->entries[i]);
            ++bad;
        }
        last_activation = activation;
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t p = 0; p < 2u; ++p) {
            if (b->sides[s].positions[p].occupant != st->occupants[s][p]) {
                fprintf(out, "  %s step %u: side %u position %u holds %u, reference %u\n", name, step, s, p,
                        b->sides[s].positions[p].occupant, st->occupants[s][p]);
                ++bad;
            }
        }
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t m = 0; m < 6u; ++m) {
            const df_conf_mon *e = &st->mons[s][m];
            if (!e->present) {
                continue;
            }
            const dfi_member *mem = &b->sides[s].members[m];
            /* The item the member holds now: its sheet's unless used up, and not one that a move took (the POOL tail's
             * item_now, DFI_TAIL_ITEM_NONE; zero under the other kinds); an item that a move gave it (item_now 1 to 254,
             * step G29) is held even without a sheet item. */
            const uint32_t now = b->tail.sides[s].item_now[m];
            const uint32_t held =
                mem->item_consumed == 0u && now != DFI_TAIL_ITEM_NONE && (now != 0u || mem->item != 0u) ? 1u : 0u;
            if (held != e->held) {
                fprintf(out, "  %s step %u: side %u member %u holds %u, reference %u\n", name, step, s, m, held,
                        e->held);
                ++bad;
            }
            /* What the opponent knows: seen, and the last public HP display. */
            const dfi_side *foe = &b->sides[1u - s];
            const uint32_t seen = ((uint32_t)foe->seen_mask >> m) & 1u;
            if (seen != e->seen || foe->knowledge[m].hp_percent != e->seen_percent ||
                foe->knowledge[m].hp_flag != e->seen_flag) {
                fprintf(out, "  %s step %u: side %u member %u seen %u at %u/%u, reference %u at %u/%u\n", name,
                        step, s, m, seen, foe->knowledge[m].hp_percent, foe->knowledge[m].hp_flag, e->seen,
                        e->seen_percent, e->seen_flag);
                ++bad;
            }
            if (mem->is_mega != e->mega) {
                fprintf(out, "  %s step %u: side %u member %u mega %u, reference %u\n", name, step, s, m, mem->is_mega,
                        e->mega);
                ++bad;
            }
            if (mem->hp != e->hp) {
                fprintf(out, "  %s step %u: side %u member %u hp %u, reference %u\n", name, step, s, m, mem->hp,
                        e->hp);
                ++bad;
            }
            for (uint32_t k = 0; k < mem->move_count; ++k) {
                if (mem->moves[k].pp != e->pp[k]) {
                    fprintf(out, "  %s step %u: side %u member %u move %u pp %u, reference %u\n", name, step, s,
                            m, k, mem->moves[k].pp, e->pp[k]);
                    ++bad;
                }
            }
            /* Stages and the stall counter live in the position. */
            const dfi_active_slot *pos = NULL;
            for (uint32_t p = 0; p < 2u; ++p) {
                if (b->sides[s].positions[p].occupant == m) {
                    pos = &b->sides[s].positions[p];
                }
            }
            for (uint32_t i = 0; i < 7u; ++i) {
                const uint32_t have = pos != NULL ? pos->stages[i] : 6u;
                if (have != e->stages[i]) {
                    fprintf(out, "  %s step %u: side %u member %u stage %u = %u, reference %u\n", name, step, s,
                            m, i, have, e->stages[i]);
                    ++bad;
                }
            }
            if (!e->fainted && (mem->status != e->status || mem->status_counter != e->status_counter)) {
                fprintf(out, "  %s step %u: side %u member %u status %u/%u, reference %u/%u\n", name, step, s, m,
                        mem->status, mem->status_counter, e->status, e->status_counter);
                ++bad;
            }
            /* A two-turn move's lock, a Choice item's lock, Unburden, Helping
             * Hand and Follow Me (Team C) and flinch, at TURN, REPLACEMENT and
             * PIVOT boundaries. */
            if (pos != NULL && b->boundary_kind != DUOFORGE_BOUNDARY_TERMINAL) {
                /* Step G56: a lockedmove (Outrage) keeps its slot in locked_move too, but the reference has no locked slot for it
                 * (its count is the tail's lock_turns; the lock is compared through the request and the move lines). */
                const bool lockedmove = b->tail.sides[s].positions[pos - b->sides[s].positions].lock_turns != 0u;
                const uint32_t lslot = pos->locked_move != 0u && !lockedmove ? (uint32_t)pos->locked_move - 1u : 0xFFu;
                const uint32_t ltarget = pos->locked_move != 0u && !lockedmove ? pos->locked_target : 0u;
                const uint32_t choice = ((uint32_t)pos->flags & DFI_VOL_CHOICE_LOCK) != 0u ? 8u : 0u;
                const uint32_t unburden = ((uint32_t)pos->flags & DFI_VOL_UNBURDEN) != 0u ? 16u : 0u;
                const uint32_t helping = ((uint32_t)pos->flags & DFI_VOL_HELPING_HAND) != 0u ? 32u : 0u;
                /* Step G30: the bit of a Rage Powder user is not Follow Me's (its volatile is not compared here: the extension's
                 * RAGE_POWDER bit is, in duoforge.state.pool_g30). */
                const bool rage_powder = pos != NULL && ((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u &&
                                         dfi_last_move_id(b, s * 2u + (uint32_t)(pos - b->sides[s].positions)) == DFI_MOVE_RAGEPOWDER;
                const uint32_t follow = ((uint32_t)pos->flags & DFI_VOL_FOLLOW_ME) != 0u && !rage_powder ? 64u : 0u;
                const uint32_t flinch = ((uint32_t)pos->flags & DFI_VOL_FLINCH) != 0u ? 128u : 0u;
                if (lslot != e->locked_slot || ltarget != e->locked_target || choice != (e->vols & 8u) ||
                    unburden != (e->vols & 16u) || helping != (e->vols & 32u) || follow != (e->vols & 64u) ||
                    flinch != (e->vols & 128u)) {
                    fprintf(out,
                            "  %s step %u: side %u member %u locked %u/%u choice %u unburden %u helping %u "
                            "follow %u flinch %u, reference %u/%u %u %u %u %u %u\n",
                            name, step, s, m, lslot, ltarget, choice, unburden, helping, follow, flinch,
                            e->locked_slot, e->locked_target, e->vols & 8u, e->vols & 16u, e->vols & 32u,
                            e->vols & 64u, e->vols & 128u);
                    ++bad;
                }
            }
            const uint32_t confusion = pos != NULL ? pos->confusion_turns : 0u;
            if (confusion != e->confusion) {
                fprintf(out, "  %s step %u: side %u member %u confusion %u, reference %u\n", name, step, s, m,
                        confusion, e->confusion);
                ++bad;
            }
            const uint32_t stall = (pos != NULL && pos->stall_level != 0u) ? 1u : 0u;
            if (stall != e->stall) {
                fprintf(out, "  %s step %u: side %u member %u stall %u, reference %u\n", name, step, s, m, stall,
                        e->stall);
                ++bad;
            }
        }
    }
    return bad;
}
