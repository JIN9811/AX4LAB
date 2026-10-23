"""Portable Isaac defaults; only build commands and resolve paths, never launch."""
from pathlib import Path
from types import SimpleNamespace
import sys

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from mcp_tools.lerobot_schemas import IsaacLabSyntheticRequest


def test_isaac_command_defaults_follow_profile_and_keep_explicit_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bridge = object.__new__(LeRobotBridge)
    bridge.config = LeRobotBridgeConfig.from_config({'conda_executable':'/bin/true', 'conda_env_name':'test-env',
        'isaac_lab_path':str(tmp_path / 'IsaacLab'), 'isaac_sim_python':str(tmp_path / 'IsaacSim/python.sh')}, repo_root=tmp_path)
    request = IsaacLabSyntheticRequest(dataset_path=str(tmp_path / "dataset"))
    command = bridge._isaac_lab_live_e2e_command(request)
    assert command[command.index("--isaac-lab-path") + 1] == str(tmp_path / "IsaacLab")
    assert command[command.index("--isaac-sim-python") + 1] == str(tmp_path / "IsaacSim/python.sh")
    explicit = request.model_copy(update={"isaac_lab_path": "/opt/lab", "isaac_sim_python": "/opt/sim/python.sh"})
    command = bridge._isaac_lab_live_e2e_command(explicit)
    assert command[command.index("--isaac-lab-path") + 1] == "/opt/lab"
    assert command[command.index("--isaac-sim-python") + 1] == "/opt/sim/python.sh"


def test_isaac_receiver_paths_keep_overrides_and_no_missing_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, repo_root=tmp_path))
    for resolve, key, env, filename in (
        (bridge._isaac_mirror_receiver_isaac_sim_executable,
         "isaac_mirror_receiver_isaac_sim_executable", "ATR_ISAAC_SIM_EXECUTABLE", "isaac-sim.sh"),
        (bridge._isaac_mirror_receiver_python,
         "isaac_mirror_receiver_python", "ATR_ISAAC_MIRROR_RECEIVER_PYTHON", "python.sh"),
    ):
        monkeypatch.delenv(env, raising=False)
        bridge.config.isaac_sim_python = ''
        assert resolve({}) == ''
        executable = tmp_path / "IsaacSim" / filename
        executable.parent.mkdir(exist_ok=True)
        executable.touch()
        bridge.config.isaac_sim_python = str(tmp_path / 'IsaacSim/python.sh')
        assert resolve({}) == str(executable)
        monkeypatch.setenv(env, "/opt/environment-command")
        assert resolve({}) == "/opt/environment-command"
        assert resolve({key: "/opt/explicit-command"}) == "/opt/explicit-command"
