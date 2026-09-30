/* ASan liveness canary (sanitizer builds only): an 8-byte heap over-read. */
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    volatile size_t i = 8;
    unsigned char *p = malloc(8);
    if (p == NULL) {
        return 2;
    }
    p[0] = 1;
    printf("CANARY_SURVIVED %u\n", (unsigned)p[i]);
    free(p);
    return 0;
}
