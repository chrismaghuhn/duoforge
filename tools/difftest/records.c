/*
 * Reader of the battle records of tools/reference/conformance_records.py
 * (see records.h). Every value is read into a field of a df_conf_* type or of
 * a duoforge_event, in the order of its declaration; the sync test
 * (tests/test_runner_records.c) compares the result with the compiled tables.
 */
#include "records.h"

#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

/* The reader follows these declarations field by field. A record type that
 * changes (a field added, a size changed) must change here with it: the
 * build stops instead of reading the records in a stale order. */
_Static_assert(sizeof(df_conf_member) == 64u, "df_conf_member changed: update tools/difftest/records.c");
_Static_assert(sizeof(df_conf_cmd) == 5u, "df_conf_cmd changed: update tools/difftest/records.c");
_Static_assert(sizeof(df_conf_mon) == 32u, "df_conf_mon changed: update tools/difftest/records.c");
_Static_assert(sizeof(df_conf_step) == 488u, "df_conf_step changed: update tools/difftest/records.c");
_Static_assert(sizeof(dfi_tape_entry) == 16u, "dfi_tape_entry changed: update tools/difftest/records.c");
_Static_assert(sizeof(duoforge_event) == 20u, "duoforge_event changed: update tools/difftest/records.c");
/* dfr_choice is compared and ordered by memcmp: it must have no padding. */
_Static_assert(sizeof(dfr_choice) == 2u + DUOFORGE_MAX_ROSTER + DUOFORGE_ACTIVE_PER_SIDE * sizeof(df_conf_cmd),
               "dfr_choice has padding or changed: update tools/difftest/records.c");

#define DFR_COUNT(a) (sizeof(a) / sizeof((a)[0]))

#if defined(__GNUC__) || defined(__clang__)
#define DFR_PRINTF(fmt, args) __attribute__((format(printf, fmt, args)))
#else
#define DFR_PRINTF(fmt, args)
#endif

typedef struct dfr_cursor {
    dfr_reader *r;
    const char *p;   /* the next value, or end */
    const char *end; /* the end of the line */
    char tag;        /* the record being read, for the messages */
    unsigned index;  /* the values read from this line, for the messages */
} dfr_cursor;

static void fail(dfr_reader *r, const char *fmt, ...) DFR_PRINTF(2, 3);
static void fail(dfr_reader *r, const char *fmt, ...)
{
    char text[200];
    va_list ap;
    va_start(ap, fmt);
    (void)vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    (void)snprintf(r->error, sizeof r->error, "line %u: %s", (unsigned)r->line_no, text);
}

void dfr_reader_init(dfr_reader *r, FILE *file)
{
    memset(r, 0, sizeof *r);
    r->file = file;
}

void dfr_reader_init_memory(dfr_reader *r, const char *data, size_t len)
{
    memset(r, 0, sizeof *r);
    r->mem = data;
    r->mem_len = len;
}

void dfr_reader_destroy(dfr_reader *r)
{
    free(r->line);
    memset(r, 0, sizeof *r);
}

void dfr_battle_free(dfr_battle *b)
{
    free(b->steps);
    free(b->tape);
    free(b->events);
    free(b->domains);
    free(b->choices);
    memset(b, 0, sizeof *b);
}

static int next_char(dfr_reader *r)
{
    if (r->file != NULL) {
        return getc(r->file);
    }
    if (r->mem_pos < r->mem_len) {
        return (unsigned char)r->mem[r->mem_pos++];
    }
    return EOF;
}

/* The next line into r->line. DFR_EOF only when the input ends before the
 * first character of a line. */
