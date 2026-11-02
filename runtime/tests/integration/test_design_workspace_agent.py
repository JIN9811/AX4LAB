"""Real registered Design graph and geometry-only Specimen boundary; no devices."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.base_agent import AgentContext
from agents.design.agent import DesignAgent
from agents.design.module import DESIGN_MODULE
from agents.specimen.agent import SpecimenMakingAgent
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from utils import compute_pool
from utils.runtime_paths import RuntimePaths


MODULE = "metamaterial_unit_cell_designer"
ALLOWED = {"geometry.generate_metamaterial_stl", "geometry.check_mesh_quality",
           "geometry.check_manufacturability"}


class GeometryOnlyRegistry(ToolRegistry):
    def __init__(self):
        super().__init__()
        self.calls = []
        register_mock_tools(self)

    def call(self, name, payload=None):
        assert name in ALLOWED, f"Hardware/slicing denied BEFORE dispatch: {name}"
        self.calls.append((name, deepcopy(payload)))
        return super().call(name, payload)


@pytest.fixture
def context(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    paths = RuntimePaths(repository_root=repo, runtime_root=repo / "runtime",
        system_root=repo / "system", workspace_root=repo / "workspaces",
        **{key: tmp_path / key for key in ("run_root", "memory_root", "artifact_root",
           "output_root", "source_inbox_root", "user_file_root", "log_root")})
    memory = SimpleNamespace(list_recent=lambda _: [], recent=lambda **_: [])
    ctx = AgentContext(None, None, None, None, memory, memory, GeometryOnlyRegistry(),
                       force_real_llm_in_test=False, paths=paths,
                       artifact_run_root=str(paths.run_root))
    assert not compute_pool.compute_enabled()
    compute_pool.configure_compute_pool(1)
    yield ctx
    compute_pool.close_compute_pool()


def request(geometry="simple_cubic", **changes):
    return {"module_id": MODULE, "geometry_id": geometry, "provider_version": "1.0.0",
            "quality": "final", "resolution": 96, **changes}


def state_for(value, **contract):
    return OrchestratorState(run_id="geometry-run", experiment_id="geometry-exp",
        mode=Mode.TEST, stage=Stage.DESIGN, active_goal="Compare geometry without performance claims",
        run_metadata={"orchestrator_design_contract": {"geometry_request": value, **contract}})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [request("schwarz_p"), request("spinodoid", seed=42), request()])
async def test_registered_graph_final_stl_and_specimen_reuse(context, value):
    state = state_for(value)
    original = deepcopy(state.run_metadata)
    result = await DESIGN_MODULE.factory().run(state, context)
    assert result.success
    spec = result.data["experiment_spec"]
    assert spec["geometry_request"]["geometry_id"] == value["geometry_id"]
    assert state.run_metadata["orchestrator_design_contract"] == original["orchestrator_design_contract"]
    receipt = spec["geometry_receipt"]
    stl = Path(spec["geometry_result"]["stl_path"])
    assert receipt["quality"] == "final" and receipt["final_geometry_valid"]
    assert receipt["checks"]["within_envelope"] and receipt["checks"]["watertight"]
    assert receipt["manufacturing_ready"] is False
    assert hashlib.sha256(stl.read_bytes()).hexdigest() == receipt["artifacts"]["stl"]["sha256"]
    assert spec["expected_mass_g"] is None and spec["expected_print_time_min"] is None
    assert "expected_objective_proxy_score" not in spec
    assert "wall_thickness_mm" not in spec and "relative_density" not in spec
    assert spec["design_evaluation"]["performance"]["value"] is None
    assert result.data["handoff_packet"]["status"] == "ready"
    assert result.data["design_report"]["manufacturability"]["status"] == "unassessed"
    assert list(context.paths.run_root.rglob("receipt.json"))
    state.current_experiment_spec = deepcopy(spec)
    state.stage = Stage.SPECIMEN
    before = len(context.tools.calls)
    prepared = await SpecimenMakingAgent().run(state, context)
    assert [name for name, _ in context.tools.calls[before:]] == [
        "geometry.check_mesh_quality", "geometry.check_manufacturability"]
    assert prepared.success is False
    assert prepared.data["failure_code"] == "MANUFACTURABILITY_REJECTED"
    assert prepared.data["specimen_result"]["manufacturability"]["manufacturability_status"] == "review_required"
    report = prepared.data["fabrication_report"]
    assert report["digital_thread"]["geometry_receipt"] == receipt
    assert report["process_plan"]["estimated_mass_g"] is None
    assert next(g for g in report["quality_gates"] if g["gate"] == "manufacturability")["status"] == "review_required"
    assert state.current_experiment_spec["geometry_request"] == spec["geometry_request"]


def test_candidate_admission_is_bounded_detached_stable_and_not_bo(context):
    value = request("spinodoid", seed=42)
    other = request()
    state = state_for(value, geometry_candidates=[other, value])
    state.run_metadata["bo_recommended_constraints"] = {"cell_size_mm": 999, "wall_thickness_mm": 999}
    prepared = DesignAgent()._prepare_design_payload(state, context)
    assert len(prepared["ranked"]) == 2
    assert [c["candidate_id"] for c in prepared["ranked"]] == sorted(c["candidate_id"] for c in prepared["ranked"])
    assert all("geometry_request" in c for c in prepared["ranked"])
    prepared["ranked"][0]["geometry_request"]["parameters"].clear()
    assert state.run_metadata["orchestrator_design_contract"]["geometry_request"] == value
    with pytest.raises(ValueError, match="bounded|8"):
        DesignAgent()._prepare_design_payload(state_for(value, geometry_candidates=[value] * 9), context)


def test_known_invalid_alternative_is_not_authorized_and_geometry_is_pending(context):
    from agents.design.decision import candidate_evaluation
    invalid = request(parameters={"cell_size_mm":10, "strut_diameter_mm":6})
    agent, state = DesignAgent(), state_for(request(), geometry_candidates=[invalid])
    prepared = agent._prepare_design_payload(state, context)
    assert len(prepared["ranked"]) == 1
    assert len(prepared["rejected"]) == 1
    assert "half cell" in prepared["rejected"][0]["reject_reasons"][0]
    assert prepared["valid_pool"] == [] and prepared["hard_valid_count"] == 0
    evaluation = candidate_evaluation(agent, state, prepared, prepared["ranked"][0])
    assert evaluation["validity"]["status"] == "pending"
    assert evaluation["request_preflight"]["status"] == "pass"
    assert "serialized" in evaluation["validity"]["reasons"][0]


@pytest.mark.asyncio
async def test_invalid_alternative_never_appears_valid_in_decision_or_breaks_handoff(context, monkeypatch):
    state = state_for(request(), geometry_candidates=[request(parameters={"cell_size_mm":10, "strut_diameter_mm":6})])
    contexts = []
    async def complete(self, task_type, prompt, **kwargs):
        body = json.loads(prompt.split("\n", 1)[1])["context"]
        contexts.append(body)
        cid = body["candidates"][0]["candidate_id"]
        return SimpleNamespace(text=json.dumps({"tool":"accept_candidate", "arguments":{"candidate_id":cid},
            "reason":"Conditional choice, pending final serialized geometry checks", "evidence_refs":["candidate:"+cid]}),
            model="deterministic-decision-fixture", raw={})
    monkeypatch.setattr(AgentContext, "complete", complete)
    context.force_real_llm_in_test = True
    result = await DesignAgent().run(state, context)
    assert result.success
    assert len(contexts[0]["candidates"]) == 1
    assert contexts[0]["candidates"][0]["evaluation"]["validity"]["status"] == "pending"
    assert contexts[0]["rejected_requests"][0]["reject_reasons"]
    descriptor = contexts[0]["geometry_catalog"][0]
    assert descriptor["agent_handoff"] is True
    assert descriptor["fields"] and descriptor["defaults"]
    assert len(contexts[0]["geometry_catalog"]) == 1  # bounded to explicit candidates
    assert result.data["experiment_spec"]["design_evaluation"]["validity"]["status"] == "pass"
    assert result.data["design_report"]["candidate_generation"]["rejected_count"] == 1
    assert all(p["geometry_request"]["parameters"]["strut_diameter_mm"] != 6 for _, p in context.tools.calls)


@pytest.mark.parametrize("value", [request("unknown"), request("spinodoid"),
    request(parameters={"strut_diameter_mm": -1}), request(provider_version="99.0")])
def test_invalid_explicit_requests_never_fallback(context, value):
    with pytest.raises(ValueError):
        DesignAgent()._prepare_design_payload(state_for(value), context)
    assert context.tools.calls == []


def test_disabled_state_is_read_only_and_does_not_interrupt_jobs(context):
    from workspaces.design.profiles import Store
    store = Store(context.paths.memory_root / "design_workspace")
    store.data["modules"][MODULE] = {"enabled": False, "revision": 2}
    store.data["jobs"]["active"] = {"state": "running"}
    store.save(store.data)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="disabled"):
        DesignAgent()._prepare_design_payload(state_for(request()), context)
    assert store.path.read_bytes() == before
    assert context.tools.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["identity", "hash", "preview", "source", "checks", "file", "receipt_file"])
async def test_bad_receipt_regenerates_same_request_seed_and_rechecks(context, damage):
    state = state_for(request("spinodoid", seed=42))
    result = await DesignAgent().run(state, context)
    spec = deepcopy(result.data["experiment_spec"])
    receipt = spec["geometry_receipt"]
    if damage == "identity": receipt["identity"]["run_id"] = "other"
    elif damage == "hash": receipt["request_sha256"] = "0" * 64
    elif damage == "preview": receipt["quality"] = "preview"
    elif damage == "source": receipt["source_fingerprint"] = "0" * 64
    elif damage == "checks": receipt["checks"]["ok"] = False
    elif damage == "file": Path(spec["geometry_result"]["stl_path"]).write_bytes(b"corrupt")
    else: Path(spec["geometry_result"]["stl_path"]).with_name("receipt.json").unlink()
    state.current_experiment_spec = spec
    before = len(context.tools.calls)
    prepared = await SpecimenMakingAgent()._prepare_fabrication_async(state, context)
    calls = context.tools.calls[before:]
    assert [name for name, _ in calls] == ["geometry.generate_metamaterial_stl",
        "geometry.check_mesh_quality", "geometry.check_manufacturability"]
    assert calls[0][1]["geometry_request"] == spec["geometry_request"]
    assert calls[0][1]["geometry_request"]["seed"] == 42
    assert prepared.success is False
    repaired = state.current_experiment_spec
    assert repaired["geometry_receipt"] == prepared.data["fabrication_report"]["digital_thread"]["geometry_receipt"]
    assert repaired["geometry_result"] == prepared.data["specimen_result"]["geometry_result"]
    retry_start = len(context.tools.calls)
    retry = await SpecimenMakingAgent()._prepare_fabrication_async(state, context)
    assert [name for name, _ in context.tools.calls[retry_start:]] == [
        "geometry.check_mesh_quality", "geometry.check_manufacturability"]
    assert retry.data["specimen_result"]["geometry_receipt"] == repaired["geometry_receipt"]


def test_nested_request_fingerprint_and_lock_include_seed_and_family(context):
    from agents.design.decision import candidate_evaluation
    agent, state = DesignAgent(), state_for(request("spinodoid", seed=42))
    prepared = agent._prepare_design_payload(state, context)
    candidate = deepcopy(prepared["ranked"][0])
    before = agent._candidate_fingerprint(candidate)
    candidate["geometry_request"]["seed"] = 43
    assert agent._candidate_fingerprint(candidate) != before
    assert candidate_evaluation(agent, state, prepared, candidate)["validity"]["status"] == "fail"


@pytest.mark.asyncio
async def test_existing_llm_authority_sees_nested_request_and_can_select_nonfirst(context, monkeypatch):
    state = state_for(request(), geometry_candidates=[request("spinodoid", seed=42)])
    prepared = DesignAgent()._prepare_design_payload(state, context)
    chosen = prepared["ranked"][-1]
    prompts, responses = [], iter(["inspect_candidate", "accept_candidate"])
    async def complete(self, task_type, prompt, **kwargs):
        prompts.append(prompt)
        return SimpleNamespace(text=json.dumps({"tool": next(responses),
            "arguments": {"candidate_id": chosen["candidate_id"]}, "reason": "Inspect locked geometry inputs",
            "evidence_refs": ["candidate:" + chosen["candidate_id"]]}), model="deterministic-decision-fixture", raw={})
    monkeypatch.setattr(AgentContext, "complete", complete)
    context.force_real_llm_in_test = True
    result = await DesignAgent().run(state, context)
    assert result.success
    assert result.data["experiment_spec"]["geometry_request"] == chosen["geometry_request"]
    assert len(prompts) == 2 and "geometry_request" in prompts[0]
    assert "expected_objective_proxy_score" not in "".join(prompts)
    assert result.data["design_decision"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_no_pool_never_runs_explicit_geometry_inline(context):
    compute_pool.close_compute_pool()
    with pytest.raises(ValueError, match="CPU pool"):
        await DesignAgent().run(state_for(request()), context)
    assert context.tools.calls == []


@pytest.mark.asyncio
async def test_final_provider_error_has_no_fallback_or_ready_receipt(context):
    with pytest.raises((ValueError, compute_pool.ComputeError), match="resolution|sampling|wall|provider|voxel"):
        await DesignAgent().run(state_for(request("schwarz_p", resolution=16)), context)
    assert len(context.tools.calls) == 0  # Known sampling failure is rejected in shared preflight.
    assert not list(context.paths.run_root.rglob("receipt.json"))


@pytest.mark.asyncio
async def test_specimen_rejects_mutated_authoritative_request_without_generating(context):
    state = state_for(request("spinodoid", seed=42))
    result = await DesignAgent().run(state, context)
    state.current_experiment_spec = deepcopy(result.data["experiment_spec"])
    state.current_experiment_spec["geometry_request"]["seed"] = 43
    before = len(context.tools.calls)
    with pytest.raises(ValueError, match="identity|fingerprint|locked"):
        await SpecimenMakingAgent()._prepare_fabrication_async(state, context)
    assert len(context.tools.calls) == before


@pytest.mark.asyncio
async def test_explicit_gyroid_sheet_keeps_existing_manufacturing_checks(context):
    state = state_for(request("gyroid"))
    result = await DesignAgent().run(state, context)
    spec = deepcopy(result.data["experiment_spec"])
    state.current_experiment_spec = spec
    steps = SpecimenMakingAgent()._prepare_fabrication_steps(state, context)
    sent, manufacturing = None, None
    try:
        while True:
            try:
                name, payload = steps.send(sent)
            except StopIteration as done:
                assert done.value.data["failure_code"] == "MANUFACTURABILITY_REJECTED"
                break
            if name not in ALLOWED:
                # Observe, never dispatch the handoff/slicer/hardware boundary.
                assert name == "artifact.create_specimen_handoff"
                assert manufacturing["manufacturability_status"] == "pass"
                break
            sent = context.tools.call(name, payload)
            if name == "geometry.check_manufacturability":
                manufacturing = sent
    finally:
        steps.close()
    assert manufacturing is not None
    assert "family_manufacturing_evidence_unavailable" not in manufacturing["reject_reasons"]
    assert manufacturing["expected_mass_g"] is None and manufacturing["expected_print_time_min"] is None
    assert manufacturing["wall_thickness_verification"]["stl_sha256"] == spec["geometry_receipt"]["artifacts"]["stl"]["sha256"]
    assert state.current_experiment_spec["geometry_request"] == spec["geometry_request"]


def test_geometry_only_guard_denies_before_dispatch(context):
    with pytest.raises(AssertionError, match="BEFORE dispatch"):
        context.tools.call("printer.prepare", {})
    assert context.tools.calls == []


@pytest.mark.parametrize("constraints", [
    {"fdm_min_wall_thickness_mm": .1}, {"min_wall_thickness_mm": .1},
    {"max_specimen_size_mm": [30]}, {"max_specimen_size_mm": [float("nan"), 30, 30]},
    {"nozzle_diameter_mm": 0}])
def test_explicit_family_cannot_relax_or_malformed_manufacturing_constraints(context, constraints):
    with pytest.raises(ValueError):
        DesignAgent()._prepare_design_payload(state_for(request(), manufacturing_constraints=constraints), context)
    assert context.tools.calls == []


def test_preview_request_final_target_and_profile_changes_are_isolated(context):
    from workspaces.design.profiles import Store
    raw = request("spinodoid", seed=42, quality="preview")
    raw.pop("resolution")
    state = state_for(raw)
    prepared = DesignAgent()._prepare_design_payload(state, context)
    frozen = deepcopy(prepared["ranked"])
    store = Store(context.paths.memory_root / "design_workspace")
    store.data["profiles"]["manual"] = {"request": request("bcc"), "revision": 8}
    store.save(store.data)
    assert prepared["ranked"] == frozen
    assert prepared["ranked"][0]["geometry_request"]["quality"] == "final"
    assert prepared["ranked"][0]["geometry_request"]["resolution"] == 96
    assert state.run_metadata["orchestrator_design_contract"]["geometry_request"] == raw


@pytest.mark.asyncio
async def test_shared_engine_candidate_previews_are_distinct_and_archived(context, monkeypatch):
    from PIL import Image
    import mcp_tools.mock_tools as numerical_tools
    def no_parent_render(*args, **kwargs):
        pytest.fail("Preview rendering must execute in the CPU subprocess, not the graph thread")
    monkeypatch.setattr(numerical_tools, "_try_write_stl_iso_capture_png", no_parent_render)
    state = state_for(request(), geometry_candidates=[request("spinodoid", seed=42)])
    result = await DesignAgent().run(state, context)
    spec = result.data["experiment_spec"]
    ledger = result.data["candidate_ledger"]
    assert result.data["design_report"]["candidate_generation"]["preview_status"] == "generated"
    assert len(ledger) == 2
    for candidate in ledger:
        preview = candidate["geometry_preview"]
        receipt = preview["geometry_receipt"]
        assert receipt["quality"] == "preview" and receipt["final_geometry_valid"] is False
        assert receipt["request"] == {**candidate["geometry_request"], "quality": "preview"}
        assert receipt["request_sha256"] != candidate["candidate_fingerprint"]
        assert Path(preview["stl_path"]) != Path(spec["geometry_result"]["stl_path"])
        assert hashlib.sha256(Path(preview["stl_path"]).read_bytes()).hexdigest() == receipt["artifacts"]["stl"]["sha256"]
        png = Path(candidate["preview_image_path"])
        assert png.is_relative_to(context.paths.run_root / state.run_id)
        assert preview["render_receipt"]["source_stl_sha256"] == receipt["artifacts"]["stl"]["sha256"]
        assert preview["render_receipt"]["request_sha256"] == receipt["request_sha256"]
        assert hashlib.sha256(png.read_bytes()).hexdigest() == preview["render_receipt"]["image_sha256"]
        with Image.open(png) as image:
            assert image.format == "PNG" and image.size == (760, 420)
            assert len(image.convert("RGB").getcolors(760 * 420)) > 10
        assert candidate["preview_image_url"].startswith("/api/runs/geometry-run/artifact-file/")
    assert spec["geometry_preview"]["geometry_receipt"]["identity"] == spec["geometry_receipt"]["identity"]
    assert spec["geometry_receipt"]["quality"] == "final"
    archives = list(context.paths.run_root.rglob("manifest.json"))
    assert archives and any("preview.png" in path.read_text() for path in archives)
    assert [payload["geometry_request"]["quality"] for name, payload in context.tools.calls] == ["final", "preview", "preview"]
    assert compute_pool.compute_status()["completed"] == 3


@pytest.mark.asyncio
async def test_explicit_gyroid_existing_report_projection_retains_geometry_lineage(context):
    from agents.specimen.presentation import project_specimen_report
    state = state_for(request("gyroid", specimen_size_mm=[10, 10, 10], resolution=48))
    result = await DesignAgent().run(state, context)
    spec = result.data["experiment_spec"]
    report = SpecimenMakingAgent()._build_fabrication_report(
        state=state, spec=spec, candidate=spec["candidate_id"], specimen_id=spec["specimen_id"],
        geometry_result=spec["geometry_result"], mesh_result={"ok": True, "mesh_status": "pass"},
        manufacturability_result={"ok": True, "manufacturability_status": "pass"},
        handoff_result={}, experiment_response={}, printer_response={}, printer_payload={},
        protocol_note="Read-only report projection; no manufacturing execution", live_gui_test_spec=False,
        printer_test_path="", top_cap_enabled=False, bottom_cap_enabled=False, geometry_payload={})
    view = project_specimen_report({}, {"fabrication_report": report})
    assert view["role_specific"]["digital_thread"]["geometry_request"] == spec["geometry_request"]
    assert view["role_specific"]["digital_thread"]["geometry_receipt"] == spec["geometry_receipt"]
    gate = next(g for g in view["role_specific"]["quality_gates"] if g["gate"] == "geometry")
    assert gate["evidence"]["geometry_receipt"] == spec["geometry_receipt"]
    assert gate["evidence"]["geometry_request"] == spec["geometry_request"]
    assert all(name == "geometry.generate_metamaterial_stl" for name, _ in context.tools.calls)
