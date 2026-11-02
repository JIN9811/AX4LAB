# Metamaterial geometry catalog — numerical research generators

Checked 2026-11-02. All code is an independent mathematical implementation;
no external geometry implementation was copied, no runtime downloads occur,
and no third-party source adoption notice is needed. These are research
geometries, not manufacturing or mechanical-property certificates.

## Contract and final evidence

Fourteen installed IDs use the common `ax4lab.geometry_request.v1` contract.
Coordinates/lengths are millimetres; solid fields are negative. The fixed
requested specimen is centered at the origin. Generic fields sample inverse
active XYZ rotation before world-box clipping. No provider silently changes
size, phase, seed, or removes disconnected fragments. `manufacturing_ready`
remains false. Actual binary STL is reloaded and checked for finite bounds,
positive volume, winding, watertightness and one connected surface component.
An enclosed cavity creates a separate surface shell and is conservatively
rejected even when bulk material might be connected. No self-intersection,
printability, strength, SEA, mass, or physical wall measurement is claimed.

Finite crops of periodic structures need not be connected. A different crop,
angle, seed or density can fail; no automatic seed resampling takes place.
Underresolved previews retain explicit failed provider validation. Final
requests cannot publish a receipt when that check or serialized mesh checks
fail. The common default resolution is 48 preview / 96 final, maximum 160.

## TPMS: six Fourier nodal approximations

With `X=2*pi*x/L`, and similarly for Y/Z, the independently implemented fields
are the following low-order nodal approximations, **not exact minimal surfaces**:

| ID | Scalar field |
| --- | --- |
| gyroid | sin X cos Y + sin Y cos Z + sin Z cos X |
| schwarz_p | cos X + cos Y + cos Z |
| schwarz_d | sin X sin Y sin Z + sin X cos Y cos Z + cos X sin Y cos Z + cos X cos Y sin Z |
| iwp | 2(cos X cos Y + cos Y cos Z + cos Z cos X) - cos 2X - cos 2Y - cos 2Z |
| neovius | 3(cos X + cos Y + cos Z) + 4 cos X cos Y cos Z |
| fischer_koch_s | cos 2X sin Y cos Z + cos X cos 2Y sin Z + sin X cos Y cos 2Z |

All support `sheet`, `network_positive` (`f>=iso_level`) and
`network_negative` (`f<=iso_level`). Networks have dimensionless `iso_level`
and mm `cell_size_mm`; they do not accept wall thickness. Network defaults
are L=10 mm for Schwarz-P/Neovius and L=12 mm for the other four, level=0.
At least 16 samples/cell are required for final output.

New sheets use `cell_size_mm`, `wall_thickness_mm`. Newton normal-flow
projection followed by tangential closest-point refinement produces a local
distance approximation, then the full requested wall is `distance<=wall/2`.
It is not a globally certified signed-distance field. Projection has fixed
iteration limits; nonconvergent samples remain void. Wall/cell must be <=0.15;
high-curvature Neovius often needs <=0.10. Each job performs 96 deterministic
normal-ray calibration probes (at least 64 must converge), requiring maximum
wall error <=5% of target, and at least four voxels across the target wall.
Calibration is numerical, finite-sample, and does not cover every junction.
Independent tests also intersect serialized triangles along analytically
known normals, with voxel-scale error bounds. No fabricated physical thickness
measurement is promoted into the common mesh report.

Gyroid `sheet` is the explicit compatibility exception: its original writer,
adaptive resolution, anisotropy, defect/cap parameters, z-only rotation and
STL bytes are unchanged. Its historical defaults remain L=5, wall=.8 mm;
the inherited adaptive grid resource restriction still applies.

