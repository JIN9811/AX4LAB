from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates


@pytest.fixture
def client(tmp_path):
    from device_bridges.serial_communication.api import create_router
    from device_bridges.serial_communication.service import SerialService
    service = SerialService(tmp_path/'config.json',tmp_path/'logs',port_provider=lambda:[])
    app = FastAPI()
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2]/'web/templates'))
    app.include_router(create_router(service,templates))
    yield TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
    service.shutdown()


def test_catalog_profiles_set_and_workspace(client):
    modules = client.get('/api/serial/modules').json()['modules']
    assert {x['id'] for x in modules} == {'cas_mwii_plus','qm_indicator'}
    assert client.get('/api/serial/modules/qm_indicator/icon').status_code == 200
    p = client.post('/api/serial/profiles',json={'module_id':'cas_mwii_plus','name':'Balance'}).json()
    assert p['settings']['baudrate']==9600
    response = client.put('/api/serial/profiles/'+p['id'],json={'name':'Balance 2','revision':1})
    assert response.status_code == 200
    assert response.json()['name']=='Balance 2'
    assert client.put('/api/serial/profiles/'+p['id'],json={'name':'Stale','revision':1}).status_code == 409
    assert client.post('/api/serial/profiles/'+p['id']+'/connect').status_code == 409
    assert client.get('/serial').status_code == 200
    assert 'serial-catalog' in client.get('/serial').text
    assert client.request('DELETE','/api/serial/profiles/'+p['id'],json={'revision':2}).status_code == 422


@pytest.mark.parametrize('host,origin',[('example.org',None),('127.0.0.1','https://evil.example')])
def test_remote_host_and_cross_origin_are_denied(client,host,origin):
    headers={'host':host}
    if origin:
        headers['origin']=origin
    assert client.get('/api/serial/modules',headers=headers).status_code == 403


def test_invalid_api_payload_and_asset_path(client):
    assert client.post('/api/serial/profiles',json={'module_id':'../x'}).status_code == 404
    assert client.get('/api/serial/modules/missing/icon').status_code == 404
    assert client.get('/api/serial/recordings/missing/raw.bin').status_code == 404
    p=client.post('/api/serial/profiles',json={'module_id':'cas_mwii_plus'}).json()
    assert client.post('/api/serial/profiles/'+p['id']+'/polling',json={'enabled':'anything'}).status_code==422


def test_api_connect_measure_record_download_and_delete(tmp_path):
    from device_bridges.serial_communication.api import create_router
    from device_bridges.serial_communication.service import SerialService
    from tests.unit.test_serial_service import FakeTransport
    service=SerialService(tmp_path/'config.json',tmp_path/'logs',
        port_provider=lambda:[{'port':'/virtual/scale','device_id':'virtual','available':True}],
        transport_factory=lambda settings:FakeTransport())
    app=FastAPI();app.include_router(create_router(service))
    try:
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',123)) as c:
            p=c.post('/api/serial/profiles',json={'module_id':'cas_mwii_plus','settings':{'port':'/virtual/scale'}}).json()
            base='/api/serial/profiles/'+p['id']
            assert c.post(base+'/connect').json()['state']=='connected'
            rec=c.post(base+'/recording',json={'enabled':True}).json()
            assert c.post(base+'/read',json={'timeout_s':1}).json()['values']['weight']==8.56
            assert c.get(base+'/latest').json()['measurement']['values']['weight']==8.56
            assert c.get(base+'/events?after=0').json()['cursor']>0
            assert c.post(base+'/recording',json={'enabled':False}).json()['complete']
            assert '8.56' in c.get('/api/serial/recordings/'+rec['id']+'/measurements.csv').text
            assert c.request('DELETE',base,json={'revision':1,'confirmed':True}).status_code==409
            assert c.post(base+'/disconnect').json()['state']=='disconnected'
            assert c.request('DELETE',base,json={'revision':1,'confirmed':True}).status_code==200
    finally:
        service.shutdown()


