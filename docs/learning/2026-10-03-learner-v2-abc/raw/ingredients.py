"""Ingredients of double-buffering (collect step k+1 while update k learns):
the time of one act call over 512 rows (256 environments, both seats, Teams
A, B and C) on the GPU and on the CPU backend, per model. On one GPU stream
an act call queued behind the update's kernels waits for them, so overlap
needs the actor's inference on the CPU; this measures what that costs.
Prints one JSON line per model: median and range of 50 timed calls."""
import json
import statistics
import time

import jax
import numpy as np

import duoforge
from duoforge import _layout, features, teams
from duoforge_learn import policy

with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_TEAM_C"]) as ctx:
    pool = teams.load(ctx, ["A", "B", "C"])
    n = 256
    rng = np.random.default_rng(1)
    setups = pool.setups(rng.integers(0, 3, n), rng.integers(0, 3, n))
    with duoforge.Batch(ctx, setups, 8, 7) as b:
        b.query_factored()
        b.step_factored(duoforge.RandomPolicy(7, n).choose_factored(b))
        b.query_factored()
        obs, slots, mask = features.encode_batch(b.observations.reshape(-1), b.domains.reshape(-1))
is_team = np.zeros(obs.shape[0], dtype=bool)

for name, cfg in (("v1", dict(policy.V1_DEFAULT)), ("v2-S", policy.v2_config("S")), ("v2-M", policy.v2_config("M")),
                  ("v2-L", policy.v2_config("L"))):
    m = policy.make(cfg)
    out = {"model": name, "rows": int(obs.shape[0])}
    for device in ("gpu", "cpu"):
        dev = jax.devices(device)[0]
        params = jax.device_put(m.init(jax.random.PRNGKey(0)), dev)
        args = [jax.device_put(x, dev) for x in (obs, slots, mask, is_team)]
        key = jax.device_put(jax.random.PRNGKey(1), dev)
        times = []
        for k in range(55):
            t0 = time.perf_counter()
            actions, _, _ = m.act(params, key, *args)
            np.asarray(actions)
            if k >= 5:
                times.append(time.perf_counter() - t0)
        out[device] = {"median_ms": round(1000 * statistics.median(times), 2),
                       "min_ms": round(1000 * min(times), 2), "max_ms": round(1000 * max(times), 2)}
    print(json.dumps(out), flush=True)
