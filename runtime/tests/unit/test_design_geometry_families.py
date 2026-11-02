"""Independent formula, graph and serialized-mesh regressions (no device IO)."""
import importlib
import importlib.util
import itertools

import numpy as np
import pytest
from scipy.optimize import brentq

from workspaces.design.catalog import DesignCatalog
from workspaces.design.engine import generate_geometry, normalize_request
from workspaces.design.meshing import create_grid

TPMS = ['gyroid', 'schwarz_p', 'schwarz_d', 'iwp', 'neovius', 'fischer_koch_s']
MODULE = 'metamaterial_unit_cell_designer'


def provider(name):
    # A missing implementation is an explicit assertion failure, not collection error.
    path = 'workspaces.design.providers.' + name
    assert importlib.util.find_spec('workspaces.design.providers') is not None, 'missing providers'
    assert importlib.util.find_spec(path) is not None, 'missing ' + name
    return importlib.import_module(path)


def request(geometry, **kw):
    return dict(module_id=MODULE, geometry_id=geometry, provider_version='1.0.0', **kw)


@pytest.mark.parametrize('name,want', zip(TPMS, [0., 3., 0., 3., 13., 0.]))
def test_tpms_origin_and_periodicity(name, want):
    # Catches wrong formula coefficients, units, and nonperiodic substitutions.
    p = provider('tpms')
    assert p.nodal(name, 0., 0., 0.) == pytest.approx(want)
    xyz = np.random.default_rng(4).uniform(-3, 3, (3, 71))
    baseline = p.nodal(name, *xyz)
    for axis in range(3):
        shifted = xyz.copy()
        shifted[axis] += 2*np.pi
        np.testing.assert_allclose(p.nodal(name, *shifted), baseline, atol=2e-14)
    numerical = [(p.nodal(name, *(xyz + np.eye(3)[i, :, None]*1e-6)) -
                  p.nodal(name, *(xyz - np.eye(3)[i, :, None]*1e-6)))/2e-6 for i in range(3)]
    np.testing.assert_allclose(p.gradient(name, *xyz), numerical, atol=2e-8)


def test_neovius_cubic_symmetry_and_tpms_not_aliases():
    p = provider('tpms')
    xyz = np.random.default_rng(15).uniform(-np.pi, np.pi, (3, 2000))
    for perm in itertools.permutations(range(3)):
        np.testing.assert_allclose(p.nodal('neovius', *xyz[list(perm)]), p.nodal('neovius', *xyz), atol=1e-13)
    signs = [p.nodal(name, *xyz)>0 for name in TPMS]
    for a, b in itertools.combinations(signs, 2):
        assert np.mean(a != b) > .10


@pytest.mark.parametrize('name', TPMS)
@pytest.mark.parametrize('mode', ['network_positive', 'network_negative'])
def test_tpms_network_real_mesh(name, mode, tmp_path):
    catalog = DesignCatalog()
    assert (MODULE, name) in catalog.geometries, catalog.errors
    receipt = generate_geometry(request(name, representation=mode, parameters={'cell_size_mm': 10},
        specimen_size_mm=[20]*3, resolution=48, quality='final'), tmp_path/name, identity={}, catalog=catalog)
    assert receipt['final_geometry_valid']
    assert .25 < receipt['volume_fraction'] < .75
    assert receipt['checks']['component_count'] == 1
    assert receipt['checks']['stl_reload'] == 'passed'
    assert receipt['provider_metadata']['periodic_field'] is True


@pytest.mark.parametrize('name', TPMS[1:])
def test_tpms_sheet_final_mesh_and_underresolution(name, tmp_path):
    catalog = DesignCatalog()
    assert (MODULE, name) in catalog.geometries
    req = request(name, parameters={'cell_size_mm': 12 if name == 'neovius' else 10, 'wall_thickness_mm': 1.2},
                  specimen_size_mm=[24 if name == 'neovius' else 18]*3, quality='final', resolution=88)
    receipt = generate_geometry(req, tmp_path/name, identity={}, catalog=catalog)
    assert .15 < receipt['volume_fraction'] < .8
    assert receipt['checks']['provider_validation']['ok']
    with pytest.raises(ValueError, match='resolution|validation'):
        generate_geometry({**req, 'resolution': 24}, tmp_path/(name+'coarse'), identity={}, catalog=catalog)


