/*
 * duoforge.reference.conformance (white-box): battles recorded from the
 * pinned Showdown (tests/reference/traces, converted by
 * tools/reference/trace_to_c.py into tests/reference/conformance.h) replayed
 * in DuoForge. The teams are created through the public API (CLOSURE_DEV,
 * the support gate must let them pass); every turn runs through the step
 * with the reference's kept draws as a test-only tape, which must be
 * consumed exactly; afterwards HP, PP, stat stages and the stall counter of
 * every member equal the reference, and so does the turn number.
 *
 * Built with DF_CONFORMANCE_TEAM_C it is duoforge.reference.conformance_team_c:
 * the same driver over the Team C battles (tests/reference/conformance_team_c.h,
 * decision 0009 section 6.1) with TEAM_C and TEAM_C_DEV contexts.
 */
#include <stdio.h>
#include <string.h>

#ifdef DF_CONFORMANCE_TEAM_C
#include "data/extended_tables.h"
#include "reference/conformance_team_c.h"
#include "support/team_c.h"
#define DF_CONF_FORMES dfi_ext_formes
#define DF_TEAM_C_BATTLES 9u /* the recorded Team C battles */
#define DF_TEAM_C_REAL 1u    /* of them under TEAM_C itself (six registered members) */
#else
#include "data/closure_tables.h"
#include "reference/conformance.h"
#define DF_CONF_FORMES dfi_closure_formes
#endif
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static unsigned event_reports = 0;

static void print_event(const char *label, const duoforge_event *e)
{
    fprintf(stderr,
            "    %s kind %u pos %u other %u cause %u id %u id2 %u hp %u/%u kind %u flag %u status %u detail %u "
            "amount %u flags %u\n",
            label, e->kind, e->position, e->other, e->cause, e->id, e->id2, e->hp, e->hp_max, e->hp_kind, e->hp_flag,
            e->status, e->detail, e->amount, e->flags);
}

/* Each player's events of the step against the protocol lines the game
 * shows that player (decision 0007 section 6). */
