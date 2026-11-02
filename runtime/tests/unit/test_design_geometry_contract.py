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
        "label": "Fixture", "actions": ["preview", "generate"], "output_kinds": ["stl"]}))
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


@pytest.mark.parametrize("key,value", [
    ("actions", None), ("actions", []), ("actions", "preview"),
    ("actions", ["preview", "preview"]), ("actions", ["shell"]),
    ("actions", [{"name": "preview", "command": "run"}]),
    ("output_kinds", None), ("output_kinds", []), ("output_kinds", ["exe"]),
    ("output_kinds", ["stl", "stl"]),
])
def test_invalid_action_contract_is_excluded(tmp_path, key, value):
    from workspaces.design.catalog import DesignCatalog
    install_provider(tmp_path)
    path = tmp_path / "fixture/module.yaml"
    data = yaml.safe_load(path.read_text())
    if value is None:
        data.pop(key)
    else:
        data[key] = value
    path.write_text(yaml.safe_dump(data))
    catalog = DesignCatalog(tmp_path)
    assert catalog.modules == []
    assert catalog.errors


@pytest.mark.parametrize("capability", [None, False, True, "yes", {}, 1])
def test_agent_capability_is_conservative_and_validated(tmp_path, capability):
    from workspaces.design.catalog import DesignCatalog
    geometry = install_provider(tmp_path)
    path = geometry / "module.yaml"
    data = yaml.safe_load(path.read_text())
    if capability is not None:
        data["agent_handoff"] = capability
    path.write_text(yaml.safe_dump(data))
    catalog = DesignCatalog(tmp_path)
    if capability is not None and type(capability) is not bool:
        assert not catalog.geometries
        assert catalog.errors
    else:
        assert catalog.resolve("fixture", "slab", "1.0.0")["descriptor"]["agent_handoff"] is (capability is True)


def test_all_shipped_geometries_intentionally_support_agent_handoff(catalog):
    assert len(catalog.geometries) == 14
    for record in catalog.geometries.values():
        # Read the declared contract, not a runtime permissive default.
        assert yaml.safe_load(record["descriptor_path"].read_text())["agent_handoff"] is True


def test_preview_only_module_rejects_final_in_api_and_engine(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workspaces.design.api import create_router
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    from workspaces.design.service import DesignService
    install_provider(tmp_path / "modules")
    path = tmp_path / "modules/fixture/module.yaml"
    data = yaml.safe_load(path.read_text())
    data["actions"] = ["preview"]
    path.write_text(yaml.safe_dump(data))
    catalog = DesignCatalog(tmp_path / "modules")
    service = DesignService(tmp_path / "memory", tmp_path / "artifacts", catalog=catalog)
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    req = request(module_id="fixture", geometry_id="slab")
    try:
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1)) as client:
            assert client.post("/api/design/validate", json={"request": req}).status_code == 200
            for endpoint in ("validate", "jobs"):
                body = {"request": {**req, "quality": "final"}}
                if endpoint == "jobs": body["idempotency_key"] = "unsupported"
                response = client.post("/api/design/" + endpoint, json=body)
                assert response.status_code == 422, response.text
                assert "action" in response.text
            assert service.jobs() == []
        with pytest.raises(ValueError, match="action"):
            generate_geometry({**req, "quality": "final"}, tmp_path / "denied", identity={}, catalog=catalog)
        preview = generate_geometry(req, tmp_path / "preview", identity={}, catalog=catalog)
        assert preview["ok"] and not preview["final_geometry_valid"]
    finally:
        service.shutdown()


def test_manual_only_provider_really_generates_but_agent_admission_rejects(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.design import geometry_adapter
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    install_provider(tmp_path / "modules")
    catalog = DesignCatalog(tmp_path / "modules")
    req = request(module_id="fixture", geometry_id="slab", quality="final")
    receipt = generate_geometry(req, tmp_path / "manual", identity={"job_id":"manual"}, catalog=catalog)
    assert receipt["final_geometry_valid"] and receipt["checks"]["stl_reload"] == "passed"
    monkeypatch.setattr(geometry_adapter, "DesignCatalog", lambda: catalog)
    ctx = SimpleNamespace(paths=SimpleNamespace(memory_root=tmp_path / "memory"))
    with pytest.raises(ValueError, match="manual.only|agent handoff"):
        geometry_adapter.enabled_catalog(ctx, req)


@pytest.mark.parametrize("geometry,parameters,changes,reason", [
    ("simple_cubic", {"cell_size_mm":10, "strut_diameter_mm":6}, {}, "half cell"),
    ("simple_cubic", {}, {"resolution":16}, "voxels"),
    ("simple_cubic", {"cell_size_mm":2, "strut_diameter_mm":.5}, {"specimen_size_mm":[100,100,100]}, "budget"),
    ("schwarz_p", {"cell_size_mm":10, "wall_thickness_mm":2}, {}, "thin-sheet"),
    ("schwarz_p", {}, {"resolution":16}, "samples|voxels"),
    ("spinodoid", {"cone_angles_deg":[0,0,0]}, {"seed":42}, "cone"),
    ("spinodoid", {"wave_count":512}, {"seed":42, "resolution":160}, "budget"),
    ("spinodoid", {"wavelength_mm":2}, {"seed":42}, "wavelength"),
    ("reentrant_honeycomb", {"inclined_length_mm":10, "vertical_length_mm":2, "angle_deg":-60}, {}, "collapsed"),
    ("voronoi", {"strut_diameter_mm":4}, {"seed":42, "specimen_size_mm":[10,10,10]}, "diameter"),
])
def test_shared_preflight_rejects_known_impossible_requests(catalog, geometry, parameters, changes, reason):
    from workspaces.design.engine import normalize_request
    with pytest.raises(ValueError, match=reason):
        normalize_request({"module_id":MODULE, "geometry_id":geometry, "provider_version":"1.0.0",
                           "quality":"final", "resolution":96, "parameters":parameters, **changes}, catalog)


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
