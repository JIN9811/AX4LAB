# Modular Design Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dynamic Design Workspace and Metamaterial Unit Cell Designer that share actual specimen generation and validation with the existing Design Agent.

**Architecture:** A common installed-module catalog supplies metadata to thin workspace APIs and schema-driven forms. Geometry providers share a numerical meshing/validation service; the existing geometry tool and agent graph use adapters into that service. Legacy Gyroid/BO behavior stays on a compatibility path.

**Tech Stack:** Existing Python/FastAPI/Jinja/static JavaScript, PyYAML, NumPy/SciPy/scikit-image/trimesh, existing CPU pool; pytest and browser validation. No new MATLAB/CAD server or hardware service.

**Spec:** `docs/superpowers/specs/2026-11-02-design-workspace-design.md` (approved).

## Global Constraints

- No physical equipment actions, production restart, active-run mutation or automatic printing.
- Keep agent/module/package admission, graph handlers, archive ownership and stage order.
- Common metadata discovery reads installed folders, never executes descriptor-supplied code.
- Preserve Serial Communication URLs, schema, profiles and protocol behavior.
- Preserve old Gyroid outputs and defaults; unknown explicit new IDs never silently become Gyroid.
- No fabricated SEA, strength, mass, duration, wall thickness or manufacturing success.
- New-family parameters/receipts must survive previews, fingerprints, handoffs and reports.
- All runtime state uses injected paths. No tracked user configuration, secrets or test artifacts.
- Isolate development with `using-git-worktrees`; never copy private configuration into tracked files.
- Implement all fourteen geometry IDs below before claiming the approved initial scope complete.

## Review Focus

1. Removed/disabled/updated providers while a job is accepted: preserve pinned identity, never substitute code (Tasks 1, 4).
2. Correct-looking meshes with incorrect physical thickness or disconnected struts: independent geometry checks, not render-only acceptance (Tasks 2, 3).
3. Nested new-family fields silently lost by old agent projections/float conversions: prove entire registered graph and Specimen preparation (Task 6).
4. Refresh/concurrent tabs/cancellation publishing stale results: revision/idempotency and request identity tests (Tasks 4, 5).
5. Distribution excludes descriptor/provider assets: test extracted installed wheel, not only editable source (Task 7).

## File and interface map

- `runtime/workspaces/catalog.py`: descriptor discovery, containment, duplicate handling and immutable identity snapshots.
- `runtime/workspaces/fields.py`: safe declarative field validation and normalization.
- `runtime/workspaces/design/catalog.py`: workspace/geometry schema adapters.
- `runtime/workspaces/design/engine.py`: validated numerical generation and receipt creation.
- `runtime/workspaces/design/meshing.py`: grid, clipping, surface extraction and artifact mesh checks.
- `runtime/workspaces/design/providers/{tpms,spinodoid,strut,cellular}.py`: pure numerical implementations; no controllers/devices.
- `runtime/workspaces/design/modules/metamaterial_unit_cell_designer/`: workspace descriptor/icon and `geometries/<id>/{module.yaml,provider.py,icon.svg}`.
- `runtime/workspaces/design/{profiles,jobs,service,api,host}.py`: private persistence, job orchestration and host binding.
- `runtime/workspaces/design/tool_adapter.py`: existing tool result and trusted run-path compatibility.
- `runtime/agents/design/geometry_adapter.py`: new-family candidate/receipt handling only.
- Existing serial catalog, Design/Specimen owner files, compute dispatch, distribution and main GUI: small integration edits, not broad rewrites.
- `runtime/web/{templates/design.html,static/design_workspace.js,static/design_workspace.css,static/workspace_fields.js,static/workspace_icons/design.svg}`: established-style dynamic interface.

Common signatures:

```python
discover_modules(root: Path, validator: Callable[[dict], dict]) -> tuple[list[dict], list[dict]]
normalize_fields(fields: list[dict], defaults: dict, values: dict) -> dict
DesignCatalog(root: Path | None = None)
DesignCatalog.resolve(module_id: str, geometry_id: str, version: str) -> dict
normalize_request(request: dict, catalog: DesignCatalog) -> dict
generate_geometry(request: dict, output_dir: Path, *, identity: dict, catalog: DesignCatalog) -> dict
DesignService(memory_root: Path, artifact_root: Path, *, catalog: DesignCatalog | None = None)
DesignService.validate(request: dict) -> dict
DesignService.submit(request: dict, *, idempotency_key: str) -> dict
DesignService.job(job_id: str) -> dict
DesignService.cancel(job_id: str) -> dict
create_router(service: Callable[[], DesignService], templates) -> APIRouter
install_design_workspace(app, paths, templates) -> None
```

