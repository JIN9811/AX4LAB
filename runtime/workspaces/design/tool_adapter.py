"""Dedicated legacy writer adapter; no old production tool dispatch is changed."""
from utils.source_identity import attest_module_source

attest_module_source(__file__)


def render_generated_preview(output, receipt):
    """CPU-worker-only, actual triangle render; never create a placeholder image."""
    import hashlib
    from pathlib import Path
    from mcp_tools.mock_tools import _try_write_stl_iso_capture_png
    from .engine import canonical_json
    output = Path(output)
    quality = receipt["quality"]
    if (quality not in {"preview", "final"} or receipt.get("ok") is not True
            or receipt.get("request", {}).get("quality") != quality
            or (quality == "final" and receipt.get("final_geometry_valid") is not True)):
        raise ValueError("STL rendering requires a valid geometry receipt")
    stl = output / "geometry.stl"
    if hashlib.sha256(stl.read_bytes()).hexdigest() != receipt["artifacts"]["stl"]["sha256"]:
        raise ValueError("Preview STL does not match generation receipt")
    image = output / "preview.png"
    if not _try_write_stl_iso_capture_png(image, stl_path=stl,
            specimen_id=receipt["identity"].get("specimen_id", ""),
            geometry_type=receipt["request"]["geometry_id"]):
        raise ValueError("Actual STL preview renderer unavailable or failed; no placeholder")
    metadata = {"schema": "ax4lab.geometry_render.v1", "quality": quality, "source_quality": quality,
        "request_sha256": receipt["request_sha256"], "identity": receipt["identity"],
        "source_stl_sha256": receipt["artifacts"]["stl"]["sha256"],
        "image_basename": image.name, "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "renderer": "actual_stl_triangles_isometric_png", "size_px": [760, 420]}
    with (output / "render.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(metadata) + "\n")


def write_legacy_gyroid(request, stl_path):
    from mcp_tools.tpms_geometry import write_smooth_gyroid_stl
    parameters = request["parameters"]
    report = write_smooth_gyroid_stl(
        stl_path=stl_path, name="geometry", specimen_size_mm=request["specimen_size_mm"],
        wall_thickness_mm=parameters["wall_thickness_mm"], cell_size_mm=parameters["cell_size_mm"],
        anisotropy_ratio=parameters["anisotropy_ratio"], orientation_deg=request["orientation_deg"][2],
        defect_seed=1 if request["seed"] is None else request["seed"], defect_ratio=parameters["defect_ratio"],
        skin_thickness_mm=parameters["skin_thickness_mm"], top_cap_enabled=parameters["top_cap_enabled"],
        bottom_cap_enabled=parameters["bottom_cap_enabled"], resolution=request["resolution"])
    if report is None:
        raise ValueError("Legacy Gyroid requires numpy, scikit-image and trimesh; no fallback allowed")
    return {"method": "legacy_gyroid_writer", "legacy": report,
            "thickness_status": "normal_calibrated_target_not_independent_measurement",
            "density_status": "sampled_estimate", "orientation": "legacy_z_field_rotation_before_clipping"}


def generate_tool(payload: dict) -> dict:
    """Internal adapter only: output_dir is a host-owned NEW artifact directory.

    The HTTP API must never expose this path-bearing payload. Task callers retain
    existing archive ownership and supply explicit nested geometry_request data.
    No implicit current_paths() fallback and no fabrication of previews or mass.
    """
    from pathlib import Path
    from .catalog import DesignCatalog
    from .engine import canonical_json, generate_geometry, normalize_request
    if not isinstance(payload, dict) or not payload.get("output_dir"):
        raise ValueError("Trusted caller must provide output_dir")
    catalog = DesignCatalog()
    request = normalize_request(payload.get("geometry_request"), catalog)
    identity = {key: payload[key] for key in ("run_id", "candidate_id", "specimen_id", "experiment_id", "job_id")
                if key in payload}
    output = Path(payload["output_dir"])
    from utils.compute_pool import compute_enabled, compute_sync
    render_preview = payload.get("render_preview", False)
    if type(render_preview) is not bool:
        raise ValueError("render_preview must be boolean")
    if render_preview and not compute_enabled():
        raise ValueError("Preview rendering requires configured CPU pool")
    if compute_enabled():
        record = catalog.resolve(request["module_id"], request["geometry_id"], request["provider_version"])
        receipt = compute_sync("geometry.design_generate", {"request": request, "output_dir": str(output),
            "identity": identity, "source_fingerprint": record["source_fingerprint"],
            "render_preview": render_preview})
    else:
        receipt = generate_geometry(request, output, identity=identity, catalog=catalog)
    render_receipt = None
    image_path = ""
    if render_preview:
        import hashlib
        import json
        render_receipt = json.loads((output / "render.json").read_text())
        image = output / "preview.png"
        if (render_receipt.get("schema") != "ax4lab.geometry_render.v1"
                or render_receipt.get("quality") != receipt["quality"]
                or render_receipt.get("source_quality") != receipt["quality"]
                or render_receipt.get("request_sha256") != receipt["request_sha256"]
                or render_receipt.get("source_stl_sha256") != receipt["artifacts"]["stl"]["sha256"]
                or render_receipt.get("identity") != receipt["identity"]
                or render_receipt.get("image_basename") != image.name
                or render_receipt.get("image_sha256") != hashlib.sha256(image.read_bytes()).hexdigest()):
            raise ValueError("Preview render lineage mismatch")
        image_path = str(image)
    report = {"ok": receipt["ok"], "geometry_type": request["geometry_id"],
              "specimen_size_mm": request["specimen_size_mm"], "geometry_request": request,
              "geometry_receipt": receipt, "volume_mm3": receipt["volume_mm3"],
              "estimated_mass_g": None, "tool_version": "design-geometry-v1"}
    if render_receipt is not None:
        report["render_receipt"] = render_receipt
    report_path = output / "geometry_report.json"
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(report) + "\n")
    log = output / "geometry.log"
    with log.open("x", encoding="utf-8") as stream:
        stream.write("geometry.design_generate completed\nrequest_sha256=" + receipt["request_sha256"] + "\n")
    return {"ok": receipt["ok"], "tool": "geometry.generate_metamaterial_stl",
            "specimen_id": identity.get("specimen_id", ""),
            "stl_path": str(output / receipt["artifacts"]["stl"]["basename"]),
            "metadata_path": str(report_path), "preview_image_path": image_path, "viewer_capture_path": image_path,
            "capture_image_path": image_path, "geometry_report": report, "geometry_receipt": receipt,
            **({"render_receipt": render_receipt, "render_metadata_path": str(output / "render.json")}
               if render_receipt is not None else {}),
            "estimated_volume_mm3": receipt["volume_mm3"], "estimated_mass_g": None,
            "bounding_box_mm": receipt["checks"]["bbox"], "generation_log_path": str(log),
            "geometry_hash": receipt["request_sha256"], "error_message": ""}
