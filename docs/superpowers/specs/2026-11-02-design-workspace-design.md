# Design Workspace and Metamaterial Unit Cell Designer

Status: detailed design approved by the user on 2026-11-02. Implementation pending.

## Intent and agreed direction

Add a Design Workspace to AX4LAB. Its first installed module is **Metamaterial
Unit Cell Designer**, supporting TPMS, spinodoid and other mechanical metamaterial
architectures. Operators configure and generate specimens in the workspace;
Design Agent uses the same engine and validation contract, not a second generator.

The user selected the shared-engine approach on 2026-11-02 and requested dynamic,
configuration-discovered modules like Serial Communication, add/remove support,
a common workspace rule, internet research, a public API and actual agent-driven
specimen generation. Baseline source was committed and pushed as `92f61b2` before
this design. This document records proposed implementation choices separately from
those requirements.

## Approaches

1. **Shared engine with installed, descriptor-discovered modules — selected.**
   Keep the working Gyroid generator and existing agent/tool contracts; introduce
   a common catalog, explicit geometry providers and a workspace/API facade.
   There is some adapter work, but GUI and agents cannot drift into separate math.
2. **Adopt one external application/library wholesale — not selected.** Tools
   such as Microgen and LattGen offer many geometries, but introduce their own
   configuration semantics, dependencies and licenses. They are research sources
   and possible optional providers, not a replacement for AX4LAB orchestration.

## Existing implementation and constraints

- `runtime/agents/design/agent.py` prepares candidates, validates constraints,
  produces candidate previews and commits the selected experiment specification.
- `runtime/agents/design/execution.py` owns the existing preparation, LLM decision
  and finalization graph. The registered `AgentModule`, graph/package admission,
  reports and archive identity must remain intact.
- Both candidate previews and Specimen fabrication invoke
  `geometry.generate_metamaterial_stl`. Its current implementation is in
  `runtime/mcp_tools/mock_tools.py`; despite its name it creates actual STL files.
- Gyroid mathematics are in `runtime/mcp_tools/tpms_geometry.py`, with mesh cleanup
  in `runtime/mcp_tools/mesh_quality.py`. CPU dispatch is already separated through
  `runtime/utils/compute_jobs.py` and `compute_pool.py`.
- Serial Communication discovers `modules/*/module.yaml`; its GUI renders metadata
  rather than a device-name switch. Discovery does not open ports or import device
  implementations. Its existing schema is `ax4lab.serial_device.v1`.
- Existing geometry aliases, candidate IDs, specimen IDs, bounds and loop-owned
  output paths must be covered by compatibility tests. New explicit geometry IDs
  must never silently become Gyroid or a different topology.

Non-goals: starting printers/robots/UTM, changing experiment stage order, rewriting
BO, changing active-run configuration, inventing material properties, adding an
internet plugin installer, or turning every geometry into a new agent/IDE node.
No production restart is implicit in implementation or offline verification.

## Common workspace module rule

Proposed canonical reference: `system/runtime/workspace_modules.md`. Shared Python
code belongs under `runtime/workspaces/`; this is distinct from agent and bridge
registries. A workspace module describes an interactive capability, not an
orchestration stage. Domain schemas extend the common metadata contract.

- Each trusted installed module directory has `module.yaml`, a local icon and a
  code-owned provider using a fixed convention. Metadata declares schema version,
  stable ID, version, label, defaults, typed fields, actions and output kinds.
- A workspace scans only its installed module root. An explicit catalog refresh
  discovers additions/removals; frontend catalogs/forms are generated from the
  API response. No module-name-specific branches in the workspace shell.
- Field metadata supports number/integer, enum, boolean, text and vector fields,
  units, bounds and declarative visibility conditions. Both API and frontend use
  the same validation rules; browser validation alone is not authoritative.
- YAML is parsed safely. Descriptors cannot supply Python imports, JavaScript,
  shell snippets, executable equations or remote resource URLs. Implementations
  are trusted installed code, loaded lazily only when an action requests them.
- Containment checks cover descriptors, providers and icons, including symlinks.
  Invalid/duplicate IDs are reported and excluded without breaking valid modules.
- Folder installation/removal is the executable-module mechanism. GUI offers
  catalog refresh and enable/disable controls, not upload/delete of source code.
  Disabling removes a module from new selections; it does not delete profiles,
  jobs, artifacts or past run evidence. Missing modules are shown as unavailable
  on saved profiles. Profile deletion is a separate confirmed operation.
- Accepted jobs retain a pinned module/version/config snapshot; removal cannot
  silently substitute a provider. Already-loaded provider changes require normal
  server restart. Catalog refresh is not arbitrary Python hot reload.
