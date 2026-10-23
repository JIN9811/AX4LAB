from __future__ import annotations

from dataclasses import fields
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from utils.config_loader import load_all_configs, load_yaml
from utils.installation_profile import (
    apply_installation_profile,
    installation_metadata,
    load_installation_profile,
)
from utils.runtime_paths import RuntimePaths
from utils.runtime_process import path_metadata


def _paths(tmp_path: Path) -> RuntimePaths:
    values = {field.name: (tmp_path / field.name).resolve() for field in fields(RuntimePaths)}
    values["repository_root"] = (tmp_path / "checkout with spaces").resolve()
    values["runtime_root"] = (values["repository_root"] / "runtime").resolve()
    values["system_root"] = (values["repository_root"] / "system").resolve()
    values["workspace_root"] = (values["repository_root"] / "workspace").resolve()
    return RuntimePaths(**values)


def _write_profile(path: Path, resources: dict[str, object], *, schema: str = "atr.installation.v1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": schema, "resources": resources}), encoding="utf-8")
    return path


def test_absent_checkout_local_profile_is_optional(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    profile = load_installation_profile(paths, environ={"HOME": str(tmp_path / "home")})

    assert profile.source is None
    assert profile.configured is False
    assert profile.resources.utm.workspace_root == ""
    assert installation_metadata(profile) == {}


@pytest.mark.parametrize('home_key', ['HOME', 'USERPROFILE'])
def test_selector_home_uses_injected_environment_not_process_home(tmp_path, home_key):
    injected = tmp_path / 'injected home'
    selected = _write_profile(injected / 'profile.json', {'isaac': {'lab_root': 'lab'}})
    assert str(injected) != os.environ.get('HOME')
    profile = load_installation_profile(_paths(tmp_path), environ={
        home_key: str(injected), 'ATR_INSTALL_PROFILE': '~/profile.json'})
    assert profile.source == selected
    assert profile.resources.isaac.lab_root == str(injected / 'lab')


@pytest.mark.parametrize('field', ['bambu_studio_executable', 'prusa_slicer_executable'])
def test_profile_slicer_executable_retains_alias(tmp_path, field):
    alias = tmp_path / 'selected tools/slicer'
    alias.parent.mkdir()
    alias.symlink_to(sys.executable)
    selected = _write_profile(tmp_path / 'profile.json', {'slicer': {field: 'selected tools/slicer'}})
    profile = load_installation_profile(_paths(tmp_path), environ={'ATR_INSTALL_PROFILE': str(selected)})
    assert getattr(profile.resources.slicer, field) == str(alias)


def test_missing_explicit_profile_is_an_error(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    missing = tmp_path / "missing profile.json"

    with pytest.raises(FileNotFoundError, match="ATR_INSTALL_PROFILE"):
        load_installation_profile(paths, environ={"ATR_INSTALL_PROFILE": str(missing)})


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"schema": "atr.installation.v0", "resources": {}}, "atr.installation.v1"),
        ({"schema": "atr.installation.v1"}, "resources"),
        ({"schema": "atr.installation.v1", "resources": {}, "extra": True}, "Unknown installation profile fields"),
        ({"schema": "atr.installation.v1", "resources": {"mystery": {}}}, "Unknown installation resource groups"),
    ],
)
def test_malformed_schema_and_unknown_keys_are_rejected(
    tmp_path: Path, document: dict[str, object], message: str
) -> None:
    paths = _paths(tmp_path)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_installation_profile(paths, environ={"ATR_INSTALL_PROFILE": str(profile_path)})


@pytest.mark.parametrize(
    ("group", "key"),
    [
        ("utm", "mode"),
        ("realsense", "pose_confidence_threshold"),
        ("lerobot", "command_templates"),
        ("lerobot", "robot_id"),
        ("slicer", "completion_policy"),
        ("slicer", "require_verified_routine"),
    ],
)
def test_policy_and_identity_keys_are_not_profile_resources(
    tmp_path: Path, group: str, key: str
) -> None:
    paths = _paths(tmp_path)
    profile_path = _write_profile(tmp_path / "profile.json", {group: {key: "unsafe"}})

    with pytest.raises(ValueError, match="Unknown .* resource fields"):
        load_installation_profile(paths, environ={"ATR_INSTALL_PROFILE": str(profile_path)})


