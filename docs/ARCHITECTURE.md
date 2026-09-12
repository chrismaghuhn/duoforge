# Architecture v0.1

Status: proposed. Target: portable C17, initially Generation 9 doubles, two fixed teams, one explicitly named rules profile. This document specifies our proposed design, not the architecture of an existing implementation.

## 1. Product boundary

The product is an authoritative headless battle library. It accepts validated configurations and player commands, resolves supported rules, publishes perspective-safe requests/events, and can snapshot, restore and replay.

It is not a team builder, tournament server, matchmaking service, model trainer or general simulator of every generation. The user's team-building system can later supply candidate teams, but a team must pass the engine's supported-profile gate before evaluation. Arbitrary teams must never be accepted by silently ignoring their mechanics.

Use separate identifiers for:

- mechanics semantics (initially a pinned Showdown-compatible Gen-9 slice);
- format legality and roster/brought-team sizes;
- information policy (team-sheet disclosure, HP representation, request visibility);
- operational episode limits;
- the tested coverage/certificate manifest.

A research profile with fixed leads, disabled Tera or omitted timers is not automatically an official VGC regulation. Do not infer the current regulation from the calendar. Tournament clocks and best-of-three management belong outside combat unless separately scoped.

Our first operational reference should be a pinned Pokémon Showdown revision. This is a practical compatibility target, not proof of cartridge-perfect behavior. Any known intentional divergence needs an explicit profile decision and evidence. Sources: [S1–S4].

## 2. Layering

```text
Offline source/data tooling                 Python ML host / evaluation
  source revision, provenance                     |
  normalized tables, support manifest             | batch requests/commands
                 |                                |
                 v                                v
       Immutable RulesContext            C ABI / batch adapter
                 |                                |
                 +--------------+-----------------+
                                |
                    Authoritative C battle core
                  requests / execution / information
                                |
                 replay, conformance tests, benchmarks
```

The source importer may read JSON or Showdown text. The core hot path uses typed IDs and generated immutable tables. Importing static metadata does not import executable mechanics correctly; each effect still needs an explicit implementation and tests.

## 3. Modules

| Module | Owns | Must not own |
|---|---|---|
| `data` | Immutable species/move/item/ability tables and canonical IDs | Live Pokémon state |
| `rules` | Profile restrictions, mechanics support, setup checks | Policy choices |
| `state` | Owned battle state, invariants and identity | File/network resources |
| `decision` | Requests, candidate enumeration and command validation | Opponent modeling |
| `execute` | Scheduling, moves, effects, switching, residuals | Dataset encoding |
| `information` | Per-player knowledge, redacted events and observations | Guessed hidden values |
| `rng` / `replay` | Explicit randomness, codecs, restoration and audit | Wall-clock game logic |
| `batch` / `bindings` | Environment scheduling and buffer transport | Independent mechanics |

Initially these can be directories in one library rather than eight separately versioned packages.

## 4. Three memory lifetimes

### 4.1 Immutable context

`PbdContext` owns or references immutable rules tables, profile configuration and support manifests. One context may be shared by many environments. Its lifetime must exceed that of all battles and snapshots using it. Stable IDs are meaningful only under that context's data and rules hashes.

Tables may use pointers internally because they are not copied into snapshots. Contexts must not lazily populate mutable global caches during battle execution. Precompute such caches before sharing or keep them worker-local.

### 4.2 Owned battle state

`PbdBattle` should contain everything necessary to resume a battle at a supported checkpoint:

```text
PbdBattle
  PokemonState roster[2][6]
  side state[2]
  active roster references[2][2]
  field state
  execution cursor and pending action/effect queues
  request epoch and sealed pending commitments when needed
  RNG state and consumption position
  player knowledge state[2]
  logical counters and terminal result
```

The six-member limit is the proposed initial supported-profile bound, not a universal Pokémon engine limit. Keep registered roster identity stable. Selecting the brought four and assigning active slots creates mappings; do not reorder identity every time a Pokémon switches.

A party-member identity and an active position are different types. Queued actions bind to an actor identity/activation as required; a replacement must not accidentally inherit an old occupant's queued move. Targets may refer to positions, not permanently to occupants. The selected command and the final resolved target are different records.

Store genuinely persistent condition state, PP, boosts, ability/item changes, effect counters, move locks and action-execution markers as the supported slice requires. Static species data belongs in the context. Model memory does not belong inside authoritative combat state.

No raw owning pointers, file handles or live C stack frames in copied battle state. Use bounded arrays and indices. Every bound requires a supported-profile rationale and tests. A capacity failure must be explicit; never drop effects or commands to stay within an arbitrary bound.

Do not impose an invented 2–8 KB budget. Measure battle size, knowledge size and scratch size independently after the first playable slice.

### 4.3 Scratch and output buffers

Reuse per-worker scratch buffers for sorting, candidate enumeration, temporary damage calculations and transactional output staging. Scratch is not authoritative. Nothing needed after an API return or pause may exist only there.

Caller-owned output buffers have explicit capacity and length. An insufficient buffer returns a capacity status without partially mutating the battle; a documented size query or context-specific maximum can help callers allocate once. No silent truncation.

## 5. Decision-boundary execution

Public progression is from one decision boundary to the next, not necessarily from one turn to the next. Supported boundary kinds should cover team selection, ordinary joint turn choices, replacement choices, pivot choices and terminal state. Add additional kinds only when a supported mechanic requires them.

