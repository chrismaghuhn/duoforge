/*
 * duoforge.data.api (white-box): the data query API (duoforge_data_*): names
 * and legality per data kind.
 *
 * Names: every row of every table round-trips under every combat kind, the
 * kind's count bounds find, name and the other calls (a POOL move under
 * TEAM_C is refused), unknown names, out-of-range ids, NULL arguments and a
 * SYNTHETIC context are refused with the documented statuses and leave every
 * output untouched; the generated names are Showdown ids and agree with the
 * header's macros.
 *
 * Legality: the lists of the API (moves, abilities, genders, the Mega forme)
 * are compared with the tables read directly (the set of the forme under the
 * CLOSURE and TEAM_C kinds, the learnable bits and the legal abilities under
 * the POOL kinds). The key acceptance is a differential against the setup:
 *   - a model of what setup accepts is written ONLY from the API's answers
 *     and the public constants (the oracle below);
 *   - random members and sides (seeded) are built from what the API reports
 *     and setup accepts them, or refuses with E_UNSUPPORTED exactly when the
 *     oracle (from duoforge_data_supported) says something is unsupported;
 *   - members built from things the API excludes are refused with
 *     E_INVALID_ARGUMENT (random mutations, and an exhaustive sweep of every
 *     forme against every move, ability, gender, item, nature and species id);
 *   - the composition rule of the support gate is checked against the white-box
 *     gate over random manifests of this test's own.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "data/support_manifest.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/data_query.h"
#include "support/check.h"

#define KIND_COUNT 6u
static const uint32_t k_kinds[KIND_COUNT] = {
    DUOFORGE_DATA_KIND_CLOSURE,    DUOFORGE_DATA_KIND_CLOSURE_DEV, DUOFORGE_DATA_KIND_TEAM_C,
    DUOFORGE_DATA_KIND_TEAM_C_DEV, DUOFORGE_DATA_KIND_POOL,        DUOFORGE_DATA_KIND_POOL_DEV,
};
static const char *const k_kind_names[KIND_COUNT] = {"CLOSURE", "CLOSURE_DEV", "TEAM_C", "TEAM_C_DEV", "POOL", "POOL_DEV"};

/* Everything the API says about one kind, loaded once. */
typedef struct kase {
    uint32_t kind;
    const char *kind_name;
    duoforge_context *ctx;
    bool dev;
    bool pool_rules;
    uint32_t n[DUOFORGE_DATA_TABLE_COUNT + 1u]; /* counts by table */
    duoforge_forme_info info[DFI_POOL_FORME_COUNT];
    uint32_t moves[DFI_POOL_FORME_COUNT][DUOFORGE_DATA_MAX_FORME_MOVES];
    /* Members that hold nothing, supported, of different dex numbers: the rest of a swept setup (built once). */
    duoforge_member_setup filler[8];
    uint32_t filler_dex[8];
    uint32_t n_filler;
} kase;
static kase g_kase[KIND_COUNT];

static uint64_t rng_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

static uint32_t rng_below(uint64_t *s, uint32_t n)
{
    return (uint32_t)(rng_next(s) % n);
}

static const char *status_text(duoforge_status st)
{
    return duoforge_status_name(st);
}

/* ---------------------------------------------------------------- loading */

static bool in_list(const uint32_t *list, uint32_t n, uint32_t v)
{
    for (uint32_t i = 0u; i < n; ++i) {
        if (list[i] == v) {
            return true;
        }
    }
    return false;
}

static void load_kase(df_test *t, kase *c, uint32_t kind, const char *kind_name)
{
    memset(c, 0, sizeof *c);
    c->kind = kind;
    c->kind_name = kind_name;
    c->dev = kind == DUOFORGE_DATA_KIND_CLOSURE_DEV || kind == DUOFORGE_DATA_KIND_TEAM_C_DEV ||
             kind == DUOFORGE_DATA_KIND_POOL_DEV;
    c->pool_rules = kind == DUOFORGE_DATA_KIND_POOL || kind == DUOFORGE_DATA_KIND_POOL_DEV;
    const duoforge_context_config cfg = {kind, 6u, 4u, 0u, 0u, NULL};
    if (!DF_CHECK(t, duoforge_context_create(&cfg, &c->ctx) == DUOFORGE_OK)) {
        return;
    }
    for (uint32_t table = 1u; table <= DUOFORGE_DATA_TABLE_COUNT; ++table) {
        DF_CHECK(t, duoforge_data_count(c->ctx, table, &c->n[table]) == DUOFORGE_OK);
    }
    for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES] && sp < DFI_POOL_FORME_COUNT; ++sp) {
        DF_CHECK(t, duoforge_data_forme_info(c->ctx, sp, &c->info[sp]) == DUOFORGE_OK);
        uint32_t count = 0u;
        const duoforge_status st =
            duoforge_data_forme_moves(c->ctx, sp, c->moves[sp], DUOFORGE_DATA_MAX_FORME_MOVES, &count);
        DF_CHECK(t, st == DUOFORGE_OK && count == c->info[sp].move_count);
    }
}

/* ------------------------------------------------------------------ names */

static const char *const *pool_names(uint32_t table)
{
    switch (table) {
    case DUOFORGE_DATA_TABLE_SPECIES:
        return dfi_pool_forme_names;
    case DUOFORGE_DATA_TABLE_MOVE:
        return dfi_pool_move_names;
    case DUOFORGE_DATA_TABLE_ITEM:
        return dfi_pool_item_names;
    case DUOFORGE_DATA_TABLE_ABILITY:
        return dfi_pool_ability_names;
    default:
        return dfi_pool_nature_names;
    }
}

static uint32_t pool_count(uint32_t table)
{
    switch (table) {
    case DUOFORGE_DATA_TABLE_SPECIES:
        return DFI_POOL_FORME_COUNT;
    case DUOFORGE_DATA_TABLE_MOVE:
        return DFI_POOL_MOVE_COUNT;
    case DUOFORGE_DATA_TABLE_ITEM:
        return DFI_POOL_ITEM_COUNT;
    case DUOFORGE_DATA_TABLE_ABILITY:
        return DFI_POOL_ABILITY_COUNT;
    default:
        return DFI_NATURE_COUNT;
    }
}

static bool is_showdown_id(const char *s)
{
    if (s == NULL || s[0] == '\0') {
        return false;
    }
    for (const char *p = s; *p != '\0'; ++p) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))) {
            return false;
        }
    }
    return true;
}

static void test_counts_and_round_trip(df_test *t, const kase *c)
{
    /* The kind's counts, from the constants of the kind's tables. */
    uint32_t want[DUOFORGE_DATA_TABLE_COUNT + 1u] = {0u};
    if (c->pool_rules) {
        want[DUOFORGE_DATA_TABLE_SPECIES] = DFI_POOL_FORME_COUNT;
        want[DUOFORGE_DATA_TABLE_MOVE] = DFI_POOL_MOVE_COUNT;
        want[DUOFORGE_DATA_TABLE_ITEM] = DFI_POOL_ITEM_COUNT;
        want[DUOFORGE_DATA_TABLE_ABILITY] = DFI_POOL_ABILITY_COUNT;
    } else if (c->kind == DUOFORGE_DATA_KIND_TEAM_C || c->kind == DUOFORGE_DATA_KIND_TEAM_C_DEV) {
        want[DUOFORGE_DATA_TABLE_SPECIES] = DFI_EXT_FORME_COUNT;
        want[DUOFORGE_DATA_TABLE_MOVE] = DFI_EXT_MOVE_COUNT;
        want[DUOFORGE_DATA_TABLE_ITEM] = DFI_EXT_ITEM_COUNT;
        want[DUOFORGE_DATA_TABLE_ABILITY] = DFI_EXT_ABILITY_COUNT;
    } else {
        want[DUOFORGE_DATA_TABLE_SPECIES] = DFI_FORME_COUNT;
        want[DUOFORGE_DATA_TABLE_MOVE] = DFI_MOVE_COUNT;
        want[DUOFORGE_DATA_TABLE_ITEM] = DFI_ITEM_COUNT;
        want[DUOFORGE_DATA_TABLE_ABILITY] = DFI_ABILITY_COUNT;
    }
    want[DUOFORGE_DATA_TABLE_NATURE] = DFI_NATURE_COUNT;
    for (uint32_t table = 1u; table <= DUOFORGE_DATA_TABLE_COUNT; ++table) {
        if (!DF_CHECK(t, c->n[table] == want[table])) {
            fprintf(stderr, "  %s table %u: count %u, expected %u\n", c->kind_name, table, c->n[table], want[table]);
            continue;
        }
        /* The context's own counts are the same numbers. */
        if (table == DUOFORGE_DATA_TABLE_SPECIES) {
            DF_CHECK(t, c->n[table] == c->ctx->species_count);
        } else if (table == DUOFORGE_DATA_TABLE_MOVE) {
            DF_CHECK(t, c->n[table] == c->ctx->move_count);
        }
        for (uint32_t id = 0u; id < c->n[table]; ++id) {
            const char *name = NULL;
            uint32_t back = 0xA5A5A5A5u;
            const duoforge_status ns = duoforge_data_name(c->ctx, table, id, &name);
            bool ok = ns == DUOFORGE_OK && is_showdown_id(name);
            if (ok) {
                const duoforge_status fs = duoforge_data_find(c->ctx, table, name, strlen(name), &back);
                ok = fs == DUOFORGE_OK && back == id && name == pool_names(table)[id];
            }
            if (!DF_CHECK(t, ok)) {
                fprintf(stderr, "  %s table %u id %u: no round trip (%s)\n", c->kind_name, table, id, name ? name : "-");
            }
        }
        /* Names are unique within the kind (find would otherwise be ambiguous). */
        for (uint32_t a = 0u; a < c->n[table]; ++a) {
            for (uint32_t b = a + 1u; b < c->n[table]; ++b) {
                if (!DF_CHECK(t, strcmp(pool_names(table)[a], pool_names(table)[b]) != 0)) {
                    fprintf(stderr, "  %s table %u: ids %u and %u share a name\n", c->kind_name, table, a, b);
                }
            }
        }
        /* An id of the pool tables beyond the kind's count is refused, by id and by name. */
        for (uint32_t id = c->n[table]; id < pool_count(table); ++id) {
            const char *name = NULL;
            uint32_t out = 0xA5A5A5A5u;
            const char *pn = pool_names(table)[id];
            DF_CHECK(t, duoforge_data_name(c->ctx, table, id, &name) == DUOFORGE_E_INVALID_ARGUMENT && name == NULL);
            DF_CHECK(t, duoforge_data_find(c->ctx, table, pn, strlen(pn), &out) == DUOFORGE_E_INVALID_ARGUMENT &&
                            out == 0xA5A5A5A5u);
        }
        const char *name = NULL;
        DF_CHECK(t, duoforge_data_name(c->ctx, table, c->n[table] + 7u, &name) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, duoforge_data_name(c->ctx, table, 0xFFFFFFFFu, &name) == DUOFORGE_E_INVALID_ARGUMENT);
    }
}

