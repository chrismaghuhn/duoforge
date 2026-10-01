/*
 * duoforge_bench: the benchmark driver (docs/decisions/0008). Records the
 * workload once, runs the selected families, and writes one JSON report
 * (manifest, results, what each side's policy chose); a short summary goes
 * to stderr. Exit 0 only when no family reported an error.
 *
 * usage: duoforge_bench [--battles N] [--repetitions R] [--warmup W]
 *                       [--max-steps S] [--policy-seed X] [--battle-seed Y]
 *                       [--families step,events,request,copy,codec,episode,batch]
 *                       [--workers 1,2,4,8,16]
 *                       [--max-seconds T] [--out FILE]
 */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L /* sysconf */
#endif

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if !defined(_WIN32)
#include <unistd.h>
#endif

#include "bench.h"
#include "bench_revision.h"
#include "support/fixtures.h"

#ifndef DFB_BUILD_TYPE
#define DFB_BUILD_TYPE "unknown"
#endif
#ifndef DFB_C_COMPILER
#define DFB_C_COMPILER "unknown"
#endif
#ifndef DFB_C_FLAGS
#define DFB_C_FLAGS ""
#endif
#ifndef DFB_IPO
#define DFB_IPO ""
#endif

typedef struct options {
    dfb_workload workload;
    uint32_t repetitions;
    uint32_t warmup;
    uint64_t max_seconds; /* 0: no limit */
    const char *families;
    const char *workers;
    const char *out;
} options;

static int usage(const char *why)
{
    fprintf(stderr, "duoforge_bench: %s\n", why);
    fprintf(stderr, "usage: duoforge_bench [--battles N] [--repetitions R] [--warmup W] [--max-steps S]\n"
                    "                      [--policy-seed X] [--battle-seed Y] [--max-seconds T]\n"
                    "                      [--families step,events,request,copy,codec,episode,batch]\n"
                    "                      [--workers 1,2,4,8,16] [--out FILE]\n");
    return 2;
}

static int parse_u64(const char *text, uint64_t *out)
{
    char *end = NULL;
    const unsigned long long v = strtoull(text, &end, 0);
    if (end == text || *end != '\0') {
        return 0;
    }
    *out = (uint64_t)v;
    return 1;
}

static int parse(int argc, char **argv, options *o)
{
    memset(o, 0, sizeof *o);
    o->workload.battles = 25u;
    o->workload.max_steps = 1000u;
    o->workload.policy_seed = 20261001u;
    o->workload.battle_seed = 7001u;
    o->repetitions = 5u;
    o->warmup = 1u;
    o->families = "step,events,request,copy,codec,episode";
    o->workers = "1,2,4,8,16";
    for (int i = 1; i < argc; ++i) {
        const char *a = argv[i];
        if (i + 1 >= argc) {
            return usage("missing value");
        }
        const char *v = argv[++i];
        uint64_t n = 0u;
        if (strcmp(a, "--families") == 0) {
            o->families = v;
            continue;
        }
        if (strcmp(a, "--workers") == 0) {
            o->workers = v;
            continue;
        }
        if (strcmp(a, "--out") == 0) {
            o->out = v;
            continue;
        }
        if (!parse_u64(v, &n)) {
            return usage("not a number");
        }
        if (strcmp(a, "--battles") == 0 && n >= 1u && n <= 100000u) {
            o->workload.battles = (uint32_t)n;
        } else if (strcmp(a, "--repetitions") == 0 && n >= 1u && n <= DFB_MAX_REPETITIONS) {
            o->repetitions = (uint32_t)n;
        } else if (strcmp(a, "--warmup") == 0 && n <= 100u) {
            o->warmup = (uint32_t)n;
        } else if (strcmp(a, "--max-steps") == 0 && n >= 1u && n <= 1000000u) {
            o->workload.max_steps = (uint32_t)n;
        } else if (strcmp(a, "--policy-seed") == 0) {
            o->workload.policy_seed = n;
        } else if (strcmp(a, "--battle-seed") == 0) {
            o->workload.battle_seed = n;
        } else if (strcmp(a, "--max-seconds") == 0) {
            o->max_seconds = n;
        } else {
            return usage("unknown option or value out of range");
        }
    }
    return 0;
}

