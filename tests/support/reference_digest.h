#ifndef DUOFORGE_TEST_SUPPORT_REFERENCE_DIGEST_H
#define DUOFORGE_TEST_SUPPORT_REFERENCE_DIGEST_H
/* Optional observation for reference tests only. The byte stream is the
 * step-0 observer's explicit ASCII encoding, never raw struct bytes. */
#include <stdio.h>
#include <duoforge/duoforge.h>
#include "core/sha256.h"
#include "state/tiebreak.h"

typedef struct df_reference_digest {
    FILE *out;
    char *bytes;
    size_t length, capacity;
    const char *name;
    uint32_t steps, stops;
} df_reference_digest;

bool df_reference_digest_open(df_reference_digest *d, int argc, char **argv);
void df_reference_digest_begin(df_reference_digest *d, const char *name,
                               const duoforge_context *ctx, const duoforge_battle *b);
void df_reference_digest_step(df_reference_digest *d, const duoforge_context *ctx,
                              const duoforge_battle *b, uint32_t used, const duoforge_step_result *r);
void df_reference_digest_events(df_reference_digest *d, const duoforge_event_buffer *buffers);
void df_reference_digest_tiebreak(df_reference_digest *d, uint32_t prefix, bool ended,
                                  const dfi_tiebreak_report *r, duoforge_status rs,
                                  duoforge_status ps, uint32_t out);
void df_reference_digest_end(df_reference_digest *d);
bool df_reference_digest_close(df_reference_digest *d);
#endif