typedef struct spot {
    uint32_t table;
    uint32_t id;
    const char *name;
} spot;

/* The generated names against the header's macros (a hand-written sample of every table, the rows of
 * every generation step included); tools/datagen/test_pool_names.py checks all of them against the
 * keys of trace_to_c.py and pool_families.js against the pinned dex. */
static void test_generated_names(df_test *t)
{
    static const spot spots[] = {
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_RILLABOOM, "rillaboom"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_STARAPTORMEGA, "staraptormega"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_RAICHUMEGAY, "raichumegay"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_KINGAMBIT, "kingambit"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_PELIPPER, "pelipper"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_ARCANINEHISUI, "arcaninehisui"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_FLOETTEETERNAL, "floetteeternal"},
        {DUOFORGE_DATA_TABLE_SPECIES, DFI_FORME_FLOETTEMEGA, "floettemega"},
        {DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_STRUGGLE, "struggle"},
        {DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_CLOSECOMBAT, "closecombat"},
        {DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_DIRECLAW, "direclaw"},
        {DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_UTURN, "uturn"},
        {DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_DAZZLINGGLEAM, "dazzlinggleam"},
        {DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_LEFTOVERS, "leftovers"},
        {DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_CHOICESCARF, "choicescarf"},
        {DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_BLACKBELT, "blackbelt"},
        {DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_YACHEBERRY, "yacheberry"},
        {DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_FLOETTITE, "floettite"},
        {DUOFORGE_DATA_TABLE_ABILITY, DFI_ABILITY_GRASSYSURGE, "grassysurge"},
        {DUOFORGE_DATA_TABLE_ABILITY, DFI_ABILITY_PSYCHICSURGE, "psychicsurge"},
        {DUOFORGE_DATA_TABLE_ABILITY, DFI_ABILITY_PIXILATE, "pixilate"},
        {DUOFORGE_DATA_TABLE_ABILITY, DFI_ABILITY_FAIRYAURA, "fairyaura"},
        {DUOFORGE_DATA_TABLE_NATURE, DFI_NATURE_ADAMANT, "adamant"},
        {DUOFORGE_DATA_TABLE_NATURE, DFI_NATURE_BASHFUL, "bashful"},
    };
    for (size_t i = 0u; i < sizeof spots / sizeof spots[0]; ++i) {
        const char *got = pool_names(spots[i].table)[spots[i].id];
        if (!DF_CHECK(t, got != NULL && strcmp(got, spots[i].name) == 0)) {
            fprintf(stderr, "  table %u id %u: %s, expected %s\n", spots[i].table, spots[i].id, got ? got : "-",
                    spots[i].name);
        }
    }
    /* No hole in a generated array (a designated initializer that missed an id leaves NULL), and the
     * Showdown id shape for every name. */
    for (uint32_t table = 1u; table <= DUOFORGE_DATA_TABLE_COUNT; ++table) {
        for (uint32_t id = 0u; id < pool_count(table); ++id) {
            DF_CHECK(t, is_showdown_id(pool_names(table)[id]));
        }
    }
    /* The prefix: a name keeps its id under every kind that has the id. */
    DF_CHECK(t, strcmp(dfi_pool_forme_names[DFI_FORME_COUNT - 1u], "grimmsnarl") == 0);
    DF_CHECK(t, strcmp(dfi_pool_forme_names[DFI_EXT_FORME_COUNT - 1u], "basculegion") == 0);
}

/* NULL arguments, a table outside its domain, a SYNTHETIC context, the checks in order, and that no
 * output is touched on failure. */
