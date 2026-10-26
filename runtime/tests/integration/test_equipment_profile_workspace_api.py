"""Profile browsing is separate from the configuration used by the run."""
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from utils import runtime_paths


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
