/*
 * duoforge_certify: the certified dataset of the closure matchups (decision
 * 0010, M5 step 4).
 *
 *   duoforge_certify generate <battles per pairing> <file>
 *   duoforge_certify verify <file>
 *   duoforge_certify minimize <file> <battle> fail|event:<kind>
 *
 * generate plays, for each pairing of the reference teams (A-B, B-A, A-A,
 * B-B), the given number of battles under the certified profile (CLOSURE,
 * register 6, bring 4) with the uniform random policy, and writes per battle
 * its seeds, every choice as the index of the chosen candidate, the step and
 * turn counts, the result and the final digest.
 *
 * verify replays every battle twice: from the stored choices, encoding the
 * battle after half its steps and continuing from a decoded copy, and from
 * the seeds alone (the policy draws the same choices again). Every step must
 * succeed and pass the full state check; counts, result and digest must
 * match the file, and the file's context fingerprint must be the running
 * engine's: the profile is frozen.
 *
 * minimize (M5 step 5) shrinks a battle of a file in that format to a short
 * reproduction of a condition: "fail" (a step or the state check fails) or
 * "event:<kind>" (an event of DUOFORGE_EVENT_<kind> is emitted). It replays
 * the choices (each index modulo the candidate count, missing ones 0), cuts
 * the battle at the first step where the condition holds, then sets every
 * choice to 0 (the first candidate) where the condition still holds, until
 * nothing changes: every remaining nonzero choice is needed.
 *
 * Seeds: one splitmix64 stream from the file's seed gives, battle by battle
 * in pairing order, the battle's rng_initstate and then its policy seed;
 * rng_initseq is 1001. The policy draws next() % n for every requested
 * player, in player order.
 */
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "support/fixtures.h"

#define CERT_PAIRINGS 4u
#define CERT_MAX_STEPS 1000u
#define CERT_MAX_DECISIONS 4096u
#define CERT_SEED UINT64_C(0x2026100100001001)
#define CERT_LINE (CERT_MAX_DECISIONS * 3u + 512u)

typedef struct cert_battle {
    uint32_t pairing;
    uint32_t index;
    uint64_t battle_seed;
    uint64_t policy_seed;
    uint32_t steps;
    uint32_t turns;
    uint32_t result;
    uint32_t decisions;
    uint16_t choice[CERT_MAX_DECISIONS];
    uint8_t digest[DUOFORGE_DIGEST_SIZE];
} cert_battle;

static const char *const cert_pairing_names[CERT_PAIRINGS] = {"A-B", "B-A", "A-A", "B-B"};
static duoforge_side_choice cert_cands[DUOFORGE_MAX_CANDIDATES];
static duoforge_event cert_events[DUOFORGE_SIDE_COUNT][DUOFORGE_MAX_EVENTS];
static cert_battle cert_in;
static cert_battle cert_out;
static char cert_line[CERT_LINE];

static uint64_t cert_next(uint64_t *s)
{
    *s += UINT64_C(0x9E3779B97F4A7C15);
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static void cert_setup(const duoforge_battle_setup *teams, uint32_t pairing, uint64_t seed,
                       duoforge_battle_setup *out)
{
    static const uint32_t pick[CERT_PAIRINGS][2] = {{0u, 1u}, {1u, 0u}, {0u, 0u}, {1u, 1u}};
    *out = *teams;
    out->sides[0] = teams->sides[pick[pairing][0]];
    out->sides[1] = teams->sides[pick[pairing][1]];
    out->rng_initstate = seed;
    out->rng_initseq = 1001u;
}

static void cert_hex(const uint8_t *p, size_t n, char *out)
{
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0u; i < n; ++i) {
        out[2u * i] = digits[p[i] >> 4];
        out[2u * i + 1u] = digits[p[i] & 15u];
    }
    out[2u * n] = '\0';
}

static int cert_nibble(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    return -1;
}