static void test_refusals(df_test *t, const kase *c)
{
    const duoforge_context *ctx = c->ctx;
    const uint32_t S = DUOFORGE_DATA_TABLE_SPECIES, M = DUOFORGE_DATA_TABLE_MOVE;
    uint32_t out = 0xA5A5A5A5u;
    uint32_t count = 0xA5A5A5A5u;
    df_sentinel sentinel;
    const char *name = (const char *)&sentinel;
    duoforge_forme_info info;
    memset(&info, 0xA5, sizeof info);
    duoforge_forme_info before = info;
    const char *rill = "rillaboom";

    /* NULL. */
    DF_CHECK(t, duoforge_data_count(NULL, S, &count) == DUOFORGE_E_NULL_ARGUMENT && count == 0xA5A5A5A5u);
    DF_CHECK(t, duoforge_data_count(ctx, S, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_name(NULL, S, 0u, &name) == DUOFORGE_E_NULL_ARGUMENT &&
                    name == (const char *)&sentinel);
    DF_CHECK(t, duoforge_data_name(ctx, S, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(NULL, S, rill, 9u, &out) == DUOFORGE_E_NULL_ARGUMENT && out == 0xA5A5A5A5u);
    DF_CHECK(t, duoforge_data_find(ctx, S, NULL, 9u, &out) == DUOFORGE_E_NULL_ARGUMENT && out == 0xA5A5A5A5u);
    DF_CHECK(t, duoforge_data_find(ctx, S, NULL, 0u, &out) == DUOFORGE_E_NULL_ARGUMENT && out == 0xA5A5A5A5u);
    DF_CHECK(t, duoforge_data_find(ctx, S, rill, 9u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    for (int preset = 0; preset < 2; ++preset) { /* rule S3: a bool output is checked at both values */
        bool supported = preset != 0;
        DF_CHECK(t, duoforge_data_supported(NULL, S, 0u, &supported) == DUOFORGE_E_NULL_ARGUMENT &&
                        supported == (preset != 0));
        DF_CHECK(t, duoforge_data_supported(ctx, S, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
        DF_CHECK(t, duoforge_data_supported(ctx, S, c->n[S], &supported) == DUOFORGE_E_INVALID_ARGUMENT &&
                        supported == (preset != 0));
        DF_CHECK(t, duoforge_data_supported(ctx, 0u, 0u, &supported) == DUOFORGE_E_INVALID_ARGUMENT &&
                        supported == (preset != 0));
    }
    DF_CHECK(t, duoforge_data_forme_info(NULL, 0u, &info) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_info(ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    uint32_t buffer[4] = {0xA5A5A5A5u, 0xA5A5A5A5u, 0xA5A5A5A5u, 0xA5A5A5A5u};
    DF_CHECK(t, duoforge_data_forme_moves(NULL, 0u, buffer, 4u, &count) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_moves(ctx, 0u, buffer, 4u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_moves(ctx, 0u, NULL, 4u, &count) == DUOFORGE_E_NULL_ARGUMENT &&
                    count == 0xA5A5A5A5u);

    /* A table outside 1..5, and an id or species beyond the kind's count. */
    for (uint32_t table = 0u; table <= DUOFORGE_DATA_TABLE_COUNT + 2u; ++table) {
        if (table >= 1u && table <= DUOFORGE_DATA_TABLE_COUNT) {
            continue;
        }
        DF_CHECK(t, duoforge_data_count(ctx, table, &count) == DUOFORGE_E_INVALID_ARGUMENT && count == 0xA5A5A5A5u);
        DF_CHECK(t, duoforge_data_name(ctx, table, 0u, &name) == DUOFORGE_E_INVALID_ARGUMENT &&
                        name == (const char *)&sentinel);
        DF_CHECK(t, duoforge_data_find(ctx, table, rill, 9u, &out) == DUOFORGE_E_INVALID_ARGUMENT &&
                        out == 0xA5A5A5A5u);
    }
    DF_CHECK(t, duoforge_data_count(ctx, 0xFFFFFFFFu, &count) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_info(ctx, c->n[S], &info) == DUOFORGE_E_INVALID_ARGUMENT &&
                    memcmp(&info, &before, sizeof info) == 0);
    DF_CHECK(t, duoforge_data_forme_info(ctx, 0xFFFFFFFFu, &info) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_forme_moves(ctx, c->n[S], buffer, 4u, &count) == DUOFORGE_E_INVALID_ARGUMENT &&
                    count == 0xA5A5A5A5u);

    /* Names: unknown, a prefix, an extension, another case, a NUL inside, the empty name, the length. */
    const char *rill_nul = "rilla\0oom";
    DF_CHECK(t, duoforge_data_find(ctx, S, "unknownmon", 10u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, S, rill, 8u, &out) == DUOFORGE_E_INVALID_ARGUMENT); /* a prefix */
    DF_CHECK(t, duoforge_data_find(ctx, S, "rillabooms", 10u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, S, "Rillaboom", 9u, &out) == DUOFORGE_E_INVALID_ARGUMENT); /* no toID here */
    DF_CHECK(t, duoforge_data_find(ctx, S, rill_nul, 9u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, S, "", 0u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, S, rill, 0u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, M, rill, 9u, &out) == DUOFORGE_E_INVALID_ARGUMENT); /* a species name as a move */
    DF_CHECK(t, out == 0xA5A5A5A5u);
    /* Not NUL-terminated: only `length` bytes are read. */
    {
        const char raw[9] = {'r', 'i', 'l', 'l', 'a', 'b', 'o', 'o', 'm'};
        DF_CHECK(t, duoforge_data_find(ctx, S, raw, 9u, &out) == DUOFORGE_OK && out == DFI_FORME_RILLABOOM);
        out = 0xA5A5A5A5u;
    }

    /* Forme moves: the capacity convention. */
    uint32_t need = 0u;
    DF_CHECK(t, duoforge_data_forme_moves(ctx, DFI_FORME_RILLABOOM, NULL, 0u, &need) == DUOFORGE_E_CAPACITY && need >= 1u);
    uint32_t big[DUOFORGE_DATA_MAX_FORME_MOVES + 1u];
    for (uint32_t i = 0u; i < DUOFORGE_DATA_MAX_FORME_MOVES + 1u; ++i) {
        big[i] = 0xA5A5A5A5u;
    }
    count = 0xA5A5A5A5u;
    DF_CHECK(t, duoforge_data_forme_moves(ctx, DFI_FORME_RILLABOOM, big, need - 1u, &count) == DUOFORGE_E_CAPACITY &&
                    count == need && big[0] == 0xA5A5A5A5u);
    count = 0xA5A5A5A5u;
    DF_CHECK(t, duoforge_data_forme_moves(ctx, DFI_FORME_RILLABOOM, big, need, &count) == DUOFORGE_OK && count == need &&
                    big[need] == 0xA5A5A5A5u && big[need - 1u] != 0xA5A5A5A5u);
    /* A Mega forme has no moves: an empty list needs no capacity and no buffer. */
    count = 0xA5A5A5A5u;
    DF_CHECK(t, duoforge_data_forme_moves(ctx, DFI_FORME_STARAPTORMEGA, NULL, 0u, &count) == DUOFORGE_OK && count == 0u);
}

static void test_synthetic(df_test *t)
{
    static const uint8_t classes[3] = {1u, 2u, 6u};
    const duoforge_context_config cfg = {DUOFORGE_DATA_KIND_SYNTHETIC, 6u, 4u, 3u, 3u, classes};
    duoforge_context *ctx = NULL;
    if (!DF_CHECK(t, duoforge_context_create(&cfg, &ctx) == DUOFORGE_OK)) {
        return;
    }
    uint32_t count = 0xA5A5A5A5u, out = 0xA5A5A5A5u;
    df_sentinel sentinel;
    const char *name = (const char *)&sentinel;
    duoforge_forme_info info;
    memset(&info, 0xA5, sizeof info);
    duoforge_forme_info before = info;
    uint32_t buffer[4] = {0xA5A5A5A5u, 0xA5A5A5A5u, 0xA5A5A5A5u, 0xA5A5A5A5u};
    for (uint32_t table = 1u; table <= DUOFORGE_DATA_TABLE_COUNT; ++table) {
        DF_CHECK(t, duoforge_data_count(ctx, table, &count) == DUOFORGE_E_UNSUPPORTED && count == 0xA5A5A5A5u);
        DF_CHECK(t, duoforge_data_name(ctx, table, 0u, &name) == DUOFORGE_E_UNSUPPORTED &&
                        name == (const char *)&sentinel);
        DF_CHECK(t, duoforge_data_find(ctx, table, "rillaboom", 9u, &out) == DUOFORGE_E_UNSUPPORTED &&
                        out == 0xA5A5A5A5u);
        for (int preset = 0; preset < 2; ++preset) {
            bool supported = preset != 0;
            DF_CHECK(t, duoforge_data_supported(ctx, table, 0u, &supported) == DUOFORGE_E_UNSUPPORTED &&
                            supported == (preset != 0));
        }
    }
    DF_CHECK(t, duoforge_data_forme_info(ctx, 0u, &info) == DUOFORGE_E_UNSUPPORTED && memcmp(&info, &before, sizeof info) == 0);
    DF_CHECK(t, duoforge_data_forme_moves(ctx, 0u, buffer, 4u, &count) == DUOFORGE_E_UNSUPPORTED &&
                    count == 0xA5A5A5A5u && buffer[0] == 0xA5A5A5A5u);
    /* NULL still comes first, and so does a table outside its domain. */
    DF_CHECK(t, duoforge_data_count(ctx, 1u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_count(ctx, 0u, &count) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, duoforge_data_find(ctx, 9u, "rillaboom", 9u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    duoforge_context_destroy(ctx);
}

/* ---------------------------------------------------------------- legality */

/* The legal moves of a base forme, from the tables read directly (not through the shared rule). */
/* The cosmetic aliases (decision 0015 section 4.2): find maps each to the row of its base forme, name gives the
 * canonical name, and the kind's count bounds an alias like the row it stands for. */
static void test_aliases(df_test *t, const kase *c)
{
    const duoforge_context *ctx = c->ctx;
    const uint32_t S = DUOFORGE_DATA_TABLE_SPECIES;
    DF_CHECK_EQ_U64(t, DFI_POOL_ALIAS_COUNT, 29u);
    uint32_t accepted = 0u;
    for (uint32_t a = 0u; a < DFI_POOL_ALIAS_COUNT; ++a) {
        const char *alias = dfi_pool_forme_aliases[a].name;
        const uint32_t row = dfi_pool_forme_aliases[a].forme;
        const size_t length = strlen(alias);
        uint32_t id = 0xA5A5A5A5u;
        const duoforge_status st = duoforge_data_find(ctx, S, alias, length, &id);
        /* An alias is no row's name: it is never a canonical name of the table. */
        for (uint32_t r = 0u; r < DFI_POOL_FORME_COUNT; ++r) {
            DF_CHECK(t, strcmp(alias, dfi_pool_forme_names[r]) != 0);
        }
        if (row < c->n[S]) {
            accepted += 1u;
            DF_CHECK(t, st == DUOFORGE_OK && id == row);
            const char *canonical = NULL;
            DF_CHECK(t, duoforge_data_name(ctx, S, id, &canonical) == DUOFORGE_OK && canonical != NULL &&
                            strcmp(canonical, dfi_pool_forme_names[row]) == 0 && strcmp(canonical, alias) != 0);
            /* The canonical name still finds the same row, and the alias is no name of another table. */
            uint32_t again = 0xA5A5A5A5u;
            DF_CHECK(t, duoforge_data_find(ctx, S, canonical, strlen(canonical), &again) == DUOFORGE_OK && again == row);
            uint32_t other = 0xA5A5A5A5u;
            for (uint32_t table = DUOFORGE_DATA_TABLE_MOVE; table <= DUOFORGE_DATA_TABLE_NATURE; ++table) {
                DF_CHECK(t, duoforge_data_find(ctx, table, alias, length, &other) == DUOFORGE_E_INVALID_ARGUMENT &&
                                other == 0xA5A5A5A5u);
            }
        } else {
            DF_CHECK(t, st == DUOFORGE_E_INVALID_ARGUMENT && id == 0xA5A5A5A5u); /* beyond the kind's count */
        }
        /* An alias is as exact as a name: a prefix, an extension, another case, a NUL inside. */
        uint32_t miss = 0xA5A5A5A5u;
        DF_CHECK(t, duoforge_data_find(ctx, S, alias, length - 1u, &miss) == DUOFORGE_E_INVALID_ARGUMENT);
        char longer[64];
        memcpy(longer, alias, length);
        longer[length] = 's';
        DF_CHECK(t, duoforge_data_find(ctx, S, longer, length + 1u, &miss) == DUOFORGE_E_INVALID_ARGUMENT);
        longer[0] = (char)(longer[0] - 'a' + 'A');
        DF_CHECK(t, duoforge_data_find(ctx, S, longer, length, &miss) == DUOFORGE_E_INVALID_ARGUMENT);
        memcpy(longer, alias, length + 1u);
        longer[length / 2u] = '\0';
        DF_CHECK(t, duoforge_data_find(ctx, S, longer, length, &miss) == DUOFORGE_E_INVALID_ARGUMENT);
        DF_CHECK(t, miss == 0xA5A5A5A5u);
    }
    /* The pool kinds see all 29; the CLOSURE and TEAM_C kinds, whose tables hold none of the rows, none. */
    DF_CHECK_EQ_U64(t, accepted, c->pool_rules ? DFI_POOL_ALIAS_COUNT : 0u);
    /* Unknown names are still refused, and a cosmetic forme that is no alias is too. */
    uint32_t out = 0xA5A5A5A5u;
    DF_CHECK(t, duoforge_data_find(ctx, S, "vivillonxx", 10u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, out == 0xA5A5A5A5u); /* the refusals wrote nothing */
    DF_CHECK(t, duoforge_data_find(ctx, S, "vivillon", 8u, &out) == (c->pool_rules ? DUOFORGE_OK : DUOFORGE_E_INVALID_ARGUMENT));
}

static uint32_t expected_moves(const kase *c, uint32_t sp, uint32_t *out)
{
    uint32_t n = 0u;
    const dfi_pool_forme_data *f = &dfi_pool_formes[sp];
    if (f->is_mega != 0u) {
        return 0u;
    }
    for (uint32_t m = 0u; m < c->n[DUOFORGE_DATA_TABLE_MOVE]; ++m) {
        bool legal;
        if (c->pool_rules) {
            legal = (((uint32_t)dfi_pool_forme_legal[sp].learnable[m / 8u] >> (m % 8u)) & 1u) != 0u;
        } else {
            legal = false;
            for (uint32_t k = 0u; k < f->set_move_count; ++k) {
                legal = legal || f->set_moves[k] == m;
            }
        }
        if (legal) {
            out[n++] = m;
        }
    }
    return n;
}

static uint32_t expected_abilities(const kase *c, uint32_t sp, uint32_t *out)
{
    uint32_t n = 0u;
    const dfi_pool_forme_data *f = &dfi_pool_formes[sp];
    if (f->is_mega != 0u) {
        return 0u;
    }
    for (uint32_t a = 0u; a < c->n[DUOFORGE_DATA_TABLE_ABILITY]; ++a) {
        bool legal = false;
        if (c->pool_rules) {
            for (uint32_t k = 0u; k < dfi_pool_forme_legal[sp].ability_count; ++k) {
                legal = legal || dfi_pool_forme_legal[sp].abilities[k] == a;
            }
        } else {
            legal = f->ability == a;
        }
        if (legal) {
            out[n++] = a;
        }
    }
    return n;
}

static void test_forme_info(df_test *t, const kase *c)
{
    uint32_t want_moves[DUOFORGE_DATA_MAX_FORME_MOVES];
    uint32_t want_abilities[DUOFORGE_DATA_MAX_FORME_MOVES];
    uint32_t max_moves = 0u;
    for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES]; ++sp) {
        const duoforge_forme_info *in = &c->info[sp];
        const dfi_pool_forme_data *f = &dfi_pool_formes[sp];
        const bool base = f->is_mega == 0u;
        bool ok = in->dex_num == f->dex_num && in->is_mega == f->is_mega && in->setup_legal == (base ? 1u : 0u) &&
                  in->base_species == f->base_forme;
        /* The Mega forme and the stone, from the rows. */
        const uint32_t mega_species = f->mega_forme != DFI_FORME_NONE ? f->mega_forme : DUOFORGE_DATA_NONE;
        ok = ok && in->mega_species == mega_species;
        if (mega_species != DUOFORGE_DATA_NONE) {
            ok = ok && in->mega_stone == f->mega_item && in->mega_ability == dfi_pool_formes[mega_species].ability &&
                 dfi_pool_formes[mega_species].mega_item == in->mega_stone && dfi_pool_formes[mega_species].base_forme == sp &&
                 mega_species < c->n[DUOFORGE_DATA_TABLE_SPECIES] && in->mega_stone < c->n[DUOFORGE_DATA_TABLE_ITEM];
        } else {
            ok = ok && in->mega_stone == DUOFORGE_DATA_NONE && in->mega_ability == DUOFORGE_DATA_NONE &&
                 in->mega_supported == 0u;
        }
        /* Genders from the gender rule. */
        uint32_t mask = 0u;
        if (base) {
            switch (f->gender_rule) {
            case DFI_GENDER_RULE_MALE:
                mask = DUOFORGE_GENDER_BIT_MALE;
                break;
            case DFI_GENDER_RULE_FEMALE:
                mask = DUOFORGE_GENDER_BIT_FEMALE;
                break;
            case DFI_GENDER_RULE_NONE:
                mask = DUOFORGE_GENDER_BIT_NONE;
                break;
            default:
                mask = DUOFORGE_GENDER_BIT_MALE | DUOFORGE_GENDER_BIT_FEMALE;
                break;
            }
        }
        ok = ok && in->gender_mask == mask && in->no_ability == (base && c->dev ? 1u : 0u);
        const uint32_t na = expected_abilities(c, sp, want_abilities);
        ok = ok && in->ability_count == na && na <= DUOFORGE_DATA_MAX_FORME_ABILITIES;
        for (uint32_t k = 0u; ok && k < DUOFORGE_DATA_MAX_FORME_ABILITIES; ++k) {
            ok = in->abilities[k] == (k < na ? want_abilities[k] : 0u);
        }
        const uint32_t nm = expected_moves(c, sp, want_moves);
        ok = ok && in->move_count == nm;
        for (uint32_t k = 0u; ok && k < nm; ++k) {
            ok = c->moves[sp][k] == want_moves[k];
        }
        if (nm > max_moves) {
            max_moves = nm;
        }
        if (!DF_CHECK(t, ok)) {
            fprintf(stderr, "  %s forme %u (%s): the info differs from the tables\n", c->kind_name, sp,
                    dfi_pool_forme_names[sp]);
        }
        if (base) {
            /* A member needs a move, and an ability unless No Ability is legal. */
            DF_CHECK(t, in->move_count >= 1u);
            DF_CHECK(t, in->ability_count >= 1u);
            /* Under the set rule the list is the set: one ability, the set's moves. */
            if (!c->pool_rules) {
                DF_CHECK(t, in->ability_count == 1u && in->move_count == f->set_move_count);
            }
        }
    }
    DF_CHECK(t, max_moves <= DUOFORGE_DATA_MAX_FORME_MOVES);
}

static uint32_t find_id(df_test *t, const kase *c, uint32_t table, const char *name)
{
    uint32_t id = 0xFFFFFFFFu;
    DF_CHECK(t, duoforge_data_find(c->ctx, table, name, strlen(name), &id) == DUOFORGE_OK);
    return id;
}

/* ----------------------------------------------------------- Mega by stone */

/* The Mega formes of a species, one per stone (duoforge_data_mega_count and _at): the count, the ascending stone ids,
 * the old single link as the first one that the forme's row has, and the refusals; and the pairs that the single link
 * cannot give (a second Mega, a stone of two species). */
static void test_mega_by_stone(df_test *t, const kase *c)
{
    const uint32_t S = DUOFORGE_DATA_TABLE_SPECIES;
    const uint32_t count = c->n[S];
    uint32_t reached[DFI_POOL_FORME_COUNT] = {0};
    for (uint32_t sp = 0u; sp < count; ++sp) {
        uint32_t n = 0xFFFFFFFFu;
        if (!DF_CHECK(t, duoforge_data_mega_count(c->ctx, sp, &n) == DUOFORGE_OK)) {
            continue;
        }
        const duoforge_forme_info *in = &c->info[sp];
        DF_CHECK(t, in->is_mega == 0u || n == 0u); /* a Mega forme reaches none */
        DF_CHECK(t, in->mega_species == DUOFORGE_DATA_NONE || n >= 1u); /* the single link is one of them */
        bool single_listed = in->mega_species == DUOFORGE_DATA_NONE;
        uint32_t last = 0u;
        for (uint32_t i = 0u; i < n; ++i) {
            duoforge_mega_info mi;
            if (!DF_CHECK(t, duoforge_data_mega_at(c->ctx, sp, i, &mi) == DUOFORGE_OK)) {
                continue;
            }
            DF_CHECK(t, mi.base_species == sp && mi.stone < c->n[DUOFORGE_DATA_TABLE_ITEM] && mi.mega_species < count);
            DF_CHECK(t, i == 0u || mi.stone > last); /* ascending item id */
            last = mi.stone;
            DF_CHECK(t, c->info[mi.mega_species].is_mega == 1u && c->info[mi.mega_species].base_species == sp);
            DF_CHECK(t, mi.mega_ability == dfi_pool_formes[mi.mega_species].ability);
            if (in->mega_species != DUOFORGE_DATA_NONE && mi.mega_species == in->mega_species) {
                single_listed = single_listed || mi.stone == in->mega_stone;
                DF_CHECK(t, mi.stone == in->mega_stone && mi.mega_ability == in->mega_ability &&
                                mi.supported == in->mega_supported); /* the old fields say the same of the first one */
            }
            reached[mi.mega_species] += 1u;
        }
        DF_CHECK(t, single_listed);
        duoforge_mega_info mi = {0xDEADu, 0xDEADu, 0xDEADu, 0xDEADu, 0xDEADu};
        const duoforge_mega_info before = mi;
        DF_CHECK(t, duoforge_data_mega_at(c->ctx, sp, n, &mi) == DUOFORGE_E_INVALID_ARGUMENT &&
                        memcmp(&mi, &before, sizeof mi) == 0);
    }
    /* Every Mega forme of the kind is reached by exactly one stone, and only by its own. */
    for (uint32_t f = 0u; f < count; ++f) {
        DF_CHECK(t, c->info[f].is_mega == 0u || reached[f] == 1u);
    }
    /* The refusals. */
    duoforge_mega_info mi = {0xDEADu, 0xDEADu, 0xDEADu, 0xDEADu, 0xDEADu};
    const duoforge_mega_info before = mi;
    uint32_t n = 0xDEADu;
    DF_CHECK(t, duoforge_data_mega_count(NULL, 0u, &n) == DUOFORGE_E_NULL_ARGUMENT && n == 0xDEADu);
    DF_CHECK(t, duoforge_data_mega_count(c->ctx, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_mega_count(c->ctx, count, &n) == DUOFORGE_E_INVALID_ARGUMENT && n == 0xDEADu);
    DF_CHECK(t, duoforge_data_mega_count(c->ctx, 0xFFFFFFFFu, &n) == DUOFORGE_E_INVALID_ARGUMENT && n == 0xDEADu);
    DF_CHECK(t, duoforge_data_mega_at(NULL, 0u, 0u, &mi) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_mega_at(c->ctx, 0u, 0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, duoforge_data_mega_at(c->ctx, count, 0u, &mi) == DUOFORGE_E_INVALID_ARGUMENT &&
                    memcmp(&mi, &before, sizeof mi) == 0);
    DF_CHECK(t, duoforge_data_mega_at(c->ctx, 0u, 0xFFFFFFFFu, &mi) == DUOFORGE_E_INVALID_ARGUMENT &&
                    memcmp(&mi, &before, sizeof mi) == 0);
    /* By name: a second Mega and a shared stone exist only under the POOL kinds. */
    const uint32_t charizard = find_id(t, c, S, "charizard");
    const uint32_t staraptor = find_id(t, c, S, "staraptor");
    uint32_t cc = 0u;
    DF_CHECK(t, duoforge_data_mega_count(c->ctx, charizard, &cc) == DUOFORGE_OK);
    DF_CHECK(t, cc == (c->pool_rules ? 2u : 1u));
    duoforge_mega_info star = {0};
    DF_CHECK(t, duoforge_data_mega_at(c->ctx, staraptor, 0u, &star) == DUOFORGE_OK && star.stone == c->info[staraptor].mega_stone &&
                    star.mega_species == c->info[staraptor].mega_species);
    if (c->pool_rules) {
        const uint32_t I = DUOFORGE_DATA_TABLE_ITEM;
        const uint32_t megax = find_id(t, c, S, "charizardmegax"), megay = find_id(t, c, S, "charizardmegay");
        duoforge_mega_info a = {0}, b2 = {0};
        DF_CHECK(t, duoforge_data_mega_at(c->ctx, charizard, 0u, &a) == DUOFORGE_OK &&
                        duoforge_data_mega_at(c->ctx, charizard, 1u, &b2) == DUOFORGE_OK);
        DF_CHECK(t, a.stone == find_id(t, c, I, "charizarditey") && a.mega_species == megay); /* ascending item id */
        DF_CHECK(t, b2.stone == find_id(t, c, I, "charizarditex") && b2.mega_species == megax);
        DF_CHECK(t, c->info[charizard].mega_species == megay); /* the single link keeps its meaning: the first Mega of the pool */
        /* Meowsticite: one stone, two species, each with its own Mega. */
        const uint32_t m_m = find_id(t, c, S, "meowstic"), m_f = find_id(t, c, S, "meowsticf");
        duoforge_mega_info mm = {0}, mf = {0};
        DF_CHECK(t, duoforge_data_mega_at(c->ctx, m_m, 0u, &mm) == DUOFORGE_OK &&
                        duoforge_data_mega_at(c->ctx, m_f, 0u, &mf) == DUOFORGE_OK);
        DF_CHECK(t, mm.stone == find_id(t, c, I, "meowsticite") && mf.stone == mm.stone);
        DF_CHECK(t, mm.mega_species == find_id(t, c, S, "meowsticmmega") && mf.mega_species == find_id(t, c, S, "meowsticfmega"));
        /* The support flag is the pair's own: over a manifest without Tough Claws Mega-X is unsupported, Mega-Y is not. */
        dfi_support_manifest claws = dfi_support;
        claws.abilities[DFI_ABILITY_TOUGHCLAWS] = 0u;
        const dfi_kind_limits lim = dfi_kind_limits_of(c->kind);
        duoforge_mega_info y = {0}, x = {0};
        dfi_data_mega_at(&lim, &claws, charizard, 0u, &y);
        dfi_data_mega_at(&lim, &claws, charizard, 1u, &x);
        DF_CHECK(t, y.supported == 1u && x.supported == 0u);
    }
}

/* Facts that follow from the decisions and the pinned data, by name. */
static void test_known_facts(df_test *t, const kase *c)
{
    const uint32_t S = DUOFORGE_DATA_TABLE_SPECIES, M = DUOFORGE_DATA_TABLE_MOVE, I = DUOFORGE_DATA_TABLE_ITEM;
    const uint32_t A = DUOFORGE_DATA_TABLE_ABILITY;
    const uint32_t milotic = find_id(t, c, S, "milotic");
    const uint32_t protect = find_id(t, c, M, "protect");
    const uint32_t struggle = find_id(t, c, M, "struggle");
    /* Milotic: Protect is a pool move (decision 0015 section 2) but not in its set. */
    DF_CHECK(t, in_list(c->moves[milotic], c->info[milotic].move_count, protect) == c->pool_rules);
    if (!c->pool_rules) {
        DF_CHECK(t, c->info[milotic].move_count == 4u);
    }
    /* Struggle: a row of the table, found by name, legal for no forme. */
    DF_CHECK(t, struggle == DFI_MOVE_STRUGGLE);
    for (uint32_t sp = 0u; sp < c->n[S]; ++sp) {
        DF_CHECK(t, !in_list(c->moves[sp], c->info[sp].move_count, struggle));
    }
    /* Staraptor holds Staraptite to reach Staraptor-Mega, which is never set up. */
    const uint32_t staraptor = find_id(t, c, S, "staraptor");
    DF_CHECK(t, c->info[staraptor].mega_species == find_id(t, c, S, "staraptormega") &&
                    c->info[staraptor].mega_stone == find_id(t, c, I, "staraptite"));
    const uint32_t mega = c->info[staraptor].mega_species;
    DF_CHECK(t, c->info[mega].is_mega == 1u && c->info[mega].setup_legal == 0u && c->info[mega].move_count == 0u &&
                    c->info[mega].ability_count == 0u && c->info[mega].gender_mask == 0u &&
                    c->info[mega].base_species == staraptor && c->info[mega].mega_species == DUOFORGE_DATA_NONE);
    /* The ability of the closure set, and under the POOL kinds also a pool ability of the forme (Overgrow). */
    const uint32_t rillaboom = find_id(t, c, S, "rillaboom");
    const duoforge_forme_info *ri = &c->info[rillaboom];
    DF_CHECK(t, in_list(ri->abilities, ri->ability_count, find_id(t, c, A, "grassysurge")));
    if (c->pool_rules) {
        DF_CHECK(t, in_list(ri->abilities, ri->ability_count, find_id(t, c, A, "overgrow")));
    } else { /* a pool name is no name of the kind, and so no ability of the forme */
        uint32_t out = 0xA5A5A5A5u;
        DF_CHECK(t, duoforge_data_find(c->ctx, A, "overgrow", 8u, &out) == DUOFORGE_E_INVALID_ARGUMENT);
    }
}

/* ------------------------------------------------------------------ support */

static bool api_supported(df_test *t, const kase *c, uint32_t table, uint32_t id)
{
    bool b = false;
    DF_CHECK(t, duoforge_data_supported(c->ctx, table, id, &b) == DUOFORGE_OK);
    return b;
}

static void test_support(df_test *t, const kase *c)
{
    /* From the manifest's arrays directly. */
    const dfi_support_manifest *s = &dfi_support;
    DF_CHECK(t, s->turn_core != 0u); /* the expectations below assume the turn core, as in this build */
    for (uint32_t id = 0u; id < c->n[DUOFORGE_DATA_TABLE_MOVE]; ++id) {
        if (!DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, id) == (s->moves[id] != 0u))) {
            fprintf(stderr, "  %s move %s\n", c->kind_name, dfi_pool_move_names[id]);
        }
    }
    for (uint32_t id = 0u; id < c->n[DUOFORGE_DATA_TABLE_ITEM]; ++id) {
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, id) == (s->items[id] != 0u));
    }
    for (uint32_t id = 0u; id < c->n[DUOFORGE_DATA_TABLE_ABILITY]; ++id) {
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_ABILITY, id) == (s->abilities[id] != 0u));
    }
    for (uint32_t id = 0u; id < c->n[DUOFORGE_DATA_TABLE_NATURE]; ++id) {
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_NATURE, id));
    }
    for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES]; ++sp) {
        const dfi_pool_forme_data *f = &dfi_pool_formes[sp];
        bool want = true;
        if (f->is_mega != 0u) { /* Mega Evolution into it: the manifest's flag and the ability it brings, and only
                                   the Mega forme that its base forme links (the other Mega formes of Absol, Charizard,
                                   Garchomp, Lucario and Raichu cannot be reached) */
            want = s->mega_evolution != 0u && s->abilities[f->ability] != 0u &&
                   dfi_pool_formes[f->base_forme].mega_forme == sp;
        }
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_SPECIES, sp) == want);
        if (f->is_mega == 0u && f->mega_forme != DFI_FORME_NONE) {
            const bool mega_ok = s->mega_evolution != 0u && s->abilities[dfi_pool_formes[f->mega_forme].ability] != 0u;
            DF_CHECK(t, (c->info[sp].mega_supported != 0u) == mega_ok);
        }
    }
    /* Struggle: literally what the manifest says (unmarked: the turn core runs it, and no member has it). */
    DF_CHECK(t, !api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_STRUGGLE));
    if (c->pool_rules) {
        /* Step G2: Rock Slide is marked; step G5: U-turn is marked; step G8: Throat Chop; step G7: Wide Guard; step G9: Encore (both have handler ids). */
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_ROCKSLIDE));
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_UTURN));
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_THROATCHOP));
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_ENCORE));
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, DFI_MOVE_WIDEGUARD)); /* step G7 */
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_FLOETTITE)); /* step G12 */
        DF_CHECK(t, api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_EXPERTBELT)); /* step G28 */
        DF_CHECK(t, !api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, DFI_ITEM_SCOPELENS));
    }
}