Request schema `ax4lab.geometry_request.v1`: `module_id`, `geometry_id`, `provider_version`,
`representation`, `parameters`, `specimen_size_mm` (3 positive floats),
`orientation_deg` (3 floats), `quality` (`preview`/`final`), `resolution`, `seed`.
Seed required for stochastic providers. Unknown keys rejected; default normalization
is explicit and returned. Initial module ID: `metamaterial_unit_cell_designer`.

Receipt schema `ax4lab.geometry_receipt.v1`: normalized request and SHA-256,
provider/module versions and source fingerprint, run/candidate/specimen identity,
artifact basenames/hashes, actual bounds, checks and quality. Paths are host-owned;
HTTP serializes artifact IDs/URLs, not arbitrary local paths. `ok` requires final
checks for final jobs; preview receipts cannot be used as manufacturing receipts.

### Task 1: Common catalog and serial compatibility

**Files:** shared catalog/fields files above and `__init__.py`; modify
`runtime/device_bridges/serial_communication/catalog.py`; create
`runtime/tests/unit/test_workspace_catalog.py`, `system/runtime/workspace_modules.md`.

**Interfaces:** produces `discover_modules`, `normalize_fields`; serial keeps its
existing `ModuleCatalog` public methods and `ax4lab.serial_device.v1` schema.

- [x] Write failing tests: a temporary third module appears without registration;
  duplicate IDs are excluded; descriptor/provider/icon symlinks cannot escape;
  discovery never imports a provider; malformed modules do not hide good modules.
- [x] Test number/integer/enum/boolean/text/vector fields, finite bounds, missing
  defaults, unknown values, and equality/membership-only `visible_when` conditions.
- [x] Run `pytest runtime/tests/unit/test_workspace_catalog.py -q`; verify genuine red.
- [x] Implement shared primitives and a serial adapter; preserve serial-specific
  validation and restart-on-code-change behavior. Do not change serial sessions.
- [x] Run new catalog tests plus `runtime/tests/unit/test_serial_*` and
  `runtime/tests/integration/test_serial_*`; all affected tests pass without ports.
- [x] Commit this independently testable contract with its reference document.

### Task 2: Geometry request, mesh pipeline and Gyroid compatibility

**Files:** design catalog/engine/meshing/tool_adapter and module descriptor files;
tests `runtime/tests/unit/test_design_geometry_contract.py`,
`runtime/tests/unit/test_design_geometry_legacy.py`.

**Interfaces:** produces `DesignCatalog`, `normalize_request`, `generate_geometry`.
Each installed provider exports `generate_field(grid: dict, request: dict) -> dict`;
`grid` contains mm-coordinate arrays and voxel spacing; returned `field` is a
signed scalar (negative solid), with explicit units, bounds and method metadata.
Legacy Gyroid is a dedicated adapter to the existing writer, not reimplemented math.

- [x] Write tests for invalid IDs/versions, negative/NaN dimensions, traversal,
  unsupported representations, repeatable hashes and preview/final separation.
- [x] Record legacy Gyroid semantic/mesh baselines at cell size 5/10 mm crossed
  with wall thickness 0.6/1.2 mm, including caps and orientation; tests compare
  old/new adapter outputs rather than assuming a visually similar mesh is equal.
- [x] Run new tests red, then implement normalized serialization and contained
  immutable job artifacts. Request identity excludes destination directory.
- [x] Implement closed finite-domain meshing, orientation-before-clipping,
  boundary closure, normals/component/bounds/volume checks and STL reload checks.
  Keep sampled/approximated/unchecked quantities explicitly labelled.
- [x] Add a CPU job named `geometry.design_generate` to `runtime/utils/compute_jobs.py`;
  trusted workers resolve the pinned provider fingerprint before computation.
- [x] Run contract, Gyroid serialization and existing mesh-quality regressions;
  verify identical normalized input and source identity produce identical receipts
  excluding timestamps/host paths. Commit.

### Task 3: Fourteen real geometry providers and research provenance

**Files:** provider implementations and fourteen geometry descriptor folders;
`runtime/tests/unit/test_design_geometry_families.py`,
`system/references/metamaterial_geometry_catalog.md` and adopted-code notices if needed.

**Interfaces:** all use Task 2's provider contract. IDs: `gyroid`, `schwarz_p`,
`schwarz_d`, `iwp`, `neovius`, `fischer_koch_s`, `spinodoid`, `simple_cubic`, `bcc`,
`fcc`, `octet`, `hexagonal_honeycomb`, `reentrant_honeycomb`, `voronoi`.

- [x] Before implementation inspect primary equations and any adopted source's
  license/revision. Record source, parameter meaning, approximation and status per
  family. No unlicensed copying or runtime downloads; record research-only families.
