# 0023 — Determinization: the public state and worlds built from it (M12, the visible-information search)

Status: the owner approved the specification and this API, with the three added points, on 2026-10-04 ("Implementierung starten"). Owner decisions of 2026-10-04: the brief of the visible-information search and the brainstorming answers to questions 1 to 7. The owner approved the design's sections 1 to 3 on 2026-10-04. It went up with the specification `docs/superpowers/specs/2026-10-04-m12-visible-search-design.md`, and the owner approves the API with it (spec section 14). Three points were added while writing (the spec's status): the queue mask, facts rather than derivations in the record, and leaving the foe's own team out of the spread table. The number 0023 is reserved; the HauptSession may renumber it at merge. Follows decisions 0002 (privileged operations), 0007 (what a player sees), 0013 §6.2 (determinization, named there), 0016 (the live tracker) and 0022 (search support).

## 1. Context

- **Stage 1 searches the true state** (decision 0022). It is an oracle: it knows the foe's stat points, its exact HP and the secret counters of both sides. Its choices are no training target for a player that sees less (stage 3), and live play has no true state (stage 2).
- **Decision 0013 §6.2 named the missing function:** build a complete battle from a player's view and a sampled assignment of the hidden values. It needs an owner decision on the belief model.
- **No call builds a mid-game state today.** Battles start from setups at TEAM_SELECTION. Mid-turn fixtures are white-box (decision 0005), and decoding canonical bytes is privileged.
- **The observation is not enough to rebuild a battle.** It leaves out public facts a battle needs:
  - the order of the actives' switch-ins, which decides some ties;
  - the turns since each counter started;
  - what the foe knows of the player.
- **Hidden from a player under open team sheets** (spec section 3):
  - the foe's stat points, hence its stats and maximum HP;
  - the foe's exact HP, shown as a floor percent with flags at 20 and 50;
  - the foe's unseen members and its pick order;
  - the drawn counters of both sides (sleep, confusion, partial trap, lock);
  - the foe's charging targets;
  - the foe's queued commands at a PIVOT;
  - the RNG.

## 2. Decision

**Two records**, declared with the calls in a new public header `include/duoforge/duoforge_view.h` (working name). The plan fixes their layouts.
- **`duoforge_public_state`:** the complete public knowledge of one player. It is fixed in size, versioned and little-endian, like the canonical encoding. It holds:
  - a header (revision, player, context fingerprint, data kind, boundary, request state, epoch, turn);
  - the player's observation and its extension (decisions 0007 and 0018);
  - what they leave out though the player knows it: the foe's leads, the stored public values of non-random counters, the order of the switch-ins, and what the foe knows of the player; elapsed sleep/confusion attempts are not stored in schema 3;
  - at a PIVOT, which positions have acted in the turn, and the player's own queued commands.
- **`duoforge_hypothesis`:** numbers only. It holds:
  - the foe's six stat point spreads;
  - its pick order, which is empty at TEAM_SELECTION;
  - one uniform for each foe member's exact HP and each charging foe member's target, plus counter uniform slots used only for inactive-counter round trips while visible sleep/confusion remains unsupported;
  - at a PIVOT, the foe's queued commands for the slots that have not acted, as slot commands of the choice API.

  A uniform is a 64-bit word, read as u / 2^64.

**Facts, not derivations.**
- Every field the observation does not already hold is something the player's client shows, or a count of shown events.
- The engine derives whatever needs a rule.
- The live tracker therefore fills the record by folding the protocol, as it fills the observation (decision 0016 §2).

**Five public calls**
- **`duoforge_battle_public(ctx, battle, player, out)`:** one player's record, read from a battle. Like the observation, it reads the full state and writes only what the player may know.
- **`duoforge_batch_public(batch, players, out, statuses)`:** the same for every environment of a batch, on its workers.
- **`duoforge_battle_from_view(ctx, view, hypothesis, out)`:** a complete battle that passes the full check. Its RNG stays zero until a search reseeds it (decision 0022).
- **`duoforge_batch_from_view(worlds, views, hypotheses, count, statuses)`:** environment i of `worlds` becomes world i, on the workers, without allocation.
- **`duoforge_public_queue_mask(ctx, turn_start, view, mask)`:** at a PIVOT, it marks the foe's pairs at the turn's start (in the pair layout of `duoforge_batch_query_encoded`) that were legal then and agree with what the turn has shown since.
  - The caller keeps the same player's record of the turn's start.
  - The engine's rules decide what agrees: the order of switches, Mega Evolution and moves, and moves called by other moves.
  - Targets are not compared, since the records show none. So the mask is sound but not tight.

**One privileged call:** `duoforge_battle_hypothesis(ctx, battle, player, out)` gives the true values of everything the record leaves open.
- It joins the privileged operations of decision 0002, for tests and the oracle only.
- Its output is never model-facing.

