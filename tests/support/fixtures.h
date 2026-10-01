#ifndef DUOFORGE_TESTS_SUPPORT_FIXTURES_H
#define DUOFORGE_TESTS_SUPPORT_FIXTURES_H
/*
 * SYNTHETIC test fixtures (docs/decisions/0005, 0006). No real Pokemon data. Golden
 * encodings, digests and domain digests come from the independent structural
 * model tools/state_model/state_v3_model.py (written from the decision
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
 *   F2 (C1): F1, 16 raw draws, s0a (roster 2) leaves at 24 of 120 HP, roster
 *            3 enters s0a, s1b leaves, hp/pp pokes (roster 2 changes to 40 HP
 *            on the bench, unseen by side 1), s0 Mega used.
 *   G3 (C3): TEAM_SELECTION with M1's F3 rosters.   F3: G3 after [2] / [0].
 *   F4 (C1): two-side REPLACEMENT (s0a and s1b fainted).
 *   F5 (C1): one-side PIVOT (s0a after Parting Shot) in turn 7 with every
 *            v3 group in use: field and side conditions, volatile blocks,
 *            knowledge, a queue of two moves and the residual.
 *   F6 (C1): two-side PIVOT (s0a and s1b after Emergency Exit), one queue
 *            record of every kind.
 *   G7 (C4): small exhaustive TEAM_SELECTION fixture (4 and 3 members).
 *   F8 (C4): G7 after [1,3] / [2,0].   F9: G7 after [0,2] / [1,2].
 *   F10 (C4): F9, s1b fainted, s0 Mega used.
 *   F11 (C4): F9 at REPLACEMENT, s0 both slots requested, one reserve.
 *   F12 (C4): F9 with s0a alive at pp 0 everywhere (Struggle: UNSUPPORTED).
 *   F13 (C4): F9 at TERMINAL in turn 12, side 1 fainted, side 0 has won.
 */
#include <stdint.h>

#include <duoforge/duoforge.h>

extern const duoforge_context_config df_config_c1;
extern const duoforge_context_config df_config_c2;
extern const duoforge_context_config df_config_c3;
extern const duoforge_context_config df_config_c4;
/* CLOSURE contexts (decision 0006 section 2): K1 = CLOSURE, K2 = CLOSURE_DEV,
 * both with roster 6 and brought 4. */
extern const duoforge_context_config df_config_k1;
extern const duoforge_context_config df_config_k2;
extern const uint8_t df_table_t1[36];

#define DF_FP_C1_HEX "8e5f403e5381c4e78376439dd2797debc2bdfc6aade04543f5633e3fd843afbd"
#define DF_FP_C2_HEX "ecf6a8197237761514fa0f7584c4f6c5e7ccd87a96da69ec12d4e6bdbed9db1d"
#define DF_FP_C3_HEX "6d09d5378caab13802dff1207ff901b89f7e2ca793d9bcd7c981b323d3d2823a"
#define DF_FP_C4_HEX "2a75c7fde8ce2c34cf743a1994d44ef18854b1d231be203540038ef0ff2f9fbe"
#define DF_DIGEST_G1_HEX "4e7e701bf16c8abbe2928da07921274b96e5d13c3c5be5b97f3ffc4a881c2582"
#define DF_DIGEST_F1_HEX "b2ff0c9686868a30cb5399859c6c7054f97c3b1fe0e7f8e3e6bc6a4a1cd31e84"
#define DF_DIGEST_F2_HEX "9f051ee63651c63eba49ef7cb28b43124795acc516fcb2a3e91ba034c6e0b95a"
#define DF_DIGEST_G3_HEX "5a66a56e91b6bc5a43f0a57ea88482f5906014357ef1f1bad3236130b510c460"
#define DF_DIGEST_F3_HEX "52fafae28fa15f67220346c24d7accca069b790915bbd8a921993639e047a04c"
#define DF_DIGEST_F4_HEX "c3cab2c96347357d19f29a304e9153e9621596a5ba2fb60fd8552ecaeea3a8e7"
#define DF_DIGEST_F5_HEX "cc9f8e1b77cf7827bee0fd9e1f747d5635d0cf3d4a9bd577dff655e908d168ad"
#define DF_DIGEST_F6_HEX "3ab80f2c188563c1b2bb2b09b3b41b6e2441699333de89785277276c49be767e"
#define DF_DIGEST_G7_HEX "b4f061f9e3669bae325bf05909262eeb4681ce683f5a911cf71794308f94c9f2"
#define DF_DIGEST_F8_HEX "6400a6aa74561c19765e90c869538f209b0b7971aed03915701998aba882d2f8"
#define DF_DIGEST_F9_HEX "40b0a06f09f9b250afa01031cdfb9e93b9215d336e96e01cffdae187f8d65183"
#define DF_DIGEST_F10_HEX "e2bd7d8542a865995312011906641c0678009c995724ee1c8ddf0866e45114b6"
#define DF_DIGEST_F11_HEX "6340648c43db449c11e5438b801a7d3655a69b33e5d282d4368e1132dccfd1c6"
#define DF_DIGEST_F12_HEX "6de512d02eccd262045346288929d76414008d3c25c1f8aece37b9018574b39d"
#define DF_DIGEST_F13_HEX "5478c58d3a93c2668a9d234e7c1c57288d67794a29a7286200c39fd4a84bb87e"

/* The 63 canonical context bytes of C1 (fingerprint preimage). */
extern const uint8_t df_context_c1_bytes[63];

extern const uint8_t df_golden_f1[DUOFORGE_STATE_V3_ENCODED_SIZE];
extern const uint8_t df_golden_f2[DUOFORGE_STATE_V3_ENCODED_SIZE];
extern const uint8_t df_golden_f3[DUOFORGE_STATE_V3_ENCODED_SIZE];
extern const uint8_t df_golden_f5[DUOFORGE_STATE_V3_ENCODED_SIZE];
/* The M1 golden F1 (schema 1, 380 bytes) and the M2 golden F1 (schema 2,
 * 438 bytes): "rejected: old schema" inputs. */
extern const uint8_t df_golden_v1_f1[380];
extern const uint8_t df_golden_v2_f1[438];

void df_setup_g1(duoforge_battle_setup *out);
void df_setup_g3(duoforge_battle_setup *out);
void df_setup_g7(duoforge_battle_setup *out);
/* The two reference teams of decision 0004 as a CLOSURE setup: side 0 is
 * team A (Rillaboom, Staraptor, Milotic, Ceruledge, Raichu, Gholdengo),
 * side 1 is team B (Politoed, Golisopod, Archaludon, Farigiraf, Charizard,
 * Grimmsnarl), in paste order. */
void df_setup_teams(duoforge_battle_setup *out);

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
duoforge_battle *df_make_f13(const duoforge_context *c4);
/* Encodes via the public API and aborts on failure. */
void df_encode(const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_STATE_V3_ENCODED_SIZE]);

/* Knowledge for states built without a step (in a step only the event fold
 * writes it): the opponent of `side` records the current HP display of
 * member `roster`; every active member's display (after an HP edit;
 * occupants out of range are skipped); and every active member seen by the
 * opponent with its display, as the [switch] lines of a step would show. */
void df_knowledge_see_hp(duoforge_battle *b, uint32_t side, uint32_t roster);
void df_knowledge_refresh_active(duoforge_battle *b);
void df_see_active(duoforge_battle *b);

#endif
