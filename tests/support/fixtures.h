#ifndef DUOFORGE_TESTS_SUPPORT_FIXTURES_H
#define DUOFORGE_TESTS_SUPPORT_FIXTURES_H
/*
 * SYNTHETIC test fixtures (docs/decisions/0005). No real Pokemon data. Golden
 * encodings, digests and domain digests come from the independent structural
 * model tools/state_model/state_v2_model.py (written from the decision
 * notes); they are never copied from the C encoder.
 *
 * Contexts (data_kind 1):
 *   C1 = {max_roster 6, brought 4, species 16, moves 36, table T1}
 *        T1 mirrors the 36 distinct team moves of decision 0004.
 *   C2 = C1 with T1[35] changed to SELF (fingerprint differs by the table)
 *   C3 = C1 with brought 1
 *   C4 = {max_roster 4, brought 2, species 8, moves 9, table 1..9}
 * Battles:
 *   G1 (C1): TEAM_SELECTION; side 0 six members (M1's F1 rosters), side 1
 *            four; Mega stones on s0 members 1 and 3 and s1 member 0.
 *   F1 (C1): G1 after picks s0 [2,0,1,3], s1 [1,3,0,2] (TURN, epoch 2).
 *   F2 (C1): F1, 16 raw draws, vacate s0a, place roster 3 at s0a, vacate
 *            s1b, hp/pp pokes, s0 Mega used.
 *   G3 (C3): TEAM_SELECTION with M1's F3 rosters.   F3: G3 after [2] / [0].
 *   F4 (C1): two-side REPLACEMENT (s0a and s1b fainted).
 *   F5 (C1): one-side PIVOT (s0a), both turn choices sealed.
 *   F6 (C1): two-side PIVOT (s0a and s1b), both sealed.
 *   G7 (C4): small exhaustive TEAM_SELECTION fixture (4 and 3 members).
 *   F8 (C4): G7 after [1,3] / [2,0].   F9: G7 after [0,2] / [1,2].
 *   F10 (C4): F9, s1b fainted, s0 Mega used.
 *   F11 (C4): F9 at REPLACEMENT, s0 both slots requested, one reserve.
 *   F12 (C4): F9 with s0a alive at pp 0 everywhere (Struggle: UNSUPPORTED).
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

extern const duoforge_context_config df_config_c1;
extern const duoforge_context_config df_config_c2;
extern const duoforge_context_config df_config_c3;
extern const duoforge_context_config df_config_c4;
extern const uint8_t df_table_t1[36];

#define DF_FP_C1_HEX "30e232e0980c9c2acba4641ef5b1ab48e8b904cfa73a395c59d917ffa2240b1b"
#define DF_FP_C2_HEX "75ebdbe313f2e41007b4c4a6fadba9e2659ca1d273dc2c0c14bf965148689ebb"
#define DF_FP_C3_HEX "ddadd54aae003b1de14bdae3f2743f95b6d07846019142436073c657f9d216ab"
#define DF_FP_C4_HEX "6c215f2674c444d63d56e19bb1d8e201895e0dfebd015c6fbe8c07834a9b5494"
#define DF_DIGEST_G1_HEX "9456bc61928daee34cf2d2462c9251a813d542f79656fc867a1c1589c4a8bbea"
#define DF_DIGEST_F1_HEX "85b831a4b3cccdf5b298aabe4d991bdb11c71497c01f01fa61dc9d585627caa7"
#define DF_DIGEST_F2_HEX "985ad44b5a343b8b22170c4543c7edb17fb64330faa3b11a97f8411e39bc6bf9"
#define DF_DIGEST_G3_HEX "126757b70e9b43579ddfc04db33c7853be90e74b0b923d956a91ce177765082e"
#define DF_DIGEST_F3_HEX "d677d61942ae5d381cbdf70899719a169e2b1a5dd3676adc4d74759ad5b81cf0"

/* The 63 canonical context bytes of C1 (fingerprint preimage). */
extern const uint8_t df_context_c1_bytes[63];

extern const uint8_t df_golden_f1[DUOFORGE_STATE_V2_ENCODED_SIZE];
extern const uint8_t df_golden_f2[DUOFORGE_STATE_V2_ENCODED_SIZE];
extern const uint8_t df_golden_f3[DUOFORGE_STATE_V2_ENCODED_SIZE];
/* The M1 golden F1 (schema 1, 380 bytes): a "rejected: schema 1" input. */
extern const uint8_t df_golden_v1_f1[380];

void df_setup_g1(duoforge_battle_setup *out);
void df_setup_g3(duoforge_battle_setup *out);
void df_setup_g7(duoforge_battle_setup *out);

/* Creates a context and aborts the test process on failure. */
duoforge_context *df_make_context(const duoforge_context_config *config);
/* Creates a battle from a setup and aborts the test process on failure. */
duoforge_battle *df_make_battle(const duoforge_context *ctx, const duoforge_battle_setup *setup);
/* White-box builders: the internal team-selection transition, identity
 * primitives and direct field pokes. Every result passes duoforge_battle_check. */
duoforge_battle *df_make_g1(const duoforge_context *c1);
duoforge_battle *df_make_f1(const duoforge_context *c1);
duoforge_battle *df_make_f2(const duoforge_context *c1);
duoforge_battle *df_make_g3(const duoforge_context *c3);
duoforge_battle *df_make_f3(const duoforge_context *c3);
duoforge_battle *df_make_f4(const duoforge_context *c1);
duoforge_battle *df_make_f5(const duoforge_context *c1);
duoforge_battle *df_make_f6(const duoforge_context *c1);
duoforge_battle *df_make_g7(const duoforge_context *c4);
duoforge_battle *df_make_f8(const duoforge_context *c4);
duoforge_battle *df_make_f9(const duoforge_context *c4);
duoforge_battle *df_make_f10(const duoforge_context *c4);
duoforge_battle *df_make_f11(const duoforge_context *c4);
duoforge_battle *df_make_f12(const duoforge_context *c4);
/* Encodes via the public API and aborts on failure. */
void df_encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V2_ENCODED_SIZE]);

#endif
