"""Opt-in real source-install acceptance, inside a disposable OS sandbox only.

The caller exports tracked source (no old .venv/private data) to a path containing
spaces, mounts it at ATR_PORTABLE_CHECKOUT, and attests the original namespaces.
Run the bootstrap test first with the offline uv cache mounted at .cache/uv;
run the remaining tests in a second sandbox WITHOUT that cache mount. See the
portable-installation evidence document for the exact reproducible commands.
No experiment is started. No fake executable replaces Python, uv, doctor or serve.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest


@pytest.fixture(scope="module")
def checkout() -> Path:
    selected = os.environ.get("ATR_PORTABLE_CHECKOUT")
    if not selected:
        pytest.skip("explicit isolated portable-installation acceptance only")
    namespaces = json.loads(os.environ["ATR_PORTABLE_HOST_NAMESPACES"])
    assert set(namespaces) == {"pid", "net", "mnt", "ipc", "user"}
    for name, host in namespaces.items():
        assert os.readlink(f"/proc/self/ns/{name}") != host
    assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
    assert not Path("/home/jin").exists(), "original source/home/cache exposed"
    for device in ("/dev/video0", "/dev/nvidia0", "/dev/ttyUSB0"):
        assert not Path(device).exists()
    root = Path(selected)
    assert root.is_absolute() and " " in str(root)
    assert Path.home() == Path("/tmp/new-user")
    return root


def child_environment(**overrides: str) -> dict[str, str]:
    # In particular, no validation interpreter/site, PYTHONPATH or host secrets.
    return {
        "PATH": "/usr/bin:/bin", "HOME": "/tmp/new-user",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "AUTONOMOUS_USE_REAL_LLM_IN_TEST": "0",
        "AUTONOMOUS_ALLOW_MOCK_FALLBACK": "1", "AUTONOMOUS_BACKEND": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:9", "NEMOCLAW_AUTO_START_PROXY": "0",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "ATR_CPU_WORKERS": "1", "MPLBACKEND": "Agg", **overrides,
    }


def invoke(args, *, cwd=Path("/tmp/unrelated"), env=None, timeout=120):
    return subprocess.run(args, cwd=cwd, env=env or child_environment(),
                          text=True, capture_output=True, timeout=timeout)


def test_bootstrap_creates_fresh_core_without_global_launcher(checkout):
    """Catches global-CLI default regressions and non-frozen/foreign env reuse."""
    assert not (checkout / ".venv").exists(), "export source, never copy an installed env"
    env = child_environment(UV_BIN="/uv", UV_OFFLINE="1", UV_NO_BUILD="1",
                            UV_LINK_MODE="hardlink", PYTHON_BIN="/usr/bin/python3")
    command = ["bash", str(checkout / "runtime/install/bootstrap_linux.sh")]
    dry = invoke([*command, "--dry-run"], env=env)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert not (checkout / ".venv").exists()
    assert not (checkout / ".env").exists()
    result = invoke(command, env=env, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (checkout / ".venv/.atr-prefix").read_text().strip() == str(checkout / ".venv")
    assert (checkout / "installation.manifest.local.json").is_file()
    assert not (Path.home() / ".local/bin/atr").exists()
    assert not (Path.home() / ".bashrc").exists()


@pytest.fixture
def profile(tmp_path):
    target = tmp_path / "external profile.json"
    target.write_text(json.dumps({"schema": "atr.installation.v1", "resources": {
        "utm": {"yolo_model_path": "model store/detector.pt"}}}))
    return target


def test_relocated_python_config_and_writes_belong_to_new_checkout(checkout, profile):
    """Catches stale editable imports, profile-relative resolution and old stores."""
    cache = checkout / ".cache/uv"
    assert not Path("/uv").exists(), "remove installer executable mount"
    assert not cache.exists() or not any(cache.iterdir()), "remove install cache mount"
    code = """