static bool cert_unhex(const char *s, uint8_t *out, size_t n)
{
    if (strlen(s) != 2u * n) {
        return false;
    }
    for (size_t i = 0u; i < n; ++i) {
        const int hi = cert_nibble(s[2u * i]);
        const int lo = cert_nibble(s[2u * i + 1u]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = (uint8_t)(hi * 16 + lo);
    }
    return true;
}

/* Continues `*b` from an encoded copy decoded into another battle. */
static bool cert_continue(const duoforge_context *ctx, const duoforge_battle_setup *setup, duoforge_battle **b)
{
    size_t size = 0u;
    if (duoforge_battle_encoded_size(ctx, *b, &size) != DUOFORGE_OK) {
        return false;
    }
    uint8_t *bytes = malloc(size);
    if (bytes == NULL) {
        return false;
    }
    size_t written = 0u;
    duoforge_battle_setup other = *setup;
    other.rng_initstate ^= 1u; /* the decoded state must replace a different one */
    duoforge_battle *c = NULL;
    bool ok = duoforge_battle_encode(ctx, *b, bytes, size, &written) == DUOFORGE_OK &&
              duoforge_battle_create(ctx, &other, &c) == DUOFORGE_OK &&
              duoforge_battle_decode(ctx, c, bytes, written) == DUOFORGE_OK;
    free(bytes);
    if (!ok) {
        duoforge_battle_destroy(c);
        return false;
    }
    duoforge_battle_destroy(*b);
    *b = c;
    return true;
}

/* Plays `in` from its seeds into `out`. draw: the policy chooses and the
 * choices are stored; otherwise the stored choices are replayed. cut > 0:
 * after that many steps the battle continues from a decoded copy. */
static bool cert_play(const duoforge_context *ctx, const duoforge_battle_setup *teams, const cert_battle *in,
                      bool draw, uint32_t cut, cert_battle *out, const char **why)
{
    *out = *in;
    out->steps = 0u;
    out->turns = 0u;
    out->result = 0u;
    duoforge_battle_setup setup;
    cert_setup(teams, in->pairing, in->battle_seed, &setup);
    duoforge_battle *b = NULL;
    if (duoforge_battle_create(ctx, &setup, &b) != DUOFORGE_OK) {
        *why = "the setup is rejected";
        return false;
    }
    uint64_t policy = in->policy_seed;
    uint32_t k = 0u;
    *why = NULL;
    for (;;) {
        duoforge_request rq;
        if (duoforge_battle_request(ctx, b, 0u, &rq) != DUOFORGE_OK) {
            *why = "a request fails";
            break;
        }
        if (rq.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
            break;
        }
        if (out->steps >= CERT_MAX_STEPS) {
            *why = "the battle does not end";
            break;
        }
        if (cut != 0u && out->steps == cut && !cert_continue(ctx, &setup, &b)) {
            *why = "the codec continuation fails";
            break;
        }
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT && *why == NULL; ++p) {
            uint32_t n = 0u;
            if (duoforge_battle_request(ctx, b, p, &rq) != DUOFORGE_OK) {
                *why = "a request fails";
                break;
            }
            bd.epoch = rq.epoch;
            if (rq.requested == 0u) {
                continue;
            }
            if (duoforge_battle_candidates(ctx, b, p, cert_cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK ||
                n == 0u || k >= CERT_MAX_DECISIONS) {
                *why = "the candidates fail";
                break;
            }
            uint32_t idx = 0u;
            if (draw) {
                idx = (uint32_t)(cert_next(&policy) % n);
                out->choice[k] = (uint16_t)idx;
            } else if (k >= in->decisions || (idx = in->choice[k]) >= n) {
                *why = "a stored choice is not a candidate";
                break;
            }
            k += 1u;
            bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
            bd.responses[p] = cert_cands[idx];
        }
        if (*why != NULL) {
            break;
        }
        duoforge_step_result res;
        duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{cert_events[0], DUOFORGE_MAX_EVENTS, 0u},
                                                               {cert_events[1], DUOFORGE_MAX_EVENTS, 0u}};
        if (duoforge_battle_step_events(ctx, b, &bd, &res, buffers) != DUOFORGE_OK) {
            *why = "a step fails";
            break;
        }
        for (uint32_t i = 0u; i < buffers[0].count; ++i) {
            if (cert_events[0][i].kind == DUOFORGE_EVENT_RESULT) {
                out->result = cert_events[0][i].detail;
            }
        }
        if (duoforge_battle_check(ctx, b) != DUOFORGE_OK) {
            *why = "the state check fails";
            break;
        }
        out->steps += 1u;
    }
    if (*why == NULL && !draw && k != in->decisions) {
        *why = "stored choices are left over";
    }
    out->decisions = k;
    duoforge_observation ob;
    memset(&ob, 0, sizeof ob);
    if (*why == NULL && (duoforge_battle_observe(ctx, b, 0u, &ob) != DUOFORGE_OK ||
                         duoforge_battle_digest(ctx, b, out->digest) != DUOFORGE_OK)) {
        *why = "the final state fails";
    }
    out->turns = *why == NULL ? ob.turn : 0u;
    duoforge_battle_destroy(b);
    return *why == NULL;
}