static dfr_status read_line(dfr_reader *r)
{
    if (r->line == NULL) {
        r->line_cap = 256u;
        r->line = malloc(r->line_cap);
        if (r->line == NULL) {
            return DFR_OUT_OF_MEMORY;
        }
    }
    size_t len = 0u;
    for (;;) {
        const int ch = next_char(r);
        if (len == 0u && ch != EOF) {
            r->line_no += 1u;
        }
        if (ch == EOF) {
            if (r->file != NULL && ferror(r->file)) {
                return DFR_IO;
            }
            if (len == 0u) {
                return DFR_EOF;
            }
            fail(r, "the input ends without a line end");
            return DFR_MALFORMED;
        }
        if (ch == '\n') {
            break;
        }
        if (ch < 0x20 || ch > 0x7E) {
            fail(r, "character 0x%02x is not printable ASCII", (unsigned)ch);
            return DFR_MALFORMED;
        }
        if (len + 2u > r->line_cap) {
            char *bigger = realloc(r->line, r->line_cap * 2u);
            if (bigger == NULL) {
                return DFR_OUT_OF_MEMORY;
            }
            r->line = bigger;
            r->line_cap *= 2u;
        }
        r->line[len++] = (char)ch;
    }
    r->line[len] = '\0';
    r->line_len = len;
    return DFR_OK;
}

/* 0, or a data kind of the tables the battle was converted with (duoforge.h). */
static bool kind_goes_with(uint32_t team_c, uint32_t kind)
{
    if (kind == 0u) {
        return true;
    }
    if (team_c == 0u) {
        return kind == DUOFORGE_DATA_KIND_CLOSURE || kind == DUOFORGE_DATA_KIND_CLOSURE_DEV;
    }
    return kind == DUOFORGE_DATA_KIND_TEAM_C || kind == DUOFORGE_DATA_KIND_TEAM_C_DEV;
}

/* The next line, where the input must not end: `what` names what is expected. */
static dfr_status next_line(dfr_reader *r, const char *what)
{
    const dfr_status st = read_line(r);
    if (st == DFR_EOF) {
        fail(r, "the input ends where %s is expected", what);
        return DFR_MALFORMED;
    }
    return st;
}

/* Starts reading the current line as a record of kind `tag`: "T value value...". */
static bool open_record(dfr_reader *r, dfr_cursor *c, char tag)
{
    if (r->line_len < 2u || r->line[0] != tag || r->line[1] != ' ') {
        fail(r, "a '%c' record is expected, found \"%.24s\"", tag, r->line);
        return false;
    }
    c->r = r;
    c->p = r->line + 2;
    c->end = r->line + r->line_len;
    c->tag = tag;
    c->index = 0u;
    return true;
}

static bool close_record(const dfr_cursor *c)
{
    if (c->p != c->end) {
        fail(c->r, "record %c: text after value %u", c->tag, c->index);
        return false;
    }
    return true;
}

/* The next line, as a record of kind `tag`. */
static dfr_status next_record(dfr_reader *r, dfr_cursor *c, char tag)
{
    char what[16];
    (void)snprintf(what, sizeof what, "a '%c' record", tag);
    const dfr_status st = next_line(r, what);
    if (st != DFR_OK) {
        return st;
    }
    return open_record(r, c, tag) ? DFR_OK : DFR_MALFORMED;
}

/* After a token that ends at q: the end of the line, or one space and more. */
static bool skip_separator(dfr_cursor *c, const char *q)
{
    if (q == c->end) {
        c->p = q;
        return true;
    }
    if (*q != ' ') {
        fail(c->r, "record %c, value %u: a space is expected after it", c->tag, c->index);
        return false;
    }
    if (q + 1 == c->end) {
        fail(c->r, "record %c, value %u: a space ends the line", c->tag, c->index);
        return false;
    }
    c->p = q + 1;
    return true;
}

/* An unsigned decimal number: digits only, no leading zero, at most max. */
static bool get_uint(dfr_cursor *c, uint32_t max, uint32_t *out)
{
    c->index += 1u;
    const char *q = c->p;
    if (q >= c->end || *q < '0' || *q > '9') {
        fail(c->r, "record %c, value %u: a decimal number is expected", c->tag, c->index);
        return false;
    }
    uint64_t v = 0u;
    while (q < c->end && *q >= '0' && *q <= '9') {
        v = v * 10u + (uint64_t)(*q - '0');
        if (v > max) {
            fail(c->r, "record %c, value %u: more than %u", c->tag, c->index, (unsigned)max);
            return false;
        }
        ++q;
    }
    if (q - c->p > 1 && *c->p == '0') {
        fail(c->r, "record %c, value %u: a leading zero", c->tag, c->index);
        return false;
    }
    if (!skip_separator(c, q)) {
        return false;
    }
    *out = (uint32_t)v;
    return true;
}

