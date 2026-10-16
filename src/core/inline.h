#ifndef DUOFORGE_CORE_INLINE_H
#define DUOFORGE_CORE_INLINE_H
/* A private function that the compiler must inline into its one caller (restructure step 4, damage): a phase of a large
 * function stays its caller's code, so the cut does not change the generated code. GCC and Clang take the attribute,
 * MSVC and clang-cl __forceinline; any other compiler gets a plain inline hint. Not part of the public headers. */
#if defined(_MSC_VER)
#define DFI_ALWAYS_INLINE __forceinline
#elif defined(__GNUC__) || defined(__clang__)
#define DFI_ALWAYS_INLINE inline __attribute__((always_inline))
#else
#define DFI_ALWAYS_INLINE inline
#endif
#endif
