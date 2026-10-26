"""Synthetic Skill integration; never connect to a model, desktop or instrument."""
import json
from copy import deepcopy

import pytest

from agents.equipment.agent import LabEquipmentAgent
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode
from tests.unit.test_equipment_agent import _saved_recording, _state
from tests.unit.test_equipment_computer_use_runner import harness
from utils.equipment_computer_use_settings import save_profile_settings
from utils.equipment_skill_runtime import EquipmentSkillRegistry, SkillContractError, canonical_sha256, validate_skill_package


def setup(tmp_path, monkeypatch, decisions=None):
    h = harness(tmp_path, monkeypatch, decisions)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    package = registry.create_draft(recording=_saved_recording(), skill_id="computer_use_demo_v1", version="1.0.0",
        target_profile="windows_desktop_v1", model_snapshot={"provider": "vllm", "model": "endpoint:selected"})
    workflow = deepcopy(package["workflow"])
    workflow["computer_use"] = h.package["workflow"]["computer_use"]
    registry.update_workflow("computer_use_demo_v1", "1.0.0", workflow, expected_workflow_sha256=package["manifest"]["workflow_sha256"])
    package = registry.compile("computer_use_demo_v1", "1.0.0")
    registry.validate("computer_use_demo_v1", "1.0.0")
    registry.mark_deployed("computer_use_demo_v1", "1.0.0", bridge_id="worker1", deployment_sha256=canonical_sha256(package["programs"]))
    h.ctx.paths.memory_root = tmp_path / "memory"
    h.ctx.paths.memory_root.mkdir()
    h.ctx.tools = ToolRegistry()
    h.ctx.tools.register("equipment.pyautogui.run", lambda _: {"ok": False, "status": "blocked", "failure_code": "unexpected_legacy_dispatch"})
    for operation in ("acquire", "observe", "act", "status", "verify", "release"):
        h.ctx.tools.register("equipment.pyautogui.computer_use_" + operation,
            lambda payload, operation=operation: h.worker.handle(operation, payload, "principal"))
    settings_path = h.ctx.paths.memory_root / "equipment_workspace_settings.json"
    monkeypatch.setattr(LabEquipmentAgent, "_WORKSPACE_SETTINGS_PATH", settings_path)
    save_profile_settings(settings_path, "windows_desktop_v1", {"execution_mode": "computer_use"})
    state = _state(mode=Mode.LIVE, experiment_spec={"equipment_profile_id": "windows_desktop_v1", "specimen_id": "spec1", "confirm_live_execute": True})
    request = {"skill_id": "computer_use_demo_v1", "version": "1.0.0", "target_profile": "windows_desktop_v1",
        "registry_root": str(registry.root), "sequence_id": "sequence1", "completion_scope": "skill_step", "skip_profile_vision_preflight": True}
    return h, registry, state, request, settings_path


@pytest.mark.asyncio
async def test_real_skill_path_uses_runner_then_existing_verification(tmp_path, monkeypatch):
    h, registry, state, request, _ = setup(tmp_path, monkeypatch, ["act", "complete"])
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert result.success, result.data
    assert h.desktop.effects == 1
    execution = result.data["equipment_skill_execution"]
    assert execution["state"] == "COMPLETED"
    assert execution["runtime_execution"]["lifecycle"] == "COMPLETED"
    assert result.data["equipment_result"]["computer_use"]["turns"] == 2
    assert "lease_token" not in json.dumps(result.data)
    assert "endpoint-secret" not in json.dumps(result.data)


@pytest.mark.asyncio
async def test_module_model_timeout_bounds_pinned_computer_use(tmp_path, monkeypatch):
    import asyncio
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage
    async def slow_model(prompt):
        await asyncio.sleep(0.5)
        return "act"
    h, _, state, request, _ = setup(tmp_path, monkeypatch, [slow_model])
    ctx = ModuleRuntimeContext(h.ctx, {"id": "equipment", "timeout_s": 0.01}, Stage.EQUIPMENT, state=state)
    result = await LabEquipmentAgent()._run_equipment_skill(state, ctx, request)
    assert not result.success
    assert result.data["equipment_result"]["failure_code"] == "block_timeout"
    assert h.desktop.effects == 0 and h.worker.state["lease"] is None


