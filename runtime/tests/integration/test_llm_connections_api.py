"""Connection editor API integration, with no device lifecycle or network calls."""
from copy import copy, deepcopy
import asyncio
import json

from fastapi.testclient import TestClient
import pytest
import app.main as main


@pytest.fixture
def client(tmp_path, monkeypatch):
    ctx = copy(main.controller._deps.agent_context)
    ctx.primary_backends = {k: copy(v) for k, v in ctx.primary_backends.items()}
    ctx.primary_backends['vllm']._nemoclaw_runtime = None
    ctx.model_routers = deepcopy(ctx.model_routers)
    ctx.runtime_profiles = deepcopy(ctx.runtime_profiles)
    ctx.fallback_backends = dict(ctx.fallback_backends)
    ctx.backend_fallbacks = dict(ctx.backend_fallbacks)
    monkeypatch.setattr(main.controller._deps, 'agent_context', ctx)
    monkeypatch.setattr(main, 'API_KEY_SETTINGS_PATH', tmp_path / 'api_keys.json')
    monkeypatch.setattr(main, 'LLM_CONNECTIONS_PATH', tmp_path / 'llm_connections.json', raising=False)
    monkeypatch.setattr(main, '_connection_service', None, raising=False)
    monkeypatch.setattr(main, 'API_KEY_DEFAULT_BASE_URL', ctx.primary_backends['openai']._base_url, raising=False)
    return TestClient(main.app)


def test_separate_page_has_current_mode_controls_and_main_window_link(client):
    response = client.get('/llm-connections')
    assert response.status_code == 200
    assert 'Current Mode' in response.text
    assert 'registered-model-cards' in response.text
    assert 'api-key-load-btn' in response.text
    assert 'connections-form' in response.text
    home = client.get('/').text
    assert 'href="/llm-connections"' in home
    assert 'target="ax4lab-llm-connections"' in home


def test_endpoint_save_binds_existing_key_and_old_load_button_cannot_leak_it(client):
    client.post('/api/runtime/api-key', json={'api_key': 'private-key', 'enabled': True})
    initial = client.get('/api/runtime/llm-connections')
    assert initial.status_code == 200
    data = initial.json()
    key = data['profiles']['openai']['orchestrator_endpoint']
    row = next(row for row in data['endpoints'] if row['id'] == key)
    row.pop('has_access_token', None)
    row.pop('id')
    row.update(base_url='https://different-provider.test/v1', model='another-model')
    saved = client.put(f'/api/runtime/llm-connections/endpoints/{key}', json=row)
    assert saved.status_code == 200 and saved.json()['ok']
    backend = main.controller._deps.agent_context.primary_backends['openai']
    assert backend._base_url == 'https://different-provider.test/v1'
    assert backend._api_key == ''
    loaded = client.post('/api/runtime/api-key/load', json={}).json()
    assert loaded['enabled'] is False
    assert loaded['endpoint_matches'] is False
    assert backend._api_key == ''
    assert 'private-key' not in json.dumps(saved.json())
    # Entering a new key explicitly authorizes the currently selected endpoint.
    client.post('/api/runtime/api-key', json={'api_key':'new-provider-key', 'enabled':True})
    assert backend._api_key == 'new-provider-key'
    assert client.get('/api/runtime/api-key').json()['endpoint_matches'] is True


def test_invalid_profile_and_busy_save_preserve_current_state(client, monkeypatch):
    initial = client.get('/api/runtime/llm-connections').json()
    profile = dict(initial['profiles']['vllm'])
    profile.pop('base_url', None)
    profile.update(worker_endpoint='missing')
    assert client.put('/api/runtime/llm-connections', json={'provider':'vllm', 'connection':profile}).status_code == 400
    profile['worker_endpoint'] = initial['profiles']['vllm']['worker_endpoint']
    monkeypatch.setattr(main.controller._planning_request_lock, 'locked', lambda: True)
    assert client.put('/api/runtime/llm-connections', json={'provider':'vllm', 'connection':profile}).status_code == 409
    assert client.get('/api/runtime/llm-connections').json()['profiles'] == initial['profiles']


def test_saved_connection_reloads_without_starting_models(client):
    profile = client.get('/api/runtime/llm-connections').json()['profiles']['vllm']
    profile.pop('base_url', None)
    assert client.put('/api/runtime/llm-connections/endpoints/saved-worker', json={
        'label':'Saved worker', 'provider':'vllm', 'base_url':'http://localhost:9002/v1',
        'model':'new-worker'}).status_code == 200
    profile.update(worker_endpoint='saved-worker')
    assert client.put('/api/runtime/llm-connections', json={'provider':'vllm','connection':profile}).status_code == 200
    main._connection_service = None
    restored = client.get('/api/runtime/llm-connections').json()
    assert restored['profiles']['vllm']['worker_endpoint'] == 'saved-worker'
    assert next(row for row in restored['endpoints'] if row['id'] == 'saved-worker')['base_url'] == 'http://localhost:9002/v1'


