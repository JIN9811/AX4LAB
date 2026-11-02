# Task 2 — Geometry contract, meshing, and legacy Gyroid adapter

## Scope and interfaces

Implemented only in the isolated `feat/design-workspace` checkout. No production
edits, restarts, equipment actions, package installation, push, API/UI work, or
changes to the old production geometry dispatch. No delegated reviewers.

- `workspaces.design.catalog.DesignCatalog(root: Path | None = None)` discovers
  capability containers and their `geometries/*` via the Task 1 common catalog.
  `modules` is a list of common records, `geometries` maps `(module_id, geometry_id)`
  to records, and `errors` contains isolated metadata failures.
- `resolve(module_id, geometry_id, version)` returns a deep copy with the common
  record keys plus `module_id`, `module_version`, `source_files`, and
  `source_fingerprint`. No provider executes during discovery or normalization.
  Refresh means constructing another catalog. A previously accepted catalog
  rejects changed files. Shared loaded numerical code requires a fresh worker.
- `engine.normalize_request(request, catalog)` returns ONLY the canonical
  request, not a validation envelope. `engine.request_sha256(normalized)` hashes
  sorted compact finite JSON. Defaults, floats and vectors are materialized;
  identity/output paths are not part of request identity.
- `engine.generate_geometry(request, output_dir, *, identity, catalog)` returns
  the receipt and writes `geometry.stl` and `receipt.json` in a NEW directory.
  The directory must not already exist, including an empty directory. It is
  host-owned, not a request field. Traversal and symlink ancestors are rejected.
  Failed numeric jobs may leave diagnostic STL/partial directories but never a
  successful receipt; the future job layer owns cleanup/retention.
- `tool_adapter.generate_tool(payload)` takes an explicit nested
  `geometry_request`, trusted `output_dir`, and optional identity keys. It returns
  the existing geometry-tool keys plus `geometry_receipt`, with the receipt also
  nested in `geometry_report`. It writes the actual JSON report/log; image paths
  are empty, estimated mass is null, and no fake rendering or mass is generated.
  Task 6 must connect the explicit nested branch; old calls are unchanged.
- CPU job `geometry.design_generate` is whitelisted and dispatched before the
  generic `geometry.*` branch. Payload keys: `request`, `output_dir`, `identity`,
  `source_fingerprint`, optional trusted `catalog_root`. The worker reconstructs
  the catalog, verifies the acceptance fingerprint BEFORE generation, and calls
  the engine directly (never submits a nested pool job).

## Request and descriptor contract for Tasks 3–6

Request schema is `ax4lab.geometry_request.v1`. Allowed keys: `schema`,
`module_id`, `geometry_id`, `provider_version`, `representation`, `parameters`,
`specimen_size_mm`, `orientation_deg`, `quality`, `resolution`, `seed`. IDs/version
are mandatory and resolved exactly; no unknown explicit ID becomes Gyroid.

Defaults: representation from descriptor, parameters from the active field
schema, size `[30.0,30.0,30.0]`, orientation `[0.0,0.0,0.0]`, quality `preview`,
resolution `48` for preview / `96` for final, seed null. A stochastic descriptor
or positive legacy defect fraction requires uint32 seed. Parameter numbers and
vectors are normalized to floats; integer fields remain integers.

Dimensions must be finite and within `[0.001,1000]` mm; legacy sheet requires
each dimension >= 1 mm because its writer otherwise clamps. Resolution is an
integer `[16,160]` (booleans rejected). Generic fields use `n³` points, with
`(n+2)³` closure padding, maximum 4,251,528 padded points. Legacy adaptive n is
exactly the writer's rule; normalization rejects requests whose effective n
would exceed 160 instead of pretending the requested lower resolution is used.
Legacy writer's existing connectivity refinement may still raise n to 160.
Provider-specific expensive work must also be bounded in Task 3 (wave counts,
edge/site counts, feature spacing). Task 4 owns measured concurrent RAM limits.

Container schema: `ax4lab.design_module.v1`; normal common identity and a fixed
`provider.py` capability container, with actions/output_kinds metadata.
Geometry schema: `ax4lab.geometry_provider.v1`; common identity, `representations`
(nonempty unique strings), `default_representation`, `fields`, `defaults`,
optional boolean `stochastic`, and `engine` (`field` default or `legacy_gyroid`).

`representation_parameters` optionally maps each mode to `{fields, defaults}`.
A selected group's schema REPLACES the base schema, rather than merging inactive
sheet/network parameters. `catalog.parameter_schema(descriptor, representation)`
is the shared lookup. This avoids using common visible_when across the separate
request representation field. Task 3 should supply mode-specific groups when
adding network modes. Existing Gyroid sheet descriptor declares z-only orientation.

