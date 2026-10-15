# E4.1: Owner-local BC6 conversion and fidelity checker

The Owner runs this code locally. The checkpoint and exported artifact never
leave that computer, including no transfer to the cloud agent. This branch
contains code and synthetic tests only. No training, distillation, E5 wiring
or adoption is performed. The tree and default JAX evaluator are unchanged.

## First: report the source metadata

From a clean checkout, under the Owner's existing machine lock:

```bash
tools/ci/machine_lock.sh e4-bc6-preflight env OPENBLAS_NUM_THREADS=1 \
  python tools/eval/run_bc6.py --checkpoint "$BC6_CHECKPOINT" --preflight-only
```

The full checkpoint SHA-256 must be
`bda5de8e4e960f3df41b029cd4d3d87fc48838fdd47c8562a78649e222ee9f39`.
It is checked before NPZ parsing, model import, output creation or a build.
The preflight reports only the source encoder/mask/model dimensions and the
hash. It does not print a tensor or create an output file.

HS confirmed the actual source mask locally as `0x082000835233ffff`,
encoder 6. This registration and the students' shared input contract pin it
exactly, with the full teacher SHA as provenance. The loader now checks
encoder-defined features through the existing C encoder preflight, including
reserve families 59..63. Undefined bits, older encoders and other registered
masks refuse explicitly. No feature or source mask is inferred or widened.
The earlier invalid contiguous bits-0..46 assumption is removed.

## Full local command

Use the repository's pinned NumPy/JAX CPU environment, Node 22 and the
pinned, built Showdown checkout. Set `DUOFORGE_PS_REFERENCE_DIR` (and
`DUOFORGE_NODE` when Node is not on PATH). `E4_OUT` and `E4_BUILD` must be
absolute paths outside every Git checkout; the output directory must be
new. The driver builds only the private bridge and shared library, Release
with IPO. Additional previously built native bridges can be supplied with
repeated `--runner PATH` options. They read the same private artifact locally.

```bash
tools/ci/machine_lock.sh --exclusive e4-bc6 env OPENBLAS_NUM_THREADS=1 \
  JAX_PLATFORMS=cpu python tools/eval/run_bc6.py \
  --checkpoint "$BC6_CHECKPOINT" --out "$E4_OUT" --build-dir "$E4_BUILD" \
  --training-commit "$BC6_TRAINING_COMMIT"
```

`BC6_TRAINING_COMMIT` is the **actual** historical training source commit
from the Owner's archived provenance. The NPZ format does not guarantee
that it contains this field. Never substitute the export commit. If that
training checkout was dirty, pass `--training-dirty`. This command does not
start another training run.

The local machine lock is required for the full command. In this agent's
cloud only synthetic tests run, without the Owner-PC lock.

## Frozen game, split and calibration protocol

The code constants, not caller-supplied size/seed knobs, define the run:

- `bc6_corpus.py`: run seed `0x2026101500040001`, split seed
  `0x2026101500040002`; 128 reserved training groups (unused), 128 calibration
  games, 1,024 held-out games. Every game has its own battle and policy seed.
  No conversion training data is extracted. The original BC6 was trained on
  historical replays; these new synthetic games are not those training games.
- Registry team families are assigned by their full paste digest before any
  row extraction. The existing engine setup filter names rejected teams.
  Separately seeded pinned random-team generation supplies 64 additional
  teams per used split, using the existing composer and legality checks.
  Identical generated team families in different splits refuse explicitly.
- Pinned Showdown plays the games with its existing random-choice policy,
  cap 96 steps, switch weight 0.1, Mega weight 0.5, no domain sampling.
  No value evaluator decides a played move. The normal client oracle replays
  these fresh games into the real open tracker and closed ParticleTracker.
  Both seats are covered; closed requests use 16 accepted worlds.
- The production Honest preparation freezes K=8, M=8, S=16, padding=1024,
  one worker, search/chance seeds, candidates, priors, weights, utilities,
  digest/status/valid-key arrays and play uniform. At most the first two
  ordinary roots per seat plus the first PIVOT/REPLACEMENT are captured.
  Root selection reads metadata only: boundary/seat coverage first, then a
  seeded order round-robin by game. Exact selected files/hashes are frozen
  before either value evaluator reads the corpus.
