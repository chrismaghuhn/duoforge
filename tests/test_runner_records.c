/*
 * duoforge.reference.runner_records (white-box): the records that
 * tools/reference/conformance_records.py writes for the committed battles
 * (read by tools/difftest/records.c) are exactly the compiled conformance
 * tables: every battle, member, step, mon, tape entry and event equals
 * tests/reference/conformance.h, byte for byte (memcmp of zeroed structs; the
 * name and the offsets, which the records count from the start of each
 * battle, are compared separately).
 *
 * usage: <test> <records file>
 *
 * Built with DF_CONFORMANCE_TEAM_C it is duoforge.reference.runner_records_team_c:
 * the same check of team_c.records against tests/reference/conformance_team_c.h.
 *
 * Negative controls: a copy of a parsed battle with one field flipped at a
 * time must be reported by the comparison, or it would pass anything; and
 * (closure build) the reader must refuse damaged copies of the first battle.
 */
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef DF_CONFORMANCE_TEAM_C
#include "reference/conformance_team_c.h"
#define DF_TEST_NAME "duoforge.reference.runner_records_team_c"
#define DF_RECORDS_TEAM_C 1u
#else
#include "reference/conformance.h"
#define DF_TEST_NAME "duoforge.reference.runner_records"
#define DF_RECORDS_TEAM_C 0u
#endif
#include "records.h"
#include "support/check.h"

#define DF_N_BATTLES (sizeof conf_battles / sizeof conf_battles[0])
#define DF_N_TAPE (sizeof conf_tape / sizeof conf_tape[0])
#define DF_N_EVENTS (sizeof conf_events / sizeof conf_events[0])

static void *must_alloc(size_t n)
{
    void *p = malloc(n == 0u ? 1u : n);
    if (p == NULL) {
        fprintf(stderr, "out of memory\n");
        exit(2);
    }
    return p;
}

/* The differences between a parsed battle and the compiled one, `w`. The
 * records count tape entries and events from the start of their battle, the
 * tables from the start of all battles: tape_base and ev_base are where this
 * battle's slices begin in conf_tape and conf_events. A difference is a line
 * on stderr when `report` is set. */
static unsigned compare_battle(const dfr_battle *p, const df_conf_battle *w, uint32_t tape_base, uint32_t ev_base,
                               bool report)
{
    unsigned bad = 0u;
#define DF_DIFF(...)                      \
    do {                                  \
        ++bad;                            \
        if (report) {                     \
            fprintf(stderr, __VA_ARGS__); \
        }                                 \
    } while (0)
    if (strcmp(p->name, w->name) != 0) {
        DF_DIFF("  battle %s: the tables call it %s\n", p->name, w->name);
    }
    if (p->team_c != DF_RECORDS_TEAM_C) {
        DF_DIFF("  battle %s: team_c %u in a file of the other kind\n", p->name, (unsigned)p->team_c);
    }
    if (p->member_count != w->member_count || p->step_count != w->step_count || p->dropped_total != w->dropped) {
        DF_DIFF("  battle %s: members %u steps %u dropped %u, tables %u %u %u\n", p->name, (unsigned)p->member_count,
                (unsigned)p->step_count, (unsigned)p->dropped_total, (unsigned)w->member_count,
                (unsigned)w->step_count, (unsigned)w->dropped);
    }
    for (uint32_t s = 0u; s < 2u; ++s) {
        for (uint32_t m = 0u; m < 6u; ++m) { /* all six: the rest of a short side is zero in both */
            if (memcmp(&p->members[s][m], &w->members[s][m], sizeof p->members[s][m]) != 0) {
                DF_DIFF("  battle %s: member %u of side %u differs\n", p->name, (unsigned)m, (unsigned)s);
            }
        }
    }
    if (p->step_count != w->step_count) {
        return bad; /* the steps cannot be matched */
    }
    for (uint32_t i = 0u; i < w->step_count; ++i) {
        const df_conf_step *ps = &p->steps[i];
        const df_conf_step *ws = &w->steps[i];
        df_conf_step have = *ps;
        have.tape_off += tape_base;
        have.ev_off[0] += ev_base;
        have.ev_off[1] += ev_base;
        if (memcmp(&have, ws, sizeof have) != 0) {
            size_t at = 0u;
            while (((const unsigned char *)&have)[at] == ((const unsigned char *)ws)[at]) {
                ++at;
            }
            DF_DIFF("  battle %s: step %u differs at byte %u of %u (the mons start at %u)\n", p->name, (unsigned)i,
                    (unsigned)at, (unsigned)sizeof have, (unsigned)offsetof(df_conf_step, mons));
            continue; /* its slices are not where the tables say */
        }
        /* The step is the same, so its slices are in range in both. */
        if (ws->tape_len != 0u &&
            memcmp(&p->tape[ps->tape_off], &conf_tape[ws->tape_off], ws->tape_len * sizeof conf_tape[0]) != 0) {
            DF_DIFF("  battle %s: the draws of step %u differ\n", p->name, (unsigned)i);
        }
        for (uint32_t pl = 0u; pl < 2u; ++pl) {
            if (ws->ev_len[pl] != 0u && memcmp(&p->events[ps->ev_off[pl]], &conf_events[ws->ev_off[pl]],
                                               ws->ev_len[pl] * sizeof conf_events[0]) != 0) {
                DF_DIFF("  battle %s: the events of player %u in step %u differ\n", p->name, (unsigned)pl,
                        (unsigned)i);
            }
        }
    }
#undef DF_DIFF
    return bad;
}