Primary sources: Fisher et al., Data in Brief 49 (2023),
[doi:10.1016/j.dib.2023.109311](https://doi.org/10.1016/j.dib.2023.109311)
(article CC BY 4.0; official equation dataset ODC-By 1.0), and Hsieh/Valdevit,
MiniSurf (2020), [doi:10.1016/j.simpa.2020.100026](https://doi.org/10.1016/j.simpa.2020.100026)
(official archive MIT). Historical mathematical provenance: von Schnering
and Nesper [doi:10.1007/BF01313411](https://doi.org/10.1007/BF01313411),
[Schoen NASA-CR-143111](https://ntrs.nasa.gov/citations/19700020472), Neovius
(1883). Microgen GPL-3.0 is a negative regression reference only: its
asymmetric Neovius coefficient is not adopted. The implementation checks cubic
permutation symmetry and keeps Fischer-Koch S distinct from other Koch forms.

## Spinodoid

Mode `grf`; parameters `wavelength_mm` (12), `wave_count` (64),
`cone_angles_deg` ([90,90,90]), `solid_fraction` (.55), mandatory uint32 seed.
The field is `sqrt(2/N)*sum cos((2*pi/wavelength)*n_i dot x+phase_i)`.
Directions are uniform on the sphere conditioned on the UNION of enabled
double cones; angles are half-angles, zero disables an axis, enabled angles
must be >=5 degrees. Phases are uniform on [0,2*pi). Solid uses the standard
normal quantile at requested fraction, so density is an ensemble expectation,
not an exact finite-domain volume fraction. The finite domain is non-periodic.
Twelve samples/wavelength are required. At most 512 waves and 600 million
point-wave evaluations are allowed; accumulation uses one wave and 32768-point
chunks, never an N-wave by full-grid array. Seed42/defaults is tested; other
seeds can disconnect and fail without replacement.

Primary: Kumar et al., npj Computational Materials 6, 73 (2020),
[doi:10.1038/s41524-020-0341-6](https://doi.org/10.1038/s41524-020-0341-6)
(paper CC BY 4.0; authors' ML companion MIT). GIBBON formula cross-check only:
root AGPL-3.0 conflicts with file GPL footer; no source copied.

## Explicit periodic strut graphs

Mode `strut`; parameters `cell_size_mm` (10), `strut_diameter_mm` (2).
The parameter is always a diameter, never mislabeled wall thickness.
Closed conventional cell C={0,1}^3, O=center, F=six face centers:

| ID | Edges per closed cell | Periodic valence |
| --- | --- | --- |
| simple_cubic | 12 cube edges | 6 |
| bcc | 8 O-C edges, no cube frame | 8 |
| fcc | 24 C-F half-face-diagonals | corners12, face centers4 |
| octet | 24 C-F plus 12 F-F nearest neighbors | 12 |

FCC is the engineering face-diagonal-only convention, NOT an octet alias.
Tiling deduplicates shared edges. The solid is the exact near-surface minimum
point-to-segment distance <= diameter/2: round-capped cylinders are joined by
union, not assembled overlapping STL shells. Far positive distance is truncated
without changing the zero surface. Diameter must be <L/2 and span four voxels.
Limits: 20000 pre-dedup tiled edges, 12000 evaluated segments, 100 million
segment-box voxel evaluations. AABB rasterization bounds working memory.

Primary octet source: Deshpande/Fleck/Ashby (2001),
[doi:10.1016/S0022-5096(01)00010-2](https://doi.org/10.1016/S0022-5096(01)00010-2).
LatticeQuery provides naming/convention evidence only: Apache-2.0 root and
restrictive ADML topology headers conflict; no implementation copied.

## Honeycombs

Modes `extruded_wall`; fields `inclined_length_mm` l, `vertical_length_mm` h,
`angle_deg` theta signed from positive horizontal, `wall_thickness_mm` t.
Vertices: (0,0), (l cos theta,l sin theta), (l cos theta,h+l sin theta),
(0,h+2l sin theta), (-l cos theta,h+l sin theta), (-l cos theta,l sin theta).
Translations: (2l cos theta,0) and (l cos theta,h+l sin theta).
`hexagonal_honeycomb` requires positive theta, `reentrant_honeycomb` negative.
Require h+2l sin theta>0 and t<min(l,h,h+2l sin theta)/2. Tiled segment bands
use distance2D<=t/2, rounded in-plane unions, extruded in material z through
the world crop. These are full physical model dimensions, not radius fields.
Final sampling requires four voxels across wall. Limits: 1500 candidate cells,
300 million segment-plane samples; z duplicates are evaluated once when possible.

Primary: Gibson et al. (1982),
[doi:10.1098/rspa.1982.0087](https://doi.org/10.1098/rspa.1982.0087),
Masters/Evans (1996), [doi:10.1016/S0263-8223(96)00054-2](https://doi.org/10.1016/S0263-8223(96)00054-2),
Gibson/Ashby *Cellular Solids*, chapter4. Publisher copyright; geometric facts
only, no copied source, text or figures.

## Voronoi one-skeleton

Mode `strut`; `site_count`, `strut_diameter_mm`, mandatory seed. Original sites
are uniform in the central 95% of each specimen dimension. All 26 combinations
of reflections through box planes supply exterior sites. Only finite Voronoi
faces incident to an original site are retained. Each planar face is ordered
by its 2D convex hull; only consecutive boundary vertices produce segments.
Segments are slab-clipped (including outside-to-outside crossings), deduplicated,
then thickened by capsule union. No nearest-cell interiors, face triangulation
diagonals, or infinity index -1 enter the struts. Seed positions, boundary
convention and achieved density are reported. No degeneracy jitter is added.
Rotations act on the contained material-box network before world cropping.
This is non-periodic. Limits: 8..128 original sites (27 reflected sets), shared
segment work limits, diameter <smallest specimen extent/4, four voxels/diameter.
Some seeds/diameters leave tiny closed void shells and conservatively fail the
single-surface-component check. They are never filled or discarded automatically.

Primary: Boualleg/Cirkl/Weeger (2025),
[doi:10.1007/s40964-025-01274-3](https://doi.org/10.1007/s40964-025-01274-3)
(CC BY 4.0). Runtime dependency semantics:
[SciPy Voronoi](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.Voronoi.html)
(BSD-3-Clause), Qhull redistribution terms. LatticeQuery's incomplete Voronoi
script was explicitly not used.

## Provenance and reproducibility

### Supported final defaults

The following are tested with the unchanged requested 30 mm cube, zero
orientation, final resolution96 (legacy Gyroid adapts), and seed42 when needed.
These parameter defaults were selected as connected finite specimens; they are
not a promise that all alternate crops or seeds connect.

| IDs | Default representation and dimensions |
| --- | --- |
| gyroid | legacy sheet L5, target wall .8 mm; unchanged legacy controls |
| schwarz_p, iwp | sheet L10, target wall1.4 mm |
| schwarz_d | sheet L12, target wall1.4 mm |
| neovius | sheet L16, target wall1.5 mm |
| fischer_koch_s | sheet L16.666666666666668, target wall1.4 mm |
| simple_cubic, bcc, fcc, octet | strut L10, diameter2 mm |
| spinodoid | grf wavelength12, 64 waves, isotropic90-degree cones, fraction .55 |
| hexagonal_honeycomb | extruded_wall l6, h12, theta30 degrees, wall1.4 mm |
| reentrant_honeycomb | extruded_wall l6, h14, theta-30 degrees, wall1.4 mm |
| voronoi | strut 16 interior sites, diameter2 mm |

In particular, a 20 mm cube of Schwarz-D L10/wall1.2 has detached corner
pieces, spinodoid seed5/default density can disconnect, and Voronoi seed42
with 24 sites can create a tiny closed inner shell. These are explicit
regression rejection cases, not silently altered requests.

The source audit records exact official source locations and license findings
in `.superpowers/sdd/2026-11-02-design-workspace/task3-source-audit.md`.
Mathematics above was independently coded; mutable third-party repository
revisions are not runtime dependencies or adopted-code identities. Each shared
provider module attests its source at import. Common catalog fingerprints cover
all shared provider source, wrappers, descriptors, mesher and numerical package
versions; source changes require a fresh worker. Receipts preserve request,
source identity, seed, method, calibrated/sampled evidence and actual STL hash.
