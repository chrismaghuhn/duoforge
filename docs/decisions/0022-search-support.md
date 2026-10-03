# 0022 — Search support: leaf expansion and search seeds (M12 stage 1)

Status: owner decisions 2026-10-03. The owner approved the specification `docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md` ("ja geht klar"), including approach A and the public additions below. Its section 4.3 is written against decision 0021's interface on `chris/encoder-in-c` at 8515e21. It is checked against `main` again once 0021 is merged; at most a detail may change, since the layout (encoder 4, decision 0018 §10.2) is fixed. The owner approved the plan `docs/superpowers/plans/2026-10-03-m12-search-stage1.md` on 2026-10-03 ("plan sieht gut aus"). Follows decisions 0012 (batch runtime), 0013 §6 (search support, named there) and 0021 (the C encoder).

## 1. Context

Roadmap M12 stage 1 is a one-turn lookahead: own top-K pairs against the foe's top-M pairs, over S chance samples, scored by the value head and reduced by a Nash or an expected-value rule (the spec, sections 1 and 5).

Two things stood in the way:
- **No call loads a state.** The batch runtime creates environments from setups and resets them from the seed derivation. Decision 0013 §6 named "load a state into a batch environment" as the first function search needs.
- **No search RNG.** A copy of a battle carries its gameplay RNG, so a stepped copy would see the real future (ARCHITECTURE §10). `duoforge_battle_reseed` exists for this but has no seed derivation.

## 2. Decision

**Approach A:**
- Python orchestrates the search (`python/duoforge_search/`).
- The engine gains one parallel batch call and one pure seed function, declared in a new header `include/duoforge/duoforge_search.h`.

These were rejected:
- **A C search core:** the network runs in JAX either way, and the engine stays a pure simulator.
- **A Python loop over single-battle bindings:** single-threaded, about 5 to 9 ms more per decision.

**`duoforge_batch_expand`:** for leaf i, on the leaf batch's workers, in one pass:
1. Environment i of the leaf batch becomes a copy of its root, an environment of the root batch (no allocation).
2. It is reseeded with `duoforge_search_seeds(seed, keys[root], samples[i])`.
3. It is stepped with the two factored choices, built and checked as `duoforge_batch_step_factored` builds them.
4. If the leaf is not TERMINAL, the viewer's row is encoded exactly as `duoforge_batch_query_encoded` would encode that player of that environment.

The declaration, its inputs and its contract are those of the spec, section 4.3. Its status arrays:
- Step and encoder refusals have separate status arrays.
- A TERMINAL leaf reports its result and gets an all-zero row.
- The call checks its arguments before it touches any leaf: NULL pointers, the count, the root environments, the viewers, the version and mask, and the contexts.

**`duoforge_search_seeds(seed, key, sample, &initstate, &initseq)`:** splitmix64 is the function of decision 0012, the finalizer of x + 0x9E3779B97F4A7C15 over uint64 (wrapping).

    h         = splitmix64(splitmix64(seed + 0x5345415243480001) + key)    ("SEARCH" tag)
    s         = splitmix64(h + sample)
    initstate = splitmix64(s + 1)
    initseq   = splitmix64(s + 2) >> 1                                    (below 2^63, decision 0001)

The leaf seeds therefore depend on the seed, the key and the sample only:
- never on the cell (i, j), so samples are common random numbers across cells;
- never on a worker, a chunk or the leaf's position.

**Python-side derivations** (`duoforge_search.seeds`, the same splitmix64):
- **Arena decision key:** `splitmix64(splitmix64(draw(arena_seed, 0x2201, env, episode) + epoch) + seat)`, with `draw` from `duoforge_learn.pairing`. Here `epoch` is the root's request epoch.
- **Play draw of the Nash rule:** `(splitmix64(splitmix64(seed + 0x504C415900000001) + key) >> 11) · 2^-53` ("PLAY" tag), a uniform number in [0, 1).

## 3. Consequences

- **Privileged operations:** copy and reseed (decision 0002) now run inside a public call. Its outputs are rows of the viewer's own view of each leaf. A search on the true state is an oracle benchmark and is labeled so (ARCHITECTURE §10; spec, section 3).
- **Roots must not change during the call.** Only one caller uses either batch at a time, as decision 0012 requires of every batch call.
- **No allocation per call:** a leaf's temporaries (observation, domain, extension, slots and pair mask) live on the stack, as in `duoforge_batch_query_encoded`.
- **Additive API:** it gets a MINOR version bump, assigned by the HauptSession at merge.
- **Not decided here:**
  - building a battle from a view and a hypothesis (`duoforge_battle_from_view`, stage 2; it needs the belief model, decision 0013 §6.2);
  - tree search;
  - exact chance nodes.