/* A battle name: [A-Za-z0-9_]{1,DFR_NAME_MAX}. */
static bool get_name(dfr_cursor *c, char *out)
{
    c->index += 1u;
    const char *q = c->p;
    while (q < c->end &&
           ((*q >= '0' && *q <= '9') || (*q >= 'A' && *q <= 'Z') || (*q >= 'a' && *q <= 'z') || *q == '_')) {
        ++q;
    }
    const size_t n = (size_t)(q - c->p);
    if (n == 0u || n > DFR_NAME_MAX) {
        fail(c->r, "record %c, value %u: a name of 1 to %u letters, digits and underscores is expected", c->tag,
             c->index, (unsigned)DFR_NAME_MAX);
        return false;
    }
    memcpy(out, c->p, n);
    out[n] = '\0';
    return skip_separator(c, q);
}

static bool rd_u32(dfr_cursor *c, uint32_t *out)
{
    return get_uint(c, UINT32_MAX, out);
}

static bool rd_u16(dfr_cursor *c, uint16_t *out)
{
    uint32_t v = 0u;
    if (!get_uint(c, UINT16_MAX, &v)) {
        return false;
    }
    *out = (uint16_t)v;
    return true;
}

static bool rd_u8(dfr_cursor *c, uint8_t *out)
{
    uint32_t v = 0u;
    if (!get_uint(c, UINT8_MAX, &v)) {
        return false;
    }
    *out = (uint8_t)v;
    return true;
}

static bool rd_u32s(dfr_cursor *c, uint32_t *out, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        if (!rd_u32(c, &out[i])) {
            return false;
        }
    }
    return true;
}

static bool rd_u8s(dfr_cursor *c, uint8_t *out, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        if (!rd_u8(c, &out[i])) {
            return false;
        }
    }
    return true;
}

/* The fields of a record in declaration order, as the flattened tuples of
 * trace_to_c.py list them. */
static bool rd_member(dfr_cursor *c, df_conf_member *m)
{
    return rd_u32(c, &m->species) && rd_u32(c, &m->gender) && rd_u32(c, &m->nature) &&
           rd_u32s(c, m->sp, DFR_COUNT(m->sp)) && rd_u32(c, &m->ability) && rd_u32(c, &m->item) &&
           rd_u32(c, &m->move_count) && rd_u32s(c, m->moves, DFR_COUNT(m->moves));
}

static bool rd_cmd(dfr_cursor *c, df_conf_cmd *d)
{
    return rd_u8(c, &d->kind) && rd_u8(c, &d->move_slot) && rd_u8(c, &d->target) && rd_u8(c, &d->mega) &&
           rd_u8(c, &d->reserve);
}

static bool rd_mon(dfr_cursor *c, df_conf_mon *m)
{
    return rd_u32(c, &m->present) && rd_u32(c, &m->hp) && rd_u8s(c, m->pp, DFR_COUNT(m->pp)) &&
           rd_u8s(c, m->stages, DFR_COUNT(m->stages)) && rd_u8(c, &m->stall) && rd_u8(c, &m->fainted) &&
           rd_u8(c, &m->status) && rd_u8(c, &m->status_counter) && rd_u8(c, &m->confusion) &&
           rd_u8(c, &m->locked_slot) && rd_u8(c, &m->locked_target) && rd_u8(c, &m->mega) && rd_u8(c, &m->held) &&
           rd_u8(c, &m->seen) && rd_u8(c, &m->seen_percent) && rd_u8(c, &m->seen_flag) && rd_u8(c, &m->vols);
}

