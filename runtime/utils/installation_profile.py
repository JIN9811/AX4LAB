"""Validated, immutable installation-specific external resource bindings.

Installation profiles can fill only the reviewed resource targets below.  They
cannot patch arbitrary runtime configuration or replace a non-empty legacy
operator value.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
import json
import os
from pathlib import Path, PureWindowsPath
import re
from types import MappingProxyType
from typing import Any, Mapping

from utils.runtime_paths import RuntimePaths


INSTALLATION_PROFILE_ENV = "ATR_INSTALL_PROFILE"
INSTALLATION_PROFILE_SCHEMA = "atr.installation.v1"
_PLACEHOLDER = re.compile(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)|%[A-Za-z_][A-Za-z0-9_]*%")


@dataclass(frozen=True, slots=True)
class UTMResources:
    workspace_root: str = ""
    script_path: str = ""
    ros_setup_paths: tuple[str, ...] = ()
    extra_setup_paths: tuple[str, ...] = ()
    yolo_model_path: str = ""


@dataclass(frozen=True, slots=True)
class RealSenseResources:
    native_python_path: str = ""
    native_library_path: str = ""
    ros_setup_paths: tuple[str, ...] = ()
    extra_setup_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeRobotResources:
    conda_executable: str = ""
    conda_env_name: str = ""
    source_root: str = ""
    dataset_root: str = ""
    hf_home: str = ""
    pi05_conda_env_name: str = ""
    xvla_conda_env_name: str = ""
    smolvla_conda_env_name: str = ""
    pi05_repo_root: str = ""
    pi05_hf_home: str = ""


@dataclass(frozen=True, slots=True)
class SlicerResources:
    bambu_studio_executable: str = ""
    prusa_slicer_executable: str = ""


@dataclass(frozen=True, slots=True)
class IsaacResources:
    lab_root: str = ""
    sim_python: str = ""
    scene_path: str = ""


@dataclass(frozen=True, slots=True)
class InstallationResources:
    utm: UTMResources = UTMResources()
    realsense: RealSenseResources = RealSenseResources()
    lerobot: LeRobotResources = LeRobotResources()
    slicer: SlicerResources = SlicerResources()
    isaac: IsaacResources = IsaacResources()


@dataclass(frozen=True, slots=True)
class InstallationProfile:
    schema: str
    resources: InstallationResources
    source: Path | None
    configured: bool
    provenance: Mapping[str, str]


_RESOURCE_TYPES = {
    "utm": UTMResources,
    "realsense": RealSenseResources,
    "lerobot": LeRobotResources,
    "slicer": SlicerResources,
    "isaac": IsaacResources,
}
_LIST_FIELDS = {
    ("utm", "ros_setup_paths"),
    ("utm", "extra_setup_paths"),
    ("realsense", "ros_setup_paths"),
    ("realsense", "extra_setup_paths"),
}
_NAME_FIELDS = {
    ("lerobot", "conda_env_name"),
    ("lerobot", "pi05_conda_env_name"),
    ("lerobot", "xvla_conda_env_name"),
    ("lerobot", "smolvla_conda_env_name"),
}
_EXECUTABLE_FIELDS = {
    "isaac.sim_python", "lerobot.conda_executable",
    "slicer.bambu_studio_executable", "slicer.prusa_slicer_executable",
}

# Resource name -> target in the bundle produced by load_all_configs().
_RESOURCE_TARGETS = {
    "utm.workspace_root": "devices.devices.utm_vision_runtime.workspace_root",
    "utm.script_path": "devices.devices.utm_vision_runtime.script_path",
    "utm.ros_setup_paths": "devices.devices.utm_vision_runtime.ros_setup_paths",
    "utm.extra_setup_paths": "devices.devices.utm_vision_runtime.extra_setup_paths",
    "utm.yolo_model_path": "devices.devices.utm_vision_runtime.environment.YOLO_MODEL_PATH",
    "realsense.native_python_path": "devices.devices.specimen_pose_tracker.rsusb_pythonpath",
    "realsense.native_library_path": "devices.devices.specimen_pose_tracker.rsusb_library_path",
    "realsense.ros_setup_paths": "devices.devices.specimen_pose_tracker.ros_setup_paths",
    "realsense.extra_setup_paths": "devices.devices.specimen_pose_tracker.extra_setup_paths",
    "lerobot.conda_executable": "lerobot.lerobot.conda_executable",
    "lerobot.conda_env_name": "lerobot.lerobot.conda_env_name",
    "lerobot.source_root": "lerobot.lerobot.source_root",
    "lerobot.dataset_root": "lerobot.lerobot.dataset_root",
    "lerobot.hf_home": "lerobot.lerobot.hf_home",
    "lerobot.pi05_conda_env_name": "lerobot.lerobot.pi05_conda_env_name",
    "lerobot.xvla_conda_env_name": "lerobot.lerobot.xvla_conda_env_name",
    "lerobot.smolvla_conda_env_name": "lerobot.lerobot.smolvla_conda_env_name",
    "lerobot.pi05_repo_root": "lerobot.lerobot.pi05_repo_root",
    "lerobot.pi05_hf_home": "lerobot.lerobot.pi05_hf_home",
    "slicer.bambu_studio_executable": "devices.devices.printer.bambu.slicer.executable_path",
    "slicer.prusa_slicer_executable": "devices.devices.printer.slicer.executable_path",
    "isaac.lab_root": "lerobot.lerobot.isaac_lab_path",
    "isaac.sim_python": "lerobot.lerobot.isaac_sim_python",
    "isaac.scene_path": "lerobot.lerobot.isaac_scene_path",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate installation profile key: {key}")
        result[key] = value
    return result


def _load_document(source: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed installation profile JSON: {source}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Installation profile root must be an object: {source}")
    if loaded.get("schema") != INSTALLATION_PROFILE_SCHEMA:
        raise ValueError(f"Expected {INSTALLATION_PROFILE_SCHEMA}: {source}")
    unknown = set(loaded) - {"schema", "resources"}
    if unknown:
        raise ValueError(f"Unknown installation profile fields: {sorted(unknown)}")
    if "resources" not in loaded or not isinstance(loaded["resources"], dict):
        raise ValueError("Installation profile resources must be an object")
    return loaded


def _contains_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.search(value))


def _home(environ: Mapping[str, str]) -> str:
    return str(environ.get("HOME") or environ.get("USERPROFILE") or "").strip()


def _expand_home(raw: str, *, environ: Mapping[str, str], label: str) -> str:
    if raw == "~" or raw.startswith("~/") or raw.startswith("~\\"):
        home = _home(environ)
        if not home:
            raise ValueError(f"Cannot expand home in {label}: HOME is unset")
        if PureWindowsPath(home).is_absolute():
            return str(PureWindowsPath(home) / raw[2:]) if len(raw) > 1 else home
        return str(Path(home) / raw[2:]) if len(raw) > 1 else home
    if raw.startswith("~"):
        raise ValueError(f"Named-user home expansion is not supported in {label}")
    return raw


def _resolve_path_value(
    value: object, *, source: Path, environ: Mapping[str, str], label: str
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Installation resource {label} must be text")
    raw = value.strip()
    if not raw:
        return ""
    if _contains_placeholder(raw):
        raise ValueError(f"Unresolved environment placeholder in installation resource {label}")
    if PureWindowsPath(raw).is_absolute() or raw.startswith("\\\\"):
        return raw
    raw = _expand_home(raw, environ=environ, label=f"installation resource {label}")
    if PureWindowsPath(raw).is_absolute():
        return raw
    path = Path(raw)
    selected = path if path.is_absolute() else source.parent / path
    # Invocation spelling selects a virtualenv/alias; resolving its symlink loses it.
    return os.path.abspath(selected) if label in _EXECUTABLE_FIELDS else str(selected.resolve())


def _resolve_name(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Installation resource {label} must be text")
    name = value.strip()
    if _contains_placeholder(name):
        raise ValueError(f"Unresolved environment placeholder in installation resource {label}")
    return name


def _resource_group(
    group: str,
    raw: object,
    *,
    source: Path,
    environ: Mapping[str, str],
) -> object:
    resource_type = _RESOURCE_TYPES[group]
    if not isinstance(raw, dict):
        raise ValueError(f"Installation {group} resources must be an object")
    allowed = {field.name for field in fields(resource_type)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown {group} resource fields: {sorted(unknown)}")
    values: dict[str, object] = {}
    for key, value in raw.items():
        label = f"{group}.{key}"
        if (group, key) in _LIST_FIELDS:
            if not isinstance(value, list):
                raise ValueError(f"Installation resource {label} must be a list")
            values[key] = tuple(
                _resolve_path_value(item, source=source, environ=environ, label=label)
                for item in value
            )
        elif (group, key) in _NAME_FIELDS:
            values[key] = _resolve_name(value, label=label)
        else:
            values[key] = _resolve_path_value(
                value, source=source, environ=environ, label=label
            )
    return resource_type(**values)


def load_installation_profile(
    paths: RuntimePaths,
    *,
    environ: Mapping[str, str] | None = None,
) -> InstallationProfile:
    """Load the selected profile without searching or touching external resources."""
    selected_environment = environ if environ is not None else os.environ
    explicit = str(selected_environment.get(INSTALLATION_PROFILE_ENV) or "").strip()
    if explicit:
        selected = Path(_expand_home(explicit, environ=selected_environment,
                                     label=INSTALLATION_PROFILE_ENV)).resolve()
        if not selected.is_file():
            raise FileNotFoundError(
                f"{INSTALLATION_PROFILE_ENV} selects a missing profile: {selected}"
            )
    else:
        selected = (paths.repository_root / "installation.local.json").resolve()
        if not selected.exists():
            return InstallationProfile(
                schema=INSTALLATION_PROFILE_SCHEMA,
                resources=InstallationResources(),
                source=None,
                configured=False,
                provenance=MappingProxyType({}),
            )
        if not selected.is_file():
            raise ValueError(f"Default installation profile is not a file: {selected}")
    document = _load_document(selected)
    raw_resources = document.get("resources", {})
    unknown_groups = set(raw_resources) - set(_RESOURCE_TYPES)
    if unknown_groups:
        raise ValueError(f"Unknown installation resource groups: {sorted(unknown_groups)}")
    values = {
        group: _resource_group(
            group,
            raw_resources.get(group, {}),
            source=selected,
            environ=selected_environment,
        )
        for group in _RESOURCE_TYPES
    }
    provenance: dict[str, str] = {}
    for group, resources in values.items():
        for field in fields(resources):
            value = getattr(resources, field.name)
            if value:
                name = f"{group}.{field.name}"
                provenance[name] = f"profile:{selected}#resources.{name}"
    return InstallationProfile(
        schema=INSTALLATION_PROFILE_SCHEMA,
        resources=InstallationResources(**values),
        source=selected,
        configured=True,
        provenance=MappingProxyType(provenance),
    )


def _resource_values(profile: InstallationProfile):
    for group_field in fields(profile.resources):
        group = group_field.name
        resources = getattr(profile.resources, group)
        for resource_field in fields(resources):
            value = getattr(resources, resource_field.name)
            if value:
                yield f"{group}.{resource_field.name}", value


def _target_parent(bundle: dict[str, Any], dotted: str) -> tuple[dict[str, Any], str]:
    parts = dotted.split(".")
    current = bundle
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ValueError(f"Installation resource target is not an object: {dotted}")
        current = child
    return current, parts[-1]


def _is_configured(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != () and value != {}


def apply_installation_profile(
    bundle: dict[str, Any], profile: InstallationProfile
) -> dict[str, Any]:
    """Return an owned bundle with allowlisted profile values applied copy-on-write."""
    if not isinstance(bundle, dict):
        raise ValueError("Configuration bundle must be an object")
    result = deepcopy(bundle)
    if not profile.configured:
        return result
    diagnostics: list[dict[str, str]] = []
    provenance: dict[str, str] = {}
    for resource, value in _resource_values(profile):
        target = _RESOURCE_TARGETS[resource]
        parent, key = _target_parent(result, target)
        if _is_configured(parent.get(key)):
            diagnostics.append(
                {
                    "code": "INSTALLATION_PROFILE_CONFLICT",
                    "resource": resource,
                    "target": target,
                    "winner": "legacy_config",
                    "profile_source": str(profile.source),
                }
            )
            provenance[resource] = f"legacy_config:{target}"
            continue
        parent[key] = list(value) if isinstance(value, tuple) else value
        provenance[resource] = profile.provenance[resource]
    result["installation"] = {
        "schema": profile.schema,
        "profile": str(profile.source),
        "configured": True,
        "provenance": provenance,
        "diagnostics": diagnostics,
    }
    return result


def installation_metadata(profile: InstallationProfile) -> dict[str, str]:
    """Return the absolute selector needed to reproduce a configured profile."""
    if not profile.configured or profile.source is None:
        return {}
    source = profile.source.resolve()
    if not source.is_absolute():
        raise ValueError("Installation profile source must be absolute")
    return {INSTALLATION_PROFILE_ENV: str(source)}
