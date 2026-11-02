"""The dedicated adapter must preserve writer bytes and semantic metadata."""
import pytest


@pytest.mark.parametrize("cell", [5., 10.])
@pytest.mark.parametrize("wall", [.6, 1.2])
@pytest.mark.parametrize("caps,angle", [(False, 0.), (True, 27.)])
def test_legacy_adapter_matches_writer_exactly(tmp_path, cell, wall, caps, angle):
    from mcp_tools.tpms_geometry import write_smooth_gyroid_stl
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import generate_geometry
    direct = tmp_path / "old.stl"
    old = write_smooth_gyroid_stl(stl_path=direct, name="geometry", specimen_size_mm=[10.]*3,
        wall_thickness_mm=wall, cell_size_mm=cell, orientation_deg=angle, resolution=48,
        top_cap_enabled=caps, bottom_cap_enabled=caps, skin_thickness_mm=.8)
    receipt = generate_geometry({"module_id": "metamaterial_unit_cell_designer", "geometry_id": "gyroid",
        "provider_version": "1.0.0", "representation": "sheet", "specimen_size_mm": [10]*3,
        "orientation_deg": [0, 0, angle], "resolution": 48, "quality": "final",
        "parameters": {"cell_size_mm": cell, "wall_thickness_mm": wall,
                       "top_cap_enabled": caps, "bottom_cap_enabled": caps, "skin_thickness_mm": .8}},
        tmp_path / "new", identity={}, catalog=DesignCatalog())
    assert receipt["provider_metadata"]["legacy"] == old
    assert (tmp_path / "new" / receipt["artifacts"]["stl"]["basename"]).read_bytes() == direct.read_bytes()
    assert receipt["checks"]["stl_reload"] == "passed"
    assert receipt["ok"]


def test_legacy_adapter_does_not_silently_drop_xy_orientation_or_clamp_dimensions():
    from workspaces.design.catalog import DesignCatalog
    from workspaces.design.engine import normalize_request
    base = {"module_id": "metamaterial_unit_cell_designer", "geometry_id": "gyroid", "provider_version": "1.0.0"}
    for overrides in [{"orientation_deg": [5, 0, 0]}, {"specimen_size_mm": [.5, 10, 10]},
                      {"parameters": {"wall_thickness_mm": 3., "cell_size_mm": 5.}}]:
        with pytest.raises(ValueError):
            normalize_request({**base, **overrides}, DesignCatalog())


def test_tool_adapter_preserves_nested_request_receipt_and_unknown_mass(tmp_path):
    from workspaces.design.tool_adapter import generate_tool
    req = {"module_id": "metamaterial_unit_cell_designer", "geometry_id": "gyroid",
           "provider_version": "1.0.0", "specimen_size_mm": [10]*3, "quality": "final", "resolution": 48}
    result = generate_tool({"geometry_request": req, "output_dir": str(tmp_path / "tool"),
                            "run_id": "r1", "specimen_id": "s1"})
    assert result["ok"]
    assert result["geometry_receipt"]["request"]["geometry_id"] == "gyroid"
    assert result["geometry_receipt"]["identity"] == {"run_id": "r1", "specimen_id": "s1"}
    assert result["estimated_mass_g"] is None
    assert result["geometry_hash"] == result["geometry_receipt"]["request_sha256"]
    assert result["preview_image_path"] == ""
    assert result["geometry_report"]["geometry_receipt"] == result["geometry_receipt"]
    with pytest.raises(ValueError, match="output_dir"):
        generate_tool({"geometry_request": req})


@pytest.mark.parametrize("quality,flag,error", [("final", True, "preview quality"),
    ("preview", "yes", "boolean"), ("preview", True, "CPU pool")])
def test_preview_render_requires_explicit_quality_flag_and_cpu_pool(tmp_path, quality, flag, error):
    from workspaces.design.tool_adapter import generate_tool
    request = {"module_id": "metamaterial_unit_cell_designer", "geometry_id": "simple_cubic",
               "provider_version": "1.0.0", "quality": quality}
    output = tmp_path / "preview"
    with pytest.raises(ValueError, match=error):
        generate_tool({"geometry_request": request, "output_dir": str(output), "render_preview": flag})
    assert not output.exists()
