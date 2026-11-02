"""Seeded constant-wavenumber GRF following Kumar et al. (2020)."""
from utils.source_identity import attest_module_source
attest_module_source(__file__)

import numpy as np
from scipy.special import ndtri


def waves(seed, count, angles):
    angles=np.asarray(angles)
    if not np.any(angles>0): raise ValueError('at least one cone must be enabled')
    if np.any((angles>0)&(angles<5)): raise ValueError('enabled cone half-angle must be at least 5 degrees')
    if not 16<=count<=512: raise ValueError('wave count exceeds numerical resource budget')
    rng=np.random.default_rng(seed)
    accepted=[]
    total=0
    cosines=np.cos(np.deg2rad(angles))
    for _ in range(4096):
        v=rng.normal(size=(1024,3))
        v/=np.linalg.norm(v,axis=1)[:,None]
        v=v[np.any((np.abs(v)>cosines)&(angles>0),axis=1)]
        accepted.append(v)
        total+=len(v)
        if total>=count: break
    else: raise ValueError('cone sampling exhausted resource budget')
    return np.concatenate(accepted)[:count],rng.uniform(0,2*np.pi,count)


def generate_field(grid,request):
    p=request['parameters']
    count=p['wave_count']
    if int(np.prod(grid['shape']))*count>600_000_000:
        raise ValueError('wave accumulation exceeds numerical resource budget')
    directions,phases=waves(request['seed'],count,p['cone_angles_deg'])
    xyz=np.array([grid[k].ravel() for k in ['x','y','z']])
    values=np.zeros(xyz.shape[1])
    beta=2*np.pi/p['wavelength_mm']
    # One wave at a time and bounded point chunks: never allocate N x grid.
    for start in range(0,xyz.shape[1],32768):
        chunk=xyz[:,start:start+32768]
        acc=np.zeros(chunk.shape[1])
        for direction,phase in zip(directions,phases):
            acc+=np.cos(beta*(direction@chunk)+phase)
        values[start:start+32768]=acc*np.sqrt(2/count)
    threshold=float(ndtri(p['solid_fraction']))
    reasons=[]
    if p['wavelength_mm']<12*max(grid['spacing_mm']):
        reasons.append('resolution requires 12 samples per wavelength')
    return dict(field=(values-threshold).reshape(grid['shape']),units='dimensionless',bounds_mm=grid['bounds_mm'],
                method='constant_wavenumber_gaussian_random_field',periodic_field=False,seed=request['seed'],
                wavelength_mm=p['wavelength_mm'],wave_count=count,cone_angles_deg=p['cone_angles_deg'],
                target_solid_fraction=p['solid_fraction'],gaussian_threshold=threshold,
                density_interpretation='ensemble expectation, not exact finite-domain fraction',
                validation=dict(ok=not reasons,reject_reasons=reasons,status='wavelength_sampling'))
