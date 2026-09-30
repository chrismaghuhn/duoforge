/*
 * duoforge.state.knowledge (white-box): the Champions HP display and the
 * per-player knowledge record (docs/decisions/0006 section 6).
 *
 * Expectations come from the pinned rule (sim/pokemon.ts:2060-2073): floor
 * percent, at least 1 while alive, a colour flag only at exactly 20 and 50
 * percent. The sweep proves that the validity predicate of the invariant
 * checker accepts exactly the pairs the display can produce.
 */
#include <stdio.h>
#include <string.h>

#include "state/identity.h"
#include "state/knowledge.h"
#include "support/check.h"
#include "support/fixtures.h"

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.knowledge");

    /* Hand-derived values. */
    {
        static const struct {
            uint32_t hp;
            uint32_t hp_max;
            uint32_t percent;
            uint32_t flag;
        } cases[] = {
            {0, 120, 0, DUOFORGE_HP_FLAG_NONE},     {1, 201, 1, DUOFORGE_HP_FLAG_NONE},
            {1, 65535, 1, DUOFORGE_HP_FLAG_NONE},   {2, 201, 1, DUOFORGE_HP_FLAG_NONE},
            {24, 120, 20, DUOFORGE_HP_FLAG_RED},    {25, 120, 20, DUOFORGE_HP_FLAG_YELLOW},
            {41, 201, 20, DUOFORGE_HP_FLAG_YELLOW}, {40, 201, 19, DUOFORGE_HP_FLAG_NONE},
            {65, 130, 50, DUOFORGE_HP_FLAG_YELLOW}, {66, 130, 50, DUOFORGE_HP_FLAG_GREEN},
            {101, 201, 50, DUOFORGE_HP_FLAG_GREEN}, {100, 201, 49, DUOFORGE_HP_FLAG_NONE},
            {200, 201, 99, DUOFORGE_HP_FLAG_NONE},  {201, 201, 100, DUOFORGE_HP_FLAG_NONE},
            {65535, 65535, 100, DUOFORGE_HP_FLAG_NONE},
        };
        for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
            uint8_t percent = 0xEEu;
            uint8_t flag = 0xEEu;
            dfi_hp_display(cases[i].hp, cases[i].hp_max, &percent, &flag);
            if (!DF_CHECK(&t, percent == cases[i].percent && flag == cases[i].flag)) {
                fprintf(stderr, "  %u/%u -> %u flag %u\n", (unsigned)cases[i].hp, (unsigned)cases[i].hp_max,
                        (unsigned)percent, (unsigned)flag);
            }
        }
        /* Corrupt input stays defined: no division by zero, never above 100. */
        uint8_t percent = 0xEEu;
        uint8_t flag = 0xEEu;
        dfi_hp_display(5u, 0u, &percent, &flag);
        DF_CHECK(&t, percent == 0u && flag == DUOFORGE_HP_FLAG_NONE);
        dfi_hp_display(65535u, 1u, &percent, &flag);
        DF_CHECK(&t, percent == 100u && flag == DUOFORGE_HP_FLAG_NONE);
    }

    /* Sweep: every (hp, hp_max) with hp_max <= 1200 and a few large maxima.
     * The display is monotone in hp, 0 exactly for hp 0, and the set of
     * produced pairs equals the set the validity predicate accepts. */
    {
        uint8_t produced[256][4];
        memset(produced, 0, sizeof produced);
        unsigned violations = 0;
        static const uint32_t maxima[] = {4999u, 10000u, 32767u, 65535u};
        for (uint32_t pass = 1u; pass <= 1200u + sizeof maxima / sizeof maxima[0]; ++pass) {
            const uint32_t hp_max = pass <= 1200u ? pass : maxima[pass - 1201u];
            uint32_t previous = 0u;
            for (uint32_t hp = 0u; hp <= hp_max; ++hp) {
                uint8_t percent = 0xEEu;
                uint8_t flag = 0xEEu;
                dfi_hp_display(hp, hp_max, &percent, &flag);
                violations += (percent == 0u) != (hp == 0u) ? 1u : 0u;
                violations += percent < previous || percent > 100u || flag > 3u ? 1u : 0u;
                violations += !dfi_hp_display_valid(percent, flag) ? 1u : 0u;
                violations += (hp == hp_max) != (percent == 100u) ? 1u : 0u;
                previous = percent;
                if (percent <= 100u && flag <= 3u) {
                    produced[percent][flag] = 1u;
                }
            }
        }
        DF_CHECK_EQ_U64(&t, violations, 0u);
        unsigned accepted = 0;
        unsigned mismatches = 0;
        for (uint32_t percent = 0u; percent < 256u; ++percent) {
            for (uint32_t flag = 0u; flag < 256u; ++flag) {
                const bool valid = dfi_hp_display_valid(percent, flag);
                const bool made = flag < 4u && produced[percent][flag] != 0u;
                accepted += valid ? 1u : 0u;
                mismatches += valid != made ? 1u : 0u;
            }
        }
        DF_CHECK_EQ_U64(&t, mismatches, 0u);
        DF_CHECK_EQ_U64(&t, accepted, 103u); /* 99 plain percentages and two flags each at 20 and 50 */
    }

    /* The record: written on entry and on refresh, kept on leaving, only for
     * active members, only in the opponent's knowledge. */
    {
        duoforge_context *c1 = df_make_context(&df_config_c1);
        duoforge_battle *b = df_make_f1(c1); /* s0 leads 2 and 0, s1 leads 1 and 3 */
        b->sides[0].members[2].hp = 60u;  /* active: 50 percent of 120, yellow */
        b->sides[0].members[1].hp = 11u;  /* bench */
        b->sides[1].members[3].hp = 0u;   /* active, fainted */
        dfi_knowledge_refresh_active(b);
        DF_CHECK(&t, b->sides[1].knowledge[2].hp_percent == 50u &&
                         b->sides[1].knowledge[2].hp_flag == DUOFORGE_HP_FLAG_YELLOW);
        DF_CHECK(&t, b->sides[1].knowledge[1].hp_percent == 0u && b->sides[1].knowledge[1].hp_flag == 0u);
        DF_CHECK(&t, b->sides[0].knowledge[3].hp_percent == 0u && b->sides[0].knowledge[1].hp_percent == 100u);
        DF_CHECK(&t, b->sides[0].knowledge[2].hp_percent == 0u); /* s1 member 2 was never seen */
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_OK);
        /* A corrupt occupant is skipped, not used as an index. */
        b->sides[0].positions[1].occupant = 0xFEu;
        dfi_knowledge_refresh_active(b);
        DF_CHECK(&t, duoforge_battle_check(c1, b) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(b);
        duoforge_context_destroy(c1);
    }

    return df_test_end(&t);
}