import json, sys
from pathlib import Path
import fastapi, torch, botorch, gpytorch
import app, utils.config_loader as loader
from utils.runtime_paths import current_paths
p = current_paths()
c = loader.load_all_configs(p.runtime_root / 'configs', paths=p)
out = p.output_root / 'portable-origin-probe.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('{}')
print(json.dumps({'prefix': sys.prefix, 'app': app.__file__, 'loader': loader.__file__,
 'dependencies': [m.__file__ for m in (fastapi, torch, botorch, gpytorch)],
 'repository': str(p.repository_root), 'output': str(out),
 'config': c['devices']['devices']['utm_vision_runtime']['environment']['YOLO_MODEL_PATH']}))
"""
    result = invoke([str(checkout / ".venv/bin/python"), "-c", code],
                    cwd=checkout / "runtime",
                    env=child_environment(ATR_INSTALL_PROFILE=str(profile)))
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["prefix"] == str(checkout / ".venv")
    assert data["repository"] == str(checkout)
    assert data["output"] == str(checkout / "outputs/portable-origin-probe.json")
    assert Path(data["output"]).is_file()
    assert data["app"] == str(checkout / "runtime/app/__init__.py")
    assert data["loader"] == str(checkout / "runtime/utils/config_loader.py")
    assert all(Path(path).is_relative_to(checkout / ".venv") for path in data["dependencies"])
    assert data["config"] == str(profile.parent / "model store/detector.pt")


def test_doctor_uses_selected_profile_without_starting_integrations(checkout, profile):
    """Catches doctor loading another source/config or ignoring required resources."""
    command = [str(checkout / ".venv/bin/python"),
               str(checkout / "runtime/scripts/doctor.py"), "--json"]
    env = child_environment(ATR_INSTALL_PROFILE=str(profile))
    core = invoke([*command, "--core-only"], env=env)
    assert core.returncode == 0, core.stdout + core.stderr
    assert json.loads(core.stdout)["ok"] is True
    selected = invoke([*command, "--integration", "utm"], env=env)
    assert selected.returncode != 0
    data = json.loads(selected.stdout)
    assert data["ok"] is False
    assert any(row["category"] == "utm" and row["level"] == "fail" for row in data["results"])
    assert not (profile.parent / "model store").exists()


def test_launcher_refuses_stale_environment_before_server_start(checkout):
    """Catches removal of the moved-prefix launch guard; restored even on failure."""
    marker = checkout / ".venv/.atr-prefix"
    before = marker.read_bytes()
    try:
        marker.write_text("/previous-user/old-checkout/.venv\n")
        result = invoke(["bash", str(checkout / "runtime/install/run_local.sh")], timeout=15)
        assert result.returncode != 0
        assert "rebuild" in result.stderr.lower()
    finally:
        marker.write_bytes(before)


def test_actual_local_launcher_serves_idle_gui_and_test_profiles(checkout, profile, tmp_path):
    """Catches launcher cwd/profile handoff failures and clean-core app import gaps."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    cwd = Path("/tmp/unrelated")
    env = child_environment(
        AX4LAB_HOST="127.0.0.1", AX4LAB_PORT=str(port),
        AUTONOMOUS_RELOAD="0", AUTONOMOUS_WORKERS="1",
        ATR_INSTALL_PROFILE=os.path.relpath(profile, cwd),
        PYTHONPATH="/nonexistent/contaminating-site", PYTHONHOME="/nonexistent/foreign-python",
    )
    log = tmp_path / "launcher.log"
    with log.open("w+") as output:
        process = subprocess.Popen(["bash", str(checkout / "runtime/install/run_local.sh")],
                                   cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            while True:
                assert process.poll() is None, log.read_text()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as response:
                        state = json.load(response)
                    break
                except (urllib.error.URLError, TimeoutError):
                    assert time.monotonic() < deadline, log.read_text()
                    time.sleep(0.1)
            assert state["state"]["mode"] == "test"
            assert state["state"]["stage"] == "idle"
            assert state["state"]["loop_count"] == 0
            assert Path(state["logs"]["json"]).is_relative_to(checkout / "runs")
            for route in ("/", "/live", "/ide", "/api/test-mode-execution-profiles"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{route}", timeout=15) as response:
                    assert response.status == 200
                    assert response.read()
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
