"""Profile browsing is separate from the configuration used by the run."""
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from utils import runtime_paths
from utils.equipment_computer_use_settings import load_profile_settings, save_profile_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    paths = replace(main.RUNTIME_PATHS, memory_root=tmp_path / "memory", artifact_root=tmp_path / "artifacts")
    monkeypatch.setattr(main, "RUNTIME_PATHS", paths)
    monkeypatch.setattr(runtime_paths, "_current", paths)
    monkeypatch.setattr(main, "load_all_configs", lambda *a, **k: {"devices": {}})
    monkeypatch.setattr(main.controller, "snapshot", lambda: {"is_running": False})
    monkeypatch.setattr(main, "EQUIPMENT_SKILL_ROOT", tmp_path / "skills")
    monkeypatch.setattr(main, "EQUIPMENT_SKILL_FLOW_PATH", tmp_path / "flows.json")
    monkeypatch.setattr(main, "EQUIPMENT_SKILL_FLOW_RUNTIME_ROOT", tmp_path / "flows")
    return TestClient(main.app)


def create(client, name="Other UTM"):
    response = client.post("/api/equipment/profiles", json={"label": name})
    assert response.status_code == 200, response.text
    return response.json()["profile"]["profile_id"]


def test_created_profile_is_saved_and_reopens_as_its_own_workspace(client):
    profile_id = create(client, "Second UTM")
    from utils.equipment_profiles import EquipmentProfileStore
    stored = EquipmentProfileStore(main.RUNTIME_PATHS.memory_root).read()
    assert {"profile_id": profile_id, "label": "Second UTM"} in stored["profiles"]
    fresh_client = TestClient(main.app)
    assert any(item["profile_id"] == profile_id for item in fresh_client.get("/api/equipment/profiles").json()["profiles"])
    page = fresh_client.get(f"/equipment/windows?profile_id={profile_id}")
    assert page.status_code == 200
    assert f'data-equipment-profile="{profile_id}"' in page.text


def test_new_profile_and_apply_use_its_own_worker(client):
    profile = create(client)
    assert client.get("/api/equipment/profiles").json()["selected_profile_id"] == "utm_windows_v1"
    assert client.post(f"/api/equipment/profiles/{profile}/apply", json={}).status_code == 409
    bridge = main._equipment_bridge(profile_id=profile)
    bridge.save_connection({"candidate_alias": "new-worker", "bridge_url": "http://192.168.0.24:8765", "token": "private-value"})
    response = client.post(f"/api/equipment/profiles/{profile}/apply", json={})
    assert response.status_code == 200, response.text
    assert response.json()["worker_id"] == "new-worker"
    assert "private-value" not in response.text
    assert client.get("/api/equipment/profiles").json()["selected_profile_id"] == profile
    assert client.get("/api/equipment/windows/config?profile_id=utm_windows_v1").json()["connection"]["selected_candidate"] == ""


def test_browsing_other_profile_never_reuses_previous_setup_or_evidence(client):
    main._equipment_bridge().save_utm_profile({"target_window": "Old instrument", "locators": {"start_button": {"x": 420, "y": 200}}})
    profile = create(client)
    result = client.get(f"/api/equipment/windows/config?profile_id={profile}")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["connection"]["selected"] is False
    assert data["utm_profile"]["profile"].get("target_window") != "Old instrument"
    assert not data["utm_profile"]["profile"].get("locators")
    assert not data["utm_live_validation"]
    assert client.get(f"/api/equipment/profiles/{profile}/skill-flow").json()["flow"]["blocks"] == []
    assert client.get("/api/equipment/windows/config?profile_id=utm_windows_v1").json()["utm_profile"]["profile"]["target_window"] == "Old instrument"
    assert client.get("/api/equipment/windows/config?profile_id=missing").status_code == 404


def test_apply_busy_never_changes_selected_device(client, monkeypatch):
    profile = create(client)
    monkeypatch.setattr(main.controller, "snapshot", lambda: {"is_running": True})
    assert client.post(f"/api/equipment/profiles/{profile}/apply", json={}).status_code == 409
    assert client.get("/api/equipment/profiles").json()["selected_profile_id"] == "utm_windows_v1"