def test_sheet_physical_width_independent_normal_probe():
    p = provider('tpms')
    # Schwarz-P zero surface through (L/4,L/4,L/4), normal (1,1,1).
    # Intersections of the actual field, not the calibration metadata, must be 1.2mm apart.
    origin = np.full(3, 2.5)
    normal = np.ones(3)/np.sqrt(3)
    def f(s):
        xyz = (origin + s*normal)[:, None]
        return float(p.sheet_distance('schwarz_p', xyz, 10)[0] - .6)
    a, b = brentq(f, -1., 0.), brentq(f, 0., 1.)
    assert b-a == pytest.approx(1.2, abs=.005)


@pytest.mark.parametrize('name,count,degrees', [('simple_cubic',12,[6]), ('bcc',8,[8]),
                                               ('fcc',24,[4,12]), ('octet',36,[12])])
def test_strut_graph_edges_and_periodic_valence(name, count, degrees):
    p = provider('strut')
    segments = p.cell_graph(name)
    assert len(segments) == count
    assert len({tuple(sorted(map(tuple,e))) for e in segments}) == count
    # Count incidents in a tiled 3x3x3 graph at strictly interior crystallographic nodes.
    edges = set()
    for offset in itertools.product(range(3), repeat=3):
        for a,b in segments:
            edges.add(tuple(sorted((tuple(a+offset),tuple(b+offset)))))
    degree = {}
    for a,b in edges:
        assert a != b
        for v in [a,b]: degree[v] = degree.get(v,0)+1
    assert sorted(set(d for v,d in degree.items() if all(.9<t<2.1 for t in v))) == degrees


@pytest.mark.parametrize('name', ['simple_cubic','bcc','fcc','octet'])
def test_strut_joined_mesh_diameter_and_resolution(name, tmp_path):
    catalog = DesignCatalog()
    assert (MODULE,name) in catalog.geometries
    req = request(name, parameters={'cell_size_mm':10,'strut_diameter_mm':2},
                  specimen_size_mm=[20]*3, resolution=64, quality='final')
    receipt = generate_geometry(req,tmp_path/name,identity={},catalog=catalog)
    assert .03 < receipt['volume_fraction'] < .65
    assert receipt['checks']['component_count'] == 1
    assert receipt['provider_metadata']['strut_diameter_mm'] == 2
    with pytest.raises(ValueError,match='resolution|validation'):
        generate_geometry({**req,'resolution':16},tmp_path/(name+'coarse'),identity={},catalog=catalog)


def test_sc_diameter_on_midbeam_and_resource_budget():
    p=provider('strut')
    req=normalize_request(request('simple_cubic',parameters={'cell_size_mm':10,'strut_diameter_mm':2},
                                 specimen_size_mm=[20]*3,resolution=81),DesignCatalog())
    grid=create_grid(req)
    field=p.generate_field(grid,req)['field']
    # x=5 midway on x beam, z=0, y=+/-1 are cylinder surfaces, y=1.25 void.
    assert field[60,44,40] == pytest.approx(0,abs=1e-12)
    assert field[60,36,40] == pytest.approx(0,abs=1e-12)
    assert field[60,45,40] > 0
    req['parameters']['cell_size_mm']=.1
    with pytest.raises(ValueError,match='budget|cells'):
        p.generate_field(grid,req)


def test_spinodoid_seed_and_cone_statistics():
    p=provider('spinodoid')
    directions,phases=p.waves(5,512,[15,0,0])
    assert np.all(np.abs(directions[:,0]) >= np.cos(np.deg2rad(15)))
    assert np.mean(directions[:,0]**2) > .95
    assert np.mean(directions[:,1]**2) < .03
    iso,_=p.waves(5,512,[90,90,90])
    np.testing.assert_allclose(np.mean(iso**2,axis=0),1/3,atol=.04)
    req=normalize_request(request('spinodoid',seed=5,resolution=32),DesignCatalog())
    grid=create_grid(req)
    a=p.generate_field(grid,req)
    b=p.generate_field(grid,req)
    assert np.array_equal(a['field'],b['field'])
    c=p.generate_field(grid,{**req,'seed':6})
    assert np.mean((a['field']<0)!=(c['field']<0)) > .2
    assert a['periodic_field'] is False
    assert .35 < np.mean(a['field']<0) < .75


