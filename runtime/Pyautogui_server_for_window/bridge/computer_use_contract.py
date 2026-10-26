"""Portable, fail-closed computer-use contracts (Python standard library only).

The caller owns lease/session identity, observation freshness and OS focus. In
particular, press/hotkey/write require a worker-side focused-control bounds check
inside the declared target immediately before dispatch. Policy validation cannot
prove focus or that an evidence program's actual registry implementation is read-only.
Image SHA-256 covers PNG bytes; anchor/postcondition SHA-256 covers RGB pixels.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
import struct


DECISION_SCHEMA = "ax4lab.equipment_computer_use.decision.v1"
POLICY_SCHEMA = "ax4lab.equipment_computer_use.policy.v1"
_GUI_ACTIONS = {"click", "double_click", "scroll", "press", "hotkey", "write"}
_POINTER_ACTIONS = {"click", "double_click", "scroll"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_KEY = re.compile(r"[a-z0-9_]{1,32}\Z")


class ComputerUseError(ValueError):
    """Stable machine-readable code and deliberately non-secret error message."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _require(condition, code="invalid_contract", message="Invalid computer-use contract"):
    if not condition:
        raise ComputerUseError(code, message)


def _object(value, required, optional=()):
    _require(isinstance(value, dict))
    _require(set(required) <= value.keys() and value.keys() <= set(required) | set(optional))


def _number(value, low, high, *, integer=False):
    _require(type(value) in ((int,) if integer else (int, float)))
    _require(low <= value <= high and math.isfinite(value))
    return value


def _text(value, maximum=128, *, empty=False):
    _require(isinstance(value, str) and (empty or bool(value.strip())) and len(value) <= maximum)
    return value


def _identifier(value):
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None)


def _hash(value):
    _require(isinstance(value, str) and _HASH.fullmatch(value) is not None)


def _list(value, maximum=256, *, nonempty=False):
    _require(isinstance(value, list) and len(value) <= maximum and (not nonempty or bool(value)))


def _strings(value, *, keys=False):
    _list(value)
    for item in value:
        if keys:
            _require(isinstance(item, str) and _KEY.fullmatch(item) is not None)
        else:
            _identifier(item)
    _require(len(value) == len(set(value)))


def _rectangle(value, *, desktop=False):
    _require(isinstance(value, list) and len(value) == 4)
    for coordinate in value[:2]:
        _number(coordinate, -32768 if desktop else 0, 32768)
    for size in value[2:]:
        _number(size, 0, 32768)
        _require(size > 0)
    return value


def _overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _inside(x, y, rectangle):
    return rectangle[0] <= x < rectangle[0] + rectangle[2] and rectangle[1] <= y < rectangle[1] + rectangle[3]


def normalize_settings(raw: dict | None) -> dict:
    """Normalize only owned settings; an absent mode always stays skill_flow."""
    if raw is None:
        raw = {}
    _require(isinstance(raw, dict), "invalid_settings", "Settings must be an object")
    mode = raw.get("execution_mode", "skill_flow")
    _require(mode in ("skill_flow", "computer_use"), "invalid_settings", "Unknown execution mode")
    config = raw.get("computer_use", {})
    _object(config, (), ("max_turns", "request_timeout_s", "frame_max_age_s"))
    turns = _number(config.get("max_turns", 64), 1, 256, integer=True)
    timeout = _number(config.get("request_timeout_s", 120), 1, 300)
    age = _number(config.get("frame_max_age_s", 150), 1, 600)
    return {"execution_mode": mode, "computer_use": {
        "max_turns": turns, "request_timeout_s": float(timeout), "frame_max_age_s": float(age)}}


def validate_program_hashes(policy: dict, raw: dict | None) -> dict:
    """Bind every mutating/evidence program to a host-validated deployed hash."""
    expected = set(policy["program_ids"]) | {check["program_id"] for check in policy["postconditions"] if check["type"] == "program"}
    value = {} if raw is None else raw
    _require(isinstance(value, dict) and set(value) == expected,
             "program_hash_binding_missing", "Every declared program requires its validated package hash")
    for program_id, digest in value.items():
        _identifier(program_id)
        _hash(digest)
    return deepcopy(value)