def test_delete_requires_confirmation_and_persists_removal(client):
    profile = create(client)
    url = f"/api/equipment/profiles/{profile}"
    assert client.request("DELETE", url + "?profile_id=utm_windows_v1", json={"confirmed": True}).status_code == 422
    assert client.request("DELETE", url, json={"confirmed": False}).status_code == 422
    assert client.request("DELETE", url, json={}).status_code == 422
    assert any(p["profile_id"] == profile for p in client.get("/api/equipment/profiles").json()["profiles"])
    result = client.request("DELETE", url, json={"confirmed": True})
    assert result.status_code == 200, result.text
    assert result.json()["selected_profile_id"] == "utm_windows_v1"
    assert not any(p["profile_id"] == profile for p in TestClient(main.app).get("/api/equipment/profiles").json()["profiles"])
    assert client.get(f"/equipment/windows?profile_id={profile}").status_code == 404


def test_delete_protects_applied_and_builtin_profiles(client):
    from utils.equipment_profiles import EquipmentProfileStore
    profile = create(client)
    EquipmentProfileStore(main.RUNTIME_PATHS.memory_root).apply(profile)
    for protected in (profile, "utm_windows_v1", "windows_desktop_v1"):
        response = client.request("DELETE", f"/api/equipment/profiles/{protected}", json={"confirmed": True})
        assert response.status_code == 409, response.text
    assert client.get("/api/equipment/profiles").json()["selected_profile_id"] == profile


def test_delete_during_run_or_equipment_job_preserves_profile(client, monkeypatch):
    profile = create(client)
    url = f"/api/equipment/profiles/{profile}"
    monkeypatch.setattr(main.controller, "snapshot", lambda: {"is_running": True})
    assert client.request("DELETE", url, json={"confirmed": True}).status_code == 409
    monkeypatch.setattr(main.controller, "snapshot", lambda: {"is_running": False})
    monkeypatch.setattr(main, "_EQUIPMENT_AGENTIC_ACTIVE_PROFILES", {profile})
    assert client.request("DELETE", url, json={"confirmed": True}).status_code == 409
    assert any(p["profile_id"] == profile for p in client.get("/api/equipment/profiles").json()["profiles"])


