#include "support/factored.h"

#include <string.h>

/* n * (n - 1) * ... * (n - m + 1): the ordered tuples of m distinct indices
   below n. */
static uint32_t df_falling(uint32_t n, uint32_t m)
{
    uint32_t p = 1u;
    for (uint32_t i = 0u; i < m; ++i) {
        p *= n - i;
    }
    return p;
}

/* The tuple of lexicographic rank k: position i selects among the unused
   indices in ascending order, each worth the tuples that complete it. */
static void df_unrank_team(uint32_t n, uint32_t m, uint32_t k, uint8_t picks[DUOFORGE_MAX_ROSTER])
{
    uint32_t used = 0u;
    for (uint32_t i = 0u; i < m; ++i) {
        const uint32_t block = df_falling(n - 1u - i, m - 1u - i);
        uint32_t digit = k / block;
        k %= block;
        for (uint32_t c = 0u; c < n; ++c) {
            if (((used >> c) & 1u) != 0u) {
                continue;
            }
            if (digit == 0u) {
                picks[i] = (uint8_t)c;
                used |= 1u << c;
                break;
            }
            digit -= 1u;
        }
    }
}

static bool df_allowed(const duoforge_factored_domain *d, uint32_t i, uint32_t j)
{
    return ((d->allowed[i] >> j) & 1u) != 0u;
}

uint32_t df_factored_expand(const duoforge_factored_domain *d, uint32_t side, duoforge_side_choice *out)
{
    duoforge_side_choice head;
    memset(&head, 0, sizeof head);
    head.epoch = d->epoch;
    head.side = (uint8_t)side;
    head.kind = d->kind;
    uint32_t n = 0u;
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        head.pick_count = d->pick_count;
        const uint32_t total = df_falling(d->member_count, d->pick_count);
        for (uint32_t k = 0u; k < total && n < DUOFORGE_MAX_CANDIDATES; ++k) {
            out[n] = head;
            df_unrank_team(d->member_count, d->pick_count, k, out[n].picks);
            n += 1u;
        }
        return n;
    }
    for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
        for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
            if (df_allowed(d, i, j) && n < DUOFORGE_MAX_CANDIDATES) {
                out[n] = head;
                out[n].slots[0] = d->slots[0][i];
                out[n].slots[1] = d->slots[1][j];
                n += 1u;
            }
        }
    }
    return n;
}

duoforge_factored_choice df_factored_choice(const duoforge_factored_domain *d, uint32_t k)
{
    duoforge_factored_choice c;
    memset(&c, 0, sizeof c);
    if (d->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        df_unrank_team(d->member_count, d->pick_count, k, c.picks);
        return c;
    }
    for (uint32_t i = 0u; i < d->slot_count[0]; ++i) {
        for (uint32_t j = 0u; j < d->slot_count[1]; ++j) {
            if (!df_allowed(d, i, j)) {
                continue;
            }
            if (k == 0u) {
                c.slot[0] = (uint8_t)i;
                c.slot[1] = (uint8_t)j;
                return c;
            }
            k -= 1u;
        }
    }
    return c;
}
