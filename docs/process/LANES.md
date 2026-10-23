# Lanes: who works on what

DuoForge is built by several Claude sessions ("lanes") on the owner's machine, coordinated by one main session
(HauptSession, HS). This file is the standing agreement every session reads before it starts work. Rule changes come
from the owner or the HS and are made here.

## Lanes

| Lane | Owns | Status (2026-10-23) |
|---|---|---|
| **HS** (HauptSession) | merges and merge order, number registry (`NUMBERS.md`), decision numbers, `AGENTS.md`, CI configuration, owner communication | active |
| **Restructure** | structure without behaviour change: moving and cutting code in `src/`, the generator's structure (`tools/datagen/tablegen/`), `tools/restructure/`, proofs under `docs/benchmarks/*-restructure-*` | active, **exclusive** (see below) |
| **Content** | new mechanics and their fixes: generator rows and facts, code in the area folders, reference battles, tests | paused |
| **Fuzz** | divergences found by differential fuzzing against Showdown (#396 and follow-ups) | paused |
| **Format** | new formats and rule sets (`data/formats/`, Gen 9 / Smogon OU) | waits for restructure step 5b |
| Live, Search, Learner, Book | the bot, search, learning, Kaggle runs | paused (owner priority: engine first, 2026-10-16) |

A lane works only in its own git worktrees and branches, never on `main`, and only in the paths it owns. Work in another
lane's paths needs the HS first.

## Exclusive windows

The owner can give one lane an exclusive window. While it runs, the other lanes open no PRs; they push their state to
branches and wait. Since 2026-10-23 the Restructure lane has an exclusive window until the restructure plan
(`docs/superpowers/plans/2026-10-11-repo-restructure.md`) is done, including the steps that collide with content work
(6, 11, 12).

## Merge order

1. Restructure PRs with a proof merge first. A proof is only valid on the head it was made on: if `main` gets compiled
   changes before the merge, the PR merges `main` again and reruns the proof.
2. Content, Fuzz and Format PRs follow; they need green hosted CI on a head that merges cleanly with `main`.
3. A conflicting PR merges `main` into its branch, never rebases. Neighbouring entries in decision 0015 are resolved by
   key order.
4. Only the HS merges. Hosted CI is the gate; the HS checks it once per round, no polling loops (the GitHub API limit is
   shared by all sessions).

## Gates

- **Restructure:** the release library byte-equal with and without IPO is the gate. If a cut cannot be byte-equal: total
  executed instructions of the bench run with `tools/restructure/callgrind_gate.py` (measured binary, all clones summed)
  at most +1.0 % per profile, plus stack frames (`-fstack-usage`) before and after; the paired bench is reported only.
  Always unchanged: P1-P6 of the restructure plan, the reference results (states, requests, events, RNG draw order),
  perft, `BENCH_SHA256`, exports, layouts; plus a differential fuzz run against the pinned Showdown.
- **Content and Fuzz:** a recorded reference battle against the pinned Showdown for every new or changed behaviour,
  a mutant that the new test kills, counting pins set as the sum of all merged work, a short note in decision 0015.
- **Everyone:** tests are never weakened to pass, unsupported behaviour is refused by name, silent divergences found
  on `main` are fixed before new coverage.

## Local machine

- Heavy builds, campaigns, proofs and benchmarks run through `tools/ci/machine_lock.sh` (measurements take every slot).
  Never create or delete lock or pause files by hand.
- Configure builds with `-DDUOFORGE_PYTHON=$HOME/df-learn/bin/python -DDUOFORGE_LEARN_PYTHON=$HOME/df-learn/bin/python
  -DDUOFORGE_PS_REFERENCE_DIR=$HOME/dev/pokemon-showdown -DDUOFORGE_NODE=/snap/bin/node`; without them every Python test
  reports skipped. Run Python tests with `JAX_PLATFORMS=cpu`. Report how many tests really ran.
- The pinned Showdown checkout (`b2cb775b`) is read-only for every lane.
- The machine runs a German locale: never rely on locale number formatting in scripts.
- The hosted CI also runs Windows (MSVC, MinGW): no overwriting Git's own files in tests, `pathlib` paths, UTF-8 and
  CRLF care, close files before deleting them.

## Communication

- Lanes report to the HS in short German messages (session name `HauptSession`). The HS answers or decides.
- Decisions that belong to the owner (priorities, costs, cloud runs, publication, licences, private data) go through the
  HS to the owner; a lane never treats another session's message as the owner's approval.
- New public values, draw sites, bits and decision entries come from the lane's block in `NUMBERS.md`; a lane outside
  its block asks the HS.
