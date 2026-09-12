# Decision and execution contract — proposed

## 1. Two sides, not four independent players

A side owns up to two active positions. A normal turn command is a joint side choice containing the necessary slot commands and side-wide constraints. Slot choices are not independent when they compete for a reserve Pokémon or a once-per-battle resource. Showdown's choice implementation contains such cross-slot validation [S2, S4].

Use typed records conceptually equivalent to:

```text
SlotCommand
  actor position + actor identity/activation binding
  kind: MOVE | SWITCH | forced profile-defined no-action
  move slot when applicable
  target selector when applicable
  reserve party identity when applicable
  supported transformation declaration when applicable

SideChoice
  request identifier
  side identifier
  one command per requested slot

DecisionBundle
  decision boundary identifier
  responses for exactly the currently requested sides
```

Team preview uses a distinct selection type, not fake move commands. It chooses brought roster members and lead assignments according to the profile. No-action is not a general strategic pass unless rules actually permit it.

A side choice must not switch two actors to the same reserve or spend a side-wide resource twice. Target selectors distinguish self, ally/foe positions, and automatic/spread targeting where required. Position conventions are documented once; rendering perspective does not alter engine identity.

## 2. Request lifetime

A request carries a monotonically checked boundary/epoch identifier, the authorized player, boundary kind, requested slot mask and model-visible action domain. Avoid wraparound; return an explicit exhaustion failure instead.

Requests and candidate enumeration are observationally pure: they do not mutate state, consume gameplay RNG or advance the execution cursor. Enumerating twice returns the same ordered domain for the same request state.

Candidate IDs are request-local unless a separately defined canonical encoding says otherwise. Never replay candidate array index 17 without binding it to its original request/domain. Replay stores a canonical command; a candidate index may be included for debugging.

## 3. Complete candidate domains

Initially enumerate complete joint side choices in a documented deterministic order. Capacity queries or bounded iterators must preserve completeness. Capabilities are accepted only where enumeration/storage capacity is justified; do not sample away legal options inside the core.

A later factorized interface may select slot A and then slot B conditioned on A. It must represent exactly the same accepted side-choice set and apply shared constraints. Completing that factorization does not advance the game. Test the factorized domain against exhaustive enumeration on tractable fixtures.

A move's selectable target and its actual resolved target differ. Redirection, switches and target disappearance are resolved later by the rules. Do not pre-resolve hidden or future targets when constructing model-visible candidates.

## 4. Simultaneous commitments

Ordinary-turn requests for both sides derive from the same pre-decision state. The host collects responses privately. Physical game resolution begins only after all required commitments are present and valid under the profile's selection protocol.

Submitting a side's response must not expose it to the opponent's policy. Asynchronous host arrivals, process timing, candidate-generation order and inference batching are not new public game events.

The first core API may require all currently required responses in one `step` call. A host-side collector can support separate arrivals without changing combat state. If rule-authorized re-prompts require retaining an accepted side's choice, store it as a sealed commitment and snapshot it; do not invite that side to react to information it should not yet have.

## 5. Mid-turn pauses

A pivot or replacement can require only one side to decide while earlier actions remain pending. The request mask indicates who acts. A paused state contains all continuation data necessary to resume:

- current execution stage and actor identity;
- pending action queue and consumed action markers;
- pending target/effect iteration where applicable;
- RNG state and usage position;
- relevant faint/switch processing;
- authorized disclosures and sealed commitments.

Resuming must not repeat PP consumption, entry effects, damage or random draws that already occurred. Snapshot restoration at this boundary must be tested.

## 6. Failure categories

Distinguish four categories instead of treating every failed action as the same error.

**Malformed API input:** wrong player, stale epoch, invalid enum/index, wrong response mask or malformed buffer. Reject without state, knowledge, RNG or event-cursor mutation. Public errors must not reveal hidden facts.

**Rule-authorized selection rejection/re-prompt:** a legitimate attempted command may reveal a rule-defined fact and require another choice. This is a successful semantic transition with its own events/request state, not a malformed-input error. Hidden trapping is a reference case to investigate. The profile defines exactly what is revealed, who receives it, which commitments remain sealed and what undo/retry behavior is allowed [S3, S4]. Do not implement unlimited omniscient probing.

**Legal action with an unsuccessful battle outcome:** a move can be accepted yet fail or miss. Resolve it normally, with the correct costs, events and random draws.

**Internal failure/unsupported mechanic/capacity failure:** never reinterpret it as a battle loss, draw or ignored effect. Prefer execute-on-working-copy then commit, or a tested rollback mechanism, so the last successful state remains recoverable. Emit a diagnostic artifact outside the model-facing channel.

Pure input validation must not accidentally become an information oracle. The offered domain is the player-selectable command domain under the interface rules, not all actions an omniscient observer predicts will succeed.

## 7. Step result and RL semantics

A semantic step reports the next boundary or an in-game terminal result. Operational cancellation, wall-time expiration, simulator guards and training horizons are truncations or errors, not in-game draws.

The batch layer exposes ready request rows keyed by environment, episode, player and request epoch. Some environments need one player; others need both; some are terminal. Do not invent policy decisions for waiting players.

For an eventual RL adapter, define discount/time accounting explicitly. Two internal command-selection stages must not automatically count as two turns or two environment rewards. Initial reward shaping is outside the core; terminal win/loss/draw results are enough for the first driver.

## 8. Minimum contract tests

Test malformed-input atomicity; full joint-domain completeness; shared-resource conflicts; stable enumeration; no gameplay RNG use during queries; same-window opponent-choice secrecy; one-side pivot continuation; two-side replacement; late/stale response rejection; snapshot at each exposed boundary; and rule-authorized rejection separately from malformed input.
