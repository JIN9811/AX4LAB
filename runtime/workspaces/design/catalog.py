"""Installed Design capabilities and pinned, code-owned numerical source identity."""
from copy import deepcopy
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform

from workspaces.catalog import discover_modules
from workspaces.fields import normalize_fields


DEFAULT_ROOT = Path(__file__).parent / "modules"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]


def _module_schema(value):
    if value.get("schema") != "ax4lab.design_module.v1":
        raise ValueError("Unsupported design module schema")
    return value


def _geometry_schema(value):
    if value.get("schema") != "ax4lab.geometry_provider.v1":
        raise ValueError("Unsupported geometry provider schema")
    modes = value.get("representations")
    if (not isinstance(modes, list) or not modes or
            any(not isinstance(mode, str) or not mode for mode in modes) or len(set(modes)) != len(modes)):
        raise ValueError("Invalid representations")
    if value.get("default_representation") not in modes:
        raise ValueError("Invalid default representation")
    if not isinstance(value.get("stochastic", False), bool):
        raise ValueError("stochastic must be boolean")
    if value.get("engine", "field") not in {"field", "legacy_gyroid"}:
        raise ValueError("Unsupported geometry engine")
    normalize_fields(value.get("fields", []), value.get("defaults", {}), {})
    groups = value.get("representation_parameters", {})
    if not isinstance(groups, dict) or set(groups) - set(modes):
        raise ValueError("Invalid representation parameter groups")
    for group in groups.values():
        if not isinstance(group, dict) or set(group) != {"fields", "defaults"}:
            raise ValueError("Representation parameters require fields and defaults")
        normalize_fields(group["fields"], group["defaults"], {})
    return value


def parameter_schema(descriptor, representation):
    """A representation group replaces, rather than adds hidden inactive parameters."""
    group = descriptor.get("representation_parameters", {}).get(representation, descriptor)
    return group.get("fields", []), group.get("defaults", {})


def source_files(record, module):
    """Dependencies are code-owned, never executable paths supplied in YAML.

    Hash all shared provider implementation files conservatively: changing one
    invalidates all acceptance snapshots. Installed providers must be self-contained
    wrappers over this shared package (no untracked dynamic numerical imports).
    """
    files = {
        "module/module.yaml": module["descriptor_path"],
        "module/provider.py": module["provider_path"],
        "geometry/module.yaml": record["descriptor_path"],
        "geometry/provider.py": record["provider_path"],
    }
    for name, path in files.items():
        owner = module if name.startswith("module/") else record
        if not path.resolve().is_relative_to(owner["root"]):
            raise ValueError("Provider source escapes installed module")
    paths = [RUNTIME_ROOT / name for name in (
        "workspaces/catalog.py", "workspaces/fields.py", "workspaces/design/catalog.py",
        "workspaces/design/engine.py", "workspaces/design/meshing.py", "workspaces/design/tool_adapter.py",
        "mcp_tools/tpms_geometry.py", "mcp_tools/mesh_quality.py")]
    paths.extend(sorted((RUNTIME_ROOT / "workspaces/design/providers").glob("*.py")))
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing numerical source dependency: {path.name}")
        if not path.resolve().is_relative_to(RUNTIME_ROOT):
            raise ValueError("Numerical source escapes runtime")
        files[path.relative_to(RUNTIME_ROOT).as_posix()] = path
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
    dependencies = {"python": platform.python_version()}
    for name in ("numpy", "scipy", "scikit-image", "trimesh"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = "unavailable"
    hashes.update({"environment/" + name: hashlib.sha256(value.encode()).hexdigest()
                   for name, value in dependencies.items()})
    return dict(sorted(hashes.items()))


def _fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DesignCatalog:
    def __init__(self, root: Path | None = None):
        self.root = Path(root if root is not None else DEFAULT_ROOT).resolve()
        self.modules, self.errors = discover_modules(self.root, _module_schema)
        self.geometries = {}
        for module in self.modules:
            geometry_root = module["root"] / "geometries"
            if not geometry_root.resolve().is_relative_to(module["root"]):
                self.errors.append({"module": module["id"], "message": "Geometry directory escapes module"})
                continue
            records, errors = discover_modules(geometry_root, _geometry_schema)
            self.errors.extend({**error, "module_id": module["id"]} for error in errors)
            for record in records:
                try:
                    sources = source_files(record, module)
                    record.update(module_id=module["id"], module_version=module["version"],
                                  source_files=sources, source_fingerprint=_fingerprint(sources))
                    self.geometries[(module["id"], record["id"])] = record
                except (OSError, ValueError) as exc:
                    self.errors.append({"module": record["id"], "message": str(exc)})

    def resolve(self, module_id: str, geometry_id: str, version: str) -> dict:
        if not all(isinstance(value, str) for value in (module_id, geometry_id, version)):
            raise ValueError("Module/provider identity must be strings")
        record = self.geometries.get((module_id, geometry_id))
        if record is None or record["version"] != version:
            raise ValueError("Unknown or unavailable geometry provider/version")
        module = next(item for item in self.modules if item["id"] == module_id)
        try:
            current = source_files(record, module)
        except OSError as exc:
            raise ValueError("Provider source changed or removed; refresh catalog") from exc
        if current != record["source_files"]:
            raise ValueError("Provider source changed; refresh catalog and restart loaded workers")
        return deepcopy(record)
