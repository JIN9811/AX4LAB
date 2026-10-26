from __future__ import annotations

from app.bootstrap import _build_runtime_profile
from backends.model_router import ModelRouter


def test_runtime_profile_uses_selected_endpoint_capability_not_model_role_defaults() -> None:
    models_cfg = {
        "models": {"orchestrator": {"primary": "endpoint:text-only"},
                   "worker": {"primary": "endpoint:vision-server"}},
        "task_routes": {"orchestrator_plan": "orchestrator", "design_reasoning": "worker"},
        "role_capabilities": {"worker": {"vision": False}, "orchestrator": {"vision": True}},
    }

    profile = _build_runtime_profile(
        backend_name="vllm",
        backend_cfg={"base_url": "http://127.0.0.1:8002/v1"},
        models_cfg=models_cfg,
        router=ModelRouter(models_cfg),
        endpoints={"text-only": {"capabilities": {"text": True, "vision": False}},
                   "vision-server": {"capabilities": {"text": True, "vision": True}}},
    )

    assert profile["models"]["worker"]["capabilities"] == {"text": True, "vision": True}
    assert profile["models"]["orchestrator"]["capabilities"] == {"text": True, "vision": False}
    assert "e4b" not in profile["models"]