static unsigned compare_events(const df_conf_step *st, const char *name, uint32_t step,
                               const duoforge_event_buffer *buffers)
{
    unsigned bad = 0;
    for (uint32_t p = 0; p < 2u; ++p) {
        const duoforge_event *want = &conf_events[st->ev_off[p]];
        const uint32_t nwant = st->ev_len[p];
        const duoforge_event *have = buffers[p].events;
        const uint32_t nhave = buffers[p].count;
        uint32_t i = 0;
        while (i < nwant && i < nhave && memcmp(&want[i], &have[i], sizeof want[i]) == 0) {
            ++i;
        }
        if (i < nwant || i < nhave) {
            ++bad;
            if (event_reports < 12u) {
                ++event_reports;
                fprintf(stderr, "  %s step %u: player %u event %u differs\n", name, step, p, i);
                if (i < nwant) {
                    print_event("reference", &want[i]);
                }
                if (i < nhave) {
                    print_event("engine   ", &have[i]);
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
static unsigned compare_observation(const duoforge_context *ctx, const duoforge_battle *b, const df_conf_step *st,
                                    const df_conf_battle *cb, uint32_t step)
{
    unsigned bad = 0;
    for (uint32_t viewer = 0; viewer < 2u; ++viewer) {
        duoforge_observation o;
        if (duoforge_battle_observe(ctx, b, viewer, &o) != DUOFORGE_OK) {
            fprintf(stderr, "  %s step %u: no observation for player %u\n", cb->name, step, viewer);
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
            fprintf(stderr, "  %s step %u: player %u sees another field\n", cb->name, step, viewer);
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
                    ability = 1u + DF_CONF_FORMES[DF_CONF_FORMES[set->species].mega_forme].ability;
                }
                bool ok = v->status == status && v->is_mega == e->mega && v->item_used == used && v->ability == ability;
                for (uint32_t k = 0; k < v->move_count && k < 4u; ++k) {
                    ok = ok && v->pp[k] == e->pp[k]; /* own exact, foe derived: the same in the closure */
                }
                if (!ok) {
                    fprintf(stderr,
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
                /* The locked target only for the own side; Protect, Flash Fire,
                 * a charged move and the stall counter as Showdown's volatiles. */
                const uint32_t target = (s == viewer && e->locked_slot != 0xFFu) ? e->locked_target : DUOFORGE_TARGET_NONE;
                bool ok = memcmp(pv->stages, e->stages, 7u) == 0 && pv->confused == (e->confusion != 0u ? 1u : 0u) &&
                          pv->locked_slot == e->locked_slot && pv->locked_target == target &&
                          pv->protecting == ((e->vols & 1u) != 0u ? 1u : 0u) &&
                          pv->flash_fire == ((e->vols & 2u) != 0u ? 1u : 0u) &&
                          pv->charging == ((e->vols & 4u) != 0u ? 1u : 0u) &&
                          (pv->protect_chain != 0u) == (e->stall != 0u);
                if (b->boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
                    ok = memcmp(pv->stages, e->stages, 7u) == 0; /* locks are not compared at the end */
                }
                if (!ok) {
                    fprintf(stderr, "  %s step %u: player %u sees side %u position %u differently\n", cb->name, step,
                            viewer, s, k);
                    ++bad;
                }
            }
        }
    }
    return bad;
}

static unsigned compare_state(const duoforge_context *ctx, const duoforge_battle *b, const df_conf_step *st,
                              const char *name, uint32_t step)
{
    unsigned bad = 0;
    if (b->turn != st->turn) {
        fprintf(stderr, "  %s step %u: turn %u, reference %u\n", name, step, b->turn, st->turn);
        ++bad;
    }
    if (b->boundary_kind != st->boundary || b->result != st->result) {
        fprintf(stderr, "  %s step %u: boundary %u result %u, reference %u %u\n", name, step, b->boundary_kind,
                b->result, st->boundary, st->result);
        ++bad;
    }
    if (b->weather != st->field[0] || b->weather_turns != st->field[1] || b->terrain != st->field[2] ||
        b->terrain_turns != st->field[3]) {
        fprintf(stderr, "  %s step %u: field %u/%u %u/%u, reference %u/%u %u/%u\n", name, step, b->weather,
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
            fprintf(stderr, "  %s step %u: condition %u has %u turns, reference %u\n", name, step, i, conditions[i],
                    st->field[4u + i]);
            ++bad;
        }
    }
    /* The moves the request offers per slot match the reference's request:
     * disabled moves (no PP, Fake Out) and Struggle. */
    if (b->boundary_kind == DUOFORGE_BOUNDARY_TURN) {
        for (uint32_t s = 0; s < 2u; ++s) {
            static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
            uint32_t n = 0;
            if (duoforge_battle_candidates(ctx, b, s, cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK) {
                fprintf(stderr, "  %s step %u: side %u has no candidates\n", name, step, s);
                ++bad;
                continue;
            }
            uint32_t mask[2] = {0u, 0u};
            for (uint32_t i = 0; i < n; ++i) {
                for (uint32_t k = 0; k < 2u; ++k) {
                    const duoforge_slot_command *c = &cands[i].slots[k];
                    if (c->kind == DUOFORGE_SLOT_MOVE) {
                        mask[k] |= c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 0x10u : 1u << c->move_slot;
                    }
                }
            }
            for (uint32_t k = 0; k < 2u; ++k) {
                const uint32_t occ = b->sides[s].positions[k].occupant;
                const bool alive = occ < DUOFORGE_MAX_ROSTER && b->sides[s].members[occ].hp != 0u;
                if (st->enabled[s][k] != 0xFFu && alive && mask[k] != st->enabled[s][k]) {
                    fprintf(stderr, "  %s step %u: side %u slot %u offers 0x%x, reference 0x%x\n", name, step, s,
                            k, mask[k], st->enabled[s][k]);
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
            fprintf(stderr, "  %s step %u: entry %u (position %u) is out of the reference's order\n", name, step, i,
                    st->entries[i]);
            ++bad;
        }
        last_activation = activation;
    }
    for (uint32_t s = 0; s < 2u; ++s) {
        for (uint32_t p = 0; p < 2u; ++p) {
            if (b->sides[s].positions[p].occupant != st->occupants[s][p]) {
                fprintf(stderr, "  %s step %u: side %u position %u holds %u, reference %u\n", name, step, s, p,
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
            const uint32_t held = mem->item != 0u && mem->item_consumed == 0u ? 1u : 0u;
            if (held != e->held) {
                fprintf(stderr, "  %s step %u: side %u member %u holds %u, reference %u\n", name, step, s, m, held,
                        e->held);
                ++bad;
            }
            /* What the opponent knows: seen, and the last public HP display. */
            const dfi_side *foe = &b->sides[1u - s];
            const uint32_t seen = ((uint32_t)foe->seen_mask >> m) & 1u;
            if (seen != e->seen || foe->knowledge[m].hp_percent != e->seen_percent ||
                foe->knowledge[m].hp_flag != e->seen_flag) {
                fprintf(stderr, "  %s step %u: side %u member %u seen %u at %u/%u, reference %u at %u/%u\n", name,
                        step, s, m, seen, foe->knowledge[m].hp_percent, foe->knowledge[m].hp_flag, e->seen,
                        e->seen_percent, e->seen_flag);
                ++bad;
            }
            if (mem->is_mega != e->mega) {
                fprintf(stderr, "  %s step %u: side %u member %u mega %u, reference %u\n", name, step, s, m, mem->is_mega,
                        e->mega);
                ++bad;
            }
            if (mem->hp != e->hp) {
                fprintf(stderr, "  %s step %u: side %u member %u hp %u, reference %u\n", name, step, s, m, mem->hp,
                        e->hp);
                ++bad;
            }
            for (uint32_t k = 0; k < mem->move_count; ++k) {
                if (mem->moves[k].pp != e->pp[k]) {
                    fprintf(stderr, "  %s step %u: side %u member %u move %u pp %u, reference %u\n", name, step, s,
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
                    fprintf(stderr, "  %s step %u: side %u member %u stage %u = %u, reference %u\n", name, step, s,
                            m, i, have, e->stages[i]);
                    ++bad;
                }
            }
            if (!e->fainted && (mem->status != e->status || mem->status_counter != e->status_counter)) {
                fprintf(stderr, "  %s step %u: side %u member %u status %u/%u, reference %u/%u\n", name, step, s, m,
                        mem->status, mem->status_counter, e->status, e->status_counter);
                ++bad;
            }
            /* A two-turn move's lock, at TURN and REPLACEMENT boundaries. */
            if (pos != NULL && b->boundary_kind != DUOFORGE_BOUNDARY_TERMINAL) {
                const uint32_t lslot = pos->locked_move != 0u ? (uint32_t)pos->locked_move - 1u : 0xFFu;
                const uint32_t ltarget = pos->locked_move != 0u ? pos->locked_target : 0u;
                if (lslot != e->locked_slot || ltarget != e->locked_target) {
                    fprintf(stderr, "  %s step %u: side %u member %u locked %u/%u, reference %u/%u\n", name, step, s,
                            m, lslot, ltarget, e->locked_slot, e->locked_target);
                    ++bad;
                }
            }
            const uint32_t confusion = pos != NULL ? pos->confusion_turns : 0u;
            if (confusion != e->confusion) {
                fprintf(stderr, "  %s step %u: side %u member %u confusion %u, reference %u\n", name, step, s, m,
                        confusion, e->confusion);
                ++bad;
            }
            const uint32_t stall = (pos != NULL && pos->stall_level != 0u) ? 1u : 0u;
            if (stall != e->stall) {
                fprintf(stderr, "  %s step %u: side %u member %u stall %u, reference %u\n", name, step, s, m, stall,
                        e->stall);
                ++bad;
            }
        }
    }
    return bad;
}

int main(void)
{
    df_test t;
#ifdef DF_CONFORMANCE_TEAM_C
    df_test_begin(&t, "duoforge.reference.conformance_team_c");
    duoforge_context *k1 = df_make_context(&df_config_team_c);
    duoforge_context *k2 = df_make_context(&df_config_team_c_dev);
#else
    df_test_begin(&t, "duoforge.reference.conformance");
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
#endif
    unsigned real = 0; /* battles under CLOSURE data: every set has a real ability */
    for (size_t bi = 0; bi < sizeof conf_battles / sizeof conf_battles[0]; ++bi) {
        const df_conf_battle *cb = &conf_battles[bi];
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        /* CLOSURE data where the sets are real, CLOSURE_DEV (No Ability
         * allowed) for the development teams. */
        const duoforge_context *ctx = k1;
        duoforge_status created = duoforge_battle_create(k1, &setup, &b);
        if (created != DUOFORGE_OK) {
            ctx = k2;
            created = duoforge_battle_create(k2, &setup, &b);
        } else {
            real += 1u;
        }
        if (!DF_CHECK(&t, created == DUOFORGE_OK && b != NULL)) {
            fprintf(stderr, "  %s: the setup is rejected: %s\n", cb->name, duoforge_status_name(created));
            continue;
        }
        unsigned bad = 0;
        for (uint32_t si = 0; si < cb->step_count && bad == 0u; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
            for (uint32_t s = 0; s < 2u; ++s) {
                if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
                    continue;
                }
                duoforge_side_choice *r = &bd.responses[s];
                r->epoch = b->request_epoch;
                r->side = (uint8_t)s;
                if (st->team) {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                    r->pick_count = 4u;
                    for (uint32_t i = 0; i < 4u; ++i) {
                        r->picks[i] = st->picks[s][i];
                    }
                } else {
                    r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                    for (uint32_t k = 0; k < 2u; ++k) {
                        const df_conf_cmd *c = &st->cmds[s][k];
                        r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve,
                                                              {0u, 0u, 0u}};
                    }
                }
            }
            duoforge_step_result res;
            uint32_t used = 0xFFFFFFFFu;
            static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
            duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u},
                                                {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
            const duoforge_status status = dfi_battle_step_events_tape(
                ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res, buffers);
            const bool consumed = used == st->tape_len;
            if (!DF_CHECK(&t, status == DUOFORGE_OK && consumed)) {
                fprintf(stderr, "  %s step %u: %s, tape %u of %u\n", cb->name, si, duoforge_status_name(status),
                        used, st->tape_len);
                ++bad;
                break;
            }
            bad += compare_state(ctx, b, st, cb->name, si);
            bad += compare_observation(ctx, b, st, cb, si);
            bad += compare_events(st, cb->name, si, buffers);
            DF_CHECK(&t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
        }
        DF_CHECK_EQ_U64(&t, bad, 0u);
        duoforge_battle_destroy(b);
    }
#ifdef DF_CONFORMANCE_TEAM_C
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], DF_TEAM_C_BATTLES);
    DF_CHECK_EQ_U64(&t, real, DF_TEAM_C_REAL);
#else
    DF_CHECK_EQ_U64(&t, sizeof conf_battles / sizeof conf_battles[0], 87u);
    /* Exactly the battles of the real teams run under CLOSURE, the certified
     * profile (decision 0010): the closure gate's 8 and the 16 of M5 step 3. */
    DF_CHECK_EQ_U64(&t, real, 24u);
#endif
#ifdef DF_CONFORMANCE_TEAM_C
    fprintf(stderr, "  %u of the battles run under TEAM_C data\n", real);
#else
    fprintf(stderr, "  %u of the battles run under CLOSURE data\n", real);
#endif
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    return df_test_end(&t);
}
