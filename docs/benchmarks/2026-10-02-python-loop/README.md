# Python loop against the native mode (M7, 2026-10-02)

How fast the Python package (decision 0013) drives the batch runtime, compared with the native mode of decision 0012, in games per second and decisions per second.

## Setup

- AMD Ryzen 7 5800X (8 cores, 16 threads), Windows 11.
- Library 0.13.0 as `duoforge_shared`, GCC 16.2.0 (WinLibs UCRT), Release with link-time optimization: `cmake -S . -B build/py-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DDUOFORGE_ENABLE_IPO=ON -DBUILD_TESTING=OFF`.
- CPython 3.12.14, NumPy 2.5.3 (the project venv).
- The four reference pairings (environment e plays pairing e % 4), CLOSURE context, the uniform random policy unless stated.
- Quiet machine (decision 0008): no build, no game and no other test running; WSL idle. The modes of one configuration run interleaved, 5 times; each run plays at least 1024 battles, the native mode 8192. The tables give the median and, in brackets, the best run.

Command (`python -m duoforge.examples.throughput`):

```text
python -m duoforge.examples.throughput --envs 256 --episodes 4 --workers 16 --repeats 5
python -m duoforge.examples.throughput --envs 64 --episodes 16 --workers 16 --repeats 5
```

## Modes

| Mode | What runs per batch step |
|---|---|
| native | nothing in Python: `play_random` plays every episode in C (requests and candidates only) |
| autoreset | `query` (requests, observations, candidates), `RandomPolicy.choose`, `step`, `reset_terminal`: each environment starts its next episode at once (the usual RL loop) |
| index | as autoreset, but in rounds: every environment plays episode k, and the round ends with the longest battle, so finished environments wait |
| factored | as index, with `query_factored`, `choose_factored`, `step_factored` |
| scripted | as index, with `ScriptedPolicy` |

## Results: games/s (decisions/s)

| Environments, workers | native | autoreset | index |
|---|---|---|---|
| 64, 1 | 10,635 (342k) | 6,151 (201k) | 4,621 (149k) |
| 64, 4 | 37,900 (1.22M) | 9,804 (321k) | 6,290 (203k) |
| 64, 16 | 81,919 (2.64M) | 8,642 (283k) | 5,719 (184k) |
| 256, 1 | 10,222 (331k) | 6,778 (235k) | 4,667 (149k) |
| 256, 4 | 37,433 (1.21M) | 16,205 (562k) | 10,981 (351k) |
| 256, 16 | 92,472 (2.99M) | **19,282 (669k)** | 11,696 (374k) |

Best runs of the main configuration (256 environments, 16 workers): native 94,509, autoreset 20,313, index 11,823 games/s.

The rounds of the other modes (first series, same setup):

| Environments, workers | index | factored | scripted |
|---|---|---|---|
| 64, 1 | 4,570 | 2,351 | 1,425 |
| 64, 16 | 5,509 | 2,423 | 1,397 |
| 256, 4 | 10,823 | 3,598 | 1,640 |
| 256, 16 | 10,589 | 3,386 | 1,542 |

## Reading

- **The engine is not the limit.** With one worker the Python loop reaches about two thirds of the native mode. From 4 workers on, Python's share of each step sets the pace: 256 environments on 16 workers give 19,300 games/s and 670,000 decisions/s, against 92,000 native.
- **Big batches pay.** A batch step costs Python about the same for 64 as for 256 environments, so 256 environments more than double the throughput on 4 and 16 workers. 1024 environments were not measured.
- **Episodes should restart at once.** Rounds (`index`) lose a third against `autoreset`, because finished environments wait for the longest battle.
- **The step also returns more than the native mode needs.** The Python loop queries every player's observation (736 bytes) and candidates each step; `play_random` reads neither observations nor copies candidates.
- **Policies in NumPy are the next cost.** The factored choice (bit unpacking and a running count over 1024 pairs per player) and the scripted scoring (`(E, 2, candidates, 2)` temporaries) take most of their modes' time. In the JAX design of decision 0013 the policy runs on the GPU, so these are reference policies, not the training path.
