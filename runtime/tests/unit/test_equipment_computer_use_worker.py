"""Worker protocol safety tests; synthetic pixels/desktop, never real input."""
import base64
import hashlib
import importlib
import io
import json
import threading
from datetime import datetime, timezone

import pytest
from PIL import Image


def runtime():
    return importlib.import_module("Pyautogui_server_for_window.bridge.computer_use_runtime")


def policy():
    digest = hashlib.sha256(bytes(10 * 10 * 3)).hexdigest()
    return {"schema": "ax4lab.equipment_computer_use.policy.v1",
            "application": {"window_title": "Demo"},
            "targets": {"button": {"region": [0, 0, 10, 10], "actions": ["click"],
                "anchor": {"region": [0, 0, 10, 10], "sha256": digest}}},
            "protected_regions": [], "program_ids": [], "runtime_value_keys": [],
            "postconditions": [{"type": "image", "region": [0, 0, 10, 10], "sha256": digest}],
            "mask_regions": []}


IDENTITY = dict(execution_id="exec1", run_id="run1", cycle_id="cycle1", specimen_id="spec1", equipment_profile_id="profile1")


class Desktop:
    def __init__(self):
        self.effects = 0
        self.before_execute = lambda: None
        self.changed = False
        self.dpi = 96

    def capture(self, policy):
        image = Image.new("RGB", (20, 20))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        png = stream.getvalue()
        return dict(captured_at=datetime.now(timezone.utc).isoformat(), image_width=20, image_height=20,
                    desktop_rect=[0, 0, 20, 20], window_rect=[0, 0, 20, 20], window_title="Demo",
                    window_id="2" if self.changed else "1", image_base64=base64.b64encode(png).decode(),
                    image_sha256=hashlib.sha256(png).hexdigest(), anchor_hashes={"button": policy["targets"]["button"]["anchor"]["sha256"]}, dpi=self.dpi)

    def execute(self, action, context):
        self.before_execute()
        self.effects += 1
        return {"ok": True}

    def verify(self, policy, context):
        return {"ok": True, "checks": [True]}


def setup(tmp_path):
    desktop = Desktop()
    controller = runtime().ComputerUseController(tmp_path, desktop, "worker1")
    lease = controller.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")
    assert lease["ok"], lease
    credentials = {**IDENTITY, "session_id": lease["session_id"], "lease_token": lease["lease_token"]}
    observation = controller.handle("observe", credentials, "principal")["observation"]
    action = dict(action_id="action1", observation_id=observation["observation_id"], action={"type": "click", "target_id": "button", "x": 2, "y": 3})
    digest = hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return controller, desktop, credentials, {**credentials, **action, "payload_sha256": digest}


def test_lifecycle_and_idempotency(tmp_path):
    c, d, credentials, action = setup(tmp_path)
    assert c.handle("act", action, "principal")["status"] == "completed"
    assert c.handle("act", action, "principal")["status"] == "completed"
    assert d.effects == 1
    assert c.handle("status", {**credentials, "action_id": "action1"}, "principal")["status"] == "completed"
    assert c.handle("verify", credentials, "principal")["evidence"]["ok"] is True
    assert c.handle("release", credentials, "principal")["ok"]


