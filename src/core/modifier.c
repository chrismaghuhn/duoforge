#include "core/modifier.h"

/* Integers below 2^53 are exact in the reference's doubles. */
#define DFI_EXACT_LIMIT (UINT64_C(1) << 53)
#define DFI_LOW32(x) ((x) & UINT64_C(0xFFFFFFFF))

bool dfi_mod_fraction(uint32_t numerator, uint32_t denominator, uint32_t *out)
{
    if (denominator == 0u) {
        return false;
    }
    const uint64_t q = ((uint64_t)numerator * 4096u) / denominator;
    *out = (uint32_t)DFI_LOW32(q); /* wide-operands-reviewed: the reference's >>> 0 */
    return true;
}

uint32_t dfi_modify(uint32_t value, uint32_t modifier)
{
    /* value * modifier < 2^64, but the reference is exact only below 2^53;
     * the closure's values (damage and stats below 2^16, modifiers below
     * 2^16) stay far below. The product is truncated like `>>> 0`. */
    const uint64_t product = DFI_LOW32((uint64_t)value * modifier);
    const uint64_t q = (product + 2047u) / 4096u;
    return (uint32_t)q; /* < 2^21 */
}

bool dfi_chain_modify(uint32_t previous, uint32_t next, uint32_t *out)
{
    const uint64_t sum = (uint64_t)previous * next + 2048u;
    if (sum >= (UINT64_C(1) << 31)) {
        return false; /* the reference shifts a 32-bit value with a sign bit */
    }
    *out = (uint32_t)(sum >> 12); /* wide-operands-reviewed: < 2^19 */
    return true;
}

bool dfi_base_damage(uint32_t level, uint32_t base_power, uint32_t attack, uint32_t defense, uint32_t *out)
{
    if (defense == 0u) {
        return false;
    }
    const uint64_t factor = ((uint64_t)level * 2u) / 5u + 2u;
    const uint64_t product = factor * base_power * attack;
    if (product >= DFI_EXACT_LIMIT) {
        return false;
    }
    const uint64_t scaled = DFI_LOW32(product) / defense;
    *out = (uint32_t)(scaled / 50u); /* wide-operands-reviewed: < 2^32 / 50 */
    return true;
}

bool dfi_randomize(uint32_t damage, uint32_t roll, uint32_t *out)
{
    if (roll > 15u) {
        return false;
    }
    const uint64_t product = DFI_LOW32((uint64_t)damage * (100u - roll));
    *out = (uint32_t)(product / 100u); /* wide-operands-reviewed: < 2^32 */
    return true;
}

uint32_t dfi_crit_damage(uint32_t damage)
{
    const uint64_t product = ((uint64_t)damage * 3u) / 2u;
    return (uint32_t)DFI_LOW32(product); /* wide-operands-reviewed: the reference's >>> 0 */
}

bool dfi_type_damage(uint32_t damage, uint32_t type_mod_biased, uint32_t *out)
{
    if (type_mod_biased > DFI_BIAS6_MAX) {
        return false;
    }
    uint64_t value = damage;
    for (uint32_t i = DFI_BIAS6; i < type_mod_biased; ++i) {
        value *= 2u; /* not truncated in the reference */
    }
    for (uint32_t i = type_mod_biased; i < DFI_BIAS6; ++i) {
        value /= 2u;
    }
    if (value > UINT32_MAX) {
        return false; /* the reference keeps a floating value; never for the closure */
    }
    *out = (uint32_t)value;
    return true;
}

uint32_t dfi_final_damage(uint32_t damage)
{
    if (damage == 0u) {
        return 1u;
    }
    return damage & 0xFFFFu;
}

bool dfi_stage_stat(uint32_t stat, uint32_t stage_biased, uint32_t *out)
{
    if (stage_biased > DFI_BIAS6_MAX) {
        return false;
    }
    uint64_t value = 0u;
    if (stage_biased >= DFI_BIAS6) {
        value = ((uint64_t)stat * (2u + (stage_biased - DFI_BIAS6))) / 2u;
    } else {
        value = ((uint64_t)stat * 2u) / (2u + (DFI_BIAS6 - stage_biased));
    }
    if (value > UINT32_MAX) {
        return false;
    }
    *out = (uint32_t)value;
    return true;
}

bool dfi_stage_accuracy(uint32_t accuracy, uint32_t stage_biased, uint32_t *out)
{
    if (stage_biased > DFI_BIAS6_MAX) {
        return false;
    }
    uint64_t value = 0u;
    if (stage_biased >= DFI_BIAS6) {
        value = ((uint64_t)accuracy * (3u + (stage_biased - DFI_BIAS6))) / 3u;
    } else {
        value = ((uint64_t)accuracy * 3u) / (3u + (DFI_BIAS6 - stage_biased));
    }
    *out = (uint32_t)DFI_LOW32(value); /* wide-operands-reviewed: the reference's >>> 0 */
    return true;
}