static int has_family(const char *list, const char *name)
{
    const size_t len = strlen(name);
    for (const char *p = list; *p != '\0';) {
        const char *end = strchr(p, ',');
        const size_t n = end != NULL ? (size_t)(end - p) : strlen(p);
        if (n == len && strncmp(p, name, len) == 0) {
            return 1;
        }
        if (end == NULL) {
            break;
        }
        p = end + 1;
    }
    return 0;
}

/* ---------------------------------------------------------------- report */

static uint64_t median_of(const uint64_t *v, uint32_t n)
{
    uint64_t s[DFB_MAX_REPETITIONS];
    for (uint32_t i = 0u; i < n; ++i) {
        s[i] = v[i];
        for (uint32_t j = i; j > 0u && s[j - 1u] > s[j]; --j) {
            const uint64_t x = s[j];
            s[j] = s[j - 1u];
            s[j - 1u] = x;
        }
    }
    return n == 0u ? 0u : s[n / 2u];
}

static uint64_t per_second(uint64_t units, uint64_t ns)
{
    return ns == 0u ? 0u : units * 1000000000u / ns;
}

static void cpu_text(char *out, size_t size)
{
#if defined(_WIN32)
    const char *id = getenv("PROCESSOR_IDENTIFIER");
    const char *n = getenv("NUMBER_OF_PROCESSORS");
    snprintf(out, size, "%s; logical processors %s", id != NULL ? id : "unknown", n != NULL ? n : "?");
#else
    char model[128] = "unknown";
    FILE *f = fopen("/proc/cpuinfo", "r");
    if (f != NULL) {
        char line[256];
        while (fgets(line, sizeof line, f) != NULL) {
            if (strncmp(line, "model name", 10) == 0) {
                const char *c = strchr(line, ':');
                if (c != NULL) {
                    snprintf(model, sizeof model, "%s", c + 2);
                    model[strcspn(model, "\n")] = '\0';
                }
                break;
            }
        }
        fclose(f);
    }
    snprintf(out, size, "%s; logical processors %ld", model, sysconf(_SC_NPROCESSORS_ONLN));
#endif
}

static void json_string(FILE *f, const char *s)
{
    fputc('"', f);
    for (; *s != '\0'; ++s) {
        if (*s == '"' || *s == '\\') {
            fputc('\\', f);
        }
        fputc((unsigned char)*s < 0x20u ? ' ' : *s, f);
    }
    fputc('"', f);
}

static void json_u64_array(FILE *f, const char *key, const dfb_result *r, int which)
{
    fprintf(f, "\"%s\": [", key);
    for (uint32_t i = 0u; i < r->repetitions; ++i) {
        const uint64_t v = which == 0 ? r->rep[i].wall_ns : r->rep[i].cpu_ns;
        fprintf(f, "%s%" PRIu64, i == 0u ? "" : ", ", v);
    }
    fprintf(f, "]");
}

