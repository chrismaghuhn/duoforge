# M7 Python adapter — specification

Decision: `docs/decisions/0013-python-adapter.md`. Roadmap: M7 in `docs/ROADMAP.md`. Status: draft for the owner's review, 2026-10-01.

## 1. Scope

M7 delivers the following; all of it is evidence-backed and needs no trained model:
- a C ABI that Python can load
- a Python package that drives the batch runtime once per batch, with the GIL released and NumPy buffers passed in without a copy
- two baseline policies
- compact trajectory recipes with provenance, which replay to features
- a bounded generation example

Out of scope: learning algorithms, GPU code, EnvPool's asynchronous mode, and the search support of decision 0013 section 6 (loading a state into a batch environment, determinization).

## 2. C additions (library 0.11.0)

Shared library: target `duoforge_shared` (output name `duoforge_shared`, so `duoforge_shared.dll` or `libduoforge_shared.so`). It contains the sources of `duoforge` and `duoforge_batch`, compiled position-independent, with `WINDOWS_EXPORT_ALL_SYMBOLS` on Windows. The static libraries are unchanged. An explicit export macro waits for a frozen ABI.

New public functions:

| Function | Header | Contract |
|---|---|---|
| `duoforge_status duoforge_reference_setup(uint32_t pairing, duoforge_battle_setup *out)` | `duoforge.h` | The reference teams of decision 0004 for `pairing` 0..3 = A-B, B-A, A-A, B-B (side 0 first), `rng_initstate` 2026 and `rng_initseq` 1001 as in the test support. Checks: NULL is E_NULL_ARGUMENT, `pairing > 3` is E_INVALID_ARGUMENT, and `*out` is untouched on failure. `df_setup_teams` becomes pairing 0 of it. |
| `duoforge_status duoforge_battle_result(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t *out_result)` | `duoforge.h` | `DUOFORGE_RESULT_SIDE_0`, `_SIDE_1` or `_TIE` at TERMINAL, 0 before. The checks and the query check of decision 0011 are those of `duoforge_battle_request`. |
| `duoforge_status duoforge_batch_reset(duoforge_batch *batch, uint32_t env, uint32_t episode)` | `duoforge_batch.h` | Resets one environment to `episode` (fresh battle from the seed derivation). Out of range is E_INVALID_ARGUMENT; a failed reset keeps the environment. |
| `duoforge_status duoforge_batch_step_indices(duoforge_batch *batch, const duoforge_request *requests, const duoforge_side_choice *candidates, const uint32_t *counts, const uint16_t *indices, duoforge_status *statuses, duoforge_step_result *results)` | `duoforge_batch.h` | For every environment that is not TERMINAL, it builds the bundle from the last query's arrays and steps it in parallel. The epoch is `requests[2e].epoch`. For each player p with `requests[2e+p].requested`, the response is `candidates[(2e+p) * DUOFORGE_MAX_CANDIDATES + indices[2e+p]]`. An index at or past `counts[2e+p]` fails that environment with E_INVALID_ARGUMENT, and so does `DUOFORGE_BATCH_NO_CHOICE` (0xFFFF) for a requested player; outcomes are atomic per environment, as in `duoforge_batch_step`. |

`duoforge_batch_episode` gains no field; recipes take the result from `duoforge_battle_result`.

**Factored domain (owner, 2026-10-01, for JAX on the GPU).** The joint candidate list of a player is up to 784 × 32 bytes. With 256 environments that is 12.8 MB per query to ship to a GPU. The factored form carries the same domain in 652 bytes per player:

```c
#define DUOFORGE_MAX_SLOT_OPTIONS 32u
typedef struct duoforge_factored_domain {
    uint32_t epoch;
    uint8_t kind;          /* DUOFORGE_CHOICE_SLOTS or _TEAM_SELECTION; 0 when not requested */
    uint8_t slot_count[2]; /* SLOTS: entries of each slot list, 1..32 */
    uint8_t member_count;  /* TEAM_SELECTION: roster size */
    uint8_t pick_count;    /* TEAM_SELECTION: brought count */
    uint8_t reserved[3];   /* zero */
    duoforge_slot_command slots[2][DUOFORGE_MAX_SLOT_OPTIONS];
    uint32_t allowed[DUOFORGE_MAX_SLOT_OPTIONS]; /* bit j of allowed[i]: the pair (slots[0][i], slots[1][j]) */
} duoforge_factored_domain; /* 652 bytes */
typedef struct duoforge_factored_choice {
    uint8_t slot[2];  /* SLOTS: indices into slots[0] and slots[1] */
    uint8_t picks[6]; /* TEAM_SELECTION: ordered roster indices, leads first; rest 0 */
} duoforge_factored_choice; /* 8 bytes */
```

