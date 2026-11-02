"""Qm auto-save adapter; no screen actions or experiment completion assertions."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path, PureWindowsPath


def collect_qm_raw_csv(bridge, payload: dict) -> dict:
    tool = "equipment.pyautogui.collect_qm_raw_csv"

    def blocked(code, message):
        return bridge._failure(tool=tool, mode=str(payload.get("runtime_mode") or "test"),
                               status="blocked", failure_code=code, message=message)

    if not bridge.config.enabled or payload.get("virtual_bridge_simulation") is True or payload.get("runtime_mode") != "live":
        return blocked("QM_COLLECTION_LIVE_REQUIRED", "Qm collection requires an explicit live data source; no device operation is performed.")
    identity = {}
    for key in ("test_type", "test_no", "sample_no", "run_id", "specimen_id"):
        value = str(payload.get(key) or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
            return blocked("QM_COLLECTION_IDENTITY_REQUIRED", f"Explicit {key} is required.")
        identity[key] = value
    try:
        since = float(payload.get("not_before_unix", 0))
        stable = float(payload.get("stable_for_sec", 2))
        if not math.isfinite(since) or since <= 0 or not math.isfinite(stable) or not .01 <= stable <= 30:
            raise ValueError
    except (ValueError, TypeError):
        return blocked("QM_COLLECTION_START_REQUIRED", "Provide the acquisition start timestamp in Windows clock time and a valid stability interval.")
    precheck = bridge._live_precheck(require_execute=False, payload=payload)
    if precheck:
        return {**precheck, "tool": tool}
    # Freeze the selected worker/token for collection AND existing artifact GETs.
    pinned = bridge.pin_computer_use_transport(payload)
    pinned.config.request_timeout_sec = max(pinned.config.request_timeout_sec, stable + 5)
    settings = pinned._live_get(tool, "/raw-data/settings")
    if not settings.get("ok"):
        return settings
    saved = settings.get("settings") or {}
    expected_template = identity["test_type"] + "_{test_no}_{sample_no}.csv"
    if saved.get("filename_template") != expected_template or not saved.get("directory"):
        return blocked("QM_FILENAME_RULE_MISMATCH", "Saved RAW filename rule does not match the selected Qm test type.")
    expected = PureWindowsPath(saved["directory"]) / expected_template.format(**identity)
    result = pinned._live_post(tool, "/raw-data/collect", {
        **{key: identity[key] for key in ("test_no", "sample_no", "run_id", "specimen_id")},
        "not_before_unix": since, "stable_for_sec": stable,
    })
    if not result.get("ok"):
        return result
    artifacts = [a for a in result.get("output_artifacts", []) if isinstance(a, dict) and a.get("kind") == "utm_csv"]
    receipt = result.get("identity") or {}
    if (len(artifacts) != 1 or any(result.get(k) != identity[k] for k in ("run_id", "specimen_id"))
            or any(str(receipt.get(k)) != identity[k] for k in ("test_no", "sample_no"))):
        return blocked("QM_COLLECTION_IDENTITY_MISMATCH", "Worker receipt does not identify the requested run/specimen/test/sample.")
    artifact = artifacts[0]
    local = str(artifact.get("local_path") or "")
    if PureWindowsPath(artifact.get("windows_path") or "") != expected or not local or not artifact.get("pulled_to_linux"):
        return blocked("QM_COLLECTION_ARTIFACT_MISMATCH", "Exact source CSV was not downloaded.")
    try:
        digest = hashlib.sha256(Path(local).read_bytes()).hexdigest()
    except OSError:
        return blocked("QM_COLLECTION_DOWNLOAD_FAILED", "Downloaded CSV is unavailable.")
    if digest != artifact.get("remote_sha256") or digest != artifact.get("sha256"):
        return blocked("QM_COLLECTION_HASH_MISMATCH", "Downloaded CSV does not match the worker source hash.")
    if not artifact.get("local_parse_ok"):
        return blocked("QM_COLLECTION_PARSE_FAILED", "Downloaded CSV failed the existing measurement validation.")
    binding = {**identity, "identity_source": "qm_exact_filename_and_local_sha256"}
    for item in result.get("output_artifacts", []) + result.get("artifact_records", []):
        if item.get("artifact_id") == artifact.get("artifact_id"):
            item.update(binding)
    result.update(status="data_ready", result_file=local, utm_csv_path=local,
                  program_id=payload.get("program_id"), sequence_id=payload.get("sequence_id"))
    result["data_acquisition"] = {**result.get("data_acquisition", {}), **binding,
        "status": "pulled_to_linux", "save_method": "windows_export_watch",
        "save_attempted_by_agent": False, "save_confirmation_screen_ok": False,
        "artifact_id": artifact["artifact_id"], "linux_path": local,
        "not_before_unix": since, "stable_for_sec": stable}
    return result