@pytest.mark.asyncio
async def test_enclosing_budget_is_not_renewed_by_each_turn(tmp_path, monkeypatch):
    import asyncio
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage
    async def short_turn(prompt):
        await asyncio.sleep(0.04)
        return "wait"
    h, _, state, request, _ = setup(tmp_path, monkeypatch, [short_turn] * 8)
    ctx = ModuleRuntimeContext(h.ctx, {"id": "equipment", "timeout_s": 0.12}, Stage.EQUIPMENT, state=state)
    # Keep this test focused on the real module's budget, not notification UI.
    ctx._notify_model_call = h.ctx._notify_model_call
    result = await LabEquipmentAgent()._run_equipment_skill(state, ctx, request)
    assert not result.success
    assert result.data["equipment_result"]["failure_code"] == "block_timeout"
    assert 2 <= len(h.prompts) < 8
    assert h.desktop.effects == 0 and h.worker.state["lease"] is None


@pytest.mark.asyncio
async def test_release_failure_never_completes_existing_skill_runtime(tmp_path, monkeypatch):
    h, _, state, request, _ = setup(tmp_path, monkeypatch)
    h.ctx.tools.register("equipment.pyautogui.computer_use_release", lambda _: {"ok": False, "status": "blocked"})
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert not result.success
    assert result.data["equipment_result"]["failure_code"] == "release_requires_operator"
    assert result.data["equipment_skill_execution"]["state"] != "COMPLETED"


@pytest.mark.asyncio
async def test_settings_change_cannot_resume_operator_run_as_legacy(tmp_path, monkeypatch):
    h, registry, state, request, path = setup(tmp_path, monkeypatch, ["needs_operator"])
    agent = LabEquipmentAgent()
    first = await agent._run_equipment_skill(state, h.ctx, request)
    assert not first.success
    save_profile_settings(path, "windows_desktop_v1", {"execution_mode": "skill_flow"})
    later = await agent._run_equipment_skill(state, h.ctx, request)
    assert not later.success
    assert later.data["equipment_handoff"]["failure_code"] == "resume_requires_operator"
    assert h.desktop.effects == 0
    assert later.data["equipment_skill_execution"]["execution_id"] == first.data["equipment_skill_execution"]["execution_id"]


def test_invalid_policy_cannot_be_saved_and_policy_tamper_invalidates_skill(tmp_path, monkeypatch):
    h, registry, _, _, _ = setup(tmp_path, monkeypatch)
    path = registry.root / "computer_use_demo_v1/1.0.0/workflow.json"
    workflow = json.loads(path.read_text())
    workflow["computer_use"]["postconditions"] = []
    from utils.equipment_skill_workflow import validate_editable_workflow
    checked = validate_editable_workflow(workflow)
    assert not checked["ok"]
    path.write_text(json.dumps(workflow))
    with pytest.raises(SkillContractError, match="workflow hash mismatch"):
        validate_skill_package(path.parent)


@pytest.mark.asyncio
async def test_tampered_deployed_policy_never_reaches_runner(tmp_path, monkeypatch):
    h, registry, state, request, _ = setup(tmp_path, monkeypatch)
    path = registry.root / "computer_use_demo_v1/1.0.0/workflow.json"
    workflow = json.loads(path.read_text())
    workflow["computer_use"]["application"]["window_title"] = "other app"
    path.write_text(json.dumps(workflow))
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert not result.success
    assert result.data["equipment_handoff"]["failure_code"] == "SKILL_CONTRACT_INVALID"
    assert h.prompts == []


def test_registered_transport_keeps_original_alias_credentials_and_releases_cache(tmp_path, monkeypatch):
    import httpx
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    tools = ToolRegistry()
    bridge = register_equipment_tools(tools, {"devices": {"equipment": {"mode": "live", "windows_pyautogui": {
        "allow_live_execute": True, "connection_memory_path": str(tmp_path / "connections.json")}}}}, repo_root=tmp_path)
    memory = {"selected_candidate": "same", "candidates": {"same": {"bridge_url": "http://original.invalid", "internal_key": "original-secret", "allow_live_execute": True}}}
    bridge._write_connection_memory(memory)
    observed = []
    def server(req):
        observed.append((str(req.url), req.headers.get(bridge.config.token_header)))
        if req.url.path == "/capabilities":
            return httpx.Response(200, json={"ok": True, "computer_use_v1": True})
        op = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"ok": True, "status": {"acquire": "acquired", "release": "released", "status": "completed"}[op], "session_id": "s", "lease_token": "lease-secret"})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(server), **kwargs))
    payload = {"execution_id": "e", "run_id": "r", "cycle_id": "1", "specimen_id": "s", "equipment_profile_id": "utm_windows_v1", "bridge_id": "same", "runtime_mode": "live"}
    assert tools.call("equipment.pyautogui.computer_use_acquire", payload)["ok"]
    memory["candidates"]["same"].update(bridge_url="http://replacement.invalid", internal_key="replacement-secret")
    bridge._write_connection_memory(memory)
    bridge.config.token_env = "DIFFERENT_TOKEN_ENV"
    assert tools.call("equipment.pyautogui.computer_use_status", {**payload, "session_id": "s", "lease_token": "lease-secret", "action_id": "a"})["ok"]
    assert all(url.startswith("http://original.invalid/") and token == "original-secret" for url, token in observed)
    assert tools.call("equipment.pyautogui.computer_use_status", {**payload, "equipment_profile_id": "windows_desktop_v1"})["failure_code"] == "execution_identity_mismatch"
    assert tools.call("equipment.pyautogui.computer_use_release", payload)["ok"]
    count = len(observed)
    assert tools.call("equipment.pyautogui.computer_use_status", payload)["failure_code"] == "resume_requires_operator"
    assert len(observed) == count


