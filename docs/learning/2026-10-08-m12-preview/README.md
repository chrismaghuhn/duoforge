# M12.x honest team-preview measurement — 2026-10-08

Turn-1 preview search improves E/X against raw 49333, but does not show a consistent panel benefit. Direct-value gains are inconclusive. Keep deployment preview raw pending the owner decision; the opt-in search remains available. The rollout costs roughly four times as much per preview.

## Protocol

Code: [#240](https://github.com/chrismaghuhn/duoforge/pull/240), measured source `89875927`. Candidate and raw opponent: frozen params-49333; panel: BC/3600/11000 from the same fixed run. Only preview is searched; actual battle turns use the unchanged raw player. Honest public reconstruction, leave-foe-source-out beliefs, 8x8 candidates, W=S=16, lambda=0.5, capacity 1024, four native workers. Direct value evaluates after entry; turn1 executes raw policies through turn 1 to the next turn boundary (limit 16 prompts). N/E/X use the existing solver.

Each arm has 2048 games against R or 1024 against each panel member, both seat orders, identical team pairs/seeds. Total 35840 games including four raw baselines. Scores are win=1/tie=0.5/loss=0; 95% percentile CIs use 2000 bootstrap resamples of paired-seat blocks, seed 2316556663399645728. These intervals are descriptive, without multiple-comparison correction.

## Scores and paired gains

| Opponent | Arm | Games | Score [95% CI] | Arm minus raw [95% CI] | Changed previews | Searched / fallback |
|---|---|---:|---|---|---:|---:|
| R | raw | 2048 | 0.5034 [0.4775, 0.5298] | — | — | — |
| R | N-value | 2048 | 0.5049 [0.4790, 0.5322] | 0.0015 [-0.0239, 0.0293] | 1530/2048 (74.7%) | 2048 / 0 |
| R | E-value | 2048 | 0.5205 [0.4951, 0.5459] | 0.0171 [-0.0098, 0.0449] | 1561/2048 (76.2%) | 2048 / 0 |
| R | X-value | 2048 | 0.5186 [0.4927, 0.5439] | 0.0151 [-0.0117, 0.0439] | 1534/2048 (74.9%) | 2048 / 0 |
| R | N-turn1 | 2048 | 0.5039 [0.4800, 0.5298] | 0.0005 [-0.0264, 0.0283] | 1548/2048 (75.6%) | 2048 / 0 |
| R | E-turn1 | 2048 | 0.5713 [0.5464, 0.5957] | 0.0679 [0.0410, 0.0947] | 1525/2048 (74.5%) | 2048 / 0 |
| R | X-turn1 | 2048 | 0.5479 [0.5229, 0.5728] | 0.0444 [0.0171, 0.0708] | 1541/2048 (75.2%) | 2048 / 0 |
| BC | raw | 1024 | 0.7393 [0.7061, 0.7715] | — | — | — |
| BC | N-value | 1024 | 0.7373 [0.7061, 0.7676] | -0.0020 [-0.0352, 0.0332] | 790/1024 (77.1%) | 1024 / 0 |
| BC | E-value | 1024 | 0.7607 [0.7295, 0.7900] | 0.0215 [-0.0117, 0.0557] | 788/1024 (77.0%) | 1024 / 0 |
| BC | X-value | 1024 | 0.7510 [0.7207, 0.7803] | 0.0117 [-0.0215, 0.0459] | 789/1024 (77.1%) | 1024 / 0 |
| BC | N-turn1 | 1024 | 0.7363 [0.7041, 0.7666] | -0.0029 [-0.0352, 0.0293] | 767/1024 (74.9%) | 1024 / 0 |
| BC | E-turn1 | 1024 | 0.7588 [0.7275, 0.7881] | 0.0195 [-0.0156, 0.0547] | 782/1024 (76.4%) | 1024 / 0 |
| BC | X-turn1 | 1024 | 0.7480 [0.7168, 0.7783] | 0.0088 [-0.0244, 0.0430] | 767/1024 (74.9%) | 1024 / 0 |
| 3600 | raw | 1024 | 0.6816 [0.6455, 0.7148] | — | — | — |
| 3600 | N-value | 1024 | 0.6631 [0.6308, 0.6953] | -0.0186 [-0.0537, 0.0176] | 790/1024 (77.1%) | 1024 / 0 |
| 3600 | E-value | 1024 | 0.6758 [0.6436, 0.7109] | -0.0059 [-0.0420, 0.0303] | 788/1024 (77.0%) | 1024 / 0 |
| 3600 | X-value | 1024 | 0.6719 [0.6377, 0.7031] | -0.0098 [-0.0449, 0.0264] | 789/1024 (77.1%) | 1024 / 0 |
| 3600 | N-turn1 | 1024 | 0.6709 [0.6377, 0.7061] | -0.0107 [-0.0430, 0.0244] | 767/1024 (74.9%) | 1024 / 0 |
| 3600 | E-turn1 | 1024 | 0.6865 [0.6523, 0.7188] | 0.0049 [-0.0293, 0.0391] | 782/1024 (76.4%) | 1024 / 0 |
| 3600 | X-turn1 | 1024 | 0.6777 [0.6455, 0.7109] | -0.0039 [-0.0371, 0.0303] | 767/1024 (74.9%) | 1024 / 0 |
| 11000 | raw | 1024 | 0.6982 [0.6650, 0.7295] | — | — | — |
| 11000 | N-value | 1024 | 0.6826 [0.6494, 0.7158] | -0.0156 [-0.0498, 0.0205] | 790/1024 (77.1%) | 1024 / 0 |
| 11000 | E-value | 1024 | 0.7021 [0.6689, 0.7334] | 0.0039 [-0.0312, 0.0391] | 788/1024 (77.0%) | 1024 / 0 |
| 11000 | X-value | 1024 | 0.6895 [0.6562, 0.7207] | -0.0088 [-0.0430, 0.0274] | 789/1024 (77.1%) | 1024 / 0 |
| 11000 | N-turn1 | 1024 | 0.6660 [0.6328, 0.6982] | -0.0322 [-0.0674, 0.0039] | 767/1024 (74.9%) | 1024 / 0 |
| 11000 | E-turn1 | 1024 | 0.6621 [0.6279, 0.6953] | -0.0361 [-0.0713, -0.0010] | 782/1024 (76.4%) | 1024 / 0 |
| 11000 | X-turn1 | 1024 | 0.6631 [0.6289, 0.6953] | -0.0352 [-0.0713, 0.0010] | 767/1024 (74.9%) | 1024 / 0 |

## Evaluator comparison and fallback audit

Value mode treats an unsupported cell as -1; turn1 refuses the whole decision and plays raw. Therefore the requested conditional comparison includes only games where **both** modes searched. In this run every preview searched, so this cohort equals the full paired suite. In general it is post-treatment and is not an unbiased whole-suite treatment effect.

| Opponent | Solver | Both-searched games | Turn1 minus value [95% CI] |
|---|---|---:|---|
| R | N | 2048 | -0.0010 [-0.0254, 0.0229] |
| R | E | 2048 | 0.0508 [0.0264, 0.0742] |
| R | X | 2048 | 0.0293 [0.0059, 0.0522] |
| BC | N | 1024 | -0.0010 [-0.0303, 0.0283] |
| BC | E | 1024 | -0.0020 [-0.0342, 0.0293] |
| BC | X | 1024 | -0.0029 [-0.0332, 0.0273] |
| 3600 | N | 1024 | 0.0078 [-0.0254, 0.0420] |
| 3600 | E | 1024 | 0.0107 [-0.0225, 0.0430] |
| 3600 | X | 1024 | 0.0059 [-0.0254, 0.0371] |
| 11000 | N | 1024 | -0.0166 [-0.0479, 0.0156] |
| 11000 | E | 1024 | -0.0400 [-0.0684, -0.0098] |
| 11000 | X | 1024 | -0.0264 [-0.0557, 0.0039] |

All 30720 searched-arm previews were searched; zero decision fallbacks of any cause, zero changed-fallback previews, zero unfinished/unresolved games. Changed choices above are all searched choices. This does not imply zero unsupported table cells: value-mode cell penalties are distinct from decision fallbacks.

## Pool and cost limits

Pool: 79 teams. Game counts by group: {'R': {'PP_/A/B/C': 2048, 'LL_': 0}, 'BC': {'PP_/A/B/C': 1024, 'LL_': 0}, '3600': {'PP_/A/B/C': 1024, 'LL_': 0}, '11000': {'PP_/A/B/C': 1024, 'LL_': 0}}. No LL_ games; these scores apply only to the represented PP_/A/B/C group. No claim for LL_.

| Opponent | Solver | Value median / p95 ms | Turn1 median / p95 ms |
|---|---|---:|---:|
| R | N | 23.6 / 31.4 | 92.1 / 105.0 |
| R | E | 23.2 / 31.0 | 92.6 / 115.4 |
| R | X | 23.7 / 30.4 | 93.4 / 113.8 |
| BC | N | 24.7 / 30.3 | 92.0 / 100.6 |
| BC | E | 24.6 / 29.4 | 93.4 / 103.0 |
| BC | X | 24.6 / 29.8 | 92.9 / 105.2 |
| 3600 | N | 23.6 / 28.9 | 92.4 / 101.0 |
| 3600 | E | 24.5 / 28.9 | 92.8 / 102.8 |
| 3600 | X | 24.3 / 29.0 | 92.6 / 105.3 |
| 11000 | N | 24.4 / 29.1 | 90.5 / 101.5 |
| 11000 | E | 24.3 / 28.0 | 92.7 / 105.1 |
| 11000 | X | 24.4 / 29.4 | 91.7 / 103.9 |

GPU JAX 0.11.2 with deterministic operations; native library 0.43.0. Elapsed job time was approximately 38 minutes including warm-up/compilation and raw battle play. Per-preview timings are diagnostics of this machine/run, not a general throughput promise.

## Provenance and validation

Checkpoint SHA-256 (no checkpoint files or private paths):

- R: `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb`
- BC: `bbd9656c5efed224e53667af1c26111594f7c3d956ea112424684099c6562b94`
- 3600: `db0987eaf7c11ede1a35d43158ddaa2748224f00a200882efcdb0fc9f2300b56`
- 11000: `ef0521b5b933cd0e74ed0381e7d2b3bed32f51c881ef652b8c4c18131477a8b9`

Arena seed: 2316556663399645730; search seed: 2316556663399645729. Source archives lack Git metadata, so commit provenance is the explicitly pinned launcher snapshot, not summary auto-detection. The earlier superseded partial run is excluded.

The frozen CLI accidentally reported baseline scores and baseline-minus-arm gains for searched arms. This report recomputes candidate scores/CIs/gains from saved private game records, verifies pairings/results/budgets, and verifies the sign reversal against the original summary. The reporting bug is fixed with a regression test in #240; no battle rerun was needed. Conditional cohorts are computed with the reviewed implementation and preserve partial-seat cluster weights. No game rows, worlds, tables, checkpoints or run paths are published.

## Decision

Recommend no deployment promotion from this measurement alone; the owner decides. The rollout is roughly four times as costly per preview. Against raw 49333 E gains +0.0679 [0.0410, 0.0947] and X +0.0444 [0.0171, 0.0708], but against 11000 the respective gains are -0.0361 [-0.0713, -0.0010] and -0.0352 [-0.0713, 0.0010]. Panel endpoints do not establish a consistent benefit. Direct value gains are inconclusive. This measurement does not test stage-3 distillation, and authorizes neither training nor another search experiment. Owner adoption decision remains separate.