static bool rd_step(dfr_cursor *c, df_conf_step *s)
{
    if (!(rd_u32(c, &s->team) && rd_u32(c, &s->answered0) && rd_u32(c, &s->answered1) && rd_u32(c, &s->tape_off) &&
          rd_u32(c, &s->tape_len) && rd_u32(c, &s->turn) && rd_u32(c, &s->boundary) && rd_u32(c, &s->result))) {
        return false;
    }
    for (size_t side = 0u; side < DFR_COUNT(s->picks); ++side) {
        if (!rd_u8s(c, s->picks[side], DFR_COUNT(s->picks[side]))) {
            return false;
        }
    }
    for (size_t side = 0u; side < DFR_COUNT(s->cmds); ++side) {
        for (size_t k = 0u; k < DFR_COUNT(s->cmds[side]); ++k) {
            if (!rd_cmd(c, &s->cmds[side][k])) {
                return false;
            }
        }
    }
    for (size_t side = 0u; side < DFR_COUNT(s->occupants); ++side) {
        if (!rd_u8s(c, s->occupants[side], DFR_COUNT(s->occupants[side]))) {
            return false;
        }
    }
    if (!rd_u8s(c, s->entries, DFR_COUNT(s->entries)) || !rd_u8s(c, s->field, DFR_COUNT(s->field))) {
        return false;
    }
    for (size_t side = 0u; side < DFR_COUNT(s->enabled); ++side) {
        if (!rd_u8s(c, s->enabled[side], DFR_COUNT(s->enabled[side]))) {
            return false;
        }
    }
    for (size_t side = 0u; side < DFR_COUNT(s->mons); ++side) {
        for (size_t m = 0u; m < DFR_COUNT(s->mons[side]); ++m) {
            if (!rd_mon(c, &s->mons[side][m])) {
                return false;
            }
        }
    }
    return rd_u32s(c, s->ev_off, DFR_COUNT(s->ev_off)) && rd_u32s(c, s->ev_len, DFR_COUNT(s->ev_len));
}

static bool rd_tape(dfr_cursor *c, dfi_tape_entry *e)
{
    return rd_u32(c, &e->site) && rd_u32(c, &e->lo) && rd_u32(c, &e->hi) && rd_u32(c, &e->value);
}

static bool rd_event(dfr_cursor *c, duoforge_event *e)
{
    return rd_u8(c, &e->kind) && rd_u8(c, &e->position) && rd_u8(c, &e->other) && rd_u8(c, &e->cause) &&
           rd_u16(c, &e->id) && rd_u16(c, &e->id2) && rd_u16(c, &e->hp) && rd_u16(c, &e->hp_max) &&
           rd_u8(c, &e->hp_kind) && rd_u8(c, &e->hp_flag) && rd_u8(c, &e->status) && rd_u8(c, &e->detail) &&
           rd_u8(c, &e->amount) && rd_u8(c, &e->flags);
}

/* "C kind pick_count picks[6] slot[0] slot[1]": the 18 values of a dfr_choice in order. */
static bool rd_choice(dfr_cursor *c, dfr_choice *ch)
{
    if (!(rd_u8(c, &ch->kind) && rd_u8(c, &ch->pick_count) && rd_u8s(c, ch->picks, DFR_COUNT(ch->picks)))) {
        return false;
    }
    for (size_t k = 0u; k < DFR_COUNT(ch->slots); ++k) {
        if (!rd_cmd(c, &ch->slots[k])) {
            return false;
        }
    }
    return true;
}

/* A slot command that a duoforge_slot_command can hold: the fields that its kind does not use are zero. */
static bool command_fits(dfr_reader *r, const df_conf_cmd *c, uint32_t member_count)
{
    switch (c->kind) {
    case DUOFORGE_SLOT_NONE:
    case DUOFORGE_SLOT_PASS:
        if (c->move_slot != 0u || c->target != 0u || c->mega != 0u || c->reserve != 0u) {
            fail(r, "record C: a slot command of kind %u with other fields than its kind", (unsigned)c->kind);
            return false;
        }
        return true;
    case DUOFORGE_SLOT_MOVE:
        if (c->move_slot > DUOFORGE_MOVE_SLOT_STRUGGLE || (c->target > 3u && c->target != DUOFORGE_TARGET_NONE) ||
            c->mega > 1u || c->reserve != 0u) {
            fail(r, "record C: a move command (slot %u, target %u, mega %u, reserve %u) outside the domain of one",
                 (unsigned)c->move_slot, (unsigned)c->target, (unsigned)c->mega, (unsigned)c->reserve);
            return false;
        }
        return true;
    case DUOFORGE_SLOT_SWITCH:
        if (c->move_slot != 0u || c->target != 0u || c->mega != 0u || c->reserve >= member_count) {
            fail(r, "record C: a switch command with the reserve %u of %u members or with other fields than a switch",
                 (unsigned)c->reserve, (unsigned)member_count);
            return false;
        }
        return true;
    default:
        fail(r, "record C: slot command kind %u is not 0 to 3", (unsigned)c->kind);
        return false;
    }
}