def test_spinodoid_final_mesh_and_invalid_cones(tmp_path):
    catalog=DesignCatalog()
    assert (MODULE,'spinodoid') in catalog.geometries
    receipt=generate_geometry(request('spinodoid',seed=42,quality='final',resolution=96),
                              tmp_path/'spin',identity={},catalog=catalog)
    assert .35 < receipt['volume_fraction'] < .75
    req=normalize_request(request('spinodoid',seed=5,parameters={'cone_angles_deg':[0,0,0]}),catalog)
    with pytest.raises(ValueError,match='cone'):
        provider('spinodoid').generate_field(create_grid(req),req)


@pytest.mark.parametrize('name,angle', [('hexagonal_honeycomb',30),('reentrant_honeycomb',-30)])
def test_honeycomb_angle_and_full_wall_width(name,angle):
    p=provider('cellular')
    polygon=p.honeycomb_polygon(4,8,angle)
    assert polygon.shape==(6,2)
    assert polygon[1,0] == pytest.approx(2*np.sqrt(3))
    assert polygon[1,1] == pytest.approx(2 if angle>0 else -2)
    assert polygon[3,1] == pytest.approx(12 if angle>0 else 4)
    # Signed reentrant ribs must be geometrically distinct, not label aliases.
    other=p.honeycomb_polygon(4,8,-angle)
    assert not np.allclose(polygon,other)
    req=normalize_request(request(name,resolution=61,specimen_size_mm=[12]*3,
        parameters={'inclined_length_mm':4,'vertical_length_mm':8,'angle_deg':angle,'wall_thickness_mm':1.2}),DesignCatalog())
    grid=create_grid(req)
    field=p.generate_field(grid,req)['field']
    # At the middle of the vertical wall, numerical interpolation locates +/-t/2.
    x=2*np.sqrt(3)
    axis=np.linspace(-6,6,61)
    line=field[:,50,30]  # y=4, away from the inclined joints
    right=brentq(lambda s: np.interp(s,axis,line),x,x+1)
    left=brentq(lambda s: np.interp(s,axis,line),x-1,x)
    assert right-left==pytest.approx(1.2,abs=.02)


@pytest.mark.parametrize('name', ['hexagonal_honeycomb','reentrant_honeycomb','voronoi'])
def test_cellular_final_real_mesh(name,tmp_path):
    catalog=DesignCatalog()
    assert (MODULE,name) in catalog.geometries
    req=request(name,quality='final',resolution=96,**({'seed':42} if name=='voronoi' else {}))
    receipt=generate_geometry(req,tmp_path/name,identity={},catalog=catalog)
    assert .03<receipt['volume_fraction']<.7
    assert receipt['checks']['component_count']==1


def test_voronoi_edges_are_face_boundaries_contained_and_seeded():
    p=provider('cellular')
    seeds,segments=p.voronoi_segments([20]*3,12,42)
    again,edges=p.voronoi_segments([20]*3,12,42)
    np.testing.assert_array_equal(seeds,again)
    np.testing.assert_array_equal(segments,edges)
    assert np.max(np.abs(segments))<=10+1e-9
    assert len(segments)>24
    assert not np.allclose(seeds,p.voronoi_segments([20]*3,12,43)[0])
    # Each interior Voronoi edge midpoint is equidistant to >=3 original sites.
    # An invented face diagonal would have only 2 nearest sites.
    tested=0
    for midpoint in segments.mean(axis=1):
        if np.max(np.abs(midpoint))>=9.999: continue
        distances=np.linalg.norm(seeds-midpoint,axis=1)
        assert np.count_nonzero(np.isclose(distances,distances.min(),atol=1e-7))>=3
        tested+=1
    assert tested>10


