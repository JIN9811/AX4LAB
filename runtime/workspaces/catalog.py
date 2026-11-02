"""Discover trusted installed workspace modules without importing providers."""

from copy import deepcopy
import math
from pathlib import Path
import re
from typing import Callable

import yaml


_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_REMOTE_SCHEME = re.compile(r"^(?:https?|data|file|javascript):", re.IGNORECASE)
_PROVIDER_FILE = "__provider_file__"
_EXECUTABLE_KEYS = {
    "callback",
    "code",
    "command",
    "equation",
    "expression",
    "import",
    "imports",
    "javascript",
    "provider",
    "provider_import",
    "python",
    "python_import",
    "script",
    "shell",
}


def _safe_metadata(value, *, source=True):
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and _REMOTE_SCHEME.match(value.strip()):
            raise ValueError("Remote resource URLs are not allowed in module metadata")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Module metadata numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _safe_metadata(item, source=source)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Module metadata keys must be strings")
            if key.lower() in _EXECUTABLE_KEYS:
                raise ValueError(f"Unsafe module metadata key: {key}")
            if source and key.startswith("__"):
                raise ValueError("Reserved module metadata key")
            _safe_metadata(item, source=source)
        return
    raise ValueError("Module metadata must contain only declarative YAML values")


def _contained_file(module_root: Path, candidate: Path, label: str) -> Path:
    if candidate.is_absolute():
        raise ValueError(f"{label} escapes module directory")
    path = (module_root / candidate).resolve()
    if not path.is_relative_to(module_root):
        raise ValueError(f"{label} escapes module directory")
    if not path.is_file():
        raise ValueError(f"Missing {label}")
    return path


def _identity(descriptor: dict) -> tuple[str, str]:
    identity = descriptor.get("id")
    version = descriptor.get("version")
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError("Invalid module ID")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("Invalid module version")
    if not isinstance(descriptor.get("label"), str) or not descriptor["label"].strip():
        raise ValueError("Missing module label")
    return identity, version


def discover_modules(
    root: Path, validator: Callable[[dict], dict]
) -> tuple[list[dict], list[dict]]:
    """Return valid module snapshots and isolated discovery errors.

    Discovery reads declarative metadata and resolves local assets, but never
    imports provider code.  Validators are code-owned schema adapters.  New
    workspaces use the fixed ``provider.py`` convention; the private provider
    override exists only for legacy adapters such as Serial Communication.
    """

    catalog_root = Path(root).resolve()
    found: dict[str, dict] = {}
    errors: list[dict] = []
    duplicates: set[str] = set()

    for descriptor_slot in sorted(catalog_root.glob("*/module.yaml")):
        module_name = descriptor_slot.parent.name
        try:
            module_root = descriptor_slot.parent.resolve()
            if not module_root.is_relative_to(catalog_root):
                raise ValueError("Module directory escapes catalog")
            descriptor_path = _contained_file(
                module_root, Path("module.yaml"), "module descriptor"
            )
            descriptor = yaml.safe_load(descriptor_path.read_text(encoding="utf-8"))
            if not isinstance(descriptor, dict):
                raise ValueError("Module descriptor must be an object")
            _safe_metadata(descriptor)

            validated = validator(deepcopy(descriptor))
            if not isinstance(validated, dict):
                raise ValueError("Module validator must return an object")
            provider_file = validated.pop(_PROVIDER_FILE, "provider.py")
            if (
                not isinstance(provider_file, str)
                or not provider_file
                or Path(provider_file).name != provider_file
            ):
                raise ValueError("Invalid provider convention")
            _safe_metadata(validated, source=False)
            identity, version = _identity(validated)

            icon = validated.get("icon", "icon.svg")
            if not isinstance(icon, str) or not icon:
                raise ValueError("Invalid module icon")
            provider_path = _contained_file(
                module_root, Path(provider_file), "module provider"
            )
            icon_path = _contained_file(module_root, Path(icon), "module icon")
            record = {
                "id": identity,
                "version": version,
                "root": module_root,
                "descriptor_path": descriptor_path,
                "provider_path": provider_path,
                "icon_path": icon_path,
                "descriptor": deepcopy(validated),
            }
            if identity in found:
                duplicates.add(identity)
            found[identity] = record
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            errors.append({"module": module_name, "message": str(exc)})

    for identity in sorted(duplicates):
        found.pop(identity, None)
        errors.append({"module": identity, "message": "Duplicate module ID"})
    return list(found.values()), errors
