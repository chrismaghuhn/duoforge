/*
 * duoforge_diff_runner: the engine half of the differential loop
 * (docs/research/expansion/differential-testing.md, component 3). White-box,
 * like the conformance test it generalises: it replays battles the Python
 * side converted from reference traces (tools/reference/conformance_records.py)
 * and compares the engine with what the pinned Showdown did.
 *
 * usage: duoforge_diff_runner [records file]
 *
 * The records come from the file, or from stdin: any number of battles (the
 * format is in records.h). Each battle is set up and stepped exactly as
 * tests/test_conformance.c does it: closure battles under CLOSURE, then
 * CLOSURE_DEV when that cannot create them; Team C battles under TEAM_C, then
 * TEAM_C_DEV. A battle whose record names a data kind (random play) is created
 * under that kind alone: a team the kind rejects is a finding, not a
 * fallback. Every step takes the reference's kept draws as its tape, which
 * must be consumed exactly, and then the engine's state, observations and
 * events are compared with the reference's (tests/support/conformance_compare.c)
 * and duoforge_battle_check must hold. The first step with a difference ends
 * the battle.
 *
 * The domain check (random play): a battle may hold samples, each the set of
 * choices that the reference accepted from a side before a step. Before that
 * step is applied the engine's candidates for the side are compared with the
 * set (domain.h); any difference ends the battle there as a DIVERGENCE
 *
 *   domain: engine-only N, reference-only M (step K side S)
 *
 * with up to three examples of each kind in the messages. A candidates call
 * that fails is a finding too (UNSUPPORTED for DUOFORGE_E_UNSUPPORTED).
 *
 * stdout: the messages of the comparators (and of this file), indented two
 * spaces, then one line per battle, flushed:
 *
 *   R <name> <PASS|DIVERGENCE|UNSUPPORTED> <context kind> <step|-> <steps> <detail>
 *
 * The context kind is the data kind the battle ran under (CLOSURE,
 * CLOSURE_DEV, TEAM_C or TEAM_C_DEV). The step is the first failing one, or -
 * when no step failed (a PASS, or a battle that could not be created); steps
 * is the number of steps the records hold; the detail is the rest of the line
 * (- for a PASS). A create that fails says "create: <status> (<kind>)" and,
 * after the DEV fallback, "create: <status> (<kind>), <status> (<kind>)": both
 * attempts, the first context's and then the DEV context's.
 *   UNSUPPORTED: the create (after the DEV fallback) or a step returned
 *                DUOFORGE_E_UNSUPPORTED.
 *   DIVERGENCE:  any other create or step failure, a tape that was not
 *                consumed exactly, a difference of a comparator, or a
 *                failing duoforge_battle_check.
 *
 * Exit status: 0 at the end of the input, 2 for input that is not the format
 * (a bug of the tool that wrote it: the message on stderr names the line),
 * 1 for any other failure (a file that cannot be read, memory, a context).
 * Heap allocation is fine here: this is a tool, not the engine.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "data/closure_tables.h"
#include "data/extended_tables.h"
#include "domain.h"
#include "records.h"
#include "state/battle_internal.h"
#include "state/request.h"
#include "support/conformance_compare.h"
#include "support/fixtures.h"
#include "support/team_c.h"

#define EXIT_MALFORMED 2

typedef enum verdict { VERDICT_PASS, VERDICT_DIVERGENCE, VERDICT_UNSUPPORTED } verdict;

static const char *const VERDICT_NAME[] = {"PASS", "DIVERGENCE", "UNSUPPORTED"};

typedef struct outcome {
    verdict verdict;
    uint32_t data_kind; /* the context the battle ran under */
    bool has_step;
    uint32_t step;
    char detail[200];
} outcome;

static const char *kind_name(uint32_t data_kind)
{
    switch (data_kind) {
    case DUOFORGE_DATA_KIND_CLOSURE:
        return "CLOSURE";
    case DUOFORGE_DATA_KIND_CLOSURE_DEV:
        return "CLOSURE_DEV";
    case DUOFORGE_DATA_KIND_TEAM_C:
        return "TEAM_C";
    case DUOFORGE_DATA_KIND_TEAM_C_DEV:
        return "TEAM_C_DEV";
    default:
        return "UNKNOWN";
    }
}