def test_paths_resolve_from_profile_directory_with_spaces_and_explicit_home(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    profile_path = _write_profile(
        tmp_path / "profiles with spaces" / "installation.json",
        {
            "utm": {
                "workspace_root": "../external resources/UTM workspace",
                "ros_setup_paths": ["../ROS distro/setup.bash", "~/robot overlay/setup.bash"],
            },
            "lerobot": {"dataset_root": "~/model cache/lerobot"},
        },
    )
    fake_home = tmp_path / "different user home"

    profile = load_installation_profile(
        paths,
        environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(fake_home)},
    )

    assert profile.resources.utm.workspace_root == str(
        (profile_path.parent / "../external resources/UTM workspace").resolve()
    )
    assert profile.resources.utm.ros_setup_paths == (
        str((profile_path.parent / "../ROS distro/setup.bash").resolve()),
        str((fake_home / "robot overlay/setup.bash").resolve()),
    )
    assert profile.resources.lerobot.dataset_root == str(
        (fake_home / "model cache/lerobot").resolve()
    )


def test_foreign_platform_absolute_paths_are_preserved(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    windows_executable = r"C:\Program Files\Bambu Studio\bambu-studio.exe"
    windows_workspace = r"D:\Lab Data\UTM"
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {
            "slicer": {"bambu_studio_executable": windows_executable},
            "utm": {"workspace_root": windows_workspace},
        },
    )

    profile = load_installation_profile(
        paths, environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)}
    )

    assert profile.resources.slicer.bambu_studio_executable == windows_executable
    assert profile.resources.utm.workspace_root == windows_workspace


@pytest.mark.parametrize("value", ["$HOME/UTM", "${UTM_ROOT}/src", "%USERPROFILE%\\UTM"])
def test_unresolved_placeholders_are_rejected(tmp_path: Path, value: str) -> None:
    paths = _paths(tmp_path)
    profile_path = _write_profile(tmp_path / "profile.json", {"utm": {"workspace_root": value}})

    with pytest.raises(ValueError, match="placeholder"):
        load_installation_profile(paths, environ={"ATR_INSTALL_PROFILE": str(profile_path)})


def test_profile_fills_only_empty_allowlisted_fields_and_reports_legacy_conflicts(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {
            "utm": {"workspace_root": "external/utm", "yolo_model_path": "models/yolo.pt"},
            "realsense": {"native_python_path": "native/python"},
            "slicer": {"bambu_studio_executable": "bin/bambu studio"},
        },
    )
    profile = load_installation_profile(
        paths, environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)}
    )
    original = {
        "devices": {
            "devices": {
                "utm_vision_runtime": {
                    "workspace_root": "/legacy/operator/UTM",
                    "environment": {"YOLO_MODEL_PATH": ""},
                },
                "specimen_pose_tracker": {"rsusb_pythonpath": ""},
                "printer": {"bambu": {"slicer": {"enabled": True}}},
                "robot": {"mode": "simulator", "robot_id": "operator-robot"},
            }
        },
        "system": {"system": {"completion_policy": "operator", "threshold": 0.75}},
    }

    resolved = apply_installation_profile(original, profile)

    assert resolved is not original
    assert resolved["devices"]["devices"]["utm_vision_runtime"]["workspace_root"] == "/legacy/operator/UTM"
    assert resolved["devices"]["devices"]["utm_vision_runtime"]["environment"]["YOLO_MODEL_PATH"] == str(
        (profile_path.parent / "models/yolo.pt").resolve()
    )
    assert resolved["devices"]["devices"]["specimen_pose_tracker"]["rsusb_pythonpath"] == str(
        (profile_path.parent / "native/python").resolve()
    )
    assert resolved["devices"]["devices"]["printer"]["bambu"]["slicer"]["executable_path"] == str(
        (profile_path.parent / "bin/bambu studio").resolve()
    )
    assert resolved["devices"]["devices"]["robot"] == original["devices"]["devices"]["robot"]
    assert resolved["system"] == original["system"]
    diagnostics = resolved["installation"]["diagnostics"]
    assert diagnostics == [
        {
            "code": "INSTALLATION_PROFILE_CONFLICT",
            "resource": "utm.workspace_root",
            "target": "devices.devices.utm_vision_runtime.workspace_root",
            "winner": "legacy_config",
            "profile_source": str(profile_path.resolve()),
        }
    ]
    assert resolved["installation"]["provenance"]["utm.yolo_model_path"].startswith("profile:")


