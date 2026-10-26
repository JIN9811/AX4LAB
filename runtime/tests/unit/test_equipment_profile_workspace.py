"""Independent UTM profiles must not borrow another device's setup."""
import json
from pathlib import Path

import pytest

from utils import equipment_profiles as profiles
from device_bridges.windows_pyautogui.bridge import WindowsPyAutoGUIBridge, WindowsPyAutoGUIBridgeConfig


def store_for(tmp_path):
    cls = getattr(profiles, "EquipmentProfileStore", None)
    assert cls is not None, "equipment profiles need a persistent workspace store"
    return cls(tmp_path / "memory")


def test_new_utm_survives_reload_without_changing_applied_profile(tmp_path):
    store = store_for(tmp_path)
    added = store.create("Other UTM")
    assert added.label == "Other UTM"
    assert added.profile_id != "utm_windows_v1"
    reloaded = profiles.EquipmentProfileRegistry.default(memory_root=tmp_path / "memory")
    assert reloaded.get(added.profile_id).label == "Other UTM"
    assert reloaded.resolve().profile_id == "utm_windows_v1"
    assert added.vision_link == reloaded.get("utm_windows_v1").vision_link
    assert not list((tmp_path / "memory").glob("equipment_profiles/*/equipment_utm_profile.json"))


def test_profile_names_and_ids_cannot_overwrite_or_escape(tmp_path):
    store = store_for(tmp_path)
    store.create("UTM B")
    for name in ("", " ", "UTM B", "UTM", "x" * 81):
        with pytest.raises(ValueError):
            store.create(name)
    for profile_id in ("../outside", "/tmp/test", "missing"):
        with pytest.raises(ValueError):
            store.apply(profile_id)
    assert store.selected_id() == "utm_windows_v1"


def test_delete_removes_custom_profile_but_preserves_historical_files(tmp_path):
    store = store_for(tmp_path)
    profile = store.create("Disposable UTM")
    settings = store.root / "equipment_profiles" / profile.profile_id / "connection.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"saved":true}')
    store.delete(profile.profile_id)
    fresh = profiles.EquipmentProfileRegistry.default(memory_root=store.root)
    with pytest.raises(ValueError, match="Unknown"):
        fresh.get(profile.profile_id)
    assert settings.read_text() == '{"saved":true}'
    assert store.read()["deleted_profiles"] == [{"profile_id": profile.profile_id, "label": "Disposable UTM"}]
    assert store.selected_id() == "utm_windows_v1"
    with pytest.raises(ValueError, match="Unknown"):
        store.apply(profile.profile_id)
    replacement = store.create("Disposable UTM")
    assert replacement.profile_id != profile.profile_id


def test_delete_protects_builtins_and_applied_profile(tmp_path):
    store = store_for(tmp_path)
    custom = store.create("Applied UTM")
    store.apply(custom.profile_id)
    for profile_id in ("utm_windows_v1", "windows_desktop_v1", custom.profile_id):
        with pytest.raises(ValueError):
            store.delete(profile_id)
    assert store.selected_id() == custom.profile_id
    assert profiles.EquipmentProfileRegistry.default(memory_root=store.root).get(custom.profile_id)


def test_bridge_configuration_isolated_and_no_legacy_env_fallback(tmp_path, monkeypatch):
    store = store_for(tmp_path)
    new = store.create("Second UTM")
    legacy = tmp_path / "memory" / "equipment_utm_profile.json"
    legacy.write_text(json.dumps({"target_window": "OLD UTM", "robot_entry_clearance_mm": 150}))
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.0.99:8765")
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "do-not-copy")
    cfg = {"equipment": {"windows_pyautogui": {"registered_programs": {"old_custom": {"sequence": [{"action": "click", "x": 999, "y": 999}]}}}}}
    with profiles.equipment_profile_scope(new.profile_id):
        bridge = WindowsPyAutoGUIBridge(WindowsPyAutoGUIBridgeConfig.from_devices_config(cfg, repo_root=tmp_path))
    assert bridge.connection_status()["bridge_url"] == ""
    assert bridge.connection_status()["token_configured"] is False
    assert bridge.config.utm_profile_memory_path != legacy
    assert "old_custom" not in bridge.config.registered_programs
    assert bridge.utm_profile_status()["profile"].get("target_window") != "OLD UTM"
    bridge.save_utm_profile({"target_window": "NEW UTM"})
    assert json.loads(legacy.read_text())["target_window"] == "OLD UTM"


