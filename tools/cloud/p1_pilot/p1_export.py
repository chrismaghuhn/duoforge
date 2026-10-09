"""Stage 3 P1 pilot run tooling (tools/cloud/p1_pilot, used by run.sh): the continuation control's final network as a
format-2 checkpoint.

A train run stopped by its ledger budget plays no final suite and so writes no snapshot of its last update; its final
parameters are in the run state (runstate.save_state, written at the stop). This writes them with the config a
snapshot of that update would carry (train.snapshot_config: model, encoder, ext_supported, ids, layout, data, teams,
update, decisions, train), every field read from the saved state, nothing recomputed. When the run did save a
snapshot of that very update, its parameters must equal the state's bit for bit.

usage: python p1_export.py RUN_DIR OUT.npz     (prints {"out", "update", "decisions", "sha256"}; exit 2 on refusal)
"""
import hashlib
import json
import os
import sys

import numpy as np


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: p1_export.py RUN_DIR OUT.npz", file=sys.stderr)
        return 2
    run_dir, out = argv
    from duoforge_learn import checkpoint, runstate
    try:
        if os.path.exists(out):
            raise ValueError(f"{out} exists: the export is written once")
        state = runstate.load_state(run_dir)
        update, decisions = state["counters"]["update"], state["counters"]["decisions"]
        config = {"model": state["model"], "encoder": state["encoder"], "ext_supported": state["ext_supported"],
                  "ids": state["ids"], "features": list(state["features"]),
                  "slot_features": list(state["slot_features"]), "data": state["data"], "teams": state["teams"],
                  "update": update, "decisions": decisions, "train": state["train"]}
        snapshot = os.path.join(run_dir, f"params-{update}.npz")
        if os.path.exists(snapshot):
            snap, _ = checkpoint.load(snapshot)
            a, b = checkpoint.flatten(snap), checkpoint.flatten(state["params"])
            if a.keys() != b.keys() or any(not np.array_equal(a[k], b[k]) for k in a):
                raise ValueError(f"{snapshot} differs from the run state of update {update}")
        checkpoint.save(out, state["params"], config)
        checkpoint.load_trained(out)  # readable as trained (the layout is its encoder's), as p1_eval loads it
    except (ValueError, OSError, KeyError) as err:
        print(f"p1_export: {err}", file=sys.stderr)
        return 2
    digest = hashlib.sha256()
    with open(out, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    print(json.dumps({"out": out, "update": update, "decisions": decisions, "sha256": digest.hexdigest()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
