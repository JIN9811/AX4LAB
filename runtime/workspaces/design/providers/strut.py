"""Explicit periodic beam graphs and exact capsule-union distance fields."""
from utils.source_identity import attest_module_source
attest_module_source(__file__)

import itertools
import numpy as np


def cell_graph(name):
    corners = np.array(list(itertools.product([0., 1.], repeat=3)))
    faces = np.array([[0,.5,.5],[1,.5,.5],[.5,0,.5],[.5,1,.5],[.5,.5,0],[.5,.5,1]])
    if name == 'simple_cubic':
        edges = [(a,b) for a,b in itertools.combinations(corners,2) if np.sum((a-b)**2)==1]
    elif name == 'bcc':
        edges = [(np.full(3,.5),b) for b in corners]
    elif name in {'fcc','octet'}:
        edges = [(a,b) for a in corners for b in faces if np.sum((a-b)**2)==.5]
        if name == 'octet':
            edges += [(a,b) for a,b in itertools.combinations(faces,2) if np.sum((a-b)**2)==.5]
    else:
        raise ValueError('Unknown beam graph')
    return np.asarray(edges)


def unique_segments(segments):
    return np.array(sorted({tuple(sorted((tuple(np.round(a,10)), tuple(np.round(b,10)))))
                            for a,b in segments if np.linalg.norm(a-b)>1e-10}))


def union_distance(grid, segments, radius, orientation):
    """Exact near-solid segment distance; truncated positive far field.

    Local segment AABBs rasterize only nearby world voxels, bounding both
    memory and work. Round caps are part of the geometry, not a mesh repair.
    """
    if len(segments)>12000:
        raise ValueError('segment count exceeds numerical resource budget')
    x,y,z=np.deg2rad(orientation)
    rx=np.array([[1,0,0],[0,np.cos(x),-np.sin(x)],[0,np.sin(x),np.cos(x)]])
    ry=np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rz=np.array([[np.cos(z),-np.sin(z),0],[np.sin(z),np.cos(z),0],[0,0,1]])
    segments=np.asarray(segments) @ (rz@ry@rx).T
    spacing=np.array(grid['spacing_mm'])
    lower=np.asarray(grid['bounds_mm'][0])
    shape=np.array(grid['shape'])
    margin=radius+2*max(spacing)
    field=np.full(grid['shape'],margin-radius)
    work=0
    for a,b in segments:
        start=np.maximum(0,np.floor((np.minimum(a,b)-margin-lower)/spacing).astype(int))
        stop=np.minimum(shape,np.ceil((np.maximum(a,b)+margin-lower)/spacing).astype(int)+1)
        if np.any(stop<=start): continue
        work+=int(np.prod(stop-start))
        if work>100_000_000:
            raise ValueError('segment voxel work exceeds numerical resource budget')
        sl=tuple(slice(int(i),int(j)) for i,j in zip(start,stop))
        delta=[grid[k][sl]-a[i] for i,k in enumerate(['world_x','world_y','world_z'])]
        ab=b-a
        t=np.clip(sum(delta[i]*ab[i] for i in range(3))/np.dot(ab,ab),0,1)
        distance=np.sqrt(sum((delta[i]-t*ab[i])**2 for i in range(3)))-radius
        np.minimum(field[sl],distance,out=field[sl])
    return field


def generate_field(grid, request):
    p=request['parameters']
    cell,diameter=p['cell_size_mm'],p['strut_diameter_mm']
    lower=np.array([grid[k].min() for k in ['x','y','z']])-diameter
    upper=np.array([grid[k].max() for k in ['x','y','z']])+diameter
    starts=np.floor(lower/cell).astype(int)
    stops=np.ceil(upper/cell).astype(int)
    cells=int(np.prod(stops-starts))
    graph=cell_graph(request['geometry_id'])
    if cells*len(graph)>20000:
        raise ValueError('tiled cells exceed numerical resource budget')
    if diameter>=cell/2:
        raise ValueError('strut diameter must be below half cell size')
    segments=unique_segments(np.concatenate([(graph+offset)*cell for offset in
        itertools.product(*(range(a,b) for a,b in zip(starts,stops))) ]))
    field=union_distance(grid,segments,diameter/2,request['orientation_deg'])
    reasons=[]
    if diameter<4*max(grid['spacing_mm']): reasons.append('resolution requires 4 voxels across diameter')
    return dict(field=field,units='mm',bounds_mm=grid['bounds_mm'],method='explicit_graph_capsule_union',
                periodic_field=True,cell_size_mm=cell,strut_diameter_mm=diameter,
                cell_edge_count=len(graph),tiled_segment_count=len(segments),junction='union of round-capped cylinders',
                validation=dict(ok=not reasons,reject_reasons=reasons,status='diameter_sampling'))
