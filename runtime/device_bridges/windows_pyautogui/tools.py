"""
File purpose:
- MCP tool wrapper for Windows PyAutoGUI equipment bridge operations.

Key classes/functions:
- register_equipment_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: equipment.pyautogui.* handlers registered.

Dependencies:
- device_bridges.windows_pyautogui.bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: tool names and payload normalization additions.
- Risky places to edit: live execution gates inside the bridge client.
- Related files: agents/equipment/agent.py, app/bootstrap.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.windows_pyautogui.bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
)
from mcp_tools.tool_registry import ToolRegistry
from utils.equipment_runtime_service import EquipmentRuntimeContractError, EquipmentRuntimeService
from utils.runtime_paths import RuntimePaths
from utils.equipment_profiles import EquipmentProfileStore, scoped_equipment_profile_id


def register_equipment_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
    paths: RuntimePaths | None = None,
) -> WindowsPyAutoGUIBridge:
    """Register Windows PyAutoGUI equipment bridge tools."""
    config = WindowsPyAutoGUIBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root, paths=paths)
    bridge = WindowsPyAutoGUIBridge(config)
    runtime = EquipmentRuntimeService((paths.memory_root if paths is not None else (repo_root or Path.cwd()) / "memory") / "equipment_runtime")
    registry.register_resource("equipment.bridge", bridge)
    memory_root = paths.memory_root if paths is not None else (repo_root or Path(__file__).resolve().parents[2]) / "memory"
    bridges = {config.equipment_profile_id: bridge}

    def selected_bridge(payload: dict[str, Any]) -> WindowsPyAutoGUIBridge:
        profile_id = str(payload.get("equipment_profile_id") or scoped_equipment_profile_id()
                         or EquipmentProfileStore(memory_root).selected_id())
        # The two original built-ins share the same legacy worker/program registry.
        if profile_id in {"utm_windows_v1", "windows_desktop_v1"} and config.equipment_profile_id in {"utm_windows_v1", "windows_desktop_v1"}:
            refreshed = WindowsPyAutoGUIBridgeConfig.from_devices_config(
                devices_config or {}, repo_root=repo_root, paths=paths, profile_id=profile_id)
            bridge.config.bridge_url_env = refreshed.bridge_url_env
            bridge.config.token_env = refreshed.token_env
            return bridge
        if profile_id not in bridges:
            bridges[profile_id] = WindowsPyAutoGUIBridge(WindowsPyAutoGUIBridgeConfig.from_devices_config(
                devices_config or {}, repo_root=repo_root, paths=paths, profile_id=profile_id))
        selected = bridges[profile_id]
        # Refresh saved coordinates after Apply without losing simulator observation state.
        if profile_id not in {"utm_windows_v1", "windows_desktop_v1"}:
            from device_bridges.windows_pyautogui.bridge import DEFAULT_REGISTERED_PROGRAMS
            refreshed = WindowsPyAutoGUIBridgeConfig.from_devices_config(
                devices_config or {}, repo_root=repo_root, paths=paths, profile_id=profile_id)
            refreshed.registered_programs.update({key: value for key, value in selected.config.registered_programs.items()
                                                  if key not in DEFAULT_REGISTERED_PROGRAMS})
            selected.config = refreshed
        return selected

    def runtime_profile(payload: dict[str, Any]) -> str:
        return str(payload.get("equipment_profile_id") or scoped_equipment_profile_id()
                   or EquipmentProfileStore(memory_root).selected_id())

    def runtime_current(payload: dict[str, Any]) -> dict[str, Any]:
        execution = runtime.latest(profile_id=runtime_profile(payload))
        return {
            "ok": True,
            "execution": execution,
            "projection": EquipmentRuntimeService.project(execution) if execution else None,
        }

    def runtime_list(payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = runtime_profile(payload)
        limit = max(1, min(int(payload.get("limit") or 100), 1000))
        executions = [item for item in runtime.list(limit=1000) if item.get("profile_id") == profile_id][:limit]
        return {
            "ok": True,
            "executions": executions,
            "projections": [EquipmentRuntimeService.project(item) for item in executions],
        }

    def runtime_get(payload: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(payload.get("execution_id") or "").strip()
        try:
            execution = runtime.get(execution_id)
            if execution.get("profile_id") != runtime_profile(payload):
                raise EquipmentRuntimeContractError("Equipment execution not found for this profile")
        except EquipmentRuntimeContractError as exc:
            return {"ok": False, "failure_code": "EQUIPMENT_EXECUTION_NOT_FOUND", "message": str(exc)}
        return {"ok": True, "execution": execution, "projection": EquipmentRuntimeService.project(execution)}

    for name in ("health", "list_programs", "register_program", "delete_program", "run", "screenshot",
                 "list_locators", "request_log", "capture_locator", "save_utm_profile", "save_connection",
                 "select_candidate", "delete_candidate"):
        registry.register(f"equipment.pyautogui.{name}",
                          lambda payload, method=name: getattr(selected_bridge(payload or {}), method)(dict(payload or {})),
                          device="equipment:windows_pyautogui" if name in {"run", "capture_locator"} else None)
    registry.register("equipment.pyautogui.utm_profile", lambda payload: selected_bridge(payload or {}).utm_profile_status())
    registry.register("equipment.pyautogui.connection_status", lambda payload: selected_bridge(payload or {}).connection_status())
    registry.register("equipment.runtime.current", runtime_current)
    registry.register("equipment.runtime.list", runtime_list)
    registry.register("equipment.runtime.get", runtime_get)
    registry.register_resource("equipment_runtime", runtime)
    return bridge
