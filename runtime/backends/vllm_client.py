"""
File purpose:
- Async vLLM OpenAI-compatible API client for the shared AgentContext backend switch.

Key classes/functions:
- VLLMBackend

Inputs/outputs:
- Input: model id and prompts
- Output: normalized LLMResponse containing chat completion text

Dependencies:
- httpx.AsyncClient
- backends.llm_backend.BaseLLMBackend

Modification guide:
- Safe places to edit: request payload parameters and response parsing
- Risky places to edit: OpenAI-compatible endpoint contract
- Related files: app/bootstrap.py, agents/base_agent.py
"""

from __future__ import annotations

from typing import Any
import logging

import httpx

from backends.llm_backend import BaseLLMBackend, LLMImageInput, LLMResponse, openai_user_content
from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime
from backends.endpoint_routes import resolve_endpoint, endpoint_token, endpoint_ref

LOG = logging.getLogger(__name__)


DEFAULT_MAX_TOKENS_BY_TASK = {
    "orchestrator_plan": 320,
    "design_reasoning": 256,
    "specimen_reasoning": 256,
    "analysis_reasoning": 192,
    "knowledge_query": 1536,
    "bo_policy": 768,
    "guardian_reasoning": 256,
    "manipulation_plan": 768,
    "vision_observation": 1536,
    "tool_formatting": 96,
    "equipment_workflow_decision": 768,
    "gui_helper": 96,
    "module_designer": 1400,
    "equipment_skill_timeline_chunk": 768,
    "equipment_skill_annotation": 1536,
}