/* ------------------------------------------------------------------- oracle */

/* What setup does with a battle setup, written from the API's answers and the public constants
 * only: INVALID_ARGUMENT for an illegal one, and for a legal one whether the gate lets it pass. */
static bool oracle_member_legal(const kase *c, const duoforge_member_setup *m)
{
    if (m->species_id >= c->n[DUOFORGE_DATA_TABLE_SPECIES] || m->species_id >= DFI_POOL_FORME_COUNT) {
        return false;
    }
    const duoforge_forme_info *in = &c->info[m->species_id];
    if (in->setup_legal == 0u || m->hp_max != 0u || m->mega_capable != 0u) {
        return false;
    }
    if (m->move_count < 1u || m->move_count > DUOFORGE_MAX_MOVE_SLOTS) {
        return false;
    }
    for (uint32_t k = 0u; k < m->move_count; ++k) {
        if (m->moves[k].pp_max != 0u || !in_list(c->moves[m->species_id], in->move_count, m->moves[k].move_id)) {
            return false;
        }
        for (uint32_t j = 0u; j < k; ++j) {
            if (m->moves[j].move_id == m->moves[k].move_id) {
                return false;
            }
        }
    }
    for (uint32_t k = m->move_count; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
        if (m->moves[k].move_id != 0u || m->moves[k].pp_max != 0u) {
            return false;
        }
    }
    if (m->gender < DUOFORGE_GENDER_MALE || m->gender > DUOFORGE_GENDER_NONE ||
        (in->gender_mask & (1u << (m->gender - 1u))) == 0u) {
        return false;
    }
    if (m->nature >= c->n[DUOFORGE_DATA_TABLE_NATURE]) {
        return false;
    }
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < 6u; ++i) {
        if (m->stat_points[i] > DUOFORGE_STAT_POINTS_MAX) {
            return false;
        }
        total += m->stat_points[i];
    }
    if (total > DUOFORGE_STAT_POINTS_TOTAL_MAX) {
        return false;
    }
    if (m->ability == 0u ? in->no_ability == 0u : !in_list(in->abilities, in->ability_count, m->ability - 1u)) {
        return false;
    }
    return m->item <= c->n[DUOFORGE_DATA_TABLE_ITEM];
}

