# Installed Design providers

The installed package is metadata-discovered, never code-uploaded. Common
`workspaces.catalog` and `workspaces.fields` also support Serial Communication.
`install_design_workspace(app, paths, templates)` binds `/design` and
`/api/design/*` lazily; the host supplies private roots and the existing CPU pool.

## Add another module/provider

A third module needs no new hard-coded browser card. For example, install a
reviewed `modules/lattice_study/` containing `module.yaml`, `provider.py`,
`icon.svg`, and `geometries/study_cubic/` with the same three filenames.

```yaml
# modules/lattice_study/module.yaml
schema: ax4lab.design_module.v1
id: lattice_study
version: 1.0.0
label: Lattice Study
actions: [preview, generate]
output_kinds: [stl]
```

The module `provider.py` may follow the existing module's metadata marker.
The geometry descriptor uses `ax4lab.geometry_provider.v1`, ID `study_cubic`,
version `1.0.0`, `representations: [strut]`, `default_representation: strut`,
and typed `fields`/`defaults` (copy the reviewed Simple Cubic descriptor shape).
Set `agent_handoff: false` for manual-only providers (also the conservative default
if omitted). Only a literal boolean is accepted. The fourteen shipped providers
explicitly set it true; Design and Specimen reject manual-only providers, and
the GUI discloses the boundary. This flag is not manufacturing approval.

Module `actions` must be a nonempty unique subset of `[preview, generate]`, and
`output_kinds` must be `[stl]`. Missing/malformed/unknown actions and outputs are
excluded during discovery. Generate maps to `quality: final`; the old Preview
action remains an internal compatibility capability only. New public jobs use
final quality, default resolution 128, minimum 96 and maximum 160.
Custom executable actions are not supported. Generate-only modules support both
the workspace and agent handoff when `agent_handoff: true`. Agent PNGs render the
same final geometry; they do not require a second Preview action or STL.

Geometry metadata may declare `design_family`, `parameter_roles` (field key to
`design`, `fixed` or `numerical`), field `description`, `design_notes`,
`default_basis`, `research_sources` (`title` and HTTPS `url`), and `default_seed`.
Role keys can cover the union of all representation fields; the contract and UI
only present the active fields. Missing role means `design`. URLs are reference
metadata only and never executable provider or asset locations.

`GET /api/design/modules/{module}/geometries/{geometry}/contract?representation=...`
returns `ax4lab.geometry_input_contract.v1`, with active `parameters` including
roles/defaults and a normalized `request_template`. Other local agents can copy
that template, override inputs, call `/api/design/validate`, then `/api/design/jobs`
and poll the returned job ID. Unknown parameters and unsupported representations
are errors. Omitted stochastic seed uses its declared default; explicit zero stays
zero and required explicit null remains invalid. Color belongs to the viewer and
must not be added to geometry inputs.

Its fixed local wrapper implements `generate_field(grid, request)`:

```python
from workspaces.design.providers import strut
from workspaces.design.providers.preflight import strut as check_strut

def preflight(request):
    check_strut({**request, 'geometry_id': 'simple_cubic'})

def generate_field(grid, request):
    return strut.generate_field(grid, {**request, 'geometry_id': 'simple_cubic'})
```

This explicitly demonstrates a named study of the existing topology, not a new
scientific family. A genuinely new family needs its own independently tested
math, physical semantics and validation. Shared numerical imports belong in
`providers/` so the code-owned source inventory fingerprints them. Do not add
untracked dynamic imports. Include all new files in the positive
`distribution-files.json` wheel/sdist lists, bump provider version as appropriate,
restart workers at a safe operational point, and refresh the catalog. Use unique
descriptor IDs; invalid metadata is isolated, not silently substituted.
Installed descriptors never choose import paths or execute expressions.
The optional code-owned `preflight(request)` hook is invoked on normalized
requests by both manual and agent paths before job admission. It must be bounded,
read-only and raise `ValueError` for known invalid cross-field, sampling or work
limits; it may not change inputs. No field/mesh generation belongs in preflight.
Missing hooks imply only common schema/resource checks, never geometric validity.
Data-dependent work, topology and calibration remain pending until the actual
final mesh is verified. Relevant enabled descriptors/schemas are supplied to the
bounded decision context for the explicit candidate pool, not as search authority.

## Scientific and license scope

All fourteen supplied geometries are independent mathematical implementations.
The preserved Gyroid sheet writer is `mcp_tools/tpms_geometry.py`. New TPMS use
audited Fourier nodal approximations and locally calibrated physical sheets;
struts use unions of segment capsules; honeycombs use extruded segment bands;
Voronoi uses the bounded cell-edge one-skeleton. These are not mechanics or
manufacturing certificates. See `system/references/metamaterial_geometry_catalog.md`
in the source repository for full formulas, conventions and limitations.

Primary references include [Kumar et al. (2020)](https://doi.org/10.1038/s41524-020-0341-6)
for Spinodoid GRF (paper CC BY 4.0),
[Deshpande et al. (2001)](https://doi.org/10.1016/S0022-5096(01)00010-2)
for Octet, and [Gibson et al. (1982)](https://doi.org/10.1098/rspa.1982.0087)
for honeycombs. Publisher works supply mathematical facts only. GIBBON and
LatticeQuery were cross-checks with conflicting/restrictive license notices;
PyAuxetic is AGPL research context. None of their implementation code is bundled.
The package's own LICENSE applies to this independent implementation (currently
no open-source redistribution grant); existing vendored viewer resources retain
their bundled notices.