def test_stale_key_dialog_cannot_authorize_key_for_changed_endpoint(client):
    old_url = client.get('/api/runtime/api-key').json()['base_url']
    data = client.get('/api/runtime/llm-connections').json()
    key = data['profiles']['openai']['orchestrator_endpoint']
    row = next(row for row in data['endpoints'] if row['id'] == key)
    row.pop('has_access_token', None)
    row.pop('id')
    row['base_url'] = 'https://new-provider.test/v1'
    assert client.put(f'/api/runtime/llm-connections/endpoints/{key}', json=row).status_code == 200
    prior = main.API_KEY_SETTINGS_PATH.read_bytes() if main.API_KEY_SETTINGS_PATH.exists() else None
    response = client.post('/api/runtime/api-key', json={
        'api_key':'wrong-provider-secret', 'enabled':True, 'expected_base_url':old_url})
    assert response.status_code == 409
    current = main.API_KEY_SETTINGS_PATH.read_bytes() if main.API_KEY_SETTINGS_PATH.exists() else None
    assert current == prior
    assert main.controller._deps.agent_context.primary_backends['openai']._api_key == ''
    assert client.post('/api/runtime/api-key', json={'api_key':'right-provider-secret',
        'enabled':True,'expected_base_url':row['base_url']}).status_code == 200


def test_lifecycle_button_passes_endpoint_identity(client, monkeypatch):
    calls = []
    async def load(ref):
        calls.append(ref)
        return {'ok': True}
    monkeypatch.setattr(main.controller, 'load_runtime_model', load)
    response = client.post('/api/runtime/models/load', json={'endpoint_id': 'local-main'})
    assert response.status_code == 200
    assert calls == ['endpoint:local-main']


def test_endpoint_token_can_enable_api_without_legacy_global_key(client, monkeypatch):
    monkeypatch.setattr(main, '_read_openai_api_key_from_local_env', lambda: ('', 'none'))
    settings = client.get('/api/runtime/llm-connections').json()
    key = settings['profiles']['openai']['orchestrator_endpoint']
    row = next(row for row in settings['endpoints'] if row['id'] == key)
    row.pop('id')
    row.pop('has_access_token', None)
    row['access_token'] = 'endpoint-only-secret'
    assert client.put(f'/api/runtime/llm-connections/endpoints/{key}', json=row).status_code == 200
    status = client.get('/api/runtime/api-key').json()
    assert status['has_key'] is True
    assert client.post('/api/runtime/api-key/load', json={}).json()['enabled'] is True
    backend = main.controller._deps.agent_context.primary_backends['openai']
    assert backend._api_routing_enabled is True
    assert client.post('/api/runtime/api-key/unload', json={}).json()['enabled'] is False
    assert backend._api_routing_enabled is False


@pytest.mark.parametrize('retained_role', ['worker', 'fallback'])
def test_api_role_switch_keeps_global_key_bound_to_original_worker(client, retained_role):
    from backends.endpoint_routes import endpoint_token
    initial = client.get('/api/runtime/llm-connections').json()
    original = initial['profiles']['openai']['worker_endpoint']
    client.post('/api/runtime/api-key', json={'api_key': 'original-api-secret', 'enabled': True})
    assert client.put('/api/runtime/llm-connections/endpoints/another-api', json={
        'provider': 'openai', 'base_url': 'https://second-api.test/v1', 'model': 'another',
        'access_token': 'second-api-secret'}).status_code == 200
    profile = {'orchestrator_endpoint': 'another-api',
               'worker_endpoint': original if retained_role == 'worker' else 'another-api'}
    if retained_role == 'fallback':
        profile.update(orchestrator_fallback=original, worker_fallback=original)
    response = client.put('/api/runtime/llm-connections', json={'provider': 'openai', 'connection': profile})
    assert response.status_code == 200
    backend = main.controller._deps.agent_context.primary_backends['openai']
    assert endpoint_token(backend, backend._endpoint_routes[original]) == 'original-api-secret'
    assert endpoint_token(backend, backend._endpoint_routes['another-api']) == 'second-api-secret'
    main._connection_service = None
    assert client.get('/api/runtime/llm-connections').status_code == 200
    client.get('/api/runtime/api-key')
    assert endpoint_token(backend, backend._endpoint_routes[original]) == 'original-api-secret'


def test_model_lifecycle_blocks_connection_edits_and_releases_on_cancel(client, monkeypatch):
    from backends.llm_lease import LLMLeaseCoordinator
    monkeypatch.setattr(main.controller._deps.agent_context, 'llm_lease', LLMLeaseCoordinator())

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        async def load(ref):
            started.set()
            await finish.wait()
        monkeypatch.setattr(main.controller, 'load_runtime_model', load)
        service = main._llm_connections()
        job = asyncio.create_task(main.post_runtime_model_load(main.RuntimeModelRequest(endpoint_id='local-main')))
        try:
            await started.wait()
            assert service.is_busy()
            with pytest.raises(RuntimeError):
                service.save_endpoint('concurrent', {'provider': 'vllm',
                    'base_url': 'http://other.test/v1', 'model': 'other'})
            assert main.controller._deps.agent_context.llm_lease.status()['active']
        finally:
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
        assert not service.is_busy()
        assert not main.controller._deps.agent_context.llm_lease.status()['active']
    asyncio.run(scenario())