def test_delete_cannot_disconnect_an_in_flight_console_execution(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace
    profile = create(client)
    entered, release = Event(), Event()
    def execute(**kwargs):
        entered.set()
        assert release.wait(5)
        return {"content": b'{"ok": true}', "content_type": "application/json", "status_code": 200}
    monkeypatch.setattr(main, "_equipment_bridge", lambda: SimpleNamespace(proxy_ui_request=execute))
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(client.post, f"/equipment/windows/bridge-ui/execute?profile_id={profile}", json={})
        try:
            assert entered.wait(5)
            response = client.request("DELETE", f"/api/equipment/profiles/{profile}", json={"confirmed": True})
            assert response.status_code == 409, response.text
        finally:
            release.set()
        assert running.result(timeout=5).status_code == 200
    assert client.request("DELETE", f"/api/equipment/profiles/{profile}", json={"confirmed": True}).status_code == 200


@pytest.mark.asyncio
async def test_console_disconnect_keeps_profile_in_use_until_worker_finishes(client, monkeypatch):
    import asyncio
    from threading import Event
    from types import SimpleNamespace
    from utils.equipment_profiles import equipment_profile_scope
    profile = create(client)
    entered, release = Event(), Event()
    def execute(**kwargs):
        entered.set()
        assert release.wait(5)
        return {"content": b"{}", "content_type": "application/json", "status_code": 200}
    async def body():
        return b"{}"
    monkeypatch.setattr(main, "_equipment_bridge", lambda: SimpleNamespace(proxy_ui_request=execute))
    request = SimpleNamespace(method="POST", body=body, url=SimpleNamespace(query=""), headers={})
    with equipment_profile_scope(profile):
        running = asyncio.create_task(main.proxy_windows_equipment_bridge_ui("execute", request))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert main._EQUIPMENT_CONSOLE_ACTIVE_PROFILES.get(profile) == 1
    finally:
        release.set()
        for _ in range(100):
            if not main._EQUIPMENT_CONSOLE_ACTIVE_PROFILES.get(profile):
                break
            await asyncio.sleep(0.01)
    assert profile not in main._EQUIPMENT_CONSOLE_ACTIVE_PROFILES


@pytest.mark.asyncio
async def test_unscoped_console_tracks_the_same_profile_as_its_bridge(client, monkeypatch):
    from types import SimpleNamespace
    from utils.equipment_profiles import EquipmentProfileStore
    first, second = create(client, "First"), create(client, "Second")
    store = EquipmentProfileStore(main.RUNTIME_PATHS.memory_root)
    store.apply(first)
    def make_bridge():
        bound = store.selected_id()
        def execute(**kwargs):
            assert main._EQUIPMENT_CONSOLE_ACTIVE_PROFILES.get(bound) == 1
            return {"content": b"{}", "content_type": "application/json", "status_code": 200}
        return SimpleNamespace(proxy_ui_request=execute)
    async def body():
        store.apply(second)
        return b"{}"
    monkeypatch.setattr(main, "_equipment_bridge", make_bridge)
    request = SimpleNamespace(method="POST", body=body, url=SimpleNamespace(query=""), headers={})
    result = await main.proxy_windows_equipment_bridge_ui("execute", request)
    assert result.status_code == 200


def test_profile_selection_filters_skills_and_rejects_conflicting_path(client, monkeypatch):
    profile = create(client)
    class Registry:
        def list(self):
            return [{"skill_id": "old", "target_profile": "utm_windows_v1"}, {"skill_id": "new", "target_profile": profile}]
    monkeypatch.setattr(main, "_equipment_skill_registry", Registry)
    assert client.get(f"/api/equipment/skills?profile_id={profile}").json()["skills"] == [{"skill_id": "new", "target_profile": profile}]
    assert client.get(f"/api/equipment/profiles/{profile}/state?profile_id=utm_windows_v1").status_code == 422


def test_all_evidence_panels_use_the_viewed_profile(client, monkeypatch):
    profile = create(client)
    monkeypatch.setattr(main.controller._state, "current_experiment_spec", {})
    monkeypatch.setattr(main.controller._state, "run_metadata", {
        "last_windows_utm_protocol_result": {"private_old_result": True},
        "last_windows_utm_proof_package": {"private_old_result": True},
    })
    monkeypatch.setattr(main, "_windows_utm_evidence_audit_from_metadata", lambda metadata, **kw: metadata)
    monkeypatch.setattr(main, "_windows_utm_proof_package_from_metadata", lambda metadata, **kw: {"source": metadata})
    monkeypatch.setattr(main, "_persist_windows_utm_proof_package", lambda package: package)
    monkeypatch.setattr(main, "_windows_utm_vision_proof_draft", lambda metadata, **kw: {"source": metadata})
    async def emit(**kw):
        pass
    monkeypatch.setattr(main.controller, "emit_workspace_result", emit)
    for method, path in (("get", "evidence-audit"), ("get", "proof-package"), ("post", "vision-proof-draft")):
        response = getattr(client, method)(f"/api/equipment/windows/{path}?profile_id={profile}", **({"json": {}} if method == "post" else {}))
        assert response.status_code == 200, response.text
        assert "private_old_result" not in response.text
    # A custom workspace must not overwrite the original instrument's evidence.
    assert main.controller._state.run_metadata["last_windows_utm_proof_package"] == {"private_old_result": True}
    from utils.equipment_profiles import equipment_profile_scope
    with equipment_profile_scope(profile):
        assert "private_old_result" not in str(main._load_windows_utm_proof_package_for_verify()[0])


def test_direct_profile_state_uses_requested_device(client):
    main._equipment_bridge().save_utm_profile({"target_window": "Old instrument"})
    profile = create(client)
    assert main._equipment_profile_state(profile)["utm_profile"]["profile"].get("target_window") != "Old instrument"


def test_computer_use_settings_default_to_legacy_and_merge_without_losing_preferences(client):
    settings_path = main.RUNTIME_PATHS.memory_root / "equipment_workspace_settings.json"
    save_profile_settings(
        settings_path,
        "windows_desktop_v1",
        {"vision_link_enabled": True, "future_preference": {"theme": "dim"}},
    )

    initial = client.get("/api/equipment/profiles/windows_desktop_v1/state").json()["workspace_settings"]
    assert initial == {
        "vision_link_enabled": True,
        "future_preference": {"theme": "dim"},
        "execution_mode": "skill_flow",
        "computer_use": {"max_turns": 64, "request_timeout_s": 120.0, "frame_max_age_s": 150.0},
        "vision_link_source": "stored",
    }

    saved = client.post(
        "/api/equipment/profiles/windows_desktop_v1/settings",
        json={
            "execution_mode": "computer_use",
            "computer_use": {"max_turns": 12, "request_timeout_s": 45, "frame_max_age_s": 30},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["workspace_settings"] == {
        "vision_link_enabled": True,
        "future_preference": {"theme": "dim"},
        "execution_mode": "computer_use",
        "computer_use": {"max_turns": 12, "request_timeout_s": 45.0, "frame_max_age_s": 30.0},
        "vision_link_source": "stored",
    }
    assert load_profile_settings(settings_path, "windows_desktop_v1")["future_preference"] == {"theme": "dim"}
    assert TestClient(main.app).get(
        "/api/equipment/profiles/windows_desktop_v1/state"
    ).json()["workspace_settings"]["execution_mode"] == "computer_use"


def test_computer_use_settings_are_profile_isolated_and_invalid_patch_is_atomic(client):
    other = create(client, "Computer-use desktop")
    settings_path = main.RUNTIME_PATHS.memory_root / "equipment_workspace_settings.json"
    save_profile_settings(settings_path, "windows_desktop_v1", {"vision_link_enabled": True, "sentinel": "keep"})

    changed = client.post(
        f"/api/equipment/profiles/{other}/settings",
        json={"vision_link_enabled": False, "execution_mode": "computer_use", "computer_use": {"max_turns": 7}},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["workspace_settings"]["computer_use"] == {
        "max_turns": 7,
        "request_timeout_s": 120.0,
        "frame_max_age_s": 150.0,
    }
    assert client.get("/api/equipment/profiles/windows_desktop_v1/state").json()["workspace_settings"] == {
        "vision_link_enabled": True,
        "sentinel": "keep",
        "execution_mode": "skill_flow",
        "computer_use": {"max_turns": 64, "request_timeout_s": 120.0, "frame_max_age_s": 150.0},
        "vision_link_source": "stored",
    }

    before = settings_path.read_bytes()
    for patch in (
        {"execution_mode": "automatic"},
        {"execution_mode": None},
        {"computer_use": None},
        {"computer_use": {"max_turns": 0}},
        {"computer_use": {"request_timeout_s": True}},
        {"computer_use": {"frame_max_age_s": 601}},
        {"computer_use": {"unknown": 1}},
        {"unknown_preference": True},
    ):
        response = client.post(f"/api/equipment/profiles/{other}/settings", json=patch)
        assert response.status_code == 422, (patch, response.text)
        assert settings_path.read_bytes() == before


def test_settings_save_never_retargets_or_launches_an_active_execution(client, monkeypatch):
    service = main._equipment_runtime_service()
    active = service.begin(
        sequence_id="settings-freeze-sequence",
        run_id="settings-freeze-run",
        experiment_id="settings-freeze-experiment",
        specimen_id="settings-freeze-specimen",
        profile_id="windows_desktop_v1",
        mode="live",
        worker={"worker_id": "worker-original", "kind": "windows_pyautogui"},
        execution_ref={"type": "skill", "skill_id": "demo", "version": "1.0.0"},
        metadata={
            "execution_settings": {
                "execution_mode": "computer_use",
                "computer_use": {"max_turns": 64, "request_timeout_s": 120.0, "frame_max_age_s": 150.0},
            }
        },
    )
    monkeypatch.setattr(
        main,
        "_equipment_bridge_for_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("settings save contacted a worker")),
    )
    monkeypatch.setattr(
        main,
        "_equipment_computer_use_endpoint_status",
        lambda: (_ for _ in ()).throw(AssertionError("settings save inspected or launched a model")),
    )

    response = client.post(
        "/api/equipment/profiles/windows_desktop_v1/settings",
        json={"execution_mode": "skill_flow", "computer_use": {"max_turns": 3}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["non_actuating"] is True
    reloaded = service.get(active["execution_id"])
    assert reloaded["worker"]["worker_id"] == "worker-original"
    assert reloaded["metadata"]["execution_settings"]["execution_mode"] == "computer_use"
    assert reloaded["metadata"]["execution_settings"]["computer_use"]["max_turns"] == 64


def test_computer_use_readiness_is_passive_and_reports_concrete_program_binding_blocker(client, monkeypatch):
    calls = []

    class Bridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True, "selected_candidate": "worker-1"}

        def _live_get(self, tool, path, payload):
            calls.append((tool, path, dict(payload)))
            return {
                "ok": True,
                "computer_use_v1": True,
                "computer_use_limits": {"program_hash_binding": False},
            }

    policy = {
        "schema": "ax4lab.equipment_computer_use.policy.v1",
        "application": {"window_title": "Demo"},
        "targets": {},
        "protected_regions": [],
        "program_ids": [],
        "runtime_value_keys": [],
        "postconditions": [{"type": "program", "program_id": "read_meter", "read_only": True}],
        "mask_regions": [],
    }

    class Registry:
        def get(self, skill_id, version):
            assert (skill_id, version) == ("computer_use_demo_v1", "1.0.0")
            return {
                "manifest": {"skill_id": skill_id, "version": version, "lifecycle": "deployed", "enabled": True,
                             "target_profile": "windows_desktop_v1"},
                "workflow": {"computer_use": policy},
            }

    monkeypatch.setattr(main, "_equipment_bridge_for_profile", lambda profile_id: Bridge())
    monkeypatch.setattr(main, "_equipment_skill_registry", lambda: Registry())
    monkeypatch.setattr(main, "_equipment_computer_use_endpoint_status", lambda: {
        "ready": True, "vision_declared": True, "provider": "vllm", "model": "endpoint:vision"
    })
    saved = client.post(
        "/api/equipment/profiles/windows_desktop_v1/settings",
        json={"execution_mode": "computer_use"},
    )
    assert saved.status_code == 200

    response = client.get(
        "/api/equipment/profiles/windows_desktop_v1/computer-use-readiness",
        params={"skill_id": "computer_use_demo_v1", "version": "1.0.0"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["non_actuating"] is True
    assert payload["ready"] is False
    assert payload["gates"] == {
        "execution_mode_selected": True,
        "worker_computer_use_v1": True,
        "worker_program_hash_binding": False,
        "endpoint_vision": True,
        "skill_policy": True,
        "skill_postconditions": True,
    }
    assert payload["blockers"] == [{
        "code": "program_hash_binding_unavailable",
        "message": "Selected worker must advertise computer_use_limits.program_hash_binding for this Skill policy.",
    }]
    assert calls == [("equipment.pyautogui.computer_use_readiness", "/capabilities", {"runtime_mode": "live"})]


def test_computer_use_readiness_rejects_invalid_policy_without_model_or_action(client, monkeypatch):
    class Bridge:
        def connection_status(self):
            return {"selected": True, "token_configured": True, "selected_candidate": "worker-1"}

        def _live_get(self, *_args):
            return {"ok": True, "computer_use_v1": True,
                    "computer_use_limits": {"program_hash_binding": True}}

    class Registry:
        def get(self, skill_id, version):
            return {
                "manifest": {"skill_id": skill_id, "version": version, "lifecycle": "draft", "enabled": True,
                             "target_profile": "windows_desktop_v1"},
                "workflow": {"computer_use": {"schema": "ax4lab.equipment_computer_use.policy.v1",
                                                "application": {"window_title": "Demo"},
                                                "targets": {}, "protected_regions": [], "program_ids": [],
                                                "runtime_value_keys": [], "postconditions": [], "mask_regions": []}},
            }

    monkeypatch.setattr(main, "_equipment_bridge_for_profile", lambda _profile_id: Bridge())
    monkeypatch.setattr(main, "_equipment_skill_registry", lambda: Registry())
    monkeypatch.setattr(main, "_equipment_computer_use_endpoint_status", lambda: {
        "ready": False, "vision_declared": False, "failure_code": "endpoint_vision_required",
        "message": "Selected endpoint must explicitly support image input",
    })
    response = client.get(
        "/api/equipment/profiles/windows_desktop_v1/computer-use-readiness",
        params={"skill_id": "bad", "version": "1.0.0"},
    )
    assert response.status_code == 200
    payload = response.json()
    codes = [item["code"] for item in payload["blockers"]]
    assert codes == ["execution_mode_required", "endpoint_vision_required", "skill_not_deployed", "postconditions_invalid"]
    assert payload["skill"]["policy_valid"] is False
    assert payload["skill"]["postconditions_valid"] is False