def validate_policy(raw: dict) -> dict:
    """Validate declared permissions. All rectangles are window-relative pixels."""
    _object(raw, ("schema", "application", "targets", "protected_regions", "program_ids",
                  "runtime_value_keys", "postconditions", "mask_regions"))
    _require(raw["schema"] == POLICY_SCHEMA)
    _object(raw["application"], ("window_title",))
    _text(raw["application"]["window_title"], 512)
    for field in ("program_ids", "runtime_value_keys"):
        _strings(raw[field])
    for field in ("protected_regions", "mask_regions"):
        _list(raw[field])
        for region in raw[field]:
            _rectangle(region)
    _require(isinstance(raw["targets"], dict) and len(raw["targets"]) <= 256)
    visible_regions = []
    for target_id, target in raw["targets"].items():
        _identifier(target_id)
        _object(target, ("region", "actions", "anchor"), ("allowed_keys", "allowed_chords"))
        _rectangle(target["region"])
        _strings(target["actions"])
        _require(bool(target["actions"]) and set(target["actions"]) <= _GUI_ACTIONS)
        _object(target["anchor"], ("region", "sha256"))
        _rectangle(target["anchor"]["region"])
        _hash(target["anchor"]["sha256"])
        _require(not any(_overlaps(target["region"], region) for region in raw["protected_regions"]),
                 "protected_region", "Target overlaps a protected region")
        visible_regions.extend((target["region"], target["anchor"]["region"]))
        if "allowed_keys" in target:
            _strings(target["allowed_keys"], keys=True)
        if "press" in target["actions"]:
            _require(bool(target.get("allowed_keys")))
        if "allowed_chords" in target:
            _list(target["allowed_chords"])
            for chord in target["allowed_chords"]:
                _strings(chord, keys=True)
                _require(2 <= len(chord) <= 4)
        if "hotkey" in target["actions"]:
            _require(bool(target.get("allowed_chords")))
    _list(raw["postconditions"], nonempty=True)
    for check in raw["postconditions"]:
        _require(isinstance(check, dict))
        if check.get("type") == "image":
            _object(check, ("type", "region", "sha256"))
            _rectangle(check["region"])
            _hash(check["sha256"])
            visible_regions.append(check["region"])
        else:
            _object(check, ("type", "program_id", "read_only"))
            _require(check["type"] == "program" and check["read_only"] is True)
            _identifier(check["program_id"])
            _require(check["program_id"] not in raw["program_ids"], "mutating_evidence",
                     "Evidence programs must be separate read-only checks")
    _require(not any(_overlaps(region, mask) for region in visible_regions for mask in raw["mask_regions"]),
             "masked_region", "Permission or evidence overlaps a masked region")
    return deepcopy(raw)


def _action_shape(action):
    _require(isinstance(action, dict))
    kind = action.get("type")
    _require(isinstance(kind, str) and kind in _GUI_ACTIONS | {"invoke_program"},
             "invalid_action", "Unknown action type")
    required = {"type", "program_id"} if kind == "invoke_program" else {"type", "target_id"}
    if kind in _POINTER_ACTIONS:
        required |= {"x", "y"}
    required |= {"scroll": {"amount"}, "press": {"key"}, "hotkey": {"keys"}, "write": {"value_key"}}.get(kind, set())
    _object(action, required)
    _identifier(action["program_id"] if kind == "invoke_program" else action["target_id"])
    if kind in _POINTER_ACTIONS:
        _number(action["x"], 0, 32768)
        _number(action["y"], 0, 32768)
    if kind == "scroll":
        _number(action["amount"], -10, 10, integer=True)
        _require(action["amount"] != 0)
    if kind == "press":
        _strings([action["key"]], keys=True)
    if kind == "hotkey":
        _strings(action["keys"], keys=True)
        _require(2 <= len(action["keys"]) <= 4)
    if kind == "write":
        _identifier(action["value_key"])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "invalid_json", "Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ComputerUseError("invalid_json", "Non-finite JSON number")