/* A copy of a parsed battle that dfr_battle_free can release. */
static dfr_battle clone_battle(const dfr_battle *src)
{
    dfr_battle c = *src;
    c.steps = must_alloc(src->step_count * sizeof *src->steps);
    memcpy(c.steps, src->steps, src->step_count * sizeof *src->steps);
    c.tape = must_alloc(src->tape_count * sizeof *src->tape);
    memcpy(c.tape, src->tape, src->tape_count * sizeof *src->tape);
    c.events = must_alloc(src->event_count * sizeof *src->events);
    memcpy(c.events, src->events, src->event_count * sizeof *src->events);
    return c;
}

/* Each control changes one thing of a battle. */
static void flip_name(dfr_battle *b)
{
    b->name[0] = (char)(b->name[0] ^ 1);
}
static void flip_team_c(dfr_battle *b)
{
    b->team_c ^= 1u;
}
static void flip_dropped(dfr_battle *b)
{
    b->dropped_total += 1u;
}
static void flip_step_count(dfr_battle *b)
{
    b->step_count -= 1u;
}
static void flip_member(dfr_battle *b)
{
    b->members[1][b->member_count - 1u].moves[0] ^= 1u;
}
static void flip_mon(dfr_battle *b)
{
    b->steps[b->step_count - 1u].mons[1][0].hp ^= 1u;
}
static void flip_step_scalar(dfr_battle *b)
{
    b->steps[0].turn ^= 1u;
}
static void flip_offset(dfr_battle *b)
{
    b->steps[1].tape_off ^= 1u;
}
static void flip_tape(dfr_battle *b)
{
    b->tape[b->tape_count - 1u].value ^= 1u;
}
static void flip_event(dfr_battle *b)
{
    b->events[b->event_count - 1u].hp ^= 1u;
}

typedef struct control {
    const char *what;
    void (*flip)(dfr_battle *);
} control;

static const control CONTROLS[] = {
    {"the name", flip_name},
    {"team_c", flip_team_c},
    {"the dropped count", flip_dropped},
    {"the step count", flip_step_count},
    {"a member", flip_member},
    {"a mon of a step", flip_mon},
    {"a field of a step", flip_step_scalar},
    {"an offset", flip_offset},
    {"a draw", flip_tape},
    {"an event", flip_event},
};

/* The comparison must find nothing in a copy and something in each flipped copy. */
static void negative_controls(df_test *t, const dfr_battle *b, const df_conf_battle *w, uint32_t tape_base,
                              uint32_t ev_base)
{
    dfr_battle same = clone_battle(b);
    DF_CHECK_EQ_U64(t, compare_battle(&same, w, tape_base, ev_base, false), 0u);
    dfr_battle_free(&same);
    for (size_t i = 0u; i < sizeof CONTROLS / sizeof CONTROLS[0]; ++i) {
        dfr_battle copy = clone_battle(b);
        CONTROLS[i].flip(&copy);
        if (!DF_CHECK(t, compare_battle(&copy, w, tape_base, ev_base, false) != 0u)) {
            fprintf(stderr, "  the comparison does not report a change of %s\n", CONTROLS[i].what);
        }
        dfr_battle_free(&copy);
    }
}

#ifndef DF_CONFORMANCE_TEAM_C
/* ---- the reader refuses what is not the format ---- */