/* The support gate of one legal member, from duoforge_data_supported and the forme's info. */
static bool oracle_member_supported(df_test *t, const kase *c, const duoforge_member_setup *m)
{
    const duoforge_forme_info *in = &c->info[m->species_id];
    if (!api_supported(t, c, DUOFORGE_DATA_TABLE_SPECIES, m->species_id)) {
        return false;
    }
    for (uint32_t k = 0u; k < m->move_count; ++k) {
        if (!api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, m->moves[k].move_id)) {
            return false;
        }
    }
    if (m->ability != 0u && !api_supported(t, c, DUOFORGE_DATA_TABLE_ABILITY, m->ability - 1u)) {
        return false;
    }
    if (m->item != 0u && !api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, m->item - 1u)) {
        return false;
    }
    /* A Mega Stone of the forme: Mega Evolution through that stone has to be supported (one stone each, from the API). */
    uint32_t stones = 0u;
    DF_CHECK(t, duoforge_data_mega_count(c->ctx, m->species_id, &stones) == DUOFORGE_OK);
    for (uint32_t i = 0u; i < stones; ++i) {
        duoforge_mega_info mi;
        DF_CHECK(t, duoforge_data_mega_at(c->ctx, m->species_id, i, &mi) == DUOFORGE_OK);
        if (m->item == mi.stone + 1u && mi.supported == 0u) {
            return false;
        }
    }
    (void)in;
    return true;
}

