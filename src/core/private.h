#ifndef DUOFORGE_CORE_PRIVATE_H
#define DUOFORGE_CORE_PRIVATE_H
/* New internal entry points are hidden on ELF. On Windows their source
 * objects live in the private archive outside the automatic export scan. */
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
#define DFI_PRIVATE __attribute__((visibility("hidden")))
#else
#define DFI_PRIVATE
#endif
#endif