static void cert_write_battle(FILE *f, const cert_battle *cb)
{
    char digest[2u * DUOFORGE_DIGEST_SIZE + 1u];
    cert_hex(cb->digest, DUOFORGE_DIGEST_SIZE, digest);
    fprintf(f, "b %s %" PRIu32 " %016" PRIx64 " %016" PRIx64 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %s ",
            cert_pairing_names[cb->pairing], cb->index, cb->battle_seed, cb->policy_seed, cb->steps, cb->turns,
            cb->result, digest);
    for (uint32_t k = 0u; k < cb->decisions; ++k) {
        fprintf(f, "%03" PRIx32, (uint32_t)cb->choice[k]);
    }
    fputc('\n', f);
}

static bool cert_parse_battle(char *line, cert_battle *cb)
{
    char pairing[8];
    char digest[2u * DUOFORGE_DIGEST_SIZE + 8u];
    int used = 0;
    memset(cb, 0, sizeof *cb);
    if (sscanf(line, "b %7s %" SCNu32 " %" SCNx64 " %" SCNx64 " %" SCNu32 " %" SCNu32 " %" SCNu32 " %70s %n",
               pairing, &cb->index, &cb->battle_seed, &cb->policy_seed, &cb->steps, &cb->turns, &cb->result, digest,
               &used) != 8 ||
        !cert_unhex(digest, cb->digest, DUOFORGE_DIGEST_SIZE)) {
        return false;
    }
    cb->pairing = CERT_PAIRINGS;
    for (uint32_t p = 0u; p < CERT_PAIRINGS; ++p) {
        if (strcmp(pairing, cert_pairing_names[p]) == 0) {
            cb->pairing = p;
        }
    }
    const char *c = line + used;
    size_t len = strcspn(c, "\r\n");
    if (cb->pairing == CERT_PAIRINGS || len % 3u != 0u || len / 3u > CERT_MAX_DECISIONS) {
        return false;
    }
    cb->decisions = (uint32_t)(len / 3u);
    for (uint32_t k = 0u; k < cb->decisions; ++k) {
        int v = 0;
        for (uint32_t j = 0u; j < 3u; ++j) {
            const int d = cert_nibble(c[3u * k + j]);
            if (d < 0) {
                return false;
            }
            v = v * 16 + d;
        }
        cb->choice[k] = (uint16_t)v;
    }
    return true;
}

static int cert_generate(const duoforge_context *ctx, const duoforge_battle_setup *teams, uint32_t per_pairing,
                         const char *path)
{
    FILE *f = fopen(path, "wb");
    if (f == NULL) {
        fprintf(stderr, "duoforge_certify: cannot write %s\n", path);
        return 1;
    }
    uint8_t fp[DUOFORGE_DIGEST_SIZE];
    char fp_hex[2u * DUOFORGE_DIGEST_SIZE + 1u];
    duoforge_context_fingerprint(ctx, fp);
    cert_hex(fp, DUOFORGE_DIGEST_SIZE, fp_hex);
    fprintf(f, "# DuoForge certified dataset closure-v1 (decision 0010, M5 step 4); written by duoforge_certify.\n");
    fprintf(f, "# b <pairing> <index> <rng_initstate> <policy seed> <steps> <turns> <result> <final digest> "
               "<choices: candidate index, 3 hex digits each>\n");
    fprintf(f, "engine %s\ncontext %s\nseed %016" PRIx64 "\nbattles_per_pairing %" PRIu32 "\n",
            duoforge_version_string(), fp_hex, CERT_SEED, per_pairing);
    uint64_t stream = CERT_SEED;
    uint32_t total = 0u;
    for (uint32_t p = 0u; p < CERT_PAIRINGS; ++p) {
        for (uint32_t i = 0u; i < per_pairing; ++i) {
            memset(&cert_in, 0, sizeof cert_in);
            cert_in.pairing = p;
            cert_in.index = i;
            cert_in.battle_seed = cert_next(&stream);
            cert_in.policy_seed = cert_next(&stream);
            const char *why = NULL;
            if (!cert_play(ctx, teams, &cert_in, true, 0u, &cert_out, &why)) {
                fprintf(stderr, "duoforge_certify: %s battle %" PRIu32 ": %s\n", cert_pairing_names[p], i, why);
                fclose(f);
                return 1;
            }
            cert_write_battle(f, &cert_out);
            total += 1u;
        }
    }
    fprintf(f, "end %" PRIu32 "\n", total);
    fclose(f);
    fprintf(stderr, "duoforge_certify: wrote %" PRIu32 " battles to %s\n", total, path);
    return 0;
}

