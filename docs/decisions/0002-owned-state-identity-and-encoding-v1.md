# 0002 — Owned state, identity, context and canonical encoding v1

Status: **proposed**. It is implemented and tested in M1 and becomes binding when the owner accepts the reviewed M1 change. M1 is **structural only**: there are no Pokémon rules, no step, no requests and no observations.

## 1. Public surface and status codes

- **The API is provisional.** `include/duoforge/duoforge.h` is the only public header. It declares no enums and no export macro, and it is not a frozen ABI. Opaque handles are used for `duoforge_context` and `duoforge_battle`.
- **Status is `typedef uint32_t duoforge_status`**, with macro values 0..10. The values are **stable within M1**; renumbering them before the ABI-stability decision is a deliberate, reviewed change.
- **Producer classes:**
  - Public-input validation produces the caller-input codes: NULL_ARGUMENT, INVALID_ARGUMENT, CONTEXT_MISMATCH, CAPACITY, MALFORMED, SCHEMA_MISMATCH and SEMANTICS_MISMATCH.
  - The invariant checker, init and internal contract violations produce INVARIANT. Internal contract violations include an RNG zero bound and identity-primitive preconditions.
  - Monotonic counters produce EXHAUSTED. These are the RNG `draws` counter and `next_activation_id`, both internal in M1.
  - Only the allocating entry points produce OUT_OF_MEMORY.
- **Translation rule.** An internal primitive's status is never relabelled as a caller-input error. A future transition forwards EXHAUSTED as a capacity failure and maps everything else to INVARIANT.
- **Read-once rule.** A public input struct (`config`, `setup`) is copied to the stack once; validation and initialization use only that copy.
- **Atomicity (universal, inherited by M2).** On any non-OK return:
  - no battle, context or RNG state is mutated;
  - no partial payload is written;
  - nothing is allocated or leaked.

  M1 additionally writes **no** out-parameter and no caller buffer on error. In particular, encode's E_CAPACITY writes nothing and reports no required size, because the size is fixed and available from `encoded_size`. How M2's variable-size outputs report their size is an **open decision**.
- **Rule-authorized rejection or revelation** (DECISION_CONTRACT §6) is **not applicable in M1**, because M1 has no choices. It stays a separate category: a successful result kind, never a status code.
- **Privileged operations:** encode, decode, digest, equal, check and reseed. Their outputs are diagnostics, replay or search-host artifacts and must never be model-facing. The M1 error order (full-state check before capacity) is acceptable only because these operations are privileged. Model-facing M2 operations must not copy it.

## 2. Context

- **Only synthetic data is accepted:** `data_kind` must be `SYNTHETIC`. The context holds `max_roster` (1..6), `brought_count` (1..max_roster), `species_count` (1..65535) and `move_count` (1..65535).
- **Validation runs on the u32 inputs before narrowing.**
- **Canonical context bytes v1** are a 31-byte encode-only preimage: envelope (kind CONTEXT=1, schema 1, semantics 1, length 31); `side_count 2`, `active_per_side 2`, `roster_capacity 6`, `move_slot_capacity 4`; `data_kind`, `max_roster`, `brought_count` (u8 each); `species_count`, `move_count` (u16 LE each).
- **The fingerprint is SHA-256 of those bytes.** It is independent of library version, compiler, build and addresses.
- **Binding.** A battle stores the fingerprint, not a pointer, and every call checks it. Adding real data or a profile bumps the context schema; M3 extends the preimage with table content hashes.

## 3. Owned battle state v1 (in memory; `sizeof` and padding are not a contract)

