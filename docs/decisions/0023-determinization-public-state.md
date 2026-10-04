# 0023 — Determinization: the public state and worlds built from it (M12, the visible-information search)

Status: draft. Owner decisions of 2026-10-04: the brief of the visible-information search and the brainstorming answers to questions 1 to 7. The owner approved the design's sections 1 to 3 on 2026-10-04. This draft goes up with the specification `docs/superpowers/specs/2026-10-04-m12-visible-search-design.md`, and the owner approves the API with it (spec section 14). Three points added while writing need the owner's yes (the spec's status): the queue mask, facts rather than derivations in the record, and leaving the foe's own team out of the spread table. The number 0023 is reserved; the HauptSession may renumber it at merge. Follows decisions 0002 (privileged operations), 0007 (what a player sees), 0013 §6.2 (determinization, named there), 0016 (the live tracker) and 0022 (search support).

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
  - what they leave out though the player knows it: the foe's leads, the turns since each counter started, the order of the switch-ins, and what the foe knows of the player;
  - at a PIVOT, which positions have acted in the turn, and the player's own queued commands.
- **`duoforge_hypothesis`:** numbers only. It holds:
  - the foe's six stat point spreads;
  - its pick order, which is empty at TEAM_SELECTION;
  - one uniform for each foe member's exact HP, for each drawn counter instance on either side, and for each charging foe member's target;
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
- **A drawn counter:** u picks from the posterior of its draw, given the turns since it started.
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
| `E_UNSUPPORTED` | a state the record cannot express, from a documented list: a POOL tail feature whose support bit is clear, or any hidden value whose distribution the engine does not model |
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
- **The backoff:** (species, nature, item) with at least 5 sets, then (species, nature), then the species, then the stat shapes of the same nature-raised stat.
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