static int cert_verify(const duoforge_context *ctx, const duoforge_battle_setup *teams, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        fprintf(stderr, "duoforge_certify: cannot read %s\n", path);
        return 1;
    }
    uint8_t fp[DUOFORGE_DIGEST_SIZE];
    char fp_hex[2u * DUOFORGE_DIGEST_SIZE + 1u];
    duoforge_context_fingerprint(ctx, fp);
    cert_hex(fp, DUOFORGE_DIGEST_SIZE, fp_hex);
    uint64_t seed = 0u;
    uint64_t stream = 0u;
    uint32_t per_pairing = 0u;
    uint32_t battles = 0u;
    uint32_t end = UINT32_MAX;
    uint32_t bad = 0u;
    bool context_ok = false;
    uint64_t decisions = 0u;
    uint64_t steps = 0u;
    uint64_t turns = 0u;
    uint32_t results[CERT_PAIRINGS][4] = {{0u}};
    while (fgets(cert_line, (int)sizeof cert_line, f) != NULL) {
        char word[80];
        if (cert_line[0] == '#' || sscanf(cert_line, "%79s", word) != 1) {
            continue;
        }
        if (strcmp(word, "context") == 0) {
            context_ok = sscanf(cert_line, "context %79s", word) == 1 && strcmp(word, fp_hex) == 0;
        } else if (strcmp(word, "seed") == 0) {
            if (sscanf(cert_line, "seed %" SCNx64, &seed) != 1) {
                bad += 1u;
            }
            stream = seed;
        } else if (strcmp(word, "battles_per_pairing") == 0) {
            if (sscanf(cert_line, "battles_per_pairing %" SCNu32, &per_pairing) != 1) {
                bad += 1u;
            }
        } else if (strcmp(word, "end") == 0) {
            if (sscanf(cert_line, "end %" SCNu32, &end) != 1) {
                bad += 1u;
            }
        } else if (strcmp(word, "b") == 0) {
            const char *why = NULL;
            /* The battle's place in the file and its seeds follow the derivation. */
            const uint32_t want_p = per_pairing == 0u ? CERT_PAIRINGS : battles / per_pairing;
            const uint32_t want_i = per_pairing == 0u ? 0u : battles % per_pairing;
            const uint64_t want_seed = cert_next(&stream);
            const uint64_t want_policy = cert_next(&stream);
            if (!cert_parse_battle(cert_line, &cert_in)) {
                why = "the line does not parse";
            } else if (cert_in.pairing != want_p || cert_in.index != want_i || cert_in.battle_seed != want_seed ||
                       cert_in.policy_seed != want_policy) {
                why = "the seeds do not follow the derivation";
            } else if (!cert_play(ctx, teams, &cert_in, false, cert_in.steps / 2u, &cert_out, &why)) {
                /* why is set */
            } else if (cert_out.steps != cert_in.steps || cert_out.turns != cert_in.turns ||
                       cert_out.result != cert_in.result ||
                       memcmp(cert_out.digest, cert_in.digest, DUOFORGE_DIGEST_SIZE) != 0) {
                why = "the replay does not reach the recorded end";
            } else if (!cert_play(ctx, teams, &cert_in, true, 0u, &cert_out, &why)) {
                /* why is set */
            } else if (cert_out.decisions != cert_in.decisions ||
                       memcmp(cert_out.choice, cert_in.choice, cert_in.decisions * sizeof cert_in.choice[0]) != 0 ||
                       memcmp(cert_out.digest, cert_in.digest, DUOFORGE_DIGEST_SIZE) != 0) {
                why = "the seeds do not reproduce the choices";
            }
            if (why != NULL) {
                bad += 1u;
                if (bad <= 5u) {
                    fprintf(stderr, "  battle %" PRIu32 ": %s\n", battles, why);
                }
            } else {
                decisions += cert_in.decisions;
                steps += cert_in.steps;
                turns += cert_in.turns;
                results[cert_in.pairing][cert_in.result & 3u] += 1u;
            }
            battles += 1u;
        }
    }
    fclose(f);
    if (!context_ok) {
        fprintf(stderr, "duoforge_certify: the context fingerprint is not the engine's (%s)\n", fp_hex);
        bad += 1u;
    }
    if (end != battles || battles != CERT_PAIRINGS * per_pairing || battles == 0u) {
        fprintf(stderr, "duoforge_certify: %" PRIu32 " battles, expected %" PRIu32 " per pairing\n", battles,
                per_pairing);
        bad += 1u;
    }
    fprintf(stderr,
            "duoforge_certify: %" PRIu32 " battles, %" PRIu64 " steps, %" PRIu64 " turns, %" PRIu64
            " decisions; %" PRIu32 " failures\n",
            battles, steps, turns, decisions, bad);
    for (uint32_t p = 0u; p < CERT_PAIRINGS; ++p) {
        fprintf(stderr, "  %s: side 0 won %" PRIu32 ", side 1 won %" PRIu32 ", ties %" PRIu32 "\n",
                cert_pairing_names[p], results[p][DUOFORGE_RESULT_SIDE_0], results[p][DUOFORGE_RESULT_SIDE_1],
                results[p][DUOFORGE_RESULT_TIE]);
    }
    return bad == 0u ? 0 : 1;
}

