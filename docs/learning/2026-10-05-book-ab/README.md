# Opening-book A/B: closing record (2026-10-05)

The preview book gives **no measured gain** on `params-49333`: paired differences range from -0.0110 to
+0.0005. Against BC the 95% interval excludes zero on the negative side. Only 258 of 2,000 previews (12.9%)
per opponent received a supported book choice.

**Owner decision:** keep the book in the code as an option, **default off**, and **do not use it in the bot**.
The owner's interpretation is: **the book is too thin / human leads don't transfer to the net's play style**.
Sparse full-choice coverage is measured; play-style mismatch is an interpretation, not an isolated causal result.
This closes the current experiment; it does not schedule a follow-up or change code.

[aggregates.json](aggregates.json) contains configuration-level aggregates and provenance only, following the
report format of [#236](https://github.com/chrismaghuhn/duoforge/pull/236). No book tables, individual games,
preview rows, checkpoints, private paths or run directories are included.

## Setup

- Code `fbcc623e88754c863b7d4a7f38be6ef63f6786d2`, library 0.43.0; preview integration [#234](https://github.com/chrismaghuhn/duoforge/pull/234).
- Candidate: frozen `params-49333`. Opponents: the same unchanged checkpoint and fixed BC (`params-0`), 3600
  and 11000 panel. Checkpoint fingerprints are in the aggregate; source paths are omitted.
- 2,000 games per arm per opponent, 16,000 total. Identical pairings/seeds in both arms, both seat orders;
  95% percentile-bootstrap intervals with 2,000 resamples of paired seat blocks. Maximum 1,000 steps.
- Champions-only, strictly validated source selection, preserving all selected observations. SV VGC is excluded;
  the original book remains unchanged. No source rows or book contents are published.
- `override`, minimum 20 observed games per full lead/back choice, ranked by the lower Wilson endpoint
  (`z=1.96`). Prior mixing was **not** measured. All battle-turn decisions remain the raw network's.
- CPU backend, four workers/four reserved cores, JAX 0.11.2 and NumPy 2.5.3. Night 3 trained concurrently;
  these scores are not a timing benchmark. No unfinished or unresolved games in either arm.

## Scores

Score is 1 for a win, 0.5 for a tie, 0 for a loss. Intervals below are 95%; differences are book minus no book.
Rounded table values are backed by the aggregate's full precision.

| Opponent | No book score [95%] | Book score [95%] | Paired difference [95%] |
|---|---|---|---|
| Same checkpoint | 0.4985 [0.4725, 0.5245] | 0.4970 [0.4705, 0.5235] | -0.0015 [-0.0125, +0.0105] |
| BC | 0.7615 [0.7390, 0.7840] | 0.7505 [0.7275, 0.7720] | -0.0110 [-0.0220, -0.0010] |
| 3600 | 0.6910 [0.6665, 0.7150] | 0.6915 [0.6665, 0.7150] | +0.0005 [-0.0125, +0.0135] |
| 11000 | 0.7155 [0.6930, 0.7385] | 0.7055 [0.6815, 0.7295] | -0.0100 [-0.0200, +0.0005] |

## Coverage and fallbacks

Counts below are **per opponent**, with all 2,000 games as denominator. They are identical across the four
matchups because the preview inputs are shared. `answered` means a backoff level returned suggestions;
`applied` means a full supported choice was used. Applied is not an independently logged changed-action counter.

| Preview result | Games | Share |
|---|---:|---:|
| Answered at any level | 2,000 | 100.0% |
| Applied a full book choice | 258 | 12.9% |
| Fell back to the net | 1,742 | 87.1% |

| Answering backoff level | Answers | Share of games | Applied |
|---|---:|---:|---:|
| Exact own items/team vs foe six | 26 | 1.3% | 0 |
| Teams ignoring items | 14 | 0.7% | 0 |
| Lead pair vs opposing lead pair | 1,960 | 98.0% | 258 |
| Single-species frequencies | 0 | 0.0% | 0 |

| Fallback cause | Games affected | Share of games | Rejected suggestions |
|---|---:|---:|---:|
| Full choice below minimum count | 1,742 | 87.1% | 70,510 |
| Missing usable back pair | 1,688 | 84.4% | 14,420 |

Causes overlap and must not be summed. Missing backs includes backs unavailable after backoff to another team,
not only Pokemon never observed. Rejected-suggestion counts are separate from game counts. No other fallback
causes occurred. A level can answer while every full choice fails the count/back-pair requirements; no backs
were guessed, and the wrapper did not silently move to another evidence level after such an answer.

## Pool-group breakdown and limits

| Learner pool group | Teams in pool | Games per arm per opponent | Result |
|---|---:|---:|---|
| PP_/A/B/C | 79 | 2,000 | All score/CIs and usage counts above apply to this group |
| LL_ | 0 | 0 | Not evaluated; no score or interval claimed |

The aggregate includes the per-opponent PP_/A/B/C breakdown and an explicit LL_ not-evaluated entry. This
does not establish a result on LL_ teams, prior mixing, another checkpoint or a denser book.

Scores and seat-cluster intervals were recomputed from private results; paired rows matched between arms and
preview counts reconciled. Only the aggregate export enters this docs PR. The observed lack of gain and thin
full-choice coverage support the owner's deployment decision: retain optional code, leave it off, exclude it
from the bot. They do not prove every possible human-prior method ineffective.
