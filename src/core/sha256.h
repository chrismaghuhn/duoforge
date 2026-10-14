#ifndef DUOFORGE_CORE_SHA256_H
#define DUOFORGE_CORE_SHA256_H
/* FIPS 180-4; internal, canonical bytes only, never raw structure memory. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "core/private.h"
#define DFI_SHA256_SIZE 32u
#define DFI_SHA256_MAX_BYTES UINT64_C(0x1FFFFFFFFFFFFFFF)
typedef struct dfi_sha256_state {
    uint32_t h[8];
    uint64_t bytes;
    uint8_t block[64];
} dfi_sha256_state;
/* init requires a state. update permits NULL data only for size zero and
 * rejects an unrepresentable total length before touching the state.
 * final takes a snapshot: repeated finalization, then further updates, are
 * defined. Rejected finalization leaves out untouched. No allocation. */
DFI_PRIVATE void dfi_sha256_init(dfi_sha256_state *state);
DFI_PRIVATE bool dfi_sha256_update(dfi_sha256_state *state, const uint8_t *data, size_t size);
DFI_PRIVATE bool dfi_sha256_final(const dfi_sha256_state *state, uint8_t out[DFI_SHA256_SIZE]);
/* Existing one-shot contract: non-NULL data even for the empty message;
 * false, out untouched, if the length cannot fit the 64-bit bit count. */
bool dfi_sha256(const uint8_t *data, size_t size, uint8_t out[DFI_SHA256_SIZE]);
#endif
