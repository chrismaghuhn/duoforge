#ifndef DUOFORGE_CORE_FORCE_INLINE_H
#define DUOFORGE_CORE_FORCE_INLINE_H
/* A phase function of a large engine function (restructure step 4): always inlined into its one caller, so that cutting
 * the function into named phases changes no generated code. */
#if defined(_MSC_VER)
#define DFI_FORCE_INLINE __forceinline
#elif defined(__GNUC__) || defined(__clang__)
#define DFI_FORCE_INLINE inline __attribute__((always_inline))
#else
#define DFI_FORCE_INLINE inline
#endif
#endif
