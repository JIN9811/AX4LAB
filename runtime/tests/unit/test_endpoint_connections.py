"""Persisted endpoint/role selection must not depend on served model names."""
import json
from types import SimpleNamespace

import pytest

from app.llm_connections import LLMConnections
from backends.model_router import ModelRouter
from backends.openai_client import OpenAIBackend
from backends.vllm_client import VLLMBackend
from backends.endpoint_routes import endpoint_token


def make_service(tmp_path):
    clients = {'vllm': VLLMBackend(base_url='http://local.test/v1'),
               'openai': OpenAIBackend(base_url='https://cloud.test/v1', api_key='cloud-key')}
    records = {}
    for provider, key in [('vllm', 'local'), ('openai', 'cloud')]:
        records[key] = dict(id=key, label=key.title(), provider=provider,
            base_url=clients[provider]._base_url, model='served-model', management_id='',
            access_token=None, capabilities={'text': True, 'vision': True})
        clients[provider]._endpoint_routes = {key: records[key]}
    routers = {provider: ModelRouter({'models': {
        role: {'primary': f'endpoint:{key}'} for role in ('orchestrator', 'worker')},
        'task_routes': {'orchestrator_plan': 'orchestrator'}})
        for provider, key in [('vllm', 'local'), ('openai', 'cloud')]}
    ctx = SimpleNamespace(primary_backends=clients, model_routers=routers,
        runtime_profiles={'vllm': {}, 'openai': {}}, active_backend='vllm', model_router=routers['vllm'])
    return LLMConnections(ctx, tmp_path / 'connections.json'), ctx


def test_endpoint_roundtrip_and_role_assignment_are_by_id(tmp_path):
    service, ctx = make_service(tmp_path)
    service.save_endpoint('second', dict(label='Other server', provider='vllm', base_url='http://second.test/v1',
        model='served-model', access_token='private-key', capabilities={'text': True, 'vision': True}))
    service.save('vllm', {'orchestrator_endpoint': 'local', 'worker_endpoint': 'second'})
    assert ctx.model_routers['vllm'].select('vision_observation').primary == 'endpoint:second'
    other, other_ctx = make_service(tmp_path)
    other.load()
    assert other_ctx.model_routers['vllm'].select('vision_observation').primary == 'endpoint:second'
    assert other.public()['profiles']['vllm']['worker_endpoint'] == 'second'
    assert 'private-key' not in json.dumps(other.public())
    assert json.loads(service.path.read_text())['schema'] == 'llm_connections.v2'
    with pytest.raises(ValueError):
        other.remove_endpoint('second')


def test_url_change_clears_token_and_provider_mismatch_is_rejected(tmp_path):
    service, ctx = make_service(tmp_path)
    record = dict(label='Other', provider='vllm', base_url='http://one.test/v1', model='served', access_token='private')
    service.save_endpoint('other', record)
    service.save_endpoint('other', {**record, 'base_url': 'http://two.test/v1', 'access_token': None})
    endpoint = ctx.primary_backends['vllm']._endpoint_routes['other']
    assert not endpoint.get('access_token')
    with pytest.raises(ValueError):
        service.save('vllm', {'orchestrator_endpoint': 'cloud', 'worker_endpoint': 'local'})


