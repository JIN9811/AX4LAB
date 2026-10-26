"""Offline diagnostics: real config/files, with forbidden operation tripwires."""
import builtins
from dataclasses import fields
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from scripts import doctor as module
from utils.runtime_paths import RuntimePaths


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "new user" / "AX4 LAB"
    runtime = root / "runtime"
    values = {field.name: root / field.name for field in fields(RuntimePaths)}
    values.update(repository_root=root, runtime_root=runtime, system_root=root / "system")
    paths = RuntimePaths(**values)
    for name in ("app/main.py", "app/serve.py", "configs/system.yaml", "configs/models.yaml",
                 "configs/devices.yaml", "configs/lerobot.yaml", "requirements.txt", "install/install_cli.sh"):
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".yaml" else "")
    (root / ".env.example").touch()
    (root / ".gitignore").write_text(".env\nmemory/\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.delenv("ATR_INSTALL_PROFILE", raising=False)
    # Minimal-dependency fixture tests configuration separately from host installation.
    monkeypatch.setattr(module, "CORE_IMPORTS", ["yaml"])
    return paths


def profile(paths, resources):
    target = paths.repository_root / "installation.local.json"
    target.write_text(json.dumps({"schema": "atr.installation.v1", "resources": resources}))


def config(paths, name, value):
    (paths.runtime_root / "configs" / f"{name}.yaml").write_text(yaml.safe_dump(value))


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 99\n")
    path.chmod(0o755)
    return str(path)


def forbidden(*args, **kwargs):
    # BaseException prevents broad diagnostic Exception handlers hiding violations.
    raise ForbiddenOperation("doctor attempted a forbidden runtime operation")


def test_offline_doctor_does_not_certify_llm_readiness(checkout, monkeypatch):
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    rows = module.Doctor(paths=checkout, core_only=True).run()
    assert any(row["name"] == "LLM readiness" and row["status"] == "unverified"
               and row["level"] == "warn" for row in rows)


class ForbiddenOperation(BaseException):
    pass


@pytest.mark.parametrize('unexpected_error', [False, True])
def test_cli_endpoint_mapping_errors_keep_redacted_json(checkout, monkeypatch, capsys, unexpected_error):
    config(checkout, 'devices', {'custom': {1: 'ordinary YAML key', 'endpoint_url':
           'https://operator:private-password@example.invalid/path?token=private-query'}})
    monkeypatch.setattr(module, 'current_paths', lambda: checkout)
    monkeypatch.setattr(sys, 'argv', ['doctor', '--json', '--core-only'])
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    if unexpected_error:
        def broken_walk(self):
            raise RuntimeError('private-password private-query')
        monkeypatch.setattr(module.Doctor, 'check_endpoints', broken_walk)
    code = module.main()
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['ok'] == (code == 0)
    assert isinstance(result['results'], list)
    assert 'private-password' not in output and 'private-query' not in output
    if unexpected_error:
        assert code == 1
        assert any(row['name'] == 'endpoints' and row['level'] == 'fail' for row in result['results'])
    else:
        assert any(row['name'] == 'endpoint: devices.custom.endpoint_url' for row in result['results'])


@pytest.mark.parametrize("core_only", [False, True])
def test_default_does_not_bootstrap_import_sdks_connect_or_spawn(checkout, monkeypatch, core_only):
    original_import = builtins.__import__
    blocked = ("app.main", "app.bootstrap", "pyrealsense2", "torch", "botorch", "pyautogui", "paho", "pymcprotocol")

    def guarded(name, *args, **kwargs):
        if name.startswith(blocked):
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(importlib, "import_module", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    doctor = module.Doctor(paths=checkout, core_only=core_only)
    results = doctor.run()
    assert not any("forbidden" in row["detail"] for row in results)
    assert "FastAPI app" not in {row["name"] for row in results}
    assert any(row.get("category") == "optional" and row.get("status") == "not_selected" for row in results)


@pytest.mark.parametrize("integration", ["utm", "realsense", "lerobot", "bambu", "prusa", "isaac"])
def test_selected_missing_resources_fail_but_unused_do_not(checkout, integration):
    doctor = module.Doctor(paths=checkout, integrations=[integration])
    results = doctor.run()
    assert doctor.exit_code() == 1
    assert any(row["level"] == "fail" and row.get("category") == integration for row in results)
    assert all(row["level"] != "fail" for row in results if row.get("category") == "optional")


def test_profile_utm_resources_and_ros_prefix_are_inspected_without_execution(checkout, monkeypatch):
    workspace = checkout.repository_root / "external UTM"
    workspace.mkdir()
    script = executable(workspace / "scripts/start_utm_vision_stack.sh")
    model = workspace / "yolo.pt"
    model.write_bytes(b"not a model; must never load")
    setup = workspace / "install/setup.bash"
    executable(setup)
    profile(checkout, {"utm": {"workspace_root": str(workspace), "script_path": script,
                               "yolo_model_path": str(model), "ros_setup_paths": [str(setup)]}})
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    doctor = module.Doctor(paths=checkout, integrations=["utm"])
    results = doctor.run()
    rows = [row for row in results if row.get("category") == "utm"]
    assert rows and not any(row["level"] == "fail" for row in rows)
    assert any(str(setup) in row["detail"] for row in rows)
    assert any("profile:" in row["detail"] for row in results)
    setup.unlink()
    second = module.Doctor(paths=checkout, integrations=["utm"])
    assert any(row["level"] == "fail" and str(setup) in row["detail"] for row in second.run())


def test_slicer_legacy_then_explicit_env_wins_no_fallback(checkout, monkeypatch):
    good = executable(checkout.repository_root / "tools/Bambu Studio")
    missing = str(checkout.repository_root / "missing legacy")
    profile(checkout, {"slicer": {"bambu_studio_executable": good}})
    config(checkout, "devices", {"devices": {"printer": {"bambu": {"slicer": {
        "executable_path": missing, "executable_env": "TEST_BAMBU_EXECUTABLE"}}}}})
    first = module.Doctor(paths=checkout, integrations=["bambu"])
    results = first.run()
    assert any(row["level"] == "fail" and missing in row["detail"] for row in results)
    assert any("legacy_config" in row["detail"] for row in results)
    monkeypatch.setenv("TEST_BAMBU_EXECUTABLE", good)
    second = module.Doctor(paths=checkout, integrations=["bambu"])
    rows = [row for row in second.run() if row.get("category") == "bambu"]
    assert not any(row["level"] == "fail" for row in rows)
    assert any("env:TEST_BAMBU_EXECUTABLE" in row["detail"] for row in rows)


def test_bambu_wrapper_is_not_selected_application_readiness(checkout):
    wrapper = executable(checkout.runtime_root / "install/bambustudio/bambu-studio-wrapper")
    profile(checkout, {"slicer": {"bambu_studio_executable": wrapper}})
    doctor = module.Doctor(paths=checkout, integrations=["bambu"])
    results = doctor.run()
    assert any(row["name"] == "Bambu wrapper" and row["level"] == "ok" for row in results)
    assert any(row["name"] == "Bambu Studio executable" and row["level"] == "fail" for row in results)


def test_wrong_launcher_binding_detected_without_mutation(checkout, monkeypatch):
    launcher = Path(os.environ["HOME"]) / ".local/bin/ax4lab"
    executable(launcher)
    original = f'#!/bin/sh\n# {checkout.repository_root}\nPROJECT_DIR=/other/checkout\n'
    launcher.write_text(original)
    doctor = module.Doctor(paths=checkout)
    results = doctor.run()
    assert any(row["name"] == "ax4lab launcher" and row["level"] == "warn" and "another checkout" in row["detail"] for row in results)
    assert launcher.read_text() == original


def test_legacy_atr_launcher_is_not_an_ax4lab_binding(checkout):
    legacy = Path(os.environ["HOME"]) / ".local/bin/atr"
    executable(legacy)
    doctor = module.Doctor(paths=checkout)
    doctor.check_cli()
    assert len(doctor.results) == 1
    assert doctor.results[0]["name"] == "ax4lab launcher"
    assert "not installed" in doctor.results[0]["detail"]


def test_wrong_loaded_source_origin_is_a_core_failure(checkout, monkeypatch):
    monkeypatch.setitem(sys.modules, "app", SimpleNamespace(__file__="/old/checkout/runtime/app/__init__.py"))
    doctor = module.Doctor(paths=checkout, core_only=True)
    results = doctor.run()
    assert any(row["name"] == "source origin: app" and row["level"] == "fail" for row in results)


def test_endpoint_credentials_queries_and_config_errors_are_redacted(checkout, monkeypatch):
    secret_url = "http://named-user:password-value@localhost:8765/bridge?token=query-secret#fragment-secret"
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", secret_url)
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "header-secret")
    config(checkout, "devices", {"devices": {"equipment": {"windows_pyautogui": {
        "bridge_url_env": "WINDOWS_PYAUTOGUI_BRIDGE_URL", "token_env": "WINDOWS_PYAUTOGUI_BRIDGE_TOKEN"}}}})
    doctor = module.Doctor(paths=checkout)
    text = json.dumps(doctor.run())
    assert "localhost:8765/bridge" in text
    for value in ("named-user", "password-value", "query-secret", "fragment-secret", "header-secret"):
        assert value not in text
    profile(checkout, {"unknown " + secret_url + " header-secret": {}})
    broken = module.Doctor(paths=checkout)
    text = json.dumps(broken.run())
    assert broken.exit_code() == 1
    for value in ("named-user", "password-value", "query-secret", "fragment-secret", "header-secret"):
        assert value not in text


def test_cli_repeatable_selection_preserves_json_and_exit(checkout, monkeypatch, capsys):
    monkeypatch.setattr(module, "current_paths", lambda: checkout)
    monkeypatch.setattr(sys, "argv", ["doctor", "--json", "--integration", "utm", "--integration", "bambu"])
    assert module.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert {"utm", "bambu"} <= {row.get("category") for row in payload["results"]}


def test_core_succeeds_with_missing_unused_integrations(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("ATR_INSTALL_PROFILE", raising=False)
    monkeypatch.setattr(module, "CORE_IMPORTS", ["yaml"])
    monkeypatch.setattr(importlib, "import_module", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    doctor = module.Doctor(core_only=True)
    assert doctor.run()
    assert doctor.exit_code() == 0, doctor.results


def test_missing_core_package_is_failure_without_import(checkout, monkeypatch):
    monkeypatch.setattr(module, "CORE_IMPORTS", ["atr_missing_package_fixture"])
    monkeypatch.setattr(importlib, "import_module", forbidden)
    doctor = module.Doctor(paths=checkout)
    assert any(row["name"] == "python imports" and row["level"] == "fail" for row in doctor.run())


def test_unselected_resource_is_not_inspected(checkout, monkeypatch):
    selected = checkout.repository_root / "unused resource"
    profile(checkout, {"slicer": {"bambu_studio_executable": str(selected)}})
    original = Path.is_file

    def guarded(path):
        if path == selected:
            forbidden()
        return original(path)

    monkeypatch.setattr(Path, "is_file", guarded)
    doctor = module.Doctor(paths=checkout)
    assert any(row["name"] == "bambu" and row["status"] == "not_selected" for row in doctor.run())


def test_core_only_rejects_hardware_and_selected_integrations(checkout):
    with pytest.raises(ValueError):
        module.Doctor(paths=checkout, core_only=True, hardware=True)
    with pytest.raises(ValueError):
        module.Doctor(paths=checkout, core_only=True, integrations=["utm"])


def test_explicit_hardware_remains_separate_from_offline_readiness(checkout, monkeypatch):
    def sdk(name):
        assert name == "pyrealsense2"
        return SimpleNamespace(context=lambda: SimpleNamespace(query_devices=lambda: [object()]))

    monkeypatch.setattr(importlib, "import_module", sdk)
    doctor = module.Doctor(paths=checkout, hardware=True)
    results = doctor.run()
    assert any(row["category"] == "hardware" and "visible devices=1" in row["detail"] for row in results)


def test_moved_venv_prefix_is_failure(checkout):
    marker = checkout.repository_root / ".venv/.atr-prefix"
    marker.parent.mkdir()
    marker.write_text("/previous checkout/.venv\n")
    doctor = module.Doctor(paths=checkout)
    assert any(row["name"] == "virtualenv" and row["level"] == "fail" for row in doctor.run())


def test_windows_paths_are_not_resolved_as_linux_relative_resources(checkout):
    profile(checkout, {"slicer": {"bambu_studio_executable": r"C:\\Program Files\\BambuStudio.exe"}})
    doctor = module.Doctor(paths=checkout, integrations=["bambu"])
    assert any(row["level"] == "fail" and "foreign-platform" in row["detail"] for row in doctor.run())


def test_invalid_yaml_suppresses_secret_containing_source_lines(checkout):
    (checkout.runtime_root / "configs/devices.yaml").write_text('password: [very-secret-value\n')
    doctor = module.Doctor(paths=checkout)
    text = json.dumps(doctor.run())
    assert "very-secret-value" not in text
    assert "configuration/profile could not be loaded" in text


def test_invalid_resource_url_errors_do_not_leak_credentials(checkout):
    profile(checkout, {"slicer": {"bambu_studio_executable": "https://username:secret@host/tool?token=private"}})
    doctor = module.Doctor(paths=checkout, integrations=["bambu"])
    text = json.dumps(doctor.run())
    assert "username" not in text
    assert "secret" not in text.replace("secret ignore policy", "")
    assert "private" not in text


@pytest.mark.parametrize("integration, nesting", [("bambu", "bambu"), ("prusa", "")])
def test_legacy_relative_slicer_uses_repository_not_runtime_root(checkout, integration, nesting):
    tool = executable(checkout.repository_root / "external tools/slicer")
    raw = {"slicer": {"executable_path": "external tools/slicer"}}
    config(checkout, "devices", {"devices": {"printer": {nesting: raw} if nesting else raw}})
    doctor = module.Doctor(paths=checkout, integrations=[integration])
    rows = [row for row in doctor.run() if row["category"] == integration]
    assert not any(row["level"] == "fail" for row in rows), rows
    assert any(tool in row["detail"] for row in rows)


def test_legacy_relative_utm_model_matches_child_workspace_cwd(checkout):
    workspace = checkout.repository_root / "UTM"
    executable(workspace / "scripts/start_utm_vision_stack.sh")
    model = workspace / "yolo.pt"
    model.write_bytes(b"model must not load")
    config(checkout, "devices", {"devices": {"utm_vision_runtime": {
        "workspace_root": str(workspace), "environment": {"YOLO_MODEL_PATH": "yolo.pt"}}}})
    doctor = module.Doctor(paths=checkout, integrations=["utm"])
    rows = [row for row in doctor.run() if row["category"] == "utm"]
    assert not any(row["level"] == "fail" for row in rows), rows
    assert any(str(model) in row["detail"] for row in rows)


def test_legacy_relative_utm_script_matches_external_workspace(checkout):
    workspace = checkout.repository_root / "external UTM"
    script = executable(workspace / "scripts/custom.sh")
    model = workspace / "yolo.pt"
    model.write_bytes(b"not loaded")
    config(checkout, "devices", {"devices": {"utm_vision_runtime": {
        "workspace_root": str(workspace), "script_path": "scripts/custom.sh",
        "environment": {"YOLO_MODEL_PATH": str(model)}}}})
    rows = [row for row in module.Doctor(paths=checkout, integrations=["utm"]).run()
            if row["category"] == "utm"]
    assert not any(row["level"] == "fail" for row in rows), rows
    assert any(script in row["detail"] for row in rows)
