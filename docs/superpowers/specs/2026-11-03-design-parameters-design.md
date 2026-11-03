# Metamaterial parameter contracts and one-STL workflow

## Intent

Expose each implemented geometry's real degrees of freedom, documented defaults,
and fixed/numerical settings to both people and agents. Generate one high-resolution
STL and display that exact artifact. Keep the existing modular catalog and device
admission boundaries; do not invent unimplemented parameters or physical evidence.

The user requested research, design, implementation and **minimal verification in
one pass**. No intermediate approval gate or full-project test campaign is required.

## Decisions and alternatives

- Extend the installed declarative descriptors rather than hardcode family UI branches
  or introduce a new CAD engine. The current numerical degrees of freedom stay valid.
- Keep legacy preview receipts readable, but new workspace jobs and explicit Design
  Agent jobs use final geometry only. PNG viewing is a rendering of that same STL,
  not a second low-quality geometry. Legacy experimental paths without an explicit
  geometry request remain unchanged.
- Use resolution 128 by default, public final generation minimum 96 and existing
  maximum 160. Existing geometric sampling and resource checks still apply.
- Color is a browser-local viewer preference, not a geometry parameter. Standard STL
  has no portable material-color contract; changing color cannot change its hash.

## Research-grounded parameter families

TPMS sheet: cell size and physical target wall; network: cell size and dimensionless
iso level (not physical thickness). Periodic strut graphs: conventional cell edge and
full diameter. Honeycombs: inclined/vertical wall lengths, signed angle, full wall
thickness; specimen z controls extrusion crop. Spinodoid: wavelength, expected solid
fraction, three cone angles; wave count is numerical, seed is realization. Voronoi:
site count and full strut diameter; seed is realization, density is a measured output.

Each descriptor gains `parameter_roles` (key -> design/fixed/numerical), optional
field descriptions, `design_family`, `design_notes`, `default_basis`, and
`research_sources` [{title,url}]. Metadata is validated and remains discoverable.
All defaults are editable starting examples for a 30-mm crop, not paper optima.
Spinodoid research envelope rho>=0.3 and active cone>=15 degrees is advisory; existing
technical bounds are not tightened. Existing stretched hexagonal default is named
accurately, not called regular. No copying third-party source code.

## Agent API

Add GET `/api/design/modules/{module_id}/geometries/{geometry_id}/contract`, optional
`representation`. Response schema `ax4lab.geometry_input_contract.v1` includes
module/geometry/provider version, representation, `parameters` (field metadata plus
default and role), `request_template` (fully normalized final/128 request),
`research_sources`, `design_notes`, `default_basis`, `design_family` and supported
representations. Validate unknown representation/identity. Existing POST validate,
POST jobs, GET job and artifact URL complete the flow. Missing parameter values use
declared defaults; explicit values including zero are never replaced. Omitted seed
uses declared default_seed (42 for stochastic providers); explicit null stays invalid
when a seed is required. Unknown parameters remain rejected.

## UI

Use existing page/cards. Group dynamic fields into Design variables and collapsed
Fixed / numerical settings using metadata; show compact optional Parameter guide
for default basis, caveats and research links. Keep dimensions/orientation separate.
One Generate STL button and one resolution field. Automatically display completed
requested job; viewer/download use its same URL. Profile load upgrades the editable
draft to final and >=96 without rewriting old profiles/jobs. Expose viewer Color,
persist across reload, retain across mesh changes. No explanatory wall of text.

## Boundaries and evidence

No device/model service operations. Preserve old artifacts and numerical validity
checks, source identities, queue limits and cancellation. New optional schema
metadata must work for third-party providers without hardcoded family IDs.
Minimum checks: focused metadata/default/API tests, UI tests, one real mesh per
representative family in isolation, one registered-agent path verifying same-STL
render hash, browser Generate/display/color/reload. No physical tests or whole-suite
claim. Work in an isolated worktree, leave deployment explicit.
