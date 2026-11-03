"""Minimal public host only: never import the production controller."""
from dataclasses import replace
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from workspaces.design.api import create_router
from workspaces.design.service import DesignService

MODULE = 'metamaterial_unit_cell_designer'


def request(**updates):
    value = {'module_id':MODULE, 'geometry_id':'simple_cubic', 'provider_version':'1.0.0'}
    value.update(updates)
    return value


@pytest.fixture
def client(tmp_path):
    service = DesignService(tmp_path/'memory', tmp_path/'artifacts')
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    with TestClient(app, base_url='http://localhost', client=('127.0.0.1', 5000)) as client:
        yield client
    service.shutdown()


def test_public_catalog_profile_validation_and_revision_shapes(client):
    modules = client.get('/api/design/modules').json()
    assert modules['modules'][0]['id'] == MODULE
    assert '/home/' not in json.dumps(modules)
    geometries = client.get(f'/api/design/modules/{MODULE}/geometries').json()['geometries']
    assert len(geometries) == 14
    assert client.get(f'/api/design/modules/{MODULE}/icon').headers['content-type'].startswith('image/svg+xml')
    assert client.post('/api/design/modules/refresh').status_code == 200
    valid = client.post('/api/design/validate', json={'request':request()}).json()
    assert valid['request']['resolution'] == 128
    p = client.post('/api/design/profiles', json={'name':'Cubic', 'request':request()})
    assert p.status_code == 201
    p = p.json()
    assert client.get(f"/api/design/profiles/{p['id']}").json()['revision'] == 1
    assert client.put(f"/api/design/profiles/{p['id']}", json={'revision':2,'name':'Wrong','request':request()}).status_code == 409
    assert client.request('DELETE', f"/api/design/profiles/{p['id']}", json={'revision':1,'confirmed':False}).status_code == 422
    assert client.request('DELETE', f"/api/design/profiles/{p['id']}", json={'revision':1,'confirmed':True}).status_code == 200
    assert client.get('/api/design/profiles').json() == {'profiles':[]}
    assert client.put(f'/api/design/modules/{MODULE}/state', json={'revision':1,'enabled':False}).json()['revision'] == 2
    assert client.put(f'/api/design/modules/{MODULE}/state', json={'revision':1,'enabled':True}).status_code == 409


@pytest.mark.parametrize('headers', [
    {'origin':'http://evil.example'}, {'origin':'http://localhost:9999'},
    {'origin':'http://['},
    {'sec-fetch-site':'cross-site'}, {'host':'evil.example'},
])
def test_host_origin_and_fetch_site_are_enforced(client, headers):
    assert client.get('/api/design/modules', headers=headers).status_code == 403
    assert client.post('/api/design/jobs', headers=headers, json={'request':request(), 'idempotency_key':'bad'}).status_code == 403


def test_remote_peer_is_forbidden(tmp_path):
    app = FastAPI()
    app.include_router(create_router(lambda: pytest.fail('Unauthorized request touched service')))
    with TestClient(app, base_url='http://localhost', client=('192.168.1.5', 123)) as c:
        assert c.get('/api/design/modules').status_code == 403


def test_payload_limits_unknown_keys_and_identity_errors(client):
    assert client.post('/api/design/validate', json={'request':request(), 'command':'run'}).status_code == 422
    assert client.post('/api/design/validate', json={'request':request(geometry_id='unknown')}).status_code == 422
    assert client.post('/api/design/validate', content=b'x'*70000, headers={'content-type':'application/json'}).status_code == 413
    assert client.post('/api/design/validate', content='{"request":', headers={'content-type':'application/json'}).status_code == 422
    assert client.get('/api/design/jobs/missing/artifacts/stl').status_code == 404
    assert client.get('/api/design/jobs').json() == {'jobs':[]}


def test_unconfigured_compute_is_503_without_job_submission(client):
    response = client.post('/api/design/jobs', json={'request':request(), 'idempotency_key':'no-pool'})
    assert response.status_code == 503
    assert client.get('/api/design/jobs').json() == {'jobs':[]}


def test_host_registration_is_lazy_and_uses_private_paths(tmp_path):
    from types import SimpleNamespace
    from workspaces.design.host import install_design_workspace
    app = FastAPI()
    install_design_workspace(app, SimpleNamespace(memory_root=tmp_path/'memory', artifact_root=tmp_path/'artifacts'), None)
    assert not (tmp_path/'memory').exists()
    with TestClient(app, base_url='http://localhost', client=('127.0.0.1',1)) as c:
        assert c.get('/api/design/modules').status_code == 200
        assert c.post('/api/design/profiles', json={'name':'Private', 'request':request()}).status_code == 201
        assert (tmp_path/'memory/design_workspace/state.json').is_file()


def test_chunked_body_limit_cannot_be_bypassed_with_length_header(client):
    response = client.post('/api/design/validate', content=iter([b' ' * 40000, b' '*40000]),
                           headers={'content-type':'application/json', 'content-length':'1'})
    assert response.status_code == 413