| Field | Width | Why it exists now |
|---|---|---|
| context fingerprint | 32 B | Compatibility binding. |
| `rng.state`, `rng.inc`, `rng.draws` | u64 | Decision 0001. M2 purity tests compare `draws`. |
| `next_activation_id` | u32, ≥ 1 | Binds commands to an occupant instance. |
| per side: `member_count`, `brought_mask` | u8 | Registered roster (stable order) and the brought set. |
| per member: `species_id`, `hp`, `hp_max` | u16 | `hp == 0` means fainted. Used for replacement eligibility. |
| per member: `move_count` | u8 | 1..4. |
| per move slot: `move_id` (u16), `pp`, `pp_max` (u8) | | Size of the M2 move-command domain; `pp == 0` is not selectable. |
| per side and position: `occupant` (u8, 0xFF = empty), `activation_id` (u32, 0 = empty) | | Active slot → roster mapping. |

- **Deliberately absent:** level, stats, types, ability, item, status, boosts, volatiles, field, turn counter, boundary kind, epoch, knowledge, terminal result, Tera/Dynamax/Z, and any Mega flag. An M1 battle is an inert structural snapshot.
- **Synthetic setup.** `hp_max` and `pp_max` are explicit synthetic inputs. `brought_mask` and `leads` are **synthetic fixture placement**, not a team-selection rule. M2/M3 replace this path, which changes the setup API and bumps semantics.
- **Canonical in-memory form (an invariant):**
  - members at index ≥ `member_count` are all-zero;
  - move slots at index ≥ `move_count` are all-zero;
  - an empty position is exactly `{0, 0xFF}`.
- **No `bool` fields**, so any byte pattern is a loadable (if invalid) state.

## 4. Identity

- **Positions.** Side 0/1 ≙ Showdown `p1`/`p2` and slot 0/1 ≙ `a`/`b`. This is naming only, with no parity claim. The flat index `side*2+slot` gives 0=p1a, 1=p1b, 2=p2a, 3=p2b.
- **Roster.** The roster index is the registration order and never changes. Selection and occupancy are mappings, not reorderings.
- **Canonical iteration order:** sides, slots, roster, move slots, each ascending.
- **Activation ids** are battle-wide, issued monotonically in `[1, UINT32_MAX-1]`; `next == UINT32_MAX` is EXHAUSTED. Every placement issues a fresh id, including re-entry of the same member, so a stale binding stops matching and **a replacement never inherits an old occupant's command**.
- **Primitives** (`dfi_place`, `dfi_vacate`, `dfi_current_binding`, `dfi_binding_is_current`) are internal. Every error leaves the battle and all out-parameters untouched. They are memory- and UB-safe on arbitrary state because they bound every index by capacity first. `place` also rejects a zero activation counter.

## 5. Invariants

The checker reports the **first** violation in a fixed order: context fingerprint → RNG inc odd → next activation nonzero → per side (member count; per member: species range, hp_max nonzero, hp ≤ hp_max, move count 1..4, per move slot: id range, pp_max nonzero, pp ≤ pp_max or unused-all-zero; unused members all-zero; brought mask range and popcount; per position: empty-with-activation, occupied-without-activation, occupant range (before the bit test), occupant brought, activation issued; occupant duplicate) → battle-wide activation duplicate. There are 22 ids after NONE.

- **Structurally allowed:** fainted occupants and reserves, `pp 0`, empty positions, any RNG state and draw count, and non-contiguous activation ids.
- **Decodability is not reachability.** State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## 6. Canonical encoding v1 and the artifact registry

- **Envelope** (20 bytes, LE, written byte-wise): magic `89 44 55 4F 0D 0A 1A 0A`, `artifact_kind` u16, `schema_version` u16, `semantics_id` u32, `total_length` u32.
- **Battle state v1** is exactly **380 bytes**; the field layout is in `src/codec/state_codec.h`. All slots are always emitted and unused ones are zero. There is no padding and no trailer.
- **Encoder.** It writes all 380 bytes unconditionally with fixed-capacity loops, so it is memory-safe on corrupt state.
- **Strict decode order.** Argument checks come first. For `duoforge_battle_decode` they include the destination handle's fingerprint (CONTEXT_MISMATCH) before any input byte is read. Then:
  1. `size < 20` → MALFORMED
  2. magic → MALFORMED
  3. kind or schema → SCHEMA_MISMATCH
  4. semantics → SEMANTICS_MISMATCH
  5. `total_length != size` (compared as u64; `size` is never narrowed) → MALFORMED
  6. `size != 380` → MALFORMED
  7. embedded fingerprint → CONTEXT_MISMATCH
  8. parse
  9. invariants → **MALFORMED**. E_INVARIANT is reserved for corrupted in-memory state.

  No byte at offset ≥ 20 is read before the size checks pass. Decoding commits only on success.
