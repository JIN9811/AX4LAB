"""Real bounded loop and worker; only model HTTP and desktop are synthetic."""
import asyncio
import importlib
import inspect
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backends.vllm_client import VLLMBackend
from tests.unit.test_equipment_computer_use_worker import Desktop, policy
from Pyautogui_server_for_window.bridge.computer_use_runtime import ComputerUseController


def runner():
    path = Path(__file__).parents[2] / "agents/equipment/computer_use.py"
    assert path.exists(), "bounded computer-use runner is missing"
    return importlib.import_module("agents.equipment.computer_use")


def harness(tmp_path, monkeypatch, decisions=None):
    desktop = Desktop()
    worker = ComputerUseController(tmp_path / "worker", desktop, "worker1")
    backend = VLLMBackend()
    backend._endpoint_routes = {"selected": {"id": "selected", "model": "synthetic", "base_url": "http://model.invalid/v1",
        "access_token": "endpoint-secret", "capabilities": {"vision": True}, "management_id": "must-not-start"}}
    calls, prompts, urls = [], [], []
    decisions = list(decisions or ["complete"])
    ctx = SimpleNamespace(active_backend="vllm", primary_backend=backend, primary_backends={"vllm": backend},
        model_routers={"vllm": SimpleNamespace(select=lambda _: SimpleNamespace(primary="endpoint:selected"))},
        paths=SimpleNamespace(artifact_root=tmp_path / "artifacts"), llm_lease=None)
    async def notify(**kwargs):
        pass
    ctx._notify_model_call = notify
    state = SimpleNamespace(run_id="run1", loop_count=1, current_experiment_spec={"specimen_id": "spec1", "equipment_profile_id": "profile1"})
    execution = {"execution_id": "exec1", "sequence_id": "sequence1", "target_profile": "profile1", "model_snapshot": {"provider": "vllm", "model": "endpoint:selected"}}
    package = {"manifest": {"skill_id": "computer_use_demo_v1", "workflow_sha256": "f" * 64, "program_sha256": {}}, "workflow": {"computer_use": policy()}}
    request = {"bridge_id": "worker1", "confirm_live_execute": True}
    settings = {"execution_mode": "computer_use"}
    async def call_tool(name, payload):
        operation = name.rsplit("_", 1)[-1]
        calls.append((operation, deepcopy(payload)))
        return worker.handle(operation, payload, "principal")
    async def respond(req):
        payload = json.loads(req.content)
        content = payload["messages"][-1]["content"]
        prompt, _ = json.JSONDecoder().raw_decode(content[0]["text"])
        prompts.append((payload, prompt))
        urls.append(str(req.url))
        chosen = decisions.pop(0) if decisions else "complete"
        if callable(chosen):
            chosen = chosen(prompt)
        if inspect.isawaitable(chosen):
            chosen = await chosen
        if isinstance(chosen, httpx.Response):
            return chosen
        if isinstance(chosen, str) and chosen in {"act", "complete", "needs_operator", "wait"}:
            decision = {"schema": "ax4lab.equipment_computer_use.decision.v1", "observation_id": prompt["observation"]["observation_id"], "kind": chosen, "reason": "synthetic"}
            if chosen == "act":
                decision["action"] = {"type": "click", "target_id": "button", "x": 2, "y": 3}
            if chosen == "wait":
                decision["seconds"] = 0
            chosen = json.dumps(decision)
        return httpx.Response(200, json={"choices": [{"message": {"content": chosen}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    args = dict(state=state, ctx=ctx, request=request, package=package, execution=execution, settings=settings, call_tool=call_tool)
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["rejected", "exception"])
async def test_verified_execution_requires_confirmed_release(tmp_path, monkeypatch, failure):
    h = harness(tmp_path, monkeypatch)
    releases = []
    async def release_failure(name, payload):
        if name.endswith("_release"):
            releases.append(payload)
            if failure == "exception":
                raise RuntimeError("endpoint-secret lease-secret")
            return {"ok": False, "status": "blocked", "failure_code": "lease_busy", "detail": "lease-secret"}
        return await h.call_tool(name, payload)
    h.args["call_tool"] = release_failure
    result = await runner().run_computer_use(**h.args)
    assert result["ok"] is False
    assert result["failure_code"] == "release_requires_operator"
    assert result["operator_intervention_required"] is True
    assert len(releases) == 1 and h.worker.state["lease"] is not None
    records = [json.loads(Path(item["local_path"]).read_text()) for item in result["output_artifacts"]]
    assert any(r["kind"] == "verification" and r["data"]["ok"] for r in records)
    assert records[-1]["kind"] == "release"
    assert records[-1]["data"]["status"] == "unresolved"
    serialized = json.dumps([result, records])
    assert "lease-secret" not in serialized and "endpoint-secret" not in serialized


@pytest.mark.asyncio
async def test_enclosing_timeout_after_dispatch_reconciles_same_id(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act", "complete"])
    h.ctx.runtime_module_config = lambda: {"timeout_s": 0.04}
    async def delayed_receipt(name, payload):
        result = await h.call_tool(name, payload)
        if name.endswith("_act"):
            await asyncio.sleep(0.08)
        return result
    h.args["call_tool"] = delayed_receipt
    result = await runner().run_computer_use(**h.args)
    assert not result["ok"] and result["failure_code"] == "block_timeout"
    assert h.desktop.effects == 1
    actions = [p for op, p in h.calls if op == "act"]
    statuses = [p for op, p in h.calls if op == "status"]
    assert len(actions) == len(statuses) == 1
    assert actions[0]["action_id"] == statuses[0]["action_id"]
    await asyncio.sleep(0.09)  # Drain the synthetic receipt task; never another dispatch.


@pytest.mark.asyncio
async def test_complete_requires_actual_worker_postconditions(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    h.desktop.verify = lambda *_: {"ok": False, "checks": [{"type": "image", "ok": False}]}
    result = await runner().run_computer_use(**h.args)
    assert result["ok"] is False
    assert result["failure_code"] == "postcondition_failed"
    assert h.desktop.effects == 0
    assert "verify" in [op for op, _ in h.calls]


@pytest.mark.asyncio
async def test_one_fresh_observation_per_action_and_bounded_64_turn_context(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act"] * 63 + ["complete"])
    result = await runner().run_computer_use(**h.args)
    assert result["ok"] is True
    assert h.desktop.effects == 63
    assert len([op for op, _ in h.calls if op == "observe"]) == 64
    assert len({p["observation"]["observation_id"] for _, p in h.prompts}) == 64
    for payload, prompt in h.prompts:
        assert len([c for c in payload["messages"][-1]["content"] if c["type"] == "image_url"]) == 1
        assert len(prompt["recent_receipts"]) <= 6
        assert len(json.dumps(prompt)) < 20000
        assert payload["response_format"]["type"] == "json_schema"
    artifacts = list((tmp_path / "artifacts").rglob("*.json"))
    assert artifacts
    assert all("endpoint-secret" not in p.read_text() and "lease_token" not in p.read_text() for p in artifacts)
    assert "lease_token" not in json.dumps(result)
    model_records = [json.loads(p.read_text()) for p in artifacts if "-model.json" in p.name]
    assert model_records[0]["data"]["usage"]["total_tokens"] == 10
    import hashlib
    previous = ""
    for path in sorted(artifacts):
        record = json.loads(path.read_text())
        assert record["previous_sha256"] == previous
        previous = record.pop("sha256")
        assert hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest() == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["{}", "{", '{"schema":"bad"}', lambda p: json.dumps({"schema": "ax4lab.equipment_computer_use.decision.v1", "observation_id": "stale", "kind": "complete", "reason": ""})])
async def test_two_format_attempts_and_no_mutation(tmp_path, monkeypatch, response):
    h = harness(tmp_path, monkeypatch, [response, response, "act"])
    result = await runner().run_computer_use(**h.args)
    assert not result["ok"]
    assert len(h.prompts) == 2
    assert h.desktop.effects == 0


@pytest.mark.asyncio
async def test_timeout_reconciles_same_action_id_without_redispatch(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act", "complete"])
    async def timeout_after_effect(name, payload):
        result = await h.call_tool(name, payload)
        if name.endswith("_act"):
            raise TimeoutError("transport may have actuated")
        return result
    h.args["call_tool"] = timeout_after_effect
    result = await runner().run_computer_use(**h.args)
    assert result["ok"]
    assert h.desktop.effects == 1
    actions = [p for op, p in h.calls if op == "act"]
    status = [p for op, p in h.calls if op == "status"]
    assert len(actions) == len(status) == 1
    assert actions[0]["action_id"] == status[0]["action_id"]


@pytest.mark.asyncio
async def test_operator_and_restart_never_create_new_action(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["needs_operator"])
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "needs_operator"
    h.execution["execution_id"] = "replacement-execution"
    again = await runner().run_computer_use(**h.args)
    assert again["failure_code"] == "resume_requires_operator"
    assert len([op for op, _ in h.calls if op == "acquire"]) == 1


@pytest.mark.asyncio
async def test_cancel_during_inference_discards_result_before_act(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    cancelled = False
    def response(prompt):
        nonlocal cancelled
        cancelled = True
        return json.dumps({"schema": "ax4lab.equipment_computer_use.decision.v1", "observation_id": prompt["observation"]["observation_id"], "kind": "act", "reason": "", "action": {"type": "click", "target_id": "button", "x": 2, "y": 3}})
    h.decisions[:] = [response]
    h.request["_cancel_requested"] = lambda: cancelled
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "cancelled"
    assert h.desktop.effects == 0


@pytest.mark.asyncio
async def test_missing_policy_never_acquires_worker(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    h.package["workflow"].pop("computer_use")
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "missing_policy"
    assert h.calls == []


@pytest.mark.asyncio
async def test_model_endpoint_row_and_identity_are_frozen(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act", "complete"])
    async def changed(name, payload):
        result = await h.call_tool(name, payload)
        if name.endswith("_act"):
            h.backend._endpoint_routes["selected"]["base_url"] = "http://other.invalid/v1"
        return result
    h.args["call_tool"] = changed
    result = await runner().run_computer_use(**h.args)
    assert result["ok"]
    assert set(h.urls) == {"http://model.invalid/v1/chat/completions"}


@pytest.mark.asyncio
async def test_any_postdispatch_exception_reconciles_same_id(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act", "complete"])
    async def broken(name, payload):
        result = await h.call_tool(name, payload)
        if name.endswith("_act"):
            raise OSError("unexpected failure after actual effect")
        return result
    h.args["call_tool"] = broken
    result = await runner().run_computer_use(**h.args)
    assert result["ok"]
    assert h.desktop.effects == 1
    assert len([op for op, _ in h.calls if op == "status"]) == 1


@pytest.mark.asyncio
async def test_no_live_confirmation_means_no_worker_acquire(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    h.request["confirm_live_execute"] = False
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "live_confirmation_required"
    assert h.calls == []


@pytest.mark.asyncio
async def test_drifted_flow_model_fingerprint_cannot_retarget(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    h.execution["model_snapshot"]["endpoint_sha256"] = "0" * 64
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "endpoint_changed"
    assert h.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["not_found", "in_progress", "ambiguous"])
async def test_uncertain_action_never_gets_reissued_or_released(tmp_path, monkeypatch, fault):
    h = harness(tmp_path, monkeypatch, ["act", "complete"])
    async def uncertain(name, payload):
        if name.endswith("_act"):
            h.calls.append(("act", deepcopy(payload)))
            return {"ok": False, "status": "effect_unknown"}
        if name.endswith("_status"):
            h.calls.append(("status", deepcopy(payload)))
            return {"ok": fault == "not_found", "status": fault}
        return await h.call_tool(name, payload)
    h.args["call_tool"] = uncertain
    result = await runner().run_computer_use(**h.args)
    assert result["status"] == "effect_unknown"
    assert result["failure_code"] == "action_requires_operator"
    assert [op for op, _ in h.calls] == ["acquire", "observe", "act", "status"]


@pytest.mark.asyncio
async def test_cancel_during_action_reconciles_but_does_not_continue(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act", "act"])
    cancelled = False
    async def cancel_action(name, payload):
        nonlocal cancelled
        result = await h.call_tool(name, payload)
        if name.endswith("_act"):
            cancelled = True
        return result
    h.args["call_tool"] = cancel_action
    h.request["_cancel_requested"] = lambda: cancelled
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "cancelled"
    assert h.desktop.effects == 1
    assert [op for op, _ in h.calls].count("status") == 1


@pytest.mark.asyncio
async def test_stale_model_result_never_actuates(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    h = harness(tmp_path, monkeypatch, ["act"])
    async def stale(name, payload):
        result = await h.call_tool(name, payload)
        if name.endswith("_observe"):
            result["observation"]["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=151)).isoformat()
        return result
    h.args["call_tool"] = stale
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "stale_observation"
    assert h.desktop.effects == 0


@pytest.mark.asyncio
async def test_old_worker_fails_without_input(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    async def old(name, payload):
        return {"ok": False, "status": "blocked", "failure_code": "computer_use_unavailable"}
    h.args["call_tool"] = old
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "computer_use_unavailable"
    assert not h.prompts and h.desktop.effects == 0


@pytest.mark.asyncio
async def test_worker_exception_is_effect_unknown_not_success(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, ["act"])
    h.desktop.execute = lambda *_: (_ for _ in ()).throw(RuntimeError("worker fault"))
    result = await runner().run_computer_use(**h.args)
    assert result["status"] == "effect_unknown"
    assert result["failure_code"] == "action_requires_operator"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["vllm", "openai"])
async def test_explicit_unsupported_schema_only_uses_json_object_on_same_endpoint(tmp_path, monkeypatch, provider):
    unsupported = httpx.Response(400, json={"error": {"code": "unsupported_json_schema"}})
    h = harness(tmp_path, monkeypatch, [unsupported, "complete"])
    if provider == "openai":
        from backends.openai_client import OpenAIBackend
        backend = OpenAIBackend(api_key="endpoint-secret")
        backend._endpoint_routes = h.backend._endpoint_routes
        h.ctx.primary_backends = {"openai": backend}
        h.ctx.active_backend = "openai"
        h.execution["model_snapshot"]["provider"] = "openai"
    result = await runner().run_computer_use(**h.args)
    assert result["ok"], result
    assert [p[0]["response_format"]["type"] for p in h.prompts] == ["json_schema", "json_object"]
    assert "decision_schema" in h.prompts[-1][1]
    assert set(h.urls) == {"http://model.invalid/v1/chat/completions"}


@pytest.mark.asyncio
async def test_arbitrary_model_error_does_not_fallback(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, [httpx.Response(400, json={"error": {"message": "bad request"}}), "act"])
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "model_request_failed"
    assert len(h.prompts) == 1 and h.desktop.effects == 0


@pytest.mark.asyncio
async def test_truncated_complete_and_missing_worker_checks_fail(tmp_path, monkeypatch):
    def truncated(prompt):
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": json.dumps({
            "schema": "ax4lab.equipment_computer_use.decision.v1", "observation_id": prompt["observation"]["observation_id"], "kind": "complete", "reason": ""})}}]})
    h = harness(tmp_path, monkeypatch, [truncated, truncated])
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "truncated_decision"
    assert not any(op == "verify" for op, _ in h.calls)


@pytest.mark.asyncio
async def test_missing_postcondition_checks_not_model_completion(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch)
    h.desktop.verify = lambda *_: {"ok": True, "checks": []}
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "postcondition_failed"


@pytest.mark.asyncio
async def test_image_over_8mib_is_rejected_without_resizing_or_model_call(tmp_path, monkeypatch):
    import base64
    import hashlib
    import struct
    import zlib
    h = harness(tmp_path, monkeypatch)
    original = h.desktop.capture
    def large(policy):
        observation = original(policy)
        png = base64.b64decode(observation["image_base64"])
        data = b"tEXt" + b"x" * (8 * 1024 * 1024)
        chunk = struct.pack(">I", len(data) - 4) + data + struct.pack(">I", zlib.crc32(data))
        png = png[:-12] + chunk + png[-12:]
        observation.update(image_base64=base64.b64encode(png).decode(), image_sha256=hashlib.sha256(png).hexdigest())
        return observation
    h.desktop.capture = large
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "image_too_large"
    assert not h.prompts and h.desktop.effects == 0


@pytest.mark.asyncio
async def test_model_lease_and_notification_are_reused(tmp_path, monkeypatch):
    from backends.llm_lease import LLMLeaseCoordinator
    h = harness(tmp_path, monkeypatch)
    h.ctx.llm_lease = LLMLeaseCoordinator()
    notifications = []
    async def notify(**kwargs):
        notifications.append(kwargs)
    h.ctx._notify_model_call = notify
    result = await runner().run_computer_use(**h.args)
    assert result["ok"]
    assert notifications == [{"task_type": "equipment_computer_use", "model": "endpoint:selected", "role": "computer_use", "backend": "vllm"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["equipment_profile_id", "cycle_id"])
async def test_scope_change_after_inference_never_acts(tmp_path, monkeypatch, field):
    h = harness(tmp_path, monkeypatch)
    def change(prompt):
        h.state.current_experiment_spec[field] = "another"
        return "complete"
    h.decisions[:] = [change]
    result = await runner().run_computer_use(**h.args)
    assert result["failure_code"] == "cancelled"
    assert h.desktop.effects == 0
    assert all(payload["equipment_profile_id"] == "profile1" for _, payload in h.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [{"type": "click", "target_id": "not-declared", "x": 2, "y": 3},
    {"type": "click", "target_id": "button", "x": 19, "y": 19},
    {"type": "write", "target_id": "button", "text": "arbitrary code"}])
async def test_typed_action_permission_rejection_never_dispatches(tmp_path, monkeypatch, action):
    def choose(prompt):
        return json.dumps({"schema": "ax4lab.equipment_computer_use.decision.v1", "observation_id": prompt["observation"]["observation_id"], "kind": "act", "reason": "", "action": action})
    h = harness(tmp_path, monkeypatch, [choose, choose])
    result = await runner().run_computer_use(**h.args)
    assert not result["ok"]
    assert h.desktop.effects == 0
    assert not any(op == "act" for op, _ in h.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [False, True])
async def test_policy_program_without_validated_package_hash_never_acquires(tmp_path, monkeypatch, evidence):
    h = harness(tmp_path, monkeypatch)
    if evidence:
        h.package["workflow"]["computer_use"]["postconditions"] = [{"type": "program", "program_id": "unbound", "read_only": True}]
    else:
        h.package["workflow"]["computer_use"]["program_ids"] = ["unbound"]
    result = await runner().run_computer_use(**h.args)
    assert result.get("failure_code") == "program_hash_binding_missing"
    assert not h.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [False, True])
@pytest.mark.parametrize("binding", ["manifest_only", "workflow_without_body", "body_without_workflow", "wrong_body_hash", "valid"])
async def test_program_binding_requires_validated_package_body(tmp_path, monkeypatch, evidence, binding):
    from utils.equipment_skill_runtime import canonical_sha256
    h = harness(tmp_path, monkeypatch)
    program = {"schema": "atr.pyautogui_program.v1", "program_id": "bound", "name": "Unicode 검증",
               "sequence": [{"action": "wait_for_file", "pattern": "synthetic.csv"}]}
    digest = canonical_sha256(program)
    h.package["manifest"]["program_sha256"] = {"bound": digest}
    h.package["workflow"]["program_ids"] = ["bound"] if binding in {"workflow_without_body", "wrong_body_hash", "valid"} else []
    h.package["programs"] = [deepcopy(program)] if binding in {"body_without_workflow", "wrong_body_hash", "valid"} else []
    if binding == "wrong_body_hash":
        h.package["programs"][0]["sequence"] = [{"action": "press", "key": "escape"}]
    if evidence:
        h.package["workflow"]["computer_use"]["postconditions"] = [{"type": "program", "program_id": "bound", "read_only": True}]
    else:
        h.package["workflow"]["computer_use"]["program_ids"] = ["bound"]
    result = await runner().run_computer_use(**h.args)
    if binding == "valid":
        assert result["ok"]
        assert h.calls[0][0] == "acquire"
        assert h.calls[0][1]["program_hashes"] == {"bound": digest}
    else:
        assert result.get("failure_code") == "program_hash_binding_missing"
        assert not h.calls and not h.prompts