**The engine's mapping** (C only, integer arithmetic)
- **A uniform u** picks the ⌊u · n / 2^64⌋-th of n equally weighted values. With integer weights, it picks the value whose cumulative range holds ⌊u · total / 2^64⌋.
- **Stats and maximum HP** follow from the stat points by the formulas.
- **Exact HP:** u picks among the values that the shown percent and flag allow. A never-seen member is at full HP.
- **Visible sleep/confusion:** public extraction and world construction return `E_UNSUPPORTED` explicitly, based only on the player's visible status facts, never on hidden remaining counters. Schema 3 lacks elapsed-attempt history, so no conditioned draw is claimed. The honest search plays the raw policy for these decisions; the arena reports the count and share per cause (`visible_sleep`, `visible_confusion`, with overlap possible). Elapsed tracking, if needed after observing those shares, requires a later decision.
- **A charging target:** u picks among the targets the move could have chosen.
- **Every value derived from a hidden one,** such as a Substitute's HP, is computed from the world's values.
- **`duoforge_battle_hypothesis`** gives each uniform the middle of the range of words that picks the true value.

**Refusals.** Every refusal is explicit, and nothing is written on one, as for every call in `duoforge.h`.

| Status | When |
|---|---|
| `E_NULL_ARGUMENT` | a missing argument |
| `E_CONTEXT_MISMATCH` | a record's fingerprint is not the context's |
| `E_SCHEMA_MISMATCH` | a record of another revision |
| `E_MALFORMED` | a record's reserved bytes or ranges are wrong |
| `E_INVALID_ARGUMENT` | the hypothesis contradicts the record: a spread past 32 or 66; a pick order against the leads or a member seen, or one at TEAM_SELECTION; a queued command for a slot that has acted, or one its member could not have chosen. Also a queue mask for a view not at a PIVOT, or with a `turn_start` that is not the same player's TURN record of that turn |
| `E_UNSUPPORTED` | visible sleep/confusion (public status facts only), or a state the record cannot express, from a documented list: a POOL tail feature whose support bit is clear, or any hidden value whose distribution the engine does not model |
| `E_INVARIANT` | a built world fails the full check (an engine bug) |

**Contracts, each proven by a test** (spec section 4.3)
- **Round trip:** `from_view(public(s, p), hypothesis(s, p))` equals `s` byte for byte, apart from the RNG.
  - It holds for every state of random play, under every data kind, at every boundary and for both players.
  - The refusals are counted by reason, and the counts are pinned.
- **Tightness:** `public(from_view(public(s, p), h), p)` equals `public(s, p)` for random valid h.
- **Info-safety:** the record's sizes and statuses depend only on p's view.
- **The own row:** p's encoded row is the same in every world of one record.
- **The queue mask** marks the foe's true pair at every PIVOT of random play.
- **The batch forms** equal the single calls for every worker count and allocate nothing.

**The belief model** (decision 0013 §6.2; owner, 2026-10-04)
- **The source:** the foe's stat points are drawn as whole spreads, from the stated spreads of the curated pastes: the `PP_` teams and Teams A, B and C.
  - `LL_` spreads are importer guesses and are not used.
  - Replays show no stat points.
- **The backoff:** (species, nature, item) with at least 5 sets, then (species, nature), then the species, then sets of the exact same nature, then all remaining stated spreads.
- **Leave one team out:** in the arena and in self-play the foe's own team's sets are left out.
- **Weights:** every world weighs 1/W. `Belief.sample(view, history, n, seed)` keeps the hook for later updates from damage and turn order (M13 lever 3).
- **Where it lives:** the belief is in Python and draws numbers only. The distributions of the engine's own draws stay in C.

**World seeds** (`duoforge_search.seeds`, with the splitmix64 of decision 0012)

    g      = splitmix64(splitmix64(seed + 0x574F524C44000001) + key)     ("WORLD" tag)
    z_w    = splitmix64(g + w)
    x_w,k  = splitmix64(z_w + k),   k = 1, 2, ...

- Each kind of draw has its own fixed range of k.
- The stream is separate from the leaf seeds and the play draw of decision 0022. The leaves of world w use leaf sample w.

**These were rejected:**
- **Worlds built in Python by editing canonical bytes:** decoding is privileged, and the stats, the HP bounds and the counter posteriors would become rules in Python.
- **The observation as the view:** it lacks the facts listed in section 1, so no round trip could prove a world complete.
- **Values instead of uniforms in the hypothesis:** Python would need the distributions of the engine's draws.
- **Python checking a queued pair against the turn so far:** the order of switches, Mega Evolution and moves is a rule. The engine's queue mask does it.