def test_voronoi_segment_clip_handles_crossing_and_honeycomb_collapse():
    p=provider('cellular')
    np.testing.assert_allclose(p.clip_segment(np.array([-20.,0,0]),np.array([20.,0,0]),np.array([10.,10,10])),[[-10,0,0],[10,0,0]])
    assert p.clip_segment(np.array([-20.,15,0]),np.array([20.,15,0]),np.array([10.,10,10])) is None
    with pytest.raises(ValueError,match='collapsed|inverted'):
        p.honeycomb_polygon(4,2,-45)


@pytest.mark.parametrize('name',TPMS[1:])
def test_sheet_serialized_width_on_analytic_normal(name,tmp_path):
    import trimesh
    # Hand-derived nodal roots and normals, independent of provider projection.
    if name in ['schwarz_p','neovius']:
        origin=np.full(3,2.5); normal=np.ones(3)/np.sqrt(3)
    elif name=='iwp':
        origin=np.array([0.,0.,np.arccos(1-np.sqrt(6)/2)*10/(2*np.pi)]); normal=np.array([0.,0.,1.])
    else:
        origin=np.zeros(3); normal=np.ones(3)/np.sqrt(3)
    p=provider('tpms')
    def f(s):return float(p.sheet_distance(name,(origin+s*normal)[:,None],10)[0]-.4)
    assert brentq(f,0,.8)-brentq(f,-.8,0)==pytest.approx(.8,abs=.008)
    # Sample actual serialized triangles crossing this ray using an independent
    # Moller-Trumbore calculation (no provider helper or mesh proximity dependency).
    from workspaces.design.meshing import mesh_field
    req=normalize_request(request(name,parameters={'cell_size_mm':10,'wall_thickness_mm':.8},
                                 specimen_size_mm=[12]*3,resolution=88),DesignCatalog())
    grid=create_grid(req)
    mesh_field(grid,p.generate_field(grid,req),tmp_path/'sheet.stl')
    triangles=trimesh.load_mesh(tmp_path/'sheet.stl').triangles
    e1,e2=triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]
    h=np.cross(np.broadcast_to(normal,e2.shape),e2)
    determinant=np.einsum('ij,ij->i',e1,h)
    keep=np.abs(determinant)>1e-10
    e1,e2,h,determinant,triangles=e1[keep],e2[keep],h[keep],determinant[keep],triangles[keep]
    s=origin-triangles[:,0]
    u=np.einsum('ij,ij->i',s,h)/determinant
    q=np.cross(s,e1)
    v=q@normal/determinant
    distance=np.einsum('ij,ij->i',e2,q)/determinant
    hits=distance[(u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)]
    left=hits[(hits<0)&(hits>-.8)].max()
    right=hits[(hits>0)&(hits<.8)].min()
    assert right-left==pytest.approx(.8,abs=.5*12/87)


def test_disconnected_crop_and_random_sample_fail_without_receipt(tmp_path):
    catalog=DesignCatalog()
    cases=[request('schwarz_d',parameters={'cell_size_mm':10,'wall_thickness_mm':1.2},
                   specimen_size_mm=[20]*3,resolution=72,quality='final'),
           request('spinodoid',seed=5,resolution=64,quality='final')]
    for i,req in enumerate(cases):
        dest=tmp_path/str(i)
        with pytest.raises(ValueError,match='disconnected'):
            generate_geometry(req,dest,identity={},catalog=catalog)
        assert not (dest/'receipt.json').exists()


@pytest.mark.parametrize('name,params', [('spinodoid',{'wave_count':513}),('voronoi',{'site_count':129}),
    ('bcc',{'strut_diameter_mm':-1}),('neovius',{'wall_thickness_mm':float('nan')}),
    ('reentrant_honeycomb',{'angle_deg':30})])
def test_family_schema_rejects_invalid_values(name,params):
    with pytest.raises(ValueError):
        normalize_request(request(name,parameters=params,seed=42),DesignCatalog())


