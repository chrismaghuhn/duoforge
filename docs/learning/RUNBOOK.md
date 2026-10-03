# Learner runbook: a training run on a rented Linux machine

This covers decision 0017 (Learner v2). The first runs go local and at night (WSL, 8 workers); rent a machine only for long or parallel runs. Base the hardware choice on the phase timings of the A/B/C measurements (`docs/learning/<date>-learner-v2-abc/`), not on the core count: a training update spends its time in the encoder, the policy calls and the PPO update, not in the engine.

## 1. Machine

- Linux with an NVIDIA GPU and CUDA 12; a persistent volume for the run directory (on RunPod `/workspace`, which survives a stop).
- Python 3.12, CMake 3.28 or newer, Ninja, GCC 13 or newer, git.

## 2. Build and environment

```bash
git clone https://github.com/chrismaghuhn/duoforge.git && cd duoforge
cmake -S . -B build/release -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_ENABLE_IPO=ON -DBUILD_TESTING=OFF
cmake --build build/release --target duoforge_shared
python3.12 -m venv ~/df-learn
~/df-learn/bin/pip install "jax[cuda12]==0.11.2" optax==0.2.8 numpy==2.5.3
export DUOFORGE_LIBRARY=$PWD/build/release/libduoforge_shared.so PYTHONPATH=$PWD/python
```

These are the versions of the local runs (`~/df-learn` in WSL, 2026-10-02).

## 3. Smoke test

```bash
~/df-learn/bin/python -c "import jax; print(jax.devices())"
JAX_PLATFORMS=cpu ~/df-learn/bin/python -m unittest python.tests.test_learn_v2.TrainingV2Test
~/df-learn/bin/python -m duoforge_learn.train --envs 64 --workers 4 --updates 5 --minutes 0 --out /workspace/runs/smoke
```

The first command must list the GPU. The last one writes `log.jsonl`, `params-*.npz` and `state.npz` into a fresh directory.

## 4. Start a run

Start it inside `tmux`, so a dropped SSH session does not stop it. The run directory goes on the persistent volume.

```bash
tmux new -s train
~/df-learn/bin/python -m duoforge_learn.train --model v2 --preset M --envs 1024 --workers 30 \
    --teams A,B,C --data-kind team_c --minutes 600 --out /workspace/runs/<name> \
    2>&1 | tee -a /workspace/runs/<name>.out
```

- `--teams` and `--data-kind`:
  - `--teams` takes registry ids from `data/teams/index.json`.
  - `--data-kind` names the kind those teams need: `team_c` for A, B and C, later the frozen pool profile.
  - The library checks every team at the start. A refused team stops the run and names its status.
- `--workers`: the vCPUs minus two (the Python thread and the system).
- The run state is saved every `--save-minutes` (10), at the end, and after SIGTERM or SIGINT: the run then ends at the next update boundary with `"stopped": "signal"` in its last log line.

## 5. Sync

Copy the run directory home while it runs. `state.npz` is replaced atomically, so a copy taken at any moment holds a complete state.

```bash
rsync -av --partial <user>@<host>:/workspace/runs/<name>/ runs/<name>/
```

## 6. Resume after an interruption

```bash
~/df-learn/bin/python -m duoforge_learn.train --resume /workspace/runs/<name> --minutes 600
```

- Running episodes are dropped and every environment starts its next episode, so no battle seed repeats.
- A resume may change the environment and worker counts, the duration, the league, schedule, evaluation and save options, and the teams. It refuses another model, seed, learning rate, epochs, minibatch, rollout or step limit, a changed team file and another data kind. The log records every change in a `resume` line.

## 7. Afterwards

```bash
~/df-learn/bin/python -m duoforge_learn.ladder runs/<name> --pick 8 --workers 8 --out runs/<name>/ladder
```

The ladder writes `ladder.json` and `ladder.md`: Elo overall and per team with 95 % intervals, plus the team-against-team matrix of the strongest checkpoint.
