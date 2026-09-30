#ifndef DUOFORGE_CORE_PLATFORM_H
#define DUOFORGE_CORE_PLATFORM_H
/*
 * Portability assertions and coding rules for DuoForge sources
 * (docs/decisions/0002 and 0003).
 *
 * Coding rules:
 *  1. Cast operands, never results. Arithmetic and shifts only run on
 *     operands already of type uint32_t or uint64_t, e.g. (uint32_t)p[3] << 24
 *     and (uint64_t)a * b. A cast applied to the result of an expression never
 *     fixes an integer promotion; it only hides it. No arithmetic or shifts
 *     directly on uint8_t or uint16_t values.
 *  2. Narrow only after a range check: dfi_u32_to_u16 / dfi_u32_to_u8, or a
 *     plain cast of a variable right after the check.
 *  3. Enforcement is review, the source lint and extreme-value tests under
 *     GCC UBSan. The compiler warning set is not a proof of promotion safety.
 *     A cast of a parenthesized expression needs the marker comment
 *     wide-operands-reviewed on the same line.
 *  4. Intentional mod 2^n wrap is allowed only in the PCG step and in
 *     SHA-256 word arithmetic, and each site is commented.
 *  5. Integer data and arithmetic use only fixed-width types without a sign
 *     bit, size_t and bool. The lint rejects the keyword-based integer types
 *     and L-suffixed literals; enums (internal identifiers only, never
 *     encoded) and char (string literals only) are allowed. Literals should
 *     use UINT32_C / UINT64_C or a u suffix. Loop counters are uint32_t or
 *     size_t.
 *  6. A shift count must be proven below the operand width; shifts by a
 *     stored value happen only after a range check.
 *  7. No floating point. No unary minus on values without a sign bit. Use
 *     for (;;) for endless loops. No constant if conditions.
 *  8. Every local and output is initialized.
 *  9. ASCII-only sources.
 * 10. Internal symbols with external linkage use the prefix dfi_.
 */
#include <limits.h>
#include <stdint.h>

_Static_assert(CHAR_BIT == 8, "DuoForge requires 8-bit bytes");
_Static_assert(UINT_MAX == UINT32_MAX, "uint32_t arithmetic must not promote");
_Static_assert(INT_MAX == INT32_MAX, "uint8_t and uint16_t must promote to a 32-bit type");
_Static_assert(SIZE_MAX >= UINT32_MAX, "size_t must hold at least 32 bits");

#endif