def test_failed_persistence_keeps_previous_runtime_connections(tmp_path, monkeypatch):
    service, ctx = make_service(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('full disk')
    monkeypatch.setattr(service, '_persist', fail)
    with pytest.raises(OSError):
        service.save_endpoint('other', dict(label='Other', provider='vllm', base_url='http://two.test/v1', model='served'))
    assert 'other' not in ctx.primary_backends['vllm']._endpoint_routes


def test_retired_managed_registration_does_not_discard_api_profile(tmp_path):
    service, ctx = make_service(tmp_path)
    service.path.write_text(json.dumps({'schema': 'llm_connections.v1', 'local_models': {
        'retired': {'model': 'retired', 'base_url': 'http://retired.test/v1', 'managed': True}},
        'profiles': {'openai': {'mode': 'custom', 'base_url': 'https://other-cloud.test/v1',
            'orchestrator_model': 'new-model', 'worker_model': 'new-model'},
            'vllm': {'mode': 'managed', 'base_url': 'http://local.test/v1',
                'orchestrator_model': 'retired', 'worker_model': 'retired'}}}))
    service.load()
    assert ctx.primary_backends['openai']._base_url == 'https://other-cloud.test/v1'
    assert ctx.model_routers['vllm'].select('vision_observation').primary == 'endpoint:local'
    assert all(row['model'] != 'retired' for row in service.public()['endpoints'])


def test_legacy_token_is_retained_when_registration_matches_configured_endpoint(tmp_path):
    service, ctx = make_service(tmp_path)
    service.path.write_text(json.dumps({'schema': 'llm_connections.v1', 'profiles': {
        'vllm': {'mode': 'custom', 'base_url': 'http://local.test/v1',
            'orchestrator_model': 'served-model', 'worker_model': 'served-model',
            'access_token': 'previous-local-key'}}}))
    service.load()
    assert ctx.primary_backends['vllm']._endpoint_routes['local']['access_token'] == 'previous-local-key'
    assert 'previous-local-key' not in json.dumps(service.public())


@pytest.mark.parametrize('provider,original', [('vllm', 'local'), ('openai', 'cloud')])
def test_switching_orchestrator_keeps_original_worker_credential(tmp_path, provider, original):
    service, ctx = make_service(tmp_path)
    backend = ctx.primary_backends[provider]
    secret = backend._api_key
    service.save_endpoint('other', dict(provider=provider, base_url='http://other.test/v1', model='other'))
    service.save(provider, dict(orchestrator_endpoint='other', worker_endpoint=original))
    assert endpoint_token(backend, backend._endpoint_routes[original]) == secret
    assert not endpoint_token(backend, backend._endpoint_routes['other'])
    service.save(provider, dict(orchestrator_endpoint=original, worker_endpoint=original))
    assert endpoint_token(backend, backend._endpoint_routes[original]) == secret


def test_management_target_change_clears_inherited_token(tmp_path):
    service, ctx = make_service(tmp_path)
    manager = SimpleNamespace(_models={key: SimpleNamespace(deployment=key) for key in ('one', 'two')})
    service._defaults['vllm']._nemoclaw_runtime = manager
    row = dict(provider='vllm', base_url='http://one.test/v1', model='served',
               management_id='one', access_token='private-one')
    service.save_endpoint('managed', row)
    service.save_endpoint('managed', {**row, 'management_id': 'two', 'access_token': None})
    assert not ctx.primary_backends['vllm']._endpoint_routes['managed']['access_token']


def test_legacy_unassigned_custom_catalog_is_preserved_on_save(tmp_path):
    service, _ = make_service(tmp_path)
    service.path.write_text(json.dumps({'schema': 'llm_connections.v1', 'profiles': {},
        'local_models': {'spare-model': {'model': 'spare-model', 'managed': False,
            'base_url': 'http://spare.test/v1', 'access_token': 'spare-private'}}}))
    service.load()
    spare = next(row for row in service.public()['endpoints'] if row['model'] == 'spare-model')
    service.save('vllm', service._profiles['vllm'])
    saved = json.loads(service.path.read_text())['endpoints'][spare['id']]
    assert saved['access_token'] == 'spare-private'


@pytest.mark.parametrize('payload', [[], {'schema': 'llm_connections.v2', 'endpoints': []},
                                     {'schema': 'llm_connections.v2', 'profiles': []}])
def test_malformed_storage_preserves_deployment_defaults(tmp_path, payload):
    service, ctx = make_service(tmp_path)
    service.path.write_text(json.dumps(payload))
    service.load()
    assert service.load_error
    assert ctx.model_routers['vllm'].select('vision_observation').primary == 'endpoint:local'