The host obtains requests for all required players before executing either player's choices. It gathers their responses privately and calls the core with a decision bundle. The core validates the bundle and advances until another meaningful decision or termination.

A team-internal autoregressive choice construction is a model operation. Choosing slot A does not advance the battle or reveal what the opposing player selected. Only a complete side choice is submitted.

Showdown's protocol represents doubles choices as multiple slot commands, and its turn loop can stop for a mid-turn decision such as U-turn [S2, S3]. Our API must preserve those semantics rather than pretending every call consumes one complete turn.

## 6. Execution and effect ordering

Use an explicit scheduler and typed C handlers. Do not start with thousands of unrelated `switch` cases in one turn function, but also do not build a fully generic effect language.

A provisional decomposition is:

```text
validate/commit commands
  -> establish eligible scheduled actions
  -> select next action using generation-specific ordering
  -> resolve pre-action effects
  -> resolve targets and move/effect pipeline
  -> process faint/replacement/pivot boundaries as required
  -> update remaining scheduling information at prescribed points
  -> resolve residual phases in prescribed order
  -> create next request or terminal result
```

This is an organizational sketch, not a normative ordering of every Pokémon rule. In particular, do not freeze all damage modifiers into a mathematically commutative chain. Exact rounding points, spread handling, protection, immunity, ability/item hooks and per-target events need reference-derived fixtures.

Use typed hooks only where useful, e.g. priority modification, redirection, hit checks, damage modifiers, after-hit effects, switching and residuals. Handler order must encode rule precedence. Registration order, hash-map iteration, pointers or thread scheduling must not decide outcomes.

Showdown updates remaining action speeds dynamically for Gen 8+ at specified points [S3]. Do not sort four commands once at the start and assume the order can never change. Tie randomness also needs its own precise consumption and re-evaluation rules; arbitrary re-sorting must not introduce extra random draws.

Re-entrant mechanics should use bounded explicit execution records. A pause stores an engine-owned continuation containing the necessary program position, actors, remaining targets and queue state. Never leave the continuation implicit on the C call stack.

## 7. Information model

`FullState`, `PlayerKnowledge` and `PlayerObservation` are different contracts. A player observation is derived only from information that player may receive under the profile. Knowing an open team sheet does not imply omniscience about all remaining battle details.

Maintain a per-player knowledge state from authorized disclosures and visible events. Use masks or tagged unknown values; do not encode an unrevealed item as if it meant the Pokémon has no item. Preserve the information profile's HP precision instead of using internal exact HP as a shortcut.

The model-facing surface includes observations, requests, candidate identities/order/counts, selection errors and event visibility. It must not expose opponent pending commands, hidden teams/sets beyond authorized disclosure, internal RNG, full-state digests, privileged labels or reset seeds.

Hidden-information-sensitive command selection needs special care. Showdown explicitly handles potential trapping and information leakage [S3, S4]. A selectable command can be rejected or fail under game rules; do not produce omniscient action masks that reveal hidden causes prematurely.

For tests, compare two histories/states with identical authorized information and verify the same model-visible request surface until a legitimate new revelation occurs. Do not impose equality when the rules legitimately reveal different information.

## 8. Data and coverage

Keep a small generated data set initially. Each record has a stable source identity, normalized ID and referenced source revision. Each executable mechanic has implementation status and evidence links. Do not infer support from the presence of a name or numerical move metadata.

A setup acceptance check is scoped to `(engine revision, data hash, rules profile, information profile, two team specifications, tested coverage manifest)`. Separate `implemented`, `tested` and `certified for this profile`.

Review the reachable rules closure, not only the four printed moves of each Pokémon. PP exhaustion/Struggle, forced replacement, recoil, residual damage and any copy/call/transform behavior present in the chosen teams can expand the closure. Restricting teams is allowed; silently modifying those teams' rules is not.

Before complete certification, synthetic fixtures and deliberately simplified profiles are allowed only with explicit labels. An unsupported normal-game configuration must fail setup. A runtime escape into an unsupported mechanic is an engine error, not a no-op and not a valid training sample.

## 9. C ABI and Python boundary

Keep public ABI handles opaque. Conceptual entry points are `reset`, `get_request`, `step`, `observe`, `snapshot/restore`, and later batch equivalents. Full prototypes are implemented only when ownership, capacities and errors are tested. The sketches in this pack are not a promised ABI.

Core gameplay uses integer/fixed-point calculations with explicit rounding. Observation encoding may produce floats outside the rule calculations. A Python binding transports buffers and commands; it does not recalculate damage or infer legal actions independently.

Start with a single environment and a tiny native driver. Later keep many environments resident in C and transport ragged request/candidate batches. One model output is selected per player request; a value head is optional, not required by the engine.

Use array-of-structs battle storage initially for clarity and cheap state cloning. Convert observations to model-friendly packed arrays in the binding layer. Do not force the entire battle engine into a GPU/structure-of-arrays layout without profiling evidence.

## 10. Planning boundary

Cheap trusted snapshot/restore enables future search. It does not authorize a competitive agent to inspect the true opponent state or future engine RNG.

A future fair planner builds hypothetical states from its own observation/history and an explicit belief model, using separate search RNG. Planning on a privileged snapshot is an oracle benchmark and must be labeled as such. Search algorithm choice is outside the initial engine milestones.

## 11. Non-goals for v0.1

No all-generation support, full Pokédex certification, GUI, public-server automation, tournament administration, generic scripting VM, GPU battle kernel, learned rules, production RL algorithm or advanced search implementation. Build the smallest verified vertical slice first.
