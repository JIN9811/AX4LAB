"""Fail-closed decisions and permissions, using only synthetic desktop metadata."""
import base64
from copy import deepcopy
import hashlib
import importlib
import json
import struct

import pytest


@pytest.fixture
def contract():
    class Contract:
        def __getattr__(self, attribute):
            name = "Pyautogui_server_for_window.bridge.computer_use_contract"
            assert importlib.util.find_spec(name) is not None, "portable contract is missing"
            return getattr(importlib.import_module(name), attribute)
    return Contract()


def policy():
    return {
        "schema": "ax4lab.equipment_computer_use.policy.v1",
        "application": {"window_title": "Synthetic demo"},
        "targets": {"button": {
            "region": [0, 0, 1900, 1000],
            "actions": ["click", "double_click", "scroll", "press", "hotkey", "write"],
            "anchor": {"region": [0, 0, 20, 20], "sha256": "a" * 64},
            "allowed_keys": ["enter"], "allowed_chords": [["ctrl", "s"]],
        }},
        "protected_regions": [[1900, 1000, 20, 20]],
        "mask_regions": [[1900, 1020, 20, 20]],
        "program_ids": ["demo_start"], "runtime_value_keys": ["export_path"],
        "postconditions": [{"type": "image", "region": [30, 0, 20, 20], "sha256": "b" * 64}],
    }


def observation():
    # Real tiny compressed PNG payload with synthetic declared 960x540 dimensions.
    import zlib
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 960, 540, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * 2880) * 540)) + chunk(b"IEND", b"")
    return dict(observation_id="obs-1", worker_id="worker", session_id="session",
                captured_at="2026-10-26T00:00:00Z", image_width=960, image_height=540,
                desktop_rect=[100, 50, 1920, 1080], window_rect=[100, 50, 1920, 1080],
                window_title="Synthetic demo", window_id="window-1", image_sha256=hashlib.sha256(png).hexdigest(),
                image_base64=base64.b64encode(png).decode(), anchor_hashes={"button": "a" * 64})


def decision(kind="act", **fields):
    return dict(schema="ax4lab.equipment_computer_use.decision.v1", observation_id="obs-1",
                kind=kind, reason="Synthetic test", **fields)


def test_legacy_settings_defaults(contract):
    for raw in (None, {}, {"vision_link_enabled": True}):
        assert contract.normalize_settings(raw) == {"execution_mode": "skill_flow", "computer_use": {
            "max_turns": 64, "request_timeout_s": 120.0, "frame_max_age_s": 150.0}}


@pytest.mark.parametrize("patch", [
    {"execution_mode": "other"}, {"execution_mode": None}, {"computer_use": None},
    {"computer_use": {"max_turns": True}}, {"computer_use": {"max_turns": 1.5}},
    {"computer_use": {"max_turns": 0}}, {"computer_use": {"max_turns": 257}},
    {"computer_use": {"request_timeout_s": float("nan")}},
    {"computer_use": {"request_timeout_s": True}}, {"computer_use": {"request_timeout_s": 301}},
    {"computer_use": {"frame_max_age_s": 0}}, {"computer_use": {"frame_max_age_s": 601}},
    {"computer_use": {"unknown": 1}},
])
def test_invalid_settings_rejected(contract, patch):
    with pytest.raises(contract.ComputerUseError):
        contract.normalize_settings(patch)


@pytest.mark.parametrize("value", [
    decision(action={"type": "click", "target_id": "button", "x": 480, "y": 270}),
    decision("wait", seconds=0), decision("wait", seconds=10),
    decision("complete"), decision("needs_operator"),
])
def test_four_decision_kinds(contract, value):
    assert contract.parse_decision(json.dumps(value), "obs-1") == value


@pytest.mark.parametrize("text", [
    '{"schema":"x","schema":"y"}', '{"kind":', '{} trailing', '```json\n{}\n```', '[]',
    json.dumps(decision("complete", extra=True)), json.dumps(decision("complete", seconds=0)),
    json.dumps(decision("wait", seconds=True)), json.dumps(decision("wait", seconds=11)),
    json.dumps(decision(action={"type": "click", "target_id": "button", "x": True, "y": 1})),
    json.dumps(decision(action={"type": "click", "target_id": "button", "x": float("nan"), "y": 1})),
    json.dumps(decision(action={"type": "click", "target_id": "button", "x": float("inf"), "y": 1})),
    json.dumps(decision(action={"type": "shell", "command": "anything"})),
    json.dumps(decision(action={"type": "write", "target_id": "button", "text": "model text"})),
    json.dumps(decision(action={"type": "scroll", "target_id": "button", "x": 1, "y": 1, "amount": 0})),
    json.dumps(decision("complete") | {"reason": "x" * 513}),
    json.dumps(decision("complete") | {"observation_id": "older"}),
])
def test_strict_decision_rejection(contract, text):
    with pytest.raises(contract.ComputerUseError) as error:
        contract.parse_decision(text, "obs-1")
    assert error.value.code


