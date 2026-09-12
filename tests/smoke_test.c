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

    return 0;
}