/* The condition a minimization keeps. */
typedef struct cert_pred {
    bool fail;      /* a step or the state check fails */
    uint32_t event; /* otherwise: an event of this kind is emitted */
} cert_pred;

/* Replays the choices of `cb` (index modulo the candidate count, missing
 * ones 0) until `pred` holds; then *out_used is the number of choices made
 * up to that step. False when the battle ends or stops first. */
static bool cert_probe(const duoforge_context *ctx, const duoforge_battle_setup *teams, const cert_battle *cb,
                       const cert_pred *pred, uint32_t *out_used)
{
    duoforge_battle_setup setup;
    cert_setup(teams, cb->pairing, cb->battle_seed, &setup);
    duoforge_battle *b = NULL;
    if (duoforge_battle_create(ctx, &setup, &b) != DUOFORGE_OK) {
        return pred->fail;
    }
    uint32_t k = 0u;
    bool holds = false;
    for (uint32_t step = 0u; step < CERT_MAX_STEPS && !holds; ++step) {
        duoforge_request rq;
        if (duoforge_battle_request(ctx, b, 0u, &rq) != DUOFORGE_OK) {
            holds = pred->fail;
            break;
        }
        if (rq.boundary_kind == DUOFORGE_BOUNDARY_TERMINAL) {
            break;
        }
        duoforge_decision_bundle bd;
        memset(&bd, 0, sizeof bd);
        bool broken = false;
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT && !broken; ++p) {
            uint32_t n = 0u;
            broken = duoforge_battle_request(ctx, b, p, &rq) != DUOFORGE_OK;
            if (broken || rq.requested == 0u) {
                bd.epoch = rq.epoch;
                continue;
            }
            bd.epoch = rq.epoch;
            broken = duoforge_battle_candidates(ctx, b, p, cert_cands, DUOFORGE_MAX_CANDIDATES, &n) != DUOFORGE_OK ||
                     n == 0u || k >= CERT_MAX_DECISIONS;
            if (!broken) {
                const uint32_t idx = (k < cb->decisions ? cb->choice[k] : 0u) % n;
                k += 1u;
                bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                bd.responses[p] = cert_cands[idx];
            }
        }
        if (broken) {
            holds = pred->fail;
            break;
        }
        duoforge_step_result res;
        duoforge_event_buffer buffers[DUOFORGE_SIDE_COUNT] = {{cert_events[0], DUOFORGE_MAX_EVENTS, 0u},
                                                               {cert_events[1], DUOFORGE_MAX_EVENTS, 0u}};
        if (duoforge_battle_step_events(ctx, b, &bd, &res, buffers) != DUOFORGE_OK ||
            duoforge_battle_check(ctx, b) != DUOFORGE_OK) {
            holds = pred->fail;
            break;
        }
        for (uint32_t i = 0u; i < buffers[0].count && !pred->fail; ++i) {
            holds = holds || cert_events[0][i].kind == pred->event;
        }
    }
    duoforge_battle_destroy(b);
    *out_used = k;
    return holds;
}

static void cert_trim(cert_battle *cb, uint32_t used)
{
    if (used < cb->decisions) {
        cb->decisions = used;
    }
    while (cb->decisions > 0u && cb->choice[cb->decisions - 1u] == 0u) {
        cb->decisions -= 1u; /* missing choices are 0 */
    }
}