def test_schema_describes_valid_and_invalid_decisions(contract):
    import jsonschema
    schema = contract.decision_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    for value in (decision("complete"), decision("wait", seconds=2),
                  decision(action={"type": "invoke_program", "program_id": "demo_start"})):
        jsonschema.validate(value, schema)
    for value in (decision("complete", action={}), decision(action={"type": "click", "x": 1, "y": 2}),
                  decision("wait", seconds=True)):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(value, schema)


def test_mapping_is_native_desktop_and_input_is_unchanged(contract):
    action = {"type": "click", "target_id": "button", "x": 480, "y": 270}
    before = deepcopy(action)
    result = contract.validate_action(action, policy(), observation(), {})
    assert (result["x"], result["y"]) == (1060, 590)
    assert action == before


@pytest.mark.parametrize("x,y", [(960, 1), (1, 540), (-1, 1), (1, -1), (950, 500), (float("nan"), 1), (True, 1)])
def test_image_and_target_bounds_are_half_open(contract, x, y):
    with pytest.raises(contract.ComputerUseError):
        contract.validate_action({"type": "click", "target_id": "button", "x": x, "y": y}, policy(), observation(), {})


@pytest.mark.parametrize("mutation", ["protected", "mask_target", "mask_anchor", "mask_postcondition", "anchor_missing", "negative", "empty", "nan", "unknown_action", "missing_postcondition", "mutating_evidence"])
def test_unsafe_policies_rejected(contract, mutation):
    p = policy()
    if mutation == "protected": p["protected_regions"] = [[1, 1, 10, 10]]
    if mutation == "mask_target": p["mask_regions"] = [[100, 100, 10, 10]]
    if mutation == "mask_anchor":
        p["targets"]["button"]["anchor"]["region"] = [1900, 1020, 10, 10]
    if mutation == "mask_postcondition": p["postconditions"][0]["region"] = [1900, 1020, 10, 10]
    if mutation == "anchor_missing": del p["targets"]["button"]["anchor"]
    if mutation == "negative": p["targets"]["button"]["region"][0] = -1
    if mutation == "empty": p["targets"]["button"]["region"][2] = 0
    if mutation == "nan": p["targets"]["button"]["region"][0] = float("nan")
    if mutation == "unknown_action": p["targets"]["button"]["actions"].append("shell")
    if mutation == "missing_postcondition": p["postconditions"] = []
    if mutation == "mutating_evidence": p["postconditions"] = [{"type": "program", "program_id": "demo_start", "read_only": True}]
    with pytest.raises(contract.ComputerUseError):
        contract.validate_policy(p)


@pytest.mark.parametrize("mutation", ["anchor", "permission", "window", "dimensions", "hash", "base64", "rect", "bounds"])
def test_untrusted_observation_or_missing_permission_rejected(contract, mutation):
    p, obs = policy(), observation()
    if mutation == "anchor": obs["anchor_hashes"] = {}
    if mutation == "permission": p["targets"]["button"]["actions"] = ["write"]
    if mutation == "window": obs["window_title"] = "Other"
    if mutation == "dimensions": obs["image_width"] = 959
    if mutation == "hash": obs["image_sha256"] = "0" * 64
    if mutation == "base64": obs["image_base64"] = "bad!"
    if mutation == "rect": obs["window_rect"] = [100, 50, 0, 1080]
    if mutation == "bounds": p["mask_regions"] = [[3000, 0, 1, 1]]
    with pytest.raises(contract.ComputerUseError):
        contract.validate_action({"type": "click", "target_id": "button", "x": 480, "y": 270}, p, obs, {})