/* A choice that a duoforge_side_choice can hold (the engine's candidates are such choices), by its kind. */
static bool choice_fits(dfr_reader *r, const dfr_choice *ch, uint32_t member_count)
{
    dfr_choice zero;
    memset(&zero, 0, sizeof zero);
    if (ch->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        if (ch->pick_count == 0u || ch->pick_count > member_count) {
            fail(r, "record C: %u picks of a side of %u members", (unsigned)ch->pick_count, (unsigned)member_count);
            return false;
        }
        for (uint32_t i = 0u; i < DFR_COUNT(ch->picks); ++i) {
            if (i >= ch->pick_count) {
                if (ch->picks[i] != 0u) {
                    fail(r, "record C: a pick beyond the %u picks", (unsigned)ch->pick_count);
                    return false;
                }
                continue;
            }
            if (ch->picks[i] >= member_count) {
                fail(r, "record C: pick %u is the roster index %u of a side of %u members", (unsigned)i,
                     (unsigned)ch->picks[i], (unsigned)member_count);
                return false;
            }
            for (uint32_t j = 0u; j < i; ++j) {
                if (ch->picks[j] == ch->picks[i]) {
                    fail(r, "record C: the roster index %u is picked twice", (unsigned)ch->picks[i]);
                    return false;
                }
            }
        }
        if (memcmp(ch->slots, zero.slots, sizeof ch->slots) != 0) {
            fail(r, "record C: slot commands in a team choice");
            return false;
        }
        return true;
    }
    if (ch->kind != DUOFORGE_CHOICE_SLOTS) {
        fail(r, "record C: choice kind %u is not %u (team) or %u (slots)", (unsigned)ch->kind,
             (unsigned)DUOFORGE_CHOICE_TEAM_SELECTION, (unsigned)DUOFORGE_CHOICE_SLOTS);
        return false;
    }
    if (ch->pick_count != 0u || memcmp(ch->picks, zero.picks, sizeof ch->picks) != 0) {
        fail(r, "record C: picks in a slot choice");
        return false;
    }
    for (size_t k = 0u; k < DFR_COUNT(ch->slots); ++k) {
        if (!command_fits(r, &ch->slots[k], member_count)) {
            return false;
        }
    }
    return true;
}

/* The array `data` of `count` elements of `elem` bytes, with room for one
 * more (`cap` is its capacity); NULL when out of memory. */
static void *room_for_one_more(void *data, uint32_t count, uint32_t *cap, size_t elem)
{
    if (count < *cap) {
        return data;
    }
    if (*cap > UINT32_MAX / 2u || (size_t)*cap * 2u > SIZE_MAX / elem) {
        return NULL;
    }
    const uint32_t bigger = *cap == 0u ? 64u : *cap * 2u;
    void *p = realloc(data, (size_t)bigger * elem);
    if (p != NULL) {
        *cap = bigger;
    }
    return p;
}

#define DFR_TRY(expr)               \
    do {                            \
        status = (expr);            \
        if (status != DFR_OK) {     \
            goto done;              \
        }                           \
    } while (0)

/* A read or a check that failed has set the message: it is DFR_MALFORMED. */
#define DFR_NEED(cond)              \
    do {                            \
        if (!(cond)) {              \
            status = DFR_MALFORMED; \
            goto done;              \
        }                           \
    } while (0)