def test_loading_profile_does_not_mutate_cached_yaml(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    config_dir = paths.runtime_root / "configs"
    config_dir.mkdir(parents=True)
    devices_file = config_dir / "devices.yaml"
    devices_file.write_text(
        "devices:\n  utm_vision_runtime:\n    workspace_root: ''\n",
        encoding="utf-8",
    )
    profile_path = _write_profile(tmp_path / "profile.json", {"utm": {"workspace_root": "UTM"}})
    environ = {"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)}
    before = load_yaml(devices_file)

    resolved = load_all_configs(config_dir, paths=paths, environ=environ)

    assert resolved["devices"]["devices"]["utm_vision_runtime"]["workspace_root"] == str(
        (profile_path.parent / "UTM").resolve()
    )
    assert before == {"devices": {"utm_vision_runtime": {"workspace_root": ""}}}
    assert load_yaml(devices_file) == before


def test_selected_profile_cannot_be_silently_skipped_without_runtime_paths(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "runtime" / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "devices.yaml").write_text("devices: {}\n", encoding="utf-8")
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {"utm": {"workspace_root": "external/UTM"}},
    )

    with pytest.raises(ValueError, match="RuntimePaths.*ATR_INSTALL_PROFILE"):
        load_all_configs(
            config_dir,
            environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)},
        )


def test_explicit_root_lerobot_smoke_fails_before_runtime_import_when_profile_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.lerobot_isaac_lab_e2e_smoke import _bridge

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "lerobot.yaml").write_text("lerobot: {}\n", encoding="utf-8")
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {"lerobot": {"source_root": "external/lerobot"}},
    )
    monkeypatch.setenv("ATR_INSTALL_PROFILE", str(profile_path))

    with pytest.raises(ValueError, match="RuntimePaths.*ATR_INSTALL_PROFILE"):
        _bridge(tmp_path)


def test_environment_executable_override_beats_profile_slicer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from device_bridges.printer_fleet.bridge import BambuSlicerConfig

    paths = _paths(tmp_path)
    config_dir = paths.runtime_root / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "devices.yaml").write_text(
        """
devices:
  printer:
    bambu:
      slicer:
        enabled: true
        executable_env: TEST_BAMBU_EXECUTABLE
""".lstrip(),
        encoding="utf-8",
    )
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {"slicer": {"bambu_studio_executable": "profile/bin/bambu"}},
    )
    profile_executable = profile_path.parent / "profile/bin/bambu"
    profile_executable.parent.mkdir(parents=True)
    profile_executable.write_text("profile", encoding="utf-8")
    profile_executable.chmod(0o755)
    environment_executable = tmp_path / "operator/bin/bambu"
    environment_executable.parent.mkdir(parents=True)
    environment_executable.write_text("environment", encoding="utf-8")
    environment_executable.chmod(0o755)
    resolved = load_all_configs(
        config_dir,
        paths=paths,
        environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)},
    )
    slicer = BambuSlicerConfig.from_dict(
        resolved["devices"]["devices"]["printer"]["bambu"]["slicer"],
        paths=paths,
    )
    monkeypatch.setenv("TEST_BAMBU_EXECUTABLE", str(environment_executable))

    payload = slicer.resolved_payload(paths=paths)

    assert slicer.executable_path == str(profile_executable.resolve())
    assert payload["source"] == "env"
    assert payload["resolved_executable_path"] == str(environment_executable)