- [x] Write and run failing field/mesh tests before each family implementation:
  distinct topology signatures, expected symmetries, boundary periodicity where
  declared, no box fallback, joined struts, finite envelope and STL reload.
- [x] TPMS: implement `sheet`, `network_positive`, `network_negative`; use mm wall
  target for sheet and dimensionless iso-level for network. Independently measure
  sheet error against voxel spacing and provider calibration; insufficient
  resolution fails final validity instead of falsely confirming physical thickness.
- [x] Spinodoid: seeded GRF with wavelength/wave count/cone angles and solid-fraction
  threshold. Bound wave accumulation memory; mark finite domains non-periodic.
  Test same seed reproducibility, different seed variation and cone anisotropy.
- [x] Struts: explicit graph definitions and union-distance fields for SC/BCC/FCC/
  Octet. Test known edges/node valences and connected junctions separately from
  mesh watertightness; diameter remains diameter, never renamed wall thickness.
- [x] Cellular: extruded hexagonal and re-entrant wall geometry; test angle effects
  and wall interpretation. Voronoi: seeded strut network with contained boundary
  handling; do not represent nearest-cell interiors as Voronoi struts.
- [x] Test coarse/fine convergence, request bounds, numerical resource rejection,
  disconnected cases and meaningful volume fraction for each representation.
  Emit final success only for geometrically valid output; commit by family group.

### Task 4: Profiles, bounded jobs and public API

**Files:** design profiles/jobs/service/api/host; tests
`runtime/tests/unit/test_design_workspace_service.py`,
`runtime/tests/integration/test_design_workspace_api.py`.

**Interfaces:** implements the interface map's `DesignService`, router/host.
Private roots: `<memory_root>/design_workspace/` and
`<artifact_root>/design_workspace/<job_id>/`. Use existing compute pool, never
web-process mesh computation or nested pool submission.

- [x] Write failing tests for atomic profile saves, stale revision conflict,
  confirmed deletion, unavailable provider on saved profile and module enable state.
- [x] Write job tests: idempotency, bounded queue, pinned provider/config, refresh
  without resubmission, cancellation vs completion race, crash/restart interrupted
  state, file hash mismatch and failed writes leaving no successful receipt.
- [x] Implement submit/status/cancel and durable receipts. Pin provider fingerprint
  at acceptance; if removed code cannot run, return an explicit job error rather
  than substitute a provider. No automatic restart/resume of interrupted jobs.
- [x] Implement `/api/design/modules`, module refresh/icon/state/geometries;
  profiles CRUD; `/validate`; `/jobs` list/create/detail/cancel and contained
  artifact download. Enforce loopback/same-origin, payload limits and revision rules.
- [x] Test API shapes using injected temporary roots and fake numeric executor;
  then exercise actual generation via API without importing production controller.
- [x] Measure queue/memory limits on representative geometries and document exact
  supported resolution limits; repeat concurrent requests and cancellation. Commit.

### Task 5: Dynamic workspace GUI

**Files:** design HTML/JS/CSS/icon and shared `workspace_fields.js`; modify main
GUI launcher; tests `runtime/tests/js/design_workspace.test.cjs` and
`runtime/tests/ui/design_workspace_browser_audit.py`.

**Interfaces:** GUI only consumes Task 4 API; forms use field keys/types/defaults
from catalog. Reuse existing local 3D-viewer dependencies after inspecting them.

- [x] Write failing JS tests for metadata-rendered fields, visibility conditions,
  no hardcoded geometry list, dirty input preservation and stale response rejection.
- [x] Add module catalog, geometry selection, profiles, Preview/Generate/Download,
  bounded job history, concise checks and persistent 3D camera orientation.
- [x] Add enable/disable and Refresh modules; do not offer executable plugin uploads.
  Keep unavailable saved profiles/artifacts visible. Module removal changes new
  selections, not retained results. Selection changes cannot relabel old previews.
- [x] Test API numeric errors visibly, cancellation, reload/new tab, field edits
  during generation and a third fixture module displayed without frontend changes.
- [x] Use frontend-testing-debugging skill and available browser tools against an
  isolated server: 1920x1080 and narrow viewport, actual STL preview/download and
  keyboard controls. Confirm no production/device calls. Commit.

### Task 6: Existing Design Agent and Specimen tool connection

**Files:** `runtime/agents/design/geometry_adapter.py`; targeted changes to Design
agent/decision/execution/presentation/module and Specimen preparation; existing
`runtime/mcp_tools/mock_tools.py` dispatch; tests
`runtime/tests/integration/test_design_workspace_agent.py`.

