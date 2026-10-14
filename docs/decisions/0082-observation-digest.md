# 0082 - The viewer's observation digest and the evaluation siblings

Status: **accepted by Owner and HS on 2026-10-14**, including evaluation-spec section 4.3's refinements (#485,
merged spec PR #488, main `b796ce43`). E1a records the version-1 bytes and independent vectors below; the D2 lane
reviews this implementation PR via the Owner. E1b adds the public digest sibling. Evaluation remains a later step.

Source: the D2 lane's
[`2026-10-14-observation-digest-draft.md`](https://github.com/chrismaghuhn/duoforge/blob/d49fd290/docs/superpowers/plans/2026-10-14-observation-digest-draft.md),
read on `search/d2-tree`; [evaluation spec](../superpowers/specs/2026-10-14-in-engine-evaluation-design.md) sections
3 and 4; depth-search sections 4.2, 6.3, 7.3 and Q3; decision [0007](0007-player-view-observation-and-events.md).
HS assigned 0082. This note assigns no public event, cause, feature or status number.

## Why and what changed from the draft

D2 merges nodes only when the selected seat observed the same step after the same parent information and action.
The engine supplies that observation identity; Python must not derive battle rules or hash a particle-filled public
record. The digest is a step transcript, not a state/RNG/encoded-row digest. D5 chains parent key, action and digest.

The draft's projected records and just `boundary_kind`/`request_mask` are insufficient. Own requested slots and
selectable options belong to the visible request. For example, the engine's existing trapping check may remove own
switch options without a separate ability announcement. Equal option counts can also describe different moves.
A raw roster index is not the species/forme shown in a switch. A final-leaf lookup is too late for SWITCH followed
by FORME/MEGA. These are the refinements approved in evaluation-spec 4.3.

## Where the digest is made

The leaf still goes through `dfi_battle_step_events_tape` in `src/state/request.c`. Its old signature remains a
wrapper; the new **private** `dfi_battle_step_observed` takes optional `dfi_observation_digest` scratch. Legacy callers
pass no observer. Public step functions, `duoforge_batch_expand`, battle state, codec and public layouts stay unchanged.

1. The step stages its existing events. `dfi_emit` and the lead-switch producer optionally capture the displayed
   switch/drag/revive/Illusion-break identity at emission time in a fixed private sidecar. They do not change an event.
2. In `dfi_events_fold_knowledge` (`src/combat/events.c`), immediately after `dfi_event_project` and before any
   own/foe/kind-specific `continue`, hash each final projected record for the selected viewer with `i >= first`.
   Own and field-wide records count, even when the knowledge fold ignores them. MOVE retargeting/flags are final here.
3. One streaming SHA state spans both team-selection windows. Prefix lead rows are hashed once; the second window
   replays them only for the existing knowledge timeline. Other steps hash their single complete event window.
4. After all checks and buffer-capacity checks pass and the working battle commits, query the selected viewer's
   request, observation, extension and factored domain through the existing authoritative queries. Append only the
   whitelist below and finalize only if the folded row count equals the independently staged engine event count.
   A mismatch refuses with `E_INVARIANT` / `observation_rows_mismatch`, leaving no valid key.
   A post-commit projection failure has its own status; it cannot rewrite the step
   status or roll back a successful battle. An uncommitted/failed step never publishes a key.

E1a exposes only private primitives and test plumbing. E1b makes the public sibling and Python sidecar available.
The D2 tree, solver and evaluator/key interfaces remain unchanged; it never substitutes a public-record key.

## Exact version-1 frame

All lengths/counts and multibyte payload scalars are little-endian. SHA-256 itself follows FIPS 180-4 and emits
32 digest bytes in its standard order. There is no host structure memory or padding in the stream.

| Order | Bytes |
|---|---|
| Domain | ASCII `duoforge.observation-digest.v1`, **one zero byte** |
| Viewer | one byte, absolute seat 0 or 1 |
| Each projected event record, in fold order | `u32 payload_length`, then that record's payload below |
| Event count | `u32`, number of canonical engine event records, including own/field rows |
| Request | `u32 payload_length`, then the viewer-authorized whitelist below |

The existing ILLUSION_END record represents its documented replace/end announcement together, as in the reference
converter; this framing counts engine records, not a new textual protocol split. It changes neither public buffers
nor reference-event comparison. No seed, RNG use, particle identity, worker/chunk index, epoch or private filename is
appended. Root information and own prior actions are separate inputs to the tree's information-set key.

Equal canonical streams/requests for a viewer yield equal hashes. Distinct streams are distinguished subject to
SHA-256's collision assumption, not a mathematical promise of collision freedom. All-zero bytes are reserved
for refusal and are never a valid key; status/validity is also checked.
An actual all-zero SHA result is explicitly refused as `E_INVARIANT` / `observation_digest_zero`.
Version/schema identity belongs in search provenance. A schema change
requires a reviewed new domain version; do not silently change v1 bytes.

### Event payload whitelist

Every payload starts with `kind:u8`. The following letters give its remaining fields **in this order**:

| Letter | Bytes and source |
|---|---|
| P | `position:u8` |
| O | `other:u8` (NO_POSITION is 255) |
| C | `cause:u8` |
| I | `id:u16`, only where it is a public move/forme/turn/item/ability identifier |
| B | displayed species/forme `u16`, gender `u8`, captured at the row's time; **replaces the roster id** |
| J | `id2:u16` |
| H | `hp:u16`, `hp_max:u16`, `hp_kind:u8`, `hp_flag:u8`, `status:u8`, after the existing viewer projection |
| D | `detail:u8` |
| A | `amount:u8` |
| F | `flags:u8` |

| Event kinds | Fields after kind |
|---|---|
| TURN | I |
| SWITCH, REVIVE | PCBJH |
| DRAG, ILLUSION_END | PBH |
| MOVE | POCIJAF |
| DAMAGE, HEAL | POCJH |
| FAINT, CRIT, PROTECT, CONFUSION_START, CONFUSION_END, CONFUSED, FLASH_FIRE, PROTECT_BROKEN | P |
| CANT | POCIJ |
| MISS | PO |
| SUPER_EFFECTIVE, RESISTED | PA |
| IMMUNE | PCJ |
| FAIL, STATUS | POCJD |
| BLOCKED | PD |
| BOOST, UNBOOST | POCJDA |
| CURE_STATUS | POCJDF |
| WEATHER | OCJDF |
| FIELD_START | OCJD |
| FIELD_END | D |
| SIDE_START, SIDE_END | ODA |
| ITEM_END | POCIJDF |
| FORME | PCIJ |
| MEGA | PJ |
| PREPARE | PI |
| ANIMATION | POIF |
| ABILITY, ACTIVATE, ITEM_START, ITEM_SHOWN | POCIJ |
| UPKEEP, CLEAR_ALL_BOOSTS | none |
| RESULT | D |
| SINGLE_TURN | POI |
| VOLATILE_START, VOLATILE_END | POCIJDA |
| TYPE_CHANGE | PCJDA |
| SWAP, COPY_BOOST | POCJ |

This is an explicit class per current event kind. Causes/flag combinations and detail variants must also belong to
that kind's implemented class in `dfi_line_schema_of`/`dfi_line_variant`. An unknown kind or variant refuses with
`E_UNSUPPORTED`, naming `observation_line_unclassified`, its numeric entry and kind name. In particular, reserved
kind 44 is not accepted by a range check. Missing captured identity or a missing HP projection is `E_INVARIANT`.
Reserved event bytes and non-whitelisted fields are absent. Nothing uses raw `sizeof(duoforge_event)` bytes.

B carries the actually shown current species/forme and gender, not the hidden Illusion holder or arbitrary particle
roster number. A SWITCH followed by a forme change retains the switch's earlier details. Renumbering a foe particle
without changing the shown identity does not split that line; a different shown identity does. REVIVE names its
bench member this way too. The existing public event's positions remain the visible absolute board positions.

### Authorized request whitelist, byte for byte

Only the selected seat's own side is serialized. The two requested-slot masks and result/request header are public
by decision 0007. Own roster addresses below are own UI addresses, not foe particle roster numbers. Existing queries
supply every field; no new rule is derived by a serializer.

| Group in order | Bytes |
|---|---|
| Public/new-boundary header | `step.kind:u8`, `boundary_kind:u8`, `request_mask:u8`, absolute-side requested-slot masks `u8[2]` |
| Own request | `requested:u8`, `slot_mask:u8`, `candidate_count:u32` |
| Own roster header | `member_count:u8`, `mega_used:u8`, `occupant:u8[2]`, `brought_order:u8[6]` |
| Each registered own member, in own roster order | the 54-byte member group below; no unregistered rows |
| Each own position, in position order | the 33-byte position group below |
| Own side conditions | `reflect_turns`, `light_screen_turns`, `tailwind_turns`, `aurora_veil_turns`, `stealth_rock`, `spikes`, `toxic_spikes`, `sticky_web`, `guard_flags`, `conditions`: ten `u8`s |
| Own factored-domain header | `kind:u8`, `member_count:u8`, `pick_count:u8`, `slot_count:u8[2]` |
| SLOTS only: own option lists, slot 0 then 1, offered order | for each used option: `kind`, `move_slot`, `target`, `mega`, `reserve`: five `u8`s |
| SLOTS only: pair matrix | `allowed[i]:u32` for `i < slot_count[0]`; no unused rows |

Member group (54 bytes): `species_id`, `hp`, `hp_max`: three `u16`; `move_ids:u16[4]`; own current `stats:u16[5]`;
`pp:u8[4]`; `pp_max:u8[4]`; own `stat_points:u8[6]`; then `move_count`, `hp_kind`, `hp_flag`, `pp_kind`, `location`,
`mega_capable`, `is_mega`, `gender`, `nature`, `ability`, `item`, `item_used`, `status`: thirteen `u8`s; own extension
`forme:u16`, `item_now:u8`. These are the existing authorized own view; no foe sheet or derived foe PP is included.

Position group (33 bytes): `stages:u8[7]`; `confused`, `charging`, `locked_slot`, `locked_target`, `acted`,
`protect_chain`, `flash_fire`, `protecting`, the documented POSITION_FLAG byte: nine `u8`s; own extension
`volatiles:u32`, `ability_now:u16`, `type_now:u8[2]`, `encore_slot`, `disable_slot`, `stockpile`, `perish`,
`move_failed`: five `u8`s; own `volatiles2:u32`. The public position-view member named `reserved` carries the three
existing POSITION_FLAG bits, not padding; unknown bits refuse. Hidden sleep/freeze/confusion counters are absent.
`transform_source` is excluded: it is a roster-index reference requiring its own visible-identity class. The current
engine refuses Transform; a nonzero source is explicitly refused here rather than hashed as a particle index.

TEAM_SELECTION has only the domain header: own member/pick counts describe its existing ordered selection domain.
An unrequested seat has domain kind zero. Unknown boundary, step kind, domain/option kind or extension revision
refuses. Declared record/count bounds are checked before any variable-length serialization. Maximum request payload
is **874 bytes** at the declared roster/slot bounds, with a compile-time bound inside 1,024 bytes of scratch.

Explicitly excluded: every foe member/position/sheet field (including candidate/domain data, PP, stat points, HP
maxima and hidden durations); every epoch; request/observation/domain/command padding; member/side/extension reserved
bytes; unused domain entries; extension metadata; raw battle/public-record/encoder bytes. No foe query or domain is
serialized. A missing authorized own-display field must be added through a reviewed schema change, not a whole-record
hash. Own option differences split the key even when candidate counts match. Epoch/foe unshown-option differences
alone do not.

## Public siblings (E1b and D4), complete signatures

These are the accepted additive signatures. E1a does not install them yet. The legacy prefix and its root-viewer
mapping are unchanged: leaf `i` uses `viewers[root_envs[i]]`, key of that root and sample of that leaf. Arrays have
`count` entries; digests are `count * 32` bytes. New opaque model/workspace handles need no implementation for the
early model-NULL mode. `duoforge_eval_error` has `leaf:u32` (`UINT32_MAX` for preflight), `phase:char[16]` and
`reason:char[128]`, bounded ASCII without private names.

```c
typedef struct duoforge_evaluator duoforge_evaluator;
typedef struct duoforge_eval_workspace duoforge_eval_workspace;
typedef struct duoforge_eval_error {
    uint32_t leaf;
    char phase[16];
    char reason[128];
} duoforge_eval_error;

duoforge_status duoforge_batch_expand_digest(
    duoforge_batch *leaves, const duoforge_batch *roots,
    uint32_t version, uint64_t ext_supported, uint64_t seed,
    const duoforge_request *root_requests,
    const duoforge_factored_domain *root_domains,
    const uint64_t *keys, const uint8_t *viewers,
    uint32_t count, const uint32_t *root_envs,
    const uint32_t *samples, const duoforge_factored_choice *choices,
    duoforge_status *step_statuses, duoforge_status *encode_statuses,
    duoforge_step_result *results, uint32_t *leaf_results, void *obs,
    uint8_t *digests, duoforge_status *digest_statuses,
    duoforge_eval_error *out_error);

duoforge_status duoforge_batch_expand_evaluated(
    duoforge_batch *leaves, const duoforge_batch *roots,
    uint32_t version, uint64_t ext_supported, uint64_t seed,
    const duoforge_request *root_requests,
    const duoforge_factored_domain *root_domains,
    const uint64_t *keys, const uint8_t *viewers,
    uint32_t count, const uint32_t *root_envs,
    const uint32_t *samples, const duoforge_factored_choice *choices,
    duoforge_status *step_statuses, duoforge_status *encode_statuses,
    duoforge_step_result *results, uint32_t *leaf_results, void *obs,
    uint8_t *digests, duoforge_status *digest_statuses,
    const uint8_t *cut, uint32_t *tiebreaks,
    const duoforge_evaluator *model, duoforge_eval_workspace *workspace,
    duoforge_status *eval_statuses, int32_t *values_q,
    duoforge_eval_error *out_error);
```

Two public conveniences share one private expand core. The digest sibling forwards without model/workspace/value
outputs. D4/D5 request values and optional digests from the evaluated sibling **in one call**, not two stochastic
expansions. In model-NULL mode value arrays must be NULL; encoder rows are optional and use the old shape/alignment.
In value mode model/workspace/eval statuses/values are required for positive count. Digest/status arrays are a pair;
the digest sibling requires them for positive count. In the evaluated sibling both may be NULL to omit digest work.
At least one of rows/digests/values is requested for positive count. Cut/tiebreak arrays are a pair. All these modes
preserve the spec's exact terminal/cut-off treatment; no network is run for their exact utilities.

Count zero accepts NULL arrays after global checks. Existing preflight ordering remains: required pointers, context,
encoder/version mask, distinct batches and valid indices/viewers, then new model/schema/workspace/capacity checks.
Preflight failure touches no leaf/output arrays; optional diagnostics name it. No partial batch, implicit resize,
JAX fallback or replacement of a failure with a plausible score. Roots stay read-only; input/output ranges do not
overlap. Tail entries past count remain untouched.

### Status values and publication

Existing statuses only; the independent digest status is essential because a successful step can be followed by
an unsupported projection. It must not be mislabeled a failed step or dropped payoff.

| Existing value | Meaning for the siblings/projection |
|---|---|
| `DUOFORGE_OK = 0` | phase succeeded; only a successful completed, nonzero digest is valid |
| `E_NULL_ARGUMENT = 1` | required pointer missing |
| `E_INVALID_ARGUMENT = 2` | invalid viewer/configuration/output mode; terminal-root step keeps the legacy refusal |
| `E_CONTEXT_MISMATCH = 3` | incompatible batches or evaluator/context |
| `E_CAPACITY = 4` | declared output/workspace capacity insufficient; no arena growth |
| `E_INVARIANT = 8` | staged event overflow, folded/event count mismatch (`observation_rows_mismatch`), bad captured identity, missing HP projection or inconsistent engine query |
| `E_EXHAUSTED = 9` | monotonic count/hash length or, later, fixed-point output cannot be represented |
| `E_UNSUPPORTED = 11` | named unclassified event/variant/request schema or existing unsupported battle operation |
| `E_STALE_EPOCH = 12` | submitted request epoch is stale, as in the existing step |

The sibling preserves all legacy statuses, seed derivation, atomic step behavior and exact results. On failed step,
the legacy copied/reseeded root remains as before; the digest bytes are zero and the key is invalid **because of the
step status**. Digest/encode/eval statuses of phases not run are OK, not fabricated additional failures. No old key
is inherited. A successful step reaching TERMINAL still has its new observation digest and exact terminal result.

A post-commit digest refusal has nonzero `digest_statuses[i]`, zero digest bytes and the successfully stepped leaf
left intact. Encoder/inference errors retain their own phase statuses. Return the lowest-index failed step, then
digest, then encoding/tiebreak, then evaluation; scheduling cannot pick the error. Optional diagnostics report that
same leaf/phase. An unsupported digest marks a refused information key; it never silently falls back to a record or
converts into a battle-step candidate drop. D2's existing refusal rules and no-unknown-payoff gates still apply.

E1a's private collector uses sticky `status`, `complete=false` and zero digest on a refusal. Its hash scratch may
contain a staged prefix, but that is never a published key. Model-NULL sidecars and SHA context are bounded stack
scratch. There is no heap, saved hash state in a battle/codec, mutable global hasher or full transcript buffer.
Windows keeps new private entry points outside automatic DLL exports; its nine pre-existing request entry points
retain explicit exports and signatures. E1b adds only its intended public entry points.

## E1b delivery: model-NULL expansion

`duoforge_batch_expand_digest` is installed as the first public sibling. The evaluated sibling above remains a
later delivery; E1b has no model, inference or weights. Both legacy and digest expansion use one private core.
The legacy signature, required row output, status order, seed formula and rules remain unchanged. Digest expansion
allows `obs == NULL`; version/mask preflight still runs, but no row is queried/encoded and encode statuses stay OK.
Digest/status outputs are required for positive count. The new diagnostic record has leaf at byte 0, phase at byte
4 (16 bytes), reason at byte 20 (128 bytes), size 148; existing public records keep their layouts.

Every selected root index and viewer is checked before dispatch; even a later invalid viewer prevents every leaf
from running. All global preflight failures name their reason and leave leaf/output arrays untouched. Optional
`out_error` is diagnostic output and may be written on preflight; success clears its strings and sets leaf to
`UINT32_MAX`. Refused steps have zero digests and digest/encode status OK for phases not run. A successful terminal
leaf still has its digest and exact result, while its encoder row is zero.

For a TURN root with either side's sealed re-prompt commands, E1b executes the ordinary step. On success only the
digest refuses as `E_UNSUPPORTED`, phase `digest`, reason `observation_reprompt_unsupported`, with zero key bytes.
The successful state, result and optional encoder row equal legacy expansion; an unavailable key never removes
that edge or becomes `engine_refused_leaves`. A genuinely failed step retains its own step status and no digest
phase runs. Legacy expansion keeps its existing re-prompt behavior. Observing retained commands later requires
routing them through the same observation contract.

Worker errors reduce by phase (step, digest, encode) then logical leaf index, matching the return status. Only
failures with requested diagnostics lock a bounded stack record using the platform's literal-initialized lock;
there is no growable error list, per-call heap, or synchronization on successful leaf work. Scratch for SHA lives
only inside the observed-step helper; legacy expansion does not instantiate that collector.

The Python adapter's `Batch.expand_digest(...)` returns legacy expansion's five arrays followed by the `(n,32)`
uint8 digests and `(n,)` uint32 digest statuses; `encode=False` returns `None` for the first output. Buffers are
borrowed and reused. `last_expand_error` exposes the bounded diagnostic record. `observation_keys(envs, viewer)`
returns copied keys plus refused booleans from this sidecar, never a Python hash of a particle-filled record.
It rejects missing keys, failed steps/digests and viewer mismatches. Adapter mutations invalidate affected keys
(conservatively all keys for non-expand mutations); legacy expand invalidates its written prefix. Read-only
queries do not invalidate keys. Direct privileged C mutation is outside the Python sidecar contract. The D2 lane
owns adoption in its unchanged tree/key interfaces and reruns its offline/bound gates before a ladder arm.

## Independent vectors and gates

`tools/reference/observation_digest_vectors.py` writes
`tests/support/observation_digest_vectors.h`; `--check` is CTest-registered. It uses Python's standard `struct` and
`hashlib`, reads no C serializer/output and needs neither Node nor a private artifact. It freezes 50 line payloads,
the 233-byte own-request fixture and a framed SHA-256 transcript. These are neutral wire fixtures, not claimed
battle setups or copied C results. The existing FIPS/padding vectors additionally exercise streaming chunk splits,
snapshot finalization and cumulative-length failure atomicity.

E1a also checks hidden-HP/maxima/RNG exclusion, displayed-damage changes, arbitrary foe roster-index exclusion,
row-time switch identity, Illusion's displayed versus owned identity, unknown kinds/variants and capacity failures.
The team-selection test proves four leads are counted once, then TURN. Artificial missed/duplicate folds refuse
with `E_INVARIANT` / `observation_rows_mismatch` against an independent staged count and publish no key.
Failed steps clear earlier private keys.
A white-box trapping control checks two engine-valid boundaries with different current-ability sources: identical
projected step events and boundary masks, different own switch options and digests. It is a request-projection
control, not a claim of identical CTS parent histories. Additional opt-in runs of every public reference battle
replay both viewers through the observed step and the
legacy step: exact canonical state/RNG, step result, tape use and event count agree; all existing reference state,
observation and event assertions still execute. The ordinary reference mode retains all its original assertions.

E1b then adds per-logical-leaf placement, worker/chunk reproducibility, public ABI/output/preflight tests and the
Python node-batch digest sidecar. Before D2 uses the digest, E1b must also pass:

- Two actual determinizations with the same public history and action, different hidden facts, and equal digests
  through the real engine step. The primitive projection controls above do not replace this E1 gate.
  The active-opponent control reconstructs two worlds from one engine-valid public HP boundary: hidden maxima
  202 and 170, different exact HP and attack Stat Points, both showing 50%. A real Recover emits a projected
  HEAL at 100% in both worlds, with equal digests. The negative control starts at 25%, emits 75%, and changes
  the digest. The public event API independently checks these HP-bearing rows. Distinct root RNG and distinct
  expansion samples also preserve keys when the actual visible transcripts stay equal.
- Invalid-viewer preflight before any leaf step executes, preserving outputs on refusal.
- Re-prompts run the normal step, with their digest either refused by name or processed through the observer;
  an unavailable digest never removes a successful edge or publishes a plausible key.

Shown gender is public and fixed by the switch details. CTS owns the test that every particle preserves that
recorded gender; only never-shown members may have sampled gender.

D2's offline pass and bound gate run again with real digest keys before a ladder arm.
No policy, network, D5 sampler or private weights are part of E1a. E2/E3 may proceed once this contract stands; each
individual E4 training run still needs its own explicit Owner go. Owner and HS decide adoption; HS merges PRs.