class VLLMBackend(BaseLLMBackend):
    """LLM backend backed by a vLLM OpenAI-compatible server."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        timeout_s: float = 300.0,
        api_key: str | None = None,
        model_base_urls: dict[str, str] | None = None,
        nemoclaw_runtime: NemoClawVLLMRuntime | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._api_key = api_key or "EMPTY"
        self._api_key_base_url = self._base_url
        self._model_base_urls = {
            str(model): str(url).rstrip("/")
            for model, url in (model_base_urls or {}).items()
            if str(model).strip() and str(url).strip()
        }
        self._nemoclaw_runtime = nemoclaw_runtime

    @staticmethod
    def _max_tokens_for_metadata(metadata: dict[str, Any] | None) -> int | None:
        """Keep local vLLM calls bounded so GUI/stage handoffs do not over-generate."""
        if not isinstance(metadata, dict):
            return None
        task_type = str(metadata.get("task_type", "")).strip()
        explicit = metadata.get("max_tokens")
        if explicit is not None:
            try:
                return max(1, int(explicit))
            except (TypeError, ValueError):
                return None
        return DEFAULT_MAX_TOKENS_BY_TASK.get(task_type)

    @staticmethod
    def _response_format_for_metadata(metadata: dict[str, Any] | None) -> dict[str, str] | None:
        if isinstance(metadata, dict) and metadata.get("response_format") == "json_object":
            return {"type": "json_object"}
        return None

    async def _base_url_for_model(self, model: str) -> str:
        endpoint = resolve_endpoint(self, model)
        if endpoint is not None:
            if endpoint.get('management_id') and self._nemoclaw_runtime is not None:
                url = await self._nemoclaw_runtime.base_url_for_model(endpoint['management_id'])
                if not url:
                    raise ValueError('The endpoint management target is not configured.')
                return url.rstrip('/')
            return endpoint['base_url'].rstrip('/')
        route = getattr(self, '_connection_routes', {}).get(model)
        if route and not route['managed']:
            return route['base_url']
        if self._nemoclaw_runtime is not None:
            runtime_url = await self._nemoclaw_runtime.base_url_for_model(model)
            if runtime_url:
                return runtime_url.rstrip("/")
        return self._model_base_urls.get(model, self._base_url)

    async def scale_down_idle_models(self, *, include_persistent: bool = False) -> dict[str, Any]:
        """Scale NemoClaw-hosted vLLM models down to zero replicas."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        return await self._nemoclaw_runtime.scale_down_idle_models(include_persistent=include_persistent)

    async def scale_down_models_except(
        self,
        keep_models: set[str] | None = None,
        *,
        include_persistent: bool = False,
    ) -> dict[str, Any]:
        """Scale non-selected NemoClaw-vLLM models down to zero replicas."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        targets = set()
        for model in keep_models or set():
            row = resolve_endpoint(self, model)
            if row is None:
                targets.add(model)
            elif row.get('management_id'):
                targets.add(row['management_id'])
        return await self._nemoclaw_runtime.scale_down_models_except(
            targets,
            include_persistent=include_persistent,
        )

    async def prepare_model(self, model: str) -> None:
        """Ensure an on-demand NemoClaw-hosted model is serving before inference timeout starts."""
        endpoint = resolve_endpoint(self, model)
        if endpoint is not None:
            target = endpoint.get('management_id')
            if target:
                if self._nemoclaw_runtime is None or target not in self._nemoclaw_runtime._models:
                    raise ValueError('The endpoint management target is not configured.')
                await self._nemoclaw_runtime.ensure_model(target)
            return
        route = getattr(self, '_connection_routes', {}).get(model)
        if route and not route['managed']:
            return
        if self._nemoclaw_runtime is not None:
            await self._nemoclaw_runtime.ensure_model(model)

    async def load_model(self, model: str) -> dict[str, Any]:
        """Manually load a NemoClaw-hosted vLLM model."""
        endpoint = resolve_endpoint(self, model)
        if endpoint is not None:
            if not endpoint.get('management_id') or self._nemoclaw_runtime is None:
                raise ValueError('This endpoint has no startup/shutdown management target.')
            return await self._nemoclaw_runtime.load_model(endpoint['management_id'])
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "model": model, "loaded": False}
        return await self._nemoclaw_runtime.load_model(model)

    async def unload_model(self, model: str) -> dict[str, Any]:
        """Manually unload a NemoClaw-hosted vLLM model."""
        endpoint = resolve_endpoint(self, model)
        if endpoint is not None:
            if not endpoint.get('management_id') or self._nemoclaw_runtime is None:
                raise ValueError('This endpoint has no startup/shutdown management target.')
            return await self._nemoclaw_runtime.unload_model(endpoint['management_id'])
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "model": model, "unloaded": False}
        return await self._nemoclaw_runtime.unload_model(model)

    async def managed_model_statuses(self) -> dict[str, Any]:
        """Return all managed NemoClaw vLLM model statuses."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "models": []}
        result = await self._nemoclaw_runtime.model_statuses()
        endpoints = getattr(self, '_endpoint_routes', None)
        if endpoints is not None:
            by_target = {row['model']: row for row in result.get('models', [])}
            result = {**result, 'models': [
                {**by_target[row['management_id']], 'model': endpoint_ref(key),
                 'endpoint_id': key, 'served_model': row['model'], 'management_id': row['management_id']}
                for key, row in endpoints.items() if row.get('management_id') in by_target]}
        return result

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        endpoint = resolve_endpoint(self, model)
        if images and endpoint is not None and not endpoint.get('capabilities', {}).get('vision', False):
            raise ValueError('This endpoint is not configured for image input.')
        base_url = await self._base_url_for_model(model)

        payload: dict[str, Any] = {
            "model": endpoint['model'] if endpoint is not None else model,
            "stream": False,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": openai_user_content(user_prompt, images)},
            ],
        }
        max_tokens = self._max_tokens_for_metadata(metadata)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        response_format = self._response_format_for_metadata(metadata)
        if response_format is not None:
            payload["response_format"] = response_format
        if metadata:
            payload["metadata"] = metadata

        headers = {"Content-Type": "application/json"}
        route = getattr(self, '_connection_routes', {}).get(model)
        token = endpoint_token(self, endpoint) if endpoint is not None else (
            route['access_token'] if route and not route['managed'] else self._api_key)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=self._timeout_s, follow_redirects=False) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        LOG.info("LLM usage task=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                 (metadata or {}).get("task_type", "unknown"), model,
                 usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"))

        content = ""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = str(message.get("content", ""))
        return LLMResponse(text=content, model=model, raw=data)
