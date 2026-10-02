# 0014 — Learner pipeline (self-play PPO over the factored domain)

Status: owner decision 2026-10-02 ("die Pipeline schon bauen, die kann man später benutzen, und wir machen einen Probelauf"). Follows decision 0013 (Python adapter) and the throughput report `docs/benchmarks/2026-10-02-python-loop/`.

## 1. Goal

A training pipeline that can be reused when more teams exist: self-play on the batch runtime, a policy network on the GPU, evaluation against the random and scripted baselines, checkpoints and a log. With the two reference teams (four pairings) a run is a pipeline test - the agent can only learn these matchups - not a general player. The first run is a short trial; a long run follows when the learning curve or more teams justify it.

## 2. Placement

- Package `python/duoforge_learn/` (JAX, optax, NumPy). The engine package `python/duoforge` stays NumPy-only (decision 0013).
- JAX runs on the GPU only under Linux, so training runs in WSL (owner's RTX 4060 Ti, 8 GB) with its own venv `~/df-learn` (`jax[cuda12]`, optax, NumPy) and a Release library with LTO built in WSL. The tests of the package run where JAX is installed (CMake `DUOFORGE_LEARN_PYTHON`); without it they report skipped.

## 3. Environment loop

Each batch step: `query_factored` (requests, observations, factored domains), `features.encode_batch` (NumPy, vectorized; equal to the per-player encoder), the policy on the GPU, `step_factored` with the chosen pair or team tuple, and for ended episodes the results (`Batch.result`) and `reset_terminal`. Both seats of every environment are played by the current policy (self-play with shared parameters); the reward of a seat is +1 for a win, -1 for a loss and 0 for a tie, at the episode's end. The engine has no turn limit, and two policies that only switch never end a battle, so an episode that reaches `--max-steps` steps (500) is cut off and scored as a tie - a training choice, not a battle rule. A fused factored step can follow if the loop, not the learner, turns out to be the limit.

## 4. Network

- Torso: an MLP over the observation part (607 floats since the encoder knows the Team C values; 594 before, so the checkpoints of 2026-10-02 need that encoder) to 256 units, twice.
- Slot heads: each of the up to 32 options of slot list s is scored from the torso and the option's 12 features (a shared hidden layer, one output per slot list). The joint logit of a pair (i, j) is the sum of the two slot logits; pairs outside the engine's pair mask get no probability. One categorical over the 1024 pairs.
- Team head: 360 logits, the ordered tuples of 4 of 6 roster indices in lexicographic order - the joint ranks of the TEAM_SELECTION domain under the certified profile (register 6, bring 4).
- Value head: one scalar from the torso, from the viewer's perspective.

## 5. Training

PPO with clipping 0.2, GAE (gamma 0.99, lambda 0.95) over each seat's own decisions (`duoforge_learn/returns.py`: a seat that is not requested at a step does not act; the episode's reward goes to its last decision; discounting counts the seat's own decisions; the value of the state after the rollout bootstraps), Adam 3e-4, 4 epochs of minibatches, entropy bonus 0.01, value coefficient 0.5, gradient clip 0.5. The policy loss covers the rows where a seat acted; the value loss covers every row - where a seat waits, its target is what its next decision returns, its reward if the episode ends first, or the bootstrap - so the value of a waiting state, which can bootstrap a rollout's end, is trained too. Seeds: `--seed` gives the battles (all 64 bits), the JAX key (its low 32 bits, the high 32 folded in) and a NumPy generator that shuffles the minibatches. GPU runs need not repeat bit for bit.

## 6. Evaluation and output

Every N updates the parameters are saved as `.npz` with the configuration, and the policy (most likely action) plays fixed-seed episodes against the scripted and the random baselines and against the parameters of the previous evaluation (`vs_previous`: above 0.5 while it still improves), on both seats and over the four pairings (the evaluation environments are a multiple of 8). An evaluation episode still running after 1000 steps counts as a tie and is logged as unfinished. The log records win rates, losses, entropy, episodes and decisions per second (JSON lines); a run writes only into an empty directory.

Encoder versions: the configuration of a checkpoint names the encoder version its network was trained with (`"encoder"`). `features.ENCODER` is 2 since a member's present flag means registered (`move_count != 0`). A configuration without the entry is version 1, whose present flag was `species_id != 0` and so marked Rillaboom (forme 0) as absent. The evaluation and the ladder give every network the inputs of its version (`checkpoint.encoder_of`, `features.as_encoder`), so an old checkpoint plays exactly on the inputs it was trained on. A version the encoder does not serve raises.

## 7. Trial run

A short run (the owner's trial) reports the learning curve, the win rates against both baselines and the throughput in `docs/learning/`. Success for the trial: the pipeline runs end to end, the losses are finite, and the win rate against the random baseline rises clearly.
