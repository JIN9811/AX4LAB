"""Backend public precedence and legacy normalization at real caller boundaries."""
from copy import deepcopy
from dataclasses import replace
import os
import socket
import subprocess

import pytest

from test_portable_bootstrap import calls
from test_ax4lab_launcher import cli, prepare_cli
from test_portable_bootstrap import checkout as checkout
from tests.unit.test_runtime_path_consumers import disposable_paths as disposable_paths


@pytest.fixture(autouse=True)
def isolated_backend_environment(monkeypatch):
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    for name in ('AX4LAB_BACKEND', 'AUTONOMOUS_BACKEND'):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize('key', ['AUTONOMOUS_BACKEND', 'AX4LAB_BACKEND'])
@pytest.mark.parametrize('alias', ['api', 'cloud', 'openai-api', 'OPENAI', ' OpenAI '])
def test_launcher_accepts_existing_openai_backend_aliases(checkout, key, alias):
    prepare_cli(checkout)
    result = cli(checkout, 'run', 'start', 'test', 'backend alias', **{key: alias})
    assert result.returncode == 0, result.stderr
    import json
    arguments = calls(checkout).splitlines()
    payload = json.loads(arguments[arguments.index('-d') + 1])
    assert payload['backend'] == 'openai'


@pytest.mark.parametrize('dotenv,environment,want', [
    ('', {'AX4LAB_BACKEND': 'openai', 'AUTONOMOUS_BACKEND': 'vllm'}, 'openai'),
    ('AX4LAB_BACKEND=openai\n', {'AUTONOMOUS_BACKEND': 'vllm'}, 'openai'),
    ('AX4LAB_BACKEND=vllm\n', {'AX4LAB_BACKEND': 'OPENAI', 'AUTONOMOUS_BACKEND': 'ollama'}, 'openai'),
    ('', {'AUTONOMOUS_BACKEND': 'api'}, 'openai'),
    ('', {'AUTONOMOUS_BACKEND': 'cloud'}, 'openai'),
    ('', {'AUTONOMOUS_BACKEND': 'openai-api'}, 'openai'),
    ('', {'AUTONOMOUS_BACKEND': ' OPENAI '}, 'openai'),
    ('', {}, 'vllm'),
])
def test_direct_bootstrap_uses_public_backend_and_legacy_normalization(
        disposable_paths, tmp_path, monkeypatch, dotenv, environment, want):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    paths = replace(disposable_paths, repository_root=tmp_path)
    (tmp_path / '.env').write_text(dotenv)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    original_loader = bootstrap._load_configs
    def configs(selected):
        cfg = deepcopy(original_loader(selected))
        cfg['system']['system']['inference_backend'] = 'vllm'
        cfg['system']['runtime_env'] = {}
        return cfg
    monkeypatch.setattr(bootstrap, '_load_configs', configs)
    # Keep configuration, routers, registries and controller real; replace only
    # external backend transports. No start, request, or hardware action occurs.
    monkeypatch.setattr(bootstrap, '_build_backend', lambda *args, **kwargs: MockLLMBackend())
    def forbidden(*args, **kwargs):
        raise AssertionError('Backend selection must not connect or start a process')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    controller = bootstrap.load_runtime(paths=paths)
    assert controller._deps.agent_context.active_backend == want
    assert controller._deps.runtime_profile['backend']['name'] == want
    assert controller._run_task is None
    assert set(controller._deps.agent_context.primary_backends) == {'vllm', 'openai'}


@pytest.mark.parametrize('key', ['AUTONOMOUS_BACKEND', 'AX4LAB_BACKEND'])
@pytest.mark.parametrize('backend', ['ollama', 'nemoclaw', 'unknown-legacy-value'])
def test_launcher_rejects_unsupported_explicit_backend_before_request(checkout, key, backend):
    prepare_cli(checkout)
    result = cli(checkout, 'run', 'start', 'test', 'backend rejection', **{key: backend})
    assert result.returncode != 0
    assert calls(checkout) == ''


@pytest.mark.parametrize('backend', ['ollama', 'nemoclaw'])
def test_backend_switch_cli_rejects_retired_adapters_before_request(checkout, backend):
    prepare_cli(checkout)
    result = cli(checkout, 'backend', backend)
    assert result.returncode != 0
    assert 'vllm' in result.stderr and 'openai' in result.stderr
    assert calls(checkout) == ''


@pytest.mark.parametrize('source', ['public', 'legacy', 'runtime_env', 'system'])
@pytest.mark.parametrize('backend', ['ollama', 'nemoclaw'])
def test_backend_selection_never_silently_falls_back_from_retired_adapter(source, backend):
    from utils.launcher_settings import select_backend_name
    cfg, env = {'system': {'inference_backend': 'vllm'}, 'runtime_env': {}}, {}
    if source == 'public':
        env['AX4LAB_BACKEND'] = backend
    elif source == 'legacy':
        env['AUTONOMOUS_BACKEND'] = backend
    elif source == 'runtime_env':
        cfg['runtime_env']['AUTONOMOUS_BACKEND'] = backend
    else:
        cfg['system']['inference_backend'] = backend
    with pytest.raises(ValueError, match='vllm.*openai'):
        select_backend_name(cfg, environ=env)


@pytest.mark.parametrize('schema_name', ['StartRunRequest', 'PlanningMessageRequest',
    'PlanningBootstrapRequest', 'BackendSwitchRequest', 'RuntimeAgentMessageRequest'])
def test_request_schemas_reject_retired_runtime_backends(schema_name):
    from app import main
    from pydantic import ValidationError
    schema = getattr(main, schema_name)
    for backend in ('ollama', 'nemoclaw'):
        with pytest.raises(ValidationError):
            schema.model_validate({'backend': backend, 'message': 'test request'})
    for backend in ('vllm', 'openai'):
        assert schema.model_validate({'backend': backend, 'message': 'test request'}).backend == backend
