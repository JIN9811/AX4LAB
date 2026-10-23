"""Server/recovery callers select the same public endpoint, with I/O intercepted."""
import json
import os
import runpy
import sys
import urllib.request

import pytest

from tests.unit.test_runtime_worker_origins import bound_layout


@pytest.fixture(autouse=True)
def clean_public_environment(monkeypatch):
    # load_dotenv mutates the mapping itself, so restore the whole mapping.
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    for key in ('AX4LAB_HOST', 'AX4LAB_PORT', 'AX4LAB_URL', 'AX4LAB_BACKEND'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('server,dotenv,overrides,want', [
    ({}, '', {'AUTONOMOUS_PORT': '7860', 'AUTONOMOUS_HOST': 'old-host'}, ('127.0.0.1', 7861)),
    ({'host': '0.0.0.0', 'port': 9123}, '', {}, ('0.0.0.0', 9123)),
    ({'port': 9123}, 'AX4LAB_HOST=127.0.0.2\nAX4LAB_PORT=9234\n', {}, ('127.0.0.2', 9234)),
    ({'port': 9123}, 'AX4LAB_PORT=9234\n', {'AX4LAB_PORT': '9345'}, ('127.0.0.1', 9345)),
])
def test_serve_honors_ax4lab_settings_with_environment_precedence(tmp_path, monkeypatch, server, dotenv, overrides, want):
    from app import serve
    from utils import runtime_paths
    paths, layout, bindings = bound_layout(tmp_path)
    (paths.runtime_root / 'configs/system.yaml').write_text(json.dumps({'server': server}))
    (paths.repository_root / '.env').write_text(dotenv)
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(layout))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    for key in ('AX4LAB_HOST', 'AX4LAB_PORT', 'AX4LAB_URL', 'AX4LAB_BACKEND'):
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    started = []
    monkeypatch.setattr(serve.uvicorn, 'run', lambda target, **kw: started.append((target, kw)))
    serve.main()
    assert started[0][0] == 'app.main:app'
    assert (started[0][1]['host'], started[0][1]['port']) == want


def test_public_backend_applies_to_preserved_runtime_protocol(tmp_path, monkeypatch):
    from app import serve
    from utils import runtime_paths
    paths, layout, bindings = bound_layout(tmp_path)
    (paths.runtime_root / 'configs/system.yaml').write_text('runtime_env:\n  AUTONOMOUS_BACKEND: vllm\n')
    (paths.repository_root / '.env').write_text('AX4LAB_BACKEND=openai\n')
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(layout))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    monkeypatch.setenv('AUTONOMOUS_BACKEND', 'ollama')
    monkeypatch.delenv('AX4LAB_BACKEND', raising=False)
    monkeypatch.chdir(tmp_path)
    captured = []
    monkeypatch.setattr(serve.uvicorn, 'run', lambda *args, **kw: captured.append(os.environ['AUTONOMOUS_BACKEND']))
    serve.main()
    assert captured == ['openai']


@pytest.mark.parametrize('module,args', [
    ('bo_budget_recovery', []),
    ('printer_wait_recovery', ['fixture-run']),
    ('run_recovery', ['fixture-run']),
    ('equipment_selection_checkpoint', ['--run-id', 'fixture-run']),
    ('equipment_tail_recovery', ['--execution-id', 'fixture-execution']),
])
@pytest.mark.parametrize('port', [None, '9456'])
def test_checkpoint_clients_never_default_to_original_atr_server(tmp_path, monkeypatch, module, args, port):
    from utils import runtime_paths
    paths, layout, bindings = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(layout))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    monkeypatch.setenv('ATR_URL', 'http://127.0.0.1:7860')
    for key in ('AX4LAB_URL', 'AX4LAB_HOST', 'AX4LAB_PORT'):
        monkeypatch.delenv(key, raising=False)
    if port:
        (paths.repository_root / '.env').write_text(f'AX4LAB_PORT={port}\n')
    monkeypatch.setattr(sys, 'argv', [module, *args])
    seen = []
    class ReachedRequest(BaseException):
        pass
    def request(url, **kwargs):
        seen.append(url)
        raise ReachedRequest()
    monkeypatch.setattr(urllib.request, 'urlopen', request)
    with pytest.raises(ReachedRequest):
        runpy.run_module('app.' + module, run_name='__main__')
    assert seen == [f'http://127.0.0.1:{port or "7861"}/api/state']
