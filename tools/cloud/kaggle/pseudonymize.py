#!/usr/bin/env python3
"""A copy of a replay dataset for Kaggle without its replay ids and without its player hashes (HauptSession 2026-10-15,
#458). Every games.npz's
- replay_id (a public battle id) becomes a meaningless label game-<part>-<index>;
- players (game._hash8 of a player's name: an unkeyed sha256, so whoever knows a name can compute it) become random
  64-bit ids, one per player, each with a residue mod 400 drawn at random from its hash's class: T0 (h % 400 == 0),
  T (h % 20 == 0, not T0) or R (h % 20 != 0). duoforge_learn.bc reads a player hash only through that class
  (duoforge_replay.split: h % 20; bc_data's test-players split: (h // 20) % 20), so every row keeps its split and
  sub-bucket, and the copy gives away the class only, not the residue;
and the part's manifest gets the new games_sha256. A player's id is derived from a secret seed (HMAC-SHA256 of the
seed and the hash), so a rebuild with the same seed gives the same ids. The seed file, the map of the replay ids
(label -> replay_id) and the map of the players (hash -> id) are files of their own that stay local, apart from the copy
(never uploaded: the content list of kaggle_run.py plan takes the copy only; whoever knows the seed can recompute the
map). Nothing else of the dataset changes. The main protection is that every Kaggle dataset is private; these
pseudonyms are the second.

    python tools/cloud/kaggle/pseudonymize.py --dataset SRC --out DST --map REPLAY_IDS.json --player-map PLAYER_IDS.json
        --seed-file SEED

DST must not exist; DST, the maps and the seed lie outside the repository, and the maps and the seed outside DST and
outside SRC. SRC must be a dataset built in parts (replay-dataset.json), every part with its games.npz, no npz outside
the parts and no two parts with the same suffix; anything else is refused. A missing seed file is made (32 random
bytes, hex); an existing one is used as it is. The copy is checked afterwards: no replay id and no player hash of the
source is left in any of its files, every row's player class is its source's, and one player has one id throughout.
Any failure after the copy is made removes it.
"""
import argparse
import hashlib
import json
import os
import hmac
import re
import secrets
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "python"))