/* As build_setup of tests/test_conformance.c. */
static void build_setup(const dfr_battle *b, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        s->sides[side].member_count = b->member_count;
        for (uint32_t m = 0u; m < b->member_count; ++m) {
            const df_conf_member *src = &b->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0u; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0u; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

/* The decision bundle of a step: the commands the reference's players chose, as the conformance test builds it. */
static void build_bundle(const duoforge_battle *battle, const df_conf_step *st, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = battle->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0u; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = battle->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0u; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0u; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve,
                                                      {0u, 0u, 0u}};
            }
        }
    }
}

static void set_detail(outcome *o, verdict v, const char *text)
{
    o->verdict = v;
    (void)snprintf(o->detail, sizeof o->detail, "%s", text);
}

/* The tape of a step as the message says it: how many entries the engine took of how many there are. */
static void tape_text(char *out, size_t cap, uint32_t used, uint32_t len)
{
    if (used == 0xFFFFFFFFu) {
        /* The engine reports the count only once it has checked the bundle. */
        (void)snprintf(out, cap, "tape n/a of %u", (unsigned)len);
    } else {
        (void)snprintf(out, cap, "tape %u of %u", (unsigned)used, (unsigned)len);
    }
}

/* The domain sample `d` of a battle, before its step is applied: the engine's candidates for the side against the
 * choices that the reference accepted. True when they are the same set; else the outcome says how they differ, and
 * the messages (up to DFD_EXAMPLES of each kind) are written to `out` as the comparators write theirs. */
static bool domain_agrees(const dfr_battle *b, const dfr_domain *d, const duoforge_context *ctx,
                          const duoforge_battle *battle, outcome *o, FILE *out)
{
    static duoforge_side_choice candidates[DUOFORGE_MAX_CANDIDATES];
    static dfr_choice engine[DUOFORGE_MAX_CANDIDATES];
    char text[200];
    uint32_t count = 0u;
    const duoforge_status status =
        duoforge_battle_candidates(ctx, battle, d->side, candidates, DUOFORGE_MAX_CANDIDATES, &count);
    if (status != DUOFORGE_OK || count > DUOFORGE_MAX_CANDIDATES) {
        (void)snprintf(text, sizeof text, "domain: candidates: %s (step %u side %u)", duoforge_status_name(status),
                       (unsigned)d->step, (unsigned)d->side);
        fprintf(out, "  %s step %u: domain side %u: the engine's candidates: %s\n", b->name, (unsigned)d->step,
                (unsigned)d->side, duoforge_status_name(status));
        o->has_step = true;
        o->step = d->step;
        set_detail(o, status == DUOFORGE_E_UNSUPPORTED ? VERDICT_UNSUPPORTED : VERDICT_DIVERGENCE, text);
        return false;
    }
    for (uint32_t i = 0u; i < count; ++i) {
        engine[i] = dfd_choice_of(&candidates[i]);
    }
    dfd_diff diff;
    dfd_compare(engine, count, &b->choices[d->choice_off], d->choice_count, &diff);
    if (diff.engine_only == 0u && diff.reference_only == 0u) {
        return true;
    }
    for (uint32_t k = 0u; k < diff.engine_only && k < DFD_EXAMPLES; ++k) {
        dfd_format(&diff.engine_examples[k], text, sizeof text);
        fprintf(out, "  %s step %u: domain side %u engine-only: %s\n", b->name, (unsigned)d->step, (unsigned)d->side,
                text);
    }
    for (uint32_t k = 0u; k < diff.reference_only && k < DFD_EXAMPLES; ++k) {
        dfd_format(&diff.reference_examples[k], text, sizeof text);
        fprintf(out, "  %s step %u: domain side %u reference-only: %s\n", b->name, (unsigned)d->step,
                (unsigned)d->side, text);
    }
    (void)snprintf(text, sizeof text, "domain: engine-only %u, reference-only %u (step %u side %u)",
                   (unsigned)diff.engine_only, (unsigned)diff.reference_only, (unsigned)d->step, (unsigned)d->side);
    o->has_step = true;
    o->step = d->step;
    set_detail(o, VERDICT_DIVERGENCE, text);
    return false;
}

/* One battle. contexts[0] is CLOSURE or TEAM_C, contexts[1] the DEV context of the same data. A battle with a
 * strict kind is created under that context alone; any other first under contexts[0], and under contexts[1] when
 * that cannot create it, as tests/test_conformance.c does. */
