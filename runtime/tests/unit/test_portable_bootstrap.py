"""Execute real installers in synthetic checkouts; never install or start anything."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

RUNTIME = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Linux shell contract')


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'new user' / 'AX4 LAB'
    shutil.copytree(RUNTIME / 'install', root / 'runtime/install')
    (root / '.env.example').write_text('EXAMPLE=1\n')
    (root / 'runtime/scripts').mkdir()
    (root / 'runtime/scripts/doctor.py').touch()
    (root / 'runtime/pyproject.toml').touch()
    (root / 'runtime/uv.lock').touch()
    tools = tmp_path / 'tools'
    tools.mkdir()
    fake_python = tools / 'fake-python'
    fake_python.write_text('''#!/usr/bin/env bash
if [[ "$*" == "-m venv .venv" ]]; then
  mkdir -p .venv/bin; cp "$FAKE_PYTHON" .venv/bin/python; cp "$FAKE_PYTHON" .venv/bin/pip; exit
fi
if [[ "$1" == "-I" ]]; then
  if [[ "$*" == *'_base_executable'* ]]; then
    if [[ -f "$(dirname "$0")/.interpreter-id" ]]; then cat "$(dirname "$0")/.interpreter-id"; else echo python3.12; fi
  else
    if [[ -f "$(dirname "$0")/.reported-prefix" ]]; then cat "$(dirname "$0")/.reported-prefix";
    else printf '%s\\n' "$(dirname "$(dirname "$0")")"; fi
  fi
  exit
fi
printf '%s\\n' "$PWD" "$@" >> "$CALLS"
if [[ "${REPORT_PROFILE:-0}" == 1 ]]; then printf 'profile:%s\\n' "$ATR_INSTALL_PROFILE" >> "$CALLS"; fi
if [[ -n "${PYTHONHOME:-}${PYTHONPATH:-}" ]]; then exit 91; fi
if [[ "$*" == *doctor.py* ]]; then exit "${DOCTOR_EXIT:-0}"; fi
''')
    fake_python.chmod(0o755)
    uv = tools / 'uv'
    uv.write_text('''#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "$CALLS"
if [[ "$1" == venv ]]; then
  target="${@: -1}"
  mkdir -p "$target/bin"
  cp "$PYTHON_BIN" "$target/bin/python"
  if [[ -f "$(dirname "$PYTHON_BIN")/.interpreter-id" ]]; then cp "$(dirname "$PYTHON_BIN")/.interpreter-id" "$target/bin/.interpreter-id"; fi
fi
if [[ "$1" == sync && "${FAIL_SYNC:-0}" == 1 ]]; then exit 25; fi
exit "${UV_EXIT:-0}"
''')
    uv.chmod(0o755)
    home = tmp_path / 'empty-home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'SHELL': '/bin/bash',
           'PATH': f'{tools}:/usr/bin:/bin', 'UV_BIN': str(uv),
           'CALLS': str(tmp_path / 'calls'), 'FAKE_PYTHON': str(fake_python),
           'PYTHON_BIN': str(fake_python)}
    return root, env


def run(checkout, script, *args, **overrides):
    root, env = checkout
    return subprocess.run(['bash', str(root / 'runtime/install' / script), *args],
                          cwd=root.parent, env={**env, **overrides}, text=True, capture_output=True)


def install_venv(checkout, prefix=None):
    root, env = checkout
    venv = root / '.venv'
    (venv / 'bin').mkdir(parents=True)
    shutil.copy2(env['FAKE_PYTHON'], venv / 'bin/python')
    shutil.copy2(env['FAKE_PYTHON'], venv / 'bin/pip')
    (venv / '.atr-prefix').write_text(str(prefix or venv) + '\n')
    return venv


def calls(checkout):
    log = Path(checkout[1]['CALLS'])
    return log.read_text() if log.exists() else ''


def test_local_launcher_uses_checkout_env_and_preserves_arguments(checkout):
    root, env = checkout
    install_venv(checkout)
    (Path(env['PATH'].split(':')[0]) / 'atr').write_text('#!/bin/sh\nexit 99\n')
    result = run(checkout, 'run_local.sh', '--host', 'value with spaces')
    assert result.returncode == 0, result.stderr
    assert calls(checkout).splitlines() == [str(root / 'runtime'), '-m', 'app.serve', '--host', 'value with spaces']


@pytest.mark.parametrize('state', ['missing', 'stale', 'unmarked'])
def test_launcher_refuses_missing_or_moved_environment(checkout, state):
    if state != 'missing':
        venv = install_venv(checkout, '/old/user/checkout/.venv')
        if state == 'unmarked':
            (venv / '.atr-prefix').unlink()
    result = run(checkout, 'run_local.sh')
    assert result.returncode != 0
    assert 'bootstrap_linux.sh' in result.stderr
    assert calls(checkout) == ''


@pytest.mark.parametrize('script', ['run_local.sh', 'bootstrap_linux.sh'])
def test_correct_marker_wrong_interpreter_prefix_stops_before_mutation(checkout, script):
    venv = install_venv(checkout)
    (venv / 'bin/.reported-prefix').write_text('/different/environment\n')
    assert (venv / '.atr-prefix').read_text().strip() == str(venv)
    result = run(checkout, script)
    assert result.returncode != 0
    assert 'Stale Python prefix' in result.stderr
    assert calls(checkout) == ''
    assert not (checkout[0] / '.env').exists()
    assert not list(checkout[0].glob('.venv.backup.*'))


def test_bootstrap_is_frozen_repeatable_and_cli_opt_in(checkout):
    for _ in range(2):
        result = run(checkout, 'bootstrap_linux.sh')
        assert result.returncode == 0, result.stderr
    assert not (Path(checkout[1]['HOME']) / '.local/bin/atr').exists()
    log = calls(checkout)
    assert log.count('uv venv ') == 1
    assert log.count('uv lock --check') == 2
    assert log.count('uv sync --frozen') == 2
    assert 'app.serve' not in log
    assert 'install_piper_tts.sh' not in log


def test_bootstrap_propagates_doctor_failure(checkout):
    install_venv(checkout)
    result = run(checkout, 'bootstrap_linux.sh', DOCTOR_EXIT='23')
    assert result.returncode == 23, result.stdout + result.stderr


def test_bootstrap_propagates_lock_failure_before_install(checkout):
    install_venv(checkout)
    result = run(checkout, 'bootstrap_linux.sh', UV_EXIT='24')
    assert result.returncode == 24
    assert 'uv sync ' not in calls(checkout)


def test_bootstrap_dry_run_has_no_side_effects(checkout):
    result = run(checkout, 'bootstrap_linux.sh', '--dry-run', '--install-cli', '--with-piper')
    assert result.returncode == 0, result.stderr
    assert calls(checkout) == ''
    assert not (checkout[0] / '.venv').exists()
    assert not (checkout[0] / '.env').exists()
    assert not (Path(checkout[1]['HOME']) / '.local').exists()


def test_stale_environment_requires_explicit_rebuild_and_is_preserved(checkout):
    old = install_venv(checkout, '/old/user/checkout/.venv')
    (old / 'sentinel').write_text('keep')
    refused = run(checkout, 'bootstrap_linux.sh')
    assert refused.returncode != 0
    assert calls(checkout) == ''
    rebuilt = run(checkout, 'bootstrap_linux.sh', '--rebuild-venv')
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert list(checkout[0].glob('.venv.backup.*/environment/sentinel'))


@pytest.mark.parametrize('on_path', [True, False])
def test_global_installer_refuses_different_binding_at_same_target(checkout, on_path):
    root, env = checkout
    target = Path(env['HOME']) / '.local/bin/ax4lab'
    target.parent.mkdir(parents=True)
    original = '#!/bin/bash\nPROJECT_DIR="/other/checkout"\n'
    target.write_text(original)
    target.chmod(0o755)
    path = f'{target.parent}:{env["PATH"]}' if on_path else env['PATH']
    result = run(checkout, 'install_cli.sh', PATH=path)
    assert result.returncode != 0
    assert target.read_text() == original
    forced = run(checkout, 'install_cli.sh', PATH=path, AX4LAB_FORCE_INSTALL='1')
    assert forced.returncode == 0, forced.stderr
    again = run(checkout, 'install_cli.sh', PATH=path)
    assert again.returncode == 0, again.stderr


def test_global_installer_refuses_other_path_command(checkout):
    other = Path(checkout[1]['PATH'].split(':')[0]) / 'ax4lab'
    other.write_text('#!/bin/sh\nexit 99\n')
    other.chmod(0o755)
    result = run(checkout, 'install_cli.sh')
    assert result.returncode != 0
    assert not (Path(checkout[1]['HOME']) / '.local/bin/ax4lab').exists()


@pytest.mark.parametrize('selector', ['profiles/local profile.json', '~/local profile.json'])
def test_launcher_normalizes_profile_before_cwd_change(checkout, selector):
    install_venv(checkout)
    expected = (Path(checkout[1]['HOME']) / 'local profile.json' if selector.startswith('~')
                else checkout[0].parent / selector)
    result = run(checkout, 'run_local.sh', ATR_INSTALL_PROFILE=selector, REPORT_PROFILE='1',
                 PYTHONHOME='/unrelated', PYTHONPATH='/unrelated')
    assert result.returncode == 0, result.stderr
    assert calls(checkout).splitlines()[-1] == f'profile:{expected}'


def test_failed_dependency_download_can_resume_without_rebuilding(checkout):
    failed = run(checkout, 'bootstrap_linux.sh', FAIL_SYNC='1')
    assert failed.returncode == 25
    resumed = run(checkout, 'bootstrap_linux.sh')
    assert resumed.returncode == 0, resumed.stderr
    assert calls(checkout).count('uv venv ') == 1


def test_interpreter_change_requires_preserving_explicit_rebuild(checkout):
    old = install_venv(checkout)
    (old / 'sentinel').write_text('keep old environment')
    selected = checkout[0].parent / 'different Python/bin/python'
    selected.parent.mkdir(parents=True)
    shutil.copy2(checkout[1]['FAKE_PYTHON'], selected)
    (selected.parent / '.interpreter-id').write_text('python3.13\n')
    refused = run(checkout, 'bootstrap_linux.sh', PYTHON_BIN=str(selected))
    assert refused.returncode != 0
    assert '--rebuild-venv' in refused.stderr
    assert calls(checkout) == ''
    assert (old / 'sentinel').read_text() == 'keep old environment'
    rebuilt = run(checkout, 'bootstrap_linux.sh', '--rebuild-venv', PYTHON_BIN=str(selected))
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert list(checkout[0].glob('.venv.backup.*/environment/sentinel'))
    assert (old / 'bin/.interpreter-id').read_text() == 'python3.13\n'
    assert (old / '.atr-prefix').read_text() == str(old) + '\n'
    assert run(checkout, 'run_local.sh').returncode == 0
