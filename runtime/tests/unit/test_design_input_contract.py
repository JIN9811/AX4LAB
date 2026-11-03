"""Shared, executable design inputs for people and agents."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workspaces.design.api import create_router
from workspaces.design.catalog import DesignCatalog, _geometry_schema, parameter_schema
from workspaces.design.engine import normalize_request
from workspaces.design.service import DesignService
from workspaces.catalog import _safe_metadata


MODULE = "metamaterial_unit_cell_designer"


def request(geometry="simple_cubic", **changes):
    return dict(module_id=MODULE, geometry_id=geometry, provider_version="1.0.0", **changes)


@pytest.fixture
def catalog():
    return DesignCatalog()


@pytest.fixture
def client(tmp_path):
    service = DesignService(tmp_path / "memory", tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(create_router(service))
    try:
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1)) as client:
            yield client
    finally:
        service.shutdown()


def test_shipped_metadata_describes_all_representation_inputs(catalog):
    assert not catalog.errors
    assert len(catalog.geometries) == 14
    for record in catalog.geometries.values():
        descriptor = record["descriptor"]
        fields = [field for mode in descriptor["representations"]
                  for field in parameter_schema(descriptor, mode)[0]]
        assert set(descriptor["parameter_roles"]) == {field["key"] for field in fields}
        assert set(descriptor["parameter_roles"].values()) <= {"design", "fixed", "numerical"}
        assert all(field.get("description") for field in fields)
        assert descriptor["design_family"] and descriptor["design_notes"] and descriptor["default_basis"]
        assert all(source["title"] and source["url"].startswith("https://")
                   for source in descriptor["research_sources"])
        assert "workspaces/design/contracts.py" in record["source_files"]


@pytest.mark.parametrize("key,value", [
    ("parameter_roles", {"cell_size_mm": "invented"}),
    ("parameter_roles", {"unknown": "design"}),
    ("parameter_roles", {}), ("design_family", []), ("design_notes", "not a list"),
    ("design_notes", [1]), ("default_basis", {}), ("research_sources", "not a list"),
    ("research_sources", [{"title": "Unsafe", "url": "javascript:alert(1)"}]),
    ("research_sources", [{"title": "Missing URL"}]),
    ("research_sources", [{"title": "No host", "url": "https:///missing"}]),
    ("default_seed", True), ("default_seed", -1), ("default_seed", 2**32),
])
def test_invalid_optional_metadata_is_rejected(catalog, key, value):
    descriptor = deepcopy(catalog.geometries[(MODULE, "simple_cubic")]["descriptor"])
    descriptor[key] = value
    with pytest.raises(ValueError):
        _geometry_schema(descriptor)


def test_omitted_metadata_remains_compatible_with_third_party_providers(catalog):
    descriptor = deepcopy(catalog.geometries[(MODULE, "simple_cubic")]["descriptor"])
    for key in ("parameter_roles", "design_family", "design_notes", "default_basis", "research_sources"):
        descriptor.pop(key, None)
    assert _geometry_schema(descriptor)["id"] == "simple_cubic"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///tmp/paper", "data:text/plain,x",
                                "http://example.com/paper", "https://user@example.com/paper",
                                "https:///missing", "https://example.com:bad", "https://a b.com"])
def test_citation_exemption_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        _safe_metadata({"research_sources": [{"title": "Paper", "url": url}]}, reference_urls=True)


def test_citation_exemption_does_not_allow_remote_assets_or_nested_urls():
    citation = {"research_sources": [{"title": "Paper", "url": "https://example.com/paper"}]}
    _safe_metadata(citation, reference_urls=True)
    for metadata in (citation, {"icon": "https://example.com/icon.svg"},
                     {"fields": [{"url": "https://example.com/source"}]}):
        with pytest.raises(ValueError):
            _safe_metadata(metadata)
    with pytest.raises(ValueError):
        _safe_metadata({"icon": "https://example.com/icon.svg"}, reference_urls=True)


def test_final_defaults_and_explicit_zero_survive_normalization(catalog):
    normalized = normalize_request(request("gyroid", parameters={"skin_thickness_mm": 0}), catalog)
    assert (normalized["quality"], normalized["resolution"]) == ("final", 128)
    assert normalized["parameters"]["skin_thickness_mm"] == 0
    assert normalize_request(request("gyroid", representation="network_positive",
                                     parameters={"iso_level": 0}), catalog)["parameters"] == {
                                         "cell_size_mm": 12., "iso_level": 0.}


@pytest.mark.parametrize("geometry", ["spinodoid", "voronoi"])
def test_stochastic_seed_defaults_only_when_omitted(catalog, geometry):
    assert normalize_request(request(geometry), catalog)["seed"] == 42
    assert normalize_request(request(geometry, seed=0), catalog)["seed"] == 0
    with pytest.raises(ValueError, match="seed"):
        normalize_request(request(geometry, seed=None), catalog)


def test_contract_templates_normalize_each_mode_without_inactive_inputs(client, catalog):
    for record in catalog.geometries.values():
        path = f"/api/design/modules/{MODULE}/geometries/{record['id']}/contract"
        default = client.get(path)
        assert default.status_code == 200, default.text
        assert default.json()["representation"] == record["descriptor"]["default_representation"]
        for mode in record["descriptor"]["representations"]:
            response = client.get(path, params={"representation": mode})
            assert response.status_code == 200, response.text
            contract = response.json()
            assert contract["schema"] == "ax4lab.geometry_input_contract.v1"
            assert contract["provider_version"] == "1.0.0"
            template = contract["request_template"]
            assert (template["quality"], template["resolution"]) == ("final", 128)
            assert normalize_request(template, catalog) == template
            assert {field["key"] for field in contract["parameters"]} == set(template["parameters"])
            assert all(field["default"] == template["parameters"][field["key"]]
                       and field["role"] in {"design", "fixed", "numerical"}
                       for field in contract["parameters"])
            if mode.startswith("network"):
                assert set(template["parameters"]) == {"cell_size_mm", "iso_level"}


def test_contract_identity_and_mode_errors(client):
    base = f"/api/design/modules/{MODULE}/geometries"
    assert client.get(base + "/missing/contract").status_code == 404
    assert client.get("/api/design/modules/missing/geometries/gyroid/contract").status_code == 404
    assert client.get(base + "/gyroid/contract?representation=unknown").status_code == 422
    assert client.get(base + "/gyroid/contract?representation=").status_code == 422


def test_wrong_family_inputs_remain_rejected(client):
    response = client.post("/api/design/validate", json={"request": request(
        "gyroid", representation="network_positive", parameters={"wall_thickness_mm": 1})})
    assert response.status_code == 422


@pytest.mark.parametrize("changes", [{"quality": "preview"}, {"resolution": 95}])
def test_new_public_jobs_reject_preview_and_low_resolution_but_preserve_profiles(client, changes):
    legacy = request(**changes)
    profile = client.post("/api/design/profiles", json={"name": "Old inputs", "request": legacy})
    assert profile.status_code == 201
    assert profile.json()["available"]
    assert client.post("/api/design/validate", json={"request": legacy}).status_code == 200
    response = client.post("/api/design/jobs", json={"request": legacy, "idempotency_key": "denied"})
    assert response.status_code == 422
    assert client.get("/api/design/jobs").json() == {"jobs": []}