- **Registry:**

  | Kind | Schema | Semantics |
  |---|---|---|
  | CONTEXT (1) | 1 | 1 |
  | BATTLE_STATE (2) | 1 | 1 |

  Semantics 1 = "duoforge-m1-foundation": RNG contract 0001, the §3 init rules, the §5 invariants and no state transitions.
- **Bump rules:**
  - a layout change bumps that kind's schema;
  - a behaviour or meaning change bumps the semantics id;
  - decoders accept exactly the current triple, with no migration before certification;
  - goldens are never regenerated in place. At a bump, the v1 goldens become "rejected: schema 1" tests.

## 7. Digest, equality, clone, copy, reseed

- **Digest:** `SHA-256(380-byte canonical encoding)`. It is privileged and never applied to raw struct bytes. The FIPS 180-4 implementation is written from the specification.
- **`equal`:** byte identity of two unchecked canonical encodings in zero-initialized buffers. It covers every field, including RNG state and `draws`. There is no struct `memcmp` and no hashing, and it is deterministic even on corrupt state.
- **`clone` and `copy`:** struct assignment, valid only within the same build and a matching fingerprint. `copy` checks the dst and then the src fingerprint, and only after that treats `dst == src` as a no-op. `copy`, `clone`, `equal`, `encoded_size` and `reseed` skip the invariant check; `check`, `encode` and `digest` run it, and `decode`/`create_decoded` run it on the input. Consequently `reseed` rewrites the RNG of any fingerprint-matching state, including one that `check` rejects (for example an even `inc` becomes odd). It is a privileged host operation, not a validator. Persistence goes **only** through the codec.
- **`reseed(initstate, initseq)`:** replaces only the gameplay RNG, with `draws = 0` and `initseq < 2^63`, to decorrelate a forked copy for search. It is privileged, and a fair planner uses it on hypothetical states built from its own observations (ARCHITECTURE §10).

## 8. Coding rules and helpers

See `src/core/platform.h`: cast operands, never results; checked narrowing only; intentional wrap only in PCG and SHA-256; fixed-width types without a sign bit only; no floating point; ASCII-only. These are enforced by review, the source lint and extreme-value tests under GCC UBSan, **not** by the warning set (decision 0003).

Helpers with Pokémon semantics (rounding modes, 4096-based modifiers, `mul_div`) arrive with their first consumer in M3 and are validated against pinned reference fixtures.

The caller-visible record rule applies from M2 on: every struct written into a caller-owned or model-facing buffer has no implicit padding (enforced by static asserts on `sizeof`/`offsetof`), and producers zero-fill it before assigning fields.

## 9. Constraints for M2 (proposed)

- **State.** State schema v2 / semantics 2 adds `boundary_kind` (TEAM_SELECTION allows an empty brought mask and empty leads), a request epoch (u32, strictly increasing, EXHAUSTED instead of wrapping), request masks, sealed commitments where re-prompts need them, side-wide once-per-battle resource flags (for Champions: Mega Evolution) and a per-player knowledge section.
- **Records.** M2 defines its own public command records; the internal identity types are not promoted as-is.
- **Information-safety rules for model-facing APIs:**
  1. required sizes and capacity triggers depend only on the acting player's authorized view or on a profile constant;
  2. validation checks only the submission against the offered request and domain, never through opponent data;
  3. engine-side failures surface as one opaque internal-failure status;
  4. paired-information tests compare status codes and sizes, not only observation bytes.