/* The whole file, NUL-terminated. */
static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        return NULL;
    }
    size_t cap = 1u << 20;
    size_t n = 0u;
    char *buf = must_alloc(cap + 1u);
    for (;;) {
        n += fread(buf + n, 1u, cap - n, f);
        if (n < cap) {
            break;
        }
        cap *= 2u;
        char *bigger = realloc(buf, cap + 1u);
        if (bigger == NULL) {
            fprintf(stderr, "out of memory\n");
            exit(2);
        }
        buf = bigger;
    }
    (void)fclose(f);
    buf[n] = '\0';
    return buf;
}

/* The status of reading one battle from `text`, whose message goes to `error`; *then_eof says whether
 * the input is then at its end. */
static dfr_status read_text(const char *text, size_t len, char *error, size_t error_cap, bool *then_eof)
{
    dfr_reader r;
    dfr_battle b;
    dfr_reader_init_memory(&r, text, len);
    const dfr_status st = dfr_read_battle(&r, &b);
    *then_eof = false;
    if (st == DFR_OK) {
        dfr_battle_free(&b);
        *then_eof = dfr_read_battle(&r, &b) == DFR_EOF;
    }
    (void)snprintf(error, error_cap, "%s", r.error);
    dfr_reader_destroy(&r);
    return st;
}

/* The first battle's text: `len` bytes at `text`. */
typedef struct sample {
    const char *text;
    size_t len;
} sample;

/* The sample with `remove` bytes at `at` replaced by `insert`. */
static char *splice(const sample *s, size_t at, size_t remove, const char *insert, size_t *out_len)
{
    const size_t ins = strlen(insert);
    char *out = must_alloc(s->len - remove + ins + 1u);
    memcpy(out, s->text, at);
    memcpy(out + at, insert, ins);
    memcpy(out + at + ins, s->text + at + remove, s->len - at - remove);
    *out_len = s->len - remove + ins;
    out[*out_len] = '\0';
    return out;
}

/* Where the nth value (from 0) of the line that starts at `line` is: "S 1 2 3" has 1 at value 0. */
static size_t value_at(const sample *s, size_t line, size_t n)
{
    const char *p = s->text + line + 2u;
    for (size_t i = 0u; i < n; ++i) {
        p = strchr(p, ' ') + 1;
    }
    return (size_t)(p - s->text);
}

static size_t value_len(const sample *s, size_t at)
{
    return strcspn(s->text + at, " \n");
}

/* The sample with its nth value of a line replaced. */
static char *replace_value(const sample *s, size_t line, size_t n, const char *text, size_t *out_len)
{
    const size_t at = value_at(s, line, n);
    return splice(s, at, value_len(s, at), text, out_len);
}

#define DF_MAX_DAMAGE 16u

typedef struct damage {
    const char *what;
    char *text;
    size_t len;
} damage;

static void refuse_damaged_copies(df_test *t, const sample *s)
{
    char error[256];
    bool then_eof = false;
    const size_t b_line = 0u;
    const size_t b_end = (size_t)(strchr(s->text, '\n') - s->text); /* the line end of the B line */
    const size_t s_line = (size_t)(strstr(s->text, "\nS ") - s->text) + 1u;
    size_t values = 0u; /* in the S line: one space before each */
    for (const char *c = s->text + s_line; *c != '\n'; ++c) {
        values += *c == ' ' ? 1u : 0u;
    }
    const size_t last_value = value_at(s, s_line, values - 1u);

    DF_CHECK_EQ_U64(t, read_text(s->text, s->len, error, sizeof error, &then_eof), DFR_OK);
    DF_CHECK(t, then_eof); /* the sample is one battle and nothing else */
    DF_CHECK_EQ_U64(t, read_text("", 0u, error, sizeof error, &then_eof), DFR_EOF);

    damage bad[DF_MAX_DAMAGE];
    size_t n = 0u;
    size_t len = 0u;
    char steps_plus_one[16];
    (void)snprintf(steps_plus_one, sizeof steps_plus_one, "%u",
                   (unsigned)strtoul(s->text + value_at(s, b_line, 3u), NULL, 10) + 1u);
#define DF_DAMAGE(why, text_expr)                      \
    do {                                               \
        if (n == DF_MAX_DAMAGE) {                      \
            fprintf(stderr, "too many damaged copies\n"); \
            exit(2);                                   \
        }                                              \
        bad[n].what = (why);                           \
        bad[n].text = (text_expr);                     \
        bad[n].len = len;                              \
        ++n;                                           \
    } while (0)
    DF_DAMAGE("the input ends before END", splice(s, s->len - 4u, 4u, "", &len));
    DF_DAMAGE("the input ends inside a line", splice(s, s->len - 2u, 2u, "", &len));
    DF_DAMAGE("text after END", splice(s, s->len - 1u, 1u, " \n", &len));
    DF_DAMAGE("another record where the B line is", splice(s, b_line, 1u, "X", &len));
    DF_DAMAGE("team_c 2", replace_value(s, b_line, 1u, "2", &len));
    DF_DAMAGE("a leading zero", splice(s, value_at(s, b_line, 1u), 0u, "0", &len));
    DF_DAMAGE("a space at the end of a line", splice(s, b_end, 0u, " ", &len));
    DF_DAMAGE("a carriage return", splice(s, b_end, 0u, "\r", &len));
    DF_DAMAGE("a byte that is not ASCII", splice(s, b_end, 0u, "\xc3\xa9", &len));
    DF_DAMAGE("a dash in a name", splice(s, value_at(s, b_line, 0u), 0u, "-", &len));
    DF_DAMAGE("a step count that is too large", replace_value(s, b_line, 3u, steps_plus_one, &len));
    DF_DAMAGE("a value above 2**32 - 1 (the tape offset of the first step)", replace_value(s, s_line, 3u, "4294967296", &len));
    DF_DAMAGE("a tape offset that is not the draws before the step", replace_value(s, s_line, 3u, "1", &len));
    DF_DAMAGE("a value above 255 in a byte (the first pick)", replace_value(s, s_line, 8u, "256", &len));
    DF_DAMAGE("a missing value (the last of the step)", splice(s, last_value - 1u, value_len(s, last_value) + 1u, "", &len));
#undef DF_DAMAGE
    for (size_t i = 0u; i < n; ++i) {
        const dfr_status st = read_text(bad[i].text, bad[i].len, error, sizeof error, &then_eof);
        if (!DF_CHECK(t, st == DFR_MALFORMED && strncmp(error, "line ", 5u) == 0)) {
            fprintf(stderr, "  the reader accepts %s (status %u)\n", bad[i].what, (unsigned)st);
        }
        free(bad[i].text);
    }
}
#endif