def test_credentials_profile_and_hash_cannot_retarget(tmp_path):
    c, d, credentials, action = setup(tmp_path)
    for altered, principal in [({}, "other"), ({"lease_token": "bad"}, "principal"), ({"equipment_profile_id": "other"}, "principal")]:
        assert not c.handle("act", {**action, **altered}, principal)["ok"]
    assert not c.handle("acquire", {**IDENTITY, "equipment_profile_id": "other", "policy": policy()}, "principal")["ok"]
    assert c.handle("act", action, "principal")["ok"]
    changed = {**action, "action": {**action["action"], "x": 4}}
    changed["payload_sha256"] = hashlib.sha256(json.dumps({k: changed[k] for k in ("action_id", "observation_id", "action")}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert c.handle("act", changed, "principal")["failure_code"] == "action_conflict"
    assert d.effects == 1


def test_concurrent_action_status_and_legacy_exclusion(tmp_path, monkeypatch):
    c, d, credentials, action = setup(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    def blocking():
        entered.set()
        assert finish.wait(5)
    d.before_execute = blocking
    thread = threading.Thread(target=lambda: c.handle("act", action, "principal"))
    thread.start()
    try:
        assert entered.wait(2)
        now = runtime().time.time()
        monkeypatch.setattr(runtime().time, "time", lambda: now + 1000)
        assert not c.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")["ok"]
        assert c.handle("status", {**credentials, "action_id": "action1"}, "principal")["status"] == "in_progress"
        assert c.handle("act", action, "principal")["status"] == "in_progress"
        assert not c.handle("release", credentials, "principal")["ok"]
        with pytest.raises(runtime().ComputerUseError):
            with c.legacy_mutation():
                pytest.fail("legacy input permitted")
    finally:
        finish.set()
        thread.join(3)
    assert d.effects == 1


def test_persisted_intent_and_fsync_failure_blocks_effect(tmp_path, monkeypatch):
    c, d, credentials, action = setup(tmp_path)
    def inspect():
        ledger = json.loads((tmp_path / "computer_use_ledger.json").read_text())
        assert ledger["actions"]["action1"]["status"] == "in_progress"
        assert credentials["lease_token"] not in json.dumps(ledger)
    d.before_execute = inspect
    monkeypatch.setattr(runtime().os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk")))
    assert not c.handle("act", action, "principal")["ok"]
    assert d.effects == 0


def test_intent_is_durable_before_input_and_observation_single_use(tmp_path):
    c, d, credentials, action = setup(tmp_path)
    def inspect():
        ledger = json.loads((tmp_path / "computer_use_ledger.json").read_text())
        assert ledger["actions"]["action1"]["status"] == "in_progress"
        assert credentials["lease_token"] not in json.dumps(ledger)
    d.before_execute = inspect
    assert c.handle("act", action, "principal")["ok"]
    another = {**action, "action_id": "action2"}
    another["payload_sha256"] = runtime().action_payload_sha256(another)
    assert c.handle("act", another, "principal")["failure_code"] == "stale_observation"
    assert d.effects == 1


def test_lease_refresh_and_stale_observation(tmp_path, monkeypatch):
    c, d, credentials, action = setup(tmp_path)
    now = runtime().time.time()
    monkeypatch.setattr(runtime().time, "time", lambda: now + 151)
    assert c.handle("act", action, "principal")["failure_code"] == "stale_observation"
    assert c.handle("status", {**credentials, "action_id": "missing"}, "principal")["status"] == "not_found"
    monkeypatch.setattr(runtime().time, "time", lambda: now + 400)
    assert not c.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")["ok"]
    assert d.effects == 0


def test_masked_policy_cannot_use_legacy_program_capture_paths(tmp_path):
    c = runtime().ComputerUseController(tmp_path, Desktop(), "worker1")
    for evidence in (False, True):
        p = policy()
        p["mask_regions"] = [[15, 15, 5, 5]]
        if evidence:
            p["postconditions"] = [{"type": "program", "program_id": "evidence", "read_only": True}]
        else:
            p["program_ids"] = ["program1"]
        result = c.handle("acquire", {**IDENTITY, "policy": p}, "principal")
        assert result["failure_code"] == "masking_program_unsupported"


def test_evidence_requires_actual_assertion_success():
    from types import SimpleNamespace
    observed = []
    def execute(gui, **kwargs):
        observed.append(kwargs["payload"])
        kwargs["trace"].append({"status": "warning"})
        return {"ok": True}
    server = SimpleNamespace(_all_programs=lambda: {"evidence": {"sequence": [{"action": "assert_visible", "target": "ready"}]}},
        get_pyautogui=lambda: (object(), None), _execute_protocol_sequence=execute)
    p = policy()
    p["postconditions"] = [{"type": "program", "program_id": "evidence", "read_only": True}]
    native = dict(window_title="Demo", window_id="1", window_rect=[0, 0, 20, 20], desktop_rect=[0, 0, 20, 20], dpi=96)
    result = runtime().NativeDesktopAdapter(server, native_context=lambda: dict(native)).verify(p, IDENTITY)
    assert not result["ok"]
    assert observed[0]["require_screen_assertions"] is True


@pytest.mark.parametrize("action", ["assert_visible", "assert_text", "pixel_matches_color", "wait_until_image", "wait_until_text"])
@pytest.mark.parametrize("condition", ["wrong_foreground", "unavailable_dpi", "changed", "valid"])
def test_screen_evidence_requires_stable_application_and_native_dpi(action, condition):
    from contextlib import contextmanager
    from types import SimpleNamespace
    native = {"window_title": "Other" if condition == "wrong_foreground" else "Demo", "window_id": "1",
              "window_rect": [0, 0, 20, 20], "desktop_rect": [0, 0, 20, 20], "dpi": 96}
    state = {"scoped": False, "checks": 0}
    @contextmanager
    def scope():
        if condition == "unavailable_dpi":
            raise runtime().ComputerUseError("native_context_unavailable", "DPI unavailable")
        state["scoped"] = True
        try:
            yield
        finally:
            state["scoped"] = False
    def evidence(gui, **kwargs):
        state["checks"] += 1
        if condition == "valid":
            assert state["scoped"], "screen evidence ran outside verified native DPI scope"
        if condition == "changed":
            native["window_id"] = "2"
        return {"ok": True}
    server = SimpleNamespace(_all_programs=lambda: {"evidence": {"sequence": [{"action": action}]}},
        get_pyautogui=lambda: (object(), None), _execute_protocol_sequence=evidence)
    adapter = runtime().NativeDesktopAdapter(server, native_context=lambda: dict(native))
    adapter.native_scope = scope
    p = policy()
    p["postconditions"] = [{"type": "program", "program_id": "evidence", "read_only": True}]
    if condition == "valid":
        assert adapter.verify(p, IDENTITY)["ok"]
    else:
        with pytest.raises(runtime().ComputerUseError) as error:
            adapter.verify(p, IDENTITY)
        assert error.value.code == {"wrong_foreground": "window_mismatch", "unavailable_dpi": "native_context_unavailable", "changed": "window_changed"}[condition]
    assert state["checks"] == (1 if condition in {"changed", "valid"} else 0)
    assert not state["scoped"]


def test_crash_unresolved_blocks_expiry_and_replay(tmp_path, monkeypatch):
    c, d, credentials, action = setup(tmp_path)
    def crash():
        raise KeyboardInterrupt()
    d.before_execute = crash
    with pytest.raises(KeyboardInterrupt):
        c.handle("act", action, "principal")
    restarted = runtime().ComputerUseController(tmp_path, d, "worker1")
    monkeypatch.setattr(runtime().time, "time", lambda: 99999999999)
    assert restarted.handle("status", {**credentials, "action_id": "action1"}, "principal")["status"] == "ambiguous"
    assert not restarted.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")["ok"]
    assert restarted.handle("act", action, "principal")["status"] == "ambiguous"
    assert d.effects == 0


def test_changed_window_refuses_dispatch(tmp_path):
    c, d, _, action = setup(tmp_path)
    d.changed = True
    assert not c.handle("act", action, "principal")["ok"]
    assert d.effects == 0


def test_changed_dpi_refuses_dispatch_even_with_same_bounds(tmp_path):
    c, d, _, action = setup(tmp_path)
    d.dpi = 144
    assert c.handle("act", action, "principal")["failure_code"] == "window_changed"
    assert d.effects == 0


def test_legacy_in_progress_prevents_acquire(tmp_path):
    c = runtime().ComputerUseController(tmp_path, Desktop(), "worker1")
    with c.legacy_mutation():
        assert not c.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")["ok"]
    assert c.handle("acquire", {**IDENTITY, "policy": policy()}, "principal")["ok"]


def test_native_adapter_masks_pixels_and_rejects_focus_outside_target():
    from types import SimpleNamespace
    dispatches = []
    image = Image.new("RGB", (20, 20), (255, 255, 255))
    gui = SimpleNamespace(screenshot=lambda **kw: image.copy(), press=lambda key: dispatches.append(key))
    server = SimpleNamespace(get_pyautogui=lambda: (gui, None))
    state = dict(window_title="Demo", window_id="1", window_rect=[0, 0, 20, 20],
                 desktop_rect=[0, 0, 20, 20], focus_rect=[10, 10, 10, 10], dpi=96)
    adapter = runtime().NativeDesktopAdapter(server, native_context=lambda: dict(state))
    p = policy()
    p["mask_regions"] = [[15, 15, 5, 5]]
    obs = adapter.capture(p)
    decoded = Image.open(io.BytesIO(base64.b64decode(obs["image_base64"])))
    assert decoded.getpixel((16, 16)) == (0, 0, 0)
    assert decoded.getpixel((0, 0)) == (255, 255, 255)
    p["targets"]["button"]["anchor"]["sha256"] = obs["anchor_hashes"]["button"]
    context = {"policy": p, "observation": obs}
    with pytest.raises(runtime().ComputerUseError, match="focus"):
        adapter.execute({"type": "press", "target_id": "button", "key": "enter"}, context)
    assert not dispatches
    state["focus_rect"] = [1, 1, 5, 5]
    assert adapter.execute({"type": "press", "target_id": "button", "key": "enter"}, context)["ok"]
    assert dispatches == ["enter"]


def test_evidence_program_cannot_disguise_mutating_steps():
    from types import SimpleNamespace
    effects = []
    server = SimpleNamespace(_all_programs=lambda: {"evidence": {"read_only": True, "program_type": "evidence_check",
        "sequence": [{"action": "click", "x": 2, "y": 3}]}}, _execute=lambda p: effects.append(p))
    adapter = runtime().NativeDesktopAdapter(server)
    p = policy()
    p["postconditions"] = [{"type": "program", "program_id": "evidence", "read_only": True}]
    with pytest.raises(runtime().ComputerUseError):
        adapter.verify(p, {})
    assert not effects


def test_worker_http_auth_ownership_and_legacy_standalone(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    import urllib.request
    import urllib.error
    path = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py"
    spec = importlib.util.spec_from_file_location("computer_use_test_server", path)
    server = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server
    spec.loader.exec_module(server)
    c, d, credentials, action = setup(tmp_path / "ledger")
    monkeypatch.setattr(server, "_computer_use_controller", lambda: c)
    monkeypatch.setattr(server, "TOKEN", "secret")
    monkeypatch.setattr(server, "ARTIFACT_ROOT", tmp_path / "artifacts")
    calls = []
    monkeypatch.setattr(server, "_execute", lambda p: calls.append(p) or {"ok": True})
    http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    def post(path, body, token=""):
        request = urllib.request.Request(f"http://127.0.0.1:{http.server_port}{path}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", server.TOKEN_HEADER: token})
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)
    try:
        assert post("/computer-use/acquire", {**IDENTITY, "policy": policy()})[0] == 401
        for path in ("/execute", "/recordings/start", "/recordings/stop", "/programs/register", "/locators/capture", "/screenshot"):
            assert post(path, {})[1]["failure_code"] == "desktop_owned"
        assert not calls
        c.handle("release", credentials, "principal")
        assert post("/execute", {})[1]["ok"]
        assert calls == [{}]
        assert post("/computer-use/acquire", {**IDENTITY, "policy": policy()}, "secret")[1]["ok"]
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)


def test_optional_helpers_absent_standalone_import_and_package_inclusion(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from utils.windows_bridge_release import build_release_package, load_release_manifest
    root = Path(__file__).resolve().parents[2]
    standalone = tmp_path / "worker.py"
    standalone.write_bytes((root / "install/windows_pyautogui_bridge_server.py").read_bytes())
    script = "import runpy; m=runpy.run_path('worker.py',run_name='standalone'); assert m['COMPUTER_USE'] is None; assert m['_capability_catalog']()['computer_use_v1'] is False; assert m['_validate_program_definition']({})['ok'] is False"
    env = {**os.environ, "WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT": str(tmp_path / "artifacts")}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    (tmp_path / "computer_use_runtime.py").write_text("raise RuntimeError('optional module unavailable')")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, '.'); " + script],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    package_root = root / "Pyautogui_server_for_window"
    package = build_release_package(load_release_manifest(package_root=package_root), package_root=package_root)
    files = {item["path"]: base64.b64decode(item["data_base64"]) for item in package["files"]}
    for name in ("computer_use_contract.py", "computer_use_runtime.py"):
        assert files[f"bridge/{name}"] == (package_root / "bridge" / name).read_bytes()


def test_native_unavailable_context_and_registered_program_dispatch():
    from types import SimpleNamespace
    gui = SimpleNamespace(screenshot=lambda **kw: Image.new("RGB", (20, 20)))
    calls = []
    server = SimpleNamespace(get_pyautogui=lambda: (gui, None), _execute=lambda payload: calls.append(payload) or {"ok": True})
    native = dict(window_title="Demo", window_id="1", window_rect=[0, 0, 20, 20], desktop_rect=[0, 0, 20, 20], dpi=96)
    adapter = runtime().NativeDesktopAdapter(server, native_context=lambda: dict(native))
    p = policy()
    p["program_ids"] = ["known"]
    observation = adapter.capture(p)
    context = {**IDENTITY, "policy": p, "observation": observation, "action_id": "action1", "runtime_values": {"program_id": "not-authorized"}}
    assert adapter.execute({"type": "invoke_program", "program_id": "known"}, context)["ok"]
    assert calls[0]["program_id"] == "known"
    assert calls[0]["sequence_id"] == "action1"
    native["window_rect"] = [0, 0, 21, 20]
    with pytest.raises(runtime().ComputerUseError):
        adapter.execute({"type": "invoke_program", "program_id": "known"}, context)
    assert len(calls) == 1


def test_write_failure_never_dispatches_and_corrupt_ledger_never_resets(tmp_path, monkeypatch):
    c, d, _, action = setup(tmp_path)
    monkeypatch.setattr(runtime().os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    assert c.handle("act", action, "principal")["failure_code"] == "ledger_unavailable"
    assert d.effects == 0
    (tmp_path / "computer_use_ledger.json").write_text("corrupt")
    with pytest.raises(ValueError):
        runtime().ComputerUseController(tmp_path, d, "worker1")


def test_structurally_corrupt_lease_cannot_be_replaced(tmp_path):
    (tmp_path / "computer_use_ledger.json").write_text('{"lease":{},"actions":{}}')
    with pytest.raises(runtime().ComputerUseError):
        runtime().ComputerUseController(tmp_path, Desktop(), "worker1")


@pytest.mark.parametrize("failure", [None, "body", "verification", "unsupported"])
def test_scoped_native_dpi_enters_verifies_and_restores(failure):
    from types import SimpleNamespace
    state = {"context": 17, "calls": []}
    def set_context(value):
        state["calls"].append(value)
        previous = state["context"]
        state["context"] = value
        return previous
    api = SimpleNamespace(SetThreadDpiAwarenessContext=set_context,
        GetThreadDpiAwarenessContext=lambda: state["context"],
        GetAwarenessFromDpiAwarenessContext=lambda context: 0 if failure == "verification" else 2)
    if failure == "unsupported":
        del api.SetThreadDpiAwarenessContext
    if failure:
        with pytest.raises((runtime().ComputerUseError, RuntimeError)):
            with runtime().native_dpi_context(api):
                assert state["context"] == -4
                if failure == "body":
                    raise RuntimeError("synthetic capture failure")
    else:
        with runtime().native_dpi_context(api):
            assert state["context"] == -4
    assert state["context"] == 17
    assert state["calls"] == ([] if failure == "unsupported" else [-4, 17])
