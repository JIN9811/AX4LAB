import json
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

import app.main as main
from backends.llm_backend import LLMResponse
from utils.equipment_skill_runtime import EquipmentSkillRegistry
from utils.equipment_profiles import EquipmentProfileRegistry


@pytest.fixture
def setup(tmp_path, monkeypatch):
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    package = registry.create_draft(recording={
        "schema": "atr.equipment_recording.v1", "status": "saved", "recording_id": "demo",
        "events": [{"kind": "key_press", "at_ms": 0, "key": "f1"}, {"kind": "key_press", "at_ms": 0, "key": "esc"}],
    }, skill_id="demo", version="1.0.0", target_profile="utm_test", model_snapshot={})
    monkeypatch.setattr(main, "_equipment_skill_registry", lambda: registry)
    template = EquipmentProfileRegistry.default(memory_root=tmp_path).get("utm_windows_v1")
    profiles = EquipmentProfileRegistry(tuple(replace(template, profile_id=p) for p in ("utm_test", "another")), "utm_test")
    monkeypatch.setattr(main, "_equipment_profile_registry", lambda: profiles)
    monkeypatch.setattr(main, "_equipment_skill_model_snapshot", lambda: {
        "provider": "split-test", "model": "selected-endpoint", "capabilities": {"vision": True}})
    import mcp_tools.source_tools as sources
    monkeypatch.setattr(sources, "source_context", lambda ctx, query, top_k: {"status": "ready", "notes": [], "citations": []})
    calls = []
    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return LLMResponse(text=json.dumps({"parts": [
                {"name": "Open", "step_ids": ["step-001"]}, {"name": "Close", "step_ids": ["step-002"]}
            ], "branches": []}), model="selected-endpoint", raw={})
    monkeypatch.setitem(main.controller._deps.agent_context.primary_backends, "split-test", Backend())
    return TestClient(main.app), registry, package, calls


def test_selected_model_proposal_confirm_and_latest_use_existing_registry(setup):
    client, registry, package, calls = setup
    base = "/api/equipment/skills/demo/1.0.0/split-proposal"
    response = client.post(base + "?profile_id=utm_test", json={"expected_workflow_sha256": package["manifest"]["workflow_sha256"]})
    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    assert len(registry.list()) == 1
    assert calls[0]["model"] == "selected-endpoint"
    prompt = json.loads(calls[0]["user_prompt"])
    assert prompt["source_knowledge"]["status"] == "ready"
    assert [s["step_id"] for s in prompt["workflow"]["steps"]] == ["step-001", "step-002"]
    confirm = base + "/" + proposal["proposal_id"] + "/confirm?profile_id=utm_test"
    assert client.post(confirm, json={"confirm_create": False}).status_code == 400
    assert len(registry.list()) == 1
    result = client.post(confirm, json={"confirm_create": True})
    assert result.status_code == 200, result.text
    assert len(result.json()["result"]["children"]) == 2
    assert registry.get("demo", "1.0.0") == package
    assert client.get(base + "/latest?profile_id=utm_test").json()["result"] == result.json()["result"]


def test_wrong_profile_and_stale_editor_do_not_invoke_model(setup):
    client, registry, package, calls = setup
    base = "/api/equipment/skills/demo/1.0.0/split-proposal"
    assert client.post(base + "?profile_id=another", json={"expected_workflow_sha256": package["manifest"]["workflow_sha256"]}).status_code == 409
    assert client.post(base + "?profile_id=utm_test", json={"expected_workflow_sha256": "0" * 64}).status_code == 409
    assert calls == []
    assert len(registry.list()) == 1


def test_model_failure_does_not_produce_fake_split_or_drafts(setup, monkeypatch):
    client, registry, package, calls = setup
    class Broken:
        async def complete(self, **kwargs):
            raise RuntimeError("offline")
    monkeypatch.setitem(main.controller._deps.agent_context.primary_backends, "split-test", Broken())
    response = client.post("/api/equipment/skills/demo/1.0.0/split-proposal", json={"expected_workflow_sha256": package["manifest"]["workflow_sha256"]})
    assert response.status_code == 503
    assert response.json()["detail"]["fallback_used"] is False
    assert len(registry.list()) == 1