/* A new zeroed element at the end of the array `arr` of `count` elements: `out` points to it. */
#define DFR_APPEND(arr, count, cap, out)                                                \
    do {                                                                                \
        void *grown_ = room_for_one_more((arr), (count), &(cap), sizeof *(arr));        \
        if (grown_ == NULL) {                                                           \
            status = DFR_OUT_OF_MEMORY;                                                 \
            goto done;                                                                  \
        }                                                                               \
        (arr) = grown_;                                                                 \
        (out) = &(arr)[(count)];                                                        \
        memset((out), 0, sizeof *(out));                                                \
        (count) += 1u;                                                                  \
    } while (0)

dfr_status dfr_read_battle(dfr_reader *r, dfr_battle *b)
{
    memset(b, 0, sizeof *b);
    r->error[0] = '\0';
    dfr_status status = read_line(r);
    if (status != DFR_OK) {
        return status; /* DFR_EOF between battles, or a failure */
    }
    dfr_cursor c = {NULL, NULL, NULL, '\0', 0u};
    uint32_t steps_read = 0u;
    uint32_t steps_cap = 0u;
    uint32_t tape_cap = 0u;
    uint32_t events_cap = 0u;
    uint32_t domains_read = 0u;
    uint32_t domains_cap = 0u;
    uint32_t choices_cap = 0u;

    DFR_NEED(open_record(r, &c, 'B'));
    DFR_NEED(get_name(&c, b->name) && get_uint(&c, 1u, &b->team_c) && rd_u32(&c, &b->strict_kind) &&
             get_uint(&c, 6u, &b->member_count) && rd_u32(&c, &b->step_count) && rd_u32(&c, &b->dropped_total) &&
             rd_u32(&c, &b->domain_count) && close_record(&c));
    if (b->member_count == 0u || b->step_count == 0u) {
        fail(r, "record B: a battle has at least one member and one step");
        status = DFR_MALFORMED;
        goto done;
    }
    if ((uint64_t)b->domain_count > 2u * (uint64_t)b->step_count) {
        fail(r, "record B: %u domain samples in %u steps (at most one per side and step)", (unsigned)b->domain_count,
             (unsigned)b->step_count);
        status = DFR_MALFORMED;
        goto done;
    }
    if (!kind_goes_with(b->team_c, b->strict_kind)) {
        fail(r, "record B: data kind %u does not go with team_c %u", (unsigned)b->strict_kind, (unsigned)b->team_c);
        status = DFR_MALFORMED;
        goto done;
    }

    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t index = 0u; index < b->member_count; ++index) {
            uint32_t got_side = 0u;
            uint32_t got_index = 0u;
            DFR_TRY(next_record(r, &c, 'M'));
            DFR_NEED(rd_u32(&c, &got_side) && rd_u32(&c, &got_index));
            if (got_side != side || got_index != index) {
                fail(r, "record M: member %u of side %u is expected, found %u of %u", (unsigned)index,
                     (unsigned)side, (unsigned)got_index, (unsigned)got_side);
                status = DFR_MALFORMED;
                goto done;
            }
            DFR_NEED(rd_member(&c, &b->members[side][index]) && close_record(&c));
        }
    }

    for (uint32_t i = 0u; i < b->step_count; ++i) {
        df_conf_step *st = NULL;
        DFR_APPEND(b->steps, steps_read, steps_cap, st);
        /* The domain samples of a step come before its S record, side 0 before side 1. */
        const uint32_t samples_before = domains_read;
        DFR_TRY(next_line(r, "a 'D' or an 'S' record"));
        while (r->line_len >= 2u && r->line[0] == 'D') {
            dfr_domain *d = NULL;
            if (domains_read == b->domain_count) {
                fail(r, "record D: record B names %u samples, there are more", (unsigned)b->domain_count);
                status = DFR_MALFORMED;
                goto done;
            }
            const bool second = domains_read > samples_before;
            const uint32_t previous_side = second ? b->domains[domains_read - 1u].side : 0u;
            DFR_APPEND(b->domains, domains_read, domains_cap, d);
            DFR_NEED(open_record(r, &c, 'D') && rd_u32(&c, &d->step) && get_uint(&c, 1u, &d->side) &&
                     get_uint(&c, DUOFORGE_MAX_CANDIDATES, &d->choice_count) && close_record(&c));
            if (d->step != i || d->choice_count == 0u || (second && d->side <= previous_side)) {
                fail(r, "record D: step %u side %u with %u choices where step %u%s is expected", (unsigned)d->step,
                     (unsigned)d->side, (unsigned)d->choice_count, (unsigned)i,
                     second ? " and the side after the one before" : "");
                status = DFR_MALFORMED;
                goto done;
            }
            d->choice_off = b->choice_count;
            for (uint32_t k = 0u; k < d->choice_count; ++k) {
                dfr_choice *ch = NULL;
                DFR_APPEND(b->choices, b->choice_count, choices_cap, ch);
                DFR_TRY(next_record(r, &c, 'C'));
                DFR_NEED(rd_choice(&c, ch) && close_record(&c) && choice_fits(r, ch, b->member_count));
                if (k > 0u && memcmp(ch - 1, ch, sizeof *ch) >= 0) {
                    fail(r, "record C: the choices of a sample are not strictly ascending");
                    status = DFR_MALFORMED;
                    goto done;
                }
            }
            DFR_TRY(next_line(r, "a 'D' or an 'S' record"));
        }
        DFR_NEED(open_record(r, &c, 'S'));
        DFR_NEED(rd_step(&c, st) && close_record(&c));
        for (uint32_t k = samples_before; k < domains_read; ++k) {
            if ((b->domains[k].side == 0u ? st->answered0 : st->answered1) == 0u) {
                fail(r, "record D: side %u is sampled before step %u, which it does not answer",
                     (unsigned)b->domains[k].side, (unsigned)i);
                status = DFR_MALFORMED;
                goto done;
            }
        }
        /* The slices of the step are the next lines: its offsets are the counts so far. */
        if (st->tape_off != b->tape_count || st->ev_off[0] != b->event_count ||
            (uint64_t)st->ev_off[1] != (uint64_t)st->ev_off[0] + st->ev_len[0]) {
            fail(r, "record S: the offsets (tape %u, events %u and %u) are not the %u draws and %u events before it",
                 (unsigned)st->tape_off, (unsigned)st->ev_off[0], (unsigned)st->ev_off[1],
                 (unsigned)b->tape_count, (unsigned)b->event_count);
            status = DFR_MALFORMED;
            goto done;
        }
        for (uint32_t k = 0u; k < st->tape_len; ++k) {
            dfi_tape_entry *e = NULL;
            DFR_APPEND(b->tape, b->tape_count, tape_cap, e);
            DFR_TRY(next_record(r, &c, 'T'));
            DFR_NEED(rd_tape(&c, e) && close_record(&c));
        }
        for (uint32_t p = 0u; p < 2u; ++p) {
            for (uint32_t k = 0u; k < st->ev_len[p]; ++k) {
                duoforge_event *e = NULL;
                DFR_APPEND(b->events, b->event_count, events_cap, e);
                DFR_TRY(next_record(r, &c, 'E'));
                DFR_NEED(rd_event(&c, e) && close_record(&c));
            }
        }
    }

    if (domains_read != b->domain_count) {
        fail(r, "record B names %u domain samples, the records hold %u", (unsigned)b->domain_count,
             (unsigned)domains_read);
        status = DFR_MALFORMED;
        goto done;
    }
    DFR_TRY(next_line(r, "END"));
    if (r->line_len != 3u || memcmp(r->line, "END", 3u) != 0) {
        fail(r, "END is expected after %u steps, found \"%.24s\"", (unsigned)b->step_count, r->line);
        status = DFR_MALFORMED;
        goto done;
    }
    /* The arrays are never NULL: see dfr_battle. */
    if (b->tape == NULL) {
        b->tape = calloc(1u, sizeof *b->tape);
    }
    if (b->events == NULL) {
        b->events = calloc(1u, sizeof *b->events);
    }
    if (b->tape == NULL || b->events == NULL) {
        status = DFR_OUT_OF_MEMORY;
    }

done:
    if (status != DFR_OK) {
        if (status == DFR_OUT_OF_MEMORY) {
            fail(r, "out of memory");
        }
        dfr_battle_free(b);
    }
    return status;
}
