"""Authoring consumes current source evidence without rewriting demonstrations."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

import app.main as main_module
from backends.llm_backend import LLMResponse
from knowledge.source_library import SourceLibrary
from mcp_tools.source_tools import register_source_tools
from mcp_tools.tool_registry import ToolRegistry
from utils.equipment_skill_runtime import EquipmentSkillRegistry


@pytest.mark.parametrize("availability", ["ready", "empty", "unavailable"])
def test_authoring_delivers_cited_reference_or_explicit_absence_without_changing_actions(
    tmp_path, monkeypatch, availability,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    library = SourceLibrary(tmp_path / "sources", inbox)
    if availability == "ready":
        (inbox / "qm.md").write_text(
            "# Qm_Tester\nAPPLY accepts the test identifier. START begins testing.\n",
            encoding="utf-8",
        )
        library.scan()
        source_id = library.scan()["pending_ids"][0]
        extracted = library.extract(source_id)
        library.publish(source_id, [{
            "title": "Qm_Tester test identifiers",
            "body": "APPLY accepts the test identifier. START begins testing.",
            "category": "equipment-manual", "ontology_type": "KnowledgeClaim",
            "tags": ["qm"], "applicability": {"software": "Qm_Tester"},
            "source_block_ids": [block["block_id"] for block in extracted["blocks"]],
        }], model={"model": "source-fixture"}, trace=[])
    tools = ToolRegistry()

    def retired_manual(*args, **kwargs):
        pytest.fail("Authoring must use Knowledge sources, not the retired manual route")

    monkeypatch.setattr(main_module, "_manual_knowledge_context", retired_manual)

    def source_library():
        if availability == "unavailable":
            raise OSError("Source storage offline")
        return library

    register_source_tools(tools, source_library)
    ctx = main_module.controller._deps.agent_context
    monkeypatch.setattr(ctx, "tools", tools)
    calls = []

    class Backend:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return LLMResponse(text=json.dumps({"steps": [{
                "step_id": "step-001", "label": "Close dialog", "confidence": 0.95,
                "review_required": False,
                # A reference-derived action must not replace what the human did.
                "action": {"action": "press", "key": "enter"},
            }]}), model="test-vision")

    monkeypatch.setitem(ctx.primary_backends, "vllm", Backend())
    monkeypatch.setattr(main_module, "_equipment_skill_model_snapshot", lambda: {
        "provider": "vllm", "model": "test-vision", "role": "worker",
        "capabilities": {"text": True, "vision": True}, "fallback_allowed": False,
    })
    monkeypatch.setattr(main_module, "RUNTIME_PATHS", replace(
        main_module.RUNTIME_PATHS, artifact_root=tmp_path / "artifacts",
    ))
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    recording = {"schema": "atr.equipment_recording.v3", "recording_id": "qm-demo",
        "name": "Qm_Tester", "target_app": "Qm_Tester", "status": "saved",
        "events": [{"kind": "key_press", "at_ms": 100, "key": "esc"}]}
    package = registry.create_draft(recording=recording, skill_id="qm-demo", version="1.0.0",
        target_profile="qm-test", model_snapshot={})
    package["recording"] = recording
    original = deepcopy(package["workflow"])
    annotations, snapshot = asyncio.run(main_module._annotate_equipment_skill_with_selected_model(package))
    evidence = json.loads(calls[-1]["user_prompt"])["source_knowledge"]
    expected_status = {"ready": "ready", "empty": "no_match", "unavailable": "unavailable"}[availability]
    assert evidence["status"] == expected_status
    assert evidence["authority"] == "reference_only"
    assert len(json.dumps(evidence, ensure_ascii=False).encode()) <= 12000
    if availability == "ready":
        assert evidence["notes"][0]["body"] == "APPLY accepts the test identifier. START begins testing."
        assert evidence["notes"][0]["applicability"] == {"software": "Qm_Tester"}
        assert evidence["citations"][0]["source_id"] == source_id
    else:
        assert not evidence["notes"] and not evidence["citations"]
    digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    assert calls[-1]["metadata"]["source_context_hash"] == digest
    result = registry.annotate("qm-demo", "1.0.0", annotations, source="model", model_snapshot=snapshot)
    assert result["annotations"]["model_snapshot"]["source_knowledge"] == evidence
    assert result["workflow"] == original
    assert result["annotations"]["steps"][0]["review_required"] is True
    assert "model_action_change_ignored" in result["annotations"]["steps"][0]["review_reasons"]