/* INVALID_ARGUMENT, or OK (legal and supported), or UNSUPPORTED (legal, not supported). */
static duoforge_status oracle_setup(df_test *t, const kase *c, const duoforge_battle_setup *s)
{
    bool supported = true;
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        const duoforge_side_setup *sd = &s->sides[side];
        for (uint32_t a = 0u; a < sd->member_count; ++a) {
            if (!oracle_member_legal(c, &sd->members[a])) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
        for (uint32_t a = 0u; a < sd->member_count; ++a) { /* Species Clause and Item Clause */
            for (uint32_t b = 0u; b < a; ++b) {
                const duoforge_member_setup *x = &sd->members[a], *y = &sd->members[b];
                if (c->info[x->species_id].dex_num == c->info[y->species_id].dex_num ||
                    (x->item != 0u && x->item == y->item)) {
                    return DUOFORGE_E_INVALID_ARGUMENT;
                }
            }
        }
        for (uint32_t a = 0u; a < sd->member_count; ++a) {
            supported = supported && oracle_member_supported(t, c, &sd->members[a]);
        }
    }
    return supported ? DUOFORGE_OK : DUOFORGE_E_UNSUPPORTED;
}

/* Setup against the oracle, with the public create (gated) and the white-box one (not gated). */
static unsigned long g_outcomes[KIND_COUNT][3]; /* OK, UNSUPPORTED, INVALID_ARGUMENT by kind */

static void check_setup(df_test *t, kase *c, const duoforge_battle_setup *s, const char *what)
{
    const duoforge_status want = oracle_setup(t, c, s);
    duoforge_battle *made = NULL;
    const duoforge_status got = duoforge_battle_create(c->ctx, s, &made);
    bool ok = got == want && (made != NULL) == (want == DUOFORGE_OK);
    duoforge_battle_destroy(made);
    duoforge_battle *raw = NULL;
    const duoforge_status raw_want = want == DUOFORGE_E_INVALID_ARGUMENT ? want : DUOFORGE_OK;
    const duoforge_status raw_got = dfi_battle_create_ungated(c->ctx, s, &raw);
    ok = ok && raw_got == raw_want && (raw != NULL) == (raw_want == DUOFORGE_OK);
    duoforge_battle_destroy(raw);
    if (!DF_CHECK(t, ok)) {
        fprintf(stderr, "  %s %s: create %s (ungated %s), the API says %s\n", c->kind_name, what, status_text(got),
                status_text(raw_got), status_text(want));
    }
    const size_t idx = (size_t)(c - g_kase);
    g_outcomes[idx][want == DUOFORGE_OK ? 0 : want == DUOFORGE_E_UNSUPPORTED ? 1 : 2] += 1u;
}

/* ------------------------------------------------------------ side building */

typedef enum pick_mode { PICK_SUPPORTED, PICK_ANY } pick_mode;

/* True iff the forme can give a member that the gate lets pass. */
static bool forme_pickable(df_test *t, const kase *c, uint32_t sp, pick_mode mode)
{
    const duoforge_forme_info *in = &c->info[sp];
    if (in->setup_legal == 0u || in->move_count == 0u || (in->ability_count == 0u && !c->dev)) {
        return false;
    }
    if (mode == PICK_ANY) {
        return true;
    }
    bool move = false, ability = c->dev;
    for (uint32_t k = 0u; k < in->move_count; ++k) {
        move = move || api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, c->moves[sp][k]);
    }
    for (uint32_t k = 0u; k < in->ability_count; ++k) {
        ability = ability || api_supported(t, c, DUOFORGE_DATA_TABLE_ABILITY, in->abilities[k]);
    }
    return move && ability && api_supported(t, c, DUOFORGE_DATA_TABLE_SPECIES, sp);
}

/* A member of the forme made only from what the API reports; under PICK_SUPPORTED also only from
 * what it reports as supported (the stone only when its Mega Evolution is). */
static void build_member(df_test *t, const kase *c, uint64_t *rng, uint32_t sp, pick_mode mode,
                         duoforge_member_setup *m)
{
    const duoforge_forme_info *in = &c->info[sp];
    memset(m, 0, sizeof *m);
    m->species_id = sp;
    /* 1 to 4 distinct moves of the forme's list. */
    uint32_t want = 1u + rng_below(rng, DUOFORGE_MAX_MOVE_SLOTS);
    uint32_t guard = 0u;
    while (m->move_count < want && guard++ < 400u) {
        const uint32_t mv = c->moves[sp][rng_below(rng, in->move_count)];
        if (mode == PICK_SUPPORTED && !api_supported(t, c, DUOFORGE_DATA_TABLE_MOVE, mv)) {
            continue;
        }
        bool dup = false;
        for (uint32_t k = 0u; k < m->move_count; ++k) {
            dup = dup || m->moves[k].move_id == mv;
        }
        if (!dup) {
            m->moves[m->move_count++].move_id = mv;
        }
    }
    if (m->move_count == 0u) { /* PICK_ANY can always find one; PICK_SUPPORTED was checked by forme_pickable */
        m->moves[0].move_id = c->moves[sp][0];
        m->move_count = 1u;
    }
    /* An ability of the list, or No Ability where legal (a quarter of the time). */
    m->ability = 0u;
    if (!(c->dev && rng_below(rng, 4u) == 0u)) {
        for (uint32_t tries = 0u; tries < 200u; ++tries) {
            const uint32_t ab = in->abilities[rng_below(rng, in->ability_count)];
            if (mode == PICK_ANY || api_supported(t, c, DUOFORGE_DATA_TABLE_ABILITY, ab)) {
                m->ability = ab + 1u;
                break;
            }
        }
    }
    /* A gender of the mask. */
    uint32_t genders[3], ng = 0u;
    for (uint32_t g = DUOFORGE_GENDER_MALE; g <= DUOFORGE_GENDER_NONE; ++g) {
        if ((in->gender_mask & (1u << (g - 1u))) != 0u) {
            genders[ng++] = g;
        }
    }
    m->gender = genders[rng_below(rng, ng)];
    m->nature = rng_below(rng, c->n[DUOFORGE_DATA_TABLE_NATURE]);
    /* Stat Points within the constants: up to the per-stat and the total maximum. */
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < 6u; ++i) {
        uint32_t v = rng_below(rng, DUOFORGE_STAT_POINTS_MAX + 1u);
        if (total + v > DUOFORGE_STAT_POINTS_TOTAL_MAX) {
            v = DUOFORGE_STAT_POINTS_TOTAL_MAX - total;
        }
        m->stat_points[i] = v;
        total += v;
    }
    /* Any item below the count, or none (a third of the time). */
    m->item = 0u;
    if (rng_below(rng, 3u) != 0u) {
        const uint32_t it = rng_below(rng, c->n[DUOFORGE_DATA_TABLE_ITEM]);
        const bool is_stone = in->mega_stone != DUOFORGE_DATA_NONE && it == in->mega_stone;
        if (mode == PICK_ANY ||
            (api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, it) && (!is_stone || in->mega_supported != 0u))) {
            m->item = it + 1u;
        }
    }
    /* Favour the forme's own stone now and then, so that the Mega gate is reached. */
    if (in->mega_stone != DUOFORGE_DATA_NONE && rng_below(rng, 4u) == 0u) {
        if (mode == PICK_ANY || (api_supported(t, c, DUOFORGE_DATA_TABLE_ITEM, in->mega_stone) &&
                                 in->mega_supported != 0u)) {
            m->item = in->mega_stone + 1u;
        }
    }
}

/* A side of legal members: distinct dex numbers and items, `count` members. */
static void build_side(df_test *t, const kase *c, uint64_t *rng, pick_mode mode, uint32_t count,
                       duoforge_side_setup *side)
{
    memset(side, 0, sizeof *side);
    uint32_t guard = 0u;
    while (side->member_count < count && guard++ < 5000u) {
        const uint32_t sp = rng_below(rng, c->n[DUOFORGE_DATA_TABLE_SPECIES]);
        if (!forme_pickable(t, c, sp, mode)) {
            continue;
        }
        duoforge_member_setup m;
        build_member(t, c, rng, sp, mode, &m);
        bool clash = false;
        for (uint32_t a = 0u; a < side->member_count; ++a) {
            clash = clash || c->info[side->members[a].species_id].dex_num == c->info[sp].dex_num ||
                    (m.item != 0u && m.item == side->members[a].item);
        }
        if (!clash) {
            side->members[side->member_count++] = m;
        }
    }
}

static uint32_t side_size(const kase *c, uint64_t *rng)
{
    return c->dev ? 4u + rng_below(rng, 3u) : DUOFORGE_MAX_ROSTER; /* the DEV kinds register 4 to 6, the others 6 */
}

static void fill_setup(df_test *t, const kase *c, uint64_t *rng, pick_mode mode, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = rng_next(rng);
    s->rng_initseq = 1u + rng_below(rng, 1000u);
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        build_side(t, c, rng, mode, side_size(c, rng), &s->sides[side]);
    }
}

/* ------------------------------------------------------------ random setups */

#define RANDOM_BATTLES 150u
#define MUTATIONS_PER_BATTLE 4u

