# Plan: the first many-team training run

This is the owner's next step after the A/B/C report (`docs/learning/2026-10-03-learner-v2-abc/`). It is a proposal: the owner decides the open points.

## Teams

Run with every registry team that passes POOL setup on the pinned main commit. `teams.load` checks each team by creating its mirror battle; teams are never checked by name. That gives:
- the tournament pastes with real Stat Points (`PP_…`, about 57 at the time of writing);
- Teams A, B and C.

Left out of the first run:
- **The 573 Limitless lists (`LL_…`).** Their Stat Points, genders and levels are importer defaults, as their notes say, so they are systematically weaker than real teams. In the training mix they would skew what the policy learns to play against.
  - Proposal: a second run, or a resume, adds them as a separate group at a low weight (`--team-weights`, for example 0.25 each), once the first run shows the pipeline holds on about 60 teams.
- **Teams with Cursed Body,** until G27 lands with the pin's speed order.
- **Sand and Snow setters, and teams with the other values encoder 2 cannot show.** Encoder 2 raises on them, explicitly. Two options:
  - start after encoder 3 lands;
  - or start with an explicit team list that leaves them out. Each team plays a short random mirror through the encoder, and the result is recorded in the run's config.

  The owner chooses.

## Pairings

All N² ordered pairings with equal weights. With about 60 teams that is about 3,600 pairings, of which about 1.7 % are mirrors, so the mix is mixed. Each episode draws its own pairing (`pairing.pairings`, a pure function of the run seed, the environment and the episode).

## Model and options

| Option | Proposal | Why |
|---|---|---|
| Model | v2-M (2.07M parameters) | strongest at equal decisions on A/B/C (616 Elo against 565 to 513); about 60 teams need capacity. v2-S is the fallback if throughput matters more |
| Environments, workers | 256, 8 (14 if the owner allows all 16 threads) | as measured; the engine is a small part of the loop |
| Minibatch | 2048 | as measured; v2-L does not fit 4096 on the 4060 Ti |
| League | share 0.5, 4 slots, refresh 50, snapshot every 200 | as measured: learner wins about 80 % of its league games, no plateau |
| Entropy | `0:0.02,200M:0.005` | over learner decisions |
| Cut-offs | 500 steps, scored by tiebreak; unresolved and engine-refused steps are a loss for both and counted | no stalling (0 cut-offs on A/B/C) |
| Evaluation | every 200 updates, suite budget 512 | stratified; about 8 to 9 games per team per evaluation, so the per-team numbers are noisy until the final ladder |
| Run length | one night, `--minutes 480` | about 250M learner decisions and 16M matches at v2-M's measured 8,700 decisions/s and 2.1M matches/h |
| Data | `--data-kind pool`, pinned to one main commit and one build | resumes then keep the same fingerprint. The name check for resumes across data PRs (spec 12.4) follows as a small commit |
| Ladder afterwards | 6 checkpoints, suite budget 4096 | per-team Elo with intervals |

## Machine

Overnight on the RTX 4060 Ti (8 GB) in WSL, announced to the HauptSession. No quiet window is needed; the run's throughput figures are indicative.

For scale: mikumiku37 trained 330M games on a 5090. At our v2-M rate that would take about 150 hours on the 4060 Ti, and about 105 hours at v2-S.

## Next levers (the owner's order, measured one at a time)

1. **Throughput:**
   - the encoder in C in the batch workers (0.07 to 0.16 s per update plus the Python thread today);
   - then bfloat16 and fewer league opponents per step (the policy calls are the largest part, 0.23 to 0.40 s per update).
2. **Model v2.1:**
   - static dex features from decision 0020 (on main): types, base stats, move data, natures, the type chart as data;
   - an opponent-next-action auxiliary head, whose target is in the viewer's terms: per foe position the kind, the move id, the target and Mega.
3. **Encoder 3** (decision 0018, the HauptSession), **then encoder 4** (event history, its own decision note).

## Wish list for encoder 4 (event history)

- **Window:** the viewer's events of the last two turns, newest first, at most 24 events. Empty slots are masked.
- **Per event, from the viewer's event log (decision 0007) only:**
  - the event kind (one-hot over the 0007 kinds);
  - the actor: own or foe, and its position;
  - the move id, embedded with the move table of model v2;
  - the target position;
  - the damage as a share of the target's maximum HP in 10 buckets, and a KO flag;
  - the outcome flags: critical, super-effective, resisted, missed, protected;
  - a status inflicted, with its ailment;
  - a stat stage change: the stat and the signed amount;
  - a switch-in, with the member's roster index;
  - the turn offset: 0 for this turn, 1 for the one before.
- **Not in it:** anything the viewer's log does not show, such as foe stats or hidden RNG.
