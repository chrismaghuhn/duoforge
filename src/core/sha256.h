#ifndef DUOFORGE_CORE_SHA256_H
#define DUOFORGE_CORE_SHA256_H
/*
 * One-shot SHA-256 (FIPS 180-4), written from the specification; no code is
 * imported. Internal. Used only on canonical encodings, never on raw struct
 * bytes.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DFI_SHA256_SIZE 32u

/*
 * data must be non-NULL (for the empty message pass a pointer to any valid
 * object with size 0). Returns false, leaving out untouched, only when the
 * message length is not representable (size >= 2^61 bytes; compiled out
 * where size_t cannot reach it).
 */
bool dfi_sha256(const uint8_t *data, size_t size, uint8_t out[DFI_SHA256_SIZE]);

#endif
