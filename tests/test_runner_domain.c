/*
 * duoforge.reference.runner_domain (white-box: the fixtures poke the state):
 * the domain check of the differential runner (tools/difftest/domain.c), the
 * engine's candidates for a side against the set of choices that the reference
 * accepted. Checked: how a candidate becomes a member of a set; that the
 * engine's own candidates, in any order, are the same set as themselves; and
 * the controls that make the check worth anything: a choice taken out of the
 * reference's set must come out engine-only, one put in reference-only, with
 * the examples in the order of the sets and no more than DFD_EXAMPLES of each,
 * and a candidate that the engine lists twice engine-only. The text of a
 * choice (what the messages say) is pinned too.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "domain.h"
#include "support/check.h"
#include "support/fixtures.h"

static duoforge_side_choice candidates[DUOFORGE_MAX_CANDIDATES];
static dfr_choice engine[DUOFORGE_MAX_CANDIDATES];
static dfr_choice reference[DUOFORGE_MAX_CANDIDATES + 2u];
static dfr_choice scratch[DUOFORGE_MAX_CANDIDATES + 2u];

static int by_bytes(const void *a, const void *b)
{
    return memcmp(a, b, sizeof(dfr_choice));
}

/* The candidates of a player as choices, in the engine's order; the count. */
static uint32_t engine_choices(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player)
{
    uint32_t count = 0u;
    const duoforge_status st =
        duoforge_battle_candidates(ctx, b, player, candidates, DUOFORGE_MAX_CANDIDATES, &count);
    if (!DF_CHECK(t, st == DUOFORGE_OK && count > 0u && count <= DUOFORGE_MAX_CANDIDATES)) {
        return 0u;
    }
    for (uint32_t i = 0u; i < count; ++i) {
        engine[i] = dfd_choice_of(&candidates[i]);
    }
    return count;
}

/* The reference's set that equals the engine's: the same choices, in ascending order. */
static void reference_equal(uint32_t n)
{
    memcpy(reference, engine, n * sizeof engine[0]);
    qsort(reference, n, sizeof reference[0], by_bytes);
}

/* dfd_compare on copies, so that the engine's list stays as the engine made it. */
static dfd_diff compare(const dfr_choice *e, uint32_t en, const dfr_choice *r, uint32_t rn)
{
    dfd_diff d;
    memcpy(scratch, e, en * sizeof scratch[0]);
    dfd_compare(scratch, en, r, rn, &d);
    return d;
}

static dfr_choice bogus_team(uint8_t last)
{
    dfr_choice c;
    memset(&c, 0, sizeof c);
    c.kind = DUOFORGE_CHOICE_TEAM_SELECTION;
    c.pick_count = 4u;
    c.picks[0] = 5u;
    c.picks[1] = 4u;
    c.picks[2] = 3u;
    c.picks[3] = last;
    return c;
}

static void mapping(df_test *t)
{
    duoforge_side_choice team;
    memset(&team, 0, sizeof team);
    team.epoch = 7u;
    team.side = 1u;
    team.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
    team.pick_count = 4u;
    team.picks[0] = 3u;
    team.picks[1] = 1u;
    team.picks[2] = 0u;
    team.picks[3] = 2u;
    dfr_choice c = dfd_choice_of(&team);
    DF_CHECK_EQ_U64(t, c.kind, DUOFORGE_CHOICE_TEAM_SELECTION);
    DF_CHECK_EQ_U64(t, c.pick_count, 4u);
    DF_CHECK(t, memcmp(c.picks, (const uint8_t[6]){3u, 1u, 0u, 2u, 0u, 0u}, 6u) == 0);
    DF_CHECK(t, c.slots[0].kind == 0u && c.slots[1].kind == 0u);

    duoforge_side_choice slots;
    memset(&slots, 0, sizeof slots);
    slots.epoch = 9u;
    slots.side = 0u;
    slots.kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
    slots.slots[0] = (duoforge_slot_command){DUOFORGE_SLOT_MOVE, 2u, 3u, 1u, 0u, {0u, 0u, 0u}};
    slots.slots[1] = (duoforge_slot_command){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 5u, {0u, 0u, 0u}};
    c = dfd_choice_of(&slots);
    DF_CHECK_EQ_U64(t, c.kind, DUOFORGE_CHOICE_SLOTS);
    DF_CHECK_EQ_U64(t, c.pick_count, 0u);
    DF_CHECK(t, c.slots[0].kind == DUOFORGE_SLOT_MOVE && c.slots[0].move_slot == 2u && c.slots[0].target == 3u &&
                    c.slots[0].mega == 1u && c.slots[0].reserve == 0u);
    DF_CHECK(t, c.slots[1].kind == DUOFORGE_SLOT_SWITCH && c.slots[1].reserve == 5u && c.slots[1].move_slot == 0u);
    /* The epoch and the side are not part of a choice. */
    slots.epoch = 10u;
    slots.side = 1u;
    const dfr_choice again = dfd_choice_of(&slots);
    DF_CHECK(t, memcmp(&again, &c, sizeof c) == 0);
}

