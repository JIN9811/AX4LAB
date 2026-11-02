"""Audited Fourier nodal approximations, not exact minimal surfaces.

See system/references/metamaterial_geometry_catalog.md for primary sources.
The legacy Gyroid sheet writer is deliberately not replaced by this module.
"""
from utils.source_identity import attest_module_source
attest_module_source(__file__)

import numpy as np


def nodal(name, x, y, z):
    sx, sy, sz = np.sin(x), np.sin(y), np.sin(z)
    cx, cy, cz = np.cos(x), np.cos(y), np.cos(z)
    if name == 'gyroid':
        return sx*cy + sy*cz + sz*cx
    if name == 'schwarz_p':
        return cx+cy+cz
    if name == 'schwarz_d':
        return sx*sy*sz + sx*cy*cz + cx*sy*cz + cx*cy*sz
    if name == 'iwp':
        return 2*(cx*cy+cy*cz+cz*cx) - np.cos(2*x)-np.cos(2*y)-np.cos(2*z)
    if name == 'neovius':
        return 3*(cx+cy+cz)+4*cx*cy*cz
    if name == 'fischer_koch_s':
        return np.cos(2*x)*sy*cz + cx*np.cos(2*y)*sz + sx*cy*np.cos(2*z)
    raise ValueError('Unknown TPMS nodal surface')


def gradient(name, x, y, z):
    sx, sy, sz = np.sin(x), np.sin(y), np.sin(z)
    cx, cy, cz = np.cos(x), np.cos(y), np.cos(z)
    if name == 'gyroid':
        return np.array([cx*cy-sz*sx, -sx*sy+cy*cz, -sy*sz+cz*cx])
    if name == 'schwarz_p':
        return -np.array([sx, sy, sz])
    if name == 'schwarz_d':
        return np.array([cx*sy*sz+cx*cy*cz-sx*sy*cz-sx*cy*sz,
                         sx*cy*sz-sx*sy*cz+cx*cy*cz-cx*sy*sz,
                         sx*sy*cz-sx*cy*sz-cx*sy*sz+cx*cy*cz])
    if name == 'iwp':
        return np.array([-2*sx*(cy+cz)+2*np.sin(2*x), -2*sy*(cx+cz)+2*np.sin(2*y),
                         -2*sz*(cx+cy)+2*np.sin(2*z)])
    if name == 'neovius':
        return np.array([-sx*(3+4*cy*cz), -sy*(3+4*cx*cz), -sz*(3+4*cx*cy)])
    if name == 'fischer_koch_s':
        return np.array([-2*np.sin(2*x)*sy*cz-sx*np.cos(2*y)*sz+cx*cy*np.cos(2*z),
                         np.cos(2*x)*cy*cz-2*cx*np.sin(2*y)*sz-sx*sy*np.cos(2*z),
                         -np.cos(2*x)*sy*sz+cx*np.cos(2*y)*cz-2*sx*cy*np.sin(2*z)])
    raise ValueError('Unknown TPMS nodal surface')


def _project(name, phase, iterations=10):
    q = phase.copy()
    for _ in range(iterations):
        f = nodal(name, *q)
        g = gradient(name, *q)
        norm2 = np.sum(g*g, axis=0)
        step = f / np.maximum(norm2, 1e-14)
        # Bound Newton travel near stationary points; those may not converge.
        step = np.clip(step, -.4/np.sqrt(np.maximum(norm2, 1e-14)), .4/np.sqrt(np.maximum(norm2, 1e-14)))
        q -= g*step
    return q


def sheet_distance(name, xyz, cell):
    """Normal-flow projection distance in mm, locally calibrated (not global SDF)."""
    phase = np.asarray(xyz)* (2*np.pi/cell)
    q = _project(name, phase)
    # Enforce closest-point stationarity as well as the level constraint.
    # Plain normal flow overestimates distance on high-curvature nodal patches.
    for _ in range(6):
        g = gradient(name, *q)
        delta = q-phase
        tangential = delta-g*np.sum(delta*g, axis=0)/np.maximum(np.sum(g*g, axis=0), 1e-14)
        q = _project(name, q-.7*tangential, iterations=3)
    distance = np.linalg.norm(q-phase, axis=0)*cell/(2*np.pi)
    return np.where(np.abs(nodal(name, *q)) < 1e-7, distance, cell)


def _calibrate(name, cell, wall):
    # Deterministic independent surface samples; no stochastic request state.
    phases = np.random.default_rng(613).uniform(-np.pi, np.pi, (3, 96))
    q = _project(name, phases)
    g = gradient(name, *q)
    norms = np.linalg.norm(g, axis=0)
    valid = (np.abs(nodal(name, *q)) < 1e-8) & (norms > 1e-5)
    q, g, norms = q[:, valid], g[:, valid], norms[valid]
    normals, xyz = g/norms, q*cell/(2*np.pi)
    widths = []
    for sign in [-1, 1]:
        lo, hi = np.zeros(len(norms)), np.full(len(norms), wall)
        for _ in range(24):
            mid = (lo+hi)/2
            outside = sheet_distance(name, xyz+sign*normals*mid, cell) >= wall/2
            hi = np.where(outside, mid, hi)
            lo = np.where(outside, lo, mid)
        widths.append((lo+hi)/2)
    error = float(np.max(np.abs(widths[0]+widths[1]-wall))) if len(norms) else wall
    return error, int(len(norms))


def generate_field(grid, request):
    p, name = request['parameters'], request['geometry_id']
    cell, mode = p['cell_size_mm'], request['representation']
    spacing = max(grid['spacing_mm'])
    reasons = []
    if cell/spacing < 16:
        reasons.append('resolution requires at least 16 samples per cell')
    metadata = dict(periodic_field=True, approximation='Fourier nodal surface', cell_size_mm=cell)
    if mode == 'sheet':
        wall = p['wall_thickness_mm']
        if wall > .15*cell:
            raise ValueError('wall target exceeds calibrated thin-sheet range (0.15 cell)')
        if wall < 4*spacing:
            reasons.append('resolution requires at least 4 voxels across target wall')
        xyz = np.array([grid[k].ravel() for k in ['x', 'y', 'z']])
        field = np.empty(xyz.shape[1])
        for start in range(0, xyz.shape[1], 32768):
            field[start:start+32768] = sheet_distance(name, xyz[:, start:start+32768], cell)-wall/2
        error, samples = _calibrate(name, cell, wall)
        if error > .05*wall or samples < 64:
            reasons.append('normal-ray calibration exceeds five percent wall error')
        metadata.update(target_wall_thickness_mm=wall, calibration_max_error_mm=error,
                        calibration_normal_rays=samples, thickness_method='normal-flow distance with normal-ray calibration',
                        thickness_limitations='local numerical approximation; junctions and physical printed walls not measured')
        units = 'mm'
    else:
        f = nodal(name, *(grid[k]*2*np.pi/cell for k in ['x', 'y', 'z']))
        field = p['iso_level']-f if mode == 'network_positive' else f-p['iso_level']
        units = 'dimensionless'
    return dict(field=field.reshape(grid['shape']), units=units, bounds_mm=grid['bounds_mm'],
                method='tpms_'+mode, validation=dict(ok=not reasons, reject_reasons=reasons,
                status='numerical_sampling_and_calibration'), **metadata)