- Serial keeps its public schema, URLs, saved profiles and protocol behavior.
  Introduce a compatibility adapter to the common discovery/metadata primitives;
  serial-specific fields and protocol validation remain in the serial package.
  Migrate only discovery primitives with parity tests, not serial sessions/I/O.

The first design workspace module is `metamaterial_unit_cell_designer`.
Inside it, a second catalog of geometry providers follows the same discovery
principles. Adding a geometry does not require editing Design Workspace JavaScript.
The common rule is documented for future workspaces; this project does not migrate
every existing workspace or its main-page launcher to a new framework.

## Research and geometry scope

Research is a maintained source catalog, not a claim to exhaust all metamaterials.
Each source records URL/DOI, inspected revision when code is adopted, license,
parameter meanings, mathematical class and implementation/verification status.
Distinguish researched, implemented, geometry-validated and physically tested.

Primary sources inspected during the initial survey:

| Source | Relevance | Adoption constraint |
|---|---|---|
| [Microgen](https://github.com/3MAH/microgen) and [API](https://3mah.github.io/microgen-docs/microgen.shape.html) | TPMS fields, sheet/network representations, mesh generation | Repository declares GPL-3.0; no automatic code copying or dependency adoption |
| [LattGen paper](https://doi.org/10.1016/j.simpa.2024.100665) | 28 implicit lattice functions, graded and hybrid structures | MATLAB/GPL-3.0 implementation; research reference, not a required runtime |
| [Kumar et al. companion repository](https://github.com/mmc-group/inverse-designed-spinodoids) | Spinodoid design parameters and original publication | Repository is ML code; not itself the geometry generator |
| [GIBBON spinodoid generator](https://github.com/gibbonCode/GIBBON/blob/master/lib/spinodoid.m) | Gaussian random field construction and anisotropy | Inspect file/repository license before reuse; MATLAB not a new runtime requirement |
| [LatticeQuery](https://github.com/jalovisko/LatticeQuery) | CAD-based strut lattices | Apache-2.0; inspect transitive CAD dependencies before adopting |
| [MSUtils](https://github.com/DataAnalyticsEngineering/MSUtils) | Voxel lattices, TPMS, stochastic microstructures | LGPL-3.0; preserve notices if adopted |
| [PyAuxetic documentation](https://pyauxetic.readthedocs.io/_/downloads/en/stable/pdf/) | Re-entrant unit-cell parameterization | AGPL-3.0-or-later; no unreviewed source inclusion |
| [Miura geometry paper](https://doi.org/10.1073/pnas.1217998110) | Folded-shell/auxetic architectures | Research-only initial category; folding/hinge mechanics are not implied by an STL |

Proposed first executable scope, subject to geometry validation:

- TPMS-derived implicit surfaces: existing Gyroid plus Schwarz P, Schwarz D,
  I-WP, Neovius and Fischer-Koch S. Identify nodal approximations honestly;
  do not claim every trigonometric level set is an exact minimal surface.
- Spinodoid: isotropic and cone-constrained anisotropic GRF volumes. Store seed,
  wave count, wavelength and threshold/solid fraction. Mark finite stochastic
  domains non-periodic unless a separately tested periodic construction is used.
- Strut lattices: simple cubic, BCC, FCC and Octet, with explicit node/edge
  definitions and unioned junctions rather than disconnected overlapping meshes.
- Cellular/auxetic: extruded hexagonal honeycomb and re-entrant honeycomb.
- Stochastic cellular: Voronoi, with seed and explicit boundary treatment.

Plate lattices, chiral/rotating-unit auxetics, origami/kirigami, graded/hybrid
architectures and imported-domain infill stay in the source catalog for expansion;
they must not appear as working generators until separately implemented and tested.
Existing non-Gyroid helpers require an audit: a familiar name is not evidence of
correct topology. Retain versioned legacy behavior for existing run specifications
while exposing new validated providers under explicit IDs.

Proposed minimum representation matrix (implementation choice for approval): all
six initial TPMS providers expose a physical-target-thickness sheet mode and
positive/negative solid-network modes controlled by dimensionless iso-level.
Sheet calibration and its measured uncertainty are provider-specific; the existing
Gyroid path retains its exact historical mapping. Network modes report achieved
volume fraction and do not promise a target-density solver. Spinodoid initially
uses a solid/void GRF threshold, strut families use unioned solid beams, honeycombs
use finite-thickness extruded walls, and Voronoi uses a strut-network construction.
No additional sheet spinodoid, plate Voronoi or hybrid representations are required
for this first release. Providers must explicitly list supported modes.

## Scientific parameters and generation contract

Every request includes module/provider ID and version, representation, parameters,
specimen envelope in mm, orientation, resolution/quality and random seed when
applicable. Separate a single-cell view from a tiled/cropped finite specimen.

- TPMS sheet wall thickness, dimensionless field offset and solid-network density
  are different quantities. Never rename one as another. Gyroid retains its
  established physical-wall contract. Additional sheet providers need their own
  distance/calibration method and measured thickness checks before claiming mm.
- Struts use diameter/radius with an unambiguous label; honeycombs use wall
  thickness and angles; spinodoids use GRF parameters and actual resulting volume
  fraction. Do not force all families through Gyroid wall/cell-ratio constraints.
- Family descriptors carry parameter bounds and capabilities; common checks cover
  finite inputs, positive dimensions, resolution/memory budget and output bounds.
  Envelope/fixture/material constraints remain independent of geometry family.
- Generated metadata includes input hash, engine/provider version, actual bounds,
  volume, volume fraction, watertightness, component count, normals and applicable
  thickness/periodic-boundary checks. Report unchecked items explicitly. Volume
  derived from invalid/open meshes is not a validated material volume.
- Preview quality cannot establish final manufacturing validity. Final generation
  runs the common mesh/shape checks; physical printability and mechanical properties
  remain distinct from geometric validity. No invented SEA, strength or slicer mass.
- Repeating identical normalized parameters, seed and provider version must be
  reproducible. Persist resolved values, not just mutable profile references.

## Service, jobs and API

Use AX4LAB's existing FastAPI/Jinja/static frontend stack and numerical worker
boundary. The domain service imports neither the controller nor hardware bridges.
Both HTTP handlers and the registered geometry tool call that service; agents do
not perform loopback HTTP or require a browser tab.

Proposed `/api/design` resources:

- `GET /modules`, `POST /modules/refresh`, `GET /modules/{id}/icon`.
- `GET /modules/{id}/geometries` and explicit module enable/disable operations.
- Versioned `GET/POST/PUT/DELETE /profiles` operations; revision conflict detection,
  atomic persistence and confirmation on deletion.
- `POST /validate` for normalized request and applicable checks.
- `POST /jobs` for preview/final generation; `GET /jobs/{id}` for state;
  `POST /jobs/{id}/cancel`; contained artifact download endpoints.

HTTP launch returns a job ID, not a long-blocking response. Bounded CPU jobs reuse
the existing pool without passing agent contexts or registries to workers. The
builder selects conservative tested memory/resolution/queue limits and documents
them. Cancellation is cooperative; a running non-interruptible operation may finish
but cannot publish its result as a successful cancelled job. Persist job receipts;
after restart unfinished jobs are marked interrupted, not automatically rerun.

Use the existing loopback/same-origin protections, bounded payloads and contained
artifact IDs. User requests cannot nominate arbitrary filesystem output paths.
The trusted run adapter derives existing loop-owned paths. Profiles live under an
injected private memory root; manual jobs use a distinct design artifact namespace.
Neither manual generation nor saving a profile mutates the current experiment.

## Design Agent integration and Specimen handoff

1. Keep `agent.design_agent`, the existing execution graph and
   `design_candidate.v1` handoff; add a versioned nested geometry request/receipt.
2. Give the existing Design preparation/decision layer the installed, enabled,
   agent-capable geometry descriptors and their parameter schemas. LLM requests
   resolve against this catalog, not a new hardcoded geometry list.
3. Preserve the legacy Gyroid/BO path and its established defaults. New-family
   selection is explicit through the experiment design contract; merely installing
   a module must not change the active BO search space or a saved campaign.
4. Family adapters validate candidates and translate the selected parameters into
   the shared generation request. Catalog-supported manual geometries must declare
   whether they also support agent/experiment handoff; show this distinction.
5. Candidate previews use the shared engine. Selected final geometry receives a
   final-quality receipt and run-owned STL, metadata and preview artifacts. This
   can run through the existing Design finalization/tool path without a printer.
6. The Specimen geometry tool verifies request hash, run/specimen identity,
   provider version, file hash and final validation before reusing that artifact.
   If no reusable receipt exists, generate via the same service. Never reuse an
   unrelated manual preview; avoid regenerating a stochastic specimen differently.
7. Keep downstream slicing, manufacturing checks, printing authorization and
   digital-thread/archive conventions. Extend field preservation and reporting so
   new-family parameters are not discarded or displayed as fabricated Gyroid data.
8. Missing/disabled/unavailable providers return a specific resolution error for
   new jobs. Already accepted work uses its pinned provider snapshot. Unknown
   explicit new IDs must not take the current silent Gyroid fallback.

New-family schemas carry selected values plus experiment dimensions/material,
candidate/specimen identity and the immutable geometry receipt. Do not fabricate
wall thickness for a solid-network family to satisfy old required-field checks;
update those checks by declared capability while retaining legacy contracts.

The current decision layer accepts/rejects an authorized candidate pool; preserve
that authority boundary. Code constructs candidates from validated family-specific
settings and the explicit experiment contract, and the LLM inspects/selects them.
This project does not grant the model arbitrary Python/formula execution or an
unbounded design search. The selected geometry configuration must survive the
existing preview payload, candidate fingerprint, handoff and archive projections.
Explicit new-family requests cannot be discarded by legacy normalization.

New-family candidates bypass `_estimate_candidate`'s legacy mechanical/risk proxy
ranking. Their authorized pool contains geometrically feasible candidates within
the explicit experiment constraints, deterministically ordered by stable candidate
ID. The LLM selects using validated evidence and declared preferences, with unknown
mechanical performance stated as unknown. Deterministic tests select a stable
feasible candidate and label that mode. Without candidate-matched experimental or
model evidence, emit no predicted strength, acquisition score or mechanical rank.
Existing Gyroid BO and ranking behavior is not rewritten by this project.

For new-family candidates, unavailable cost estimates are null with a source/status,
not zero or a made-up Gyroid heuristic. Preserve existing legacy estimates only on
their legacy path and with their existing estimated label. Slicer mass/duration
remain authoritative after slicing; add support for pending cost checks in the
new-family handoff rather than claiming those limits already passed.

## GUI scope

Use the established AX4LAB workspace template, colors and concise English labels.
The main GUI opens Design Workspace in a separate tab. The workspace opens with
its installed module catalog; selecting Metamaterial Unit Cell Designer opens
family/geometry selection, dynamically rendered parameters, saved profiles, a 3D
preview and concise validation/artifact results. No verbose explanatory cards.

Separate Preview, Generate and Download actions. Keep dirty inputs and camera
orientation during job polling; ignore stale responses from earlier selections.
Refresh/new tabs can reload job history without creating duplicate jobs. STL export
is not printing. Large meshes are not pushed repeatedly into the browser; preview
uses an appropriately reduced asset with final-artifact access kept separate.

## Validation and completion evidence

- Catalog tests: third-party fixture module discovery without central edits,
  dynamic fields/actions, malformed metadata, duplicates, traversal, disabled and
  removed modules, retained profiles/artifacts, version changes.
- Serial parity: existing catalog/profile/API/protocol and pseudo-terminal tests;
  no physical ports opened. Verify packaged module discovery outside the checkout.
- Geometry tests: family topology, periodicity where promised, envelope/caps,
  watertightness, connectivity, finite inputs, seed repeatability, thickness
  semantics, and final STL reloading. Boundary tests include Gyroid's current
  design-space corners rather than only one visually attractive specimen.
- Compatibility: existing geometry tool contract, compute-pool dispatch, Design
  module lifecycle/package/IDE tests, candidate reports and Specimen handoff.
- GUI/API: dynamic add/remove, save/reload, generation/cancellation and artifact
  download at desktop 1920x1080 and narrow viewport. No stale preview attribution.
- Actual generation: invoke the real registered Design Agent graph in an isolated
  run, create final STL and retain its receipt/artifacts; separately exercise a
  configured LLM-backed decision without physical device tools. Report deterministic
  and LLM-backed evidence separately. Never relabel mocks as actual agent evidence.
- Exercise TPMS, spinodoid and a strut family through both the shared API and agent
  contract, plus receipt reuse at Specimen geometry preparation without slicing or
  device execution. Compare hashes/normalized inputs and fail on mismatch.
- Run the repository suite where dependencies permit; report unrelated failures
  rather than altering experimental logic to make tests green.

Implementation completion requires the executable scope above, not just catalog
entries. Document unavailable/rejected designs and measurement limitations. Hardware
printing and mechanical validation are outside the completion claim.

## Builder-owned choices and rollout

The builder may choose internal filenames, schema-validation libraries already
available, preview tessellation settings and quantitative resource limits after
measurement. Record provider math provenance and geometry-specific tolerances.
Use an isolated checkout for development and testing; do not migrate current run
data or load unreviewed third-party code into the production process. A production
restart/application step is separate from offline completion and needs an explicit
safe operational point. Update user usage docs and system/module/API references
with the implementation, including license notices for any adopted code.
