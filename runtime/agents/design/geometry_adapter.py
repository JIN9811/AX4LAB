"""Explicit geometry capability bridge, without manual-job ownership or device authority.

Normalization/receipt verification are cheap main-thread operations. Generation
and mesh/manufacturing inspection remain registered CPU tool operations.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from workspaces.design.catalog import DesignCatalog
from workspaces.design.engine import normalize_request, request_sha256
from workspaces.design.jobs import contained
from workspaces.design.profiles import Store


MAX_CANDIDATES = 8
REQUIRED_FIELDS = ("candidate_id", "specimen_id", "geometry_type", "specimen_size_mm",
    "geometry_request", "material", "printer_profile", "slicer_profile_hint",
    "layer_height_mm", "nozzle_diameter_mm")


def explicit_contract(state):
    contract = (state.run_metadata or {}).get("orchestrator_design_contract") or {}
    return contract if "geometry_request" in contract or "geometry_candidates" in contract else None


def enabled_catalog(ctx, request):
    """Read atomic persisted state; never construct a second job coordinator."""
    paths = getattr(ctx, "paths", None)
    if paths is None:
        raise ValueError("Explicit geometry requires injected runtime paths")
    catalog = DesignCatalog()
    normalized = normalize_request(request, catalog)
    state = Store(paths.memory_root / "design_workspace").data
    enabled = state["modules"].get(normalized["module_id"], {"enabled": True})
    if enabled.get("enabled") is not True:
        raise ValueError("Design geometry module disabled")
    return catalog, normalized


def final_request(value):
    if not isinstance(value, dict):
        raise ValueError("geometry_request must be an object")
    result = deepcopy(value)
    # Preview evidence is never promoted: a separate final generation is required.
    result["quality"] = "final"
    result.setdefault("resolution", 96)
    return result


def validate_constraints(constraints):
    for key in ("max_specimen_size_mm", "utm_fixture_limit_mm"):
        values = constraints.get(key)
        if (not isinstance(values, list) or len(values) != 3 or any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values)):
            raise ValueError("Invalid manufacturing envelope: " + key)
    for key in ("nozzle_diameter_mm", "layer_height_mm", "max_print_time_min", "max_mass_g",
                "minimum_feature_size_mm", "fdm_min_wall_thickness_mm", "min_wall_thickness_mm",
                "fdm_max_bridge_distance_mm", "fdm_max_unsupported_overhang_deg"):
        value = constraints.get(key)
        minimum = .4 if key in {"minimum_feature_size_mm", "fdm_min_wall_thickness_mm", "min_wall_thickness_mm"} else 0
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value <= 0 or value < minimum):
            raise ValueError("Invalid or relaxed manufacturing constraint: " + key)


def prepare(agent, state, ctx):
    contract = explicit_contract(state)
    if not isinstance(contract.get("geometry_request"), dict):
        raise ValueError("Explicit geometry_candidates require geometry_request")
    extra = contract.get("geometry_candidates", [])
    if not isinstance(extra, list) or len(extra) > MAX_CANDIDATES:
        raise ValueError("geometry_candidates must be bounded to 8 requests")
    constraints = deepcopy(agent.DEFAULT_CONSTRAINTS)
    # Do not project stale specs, BO values, or manual profiles into a new family.
    for key in ("cell_size_mm", "wall_thickness_mm", "relative_density", "anisotropy_ratio",
                "orientation_deg", "defect_ratio", "skin_thickness_mm", "top_cap_enabled",
                "bottom_cap_enabled", "top_bottom_cap", "tpms_thickness", "tpms_resolution",
                "preferred_geometry_type"):
        constraints.pop(key, None)
    agreed = contract.get("manufacturing_constraints") or {}
    if not isinstance(agreed, dict):
        raise ValueError("manufacturing_constraints must be an object")
    constraints.update({key: deepcopy(value) for key, value in agreed.items() if key in constraints})
    validate_constraints(constraints)
    objective = agent._objective_contract(state, constraints)
    pool = {}
    for raw in [contract["geometry_request"], *extra]:
        # Validate original quality/schema as well as the explicitly final target.
        enabled_catalog(ctx, raw)
        catalog, request = enabled_catalog(ctx, final_request(raw))
        record = catalog.resolve(request["module_id"], request["geometry_id"], request["provider_version"])
        for actual, maximum, fixture in zip(request["specimen_size_mm"],
                constraints["max_specimen_size_mm"], constraints["utm_fixture_limit_mm"]):
            if actual > min(float(maximum), float(fixture)):
                raise ValueError("Geometry exceeds agreed specimen/fixture envelope")
        fingerprint = request_sha256(request)
        pool[fingerprint] = {"candidate_id": "geometry-" + fingerprint[:16],
            "candidate_fingerprint": fingerprint, "geometry_type": request["geometry_id"],
            "specimen_size_mm": deepcopy(request["specimen_size_mm"]),
            "orientation_deg": deepcopy(request["orientation_deg"]),
            "geometry_request": request, "source_fingerprint": record["source_fingerprint"],
            "geometry_receipt": None, "candidate_status": "validated_request",
            "expected_mass_g": None, "expected_print_time_min": None, "expected_volume_mm3": None}
    if len(pool) > MAX_CANDIDATES:
        raise ValueError("Candidate admission bounded to 8 distinct requests")
    ranked = sorted(pool.values(), key=lambda item: item["candidate_id"])
    return {"geometry_capability": True, "constraints": constraints, "objective": objective,
        "pool": ranked, "ranked": ranked, "valid_pool": ranked, "hard_valid_count": len(ranked),
        "accepted_requests": {item["candidate_id"]: deepcopy(item["geometry_request"]) for item in ranked},
        "prior_summary": agent._prior_results_summary(ctx), "failure_summary": agent._failure_memory_summary(ctx),
        "knowledge_summary": {"entries": [], "source": "none"}, "bo_recommendation": {},
        "strategy": "explicit_geometry_requests", "rejected": [], "repaired_candidates": []}


def evaluate(state, prepared, candidate):
    request = candidate.get("geometry_request")
    reasons = []
    accepted = prepared["accepted_requests"].get(candidate["candidate_id"])
    if accepted is None or request != accepted or request_sha256(request) != candidate.get("candidate_fingerprint"):
        reasons.append("locked geometry_request mismatch or unauthorized candidate")
    return {"schema": "design_evaluation.v1", "candidate_id": candidate["candidate_id"],
        "candidate_fingerprint": candidate.get("candidate_fingerprint"),
        "validity": {"status": "fail" if reasons else "pass", "reasons": reasons,
                     "source": "geometry schema, envelope and locked normalized request"},
        "constraint_margins": [], "locked_parameters": {"geometry_request": deepcopy(accepted)},
        "performance": {"status": "unassessed", "metric": prepared["objective"]["primary_metric"],
            "value": None, "source": None, "reason": "No measured candidate-matched mechanical evidence."},
        "cost": {key: {"value": None, "unit": unit, "status": "unassessed"}
                 for key, unit in (("mass", "g"), ("volume", "mm3"), ("duration", "min"))}}


def identity(state, spec):
    return {"run_id": state.run_id, "experiment_id": state.experiment_id,
            "candidate_id": spec["candidate_id"], "specimen_id": spec["specimen_id"]}


def output_payload(state, ctx, spec, category):
    from utils.agent_artifact_archive import _safe
    ids = identity(state, spec)
    for value in ids.values():
        _safe(value)
    root = Path(ctx.paths.run_root)
    output = contained(root, root / state.run_id / category / spec["specimen_id"] / ("final-" + uuid4().hex))
    return {**ids, "geometry_request": deepcopy(spec["geometry_request"]), "output_dir": str(output)}


def verified_geometry(state, ctx, spec, catalog):
    """Fail closed on every mismatch; caller may regenerate the SAME request."""
    try:
        request = normalize_request(spec["geometry_request"], catalog)
        result, receipt = spec["geometry_result"], spec["geometry_receipt"]
        record = catalog.resolve(request["module_id"], request["geometry_id"], request["provider_version"])
        if (request["quality"] != "final" or receipt.get("schema") != "ax4lab.geometry_receipt.v1"
                or receipt.get("ok") is not True or receipt.get("quality") != "final"
                or receipt.get("final_geometry_valid") is not True
                or receipt.get("identity") != identity(state, spec)
                or receipt.get("request") != request or receipt.get("request_sha256") != request_sha256(request)
                or receipt.get("source_fingerprint") != record["source_fingerprint"]
                or receipt.get("source_files") != record["source_files"] or result.get("ok") is not True
                or result.get("geometry_receipt") != receipt):
            return None
        checks = receipt["checks"]
        if (checks.get("ok") is not True or checks.get("watertight") is not True
                or checks.get("within_envelope") is not True or checks.get("component_count") != 1
                or checks.get("reject_reasons") or checks.get("stl_reload") != "passed"
                or checks.get("normals_finite_unit") is not True
                or checks.get("provider_validation", {}).get("ok") is not True):
            return None
        root = Path(ctx.paths.run_root) / state.run_id
        file = contained(root, Path(result["stl_path"]))
        artifact = receipt["artifacts"]["stl"]
        if (file.name != "geometry.stl" or artifact["basename"] != file.name
                or file.stat().st_size != artifact["size_bytes"]
                or hashlib.sha256(file.read_bytes()).hexdigest() != artifact["sha256"]
                or json.loads(contained(root, file.with_name("receipt.json")).read_text()) != receipt):
            return None
        return deepcopy(result)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def finalize_steps(agent, state, ctx, prepared, candidate, decision):
    from utils.compute_pool import compute_enabled
    if not compute_enabled():
        raise ValueError("Explicit geometry requires configured CPU pool")
    selected = deepcopy(candidate)
    evaluation = evaluate(state, prepared, selected)
    if evaluation["validity"]["status"] != "pass":
        raise ValueError("Selected geometry does not match locked request")
    catalog, request = enabled_catalog(ctx, selected["geometry_request"])
    record = catalog.resolve(request["module_id"], request["geometry_id"], request["provider_version"])
    if record["source_fingerprint"] != selected["source_fingerprint"]:
        raise ValueError("Geometry source changed after candidate admission")
    constraints = prepared["constraints"]
    selected.update(specimen_id="specimen-" + selected["candidate_fingerprint"][:16],
        material=constraints["material"], printer_profile=agent._printer_profile(constraints),
        slicer_profile_hint=agent._slicer_profile_hint(constraints),
        layer_height_mm=constraints["layer_height_mm"], nozzle_diameter_mm=constraints["nozzle_diameter_mm"],
        constraints=deepcopy(constraints), objective_type=prepared["objective"]["objective_type"],
        objective_direction=prepared["objective"]["direction"], generation_strategy="explicit_geometry_requests",
        score_semantics="unassessed_no_mechanical_proxy", design_evaluation=evaluation)
    generated = yield ("geometry.generate_metamaterial_stl", output_payload(state, ctx, selected, "design_geometry"))
    selected.update(geometry_result=generated, geometry_receipt=generated.get("geometry_receipt"))
    if verified_geometry(state, ctx, selected, catalog) is None:
        raise ValueError("Final geometry tool returned invalid receipt/artifact")
    selected["candidate_status"] = "selected"
    selected["expected_volume_mm3"] = selected["geometry_receipt"]["volume_mm3"]
    evaluation["cost"]["volume"].update(value=selected["expected_volume_mm3"], status="serialized_mesh")
    ledger = [deepcopy(selected if c["candidate_id"] == selected["candidate_id"] else c) for c in prepared["ranked"]]
    report = {"schema": "design_report.v1", "run_id": state.run_id,
        "report_id": f"design-report-{state.run_id}-{state.loop_count + 1}", "loop_index": state.loop_count + 1,
        "status": "selected", "evaluation_semantics": "evidence_based_v1", "objective": prepared["objective"],
        "candidate_generation": {"strategy": prepared["strategy"], "candidate_count": len(ledger),
            "valid_count": len(ledger), "rejected_count": 0, "repaired_count": 0,
            "candidate_ledger": ledger, "top_candidates": ledger, "preview_status": "not_generated"},
        "candidate_evaluation": evaluation, "design_evaluation": evaluation,
        "geometry_request": deepcopy(request), "geometry_receipt": deepcopy(selected["geometry_receipt"]),
        "manufacturability": {"status": "unassessed", "fdm_constraints_checked": False,
            "expected_mass_g": None, "expected_print_time_min": None},
        "decision_register": [{"decision": "selected_explicit_geometry", "candidate_id": selected["candidate_id"],
            "rationale": decision["reason"] if decision else "Deterministic test selection by stable candidate ID."}],
        "handoff_to_specimen": {"required_fields_present": all(selected.get(k) is not None for k in REQUIRED_FIELDS),
            "required_fields": list(REQUIRED_FIELDS), "missing_required_fields": [],
            "known_risks": ["Final geometry is not printability evidence; Specimen manufacturing checks remain required."]}}
    if decision is not None:
        report["design_decision"] = deepcopy(decision)
    packet = agent._design_handoff_packet(state=state, selected=selected, design_report=report)
    result = {"experiment_spec": selected, "design_report": report,
        "design_agent_report": {**deepcopy(report), "schema": "design_agent_report.v1"},
        "design_candidate": packet, "handoff_packet": packet, "candidate_ledger": ledger,
        "decisions": report["decision_register"], "metrics": evaluation}
    if decision is not None:
        result["design_decision"] = decision
    return result


def specimen_geometry_steps(state, ctx, spec):
    from utils.compute_pool import compute_enabled
    if not compute_enabled():
        raise ValueError("Explicit geometry requires configured CPU pool")
    validate_constraints(spec.get("constraints") or {})
    catalog, request = enabled_catalog(ctx, spec["geometry_request"])
    if request["quality"] != "final":
        raise ValueError("Specimen requires a final normalized geometry_request")
    if (request_sha256(request) != spec.get("candidate_fingerprint")
            or request["geometry_id"] != spec.get("geometry_type")
            or request["specimen_size_mm"] != spec.get("specimen_size_mm")):
        raise ValueError("Specimen geometry identity/fingerprint differs from locked request")
    spec["geometry_request"] = request
    payload = output_payload(state, ctx, spec, "specimens")
    geometry = verified_geometry(state, ctx, spec, catalog)
    if geometry is None:
        geometry = yield ("geometry.generate_metamaterial_stl", payload)
        spec.update(geometry_result=geometry, geometry_receipt=geometry.get("geometry_receipt"))
        if verified_geometry(state, ctx, spec, catalog) is None:
            raise ValueError("Regenerated geometry failed receipt verification")
    mesh = yield ("geometry.check_mesh_quality", {"stl_path": geometry["stl_path"],
        "geometry_request": request, "constraints": spec.get("constraints", {})})
    if mesh.get("ok") is not True or mesh.get("mesh_status") != "pass":
        raise RuntimeError("geometry.check_mesh_quality failed: " + str(mesh.get("reject_reasons")))
    manufacturing = yield ("geometry.check_manufacturability", {"stl_path": geometry["stl_path"],
        "geometry_request": request, "geometry_receipt": spec["geometry_receipt"],
        "mesh_report": mesh["mesh_report"], "constraints": spec.get("constraints", {}),
        "printer_profile": spec["printer_profile"], "material": spec["material"]})
    return payload, geometry, mesh, manufacturing


def blocked_specimen_result(state, spec, geometry, mesh, manufacturing):
    from agents.base_agent import AgentResult
    report = {"schema": "fabrication_report.v1", "run_id": state.run_id,
        "digital_thread": {**identity(state, spec), "geometry_request": deepcopy(spec["geometry_request"]),
            "geometry_receipt": deepcopy(spec["geometry_receipt"]), "stl_path": geometry["stl_path"],
            "geometry_hash": geometry["geometry_hash"]},
        "process_plan": {"estimated_mass_g": None, "estimated_print_time_min": None},
        "quality_gates": [
            {"gate": "geometry", "status": "pass", "evidence": spec["geometry_receipt"]},
            {"gate": "mesh", "status": "pass", "evidence": mesh},
            {"gate": "manufacturability", "status": manufacturing["manufacturability_status"], "evidence": manufacturing},
            {"gate": "slicer", "status": "not_run", "evidence": {}}],
        "fabrication_outcome": {"status": "blocked", "actuation_performed": False},
        "feedback_to_design": {"reject_reasons": manufacturing.get("reject_reasons", [])}}
    return AgentResult(success=False, summary="Manufacturing evidence requires review",
        data={"failure_code": "MANUFACTURABILITY_REJECTED", "fabrication_report": report,
            "specimen_result": {"ok": False, "status": "blocked", **identity(state, spec),
                "geometry_request": spec["geometry_request"], "geometry_receipt": spec["geometry_receipt"],
                "geometry_result": geometry, "mesh_result": mesh, "manufacturability": manufacturing,
                "fabrication_report": report}})


def check_manufacturing(payload):
    """CPU-worker check boundary: geometry evidence never certifies printing.

    Gyroid sheet retains its existing manufacturing rules. Other providers have
    no verified overhang/bridge/fixture policy yet and report pending evidence,
    alongside the same actual-STL wall inspection (not nominal strut diameter).
    """
    from mcp_tools.wall_thickness import inspect_wall_thickness
    request = normalize_request(payload["geometry_request"], DesignCatalog())
    constraints = deepcopy(payload.get("constraints") or {})
    receipt = payload.get("geometry_receipt") or {}
    if request["geometry_id"] == "gyroid" and request["representation"] == "sheet":
        from mcp_tools.mock_tools import _check_manufacturability
        constraints.update(request["parameters"], geometry_type="gyroid",
            relative_density=receipt.get("volume_fraction"), _geometry_unsliced=True)
        return _check_manufacturability({key: value for key, value in
            {**payload, "constraints": constraints}.items() if key != "geometry_request"})
    required_wall = max(float(constraints.get(key, .4)) for key in
                        ("minimum_feature_size_mm", "min_wall_thickness_mm", "fdm_min_wall_thickness_mm"))
    wall = inspect_wall_thickness(payload["stl_path"], required_wall)
    reasons = ["family_manufacturing_evidence_unavailable"]
    if not payload.get("mesh_report", {}).get("ok"):
        reasons.append("mesh_checks_failed")
    if wall.get("status") != "pass":
        reasons.append("generated_mesh_minimum_wall_" + str(wall.get("status")))
    return {"ok": False, "tool": "geometry.check_manufacturability",
        "manufacturability_status": "review_required", "reject_reasons": reasons,
        "expected_mass_g": None, "expected_print_time_min": None,
        "wall_thickness_verification": wall, "minimum_feature_size_mm": required_wall,
        "overhang_risk": "unassessed", "unsupported_island_risk": "unassessed",
        "compression_fixture_status": "unassessed", "warnings": [
            "Provider numerical calibration and final receipt are not physical printability evidence."]}
