"""Extruded polygon-wall honeycombs and reflected-boundary Voronoi struts."""
from utils.source_identity import attest_module_source
attest_module_source(__file__)

import itertools
import numpy as np
from scipy.spatial import ConvexHull, Voronoi
from .strut import unique_segments, union_distance


def honeycomb_polygon(length, height, angle):
    theta=np.deg2rad(angle)
    a,b=length*np.cos(theta),length*np.sin(theta)
    if abs(angle)>=85 or height+2*b<=0 or length<=0 or height<=0:
        raise ValueError('collapsed or inverted honeycomb cell')
    return np.array([[0,0],[a,b],[a,height+b],[0,height+2*b],[-a,height+b],[-a,b]])


def honeycomb_field(grid,request):
    p=request['parameters']
    length,height,angle=p['inclined_length_mm'],p['vertical_length_mm'],p['angle_deg']
    if (request['geometry_id']=='hexagonal_honeycomb' and angle<=0 or
        request['geometry_id']=='reentrant_honeycomb' and angle>=0):
        raise ValueError('signed angle does not match honeycomb family')
    polygon=honeycomb_polygon(length,height,angle)
    a,b=polygon[1]
    radius=p['wall_thickness_mm']/2
    if 2*radius>=min(length,height,height+2*b)/2:
        raise ValueError('wall thickness closes honeycomb features')
    lower=np.array([grid[k].min() for k in ['x','y']])-2*max(length,height)-radius
    upper=np.array([grid[k].max() for k in ['x','y']])+2*max(length,height)+radius
    basis=np.array([[2*a,a],[0,height+b]])
    corners=np.array(list(itertools.product(*zip(lower,upper))))
    ij=corners @ np.linalg.inv(basis).T
    starts=np.floor(ij.min(axis=0)).astype(int)
    stops=np.ceil(ij.max(axis=0)).astype(int)+1
    if np.prod(stops-starts)>1500: raise ValueError('honeycomb cell count exceeds resource budget')
    segments=[]
    for offset in itertools.product(*(range(i,j) for i,j in zip(starts,stops))):
        vertices=polygon+basis@offset
        for i in range(6):
            aa,bb=vertices[i],vertices[(i+1)%6]
            if np.all(np.maximum(aa,bb)>=lower) and np.all(np.minimum(aa,bb)<=upper):
                segments.append((aa,bb))
    segments=unique_segments(segments)
    # Distance depends only on material-plane x,y. Duplicate z samples are
    # evaluated once for unrotated/z-rotated extrusions.
    planar=not any(request['orientation_deg'][:2])
    x,y=(grid['x'][:,:,0],grid['y'][:,:,0]) if planar else (grid['x'],grid['y'])
    if len(segments)*x.size>300_000_000: raise ValueError('honeycomb voxel work exceeds resource budget')
    field=np.full(x.shape,max(length,height))
    for aa,bb in segments:
        ab=bb-aa
        t=np.clip(((x-aa[0])*ab[0]+(y-aa[1])*ab[1])/np.dot(ab,ab),0,1)
        distance=np.hypot(x-aa[0]-t*ab[0],y-aa[1]-t*ab[1])-radius
        np.minimum(field,distance,out=field)
    if planar: field=np.broadcast_to(field[:,:,None],grid['shape']).copy()
    reasons=[]
    if 2*radius<4*max(grid['spacing_mm']): reasons.append('resolution requires 4 voxels across wall')
    return dict(field=field,units='mm',bounds_mm=grid['bounds_mm'],method='extruded_segment_band_union',
                periodic_field=True,periodic_translation_vectors_mm=[basis[:,0].tolist(),basis[:,1].tolist()],
                wall_thickness_mm=2*radius,angle_deg=angle,angle_convention='signed from positive horizontal',
                junction='rounded in-plane segment union',extrusion='material z through world specimen crop',
                validation=dict(ok=not reasons,reject_reasons=reasons,status='wall_sampling'))


def clip_segment(a,b,half):
    """Slab clipping retains crossing segments even when both ends are outside."""
    lo,hi=0.,1.
    delta=b-a
    for i in range(3):
        if abs(delta[i])<1e-12:
            if abs(a[i])>half[i]+1e-9:return None
        else:
            t0,t1=sorted(((-half[i]-a[i])/delta[i],(half[i]-a[i])/delta[i]))
            lo,hi=max(lo,t0),min(hi,t1)
            if hi-lo<1e-10:return None
    return np.clip(np.array([a+lo*delta,a+hi*delta]),-half,half)


def voronoi_segments(size,count,seed):
    if not 8<=count<=128: raise ValueError('Voronoi site count exceeds resource budget')
    size=np.asarray(size,dtype=float)
    half=size/2
    seeds=np.random.default_rng(seed).uniform(-.95,.95,(count,3))*half
    # Original sites first, followed by all 26 reflected combinations.
    images=[seeds]
    for shifts in itertools.product([-1,0,1],repeat=3):
        if shifts==(0,0,0):continue
        images.append(np.column_stack([seeds[:,i] if s==0 else s*size[i]-seeds[:,i]
                                       for i,s in enumerate(shifts)]))
    diagram=Voronoi(np.concatenate(images))
    segments=[]
    for sites,indices in zip(diagram.ridge_points,diagram.ridge_vertices):
        if min(sites)>=count or -1 in indices or len(indices)<3:continue
        points=diagram.vertices[indices]
        centered=points-points.mean(axis=0)
        # A ridge is a FACE: only the ordered planar hull boundary is a strut.
        _,_,vh=np.linalg.svd(centered,full_matrices=False)
        projected=centered@vh[:2].T
        hull=ConvexHull(projected)
        vertices=points[hull.vertices]
        for i in range(len(vertices)):
            clipped=clip_segment(vertices[i],vertices[(i+1)%len(vertices)],half)
            if clipped is not None:segments.append(clipped)
    if not segments:raise ValueError('Voronoi has no contained strut edges')
    return seeds,unique_segments(segments)


def generate_field(grid,request):
    if request['geometry_id']!='voronoi':return honeycomb_field(grid,request)
    p=request['parameters']
    seeds,segments=voronoi_segments(request['specimen_size_mm'],p['site_count'],request['seed'])
    diameter=p['strut_diameter_mm']
    if diameter>=min(request['specimen_size_mm'])/4:
        raise ValueError('Voronoi diameter too large for specimen')
    field=union_distance(grid,segments,diameter/2,request['orientation_deg'])
    reasons=[]
    if diameter<4*max(grid['spacing_mm']):reasons.append('resolution requires 4 voxels across diameter')
    return dict(field=field,units='mm',bounds_mm=grid['bounds_mm'],method='voronoi_face_boundary_capsule_union',
                periodic_field=False,seed=request['seed'],site_count=len(seeds),seed_positions_mm=seeds.tolist(),
                strut_diameter_mm=diameter,segment_count=len(segments),
                boundary_scheme='26 reflected ghost-site sets; original-incident finite face edges clipped to material box',
                degeneracy_jitter='none',validation=dict(ok=not reasons,reject_reasons=reasons,status='diameter_sampling'))