def test_public_fake_worker_queue_and_cancel_contract(tmp_path):
    from concurrent.futures import Future
    import threading
    class Worker:
        def __init__(self):
            self.started = threading.Event()
            self.cancellation = None
        def submit(self, job, payload, *, timeout, cancellation):
            self.cancellation = cancellation
            self.started.set()
            return Future(), cancellation
    worker = Worker()
    service = DesignService(tmp_path/'memory', tmp_path/'artifacts', executor=worker)
    app = FastAPI()
    app.include_router(create_router(lambda:service))
    try:
        with TestClient(app, base_url='http://localhost', client=('127.0.0.1',1)) as c:
            body = {'request':request(), 'idempotency_key':'one'}
            a = c.post('/api/design/jobs', json=body).json()
            assert worker.started.wait(2)
            assert c.post('/api/design/jobs', json=body).json()['id'] == a['id']
            assert c.post('/api/design/jobs', json={**body,'request':request(resolution=96)}).status_code == 409
            b = c.post('/api/design/jobs', json={**body,'idempotency_key':'two'}).json()
            assert c.post('/api/design/jobs', json={**body,'idempotency_key':'three'}).status_code == 429
            assert c.post(f"/api/design/jobs/{b['id']}/cancel").json()['state'] == 'cancelled'
            assert c.post(f"/api/design/jobs/{a['id']}/cancel").json()['state'] == 'cancelled'
            assert worker.cancellation.is_set()
            assert c.get(f"/api/design/jobs/{a['id']}/artifacts/stl").status_code == 404
    finally:
        service.shutdown()


def test_real_api_generation_download_and_receipt_restart(tmp_path, monkeypatch):
    from utils.compute_pool import ComputePool
    from utils import compute_pool
    from utils.runtime_paths import current_paths
    private = {name:tmp_path/name for name in ('run_root','memory_root','artifact_root','output_root',
        'source_inbox_root','user_file_root','log_root')}
    paths = replace(current_paths(), **private)
    bindings = tmp_path/'bindings.json'
    bindings.write_text(json.dumps({'schema':'atr.path_bindings.v1','stores':{k:str(v) for k,v in private.items()}}))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    pool = ComputePool(1, paths=paths)
    monkeypatch.setattr(compute_pool, '_pool', pool)
    service = DesignService(paths.memory_root, paths.artifact_root)
    app = FastAPI()
    app.include_router(create_router(lambda:service))
    try:
        with TestClient(app, base_url='http://localhost', client=('127.0.0.1',123)) as c:
            body = {'request':request(quality='final',resolution=96), 'idempotency_key':'real'}
            response = c.post('/api/design/jobs', json=body)
            assert response.status_code == 202
            job = response.json()
            deadline = time.monotonic()+40
            while time.monotonic()<deadline:
                job = c.get(f"/api/design/jobs/{job['id']}").json()
                if job['state'] in {'succeeded','failed'}:
                    break
                time.sleep(.03)
            assert job['state'] == 'succeeded', job
            receipt = job['receipt']
            assert receipt['final_geometry_valid'] is True
            assert receipt['manufacturing_ready'] is False
            assert receipt['checks']['watertight'] is True
            data = c.get(job['artifact_urls']['stl'])
            assert data.status_code == 200
            assert len(data.content) == receipt['artifacts']['stl']['size_bytes']
            assert c.post('/api/design/jobs', json=body).json()['id'] == job['id']
            assert pool.status()['completed'] == 1
            assert c.post(f"/api/design/jobs/{job['id']}/cancel").json()['state'] == 'succeeded'
            slow = c.post('/api/design/jobs', json={'request':request(geometry_id='spinodoid', seed=42,
                quality='final', resolution=160), 'idempotency_key':'real-cancel'}).json()
            deadline = time.monotonic()+3
            while time.monotonic()<deadline and pool.status()['active'] == 0:
                time.sleep(.005)
            assert pool.status()['active'] == 1
            assert c.post(f"/api/design/jobs/{slow['id']}/cancel").json()['state'] == 'cancelled'
            deadline = time.monotonic()+3
            while time.monotonic()<deadline and pool.status()['active']:
                time.sleep(.01)
            assert pool.status()['active'] == 0
            assert pool.status()['failed'] == 1
            assert c.get(f"/api/design/jobs/{slow['id']}/artifacts/stl").status_code == 404
    finally:
        service.shutdown()
        pool.close()
    reloaded = DesignService(paths.memory_root, paths.artifact_root)
    try:
        assert reloaded.job(job['id'])['receipt'] == receipt
        assert reloaded.artifact(job['id'], 'stl').is_file()
    finally:
        reloaded.shutdown()


def test_removed_accepted_provider_fails_in_real_worker_without_substitution(tmp_path, monkeypatch):
    import shutil
    import threading
    from utils.compute_pool import ComputePool
    from utils.runtime_paths import current_paths
    from workspaces.design.catalog import DEFAULT_ROOT, DesignCatalog
    private = {name:tmp_path/name for name in ('run_root','memory_root','artifact_root','output_root',
        'source_inbox_root','user_file_root','log_root')}
    paths = replace(current_paths(), **private)
    bindings = tmp_path/'bindings.json'
    bindings.write_text(json.dumps({'schema':'atr.path_bindings.v1','stores':{k:str(v) for k,v in private.items()}}))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    modules = tmp_path/'modules'
    shutil.copytree(DEFAULT_ROOT, modules)
    pool = ComputePool(1, paths=paths)
    class Gate:
        ready = threading.Event()
        release = threading.Event()
        def submit(self, *args, **kwargs):
            self.ready.set()
            assert self.release.wait(3)
            return pool.submit(*args, **kwargs)
    gate = Gate()
    service = DesignService(paths.memory_root, paths.artifact_root, catalog=DesignCatalog(modules), executor=gate)
    try:
        job = service.submit(request(), idempotency_key='removed')
        assert gate.ready.wait(2)
        (modules/MODULE/'geometries/simple_cubic/provider.py').unlink()
        service.refresh()
        gate.release.set()
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            result = service.job(job['id'])
            if result['state'] == 'failed':
                break
            time.sleep(.02)
        assert result['state'] == 'failed'
        assert 'unavailable' in result['error']['message']
        assert result['request']['geometry_id'] == 'simple_cubic'
        assert 'receipt' not in result
        assert service.submit(request(), idempotency_key='removed')['id'] == job['id']
    finally:
        gate.release.set()
        service.shutdown()
        pool.close()