- Held-out selection is exactly 2,048 roots per sheet stratum (4,096 total),
  at least 131,072 neural rows and 256 independent groups. Missing counts
  or any TURN/REPLACEMENT/PIVOT × seat, field/item/ability coverage fail.
  Named unsupported tracker/world/battle attempts are counted and are never
  replaced by newly seeded games. Model, encoding and unexpected errors fail.
- Calibration uses 32 roots per stratum, 64 seeded neural rows per root
  (4,096 total). Units 256,512,1024,2048,4096,8192,16384 are tried only on
  calibration, lowest MAE then lower unit wins. Unrepresentable quantization
  candidates refuse by name; inference failures abort. No hold-out tuning.

`split.json`, corpus manifests and `gate-manifest.json` freeze source,
context, seeds, exact requests and policies before the value runs. The final
calibration manifest is frozen before held-out values are read. All of these
files, including generated games, stay private outside the checkout.

## Conversion and gates

The converter positively classifies all 46 original parameter leaves and
keeps every original float32 bit in the 27-leaf value-path audit (1,802,441
learned parameters). Nineteen policy/team-only leaves are validated and
explicitly omitted. The compiled wire has 28 tensors including input.unit.
Dense weights transpose from input/output to output/input. Signed exact
round-to-nearest ties-even, symmetric int8 weights, per-output dense scales,
int64 biases, learned int32 LayerNorm gamma/beta and conservative loader
bounds are explicit. There is no learned-parameter clipping or fallback.

The extracted floating graph must match the original JAX value bits at the
fixed padding before quantization is assessed. The independent Python integer
graph compares all 201 intermediates on 16 balanced held-out rows. Every
native runner recomputes every held-out value twice. All native value and
intermediate streams must match. These are private offline bridge calls,
not a new public evaluator API or a production timing measurement.

Section 9's full BC6 thresholds are unchanged: separately open/closed,
MAE ≤ .01, p99 ≤ .05, max ≤ .15; actual EV/Nash/inherited-live played choices
≥ 98% under identical uniforms; stable EV margin ≥ .02 agreement ≥ 99%;
mean/p99 TV ≤ .02/.10; mean/p99 teacher-valued regret ≤ .002/.02. Mean metrics also report a
2,000-resample game-cluster bootstrap interval with fixed seed
`0x2026101500040003`; no undefined denominator is discarded. The same
existing search reducers apply to both prepared tables. Terminal/refused
utilities are not included as easy zero-error neural rows. Step/encoding/
result arrays are compared between old expansion and repeated digest
expansion before capture. An unsupported digest never removes a battle edge.

Compiler/platform cells are GCC/Linux, Clang/Linux, MSVC/Windows,
Clang/Windows and GCC/Windows. An absent native runner leaves that gate
incomplete. A successful numeric run on one platform therefore still exits
3 until the matrix is complete; it never claims all fidelity passed.

The driver regenerates the selected artifact twice, compares bytes, and
runs the standalone exporter's read-only `--check`. For another regeneration
check using the saved private manifest:

```bash
python tools/eval/export_bc6.py --repo "$PWD" --checkpoint "$BC6_CHECKPOINT" \
  --manifest "$E4_OUT/export-manifest.json" --output "$E4_OUT/bc6-full.dfeval" \
  --audit "$E4_OUT/export-audit-private.json" --check
```

No existing output is overwritten. Files use mode 0600 and the driver uses
umask 077 (on Windows, retain the Owner's private-directory ACL).

## Return to HS/cloud

Return **only** `gate-summary.json` and the selected file's SHA-256. That
summary contains aggregate counts, thresholds, metrics, agreement intervals,
compiler/binary hashes, source commit and dirty status. Keep the checkpoint,
DFEVAL file, row files, generated games, traces, detailed audits and manifests
on the Owner computer. No private file is an allowed CI artifact.

Exit 0 means all implemented full-conversion gates including the native
matrix passed; 3 means a completed run with failed/incomplete gates; 2 means
a named preflight/tool/input failure. Passing conversion still grants no
live adoption and no distillation/training authorization.
