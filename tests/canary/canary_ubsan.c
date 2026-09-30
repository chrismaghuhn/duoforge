/*
 * UBSan liveness canary (sanitizer builds only). Must be stopped by the
 * compile flag -fno-sanitize-recover=all; the test runs with halt_on_error=0
 * so the runtime option cannot mask a missing compile flag.
 */
#include <limits.h>
#include <stdio.h>

int main(void)
{
    volatile int x = INT_MAX;
    int y = x + 1;
    printf("CANARY_SURVIVED %d\n", y);
    return 0;
}
