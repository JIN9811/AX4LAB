"""Backend configuration preserves endpoint identity and normalizes old roles."""
from copy import deepcopy
from pathlib import Path
import os
from types import SimpleNamespace

import pytest
import yaml

from app.bootstrap import _bind_model_endpoints, _build_backend, _models_cfg_for_backend
from backends.endpoint_routes import resolve_endpoint
from backends.model_router import ModelRouter


def test_backend_routes_normalize_legacy_roles_without_resurrecting_old_env(monkeypatch):
    cfg = {"models": {"e4b": {"primary": "legacy"}}, "backend_models": {
        "vllm": {"e4b": {"primary": "endpoint:local-main"}},
        "openai": {"e4b": {"primary": "endpoint:api-main"}},
    }, "task_routes": {"design_reasoning": "e4b"}}
    before = deepcopy(cfg)
    monkeypatch.setenv("AUTONOMOUS_E4B_MODEL", "retired")
    monkeypatch.setenv("AUTONOMOUS_VLLM_E4B_MODEL", "retired-local")
    for provider, expected in (("vllm", "endpoint:local-main"), ("openai", "endpoint:api-main")):
        routed = _models_cfg_for_backend(cfg, provider)
        assert routed["models"] == {"worker": {"primary": expected}}
        assert routed["task_routes"]["design_reasoning"] == "worker"
    assert cfg == before


def test_endpoint_override_wins_over_model_compatibility_override(monkeypatch):
    cfg = {"models": {"worker": {"primary": "legacy"}}, "backend_models": {
        "vllm": {"worker": {"primary": "endpoint:local-main"}}}}
    monkeypatch.setenv("AUTONOMOUS_VLLM_WORKER_MODEL", "compatible-served-model")
    monkeypatch.setenv("AUTONOMOUS_VLLM_WORKER_ENDPOINT", "other-local")
    assert _models_cfg_for_backend(cfg, "vllm")["models"]["worker"]["primary"] == "endpoint:other-local"
    monkeypatch.setenv("AUTONOMOUS_VLLM_WORKER_ENDPOINT", "endpoint:already-prefixed")
    assert _models_cfg_for_backend(cfg, "vllm")["models"]["worker"]["primary"] == "endpoint:already-prefixed"
    monkeypatch.delenv("AUTONOMOUS_VLLM_WORKER_ENDPOINT")
    assert _models_cfg_for_backend(cfg, "vllm")["models"]["worker"]["primary"] == "compatible-served-model"


def test_global_compatibility_override_does_not_replace_configured_backend(monkeypatch):
    cfg = {"models": {"worker": {"primary": "legacy"}}, "backend_models": {
        "vllm": {"worker": {"primary": "endpoint:local-main"}}}}
    monkeypatch.setenv("AUTONOMOUS_WORKER_MODEL", "global-model")
    assert _models_cfg_for_backend(cfg, "vllm")["models"]["worker"]["primary"] == "endpoint:local-main"
    assert _models_cfg_for_backend(cfg, "custom")["models"]["worker"]["primary"] == "global-model"


@pytest.mark.parametrize("provider,reference,model", [
    ("vllm", "endpoint:local-main", "gemma4:31b"),
    ("openai", "endpoint:api-main", "gpt-5.5"),
])
def test_shipped_routes_resolve_registered_endpoint_without_backend_io(provider, reference, model, monkeypatch):
    config_root = Path(__file__).resolve().parents[2] / "configs"
    system = yaml.safe_load((config_root / "system.yaml").read_text())
    models = yaml.safe_load((config_root / "models.yaml").read_text())
    for key in tuple(os.environ):
        if key.startswith("AUTONOMOUS_") and key.endswith(("_MODEL", "_ENDPOINT")):
            monkeypatch.delenv(key)
    client = _build_backend(provider, system_cfg=system["system"], cfg={"system": system})
    router = ModelRouter(_models_cfg_for_backend(models, provider))
    for task in ("orchestrator_plan", "orchestrator_supervisor", "design_reasoning", "vision_observation",
                 "manipulation_plan", "guardian_review", "tool_formatting"):
        selected = router.select(task)
        assert selected.primary == reference
        assert selected.fallback is None
        assert resolve_endpoint(client, selected.primary)["model"] == model
    if provider == "vllm":
        assert set(client._nemoclaw_runtime._models) == {"local-main"}
        assert system["system"]["vllm_background_startup_models"] == ["endpoint:local-main"]


def test_bootstrap_rejects_endpoint_map_identity_mismatch():
    cfg = {"system": {"llm_connections": {"endpoints": {"wrong-id": {
        "id": "actual-id", "provider": "vllm", "base_url": "http://localhost:8000/v1", "model": "custom"}}}}}
    with pytest.raises(ValueError, match="identity"):
        _build_backend("vllm", system_cfg={}, cfg=cfg)


def test_disabled_manager_does_not_block_api_only_bootstrap():
    root = Path(__file__).resolve().parents[2] / "configs"
    system = yaml.safe_load((root / "system.yaml").read_text())
    system["vllm"]["nemoclaw_k8s"]["enabled"] = False
    api = _build_backend("openai", system_cfg=system["system"], cfg={"system": system})
    local = _build_backend("vllm", system_cfg=system["system"], cfg={"system": system})
    assert resolve_endpoint(api, "endpoint:api-main")["model"] == "gpt-5.5"
    assert resolve_endpoint(local, "endpoint:local-main")["management_id"] == "local-main"
    assert local._nemoclaw_runtime is None


def test_enabled_manager_rejects_unknown_management_target():
    root = Path(__file__).resolve().parents[2] / "configs"
    system = yaml.safe_load((root / "system.yaml").read_text())
    system["llm_connections"]["endpoints"]["local-main"]["management_id"] = "unknown-target"
    with pytest.raises(ValueError, match="Unknown endpoint management target"):
        _build_backend("vllm", system_cfg=system["system"], cfg={"system": system})


def test_concrete_compatibility_route_is_bound_to_one_endpoint_identity():
    cfg = {"models": {"worker": {"primary": "served-alias", "fallback": "endpoint:spare"}}}
    before = deepcopy(cfg)
    backend = SimpleNamespace(_endpoint_routes={
        "chosen": {"id": "chosen", "model": "served-alias"},
        "spare": {"id": "spare", "model": "spare-alias"},
    })
    bound = _bind_model_endpoints(cfg, backend)
    assert bound["models"]["worker"] == {"primary": "endpoint:chosen", "fallback": "endpoint:spare"}
    assert cfg == before


@pytest.mark.parametrize("routes", [{}, {
    "one": {"id": "one", "model": "shared"}, "two": {"id": "two", "model": "shared"},
}])
def test_unknown_or_ambiguous_legacy_route_never_binds_to_an_arbitrary_endpoint(routes):
    with pytest.raises(ValueError, match="missing or ambiguous"):
        _bind_model_endpoints({"models": {"worker": {"primary": "shared"}}},
                              SimpleNamespace(_endpoint_routes=routes))
