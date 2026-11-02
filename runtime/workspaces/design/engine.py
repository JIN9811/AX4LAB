"""Validated deterministic geometry requests and immutable, host-owned artifacts."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from workspaces.fields import normalize_fields
from .catalog import DesignCatalog, parameter_schema


REQUEST_SCHEMA = "ax4lab.geometry_request.v1"
ENGINE_VERSION = "1.0.0"
MAX_RESOLUTION = 160
MAX_GRID_POINTS = 4_251_528  # (160 + two closure samples)^3
_KEYS = {"schema", "module_id", "geometry_id", "provider_version", "representation", "parameters",
         "specimen_size_mm", "orientation_deg", "quality", "resolution", "seed"}
_IDENTITY_KEYS = {"run_id", "candidate_id", "specimen_id", "experiment_id", "job_id"}
_LOADED_SOURCES = {}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def request_sha256(normalized):
    return hashlib.sha256(canonical_json(normalized).encode()).hexdigest()


def _vector(value, name, *, positive=False):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must contain three numbers")
    try:
        invalid = any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or
                      (positive and not .001 <= x <= 1000) for x in value)
    except OverflowError:
        invalid = True
    if invalid:
        raise ValueError(f"{name} must contain finite {'positive ' if positive else ''}numbers")
    return [float(x) if x else 0.0 for x in value]


def normalize_request(request: dict, catalog: DesignCatalog) -> dict:
    if not isinstance(request, dict) or set(request) - _KEYS:
        raise ValueError("Unknown geometry request keys")
    if request.get("schema", REQUEST_SCHEMA) != REQUEST_SCHEMA:
        raise ValueError("Unsupported geometry request schema")
    record = catalog.resolve(request.get("module_id"), request.get("geometry_id"), request.get("provider_version"))
    descriptor = record["descriptor"]
    representation = request.get("representation", descriptor["default_representation"])
    if representation not in descriptor["representations"]:
        raise ValueError("Unsupported representation")
    fields, defaults = parameter_schema(descriptor, representation)
    parameters = normalize_fields(fields, defaults, request.get("parameters", {}))
    for field in fields:
        if field["type"] == "number":
            parameters[field["key"]] = float(parameters[field["key"]])
        elif field["type"] == "vector":
            parameters[field["key"]] = [float(x) for x in parameters[field["key"]]]
    size = _vector(request.get("specimen_size_mm", [30, 30, 30]), "specimen_size_mm", positive=True)
    orientation = _vector(request.get("orientation_deg", [0, 0, 0]), "orientation_deg")
    quality = request.get("quality", "preview")
    if not isinstance(quality, str) or quality not in {"preview", "final"}:
        raise ValueError("quality must be preview or final")
    resolution = request.get("resolution", 48 if quality == "preview" else 96)
    if type(resolution) is not int or not 16 <= resolution <= MAX_RESOLUTION:
        raise ValueError(f"resolution must be an integer in [16, {MAX_RESOLUTION}]")
    seed = request.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2**32 - 1):
        raise ValueError("seed must be a uint32 integer")
    if (descriptor.get("stochastic", False) or parameters.get("defect_ratio", 0) > 0) and seed is None:
        raise ValueError("seed is required for stochastic geometry")
    if descriptor.get("engine") == "legacy_gyroid" and representation == "sheet":
        if orientation[:2] != [0, 0]:
            raise ValueError("Legacy Gyroid sheet supports z orientation only")
        if min(size) < 1:
            raise ValueError("Legacy Gyroid requires specimen dimensions >= 1 mm")
        wall, cell = parameters["wall_thickness_mm"], parameters["cell_size_mm"]
        if not 0 < wall < cell / 2:
            raise ValueError("wall_thickness_mm must be below half cell_size_mm")
        # Preserve the writer's adaptive sampling exactly, but reject rather than
        # silently exceed this workspace's bounded numerical allocation budget.
        effective = max(48, resolution, math.ceil(max(size) * 3 / max(wall, .05)) + 1)
        if effective > MAX_RESOLUTION:
            raise ValueError("Legacy adaptive resolution exceeds workspace resource budget")
    return {"schema": REQUEST_SCHEMA, "module_id": record["module_id"], "geometry_id": record["id"],
            "provider_version": record["version"], "representation": representation,
            "parameters": parameters, "specimen_size_mm": size, "orientation_deg": orientation,
            "quality": quality, "resolution": resolution, "seed": seed}


def _identity(value):
    if not isinstance(value, dict) or set(value) - _IDENTITY_KEYS:
        raise ValueError("Unknown artifact identity keys")
    if any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", item)
           for item in value.values()):
        raise ValueError("Invalid artifact identity")
    return deepcopy(value)


def _pin_sources(record):
    shared = {name: digest for name, digest in record["source_files"].items()
              if name.startswith(("workspaces/", "mcp_tools/", "environment/"))}
    if _LOADED_SOURCES and shared != _LOADED_SOURCES:
        raise ValueError("Shared numerical source changed; restart worker")
    _LOADED_SOURCES.update(shared)


def _load_provider(record):
    # Compile exact bytes rather than timestamp-based pyc: installed wrapper edits
    # within the same second must not run stale bytecode under a new fingerprint.
    path = record["provider_path"]
    namespace = {"__name__": "_ax4lab_geometry_" + record["source_fingerprint"], "__file__": str(path)}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    generate = namespace.get("generate_field")
    if not callable(generate):
        raise ValueError("Provider must export generate_field")
    return generate


def generate_geometry(request: dict, output_dir: Path, *, identity: dict, catalog: DesignCatalog) -> dict:
    normalized = normalize_request(request, catalog)
    identity = _identity(identity)
    record = catalog.resolve(normalized["module_id"], normalized["geometry_id"], normalized["provider_version"])
    _pin_sources(record)
    output_dir = Path(output_dir).absolute()
    if ".." in output_dir.parts or any(path.is_symlink() for path in (output_dir, *output_dir.parents)):
        raise ValueError("Artifact path must not traverse or use symlinks")
    output_dir.mkdir(parents=True, exist_ok=False)
    stl = output_dir / "geometry.stl"
    from .meshing import create_grid, mesh_field, validate_mesh
    if record["descriptor"].get("engine") == "legacy_gyroid" and normalized["representation"] == "sheet":
        from .tool_adapter import write_legacy_gyroid
        metadata = write_legacy_gyroid(normalized, stl)
    else:
        grid = create_grid(normalized)
        field = _load_provider(record)(grid, deepcopy(normalized))
        metadata = mesh_field(grid, field, stl)
    provider_validation = metadata.get("validation", {"ok": True, "reject_reasons": [], "status": "not_applicable"})
    if (not isinstance(provider_validation, dict) or type(provider_validation.get("ok")) is not bool or
            not isinstance(provider_validation.get("reject_reasons"), list) or
            any(not isinstance(reason, str) for reason in provider_validation["reject_reasons"])):
        raise ValueError("Invalid provider validation metadata")
    if normalized["quality"] == "final" and not provider_validation["ok"]:
        raise ValueError(f"Provider final validation failed: {provider_validation['reject_reasons']}")
    # Any changed source invalidates the result before publication.
    catalog.resolve(normalized["module_id"], normalized["geometry_id"], normalized["provider_version"])
    checked = validate_mesh(stl, normalized["specimen_size_mm"])
    if not checked["ok"]:
        raise ValueError(f"Generated mesh failed checks: {checked['reject_reasons']}")
    checked["provider_validation"] = provider_validation
    final = normalized["quality"] == "final"
    receipt = {
        "schema": "ax4lab.geometry_receipt.v1", "ok": True, "quality": normalized["quality"],
        "manufacturing_ready": False,  # Geometry alone cannot establish manufacturing readiness.
        "final_geometry_valid": final, "request": normalized, "request_sha256": request_sha256(normalized),
        "engine_version": ENGINE_VERSION, "module_version": record["module_version"],
        "provider_version": record["version"], "source_fingerprint": record["source_fingerprint"],
        "source_files": record["source_files"], "identity": identity,
        "artifacts": {"stl": {"basename": stl.name, "sha256": hashlib.sha256(stl.read_bytes()).hexdigest(),
                              "size_bytes": stl.stat().st_size}},
        "bounds_mm": checked["bounds_mm"], "volume_mm3": checked["volume_mm3"],
        "volume_fraction": checked["volume_mm3"] / math.prod(normalized["specimen_size_mm"]),
        "volume_method": "closed_serialized_triangle_mesh", "checks": checked,
        "provider_metadata": metadata,
    }
    with (output_dir / "receipt.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(receipt) + "\n")
    return receipt