static void apply_mutation(const kase *c, uint64_t *rng, duoforge_battle_setup *s, uint32_t *which)
{
    const uint32_t side = rng_below(rng, DUOFORGE_SIDE_COUNT);
    duoforge_side_setup *sd = &s->sides[side];
    duoforge_member_setup *m = &sd->members[rng_below(rng, sd->member_count)];
    const duoforge_forme_info *in = &c->info[m->species_id];
    *which = rng_below(rng, 9u);
    uint32_t v;
    switch (*which) {
    case 0: /* a move the API does not list: any id of the pool tables or beyond, not in the forme's list */
        do {
            v = rng_below(rng, DFI_POOL_MOVE_COUNT + 3u);
        } while (in_list(c->moves[m->species_id], in->move_count, v));
        m->moves[rng_below(rng, m->move_count)].move_id = v;
        break;
    case 1: /* an ability the API does not list (or No Ability where it is not legal) */
        do {
            v = rng_below(rng, DFI_POOL_ABILITY_COUNT + 3u);
        } while (v != 0u && in_list(in->abilities, in->ability_count, v - 1u));
        if (v == 0u && c->dev) {
            v = DFI_POOL_ABILITY_COUNT + 1u;
        }
        m->ability = v;
        break;
    case 2: /* a gender the mask excludes */
        do {
            v = rng_below(rng, 6u);
        } while (v >= DUOFORGE_GENDER_MALE && v <= DUOFORGE_GENDER_NONE && (in->gender_mask & (1u << (v - 1u))) != 0u);
        m->gender = v;
        break;
    case 3: /* an item beyond the kind's count */
        m->item = c->n[DUOFORGE_DATA_TABLE_ITEM] + 1u + rng_below(rng, DFI_POOL_ITEM_COUNT);
        break;
    case 4: /* a species beyond the kind's count */
        m->species_id = c->n[DUOFORGE_DATA_TABLE_SPECIES] + rng_below(rng, 5u);
        break;
    case 5: { /* a Mega forme as the member's species */
        uint32_t megas[DFI_POOL_FORME_COUNT], n = 0u;
        for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES]; ++sp) {
            if (c->info[sp].is_mega != 0u) {
                megas[n++] = sp;
            }
        }
        m->species_id = megas[rng_below(rng, n)];
        break;
    }
    case 6: /* a nature beyond the table */
        m->nature = c->n[DUOFORGE_DATA_TABLE_NATURE] + rng_below(rng, 4u);
        break;
    case 7: /* Stat Points above a constant: one stat, or the total */
        if (rng_below(rng, 2u) == 0u) {
            m->stat_points[rng_below(rng, 6u)] = DUOFORGE_STAT_POINTS_MAX + 1u;
        } else {
            for (uint32_t i = 0u; i < 6u; ++i) {
                m->stat_points[i] = 12u; /* 72 in all */
            }
        }
        break;
    default: /* the same move twice */
        if (m->move_count >= 2u) {
            m->moves[1].move_id = m->moves[0].move_id;
        } else {
            m->moves[1].move_id = m->moves[0].move_id;
            m->move_count = 2u;
        }
        break;
    }
}

static void test_random_setups(df_test *t, kase *c, uint32_t kind_index)
{
    uint64_t rng = 0xD0F0D0F0ull + kind_index * 0x1000193ull;
    for (uint32_t i = 0u; i < RANDOM_BATTLES; ++i) {
        duoforge_battle_setup s;
        fill_setup(t, c, &rng, i % 2u == 0u ? PICK_SUPPORTED : PICK_ANY, &s);
        check_setup(t, c, &s, "random");
        for (uint32_t k = 0u; k < MUTATIONS_PER_BATTLE; ++k) {
            duoforge_battle_setup bad = s;
            uint32_t which = 0u;
            apply_mutation(c, &rng, &bad, &which);
            /* The oracle must call it illegal (the mutation really is outside the API's lists); and setup agrees. */
            if (!DF_CHECK(t, oracle_setup(t, c, &bad) == DUOFORGE_E_INVALID_ARGUMENT)) {
                fprintf(stderr, "  %s mutation %u was not excluded by the API\n", c->kind_name, which);
            }
            check_setup(t, c, &bad, "mutated");
        }
    }
    /* Non-vacuity: legal sides were accepted; and where something is unmarked, refused after validation. */
    DF_CHECK(t, g_outcomes[kind_index][0] > 0u);
    DF_CHECK(t, g_outcomes[kind_index][2] >= RANDOM_BATTLES);
    if (c->pool_rules) {
        DF_CHECK(t, g_outcomes[kind_index][1] > 0u);
    }
}

/* ---------------------------------------------------------- exhaustive sweep */

/* The fillers of a swept setup: members that hold nothing (no item), supported, with different dex numbers; the
 * first ones that the tables give, built once per kind. */
static void ensure_fillers(df_test *t, kase *c)
{
    if (c->n_filler != 0u) {
        return;
    }
    uint64_t rng = 7u;
    for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES] && c->n_filler < 8u; ++sp) {
        if (!forme_pickable(t, c, sp, PICK_SUPPORTED)) {
            continue;
        }
        const uint32_t dex = c->info[sp].dex_num;
        if (in_list(c->filler_dex, c->n_filler, dex)) {
            continue;
        }
        build_member(t, c, &rng, sp, PICK_SUPPORTED, &c->filler[c->n_filler]);
        c->filler[c->n_filler].item = 0u;
        c->filler_dex[c->n_filler] = dex;
        c->n_filler += 1u;
    }
}

/* A side-0 member under test, with the rest of both sides made of fillers whose dex numbers differ from the member's. */
static void fillers(const kase *c, uint32_t avoid_dex, duoforge_side_setup *side, uint32_t count)
{
    for (uint32_t k = 0u; k < c->n_filler && side->member_count < count; ++k) {
        if (c->filler_dex[k] != avoid_dex) {
            side->members[side->member_count++] = c->filler[k];
        }
    }
}

static void sweep_member(df_test *t, kase *c, const duoforge_member_setup *under_test)
{
    ensure_fillers(t, c);
    duoforge_battle_setup s;
    memset(&s, 0, sizeof s);
    s.rng_initseq = 1u;
    uint32_t avoid = 0xFFFFFFFFu;
    if (under_test->species_id < c->n[DUOFORGE_DATA_TABLE_SPECIES]) {
        avoid = c->info[under_test->species_id].dex_num;
    }
    const uint32_t count = c->dev ? 4u : DUOFORGE_MAX_ROSTER;
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        if (side == 0u) {
            s.sides[0].members[0] = *under_test;
            s.sides[0].member_count = 1u;
        }
        fillers(c, avoid, &s.sides[side], count);
        DF_CHECK(t, s.sides[side].member_count == count); /* the fixture needs enough supported fillers */
    }
    check_setup(t, c, &s, "sweep");
}

/* The formes that get the full sweep, every move, ability, gender, item and nature id against them: the prefix (the
 * closure, Team C and G2), every 23rd forme, and the formes with two Mega formes or a Mega Stone that two bases
 * share (Absol, Charizard, Garchomp, Lucario, Raichu, Meowstic). The others get the light sweep: the member as the
 * API describes it, each id the API lists for it, and a few ids it does not list. The whole pool has 346 formes, so a
 * full sweep of each would be 300 thousand setups per kind. */
static bool full_sweep(const kase *c, uint32_t sp)
{
    const uint32_t dex = c->info[sp].dex_num;
    return sp < DFI_EXT_FORME_COUNT + 5u || sp % 23u == 0u || dex == 359u || dex == 6u || dex == 445u || dex == 448u ||
           dex == 26u || dex == 678u;
}

static void test_exhaustive(df_test *t, kase *c)
{
    const uint32_t S = DUOFORGE_DATA_TABLE_SPECIES;
    duoforge_member_setup base;
    uint64_t rng = 99u;
    for (uint32_t sp = 0u; sp < c->n[S]; ++sp) {
        if (!forme_pickable(t, c, sp, PICK_ANY)) {
            continue;
        }
        build_member(t, c, &rng, sp, PICK_SUPPORTED, &base);
        /* The base member is legal; every variant is the base with one field changed. */
        base.item = 0u;
        base.move_count = 1u;
        memset(&base.moves[1], 0, sizeof base.moves[1] * (DUOFORGE_MAX_MOVE_SLOTS - 1u));
        sweep_member(t, c, &base);
        duoforge_member_setup m = base;
        if (full_sweep(c, sp)) {
            for (uint32_t mv = 0u; mv < DFI_POOL_MOVE_COUNT + 2u; ++mv) {
                m = base;
                m.moves[0].move_id = mv;
                sweep_member(t, c, &m);
            }
            for (uint32_t ab = 0u; ab < DFI_POOL_ABILITY_COUNT + 3u; ++ab) {
                m = base;
                m.ability = ab;
                sweep_member(t, c, &m);
            }
            for (uint32_t it = 0u; it < DFI_POOL_ITEM_COUNT + 3u; ++it) {
                m = base;
                m.item = it;
                sweep_member(t, c, &m);
            }
        } else {
            const duoforge_forme_info *in = &c->info[sp];
            for (uint32_t k = 0u; k < in->move_count; ++k) { /* the moves the API lists */
                m = base;
                m.moves[0].move_id = c->moves[sp][k];
                sweep_member(t, c, &m);
            }
            for (uint32_t k = 0u; k < 4u; ++k) { /* and some that it does not (the nearest ids below and above) */
                for (uint32_t mv = (sp * 7u + k * 131u) % (DFI_POOL_MOVE_COUNT + 2u);; mv = (mv + 1u) % (DFI_POOL_MOVE_COUNT + 2u)) {
                    if (mv >= DFI_POOL_MOVE_COUNT || !in_list(c->moves[sp], in->move_count, mv)) {
                        m = base;
                        m.moves[0].move_id = mv;
                        sweep_member(t, c, &m);
                        break;
                    }
                }
            }
            for (uint32_t k = 0u; k < in->ability_count; ++k) { /* the abilities the API lists, and 4 it does not */
                m = base;
                m.ability = in->abilities[k] + 1u;
                sweep_member(t, c, &m);
            }
            for (uint32_t k = 0u; k < 4u; ++k) {
                for (uint32_t ab = (sp * 5u + k * 53u) % (DFI_POOL_ABILITY_COUNT + 3u);;
                     ab = (ab + 1u) % (DFI_POOL_ABILITY_COUNT + 3u)) {
                    if (ab == 0u ? !c->dev : (ab > DFI_POOL_ABILITY_COUNT || !in_list(in->abilities, in->ability_count, ab - 1u))) {
                        m = base;
                        m.ability = ab;
                        sweep_member(t, c, &m);
                        break;
                    }
                }
            }
            for (uint32_t it = sp % 7u; it < DFI_POOL_ITEM_COUNT + 3u; it += 7u) {
                m = base;
                m.item = it;
                sweep_member(t, c, &m);
            }
        }
        for (uint32_t g = 0u; g < 6u; ++g) {
            m = base;
            m.gender = g;
            sweep_member(t, c, &m);
        }
        for (uint32_t nat = 0u; nat < DFI_NATURE_COUNT + 3u; nat += (full_sweep(c, sp) ? 1u : 12u)) {
            m = base;
            m.nature = nat;
            sweep_member(t, c, &m);
        }
    }
    /* Every species id of the pool tables and beyond, as the member's species. */
    for (uint32_t sp = 0u; sp < DFI_POOL_FORME_COUNT + 3u; ++sp) {
        duoforge_member_setup m;
        memset(&m, 0, sizeof m);
        m.species_id = sp;
        m.move_count = 1u;
        m.moves[0].move_id = sp < DFI_POOL_FORME_COUNT && c->info[sp].move_count > 0u ? c->moves[sp][0] : 0u;
        m.gender = DUOFORGE_GENDER_MALE;
        m.ability = 1u;
        sweep_member(t, c, &m);
    }
}

