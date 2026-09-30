#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "duoforge/duoforge.h"

int main(void)
{
    const char *version = duoforge_version_string();

    if (version == NULL || strcmp(version, DUOFORGE_VERSION_STRING) != 0) {
        fprintf(stderr, "unexpected DuoForge version: %s\n",
                version == NULL ? "(null)" : version);
        return 1;
    }

    /* Recorded so CI can assert the tested bitness (e.g. the Win32 row). */
    printf("duoforge smoke: version=%s pointer_bits=%u size_t_bits=%u\n", version,
           (unsigned)(sizeof(void *) * CHAR_BIT), (unsigned)(sizeof(size_t) * CHAR_BIT));
    return 0;
}