def test_read_once_timeout_does_not_invite_http_request_replay(tmp_path):
    from device_bridges.serial_communication.api import create_router
    from device_bridges.serial_communication.service import SerialService
    from tests.unit.test_serial_service import FakeTransport

    transport = FakeTransport(reply=False)
    service = SerialService(
        tmp_path/'config.json', tmp_path/'logs',
        port_provider=lambda: [{'port': '/virtual/scale', 'device_id': 'virtual', 'available': True}],
        transport_factory=lambda settings: transport,
    )
    app = FastAPI()
    app.include_router(create_router(service))
    try:
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 123)) as c:
            p = c.post('/api/serial/profiles', json={
                'module_id': 'cas_mwii_plus', 'settings': {'port': '/virtual/scale'},
            }).json()
            base = '/api/serial/profiles/' + p['id']
            assert c.post(base + '/connect').json()['state'] == 'connected'
            response = c.post(base + '/read', json={'timeout_s': .1})

            # 408 lets Firefox replay the POST, sending another instrument request.
            # This is a downstream device timeout, not an incomplete HTTP request.
            assert response.status_code == 504
            assert response.json()['detail']['code'] == 'timeout'
            assert c.get(base + '/latest').json()['measurement'] is None
            status = c.get(base + '/status').json()
            assert status['state'] == 'connected'
            assert status['polling'] is False
            assert status['tx_bytes'] == 1
            assert transport.sent == [b'P']

            # A later, explicit read still works after a timeout releases the gate.
            transport.reply = True
            retry = c.post(base + '/read', json={'timeout_s': 1})
            assert retry.status_code == 200
            assert retry.json()['values']['weight'] == 8.56
            assert transport.sent == [b'P', b'P']
    finally:
        service.shutdown()


def test_host_registration_is_lazy_and_bridge_discovery_is_pure(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from device_bridges.serial_communication.host import install_serial_workspace
    from device_bridges.serial_communication import service
    from device_bridges.module_discovery import discover_bridge_modules
    def forbidden(*args,**kwargs):
        raise AssertionError('Service constructed on registration')
    monkeypatch.setattr(service,'SerialService',forbidden)
    install_serial_workspace(FastAPI(),SimpleNamespace(memory_root=tmp_path/'memory',log_root=tmp_path/'logs'),None)
    assert 'serial_communication' in {m.module_id for m in discover_bridge_modules()}
    assert list(tmp_path.iterdir())==[]


def test_remote_peer_is_denied(tmp_path):
    from device_bridges.serial_communication.api import create_router
    app=FastAPI();app.include_router(create_router(lambda:None))
    c=TestClient(app,base_url='http://127.0.0.1',client=('192.168.0.3',123))
    assert c.get('/api/serial/modules').status_code==403


def test_qm_model_preview_and_selected_profile_do_not_connect(client):
    preview = client.get('/serial/modules/qm_indicator/views/model')
    assert preview.status_code == 200
    assert 'data-module-id="qm_indicator"' in preview.text
    p = client.post('/api/serial/profiles', json={'module_id':'qm_indicator'}).json()
    page = client.get('/serial/modules/qm_indicator/views/model', params={'profile_id':p['id']})
    assert page.status_code == 200
    assert 'serial-page.mjs' in page.text
    status = client.get('/api/serial/profiles/'+p['id']+'/status').json()
    assert status['state'] == 'disconnected'
    assert status['rx_bytes'] == status['tx_bytes'] == 0
    assert client.get('/api/serial/profiles/'+p['id']+'/latest').json()['measurement'] is None


def test_qm_model_rejects_wrong_missing_and_remote_profiles(client):
    p = client.post('/api/serial/profiles', json={'module_id':'cas_mwii_plus'}).json()
    assert client.get('/serial/modules/qm_indicator/views/model', params={'profile_id':p['id']}).status_code == 422
    assert client.get('/serial/modules/qm_indicator/views/model', params={'profile_id':'missing'}).status_code == 404
    assert client.get('/serial/modules/qm_indicator/views/model', headers={'host':'example.org'}).status_code == 403


def test_model_preview_reads_only_catalog_and_profile_store(tmp_path, monkeypatch):
    from device_bridges.serial_communication.api import create_router
    from device_bridges.serial_communication.service import SerialService
    def forbidden(*args, **kwargs):
        raise AssertionError('Preview attempted device I/O')
    service=SerialService(tmp_path/'profiles.json',tmp_path/'logs',
                          port_provider=forbidden,transport_factory=forbidden)
    monkeypatch.setattr(service.catalog, 'protocol', forbidden)
    app=FastAPI();app.include_router(create_router(service))
    with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',123)) as c:
        assert c.get('/serial/modules/qm_indicator/views/model').status_code == 200
        assert c.get('/serial/modules/qm_indicator/views/workcell').status_code == 200
        assets='/api/serial/modules/qm_indicator/views/model/assets/'
        assert c.get(assets+'serial-page.mjs').status_code == 200
        assert c.get(assets+'vendor/three.module.js').status_code == 200
        assert c.get(assets+'%2e%2e/%2e%2e/protocol.py').status_code == 404
        assert c.get('/serial/modules/cas_mwii_plus/views/model').status_code == 404
        assert c.get(assets+'scene.json',headers={'origin':'https://example.org'}).status_code == 403
    assert not (tmp_path/'profiles.json').exists()
    assert service.sessions == {}
