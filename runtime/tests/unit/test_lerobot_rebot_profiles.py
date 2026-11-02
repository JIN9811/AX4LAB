"""Rebot profiles must retain their native command schemas, without device I/O."""
from pathlib import Path

import pytest
import yaml

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from mcp_tools.lerobot_schemas import LeRobotSessionRequest


@pytest.fixture
def bridge(tmp_path):
    raw = yaml.safe_load((Path(__file__).parents[2] / "configs/lerobot.yaml").read_text())
    cfg = LeRobotBridgeConfig.from_config(raw, repo_root=tmp_path)
    return LeRobotBridge(cfg)


@pytest.mark.parametrize("profile_id,robot,leader", [
    ("rebot_b601_rs", "bi_rebot_b601_follower", "bi_rebot_102_leader"),
    ("rebot_b601_rs_quest", "rebot_vr", "quest3"),
])
def test_rebot_profiles_are_listed_and_selectable(bridge, profile_id, robot, leader):
    profiles = {p["profile_id"]: p for p in bridge.profiles_list()["profiles"]}
    assert profile_id in profiles
    profile = profiles[profile_id]
    assert (profile["robot_type"], profile["teleop_type"]) == (robot, leader)
    assert profile["safety_limits"]["live_enabled"]
    assert not profile["safety_limits"]["allow_policy_rollout"]
    assert profile["supported_workflows"] == ["teleoperate", "record"]
    # Registration alone cannot validate an unconfigured local installation.
    assert not bridge.profiles_validate({"profile_id": profile_id})["ok"]
    selected = bridge.configure({"profile_id": profile_id})
    assert selected["selected_profile_id"] == profile_id
    assert selected["default_profile_id"] == "robotis_omx_ai"


@pytest.mark.parametrize("profile_id", ["rebot_b601_rs", "rebot_b601_rs_quest"])
def test_rebot_preview_never_adds_single_arm_serial_or_fake_ports(bridge, profile_id):
    profile = bridge._profile(profile_id)
    assert profile.profile_id == profile_id
    request = LeRobotSessionRequest(profile_id=profile_id, camera_enabled=False)
    command = bridge._workflow_command(profile, "teleoperate", request, ["--fps=30"])
    assert not any(arg.startswith(("--robot.port=", "--teleop.port=")) for arg in command)
    assert not any("FAKE" in arg for arg in command)
    if profile_id == "rebot_b601_rs":
        assert "--robot.left_arm_config.motor_family=rs" in command
        assert "--robot.right_arm_config.motor_family=rs" in command
        assert "--robot.left_arm_config.can_adapter=socketcan" in command
        assert "--robot.right_arm_config.can_adapter=socketcan" in command
    else:
        assert "--robot.type=rebot_vr" in command
        assert "--teleop.type=quest3" in command


def test_existing_omx_preview_keeps_serial_arguments(bridge):
    profile = bridge._profile("robotis_omx_ai")
    command = bridge._workflow_command(profile, "teleoperate", LeRobotSessionRequest(camera_enabled=False), [])
    assert any(arg.startswith("--robot.port=") for arg in command)
    assert any(arg.startswith("--teleop.port=") for arg in command)