static void write_result(FILE *f, const dfb_result *r, int first)
{
    uint64_t wall[DFB_MAX_REPETITIONS];
    uint32_t disturbed = 0u;
    for (uint32_t i = 0u; i < r->repetitions; ++i) {
        wall[i] = r->rep[i].wall_ns;
        disturbed += dfb_rep_disturbed_workers(&r->rep[i], r->workers) ? 1u : 0u;
    }
    const uint64_t med = median_of(wall, r->repetitions);
    fprintf(f, "%s\n    {\"family\": \"%s\", \"variant\": ", first ? "" : ",", r->family);
    json_string(f, r->variant);
    fprintf(f, ", \"workers\": %" PRIu32 ", \"repetitions\": %" PRIu32 ", ", r->workers == 0u ? 1u : r->workers,
            r->repetitions);
    json_u64_array(f, "wall_ns", r, 0);
    fprintf(f, ", ");
    json_u64_array(f, "cpu_ns", r, 1);
    fprintf(f, ",\n     \"disturbed_repetitions\": %" PRIu32 ", \"median_wall_ns\": %" PRIu64, disturbed, med);
    fprintf(f, ", \"battles\": %" PRIu64 ", \"turns\": %" PRIu64 ", \"steps\": %" PRIu64
               ", \"side_decisions\": %" PRIu64 ", \"calls\": %" PRIu64 ", \"bytes\": %" PRIu64
               ", \"truncations\": %" PRIu64 ", \"errors\": %" PRIu64,
            r->battles, r->turns, r->steps, r->side_decisions, r->calls, r->bytes, r->truncations, r->errors);
    fprintf(f, ",\n     \"per_second\": {\"battles\": %" PRIu64 ", \"turns\": %" PRIu64 ", \"steps\": %" PRIu64
               ", \"side_decisions\": %" PRIu64 ", \"calls\": %" PRIu64 "}",
            per_second(r->battles, med), per_second(r->turns, med), per_second(r->steps, med),
            per_second(r->side_decisions, med), per_second(r->calls, med));
    if (r->parts[0] != NULL) {
        fprintf(f, ",\n     \"median_part_ns\": {");
        for (uint32_t p = 0u; p < DFB_PARTS && r->parts[p] != NULL; ++p) {
            uint64_t v[DFB_MAX_REPETITIONS];
            for (uint32_t i = 0u; i < r->repetitions; ++i) {
                v[i] = r->rep[i].part_ns[p];
            }
            fprintf(f, "%s\"%s\": %" PRIu64, p == 0u ? "" : ", ", r->parts[p], median_of(v, r->repetitions));
        }
        fprintf(f, "}");
    }
    fprintf(f, "}");
    fprintf(stderr, "  %-14s %-26s median %8.3f ms over %" PRIu32 " (disturbed %" PRIu32 ")",
            r->family, r->variant, (double)med / 1e6, r->repetitions, disturbed);
    if (r->steps != 0u) {
        fprintf(stderr, ", %" PRIu64 " steps/s", per_second(r->steps, med));
    } else if (r->calls != 0u) {
        fprintf(stderr, ", %" PRIu64 " calls/s", per_second(r->calls, med));
    }
    if (r->errors != 0u) {
        fprintf(stderr, ", ERRORS %" PRIu64, r->errors);
    }
    fputc('\n', stderr);
}

static void write_tally(FILE *f, const dfb_tally *t, int side)
{
    fprintf(f, "%s\n    {\"side\": %d, \"choices\": %" PRIu64 ", \"team_selections\": %" PRIu64
               ", \"slot_commands\": %" PRIu64 ", \"moves\": %" PRIu64 ", \"struggles\": %" PRIu64
               ", \"megas\": %" PRIu64 ", \"switches\": %" PRIu64 ", \"replacements\": %" PRIu64
               ", \"passes\": %" PRIu64 ",\n     \"target_foe\": %" PRIu64 ", \"target_ally\": %" PRIu64
               ", \"target_none\": %" PRIu64 ", \"leads\": [",
            side == 0 ? "" : ",", side, t->choices, t->team_selections, t->slot_commands, t->moves, t->struggles,
            t->megas, t->switches, t->replacements, t->passes, t->target_foe, t->target_ally, t->target_none);
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        fprintf(f, "%s%" PRIu64, i == 0u ? "" : ", ", t->leads[i]);
    }
    fprintf(f, "],\n     \"move_uses\": {");
    int first = 1;
    for (uint32_t id = 0u; id < DFB_TALLY_MOVE_IDS; ++id) {
        if (t->move_uses[id] != 0u) {
            fprintf(f, "%s\"%" PRIu32 "\": %" PRIu64, first ? "" : ", ", id, t->move_uses[id]);
            first = 0;
        }
    }
    fprintf(f, "}}");
    fprintf(stderr,
            "  side %d chose: %" PRIu64 " moves (%" PRIu64 " Mega, %" PRIu64 " Struggle; targets foe %" PRIu64
            ", ally %" PRIu64 ", none %" PRIu64 "), %" PRIu64 " switches, %" PRIu64 " replacements, %" PRIu64
            " passes\n",
            side, t->moves, t->megas, t->struggles, t->target_foe, t->target_ally, t->target_none, t->switches,
            t->replacements, t->passes);
}

