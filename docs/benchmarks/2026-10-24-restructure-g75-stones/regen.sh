#!/usr/bin/env bash
# The two files of this step made again from their sources with tools/restructure/split_test.py and compared byte for byte
# with the checked-out tree: forms/test_mega_stones.c (the merge of 6e-2 with G75's section added) and
# interactions/test_cheap_set_rows.c. Usage: bash docs/benchmarks/2026-10-24-restructure-g75-stones/regen.sh <scratch dir>
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
t=$1/g75
rm -rf "$t"; mkdir -p "$t"
git -C "$repo" archive de746106 tests | tar -x -C "$t"   # the sources of 6e-2's merge (main before #662)
cp "$repo/tests/support/conformance_replay.h" "$t/tests/support/"
git -C "$repo" show 5bddd637:tests/interactions/test_pool_g75.c > "$t/tests/interactions/test_pool_g75.c"   # G75 grouped by subject
python3 "$repo/tools/restructure/split_test.py" "$repo/docs/benchmarks/2026-10-24-restructure-g75-stones/specs/mega_stones.merge.json" --merge --root "$t" > /dev/null
python3 "$repo/tools/restructure/split_test.py" "$repo/docs/benchmarks/2026-10-24-restructure-g75-stones/specs/g75.json" --root "$t" --except forms/test_mega_stones.c > /dev/null
bad=0
for f in forms/test_mega_stones.c interactions/test_cheap_set_rows.c; do
    if ! cmp -s "$t/tests/$f" "$repo/tests/$f"; then echo "DIFFERS: $f"; bad=$((bad + 1)); fi
done
echo "regen: 2 files compared, $bad differ"
[ "$bad" -eq 0 ]