## 3. Consequences

- **The privilege boundary**
  - `duoforge_battle_public` reads a full battle but writes only the player's knowledge, so it is public, like the observation.
  - `duoforge_battle_from_view` reads no battle: a world is the record plus the hypothesis.
  - The honest search never calls `duoforge_battle_hypothesis`. An end-to-end test checks that two roots that differ only in values hidden from the searcher get the same decision (spec section 12).
- **The oracle stays labeled.** Stage 1 remains the oracle benchmark, and the measurement reports the oracle bias, oracle minus honest (spec section 9).
- **Live:** a test proves the tracker's record equal to `duoforge_battle_public`, byte for byte, at every request of every committed closure battle, as `duoforge.python.live` does for the observation.
- **Unsupported states:** the search lets the raw network decide and counts the decision as "unreconstructible", with its reason (spec section 6.7), never silently.
- **No new floating-point exception:** the uniforms are integer words, mapped in integer arithmetic. `float` stays in `encode.c` and `duoforge_encode.h` (owner, 2026-10-03).
- **Batches:** no allocation per call. The batch forms run on the batch's workers, and a batch has one caller at a time (decision 0012).
- **Additive API:** a MINOR version bump, assigned by the HauptSession at merge.
- **Not decided here:**
  - closed team sheets (M14), where the hypothesis would also hold the unrevealed sets;
  - belief updates from damage and turn order (M13 lever 3);
  - a tree search;
  - the stage 3 training loop.

## 4. Amendments from the implementation (PR A, 2026-10-04)

The engine state decided these details. `include/duoforge/duoforge_view.h` documents them.
- **The public state is the masked canonical encoding.** It is the battle's canonical bytes (`src/codec/state_codec.h`) with the hidden values replaced: RNG zero; the foe's stat points, stats, maximum HP, exact HP and PP zero; its brought set empty and its pick order cut to the leads; running sleep and confusion counters as `DUOFORGE_VIEW_HIDDEN`; a charging foe's target as `DUOFORGE_VIEW_HIDDEN_TARGET`. A small header repeats what the search reads (boundary, turn, epoch, seen mask, leads). The layout is the codec's, so it needs no second definition, and a world is decoded strictly, so it passes the full check.
- **Counters set without a draw** (Encore, Taunt, Heal Block and the others) stay as the remaining turns the state holds. They are public, and the starting length is not in the state, so no "duration variant" bit is needed.
- **Drawn counters are not conditioned on the turns elapsed,** because the state keeps no such count. A running sleep has 1, 2 or 3 turns left, with weights 3, 3, 2. A running confusion has 1 to 5, with weights 4, 4, 3, 2, 1. Each weight is the prior's tail, the value seen at a random point of the run. Conditioning on the elapsed turns needs that count in the state: a later step.
- **The freeze counter is public:** it always starts at 3, and the thaw chance is separate.
- **Refused for now (`E_UNSUPPORTED`, public criteria):**
  - a PIVOT where the foe still has sealed or queued commands (PR B samples them);
  - a foe Substitute, whose HP follows hidden damage;
  - a partial trap or a locked move (no mechanic draws their turns yet).
- **A hypothesis whose maximum HP no exact HP fits** (a display flagged at exactly 20 or 50 % constrains it) is `E_INVALID_ARGUMENT`. The search draws another spread for that member and counts it.
- **A world's RNG** is seeded with (0, 0), since a zero PCG state is not a valid state; every leaf is reseeded anyway.
- **A built world that fails the full check** is `E_MALFORMED`, as the strict decoder reports it.
- **The proof (`tests/test_view.c`):** 80 random games each under CLOSURE, TEAM_C and POOL (Teams A, B and C), about 8,500 views. Each view is a byte-equal round trip; 4 random hypotheses per view give back the same public state and the same observation and extension; hidden sleep, confusion and charging targets all occur.

## 5. PR B: batches and PIVOT queues

The batch calls use the existing worker hooks, allocate no storage, report per-environment statuses and preserve each refused output/environment. Invalid batch arguments are checked before any worker runs.

Public record revision 2 exposes the pending foe-slot mask and queue count. At PIVOT, remaining MOVE records are sorted by kind, side and slot, and the foe's move slot and target are masked. Queue order also depended on hidden priorities and speeds; it therefore cannot remain public. Hypothesis revision 2 adds the pending commands and the inverse permutation for privileged byte-exact round trips. Search worlds use the canonical permutation: the resumed switch-ins run before the engine sorts remaining moves again. A queue containing switch, entry or Mega actions, or sealed opponent commands at a re-prompt, remains explicitly unsupported. No original queue order is passed to the honest search. A PIVOT without a publicly shown current-turn Protect, Helping Hand or Follow Me volatile is refused as a whole (these reset in every residual; move_actions does not): rejecting only an outstanding private Mega action before the move phase would reveal an unannounced declaration. A white-box regression checks identical refusals with and without that hidden declaration.