int main(int argc, char **argv)
{
    options o;
    const int pr = parse(argc, argv, &o);
    if (pr != 0) {
        return pr;
    }
    FILE *f = stdout;
    if (o.out != NULL) {
        f = fopen(o.out, "w");
        if (f == NULL) {
            return usage("cannot open the output file");
        }
    }
    const uint64_t started = dfb_wall_ns();
    duoforge_context *ctx = df_make_context(&df_config_k1);
    uint8_t fp[DUOFORGE_DIGEST_SIZE];
    char fp_hex[2u * DUOFORGE_DIGEST_SIZE + 1u];
    fp_hex[0] = '\0';
    if (duoforge_context_fingerprint(ctx, fp) == DUOFORGE_OK) {
        for (uint32_t i = 0u; i < DUOFORGE_DIGEST_SIZE; ++i) {
            snprintf(&fp_hex[2u * i], 3u, "%02x", fp[i]);
        }
    }
    char cpu[256];
    cpu_text(cpu, sizeof cpu);
    char when[32] = "unknown";
    const time_t now = time(NULL);
    const struct tm *utc = gmtime(&now);
    if (utc != NULL) {
        strftime(when, sizeof when, "%Y-%m-%dT%H:%M:%SZ", utc);
    }
#if defined(_WIN32)
    const char *os = "windows";
#elif defined(__linux__)
    const char *os = "linux";
#elif defined(__APPLE__)
    const char *os = "macos";
#else
    const char *os = "other";
#endif

    fprintf(f, "{\n  \"manifest\": {\"engine\": \"duoforge %s\", \"revision\": \"%s\", \"dirty\": %s,\n",
            duoforge_version_string(), DFB_REVISION, DFB_DIRTY ? "true" : "false");
    fprintf(f, "    \"compiler\": ");
    json_string(f, DFB_C_COMPILER);
    fprintf(f, ", \"build_type\": ");
    json_string(f, DFB_BUILD_TYPE);
    fprintf(f, ", \"c_flags\": ");
    json_string(f, DFB_C_FLAGS);
    fprintf(f, ", \"ipo\": %s", DFB_IPO[0] != '\0' ? "true" : "false");
    fprintf(f, ",\n    \"os\": \"%s\", \"cpu\": ", os);
    json_string(f, cpu);
    fprintf(f, ", \"workers\": 1, \"affinity\": \"none\", \"started_utc\": \"%s\",\n", when);
    fprintf(f, "    \"workload\": \"closure-pairings-v1\", \"pairings\": [\"A-B\", \"B-A\", \"A-A\", \"B-B\"],"
               " \"battles_per_pairing\": %" PRIu32 ", \"max_steps\": %" PRIu32 ",\n",
            o.workload.battles, o.workload.max_steps);
    fprintf(f, "    \"policy\": \"uniform random over candidates (splitmix64)\", \"policy_seed\": %" PRIu64
               ", \"battle_seed\": %" PRIu64 ", \"context_fingerprint\": \"%s\",\n",
            o.workload.policy_seed, o.workload.battle_seed, fp_hex);
    fprintf(f, "    \"warmup\": %" PRIu32 ", \"repetitions\": %" PRIu32 ", \"timer\": \"wall: %s, cpu: process\"},\n",
            o.warmup, o.repetitions,
#if defined(_WIN32)
            "QueryPerformanceCounter"
#else
            "CLOCK_MONOTONIC"
#endif
    );

    fprintf(stderr, "duoforge_bench: recording %" PRIu32 " battles per pairing...\n", o.workload.battles);
    dfb_tapes *tapes = NULL;
    dfb_result rec;
    static dfb_tally tally[DUOFORGE_SIDE_COUNT];
    dfb_tally_reset(&tally[0]);
    dfb_tally_reset(&tally[1]);
    duoforge_status st = dfb_tapes_record(ctx, &o.workload, &tapes, &rec, tally);
    uint64_t errors = rec.errors;
    fprintf(f, "  \"record\": {\"battles\": %" PRIu64 ", \"turns\": %" PRIu64 ", \"steps\": %" PRIu64
               ", \"side_decisions\": %" PRIu64 ", \"truncations\": %" PRIu64 ", \"errors\": %" PRIu64 "},\n",
            rec.battles, rec.turns, rec.steps, rec.side_decisions, rec.truncations, rec.errors);
    fprintf(stderr, "  recorded %" PRIu64 " battles, %" PRIu64 " steps, %" PRIu64 " turns, %" PRIu64
                    " truncations, %" PRIu64 " errors (%s)\n",
            rec.battles, rec.steps, rec.turns, rec.truncations, rec.errors, duoforge_status_name(st));
    fprintf(f, "  \"choices\": [");
    write_tally(f, &tally[0], 0);
    write_tally(f, &tally[1], 1);
    fprintf(f, "\n  ],\n  \"results\": [");

    static const char *const names[] = {"step", "events", "request", "copy", "codec", "episode", "batch"};
    int first = 1;
    uint32_t skipped = 0u;
    for (uint32_t i = 0u; i < sizeof names / sizeof names[0] && tapes != NULL; ++i) {
        if (!has_family(o.families, names[i])) {
            continue;
        }
        if (o.max_seconds != 0u && dfb_wall_ns() - started > o.max_seconds * 1000000000u) {
            skipped += 1u; /* the time limit: the remaining families do not run */
            continue;
        }
        static dfb_result r;
        if (i == 6u) {
            /* BATCH_NATIVE: one result per worker count, all playing the same battles. */
            uint64_t hash = 0u;
            const char *w = o.workers;
            while (*w != '\0') {
                char *end = NULL;
                const unsigned long n = strtoul(w, &end, 10);
                if (end == w || n < 1u || n > 256u) {
                    errors += 1u;
                    fprintf(stderr, "duoforge_bench: bad --workers list\n");
                    break;
                }
                st = dfb_batch_native(ctx, &o.workload, (uint32_t)n, o.warmup, o.repetitions, &hash, &r);
                errors += r.errors + (st != DUOFORGE_OK && r.errors == 0u ? 1u : 0u);
                write_result(f, &r, first);
                first = 0;
                w = *end == ',' ? end + 1 : end;
            }
            continue;
        }
        switch (i) {
        case 0:
            st = dfb_step_core(ctx, tapes, false, o.warmup, o.repetitions, &r);
            break;
        case 1:
            st = dfb_step_core(ctx, tapes, true, o.warmup, o.repetitions, &r);
            break;
        case 2:
            st = dfb_request(ctx, tapes, o.warmup, o.repetitions, &r);
            break;
        case 3:
            st = dfb_snapshot(ctx, tapes, false, o.warmup, o.repetitions, &r);
            break;
        case 4:
            st = dfb_snapshot(ctx, tapes, true, o.warmup, o.repetitions, &r);
            break;
        default:
            st = dfb_episode_native(ctx, &o.workload, o.warmup, o.repetitions, &r);
            break;
        }
        errors += r.errors + (st != DUOFORGE_OK && r.errors == 0u ? 1u : 0u);
        write_result(f, &r, first);
        first = 0;
    }
    fprintf(f, "\n  ],\n  \"skipped_by_time_limit\": %" PRIu32 ", \"errors\": %" PRIu64 "\n}\n", skipped, errors);
    if (f != stdout) {
        fclose(f);
    }
    dfb_tapes_destroy(tapes);
    duoforge_context_destroy(ctx);
    fprintf(stderr, "duoforge_bench: %s\n", errors == 0u ? "done" : "FAILED (see errors)");
    return errors == 0u ? 0 : 1;
}