**Interfaces:** explicit `orchestrator_design_contract.geometry_request` carries
Task 2 request schema; optional `geometry_candidates` carries a bounded list of
fully specified requests. Candidate records preserve nested `geometry_request`
and `geometry_receipt`. Legacy specs without these fields retain the old path.
`tool_adapter.generate_tool(payload: dict) -> dict` emits the current geometry-tool
result keys plus receipt; only trusted internal callers provide run output roots.

- [x] Write failing tests for schema propagation through real registered Design
  graph, new-family normalization, bounded candidate admission, state isolation,
  unknown/disabled provider, and no implicit changes to current Gyroid/BO defaults.
- [x] Implement family-specific preparation/validation; bypass legacy heuristic
  mechanical rankings for new requests. Stable candidate-ID order, unknown
  performance and null unsliced cost; keep existing LLM accept/inspect authority.
- [x] Extend decision summaries, locking/fingerprints, reports and required handoff
  fields by capability. No fake wall/cell/mass values to satisfy old required fields.
- [x] Generate final selected geometry through the registered tool and preserve
  receipt/metadata under the existing run archive. Candidate preview is distinct.
- [x] In Specimen geometry preparation verify identity, input/source/file hashes,
  final quality and checks before artifact reuse; otherwise regenerate the same
  normalized request/seed. Bad receipt must not bypass manufacturing checks.
- [x] Run registered agent graph for TPMS, spinodoid and strut requests; inspect
  final STL. Advance Specimen preparation only through geometry/check operations,
  with a fail-fast tool allowlist preventing slicing or hardware.
- [x] Run legacy Design/Specimen/module lifecycle/contract/compute regressions and
  compare candidate identity/report shape. Commit.

### Task 7: Distribution, actual LLM evidence, docs and final review

**Files:** `runtime/distribution-files.json`, `runtime/pyproject.toml`, main host
binding, `docs/gui/design_workspace.md`, existing GUI index and Design/Specimen
system references; `runtime/tests/unit/test_design_workspace_distribution.py`;
`runtime/scripts/verify_design_workspace.py` (hardware-denied offline verification).

**Interfaces:** binds `install_design_workspace` without eager numerical imports,
connections or jobs. Distribution explicitly includes shared modules, descriptors,
provider code and browser resources; add optional scientific dependency extra only
if existing dependency declarations do not cover the installed engine requirements.

- [x] Write failing packaged-resource/standalone-import tests; implement packaging
  and lazy host binding. Verify extracted wheel discovery and GUI/API assets.
- [x] Run isolated full verification script with explicit roots and hardware calls
  denied. Retain inputs, source hashes, receipts, STL, screenshots and timings in
  an untracked validation directory. Output individual failures rather than hide them.
- [x] Exercise a configured real LLM through existing AgentContext routing without
  loading/stopping models or mutating production settings. If unavailable, report
  exact blocker; deterministic graph evidence cannot substitute for LLM evidence.
- [x] Verify shared API vs agent request/mesh hashes, all fourteen providers and
  representations, Gyroid boundary cases, serial parity and artifact reuse.
- [x] Run project default suite in isolation; classify unrelated dependency and
  baseline failures without changing scientific checks to silence them.
- [x] Update usage/system docs with actual outcomes, supported parameter ranges,
  source/license notices, installation and a third-provider extension example.
- [ ] Use requesting-code-review for whole-branch review; address findings, rerun
  affected tests and use verification-before-completion before completion claims.
- [ ] Hand off isolated branch/results; integration and production application
  follow the user's selected rollout and a safe operational point. Do not claim
  the running server changed merely because the code exists in another checkout.

## Plan self-review

Catalog/common serial rule → Task 1. Geometry semantics/source scope → Tasks 2–3.
Jobs/API/persistence → Task 4. Dynamic GUI → Task 5. Registered agent, receipts and
existing tool path → Task 6. Packaging, real model evidence and docs → Task 7.
All five review-focus cases have explicit tests. Runtime numerical/resource
measurements determine documented tolerances/limits; no physical experiment or
claimed mechanical validation is part of this plan.

Status: Tasks 1–7 implemented on isolated `feat/design-workspace`; focused
verification includes actual API/registered-agent hash parity, all fourteen
providers/modes, browser evidence, extracted wheel and one configured real LLM
run. The earlier 77 dependency collection errors are resolved by isolated-environment
dependency installation: guarded `pytest --collect-only` collected 7,633 tests
without errors (exit 0, 3.03 seconds). The full suite was not executed; collection
success does not establish a green suite. The known baseline specimen golden
mismatch remains unresolved. Review findings, including N1, are addressed;
user-selected integration remains pending. No merge, push or production activation.
