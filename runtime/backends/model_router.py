"""
File purpose:
- Route task types to model roles and concrete model ids via YAML config.

Key classes/functions:
- ModelRouter

Inputs/outputs:
- Input: task type + model config dictionary
- Output: selected primary/fallback model id

Dependencies:
- dataclasses.dataclass

Modification guide:
- Safe places to edit: fallback strategy and route defaults
- Risky places to edit: config key names shared with models.yaml
- Related files: configs/models.yaml, backends/ollama_client.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from backends.endpoint_routes import normalize_roles


@dataclass(slots=True)
class ModelSelection:
    """Resolved model choice for one task call."""

    role: str
    primary: str
    fallback: str | None


class ModelRouter:
    """Model selection router driven by YAML configuration."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = normalize_roles(config)
        self._models = self._cfg.get("models", {})
        self._task_routes = self._cfg.get("task_routes", {})

    def select(self, task_type: str) -> ModelSelection:
        """Resolve model role and model ids for the given task type."""
        role = str(self._task_routes.get(task_type, "worker"))
        role_cfg = self._models.get(role, {})
        primary = str(role_cfg.get("primary") or '').strip()
        if not primary:
            raise ValueError(f'No connection is assigned to role {role!r} for task {task_type!r}.')
        fallback = role_cfg.get("fallback")
        return ModelSelection(role=role, primary=primary, fallback=str(fallback) if fallback else None)
