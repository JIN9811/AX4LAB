"""Public CLI behavior at real installer/settings boundaries; no live I/O."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_portable_bootstrap import RUNTIME, calls, install_venv, run
from test_portable_bootstrap import checkout as checkout


def cli(checkout, *args, **overrides):
    root, env = checkout
    return subprocess.run([str(Path(env['HOME']) / '.local/bin/ax4lab'), *args],
                          cwd=root.parent, env={**env, **overrides}, text=True,
                          capture_output=True)


def prepare_cli(checkout):
    root, env = checkout
    venv = install_venv(checkout)
    (root / 'runtime/configs').mkdir()
    (root / 'runtime/configs/system.yaml').write_text('server: {}\n')
    (root / 'runtime/utils').mkdir()
    helper = RUNTIME / 'utils/launcher_settings.py'
    if helper.exists():
        shutil.copy2(helper, root / 'runtime/utils/launcher_settings.py')
    python = venv / 'bin/python'
    original = python.read_text()
    python.write_text(original.replace('#!/usr/bin/env bash\n', '''#!/usr/bin/env bash
if [[ "$1" == *launcher_settings.py ]]; then exec "$REAL_PYTHON" "$@"; fi
if [[ "$1" == -m && "$2" == json.tool ]]; then exec "$REAL_PYTHON" "$@"; fi
if [[ "$1" == -c && -n "${STOP_HARNESS:-}" ]]; then exec "$REAL_PYTHON" "$STOP_HARNESS" "$2"; fi
if [[ "$1" == -c && "$2" == 'import json,'* ]]; then exec "$REAL_PYTHON" "$@"; fi
''', 1))
    env['REAL_PYTHON'] = sys.executable
    tools = Path(env['PATH'].split(':')[0])
    curl = tools / 'curl'
    curl.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CALLS"\nprintf "{}\\n"\n')
    curl.chmod(0o755)
    installed = run(checkout, 'install_cli.sh')
    assert installed.returncode == 0, installed.stderr
    assert (Path(env['HOME']) / '.local/bin/ax4lab').exists(), installed.stdout
    return root, env


def test_installer_coexists_with_old_atr_without_modifying_or_executing_it(checkout):
    root, env = checkout
    old = Path(env['HOME']) / '.local/bin/atr'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'#!/bin/sh\n# original checkout\nexit 99\n')
    old.chmod(0o755)
    before = old.read_bytes()
    result = run(checkout, 'install_cli.sh', PATH=f'{old.parent}:{env["PATH"]}')
    assert result.returncode == 0, result.stderr
    assert old.read_bytes() == before
    help_result = cli(checkout, '--help')
    assert help_result.returncode == 0
    assert 'ax4lab up' in help_result.stdout
    assert 'AX4LAB_URL' in help_result.stdout


@pytest.mark.parametrize('endpoint', ['local-main', 'custom-endpoint', 'e4b'])
def test_model_load_cli_preserves_endpoint_identity_without_model_aliases(checkout, endpoint):
    prepare_cli(checkout)
    result = cli(checkout, 'model', 'load', endpoint)
    assert result.returncode == 0, result.stderr
    arguments = calls(checkout).splitlines()
    payload = json.loads(arguments[arguments.index('-d') + 1])
    assert payload == {'endpoint_id': endpoint}
    assert 'http://127.0.0.1:7861/api/runtime/models/load' in arguments


@pytest.mark.parametrize('config,dotenv,overrides,want', [
    ({}, '', {'ATR_URL': 'http://127.0.0.1:7860', 'AUTONOMOUS_PORT': '7860'}, 'http://127.0.0.1:7861/api/state'),
    ({'port': 9123}, '', {}, 'http://127.0.0.1:9123/api/state'),
    ({'port': 9123}, 'AX4LAB_HOST=127.0.0.2\nAX4LAB_PORT=9234\n', {}, 'http://127.0.0.2:9234/api/state'),
    ({'port': 9123}, 'AX4LAB_PORT=9234\n', {'AX4LAB_PORT': '9345'}, 'http://127.0.0.1:9345/api/state'),
    ({'host': '0.0.0.0'}, '', {}, 'http://127.0.0.1:7861/api/state'),
    ({'host': '::'}, '', {}, 'http://[::1]:7861/api/state'),
    ({}, 'AX4LAB_URL=https://example.invalid/proxy/\n', {}, 'https://example.invalid/proxy/api/state'),
])
def test_cli_resolves_url_from_checkout_settings_not_legacy_atr(checkout, config, dotenv, overrides, want):
    root, _ = prepare_cli(checkout)
    (root / 'runtime/configs/system.yaml').write_text(json.dumps({'server': config}))
    (root / '.env').write_text(dotenv)
    result = cli(checkout, 'status', **overrides)
    assert result.returncode == 0, result.stderr
    assert want in calls(checkout).splitlines()


@pytest.mark.parametrize('state', ['missing', 'stale', 'valid'])
def test_up_uses_guarded_checkout_launcher(checkout, state):
    root, _ = prepare_cli(checkout)
    if state == 'missing':
        (root / '.venv/bin/python').unlink()
    elif state == 'stale':
        (root / '.venv/.atr-prefix').write_text('/another/checkout/.venv\n')
    result = cli(checkout, 'up')
    assert (result.returncode == 0) == (state == 'valid'), result.stderr
    if state == 'valid':
        assert calls(checkout).splitlines() == [str(root / 'runtime'), '-m', 'app.serve']
    else:
        assert 'bootstrap_linux.sh' in result.stderr
        assert 'app.serve' not in calls(checkout)


def test_legacy_force_flag_cannot_replace_ax4lab_launcher(checkout):
    target = Path(checkout[1]['HOME']) / '.local/bin/ax4lab'
    target.parent.mkdir(parents=True)
    target.write_text('original unrelated command\n')
    result = run(checkout, 'install_cli.sh', ATR_FORCE_INSTALL='1')
    assert result.returncode != 0
    assert target.read_text() == 'original unrelated command\n'


@pytest.mark.parametrize('dotenv,overrides,want', [
    ('AX4LAB_BACKEND=openai\n', {'ATR_BACKEND': 'nemoclaw'}, 'openai'),
    ('AX4LAB_BACKEND=openai\n', {'AX4LAB_BACKEND': 'vllm'}, 'vllm'),
])
def test_run_request_uses_public_backend_selection(checkout, dotenv, overrides, want):
    root, _ = prepare_cli(checkout)
    (root / '.env').write_text(dotenv)
    result = cli(checkout, 'run', 'start', 'test', 'isolated request', **overrides)
    assert result.returncode == 0, result.stderr
    arguments = calls(checkout).splitlines()
    payload = json.loads(arguments[arguments.index('-d') + 1])
    assert payload['backend'] == want
    assert payload['goal'] == 'isolated request'


@pytest.mark.parametrize('args,key', [
    (['chat', 'hello'], 'session_id'),
    (['chat', 'bootstrap', 'isolated goal'], 'session_id'),
    (['module', 'save-yaml', 'fixture-module'], 'author'),
    (['graph', 'save-yaml', 'fixture-graph'], 'author'),
])
def test_new_cli_requests_use_independent_session_and_author_identity(checkout, args, key):
    root, _ = prepare_cli(checkout)
    if 'save-yaml' in args:
        source = root / 'fixture.yaml'
        source.write_text('{}\n')
        args = [*args, str(source)]
    result = cli(checkout, *args)
    assert result.returncode == 0, result.stderr
    arguments = calls(checkout).splitlines()
    payload = json.loads(arguments[arguments.index('-d') + 1])
    assert payload[key] == 'ax4lab-cli'


@pytest.mark.parametrize('setting', ['AX4LAB_PORT=0', 'AX4LAB_PORT=65536',
                                     'AX4LAB_URL=http://host.invalid/path with spaces'])
def test_invalid_endpoint_stops_before_any_api_request(checkout, setting):
    root, _ = prepare_cli(checkout)
    (root / '.env').write_text(setting + '\n')
    result = cli(checkout, 'status')
    assert result.returncode != 0
    assert calls(checkout) == ''


def test_down_only_signals_exact_checkout_server(checkout, tmp_path):
    root, env = prepare_cli(checkout)
    processes = {
        '500001': {'cwd': str(root / 'runtime'), 'argv': ['/python', '-m', 'app.serve']},
        '500002': {'cwd': '/original/runtime', 'argv': ['/python', '-m', 'app.serve', '--note', str(root)]},
        '500003': {'cwd': str(root) + '-other/runtime', 'argv': ['/python', '-m', 'app.serve']},
        '500004': {'cwd': str(root / 'runtime'), 'argv': ['/python', '-m', 'unrelated', 'app.serve']},
        '500005': {'cwd': '/original/runtime', 'argv': ['lerobot-record', '--note', str(root)]},
        '500006': {'cwd': str(root / 'runtime'), 'argv': ['/python', '-m', 'other.module', '-m', 'app.serve']},
    }
    harness = tmp_path / 'process_boundary.py'
    harness.write_text('''import builtins, io, json, os, signal, sys
processes = json.loads(os.environ['FAKE_PROCESSES'])
events = []
original_open = builtins.open
def opened(path, *args, **kwargs):
    if str(path).startswith('/proc/'):
        return io.BytesIO(('\\0'.join(processes[str(path).split('/')[2]]['argv']) + '\\0').encode())
    return original_open(path, *args, **kwargs)
builtins.open = opened
os.listdir = lambda path: list(processes) if path == '/proc' else []
os.readlink = lambda path: processes[str(path).split('/')[2]]['cwd']
def kill(pid, sig):
    if sig == 0: raise ProcessLookupError()
    events.append([pid, int(sig)])
os.kill = kill
def killpg(*args): raise AssertionError('unscoped process-group kill')
os.killpg = killpg
try: exec(sys.argv[1])
except SystemExit as exc:
    if exc.code: raise
with original_open(os.environ['KILL_LOG'], 'a') as output:
    output.write(json.dumps(events) + '\\n')
''')
    kill_log = tmp_path / 'kills'
    result = cli(checkout, 'down', STOP_HARNESS=str(harness), KILL_LOG=str(kill_log),
                 FAKE_PROCESSES=json.dumps(processes))
    assert result.returncode == 0, result.stderr
    events = [event for row in kill_log.read_text().splitlines() for event in json.loads(row)]
    assert events == [[500001, 15]]
