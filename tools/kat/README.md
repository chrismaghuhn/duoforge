# PCG32 known-answer vector generator

`gen_pcg32_kat.c` is DuoForge's harness. It links the **pinned** upstream reference and prints `tests/data/pcg32_kat_vectors.h`.

## Regenerate

```sh
git clone https://github.com/imneme/pcg-c-basic.git "$PCG"
git -C "$PCG" checkout --detach bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3
sha256sum "$PCG/pcg_basic.c" "$PCG/pcg_basic.h"   # must match third_party/pcg-c-basic/PROVENANCE.md
cc -std=c17 -O2 -I"$PCG" tools/kat/gen_pcg32_kat.c "$PCG/pcg_basic.c" -o gen
./gen > tests/data/pcg32_kat_vectors.h
```

The output is deterministic, with no dates. The committed header was generated on 2026-09-30 with `gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` and has sha256 `6935902bbed5879a9d95647f1caa1615923990b04bc4503a8bb7f8848440a1b2`.

The CMake option `-DDUOFORGE_PCG_REFERENCE_DIR=$PCG` automates this. It builds the generator against the checkout and runs:

- `duoforge.rng.kat_regen`, which checks byte-identical regeneration;
- `duoforge.rng.reference_differential`, which runs 1,024,000 mixed raw and bounded operations in lockstep with the reference.

The CI workflow `.github/workflows/rng-reference.yml` does the same.

## Contents

The header covers 6 seeds. For each seed it has:

- the state after seeding;
- 16 raw words and the state after them;
- 9 bounds (1, 2, 3, 6, 7, 100, 2^31, 2^31+1, 2^32-1), 12 sequential bounded draws each, with the number of raw words each draw consumed;
- a shuffle sequence: bounded(52) down to bounded(2).

The harness measures draw counts by re-stepping a copy of the reference state, independently of DuoForge code. It exits nonzero if any single call needs more than 255 draws.