| Function | Contract |
|---|---|
| `duoforge_status duoforge_battle_factored(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player, duoforge_factored_domain *out)` | Checks as `duoforge_battle_candidates`. **Exact:** the allowed pairs in row-major (i, j) order, each made a side choice with the epoch and side, are byte for byte the list of `duoforge_battle_candidates`, in its order. At TEAM_SELECTION only `kind`, `member_count` and `pick_count` are set; the domain is the ordered tuples of distinct roster indices in lexicographic order. |
| `duoforge_status duoforge_batch_query_factored(duoforge_batch *batch, duoforge_request *requests, duoforge_observation *observations, duoforge_factored_domain *domains)` | `domains[2e+p]`, in parallel; any output may be NULL. |
| `duoforge_status duoforge_batch_step_factored(duoforge_batch *batch, const duoforge_request *requests, const duoforge_factored_domain *domains, const duoforge_factored_choice *choices, duoforge_status *statuses, duoforge_step_result *results)` | As `duoforge_batch_step_indices`. A SLOTS choice whose bit is not set, or whose index is past `slot_count`, fails that environment with E_INVALID_ARGUMENT. The step itself checks a TEAM_SELECTION choice. |

The rank of a choice in the joint list maps between the two forms: for SLOTS, the number of allowed pairs before (i, j) in row-major order; for TEAM_SELECTION, the lexicographic rank of the tuple. Recipes store this joint index.

## 3. Python package `python/duoforge`

- **Environment.** CPython 3.10 or later, NumPy 2. In this repository it is the project venv `.venv`, which git ignores. CMake option `DUOFORGE_PYTHON` names the interpreter for the Python tests; the tests are skipped explicitly when it is empty.
- **Loading** (`_lib.py`): the library path comes from `DUOFORGE_LIBRARY`, otherwise the package looks next to itself and in `build/*/`. It loads with `ctypes.CDLL` and sets `argtypes` and `restype` for every function used. ctypes releases the GIL for the duration of every foreign call.
- **Layouts** (`_layout.py`): NumPy structured dtypes with explicit offsets for `duoforge_request`, `duoforge_observation` (with its side, member and position views), `duoforge_side_choice` (with `duoforge_slot_command`), `duoforge_step_result`, `duoforge_battle_setup`, `duoforge_context_config` and `duoforge_batch_episode`. A C tool `duoforge_layout_dump` prints `sizeof`/`offsetof` of every field as JSON, and the layout test requires equality.
- **Classes:**
  - `Context(data_kind=CLOSURE, max_roster=6, brought_count=4)`
  - `Batch(context, setups: ndarray[setup_dtype], workers: int, seed: int)`, which owns these buffers, allocated once:
    - `requests` (E,2)
    - `observations` (E,2)
    - `candidates` (E,2,784)
    - `counts` (E,2) of uint32
    - `statuses` (E,) of uint32
    - `results` (E,)
  - `Batch` methods: `query()`, `step(indices: ndarray[(E,2), uint16])`, `reset(env, episode)`, `reset_terminal()`, `play_random(episodes, max_steps) -> ndarray[episode_dtype]`, `result(env) -> int`, `digest(env) -> bytes`, `episode(env) -> int`, `close()`.
  - `Batch.query_factored()` fills `domains` (E,2) (`FACTORED_DOMAIN` dtype), and `Batch.step_factored(choices: ndarray[(E,2), FACTORED_CHOICE])` steps it. The helpers `joint_index(domain, choice)` and `factored_choice(domain, joint_index)` map between the forms.
  - `seeds(seed, env, episode) -> (initstate, initseq, policy_seed)`
  - `reference_setups(pairings) -> ndarray[setup_dtype]`
- **Errors.** A non-OK batch status raises `DuoforgeError(status_name, statuses)`; there are no silent partial steps.
- **No rules in Python.** Python allocates, calls and views. Choosing an index is the policy's job; legality is the engine's.

## 4. Policies

- **`RandomPolicy`:** the native policy of decision 0012, vectorized. Each environment holds a splitmix64 state seeded from `seeds(seed, env, episode)[2]`. Each requested player, in player order, takes `next() % count`. It works on both forms: in the factored form it takes the allowed pair, or the ordered tuple, of joint rank `next() % count`. With the same seeds both forms must give exactly the native mode's episodes.
- **`ScriptedPolicy`:** reads only the player's observation and candidates. Each slot command of a candidate is scored as follows:
  - MOVE at a foe position: 100 − that foe's shown HP percent
  - MOVE without a foe target: 10
  - SWITCH: −50
  - PASS and NONE: 0

  A candidate's score is the sum over its two slots. The highest score wins, and ties go to the lowest index. Vectorized over (E,2,count).