def inside(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return path == root or path.startswith(root + os.sep)


ID_SPAN = (1 << 64) // 400  # q * 400 + residue stays below 2 ** 64 for q < ID_SPAN
CLASSES = {"T0": [0], "T": list(range(20, 400, 20)), "R": [r for r in range(400) if r % 20]}


def player_class(h):
    """The class of a player hash that duoforge_learn.bc reads: T0 (h % 400 == 0), T (h % 20 == 0) or R."""
    h = int(h)
    return "T0" if h % 400 == 0 else "T" if h % 20 == 0 else "R"


def player_ids(hashes, seed):
    """{hash: id}: for each hash a 64-bit id from HMAC-SHA256(seed, hash), with a residue mod 400 of the hash's class
    and the rest of its bits drawn by the HMAC; all distinct and none equal to a hash (a clash takes the next attempt).
    The same seed gives the same ids."""
    taken, out = set(int(h) for h in hashes), {}
    for h in sorted(set(int(h) for h in hashes)):
        residues, attempt = CLASSES[player_class(h)], 0
        while True:
            v = int.from_bytes(hmac.new(seed, f"{h}:{attempt}".encode(), "sha256").digest()[:16], "little")
            pid = (v % ID_SPAN) * 400 + residues[(v // ID_SPAN) % len(residues)]
            if pid not in taken:
                break
            attempt += 1
        taken.add(pid)
        out[h] = pid
    return out


def read_seed(path):
    """The seed's bytes from its file (hex), made with 32 random bytes when the file does not exist."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32) + "\n")
    text = open(path, encoding="utf-8").read().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise SystemExit("the seed file does not hold 64 hex digits (not shown)")
    return bytes.fromhex(text)


def label(part, index):
    return f"game-{part.rsplit('-', 1)[-1]}-{index:06d}"


def pseudonymize(src, dst, map_path, player_map_path, seed_path):
    from duoforge_replay.dataset import MARKER, write_npz  # the dataset's own format: byte-identical for equal arrays
    for path, what in ((dst, "--out"), (map_path, "--map"), (player_map_path, "--player-map"), (seed_path, "--seed-file")):
        if inside(path, REPO):
            raise SystemExit(f"{what} is inside the repository: the copy, the maps and the seed are private")
    for path, what in ((map_path, "--map"), (player_map_path, "--player-map"), (seed_path, "--seed-file")):
        if inside(path, dst):
            raise SystemExit(f"{what} lies inside --out: it must stay local, apart from the copy")
        if inside(path, src):
            raise SystemExit(f"{what} lies inside --dataset: it would be copied into the copy")
    if os.path.exists(dst):
        raise SystemExit("--out exists: give a new directory")
    if not os.path.isfile(os.path.join(src, "manifest.json")):
        raise SystemExit("--dataset holds no manifest.json: not a replay dataset")
    if not os.path.isfile(os.path.join(src, MARKER)):  # dataset.parts() would read the directory itself
        raise SystemExit(f"--dataset holds no {MARKER}: only a dataset built in parts is supported")
    parts = sorted(n for n in os.listdir(src) if os.path.isdir(os.path.join(src, n)))
    stray = [os.path.relpath(os.path.join(d, n), src) for d, _, names in os.walk(src) for n in names
             if n.endswith(".npz") and os.path.dirname(os.path.relpath(os.path.join(d, n), src)) not in parts]
    if stray or not parts or any(not n.startswith("part-") or n.endswith(".tmp") for n in parts):
        raise SystemExit("--dataset holds an npz outside its parts, no part, or a directory that is no finished "
                         "part: not supported")
    missing = [n for n in parts if not os.path.isfile(os.path.join(src, n, "games.npz"))]
    if missing:
        raise SystemExit(f"{len(missing)} part(s) of --dataset hold no games.npz (e.g. {missing[0]}): not supported")
    if len({label(n, 0) for n in parts}) != len(parts):
        raise SystemExit("two parts of --dataset end in the same suffix: their labels would collide")
    seed = read_seed(seed_path)
    shutil.copytree(src, dst)
    try:
        return rewrite(src, dst, parts, map_path, player_map_path, seed, write_npz)
    except BaseException:  # a failure leaves no raw or half-made copy behind
        shutil.rmtree(dst, ignore_errors=True)
        raise


def rewrite(src, dst, parts, map_path, player_map_path, seed, write_npz):
    mapping, seen = {}, set()
    originals = set()
    for part in parts:  # every player hash of the dataset, for one id per player throughout
        with np.load(os.path.join(dst, part, "games.npz"), allow_pickle=False) as z:
            originals.update(int(h) for h in z["players"].reshape(-1))
    if not originals:
        raise SystemExit("--dataset holds no game: nothing to pseudonymize")
    ids_of = player_ids(originals, seed)
    for part in parts:
        games = os.path.join(dst, part, "games.npz")
        with np.load(games, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files}
        ids = [str(x) for x in arrays["replay_id"]]
        labels = [label(part, i) for i in range(len(ids))]
        for lab, rid in zip(labels, ids):
            mapping[lab] = rid
            seen.add(rid)
        arrays["replay_id"] = np.array(labels, dtype=str) if labels else np.array([], dtype=arrays["replay_id"].dtype)
        players = arrays["players"]
        arrays["players"] = np.array([ids_of[int(h)] for h in players.reshape(-1)],
                                     dtype=players.dtype).reshape(players.shape)
        os.remove(games)
        write_npz(games, arrays)
        manifest = os.path.join(dst, part, "manifest.json")
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)
        m["games_sha256"] = hashlib.sha256(open(games, "rb").read()).hexdigest()
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)
    left = []
    for d, _, names in os.walk(dst):  # no replay id and no player hash of the source is left anywhere in the copy
        for n in names:
            path = os.path.join(d, n)
            if n.endswith(".npz"):
                with np.load(path, allow_pickle=False) as z:
                    text = " ".join(str(x) for k in z.files if z[k].dtype.kind in "US" for x in z[k].reshape(-1))
                    numbers = {int(x) for k in z.files if z[k].dtype.kind in "iu" for x in z[k].reshape(-1)}
            else:
                text = open(path, "rb").read().decode("utf-8", "replace")
                numbers = {int(x) for x in re.findall(r"\d{6,}", text)}
            if any(rid in text for rid in seen) or numbers & originals:
                left.append(os.path.relpath(path, dst))
    for part in parts:  # every row keeps its player class; one player has one id throughout
        games = os.path.join(dst, part, "games.npz")
        with np.load(os.path.join(src, part, "games.npz"), allow_pickle=False) as a, np.load(games) as b:
            for h, pid in zip(a["players"].reshape(-1), b["players"].reshape(-1)):
                if player_class(h) != player_class(pid) or ids_of[int(h)] != int(pid):
                    left.append(f"{part}/games.npz (a player's class or id)")
                    break
    if left:
        raise SystemExit(f"an id of the source is left, or a class changed, in {len(left)} file(s) of the copy "
                         f"(e.g. {left[0]}): the copy was removed")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({"dataset": os.path.abspath(src), "copy": os.path.abspath(dst), "replay_ids": mapping}, f)
    with open(player_map_path, "w", encoding="utf-8") as f:
        json.dump({"dataset": os.path.abspath(src), "copy": os.path.abspath(dst),
                   "players": {str(h): str(pid) for h, pid in sorted(ids_of.items())}}, f)
    return len(mapping)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pseudonymize.py", description=__doc__.split("\n")[0])
    p.add_argument("--dataset", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--map", required=True, help="the replay ids' map (local)")
    p.add_argument("--player-map", required=True, help="the players' map (local)")
    p.add_argument("--seed-file", required=True, help="the players' seed (local; made when missing)")
    a = p.parse_args(argv)
    n = pseudonymize(a.dataset, a.out, a.map, a.player_map, a.seed_file)
    print(f"{n} replay ids and every player hash replaced; the map stays local, apart from the copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