def parse_decision(text: str, observation_id: str) -> dict:
    """Accept exactly one bounded strict JSON decision for this observation."""
    _text(text, 16384)
    _identifier(observation_id)
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise ComputerUseError("invalid_json", "Malformed decision JSON") from None
    _require(isinstance(value, dict))
    kind = value.get("kind")
    _require(isinstance(kind, str) and kind in ("act", "wait", "complete", "needs_operator"))
    required = {"schema", "observation_id", "kind", "reason"}
    required |= {"act": {"action"}, "wait": {"seconds"}}.get(kind, set())
    _object(value, required)
    _require(value["schema"] == DECISION_SCHEMA)
    _require(value["observation_id"] == observation_id, "stale_observation", "Observation ID does not match")
    _text(value["reason"], 512, empty=True)
    if kind == "act":
        _action_shape(value["action"])
    elif kind == "wait":
        _number(value["seconds"], 0, 10)
    return value


def decision_json_schema() -> dict:
    """Provider guidance only: local strict parsing is always authoritative."""
    identifier = {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,128}(?![\\s\\S])"}
    key = {"type": "string", "pattern": "^[a-z0-9_]{1,32}(?![\\s\\S])"}
    variants = []
    for kind in sorted(_GUI_ACTIONS | {"invoke_program"}):
        properties = {"type": {"const": kind}}
        properties["program_id" if kind == "invoke_program" else "target_id"] = identifier
        if kind in _POINTER_ACTIONS:
            properties.update({axis: {"type": "number", "minimum": 0, "maximum": 32768} for axis in ("x", "y")})
        if kind == "scroll":
            properties["amount"] = {"type": "integer", "minimum": -10, "maximum": 10, "not": {"const": 0}}
        if kind == "press": properties["key"] = key
        if kind == "hotkey": properties["keys"] = {"type": "array", "items": key, "minItems": 2, "maxItems": 4, "uniqueItems": True}
        if kind == "write": properties["value_key"] = identifier
        variants.append({"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False})
    decisions = []
    for kind in ("act", "wait", "complete", "needs_operator"):
        properties = {"schema": {"const": DECISION_SCHEMA}, "observation_id": identifier,
                      "kind": {"const": kind}, "reason": {"type": "string", "maxLength": 512}}
        if kind == "act": properties["action"] = {"oneOf": variants}
        if kind == "wait": properties["seconds"] = {"type": "number", "minimum": 0, "maximum": 10}
        decisions.append({"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "oneOf": decisions}


def _validate_observation(obs, policy):
    _require(isinstance(obs, dict))
    fields = {"observation_id", "worker_id", "session_id", "captured_at", "image_width", "image_height",
              "desktop_rect", "window_rect", "window_title", "window_id", "image_sha256", "image_base64", "anchor_hashes"}
    _require(fields <= obs.keys())
    for field in ("observation_id", "worker_id", "session_id"):
        _identifier(obs[field])
    _text(obs["window_id"])
    _text(obs["captured_at"])
    try:
        stamp = datetime.fromisoformat(obs["captured_at"].replace("Z", "+00:00"))
        _require(stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0)
    except ValueError:
        raise ComputerUseError("invalid_observation", "Invalid UTC capture timestamp") from None
    for field in ("image_width", "image_height"):
        _number(obs[field], 1, 16384, integer=True)
    _rectangle(obs["desktop_rect"], desktop=True)
    _rectangle(obs["window_rect"], desktop=True)
    _require(obs["window_title"] == policy["application"]["window_title"], "window_mismatch", "Application window does not match")
    _hash(obs["image_sha256"])
    _text(obs["image_base64"], 64 * 1024 * 1024)
    try:
        png = base64.b64decode(obs["image_base64"], validate=True)
    except (ValueError, binascii.Error):
        raise ComputerUseError("invalid_observation", "Invalid image encoding") from None
    _require(hashlib.sha256(png).hexdigest() == obs["image_sha256"], "image_mismatch", "Image hash does not match")
    _require(len(png) >= 33 and png[:8] == b"\x89PNG\r\n\x1a\n" and png[8:16] == b"\x00\x00\x00\rIHDR",
             "invalid_observation", "Image must be PNG")
    _require(struct.unpack(">II", png[16:24]) == (obs["image_width"], obs["image_height"]),
             "image_mismatch", "Image dimensions do not match")
    # Verify the complete PNG envelope, not just a forgeable IHDR header. Pixel
    # decoding and RGB anchor calculation remain the capturing worker's job.
    offset, has_data, has_end = 8, False, False
    while offset < len(png):
        _require(offset + 12 <= len(png), "invalid_observation", "Truncated PNG chunk")
        size = struct.unpack(">I", png[offset:offset + 4])[0]
        end = offset + 12 + size
        _require(end <= len(png), "invalid_observation", "Truncated PNG chunk")
        kind = png[offset + 4:offset + 8]
        crc = struct.unpack(">I", png[end - 4:end])[0]
        _require(binascii.crc32(png[offset + 4:end - 4]) == crc,
                 "invalid_observation", "PNG checksum mismatch")
        has_data = has_data or kind == b"IDAT"
        if kind == b"IEND":
            _require(size == 0 and end == len(png), "invalid_observation", "Invalid PNG end")
            has_end = True
        offset = end
    _require(has_data and has_end, "invalid_observation", "Incomplete PNG image")
    _require(isinstance(obs["anchor_hashes"], dict))
    for target_id, digest in obs["anchor_hashes"].items():
        _identifier(target_id)
        _hash(digest)
    regions = policy["protected_regions"] + policy["mask_regions"]
    regions += [region for target in policy["targets"].values() for region in (target["region"], target["anchor"]["region"])]
    regions += [check["region"] for check in policy["postconditions"] if check["type"] == "image"]
    width, height = obs["window_rect"][2:]
    _require(all(x + w <= width and y + h <= height for x, y, w, h in regions),
             "region_out_of_bounds", "Policy region exceeds application window")


def validate_action(action, policy, observation, runtime_values) -> dict:
    """Return a dispatch copy: desktop x/y and host-resolved text for write.

    desktop_rect is the native desktop rectangle represented by the image;
    window_rect is the native application bounds (both [x,y,width,height]).
    Coordinates are half-open; floor rounding never extends target authority.
    """
    _action_shape(action)
    policy = validate_policy(policy)
    _validate_observation(observation, policy)
    _require(isinstance(runtime_values, dict) and runtime_values.keys() <= set(policy["runtime_value_keys"]),
             "unknown_runtime_value", "Runtime value is not declared")
    for value in runtime_values.values():
        _text(value, 4096, empty=True)
        _require("\x00" not in value)
    result = deepcopy(action)
    kind = action["type"]
    if kind == "invoke_program":
        _require(action["program_id"] in policy["program_ids"], "permission_denied", "Program is not declared")
        return result
    target = policy["targets"].get(action["target_id"])
    _require(target is not None and kind in target["actions"], "permission_denied", "Target action is not declared")
    _require(observation["anchor_hashes"].get(action["target_id"]) == target["anchor"]["sha256"],
             "anchor_mismatch", "Target anchor is missing or changed")
    if kind in _POINTER_ACTIONS:
        _require(action["x"] < observation["image_width"] and action["y"] < observation["image_height"],
                 "coordinate_out_of_bounds", "Pointer exceeds image bounds")
        dx, dy, dw, dh = observation["desktop_rect"]
        x = dx + action["x"] * dw / observation["image_width"]
        y = dy + action["y"] * dh / observation["image_height"]
        wx, wy, _, _ = observation["window_rect"]
        for px, py in ((x, y), (math.floor(x), math.floor(y))):
            _require(_inside(px, py, observation["window_rect"]) and _inside(px - wx, py - wy, target["region"]),
                     "coordinate_out_of_bounds", "Pointer is outside declared target")
        result.update(x=math.floor(x), y=math.floor(y))
    if kind == "press":
        _require(action["key"] in target["allowed_keys"], "permission_denied", "Key is not declared")
    if kind == "hotkey":
        _require(action["keys"] in target["allowed_chords"], "permission_denied", "Chord is not declared")
    if kind == "write":
        _require(action["value_key"] in runtime_values, "unknown_runtime_value", "Runtime text value is missing")
        result["text"] = runtime_values[action["value_key"]]
    return result
