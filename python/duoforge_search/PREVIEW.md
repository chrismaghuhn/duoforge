# M12.x: honest team-preview search

The default `Honest` preview remains raw. Opt in with `preview_mode="value"` or `"turn1"`;
`preview_only=True` keeps all subsequent real battle decisions raw. The opening book is not used.

The own candidates are the network's top eight ordered bring-four tuples; the foe candidates are its top eight
by mean probability in sampled public-information worlds. Both sides use the existing 360-tuple domain helpers.
Own inputs come only from the public root; foe policy rows and all leaf states come from C-built worlds.
Preview hypotheses have no preselected hidden bench. Every table cell explicitly plays both candidate tuples.
Worlds and gameplay seeds are shared across cells; N/E/X use the existing Bayesian solver (`lambda=0.5`).
No rule, entry effect or move outcome is implemented in Python.
`preview_rule` (step 1 of the search ladder, #440) names the rule that plays the preview's table ("nash", "ev" or
"mix"); None plays the search's own `rule`. The record's `rule` field names the rule actually played. A foe network
(`foe_net`) is accepted with `preview_mode="value"` and `"turn1"`: the foe candidates come from it, the own
candidates and the leaf values from the main network.
This is the Champions open-team-list regime: stat alignment (the stat-changing Nature effect) is public,
while the actual stats remain hidden. The official [2026 VGC handbook](https://mcdn.pokemon.com/pokemon-prod/raw/upload/v1/live/static-assets/content-assets/cms2/pdf/play-pokemon/rules/play-pokemon-vgc-tournament-handbook-en.pdf)
section 2.5 lists stat alignment and excludes only stats from disclosure; [Pokemon.com's NAIC discussion](https://www.pokemon.com/uk/features/2026-north-america-international-championships-pokemon-vgc-roundtable)
confirms this change. This does not authorize assuming Nature known in closed-sheet formats.

`preview_width` (#440) sets the candidates. It is an option, and live play keeps the default:
- `"top"` (the default): the top tuples as above.
- `"distinct"` (arm 1bw): one tuple per bring-and-lead combination, its likeliest ordering, with the combination's
  probability summed over its orderings (`preview.distinct`). The own side adds, for each member none of the K
  likeliest combinations brings, the likeliest combination that brings it, so it has at most K + 2 candidates
  (`COVER_MAX`). The foe side has the M likeliest, without that cover. A combination merges the bench order **and
  the two lead seats**. The seats are separate positions in battle and in the network's input, so this merge is an
  approximation, not evaluator equality (the review of #462).
- `"seats"` (arm 1bws): as `"distinct"`, but the lead seats are kept and only the bench order merges
  (180 combinations).

The record names a width other than `"top"` (`preview_width`). The preview's Bayesian LP is held to the size limit
of `matrix.MAX_BAYES_CELLS`, where the exact rescue is known to finish. `Honest` checks K + 2 rows for a widened
preview when it is built, and each preview table is checked again before its rollouts. Above the limit the search
stops with a named error, never a silent fallback.

Two evaluators are measured on the same pairings/seeds:

- `value`: value head after the core applies both previews and all initial entry effects. The core is already
  at the first turn-1 decision here; a supposed rollout merely "to turn 1" would be identical.
- `turn1`: raw greedy policies play through turn 1, including intermediate pivots/replacements, stopping at
  the next TURN boundary or TERMINAL. The default bound is 16 prompts. Hitting it returns the original preview
  choice with explicit `preview_rollout_limit`; it never masquerades as a completed rollout. Unsupported entry
  reconstruction is counted explicitly. Other engine/encoding failures stop the run. Leaf refusals and terminal
  scores follow the existing search protocol. At an evaluation cutoff, use the core's tiebreak instead of extending
  beyond the game's last step.

With a foe network (`foe_net`, step 1b of the ladder, #440) the turn-1 rollout plays the foe seat with it: the foe
seat's rows come from the foe encoding and its policy from the foe network, while the player's seat keeps the main
network and encoder and the value rows stay the player's main-encoder rows. The foe's pair is chosen from the foe
encoding's legal mask; where the main encoding gives an asked foe seat another mask, the decision raises
`SearchError` rather than picking from either one. Without a foe network the rollout is unchanged.

Candidate ties use the lower tuple rank. Decisions are deterministic with the same seeds, device/runtime,
capacity and shapes. Leaves/value calls use the fixed existing capacity and padding. Buffers are native batch
buffers allocated at search construction; Python plans/records are preview-search metadata, not C hot-path changes.
Cross-capacity/device float-bit equality is not claimed. Stage-3 lockstep batching is separate work.

## Paired measurement

```sh
PYTHONPATH=python python -m duoforge_search.preview_ab --run-dir PRIVATE_RUN --checkpoint params-49333 \
    --panel-run-dir PRIVATE_STAGE1_RUN --out PRIVATE_EMPTY_OUTPUT --workers 4 --capacity 1024
```

Defaults match #236's budgets: N/E/X, 8x8, 16 worlds, 2,048 games per configuration vs the unchanged checkpoint,
1,024 per configuration vs BC/3600/11000, both evaluator modes. That is 35,840 games including four raw baselines.
Panel paths must be explicit or resolved under the named panel run. No search is added to opponents or real turns.
`--worlds`, `--capacity`, `--rollout-steps`, game budgets, step cutoff and bootstrap resamples are recorded.

The reports give score/95% CI, paired gain vs raw and paired `turn1-minus-value` difference, actual changed-preview
count/share against captured baseline ranks, fallback causes and timing. Capture baseline ranks from its actual
network calls instead of assuming another model batch shape has the same floating argmax.
Changed previews are split into searched and fallback cases. In addition to the full-suite comparison,
`both_searched` reports rollout-minus-value only on games where both modes searched. Its weighted seat-cluster
bootstrap keeps even one included seat of a pair. This post-treatment cohort is descriptive, not an unbiased
whole-suite effect; the two modes' different unsupported-cell/fallback policies remain explicitly reported.
Bootstrap resamples keep both seat orders together. Raw games, decisions/tables and conditions stay outside all
repo worktrees, guarded by `refuse_repository`; only a later authorized aggregate-only report may be published.
Completed opponent arms are retained privately if a later arm fails. No performance/strength gain is presumed.
