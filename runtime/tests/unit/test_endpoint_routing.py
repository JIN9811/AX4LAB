"""Endpoint identity, not served model names, determines I/O and lifecycle."""
import json
from types import SimpleNamespace

import httpx
import pytest

from backends.vllm_client import VLLMBackend
from backends.openai_client import OpenAIBackend
from backends.model_router import ModelRouter


def routes():
    return {
        'first': dict(id='first', provider='vllm', base_url='http://first.test/v1',
                      model='same-model', access_token='first-secret', management_id='',
                      capabilities={'text': True, 'vision': True}),
        'second': dict(id='second', provider='vllm', base_url='http://second.test/v1',
                       model='same-model', access_token='second-secret', management_id='',
                       capabilities={'text': True, 'vision': False}),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['vllm', 'openai'])
async def test_same_served_model_on_two_endpoints_keeps_url_and_token_identity(monkeypatch, kind):
    seen = []
    async def respond(request):
        seen.append((str(request.url), request.headers.get('Authorization'), json.loads(request.content)['model']))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    backend = (VLLMBackend if kind == 'vllm' else OpenAIBackend)(base_url='http://wrong.test/v1', api_key='wrong-secret')
    backend._endpoint_routes = {key: {**row, 'provider': kind} for key, row in routes().items()}
    for key in ('first', 'second'):
        await backend.complete(model=f'endpoint:{key}', system_prompt='s', user_prompt='u')
    assert seen == [('http://first.test/v1/chat/completions', 'Bearer first-secret', 'same-model'),
                    ('http://second.test/v1/chat/completions', 'Bearer second-secret', 'same-model')]


@pytest.mark.asyncio
async def test_missing_or_ambiguous_endpoint_never_uses_default_server():
    backend = VLLMBackend(base_url='http://wrong.test/v1')
    backend._endpoint_routes = routes()
    for ref in ('endpoint:removed', 'same-model', 'unregistered'):
        with pytest.raises(ValueError):
            await backend._base_url_for_model(ref)


@pytest.mark.asyncio
async def test_lifecycle_uses_management_target_not_model_name():
    calls = []
    class Runtime:
        async def load_model(self, target):
            calls.append(('load', target))
            return {'enabled': True, 'loaded': True}
        async def unload_model(self, target):
            calls.append(('unload', target))
            return {'enabled': True, 'unloaded': True}
    backend = VLLMBackend(nemoclaw_runtime=Runtime())
    backend._endpoint_routes = routes()
    backend._endpoint_routes['first']['management_id'] = 'deployment-main'
    await backend.load_model('endpoint:first')
    await backend.unload_model('endpoint:first')
    assert calls == [('load', 'deployment-main'), ('unload', 'deployment-main')]
    with pytest.raises(ValueError):
        await backend.load_model('endpoint:second')


def test_worker_default_is_generic_and_missing_role_does_not_invent_a_model():
    router = ModelRouter({'models': {'worker': {'primary': 'endpoint:local'}}})
    assert router.select('vision_observation').primary == 'endpoint:local'
    assert router.select('vision_observation').role == 'worker'
    with pytest.raises(ValueError):
        ModelRouter({'models': {}}).select('vision_observation')


def test_old_role_key_is_normalized_only_on_import():
    router = ModelRouter({'models': {'e4b': {'primary': 'endpoint:local'}},
                          'task_routes': {'design_reasoning': 'e4b'}})
    assert router.select('design_reasoning').role == 'worker'
    assert router.select('vision_observation').primary == 'endpoint:local'