def test_computer_use_tool_artifacts_redact_lease(tmp_path):
    from utils.agent_artifact_archive import _public
    public = _public({"payload": {"lease_token": "lease-secret"}, "result": {"lease_token": "lease-secret"}})
    assert "lease-secret" not in json.dumps(public)


@pytest.mark.asyncio
async def test_settings_must_be_durable_before_any_execution(tmp_path, monkeypatch):
    h, registry, state, request, _ = setup(tmp_path, monkeypatch)
    import utils.equipment_skill_runtime as runtime
    monkeypatch.setattr(runtime.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk unavailable")))
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert not result.success
    assert result.data["equipment_handoff"]["failure_code"] == "SKILL_CONTRACT_INVALID"
    assert not h.prompts and h.desktop.effects == 0


@pytest.mark.asyncio
async def test_real_flow_freezes_settings_across_two_skill_blocks(tmp_path, monkeypatch):
    h, registry, state, _, path = setup(tmp_path, monkeypatch, ["complete", "complete"])
    state.current_experiment_spec["equipment_skill_registry_root"] = str(registry.root)
    flow = {"schema": "atr.equipment_skill_flow.v1", "flow_id": "demo", "profile_id": "windows_desktop_v1", "agentic_task_id": "", "blocks": [
        {"id": block_id, "label": block_id, "skill": {"skill_id": "computer_use_demo_v1", "skill_version": "1.0.0"},
         "agentic": {"task": "demo", "completed": target, "failed": "__blocked__"}, "vision": {"enabled": False}}
        for block_id, target in [("first", "second"), ("second", "__complete__")]]}
    first = True
    original_verify = h.desktop.verify
    def change_settings(*args):
        nonlocal first
        if first:
            save_profile_settings(path, "windows_desktop_v1", {"execution_mode": "skill_flow", "computer_use": {"max_turns": 1}})
            first = False
        return original_verify(*args)
    h.desktop.verify = change_settings
    checkpoint = {}
    result = await LabEquipmentAgent()._run_equipment_skill_flow(state, h.ctx, flow, checkpoint=checkpoint)
    assert result.success, result.data
    assert len(h.prompts) == 2
    assert checkpoint["execution_settings"]["execution_mode"] == "computer_use"
    assert checkpoint["execution_settings"]["computer_use"]["max_turns"] == 64
    assert checkpoint["computer_use_model_selection"]["model"] == "endpoint:selected"


@pytest.mark.asyncio
async def test_guarded_tool_wrapper_preserves_pinned_identity_on_release(tmp_path, monkeypatch):
    h, _, state, _, _ = setup(tmp_path, monkeypatch)
    captured = []
    h.ctx.tools.register("equipment.pyautogui.computer_use_release", lambda payload: captured.append(dict(payload)) or {"ok": True})
    state.current_experiment_spec["equipment_profile_id"] = "utm_windows_v1"
    await LabEquipmentAgent()._call_tool(h.ctx, "equipment.pyautogui.computer_use_release", {"equipment_profile_id": "windows_desktop_v1"}, state=state)
    assert captured[0]["equipment_profile_id"] == "windows_desktop_v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["specimen", "cycle"])
async def test_resume_identity_cannot_reuse_previous_specimen_completion(tmp_path, monkeypatch, changed):
    h, _, state, request, _ = setup(tmp_path, monkeypatch)
    agent = LabEquipmentAgent()
    first = await agent._run_equipment_skill(state, h.ctx, request)
    assert first.success
    if changed == "specimen":
        state.current_experiment_spec["specimen_id"] = "different-specimen"
    else:
        state.loop_count += 1
    later = await agent._run_equipment_skill(state, h.ctx, request)
    assert not later.success
    assert later.data["equipment_handoff"]["failure_code"] == "SKILL_CONTRACT_INVALID"
