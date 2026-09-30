#ifndef DUOFORGE_TESTS_SUPPORT_FIXTURES_H
#define DUOFORGE_TESTS_SUPPORT_FIXTURES_H
/*
 * SYNTHETIC test fixtures (docs/decisions/0002, appendix). No real Pokemon
 * data. Golden encodings and digests come from the independent structural
 * model tools/state_model/state_v1_model.py (written from the decision-note
 * tables), cross-checked against the M1 plan's independently derived values;
 * they are never copied from the C encoder.
 *
 *   C1 = {data_kind 1, max_roster 6, brought 4, species 16, moves 32}
 *   C2 = C1 with moves 33
 *   C3 = C1 with brought 1
 *   F1 (C1): RNG (42,54); side 0 six members, brought 0x0F, leads {2,0};
 *            side 1 four members, brought 0x0F, leads {1,3}.
 *   F2 (C1): F1, 16 raw draws, vacate s0a, place roster 3 at s0a, vacate
 *            s1b, then hp/pp pokes (fainted active and reserve, pp 0).
 *   F3 (C3): RNG (42,54); one lead per side, slot b empty.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

extern const duoforge_context_config df_config_c1;
extern const duoforge_context_config df_config_c2;
extern const duoforge_context_config df_config_c3;

#define DF_FP_C1_HEX "607c34de37e9fee5a0019c983e3cf49dac8fc41389ec116f09243fecc60f0cb1"
#define DF_FP_C2_HEX "53de00d6b5978adb2749ce1ecccc87997bb7a95d85a867efc96803a60bbb42ca"
#define DF_FP_C3_HEX "b5c723a61b71c0e3595651ea8b6091a876537a6ae9320ef8cb1a983cbf79834c"
#define DF_DIGEST_F1_HEX "40cfbb3f344bffc7a68dbd4a067245b1c316b952ceecddccba25224e416613be"
#define DF_DIGEST_F2_HEX "626f046b35c295daf135f872c1f44e43de94084cfaf6aa10a73ad8ee34a1512f"
#define DF_DIGEST_F3_HEX "99f1a5145e382ea60266806231eb783a83a6d755860279cfc3819124146a88d0"

/* The 31 canonical context bytes of C1 (fingerprint preimage). */
extern const uint8_t df_context_c1_bytes[31];

extern const uint8_t df_golden_f1[DUOFORGE_STATE_V1_ENCODED_SIZE];
extern const uint8_t df_golden_f2[DUOFORGE_STATE_V1_ENCODED_SIZE];
extern const uint8_t df_golden_f3[DUOFORGE_STATE_V1_ENCODED_SIZE];

void df_setup_f1(duoforge_battle_setup *out);
void df_setup_f3(duoforge_battle_setup *out);

/* Creates a context and aborts the test process on failure. */
duoforge_context *df_make_context(const duoforge_context_config *config);
/* Creates a battle from a setup and aborts the test process on failure. */
duoforge_battle *df_make_battle(const duoforge_context *ctx, const duoforge_battle_setup *setup);
/* White-box: builds F2 from F1 through the identity primitives (C1). */
duoforge_battle *df_make_f2(const duoforge_context *c1);
/* Encodes via the public API and aborts on failure. */
void df_encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V1_ENCODED_SIZE]);

#endif
