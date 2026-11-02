"""Real contract boundaries: no fallback IDs, mutable identity, or unchecked STL."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml


MODULE = "metamaterial_unit_cell_designer"


def request(**overrides):
    return {"module_id": MODULE, "geometry_id": "gyroid", "provider_version": "1.0.0",
            "specimen_size_mm": [10, 10, 10], **overrides}


@pytest.fixture
def catalog():
    from workspaces.design.catalog import DesignCatalog
    return DesignCatalog()


def test_orientation_capability_matches_each_representation(catalog):
    from workspaces.design.engine import normalize_request
    descriptor = catalog.resolve(MODULE, 'gyroid', '1.0.0')['descriptor']
    for representation in descriptor['representations']:
        axes = descriptor['representation_orientation_axes'][representation]
        for axis, index in [('x', 0), ('y', 1), ('z', 2)]:
            orientation = [0, 0, 0]
            orientation[index] = 15
            value = request(representation=representation, orientation_deg=orientation)
            if axis in axes:
                assert normalize_request(value, catalog)['orientation_deg'][index] == 15
            else:
                with pytest.raises(ValueError, match='orientation'):
                    normalize_request(value, catalog)


@pytest.mark.parametrize("overrides", [
    {"geometry_id": "unknown"}, {"module_id": "../outside"},
    {"geometry_id": "../gyroid"}, {"provider_version": "9.0.0"},
    {"specimen_size_mm": [-1, 10, 10]}, {"specimen_size_mm": [float("nan"), 10, 10]},
    {"specimen_size_mm": [True, 10, 10]}, {"orientation_deg": [0, float("inf"), 0]},
    {"representation": "made_up"}, {"resolution": 513}, {"resolution": True},
    {"quality": "manufacture"}, {"seed": -1}, {"output_dir": "../escape"},
    {"parameters": {"command": "unsafe"}}, {"schema": "unknown"},
    {"quality": []}, {"specimen_size_mm": [10**1000, 10, 10]},
    {"specimen_size_mm": [1e-200, 10, 10]}, {"specimen_size_mm": [1001, 10, 10]},
])
def test_invalid_requests_fail_without_gyroid_fallback(catalog, overrides):
    from workspaces.design.engine import normalize_request
    with pytest.raises(ValueError):
        normalize_request(request(**overrides), catalog)


def test_defaults_are_explicit_and_request_hash_ignores_mapping_order(catalog):
    from workspaces.design.engine import normalize_request, request_sha256
    normalized = normalize_request(request(), catalog)
    assert normalized["schema"] == "ax4lab.geometry_request.v1"
    assert normalized["representation"] == "sheet"
    assert normalized["quality"] == "preview"
    assert normalized["orientation_deg"] == [0., 0., 0.]
    assert normalized["parameters"]["cell_size_mm"] == 5.
    assert normalized["parameters"]["wall_thickness_mm"] == 0.8
    assert normalized["seed"] is None
    assert normalize_request(normalized, catalog) == normalized
    assert request_sha256(normalized) == request_sha256(dict(reversed(list(normalized.items()))))
    assert request_sha256(normalized) != request_sha256({**normalized, "quality": "final"})


def install_provider(root, *, stochastic=False):
    """An actual external installed provider: long slab rotated before clipping."""
    module = root / "fixture"
    geometry = module / "geometries" / "slab"
    geometry.mkdir(parents=True)
    (module / "module.yaml").write_text(yaml.safe_dump({
        "schema": "ax4lab.design_module.v1", "id": "fixture", "version": "1.0.0",
        "label": "Fixture", "actions": ["generate"], "output_kinds": ["stl"]}))
    (module / "provider.py").write_text('raise RuntimeError("catalog must not import me")\n')
    (module / "icon.svg").write_text("<svg/>")
    (geometry / "module.yaml").write_text(yaml.safe_dump({
        "schema": "ax4lab.geometry_provider.v1", "id": "slab", "version": "1.0.0",
        "label": "Slab", "representations": ["solid"], "default_representation": "solid",
        "fields": [], "defaults": {}, "stochastic": stochastic}))
    (geometry / "provider.py").write_text(
        'import numpy as np\n'
        'def generate_field(grid, request):\n'
        '    return {"field": np.abs(grid["x"]) - 1.5, "units": "mm",\n'
        '            "bounds_mm": grid["bounds_mm"], "method": "analytic_slab_distance"}\n')
    (geometry / "icon.svg").write_text("<svg/>")
    return geometry


def test_discovery_does_not_execute_and_seed_is_required(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import normalize_request
    install_provider(tmp_path, stochastic=True)
    cat = DesignCatalog(tmp_path)
    req = request(module_id="fixture", geometry_id="slab")
    with pytest.raises(ValueError, match="seed"):
        normalize_request(req, cat)
    assert normalize_request({**req, "seed": 42}, cat)["seed"] == 42


def test_source_fingerprint_pins_provider_and_shared_numeric_dependencies(tmp_path, catalog):
    from workspaces.design.catalog import DesignCatalog
    geometry = install_provider(tmp_path)
    cat = DesignCatalog(tmp_path)
    first = cat.resolve("fixture", "slab", "1.0.0")
    (geometry / "provider.py").write_text((geometry / "provider.py").read_text() + "\n# new source\n")
    second = DesignCatalog(tmp_path).resolve("fixture", "slab", "1.0.0")
    assert first["source_fingerprint"] != second["source_fingerprint"]
    with pytest.raises(ValueError, match="changed"):
        cat.resolve("fixture", "slab", "1.0.0")
    legacy = catalog.resolve(MODULE, "gyroid", "1.0.0")
    assert "mcp_tools/tpms_geometry.py" in legacy["source_files"]
    assert "workspaces/design/meshing.py" in legacy["source_files"]
    # Binary scientific dependencies also alter output under unchanged Python wrappers.
    assert "environment/numpy" in legacy["source_files"]
    assert "environment/scikit-image" in legacy["source_files"]


def test_rotated_field_is_closed_inside_fixed_envelope_and_reload_valid(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    install_provider(tmp_path / "modules")
    cat = DesignCatalog(tmp_path / "modules")
    req = request(module_id="fixture", geometry_id="slab", quality="final",
                  specimen_size_mm=[10, 8, 6], resolution=40, orientation_deg=[0, 0, 90])
    receipt = generate_geometry(req, tmp_path / "artifacts", identity={"run_id": "r1"}, catalog=cat)
    assert receipt["ok"]
    assert receipt["checks"]["watertight"]
    assert receipt["checks"]["winding_consistent"]
    assert receipt["checks"]["component_count"] == 1
    assert receipt["checks"]["stl_reload"] == "passed"
    assert receipt["bounds_mm"] == pytest.approx(np.array([[-5, -1.5, -3], [5, 1.5, 3]]), abs=.04)
    assert receipt["volume_mm3"] == pytest.approx(180, rel=.02)
    assert receipt["checks"]["physical_printability"] == "unchecked"
    assert receipt["checks"]["self_intersections"] == "unchecked"
    artifact = receipt["artifacts"]["stl"]
    assert Path(artifact["basename"]).name == artifact["basename"]
    assert hashlib.sha256((tmp_path / "artifacts" / artifact["basename"]).read_bytes()).hexdigest() == artifact["sha256"]


def test_repeatable_receipts_and_immutable_contained_artifacts(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    install_provider(tmp_path / "modules")
    cat = DesignCatalog(tmp_path / "modules")
    req = request(module_id="fixture", geometry_id="slab", resolution=32)
    receipt = generate_geometry(req, tmp_path / "a", identity={"candidate_id": "candidate_1"}, catalog=cat)
    other = generate_geometry(req, tmp_path / "b", identity={"candidate_id": "candidate_1"}, catalog=cat)
    assert receipt == other
    assert receipt["manufacturing_ready"] is False
    assert receipt["quality"] == "preview"
    assert json.loads((tmp_path / "a" / "receipt.json").read_text()) == receipt
    with pytest.raises(FileExistsError):
        generate_geometry(req, tmp_path / "a", identity={}, catalog=cat)
    with pytest.raises(ValueError):
        generate_geometry(req, tmp_path / "traversal", identity={"run_id": "../escape"}, catalog=cat)
    (tmp_path / "link").symlink_to(tmp_path / "b", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        generate_geometry(req, tmp_path / "link", identity={}, catalog=cat)


def test_worker_rejects_changed_acceptance_fingerprint_before_writing(tmp_path, catalog):
    from utils.compute_jobs import execute
    from utils.compute_pool import JOBS
    from workspaces.design.engine import normalize_request
    assert "geometry.design_generate" in JOBS
    req = normalize_request(request(), catalog)
    with pytest.raises(ValueError, match="fingerprint"):
        execute("geometry.design_generate", {"request": req, "output_dir": str(tmp_path / "job"),
            "identity": {}, "source_fingerprint": "0" * 64})
    assert not (tmp_path / "job").exists()


@pytest.mark.parametrize("field", ["empty", "nonfinite", "disconnected"])
def test_bad_numeric_fields_do_not_publish_success(tmp_path, field):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    geometry = install_provider(tmp_path / "modules")
    formula = {"empty": 'np.ones_like(grid["x"])',
               "nonfinite": 'np.full_like(grid["x"], np.nan)',
               "disconnected": 'np.minimum((grid["x"]-3)**2+grid["y"]**2+grid["z"]**2-1, (grid["x"]+3)**2+grid["y"]**2+grid["z"]**2-1)'}[field]
    (geometry / "provider.py").write_text('import numpy as np\ndef generate_field(grid, request):\n'
        f'    return {{"field": {formula}, "units": "mm", "bounds_mm": grid["bounds_mm"], "method": "fixture"}}\n')
    with pytest.raises(ValueError):
        generate_geometry(request(module_id="fixture", geometry_id="slab", quality="final"),
                          tmp_path / "out", identity={}, catalog=DesignCatalog(tmp_path / "modules"))
    assert not (tmp_path / "out" / "receipt.json").exists()


def test_provider_accuracy_gate_rejects_final_but_labels_preview(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    geometry = install_provider(tmp_path / "modules")
    source = (geometry / "provider.py").read_text().replace(
        '"method": "analytic_slab_distance"',
        '"method": "analytic_slab_distance", "validation": {"ok": False, "reject_reasons": ["insufficient_wall_resolution"]}')
    (geometry / "provider.py").write_text(source)
    cat = DesignCatalog(tmp_path / "modules")
    req = request(module_id="fixture", geometry_id="slab")
    with pytest.raises(ValueError, match="insufficient_wall_resolution"):
        generate_geometry({**req, "quality": "final"}, tmp_path / "final", identity={}, catalog=cat)
    preview = generate_geometry(req, tmp_path / "preview", identity={}, catalog=cat)
    assert not preview["checks"]["provider_validation"]["ok"]
    assert preview["final_geometry_valid"] is False


def test_catalog_rejects_provider_symlink_swap_even_with_identical_bytes(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    geometry = install_provider(tmp_path / "modules")
    cat = DesignCatalog(tmp_path / "modules")
    external = tmp_path / "external.py"
    provider = geometry / "provider.py"
    external.write_bytes(provider.read_bytes())
    provider.unlink()
    provider.symlink_to(external)
    with pytest.raises(ValueError, match="escapes"):
        cat.resolve("fixture", "slab", "1.0.0")


def test_real_compute_worker_matches_direct_receipt_without_pool_recursion(tmp_path, monkeypatch):
    from dataclasses import replace
    from utils.compute_pool import ComputePool
    from utils.runtime_paths import current_paths
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry, normalize_request
    install_provider(tmp_path / "modules")
    cat = DesignCatalog(tmp_path / "modules")
    req = normalize_request(request(module_id="fixture", geometry_id="slab", resolution=32), cat)
    record = cat.resolve("fixture", "slab", "1.0.0")
    direct = generate_geometry(req, tmp_path / "direct", identity={}, catalog=cat)
    private = {name: tmp_path / name for name in ("run_root", "memory_root", "artifact_root", "output_root",
                                                "source_inbox_root", "user_file_root", "log_root")}
    paths = replace(current_paths(), **private)
    bindings = tmp_path / "bindings.json"
    bindings.write_text(json.dumps({"schema": "atr.path_bindings.v1", "stores": {key: str(value) for key, value in private.items()}}))
    monkeypatch.setenv("ATR_PATH_BINDINGS", str(bindings))
    pool = ComputePool(1, paths=paths)
    try:
        future, _ = pool.submit("geometry.design_generate", {"request": req, "identity": {},
            "catalog_root": str(cat.root), "source_fingerprint": record["source_fingerprint"],
            "output_dir": str(tmp_path / "worker")})
        assert future.result(timeout=30) == direct
        assert pool.status()["completed"] == 1
    finally:
        pool.close()


def test_loaded_legacy_source_cannot_be_relabelled_with_changed_dependency(tmp_path, monkeypatch):
    import shutil
    import workspaces.design.catalog as catalog_module
    from workspaces.design.engine import generate_geometry
    cat = catalog_module.DesignCatalog()
    generate_geometry(request(resolution=48), tmp_path / "first", identity={}, catalog=cat)
    record = cat.resolve(MODULE, "gyroid", "1.0.0")
    isolated_runtime = tmp_path / "runtime"
    for name in record["source_files"]:
        if name.startswith(("workspaces/", "mcp_tools/", "utils/")):
            destination = isolated_runtime / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(catalog_module.RUNTIME_ROOT / name, destination)
    dependency = isolated_runtime / "mcp_tools/tpms_geometry.py"
    dependency.write_text(dependency.read_text() + "\n# installed numerical code changed\n")
    monkeypatch.setattr(catalog_module, "RUNTIME_ROOT", isolated_runtime)
    changed = catalog_module.DesignCatalog()
    assert changed.resolve(MODULE, "gyroid", "1.0.0")["source_fingerprint"] != record["source_fingerprint"]
    with pytest.raises(ValueError, match="restart"):
        generate_geometry(request(resolution=48), tmp_path / "second", identity={}, catalog=changed)
    assert not (tmp_path / "second").exists()


def test_representation_schema_replaces_inactive_parameters(tmp_path):
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import normalize_request
    geometry = install_provider(tmp_path / "modules")
    descriptor_file = geometry / "module.yaml"
    descriptor = yaml.safe_load(descriptor_file.read_text())
    descriptor["representations"].append("network")
    descriptor["representation_parameters"] = {"network": {"fields": [
        {"key": "iso_level", "label": "Iso level", "type": "number", "min": -1, "max": 1}],
        "defaults": {"iso_level": 0}}}
    descriptor_file.write_text(yaml.safe_dump(descriptor))
    cat = DesignCatalog(tmp_path / "modules")
    req = request(module_id="fixture", geometry_id="slab", representation="network")
    assert normalize_request(req, cat)["parameters"] == {"iso_level": 0.0}
    with pytest.raises(ValueError):
        normalize_request({**req, "representation": "solid", "parameters": {"iso_level": 0}}, cat)


@pytest.mark.parametrize("preloaded,before,after", [
    ("mcp_tools.tpms_geometry", "return 1.5 * math.sin(", "return 1.4 * math.sin("),
    ("mcp_tools.mesh_quality", "if volume <= 0:", "if volume <= -1:"),
    ("workspaces.design.engine", 'ENGINE_VERSION = "1.0.0"', 'ENGINE_VERSION = "1.0.1"'),
    ("workspaces.design.providers.tpms", "return cx+cy+cz", "return 2*cx+cy+cz"),
    ("workspaces.design.providers.strut", "radius+2*max(spacing)", "radius+3*max(spacing)"),
    ("workspaces.design.providers.spinodoid", "np.sqrt(2/count)", "np.sqrt(3/count)"),
    ("workspaces.design.providers.cellular", "abs(angle)>=85", "abs(angle)>=84"),
])
def test_first_generation_rejects_dependency_changed_after_preload(tmp_path, preloaded, before, after):
    """A fresh process's cached Python must never be labelled with newer disk bytes."""
    import os
    import shutil
    import subprocess
    import sys
    runtime = Path(__file__).resolve().parents[2]
    isolated = tmp_path / "runtime"
    shutil.copytree(runtime / "workspaces", isolated / "workspaces", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("mcp_tools/tpms_geometry.py", "mcp_tools/mesh_quality.py", "utils/source_identity.py"):
        source = runtime / name
        if source.exists():
            target = isolated / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    script = '''
import importlib
from pathlib import Path
import sys
module = importlib.import_module(sys.argv[1])
if sys.argv[1].startswith("mcp_tools."):
    assert "workspaces.design.engine" not in sys.modules
path = Path(module.__file__)
source = path.read_text()
assert sys.argv[2] in source
path.write_text(source.replace(sys.argv[2], sys.argv[3]))
from workspaces.design.catalog import DesignCatalog
from workspaces.design.engine import generate_geometry
output = Path("first-generation")
try:
    generate_geometry({"module_id": "metamaterial_unit_cell_designer", "geometry_id": "gyroid",
        "provider_version": "1.0.0", "specimen_size_mm": [10,10,10], "resolution": 48},
        output, identity={}, catalog=DesignCatalog())
except ValueError as error:
    assert "restart" in str(error), str(error)
else:
    raise AssertionError("first generation accepted stale preloaded numerical code")
assert not output.exists(), "source rejection must precede artifact allocation"
'''
    completed = subprocess.run([sys.executable, "-c", script, preloaded, before, after],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(isolated)}, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
