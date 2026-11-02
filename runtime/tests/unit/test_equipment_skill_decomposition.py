from copy import deepcopy
import importlib
import json

import pytest

from utils.equipment_skill_runtime import EquipmentSkillRegistry, SkillContractError, validate_skill_package


@pytest.fixture
def source(tmp_path):
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(recording={
        "schema": "atr.equipment_recording.v1", "status": "saved", "recording_id": "demo",
        "events": [{"kind": "key_press", "at_ms": 0, "key": "f1"},
                   {"kind": "key_press", "at_ms": 0, "key": "f2"},
                   {"kind": "key_press", "at_ms": 0, "key": "esc"}],
    }, skill_id="demo", version="1.0.0", target_profile="utm_test", model_snapshot={})
    return registry


def service(registry):
    module = importlib.import_module("utils.equipment_skill_decomposition")
    return module.SkillDecomposition(registry)


def payload():
    return {"parts": [
        {"name": "Enter values", "step_ids": ["step-001", "step-002"], "purpose": "Fill input"},
        {"name": "Close", "step_ids": ["step-003"], "purpose": "Dismiss input"},
    ], "branches": [{"after_part": 1, "condition": "Dialog is missing", "description": "Another demonstration needed"}]}


def test_confirm_creates_independent_review_drafts_without_changing_source_or_actions(source):
    before = deepcopy(source.get("demo", "1.0.0"))
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={"model": "selected"})
    assert len(source.list()) == 1
    result = split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    assert source.get("demo", "1.0.0") == before
    children = [validate_skill_package(source._package_dir(c["skill_id"], c["version"])) for c in result["children"]]
    assert [s for child in children for s in child["workflow"]["steps"]] == before["workflow"]["steps"]
    assert [c["manifest"]["name"] for c in children] == ["Enter values", "Close"]
    assert all(c["manifest"]["lifecycle"] == "review_required" and c["programs"] == [] for c in children)
    assert all(all(s["review_required"] for s in c["annotations"]["steps"]) for c in children)
    assert result["composition"]["executable"] is False
    assert result["composition"]["branches"][0]["status"] == "needs_demonstration"
    assert split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True) == result
    assert len(source.list()) == 3


@pytest.mark.parametrize("groups", [[], [["step-001"]], [["step-001", "step-001"], ["step-003"]],
    [["step-002", "step-001"], ["step-003"]], [["step-001", "step-002"], ["invented"]],
    [["step-001"], [], ["step-002", "step-003"]]])
def test_invalid_partition_never_creates_children(source, groups):
    split = service(source)
    with pytest.raises(SkillContractError):
        split.propose("demo", "1.0.0", {"parts": [{"name": "X", "step_ids": g} for g in groups]}, model_snapshot={})
    assert len(source.list()) == 1


def test_confirmation_and_source_revision_are_required(source):
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={})
    with pytest.raises(SkillContractError, match="confirmation"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=False)
    package = source.get("demo", "1.0.0")
    package["workflow"]["steps"][0]["label"] = "Edited"
    source.update_workflow("demo", "1.0.0", package["workflow"], expected_workflow_sha256=package["manifest"]["workflow_sha256"])
    with pytest.raises(SkillContractError, match="revision"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    assert len(source.list()) == 1


def test_rejects_added_action_and_unknown_branch_target(source):
    split = service(source)
    bad = payload()
    bad["parts"][0]["actions"] = [{"action": "press", "key": "enter"}]
    with pytest.raises(SkillContractError):
        split.propose("demo", "1.0.0", bad, model_snapshot={})
    bad = payload()
    bad["branches"][0]["after_part"] = 99
    with pytest.raises(SkillContractError):
        split.propose("demo", "1.0.0", bad, model_snapshot={})


def test_conflicting_destination_is_not_overwritten(source):
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={})
    child = proposal["parts"][0]
    dest = source._package_dir(child["skill_id"], "1.0.0")
    dest.mkdir(parents=True)
    (dest / "mine.txt").write_text("keep")
    with pytest.raises(SkillContractError, match="exists|conflict"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    assert (dest / "mine.txt").read_text() == "keep"
    assert len(source.list()) == 1


def test_single_purpose_proposal_does_not_force_artificial_split(source):
    split = service(source)
    proposal = split.propose("demo", "1.0.0", {"parts": [{"name": "One task", "step_ids": ["step-001", "step-002", "step-003"]}]}, model_snapshot={})
    assert proposal["split_recommended"] is False
    with pytest.raises(SkillContractError, match="single"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)


def test_publication_failure_removes_only_own_new_children_and_can_retry(source, monkeypatch):
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={})
    from pathlib import Path
    original = Path.rename
    def fail_second(path, target):
        if str(target).endswith(proposal["parts"][1]["skill_id"] + "/1.0.0"):
            raise OSError("disk failure")
        return original(path, target)
    monkeypatch.setattr(Path, "rename", fail_second)
    with pytest.raises(OSError, match="disk failure"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    assert len(source.list()) == 1
    monkeypatch.setattr(Path, "rename", original)
    assert len(split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)["children"]) == 2


def test_long_skill_preserves_actions_beyond_macro_segment_limit(source):
    package = source.get("demo", "1.0.0")
    steps = [{"step_id": f"long-{i:03d}", "label": "Wait", "action": {"action": "wait", "seconds": 0.1},
              "checkpoint_after": False} for i in range(240)]
    package["workflow"]["steps"] = steps
    source.update_workflow("demo", "1.0.0", package["workflow"], expected_workflow_sha256=package["manifest"]["workflow_sha256"])
    split = service(source)
    proposal = split.propose("demo", "1.0.0", {"parts": [
        {"name": "Observe", "step_ids": [s["step_id"] for s in steps[:130]]},
        {"name": "Confirm", "step_ids": [s["step_id"] for s in steps[130:]]},
    ]}, model_snapshot={})
    result = split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    children = [source.get(c["skill_id"], c["version"]) for c in result["children"]]
    assert [s for c in children for s in c["workflow"]["steps"]] == steps
    assert [len(c["workflow"]["steps"]) for c in children] == [130, 110]


def test_annotation_only_change_invalidates_proposal(source):
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={})
    source.annotate("demo", "1.0.0", {"steps": [{"step_id": "step-001", "intent": "Changed meaning", "confidence": 0.9}]}, model_snapshot={})
    with pytest.raises(SkillContractError, match="revision"):
        split.apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)


def test_interrupted_process_publication_resumes_matching_child_once(source):
    from utils.equipment_skill_runtime import _atomic_write_json
    split = service(source)
    proposal = split.propose("demo", "1.0.0", payload(), model_snapshot={})
    package, recording, _ = split.source("demo", "1.0.0")
    first = split._child(package, recording, proposal, proposal["parts"][0])
    dest = source._package_dir(proposal["parts"][0]["skill_id"], "1.0.0")
    for name, value in first.items():
        _atomic_write_json(dest / f"{name}.json", value)
    before = (dest / "manifest.json").stat().st_mtime_ns
    result = service(source).apply("demo", "1.0.0", proposal["proposal_id"], confirmed=True)
    assert len(result["children"]) == 2
    assert len(source.list()) == 3
    assert (dest / "manifest.json").stat().st_mtime_ns == before