static void format(df_test *t)
{
    char text[128];
    dfr_choice c;
    memset(&c, 0, sizeof c);
    c.kind = DUOFORGE_CHOICE_TEAM_SELECTION;
    c.pick_count = 4u;
    c.picks[0] = 2u;
    c.picks[1] = 4u;
    c.picks[2] = 0u;
    c.picks[3] = 1u;
    dfd_format(&c, text, sizeof text);
    DF_CHECK(t, strcmp(text, "team 2 4 0 1") == 0);
    memset(&c, 0, sizeof c);
    c.kind = DUOFORGE_CHOICE_SLOTS;
    c.slots[0] = (df_conf_cmd){DUOFORGE_SLOT_MOVE, 1u, 2u, 1u, 0u};
    c.slots[1] = (df_conf_cmd){DUOFORGE_SLOT_SWITCH, 0u, 0u, 0u, 3u};
    dfd_format(&c, text, sizeof text);
    DF_CHECK(t, strcmp(text, "slots move 1 -> 2 mega, switch 3") == 0);
    c.slots[0] = (df_conf_cmd){DUOFORGE_SLOT_MOVE, 4u, DUOFORGE_TARGET_NONE, 0u, 0u};
    c.slots[1] = (df_conf_cmd){DUOFORGE_SLOT_PASS, 0u, 0u, 0u, 0u};
    dfd_format(&c, text, sizeof text);
    DF_CHECK(t, strcmp(text, "slots move 4 -> none, pass") == 0);
    c.slots[0] = (df_conf_cmd){DUOFORGE_SLOT_NONE, 0u, 0u, 0u, 0u};
    c.slots[1] = (df_conf_cmd){DUOFORGE_SLOT_MOVE, 0u, 0u, 0u, 0u};
    dfd_format(&c, text, sizeof text);
    DF_CHECK(t, strcmp(text, "slots none, move 0 -> 0") == 0);
    /* A buffer too small: cut, still NUL-terminated, nothing written beyond. */
    char small[8];
    memset(small, 'x', sizeof small);
    dfd_format(&c, small, 5u);
    DF_CHECK(t, strcmp(small, "slot") == 0 && small[5] == 'x');
    dfd_format(&c, small, 0u);
    DF_CHECK(t, small[5] == 'x');
}

