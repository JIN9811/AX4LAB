"""Bounded request-only checks, shared by API, agents and numerical workers.

No mesh, field arrays or stochastic realization is constructed here. These
necessary conditions are not proof of connected/valid serialized geometry.
Data-dependent segment/work, calibration and topology checks remain pending
until generation; never convert this preflight to a final validity receipt.
"""
import itertools
import math

from utils.source_identity import attest_module_source

attest_module_source(__file__)


def _spacing(request):
    return max(request["specimen_size_mm"]) / (request["resolution"] - 1)


def _sample(request, feature, samples, name):
    if request["quality"] == "final" and feature < samples * _spacing(request):
        raise ValueError(f"resolution requires {samples} voxels/samples across {name}")


def _bounds(request):
    """Exact material-space AABB of eight rotated world-crop corners."""
    import numpy as np
    x, y, z = np.deg2rad(request["orientation_deg"])
    rx = np.array([[1,0,0],[0,np.cos(x),-np.sin(x)],[0,np.sin(x),np.cos(x)]])
    ry = np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rz = np.array([[np.cos(z),-np.sin(z),0],[np.sin(z),np.cos(z),0],[0,0,1]])
    half = np.abs(rz @ ry @ rx).T @ (np.asarray(request["specimen_size_mm"]) / 2)
    return -half, half


def strut(request):
    from .strut import cell_graph
    p = request["parameters"]
    cell, diameter = p["cell_size_mm"], p["strut_diameter_mm"]
    if diameter >= cell / 2:
        raise ValueError("strut diameter must be below half cell size")
    lower, upper = _bounds(request)
    cells = math.prod(math.ceil((hi + diameter)/cell) - math.floor((lo - diameter)/cell)
                      for lo, hi in zip(lower, upper))
    if cells * len(cell_graph(request["geometry_id"])) > 20000:
        raise ValueError("tiled cells exceed numerical resource budget")
    _sample(request, diameter, 4, "diameter")


def tpms(request):
    p = request["parameters"]
    cell = p["cell_size_mm"]
    if request["representation"] == "sheet":
        wall = p["wall_thickness_mm"]
        if wall > .15 * cell:
            raise ValueError("wall target exceeds calibrated thin-sheet range (0.15 cell)")
        _sample(request, wall, 4, "target wall")
    _sample(request, cell, 16, "cell")


def spinodoid(request):
    p = request["parameters"]
    angles = p["cone_angles_deg"]
    if not any(a > 0 for a in angles):
        raise ValueError("at least one cone must be enabled")
    if any(0 < a < 5 for a in angles):
        raise ValueError("enabled cone half-angle must be at least 5 degrees")
    if request["resolution"] ** 3 * p["wave_count"] > 600_000_000:
        raise ValueError("wave accumulation exceeds numerical resource budget")
    _sample(request, p["wavelength_mm"], 12, "wavelength")


def cellular(request):
    import numpy as np
    from .cellular import honeycomb_polygon
    p = request["parameters"]
    if request["geometry_id"] == "voronoi":
        diameter = p["strut_diameter_mm"]
        if diameter >= min(request["specimen_size_mm"]) / 4:
            raise ValueError("Voronoi diameter too large for specimen")
        _sample(request, diameter, 4, "diameter")
        return
    length, height, angle = p["inclined_length_mm"], p["vertical_length_mm"], p["angle_deg"]
    if (request["geometry_id"] == "hexagonal_honeycomb" and angle <= 0 or
            request["geometry_id"] == "reentrant_honeycomb" and angle >= 0):
        raise ValueError("signed angle does not match honeycomb family")
    a, b = honeycomb_polygon(length, height, angle)[1]
    wall = p["wall_thickness_mm"]
    if wall >= min(length, height, height + 2*b) / 2:
        raise ValueError("wall thickness closes honeycomb features")
    lower, upper = _bounds(request)
    margin = 2 * max(length, height) + wall / 2
    corners = np.array(list(itertools.product(*zip(lower[:2]-margin, upper[:2]+margin))))
    basis = np.array([[2*a, a], [0, height+b]])
    ij = corners @ np.linalg.inv(basis).T
    cells = np.prod(np.ceil(ij.max(axis=0)) + 1 - np.floor(ij.min(axis=0)))
    if cells > 1500:
        raise ValueError("honeycomb cell count exceeds resource budget")
    _sample(request, wall, 4, "wall")
