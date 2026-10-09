"""Do value bits at a fixed call shape depend on a row's position, its neighbours or the padding? (stage 3 P2
plan, Task 1.)

Lookahead's docstring claims a row's value does not depend on its position in the value call, and P2's
batching (deduplicated and packed rows of many decisions) is byte-preserving only if that holds for any
position, any neighbours and any padding at the pinned capacity. Bits are compared exactly (float32 as
uint32); there is no tolerance. The result holds only under its reported conditions: CPU bits depend on the
instruction set and XLA flags, GPU bits on the device and its flags.

CLI (private, an owner window): python -m duoforge_search.rowprobe --checkpoint PATH --device cpu|gpu --out PATH
"""
import argparse
import hashlib
import json
import os
import platform
import sys

import numpy as np

NEIGHBOUR_DRAWS = 3


def conditions(capacity, device):
    import jax
    cpu = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return {"jax": jax.__version__, "cpu": cpu, "xla_flags": os.environ.get("XLA_FLAGS", ""), "device": device,
            "capacity": int(capacity)}


def encoded_rows(n, seed, encoder=4, envs=64, workers=4):
    """n distinct encoded rows (float32, both seats) of reference setups under seeded random play."""
    import duoforge
    from duoforge import _layout
    out, seen = [], set()
    with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
            duoforge.Batch(ctx, np.resize(duoforge.reference_setups([0, 1, 2, 3]), envs), workers, seed) as batch:
        mask = int(batch.observe_ext()[0, 0]["supported"])
        policy = duoforge.RandomPolicy(seed, envs)
        for _ in range(10_000):
            batch.query_factored()
            obs, _, _ = batch.query_encoded(encoder, mask)
            for row in obs.reshape(-1, obs.shape[-1]):
                key = row.tobytes()
                if key not in seen and row.any():
                    seen.add(key)
                    out.append(row.astype(np.float32))
                    if len(out) == n:
                        return np.stack(out)
            batch.step_factored(policy.choose_factored(batch))
            batch.reset_terminal()
    raise RuntimeError(f"random play gave only {len(out)} distinct rows")


def _bits(model, params, call):
    return np.asarray(model.value(params, call), dtype=np.float32).reshape(-1).view(np.uint32)


def row_independence(model, params, rows, capacity, seed, device="cpu"):
    """Counts of rows whose value bits ever differ when the row moves to every position of a call (cyclic
    shifts), when the other rows of the call change (NEIGHBOUR_DRAWS seeded draws of the remaining rows), or
    when the tail of a partial call is zero padding instead of real rows. rows: (N >= capacity, width)."""
    rows = np.ascontiguousarray(rows, dtype=np.float32)
    if rows.ndim != 2 or rows.shape[0] < capacity:
        raise ValueError(f"row_independence needs at least {capacity} rows")
    base = rows[:capacity]
    reference = _bits(model, params, base)
    position = np.zeros(capacity, bool)
    for shift in range(1, capacity):
        position |= np.roll(_bits(model, params, np.roll(base, shift, axis=0)), -shift) != reference
    rng = np.random.default_rng(seed)
    keep = capacity // 4
    others = rows[keep:]
    neighbour = np.zeros(keep, bool)
    for _ in range(NEIGHBOUR_DRAWS):
        call = base.copy()
        call[keep:] = others[rng.integers(0, len(others), size=capacity - keep)]
        neighbour |= _bits(model, params, call)[:keep] != reference[:keep]
    used = capacity * 7 // 10
    padded = np.zeros_like(base)
    padded[:used] = base[:used]
    padding = _bits(model, params, padded)[:used] != reference[:used]
    return {"position_bits": int(position.sum()), "neighbour_bits": int(neighbour.sum()),
            "padding_bits": int(padding.sum()), "rows": int(capacity),
            "conditions": conditions(capacity, device)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m duoforge_search.rowprobe")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--device", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--capacity", type=int, default=1024)
    args = parser.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    os.environ["JAX_PLATFORMS"] = "cpu" if args.device == "cpu" else "cuda"
    from duoforge_learn import checkpoint, policy
    params, config = checkpoint.load_current(args.checkpoint)
    model = policy.make(checkpoint.model_config(config, params))
    rows = encoded_rows(args.capacity + args.capacity // 2, seed=7, encoder=checkpoint.encoder_of(config))
    result = row_independence(model, params, rows, args.capacity, seed=7, device=args.device)
    with open(args.checkpoint, "rb") as f:
        result["checkpoint_sha256"] = hashlib.sha256(f.read()).hexdigest()
    with open(args.out, "x", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    print(json.dumps(result, sort_keys=True))
    return 0 if not (result["position_bits"] or result["neighbour_bits"] or result["padding_bits"]) else 1


if __name__ == "__main__":
    sys.exit(main())