@pytest.mark.parametrize("action", [
    {"type": "press", "target_id": "button", "key": "escape"},
    {"type": "hotkey", "target_id": "button", "keys": ["alt", "f4"]},
    {"type": "write", "target_id": "button", "value_key": "unknown"},
    {"type": "invoke_program", "program_id": "undeclared"},
])
def test_undeclared_keyboard_value_or_program_rejected(contract, action):
    with pytest.raises(contract.ComputerUseError):
        contract.validate_action(action, policy(), observation(), {})


def test_allowed_keys_values_and_programs(contract):
    for action in ({"type": "press", "target_id": "button", "key": "enter"},
                   {"type": "hotkey", "target_id": "button", "keys": ["ctrl", "s"]},
                   {"type": "invoke_program", "program_id": "demo_start"}):
        assert contract.validate_action(action, policy(), observation(), {}) == action
    result = contract.validate_action({"type": "write", "target_id": "button", "value_key": "export_path"},
                                      policy(), observation(), {"export_path": "host-owned.csv"})
    assert result["text"] == "host-owned.csv"
    for values in ({"unexpected": "value"}, {"export_path": True}, {}):
        with pytest.raises(contract.ComputerUseError):
            contract.validate_action({"type": "write", "target_id": "button", "value_key": "export_path"}, policy(), observation(), values)


@pytest.mark.parametrize("action", [
    {"type": "double_click", "target_id": "button", "x": 0, "y": 0},
    {"type": "scroll", "target_id": "button", "x": 0, "y": 0, "amount": -10},
    {"type": "press", "target_id": "button", "key": "enter"},
    {"type": "hotkey", "target_id": "button", "keys": ["ctrl", "s"]},
    {"type": "write", "target_id": "button", "value_key": "export_path"},
    {"type": "invoke_program", "program_id": "demo_start"},
])
def test_each_action_has_strict_parser_and_schema_support(contract, action):
    import jsonschema
    value = decision(action=action)
    assert contract.parse_decision(json.dumps(value), "obs-1")["action"] == action
    jsonschema.validate(value, contract.decision_json_schema())
    invalid = decision(action={**action, "extra": "not allowed"})
    with pytest.raises(contract.ComputerUseError):
        contract.parse_decision(json.dumps(invalid), "obs-1")


def test_read_only_evidence_and_policy_copy(contract):
    p = policy()
    p["postconditions"] = [{"type": "program", "program_id": "read_result", "read_only": True}]
    accepted = contract.validate_policy(p)
    accepted["targets"]["button"]["region"][0] = 999
    assert p["targets"]["button"]["region"][0] == 0
    p["postconditions"][0]["read_only"] = False
    with pytest.raises(contract.ComputerUseError):
        contract.validate_policy(p)


@pytest.mark.parametrize("value", ["x" * 4097, "has\x00nul", 1, None])
def test_resolved_write_text_is_bounded(contract, value):
    with pytest.raises(contract.ComputerUseError):
        contract.validate_action({"type": "write", "target_id": "button", "value_key": "export_path"},
                                 policy(), observation(), {"export_path": value})


def test_negative_desktop_origin_and_half_open_origin_are_supported(contract):
    obs = observation()
    obs["desktop_rect"] = [-1920, -1080, 1920, 1080]
    obs["window_rect"] = [-1920, -1080, 1920, 1080]
    result = contract.validate_action({"type": "click", "target_id": "button", "x": 0, "y": 0}, policy(), obs, {})
    assert (result["x"], result["y"]) == (-1920, -1080)


def test_truncated_png_with_matching_hash_rejected(contract):
    obs = observation()
    png = base64.b64decode(obs["image_base64"])[:33]
    obs.update(image_base64=base64.b64encode(png).decode(), image_sha256=hashlib.sha256(png).hexdigest())
    with pytest.raises(contract.ComputerUseError):
        contract.validate_action({"type": "invoke_program", "program_id": "demo_start"}, policy(), obs, {})
@pytest.mark.parametrize('field', ['observation_id', 'target_id', 'key'])
def test_emitted_schema_rejects_terminal_newline_identifiers(field):
    import jsonschema
    from Pyautogui_server_for_window.bridge.computer_use_contract import decision_json_schema
    value = {'schema': 'ax4lab.equipment_computer_use.decision.v1',
             'observation_id': 'observation1', 'kind': 'act', 'reason': '',
             'action': {'type': 'press', 'target_id': 'button', 'key': 'enter'}}
    owner = value if field == 'observation_id' else value['action']
    owner[field] += '\n'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, decision_json_schema())