## Numerical provider contract

Every generic provider exports `generate_field(grid: dict, request: dict) -> dict`.
Request is a deep copy of the normalized request; providers are trusted installed
code, self-contained or wrappers around `workspaces/design/providers/*.py`.
No executable imports/paths are supplied by descriptors.

Grid contains:

- `x`, `y`, `z`: dense `(n,n,n)` arrays in mm in rotated LOCAL coordinates.
- `world_x`, `world_y`, `world_z`: dense arrays in the fixed centered specimen.
- `spacing_mm`: three spacings; `shape`: `(n,n,n)`; `units`: `mm`.
- `bounds_mm`: two vectors `[-size/2,+size/2]`, the world clipping domain.

Generic orientation is active XYZ Euler degrees with `Rz @ Ry @ Rx`; inverse
rotation maps world coordinates to local field coordinates BEFORE clipping.
The field is sampled over the fixed world box. Providers using caps/finite walls
can use world coordinates to keep physical compression planes aligned with it.

Required result: `field` (same shape, finite scalar, negative solid),
`units` (`mm` or `dimensionless`), `bounds_mm` (same domain), nonempty `method`.
Other finite JSON-compatible metadata survives in `provider_metadata`; do not
return NumPy arrays/scalars in metadata. Engine adds spacing, sampled solid
fraction, sampling/closure method, and orientation labels.

Optional `validation={ok: bool, reject_reasons: list[str], ...}` gates FINAL
success. A final false fails without publishing receipt; preview preserves the
explicit failed check and cannot become final evidence. Task 3 can attach
provider-specific thickness/calibration/error checks here. Absent validation is
explicitly `not_applicable`, not a claimed physical thickness measurement.

Meshing pads positive exterior, extracts the zero level, clamps closure to the
box, snaps only float32-scale grid roundoff, welds and removes collapsed/duplicate
faces, writes binary STL and reloads that actual STL. It checks watertightness,
edge topology, face winding, finite unit normals, a single connected component,
positive bounded volume and actual centered bounds. Generic processing never
silently discards disconnected components. A rotated analytic slab independently
checks bounds `[[-5,-1.5,-3],[5,1.5,3]]` and volume 180 mm³.

Legacy Gyroid sheet is an explicit exception to generic field extraction: the
dedicated adapter calls `write_smooth_gyroid_stl` unchanged. It retains that
writer's z-field rotation sign, adaptive grid, caps and component-cleanup metadata.
X/y rotations are rejected, never dropped. Other representations can be added to
the same descriptor/provider and will use the generic field path.

## Receipt and source pinning

Receipt schema: `ax4lab.geometry_receipt.v1`. Includes `ok`, `quality`,
`final_geometry_valid`, `manufacturing_ready`, canonical `request`,
`request_sha256`, engine/module/provider versions, `source_fingerprint`,
`source_files`, `identity`, `artifacts`, actual `bounds_mm`, `volume_mm3`,
`volume_fraction`, `volume_method`, `checks`, and `provider_metadata`.

`identity` only permits `run_id`, `candidate_id`, `specimen_id`, `experiment_id`,
`job_id`, each a safe nonempty bounded segment. `artifacts.stl` has `basename`,
SHA-256 and size_bytes; no host paths or timestamps appear in the receipt.
Repeated identical request/source/identity across output destinations produces
equal receipts and STL hashes, including a real subprocess worker round trip.

`ok` means generation/common mesh checks passed (and, for final, provider checks).
`final_geometry_valid` is true only for a passed final request.
`manufacturing_ready` is always false: geometry does not establish printability.
Self-intersections, physical printability, mechanical properties, physical wall
verification and periodic boundary checks remain explicitly unchecked unless
future provider evidence is attached. Closed serialized triangle volume is
reported distinctly from sampled field fraction/legacy estimated density.

Fingerprint covers capability/geometry YAML and provider files, common catalog
and fields code, engine/catalog/meshing/tool adapter, legacy TPMS/mesh-quality
implementations, ALL shared `providers/*.py`, and hashes of Python/NumPy/SciPy/
scikit-image/trimesh versions. Installed wrapper bytes are compiled directly to
avoid timestamp-based stale pyc. File/source containment is rechecked even after
discovery. Changed shared sources in a process that generated before are rejected
with a restart requirement, before allocating an output directory. This is not a
hot-reload facility; arbitrary external provider dependency imports are unsupported.