int main(int argc, char **argv)
{
    df_test t;
    df_test_begin(&t, DF_TEST_NAME);
    if (argc != 2) {
        fprintf(stderr, "usage: %s <records file>\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (f == NULL) {
        fprintf(stderr, "%s: cannot open %s (duoforge.reference.records_write writes it)\n", DF_TEST_NAME, argv[1]);
        return 2;
    }
    dfr_reader reader;
    dfr_reader_init(&reader, f);
    uint32_t tape_base = 0u;
    uint32_t ev_base = 0u;
    size_t seen = 0u;
    bool controlled = false;
    for (;;) {
        dfr_battle b;
        const dfr_status st = dfr_read_battle(&reader, &b);
        if (st == DFR_EOF) {
            break;
        }
        if (!DF_CHECK(&t, st == DFR_OK)) {
            fprintf(stderr, "  %s: %s\n", argv[1], reader.error);
            break;
        }
        if (!DF_CHECK(&t, seen < DF_N_BATTLES)) {
            fprintf(stderr, "  %s holds more battles than the tables (%u)\n", argv[1], (unsigned)DF_N_BATTLES);
            dfr_battle_free(&b);
            break;
        }
        const df_conf_battle *w = &conf_battles[seen];
        DF_CHECK_EQ_U64(&t, compare_battle(&b, w, tape_base, ev_base, true), 0u);
        if (!controlled && b.step_count >= 2u && b.tape_count > 0u && b.event_count > 0u) {
            negative_controls(&t, &b, w, tape_base, ev_base);
            controlled = true;
        }
        tape_base += b.tape_count;
        ev_base += b.event_count;
        ++seen;
        dfr_battle_free(&b);
    }
    dfr_reader_destroy(&reader);
    (void)fclose(f);
    DF_CHECK_EQ_U64(&t, seen, DF_N_BATTLES);
    DF_CHECK_EQ_U64(&t, tape_base, DF_N_TAPE);
    DF_CHECK_EQ_U64(&t, ev_base, DF_N_EVENTS);
    DF_CHECK(&t, controlled);
#ifndef DF_CONFORMANCE_TEAM_C
    char *text = slurp(argv[1]);
    if (DF_CHECK(&t, text != NULL)) {
        const char *end = strstr(text, "\nEND\n");
        if (DF_CHECK(&t, end != NULL)) {
            const sample first = {text, (size_t)(end - text) + 5u};
            refuse_damaged_copies(&t, &first);
        }
        free(text);
    }
#endif
    fprintf(stderr, "  %u battles, %u draws, %u events\n", (unsigned)seen, (unsigned)tape_base, (unsigned)ev_base);
    return df_test_end(&t);
}