@pytest.mark.parametrize('name',TPMS+['simple_cubic','bcc','fcc','octet','spinodoid','hexagonal_honeycomb','reentrant_honeycomb','voronoi'])
def test_descriptor_defaults_support_real_final_output(name,tmp_path):
    receipt=generate_geometry(request(name,quality='final',seed=42 if name in ['spinodoid','voronoi'] else None),
                              tmp_path/name,identity={},catalog=DesignCatalog())
    assert receipt['final_geometry_valid'] and .02<receipt['volume_fraction']<.85


@pytest.mark.parametrize('name,params,mode', [('schwarz_p',{'cell_size_mm':10,'wall_thickness_mm':1.2},'sheet'),
    ('schwarz_p',{'cell_size_mm':10},'network_positive'),('octet',{'cell_size_mm':10,'strut_diameter_mm':2},'strut'),
    ('hexagonal_honeycomb',{},'extruded_wall'),('spinodoid',{},'grf'),('voronoi',{},'strut')])
def test_field_volume_coarse_fine_convergence(name,params,mode):
    catalog=DesignCatalog()
    p=provider('tpms' if name=='schwarz_p' else 'strut' if name=='octet' else 'spinodoid' if name=='spinodoid' else 'cellular')
    fractions=[]
    for resolution in [40,80]:
        req=normalize_request(request(name,parameters=params,representation=mode,resolution=resolution,
                                      seed=42 if name in ['spinodoid','voronoi'] else None),catalog)
        result=p.generate_field(create_grid(req),req)
        fractions.append(np.mean(result['field']<0))
    assert abs(fractions[1]-fractions[0])<.035


@pytest.mark.parametrize('name',TPMS)
@pytest.mark.parametrize('mode',['network_positive','network_negative'])
def test_tpms_network_defaults(name,mode,tmp_path):
    r=generate_geometry(request(name,representation=mode,quality='final'),tmp_path/name,identity={},catalog=DesignCatalog())
    assert r['final_geometry_valid'] and .2<r['volume_fraction']<.8


@pytest.mark.parametrize('name', ['spinodoid','hexagonal_honeycomb','reentrant_honeycomb','voronoi'])
def test_remaining_families_underresolved_final_rejected(name,tmp_path):
    req=request(name,resolution=16,quality='final',seed=42 if name in ['spinodoid','voronoi'] else None)
    with pytest.raises(ValueError,match='validation|resolution'):
        generate_geometry(req,tmp_path/name,identity={},catalog=DesignCatalog())
    assert not (tmp_path/name/'receipt.json').exists()


def test_additional_numerical_resource_rejections():
    # Admission must fail before allocating an N-wave x full-grid array.
    spin=provider('spinodoid')
    req=normalize_request(request('spinodoid',seed=42,resolution=160,parameters={'wave_count':512}),DesignCatalog())
    with pytest.raises(ValueError,match='budget'):
        spin.generate_field({'shape':(160,160,160)},req)
    req=normalize_request(request('hexagonal_honeycomb',parameters={'inclined_length_mm':.1,
        'vertical_length_mm':.1,'wall_thickness_mm':.1}),DesignCatalog())
    with pytest.raises(ValueError,match='closes|budget'):
        provider('cellular').generate_field(create_grid(req),req)


def test_voronoi_closed_void_shell_remains_a_rejection(tmp_path):
    with pytest.raises(ValueError,match='disconnected'):
        generate_geometry(request('voronoi',seed=42,parameters={'site_count':24},quality='final'),
                          tmp_path/'void',identity={},catalog=DesignCatalog())
    assert not (tmp_path/'void'/'receipt.json').exists()


@pytest.mark.parametrize('name,cell,wall', [('schwarz_p',10,2),('neovius',12,1.4)])
def test_uncalibrated_sheet_cannot_claim_final_thickness(name,cell,wall,tmp_path):
    with pytest.raises(ValueError,match='calibrat|validation'):
        generate_geometry(request(name,parameters={'cell_size_mm':cell,'wall_thickness_mm':wall},
                                  specimen_size_mm=[20]*3,quality='final'),
                          tmp_path/name,identity={},catalog=DesignCatalog())
    assert not (tmp_path/name/'receipt.json').exists()