/* Every row of the move, item, ability and species tables is in a setup that the oracle judges (decision 0015
 * section 4.2): for each id, a member that legally has it and is otherwise as supported as its forme allows, and
 * setup must say OK, or E_UNSUPPORTED exactly when the API says the row (or something else of the member) is not
 * supported. A row that no forme can have is counted (Struggle, and the Mega formes for the species table). */
static void test_every_row(df_test *t, kase *c)
{
    static uint32_t first_move[DFI_POOL_MOVE_COUNT];
    static uint32_t first_ability[DFI_POOL_ABILITY_COUNT];
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        first_move[i] = 0xFFFFFFFFu;
    }
    for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
        first_ability[i] = 0xFFFFFFFFu;
    }
    /* Prefer a forme that is otherwise supported; else any forme that has the row. */
    for (int pass = 0; pass < 2; ++pass) {
        for (uint32_t sp = 0u; sp < c->n[DUOFORGE_DATA_TABLE_SPECIES]; ++sp) {
            if (c->info[sp].setup_legal == 0u || (pass == 0 && !forme_pickable(t, c, sp, PICK_SUPPORTED))) {
                continue;
            }
            for (uint32_t k = 0u; k < c->info[sp].move_count; ++k) {
                if (first_move[c->moves[sp][k]] == 0xFFFFFFFFu) {
                    first_move[c->moves[sp][k]] = sp;
                }
            }
            for (uint32_t k = 0u; k < c->info[sp].ability_count; ++k) {
                if (first_ability[c->info[sp].abilities[k]] == 0xFFFFFFFFu) {
                    first_ability[c->info[sp].abilities[k]] = sp;
                }
            }
        }
    }
    uint64_t rng = 4242u;
    duoforge_member_setup m;
    uint32_t nobody = 0u;
    for (uint32_t mv = 0u; mv < c->n[DUOFORGE_DATA_TABLE_MOVE]; ++mv) {
        if (first_move[mv] == 0xFFFFFFFFu) {
            nobody += 1u; /* Struggle: the engine's own, no forme has it */
            continue;
        }
        build_member(t, c, &rng, first_move[mv], PICK_SUPPORTED, &m);
        m.item = 0u;
        m.moves[0].move_id = mv;
        m.move_count = 1u;
        memset(&m.moves[1], 0, sizeof m.moves[1] * (DUOFORGE_MAX_MOVE_SLOTS - 1u));
        sweep_member(t, c, &m);
    }
    DF_CHECK(t, nobody <= 1u);
    for (uint32_t ab = 0u; ab < c->n[DUOFORGE_DATA_TABLE_ABILITY]; ++ab) {
        if (first_ability[ab] == 0xFFFFFFFFu) {
            continue; /* a Mega-only ability: no base forme lists it */
        }
        build_member(t, c, &rng, first_ability[ab], PICK_SUPPORTED, &m);
        m.item = 0u;
        m.ability = ab + 1u;
        sweep_member(t, c, &m);
    }
    const uint32_t sp0 = first_move[DFI_MOVE_PROTECT];
    for (uint32_t it = 0u; it < c->n[DUOFORGE_DATA_TABLE_ITEM]; ++it) {
        build_member(t, c, &rng, sp0, PICK_SUPPORTED, &m);
        m.item = it + 1u;
        sweep_member(t, c, &m);
    }
}
/* ------------------------------------------- the composition of the support gate */

/* The gate composition of the header (a member is supported exactly when its ability, item and
 * moves are, and its forme's Mega Evolution when it holds the stone) against the white-box gate,
 * over manifests of this test's own: each flag random. */
static void test_gate_composition(df_test *t, kase *c, uint32_t kind_index)
{
    uint64_t rng = 0xFEED0000ull + kind_index;
    const dfi_kind_limits lim = dfi_kind_limits_of(c->kind);
    unsigned long supported_seen = 0u, refused_seen = 0u;
    for (uint32_t round = 0u; round < 300u; ++round) {
        dfi_support_manifest manifest;
        /* 10 to 90 percent of the flags, and every fourth manifest has all of them. */
        const uint32_t density = round % 4u == 0u ? 10u : 1u + rng_below(&rng, 9u);
        manifest.turn_core = rng_below(&rng, 12u) != 0u ? 1u : 0u;
        manifest.switching = 1u;
        manifest.mega_evolution = rng_below(&rng, 3u) != 0u ? 1u : 0u;
        for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
            manifest.moves[i] = rng_below(&rng, 10u) < density ? 1u : 0u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
            manifest.abilities[i] = rng_below(&rng, 10u) < density ? 1u : 0u;
        }
        for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
            manifest.items[i] = rng_below(&rng, 10u) < density ? 1u : 0u;
        }
        duoforge_battle_setup s;
        fill_setup(t, c, &rng, PICK_ANY, &s);
        /* Sometimes put each member's own stone in its item slot, so that the Mega gate is reached. */
        for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
            for (uint32_t a = 0u; a < s.sides[side].member_count; ++a) {
                duoforge_member_setup *m = &s.sides[side].members[a];
                const duoforge_forme_info *in = &c->info[m->species_id];
                bool clash = false;
                for (uint32_t b = 0u; b < s.sides[side].member_count; ++b) {
                    clash = clash || (b != a && in->mega_stone != DUOFORGE_DATA_NONE &&
                                      s.sides[side].members[b].item == in->mega_stone + 1u);
                }
                if (in->mega_stone != DUOFORGE_DATA_NONE && !clash && rng_below(&rng, 2u) == 0u) {
                    m->item = in->mega_stone + 1u;
                }
            }
        }
        /* The composition, from the white-box id answers and forme infos over this manifest. */
        bool want = manifest.turn_core != 0u;
        for (uint32_t side = 0u; want && side < DUOFORGE_SIDE_COUNT; ++side) {
            for (uint32_t a = 0u; want && a < s.sides[side].member_count; ++a) {
                const duoforge_member_setup *m = &s.sides[side].members[a];
                duoforge_forme_info in;
                dfi_data_forme_info(&lim, &manifest, m->species_id, &in);
                want = dfi_data_supported(&manifest, DUOFORGE_DATA_TABLE_SPECIES, m->species_id);
                for (uint32_t k = 0u; k < m->move_count; ++k) {
                    want = want && dfi_data_supported(&manifest, DUOFORGE_DATA_TABLE_MOVE, m->moves[k].move_id);
                }
                want = want && (m->ability == 0u ||
                                dfi_data_supported(&manifest, DUOFORGE_DATA_TABLE_ABILITY, m->ability - 1u));
                want = want &&
                       (m->item == 0u || dfi_data_supported(&manifest, DUOFORGE_DATA_TABLE_ITEM, m->item - 1u));
                want = want && !(in.mega_stone != DUOFORGE_DATA_NONE && m->item == in.mega_stone + 1u &&
                                 in.mega_supported == 0u);
            }
        }
        const bool got = dfi_closure_setup_supported(&manifest, &s);
        if (!DF_CHECK(t, got == want)) {
            fprintf(stderr, "  %s round %u: the gate says %d, the composition %d\n", c->kind_name, round, got, want);
        }
        if (got) {
            supported_seen += 1u;
        } else {
            refused_seen += 1u;
        }
    }
    DF_CHECK(t, supported_seen > 0u && refused_seen > 0u);
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.data.api");

    for (uint32_t k = 0u; k < KIND_COUNT; ++k) {
        load_kase(&t, &g_kase[k], k_kinds[k], k_kind_names[k]);
    }
    test_generated_names(&t);
    test_synthetic(&t);
    for (uint32_t k = 0u; k < KIND_COUNT; ++k) {
        kase *c = &g_kase[k];
        if (c->ctx == NULL) {
            continue;
        }
        test_counts_and_round_trip(&t, c);
        test_refusals(&t, c);
        test_aliases(&t, c);
        test_forme_info(&t, c);
        test_known_facts(&t, c);
        test_mega_by_stone(&t, c);
        test_support(&t, c);
        test_random_setups(&t, c, k);
        test_exhaustive(&t, c);
        test_every_row(&t, c);
        test_gate_composition(&t, c, k);
        fprintf(stderr, "  %s: setups OK %lu, UNSUPPORTED %lu, INVALID_ARGUMENT %lu\n", c->kind_name,
                g_outcomes[k][0], g_outcomes[k][1], g_outcomes[k][2]);
    }
    for (uint32_t k = 0u; k < KIND_COUNT; ++k) {
        duoforge_context_destroy(g_kase[k].ctx);
    }
    return df_test_end(&t);
}