def test_apply_and_explicit_scope_resolve_different_profiles(tmp_path):
    store = store_for(tmp_path)
    new = store.create("Applied UTM")
    store.apply(new.profile_id)
    registry = profiles.EquipmentProfileRegistry.default(memory_root=tmp_path / "memory")
    assert registry.resolve().profile_id == new.profile_id
    assert registry.resolve(profile_id="utm_windows_v1").profile_id == "utm_windows_v1"
    custom = WindowsPyAutoGUIBridgeConfig.from_devices_config({}, repo_root=tmp_path)
    with profiles.equipment_profile_scope("utm_windows_v1"):
        old = WindowsPyAutoGUIBridgeConfig.from_devices_config({}, repo_root=tmp_path)
    assert custom.connection_memory_path != old.connection_memory_path
    assert old.connection_memory_path == tmp_path / "memory" / "windows_pyautogui_connection.json"


def test_registered_agent_tools_follow_applied_profile_but_respect_pinned_run(tmp_path):
    from mcp_tools.tool_registry import ToolRegistry
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    registry = ToolRegistry()
    register_equipment_tools(registry, {}, repo_root=tmp_path)
    new = store_for(tmp_path).create("Agent UTM")
    store_for(tmp_path).apply(new.profile_id)
    registry.call("equipment.pyautogui.save_utm_profile", {"target_window": "New"})
    result = registry.call("equipment.pyautogui.utm_profile", {})
    assert result["profile"]["target_window"] == "New"
    assert new.profile_id in result["profile_memory_path"]
    old = registry.call("equipment.pyautogui.utm_profile", {"equipment_profile_id": "utm_windows_v1"})
    assert old["profile"].get("target_window") != "New"
    assert Path(old["profile_memory_path"]) == tmp_path / "memory" / "equipment_utm_profile.json"


def test_runtime_evidence_tools_cannot_read_another_profile(tmp_path):
    from mcp_tools.tool_registry import ToolRegistry
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    from utils.equipment_runtime_service import EquipmentRuntimeService
    registry = ToolRegistry()
    register_equipment_tools(registry, {}, repo_root=tmp_path)
    runtime = EquipmentRuntimeService(tmp_path / "memory" / "equipment_runtime")
    execution = runtime.begin(sequence_id="seq", run_id="run", experiment_id="exp", specimen_id="spec",
                              profile_id="utm_windows_v1", mode="test", worker={"worker_id": "old"},
                              execution_ref={"type": "program", "program_id": "utm_compression_start_v1"})
    profile = store_for(tmp_path).create("New device").profile_id
    with profiles.equipment_profile_scope(profile):
        assert registry.call("equipment.runtime.current", {})["execution"] is None
        assert registry.call("equipment.runtime.list", {})["executions"] == []
        assert registry.call("equipment.runtime.get", {"execution_id": execution["execution_id"]})["ok"] is False


@pytest.mark.asyncio
async def test_applied_default_is_pinned_and_tools_cannot_retarget_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.equipment.agent import LabEquipmentAgent
    from agents.base_agent import AgentResult
    from orchestrator.state import OrchestratorState, Mode
    from utils import runtime_paths
    from dataclasses import replace
    paths = replace(runtime_paths.current_paths(), memory_root=tmp_path / "memory", artifact_root=tmp_path / "artifacts")
    monkeypatch.setattr(runtime_paths, "_current", paths)
    store = store_for(tmp_path)
    new = store.create("Another device")
    store.apply("utm_windows_v1")
    state = OrchestratorState(run_id="profile-pin", experiment_id="profile-pin", mode=Mode.TEST)
    state.current_experiment_spec = {}
    agent = LabEquipmentAgent()
    async def execute(state, ctx):
        assert state.current_experiment_spec["equipment_profile_id"] == "utm_windows_v1"
        store.apply(new.profile_id)
        assert agent._selected_profile(state).profile_id == "utm_windows_v1"
        return AgentResult(success=True, summary="pin checked", data={})
    monkeypatch.setattr(agent, "_run_profile_bound", execute)
    await agent.run(state, SimpleNamespace(paths=paths))


def test_apply_default_worker_overrides_legacy_environment_route(tmp_path, monkeypatch):
    from mcp_tools.tool_registry import ToolRegistry
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    monkeypatch.setenv("WINDOWS_PYAUTOGUI_BRIDGE_URL", "http://192.168.0.99:8765")
    registry = ToolRegistry()
    bridge = register_equipment_tools(registry, {}, repo_root=tmp_path)
    bridge.save_connection({"candidate_alias": "chosen", "bridge_url": "http://192.168.0.24:8765", "token": "private"})
    assert bridge.connection_status()["bridge_url"] == "http://192.168.0.99:8765"
    store_for(tmp_path).apply("utm_windows_v1")
    assert registry.call("equipment.pyautogui.connection_status", {})["bridge_url"] == "http://192.168.0.24:8765"