static outcome run_battle(const dfr_battle *b, duoforge_context *const contexts[2],
                          const duoforge_context_config *const configs[2], FILE *out)
{
    outcome o;
    memset(&o, 0, sizeof o);
    set_detail(&o, VERDICT_PASS, "-");

    duoforge_battle_setup setup;
    build_setup(b, &setup);
    duoforge_battle *battle = NULL;
    const bool strict = b->strict_kind != 0u;
    size_t first = 0u;
    if (strict && b->strict_kind == configs[1]->data_kind) {
        first = 1u;
    }
    const duoforge_context *ctx = contexts[first];
    o.data_kind = configs[first]->data_kind;
    duoforge_status created = duoforge_battle_create(ctx, &setup, &battle);
    duoforge_status first_created = created;
    if (created != DUOFORGE_OK && !strict) {
        ctx = contexts[1];
        o.data_kind = configs[1]->data_kind;
        battle = NULL;
        created = duoforge_battle_create(ctx, &setup, &battle);
    }
    if (created != DUOFORGE_OK || battle == NULL) {
        char text[160];
        if (strict) {
            (void)snprintf(text, sizeof text, "create: %s (%s)", duoforge_status_name(created),
                           kind_name(o.data_kind));
        } else {
            /* Both attempts: the first context's status, then the DEV context's. */
            (void)snprintf(text, sizeof text, "create: %s (%s), %s (%s)", duoforge_status_name(first_created),
                           kind_name(configs[0]->data_kind), duoforge_status_name(created), kind_name(o.data_kind));
        }
        if (created == DUOFORGE_OK) {
            (void)snprintf(text, sizeof text, "create: no battle handle (%s)", kind_name(o.data_kind));
        }
        set_detail(&o, created == DUOFORGE_E_UNSUPPORTED ? VERDICT_UNSUPPORTED : VERDICT_DIVERGENCE, text);
        return o;
    }

    /* The view the comparators take: the battle as the compiled tables hold it. */
    const df_conf_battle cb = {b->name, b->member_count, b->members, b->steps, b->step_count, b->dropped_total};
    const dfi_forme_data *formes = b->team_c != 0u ? dfi_ext_formes : dfi_closure_formes;
    /* Event differences written so far; the comparator stops at its cap per run. */
    unsigned event_reports = 0u;
    uint32_t next_domain = 0u; /* the samples come in the order of the steps */
    for (uint32_t si = 0u; si < b->step_count; ++si) {
        const df_conf_step *st = &b->steps[si];
        /* What the reference accepted before this step, against what the engine offers now. */
        bool domain_ok = true;
        while (domain_ok && next_domain < b->domain_count && b->domains[next_domain].step == si) {
            domain_ok = domain_agrees(b, &b->domains[next_domain], ctx, battle, &o, out);
            ++next_domain;
        }
        if (!domain_ok) {
            break;
        }
        duoforge_decision_bundle bd;
        build_bundle(battle, st, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
        duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u}, {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
        const duoforge_status status =
            dfi_battle_step_events_tape(ctx, battle, &bd, &b->tape[st->tape_off], st->tape_len, &used, &res, buffers);
        const bool consumed = used == st->tape_len;
        if (status != DUOFORGE_OK || !consumed) {
            char tape[64];
            char text[160];
            tape_text(tape, sizeof tape, used, st->tape_len);
            o.has_step = true;
            o.step = si;
            if (status != DUOFORGE_OK) {
                (void)snprintf(text, sizeof text, "step: %s, %s", duoforge_status_name(status), tape);
                fprintf(out, "  %s step %u: %s, %s\n", b->name, (unsigned)si, duoforge_status_name(status), tape);
                set_detail(&o, status == DUOFORGE_E_UNSUPPORTED ? VERDICT_UNSUPPORTED : VERDICT_DIVERGENCE, text);
            } else {
                (void)snprintf(text, sizeof text, "step: the tape is not consumed exactly, %s", tape);
                fprintf(out, "  %s step %u: the tape is not consumed exactly, %s\n", b->name, (unsigned)si, tape);
                set_detail(&o, VERDICT_DIVERGENCE, text);
            }
            break;
        }
        const unsigned state_bad = df_conf_compare_state(out, ctx, battle, st, b->name, si);
        const unsigned observation_bad = df_conf_compare_observation(out, ctx, battle, st, &cb, si, formes);
        const unsigned events_bad = df_conf_compare_events(out, st, b->name, si, buffers, b->events, &event_reports);
        const duoforge_status check = duoforge_battle_check(ctx, battle);
        if (check != DUOFORGE_OK) {
            fprintf(out, "  %s step %u: duoforge_battle_check: %s\n", b->name, (unsigned)si, duoforge_status_name(check));
        }
        if (state_bad + observation_bad + events_bad != 0u || check != DUOFORGE_OK) {
            char text[160];
            (void)snprintf(text, sizeof text, "differences: state %u, observation %u, events %u, battle_check %s",
                           state_bad, observation_bad, events_bad, duoforge_status_name(check));
            o.has_step = true;
            o.step = si;
            set_detail(&o, VERDICT_DIVERGENCE, text);
            break;
        }
    }
    duoforge_battle_destroy(battle);
    return o;
}

static void print_result(const dfr_battle *b, const outcome *o)
{
    printf("R %s %s %s ", b->name, VERDICT_NAME[o->verdict], kind_name(o->data_kind));
    if (o->has_step) {
        printf("%u", (unsigned)o->step);
    } else {
        printf("-");
    }
    printf(" %u %s\n", (unsigned)b->step_count, o->detail);
}

int main(int argc, char **argv)
{
    if (argc > 2) {
        fputs("usage: duoforge_diff_runner [records file]\n", stderr);
        return 2;
    }
#ifdef _WIN32
    /* LF line ends in both directions, and no Ctrl-Z as end of input. */
    (void)_setmode(_fileno(stdin), _O_BINARY);
    (void)_setmode(_fileno(stdout), _O_BINARY);
#endif
    FILE *in = stdin;
    if (argc == 2) {
        in = fopen(argv[1], "rb");
        if (in == NULL) {
            fprintf(stderr, "duoforge_diff_runner: cannot open %s\n", argv[1]);
            return 1;
        }
    }

    /* [0] closure, [1] Team C; in each the first context, then the DEV one. */
    static const duoforge_context_config *const configs[2][2] = {{&df_config_k1, &df_config_k2},
                                                                 {&df_config_team_c, &df_config_team_c_dev}};
    duoforge_context *contexts[2][2] = {{NULL, NULL}, {NULL, NULL}};
    int rc = 0;
    for (size_t kind = 0u; kind < 2u && rc == 0; ++kind) {
        for (size_t dev = 0u; dev < 2u && rc == 0; ++dev) {
            const duoforge_status s = duoforge_context_create(configs[kind][dev], &contexts[kind][dev]);
            if (s != DUOFORGE_OK) {
                fprintf(stderr, "duoforge_diff_runner: no %s context: %s\n", kind_name(configs[kind][dev]->data_kind),
                        duoforge_status_name(s));
                rc = 1;
            }
        }
    }

    dfr_reader reader;
    dfr_reader_init(&reader, in);
    while (rc == 0) {
        dfr_battle battle;
        const dfr_status st = dfr_read_battle(&reader, &battle);
        if (st == DFR_EOF) {
            break;
        }
        if (st != DFR_OK) {
            if (st == DFR_MALFORMED) {
                fprintf(stderr, "duoforge_diff_runner: malformed input: %s\n", reader.error);
                rc = EXIT_MALFORMED;
            } else {
                fprintf(stderr, "duoforge_diff_runner: cannot read the input: %s\n",
                        st == DFR_OUT_OF_MEMORY ? "out of memory" : "read error");
                rc = 1;
            }
            break;
        }
        const size_t kind = battle.team_c != 0u ? 1u : 0u;
        const outcome o = run_battle(&battle, contexts[kind], configs[kind], stdout);
        print_result(&battle, &o);
        dfr_battle_free(&battle);
        if (fflush(stdout) != 0) {
            fprintf(stderr, "duoforge_diff_runner: cannot write the output\n");
            rc = 1;
        }
    }

    dfr_reader_destroy(&reader);
    if (in != stdin) {
        (void)fclose(in);
    }
    for (size_t kind = 0u; kind < 2u; ++kind) {
        for (size_t dev = 0u; dev < 2u; ++dev) {
            duoforge_context_destroy(contexts[kind][dev]);
        }
    }
    return rc;
}
