"""Native Windows subprocess acceptance; never touch desktop, devices or tasks."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

RUNTIME = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='requires native Windows PowerShell')


def powershell(script, *args):
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(script), *args], capture_output=True, text=True)


def test_windows_bootstrap_forwards_literal_host_paths_and_never_starts(tmp_path):
    root = tmp_path / "user's checkout [1] with spaces"
    installer = root / 'runtime/install/bootstrap_windows.ps1'
    installer.parent.mkdir(parents=True)
    shutil.copy2(RUNTIME / 'install/bootstrap_windows.ps1', installer)
    bridge = root / 'runtime/Pyautogui_server_for_window/scripts/install_bridge.ps1'
    bridge.parent.mkdir(parents=True)
    bridge.write_text('''param([string]$DataRoot, [string]$PythonLauncher, [switch]$SetupOnly, [switch]$DryRun)
if (-not $SetupOnly -or -not $DryRun) { throw "unsafe invocation" }
Write-Output $DataRoot
Write-Output $PythonLauncher
''')
    data = str(tmp_path / "data [2] with spaces")
    python = str(tmp_path / "Python [3]/python.exe")
    result = powershell(installer, '-DryRun', '-DataRoot', data, '-PythonLauncher', python)
    assert result.returncode == 0, result.stdout + result.stderr
    assert data in result.stdout and python in result.stdout
    assert not Path(data).exists()


@pytest.mark.parametrize('data', ['/linux/path', 'C:relative', 'relative directory'])
def test_bridge_rejects_non_absolute_host_paths_before_side_effects(tmp_path, data):
    script = tmp_path / 'bridge with spaces/scripts/install_bridge.ps1'
    script.parent.mkdir(parents=True)
    shutil.copy2(RUNTIME / 'Pyautogui_server_for_window/scripts/install_bridge.ps1', script)
    result = powershell(script, '-DryRun', '-SetupOnly', '-DataRoot', data)
    assert result.returncode != 0
    assert 'absolute Windows' in result.stderr
    assert not (script.parent.parent / '.venv').exists()


def test_bridge_dry_run_uses_literal_checkout_and_data_paths(tmp_path):
    script = tmp_path / "bridge [1]'s folder/scripts/install_bridge.ps1"
    script.parent.mkdir(parents=True)
    shutil.copy2(RUNTIME / 'Pyautogui_server_for_window/scripts/install_bridge.ps1', script)
    data = tmp_path / 'data [2]'
    result = powershell(script, '-DryRun', '-SetupOnly', '-DataRoot', str(data))
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(script.parent.parent) in result.stdout
    assert str(data) in result.stdout
    assert not data.exists()
    assert not (script.parent.parent / '.venv').exists()


def test_bridge_propagates_native_environment_creation_failure(tmp_path):
    script = tmp_path / 'bridge/scripts/install_bridge.ps1'
    script.parent.mkdir(parents=True)
    shutil.copy2(RUNTIME / 'Pyautogui_server_for_window/scripts/install_bridge.ps1', script)
    fake = tmp_path / 'fake python.cmd'
    fake.write_text('@exit /b 17\r\n')
    result = powershell(script, '-SetupOnly', '-DataRoot', str(tmp_path / 'data'),
                        '-PythonLauncher', str(fake))
    assert result.returncode != 0
    assert 'creation failed' in result.stderr
    assert not (tmp_path / 'data').exists()