## 5. Feature encoder

`encode(observation, domain) -> (obs_part, slot_part, pair_mask)` is a pure function of the player's own observation and factored domain. `obs_part` is a fixed-length float32 vector, `slot_part` has shape (2, 32, k), and `pair_mask` is a (32, 32) bool array. This is the form for a policy network with one action head per slot. Its exact layout is the plan's choice and is documented in its docstring. It never reads a battle, so it can carry no hidden information beyond what decision 0007 already proves for the observation (`duoforge.request.information`, the closure gate's information equivalence).

## 6. Trajectory recipes (owner, 2026-10-01: replay recipes, no feature dumps)

One recipe is two files: `<name>.npz` and `<name>.json`.

| Array in the npz | Shape, type | Content |
|---|---|---|
| `env`, `episode` | (N,), uint32 | where the episode ran |
| `setup` | (N,), uint8 | index into the manifest's setup table |
| `policy` | (N,2), uint16 | index into the manifest's policy table per side |
| `steps` | (N,), uint32 | steps to TERMINAL |
| `result` | (N,), uint8 | `DUOFORGE_RESULT_*`, 0 if truncated |
| `truncated` | (N,), bool | stopped by `max_steps` |
| `digest` | (N,32), uint8 | final state digest |
| `choice_offset` | (N+1,), uint64 | episode i's choices are `choice[choice_offset[i]:choice_offset[i+1]]` |
| `choice` | (M,), uint16 | candidate indices in decision order: steps in order, requested players in player order |

The manifest (JSON) holds:
- `format` ("duoforge-recipe-1")
- the library version and the context fingerprint (hex)
- the observation size and the SHA-256 of the observation dtype's layout (names, offsets, itemsize), which the layout test pins to the C layout
- the batch seed and `max_steps`
- the setup table (pairing name and SHA-256 of the setup bytes)
- the policy table (name and parameters)
- the creation time and the generating command

Replay (`replay(recipe, on_decision=None)`):
- It rebuilds every episode with a batch: setups from the table, seeds from (batch seed, env, episode), choices from the arrays.
- `on_decision(env, episode, player, observation, candidates, count, choice)`, when given, receives the features' inputs.
- A different final digest, a different step count or a choice outside the candidates raises `ReplayMismatch`. A recipe written by another library version or fingerprint raises `RecipeVersionError` before anything is replayed.

Size: about 100 bytes per battle (32 decisions × 2 bytes plus the per-episode columns), against about 25 KB per battle for observation dumps.

## 7. Example

`python -m duoforge.examples.generate --envs 64 --episodes 10 --policy random|scripted --workers N --seed S --out DIR/NAME` writes a recipe and then replays it. It prints battles, decisions, results per pairing and the bytes on disk, and exits non-zero on a mismatch.

## 8. Exit tests (CTest, label `python`)

| Test | Proves |
|---|---|
| C `duoforge.batch.step_indices` | index stepping equals bundle stepping, an invalid index and NO_CHOICE fail only their environment, and TERMINAL environments are skipped |
| C `duoforge.api.reference_setup`, `duoforge.api.result`, `duoforge.batch.reset` | the new functions' contracts |
| Python `layout` | every dtype equals the C layout |
| Python `equivalence` | `RandomPolicy` through `step` gives byte-identical episode records to `play_random`, for 1 and 4 workers |
| Python `recipes` | write, read and replay round-trip, digests match, and a changed choice raises `ReplayMismatch` |
| Python `policies_features` | the scripted policy picks only legal indices and is deterministic, and `encode` is pure (same input, same output) |
| Python `example` | the example runs with 8 environments and 2 episodes and replays |

The local CI (`tools/ci/local_ci.sh`) runs the Python tests in the Windows GCC Debug job when `.venv` exists, and on Linux in the WSL GCC Release job when `~/df-venv` exists. That venv holds NumPy and needs `python3.12-venv` (the owner installs it with `sudo apt install python3.12-venv`). JAX's GPU builds are Linux-only, so the package must work there.

| Test | Proves |
|---|---|
| C `duoforge.request.factored` | over the 64 battles of `duoforge.request.candidates_digest`, every factored domain expands byte for byte to the candidate list in its order |
| C `duoforge.batch.step_factored` | factored stepping equals index stepping, and a forbidden pair fails only its environment |
| Python `equivalence` (factored) | `RandomPolicy` on the factored form equals the native mode too |
