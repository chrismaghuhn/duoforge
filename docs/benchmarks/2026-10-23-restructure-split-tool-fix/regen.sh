#!/usr/bin/env bash
# Every part of restructure 6e-1 and 6e-2 made again from its sources with tools/restructure/split_test.py, compared byte for
# byte with the checked-out tree. Usage: bash docs/benchmarks/2026-10-23-restructure-split-tool-fix/regen.sh <scratch dir>
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
scratch=$1
d1=$repo/docs/benchmarks/2026-10-23-restructure-test-splits-abilities/specs
d2=$repo/docs/benchmarks/2026-10-23-restructure-test-splits-forms-items/specs
t1=$scratch/e1; t2=$scratch/e2
rm -rf "$t1" "$t2"; mkdir -p "$t1" "$t2"
git -C "$repo" archive 757a00ca tests | tar -x -C "$t1"   # the sources of 6e-1 (main before #656)
git -C "$repo" archive de746106 tests | tar -x -C "$t2"   # the sources of 6e-2 (main before #662)
for t in "$t1" "$t2"; do cp "$repo/tests/support/conformance_replay.h" "$t/tests/support/"; done
for k in g45 g65 g63 g22 a2a; do python3 "$repo/tools/restructure/split_test.py" "$d1/$k.json" --root "$t1" > /dev/null; done
python3 "$repo/tools/restructure/split_test.py" "$d2/mega_stones.merge.json" --merge --root "$t2" > /dev/null
for k in g51 g59 mega2 g57 g49; do
    python3 "$repo/tools/restructure/split_test.py" "$d2/$k.json" --root "$t2" --except forms/test_mega_stones.c > /dev/null
done
n=0; bad=0
for f in $(cut -f1,3,4 "$repo/tests/renames.tsv" | awk -F'\t' '$2=="part" || $2=="merge" {print $3}' | sort -u) abilities/test_magic_bounce.c; do
    case $f in forms/test_mega_stones.c|abilities/test_keen_eye.c|abilities/test_regenerator_pivot.c|abilities/test_mega_launcher.c|abilities/test_mega_sol.c|abilities/test_aura_guard.c|abilities/test_magic_bounce.c|items/*) src=$t2/tests/$f ;; *) src=$t1/tests/$f ;; esac
    n=$((n + 1))
    if ! cmp -s "$src" "$repo/tests/$f"; then echo "DIFFERS: $f"; bad=$((bad + 1)); fi
done
echo "regen: $n files compared, $bad differ"
[ "$bad" -eq 0 ]
