#include "rng/draw.h"

dfi_draws dfi_draws_from_rng(dfi_rng *rng)
{
    dfi_draws d = {rng, NULL, 0u, 0u, false, NULL, 0u, 0u};
    return d;
}

static duoforge_status dfi_draw_from_tape(dfi_draws *d, uint32_t site, uint32_t lo, uint32_t hi, uint32_t *out)
{
    if (d->tape_pos >= d->tape_len) {
        d->failed = true; /* exhausted: the engine drew more than the reference */
        return DUOFORGE_E_INVARIANT;
    }
    const dfi_tape_entry *e = &d->tape[d->tape_pos];
    if (e->site != site || e->lo != lo || e->hi != hi || e->value < lo || e->value >= hi) {
        d->failed = true; /* a different site or bound than the reference */
        return DUOFORGE_E_INVARIANT;
    }
    d->tape_pos += 1u;
    *out = e->value;
    return DUOFORGE_OK;
}

duoforge_status dfi_draw(dfi_draws *d, uint32_t site, uint32_t lo, uint32_t hi, uint32_t *out)
{
    if (site == 0u || site >= DFI_SITE_COUNT || hi <= lo) {
        return DUOFORGE_E_INVARIANT;
    }
    uint32_t value = 0u;
    if (d->tape != NULL) {
        const duoforge_status ts = dfi_draw_from_tape(d, site, lo, hi, &value);
        if (ts != DUOFORGE_OK) {
            return ts;
        }
    } else {
        uint32_t r = 0u;
        const duoforge_status rs = dfi_rng_bounded_u32(d->rng, hi - lo, &r);
        if (rs != DUOFORGE_OK) {
            return rs;
        }
        value = lo + r; /* < hi */
    }
    if (d->log != NULL && d->log_len < d->log_cap) {
        d->log[d->log_len] = (uint8_t)site; /* site < DFI_SITE_COUNT */
    }
    if (d->log_len < UINT32_MAX) {
        d->log_len += 1u;
    }
    *out = value;
    return DUOFORGE_OK;
}

duoforge_status dfi_draw_chance(dfi_draws *d, uint32_t site, uint32_t numerator, uint32_t denominator, bool *out)
{
    uint32_t r = 0u;
    const duoforge_status st = dfi_draw(d, site, 0u, denominator, &r);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *out = r < numerator;
    return DUOFORGE_OK;
}
