#ifndef DUOFORGE_CODEC_ENVELOPE_H
#define DUOFORGE_CODEC_ENVELOPE_H
/*
 * Generic 20-byte artifact envelope (docs/decisions/0002). All integers are
 * little-endian and written byte-wise.
 *
 *   off  size  field
 *     0     8  magic 89 44 55 4F 0D 0A 1A 0A (PNG-style: detects 7-bit
 *              stripping, CRLF translation and ^Z truncation)
 *     8     2  artifact_kind (u16)
 *    10     2  schema_version (u16), per kind
 *    12     4  semantics_id (u32)
 *    16     4  total_length (u32), whole encoding including the envelope
 */
#include <stdint.h>

#include "core/bytes.h"

#define DFI_ENVELOPE_SIZE 20u
#define DFI_ENVELOPE_MAGIC_SIZE 8u
#define DFI_ENVELOPE_KIND_OFF 8u
#define DFI_ENVELOPE_SCHEMA_OFF 10u
#define DFI_ENVELOPE_SEMANTICS_OFF 12u
#define DFI_ENVELOPE_LENGTH_OFF 16u

/* Artifact kinds (registry: docs/decisions/0002). */
#define DFI_ARTIFACT_CONTEXT 1u      /* fingerprint preimage only; never decoded */
#define DFI_ARTIFACT_BATTLE_STATE 2u

static const uint8_t dfi_envelope_magic[DFI_ENVELOPE_MAGIC_SIZE] = {
    0x89u, 0x44u, 0x55u, 0x4Fu, 0x0Du, 0x0Au, 0x1Au, 0x0Au,
};

static inline void dfi_write_envelope(uint8_t *out, uint16_t kind, uint16_t schema, uint32_t semantics,
                                      uint32_t total_length)
{
    for (uint32_t i = 0u; i < DFI_ENVELOPE_MAGIC_SIZE; ++i) {
        out[i] = dfi_envelope_magic[i];
    }
    dfi_store_u16le(out + DFI_ENVELOPE_KIND_OFF, kind);
    dfi_store_u16le(out + DFI_ENVELOPE_SCHEMA_OFF, schema);
    dfi_store_u32le(out + DFI_ENVELOPE_SEMANTICS_OFF, semantics);
    dfi_store_u32le(out + DFI_ENVELOPE_LENGTH_OFF, total_length);
}

#endif
