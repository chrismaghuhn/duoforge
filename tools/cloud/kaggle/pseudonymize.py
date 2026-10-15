#!/usr/bin/env python3
"""A copy of a replay dataset for Kaggle without its replay ids (HauptSession 2026-10-15, #458): every games.npz's
replay_id (a public battle id) becomes a meaningless label game-<part>-<index>, the part's manifest gets the new
games_sha256, and the map label -> replay_id is written to a file of its own that stays local (never uploaded: the
content list of kaggle_run.py plan takes the copy only). Nothing else of the dataset changes, so duoforge_learn.bc reads
the copy as it reads the original (bc_data reads replay_id for its messages only).

    python tools/cloud/kaggle/pseudonymize.py --dataset SRC --out DST --map MAP.json

DST must not exist; DST and MAP lie outside the repository and MAP outside DST. The copy is checked afterwards: no
replay id of the source is left in any of its files.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "python"))


def inside(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return path == root or path.startswith(root + os.sep)


def label(part, index):
    return f"game-{part.rsplit('-', 1)[-1]}-{index:06d}"


def pseudonymize(src, dst, map_path):
    from duoforge_replay.dataset import write_npz  # the dataset's own format: byte-identical for equal arrays
    for path, what in ((dst, "--out"), (map_path, "--map")):
        if inside(path, REPO):
            raise SystemExit(f"{what} is inside the repository: the copy and the map are private")
    if inside(map_path, dst):
        raise SystemExit("--map lies inside --out: the map must stay local, apart from the copy")
    if os.path.exists(dst):
        raise SystemExit("--out exists: give a new directory")
    if not os.path.isfile(os.path.join(src, "manifest.json")):
        raise SystemExit("--dataset holds no manifest.json: not a replay dataset")
    shutil.copytree(src, dst)
    mapping, seen = {}, set()
    for part in sorted(os.listdir(dst)):
        games = os.path.join(dst, part, "games.npz")
        if not os.path.isfile(games):
            continue
        with np.load(games, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files}
        ids = [str(x) for x in arrays["replay_id"]]
        labels = [label(part, i) for i in range(len(ids))]
        for lab, rid in zip(labels, ids):
            mapping[lab] = rid
            seen.add(rid)
        arrays["replay_id"] = np.array(labels, dtype=str) if labels else np.array([], dtype=arrays["replay_id"].dtype)
        os.remove(games)
        write_npz(games, arrays)
        manifest = os.path.join(dst, part, "manifest.json")
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)
        m["games_sha256"] = hashlib.sha256(open(games, "rb").read()).hexdigest()
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)
    left = []
    for d, _, names in os.walk(dst):  # no replay id of the source is left anywhere in the copy
        for n in names:
            data = open(os.path.join(d, n), "rb").read()
            if n.endswith(".npz"):
                with np.load(os.path.join(d, n), allow_pickle=False) as z:
                    data = b"".join(z[k].tobytes() for k in z.files if z[k].dtype.kind in "US")
                    text = " ".join(str(x) for k in z.files if z[k].dtype.kind in "US" for x in z[k].reshape(-1))
            else:
                text = data.decode("utf-8", "replace")
            if any(rid in text for rid in seen):
                left.append(os.path.relpath(os.path.join(d, n), dst))
    if left:
        shutil.rmtree(dst)
        raise SystemExit(f"a replay id is left in {len(left)} file(s) of the copy (e.g. {left[0]}): the copy was removed")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({"dataset": os.path.abspath(src), "copy": os.path.abspath(dst), "replay_ids": mapping}, f)
    return len(mapping)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pseudonymize.py", description=__doc__.split("\n")[0])
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--map", required=True)
    a = p.parse_args(argv)
    n = pseudonymize(a.dataset, a.out, a.map)
    print(f"{n} replay ids replaced; the map stays local, apart from the copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
