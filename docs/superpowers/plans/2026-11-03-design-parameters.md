# Metamaterial Parameter Contracts Implementation Plan

> **For agentic workers:** Use executing-plans for coordination; bounded independent
> code areas may run in parallel. User requests minimum verification, not full suite.

**Goal:** Family-specific, evidence-backed inputs and a single final STL for GUI/API/agents.
**Architecture:** Existing descriptor catalog and numerical engine; extend input contract;
keep modular field rendering and registered compute jobs.
**Tech Stack:** Python/FastAPI/YAML, browser JavaScript/vtk.js, pytest/node/Playwright.
**Spec:** `docs/superpowers/specs/2026-11-03-design-parameters-design.md`

## Global Constraints

- No hardware actions; no changes to non-explicit legacy experimental paths.
- Defaults final/128; new workspace final jobs 96..160; old evidence immutable.
- Seeds default only when omitted; do not replace explicit zero/null.
- No new numerical dependency or unimplemented design controls.
- Color does not enter geometry requests, receipts or STL bytes.

## Review Focus

- Profile migration must not overwrite historical preview receipts.
- Representation changes must not leak sheet-only fields into network requests.
- Stochastic default seed must reach API as well as GUI; explicit values remain exact.
- Selected candidate PNG must use the identical final STL handed to Specimen.
- Source fingerprints include added contract implementation; stale workers fail closed.

## Task 1: Descriptor metadata and API contract

Files: `runtime/workspaces/design/{catalog,engine,service,api,contracts}.py`, all
installed geometry YAML descriptors; `runtime/tests/unit/test_design_input_contract.py`.
Interface: GET contract as specified; descriptor metadata keys shared with GUI.

- [x] RED: tests for 14 descriptor role maps, per-mode request templates, seed omission/
  zero/null, wrong family fields, final/128 defaults and public preview rejection.
- [x] Implement metadata validation, documented field roles/notes/source URLs and
  normalized contract templates; keep hard physical/numerical rules.
- [x] GREEN: focused new contract/API and existing geometry contract tests.

## Task 2: Single-artifact explicit agent generation

Files: `runtime/agents/design/geometry_adapter.py`,
`runtime/workspaces/design/tool_adapter.py`, focused agent/tool tests.
Consumes Task 1 default final request; produces final receipt + same-STL PNG metadata.

- [x] RED: selected generation occurs once, PNG source hash equals handed-off final
  STL hash; generate-only module supports agent, failed alternative does not erase selected.
- [x] Render final receipt directly; preserve historical low-quality compatibility only
  outside new public workspace requests; use final-only candidate images.
- [x] GREEN: focused tool and agent tests with no equipment dispatch.

## Task 3: Dynamic grouped UI, single generation and color

Files: `runtime/web/{static/design_workspace.js,static/design_workspace.css,
templates/design.html}`, `runtime/tests/js/design_workspace.test.cjs`.
Consumes roles/notes/default_seed metadata, not hardcoded geometry IDs.

- [x] RED: single final request, profile upgrade draft, metadata grouping, color validation.
- [x] Remove split preview generation; final defaults128; latest job auto display;
  render groups/compact guide; persisted color changes existing/new actors without jobs.
- [x] GREEN: node tests and isolated real browser flow including screenshot and console.

## Task 4: User docs, examples and bounded integration

Files: `docs/gui/design_workspace.md`,
`system/references/metamaterial_geometry_catalog.md`, `runtime/workspaces/design/README.md`.

- [x] Record primary source comparisons and distinction between study settings and
  project defaults; exact machine/API request example and compatibility behavior.
- [x] Generate representative final artifacts in isolated stores, inspect receipt hashes.
- [x] One bounded fresh code review; resolve material findings with regression tests.
- [x] Report checks, remaining scientific limits and deployment status accurately.

## Verification outcome — 2026-11-03

- Combined focused Python suite: **189 passed** in 131.75 s (input contracts,
  geometry contracts, service, API, wheel distribution, registered Design graph,
  and legacy geometry compatibility). Existing Pydantic field-shadow and
  NumPy/scikit-image deprecation warnings remain; no test failures.
- `node --test runtime/tests/js/design_workspace.test.cjs`: **19 passed**.
- Isolated `runtime/tests/ui/design_workspace_browser_audit.py`: passed at
  1920×1080 and 390×844; no application console/page errors. Covers profiles,
  draft migration, generated-STL auto-display/download, cancellation, module
  removal/history, camera persistence and color persistence. Software-renderer
  ReadPixels performance warnings are recorded separately.
- The same audit with `--parameters-only` generated Spinodoid and Voronoi at
  final resolution128. Both receipts are watertight and final-geometry-valid;
  downloads match receipt hashes (19,368,584 and 14,307,084 bytes respectively).
- Pixel comparison caught vtkSTLReader facet scalars overriding actor color.
  Disabling mapper scalar visibility fixed it; the pixel regression now passes
  for both stochastic shapes without creating additional generation jobs.
- Independent read-only review: no material findings; 33 input-contract tests
  independently passed. Browser color issue was subsequently found and fixed
  by the main agent's visual check.
- Local screenshots/evidence: `/tmp/ax4lab-design-parameters-browser` and
  `/tmp/ax4lab-design-parameters-stochastic`. These are not runtime dependencies.
- No all-combinations, physical manufacturing, equipment or LLM validation is
  claimed. No production server changes, merge or push were performed. Work is
  isolated on `feat/design-parameters`, based on main commit `824b2c4`.
