"""Recovery must not expand a zero-effect GUI retry into arbitrary actuation."""
import pytest
import json
from types import SimpleNamespace
from backends.llm_backend import LLMImageInput, LLMResponse

from agents.equipment.agent import LabEquipmentAgent
from utils.equipment_skill_runtime import SkillContractError, validate_recovery_decision


@pytest.mark.parametrize("changes", [{"executed_action_count": False}, {"executed_action_count": "0"},
    {"executed_action_count": 0.1}, {"actuation_performed": True}, {"effects_known": False},
    {"effect_unknown": True}, {"status": "running"}])
def test_recovery_never_retries_unknown_or_partially_executed_segment(changes):
    result = {"ok": False, "executed_action_count": 0, "failure_code": "PYAUTOGUI_LOCATOR_NOT_FOUND", **changes}
    assert not LabEquipmentAgent._skill_segment_retry_is_safe(result)


@pytest.mark.parametrize("operation,payload", [
    ("focus_window", {"target_window": "Program 1", "action": "click", "x": 120, "y": 40}),
    ("press", {"key": "enter"}), ("press", {"key": "esc", "presses": 20}),
    ("wait", {"seconds": float("inf")}),
])
def test_recovery_rejects_payload_overrides_and_unbounded_actions(operation, payload):
    with pytest.raises(SkillContractError):
        validate_recovery_decision({"schema": "atr.equipment_skill_recovery.v1", "operation": operation,
            "payload": payload, "expected_verification": {"ready": True}, "confidence": 0.9, "attempt": 1},
            exception={"allowed_recovery_operations": [operation]})


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_visual_recovery_repairs_json_once_before_any_action(repair_succeeds):
    calls = []
    async def complete(**kw):
        calls.append(kw)
        text = '{"operation":"press"}}'  # observed extra-brace failure
        if len(calls) == 2 and repair_succeeds:
            text = json.dumps({"schema":"atr.equipment_skill_recovery.v1", "operation":"press",
                "payload":{"key":"esc"}, "expected_verification":{"modal_closed":True}, "confidence":0.95, "attempt":1})
        return LLMResponse(text=text, model=kw["model"])
    backend = SimpleNamespace(complete=complete)
    ctx = SimpleNamespace(active_backend="vllm", primary_backend=backend, primary_backends={"vllm":backend})
    args = dict(model_snapshot={"provider":"vllm","model":"endpoint:current"},
        exception={"allowed_recovery_operations":["press"]}, images=[LLMImageInput(data=b"test fixture",mime_type="image/png")])
    if repair_succeeds:
        result = await LabEquipmentAgent()._selected_skill_recovery_decision(ctx, **args)
        assert result["operation"] == "press"
    else:
        with pytest.raises(SkillContractError):
            await LabEquipmentAgent()._selected_skill_recovery_decision(ctx, **args)
    assert len(calls) == 2
    assert calls[1]["metadata"]["json_retry_attempt"] == 1
    assert calls[1]["images"] == calls[0]["images"]
