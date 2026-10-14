#ifndef DUOFORGE_STATE_OBSERVATION_KEY_H
#define DUOFORGE_STATE_OBSERVATION_KEY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* HS's 0082 contract reserves all-zero bytes for a refused key. Status is
 * still checked independently; a nonzero byte alone does not imply success. */
static inline bool dfi_observation_key_nonzero(const uint8_t *key)
{
    if (key == NULL) { return false; }
    uint32_t present = 0u;
    for (uint32_t i = 0u; i < 32u; ++i) { present |= key[i]; }
    return present != 0u;
}
#endif
