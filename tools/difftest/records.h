#ifndef DUOFORGE_TOOLS_DIFFTEST_RECORDS_H
#define DUOFORGE_TOOLS_DIFFTEST_RECORDS_H
/*
 * Reader of the battle records that tools/reference/conformance_records.py
 * writes (its docstring has the format): the input of the differential
 * runner (diff_runner.c) and of the test that checks the records against the
 * compiled conformance tables (tests/test_runner_records.c).
 *
 * A battle is read into the df_conf_* types of
 * tests/reference/conformance_types.h, zero-filled where the records say
 * nothing (the members beyond member_count). The reader is strict: a line
 * that is not exactly the format (a value that does not fit its field, a
 * leading zero, an extra or a missing token, a character that is not
 * printable ASCII, a count or an offset that disagrees with the lines) is
 * DFR_MALFORMED with a message naming the line, never a guess. The tape
 * offsets of a step are into the tape of its own battle.
 *
 * White-box (it includes rng/draw.h): the consumer has src/ on its include path.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include <duoforge/duoforge.h>

#include "reference/conformance_types.h"
#include "rng/draw.h"

#define DFR_NAME_MAX 63u

typedef struct dfr_battle {
    char name[DFR_NAME_MAX + 1u];
    uint32_t team_c;       /* 0: the closure tables, 1: Team C's */
    /* 0: the conformance fallback (CLOSURE, then CLOSURE_DEV; TEAM_C, then
     * TEAM_C_DEV); else the DUOFORGE_DATA_KIND_* the battle must be created
     * under, with no fallback. It goes with team_c: a closure kind for a
     * closure battle, a Team C kind for a Team C battle. */
    uint32_t strict_kind;
    uint32_t member_count; /* 1..6, the same for both sides */
    uint32_t step_count;   /* at least 1 */
    uint32_t dropped_total;
    df_conf_member members[2][6]; /* member_count per side, the rest zero */
    df_conf_step *steps;          /* step_count entries */
    /* Every step's kept draws and events; a step names its slice by offset.
     * Never NULL after DFR_OK (at least one zero element is allocated): a NULL
     * tape would mean "play with the generator" to dfi_battle_step_events_tape. */
    dfi_tape_entry *tape;
    uint32_t tape_count;
    duoforge_event *events;
    uint32_t event_count;
} dfr_battle;

typedef enum dfr_status {
    DFR_OK = 0,
    DFR_EOF,          /* the input ended between battles */
    DFR_MALFORMED,    /* not the format: dfr_reader.error says where */
    DFR_OUT_OF_MEMORY,
    DFR_IO            /* the input could not be read */
} dfr_status;

typedef struct dfr_reader {
    FILE *file;      /* NULL for a reader over memory */
    const char *mem; /* memory reader: the data (not owned) */
    size_t mem_len;
    size_t mem_pos;
    char *line;      /* the current line without its line end, NUL-terminated */
    size_t line_len;
    size_t line_cap;
    uint32_t line_no; /* of the current line, from 1 */
    char error[256];  /* the message of the last DFR_MALFORMED */
} dfr_reader;

/* A reader over an open stream (binary mode: the format has LF line ends and
 * a CR is malformed) or over `len` bytes in memory. The reader does not close
 * the file. */
void dfr_reader_init(dfr_reader *r, FILE *file);
void dfr_reader_init_memory(dfr_reader *r, const char *data, size_t len);
void dfr_reader_destroy(dfr_reader *r);

/* The next battle of the input. DFR_EOF when the input ends cleanly before a
 * battle; any other failure leaves *out zeroed (nothing to free). */
dfr_status dfr_read_battle(dfr_reader *r, dfr_battle *out);

/* Frees the arrays of a battle and zeroes it. */
void dfr_battle_free(dfr_battle *b);

#endif
