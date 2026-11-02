# Design Workspace

Open **Design** from the workspace launcher, or `/design`, on the server PC.
Select **Metamaterial Unit Cell Designer**, a geometry and its representation.
The installed descriptors supply the controls, units, defaults and available modes.
Only declared actions are available: preview-only modules cannot Generate, even
through the API. Provider status states **Manual only** or **Agent handoff
supported**; support never implies manufacturing approval.
New profiles in Generate-only modules use final quality and the final resolution.
These modules remain manually usable, but agent handoff requires both Preview
and Generate because the current workflow always produces separate preview evidence.

## Configure and generate

1. Select **New**, name a profile and edit geometry parameters, specimen dimensions
   and orientation. **Save profile** persists the draft; it does not generate or
   operate equipment. Unsaved edits remain visibly distinct from saved state.
2. **Preview** creates a separate, explicitly non-final STL and interactive view.
   The usual resolution is 48. Changing inputs does not relabel an existing mesh.
3. **Generate** creates final geometry, normally at resolution 96. Select the
   exact job in history and **Download STL** after success. Final generation does
   not silently replace the displayed preview. Receipts record the accepted
   inputs, source identity, validation, artifact SHA256 and numerical timings.
4. Cancel queued/running jobs when necessary. Profile deletion requires confirmation
   and does not delete generated artifacts. Refresh discovers installed modules;
   disabling/removing one makes its profiles unavailable without deleting history.

The API is loopback/same-origin only. One active and one queued job are allowed;
the worker timeout is 300 seconds. A configured existing CPU pool is required.
No pool returns 503, not an inline numerical fallback. Interrupted jobs remain
interrupted after restart; they are not automatically replayed.

## Geometry is not manufacturing approval

All fourteen IDs are implemented: Gyroid, Schwarz P/D, I-WP, Neovius,
Fischer–Koch S, Spinodoid, Simple Cubic, BCC, FCC, Octet, hexagonal/re-entrant
honeycomb and Voronoi. The six TPMS families support sheet and positive/negative
network modes. Other families have explicit GRF, strut or extruded-wall modes.

Dimensions are millimetres; orientation is active XYZ degrees in a fixed centered
specimen box. Legacy Gyroid sheet supports Z rotation only. A strut diameter is
not a sheet wall thickness. TPMS are Fourier nodal approximations, not exact
minimal surfaces. Spinodoid fraction is an ensemble target, not guaranteed finite
density. Seeds are mandatory for Spinodoid, Voronoi and nonzero random defects.

Schema limits: dimensions 0.001–1000 mm (legacy Gyroid at least 1 mm), resolution
16–160, seed 0–4294967295. These are admission bounds, **not a promise every
combination meshes**. Provider sampling, work budgets, physical-width calibration
and actual serialized-STL topology must also pass. New sheets/struts/walls need
four voxels across the feature; thin or disconnected final geometry fails closed.
No crop adjustment, seed substitution or fragment removal hides that failure.
Defaults are tested for a 30 mm cube, final 96, zero rotation and seed 42 where
needed. NumPy/SciPy/scikit-image/trimesh versions are included in source identity.

`final_geometry_valid=true` means numerical geometry validation, never mechanical
validation or print approval. `manufacturing_ready` remains false. New-family
Specimen preparation reuses the verified receipt, still runs mesh and actual-STL
wall checks, and stops at the existing manufacturing **review required** boundary.
No slicing/printing is authorized by generation. Unmeasured strength/SEA, mass,
cost and duration stay unassessed/null. Explicit legacy Gyroid keeps its existing
manufacturing policy; legacy requests without the new contract retain their path.

See the [mathematical/source catalog](../../system/references/metamaterial_geometry_catalog.md)
for formulas, conventions, physical-width tolerances, tested defaults, known
rejected crops/seeds and source/license notices. Implementations are independent;
no external generator source was copied. In particular GIBBON, LatticeQuery and
PyAuxetic are research references, not bundled dependencies or adopted licenses.

## API and existing agents

`GET /api/design/modules` and
`GET /api/design/modules/{module_id}/geometries` discover capabilities.
`POST /api/design/validate` accepts `{"request": ...}`. Profiles use
`/api/design/profiles`; updates/deletions require the current revision, and delete
requires `confirmed: true`. Module state updates also require its revision.

Example `POST /api/design/jobs` body:

```json
{
  "idempotency_key": "my-cubic-001",
  "request": {
    "module_id": "metamaterial_unit_cell_designer",
    "geometry_id": "simple_cubic",
    "provider_version": "1.0.0",
    "quality": "final",
    "resolution": 96,
    "parameters": {"cell_size_mm": 10, "strut_diameter_mm": 2}
  }
}
```

Poll the exact returned ID at `/api/design/jobs/{id}`; use its returned
`artifact_urls` after success. Reusing a key with changed inputs is a conflict.
Requests cannot select output paths, Python modules, equations or shell commands.
Changed/removed sources after acceptance invalidate execution; reload workers
after installing new source code. Receipts remain tied to their original source.

The existing registered Design graph opts in through
`state.run_metadata['orchestrator_design_contract']['geometry_request']`.
Optional `geometry_candidates` admits at most eight distinct normalized requests.
Shared request preflight rejects known cross-field, sampling and resource failures.
Invalid alternatives remain in the rejection evidence, not the selection pool;
an invalid primary request fails without substitution. Preflight-admitted candidates
are explicitly **pending** final geometry checks (not hard-valid). Model selection
is conditional; only a verified final serialized receipt authorizes handoff.
Unselected preview failures are reported without invalidating a verified selection.
It uses the same engine/tool/CPU job, preserves seed and representation through
selection, and creates separate hash-linked actual-STL preview PNGs. Specimen
reuses only verified final receipts; corrupted artifacts regenerate the same
locked request. No graph stage or device admission identity is added.

## Installation, extension and verification

The normal runtime install (`python -m pip install ./runtime`, or its built wheel)
already declares NumPy, SciPy, scikit-image, trimesh, rtree and Pillow; there is
no separate Design scientific extra. The wheel includes the shared catalog,
all provider wrappers/implementations/descriptors/icons and browser resources.
The main host binding is lazy: installation registers routes without opening
devices, loading numerical engines, creating state or submitting jobs.

For a third installed module/provider, see the
[packaged extension reference](../../runtime/workspaces/design/README.md).
Install reviewed files on disk and refresh; the UI does not upload executable
code. Adding a form does not establish scientific validity or manufacturing policy.

From `runtime/`, with test dependencies installed:

```sh
PYTHONPATH=. python scripts/verify_design_workspace.py --output-root /tmp/design-check-unique
```

The root must not already exist. All mutable roots and worker bindings are
explicit and isolated. The verifier denies non-geometry tools before dispatch,
compares actual API/registered-agent request and STL hashes for TPMS/Spinodoid/
strut examples, verifies Specimen reuse, and retains receipts, previews, logs,
per-test XML and numerical/Serial regression evidence. It makes no LLM call.

Isolated validation on 2026-11-02 also completed a separate real configured
`endpoint:api-main` / `gpt-5.5` Design run through `AgentContext`, with no mock
fallback. This is bounded model/geometry evidence, not equipment execution.
The default whole-project suite remains blocked at collection by missing
pyarrow/torch/h5py/cv2 in the isolated validation environment. Production was
not restarted, configured, upgraded or activated by this worktree validation.
