#ifndef DUOFORGE_CORE_MODIFIER_H
#define DUOFORGE_CORE_MODIFIER_H
/*
 * Damage and stat arithmetic of the pinned reference (docs/decisions/0002
 * section 8, 0006 section 4), in integers. The reference computes in
 * doubles and truncates with `x >>> 0` (sim/dex.ts:365-368): for the
 * non-negative values here that is floor(x) modulo 2^32. Every helper
 * below reproduces that, including the wrap-around, by computing in 64 bits
 * and keeping the low 32 bits where the reference truncates.
 *
 * Modifiers are 4096-based integers: the reference's `tr(numerator * 4096 /
 * denominator)` (sim/battle.ts:2327-2343). Common values: 0.25 -> 1024,
 * 0.5 -> 2048, 0.75 -> 3072, 1 -> 4096, 1.2 -> 4915, 1.3 -> 5324, 1.5 -> 6144,
 * 2 -> 8192.
 *
 * All functions are pure; fallible ones return false and leave *out
 * untouched.
 */
#include <stdbool.h>
#include <stdint.h>

#define DFI_MOD_ONE 4096u

/* tr(numerator * 4096 / denominator); denominator > 0. */
bool dfi_mod_fraction(uint32_t numerator, uint32_t denominator, uint32_t *out);

/* modify(value, modifier): tr((tr(value * modifier) + 2047) / 4096)
 * (sim/battle.ts:2331-2343). */
uint32_t dfi_modify(uint32_t value, uint32_t modifier);

/* The chained modifier ((previous * next + 2048) >> 12) of chainModify
 * (sim/battle.ts:2318-2329). The reference shifts a 32-bit value with a sign bit;
 * false when the sum leaves that range (never for the closure's modifiers). */
bool dfi_chain_modify(uint32_t previous, uint32_t next, uint32_t *out);

/* The base damage tr(tr(tr(tr(2 * L / 5 + 2) * P * A) / D) / 50)
 * (sim/battle-actions.ts:1718); defense > 0. */
bool dfi_base_damage(uint32_t level, uint32_t base_power, uint32_t attack, uint32_t defense, uint32_t *out);

/* randomizer: tr(tr(damage * (100 - roll)) / 100), roll 0..15
 * (sim/battle.ts:2391-2394). */
bool dfi_randomize(uint32_t damage, uint32_t roll, uint32_t *out);

/* The critical hit factor tr(damage * 1.5) (modifyDamage, not a modifier). */
uint32_t dfi_crit_damage(uint32_t damage);

/* Stages and type effectiveness have a sign in the reference; here they are
 * biased by DFI_BIAS6: a value v means v - 6, so 0..12 covers -6..+6. */
#define DFI_BIAS6 6u
#define DFI_BIAS6_MAX 12u

/* Type effectiveness steps (biased typeMod): above 6 doubles per step,
 * below 6 halves with truncation per step (modifyDamage). */
bool dfi_type_damage(uint32_t damage, uint32_t type_mod_biased, uint32_t *out);

/* The last steps of modifyDamage: 0 becomes 1, then tr(damage, 16). */
uint32_t dfi_final_damage(uint32_t damage);

/* A stat after a (biased) stage: floor(stat * [1, 1.5, 2, ... 4][b]) for
 * b >= 0, floor(stat / table[-b]) below (sim/pokemon.ts:583-590). With the
 * table entry (2 + |b|) / 2 both are exact integer divisions. */
bool dfi_stage_stat(uint32_t stat, uint32_t stage_biased, uint32_t *out);

/* Accuracy after the combined accuracy/evasion (biased) stage:
 * tr(acc * (3 + b) / 3) or tr(acc * 3 / (3 - b)) (sim/battle-actions.ts:722-727). */
bool dfi_stage_accuracy(uint32_t accuracy, uint32_t stage_biased, uint32_t *out);

#endif
