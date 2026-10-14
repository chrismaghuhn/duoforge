# Private BC6 value export: plan before E4

Status: proposed hand-off for Owner/HS review. E2/E3 use synthetic parameters;
this document performs no private-file read, conversion, calibration or training.
Each E4 conversion and each individual distillation run still needs the Owner's
explicit Go under the [evaluation spec](../specs/2026-10-14-in-engine-evaluation-design.md).

## Format and private storage

E2 freezes `DFEVAL` v1: bounded little-endian header, canonical UTF-8 metadata,
exact tensor directory, integer payloads and explicit multiplier/shift records.
The initial metadata grammar is a documented ASCII subset of UTF-8. The loader
accepts only compiled, reviewed graph descriptors, not an executable graph in a
file. Its production registry stays unavailable until E3g registers the actual
candidate descriptors; successful E2 fixtures use a private test-only descriptor.

The format pins the encoder-6 names/order/grouping and mask, categorical capacities,
engine context fingerprint, arithmetic version, shapes, rounding/saturation nodes
and per-graph file/workspace bounds. Unknown entries and incompatible versions are
named refusals. The exact byte contract is [DFEVAL v1](../specs/2026-10-14-dfeval-v1.md).

Checkpoint, calibration/split manifests, exported file and detailed audit reports
live in an Owner-configured private directory outside every repository checkout.
No default private path, download, model discovery, embedded trained model or CI
upload is introduced. Runtime configuration supplies an absolute file path and
mandatory expected full-file SHA-256. The loader hashes the actual opened bytes
and validates the complete file before publishing an immutable model handle.

## SHA chain and deterministic reproduction

The private manifest records full SHA-256 values for this dependency chain:

1. Original checkpoint bytes, configuration and each source value-path tensor.
2. Canonical value-graph/tensor inventory and input name/group mapping.
3. Disjoint generation-group split and calibration/quantization manifests, including
   scales, epsilon representation, bounds and all rounding/saturation sites.
4. Exporter/oracle code commits and dirty flags, engine context and arithmetic version.
5. Complete `DFEVAL` file and canonical audit report, linked to the preceding hashes.

The external trusted configuration pins item 5; an embedded checksum or claim of
approval cannot replace it. Changing any dependency requires explicit regeneration,
revalidation and a new expected hash. E4's exporter has deterministic regeneration
and `--check`; existing bytes are never patched manually. Two clean exports of the
same frozen inputs must be byte-equal. Public reports expose aggregate counts and
code/schema provenance; private payloads, paths and detailed rows remain private.

## What establishes the full BC6 conversion's “1:1” claim

The claim means the complete original **value graph** and its learned-parameter
provenance. It does not mean bit-equal floating values after integer quantization.
The frozen checkpoint, rather than a nickname or preset, fixes actual dimensions.

- Inventory every source value tensor with shape, element count and canonical
  binary32-bit hash. Account for every source element exactly once in its declared
  integer tensor and scale mapping. The audit distinguishes source-bit identity
  from quantization error; it never hashes dequantized values as original weights.
- Preserve embeddings, move/member masks and ordered pools, gathers, all dense
  layers, learned LayerNorm gamma/beta, positive epsilon, ReLU order, residuals and
  the linear value head. Only heads proven unused by `policy.Model.value` may be
  omitted. No retraining, distillation or operator replacement is this conversion.
- Compare the extracted floating value-only oracle to the original JAX value call
  under identical pinned inputs/backend/settings before quantization; report any
  difference rather than presenting operator completeness as numerical parity.
- Compare the integer oracle and C implementation exactly, including canonical
  inputs and intermediate tensors, across supported compilers/platforms. Then run
  the original JAX-versus-C BC6 gates on the untouched held-out corpus: MAE <= 0.01,
  p99 <= 0.05, maximum <= 0.15; decision agreement >= 98%, stable-margin agreement
  >= 99%; distribution and regret limits exactly as spec section 9 specifies.
  Mechanics/status/key classification, finite values and reproduction also gate.

A complete inventory alone does not pass the numerical or decision gates. Failure
leaves D4 on JAX; tolerances are not widened after results. Distilled small/medium
candidates report these deviations but use their separate mandatory gates and the
strength-at-equal-time comparison, with equal-budget controls, to determine adoption.

No export, private conversion, calibration or training starts from this plan alone.
