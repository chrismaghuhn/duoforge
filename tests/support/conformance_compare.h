#ifndef DUOFORGE_TESTS_SUPPORT_CONFORMANCE_COMPARE_H
#define DUOFORGE_TESTS_SUPPORT_CONFORMANCE_COMPARE_H
/*
 * The comparators of the conformance tests (tests/test_conformance.c): the
 * engine's battle after one step against what the pinned reference recorded
 * for it (tests/reference/conformance_types.h). White-box: they read the
 * battle through state/battle_internal.h.
 *
 * Each one returns the number of differences and writes one line per
 * difference to `out`. `step` is the index of the step, for the messages.
 */
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "data/closure_tables.h"
#include "reference/conformance_types.h"

/* At most this many event differences are written per run; the counter is the caller's. */
#define DF_CONF_EVENT_REPORT_CAP 12u

/* Turn, boundary, result, weather, terrain, Trick Room and the side
 * conditions, the moves each request offers, the order of the entries, the
 * occupants, and per member HP, PP, item, Mega forme, what the opponent has
 * seen, stages, status, locks, confusion and the stall counter. */
unsigned df_conf_compare_state(FILE *out, const duoforge_context *ctx, const duoforge_battle *b,
                               const df_conf_step *st, const char *name, uint32_t step);

/* The status a viewer must see on member `set` (side s): the owner's true status, the foe's shown one, and none for a foe that has
 * seen the member fainted; a holder that fainted under its shown name is the exception (decision 0026 section 4). */
uint32_t df_conf_expected_status(const df_conf_mon *e, const df_conf_member *set, uint32_t s, uint32_t viewer);

/* Both players' observations. The Mega forme's ability is read from the pool tables, whose prefix is the closure
 * and Team C tables (decision 0015), so one table serves every data kind. */
unsigned df_conf_compare_observation(FILE *out, const duoforge_context *ctx, const duoforge_battle *b,
                                     const df_conf_step *st, const df_conf_battle *cb, uint32_t step);

/* Each player's events of the step: `buffers` are the engine's, `events` the
 * array the step's ev_off and ev_len index (conf_events). `event_reports`
 * counts the differences written so far and stops at DF_CONF_EVENT_REPORT_CAP:
 * the differences are still counted in the result. */
unsigned df_conf_compare_events(FILE *out, const df_conf_step *st, const char *name, uint32_t step,
                                const duoforge_event_buffer *buffers, const duoforge_event *events,
                                unsigned *event_reports);

#endif
