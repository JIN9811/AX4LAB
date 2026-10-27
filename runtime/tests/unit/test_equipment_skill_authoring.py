import pytest

from utils.equipment_skill_runtime import EquipmentSkillRegistry, SkillContractError, canonical_sha256


def _draft(tmp_path):
    registry = EquipmentSkillRegistry(tmp_path)
    package = registry.create_draft(
        recording={"schema": "atr.equipment_recording.v3", "recording_id": "demo", "status": "saved",
                   "events": [{"kind": "mouse_click", "at_ms": 100, "x": 20, "y": 30}]},
        skill_id="demo", version="1.0.0", target_profile="local_program1", model_snapshot={},
    )
    return registry, package


def test_model_semantics_and_variables_persist_without_rewriting_human_actions(tmp_path):
    registry, draft = _draft(tmp_path)
    annotation = {
        "step_id": "step-001", "confidence": 0.98, "review_required": False,
        "intent": "Choose the specimen", "target_semantics": "Specimen dropdown",
        "preconditions": ["Application is idle"], "postconditions": ["Specimen selected"],
        "success_evidence": ["Selected specimen label is visible"],
        "failure_evidence": ["Validation warning"],
        "proposed_variables": [{"name": "specimen_id", "type": "string", "recorded_value": "S1",
                                "description": "Per-run specimen", "action_field": "text"}],
        "action": {"action": "write", "text": "S2"},
    }

    result = registry.annotate("demo", "1.0.0", {"steps": [annotation]}, source="model")

    saved = result["annotations"]["steps"][0]
    for key in ("intent", "target_semantics", "preconditions", "postconditions", "success_evidence", "failure_evidence"):
        assert saved[key] == annotation[key]
    assert saved["proposed_variables"][0]["recorded_value"] == "S1"
    assert saved["proposed_variables"][0]["status"] == "proposed"
    assert saved["review_required"] is True
    assert "proposed_variables" in saved["review_reasons"]
    assert result["workflow"] == draft["workflow"]
    assert result["manifest"]["annotations_sha256"] == canonical_sha256(result["annotations"])
    registry.compile("demo", "1.0.0")
    with pytest.raises(SkillContractError, match="review"):
        registry.validate("demo", "1.0.0")


def test_model_locator_stays_pending_until_explicit_manual_review_and_recompile(tmp_path):
    registry, draft = _draft(tmp_path)
    registry.compile("demo", "1.0.0")
    proposed = {"region_normalized": [0.1, 0.2, 0.3, 0.4], "locator_backend": "multimodal_roi_image"}
    result = registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "confidence": 0.98, "review_required": False, "locator": proposed}
    ]}, source="model")

    assert result["workflow"]["steps"] == draft["workflow"]["steps"]
    assert result["annotations"]["steps"][0]["locator_status"] == "proposed"
    assert result["annotations"]["steps"][0]["review_required"] is True
    unchanged = registry.annotate("demo", "1.0.0", {"steps": [{"step_id": "step-001", "label": "New label"}]})
    assert unchanged["annotations"]["steps"][0]["review_required"] is True

    semantics_only = registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "confidence": 0.98, "review_required": False}
    ]})
    assert semantics_only["workflow"]["steps"] == draft["workflow"]["steps"]
    assert semantics_only["annotations"]["steps"][0]["review_required"] is True
    assert semantics_only["annotations"]["steps"][0]["locator_status"] == "proposed"
    reviewed = registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "confidence": 0.98, "review_required": False, "locator": proposed}
    ]})
    assert reviewed["workflow"]["steps"][0]["action"]["region_normalized"] == [0.1, 0.2, 0.3, 0.4]
    assert reviewed["annotations"]["steps"][0]["locator_status"] == "reviewed"
    assert reviewed["workflow"]["program_ids"] == []
    assert reviewed["manifest"]["program_sha256"] == {}
    with pytest.raises(SkillContractError, match="compiled"):
        registry.validate("demo", "1.0.0")
    registry.compile("demo", "1.0.0")
    assert registry.validate("demo", "1.0.0")["ok"] is True


@pytest.mark.parametrize("updates,reason", [
    ({"confidence": 0.2, "review_required": False}, "low_confidence"),
    ({"confidence": 0.95, "review_required": False, "ambiguity": "Two similar controls"}, "ambiguity"),
])
def test_model_cannot_clear_review_for_ambiguous_evidence(tmp_path, updates, reason):
    registry, _ = _draft(tmp_path)
    result = registry.annotate("demo", "1.0.0", {"steps": [{"step_id": "step-001", **updates}]}, source="model")
    assert result["annotations"]["steps"][0]["review_required"] is True
    assert reason in result["annotations"]["steps"][0]["review_reasons"]


def test_manual_rejection_preserves_current_action_and_clears_proposal_gate(tmp_path):
    registry, draft = _draft(tmp_path)
    proposed = {"region_normalized": [0.1, 0.2, 0.3, 0.4]}
    registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "confidence": 0.98, "locator": proposed}
    ]}, source="model")
    result = registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "reject_locator": True, "review_required": False}
    ]})
    saved = result["annotations"]["steps"][0]
    assert saved["locator_status"] == "rejected"
    assert saved["rejected_locator"] == proposed
    assert "locator" not in saved
    assert saved["review_required"] is False
    assert result["workflow"] == draft["workflow"]
    registry.compile("demo", "1.0.0")
    assert registry.validate("demo", "1.0.0")["ok"] is True


@pytest.mark.parametrize("source,extras", [("model", {}), ("manual", {"locator": {"region": [1, 2, 3, 4]}})])
def test_locator_rejection_requires_unambiguous_manual_choice(tmp_path, source, extras):
    registry, _ = _draft(tmp_path)
    with pytest.raises(SkillContractError, match="locator rejection"):
        registry.annotate("demo", "1.0.0", {"steps": [
            {"step_id": "step-001", "reject_locator": True, **extras}
        ]}, source=source)


@pytest.mark.parametrize("update", [
    {"locator": {"region_normalized": [0.1, 0.2, 0.3, 0.4]}},
    {"postconditions": ["The new completion screen is visible"]},
])
def test_annotation_edit_invalidates_validation_and_remote_deployment(tmp_path, update):
    registry, _ = _draft(tmp_path)
    registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "review_required": False}
    ]})
    compiled = registry.compile("demo", "1.0.0")
    registry.validate("demo", "1.0.0")
    registry.mark_deployed("demo", "1.0.0", bridge_id="worker", deployment_sha256="a" * 64,
                           program_sha256=compiled["manifest"]["program_sha256"])
    changed = registry.annotate("demo", "1.0.0", {"steps": [
        {"step_id": "step-001", "review_required": False, **update}
    ]})
    assert "deployment" not in changed["manifest"]
    assert "validated_at" not in changed["manifest"]
    registry.compile("demo", "1.0.0")
    enabled = registry.set_enabled("demo", "1.0.0", True)
    assert enabled["manifest"]["lifecycle"] == "compiled"
    with pytest.raises(SkillContractError, match="not validated"):
        registry.begin_execution(skill_id="demo", version="1.0.0", sequence_id="new-run",
                                 target_profile="local_program1", model_snapshot={})
