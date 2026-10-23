"""Audit CLI endpoint selection without browsers, servers, or application imports."""
from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import urllib.request

import pytest

from tests.unit.test_runtime_worker_origins import bound_layout


RUNTIME = Path(__file__).resolve().parents[2]
AUDITS = [
    ('equipment_agent_manager_browser_audit', 'run_audit'),
    ('bo_objective_compiler_browser_audit', 'audit'),
    ('module_management_browser_audit', 'scenario_module_management'),
    ('planning_browser_audit', 'scenario_live_planning_render'),
]


def load_script(path):
    spec = importlib.util.spec_from_file_location('isolated_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_external_or_application_imports(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Browser, server, and external process execution is forbidden')

    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(subprocess, 'Popen', deny)
    monkeypatch.setattr(urllib.request, 'urlopen', deny)
    original_import = builtins.__import__

    def import_without_app(name, *args, **kwargs):
        if name == 'app' or name.startswith('app.'):
            raise AssertionError('Audit endpoint selection must not import the application')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_app)


@pytest.mark.parametrize('script,boundary', AUDITS)
@pytest.mark.parametrize('configuration,want', [
    ('default', 'http://127.0.0.1:7861'),
    ('environment', 'http://127.0.0.1:9181'),
    ('dotenv', 'http://127.0.0.1:9182'),
    ('yaml', 'http://127.0.0.1:9183'),
    ('url', 'http://audit.example.invalid:9184'),
    ('explicit', 'http://explicit.example.invalid:9185'),
])
def test_audit_main_dispatches_only_to_selected_ax4lab_endpoint(
    tmp_path, monkeypatch, script, boundary, configuration, want,
):
    from utils import runtime_paths
    paths, layout, bindings = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(layout))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(bindings))
    monkeypatch.setenv('ATR_URL', 'http://127.0.0.1:7860')
    for key in ('AX4LAB_HOST', 'AX4LAB_PORT', 'AX4LAB_URL', 'AX4LAB_BACKEND'):
        monkeypatch.delenv(key, raising=False)
    if configuration == 'environment': monkeypatch.setenv('AX4LAB_PORT', '9181')
    elif configuration == 'dotenv': (paths.repository_root / '.env').write_text('AX4LAB_PORT=9182\n')
    elif configuration == 'yaml':
        (paths.runtime_root / 'configs/system.yaml').write_text('server:\n  port: 9183\n')
    elif configuration == 'url': monkeypatch.setenv('AX4LAB_URL', want)
    elif configuration == 'explicit': monkeypatch.setenv('AX4LAB_PORT', 'invalid-local-config')
    module = load_script(RUNTIME / 'tests/ui' / (script + '.py'))
    argv = [script, '--base-url', want] if configuration == 'explicit' else [script]
    monkeypatch.setattr(sys, 'argv', argv)

    class EndpointSelected(BaseException):
        pass

    def stop_at_boundary(*args, **kwargs):
        url = args[1] if boundary.startswith('scenario_') else args[0]
        raise EndpointSelected(url)

    monkeypatch.setattr(module, boundary, stop_at_boundary)
    if hasattr(module, 'WebDriverAudit'):
        monkeypatch.setattr(module, 'WebDriverAudit',
                            lambda *args, **kwargs: SimpleNamespace(start=lambda: None, stop=lambda: None))
        monkeypatch.setattr(module.time, 'sleep', lambda duration: None)
    with pytest.raises(EndpointSelected) as selected:
        module.main()
    assert selected.value.args == (want,)


@pytest.mark.parametrize('script,boundary', AUDITS)
def test_audit_import_does_not_resolve_endpoint_or_start_application(monkeypatch, script, boundary):
    from utils import launcher_settings

    def deny_resolution():
        raise AssertionError('Endpoint resolution belongs to main, not module import')

    monkeypatch.setattr(launcher_settings, 'api_base_url', deny_resolution)
    load_script(RUNTIME / 'tests/ui' / (script + '.py'))


def test_portable_acceptance_hands_ephemeral_port_to_current_launcher(tmp_path, monkeypatch):
    from utils.launcher_settings import load_launcher_settings
    module = load_script(RUNTIME / 'tests/integration/test_portable_installation.py')

    class Reservation:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def bind(self, address): assert address == ('127.0.0.1', 0)
        def getsockname(self): return ('127.0.0.1', 45123)

    class LaunchRequested(BaseException):
        pass

    def stop_before_launch(command, **kwargs):
        raise LaunchRequested(kwargs['env'])

    monkeypatch.setattr(module.socket, 'socket', Reservation)
    monkeypatch.setattr(module.subprocess, 'Popen', stop_before_launch)
    with pytest.raises(LaunchRequested) as launched:
        module.test_actual_local_launcher_serves_idle_gui_and_test_profiles(
            tmp_path / 'checkout', tmp_path / 'profile.json', tmp_path)
    environment = launched.value.args[0]
    settings = load_launcher_settings(tmp_path, tmp_path / 'runtime', environ=environment)
    assert (settings.host, settings.port) == ('127.0.0.1', 45123)
    assert 'AUTONOMOUS_HOST' not in environment and 'AUTONOMOUS_PORT' not in environment
