#ifndef DFI_COMBAT_DAMAGE_CHAIN_H
#define DFI_COMBAT_DAMAGE_CHAIN_H

/*
 * The ModifyDamage chain (step G34): the handlers of the event that the engine knows have no order and priority 0, so
 * runEvent's speedSort (comparePriority, sim/battle.ts:403-410) puts them in the order of their holders' speed (the
 * attacker's item against the defender's Glaive Rush, ability and berry; a side condition has no speed, so a screen is
 * last), then of their subOrder (a condition 2, an ability 7, an item 8), and shuffles only a complete tie. That order is
 * computable from the state (a follow-up of step G34), but this build does not compute it: it needs no order while every
 * order of the modifiers that one hit has chains to one value (chainModify, sim/battle.ts:2321-2330: previous * next +
 * 2048, shifted right by 12, from 4096), and refuses the combinations for which they do not. `dfi_mods_commute` is that
 * test, over the modifiers that one hit has; the combinations for which it fails are E_UNSUPPORTED (turn.c), and
 * tools/reference/trace_to_c.py (modifiers_commute) holds the same values for the converter's drop rule.
 *
 * The modifiers (out of 4096): Life Orb 5324, Expert Belt 4915, a resist berry 2048, a screen or Aurora Veil 2732, Glaive
 * Rush's volatile 8192, Solid Rock 3072, Multiscale 2048, and (step G35) Friend Guard 3072, the ability of the target's partner.
 * One hit has at most one of Life Orb and Expert Belt (the attacker's item), one of Solid Rock and Multiscale (the target's
 * ability), one screen, one berry, Glaive Rush's volatile and Friend Guard, so six modifiers at most.
 */
#include <stdbool.h>
#include <stdint.h>

#define DFI_MODIFY_DAMAGE_MAX 6u

/* one chainModify step on the accumulated modifier */
#define DFI_MD_CHAIN(a, b) ((((a) * (b)) + 2048u) >> 12)

/* True when every order of `mods` (n <= DFI_MODIFY_DAMAGE_MAX values) chains, from 4096, to the value of the first order:
 * Heap's algorithm over a copy, no allocation. */
static inline bool dfi_mods_commute(const uint32_t *mods, uint32_t n)
{
    uint32_t a[DFI_MODIFY_DAMAGE_MAX] = {0u};
    uint32_t c[DFI_MODIFY_DAMAGE_MAX] = {0u};
    if (n > DFI_MODIFY_DAMAGE_MAX) {
        return false;
    }
    for (uint32_t i = 0u; i < n; ++i) {
        a[i] = mods[i];
    }
    uint32_t first = 4096u;
    for (uint32_t i = 0u; i < n; ++i) {
        first = DFI_MD_CHAIN(first, a[i]);
    }
    uint32_t i = 0u;
    while (i < n) {
        if (c[i] < i) {
            const uint32_t j = (i % 2u == 0u) ? 0u : c[i];
            const uint32_t t = a[j];
            a[j] = a[i];
            a[i] = t;
            uint32_t v = 4096u;
            for (uint32_t k = 0u; k < n; ++k) {
                v = DFI_MD_CHAIN(v, a[k]);
            }
            if (v != first) {
                return false;
            }
            c[i] += 1u;
            i = 0u;
        } else {
            c[i] = 0u;
            i += 1u;
        }
    }
    return true;
}

#endif