def test_train_call_dataset_root_overrides_profile_and_omission_uses_profile(
    tmp_path: Path,
) -> None:
    from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
    from mcp_tools.lerobot_schemas import LeRobotSessionRequest

    paths = _paths(tmp_path)
    config_dir = paths.runtime_root / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "lerobot.yaml").write_text(
        """
lerobot:
  default_profile_id: fake_omx_ai
  dataset_root: ''
  profiles:
    fake_omx_ai:
      profile_id: fake_omx_ai
      display_name: Fake ROBOTIS OMX-AI
      robot_family: robotis_omx
      robot_type: omx_follower
      teleop_type: omx_leader
""".lstrip(),
        encoding="utf-8",
    )
    profile_path = _write_profile(
        tmp_path / "profile.json",
        {"lerobot": {"dataset_root": "profile/datasets"}},
    )
    resolved = load_all_configs(
        config_dir,
        paths=paths,
        environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)},
    )
    bridge = LeRobotBridge(
        LeRobotBridgeConfig.from_config(resolved["lerobot"], paths=paths)
    )
    robot_profile = bridge._profile("fake_omx_ai")  # noqa: SLF001
    assert robot_profile is not None
    request_root = str((tmp_path / "request/datasets").resolve())

    explicit_args = bridge._train_args(  # noqa: SLF001
        robot_profile,
        LeRobotSessionRequest(profile_id="fake_omx_ai", dataset_root=request_root),
    )
    default_args = bridge._train_args(  # noqa: SLF001
        robot_profile,
        LeRobotSessionRequest(profile_id="fake_omx_ai"),
    )

    assert f"--dataset.root={request_root}" in explicit_args
    assert f"--dataset.root={(profile_path.parent / 'profile/datasets').resolve()}" in default_args


def test_filtered_fresh_process_reproduces_profile_and_source_roots_from_unrelated_cwd(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    paths.runtime_root.mkdir(parents=True)
    paths.system_root.mkdir(parents=True)
    layout = tmp_path / "layout.json"
    stores = {
        field.name: str(getattr(paths, field.name))
        for field in fields(RuntimePaths)
        if field.name.endswith("_root") and field.name not in {
            "repository_root", "runtime_root", "system_root", "workspace_root"
        }
    }
    layout.write_text(
        json.dumps(
            {
                "schema": "atr.path_layout.v1",
                "repository_root": str(paths.repository_root),
                "runtime_root": str(paths.runtime_root),
                "system_root": str(paths.system_root),
                "workspace_root": str(paths.workspace_root),
                "defaults": stores,
                "stores": {},
                "candidates": {},
            }
        ),
        encoding="utf-8",
    )
    profile_path = _write_profile(
        tmp_path / "portable profile" / "installation.json",
        {"utm": {"workspace_root": "../equipment/UTM"}},
    )
    profile = load_installation_profile(
        paths,
        environ={"ATR_INSTALL_PROFILE": str(profile_path), "HOME": str(tmp_path)},
    )
    metadata = path_metadata(paths, profile=profile, environ={"ATR_LAYOUT_CONFIG": str(layout)})
    child_script = """
import json
from utils.installation_profile import load_installation_profile
from utils.runtime_paths import current_paths
paths = current_paths()
profile = load_installation_profile(paths)
print(json.dumps({
    'profile': str(profile.source),
    'utm': profile.resources.utm.workspace_root,
    'repository_root': str(paths.repository_root),
    'runtime_root': str(paths.runtime_root),
}, sort_keys=True))
"""
    unrelated = tmp_path / "unrelated cwd"
    unrelated.mkdir()
    child_env = {
        "HOME": str(tmp_path / "filtered home"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        **metadata,
    }

    completed = subprocess.run(
        [sys.executable, "-c", child_script],
        cwd=unrelated,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    child = json.loads(completed.stdout)
    assert child == {
        "profile": str(profile.source),
        "repository_root": str(paths.repository_root),
        "runtime_root": str(paths.runtime_root),
        "utm": profile.resources.utm.workspace_root,
    }