/* One state's domain of one player: the set against itself, and every control. */
static void domain_of(df_test *t, const char *what, const duoforge_context *ctx, const duoforge_battle *b,
                      uint32_t player, uint32_t expected_kind, uint32_t expected_count)
{
    const uint32_t n = engine_choices(t, ctx, b, player);
    if (!DF_CHECK_EQ_U64(t, n, expected_count) || n < 7u) {
        fprintf(stderr, "  %s: %u candidates of player %u\n", what, (unsigned)n, (unsigned)player);
        return;
    }
    DF_CHECK_EQ_U64(t, engine[0].kind, expected_kind);
    reference_equal(n);
    dfd_diff d = compare(engine, n, reference, n);
    DF_CHECK(t, d.engine_only == 0u && d.reference_only == 0u);

    /* The engine's order does not matter: reversed it is the same set. */
    for (uint32_t i = 0u; i < n; ++i) {
        scratch[i] = engine[n - 1u - i];
    }
    dfd_compare(scratch, n, reference, n, &d);
    DF_CHECK(t, d.engine_only == 0u && d.reference_only == 0u);

    /* Control: a choice that the reference does not accept is engine-only, with the choice as the example. */
    const uint32_t k = n / 2u;
    const dfr_choice taken = reference[k];
    memmove(&reference[k], &reference[k + 1u], (n - k - 1u) * sizeof reference[0]);
    d = compare(engine, n, reference, n - 1u);
    DF_CHECK(t, d.engine_only == 1u && d.reference_only == 0u && memcmp(&d.engine_examples[0], &taken, sizeof taken) == 0);

    /* Control: a choice that the engine does not offer is reference-only (one above all, and one in the middle). */
    reference_equal(n);
    dfr_choice extra = reference[n - 1u];
    extra.kind = 3u; /* above every real choice, and in no domain */
    reference[n] = extra;
    d = compare(engine, n, reference, n + 1u);
    DF_CHECK(t, d.engine_only == 0u && d.reference_only == 1u && memcmp(&d.reference_examples[0], &extra, sizeof extra) == 0);
    reference_equal(n);
    dfr_choice other = reference[k];
    other.slots[1].reserve ^= 1u; /* a variant of a real choice: in no domain, or the control proves nothing */
    other.picks[5] ^= 1u;
    other.pick_count = other.kind == DUOFORGE_CHOICE_SLOTS ? 0u : other.pick_count;
    int in_domain = 0;
    for (uint32_t i = 0u; i < n; ++i) {
        in_domain |= memcmp(&engine[i], &other, sizeof other) == 0;
    }
    if (DF_CHECK(t, !in_domain)) {
        const dfr_choice replaced = reference[k];
        reference[k] = other;
        qsort(reference, n, sizeof reference[0], by_bytes);
        d = compare(engine, n, reference, n);
        DF_CHECK(t, d.engine_only == 1u && d.reference_only == 1u);
        DF_CHECK(t, memcmp(&d.engine_examples[0], &replaced, sizeof replaced) == 0 &&
                        memcmp(&d.reference_examples[0], &other, sizeof other) == 0);
    }

    /* Control: nothing accepted: everything is engine-only, the examples are the first three in order. */
    reference_equal(n);
    d = compare(engine, n, reference, 0u);
    DF_CHECK(t, d.engine_only == n && d.reference_only == 0u);
    DF_CHECK(t, memcmp(&d.engine_examples[0], &reference[0], sizeof reference[0]) == 0 &&
                    memcmp(&d.engine_examples[1], &reference[1], sizeof reference[0]) == 0 &&
                    memcmp(&d.engine_examples[2], &reference[2], sizeof reference[0]) == 0);
    /* Control: the engine offers nothing: everything the reference accepted is reference-only. */
    d = compare(engine, 0u, reference, n);
    DF_CHECK(t, d.engine_only == 0u && d.reference_only == n);
    DF_CHECK(t, memcmp(&d.reference_examples[2], &reference[2], sizeof reference[0]) == 0);

    /* Control: a candidate listed twice is engine-only the second time. */
    memcpy(scratch, engine, n * sizeof engine[0]);
    scratch[n] = engine[3];
    dfd_compare(scratch, n + 1u, reference, n, &d);
    DF_CHECK(t, d.engine_only == 1u && d.reference_only == 0u && memcmp(&d.engine_examples[0], &engine[3], sizeof engine[3]) == 0);
}

/* The examples are the first of each kind in the order of the sets, and no more than DFD_EXAMPLES. */
static void examples(df_test *t)
{
    dfr_choice eng[6];
    dfr_choice ref[6];
    for (uint32_t i = 0u; i < 6u; ++i) {
        eng[i] = bogus_team((uint8_t)i);
        eng[i].picks[4] = 1u; /* engine-only teams ...picks[4] = 1 */
        ref[i] = bogus_team((uint8_t)i);
        ref[i].picks[4] = 2u; /* ... reference-only picks[4] = 2: they interleave with none */
    }
    dfd_diff d;
    dfd_compare(eng, 6u, ref, 6u, &d);
    DF_CHECK(t, d.engine_only == 6u && d.reference_only == 6u);
    for (uint32_t i = 0u; i < DFD_EXAMPLES; ++i) {
        DF_CHECK(t, d.engine_examples[i].picks[3] == i && d.engine_examples[i].picks[4] == 1u);
        DF_CHECK(t, d.reference_examples[i].picks[3] == i && d.reference_examples[i].picks[4] == 2u);
    }
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.reference.runner_domain");
    mapping(&t);
    format(&t);
    examples(&t);
    duoforge_context *c1 = df_make_context(&df_config_c1);
    duoforge_battle *g1 = df_make_g1(c1);
    duoforge_battle *f1 = df_make_f1(c1);
    /* G1: team selection, side 0 six members (360 ordered picks of 4), side 1 four members (24). */
    domain_of(&t, "G1 side 0", c1, g1, 0u, DUOFORGE_CHOICE_TEAM_SELECTION, 360u);
    domain_of(&t, "G1 side 1", c1, g1, 1u, DUOFORGE_CHOICE_TEAM_SELECTION, 24u);
    /* F1: the first turn, joint slot choices (33 and 118). */
    domain_of(&t, "F1 side 0", c1, f1, 0u, DUOFORGE_CHOICE_SLOTS, 33u);
    domain_of(&t, "F1 side 1", c1, f1, 1u, DUOFORGE_CHOICE_SLOTS, 118u);
    duoforge_battle_destroy(g1);
    duoforge_battle_destroy(f1);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
