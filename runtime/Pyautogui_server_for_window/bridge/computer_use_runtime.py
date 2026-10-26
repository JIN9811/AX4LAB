"""Authenticated desktop ownership and durable, at-most-once action dispatch.

The adapter is trusted worker code, never supplied by HTTP/model callers. A
persisted ambiguous effect deliberately requires operator recovery, not expiry.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from uuid import uuid4

try:
    from .computer_use_contract import ComputerUseError, validate_policy, validate_action, _validate_observation
except ImportError:  # standalone packaged worker
    from computer_use_contract import ComputerUseError, validate_policy, validate_action, _validate_observation

IDENTITY_FIELDS = ("execution_id", "run_id", "cycle_id", "specimen_id", "equipment_profile_id")
OPERATIONS = {"acquire", "observe", "act", "status", "verify", "release"}


def _require(condition, code, message):
    if not condition:
        raise ComputerUseError(code, message)


def _id(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value),
             "invalid_request", "Invalid identity")
    return value


def action_payload_sha256(payload):
    """Hash only action_id, observation_id and action, canonical UTF-8 JSON."""
    return hashlib.sha256(json.dumps({key: payload[key] for key in
        ("action_id", "observation_id", "action")}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ComputerUseController:
    def __init__(self, root: Path, adapter, worker_id: str):
        self.root, self.adapter, self.worker_id = Path(root), adapter, _id(worker_id)
        self.lock = threading.RLock()
        self.busy = False
        self.legacy_active = 0
        self.observation = None
        self.faulted = False
        self.path = self.root / "computer_use_ledger.json"
        self.state = {"lease": None, "actions": {}}
        if self.path.exists():
            # Corruption fails startup closed; never replace an unreadable ledger.
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            _require(isinstance(self.state, dict) and set(self.state) == {"lease", "actions"} and
                     isinstance(self.state["actions"], dict) and len(self.state["actions"]) <= 4096,
                     "ledger_invalid", "Invalid ownership ledger")
            lease = self.state["lease"]
            if lease is not None:
                _require(isinstance(lease, dict) and {"identity", "principal", "session_id", "token_hash", "policy",
                         "runtime_values", "lease_seconds", "frame_max_age_s", "expires_at"} == set(lease),
                         "ledger_invalid", "Invalid lease ledger")
                _require(isinstance(lease["identity"], dict) and set(lease["identity"]) == set(IDENTITY_FIELDS) and
                         isinstance(lease["principal"], str) and bool(lease["principal"]) and
                         isinstance(lease["token_hash"], str) and re.fullmatch(r"[0-9a-f]{64}", lease["token_hash"]) and
                         type(lease["expires_at"]) in (int, float) and math.isfinite(lease["expires_at"]) and
                         type(lease["lease_seconds"]) in (int, float) and 30 <= lease["lease_seconds"] <= 1800 and
                         type(lease["frame_max_age_s"]) in (int, float) and 1 <= lease["frame_max_age_s"] <= 600,
                         "ledger_invalid", "Invalid lease ledger")
                for value in [lease["session_id"], *lease["identity"].values()]:
                    _id(value)
                validate_policy(lease["policy"])
                _require(isinstance(lease["runtime_values"], dict) and
                         lease["runtime_values"].keys() <= set(lease["policy"]["runtime_value_keys"]) and
                         all(isinstance(v, str) and len(v) <= 4096 and "\x00" not in v for v in lease["runtime_values"].values()),
                         "ledger_invalid", "Invalid lease values")
            for action_id, record in self.state["actions"].items():
                _id(action_id)
                _require(isinstance(record, dict) and {"action_id", "payload_sha256", "session_id", "status"} <= record.keys() and
                         record["action_id"] == action_id and record["status"] in {"in_progress", "ambiguous", "completed", "failed"} and
                         isinstance(record["payload_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", record["payload_sha256"]),
                         "ledger_invalid", "Invalid action ledger")
                _id(record["session_id"])
                _require(record["status"] not in {"in_progress", "ambiguous"} or
                         (lease is not None and record["session_id"] == lease["session_id"]),
                         "ledger_invalid", "Unresolved action has no owner")
                if record["status"] == "in_progress":
                    record["status"] = "ambiguous"
            self._persist()

    def _persist(self):
        temporary = self.root / (".computer-use-" + uuid4().hex)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with temporary.open("x", encoding="utf-8") as output:
                os.chmod(temporary, 0o600)
                json.dump(self.state, output, separators=(",", ":"), allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except OSError:
            self.faulted = True
            raise ComputerUseError("ledger_unavailable", "Durable ownership storage unavailable") from None
        finally:
            temporary.unlink(missing_ok=True)

    def _unresolved(self):
        return any(r["status"] in {"in_progress", "ambiguous"} for r in self.state["actions"].values())

    def _expire(self):
        lease = self.state["lease"]
        if lease and time.time() > lease["expires_at"] and not (self.busy or self._unresolved()):
            self.state["lease"] = None
            self.observation = None
            self._persist()

    @contextmanager
    def legacy_mutation(self):
        with self.lock:
            self._expire()
            _require(not self.faulted and not self.state["lease"] and not self.busy,
                     "desktop_owned", "Desktop is reserved by computer use")
            self.legacy_active += 1
        try:
            yield
        finally:
            with self.lock:
                self.legacy_active -= 1

    def _credentials(self, payload, principal):
        lease = self.state["lease"]
        token = payload.get("lease_token")
        _require(lease and isinstance(token, str) and len(token) <= 512 and
                 secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), lease["token_hash"]) and
                 principal == lease["principal"] and payload.get("session_id") == lease["session_id"] and
                 all(payload.get(k) == lease["identity"][k] for k in IDENTITY_FIELDS),
                 "lease_denied", "Lease identity or credential does not match")
        return lease

    def _response(self, record):
        receipt = {k: deepcopy(v) for k, v in record.items() if k not in {"session_id"}}
        return {"ok": record["status"] == "completed", "status": record["status"], "receipt": receipt}

    def handle(self, operation: str, payload: dict, principal: str) -> dict:
        try:
            return self._handle(operation, payload, principal)
        except ComputerUseError as error:
            return {"ok": False, "status": "blocked", "failure_code": error.code, "message": str(error)}
        except (TypeError, ValueError, KeyError, OverflowError):
            return {"ok": False, "status": "blocked", "failure_code": "invalid_request"}

    def _handle(self, operation, payload, principal):
        _require(operation in OPERATIONS and isinstance(payload, dict) and isinstance(principal, str) and bool(principal),
                 "invalid_request", "Invalid authenticated operation")
        with self.lock:
            self._expire()
            if operation == "acquire":
                _require(not self.faulted and not self.state["lease"] and not self.busy and not self.legacy_active
                         and not self._unresolved(), "desktop_owned", "Desktop is reserved")
                if hasattr(self.adapter, "check_available"):
                    self.adapter.check_available()
                identity = {k: _id(payload.get(k)) for k in IDENTITY_FIELDS}
                policy = validate_policy(payload.get("policy"))
                _require(not policy["mask_regions"] or not (policy["program_ids"] or
                         any(check["type"] == "program" for check in policy["postconditions"])),
                         "masking_program_unsupported", "Masked sessions cannot use legacy program capture paths")
                values = payload.get("runtime_values", {})
                _require(isinstance(values, dict) and values.keys() <= set(policy["runtime_value_keys"]) and
                         all(isinstance(v, str) and len(v) <= 4096 and "\x00" not in v for v in values.values()),
                         "invalid_request", "Invalid host runtime values")
                seconds, age = payload.get("lease_seconds", 300), payload.get("frame_max_age_s", 150)
                _require(type(seconds) in (int, float) and 30 <= seconds <= 1800 and
                         type(age) in (int, float) and 1 <= age <= 600, "invalid_request", "Invalid lease limits")
                token, session = secrets.token_urlsafe(32), uuid4().hex
                self.state["lease"] = {"identity": identity, "principal": principal, "session_id": session,
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(), "policy": policy,
                    "runtime_values": deepcopy(values), "lease_seconds": seconds, "frame_max_age_s": age,
                    "expires_at": time.time() + seconds}
                self._persist()
                return {"ok": True, "status": "acquired", "worker_id": self.worker_id,
                        "session_id": session, "lease_token": token}
            lease = self._credentials(payload, principal)
            if operation == "status":
                action_id = _id(payload.get("action_id"))
                record = self.state["actions"].get(action_id)
                _require(not record or record["session_id"] == lease["session_id"], "action_conflict", "Action belongs to another session")
                lease["expires_at"] = time.time() + lease["lease_seconds"]
                self._persist()
                return self._response(record) if record else {"ok": True, "status": "not_found"}
            if operation == "act":
                action_id = _id(payload.get("action_id"))
                digest = action_payload_sha256(payload)
                _require(digest == payload.get("payload_sha256"), "payload_mismatch", "Action hash does not match")
                record = self.state["actions"].get(action_id)
                if record:
                    _require(record["payload_sha256"] == digest and record["session_id"] == lease["session_id"],
                             "action_conflict", "Action ID was already used")
                    lease["expires_at"] = time.time() + lease["lease_seconds"]
                    self._persist()
                    return self._response(record)
            _require(not self.faulted and not self.busy and not self._unresolved(),
                     "desktop_busy", "Desktop has an executing or unresolved action")
            if operation == "release":
                self.state["lease"] = None
                self.observation = None
                self._persist()
                return {"ok": True, "status": "released"}
            self.busy = True
        # Never hold the worker mutex during a physical program or image capture.
        try:
            context = {**deepcopy(lease["identity"]), "session_id": lease["session_id"],
                       "runtime_values": deepcopy(lease["runtime_values"]), "policy": deepcopy(lease["policy"])}
            if operation == "observe":
                observation = self._capture(lease)
                with self.lock:
                    self.observation = observation
                result = {"ok": True, "status": "observed", "observation": deepcopy(observation)}
            elif operation == "verify":
                result = {"ok": True, "status": "verified", "evidence": self.adapter.verify(lease["policy"], context)}
                result["ok"] = result["evidence"].get("ok") is True
                if not result["ok"]:
                    result["status"] = "failed"
            else:
                observation = self.observation
                _require(observation and payload.get("observation_id") == observation["observation_id"],
                         "stale_observation", "Observation is no longer current")
                captured = datetime.fromisoformat(observation["captured_at"].replace("Z", "+00:00")).timestamp()
                _require(0 <= time.time() - captured <= lease["frame_max_age_s"], "stale_observation", "Observation has expired")
                current = self._capture(lease)
                _require(all(current.get(k) == observation.get(k) for k in
                             ("window_id", "window_title", "window_rect", "desktop_rect", "image_width", "image_height", "dpi")),
                         "window_changed", "Application geometry or identity changed")
                validated = validate_action(payload["action"], lease["policy"], current, lease["runtime_values"])
                context["observation"] = current
                context["action_id"] = action_id
                with self.lock:
                    _require(len(self.state["actions"]) < 4096, "ledger_full", "Action ledger requires operator archival")
                    record = {"action_id": action_id, "payload_sha256": digest, "session_id": lease["session_id"], "status": "in_progress"}
                    self.state["actions"][action_id] = record
                    self._persist()  # MUST precede any input; failed fsync means zero effects.
                    self.observation = None
                try:
                    receipt = self.adapter.execute(validated, context)
                    record["status"] = "completed" if receipt.get("ok") is True else "failed"
                    record["result"] = receipt
                except ComputerUseError as error:
                    record["status"] = "ambiguous"
                    record["failure_code"] = error.code
                except Exception:
                    record["status"] = "ambiguous"
                    record["failure_code"] = "effect_unknown"
                with self.lock:
                    self._persist()
                result = self._response(record)
            with self.lock:
                lease["expires_at"] = time.time() + lease["lease_seconds"]
                self._persist()
            return result
        finally:
            with self.lock:
                self.busy = False

    def _capture(self, lease):
        observation = self.adapter.capture(lease["policy"])
        observation.update(observation_id=uuid4().hex, worker_id=self.worker_id, session_id=lease["session_id"])
        _validate_observation(observation, lease["policy"])
        return observation


@contextmanager
def native_dpi_context(api=None):
    """Scope per-monitor-v2 to this worker thread; restore even after failure."""
    if api is None:
        _require(os.name == "nt", "native_context_unavailable", "Windows native DPI context is required")
        import ctypes
        api = ctypes.WinDLL("user32", use_last_error=True)
        try:
            api.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            api.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            api.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            api.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        except AttributeError:
            raise ComputerUseError("native_context_unavailable", "Native DPI APIs are unavailable") from None
    _require(all(hasattr(api, name) for name in ("SetThreadDpiAwarenessContext", "GetThreadDpiAwarenessContext", "GetAwarenessFromDpiAwarenessContext")),
             "native_context_unavailable", "Native DPI APIs are unavailable")
    previous = api.SetThreadDpiAwarenessContext(-4)
    _require(bool(previous), "native_context_unavailable", "Cannot enter per-monitor DPI context")
    try:
        _require(api.GetAwarenessFromDpiAwarenessContext(api.GetThreadDpiAwarenessContext()) == 2,
                 "native_context_unavailable", "Native DPI context verification failed")
        yield
    finally:
        _require(bool(api.SetThreadDpiAwarenessContext(previous)), "native_context_unavailable", "Cannot restore native DPI context")


def _windows_context():
    """Read physical native bounds; never infer focus from a screenshot."""
    _require(os.name == "nt", "native_context_unavailable", "Windows native focus/DPI context is required")
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _require(user.GetAwarenessFromDpiAwarenessContext(user.GetThreadDpiAwarenessContext()) == 2,
             "native_context_unavailable", "Per-monitor native DPI context is required")
    hwnd = user.GetForegroundWindow()
    _require(bool(hwnd), "native_context_unavailable", "Foreground window is unavailable")
    rect = wintypes.RECT()
    _require(bool(user.GetWindowRect(hwnd, ctypes.byref(rect))), "native_context_unavailable", "Window bounds unavailable")
    title = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
    user.GetWindowTextW(hwnd, title, len(title))
    dpi = user.GetDpiForWindow(hwnd)
    _require(dpi > 0, "native_context_unavailable", "Window DPI unavailable")
    class GUIThreadInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD)] + [
            (name, wintypes.HWND) for name in ("hwndActive", "hwndFocus", "hwndCapture", "hwndMenuOwner", "hwndMoveSize", "hwndCaret")] + [("rcCaret", wintypes.RECT)]
    info = GUIThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    thread_id = user.GetWindowThreadProcessId(hwnd, None)
    focus = wintypes.RECT()
    focus_rect = None
    if user.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus and user.GetWindowRect(info.hwndFocus, ctypes.byref(focus)):
        focus_rect = [focus.left, focus.top, focus.right - focus.left, focus.bottom - focus.top]
    bounds = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
    _require(all(0 < size <= 16384 for size in bounds[2:]), "native_context_unavailable", "Invalid native window bounds")
    return {"window_id": str(hwnd), "window_title": title.value, "window_rect": bounds,
            "desktop_rect": list(bounds), "focus_rect": focus_rect, "dpi": dpi}


class NativeDesktopAdapter:
    """OS capture/dispatch and existing registered-program evidence paths."""
    def __init__(self, server, native_context=None):
        self.server = server
        self.native_context = native_context or _windows_context
        self.native_scope = nullcontext if native_context is not None else native_dpi_context

    def check_available(self):
        _require(self.server.RECORDING_MANAGER.status().get("status") == "idle",
                 "desktop_busy", "An existing desktop recording is active")

    def _image(self, policy):
        gui, error = self.server.get_pyautogui()
        _require(gui is not None, "native_context_unavailable", "Desktop capture unavailable")
        native = self.native_context()
        _require(native["window_title"] == policy["application"]["window_title"], "window_mismatch", "Application window is not foreground")
        image = gui.screenshot(region=tuple(native["window_rect"])).convert("RGB")
        _require(list(image.size) == native["window_rect"][2:], "native_context_unavailable", "Native capture dimensions differ")
        after = self.native_context()
        _require(all(native[k] == after[k] for k in ("window_id", "window_rect", "dpi")),
                 "window_changed", "Window changed during capture")
        return gui, native, image

    @staticmethod
    def _crop(image, region):
        x, y, w, h = region
        _require(all(type(v) is int for v in region) and x >= 0 and y >= 0 and w > 0 and h > 0 and
                 x + w <= image.width and y + h <= image.height, "region_out_of_bounds", "Native image region is invalid")
        return image.crop((x, y, x + w, y + h))

    def capture(self, policy):
        with self.native_scope():
            return self._capture(policy)

    def _capture(self, policy):
        _, native, image = self._image(policy)
        anchors = {key: hashlib.sha256(self._crop(image, target["anchor"]["region"]).tobytes()).hexdigest()
                   for key, target in policy["targets"].items()}
        for region in policy["mask_regions"]:
            self._crop(image, region)  # validate prior to masking
            x, y, w, h = region
            image.paste((0, 0, 0), (x, y, x + w, y + h))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        png = stream.getvalue()
        return {**{k: native[k] for k in ("window_id", "window_title", "window_rect", "desktop_rect")},
                "captured_at": datetime.now(timezone.utc).isoformat(), "image_width": image.width,
                "image_height": image.height, "image_base64": base64.b64encode(png).decode(),
                "image_sha256": hashlib.sha256(png).hexdigest(), "anchor_hashes": anchors, "dpi": native["dpi"]}

    def execute(self, action, context):
        with self.native_scope():
            return self._execute(action, context)

    def _execute(self, action, context):
        policy, previous = context["policy"], context["observation"]
        gui, native, image = self._image(policy)
        _require(all(native[k] == previous[k] for k in ("window_id", "window_rect", "desktop_rect", "dpi")),
                 "window_changed", "Window changed before dispatch")
        kind = action["type"]
        if kind == "invoke_program":
            _require(not policy["mask_regions"], "masking_program_unsupported", "Masked sessions cannot run legacy programs")
            return self.server._execute({**{k: context[k] for k in IDENTITY_FIELDS},
                "program_id": action["program_id"], "sequence_id": context["action_id"],
                "runtime_values": context["runtime_values"]})
        target = policy["targets"][action["target_id"]]
        _require(hashlib.sha256(self._crop(image, target["anchor"]["region"]).tobytes()).hexdigest() == target["anchor"]["sha256"],
                 "anchor_mismatch", "Target changed before dispatch")
        # Native focus and geometry are read again immediately before keyboard input.
        current = self.native_context()
        _require(all(current[k] == native[k] for k in ("window_id", "window_rect", "dpi")),
                 "window_changed", "Window changed before dispatch")
        if kind in {"press", "hotkey", "write"}:
            focus = current.get("focus_rect")
            wx, wy, _, _ = current["window_rect"]
            x, y, w, h = target["region"]
            _require(focus and focus[2] > 0 and focus[3] > 0 and wx + x <= focus[0] and wy + y <= focus[1] and
                     focus[0] + focus[2] <= wx + x + w and focus[1] + focus[3] <= wy + y + h,
                     "focus_outside_target", "Native focused control is outside declared target")
        if kind == "click":
            gui.click(action["x"], action["y"])
        elif kind == "double_click":
            gui.doubleClick(action["x"], action["y"], interval=0.1)
        elif kind == "scroll":
            gui.scroll(action["amount"], x=action["x"], y=action["y"])
        elif kind == "press":
            gui.press(action["key"])
        elif kind == "hotkey":
            gui.hotkey(*action["keys"])
        elif kind == "write":
            gui.write(action["text"], interval=0.01)
        else:
            raise ComputerUseError("invalid_action", "Unsupported input")
        return {"ok": True}

    def verify(self, policy, context):
        checks = []
        for check in policy["postconditions"]:
            if check["type"] == "image":
                with self.native_scope():
                    _, _, image = self._image(policy)
                checks.append({"type": "image", "ok": hashlib.sha256(self._crop(image, check["region"]).tobytes()).hexdigest() == check["sha256"]})
                continue
            program = self.server._all_programs().get(check["program_id"], {})
            _require(not policy["mask_regions"], "masking_program_unsupported", "Masked sessions cannot run legacy evidence programs")
            sequence = program.get("sequence", [])
            # Introspect actual registry contents, not the policy's read_only claim.
            read_actions = {"health", "log", "wait", "assert_visible", "assert_text", "pixel_matches_color", "wait_for_file", "wait_until_image", "wait_until_text"}
            assertions = {"assert_visible", "assert_text", "pixel_matches_color", "wait_for_file", "wait_until_image", "wait_until_text"}
            _require(program.get("enabled") is not False and (program.get("managed_by") != "atr_equipment_skill" or program.get("integrity_ok") is True)
                     and isinstance(sequence, list) and 1 <= len(sequence) <= 100 and
                     all(isinstance(step, dict) and step.get("action") in read_actions for step in sequence) and
                     any(step["action"] in assertions for step in sequence), "mutating_evidence", "Registered evidence is not a read-only assertion program")
            gui, _ = self.server.get_pyautogui()
            _require(gui is not None, "native_context_unavailable", "Evidence desktop unavailable")
            trace = []
            screen_evidence = any(step["action"] in assertions - {"wait_for_file"} for step in sequence)
            with self.native_scope() if screen_evidence else nullcontext():
                if screen_evidence:
                    native = self.native_context()
                    _require(native["window_title"] == policy["application"]["window_title"],
                             "window_mismatch", "Evidence application window is not foreground")
                result = self.server._execute_protocol_sequence(gui, program_id=check["program_id"],
                    payload={"sequence": deepcopy(sequence), "locators": deepcopy(program.get("locators", {})),
                             "require_screen_assertions": True, "runtime_values": context.get("runtime_values", {})},
                    run_id=context["run_id"], specimen_id=context["specimen_id"], trace=trace)
                if screen_evidence:
                    after = self.native_context()
                    _require(all(native[k] == after[k] for k in ("window_id", "window_title", "window_rect", "desktop_rect", "dpi")),
                             "window_changed", "Native application context changed during evidence verification")
            checks.append({"type": "program", "program_id": check["program_id"],
                           "ok": result.get("ok") is True and all(step.get("status") == "ok" for step in trace)})
        return {"ok": bool(checks) and all(c["ok"] for c in checks), "checks": checks}
