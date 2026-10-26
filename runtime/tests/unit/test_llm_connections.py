"""Endpoint registrations affect real requests without crossing credential boundaries."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from app.llm_connections import EndpointRecord, LLMConnections
from backends.model_router import ModelRouter
from backends.openai_client import OpenAIBackend
from backends.vllm_client import VLLMBackend


class ManagedBoundary:
    """Only service resolution is allowed; tests never provision a model."""
    def __init__(self):
        self._models = {key: SimpleNamespace(deployment='deployment-' + key)
                        for key in ('main-server', 'worker-server', 'spare-server')}
        self.resolutions = []

    async def base_url_for_model(self, target):
        self.resolutions.append(target)
        return 'http://' + target + '.test:31000/v1'

    async def ensure_model(self, target):
        raise AssertionError('Registration and probes must never prepare a deployment')

    async def load_model(self, target):
        raise AssertionError('Registration and probes must never start a deployment')

    async def unload_model(self, target):
        raise AssertionError('Removing a registration must never stop a deployment')


def record(key, *, provider='vllm', url='http://extra.test/v1', model='extra-model',
           token=None, management_id=''):
    return EndpointRecord(id=key, label=key, provider=provider, base_url=url, model=model,
        access_token=token, management_id=management_id,
        capabilities={'text': True, 'vision': True}).model_dump()


def profile(main='local-main', worker='local-worker', **overrides):
    return dict(orchestrator_endpoint=main, worker_endpoint=worker,
                orchestrator_fallback='', worker_fallback='', **overrides)


def make_service(tmp_path, *, busy=False, managed=False):
    manager = ManagedBoundary() if managed else None
    clients = {
        'openai': OpenAIBackend(base_url='https://cloud.test/v1', api_key='cloud-secret'),
        'vllm': VLLMBackend(base_url='http://localhost:8000/v1', api_key='local-secret',
                            nemoclaw_runtime=manager),
    }
    clients['openai']._endpoint_routes = {
        'api-main': record('api-main', provider='openai', url='https://cloud.test/v1', model='api-model')}
    clients['vllm']._endpoint_routes = {
        'local-main': record('local-main', url='http://localhost:8000/v1', model='large',
                             management_id='main-server' if managed else ''),
        'local-worker': record('local-worker', url='http://old-worker:8000/v1', model='small',
                               token='worker-secret', management_id='worker-server' if managed else ''),
    }
    routers = {provider: ModelRouter({'models': {
        'orchestrator': {'primary': 'endpoint:' + main},
        'worker': {'primary': 'endpoint:' + worker}},
        'task_routes': {'orchestrator_plan': 'orchestrator', 'design_reasoning': 'worker'}})
        for provider, main, worker in [('openai', 'api-main', 'api-main'),
                                       ('vllm', 'local-main', 'local-worker')]}
    ctx = SimpleNamespace(primary_backends=clients, model_routers=routers,
        runtime_profiles={'openai': {}, 'vllm': {}}, active_backend='vllm', model_router=routers['vllm'])
    return LLMConnections(ctx, tmp_path / 'llm_connections.json', busy=lambda: busy), ctx


def transport(monkeypatch, responder):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kw: real(transport=httpx.MockTransport(responder), **kw))


async def test_save_persists_routes_tokens_and_private_permissions(tmp_path, monkeypatch):
    service, ctx = make_service(tmp_path)
    service.save_endpoint('other', record('other', url='http://localhost:9000/v1',
                                         model='new-small', token='new-local-secret'))
    service.save('vllm', profile('other', 'other'))
    assert ctx.model_routers['vllm'].select('design_reasoning').primary == 'endpoint:other'
    assert ctx.model_routers['vllm'].select('design_reasoning').fallback is None
    assert 'new-local-secret' not in json.dumps(service.public())
    assert 'cloud-secret' not in json.dumps(service.public())
    restored, restored_ctx = make_service(tmp_path)
    restored.load()
    requests = []
    def respond(request):
        requests.append((str(request.url), json.loads(request.content)['model'], request.headers.get('authorization')))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Connected'}}]})
    transport(monkeypatch, respond)
    await restored_ctx.primary_backends['vllm'].complete(model='endpoint:other', system_prompt='', user_prompt='hello')
    assert requests == [('http://localhost:9000/v1/chat/completions', 'new-small', 'Bearer new-local-secret')]
    assert restored_ctx.model_routers['vllm'].select('orchestrator_plan').primary == 'endpoint:other'
    assert json.loads(service.path.read_text())['schema'] == 'llm_connections.v2'
    assert service.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('url', ['file:///tmp/key', 'http://user:password@host/v1',
    'https://host/v1?key=secret', 'https://host/v1#key', 'https://host:99999/v1',
    'https://host/v1/chat/completions'])
def test_invalid_endpoint_does_not_mutate_runtime_or_file(tmp_path, url):
    service, ctx = make_service(tmp_path)
    before = service.public()
    with pytest.raises(ValueError):
        service.save_endpoint('api-main', {**record('api-main', provider='openai'), 'base_url': url})
    assert service.public() == before
    assert ctx.primary_backends['openai']._base_url == 'https://cloud.test/v1'
    assert not service.path.exists()


def test_endpoint_change_clears_old_credential_and_busy_refuses_save(tmp_path):
    service, ctx = make_service(tmp_path)
    service.save_endpoint('api-main', record('api-main', provider='openai', url='https://another.test/v1'))
    from backends.endpoint_routes import endpoint_token
    backend = ctx.primary_backends['openai']
    assert not endpoint_token(backend, backend._endpoint_routes['api-main'])
    service, ctx = make_service(tmp_path, busy=True)
    before = service.path.read_bytes()
    with pytest.raises(RuntimeError, match='idle'):
        service.save('vllm', profile('local-main', 'local-main'))
    with pytest.raises(RuntimeError, match='idle'):
        service.save_endpoint('extra', record('extra'))
    assert service.path.read_bytes() == before
    assert ctx.primary_backends['vllm']._base_url == 'http://localhost:8000/v1'


async def test_probe_uses_selected_endpoint_without_save_prepare_or_fallback(tmp_path, monkeypatch):
    service, ctx = make_service(tmp_path, managed=True)
    requests = []
    def respond(request):
        requests.append((str(request.url), json.loads(request.content), request.headers.get('authorization'),
                         request.extensions['timeout']))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Connected'}}]})
    transport(monkeypatch, respond)
    draft = profile('local-main', 'local-worker')
    draft['worker_fallback'] = 'local-main'
    result = await service.probe('vllm', draft, 'worker')
    assert result['ok'] and result['reply'] == 'Connected'
    assert result['endpoint_id'] == 'local-worker'
    assert len(requests) == 1
    assert requests[0][0] == 'http://worker-server.test:31000/v1/chat/completions'
    assert requests[0][1]['model'] == 'small'
    assert requests[0][1]['max_tokens'] == 128
    assert requests[0][2] == 'Bearer worker-secret'
    assert requests[0][3]['read'] == 60
    assert ctx.primary_backends['vllm']._base_url == 'http://localhost:8000/v1'
    assert service.public()['profiles']['vllm']['worker_fallback'] == ''
    assert not service.path.exists()


@pytest.mark.parametrize('status,content', [(401, 'worker-secret'), (200, ''), (200, None)])
async def test_probe_errors_and_empty_replies_are_not_success(tmp_path, monkeypatch, status, content):
    service, _ = make_service(tmp_path)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={'choices': [{'message': {'content': content}}]})
    transport(monkeypatch, respond)
    selected = profile()
    selected['worker_fallback'] = 'local-main'
    result = await service.probe('vllm', selected, 'worker')
    assert result['ok'] is False
    assert len(requests) == 1
    assert 'worker-secret' not in json.dumps(result)


async def test_probe_timeout_is_reported_without_saving_or_fallback(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    def timeout(request):
        raise httpx.ReadTimeout('private server information', request=request)
    transport(monkeypatch, timeout)
    result = await service.probe('vllm', profile(), 'worker')
    assert not result['ok'] and '60 seconds' in result['message']
    assert 'private server information' not in json.dumps(result)
    assert not service.path.exists()


async def test_managed_and_custom_endpoint_assignment_preserves_lifecycle_identity(tmp_path):
    service, ctx = make_service(tmp_path, managed=True)
    client = ctx.primary_backends['vllm']
    manager = client._nemoclaw_runtime
    service.save_endpoint('custom', record('custom', model='small', url='http://custom.test/v1'))
    service.save('vllm', profile('custom', 'custom'))
    assert await client._base_url_for_model('endpoint:custom') == 'http://custom.test/v1'
    assert manager.resolutions == []
    service.save('vllm', profile())
    assert client._nemoclaw_runtime is manager
    assert await client._base_url_for_model('endpoint:local-worker') == 'http://worker-server.test:31000/v1'
    assert manager.resolutions == ['worker-server']


async def test_saving_api_keeps_other_local_endpoint_url_after_restore(tmp_path):
    service, _ = make_service(tmp_path)
    service.save_endpoint('new-api', record('new-api', provider='openai', url='https://new-cloud.test/v1'))
    service.save('openai', profile('new-api', 'new-api'))
    restored, ctx = make_service(tmp_path)
    restored.load()
    assert ctx.primary_backends['openai']._base_url == 'https://new-cloud.test/v1'
    assert await ctx.primary_backends['vllm']._base_url_for_model('endpoint:local-worker') == 'http://old-worker:8000/v1'
    assert restored.public()['profiles']['vllm']['worker_endpoint'] == 'local-worker'


@pytest.mark.parametrize('data', [[], None, {'profiles': []}, {'profiles': None},
    {'schema': 'unknown', 'profiles': {}},
    {'schema': 'llm_connections.v2', 'profiles': {}, 'endpoints': {}},
    {'schema': 'llm_connections.v2', 'profiles': {}, 'endpoints': []}])
def test_malformed_settings_leave_all_defaults_intact(tmp_path, data):
    service, ctx = make_service(tmp_path)
    before = deepcopy(service.public())
    service.path.write_text(json.dumps(data))
    stored = service.path.read_bytes()
    service.load()
    assert service.load_error
    after = service.public()
    assert after['endpoints'] == before['endpoints']
    assert after['profiles'] == before['profiles']
    assert ctx.primary_backends['openai']._base_url == 'https://cloud.test/v1'
    assert service.path.read_bytes() == stored


@pytest.mark.parametrize('with_lease', [True, False])
async def test_probe_reserves_capacity_and_releases_on_cancellation(tmp_path, monkeypatch, with_lease):
    from backends.llm_lease import LLMLeaseCoordinator, LLMLeaseBusy
    service, ctx = make_service(tmp_path)
    if with_lease:
        ctx.llm_lease = LLMLeaseCoordinator()
    entered = asyncio.Event()
    async def waiting_response(request):
        entered.set()
        await asyncio.Event().wait()
    transport(monkeypatch, waiting_response)
    task = asyncio.create_task(service.probe('vllm', profile(), 'worker'))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert service.public()['busy']
        with pytest.raises(RuntimeError, match='idle'):
            service.save('openai', profile('api-main', 'api-main'))
        with pytest.raises(RuntimeError, match='idle'):
            await service.probe('vllm', profile(), 'worker')
        if with_lease:
            with pytest.raises(LLMLeaseBusy):
                async with ctx.llm_lease.acquire(10, 'normal-inference', wait=False):
                    pytest.fail('Probe must hold the shared lease')
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not service.public()['busy']
    assert not service.path.exists()
    if with_lease:
        assert not ctx.llm_lease.status()['active']


async def test_manual_registration_and_removal_never_discover_or_provision(tmp_path, monkeypatch):
    service, ctx = make_service(tmp_path, managed=True)
    requests = []
    def respond(request):
        requests.append((request.method, str(request.url), request.headers.get('authorization')))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Connected'}}]})
    transport(monkeypatch, respond)
    service.save_endpoint('extra', record('extra', token='endpoint-secret'))
    assert requests == [] and ctx.primary_backends['vllm']._nemoclaw_runtime.resolutions == []
    restored, restored_ctx = make_service(tmp_path, managed=True)
    restored.load()
    await restored_ctx.primary_backends['vllm'].complete(model='endpoint:extra', system_prompt='', user_prompt='hello')
    assert requests == [('POST', 'http://extra.test/v1/chat/completions', 'Bearer endpoint-secret')]
    restored.remove_endpoint('extra')
    assert len(requests) == 1
    assert 'extra' not in json.loads(service.path.read_text())['endpoints']
    assert 'extra' not in [row['id'] for row in restored.public()['endpoints']]


async def test_new_endpoint_does_not_inherit_saved_token_from_another_endpoint(tmp_path, monkeypatch):
    service, ctx = make_service(tmp_path)
    service.save_endpoint('unrelated', record('unrelated', url='http://unrelated.test/v1'))
    requests = []
    def respond(request):
        requests.append(request.headers.get('authorization'))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Connected'}}]})
    transport(monkeypatch, respond)
    await ctx.primary_backends['vllm'].complete(model='endpoint:unrelated', system_prompt='', user_prompt='hello')
    assert requests == [None]


def test_removing_assigned_endpoint_preserves_registry_and_storage(tmp_path):
    service, _ = make_service(tmp_path)
    before = service.public()
    with pytest.raises(ValueError, match='assigned'):
        service.remove_endpoint('local-main')
    assert service.public() == before
    assert not service.path.exists()


def test_invalid_management_registration_preserves_existing_registry(tmp_path):
    service, _ = make_service(tmp_path, managed=True)
    before = service.public()
    with pytest.raises(ValueError, match='management target'):
        service.save_endpoint('bad', record('bad', management_id='not-configured'))
    assert service.public() == before
    assert not service.path.exists()


async def test_registration_retains_same_endpoint_token_and_probe_redacts_it(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    service.save_endpoint('other', record('other', token='endpoint-private'))
    service.save_endpoint('other', record('other', model='replacement-model'))
    saved = service.path.read_bytes()
    requests = []
    def respond(request):
        requests.append((request.headers.get('authorization'), json.loads(request.content)['model']))
        return httpx.Response(200, json={'choices': [{'message': {'content': request.headers['authorization']}}]})
    transport(monkeypatch, respond)
    reply = await service.probe('vllm', profile('other', 'other'), 'orchestrator')
    assert reply['ok'] and requests == [('Bearer endpoint-private', 'replacement-model')]
    assert 'endpoint-private' not in json.dumps(reply)
    assert 'endpoint-private' not in json.dumps(service.public())
    assert service.path.read_bytes() == saved


async def test_removed_managed_endpoint_can_be_reregistered_with_same_management_identity(tmp_path):
    service, ctx = make_service(tmp_path, managed=True)
    spare = record('spare', model='shared-name', management_id='spare-server')
    service.save_endpoint('spare', spare)
    service.remove_endpoint('spare')
    service.save_endpoint('spare', spare)
    assert await ctx.primary_backends['vllm']._base_url_for_model('endpoint:spare') == 'http://spare-server.test:31000/v1'
    restored, restored_ctx = make_service(tmp_path, managed=True)
    restored.load()
    assert await restored_ctx.primary_backends['vllm']._base_url_for_model('endpoint:spare') == 'http://spare-server.test:31000/v1'
    assert 'spare-server' in [row['id'] for row in restored.public()['management_targets']]
