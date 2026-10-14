#include "core/sha256.h"
bool dfi_sha256(const uint8_t *data, size_t size, uint8_t out[DFI_SHA256_SIZE])
{
    dfi_sha256_state state;
    dfi_sha256_init(&state);
    return dfi_sha256_update(&state, data, size) && dfi_sha256_final(&state, out);
}
