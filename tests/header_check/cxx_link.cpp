// Proves the extern "C" guard: a C++ translation unit calls the C API and links.
#include <cstdio>
#include <cstring>

#include "duoforge/duoforge.h"
#include "duoforge/duoforge_batch.h"
#include "duoforge/duoforge_encode.h"

int main()
{
    const char *v = duoforge_version_string();
    if (v == nullptr || std::strcmp(v, DUOFORGE_VERSION_STRING) != 0) {
        std::fprintf(stderr, "cxx link: unexpected version\n");
        return 1;
    }
    std::printf("cxx link: OK %s\n", v);
    return 0;
}
