# M12.x: honest team-preview search

The default `Honest` preview remains raw. Opt in with `preview_mode="value"` or `"turn1"`;
`preview_only=True` keeps all subsequent real battle decisions raw. The opening book is not used.

The own candidates are the network's top eight ordered bring-four tuples; the foe candidates are its top eight
by mean probability in sampled public-information worlds. Both sides use the existing 360-tuple domain helpers.
Own inputs come only from the public root; foe policy rows and all leaf states come from C-built worlds.
Preview hypotheses have no preselected hidden bench. Every table cell explicitly plays both candidate tuples.
Worlds and gameplay seeds are shared across cells; N/E/X use the existing Bayesian solver (`lambda=0.5`).
No rule, entry effect or move outcome is implemented in Python.

Two evaluators are measured on the same pairings/seeds:

- `value`: value head after the core applies both previews and all initial entry effects. The core is already
  at the first turn-1 decision here; a supposed rollout merely "to turn 1" would be identical.
- `turn1`: raw greedy policies play through turn 1, including intermediate pivots/replacements, stopping at
  the next TURN boundary or TERMINAL. The default bound is 16 prompts. Hitting it returns the original preview
  choice with explicit `preview_rollout_limit`; it never masquerades as a completed rollout. Unsupported entry
  reconstruction is counted explicitly. Other engine/encoding failures stop the run. Leaf refusals and terminal
  scores follow the existing search protocol. At an evaluation cutoff, use the core's tiebreak instead of extending
  beyond the game's last step.

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
Bootstrap resamples keep both seat orders together. Raw games, decisions/tables and conditions stay outside all
repo worktrees, guarded by `refuse_repository`; only a later authorized aggregate-only report may be published.
Completed opponent arms are retained privately if a later arm fails. No performance/strength gain is presumed.
