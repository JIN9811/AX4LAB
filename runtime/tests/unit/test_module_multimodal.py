from __future__ import annotations

import httpx
import pytest

from agents.base_agent import AgentContext
from backends.llm_backend import LLMImageInput, LLMResponse
from backends.llm_lease import LLMLeaseCoordinator
from backends.mock_llm import MockLLMBackend
from backends.model_router import ModelRouter
from backends.openai_client import OpenAIBackend
from backends.vllm_client import VLLMBackend
from orchestrator.langgraph_runtime import ModuleRuntimeContext
from orchestrator.state import Stage


def _context(primary, fallback, *, leased: bool, separate_backend: bool = True):
    router = ModelRouter({"models": {"e4b": {"primary": "primary", "fallback": "secondary"}}})
    remote_router = ModelRouter(
        {"models": {"e4b": {"primary": "remote-primary", "fallback": "remote-secondary"}}}
    )
    base = AgentContext(
        model_router=router,
        primary_backend=primary,
        fallback_backend=fallback,
        rag=None,
        experiment_db=None,
        failure_memory=None,
        tools=None,
        model_routers={"openai": remote_router},
        backend_fallbacks={"vllm": "openai"} if separate_backend else {},
        llm_lease=LLMLeaseCoordinator() if leased else None,
    )
    return ModuleRuntimeContext(base, {"id": "vision"}, Stage.VISION), base


@pytest.mark.parametrize("leased", [False, True])
@pytest.mark.parametrize(
    ("success_model", "expected_models", "separate_backend"),
    [
        ("primary", ["remote-primary", "remote-secondary", "primary"], True),
        ("secondary", ["remote-primary", "remote-secondary", "primary", "secondary"], True),
        ("remote-primary", ["remote-primary"], True),
        (
            "remote-secondary",
            ["remote-primary", "remote-secondary"],
            True,
        ),
        ("secondary", ["primary", "secondary", "secondary"], False),
    ],
)
async def test_module_images_reach_each_selected_model_and_fallback(
    monkeypatch, leased, success_model, expected_models, separate_backend
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        requests.append(payload)
        successful = payload["model"] == success_model
        if not separate_backend:
            successful = successful and request.url.host == "remote.test"
        return httpx.Response(
            200 if successful else 503,
            json={"choices": [{"message": {"content": "image grounded result"}}]},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    ctx, base = _context(
        VLLMBackend(base_url="http://local.test/v1"),
        OpenAIBackend(base_url="http://remote.test/v1", api_key="test"),
        leased=leased,
        separate_backend=separate_backend,
    )

    response = await ctx.complete(
        "vision_reasoning",
        "Inspect evidence",
        images=[
            LLMImageInput(b"raw", "image/png", "raw frame"),
            LLMImageInput(b"annotated", "image/png", "annotated frame"),
        ],
    )

    assert response.text == "image grounded result"
    assert response.model == success_model
    assert [request["model"] for request in requests] == expected_models
    for request in requests:
        assert request["messages"][1]["content"] == [
            {
                "type": "text",
                "text": "Inspect evidence\n\nImage 1: raw frame\nImage 2: annotated frame",
            },
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,cmF3", "detail": "high"}},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,YW5ub3RhdGVk", "detail": "high"},
            },
        ]
    if leased:
        assert base.llm_lease.status()["last_owner"] == "module:vision:vision_reasoning"


@pytest.mark.parametrize("llm", [{"backend": "vllm"}, {"model": "module-owned-model"}])
async def test_explicit_module_route_remains_authoritative(llm):
    class Backend:
        async def complete(self, *, model, **kwargs):
            return LLMResponse(text="actual result", model=model)

    _, base = _context(Backend(), Backend(), leased=False)
    ctx = ModuleRuntimeContext(base, {"id": "vision", "llm": llm}, Stage.VISION)
    response = await ctx.complete("vision_reasoning", "text only")
    assert response.model == llm.get("model", "primary")


@pytest.mark.parametrize("override", ["ollama", "nemoclaw", "missing-endpoint-backend"])
def test_explicit_unregistered_module_backend_fails_before_active_backend_fallback(override):
    class Backend:
        async def complete(self, **kwargs):
            pytest.fail("An unsupported module backend must not call the active provider")

    provider = Backend()
    _, base = _context(provider, provider, leased=False)
    base.primary_backends = {"vllm": provider, "openai": provider}
    with pytest.raises(ValueError, match="Unsupported module inference backend"):
        ModuleRuntimeContext(base, {"id": "vision", "llm": {"backend": override}}, Stage.VISION)


def test_standalone_context_does_not_treat_unknown_override_as_active_backend():
    provider = MockLLMBackend()
    _, base = _context(provider, provider, leased=False)
    assert base.primary_backends == {}
    with pytest.raises(ValueError, match="Unsupported module inference backend"):
        ModuleRuntimeContext(base, {"id": "vision", "llm": {"backend": "unknown"}}, Stage.VISION)


async def test_registered_module_backend_override_uses_that_provider():
    class Backend:
        def __init__(self, label):
            self.label = label

        async def complete(self, *, model, **kwargs):
            return LLMResponse(text=self.label, model=model)

    local, api = Backend("local"), Backend("api")
    _, base = _context(local, api, leased=False)
    base.primary_backends = {"vllm": local, "openai": api}
    ctx = ModuleRuntimeContext(base, {"id": "vision", "llm": {"backend": "openai"}}, Stage.VISION)
    response = await ctx.complete("vision_reasoning", "text only")
    assert response.text == "api"
    assert response.model == "remote-primary"


async def test_empty_module_response_falls_back_instead_of_reporting_success():
    class Backend:
        async def complete(self, *, model, **kwargs):
            return LLMResponse(text="  " if model == "primary" else "recovered", model=model)

    backend = Backend()
    ctx, _ = _context(backend, backend, leased=False, separate_backend=False)
    response = await ctx.complete("vision_reasoning", "text only")
    assert response.text == "recovered"
    assert response.model == "secondary"


@pytest.mark.parametrize("images", [None, []])
@pytest.mark.parametrize("leased", [False, True])
async def test_module_text_calls_remain_compatible_with_legacy_backend(images, leased) -> None:
    class LegacyTextBackend:
        async def complete(self, *, model, system_prompt, user_prompt, metadata):
            return LLMResponse(text=user_prompt, model=model)

    backend = LegacyTextBackend()
    ctx, _ = _context(backend, backend, leased=leased, separate_backend=False)

    response = await ctx.complete("vision_reasoning", "text only", images=images)

    assert response.text == "text only"


async def test_module_does_not_accept_mock_response_as_multimodal_success() -> None:
    backend = MockLLMBackend()
    ctx, _ = _context(backend, backend, leased=False, separate_backend=False)

    with pytest.raises(RuntimeError, match="mock.*multimodal"):
        await ctx.complete(
            "vision_reasoning", "Inspect evidence", images=[LLMImageInput(b"raw", "image/png")]
        )

    response = await ctx.complete("vision_reasoning", "text only")
    assert response.raw["mock"] is True