The queue mask builds neutral worlds in C and compares public switch/activation, Mega and move-use facts. It does not compare targets. An unknown brought member can change the turn-start domain's switch options and pair indices: without a unique brought set the mask returns E_UNSUPPORTED, rather than guessing those indices. This refusal belongs to the search's unreconstructible counts.

The random-play proof covers 8,332 views, including PIVOT, under CLOSURE, TEAM_C and POOL. It checks 157 successful queue masks against the true turn-start pair and counts 199 explicit ambiguous-bench refusals. Batch equivalence and argument atomicity run with 1, 2, 3, 4, 8 and 16 workers; the TSan selection includes view tests. The library MINOR bump remains assigned at merge, as for PR A.

## 6. PR E: visible-information lookahead and arena

`duoforge_search.honest.Honest` holds the preview and current turn-start public records per batch environment, seat and episode. It evaluates only the viewer's row of the real root; every foe row is a reconstructed world. The privileged hypothesis function and true-root encoding are absent from this path, including error diagnostics. C owns stats, HP, counters, targets, legality and queue reconstruction. Bench filtering compares roster indices; queued commands are copied whole from the turn-start domain.

Worlds use the belief words of PR D and their own world index as the leaf sample in every cell. One Bayesian strategy holds across all worlds. Records hold all N/E/X outcomes, per-world foe probabilities, W, the spread-table hash, drops, redraws and reconstruction refusals. K=1 plays the raw policy without building worlds. Unsupported reconstructions and missing history play raw with an explicit counted reason; other failures stop with the public record and, for solver failures, the tables.

Two interface details follow from the available C API:
- A rejected world reports only a status, not a failed member. An HP contradiction therefore redraws all spreads of that world, retaining its HP/counter/target/bench/queue words and every other world's spreads. After 256 attempts the search stops explicitly.
- Hidden bench membership can change the foe's slot-list indices. The world-weighted probability ranking is filtered by each world's C legality mask; each world's columns name its own legal responses. No illegal pair is submitted to expansion, and the foe's Bayesian response remains specific to its world.

The spread table reads A/B/C and PP_ sources in registry order sorted by id, validates their hashes, skips unstated spreads and counts sets absent from the active context. LL_ guesses are excluded. Arena foe pool indices map to source ids for leave-one-team-out.

`python -m duoforge_search.arena --search honest --agents N,E,X --lam 0.5 --worlds 16 ...` selects this path; `--search oracle` retains the labeled stage-1 path and now also supports X. The default remains oracle for existing command lines. Conditions record the search kind, W, lambda, source counts and table hash; searched-decision costs separate public records, world builds, team head, leaves, network and solve. The tests use synthetic checkpoints and CPU smoke runs only. Plan task 13's measurement and the live/training stages are not part of this PR.
The random-play proof covers 7,558 supported views, including PIVOT, under CLOSURE, TEAM_C and POOL. It checks 20 successful queue masks against the true turn-start pair and counts 32 explicit ambiguous-bench refusals. Batch equivalence and argument atomicity run with 1, 2, 3, 4, 8 and 16 workers; the TSan selection includes view tests. The library MINOR bump remains assigned at merge, as for PR A.
## Review amendment: elapsed counters (owner, 2026-10-04)

The random-point sleep/confusion mixture in section 4 is superseded. Schema 3 does not store publicly elapsed attempts. Any visible sleep or confusion therefore makes public extraction and world construction explicitly E_UNSUPPORTED. The predicate reads only the player's public observation, never the hidden remaining counter. Tests vary all remaining values and both viewers and check unchanged outputs. The honest arena reports the count and share of raw fallbacks separately for visible sleep and visible confusion (overlap is possible). If that share is large, elapsed tracking requires its own later decision and implementation; it is not silently approximated here.

## PR D: back-off review clarification

Review clarification: back-off level 4 compares exact nature ids, as the NumPy table implements; level 5 uses all remaining source sets. A redraw advances from the original eligible level towards level 5. The stronger exact-nature match is intentional; no nature-rule implementation is hidden in Python.

## PR E: review notes

Review notes for E: stale/missing turn-start records count as unreconstructible. Every stopped-world reproduction includes the search seed, exclusion, preview and turn-start records (or explicit absence), plus the current public view. Redraw failures retain that reproduction. Arena diagnostics report counts and shares per visible-counter cause; sleep and confusion can overlap. Oracle records explicitly label search=oracle. Oracle E also computes N/X for the diagnostic contract; its played E action remains the expected-value maximum, verified against the original path.