static int cert_minimize(const duoforge_context *ctx, const duoforge_battle_setup *teams, const char *path,
                         uint32_t number, const char *condition)
{
    cert_pred pred = {false, 0u};
    if (strcmp(condition, "fail") == 0) {
        pred.fail = true;
    } else if (strncmp(condition, "event:", 6u) != 0 || sscanf(condition + 6, "%" SCNu32, &pred.event) != 1) {
        return 2;
    }
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        fprintf(stderr, "duoforge_certify: cannot read %s\n", path);
        return 1;
    }
    uint32_t seen = 0u;
    bool found = false;
    while (!found && fgets(cert_line, (int)sizeof cert_line, f) != NULL) {
        if (strncmp(cert_line, "b ", 2u) == 0) {
            found = seen == number && cert_parse_battle(cert_line, &cert_in);
            seen += 1u;
        }
    }
    fclose(f);
    if (!found) {
        fprintf(stderr, "duoforge_certify: no battle %" PRIu32 " in %s\n", number, path);
        return 1;
    }
    const uint32_t before = cert_in.decisions;
    uint32_t used = 0u;
    if (!cert_probe(ctx, teams, &cert_in, &pred, &used)) {
        fprintf(stderr, "duoforge_certify: the condition does not hold in battle %" PRIu32 "\n", number);
        return 1;
    }
    cert_trim(&cert_in, used);
    uint32_t last = used;
    uint32_t probes = 1u;
    for (bool changed = true; changed;) {
        changed = false;
        for (uint32_t i = 0u; i < cert_in.decisions; ++i) {
            if (cert_in.choice[i] == 0u) {
                continue;
            }
            const uint16_t keep = cert_in.choice[i];
            cert_in.choice[i] = 0u;
            probes += 1u;
            if (cert_probe(ctx, teams, &cert_in, &pred, &used)) {
                cert_trim(&cert_in, used);
                last = used;
                changed = true;
            } else {
                cert_in.choice[i] = keep;
            }
        }
    }
    /* Checked again: the condition holds, and no nonzero choice can be 0. */
    bool verified = cert_probe(ctx, teams, &cert_in, &pred, &used);
    uint32_t nonzero = 0u;
    for (uint32_t i = 0u; i < cert_in.decisions && verified; ++i) {
        const uint16_t keep = cert_in.choice[i];
        if (keep != 0u) {
            nonzero += 1u;
            cert_in.choice[i] = 0u;
            verified = !cert_probe(ctx, teams, &cert_in, &pred, &used);
            cert_in.choice[i] = keep;
        }
    }
    printf("min %s %016" PRIx64 " %016" PRIx64 " ", cert_pairing_names[cert_in.pairing], cert_in.battle_seed,
           cert_in.policy_seed);
    for (uint32_t k = 0u; k < cert_in.decisions; ++k) {
        printf("%03" PRIx32, (uint32_t)cert_in.choice[k]);
    }
    printf("\n");
    fprintf(stderr,
            "duoforge_certify: %s holds after %" PRIu32 " choices (from %" PRIu32 "), %" PRIu32
            " of them not the first candidate; %" PRIu32 " replays\n",
            condition, last, before, nonzero, probes);
    if (!verified) {
        fprintf(stderr, "duoforge_certify: the result does not check\n");
    }
    return verified ? 0 : 1;
}

int main(int argc, char **argv)
{
    duoforge_context *ctx = df_make_context(&df_config_k1);
    duoforge_battle_setup teams;
    df_setup_teams(&teams);
    int rc = 2;
    if (argc == 4 && strcmp(argv[1], "generate") == 0) {
        const long n = strtol(argv[2], NULL, 10);
        rc = n > 0 && n <= 100000 ? cert_generate(ctx, &teams, (uint32_t)n, argv[3]) : 2;
    } else if (argc == 3 && strcmp(argv[1], "verify") == 0) {
        rc = cert_verify(ctx, &teams, argv[2]);
    } else if (argc == 5 && strcmp(argv[1], "minimize") == 0) {
        const long n = strtol(argv[3], NULL, 10);
        rc = n >= 0 ? cert_minimize(ctx, &teams, argv[2], (uint32_t)n, argv[4]) : 2;
    }
    if (rc == 2) {
        fprintf(stderr, "usage: duoforge_certify generate <battles per pairing> <file> | verify <file> |\n"
                        "       minimize <file> <battle> fail|event:<kind>\n");
    }
    duoforge_context_destroy(ctx);
    return rc;
}