## Evidence

| Test | Covers |
|---|---|
| `duoforge.state.context` | Fingerprints, faults (including 2^w + valid), boundaries, NULL. |
| `duoforge.state.setup` | Init, determinism, a 38-case fault table. |
| `duoforge.state.setup_sweep` | 142 fields × 29/32 values per base, 8,248 creates. Counts equal the model. |
| `duoforge.state.identity` | Stale bindings, primitive atomicity, corrupt counts, exhaustion. |
| `duoforge.state.invariants` | One corruption per id, allowed states, hostile counts, order, purity. |
| `duoforge.state.clone_equal` | Clone/copy/equal relation over 22 states, fork streams, reseed, padding independence, mismatch, corrupt state. |
| `duoforge.codec.golden` | Goldens, digests, round trips, RNG continuation, context bytes. |
| `duoforge.codec.negative` | Every decode path through both entry points on exact-size heap inputs, including `size = 380 + 2^32`; 23 targeted invariant edits; capacity; encoder coverage. |
| `duoforge.codec.mutation` | 290,700 single-byte mutations with exact per-region counts, plus 10,000 multi-byte mutations. |
| `duoforge.api.atomicity` | Status values and names, NULL sweep, context-mismatch sweep, precedence. |

Negative controls (8, run locally on 2026-09-30) each turn the named tests red. They are listed in the commit message of `1a312b1`.

## Appendix: fixtures and independent derivation

Fixtures (all SYNTHETIC):

- **C1** = {1, 6, 4, 16, 32}; **C2** = C1 with moves 33; **C3** = C1 with brought 1.
- **F1:** RNG (42, 54). Side 0 has 6 members, brought 0x0F, leads {2, 0}; member i has species i+1, hp_max 100+10i and (i mod 4)+1 moves, where move k has id 4i+k and pp_max 5+5k. Side 1 has 4 members, brought 0x0F, leads {1, 3}; member i has species 10+i, hp_max 200+i and 4 moves, where move k has id 31−(4i+k) and pp_max 8(k+1).
- **F2:** F1, then 16 raw draws, vacate s0a, place roster 3 at s0a, vacate s1b, then pokes: s0.m0.hp 0, s0.m1.hp 57, s0.m1.moves[0].pp 0, s1.m2.hp 0, s1.m0.moves[3].pp 7.
- **F3:** C3 with RNG (42, 54).

Expected values:

| Value | SHA-256 |
|---|---|
| C1 fingerprint | `607c34de37e9fee5a0019c983e3cf49dac8fc41389ec116f09243fecc60f0cb1` |
| C2 fingerprint | `53de00d6b5978adb2749ce1ecccc87997bb7a95d85a867efc96803a60bbb42ca` |
| C3 fingerprint | `b5c723a61b71c0e3595651ea8b6091a876537a6ae9320ef8cb1a983cbf79834c` |
| F1 digest | `40cfbb3f344bffc7a68dbd4a067245b1c316b952ceecddccba25224e416613be` |
| F2 digest | `626f046b35c295daf135f872c1f44e43de94084cfaf6aa10a73ad8ee34a1512f` |
| F3 digest | `99f1a5145e382ea60266806231eb783a83a6d755860279cfc3819124146a88d0` |

Derivation:

- Three independent planner/reviewer models derived these values while the M1 plan was being written.
- The committed stdlib-only model `tools/state_model/state_v1_model.py` was written from these tables, not from the C code. It reproduces all of them: fingerprints, the golden bytes (byte-identical), the per-region mutation counts, the 23 targeted invariant ids and the setup-sweep counts. The command is `python3 tools/state_model/state_v1_model.py` (Python 3.11.15), and the output sha256 is `26accd30b43dc60d2ac5fac9e9e2b18fcce2b458b4dfe48e36823caa3893cb78`.
- The golden C arrays in `tests/support/fixtures.c` were emitted field-annotated from that model and re-hashed. They were never copied from the C encoder.