## Recorded legacy baseline (10 mm cube, requested resolution 48)

Tests compare both complete legacy semantic reports and EXACT STL bytes between
the existing writer and new adapter. Cap cases use both caps, 0.8 mm skin and
27° z orientation; uncapped cases use 0°. All actual bounds are ±5 mm, watertight,
one connected component, positive volume, and pass STL reload validation.

| Cell mm | Wall mm | Caps / angle | Actual n | Triangles | Volume mm³ |
|---|---|---|---|---|---|
| 5 | 0.6 | off / 0° | 51 | 103400 | 414.164195579 |
| 10 | 0.6 | off / 0° | 51 | 54408 | 209.325859897 |
| 5 | 1.2 | off / 0° | 48 | 81796 | 771.504860016 |
| 10 | 1.2 | off / 0° | 48 | 50280 | 411.343721218 |
| 5 | 0.6 | on / 27° | 51 | 100352 | 525.080257145 |
| 10 | 0.6 | on / 27° | 51 | 62388 | 349.602782611 |
| 5 | 1.2 | on / 27° | 48 | 74428 | 814.021390136 |
| 10 | 1.2 | on / 27° | 48 | 55416 | 502.610719388 |

## TDD and verification record

All commands use `PYTHONPATH=runtime` and
`/tmp/ax4lab-design-validation.YQ2uYw/venv/bin/python -m pytest`.

1. Initial new tests before implementation: 15 failed / 19 fixture errors solely
   because `workspaces.design` did not yet exist. This import-stage red alone was
   not counted as sufficient numeric validation.
2. First implemented run: 32 passed / 2 failed. Real slab tests caught negative
   signed volume (-180) from the wrong marching-cubes winding direction; bounds
   and watertightness were correct. Corrected the extraction direction, not the
   validation; 34 passed in 4.59s.
3. Additional boundary tests: 6 failed / 36 passed. Caught non-ValueError malformed
   quality/huge-integer handling, missing final provider accuracy gate, symlink
   replacement escape, missing tool adapter. The sixth was a test fixture's
   non-reproducible injected runtime paths; added real temporary bindings metadata
   (no production path changes). Then 42 passed in 5.41s.
4. Legacy shared-code cache mutation test: genuine `DID NOT RAISE` red, then moved
   shared source guard before both legacy and generic generation. A representation
   schema test additionally verifies inactive parameters cannot leak across modes.
5. Binary dependency identity assertion failed before adding environment version
   digests to source identity, preventing same-wrapper/different-stack reuse.
6. Final changed-code command:
   `pytest runtime/tests/unit/test_design_geometry_contract.py runtime/tests/unit/test_design_geometry_legacy.py -q`
   — **44 passed, 73 warnings in 6.27s**, exit 0, after the final dependency
   fingerprint additions. Includes actual worker round trip and all eight exact
   old/new Gyroid comparisons.
7. Extended numerical command:
   `pytest runtime/tests/unit/test_design_geometry_contract.py runtime/tests/unit/test_design_geometry_legacy.py runtime/tests/unit/test_tpms_geometry.py runtime/tests/unit/test_gyroid_serialization_regression.py runtime/tests/unit/test_serialized_mesh_quality.py runtime/tests/unit/test_mesh_wall_thickness.py -q`
   — **68 passed, 92 warnings in 187.60s**, exit 0. Started before the final
   dependency-version identity addition; the later 44-test run covers that
   addition. At the controller's 180-second bound, the process finished before
   the attempted interrupt reached it; no tests were interrupted or skipped.
8. `git diff --check` — clean. Full-project suite not run as directed.

## Self-review and remaining boundaries

- New artifact paths are injected; worker test uses private temporary bindings.
- No legacy math/defaults or production tool branches were modified.
- Failure checks are numerical and serialized, not placeholder box outputs.
- Deterministic receipts intentionally exclude output directory and timestamps.
- Scope does NOT assert all fourteen geometries, independent physical sheet-wall
  validity, absence of self-intersections, slicing/manufacturing readiness, or
  compatibility of arbitrary installed Python dependency graphs.
- Shared source snapshot pinning applies from the first generation in a process;
  update installed code only through normal worker restart, not concurrent file
  mutation. The catalog itself detects stale acceptance snapshots on every resolve.
- Full-project suite is deliberately deferred to Task 7 per controller direction.
- External scikit-image currently emits NumPy 2.5 array-shape DeprecationWarnings;
  they are reported, not silenced and not caused by the new numerical contract.
  The extended existing-tool run also reports five existing Pydantic schema-field
  shadowing warnings in `experiments/schemas.py`.
