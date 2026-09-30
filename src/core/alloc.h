#ifndef DUOFORGE_CORE_ALLOC_H
#define DUOFORGE_CORE_ALLOC_H
/*
 * The only allocation site of the library (lint-enforced). Allocation
 * happens only in create/clone entry points, never on a hot path.
 */
#include <stddef.h>

/* Returns zero-filled storage of size bytes, or NULL. size must be nonzero. */
void *dfi_alloc_zeroed(size_t size);
/* NULL is a no-op. */
void dfi_free(void *p);

#endif
