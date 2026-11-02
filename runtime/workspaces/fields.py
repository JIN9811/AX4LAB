"""Validate and normalize declarative workspace field values."""

from copy import deepcopy
import math
import re

from utils.source_identity import attest_module_source

attest_module_source(__file__)


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TYPES = {"number", "integer", "enum", "boolean", "text", "vector"}
_COMMON_KEYS = {"key", "label", "type", "description", "unit", "visible_when"}
_TYPE_KEYS = {
    "number": {"min", "max", "step"},
    "integer": {"min", "max", "step"},
    "enum": {"options"},
    "boolean": set(),
    "text": set(),
    "vector": {"length", "min", "max"},
}


def _number(value, *, integer=False) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if integer:
        return False
    return isinstance(value, float) and math.isfinite(value)


def _validate_bounds(field: dict, *, integer=False):
    key = field["key"]
    lower, upper = field.get("min"), field.get("max")
    if not _number(lower, integer=integer) or not _number(upper, integer=integer):
        raise ValueError(f"{key} bounds must be finite")
    if lower > upper:
        raise ValueError(f"{key} minimum exceeds maximum")
    if "step" in field:
        step = field["step"]
        if not _number(step, integer=integer) or step <= 0:
            raise ValueError(f"{key} step must be finite and positive")


def _validate_field(field: dict) -> dict:
    if not isinstance(field, dict):
        raise ValueError("field metadata must be an object")
    key = field.get("key")
    kind = field.get("type")
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError("invalid field key")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise ValueError(f"invalid field type for {key}")
    if not isinstance(field.get("label"), str) or not field["label"].strip():
        raise ValueError(f"missing field label for {key}")
    unknown = set(field) - _COMMON_KEYS - _TYPE_KEYS[kind]
    if unknown:
        raise ValueError(f"unknown field metadata for {key}: {sorted(unknown)}")
    for optional in ("description", "unit"):
        if optional in field and not isinstance(field[optional], str):
            raise ValueError(f"invalid {optional} for {key}")

    if kind == "number":
        _validate_bounds(field)
    elif kind == "integer":
        _validate_bounds(field, integer=True)
    elif kind == "enum":
        options = field.get("options")
        if (
            not isinstance(options, list)
            or not options
            or not all(isinstance(option, str) and option for option in options)
            or len(set(options)) != len(options)
        ):
            raise ValueError(f"invalid enum options for {key}")
    elif kind == "vector":
        if not _number(field.get("length"), integer=True) or field["length"] <= 0:
            raise ValueError(f"invalid vector length for {key}")
        _validate_bounds(field)
    return field


def _validate_value(field: dict, value):
    key, kind = field["key"], field["type"]
    if kind == "number":
        if not _number(value):
            raise ValueError(f"{key} must be a finite number")
        if not field["min"] <= value <= field["max"]:
            raise ValueError(f"{key} is outside its bounds")
    elif kind == "integer":
        if not _number(value, integer=True):
            raise ValueError(f"{key} must be an integer")
        if not field["min"] <= value <= field["max"]:
            raise ValueError(f"{key} is outside its bounds")
    elif kind == "enum":
        if value not in field["options"]:
            raise ValueError(f"{key} is not an allowed option")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
    elif kind == "text":
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
    elif kind == "vector":
        if not isinstance(value, list) or len(value) != field["length"]:
            raise ValueError(f"{key} must be a vector of length {field['length']}")
        if not all(_number(item) for item in value):
            raise ValueError(f"{key} vector values must be finite numbers")
        if not all(field["min"] <= item <= field["max"] for item in value):
            raise ValueError(f"{key} vector value is outside its bounds")


def _validate_visibility(field: dict, by_key: dict[str, dict]):
    condition = field.get("visible_when")
    if condition is None:
        return
    if not isinstance(condition, dict):
        raise ValueError(f"visible_when for {field['key']} must be an object")
    if set(condition) not in ({"field", "equals"}, {"field", "in"}):
        raise ValueError(f"visible_when for {field['key']} supports only equals or in")
    dependency = condition.get("field")
    if dependency not in by_key or dependency == field["key"]:
        raise ValueError(f"visible_when for {field['key']} references an invalid field")
    if "equals" in condition:
        _validate_value(by_key[dependency], condition["equals"])
    else:
        members = condition["in"]
        if not isinstance(members, list) or not members:
            raise ValueError(f"visible_when membership for {field['key']} must be non-empty")
        for member in members:
            _validate_value(by_key[dependency], member)


def normalize_fields(fields: list[dict], defaults: dict, values: dict) -> dict:
    """Validate field metadata and return defaults overlaid with explicit values."""

    if not isinstance(fields, list) or not isinstance(defaults, dict) or not isinstance(values, dict):
        raise ValueError("fields must be a list and defaults/values must be objects")
    validated = [_validate_field(deepcopy(field)) for field in fields]
    by_key = {field["key"]: field for field in validated}
    if len(by_key) != len(validated):
        raise ValueError("duplicate field key")
    missing = set(by_key) - set(defaults)
    if missing:
        raise ValueError(f"missing default for fields: {sorted(missing)}")
    unknown_defaults = set(defaults) - set(by_key)
    if unknown_defaults:
        raise ValueError(f"unknown defaults: {sorted(unknown_defaults)}")
    unknown_values = set(values) - set(by_key)
    if unknown_values:
        raise ValueError(f"unknown values: {sorted(unknown_values)}")
    for field in validated:
        _validate_visibility(field, by_key)

    normalized = deepcopy(defaults)
    normalized.update(deepcopy(values))
    for field in validated:
        _validate_value(field, normalized[field["key"]])
    return normalized
