#include "core/alloc.h"

#include <stdlib.h>

void *dfi_alloc_zeroed(size_t size)
{
    if (size == 0u) {
        return NULL;
    }
    return calloc(1u, size);
}

void dfi_free(void *p)
{
    free(p);
}
