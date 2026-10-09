"""Stage 3 P1 pilot run tooling (tools/cloud/p1_pilot, used by run.sh): the continuation control's compute matching
(Learner v2 plan 2026-10-08-stage3-p1-learner, task 7).

The control's first updates are its calibration (charged to its own ledger, nothing wasted): a few updates with
every update on the CPU (--update-gpu-share 0), then a few with every update on the GPU (--update-gpu-share 1),
acting on the CPU throughout (--act-gpu-share 0, so the GPU only runs updates), each block in its own process. From
the run's log.jsonl (each update's cumulative "ledger" and its "update_device") this measures per update:
  c_cpu: CPU core-seconds of an update on the CPU (collection + update),
  c_gpu: CPU core-seconds of an update on the GPU, g_gpu: its GPU-seconds,
skipping the first update of every process (its JIT), and solves the update share q so that the REMAINING budget
(pilot totals minus what the control already spent, read from the control's ledger file, which also holds what
the records do not: the calibration's final suites and process start-up) is hit on both axes at the same update:
  R_g / R_c = q g_gpu / (q c_gpu + (1 - q) c_cpu).
It prints (and with --out writes) the resume flags: --update-gpu-share q --act-gpu-share 0 --stop-cpu-core-seconds
P_c --stop-gpu-seconds P_g (the ledger totals are cumulative, so the stops are the pilot's totals) --updates 0
--minutes M (a safety cap, twice the forecast wall time) and the learning-rate decay end D = 0.9 x the forecast
decisions of the whole run (--learning-rate-schedule 0:1,D:0.1).

usage: python p1_match.py --pilot-ledger PILOT.json --control-run RUN_DIR --control-ledger CONTROL.json [--out F]
exit: 0 OK, 3 INFEASIBLE (run.sh: STOP), 2 bad input.
"""
import argparse
import json
import math
import sys
from pathlib import Path

INFEASIBLE = 3


def per_update(records, device):
    """Mean (cpu, gpu, wall) ledger deltas of the updates on device, skipping the first update after every
    (re)start (its JIT)."""
    cpu, gpu, wall = [], [], []
    for prev, cur in zip(records, records[1:]):
        if cur.get("update_device") != device or cur.get("restart"):
            continue
        cpu.append(cur["ledger"]["cpu_core_seconds"] - prev["ledger"]["cpu_core_seconds"])
        gpu.append(cur["ledger"]["gpu_seconds"] - prev["ledger"]["gpu_seconds"])
        wall.append(cur["collect_s"] + cur["update_s"])
    if not cpu:
        return None
    return sum(cpu) / len(cpu), sum(gpu) / len(gpu), sum(wall) / len(wall), len(cpu)


def records_of(run_dir):
    records, restart = [], True
    for line in Path(run_dir, "log.jsonl").read_text().splitlines():
        r = json.loads(line)
        if "resume" in r or "init" in r:
            restart = True
            continue
        if "update" in r and "ledger" in r:
            r["restart"] = restart
            restart = False
            records.append(r)
    return records


def solve(pilot, spent, records):
    target_c, target_g = pilot["cpu_core_seconds"], pilot["gpu_seconds"]
    on_cpu, on_gpu = per_update(records, "cpu"), per_update(records, "default")
    if on_cpu is None or on_gpu is None:
        raise ValueError(f"calibrate first: warm updates on the CPU {on_cpu}, on the GPU {on_gpu}")
    c_cpu, _, w_cpu, n_cpu = on_cpu
    c_gpu, g_gpu, w_gpu, n_gpu = on_gpu
    spent = {k: spent[k] for k in ("cpu_core_seconds", "gpu_seconds")}
    rem_c, rem_g = target_c - spent["cpu_core_seconds"], target_g - spent["gpu_seconds"]
    out = {"pilot": {"cpu_core_seconds": target_c, "gpu_seconds": target_g}, "spent": spent,
           "per_update": {"cpu_on_cpu": c_cpu, "cpu_on_gpu": c_gpu, "gpu_on_gpu": g_gpu, "wall_on_cpu": w_cpu,
                          "wall_on_gpu": w_gpu, "warm_updates": [n_cpu, n_gpu]},
           "calibration_updates": records[-1]["update"]}
    if rem_c <= 0 or rem_g < 0:
        out["status"] = "INFEASIBLE: the calibration already spent the pilot's budget on an axis"
        return out, INFEASIBLE
    rho = rem_g / rem_c
    denominator = g_gpu - rho * (c_gpu - c_cpu)
    q = rho * c_cpu / denominator if denominator > 0 else float("inf")
    out["rho"] = rho
    if not 0.0 <= q <= 1.0:
        out["status"] = f"INFEASIBLE: q = {q} outside [0, 1] (acting on the GPU would be needed: re-plan)"
        out["q"] = None if math.isinf(q) else q
        return out, INFEASIBLE
    per_c = q * c_gpu + (1 - q) * c_cpu
    updates = rem_c / per_c
    decisions_per_update = records[-1]["decisions"] / records[-1]["update"]
    total_updates = records[-1]["update"] + updates
    decay_end = int(0.9 * total_updates * decisions_per_update)
    wall = updates * (q * w_gpu + (1 - q) * w_cpu)
    minutes = max(10.0, math.ceil(2 * wall / 60))
    flags = ["--update-gpu-share", f"{q:.6f}", "--act-gpu-share", "0", "--stop-cpu-core-seconds", f"{target_c:.3f}",
             "--stop-gpu-seconds", f"{target_g:.3f}", "--updates", "0", "--minutes", f"{minutes:.0f}",
             "--learning-rate-schedule", f"0:1,{decay_end}:0.1"]
    out |= {"q": q, "remaining_updates": updates, "forecast_total_updates": total_updates,
            "forecast_gpu_at_cpu_stop": spent["gpu_seconds"] + updates * q * g_gpu,
            "forecast_wall_seconds": wall, "safety_minutes": minutes,
            "learning_rate_schedule": f"0:1,{decay_end}:0.1", "resume_flags": flags, "status": "OK"}
    return out, 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="p1_match.py")
    p.add_argument("--pilot-ledger", required=True)
    p.add_argument("--control-run", required=True)
    p.add_argument("--control-ledger", required=True,
                   help="the control's ledger file: what it spent so far, including what no record shows")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    try:
        pilot = json.loads(Path(args.pilot_ledger).read_text())
        spent = json.loads(Path(args.control_ledger).read_text())
        records = records_of(args.control_run)
        if not records:
            raise ValueError("no update with a ledger in the control run yet")
        out, code = solve(pilot, spent, records)
    except (ValueError, OSError, KeyError) as err:
        print(f"p1_match: {err}", file=sys.stderr)
        return 2
    text = json.dumps(out, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
